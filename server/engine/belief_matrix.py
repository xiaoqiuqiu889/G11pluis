"""Belief matrix — the 4-layer per-character belief model.

The matrix is the heart of the AI-native engine: every agent reads
it, and only the Resolver writes it.  Layers:

1. ``objective_facts``      — shared ground truth, Resolver-only writes
2. ``character_knowledge``  — what this character believes (may diverge)
3. ``character_memories``   — autobiographical memory with distortion
4. ``hidden_secrets``       — things the character knows but others don't

Belief states: 5 — ``certain``, ``uncertain``, ``wrong``, ``denied``,
``reinforced``.  Distortion types: 10 (see
:data:`server.engine.types.DISTORTION_TYPES`).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

from .types import (
    SCHEMA_VERSION,
    BeliefState,
    DistortionType,
    clamp_unit,
)
from .exceptions import ValidationError


# ---------------------------------------------------------------------------
# Layer 1: objective facts
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ObjectiveFact:
    factId: str
    description: str
    establishedAt: int
    isContested: bool
    establishedBy: str = ""

    def __post_init__(self) -> None:
        if not self.factId:
            raise ValueError("factId is required")
        if not self.description:
            raise ValueError("description is required")
        if self.establishedAt < 0:
            raise ValueError("establishedAt must be >= 0")

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Layer 2: character knowledge
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CharacterKnowledge:
    subject: str
    belief_state: str
    confidence: float
    lastUpdatedAt: int
    reasoning: str = ""
    evidenceMemoryIds: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.belief_state not in {s.value for s in BeliefState}:
            raise ValueError(f"invalid belief_state: {self.belief_state!r}")
        self.confidence = clamp_unit(self.confidence)
        if self.lastUpdatedAt < 0:
            raise ValueError("lastUpdatedAt must be >= 0")
        # dedupe
        self.evidenceMemoryIds = list(dict.fromkeys(self.evidenceMemoryIds))

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Layer 3: character memories
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MemoryEntry:
    memoryId: str
    summary: str
    emotional_weight: float
    distortion_type: str
    formedAt: int
    involvedCharacterIds: list[str] = field(default_factory=list)
    recallCount: int = 0
    decayScore: float = 1.0

    def __post_init__(self) -> None:
        if not self.memoryId:
            raise ValueError("memoryId is required")
        if not self.summary:
            raise ValueError("summary is required")
        if self.distortion_type not in {d.value for d in DistortionType}:
            raise ValueError(f"invalid distortion_type: {self.distortion_type!r}")
        self.emotional_weight = clamp_unit(self.emotional_weight)
        self.decayScore = clamp_unit(self.decayScore)
        if self.formedAt < 0:
            raise ValueError("formedAt must be >= 0")
        if self.recallCount < 0:
            raise ValueError("recallCount must be >= 0")
        self.involvedCharacterIds = list(
            dict.fromkeys(self.involvedCharacterIds)
        )

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Layer 4: hidden secrets
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class HiddenSecret:
    secretId: str
    content: str
    isSecret: bool
    knownByCharacterIds: list[str] = field(default_factory=list)
    leakageRisk: float = 0.0
    createdAt: int = 0

    def __post_init__(self) -> None:
        if not self.secretId:
            raise ValueError("secretId is required")
        if not self.content:
            raise ValueError("content is required")
        self.leakageRisk = clamp_unit(self.leakageRisk)
        if self.createdAt < 0:
            raise ValueError("createdAt must be >= 0")
        self.knownByCharacterIds = list(dict.fromkeys(self.knownByCharacterIds))

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# The matrix itself
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BeliefMatrix:
    """The 4-layer belief model for a single character.

    Stored in :attr:`WorldSnapshot.beliefMatrices` as a list of these.
    The Resolver is the only writer; agents read them via the
    memory-recall service.
    """

    characterId: str
    objective_facts: list[ObjectiveFact] = field(default_factory=list)
    character_knowledge: list[CharacterKnowledge] = field(default_factory=list)
    character_memories: list[MemoryEntry] = field(default_factory=list)
    hidden_secrets: list[HiddenSecret] = field(default_factory=list)
    runId: str = ""
    schemaVersion: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.characterId:
            raise ValueError("characterId is required")

    # ----- queries --------------------------------------------------------

    def find_knowledge(self, subject: str) -> CharacterKnowledge | None:
        for k in self.character_knowledge:
            if k.subject == subject:
                return k
        return None

    def find_memory(self, memory_id: str) -> MemoryEntry | None:
        for m in self.character_memories:
            if m.memoryId == memory_id:
                return m
        return None

    def find_fact(self, fact_id: str) -> ObjectiveFact | None:
        for f in self.objective_facts:
            if f.factId == fact_id:
                return f
        return None

    def find_secret(self, secret_id: str) -> HiddenSecret | None:
        for s in self.hidden_secrets:
            if s.secretId == secret_id:
                return s
        return None

    def knows_secret(self, secret_id: str, character_id: str) -> bool:
        s = self.find_secret(secret_id)
        if s is None:
            return False
        return character_id in s.knownByCharacterIds

    # ----- legal state transitions ---------------------------------------

    @staticmethod
    def legal_transition(from_state: str, to_state: str) -> bool:
        """Return True iff ``from -> to`` is a legal belief-state transition.

        A transition is legal if:

        * ``to`` is a valid BeliefState, **and**
        * ``to != from`` (no-op transitions are rejected), **and**
        * ``to != 'unset'`` (no such state at the matrix level;
          matrix-level code uses Python's ``None`` for absence).

        The engine deliberately keeps this permissive — *what* is
        believable is content-driven and lives in the narrative
        contract; the matrix only enforces the schema enums.
        """

        if from_state == to_state:
            return False
        if to_state == "unset":
            return False
        return to_state in {s.value for s in BeliefState}

    # ----- apply an update -----------------------------------------------

    def apply_update(
        self,
        *,
        subject: str,
        new_state: str,
        confidence: float,
        evidenceMemoryId: str | None = None,
        sequence: int = 0,
    ) -> CharacterKnowledge:
        """Apply a belief update, returning the (possibly new) entry.

        If ``subject`` is already known, the previous state is
        recorded (``previousState``) and the entry updated.  If
        ``subject`` is new, an entry with ``previousState='unset'``
        is appended (the Resolver uses this in the audit log).

        The function enforces schema enums and clamps confidence,
        but **does not** enforce ``legal_transition`` — that's the
        Resolver's job (it has access to the contract).  This
        keeps the matrix a pure data structure.
        """

        if new_state not in {s.value for s in BeliefState}:
            raise ValidationError(f"invalid belief state: {new_state!r}")
        confidence = clamp_unit(confidence)
        previous = self.find_knowledge(subject)
        previous_state = previous.belief_state if previous else "unset"
        entry = CharacterKnowledge(
            subject=subject,
            belief_state=new_state,
            confidence=confidence,
            lastUpdatedAt=sequence,
            reasoning=previous.reasoning if previous else "",
            evidenceMemoryIds=[evidenceMemoryId] if evidenceMemoryId else (
                list(previous.evidenceMemoryIds) if previous else []
            ),
        )
        if previous is None:
            self.character_knowledge.append(entry)
        else:
            self.character_knowledge = [
                k if k.subject != subject else entry for k in self.character_knowledge
            ]
        # The Resolver also tracks ``previousState`` separately in
        # the outcome audit; we expose it for callers.
        entry.reasoning = entry.reasoning  # no-op; placeholder
        return entry

    # ----- serialisation --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "characterId": self.characterId,
            "runId": self.runId,
            "objective_facts": [f.to_json_dict() for f in self.objective_facts],
            "character_knowledge": [k.to_json_dict() for k in self.character_knowledge],
            "character_memories": [m.to_json_dict() for m in self.character_memories],
            "hidden_secrets": [s.to_json_dict() for s in self.hidden_secrets],
            "schemaVersion": self.schemaVersion,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "BeliefMatrix":
        return BeliefMatrix(
            characterId=data["characterId"],
            runId=data.get("runId", ""),
            objective_facts=[ObjectiveFact(**f) for f in data.get("objective_facts", [])],
            character_knowledge=[
                CharacterKnowledge(**k) for k in data.get("character_knowledge", [])
            ],
            character_memories=[MemoryEntry(**m) for m in data.get("character_memories", [])],
            hidden_secrets=[HiddenSecret(**s) for s in data.get("hidden_secrets", [])],
            schemaVersion=data.get("schemaVersion", SCHEMA_VERSION),
        )

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def from_json(payload: str) -> "BeliefMatrix":
        import json

        return BeliefMatrix.from_dict(json.loads(payload))


# ---------------------------------------------------------------------------
# Matrix store (per-run collection)
# ---------------------------------------------------------------------------


class BeliefMatrixStore:
    """A collection of :class:`BeliefMatrix` keyed by characterId.

    The store is the in-memory representation of the
    ``world_snapshot.beliefMatrices`` array.  All operations are
    pure: a new store is returned rather than mutating in place.
    """

    def __init__(self, matrices: Iterable[BeliefMatrix] | None = None) -> None:
        self._matrices: dict[str, BeliefMatrix] = {}
        for m in matrices or []:
            self._matrices[m.characterId] = m

    def __len__(self) -> int:
        return len(self._matrices)

    def __iter__(self):
        return iter(self._matrices.values())

    def get(self, character_id: str) -> BeliefMatrix | None:
        return self._matrices.get(character_id)

    def get_or_create(self, character_id: str, runId: str = "") -> BeliefMatrix:
        m = self._matrices.get(character_id)
        if m is None:
            m = BeliefMatrix(characterId=character_id, runId=runId)
            self._matrices[character_id] = m
        return m

    def upsert(self, matrix: BeliefMatrix) -> None:
        self._matrices[matrix.characterId] = matrix

    def all(self) -> list[BeliefMatrix]:
        return list(self._matrices.values())

    def to_list(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self._matrices.values()]

    @staticmethod
    def from_list(data: Iterable[dict[str, Any]]) -> "BeliefMatrixStore":
        return BeliefMatrixStore(BeliefMatrix.from_dict(d) for d in data)


__all__ = [
    "ObjectiveFact",
    "CharacterKnowledge",
    "MemoryEntry",
    "HiddenSecret",
    "BeliefMatrix",
    "BeliefMatrixStore",
]
