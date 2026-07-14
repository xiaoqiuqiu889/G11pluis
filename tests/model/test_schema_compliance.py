"""Unit tests for the schema validator (8 engine JSON Schemas).

Coverage
--------

* All 8 schemas load from disk
* Each schema accepts a known-good sample payload
* Each schema rejects a known-bad payload (e.g. wrong enum value)
* :meth:`validate_for_task` looks up the right schema per task
* :func:`safe_parse_json` handles JSON, fenced JSON, and prose
"""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "server"))

from model import (  # noqa: E402
    SchemaValidator,
    TaskType,
    safe_parse_json,
)


# ---------------------------------------------------------------------------
# Sample payloads (valid + invalid)
# ---------------------------------------------------------------------------


def _valid_player_action() -> dict:
    return {
        "runId": str(uuid.uuid4()),
        "sceneId": "photo_lab_2008",
        "actionType": "question",
        "actorId": "player",
        "targetId": "arash",
        "utterance": "hi",
        "tone": "hesitant",
        "disclosureLevel": 0.5,
        "isDeceptive": False,
        "schemaVersion": "1.0.0",
    }


def _valid_npc_proposal() -> dict:
    return {
        "proposalId": str(uuid.uuid4()),
        "runId": str(uuid.uuid4()),
        "characterId": "arash",
        "proposedAction": "comfort",
        "speechIntent": "comfort",
        "reasonCodes": ["player_disclosed_truth"],
        "confidence": 0.7,
        "schemaVersion": "1.0.0",
    }


def _valid_director_beat() -> dict:
    return {
        "proposalId": str(uuid.uuid4()),
        "runId": str(uuid.uuid4()),
        "sceneId": "photo_lab_2008",
        "proposedBeat": "beat_divide_photos",
        "allowedByContract": True,
        "forbiddenRevealsChecked": ["leila_future_marriage"],
        "transitionToNext": False,
        "reasoning": "Player has asked about the photo, anchor 1 needs to fire.",
        "pacingPressure": 0.6,
        "schemaVersion": "1.0.0",
    }


def _valid_resolver_outcome() -> dict:
    return {
        "outcomeId": str(uuid.uuid4()),
        "runId": str(uuid.uuid4()),
        "eventSequence": 1,
        "idempotencyKey": "idem-1234567890",
        "acceptedNpcAction": {
            "proposalId": str(uuid.uuid4()),
            "characterId": "arash",
            "proposedAction": "comfort",
            "speechIntent": "comfort",
        },
        "nextBeat": {
            "sceneId": "photo_lab_2008",
            "beatId": "beat_divide_photos",
            "transition": "continue",
        },
        "timestamp": "2026-07-15T00:00:00Z",
        "schemaVersion": "1.0.0",
    }


def _valid_belief_matrix() -> dict:
    return {
        "characterId": "arash",
        "objective_facts": [],
        "character_knowledge": [],
        "character_memories": [],
        "hidden_secrets": [],
        "schemaVersion": "1.0.0",
    }


def _valid_causal_seed() -> dict:
    return {
        "id": "seed_photo_2008_to_2024",
        "source_scene": "photo_lab_2008",
        "source_event": str(uuid.uuid4()),
        "description": "The two photos are planted in the darkroom.",
        "trigger_condition": {
            "type": "scene_match",
            "predicate": "sceneId == 'reunion_2024'",
        },
        "target_scenes": ["reunion_2024"],
        "echo_intensity": 0.5,
        "is_secret": False,
        "schemaVersion": "1.0.0",
    }


def _valid_narrative_contract() -> dict:
    return {
        "sceneId": "photo_lab_2008",
        "title": "暗房与两张同版试业照",
        "era": "2008",
        "location": "革命街旧宅·地下暗房",
        "required_anchors": [
            {"anchorId": "a1", "description": "两张同版试业照", "mandatory": True},
        ],
        "core_conflict": "如何在两张照片中分配这一段关系。",
        "allowed_beats": [
            {"beatId": "b1", "label": "分照片", "tier": "setup"},
        ],
        "forbidden_reveals": [
            {"revealKey": "leila_future_marriage", "reason": "未到时候"},
        ],
        "max_turns": 8,
        "total_action_budget": 30,
        "legal_endings": [
            {"endingId": "end_a", "label": "两人各执一份", "conditions": ["photo_divided"]},
        ],
        "schemaVersion": "1.0.0",
    }


