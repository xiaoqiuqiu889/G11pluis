"""World snapshot data class — the canonical run state.

A :class:`WorldSnapshot` is the single source of truth for a run.  It
is what every agent reads from, and the **only** thing the Resolver
writes to.  See ``server/config/schemas/world_snapshot.schema.json``
for the authoritative field definitions.

Design notes
------------
* The snapshot is a **plain dataclass** with full type hints — no
  ORM, no framework lock-in.  The Resolver can construct a new
  snapshot in memory and the persistence layer (out of scope for
  this package) is responsible for serialising it.
* Numeric fields are stored in their *clamped* form.  Reducers and
  the Resolver never write an out-of-range value.
* ``checksum`` is computed over the canonical payload (everything
  except ``checksum`` and ``timestamp``) so any tampering at load
  time is detectable.  The Resolver is expected to set this.
* Serialisation goes through :func:`to_dict` and :func:`from_dict`
  so the JSON shape stays aligned with the schema.  ``to_json`` /
  ``from_json`` are thin wrappers over the standard library.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable

from .types import (
    SCHEMA_VERSION,
    ScenePhase,
    Era,
    CASE_ERAS,
    clamp_unit,
    clamp_relationship,
)


# ---------------------------------------------------------------------------
# Sub-blocks
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CanonicalState:
    """Top-level scene/era/phase metadata."""

    currentSceneId: str
    era: str
    turnIndex: int
    phase: str
    activeContractId: str = ""
    activeBeatId: str | None = None
    endingId: str | None = None
    globalTension: float = 0.0

    def __post_init__(self) -> None:
        if self.phase not in {p.value for p in ScenePhase}:
            raise ValueError(f"invalid phase: {self.phase!r}")
        # Era validation: accept either one of the 13 canonical
        # :class:`Era` values or a case-scoped shorthand declared
        # in :data:`types.CASE_ERAS` (ADR 0007, P0-7).  We union
        # the values across every case so a snapshot can be
        # constructed without knowing the case slug at this point;
        # the case-aware check is done at the contract / resolver
        # boundary.
        legal_eras = {e.value for e in Era}
        for case_map in CASE_ERAS.values():
            legal_eras.update(case_map.values())
        if self.era not in legal_eras:
            raise ValueError(
                f"invalid era: {self.era!r} "
                f"(not in Era enum or any case-scoped override in CASE_ERAS)"
            )
        self.globalTension = clamp_unit(self.globalTension)
        if self.turnIndex < 0:
            raise ValueError("turnIndex must be >= 0")


@dataclass(slots=True)
class RelationshipState:
    """A single directed relationship pair (from -> to)."""

    from_: str
    to: str
    trust: float
    intimacy: float
    unresolvedConflict: float
    respect: float = 0.0
    fear: float = 0.0
    lastUpdatedAt: int = 0

    def __post_init__(self) -> None:
        if not self.from_ or not self.to:
            raise ValueError("from and to must be non-empty")
        self.trust = clamp_relationship(self.trust)
        self.intimacy = clamp_relationship(self.intimacy)
        self.respect = clamp_relationship(self.respect)
        self.fear = clamp_unit(self.fear)
        self.unresolvedConflict = clamp_unit(self.unresolvedConflict)
        if self.lastUpdatedAt < 0:
            raise ValueError("lastUpdatedAt must be >= 0")

    # ``dataclasses.asdict`` uses the field name, but the schema uses
    # ``from`` (a Python keyword) — provide a JSON-friendly dict.
    def to_json_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_,
            "to": self.to,
            "trust": self.trust,
            "intimacy": self.intimacy,
            "unresolvedConflict": self.unresolvedConflict,
            "respect": self.respect,
            "fear": self.fear,
            "lastUpdatedAt": self.lastUpdatedAt,
        }


@dataclass(slots=True)
class ArtifactState:
    """Object ownership + state.  See :mod:`artifact` for the state machine."""

    artifactId: str
    ownerId: str
    state: str
    isRevealed: bool
    location: str | None = None
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.artifactId:
            raise ValueError("artifactId must be non-empty")
        if not self.ownerId:
            raise ValueError("ownerId must be non-empty")
        if len(self.tags) > 16:
            raise ValueError("max 16 tags")
        # dedupe while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for t in self.tags:
            if t not in seen:
                seen.add(t)
                deduped.append(t)
        self.tags = deduped


@dataclass(slots=True)
class DirectorState:
    """Director-side bookkeeping."""

    currentBeatId: str
    elapsedTurnsInScene: int = 0
    actionsSpentInScene: int = 0
    firedBeats: list[str] = field(default_factory=list)
    hitAnchors: list[str] = field(default_factory=list)
    forbiddenRevealsCheckedAt: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.elapsedTurnsInScene < 0:
            raise ValueError("elapsedTurnsInScene must be >= 0")
        if self.actionsSpentInScene < 0:
            raise ValueError("actionsSpentInScene must be >= 0")
        # dedupe fired beats and hit anchors
        self.firedBeats = list(dict.fromkeys(self.firedBeats))
        self.hitAnchors = list(dict.fromkeys(self.hitAnchors))


@dataclass(slots=True)
class MemoryItem:
    """Currently-recalled memory.  See belief_matrix.MemoryEntry for the
    internal representation used by the memory-recall agent."""

    memoryId: str
    ownerCharacterId: str
    summary: str
    recallWeight: float
    decayScore: float
    lastRecalledAt: int | None = None
    embeddingHash: str = ""

    def __post_init__(self) -> None:
        if len(self.memoryId) < 1 or len(self.memoryId) > 64:
            raise ValueError("memoryId length out of range")
        if len(self.ownerCharacterId) < 1 or len(self.ownerCharacterId) > 64:
            raise ValueError("ownerCharacterId length out of range")
        if len(self.summary) < 1 or len(self.summary) > 800:
            raise ValueError("summary length out of range")
        self.recallWeight = clamp_unit(self.recallWeight)
        self.decayScore = clamp_unit(self.decayScore)
        if self.lastRecalledAt is not None and self.lastRecalledAt < 0:
            raise ValueError("lastRecalledAt must be >= 0")
        if self.embeddingHash and len(self.embeddingHash) < 16:
            raise ValueError("embeddingHash too short")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "memoryId": self.memoryId,
            "ownerCharacterId": self.ownerCharacterId,
            "summary": self.summary,
            "recallWeight": self.recallWeight,
            "decayScore": self.decayScore,
            "lastRecalledAt": self.lastRecalledAt,
            "embeddingHash": self.embeddingHash,
        }


@dataclass(slots=True)
class RecentOutcomeRef:
    outcomeId: str
    eventSequence: int
    timestamp: str

    def __post_init__(self) -> None:
        uuid.UUID(self.outcomeId)  # validate format
        if self.eventSequence < 0:
            raise ValueError("eventSequence must be >= 0")
        # Validate ISO-8601 by re-parsing
        datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Top-level snapshot
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WorldSnapshot:
    """The single canonical world state for a run.

    Construction
    ------------
    A run starts from a "fresh" snapshot, built via :meth:`empty` or
    hydrated from disk via :meth:`from_dict` / :meth:`from_json`.
    After every accepted :class:`engine.resolver.ResolverOutcome` the
    Resolver produces a new snapshot via the pure helpers
    (:meth:`with_canonical_state`, :meth:`with_relationship_state`,
    :meth:`with_artifact_state`, :meth:`with_director_state`,
    :meth:`with_belief_matrices`, :meth:`with_causal_seeds_active`,
    :meth:`with_recent_outcomes`).

    All ``with_*`` helpers are **pure** — they return a new snapshot
    and never mutate ``self``.  This is what makes replay and
    regression testing cheap.
    """

    runId: str
    eventSequence: int
    canonicalState: CanonicalState
    relationshipState: list[RelationshipState]
    artifactState: list[ArtifactState]
    directorState: DirectorState
    beliefMatrices: list[dict[str, Any]]  # belief_matrix entries; raw dicts to avoid circular import
    memories: list[MemoryItem]
    causalSeedsActive: list[dict[str, Any]]  # causal_seed entries; raw dicts likewise
    recentOutcomes: list[RecentOutcomeRef] = field(default_factory=list)
    timestamp: str = ""
    checksum: str = ""
    schemaVersion: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        # Validate runId
        try:
            uuid.UUID(self.runId)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"runId must be a UUID: {exc}") from exc
        if self.eventSequence < 0:
            raise ValueError("eventSequence must be >= 0")
        if self.schemaVersion != SCHEMA_VERSION:
            raise ValueError(f"schemaVersion must be {SCHEMA_VERSION}")
        if not self.timestamp:
            self.timestamp = (
                datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            )

    # ----- factory helpers ------------------------------------------------

    @staticmethod
    def empty(runId: str, sceneId: str, era: str | Era, contractId: str = "") -> "WorldSnapshot":
        """Construct a fresh, zero-state snapshot for a new run.

        The scene starts in :attr:`ScenePhase.SETUP` with neutral
        relationships and an empty belief / artifact / seed store.
        """

        if isinstance(era, Era):
            era = era.value
        canonical = CanonicalState(
            currentSceneId=sceneId,
            era=era,
            turnIndex=0,
            phase=ScenePhase.SETUP.value,
            activeContractId=contractId,
            activeBeatId=None,
            endingId=None,
            globalTension=0.0,
        )
        director = DirectorState(
            currentBeatId="beat_setup_0",
            elapsedTurnsInScene=0,
            actionsSpentInScene=0,
        )
        return WorldSnapshot(
            runId=runId,
            eventSequence=0,
            canonicalState=canonical,
            relationshipState=[],
            artifactState=[],
            directorState=director,
            beliefMatrices=[],
            memories=[],
            causalSeedsActive=[],
            recentOutcomes=[],
        )

    # ----- pure update helpers (used by the Resolver) ---------------------

    def with_canonical_state(self, **changes: Any) -> "WorldSnapshot":
        """Return a copy with selected :class:`CanonicalState` fields changed."""

        current = asdict(self.canonicalState)
        current.update(changes)
        new_canonical = CanonicalState(**current)
        return WorldSnapshot(
            runId=self.runId,
            eventSequence=self.eventSequence,
            canonicalState=new_canonical,
            relationshipState=list(self.relationshipState),
            artifactState=list(self.artifactState),
            directorState=self.directorState,
            beliefMatrices=[dict(m) for m in self.beliefMatrices],
            memories=list(self.memories),
            causalSeedsActive=[dict(s) for s in self.causalSeedsActive],
            recentOutcomes=list(self.recentOutcomes),
            timestamp=self.timestamp,
            checksum=self.checksum,
        )

    def with_relationship_state(self, relationships: Iterable[RelationshipState]) -> "WorldSnapshot":  # noqa: E501
        return WorldSnapshot(
            runId=self.runId,
            eventSequence=self.eventSequence,
            canonicalState=self.canonicalState,
            relationshipState=list(relationships),
            artifactState=list(self.artifactState),
            directorState=self.directorState,
            beliefMatrices=[dict(m) for m in self.beliefMatrices],
            memories=list(self.memories),
            causalSeedsActive=[dict(s) for s in self.causalSeedsActive],
            recentOutcomes=list(self.recentOutcomes),
            timestamp=self.timestamp,
            checksum=self.checksum,
        )

    def with_artifact_state(self, artifacts: Iterable[ArtifactState]) -> "WorldSnapshot":
        return WorldSnapshot(
            runId=self.runId,
            eventSequence=self.eventSequence,
            canonicalState=self.canonicalState,
            relationshipState=list(self.relationshipState),
            artifactState=list(artifacts),
            directorState=self.directorState,
            beliefMatrices=[dict(m) for m in self.beliefMatrices],
            memories=list(self.memories),
            causalSeedsActive=[dict(s) for s in self.causalSeedsActive],
            recentOutcomes=list(self.recentOutcomes),
            timestamp=self.timestamp,
            checksum=self.checksum,
        )

    def with_director_state(self, director: DirectorState) -> "WorldSnapshot":
        return WorldSnapshot(
            runId=self.runId,
            eventSequence=self.eventSequence,
            canonicalState=self.canonicalState,
            relationshipState=list(self.relationshipState),
            artifactState=list(self.artifactState),
            directorState=director,
            beliefMatrices=[dict(m) for m in self.beliefMatrices],
            memories=list(self.memories),
            causalSeedsActive=[dict(s) for s in self.causalSeedsActive],
            recentOutcomes=list(self.recentOutcomes),
            timestamp=self.timestamp,
            checksum=self.checksum,
        )

    def with_belief_matrices(self, matrices: Iterable[dict[str, Any]]) -> "WorldSnapshot":
        return WorldSnapshot(
            runId=self.runId,
            eventSequence=self.eventSequence,
            canonicalState=self.canonicalState,
            relationshipState=list(self.relationshipState),
            artifactState=list(self.artifactState),
            directorState=self.directorState,
            beliefMatrices=[dict(m) for m in matrices],
            memories=list(self.memories),
            causalSeedsActive=[dict(s) for s in self.causalSeedsActive],
            recentOutcomes=list(self.recentOutcomes),
            timestamp=self.timestamp,
            checksum=self.checksum,
        )

    def with_causal_seeds_active(self, seeds: Iterable[dict[str, Any]]) -> "WorldSnapshot":
        return WorldSnapshot(
            runId=self.runId,
            eventSequence=self.eventSequence,
            canonicalState=self.canonicalState,
            relationshipState=list(self.relationshipState),
            artifactState=list(self.artifactState),
            directorState=self.directorState,
            beliefMatrices=[dict(m) for m in self.beliefMatrices],
            memories=list(self.memories),
            causalSeedsActive=[dict(s) for s in seeds],
            recentOutcomes=list(self.recentOutcomes),
            timestamp=self.timestamp,
            checksum=self.checksum,
        )

    def with_recent_outcomes(self, outcomes: Iterable[RecentOutcomeRef]) -> "WorldSnapshot":
        return WorldSnapshot(
            runId=self.runId,
            eventSequence=self.eventSequence,
            canonicalState=self.canonicalState,
            relationshipState=list(self.relationshipState),
            artifactState=list(self.artifactState),
            directorState=self.directorState,
            beliefMatrices=[dict(m) for m in self.beliefMatrices],
            memories=list(self.memories),
            causalSeedsActive=[dict(s) for s in self.causalSeedsActive],
            recentOutcomes=list(outcomes),
            timestamp=self.timestamp,
            checksum=self.checksum,
        )

    def with_event_sequence(self, seq: int) -> "WorldSnapshot":
        if seq < self.eventSequence:
            raise ValueError("eventSequence must be monotonic non-decreasing")
        return WorldSnapshot(
            runId=self.runId,
            eventSequence=seq,
            canonicalState=self.canonicalState,
            relationshipState=list(self.relationshipState),
            artifactState=list(self.artifactState),
            directorState=self.directorState,
            beliefMatrices=[dict(m) for m in self.beliefMatrices],
            memories=list(self.memories),
            causalSeedsActive=[dict(s) for s in self.causalSeedsActive],
            recentOutcomes=list(self.recentOutcomes),
            timestamp=self.timestamp,
            checksum=self.checksum,
        )

    def with_timestamp(self, ts: str) -> "WorldSnapshot":
        return WorldSnapshot(
            runId=self.runId,
            eventSequence=self.eventSequence,
            canonicalState=self.canonicalState,
            relationshipState=list(self.relationshipState),
            artifactState=list(self.artifactState),
            directorState=self.directorState,
            beliefMatrices=[dict(m) for m in self.beliefMatrices],
            memories=list(self.memories),
            causalSeedsActive=[dict(s) for s in self.causalSeedsActive],
            recentOutcomes=list(self.recentOutcomes),
            timestamp=ts,
            checksum=self.checksum,
        )

    def with_checksum(self, digest: str) -> "WorldSnapshot":
        if len(digest) != 64:
            raise ValueError("checksum must be 64 hex chars (SHA-256)")
        return WorldSnapshot(
            runId=self.runId,
            eventSequence=self.eventSequence,
            canonicalState=self.canonicalState,
            relationshipState=list(self.relationshipState),
            artifactState=list(self.artifactState),
            directorState=self.directorState,
            beliefMatrices=[dict(m) for m in self.beliefMatrices],
            memories=list(self.memories),
            causalSeedsActive=[dict(s) for s in self.causalSeedsActive],
            recentOutcomes=list(self.recentOutcomes),
            timestamp=self.timestamp,
            checksum=digest,
        )

    # ----- serialisation --------------------------------------------------

    def compute_checksum(self) -> str:
        """Return the SHA-256 hex digest of the canonical payload.

        The canonical payload is everything *except* ``checksum`` and
        ``timestamp``.  Serialised via :func:`to_dict` (sort_keys=True)
        so the result is stable across runs and platforms.
        """

        data = self.to_dict()
        data.pop("checksum", None)
        data.pop("timestamp", None)
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.runId,
            "eventSequence": self.eventSequence,
            "canonicalState": asdict(self.canonicalState),
            "relationshipState": [r.to_json_dict() for r in self.relationshipState],
            "artifactState": [asdict(a) for a in self.artifactState],
            "directorState": asdict(self.directorState),
            "beliefMatrices": [dict(m) for m in self.beliefMatrices],
            "memories": [m.to_json_dict() for m in self.memories],
            "causalSeedsActive": [dict(s) for s in self.causalSeedsActive],
            "recentOutcomes": [asdict(o) for o in self.recentOutcomes],
            "timestamp": self.timestamp,
            "checksum": self.checksum,
            "schemaVersion": self.schemaVersion,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "WorldSnapshot":
        canonical = CanonicalState(**data["canonicalState"])
        # RelationshipState uses ``from_`` because ``from`` is a Python keyword;
        # map the JSON alias explicitly instead of forwarding both names.
        relationships = []
        for r in data.get("relationshipState", []):
            rel = RelationshipState(
                from_=r["from"],
                to=r["to"],
                trust=r["trust"],
                intimacy=r["intimacy"],
                unresolvedConflict=r["unresolvedConflict"],
                respect=r.get("respect", 0.0),
                fear=r.get("fear", 0.0),
                lastUpdatedAt=r.get("lastUpdatedAt", 0),
            )
            relationships.append(rel)
        artifacts = [ArtifactState(**a) for a in data.get("artifactState", [])]
        director = DirectorState(**data["directorState"])
        memories = [MemoryItem(**m) for m in data.get("memories", [])]
        recent = [
            RecentOutcomeRef(**o) for o in data.get("recentOutcomes", [])
        ]
        return WorldSnapshot(
            runId=data["runId"],
            eventSequence=data["eventSequence"],
            canonicalState=canonical,
            relationshipState=relationships,
            artifactState=artifacts,
            directorState=director,
            beliefMatrices=list(data.get("beliefMatrices", [])),
            memories=memories,
            causalSeedsActive=list(data.get("causalSeedsActive", [])),
            recentOutcomes=recent,
            timestamp=data.get("timestamp", ""),
            checksum=data.get("checksum", ""),
            schemaVersion=data.get("schemaVersion", SCHEMA_VERSION),
        )

    @staticmethod
    def from_json(payload: str) -> "WorldSnapshot":
        return WorldSnapshot.from_dict(json.loads(payload))

    def verify_checksum(self) -> bool:
        """Return True iff ``self.checksum`` matches the computed digest."""

        if not self.checksum:
            return False
        return self.checksum == self.compute_checksum()


__all__ = [
    "CanonicalState",
    "RelationshipState",
    "ArtifactState",
    "DirectorState",
    "MemoryItem",
    "RecentOutcomeRef",
    "WorldSnapshot",
]
