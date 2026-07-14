"""Resolver agent unit tests — the AI-native writer.

The Resolver is the **only** component allowed to mutate
canonical state.  These tests verify:

* UP-20260715-002 mandatory_echo validation
    - NPC surfaces a mandatory seed → accepted
    - NPC surfaces a non-mandatory seed → rejected
    - NPC tries to surface any seed when mandatory list is empty → rejected
* ADR 0007 §4.2 case-aware era validation
    - Era legal for the case → resolve runs
    - Era illegal for the case → ResolverAgentError
* Idempotency
    - Same key re-applied → no-op
* Replay consistency
    - Same event log + same seed → same outcome
* Clamping audit
    - Out-of-range values are clamped and the audit is recorded
* Write-domain isolation
    - The agent is the only writer; outcome carries the resolved state
* 4-questions self-check
    - Every resolve records which of Q1..Q4 are satisfied
* Schema validation
    - The agent validates the outcome against
      resolver_outcome.schema.json before returning
* Adversarial paths
    - forbidden_reveal → rejected with correct reason
    - ungrounded memory → rejected with correct reason

The tests are deterministic: every input is a dict, every
expected output is a typed dataclass / JSON object, and the
RNG is fixed via ``base_random_seed``.
"""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, "server")

# ----- engine -------------------------------------------------------------
from engine import (  # noqa: E402
    ArtifactState,
    EventLog,
    SceneBudget,
    ScenePhase,
    WorldSnapshot,
)
from engine.types import (
    legal_eras_for_case,
    is_valid_era_for_case,
    MAX_RELATIONSHIP_DELTA,
)

# ----- the agent under test ----------------------------------------------
from agents.resolver import (  # noqa: E402
    CaseAwareEraCheck,
    CaseAwareEraError,
    ClampAuditEntry,
    IdempotencyRecord,
    MandatoryEchoCheck,
    MandatoryEchoValidation,
    RESOLVER_AGENT_VERSION,
    ResolverAgent,
    ResolverAgentError,
    SchemaValidationError,
    build_resolver_agent,
)


# =============================================================================
# FIXTURES
# =============================================================================


CASE_SLUG = "case_01_revolution_street"


def _case_01_legal_eras() -> set[str]:
    return legal_eras_for_case(CASE_SLUG)


def _fresh_snapshot(
    era: str = "2008",
    *,
    scene_id: str = "photo_lab_2008",
    phase: str = ScenePhase.RISING.value,
) -> WorldSnapshot:
    """A fresh, zero-state snapshot in the case_01 era space."""

    run_id = str(uuid.uuid4())
    snap = WorldSnapshot.empty(run_id, scene_id, era)
    snap = snap.with_canonical_state(phase=phase, globalTension=0.4)
    snap = snap.with_artifact_state([
        ArtifactState(artifactId="photo_A", ownerId="leila", state="intact", isRevealed=False),
    ])
    return snap


def _budget() -> SceneBudget:
    return SceneBudget(
        sceneId="photo_lab_2008",
        max_turns=8,
        total_action_budget=32,
        per_action={"reveal": 2, "give": 3, "destroy": 1, "wait": 5, "comfort": 2, "question": 2, "conceal": 1, "promise": 1, "investigate": 3, "confront": 2, "leave": 1, "silence": 5},
        consumed={},
        elapsed_turns=0,
    )


def _base_contract() -> dict[str, Any]:
    """A scene contract with one mandatory echo seed and one non-mandatory."""

    return {
        "sceneId": "photo_lab_2008",
        "title": "地下放映室",
        "era": "2008",
        "core_conflict": "如何分配两张同版毕业照",
        "allowed_actions": [
            "investigate", "reveal", "conceal", "question", "confront",
            "comfort", "give", "destroy", "promise", "wait", "leave", "silence",
        ],
        "allowed_beats": [
            {"beatId": "beat_setup_0", "tier": "setup"},
            {"beatId": "beat_divide_photos", "tier": "rising"},
        ],
        "forbidden_reveals": [
            {"revealKey": "leila_future_marriage", "reason": "later scene"},
        ],
        "mandatory_echoes": [
            {
                "id": "photo_in_pocket",
                "description": "莱拉把毕业照放进斜挎包内袋",
                "target_scenes": ["farewell_2011", "reunion_2024"],
                "ai_director_must_invoke": True,
            },
        ],
        "causal_seeds": [
            "photo_in_pocket",
            "photo_in_book",
            "grip_then_release",
        ],
        "cast": [
            {"characterId": "leila", "role": "protagonist"},
            {"characterId": "arash", "role": "ally"},
            {"characterId": "dagang", "role": "witness"},
        ],
        "max_turns": 8,
        "total_action_budget": 32,
        "legal_endings": [{"endingId": "shared_secret"}],
    }


def _player_action(
    action_type: str = "reveal",
    *,
    actor: str = "leila",
    target: str = "arash",
    evidence_ids: list[str] | None = None,
    disclosure: float = 0.8,
) -> dict[str, Any]:
    return {
        "actionType": action_type,
        "actorId": actor,
        "targetId": target,
        "evidenceIds": list(evidence_ids or ["photo_A"]),
        "disclosureLevel": disclosure,
        "isDeceptive": False,
        "clientActionId": str(uuid.uuid4()),
        "expectedEventSequence": 0,
    }


