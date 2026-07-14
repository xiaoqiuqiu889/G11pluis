"""Model-layer 4-level degradation chain.

This is the **model-side** counterpart of the engine-side
degradation chain in :mod:`server.engine.degradation`.  The two
chains are layered:

* The **engine** chain (in ``server/engine/degradation.py``) decides
  *what to do* — skip the director beat, use the writer mainline,
  surface the L4 player-facing message.
* The **model** chain (this file) decides *whether to call the LLM
  at all*, *which provider to try next*, and *which writer content
  to substitute* when the LLM is unavailable.

The 4 levels (from decision 5) re-stated for the model layer
------------------------------------------------------------

* **L1** — NPC reaction timed out → use a writer-authored fallback
  line from ``content/<case>/fallbacks/npc_lines.yaml``.
* **L2** — Director timed out → skip beat validation; the engine
  still runs the NPC proposal through the state machine.  Model
  layer's job: return a "beat skip" stub to the resolver.
* **L3** — Resolver-before *or* two consecutive failures anywhere
  in the chain → the mainline runs from a writer-authored script;
  **no LLM call is made**.
* **L4** — Resolver write failure → surface the player-facing
  "service unavailable" message; the engine layer is responsible
  for preserving the save.

Monotonicity
------------
Once the chain moves to L3 it does NOT drop back to L2.  The
chain clears only on a new run (or on explicit operator reset).
This is the same monotonicity rule as the engine chain.

What this module does
---------------------

* :class:`ModelDegradationChain` is the per-run state object.
* :func:`run_with_chain` is the high-level "call the LLM, fall
  through on failure" entry point that the gateway uses.
* :func:`trigger_l1` / :func:`trigger_l2` /
  :func:`trigger_l3` / :func:`trigger_l4` are the explicit
  level entries (used by the engine layer when *it* decides to
  escalate).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Sequence

from .exceptions import (
    DegradationEscalatedError,
    ModelCallError,
    PersistFailureError,
    ProviderTimeoutError,
    SchemaValidationError,
)
from .fallback_loader import FallbackContentLoader, ModelFallbackContent


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------


class ModelDegradationLevel(str, Enum):
    """The 4 levels in the model-layer chain.

    String-valued for JSON audit friendliness.  Order matters —
    L1 < L2 < L3 < L4.
    """

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


LEVEL_ORDER: tuple[ModelDegradationLevel, ...] = (
    ModelDegradationLevel.L1,
    ModelDegradationLevel.L2,
    ModelDegradationLevel.L3,
    ModelDegradationLevel.L4,
)


# ---------------------------------------------------------------------------
# Diagnostic record
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ModelDegradationRecord:
    """A single escalation event, written to the model_calls audit."""

    level: ModelDegradationLevel
    trigger: str
    timestamp: str
    scene_id: str
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Chain state
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ModelDegradationChain:
    """Per-run monotonic degradation state.

    Each run gets one chain.  The chain records every escalation
    so the cost controller can answer "did this run hit L3?".
    """

    run_id: str
    case_slug: str = "case_01_revolution_street"
    scene_id: str = ""
    _level: ModelDegradationLevel | None = None
    _consecutive_failures: int = 0
    _records: list[ModelDegradationRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def current_level(self) -> ModelDegradationLevel | None:
        with self._lock:
            return self._level

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures

    @property
    def records(self) -> list[ModelDegradationRecord]:
        with self._lock:
            return list(self._records)

    def is_at_least(self, level: ModelDegradationLevel) -> bool:
        with self._lock:
            if self._level is None:
                return False
            return LEVEL_ORDER.index(self._level) >= LEVEL_ORDER.index(level)

    def reset_consecutive(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def note_failure(self) -> int:
        with self._lock:
            self._consecutive_failures += 1
            return self._consecutive_failures

    def escalate(
        self,
        *,
        to: ModelDegradationLevel,
        trigger: str,
        details: dict[str, Any] | None = None,
    ) -> ModelDegradationRecord:
        with self._lock:
            if (
                self._level is not None
                and LEVEL_ORDER.index(self._level) >= LEVEL_ORDER.index(to)
            ):
                # Monotonic: do not move backwards.
                return self._records[-1]
            rec = ModelDegradationRecord(
                level=to,
                trigger=trigger,
                timestamp=datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                scene_id=self.scene_id,
                details=dict(details or {}),
            )
            self._records.append(rec)
            self._level = to
            return rec


# ---------------------------------------------------------------------------
# Writer-side payload for L1/L2/L3
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WriterPayload:
    """The content returned when the LLM is replaced by writer content."""

    level: ModelDegradationLevel
    source: str  # "npc_line" / "director_skip" / "hard_line" / "persist_message"
    content: str
    parsed: dict[str, Any] | None = None
    beat_id: str | None = None
    characterId: str | None = None
    actionType: str | None = None


# ---------------------------------------------------------------------------
# High-level run helper
# ---------------------------------------------------------------------------


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def trigger_l1(
    chain: ModelDegradationChain,
    *,
    fallback: ModelFallbackContent,
    characterId: str,
    actionType: str,
    error: str,
) -> WriterPayload:
    """Escalate to L1 and return a writer NPC fallback line."""

    chain.escalate(
        to=ModelDegradationLevel.L1,
        trigger="npc_timeout",
        details={"characterId": characterId, "actionType": actionType, "error": error},
    )
    line = fallback.lookup_npc_line(characterId=characterId, actionType=actionType)
    if line is None:
        # No writer line: synthesise a "remain silent" stub.
        return WriterPayload(
            level=ModelDegradationLevel.L1,
            source="npc_line",
            content="[fallback] （角色保持沉默。）",
            characterId=characterId,
            actionType=actionType,
        )
    return WriterPayload(
        level=ModelDegradationLevel.L1,
        source="npc_line",
        content=line.line,
        characterId=line.characterId,
        actionType=line.actionType,
    )


def trigger_l2(
    chain: ModelDegradationChain,
    *,
    fallback: ModelFallbackContent,
    beat_id: str,
    error: str,
) -> WriterPayload:
    """Escalate to L2 (Director skip)."""

    chain.escalate(
        to=ModelDegradationLevel.L2,
        trigger="director_timeout",
        details={"beatId": beat_id, "error": error},
    )
    return WriterPayload(
        level=ModelDegradationLevel.L2,
        source="director_skip",
        content=fallback.director_skip_line,
        beat_id=beat_id,
    )


def trigger_l3(
    chain: ModelDegradationChain,
    *,
    fallback: ModelFallbackContent,
    beat_id: str,
    error: str,
) -> WriterPayload:
    """Escalate to L3 (no LLM; writer mainline)."""

    chain.escalate(
        to=ModelDegradationLevel.L3,
        trigger="consecutive_failure",
        details={"beatId": beat_id, "error": error},
    )
    return WriterPayload(
        level=ModelDegradationLevel.L3,
        source="hard_line",
        content=fallback.lookup_hard_line(beat_id),
        beat_id=beat_id,
    )


def trigger_l4(
    chain: ModelDegradationChain,
    *,
    fallback: ModelFallbackContent,
    error: str,
) -> WriterPayload:
    """Escalate to L4 (persist failure; player-facing message)."""

    chain.escalate(
        to=ModelDegradationLevel.L4,
        trigger="persist_failure",
        details={"error": error},
    )
    return WriterPayload(
        level=ModelDegradationLevel.L4,
        source="persist_message",
        content=fallback.persist_message,
    )


# ---------------------------------------------------------------------------
# Run-with-chain helper (used by the gateway)
# ---------------------------------------------------------------------------


#: Exception types that should count as a "failure" for the
#: consecutive counter.  Anything else (e.g. a BudgetExceeded
#: from the cost controller) is treated as a hard stop and does
#: not increment the counter.
FAILURE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ProviderTimeoutError,
    SchemaValidationError,
    DegradationEscalatedError,
)


def run_with_chain(
    *,
    chain: ModelDegradationChain,
    fallback: ModelFallbackContent,
    task_name: str,
    primary_call: Callable[[], Any],
    on_l1: Callable[[Exception], WriterPayload] | None = None,
    on_l2: Callable[[Exception], WriterPayload] | None = None,
    on_l3: Callable[[Exception], WriterPayload] | None = None,
    max_consecutive_failures: int = 2,
) -> tuple[Any, str, str | None]:
    """Run ``primary_call`` with the model-layer degradation chain.

    The behaviour:

    0. If the chain is **already at L3** (terminal), short-circuit:
       do **not** call the LLM, return a writer payload at L3.
       This is the "monotonic + L3 is sticky" rule from decision 5.
    1. Otherwise call ``primary_call``.
    2. If it raises :class:`ProviderTimeoutError` or
       :class:`SchemaValidationError` (or
       :class:`DegradationEscalatedError`), increment the
       consecutive counter.
    3. If the consecutive count reaches ``max_consecutive_failures``
       (default 2), escalate to **L3** and return the writer
       mainline.  L3 does NOT call the LLM again in the same
       run.
    4. If the failure is a timeout and we have not yet hit L3,
       surface an **L1** or **L2** payload (depending on
       ``task_name`` — ``npc_*`` → L1, ``director_*`` → L2).

    Returns
    -------
    (result, finish_reason, degradation_level)
        ``result`` is either the value returned by
        ``primary_call`` or a :class:`WriterPayload`.
        ``finish_reason`` is ``"stop"`` on success, ``"fallback"``
        on a writer substitution.  ``degradation_level`` is
        ``None`` for clean LLM calls, ``"L1" / "L2" / "L3"`` for
        the corresponding fallback path.
    """

    # L3 short-circuit: once we're at L3, no more LLM calls in
    # this run.  We escalate (monotonically — same level) and
    # return the writer payload.  ``primary_call`` is never
    # invoked.
    if chain.is_at_least(ModelDegradationLevel.L3):
        payload = (on_l3(None) if on_l3 else trigger_l3(
            chain,
            fallback=fallback,
            beat_id=task_name,
            error="L3 sticky: skipping LLM call",
        ))
        return payload, "fallback", ModelDegradationLevel.L3.value

    try:
        result = primary_call()
        chain.reset_consecutive()
        return result, "stop", None
    except Exception as exc:  # noqa: BLE001
        chain.note_failure()
        # L3 short-circuit: after N consecutive failures, no LLM.
        if chain.consecutive_failures >= max_consecutive_failures:
            payload = (on_l3(exc) if on_l3 else trigger_l3(
                chain,
                fallback=fallback,
                beat_id=getattr(exc, "beat_id", "fallback_beat"),
                error=str(exc),
            ))
            return payload, "fallback", ModelDegradationLevel.L3.value

        # L1 vs L2 split: decide by task name.  Anything starting
        # with ``npc`` is L1; ``director`` is L2; everything else
        # (resolver, memory) defaults to L2 (skip-validation).
        if task_name.startswith("npc"):
            payload = (on_l1(exc) if on_l1 else trigger_l1(
                chain,
                fallback=fallback,
                characterId=getattr(exc, "characterId", "unknown"),
                actionType=getattr(exc, "actionType", "unknown"),
                error=str(exc),
            ))
            return payload, "fallback", ModelDegradationLevel.L1.value
        if task_name.startswith("director"):
            payload = (on_l2(exc) if on_l2 else trigger_l2(
                chain,
                fallback=fallback,
                beat_id=getattr(exc, "beat_id", "fallback_beat"),
                error=str(exc),
            ))
            return payload, "fallback", ModelDegradationLevel.L2.value
        # Other tasks: treat as L2 (skip validation, allow
        # the engine to keep going).
        payload = (on_l2(exc) if on_l2 else trigger_l2(
            chain,
            fallback=fallback,
            beat_id=getattr(exc, "beat_id", "fallback_beat"),
            error=str(exc),
        ))
        return payload, "fallback", ModelDegradationLevel.L2.value


# ---------------------------------------------------------------------------
# Loader integration
# ---------------------------------------------------------------------------


def default_loader() -> FallbackContentLoader:
    """Return the project's default :class:`FallbackContentLoader`."""

    return FallbackContentLoader()


__all__ = [
    "ModelDegradationLevel",
    "LEVEL_ORDER",
    "ModelDegradationRecord",
    "ModelDegradationChain",
    "WriterPayload",
    "FAILURE_EXCEPTIONS",
    "trigger_l1",
    "trigger_l2",
    "trigger_l3",
    "trigger_l4",
    "run_with_chain",
    "default_loader",
]
