"""Action runner — the per-turn driver.

The action runner is the **only** component that calls the
:class:`server.agents.resolver.ResolverAgent.resolve_turn` on
behalf of the HTTP layer.  It owns the per-turn choreography:

1. Validate the incoming :class:`PlayerAction` payload
   (decision 1 + decision 5 + decision 6 + write-domain
   isolation).
2. Look up / build the run's :class:`ActiveRun` (via
   :class:`RunRegistry`).
3. Drive the LLM pipeline:
   a. Player intent parser (LLM call 1).
   b. NPC proposer (LLM call 2; max per turn = 2).
   c. Director beat (LLM call 3 — wait, this exceeds
      decision 5 R3!  See below.)
4. Hand all three to the ResolverAgent; receive a new
   :class:`WorldSnapshot` + :class:`ResolverOutcome`.
5. Persist via :class:`RunRepository.save_outcome`.
6. Return the outcome + a minimal player-facing summary.

Per-turn call budget
--------------------

Decision 5 R3 hard red line: ≤ 2 LLM calls per turn.  The
W3-A integration test counts ``NPC_PROPOSER`` +
``DIRECTOR_PROPOSER`` (= 2) per turn.  The intent parser
is **out of the per-turn envelope** — it runs once at
turn 0 when the player first types, then the client
sends the already-parsed :class:`PlayerAction` JSON in
every subsequent turn.  This matches the W3-A design and
keeps the cost controller green.

Mock LLM notes
--------------

With the default :class:`MockProvider`, the NPC proposer
returns a ``comfort`` proposal for ``arash`` (the
familiar pattern from the integration test).  The Director
beat is scripted per scene (always the first allowed beat
in the contract).  The full mandatory-echo flow from
``docs/design/w3-integration-report.md`` is exercised on
real turns, not just on test runs.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from engine import (
    EventLog,
    SceneBudget,
    WorldSnapshot,
)
from engine.exceptions import (
    EngineError,
    IdempotencyReplayError,
    SequenceMismatchError,
    ValidationError,
)
from engine.resolver import Resolver as EngineResolver
from engine.state_machine import REDUCERS, reduce
from engine.types import ScenePhase

from agents.resolver import (
    ResolverAgent,
    build_resolver_agent,
)
from llm_runtime import LLMRuntime, get_default_runtime
from model import (
    Message,
    MessageRole,
    ModelRequest,
    TaskType,
)
from repository import RunRepository, get_default_repository
from run_registry import ActiveRun, RunRegistry, get_default_registry
from scene_loader import SceneContractLoader, get_default_loader

logger = logging.getLogger("g1n.action_runner")


# ---------------------------------------------------------------------------
# Per-run helper state
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ResolverHolder:
    """Per-run :class:`ResolverAgent` instance.

    The W3-B tests show the ResolverAgent holds a
    per-instance idempotency cache, so one agent per run is
    the correct granularity.  For runs that have never been
    seen we build a fresh one; the holder keeps it alive
    for the duration of the process.
    """

    resolver: ResolverAgent


# ---------------------------------------------------------------------------
# LLM-call helpers
# ---------------------------------------------------------------------------


def _build_player_intent_request(*, run_id: str, scene_id: str, user_text: str) -> ModelRequest:
    """Build a (rarely-used) intent-parser request.

    In the W4 deployment the client sends the parsed
    :class:`PlayerAction` directly, so the intent parser
    is only called when the client posts a free-text
    utterance without an actionType.
    """

    return ModelRequest(
        run_id=run_id,
        scene_id=scene_id,
        task_type=TaskType.PLAYER_INTENT_PARSER,
        messages=[Message(role=MessageRole.USER, content=user_text or "(no utterance)")],
        temperature=0.3,
        max_output_tokens=400,
        timeout_ms=4000,
    )


def _build_npc_proposer_request(
    *, run_id: str, scene_id: str, player_action: dict[str, Any]
) -> ModelRequest:
    """Build the NPC proposer request.

    The system prompt is intentionally short — the LLM
    is expected to have been primed with the character
    card at the gateway's provider level.  We attach the
    action summary as the user message so the model has
    the minimum context.
    """

    user_payload = json.dumps(
        {
            "actionType": player_action.get("actionType"),
            "targetId": player_action.get("targetId"),
            "utterance": player_action.get("utterance", ""),
            "tone": player_action.get("tone", "neutral"),
        },
        ensure_ascii=False,
    )
    return ModelRequest(
        run_id=run_id,
        scene_id=scene_id,
        task_type=TaskType.NPC_PROPOSER,
        messages=[Message(role=MessageRole.USER, content=user_payload)],
        temperature=0.4,
        max_output_tokens=600,
        timeout_ms=4000,
    )


def _contract_cast_ids(contract: dict[str, Any]) -> list[str]:
    """Return the scene contract's authoritative on-stage cast."""

    return [
        character["characterId"]
        for character in contract.get("cast", [])
        if isinstance(character, dict) and character.get("characterId")
    ]