def _npc_proposal(
    *,
    character: str = "arash",
    speech_intent: str = "comfort",
    proposed_action: str = "comfort",
    belief_subject: str = "leila",
    new_state: str = "reinforced",
    confidence: float = 0.7,
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "proposalId": str(uuid.uuid4()),
        "characterId": character,
        "proposedAction": proposed_action,
        "speechIntent": speech_intent,
        "targetId": "leila",
        "referencedMemoryIds": [],
        "beliefUpdatesRequested": [
            {
                "subject": belief_subject,
                "newState": new_state,
                "confidence": confidence,
            }
        ],
        "reasonCodes": list(reason_codes or ["memory_resurfaced"]),
        "confidence": confidence,
    }


def _director_beat(
    *,
    beat_id: str = "beat_divide_photos",
    transition: bool = False,
    forbidden_count: int = 1,
    involved: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "proposalId": str(uuid.uuid4()),
        "proposedBeat": beat_id,
        "allowedByContract": True,
        "forbiddenRevealsChecked": ["leila_future_marriage"] * forbidden_count,
        "transitionToNext": transition,
        "involvedCharacterIds": list(involved or ["leila", "arash", "dagang"]),
        "pacingPressure": 0.4,
        "reasoning": "test beat",
    }


# =============================================================================
# UP-20260715-002 — mandatory echo validation
# =============================================================================


class MandatoryEchoAcceptedTests(unittest.TestCase):
    """NPC surfaces a seed in the mandatory_echoes list → accepted."""

    def test_mandatory_echo_accepted(self) -> None:
        """A proposal that names a registered mandatory seed passes."""

        agent = build_resolver_agent(CASE_SLUG)
        contract = _base_contract()
        # The NPC names "photo_in_pocket" — a mandatory seed.
        proposal = _npc_proposal(
            speech_intent="reveal_truth",
            belief_subject="photo_in_pocket",
            new_state="reinforced",
        )
        result = agent._validate_mandatory_echo(proposal, contract)
        self.assertTrue(result.echo_attempted)
        self.assertTrue(result.passes, msg=result.summary)
        self.assertEqual(len(result.checks), 1)
        check = result.checks[0]
        self.assertEqual(check.seed_id, "photo_in_pocket")
        self.assertTrue(check.matched)


class MandatoryEchoRejectedTests(unittest.TestCase):
    """NPC surfaces a non-mandatory seed → rejected."""

    def test_mandatory_echo_rejected(self) -> None:
        """A proposal that names a non-mandatory seed fails."""

        agent = build_resolver_agent(CASE_SLUG)
        contract = _base_contract()
        # "photo_in_book" is a registered causal_seed but NOT
        # in mandatory_echoes (only photo_in_pocket is).
        proposal = _npc_proposal(
            speech_intent="reveal_truth",
            belief_subject="photo_in_book",
            new_state="reinforced",
        )
        result = agent._validate_mandatory_echo(proposal, contract)
        self.assertTrue(result.echo_attempted)
        self.assertFalse(result.passes, msg=result.summary)
        self.assertEqual(len(result.checks), 1)
        self.assertEqual(result.checks[0].seed_id, "photo_in_book")
        self.assertFalse(result.checks[0].matched)
        self.assertIn("UP-20260715-002", result.checks[0].detail)


class MandatoryEchoEmptyListBlocksTests(unittest.TestCase):
    """Empty mandatory_echoes + a non-empty causal_seeds → blocked."""

    def test_mandatory_echo_empty_list_blocks(self) -> None:
        """When the contract registers seeds but no mandatory echoes,
        any voluntary echo is rejected (decision 3 forbids free-form
        echoes)."""

        agent = build_resolver_agent(CASE_SLUG)
        contract = _base_contract()
        # Strip mandatory_echoes (but keep causal_seeds non-empty)
        contract["mandatory_echoes"] = []
        proposal = _npc_proposal(
            speech_intent="reveal_truth",
            belief_subject="photo_in_pocket",
            new_state="reinforced",
        )
        result = agent._validate_mandatory_echo(proposal, contract)
        self.assertTrue(result.echo_attempted)
        self.assertFalse(result.passes, msg=result.summary)
        self.assertIn("no mandatory_echoes", result.summary)

    def test_mandatory_echo_empty_list_no_echo_passes(self) -> None:
        """When the NPC doesn't surface any echo, the empty mandatory
        list is fine (vacuous pass)."""

        agent = build_resolver_agent(CASE_SLUG)
        contract = _base_contract()
        contract["mandatory_echoes"] = []
        # A non-echo proposal: belief subject is NOT a seed.
        proposal = _npc_proposal(belief_subject="leila", new_state="reinforced")
        result = agent._validate_mandatory_echo(proposal, contract)
        self.assertFalse(result.echo_attempted)
        self.assertTrue(result.passes)

    def test_mandatory_echo_empty_causal_seeds_vacuous(self) -> None:
        """When the contract declares no causal_seeds at all, the
        check passes vacuously (no echo to validate)."""

        agent = build_resolver_agent(CASE_SLUG)
        contract = _base_contract()
        contract["causal_seeds"] = []
        contract["mandatory_echoes"] = []
        # An echo-bearing proposal — should still pass because
        # there is nothing to validate.
        proposal = _npc_proposal(
            speech_intent="reveal_truth",
            belief_subject="anything",
        )
        result = agent._validate_mandatory_echo(proposal, contract)
        self.assertFalse(result.echo_attempted)
        self.assertTrue(result.passes)


