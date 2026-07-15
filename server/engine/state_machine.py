"""Deterministic state machine with 12 structured-action Reducers.

The state machine is the heart of the AI-native engine.  Given a
:class:`PlayerAction` and a :class:`WorldSnapshot`, a **reducer**
computes a :class:`ReducerOutcome` — the deltas to relationships,
artifacts and beliefs that *would* result if the Resolver accepted
the action.  The Resolver then merges this proposal with NPC and
Director proposals before persisting.

Why a separate state machine
----------------------------
* **Determinism** — every reducer is a pure function.  Replay
  reproduces outcomes byte-for-byte.
* **Whitelist enforcement** — the active scene contract declares
  which action types are legal *this turn*.  Reducers that try to
  fire an off-whitelist action raise :exc:`ActionRejectedError`.
* **No LLM dependency** — the engine's state machine runs without
  any model.  AI is layered on top in W3.
* **Clamping is mandatory** — every numeric delta passes through
  :mod:`types`'s clamp helpers, so a malicious or runaway
  computation cannot overflow the schema enums.

The 12 reducers
---------------
Each maps to one of the 12 atomic :class:`ActionType` values.
See the docstrings of each function for its semantics.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .artifact import ArtifactOperation, ArtifactUpdate, apply_artifact_updates
from .belief_matrix import BeliefMatrixStore
from .causal_seed import CausalSeed
from .exceptions import (
    ActionBudgetExceededError,
    ActionRejectedError,
    EvidenceNotFoundError,
    EvidenceRequiredError,
    TargetNotPresentError,
    TargetRequiredError,
    TurnBudgetExceededError,
    ValidationError,
)
from .relationship import (
    DEFAULT_DELTAS,
    RelationshipDelta,
    apply_relationship_deltas,
)
from .types import (
    ActionType,
    EVIDENCE_REQUIRED_ACTIONS,
    MAX_RELATIONSHIP_DELTA,
    TARGET_REQUIRED_ACTIONS,
    clamp_unit,
)
from .world_snapshot import WorldSnapshot


# ---------------------------------------------------------------------------
# Outcome containers
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ReducerOutcome:
    """The deterministic delta a single reducer proposes.

    Every reducer returns one of these.  The Resolver is the only
    component allowed to apply it to the canonical state; the
    outcome here is *pure data*.

    Attributes
    ----------
    accepted : bool
        True if the action was legal and produced a delta; False
        if it was rejected at the validation gate (e.g. off
        whitelist, missing target, missing evidence).
    rejectReason : str
        The reason code for rejection (e.g. ``"action_not_whitelisted"``,
        ``"target_required"``, ``"evidence_required"``).  Empty if
        accepted.
    relationshipDeltas : list[RelationshipDelta]
        Per-pair deltas to apply to ``relationshipState``.
    artifactUpdates : list[ArtifactUpdate]
        Per-artifact updates to apply to ``artifactState``.
    beliefUpdates : list[dict]
        Belief deltas to apply; the Resolver turns these into
        :class:`belief_matrix.CharacterKnowledge` updates.
    causalSeeds : list[CausalSeed]
        New seeds to plant (e.g. ``photo_in_pocket``).
    clampedValues : list[dict]
        Audit of any clamp events.  Format matches the resolver
        outcome schema's ``clampedValues`` array.
    actionWhitelist : list[str]
        The post-action whitelist of remaining legal actions.
        The Resolver uses this to drive the **changes-available-actions**
        leg of the four-questions self-check.
    consumedTurn : bool
        True if this action consumed one of the scene's
        ``max_turns`` slots.
    deterministic_decisions : list[str]
        Human-readable list of decisions the reducer made
        (e.g. ``"rejected action: action_not_whitelisted"``).
    """

    accepted: bool
    rejectReason: str = ""
    relationshipDeltas: list[RelationshipDelta] = field(default_factory=list)
    artifactUpdates: list[ArtifactUpdate] = field(default_factory=list)
    beliefUpdates: list[dict] = field(default_factory=list)
    causalSeeds: list[CausalSeed] = field(default_factory=list)
    clampedValues: list[dict] = field(default_factory=list)
    actionWhitelist: list[str] = field(default_factory=list)
    consumedTurn: bool = True
    deterministic_decisions: list[str] = field(default_factory=list)
    _idempotency_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "rejectReason": self.rejectReason,
            "relationshipDeltas": [d.to_json_dict() for d in self.relationshipDeltas],
            "artifactUpdates": [u.to_json_dict() for u in self.artifactUpdates],
            "beliefUpdates": list(self.beliefUpdates),
            "causalSeeds": [s.to_dict() for s in self.causalSeeds],
            "clampedValues": list(self.clampedValues),
            "actionWhitelist": list(self.actionWhitelist),
            "consumedTurn": self.consumedTurn,
            "deterministic_decisions": list(self.deterministic_decisions),
        }


# ---------------------------------------------------------------------------
# Action whitelist + budget model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SceneBudget:
    """A scene's per-action and per-turn budgets.

    Mirrors the ``turn_budget`` and ``total_action_budget`` fields
    of a narrative contract.  The state machine consults this on
    every action to decide whether the player may still fire it.
    """

    sceneId: str
    max_turns: int
    total_action_budget: int
    per_action: dict[str, int] = field(default_factory=dict)
    consumed: dict[str, int] = field(default_factory=dict)
    elapsed_turns: int = 0

    def __post_init__(self) -> None:
        """Enforce the per-action-budget hard cap.

        The sum of every per-action cap may not exceed
        ``total_action_budget``.  A scene contract that violates
        this invariant is rejected at construction time, not at
        reducer dispatch time — this is the **P0-3** enforcement
        point.

        Raises
        ------
        ValueError
            ``sum(per_action) > total_action_budget``.
        """
        per_action_sum = sum(int(v) for v in self.per_action.values())
        if per_action_sum > self.total_action_budget:
            raise ValueError(
                f"SceneBudget[{self.sceneId}]: per_action sum "
                f"({per_action_sum}) exceeds total_action_budget "
                f"({self.total_action_budget})"
            )

    def remaining(self, action: str) -> int:
        cap = self.per_action.get(action, self.total_action_budget)
        used = self.consumed.get(action, 0)
        return max(0, cap - used)

    def can_fire(self, action: str) -> bool:
        if self.elapsed_turns >= self.max_turns:
            return False
        return self.remaining(action) > 0

    def consume(self, action: str, *, turn: bool = True) -> None:
        if not self.can_fire(action):
            raise ActionBudgetExceededError(
                f"action budget exhausted for {action} in {self.sceneId}"
            )
        self.consumed[action] = self.consumed.get(action, 0) + 1
        if turn:
            self.elapsed_turns += 1

    def whitelist(self) -> list[str]:
        return [a for a in self.per_action if self.remaining(a) > 0]


# ---------------------------------------------------------------------------
# Validation gate (shared by all 12 reducers)
# ---------------------------------------------------------------------------


def _validate(
    *,
    action: dict[str, Any],
    scene_whitelist: set[str],
    budget: SceneBudget,
    cast: list[str] | None,
    artifact_ids_in_state: set[str],
) -> list[str]:
    """Run the cross-cutting validation rules.  Returns deterministic_decisions.

    Raises
    ------
    ActionRejectedError
        ``actionType`` not in scene whitelist.
    TurnBudgetExceededError
        The scene's ``max_turns`` has been hit.
    TargetRequiredError
        The action's type requires a target but ``targetId`` is null.
    TargetNotPresentError
        The target is not on stage in the active scene.
    EvidenceRequiredError
        The action's type requires evidence but ``evidenceIds`` is empty.
    EvidenceNotFoundError
        A referenced evidence artifact does not exist in the
        canonical artifact state.
    ActionBudgetExceededError
        The per-action budget is exhausted.
    """

    decisions: list[str] = []
    action_type = action.get("actionType")
    if not action_type:
        raise ValidationError("actionType is required")
    if action_type not in scene_whitelist:
        decisions.append(f"rejected: action {action_type!r} not in scene whitelist")
        raise ActionRejectedError(
            f"action {action_type!r} not in scene whitelist {sorted(scene_whitelist)}"
        )
    if budget.elapsed_turns >= budget.max_turns:
        decisions.append(f"rejected: max_turns ({budget.max_turns}) reached")
        raise TurnBudgetExceededError(
            f"scene {budget.sceneId!r} has reached max_turns ({budget.max_turns})"
        )
    if not budget.can_fire(action_type):
        decisions.append(f"rejected: per-action budget exhausted for {action_type!r}")
        raise ActionBudgetExceededError(
            f"per-action budget for {action_type!r} in {budget.sceneId!r} is exhausted"
        )
    target_id = action.get("targetId")
    if action_type in TARGET_REQUIRED_ACTIONS and not target_id:
        decisions.append(f"rejected: {action_type!r} requires a targetId")
        raise TargetRequiredError(f"{action_type!r} requires a non-null targetId")
    if target_id and cast is not None and target_id not in cast:
        decisions.append(f"rejected: target {target_id!r} not on stage")
        raise TargetNotPresentError(f"target {target_id!r} not on stage in {budget.sceneId!r}")
    evidence_ids = action.get("evidenceIds") or []
    if action_type in EVIDENCE_REQUIRED_ACTIONS and not evidence_ids:
        decisions.append(f"rejected: {action_type!r} requires evidenceIds")
        raise EvidenceRequiredError(f"{action_type!r} requires at least one evidenceId")
    for eid in evidence_ids:
        if eid not in artifact_ids_in_state:
            decisions.append(f"rejected: evidence {eid!r} not in artifactState")
            raise EvidenceNotFoundError(
                f"evidence artifact {eid!r} not found in artifactState"
            )
    return decisions


def _actor_delta(
    actor_id: str,
    target_id: str | None,
    action_type: str,
    disclosure_level: float,
) -> tuple[RelationshipDelta, RelationshipDelta | None]:
    """Compute the (actor→target, target→actor) relationship deltas.

    The defaults from :data:`relationship.DEFAULT_DELTAS` are
    scaled by ``disclosureLevel`` (0..1) so that a fully-opaque
    action produces a smaller magnitude than a fully-open one.
    Trust / intimacy / etc. are then capped at the per-turn
    |delta| ≤ 0.25 by the relationship module.
    """

    defaults = DEFAULT_DELTAS.get(action_type, {})
    magnitude = max(0.0, min(1.0, disclosure_level or 0.5))
    fwd = RelationshipDelta(
        from_=actor_id,
        to=target_id or actor_id,
        trust=defaults.get("trust", 0.0) * magnitude,
        intimacy=defaults.get("intimacy", 0.0) * magnitude,
        unresolvedConflict=defaults.get("unresolvedConflict", 0.0) * magnitude,
        respect=defaults.get("respect", 0.0) * magnitude,
        fear=defaults.get("fear", 0.0) * magnitude,
    )
    # target → actor is the mirror with a small attenuation
    back: RelationshipDelta | None = None
    if target_id:
        back_mag = magnitude * 0.6
        back = RelationshipDelta(
            from_=target_id,
            to=actor_id,
            trust=defaults.get("trust", 0.0) * back_mag,
            intimacy=defaults.get("intimacy", 0.0) * back_mag,
            unresolvedConflict=defaults.get("unresolvedConflict", 0.0) * back_mag,
            respect=defaults.get("respect", 0.0) * back_mag,
            fear=defaults.get("fear", 0.0) * back_mag,
        )
    return fwd, back


# ---------------------------------------------------------------------------
# The 12 reducers
# ---------------------------------------------------------------------------


def _build_reducer(
    handler: Callable[[dict, WorldSnapshot, SceneBudget], ReducerOutcome],
) -> Callable[[dict, WorldSnapshot, SceneBudget], ReducerOutcome]:
    """Decorator that wraps a reducer with idempotency-key derivation.

    The state machine doesn't itself deduplicate, but it does stamp
    the outcome with the action's idempotency key so the Resolver
    can do the canonical dedup.
    """

    def wrapper(action: dict, snapshot: WorldSnapshot, budget: SceneBudget) -> ReducerOutcome:
        outcome = handler(action, snapshot, budget)
        # Stash the idempotency key as an attribute (ReducerOutcome
        # is a slotted dataclass, so setattr needs to use the
        # actual __dict__ via object.__setattr__).
        object.__setattr__(outcome, "_idempotency_key", _make_idempotency_key(action, snapshot))
        return outcome

    return wrapper


def _make_idempotency_key(action: dict, snapshot: WorldSnapshot) -> str:
    raw = (
        f"{snapshot.runId}|{action.get('clientActionId') or ''}|"
        f"{action.get('actionType')}|{action.get('expectedEventSequence')}|"
        f"{action.get('actorId')}|{action.get('targetId') or ''}|"
        f"{','.join(sorted(action.get('evidenceIds') or []))}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


# ----- investigate ----------------------------------------------------------


@_build_reducer
def reduce_investigate(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``investigate`` — examine an object or memory.

    Effects
    -------
    * Small positive trust (player is paying attention).
    * Reveals a memory in the cast's recall set if an artifact
      is referenced.
    * Burns one ``investigate`` budget unit.
    * Does **not** consume a turn by default (per scene contract
      convention; the Resolver can override).
    """

    decisions: list[str] = []
    decisions.append("investigate: examining referenced evidence")
    evidence_ids = action.get("evidenceIds") or []
    actor = action.get("actorId")
    target = action.get("targetId") or actor
    disclosure = float(action.get("disclosureLevel", 0.5))
    fwd, back = _actor_delta(actor, target, ActionType.INVESTIGATE.value, disclosure)
    belief_updates: list[dict] = []
    for eid in evidence_ids:
        belief_updates.append(
            {
                "characterId": target,
                "subject": eid,
                "newState": "reinforced",
                "confidence": clamp_unit(0.4 + 0.2 * disclosure),
                "evidenceMemoryId": None,
                "previousState": "unset",
                "reasonCode": "investigate",
            }
        )
    decisions.append(f"marked {len(evidence_ids)} evidence items as recalled for {target}")
    budget.consume(ActionType.INVESTIGATE.value, turn=False)
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=[fwd] + ([back] if back else []),
        artifactUpdates=[],
        beliefUpdates=belief_updates,
        causalSeeds=[],
        actionWhitelist=budget.whitelist(),
        consumedTurn=False,
        deterministic_decisions=decisions,
    )


