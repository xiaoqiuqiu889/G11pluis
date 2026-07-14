"""Unit tests for the content guards (校验链 content gate).

The brief calls these tests "关键测试" (critical) for the
mandatory_echo validator (UP-20260715-002) — a regression here
would let the AI Director invent cross-era echoes on the fly,
which is what 决策 3 explicitly forbids.

Coverage:

* forbidden_reveal surface scan (multiple text fields)
* mandatory_echo enforcement: NPC-raised echoes MUST be in
  the scene's mandatory list
* ungrounded memory: NPC cannot reference memories not in
  recall
* belief visibility matrix (subjective suppression /
  objective concealment / selective forgetting)
* orchestrator: ``run_content_guards`` returns the
  expected pass / fail aggregate
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.safety.content_guards import (  # noqa: E402
    BeliefVisibility,
    ContentGuardInput,
    ContentGuardReport,
    check_forbidden_reveals,
    check_mandatory_echoes,
    check_proposal_visibility,
    check_ungrounded_memory,
    run_content_guards,
)


class ForbiddenRevealsTests(unittest.TestCase):
    """The forbidden-reveal surface scan must hit every text field."""

    def test_no_violation_when_payload_clean(self) -> None:
        payload = {"resolvedText": "It was a quiet afternoon.", "narrative": ""}
        self.assertEqual(
            check_forbidden_reveals(payload, ["leila_future_marriage"]),
            [],
        )

    def test_violation_in_resolvedText(self) -> None:
        payload = {"resolvedText": "Leila's leila_future_marriage to Kamran is set."}
        violations = check_forbidden_reveals(payload, ["leila_future_marriage"])
        self.assertEqual(len(violations), 1)
        self.assertIn("resolvedText", violations[0])

    def test_violation_in_narrative(self) -> None:
        payload = {"narrative": "She recalled the airport_2011 scene."}
        violations = check_forbidden_reveals(payload, [{"revealKey": "airport_2011"}])
        self.assertEqual(len(violations), 1)
        self.assertIn("narrative", violations[0])

    def test_violation_in_utterance(self) -> None:
        payload = {"utterance": "I remember the luggage_2011 tag."}
        violations = check_forbidden_reveals(payload, ["luggage_2011"])
        self.assertEqual(len(violations), 1)
        self.assertIn("utterance", violations[0])

    def test_violation_in_belief_update_reasoning(self) -> None:
        payload = {
            "beliefUpdates": [
                {
                    "subject": "arash_father",
                    "newState": "certain",
                    "confidence": 0.9,
                    "reasoning": "He is recovering from a stroke (medical detail)",
                }
            ]
        }
        # medical_rehab is in the forbidden list
        violations = check_forbidden_reveals(payload, ["medical_rehab"])
        # The check looks at the subject too, but only string-valued
        # belief-update fields are scanned.  medical_rehab substring
        # "medical_rehab" is not in subject "arash_father".
        self.assertEqual(violations, [])

    def test_dict_shaped_forbidden_reveals(self) -> None:
        # Two shapes are accepted: plain string and dict with revealKey
        payload = {"resolvedText": "The istanbul_reunion happens someday."}
        reveals = [{"revealKey": "istanbul_reunion", "reason": "future"}]
        violations = check_forbidden_reveals(payload, reveals)
        self.assertEqual(len(violations), 1)
        self.assertIn("istanbul_reunion", violations[0])

    def test_empty_forbidden_list_is_no_op(self) -> None:
        payload = {"resolvedText": "Anything."}
        self.assertEqual(check_forbidden_reveals(payload, []), [])

    def test_no_text_surfaces_is_no_op(self) -> None:
        # payload with no text surfaces should be a no-op
        payload = {"runId": "00000000-0000-4000-8000-000000000001"}
        self.assertEqual(
            check_forbidden_reveals(payload, ["leila_future_marriage"]),
            [],
        )


class MandatoryEchoesTests(unittest.TestCase):
    """The critical check (决策 3 / UP-20260715-002).

    Every NPC-raised echo MUST appear in the scene's
    ``mandatory_echoes`` list.  A regression here would let
    the AI Director invent cross-era echoes on the fly.
    """

    def test_mandatory_echo_accepted(self) -> None:
        raised = [
            {
                "id": "photo_in_pocket",
                "speaker": "arash",
                "line": "I remember you kept it in your bag.",
            }
        ]
        mandatory = [
            {"id": "photo_in_pocket", "description": "Photo in pocket"},
            {"id": "photo_in_book", "description": "Photo in book"},
        ]
        violations = check_mandatory_echoes(raised, mandatory)
        self.assertEqual(violations, [])

    def test_mandatory_echo_violation_caught(self) -> None:
        raised = [
            {
                "id": "istanbul_reunion_2024",
                "speaker": "arash",
                "line": "One day we'll meet again in Istanbul.",
            }
        ]
        mandatory = [
            {"id": "photo_in_pocket", "description": "Photo in pocket"},
            {"id": "photo_in_book", "description": "Photo in book"},
        ]
        violations = check_mandatory_echoes(raised, mandatory)
        self.assertEqual(len(violations), 1)
        self.assertIn("istanbul_reunion_2024", violations[0])
        self.assertIn("arash", violations[0])
        self.assertIn("not in mandatory_echoes", violations[0])

    def test_mixed_raised_echoes(self) -> None:
        raised = [
            {"id": "photo_in_pocket", "speaker": "arash", "line": "kept it"},
            {"id": "future_marriage", "speaker": "arash", "line": "leila will marry"},
            {"id": "photo_in_book", "speaker": "leila", "line": "in the book"},
        ]
        mandatory = [
            {"id": "photo_in_pocket"},
            {"id": "photo_in_book"},
        ]
        violations = check_mandatory_echoes(raised, mandatory)
        self.assertEqual(len(violations), 1)
        self.assertIn("future_marriage", violations[0])

    def test_mandatory_ids_as_strings(self) -> None:
        raised = [{"id": "echo_a", "speaker": "x", "line": "a"}]
        # mandatory list uses plain strings
        mandatory = ["echo_a", "echo_b"]
        violations = check_mandatory_echoes(raised, mandatory)
        self.assertEqual(violations, [])

    def test_no_raised_echoes_is_no_op(self) -> None:
        mandatory = [{"id": "echo_a"}]
        self.assertEqual(check_mandatory_echoes([], mandatory), [])

    def test_non_dict_entries_are_skipped(self) -> None:
        # An NPC proposal may include non-dict noise; the
        # check must not crash on it.
        raised = ["not a dict", {"id": "echo_a", "speaker": "x", "line": "y"}]
        mandatory = [{"id": "echo_a"}]
        self.assertEqual(check_mandatory_echoes(raised, mandatory), [])

    def test_up_20260715_002_regression(self) -> None:
        """The exact regression scenario from UP-20260715-002.

        An NPC proposal in the reunion_2024 scene raised an
        echo (``future_marriage``) that is **not** in the
        scene's mandatory_echoes list.  The four-questions
        guard missed it because the design-time check uses
        the YAML; the runtime check (this module) catches
        it because the YAML is still consulted as the
        source of truth at runtime.
        """

        raised = [
            {
                "id": "leila_future_marriage",
                "speaker": "arash",
                "line": "I know you'll marry Kamran someday.",
            }
        ]
        mandatory = [
            {"id": "two_photos_takeout_compare"},
            {"id": "grip_then_release_2011"},
            {"id": "poetry_book_close_2011"},
        ]
        violations = check_mandatory_echoes(raised, mandatory)
        self.assertEqual(len(violations), 1)
        self.assertIn("leila_future_marriage", violations[0])


class UngroundedMemoryTests(unittest.TestCase):
    """The NPC cannot reference a memory outside the recall set."""

    def test_no_violation_when_all_grounded(self) -> None:
        recall = {"mem_1", "mem_2", "mem_3"}
        violations = check_ungrounded_memory(["mem_1", "mem_2"], recall)
        self.assertEqual(violations, [])

    def test_violation_when_ungrounded(self) -> None:
        recall = {"mem_1"}
        violations = check_ungrounded_memory(["mem_1", "mem_bogus"], recall)
        self.assertEqual(len(violations), 1)
        self.assertIn("mem_bogus", violations[0])
        self.assertIn("not in the recall set", violations[0])

    def test_empty_references_is_no_op(self) -> None:
        self.assertEqual(check_ungrounded_memory([], {"mem_1"}), [])

    def test_empty_recall_set_blocks_all(self) -> None:
        violations = check_ungrounded_memory(["mem_1", "mem_2"], [])
        self.assertEqual(len(violations), 2)


class BeliefVisibilityTests(unittest.TestCase):
    """Subjective suppression / objective concealment / selective forgetting."""

    def test_no_violation_when_clean(self) -> None:
        v = BeliefVisibility(characterId="leila")
        violations = check_proposal_visibility(["photo_A"], v)
        self.assertEqual(violations, [])

    def test_subjective_suppression_caught(self) -> None:
        v = BeliefVisibility(
            characterId="leila",
            subjective_suppression={"shame_about_father"},
        )
        violations = check_proposal_visibility(["shame_about_father"], v)
        self.assertEqual(len(violations), 1)
        self.assertIn("suppressing", violations[0])
        self.assertIn("shame_about_father", violations[0])

    def test_objective_concealment_caught(self) -> None:
        v = BeliefVisibility(
            characterId="arash_2011",
            objective_concealment={"2008_photo"},
        )
        violations = check_proposal_visibility(["2008_photo"], v)
        self.assertEqual(len(violations), 1)
        self.assertIn("should not know", violations[0])

    def test_selective_forgetting_caught(self) -> None:
        v = BeliefVisibility(
            characterId="leila_2024",
            selective_forgetting={"traumatic_event_2011"},
        )
        violations = check_proposal_visibility(["traumatic_event_2011"], v)
        self.assertEqual(len(violations), 1)
        self.assertIn("selectively forgetting", violations[0])

    def test_multiple_violations(self) -> None:
        v = BeliefVisibility(
            characterId="x",
            subjective_suppression={"a"},
            objective_concealment={"b"},
            selective_forgetting={"c"},
        )
        violations = check_proposal_visibility(["a", "b", "c", "d"], v)
        self.assertEqual(len(violations), 3)


class ContentGuardOrchestratorTests(unittest.TestCase):
    """``run_content_guards`` aggregates every check."""

    def test_clean_payload_passes(self) -> None:
        payload = {
            "resolvedText": "The 2008 photo is in my bag.",
            "beliefUpdates": [
                {
                    "subject": "photo_in_pocket",
                    "newState": "certain",
                    "confidence": 0.9,
                    "reasoning": "I always carry it.",
                }
            ],
        }
        inp = ContentGuardInput(
            payload=payload,
            forbidden_reveals=["leila_future_marriage"],
            mandatory_echoes=[{"id": "photo_in_pocket"}],
            npc_raised_echoes=[{"id": "photo_in_pocket", "speaker": "arash"}],
            referenced_memory_ids=["mem_1"],
            recall_set=["mem_1"],
            visibility=BeliefVisibility(characterId="arash"),
            dialogue_subjects=["photo_in_pocket"],
        )
        r = run_content_guards(inp)
        self.assertTrue(r.passed, r.to_human_readable())
        self.assertEqual(r.summary["total"], 0)

    def test_dirty_payload_fails(self) -> None:
        payload = {
            "resolvedText": "leila_future_marriage istanbul_reunion happens here.",
            "narrative": "future_secrets",
        }
        inp = ContentGuardInput(
            payload=payload,
            forbidden_reveals=["leila_future_marriage", "istanbul_reunion"],
            mandatory_echoes=[{"id": "photo_in_pocket"}],
            npc_raised_echoes=[
                {"id": "leila_future_marriage", "speaker": "arash"},
                {"id": "photo_in_pocket", "speaker": "arash"},
            ],
            referenced_memory_ids=["mem_1", "mem_bogus"],
            recall_set=["mem_1"],
            visibility=BeliefVisibility(
                characterId="arash",
                subjective_suppression={"future_secrets"},
            ),
            dialogue_subjects=["future_secrets"],
        )
        r = run_content_guards(inp)
        self.assertFalse(r.passed)
        # forbidden_reveal: 2 (leila_future_marriage + istanbul_reunion)
        # mandatory_echo: 1 (leila_future_marriage not in mandatory)
        # ungrounded_memory: 1 (mem_bogus)
        # visibility: 1 (future_secrets)
        self.assertEqual(r.summary["forbidden_reveal"], 2)
        self.assertEqual(r.summary["mandatory_echo"], 1)
        self.assertEqual(r.summary["ungrounded_memory"], 1)
        self.assertEqual(r.summary["visibility"], 1)
        self.assertEqual(r.summary["total"], 5)

    def test_to_human_readable_includes_verdict(self) -> None:
        payload = {"resolvedText": "leila_future_marriage appears here."}
        inp = ContentGuardInput(
            payload=payload,
            forbidden_reveals=["leila_future_marriage"],
        )
        r = run_content_guards(inp)
        text = r.to_human_readable()
        self.assertIn("❌", text)
        self.assertIn("forbidden_reveal", text)
        self.assertIn("leila_future_marriage", text)

    def test_to_dict_round_trip(self) -> None:
        import json
        payload = {"resolvedText": "leila_future_marriage surfaces here."}
        inp = ContentGuardInput(
            payload=payload, forbidden_reveals=["leila_future_marriage"]
        )
        r = run_content_guards(inp)
        s = json.dumps(r.to_dict())
        reloaded = json.loads(s)
        self.assertFalse(reloaded["passed"])
        self.assertGreaterEqual(reloaded["summary"]["total"], 1)


class BeliefVisibilityDataClassTests(unittest.TestCase):
    """``BeliefVisibility.to_dict`` is JSON-serialisable."""

    def test_to_dict(self) -> None:
        v = BeliefVisibility(
            characterId="leila",
            subjective_suppression={"a", "b"},
            objective_concealment={"c"},
            selective_forgetting={"d", "e"},
        )
        d = v.to_dict()
        self.assertEqual(d["characterId"], "leila")
        # Sets are serialised as sorted lists
        self.assertEqual(sorted(d["subjective_suppression"]), ["a", "b"])
        self.assertEqual(d["objective_concealment"], ["c"])
        self.assertEqual(sorted(d["selective_forgetting"]), ["d", "e"])


if __name__ == "__main__":
    unittest.main()