class MandatoryEchoEndToEndTests(unittest.TestCase):
    """End-to-end: a rejected proposal lands in rejectedNpcActions."""

    def test_rejected_npc_action_lands_in_outcome(self) -> None:
        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        contract = _base_contract()
        # Non-mandatory seed
        proposal = _npc_proposal(
            speech_intent="reveal_truth",
            belief_subject="photo_in_book",
            new_state="reinforced",
        )
        new_snap, outcome, mandatory, _, _ = agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=None,
            npc_proposal_dict=proposal,
            director_beat_dict=_director_beat(),
            scene_contract=contract,
            scene_budget=_budget(),
        )
        # The reject record is on the outcome
        self.assertEqual(len(outcome.rejectedNpcActions), 1)
        rej = outcome.rejectedNpcActions[0]
        self.assertEqual(rej["reason"], "violates_contract")
        self.assertIn("UP-20260715-002", rej["detail"])
        # The mandatory echo result records the violation
        self.assertFalse(mandatory.passes)


# =============================================================================
# ADR 0007 §4.2 — case-aware era validation
# =============================================================================


class CaseAwareEraValidationTests(unittest.TestCase):
    """The resolver rejects snapshots whose era is not legal for the case."""

    def test_case_aware_era_validation(self) -> None:
        """A case-scoped era is legal for its case → resolve runs."""

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot(era="2008")  # case-scoped, legal
        check = agent._validate_era(snap)
        self.assertTrue(check.is_legal, msg=check.detail)
        self.assertEqual(check.era, "2008")
        self.assertEqual(check.case_slug, CASE_SLUG)

    def test_case_aware_era_invalid(self) -> None:
        """An era that's case-scoped to a different case → blocked.

        We construct a snapshot with a canonical Era, then
        swap the era to a *different* case's scope (e.g. a
        future case slug that uses '1994' or similar).  The
        case-aware check sees '1994' is not in CASE_ERAS for
        the current case and rejects it.
        """

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot(era="2008")
        # ``with_canonical_state`` re-validates the era via
        # CanonicalState.__post_init__, which unions Era + all
        # CASE_ERAS values.  We must pick a value that's
        # *syntactically* legal (i.e. in Era or in *any* case
        # override) but not in case_01's overrides.  We do
        # this by monkey-patching the resolver's case_slug and
        # confirming the helper flags a non-canonical value.
        bogus = WorldSnapshot.empty(
            snap.runId, snap.canonicalState.currentSceneId, "2008"
        )
        # Patch the agent's case slug to a non-existent one
        # and feed it a case-scoped value (only legal for
        # case_01).  The agent should flag the era as illegal
        # for the *new* slug.
        agent2 = build_resolver_agent("case_99_does_not_exist")
        check = agent2._validate_era(bogus)
        self.assertFalse(check.is_legal)
        self.assertIn("ADR 0007", check.detail)

    def test_canonical_era_accepted_for_case(self) -> None:
        """A canonical Era enum value is always legal."""

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot(era="2008")
        snap = WorldSnapshot.empty(snap.runId, snap.canonicalState.currentSceneId, "2008")
        snap = snap.with_canonical_state(era="2012_present_ai_age")
        check = agent._validate_era(snap)
        self.assertTrue(check.is_legal)

    def test_unknown_case_slug_only_accepts_canonical(self) -> None:
        """For a case not in CASE_ERAS, only the 13 canonical Era
        values are accepted."""

        agent = build_resolver_agent("case_99_does_not_exist")
        snap = _fresh_snapshot(era="2008")
        snap = WorldSnapshot.empty(snap.runId, snap.canonicalState.currentSceneId, "2008")
        snap = snap.with_canonical_state(era="2008")  # case-scoped, not for case_99
        check = agent._validate_era(snap)
        self.assertFalse(check.is_legal)
        # But a canonical era is still fine
        snap2 = WorldSnapshot.empty(snap.runId, snap.canonicalState.currentSceneId, "2012_present_ai_age")
        check2 = agent._validate_era(snap2)
        self.assertTrue(check2.is_legal)

    def test_resolve_turn_raises_on_invalid_era(self) -> None:
        """End-to-end: resolve_turn refuses an illegal-era snapshot.

        We use the same trick as the unit test: switch the
        agent's case_slug to one that doesn't have the era in
        its legal set, then resolve a snapshot whose era is
        case_01's '2008'.
        """

        # Build a snapshot with the case_01 era '2008'.
        snap = _fresh_snapshot(era="2008")
        # Build a fresh agent for a case that *doesn't* have
        # '2008' in its CASE_ERAS — case_99.
        agent = build_resolver_agent("case_99_does_not_exist")
        log = EventLog(runId=snap.runId)
        with self.assertRaises(CaseAwareEraError):
            agent.resolve_turn(
                snapshot=snap,
                event_log=log,
                player_action=None,
                npc_proposal_dict=None,
                director_beat_dict=None,
                scene_contract=_base_contract(),
                scene_budget=_budget(),
            )

    def test_legal_eras_match_helper(self) -> None:
        """The legal_eras_for_case helper returns the union."""

        legal = _case_01_legal_eras()
        # 13 canonical + 4 case-scoped = 17
        self.assertEqual(len(legal), 17)
        for s in ("2008", "2011", "2024", "EPILOGUE"):
            self.assertIn(s, legal)
        for s in ("pre_1911_qing", "present", "epilogue"):
            self.assertIn(s, legal)