# ----- reveal ---------------------------------------------------------------


@_build_reducer
def reduce_reveal(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``reveal`` — surface a previously hidden fact or secret.

    Effects
    -------
    * Mark the target's belief on the subject as ``reinforced``
      (or ``certain`` if disclosure is full).
    * Mark the evidence artifact as ``isRevealed=True``.
    * Plant no seed (reveal is *consumption* of an existing
      secret, not creation of a new one).
    * Burns one ``reveal`` budget unit and one turn.
    """

    decisions: list[str] = ["reveal: surfacing evidence + belief update"]
    actor = action.get("actorId")
    target = action.get("targetId") or actor
    disclosure = float(action.get("disclosureLevel", 0.5))
    is_deceptive = bool(action.get("isDeceptive", False))
    fwd, back = _actor_delta(actor, target, ActionType.REVEAL.value, disclosure)
    evidence_ids = action.get("evidenceIds") or []
    # Set isRevealed on every evidence artifact
    artifact_updates: list[ArtifactUpdate] = [
        ArtifactUpdate(artifactId=eid, operation=ArtifactOperation.REVEAL, reasonCode="reveal")
        for eid in evidence_ids
    ]
    belief_state = "wrong" if is_deceptive else "reinforced" if disclosure < 1.0 else "certain"
    confidence = clamp_unit(0.6 + 0.3 * disclosure)
    belief_updates: list[dict] = [
        {
            "characterId": target,
            "subject": eid,
            "newState": belief_state,
            "confidence": confidence,
            "evidenceMemoryId": None,
            "previousState": "unset",
            "reasonCode": "reveal_deceptive" if is_deceptive else "reveal",
        }
        for eid in evidence_ids
    ]
    if is_deceptive:
        decisions.append("deceptive reveal: target belief marked 'wrong'")
    budget.consume(ActionType.REVEAL.value)
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=[fwd] + ([back] if back else []),
        artifactUpdates=artifact_updates,
        beliefUpdates=belief_updates,
        causalSeeds=[],
        actionWhitelist=budget.whitelist(),
        consumedTurn=True,
        deterministic_decisions=decisions,
    )


# ----- conceal --------------------------------------------------------------


@_build_reducer
def reduce_conceal(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``conceal`` — withdraw a statement or hide an object.

    Effects
    -------
    * Mark referenced evidence as ``isRevealed=False``.
    * Small negative trust (slight evasiveness).
    * Burns one ``conceal`` budget unit and one turn.
    """

    decisions: list[str] = ["conceal: hiding referenced evidence"]
    actor = action.get("actorId")
    target = action.get("targetId") or actor
    disclosure = float(action.get("disclosureLevel", 0.5))
    fwd, back = _actor_delta(actor, target, ActionType.CONCEAL.value, disclosure)
    evidence_ids = action.get("evidenceIds") or []
    artifact_updates: list[ArtifactUpdate] = [
        ArtifactUpdate(artifactId=eid, operation=ArtifactOperation.CONCEAL, reasonCode="conceal")
        for eid in evidence_ids
    ]
    belief_updates: list[dict] = [
        {
            "characterId": target,
            "subject": eid,
            "newState": "denied",
            "confidence": clamp_unit(0.5 + 0.2 * (1.0 - disclosure)),
            "evidenceMemoryId": None,
            "previousState": "unset",
            "reasonCode": "conceal",
        }
        for eid in evidence_ids
    ]
    budget.consume(ActionType.CONCEAL.value)
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=[fwd] + ([back] if back else []),
        artifactUpdates=artifact_updates,
        beliefUpdates=belief_updates,
        causalSeeds=[],
        actionWhitelist=budget.whitelist(),
        consumedTurn=True,
        deterministic_decisions=decisions,
    )


