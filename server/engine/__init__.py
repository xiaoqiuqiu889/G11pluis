"""AI-native game engine — deterministic state machine + event ledger.

This package implements the core of the 《革命街没有尽头》AI-native
remake: a deterministic state machine that settles every player
and NPC action into a single canonical world state.

Top-level layout
----------------

* :mod:`.types`             — shared enums and clamps
* :mod:`.exceptions`        — engine error hierarchy
* :mod:`.world_snapshot`    — the canonical state dataclass
* :mod:`.event_log`         — append-only event ledger
* :mod:`.relationship`      — relationship state management
* :mod:`.artifact`          — artifact ownership state machine
* :mod:`.belief_matrix`     — 4-layer belief model
* :mod:`.causal_seed`       — cross-era causal seed store
* :mod:`.state_machine`     — 12 atomic-action reducers
* :mod:`.resolver`          — the single canonical-state writer
* :mod:`.degradation`       — 4-level fallback chain

Public API
----------
The names below are re-exported so callers can do::

    from server.engine import WorldSnapshot, Resolver, EventLog, ...

without knowing the internal module layout.
"""

from __future__ import annotations

from .artifact import (
    ArtifactOperation,
    ArtifactUpdate,
    VALID_OPERATIONS,
    apply_artifact_updates,
    assert_uniqueness,
    find_artifact,
    is_revealed,
    owner_of,
)
from .belief_matrix import (
    BeliefMatrix,
    BeliefMatrixStore,
    CharacterKnowledge,
    HiddenSecret,
    MemoryEntry,
    ObjectiveFact,
)
from .causal_seed import (
    CausalSeed,
    CausalSeedStore,
    EraSpan,
    TriggerCondition,
)
from .degradation import (
    DegradationChain,
    DegradationLevel,
    DegradationRecord,
    FallbackScript,
    LEVEL_ORDER,
    NPCFallbackLine,
    with_director_timeout_skip,
    with_hard_degradation,
    with_npc_timeout_fallback,
    with_persist_failure,
)
from .event_log import EventLog, GameEvent, deterministic_seed
from .exceptions import (
    ActionBudgetExceededError,
    ActionRejectedError,
    ArtifactConflictError,
    BeliefStateContradictionError,
    DegradationError,
    DirectorTimeoutError,
    DuplicateProposalError,
    EngineError,
    EvidenceNotFoundError,
    EvidenceRequiredError,
    ForbiddenRevealError,
    HardDegradationError,
    IdempotencyReplayError,
    IllegalTargetError,
    IllegalTransitionError,
    LowConfidenceOverriddenError,
    NPCTimeoutError,
    PersistFailureError,
    ResolverError,
    SequenceMismatchError,
    TargetNotPresentError,
    TargetRequiredError,
    TurnBudgetExceededError,
    UngroundedMemoryError,
    ValidationError,
)
from .relationship import (
    DEFAULT_DELTAS,
    RelationshipDelta,
    apply_relationship_delta,
    apply_relationship_deltas,
    find_pair,
)
from .resolver import (
    DirectorBeatInput,
    NarrativeContract,
    NPCProposal,
    Resolver,
    ResolverOutcome,
)
from .state_machine import (
    REDUCERS,
    ReducerOutcome,
    SceneBudget,
    apply_reducer_outcome,
    reduce,
)
from .types import (
    ActionType,
    BELIEF_STATES,
    BeliefState,
    DISTORTION_TYPES,
    DistortionType,
    Era,
    MAX_RELATIONSHIP,
    MAX_RELATIONSHIP_DELTA,
    MIN_RELATIONSHIP,
    SCHEMA_VERSION,
    ScenePhase,
    TRIGGER_TYPES,
    TriggerType,
    clamp,
    clamp_relationship,
    clamp_relationship_delta,
    clamp_unit,
)
from .world_snapshot import (
    ArtifactState,
    CanonicalState,
    DirectorState,
    MemoryItem,
    RecentOutcomeRef,
    RelationshipState,
    WorldSnapshot,
)

__version__ = "1.0.0"

__all__ = [
    # types
    "ActionType",
    "BeliefState",
    "DistortionType",
    "TriggerType",
    "ScenePhase",
    "Era",
    "SCHEMA_VERSION",
    "MAX_RELATIONSHIP",
    "MIN_RELATIONSHIP",
    "MAX_RELATIONSHIP_DELTA",
    "BELIEF_STATES",
    "DISTORTION_TYPES",
    "TRIGGER_TYPES",
    "clamp",
    "clamp_unit",
    "clamp_relationship",
    "clamp_relationship_delta",
    # exceptions
    "EngineError",
    "ValidationError",
    "ActionRejectedError",
    "ActionBudgetExceededError",
    "TurnBudgetExceededError",
    "TargetRequiredError",
    "TargetNotPresentError",
    "EvidenceRequiredError",
    "EvidenceNotFoundError",
    "ArtifactConflictError",
    "IdempotencyReplayError",
    "SequenceMismatchError",
    "IllegalTransitionError",
    "ResolverError",
    "ForbiddenRevealError",
    "UngroundedMemoryError",
    "BeliefStateContradictionError",
    "IllegalTargetError",
    "DuplicateProposalError",
    "LowConfidenceOverriddenError",
    "DegradationError",
    "NPCTimeoutError",
    "DirectorTimeoutError",
    "HardDegradationError",
    "PersistFailureError",
    # world snapshot
    "CanonicalState",
    "RelationshipState",
    "ArtifactState",
    "DirectorState",
    "MemoryItem",
    "RecentOutcomeRef",
    "WorldSnapshot",
    # event log
    "GameEvent",
    "EventLog",
    "deterministic_seed",
    # relationship
    "RelationshipDelta",
    "DEFAULT_DELTAS",
    "apply_relationship_delta",
    "apply_relationship_deltas",
    "find_pair",
    # artifact
    "ArtifactOperation",
    "VALID_OPERATIONS",
    "ArtifactUpdate",
    "apply_artifact_updates",
    "assert_uniqueness",
    "find_artifact",
    "is_revealed",
    "owner_of",
    # belief matrix
    "ObjectiveFact",
    "CharacterKnowledge",
    "MemoryEntry",
    "HiddenSecret",
    "BeliefMatrix",
    "BeliefMatrixStore",
    # causal seed
    "TriggerCondition",
    "EraSpan",
    "CausalSeed",
    "CausalSeedStore",
    # state machine
    "REDUCERS",
    "ReducerOutcome",
    "SceneBudget",
    "reduce",
    "apply_reducer_outcome",
    # resolver
    "NPCProposal",
    "DirectorBeatInput",
    "NarrativeContract",
    "ResolverOutcome",
    "Resolver",
    # degradation
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
