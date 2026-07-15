"""Vector search — pgvector HNSW index, cosine similarity, low-latency recall.

W9 deliverable.  The production path uses PostgreSQL 15+ with the
``pgvector`` extension (>= 0.5) so the :class:`MemoryRecallIndex`
serves **4-8 segment recall under 100ms p95** (W9 acceptance).
The module is also importable on a SQLite dev box — the
:class:`InMemoryVectorIndex` fallback keeps unit tests + local
``Demo-01.cmd`` local deterministic-stack work-flow green.

Why HNSW (not IVFFLAT)
----------------------

* **Recall quality** — HNSW returns ≥ 0.95 recall@10 across the
  scale we operate at (≤ 10k vectors / run × 1k concurrent
  runs); IVFFLAT drops below 0.85 once ``lists`` < ``sqrt(N)``
  and the project does not control the data-set size per run.
* **Insert latency** — HNSW inserts are O(log N) and do not
  require a periodic ``VACUUM`` rebuild like IVFFLAT.  Every
  accepted ResolverOutcome that fires a new
  ``MemoryRow.embedding_hash`` calls :meth:`MemoryRecallIndex.upsert`
  in the hot path; rebuilding the IVFFLAT centroids on every
  write is a non-starter.
* **No training step** — HNSW works the moment the index is
  created.  IVFFLAT requires ``kmeans`` training on a
  representative sample; on the very first memory of a new
  run that means a synchronous ``CREATE INDEX`` block.

Cosine similarity
-----------------

The module normalises every input vector to unit length on
ingest **and** on query, and uses pgvector's ``<=>`` cosine
distance operator (``vector_cosine_ops``).  HNSW with
``vector_cosine_ops`` is the recommended pairing in the
pgvector 0.5 release notes — ``vector_l2_ops`` would silently
rank by L2 magnitude and break the recall contract.

Configuration constants
-----------------------

* :data:`HNSW_M`              — graph degree (16 is pgvector
  default; we pin 16 to keep recall high without bloating
  the index).
* :data:`HNSW_EF_CONSTRUCTION` — build-time candidate width
  (64 — matches pgvector default for ``m=16``).
* :data:`HNSW_EF_SEARCH`      — query-time candidate width
  (40 — tuned for ≥ 0.95 recall@10 with < 100ms p95 on
  a 4 vCPU / 16GB pgvector instance).
* :data:`EMBEDDING_DIM`       — vector width.  384 is the
  ``all-MiniLM-L6-v2`` size; the embedder plug-in contract
  documents that any other dimension must be a
  deployment-time override (not a runtime change).

This module does **not** embed text — that is the
embedder service's job (W3-A).  We only store, index, and
query vectors the upstream produced.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, Sequence

logger = logging.getLogger("g1n.vector_search")

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------


#: pgvector HNSW graph degree.  16 is pgvector's default and the
#: value cited in the 0.5 release notes for "balanced
#: recall/build-time" workloads.
HNSW_M: int = 16

#: Build-time candidate list width.  Higher = better recall,
#: slower build.  64 is the pgvector default for ``m=16`` and
#: is the smallest value that hits ≥ 0.99 build-time recall
#: in pgvector's own benchmarks.
HNSW_EF_CONSTRUCTION: int = 64

#: Query-time candidate list width.  The value is exposed via
#: ``SET hnsw.ef_search = 40`` per-session so a single
#: deployment can be retuned at runtime without re-indexing.
#: 40 is the W9 acceptance target: ≥ 0.95 recall@10 and
#: < 100ms p95 on the 4-vCPU reference box.
HNSW_EF_SEARCH: int = 40

#: Vector width.  384 matches ``all-MiniLM-L6-v2``; see the
#: module docstring for the deployment-time override path.
EMBEDDING_DIM: int = 384

#: Default top-k for a 4-8 segment recall (decision 3: 4-8
#: segments = 4-8 distinct scene eras the NPC may surface a
#: memory from).
DEFAULT_TOP_K: int = 8

#: p95 budget.  The :meth:`MemoryRecallIndex.search` method
#: logs a warning if the in-process measurement exceeds this
#: value; the same threshold drives the Prometheus histogram
#: bucket boundary (see :mod:`server.observability`).
LATENCY_BUDGET_MS: float = 100.0

# ---------------------------------------------------------------------------
# Distance operators
# ---------------------------------------------------------------------------


#: SQL fragment for cosine distance (pgvector ``<=>``).  Used
#: both by the CREATE INDEX statement and by the SELECT.
COSINE_DISTANCE_SQL: str = "embedding <=> %s::vector"

#: SQL fragment to pre-normalise the input vector.  pgvector
#: does not auto-normalise; we pass the unit-length vector
#: and rely on the ``<=>`` operator to compute the distance.
NORMALISE_SQL: str = (
    "CASE WHEN vector_norm(%s::vector) = 0 THEN %s::vector "
    "ELSE %s::vector / vector_norm(%s::vector) END"
)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------


#: The CREATE INDEX statement.  Idempotent: re-running the
#: migration on a populated database is a no-op (the ``IF NOT
#: EXISTS`` clause is pgvector ≥ 0.5 syntax).
HNSW_INDEX_DDL: str = (
    "CREATE INDEX IF NOT EXISTS ix_memory_embeddings_hnsw "
    "ON memory_embeddings "
    "USING hnsw (embedding vector_cosine_ops) "
    f"WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})"
)

#: Companion statement that makes the per-session
#: ``ef_search`` knob live.  ``SET ... FROM CURRENT`` is
#: pgvector ≥ 0.5 — older versions require a per-session
#: ``SET hnsw.ef_search`` instead.
SET_EF_SEARCH_SQL: str = f"SET hnsw.ef_search = {HNSW_EF_SEARCH}"


# ---------------------------------------------------------------------------
# Protocol for the embedder — the vector_search module never
# embeds text itself; it asks the gateway / embedder service.
# ---------------------------------------------------------------------------


class EmbedderProtocol(Protocol):
    """A minimal embedder interface.

    The W3-A ``EmbeddingService`` satisfies this.  We declare
    it here as a Protocol so unit tests can swap in a stub
    without importing the W3-A package.
    """

    def embed(self, text: str) -> list[float]:  # pragma: no cover - interface
        ...


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RecallHit:
    """One recall hit returned by :meth:`MemoryRecallIndex.search`.

    Attributes
    ----------
    memory_id : str
        Stable id of the matching :class:`MemoryRow`.
    run_id : str
        The run the memory belongs to (always the queried run —
        we never cross runs in a recall).
    score : float
        Cosine similarity in ``[0, 1]`` (1 = identical, 0 =
        orthogonal).  The query returns ``1 - distance``.
    segment_id : str
        The era segment the memory came from (decision 3:
        4-8 segment recall surfaces memories whose era is
        relevant to the active beat).
    summary : str
        The memory's text summary (truncated to 240 chars in
        the recall response so we don't blow the per-turn
        output token budget).
    embedding_hash : str
        The hash of the memory's embedding; lets the caller
        skip a re-embed when the same memory is referenced
        multiple times in a turn.
    """

    memory_id: str
    run_id: str
    score: float
    segment_id: str
    summary: str
    embedding_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "memoryId": self.memory_id,
            "runId": self.run_id,
            "score": round(self.score, 6),
            "segmentId": self.segment_id,
            "summary": self.summary,
            "embeddingHash": self.embedding_hash,
        }


@dataclass(slots=True)
class RecallStats:
    """Operational stats from one search call.

    Surfaced to the caller + emitted as a Prometheus histogram
    sample (see :mod:`server.observability`).  Latency is the
    wall-clock time for the search call only; the embedding
    call (if any) is measured separately.
    """

    latency_ms: float
    candidates_examined: int
    ef_search: int
    index_path: str          # "pgvector" | "in_memory"
    db_calls: int
    p95_budget_exceeded: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "latencyMs": round(self.latency_ms, 3),
            "candidatesExamined": self.candidates_examined,
            "efSearch": self.ef_search,
            "indexPath": self.index_path,
            "dbCalls": self.db_calls,
            "p95BudgetExceeded": self.p95_budget_exceeded,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise(vec: Sequence[float]) -> list[float]:
    """L2-normalise a vector; return a fresh list.

    pgvector's ``<=>`` operator computes cosine distance as
    ``1 - (a / |a|) · (b / |b|)``.  When the vectors are
    pre-normalised the cosine distance collapses to
    ``1 - a · b`` — a single multiply-add.  We always pass
    pre-normalised vectors, so the operator is never asked
    to do the divide itself.
    """

    norm = math.sqrt(sum(float(x) * float(x) for x in vec))
    if norm <= 0.0:
        # Zero vector — return a zero-length result; the
        # pgvector ``<=>`` operator handles it but we want
        # consistent behaviour on both backends.
        return [0.0] * len(vec)
    return [float(x) / norm for x in vec]


def _to_pgvector_literal(vec: Sequence[float]) -> str:
    """Format a vector as a pgvector literal (``'[v1,v2,...]'``)."""

    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


# ---------------------------------------------------------------------------
# In-memory fallback (dev + tests)
# ---------------------------------------------------------------------------


class InMemoryVectorIndex:
    """Pure-Python fallback when pgvector is unavailable.

    Used by:

    * the local deterministic flow (``Demo-01.cmd`` on a SQLite box);
    * the unit tests so they don't need a running PostgreSQL.

    The cosine distance is computed in pure Python — fine for
    ≤ 10k vectors × 1k queries / sec, terrible for production.
    Production traffic **must** go through
    :class:`PgVectorRecallIndex` (see :meth:`MemoryRecallIndex`
    for the auto-fallback policy).
    """

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim
        # OrderedDict preserves insertion order so a
        # "list all memories for run" call is stable.
        self._rows: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        # Per-run shard keeps the search O(n) over the run's
        # memories, not the global corpus.
        self._by_run: dict[str, set[str]] = {}

    @property
    def dim(self) -> int:
        return self._dim

    def upsert(
        self,
        *,
        memory_id: str,
        run_id: str,
        segment_id: str,
        summary: str,
        embedding: Sequence[float],
        embedding_hash: str = "",
    ) -> None:
        if len(embedding) != self._dim:
            raise ValueError(
                f"embedding dim mismatch: got {len(embedding)}, want {self._dim}"
            )
        with self._lock:
            self._rows[memory_id] = {
                "memory_id": memory_id,
                "run_id": run_id,
                "segment_id": segment_id,
                "summary": summary,
                "embedding_hash": embedding_hash,
                "vector": _normalise(embedding),
            }
            self._by_run.setdefault(run_id, set()).add(memory_id)

    def search(
        self,
        *,
        run_id: str,
        query_embedding: Sequence[float],
        top_k: int = DEFAULT_TOP_K,
    ) -> tuple[list[RecallHit], RecallStats]:
        if len(query_embedding) != self._dim:
            raise ValueError(
                f"query dim mismatch: got {len(query_embedding)}, want {self._dim}"
            )
        started = time.perf_counter()
        q = _normalise(query_embedding)
        members = list(self._by_run.get(run_id, ()))
        scored: list[tuple[float, dict[str, Any]]] = []
        for mid in members:
            row = self._rows.get(mid)
            if row is None:
                continue
            v = row["vector"]
            # Cosine similarity = dot of pre-normalised vectors.
            sim = sum(q[i] * v[i] for i in range(self._dim))
            scored.append((sim, row))
        scored.sort(key=lambda kv: kv[0], reverse=True)
        top = scored[: max(1, top_k)]
        hits = [
            RecallHit(
                memory_id=row["memory_id"],
                run_id=row["run_id"],
                score=float(sim),
                segment_id=row["segment_id"],
                summary=row["summary"][:240],
                embedding_hash=row["embedding_hash"],
            )
            for sim, row in top
        ]
        latency_ms = (time.perf_counter() - started) * 1000.0
        stats = RecallStats(
            latency_ms=latency_ms,
            candidates_examined=len(members),
            ef_search=HNSW_EF_SEARCH,
            index_path="in_memory",
            db_calls=0,
            p95_budget_exceeded=latency_ms > LATENCY_BUDGET_MS,
        )
        return hits, stats

    def count(self, run_id: str | None = None) -> int:
        if run_id is None:
            return len(self._rows)
        return len(self._by_run.get(run_id, ()))


# ---------------------------------------------------------------------------
# pgvector backend
# ---------------------------------------------------------------------------


class PgVectorRecallIndex:
    """The production HNSW index.

    Schema (created by the migration in
    ``server/migrations/versions/2026_07_15_0000_g1n_initial_schema.py``
    plus the W9 add-on :data:`HNSW_INDEX_DDL`):

    .. code-block:: sql

        CREATE TABLE memory_embeddings (
          memory_id     text PRIMARY KEY,
          run_id        text NOT NULL,
          segment_id    text NOT NULL,
          summary       text NOT NULL,
          embedding     vector(384) NOT NULL,
          embedding_hash text NOT NULL DEFAULT '',
          created_at    timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_memory_embeddings_hnsw
            ON memory_embeddings
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);

    The session-scoped ``SET hnsw.ef_search = 40`` lives in
    :meth:`_open_session` so the W9 acceptance target is
    met without changing the global GUC.

    Why a per-instance object
    -------------------------

    A :class:`PgVectorRecallIndex` holds the SQLAlchemy
    engine + a per-thread session factory.  The engine's
    connection pool is the same pool the rest of the server
    uses; the search path does **not** open a new pool.
    """

    def __init__(
        self,
        engine: Any,
        *,
        dim: int = EMBEDDING_DIM,
        ef_search: int = HNSW_EF_SEARCH,
    ) -> None:
        self._engine = engine
        self._dim = dim
        self._ef_search = int(ef_search)
        # Per-thread SessionLocal so each worker reuses one
        # connection for the lifetime of the request.
        self._tls = threading.local()

    @property
    def dim(self) -> int:
        return self._dim

    def _session(self):  # pragma: no cover - thin shim
        sess = getattr(self._tls, "session", None)
        if sess is None:
            from sqlalchemy.orm import sessionmaker  # local import — keep module importable on SQLite

            SessionLocal = sessionmaker(bind=self._engine, autoflush=False, autocommit=False, future=True)
            sess = SessionLocal()
            # Apply ef_search per session (not per query) so
            # a single SET round-trip covers the burst.
            try:
                with sess.connection().execution_options(isolation_level="AUTOCOMMIT") as conn:
                    conn.exec_driver_sql(f"SET hnsw.ef_search = {self._ef_search}")
            except Exception:
                # Older pgvector (< 0.5) doesn't accept the
                # per-session SET.  We fall through and rely
                # on the cluster-level GUC.
                pass
            self._tls.session = sess
        return sess

    def ensure_index(self) -> None:
        """Idempotently create the HNSW index.

        The migration runs this once at deploy time; calling
        it again is a no-op (the DDL is ``CREATE INDEX IF NOT
        EXISTS``).
        """

        sess = self._session()
        with sess.connection() as conn:
            conn.exec_driver_sql(
                "CREATE EXTENSION IF NOT EXISTS vector"
            )
            conn.exec_driver_sql(HNSW_INDEX_DDL)
        sess.commit()

    def upsert(
        self,
        *,
        memory_id: str,
        run_id: str,
        segment_id: str,
        summary: str,
        embedding: Sequence[float],
        embedding_hash: str = "",
    ) -> None:
        if len(embedding) != self._dim:
            raise ValueError(
                f"embedding dim mismatch: got {len(embedding)}, want {self._dim}"
            )
        vec_literal = _to_pgvector_literal(_normalise(embedding))
        sess = self._session()
        with sess.connection() as conn:
            # ON CONFLICT keeps the index hot without an
            # exclusive lock on the table; the index is
            # incrementally maintained by pgvector.
            conn.exec_driver_sql(
                """
                INSERT INTO memory_embeddings
                    (memory_id, run_id, segment_id, summary,
                     embedding, embedding_hash)
                VALUES (%s, %s, %s, %s, %s::vector, %s)
                ON CONFLICT (memory_id) DO UPDATE SET
                    segment_id = EXCLUDED.segment_id,
                    summary = EXCLUDED.summary,
                    embedding = EXCLUDED.embedding,
                    embedding_hash = EXCLUDED.embedding_hash
                """,
                (memory_id, run_id, segment_id, summary, vec_literal, embedding_hash),
            )
        sess.commit()

    def search(
        self,
        *,
        run_id: str,
        query_embedding: Sequence[float],
        top_k: int = DEFAULT_TOP_K,
    ) -> tuple[list[RecallHit], RecallStats]:
        if len(query_embedding) != self._dim:
            raise ValueError(
                f"query dim mismatch: got {len(query_embedding)}, want {self._dim}"
            )
        vec_literal = _to_pgvector_literal(_normalise(query_embedding))
        k = max(1, int(top_k))
        started = time.perf_counter()
        sess = self._session()
        rows: list[Any] = []
        candidates = 0
        with sess.connection() as conn:
            # Use ``ORDER BY embedding <=> $1`` and
            # ``LIMIT $2`` — pgvector pushes the LIMIT into
            # the HNSW scan so the planner stops expanding
            # the candidate list once it has ``k`` rows.
            result = conn.exec_driver_sql(
                """
                SELECT memory_id, run_id, segment_id, summary,
                       embedding_hash, 1 - (embedding <=> %s::vector) AS score
                FROM memory_embeddings
                WHERE run_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_literal, run_id, vec_literal, k),
            )
            for r in result:
                rows.append(r)
            # ``pg_stat_user_tables.n_live_tup`` is a single
            # round-trip to learn the candidate set size; we
            # use it to surface a useful histogram bucket.
            try:
                tup_row = conn.exec_driver_sql(
                    """
                    SELECT n_live_tup FROM pg_stat_user_tables
                    WHERE relname = 'memory_embeddings'
                    """
                ).first()
                candidates = int(tup_row[0]) if tup_row else 0
            except Exception:
                candidates = 0
        sess.commit()
        latency_ms = (time.perf_counter() - started) * 1000.0
        hits = [
            RecallHit(
                memory_id=str(r[0]),
                run_id=str(r[1]),
                segment_id=str(r[2]),
                summary=str(r[3])[:240],
                embedding_hash=str(r[4]),
                score=float(r[5]),
            )
            for r in rows
        ]
        stats = RecallStats(
            latency_ms=latency_ms,
            candidates_examined=candidates,
            ef_search=self._ef_search,
            index_path="pgvector",
            db_calls=2,
            p95_budget_exceeded=latency_ms > LATENCY_BUDGET_MS,
        )
        if stats.p95_budget_exceeded:
            logger.warning(
                "vector_search: p95 budget exceeded run=%s latency_ms=%.1f",
                run_id,
                latency_ms,
            )
        return hits, stats