# ----- question -------------------------------------------------------------


@_build_reducer
def reduce_question(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``question`` — ask the target a question.

    Effects
    -------
    * Mild positive intimacy (player shows interest).
    * No artifact changes.
    * Burns one ``question`` budget unit and one turn.
    """

    decisions: list[str] = ["question: probing target without evidence changes"]
    actor = action.get("actorId")
    target = action.get("targetId") or actor
    disclosure = float(action.get("disclosureLevel", 0.5))
    fwd, back = _actor_delta(actor, target, ActionType.QUESTION.value, disclosure)
    budget.consume(ActionType.QUESTION.value)
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=[fwd] + ([back] if back else []),
        artifactUpdates=[],
        beliefUpdates=[],
        causalSeeds=[],
        actionWhitelist=budget.whitelist(),
        consumedTurn=True,
        deterministic_decisions=decisions,
    )


# ----- confront -------------------------------------------------------------


@_build_reducer
def reduce_confront(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``confront`` — bring an unresolved tension into the open.

    Effects
    -------
    * Negative trust (it's hard to confront someone), but
      positive intimacy (honesty).
    * Raised ``unresolvedConflict`` (now it's on the table).
    * Burns one ``confront`` budget unit and one turn.
    """

    decisions: list[str] = ["confront: acknowledging unresolved tension"]
    actor = action.get("actorId")
    target = action.get("targetId") or actor
    disclosure = float(action.get("disclosureLevel", 0.5))
    fwd, back = _actor_delta(actor, target, ActionType.CONFRONT.value, disclosure)
    budget.consume(ActionType.CONFRONT.value)
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=[fwd] + ([back] if back else []),
        artifactUpdates=[],
        beliefUpdates=[],
        causalSeeds=[],
        actionWhitelist=budget.whitelist(),
        consumedTurn=True,
        deterministic_decisions=decisions,
    )


