"""Unit tests for the state-machine invariant checker.

The brief lists ten invariants (I1..I10); this suite tests
each one independently and the orchestrator
:func:`check_all_invariants`.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.safety.invariant_checker import (  # noqa: E402
    InvariantCheckInput,
    InvariantReport,
    InvariantViolation,
    check_all_invariants,
    check_artifact_location_uniqueness,
    check_atomic_write,
    check_event_log_idempotency,
    check_knowledge_grounded_in_evidence,
    check_no_action_by_inactive_character,
    check_no_entitlement_fabrication,
    check_no_forbidden_secret_leak,
    check_objective_facts_immutability,
    check_replay_determinism,
    check_relationship_values_in_range,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _clean_snapshot() -> dict:
    return {
        "runId": "00000000-0000-4000-8000-000000000001",
        "eventSequence": 1,
        "canonicalState": {
            "currentSceneId": "photo_lab_2008",
            "era": "2008",
            "turnIndex": 1,
            "phase": "rising",
            "cast": ["leila", "arash"],
        },
        "relationshipState": [
            {
                "from": "leila",
                "to": "arash",
                "trust": 0.5,
                "intimacy": 0.3,
                "unresolvedConflict": 0.1,
                "respect": 0.4,
                "fear": 0.0,
            }
        ],
        "artifactState": [
            {
                "artifactId": "photo_A",
                "ownerId": "leila",
                "state": "intact",
                "isRevealed": False,
                "location": "leila_pocket",
            }
        ],
        "beliefMatrices": [
            {
                "characterId": "leila",
                "objective_facts": [
                    {
                        "factId": "fact_1",
                        "description": "A fact",
                        "establishedAt": 1,
                        "isContested": False,
                    }
                ],
                "character_knowledge": [
                    {
                        "subject": "photo_A",
                        "belief_state": "certain",
                        "confidence": 0.9,
                        "evidenceMemoryIds": ["mem_1"],
                    }
                ],
                "character_memories": [],
                "hidden_secrets": [],
            }
        ],
        "event_log": [],
        "recentOutcomes": [],
    }


def _clean_event_log() -> list[dict]:
    return [
        {
            "sequence": 1,
            "actorId": "leila",
            "idempotencyKey": "k1",
            "actionPayload": {"clientActionId": "caid_1"},
        }
    ]


# ---------------------------------------------------------------------------
# I1: objective facts immutability
# ---------------------------------------------------------------------------


class ObjectiveFactsImmutabilityTests(unittest.TestCase):
    def test_clean_fact_passes(self) -> None:
        violations = check_objective_facts_immutability(_clean_snapshot())
        self.assertEqual(violations, [])

    def test_missing_factId_caught(self) -> None:
        snap = _clean_snapshot()
        snap["beliefMatrices"][0]["objective_facts"][0]["factId"] = ""
        violations = check_objective_facts_immutability(snap)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].invariant_id, "I1")
        self.assertIn("factId", violations[0].path)

    def test_negative_establishedAt_caught(self) -> None:
        snap = _clean_snapshot()
        snap["beliefMatrices"][0]["objective_facts"][0]["establishedAt"] = -1
        violations = check_objective_facts_immutability(snap)
        self.assertEqual(len(violations), 1)
        self.assertIn("establishedAt", violations[0].path)


# ---------------------------------------------------------------------------
# I2: knowledge is grounded in evidence
# ---------------------------------------------------------------------------


class KnowledgeGroundedTests(unittest.TestCase):
    def test_high_confidence_with_evidence_passes(self) -> None:
        violations = check_knowledge_grounded_in_evidence(_clean_snapshot())
        self.assertEqual(violations, [])

    def test_high_confidence_without_evidence_fails(self) -> None:
        snap = _clean_snapshot()
        snap["beliefMatrices"][0]["character_knowledge"].append({
            "subject": "arash_secret",
            "belief_state": "certain",
            "confidence": 0.9,
            "evidenceMemoryIds": [],
        })
        violations = check_knowledge_grounded_in_evidence(snap)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].invariant_id, "I2")
        self.assertIn("arash_secret", violations[0].detail)

    def test_low_confidence_without_evidence_passes(self) -> None:
        # Confidence 0.4 with no evidence is allowed ("feels something")
        snap = _clean_snapshot()
        snap["beliefMatrices"][0]["character_knowledge"].append({
            "subject": "vague",
            "belief_state": "uncertain",
            "confidence": 0.4,
            "evidenceMemoryIds": [],
        })
        violations = check_knowledge_grounded_in_evidence(snap)
        self.assertEqual(violations, [])


# ---------------------------------------------------------------------------
# I3: artifact location uniqueness
# ---------------------------------------------------------------------------


class ArtifactLocationUniquenessTests(unittest.TestCase):
    def test_clean_passes(self) -> None:
        violations = check_artifact_location_uniqueness(_clean_snapshot())
        self.assertEqual(violations, [])

    def test_empty_location_passes(self) -> None:
        snap = _clean_snapshot()
        snap["artifactState"][0]["location"] = None
        violations = check_artifact_location_uniqueness(snap)
        self.assertEqual(violations, [])

    def test_too_long_location_caught(self) -> None:
        snap = _clean_snapshot()
        snap["artifactState"][0]["location"] = "x" * 200  # > 128 chars
        violations = check_artifact_location_uniqueness(snap)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].invariant_id, "I3")


# ---------------------------------------------------------------------------
# I4: no action by dead / absent characters
# ---------------------------------------------------------------------------


class InactiveCharacterTests(unittest.TestCase):
    def test_active_character_passes(self) -> None:
        snap = _clean_snapshot()
        log = _clean_event_log()
        violations = check_no_action_by_inactive_character(snap, log)
        self.assertEqual(violations, [])

    def test_dead_character_blocked(self) -> None:
        snap = _clean_snapshot()
        snap["canonicalState"]["casualties"] = ["leila"]
        log = _clean_event_log()  # actorId=leila
        violations = check_no_action_by_inactive_character(snap, log)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].invariant_id, "I4")
        self.assertIn("leila", violations[0].detail)

    def test_not_in_cast_blocked(self) -> None:
        snap = _clean_snapshot()
        snap["canonicalState"]["cast"] = ["arash"]
        log = _clean_event_log()  # actorId=leila
        violations = check_no_action_by_inactive_character(snap, log)
        self.assertEqual(len(violations), 1)
        self.assertIn("not in cast", violations[0].detail)

    def test_system_actor_always_allowed(self) -> None:
        snap = _clean_snapshot()
        snap["canonicalState"]["cast"] = ["arash"]
        log = [{"sequence": 1, "actorId": "system", "idempotencyKey": "k1"}]
        violations = check_no_action_by_inactive_character(snap, log)
        self.assertEqual(violations, [])


# ---------------------------------------------------------------------------
# I5: relationship values in legal range
# ---------------------------------------------------------------------------


class RelationshipRangeTests(unittest.TestCase):
    def test_clean_passes(self) -> None:
        violations = check_relationship_values_in_range(_clean_snapshot())
        self.assertEqual(violations, [])

    def test_trust_above_max_caught(self) -> None:
        snap = _clean_snapshot()
        snap["relationshipState"][0]["trust"] = 1.5
        violations = check_relationship_values_in_range(snap)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].invariant_id, "I5")
        self.assertIn("trust", violations[0].path)

    def test_intimacy_below_min_caught(self) -> None:
        snap = _clean_snapshot()
        snap["relationshipState"][0]["intimacy"] = -1.5
        violations = check_relationship_values_in_range(snap)
        self.assertEqual(len(violations), 1)
        self.assertIn("intimacy", violations[0].path)

    def test_unresolved_conflict_negative_caught(self) -> None:
        snap = _clean_snapshot()
        snap["relationshipState"][0]["unresolvedConflict"] = -0.1
        violations = check_relationship_values_in_range(snap)
        self.assertEqual(len(violations), 1)
        self.assertIn("unresolvedConflict", violations[0].path)

    def test_fear_above_one_caught(self) -> None:
        snap = _clean_snapshot()
        snap["relationshipState"][0]["fear"] = 1.5
        violations = check_relationship_values_in_range(snap)
        self.assertEqual(len(violations), 1)

    def test_non_finite_value_caught(self) -> None:
        snap = _clean_snapshot()
        snap["relationshipState"][0]["trust"] = float("inf")
        violations = check_relationship_values_in_range(snap)
        self.assertEqual(len(violations), 1)
        self.assertIn("finite", violations[0].detail)

    def test_non_numeric_value_caught(self) -> None:
        snap = _clean_snapshot()
        snap["relationshipState"][0]["trust"] = "high"
        violations = check_relationship_values_in_range(snap)
        self.assertEqual(len(violations), 1)


# ---------------------------------------------------------------------------
# I6: no secret leak
# ---------------------------------------------------------------------------


class SecretLeakTests(unittest.TestCase):
    def test_no_reveals_declared_passes(self) -> None:
        violations = check_no_forbidden_secret_leak(_clean_snapshot(), [])
        self.assertEqual(violations, [])

    def test_clean_recent_outcomes_passes(self) -> None:
        snap = _clean_snapshot()
        snap["recentOutcomes"] = [{"outcomeId": "x", "eventSequence": 1, "timestamp": "2024"}]
        violations = check_no_forbidden_secret_leak(snap, ["leila_future_marriage"])
        self.assertEqual(violations, [])

    def test_leak_caught(self) -> None:
        snap = _clean_snapshot()
        # recentOutcomes doesn't normally carry text; but the invariant
        # checks the *textual* content of any string field other than
        # timestamp.  This catches a future extension.
        snap["recentOutcomes"] = [{
            "outcomeId": "x",
            "eventSequence": 1,
            "timestamp": "2024",
            "description": "leila_future_marriage confirmed",
        }]
        violations = check_no_forbidden_secret_leak(snap, ["leila_future_marriage"])
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].invariant_id, "I6")


# ---------------------------------------------------------------------------
# I7: no entitlement fabrication
# ---------------------------------------------------------------------------


class EntitlementFabricationTests(unittest.TestCase):
    def test_clean_payload_passes(self) -> None:
        payload = {"runId": "x", "text": "clean"}
        violations = check_no_entitlement_fabrication(payload)
        self.assertEqual(violations, [])

    def test_isFree_caught(self) -> None:
        violations = check_no_entitlement_fabrication({"isFree": True})
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].invariant_id, "I7")

    def test_price_caught(self) -> None:
        violations = check_no_entitlement_fabrication({"price": 25})
        self.assertEqual(len(violations), 1)

    def test_credits_caught(self) -> None:
        violations = check_no_entitlement_fabrication({"credits": 100})
        self.assertEqual(len(violations), 1)

    def test_tier_caught(self) -> None:
        violations = check_no_entitlement_fabrication({"tier": "premium"})
        self.assertEqual(len(violations), 1)

    def test_nested_entitlement_caught(self) -> None:
        payload = {"content": {"isPaid": True}}
        violations = check_no_entitlement_fabrication(payload)
        self.assertEqual(len(violations), 1)
        self.assertIn("isPaid", violations[0].path)

    def test_list_of_entitlement_caught(self) -> None:
        payload = {"items": [{"price": 9.99}, {"price": 19.99}]}
        violations = check_no_entitlement_fabrication(payload)
        self.assertEqual(len(violations), 2)


# ---------------------------------------------------------------------------
# I8: replay determinism
# ---------------------------------------------------------------------------


class ReplayDeterminismTests(unittest.TestCase):
    def test_identical_snapshots_pass(self) -> None:
        snap = _clean_snapshot()
        violations = check_replay_determinism(snap, snap)
        self.assertEqual(violations, [])

    def test_different_snapshots_fail(self) -> None:
        snap = _clean_snapshot()
        other = dict(snap)
        other["eventSequence"] = 99
        violations = check_replay_determinism(snap, other)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].invariant_id, "I8")

    def test_timestamp_differences_ignored(self) -> None:
        snap = _clean_snapshot()
        snap["timestamp"] = "2024-01-01T00:00:00Z"
        snap["checksum"] = "x" * 64
        other = dict(snap)
        other["timestamp"] = "2024-01-01T00:00:01Z"
        other["checksum"] = "y" * 64
        violations = check_replay_determinism(snap, other)
        self.assertEqual(violations, [])


# ---------------------------------------------------------------------------
# I9: atomic write
# ---------------------------------------------------------------------------


class AtomicWriteTests(unittest.TestCase):
    def test_matching_sequence_passes(self) -> None:
        snap = _clean_snapshot()
        log = _clean_event_log()  # last sequence = 1
        # _clean_snapshot has eventSequence=1
        violations = check_atomic_write(snap, log)
        self.assertEqual(violations, [])

    def test_mismatch_caught(self) -> None:
        snap = _clean_snapshot()
        snap["eventSequence"] = 0  # but log has 1
        log = _clean_event_log()
        violations = check_atomic_write(snap, log)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].invariant_id, "I9")

    def test_partial_snapshot_blocked(self) -> None:
        snap = _clean_snapshot()
        snap["partial"] = True
        violations = check_atomic_write(snap, _clean_event_log())
        self.assertEqual(len(violations), 1)
        self.assertIn("partial", violations[0].rule)

    def test_empty_log_passes(self) -> None:
        snap = _clean_snapshot()
        snap["eventSequence"] = 0
        violations = check_atomic_write(snap, [])
        self.assertEqual(violations, [])


# ---------------------------------------------------------------------------
# I10: event log idempotency
# ---------------------------------------------------------------------------


class EventLogIdempotencyTests(unittest.TestCase):
    def test_unique_keys_pass(self) -> None:
        log = [
            {"sequence": 1, "actorId": "leila", "idempotencyKey": "k1"},
            {"sequence": 2, "actorId": "arash", "idempotencyKey": "k2"},
        ]
        violations = check_event_log_idempotency(log)
        self.assertEqual(violations, [])

    def test_duplicate_keys_caught(self) -> None:
        log = [
            {"sequence": 1, "actorId": "leila", "idempotencyKey": "k1"},
            {"sequence": 2, "actorId": "arash", "idempotencyKey": "k1"},
        ]
        violations = check_event_log_idempotency(log)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].invariant_id, "I10")
        self.assertEqual(violations[0].offending_value, "k1")

    def test_missing_key_caught(self) -> None:
        log = [
            {"sequence": 1, "actorId": "leila", "idempotencyKey": ""},
        ]
        violations = check_event_log_idempotency(log)
        self.assertEqual(len(violations), 1)
        self.assertIn("missing", violations[0].detail)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class OrchestratorTests(unittest.TestCase):
    def test_clean_snapshot_passes_all(self) -> None:
        snap = _clean_snapshot()
        log = _clean_event_log()
        inp = InvariantCheckInput(
            snapshot=snap, event_log=log, payload=None, forbidden_reveals=[]
        )
        r = check_all_invariants(inp)
        self.assertTrue(r.passed, r.to_human_readable())
        self.assertEqual(r.violations, [])
        self.assertEqual(r.summary["total"], 0)

    def test_dirty_snapshot_fails_with_violations(self) -> None:
        snap = _clean_snapshot()
        # Trigger I2 (high confidence, no evidence)
        snap["beliefMatrices"][0]["character_knowledge"].append({
            "subject": "arash_secret",
            "belief_state": "certain",
            "confidence": 0.9,
            "evidenceMemoryIds": [],
        })
        # Trigger I5 (trust out of range)
        snap["relationshipState"][0]["trust"] = 2.0
        # Trigger I7 (entitlement)
        payload = {"isPaid": True}
        # Trigger I10 (duplicate key)
        log = _clean_event_log() * 2
        inp = InvariantCheckInput(
            snapshot=snap, event_log=log, payload=payload
        )
        r = check_all_invariants(inp)
        self.assertFalse(r.passed)
        self.assertIn("I2", r.summary)
        self.assertIn("I5", r.summary)
        self.assertIn("I7", r.summary)
        self.assertIn("I10", r.summary)
        self.assertGreaterEqual(r.summary["total"], 4)

    def test_to_human_readable(self) -> None:
        snap = _clean_snapshot()
        snap["relationshipState"][0]["trust"] = 99.0
        inp = InvariantCheckInput(snapshot=snap, event_log=_clean_event_log())
        r = check_all_invariants(inp)
        text = r.to_human_readable()
        self.assertIn("❌", text)
        self.assertIn("I5", text)

    def test_to_dict_round_trip(self) -> None:
        snap = _clean_snapshot()
        snap["relationshipState"][0]["trust"] = 5.0
        inp = InvariantCheckInput(snapshot=snap)
        r = check_all_invariants(inp)
        s = json.dumps(r.to_dict())
        reloaded = json.loads(s)
        self.assertFalse(reloaded["passed"])
        self.assertGreaterEqual(reloaded["summary"]["I5"], 1)


if __name__ == "__main__":
    unittest.main()
