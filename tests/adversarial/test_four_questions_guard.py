"""
test_four_questions_guard.py
============================
Adversarial test suite for the 4-Questions Self-Check (决策 6).

Required coverage (per the dev task brief):
  1.  passing scene (all 4 questions ✅)
  2.  blocking scene (any of the 4 ❌)
  3.  forbidden_reveal violation
  4.  turn_budget overflow
  5.  artifact duplication
  6.  missing mandatory_echo list
  7.  mandatory echo vs NPC recall mismatch

Plus we add structural tests so every branch in
``four_questions_guard_lib`` is exercised — this is the 100% line /
branch coverage the brief requires.

Every test is hermetic: no network, no filesystem reads of the real
project content, no shared mutable state.  The 7 required scenarios
are pinned to the brief's "7 个测试场景" list and live in named
functions so failures are easy to triage.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Make the ``tools/`` folder importable.
_TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(_TOOLS))

import four_questions_guard_lib as lib  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — all fixtures are inline so the suite is self-contained.
# ---------------------------------------------------------------------------


def _passing_interaction() -> dict:
    """Scenario 1: a fully compliant interaction (4/4 ✅)."""
    return {
        "type": "resolver_outcome",
        "sceneId": "photo_lab_2008",
        "runId": "00000000-0000-4000-8000-000000000001",
        "actorId": "leila",
        "targetId": "arash",
        "artifact_updates": [
            {
                "artifactId": "photo_pair",
                "newOwnerId": "arash",
                "newState": "夹进诗集书页",
                "newLocation": "阿拉什夹克内袋",
            },
        ],
        "event_log": [
            {
                "eventId": "evt_001",
                "description": "莱拉把同版照片给了阿拉什",
                "sequence": 42,
            },
        ],
        "belief_updates": [
            {
                "characterId": "arash",
                "subject": "photo_pair_ownership",
                "belief_state": "certain",
                "confidence": 0.9,
                "reasoning": "莱拉亲手递给我",
            },
        ],
        "belief_matrix": [
            {
                "characterId": "arash",
                "addedMemory": "莱拉把照片交到我手中",
                "emotionalWeight": 0.95,
            },
        ],
        "turn_budget": {
            "total": 8,
            "current_turn": 3,
            "max_turns": 8,
        },
        "action_whitelist": [
            "investigate", "give", "conceal", "leave",
        ],
        "causal_seeds": [
            {"seedId": "photo_in_book", "planted": True, "intensity": 0.9},
        ],
        "far_echo_routes": [
            {
                "targetSceneId": "reunion_2024",
                "seedIds": ["photo_in_book"],
            },
        ],
        "forbidden_reveals": [
            {"revealKey": "leila_future_marriage", "reason": "未达条件"},
        ],
        "artifacts": [
            {"artifactId": "photo_pair", "ownerId": "arash", "state": "in_book"},
        ],
        "mandatory_echoes": [
            {"id": "photo_in_book", "description": "2008 阿拉什把照片夹进诗集"},
        ],
        "npc_raised_echoes": [
            {
                "id": "photo_in_book",
                "speaker": "arash",
                "line": "你把那张照片带了多少年？",
                "inMandatoryList": True,
            },
        ],
    }


def _blocking_q1() -> dict:
    """Scenario 2a: world-state change missing (Q1 ❌)."""
    doc = _passing_interaction()
    doc["artifact_updates"] = []
    doc["event_log"] = []
    return doc


def _blocking_q2() -> dict:
    """Scenario 2b: character-knowledge change missing (Q2 ❌)."""
    doc = _passing_interaction()
    doc["belief_updates"] = []
    doc["belief_matrix"] = []
    return doc


def _blocking_q3() -> dict:
    """Scenario 2c: available-action change missing (Q3 ❌)."""
    doc = _passing_interaction()
    doc.pop("turn_budget", None)
    doc.pop("action_whitelist", None)
    return doc


def _blocking_q4() -> dict:
    """Scenario 2d: future-echo material missing (Q4 ❌)."""
    doc = _passing_interaction()
    doc["causal_seeds"] = []
    doc["far_echo_routes"] = []
    return doc


def _forbidden_reveal_violation() -> dict:
    """Scenario 3: a forbidden reveal key is mentioned in the utterance."""
    doc = _passing_interaction()
    doc["forbidden_reveals"] = [
        {"revealKey": "leila_future_marriage", "reason": "未达条件"},
        {"revealKey": "kamran_2024_reunion", "reason": "未达条件"},
    ]
    doc["utterance"] = (
        "我想告诉你 leila_future_marriage 和 kamran_2024_reunion 的全部细节。"
    )
    return doc


def _turn_budget_overflow() -> dict:
    """Scenario 4: current_turn exceeds max_turns."""
    doc = _passing_interaction()
    doc["turn_budget"] = {
        "total": 8,
        "current_turn": 9,
        "max_turns": 8,
    }
    return doc


def _artifact_duplication() -> dict:
    """Scenario 5: an artifact has two distinct owners in the listing."""
    doc = _passing_interaction()
    doc["artifacts"] = [
        {"artifactId": "photo_pair", "ownerId": "leila", "state": "in_pocket"},
        {"artifactId": "photo_pair", "ownerId": "arash", "state": "in_book"},
    ]
    return doc


def _missing_mandatory_echoes() -> dict:
    """Scenario 6: a scene contract without a mandatory_echoes list."""
    return {
        "sceneId": "farewell_2011",
        "required_anchors": [{"anchorId": "airport_setting", "description": "国际出发大厅"}],
        "allowed_beats": [{"beatId": "silence", "label": "沉默", "tier": "falling"}],
        "core_conflict": "是否把卡姆兰的名字说出口",
        "forbidden_reveals": [
            {"revealKey": "leila_2024_reunion", "reason": "未达条件"},
        ],
        # NOTE: no mandatory_echoes key on purpose.
    }


def _mandatory_echo_npc_mismatch() -> dict:
    """Scenario 7: NPC raised an echo that is NOT in the mandatory list."""
    doc = _passing_interaction()
    doc["mandatory_echoes"] = [
        {"id": "photo_in_book", "description": "2008 阿拉什把照片夹进诗集"},
    ]
    doc["npc_raised_echoes"] = [
        {
            "id": "photo_in_book",
            "speaker": "arash",
            "line": "你把那张照片带了多少年？",
            "inMandatoryList": True,
        },
        {
            "id": "leila_2024_reunion",  # not in mandatory list
            "speaker": "leila",
            "line": "13 年后我们会在伊斯坦布尔重逢。",
            "inMandatoryList": False,
        },
    ]
    return doc


# ---------------------------------------------------------------------------
# The 7 required scenarios
# ---------------------------------------------------------------------------


class TestRequiredScenarios(unittest.TestCase):
    """Brief-mandated: 7 named scenarios."""

    def test_01_passing_scene_all_four_yes(self):
        doc = _passing_interaction()
        report = lib.run_guard(doc, document_path="<test:passing>")
        self.assertEqual(report.document_kind, "interaction")
        self.assertFalse(report.blocking, msg=report.to_human_readable())
        # Q1-Q4 must all pass.
        q_results = {r.id: r for r in report.results if r.id.startswith("Q")}
        for qid in lib.CORE_QUESTION_IDS:
            self.assertTrue(
                q_results[qid].passed,
                f"{qid} should pass on a fully compliant interaction: {q_results[qid].detail}",
            )
        # All 3 additional checks should pass; both mandatory-echo checks should pass.
        a_results = {r.id: r for r in report.results}
        self.assertTrue(a_results["A_forbidden_reveal_risk"].passed)
        self.assertTrue(a_results["B_turn_budget_safe"].passed)
        self.assertTrue(a_results["C_artifact_uniqueness"].passed)
        self.assertTrue(a_results["D_mandatory_echo_declared"].passed)
        self.assertTrue(a_results["E_npc_recall_within_mandatory"].passed)

    def test_02a_blocking_when_q1_missing(self):
        doc = _blocking_q1()
        report = lib.run_guard(doc, document_path="<test:q1>")
        self.assertTrue(report.blocking, msg=report.to_human_readable())
        reasons = "\n".join(report.blocking_reasons)
        self.assertIn("Q1_changes_world_state", reasons)

    def test_02b_blocking_when_q2_missing(self):
        doc = _blocking_q2()
        report = lib.run_guard(doc, document_path="<test:q2>")
        self.assertTrue(report.blocking, msg=report.to_human_readable())
        reasons = "\n".join(report.blocking_reasons)
        self.assertIn("Q2_changes_character_knowledge", reasons)

    def test_02c_blocking_when_q3_missing(self):
        doc = _blocking_q3()
        report = lib.run_guard(doc, document_path="<test:q3>")
        self.assertTrue(report.blocking, msg=report.to_human_readable())
        reasons = "\n".join(report.blocking_reasons)
        self.assertIn("Q3_changes_available_actions", reasons)

    def test_02d_blocking_when_q4_missing(self):
        doc = _blocking_q4()
        report = lib.run_guard(doc, document_path="<test:q4>")
        self.assertTrue(report.blocking, msg=report.to_human_readable())
        reasons = "\n".join(report.blocking_reasons)
        self.assertIn("Q4_creates_future_echo", reasons)

    def test_03_forbidden_reveal_violation(self):
        doc = _forbidden_reveal_violation()
        report = lib.run_guard(doc, document_path="<test:forbidden>")
        self.assertTrue(report.blocking, msg=report.to_human_readable())
        reasons = "\n".join(report.blocking_reasons)
        self.assertIn("A_forbidden_reveal_risk", reasons)
        a_result = next(r for r in report.results if r.id == "A_forbidden_reveal_risk")
        self.assertFalse(a_result.passed)
        self.assertIn("leila_future_marriage", a_result.detail)
        self.assertIn("kamran_2024_reunion", a_result.detail)

    def test_04_turn_budget_overflow(self):
        doc = _turn_budget_overflow()
        report = lib.run_guard(doc, document_path="<test:turn_budget>")
        self.assertTrue(report.blocking, msg=report.to_human_readable())
        reasons = "\n".join(report.blocking_reasons)
        self.assertIn("B_turn_budget_safe", reasons)
        b_result = next(r for r in report.results if r.id == "B_turn_budget_safe")
        self.assertFalse(b_result.passed)
        self.assertIn("9", b_result.detail)
        self.assertIn("8", b_result.detail)

    def test_05_artifact_duplication(self):
        doc = _artifact_duplication()
        report = lib.run_guard(doc, document_path="<test:artifacts>")
        self.assertTrue(report.blocking, msg=report.to_human_readable())
        reasons = "\n".join(report.blocking_reasons)
        self.assertIn("C_artifact_uniqueness", reasons)
        c_result = next(r for r in report.results if r.id == "C_artifact_uniqueness")
        self.assertFalse(c_result.passed)
        self.assertIn("photo_pair", c_result.detail)

    def test_06_missing_mandatory_echo(self):
        doc = _missing_mandatory_echoes()
        report = lib.run_guard(doc, document_path="<test:mandatory_missing>")
        self.assertEqual(report.document_kind, "scene_contract")
        self.assertTrue(report.blocking, msg=report.to_human_readable())
        reasons = "\n".join(report.blocking_reasons)
        self.assertIn("D_mandatory_echo_declared", reasons)
        d_result = next(r for r in report.results if r.id == "D_mandatory_echo_declared")
        self.assertFalse(d_result.passed)
        self.assertIn("mandatory_echoes", d_result.detail)

    def test_07_mandatory_echo_npc_mismatch(self):
        doc = _mandatory_echo_npc_mismatch()
        report = lib.run_guard(doc, document_path="<test:npc_mismatch>")
        self.assertTrue(report.blocking, msg=report.to_human_readable())
        reasons = "\n".join(report.blocking_reasons)
        self.assertIn("E_npc_recall_within_mandatory", reasons)
        e_result = next(r for r in report.results if r.id == "E_npc_recall_within_mandatory")
        self.assertFalse(e_result.passed)
        self.assertIn("leila_2024_reunion", e_result.detail)


# ---------------------------------------------------------------------------
# Coverage tests — every branch in four_questions_guard_lib
# ---------------------------------------------------------------------------


class TestStructuralCoverage(unittest.TestCase):
    """Branch coverage for the helper layer."""

    def test_detect_document_kind_scene_contract(self):
        self.assertEqual(
            lib.detect_document_kind({"required_anchors": [], "allowed_beats": []}),
            "scene_contract",
        )

    def test_detect_document_kind_interaction(self):
        self.assertEqual(
            lib.detect_document_kind({"causal_seeds": []}),
            "interaction",
        )
        self.assertEqual(
            lib.detect_document_kind({"turn_budget": {}}),
            "interaction",
        )
        self.assertEqual(
            lib.detect_document_kind({"belief_updates": []}),
            "interaction",
        )

    def test_detect_document_kind_unknown(self):
        self.assertEqual(
            lib.detect_document_kind({"foo": "bar"}),
            "unknown",
        )

    def test_load_document_yaml(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fp:
            fp.write("sceneId: test_scene\nartifact_updates: []\n")
            path = fp.name
        try:
            doc = lib.load_document(path)
            self.assertEqual(doc["sceneId"], "test_scene")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_document_json(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fp:
            json.dump({"sceneId": "json_test"}, fp)
            path = fp.name
        try:
            doc = lib.load_document(path)
            self.assertEqual(doc["sceneId"], "json_test")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_document_empty_raises(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fp:
            fp.write("")
            path = fp.name
        try:
            with self.assertRaises(ValueError):
                lib.load_document(path)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_document_non_mapping_raises(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fp:
            fp.write("[1, 2, 3]")
            path = fp.name
        try:
            with self.assertRaises(ValueError):
                lib.load_document(path)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_run_guard_with_check_filter(self):
        doc = _passing_interaction()
        report = lib.run_guard(doc, document_path="<t>", check_ids=["Q1_changes_world_state"])
        self.assertEqual(len(report.results), 1)
        self.assertEqual(report.results[0].id, "Q1_changes_world_state")

    def test_run_guard_rejects_unknown_check(self):
        with self.assertRaises(ValueError):
            lib.run_guard({}, check_ids=["Z_not_a_real_check"])

    def test_report_to_human_readable_does_not_crash(self):
        doc = _passing_interaction()
        report = lib.run_guard(doc)
        text = report.to_human_readable()
        self.assertIn("PASS", text)
        self.assertIn("Q1", text)

    def test_check_q3_with_action_whitelist_change(self):
        doc = {
            "action_whitelist_change": {
                "added": ["silence"],
                "removed": ["destroy"],
            }
        }
        result = lib.check_q3_available_actions(doc)
        self.assertTrue(result.passed)
        self.assertIn("silence", result.detail)

    def test_check_q4_with_only_causal_seeds(self):
        doc = {"causal_seeds": [{"seedId": "x", "planted": True}]}
        result = lib.check_q4_future_echo(doc)
        self.assertTrue(result.passed)
        self.assertIn("x", result.detail)

    def test_check_q4_with_only_far_echo_routes(self):
        doc = {"far_echo_routes": [{"targetSceneId": "future", "seedIds": ["s1"]}]}
        result = lib.check_q4_future_echo(doc)
        self.assertTrue(result.passed)
        self.assertIn("future", result.detail)

    def test_check_a_skipped_when_no_forbidden(self):
        result = lib.check_a_forbidden_reveal({})
        self.assertTrue(result.passed)
        self.assertTrue(result.detail.startswith("skipped"))

    def test_check_a_skipped_when_forbidden_has_no_keys(self):
        result = lib.check_a_forbidden_reveal({"forbidden_reveals": [{"reason": "r"}]})
        self.assertTrue(result.passed)
        self.assertTrue(result.detail.startswith("skipped"))

    def test_check_a_violation_via_narrative_field(self):
        doc = {
            "forbidden_reveals": [{"revealKey": "secret_x", "reason": "r"}],
            "narrative": "今天我打算告诉你 secret_x 的全部",
        }
        result = lib.check_a_forbidden_reveal(doc)
        self.assertFalse(result.passed)
        self.assertIn("narrative", result.detail)

    def test_check_b_skipped_when_only_one_declared(self):
        # Only current_turn — no max_turns.
        result = lib.check_b_turn_budget_safe({"turn_budget": {"current_turn": 3}})
        self.assertTrue(result.passed)
        self.assertTrue(result.detail.startswith("skipped"))

    def test_check_b_uses_canonical_state(self):
        doc = {
            "turn_budget": {"max_turns": 8},
            "canonicalState": {"turnIndex": 3},
        }
        result = lib.check_b_turn_budget_safe(doc)
        self.assertTrue(result.passed)
        self.assertIn("3", result.detail)
        self.assertIn("8", result.detail)

    def test_check_b_uses_top_level_turnIndex(self):
        doc = {"turnIndex": 4, "max_turns": 8}
        result = lib.check_b_turn_budget_safe(doc)
        self.assertTrue(result.passed)

    def test_check_c_skipped_when_no_artifacts(self):
        result = lib.check_c_artifact_uniqueness({})
        self.assertTrue(result.passed)
        self.assertTrue(result.detail.startswith("skipped"))

    def test_check_c_uses_artifactState_fallback(self):
        doc = {
            "artifactState": [
                {"artifactId": "a1", "ownerId": "leila", "state": "x"},
                {"artifactId": "a2", "ownerId": "arash", "state": "y"},
            ]
        }
        result = lib.check_c_artifact_uniqueness(doc)
        self.assertTrue(result.passed)
        # Per-artifact evidence is in the evidence list, not in detail.
        self.assertIn("a1", " ".join(result.evidence))
        self.assertIn("a2", " ".join(result.evidence))

    def test_check_c_uses_artifact_updates_fallback(self):
        doc = {
            "artifact_updates": [
                {"artifactId": "a1", "newOwnerId": "leila"},
            ]
        }
        result = lib.check_c_artifact_uniqueness(doc)
        self.assertTrue(result.passed)

    def test_check_d_skipped_on_interaction(self):
        doc = _passing_interaction()  # an interaction, not a scene contract
        result = lib.check_d_mandatory_echo_declared(doc)
        self.assertTrue(result.passed)
        self.assertTrue(result.detail.startswith("skipped"))

    def test_check_d_passes_when_mandatory_listed(self):
        doc = {
            "required_anchors": [],
            "allowed_beats": [],
            "mandatory_echoes": [{"id": "x"}],
        }
        result = lib.check_d_mandatory_echo_declared(doc)
        self.assertTrue(result.passed)
        self.assertIn("1 mandatory", result.detail)

    def test_check_e_skipped_when_no_npc_raised(self):
        result = lib.check_e_npc_recall_within_mandatory({})
        self.assertTrue(result.passed)
        self.assertTrue(result.detail.startswith("skipped"))

    def test_check_e_skipped_when_no_anchors(self):
        doc = {
            "npc_raised_echoes": [{"id": "x", "speaker": "arash", "line": "..."}],
        }
        result = lib.check_e_npc_recall_within_mandatory(doc)
        self.assertTrue(result.passed)
        self.assertTrue(result.detail.startswith("skipped"))

    def test_check_e_passes_when_all_in_mandatory(self):
        doc = {
            "mandatory_echoes": [{"id": "x"}],
            "npc_raised_echoes": [
                {"id": "x", "speaker": "arash", "line": "...", "inMandatoryList": True},
            ],
        }
        result = lib.check_e_npc_recall_within_mandatory(doc)
        self.assertTrue(result.passed)

    def test_check_e_uses_inherited_mandatory(self):
        doc = {
            "inherited_mandatory_echoes": [{"id": "x"}],
            "npc_raised_echoes": [
                {"id": "x", "speaker": "arash", "line": "..."},
            ],
        }
        result = lib.check_e_npc_recall_within_mandatory(doc)
        self.assertTrue(result.passed)

    def test_blocking_policy_scene_contract_q_advisory(self):
        # Scene contract with no Q1 material should not block on Q1
        # (it's a declaration, not a runtime event).
        doc = _missing_mandatory_echoes()  # already a scene contract without mandatory
        report = lib.run_guard(doc, document_path="<t>")
        # Q1 is failing but not blocking
        q1 = next(r for r in report.results if r.id == "Q1_changes_world_state")
        self.assertFalse(q1.passed)
        # blocking reasons should only include D
        self.assertTrue(all(r.startswith("D_") for r in report.blocking_reasons),
                        msg=f"unexpected blockers: {report.blocking_reasons}")

    def test_blocking_policy_interaction_q_strict(self):
        # An interaction that fails Q1 should block on Q1.
        doc = _blocking_q1()
        report = lib.run_guard(doc, document_path="<t>")
        self.assertTrue(report.blocking)
        self.assertTrue(any("Q1_" in r for r in report.blocking_reasons))

    def test_as_list_scalar(self):
        # A scalar (non-list) value is wrapped in a single-element list.
        result = lib._as_list("hello")
        self.assertEqual(result, ["hello"])
        result = lib._as_list(42)
        self.assertEqual(result, [42])

    def test_nonempty_branches(self):
        self.assertFalse(lib._nonempty(None))
        self.assertFalse(lib._nonempty(""))
        self.assertFalse(lib._nonempty([]))
        self.assertFalse(lib._nonempty({}))
        self.assertTrue(lib._nonempty("x"))
        self.assertTrue(lib._nonempty([1]))
        self.assertTrue(lib._nonempty(0))  # 0 is "nonempty" by _nonempty semantics
        self.assertTrue(lib._nonempty(False))

    def test_check_q1_with_scalar_or_non_dict_entries(self):
        # exercise the `else: evidence.append(repr)` branch
        doc = {
            "artifact_updates": ["raw_string_entry"],
            "event_log": [42],
        }
        result = lib.check_q1_world_state(doc)
        self.assertTrue(result.passed)
        self.assertTrue(any("raw_string_entry" in e for e in result.evidence))
        self.assertTrue(any("42" in e for e in result.evidence))

    def test_check_q2_with_non_dict_entries(self):
        doc = {
            "belief_updates": ["raw_entry"],
            "belief_matrix": [None],
        }
        result = lib.check_q2_character_knowledge(doc)
        self.assertTrue(result.passed)
        self.assertTrue(any("raw_entry" in e for e in result.evidence))

    def test_check_q3_illegal_verb_warnings(self):
        doc = {"action_whitelist": ["investigate", "free_chat"]}
        result = lib.check_q3_available_actions(doc)
        self.assertTrue(result.passed)
        self.assertIn("free_chat", result.detail)
        self.assertIn("illegal", result.detail)

    def test_check_q4_reinforced_seeds(self):
        # Causal seed declared but NOT planted → still passes (reinforced).
        doc = {"causal_seeds": [{"seedId": "x", "planted": False}]}
        result = lib.check_q4_future_echo(doc)
        self.assertTrue(result.passed)
        self.assertIn("reinforced", result.detail)

    def test_check_q4_far_echo_routes_non_dict(self):
        doc = {"far_echo_routes": ["raw_route"]}
        result = lib.check_q4_future_echo(doc)
        self.assertTrue(result.passed)

    def test_check_a_violation_via_text_field(self):
        doc = {
            "forbidden_reveals": [{"revealKey": "secret_x", "reason": "r"}],
            "text": "I will tell you about secret_x",
        }
        result = lib.check_a_forbidden_reveal(doc)
        self.assertFalse(result.passed)

    def test_check_b_with_max_turns_alias(self):
        doc = {"turn_budget": {"current_turn": 3, "maxTurns": 8}}
        result = lib.check_b_turn_budget_safe(doc)
        self.assertTrue(result.passed)
        self.assertIn("3", result.detail)
        self.assertIn("8", result.detail)

    def test_check_b_with_max_turns_top_level(self):
        # top-level max_turns picked up after canonical turnIndex
        doc = {"turnIndex": 4, "max_turns": 8}
        result = lib.check_b_turn_budget_safe(doc)
        self.assertTrue(result.passed)
        self.assertIn("4", result.detail)

    def test_check_b_invalid_ints_skipped(self):
        doc = {"turn_budget": {"current_turn": "not_a_number", "max_turns": "still_not"}}
        result = lib.check_b_turn_budget_safe(doc)
        self.assertTrue(result.passed)
        self.assertTrue(result.detail.startswith("skipped"))

    def test_check_b_only_max_turns(self):
        # Symmetric to test_check_b_skipped_when_only_one_declared.
        result = lib.check_b_turn_budget_safe({"turn_budget": {"max_turns": 8}})
        self.assertTrue(result.passed)
        self.assertTrue(result.detail.startswith("skipped"))

    def test_check_d_with_string_mandatory_list(self):
        # mandatory_echoes can be a list of strings, not just dicts.
        doc = {
            "required_anchors": [],
            "allowed_beats": [],
            "mandatory_echoes": ["echo_a", "echo_b"],
        }
        result = lib.check_d_mandatory_echo_declared(doc)
        self.assertTrue(result.passed)
        self.assertIn("2 mandatory", result.detail)
        self.assertTrue(any("echo_a" in e for e in result.evidence))

    def test_check_e_with_string_mandatory_list(self):
        # mandatory list is plain strings; no inMandatoryList on echo.
        doc = {
            "mandatory_echoes": ["echo_a"],
            "npc_raised_echoes": [
                {"id": "echo_a", "speaker": "arash", "line": "..."},
            ],
        }
        result = lib.check_e_npc_recall_within_mandatory(doc)
        self.assertTrue(result.passed)
        # Evidence should mark the NPC-raised echo with ✓
        self.assertTrue(any("✓" in e for e in result.evidence))

    def test_ensure_yaml_raises_when_missing(self):
        # Temporarily neuter the yaml import and verify the error path.
        saved = lib.yaml
        try:
            lib.yaml = None
            with self.assertRaises(RuntimeError) as cm:
                lib._ensure_yaml()
            self.assertIn("PyYAML", str(cm.exception))
        finally:
            lib.yaml = saved

    def test_load_document_extension_routing(self):
        # A .txt file (no recognised extension) is loaded as YAML.
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fp:
            fp.write("sceneId: txt_test\nartifact_updates: []\n")
            path = fp.name
        try:
            doc = lib.load_document(path)
            self.assertEqual(doc["sceneId"], "txt_test")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_human_readable_with_evidence_overflow(self):
        # Construct a CheckResult with > 5 evidence items so the
        # "(N more)" overflow line is exercised, and pin a non-empty
        # blocking_reasons so that branch is also rendered.
        result = lib.CheckResult(
            id="X_test",
            label="test",
            passed=False,
            evidence=[f"e{i}" for i in range(8)],
            detail="synthetic detail",
        )
        report = lib.GuardReport(
            document_kind="interaction",
            document_path="<synthetic>",
            blocking=True,
            blocking_reasons=["synthetic blocker"],
            results=[result],
            summary={"passed": 0, "failed": 1, "skipped": 0, "total": 1},
        )
        text = report.to_human_readable()
        self.assertIn("more", text)
        self.assertIn("blocking reasons", text)
        self.assertIn("synthetic blocker", text)

    def test_check_q3_illegal_verb_branch(self):
        # Pass an action_whitelist with an illegal verb so the
        # `if illegal:` branch fires.
        doc = {"action_whitelist": ["investigate", "freestyle_chat"]}
        result = lib.check_q3_available_actions(doc)
        self.assertTrue(result.passed)
        self.assertIn("illegal", result.detail)
        self.assertIn("freestyle_chat", result.detail)

    def test_check_a_all_surfaces_none_continue_branch(self):
        # Every surface is None — the `continue` branch in check_a
        # must fire for each.  The check should pass because no surface
        # carries a forbidden key.
        doc = {
            "forbidden_reveals": [{"revealKey": "secret_x", "reason": "r"}],
            # No utterance / narrative / text / dialogue / revealed_keys
        }
        result = lib.check_a_forbidden_reveal(doc)
        self.assertTrue(result.passed)
        self.assertIn("0 surfaces", result.detail)

    def test_check_b_falls_back_to_top_level_max_turns(self):
        # No canonicalState; only top-level max_turns is supplied.
        doc = {"turnIndex": 5, "max_turns": 10}
        result = lib.check_b_turn_budget_safe(doc)
        self.assertTrue(result.passed)
        self.assertIn("5", result.detail)
        self.assertIn("10", result.detail)

    def test_check_b_invalid_top_level(self):
        # top-level max_turns is a non-numeric string — silent skip
        doc = {"turnIndex": 4, "max_turns": "ten"}
        result = lib.check_b_turn_budget_safe(doc)
        self.assertTrue(result.passed)
        self.assertTrue(result.detail.startswith("skipped"))

    def test_check_e_with_string_mandatory_and_string_id_echo(self):
        # mandatory_echoes is a list of strings AND npc_raised_echoes
        # has a string id — exercises the `else: mandatory_ids.add`
        # branch and the `or echo.get("seedId")` fallback.
        doc = {
            "mandatory_echoes": ["echo_a"],
            "npc_raised_echoes": [
                {"seedId": "echo_a", "speaker": "arash", "line": "..."},
            ],
        }
        result = lib.check_e_npc_recall_within_mandatory(doc)
        self.assertTrue(result.passed)
        # The echo should be marked ✓ (in mandatory list)
        self.assertTrue(any("✓" in e for e in result.evidence))

    def test_check_q3_turn_budget_change_branch(self):
        # Exercise the `turn_budget_change` block of check_q3.
        doc = {
            "turn_budget": {"total": 8, "give": 3},
            "turn_budget_change": {"delta_total": 0, "delta_actions": {"give": -1}},
        }
        result = lib.check_q3_available_actions(doc)
        self.assertTrue(result.passed)
        self.assertIn("turn_budget_change", result.detail)

    def test_check_q4_non_dict_causal_seed_skipped(self):
        # Exercise the `if not isinstance(seed, dict): continue` branch
        # in check_q4.  Mixed list: one real seed, one bare string.
        doc = {
            "causal_seeds": [
                "raw_string",
                {"seedId": "real_seed", "planted": True},
            ]
        }
        result = lib.check_q4_future_echo(doc)
        self.assertTrue(result.passed)
        self.assertIn("real_seed", result.detail)
        # The raw string should be silently skipped, not crash
        self.assertNotIn("raw_string", " ".join(result.evidence))

    def test_check_a_list_surface_violation(self):
        # Exercise the `if isinstance(surface_value, list):` branch of
        # check_a by passing the forbidden key inside a list field.
        doc = {
            "forbidden_reveals": [{"revealKey": "secret_x", "reason": "r"}],
            "revealed_keys": ["secret_x"],
        }
        result = lib.check_a_forbidden_reveal(doc)
        self.assertFalse(result.passed)
        self.assertIn("revealed_keys", result.detail)

    def test_check_b_invalid_turn_index_falls_back(self):
        # canonicalState.turnIndex is non-numeric → falls back to top-level
        # turnIndex.  Exercises the `except` branches at 604-605 and
        # 609-610.
        doc = {
            "canonicalState": {"turnIndex": "garbage"},
            "turnIndex": 5,
            "max_turns": 8,
        }
        result = lib.check_b_turn_budget_safe(doc)
        self.assertTrue(result.passed)
        self.assertIn("5", result.detail)

    def test_check_b_invalid_top_level_turn_index(self):
        # top-level turnIndex is non-numeric — exercises the
        # `except (TypeError, ValueError): pass` branch at 609-610.
        # Neither canonicalState nor top-level turnIndex can be coerced
        # to int, so both except branches fire; the check ends up
        # skipped when no max_turns is present either.
        doc = {
            "canonicalState": {"turnIndex": "garbage"},
            "turnIndex": "still_garbage",
        }
        result = lib.check_b_turn_budget_safe(doc)
        self.assertTrue(result.passed)
        self.assertTrue(result.detail.startswith("skipped"))

    def test_check_e_skips_non_dict_npc_raised(self):
        # npc_raised_echoes contains a non-dict entry that should be
        # silently skipped, not crash.
        doc = {
            "mandatory_echoes": ["echo_a"],
            "npc_raised_echoes": [
                "raw_string_not_a_dict",
                {"id": "echo_a", "speaker": "arash", "line": "...", "inMandatoryList": True},
            ],
        }
        result = lib.check_e_npc_recall_within_mandatory(doc)
        self.assertTrue(result.passed)


# ---------------------------------------------------------------------------
# CLI / I/O tests — exercise the wrapper end to end
# ---------------------------------------------------------------------------


class TestCliWrapper(unittest.TestCase):
    """Smoke tests for the CLI tool.  These do not spawn a subprocess —
    they call the ``main`` entrypoint directly so failures are visible
    in the test log."""

    def setUp(self):
        # The CLI is a ``tools/four-questions-guard.py`` file with a
        # dash in its name, so we cannot import it with the normal
        # ``import`` statement — use importlib to load it as
        # ``four_questions_guard_cli`` instead.
        import importlib.util
        if str(_TOOLS) not in sys.path:
            sys.path.insert(0, str(_TOOLS))
        cli_path = _TOOLS / "four-questions-guard.py"
        spec = importlib.util.spec_from_file_location("four_questions_guard_cli", cli_path)
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)  # type: ignore[union-attr]

    def _write(self, doc: dict, suffix: str = ".yaml") -> str:
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as fp:
            if suffix.endswith(".json"):
                json.dump(doc, fp, ensure_ascii=False)
            else:
                import yaml  # local import to keep this test self-contained
                yaml.safe_dump(doc, fp, allow_unicode=True)
            return fp.name

    def test_cli_passing_returns_zero(self):
        path = self._write(_passing_interaction())
        try:
            rc = self.cli.main([path, "--quiet", "--json"])
            self.assertEqual(rc, 0, "passing interaction should return 0")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cli_blocking_returns_one(self):
        path = self._write(_blocking_q1())
        try:
            rc = self.cli.main([path, "--quiet", "--json"])
            self.assertEqual(rc, 1, "Q1-missing interaction should return 1")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cli_missing_file_returns_two(self):
        rc = self.cli.main(["/this/file/does/not/exist.yaml", "--quiet", "--json"])
        self.assertEqual(rc, 2, "missing file should return 2 (I/O error)")

    def test_cli_json_output_is_valid_json(self):
        path = self._write(_passing_interaction())
        try:
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = self.cli.main([path, "--quiet", "--json"])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["version"], "1.0.0")
            self.assertEqual(payload["summary"]["total_documents"], 1)
            self.assertEqual(payload["summary"]["blocking_documents"], 0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cli_strict_treats_skip_as_fail(self):
        # An empty doc would normally skip most checks; --strict should
        # convert those skips to failures and block the PR.
        path = self._write({})
        try:
            rc = self.cli.main([path, "--quiet", "--strict", "--json"])
            self.assertEqual(rc, 1, "strict mode should block on skips")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cli_check_filter(self):
        path = self._write(_passing_interaction())
        try:
            rc = self.cli.main([
                path, "--quiet", "--json",
                "--checks", "Q1_changes_world_state,Q4_creates_future_echo",
            ])
            self.assertEqual(rc, 0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cli_unknown_check_exits_nonzero(self):
        path = self._write(_passing_interaction())
        try:
            with self.assertRaises(SystemExit) as cm:
                self.cli.main([path, "--checks", "Z_unknown"])
            self.assertNotEqual(cm.exception.code, 0)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cli_version(self):
        with self.assertRaises(SystemExit) as cm:
            self.cli.main(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_cli_human_output_for_blocking(self):
        # Drive the human-output branch.
        path = self._write(_blocking_q1())
        try:
            import io
            from contextlib import redirect_stderr, redirect_stdout
            err = io.StringIO()
            out = io.StringIO()
            with redirect_stderr(err), redirect_stdout(out):
                rc = self.cli.main([path, "--human"])
            self.assertEqual(rc, 1)
            # err should contain the human-readable BLOCK summary
            self.assertIn("BLOCK", err.getvalue())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cli_human_output_for_passing(self):
        path = self._write(_passing_interaction())
        try:
            import io
            from contextlib import redirect_stderr, redirect_stdout
            err = io.StringIO()
            out = io.StringIO()
            with redirect_stderr(err), redirect_stdout(out):
                rc = self.cli.main([path, "--human"])
            self.assertEqual(rc, 0)
            self.assertIn("PASS", err.getvalue())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cli_multiple_documents_summary(self):
        a = self._write(_passing_interaction())
        b = self._write(_blocking_q1())
        try:
            import io
            from contextlib import redirect_stderr, redirect_stdout
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = self.cli.main([a, b, "--quiet", "--json"])
            self.assertEqual(rc, 1)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["summary"]["total_documents"], 2)
            self.assertEqual(payload["summary"]["blocking_documents"], 1)
            self.assertEqual(payload["summary"]["passing_documents"], 1)
        finally:
            Path(a).unlink(missing_ok=True)
            Path(b).unlink(missing_ok=True)

    def test_cli_multiple_documents_human_output(self):
        # Two documents → triggers the `\n` separator line in
        # _emit_human (line 156).
        a = self._write(_passing_interaction())
        b = self._write(_passing_interaction())
        try:
            import io
            from contextlib import redirect_stderr, redirect_stdout
            err = io.StringIO()
            out = io.StringIO()
            with redirect_stderr(err), redirect_stdout(out):
                rc = self.cli.main([a, b, "--human"])
            self.assertEqual(rc, 0)
            # The two reports should be separated by a blank line.
            self.assertIn("all 2 document(s) pass", err.getvalue())
        finally:
            Path(a).unlink(missing_ok=True)
            Path(b).unlink(missing_ok=True)

    def test_cli_subprocess_invocation(self):
        # The `if __name__ == "__main__":` block runs the CLI as a
        # subprocess.  This catches regressions in the entry point
        # itself (e.g. import errors that only fire on cold start).
        import subprocess
        path = self._write(_passing_interaction())
        try:
            result = subprocess.run(
                [sys.executable, str(_TOOLS / "four-questions-guard.py"),
                 "--quiet", "--json", path],
                capture_output=True, text=True, encoding="utf-8", timeout=10,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["summary"]["blocking_documents"], 0)
        finally:
            Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Integration with the real W1-C scene contracts
# ---------------------------------------------------------------------------


class TestRealSceneContracts(unittest.TestCase):
    """Run the guard against the W1-C contracts to verify the tool
    behaves sensibly on real input.

    These scenes have been updated to include a ``mandatory_echoes``
    list (decision-3 compliance), so the D check passes.  The
    remaining checks (Q1, Q2) fail because scene contracts are
    declarative — the runtime Q1/Q2/Q4 material is filled in by the
    Resolver.  Per the blocking policy in ``run_guard`` these
    are advisory on scene contracts, so the scene should still
    PASS overall (only D / A are blocking for the contract kind).
    """

    def setUp(self):
        self.scenes_dir = Path(__file__).resolve().parents[2] / "content" / "case_01_revolution_street" / "scenes"
        if not self.scenes_dir.is_dir():
            self.skipTest(f"no W1-C scenes at {self.scenes_dir}")

    def test_photo_lab_passes_with_mandatory_echoes(self):
        path = self.scenes_dir / "photo_lab_2008.yaml"
        if not path.exists():
            self.skipTest(f"missing scene: {path}")
        report = lib.run_guard(lib.load_document(str(path)), document_path=str(path))
        # D should pass — mandatory_echoes is declared.
        d = next(r for r in report.results if r.id == "D_mandatory_echo_declared")
        self.assertTrue(d.passed, msg=f"D should pass: {d.detail}")
        # Q4 should pass — far_echo_routes is filled in.
        q4 = next(r for r in report.results if r.id == "Q4_creates_future_echo")
        self.assertTrue(q4.passed, msg=f"Q4 should pass: {q4.detail}")
        # The contract should NOT be blocked — Q1/Q2 are advisory on
        # scene contracts (they're runtime fields).
        self.assertFalse(report.blocking, msg=report.to_human_readable())

    def test_farewell_passes_with_mandatory_echoes(self):
        path = self.scenes_dir / "farewell_2011.yaml"
        if not path.exists():
            self.skipTest(f"missing scene: {path}")
        report = lib.run_guard(lib.load_document(str(path)), document_path=str(path))
        d = next(r for r in report.results if r.id == "D_mandatory_echo_declared")
        self.assertTrue(d.passed, msg=f"D should pass: {d.detail}")
        self.assertFalse(report.blocking, msg=report.to_human_readable())

    def test_reunion_passes_with_mandatory_echoes(self):
        path = self.scenes_dir / "reunion_2024.yaml"
        if not path.exists():
            self.skipTest(f"missing scene: {path}")
        report = lib.run_guard(lib.load_document(str(path)), document_path=str(path))
        d = next(r for r in report.results if r.id == "D_mandatory_echo_declared")
        self.assertTrue(d.passed, msg=f"D should pass: {d.detail}")
        self.assertFalse(report.blocking, msg=report.to_human_readable())

    def test_real_scene_missing_mandatory_blocks(self):
        # Build a synthetic scene without mandatory_echoes and verify
        # the D check blocks.  This is the contract-level negative
        # test — it documents what the tool would do if a future
        # W1-C update accidentally drops the mandatory_echoes list.
        path = self.scenes_dir / "photo_lab_2008.yaml"
        if not path.exists():
            self.skipTest(f"missing scene: {path}")
        doc = lib.load_document(str(path))
        doc.pop("mandatory_echoes", None)
        report = lib.run_guard(doc, document_path=str(path))
        self.assertTrue(report.blocking, msg=report.to_human_readable())
        self.assertTrue(
            any("D_mandatory_echo_declared" in r for r in report.blocking_reasons),
            msg=f"D should be the blocker: {report.blocking_reasons}",
        )


if __name__ == "__main__":
    unittest.main()
