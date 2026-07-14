"""W8-2 · BYOK (Bring Your Own Key) — 玩家自接 API key.

Why this module exists
----------------------

决策 4 商业化把 BYOK 定为 P1，但本次 W8-2 必须实现：理由是
W8-1 之后玩家只能跑 200 积分（= 20 主调用 / 10 局左右），而
真实玩家在跑通前两局后就会出现"token 焦虑"——BYOK 让愿意自己
掏钱跑更多局的玩家接入 OpenAI / DeepSeek / Qwen 的 API key。

What this module does
---------------------

* 玩家通过 :class:`BYOKKeyStore.register` 提交 API key
* 服务端用 Fernet (AES-128 CBC + HMAC-SHA256) 加密入库
  — 明文 key 永远不进日志，永远不返回给客户端
* 玩家 key 用于 :class:`BYOKProvider`（继承
  :class:`OpenAICompatibleProvider`，多接一个 ``api_key`` 参数）
* 服务端 key 池 vs 玩家 key 池自动 fallback：
  1. 玩家 key 可用且未超限 → 用玩家 key（BYOK 路径）
  2. 玩家 key 失败 / 限流 / 余额不足 → 降级到服务端 key 池
  3. 两边都失败 → 沿用 4 级降级链（L1 → L2 → L3 → L4）

Red lines (must not violate)
----------------------------

* ❌ BYOK key 明文存储 — Fernet 加密是默认 + 唯一路径
* ❌ BYOK key 写日志 — 唯一出现在日志里的是
   ``key_fingerprint`` (SHA-256 前 8 hex 字符)
* ❌ BYOK 玩家绕过决策 4 付费档位 — BYOK **不**给决策 4
   的"私人终章 / 双视角"等付费内容；它只解锁"更多 AI 调用"
* ❌ BYOK 玩家跳过 consume_credits 扣费 — BYOK 调用 **不**
   扣 entitlement 的 credits（玩家用自己 key 付费），但
   :class:`RunCostLedgerRow` 仍然累加 ``byok_calls`` 用于
   ops 监控 + decision 5 红线检查（不让玩家用自己 key 跑
   飞，绕开 R1 主调用 20 次硬红线）

Rate limiting
-------------

* 每用户 20 次/分钟（可调，通过 ``rate_limit_per_minute`` 字段）
* 连续 5 次失败 → status='disabled'，自动 fallback
* token bucket 在内存里维护（per-user-per-provider），刷新
  频率 60s
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from auth import require_user
from db import ByokKeyRow, SessionLocal

logger = logging.getLogger("g1n.byok")

# ---------------------------------------------------------------------------
# Encryption master key handling
# ---------------------------------------------------------------------------

_BYOK_KEY_ENV = "G1N_BYOK_ENCRYPTION_KEY"
_DEFAULT_BYOK_KEY: bytes | None = None
_f: Any = None  # the Fernet instance; lazy-initialised


def _load_fernet() -> Any:
    """Load (or generate) the Fernet master key.

    The key is symmetric — anyone with the env var can decrypt
    every BYOK key in the DB.  **Treat it as a root secret**.

    The env var must be a url-safe base64 32-byte key (the
    output of ``Fernet.generate_key()``).  For dev/test we
    generate an ephemeral key with a loud log warning.
    """

    global _f, _DEFAULT_BYOK_KEY
    if _f is not None:
        return _f
    try:
        from cryptography.fernet import Fernet, InvalidToken  # type: ignore
    except ImportError as exc:  # pragma: no cover - cryptography is in W4 deps
        raise RuntimeError(
            "W8-2 requires the `cryptography` package; install it with "
            "`pip install cryptography`"
        ) from exc
    key_b64 = os.environ.get(_BYOK_KEY_ENV, "")
    if not key_b64:
        _DEFAULT_BYOK_KEY = Fernet.generate_key()
        key_b64 = _DEFAULT_BYOK_KEY.decode("ascii")
        logger.warning(
            "g1n.byok: %s not set — generated ephemeral Fernet key. "
            "BYOK keys encrypted with this key will be UNREADABLE after "
            "process restart. Set the env var in any non-dev deployment.",
            _BYOK_KEY_ENV,
        )
    else:
        _DEFAULT_BYOK_KEY = key_b64.encode("ascii")
    _f = Fernet(_DEFAULT_BYOK_KEY)
    # Stash on the module so tests can introspect.
    return _f


def set_byok_fernet_for_tests(key_b64: str) -> None:
    """Test hook — inject a known Fernet key so encrypt / decrypt round-trips."""

    global _f, _DEFAULT_BYOK_KEY
    os.environ[_BYOK_KEY_ENV] = key_b64
    _DEFAULT_BYOK_KEY = key_b64.encode("ascii")
    _f = None
    _load_fernet()


# ---------------------------------------------------------------------------
# Fingerprint + encryption helpers
# ---------------------------------------------------------------------------


def fingerprint_key(plaintext: str) -> str:
    """Return the first 16 hex chars of SHA-256(plaintext).

    The fingerprint is **safe to log** and **safe to expose**
    to the client (so the player can tell which key is
    which).  It is **not** a secret — the full SHA-256 is
    64 hex chars; we truncate to 16 to keep the UI clean.
    """

    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:16]


def encrypt_key(plaintext: str) -> str:
    """Encrypt the plaintext with Fernet.  Returns a base64 string."""

    f = _load_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_key(ciphertext: str) -> str:
    """Decrypt a Fernet ciphertext.  Raises HTTPException(500) on tamper."""

    f = _load_fernet()
    try:
        from cryptography.fernet import InvalidToken  # type: ignore
    except ImportError:  # pragma: no cover
        InvalidToken = Exception
    try:
        return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="BYOK key ciphertext is corrupted or the master key has rotated",
        ) from exc


# ---------------------------------------------------------------------------
# Supported provider catalogue
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class BYOKProviderSpec:
    """One supported provider in the BYOK catalogue."""

    name: str
    label: str
    base_url: str
    default_model: str
    api_key_env: str
    docs_url: str


BYOK_PROVIDER_CATALOG: dict[str, BYOKProviderSpec] = {
    "openai_compatible": BYOKProviderSpec(
        name="openai_compatible",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
        docs_url="https://platform.openai.com/api-keys",
    ),
    "deepseek": BYOKProviderSpec(
        name="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        docs_url="https://platform.deepseek.com/api_keys",
    ),
    "qwen": BYOKProviderSpec(
        name="qwen",
        label="通义千问 (Qwen)",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        api_key_env="QWEN_API_KEY",
        docs_url="https://dashscope.console.aliyun.com/apiKey",
    ),
}


def _validate_provider_name(name: str) -> BYOKProviderSpec:
    spec = BYOK_PROVIDER_CATALOG.get(name)
    if spec is None:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported BYOK provider: {name!r}; "
                   f"supported: {sorted(BYOK_PROVIDER_CATALOG.keys())}",
        )
    return spec


# ---------------------------------------------------------------------------
# Token-bucket rate limiter
# ---------------------------------------------------------------------------


@dataclass
class _TokenBucket:
    """Per-(user, provider) token bucket; refills at ``rate_per_minute``/60 per second."""

    rate_per_minute: int
    capacity: int
    tokens: float = field(default=0.0)
    last_refill: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.rate_per_minute <= 0:
            self.rate_per_minute = 1
        # Capacity = 2x the per-minute rate so a burst of
        # "rapid clicks" still gets through, but the long-
        # run rate is enforced.
        self.capacity = max(1, self.rate_per_minute * 2)
        self.tokens = float(self.capacity)

    def try_acquire(self, *, n: int = 1) -> bool:
        """Try to take ``n`` tokens.  Returns True on success."""

        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            refill = (elapsed / 60.0) * self.rate_per_minute
            self.tokens = min(self.capacity, self.tokens + refill)
            self.last_refill = now
            if self.tokens >= n:
                self.tokens -= n
                return True
            return False

    def current_tokens(self) -> float:
        """Read-only inspection (for ops endpoints)."""

        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            refill = (elapsed / 60.0) * self.rate_per_minute
            return min(self.capacity, self.tokens + refill)


# ---------------------------------------------------------------------------
# BYOK Provider — drop-in replacement for OpenAICompatibleProvider
# ---------------------------------------------------------------------------


class BYOKProvider:
    """A provider that talks to the OpenAI wire format using
    a *player-supplied* API key.

    Constructed by :class:`BYOKManager` per call (the key
    is decrypted on demand and never cached in plaintext
    across the boundary).  The instance is short-lived —
    one LLM call per instance — so the plaintext key lives
    in memory only for the duration of the call.
    """

    name: str = "byok"

    def __init__(
        self,
        *,
        provider_spec: BYOKProviderSpec,
        api_key: str,
        key_id: str,
        key_fingerprint: str,
        model: str | None = None,
        base_url: str | None = None,
        timeout_ms: int = 8000,
    ) -> None:
        self._spec = provider_spec
        self._api_key = api_key
        self._key_id = key_id
        self._key_fingerprint = key_fingerprint
        self._model = model or provider_spec.default_model
        self._base_url = base_url or provider_spec.base_url
        self._timeout_ms = timeout_ms
        # Lazy import to keep the module import-cheap.
        from model.providers.openai_compatible import OpenAICompatibleProvider

        self._delegate = OpenAICompatibleProvider(
            base_url=self._base_url,
            api_key=self._api_key,
            name=f"byok_{provider_spec.name}",
            timeout_ms=timeout_ms,
        )

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def key_fingerprint(self) -> str:
        return self._key_fingerprint

    def complete(self, **kwargs: Any) -> Any:
        """Forward to the underlying :class:`OpenAICompatibleProvider`."""

        return self._delegate.complete(**kwargs)

    @property
    def spec(self) -> BYOKProviderSpec:
        return self._spec

    @property
    def model(self) -> str:
        return self._model

    def clear(self) -> None:
        """Best-effort wipe of the in-memory plaintext key.

        CPython's str is immutable so this can only overwrite
        the reference; the GC will eventually collect the
        underlying string.  The intent is to limit the window
        in which the plaintext key is reachable through the
        BYOKProvider instance.
        """

        self._api_key = ""  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class InsufficientCreditsError(Exception):
    """Raised when the player's balance is 0 and no BYOK key is available.

    The :class:`server.balance_monitor` catches this and
    routes the request into the L3 degradation chain (writer
    mainline) per decision 5.
    """


@dataclass(slots=True)
class BYOKResolveResult:
    """The output of :meth:`BYOKKeyStore.resolve`."""

    mode: str  # "byok" | "server" | "none"
    provider: Any  # the LLM provider instance (None when mode == "none")
    key_fingerprint: str | None  # populated iff mode == "byok"
    key_id: str | None  # populated iff mode == "byok"
    reason: str  # human-readable explanation


class BYOKKeyStore:
    """The single source of truth for player BYOK keys."""

    def __init__(self) -> None:
        # Pre-warm the Fernet so the very first request
        # doesn't pay the import / key-derive cost.
        _load_fernet()
        # Per-(user, provider) rate limiters, in-memory.
        self._buckets: dict[tuple[str, str], _TokenBucket] = {}
        self._buckets_lock = threading.Lock()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(
        self,
        *,
        user_id: str,
        provider_name: str,
        api_key: str,
        label: str = "",
        base_url: str | None = None,
        model: str | None = None,
        rate_limit_per_minute: int = 20,
    ) -> dict[str, Any]:
        spec = _validate_provider_name(provider_name)
        api_key = (api_key or "").strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="api_key is empty")
        if len(api_key) < 8:
            raise HTTPException(status_code=400, detail="api_key is too short")
        fp = fingerprint_key(api_key)
        cipher = encrypt_key(api_key)
        now = datetime.now(timezone.utc)
        with SessionLocal() as s:
            existing = s.execute(
                select(ByokKeyRow).where(
                    ByokKeyRow.user_id == user_id,
                    ByokKeyRow.provider == provider_name,
                    ByokKeyRow.label == label,
                )
            ).scalar_one_or_none()
            if existing is not None:
                # Update the key (rotate) — keep id stable.
                existing.encrypted_key = cipher
                existing.key_fingerprint = fp
                existing.base_url = base_url
                existing.model = model
                existing.status = "active"
                existing.rate_limit_per_minute = int(rate_limit_per_minute)
                existing.consecutive_failures = 0
                existing.last_error = None
                existing.last_used_at = None
                existing.revoked_at = None
                s.commit()
                s.refresh(existing)
                logger.info(
                    "g1n.byok: rotated key user=%s provider=%s label=%s fp=%s",
                    user_id, provider_name, label, fp,
                )
                return existing.to_dict()
            row = ByokKeyRow(
                id=f"byok_{uuid.uuid4().hex[:16]}",
                user_id=user_id,
                provider=provider_name,
                label=label,
                key_fingerprint=fp,
                encrypted_key=cipher,
                base_url=base_url,
                model=model,
                status="active",
                rate_limit_per_minute=int(rate_limit_per_minute),
                created_at=now,
                meta_json=json.dumps({"specLabel": spec.label}, ensure_ascii=False),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            logger.info(
                "g1n.byok: registered key user=%s provider=%s label=%s fp=%s",
                user_id, provider_name, label, fp,
            )
            return row.to_dict()

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as s:
            rows = s.execute(
                select(ByokKeyRow)
                .where(ByokKeyRow.user_id == user_id)
                .order_by(ByokKeyRow.created_at.desc())
            ).scalars().all()
            return [r.to_dict() for r in rows]

    def get_one(self, *, user_id: str, key_id: str) -> dict[str, Any] | None:
        with SessionLocal() as s:
            row = s.execute(
                select(ByokKeyRow).where(
                    ByokKeyRow.user_id == user_id,
                    ByokKeyRow.id == key_id,
                )
            ).scalar_one_or_none()
            return row.to_dict() if row else None

    def revoke(self, *, user_id: str, key_id: str) -> dict[str, Any] | None:
        with SessionLocal() as s:
            row = s.execute(
                select(ByokKeyRow).where(
                    ByokKeyRow.user_id == user_id,
                    ByokKeyRow.id == key_id,
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = "revoked"
            row.revoked_at = datetime.now(timezone.utc)
            s.commit()
            s.refresh(row)
            logger.info(
                "g1n.byok: revoked key user=%s key_id=%s fp=%s",
                user_id, key_id, row.key_fingerprint,
            )
            return row.to_dict()

    def delete_hard(self, *, user_id: str, key_id: str) -> bool:
        """Hard-delete a key (GDPR-style; mostly for tests)."""

        with SessionLocal() as s:
            row = s.execute(
                select(ByokKeyRow).where(
                    ByokKeyRow.user_id == user_id,
                    ByokKeyRow.id == key_id,
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            s.delete(row)
            s.commit()
            return True

    # ------------------------------------------------------------------
    # Provider resolution (the heart of the fallback policy)
    # ------------------------------------------------------------------

    def resolve(
        self,
        *,
        user_id: str,
        preferred_provider: str | None = None,
    ) -> BYOKResolveResult:
        """Pick the provider to use for the next LLM call.

        Resolution order:

        1. **BYOK preferred** — if the player has an active
           key for ``preferred_provider`` (or any provider if
           ``preferred_provider`` is None) and the rate
           limiter grants a token, build a :class:`BYOKProvider`
           and return it.
        2. **Server key pool** — fall back to the
           env-var-loaded provider from
           :class:`server.llm_runtime`.  This is whatever
           the operator configured (OpenAI / DeepSeek / Qwen /
           mock).
        3. **None** — the operator is running in mock mode
           AND the player has no BYOK key.  The LLM runtime
           short-circuits to the mock provider.
        """

        # Pre-fetch all active keys for this user.
        with SessionLocal() as s:
            rows = s.execute(
                select(ByokKeyRow).where(
                    ByokKeyRow.user_id == user_id,
                    ByokKeyRow.status == "active",
                )
            ).scalars().all()
            active_keys = [r for r in rows]
        if not active_keys:
            return BYOKResolveResult(
                mode="none",
                provider=None,
                key_fingerprint=None,
                key_id=None,
                reason="no active BYOK key for user",
            )
        # Honour the preferred provider when available;
        # otherwise iterate in registration order (most
        # recent first).
        if preferred_provider:
            active_keys = sorted(
                active_keys,
                key=lambda r: (0 if r.provider == preferred_provider else 1, r.created_at),
            )
        for row in active_keys:
            if row.consecutive_failures >= 5:
                # Auto-disabled after a streak of failures;
                # the resolver will try the next provider.
                continue
            bucket = self._get_bucket(user_id, row.provider, row.rate_limit_per_minute)
            if not bucket.try_acquire():
                continue
            try:
                plaintext = decrypt_key(row.encrypted_key)
            except HTTPException as exc:
                logger.warning(
                    "g1n.byok: decrypt failed user=%s key_id=%s fp=%s: %s",
                    user_id, row.id, row.key_fingerprint, exc.detail,
                )
                self._mark_failure(row.id, "decrypt_failed")
                continue
            spec = BYOK_PROVIDER_CATALOG[row.provider]
            provider = BYOKProvider(
                provider_spec=spec,
                api_key=plaintext,
                key_id=row.id,
                key_fingerprint=row.key_fingerprint,
                model=row.model,
                base_url=row.base_url,
            )
            return BYOKResolveResult(
                mode="byok",
                provider=provider,
                key_fingerprint=row.key_fingerprint,
                key_id=row.id,
                reason=f"byok provider={row.provider} fp={row.key_fingerprint}",
            )
        return BYOKResolveResult(
            mode="none",
            provider=None,
            key_fingerprint=None,
            key_id=None,
            reason="all BYOK keys disabled or rate-limited",
        )

    def mark_success(self, *, key_id: str) -> None:
        with SessionLocal() as s:
            row = s.get(ByokKeyRow, key_id)
            if row is None:
                return
            row.consecutive_failures = 0
            row.last_error = None
            row.last_used_at = datetime.now(timezone.utc)
            s.commit()

    def mark_failure(self, *, key_id: str, error: str) -> None:
        self._mark_failure(key_id, error)

    def _mark_failure(self, key_id: str, error: str) -> None:
        with SessionLocal() as s:
            row = s.get(ByokKeyRow, key_id)
            if row is None:
                return
            row.consecutive_failures = int(row.consecutive_failures) + 1
            row.last_error = error[:256]
            row.last_used_at = datetime.now(timezone.utc)
            if row.consecutive_failures >= 5:
                row.status = "disabled"
                logger.warning(
                    "g1n.byok: auto-disabled key_id=%s after %d failures",
                    key_id, row.consecutive_failures,
                )
            s.commit()

    def _get_bucket(
        self, user_id: str, provider_name: str, rate_per_minute: int
    ) -> _TokenBucket:
        key = (user_id, provider_name)
        with self._buckets_lock:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.rate_per_minute != rate_per_minute:
                bucket = _TokenBucket(rate_per_minute=rate_per_minute, capacity=rate_per_minute * 2)
                self._buckets[key] = bucket
            return bucket

    def usage(self, user_id: str) -> dict[str, Any]:
        """Per-provider usage for the ops endpoint."""

        with SessionLocal() as s:
            rows = s.execute(
                select(ByokKeyRow).where(ByokKeyRow.user_id == user_id)
            ).scalars().all()
            out: dict[str, Any] = {"providers": {}, "rateLimitTokens": {}}
            for r in rows:
                bucket = self._buckets.get((user_id, r.provider))
                out["providers"][r.provider] = {
                    "status": r.status,
                    "keyFingerprint": r.key_fingerprint,
                    "consecutiveFailures": int(r.consecutive_failures),
                    "rateLimitPerMinute": int(r.rate_limit_per_minute),
                    "lastUsedAt": r.last_used_at.isoformat() if r.last_used_at else None,
                    "lastError": r.last_error,
                }
                if bucket is not None:
                    out["rateLimitTokens"][r.provider] = round(bucket.current_tokens(), 2)
            return out


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_default_store: BYOKKeyStore | None = None


def get_default_byok_store() -> BYOKKeyStore:
    global _default_store
    if _default_store is None:
        _default_store = BYOKKeyStore()
    return _default_store


def reset_default_byok_store() -> None:
    global _default_store
    _default_store = None


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


class RegisterKeyRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    apiKey: str = Field(min_length=8, max_length=512)
    label: str = Field(default="default", max_length=64)
    baseUrl: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=64)
    rateLimitPerMinute: int = Field(default=20, ge=1, le=600)

    @field_validator("provider")
    @classmethod
    def _check_provider(cls, v: str) -> str:
        if v not in BYOK_PROVIDER_CATALOG:
            raise ValueError(
                f"unsupported provider: {v!r}; supported: "
                f"{sorted(BYOK_PROVIDER_CATALOG.keys())}"
            )
        return v


class TestKeyRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    apiKey: str = Field(min_length=8, max_length=512)
    baseUrl: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=64)


def build_byok_router() -> APIRouter:
    router = APIRouter(prefix="/v1/byok", tags=["byok"])
    store = get_default_byok_store

    @router.get("/providers")
    async def list_providers() -> dict[str, Any]:
        """Catalogue of supported BYOK providers (public info)."""

        return {
            "ok": True,
            "providers": [
                {
                    "name": s.name,
                    "label": s.label,
                    "defaultModel": s.default_model,
                    "docsUrl": s.docs_url,
                    "supportsCustomBaseUrl": True,
                    "supportsCustomModel": True,
                }
                for s in BYOK_PROVIDER_CATALOG.values()
            ],
        }

    @router.post("/keys")
    async def register_key(
        req: RegisterKeyRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        # The demo-user cannot register a real BYOK key
        # (no real auth).  The legacy path stays for tests.
        if user.get("id") == "demo-user":
            raise HTTPException(
                status_code=403,
                detail="BYOK requires a registered account (demo-user is anonymous)",
            )
        key = store().register(
            user_id=user["id"],
            provider_name=req.provider,
            api_key=req.apiKey,
            label=req.label,
            base_url=req.baseUrl,
            model=req.model,
            rate_limit_per_minute=req.rateLimitPerMinute,
        )
        return {"ok": True, "key": key}

    @router.get("/keys")
    async def list_keys(
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        keys = store().list_for_user(user["id"])
        return {"ok": True, "keys": keys, "count": len(keys)}

    @router.delete("/keys/{key_id}")
    async def revoke_key(
        key_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        revoked = store().revoke(user_id=user["id"], key_id=key_id)
        if revoked is None:
            raise HTTPException(status_code=404, detail="key not found")
        return {"ok": True, "key": revoked}

    @router.post("/keys/{key_id}/test")
    async def test_key(
        key_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """Send a tiny ``models.list``-style probe to verify the key is live.

        Uses the OpenAI-compatible ``/models`` endpoint and
        returns 200 on any 2xx.  We never persist the
        response body — only the ok / error status.
        """

        from model.providers.openai_compatible import OpenAICompatibleProvider

        key_dict = store().get_one(user_id=user["id"], key_id=key_id)
        if key_dict is None:
            raise HTTPException(status_code=404, detail="key not found")
        if key_dict["status"] != "active":
            raise HTTPException(
                status_code=409,
                detail=f"key is {key_dict['status']!r}; activate it first",
            )
        plaintext = decrypt_key(
            # We need the ciphertext — re-load with the secret.
            SessionLocal()
            .execute(
                select(ByokKeyRow).where(
                    ByokKeyRow.user_id == user["id"],
                    ByokKeyRow.id == key_id,
                )
            )
            .scalar_one()
            .encrypted_key
        )
        spec = BYOK_PROVIDER_CATALOG[key_dict["provider"]]
        provider = OpenAICompatibleProvider(
            base_url=key_dict.get("baseUrl") or spec.base_url,
            api_key=plaintext,
            name=f"byok_test_{spec.name}",
            timeout_ms=5000,
        )
        try:
            import httpx

            url = f"{provider.base_url}/models"
            headers = {
                "Authorization": f"Bearer {provider._api_key}",  # noqa: SLF001 (intentional — test path)
                "Content-Type": "application/json",
            }
            start = time.monotonic()
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url, headers=headers)
            latency_ms = int((time.monotonic() - start) * 1000)
            ok = 200 <= resp.status_code < 300
            return {
                "ok": ok,
                "statusCode": resp.status_code,
                "latencyMs": latency_ms,
                "keyFingerprint": key_dict["keyFingerprint"],
                "provider": key_dict["provider"],
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": str(exc)[:256],
                "keyFingerprint": key_dict["keyFingerprint"],
                "provider": key_dict["provider"],
            }

    @router.get("/usage")
    async def usage(
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        return {"ok": True, "userId": user["id"], **store().usage(user["id"])}

    return router


__all__ = [
    "BYOK_PROVIDER_CATALOG",
    "BYOKProviderSpec",
    "BYOKKeyStore",
    "BYOKProvider",
    "BYOKResolveResult",
    "InsufficientCreditsError",
    "fingerprint_key",
    "encrypt_key",
    "decrypt_key",
    "set_byok_fernet_for_tests",
    "get_default_byok_store",
    "reset_default_byok_store",
    "build_byok_router",
]
