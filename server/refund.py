"""W8-1 · 退款接口

Three rules from the brief:

1. **7 天无理由退款** — within 7 days of the order being
   paid, the player may refund for any reason.  The
   refund is **full** when no consumption has happened;
   otherwise it is **prorated** (see rule 2).

2. **部分消耗后退款（按比例）** — the refund amount is
   ``amount_cents * (1 - consumption_rate)``.  The
   consumption rate is computed by
   :meth:`EntitlementService.consumption_for_order` and
   captures the credits the player actually spent.

3. **已解锁的"私人终章"不可退** — the collectors pack
   includes a *consumable* deliverable (the private
   ending).  Once the player has triggered it, the
   refund is 0 regardless of the 7-day window.  The
   red line spells it out: 不要让退款绕过 mandatory
   echo 已触发的事实.

The implementation:

* :class:`RefundService` writes a :class:`RefundRow` and
  flips the order's ``refunded_cents`` counter.
* :func:`compute_refund_amount` is the pure function the
  service calls — it returns ``(amount_cents, refund_type,
  reason)`` so tests can pin the math.
* :class:`RefundRouter` exposes
  ``POST /v1/orders/:id/refund`` (the user-facing
  endpoint) and ``GET /v1/refunds/:id`` (status read).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from auth import require_user
from db import (
    EntitlementRow,
    PaymentOrderRow,
    RefundRow,
    SessionLocal,
)
from payment_gateway import get_default_payment_service
from entitlements import (
    NON_REFUNDABLE_ON_CONSUME_SCOPES,
    get_default_entitlement_service,
)

logger = logging.getLogger("g1n.refund")

#: The refund window — 7 days (decision 4 acceptance
#: criterion + the red line "已解锁的"私人终章"不可退").
REFUND_WINDOW_DAYS = 7
REFUND_WINDOW_SECONDS = REFUND_WINDOW_DAYS * 24 * 60 * 60


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Pure refund math
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class RefundDecision:
    amount_cents: int
    refund_type: str  # "full" | "partial" | "none"
    reason: str
    prorated_consumption_rate: float
    blocked_reason: str | None = None


def compute_refund_amount(
    *,
    order: dict[str, Any],
    consumption: dict[str, Any],
    now: datetime | None = None,
) -> RefundDecision:
    """Pure function — no DB / IO.  The caller passes in
    the order dict + the consumption inspection result.

    Returns a :class:`RefundDecision` the service maps
    onto a :class:`RefundRow`.
    """

    now = now or _now_utc()
    amount = int(order.get("amountCents", 0))
    if order.get("status") != "paid":
        return RefundDecision(
            amount_cents=0,
            refund_type="none",
            reason="order_not_paid",
            prorated_consumption_rate=0.0,
            blocked_reason=f"order status is {order.get('status')!r}",
        )
    paid_at_str = order.get("paidAt")
    if not paid_at_str:
        return RefundDecision(
            amount_cents=0,
            refund_type="none",
            reason="missing_paid_at",
            prorated_consumption_rate=0.0,
            blocked_reason="order has no paidAt",
        )
    paid_at = datetime.fromisoformat(paid_at_str)
    # SQLite drops tzinfo on round-trip; if the parsed
    # value is naive, treat it as UTC (matches the
    # server's ``_now_utc`` convention).
    if paid_at.tzinfo is None:
        paid_at = paid_at.replace(tzinfo=timezone.utc)
    if now - paid_at > timedelta(seconds=REFUND_WINDOW_SECONDS):
        return RefundDecision(
            amount_cents=0,
            refund_type="none",
            reason="outside_7d_window",
            prorated_consumption_rate=0.0,
            blocked_reason=f"paidAt={paid_at.isoformat()}, now={now.isoformat()}",
        )
    rate = float(consumption.get("rate", 0.0))
    unlocked_non_refundable = bool(consumption.get("unlockedNonRefundable", False))
    if unlocked_non_refundable:
        # Red line: 不要让退款绕过 mandatory echo 已触发
        # 的事实("私人终章"已解锁不可退).
        return RefundDecision(
            amount_cents=0,
            refund_type="none",
            reason="private_ending_unlocked",
            prorated_consumption_rate=rate,
            blocked_reason="consumable deliverable already triggered",
        )
    if rate <= 0.0:
        return RefundDecision(
            amount_cents=amount,
            refund_type="full",
            reason="within_7d_no_consumption",
            prorated_consumption_rate=0.0,
        )
    refund = int(round(amount * (1.0 - rate)))
    return RefundDecision(
        amount_cents=refund,
        refund_type="partial" if refund < amount else "full",
        reason="within_7d_prorated",
        prorated_consumption_rate=rate,
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RefundService:
    """Owns the refund lifecycle."""

    def request_refund(
        self,
        *,
        order_id: str,
        user_id: str,
        reason: str = "customer_request",
    ) -> dict[str, Any]:
        payment_svc = get_default_payment_service()
        ent_svc = get_default_entitlement_service()
        with SessionLocal() as s:
            order = s.get(PaymentOrderRow, order_id)
            if order is None:
                raise HTTPException(status_code=404, detail=f"order not found: {order_id}")
            if order.user_id != user_id:
                raise HTTPException(status_code=403, detail="not your order")
            order_dict = order.to_dict()
            # Already-refunded amount.
            existing_refunds = s.execute(
                select(RefundRow).where(
                    RefundRow.order_id == order_id,
                    RefundRow.status.in_(("pending", "succeeded")),
                )
            ).scalars().all()
            already_refunded = sum(int(r.amount_cents) for r in existing_refunds)
            consumption = ent_svc.consumption_for_order(user_id=user_id, order_id=order_id)
            decision = compute_refund_amount(order=order_dict, consumption=consumption)
            if decision.refund_type == "none":
                # Record the rejection for audit; no gateway
                # call, no entitlement mutation.
                blocked = RefundRow(
                    id=f"rej_{uuid.uuid4().hex[:16]}",
                    order_id=order_id,
                    user_id=user_id,
                    reason=reason,
                    refund_type="none",
                    amount_cents=0,
                    prorated_consumption_rate=decision.prorated_consumption_rate,
                    status="rejected",
                    error_message=decision.blocked_reason or decision.reason,
                )
                s.add(blocked)
                s.commit()
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": decision.reason,
                        "message": decision.blocked_reason or decision.reason,
                    },
                )
            remaining = max(0, int(order_dict["amountCents"]) - already_refunded)
            amount_to_refund = min(decision.amount_cents, remaining)
            if amount_to_refund <= 0:
                raise HTTPException(status_code=409, detail={"code": "already_refunded"})
            # Call the gateway.
            try:
                gateway_result = payment_svc.provider.refund(
                    provider_charge_id=order.provider_session_id,
                    provider_payment_intent_id=order.provider_payment_intent_id,
                    amount_cents=amount_to_refund,
                    reason=decision.reason,
                )
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                # The mock provider is in-process; only the
                # Stripe path can fail.  Log and surface.
                logger.exception("refund: gateway call failed for order=%s", order_id)
                failed = RefundRow(
                    id=f"rej_{uuid.uuid4().hex[:16]}",
                    order_id=order_id,
                    user_id=user_id,
                    reason=reason,
                    refund_type=decision.refund_type,
                    amount_cents=amount_to_refund,
                    prorated_consumption_rate=decision.prorated_consumption_rate,
                    status="failed",
                    error_message=str(exc)[:512],
                )
                s.add(failed)
                s.commit()
                raise HTTPException(status_code=502, detail=f"refund failed: {exc}") from exc
            # Persist the refund row + update the order.
            refund_id = f"rfd_{uuid.uuid4().hex[:16]}"
            row = RefundRow(
                id=refund_id,
                order_id=order_id,
                user_id=user_id,
                reason=reason,
                refund_type=decision.refund_type,
                amount_cents=int(gateway_result.amount_cents),
                prorated_consumption_rate=decision.prorated_consumption_rate,
                status=gateway_result.status or "succeeded",
                provider_refund_id=gateway_result.provider_refund_id,
                processed_at=_now_utc(),
                meta_json=json.dumps({"raw": gateway_result.raw}, ensure_ascii=False, default=str),
            )
            s.add(row)
            order.refunded_cents = int(order.refunded_cents) + int(gateway_result.amount_cents)
            if int(order.refunded_cents) >= int(order.amount_cents):
                order.status = "refunded"
            s.commit()
            s.refresh(row)
            s.refresh(order)
            # Revoke the entitlement (credits = 0) when
            # the refund covered the full amount.  For
            # partial refunds, leave the entitlement alone
            # — the player keeps what they paid for.
            if int(order.refunded_cents) >= int(order.amount_cents):
                # Look up the product's scope (the
                # entitlement is keyed on the scope, not
                # the product id; for W8-1 the two happen
                # to be the same, but the lookup below
                # uses the canonical mapping so the
                # revocation works for any new product).
                from payment_gateway import PRODUCT_CATALOG
                product_meta = PRODUCT_CATALOG.get(order.product_id, {})
                scope = product_meta.get("scope", order.product_id)
                ent_svc.revoke(
                    user_id=user_id,
                    scope=scope,
                    reason="refunded",
                )
                # W8-2: append a 'refund' entry to the
                # credit ledger so the operations
                # dashboard can show the
                # refund → credits = 0 transition.
                try:
                    from balance_monitor import (
                        get_default_balance_monitor,
                    )
                    get_default_balance_monitor().note_refund(
                        user_id=user_id,
                        scope=scope,
                        refund_id=refund_id,
                        order_id=order_id,
                        amount_credits=int(product_meta.get("credits", 0) or 0),
                    )
                except Exception as exc:  # noqa: BLE001
                    # The ledger is audit-only; never let
                    # it block the refund.
                    logger.warning(
                        "g1n.refund: credit_ledger.note_refund failed "
                        "for order=%s: %s", order_id, exc,
                    )
            return {"ok": True, "refund": row.to_dict(), "order": order.to_dict()}

    def get_refund(self, refund_id: str) -> dict[str, Any] | None:
        with SessionLocal() as s:
            row = s.get(RefundRow, refund_id)
            return row.to_dict() if row else None

    def list_for_order(self, order_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as s:
            rows = s.execute(
                select(RefundRow)
                .where(RefundRow.order_id == order_id)
                .order_by(RefundRow.requested_at.desc())
            ).scalars().all()
            return [r.to_dict() for r in rows]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_default_service: RefundService | None = None


def get_default_refund_service() -> RefundService:
    global _default_service
    if _default_service is None:
        _default_service = RefundService()
    return _default_service


def reset_default_refund_service() -> None:
    global _default_service
    _default_service = None


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


class RefundRequest(BaseModel):
    reason: str = Field(default="customer_request", max_length=64)


def build_refund_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["refunds"])
    svc = get_default_refund_service

    @router.post("/orders/{order_id}/refund")
    async def request_refund(
        order_id: str,
        req: RefundRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        return svc().request_refund(
            order_id=order_id,
            user_id=user["id"],
            reason=req.reason,
        )

    @router.get("/refunds/{refund_id}")
    async def get_refund(
        refund_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        refund = svc().get_refund(refund_id)
        if refund is None:
            raise HTTPException(status_code=404, detail="refund not found")
        if refund["userId"] != user["id"]:
            raise HTTPException(status_code=403, detail="not your refund")
        return {"ok": True, "refund": refund}

    @router.get("/orders/{order_id}/refunds")
    async def list_for_order(
        order_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        return {"ok": True, "orderId": order_id, "refunds": svc().list_for_order(order_id)}

    return router


__all__ = [
    "REFUND_WINDOW_DAYS",
    "REFUND_WINDOW_SECONDS",
    "RefundDecision",
    "compute_refund_amount",
    "RefundService",
    "get_default_refund_service",
    "reset_default_refund_service",
    "build_refund_router",
]
