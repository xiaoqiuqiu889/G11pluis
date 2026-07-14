"""Unit tests for the schema-output verifier (校验链 schema gate).

The verifier must:

* accept every well-formed payload for the 8 schemas
* reject malformed payloads with a clear category
  (``format_error`` / ``enum_error`` / ``range_error`` /
  ``missing_field`` / ``extra_field`` / ``type_error`` /
  ``schema_error``)
* include path + validator + offending value + rule in every
  report
* cache schemas across calls

We test against all 8 schemas using a small fixture per
schema.  The fixtures are hand-rolled and minimal — the goal
is to exercise the gate, not to retest the schemas (the
schemas themselves are exercised in
``tests/adversarial/test_content_studio.py`` etc.).
"""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.safety import (  # noqa: E402
    ErrorCategory,
    OutputVerifier,
    SCHEMA_REGISTRY,
    VerificationReport,
    verify_output,
)


# ---------------------------------------------------------------------------
# Fixtures — one minimal valid payload per schema
# ---------------------------------------------------------------------------


def _player_action() -> dict:
    return {
        "runId": "00000000-0000-4000-8000-000000000001",
        "sceneId": "photo_lab_2008",
        "actionType": "investigate",
        "actorId": "leila",
        "clientActionId": "00000000-0000-4000-8000-000000000010",
        "expectedEventSequence": 5,
        "targetId": None,
        "evidenceIds": [],
        "utterance": "",
        "tone": "neutral",
        "disclosureLevel": 0.0,
        "isDeceptive": False,
        "clientTimestamp": "2024-01-01T00:00:00Z",
        "schemaVersion": "1.0.0",
    }


def _npc_proposal() -> dict:
    return {
        "proposalId": "00000000-0000-4000-8000-000000000020",
        "runId": "00000000-0000-4000-8000-000000000001",
        "characterId": "arash",
        "triggerPlayerActionId": None,
        "proposedAction": "comfort",
        "targetId": "leila",
        "speechIntent": "comfort",
        "referencedMemoryIds": [],
        "beliefUpdatesRequested": [],
        "emotionalTransition": {
            "from": "tense",
            "to": "hopeful",
            "intensity": 0.50,
        },
        "reasonCodes": ["player_disclosed_truth"],
        "confidence": 0.75,  # 0.75 is exactly representable as 15*0.05
        "expectedContradictions": [],
        "timestamp": "2024-01-01T00:00:00Z",
        "schemaVersion": "1.0.0",
    }


def _director_beat() -> dict:
    return {
        "proposalId": "00000000-0000-4000-8000-000000000030",
        "runId": "00000000-0000-4000-8000-000000000001",
        "sceneId": "photo_lab_2008",
        "proposedBeat": "beat_setup_0",
        "allowedByContract": True,
        "forbiddenRevealsChecked": ["leila_future_marriage"],
        "transitionToNext": False,
        "suggestedTargetSceneId": None,
        "reasoning": "The Director checked the forbidden-reveals list.",
        "pacingPressure": 0.5,
        "expectedTensionDelta": 0.0,
        "involvedCharacterIds": ["leila", "arash"],
        "firedCausalSeeds": [],
        "timestamp": "2024-01-01T00:00:00Z",
        "schemaVersion": "1.0.0",
    }


def _resolver_outcome() -> dict:
    return {
        "outcomeId": "00000000-0000-4000-8000-000000000040",
        "runId": "00000000-0000-4000-8000-000000000001",
        "eventSequence": 1,
        "triggerPlayerActionId": "00000000-0000-4000-8000-000000000010",
        "triggerDirectorProposalId": None,
        "idempotencyKey": "x" * 32,
        "acceptedNpcAction": {
            "proposalId": "00000000-0000-4000-8000-000000000020",
            "characterId": "arash",
            "proposedAction": "comfort",
            "speechIntent": "comfort",
            "resolvedText": "",
        },
        "rejectedNpcActions": [],
        "relationshipDelta": [],
        "beliefUpdates": [],
        "artifactUpdates": [],
        "newCausalSeeds": [],
        "firedCausalSeeds": [],
        "nextBeat": {
            "sceneId": "photo_lab_2008",
            "beatId": "beat_setup_0",
            "transition": "continue",
            "legalEndingId": None,
        },
        "clampedValues": [],
        "auditTrail": {"llmCalls": [], "deterministicDecisions": []},
        "timestamp": "2024-01-01T00:00:00Z",
        "schemaVersion": "1.0.0",
    }


