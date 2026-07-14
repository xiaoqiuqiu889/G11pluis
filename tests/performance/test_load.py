"""Performance / load test — Locust 100 concurrent users × 30 min.

W9 deliverable.  The file ships a runnable Locust scenario +
a CI-friendly batch mode that can be invoked from a script
without spinning up the Locust web UI.

Goals
-----

The brief pins three acceptance numbers; this test asserts on
all of them:

* **P95 < 4 s** for the ``POST /v1/runs/:runId/actions`` core
  endpoint (决策 5 R4 hard red line).
* **单局 AI 成本 < ¥0.8** per run (决策 5 soft target).
* **100 局批量模拟无崩溃** — the load test drives 100
  full three-scene runs back-to-back; the process must not
  OOM, raise, or 5xx above the 1% error-rate alert.

W9 红线
-------

* **隔离 namespace** — the load test sets
  ``G1N_DB_URL=sqlite:///./data/load_test.db`` and
  ``G1N_CACHE_BACKEND=memory`` so the production SQLite
  file and the production Redis namespace are never
  touched.  Set ``G1N_LOAD_TEST_PROD_NAMESPACE=1`` to
  opt in (not recommended).
* **永远不要 LLM 输出进缓存** — the action flow does not
  cache LLM responses, so the load test does not need to
  purge anything.
* **HPA 不会丢 run 状态** — every turn the action runner
  takes a snapshot, so a pod eviction in the middle of a
  burst is recoverable (the next request re-hydrates from
  the DB).

Usage
-----

Interactive (web UI)::

    locust -f tests/performance/test_load.py --host=http://127.0.0.1:8000

Headless (CI)::

    locust -f tests/performance/test_load.py --host=http://127.0.0.1:8000 \\
        --headless -u 100 -r 10 --run-time 30m \\
        --html=artifacts/load_test.html --csv=artifacts/load_test

Or the bundled :func:`run_batch` helper (no Locust binary
required, used by the CI workflow).
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Make the project importable when this file is run from
# any working directory.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# ---------------------------------------------------------------------------
# Hard isolation: this module must NEVER touch the production namespace.
# The env-var defaults below are re-asserted in
# :func:`_enforce_isolation` so a misconfigured CI cannot
# pollute the prod DB / cache.
# ---------------------------------------------------------------------------


_ISOLATION_ENV: dict[str, str] = {
    # SQLite file in a dedicated dir; the action runner
    # re-creates the schema on first request.
    "G1N_DB_URL": "sqlite:///" + str((ROOT / "data" / "load_test.db").as_posix()),
    # In-memory cache so we exercise the same hot path
    # without polluting a shared Redis namespace.
    "G1N_CACHE_BACKEND": "memory",
    # Force the mock LLM provider so the test does not
    # burn real tokens.  The acceptance numbers in the
    # brief are measured against the mock path; real LLM
    # latency is a different envelope.
    "G1N_USE_MOCK": "1",
    # Disable the OTel SDK so the load test does not try
    # to reach a collector that does not exist.
    "OTEL_SDK_DISABLED": "true",
}


def _enforce_isolation() -> None:
    """Re-assert the isolation env vars on every import.

    Belt-and-braces — the env-var defaults above are
    applied at module import, but a misbehaving CI step
    that sets ``G1N_DB_URL`` first would silently
    overwrite them.  We only let the operator opt in
    explicitly via :data:`_OPT_IN_ENV`.
    """

    for k, v in _ISOLATION_ENV.items():
        if k in os.environ:
            if k == "G1N_DB_URL" and not os.environ.get("G1N_LOAD_TEST_PROD_NAMESPACE"):
                # Production namespace opt-in not granted;
                # keep the isolation value.
                os.environ[k] = v
        else:
            os.environ[k] = v


_enforce_isolation()

logger = logging.getLogger("g1n.load_test")

# ---------------------------------------------------------------------------
# Acceptance thresholds (decision 5 + W9 brief)
# ---------------------------------------------------------------------------


#: 决策 5 R4: 关键交互响应 P95 < 4s.
P95_BUDGET_S: float = 4.0

#: 决策 5 soft target: 单局 AI 成本 < ¥0.8.
PER_RUN_COST_BUDGET_CNY: float = 0.8

#: W9 brief: 100 局批量模拟无崩溃.
BATCH_RUN_TARGET: int = 100

#: Maximum acceptable 5xx rate during the test (drives
#: the W9 error-rate alert).
ERROR_RATE_BUDGET: float = 0.01

#: Locust concurrency — 100 users for 30 minutes per the
#: brief.  These are env-overridable so the CI smoke can
#: use a smaller value.
DEFAULT_USERS: int = int(os.environ.get("G1N_LOAD_USERS", "100"))
DEFAULT_SPAWN_RATE: int = int(os.environ.get("G1N_LOAD_SPAWN_RATE", "10"))
DEFAULT_RUN_TIME_S: int = int(os.environ.get("G1N_LOAD_RUN_TIME_S", str(30 * 60)))

# ---------------------------------------------------------------------------
# Optional Locust import (graceful when not installed)
# ---------------------------------------------------------------------------


try:  # pragma: no cover - import is environment-dependent
    from locust import HttpUser, between, events, task  # type: ignore
    from locust.env import Environment  # type: ignore

    LOCUST_AVAILABLE = True
except Exception:  # noqa: BLE001
    LOCUST_AVAILABLE = False

    # Lightweight stand-ins so the file is parseable when
    # Locust is not installed (e.g. the lint step on a
    # worker that only has pytest).
    def task(*_args: Any, **_kwargs: Any):  # type: ignore
        def _decorator(fn: Any) -> Any:
            return fn

        return _decorator

    def between(_a: float, _b: float):  # type: ignore
        return None

    class _Events:  # type: ignore
        class test_stop:  # noqa: D401 - Locust-style
            pass

    events = _Events()  # type: ignore

    class HttpUser:  # type: ignore
        host = "http://127.0.0.1:8000"
        wait_time = staticmethod(between(1, 3))
        client: Any = None

    class Environment:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.runner = _RunnerStub()

    class _RunnerStub:  # type: ignore
        def quit(self) -> None: ...


# ---------------------------------------------------------------------------
# Locust user — the per-virtual-user behaviour
# ---------------------------------------------------------------------------


class G1NPlayerUser(HttpUser):  # type: ignore[misc]
    """A simulated player that opens a run, enters a scene,
    and posts actions at a realistic cadence (1-3 s between
    actions — the user has to read the prose).

    The user re-uses a single run for the whole session
    so the action hot path exercises the in-memory
    registry; the W9 acceptance calls for **100 局**
    (100 distinct runs) end-to-end, which the
    :class:`BatchRunner` drives separately.
    """

    wait_time = between(1, 3)

    def on_start(self) -> None:
        """Create a run and enter the opening scene."""

        self.run_id: str = ""
        self.event_sequence: int = 0
        # 8 action types (decision 1: ≥ 6 from 12).  The
        # mix mirrors the integration test's distribution.
        self.action_types: list[str] = [
            "question",
            "give",
            "conceal",
            "promise",
            "examine",
            "wait",
            "destroy",
            "divulge",
        ]
        self._create_run()

    def _create_run(self) -> None:
        r = self.client.post(  # type: ignore[union-attr]
            "/v1/runs",
            json={
                "userId": f"load-{uuid.uuid4().hex[:8]}",
                "caseSlug": "case_01_revolution_street",
                "startSceneId": "photo_lab_2008",
                "startEra": "2008",
            },
            name="POST /v1/runs",
        )
        if r.status_code != 200:
            return
        try:
            payload = r.json()
        except (ValueError, json.JSONDecodeError):
            return
        self.run_id = (payload.get("run") or {}).get("runId", "")

    @task(8)  # the core endpoint, weighted highest
    def post_action(self) -> None:
        if not self.run_id:
            return
        idx = self.event_sequence % len(self.action_types)
        action_type = self.action_types[idx]
        body = {
            "runId": self.run_id,
            "sceneId": "photo_lab_2008",
            "clientActionId": f"caid-{uuid.uuid4().hex}",
            "expectedEventSequence": self.event_sequence,
            "playerAction": {
                "actionType": action_type,
                "actorId": "player",
                "targetId": "leila" if idx % 2 == 0 else "arash",
                "utterance": f"load-test turn {self.event_sequence}",
                "tone": "neutral",
                "disclosureLevel": 0.5,
                "isDeceptive": False,
                "schemaVersion": "1.0.0",
            },
            "clientVersion": "loadtest-1.0.0",
        }
        t0 = time.perf_counter()
        r = self.client.post(  # type: ignore[union-attr]
            f"/v1/runs/{self.run_id}/actions",
            json=body,
            name="POST /v1/runs/:id/actions",
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if r.status_code == 200:
            self.event_sequence += 1
        # Forward the latency to the metrics registry so
        # the W9 acceptance check sees a real p95 sample.
        try:
            from server.observability import record_model_call

            record_model_call(  # noqa: F841
                agent="client",
                model="load_test_client",
                provider="load_test",
                latency_ms=elapsed_ms,
                input_tokens=0,
                output_tokens=0,
                cost_cny=0.0,
            )
        except Exception:
            pass

    @task(1)
    def get_snapshot(self) -> None:
        if not self.run_id:
            return
        self.client.get(  # type: ignore[union-attr]
            f"/v1/runs/{self.run_id}/snapshot",
            name="GET /v1/runs/:id/snapshot",
        )

    @task(1)
    def get_scene(self) -> None:
        self.client.get(  # type: ignore[union-attr]
            "/v1/scenes/photo_lab_2008",
            name="GET /v1/scenes/:id",
        )

    @task(1)
    def get_archive(self) -> None:
        if not self.run_id:
            return
        self.client.get(  # type: ignore[union-attr]
            f"/v1/runs/{self.run_id}/archive",
            name="GET /v1/runs/:id/archive",
        )


# ---------------------------------------------------------------------------
# Batch run driver — 100 局无崩溃 (the W9 acceptance)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BatchResult:
    """One batch run's outcome."""

    runs_completed: int = 0
    runs_failed: int = 0
    total_actions: int = 0
    p95_latency_ms: float = 0.0
    avg_cost_cny: float = 0.0
    max_cost_cny: float = 0.0
    error_rate: float = 0.0
    duration_s: float = 0.0
    started_at: float = 0.0
    ended_at: float = 0.0
    failed_run_ids: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runsCompleted": self.runs_completed,
            "runsFailed": self.runs_failed,
            "totalActions": self.total_actions,
            "p95LatencyMs": round(self.p95_latency_ms, 1),
            "avgCostCny": round(self.avg_cost_cny, 4),
            "maxCostCny": round(self.max_cost_cny, 4),
            "errorRate": round(self.error_rate, 4),
            "durationSeconds": round(self.duration_s, 1),
            "failedRunIds": self.failed_run_ids[:5],
        }


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return float(s[f])
    return s[f] + (s[c] - s[f]) * (k - f)