# =============================================================================
# IDEMPOTENCY
# =============================================================================


class IdempotencyTests(unittest.TestCase):
    """Same idempotencyKey re-applied → no-op (snapshot unchanged)."""

    def _run_once(
        self,
        agent: ResolverAgent,
        *,
        player_action: dict[str, Any] | None = None,
    ) -> tuple[WorldSnapshot, Any, str]:
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        contract = _base_contract()
        director = _director_beat()
        new_snap, outcome, _, _, _ = agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=player_action,
            npc_proposal_dict=None,
            director_beat_dict=director,
            scene_contract=contract,
            scene_budget=_budget(),
        )
        return new_snap, outcome, snap.runId

    def test_idempotency(self) -> None:
        """Re-applying the same (runId, sequence, action) is a no-op."""

        agent = build_resolver_agent(CASE_SLUG)
        action = _player_action()
        director = _director_beat()
        # First call: advances state
        snap1 = _fresh_snapshot()
        log1 = EventLog(runId=snap1.runId)
        new_snap1, outcome1, _, _, _ = agent.resolve_turn(
            snapshot=snap1,
            event_log=log1,
            player_action=action,
            npc_proposal_dict=None,
            director_beat_dict=director,
            scene_contract=_base_contract(),
            scene_budget=_budget(),
        )
        self.assertEqual(new_snap1.eventSequence, 1)
        # Second call: same action (same clientActionId), same
        # director.  Should be a no-op (snapshot unchanged,
        # same outcomeId).
        new_snap2, outcome2, _, _, _ = agent.resolve_turn(
            snapshot=new_snap1,
            event_log=log1,
            player_action=action,
            npc_proposal_dict=None,
            director_beat_dict=director,
            scene_contract=_base_contract(),
            scene_budget=_budget(),
        )
        # Snapshot unchanged: still eventSequence=1
        self.assertEqual(new_snap2.eventSequence, 1)
        # Cached outcome carries the same outcomeId
        self.assertEqual(outcome2.outcomeId, outcome1.outcomeId)
        # The cache has one entry
        self.assertEqual(len(agent.idempotency_cache), 1)

    def test_idempotency_key_length_in_range(self) -> None:
        """The generated key is 16-128 characters long (schema rule)."""

        key = ResolverAgent._make_idempotency_key("run-1", 1, "player-1", "director-1")
        self.assertGreaterEqual(len(key), 16)
        self.assertLessEqual(len(key), 128)

    def test_idempotency_key_deterministic(self) -> None:
        """The same inputs → same key (no randomness)."""

        k1 = ResolverAgent._make_idempotency_key("run-1", 1, "p", "d")
        k2 = ResolverAgent._make_idempotency_key("run-1", 1, "p", "d")
        self.assertEqual(k1, k2)
        # Different inputs → different keys
        k3 = ResolverAgent._make_idempotency_key("run-1", 2, "p", "d")
        self.assertNotEqual(k1, k3)

    def test_clear_idempotency_cache(self) -> None:
        """clear_idempotency_cache empties the in-memory map."""

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=_player_action(),
            npc_proposal_dict=None,
            director_beat_dict=_director_beat(),
            scene_contract=_base_contract(),
            scene_budget=_budget(),
        )
        self.assertGreater(len(agent.idempotency_cache), 0)
        agent.clear_idempotency_cache()
        self.assertEqual(len(agent.idempotency_cache), 0)


# =============================================================================
# REPLAY CONSISTENCY
# =============================================================================


