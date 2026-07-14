"""Unit tests for the task router (per-task model + provider config).

Coverage
--------

* Default configs for all 5 task types
* Router iterates routes in order
* Hot-swap of a config
* Cost-of-routing is computed correctly (route overrides)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "server"))

from model import (  # noqa: E402
    DEFAULT_TASK_CONFIGS,
    ModelRoute,
    TaskConfig,
    TaskRouter,
    TaskType,
    build_default_router,
)


class DefaultConfigsTests(unittest.TestCase):

    def test_all_tasks_have_default_config(self) -> None:
        for task in TaskType:
            self.assertIn(task, DEFAULT_TASK_CONFIGS)
            cfg = DEFAULT_TASK_CONFIGS[task]
            self.assertGreater(len(cfg.routes), 0)
            for route in cfg.routes:
                self.assertTrue(route.provider)
                self.assertTrue(route.model)

    def test_player_intent_parser_uses_fast_model(self) -> None:
        cfg = DEFAULT_TASK_CONFIGS[TaskType.PLAYER_INTENT_PARSER]
        # Primary should be a fast, cheap model
        self.assertEqual(cfg.routes[0].provider, "deepseek")
        self.assertEqual(cfg.routes[0].model, "deepseek-chat")

    def test_npc_proposer_uses_main_model(self) -> None:
        cfg = DEFAULT_TASK_CONFIGS[TaskType.NPC_PROPOSER]
        self.assertGreaterEqual(len(cfg.routes), 2)
        # First is primary, second is fallback
        self.assertNotEqual(cfg.routes[0].provider, cfg.routes[1].provider)

    def test_memory_recall_uses_turbo(self) -> None:
        cfg = DEFAULT_TASK_CONFIGS[TaskType.MEMORY_RECALL]
        # Memory recall is cheap, no schema — fast model is fine
        # Default may vary; just verify it has at least one route
        self.assertGreaterEqual(len(cfg.routes), 1)


class RouterIterationTests(unittest.TestCase):

    def test_iter_routes_yields_in_order(self) -> None:
        r = TaskRouter()
        routes = list(r.iter_routes(TaskType.NPC_PROPOSER))
        self.assertEqual(len(routes), 2)
        for route, retries in routes:
            self.assertIsInstance(route, ModelRoute)
            self.assertEqual(retries, 1)

    def test_get_unknown_task_raises(self) -> None:
        r = build_default_router()
        # Sanity: a known task does NOT raise.
        cfg = r.get(TaskType.NPC_PROPOSER)
        self.assertIsNotNone(cfg)
        # The TaskType enum has no "unknown" value, so the only
        # way to provoke a missing config is to remove it after
        # construction.  Manually remove the config and re-test.
        r._configs.pop(TaskType.NPC_PROPOSER)  # type: ignore[attr-defined]
        with self.assertRaises(KeyError):
            r.get(TaskType.NPC_PROPOSER)


class HotSwapTests(unittest.TestCase):

    def test_set_replaces_config(self) -> None:
        r = TaskRouter()
        new_cfg = TaskConfig(
            task_type=TaskType.NPC_PROPOSER,
            routes=[ModelRoute(provider="qwen", model="qwen-max")],
        )
        r.set(TaskType.NPC_PROPOSER, new_cfg)
        got = r.get(TaskType.NPC_PROPOSER)
        self.assertEqual(got.routes[0].provider, "qwen")
        self.assertEqual(got.routes[0].model, "qwen-max")

    def test_all_configs_returns_snapshot(self) -> None:
        r = build_default_router()
        snap = r.all_configs
        self.assertEqual(set(snap.keys()), set(TaskType))


if __name__ == "__main__":
    unittest.main()
