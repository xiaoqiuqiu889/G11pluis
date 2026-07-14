"""Unit tests for the cost controller (decision 5 hard red lines).

The :class:`CostController` enforces the four hard red lines
from decision 5:

* 30-45 min run main calls ≤ 20
* Single output token < 800
* Per-turn model calls ≤ 2
* Key interaction P95 < 4s (recorded, alert on breach)

Plus the soft target: per-run cost < ¥0.8.

And the P0 alert: 3 consecutive runs triggering L3 → P0.

What is covered
---------------

* Pricing table lookups (provider+model, wildcard, default)
* Pre-call budget checks
* Per-call recording
* Run summary aggregation
* P0 alert on consecutive L3 runs
* Soft target tagging
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "server"))

from model import (  # noqa: E402
    CostController,
    make_cost_record,
)
from model.cost_control import (  # noqa: E402
    DEFAULT_PRICING,
    HARD_OUTPUT_TOKEN_LIMIT,
    HARD_RUN_CALL_BUDGET,
    HARD_TURN_CALL_BUDGET,
    P0_L3_CONSECUTIVE_THRESHOLD,
    P0Alert,
    PRICING,
    SOFT_RUN_COST_TARGET,
)
from model.exceptions import (  # noqa: E402
    BudgetExceededError,
    OutputTokenLimitExceededError,
)


def _record(
    *,
    run_id: str = "run-1",
    cost_cny: float = 0.0,
    model: str = "deepseek-chat",
    provider: str = "deepseek",
    input_tokens: int = 100,
    output_tokens: int = 100,
    degradation_level: str | None = None,
) -> object:
    return make_cost_record(
        run_id=run_id,
        scene_id="photo_lab_2008",
        task_type="npc_proposer",
        agent="npc_agent",
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=100,
        finish_reason="stop",
        degradation_level=degradation_level,
    )


# ---------------------------------------------------------------------------
# Constants — guard against accidental edits
# ---------------------------------------------------------------------------


class Decision5RedLinesTests(unittest.TestCase):

    def test_hard_run_call_budget(self) -> None:
        self.assertEqual(HARD_RUN_CALL_BUDGET, 20)

    def test_hard_turn_call_budget(self) -> None:
        self.assertEqual(HARD_TURN_CALL_BUDGET, 2)

    def test_hard_output_token_limit(self) -> None:
        self.assertEqual(HARD_OUTPUT_TOKEN_LIMIT, 800)

    def test_soft_run_cost_target(self) -> None:
        self.assertEqual(SOFT_RUN_COST_TARGET, 0.8)

    def test_p0_threshold(self) -> None:
        self.assertEqual(P0_L3_CONSECUTIVE_THRESHOLD, 3)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


class PricingTests(unittest.TestCase):

    def test_deepseek_chat_pricing(self) -> None:
        cc = CostController()
        # 1000 in + 1000 out at deepseek-chat rates
        # in:  1000 / 1000 * 0.001 = 0.001
        # out: 1000 / 1000 * 0.002 = 0.002
        # total: 0.003
        cost = cc.price(
            provider="deepseek", model="deepseek-chat",
            input_tokens=1000, output_tokens=1000,
        )
        self.assertAlmostEqual(cost, 0.003, places=6)

    def test_qwen_plus_pricing(self) -> None:
        cc = CostController()
        cost = cc.price(
            provider="qwen", model="qwen-plus",
            input_tokens=1000, output_tokens=1000,
        )
        # 0.0008 + 0.002 = 0.0028
        self.assertAlmostEqual(cost, 0.0028, places=6)

    def test_wildcard_pricing(self) -> None:
        cc = CostController()
        # DeepSeek reasoner is more expensive
        cost = cc.price(
            provider="deepseek", model="deepseek-reasoner",
            input_tokens=1000, output_tokens=1000,
        )
        # 0.004 + 0.016 = 0.020
        self.assertAlmostEqual(cost, 0.020, places=6)

    def test_unknown_model_uses_default(self) -> None:
        cc = CostController()
        cost = cc.price(
            provider="unknown", model="unknown-model",
            input_tokens=1000, output_tokens=1000,
        )
        # 0.005 + 0.015 = 0.020 (default pricing)
        self.assertAlmostEqual(cost, 0.020, places=6)

    def test_mock_provider_zero_cost(self) -> None:
        cc = CostController()
        cost = cc.price(
            provider="mock", model="anything",
            input_tokens=10000, output_tokens=10000,
        )
        self.assertEqual(cost, 0.0)

    def test_writer_zero_cost(self) -> None:
        cc = CostController()
        cost = cc.price(
            provider="writer", model="writer",
            input_tokens=10000, output_tokens=10000,
        )
        self.assertEqual(cost, 0.0)


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


class BudgetEnforcementTests(unittest.TestCase):

    def test_run_budget_blocks_at_20_calls(self) -> None:
        cc = CostController()
        # Record 20 calls
        for _ in range(20):
            cc.record(record=_record())
        with self.assertRaises(BudgetExceededError) as ctx:
            cc.check_run_budget(run_id="run-1")
        self.assertIn("20 calls", str(ctx.exception))

    def test_run_budget_allows_under_cap(self) -> None:
        cc = CostController()
        cc.record(record=_record())
        cc.check_run_budget(run_id="run-1")  # should not raise

    def test_turn_budget_blocks_at_2_calls(self) -> None:
        cc = CostController()
        cc.record(record=_record(), turn_idx=5)
        cc.record(record=_record(), turn_idx=5)
        with self.assertRaises(BudgetExceededError) as ctx:
            cc.check_turn_budget(run_id="run-1", turn_idx=5)
        self.assertIn("2 calls", str(ctx.exception))

    def test_turn_budget_independent_per_turn(self) -> None:
        cc = CostController()
        cc.record(record=_record(), turn_idx=0)
        cc.record(record=_record(), turn_idx=0)
        # Turn 1 still has budget
        cc.check_turn_budget(run_id="run-1", turn_idx=1)
        cc.record(record=_record(), turn_idx=1)
        cc.check_turn_budget(run_id="run-1", turn_idx=1)

    def test_output_token_red_line_at_801(self) -> None:
        cc = CostController()
        with self.assertRaises(OutputTokenLimitExceededError):
            cc.check_output_token_limit(model="any", output_tokens=801)

    def test_output_token_at_800_passes(self) -> None:
        cc = CostController()
        cc.check_output_token_limit(model="any", output_tokens=800)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


class RecordingTests(unittest.TestCase):

    def test_record_fills_cost_cny(self) -> None:
        cc = CostController()
        rec = _record(input_tokens=1000, output_tokens=1000)
        cc.record(record=rec)
        # 0.001 + 0.002 = 0.003
        self.assertAlmostEqual(rec.cost_cny, 0.003, places=6)

    def test_record_increments_run_call_count(self) -> None:
        cc = CostController()
        cc.record(record=_record())
        cc.record(record=_record())
        self.assertEqual(len(cc.records_for("run-1")), 2)
        # run call count is internal but the summary reflects it
        summary = cc.run_summary("run-1")
        self.assertEqual(summary.total_calls, 2)

    def test_run_summary_aggregates_tokens(self) -> None:
        cc = CostController()
        for _ in range(5):
            cc.record(record=_record(input_tokens=200, output_tokens=100))
        summary = cc.run_summary("run-1")
        self.assertEqual(summary.total_calls, 5)
        self.assertEqual(summary.total_input_tokens, 1000)
        self.assertEqual(summary.total_output_tokens, 500)
        # deepseek-chat: in 0.001/1K, out 0.002/1K
        # per call: 0.0002 + 0.0002 = 0.0004 → 5 calls = 0.002
        self.assertAlmostEqual(summary.total_cost_cny, 0.002, places=6)

    def test_soft_target_tags_record(self) -> None:
        cc = CostController()
        # 1 call at ¥1.00 (above ¥0.8 soft target)
        big = make_cost_record(
            run_id="run-1", scene_id="s", task_type="x", agent="a",
            model="unknown", provider="unknown",
            input_tokens=100_000, output_tokens=100_000,
            latency_ms=10, finish_reason="stop",
        )
        cc.record(record=big)
        self.assertTrue(big.metadata.get("overSoftTarget", False))

    def test_p95_latency_calculated(self) -> None:
        cc = CostController()
        for i in range(20):
            cc.record(record=make_cost_record(
                run_id="run-1", scene_id="s", task_type="x", agent="a",
                model="mock", provider="mock",
                input_tokens=10, output_tokens=10,
                latency_ms=(i + 1) * 100, finish_reason="stop",
            ))
        summary = cc.run_summary("run-1")
        # 20 latencies: 100..2000, p95 = index 18.05 → 1900
        self.assertEqual(summary.p95_latency_ms, 1900)

    def test_l3_count_in_summary(self) -> None:
        cc = CostController()
        for _ in range(3):
            cc.record(record=_record(degradation_level="L3"))
        cc.record(record=_record(degradation_level="L1"))
        summary = cc.run_summary("run-1")
        self.assertEqual(summary.l3_count, 3)
        self.assertEqual(summary.l4_count, 0)


# ---------------------------------------------------------------------------
# P0 alert
# ---------------------------------------------------------------------------


class P0AlertTests(unittest.TestCase):

    def test_p0_fires_on_three_consecutive_l3(self) -> None:
        fired: list = []
        cc = CostController(alert_sink=lambda a: fired.append(a))
        for i in range(3):
            run_id = f"run-{i}"
            cc._run_l3_flag[run_id] = True  # type: ignore[attr-defined]
            cc.note_run_completion(run_id)
        self.assertEqual(len(fired), 1)
        self.assertIsInstance(fired[0], P0Alert)
        self.assertIn("consecutive", fired[0].reason)
        self.assertEqual(fired[0].run_ids, ["run-0", "run-1", "run-2"])
        self.assertEqual(fired[0].payload["threshold"], 3)

    def test_p0_does_not_fire_on_two_l3(self) -> None:
        fired: list = []
        cc = CostController(alert_sink=lambda a: fired.append(a))
        for i in range(2):
            run_id = f"run-{i}"
            cc._run_l3_flag[run_id] = True  # type: ignore[attr-defined]
            cc.note_run_completion(run_id)
        self.assertEqual(len(fired), 0)

    def test_p0_does_not_fire_on_three_l3_with_break(self) -> None:
        fired: list = []
        cc = CostController(alert_sink=lambda a: fired.append(a))
        cc._run_l3_flag["run-0"] = True  # type: ignore[attr-defined]
        cc.note_run_completion("run-0")
        cc._run_l3_flag["run-1"] = True  # type: ignore[attr-defined]
        cc.note_run_completion("run-1")
        # run-clean breaks the chain
        cc._run_l3_flag["run-clean"] = False  # type: ignore[attr-defined]
        cc.note_run_completion("run-clean")
        cc._run_l3_flag["run-2"] = True  # type: ignore[attr-defined]
        cc.note_run_completion("run-2")
        self.assertEqual(len(fired), 0)

    def test_p0_does_not_fire_twice_for_same_streak(self) -> None:
        fired: list = []
        cc = CostController(alert_sink=lambda a: fired.append(a))
        for i in range(5):
            run_id = f"run-{i}"
            cc._run_l3_flag[run_id] = True  # type: ignore[attr-defined]
            cc.note_run_completion(run_id)
        # 5 consecutive L3 runs, but the threshold is 3 — alert
        # should fire only once for the same run streak.
        self.assertEqual(len(fired), 1)

    def test_p0_alert_sink_failure_does_not_break_loop(self) -> None:
        def bad_sink(_: P0Alert) -> None:
            raise RuntimeError("sink is down")
        cc = CostController(alert_sink=bad_sink)
        for i in range(3):
            run_id = f"run-{i}"
            cc._run_l3_flag[run_id] = True  # type: ignore[attr-defined]
            # Should not raise even though the sink raises
            cc.note_run_completion(run_id)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class ResetTests(unittest.TestCase):

    def test_reset_clears_all_state(self) -> None:
        cc = CostController()
        cc.record(record=_record())
        cc._run_l3_flag["run-x"] = True  # type: ignore[attr-defined]
        cc.note_run_completion("run-x")
        cc.reset()
        self.assertEqual(cc.records_for("run-1"), [])
        self.assertEqual(cc.alerts, [])


# ---------------------------------------------------------------------------
# Integration with the gateway
# ---------------------------------------------------------------------------


class GatewayIntegrationTests(unittest.TestCase):
    """The cost controller's budget checks are invoked by the gateway."""

    def test_gateway_calls_run_budget_check(self) -> None:
        from model import MockProvider, ModelGateway, TaskRouter, TaskType, ModelRoute, TaskConfig
        from model.schema_compliance import SchemaValidator
        from model.fallback_loader import FallbackContentLoader

        mock = MockProvider()
        cc = CostController(hard_run_call_budget=2)
        # Build a router that only knows about the mock provider.
        mock_router = TaskRouter({
            TaskType.NPC_PROPOSER: TaskConfig(
                task_type=TaskType.NPC_PROPOSER,
                routes=[ModelRoute(provider="mock", model="mock")],
            ),
        })
        gw = ModelGateway(
            providers={"mock": mock},
            router=mock_router,
            cost_controller=cc,
            validator=SchemaValidator(),
            fallback_loader=FallbackContentLoader(),
        )
        run_id = "run-budget-test"
        gw.start_run(run_id=run_id, scene_id="photo_lab_2008")
        # First call: push a valid proposal
        from model.models import ProviderResult, ModelRequest, Message, MessageRole
        import json, uuid
        valid = {
            "proposalId": str(uuid.uuid4()),
            "runId": run_id,
            "characterId": "arash",
            "proposedAction": "comfort",
            "speechIntent": "comfort",
            "reasonCodes": ["player_disclosed_truth"],
            "confidence": 0.7,
            "schemaVersion": "1.0.0",
        }
        for _ in range(5):
            mock.push(ProviderResult(
                content=json.dumps(valid, ensure_ascii=False),
                model="mock", provider="mock",
                input_tokens=10, output_tokens=10,
                finish_reason="stop", latency_ms=1,
            ))
        req = ModelRequest(
            run_id=run_id, scene_id="photo_lab_2008",
            task_type=TaskType.NPC_PROPOSER,
            messages=[Message(role=MessageRole.USER, content="...")],
        )
        # 2 calls OK
        gw.complete(req)
        gw.complete(req)
        # 3rd blocked by cost controller
        with self.assertRaises(BudgetExceededError):
            gw.complete(req)
        gw.end_run(run_id)


if __name__ == "__main__":
    unittest.main()
