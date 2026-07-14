"""
replay-lab/replay.py
====================
Snapshot replay engine for 《革命街没有尽头》.

A "replay" takes:
  1. an **initial world snapshot** (canonical state at the start of the
     run), and
  2. an **event log** — an ordered sequence of ResolverOutcome-style
     entries (see ``server/config/schemas/resolver_outcome.schema.json``).

It walks the log in ``eventSequence`` order and applies each event's
``canonicalDelta`` to the running state, producing a final snapshot
plus a per-event trace (what changed, what stayed the same).

This is the debugging / QA / analytics backbone for the project.  It
is intentionally simple: no model calls, no async I/O, pure-Python
state reducer.

Key public surface
------------------
* ``EventLogEntry``     — dataclass for one event
* ``ReplayResult``      — dataclass for the aggregated replay
* ``replay(initial_snapshot, events)`` — the reducer
* ``load_event_log(path)`` / ``dump_replay(result, path)`` — I/O helpers

Event-log format (YAML / JSON)
-------------------------------
The on-disk format is a list of objects with at least these keys::

    - eventSequence: 0
      outcomeId: 00000000-0000-4000-8000-000000000001
      timestamp: 2026-07-14T12:00:00Z
      sceneId: photo_lab_2008
      actionType: give
      actorId: leila
      targetId: arash
      artifact_updates:           # applied to snapshot.artifactState
        - artifactId: photo_pair
          newOwnerId: arash
          newState: "夹进诗集"
          newLocation: "阿拉什夹克内袋"
      belief_updates:            # applied to snapshot.beliefMatrices
        - characterId: arash
          subject: photo_pair_ownership
          belief_state: certain
          confidence: 0.9
      event_log:                 # appended to the event log ring
        - eventId: evt_001
          description: "莱拉把同版照片给了阿拉什"
      causal_seeds:              # merged into snapshot.causalSeedsActive
        - seedId: photo_in_book
          planted: true
          intensity: 0.9
      turn_index: 1              # advances snapshot.canonicalState.turnIndex

Fields are optional — an event can be a pure dialogue event with no
state change, in which case only ``eventSequence`` / ``outcomeId`` are
required.
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EventLogEntry:
    """One event in the log.  Mirrors ResolverOutcome with a
    ``canonicalDelta`` payload."""

    eventSequence: int
    outcomeId: str
    timestamp: str
    sceneId: str | None = None
    actionType: str | None = None
    actorId: str | None = None
    targetId: str | None = None
    artifact_updates: list[dict[str, Any]] = field(default_factory=list)
    belief_updates: list[dict[str, Any]] = field(default_factory=list)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    causal_seeds: list[dict[str, Any]] = field(default_factory=list)
    turn_index: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Don't serialise the raw passthrough twice.
        d.pop("raw", None)
        return d


@dataclass
class ReplayTraceEntry:
    """One step of the replay — what changed when this event fired."""

    eventSequence: int
    outcomeId: str
    sceneId: str | None
    actionType: str | None
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    resulting_turn_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReplayResult:
    """Aggregate replay output."""

    runId: str
    initial_event_sequence: int
    final_event_sequence: int
    events_applied: int
    events_skipped: int
    final_snapshot: dict[str, Any]
    trace: list[ReplayTraceEntry] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.runId,
            "initial_event_sequence": self.initial_event_sequence,
            "final_event_sequence": self.final_event_sequence,
            "events_applied": self.events_applied,
            "events_skipped": self.events_skipped,
            "final_snapshot": self.final_snapshot,
            "trace": [t.to_dict() for t in self.trace],
            "summary": dict(self.summary),
        }


# ---------------------------------------------------------------------------
# Event-log I/O
# ---------------------------------------------------------------------------


def load_event_log(path: str) -> list[EventLogEntry]:
    """Load an event log from a YAML or JSON file.

    The file is expected to be either a top-level list of events or a
    mapping under the key ``events``.
    """
    with open(path, "r", encoding="utf-8") as fp:
        text = fp.read()
    if path.lower().endswith(".json"):
        data = json.loads(text)
    else:
        if yaml is None:  # pragma: no cover
            raise RuntimeError("PyYAML is required for .yaml event logs")
        data = yaml.safe_load(text)
    if isinstance(data, dict) and "events" in data:
        data = data["events"]
    if not isinstance(data, list):
        raise ValueError(
            f"event log must be a list of events (or {{events: [...]}}); "
            f"got {type(data).__name__}: {path}"
        )
    entries: list[EventLogEntry] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            entries.append(_entry_from_dict(item))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"invalid event entry {item!r}: {exc}") from exc
    # Ensure strictly increasing eventSequence.
    entries.sort(key=lambda e: e.eventSequence)
    return entries


def _entry_from_dict(item: dict[str, Any]) -> EventLogEntry:
    """Build an EventLogEntry from a dict.  Fills defaults."""
    seq = int(item.get("eventSequence", item.get("seq", 0)))
    oid = str(item.get("outcomeId", item.get("id", _make_outcome_id())))
    ts = str(item.get("timestamp", item.get("ts", "")))
    return EventLogEntry(
        eventSequence=seq,
        outcomeId=oid,
        timestamp=ts,
        sceneId=item.get("sceneId"),
        actionType=item.get("actionType"),
        actorId=item.get("actorId"),
        targetId=item.get("targetId"),
        artifact_updates=list(item.get("artifact_updates", []) or []),
        belief_updates=list(item.get("belief_updates", []) or []),
        event_log=list(item.get("event_log", []) or []),
        causal_seeds=list(item.get("causal_seeds", []) or []),
        turn_index=item.get("turn_index"),
        raw=dict(item),
    )


def _make_outcome_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# The replay reducer
# ---------------------------------------------------------------------------


def replay(
    initial_snapshot: dict[str, Any],
    events: Iterable[EventLogEntry],
    *,
    runId: str | None = None,
    stop_at: int | None = None,
) -> ReplayResult:
    """Walk ``events`` in order, applying each event's delta to a
    working copy of ``initial_snapshot``.  Returns the final snapshot
    plus a per-event trace.

    Parameters
    ----------
    initial_snapshot:
        The canonical world snapshot at the start of the run.  See
        ``server/config/schemas/world_snapshot.schema.json`` for the
        full shape.
    events:
        An iterable of EventLogEntry.  Order matters; if the iterable
        is not already sorted, the replay will sort it by
        ``eventSequence``.
    runId:
        Override the runId of the output snapshot.  Defaults to the
        snapshot's own ``runId`` field.
    stop_at:
        If given, the replay halts once it processes an event with
        ``eventSequence >= stop_at``.  Useful for "replay up to turn N"
        debugging.
    """
    snapshot = copy.deepcopy(initial_snapshot)
    runId_out = runId or str(snapshot.get("runId", ""))
    if runId is not None:
        # If the caller overrode the runId, propagate it to the snapshot
        # too so the final_snapshot is self-identifying.
        snapshot["runId"] = runId
    event_list = sorted(events, key=lambda e: e.eventSequence)

    initial_event_sequence = int(snapshot.get("eventSequence", 0))
    applied = 0
    skipped = 0
    trace: list[ReplayTraceEntry] = []

    for ev in event_list:
        if stop_at is not None and ev.eventSequence > stop_at:
            skipped += 1
            trace.append(ReplayTraceEntry(
                eventSequence=ev.eventSequence,
                outcomeId=ev.outcomeId,
                sceneId=ev.sceneId,
                actionType=ev.actionType,
                applied=[],
                skipped=[f"stop_at={stop_at}"],
                resulting_turn_index=_current_turn(snapshot),
            ))
            continue

        # 1) artifact updates: append or replace
        applied_labels: list[str] = []
        for upd in ev.artifact_updates:
            if not isinstance(upd, dict):
                continue
            aid = upd.get("artifactId")
            if not aid:
                continue
            _apply_artifact_update(snapshot, aid, upd)
            applied_labels.append(f"artifact:{aid}")

        # 2) belief updates
        for upd in ev.belief_updates:
            if not isinstance(upd, dict):
                continue
            cid = upd.get("characterId")
            if not cid:
                continue
            _apply_belief_update(snapshot, cid, upd)
            applied_labels.append(f"belief:{cid}/{upd.get('subject', '?')}")

        # 3) event log ring buffer
        for entry in ev.event_log:
            if not isinstance(entry, dict):
                continue
            snapshot.setdefault("eventLog", []).append(entry)
            applied_labels.append(f"event:{entry.get('eventId', '?')}")

        # 4) causal seeds
        for seed in ev.causal_seeds:
            if not isinstance(seed, dict):
                continue
            _apply_causal_seed(snapshot, seed)
            applied_labels.append(f"seed:{seed.get('seedId', '?')}")

        # 5) turn index advance
        if ev.turn_index is not None:
            try:
                new_turn = int(ev.turn_index)
                _advance_turn(snapshot, new_turn)
                applied_labels.append(f"turn:{new_turn}")
            except (TypeError, ValueError):
                skipped += 1
                applied_labels.append("turn:invalid")

        # 6) bump the snapshot's eventSequence
        snapshot["eventSequence"] = max(
            int(snapshot.get("eventSequence", 0)),
            ev.eventSequence,
        )

        applied += 1
        trace.append(ReplayTraceEntry(
            eventSequence=ev.eventSequence,
            outcomeId=ev.outcomeId,
            sceneId=ev.sceneId,
            actionType=ev.actionType,
            applied=applied_labels,
            skipped=[],
            resulting_turn_index=_current_turn(snapshot),
        ))

    summary = {
        "events_applied": applied,
        "events_skipped": skipped,
        "artifacts": len(snapshot.get("artifactState", [])),
        "belief_matrices": len(snapshot.get("beliefMatrices", [])),
        "causal_seeds": len(snapshot.get("causalSeedsActive", [])),
        "event_log": len(snapshot.get("eventLog", [])),
    }

    return ReplayResult(
        runId=runId_out,
        initial_event_sequence=initial_event_sequence,
        final_event_sequence=int(snapshot.get("eventSequence", 0)),
        events_applied=applied,
        events_skipped=skipped,
        final_snapshot=snapshot,
        trace=trace,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _current_turn(snapshot: dict[str, Any]) -> int | None:
    canonical = snapshot.get("canonicalState") or {}
    try:
        return int(canonical.get("turnIndex", 0))
    except (TypeError, ValueError):
        return None


def _advance_turn(snapshot: dict[str, Any], new_turn: int) -> None:
    canonical = snapshot.setdefault("canonicalState", {})
    try:
        canonical["turnIndex"] = max(int(canonical.get("turnIndex", 0)), new_turn)
    except (TypeError, ValueError):
        pass


def _apply_artifact_update(
    snapshot: dict[str, Any], artifact_id: str, upd: dict[str, Any]
) -> None:
    state = snapshot.setdefault("artifactState", [])
    # Replace if exists, else append.
    for i, art in enumerate(state):
        if isinstance(art, dict) and art.get("artifactId") == artifact_id:
            merged = {**art, **upd}
            # Map our shorthand keys back to the schema.
            if "newOwnerId" in upd:
                merged["ownerId"] = upd["newOwnerId"]
            if "newState" in upd:
                merged["state"] = upd["newState"]
            if "newLocation" in upd:
                merged["location"] = upd["newLocation"]
            state[i] = merged
            return
    new_entry = {"artifactId": artifact_id}
    if "newOwnerId" in upd:
        new_entry["ownerId"] = upd["newOwnerId"]
    if "newState" in upd:
        new_entry["state"] = upd["newState"]
    if "newLocation" in upd:
        new_entry["location"] = upd["newLocation"]
    if "state" in upd and "state" not in new_entry:
        new_entry["state"] = upd["state"]
    if "ownerId" in upd and "ownerId" not in new_entry:
        new_entry["ownerId"] = upd["ownerId"]
    new_entry["isRevealed"] = upd.get("isRevealed", True)
    state.append(new_entry)


def _apply_belief_update(
    snapshot: dict[str, Any], character_id: str, upd: dict[str, Any]
) -> None:
    matrices = snapshot.setdefault("beliefMatrices", [])
    target: dict[str, Any] | None = None
    for m in matrices:
        if isinstance(m, dict) and m.get("characterId") == character_id:
            target = m
            break
    if target is None:
        target = {
            "characterId": character_id,
            "objective_facts": [],
            "character_knowledge": [],
            "character_memories": [],
            "hidden_secrets": [],
            "schemaVersion": "1.0.0",
        }
        matrices.append(target)
    target.setdefault("character_knowledge", []).append({
        "subject": upd.get("subject", "?"),
        "belief_state": upd.get("belief_state", "uncertain"),
        "confidence": float(upd.get("confidence", 0.5)),
        "lastUpdatedAt": int(snapshot.get("eventSequence", 0)),
    })


def _apply_causal_seed(snapshot: dict[str, Any], seed: dict[str, Any]) -> None:
    seeds = snapshot.setdefault("causalSeedsActive", [])
    seed_id = seed.get("seedId") or seed.get("id")
    if not seed_id:
        return
    for i, s in enumerate(seeds):
        if isinstance(s, dict) and (s.get("id") == seed_id or s.get("seedId") == seed_id):
            merged = {**s, **seed}
            seeds[i] = merged
            return
    new_seed = {"id": seed_id}
    new_seed.update(seed)
    seeds.append(new_seed)


# ---------------------------------------------------------------------------
# Convenience: build a minimal initial snapshot
# ---------------------------------------------------------------------------


def make_initial_snapshot(
    runId: str | None = None,
    sceneId: str = "<unknown>",
    era: str = "present",
) -> dict[str, Any]:
    """Build a minimal world snapshot suitable for replay-lab
    examples.  Real runs will load this from the database.
    """
    return {
        "runId": runId or str(uuid.uuid4()),
        "eventSequence": 0,
        "canonicalState": {
            "currentSceneId": sceneId,
            "era": era,
            "turnIndex": 0,
            "phase": "setup",
        },
        "relationshipState": [],
        "artifactState": [],
        "directorState": {
            "currentBeatId": "opening",
            "elapsedTurnsInScene": 0,
            "actionsSpentInScene": 0,
        },
        "beliefMatrices": [],
        "memories": [],
        "causalSeedsActive": [],
        "recentOutcomes": [],
        "timestamp": "",
        "checksum": "0" * 64,
        "schemaVersion": "1.0.0",
    }


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    "EventLogEntry",
    "ReplayTraceEntry",
    "ReplayResult",
    "load_event_log",
    "replay",
    "make_initial_snapshot",
]
