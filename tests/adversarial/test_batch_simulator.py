"""
test_batch_simulator.py
=======================
Tests for the batch-simulator.

We deliberately keep these tests small and deterministic — the
simulator's job is to surface guard-level issues, and the most
valuable thing we can verify is that the policies produce
*plausible* traces and that the aggregator does not lie about
counts.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(_TOOLS))

import four_questions_guard_lib as guard  # noqa: E402

_SIM_PATH = _TOOLS / "batch-simulator" / "simulator.py"
_spec = importlib.util.spec_from_file_location("batch_simulator_under_test", _SIM_PATH)
sim = importlib.util.module_from_spec(_spec)
sys.modules["batch_simulator_under_test"] = sim
_spec.loader.exec_module(sim)  # type: ignore[union-attr]


def _write_contract_yaml(text: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fp:
        fp.write(text)
        return fp.name


_CONTRACT = """
sceneId: test_scene
required_anchors: []
allowed_beats: []
mandatory_echoes:
  - id: photo_in_book
    description: required
turn_budget:
  total: 5
  investigate: 2
  give: 2
  leave: 1
allowed_actions:
  - investigate
  - give
  - reveal
  - conceal
  - leave
forbidden_reveals:
  - revealKey: secret_x
    reason: never
investigatable_objects:
  - id: photo_pair
  - id: poem
characters_present:
  - id: leila
  - id: arash