def _belief_matrix() -> dict:
    return {
        "characterId": "leila",
        "runId": "00000000-0000-4000-8000-000000000001",
        "objective_facts": [
            {
                "factId": "fact_1",
                "description": "A fact.",
                "establishedAt": 1,
                "isContested": False,
            }
        ],
        "character_knowledge": [],
        "character_memories": [],
        "hidden_secrets": [],
        "schemaVersion": "1.0.0",
    }


def _narrative_contract() -> dict:
    return {
        "sceneId": "photo_lab_2008",
        "title": "地下放映室与两张毕业照",
        "era": "2008",
        "location": "德黑兰大学·革命街旧书店地下室",
        "required_anchors": [
            {"anchorId": "anchor_1", "description": "anch", "mandatory": True}
        ],
        "core_conflict": "Two photos must be split or shared between the two characters.",
        "allowed_beats": [
            {
                "beatId": "beat_setup_0",
                "label": "setup",
                "tier": "setup",
            }
        ],
        "forbidden_reveals": [
            {"revealKey": "leila_future_marriage", "reason": "future"}
        ],
        "max_turns": 8,
        "total_action_budget": 32,
        "legal_endings": [
            {
                "endingId": "shared_secret",
                "label": "Shared secret",
                "conditions": ["photos split"],
            }
        ],
        "schemaVersion": "1.0.0",
    }


def _causal_seed() -> dict:
    return {
        "id": "seed_photo_in_pocket",
        "source_scene": "photo_lab_2008",
        "source_event": "out_1",
        "description": "Photo in pocket.",
        "trigger_condition": {
            "type": "artifact_present",
            "predicate": "photo_A in cast",
            "minEcho": 0.5,
        },
        "target_scenes": ["farewell_2011", "reunion_2024"],
        "echo_intensity": 0.5,
        "is_secret": False,
        "firedAt": None,
        "firedInSceneId": None,
        "linkedCharacterIds": ["leila"],
        "decayRate": 0.02,
        "tags": ["photo"],
        "schemaVersion": "1.0.0",
    }


def _world_snapshot() -> dict:
    return {
        "runId": "00000000-0000-4000-8000-000000000001",
        "eventSequence": 0,
        "canonicalState": {
            "currentSceneId": "photo_lab_2008",
            "era": "2008",
            "turnIndex": 0,
            "phase": "setup",
            "activeContractId": "c_photo_lab_2008",
            "activeBeatId": None,
            "endingId": None,
            "globalTension": 0.0,
        },
        "relationshipState": [],
        "artifactState": [],
        "directorState": {
            "currentBeatId": "beat_setup_0",
            "elapsedTurnsInScene": 0,
            "actionsSpentInScene": 0,
            "firedBeats": [],
            "hitAnchors": [],
            "forbiddenRevealsCheckedAt": [],
        },
        "beliefMatrices": [],
        "memories": [],
        "causalSeedsActive": [],
        "recentOutcomes": [],
        "timestamp": "2024-01-01T00:00:00Z",
        "checksum": "0" * 64,
        "schemaVersion": "1.0.0",
    }


