"""The Resolver — the single canonical-state writer.

Per the 《崇祯》reference and the engine's write-domain-isolation
rule, **only the Resolver** may mutate canonical state.  It:

1. Accepts a player action + NPC proposal + Director beat.
2. Runs the deterministic state-machine reducer over the player
   action.
3. Merges NPC / Director deltas (after re-validating them).
4. Audits every numeric clamp, every rejected NPC proposal.
5. Produces a :class:`ResolverOutcome` and an updated
   :class:`WorldSnapshot` (the snapshot is returned alongside the
   outcome so the persistence layer can write both atomically).

The Resolver is **the only place** that emits a ResolverOutcome.
It is also the only place that writes the event log
(:class:`engine.event_log.GameEvent`).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable

from .artifact import ArtifactUpdate, apply_artifact_updates
from .belief_matrix import BeliefMatrixStore
from .causal_seed import CausalSeed, CausalSeedStore
from .event_log import GameEvent, EventLog
from .exceptions import (
    ArtifactConflictError,
    DuplicateProposalError,
    ForbiddenRevealError,
    IdempotencyReplayError,
    IllegalTargetError,
    IllegalTransitionError,
    SequenceMismatchError,
    UngroundedMemoryError,
    ValidationError,
)
from .relationship import (
    RelationshipDelta,
    apply_relationship_deltas,
)
from .state_machine import (
    REDUCERS,
    ReducerOutcome,
    SceneBudget,
    apply_reducer_outcome,
    reduce,
)
from .types import SCHEMA_VERSION, ScenePhase, clamp_unit
from .world_snapshot import (
    CanonicalState,
    RecentOutcomeRef,
    WorldSnapshot,
)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class NPCProposal:
    """The minimal proposal shape the Resolver consumes.

    The full NpcProposal (per the JSON schema) is richer; this is
    the projection the Resolver works with.  The Agent layer is
    responsible for the schema validation upstream.
    """

    proposalId: str
    characterId: str
    proposedAction: str
    speechIntent: str
    targetId: str | None = None
    referencedMemoryIds: list[str] = field(default_factory=list)
    beliefUpdatesRequested: list[dict[str, Any]] = field(default_factory=list)
    emotionalTransition: dict[str, Any] | None = None
    reasonCodes: list[str] = field(default_factory=list)
    confidence: float = 0.5
    expectedContradictions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DirectorBeatInput:
    """The Director's beat selection."""

    proposalId: str
    proposedBeat: str
    allowedByContract: bool
    forbiddenRevealsChecked: list[str]
    transitionToNext: bool
    suggestedTargetSceneId: str | None = None
    reasoning: str = ""
    pacingPressure: float = 0.0
    expectedTensionDelta: float = 0.0
    involvedCharacterIds: list[str] = field(default_factory=list)
    firedCausalSeeds: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NarrativeContract:
    """The subset of a NarrativeContract the Resolver needs."""

    sceneId: str
    allowed_beats: list[dict[str, Any]]
    forbidden_reveals: list[dict[str, str]]
    legal_endings: list[dict[str, Any]]
    max_turns: int
    total_action_budget: int
    causal_seeds: list[str] = field(default_factory=list)

    def is_beat_allowed(self, beat_id: str) -> bool:
        return any(b.get("beatId") == beat_id for b in self.allowed_beats)

    def is_ending_legal(self, ending_id: str) -> bool:
        return any(e.get("endingId") == ending_id for e in self.legal_endings)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ResolverOutcome:
    """The authoritative outcome of resolving a turn.

    Matches the JSON Schema's resolver_outcome structure; numeric
    fields are clamped at apply-time.
    """

    outcomeId: str
    runId: str
    eventSequence: int
    idempotencyKey: str
    acceptedNpcAction: dict[str, Any]
    nextBeat: dict[str, Any]
    timestamp: str
    triggerPlayerActionId: str | None = None
    triggerDirectorProposalId: str | None = None
    rejectedNpcActions: list[dict[str, Any]] = field(default_factory=list)
    relationshipDelta: list[dict[str, Any]] = field(default_factory=list)
    beliefUpdates: list[dict[str, Any]] = field(default_factory=list)
    artifactUpdates: list[dict[str, Any]] = field(default_factory=list)
    newCausalSeeds: list[str] = field(default_factory=list)
    firedCausalSeeds: list[str] = field(default_factory=list)
    clampedValues: list[dict[str, Any]] = field(default_factory=list)
    auditTrail: dict[str, Any] = field(default_factory=dict)
    schemaVersion: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ResolverOutcome":
        return ResolverOutcome(**data)


