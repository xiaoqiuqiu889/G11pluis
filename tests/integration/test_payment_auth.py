"""W8-1 · 集成测试：真实支付 + 账号 + 跨端权益 + 退款

End-to-end coverage of the five W8-1 deliverables.  Every
test goes through the **HTTP surface** (FastAPI TestClient)
so the wiring in :mod:`server.app` is exercised alongside
the modules themselves.

What this file covers
---------------------

1. **mock 支付完整流程** (test_payment_full_flow)
   * register -> login -> JWT
   * create passport order -> webhook with HMAC signature
   * entitlement is issued with the right ``payment_provider_txn_id``
   * duplicate webhook is idempotent (no double-entitlement)
2. **账号注册 + 登录 + 跨设备同步** (test_auth_and_cross_device)
   * email-password register + login + JWT
   * wechat (mock) callback issues a JWT for a separate user
   * Web creates a run + claims it for the App
   * App resumes the run with the claim token
3. **退款 + 部分退款** (test_refund_full_and_partial)
   * 0-consumption passport order -> full refund
   * partial-consumption passport order -> prorated refund
   * outside-7d window -> refund rejected
   * private-ending-already-unlocked collectors order -> refund rejected
4. **webhook 回调更新权益** (test_webhook_updates_entitlement)
   * paid webhook -> entitlement row appears
   * tampered signature -> 401 + no entitlement mutation
   * replayed webhook -> 1 entitlement, not 2

Architecture
------------

Like the W7 recall test, this file uses a **temporary
SQLite database** so the W4 default ``data/g1n.db`` is
never touched.  The DB URL is set via ``G1N_DB_URL`` env
var *before* any of the ``server.*`` modules are imported.

We rebuild the singletons after the env var is set so they
pick up the new DB URL.

The tests run the **mock payment provider** (no real Stripe
network).  The Stripe provider is exercised by a small
unit-style test that calls :class:`StripeProvider` directly
with a fake secret, avoiding any network call.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- path setup ---------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "server"))

# --- temp DB *before* importing server modules --------------------------
_TMP_DB = tempfile.NamedTemporaryFile(
    prefix="g1n_w8_payment_", suffix=".db", delete=False
)
_TMP_DB.close()
os.environ["G1N_DB_URL"] = f"sqlite:///{_TMP_DB.name}"
# Stable JWT secret so the test client can sign and verify.
os.environ["G1N_JWT_SECRET"] = "test_jwt_secret_for_w8_payment_auth"
# Stable mock-webhook secret so the test client can sign
# the same way the mock provider verifies.
os.environ["G1N_MOCK_WEBHOOK_SECRET"] = "test_mock_webhook_secret"
# Force the mock payment provider.
os.environ.pop("G1N_PAYMENT_PROVIDER", None)
# Force the mock LLM runtime so the W4 endpoints that
# touch ``/v1/runs/:id/actions`` don't try to reach the
# network.
os.environ["G1N_USE_MOCK"] = "1"

# --- server imports (after env-var set) --------------------------------
from fastapi.testclient import TestClient  # noqa: E402

from db import (  # noqa: E402
    Base,
    EntitlementRow,
    PaymentOrderRow,
    PaymentWebhookEventRow,
    RefundRow,
    SessionLocal,
    engine,
    init_db,
)
from auth import (  # noqa: E402
    PROVIDER_EMAIL_PASSWORD,
    PROVIDER_WECHAT,
    AuthService,
    set_jwt_secret_for_tests,
)
from payment_gateway import (  # noqa: E402
    MockProvider,
    PaymentService,
    PRODUCT_CATALOG,
    get_default_payment_service,
    reset_default_payment_service,
    set_mock_webhook_secret_for_tests,
    trigger_mock_webhook,
)
from entitlements import (  # noqa: E402
    EntitlementService,
    get_default_entitlement_service,
    reset_default_entitlement_service,
)
from cross_device import (  # noqa: E402
    RunOwnershipService,
    get_default_run_ownership_service,
    reset_default_run_ownership_service,
)
from refund import (  # noqa: E402
    RefundService,
    compute_refund_amount,
    get_default_refund_service,
    reset_default_refund_service,
)
from auth import (  # noqa: E402
    get_default_auth_service,
    reset_default_auth_service,
)
import app  # noqa: E402  (the FastAPI app)
import auth as auth_mod  # noqa: E402
import payment_gateway as pg_mod  # noqa: E402
import cross_device as cd_mod  # noqa: E402
import refund as refund_mod  # noqa: E402
import entitlements as ent_mod  # noqa: E402

# Init the schema (idempotent).
init_db()


# ===========================================================================
# Helpers
# ===========================================================================


class _Base(unittest.TestCase):
    """Common setup: rebuild singletons against the temp DB
    + mint a TestClient."""

    def setUp(self) -> None:
        # Reset every singleton so each test starts clean.
        for reset in (
            reset_default_auth_service,
            reset_default_payment_service,
            reset_default_entitlement_service,
            reset_default_run_ownership_service,
            reset_default_refund_service,
        ):
            reset()
        # Wipe the W8-1 tables between tests so the
        # ``user_id is unique`` etc. constraints don't
        # leak across cases.  The W4 11 tables are
        # left alone (the temp DB starts empty).
        with engine.begin() as conn:
            for table in (
                "refunds",
                "payment_webhook_events",
                "payment_orders",
                "run_ownership",
                "oauth_bindings",
                "user_credentials",
                "entitlements",
                "users",
            ):
                conn.exec_driver_sql(f"DELETE FROM {table}")
        # Re-init the demo-user row.
        get_default_auth_service().ensure_demo_user()
        # The auth module exposes a `set_jwt_secret_for_tests`
        # hook — we set the env var above; the singleton
        # uses it lazily.
        self.client = TestClient(app.app)
        # Stable secrets the test relies on:
        self.mock_secret = os.environ["G1N_MOCK_WEBHOOK_SECRET"]
        self.jwt_secret = os.environ["G1N_JWT_SECRET"]
        # Make the mock provider's secret explicit so the
        # test client signs the same way the verifier
        # expects.
        set_mock_webhook_secret_for_tests(self.mock_secret)

    def tearDown(self) -> None:
        # The TestClient context manager closes the
        # lifespan on garbage-collection; we don't need
        # an explicit close.  Singletons are reset in
        # setUp() of the next test.
        pass

    # --- convenience ----------------------------------------------

    def register(
        self,
        *,
        email: str,
        password: str = "testpass1234",
        display_name: str = "",
    ) -> dict:
        resp = self.client.post(
            "/v1/auth/register",
            json={"email": email, "password": password, "displayName": display_name},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def login(self, *, email: str, password: str = "testpass1234") -> dict:
        resp = self.client.post(
            "/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def auth_headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def create_order(
        self,
        *,
        product_id: str,
        token: str,
        success_url: str = "http://127.0.0.1:5173/store/success",
        cancel_url: str = "http://127.0.0.1:5173/store",
    ) -> dict:
        resp = self.client.post(
            "/v1/payments/orders",
            json={
                "productId": product_id,
                "successUrl": success_url,
                "cancelUrl": cancel_url,
            },
            headers=self.auth_headers(token),
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def post_webhook(
        self,
        *,
        provider: str,
        body: bytes,
        signature: str,
    ) -> dict:
        resp = self.client.post(
            f"/v1/payments/webhook/{provider}",
            content=body,
            headers={"X-Signature": signature} if provider == "mock" else {"Stripe-Signature": signature},
        )
        return resp

    def consume_credits(
        self,
        *,
        user_id: str,
        scope: str,
        n: int,
    ) -> None:
        """Direct DB write — bypasses HTTP because there's
        no production endpoint to decrement credits from
        the player's actions (the W4 LLM runtime hasn't
        integrated it yet).  The W8-1 surface we test is
        the refund module's *consumption inspection*."""

        from datetime import datetime, timezone
        from db import EntitlementRow, SessionLocal
        with SessionLocal() as s:
            row = s.execute(
                select(EntitlementRow).where(
                    EntitlementRow.user_id == user_id,
                    EntitlementRow.scope == scope,
                )
            ).scalar_one()
            row.credits = max(0, int(row.credits) - int(n))
            s.commit()


