"""Relationship state management.

A relationship is a directed pair ``(from, to)`` with five numeric
dimensions:

* ``trust``         ∈ [-1, 1]    — does A believe B will not hurt them?
* ``intimacy``      ∈ [-1, 1]    — emotional closeness (negative = distance)
* ``respect``       ∈ [-1, 1]    — admiration / devaluation
* ``fear``          ∈ [0, 1]     — magnitude of fear (always non-negative)
* ``unresolvedConflict`` ∈ [0, 1] — how much of the latest tension is still open

Per the decision-1 hard cap, **each turn's |delta| ≤ 0.25** for any
dimension.  This is what keeps a 30-45 minute session from turning
into a runaway "love meter" (decision 1, experience-lesson rule 4).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from .types import (
    clamp_unit,
    clamp_relationship,
    clamp_relationship_delta,
)
from .world_snapshot import RelationshipState


# ---------------------------------------------------------------------------
# Delta application
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RelationshipDelta:
    """A single per-turn delta to a relationship pair.

    The Resolver produces one of these per pair it wants to change
    (or many, when the player action + NPC reaction touch the same
    pair).  Apply via :func:`apply_relationship_delta` to enforce
    the per-turn cap.
    """

    from_: str
    to: str
    trust: float = 0.0
    intimacy: float = 0.0
    unresolvedConflict: float = 0.0
    respect: float = 0.0
    fear: float = 0.0

    def to_json_dict(self) -> dict[str, float | str]:
        return {
            "from": self.from_,
            "to": self.to,
            "trust": self.trust,
            "intimacy": self.intimacy,
            "unresolvedConflict": self.unresolvedConflict,
            "respect": self.respect,
            "fear": self.fear,
        }


def find_pair(
    relationships: list[RelationshipState], from_: str, to: str
) -> RelationshipState | None:
    """O(n) pair lookup; relationships lists are small (≤ 512)."""

    for r in relationships:
        if r.from_ == from_ and r.to == to:
            return r
    return None


def apply_relationship_delta(
    relationships: list[RelationshipState], delta: RelationshipDelta
) -> tuple[list[RelationshipState], list[dict[str, float]]]:
    """Apply ``delta`` to the matching pair, creating it if necessary.

    Returns the **new** list of relationships plus a list of clamp
    audit entries (``{"field": "trust", "original": ..., "applied": ...}``).

    The function is **pure** — the input list is never mutated; a
    new list is returned.  This matters for replay: the same input
    list + same delta must always yield the same output.

    Per-turn cap: each *delta* component is clamped to |x| ≤ 0.25
    before being added.  The resulting value is then clamped to
    its domain (e.g. ``trust ∈ [-1, 1]``).
    """

    audit: list[dict[str, float]] = []

    # Clamp deltas first (the |x| ≤ 0.25 cap)
    c_trust = clamp_relationship_delta(delta.trust)
    c_intimacy = clamp_relationship_delta(delta.intimacy)
    c_respect = clamp_relationship_delta(delta.respect)
    c_unresolved = clamp_relationship_delta(delta.unresolvedConflict)
    c_fear = clamp_relationship_delta(delta.fear)
    if c_trust != delta.trust:
        audit.append({"path": "trust_delta", "original": delta.trust, "applied": c_trust})
    if c_intimacy != delta.intimacy:
        audit.append({"path": "intimacy_delta", "original": delta.intimacy, "applied": c_intimacy})
    if c_respect != delta.respect:
        audit.append({"path": "respect_delta", "original": delta.respect, "applied": c_respect})
    if c_unresolved != delta.unresolvedConflict:
        audit.append(
            {"path": "unresolvedConflict_delta", "original": delta.unresolvedConflict, "applied": c_unresolved}
        )
    if c_fear != delta.fear:
        audit.append({"path": "fear_delta", "original": delta.fear, "applied": c_fear})

    # Locate or create the pair
    new_list = list(relationships)
    pair = find_pair(new_list, delta.from_, delta.to)
    if pair is None:
        pair = RelationshipState(
            from_=delta.from_,
            to=delta.to,
            trust=c_trust,
            intimacy=c_intimacy,
            unresolvedConflict=max(0.0, c_unresolved),  # start at 0; delta can only raise
            respect=c_respect,
            fear=max(0.0, c_fear),
            lastUpdatedAt=0,  # filled in by Resolver
        )
        new_list.append(pair)
        return new_list, audit

    new_trust = clamp_relationship(pair.trust + c_trust)
    new_intimacy = clamp_relationship(pair.intimacy + c_intimacy)
    new_respect = clamp_relationship(pair.respect + c_respect)
    # unresolvedConflict is monotonic non-decreasing (schema rule)
    new_unresolved = clamp_unit(max(pair.unresolvedConflict, pair.unresolvedConflict + c_unresolved))
    new_fear = clamp_unit(max(0.0, pair.fear + c_fear))

    if new_trust != pair.trust + c_trust:
        audit.append({"path": "trust", "original": pair.trust + c_trust, "applied": new_trust})
    if new_intimacy != pair.intimacy + c_intimacy:
        audit.append({"path": "intimacy", "original": pair.intimacy + c_intimacy, "applied": new_intimacy})
    if new_respect != pair.respect + c_respect:
        audit.append({"path": "respect", "original": pair.respect + c_respect, "applied": new_respect})
    if new_unresolved != pair.unresolvedConflict + c_unresolved:
        audit.append(
            {"path": "unresolvedConflict", "original": pair.unresolvedConflict + c_unresolved, "applied": new_unresolved}
        )
    if new_fear != pair.fear + c_fear:
        audit.append({"path": "fear", "original": pair.fear + c_fear, "applied": new_fear})

    new_pair = replace(
        pair,
        trust=new_trust,
        intimacy=new_intimacy,
        respect=new_respect,
        unresolvedConflict=new_unresolved,
        fear=new_fear,
    )
    new_list = [p if p.from_ != delta.from_ or p.to != delta.to else new_pair for p in new_list]
    return new_list, audit


def apply_relationship_deltas(
    relationships: list[RelationshipState], deltas: Iterable[RelationshipDelta]
) -> tuple[list[RelationshipState], list[dict[str, float]]]:
    """Apply a sequence of deltas in order, accumulating audit entries."""

    audit: list[dict[str, float]] = []
    state = relationships
    for d in deltas:
        state, a = apply_relationship_delta(state, d)
        audit.extend(a)
    return state, audit


# ---------------------------------------------------------------------------
# Convenience: derive a turn's "default" deltas from a 12-action
# ---------------------------------------------------------------------------


DEFAULT_DELTAS: dict[str, dict[str, float]] = {
    # The default per-action delta is **direction only**; the
    # magnitude is the player's ``disclosureLevel`` (0..1) times
    # the per-turn cap.  This makes the magnitude depend on player
    # intent, while the direction stays deterministic.
    "investigate":  {"trust": 0.25, "intimacy": 0.10},
    "reveal":       {"trust": 0.25, "intimacy": 0.20},
    "conceal":      {"trust": -0.10, "intimacy": -0.05},
    "question":     {"trust": 0.05, "intimacy": 0.10},
    "confront":     {"trust": -0.10, "intimacy": 0.15, "unresolvedConflict": 0.20},
    "comfort":      {"trust": 0.20, "intimacy": 0.25},
    "give":         {"trust": 0.20, "intimacy": 0.15},
    "destroy":      {"trust": -0.10, "intimacy": -0.10, "unresolvedConflict": 0.10},
    "promise":      {"trust": 0.25, "intimacy": 0.10},
    "wait":         {"trust": 0.0, "intimacy": 0.0},
    "leave":        {"trust": -0.10, "intimacy": -0.20, "unresolvedConflict": 0.10},
    "silence":      {"trust": -0.05, "intimacy": -0.05},
}


__all__ = [
    "RelationshipDelta",
    "find_pair",
    "apply_relationship_delta",
    "apply_relationship_deltas",
    "DEFAULT_DELTAS",
]
