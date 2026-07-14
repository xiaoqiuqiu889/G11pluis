"""Append-only event log for the AI-native engine.

The event log is the **single source of truth for replay**.  Every
accepted :class:`engine.resolver.ResolverOutcome` becomes a
:class:`GameEvent`; replaying the log against a deterministic
state-machine (and the same RNG seed stream) must reproduce the
final :class:`world_snapshot.WorldSnapshot` byte-for-byte.

Why append-only
---------------
Per the engineering principles of the 《崇祯》reference, the state
machine is **deterministic and replayable**.  This rules out
in-place mutation of past events; instead, corrections are recorded
as *new* events that supersede earlier ones via the idempotency
mechanism.  An audit log of an error-prone LLM-based system has no
business being mutable.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

from .types import SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Game event
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GameEvent:
    """A single canonical event in a run's event log.

    Fields mirror the resolver_outcome schema's bookkeeping:
    * ``eventSequence`` is monotonic, contiguous and starts at 1
      (the schema requires ``eventSequence >= 1`` for outcomes).
    * ``idempotencyKey`` is the Resolver's composite hash; a
      duplicate is a no-op (not an error).
    * ``randomSeed`` lets the ReplayService reproduce any
      randomness the LLM-era decision used; in the deterministic
      pre-LLM engine it is simply propagated.
    * ``causalSeed`` is the *causal* seed the event activated /
      planted (if any), kept here for cheap forward-index lookup.
    """

    sequence: int
    sceneId: str
    actorId: str
    actionType: str
    actionPayload: dict[str, Any]
    validatedDelta: dict[str, Any]
    causalSeed: str | None = None
    randomSeed: int = 0
    createdAt: str = ""
    idempotencyKey: str = ""
    runId: str = ""
    outcomeId: str = ""

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("event sequence must start at 1")
        if not self.sceneId:
            raise ValueError("sceneId is required")
        if not self.actorId:
            raise ValueError("actorId is required")
        if not self.actionType:
            raise ValueError("actionType is required")
        if not self.createdAt:
            self.createdAt = (
                datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            )

    # ----- helpers --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "GameEvent":
        return GameEvent(
            sequence=data["sequence"],
            sceneId=data["sceneId"],
            actorId=data["actorId"],
            actionType=data["actionType"],
            actionPayload=dict(data.get("actionPayload", {})),
            validatedDelta=dict(data.get("validatedDelta", {})),
            causalSeed=data.get("causalSeed"),
            randomSeed=int(data.get("randomSeed", 0)),
            createdAt=data.get("createdAt", ""),
            idempotencyKey=data.get("idempotencyKey", ""),
            runId=data.get("runId", ""),
            outcomeId=data.get("outcomeId", ""),
        )

    @staticmethod
    def from_json(payload: str) -> "GameEvent":
        return GameEvent.from_dict(json.loads(payload))

    @staticmethod
    def make_idempotency_key(
        *,
        runId: str,
        eventSequence: int,
        triggerPlayerActionId: str | None,
        triggerDirectorProposalId: str | None,
    ) -> str:
        """Build the composite idempotency key the Resolver uses.

        Format: ``{runId}|{eventSequence}|{playerId}|{directorId}``,
        then hashed to 64 hex chars in the Resolver.  Here we just
        produce the composite string; the resolver handles hashing.
        """

        return "|".join(
            [
                runId,
                str(eventSequence),
                triggerPlayerActionId or "",
                triggerDirectorProposalId or "",
            ]
        )


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EventLog:
    """An append-only, sequence-numbered log of :class:`GameEvent` objects.

    Construction
    ------------
    ``EventLog()`` yields an empty log; ``EventLog.from_iterable(events)``
    rehydrates from persistence.  Events are kept in a list (we don't
    need O(1) lookups — the log is replayed in order).

    Threading
    ---------
    The log itself does not lock; the engine runs single-threaded
    per run, with the Resolver being the only writer.  If you need
    cross-process consistency, wrap with an external lock.
    """

    runId: str
    _events: list[GameEvent] = field(default_factory=list)
    _idempotency: dict[str, GameEvent] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            uuid.UUID(self.runId)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"runId must be a UUID: {exc}") from exc

    # ----- read API -------------------------------------------------------

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[GameEvent]:
        return iter(self._events)

    @property
    def events(self) -> list[GameEvent]:
        """Read-only view of events in insertion order."""

        return list(self._events)

    @property
    def last_sequence(self) -> int:
        """The last assigned sequence number, or 0 if the log is empty."""

        return self._events[-1].sequence if self._events else 0

    def get(self, sequence: int) -> GameEvent | None:
        """O(n) lookup by sequence.  Acceptable — logs are short."""

        for ev in self._events:
            if ev.sequence == sequence:
                return ev
        return None

    def has_idempotency_key(self, key: str) -> bool:
        return key in self._idempotency

    # ----- write API ------------------------------------------------------

    def append(self, event: GameEvent) -> bool:
        """Append ``event`` if it is new.

        Returns
        -------
        bool
            ``True`` if the event was appended; ``False`` if it was
            a duplicate (idempotencyKey already seen).  Duplicates
            are *not* an error — the schema explicitly requires
            replays to be no-ops.
        """

        if event.runId and event.runId != self.runId:
            raise ValueError("event runId does not match log runId")
        # monotonic check (contiguous from 1; gap of 0 = reject)
        expected = self.last_sequence + 1
        if event.sequence != expected:
            raise ValueError(
                f"event sequence must be contiguous: expected {expected}, got {event.sequence}"
            )
        if event.idempotencyKey and event.idempotencyKey in self._idempotency:
            return False
        self._events.append(event)
        if event.idempotencyKey:
            self._idempotency[event.idempotencyKey] = event
        return True

    def replay(self) -> list[GameEvent]:
        """Return a copy of the events in order, for the replay service."""

        return list(self._events)

    # ----- persistence helpers -------------------------------------------

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events]

    def to_json(self) -> str:
        return json.dumps(
            {"runId": self.runId, "events": self.to_list()},
            ensure_ascii=False,
        )

    @staticmethod
    def from_iterable(runId: str, events: Iterable[GameEvent | dict[str, Any]]) -> "EventLog":  # noqa: E501
        log = EventLog(runId=runId)
        for ev in events:
            if isinstance(ev, dict):
                ev = GameEvent.from_dict(ev)
            if not log.append(ev):
                # Replays should never silently drop; surface as a
                # warning during deserialisation.  In production
                # this would be logged.
                pass
        return log

    @staticmethod
    def from_json(payload: str) -> "EventLog":
        data = json.loads(payload)
        return EventLog.from_iterable(data["runId"], data.get("events", []))


# ---------------------------------------------------------------------------
# Replay helper
# ---------------------------------------------------------------------------


def deterministic_seed(base: int, event_sequence: int) -> int:
    """Produce a per-event deterministic seed from a base + sequence.

    The replay contract is: given the same event log and the same
    base seed, every reducer call sees the same RNG output.  This
    function is the canonical implementation; reducers and tests
    both import it.
    """

    # 64-bit FNV-1a-ish mixer; cheap and stable.
    x = (base ^ (event_sequence * 0x9E3779B97F4A7C15)) & 0xFFFFFFFFFFFFFFFF
    x = (x ^ (x >> 33)) * 0xFF51AFD7ED558CCD
    x &= 0xFFFFFFFFFFFFFFFF
    x = (x ^ (x >> 33)) * 0xC4CEB9FE1A85EC53
    x &= 0xFFFFFFFFFFFFFFFF
    x = x ^ (x >> 33)
    return x & 0x7FFFFFFF  # non-negative int for compatibility with stdlib random


__all__ = [
    "GameEvent",
    "EventLog",
    "deterministic_seed",
]