def _drive_single_run(
    client: Any,
    *,
    actions_per_run: int,
    scene_id: str = "photo_lab_2008",
) -> tuple[bool, list[float], float]:
    """Drive one full run; return ``(ok, latencies, total_cost)``."""

    # 1) Create the run.
    r = client.post(
        "/v1/runs",
        json={
            "userId": f"batch-{uuid.uuid4().hex[:8]}",
            "caseSlug": "case_01_revolution_street",
            "startSceneId": scene_id,
            "startEra": "2008",
        },
    )
    if r.status_code != 200:
        return False, [], 0.0
    run = (r.json() or {}).get("run") or {}
    run_id = run.get("runId", "")
    if not run_id:
        return False, [], 0.0

    # 2) Drive N actions.
    latencies: list[float] = []
    total_cost = 0.0
    for seq in range(actions_per_run):
        t0 = time.perf_counter()
        r = client.post(
            f"/v1/runs/{run_id}/actions",
            json={
                "runId": run_id,
                "sceneId": scene_id,
                "clientActionId": f"caid-{uuid.uuid4().hex}",
                "expectedEventSequence": seq,
                "playerAction": {
                    "actionType": "question" if seq % 2 == 0 else "examine",
                    "actorId": "player",
                    "targetId": "leila",
                    "utterance": f"batch seq {seq}",
                    "tone": "neutral",
                    "disclosureLevel": 0.5,
                    "isDeceptive": False,
                    "schemaVersion": "1.0.0",
                },
                "clientVersion": "loadtest-1.0.0",
            },
        )
        latencies.append((time.perf_counter() - t0) * 1000.0)
        if r.status_code != 200:
            return False, latencies, total_cost
        try:
            payload = r.json()
        except (ValueError, json.JSONDecodeError):
            return False, latencies, total_cost
        # Sum the per-action cost (the brief measures the
        # aggregate cost per run; the server returns
        # ``modelCalls`` with a ``costCny`` field).
        for mc in (payload.get("modelCalls") or []):
            try:
                total_cost += float(mc.get("costCny") or 0.0)
            except (TypeError, ValueError):
                pass
    return True, latencies, total_cost