# ----- comfort --------------------------------------------------------------


@_build_reducer
def reduce_comfort(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``comfort`` — acknowledge the target's pain or worry.

    Effects
    -------
    * Strong positive intimacy + trust.
    * Burns one ``comfort`` budget unit and one turn.
    """

    decisions: list[str] = ["comfort: offering emotional support to target"]
    actor = action.get("actorId")
    target = action.get("targetId") or actor
    disclosure = float(action.get("disclosureLevel", 0.5))
    fwd, back = _actor_delta(actor, target, ActionType.COMFORT.value, disclosure)
    budget.consume(ActionType.COMFORT.value)
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=[fwd] + ([back] if back else []),
        artifactUpdates=[],
        beliefUpdates=[],
        causalSeeds=[],
        actionWhitelist=budget.whitelist(),
        consumedTurn=True,
        deterministic_decisions=decisions,
    )


# ----- give -----------------------------------------------------------------


@_build_reducer
def reduce_give(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``give`` — hand an artifact to the target (or take it yourself).

    Effects
    -------
    * Transfers ownership of every evidence artifact to the
      target (or to the actor if no target).
    * Burns one ``give`` budget unit and one turn.
    * The most "AI-native" reducer — it changes the world state
      in a way that's hard to undo (a photo in someone's pocket
      is a different photo than a photo in a bag).
    """

    decisions: list[str] = ["give: transferring artifact ownership"]
    actor = action.get("actorId")
    target = action.get("targetId") or actor
    evidence_ids = action.get("evidenceIds") or []
    if (
        snapshot.canonicalState.currentSceneId == "photo_lab_2008"
        and evidence_ids == ["photo_pair"]
        and target in {"arash", "leila"}
    ):
        # Resolve the aggregate interaction handle into two physical photos.
        photo_b_owner = "arash" if target == "arash" else "leila"
        photo_b_state = "in_book" if target == "arash" else "in_pocket"
        artifact_updates = [
            ArtifactUpdate(artifactId="photo_A", operation=ArtifactOperation.TRANSFER, newOwnerId="leila", reasonCode="photo_pair_choice"),
            ArtifactUpdate(artifactId="photo_A", operation=ArtifactOperation.MODIFY_STATE, newState="in_pocket", reasonCode="photo_pair_choice"),
            ArtifactUpdate(artifactId="photo_B", operation=ArtifactOperation.TRANSFER, newOwnerId=photo_b_owner, reasonCode="photo_pair_choice"),
            ArtifactUpdate(artifactId="photo_B", operation=ArtifactOperation.MODIFY_STATE, newState=photo_b_state, reasonCode="photo_pair_choice"),
            ArtifactUpdate(artifactId="photo_pair", operation=ArtifactOperation.DESTROY, reasonCode="photo_pair_choice_resolved"),
        ]
        decisions.append(
            "resolved photo_pair as one_each"
            if target == "arash"
            else "resolved photo_pair as leila_keeps_both"
        )
    else:
        artifact_updates = [
            ArtifactUpdate(
                artifactId=eid,
                operation=ArtifactOperation.TRANSFER,
                newOwnerId=target,
                reasonCode="give",
            )
            for eid in evidence_ids
        ]
    disclosure = float(action.get("disclosureLevel", 0.5))
    relationship_deltas: list[RelationshipDelta] = []
    if target != actor:
        fwd, back = _actor_delta(actor, target, ActionType.GIVE.value, disclosure)
        relationship_deltas = [fwd] + ([back] if back else [])
    budget.consume(ActionType.GIVE.value)
    decisions.append(
        f"transferred {len(evidence_ids)} artifact(s) from {actor!r} to {target!r}"
    )
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=relationship_deltas,
        artifactUpdates=artifact_updates,
        beliefUpdates=[],
        causalSeeds=[],
        actionWhitelist=budget.whitelist(),
        consumedTurn=True,
        deterministic_decisions=decisions,
    )