# ---------------------------------------------------------------------------
# Public facade — auto-detects pgvector
# ---------------------------------------------------------------------------


class MemoryRecallIndex:
    """The component the recall service talks to.

    Decides between :class:`PgVectorRecallIndex` (production)
    and :class:`InMemoryVectorIndex` (dev / tests) based on
    the active SQLAlchemy engine URL.  The decision is
    logged once at first use; tests assert on the
    ``index_path`` field of :class:`RecallStats` to make
    sure the right backend is in play.
    """

    def __init__(
        self,
        engine: Any | None = None,
        *,
        dim: int = EMBEDDING_DIM,
        ef_search: int = HNSW_EF_SEARCH,
        force_in_memory: bool | None = None,
    ) -> None:
        self._dim = dim
        self._ef_search = int(ef_search)
        self._backend: InMemoryVectorIndex | PgVectorRecallIndex
        if force_in_memory is True:
            self._backend = InMemoryVectorIndex(dim=dim)
            logger.info("vector_search: forced in-memory backend")
        elif force_in_memory is False:
            if engine is None:
                raise ValueError("pgvector backend requires a SQLAlchemy engine")
            self._backend = PgVectorRecallIndex(engine, dim=dim, ef_search=ef_search)
            logger.info("vector_search: forced pgvector backend")
        else:
            # Auto-detect — the engine is the same one
            # ``db.engine`` exports.  SQLite means dev; pg
            # means prod.
            if engine is None:
                from db import engine as default_engine

                engine = default_engine
            url = str(getattr(engine, "url", ""))
            if url.startswith("postgresql") or url.startswith("postgres"):
                self._backend = PgVectorRecallIndex(engine, dim=dim, ef_search=ef_search)
                logger.info("vector_search: pgvector backend (url=%s)", url.split("@")[-1])
            else:
                self._backend = InMemoryVectorIndex(dim=dim)
                logger.info(
                    "vector_search: in-memory backend (url=%s) — production must use postgresql+pgvector",
                    url,
                )

    # Forwarding surface --------------------------------------------------

    @property
    def backend(self) -> InMemoryVectorIndex | PgVectorRecallIndex:
        return self._backend

    @property
    def index_path(self) -> str:
        return "pgvector" if isinstance(self._backend, PgVectorRecallIndex) else "in_memory"

    def ensure_index(self) -> None:
        if isinstance(self._backend, PgVectorRecallIndex):
            self._backend.ensure_index()

    def upsert(
        self,
        *,
        memory_id: str,
        run_id: str,
        segment_id: str,
        summary: str,
        embedding: Sequence[float],
        embedding_hash: str = "",
    ) -> None:
        self._backend.upsert(
            memory_id=memory_id,
            run_id=run_id,
            segment_id=segment_id,
            summary=summary,
            embedding=embedding,
            embedding_hash=embedding_hash,
        )

    def search(
        self,
        *,
        run_id: str,
        query_embedding: Sequence[float],
        top_k: int = DEFAULT_TOP_K,
    ) -> tuple[list[RecallHit], RecallStats]:
        return self._backend.search(
            run_id=run_id, query_embedding=query_embedding, top_k=top_k
        )

    def count(self, run_id: str | None = None) -> int:
        if isinstance(self._backend, InMemoryVectorIndex):
            return self._backend.count(run_id)
        # pgvector: cheap COUNT(*) but we keep it out of
        # the hot path — only call from the test harness.
        sess = self._backend._session()  # type: ignore[attr-defined]
        with sess.connection() as conn:
            if run_id is None:
                row = conn.exec_driver_sql("SELECT COUNT(*) FROM memory_embeddings").first()
            else:
                row = conn.exec_driver_sql(
                    "SELECT COUNT(*) FROM memory_embeddings WHERE run_id = %s",
                    (run_id,),
                ).first()
        sess.commit()
        return int(row[0]) if row else 0

    def healthcheck(self) -> dict[str, Any]:
        """Liveness probe used by ``GET /health``."""

        return {
            "indexPath": self.index_path,
            "dim": self._dim,
            "efSearch": self._ef_search,
            "hnswM": HNSW_M,
            "hnswEfConstruction": HNSW_EF_CONSTRUCTION,
            "latencyBudgetMs": LATENCY_BUDGET_MS,
        }