# ---------------------------------------------------------------------------
# The Resolver
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Resolver:
    """The canonical-state writer.

    The Resolver holds no persistent state of its own — every call
    takes the current snapshot + event log and returns the new
    pair.  This keeps the type testable and lets the persistence
    layer drive the cadence.
    """

    base_random_seed: int = 0

    def resolve(  # noqa: C901 — complex by necessity
        self,
        *,
        snapshot: WorldSnapshot,
        event_log: EventLog,
        player_action: dict[str, Any] | None,
        npc_proposal: NPCProposal | None,
        director_beat: DirectorBeatInput | None,
        contract: NarrativeContract,
        scene_budget: SceneBudget,
        recall_set: set[str] | None = None,
    ) -> tuple[WorldSnapshot, ResolverOutcome]:
        """Run a full resolve.

        Returns
        -------
        (new_snapshot, outcome)
            The new snapshot is fully self-consistent; the outcome
            is the audit record the persistence layer stores.

        Raises
        ------
        IdempotencyReplayError
            The same idempotency key was already applied.
        SequenceMismatchError
            ``player_action.expectedEventSequence`` is too far
            behind the canonical eventSequence.
        """

        recall = recall_set or set()
        deterministic: list[str] = []

        # ---- 1. Sequence + idempotency gate ------------------------------
        if player_action is not None:
            exp = player_action.get("expectedEventSequence")
            if exp is not None and snapshot.eventSequence - exp > 1:
                raise SequenceMismatchError(
                    f"client sequence {exp} is more than 1 behind canonical {snapshot.eventSequence}"
                )
            # Replay detection: if the same clientActionId was
            # already recorded, this is a duplicate and we
            # short-circuit with the existing event.
            client_aid = player_action.get("clientActionId")
            if client_aid:
                for ev in event_log:
                    if ev.actionPayload.get("clientActionId") == client_aid:
                        raise IdempotencyReplayError(
                            f"clientActionId already applied: {client_aid[:8]}…"
                        )
        # Build the canonical idempotency key
        next_seq = snapshot.eventSequence + 1
        idem = _make_idempotency_key(
            snapshot.runId,
            next_seq,
            (player_action or {}).get("clientActionId") if player_action else None,
            director_beat.proposalId if director_beat else None,
        )
        if event_log.has_idempotency_key(idem):
            raise IdempotencyReplayError(f"idempotency key already seen: {idem[:16]}…")
        deterministic.append(f"idempotency_key={idem[:16]}…")

        # ---- 2. Run the reducer for the player action --------------------
        reducer_outcome: ReducerOutcome | None = None
        if player_action is not None:
            whitelist = set()
            # The whitelist comes from the contract; for the
            # state-machine the active scene's allowed_actions is
            # in the YAML.  We accept either (a) all 12 for unit
            # tests or (b) the per-scene list passed in via the
            # budget's per_action dict.
            whitelist = set(REDUCERS.keys())
            try:
                reducer_outcome = reduce(
                    player_action,
                    snapshot,
                    scene_budget,
                    scene_whitelist=whitelist,
                    cast=director_beat.involvedCharacterIds if director_beat else None,
                )
            except ValidationError as exc:
                # Validation errors are deterministic rejections.
                # A rejected action does NOT advance the
                # canonical state and does NOT write to the
                # event log — the snapshot stays at the current
                # eventSequence.  Only the audit outcome is
                # returned to the caller.
                deterministic.append(f"rejected player action: {exc}")
                outcome = self._build_rejection(
                    snapshot=snapshot,
                    event_sequence=next_seq,
                    idempotency_key=idem,
                    player_action=player_action,
                    reason=str(exc),
                    deterministic=deterministic,
                )
                return snapshot, outcome

        # ---- 3. Validate the Director beat ------------------------------
        if director_beat is not None:
            self._validate_director_beat(director_beat, contract, snapshot, deterministic)

        # ---- 4. Validate the NPC proposal -------------------------------
        rejected_npc: list[dict[str, Any]] = []
        accepted_npc: NPCProposal | None = None
        if npc_proposal is not None:
            try:
                self._validate_npc_proposal(
                    npc_proposal, contract, recall, deterministic
                )
                accepted_npc = npc_proposal
            except (
                ForbiddenRevealError,
                UngroundedMemoryError,
                IllegalTargetError,
                DuplicateProposalError,
            ) as exc:
                deterministic.append(f"rejected NPC proposal {npc_proposal.proposalId[:8]}…: {exc}")
                rejected_npc.append(
                    {
                        "proposalId": npc_proposal.proposalId,
                        "reason": _reason_code(exc),
                        "detail": str(exc),
                    }
                )

        # ---- 5. Apply deltas to a working copy of the snapshot ----------
        working = snapshot
        if reducer_outcome is not None and reducer_outcome.accepted:
            working = apply_reducer_outcome(working, reducer_outcome)
            deterministic.extend(reducer_outcome.deterministic_decisions)

        # NPC relationship deltas (heuristic; the agent declares
        # them in beliefUpdatesRequested; for relationships we
        # accept an optional "relationshipDelta" field in the
        # proposal).
        if accepted_npc is not None:
            rel_deltas = [
                RelationshipDelta(
                    from_=d.get("from", accepted_npc.characterId),
                    to=d.get("to", ""),
                    trust=float(d.get("trust", 0.0)),
                    intimacy=float(d.get("intimacy", 0.0)),
                    unresolvedConflict=float(d.get("unresolvedConflict", 0.0)),
                    respect=float(d.get("respect", 0.0)),
                    fear=float(d.get("fear", 0.0)),
                )
                for d in getattr(accepted_npc, "relationshipDelta", []) or []
            ]
            if rel_deltas:
                new_rel, audit = apply_relationship_deltas(working.relationshipState, rel_deltas)
                working = working.with_relationship_state(new_rel)
                deterministic.append(
                    f"applied {len(rel_deltas)} NPC relationship delta(s)"
                )

            # NPC belief updates
            if accepted_npc.beliefUpdatesRequested:
                store = BeliefMatrixStore.from_list(working.beliefMatrices)
                matrix = store.get_or_create(accepted_npc.characterId)
                for u in accepted_npc.beliefUpdatesRequested:
                    matrix.apply_update(
                        subject=u["subject"],
                        new_state=u["newState"],
                        confidence=float(u.get("confidence", 0.5)),
                        evidenceMemoryId=u.get("evidenceMemoryId"),
                        sequence=next_seq,
                    )
                store.upsert(matrix)
                working = working.with_belief_matrices(store.to_list())

        # ---- 6. Beat transition + causal seed firing --------------------
        next_beat_info: dict[str, Any] = {"sceneId": working.canonicalState.currentSceneId, "beatId": "continue"}
        transition = "continue"
        if director_beat is not None:
            if director_beat.transitionToNext:
                transition = "advance_scene"
                target = director_beat.suggestedTargetSceneId or working.canonicalState.currentSceneId
                next_beat_info = {"sceneId": target, "beatId": director_beat.proposedBeat}
            else:
                next_beat_info = {
                    "sceneId": working.canonicalState.currentSceneId,
                    "beatId": director_beat.proposedBeat,
                }
            # Bump director state
            new_director = working.directorState
            fired = list(new_director.firedBeats)
            if director_beat.proposedBeat not in fired:
                fired.append(director_beat.proposedBeat)
            working = working.with_director_state(
                type(new_director)(
                    currentBeatId=director_beat.proposedBeat,
                    elapsedTurnsInScene=new_director.elapsedTurnsInScene + (1 if reducer_outcome and reducer_outcome.consumedTurn else 0),
                    actionsSpentInScene=new_director.actionsSpentInScene + 1,
                    firedBeats=fired,
                    hitAnchors=list(new_director.hitAnchors),
                    forbiddenRevealsCheckedAt=list(new_director.forbiddenRevealsCheckedAt) + [next_seq],
                )
            )

        # Fire any causal seeds the Director asked for
        fired_seeds: list[str] = []
        if director_beat is not None and director_beat.firedCausalSeeds:
            store = CausalSeedStore.from_list(working.causalSeedsActive)
            for sid in director_beat.firedCausalSeeds:
                seed = store.get(sid)
                if seed is None:
                    continue
                store.fire(sid, at_sequence=next_seq, in_scene_id=working.canonicalState.currentSceneId)
                fired_seeds.append(sid)
            working = working.with_causal_seeds_active([s.to_dict() for s in store.active()])

        # Also fire any seeds whose trigger matches the current state.
        # The Resolver is the only component allowed to do this.
        auto_fired = self._auto_fire_seeds(working, recall, next_seq, deterministic)
        for s in auto_fired:
            if s not in fired_seeds:
                fired_seeds.append(s)

        # The Resolver alone decides when a whitelisted scene ending is met.
        # Planted seeds remain in the snapshot; fired seeds may have been
        # retired, so include both this turn and the append-only event log.
        available_seed_ids = {
            str(seed.get("id"))
            for seed in working.causalSeedsActive
            if isinstance(seed, dict) and seed.get("id")
        }
        available_seed_ids.update(fired_seeds)
        available_seed_ids.update(_historical_fired_seed_ids(event_log))
        legal_ending_id = _match_legal_ending(contract, available_seed_ids)
        if legal_ending_id is not None:
            working = working.with_canonical_state(
                phase=ScenePhase.ENDED.value,
                endingId=legal_ending_id,
            )
            next_beat_info = {
                "sceneId": working.canonicalState.currentSceneId,
                "beatId": f"ending:{legal_ending_id}",
                "legalEndingId": legal_ending_id,
            }
            transition = "end_scene"
            deterministic.append(f"legal ending matched: {legal_ending_id!r}")

        # ---- 7. Bump event sequence + compute checksum -----------------
        working = working.with_event_sequence(next_seq)
        working = working.with_timestamp(_now_iso())
        checksum = working.compute_checksum()
        working = working.with_checksum(checksum)

        # ---- 8. Build the outcome --------------------------------------
        accepted_npc_action_dict: dict[str, Any]
        if accepted_npc is not None:
            accepted_npc_action_dict = {
                "proposalId": accepted_npc.proposalId,
                "characterId": accepted_npc.characterId,
                "proposedAction": accepted_npc.proposedAction,
                "speechIntent": accepted_npc.speechIntent,
                "resolvedText": "",  # populated by the Agent layer
            }
        else:
            accepted_npc_action_dict = {
                "proposalId": "00000000-0000-0000-0000-000000000000",
                "characterId": "",
                "proposedAction": "silence",
                "speechIntent": "remain_silent",
                "resolvedText": "",
            }

        outcome = ResolverOutcome(
            outcomeId=str(uuid.uuid4()),
            runId=snapshot.runId,
            eventSequence=next_seq,
            idempotencyKey=idem,
            acceptedNpcAction=accepted_npc_action_dict,
            nextBeat=next_beat_info,
            timestamp=working.timestamp,
            triggerPlayerActionId=(player_action or {}).get("clientActionId") if player_action else None,
            triggerDirectorProposalId=director_beat.proposalId if director_beat else None,
            rejectedNpcActions=rejected_npc,
            relationshipDelta=[d.to_json_dict() for d in (reducer_outcome.relationshipDeltas if reducer_outcome else [])],
            beliefUpdates=reducer_outcome.beliefUpdates if reducer_outcome else [],
            artifactUpdates=[u.to_json_dict() for u in (reducer_outcome.artifactUpdates if reducer_outcome else [])],
            newCausalSeeds=[s.id for s in (reducer_outcome.causalSeeds if reducer_outcome else [])],
            firedCausalSeeds=fired_seeds,
            clampedValues=_merge_clamp_audits(reducer_outcome, working),
            auditTrail={
                "llmCalls": [],  # populated by the Agent layer
                "deterministicDecisions": deterministic,
            },
        )
        # The nextBeat.transition field
        outcome.nextBeat["transition"] = transition

        # ---- 9. Persist to event log -----------------------------------
        new_snapshot = self._record_outcome(
            working, outcome, event_log, player_action, npc_proposal, director_beat
        )
        return new_snapshot, outcome

    # ----- helpers --------------------------------------------------------

    def _validate_director_beat(
        self,
        beat: DirectorBeatInput,
        contract: NarrativeContract,
        snapshot: WorldSnapshot,
        deterministic: list[str],
    ) -> None:
        if not beat.allowedByContract:
            deterministic.append("rejected director beat: allowedByContract=false")
            raise ValidationError("Director beat marked allowedByContract=false")
        if not contract.is_beat_allowed(beat.proposedBeat):
            deterministic.append(
                f"rejected director beat: {beat.proposedBeat!r} not in allowed_beats"
            )
            raise IllegalTransitionError(
                f"beat {beat.proposedBeat!r} not in contract.allowed_beats"
            )
        # forbiddenRevealsChecked must equal contract.forbidden_reveals (length match)
        if len(beat.forbiddenRevealsChecked) != len(contract.forbidden_reveals):
            deterministic.append(
                f"rejected director beat: forbiddenRevealsChecked length "
                f"{len(beat.forbiddenRevealsChecked)} != contract {len(contract.forbidden_reveals)}"
            )
            raise ValidationError(
                "forbiddenRevealsChecked length must match contract.forbidden_reveals"
            )
        if beat.transitionToNext and not beat.suggestedTargetSceneId:
            raise ValidationError(
                "transitionToNext=true requires suggestedTargetSceneId"
            )
        deterministic.append(f"director beat accepted: {beat.proposedBeat!r}")

    def _validate_npc_proposal(
        self,
        proposal: NPCProposal,
        contract: NarrativeContract,
        recall: set[str],
        deterministic: list[str],
    ) -> None:
        if proposal.proposedAction not in REDUCERS:
            raise ValidationError(f"NPC proposedAction not in 12-type vocab: {proposal.proposedAction!r}")
        # The proposal must reference at least one memory to ground
        # reveal_truth / conceal_truth
        if proposal.speechIntent in {"reveal_truth", "conceal_truth"}:
            if not proposal.referencedMemoryIds:
                raise UngroundedMemoryError(
                    f"{proposal.speechIntent!r} requires referencedMemoryIds"
                )
        # All referenced memories must be in the recall set
        ungrounded = [m for m in proposal.referencedMemoryIds if m not in recall]
        if ungrounded:
            raise UngroundedMemoryError(
                f"referenced memories not in recall set: {ungrounded}"
            )
        # Forbidden-reveal check: the proposal's beliefUpdatesRequested
        # must not surface a fact on the forbidden_reveals list.
        forbidden_keys = {fr.get("revealKey", "") for fr in contract.forbidden_reveals}
        for u in proposal.beliefUpdatesRequested:
            if u.get("subject", "") in forbidden_keys:
                raise ForbiddenRevealError(
                    f"proposal would reveal forbidden fact {u['subject']!r}"
                )
        # target present
        if proposal.targetId and proposal.targetId == "":
            raise IllegalTargetError("targetId is empty string")
        deterministic.append(f"npc proposal accepted: {proposal.proposalId[:8]}…")

    def _auto_fire_seeds(
        self,
        snapshot: WorldSnapshot,
        recall: set[str],
        next_seq: int,
        deterministic: list[str],
    ) -> list[str]:
        """Fire any causal seeds whose trigger matches the current snapshot."""

        fired: list[str] = []
        store = CausalSeedStore.from_list(snapshot.causalSeedsActive)
        current_scene = snapshot.canonicalState.currentSceneId
        current_era = snapshot.canonicalState.era
        artifact_ids = {a.artifactId for a in snapshot.artifactState}
        for seed in store.list_all():
            if not seed.is_dormant:
                continue
            if seed.matches(
                current_scene_id=current_scene,
                current_era=current_era,
                character_present=set(seed.linkedCharacterIds),
                artifact_present=artifact_ids,
                memories_recalled=recall,
            ):
                store.fire(seed.id, at_sequence=next_seq, in_scene_id=current_scene)
                fired.append(seed.id)
                deterministic.append(f"auto-fired causal seed: {seed.id!r}")
        # Persist the (possibly mutated) store back
        return fired

    def _build_rejection(
        self,
        *,
        snapshot: WorldSnapshot,
        event_sequence: int,
        idempotency_key: str,
        player_action: dict[str, Any],
        reason: str,
        deterministic: list[str],
    ) -> ResolverOutcome:
        """Build a ResolverOutcome for a rejected player action."""

        return ResolverOutcome(
            outcomeId=str(uuid.uuid4()),
            runId=snapshot.runId,
            eventSequence=event_sequence,
            idempotencyKey=idempotency_key,
            acceptedNpcAction={
                "proposalId": "00000000-0000-0000-0000-000000000000",
                "characterId": "",
                "proposedAction": "silence",
                "speechIntent": "remain_silent",
                "resolvedText": "",
            },
            nextBeat={
                "sceneId": snapshot.canonicalState.currentSceneId,
                "beatId": "rejected_action",
                "transition": "continue",
            },
            timestamp=_now_iso(),
            triggerPlayerActionId=player_action.get("clientActionId"),
            triggerDirectorProposalId=None,
            rejectedNpcActions=[],
            relationshipDelta=[],
            beliefUpdates=[],
            artifactUpdates=[],
            newCausalSeeds=[],
            firedCausalSeeds=[],
            clampedValues=[],
            auditTrail={
                "llmCalls": [],
                "deterministicDecisions": deterministic + [f"player action rejected: {reason}"],
            },
        )

    def _record_outcome(
        self,
        snapshot: WorldSnapshot,
        outcome: ResolverOutcome,
        event_log: EventLog,
        player_action: dict[str, Any] | None,
        npc_proposal: NPCProposal | None,
        director_beat: DirectorBeatInput | None,
    ) -> WorldSnapshot:
        """Append a :class:`GameEvent` to the log; update recentOutcomes."""

        action_type = (
            (player_action or {}).get("actionType", "no_player_action")
            if player_action
            else "no_player_action"
        )
        actor_id = (
            (player_action or {}).get("actorId", "")
            if player_action
            else (
                npc_proposal.characterId
                if npc_proposal
                else (director_beat.proposalId if director_beat else "system")
            )
        )
        # Build the validatedDelta: the new sequence + checksum.
        event = GameEvent(
            sequence=outcome.eventSequence,
            sceneId=snapshot.canonicalState.currentSceneId,
            actorId=actor_id,
            actionType=action_type,
            actionPayload={
                "clientActionId": (player_action or {}).get("clientActionId") if player_action else None,
                "npcProposalId": npc_proposal.proposalId if npc_proposal else None,
                "directorProposalId": director_beat.proposalId if director_beat else None,
            },
            validatedDelta={
                "checksum": snapshot.checksum,
                "firedCausalSeeds": list(outcome.firedCausalSeeds),
            },
            causalSeed=outcome.firedCausalSeeds[0] if outcome.firedCausalSeeds else None,
            randomSeed=self.base_random_seed,
            idempotencyKey=outcome.idempotencyKey,
            runId=snapshot.runId,
            outcomeId=outcome.outcomeId,
        )
        event_log.append(event)
        # Roll recentOutcomes (ring buffer, max 64)
        new_recent = [RecentOutcomeRef(
            outcomeId=outcome.outcomeId,
            eventSequence=outcome.eventSequence,
            timestamp=outcome.timestamp,
        )]
        for o in snapshot.recentOutcomes[:63]:
            new_recent.append(o)
        return snapshot.with_recent_outcomes(new_recent)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_idempotency_key(
    runId: str,
    event_sequence: int,
    player_action_id: str | None,
    director_proposal_id: str | None,
) -> str:
    raw = f"{runId}|{event_sequence}|{player_action_id or ''}|{director_proposal_id or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _reason_code(exc: Exception) -> str:
    from .exceptions import (
        DuplicateProposalError,
        ForbiddenRevealError,
        IllegalTargetError,
        UngroundedMemoryError,
    )
    if isinstance(exc, ForbiddenRevealError):
        return "forbidden_reveal"
    if isinstance(exc, UngroundedMemoryError):
        return "ungrounded_memory"
    if isinstance(exc, IllegalTargetError):
        return "illegal_target"
    if isinstance(exc, DuplicateProposalError):
        return "duplicate_proposal"
    return "violates_contract"