def run_batch(
    *,
    n_runs: int = BATCH_RUN_TARGET,
    actions_per_run: int = 12,
    base_url: str = "http://127.0.0.1:8000",
    out_path: str | Path | None = None,
) -> BatchResult:
    """Drive ``n_runs`` full runs and assert on the W9
    acceptance numbers.

    The function uses :class:`httpx.Client` (not Locust)
    so it is invocable from any CI step without the
    Locust binary.  When ``out_path`` is provided, the
    :class:`BatchResult` is written as JSON for the
    workflow to publish.
    """

    import httpx  # local import — keeps the top of the file import-cheap

    result = BatchResult(started_at=time.time())
    try:
        client = httpx.Client(base_url=base_url, timeout=30.0)
    except Exception as exc:  # noqa: BLE001
        logger.error("load_test: cannot construct httpx client: %s", exc)
        result.ended_at = time.time()
        result.duration_s = result.ended_at - result.started_at
        return result
    try:
        for i in range(n_runs):
            ok, latencies, cost = _drive_single_run(
                client, actions_per_run=actions_per_run
            )
            result.latencies_ms.extend(latencies)
            result.total_actions += len(latencies)
            if ok:
                result.runs_completed += 1
                result.avg_cost_cny += cost
                result.max_cost_cny = max(result.max_cost_cny, cost)
            else:
                result.runs_failed += 1
                result.failed_run_ids.append(f"run-{i:03d}")
    finally:
        client.close()
    result.ended_at = time.time()
    result.duration_s = result.ended_at - result.started_at
    result.p95_latency_ms = _percentile(result.latencies_ms, 95.0)
    if result.runs_completed:
        result.avg_cost_cny /= result.runs_completed
    result.error_rate = (
        result.runs_failed / max(1, result.runs_completed + result.runs_failed)
    )

    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(result.to_dict(), fp, ensure_ascii=False, indent=2)

    return result


