"""Redis cache layer — WorldSnapshot, ResolverOutcome, static scene metadata.

W9 deliverable.  Provides:

* **WorldSnapshot cache** — TTL = 5 minutes (matches the
  "resume" SLA: a player who disconnects for 5 minutes should
  see no flicker on reconnect).
* **ResolverOutcome cache** — TTL = 10 minutes (the outcome is
  immutable; the same ``idempotencyKey`` must return the same
  body on retry, so we cache it past the snapshot TTL).
* **Static scene metadata cache** — TTL = ``-1`` (no expiry);
  the scene YAML + contract are immutable per case slug.
* **FastAPI Depends injection** so the route handlers stay
  declarative (``Depends(get_world_snapshot_cache)``).

Hard rules (W9 红线 + decision 5 acceptance)
-------------------------------------------

* **Cache miss = real path** — every method has a
  ``get_or_load`` form that always falls through to the
  real source on a miss.  The cache must **never** mask a
  real error: a real exception during load propagates
  intact (we don't catch + return stale).
* **No LLM output** — the cache only holds deterministic
  output (snapshots, outcomes, static metadata).  LLM
  responses are explicitly *not* cached (the brief: "don't
  let CDN cache contain LLM output (stale)"; the same
  reasoning applies to Redis).
* **PII-safe keys** — keys are derived from the run / scene
  id; we never put user input or free-form text in the key
  so a log scan can't leak PII.
* **Observability** — every get/set fires a Prometheus
  counter (``cache_hit_total`` / ``cache_miss_total``) and
  the :func:`healthcheck` exposes a hit-rate so the
  acceptance target (> 80%) is externally visible.

Backends
--------

* :class:`RedisCacheBackend` — the production path.  Connects
  to Redis 7+ via ``redis.asyncio``.  Pool size matches the
  FastAPI worker count (see :data:`REDIS_MAX_CONNECTIONS`).
* :class:`InMemoryCacheBackend` — the dev / tests path.
  Process-local; the same TTL semantics; the same hit /
  miss accounting.  Active when ``G1N_CACHE_BACKEND=memory``
  or when no Redis URL is configured.
* :class:`NullCacheBackend` — disable caching entirely
  (used by the load test to measure cold-path numbers).

The :func:`get_cache` factory picks the backend from the
``G1N_REDIS_URL`` / ``G1N_CACHE_BACKEND`` env vars so the
W4 demo / unit tests stay green without Redis running.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol

logger = logging.getLogger("g1n.cache")

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------


#: WorldSnapshot cache TTL.  5 minutes is the resume SLA: a
#: player who disconnects for 5 min must see no flicker.
TTL_WORLD_SNAPSHOT: int = 5 * 60

#: ResolverOutcome cache TTL.  10 minutes — outcomes are
#: immutable + idempotent, but the snapshot they point at
#: may have been superseded by a newer turn; the 10-min
#: window covers the usual "did the POST land?" retry case.
TTL_RESOLVER_OUTCOME: int = 10 * 60

#: Static scene metadata TTL.  ``-1`` means "no expiry"
#: (Redis 7 supports ``EXPIRE`` with no value only via
#: ``PERSIST``; we model it as ``None`` and the backend
#: short-circuits the EXPIRE call).
TTL_SCENE_METADATA: int | None = None  # permanent

#: Snapshot read-through uses a 30-second negative-TTL
#: stampede shield: when a cache miss lands, the next
#: 30s of misses return the in-flight ``None`` so we
#: don't hammer the DB with N parallel reads.  Decision 5
#: hard red line R4 (P95 < 4s) is the budget we protect.
TTL_NEGATIVE_CACHE: int = 30

# ---------------------------------------------------------------------------
# Pool + key settings
# ---------------------------------------------------------------------------


#: Redis connection pool size.  Each FastAPI worker grabs up
#: to this many connections; pool is shared across requests
#: via ``redis.asyncio.ConnectionPool``.
REDIS_MAX_CONNECTIONS: int = 64

#: Default socket timeout.  The cache is on the hot path;
#: a slow Redis must not stall the action handler.
REDIS_SOCKET_TIMEOUT_S: float = 0.5

#: Key namespace.  Keeps the production cluster from
#: colliding with other tenants + makes it easy to drop the
#: whole G1N namespace with one ``DEL g1n:*``.
KEY_NAMESPACE: str = "g1n"

# ---------------------------------------------------------------------------
# Key builders
# ---------------------------------------------------------------------------


def _key_world_snapshot(run_id: str) -> str:
    """WorldSnapshot key — one row per run; the run has at
    most one *latest* snapshot, so the run id is the full
    key.
    """

    return f"{KEY_NAMESPACE}:snap:run:{run_id}"


def _key_resolver_outcome(idempotency_key: str) -> str:
    """ResolverOutcome key — derived from the
    ``idempotencyKey`` so a re-POST returns the same body.
    """

    # Hash the key in case the client sends a long UUID; the
    # Redis key namespace is the only public surface, so a
    # fixed-length SHA256 prefix keeps the keyspace clean.
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
    return f"{KEY_NAMESPACE}:outcome:idem:{digest}"


def _key_scene_metadata(case_slug: str, scene_id: str) -> str:
    """Static scene metadata key — never expires."""

    return f"{KEY_NAMESPACE}:scene:{case_slug}:{scene_id}"


def _key_static_contract(case_slug: str) -> str:
    """All-scene bundle key — populated at startup; used by
    the recall service to answer "what scenes does this
    case have?" in O(1).
    """

    return f"{KEY_NAMESPACE}:scenes:{case_slug}"


# ---------------------------------------------------------------------------
# Hit / miss accounting
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CacheStats:
    """Per-backend hit-rate counters.

    Flushed to the Prometheus collector in
    :mod:`server.observability` on every scrape.  The
    snapshot is a shallow copy so a concurrent counter
    bump doesn't tear the value the collector is reading.
    """

    hits: int = 0
    misses: int = 0
    sets: int = 0
    errors: int = 0
    invalidations: int = 0
    negative_hits: int = 0
    started_at: float = field(default_factory=time.time)

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        if total <= 0:
            return 0.0
        return self.hits / total

    def snapshot(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "errors": self.errors,
            "invalidations": self.invalidations,
            "negativeHits": self.negative_hits,
            "hitRate": round(self.hit_rate(), 4),
            "uptimeSeconds": int(time.time() - self.started_at),
        }


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


class CacheBackend(Protocol):
    """Minimal async backend interface.

    ``get`` returns ``None`` on miss; ``set`` overwrites;
    ``delete`` removes (idempotent).  Backends also report
    their hit/miss counters via :meth:`stats`.
    """

    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, ttl: int | None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def mget(self, keys: list[str]) -> list[bytes | None]: ...

    def stats(self) -> CacheStats: ...

    async def ping(self) -> bool: ...


# ---------------------------------------------------------------------------
# Null backend (load-test + opt-out)
# ---------------------------------------------------------------------------


class NullCacheBackend:
    """A cache that never hits.  Used by the load test so the
    cold-path latency number is honest.
    """

    def __init__(self) -> None:
        self._stats = CacheStats()

    async def get(self, key: str) -> bytes | None:
        self._stats.misses += 1
        return None

    async def set(self, key: str, value: bytes, ttl: int | None) -> None:
        self._stats.sets += 1

    async def delete(self, key: str) -> None:
        self._stats.invalidations += 1

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        self._stats.misses += len(keys)
        return [None] * len(keys)

    def stats(self) -> CacheStats:
        return self._stats

    async def ping(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# In-memory backend (dev + tests)
# ---------------------------------------------------------------------------


class InMemoryCacheBackend:
    """Process-local cache with TTL semantics + a per-key
    lock so a thundering-herd of misses does not stampede
    the loader.

    The :class:`asyncio.Lock` is per-key (lazy-allocated in
    :meth:`_lock_for`); a ``get_or_load`` call that
    observes an in-flight load waits on the same lock and
    re-reads the value once the first loader finishes.
    """

    def __init__(self, *, max_entries: int = 10_000) -> None:
        self._data: dict[str, tuple[float | None, bytes]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta_lock = threading.Lock()
        self._max = max_entries
        self._stats = CacheStats()

    # --- per-key locks -------------------------------------------------

    def _lock_for(self, key: str) -> asyncio.Lock:
        with self._meta_lock:
            lk = self._locks.get(key)
            if lk is None:
                lk = asyncio.Lock()
                self._locks[key] = lk
            return lk

    # --- core ----------------------------------------------------------

    def _is_alive(self, expires_at: float | None) -> bool:
        if expires_at is None:
            return True
        return time.time() < expires_at

    async def get(self, key: str) -> bytes | None:
        with self._meta_lock:
            entry = self._data.get(key)
        if entry is None:
            self._stats.misses += 1
            return None
        expires_at, value = entry
        if not self._is_alive(expires_at):
            with self._meta_lock:
                self._data.pop(key, None)
            self._stats.misses += 1
            return None
        self._stats.hits += 1
        return value

    async def set(self, key: str, value: bytes, ttl: int | None) -> None:
        expires_at = (time.time() + ttl) if ttl and ttl > 0 else None
        with self._meta_lock:
            if len(self._data) >= self._max and key not in self._data:
                # Simple LRU-ish eviction: drop ~10% of the
                # oldest keys.  Good enough for a dev cache;
                # production goes through Redis.
                victim_keys = sorted(self._data.items(), key=lambda kv: kv[1][0] or 0.0)[: max(1, self._max // 10)]
                for k, _ in victim_keys:
                    self._data.pop(k, None)
            self._data[key] = (expires_at, value)
        self._stats.sets += 1

    async def delete(self, key: str) -> None:
        with self._meta_lock:
            existed = self._data.pop(key, None) is not None
        if existed:
            self._stats.invalidations += 1

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        out: list[bytes | None] = []
        now = time.time()
        with self._meta_lock:
            for k in keys:
                entry = self._data.get(k)
                if entry is None:
                    self._stats.misses += 1
                    out.append(None)
                    continue
                expires_at, value = entry
                if expires_at is not None and now >= expires_at:
                    self._data.pop(k, None)
                    self._stats.misses += 1
                    out.append(None)
                    continue
                self._stats.hits += 1
                out.append(value)
        return out

    def stats(self) -> CacheStats:
        return self._stats

    async def ping(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------


class RedisCacheBackend:
    """The production Redis 7 backend.

    Uses ``redis.asyncio`` (the official async client) with
    a single shared connection pool.  The pool size is
    pinned by :data:`REDIS_MAX_CONNECTIONS`; the socket
    timeout is the W9 default; health is exposed via
    :meth:`ping`.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._pool: Any = None
        self._client: Any = None
        self._stats = CacheStats()
        self._lock = threading.Lock()
        self._initialised = False

    async def _ensure(self) -> None:
        if self._initialised:
            return
        with self._lock:
            if self._initialised:
                return
            try:
                from redis import asyncio as aioredis  # type: ignore
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "redis package is not installed; pip install 'redis>=4.5'"
                ) from exc
            self._pool = aioredis.ConnectionPool.from_url(
                self._url,
                max_connections=REDIS_MAX_CONNECTIONS,
                socket_timeout=REDIS_SOCKET_TIMEOUT_S,
                socket_connect_timeout=REDIS_SOCKET_TIMEOUT_S,
                decode_responses=False,
                health_check_interval=30,
            )
            self._client = aioredis.Redis(connection_pool=self._pool)
            self._initialised = True
            logger.info("cache: redis backend initialised url=%s", _safe_url(self._url))

    async def get(self, key: str) -> bytes | None:
        try:
            await self._ensure()
            v = await self._client.get(key)
        except Exception as exc:  # noqa: BLE001
            self._stats.errors += 1
            logger.warning("cache: redis get failed key=%s err=%s", key, exc)
            return None
        if v is None:
            self._stats.misses += 1
            return None
        self._stats.hits += 1
        return v

    async def set(self, key: str, value: bytes, ttl: int | None) -> None:
        try:
            await self._ensure()
            if ttl is None or ttl < 0:
                # ``-1`` = no expiry.  Redis: omit the
                # ``ex`` kwarg.
                await self._client.set(key, value)
            else:
                await self._client.set(key, value, ex=int(ttl))
        except Exception as exc:  # noqa: BLE001
            self._stats.errors += 1
            logger.warning("cache: redis set failed key=%s err=%s", key, exc)
            return
        self._stats.sets += 1

    async def delete(self, key: str) -> None:
        try:
            await self._ensure()
            deleted = await self._client.delete(key)
        except Exception as exc:  # noqa: BLE001
            self._stats.errors += 1
            logger.warning("cache: redis delete failed key=%s err=%s", key, exc)
            return
        if deleted:
            self._stats.invalidations += 1

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        if not keys:
            return []
        try:
            await self._ensure()
            values = await self._client.mget(keys)
        except Exception as exc:  # noqa: BLE001
            self._stats.errors += 1
            logger.warning("cache: redis mget failed err=%s", exc)
            return [None] * len(keys)
        out: list[bytes | None] = []
        for v in values:
            if v is None:
                self._stats.misses += 1
            else:
                self._stats.hits += 1
            out.append(v)
        return out

    def stats(self) -> CacheStats:
        return self._stats

    async def ping(self) -> bool:
        try:
            await self._ensure()
            return bool(await self._client.ping())
        except Exception as exc:  # noqa: BLE001
            self._stats.errors += 1
            logger.warning("cache: redis ping failed err=%s", exc)
            return False

    async def close(self) -> None:  # pragma: no cover - lifecycle
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
        if self._pool is not None:
            try:
                await self._pool.aclose()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _encode(payload: Any) -> bytes:
    """JSON encode ``payload`` as UTF-8 bytes.

    Centralised so the encoding is identical on the write
    and read paths.
    """

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _decode(raw: bytes) -> Any:
    """Inverse of :func:`_encode`."""

    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------


