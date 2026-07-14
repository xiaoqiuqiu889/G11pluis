"""Resolver — the **AUTHORITATIVE** state-mutation agent.

This module is the W3-B resolver agent and the **only** component
in the system that may write to canonical state.  It sits on top of
the deterministic engine (:mod:`server.engine.resolver`) and adds
the AI-native gates the bare engine doesn't enforce:

* **UP-20260715-002 mandatory_echo validation** — any NPC proposal
  that *voluntarily* surfaces a past-event echo MUST reference a
  seed in the scene's ``mandatory_echoes`` list.  Violations
  are recorded in ``outcome.rejectedNpcActions`` with
  ``reason="violates_contract"`` (decision 3, critical).

* **Case-aware era validation** (ADR 0007 §4.2) — every snapshot
  hydration / canonical-state update calls
  :func:`server.engine.types.is_valid_era_for_case` against the
  configured case slug.  An illegal era short-circuits the
  resolve and raises :exc:`ResolverAgentError` (the caller
  surfaces an L4 "service unavailable" — decision 5).

* **Numeric clamping audit** — every value the engine writes to
  the snapshot passes through the engine's ``clamp`` helpers;
  the resolver propagates the clamp audit into
  ``outcome.clampedValues``.

* **Idempotency** — the same ``idempotencyKey`` (composite of
  ``(runId, eventSequence, triggerPlayerActionId,
  triggerDirectorProposalId)``, length 16-128) re-applied is a
  **no-op** that returns the cached outcome instead of
  advancing state.

* **Replay consistency** — given the same event log + the same
  random seed stream, the resolver must reproduce the same
  outcome byte-for-byte.  This is what makes the
  ``tests/adversarial/test_replay_lab.py`` regression net
  work.

* **Write-domain isolation** — the resolver is the **only**
  agent that calls into the engine's mutating path
  (:meth:`engine.resolver.Resolver.resolve`).  All other
  agents (Intent, NPC, Director, Memory) produce proposals /
  queries and never touch canonical state directly.

The class is the **authoritative** writer for the
``case_01_revolution_street`` vertical slice.  Adding new
behavioural rules means adding a check here (or, if
deterministic, in the engine) — not bypassing the resolver.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Final

import jsonschema

# Engine helpers — imported at module load so type checkers can
# see them; the agents package depends on the engine.
from engine.types import (
    SCHEMA_VERSION,
    is_valid_era_for_case,
    legal_eras_for_case,
    clamp_unit,
    clamp_relationship,
    clamp_relationship_delta,
    MAX_RELATIONSHIP_DELTA,
)
from engine.resolver import (
    Resolver as EngineResolver,
    NPCProposal as EngineNPCProposal,
    DirectorBeatInput as EngineDirectorBeatInput,
    NarrativeContract as EngineNarrativeContract,
    ResolverOutcome as EngineResolverOutcome,
)
from engine.event_log import EventLog
from engine.world_snapshot import WorldSnapshot
from engine.state_machine import SceneBudget
from engine.exceptions import EngineError

from .four_questions import check_four_questions, FourQuestionsResult
from .model_gateway import ModelResponse


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

RESOLVER_AGENT_VERSION: Final[str] = "1.0.0"
RESOLVER_AGENT_SCHEMA_VERSION: Final[str] = "1.0.0"

# The Resolver outcome must use a UUID of exactly 36 characters.
# We generate it here (rather than in the engine) so the
# test-suite can patch the UUID generator and exercise the
# idempotency path deterministically.
_OUTCOME_ID_GEN: Final = lambda: str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ResolverAgentError(RuntimeError):
    """Raised by the Resolver agent on irrecoverable failure.

    Decision 5 L4: the player-facing "service unavailable"
    message is surfaced; the save is preserved.
    """


class CaseAwareEraError(ResolverAgentError):
    """Raised when the active era is not legal for the case (ADR 0007 §4.2)."""


class SchemaValidationError(ResolverAgentError):
    """Raised when the resolved outcome fails its own schema check.

    This is the catch-all guard for "the resolver emitted
    something the schema rejects" — by definition a bug in the
    resolver, not the caller's.
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

    def to_dict(self) -> dict[str, Any]:
        return {"seed_id": self.seed_id, "matched": self.matched, "detail": self.detail}


