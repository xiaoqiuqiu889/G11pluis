"""Unit tests for the model-layer 4-level degradation chain.

The engine-layer degradation chain is in
:mod:`server.engine.degradation`; these tests target the
**model-layer** chain in :mod:`server.model.degradation`.

What is covered
---------------

* L1 fires on a single NPC task failure
* L2 fires on a single Director task failure
* L3 fires after two consecutive failures (any task)
* L3 is monotonic (does not drop back to L2)
* L4 fires on PersistFailureError
* :func:`run_with_chain` returns the writer payload on failure
* :func:`run_with_chain` returns the LLM result on success
* The writer payload surfaces the right L1/L2/L3/L4 level
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "server"))

from model import (  # noqa: E402
    CostController,
    FallbackContentLoader,
    MockProvider,
    ModelDegradationChain,
    ModelDegradationLevel,
    ModelGateway,
    ModelRequest,
    Message,
    MessageRole,
    TaskType,
    WriterPayload,
    build_default_router,
    run_with_chain,
    trigger_l1,
    trigger_l2,
    trigger_l3,
    trigger_l4,
)
from model.degradation import LEVEL_ORDER  # noqa: E402
from model.exceptions import (  # noqa: E402
    PersistFailureError,
    ProviderTimeoutError,
    SchemaValidationError,
)


def _chain(scene_id: str = "photo_lab_2008") -> ModelDegradationChain:
    return ModelDegradationChain(
        run_id=str(uuid.uuid4()),
        scene_id=scene_id,
    )


def _fallback() -> object:
    """A simple fallback content for tests."""

    from model import ModelFallbackContent, ModelNPCFallbackLine
    return ModelFallbackContent(
        case_slug="case_01_revolution_street",
        scene_id="photo_lab_2008",
        npc_lines=[
            ModelNPCFallbackLine(
                characterId="arash", sceneId="photo_lab_2008",
                actionType="comfort",
                line="[hard-coded] 阿拉什的目光落在相纸上。",
                speechIntent="remain_silent",
            ),
            ModelNPCFallbackLine(
                characterId="leila", sceneId="photo_lab_2008",
                actionType="question",
                line="[hard-coded] 莱拉侧过脸。",
                speechIntent="question",
            ),
        ],
        director_skip_line="[hard-coded] 节拍暂时跳过，由备选叙事接续。",
        hard_lines={
            "beat_divide_photos": "[hard-coded] 两人在暗房里分享相纸的沉默。",
        },
        persist_message="服务暂不可用，本轮进度已为您保留。",
    )


# ---------------------------------------------------------------------------
# L1
# ---------------------------------------------------------------------------


class L1Tests(unittest.TestCase):

    def test_l1_fires_on_npc_failure(self) -> None:
        chain = _chain()
        fb = _fallback()
        payload = trigger_l1(
            chain, fallback=fb,
            characterId="arash", actionType="comfort",
            error="provider timeout",
        )
        self.assertEqual(payload.level, ModelDegradationLevel.L1)
        self.assertEqual(payload.source, "npc_line")
        self.assertIn("阿拉什", payload.content)
        self.assertEqual(chain.current_level, ModelDegradationLevel.L1)
        self.assertEqual(len(chain.records), 1)
        self.assertEqual(chain.records[0].trigger, "npc_timeout")

    def test_l1_unknown_character_falls_back_to_action(self) -> None:
        chain = _chain()
        fb = _fallback()
        payload = trigger_l1(
            chain, fallback=fb,
            characterId="nonexistent", actionType="comfort",
            error="x",
        )
        # Action-only fallback matches the first arash/comfort line
        self.assertIn("阿拉什", payload.content)


# ---------------------------------------------------------------------------
# L2
# ---------------------------------------------------------------------------


class L2Tests(unittest.TestCase):

    def test_l2_fires_on_director_timeout(self) -> None:
        chain = _chain()
        fb = _fallback()
        payload = trigger_l2(
            chain, fallback=fb,
            beat_id="beat_divide_photos", error="simulated 4s deadline",
        )
        self.assertEqual(payload.level, ModelDegradationLevel.L2)
        self.assertEqual(payload.source, "director_skip")
        self.assertIn("节拍暂时跳过", payload.content)
        self.assertEqual(chain.current_level, ModelDegradationLevel.L2)


# ---------------------------------------------------------------------------
# L3 (monotonic)
# ---------------------------------------------------------------------------


class L3Tests(unittest.TestCase):

    def test_l3_fires_after_two_consecutive_failures(self) -> None:
        chain = _chain()
        fb = _fallback()
        trigger_l1(chain, fallback=fb, characterId="arash",
                   actionType="comfort", error="first")
        # Now escalate to L3 (manually simulating 2nd failure).
        payload = trigger_l3(
            chain, fallback=fb, beat_id="beat_divide_photos",
            error="second",
        )
        self.assertEqual(payload.level, ModelDegradationLevel.L3)
        self.assertEqual(chain.current_level, ModelDegradationLevel.L3)
        self.assertTrue(chain.is_at_least(ModelDegradationLevel.L3))

    def test_l3_does_not_drop_back_to_l2(self) -> None:
        chain = _chain()
        fb = _fallback()
        trigger_l3(chain, fallback=fb, beat_id="b1", error="x")
        # Try to go back to L2 — monotonic, must stay L3.
        trigger_l2(chain, fallback=fb, beat_id="b2", error="y")
        self.assertEqual(chain.current_level, ModelDegradationLevel.L3)
        self.assertFalse(chain.is_at_least(ModelDegradationLevel.L4))

    def test_l3_returns_hard_line_lookup(self) -> None:
        chain = _chain()
        fb = _fallback()
        trigger_l3(chain, fallback=fb, beat_id="beat_divide_photos", error="x")
        payload = trigger_l3(chain, fallback=fb, beat_id="unknown_beat", error="y")
        # No hard line for unknown_beat → falls through to director_skip_line
        self.assertIn("节拍暂时跳过", payload.content)


# ---------------------------------------------------------------------------
# L4
# ---------------------------------------------------------------------------


class L4Tests(unittest.TestCase):

    def test_l4_fires_on_persist_failure(self) -> None:
        chain = _chain()
        fb = _fallback()
        payload = trigger_l4(chain, fallback=fb, error="DB down")
        self.assertEqual(payload.level, ModelDegradationLevel.L4)
        self.assertEqual(payload.source, "persist_message")
        self.assertIn("服务暂不可用", payload.content)
        self.assertTrue(chain.is_at_least(ModelDegradationLevel.L4))


# ---------------------------------------------------------------------------
# run_with_chain
# ---------------------------------------------------------------------------


class RunWithChainTests(unittest.TestCase):

    def test_returns_llm_result_on_success(self) -> None:
        chain = _chain()
        result, finish, level = run_with_chain(
            chain=chain,
            fallback=_fallback(),
            task_name="npc_proposer",
            primary_call=lambda: {"ok": True},
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(finish, "stop")
        self.assertIsNone(level)
        self.assertEqual(chain.consecutive_failures, 0)

    def test_l1_on_npc_timeout(self) -> None:
        chain = _chain()
        def boom() -> None:
            raise ProviderTimeoutError("simulated 4s")
        result, finish, level = run_with_chain(
            chain=chain,
            fallback=_fallback(),
            task_name="npc_proposer",
            primary_call=boom,
        )
        self.assertIsInstance(result, WriterPayload)
        self.assertEqual(finish, "fallback")
        self.assertEqual(level, "L1")
        self.assertEqual(chain.consecutive_failures, 1)

    def test_l2_on_director_timeout(self) -> None:
        chain = _chain()
        def boom() -> None:
            raise ProviderTimeoutError("simulated 4s")
        result, finish, level = run_with_chain(
            chain=chain,
            fallback=_fallback(),
            task_name="director_proposer",
            primary_call=boom,
        )
        self.assertIsInstance(result, WriterPayload)
        self.assertEqual(level, "L2")
        self.assertEqual(chain.consecutive_failures, 1)

    def test_l3_after_two_consecutive_failures(self) -> None:
        chain = _chain()
        fb = _fallback()
        def boom() -> None:
            raise ProviderTimeoutError("simulated 4s")
        run_with_chain(chain=chain, fallback=fb,
                       task_name="npc_proposer", primary_call=boom)
        run_with_chain(chain=chain, fallback=fb,
                       task_name="npc_proposer", primary_call=boom)
        # Third attempt would L3 — but we already L3'd on the 2nd.
        result, finish, level = run_with_chain(
            chain=chain, fallback=fb,
            task_name="npc_proposer", primary_call=boom,
        )
        self.assertEqual(level, "L3")
        self.assertTrue(chain.is_at_least(ModelDegradationLevel.L3))

    def test_schema_validation_counts_as_failure(self) -> None:
        chain = _chain()
        def boom() -> None:
            raise SchemaValidationError("bad", errors=["x"], schema="npc_proposal")
        result, finish, level = run_with_chain(
            chain=chain, fallback=_fallback(),
            task_name="npc_proposer", primary_call=boom,
        )
        self.assertEqual(level, "L1")
        self.assertEqual(chain.consecutive_failures, 1)

    def test_l3_does_not_call_llm_third_time(self) -> None:
        chain = _chain()
        fb = _fallback()
        call_count = {"n": 0}
        def boom() -> None:
            call_count["n"] += 1
            raise ProviderTimeoutError("simulated 4s")
        run_with_chain(chain=chain, fallback=fb, task_name="npc_proposer", primary_call=boom)
        run_with_chain(chain=chain, fallback=fb, task_name="npc_proposer", primary_call=boom)
        # The 3rd call should NOT invoke primary_call (L3 is terminal).
        result, finish, level = run_with_chain(
            chain=chain, fallback=fb, task_name="npc_proposer", primary_call=boom,
        )
        self.assertEqual(call_count["n"], 2)
        self.assertEqual(level, "L3")


# ---------------------------------------------------------------------------
# Level ordering
# ---------------------------------------------------------------------------


class LevelOrderTests(unittest.TestCase):

    def test_level_order(self) -> None:
        self.assertEqual(
            LEVEL_ORDER,
            (
                ModelDegradationLevel.L1,
                ModelDegradationLevel.L2,
                ModelDegradationLevel.L3,
                ModelDegradationLevel.L4,
            ),
        )

    def test_chain_starts_at_none(self) -> None:
        chain = _chain()
        self.assertIsNone(chain.current_level)
        self.assertFalse(chain.is_at_least(ModelDegradationLevel.L1))


# ---------------------------------------------------------------------------
# Engine ↔ model layer cooperation
# ---------------------------------------------------------------------------


class EngineModelCooperationTests(unittest.TestCase):

    def test_model_layer_chain_coexists_with_engine_layer(self) -> None:
        """The model chain should not conflict with the engine chain.

        Both layers can be on different levels at the same time:
        the model layer is L3 (no LLM) and the engine layer is L2
        (skip beat).  The engine layer's level informs the model
        layer's payload selection.
        """

        from engine import DegradationChain as EngineChain, DegradationLevel

        engine_chain = EngineChain(scene_id="photo_lab_2008")
        model_chain = _chain()

        # Engine escalates to L2
        engine_chain.escalate(to=DegradationLevel.L2_DIRECTOR_TIMEOUT, trigger="director_timeout")
        # Model escalates to L3 independently
        trigger_l3(model_chain, fallback=_fallback(),
                   beat_id="beat_x", error="x")

        self.assertEqual(
            engine_chain.current_level, DegradationLevel.L2_DIRECTOR_TIMEOUT
        )
        self.assertEqual(
            model_chain.current_level, ModelDegradationLevel.L3
        )


if __name__ == "__main__":
    unittest.main()