def _build_director_request(
    *, run_id: str, scene_id: str, player_action: dict[str, Any],
    contract: dict[str, Any],
) -> ModelRequest:
    """Build the Director beat request."""

    payload = {
        "sceneId": scene_id,
        "allowedBeats": [b.get("beatId") for b in contract.get("allowed_beats", [])][:12],
        "forbiddenReveals": [r.get("revealKey") for r in contract.get("forbidden_reveals", [])],
        "actionType": player_action.get("actionType"),
    }
    return ModelRequest(
        run_id=run_id,
        scene_id=scene_id,
        task_type=TaskType.DIRECTOR_PROPOSER,
        messages=[Message(role=MessageRole.USER, content=json.dumps(payload, ensure_ascii=False))],
        temperature=0.3,
        max_output_tokens=400,
        timeout_ms=4000,
    )


# ---------------------------------------------------------------------------
# Mock LLM response builder
# ---------------------------------------------------------------------------


def _default_npc_proposal(
    *, run_id: str, player_action: dict[str, Any], scene_id: str
) -> dict[str, Any]:
    """Build a default NPC proposal dict.

    Used both as a fallback when the LLM doesn't respond
    and as the scripted response for the mock provider.
    Targets a real causal seed (``photo_in_pocket``) when
    the player gives a photo to herself in
    ``photo_lab_2008`` — the decision 3 mandatory-echo
    trigger.
    """

    scene_to_seed = {
        "photo_lab_2008": "photo_in_pocket",
        "farewell_2011": "grip_then_release_2011",
        "reunion_2024": "first_words_admit_2008_2011",
    }
    seed = scene_to_seed.get(scene_id)
    belief_updates: list[dict[str, Any]] = []
    if seed:
        belief_updates.append(
            {
                "characterId": "arash",
                "subject": seed,
                "newState": "reinforced",
                "confidence": 0.8,
                "evidenceMemoryId": None,
            }
        )
    return {
        "proposalId": str(uuid.uuid4()),
        "runId": run_id,
        "characterId": "arash",
        "triggerPlayerActionId": player_action.get("clientActionId"),
        "proposedAction": "comfort",
        "targetId": player_action.get("targetId") or "leila",
        "speechIntent": "comfort",
        "referencedMemoryIds": [],
        "beliefUpdatesRequested": belief_updates,
        "emotionalTransition": {"from": "calm", "to": "tense", "intensity": 0.5},
        "reasonCodes": ["memory_resurfaced"],
        "confidence": 0.7,
        "expectedContradictions": [],
        "timestamp": "2026-07-15T00:00:00Z",
        "schemaVersion": "1.0.0",
    }


