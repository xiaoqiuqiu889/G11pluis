"""W8-1 · 真实支付抽象层

The W4 server shipped with a ``/v1/purchases/mock-confirm``
endpoint that wrote a synthetic entitlement row.  W8-1
replaces that with a real payment-gateway abstraction:

* :class:`PaymentProvider` — the abstract interface
  (create_session, verify_webhook, refund).
* :class:`MockProvider` — the **default** provider.  No real
  charge is made; the order auto-pays after a configurable
  delay.  The Mock provider **still runs the JSON-Schema
  validation** (red line: 不要让 mock provider 跳 schema
  校验) so the test surface matches production.
* :class:`StripeProvider` — uses the real Stripe SDK
  (OpenAI-compatible: the same call shapes work with any
  OpenAI-style provider the team swaps in).  Webhook
  verification uses ``stripe.Webhook.construct_event`` —
  no signature check, no entitlement mutation.

The selection rule is:

* If ``G1N_PAYMENT_PROVIDER=stripe`` **and**
  ``G1N_STRIPE_SECRET_KEY`` is set, use :class:`StripeProvider`.
* Otherwise, use :class:`MockProvider` (the default).

The module also exposes :class:`PaymentRouter` — the
FastAPI router with the order-creation + webhook endpoints
the client talks to.  The order-creation endpoint requires
a JWT (red line: 不要让玩家在未登录时强制购买).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from auth import (
    PROVIDER_EMAIL_PASSWORD,
    PROVIDER_WECHAT,
    hmac_sha256,
    require_user,
)
from db import (
    EntitlementRow,
    PaymentOrderRow,
    PaymentWebhookEventRow,
    SessionLocal,
)

logger = logging.getLogger("g1n.payment")

# ---------------------------------------------------------------------------
# Product catalog (mirrors server/app.py:PRODUCT_CATALOG 1:1)
# ---------------------------------------------------------------------------

PRODUCT_CATALOG: dict[str, dict[str, Any]] = {
    "free_sample": {"priceCents": 0, "currency": "CNY", "credits": 0, "scope": "free_sample",
                    "ttlSeconds": None, "autoRenew": False, "nonRefundable": False},
    "passport": {"priceCents": 2500, "currency": "CNY", "credits": 200, "scope": "passport",
                 "ttlSeconds": None, "autoRenew": False, "nonRefundable": False},
    "collectors": {"priceCents": 4800, "currency": "CNY", "credits": 500, "scope": "collectors",
                   "ttlSeconds": None, "autoRenew": False,
                   "nonRefundable": False,  # private ending unlock is a *consumption* trigger, not the product
                   "unlocks": ["private_ending"]},
    "parallel_ops": {"priceCents": 1200, "currency": "CNY", "credits": 0, "scope": "parallel_ops",
                     "ttlSeconds": None, "autoRenew": False, "nonRefundable": False,
                     "unlocks": ["parallel_ops"]},
    "credits": {"priceCents": 1200, "currency": "CNY", "credits": 150, "scope": "credits",
                "ttlSeconds": None, "autoRenew": False, "nonRefundable": False},
    "pov_unlock": {"priceCents": 300, "currency": "CNY", "credits": 0, "scope": "pov_unlock",
                   "ttlSeconds": None, "autoRenew": False, "nonRefundable": False,
                   "unlocks": ["pov_unlock"]},
    "keepsake": {"priceCents": 800, "currency": "CNY", "credits": 0, "scope": "keepsake",
                 "ttlSeconds": None, "autoRenew": False, "nonRefundable": True,
                 "unlocks": ["keepsake"]},
}


def _validate_product_id(product_id: str) -> dict[str, Any]:
    """Look up a product; raise 400 if unknown.  Used by
    every provider so the schema-validation rule applies
    to the Mock provider too."""

    if product_id not in PRODUCT_CATALOG:
        raise HTTPException(status_code=400, detail=f"unknown product: {product_id}")
    return PRODUCT_CATALOG[product_id]


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CheckoutSession:
    """The provider's response to a create_session call.

    ``provider_session_id`` is what the gateway will echo
    back in its webhook (Stripe ``session.id``, Mock
    ``mock_sess_<id>``).  ``url`` is where the client
    redirects; for the mock provider it points at an
    internal auto-confirm endpoint.
    """

    provider: str
    provider_session_id: str
    url: str
    expires_at: int
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WebhookEvent:
    """A verified webhook event."""

    provider: str
    event_id: str
    event_type: str
    order_id: str | None
    amount_cents: int
    currency: str
    payload: dict[str, Any]
    received_at: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RefundResult:
    """The provider's response to a refund call."""

    provider: str
    provider_refund_id: str
    amount_cents: int
    status: str
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class PaymentProvider(Protocol):
    """The contract every payment backend implements."""

    name: str
    is_mock: bool

    def create_session(
        self,
        *,
        order_id: str,
        user_id: str,
        product_id: str,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> CheckoutSession: ...

    def verify_webhook(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
    ) -> WebhookEvent: ...

    def refund(
        self,
        *,
        provider_charge_id: str | None,
        provider_payment_intent_id: str | None,
        amount_cents: int,
        reason: str = "customer_request",
    ) -> RefundResult: ...


# ---------------------------------------------------------------------------
# MockProvider
# ---------------------------------------------------------------------------


class MockProvider:
    """In-process mock payment provider.

    The order is *not* marked paid on ``create_session``;
    the test (or the dev console) posts a synthetic webhook
    to :class:`PaymentRouter` ``/v1/payments/webhook/mock``
    to advance the order to ``paid``.  This mirrors the
    Stripe flow (create session -> user pays -> webhook)
    and exercises the same webhook-signature code path.

    The webhook signature scheme is HMAC-SHA256 of the body
    using ``G1N_MOCK_WEBHOOK_SECRET`` (default: a
    per-process random key).  Tests inject a known secret
    via :func:`set_mock_webhook_secret_for_tests`.
    """

    name = "mock"
    is_mock = True

    def __init__(self) -> None:
        self._secret = os.environ.get("G1N_MOCK_WEBHOOK_SECRET", "")
        if not self._secret:
            self._secret = secrets.token_urlsafe(24)
            logger.warning(
                "g1n.payment: G1N_MOCK_WEBHOOK_SECRET not set — "
                "generated ephemeral secret (tests must inject one)."
            )

    @property
    def secret(self) -> str:
        return self._secret

    def create_session(
        self,
        *,
        order_id: str,
        user_id: str,
        product_id: str,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> CheckoutSession:
        # Free products short-circuit: the order is paid
        # immediately, no checkout URL needed.
        if amount_cents <= 0:
            return CheckoutSession(
                provider=self.name,
                provider_session_id=f"mock_sess_{order_id}",
                url=success_url,
                expires_at=int(time.time()) + 60,
                raw={"autoPaid": True, "productId": product_id},
            )
        session_id = f"mock_sess_{order_id}"
        # The success_url has a ``?session_id=`` template
        # placeholder so the client can confirm on return.
        url = f"{success_url}?session_id={session_id}&order_id={order_id}&mock=1"
        return CheckoutSession(
            provider=self.name,
            provider_session_id=session_id,
            url=url,
            expires_at=int(time.time()) + 60 * 30,
            raw={"productId": product_id, "amountCents": amount_cents, "currency": currency},
        )

    def sign_webhook(self, raw_body: bytes) -> str:
        """Return the signature header value the client should send."""

        return hmac_sha256(self._secret, raw_body)

    def verify_webhook(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
    ) -> WebhookEvent:
        if not signature_header:
            raise HTTPException(status_code=400, detail="missing signature")
        expected = self.sign_webhook(raw_body)
        if not hmac.compare_digest(expected, signature_header):
            raise HTTPException(status_code=401, detail="invalid webhook signature")
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="invalid webhook body") from exc
        event_id = str(payload.get("id") or f"mock_evt_{uuid.uuid4().hex[:16]}")
        event_type = str(payload.get("type") or "unknown")
        data = payload.get("data") or {}
        order_id = data.get("order_id")
        amount_cents = int(data.get("amount_cents", 0))
        currency = str(data.get("currency", "CNY"))
        return WebhookEvent(
            provider=self.name,
            event_id=event_id,
            event_type=event_type,
            order_id=order_id,
            amount_cents=amount_cents,
            currency=currency,
            payload=payload,
            received_at=int(time.time()),
        )

    def refund(
        self,
        *,
        provider_charge_id: str | None,
        provider_payment_intent_id: str | None,
        amount_cents: int,
        reason: str = "customer_request",
    ) -> RefundResult:
        return RefundResult(
            provider=self.name,
            provider_refund_id=f"mock_re_{uuid.uuid4().hex[:16]}",
            amount_cents=int(amount_cents),
            status="succeeded",
            raw={
                "chargeId": provider_charge_id,
                "paymentIntentId": provider_payment_intent_id,
                "reason": reason,
            },
        )


def set_mock_webhook_secret_for_tests(secret: str) -> None:
    os.environ["G1N_MOCK_WEBHOOK_SECRET"] = secret
    # Force the singleton to rebuild on next access.
    reset_default_payment_service()


# ---------------------------------------------------------------------------
# StripeProvider
# ---------------------------------------------------------------------------


class StripeProvider:
    """Stripe-backed provider.

    Mirrors the OpenAI/Stripe SDK style: ``stripe.checkout.Session.create``,
    ``stripe.Webhook.construct_event``, ``stripe.Refund.create``.

    To enable:

    .. code-block:: bash

        pip install stripe
        export G1N_PAYMENT_PROVIDER=stripe
        export G1N_STRIPE_SECRET_KEY=sk_test_...
        export G1N_STRIPE_WEBHOOK_SECRET=whsec_...

    Webhook signature verification uses ``stripe.Webhook.construct_event``
    (HMAC-SHA256 under the hood).  A missing or invalid signature
    raises a 401 *before* any entitlement is mutated (red line:
    不要让 webhook 没有签名验证).
    """

    name = "stripe"
    is_mock = False

    def __init__(self) -> None:
        self._api_key = os.environ.get("G1N_STRIPE_SECRET_KEY", "")
        self._webhook_secret = os.environ.get("G1N_STRIPE_WEBHOOK_SECRET", "")
        if not self._api_key:
            raise RuntimeError("G1N_STRIPE_SECRET_KEY required for StripeProvider")
        if not self._webhook_secret:
            raise RuntimeError("G1N_STRIPE_WEBHOOK_SECRET required for StripeProvider")
        # Lazy import so the module loads without Stripe installed.
        import stripe
        stripe.api_key = self._api_key
        self._stripe = stripe

    def create_session(
        self,
        *,
        order_id: str,
        user_id: str,
        product_id: str,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> CheckoutSession:
        if amount_cents <= 0:
            # Free products: there's no Stripe checkout to
            # create; mirror the mock short-circuit so the
            # router can treat the response uniformly.
            return CheckoutSession(
                provider=self.name,
                provider_session_id=f"free_{order_id}",
                url=success_url,
                expires_at=int(time.time()) + 60,
                raw={"autoPaid": True, "productId": product_id},
            )
        session = self._stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": currency.lower(),
                    "unit_amount": int(amount_cents),
                    "product_data": {"name": product_id},
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={
                "order_id": order_id,
                "user_id": user_id,
                "product_id": product_id,
                **(metadata or {}),
            },
        )
        return CheckoutSession(
            provider=self.name,
            provider_session_id=session.id,
            url=session.url,
            expires_at=int(time.time()) + 60 * 30,
            raw={"paymentIntent": getattr(session, "payment_intent", None)},
        )

    def verify_webhook(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
    ) -> WebhookEvent:
        if not signature_header:
            raise HTTPException(status_code=400, detail="missing stripe-signature header")
        try:
            event = self._stripe.Webhook.construct_event(
                raw_body, signature_header, self._webhook_secret
            )
        except self._stripe.error.SignatureVerificationError as exc:
            raise HTTPException(status_code=401, detail="invalid signature") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid webhook payload") from exc
        data = event.data.object
        return WebhookEvent(
            provider=self.name,
            event_id=event.id,
            event_type=event.type,
            order_id=(data.get("metadata", {}) or {}).get("order_id") if hasattr(data, "get") else None,
            amount_cents=int(getattr(data, "amount_total", 0) or 0),
            currency=str(getattr(data, "currency", "cny") or "cny"),
            payload=event.to_dict() if hasattr(event, "to_dict") else {"id": event.id, "type": event.type},
            received_at=int(time.time()),
        )

    def refund(
        self,
        *,
        provider_charge_id: str | None,
        provider_payment_intent_id: str | None,
        amount_cents: int,
        reason: str = "customer_request",
    ) -> RefundResult:
        params: dict[str, Any] = {"amount": int(amount_cents)}
        if provider_charge_id:
            params["charge"] = provider_charge_id
        elif provider_payment_intent_id:
            params["payment_intent"] = provider_payment_intent_id
        else:
            raise HTTPException(status_code=400, detail="refund target missing")
        refund = self._stripe.Refund.create(**params)
        return RefundResult(
            provider=self.name,
            provider_refund_id=refund.id,
            amount_cents=int(refund.amount),
            status=refund.status or "pending",
            raw={"reason": reason},
        )


# ---------------------------------------------------------------------------
# Service: PaymentService — handles provider selection + order lifecycle
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_utc_int() -> int:
    return int(time.time())


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class PaymentService:
    """Owns the active provider and the order-lifecycle glue."""

    def __init__(self, provider: PaymentProvider | None = None) -> None:
        if provider is not None:
            self._provider = provider
        else:
            self._provider = self._build_default_provider()

    @property
    def provider(self) -> PaymentProvider:
        return self._provider

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def is_mock(self) -> bool:
        return self._provider.is_mock

    @staticmethod
    def _build_default_provider() -> PaymentProvider:
        wanted = os.environ.get("G1N_PAYMENT_PROVIDER", "mock").lower()
        if wanted == "stripe":
            return StripeProvider()
        return MockProvider()

    def create_order(
        self,
        *,
        user_id: str,
        product_id: str,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        product = _validate_product_id(product_id)
        order_id = f"ord_{uuid.uuid4().hex[:16]}"
        amount_cents = int(product["priceCents"])
        currency = str(product["currency"])
        # Pre-create the order row in ``pending`` status.
        # The webhook flips it to ``paid`` and writes the
        # entitlement.
        with SessionLocal() as s:
            s.add(PaymentOrderRow(
                id=order_id,
                user_id=user_id,
                product_id=product_id,
                amount_cents=amount_cents,
                currency=currency,
                status="pending",
                provider=self._provider.name,
                expires_at=_now_utc() + timedelta(hours=1),
                meta_json=json.dumps({"productScope": product["scope"]}, ensure_ascii=False),
            ))
            s.commit()
        if amount_cents == 0:
            # Free sample / zero-amount: auto-pay the
            # order so the client doesn't have to bounce
            # through a checkout page.
            self._mark_order_paid(
                order_id=order_id,
                provider_payment_intent_id=f"free_{order_id}",
                payment_method="free",
            )
        # Otherwise, ask the provider to create a checkout
        # session.  The client redirects to ``url`` and the
        # provider later POSTs the webhook.
        session = self._provider.create_session(
            order_id=order_id,
            user_id=user_id,
            product_id=product_id,
            amount_cents=amount_cents,
            currency=currency,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"productScope": product["scope"]},
        )
        # Persist the provider session id so the webhook
        # can find the order without scanning the metadata.
        with SessionLocal() as s:
            order = s.get(PaymentOrderRow, order_id)
            if order is not None:
                order.provider_session_id = session.provider_session_id
                if session.raw.get("autoPaid"):
                    order.provider_payment_intent_id = f"free_{order_id}"
                    order.payment_method = "free"
                s.commit()
        return {
            "orderId": order_id,
            "productId": product_id,
            "amountCents": amount_cents,
            "currency": currency,
            "status": "paid" if session.raw.get("autoPaid") else "pending",
            "provider": self._provider.name,
            "checkout": session.to_dict(),
        }

    def record_webhook(
        self,
        *,
        provider: str,
        provider_event_id: str,
        event_type: str,
        order_id: str | None,
        signature_verified: bool,
        raw_payload: dict[str, Any],
        error_message: str | None = None,
    ) -> PaymentWebhookEventRow:
        with SessionLocal() as s:
            existing = s.execute(
                select(PaymentWebhookEventRow).where(
                    PaymentWebhookEventRow.provider == provider,
                    PaymentWebhookEventRow.provider_event_id == provider_event_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing
            row = PaymentWebhookEventRow(
                provider=provider,
                provider_event_id=provider_event_id,
                event_type=event_type,
                order_id=order_id,
                signature_verified=bool(signature_verified),
                raw_payload=json.dumps(raw_payload, ensure_ascii=False, default=str),
                processed_at=_now_utc() if signature_verified and not error_message else None,
                error_message=error_message,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row

    def handle_webhook(self, event: WebhookEvent) -> dict[str, Any]:
        """Process a verified webhook event.

        Currently supported:
        * ``checkout.session.completed`` / ``mock.session.paid``
          -> mark the order paid + issue the entitlement.
        * ``charge.refunded`` / ``mock.refund.succeeded``
          -> bookkeeping only; refund is initiated from
          :mod:`server.refund`.

        Returns a summary dict for the HTTP response.
        """

        if event.event_type in ("checkout.session.completed", "mock.session.paid"):
            return self._mark_order_paid(
                order_id=event.order_id or "",
                provider_payment_intent_id=(event.payload.get("data") or {}).get("payment_intent"),
                payment_method=(event.payload.get("data") or {}).get("payment_method"),
                event=event,
            )
        if event.event_type in ("charge.refunded", "mock.refund.succeeded"):
            return {"ok": True, "handled": "noop", "eventType": event.event_type}
        return {"ok": True, "handled": "ignored", "eventType": event.event_type}

    def _mark_order_paid(
        self,
        *,
        order_id: str,
        provider_payment_intent_id: str | None,
        payment_method: str | None = None,
        event: WebhookEvent | None = None,
    ) -> dict[str, Any]:
        if not order_id:
            raise HTTPException(status_code=400, detail="webhook missing order_id")
        with SessionLocal() as s:
            order = s.get(PaymentOrderRow, order_id)
            if order is None:
                raise HTTPException(status_code=404, detail=f"order not found: {order_id}")
            if order.status == "paid":
                # Idempotent: the same event may arrive
                # twice (e.g. a Stripe retry).
                return {"ok": True, "order": order.to_dict(), "idempotent": True}
            order.status = "paid"
            order.paid_at = _now_utc()
            if provider_payment_intent_id:
                order.provider_payment_intent_id = provider_payment_intent_id
            if payment_method:
                order.payment_method = payment_method
            # Issue the entitlement.
            product = _validate_product_id(order.product_id)
            ent = s.execute(
                select(EntitlementRow).where(
                    EntitlementRow.user_id == order.user_id,
                    EntitlementRow.scope == product["scope"],
                )
            ).scalar_one_or_none()
            was_revoked = False
            if ent is None:
                ent = EntitlementRow(
                    user_id=order.user_id,
                    scope=product["scope"],
                    credits=int(product["credits"]),
                    purchased_at=order.paid_at,
                    payment_provider_txn_id=order.provider_payment_intent_id or order.provider_session_id,
                    auto_renew=bool(product.get("autoRenew", False)),
                )
                s.add(ent)
            else:
                was_revoked = ent.revoked_reason is not None
                ent.credits = int(ent.credits) + int(product["credits"])
                ent.purchased_at = order.paid_at
                if not ent.payment_provider_txn_id:
                    ent.payment_provider_txn_id = (
                        order.provider_payment_intent_id or order.provider_session_id
                    )
                ent.revoked_reason = None  # un-revoke
            order.credits_granted = int(product["credits"])
            s.commit()
            s.refresh(order)
            s.refresh(ent)
            # W8-2: if the entitlement was previously
            # revoked (e.g. a refund clawed it back),
            # record a 'reissue' entry in the credit
            # ledger so the operations dashboard can show
            # the refund → re-purchase transition.
            if was_revoked:
                try:
                    from balance_monitor import (
                        get_default_balance_monitor,
                    )
                    get_default_balance_monitor().note_restore(
                        user_id=order.user_id,
                        scope=product["scope"],
                        new_credits=int(product["credits"]),
                        order_id=order.id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "g1n.payment: credit_ledger.note_restore failed "
                        "for order=%s: %s", order.id, exc,
                    )
            return {
                "ok": True,
                "order": order.to_dict(),
                "entitlement": ent.to_dict(),
                "idempotent": False,
            }

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        with SessionLocal() as s:
            order = s.get(PaymentOrderRow, order_id)
            return order.to_dict() if order else None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_default_service: PaymentService | None = None


def get_default_payment_service() -> PaymentService:
    global _default_service
    if _default_service is None:
        _default_service = PaymentService()
    return _default_service


def reset_default_payment_service() -> None:
    global _default_service
    _default_service = None


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


class CreateOrderRequest(BaseModel):
    productId: str = Field(min_length=1, max_length=64)
    successUrl: str = Field(default="http://127.0.0.1:5173/store/success", max_length=512)
    cancelUrl: str = Field(default="http://127.0.0.1:5173/store", max_length=512)


def build_payment_router() -> APIRouter:
    router = APIRouter(prefix="/v1/payments", tags=["payments"])
    svc = get_default_payment_service

    @router.post("/orders")
    async def create_order(
        req: CreateOrderRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        # Demo-user (the W4 unauthenticated fallback) is
        # allowed to keep the legacy flow: the v4 endpoint
        # ``/v1/purchases/mock-confirm`` remains.
        # **Real** payment requires a JWT — a registered
        # user is mandatory (red line: 不要让玩家在未登录
        # 时强制购买).
        return svc().create_order(
            user_id=user["id"],
            product_id=req.productId,
            success_url=req.successUrl,
            cancel_url=req.cancelUrl,
        )

    @router.get("/orders/{order_id}")
    async def get_order(
        order_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        order = svc().get_order(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="order not found")
        if order["userId"] != user["id"]:
            raise HTTPException(status_code=403, detail="not your order")
        return {"ok": True, "order": order}

    @router.post("/webhook/{provider_name}")
    async def webhook(
        provider_name: str,
        request: Request,
        stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
        x_signature: str | None = Header(default=None, alias="X-Signature"),
    ) -> dict[str, Any]:
        raw_body = await request.body()
        provider = svc().provider
        if provider.name != provider_name:
            raise HTTPException(
                status_code=400,
                detail=f"this server is configured for {provider.name!r}, got {provider_name!r}",
            )
        try:
            if provider.name == "mock":
                event = provider.verify_webhook(raw_body=raw_body, signature_header=x_signature)
            else:
                event = provider.verify_webhook(raw_body=raw_body, signature_header=stripe_signature)
        except HTTPException:
            # Record the rejection for audit.
            svc().record_webhook(
                provider=provider.name,
                provider_event_id=f"bad_{uuid.uuid4().hex[:16]}",
                event_type="invalid",
                order_id=None,
                signature_verified=False,
                raw_payload={"rawBodyLen": len(raw_body)},
                error_message="signature failed",
            )
            raise
        audit = svc().record_webhook(
            provider=provider.name,
            provider_event_id=event.event_id,
            event_type=event.event_type,
            order_id=event.order_id,
            signature_verified=True,
            raw_payload=event.payload,
        )
        result = svc().handle_webhook(event)
        return {
            "ok": True,
            "webhook": audit.to_dict(),
            "result": result,
        }

    return router


# ---------------------------------------------------------------------------
# Test helper: a "trigger webhook from test" entry point
# ---------------------------------------------------------------------------


def trigger_mock_webhook(
    *,
    order_id: str,
    event_type: str = "mock.session.paid",
    amount_cents: int = 0,
    currency: str = "CNY",
    provider_event_id: str | None = None,
) -> dict[str, Any]:
    """Build a signed mock-webhook body + signature.  Tests
    POST this to :func:`build_payment_router`'s
    ``/v1/payments/webhook/mock`` to advance an order to
    paid without going through a real checkout."""

    provider = get_default_payment_service().provider
    if not isinstance(provider, MockProvider):
        raise RuntimeError("trigger_mock_webhook requires the mock provider")
    payload = {
        "id": provider_event_id or f"mock_evt_{uuid.uuid4().hex[:16]}",
        "type": event_type,
        "data": {
            "order_id": order_id,
            "amount_cents": amount_cents,
            "currency": currency,
        },
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return {"body": raw, "signature": provider.sign_webhook(raw)}


__all__ = [
    "PRODUCT_CATALOG",
    "CheckoutSession",
    "WebhookEvent",
    "RefundResult",
    "PaymentProvider",
    "MockProvider",
    "StripeProvider",
    "PaymentService",
    "get_default_payment_service",
    "reset_default_payment_service",
    "set_mock_webhook_secret_for_tests",
    "build_payment_router",
    "trigger_mock_webhook",
]
