"""Cost monitor — the 决策 5 硬红线 gate.

Decision 5 sets four hard red lines that any breach must trigger
a CI / P0 报警.  This module is the **runtime** monitor; the
CI workflow is the **build-time** monitor.  Both use the same
:data:`HARD_RED_LINES` table as the single source of truth.

Hard red lines (决策 5)
-----------------------

* **R1**  30-45 minute vertical slice main calls per run
          ≤ 20.
* **R2**  Single LLM output tokens < 800 (any single call).
* **R3**  Per-turn model calls ≤ 2 (one player action is
          allowed to spawn at most 2 LLM calls — typically one
          for the NPC agent and one for the Director beat).
* **R4**  Key interaction response P95 < 4 seconds.

In addition, the **soft** signal we monitor:

* **S1**  Three consecutive runs that trigger L3 (the third
          tier of the 4-level degradation chain) must fire a
          P0 报警.  The engine writes a ``degradationLevel``
          to the ``model_calls`` table; we count occurrences
          and trip a P0 when the rolling count hits 3.

Why this is its own module
--------------------------

The cost monitor is the only safety component that **CI
blocks** on its own.  Everything else in the safety package
blocks a *payload*; this one blocks a *build*.  The module is
also the only one that must be runnable as a standalone CLI
with a clean exit code (see :class:`ExitCode`).
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Hard red lines
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RedLine:
    """One entry in the :data:`HARD_RED_LINES` table.

    Attributes
    ----------
    id : str
        Stable identifier — ``R1`` / ``R2`` / ``R3`` / ``R4``.
    label : str
        Human-readable label (Chinese ok; the report is for
        the engineering team).
    threshold : float
        The maximum legal value (inclusive for ``max`` rules,
        exclusive for ``min`` rules).
    comparator : str
        ``"<="`` (current must be at or below threshold) or
        ``">="`` (current must be at or above threshold).
        For our four hard red lines all are ``"<="``.
    unit : str
        The unit of the metric (``"calls"`` / ``"tokens"`` /
        ``"calls_per_turn"`` / ``"ms"``).
    """

    id: str
    label: str
    threshold: float
    comparator: str
    unit: str

    def check(self, value: float) -> bool:
        """Return True iff the value is within the red line."""

        if self.comparator == "<=":
            return value <= self.threshold
        if self.comparator == ">=":
            return value >= self.threshold
        raise ValueError(f"unknown comparator: {self.comparator!r}")


#: The four hard red lines from 决策 5.
#:
#: **DO NOT EDIT** the thresholds without a decision-document
#: revision — these are the literal values the brief pinned
#: in ``requirements-review-v1.md`` §2.  Renaming an ``id``
#: breaks the CI workflow and the P0 报警 dashboard; tests
#: assert on the literal ``"R1"`` etc.
HARD_RED_LINES: tuple[RedLine, ...] = (
    RedLine("R1", "纵切片主调用次数", 20.0, "<=", "calls"),
    RedLine("R2", "单次输出 token", 800.0, "<=", "tokens"),
    RedLine("R3", "单回合模型调用次数", 2.0, "<=", "calls_per_turn"),
    RedLine("R4", "关键交互响应 P95", 4_000.0, "<=", "ms"),
)


# ---------------------------------------------------------------------------
# P0 报警 (degradation chain escalation)
# ---------------------------------------------------------------------------


#: Number of consecutive runs that must trigger L3 (or
#: worse) before a P0 报警 fires.  Decision 5 §"反向代价"
#: pins this at 3.
P0_ESCALATION_THRESHOLD: int = 3


# ---------------------------------------------------------------------------
# Exit codes (mirrors idempotency.py)
# ---------------------------------------------------------------------------


class ExitCode(int, Enum):
    """Stable exit codes for the CLI / CI surface."""

    PASS = 0
    BLOCK = 1       # a hard red line was breached
    IO_ERROR = 2


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ModelCall:
    """A single recorded LLM call (the ``model_calls`` table row).

    Mirrors the engine's :class:`model.ModelCall` dataclass
    (which lives in W3-A's package).  We re-declare the shape
    here so the safety layer does not depend on W3-A.
    """

    runId: str
    sequence: int
    agent: str  # "player_client" | "npc_agent" | "director_agent" | "resolver" | "memory_recall"
    model: str
    inputTokens: int = 0
    outputTokens: int = 0
    latencyMs: int = 0
    degradationLevel: int = 0  # 0 = L0 (no degradation), 1..4 = L1..L4
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.runId:
            raise ValueError("runId is required")
        if self.sequence < 0:
            raise ValueError("sequence must be >= 0")
        if not self.agent:
            raise ValueError("agent is required")
        if not self.model:
            raise ValueError("model is required")
        if not self.timestamp:
            self.timestamp = (
                datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            )


@dataclass(slots=True)
class RunSummary:
    """Per-run aggregate numbers."""

    runId: str
    main_call_count: int
    per_turn_max_calls: int
    max_output_tokens: int
    p95_latency_ms: float
    l3_or_worse_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CostViolation:
    """One red-line breach row."""

    red_line_id: str
    label: str
    observed: float
    threshold: float
    unit: str
    runId: str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CostReport:
    """The aggregate cost report."""

    passed: bool
    exit_code: int
    run_summaries: list[RunSummary] = field(default_factory=list)
    violations: list[CostViolation] = field(default_factory=list)
    p0_alert: bool = False
    p0_reason: str = ""
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "exit_code": int(self.exit_code),
            "run_summaries": [r.to_dict() for r in self.run_summaries],
            "violations": [v.to_dict() for v in self.violations],
            "p0_alert": self.p0_alert,
            "p0_reason": self.p0_reason,
            "summary": dict(self.summary),
        }

    def to_human_readable(self) -> str:
        lines: list[str] = []
        verdict = "✅ PASS" if self.passed else "❌ BLOCK"
        lines.append(f"{verdict}  cost_monitor  exit_code={int(self.exit_code)}")
        s = self.summary
        lines.append(
            "summary: "
            + ", ".join(f"{k}={v}" for k, v in s.items() if v)
        )
        for v in self.violations:
            lines.append(
                f"  • [{v.red_line_id}] {v.label}  observed={v.observed}{v.unit}  "
                f"threshold={v.threshold}{v.unit}  run={v.runId}"
            )
            if v.detail:
                lines.append(f"      {v.detail}")
        for r in self.run_summaries:
            lines.append(
                f"  run {r.runId[:8]}: main_calls={r.main_call_count} "
                f"per_turn_max={r.per_turn_max_calls} "
                f"max_output_tokens={r.max_output_tokens} "
                f"p95={r.p95_latency_ms:.0f}ms l3+={r.l3_or_worse_count}"
            )
        if self.p0_alert:
            lines.append(f"  ⚠ P0 报警: {self.p0_reason}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _percentile(values: list[float], p: float) -> float:
    """Return the *p*-th percentile of ``values`` (0..100).

    Linear interpolation between the two closest observations
    — same algorithm as numpy's default, but inlined so the
    safety package stays stdlib-only.
    """

    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def summarise_run(runId: str, calls: list[ModelCall]) -> RunSummary:
    """Compute the per-run aggregate numbers from a list of calls.

    The "main calls" are ``npc_agent`` + ``director_agent`` +
    ``resolver`` — the agents the player or director spawn.
    ``player_client`` is the client, not a server-side call;
    ``memory_recall`` is a vector-search call that is **not**
    counted in the 20-call budget.
    """

    main_agents = {"npc_agent", "director_agent", "resolver"}
    main_calls = [c for c in calls if c.agent in main_agents]
    per_turn: dict[int, int] = {}
    for c in main_calls:
        per_turn[c.sequence] = per_turn.get(c.sequence, 0) + 1
    per_turn_max = max(per_turn.values()) if per_turn else 0
    max_output_tokens = max((c.outputTokens for c in main_calls), default=0)
    latencies = [float(c.latencyMs) for c in main_calls if c.latencyMs > 0]
    p95 = _percentile(latencies, 95.0) if latencies else 0.0
    l3_count = sum(1 for c in calls if c.degradationLevel >= 3)
    return RunSummary(
        runId=runId,
        main_call_count=len(main_calls),
        per_turn_max_calls=per_turn_max,
        max_output_tokens=max_output_tokens,
        p95_latency_ms=p95,
        l3_or_worse_count=l3_count,
    )


def check_red_lines(summary: RunSummary) -> list[CostViolation]:
    """Return the red-line breaches for one run summary."""

    out: list[CostViolation] = []
    for line in HARD_RED_LINES:
        if line.id == "R1":
            observed = float(summary.main_call_count)
        elif line.id == "R2":
            observed = float(summary.max_output_tokens)
        elif line.id == "R3":
            observed = float(summary.per_turn_max_calls)
        elif line.id == "R4":
            observed = float(summary.p95_latency_ms)
        else:
            continue
        if not line.check(observed):
            out.append(CostViolation(
                red_line_id=line.id,
                label=line.label,
                observed=observed,
                threshold=line.threshold,
                unit=line.unit,
                runId=summary.runId,
                detail=f"hard red line {line.id} ({line.label}) breached",
            ))
    return out


def check_p0_escalation(history: list[RunSummary]) -> tuple[bool, str]:
    """Return ``(p0_fired, reason)`` based on a rolling L3 history.

    The engine emits one ``RunSummary`` per completed run.
    The cost monitor keeps a rolling window of the last
    ``P0_ESCALATION_THRESHOLD`` runs; if every one of them
    triggered L3 or worse, we fire a P0 报警.
    """

    if len(history) < P0_ESCALATION_THRESHOLD:
        return False, ""
    recent = history[-P0_ESCALATION_THRESHOLD:]
    if all(r.l3_or_worse_count > 0 for r in recent):
        ids = ", ".join(r.runId[:8] for r in recent)
        return True, (
            f"连续 {P0_ESCALATION_THRESHOLD} 局触发 L3 降级 (runs: {ids}) — "
            "prompt 或合同可能有问题，触发 P0 报警"
        )
    return False, ""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def evaluate(
    calls_by_run: dict[str, list[ModelCall]],
    *,
    p0_history: list[RunSummary] | None = None,
) -> CostReport:
    """Evaluate a batch of runs and return the cost report.

    Parameters
    ----------
    calls_by_run : dict
        Mapping ``runId -> list[ModelCall]``.
    p0_history : list[RunSummary] | None
        Optional pre-existing run summaries to fold into the
        P0 escalation check.  When ``None`` the function
        only looks at the runs in ``calls_by_run``.
    """

    summaries: list[RunSummary] = []
    violations: list[CostViolation] = []
    for runId, calls in calls_by_run.items():
        summary = summarise_run(runId, calls)
        summaries.append(summary)
        violations.extend(check_red_lines(summary))

    p0_history_list = list(p0_history or []) + summaries
    p0_alert, p0_reason = check_p0_escalation(p0_history_list)

    summary_counts: dict[str, int] = {}
    for v in violations:
        summary_counts[v.red_line_id] = summary_counts.get(v.red_line_id, 0) + 1
    summary_counts["total_violations"] = len(violations)
    summary_counts["p0_alert"] = 1 if p0_alert else 0

    exit_code = int(ExitCode.BLOCK if violations else ExitCode.PASS)

    return CostReport(
        passed=not violations,
        exit_code=exit_code,
        run_summaries=summaries,
        violations=violations,
        p0_alert=p0_alert,
        p0_reason=p0_reason,
        summary=summary_counts,
    )


# ---------------------------------------------------------------------------
# Live counter (for the server's runtime path)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LiveCounter:
    """A per-run live counter the server increments as calls happen.

    Use :meth:`record` to add a call, :meth:`check` to ask
    "is this run within the red lines so far?"  The counter
    is in-process; cross-process aggregation goes through
    the database (out of scope for the safety package).
    """

    runId: str
    main_calls: int = 0
    max_output_tokens: int = 0
    per_turn_counts: dict[int, int] = field(default_factory=dict)
    latencies: list[int] = field(default_factory=list)
    l3_or_worse_count: int = 0
    started_at: float = field(default_factory=time.time)

    def record(self, call: ModelCall) -> list[CostViolation]:
        """Record one call and return any new red-line violations.

        The function returns a list because a single call can
        breach at most one red line at a time; the list shape
        keeps the call-site clean.
        """

        violations: list[CostViolation] = []
        if call.agent in {"npc_agent", "director_agent", "resolver"}:
            self.main_calls += 1
            self.per_turn_counts[call.sequence] = (
                self.per_turn_counts.get(call.sequence, 0) + 1
            )
            if call.outputTokens > self.max_output_tokens:
                self.max_output_tokens = call.outputTokens
            if call.latencyMs > 0:
                self.latencies.append(call.latencyMs)
        if call.degradationLevel >= 3:
            self.l3_or_worse_count += 1
        return violations

    def check(self) -> list[CostViolation]:
        """Return the red-line breaches seen so far in this run."""

        summary = RunSummary(
            runId=self.runId,
            main_call_count=self.main_calls,
            per_turn_max_calls=max(self.per_turn_counts.values()) if self.per_turn_counts else 0,
            max_output_tokens=self.max_output_tokens,
            p95_latency_ms=_percentile([float(x) for x in self.latencies], 95.0) if self.latencies else 0.0,
            l3_or_worse_count=self.l3_or_worse_count,
        )
        return check_red_lines(summary)


# ---------------------------------------------------------------------------
# CI helper
# ---------------------------------------------------------------------------


def evaluate_from_file(
    path: str | Path,
    *,
    p0_history_path: str | Path | None = None,
) -> CostReport:
    """Read calls from a JSON file and evaluate.

    Two input shapes are accepted:

    * ``[ModelCall, ModelCall, ...]`` — flat list, runId on
      each call.
    * ``{"calls": [...], "p0_history": [...]}`` — wrapper with
      both ``calls`` and an optional pre-aggregated
      ``p0_history`` of :class:`RunSummary` rows.

    The wrapper shape is what the CI workflow writes.
    """

    p = Path(path)
    try:
        with open(p, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return CostReport(
            passed=False,
            exit_code=int(ExitCode.IO_ERROR),
            summary={"io_error": 1, "total_violations": 0},
        )

    if isinstance(data, list):
        calls_raw = data
        p0_history_raw: list[dict[str, Any]] = []
    elif isinstance(data, dict):
        calls_raw = data.get("calls", [])
        p0_history_raw = data.get("p0_history", []) or []
        if p0_history_path is not None:
            try:
                with open(p0_history_path, "r", encoding="utf-8") as fp:
                    hist = json.load(fp)
                if isinstance(hist, list):
                    p0_history_raw = hist
            except (OSError, json.JSONDecodeError):
                pass
    else:
        return CostReport(
            passed=False,
            exit_code=int(ExitCode.IO_ERROR),
            summary={"io_error": 1, "total_violations": 0},
        )

    calls_by_run: dict[str, list[ModelCall]] = {}
    for raw in calls_raw:
        if not isinstance(raw, dict):
            continue
        try:
            call = ModelCall(
                runId=raw.get("runId", ""),
                sequence=int(raw.get("sequence", 0)),
                agent=raw.get("agent", ""),
                model=raw.get("model", ""),
                inputTokens=int(raw.get("inputTokens", 0)),
                outputTokens=int(raw.get("outputTokens", 0)),
                latencyMs=int(raw.get("latencyMs", 0)),
                degradationLevel=int(raw.get("degradationLevel", 0)),
                timestamp=raw.get("timestamp", ""),
            )
        except (TypeError, ValueError):
            continue
        calls_by_run.setdefault(call.runId, []).append(call)

    p0_history = [
        RunSummary(
            runId=h.get("runId", ""),
            main_call_count=int(h.get("main_call_count", 0)),
            per_turn_max_calls=int(h.get("per_turn_max_calls", 0)),
            max_output_tokens=int(h.get("max_output_tokens", 0)),
            p95_latency_ms=float(h.get("p95_latency_ms", 0.0)),
            l3_or_worse_count=int(h.get("l3_or_worse_count", 0)),
        )
        for h in p0_history_raw
        if isinstance(h, dict)
    ]

    return evaluate(calls_by_run, p0_history=p0_history)


__all__ = [
    "RedLine",
    "HARD_RED_LINES",
    "P0_ESCALATION_THRESHOLD",
    "ExitCode",
    "ModelCall",
    "RunSummary",
    "CostViolation",
    "CostReport",
    "LiveCounter",
    "summarise_run",
    "check_red_lines",
    "check_p0_escalation",
    "evaluate",
    "evaluate_from_file",
    "_percentile",
]