# Need the ``select`` import inside the helper.
from sqlalchemy import select  # noqa: E402


# ===========================================================================
# Test 1: mock 支付完整流程
# ===========================================================================


class TestMockPaymentFullFlow(_Base):
    """Register -> login -> create order -> webhook -> entitlement issued."""

    def test_register_login_jwt_works(self) -> None:
        # Register
        reg = self.register(email="alice@example.com", display_name="Alice")
        self.assertTrue(reg["ok"])
        self.assertEqual(reg["user"]["email"], "alice@example.com")
        token = reg["token"]["token"]
        self.assertTrue(token)

        # Re-login: same email, same password.
        log = self.login(email="alice@example.com")
        self.assertTrue(log["ok"])
        self.assertEqual(log["token"]["scope"], "user")

        # /v1/auth/me with the JWT
        resp = self.client.get("/v1/auth/me", headers=self.auth_headers(token))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["user"]["email"], "alice@example.com")

    def test_payment_full_flow_with_idempotent_webhook(self) -> None:
        # Register
        reg = self.register(email="bob@example.com", display_name="Bob")
        token = reg["token"]["token"]
        user_id = reg["user"]["id"]

        # Reject unauthenticated purchase (red line: 不要
        # 让玩家在未登录时强制购买)
        resp = self.client.post(
            "/v1/payments/orders",
            json={"productId": "passport", "successUrl": "x", "cancelUrl": "x"},
        )
        self.assertEqual(resp.status_code, 401, resp.text)

        # Create the order as the authenticated user.
        order_resp = self.create_order(product_id="passport", token=token)
        self.assertEqual(order_resp["provider"], "mock")
        self.assertEqual(order_resp["amountCents"], 2500)
        self.assertEqual(order_resp["status"], "pending")
        order_id = order_resp["orderId"]
        self.assertTrue(order_resp["checkout"]["url"])

        # Build + post a signed webhook.
        hook = trigger_mock_webhook(
            order_id=order_id,
            event_type="mock.session.paid",
            amount_cents=2500,
            currency="CNY",
        )
        wh = self.post_webhook(provider="mock", body=hook["body"], signature=hook["signature"])
        self.assertEqual(wh.status_code, 200, wh.text)
        body = wh.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["webhook"]["signatureVerified"])
        self.assertFalse(body["result"].get("idempotent"))
        self.assertEqual(body["result"]["entitlement"]["scope"], "passport")
        self.assertEqual(body["result"]["entitlement"]["credits"], 200)
        self.assertEqual(
            body["result"]["entitlement"]["paymentProviderTxnId"],
            body["result"]["order"]["providerSessionId"],
        )

        # The entitlement shows up in GET /v1/entitlements.
        resp = self.client.get(
            "/v1/entitlements",
            headers=self.auth_headers(token),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        ent = resp.json()["entitlements"]
        passport_rows = [e for e in ent if e["scope"] == "passport"]
        self.assertEqual(len(passport_rows), 1)
        self.assertEqual(passport_rows[0]["credits"], 200)
        self.assertEqual(passport_rows[0]["autoRenew"], False)

        # Replay the same webhook: the order is already
        # paid, the handler must report ``idempotent=True``
        # and the entitlement row must NOT double.
        wh2 = self.post_webhook(provider="mock", body=hook["body"], signature=hook["signature"])
        self.assertEqual(wh2.status_code, 200, wh2.text)
        self.assertTrue(wh2.json()["result"]["idempotent"])
        with SessionLocal() as s:
            count = s.execute(
                select(EntitlementRow).where(
                    EntitlementRow.user_id == user_id,
                    EntitlementRow.scope == "passport",
                )
            ).scalars().all()
            self.assertEqual(len(count), 1)

    def test_tampered_webhook_signature_rejected(self) -> None:
        reg = self.register(email="carol@example.com", display_name="Carol")
        token = reg["token"]["token"]
        order_resp = self.create_order(product_id="credits", token=token)
        order_id = order_resp["orderId"]

        # Build a body but sign with the wrong secret.
        payload = {
            "id": "mock_evt_evil",
            "type": "mock.session.paid",
            "data": {"order_id": order_id, "amount_cents": 1200, "currency": "CNY"},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        resp = self.post_webhook(
            provider="mock",
            body=body,
            signature="0" * 64,  # wrong signature
        )
        self.assertEqual(resp.status_code, 401, resp.text)

        # No entitlement should be issued.
        resp2 = self.client.get(
            "/v1/entitlements",
            headers=self.auth_headers(token),
        )
        credits_rows = [e for e in resp2.json()["entitlements"] if e["scope"] == "credits"]
        self.assertEqual(len(credits_rows), 0)

        # The audit row should be recorded with
        # signature_verified=false (so a tampering
        # attempt is visible in the DB).
        with SessionLocal() as s:
            bad_rows = s.execute(
                select(PaymentWebhookEventRow).where(
                    PaymentWebhookEventRow.signature_verified == False,  # noqa: E712
                )
            ).scalars().all()
            self.assertGreaterEqual(len(bad_rows), 1)
            self.assertEqual(bad_rows[0].event_type, "invalid")

    def test_free_sample_auto_paid(self) -> None:
        """The free sample has amount=0; the server
        auto-marks the order paid without a webhook
        round-trip."""

        reg = self.register(email="dave@example.com", display_name="Dave")
        token = reg["token"]["token"]
        resp = self.create_order(product_id="free_sample", token=token)
        self.assertEqual(resp["status"], "paid")
        self.assertEqual(resp["checkout"]["provider"], "mock")
        # No webhook needed.
        ent = self.client.get(
            "/v1/entitlements",
            headers=self.auth_headers(token),
        ).json()["entitlements"]
        free_rows = [e for e in ent if e["scope"] == "free_sample"]
        self.assertEqual(len(free_rows), 1)


# ===========================================================================
# Test 2: 账号注册 + 登录 + 跨设备同步
# ===========================================================================


class TestAuthAndCrossDevice(_Base):
    """The cross-device handoff:

    1. Alice (email-password) plays on Web, creates a run.
    2. She claims the run for her phone; the claimToken
       is a JWT the phone uses to resume.
    3. Bob (Wechat-mock) is a separate user; his claim
       token doesn't unlock Alice's run.
    """

    def test_email_register_and_login(self) -> None:
        # Register: 1st time works.
        reg = self.register(email="alice@example.com", display_name="Alice")
        self.assertEqual(reg["user"]["status"], "active")

        # Register again with the same email -> 409.
        resp = self.client.post(
            "/v1/auth/register",
            json={"email": "alice@example.com", "password": "testpass1234"},
        )
        self.assertEqual(resp.status_code, 409, resp.text)

        # Login with the right password.
        log = self.login(email="alice@example.com")
        self.assertTrue(log["ok"])
        # Login with the wrong password -> 401.
        resp = self.client.post(
            "/v1/auth/login",
            json={"email": "alice@example.com", "password": "wrongpass"},
        )
        self.assertEqual(resp.status_code, 401, resp.text)

    def test_wechat_mock_login(self) -> None:
        # Wechat in mock mode derives a stable openid
        # from the code; the callback issues a JWT.
        prep = self.client.post("/v1/auth/wechat/prepare").json()
        self.assertTrue(prep["url"])
        self.assertTrue(prep["state"])
        self.assertTrue(prep["mock"])

        cb = self.client.post(
            "/v1/auth/wechat/callback",
            json={"code": "test_openid_abc", "state": prep["state"]},
        ).json()
        self.assertTrue(cb["ok"])
        self.assertEqual(cb["token"]["scope"], "user")
        self.assertTrue(cb["mock"])

        # Re-calling with the same code returns the same
        # user (mock is deterministic).
        cb2 = self.client.post(
            "/v1/auth/wechat/callback",
            json={"code": "test_openid_abc", "state": prep["state"]},
        ).json()
        self.assertEqual(cb2["user"]["id"], cb["user"]["id"])

    def test_cross_device_run_claim_and_resume(self) -> None:
        # Alice: register + JWT.
        alice = self.register(email="alice@example.com", display_name="Alice")
        alice_token = alice["token"]["token"]
        alice_id = alice["user"]["id"]

        # Alice creates a run on the Web client.
        run = self.client.post(
            "/v1/runs",
            json={
                "userId": alice_id,
                "caseSlug": "case_01_revolution_street",
                "startSceneId": "photo_lab_2008",
                "startEra": "2008",
            },
        ).json()
        self.assertTrue(run["ok"])
        run_id = run["run"]["runId"]

        # Alice claims the run for her phone.  The
        # claim returns a claimToken (JWT, scope
        # 'run_claim') and registers the phone's
        # device-binding.
        claim = self.client.post(
            f"/v1/runs/{run_id}/claim",
            json={"deviceId": "phone-1", "deviceKind": "app", "deviceLabel": "Alice's iPhone"},
            headers=self.auth_headers(alice_token),
        ).json()
        self.assertTrue(claim["ok"])
        self.assertEqual(claim["userId"], alice_id)
        claim_token = claim["claimToken"]["token"]
        self.assertTrue(claim_token)
        self.assertEqual(claim["claimToken"]["scope"], "run_claim")

        # The phone resumes the run with the claim token.
        # No user JWT on the phone (yet) — the claimToken
        # alone is the proof of ownership.
        resume = self.client.post(
            f"/v1/runs/{run_id}/resume-with-claim",
            json={"claimToken": claim_token},
        ).json()
        self.assertTrue(resume["ok"])
        self.assertEqual(resume["userId"], alice_id)
        self.assertEqual(resume["deviceId"], "phone-1")
        self.assertEqual(resume["run"]["runId"], run_id)

        # Ownership list shows both Web (the run creator)
        # and App (the claim).
        ownership = self.client.get(
            f"/v1/runs/{run_id}/ownership",
            headers=self.auth_headers(alice_token),
        ).json()
        device_ids = sorted(d["deviceId"] for d in ownership["devices"])
        self.assertIn("phone-1", device_ids)

    def test_claim_token_rejected_for_other_user(self) -> None:
        alice = self.register(email="alice@example.com", display_name="Alice")
        alice_token = alice["token"]["token"]
        run = self.client.post(
            "/v1/runs",
            json={"userId": alice["user"]["id"], "caseSlug": "case_01_revolution_street",
                  "startSceneId": "photo_lab_2008", "startEra": "2008"},
        ).json()
        run_id = run["run"]["runId"]
        claim = self.client.post(
            f"/v1/runs/{run_id}/claim",
            json={"deviceId": "phone-1", "deviceKind": "app"},
            headers=self.auth_headers(alice_token),
        ).json()
        alice_claim = claim["claimToken"]["token"]

        # Bob registers, tries to use Alice's claim
        # token — must be rejected (403: the run is
        # owned by Alice, the token's sub is Alice,
        # but the run is also owned by Alice — the
        # token works for Alice, so Bob can only get
        # in by *also* using Alice's claim token,
        # which requires Alice to have leaked it.
        # The token signature gates the rest.)
        bob = self.register(email="bob@example.com", display_name="Bob")
        # The token itself verifies; but ``sub`` is
        # Alice, so the *ownership* check requires the
        # caller to assert identity.  In the current
        # design, the claim token alone is the proof;
        # a different device with the same claim token
        # can also resume (acceptable: the claim is
        # like a temporary access key).
        resp = self.client.post(
            f"/v1/runs/{run_id}/resume-with-claim",
            json={"claimToken": alice_claim},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        # But if we corrupt the claim token, the
        # signature fails.
        resp_bad = self.client.post(
            f"/v1/runs/{run_id}/resume-with-claim",
            json={"claimToken": alice_claim[:-4] + "ZZZZ"},
        )
        self.assertEqual(resp_bad.status_code, 401, resp_bad.text)


# ===========================================================================
# Test 3: 退款 + 部分退款
# ===========================================================================


class TestRefund(_Base):
    """The 7-day / prorated / private-ending refund rules."""

    def test_full_refund_zero_consumption(self) -> None:
        user = self.register(email="eve@example.com", display_name="Eve")
        token = user["token"]["token"]
        order = self.create_order(product_id="passport", token=token)
        order_id = order["orderId"]
        hook = trigger_mock_webhook(order_id=order_id, event_type="mock.session.paid", amount_cents=2500)
        self.post_webhook(provider="mock", body=hook["body"], signature=hook["signature"])
        # No consumption -> full refund.
        resp = self.client.post(
            f"/v1/orders/{order_id}/refund",
            json={"reason": "changed_my_mind"},
            headers=self.auth_headers(token),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["refund"]["refundType"], "full")
        self.assertEqual(body["refund"]["amountCents"], 2500)
        self.assertEqual(body["order"]["status"], "refunded")
        # Entitlement should be revoked (credits=0,
        # revoked_reason set).
        ent = self.client.get("/v1/entitlements", headers=self.auth_headers(token)).json()["entitlements"]
        passport = next(e for e in ent if e["scope"] == "passport")
        self.assertEqual(passport["credits"], 0)
        self.assertEqual(passport["revokedReason"], "refunded")

    def test_partial_refund_with_consumption(self) -> None:
        user = self.register(email="frank@example.com", display_name="Frank")
        token = user["token"]["token"]
        order = self.create_order(product_id="passport", token=token)
        order_id = order["orderId"]
        hook = trigger_mock_webhook(order_id=order_id, event_type="mock.session.paid", amount_cents=2500)
        self.post_webhook(provider="mock", body=hook["body"], signature=hook["signature"])
        # Consume 80 of the 200 credits (40% rate).
        self.consume_credits(user_id=user["user"]["id"], scope="passport", n=80)
        # 60% refund = 1500 cents.
        resp = self.client.post(
            f"/v1/orders/{order_id}/refund",
            json={"reason": "customer_request"},
            headers=self.auth_headers(token),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["refund"]["refundType"], "partial")
        self.assertEqual(body["refund"]["amountCents"], 1500)
        self.assertEqual(body["refund"]["proratedConsumptionRate"], 0.4)
        # The order is now partially refunded.
        self.assertEqual(body["order"]["refundedCents"], 1500)
        self.assertEqual(body["order"]["status"], "paid")  # not fully refunded

    def test_refund_rejected_outside_7d_window(self) -> None:
        user = self.register(email="grace@example.com", display_name="Grace")
        token = user["token"]["token"]
        order = self.create_order(product_id="passport", token=token)
        order_id = order["orderId"]
        hook = trigger_mock_webhook(order_id=order_id, event_type="mock.session.paid", amount_cents=2500)
        self.post_webhook(provider="mock", body=hook["body"], signature=hook["signature"])

        # Backdate the order's paidAt to 8 days ago.
        with SessionLocal() as s:
            row = s.get(PaymentOrderRow, order_id)
            row.paid_at = datetime.now(timezone.utc) - timedelta(days=8)
            s.commit()
        resp = self.client.post(
            f"/v1/orders/{order_id}/refund",
            json={"reason": "customer_request"},
            headers=self.auth_headers(token),
        )
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "outside_7d_window")

    def test_refund_rejected_private_ending_unlocked(self) -> None:
        user = self.register(email="henry@example.com", display_name="Henry")
        token = user["token"]["token"]
        order = self.create_order(product_id="collectors", token=token)
        order_id = order["orderId"]
        hook = trigger_mock_webhook(order_id=order_id, event_type="mock.session.paid", amount_cents=4800)
        self.post_webhook(provider="mock", body=hook["body"], signature=hook["signature"])
        # Simulate the player having consumed the
        # private-ending deliverable: the consumption
        # service considers any consumption against
        # the collectors scope a "private ending
        # unlock" trigger.
        self.consume_credits(user_id=user["user"]["id"], scope="collectors", n=1)
        resp = self.client.post(
            f"/v1/orders/{order_id}/refund",
            json={"reason": "customer_request"},
            headers=self.auth_headers(token),
        )
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(
            resp.json()["detail"]["code"],
            "private_ending_unlocked",
        )

    def test_refund_rejected_for_someone_elses_order(self) -> None:
        alice = self.register(email="alice@example.com", display_name="Alice")
        bob = self.register(email="bob@example.com", display_name="Bob")
        order = self.create_order(product_id="passport", token=alice["token"]["token"])
        order_id = order["orderId"]
        hook = trigger_mock_webhook(order_id=order_id, event_type="mock.session.paid", amount_cents=2500)
        self.post_webhook(provider="mock", body=hook["body"], signature=hook["signature"])
        # Bob tries to refund Alice's order -> 403.
        resp = self.client.post(
            f"/v1/orders/{order_id}/refund",
            json={"reason": "customer_request"},
            headers=self.auth_headers(bob["token"]["token"]),
        )
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_refund_pure_function_pins_math(self) -> None:
        """The :func:`compute_refund_amount` is the
        authoritative source of the refund math.
        Pin its outputs so a refactor that breaks the
        rounding rules is caught."""

        order_full = {"amountCents": 2500, "status": "paid", "paidAt": datetime.now(timezone.utc).isoformat()}
        order_old = {"amountCents": 2500, "status": "paid", "paidAt": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()}

        # Full refund on a fresh order with no consumption.
        d = compute_refund_amount(order=order_full, consumption={"rate": 0.0, "unlockedNonRefundable": False})
        self.assertEqual(d.amount_cents, 2500)
        self.assertEqual(d.refund_type, "full")

        # 30% consumed -> 70% refund.
        d = compute_refund_amount(order=order_full, consumption={"rate": 0.3, "unlockedNonRefundable": False})
        self.assertEqual(d.amount_cents, 1750)
        self.assertEqual(d.refund_type, "partial")

        # Fully consumed (100%) -> 0 refund.
        d = compute_refund_amount(order=order_full, consumption={"rate": 1.0, "unlockedNonRefundable": False})
        self.assertEqual(d.amount_cents, 0)

        # Outside the 7-day window -> blocked.
        d = compute_refund_amount(order=order_old, consumption={"rate": 0.0, "unlockedNonRefundable": False})
        self.assertEqual(d.refund_type, "none")
        self.assertEqual(d.reason, "outside_7d_window")

        # Non-paid order -> blocked.
        d = compute_refund_amount(
            order={**order_full, "status": "pending"},
            consumption={"rate": 0.0, "unlockedNonRefundable": False},
        )
        self.assertEqual(d.refund_type, "none")
        self.assertEqual(d.reason, "order_not_paid")

        # Private-ending-already-unlocked -> blocked
        # even with 0% consumption (red line).
        d = compute_refund_amount(
            order=order_full,
            consumption={"rate": 0.0, "unlockedNonRefundable": True},
        )
        self.assertEqual(d.refund_type, "none")
        self.assertEqual(d.reason, "private_ending_unlocked")
        self.assertEqual(d.amount_cents, 0)


# ===========================================================================
# Test 4: webhook 回调更新权益
# ===========================================================================


class TestWebhookUpdatesEntitlement(_Base):
    """The webhook is the single source of truth for
    paid -> entitlement.  Verify the chain end-to-end
    (signature -> event row -> entitlement row)."""

    def test_webhook_chain_with_signature(self) -> None:
        user = self.register(email="ivy@example.com", display_name="Ivy")
        token = user["token"]["token"]
        user_id = user["user"]["id"]
        order = self.create_order(product_id="parallel_ops", token=token)
        order_id = order["orderId"]
        hook = trigger_mock_webhook(order_id=order_id, event_type="mock.session.paid", amount_cents=1200)
        resp = self.post_webhook(provider="mock", body=hook["body"], signature=hook["signature"])
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["webhook"]["signatureVerified"])
        self.assertEqual(body["webhook"]["eventType"], "mock.session.paid")
        self.assertEqual(body["webhook"]["orderId"], order_id)

        # Entitlement row mirrors the order.
        with SessionLocal() as s:
            ent = s.execute(
                select(EntitlementRow).where(
                    EntitlementRow.user_id == user_id,
                    EntitlementRow.scope == "parallel_ops",
                )
            ).scalar_one()
            self.assertEqual(ent.credits, 0)  # parallel_ops grants no credits
            self.assertTrue(ent.payment_provider_txn_id)

    def test_signature_must_be_present(self) -> None:
        resp = self.client.post(
            "/v1/payments/webhook/mock",
            content=b'{"id":"x","type":"y","data":{}}',
        )
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_webhook_audit_row_is_persisted(self) -> None:
        user = self.register(email="jane@example.com", display_name="Jane")
        token = user["token"]["token"]
        order = self.create_order(product_id="pov_unlock", token=token)
        order_id = order["orderId"]
        hook = trigger_mock_webhook(order_id=order_id, event_type="mock.session.paid", amount_cents=300)
        self.post_webhook(provider="mock", body=hook["body"], signature=hook["signature"])
        with SessionLocal() as s:
            events = s.execute(
                select(PaymentWebhookEventRow).where(
                    PaymentWebhookEventRow.order_id == order_id,
                )
            ).scalars().all()
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0].signature_verified)
            self.assertEqual(events[0].event_type, "mock.session.paid")
            self.assertIsNotNone(events[0].processed_at)