# ----- destroy --------------------------------------------------------------


@_build_reducer
def reduce_destroy(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``destroy`` — irreversibly remove an artifact from the world.

    This is one of the **four irreversible interventions** called
    out in decision 1 (destroy / conceal / give / promise).  Once
    applied, the artifact is gone from ``artifactState`` and the
    reducer does not plant a compensating seed — destruction is
    final.

    Effects
    -------
    * Removes every evidence artifact from the canonical state.
    * Negative trust + intimacy.
    * Raised ``unresolvedConflict`` (the other party will notice).
    * Burns one ``destroy`` budget unit and one turn.
    """

    decisions: list[str] = ["destroy: irreversible artifact removal"]
    actor = action.get("actorId")
    target = action.get("targetId") or actor
    evidence_ids = action.get("evidenceIds") or []
    artifact_updates: list[ArtifactUpdate] = [
        ArtifactUpdate(artifactId=eid, operation=ArtifactOperation.DESTROY, reasonCode="destroy")
        for eid in evidence_ids
    ]
    disclosure = float(action.get("disclosureLevel", 0.5))
    fwd, back = _actor_delta(actor, target, ActionType.DESTROY.value, disclosure)
    budget.consume(ActionType.DESTROY.value)
    decisions.append(f"destroyed {len(evidence_ids)} artifact(s)")
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=[fwd] + ([back] if back else []),
        artifactUpdates=artifact_updates,
        beliefUpdates=[],
        causalSeeds=[],
        actionWhitelist=budget.whitelist(),
        consumedTurn=True,
        deterministic_decisions=decisions,
    )


# ----- promise --------------------------------------------------------------


@_build_reducer
def reduce_promise(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``promise`` — make a commitment to the target.

    Effects
    -------
    * Strong positive trust.
    * Plants a *causal seed* (a promise is a payload that may
      echo into future scenes — see decision 3).
    * Burns one ``promise`` budget unit and one turn.
    """

    decisions: list[str] = ["promise: planting cross-era causal seed"]
    actor = action.get("actorId")
    target = action.get("targetId") or actor
    scene_id = snapshot.canonicalState.currentSceneId
    era = snapshot.canonicalState.era
    # Build a deterministic seed id from the action payload.
    raw = (
        f"seed_promise|{actor}|{target}|{scene_id}|"
        f"{action.get('clientActionId') or ''}|"
        f"{action.get('utterance') or ''}"
    )
    seed_id = "seed_promise_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    seed = CausalSeed(
        id=seed_id,
        source_scene=scene_id,
        source_event=action.get("clientActionId") or str(uuid.uuid4()),
        description=(action.get("utterance") or "a promise")[:500],
        trigger_condition=__import__(
            "server.engine.causal_seed", fromlist=["TriggerCondition"]
        ).TriggerCondition(
            type="character_present",
            predicate=f"character {target} in scene",
            minEcho=0.0,
        ),
        target_scenes=[scene_id],  # contracts may broaden this; default to current
        echo_intensity=clamp_unit(0.6),
        is_secret=bool(action.get("isDeceptive", False)),
    )
    decisions.append(f"planted causal seed {seed_id!r}")
    disclosure = float(action.get("disclosureLevel", 0.5))
    fwd, back = _actor_delta(actor, target, ActionType.PROMISE.value, disclosure)
    budget.consume(ActionType.PROMISE.value)
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=[fwd] + ([back] if back else []),
        artifactUpdates=[],
        beliefUpdates=[],
        causalSeeds=[seed],
        actionWhitelist=budget.whitelist(),
        consumedTurn=True,
        deterministic_decisions=decisions,
    )


