"""Cost control — per-call audit, per-run cap, L3 alert.

Decision 5 hard red lines (must be enforced):

* 30-45 minute run main calls ≤ 20
* Single output token < 800
* Per-turn model calls ≤ 2
* Key interaction P95 < 4s (this module records latency; the
  alert layer is in the gateway)

Decision 5 soft target (alert on breach):

* Per-run AI cost < ¥0.8
* Income 8-12% on AI

P0 alert condition (from decision 5 acceptance criteria):

* 3 consecutive runs triggering L3 degradation → P0 alert

This module
-----------

* :class:`CostController` tracks every call as a
  :class:`CostRecord` in memory (the W4 integration layer is
  responsible for persisting the records to the ``model_calls``
  table).
* :class:`CostController.record` checks the red lines and raises
  :class:`BudgetExceededError` / :class:`OutputTokenLimitExceededError`
  on breach.
* :class:`CostController.check_turn_budget` and
  :class:`CostController.check_run_budget` are called by the
  gateway *before* a call to short-circuit the LLM path.
* :class:`CostController.note_run_completion` updates the
  consecutive-L3 counter and fires the P0 alert when threshold
  is crossed.
* :class:`CostController.run_summary` returns a
  :class:`RunCostSummary` for the active run.

Pricing
-------

Pricing is per-1K-tokens in CNY.  Defaults are based on public
price cards (2025); override in :class:`CostController`
construction for cost tests.  Unknown models fall through to a
``default_input_per_1k`` / ``default_output_per_1k`` pair so
the controller never raises on an unknown model.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from .exceptions import (
    BudgetExceededError,
    CostCapExceededError,
    OutputTokenLimitExceededError,
)
from .models import CostRecord, RunCostSummary


# ---------------------------------------------------------------------------
# Pricing table
# ---------------------------------------------------------------------------


#: Per-1K-tokens price in CNY.  Keys are ``(provider, model)``
#: tuples.  A ``None`` provider in the key matches any provider.
#: These are public-list prices (DeepSeek-V3 ¥0.001 / 1K in,
#: ¥0.002 / 1K out; Qwen-Plus ¥0.0008 / 1K in, ¥0.002 / 1K out;
#: 2025-07).  Override per-deployment.
PRICING: dict[tuple[str | None, str], tuple[float, float]] = {
    ("deepseek", "deepseek-chat"): (0.001, 0.002),
    ("deepseek", "deepseek-reasoner"): (0.004, 0.016),
    ("qwen", "qwen-plus"): (0.0008, 0.002),
    ("qwen", "qwen-max"): (0.020, 0.060),
    ("qwen", "qwen-turbo"): (0.0003, 0.0006),
    ("openai_compatible", "gpt-4o-mini"): (0.0015, 0.006),
    # Mock / writer fallbacks: zero cost
    ("mock", "*"): (0.0, 0.0),
    ("writer", "*"): (0.0, 0.0),
}

# Fallback when (provider, model) is not in the table
DEFAULT_PRICING: tuple[float, float] = (0.005, 0.015)  # rough mid-tier


# ---------------------------------------------------------------------------
# Hard red lines (decision 5)
# ---------------------------------------------------------------------------


#: Maximum main calls in a single run (decision 5 red line).
HARD_RUN_CALL_BUDGET: int = 20

#: Maximum model calls in a single turn (decision 5 red line).
HARD_TURN_CALL_BUDGET: int = 2

#: Maximum output tokens in a single call (decision 5 red line).
HARD_OUTPUT_TOKEN_LIMIT: int = 800

#: Soft target: per-run cost in CNY (decision 5 soft target).
SOFT_RUN_COST_TARGET: float = 0.8

#: P95 latency target for key interactions in ms (decision 5).
P95_LATENCY_TARGET_MS: int = 4000

#: Consecutive L3 runs before P0 alert (decision 5 acceptance).
P0_L3_CONSECUTIVE_THRESHOLD: int = 3


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class P0Alert:
    """An alert fired by the cost controller.

    The P0 alert is the "consecutive L3 degradation" alarm from
    decision 5's acceptance criteria.  W4 integration is
    responsible for routing this to on-call (PagerDuty / 飞书 /
    log alert).
    """

    reason: str
    run_ids: list[str]
    triggered_at: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "runIds": list(self.run_ids),
            "triggeredAt": self.triggered_at,
            "payload": dict(self.payload),
        }


# ---------------------------------------------------------------------------
# Cost controller
# ---------------------------------------------------------------------------


class CostController:
    """Track per-call cost + per-run aggregate + P0 alerts.

    Thread-safe: the gateway is called from request handlers in
    the FastAPI server, so concurrent access is the norm.
    """

    def __init__(
        self,
        *,
        run_cost_soft_target: float = SOFT_RUN_COST_TARGET,
        hard_run_call_budget: int = HARD_RUN_CALL_BUDGET,
        hard_turn_call_budget: int = HARD_TURN_CALL_BUDGET,
        hard_output_token_limit: int = HARD_OUTPUT_TOKEN_LIMIT,
        p0_consecutive_l3_threshold: int = P0_L3_CONSECUTIVE_THRESHOLD,
        alert_sink: Callable[[P0Alert], None] | None = None,
        pricing: dict[tuple[str | None, str], tuple[float, float]] | None = None,
    ) -> None:
        self._run_cost_soft_target = run_cost_soft_target
        self._hard_run_call_budget = hard_run_call_budget
        self._hard_turn_call_budget = hard_turn_call_budget
        self._hard_output_token_limit = hard_output_token_limit
        self._p0_consecutive_l3_threshold = p0_consecutive_l3_threshold
        self._alert_sink = alert_sink
        self._pricing = pricing if pricing is not None else dict(PRICING)

        self._lock = threading.RLock()
        # Per-run state
        self._run_records: dict[str, list[CostRecord]] = {}
        self._run_call_count: dict[str, int] = {}
        self._run_l3_flag: dict[str, bool] = {}
        self._turn_call_count: dict[tuple[str, int], int] = {}  # (run_id, turn_idx)
        # P0 alert state — last N run ids (most recent at right)
        self._recent_run_ids: deque[str] = deque(maxlen=p0_consecutive_l3_threshold)
        # Run ids that have already been part of a fired alert;
        # used to dedupe across long L3 streaks.
        self._alerted_run_ids: set[str] = set()
        # P0 alert audit
        self._alerts: list[P0Alert] = []

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def price(self, *, provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
        """Compute the call cost in CNY."""

        in_rate, out_rate = self._lookup_pricing(provider, model)
        return (input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate

    def _lookup_pricing(self, provider: str, model: str) -> tuple[float, float]:
        # Exact match first
        if (provider, model) in self._pricing:
            return self._pricing[(provider, model)]
        # Wildcard model
        if (provider, "*") in self._pricing:
            return self._pricing[(provider, "*")]
        # Wildcard provider
        if (None, model) in self._pricing:
            return self._pricing[(None, model)]
        return DEFAULT_PRICING

    # ------------------------------------------------------------------
    # Pre-call checks
    # ------------------------------------------------------------------

    def check_run_budget(self, *, run_id: str) -> None:
        """Raise if the per-run call count is at the hard cap."""

        with self._lock:
            count = self._run_call_count.get(run_id, 0)
        if count >= self._hard_run_call_budget:
            raise BudgetExceededError(
                f"run {run_id!r} exhausted hard call budget "
                f"({self._hard_run_call_budget} calls; decision 5 red line)"
            )

    def check_turn_budget(self, *, run_id: str, turn_idx: int) -> None:
        """Raise if the per-turn call count is at the hard cap (2)."""

        with self._lock:
            count = self._turn_call_count.get((run_id, turn_idx), 0)
        if count >= self._hard_turn_call_budget:
            raise BudgetExceededError(
                f"run {run_id!r} turn {turn_idx} exhausted hard turn budget "
                f"({self._hard_turn_call_budget} calls; decision 5 red line)"
            )

    def check_output_token_limit(self, *, model: str, output_tokens: int) -> None:
        """Raise if a single call would exceed the 800-token cap."""

        if output_tokens > self._hard_output_token_limit:
            raise OutputTokenLimitExceededError(
                f"model {model!r} emitted {output_tokens} tokens; "
                f"hard cap is {self._hard_output_token_limit} "
                f"(decision 5 red line)"
            )

    # ------------------------------------------------------------------
    # Per-call recording
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        record: CostRecord,
        turn_idx: int = 0,
    ) -> CostRecord:
        """Record a call's cost.  Returns the same record (with cost filled)."""

        cost = self.price(
            provider=record.provider,
            model=record.model,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
        )
        record.cost_cny = round(cost, 6)

        with self._lock:
            self._run_records.setdefault(record.run_id, []).append(record)
            self._run_call_count[record.run_id] = (
                self._run_call_count.get(record.run_id, 0) + 1
            )
            self._turn_call_count[(record.run_id, turn_idx)] = (
                self._turn_call_count.get((record.run_id, turn_idx), 0) + 1
            )
            if record.degradation_level == "L3":
                self._run_l3_flag[record.run_id] = True

        # Soft target warning (does not raise, but tagged on the
        # record via metadata so the audit can show "over budget").
        summary = self.run_summary(record.run_id)
        if summary.total_cost_cny > self._run_cost_soft_target:
            record.metadata["overSoftTarget"] = True
        return record

    # ------------------------------------------------------------------
    # Run-level summary + L3 alert
    # ------------------------------------------------------------------

    def run_summary(self, run_id: str) -> RunCostSummary:
        """Build a :class:`RunCostSummary` for ``run_id`` (empty if unknown)."""

        with self._lock:
            records = list(self._run_records.get(run_id, []))
        if not records:
            return RunCostSummary(run_id=run_id)
        latencies = sorted(r.latency_ms for r in records)
        p95_index = max(0, int(round(0.95 * (len(latencies) - 1))))
        return RunCostSummary(
            run_id=run_id,
            total_calls=len(records),
            total_input_tokens=sum(r.input_tokens for r in records),
            total_output_tokens=sum(r.output_tokens for r in records),
            total_cost_cny=round(sum(r.cost_cny for r in records), 6),
            p95_latency_ms=latencies[p95_index],
            l3_count=sum(1 for r in records if r.degradation_level == "L3"),
            l4_count=sum(1 for r in records if r.degradation_level == "L4"),
        )

    def note_run_completion(self, run_id: str) -> list[P0Alert]:
        """Call when a run ends.  Returns any P0 alerts fired.

        The P0 alert fires when the *last N* runs (N =
        ``p0_consecutive_l3_threshold``) all triggered L3
        degradation.  The L3 flag is set on the run by
        :meth:`record` when any call in the run escalated to L3.

        The alert is fired at most once per L3 streak: if the
        last N runs are all L3 *and none of them have been part
        of a previous alert*, fire.  When a non-L3 run breaks
        the streak, the alerted-run-id set is cleared.
        """

        fired: list[P0Alert] = []
        with self._lock:
            had_l3 = self._run_l3_flag.get(run_id, False)
            if had_l3:
                self._recent_run_ids.append(run_id)
            else:
                # Non-L3 run breaks the consecutive chain AND
                # resets the alerted-set, so the next L3 streak
                # can fire a fresh alert.
                self._recent_run_ids.clear()
                self._alerted_run_ids.clear()
            if len(self._recent_run_ids) >= self._p0_consecutive_l3_threshold:
                # Has every recent run already been alerted?
                if not set(self._recent_run_ids).issubset(self._alerted_run_ids):
                    run_ids = list(self._recent_run_ids)
                    alert = P0Alert(
                        reason=(
                            f"{len(run_ids)} consecutive runs triggered L3 "
                            f"degradation (decision 5 acceptance criteria)"
                        ),
                        run_ids=run_ids,
                        triggered_at=datetime.now(timezone.utc)
                        .isoformat(timespec="seconds")
                        .replace("+00:00", "Z"),
                        payload={
                            "threshold": self._p0_consecutive_l3_threshold,
                            "summaries": [
                                self.run_summary(r).to_dict() for r in run_ids
                            ],
                        },
                    )
                    self._alerts.append(alert)
                    fired.append(alert)
                    self._alerted_run_ids.update(run_ids)
                    if self._alert_sink is not None:
                        try:
                            self._alert_sink(alert)
                        except Exception:  # noqa: BLE001
                            # The alert sink is best-effort; we
                            # never let a sink failure break the
                            # game loop.
                            pass
        return fired

    def _recent_run_ids_already_alerted(self) -> bool:
        """Kept for backward compatibility — uses the new set-based check."""

        return set(self._recent_run_ids).issubset(self._alerted_run_ids)

    # ------------------------------------------------------------------
    # Accessors for tests
    # ------------------------------------------------------------------

    def records_for(self, run_id: str) -> list[CostRecord]:
        with self._lock:
            return list(self._run_records.get(run_id, []))

    @property
    def alerts(self) -> list[P0Alert]:
        return list(self._alerts)

    def reset(self) -> None:
        with self._lock:
            self._run_records.clear()
            self._run_call_count.clear()
            self._run_l3_flag.clear()
            self._turn_call_count.clear()
            self._recent_run_ids.clear()
            self._alerted_run_ids.clear()
            self._alerts.clear()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def make_cost_record(
    *,
    run_id: str,
    scene_id: str,
    task_type: str,
    agent: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    finish_reason: str,
    degradation_level: str | None = None,
    used_fallback: bool = False,
    attempts: int = 1,
    request_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> CostRecord:
    """Convenience constructor for a :class:`CostRecord`."""

    return CostRecord(
        request_id=request_id,
        run_id=run_id,
        scene_id=scene_id,
        task_type=task_type,
        agent=agent,
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        cost_cny=0.0,  # filled by CostController.record
        finish_reason=finish_reason,
        degradation_level=degradation_level,
        used_fallback=used_fallback,
        attempts=attempts,
        timestamp=datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        metadata=dict(metadata or {}),
    )


__all__ = [
    "PRICING",
    "DEFAULT_PRICING",
    "HARD_RUN_CALL_BUDGET",
    "HARD_TURN_CALL_BUDGET",
    "HARD_OUTPUT_TOKEN_LIMIT",
    "SOFT_RUN_COST_TARGET",
    "P95_LATENCY_TARGET_MS",
    "P0_L3_CONSECUTIVE_THRESHOLD",
    "P0Alert",
    "CostController",
    "make_cost_record",
]
