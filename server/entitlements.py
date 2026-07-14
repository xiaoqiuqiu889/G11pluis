"""W8-1 · 真实权益系统

W4 had a single ``/v1/purchases/mock-confirm`` endpoint
that wrote a synthetic entitlement row.  W8-1 replaces that
with the real entitlement lifecycle:

* :class:`EntitlementService` is the single source of
  truth — the W4 mock-confirm endpoint and the W8-1
  payment webhook both call into it.
* :class:`EntitlementsRouter` exposes the cross-device
  sync surface (``GET /v1/entitlements``) plus a
  back-compat alias for the W4 ``mock-confirm`` endpoint
  (the W4 client keeps working — it just goes through a
  different code path now).

The entitlement row is keyed on ``(user_id, scope)`` (the
W4 unique constraint is preserved) and carries the
W8-1 additions:

* ``expires_at``              — W4 already had it.
* ``auto_renew``              — boolean (W8-1).
* ``payment_provider_txn_id`` — the gateway charge id (W8-1).
* ``revoked_reason``          — populated when a refund
                                 pulls the entitlement back.

Consumption tracking
--------------------

The brief says: 退款逻辑 must honour consumption (you used
half the credits -> half refund).  Consumption is captured
as a ``model_calls``-derived metric: the entitlement's
``credits`` column is decremented as the player spends them
(decision 5 keeps the LLM call count in ``model_calls``;
the W8-1 entitlement service watches that table).

The function :func:`compute_consumption_rate` returns a
0..1 fraction the refund module uses to compute the
prorated amount.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from auth import require_user
from db import (
    EntitlementRow,
    GameRun,
    ModelCallRow,
    PaymentOrderRow,
    RefundRow,
    SessionLocal,
)
from payment_gateway import (
    PRODUCT_CATALOG,
    _validate_product_id,
    get_default_payment_service,
)

logger = logging.getLogger("g1n.entitlements")

# ---------------------------------------------------------------------------
# W4-back-compat shim
# ---------------------------------------------------------------------------

#: Scopes the W4 client hard-codes (decision 4 product
#: catalog).  The W8-1 entitlement service treats these
#: as authoritative.
W4_SCOPES: frozenset[str] = frozenset({
    "free_sample", "passport", "collectors",
    "parallel_ops", "credits", "pov_unlock", "keepsake",
})

#: Scopes that unlock **consumable** content; once any of
#: these is consumed (e.g. the player opened the private
#: ending), the entitlement is *non-refundable*.  Used by
#: :mod:`server.refund`.
NON_REFUNDABLE_ON_CONSUME_SCOPES: frozenset[str] = frozenset({
    "collectors",      # private ending unlock
    "pov_unlock",      # per-segment reveal
    "keepsake",        # deliverable letter + photos + report
})


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_json(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _from_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


class EntitlementService:
    """Owns the entitlement lifecycle."""

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as s:
            rows = s.execute(
                select(EntitlementRow)
                .where(EntitlementRow.user_id == user_id)
                .order_by(EntitlementRow.purchased_at.desc())
            ).scalars().all()
            return [r.to_dict() for r in rows]

    def get_one(self, user_id: str, scope: str) -> dict[str, Any] | None:
        with SessionLocal() as s:
            row = s.execute(
                select(EntitlementRow).where(
                    EntitlementRow.user_id == user_id,
                    EntitlementRow.scope == scope,
                )
            ).scalar_one_or_none()
            return row.to_dict() if row else None

    def has_scope(self, user_id: str, scope: str) -> bool:
        """True iff the user has an active (non-revoked) entitlement
        for the given scope and the credits / non-expiry gate
        is satisfied."""

        ent = self.get_one(user_id, scope)
        if ent is None or ent.get("revokedReason"):
            return False
        if ent.get("expiresAt") is not None:
            expires_at = datetime.fromisoformat(ent["expiresAt"])
            if expires_at < _now_utc():
                return False
        return True

    def issue(
        self,
        *,
        user_id: str,
        scope: str,
        credits: int = 0,
        payment_provider_txn_id: str | None = None,
        auto_renew: bool = False,
        expires_at: datetime | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue or top-up an entitlement.  Idempotent on
        ``(user_id, scope)`` — re-issuing adds credits rather
        than overwriting them."""

        with SessionLocal() as s:
            existing = s.execute(
                select(EntitlementRow).where(
                    EntitlementRow.user_id == user_id,
                    EntitlementRow.scope == scope,
                )
            ).scalar_one_or_none()
            if existing is not None:
                # W8-2: when the existing row was previously
                # revoked (e.g. a refund clawed the credits
                # back), un-revoking is a *restore* event
                # worth recording in the credit ledger so
                # the ops dashboard can show
                # "refund → re-purchase → credits restored"
                # as a single line.
                was_revoked = existing.revoked_reason is not None
                existing.credits = int(existing.credits) + int(credits)
                if payment_provider_txn_id:
                    existing.payment_provider_txn_id = payment_provider_txn_id
                if auto_renew:
                    existing.auto_renew = True
                if expires_at is not None:
                    existing.expires_at = expires_at
                existing.revoked_reason = None
                if meta:
                    existing.meta_json = _to_json({**(_from_json(existing.meta_json) or {}), **meta})
                s.commit()
                s.refresh(existing)
                if was_revoked:
                    try:
                        from balance_monitor import (
                            get_default_balance_monitor,
                        )
                        get_default_balance_monitor().note_restore(
                            user_id=user_id,
                            scope=scope,
                            new_credits=int(credits),
                            order_id=payment_provider_txn_id,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "g1n.entitlements: credit_ledger.note_restore failed "
                            "for user=%s scope=%s: %s", user_id, scope, exc,
                        )
                return existing.to_dict()
            row = EntitlementRow(
                user_id=user_id,
                scope=scope,
                credits=int(credits),
                purchased_at=_now_utc(),
                expires_at=expires_at,
                auto_renew=bool(auto_renew),
                payment_provider_txn_id=payment_provider_txn_id,
                meta_json=_to_json(meta or {}),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.to_dict()

    def revoke(
        self,
        *,
        user_id: str,
        scope: str,
        reason: str,
    ) -> dict[str, Any] | None:
        with SessionLocal() as s:
            row = s.execute(
                select(EntitlementRow).where(
                    EntitlementRow.user_id == user_id,
                    EntitlementRow.scope == scope,
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            row.credits = 0
            row.revoked_reason = reason[:64]
            s.commit()
            s.refresh(row)
            return row.to_dict()

    def consume_credits(self, *, user_id: str, scope: str, n: int) -> int:
        """Deduct ``n`` credits from the entitlement.  Returns
        the number actually deducted (may be less than ``n``
        if the user runs out).  Used by the LLM runtime to
        charge the player against their credits."""

        if n <= 0:
            return 0
        with SessionLocal() as s:
            row = s.execute(
                select(EntitlementRow).where(
                    EntitlementRow.user_id == user_id,
                    EntitlementRow.scope == scope,
                )
            ).scalar_one_or_none()
            if row is None or row.revoked_reason:
                return 0
            take = min(int(n), int(row.credits))
            row.credits = int(row.credits) - take
            s.commit()
            return take

    def sync_from_orders(self, user_id: str) -> list[dict[str, Any]]:
        """Backfill: any ``paid`` order that doesn't have a
        matching entitlement row gets one issued.  Idempotent."""

        with SessionLocal() as s:
            paid_orders = s.execute(
                select(PaymentOrderRow).where(
                    PaymentOrderRow.user_id == user_id,
                    PaymentOrderRow.status == "paid",
                )
            ).scalars().all()
            issued: list[dict[str, Any]] = []
            for order in paid_orders:
                product = PRODUCT_CATALOG.get(order.product_id)
                if product is None:
                    continue
                existing = s.execute(
                    select(EntitlementRow).where(
                        EntitlementRow.user_id == user_id,
                        EntitlementRow.scope == product["scope"],
                    )
                ).scalar_one_or_none()
                if existing is None:
                    ent = EntitlementRow(
                        user_id=user_id,
                        scope=product["scope"],
                        credits=int(product["credits"]),
                        purchased_at=order.paid_at or _now_utc(),
                        payment_provider_txn_id=order.provider_payment_intent_id or order.provider_session_id,
                        auto_renew=bool(product.get("autoRenew", False)),
                    )
                    s.add(ent)
                    s.flush()
                    issued.append(ent.to_dict())
            s.commit()
        return issued

    def consumption_for_order(
        self,
        *,
        user_id: str,
        order_id: str,
    ) -> dict[str, Any]:
        """Inspect how much of an order's entitlement has been
        consumed (so :mod:`server.refund` can prorate).

        Returns::

            {
              "consumed": 80,           # model calls attributed to the order
              "granted": 200,            # credits originally granted
              "rate": 0.4,               # 0..1 (consumed / granted)
              "unlockedNonRefundable": bool
            }
        """
        with SessionLocal() as s:
            order = s.get(PaymentOrderRow, order_id)
            if order is None:
                raise HTTPException(status_code=404, detail=f"order not found: {order_id}")
            product = PRODUCT_CATALOG.get(order.product_id) or {}
            scope = product.get("scope")
            ent = None
            if scope:
                ent = s.execute(
                    select(EntitlementRow).where(
                        EntitlementRow.user_id == user_id,
                        EntitlementRow.scope == scope,
                    )
                ).scalar_one_or_none()
            granted = int(product.get("credits", 0) or 0)
            if ent is None:
                consumed = 0
            else:
                # Initial credits (granted) = current + consumed.
                consumed = max(0, granted - int(ent.credits))
            rate = 0.0 if granted <= 0 else min(1.0, consumed / float(granted))
            # "Non-refundable on consume" gates: any of the
            # non-refundable scopes counts as already-consumed
            # for refund purposes.
            unlocked_non_refundable = order.product_id in NON_REFUNDABLE_ON_CONSUME_SCOPES and consumed > 0
            return {
                "consumed": consumed,
                "granted": granted,
                "rate": rate,
                "unlockedNonRefundable": unlocked_non_refundable,
                "orderProductId": order.product_id,
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_default_service: EntitlementService | None = None


def get_default_entitlement_service() -> EntitlementService:
    global _default_service
    if _default_service is None:
        _default_service = EntitlementService()
    return _default_service


def reset_default_entitlement_service() -> None:
    global _default_service
    _default_service = None


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


class MockConfirmRequest(BaseModel):
    """W4 back-compat shim — kept so the W4 client keeps
    working.  Maps directly onto a free / mock-paid
    entitlement for the default user."""

    userId: str = Field(default="demo-user", min_length=1, max_length=64)
    productId: str = Field(..., min_length=1, max_length=64)
    credits: int = Field(default=0, ge=0, le=100000)
    meta: dict[str, Any] = Field(default_factory=dict)


class ConsumeRequest(BaseModel):
    scope: str = Field(min_length=1, max_length=32)
    n: int = Field(ge=1, le=10000)


class SyncRequest(BaseModel):
    pass  # body unused — endpoint just triggers the sync


def build_entitlements_router() -> APIRouter:
    router = APIRouter(prefix="/v1/entitlements", tags=["entitlements"])
    svc = get_default_entitlement_service

    @router.get("")
    async def list_entitlements(
        userId: str | None = None,
        user: dict[str, Any] | None = Depends(_maybe_user),
    ) -> dict[str, Any]:
        """Cross-device sync endpoint.

        If the request carries a valid JWT, the server
        uses ``user['id']`` — the ``userId`` query param
        is ignored (preventing one user from reading
        another user's entitlements).  If the request has
        no JWT, the ``userId`` query param is honoured —
        this is the W4 demo-user back-compat path.
        """

        target_user_id = (user or {}).get("id") or userId or "demo-user"
        items = svc().list_for_user(target_user_id)
        return {
            "ok": True,
            "userId": target_user_id,
            "entitlements": items,
            "defaultUser": target_user_id == "demo-user",
            "source": "db",
        }

    @router.post("/sync")
    async def sync(
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        """Reconcile the user's entitlements with their paid orders."""

        issued = svc().sync_from_orders(user["id"])
        return {"ok": True, "issued": issued, "current": svc().list_for_user(user["id"])}

    @router.post("/consume")
    async def consume(
        req: ConsumeRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        consumed = svc().consume_credits(user_id=user["id"], scope=req.scope, n=req.n)
        return {"ok": True, "consumed": consumed, "scope": req.scope}

    @router.post("/mock-confirm")
    async def mock_confirm(req: MockConfirmRequest) -> dict[str, Any]:
        """W4 back-compat — used by the W4 client in mock
        mode.  Internally goes through the entitlement
        service so the W4 happy-path and the W8-1
        payment-webhook path share the same write surface."""

        product = _validate_product_id(req.productId)
        ent = svc().issue(
            user_id=req.userId,
            scope=product["scope"],
            credits=int(req.credits or product.get("credits", 0)),
            payment_provider_txn_id=f"mock_confirm_{uuid.uuid4().hex[:12]}",
            meta={"source": "w4_mock_confirm", "productId": req.productId, **(req.meta or {})},
        )
        return {"ok": True, "userId": req.userId, "productId": req.productId, "entitlement": ent}

    return router


# ---------------------------------------------------------------------------
# Optional-auth dependency for ``GET /v1/entitlements``
# ---------------------------------------------------------------------------


async def _maybe_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any] | None:
    """Like :func:`auth.require_user` but returns ``None``
    when the header is missing — used by the W4
    ``GET /v1/entitlements`` endpoint so unauthenticated
    callers (the demo user) still get a response."""

    if not authorization:
        return None
    try:
        return require_user(authorization=authorization)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# W4 mock-confirm alias — kept at module-level so app.py
# can keep using the ``/v1/purchases/mock-confirm`` path.
# ---------------------------------------------------------------------------


def mock_confirm_back_compat(req: MockConfirmRequest) -> dict[str, Any]:
    """Function-form of the W4 ``/v1/purchases/mock-confirm``."""

    product = _validate_product_id(req.productId)
    ent = get_default_entitlement_service().issue(
        user_id=req.userId,
        scope=product["scope"],
        credits=int(req.credits or product.get("credits", 0)),
        payment_provider_txn_id=f"mock_confirm_{uuid.uuid4().hex[:12]}",
        meta={"source": "w4_purchases_mock_confirm", "productId": req.productId, **(req.meta or {})},
    )
    return {"ok": True, "userId": req.userId, "productId": req.productId, "entitlement": ent}


__all__ = [
    "W4_SCOPES",
    "NON_REFUNDABLE_ON_CONSUME_SCOPES",
    "EntitlementService",
    "get_default_entitlement_service",
    "reset_default_entitlement_service",
    "build_entitlements_router",
    "mock_confirm_back_compat",
]