# ----- wait -----------------------------------------------------------------


@_build_reducer
def reduce_wait(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``wait`` — do nothing for a beat.

    Effects
    -------
    * Zero deltas by default; this is the only "passive" reducer.
    * The Resolver can still apply ambient NPC / Director deltas
      in the same turn.
    * Burns one ``wait`` budget unit and one turn.
    """

    decisions: list[str] = ["wait: no direct delta; ambient effects only"]
    budget.consume(ActionType.WAIT.value)
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=[],
        artifactUpdates=[],
        beliefUpdates=[],
        causalSeeds=[],
        actionWhitelist=budget.whitelist(),
        consumedTurn=True,
        deterministic_decisions=decisions,
    )


# ----- leave ----------------------------------------------------------------


@_build_reducer
def reduce_leave(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``leave`` — exit the active scene (or the room).

    Effects
    -------
    * Strong negative intimacy (distance).
    * Raised ``unresolvedConflict``.
    * The Resolver may transition to the next scene (per the
      Director's contract decision).
    * Burns one ``leave`` budget unit and one turn.
    """

    decisions: list[str] = ["leave: exiting current spatial context"]
    actor = action.get("actorId")
    target = action.get("targetId") or actor
    disclosure = float(action.get("disclosureLevel", 0.5))
    fwd, back = _actor_delta(actor, target, ActionType.LEAVE.value, disclosure)
    budget.consume(ActionType.LEAVE.value)
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=[fwd] + ([back] if back else []),
        artifactUpdates=[],
        beliefUpdates=[],
        causalSeeds=[],
        actionWhitelist=budget.whitelist(),
        consumedTurn=True,
        deterministic_decisions=decisions,
    )