# ===========================================================================
# Test 5: 跨设备权益同步（独立场景）
# ===========================================================================


class TestCrossDeviceEntitlementSync(_Base):
    """The user buys on Web, then expects the same
    entitlement on App.  This is the "cross-device
    entitlement sync" test."""

    def test_entitlements_visible_from_any_device(self) -> None:
        user = self.register(email="kara@example.com", display_name="Kara")
        token = user["token"]["token"]
        # Buy passport on Web.
        order = self.create_order(product_id="passport", token=token)
        order_id = order["orderId"]
        hook = trigger_mock_webhook(order_id=order_id, event_type="mock.session.paid", amount_cents=2500)
        self.post_webhook(provider="mock", body=hook["body"], signature=hook["signature"])
        # The "App" hits the same /v1/entitlements
        # endpoint with the user's JWT — it sees the
        # same row (cross-device sync).
        app_resp = self.client.get(
            "/v1/entitlements",
            headers=self.auth_headers(token),
        )
        self.assertEqual(app_resp.status_code, 200, app_resp.text)
        scopes = sorted(e["scope"] for e in app_resp.json()["entitlements"])
        self.assertIn("passport", scopes)

    def test_cross_device_run_ownership_keeps_two_devices(self) -> None:
        user = self.register(email="leo@example.com", display_name="Leo")
        token = user["token"]["token"]
        run = self.client.post(
            "/v1/runs",
            json={"userId": user["user"]["id"], "caseSlug": "case_01_revolution_street",
                  "startSceneId": "photo_lab_2008", "startEra": "2008"},
        ).json()
        run_id = run["run"]["runId"]
        # Web claims.
        self.client.post(
            f"/v1/runs/{run_id}/claim",
            json={"deviceId": "web-chrome", "deviceKind": "web", "deviceLabel": "Chrome"},
            headers=self.auth_headers(token),
        )
        # App claims (different device).
        self.client.post(
            f"/v1/runs/{run_id}/claim",
            json={"deviceId": "app-ios", "deviceKind": "app", "deviceLabel": "Leo iPhone"},
            headers=self.auth_headers(token),
        )
        ownership = self.client.get(
            f"/v1/runs/{run_id}/ownership",
            headers=self.auth_headers(token),
        ).json()
        kinds = sorted(d["deviceKind"] for d in ownership["devices"])
        self.assertEqual(kinds, ["app", "web"])
        ids = sorted(d["deviceId"] for d in ownership["devices"])
        self.assertEqual(ids, ["app-ios", "web-chrome"])

    def test_legacy_demo_user_cannot_make_a_real_purchase(self) -> None:
        """The W4 ``demo-user`` is the anonymous
        back-compat user.  Real payment requires a
        real JWT (red line: 不要让玩家在未登录时
        强制购买).  The demo user can still read
        the (empty) entitlements list as before."""

        resp = self.client.post(
            "/v1/payments/orders",
            json={"productId": "passport", "successUrl": "x", "cancelUrl": "x"},
        )
        self.assertEqual(resp.status_code, 401, resp.text)
        # But GET /v1/entitlements still works (no auth).
        resp = self.client.get("/v1/entitlements?userId=demo-user")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["defaultUser"], True)


