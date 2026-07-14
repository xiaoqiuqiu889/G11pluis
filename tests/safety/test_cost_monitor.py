"""Unit tests for the cost monitor (决策 5 硬红线 gate).

Decision 5 sets four hard red lines:

* R1  30-45 minute vertical slice main calls per run ≤ 20
* R2  Single LLM output tokens < 800
* R3  Per-turn model calls ≤ 2
* R4  Key interaction response P95 < 4 s (4000 ms)

Plus the soft signal: 3 consecutive runs that trigger L3+
fire a P0 报警.

Coverage:

* ``HARD_RED_LINES`` literal — the 4 thresholds are pinned
* Each red line is breachable and passable
* ``summarise_run`` aggregates the per-run numbers
* ``check_p0_escalation`` fires after 3 consecutive L3 runs
* ``LiveCounter`` integrates ``record`` + ``check``
* ``evaluate_from_file`` reads the CI JSON file format
* Exit code stability: 0 = pass, 1 = block, 2 = I/O error
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.safety.cost_monitor import (  # noqa: E402
    CostReport,
    CostViolation,
    ExitCode,
    HARD_RED_LINES,
    LiveCounter,
    ModelCall,
    P0_ESCALATION_THRESHOLD,
    RedLine,
    RunSummary,
    _percentile,
    check_p0_escalation,
    check_red_lines,
    evaluate,
    evaluate_from_file,
    summarise_run,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class HardRedLinesTests(unittest.TestCase):
    """The 4 red lines are pinned by the brief."""

    def test_count_is_four(self) -> None:
        self.assertEqual(len(HARD_RED_LINES), 4)

    def test_red_line_ids(self) -> None:
        ids = [line.id for line in HARD_RED_LINES]
        self.assertEqual(ids, ["R1", "R2", "R3", "R4"])

    def test_thresholds_are_pinned(self) -> None:
        # These are the literal values from requirements-review-v1.md
        # §2 decision 5; do NOT change without a decision revision.
        thresholds = {line.id: line.threshold for line in HARD_RED_LINES}
        self.assertEqual(thresholds["R1"], 20.0)
        self.assertEqual(thresholds["R2"], 800.0)
        self.assertEqual(thresholds["R3"], 2.0)
        self.assertEqual(thresholds["R4"], 4_000.0)

    def test_all_comparators_are_le(self) -> None:
        for line in HARD_RED_LINES:
            self.assertEqual(line.comparator, "<=")

    def test_units(self) -> None:
        units = {line.id: line.unit for line in HARD_RED_LINES}
        self.assertEqual(units["R1"], "calls")
        self.assertEqual(units["R2"], "tokens")
        self.assertEqual(units["R3"], "calls_per_turn")
        self.assertEqual(units["R4"], "ms")

    def test_p0_threshold_is_three(self) -> None:
        self.assertEqual(P0_ESCALATION_THRESHOLD, 3)

    def test_check_helper(self) -> None:
        line = RedLine("X", "test", 10.0, "<=", "x")
        self.assertTrue(line.check(5.0))
        self.assertTrue(line.check(10.0))
        self.assertFalse(line.check(11.0))
        with self.assertRaises(ValueError):
            RedLine("X", "test", 10.0, "==", "x").check(5.0)


class ExitCodeTests(unittest.TestCase):
    def test_exit_codes_are_canonical(self) -> None:
        self.assertEqual(int(ExitCode.PASS), 0)
        self.assertEqual(int(ExitCode.BLOCK), 1)
        self.assertEqual(int(ExitCode.IO_ERROR), 2)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _call(
    runId: str = "r1",
    sequence: int = 1,
    agent: str = "npc_agent",
    model: str = "m1",
    input_tokens: int = 10,
    output_tokens: int = 20,
    latency_ms: int = 100,
    degradation: int = 0,
) -> ModelCall:
    return ModelCall(
        runId=runId,
        sequence=sequence,
        agent=agent,
        model=model,
        inputTokens=input_tokens,
        outputTokens=output_tokens,
        latencyMs=latency_ms,
        degradationLevel=degradation,
    )


class SummariseRunTests(unittest.TestCase):
    def test_main_calls_count_only_relevant_agents(self) -> None:
        calls = [
            _call(agent="npc_agent", sequence=1),
            _call(agent="director_agent", sequence=1),
            _call(agent="resolver", sequence=2),
            _call(agent="player_client", sequence=1),  # not counted
            _call(agent="memory_recall", sequence=1),  # not counted
        ]
        s = summarise_run("r1", calls)
        self.assertEqual(s.main_call_count, 3)
        # 2 main calls share sequence 1 (NPC + Director)
        self.assertEqual(s.per_turn_max_calls, 2)
        self.assertEqual(s.max_output_tokens, 20)

    def test_p95_latency(self) -> None:
        # 20 values: latency = 200, 300, ..., 2100
        calls = [
            _call(sequence=i, latency_ms=(i + 1) * 100)
            for i in range(1, 21)
        ]
        s = summarise_run("r1", calls)
        # P95 via linear interpolation between index 18 and 19
        # (2000 and 2100) = 2005
        self.assertEqual(s.p95_latency_ms, 2005.0)

    def test_l3_count(self) -> None:
        calls = [
            _call(sequence=1, degradation=3),
            _call(sequence=2, degradation=4),
            _call(sequence=3, degradation=0),
        ]
        s = summarise_run("r1", calls)
        self.assertEqual(s.l3_or_worse_count, 2)

    def test_empty_call_list(self) -> None:
        s = summarise_run("r1", [])
        self.assertEqual(s.main_call_count, 0)
        self.assertEqual(s.per_turn_max_calls, 0)
        self.assertEqual(s.max_output_tokens, 0)
        self.assertEqual(s.p95_latency_ms, 0.0)
        self.assertEqual(s.l3_or_worse_count, 0)


class PercentileTests(unittest.TestCase):
    def test_percentile_helper(self) -> None:
        self.assertEqual(_percentile([1, 2, 3, 4, 5], 50.0), 3.0)
        self.assertEqual(_percentile([1], 95.0), 1.0)
        self.assertEqual(_percentile([], 95.0), 0.0)
        # P95 of 1..20 ≈ 19
        v = _percentile(list(range(1, 21)), 95.0)
        self.assertGreaterEqual(v, 18)
        self.assertLessEqual(v, 20)


# ---------------------------------------------------------------------------
# Red-line checks
# ---------------------------------------------------------------------------


class CheckRedLinesTests(unittest.TestCase):
    def test_all_within_bounds(self) -> None:
        s = RunSummary(
            runId="r1", main_call_count=15, per_turn_max_calls=2,
            max_output_tokens=500, p95_latency_ms=2000.0, l3_or_worse_count=0,
        )
        self.assertEqual(check_red_lines(s), [])

    def test_r1_breach(self) -> None:
        s = RunSummary(
            runId="r1", main_call_count=21, per_turn_max_calls=2,
            max_output_tokens=500, p95_latency_ms=2000.0, l3_or_worse_count=0,
        )
        violations = check_red_lines(s)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].red_line_id, "R1")
        self.assertEqual(violations[0].observed, 21.0)
        self.assertEqual(violations[0].threshold, 20.0)

    def test_r2_breach(self) -> None:
        s = RunSummary(
            runId="r1", main_call_count=15, per_turn_max_calls=2,
            max_output_tokens=850, p95_latency_ms=2000.0, l3_or_worse_count=0,
        )
        violations = check_red_lines(s)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].red_line_id, "R2")

    def test_r3_breach(self) -> None:
        s = RunSummary(
            runId="r1", main_call_count=15, per_turn_max_calls=3,
            max_output_tokens=500, p95_latency_ms=2000.0, l3_or_worse_count=0,
        )
        violations = check_red_lines(s)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].red_line_id, "R3")

    def test_r4_breach(self) -> None:
        s = RunSummary(
            runId="r1", main_call_count=15, per_turn_max_calls=2,
            max_output_tokens=500, p95_latency_ms=4500.0, l3_or_worse_count=0,
        )
        violations = check_red_lines(s)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].red_line_id, "R4")

    def test_multiple_breaches(self) -> None:
        s = RunSummary(
            runId="r1", main_call_count=25, per_turn_max_calls=4,
            max_output_tokens=1000, p95_latency_ms=5000.0, l3_or_worse_count=0,
        )
        violations = check_red_lines(s)
        self.assertEqual(len(violations), 4)
        ids = {v.red_line_id for v in violations}
        self.assertEqual(ids, {"R1", "R2", "R3", "R4"})


# ---------------------------------------------------------------------------
# P0 报警
# ---------------------------------------------------------------------------


class P0EscalationTests(unittest.TestCase):
    def _summary(self, l3_count: int) -> RunSummary:
        return RunSummary(
            runId="x", main_call_count=10, per_turn_max_calls=2,
            max_output_tokens=500, p95_latency_ms=1000.0,
            l3_or_worse_count=l3_count,
        )

    def test_no_p0_when_under_threshold(self) -> None:
        history = [self._summary(1), self._summary(0)]
        fired, reason = check_p0_escalation(history)
        self.assertFalse(fired)
        self.assertEqual(reason, "")

    def test_p0_fires_at_3_consecutive_l3(self) -> None:
        history = [self._summary(1), self._summary(2), self._summary(1)]
        fired, reason = check_p0_escalation(history)
        self.assertTrue(fired)
        self.assertIn("3", reason)
        self.assertIn("P0", reason)

    def test_p0_does_not_fire_with_only_two(self) -> None:
        history = [self._summary(1), self._summary(2)]
        fired, _ = check_p0_escalation(history)
        self.assertFalse(fired)

    def test_p0_does_not_fire_with_gap(self) -> None:
        history = [self._summary(1), self._summary(0), self._summary(1)]
        fired, _ = check_p0_escalation(history)
        self.assertFalse(fired)


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------


class EvaluateTests(unittest.TestCase):
    def test_clean_run_passes(self) -> None:
        calls = [_call(sequence=i) for i in range(1, 16)]  # 15 calls, fine
        r = evaluate({"r1": calls})
        self.assertTrue(r.passed)
        self.assertEqual(r.exit_code, int(ExitCode.PASS))
        self.assertEqual(r.violations, [])
        self.assertFalse(r.p0_alert)

    def test_breach_blocks(self) -> None:
        calls = [_call(sequence=i) for i in range(1, 22)]  # 21 calls
        r = evaluate({"r1": calls})
        self.assertFalse(r.passed)
        self.assertEqual(r.exit_code, int(ExitCode.BLOCK))
        self.assertEqual(r.summary["R1"], 1)
        self.assertEqual(r.summary["total_violations"], 1)

    def test_p0_alert_on_3_consecutive_l3(self) -> None:
        calls_by_run = {
            f"r{i}": [_call(runId=f"r{i}", sequence=1, degradation=3)]
            for i in range(3)
        }
        r = evaluate(calls_by_run)
        self.assertTrue(r.p0_alert)
        self.assertIn("P0", r.p0_reason)

    def test_p0_alert_with_preexisting_history(self) -> None:
        history = [
            RunSummary(
                runId=f"hist{i}", main_call_count=10, per_turn_max_calls=1,
                max_output_tokens=100, p95_latency_ms=500.0,
                l3_or_worse_count=2,
            )
            for i in range(2)
        ]
        new_calls = [_call(runId="new1", sequence=1, degradation=4)]
        r = evaluate({"new1": new_calls}, p0_history=history)
        self.assertTrue(r.p0_alert)

    def test_to_human_readable(self) -> None:
        calls = [_call(sequence=i) for i in range(1, 22)]
        r = evaluate({"r1": calls})
        text = r.to_human_readable()
        self.assertIn("❌", text)
        self.assertIn("R1", text)
        self.assertIn("exit_code=1", text)

    def test_to_dict_round_trip(self) -> None:
        calls = [_call(sequence=i) for i in range(1, 22)]
        r = evaluate({"r1": calls})
        s = json.dumps(r.to_dict())
        reloaded = json.loads(s)
        self.assertFalse(reloaded["passed"])
        self.assertEqual(reloaded["exit_code"], 1)


# ---------------------------------------------------------------------------
# Live counter
# ---------------------------------------------------------------------------


class LiveCounterTests(unittest.TestCase):
    def test_no_violations_within_bounds(self) -> None:
        lc = LiveCounter(runId="lc1")
        for i in range(15):
            lc.record(_call(runId="lc1", sequence=i))
        self.assertEqual(lc.check(), [])

    def test_r1_breach_recorded(self) -> None:
        lc = LiveCounter(runId="lc1")
        for i in range(21):
            lc.record(_call(runId="lc1", sequence=i))
        violations = lc.check()
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].red_line_id, "R1")

    def test_r2_breach_recorded(self) -> None:
        lc = LiveCounter(runId="lc1")
        lc.record(_call(output_tokens=2000))
        violations = lc.check()
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].red_line_id, "R2")

    def test_r3_breach_recorded(self) -> None:
        lc = LiveCounter(runId="lc1")
        # 3 calls in the same turn
        for i in range(3):
            lc.record(_call(sequence=1))
        violations = lc.check()
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].red_line_id, "R3")

    def test_r4_breach_recorded(self) -> None:
        lc = LiveCounter(runId="lc1")
        lc.record(_call(latency_ms=10_000))
        violations = lc.check()
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].red_line_id, "R4")

    def test_l3_counter_increments(self) -> None:
        lc = LiveCounter(runId="lc1")
        lc.record(_call(degradation=3))
        lc.record(_call(degradation=4))
        self.assertEqual(lc.l3_or_worse_count, 2)


# ---------------------------------------------------------------------------
# evaluate_from_file (CI integration)
# ---------------------------------------------------------------------------


class EvaluateFromFileTests(unittest.TestCase):
    def test_clean_file(self) -> None:
        data = {
            "calls": [
                {"runId": "r1", "sequence": i, "agent": "npc_agent",
                 "model": "m", "outputTokens": 100, "latencyMs": 200}
                for i in range(15)
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            path = f.name
        try:
            r = evaluate_from_file(path)
            self.assertTrue(r.passed)
            self.assertEqual(r.exit_code, int(ExitCode.PASS))
        finally:
            Path(path).unlink()

    def test_breach_file_blocks(self) -> None:
        data = {
            "calls": [
                {"runId": "r1", "sequence": i, "agent": "npc_agent",
                 "model": "m", "outputTokens": 100, "latencyMs": 200}
                for i in range(25)
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            path = f.name
        try:
            r = evaluate_from_file(path)
            self.assertFalse(r.passed)
            self.assertEqual(r.exit_code, int(ExitCode.BLOCK))
        finally:
            Path(path).unlink()

    def test_io_error(self) -> None:
        r = evaluate_from_file("/no/such/file.json")
        self.assertFalse(r.passed)
        self.assertEqual(r.exit_code, int(ExitCode.IO_ERROR))

    def test_p0_history_passed_in_wrapper(self) -> None:
        data = {
            "calls": [
                {"runId": "r1", "sequence": 1, "agent": "npc_agent",
                 "model": "m", "outputTokens": 100, "latencyMs": 200,
                 "degradationLevel": 3},
            ],
            "p0_history": [
                {"runId": f"hist{i}", "main_call_count": 10,
                 "per_turn_max_calls": 1, "max_output_tokens": 100,
                 "p95_latency_ms": 500.0, "l3_or_worse_count": 2}
                for i in range(2)
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            path = f.name
        try:
            r = evaluate_from_file(path)
            self.assertTrue(r.p0_alert)
        finally:
            Path(path).unlink()


# ---------------------------------------------------------------------------
# Decision 5 acceptance: simulate one run and verify no breach
# ---------------------------------------------------------------------------


class Decision5AcceptanceTests(unittest.TestCase):
    """The CI workflow's ``cost-red-line`` job simulates a full run
    of 20 main calls and asserts every red line is within bounds.
    This is the same simulation, run as a unit test.
    """

    def test_simulated_run_passes_all_red_lines(self) -> None:
        # 20 main calls (one per turn), each with reasonable
        # output tokens + latency
        calls = [
            _call(sequence=i + 1, output_tokens=200, latency_ms=1000)
            for i in range(20)
        ]
        r = evaluate({"r_sim": calls})
        self.assertTrue(r.passed, r.to_human_readable())
        self.assertEqual(r.exit_code, int(ExitCode.PASS))
        # 20 main calls, 1 per turn (R3 ≤ 2), tokens ≤ 800, P95 < 4000ms
        s = r.run_summaries[0]
        self.assertEqual(s.main_call_count, 20)
        self.assertEqual(s.per_turn_max_calls, 1)
        self.assertLessEqual(s.max_output_tokens, 800)
        self.assertLess(s.p95_latency_ms, 4_000.0)

    def test_breach_at_21st_call(self) -> None:
        calls = [
            _call(sequence=i + 1, output_tokens=200, latency_ms=1000)
            for i in range(21)
        ]
        r = evaluate({"r_breach": calls})
        self.assertFalse(r.passed)
        self.assertEqual(r.exit_code, int(ExitCode.BLOCK))


if __name__ == "__main__":
    unittest.main()