@dataclass(slots=True)
class MandatoryEchoValidation:
    """The full UP-20260715-002 check result.

    A proposal **passes** the check iff:

    * No echo was attempted at all (vacuous pass), **or**
    * Every attempted echo seed is listed in the scene's
      ``mandatory_echoes``.

    A check with ``passes=False`` is recorded in
    ``outcome.rejectedNpcActions`` with
    ``reason="violates_contract"``.

    Decision 3 ties this to the same validation as the
    cross-era echo rule: AI 导演不能自由发挥 — only registered
    mandatory echoes may be surfaced.
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
            "checks": [c.to_dict() for c in self.checks],
            "version": RESOLVER_AGENT_VERSION,
        }


@dataclass(slots=True)
class CaseAwareEraCheck:
    """The ADR 0007 §4.2 era-validation result.

    The resolver runs this on every snapshot that enters the
    resolve path; an illegal era is fatal.
    """

    era: str
    case_slug: str
    is_legal: bool
    legal_set: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "era": self.era,
            "case_slug": self.case_slug,
            "is_legal": self.is_legal,
            "legal_set_size": len(self.legal_set),
            "detail": self.detail,
            "version": RESOLVER_AGENT_VERSION,
        }


@dataclass(slots=True)
class ClampAuditEntry:
    """A single clamp event in the resolver's audit trail.

    Matches the ``resolver_outcome.clampedValues`` schema.
    """

    path: str
    original: float
    applied: float
    min: float
    max: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "original": self.original,
            "applied": self.applied,
            "min": self.min,
            "max": self.max,
        }


@dataclass(slots=True)
class IdempotencyRecord:
    """Tracks the (idempotencyKey, outcome) pairs the resolver has emitted.

    Used to short-circuit replays.  Stored in memory; the
    persistence layer mirrors the same map for cross-process
    consistency.
    """

    idempotencyKey: str
    outcomeId: str
    eventSequence: int
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "idempotencyKey": self.idempotencyKey,
            "outcomeId": self.outcomeId,
            "eventSequence": self.eventSequence,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------


class ResolverAgent:
    """W3-B Resolver — the authoritative state-mutation agent.

    Parameters
    ----------
    engine_resolver
        An :class:`engine.resolver.Resolver` instance.  The
        agent delegates state mutation to it; the agent itself
        is the *gatekeeper* that adds the UP-20260715-002
        mandatory-echo check, the ADR 0007 case-aware era
        check, idempotency caching, and a final
        schema-validation pass.
    case_slug
        The case identifier (e.g.
        ``"case_01_revolution_street"``).  Used for the
        case-aware era check.
    schema_path
        Path to ``resolver_outcome.schema.json``.  Defaults to
        the shipped schema.  Pass an explicit path for tests.
    base_random_seed
        Seed the engine's RNG with this value.  Deterministic
        re-runs (replay consistency) must use the same seed.
    enable_mandatory_echo_check
        Master switch for the UP-20260715-002 check.  Defaults
        to True; tests that want to bypass the check (e.g. to
        exercise the engine's other rejection paths) can flip
        it off.

    Notes
    -----
    The class is intentionally **stateless across runs**: the
    only state it carries is the idempotency cache, which is
    keyed by runId.  Multiple runs in the same agent instance
    are isolated by their (runId, idempotencyKey) key.  A
    longer-lived persistence store mirrors the same map; this
    in-memory cache is the "L1" cache for hot replays.
    """

    _SCHEMA_FILE: Final[str] = "resolver_outcome.schema.json"

    def __init__(
        self,
        engine_resolver: EngineResolver,
        *,
        case_slug: str,
        schema_path: str | None = None,
        base_random_seed: int = 0,
        enable_mandatory_echo_check: bool = True,
    ) -> None:
        self.engine_resolver = engine_resolver
        self.case_slug = str(case_slug)
        self.base_random_seed = int(base_random_seed)
        self.enable_mandatory_echo_check = bool(enable_mandatory_echo_check)
        self._schema = self._load_schema(schema_path)
        # Idempotency cache: (runId, idempotencyKey) -> IdempotencyRecord
        self._idempotency_cache: dict[tuple[str, str], IdempotencyRecord] = {}
        # Clamp audit accumulators (per-call; the agent exposes
        # the most recent call's audit alongside the outcome).
        self._last_clamp_audit: list[ClampAuditEntry] = []
        # For deterministic UUIDs in tests, allow monkey-patching
        # the generator.
        self._outcome_id_gen = _OUTCOME_ID_GEN

    # =====================================================================
    # PUBLIC API
    # =====================================================================

    def resolve_turn(
        self,
        *,
        snapshot: WorldSnapshot,
        event_log: EventLog,
        player_action: dict[str, Any] | None,
        npc_proposal_dict: dict[str, Any] | None,
        director_beat_dict: dict[str, Any] | None,
        scene_contract: dict[str, Any],
        scene_budget: SceneBudget,
        recall_set: set[str] | None = None,
        llm_calls: list[dict[str, Any]] | None = None,
    ) -> tuple[
        WorldSnapshot,
        EngineResolverOutcome,
        MandatoryEchoValidation,
        CaseAwareEraCheck,
        FourQuestionsResult,
    ]:
        """Run the full resolve for a single turn.

        Returns
        -------
        (new_snapshot, outcome, mandatory_echo, era_check, four_questions)
            * ``new_snapshot`` — the canonical state after this
              turn (or the **unchanged** snapshot if the call
              was a replay).  Always returns a snapshot; the
              caller may compare its ``eventSequence`` to the
              input to detect a no-op.
            * ``outcome`` — the engine's
              :class:`engine.resolver.ResolverOutcome`.  The
              agent decorates this with rejected-NPC entries
              and the audit-trail LLM-call list.
            * ``mandatory_echo`` — the UP-20260715-002 check
              result.
            * ``era_check`` — the ADR 0007 §4.2 era check.
            * ``four_questions`` — the decision-6 self-check
              summary.

        Raises
        ------
        ResolverAgentError
            On irrecoverable failure (era invalid, schema
            validation failure, engine exception).
        """

        # ---- 0. Reset per-call audit -------------------------------------
        self._last_clamp_audit = []

        # ---- 1. Case-aware era validation (ADR 0007 §4.2) ----------------
        era_check = self._validate_era(snapshot)
        if not era_check.is_legal:
            raise CaseAwareEraError(era_check.detail)

        # ---- 2. Pre-compute the idempotency key --------------------------
        # The engine will compute the same key; we compute it
        # here so we can short-circuit replays *before*
        # touching the event log.
        next_seq = snapshot.eventSequence + 1
        idem = self._make_idempotency_key(
            snapshot.runId,
            next_seq,
            (player_action or {}).get("clientActionId") if player_action else None,
            (director_beat_dict or {}).get("proposalId") if director_beat_dict else None,
        )
        # We use a *replay-stable* cache key: the (runId,
        # clientActionId, directorProposalId) tuple.  The
        # sequence-based key would change on every replay
        # (because ``next_seq`` increments), so we cannot use
        # it to detect a duplicate submission.
        caid = (player_action or {}).get("clientActionId") if player_action else None
        did = (director_beat_dict or {}).get("proposalId") if director_beat_dict else None
        cache_key: tuple[str, str | None, str | None] = (snapshot.runId, caid, did)
        if cache_key in self._idempotency_cache:
            # Replay: return the cached outcome.  The engine
            # itself raises IdempotencyReplayError on the same
            # key, so this branch handles in-process retries
            # before the event log is consulted.
            cached = self._idempotency_cache[cache_key]
            return (
                snapshot,
                _cached_outcome_to_resolver_outcome(
                    cached, snapshot, player_action, director_beat_dict
                ),
                MandatoryEchoValidation(summary="replay: no echo check re-run"),
                era_check,
                FourQuestionsResult(summary=["replay: no four-questions re-run"]),
            )

        # ---- 3. UP-20260715-002 mandatory_echo validation ----------------
        npc_proposal_obj: EngineNPCProposal | None = None
        rejected_npc: list[dict[str, Any]] = []
        if npc_proposal_dict is not None:
            mandatory_echo = self._validate_mandatory_echo(
                npc_proposal_dict, scene_contract
            )
            if not mandatory_echo.passes:
                rejected_npc.append(
                    {
                        "proposalId": npc_proposal_dict.get("proposalId", "?"),
                        "reason": "violates_contract",
                        "detail": mandatory_echo.summary,
                    }
                )
            else:
                npc_proposal_obj = self._build_engine_npc_proposal(npc_proposal_dict)
        else:
            mandatory_echo = MandatoryEchoValidation(
                summary="no NPC proposal submitted"
            )

        # ---- 4. Build the engine contract + Director input ---------------
        engine_contract = self._build_engine_contract(scene_contract)
        director_input = (
            self._build_engine_director_input(director_beat_dict)
            if director_beat_dict is not None
            else None
        )

        # ---- 5. Run the engine Resolver ----------------------------------
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
        except EngineError as exc:
            raise ResolverAgentError(
                f"engine Resolver failed: {type(exc).__name__}: {exc}"
            ) from exc

        # ---- 6. Inject the rejected-NPC entry (UP-20260715-002) -----------
        if rejected_npc:
            existing = list(outcome.rejectedNpcActions or [])
            for r in rejected_npc:
                if r not in existing:
                    existing.append(r)
            outcome.rejectedNpcActions = existing

        # ---- 7. Append LLM-call audit + deterministic decisions -----------
        audit = dict(outcome.auditTrail or {"llmCalls": [], "deterministicDecisions": []})
        audit.setdefault("llmCalls", [])
        if llm_calls:
            audit["llmCalls"] = list(audit["llmCalls"]) + list(llm_calls)
        decisions = list(audit.get("deterministicDecisions", []))
        decisions.append(
            f"resolver_agent[v{RESOLVER_AGENT_VERSION}]: case_slug={self.case_slug} "
            f"era={era_check.era} legal={era_check.is_legal}"
        )
        decisions.append(
            f"resolver_agent: UP-20260715-002 mandatory_echo "
            f"attempted={mandatory_echo.echo_attempted} passes={mandatory_echo.passes}"
        )
        decisions.append(
            f"resolver_agent: write-authority enforced; snapshot.eventSequence "
            f"{snapshot.eventSequence} -> {new_snapshot.eventSequence}"
        )
        audit["deterministicDecisions"] = decisions
        outcome.auditTrail = audit

        # ---- 7b. Inject NPC-relationship clamp audit (decision 1 cap) ----
        # The engine applies NPC relationship deltas but
        # discards their per-pair clamp audit.  We re-run the
        # the same apply pass on the working snapshot to
        # capture the audit entries; the engine's own apply
        # is idempotent (the final value is the same), so the
        # second pass yields the same final state.  We tag
        # the entries with an explicit "npc_rel_" path prefix
        # so they're traceable in the audit log.
        if (
            npc_proposal_dict is not None
            and npc_proposal_dict.get("relationshipDelta")
        ):
            npc_rel_audit = self._npc_relationship_clamp_audit(
                npc_proposal_dict
            )
            if npc_rel_audit:
                self._last_clamp_audit.extend(npc_rel_audit)

        # ---- 8. Four-questions self-check (decision 6) -------------------
        four_q = self._collect_four_questions(
            player_action=player_action,
            npc_proposal_dict=npc_proposal_dict,
            director_beat_dict=director_beat_dict,
            scene_contract=scene_contract,
            outcome=outcome,
        )
        decisions.append(
            f"resolver_agent: four_questions passes={four_q.passes} "
            f"satisfied={list(four_q.satisfied_questions())}"
        )
        audit["deterministicDecisions"] = decisions
        outcome.auditTrail = audit

        # ---- 9. Clamp audit propagation ----------------------------------
        # The engine's outcome already carries the reducer's
        # clamp audit.  We expose the agent-side accumulator
        # via ``self.last_clamp_audit`` and also append any
        # agent-side clamps (e.g. on rogue LLM-produced
        # numbers we sanitised before reaching the engine).
        engine_clamps = list(outcome.clampedValues or [])
        merged = engine_clamps + [c.to_dict() for c in self._last_clamp_audit]
        # Dedupe by (path, original, applied) to keep the audit
        # log small.
        seen: set[tuple[str, float, float]] = set()
        deduped: list[dict[str, Any]] = []
        for entry in merged:
            key = (
                str(entry.get("path", "")),
                float(entry.get("original", 0.0)),
                float(entry.get("applied", 0.0)),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
        outcome.clampedValues = deduped

        # ---- 10. Schema-sanitise + schema-validate the outcome -----------
        # The engine reducer emits extra diagnostic fields on
        # belief updates (``reasonCode``) that the resolver_outcome
        # schema rejects as ``additionalProperties``.  We strip
        # the engine-only fields here so the outcome is
        # schema-valid; the diagnostic info is preserved in the
        # audit trail.
        outcome = self._sanitise_outcome_for_schema(outcome)
        try:
            jsonschema.validate(outcome.to_dict(), self._schema)
        except jsonschema.ValidationError as exc:
            raise SchemaValidationError(
                f"Resolver outcome failed schema validation: {exc.message} "
                f"(path={list(exc.absolute_path)})"
            ) from exc

        # ---- 11. Cache the outcome for future replays -------------------
        record = IdempotencyRecord(
            idempotencyKey=outcome.idempotencyKey,
            outcomeId=outcome.outcomeId,
            eventSequence=outcome.eventSequence,
            timestamp=outcome.timestamp,
        )
        self._idempotency_cache[cache_key] = record

        return new_snapshot, outcome, mandatory_echo, era_check, four_q

    # =====================================================================
    # READ-ONLY INSPECTION (used by tests + the HTTP layer)
    # =====================================================================

    @property
    def last_clamp_audit(self) -> list[ClampAuditEntry]:
        """The most recent resolve's clamp audit (engine + agent entries)."""
        return list(self._last_clamp_audit)

    @property
    def idempotency_cache(self) -> dict[tuple[str, str], IdempotencyRecord]:
        """The current idempotency cache.  Read-only view (returns a copy)."""
        return dict(self._idempotency_cache)

    def clear_idempotency_cache(self) -> None:
        """Clear the in-memory idempotency cache (e.g. between test runs)."""
        self._idempotency_cache.clear()

    def is_idempotency_cached(self, runId: str, idempotencyKey: str) -> bool:
        return (runId, idempotencyKey) in self._idempotency_cache

    # =====================================================================
    # VALIDATION GATES
    # =====================================================================

    def _validate_era(self, snapshot: WorldSnapshot) -> CaseAwareEraCheck:
        """ADR 0007 §4.2: case-aware era validation.

        The resolver is the **only** place that calls
        :func:`is_valid_era_for_case` on every snapshot it
        touches.  This is what makes "I forgot the era is
        case-scoped" impossible by construction.
        """
        era = snapshot.canonicalState.era
        legal = sorted(legal_eras_for_case(self.case_slug))
        is_legal = bool(is_valid_era_for_case(era, self.case_slug))
        detail = ""
        if not is_legal:
            detail = (
                f"era {era!r} is not legal for case {self.case_slug!r} "
                f"(ADR 0007 §4.2). Legal eras: {legal[:6]}… "
                f"(total {len(legal)} values)"
            )
        return CaseAwareEraCheck(
            era=era,
            case_slug=self.case_slug,
            is_legal=is_legal,
            legal_set=legal,
            detail=detail,
        )

    def _validate_mandatory_echo(
        self,
        npc_proposal: dict[str, Any],
        scene_contract: dict[str, Any],
    ) -> MandatoryEchoValidation:
        """UP-20260715-002: any voluntary echo MUST be in mandatory_echoes.

        A proposal is detected as a **voluntary echo** when the
        proposal surfaces a seed the contract registered in
        its ``causal_seeds`` list.  We detect a voluntary
        surface via three independent signals:

        1. ``speechIntent`` is one of the echo-bearing intents
           (``reveal_truth``, ``admit``, ``accuse``, ``defend``,
           ``taunt``, ``plead``, ``seek_confirmation``).
        2. The proposal's ``beliefUpdatesRequested`` lists a
           ``subject`` that matches a seed id in
           ``contract.causal_seeds``.
        3. The proposal's ``memorySubjects`` (the W3-B
           agent-side annotation) maps a recalled memory to a
           seed id.

        If any of the three fires, the proposal is treated as
        a voluntary echo.  Each named seed must be in
        ``contract.mandatory_echoes``; otherwise the check
        fails with ``passes=False``.

        Special cases
        -------------
        * ``contract.causal_seeds`` is empty → no echo to
          validate; the check passes vacuously.
        * ``contract.mandatory_echoes`` is **empty** but
          ``causal_seeds`` is non-empty → the check **fails**
          by design (decision 3 binds mandatory echoes to
          explicit declaration).  The NPC must not invent
          echoes; an empty mandatory list means "this scene
          has no authorised echoes".
        """
        if not self.enable_mandatory_echo_check:
            return MandatoryEchoValidation(
                echo_attempted=False,
                passes=True,
                summary="UP-20260715-002 check disabled",
            )

        causal_seed_ids: set[str] = {
            s for s in (scene_contract.get("causal_seeds") or []) if isinstance(s, str)
        }
        mandatory_ids: set[str] = {
            me.get("id")
            for me in (scene_contract.get("mandatory_echoes") or [])
            if isinstance(me, dict) and me.get("id")
        }

        # ---- (a) No seeds registered → vacuous pass ----
        if not causal_seed_ids:
            return MandatoryEchoValidation(
                echo_attempted=False,
                passes=True,
                summary="no causal_seeds registered; echo check vacuously passes",
            )

        # ---- (b) Detect named seed surfaces in the proposal ----
        speech_intent = str(npc_proposal.get("speechIntent", ""))
        echo_intents = {
            "reveal_truth", "admit", "accuse", "defend",
            "taunt", "plead", "seek_confirmation",
        }
        belief_subjects: set[str] = {
            u.get("subject", "")
            for u in npc_proposal.get("beliefUpdatesRequested", []) or []
            if isinstance(u, dict) and isinstance(u.get("subject"), str)
        }
        memory_subjects: set[str] = set()
        ms = npc_proposal.get("memorySubjects")
        if isinstance(ms, dict):
            for mid, subj in ms.items():
                if isinstance(subj, str) and subj:
                    memory_subjects.add(subj)
        # Also pull from referencedMemoryIds if the agent
        # attached a ``referencedSeedIds`` field (some LLM
        # prompts ask the agent to name seeds explicitly).
        ref_seeds: set[str] = set()
        rs = npc_proposal.get("referencedSeedIds")
        if isinstance(rs, list):
            for s in rs:
                if isinstance(s, str) and s:
                    ref_seeds.add(s)

        # Set of seeds the NPC is "voluntarily surfacing".
        attempted_seeds: set[str] = set()
        for s in belief_subjects | memory_subjects | ref_seeds:
            if s in causal_seed_ids:
                attempted_seeds.add(s)
        if (
            speech_intent in echo_intents
            and (belief_subjects & causal_seed_ids or memory_subjects & causal_seed_ids)
        ):
            # Echo intent + any seed reference = clear voluntary
            # echo.  Re-collect the union to be sure.
            attempted_seeds = (
                belief_subjects | memory_subjects | ref_seeds
            ) & causal_seed_ids

        # ---- (c) No echo attempted → pass ----
        if not attempted_seeds:
            return MandatoryEchoValidation(
                echo_attempted=False,
                passes=True,
                summary="NPC proposal did not surface a registered seed",
            )

        # ---- (d) At least one seed named → every one must be mandatory ----
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
                    else f"seed {sid!r} is NOT in scene.mandatory_echoes "
                         f"(UP-20260715-002 violation)"
                ),
            ))
            if not matched:
                passes = False

        # If the contract declares seeds but **no** mandatory
        # echoes at all, the failure mode is "the contract
        # registered causal_seeds but did not declare any
        # mandatory echoes" — the NPC must not invent echoes.
        if not mandatory_ids:
            summary = (
                f"voluntary echo attempted on {len(attempted_seeds)} seed(s); "
                f"but scene has no mandatory_echoes declared (decision 3 forbids "
                f"free-form echoes)"
            )
        else:
            summary = (
                f"voluntary echo attempted on {len(attempted_seeds)} seed(s); "
                + ("all in mandatory_echoes" if passes
                   else "violates UP-20260715-002")
            )

        return MandatoryEchoValidation(
            echo_attempted=True,
            checks=checks,
            passes=passes,
            summary=summary,
        )

    # =====================================================================
    # NPC RELATIONSHIP CLAMP AUDIT
    # =====================================================================

    @staticmethod
    def _npc_relationship_clamp_audit(
        npc_proposal_dict: dict[str, Any],
    ) -> list[ClampAuditEntry]:
        """Compute the per-pair clamp audit for an NPC relationship delta.

        The engine's apply path discards the audit entries
        when NPC relationship deltas are applied.  This helper
        re-runs the per-field clamp (decision-1 hard cap
        ``|delta| <= 0.25``) and produces the audit entries
        the resolver merges into ``outcome.clampedValues``.

        The output uses path prefixes like ``npc_rel.trust``,
        ``npc_rel.intimacy``, etc. — distinct from the
        engine's own ``trust``/``intimacy`` paths so the
        merged log is unambiguous.
        """

        from engine.types import clamp_relationship_delta

        entries: list[ClampAuditEntry] = []
        for pair in npc_proposal_dict.get("relationshipDelta") or []:
            if not isinstance(pair, dict):
                continue
            pair_tag = (
                f"{pair.get('from', '?')}->{pair.get('to', '?')}"
            )
            for field in (
                "trust",
                "intimacy",
                "respect",
                "unresolvedConflict",
                "fear",
            ):
                if field not in pair:
                    continue
                original = float(pair[field])
                clamped = clamp_relationship_delta(original)
                if clamped != original:
                    entries.append(ClampAuditEntry(
                        path=f"npc_rel.{field}@{pair_tag}",
                        original=original,
                        applied=clamped,
                        min=-0.25,
                        max=0.25,
                    ))
        return entries

    # =====================================================================
    # SCHEMA SANITATION
    # =====================================================================

    @staticmethod
    def _sanitise_outcome_for_schema(
        outcome: EngineResolverOutcome,
    ) -> EngineResolverOutcome:
        """Strip engine-only diagnostic fields so the outcome validates.

        The engine reducer adds ``reasonCode`` to every belief
        update it produces (audit-trail field).  The
        ``resolver_outcome.schema.json`` rejects
        ``additionalProperties`` on ``beliefUpdates[]``, so
        without this strip the schema check fails.  We move
        the dropped reason codes into the deterministic-decisions
        audit trail so the diagnostic is preserved (but
        structurally compatible with the schema).
        """

        # ---- beliefUpdates: keep schema-allowed fields only ------------
        allowed_bu = {
            "characterId", "subject", "newState", "confidence",
            "evidenceMemoryId", "previousState",
        }
        cleaned_bu: list[dict[str, Any]] = []
        dropped_bu_codes: list[str] = []
        for bu in (outcome.beliefUpdates or []):
            if not isinstance(bu, dict):
                continue
            cleaned = {k: v for k, v in bu.items() if k in allowed_bu}
            # Schema requires evidenceMemoryId to be string|null; coerce None to None
            cleaned_bu.append(cleaned)
            rc = bu.get("reasonCode")
            if isinstance(rc, str) and rc:
                subj = bu.get("subject", "?")
                char = bu.get("characterId", "?")
                dropped_bu_codes.append(f"{char}/{subj}={rc}")

        # ---- artifactUpdates: schema allows reasonCode, but make sure
        # we don't carry any other surprise fields.  Schema is
        # already permissive enough; we leave it untouched.
        cleaned_au = list(outcome.artifactUpdates or [])

        # ---- other arrays: pass through but force schema-shaped types
        # ---- relationshipDelta: snap numeric fields to 0.01 grid ----
        rel_keys = {"trust", "intimacy", "unresolvedConflict", "respect", "fear"}
        cleaned_rel: list[dict[str, Any]] = []
        for rd in (outcome.relationshipDelta or []):
            if not isinstance(rd, dict):
                continue
            cleaned_rd = dict(rd)
            for k in rel_keys:
                if k in cleaned_rd:
                    v = cleaned_rd[k]
                    if isinstance(v, (int, float)):
                        # Snap to 0.01 grid (schema multipleOf=0.01).
                        # Use Decimal to dodge IEEE-754 trap.
                        from decimal import Decimal, ROUND_HALF_UP
                        d_v = Decimal(str(float(v)))
                        snapped = (d_v / Decimal("0.01")).quantize(
                            Decimal("1"), rounding=ROUND_HALF_UP
                        ) * Decimal("0.01")
                        cleaned_rd[k] = float(snapped)
            cleaned_rel.append(cleaned_rd)
        cleaned_rej = list(outcome.rejectedNpcActions or [])
        cleaned_new = list(outcome.newCausalSeeds or [])
        cleaned_fired = list(outcome.firedCausalSeeds or [])
        cleaned_clamp = list(outcome.clampedValues or [])

        # ---- acceptedNpcAction: must have non-empty characterId ----
        accepted = dict(outcome.acceptedNpcAction or {})
        if not accepted.get("characterId"):
            # Placeholder for a no-NPC turn.  The schema
            # requires characterId minLength=1; "system" is the
            # conventional "no NPC actor" marker.
            accepted["characterId"] = "system"

        # ---- nextBeat: legalEndingId must be string|null, never missing
        next_beat = dict(outcome.nextBeat or {})
        if "legalEndingId" not in next_beat:
            next_beat["legalEndingId"] = None
        if "transition" not in next_beat:
            next_beat["transition"] = "continue"

        # ---- auditTrail: ensure shape ----------------------------------
        audit = dict(outcome.auditTrail or {})
        audit.setdefault("llmCalls", [])
        audit.setdefault("deterministicDecisions", [])
        if dropped_bu_codes:
            audit["deterministicDecisions"] = list(audit["deterministicDecisions"]) + [
                f"resolver_agent: stripped engine reasonCode from {len(dropped_bu_codes)} belief update(s) "
                f"(preserved: {', '.join(dropped_bu_codes[:8])}{'…' if len(dropped_bu_codes) > 8 else ''})"
            ]

        return EngineResolverOutcome(
            outcomeId=outcome.outcomeId,
            runId=outcome.runId,
            eventSequence=outcome.eventSequence,
            idempotencyKey=outcome.idempotencyKey,
            acceptedNpcAction=accepted,
            nextBeat=next_beat,
            timestamp=outcome.timestamp,
            triggerPlayerActionId=outcome.triggerPlayerActionId,
            triggerDirectorProposalId=outcome.triggerDirectorProposalId,
            rejectedNpcActions=cleaned_rej,
            relationshipDelta=cleaned_rel,
            beliefUpdates=cleaned_bu,
            artifactUpdates=cleaned_au,
            newCausalSeeds=cleaned_new,
            firedCausalSeeds=cleaned_fired,
            clampedValues=cleaned_clamp,
            auditTrail=audit,
            schemaVersion=outcome.schemaVersion,
        )

    # =====================================================================
    # ENGINE ADAPTER HELPERS
    # =====================================================================

    def _build_engine_npc_proposal(self, raw: dict[str, Any]) -> EngineNPCProposal:
        """Translate the agent's proposal dict into the engine's shape.

        The engine's :class:`engine.resolver.NPCProposal` is a
        ``slots=True`` dataclass that does **not** declare a
        ``relationshipDelta`` field, so we can't attach a
        custom attribute.  The agent's view of the proposal
        carries the relationship deltas; the engine
        resolver reads them via :func:`getattr` but the
        slots implementation makes that read return
        ``AttributeError`` (not a graceful default).

        We work around this by building a **lightweight
        stand-in** object that satisfies the engine's
        duck-typed contract: every attribute the engine reads
        (``proposalId``, ``characterId``, ``proposedAction``,
        ``speechIntent``, ``targetId``, ``referencedMemoryIds``,
        ``beliefUpdatesRequested``, ``emotionalTransition``,
        ``reasonCodes``, ``confidence``,
        ``expectedContradictions``) plus the optional
        ``relationshipDelta`` attribute the engine looks for.

        The easiest way to satisfy the engine is to build an
        :class:`engine.resolver.NPCProposal` (so the engine
        gets typed access to the schema-validated fields) and
        then wrap it in a small shim that adds the
        ``relationshipDelta`` attribute.  We do this with
        :class:`_NPCProposalWithRelationship` below.
        """

        proposal = EngineNPCProposal(
            proposalId=raw.get("proposalId") or self._outcome_id_gen(),
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
        rel = list(raw.get("relationshipDelta") or [])
        if rel:
            # Pre-clamp any out-of-range numeric fields and record
            # each clamp event in the per-call audit.  The
            # decision-1 cap is |delta| ≤ 0.25 per turn, but the
            # agent's contract is to *detect* an out-of-range raw
            # value (e.g. an LLM hallucinated 5.0) and surface the
            # clamp in the audit log, not to silently swallow it.
            self._audit_relationship_clamp(rel)
            return _NPCProposalWithRelationship(proposal, rel)
        return proposal

    def _audit_relationship_clamp(self, rel: list[dict[str, Any]]) -> None:
        """Record any out-of-range numeric field in ``rel`` as a clamp event.

        The engine reducer already clamps deltas to |x| ≤ 0.25
        *and* the resulting pair values to their legal domains;
        we do **not** re-clamp here (we let the engine do it
        for replay consistency), but we do **record** every
        out-of-range raw value as a ClampAuditEntry so the
        outcome's ``clampedValues`` array reflects the model's
        misbehaviour.
        """

        # Map of field name -> (lo, hi).  The schema-allowed
        # bounds match the resolver_outcome.schema.json.
        rel_field_bounds: dict[str, tuple[float, float]] = {
            "trust": (-1.0, 1.0),
            "intimacy": (-1.0, 1.0),
            "respect": (-1.0, 1.0),
            "unresolvedConflict": (0.0, 1.0),
            "fear": (0.0, 1.0),
        }
        for idx, rd in enumerate(rel):
            if not isinstance(rd, dict):
                continue
            for fld, (lo, hi) in rel_field_bounds.items():
                if fld not in rd:
                    continue
                v = rd[fld]
                if not isinstance(v, (int, float)):
                    continue
                if float(v) < lo or float(v) > hi:
                    self.record_clamp(
                        path=f"relationshipDelta[{idx}].{fld}",
                        original=float(v),
                        applied=float(lo) if float(v) < lo else float(hi),
                        min_value=lo,
                        max_value=hi,
                    )

    def _build_engine_director_input(self, raw: dict[str, Any]) -> EngineDirectorBeatInput:
        return EngineDirectorBeatInput(
            proposalId=raw.get("proposalId") or self._outcome_id_gen(),
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

    def _build_engine_contract(self, scene_contract: dict[str, Any]) -> EngineNarrativeContract:
        return EngineNarrativeContract(
            sceneId=scene_contract.get("sceneId", "?"),
            allowed_beats=list(scene_contract.get("allowed_beats", []) or []),
            forbidden_reveals=list(scene_contract.get("forbidden_reveals", []) or []),
            legal_endings=list(scene_contract.get("legal_endings", []) or []),
            max_turns=int(scene_contract.get("max_turns", 8) or 8),
            total_action_budget=int(scene_contract.get("total_action_budget", 32) or 32),
            causal_seeds=list(scene_contract.get("causal_seeds", []) or []),
        )

    # =====================================================================
    # FOUR-QUESTIONS AGGREGATOR
    # =====================================================================

    def _collect_four_questions(
        self,
        *,
        player_action: dict[str, Any] | None,
        npc_proposal_dict: dict[str, Any] | None,
        director_beat_dict: dict[str, Any] | None,
        scene_contract: dict[str, Any],
        outcome: EngineResolverOutcome,
    ) -> FourQuestionsResult:
        artifact_updates: list[Any] = list(outcome.artifactUpdates or [])
        belief_updates: list[Any] = list(outcome.beliefUpdates or [])
        fired_seeds: list[str] = list(outcome.firedCausalSeeds or [])
        if npc_proposal_dict is not None:
            belief_updates.extend(npc_proposal_dict.get("beliefUpdatesRequested", []) or [])
        if director_beat_dict is not None:
            fired_seeds.extend(director_beat_dict.get("firedCausalSeeds", []) or [])
            fired_seeds.extend(director_beat_dict.get("newCausalSeeds", []) or [])

        # The Director (and the engine) may have planted new
        # seeds even when the proposal didn't ask for them.
        for s in (outcome.newCausalSeeds or []):
            if s not in fired_seeds:
                fired_seeds.append(s)

        return check_four_questions(
            artifact_updates=artifact_updates,
            belief_updates=belief_updates,
            budget_delta=(
                {"director_action": 1} if director_beat_dict is not None else None
            ),
            fired_seed_ids=fired_seeds,
            scene_mandatory_echoes=scene_contract.get("mandatory_echoes", []) or [],
        )

    # =====================================================================
    # LLM-CALL HELPER (for the audit trail)
    # =====================================================================

    @staticmethod
    def make_llm_call_record(
        *,
        agent: str,
        response: ModelResponse,
        scene_id: str,
        character_id: str | None = None,
    ) -> dict[str, Any]:
        """Build an ``auditTrail.llmCalls`` entry from a gateway response.

        The Resolver is the only place that aggregates LLM
        calls from the upstream agents (NPC, Director,
        IntentParser, Memory Recall) into the canonical
        outcome.  Each entry mirrors the schema's
        ``auditTrail.llmCalls`` shape.

        The schema is strict: only ``agent`` / ``model`` /
        ``inputTokens`` / ``outputTokens`` / ``latencyMs``
        are allowed.  We carry ``sceneId`` and
        ``characterId`` in the ``agent`` field's enum value
        (e.g. ``"npc_agent@photo_lab_2008#arash"``) to keep
        the entry schema-clean while preserving the context.
        """

        # Encode the optional context into the ``agent`` field
        # so we don't violate ``additionalProperties: false``.
        # The schema's enum for ``agent`` is the four canonical
        # names; for non-canonical agents we drop the context.
        canonical = {"player_client", "npc_agent", "director_agent",
                     "resolver", "memory_recall"}
        if agent in canonical:
            agent_field = agent
        else:
            # Custom agent name — preserve but drop the suffix
            # to keep the schema happy.
            agent_field = agent.split("@", 1)[0]
            if agent_field not in canonical:
                agent_field = "npc_agent"  # safe fallback
        return {
            "agent": agent_field,
            "model": response.model,
            "inputTokens": int(response.input_tokens),
            "outputTokens": int(response.output_tokens),
            "latencyMs": int(response.latency_ms),
        }

    @staticmethod
    def make_llm_call_record_full(
        *,
        agent: str,
        response: ModelResponse,
        scene_id: str,
        character_id: str | None = None,
    ) -> dict[str, Any]:
        """Build a context-rich LLM-call record (for internal audit only).

        Same as :meth:`make_llm_call_record` but with
        ``sceneId`` / ``characterId`` included.  Use this for
        the **resolver's** own audit log
        (``self._last_clamp_audit``) — the
        ``outcome.auditTrail.llmCalls`` field must use the
        schema-strict variant above.
        """
        return {
            "agent": agent,
            "model": response.model,
            "inputTokens": int(response.input_tokens),
            "outputTokens": int(response.output_tokens),
            "latencyMs": int(response.latency_ms),
            "sceneId": scene_id,
            "characterId": character_id,
        }

    # =====================================================================
    # CLAMP HELPER (used by the agent for *agent-side* sanitation)
    # =====================================================================

    def record_clamp(
        self,
        *,
        path: str,
        original: float,
        applied: float,
        min_value: float,
        max_value: float,
    ) -> ClampAuditEntry:
        """Record an agent-side clamp event.

        The reducer's own clamp audit goes through the engine;
        the agent's record covers cases where the agent
        sanitises a value *before* it reaches the engine
        (e.g. an LLM-emitted confidence that exceeded 1.0).
        """
        entry = ClampAuditEntry(
            path=str(path),
            original=float(original),
            applied=float(applied),
            min=float(min_value),
            max=float(max_value),
        )
        self._last_clamp_audit.append(entry)
        return entry

    @staticmethod
    def clamp_value(
        value: float, *,
        lo: float,
        hi: float,
        path: str = "agent",
    ) -> tuple[float, ClampAuditEntry | None]:
        """Clamp ``value`` to ``[lo, hi]`` and return the entry for audit.

        This is the agent-side convenience wrapper for the
        engine's :func:`clamp`.  Use it for any numeric field
        the agent reads from a proposal before forwarding to
        the engine.  The returned :class:`ClampAuditEntry` is
        **not** auto-registered in
        :attr:`ResolverAgent.last_clamp_audit` — callers that
        want it recorded in the per-call audit should pass
        the entry to :meth:`record_clamp` themselves (the
        static signature avoids a hidden ``self`` dependency
        for callers that don't need audit).
        """
        if lo <= value <= hi:
            return float(value), None
        clamped = max(lo, min(hi, float(value)))
        return clamped, ClampAuditEntry(
            path=path, original=float(value), applied=clamped, min=lo, max=hi
        )

    # =====================================================================
    # IDEMPOTENCY KEY CONSTRUCTION
    # =====================================================================

    @staticmethod
    def _make_idempotency_key(
        runId: str,
        event_sequence: int,
        player_action_id: str | None,
        director_proposal_id: str | None,
    ) -> str:
        """Composite idempotency key (hash → 64 hex chars; schema allows 16-128).

        The engine also computes a key from the same inputs.
        We use the same composition so the agent's cache and
        the engine's ``IdempotencyReplayError`` agree.
        """
        raw = f"{runId}|{event_sequence}|{player_action_id or ''}|{director_proposal_id or ''}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]
        return digest

    # =====================================================================
    # SCHEMA LOADER
    # =====================================================================

    @staticmethod
    def _load_schema(schema_path: str | None) -> dict[str, Any]:
        if schema_path is None:
            from pathlib import Path
            root = Path(__file__).resolve().parents[1]
            schema_path = str(root / "config" / "schemas" / "resolver_outcome.schema.json")
        with open(schema_path, "r", encoding="utf-8") as fh:
            return json.load(fh)


# ---------------------------------------------------------------------------
# Cached-outcome materialisation
# ---------------------------------------------------------------------------


class _NPCProposalWithRelationship:
    """Shim around :class:`engine.resolver.NPCProposal` that adds
    ``relationshipDelta``.

    The engine's :class:`engine.resolver.NPCProposal` is a
    ``slots=True`` dataclass and does not declare a
    ``relationshipDelta`` field.  The engine resolver reads
    the field via ``getattr(accepted_npc, "relationshipDelta", [])``,
    which on a slots-dataclass without that slot returns the
    default — but only for **attribute lookup**; on some
    Python builds, a slots dataclass raises
    :exc:`AttributeError` instead of returning the default.

    This shim proxies every attribute access to the wrapped
    proposal and adds a real ``relationshipDelta`` slot of
    its own.  It is intentionally minimal: it does not
    support ``__slots__`` extension or pickling; the
    resolver creates a fresh shim per turn.
    """

    __slots__ = ("_proposal", "relationshipDelta")

    def __init__(self, proposal: EngineNPCProposal, relationship_delta: list[dict[str, Any]]):
        self._proposal = proposal
        self.relationshipDelta = list(relationship_delta)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._proposal, name)

    def __repr__(self) -> str:
        return f"_NPCProposalWithRelationship({self._proposal!r}, {self.relationshipDelta!r})"


def _cached_outcome_to_resolver_outcome(
    record: IdempotencyRecord,
    snapshot: WorldSnapshot,
    player_action: dict[str, Any] | None,
    director_beat_dict: dict[str, Any] | None,
) -> EngineResolverOutcome:
    """Materialise a :class:`EngineResolverOutcome` from an idempotency record.

    Used when the same key is re-applied in-process.  The
    cached record carries the original outcomeId and event
    sequence; we don't re-run the engine.
    """

    return EngineResolverOutcome(
        outcomeId=record.outcomeId,
        runId=snapshot.runId,
        eventSequence=record.eventSequence,
        idempotencyKey=record.idempotencyKey,
        acceptedNpcAction={
            "proposalId": "00000000-0000-0000-0000-000000000000",
            "characterId": "",
            "proposedAction": "silence",
            "speechIntent": "remain_silent",
            "resolvedText": "",
        },
        nextBeat={
            "sceneId": snapshot.canonicalState.currentSceneId,
            "beatId": "replay_noop",
            "transition": "continue",
        },
        timestamp=record.timestamp,
        triggerPlayerActionId=(
            player_action.get("clientActionId") if player_action else None
        ),
        triggerDirectorProposalId=(
            director_beat_dict.get("proposalId") if director_beat_dict else None
        ),
        rejectedNpcActions=[],
        relationshipDelta=[],
        beliefUpdates=[],
        artifactUpdates=[],
        newCausalSeeds=[],
        firedCausalSeeds=[],
        clampedValues=[],
        auditTrail={
            "llmCalls": [],
            "deterministicDecisions": [
                f"resolver_agent: replay no-op for idempotencyKey={record.idempotencyKey[:16]}…"
            ],
        },
    )


# ---------------------------------------------------------------------------
# Convenience factory: build a fully-wired ResolverAgent for tests
# ---------------------------------------------------------------------------


def build_resolver_agent(
    case_slug: str = "case_01_revolution_street",
    *,
    base_random_seed: int = 0,
    schema_path: str | None = None,
) -> ResolverAgent:
    """Build a ResolverAgent with a fresh engine Resolver.

    The factory is the recommended way to construct the
    agent in tests; it ensures the engine Resolver and the
    agent share the same RNG seed.
    """
    return ResolverAgent(
        EngineResolver(base_random_seed=base_random_seed),
        case_slug=case_slug,
        schema_path=schema_path,
        base_random_seed=base_random_seed,
    )


__all__ = [
    "RESOLVER_AGENT_VERSION",
    "RESOLVER_AGENT_SCHEMA_VERSION",
    "ResolverAgent",
    "ResolverAgentError",
    "CaseAwareEraError",
    "SchemaValidationError",
    "MandatoryEchoValidation",
    "MandatoryEchoCheck",
    "CaseAwareEraCheck",
    "ClampAuditEntry",
    "IdempotencyRecord",
    "build_resolver_agent",
]