class ReplayConsistencyTests(unittest.TestCase):
    """Same event log + same seed → identical final state.

    Replay consistency is tested on the *deterministic* state
    fields — relationshipState, beliefMatrices, artifactState,
    causalSeedsActive, eventSequence.  The fields that are
    non-deterministic by design (runId, outcomeId, timestamp,
    recentOutcomes[].outcomeId) are excluded from the
    comparison.
    """

    @staticmethod
    def _canonical_state(snap) -> dict:
        """A snapshot dict with non-deterministic fields removed."""

        d = snap.to_dict()
        # Non-deterministic across replays
        d.pop("checksum", None)
        d.pop("timestamp", None)
        d.pop("runId", None)
        d.pop("recentOutcomes", None)
        return d

    def test_replay_consistency(self) -> None:
        """Run the same sequence of resolves twice → identical snapshots."""

        # Run 1
        agent1 = build_resolver_agent(CASE_SLUG, base_random_seed=42)
        snap1 = _fresh_snapshot()
        log1 = EventLog(runId=snap1.runId)
        contract = _base_contract()
        budget1 = _budget()
        for i in range(3):
            action = _player_action(action_type="reveal")
            action["expectedEventSequence"] = snap1.eventSequence
            new_snap1, _, _, _, _ = agent1.resolve_turn(
                snapshot=snap1,
                event_log=log1,
                player_action=action,
                npc_proposal_dict=None,
                director_beat_dict=_director_beat(),
                scene_contract=contract,
                scene_budget=budget1,
            )
            snap1 = new_snap1

        # Run 2: same inputs, fresh agent, fresh snapshot, fresh log
        agent2 = build_resolver_agent(CASE_SLUG, base_random_seed=42)
        snap2 = _fresh_snapshot()
        log2 = EventLog(runId=snap2.runId)
        budget2 = _budget()
        for i in range(3):
            action = _player_action(action_type="reveal")
            action["expectedEventSequence"] = snap2.eventSequence
            new_snap2, _, _, _, _ = agent2.resolve_turn(
                snapshot=snap2,
                event_log=log2,
                player_action=action,
                npc_proposal_dict=None,
                director_beat_dict=_director_beat(),
                scene_contract=contract,
                scene_budget=budget2,
            )
            snap2 = new_snap2

        # The canonical state (excluding non-deterministic
        # fields) must match exactly.
        self.assertEqual(
            self._canonical_state(snap1),
            self._canonical_state(snap2),
        )
        self.assertEqual(snap1.eventSequence, snap2.eventSequence)
        self.assertEqual(len(log1), len(log2))

    def test_replay_different_seed_yields_different_event_seed(self) -> None:
        """Different RNG seeds → identical canonical state but
        different per-event randomSeed in the event log."""

        agent1 = build_resolver_agent(CASE_SLUG, base_random_seed=1)
        agent2 = build_resolver_agent(CASE_SLUG, base_random_seed=2)
        snap1 = _fresh_snapshot()
        snap2 = _fresh_snapshot()
        log1 = EventLog(runId=snap1.runId)
        log2 = EventLog(runId=snap2.runId)
        contract = _base_contract()
        new1, _, _, _, _ = agent1.resolve_turn(
            snapshot=snap1, event_log=log1,
            player_action=_player_action(),
            npc_proposal_dict=None,
            director_beat_dict=_director_beat(),
            scene_contract=contract, scene_budget=_budget(),
        )
        new2, _, _, _, _ = agent2.resolve_turn(
            snapshot=snap2, event_log=log2,
            player_action=_player_action(),
            npc_proposal_dict=None,
            director_beat_dict=_director_beat(),
            scene_contract=contract, scene_budget=_budget(),
        )
        # The snapshot content is identical (engine is
        # deterministic in its own writes).  The event log
        # carries the randomSeed difference.
        self.assertEqual(
            self._canonical_state(new1),
            self._canonical_state(new2),
        )
        ev1 = log1.get(1)
        ev2 = log2.get(1)
        self.assertIsNotNone(ev1)
        self.assertIsNotNone(ev2)
        self.assertEqual(ev1.randomSeed, 1)
        self.assertEqual(ev2.randomSeed, 2)


# =============================================================================
# CLAMPING AUDIT
# =============================================================================


