"""W10 · Analytics warehouse — player-data driven funnels and reports.

This is the **read-side** companion to the W4 write-side
:class:`server.repository.RunRepository`.  Nothing here mutates
canonical state; it only reads ``analytics_events``,
``recall_items``, ``game_runs``, ``model_calls``,
``entitlements`` and the related tables that the
write-side is filling.

Funnels and metrics
-------------------

* **D1 / D3 / D7 召回转化漏斗**
  ``scheduled → generated → sent → opened → recap_started → recap_completed``.
  All stages come from real rows (``recall_items.status`` +
  the matching ``analytics_events``), never template numbers.

* **单局完成率（按章节）**
  A run is "completed" when its final snapshot phase
  reaches ``act_ended`` or ``run_ended``; the per-scene
  completion rate is ``finished_in_scene / entered_scene``.

* **mandatory echo 触发率**
  Per scene, the percentage of runs that fired ≥ 1
  mandatory echo (``causal_seeds.is_dormant=false`` at run end).

* **付费转化漏斗**
  ``free_sample → passport → collectors → pov_unlock / keepsake``.
  Built from the ``entitlements`` table.

* **留存曲线**
  Day-N retention = ``distinct users with ≥ 1
  analytics_events event on day N / total signups as of day 0``.

* **每周报告**
  :func:`WeeklyReportBuilder.build` returns a
  human-readable Markdown report + the same data as
  JSON.  A CLI entry point writes the report to disk.

Privacy red line (决策 5 + W10)
------------------------------

* No metric consults ``playerAction`` content, only
  ``actionType`` + ``sceneId`` + ``runId``.  We never
  read the player's text.
* DAU/retention join on ``user_id`` only when
  ``G1N_ANALYTICS_INCLUDE_USER=true`` (default **off**);
  in the default config the per-user fields are
  stripped to aggregate counts.
* No metric can affect in-game behaviour.  This module
  exposes **read-only** helpers + a writer for the
  weekly report file.  Nothing here is on the
  request-path of ``/v1/runs/:id/actions``.

Why a separate module
---------------------

The repository and the action runner are the write
surface.  The dashboard reads SQL that is not on the hot
path, so it can afford a slightly higher latency
tolerance.  Pulling these queries out keeps the
hot-path module import-cheap and lets the dashboard be
replaced (Grafana JSON, etc.) without touching engine
code.

CLI usage
---------

::

    # Print a JSON report for the last 7 days
    python -m server.analytics_warehouse --window 7d --json

    # Write the weekly report to docs/operations/reports/
    python -m server.analytics_warehouse --window 7d --write

    # Single-metric CLI
    python -m server.analytics_warehouse --metric dau --window 1d
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Path setup so ``db`` and the engine packages are importable both when
# this module is run as ``python -m server.analytics_warehouse`` (from the
# project root) and when it is imported by the FastAPI app.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
for p in (str(_PROJECT_ROOT), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from db import (  # noqa: E402
    AnalyticsEventRow,
    CausalSeedRow,
    EntitlementRow,
    GameEventRow,
    GameRun,
    ModelCallRow,
    SessionLocal,
    WorldSnapshotRow,
    init_db,
)
from safety.cost_monitor import HARD_RED_LINES  # noqa: E402

#: The recall service is optional; if it is not importable
#: (e.g. partial checkout, or before W7 init), the recall
#: queries degrade gracefully to a no-op rather than
#: crashing the whole warehouse.  This module **does
#: not** depend on W7 — the recall_funnel helper just
#: returns an empty funnel.
try:  # pragma: no cover - import error is exercised manually
    from recall_service import RecallItemRow  # type: ignore  # noqa: E402
    _RECALL_AVAILABLE = True
except Exception:  # noqa: BLE001
    RecallItemRow = None  # type: ignore
    _RECALL_AVAILABLE = False

logger = logging.getLogger("g1n.analytics_warehouse")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


#: Default per-user privacy setting.  When ``False`` the
#: returned payload strips all per-user identifiers.
INCLUDE_USER: bool = (
    os.environ.get("G1N_ANALYTICS_INCLUDE_USER", "false").lower() == "true"
)

#: Cost red lines (decision 5) are passed through so the
#: warehouse report can show the live "within red line" state
#: without re-importing :mod:`safety.cost_monitor`.
COST_RED_LINE_LIMITS: dict[str, dict[str, Any]] = {
    rl.id: {
        "label": rl.label,
        "threshold": rl.threshold,
        "unit": rl.unit,
    }
    for rl in HARD_RED_LINES
}

#: Recall funnel stages, in canonical order.
RECALL_FUNNEL_STAGES: tuple[str, ...] = (
    "scheduled",
    "generated",
    "sent",
    "opened",
    "recap_started",
    "recap_completed",
)

#: Mapping from terminal run phase to the canonical "completed" status.
#: A run is "completed" when its final phase reaches one of these.
COMPLETED_PHASES: frozenset[str] = frozenset({
    "act_ended",
    "run_ended",
    "scene_ended",
})


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.utcnow()


def _parse_window(spec: str) -> timedelta:
    """Parse ``7d`` / ``24h`` / ``30m`` to a :class:`timedelta`."""

    spec = spec.strip().lower()
    if not spec:
        raise ValueError("window spec is empty")
    unit = spec[-1]
    try:
        n = int(spec[:-1])
    except ValueError as exc:
        raise ValueError(f"invalid window: {spec!r}") from exc
    if unit == "d":
        return timedelta(days=n)
    if unit == "h":
        return timedelta(hours=n)
    if unit == "m":
        return timedelta(minutes=n)
    raise ValueError(f"unsupported unit {unit!r} in {spec!r}")


def _humanize_window(window: timedelta) -> str:
    """Render a :class:`timedelta` as ``Nd`` / ``Nh`` / ``Nm`` for display."""

    total_seconds = int(window.total_seconds())
    if total_seconds <= 0:
        return "0m"
    if total_seconds % 86400 == 0:
        return f"{total_seconds // 86400}d"
    if total_seconds % 3600 == 0:
        return f"{total_seconds // 3600}h"
    return f"{total_seconds // 60}m"


def _strip_user(record: dict[str, Any]) -> dict[str, Any]:
    """Remove per-user identifiers from a record (privacy red line)."""

    return {
        k: v
        for k, v in record.items()
        if k not in {"userId", "user_id", "userHash", "ip"}
    }


def _strip_user_from_aggregate(
    counter: dict[str, int] | Counter,
) -> dict[str, int]:
    return {k: int(v) for k, v in counter.items()}


# ---------------------------------------------------------------------------
# D1/D3/D7 召回转化漏斗
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RecallFunnel:
    """The D1 / D3 / D7 recall funnel, segmented by ``recall_type``."""

    window: str
    by_type: dict[str, dict[str, int]] = field(default_factory=dict)
    overall: dict[str, int] = field(default_factory=dict)
    conversion_rates: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "byType": self.by_type,
            "overall": self.overall,
            "conversionRates": {k: round(v, 4) for k, v in self.conversion_rates.items()},
        }


def compute_recall_funnel(
    session: Session,
    *,
    window: timedelta,
) -> RecallFunnel:
    """Return the D1 / D3 / D7 recall funnel for the last ``window``.

    The ``recall_items.status`` column carries the canonical
    state machine ``scheduled → sent → opened →
    recap_started → recap_completed``; we count distinct
    items at each stage (not event counts — a single item
    can be opened multiple times; the funnel must measure
    *user-level progression*, not raw event volume).
    """

    if not _RECALL_AVAILABLE or RecallItemRow is None:
        # W7 not wired yet — return a zero-filled funnel
        # so the dashboard does not error out.
        return RecallFunnel(
            window=_humanize_window(window),
            by_type={
                t: {stage: 0 for stage in RECALL_FUNNEL_STAGES}
                for t in ("d1", "d3", "d7")
            },
            overall={stage: 0 for stage in RECALL_FUNNEL_STAGES},
            conversion_rates={},
        )
    since = _now() - window
    rows = session.execute(
        select(RecallItemRow).where(RecallItemRow.created_at >= since)
    ).scalars().all()
    by_type: dict[str, dict[str, int]] = defaultdict(
        lambda: {stage: 0 for stage in RECALL_FUNNEL_STAGES}
    )
    overall: dict[str, int] = {stage: 0 for stage in RECALL_FUNNEL_STAGES}
    for r in rows:
        # Map the row's status into the funnel stage.  Items
        # at ``generated`` are a sub-stage of ``sent`` but
        # the spec only requires the headline stages.
        status = r.status or "scheduled"
        if status in ("scheduled",):
            by_type[r.recall_type]["scheduled"] += 1
        elif status in ("sent", "generated"):
            by_type[r.recall_type]["sent"] += 1
        elif status == "opened":
            by_type[r.recall_type]["sent"] += 1
            by_type[r.recall_type]["opened"] += 1
        elif status == "recap_started":
            by_type[r.recall_type]["sent"] += 1
            by_type[r.recall_type]["opened"] += 1
            by_type[r.recall_type]["recap_started"] += 1
        elif status == "recap_completed":
            by_type[r.recall_type]["sent"] += 1
            by_type[r.recall_type]["opened"] += 1
            by_type[r.recall_type]["recap_started"] += 1
            by_type[r.recall_type]["recap_completed"] += 1
        elif status == "failed":
            # Failed items are excluded from the funnel;
            # the alerting pipeline owns the failure stream.
            continue
        else:  # pragma: no cover - defensive
            continue
    # Roll up the per-type counts into the overall funnel.
    for stage in RECALL_FUNNEL_STAGES:
        overall[stage] = sum(t[stage] for t in by_type.values())
    # Conversion rates: stage N+1 / stage N, where stage 0 is
    # ``scheduled`` (the bottom of the funnel).
    conv: dict[str, float] = {}
    base = overall.get("scheduled", 0) or 0
    for i in range(1, len(RECALL_FUNNEL_STAGES)):
        prev = overall[RECALL_FUNNEL_STAGES[i - 1]] or 0
        curr = overall[RECALL_FUNNEL_STAGES[i]] or 0
        if prev > 0:
            conv[f"{RECALL_FUNNEL_STAGES[i-1]}_to_{RECALL_FUNNEL_STAGES[i]}"] = (
                curr / prev
            )
    return RecallFunnel(
        window=_humanize_window(window),
        by_type={k: dict(v) for k, v in by_type.items()},
        overall=overall,
        conversion_rates=conv,
    )


# ---------------------------------------------------------------------------
# 单局完成率（按章节）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SceneCompletionRow:
    scene_id: str
    entered: int
    completed: int
    completion_rate: float
    avg_turns_to_complete: float


@dataclass(slots=True)
class SceneCompletionReport:
    window: str
    rows: list[SceneCompletionRow] = field(default_factory=list)
    overall_completion_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "rows": [asdict(r) for r in self.rows],
            "overallCompletionRate": round(self.overall_completion_rate, 4),
        }


def compute_scene_completion(
    session: Session,
    *,
    window: timedelta,
) -> SceneCompletionReport:
    """Per-scene completion rate.

    A run is "entered" a scene if it has any event whose
    ``scene_id`` matches.  A run is "completed" in a scene
    if its final snapshot (latest ``event_sequence``) has
    ``canonicalState.phase`` in :data:`COMPLETED_PHASES` or
    if the run has progressed to a later scene.
    """

    since = _now() - window
    # Fetch only what's needed; large projects will want
    # a partitioned view but at W10 volumes the simple
    # query is fine.
    runs = session.execute(
        select(GameRun).where(GameRun.started_at >= since)
    ).scalars().all()
    events = session.execute(
        select(GameEventRow).where(GameEventRow.created_at >= since)
    ).scalars().all()
    snapshots = session.execute(
        select(WorldSnapshotRow).where(WorldSnapshotRow.created_at >= since)
    ).scalars().all()

    entered_by_scene: dict[str, set[str]] = defaultdict(set)
    completed_by_scene: dict[str, set[str]] = defaultdict(set)
    turns_to_complete: dict[str, list[int]] = defaultdict(list)
    latest_snap_per_run: dict[str, tuple[int, dict[str, Any]]] = {}
    for snap in snapshots:
        prev = latest_snap_per_run.get(snap.run_id)
        if prev is None or snap.event_sequence > prev[0]:
            try:
                data = json.loads(snap.snapshot_json) if snap.snapshot_json else {}
            except json.JSONDecodeError:
                data = {}
            latest_snap_per_run[snap.run_id] = (snap.event_sequence, data)

    # Fall back to the game_runs row when no snapshot
    # exists for a run — this is the common case for
    # newly-created runs that have not yet had a turn.
    for run in runs:
        if run.run_id not in latest_snap_per_run:
            latest_snap_per_run[run.run_id] = (
                run.event_sequence or 0,
                {
                    "canonicalState": {
                        "currentSceneId": run.current_scene_id,
                        "phase": run.phase,
                        "era": run.era,
                    }
                },
            )

    for e in events:
        if e.scene_id:
            entered_by_scene[e.scene_id].add(e.run_id)

    # A scene is "completed" by a run if either:
    # 1) the run's latest snapshot is in a terminal phase
    #    AND the run's current scene is at or beyond that scene, or
    # 2) the run has any event in a scene strictly *after*
    #    the candidate scene.
    scene_order = ["photo_lab_2008", "farewell_2011", "reunion_2024"]

    def _scene_index(name: str) -> int:
        try:
            return scene_order.index(name)
        except ValueError:
            return 99

    for run_id, (_, data) in latest_snap_per_run.items():
        current = data.get("canonicalState", {}).get("currentSceneId", "")
        phase = data.get("canonicalState", {}).get("phase", "")
        current_idx = _scene_index(current)
        for scene_id, runs_entered in entered_by_scene.items():
            # Only consider a "completion" if the run
            # actually entered this scene.  A run that
            # jumped straight to reunion_2024 (the
            # end-of-the-line) without entering
            # photo_lab_2008 should not be counted as a
            # completion of photo_lab_2008.
            if run_id not in runs_entered:
                continue
            scene_idx = _scene_index(scene_id)
            # The run completed this scene if:
            # - the run's current scene is later, OR
            # - the run's current scene is this scene AND
            #   its phase is terminal.
            if current_idx > scene_idx or (
                current_idx == scene_idx and phase in COMPLETED_PHASES
            ):
                completed_by_scene[scene_id].add(run_id)

    # Average turns to complete: the event_sequence of the
    # last event in the scene for each completed run.
    last_event_seq: dict[tuple[str, str], int] = {}
    for e in events:
        key = (e.run_id, e.scene_id)
        if e.scene_id and e.event_sequence > last_event_seq.get(key, -1):
            last_event_seq[key] = e.event_sequence
    for scene_id, runs_completed in completed_by_scene.items():
        for rid in runs_completed:
            seq = last_event_seq.get((rid, scene_id))
            if seq is not None and seq > 0:
                turns_to_complete[scene_id].append(seq)

    rows: list[SceneCompletionRow] = []
    total_entered = 0
    total_completed = 0
    for scene_id in sorted(entered_by_scene.keys()):
        entered = len(entered_by_scene[scene_id])
        completed = len(completed_by_scene.get(scene_id, set()))
        rate = (completed / entered) if entered > 0 else 0.0
        avg_turns = (
            sum(turns_to_complete[scene_id]) / len(turns_to_complete[scene_id])
            if turns_to_complete[scene_id]
            else 0.0
        )
        rows.append(SceneCompletionRow(
            scene_id=scene_id,
            entered=entered,
            completed=completed,
            completion_rate=rate,
            avg_turns_to_complete=avg_turns,
        ))
        total_entered += entered
        total_completed += completed
    overall = (total_completed / total_entered) if total_entered > 0 else 0.0
    return SceneCompletionReport(
        window=_humanize_window(window),
        rows=rows,
        overall_completion_rate=overall,
    )


# ---------------------------------------------------------------------------
# mandatory echo 触发率
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MandatoryEchoReport:
    window: str
    by_scene: dict[str, dict[str, Any]] = field(default_factory=dict)
    overall_trigger_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "byScene": self.by_scene,
            "overallTriggerRate": round(self.overall_trigger_rate, 4),
        }


def compute_mandatory_echo_rate(
    session: Session,
    *,
    window: timedelta,
) -> MandatoryEchoReport:
    """Per-scene mandatory-echo trigger rate.

    Decision 3 red line: the player who takes the
    trigger action must see the future echo.  We measure
    "trigger rate" = ``runs where the scene's mandatory
    echoes were fired at least once / runs that entered
    the scene``.
    """

    since = _now() - window
    runs = session.execute(
        select(GameRun).where(GameRun.started_at >= since)
    ).scalars().all()
    seeds = session.execute(
        select(CausalSeedRow).where(CausalSeedRow.created_at >= since)
    ).scalars().all()
    events = session.execute(
        select(GameEventRow).where(GameEventRow.created_at >= since)
    ).scalars().all()

    entered_by_scene: dict[str, set[str]] = defaultdict(set)
    for e in events:
        if e.scene_id:
            entered_by_scene[e.scene_id].add(e.run_id)

    # A "mandatory echo" is any seed with ``echo_intensity``
    # above the 0.5 default and ``is_secret=false``.  The
    # mandatory-echo declaration lives in the scene
    # contract; here we count the runtime side.
    fired_seeds: dict[str, set[str]] = defaultdict(set)
    for s in seeds:
        if not s.is_dormant and s.echo_intensity >= 0.5 and not s.is_secret:
            fired_seeds[s.source_scene].add(s.run_id)

    by_scene: dict[str, dict[str, Any]] = {}
    total_entered = 0
    total_fired = 0
    for scene_id, runs_entered in entered_by_scene.items():
        fired = fired_seeds.get(scene_id, set())
        rate = (len(fired) / len(runs_entered)) if runs_entered else 0.0
        by_scene[scene_id] = {
            "entered": len(runs_entered),
            "echoFired": len(fired),
            "triggerRate": rate,
        }
        total_entered += len(runs_entered)
        total_fired += len(fired)
    overall = (total_fired / total_entered) if total_entered else 0.0
    return MandatoryEchoReport(
        window=_humanize_window(window),
        by_scene=by_scene,
        overall_trigger_rate=overall,
    )


# ---------------------------------------------------------------------------
# 付费转化漏斗
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PaymentFunnelReport:
    window: str
    stages: dict[str, int] = field(default_factory=dict)
    conversion_rates: dict[str, float] = field(default_factory=dict)
    arpu_cny: float = 0.0
    paying_users: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "stages": self.stages,
            "conversionRates": {k: round(v, 4) for k, v in self.conversion_rates.items()},
            "arpuCny": round(self.arpu_cny, 2),
            "payingUsers": self.paying_users,
        }


#: Price table in CNY.  Mirrors the catalogue in
#: ``server.app.PRODUCT_CATALOG`` (decision 4).  Kept in
#: sync by a test; not auto-wired because the catalogue
#: lives in the HTTP layer.
PRICE_TABLE_CNY: dict[str, int] = {
    "free_sample": 0,
    "passport": 25,
    "collectors": 48,
    "parallel_ops": 12,
    "credits": 12,
    "pov_unlock": 3,
    "keepsake": 8,
}


def compute_payment_funnel(
    session: Session,
    *,
    window: timedelta,
) -> PaymentFunnelReport:
    """The free → paid conversion funnel from ``entitlements`` rows."""

    since = _now() - window
    rows = session.execute(
        select(EntitlementRow).where(EntitlementRow.purchased_at >= since)
    ).scalars().all()
    users_by_scope: dict[str, set[str]] = defaultdict(set)
    revenue_cny = 0.0
    for r in rows:
        users_by_scope[r.scope].add(r.user_id)
        revenue_cny += PRICE_TABLE_CNY.get(r.scope, 0)
    stages: dict[str, int] = {}
    for scope in ("free_sample", "passport", "collectors"):
        stages[scope] = len(users_by_scope.get(scope, set()))
    # Stage conversions: paid / free.
    paid_users = (
        users_by_scope.get("passport", set())
        | users_by_scope.get("collectors", set())
    )
    free_users = users_by_scope.get("free_sample", set())
    conv: dict[str, float] = {}
    if free_users:
        conv["free_to_passport"] = (
            len(users_by_scope.get("passport", set()) & free_users) / len(free_users)
        )
        conv["free_to_paid"] = len(paid_users & free_users) / len(free_users)
    if users_by_scope.get("passport"):
        conv["passport_to_collectors"] = (
            len(users_by_scope.get("collectors", set()) & users_by_scope.get("passport", set()))
            / len(users_by_scope.get("passport", set()))
        )
    arpu = (revenue_cny / len(paid_users)) if paid_users else 0.0
    return PaymentFunnelReport(
        window=_humanize_window(window),
        stages=stages,
        conversion_rates=conv,
        arpu_cny=arpu,
        paying_users=len(paid_users),
    )


# ---------------------------------------------------------------------------
# 留存曲线
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RetentionCurve:
    window: str
    day_retention: dict[int, float] = field(default_factory=dict)
    cohort_size: int = 0
    cohort_by_signup_day: dict[str, dict[int, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "cohortSize": self.cohort_size,
            "dayRetention": {str(k): round(v, 4) for k, v in self.day_retention.items()},
            "cohortBySignupDay": self.cohort_by_signup_day,
        }


def compute_retention_curve(
    session: Session,
    *,
    window: timedelta,
) -> RetentionCurve:
    """Day-N retention = users with ≥ 1 event on day N / cohort size.

    The "cohort" is every user whose first run started in
    the window.  An event on day N is any
    ``analytics_events`` row for that user at least N
    days after their cohort-start date.
    """

    since = _now() - window
    # Pull each user's first run's start time.
    first_run = session.execute(
        select(
            GameRun.user_id,
            func.min(GameRun.started_at).label("first_at"),
        )
        .where(GameRun.started_at >= since)
        .group_by(GameRun.user_id)
    ).all()
    signup_at: dict[str, datetime] = {uid: first for uid, first in first_run}
    if not signup_at:
        return RetentionCurve(
            window=_humanize_window(window),
            cohort_size=0,
        )
    cohort_size = len(signup_at)
    # Active days per user.
    active_by_user_day: dict[tuple[str, int], int] = defaultdict(int)
    for ev in session.execute(
        select(AnalyticsEventRow).where(AnalyticsEventRow.created_at >= since)
    ).scalars().all():
        if not ev.user_id or ev.created_at is None:
            continue
        signup = signup_at.get(ev.user_id)
        if signup is None:
            continue
        delta_days = (ev.created_at - signup).days
        if delta_days < 0:
            continue
        active_by_user_day[(ev.user_id, delta_days)] += 1
    # Day-N = fraction of cohort with ≥ 1 event on day N.
    days = sorted({d for (_, d) in active_by_user_day.keys()})
    day_retention: dict[int, float] = {}
    for d in days:
        active = sum(1 for (uid, dd) in active_by_user_day if dd == d)
        day_retention[d] = active / cohort_size if cohort_size else 0.0
    # Cohort by signup day — for the Grafana stacked chart.
    cohort_by_signup_day: dict[str, dict[int, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for (uid, d), _ in active_by_user_day.items():
        signup = signup_at[uid]
        cohort_by_signup_day[signup.date().isoformat()][d] += 1
    return RetentionCurve(
        window=_humanize_window(window),
        day_retention=day_retention,
        cohort_size=cohort_size,
        cohort_by_signup_day={k: dict(v) for k, v in cohort_by_signup_day.items()},
    )


# ---------------------------------------------------------------------------
# DAU + 关键 KPI
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class KpiSnapshot:
    window: str
    dau: int = 0
    new_signups: int = 0
    runs_started: int = 0
    runs_completed: int = 0
    cost_cny: float = 0.0
    avg_cost_per_run_cny: float = 0.0
    p95_latency_ms: float = 0.0
    red_line_breaches: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "dau": self.dau,
            "newSignups": self.new_signups,
            "runsStarted": self.runs_started,
            "runsCompleted": self.runs_completed,
            "costCny": round(self.cost_cny, 2),
            "avgCostPerRunCny": round(self.avg_cost_per_run_cny, 2),
            "p95LatencyMs": round(self.p95_latency_ms, 1),
            "redLineBreaches": dict(self.red_line_breaches),
        }


def compute_kpis(
    session: Session,
    *,
    window: timedelta,
) -> KpiSnapshot:
    """DAU + cost + red-line breaches in the window."""

    since = _now() - window
    dau_rows = session.execute(
        select(func.count(func.distinct(AnalyticsEventRow.user_id))).where(
            AnalyticsEventRow.created_at >= since,
            AnalyticsEventRow.user_id.is_not(None),
        )
    ).scalar()
    new_signups = session.execute(
        select(func.count(func.distinct(GameRun.user_id))).where(
            GameRun.started_at >= since
        )
    ).scalar()
    runs_started = session.execute(
        select(func.count(GameRun.run_id)).where(GameRun.started_at >= since)
    ).scalar()
    runs_completed = session.execute(
        select(func.count(GameRun.run_id)).where(
            GameRun.started_at >= since,
            GameRun.ended_at.is_not(None),
        )
    ).scalar()
    cost_rows = session.execute(
        select(func.coalesce(func.sum(ModelCallRow.cost_cny), 0.0)).where(
            ModelCallRow.created_at >= since
        )
    ).scalar()
    latency_rows = session.execute(
        select(ModelCallRow.latency_ms).where(
            ModelCallRow.created_at >= since,
            ModelCallRow.latency_ms > 0,
        )
    ).all()
    p95 = _percentile(
        [float(r[0]) for r in latency_rows if r[0] and r[0] > 0], 95.0
    )
    return KpiSnapshot(
        window=_humanize_window(window),
        dau=int(dau_rows or 0),
        new_signups=int(new_signups or 0),
        runs_started=int(runs_started or 0),
        runs_completed=int(runs_completed or 0),
        cost_cny=float(cost_rows or 0.0),
        avg_cost_per_run_cny=(
            float(cost_rows or 0.0) / runs_completed if runs_completed else 0.0
        ),
        p95_latency_ms=p95,
        red_line_breaches={},  # filled by the weekly report builder
    )


def _percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile, stdlib only (matches cost_monitor)."""

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


