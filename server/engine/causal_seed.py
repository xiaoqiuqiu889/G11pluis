"""Causal seed — cross-era narrative payload.

A causal seed is a small narrative payload (a sentence, an object,
a promise) planted in one scene that may echo into other scenes
decades later.  Seeds have three lifecycle states:

* **dormant** — planted, not yet triggered (``firedAt is None``)
* **active**  — trigger condition matched this turn, ``firedAt`` set
* **fired**   — alias for active; the seed is retired from
  ``causalSeedsActive`` and recorded in the outcome audit

The Resolver is the only component that decides when a seed's
``trigger_condition`` matches and activates it.  Active seeds are
listed in the world snapshot; fired seeds are removed from the
list and tracked via the ``recentOutcomes`` ring buffer instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

from .types import (
    SCHEMA_VERSION,
    TriggerType,
    clamp_unit,
)
from .exceptions import ValidationError


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TriggerCondition:
    """A seed's trigger condition (8-type vocabulary)."""

    type: str
    predicate: str
    minEcho: float = 0.0

    def __post_init__(self) -> None:
        if self.type not in {t.value for t in TriggerType}:
            raise ValueError(f"invalid trigger type: {self.type!r}")
        if not self.predicate:
            raise ValueError("predicate is required")
        self.minEcho = clamp_unit(self.minEcho)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EraSpan:
    from_: str = ""
    to: str = ""

    def __post_init__(self) -> None:
        # Empty strings mean "no constraint".  Validating only when set.
        from .types import Era as _Era

        if self.from_ and self.from_ not in {e.value for e in _Era}:
            raise ValueError(f"invalid era: {self.from_!r}")
        if self.to and self.to not in {e.value for e in _Era}:
            raise ValueError(f"invalid era: {self.to!r}")

    def to_json_dict(self) -> dict[str, str]:
        d: dict[str, str] = {}
        if self.from_:
            d["from"] = self.from_
        if self.to:
            d["to"] = self.to
        return d


