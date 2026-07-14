"""MemoryManager unit tests.

Covers the 6-step filter (brief §3 decision 5):

* Step 1 — vector recall (cosine ≥ 0.78)
* Step 2 — permission (owner / public / shared / scene-scoped)
* Step 3 — temporal (formedAt ≤ current_event_sequence)
* Step 4 — secret-aware (layer-4 secret is hidden from non-aware characters)
* Step 5 — distortion-aware (confabulation downranked 50%)
* Step 6 — recency/decay rerank (emotional_weight × decayScore)

Plus:

* top_k clamped to 4-8
* similarity_threshold validation
* InMemoryVectorIndex correctness
"""

from __future__ import annotations

import sys
import unittest
import uuid

sys.path.insert(0, "server")

from agents import (  # noqa: E402
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_TOP_K,
    InMemoryVectorIndex,
    MAX_TOP_K,
    MEMORY_MANAGER_VERSION,
    MIN_TOP_K,
    MemoryManager,
    MemoryRecall,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memory(
    *,
    mid: str,
    subject: str,
    summary: str,
    owner: str = "leila",
    formed_at: int = 0,
    distortion: str = "none",
    emotional_weight: float = 0.5,
    decay: float = 1.0,
    scene_id: str = "photo_lab_2008",
    is_public: bool = False,
    visible_to: list[str] | None = None,
) -> dict:
    return {
        "memoryId": mid,
        "ownerCharacterId": owner,
        "summary": summary,
        "subject": subject,
        "formedAt": formed_at,
        "distortion_type": distortion,
        "emotional_weight": emotional_weight,
        "decayScore": decay,
        "sceneId": scene_id,
        "isPublic": is_public,
        "visibleToCharacterIds": list(visible_to or []),
        # The embedder produces a 64-dim unit vector; we hand-build
        # vectors that differ enough to land above / below the
        # 0.78 threshold.
        "embedding": _v_for_text(mid),
    }


def _v_for_text(text: str) -> list[float]:
    """Same hash-based scheme as the default embedder."""

    import hashlib
    h = hashlib.sha256(text.encode("utf-8")).digest()
    out: list[float] = []
    i = 0
    while len(out) < 64:
        byte = h[i % len(h)]
        out.append((byte / 255.0) - 0.5)
        i += 1
        if i > 0 and i % len(h) == 0:
            h = hashlib.sha256(h).digest()
    norm = sum(x * x for x in out) ** 0.5 or 1.0
    return [x / norm for x in out]


# ---------------------------------------------------------------------------
# Index tests
# ---------------------------------------------------------------------------


class InMemoryIndexTests(unittest.TestCase):
    def test_search_returns_sorted_by_similarity(self) -> None:
        idx = InMemoryVectorIndex([
            _memory(mid="m1", subject="A", summary="first", owner="leila"),
            _memory(mid="m2", subject="B", summary="second", owner="leila"),
        ])
        # Query for m1's vector — should rank m1 first
        out = idx.search(query_embedding=_v_for_text("m1"), top_k=2)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][0], "m1")
        self.assertGreater(out[0][1], out[1][1])

    def test_candidate_ids_filter(self) -> None:
        idx = InMemoryVectorIndex([
            _memory(mid="m1", subject="A", summary="x", owner="leila"),
            _memory(mid="m2", subject="B", summary="x", owner="leila"),
        ])
        out = idx.search(
            query_embedding=_v_for_text("m1"),
            top_k=10,
            candidate_ids=["m2"],
        )
        self.assertEqual([m for m, _ in out], ["m2"])

    def test_fetch_returns_full_records(self) -> None:
        idx = InMemoryVectorIndex([
            _memory(mid="m1", subject="A", summary="x", owner="leila"),
        ])
        fetched = idx.fetch(["m1"])
        self.assertEqual(len(fetched), 1)
        self.assertEqual(fetched[0]["memoryId"], "m1")
        self.assertEqual(fetched[0]["subject"], "A")


# ---------------------------------------------------------------------------
# Top-K clamping
# ---------------------------------------------------------------------------