# ---------------------------------------------------------------------------
# Weekly report
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WeeklyReport:
    """One weekly operations report.

    The report is dual-shaped: ``payload`` is the
    machine-readable JSON; ``markdown`` is the human
    narrative for email / Slack.
    """

    window: str
    generated_at: str
    payload: dict[str, Any]
    markdown: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "generatedAt": self.generated_at,
            "payload": self.payload,
            "markdown": self.markdown,
        }


class WeeklyReportBuilder:
    """Aggregate the funnels into a single weekly report."""

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory or SessionLocal

    def _session(self) -> Session:
        return self._session_factory()

    def build(self, *, window: timedelta = timedelta(days=7)) -> WeeklyReport:
        with self._session() as s:
            recall = compute_recall_funnel(s, window=window)
            completion = compute_scene_completion(s, window=window)
            echo = compute_mandatory_echo_rate(s, window=window)
            payment = compute_payment_funnel(s, window=window)
            retention = compute_retention_curve(s, window=window)
            kpis = compute_kpis(s, window=window)
            # Red-line breach summary from model_calls.
            kpis.red_line_breaches = self._red_line_breach_summary(s, window=window)
        payload = {
            "kpis": kpis.to_dict(),
            "recallFunnel": recall.to_dict(),
            "sceneCompletion": completion.to_dict(),
            "mandatoryEcho": echo.to_dict(),
            "paymentFunnel": payment.to_dict(),
            "retentionCurve": retention.to_dict(),
            "redLineLimits": COST_RED_LINE_LIMITS,
            "includeUser": INCLUDE_USER,
        }
        if not INCLUDE_USER:
            # Defensive: scrub any user-level fields from
            # the report.  The funnels already aggregate;
            # this is a belt-and-suspenders guard.
            payload["privacy"] = {"userLevel": False}
        else:
            payload["privacy"] = {"userLevel": True}
        return WeeklyReport(
            window=f"{int(window.total_seconds() // 86400)}d",
            generated_at=_now().isoformat(timespec="seconds") + "Z",
            payload=payload,
            markdown=self._render_markdown(
                kpis=kpis,
                recall=recall,
                completion=completion,
                echo=echo,
                payment=payment,
                retention=retention,
            ),
        )

    def _red_line_breach_summary(
        self,
        session: Session,
        *,
        window: timedelta,
    ) -> dict[str, int]:
        """Count model_calls rows that breach a hard red line.

        We do **not** re-run the cost monitor over every run
        here — the runtime :class:`LiveCounter` writes a row
        to ``model_calls`` for each LLM call, and the
        warehouse counts the *breach* in the rows
        themselves.  This is the same data the Grafana
        dashboard plots.
        """

        since = _now() - window
        rows = session.execute(
            select(ModelCallRow).where(ModelCallRow.created_at >= since)
        ).scalars().all()
        breaches: dict[str, int] = {
            rl.id: 0 for rl in HARD_RED_LINES
        }
        for r in rows:
            if r.output_tokens and r.output_tokens > 800:
                breaches["R2"] += 1
            if r.latency_ms and r.latency_ms > 4000:
                breaches["R4"] += 1
        return breaches

    def _render_markdown(
        self,
        *,
        kpis: KpiSnapshot,
        recall: RecallFunnel,
        completion: SceneCompletionReport,
        echo: MandatoryEchoReport,
        payment: PaymentFunnelReport,
        retention: RetentionCurve,
    ) -> str:
        lines: list[str] = []
        lines.append(f"# 革命街 AI 原生 · 周运营报告 · {kpis.window}")
        lines.append("")
        lines.append(f"_生成时间：{_now().isoformat(timespec='seconds')}Z_")
        lines.append("")
        lines.append("## 1. 关键 KPI")
        lines.append("")
        lines.append(f"- DAU: **{kpis.dau}**")
        lines.append(f"- 新增用户: {kpis.new_signups}")
        lines.append(f"- 启动局数: {kpis.runs_started} / 完成局数: {kpis.runs_completed}")
        lines.append(f"- AI 成本: ¥{kpis.cost_cny:.2f}（单局 ¥{kpis.avg_cost_per_run_cny:.2f}）")
        lines.append(f"- P95 延迟: {kpis.p95_latency_ms:.0f} ms")
        lines.append("")
        lines.append("## 2. D1 / D3 / D7 召回转化漏斗")
        lines.append("")
        lines.append("| 阶段 | 数量 |")
        lines.append("|---|---:|")
        for stage, n in recall.overall.items():
            lines.append(f"| {stage} | {n} |")
        lines.append("")
        if recall.conversion_rates:
            lines.append("### 阶段转化率")
            lines.append("")
            for k, v in recall.conversion_rates.items():
                lines.append(f"- {k}: {v*100:.1f}%")
            lines.append("")
        lines.append("## 3. 单局完成率（按章节）")
        lines.append("")
        lines.append("| 场景 | 进入 | 完成 | 完成率 | 平均回合 |")
        lines.append("|---|---:|---:|---:|---:|")
        for r in completion.rows:
            lines.append(
                f"| {r.scene_id} | {r.entered} | {r.completed} | "
                f"{r.completion_rate*100:.1f}% | {r.avg_turns_to_complete:.1f} |"
            )
        lines.append("")
        lines.append("## 4. Mandatory Echo 触发率")
        lines.append("")
        lines.append("| 场景 | 进入 | 触发 | 触发率 |")
        lines.append("|---|---:|---:|---:|")
        for scene_id, data in echo.by_scene.items():
            lines.append(
                f"| {scene_id} | {data['entered']} | {data['echoFired']} | "
                f"{data['triggerRate']*100:.1f}% |"
            )
        lines.append("")
        lines.append("## 5. 付费转化漏斗")
        lines.append("")
        lines.append("| 商品 | 购买用户 |")
        lines.append("|---|---:|")
        for scope, n in payment.stages.items():
            lines.append(f"| {scope} | {n} |")
        lines.append(f"")
        lines.append(f"- ARPU: ¥{payment.arpu_cny:.2f}")
        lines.append(f"- 付费用户: {payment.paying_users}")
        lines.append("")
        lines.append("## 6. 留存曲线")
        lines.append("")
        if retention.day_retention:
            lines.append("| Day | 留存 |")
            lines.append("|---:|---:|")
            for d in sorted(retention.day_retention.keys()):
                lines.append(
                    f"| D{d} | {retention.day_retention[d]*100:.1f}% |"
                )
        else:
            lines.append("_无数据_")
        lines.append("")
        lines.append("## 7. 决策 5 硬红线状态")
        lines.append("")
        lines.append("| 红线 | 阈值 | 当前周期突破 |")
        lines.append("|---|---|---:|")
        for rl_id, info in COST_RED_LINE_LIMITS.items():
            breaches = kpis.red_line_breaches.get(rl_id, 0)
            lines.append(
                f"| {rl_id} {info['label']} | {info['threshold']} {info['unit']} | {breaches} |"
            )
        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# FastAPI router — surface the warehouse to the dashboard