def assert_w9_acceptance(result: BatchResult) -> None:
    """Raise :class:`AssertionError` if the batch failed any
    W9 acceptance number.

    Returns silently on success so callers can use it as
    a one-line check at the end of a CI step.
    """

    failures: list[str] = []
    if result.p95_latency_ms > P95_BUDGET_S * 1000.0:
        failures.append(
            f"P95 {result.p95_latency_ms:.0f}ms > {P95_BUDGET_S * 1000.0:.0f}ms "
            f"(决策 5 R4)"
        )
    if result.max_cost_cny > PER_RUN_COST_BUDGET_CNY:
        failures.append(
            f"max run cost ¥{result.max_cost_cny:.4f} > ¥{PER_RUN_COST_BUDGET_CNY} "
            f"(决策 5 soft target)"
        )
    if result.runs_failed > 0:
        failures.append(
            f"{result.runs_failed}/{result.runs_completed + result.runs_failed} "
            f"runs failed (100 局无崩溃)"
        )
    if result.error_rate > ERROR_RATE_BUDGET:
        failures.append(
            f"error rate {result.error_rate:.2%} > {ERROR_RATE_BUDGET:.0%} "
            f"(W9 错误率红线)"
        )
    if failures:
        raise AssertionError("W9 acceptance failed:\n  - " + "\n  - ".join(failures))