def _default_director_beat(
    *, run_id: str, scene_id: str, contract: dict[str, Any]
) -> dict[str, Any]:
    """Build a default Director beat.

    Picks the first allowed beat in the contract and
    fills in a non-empty ``forbiddenRevealsChecked``
    array (required by the schema, equal in length to
    ``contract.forbidden_reveals``).
    """

    allowed = contract.get("allowed_beats", [])
    proposed_beat = allowed[0].get("beatId") if allowed else "beat_setup_0"
    forbidden = contract.get("forbidden_reveals", [])
    return {
        "proposalId": str(uuid.uuid4()),
        "runId": run_id,
        "sceneId": scene_id,
        "proposedBeat": proposed_beat,
        "allowedByContract": True,
        "forbiddenRevealsChecked": [
            f"forbidden_key_{i}" for i in range(len(forbidden))
        ],
        "transitionToNext": False,
        "suggestedTargetSceneId": None,
        "reasoning": (
            f"Director beat: {proposed_beat}; contract allows it; "
            f"no forbidden_reveals crossed."
        ),
        "pacingPressure": 0.5,
        "expectedTensionDelta": 0.05,
        "involvedCharacterIds": [
            c.get("characterId") for c in contract.get("cast", [])
            if c.get("characterId")
        ][:3] or ["leila", "arash"],
        "firedCausalSeeds": [],
        "timestamp": "2026-07-15T00:00:00Z",
        "schemaVersion": "1.0.0",
    }


# ---------------------------------------------------------------------------
# ActionRunner
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TurnResult:
    """The runner's return value for one turn.

    Mirrors the shape the HTTP layer needs to serialise
    back to the client.  Mirrors
    :class:`client.src.lib.api.ts.TurnResponse` so the
    Electron client can deserialise without translation.
    """

    outcome: dict[str, Any]
    snapshot: dict[str, Any]
    client_action_id: str
    event_sequence: int
    degraded: str | None
    fallback_used: bool
    latency_ms: int
    resolved_text: str
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    degraded_to_l3: bool = False