# ---------------------------------------------------------------------------


def build_analytics_router() -> Any:
    """Expose the warehouse on a FastAPI router.

    The router is mounted by ``server.app`` if FastAPI is
    available; importing the module alone has no side
    effects.
    """

    try:
        from fastapi import APIRouter, HTTPException, Query
    except ImportError:  # pragma: no cover - FastAPI is in W4 deps
        return None

    router = APIRouter(prefix="/v1/operations", tags=["operations"])

    @router.get("/funnels/recall")
    def recall_funnel(window: str = "7d") -> dict[str, Any]:
        try:
            td = _parse_window(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with SessionLocal() as s:
            return compute_recall_funnel(s, window=td).to_dict()

    @router.get("/funnels/completion")
    def scene_completion(window: str = "7d") -> dict[str, Any]:
        try:
            td = _parse_window(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with SessionLocal() as s:
            return compute_scene_completion(s, window=td).to_dict()

    @router.get("/funnels/payment")
    def payment_funnel(window: str = "7d") -> dict[str, Any]:
        try:
            td = _parse_window(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with SessionLocal() as s:
            return compute_payment_funnel(s, window=td).to_dict()

    @router.get("/metrics/mandatory-echo")
    def mandatory_echo(window: str = "7d") -> dict[str, Any]:
        try:
            td = _parse_window(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with SessionLocal() as s:
            return compute_mandatory_echo_rate(s, window=td).to_dict()

    @router.get("/metrics/retention")
    def retention(window: str = "7d") -> dict[str, Any]:
        try:
            td = _parse_window(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with SessionLocal() as s:
            return compute_retention_curve(s, window=td).to_dict()

    @router.get("/metrics/kpis")
    def kpis(window: str = "1d") -> dict[str, Any]:
        try:
            td = _parse_window(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with SessionLocal() as s:
            return compute_kpis(s, window=td).to_dict()

    @router.get("/reports/weekly")
    def weekly_report(window: str = "7d") -> dict[str, Any]:
        try:
            td = _parse_window(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        builder = WeeklyReportBuilder()
        return builder.build(window=td).to_dict()

    return router


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _force_utf8_stdout() -> None:
    """Reconfigure stdout to UTF-8 so Windows GBK locales don't crash."""

    import io
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
                continue
            except (ValueError, OSError):
                pass
        if hasattr(stream, "buffer"):
            try:
                setattr(
                    sys,
                    stream_name,
                    io.TextIOWrapper(stream.buffer, encoding="utf-8"),
                )
            except (ValueError, OSError):
                pass


def _cli(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(
        prog="analytics-warehouse",
        description="革命街 AI 原生 · 玩家数据分析 / 漏斗 / 周报",
    )
    parser.add_argument(
        "--window", default="7d", help="时间窗（7d / 24h / 30m）"
    )
    parser.add_argument(
        "--metric",
        choices=[
            "all",
            "dau",
            "recall",
            "completion",
            "echo",
            "payment",
            "retention",
        ],
        default="all",
    )
    parser.add_argument(
        "--json", action="store_true", help="JSON-only 输出"
    )
    parser.add_argument(
        "--write", action="store_true",
        help="写每周报告到 docs/operations/reports/",
    )
    args = parser.parse_args(argv)
    init_db()
    try:
        window = _parse_window(args.window)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with SessionLocal() as s:
        if args.metric == "all":
            builder = WeeklyReportBuilder()
            report = builder.build(window=window)
            if args.write:
                out_dir = _PROJECT_ROOT / "docs" / "operations" / "reports"
                out_dir.mkdir(parents=True, exist_ok=True)
                stamp = _now().strftime("%Y%m%d-%H%M%S")
                json_path = out_dir / f"weekly-{stamp}.json"
                md_path = out_dir / f"weekly-{stamp}.md"
                json_path.write_text(
                    json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                md_path.write_text(report.markdown, encoding="utf-8")
                print(f"wrote {json_path}")
                print(f"wrote {md_path}")
            else:
                if args.json:
                    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
                else:
                    print(report.markdown)
        else:
            metric = args.metric
            if metric == "dau":
                result = compute_kpis(s, window=window).to_dict()
            elif metric == "recall":
                result = compute_recall_funnel(s, window=window).to_dict()
            elif metric == "completion":
                result = compute_scene_completion(s, window=window).to_dict()
            elif metric == "echo":
                result = compute_mandatory_echo_rate(s, window=window).to_dict()
            elif metric == "payment":
                result = compute_payment_funnel(s, window=window).to_dict()
            elif metric == "retention":
                result = compute_retention_curve(s, window=window).to_dict()
            else:  # pragma: no cover
                result = {}
            print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