# ----- silence --------------------------------------------------------------


@_build_reducer
def reduce_silence(
    action: dict, snapshot: WorldSnapshot, budget: SceneBudget
) -> ReducerOutcome:
    """``silence`` — withhold a response.

    Effects
    -------
    * Mild negative trust + intimacy (withholding).
    * Burns one ``silence`` budget unit and one turn.
    """

    decisions: list[str] = ["silence: withholding response"]
    actor = action.get("actorId")
    target = action.get("targetId") or actor
    disclosure = float(action.get("disclosureLevel", 0.5))
    fwd, back = _actor_delta(actor, target, ActionType.SILENCE.value, disclosure)
    budget.consume(ActionType.SILENCE.value)
    return ReducerOutcome(
        accepted=True,
        relationshipDeltas=[fwd] + ([back] if back else []),
        artifactUpdates=[],
        beliefUpdates=[],
        causalSeeds=[],
        actionWhitelist=budget.whitelist(),
        consumedTurn=True,
        deterministic_decisions=decisions,
    )


# ---------------------------------------------------------------------------
# Dispatch table + main entry
# ---------------------------------------------------------------------------


REDUCERS: dict[str, Callable[[dict, WorldSnapshot, SceneBudget], ReducerOutcome]] = {
    ActionType.INVESTIGATE.value: reduce_investigate,
    ActionType.REVEAL.value: reduce_reveal,
    ActionType.CONCEAL.value: reduce_conceal,
    ActionType.QUESTION.value: reduce_question,
    ActionType.CONFRONT.value: reduce_confront,
    ActionType.COMFORT.value: reduce_comfort,
    ActionType.GIVE.value: reduce_give,
    ActionType.DESTROY.value: reduce_destroy,
    ActionType.PROMISE.value: reduce_promise,
    ActionType.WAIT.value: reduce_wait,
    ActionType.LEAVE.value: reduce_leave,
    ActionType.SILENCE.value: reduce_silence,
}