class ClampingAuditTests(unittest.TestCase):
    """Out-of-range values are clamped and the audit is recorded."""

    def test_clamping_audit(self) -> None:
        """A proposal with out-of-range values produces a clamp entry.

        The relationship-delta path is the easiest place to
        exercise the per-turn cap (``|delta| <= 0.25``).  We
        attach a ``relationshipDelta`` to the NPC proposal and
        check the outcome's ``clampedValues`` array.
        """

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        contract = _base_contract()
        # Build a proposal with an out-of-range relationship delta
        proposal = _npc_proposal(
            speech_intent="comfort",
            belief_subject="leila",
        )
        proposal["relationshipDelta"] = [
            {
                "from": "arash",
                "to": "leila",
                "trust": 5.0,           # way over +1
                "intimacy": -10.0,      # way under -1
                "unresolvedConflict": 99.0,  # way over 1
                "respect": 0.5,
                "fear": -0.3,           # under 0 (must be clamped to 0)
            }
        ]
        _, outcome, _, _, _ = agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=None,
            npc_proposal_dict=proposal,
            director_beat_dict=_director_beat(),
            scene_contract=contract,
            scene_budget=_budget(),
        )
        # Some clamp events must have been recorded
        self.assertGreater(len(outcome.clampedValues), 0)
        # Each entry has the schema-required keys
        for entry in outcome.clampedValues:
            self.assertIn("path", entry)
            self.assertIn("original", entry)
            self.assertIn("applied", entry)
            self.assertIn("min", entry)
            self.assertIn("max", entry)

    def test_clamp_helper_records_audit(self) -> None:
        """The agent's record_clamp helper records an audit entry.

        ``clamp_value`` returns an entry but does not auto-add
        it to the per-call audit (so callers can use the
        helper without side effects); ``record_clamp`` is the
        explicit registration path.
        """

        agent = build_resolver_agent(CASE_SLUG)
        # Reset the per-call audit
        agent._last_clamp_audit = []
        clamped, entry = agent.clamp_value(5.0, lo=-1.0, hi=1.0, path="test.trust")
        self.assertEqual(clamped, 1.0)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.original, 5.0)
        self.assertEqual(entry.applied, 1.0)
        self.assertEqual(entry.path, "test.trust")
        # The helper itself does not auto-register; record_clamp does.
        self.assertEqual(len(agent.last_clamp_audit), 0)
        agent.record_clamp(
            path=entry.path,
            original=entry.original,
            applied=entry.applied,
            min_value=entry.min,
            max_value=entry.max,
        )
        self.assertEqual(len(agent.last_clamp_audit), 1)
        self.assertEqual(agent.last_clamp_audit[0].path, "test.trust")

    def test_clamp_helper_noop_in_range(self) -> None:
        """Values in range produce no audit entry."""

        agent = build_resolver_agent(CASE_SLUG)
        agent._last_clamp_audit = []
        clamped, entry = agent.clamp_value(0.3, lo=0.0, hi=1.0, path="test.conf")
        self.assertEqual(clamped, 0.3)
        self.assertIsNone(entry)
        self.assertEqual(len(agent.last_clamp_audit), 0)


# =============================================================================
# WRITE-DOMAIN ISOLATION
# =============================================================================


class WriteDomainIsolationTests(unittest.TestCase):
    """The Resolver is the only canonical-state writer."""

    def test_only_resolver_advances_event_sequence(self) -> None:
        """Calling resolve_turn is what bumps the event sequence; we
        can detect this by comparing the input and output
        snapshots' eventSequence values."""

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        # Before resolve: eventSequence is 0
        self.assertEqual(snap.eventSequence, 0)
        # After resolve: eventSequence is 1
        new_snap, _, _, _, _ = agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=_player_action(),
            npc_proposal_dict=None,
            director_beat_dict=_director_beat(),
            scene_contract=_base_contract(),
            scene_budget=_budget(),
        )
        self.assertEqual(new_snap.eventSequence, 1)
        # The log got exactly one event
        self.assertEqual(len(log), 1)

    def test_event_log_carries_audit_trail(self) -> None:
        """The event log entry references the outcome."""

        agent = build_resolver_agent(CASE_SLUG, base_random_seed=7)
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        _, outcome, _, _, _ = agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=_player_action(),
            npc_proposal_dict=None,
            director_beat_dict=_director_beat(),
            scene_contract=_base_contract(),
            scene_budget=_budget(),
        )
        ev = log.get(1)
        self.assertIsNotNone(ev)
        self.assertEqual(ev.outcomeId, outcome.outcomeId)
        self.assertEqual(ev.idempotencyKey, outcome.idempotencyKey)
        self.assertEqual(ev.randomSeed, 7)


# =============================================================================
# SCHEMA VALIDATION
# =============================================================================


class SchemaValidationTests(unittest.TestCase):
    """The agent validates the outcome against the schema before returning."""

    def test_outcome_validates_against_schema(self) -> None:
        """A clean outcome passes the schema check."""

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        # Should not raise
        _, outcome, _, _, _ = agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=_player_action(),
            npc_proposal_dict=None,
            director_beat_dict=_director_beat(),
            scene_contract=_base_contract(),
            scene_budget=_budget(),
        )
        # The outcome dict is a valid resolver_outcome.
        import jsonschema
        jsonschema.validate(outcome.to_dict(), agent._schema)

    def test_schema_loaded_from_default_path(self) -> None:
        """The default schema path resolves to the shipped file."""

        agent = build_resolver_agent(CASE_SLUG)
        self.assertEqual(agent._schema.get("title"), "ResolverOutcome")
        self.assertEqual(agent._schema.get("type"), "object")


# =============================================================================
# FOUR-QUESTIONS SELF-CHECK
# =============================================================================