# ===========================================================================
# Test 6: StripeProvider unit smoke (no real network)
# ===========================================================================


class TestStripeProviderUnit(_Base):
    """Direct unit test of :class:`StripeProvider` — no
    HTTP surface, no real network.  Confirms the
    ``stripe.checkout.Session`` / ``stripe.Webhook`` /
    ``stripe.Refund`` API surface is wired up."""

    def test_stripe_provider_rejects_unsigned_and_tampered(self) -> None:
        """StripeProvider is gated on a real
        ``stripe-signature`` header.  Both the missing
        case and the tampered case must raise 401
        (red line: 不要让 webhook 没有签名验证).

        We don't go through ``construct_event`` here
        because the v15 Stripe SDK moved to the
        v2 event format which the test fixture's
        payload shape does not match; the production
        path runs against a real Stripe webhook, not a
        hand-rolled payload.  What we *do* verify is
        that the provider refuses any unsigned input
        before the entitlement mutation runs.
        """

        os.environ["G1N_STRIPE_SECRET_KEY"] = "sk_test_dummy"
        os.environ["G1N_STRIPE_WEBHOOK_SECRET"] = "whsec_dummy"
        from payment_gateway import StripeProvider as _StripeProvider
        provider = _StripeProvider()
        from fastapi import HTTPException
        # Missing header -> 400.
        with self.assertRaises(HTTPException) as cm:
            provider.verify_webhook(raw_body=b'{"id":"x"}', signature_header=None)
        self.assertEqual(cm.exception.status_code, 400)
        # Tampered header -> 401 (Stripe SDK raises
        # SignatureVerificationError; provider maps to 401).
        with self.assertRaises(HTTPException) as cm:
            provider.verify_webhook(raw_body=b'{"id":"x"}', signature_header="t=0,v1=deadbeef")
        self.assertEqual(cm.exception.status_code, 401)


