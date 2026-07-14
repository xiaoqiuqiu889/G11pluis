"""W8-1 · 真实账号系统

Red lines (from the W8-1 brief):

* 不要让玩家在未登录时强制购买 — every payment endpoint must
  require an authenticated user.  The AuthService exposes
  :func:`require_user` so payment modules can gate their
  routes on it.
* 不要把账号密码明文存储 — only ``bcrypt`` hashes ever touch
  the database; the ``password_hash`` column is the only
  storage surface.
* 不要让 webhook 没有签名验证 — the JWT bearer scheme
  used here is itself a signed token; the HMAC secret comes
  from ``G1N_JWT_SECRET`` (random default in dev / tests
  to avoid a hard-coded fallback).  See
  :func:`_load_jwt_secret`.

Public surface
--------------

* :class:`AuthService` — the singleton facade.
* :class:`EmailPasswordProvider` — bcrypt-backed email + password.
* :class:`WechatProvider` — Wechat Open Platform ``code -> openid``
  flow (mock-mode synthesises the openid so the rest of the
  server is testable offline).
* :class:`AuthRouter` — FastAPI router with
  ``/v1/auth/register``, ``/v1/auth/login``,
  ``/v1/auth/wechat/prepare``, ``/v1/auth/wechat/callback``,
  ``/v1/auth/me``, ``/v1/auth/logout`` (stateless — the
  client discards the token).
* :func:`require_user` — FastAPI dependency that extracts
  the authenticated user from a ``Bearer`` token.
* :func:`issue_jwt` / :func:`decode_jwt` — used by both
  this module and :mod:`server.cross_device` to mint
  ``user``-scoped and ``run_claim``-scoped tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import bcrypt
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db import OAuthBindingRow, SessionLocal, UserCredentialRow, UserRow

logger = logging.getLogger("g1n.auth")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: JWT algorithm (HS256 is fine for a single-tenant game server;
#: production should use a real KMS-stored secret).
JWT_ALGORITHM = "HS256"

#: Default token lifetime — 7 days, matching the refund window
#: so a single JWT can span a partial-refund flow without a
#: forced re-login.
JWT_DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60

#: Run-claim token lifetime — 24h is enough for a cross-device
#: handoff and short enough to keep the security surface small.
RUN_CLAIM_TTL_SECONDS = 24 * 60 * 60

#: bcrypt cost — 12 is the OWASP-recommended default for 2024+;
#: tests can override via ``G1N_BCRYPT_ROUNDS`` for speed.
DEFAULT_BCRYPT_ROUNDS = 12

#: User status strings — kept as plain ``str`` to avoid forcing
#: a DB-level enum migration on the existing ``users`` table.
USER_STATUS_ACTIVE = "active"
USER_STATUS_SUSPENDED = "suspended"
USER_STATUS_DELETED = "deleted"

#: Provider identifiers.
PROVIDER_EMAIL_PASSWORD = "email_password"
PROVIDER_WECHAT = "wechat"

# ---------------------------------------------------------------------------
# JWT secret handling
# ---------------------------------------------------------------------------

_JWT_SECRET_ENV = "G1N_JWT_SECRET"
#: A process-stable random secret when ``G1N_JWT_SECRET`` is
#: not set.  Generated once per process; tests inject a fixed
#: value via the env var so they can sign and verify.
_DEFAULT_JWT_SECRET: str | None = None


def _load_jwt_secret() -> str:
    global _DEFAULT_JWT_SECRET
    secret = os.environ.get(_JWT_SECRET_ENV)
    if secret:
        return secret
    if _DEFAULT_JWT_SECRET is None:
        _DEFAULT_JWT_SECRET = secrets.token_urlsafe(48)
        logger.warning(
            "g1n.auth: %s not set — generated ephemeral JWT secret "
            "(tokens will not survive a process restart).",
            _JWT_SECRET_ENV,
        )
    return _DEFAULT_JWT_SECRET


def set_jwt_secret_for_tests(value: str) -> None:
    """Test hook — pin a known secret so the test client can sign tokens."""

    os.environ[_JWT_SECRET_ENV] = value
    global _DEFAULT_JWT_SECRET
    _DEFAULT_JWT_SECRET = None


# ---------------------------------------------------------------------------
# Token shapes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AuthToken:
    """A signed JWT for an authenticated user.

    The ``scope`` field is the JWT's ``scope`` claim:
    ``"user"`` for an end-user session, ``"run_claim"`` for a
    short-lived cross-device run handoff (see
    :mod:`server.cross_device`).
    """

    token: str
    user_id: str
    scope: str
    issued_at: int
    expires_at: int
    run_id: str | None = None
    device_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "userId": self.user_id,
            "scope": self.scope,
            "issuedAt": self.issued_at,
            "expiresAt": self.expires_at,
            "runId": self.run_id,
            "deviceId": self.device_id,
        }


def issue_jwt(
    *,
    user_id: str,
    scope: str = "user",
    ttl_seconds: int = JWT_DEFAULT_TTL_SECONDS,
    run_id: str | None = None,
    device_id: str | None = None,
) -> AuthToken:
    """Sign a JWT.  Used for both user sessions and run-claim tokens."""

    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user_id,
        "scope": scope,
        "iat": now,
        "exp": now + int(ttl_seconds),
        "jti": uuid.uuid4().hex,
    }
    if run_id is not None:
        payload["runId"] = run_id
    if device_id is not None:
        payload["deviceId"] = device_id
    token = jwt.encode(payload, _load_jwt_secret(), algorithm=JWT_ALGORITHM)
    return AuthToken(
        token=token,
        user_id=user_id,
        scope=scope,
        issued_at=now,
        expires_at=payload["exp"],
        run_id=run_id,
        device_id=device_id,
    )


def decode_jwt(token: str, *, expected_scope: str | None = None) -> dict[str, Any]:
    """Verify signature + expiry; return the payload.

    Raises :class:`fastapi.HTTPException` 401 on any failure
    (we don't leak the reason to the client).
    """

    try:
        payload = jwt.decode(
            token,
            _load_jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat", "scope"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    if expected_scope is not None and payload.get("scope") != expected_scope:
        raise HTTPException(status_code=401, detail="wrong token scope")
    return payload


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class AuthProvider(Protocol):
    """Pluggable identity provider.  Two implementations in
    this module; tests may add more."""

    name: str

    def register(self, *, user_id: str, **fields: Any) -> dict[str, Any]: ...

    def login(self, **fields: Any) -> dict[str, Any]: ...

    def get_or_create_binding(
        self, *, user_id: str, provider_uid: str, meta: dict[str, Any] | None = None
    ) -> OAuthBindingRow: ...


# ---------------------------------------------------------------------------
# Email + password
# ---------------------------------------------------------------------------


class EmailPasswordProvider:
    """Email + bcrypt password provider.

    Stores only the bcrypt hash.  :meth:`register` is idempotent
    on the (email) unique key — a re-registration attempt for
    an existing active user returns a 409; for a soft-deleted
    user it resurrects the row.
    """

    name = PROVIDER_EMAIL_PASSWORD

    def __init__(self, *, bcrypt_rounds: int | None = None) -> None:
        self._rounds = int(
            bcrypt_rounds
            or int(os.environ.get("G1N_BCRYPT_ROUNDS", DEFAULT_BCRYPT_ROUNDS))
        )

    @staticmethod
    def _hash_password(plaintext: str) -> str:
        # bcrypt has a 72-byte input cap; we pre-hash with
        # sha256 to side-step the limit (and to keep the
        # truncation deterministic — bcrypt silently
        # truncates at 72 bytes which would surprise callers
        # with long passphrases).
        digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
        return bcrypt.hashpw(digest.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    @staticmethod
    def _verify_password(plaintext: str, hashed: str) -> bool:
        digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
        try:
            return bcrypt.checkpw(digest.encode("utf-8"), hashed.encode("utf-8"))
        except (ValueError, TypeError):
            return False

    def register(
        self,
        *,
        user_id: str | None = None,
        email: str,
        password: str,
        display_name: str = "",
        **_: Any,
    ) -> dict[str, Any]:
        email_norm = email.strip().lower()
        if not email_norm or "@" not in email_norm:
            raise HTTPException(status_code=400, detail="invalid email")
        if len(password) < 8:
            raise HTTPException(status_code=400, detail="password too short (>= 8 chars)")
        uid = user_id or f"u_{uuid.uuid4().hex[:12]}"
        with SessionLocal() as s:
            existing = s.execute(
                select(UserRow).where(UserRow.email == email_norm)
            ).scalar_one_or_none()
            if existing is not None:
                if existing.status == USER_STATUS_DELETED:
                    existing.status = USER_STATUS_ACTIVE
                else:
                    raise HTTPException(status_code=409, detail="email already registered")
            else:
                existing = UserRow(
                    id=uid,
                    email=email_norm,
                    display_name=display_name or email_norm.split("@", 1)[0],
                    status=USER_STATUS_ACTIVE,
                    is_anonymous=False,
                )
                s.add(existing)
                try:
                    s.flush()
                except IntegrityError as exc:
                    s.rollback()
                    raise HTTPException(status_code=409, detail="email already registered") from exc
            cred = s.execute(
                select(UserCredentialRow).where(UserCredentialRow.user_id == existing.id)
            ).scalar_one_or_none()
            if cred is None:
                cred = UserCredentialRow(
                    user_id=existing.id,
                    password_hash=self._hash_password(password),
                )
                s.add(cred)
            else:
                cred.password_hash = self._hash_password(password)
                cred.rotated_at = _now_utc()
            s.commit()
            s.refresh(existing)
            return existing.to_dict()

    def login(self, *, email: str, password: str, **_: Any) -> dict[str, Any]:
        email_norm = email.strip().lower()
        with SessionLocal() as s:
            user = s.execute(
                select(UserRow).where(UserRow.email == email_norm)
            ).scalar_one_or_none()
            if user is None or user.status == USER_STATUS_DELETED:
                # Don't leak which leg failed: a single "invalid
                # credentials" message covers both the no-user
                # and the wrong-password cases.
                raise HTTPException(status_code=401, detail="invalid credentials")
            if user.status == USER_STATUS_SUSPENDED:
                raise HTTPException(status_code=403, detail="account suspended")
            cred = s.execute(
                select(UserCredentialRow).where(UserCredentialRow.user_id == user.id)
            ).scalar_one_or_none()
            if cred is None or not self._verify_password(password, cred.password_hash):
                raise HTTPException(status_code=401, detail="invalid credentials")
            user.last_active_at = _now_utc()
            s.commit()
            return user.to_dict()

    def get_or_create_binding(
        self,
        *,
        user_id: str,
        provider_uid: str,
        meta: dict[str, Any] | None = None,
    ) -> OAuthBindingRow:
        with SessionLocal() as s:
            binding = s.execute(
                select(OAuthBindingRow).where(
                    OAuthBindingRow.provider == self.name,
                    OAuthBindingRow.provider_user_id == provider_uid,
                )
            ).scalar_one_or_none()
            if binding is None:
                binding = OAuthBindingRow(
                    user_id=user_id,
                    provider=self.name,
                    provider_user_id=provider_uid,
                    provider_meta_json=json_dumps(meta or {}),
                )
                s.add(binding)
                s.commit()
                s.refresh(binding)
            return binding


# ---------------------------------------------------------------------------
# Wechat (Open Platform compatible)
# ---------------------------------------------------------------------------


class WechatProvider:
    """Wechat Open Platform OAuth2 (code -> openid).

    Two endpoints are exposed (see :class:`AuthRouter`):

    * ``/v1/auth/wechat/prepare`` — server generates a
      ``state`` nonce + returns the Wechat authorize URL.
      The client opens the URL in a WebView / browser, the
      user scans with Wechat, Wechat redirects back to the
      client with ``?code=...&state=...``.
    * ``/v1/auth/wechat/callback`` — client POSTs the
      ``code`` to the server; the server exchanges it
      for an ``openid`` via the Wechat API
      (``/sns/oauth2/access_token``).

    When :envvar:`G1N_WECHAT_APPID` is not set (default in
    dev / tests), the provider runs in *mock mode*: the
    ``code`` parameter is treated as the openid directly
    and a deterministic ``provider_uid`` is derived.  This
    keeps the rest of the server testable offline.
    """

    name = PROVIDER_WECHAT

    def __init__(self) -> None:
        self._appid = os.environ.get("G1N_WECHAT_APPID", "")
        self._app_secret = os.environ.get("G1N_WECHAT_APP_SECRET", "")
        self._redirect_uri = os.environ.get(
            "G1N_WECHAT_REDIRECT_URI", "http://127.0.0.1:5173/auth/wechat/callback"
        )
        self._is_mock = not (self._appid and self._app_secret)

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    def prepare(self) -> dict[str, Any]:
        """Generate an authorize URL + state nonce."""

        state = secrets.token_urlsafe(16)
        if self._is_mock:
            # The mock URL is a no-op echo that round-trips
            # ``state`` so the client-side code path stays
            # identical between dev and prod.
            url = (
                f"{self._redirect_uri}?code=mock_openid_{state[:8]}"
                f"&state={state}"
            )
            return {
                "url": url,
                "state": state,
                "mock": True,
                "provider": self.name,
            }
        url = (
            "https://open.weixin.qq.com/connect/oauth2/authorize"
            f"?appid={self._appid}&redirect_uri={self._redirect_uri}"
            f"&response_type=code&scope=snsapi_login&state={state}"
        )
        return {"url": url, "state": state, "mock": False, "provider": self.name}

    def login(self, *, code: str, state: str | None = None, **_: Any) -> dict[str, Any]:
        """Exchange a ``code`` for an openid and resolve a user."""

        if not code:
            raise HTTPException(status_code=400, detail="missing code")
        if self._is_mock:
            provider_uid = self._mock_openid_from_code(code)
            access_token = f"mock_at_{provider_uid}"
        else:
            access_token, provider_uid, _expires_in = self._exchange_code(code)
        # Resolve or create a user.
        with SessionLocal() as s:
            binding = s.execute(
                select(OAuthBindingRow).where(
                    OAuthBindingRow.provider == self.name,
                    OAuthBindingRow.provider_user_id == provider_uid,
                )
            ).scalar_one_or_none()
            if binding is not None:
                user = s.get(UserRow, binding.user_id)
                if user is None or user.status == USER_STATUS_DELETED:
                    raise HTTPException(status_code=401, detail="account deleted")
                if user.status == USER_STATUS_SUSPENDED:
                    raise HTTPException(status_code=403, detail="account suspended")
                user.last_active_at = _now_utc()
                s.commit()
                return user.to_dict() | {"_accessToken": access_token}
            # First-time login: create a user keyed on the
            # openid.  Email is null (Wechat doesn't share
            # it via the login scope).
            uid = f"u_wx_{provider_uid[:12]}"
            user = UserRow(
                id=uid,
                email=None,
                display_name=f"Wechat {provider_uid[:6]}",
                status=USER_STATUS_ACTIVE,
                is_anonymous=False,
            )
            s.add(user)
            try:
                s.flush()
            except IntegrityError as exc:
                s.rollback()
                raise HTTPException(status_code=500, detail="wechat login race") from exc
            binding = OAuthBindingRow(
                user_id=uid,
                provider=self.name,
                provider_user_id=provider_uid,
                provider_meta_json=json_dumps({"state": state, "accessToken": access_token}),
            )
            s.add(binding)
            s.commit()
            s.refresh(user)
            return user.to_dict() | {"_accessToken": access_token}

    def get_or_create_binding(
        self,
        *,
        user_id: str,
        provider_uid: str,
        meta: dict[str, Any] | None = None,
    ) -> OAuthBindingRow:
        with SessionLocal() as s:
            binding = s.execute(
                select(OAuthBindingRow).where(
                    OAuthBindingRow.provider == self.name,
                    OAuthBindingRow.provider_user_id == provider_uid,
                )
            ).scalar_one_or_none()
            if binding is None:
                binding = OAuthBindingRow(
                    user_id=user_id,
                    provider=self.name,
                    provider_user_id=provider_uid,
                    provider_meta_json=json_dumps(meta or {}),
                )
                s.add(binding)
                s.commit()
                s.refresh(binding)
            return binding

    def _exchange_code(self, code: str) -> tuple[str, str, int]:
        """Real Wechat API call — kept lazy-imported so dev
        / tests can run without ``httpx`` misbehaving."""

        import json
        from urllib.parse import urlencode
        from urllib.request import urlopen

        query = urlencode({
            "appid": self._appid,
            "secret": self._app_secret,
            "code": code,
            "grant_type": "authorization_code",
        })
        url = f"https://api.weixin.qq.com/sns/oauth2/access_token?{query}"
        try:
            with urlopen(url, timeout=8) as resp:  # noqa: S310 — controlled URL
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"wechat exchange failed: {exc}") from exc
        if "openid" not in payload:
            raise HTTPException(status_code=401, detail=f"wechat error: {payload.get('errmsg', '?')}")
        return (
            str(payload.get("access_token", "")),
            str(payload["openid"]),
            int(payload.get("expires_in", 7200)),
        )

    @staticmethod
    def _mock_openid_from_code(code: str) -> str:
        # Stable mapping so tests can predict the openid.
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:24]
        return f"mock_open_{digest}"


# ---------------------------------------------------------------------------
# AuthService — the singleton facade
# ---------------------------------------------------------------------------


def _now_utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def json_dumps(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, default=str)


class AuthService:
    """Provider-agnostic facade.

    Holds one instance of each built-in provider.  Tests can
    inject a stub by calling :meth:`register_provider`.
    """

    def __init__(
        self,
        *,
        email_password: EmailPasswordProvider | None = None,
        wechat: WechatProvider | None = None,
    ) -> None:
        self._providers: dict[str, AuthProvider] = {}
        self._providers[PROVIDER_EMAIL_PASSWORD] = email_password or EmailPasswordProvider()
        self._providers[PROVIDER_WECHAT] = wechat or WechatProvider()

    @property
    def providers(self) -> dict[str, AuthProvider]:
        return dict(self._providers)

    def register_provider(self, name: str, provider: AuthProvider) -> None:
        self._providers[name] = provider

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with SessionLocal() as s:
            user = s.get(UserRow, user_id)
            if user is None or user.status == USER_STATUS_DELETED:
                return None
            return user.to_dict()

    def suspend_user(self, user_id: str, *, reason: str = "admin") -> None:
        with SessionLocal() as s:
            user = s.get(UserRow, user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="user not found")
            user.status = USER_STATUS_SUSPENDED
            user.last_active_at = _now_utc()
            s.commit()

    def delete_user(self, user_id: str) -> None:
        """Soft delete — the row stays so refunds / webhooks
        that reference it can still find the foreign key."""

        with SessionLocal() as s:
            user = s.get(UserRow, user_id)
            if user is None:
                return
            user.status = USER_STATUS_DELETED
            user.last_active_at = _now_utc()
            s.commit()

    def ensure_demo_user(self) -> str:
        """Idempotently make sure the W4 ``demo-user`` row
        exists.  The W4 client passes ``userId=demo-user``
        without a JWT; that mode keeps working as a guest
        session, but it can no longer make a real purchase
        (see :mod:`server.payment_gateway`)."""

        with SessionLocal() as s:
            existing = s.get(UserRow, "demo-user")
            if existing is not None:
                return existing.id
            user = UserRow(
                id="demo-user",
                email=None,
                display_name="Demo Player",
                status=USER_STATUS_ACTIVE,
                is_anonymous=True,
            )
            s.add(user)
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
            return "demo-user"

    def register_email_password(
        self, *, email: str, password: str, display_name: str = ""
    ) -> dict[str, Any]:
        provider = self._providers[PROVIDER_EMAIL_PASSWORD]
        assert isinstance(provider, EmailPasswordProvider)
        return provider.register(email=email, password=password, display_name=display_name)

    def login_email_password(self, *, email: str, password: str) -> AuthToken:
        provider = self._providers[PROVIDER_EMAIL_PASSWORD]
        assert isinstance(provider, EmailPasswordProvider)
        user = provider.login(email=email, password=password)
        return issue_jwt(user_id=user["id"], scope="user")

    def prepare_wechat(self) -> dict[str, Any]:
        provider = self._providers[PROVIDER_WECHAT]
        assert isinstance(provider, WechatProvider)
        return provider.prepare()

    def login_wechat(self, *, code: str, state: str | None = None) -> AuthToken:
        provider = self._providers[PROVIDER_WECHAT]
        assert isinstance(provider, WechatProvider)
        user = provider.login(code=code, state=state)
        return issue_jwt(user_id=user["id"], scope="user")


# ---------------------------------------------------------------------------
# FastAPI dependency: require authenticated user
# ---------------------------------------------------------------------------


_default_service: AuthService | None = None


def get_default_auth_service() -> AuthService:
    """Process-wide AuthService singleton."""

    global _default_service
    if _default_service is None:
        _default_service = AuthService()
        # Make sure the legacy demo-user row exists so
        # W4's unauthenticated ``userId=demo-user`` calls
        # keep working as a guest session.
        _default_service.ensure_demo_user()
    return _default_service


def reset_default_auth_service() -> None:
    """Test hook — drop the singleton so the next
    :func:`get_default_auth_service` rebuilds it."""

    global _default_service
    _default_service = None


def require_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """FastAPI dependency: extract the authenticated user from
    ``Authorization: Bearer <jwt>``.

    Raises 401 if the header is missing / malformed /
    expired.  Raises 403 if the user has been suspended or
    deleted since the token was issued (defence in depth —
    the token's signature is still valid, but the
    authoritative status is the database row)."""

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_jwt(token, expected_scope="user")
    svc = get_default_auth_service()
    user = svc.get_user(payload["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    if user["status"] == USER_STATUS_SUSPENDED:
        raise HTTPException(status_code=403, detail="account suspended")
    if user["status"] == USER_STATUS_DELETED:
        raise HTTPException(status_code=401, detail="user not found")
    return user


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    displayName: str = Field(default="", max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class WechatCallbackRequest(BaseModel):
    code: str = Field(min_length=1, max_length=512)
    state: str | None = Field(default=None, max_length=128)


def build_auth_router() -> APIRouter:
    router = APIRouter(prefix="/v1/auth", tags=["auth"])
    svc = get_default_auth_service

    @router.post("/register")
    async def register(req: RegisterRequest) -> dict[str, Any]:
        user = svc().register_email_password(
            email=req.email,
            password=req.password,
            display_name=req.displayName,
        )
        token = issue_jwt(user_id=user["id"], scope="user")
        return {"ok": True, "user": user, "token": token.to_dict()}

    @router.post("/login")
    async def login(req: LoginRequest) -> dict[str, Any]:
        token = svc().login_email_password(email=req.email, password=req.password)
        return {"ok": True, "token": token.to_dict()}

    @router.post("/wechat/prepare")
    async def wechat_prepare() -> dict[str, Any]:
        return svc().prepare_wechat()

    @router.post("/wechat/callback")
    async def wechat_callback(req: WechatCallbackRequest) -> dict[str, Any]:
        # We need the user dict too so the client can
        # show "Welcome, <name>" without a second
        # /v1/auth/me round-trip.  Re-resolve the user
        # from the freshly-minted token.
        token = svc().login_wechat(code=req.code, state=req.state)
        user = svc().get_user(token.user_id)
        return {
            "ok": True,
            "user": user,
            "token": token.to_dict(),
            "mock": svc().providers[PROVIDER_WECHAT].is_mock,
        }

    @router.get("/me")
    async def me(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return {"ok": True, "user": user}

    @router.post("/logout")
    async def logout(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        # JWTs are stateless — the client just discards the
        # token.  The endpoint exists so the client can
        # call a "I'm out" hook that may eventually
        # invalidate a refresh-token table.
        return {"ok": True, "userId": user["id"]}

    return router


# ---------------------------------------------------------------------------
# Webhook signature helpers (shared with payment_gateway.py)
# ---------------------------------------------------------------------------


def hmac_sha256(secret: str, payload: bytes) -> str:
    """HMAC-SHA256 hex digest — used for webhook signing."""

    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


__all__ = [
    # constants
    "JWT_ALGORITHM",
    "JWT_DEFAULT_TTL_SECONDS",
    "RUN_CLAIM_TTL_SECONDS",
    "USER_STATUS_ACTIVE",
    "USER_STATUS_SUSPENDED",
    "USER_STATUS_DELETED",
    "PROVIDER_EMAIL_PASSWORD",
    "PROVIDER_WECHAT",
    # tokens
    "AuthToken",
    "issue_jwt",
    "decode_jwt",
    "set_jwt_secret_for_tests",
    # providers
    "AuthProvider",
    "EmailPasswordProvider",
    "WechatProvider",
    "AuthService",
    # service access
    "get_default_auth_service",
    "reset_default_auth_service",
    "require_user",
    "build_auth_router",
    # helpers
    "hmac_sha256",
    "constant_time_eq",
]