def _historical_fired_seed_ids(event_log: EventLog) -> set[str]:
    """Collect causal seeds retired by earlier authoritative turns."""

    fired: set[str] = set()
    for event in event_log:
        if event.causalSeed:
            fired.add(str(event.causalSeed))
        values = event.validatedDelta.get("firedCausalSeeds", [])
        if isinstance(values, list):
            fired.update(str(value) for value in values if value)
    return fired


def _match_legal_ending(
    contract: NarrativeContract, available_seed_ids: set[str]
) -> str | None:
    """Return the first declared ending whose non-empty seed conditions match."""

    for ending in contract.legal_endings:
        ending_id = ending.get("endingId")
        conditions = ending.get("conditions", []) or []
        if not ending_id or not isinstance(conditions, list) or not conditions:
            continue
        required: set[str] = set()
        for condition in conditions:
            if isinstance(condition, str) and condition:
                required.add(condition)
            elif isinstance(condition, dict):
                seed_id = (
                    condition.get("seedId")
                    or condition.get("seed_id")
                    or condition.get("id")
                )
                if seed_id:
                    required.add(str(seed_id))
        if required and required.issubset(available_seed_ids):
            return str(ending_id)
    return None

def _merge_clamp_audits(
    reducer_outcome: ReducerOutcome | None,
    snapshot: WorldSnapshot,
) -> list[dict[str, Any]]:
    """Merge reducer's clamp audit with the snapshot's validatedDelta bookkeeping."""

    audits = list(reducer_outcome.clampedValues) if reducer_outcome else []
    return audits


__all__ = [
    "NPCProposal",
    "DirectorBeatInput",
    "NarrativeContract",
    "ResolverOutcome",
    "Resolver",
]