VALID_FIXTURES: dict[str, dict] = {
    "player_action": _player_action,
    "npc_proposal": _npc_proposal,
    "director_beat": _director_beat,
    "resolver_outcome": _resolver_outcome,
    "belief_matrix": _belief_matrix,
    "narrative_contract": _narrative_contract,
    "causal_seed": _causal_seed,
    "world_snapshot": _world_snapshot,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class SchemaRegistryTests(unittest.TestCase):
    """All 8 schemas are registered and resolvable."""

    def test_all_eight_schemas_listed(self) -> None:
        self.assertEqual(
            set(SCHEMA_REGISTRY),
            {
                "player_action",
                "npc_proposal",
                "director_beat",
                "resolver_outcome",
                "belief_matrix",
                "narrative_contract",
                "causal_seed",
                "world_snapshot",
            },
        )

    def test_unknown_schema_raises(self) -> None:
        with self.assertRaises(KeyError):
            OutputVerifier().verify("nonexistent_schema", {})

    def test_default_verifier_uses_project_schema_dir(self) -> None:
        v = OutputVerifier()
        r = v.verify("player_action", _player_action())
        self.assertTrue(r.valid)
        # schema_path should be inside server/config/schemas
        self.assertIn("config", r.schema_path)
        self.assertTrue(r.schema_path.endswith("player_action.schema.json"))


class ValidPayloadTests(unittest.TestCase):
    """Every fixture passes its schema."""

    def setUp(self) -> None:
        self.v = OutputVerifier()

    def test_player_action_valid(self) -> None:
        r = self.v.verify("player_action", _player_action())
        self.assertTrue(r.valid, r.to_human_readable())
        self.assertEqual(r.errors, [])

    def test_npc_proposal_valid(self) -> None:
        r = self.v.verify("npc_proposal", _npc_proposal())
        self.assertTrue(r.valid, r.to_human_readable())

    def test_director_beat_valid(self) -> None:
        r = self.v.verify("director_beat", _director_beat())
        self.assertTrue(r.valid, r.to_human_readable())

    def test_resolver_outcome_valid(self) -> None:
        r = self.v.verify("resolver_outcome", _resolver_outcome())
        self.assertTrue(r.valid, r.to_human_readable())

    def test_belief_matrix_valid(self) -> None:
        r = self.v.verify("belief_matrix", _belief_matrix())
        self.assertTrue(r.valid, r.to_human_readable())

    def test_narrative_contract_valid(self) -> None:
        r = self.v.verify("narrative_contract", _narrative_contract())
        self.assertTrue(r.valid, r.to_human_readable())

    def test_causal_seed_valid(self) -> None:
        r = self.v.verify("causal_seed", _causal_seed())
        self.assertTrue(r.valid, r.to_human_readable())

    def test_world_snapshot_valid(self) -> None:
        r = self.v.verify("world_snapshot", _world_snapshot())
        self.assertTrue(r.valid, r.to_human_readable())

    def test_json_string_payload_accepted(self) -> None:
        payload = json.dumps(_player_action())
        r = self.v.verify("player_action", payload)
        self.assertTrue(r.valid, r.to_human_readable())

    def test_malformed_json_string_reports_format_error(self) -> None:
        r = self.v.verify("player_action", "not json {")
        self.assertFalse(r.valid)
        self.assertEqual(r.errors[0].category, ErrorCategory.FORMAT_ERROR.value)


class ErrorCategoryTests(unittest.TestCase):
    """Every category is reachable from a real schema."""

    def setUp(self) -> None:
        self.v = OutputVerifier()

    def test_enum_error(self) -> None:
        bad = _player_action()
        bad["actionType"] = "chat"  # not in the 12-type vocab
        r = self.v.verify("player_action", bad)
        self.assertFalse(r.valid)
        cats = {e.category for e in r.errors}
        self.assertIn(ErrorCategory.ENUM_ERROR.value, cats)

    def test_missing_field(self) -> None:
        bad = {k: v for k, v in _player_action().items() if k != "actorId"}
        r = self.v.verify("player_action", bad)
        self.assertFalse(r.valid)
        cats = {e.category for e in r.errors}
        self.assertIn(ErrorCategory.MISSING_FIELD.value, cats)

    def test_extra_field(self) -> None:
        bad = dict(_player_action(), free_form_garbage="hello")
        r = self.v.verify("player_action", bad)
        self.assertFalse(r.valid)
        cats = {e.category for e in r.errors}
        self.assertIn(ErrorCategory.EXTRA_FIELD.value, cats)

    def test_range_error_minimum(self) -> None:
        bad = _player_action()
        bad["disclosureLevel"] = -0.1
        r = self.v.verify("player_action", bad)
        self.assertFalse(r.valid)
        cats = {e.category for e in r.errors}
        self.assertIn(ErrorCategory.RANGE_ERROR.value, cats)

    def test_range_error_maximum(self) -> None:
        bad = _player_action()
        bad["disclosureLevel"] = 1.5
        r = self.v.verify("player_action", bad)
        self.assertFalse(r.valid)
        cats = {e.category for e in r.errors}
        self.assertIn(ErrorCategory.RANGE_ERROR.value, cats)

    def test_format_error_uuid(self) -> None:
        bad = _player_action()
        bad["runId"] = "not-a-uuid"
        r = self.v.verify("player_action", bad)
        self.assertFalse(r.valid)
        cats = {e.category for e in r.errors}
        self.assertIn(ErrorCategory.FORMAT_ERROR.value, cats)

    def test_type_error(self) -> None:
        bad = _player_action()
        bad["eventSequence"] = "not an int"
        # The schema actually uses expectedEventSequence, swap
        bad = _player_action()
        bad["expectedEventSequence"] = "abc"
        r = self.v.verify("player_action", bad)
        self.assertFalse(r.valid)
        cats = {e.category for e in r.errors}
        self.assertIn(ErrorCategory.TYPE_ERROR.value, cats)

    def test_schema_error(self) -> None:
        """A conditional rule violation (allOf/then) is a schema_error."""
        # PlayerAction's allOf: question/confront/give/comfort require non-null targetId.
        bad = _player_action()
        bad["actionType"] = "question"
        bad["targetId"] = None  # violates the allOf then-branch
        r = self.v.verify("player_action", bad)
        self.assertFalse(r.valid)
        # The path should point to targetId
        paths = [e.path for e in r.errors]
        self.assertTrue(
            any("targetId" in p for p in paths),
            f"expected targetId in paths; got {paths}",
        )


class ReportStructureTests(unittest.TestCase):
    """The report exposes path, validator, value, rule, explanation."""

    def test_each_error_has_full_metadata(self) -> None:
        bad = _player_action()
        bad["actionType"] = "chat"
        r = OutputVerifier().verify("player_action", bad)
        self.assertEqual(len(r.errors), 1)
        e = r.errors[0]
        self.assertEqual(e.category, ErrorCategory.ENUM_ERROR.value)
        self.assertEqual(e.path, "actionType")
        self.assertEqual(e.validator, "enum")
        self.assertEqual(e.offending_value, "chat")
        # The legal enum list should be in the rule
        self.assertIn("investigate", str(e.schema_rule))
        self.assertIn("comfort", str(e.schema_rule))
        # Explanation should be human-readable
        self.assertTrue(e.explanation)

    def test_summary_counts(self) -> None:
        bad = _player_action()
        bad["actionType"] = "chat"  # 1 enum
        bad["disclosureLevel"] = 1.5  # 1 range
        bad["free_field"] = "x"  # 1 extra
        r = OutputVerifier().verify("player_action", bad)
        self.assertEqual(r.summary["total"], 3)
        self.assertEqual(r.summary[ErrorCategory.ENUM_ERROR.value], 1)
        self.assertEqual(r.summary[ErrorCategory.RANGE_ERROR.value], 1)
        self.assertEqual(r.summary[ErrorCategory.EXTRA_FIELD.value], 1)

    def test_to_dict_is_json_serialisable(self) -> None:
        bad = _player_action()
        bad["actionType"] = "chat"
        r = OutputVerifier().verify("player_action", bad)
        # Must round-trip through json
        s = json.dumps(r.to_dict())
        reloaded = json.loads(s)
        self.assertFalse(reloaded["valid"])
        self.assertEqual(len(reloaded["errors"]), 1)

    def test_human_readable_includes_verdict_and_path(self) -> None:
        bad = _player_action()
        bad["actionType"] = "chat"
        r = OutputVerifier().verify("player_action", bad)
        text = r.to_human_readable()
        self.assertIn("❌", text)
        self.assertIn("actionType", text)
        self.assertIn("enum", text)


class CacheTests(unittest.TestCase):
    """Schemas are cached across calls; ``clear_cache`` resets."""

    def test_cache_reused_across_calls(self) -> None:
        v = OutputVerifier()
        v.verify("player_action", _player_action())
        # Internal: same path should be cached
        self.assertIn("player_action", v._cache)
        v.verify("player_action", _player_action())
        # Still in cache; cache count for the schema is 1
        self.assertEqual(len(v._cache.get("player_action", (None, None))), 2)

    def test_clear_cache_empties(self) -> None:
        v = OutputVerifier()
        v.verify("player_action", _player_action())
        v.clear_cache()
        self.assertEqual(v._cache, {})


class ModuleLevelApiTests(unittest.TestCase):
    """The module-level ``verify_output`` convenience works."""

    def test_module_level_verify(self) -> None:
        r = verify_output("player_action", _player_action())
        self.assertTrue(r.valid)
        self.assertIsInstance(r, VerificationReport)


class AdrValidationTests(unittest.TestCase):
    """ADR 0007: ``case_01_revolution_street`` short year codes are valid
    in any schema's era field that the engine accepts.

    The schema ``world_snapshot.canonicalState.era`` still has the
    13-value enum; the *runtime* accepts short year codes via
    :data:`types.CASE_ERAS`.  This test confirms the schema
    is unchanged (still the 13-value enum) so a future ADR drift
    is detectable from CI.
    """

    def test_world_snapshot_schema_era_includes_adr_0007_overrides(self) -> None:
        """ADR 0007 §2.5: the world_snapshot schema is updated in the
        same PR as the runtime extension.  The schema now lists the
        13 canonical Era values **plus** the 4 case-scoped values
        declared in :data:`types.CASE_ERAS` for
        ``case_01_revolution_street`` (``2008``, ``2011``,
        ``2024``, ``EPILOGUE``).
        """

        path = (
            Path(__file__).resolve().parents[2]
            / "server"
            / "config"
            / "schemas"
            / "world_snapshot.schema.json"
        )
        with open(path, "r", encoding="utf-8") as fp:
            schema = json.load(fp)
        era_enum = schema["properties"]["canonicalState"]["properties"]["era"]["enum"]
        # 13 canonical + 4 case-scoped = 17 (ADR 0007 §2.5)
        self.assertEqual(len(era_enum), 17, era_enum)
        # All 4 case-scoped values are present
        for case_value in ("2008", "2011", "2024", "EPILOGUE"):
            self.assertIn(case_value, era_enum)
        # The 13 canonical Era values are still present
        for canonical in ("pre_1911_qing", "1911_1927_republic", "2012_present_ai_age"):
            self.assertIn(canonical, era_enum)

    def test_case_era_runtime_helper(self) -> None:
        """The engine's :func:`is_valid_era_for_case` must accept the
        4 case-scoped eras for the first case and reject them for
        any unknown case.
        """

        sys.path.insert(0, str(ROOT / "server"))
        try:
            from engine import is_valid_era_for_case  # type: ignore
        finally:
            sys.path = [p for p in sys.path if not p.endswith("server")]
        self.assertTrue(is_valid_era_for_case("2008", "case_01_revolution_street"))
        self.assertTrue(is_valid_era_for_case("2011", "case_01_revolution_street"))
        self.assertTrue(is_valid_era_for_case("2024", "case_01_revolution_street"))
        self.assertTrue(is_valid_era_for_case("EPILOGUE", "case_01_revolution_street"))
        # case-scoped values must NOT leak across case boundaries
        self.assertFalse(is_valid_era_for_case("2008", "case_99_never_built"))


if __name__ == "__main__":
    unittest.main()