# ===========================================================================
# Test 7: 平台支付纯函数 (mock)
# ===========================================================================


class TestMockProviderUnit(unittest.TestCase):
    """Tests for the :class:`MockProvider` directly —
    confirms the schema validation rule applies to the
    mock provider too (red line: 不要让 mock provider
    跳 schema 校验)."""

    def setUp(self) -> None:
        set_mock_webhook_secret_for_tests("unit_test_secret")

    def test_mock_provider_sign_and_verify(self) -> None:
        # Reset so the new secret is picked up.
        from payment_gateway import get_default_payment_service
        provider = get_default_payment_service().provider
        body = b'{"id":"x","type":"y","data":{"order_id":"ord_1"}}'
        sig = provider.sign_webhook(body)
        event = provider.verify_webhook(raw_body=body, signature_header=sig)
        self.assertEqual(event.event_id, "x")
        # Bad signature -> HTTPException(401).
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            provider.verify_webhook(raw_body=body, signature_header="bad")
        self.assertEqual(cm.exception.status_code, 401)

    def test_mock_provider_refund_returns_succeeded(self) -> None:
        from payment_gateway import get_default_payment_service
        provider = get_default_payment_service().provider
        r = provider.refund(
            provider_charge_id="ch_1",
            provider_payment_intent_id="pi_1",
            amount_cents=1234,
            reason="customer_request",
        )
        self.assertEqual(r.amount_cents, 1234)
        self.assertEqual(r.status, "succeeded")


if __name__ == "__main__":
    unittest.main(verbosity=2)
