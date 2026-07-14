"""W9 sanity tests — vector_search / cache / observability / load test.

Lightweight smoke tests that exercise the W9 surface
without external infrastructure.  The acceptance numbers
themselves are checked by the load test (see
:mod:`tests.performance.test_load`); this file verifies
the modules import, the keys / TTLs / metrics are wired
correctly, and the dashboards / configs parse.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))


class VectorSearchSanityTests(unittest.TestCase):
    def setUp(self) -> None:
        from server import vector_search

        self.vector_search = vector_search

    def test_constants_match_brief(self) -> None:
        vs = self.vector_search
        # Brief: pgvector HNSW; cosine similarity.
        self.assertIn("vector_cosine_ops", vs.HNSW_INDEX_DDL)
        self.assertIn("hnsw", vs.HNSW_INDEX_DDL)
        # 4-8 段召回延迟 < 100ms (p95).
        self.assertEqual(vs.LATENCY_BUDGET_MS, 100.0)
        self.assertEqual(vs.DEFAULT_TOP_K, 8)
        # Reasonable HNSW parameters.
        self.assertEqual(vs.HNSW_M, 16)
        self.assertEqual(vs.HNSW_EF_CONSTRUCTION, 64)
        self.assertEqual(vs.HNSW_EF_SEARCH, 40)

    def test_in_memory_index_round_trip(self) -> None:
        vs = self.vector_search
        idx = vs.InMemoryVectorIndex(dim=8)
        # Normalisation: zero vector stays zero; non-zero is unit-length.
        zero = vs._normalise([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(zero, [0.0] * 8)
        unit = vs._normalise([3.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        # 3-4-5 triangle → 3/5 + 4/5.
        self.assertAlmostEqual(unit[0], 0.6, places=6)
        self.assertAlmostEqual(unit[1], 0.8, places=6)

        # upsert + search.
        idx.upsert(
            memory_id="m1",
            run_id="r1",
            segment_id="2008",
            summary="leila looks at the photo",
            embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        idx.upsert(
            memory_id="m2",
            run_id="r1",
            segment_id="2011",
            summary="arash hides the letter",
            embedding=[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        hits, stats = idx.search(
            run_id="r1",
            query_embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            top_k=4,
        )
        self.assertEqual(stats.index_path, "in_memory")
        # 4-8 segments: top_k=4 returns 2 (we only inserted 2).
        self.assertEqual(len(hits), 2)
        # Most similar is m1.
        self.assertEqual(hits[0].memory_id, "m1")
        self.assertGreater(hits[0].score, 0.99)

    def test_facade_picks_in_memory_for_sqlite(self) -> None:
        from server.db import engine

        idx = self.vector_search.MemoryRecallIndex(engine)
        self.assertEqual(idx.index_path, "in_memory")
        h = idx.healthcheck()
        self.assertEqual(h["indexPath"], "in_memory")
        self.assertEqual(h["efSearch"], self.vector_search.HNSW_EF_SEARCH)

    def test_pgvector_literal_format(self) -> None:
        s = self.vector_search._to_pgvector_literal([0.1, 0.2, 0.3])
        self.assertEqual(s, "[0.1000000,0.2000000,0.3000000]")


class CacheSanityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from server import cache

        # Force the in-memory backend for the test.
        os.environ["G1N_CACHE_BACKEND"] = "memory"
        cache.reset_default_cache()
        self.cache_mod = cache
        self.service = cache.get_default_cache()

    async def test_ttls_match_brief(self) -> None:
        c = self.cache_mod
        # Brief: WorldSnapshot 5min / ResolverOutcome 10min / static permanent.
        self.assertEqual(c.TTL_WORLD_SNAPSHOT, 5 * 60)
        self.assertEqual(c.TTL_RESOLVER_OUTCOME, 10 * 60)
        self.assertIsNone(c.TTL_SCENE_METADATA)  # permanent

    async def test_world_snapshot_round_trip(self) -> None:
        snap = {"runId": "r1", "canonicalState": {"currentSceneId": "photo_lab_2008"}}
        await self.service.set_world_snapshot("r1", snap)
        got = await self.service.get_world_snapshot("r1")
        self.assertEqual(got, snap)
        await self.service.invalidate_world_snapshot("r1")
        self.assertIsNone(await self.service.get_world_snapshot("r1"))

    async def test_resolver_outcome_round_trip(self) -> None:
        outcome = {"outcomeId": "o1", "idempotencyKey": "idem-1", "acceptedNpcAction": {}}
        await self.service.set_resolver_outcome("idem-1", outcome)
        got = await self.service.get_resolver_outcome("idem-1")
        self.assertEqual(got, outcome)

    async def test_scene_metadata_permanent(self) -> None:
        meta = {"sceneId": "photo_lab_2008", "title": "暗房", "allowedBeats": 4}
        await self.service.set_scene_metadata("case_01", "photo_lab_2008", meta)
        got = await self.service.get_scene_metadata("case_01", "photo_lab_2008")
        self.assertEqual(got, meta)

    async def test_get_or_load_propagates_real_errors(self) -> None:
        """W9 红线 1: cache miss must not mask real errors."""

        async def _loader() -> None:
            raise RuntimeError("db down — do not swallow me")

        with self.assertRaises(RuntimeError):
            await self.service.get_or_load_world_snapshot("r-missing", _loader)

    async def test_hit_rate_accounting(self) -> None:
        # 3 hits, 1 miss on the world snapshot.
        await self.service.set_world_snapshot("r-acc", {"v": 1})
        await self.service.get_world_snapshot("r-acc")
        await self.service.get_world_snapshot("r-acc")
        await self.service.get_world_snapshot("r-acc")
        await self.service.get_world_snapshot("r-miss")
        stats = self.service.stats()
        self.assertEqual(stats.hits, 3)
        self.assertEqual(stats.misses, 1)
        self.assertEqual(stats.hit_rate(), 0.75)

    async def test_depends_yields_service(self) -> None:
        from server.cache import get_cache_service

        gen = get_cache_service()
        s = await gen.__anext__()
        self.assertIs(s, self.service)
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass


class ObservabilitySanityTests(unittest.TestCase):
    def setUp(self) -> None:
        from server import observability

        observability.reset_default_registry()
        observability.reset_default_tracer()
        self.obs = observability
        self.reg = observability.get_default_registry()

    def test_record_model_call_increments(self) -> None:
        self.reg.record_model_call(
            agent="npc_agent",
            model="deepseek-v3",
            provider="deepseek",
            latency_ms=320.0,
            input_tokens=512,
            output_tokens=140,
            cost_cny=0.002,
        )
        body = self.reg.render()
        self.assertIn("g1n_model_call_latency_ms", body)
        self.assertIn("g1n_model_call_cost_cny_total", body)
        self.assertIn("npc_agent", body)
        self.assertIn("deepseek-v3", body)

    def test_pii_safe_label(self) -> None:
        self.obs._safe_label("user-123", prefix="u_")
        # Hash is sha256[:12] prefixed.
        s = self.obs._safe_label("user-123", prefix="u_")
        self.assertTrue(s.startswith("u_"))
        self.assertEqual(len(s), 2 + 12)
        # Empty input.
        self.assertEqual(self.obs._safe_label(""), "h_none")

    def test_degradation_counter(self) -> None:
        self.reg.record_degradation(3)
        self.reg.record_degradation(3)
        self.reg.record_degradation(4)
        body = self.reg.render()
        self.assertIn('level="L3"', body)
        self.assertIn('level="L4"', body)

    def test_cache_hit_rate_gauge(self) -> None:
        for _ in range(8):
            self.reg.record_cache(kind="world_snapshot", hit=True)
        for _ in range(2):
            self.reg.record_cache(kind="world_snapshot", hit=False)
        body = self.reg.render()
        self.assertIn("g1n_cache_hit_rate", body)
        self.assertIn("world_snapshot", body)

    def test_vector_search_observation(self) -> None:
        self.reg.record_vector_search(
            index_path="pgvector", latency_ms=42.0, p95_budget_exceeded=False
        )
        self.reg.record_vector_search(
            index_path="pgvector", latency_ms=150.0, p95_budget_exceeded=True
        )
        body = self.reg.render()
        self.assertIn("g1n_vector_search_ms", body)
        self.assertIn("g1n_vector_search_p95_budget_exceeded_total", body)

    def test_alert_rules_dont_explode_on_empty(self) -> None:
        # An empty registry must not raise in the alert evaluator.
        fired = self.obs.evaluate_alerts(registry=self.reg)
        # No P0 (no L3 trips), no error rate (no requests), no p95
        # breach (insufficient samples).
        for f in fired:
            self.assertNotEqual(f["severity"], "p0")

    def test_p95_budget_alert_fires(self) -> None:
        # 60 vector searches, ~50% over budget.
        for i in range(60):
            self.reg.record_vector_search(
                index_path="pgvector",
                latency_ms=200.0 if i % 2 == 0 else 30.0,
                p95_budget_exceeded=(i % 2 == 0),
            )
        fired = self.obs.evaluate_alerts(registry=self.reg)
        ids = [f["id"] for f in fired]
        self.assertIn("vector.p95", ids)

    def test_error_rate_alert_fires(self) -> None:
        # 5xx every request.
        for _ in range(20):
            self.reg.record_http(
                route="/v1/runs/:id/actions",
                method="POST",
                status_code=500,
                duration_s=0.1,
            )
        for _ in range(5):
            self.reg.record_http(
                route="/v1/runs/:id/actions",
                method="POST",
                status_code=200,
                duration_s=0.1,
            )
        fired = self.obs.evaluate_alerts(registry=self.reg)
        ids = [f["id"] for f in fired]
        self.assertIn("http.error_rate", ids)

    def test_grafana_dashboard_json(self) -> None:
        d = self.obs.GRAFANA_DASHBOARD_JSON
        self.assertEqual(d["uid"], "g1n-server-overview")
        self.assertGreaterEqual(len(d["panels"]), 8)
        # Each panel references a real metric from the registry.
        for panel in d["panels"]:
            targets = panel.get("targets") or []
            self.assertGreater(len(targets), 0, panel)

    def test_tracer_noop_default(self) -> None:
        from server.observability import NoopTracer, trace_turn

        tracer = NoopTracer()
        with trace_turn("r1", "photo_lab_2008", tracer=tracer) as span:
            span.set_attribute("eventSequence", 1)
        self.assertEqual(len(tracer.spans), 1)
        self.assertEqual(tracer.spans[0].name, "g1n.turn")
        self.assertIn("eventSequence", tracer.spans[0].attributes)


class LoadTestSanityTests(unittest.TestCase):
    def setUp(self) -> None:
        # Re-import the module each time so the isolation
        # env-var enforcement is fresh.
        import importlib

        if "tests.performance.test_load" in sys.modules:
            importlib.reload(sys.modules["tests.performance.test_load"])
        else:
            sys.path.insert(0, str(ROOT / "tests" / "performance"))
            import tests.performance.test_load  # noqa: F401

        self.mod = sys.modules["tests.performance.test_load"]

    def test_isolation_env(self) -> None:
        # The module must re-assert the isolation vars on
        # import; if a CI step sets G1N_DB_URL first, the
        # load test should still default to the load-test
        # SQLite.
        self.assertIn("load_test.db", os.environ.get("G1N_DB_URL", ""))
        self.assertEqual(os.environ.get("G1N_CACHE_BACKEND"), "memory")
        self.assertEqual(os.environ.get("G1N_USE_MOCK"), "1")
        self.assertEqual(os.environ.get("OTEL_SDK_DISABLED"), "true")

    def test_acceptance_thresholds(self) -> None:
        self.assertEqual(self.mod.P95_BUDGET_S, 4.0)
        self.assertEqual(self.mod.PER_RUN_COST_BUDGET_CNY, 0.8)
        self.assertEqual(self.mod.BATCH_RUN_TARGET, 100)
        self.assertEqual(self.mod.ERROR_RATE_BUDGET, 0.01)
        self.assertEqual(self.mod.DEFAULT_USERS, 100)
        self.assertEqual(self.mod.DEFAULT_RUN_TIME_S, 30 * 60)

    def test_assert_w9_acceptance_passes(self) -> None:
        r = self.mod.BatchResult(
            runs_completed=100,
            runs_failed=0,
            total_actions=1200,
            p95_latency_ms=3500.0,
            avg_cost_cny=0.6,
            max_cost_cny=0.75,
            error_rate=0.0,
        )
        # Should not raise.
        self.mod.assert_w9_acceptance(r)

    def test_assert_w9_acceptance_fails_on_p95(self) -> None:
        r = self.mod.BatchResult(
            runs_completed=100,
            p95_latency_ms=5000.0,
            max_cost_cny=0.5,
            error_rate=0.0,
        )
        with self.assertRaises(AssertionError) as ctx:
            self.mod.assert_w9_acceptance(r)
        self.assertIn("P95", str(ctx.exception))

    def test_assert_w9_acceptance_fails_on_cost(self) -> None:
        r = self.mod.BatchResult(
            runs_completed=100,
            p95_latency_ms=3000.0,
            max_cost_cny=1.5,
            error_rate=0.0,
        )
        with self.assertRaises(AssertionError) as ctx:
            self.mod.assert_w9_acceptance(r)
        self.assertIn("cost", str(ctx.exception).lower())

    def test_assert_w9_acceptance_fails_on_runs_failed(self) -> None:
        r = self.mod.BatchResult(
            runs_completed=98,
            runs_failed=2,
            p95_latency_ms=3000.0,
            max_cost_cny=0.5,
            error_rate=0.02,
        )
        with self.assertRaises(AssertionError) as ctx:
            self.mod.assert_w9_acceptance(r)
        # Both 100-runs and error-rate rules fire.
        msg = str(ctx.exception)
        self.assertIn("100", msg)


class ConfigSanityTests(unittest.TestCase):
    def test_cloudflare_json_parses(self) -> None:
        path = ROOT / "infra" / "cdn" / "cloudflare.json"
        with open(path, "r", encoding="utf-8") as fp:
            cfg = json.load(fp)
        self.assertEqual(cfg["version"], "1.0.0")
        # Brief: artifacts 30d / audio 90d / api no-cache.
        rules = {r["name"]: r for r in cfg["cache"]["rules"]}
        self.assertIn("artifacts-30d", rules)
        self.assertIn("audio-90d", rules)
        self.assertIn("api-no-cache", rules)
        self.assertEqual(rules["artifacts-30d"]["edge_ttl"], 30 * 24 * 3600)
        self.assertEqual(rules["audio-90d"]["edge_ttl"], 90 * 24 * 3600)
        # The api rule must be no-cache (W9 红线 2).
        self.assertEqual(rules["api-no-cache"]["cache_level"], "bypass")
        # Acceptance checklist must include the headers.
        checklist = cfg["acceptanceChecklist"]
        self.assertIn("api_no_cache_header", checklist)

    def test_k8s_yaml_parses(self) -> None:
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        path = ROOT / "infra" / "scaling" / "k8s.yaml"
        with open(path, "r", encoding="utf-8") as fp:
            docs = list(yaml.safe_load_all(fp))
        # Brief: max 10 pods, CPU > 70%, mem > 80%, queue > 50, 20 conn/pod.
        hpas = [d for d in docs if d and d.get("kind") == "HorizontalPodAutoscaler"]
        self.assertEqual(len(hpas), 2)  # prod + load-test
        prod = next(h for h in hpas if h["metadata"]["namespace"] == "g1n-prod")
        self.assertEqual(prod["spec"]["maxReplicas"], 10)
        # Triggers.
        triggers = {(m["type"], m["resource"]["name"], m["resource"]["target"]["averageUtilization"])
                    for m in prod["spec"]["metrics"] if m["type"] == "Resource"}
        self.assertIn(("Resource", "cpu", 70), triggers)
        self.assertIn(("Resource", "memory", 80), triggers)
        # Queue length > 50 (the custom-metric trigger).  Look only at the
        # top-level ``metrics:`` entries, not the HPA ``behavior.policies:``
        # block (which also has a ``type: Pods`` for the scale-up policy).
        queue_metrics = [m for m in prod["spec"]["metrics"] if m.get("type") == "Pods" and "pods" in m]
        self.assertEqual(len(queue_metrics), 1)
        self.assertEqual(queue_metrics[0]["pods"]["metric"]["name"], "g1n_inflight_actions")
        self.assertEqual(queue_metrics[0]["pods"]["target"]["averageValue"], "50")
        # DB pool = 20 / pod.
        cfg = [d for d in docs if d and d.get("kind") == "ConfigMap"
               and d["metadata"]["name"] == "g1n-server-config"
               and d["metadata"]["namespace"] == "g1n-prod"]
        self.assertEqual(len(cfg), 1)
        self.assertEqual(cfg[0]["data"]["G1N_DB_POOL"], "20")


if __name__ == "__main__":
    unittest.main()