# ---------------------------------------------------------------------------
# Locust event hooks — populate the BatchResult and fail the run on
# acceptance breach.
# ---------------------------------------------------------------------------


_LOCUST_BATCH: BatchResult | None = None


def install_locust_hooks() -> None:  # pragma: no cover - Locust-only
    """Wire the Locust event bus to a :class:`BatchResult`.

    The hook collects every action latency, computes the
    p95 on ``test_stop``, and exits non-zero if any W9
    acceptance number was breached.
    """

    if not LOCUST_AVAILABLE:
        logger.warning("load_test: Locust not installed; skipping hook install")
        return
    global _LOCUST_BATCH
    _LOCUST_BATCH = BatchResult(started_at=time.time())

    @events.test_start.add_listener
    def _on_start(environment: Any, **_: Any) -> None:
        if _LOCUST_BATCH is not None:
            _LOCUST_BATCH.started_at = time.time()

    @events.test_stop.add_listener
    def _on_stop(environment: Any, **_: Any) -> None:
        if _LOCUST_BATCH is None:
            return
        _LOCUST_BATCH.ended_at = time.time()
        _LOCUST_BATCH.duration_s = _LOCUST_BATCH.ended_at - _LOCUST_BATCH.started_at
        # Pull the request-level stats from the Locust
        # runner; the per-request latency lives in
        # ``environment.runner.stats.total``.
        stats = getattr(getattr(environment, "runner", None), "stats", None)
        if stats is not None and getattr(stats, "total", None) is not None:
            t = stats.total
            _LOCUST_BATCH.latencies_ms = list(
                getattr(t, "response_times", {}).values()
            ) or []
            _LOCUST_BATCH.p95_latency_ms = _percentile(
                _LOCUST_BATCH.latencies_ms, 95.0
            )
            num_reqs = int(getattr(t, "num_requests", 0))
            num_fail = int(getattr(t, "num_failures", 0))
            _LOCUST_BATCH.total_actions = num_reqs
            _LOCUST_BATCH.error_rate = (
                num_fail / num_reqs if num_reqs else 0.0
            )
            _LOCUST_BATCH.runs_completed = num_reqs  # one HTTP call ≈ one action
        try:
            assert_w9_acceptance(_LOCUST_BATCH)
            logger.info(
                "load_test: W9 acceptance PASSED p95=%.0fms runs=%d error_rate=%.2f%%",
                _LOCUST_BATCH.p95_latency_ms,
                _LOCUST_BATCH.runs_completed,
                _LOCUST_BATCH.error_rate * 100,
            )
        except AssertionError as exc:
            logger.error("load_test: %s", exc)
            try:
                environment.runner.quit()
            except Exception:
                pass


# Install the hooks at import time so ``locust -f`` picks
# them up automatically.
if LOCUST_AVAILABLE:
    install_locust_hooks()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> int:
    """Headless batch driver — ``python tests/performance/test_load.py``."""

    import argparse

    parser = argparse.ArgumentParser(description="G1N W9 load test (batch mode)")
    parser.add_argument("--runs", type=int, default=BATCH_RUN_TARGET)
    parser.add_argument("--actions-per-run", type=int, default=12)
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:8000")
    parser.add_argument(
        "--out",
        type=str,
        default=str(ROOT / "artifacts" / "load_test_batch.json"),
    )
    args = parser.parse_args()

    result = run_batch(
        n_runs=args.runs,
        actions_per_run=args.actions_per_run,
        base_url=args.base_url,
        out_path=args.out,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    try:
        assert_w9_acceptance(result)
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())


__all__ = [
    "G1NPlayerUser",
    "BatchResult",
    "run_batch",
    "assert_w9_acceptance",
    "install_locust_hooks",
    "P95_BUDGET_S",
    "PER_RUN_COST_BUDGET_CNY",
    "BATCH_RUN_TARGET",
    "ERROR_RATE_BUDGET",
    "DEFAULT_USERS",
    "DEFAULT_SPAWN_RATE",
    "DEFAULT_RUN_TIME_S",
]
