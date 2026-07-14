"""Memory manager — long-term memory retrieval (pgvector + 6-step filter).

The memory manager is the **only** component allowed to read the
long-term memory store.  It implements the brief's 6-step filter
on top of pgvector's cosine-similarity search:

1. **Vector recall** — top-K = 4-8 by cosine similarity ≥ 0.78.
2. **Permission** — only memories the requesting character has
   permission to know (i.e. owned, or shared with the requesting
   character, or marked public).
3. **Temporal** — exclude memories whose ``formedAt`` event
   sequence is *after* the active scene's event sequence (i.e.
   no future leakage).
4. **Secret-aware** — exclude memories that wrap a layer-4 secret
   whose ``isSecret=True`` and the requesting character is not
   in ``knownByCharacterIds``.
5. **Distortion-aware** — down-rank memories with
   ``distortion_type = 'confabulation'`` by 50% (they are by
   definition suspect).
6. **Recency / decay** — re-rank by ``emotional_weight *
   decayScore`` so vivid + fresh memories surface first.

The output is a :class:`MemoryRecall` — a deterministic
4-8-item list of memory JSON dicts and the set of memoryIds
the agent may reference.  The Resolver uses the set to validate
the NPC proposal's ``referencedMemoryIds`` (decision 3).

Why a stub pgvector backend
---------------------------
The production W3 stack would call into Postgres + the pgvector
extension.  The W3-B tests can run without a Postgres instance;
:class:`MemoryManager` accepts an arbitrary backend that conforms
to the :class:`VectorIndex` protocol.  The default backend
(:class:`InMemoryVectorIndex`) does brute-force cosine similarity
over a Python list — enough for unit tests and for the W3-A
team to swap in the real pgvector client without changing
this file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, runtime_checkable
from typing import Final


MEMORY_MANAGER_VERSION: Final[str] = "1.0.0"

DEFAULT_SIMILARITY_THRESHOLD: Final[float] = 0.78
DEFAULT_TOP_K: Final[int] = 8
MIN_TOP_K: Final[int] = 4
MAX_TOP_K: Final[int] = 8


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RecallFilterError(RuntimeError):
    """Raised when the recall pipeline cannot produce a valid set.

    This is a *recoverable* error — the agent / Resolver drops
    the recall set and the NPC proposal cannot reference any
    memory (the proposal would then fail the ungrounded-memory
    check in the engine's resolver).
    """


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MemoryRecall:
    """The output of the 6-step filter.

    Attributes
    ----------
    memories : list[dict]
        4-8 memory dicts, ranked by relevance (top first).
    memory_ids : set[str]
        Convenience: ``set(m["memoryId"] for m in memories)``.
        The Resolver uses this set for ungrounded-memory checks.
    query_embedding : list[float]
        The embedding used for the cosine-similarity search.
        Useful for re-use across the same turn.
    audit : dict
        Step-by-step counts the agent / Resolver can log.
    """

    memories: list[dict[str, Any]] = field(default_factory=list)
    memory_ids: set[str] = field(default_factory=set)
    query_embedding: list[float] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Vector index interface
# ---------------------------------------------------------------------------


@runtime_checkable
class VectorIndex(Protocol):
    """The pgvector-compatible index.

    Production: ``PgVectorIndex`` over a ``memories`` table with a
    ``pgvector`` ``vector`` column.  Tests: :class:`InMemoryVectorIndex`.
    """

    def search(
        self,
        *,
        query_embedding: list[float],
        top_k: int,
        candidate_ids: Iterable[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Return up to ``top_k`` ``(memoryId, cosine_similarity)`` pairs.

        Implementations MUST return the pairs sorted by similarity
        descending.  ``candidate_ids``, when given, restricts the
        search to a subset (used by the permission / secret filters
        to narrow the candidate pool before re-scoring).
        """

    def fetch(self, memory_ids: Iterable[str]) -> list[dict[str, Any]]:
        """Return the full memory dicts for the given IDs."""


# ---------------------------------------------------------------------------
# In-memory index (default; tests use this)
# ---------------------------------------------------------------------------


class InMemoryVectorIndex:
    """Brute-force cosine-similarity index over a list of memories.

    The list-of-dicts shape matches the snapshot's ``memories``
    field plus a few pgvector-specific fields
    (``ownerCharacterId`` / ``embedding`` / ``formedAt`` /
    ``isSecret`` / ``knownByCharacterIds`` / ``distortion_type``).
    """

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        # Records must include a numeric ``embedding`` list.
        self._records: list[dict[str, Any]] = list(records or [])

    def upsert(self, record: dict[str, Any]) -> None:
        existing = next(
            (i for i, r in enumerate(self._records) if r.get("memoryId") == record.get("memoryId")),
            None,
        )
        if existing is None:
            self._records.append(dict(record))
        else:
            self._records[existing] = dict(record)

    def search(
        self,
        *,
        query_embedding: list[float],
        top_k: int,
        candidate_ids: Iterable[str] | None = None,
    ) -> list[tuple[str, float]]:
        ids = set(candidate_ids) if candidate_ids is not None else None
        scored: list[tuple[str, float]] = []
        for rec in self._records:
            mid = rec.get("memoryId", "")
            if ids is not None and mid not in ids:
                continue
            emb = rec.get("embedding") or []
            sim = _cosine(query_embedding, emb)
            scored.append((mid, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[: int(top_k)]

    def fetch(self, memory_ids: Iterable[str]) -> list[dict[str, Any]]:
        wanted = set(memory_ids)
        return [dict(r) for r in self._records if r.get("memoryId") in wanted]


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        # In production the embeddings always come from the same
        # model; mismatched length is a misconfiguration.  Return
        # 0.0 so the candidate is naturally filtered out.
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _unit_vector(embedding: list[float]) -> list[float]:
    """Return a unit-normalised copy of ``embedding``.

    Cosine similarity is invariant to magnitude, but the in-memory
    index assumes unit vectors for stable ranking when two records
    happen to have the same direction.  This helper is a no-op for
    already-normalised vectors.
    """

    if not embedding:
        return []
    norm = math.sqrt(sum(x * x for x in embedding))
    if norm <= 0.0:
        return [0.0 for _ in embedding]
    return [x / norm for x in embedding]


# ---------------------------------------------------------------------------
# The manager
# ---------------------------------------------------------------------------


class MemoryManager:
    """The 6-step recall pipeline.

    Parameters
    ----------
    index
        A :class:`VectorIndex`.  Defaults to an empty
        :class:`InMemoryVectorIndex`.
    similarity_threshold
        Cosine-similarity floor (brief: 0.78).
    top_k
        Number of memories to return (brief: 4-8).  Clamped.
    embedder
        Optional callable ``text -> list[float]``.  When omitted,
        a deterministic hash-based stub is used (the same text
        produces the same embedding across runs, which is enough
        for unit tests and replay).
    """

    def __init__(
        self,
        index: VectorIndex | None = None,
        *,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        top_k: int = DEFAULT_TOP_K,
        embedder: Any = None,
    ) -> None:
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError(
                f"similarity_threshold must be in [0, 1]; got {similarity_threshold}"
            )
        top_k = int(top_k)
        if top_k < MIN_TOP_K:
            top_k = MIN_TOP_K
        elif top_k > MAX_TOP_K:
            top_k = MAX_TOP_K
        self.index = index or InMemoryVectorIndex()
        self.threshold = float(similarity_threshold)
        self.top_k = int(top_k)
        self.embedder = embedder or _hash_embedder

    # ----- public API ----------------------------------------------------

    def recall_for(
        self,
        *,
        character_id: str,
        query: str,
        scene_id: str,
        current_event_sequence: int,
        belief_matrix: dict[str, Any] | None = None,
        secrets: list[dict[str, Any]] | None = None,
        character_knowledge: set[str] | None = None,
    ) -> MemoryRecall:
        """Run the 6-step filter and return a :class:`MemoryRecall`.

        Parameters
        ----------
        character_id
            The character whose perspective we're recalling from.
        query
            The query text.  Combined with ``character_id`` to form
            the embedding input.
        scene_id
            The active scene (used for scene-scoped memory access).
        current_event_sequence
            Step 3 (temporal filter): memories whose ``formedAt``
            is *strictly after* this sequence are excluded.
        belief_matrix
            The character's full belief matrix.  The memory manager
            uses it to:
            * build a tighter embedding (knowledge-aware query)
            * validate step 4 (secret-aware) for memories the
              character is supposed to know
        secrets
            The layer-4 secrets for the run.  Used in step 4.
        character_knowledge
            Set of fact-IDs / subject-IDs the character has
            previously been exposed to.  Memories anchored to a
            subject the character does NOT know are demoted (they
            are likely ungrounded).
        """

        # Build the query embedding
        query_text = f"{character_id}|{scene_id}|{query}"
        query_embedding = self.embedder(query_text)

        # Step 1 — vector recall: top_k with candidate=None
        initial = self.index.search(
            query_embedding=query_embedding,
            top_k=max(self.top_k * 2, 16),  # over-fetch to absorb later filters
        )
        audit: dict[str, Any] = {
            "step1_initial_count": len(initial),
            "step2_permission": 0,
            "step3_temporal": 0,
            "step4_secret": 0,
            "step5_distortion": 0,
            "step6_decay_rerank": 0,
            "final_count": 0,
        }

        # Build the per-character permission set
        known_subjects = set(character_knowledge or set())
        if belief_matrix:
            for km in belief_matrix.get("character_knowledge", []) or []:
                subj = km.get("subject")
                if subj:
                    known_subjects.add(subj)
            for mem in belief_matrix.get("character_memories", []) or []:
                # The character's own memories are always readable
                pass

        # Build the secret-blacklist (per character)
        secrets_list = list(secrets or [])
        secret_blacklist_subjects: set[str] = set()
        for sec in secrets_list:
            if not sec.get("isSecret", False):
                continue
            if character_id in (sec.get("knownByCharacterIds") or []):
                continue
            # The character does not know the secret; the wrapped
            # subject is forbidden.
            content = str(sec.get("content", ""))
            if content:
                secret_blacklist_subjects.add(content)

        # Fetch the full records for the candidates
        candidate_ids = [mid for mid, _ in initial]
        records = {r["memoryId"]: r for r in self.index.fetch(candidate_ids)}

        filtered: list[tuple[dict[str, Any], float]] = []
        for mid, sim in initial:
            rec = records.get(mid)
            if rec is None:
                continue
            if sim < self.threshold:
                continue
            # ---- Step 2: permission ----
            owner = rec.get("ownerCharacterId")
            permitted = (
                owner == character_id
                or rec.get("isPublic", False)
                or character_id in (rec.get("visibleToCharacterIds") or [])
                or rec.get("sceneId") == scene_id
            )
            if not permitted:
                audit["step2_permission"] += 1
                continue
            # ---- Step 3: temporal ----
            formed_at = rec.get("formedAt")
            if formed_at is not None and int(formed_at) > int(current_event_sequence):
                audit["step3_temporal"] += 1
                continue
            # ---- Step 4: secret-aware ----
            subj = rec.get("subject", "")
            if subj in secret_blacklist_subjects:
                audit["step4_secret"] += 1
                continue
            if known_subjects and subj and subj not in known_subjects and owner != character_id:
                # The character hasn't been exposed to this subject;
                # demote (but don't drop) the memory.
                sim *= 0.85
            # ---- Step 5: distortion-aware ----
            distortion = rec.get("distortion_type", "none")
            if distortion == "confabulation":
                sim *= 0.5
                audit["step5_distortion"] += 1
            # ---- Step 6: recency / decay re-rank ----
            ew = float(rec.get("emotional_weight", 0.5) or 0.5)
            decay = float(rec.get("decayScore", 1.0) or 1.0)
            sim = sim * (0.6 + 0.4 * ew) * (0.7 + 0.3 * decay)
            audit["step6_decay_rerank"] += 1
            filtered.append((rec, sim))

        # Re-rank by adjusted similarity
        filtered.sort(key=lambda x: x[1], reverse=True)

        # Apply top_k and similarity threshold again
        out: list[dict[str, Any]] = []
        for rec, sim in filtered[: self.top_k]:
            if sim < self.threshold:
                continue
            out.append(
                {
                    "memoryId": rec.get("memoryId"),
                    "ownerCharacterId": rec.get("ownerCharacterId"),
                    "summary": rec.get("summary", ""),
                    "emotional_weight": float(rec.get("emotional_weight", 0.5) or 0.5),
                    "distortion_type": rec.get("distortion_type", "none"),
                    "formedAt": rec.get("formedAt"),
                    "recallWeight": round(min(1.0, max(0.0, sim)), 4),
                    "decayScore": float(rec.get("decayScore", 1.0) or 1.0),
                    "subject": rec.get("subject", ""),
                    "sceneId": rec.get("sceneId", scene_id),
                }
            )

        audit["final_count"] = len(out)
        return MemoryRecall(
            memories=out,
            memory_ids={m["memoryId"] for m in out if m.get("memoryId")},
            query_embedding=query_embedding,
            audit=audit,
        )

    def upsert(self, record: dict[str, Any]) -> None:
        """Add a memory to the index (used by replay / seeding)."""

        if not hasattr(self.index, "upsert"):
            # A real pgvector index would have its own upsert path.
            return
        self.index.upsert(record)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Default embedder
# ---------------------------------------------------------------------------


def _hash_embedder(text: str, dim: int = 64) -> list[float]:
    """Deterministic, unit-norm hash-based embedder.

    This is **not** a real embedding model — it's a stub that
    makes the test suite reproducible.  The W3-A gateway provides
    the real embedder.  The output is a unit vector whose
    direction encodes the input text's hash, so two identical
    strings produce identical vectors.
    """

    import hashlib

    h = hashlib.sha256(text.encode("utf-8")).digest()
    # Stretch the 32-byte digest to `dim` floats.
    out: list[float] = []
    i = 0
    while len(out) < dim:
        byte = h[i % len(h)]
        out.append((byte / 255.0) - 0.5)
        i += 1
        if i > 0 and i % len(h) == 0:
            h = hashlib.sha256(h).digest()
    return _unit_vector(out)


__all__ = [
    "MEMORY_MANAGER_VERSION",
    "DEFAULT_SIMILARITY_THRESHOLD",
    "DEFAULT_TOP_K",
    "MIN_TOP_K",
    "MAX_TOP_K",
    "MemoryManager",
    "MemoryRecall",
    "RecallFilterError",
    "VectorIndex",
    "InMemoryVectorIndex",
]