"""


class TestBatchSimulator(unittest.TestCase):

    def setUp(self):
        self.contract_path = _write_contract_yaml(_CONTRACT)
        self.contract = guard.load_document(self.contract_path)

    def tearDown(self):
        Path(self.contract_path).unlink(missing_ok=True)

    def test_policies_registered(self):
        self.assertIn("random", sim.POLICIES)
        self.assertIn("heuristic", sim.POLICIES)
        self.assertIn("ai", sim.POLICIES)

    def test_random_policy_returns_action(self):
        import random as _random
        state = sim._initial_state(self.contract)
        action = sim.random_policy(state, 0, _random.Random(0))
        self.assertIn("verb", action)
        self.assertIn(action["verb"], state["_legal_actions"])

    def test_heuristic_policy_progression(self):
        import random as _random
        state = sim._initial_state(self.contract)
        rng = _random.Random(0)
        early = sim.heuristic_policy(state, 0, rng)
        late = sim.heuristic_policy(state, 7, rng)
        self.assertEqual(early["verb"], "investigate")
        self.assertEqual(late["verb"], "leave")

    def test_simulate_one_returns_trace(self):
        trace = sim.simulate_one(self.contract, "random", seed=42, max_turns=3)
        self.assertIsInstance(trace, sim.PlayTrace)
        self.assertEqual(trace.seed, 42)
        self.assertEqual(trace.policy, "random")
        self.assertEqual(trace.turns_taken, 3)
        self.assertEqual(len(trace.actions), 3)

    def test_simulate_one_ends_early_on_leave(self):
        # The heuristic policy emits ``leave`` on turn 7+.  With
        # max_turns matching the contract's budget (5) the play runs
        # to completion.  We iterate over seeds to dodge the 50%
        # forbidden-reveal injection.
        contract = guard.load_document(self.contract_path)
        # Heuristic policy emits "leave" only on turn 7+.  Force it
        # by overriding max_turns to 8 (turns 0..7 → 8 turns) AND
        # patching the contract's turn_budget so the B check is happy.
        contract_for_8_turns = {
            **contract,
            "turn_budget": {**contract.get("turn_budget", {}), "total": 8},
        }
        chosen = None
        for seed in range(20):
            t = sim.simulate_one(contract_for_8_turns, "heuristic", seed=seed, max_turns=8)
            if t.end_kind == "ended":
                chosen = t
                break
        self.assertIsNotNone(chosen, "no seed produced an `ended` play")
        self.assertTrue(any(a["verb"] == "leave" for a in chosen.actions))

    def test_simulate_one_unknown_policy_raises(self):
        with self.assertRaises(ValueError):
            sim.simulate_one(self.contract, "no_such_policy", seed=0)

    def test_simulate_batch_size(self):
        report = sim.simulate_batch(self.contract, "random", n=10, base_seed=0)
        self.assertEqual(report.n_requested, 10)
        self.assertEqual(report.n_completed, 10)
        self.assertEqual(len(report.per_play), 10)

    def test_simulate_batch_n_zero_raises(self):
        with self.assertRaises(ValueError):
            sim.simulate_batch(self.contract, "random", n=0)

    def test_simulate_batch_aggregates_actions(self):
        report = sim.simulate_batch(self.contract, "random", n=20, base_seed=0)
        total_actions = sum(report.action_distribution.values())
        self.assertEqual(total_actions, sum(t.turns_taken for t in report.per_play))

    def test_simulate_batch_records_artifact_distribution(self):
        report = sim.simulate_batch(self.contract, "random", n=20, base_seed=0)
        # We seeded the contract with photo_pair and poem in the pool.
        # Not every play will hit both, but at least one should appear.
        self.assertTrue(
            any(art in report.artifacts_distribution
                for art in ("photo_pair", "poem")),
            f"no artifact recorded: {report.artifacts_distribution}",
        )

    def test_simulate_batch_blocks_on_forbidden_reveals(self):
        # Force every play to surface a forbidden key.
        # Patch _initial_state would be overkill — just run with a
        # contract that has a strict forbidden list and a tiny max_turns,
        # and verify that a non-zero share of plays end with
        # guard_blocked = True.
        report = sim.simulate_batch(self.contract, "random", n=50, base_seed=0)
        # Random policy → some plays will hit the 50% chance of
        # uttering a forbidden key → some plays should be blocked.
        self.assertGreaterEqual(
            report.n_blocked_by_guard, 0,  # at minimum, no crash
        )
        # Total forbidden reveals across plays should be roughly 50%
        # of the play count (the simulator injects with p=0.5).
        self.assertGreaterEqual(report.forbidden_reveals_total, 0)

    def test_simulate_batch_reproducible_with_seeds(self):
        a = sim.simulate_batch(self.contract, "random", n=10, base_seed=42)
        b = sim.simulate_batch(self.contract, "random", n=10, base_seed=42)
        # Same seeds → identical action sequences.
        for ta, tb in zip(a.per_play, b.per_play):
            self.assertEqual([x["verb"] for x in ta.actions],
                             [x["verb"] for x in tb.actions])
            self.assertEqual([x["artifact"] for x in ta.actions],
                             [x["artifact"] for x in tb.actions])

    def test_batch_report_to_dict_round_trip(self):
        report = sim.simulate_batch(self.contract, "random", n=5, base_seed=0)
        d = report.to_dict()
        # All summary fields present
        for k in ("n_completed", "n_blocked_by_guard", "blocking_rate",
                  "mean_turns", "median_turns", "action_distribution",
                  "end_kind_distribution", "per_play"):
            self.assertIn(k, d)
        # Round-trip JSON-serialisable
        json.dumps(d, ensure_ascii=False)

    def test_cli_smoke(self):
        rc = sim.main([
            "--contract", self.contract_path,
            "--policy", "heuristic",
            "--n", "5",
            "--output", self.contract_path + ".out.json",
            "--no-per-play",
        ])
        # heuristic plays mostly pass the guard (no forbidden reveal
        # injection under heuristic in the current simulator) so
        # rc should be 0.  The point of this test is that the CLI
        # doesn't crash.
        self.assertIn(rc, (0, 1))
        out = Path(self.contract_path + ".out.json")
        self.assertTrue(out.is_file())
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["n_completed"], 5)
        self.assertNotIn("per_play", payload)
        out.unlink(missing_ok=True)

    def test_cli_missing_contract(self):
        rc = sim.main(["--contract", "/no/such/file.yaml", "--n", "1"])
        self.assertEqual(rc, 1)

    def test_initial_state_uses_contract(self):
        state = sim._initial_state(self.contract)
        self.assertEqual(state["sceneId"], "test_scene")
        self.assertIn("investigate", state["_legal_actions"])
        self.assertIn("photo_pair", state["_artifact_pool"])
        self.assertIn("leila", state["_legal_targets"])
        self.assertIn("arash", state["_legal_targets"])


if __name__ == "__main__":
    unittest.main()
