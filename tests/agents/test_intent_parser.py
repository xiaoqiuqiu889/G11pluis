"""IntentParser unit tests.

Covers:

* LLM success path (json_object strict mode) — 12-value vocab mapping
* LLM misshape → single retry → success
* LLM misshape → single retry → failure → L3 fallback (silence)
* Schema validation enforces 12-value actionType enum
* Schema validation enforces target/evidence constraints
* Temperature is clamped to [0.2, 0.5] (decision 5 / brief)
* max_output_tokens clamped to <= 800 (decision 5 hard red-line)
* Empty utterance short-circuits to silence (no LLM call)
"""

from __future__ import annotations

import sys
import unittest
import uuid

sys.path.insert(0, "server")

from agents import (  # noqa: E402
    INTENT_PARSER_VERSION,
    IntentParser,
    IntentParseError,
    ParsedPlayerAction,
    StubModelGateway,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scene_contract(actions: list[str] | None = None) -> dict:
    return {
        "sceneId": "photo_lab_2008",
        "title": "地下放映室",
        "era": "2008",
        "core_conflict": "如何分配两张同版毕业照",
        "allowed_actions": actions or [
            "investigate", "reveal", "conceal", "question", "confront",
            "comfort", "give", "destroy", "promise", "wait", "leave", "silence",
        ],
    }


def _ok_payload(**overrides) -> dict:
    base = {
        "runId": str(uuid.uuid4()),
        "sceneId": "photo_lab_2008",
        "actionType": "question",
        "actorId": "player",
        "targetId": "arash",
        "evidenceIds": [],
        "utterance": "那张照片里是谁?",
        "tone": "hesitant",
        "disclosureLevel": 0.5,
        "isDeceptive": False,
        "clientActionId": str(uuid.uuid4()),
        "expectedEventSequence": 0,
        "schemaVersion": "1.0.0",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TemperatureClampTests(unittest.TestCase):
    """Decision 5 / brief: temperature ∈ [0.2, 0.5]."""

    def test_constructor_accepts_low_boundary(self) -> None:
        gw = StubModelGateway()
        IntentParser(gw, temperature=0.2)  # no error

    def test_constructor_accepts_high_boundary(self) -> None:
        gw = StubModelGateway()
        IntentParser(gw, temperature=0.5)  # no error

    def test_constructor_rejects_below(self) -> None:
        with self.assertRaises(ValueError):
            IntentParser(StubModelGateway(), temperature=0.1)

    def test_constructor_rejects_above(self) -> None:
        with self.assertRaises(ValueError):
            IntentParser(StubModelGateway(), temperature=0.6)


class MaxOutputTokenClampTests(unittest.TestCase):
    """Decision 5 hard red-line: < 800 tokens."""

    def test_default_is_safe(self) -> None:
        gw = StubModelGateway()
        p = IntentParser(gw)
        self.assertLessEqual(p.max_output_tokens, 800)

    def test_explicit_value_too_high(self) -> None:
        with self.assertRaises(ValueError):
            IntentParser(StubModelGateway(), max_output_tokens=900)


class SuccessPathTests(unittest.TestCase):
    """The happy path: LLM emits a valid PlayerAction, parser returns it."""

    def test_first_attempt_succeeds(self) -> None:
        gw = StubModelGateway()
        gw.register("intent_parser", "player_action", _ok_payload())
        parser = IntentParser(gw)
        result = parser.parse(
            run_id=str(uuid.uuid4()),
            scene_id="photo_lab_2008",
            actor_id="player",
            utterance="那张照片里是谁?",
            scene_contract=_scene_contract(),
        )
        self.assertIsInstance(result, ParsedPlayerAction)
        self.assertEqual(result.retries, 0)
        self.assertFalse(result.fallback_used)
        self.assertEqual(result.action["actionType"], "question")
        self.assertEqual(result.action["targetId"], "arash")
        self.assertEqual(result.action["schemaVersion"], "1.0.0")

    def test_llm_omits_optional_fields_get_filled(self) -> None:
        gw = StubModelGateway()
        gw.register("intent_parser", "player_action", {
            "actionType": "give",
            "targetId": "arash",
            "evidenceIds": ["photo_pair"],
        })
        parser = IntentParser(gw)
        run_id = str(uuid.uuid4())
        result = parser.parse(
            run_id=run_id,
            scene_id="photo_lab_2008",
            actor_id="leila",
            utterance="这张给你",
            scene_contract=_scene_contract(),
        )
        self.assertEqual(result.action["runId"], run_id)
        self.assertEqual(result.action["actorId"], "leila")
        self.assertEqual(result.action["schemaVersion"], "1.0.0")
        self.assertIn("clientActionId", result.action)
        # Schema enforces evidenceIds non-empty for 'give'
        self.assertEqual(result.action["evidenceIds"], ["photo_pair"])


class RetryPathTests(unittest.TestCase):
    """First attempt fails; second attempt succeeds; retries=1."""

    def test_retry_recovers_from_invalid_json(self) -> None:
        # The stub returns a non-dict on first call, a valid one
        # on the second.  We achieve this by registering only
        # one valid response but injecting failure via a wrapper.
        called = {"n": 0}

        class FlakeyGateway:
            def complete(self_inner, request):  # type: ignore[no-untyped-def]
                called["n"] += 1
                if called["n"] == 1:
                    raise ValueError("simulated invalid json")
                from agents import ModelResponse
                return ModelResponse(
                    payload=_ok_payload(),
                    model="stub",
                    input_tokens=10,
                    output_tokens=10,
                    latency_ms=1,
                )

        parser = IntentParser(FlakeyGateway())  # type: ignore[arg-type]
        result = parser.parse(
            run_id=str(uuid.uuid4()),
            scene_id="photo_lab_2008",
            actor_id="player",
            utterance="hello",
            scene_contract=_scene_contract(),
        )
        self.assertEqual(result.retries, 1)
        self.assertFalse(result.fallback_used)


class FallbackPathTests(unittest.TestCase):
    """Two failures → L3 hard-degradation mainline (silence)."""

    def test_two_failures_emit_silence(self) -> None:
        class AlwaysFail:
            def complete(self_inner, request):  # type: ignore[no-untyped-def]
                raise ValueError("LLM is down")

        parser = IntentParser(AlwaysFail())  # type: ignore[arg-type]
        result = parser.parse(
            run_id=str(uuid.uuid4()),
            scene_id="photo_lab_2008",
            actor_id="player",
            utterance="hello",
            scene_contract=_scene_contract(),
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.retries, 1)
        self.assertEqual(result.action["actionType"], "silence")
        self.assertEqual(result.action["disclosureLevel"], 0.0)

    def test_empty_utterance_short_circuits(self) -> None:
        """No utterance → emit silence without calling the LLM."""

        class ShouldNotBeCalled:
            def complete(self_inner, request):  # type: ignore[no-untyped-def]
                raise AssertionError("LLM must not be called for empty utterance")

        parser = IntentParser(ShouldNotBeCalled())  # type: ignore[arg-type]
        result = parser.parse(
            run_id=str(uuid.uuid4()),
            scene_id="photo_lab_2008",
            actor_id="player",
            utterance="",
            scene_contract=_scene_contract(),
        )
        # Empty utterance is a deterministic short-circuit; we
        # emit silence without spending an LLM call.  It's
        # treated as a (benign) fallback for accounting purposes.
        self.assertEqual(result.action["actionType"], "silence")
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.confidence, 1.0)


class SchemaEnforcementTests(unittest.TestCase):
    """The 12-value vocab and target/evidence constraints are enforced."""

    def test_invalid_action_type_rejected(self) -> None:
        gw = StubModelGateway()
        gw.register(
            "intent_parser",
            "player_action",
            _ok_payload(actionType="hug"),  # not in 12-value vocab
        )
        parser = IntentParser(gw)
        # The first attempt fails; the retry also fails because
        # the stub returns the same bad payload.  Result: fallback.
        result = parser.parse(
            run_id=str(uuid.uuid4()),
            scene_id="photo_lab_2008",
            actor_id="player",
            utterance="hug him",
            scene_contract=_scene_contract(),
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.action["actionType"], "silence")

    def test_question_requires_target_id(self) -> None:
        gw = StubModelGateway()
        gw.register(
            "intent_parser",
            "player_action",
            _ok_payload(actionType="question", targetId=None),
        )
        parser = IntentParser(gw)
        result = parser.parse(
            run_id=str(uuid.uuid4()),
            scene_id="photo_lab_2008",
            actor_id="player",
            utterance="who are you?",
            scene_contract=_scene_contract(),
        )
        self.assertTrue(result.fallback_used)

    def test_give_requires_evidence_ids(self) -> None:
        gw = StubModelGateway()
        gw.register(
            "intent_parser",
            "player_action",
            _ok_payload(actionType="give", targetId="arash", evidenceIds=[]),
        )
        parser = IntentParser(gw)
        result = parser.parse(
            run_id=str(uuid.uuid4()),
            scene_id="photo_lab_2008",
            actor_id="leila",
            utterance="take this",
            scene_contract=_scene_contract(),
        )
        self.assertTrue(result.fallback_used)


class VersionTest(unittest.TestCase):
    def test_version_is_pinned(self) -> None:
        self.assertEqual(INTENT_PARSER_VERSION, "1.0.0")


class FreeFormChatForbiddenTest(unittest.TestCase):
    """V0.1 lesson 1: free-form chat is structurally forbidden.

    If the LLM emits a non-dict payload (a string of prose), the
    parser must reject and fall back — never pass prose through.
    """

    def test_prose_payload_rejected(self) -> None:
        from agents import ModelResponse

        class ProseGateway:
            def complete(self_inner, request):  # type: ignore[no-untyped-def]
                return ModelResponse(
                    payload="I think the player wants to hug Arash.",  # type: ignore[arg-type]
                    model="stub",
                    input_tokens=10,
                    output_tokens=10,
                    latency_ms=1,
                )

        parser = IntentParser(ProseGateway())  # type: ignore[arg-type]
        result = parser.parse(
            run_id=str(uuid.uuid4()),
            scene_id="photo_lab_2008",
            actor_id="player",
            utterance="hug him",
            scene_contract=_scene_contract(),
        )
        # 2 prose attempts → L3 fallback
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.action["actionType"], "silence")


if __name__ == "__main__":
    unittest.main()