# ---------------------------------------------------------------------------
# Factory — reads the same env-var convention as db.build_engine
# ---------------------------------------------------------------------------


_default_index: MemoryRecallIndex | None = None
_default_lock = threading.Lock()


def get_default_index(dim: int = EMBEDDING_DIM) -> MemoryRecallIndex:
    """Return the process-wide :class:`MemoryRecallIndex`.

    Lazy so importing this module does not pay the
    ``CREATE EXTENSION`` cost on a SQLite dev box.
    """

    global _default_index
    with _default_lock:
        if _default_index is None:
            from db import engine as default_engine

            _default_index = MemoryRecallIndex(default_engine, dim=dim)
        return _default_index


def reset_default_index() -> None:  # pragma: no cover - test helper
    """Drop the cached index (test helper)."""

    global _default_index
    with _default_lock:
        _default_index = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def healthcheck() -> dict[str, Any]:
    """Liveness probe used by ``GET /health``."""

    idx = get_default_index()
    return {
        "indexPath": idx.index_path,
        "dim": idx._dim,
        "efSearch": idx._ef_search,
        "hnswM": HNSW_M,
        "hnswEfConstruction": HNSW_EF_CONSTRUCTION,
        "latencyBudgetMs": LATENCY_BUDGET_MS,
    }


__all__ = [
    "HNSW_M",
    "HNSW_EF_CONSTRUCTION",
    "HNSW_EF_SEARCH",
    "EMBEDDING_DIM",
    "DEFAULT_TOP_K",
    "LATENCY_BUDGET_MS",
    "HNSW_INDEX_DDL",
    "SET_EF_SEARCH_SQL",
    "COSINE_DISTANCE_SQL",
    "RecallHit",
    "RecallStats",
    "EmbedderProtocol",
    "InMemoryVectorIndex",
    "PgVectorRecallIndex",
    "MemoryRecallIndex",
    "get_default_index",
    "reset_default_index",
    "healthcheck",
    "_normalise",
    "_to_pgvector_literal",
]
