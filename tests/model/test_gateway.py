"""Unit tests for the Model Gateway.

Coverage
--------

* Construction (with / without real providers)
* Per-run lifecycle (start_run / end_run)
* Structured completion (schema validation + retry)
* Chat completion (no schema)
* Routing fallback (try next route on failure)
* Schema validation failure → retry once → fallback
* Cost controller wiring
* Degradation chain wiring

These tests do NOT touch the network: they use a single
:class:`MockProvider` and push scripted responses.
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
    CostController,
    DeepSeekProvider,
    FallbackContentLoader,
    Message,
    MessageRole,
    MockProvider,
    ModelGateway,
    ModelRequest,
    ProviderResult,
    QwenProvider,
    SchemaValidator,
    TaskType,
    build_default_gateway,
    build_default_router,
)
from model.exceptions import (  # noqa: E402
    BudgetExceededError,
    OutputTokenLimitExceededError,
    ProviderTimeoutError,
    SchemaValidationError,
)


def _ok_npc_proposal_dict() -> dict:
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


def _start_gateway_with_mock(
    *, mock: MockProvider | None = None, cost_controller: CostController | None = None
) -> tuple[ModelGateway, str]:
    mock = mock or MockProvider()
    gw = ModelGateway(
        providers={"mock": mock},
        router=build_default_router(),
        cost_controller=cost_controller or CostController(),
        validator=SchemaValidator(),
        fallback_loader=FallbackContentLoader(),
    )
    run_id = str(uuid.uuid4())
    gw.start_run(run_id=run_id, scene_id="photo_lab_2008")
    return gw, run_id


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class ConstructionTests(unittest.TestCase):

    def test_default_gateway_has_mock_only(self) -> None:
        gw = build_default_gateway()
        self.assertIn("mock", gw._providers)
        # Real providers are opt-in
        self.assertNotIn("deepseek", gw._providers)
        self.assertNotIn("qwen", gw._providers)

    def test_real_providers_require_api_keys(self) -> None:
        # Without env vars, providers should still construct (they
        # raise on first call, not on construction).
        ds = DeepSeekProvider(api_key=None)
        self.assertEqual(ds.name, "deepseek")
        self.assertEqual(ds._api_key, "")
        qw = QwenProvider(api_key=None)
        self.assertEqual(qw.name, "qwen")
        self.assertEqual(qw._api_key, "")

    def test_empty_providers_raises(self) -> None:
        with self.assertRaises(ValueError):
            ModelGateway(providers={})


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class RunLifecycleTests(unittest.TestCase):

    def test_start_and_end_run(self) -> None:
        gw, run_id = _start_gateway_with_mock()
        self.assertIsNotNone(gw.degradation_chain(run_id))
        alerts = gw.end_run(run_id)
        self.assertIsInstance(alerts, list)
        # After end_run, chain should be removed.
        self.assertIsNone(gw.degradation_chain(run_id))

    def test_complete_without_start_raises(self) -> None:
        gw, _ = _start_gateway_with_mock()
        req = ModelRequest(
            run_id=str(uuid.uuid4()),  # not started
            scene_id="photo_lab_2008",
            task_type=TaskType.NPC_PROPOSER,
            messages=[Message(role=MessageRole.USER, content="hi")],
        )
        with self.assertRaises(KeyError):
            gw.complete(req)


# ---------------------------------------------------------------------------
# Structured completion
# ---------------------------------------------------------------------------


class StructuredCompletionTests(unittest.TestCase):

    def test_complete_parses_and_validates(self) -> None:
        mock = MockProvider()
        valid = _ok_npc_proposal_dict()
        mock.push(ProviderResult(
            content=json.dumps(valid, ensure_ascii=False),
            model="mock",
            provider="mock",
            input_tokens=120,
            output_tokens=80,
            finish_reason="stop",
            latency_ms=120,
        ))
        gw, run_id = _start_gateway_with_mock(mock=mock)
        req = ModelRequest(
            run_id=run_id,
            scene_id="photo_lab_2008",
            task_type=TaskType.NPC_PROPOSER,
            messages=[Message(role=MessageRole.USER, content="...")],
        )
        response = gw.complete(req)
        self.assertTrue(response.is_clean)
        self.assertEqual(response.task_type, TaskType.NPC_PROPOSER)
        self.assertIsNotNone(response.parsed)
        self.assertEqual(response.parsed["characterId"], "arash")
        self.assertEqual(response.finish_reason, "stop")
        self.assertEqual(response.attempts, 1)
        # Cost should be recorded
        summary = gw.run_summary(run_id)
        self.assertEqual(summary.total_calls, 1)
        self.assertGreater(summary.total_cost_cny, 0.0)

    def test_invalid_schema_triggers_retry(self) -> None:
        # First response: invalid (missing required field)
        # Second response: valid
        mock = MockProvider()
        mock.push(ProviderResult(
            content='{"not_a_valid_proposal": true}',
            model="mock", provider="mock",
            input_tokens=10, output_tokens=10, finish_reason="stop",
            latency_ms=10,
        ))
        valid = _ok_npc_proposal_dict()
        mock.push(ProviderResult(
            content=json.dumps(valid, ensure_ascii=False),
            model="mock", provider="mock",
            input_tokens=120, output_tokens=80, finish_reason="stop",
            latency_ms=120,
        ))
        gw, run_id = _start_gateway_with_mock(mock=mock)
        req = ModelRequest(
            run_id=run_id,
            scene_id="photo_lab_2008",
            task_type=TaskType.NPC_PROPOSER,
            messages=[Message(role=MessageRole.USER, content="...")],
        )
        response = gw.complete(req)
        self.assertTrue(response.is_clean)
        self.assertEqual(response.attempts, 2)

    def test_double_schema_failure_falls_back(self) -> None:
        # Both responses invalid → fallback
        mock = MockProvider()
        mock.push(ProviderResult(
            content='{"garbage": 1}',
            model="mock", provider="mock",
            input_tokens=10, output_tokens=10, finish_reason="stop",
            latency_ms=10,
        ))
        mock.push(ProviderResult(
            content='{"still_garbage": 2}',
            model="mock", provider="mock",
            input_tokens=10, output_tokens=10, finish_reason="stop",
            latency_ms=10,
        ))
        gw, run_id = _start_gateway_with_mock(mock=mock)
        req = ModelRequest(
            run_id=run_id,
            scene_id="photo_lab_2008",
            task_type=TaskType.NPC_PROPOSER,
            messages=[Message(role=MessageRole.USER, content="...")],
        )
        response = gw.complete(req)
        self.assertTrue(response.used_fallback)
        # The fallback is an L1 NPC line.
        self.assertEqual(response.degradation_level, "L1")
        self.assertEqual(response.provider, "writer")
        self.assertEqual(response.model, "writer")

    def test_provider_timeout_triggers_next_route(self) -> None:
        # Mock has no scripted response → falls through to default;
        # we instead force a timeout from the provider by raising
        # ProviderTimeoutError via the raise_after mechanism.
        mock = MockProvider(raise_after=0)  # all calls raise
        gw, run_id = _start_gateway_with_mock(mock=mock)
        req = ModelRequest(
            run_id=run_id,
            scene_id="photo_lab_2008",
            task_type=TaskType.NPC_PROPOSER,
            messages=[Message(role=MessageRole.USER, content="...")],
        )
        response = gw.complete(req)
        self.assertTrue(response.used_fallback)
        self.assertEqual(response.degradation_level, "L1")


# ---------------------------------------------------------------------------
# Chat (no schema) completion
# ---------------------------------------------------------------------------


class ChatCompletionTests(unittest.TestCase):

    def test_chat_returns_raw_content(self) -> None:
        mock = MockProvider()
        mock.push(ProviderResult(
            content="plain text response from the model",
            model="mock", provider="mock",
            input_tokens=10, output_tokens=20, finish_reason="stop",
            latency_ms=50,
        ))
        gw, run_id = _start_gateway_with_mock(mock=mock)
        req = ModelRequest(
            run_id=run_id,
            scene_id="photo_lab_2008",
            task_type=TaskType.MEMORY_RECALL,
            messages=[Message(role=MessageRole.USER, content="...")],
        )
        response = gw.chat(req)
        self.assertEqual(response.content, "plain text response from the model")
        self.assertIsNone(response.parsed)
        self.assertTrue(response.is_clean)


# ---------------------------------------------------------------------------
# Cost + budget enforcement
# ---------------------------------------------------------------------------


class CostAndBudgetTests(unittest.TestCase):

    def test_per_run_call_budget_enforced(self) -> None:
        mock = MockProvider()
        # Queue up exactly 25 valid responses
        for _ in range(25):
            valid = _ok_npc_proposal_dict()
            mock.push(ProviderResult(
                content=json.dumps(valid, ensure_ascii=False),
                model="mock", provider="mock",
                input_tokens=10, output_tokens=10, finish_reason="stop",
                latency_ms=1,
            ))
        cc = CostController(hard_run_call_budget=3)
        gw, run_id = _start_gateway_with_mock(mock=mock, cost_controller=cc)
        req = ModelRequest(
            run_id=run_id,
            scene_id="photo_lab_2008",
            task_type=TaskType.NPC_PROPOSER,
            messages=[Message(role=MessageRole.USER, content="...")],
        )
        # 3 successful calls
        for _ in range(3):
            gw.complete(req)
        # 4th should be blocked
        with self.assertRaises(BudgetExceededError):
            gw.complete(req)

    def test_per_turn_call_budget_enforced(self) -> None:
        mock = MockProvider()
        for _ in range(5):
            valid = _ok_npc_proposal_dict()
            mock.push(ProviderResult(
                content=json.dumps(valid, ensure_ascii=False),
                model="mock", provider="mock",
                input_tokens=10, output_tokens=10, finish_reason="stop",
                latency_ms=1,
            ))
        cc = CostController(hard_turn_call_budget=2)
        gw, run_id = _start_gateway_with_mock(mock=mock, cost_controller=cc)
        req = ModelRequest(
            run_id=run_id,
            scene_id="photo_lab_2008",
            task_type=TaskType.NPC_PROPOSER,
            messages=[Message(role=MessageRole.USER, content="...")],
        )
        gw.complete(req)
        gw.complete(req)
        with self.assertRaises(BudgetExceededError):
            gw.complete(req)

    def test_output_token_red_line_raises(self) -> None:
        # The cost controller's check_output_token_limit raises
        # OutputTokenLimitExceededError; verify the constant.
        from model.cost_control import HARD_OUTPUT_TOKEN_LIMIT
        self.assertEqual(HARD_OUTPUT_TOKEN_LIMIT, 800)
        cc = CostController()
        with self.assertRaises(OutputTokenLimitExceededError):
            cc.check_output_token_limit(model="any", output_tokens=801)


# ---------------------------------------------------------------------------
# P0 alert
# ---------------------------------------------------------------------------


class P0AlertTests(unittest.TestCase):

    def test_three_consecutive_l3_runs_fire_p0(self) -> None:
        fired: list = []
        cc = CostController(alert_sink=lambda a: fired.append(a))
        # Simulate 3 runs that each had an L3 escalation.
        for i in range(3):
            run_id = f"run-{i}"
            cc._run_l3_flag[run_id] = True  # type: ignore[attr-defined]
            alerts = cc.note_run_completion(run_id)
            if alerts:
                fired.extend(alerts)
        self.assertEqual(len(fired), 1)
        self.assertIn("L3", fired[0].reason)
        self.assertEqual(len(fired[0].run_ids), 3)

    def test_non_l3_run_breaks_streak(self) -> None:
        cc = CostController()
        for i in range(2):
            run_id = f"run-l3-{i}"
            cc._run_l3_flag[run_id] = True  # type: ignore[attr-defined]
            cc.note_run_completion(run_id)
        # A non-L3 run breaks the chain.
        cc._run_l3_flag["run-clean"] = False  # type: ignore[attr-defined]
        cc.note_run_completion("run-clean")
        # The next L3 run should not fire P0 because the streak
        # was reset.
        cc._run_l3_flag["run-l3-x"] = True  # type: ignore[attr-defined]
        cc.note_run_completion("run-l3-x")
        self.assertEqual(len(cc.alerts), 0)


if __name__ == "__main__":
    unittest.main()