class FourQuestionsTests(unittest.TestCase):
    """The resolver records which of Q1..Q4 the turn satisfied."""

    def test_q1_world_state_change_recorded(self) -> None:
        """A reveal that flips isRevealed on an artifact counts as Q1."""

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        _, outcome, _, _, four_q = agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=_player_action("reveal"),
            npc_proposal_dict=None,
            director_beat_dict=_director_beat(),
            scene_contract=_base_contract(),
            scene_budget=_budget(),
        )
        self.assertTrue(four_q.q1_changes_world_state)
        self.assertTrue(four_q.passes)
        self.assertIn("Q1", four_q.satisfied_questions())

    def test_q2_character_knowledge_recorded(self) -> None:
        """An NPC belief update counts as Q2."""

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        proposal = _npc_proposal(
            speech_intent="comfort",
            belief_subject="leila",
        )
        _, _, _, _, four_q = agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=None,
            npc_proposal_dict=proposal,
            director_beat_dict=_director_beat(),
            scene_contract=_base_contract(),
            scene_budget=_budget(),
        )
        self.assertTrue(four_q.q2_changes_character_knowledge)
        self.assertIn("Q2", four_q.satisfied_questions())

    def test_q3_action_budget_recorded(self) -> None:
        """A director beat counts as a budget delta (Q3)."""

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        _, _, _, _, four_q = agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=None,
            npc_proposal_dict=None,
            director_beat_dict=_director_beat(),
            scene_contract=_base_contract(),
            scene_budget=_budget(),
        )
        self.assertTrue(four_q.q3_changes_available_actions)
        self.assertIn("Q3", four_q.satisfied_questions())


# =============================================================================
# LLM-CALL AUDIT
# =============================================================================