def reduce(
    action: dict,
    snapshot: WorldSnapshot,
    budget: SceneBudget,
    *,
    scene_whitelist: set[str] | None = None,
    cast: list[str] | None = None,
) -> ReducerOutcome:
    """The public state-machine entry point.

    Parameters
    ----------
    action : dict
        A PlayerAction-shaped dict (validated against the schema
        upstream; the state machine trusts the field set).
    snapshot : WorldSnapshot
        The current canonical world state.  **Not mutated.**
    budget : SceneBudget
        The active scene's per-action and per-turn budget.
    scene_whitelist : set[str], optional
        The set of action types the contract allows.  Defaults to
        all 12 if not supplied (useful for tests).
    cast : list[str], optional
        The list of character IDs on stage.  Used for target
        validation.  Defaults to None (no cast enforcement).

    Returns
    -------
    ReducerOutcome
        A *pure* description of the proposed state change.  The
        Resolver is the only component that may apply it.
    """

    whitelist = scene_whitelist if scene_whitelist is not None else set(REDUCERS.keys())
    artifact_ids = {a.artifactId for a in snapshot.artifactState}
    decisions = _validate(
        action=action,
        scene_whitelist=whitelist,
        budget=budget,
        cast=cast,
        artifact_ids_in_state=artifact_ids,
    )
    handler = REDUCERS[action["actionType"]]
    outcome = handler(action, snapshot, budget)
    outcome.deterministic_decisions = decisions + outcome.deterministic_decisions
    return outcome


def apply_reducer_outcome(
    snapshot: WorldSnapshot, outcome: ReducerOutcome
) -> WorldSnapshot:
    """Apply a :class:`ReducerOutcome` to a snapshot, returning a new snapshot.

    This helper exists so that the **deterministic** state machine
    can advance the canonical state without going through the full
    Resolver.  Tests use it to verify the reducers are correct in
    isolation.  The Resolver itself goes through a richer path
    (merging with NPC + Director proposals, building the audit
    trail, etc.).
    """

    if not outcome.accepted:
        return snapshot
    new_rel, _ = apply_relationship_deltas(snapshot.relationshipState, outcome.relationshipDeltas)
    new_art = apply_artifact_updates(snapshot.artifactState, outcome.artifactUpdates)
    # Causal seeds: append to active set
    new_seeds = list(snapshot.causalSeedsActive)
    for s in outcome.causalSeeds:
        new_seeds.append(s.to_dict())
    # Belief updates: applied as a list-of-dict to beliefMatrices.
    # We do the merge here for the deterministic case (no NPC proposals).
    new_matrices = _apply_belief_updates(snapshot.beliefMatrices, outcome.beliefUpdates)
    return (
        snapshot.with_relationship_state(new_rel)
        .with_artifact_state(new_art)
        .with_causal_seeds_active(new_seeds)
        .with_belief_matrices(new_matrices)
    )


def _apply_belief_updates(
    matrices: list[dict[str, Any]], updates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Apply belief deltas to a list of matrix dicts.

    Pure: returns a new list.
    """

    from .belief_matrix import BeliefMatrix, BeliefMatrixStore

    if not updates:
        return [dict(m) for m in matrices]
    store = BeliefMatrixStore.from_list(matrices)
    for u in updates:
        matrix = store.get_or_create(u["characterId"])
        matrix.apply_update(
            subject=u["subject"],
            new_state=u["newState"],
            confidence=u["confidence"],
            evidenceMemoryId=u.get("evidenceMemoryId"),
            sequence=0,
        )
        store.upsert(matrix)
    return store.to_list()


__all__ = [
    "ReducerOutcome",
    "SceneBudget",
    "REDUCERS",
    "reduce",
    "apply_reducer_outcome",
]
