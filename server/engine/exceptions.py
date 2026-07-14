"""Engine-level exception hierarchy.

Centralising exceptions lets call sites (HTTP handlers, tests, the
Director agent) pattern-match on failure modes without parsing string
messages.  Every reducer / resolver path raises a subclass of
:exc:`EngineError` so the degradation chain can pick a fallback
without ambiguity.
"""

from __future__ import annotations


class EngineError(Exception):
    """Base class for every error raised inside the engine."""


# ---------------------------------------------------------------------------
# Validation errors (deterministic, fail fast)
# ---------------------------------------------------------------------------


class ValidationError(EngineError):
    """A field failed schema validation; safe to surface to the client."""


class ActionRejectedError(ValidationError):
    """The submitted actionType is not in the active scene's whitelist."""


class TargetRequiredError(ValidationError):
    """An action requiring a target character was submitted without one."""


class EvidenceRequiredError(ValidationError):
    """An action requiring evidence (artifact ID) was submitted without one."""


class TargetNotPresentError(ValidationError):
    """The target character is not on stage in the active scene."""


class EvidenceNotFoundError(ValidationError):
    """A referenced artifactId does not exist in artifactState."""


class ActionBudgetExceededError(ValidationError):
    """The player has already used the per-action-type budget for this scene."""


class TurnBudgetExceededError(ValidationError):
    """The player has exceeded the scene's max_turns."""


class IdempotencyReplayError(ValidationError):
    """The same idempotencyKey was already applied; this is a benign replay."""


class SequenceMismatchError(ValidationError):
    """Client's expectedEventSequence is too far behind the canonical sequence."""


class ArtifactConflictError(ValidationError):
    """The same physical artifact is already owned by another location."""


class IllegalTransitionError(ValidationError):
    """An end_run beat was submitted with an endingId not in the contract's legal_endings."""


# ---------------------------------------------------------------------------
# Resolver errors
# ---------------------------------------------------------------------------


class ResolverError(EngineError):
    """Base class for any error originating inside the Resolver."""


class ForbiddenRevealError(ResolverError):
    """An NPC proposal would surface information on the contract's forbidden_reveals list."""


class UngroundedMemoryError(ResolverError):
    """An NPC proposal cited a memoryId not in the current recall set."""


class BeliefStateContradictionError(ResolverError):
    """An NPC proposal contradicts an established belief_state of the speaker."""


class IllegalTargetError(ResolverError):
    """The NPC proposal's target is not on stage in the active scene."""


class DuplicateProposalError(ResolverError):
    """The same proposalId has already been processed in this run."""


class LowConfidenceOverriddenError(ResolverError):
    """A low-confidence NPC proposal was overridden by a higher-priority one."""


# ---------------------------------------------------------------------------
# Degradation chain errors
# ---------------------------------------------------------------------------


class DegradationError(EngineError):
    """Triggered when the degradation chain is invoked."""


class NPCTimeoutError(DegradationError):
    """L1 trigger: NPC agent did not respond in time."""


class DirectorTimeoutError(DegradationError):
    """L2 trigger: Director agent did not respond in time."""


class HardDegradationError(DegradationError):
    """L3 trigger: second consecutive failure before the Resolver."""


class PersistFailureError(DegradationError):
    """L4 trigger: Resolver failed to persist the outcome."""


__all__ = [name for name in dir() if name.endswith("Error") or name == "EngineError"]