@dataclass(slots=True)
class CausalSeed:
    """A cross-era narrative payload.

    See ``causal_seed.schema.json`` for the authoritative field
    definitions.  The Resolver is the only writer; other modules
    read-only.
    """

    id: str
    source_scene: str
    source_event: str
    description: str
    trigger_condition: TriggerCondition
    target_scenes: list[str]
    echo_intensity: float
    is_secret: bool
    firedAt: int | None = None
    firedInSceneId: str | None = None
    eraSpan: EraSpan = field(default_factory=EraSpan)
    linkedCharacterIds: list[str] = field(default_factory=list)
    decayRate: float = 0.02
    tags: list[str] = field(default_factory=list)
    schemaVersion: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id is required")
        if not self.source_scene:
            raise ValueError("source_scene is required")
        if not self.source_event:
            raise ValueError("source_event is required")
        if not self.description:
            raise ValueError("description is required")
        if not self.target_scenes:
            raise ValueError("target_scenes must be non-empty")
        # Schema rule: firedAt and firedInSceneId are coupled
        if (self.firedAt is None) != (self.firedInSceneId is None):
            raise ValueError(
                "firedAt and firedInSceneId must be set together (or both null)"
            )
        self.echo_intensity = clamp_unit(self.echo_intensity)
        self.decayRate = max(0.0, min(1.0, self.decayRate))
        self.linkedCharacterIds = list(dict.fromkeys(self.linkedCharacterIds))
        self.tags = list(dict.fromkeys(self.tags))

    # ----- lifecycle ------------------------------------------------------

    @property
    def is_dormant(self) -> bool:
        return self.firedAt is None

    @property
    def is_fired(self) -> bool:
        return self.firedAt is not None

    def decay(self) -> None:
        """Apply one tick of decay to ``echo_intensity`` in place.

        Decay is multiplicative: ``intensity *= (1 - decayRate)``.
        This is the standard narrative-time decay; the Resolver
        calls it once per turn before evaluating triggers.
        """

        if self.is_fired:
            return
        self.echo_intensity = clamp_unit(self.echo_intensity * (1.0 - self.decayRate))

    def reinforce(self, amount: float = 0.1) -> None:
        """Bump ``echo_intensity`` (clamped to [0, 1]) in place."""

        if self.is_fired:
            return
        self.echo_intensity = clamp_unit(self.echo_intensity + amount)

    def fire(self, *, at_sequence: int, in_scene_id: str) -> None:
        """Activate the seed, recording the firing event."""

        if self.is_fired:
            return  # idempotent
        self.firedAt = at_sequence
        self.firedInSceneId = in_scene_id

    def matches(
        self,
        *,
        current_scene_id: str,
        current_era: str,
        era_match: bool = True,
        scene_match: bool = True,
        character_present: set[str] | None = None,
        location: str | None = None,
        belief_states: dict[str, str] | None = None,
        artifact_present: set[str] | None = None,
        memories_recalled: set[str] | None = None,
    ) -> bool:
        """Return True iff the seed's trigger condition matches.

        The Resolver passes a snapshot of the current turn's
        context; this method evaluates the trigger_type.  The
        ``predicate`` string is parsed by the Resolver (DSL subset:
        ``subject/operator/value``); the store only handles the
        structural type switch.
        """

        t = self.trigger_condition.type
        if self.is_fired:
            return False
        if self.echo_intensity < self.trigger_condition.minEcho:
            return False
        # Era span constraint (always applied if set)
        if self.eraSpan.from_ or self.eraSpan.to:
            eras = [e.value for e in __import__("server.engine.types", fromlist=["Era"]).Era]
            if self.eraSpan.from_ and eras.index(current_era) < eras.index(self.eraSpan.from_):
                return False
            if self.eraSpan.to and eras.index(current_era) > eras.index(self.eraSpan.to):
                return False
        if t == TriggerType.SCENE_MATCH.value:
            return current_scene_id in self.target_scenes and scene_match
        if t == TriggerType.ERA_MATCH.value:
            return era_match
        if t == TriggerType.CHARACTER_PRESENT.value:
            return bool(character_present) and any(
                cid in (character_present or set()) for cid in self.linkedCharacterIds
            )
        if t == TriggerType.LOCATION_MATCH.value:
            return location is not None and self._predicate_mentions(location)
        if t == TriggerType.BELIEF_STATE.value:
            return bool(belief_states) and self._predicate_evaluates_belief(belief_states)
        if t == TriggerType.MEMORY_RECALL.value:
            return bool(memories_recalled) and any(
                mid in (memories_recalled or set()) for mid in self.linkedCharacterIds
            )
        if t == TriggerType.ARTIFACT_PRESENT.value:
            return bool(artifact_present) and self._predicate_evaluates_artifact(artifact_present)
        if t == TriggerType.COMPOSITE.value:
            # Composite = AND-join of all of the above contexts.
            return all(
                [
                    self.matches(
                        current_scene_id=current_scene_id,
                        current_era=current_era,
                        era_match=era_match,
                        scene_match=scene_match,
                        character_present=character_present,
                        location=location,
                        belief_states=belief_states,
                        artifact_present=artifact_present,
                        memories_recalled=memories_recalled,
                    )
                ]
            )
        return False

    # Predicate parsing (best-effort) ----------------------------------

    def _predicate_mentions(self, location: str) -> bool:
        # Cheap heuristic: predicate must contain the location text.
        return location in self.trigger_condition.predicate

    def _predicate_evaluates_belief(self, belief_states: dict[str, str]) -> bool:
        # Predicate format: "subject in {state1,state2}" or "subject=state"
        p = self.trigger_condition.predicate
        if "=" in p:
            subj, state = [s.strip() for s in p.split("=", 1)]
            return belief_states.get(subj) == state
        if " in " in p:
            subj, states = [s.strip() for s in p.split(" in ", 1)]
            allowed = {s.strip() for s in states.strip("{}").split(",")}
            return belief_states.get(subj, "") in allowed
        return False

    def _predicate_evaluates_artifact(self, artifact_present: set[str]) -> bool:
        # Predicate format: "artifactId in scene"
        p = self.trigger_condition.predicate
        if " in " in p:
            art, _ = [s.strip() for s in p.split(" in ", 1)]
            return art in artifact_present
        return any(a in p for a in artifact_present)

    # ----- serialisation -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_scene": self.source_scene,
            "source_event": self.source_event,
            "description": self.description,
            "trigger_condition": self.trigger_condition.to_json_dict(),
            "target_scenes": list(self.target_scenes),
            "echo_intensity": self.echo_intensity,
            "is_secret": self.is_secret,
            "firedAt": self.firedAt,
            "firedInSceneId": self.firedInSceneId,
            "eraSpan": self.eraSpan.to_json_dict(),
            "linkedCharacterIds": list(self.linkedCharacterIds),
            "decayRate": self.decayRate,
            "tags": list(self.tags),
            "schemaVersion": self.schemaVersion,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CausalSeed":
        era_span_data = data.get("eraSpan", {}) or {}
        return CausalSeed(
            id=data["id"],
            source_scene=data["source_scene"],
            source_event=data["source_event"],
            description=data["description"],
            trigger_condition=TriggerCondition(**data["trigger_condition"]),
            target_scenes=list(data["target_scenes"]),
            echo_intensity=float(data["echo_intensity"]),
            is_secret=bool(data["is_secret"]),
            firedAt=data.get("firedAt"),
            firedInSceneId=data.get("firedInSceneId"),
            eraSpan=EraSpan(from_=era_span_data.get("from", ""), to=era_span_data.get("to", "")),
            linkedCharacterIds=list(data.get("linkedCharacterIds", [])),
            decayRate=float(data.get("decayRate", 0.02)),
            tags=list(data.get("tags", [])),
            schemaVersion=data.get("schemaVersion", SCHEMA_VERSION),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def from_json(payload: str) -> "CausalSeed":
        return CausalSeed.from_dict(json.loads(payload))


# ---------------------------------------------------------------------------
# Seed store
# ---------------------------------------------------------------------------


class CausalSeedStore:
    """A collection of :class:`CausalSeed` objects.

    The store is what the WorldSnapshot's ``causalSeedsActive`` array
    wraps.  All operations are pure: ``tick``, ``fire`` and
    ``plant`` return new seeds / new stores; the in-place mutators
    are explicitly named ``tick_inplace`` etc.
    """

    def __init__(self, seeds: Iterable[CausalSeed] | None = None) -> None:
        self._seeds: dict[str, CausalSeed] = {}
        for s in seeds or []:
            self._seeds[s.id] = s

    def __len__(self) -> int:
        return len(self._seeds)

    def __iter__(self):
        return iter(self._seeds.values())

    # ----- queries -------------------------------------------------------

    def get(self, seed_id: str) -> CausalSeed | None:
        return self._seeds.get(seed_id)

    def active(self) -> list[CausalSeed]:
        """Return all dormant seeds (the ones the snapshot persists)."""

        return [s for s in self._seeds.values() if s.is_dormant]

    def fired(self) -> list[CausalSeed]:
        return [s for s in self._seeds.values() if s.is_fired]

    def list_all(self) -> list[CausalSeed]:
        return list(self._seeds.values())

    # ----- mutations -----------------------------------------------------

    def plant(self, seed: CausalSeed) -> None:
        if not seed.is_dormant:
            raise ValidationError("plant() requires a dormant seed")
        self._seeds[seed.id] = seed

    def fire(self, seed_id: str, *, at_sequence: int, in_scene_id: str) -> CausalSeed:
        s = self._seeds.get(seed_id)
        if s is None:
            raise ValidationError(f"unknown seed id: {seed_id}")
        s.fire(at_sequence=at_sequence, in_scene_id=in_scene_id)
        return s

    def tick_decay(self) -> None:
        """Apply one decay tick to every dormant seed, in place."""

        for s in self._seeds.values():
            s.decay()

    def remove_fired(self) -> list[CausalSeed]:
        """Remove fired seeds from the active set; return the removed ones.

        Per the schema, ``causalSeedsActive`` only contains dormant
        seeds.  The Resolver calls this after a turn to keep the
        snapshot clean.
        """

        fired = self.fired()
        for s in fired:
            self._seeds.pop(s.id, None)
        return fired

    # ----- serialisation ------------------------------------------------

    def to_list(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._seeds.values()]

    @staticmethod
    def from_list(data: Iterable[dict[str, Any]]) -> "CausalSeedStore":
        return CausalSeedStore(CausalSeed.from_dict(d) for d in data)


__all__ = [
    "TriggerCondition",
    "EraSpan",
    "CausalSeed",
    "CausalSeedStore",
]
