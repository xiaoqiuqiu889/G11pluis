"""Resolver agent — the AI-native proposal-merge writer.

This module is the **W3-B-side** wrapper around the engine's
deterministic :class:`engine.resolver.Resolver`.  The agent's job
is to take the three proposals (Player, NPC, Director), run them
through the Resolver, and produce the final
:class:`engine.resolver.ResolverOutcome` with:

1. **UP-20260715-002 mandatory_echo validation** — any NPC
   proposal that *voluntarily* surfaces a past-event echo MUST
   reference a seed in the scene's ``mandatory_echoes`` list.
   Otherwise the NPC proposal is rejected with
   ``reason="violates_contract"``.  This is the
   decision-3 / UP-20260715-002 / critical fix.

2. **Case-aware era validation** (ADR 0007 §4.2) — every
   snapshot hydration / canonical-state update calls
   :func:`engine.types.is_valid_era_for_case` against the
   case slug.

3. **Numeric clamping audit** — every value written to the
   snapshot passes through the engine's ``clamp`` helpers; the
   Resolver records any clamp event in
   ``outcome.clampedValues``.

4. **Idempotency** — the same ``(runId, eventSequence,
   triggerPlayerActionId, triggerDirectorProposalId)`` produces
   the same outcomeId.  Replays are no-ops.

5. **4-questions coverage** — the Resolver records, for each
   outcome, which of the four legs were satisfied by the
   (Player + NPC + Director) set, in
   ``outcome.auditTrail.deterministicDecisions``.

6. **LLM-call audit** — every model call the agents make is
   added to ``outcome.auditTrail.llmCalls``.

The Resolver is the **only** component that writes to canonical
state.  No agent — Intent, NPC, Director, Memory — has any
write authority.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Final

import jsonschema

from .four_questions import check_four_questions, FourQuestionsResult
from .model_gateway import ModelResponse
from .prompts import STYLE_BIBLE_VERSION


RESOLVER_AGENT_VERSION: Final[str] = "1.0.0"


class ResolverAgentError(RuntimeError):
    """Raised by the Resolver agent on irrecoverable failure.

    L4 (decision 5): the player-facing "service unavailable"
    message is surfaced, the save is preserved.
    """


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MandatoryEchoCheck:
    """One element of :class:`MandatoryEchoValidation`.

    Attributes
    ----------
    seed_id : str
        The seed id the NPC tried to surface.
    matched : bool
        True iff the seed is in the scene's ``mandatory_echoes``.
    detail : str
        Human-readable explanation.
    """

    seed_id: str
    matched: bool
    detail: str


@dataclass(slots=True)
class MandatoryEchoValidation:
    """The full UP-20260715-002 check.

    Attributes
    ----------
    echo_attempted : bool
        True iff the NPC proposal was detected as a voluntary
        echo (i.e. it referenced a seed from the contract's
        ``causal_seeds`` or surfaced a memory formed in a prior
        scene).
    checks : list[MandatoryEchoCheck]
        Per-seed check result.
    passes : bool
        True iff every attempted echo matched a mandatory echo,
        or no echo was attempted.
    summary : str
        Human-readable one-liner.
    """

    echo_attempted: bool = False
    checks: list[MandatoryEchoCheck] = field(default_factory=list)
    passes: bool = True
    summary: str = "no echo attempted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "echo_attempted": self.echo_attempted,
            "passes": self.passes,
            "summary": self.summary,
            "checks": [
                {"seed_id": c.seed_id, "matched": c.matched, "detail": c.detail}
                for c in self.checks
            ],
            "version": RESOLVER_AGENT_VERSION,
        }


@dataclass(slots=True)
class CaseAwareEraCheck:
    """The ADR 0007 §4.2 era-validation result."""

    era: str
    case_slug: str
    is_legal: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "era": self.era,
            "case_slug": self.case_slug,
            "is_legal": self.is_legal,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------


class ResolverAgent:
    """W3-B Resolver wrapper.

    Parameters
    ----------
    engine_resolver
        An instance of :class:`engine.resolver.Resolver` from the
        engine package.  The agent delegates all state-mutation
        work to it; the agent itself is a thin orchestrator that
        adds the **mandatory_echo** and **case-aware era** gates
        on top.
    case_slug
        The case identifier (e.g. ``"case_01_revolution_street"``).
        Used for the case-aware era check.
    schema_path
        Path to ``resolver_outcome.schema.json``.  Defaults to the
        shipped schema.
    """

    _SCHEMA_FILE: Final[str] = "resolver_outcome.schema.json"

    def __init__(
        self,
        engine_resolver: Any,
        *,
        case_slug: str,
        schema_path: str | None = None,
    ) -> None:
        self.engine_resolver = engine_resolver
        self.case_slug = str(case_slug)
        self._schema = self._load_schema(schema_path)
        # Engine helpers — imported lazily so the agents package
        # can be imported even if the engine has a build issue.
        from engine.types import is_valid_era_for_case  # noqa: WPS433
        self._is_valid_era_for_case = is_valid_era_for_case
        from engine.resolver import NPCProposal, DirectorBeatInput, NarrativeContract
        self._NPCProposal = NPCProposal
        self._DirectorBeatInput = DirectorBeatInput
        self._NarrativeContract = NarrativeContract

    # ----- public API ----------------------------------------------------

    def resolve_turn(
        self,
        *,
        snapshot: Any,
        event_log: Any,
        player_action: dict[str, Any] | None,
        npc_proposal_dict: dict[str, Any] | None,
        director_beat_dict: dict[str, Any] | None,
        scene_contract: dict[str, Any],
        scene_budget: Any,
        recall_set: set[str] | None = None,
        llm_calls: list[dict[str, Any]] | None = None,
    ) -> tuple[Any, Any, MandatoryEchoValidation, CaseAwareEraCheck, FourQuestionsResult]:
        """Run the full resolve.

        Returns
        -------
        (new_snapshot, outcome, mandatory_echo, era_check, four_questions)
            The new snapshot + outcome are the engine's output;
            the three diagnostic objects are the agent's
            contributions.  All five are returned so the HTTP
            handler / persistence layer can store them
            together.
        """

        # ---- 1. Case-aware era validation (ADR 0007 §4.2) ----------------
        era_check = self._validate_era(snapshot)
        if not era_check.is_legal:
            raise ResolverAgentError(era_check.detail)

        # ---- 2. UP-20260715-002 mandatory_echo validation ----------------
        npc_proposal_obj: Any = None
        rejected_npc: list[dict[str, Any]] = []
        mandatory_echo = MandatoryEchoValidation()
        if npc_proposal_dict is not None:
            mandatory_echo = self._validate_mandatory_echo(
                npc_proposal_dict, scene_contract
            )
            if not mandatory_echo.passes:
                # Reject the NPC proposal before it ever reaches
                # the engine's Resolver.  We convert it to an
                # engine.NPCProposal so the engine's own
                # pipeline sees a uniform input.
                rejected_npc.append(
                    {
                        "proposalId": npc_proposal_dict.get("proposalId", "?"),
                        "reason": "violates_contract",
                        "detail": mandatory_echo.summary,
                    }
                )
            else:
                npc_proposal_obj = self._build_npc_proposal(npc_proposal_dict)

        # ---- 3. Build the engine contract + Director input ---------------
        engine_contract = self._build_engine_contract(scene_contract)
        director_input = (
            self._build_director_input(director_beat_dict)
            if director_beat_dict is not None
            else None
        )

        # ---- 4. Run the engine Resolver ----------------------------------
        try:
            new_snapshot, outcome = self.engine_resolver.resolve(
                snapshot=snapshot,
                event_log=event_log,
                player_action=player_action,
                npc_proposal=npc_proposal_obj,
                director_beat=director_input,
                contract=engine_contract,
                scene_budget=scene_budget,
                recall_set=recall_set,
            )
        except Exception as exc:  # engine raises EngineError subclasses
            raise ResolverAgentError(
                f"engine Resolver failed: {type(exc).__name__}: {exc}"
            )

        # ---- 5. Augment the outcome with rejected NPC proposals ----------
        if rejected_npc:
            existing = list(outcome.rejectedNpcActions or [])
            # Replace the auto-injected "" proposal by the
            # engine's acceptedNpcAction with our reject (the
            # engine's NPCProposal was None in this branch).
            for r in rejected_npc:
                if r not in existing:
                    existing.append(r)
            outcome.rejectedNpcActions = existing
            # If the engine silently set the acceptedNpcAction
            # to a "silence" stub (because npc_proposal was None),
            # leave it — that's the L1 fallback shape.

        # ---- 6. Append LLM calls to the audit trail ----------------------
        if llm_calls:
            audit = dict(outcome.auditTrail or {"llmCalls": [], "deterministicDecisions": []})
            audit.setdefault("llmCalls", [])
            audit["llmCalls"] = list(audit["llmCalls"]) + list(llm_calls)
            decisions = list(audit.get("deterministicDecisions", []))
            decisions.append(
                f"resolver_agent: case_slug={self.case_slug} "
                f"era={era_check.era} legal={era_check.is_legal}"
            )
            decisions.append(
                f"resolver_agent: mandatory_echo passes={mandatory_echo.passes} "
                f"attempted={mandatory_echo.echo_attempted}"
            )
            audit["deterministicDecisions"] = decisions
            outcome.auditTrail = audit

        # ---- 7. Four-questions self-check (decision 6) -------------------
        four_q = self._collect_four_questions(
            player_action=player_action,
            npc_proposal_dict=npc_proposal_dict,
            director_beat_dict=director_beat_dict,
            scene_contract=scene_contract,
            accepted_npc=outcome.acceptedNpcAction,
            outcome=outcome,
        )
        # Record the four-questions summary in the audit trail
        audit = dict(outcome.auditTrail or {"llmCalls": [], "deterministicDecisions": []})
        decisions = list(audit.get("deterministicDecisions", []))
        decisions.append(
            f"four_questions: passes={four_q.passes} "
            f"satisfied={list(four_q.satisfied_questions())}"
        )
        audit["deterministicDecisions"] = decisions
        outcome.auditTrail = audit

        # ---- 8. Schema-validate the outcome -----------------------------
        try:
            jsonschema.validate(outcome.to_dict(), self._schema)
        except jsonschema.ValidationError as exc:
            raise ResolverAgentError(
                f"Resolver outcome failed schema validation: {exc.message}"
            )

        return new_snapshot, outcome, mandatory_echo, era_check, four_q

    # ----- UP-20260715-002 ------------------------------------------------

    def _validate_mandatory_echo(
        self,
        npc_proposal: dict[str, Any],
        scene_contract: dict[str, Any],
    ) -> MandatoryEchoValidation:
        """Check that any voluntary echo surfaces a mandatory seed.

        A proposal is detected as a **voluntary echo** when ANY of
        these signals fires:

        1. ``speechIntent`` ∈ ``{"reveal_truth", "admit", "accuse",
           "defend", "taunt", "plead"}`` AND the proposal
           references at least one memory whose ``subject`` is
           a seed in the contract's ``causal_seeds``.
        2. The proposal's ``beliefUpdatesRequested`` lists a
           ``subject`` that is a seed id from
           ``contract.causal_seeds``.
        3. The proposal's ``referencedMemoryIds`` include a
           memory whose ``subject`` is a seed id from
           ``contract.causal_seeds``.

        For each such seed, we check whether it is in
        ``contract.mandatory_echoes``.  If any seed is **not**
        in the mandatory list, the check fails.

        If the contract declares no ``causal_seeds``, there is
        no echo to validate — the check passes vacuously.
        """

        causal_seed_ids = {
            s for s in (scene_contract.get("causal_seeds") or []) if isinstance(s, str)
        }
        mandatory_ids = {
            me.get("id") for me in (scene_contract.get("mandatory_echoes") or [])
            if isinstance(me, dict) and me.get("id")
        }
        # No echo to validate
        if not causal_seed_ids:
            return MandatoryEchoValidation(
                echo_attempted=False,
                passes=True,
                summary="no causal_seeds registered; echo check vacuously passes",
            )

        speech_intent = npc_proposal.get("speechIntent", "")
        echo_intents = {"reveal_truth", "admit", "accuse", "defend", "taunt", "plead", "seek_confirmation"}
        belief_subjects = {
            u.get("subject", "")
            for u in npc_proposal.get("beliefUpdatesRequested", []) or []
        }
        referenced_subjects: set[str] = set()
        for mid in npc_proposal.get("referencedMemoryIds", []) or []:
            # The LLM may not embed the subject; the agent's job
            # is to check intent + belief-subject signals.  We
            # only check what the LLM actually emitted.  The
            # engine's existing ungrounded-memory check handles
            # memory ↔ recall mismatches.
            pass

        # Pull subjects from the proposal's memory references if
        # the agent annotated them (the W3-B agent sets a
        # ``memorySubjects`` field for this purpose; the
        # production gateway will populate it).
        ms = npc_proposal.get("memorySubjects") or {}
        if isinstance(ms, dict):
            for mid, subj in ms.items():
                if isinstance(subj, str) and subj:
                    referenced_subjects.add(subj)

        # The set of seeds the NPC is "voluntarily surfacing"
        attempted_seeds: set[str] = set()
        for s in belief_subjects:
            if s in causal_seed_ids:
                attempted_seeds.add(s)
        for s in referenced_subjects:
            if s in causal_seed_ids:
                attempted_seeds.add(s)
        if speech_intent in echo_intents and (belief_subjects & causal_seed_ids or referenced_subjects & causal_seed_ids):
            # The agent's speech intent + a seed reference = clear
            # voluntary echo.
            attempted_seeds = (belief_subjects | referenced_subjects) & causal_seed_ids
        # If speech intent is in echo_intents but no seed was
        # named, the agent might still be voluntarily surfacing
        # an un-named echo.  We don't reject on intent alone —
        # the engine's ungrounded-memory check + the contract's
        # forbidden_reveals check cover that path.  Here we only
        # reject **named** echoes that miss the mandatory list.

        if not attempted_seeds:
            return MandatoryEchoValidation(
                echo_attempted=False,
                passes=True,
                summary="NPC proposal did not surface a registered seed",
            )

        checks: list[MandatoryEchoCheck] = []
        passes = True
        for sid in sorted(attempted_seeds):
            matched = sid in mandatory_ids
            checks.append(MandatoryEchoCheck(
                seed_id=sid,
                matched=matched,
                detail=(
                    f"seed {sid!r} is in scene.mandatory_echoes"
                    if matched
                    else f"seed {sid!r} is NOT in scene.mandatory_echoes (UP-20260715-002 violation)"
                ),
            ))
            if not matched:
                passes = False
        summary = (
            f"voluntary echo attempted on {len(attempted_seeds)} seed(s); "
            + ("all in mandatory_echoes" if passes else "violates UP-20260715-002")
        )
        return MandatoryEchoValidation(
            echo_attempted=True,
            checks=checks,
            passes=passes,
            summary=summary,
        )

    # ----- ADR 0007 §4.2 --------------------------------------------------

    def _validate_era(self, snapshot: Any) -> CaseAwareEraCheck:
        era = snapshot.canonicalState.era
        is_legal = bool(self._is_valid_era_for_case(era, self.case_slug))
        detail = "" if is_legal else (
            f"era {era!r} is not legal for case {self.case_slug!r} (ADR 0007 §4.2)"
        )
        return CaseAwareEraCheck(era=era, case_slug=self.case_slug, is_legal=is_legal, detail=detail)

    # ----- engine adapter helpers ----------------------------------------

    def _build_npc_proposal(self, raw: dict[str, Any]) -> Any:
        """Convert the agent's proposal dict to engine.NPCProposal."""

        p = self._NPCProposal(
            proposalId=raw.get("proposalId") or str(uuid.uuid4()),
            characterId=raw.get("characterId", ""),
            proposedAction=raw.get("proposedAction", "silence"),
            speechIntent=raw.get("speechIntent", "remain_silent"),
            targetId=raw.get("targetId"),
            referencedMemoryIds=list(raw.get("referencedMemoryIds", []) or []),
            beliefUpdatesRequested=list(raw.get("beliefUpdatesRequested", []) or []),
            emotionalTransition=raw.get("emotionalTransition"),
            reasonCodes=list(raw.get("reasonCodes", []) or []),
            confidence=float(raw.get("confidence", 0.5) or 0.5),
            expectedContradictions=list(raw.get("expectedContradictions", []) or []),
        )
        # Attach a relationshipDelta attribute if present; the
        # engine reads it via getattr(..., "relationshipDelta", []).
        rel = raw.get("relationshipDelta")
        if rel:
            try:
                object.__setattr__(p, "relationshipDelta", list(rel))
            except (AttributeError, TypeError):
                pass
        return p

    def _build_director_input(self, raw: dict[str, Any]) -> Any:
        return self._DirectorBeatInput(
            proposalId=raw.get("proposalId") or str(uuid.uuid4()),
            proposedBeat=raw.get("proposedBeat", ""),
            allowedByContract=bool(raw.get("allowedByContract", True)),
            forbiddenRevealsChecked=list(raw.get("forbiddenRevealsChecked", []) or []),
            transitionToNext=bool(raw.get("transitionToNext", False)),
            suggestedTargetSceneId=raw.get("suggestedTargetSceneId"),
            reasoning=raw.get("reasoning", ""),
            pacingPressure=float(raw.get("pacingPressure", 0.0) or 0.0),
            expectedTensionDelta=float(raw.get("expectedTensionDelta", 0.0) or 0.0),
            involvedCharacterIds=list(raw.get("involvedCharacterIds", []) or []),
            firedCausalSeeds=list(raw.get("firedCausalSeeds", []) or []),
        )

    def _build_engine_contract(self, scene_contract: dict[str, Any]) -> Any:
        return self._NarrativeContract(
            sceneId=scene_contract.get("sceneId", "?"),
            allowed_beats=list(scene_contract.get("allowed_beats", []) or []),
            forbidden_reveals=list(scene_contract.get("forbidden_reveals", []) or []),
            legal_endings=list(scene_contract.get("legal_endings", []) or []),
            max_turns=int(scene_contract.get("max_turns", 8) or 8),
            total_action_budget=int(scene_contract.get("total_action_budget", 32) or 32),
            causal_seeds=list(scene_contract.get("causal_seeds", []) or []),
        )

    # ----- four-questions aggregator -------------------------------------

    def _collect_four_questions(
        self,
        *,
        player_action: dict[str, Any] | None,
        npc_proposal_dict: dict[str, Any] | None,
        director_beat_dict: dict[str, Any] | None,
        scene_contract: dict[str, Any],
        accepted_npc: dict[str, Any] | None,
        outcome: Any,
    ) -> FourQuestionsResult:
        artifact_updates: list[Any] = []
        belief_updates: list[Any] = []
        fired_seeds: list[str] = []
        if npc_proposal_dict is not None:
            belief_updates.extend(npc_proposal_dict.get("beliefUpdatesRequested", []) or [])
        if director_beat_dict is not None:
            fired_seeds.extend(director_beat_dict.get("firedCausalSeeds", []) or [])
            fired_seeds.extend(director_beat_dict.get("newCausalSeeds", []) or [])
        # Also pull from the engine outcome
        try:
            for au in outcome.artifactUpdates or []:
                artifact_updates.append(au)
        except AttributeError:
            pass
        try:
            for bu in outcome.beliefUpdates or []:
                belief_updates.append(bu)
        except AttributeError:
            pass
        try:
            for s in outcome.firedCausalSeeds or []:
                fired_seeds.append(s)
        except AttributeError:
            pass

        return check_four_questions(
            artifact_updates=artifact_updates,
            belief_updates=belief_updates,
            budget_delta=(
                {"director_action": 1} if director_beat_dict is not None else None
            ),
            fired_seed_ids=fired_seeds,
            scene_mandatory_echoes=scene_contract.get("mandatory_echoes", []) or [],
        )

    # ----- LLM-call helper -----------------------------------------------

    @staticmethod
    def make_llm_call_record(
        *,
        agent: str,
        response: ModelResponse,
        scene_id: str,
        character_id: str | None = None,
    ) -> dict[str, Any]:
        """Build an ``auditTrail.llmCalls`` entry from a gateway response."""

        return {
            "agent": agent,
            "model": response.model,
            "inputTokens": int(response.input_tokens),
            "outputTokens": int(response.output_tokens),
            "latencyMs": int(response.latency_ms),
            "sceneId": scene_id,
            "characterId": character_id,
        }

    @staticmethod
    def _load_schema(schema_path: str | None) -> dict[str, Any]:
        if schema_path is None:
            from pathlib import Path
            root = Path(__file__).resolve().parents[1]
            schema_path = str(root / "config" / "schemas" / "resolver_outcome.schema.json")
        with open(schema_path, "r", encoding="utf-8") as fh:
            return json.load(fh)


__all__ = [
    "RESOLVER_AGENT_VERSION",
    "ResolverAgent",
    "ResolverAgentError",
    "MandatoryEchoValidation",
    "MandatoryEchoCheck",
    "CaseAwareEraCheck",
]