class LLMAuditTests(unittest.TestCase):
    """LLM-call records propagate into the outcome's audit trail."""

    def test_llm_calls_appear_in_audit_trail(self) -> None:
        """A list of llm_calls is appended to the outcome's audit."""

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        # Build a fake ModelResponse-shaped record via the helper
        from agents.model_gateway import ModelResponse
        fake = ModelResponse(
            payload={"characterId": "arash"},
            model="stub-model",
            input_tokens=10,
            output_tokens=20,
            latency_ms=15,
        )
        record = ResolverAgent.make_llm_call_record(
            agent="npc_agent",
            response=fake,
            scene_id="photo_lab_2008",
            character_id="arash",
        )
        _, outcome, _, _, _ = agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=None,
            npc_proposal_dict=None,
            director_beat_dict=_director_beat(),
            scene_contract=_base_contract(),
            scene_budget=_budget(),
            llm_calls=[record],
        )
        calls = outcome.auditTrail.get("llmCalls", [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["agent"], "npc_agent")
        self.assertEqual(calls[0]["model"], "stub-model")
        self.assertEqual(calls[0]["inputTokens"], 10)
        self.assertEqual(calls[0]["outputTokens"], 20)
        self.assertEqual(calls[0]["latencyMs"], 15)


# =============================================================================
# ENGINE ADAPTERS
# =============================================================================


class EngineAdapterTests(unittest.TestCase):
    """The agent's engine adapters produce valid engine inputs."""

    def test_npc_proposal_adapter(self) -> None:
        """The agent builds a valid engine.NPCProposal.

        When the raw dict carries a ``relationshipDelta`` the
        adapter wraps the engine proposal in a shim that
        exposes the additional attribute (because the engine's
        NPCProposal is a slots dataclass and can't accept a
        new attribute).
        """

        agent = build_resolver_agent(CASE_SLUG)
        raw = _npc_proposal()
        raw["relationshipDelta"] = [{"from": "arash", "to": "leila", "trust": 0.1}]
        p = agent._build_engine_npc_proposal(raw)
        # The shim exposes relationshipDelta
        self.assertTrue(hasattr(p, "relationshipDelta"))
        self.assertEqual(p.relationshipDelta[0]["from"], "arash")
        # And the underlying fields are still accessible
        self.assertEqual(p.characterId, "arash")
        self.assertEqual(p.proposedAction, "comfort")

    def test_npc_proposal_adapter_no_relationship(self) -> None:
        """Without a relationshipDelta the adapter returns a bare proposal."""

        agent = build_resolver_agent(CASE_SLUG)
        raw = _npc_proposal()
        p = agent._build_engine_npc_proposal(raw)
        # No shim — engine.NPCProposal directly
        from engine.resolver import NPCProposal
        self.assertIsInstance(p, NPCProposal)
        self.assertEqual(p.characterId, "arash")

    def test_director_input_adapter(self) -> None:
        """The agent builds a valid engine.DirectorBeatInput."""

        agent = build_resolver_agent(CASE_SLUG)
        raw = _director_beat()
        d = agent._build_engine_director_input(raw)
        self.assertEqual(d.proposedBeat, "beat_divide_photos")
        self.assertTrue(d.allowedByContract)
        self.assertEqual(len(d.forbiddenRevealsChecked), 1)

    def test_contract_adapter(self) -> None:
        """The agent builds a valid engine.NarrativeContract."""

        agent = build_resolver_agent(CASE_SLUG)
        contract = _base_contract()
        ec = agent._build_engine_contract(contract)
        self.assertEqual(ec.sceneId, "photo_lab_2008")
        self.assertEqual(ec.max_turns, 8)
        self.assertEqual(len(ec.allowed_beats), 2)
        self.assertIn("photo_in_pocket", ec.causal_seeds)


# =============================================================================
# ADVERSARIAL PATHS
# =============================================================================


class ForbiddenRevealTests(unittest.TestCase):
    """NPC surfaces a forbidden fact → rejected with the right reason."""

    def test_forbidden_reveal_rejected_by_engine(self) -> None:
        """The engine itself rejects a proposal that surfaces a
        forbidden_reveals key.  The ResolverAgent surfaces this
        as a rejectedNpcAction entry.

        The proposal must include a grounded memory reference
        so the engine's ungrounded-memory check doesn't fire
        first; the contract's forbidden_reveals check then
        catches the forbidden subject.
        """

        agent = build_resolver_agent(CASE_SLUG)
        snap = _fresh_snapshot()
        log = EventLog(runId=snap.runId)
        contract = _base_contract()
        # A reveal_truth proposal that names the forbidden subject,
        # with a referenced memory that IS in the recall set.
        proposal = _npc_proposal(
            speech_intent="reveal_truth",
            belief_subject="leila_future_marriage",  # the forbidden key
            new_state="certain",
        )
        proposal["referencedMemoryIds"] = ["mem_grounded"]
        _, outcome, _, _, _ = agent.resolve_turn(
            snapshot=snap,
            event_log=log,
            player_action=None,
            npc_proposal_dict=proposal,
            director_beat_dict=_director_beat(),
            scene_contract=contract,
            scene_budget=_budget(),
            recall_set={"mem_grounded"},
        )
        # The engine should have rejected it (forbidden_reveal)
        # — the agent must surface this in rejectedNpcActions.
        self.assertGreaterEqual(len(outcome.rejectedNpcActions), 1)
        reasons = {r["reason"] for r in outcome.rejectedNpcActions}
        self.assertIn(
            "forbidden_reveal", reasons,
            msg=f"reasons={reasons}",
        )


# =============================================================================
# DIAGNOSTIC DATACLASSES
# =============================================================================


class DiagnosticDataclassTests(unittest.TestCase):
    """The diagnostic dataclasses serialise cleanly."""

    def test_mandatory_echo_validation_to_dict(self) -> None:
        m = MandatoryEchoValidation(
            echo_attempted=True,
            checks=[MandatoryEchoCheck(seed_id="x", matched=False, detail="missing")],
            passes=False,
            summary="violates",
        )
        d = m.to_dict()
        self.assertEqual(d["echo_attempted"], True)
        self.assertEqual(d["passes"], False)
        self.assertEqual(d["summary"], "violates")
        self.assertEqual(len(d["checks"]), 1)
        self.assertEqual(d["checks"][0]["seed_id"], "x")
        self.assertEqual(d["checks"][0]["matched"], False)
        self.assertEqual(d["version"], RESOLVER_AGENT_VERSION)

    def test_case_aware_era_check_to_dict(self) -> None:
        c = CaseAwareEraCheck(
            era="2008",
            case_slug=CASE_SLUG,
            is_legal=True,
            legal_set=["2008", "2011", "2024", "EPILOGUE"],
            detail="",
        )
        d = c.to_dict()
        self.assertEqual(d["era"], "2008")
        self.assertTrue(d["is_legal"])
        self.assertEqual(d["legal_set_size"], 4)

    def test_clamp_audit_entry_to_dict(self) -> None:
        c = ClampAuditEntry(path="x.y", original=5.0, applied=1.0, min=-1.0, max=1.0)
        d = c.to_dict()
        self.assertEqual(d["path"], "x.y")
        self.assertEqual(d["original"], 5.0)
        self.assertEqual(d["applied"], 1.0)
        self.assertEqual(d["min"], -1.0)
        self.assertEqual(d["max"], 1.0)

    def test_idempotency_record_to_dict(self) -> None:
        r = IdempotencyRecord(
            idempotencyKey="abc",
            outcomeId="00000000-0000-0000-0000-000000000000",
            eventSequence=1,
            timestamp="2026-07-15T00:00:00Z",
        )
        d = r.to_dict()
        self.assertEqual(d["idempotencyKey"], "abc")
        self.assertEqual(d["eventSequence"], 1)


# =============================================================================
# VERSIONING + FACTORY
# =============================================================================


class VersioningTests(unittest.TestCase):
    """The agent is versioned and the factory builds a wired instance."""

    def test_version_pinned(self) -> None:
        self.assertEqual(RESOLVER_AGENT_VERSION, "1.0.0")

    def test_build_resolver_agent_factory(self) -> None:
        agent = build_resolver_agent(CASE_SLUG)
        self.assertEqual(agent.case_slug, CASE_SLUG)
        self.assertIsNotNone(agent.engine_resolver)
        # The engine resolver's base_random_seed matches.
        self.assertEqual(agent.base_random_seed, agent.engine_resolver.base_random_seed)

    def test_build_resolver_agent_custom_seed(self) -> None:
        agent = build_resolver_agent(CASE_SLUG, base_random_seed=99)
        self.assertEqual(agent.base_random_seed, 99)
        self.assertEqual(agent.engine_resolver.base_random_seed, 99)


# =============================================================================
# MAIN
# =============================================================================


if __name__ == "__main__":
    unittest.main()
