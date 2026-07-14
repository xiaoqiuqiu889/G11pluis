"""4-level degradation chain.

Implements the cost-control fallback ladder from decision 5:

* **L1** ``npc_timeout_fallback``     — NPC reaction timed out →
  use a writer-authored fallback line.
* **L2** ``director_timeout_skip``    — Director timed out → skip
  beat validation; only run the NPC proposal through the resolver.
* **L3** ``hard_degradation``         — second consecutive failure
  before the Resolver → run the main line from a writer-authored
  script (no LLM call at all).
* **L4** ``persist_failure``          — Resolver failed to persist
  → surface a "service unavailable" message and preserve the save.

Each level has:

* a **trigger condition** — the precise failure that escalates to it
* a **fallback action**   — what the engine does instead
* a **diagnostic record** — what gets logged for the model_calls
  audit table

The chain is **monotonic**: once we go to L3, we stay there for
the rest of the session unless an explicit operator action lifts
the level.  L4 is terminal.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .exceptions import (
    DegradationError,
    DirectorTimeoutError,
    HardDegradationError,
    NPCTimeoutError,
    PersistFailureError,
)


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------


class DegradationLevel(str, Enum):
    """The 4 levels in the chain.

    Stored as strings so the value is JSON-friendly.
    """

    L1_NPC_TIMEOUT = "L1"
    L2_DIRECTOR_TIMEOUT = "L2"
    L3_HARD_DEGRADATION = "L3"
    L4_PERSIST_FAILURE = "L4"


# Ordered for fast "what is the worst level so far" computation.
LEVEL_ORDER: tuple[DegradationLevel, ...] = (
    DegradationLevel.L1_NPC_TIMEOUT,
    DegradationLevel.L2_DIRECTOR_TIMEOUT,
    DegradationLevel.L3_HARD_DEGRADATION,
    DegradationLevel.L4_PERSIST_FAILURE,
)


# ---------------------------------------------------------------------------
# Fallback payloads
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class NPCFallbackLine:
    """A writer-authored fallback NPC line.

    The :class:`FallbackScript` carries one of these per scene
    and per action type.  Lines are deliberately flat prose
    (no LLM in the loop); they keep the player moving while the
    team investigates the timeout.
    """

    characterId: str
    sceneId: str
    actionType: str
    line: str
    speechIntent: str = "remain_silent"


@dataclass(slots=True)
class FallbackScript:
    """Writer-authored fallback content for a single scene.

    Provides:

    * ``npc_lines``   — per-action fallback NPC lines (L1).
    * ``director_skip_line`` — flat narration used when the
      Director step is skipped (L2).
    * ``hard_lines``   — full mainline per beat when L3 fires.
    * ``persist_message`` — player-facing error message (L4).
    """

    sceneId: str
    npc_lines: list[NPCFallbackLine] = field(default_factory=list)
    director_skip_line: str = "（场景节拍暂时无法生成，由备选叙事接续）"
    hard_lines: dict[str, str] = field(default_factory=dict)  # beat_id -> prose
    persist_message: str = "服务暂不可用，本轮进度已为您保留。"

    def lookup_npc_line(
        self, *, characterId: str, actionType: str
    ) -> NPCFallbackLine | None:
        for line in self.npc_lines:
            if line.characterId == characterId and line.actionType == actionType:
                return line
        # Fallback: any line for this action in this scene
        for line in self.npc_lines:
            if line.actionType == actionType:
                return line
        return None


# ---------------------------------------------------------------------------
# Diagnostic record
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DegradationRecord:
    """A single degradation event, written to the model_calls audit."""

    level: DegradationLevel
    trigger: str
    timestamp: str
    sceneId: str
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DegradationChain:
    """A monotonic degradation chain.

    Use ``escalate`` to move up, ``current_level`` to query, and
    ``is_at_least`` to test.  The chain keeps a record of every
    escalation so the model_calls table can answer "how often did
    we hit L3 in the last 24h".
    """

    sceneId: str = ""
    _level: DegradationLevel | None = None
    _consecutive_failures: int = 0
    _records: list[DegradationRecord] = field(default_factory=list)

    @property
    def current_level(self) -> DegradationLevel | None:
        return self._level

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def records(self) -> list[DegradationRecord]:
        return list(self._records)

    def is_at_least(self, level: DegradationLevel) -> bool:
        if self._level is None:
            return False
        return LEVEL_ORDER.index(self._level) >= LEVEL_ORDER.index(level)

    def reset_consecutive(self) -> None:
        """Reset the consecutive-failure counter (called on success)."""

        self._consecutive_failures = 0

    def escalate(
        self,
        *,
        to: DegradationLevel,
        trigger: str,
        details: dict[str, Any] | None = None,
    ) -> DegradationRecord:
        """Move the chain to ``to`` (or higher if already past it)."""

        if self._level is not None and LEVEL_ORDER.index(self._level) >= LEVEL_ORDER.index(to):
            # Already at or past; do not move backwards
            return self._records[-1]
        from datetime import datetime, timezone

        rec = DegradationRecord(
            level=to,
            trigger=trigger,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            sceneId=self.sceneId,
            details=dict(details or {}),
        )
        self._records.append(rec)
        self._level = to
        return rec

    def note_failure(self) -> None:
        """Increment the consecutive-failure counter."""

        self._consecutive_failures += 1


# ---------------------------------------------------------------------------
# Wrappers
# ---------------------------------------------------------------------------


def with_npc_timeout_fallback(
    *,
    chain: DegradationChain,
    fallback: FallbackScript,
    characterId: str,
    actionType: str,
    npc_call: Callable[[], Any],
    timeout_seconds: float = 4.0,
) -> tuple[Any, bool]:
    """Run ``npc_call`` with a timeout; on timeout, return a fallback line.

    Returns
    -------
    (result, used_fallback)
        ``result`` is the npc_call return value on success, or the
        fallback NPC line on timeout.  ``used_fallback`` is True
        iff the timeout fired.
    """

    start = time.monotonic()
    try:
        result = npc_call()
        if time.monotonic() - start > timeout_seconds:
            raise NPCTimeoutError("npc_call exceeded timeout")
        chain.reset_consecutive()
        return result, False
    except (NPCTimeoutError, TimeoutError) as exc:
        chain.note_failure()
        chain.escalate(
            to=DegradationLevel.L1_NPC_TIMEOUT,
            trigger="npc_timeout",
            details={"characterId": characterId, "actionType": actionType, "error": str(exc)},
        )
        line = fallback.lookup_npc_line(characterId=characterId, actionType=actionType)
        return line, True


def with_director_timeout_skip(
    *,
    chain: DegradationChain,
    fallback: FallbackScript,
    director_call: Callable[[], Any],
    timeout_seconds: float = 4.0,
) -> tuple[Any, bool]:
    """Run ``director_call`` with a timeout; on timeout, skip beat validation.

    The Resolver, when given the resulting flag, will skip the
    director-beat whitelist check and use a no-op beat
    (``beat_skip``).  This is **L2** — the NPC proposal still
    runs through the state machine, so the player still gets a
    meaningful turn.
    """

    try:
        result = director_call()
        chain.reset_consecutive()
        return result, False
    except (DirectorTimeoutError, TimeoutError, DegradationError) as exc:
        chain.note_failure()
        if chain.consecutive_failures >= 2:
            # Two failures in a row → escalate to L3
            chain.escalate(
                to=DegradationLevel.L3_HARD_DEGRADATION,
                trigger="director_timeout_x2",
                details={"error": str(exc)},
            )
        else:
            chain.escalate(
                to=DegradationLevel.L2_DIRECTOR_TIMEOUT,
                trigger="director_timeout",
                details={"error": str(exc)},
            )
        return None, True


def with_hard_degradation(
    *,
    chain: DegradationChain,
    fallback: FallbackScript,
    beatId: str,
) -> str:
    """Return the hard-degradation mainline for ``beatId``.

    Raises :exc:`HardDegradationError` if L3 isn't currently
    active — call sites should branch on ``chain.is_at_least(L3)``
    first.
    """

    if not chain.is_at_least(DegradationLevel.L3_HARD_DEGRADATION):
        raise HardDegradationError("L3 hard degradation not active")
    return fallback.hard_lines.get(beatId, fallback.director_skip_line)


def with_persist_failure(
    *,
    chain: DegradationChain,
    fallback: FallbackScript,
    persist_call: Callable[[], Any],
) -> Any:
    """Wrap a persistence call.  On failure, escalate to L4 and re-raise.

    The L4 fallback is **always** to surface the player-facing
    error message in ``fallback.persist_message`` and preserve the
    save (the persistence layer is responsible for that).  L4 is
    terminal — no further automatic recovery is attempted.
    """

    try:
        result = persist_call()
        chain.reset_consecutive()
        return result
    except PersistFailureError as exc:
        chain.escalate(
            to=DegradationLevel.L4_PERSIST_FAILURE,
            trigger="persist_failure",
            details={"error": str(exc)},
        )
        # The persistence layer is expected to surface the
        # fallback message; we still re-raise so the caller can
        # decide whether to keep the session alive.
        raise


__all__ = [
    "DegradationLevel",
    "LEVEL_ORDER",
    "NPCFallbackLine",
    "FallbackScript",
    "DegradationRecord",
    "DegradationChain",
    "with_npc_timeout_fallback",
    "with_director_timeout_skip",
    "with_hard_degradation",
    "with_persist_failure",
]