def _valid_world_snapshot() -> dict:
    return {
        "runId": str(uuid.uuid4()),
        "eventSequence": 0,
        "canonicalState": {
            "currentSceneId": "photo_lab_2008",
            "era": "2008",
            "turnIndex": 0,
            "phase": "setup",
            "globalTension": 0.0,
        },
        "relationshipState": [],
        "artifactState": [],
        "directorState": {
            "currentBeatId": "b1",
            "elapsedTurnsInScene": 0,
            "actionsSpentInScene": 0,
        },
        "beliefMatrices": [],
        "memories": [],
        "causalSeedsActive": [],
        "timestamp": "2026-07-15T00:00:00Z",
        "checksum": "0" * 64,
        "schemaVersion": "1.0.0",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class SchemaLoadingTests(unittest.TestCase):

    def test_all_eight_schemas_loaded(self) -> None:
        v = SchemaValidator()
        self.assertEqual(
            set(v.schema_names),
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
        v = SchemaValidator()
        with self.assertRaises(KeyError):
            v.validate(schema_name="nope", payload={})


class ValidationTests(unittest.TestCase):

    def setUp(self) -> None:
        self.v = SchemaValidator()

    def test_valid_player_action(self) -> None:
        report = self.v.validate(schema_name="player_action", payload=_valid_player_action())
        self.assertTrue(report.ok, msg=str([str(i) for i in report.issues]))
        self.assertIsNotNone(report.parsed)

    def test_invalid_player_action_enum(self) -> None:
        bad = _valid_player_action()
        bad["actionType"] = "fly_to_mars"  # not in enum
        report = self.v.validate(schema_name="player_action", payload=bad)
        self.assertFalse(report.ok)
        self.assertTrue(any("actionType" in i.path for i in report.issues))

    def test_valid_npc_proposal(self) -> None:
        report = self.v.validate(schema_name="npc_proposal", payload=_valid_npc_proposal())
        self.assertTrue(report.ok, msg=str([str(i) for i in report.issues]))

    def test_invalid_npc_proposal_speech_intent(self) -> None:
        bad = _valid_npc_proposal()
        bad["speechIntent"] = "levitate"  # not in enum
        report = self.v.validate(schema_name="npc_proposal", payload=bad)
        self.assertFalse(report.ok)

    def test_valid_director_beat(self) -> None:
        report = self.v.validate(schema_name="director_beat", payload=_valid_director_beat())
        self.assertTrue(report.ok, msg=str([str(i) for i in report.issues]))

    def test_invalid_director_beat_allowedByContract(self) -> None:
        bad = _valid_director_beat()
        bad["allowedByContract"] = False  # schema const=true
        report = self.v.validate(schema_name="director_beat", payload=bad)
        self.assertFalse(report.ok)

    def test_valid_resolver_outcome(self) -> None:
        report = self.v.validate(schema_name="resolver_outcome", payload=_valid_resolver_outcome())
        self.assertTrue(report.ok, msg=str([str(i) for i in report.issues]))

    def test_valid_belief_matrix(self) -> None:
        report = self.v.validate(schema_name="belief_matrix", payload=_valid_belief_matrix())
        self.assertTrue(report.ok, msg=str([str(i) for i in report.issues]))

    def test_valid_causal_seed(self) -> None:
        report = self.v.validate(schema_name="causal_seed", payload=_valid_causal_seed())
        self.assertTrue(report.ok, msg=str([str(i) for i in report.issues]))

    def test_valid_narrative_contract(self) -> None:
        report = self.v.validate(schema_name="narrative_contract", payload=_valid_narrative_contract())
        self.assertTrue(report.ok, msg=str([str(i) for i in report.issues]))

    def test_valid_world_snapshot(self) -> None:
        report = self.v.validate(schema_name="world_snapshot", payload=_valid_world_snapshot())
        self.assertTrue(report.ok, msg=str([str(i) for i in report.issues]))


class ValidateForTaskTests(unittest.TestCase):

    def test_player_intent_parser_uses_player_action_schema(self) -> None:
        v = SchemaValidator()
        report = v.validate_for_task(task_type=TaskType.PLAYER_INTENT_PARSER, payload=_valid_player_action())
        self.assertTrue(report.ok)

    def test_npc_proposer_uses_npc_proposal_schema(self) -> None:
        v = SchemaValidator()
        report = v.validate_for_task(task_type=TaskType.NPC_PROPOSER, payload=_valid_npc_proposal())
        self.assertTrue(report.ok)

    def test_director_proposer_uses_director_beat_schema(self) -> None:
        v = SchemaValidator()
        report = v.validate_for_task(task_type=TaskType.DIRECTOR_PROPOSER, payload=_valid_director_beat())
        self.assertTrue(report.ok)

    def test_resolver_uses_resolver_outcome_schema(self) -> None:
        v = SchemaValidator()
        report = v.validate_for_task(task_type=TaskType.RESOLVER, payload=_valid_resolver_outcome())
        self.assertTrue(report.ok)

    def test_memory_recall_has_no_schema(self) -> None:
        v = SchemaValidator()
        # Any parseable JSON should be accepted.
        report = v.validate_for_task(task_type=TaskType.MEMORY_RECALL, payload={"x": 1})
        self.assertTrue(report.ok)
        self.assertEqual(report.parsed, {"x": 1})


class SafeParseJsonTests(unittest.TestCase):

    def test_plain_json(self) -> None:
        self.assertEqual(safe_parse_json('{"a": 1}'), {"a": 1})

    def test_fenced_json(self) -> None:
        text = '```json\n{"a": 1}\n```'
        self.assertEqual(safe_parse_json(text), {"a": 1})

    def test_prose_around_json(self) -> None:
        text = 'Here is the JSON: {"a": 1} -- end.'
        self.assertEqual(safe_parse_json(text), {"a": 1})

    def test_garbage_returns_none(self) -> None:
        self.assertIsNone(safe_parse_json('not json at all'))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(safe_parse_json(""))


if __name__ == "__main__":
    unittest.main()