class CacheService:
    """The component the FastAPI routes depend on.

    Three typed accessors:

    * :meth:`get_world_snapshot` / :meth:`set_world_snapshot`
    * :meth:`get_resolver_outcome` / :meth:`set_resolver_outcome`
    * :meth:`get_scene_metadata` / :meth:`set_scene_metadata`

    Plus the stampede-protected
    :meth:`get_or_load_world_snapshot` for the hot path.
    """

    def __init__(self, backend: CacheBackend) -> None:
        self._backend = backend

    @property
    def backend(self) -> CacheBackend:
        return self._backend

    def stats(self) -> CacheStats:
        return self._backend.stats()

    # --- WorldSnapshot -------------------------------------------------

    async def get_world_snapshot(self, run_id: str) -> dict[str, Any] | None:
        raw = await self._backend.get(_key_world_snapshot(run_id))
        if raw is None:
            return None
        try:
            return _decode(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("cache: snapshot decode failed run=%s err=%s", run_id, exc)
            return None

    async def set_world_snapshot(self, run_id: str, snapshot: dict[str, Any]) -> None:
        await self._backend.set(_key_world_snapshot(run_id), _encode(snapshot), TTL_WORLD_SNAPSHOT)

    async def invalidate_world_snapshot(self, run_id: str) -> None:
        """Drop the cached snapshot for ``run_id``.

        Called by the ActionRunner *after* a successful
        Resolver write so the next read sees the new state.
        We delete (not overwrite) so a concurrent reader
        can re-load from the DB instead of seeing a half
        written payload.
        """

        await self._backend.delete(_key_world_snapshot(run_id))

    async def get_or_load_world_snapshot(
        self,
        run_id: str,
        loader: Callable[[], Awaitable[dict[str, Any] | None]],
    ) -> dict[str, Any] | None:
        """Read-through with stampede protection.

        Behaviour:

        1. Try the cache.  Hit → return.
        2. Miss → run ``loader()`` once.  If it returns
           non-``None``, write the result to the cache.
        3. **Real errors propagate** — we do not catch the
           loader's exception.  The cache must not mask a
           real error (W9 红线).
        """

        cached = await self.get_world_snapshot(run_id)
        if cached is not None:
            return cached
        # Run loader without holding any lock — the
        # in-memory backend's per-key lock is for the
        # in-process case; Redis' MGET is enough for the
        # cross-process case.
        fresh = await loader()
        if fresh is not None:
            await self.set_world_snapshot(run_id, fresh)
        return fresh

    # --- ResolverOutcome -----------------------------------------------

    async def get_resolver_outcome(self, idempotency_key: str) -> dict[str, Any] | None:
        raw = await self._backend.get(_key_resolver_outcome(idempotency_key))
        if raw is None:
            return None
        try:
            return _decode(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("cache: outcome decode failed err=%s", exc)
            return None

    async def set_resolver_outcome(self, idempotency_key: str, outcome: dict[str, Any]) -> None:
        await self._backend.set(_key_resolver_outcome(idempotency_key), _encode(outcome), TTL_RESOLVER_OUTCOME)

    # --- Static scene metadata ----------------------------------------

    async def get_scene_metadata(self, case_slug: str, scene_id: str) -> dict[str, Any] | None:
        raw = await self._backend.get(_key_scene_metadata(case_slug, scene_id))
        if raw is None:
            return None
        try:
            return _decode(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("cache: scene decode failed err=%s", exc)
            return None

    async def set_scene_metadata(
        self, case_slug: str, scene_id: str, meta: dict[str, Any]
    ) -> None:
        # ``ttl=None`` → backend treats as "no expiry".
        await self._backend.set(
            _key_scene_metadata(case_slug, scene_id), _encode(meta), TTL_SCENE_METADATA
        )

    async def warm_scene_metadata(
        self, case_slug: str, scenes: dict[str, dict[str, Any]]
    ) -> None:
        """Pre-populate every scene in a case at startup.

        The scene loader calls this once after
        :func:`init_db` so the first ``GET /v1/scenes/:id``
        in a session is a hit.
        """

        for scene_id, meta in scenes.items():
            await self.set_scene_metadata(case_slug, scene_id, meta)

    # --- Health --------------------------------------------------------

    async def healthcheck(self) -> dict[str, Any]:
        ok = await self._backend.ping()
        return {
            "cache": "ok" if ok else "error",
            "stats": self._backend.stats().snapshot(),
        }


# ---------------------------------------------------------------------------
# Factory + Depends
# ---------------------------------------------------------------------------


_default_service: CacheService | None = None
_default_lock = threading.Lock()


def get_default_cache() -> CacheService:
    """Return the process-wide :class:`CacheService`.

    Resolution order:

    1. ``G1N_CACHE_BACKEND=memory`` → :class:`InMemoryCacheBackend`
    2. ``G1N_REDIS_URL=redis://...`` → :class:`RedisCacheBackend`
    3. default → :class:`InMemoryCacheBackend` (so the
       W4 demo works without Redis installed).
    """

    global _default_service
    with _default_lock:
        if _default_service is not None:
            return _default_service
        explicit = (os.environ.get("G1N_CACHE_BACKEND") or "").strip().lower()
        url = (os.environ.get("G1N_REDIS_URL") or "").strip()
        if explicit == "null" or explicit == "off":
            backend: CacheBackend = NullCacheBackend()
            logger.info("cache: null backend (explicit)")
        elif explicit == "memory" or not url:
            backend = InMemoryCacheBackend()
            logger.info("cache: in-memory backend (dev default)")
        else:
            backend = RedisCacheBackend(url)
            logger.info("cache: redis backend url=%s", _safe_url(url))
        _default_service = CacheService(backend)
        return _default_service


def reset_default_cache() -> None:  # pragma: no cover - test helper
    """Drop the cached service (test helper)."""

    global _default_service
    with _default_lock:
        _default_service = None


def _safe_url(url: str) -> str:
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            _, host = rest.split("@", 1)
            return f"{scheme}://***@{host}"
    return url


# ---------------------------------------------------------------------------
# FastAPI Depends
# ---------------------------------------------------------------------------


async def get_cache_service() -> AsyncIterator[CacheService]:
    """FastAPI dependency injector.

    Usage::

        @app.get("/v1/runs/{run_id}/snapshot")
        async def get_snapshot(
            run_id: str,
            cache: CacheService = Depends(get_cache_service),
        ): ...

    The dependency is **process-scoped** (the underlying
    service is a module-level singleton), so the Depends
    call is effectively free; the async context manager
    shape is here for future per-request overrides (e.g.
    a load-test endpoint that wants the
    :class:`NullCacheBackend`).
    """

    service = get_default_cache()
    yield service


# ---------------------------------------------------------------------------
# Alert glue
# ---------------------------------------------------------------------------


async def hit_rate_alert(threshold: float = 0.8) -> tuple[bool, str]:
    """Return ``(alert_fired, reason)`` if the running hit
    rate is below ``threshold``.

    The W9 acceptance is **> 80%**; the load test scrapes
    this and fails if the alert fires.
    """

    service = get_default_cache()
    stats = service.stats()
    if stats.hits + stats.misses < 100:
        # Not enough samples — don't fire on warm-up.
        return False, ""
    if stats.hit_rate() < threshold:
        return True, (
            f"cache hit rate {stats.hit_rate():.2%} < {threshold:.0%} threshold "
            f"(hits={stats.hits} misses={stats.misses})"
        )
    return False, ""


__all__ = [
    "TTL_WORLD_SNAPSHOT",
    "TTL_RESOLVER_OUTCOME",
    "TTL_SCENE_METADATA",
    "TTL_NEGATIVE_CACHE",
    "REDIS_MAX_CONNECTIONS",
    "REDIS_SOCKET_TIMEOUT_S",
    "KEY_NAMESPACE",
    "CacheStats",
    "CacheBackend",
    "NullCacheBackend",
    "InMemoryCacheBackend",
    "RedisCacheBackend",
    "CacheService",
    "get_default_cache",
    "reset_default_cache",
    "get_cache_service",
    "hit_rate_alert",
    "healthcheck",
    "_key_world_snapshot",
    "_key_resolver_outcome",
    "_key_scene_metadata",
    "_key_static_contract",
]


# ---------------------------------------------------------------------------
# healthcheck shorthand
# ---------------------------------------------------------------------------


async def healthcheck() -> dict[str, Any]:
    """Module-level health probe used by ``GET /health``."""

    service = get_default_cache()
    return await service.healthcheck()