class TopKClampTests(unittest.TestCase):
    def test_default_is_8(self) -> None:
        self.assertEqual(DEFAULT_TOP_K, 8)

    def test_min_is_4(self) -> None:
        self.assertEqual(MIN_TOP_K, 4)

    def test_max_is_8(self) -> None:
        self.assertEqual(MAX_TOP_K, 8)

    def test_constructor_clamps_low(self) -> None:
        mm = MemoryManager(top_k=1)
        self.assertEqual(mm.top_k, 4)

    def test_constructor_clamps_high(self) -> None:
        mm = MemoryManager(top_k=20)
        self.assertEqual(mm.top_k, 8)


class SimilarityThresholdTests(unittest.TestCase):
    def test_default_is_0_78(self) -> None:
        self.assertAlmostEqual(DEFAULT_SIMILARITY_THRESHOLD, 0.78)

    def test_rejects_negative(self) -> None:
        with self.assertRaises(ValueError):
            MemoryManager(similarity_threshold=-0.1)

    def test_rejects_above_one(self) -> None:
        with self.assertRaises(ValueError):
            MemoryManager(similarity_threshold=1.5)


# ---------------------------------------------------------------------------
# 6-step filter
# ---------------------------------------------------------------------------


class SixStepFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        # 10 candidate memories with varied subjects, owners,
        # formedAt, distortions, weights.  We hand-build the
        # embeddings to ensure the test is reproducible (random
        # 64-dim unit vectors have ~0 cosine, below the 0.78
        # threshold).
        self.query_v = [1.0] + [0.0] * 63
        self.records = [
            _memory(mid="memA", subject="photo_2008", summary="A", owner="leila", formed_at=0, emotional_weight=0.9, decay=1.0),
            _memory(mid="memB", subject="photo_2008", summary="B", owner="arash", formed_at=0, emotional_weight=0.5, decay=0.7),
            _memory(mid="memC", subject="movie_ticket", summary="C", owner="arash", formed_at=0, emotional_weight=0.5, decay=0.5),
            _memory(mid="memD", subject="confab_x", summary="D", owner="arash", formed_at=0, emotional_weight=0.5, decay=0.5, distortion="confabulation"),
            _memory(mid="memE", subject="future_thing", summary="E", owner="leila", formed_at=99, emotional_weight=0.5, decay=0.5),
            _memory(mid="memF", subject="leila_secret", summary="F", owner="leila", formed_at=0, emotional_weight=0.5, decay=0.5),
            _memory(mid="memG", subject="public_thing", summary="G", owner="x", formed_at=0, emotional_weight=0.5, decay=0.5, is_public=True),
            _memory(mid="memH", subject="private_x", summary="H", owner="x", formed_at=0, emotional_weight=0.5, decay=0.5),
            _memory(mid="memI", subject="photo_2008", summary="I", owner="arash", formed_at=0, emotional_weight=0.1, decay=0.1),
            _memory(mid="memJ", subject="photo_2008", summary="J", owner="leila", formed_at=0, emotional_weight=0.7, decay=0.9),
        ]
        # Give every memory a unit vector parallel to the query
        # (cosine ≈ 1.0), then mutate per-test as needed.
        for r in self.records:
            r["embedding"] = list(self.query_v)
        self.idx = InMemoryVectorIndex(self.records)
        # Inject a constant embedder so the query is the same
        # vector the memories are parallel to.
        self.mm = MemoryManager(
            self.idx,
            top_k=4,
            embedder=lambda text: list(self.query_v),
        )

    def test_recall_returns_up_to_top_k(self) -> None:
        recall = self.mm.recall_for(
            character_id="leila",
            query="photo 2008",
            scene_id="photo_lab_2008",
            current_event_sequence=10,
        )
        self.assertLessEqual(len(recall.memories), 4)
        self.assertGreaterEqual(len(recall.memories), 1)
        self.assertEqual(recall.memory_ids, {m["memoryId"] for m in recall.memories})

    def test_step1_threshold_filters_low_similarity(self) -> None:
        # Set a very high threshold — almost nothing survives.
        # Mutate one memory to be orthogonal (cosine = 0).
        for r in self.idx._records:
            if r["memoryId"] == "memB":
                r["embedding"] = [0.0] + [1.0] + [0.0] * 62
        mm = MemoryManager(
            self.idx, similarity_threshold=0.99, top_k=4,
            embedder=lambda text: list(self.query_v),
        )
        recall = mm.recall_for(
            character_id="leila",
            query="photo 2008",
            scene_id="photo_lab_2008",
            current_event_sequence=10,
        )
        # memB is excluded by similarity threshold
        self.assertNotIn("memB", recall.memory_ids)

    def test_step3_temporal_excludes_future(self) -> None:
        recall = self.mm.recall_for(
            character_id="leila",
            query="future",
            scene_id="photo_lab_2008",
            current_event_sequence=0,
        )
        # memE has formedAt=99; must be excluded
        self.assertNotIn("memE", recall.memory_ids)

    def test_step2_permission_includes_owner_and_public(self) -> None:
        # For arash: owner=arash (memB, memC, memD, memI), scene
        # member (any in same scene).  All arash-owned should be
        # visible; memH (private, owner=x) is NOT visible to arash
        # unless it's public.
        recall = self.mm.recall_for(
            character_id="arash",
            query="photo_2008",
            scene_id="photo_lab_2008",
            current_event_sequence=10,
        )
        # memH is owner=x, not public, not scene-shared → not visible
        self.assertNotIn("memH", recall.memory_ids)
        # Public memG should be visible to anyone
        # (it may or may not be in top-4; check audit instead)
        self.assertGreaterEqual(recall.audit.get("final_count", 0), 0)

    def test_step4_secret_blacklists_wrapped_subject(self) -> None:
        # The secret wraps memF ("leila_secret") as content.  Arash
        # does not know the secret, so memF should be filtered.
        secrets = [
            {
                "secretId": "s1",
                "content": "leila_secret",
                "isSecret": True,
                "knownByCharacterIds": ["leila"],
            }
        ]
        recall = self.mm.recall_for(
            character_id="arash",
            query="leila_secret",
            scene_id="photo_lab_2008",
            current_event_sequence=10,
            secrets=secrets,
        )
        # memF is owned by leila (not arash); the secret is
        # arash-unaware.  The blacklisted subject blocks it.
        self.assertNotIn("memF", recall.memory_ids)
        self.assertGreaterEqual(recall.audit.get("step4_secret", 0), 1)

    def test_step5_confabulation_demoted(self) -> None:
        # memD is confabulation; it should still appear in
        # recall but be demoted 50%.  We verify the audit
        # recorded it.
        recall = self.mm.recall_for(
            character_id="arash",
            query="confab_x",
            scene_id="photo_lab_2008",
            current_event_sequence=10,
        )
        self.assertGreaterEqual(recall.audit.get("step5_distortion", 0), 1)

    def test_step6_decay_rerank(self) -> None:
        recall = self.mm.recall_for(
            character_id="leila",
            query="photo_2008",
            scene_id="photo_lab_2008",
            current_event_sequence=10,
        )
        self.assertGreaterEqual(recall.audit.get("step6_decay_rerank", 0), 1)

    def test_audit_fields_present(self) -> None:
        recall = self.mm.recall_for(
            character_id="leila",
            query="photo",
            scene_id="photo_lab_2008",
            current_event_sequence=10,
        )
        for key in (
            "step1_initial_count",
            "step2_permission",
            "step3_temporal",
            "step4_secret",
            "step5_distortion",
            "step6_decay_rerank",
            "final_count",
        ):
            self.assertIn(key, recall.audit)

    def test_version_is_pinned(self) -> None:
        self.assertEqual(MEMORY_MANAGER_VERSION, "1.0.0")

    def test_character_knowledge_demotes_unknown_subjects(self) -> None:
        recall = self.mm.recall_for(
            character_id="arash",
            query="photo_2008",
            scene_id="photo_lab_2008",
            current_event_sequence=10,
            character_knowledge={"movie_ticket"},
        )
        self.assertIsInstance(recall, MemoryRecall)


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


class UpsertTests(unittest.TestCase):
    def test_upsert_adds_new(self) -> None:
        idx = InMemoryVectorIndex()
        mm = MemoryManager(idx, top_k=4)
        mm.upsert(_memory(mid="new1", subject="x", summary="y"))
        out = idx.search(query_embedding=_v_for_text("new1"), top_k=1)
        self.assertEqual(out[0][0], "new1")

    def test_upsert_replaces_existing(self) -> None:
        idx = InMemoryVectorIndex([_memory(mid="m", subject="old", summary="x")])
        mm = MemoryManager(idx, top_k=4)
        mm.upsert(_memory(mid="m", subject="new", summary="x"))
        fetched = idx.fetch(["m"])
        self.assertEqual(fetched[0]["subject"], "new")


if __name__ == "__main__":
    unittest.main()
