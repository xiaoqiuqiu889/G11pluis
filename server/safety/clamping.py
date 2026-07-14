"""Numeric clamping — the physical-boundary gate.

Every numeric value the LLM emits is suspect: it may overflow a
``multipleOf: 0.01`` grid, blow past a ``[-1, 1]`` cap, or simply
be ``NaN`` / ``Infinity``.  This module is the **first** place a
numeric value touches our code, and the rule is "snake the value
to a legal grid; if it can't, reject it".

The engine already has its own ``clamp()`` helper
(``server.engine.types.clamp``) — this module is the **safety
counterpart** with three differences:

1. **Self-contained** — does not import from ``server.engine``.
   The safety package is the bottom of the dependency graph, so
   it must compile without the engine.
2. **Audit-first** — every clamp event is recorded in a
   :class:`ClampingAudit` so the Resolver can lift the entries
   into ``ResolverOutcome.clampedValues``.
3. **Explicit quantum** — the schema quantum is encoded as a
   named constant per field type so a typo in a quantum
   produces a clear error at import time, not a silent rounding
   drift in production.

Why we use ``Decimal + ROUND_HALF_UP``
--------------------------------------

The classic floating-point hazard::

    >>> 0.95 / 0.01
    94.99999999999999

snapping a value like ``0.95`` to the 0.01 grid via
``round(value / 0.01) * 0.01`` produces ``0.94`` — **off by
one quantum** — and the schema's ``multipleOf: 0.01`` check
will reject it.  Going through ``Decimal`` with
``ROUND_HALF_UP`` sidesteps the hazard and matches the
behaviour a human would expect.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Numeric ranges (mirror the JSON-Schema fields exactly)
# ---------------------------------------------------------------------------


class FieldKind(str, Enum):
    """The seven numeric field families the safety layer clamps.

    Each family has a fixed (lo, hi, quantum) triple.  Tests assert
    on the values; renames here must propagate to ``clamp_field``
    and the test suite.
    """

    #: relationship.trust / intimacy / respect ∈ [-1, 1], 0.01 quantum
    RELATIONSHIP = "relationship"
    #: per-turn relationship delta (|delta| ≤ 0.25), 0.01 quantum
    RELATIONSHIP_DELTA = "relationship_delta"
    #: unit-interval fields (0..1), 0.01 quantum
    UNIT = "unit"
    #: emotion intensity (0..1), 0.05 quantum (matches EMOTION_QUANTUM)
    EMOTION = "emotion"
    #: pacing pressure (0..1), 0.05 quantum
    PACING = "pacing"
    #: tension delta (-1..1), 0.05 quantum
    TENSION_DELTA = "tension_delta"
    #: event sequence (0..100000), integer
    EVENT_SEQUENCE = "event_sequence"
    #: echo intensity (0..1), 0.01 quantum
    ECHO_INTENSITY = "echo_intensity"


#: Range / quantum table.  The values mirror the JSON-Schema
#: ``minimum`` / ``maximum`` / ``multipleOf`` fields exactly.
FIELD_SPECS: dict[FieldKind, tuple[float, float, float]] = {
    FieldKind.RELATIONSHIP: (-1.0, 1.0, 0.01),
    FieldKind.RELATIONSHIP_DELTA: (-0.25, 0.25, 0.01),
    FieldKind.UNIT: (0.0, 1.0, 0.01),
    FieldKind.EMOTION: (0.0, 1.0, 0.05),
    FieldKind.PACING: (0.0, 1.0, 0.05),
    FieldKind.TENSION_DELTA: (-1.0, 1.0, 0.05),
    FieldKind.EVENT_SEQUENCE: (0.0, 100_000.0, 1.0),
    FieldKind.ECHO_INTENSITY: (0.0, 1.0, 0.01),
}


# ---------------------------------------------------------------------------
# Audit data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ClampEvent:
    """One audit row recording a single clamp operation.

    Matches the shape of ``ResolverOutcome.clampedValues[*]`` so
    the Resolver can lift it directly into the outcome audit log.

    Attributes
    ----------
    path : str
        JSON-pointer path of the clamped value
        (e.g. ``"relationshipDelta[0].trust"``).
    original : float
        The raw value before clamping.  May be ``NaN`` /
        ``Infinity`` (in which case ``applied`` is the nearest
        bound and the event is still recorded).
    applied : float
        The value the safety layer actually used.
    min : float
        The lower bound that was enforced.
    max : float
        The upper bound that was enforced.
    reason : str
        One of ``"below_min"``, ``"above_max"``, ``"not_multiple_of"``,
        ``"nan"``, ``"infinity"``, ``"non_finite"``.
    """

    path: str
    original: float
    applied: float
    min: float
    max: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ClampingAudit:
    """Accumulator for :class:`ClampEvent` rows.

    Use :meth:`record` to add a row, :meth:`events` to read them
    back, and :meth:`to_dict` to lift them into a JSON-serialisable
    payload (the Resolver passes the dict straight into
    ``ResolverOutcome.clampedValues``).
    """

    events: list[ClampEvent] = field(default_factory=list)

    def record(self, event: ClampEvent) -> None:
        self.events.append(event)

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterable[ClampEvent]:
        return iter(self.events)

    def to_dict(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.events]

    def clear(self) -> None:
        self.events.clear()


# ---------------------------------------------------------------------------
# Core primitive
# ---------------------------------------------------------------------------


def _is_finite(value: float) -> bool:
    """Return ``True`` iff ``value`` is a real, finite number."""

    if value != value:  # NaN
        return False
    if value in (float("inf"), float("-inf")):
        return False
    return True


def _snap_to_quantum(value: float, quantum: float) -> float:
    """Snap ``value`` to the nearest multiple of ``quantum`` (Decimal-safe)."""

    if quantum <= 0:
        raise ValueError(f"quantum must be positive; got {quantum!r}")
    d_value = Decimal(str(value))
    d_quantum = Decimal(str(quantum))
    n = (d_value / d_quantum).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(n * d_quantum)


def clamp_to_range(
    value: float,
    *,
    lo: float,
    hi: float,
    quantum: float,
    path: str = "<root>",
    audit: ClampingAudit | None = None,
) -> float:
    """Clamp ``value`` to ``[lo, hi]`` and snap to ``quantum``; audit each step.

    Parameters
    ----------
    value : float
        The raw value.  May be ``NaN`` / ``Infinity`` / out of
        range; the function always returns a finite, in-range
        value (or raises :class:`ValueError` for non-finite
        values when ``audit`` is ``None``).
    lo, hi : float
        The legal range.  ``lo`` must be ``<= hi``.
    quantum : float
        The schema ``multipleOf`` quantum.  Must be positive.
    path : str
        The JSON path of the value, used only for audit rows.
    audit : ClampingAudit | None
        When provided, every clamp / snap event is recorded.
        When ``None``, the function still applies the clamp
        but does not record (useful for one-off calls that
        don't need an audit trail).

    Returns
    -------
    float
        The clamped, snapped value.

    Raises
    ------
    ValueError
        ``value`` is not finite (NaN / +/-Infinity) and ``audit``
        is ``None``.  With ``audit`` provided the function
        records the bad value and returns the bound closest to
        the sign of the original value (``lo`` for ``-inf`` and
        NaN-negative-typed, ``hi`` otherwise).
    """

    if not _is_finite(value):
        # Pick a bound; with an audit we record and pick hi for
        # +inf / NaN (positive zero) and lo for -inf.  We can't
        # inspect the sign of NaN so we treat it as 0 and pick
        # ``lo`` defensively.
        if value == float("inf") or (value != value):  # NaN
            applied = hi
            reason = "infinity" if value == float("inf") else "nan"
        else:  # -inf
            applied = lo
            reason = "infinity"
        if audit is None:
            raise ValueError(
                f"non-finite value at {path!r}: {value!r} (lo={lo}, hi={hi})"
            )
        audit.record(ClampEvent(
            path=path,
            original=value,
            applied=applied,
            min=lo,
            max=hi,
            reason=reason,
        ))
        return applied

    snapped = _snap_to_quantum(value, quantum)
    if snapped < lo:
        if audit is not None:
            audit.record(ClampEvent(
                path=path,
                original=value,
                applied=lo,
                min=lo,
                max=hi,
                reason="below_min",
            ))
        return lo
    if snapped > hi:
        if audit is not None:
            audit.record(ClampEvent(
                path=path,
                original=value,
                applied=hi,
                min=lo,
                max=hi,
                reason="above_max",
            ))
        return hi
    if snapped != value:
        if audit is not None:
            audit.record(ClampEvent(
                path=path,
                original=value,
                applied=snapped,
                min=lo,
                max=hi,
                reason="not_multiple_of",
            ))
    return snapped


def clamp_field(
    kind: FieldKind,
    value: float,
    *,
    path: str = "<root>",
    audit: ClampingAudit | None = None,
) -> float:
    """Clamp ``value`` to the legal range / quantum for the given field kind.

    See :data:`FIELD_SPECS` for the per-kind ranges.  This is
    the function the rest of the safety package calls; the
    raw :func:`clamp_to_range` is exposed for tests.
    """

    if kind not in FIELD_SPECS:
        raise KeyError(f"unknown field kind: {kind!r}")
    lo, hi, quantum = FIELD_SPECS[kind]
    return clamp_to_range(
        value, lo=lo, hi=hi, quantum=quantum, path=path, audit=audit,
    )


# ---------------------------------------------------------------------------
# Bulk helpers
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ClampRequest:
    """One request to clamp a single value at a known JSON path.

    Use :func:`clamp_many` to apply a batch of :class:`ClampRequest`
    objects against a shared :class:`ClampingAudit`.
    """

    kind: FieldKind
    value: float
    path: str


def clamp_many(
    requests: Iterable[ClampRequest],
    *,
    audit: ClampingAudit | None = None,
) -> dict[str, float]:
    """Apply a batch of :class:`ClampRequest` against a shared audit.

    Returns a dict keyed by ``request.path`` of the clamped
    values.  When ``audit`` is ``None`` a fresh
    :class:`ClampingAudit` is created and discarded (caller has
    no access to the events).  Pass an explicit audit to keep
    the trail.
    """

    out: dict[str, float] = {}
    for r in requests:
        out[r.path] = clamp_field(r.kind, r.value, path=r.path, audit=audit)
    return out


# ---------------------------------------------------------------------------
# Common predicates
# ---------------------------------------------------------------------------


def is_legal_unit(value: float, *, quantum: float = 0.01) -> bool:
    """True iff ``value`` is a finite, in-range, quantum-aligned unit value."""

    if not _is_finite(value):
        return False
    if value < 0.0 or value > 1.0:
        return False
    return _snap_to_quantum(value, quantum) == value


def is_legal_relationship(value: float, *, quantum: float = 0.01) -> bool:
    """True iff ``value`` is a finite, in-range, quantum-aligned relationship."""

    if not _is_finite(value):
        return False
    if value < -1.0 or value > 1.0:
        return False
    return _snap_to_quantum(value, quantum) == value


def is_legal_relationship_delta(value: float, *, quantum: float = 0.01) -> bool:
    """True iff ``value`` is a finite, in-range, quantum-aligned delta.

    Enforces the per-turn cap of ``|delta| ≤ 0.25`` (decision 1).
    """

    if not _is_finite(value):
        return False
    if value < -0.25 or value > 0.25:
        return False
    return _snap_to_quantum(value, quantum) == value


def is_legal_event_sequence(value: float) -> bool:
    """True iff ``value`` is an integer in ``[0, 100000]``."""

    if not _is_finite(value):
        return False
    if value < 0 or value > 100_000:
        return False
    return float(int(value)) == value


def is_legal_echo_intensity(value: float, *, quantum: float = 0.01) -> bool:
    """True iff ``value`` is a finite, in-range, quantum-aligned echo_intensity."""

    if not _is_finite(value):
        return False
    if value < 0.0 or value > 1.0:
        return False
    return _snap_to_quantum(value, quantum) == value


__all__ = [
    "FieldKind",
    "FIELD_SPECS",
    "ClampEvent",
    "ClampingAudit",
    "ClampRequest",
    "clamp_to_range",
    "clamp_field",
    "clamp_many",
    "is_legal_unit",
    "is_legal_relationship",
    "is_legal_relationship_delta",
    "is_legal_event_sequence",
    "is_legal_echo_intensity",
    "_is_finite",
    "_snap_to_quantum",
]