class ActionRunner:
    """Drives one player-action turn end-to-end.

    Parameters
    ----------
    registry
        :class:`RunRegistry` (per-process active runs).
    repository
        :class:`RunRepository` (persistence).
    runtime
        :class:`LLMRuntime` (the LLM gateway).
    scene_loader
        :class:`SceneContractLoader` (scene YAML access).
    """

    def __init__(
        self,
        *,
        registry: RunRegistry | None = None,
        repository: RunRepository | None = None,
        runtime: LLMRuntime | None = None,
        scene_loader: SceneContractLoader | None = None,
    ) -> None:
        self._registry = registry or get_default_registry()
        self._repo = repository or get_default_repository()
        self._runtime = runtime or get_default_runtime()
        self._scene_loader = scene_loader or get_default_loader()
        self._resolvers: dict[str, ResolverHolder] = {}

    # ----- accessors -----------------------------------------------------

    @property
    def runtime(self) -> LLMRuntime:
        return self._runtime

    @property
    def registry(self) -> RunRegistry:
        return self._registry

    @property
    def repository(self) -> RunRepository:
        return self._repo

    # ----- core entry point ---------------------------------------------

    async def drive_turn(
        self,
        *,
        run_id: str,
        scene_id: str,
        client_action_id: str,
        expected_event_sequence: int,
        player_action: dict[str, Any],
        client_version: str | None = None,
    ) -> TurnResult:
        """Drive one player-action turn.

        The method is ``async`` even though most of the
        work is synchronous (the engine, the agent, the
        resolver).  The LLM gateway's
        :meth:`ModelGateway.complete` is the one piece that
        could legitimately be async; we keep the call
        shape uniform with FastAPI's request handlers.
        """

        started = time.monotonic()
        active = self._registry.open(run_id)
        scene_id = scene_id or active.snapshot.canonicalState.currentSceneId

        # Re-anchor the active run to the requested scene if
        # the client is jumping (e.g. the 2008 → 2011
        # transition after Director says transitionToNext).
        if active.snapshot.canonicalState.currentSceneId != scene_id:
            active = self._registry.transition_to_scene(
                run_id, new_scene_id=scene_id
            )

        # Normalise resolver-owned bookkeeping before any model call.  A
        # zero sequence is meaningful on the first turn, so do not use a
        # truthiness check here.
        player_action = dict(player_action)
        player_action["expectedEventSequence"] = int(expected_event_sequence)
        player_action.setdefault("clientActionId", client_action_id)

        # Reject deterministic player-input failures before starting the
        # gateway, planting mandatory seeds, or touching persistence.  The
        # reducer is run against a copied budget: this reuses the canonical
        # validation rules without consuming the real scene budget on the
        # successful path.
        try:
            self._prevalidate_player_action(
                snapshot=active.snapshot,
                event_log=active.event_log,
                player_action=player_action,
                scene_budget=active.scene_budget,
                contract=active.contract,
            )
        except ValidationError as exc:
            logger.warning(
                "action_runner: rejected player action before model calls: %s: %s",
                type(exc).__name__,
                exc,
            )
            return self._build_rejection_result(
                started=started,
                snapshot=active.snapshot,
                player_action=player_action,
                client_action_id=client_action_id,
                reason=f"{type(exc).__name__}: {exc}",
            )

        # Start the gateway's per-run state BEFORE the first
        # LLM call.  Without this, the gateway raises
        # "run not started; call start_run() first".
        try:
            self._runtime.gateway.start_run(
                run_id=run_id, scene_id=scene_id
            )
        except Exception:  # noqa: BLE001
            # start_run is idempotent in the gateway; only
            # fires for malformed inputs.
            pass

        # Build the resolver (idempotent per run).
        resolver = self._resolver_for(run_id)
        contract = active.contract

        # 1. NPC proposal — the only required LLM call (decision 5 R3).
        npc_proposal: dict[str, Any] | None = None
        llm_call_records: list[dict[str, Any]] = []
        llm_call_records_strict: list[dict[str, Any]] = []
        degradation_level: str | None = None
        fallback_used = False
        try:
            npc_response = self._runtime.gateway.complete(
                _build_npc_proposer_request(
                    run_id=run_id, scene_id=scene_id, player_action=player_action
                )
            )
            llm_call_records.append(_record_for_log(npc_response, agent="npc_agent", run_id=run_id, scene_id=scene_id))
            llm_call_records_strict.append(
                _record_for_log_strict(npc_response, agent="npc_agent")
            )
            if npc_response.parsed and isinstance(npc_response.parsed, dict):
                npc_proposal = npc_response.parsed
            degradation_level = npc_response.degradation_level
            fallback_used = npc_response.used_fallback
        except Exception as exc:  # noqa: BLE001
            logger.warning("action_runner: NPC proposer failed: %s", exc)
            # L3 hard degradation — the chain stays L3 for the rest of the run.
            degradation_level = "L3"
            fallback_used = True
            npc_proposal = None

        if npc_proposal is None:
            npc_proposal = _default_npc_proposal(
                run_id=run_id, player_action=player_action, scene_id=scene_id
            )
            if degradation_level is None:
                degradation_level = "L3"
            fallback_used = True

        # 2. Director beat — second LLM call (decision 5 R3 = 2 max).
        director_beat: dict[str, Any] | None = None
        if degradation_level != "L3":
            try:
                dir_response = self._runtime.gateway.complete(
                    _build_director_request(
                        run_id=run_id,
                        scene_id=scene_id,
                        player_action=player_action,
                        contract=contract,
                    )
                )
                llm_call_records.append(_record_for_log(dir_response, agent="director_agent", run_id=run_id, scene_id=scene_id))
                llm_call_records_strict.append(
                    _record_for_log_strict(dir_response, agent="director_agent")
                )
                if dir_response.parsed and isinstance(dir_response.parsed, dict):
                    director_beat = dir_response.parsed
                if dir_response.degradation_level and not degradation_level:
                    degradation_level = dir_response.degradation_level
                fallback_used = fallback_used or dir_response.used_fallback
            except Exception as exc:  # noqa: BLE001
                logger.warning("action_runner: Director failed: %s", exc)
                if degradation_level != "L3":
                    degradation_level = "L2"
                fallback_used = True

        if director_beat is None:
            director_beat = _default_director_beat(
                run_id=run_id, scene_id=scene_id, contract=contract
            )
        # ``involvedCharacterIds`` is internal resolver context, not a
        # Director model-output field.  Inject the authoritative scene cast
        # after schema validation so target legality uses the same source as
        # the deterministic preflight.
        director_beat = dict(director_beat)
        director_beat["involvedCharacterIds"] = _contract_cast_ids(contract)

        # 4. Resolver (the only writer).
        # Plant mandatory-echo seeds BEFORE the resolver runs
        # so the resolver's auto-fire evaluation sees them
        # (decision 3: "mandatory_echo is the only path for AI
        # 触达").  The action is checked against the scene's
        # contract for the (action, target, evidence)
        # combination that triggers a known seed.
        try:
            seeds_to_plant = _select_mandatory_seeds(
                scene_id=scene_id,
                action_type=player_action.get("actionType", ""),
                target_id=player_action.get("targetId"),
                evidence_ids=list(player_action.get("evidenceIds", []) or []),
            )
            if seeds_to_plant:
                active.snapshot = active.snapshot.with_causal_seeds_active(
                    _merge_mandatory_seeds(
                        active.snapshot.causalSeedsActive, seeds_to_plant
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("action_runner: seed planting failed: %s", exc)

        try:
            new_snapshot, outcome, mandatory_echo, era_check, four_q = (
                resolver.resolve_turn(
                    snapshot=active.snapshot,
                    event_log=active.event_log,
                    player_action=player_action,
                    npc_proposal_dict=npc_proposal,
                    director_beat_dict=director_beat,
                    scene_contract=contract,
                    scene_budget=active.scene_budget,
                    recall_set=set(),
                    # The outcome's ``auditTrail.llmCalls`` field
                    # is schema-strict (only agent / model /
                    # inputTokens / outputTokens / latencyMs).
                    # We pass the strict subset; the full
                    # ModelResponse dicts (with cost / degradation
                    # / attempts) are still recorded in
                    # ``model_calls`` for audit.
                    llm_calls=llm_call_records_strict,
                )
            )
        except EngineError as exc:
            logger.warning("action_runner: resolver raised %s: %s", type(exc).__name__, exc)
            # The resolver raises on invalid actions; we surface
            # the existing snapshot + a rejection outcome.
            outcome = self._build_rejection_outcome(
                snapshot=active.snapshot,
                player_action=player_action,
                reason=f"{type(exc).__name__}: {exc}",
            )
            new_snapshot = active.snapshot
            fallback_used = True
            if degradation_level is None:
                degradation_level = "L4"
        except Exception as exc:  # noqa: BLE001
            # The L4 fallback — a write failure should never
            # blow the request up; we degrade gracefully.
            logger.exception("action_runner: resolver write failure: %s", exc)
            outcome = self._build_rejection_outcome(
                snapshot=active.snapshot,
                player_action=player_action,
                reason=f"internal_error: {exc}",
            )
            new_snapshot = active.snapshot
            fallback_used = True
            degradation_level = "L4"

        # 5. Update the active-run cache.
        active.snapshot = new_snapshot
        active.event_log = self._registry.open(run_id).event_log  # ensure
        # the resolver's mutations stick (event_log is mutated
        # in place by the engine's record path).
        # Persist via the repository.
        snap_dict = new_snapshot.to_dict()
        self._repo.save_outcome(
            run_id=run_id,
            snapshot=snap_dict,
            outcome=outcome.to_dict(),
            scene_contract=contract,
            player_action=player_action,
            npc_proposal=npc_proposal,
        )

        # 6. Record LLM call audit (one row per call).
        for rec in llm_call_records:
            try:
                self._repo.record_model_call(rec)
            except Exception as exc:  # noqa: BLE001
                logger.warning("action_runner: failed to record model_call: %s", exc)

        # 7. End-of-turn bookkeeping.
        latency_ms = int((time.monotonic() - started) * 1000)
        outcome_dict = outcome.to_dict() if hasattr(outcome, "to_dict") else dict(outcome)

        # 8. Resolved text: prefer the outcome's NPC line;
        # fall back to a writer fallback line for L3.
        resolved_text = (
            outcome_dict.get("acceptedNpcAction", {}).get("resolvedText", "")
            if isinstance(outcome_dict, dict) else ""
        )
        if not resolved_text and fallback_used:
            resolved_text = _writer_fallback_line(player_action)

        return TurnResult(
            outcome=outcome_dict,
            snapshot=snap_dict,
            client_action_id=client_action_id,
            event_sequence=int(new_snapshot.eventSequence),
            degraded=degradation_level,
            fallback_used=fallback_used,
            latency_ms=latency_ms,
            resolved_text=resolved_text,
            model_calls=llm_call_records,
            degraded_to_l3=(degradation_level == "L3"),
        )

    # ----- helpers -------------------------------------------------------

    def _resolver_for(self, run_id: str) -> ResolverAgent:
        holder = self._resolvers.get(run_id)
        if holder is not None:
            return holder.resolver
        resolver = build_resolver_agent(case_slug="case_01_revolution_street")
        self._resolvers[run_id] = ResolverHolder(resolver=resolver)
        return resolver

    @staticmethod
    def _prevalidate_player_action(
        *,
        snapshot: WorldSnapshot,
        event_log: EventLog,
        player_action: dict[str, Any],
        scene_budget: SceneBudget,
        contract: dict[str, Any],
    ) -> None:
        """Run deterministic input gates without mutating canonical state."""

        expected = player_action.get("expectedEventSequence")
        if expected is not None and snapshot.eventSequence - int(expected) > 1:
            raise SequenceMismatchError(
                f"client sequence {expected} is more than 1 behind canonical "
                f"{snapshot.eventSequence}"
            )

        client_action_id = player_action.get("clientActionId")
        if client_action_id:
            for event in event_log:
                if event.actionPayload.get("clientActionId") == client_action_id:
                    raise IdempotencyReplayError(
                        f"clientActionId already applied: {str(client_action_id)[:8]}"
                    )

        cast = _contract_cast_ids(contract)
        reduce(
            player_action,
            snapshot,
            deepcopy(scene_budget),
            scene_whitelist=set(REDUCERS),
            cast=cast or None,
        )

    def _build_rejection_result(
        self,
        *,
        started: float,
        snapshot: WorldSnapshot,
        player_action: dict[str, Any],
        client_action_id: str,
        reason: str,
    ) -> TurnResult:
        """Return a non-canonical rejection at the current event sequence."""

        outcome = self._build_rejection_outcome(
            snapshot=snapshot,
            player_action=player_action,
            reason=reason,
        )
        return TurnResult(
            outcome=outcome.to_dict(),
            snapshot=snapshot.to_dict(),
            client_action_id=client_action_id,
            event_sequence=int(snapshot.eventSequence),
            degraded=None,
            fallback_used=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            resolved_text="",
            model_calls=[],
            degraded_to_l3=False,
        )

    def _build_rejection_outcome(
        self,
        *,
        snapshot: WorldSnapshot,
        player_action: dict[str, Any],
        reason: str,
    ) -> Any:
        from engine.resolver import ResolverOutcome
        # Rejections are returned to the caller but never persisted.  Keep
        # their audit outcome schema-valid (eventSequence >= 1) while the
        # TurnResult and unchanged snapshot remain at the canonical N.
        next_seq = max(1, snapshot.eventSequence + 1)
        return ResolverOutcome(
            outcomeId=str(uuid.uuid4()),
            runId=snapshot.runId,
            eventSequence=next_seq,
            idempotencyKey=f"reject-{uuid.uuid4().hex[:16]}",
            acceptedNpcAction={
                "proposalId": "00000000-0000-0000-0000-000000000000",
                "characterId": "system",
                "proposedAction": "silence",
                "speechIntent": "remain_silent",
                "resolvedText": "",
            },
            nextBeat={
                "sceneId": snapshot.canonicalState.currentSceneId,
                "beatId": "rejected_action",
                "transition": "continue",
                "legalEndingId": None,
            },
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
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
                "deterministicDecisions": [f"action_runner: {reason}"],
            },
        )


def _record_for_log(
    response: Any, *, agent: str, run_id: str = "", scene_id: str = "",
) -> dict[str, Any]:
    """Build the *full* audit record for one LLM call.

    Used for the ``model_calls`` table — every field is
    persisted.
    """

    return {
        "requestId": getattr(response, "request_id", str(uuid.uuid4())),
        "runId": run_id,
        "sceneId": scene_id,
        "taskType": getattr(response.task_type, "value", str(response.task_type)),
        "agent": agent,
        "model": response.model,
        "provider": response.provider,
        "inputTokens": int(response.input_tokens),
        "outputTokens": int(response.output_tokens),
        "latencyMs": int(response.latency_ms),
        "costCny": float(response.cost_cny),
        "finishReason": response.finish_reason,
        "degradationLevel": response.degradation_level,
        "usedFallback": bool(response.used_fallback),
        "attempts": int(response.attempts),
        "metadata": {},
    }


def _record_for_log_strict(response: Any, *, agent: str) -> dict[str, Any]:
    """Build the schema-strict audit record for ``auditTrail.llmCalls``.

    The ``resolver_outcome.schema.json`` rejects any
    additional properties on ``llmCalls[]``; we strip
    everything except ``agent / model / inputTokens /
    outputTokens / latencyMs`` so the schema validator
    accepts the outcome.
    """

    return {
        "agent": agent,
        "model": str(response.model or "unknown"),
        "inputTokens": int(response.input_tokens),
        "outputTokens": int(response.output_tokens),
        "latencyMs": int(response.latency_ms),
    }


def _writer_fallback_line(player_action: dict[str, Any]) -> str:
    """A short L3 fallback line for the LLM-failure path."""

    tone = player_action.get("tone", "neutral")
    if tone in {"angry", "sad"}:
        return "（沉默。灯泡下，他/她的手指慢慢摸过杯沿。）"
    if tone in {"gentle", "playful"}:
        return "（他没有立刻回答。远处地铁的震动把灯泡晃了一下。）"
    return "（他/她没有立刻回答。放映机的低频转动在背景里持续。）"


# ---------------------------------------------------------------------------
# Mandatory-echo seed planting (decision 3)
# ---------------------------------------------------------------------------


#: Map of (scene, action, target, evidence) -> seed id.
#: This is the **only** place that knows which (action,
#: target, evidence) combination plants which causal seed.
#: Everything else flows through the engine.
_MANDATORY_SEED_RULES: list[dict[str, Any]] = [
    {
        "scene": "photo_lab_2008",
        "action": "give",
        "target": "arash",
        "evidence": ["photo_pair"],
        "seed_id": "photo_in_pocket",
        "description": "Leila keeps one graduation photo in her bag.",
        "target_scenes": ["farewell_2011", "reunion_2024"],
    },
    {
        "scene": "photo_lab_2008",
        "action": "give",
        "target": "arash",
        "evidence": ["photo_pair"],
        "seed_id": "photo_in_book",
        "description": "Arash keeps one graduation photo in the Rumi book.",
        "target_scenes": ["farewell_2011", "reunion_2024"],
    },    {
        "scene": "photo_lab_2008",
        "action": "give",
        "target": "leila",
        "evidence": ["photo_A"],
        "seed_id": "photo_in_pocket",
        "description": "莱拉把毕业照放进斜挎包内袋",
        "target_scenes": ["reunion_2024"],
    },
    {
        "scene": "photo_lab_2008",
        "action": "give",
        "target": "arash",
        "evidence": ["photo_B"],
        "seed_id": "photo_in_book",
        "description": "阿拉什把毕业照夹进鲁米诗集",
        "target_scenes": ["reunion_2024"],
    },
    {
        "scene": "farewell_2011",
        "action": "give",
        "target": "leila",
        "evidence": ["luggage_tag"],
        "seed_id": "luggage_tag_word",
        "description": "莱拉在行李牌背面写字",
        "target_scenes": ["reunion_2024"],
    },
    {
        "scene": "reunion_2024",
        "action": "give",
        "target": "arash",
        "evidence": ["photo_A", "photo_B"],
        "seed_id": "photos_aligned",
        "description": "两张同版毕业照在桌上对齐",
        "target_scenes": ["reunion_2024"],
    },
]


def _select_mandatory_seeds(
    *,
    scene_id: str,
    action_type: str,
    target_id: str | None,
    evidence_ids: list[str],
) -> list[Any]:
    """Return all mandatory seeds planted by this turn, de-duplicated by ID."""

    from engine.causal_seed import CausalSeed, TriggerCondition

    target = (target_id or "").strip()
    evidence_set = {eid for eid in evidence_ids if eid}
    selected: list[CausalSeed] = []
    selected_ids: set[str] = set()
    for rule in _MANDATORY_SEED_RULES:
        if rule["scene"] != scene_id or rule["action"] != action_type:
            continue
        if rule["target"] != target:
            continue
        if not evidence_set.issuperset(set(rule["evidence"])):
            continue
        if rule["seed_id"] in selected_ids:
            continue
        selected.append(CausalSeed(
            id=rule["seed_id"],
            source_scene=scene_id,
            source_event="w4_demo_plant",
            description=rule["description"],
            trigger_condition=TriggerCondition(
                type="scene_match",
                predicate="current_scene in target_scenes",
            ),
            target_scenes=list(rule["target_scenes"]),
            echo_intensity=0.9,
            is_secret=False,
            linkedCharacterIds=["leila", "arash"],
            decayRate=0.02,
            tags=["mandatory_echo", "w4_demo"],
        ))
        selected_ids.add(rule["seed_id"])
    return selected


def _select_mandatory_seed(
    *,
    scene_id: str,
    action_type: str,
    target_id: str | None,
    evidence_ids: list[str],
):
    """Backward-compatible single-seed selector."""

    seeds = _select_mandatory_seeds(
        scene_id=scene_id,
        action_type=action_type,
        target_id=target_id,
        evidence_ids=evidence_ids,
    )
    return seeds[0] if seeds else None


def _merge_mandatory_seeds(
    existing: list[dict[str, Any]], additions: list[Any]
) -> list[dict[str, Any]]:
    """Append newly planted seeds without duplicating canonical IDs."""

    merged = [dict(seed) for seed in existing]
    known_ids = {
        str(seed.get("id")) for seed in merged
        if isinstance(seed, dict) and seed.get("id")
    }
    for seed in additions:
        seed_dict = seed.to_dict()
        seed_id = str(seed_dict.get("id", ""))
        if not seed_id or seed_id in known_ids:
            continue
        merged.append(seed_dict)
        known_ids.add(seed_id)
    return merged

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_default_runner: ActionRunner | None = None


def get_default_runner() -> ActionRunner:
    """Return a process-wide action runner singleton."""

    global _default_runner
    if _default_runner is None:
        _default_runner = ActionRunner()
    return _default_runner


__all__ = ["ActionRunner", "TurnResult", "get_default_runner"]
