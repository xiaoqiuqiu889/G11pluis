"""FastAPI entry point — the G1N (革命街 AI 原生) HTTP server.

W4 deliverable: the runtime that exposes the 13
brief-mandated endpoints and ties the engine + agents +
persistence + LLM runtime together.  All mutations go
through the ResolverAgent (write-domain isolation; the
HTTP layer **never** writes to canonical state directly).

Endpoint map (v1)
-----------------

+--------------------------------------------+------------------------+
| Method + Path                              | Purpose                |
+============================================+========================+
| GET  /health                               | liveness + DB ping     |
+--------------------------------------------+------------------------+
| GET  /v1/catalog                           | product catalog        |
+--------------------------------------------+------------------------+
| GET  /v1/entitlements                      | user entitlements      |
+--------------------------------------------+------------------------+
| POST /v1/purchases/mock-confirm            | mock purchase          |
+--------------------------------------------+------------------------+
| POST /v1/runs                              | create run             |
+--------------------------------------------+------------------------+
| GET  /v1/runs/:runId                       | read run               |
+--------------------------------------------+------------------------+
| POST /v1/runs/:runId/scenes/:sceneId/enter | enter scene            |
+--------------------------------------------+------------------------+
| POST /v1/runs/:runId/actions               | player action (core)   |
+--------------------------------------------+------------------------+
| GET  /v1/runs/:runId/timeline              | event timeline         |
+--------------------------------------------+------------------------+
| GET  /v1/runs/:runId/archive               | archive (artifacts,    |
|                                            | beliefs, memories,     |
|                                            | seeds, branches)       |
+--------------------------------------------+------------------------+
| POST /v1/runs/:runId/branches              | create branch          |
+--------------------------------------------+------------------------+
| GET  /v1/runs/:runId/branches              | list branches          |
+--------------------------------------------+------------------------+
| POST /v1/runs/:runId/resume                | resume (hydrate)       |
+--------------------------------------------+------------------------+
| GET  /v1/runs/:runId/snapshot              | latest WorldSnapshot   |
+--------------------------------------------+------------------------+
| GET  /v1/scenes/:sceneId                   | scene metadata         |
+--------------------------------------------+------------------------+
| POST /v1/analytics/events                  | analytics event sink   |
+--------------------------------------------+------------------------+
| GET  /                                     | HTML landing page      |
+--------------------------------------------+------------------------+

Run with::

    python -m server.app
    # or
    uvicorn server.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

# ---- server package import shim -----------------------------------------
# The engine / agents / model packages are siblings of
# ``server``.  When the app is launched via
# ``python -m server.app`` (or ``uvicorn server.app:app``)
# the working directory is the project root, so the engine
# packages are importable.  When launched from ``server/`` the
# engine packages are siblings of ``app.py`` (and the engine
# imports in those modules use bare names like
# ``from engine.types import ...``), so we add the project
# root *and* the server directory to ``sys.path``.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
for p in (_PROJECT_ROOT, _SERVER_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# Now safe to import the engine / agents / model packages
from action_runner import ActionRunner, TurnResult, get_default_runner  # noqa: E402
from db import healthcheck, init_db  # noqa: E402
from llm_runtime import get_default_runtime  # noqa: E402
from repository import RunRepository, get_default_repository  # noqa: E402
from run_registry import RunRegistry, get_default_registry  # noqa: E402
from scene_loader import (  # noqa: E402
    SCENES_IN_ORDER,
    CASE_SLUG_DEFAULT,
    CASE_REGISTRY,
    SceneContractLoader,
    get_default_loader,
    get_case_meta,
    list_cases,
)

logger = logging.getLogger("g1n.app")

# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialise DB + singletons at startup; release at shutdown."""

    logging.basicConfig(
        level=os.environ.get("G1N_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    )
    logger.info("g1n.app: starting up (project_root=%s)", _PROJECT_ROOT)
    init_db()
    # W7: create the recall_items table (idempotent, no-op on repeat).
    try:
        from recall_service import init_recall_tables
        init_recall_tables()
    except Exception as exc:  # noqa: BLE001
        # The table is a W7 add-on; the rest of the server
        # must keep working even if the import fails (e.g. a
        # partial checkout).  Log loudly so the operator
        # can see the regression.
        logger.warning("g1n.app: init_recall_tables() failed: %s", exc)
    # Warm the singletons so the first request doesn't pay the cold-start cost.
    get_default_loader()
    get_default_repository()
    get_default_registry()
    runtime = get_default_runtime()
    logger.info("g1n.app: runtime ready providers=%s", runtime.provider_names)
    app.state.started_at = time.time()
    yield
    logger.info("g1n.app: shutting down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


app = FastAPI(
    title="革命街 AI 原生 · 服务端",
    version="1.0.0",
    description=(
        "《革命街没有尽头》AI 原生重构版 — W4 部署服务端。\n\n"
        "所有 mutating 端点都通过 ResolverAgent（决策 1+3+5+6 的统一执行点），"
        "符合 brief 的写域隔离约束。默认 mock LLM 模式不需要任何 API key。"
    ),
    lifespan=_lifespan,
)

# CORS — the Electron dev server (port 5173) is the primary client
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("G1N_CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


# ---------------------------------------------------------------------------
# W7 留存机制 — 召回 + 推送 router
# ---------------------------------------------------------------------------
#
# The push router mounts ``/v1/recall/{schedule,pending,mark-read,tick}`` on
# the same FastAPI app.  W4's `/v1/analytics/events` endpoint already
# accepts arbitrary event names, so the W7 funnel
# (`recall_d1_sent` ... `recap_completed`) rides the same sink — no new
# table needed for the analytics side.  The W7-specific row
# (`recall_items`) lives in `server/recall_service.py`; its table is
# created by `init_recall_tables()` in the lifespan above.
try:
    from push_service import build_push_router
    app.include_router(build_push_router())
    logger.info("g1n.app: W7 push router mounted at /v1/recall/*")
except Exception as exc:  # noqa: BLE001
    # Same policy as the lifespan init: W7 is an add-on, the W4
    # server must keep running even if a partial checkout broke
    # the import.  Log loudly so the regression is visible.
    logger.warning("g1n.app: W7 push router mount failed: %s", exc)


# ---------------------------------------------------------------------------
# W8-1 — 真实支付 + 账号 + 跨端权益
# ---------------------------------------------------------------------------
#
# The W4 server shipped with a single ``/v1/purchases/mock-confirm``
# endpoint that wrote a synthetic entitlement row.  W8-1 adds the real
# payment + auth + cross-device surfaces (5 new modules under
# ``server/``).  All W4 routes continue to work — the W8-1 routers
# live under ``/v1/auth/*``, ``/v1/payments/*``,
# ``/v1/entitlements/sync``, ``/v1/runs/:id/claim`` and
# ``/v1/orders/:id/refund`` (paths that don't collide with W4).
#
# Mount policy: the W8-1 modules are the W8-1 brief's required
# deliverable, so a missing import here is a *hard* failure — we
# do not silently swallow it the way we do for the W7 add-on.
# W8-1 has its own integration test
# (``tests/integration/test_payment_auth.py``) that will surface
# any regression.
for _w81_module, _w81_router in (
    ("auth", "build_auth_router"),
    ("payment_gateway", "build_payment_router"),
    ("entitlements", "build_entitlements_router"),
    ("cross_device", "build_cross_device_router"),
    ("refund", "build_refund_router"),
):
    try:
        import importlib
        _mod = importlib.import_module(_w81_module)
        app.include_router(getattr(_mod, _w81_router)())
        logger.info("g1n.app: W8-1 router mounted: %s.%s", _w81_module, _w81_router)
    except Exception as exc:  # noqa: BLE001
        # W8-1 is a brief-required deliverable; a missing
        # import is a hard error.  Re-raise so the operator
        # notices immediately.
        logger.error("g1n.app: W8-1 router mount failed: %s.%s: %s", _w81_module, _w81_router, exc)
        raise


# ---------------------------------------------------------------------------
# W8-2 — BYOK 自接 API + 余额监控 + LLM runtime 串联
# ---------------------------------------------------------------------------
#
# W8-1 left three gaps (see W8-1-report.md §6):
#   1. consume_credits is not wired into the LLM runtime
#   2. payment_webhook_events has no query endpoint
#   3. Refund doesn't reset credits on re-purchase
#
# W8-2 closes all three:
#   * `byok`     — encrypted BYOK key store + provider
#   * `balance_monitor` — credit / cost / degradation centre
#   * `llm_runtime.request_llm_call` — the engine-layer entry point
#     that consults the balance monitor + consume_credits + the
#     LLM gateway in one shot
#   * the two new ``/v1/operations/payments/*`` endpoints
#     (``webhooks`` + ``refunds``) close the dashboard gap
#
# Mount policy: the W8-2 modules are the W8-2 brief's required
# deliverable, so a missing import here is a *hard* failure
# (same policy as W8-1 above).
for _w82_module, _w82_router in (
    ("byok", "build_byok_router"),
    ("balance_monitor", "build_balance_router"),
):
    try:
        import importlib
        _mod = importlib.import_module(_w82_module)
        app.include_router(getattr(_mod, _w82_router)())
        logger.info("g1n.app: W8-2 router mounted: %s.%s", _w82_module, _w82_router)
    except Exception as exc:  # noqa: BLE001
        logger.error("g1n.app: W8-2 router mount failed: %s.%s: %s", _w82_module, _w82_router, exc)
        raise


# ---------------------------------------------------------------------------
# W8-2 — payment_webhook_events / refunds dashboard query
# ---------------------------------------------------------------------------
#
# The W8-1 brief said the webhook events table exists but
# ``no query endpoint``.  W8-2 adds two:
#
#   * GET /v1/operations/payments/webhooks?window=7d
#     — webhook events for the last N days, optionally
#       filtered by ``provider`` / ``event_type`` /
#       ``signature_verified`` (the audit-trail use case).
#   * GET /v1/operations/payments/refunds?window=7d
#     — refund rows for the last N days, plus a small
#       aggregate (total amount, count by status) so the
#       Grafana dashboard can show a refund spike without
#       pulling a separate metric endpoint.
#
# Both are mounted under ``/v1/operations`` so they sit
# next to the W10 analytics warehouse routes that the
# existing Grafana dashboard already talks to.
try:
    from fastapi import Query
    from sqlalchemy import func, select

    from db import (
        PaymentOrderRow,
        PaymentWebhookEventRow,
        RefundRow,
        SessionLocal,
    )

    @app.get("/v1/operations/payments/webhooks")
    async def operations_payment_webhooks(
        window: str = Query(default="7d", max_length=16),
        provider: str | None = Query(default=None, max_length=32),
        event_type: str | None = Query(default=None, max_length=64),
        signature_verified: bool | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        """List recent webhook events for ops / dashboard.

        The default window matches the Grafana ``time`` picker
        (now-7d).  ``signature_verified=false`` rows are
        tampering attempts — they show up so the operator
        can investigate, but the dashboard panel highlights
        them red.
        """

        # Reuse the analytics-warehouse window parser so
        # ``7d`` / ``24h`` / ``30m`` all behave the same.
        from analytics_warehouse import _parse_window, _humanize_window
        try:
            td = _parse_window(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        since = datetime.now(timezone.utc) - td
        with SessionLocal() as s:
            stmt = select(PaymentWebhookEventRow).where(
                PaymentWebhookEventRow.received_at >= since
            )
            if provider:
                stmt = stmt.where(PaymentWebhookEventRow.provider == provider)
            if event_type:
                stmt = stmt.where(PaymentWebhookEventRow.event_type == event_type)
            if signature_verified is not None:
                stmt = stmt.where(
                    PaymentWebhookEventRow.signature_verified == bool(signature_verified)
                )
            stmt = stmt.order_by(PaymentWebhookEventRow.received_at.desc()).limit(limit)
            rows = s.execute(stmt).scalars().all()
            # Aggregate counts (over the same filter) so
            # the dashboard can show a tampering spike
            # without pulling a second query.
            aggregate_stmt = select(
                PaymentWebhookEventRow.signature_verified,
                PaymentWebhookEventRow.event_type,
                func.count(PaymentWebhookEventRow.id),
            ).where(PaymentWebhookEventRow.received_at >= since)
            if provider:
                aggregate_stmt = aggregate_stmt.where(
                    PaymentWebhookEventRow.provider == provider
                )
            aggregate_stmt = aggregate_stmt.group_by(
                PaymentWebhookEventRow.signature_verified,
                PaymentWebhookEventRow.event_type,
            )
            agg_rows = s.execute(aggregate_stmt).all()
        return {
            "ok": True,
            "window": _humanize_window(td),
            "since": since.isoformat(),
            "count": len(rows),
            "events": [r.to_dict() for r in rows],
            "aggregate": [
                {
                    "signatureVerified": bool(sv),
                    "eventType": et,
                    "count": int(c),
                }
                for sv, et, c in agg_rows
            ],
        }

    @app.get("/v1/operations/payments/refunds")
    async def operations_payment_refunds(
        window: str = Query(default="7d", max_length=16),
        refund_type: str | None = Query(default=None, max_length=16),
        status: str | None = Query(default=None, max_length=16),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        """List recent refund rows + a small aggregate for the
        Grafana refund panel."""

        from analytics_warehouse import _parse_window, _humanize_window
        try:
            td = _parse_window(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        since = datetime.now(timezone.utc) - td
        with SessionLocal() as s:
            stmt = (
                select(RefundRow, PaymentOrderRow.product_id, PaymentOrderRow.amount_cents)
                .join(PaymentOrderRow, RefundRow.order_id == PaymentOrderRow.id, isouter=True)
                .where(RefundRow.requested_at >= since)
            )
            if refund_type:
                stmt = stmt.where(RefundRow.refund_type == refund_type)
            if status:
                stmt = stmt.where(RefundRow.status == status)
            stmt = stmt.order_by(RefundRow.requested_at.desc()).limit(limit)
            rows = s.execute(stmt).all()
            # Aggregate — total amount + count by status
            # + count by refund_type for the dashboard.
            agg = s.execute(
                select(
                    RefundRow.status,
                    RefundRow.refund_type,
                    func.count(RefundRow.id),
                    func.coalesce(func.sum(RefundRow.amount_cents), 0),
                )
                .where(RefundRow.requested_at >= since)
                .group_by(RefundRow.status, RefundRow.refund_type)
            ).all()
        refunds: list[dict[str, Any]] = []
        for refund, product_id, order_amount_cents in rows:
            d = refund.to_dict()
            d["productId"] = product_id
            d["orderAmountCents"] = int(order_amount_cents) if order_amount_cents is not None else None
            refunds.append(d)
        return {
            "ok": True,
            "window": _humanize_window(td),
            "since": since.isoformat(),
            "count": len(refunds),
            "refunds": refunds,
            "aggregate": [
                {
                    "status": st,
                    "refundType": rt_,
                    "count": int(c),
                    "amountCents": int(a or 0),
                }
                for st, rt_, c, a in agg
            ],
        }

    logger.info("g1n.app: W8-2 operations dashboard routes mounted: /v1/operations/payments/*")
except Exception as exc:  # noqa: BLE001
    # Same policy as the lifespan init: missing module is a
    # hard error for W8-2 (the brief lists this dashboard
    # route as required).
    logger.error("g1n.app: W8-2 operations dashboard mount failed: %s", exc)
    raise


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class CreateRunRequest(BaseModel):
    userId: str = Field(default="demo-user", min_length=1, max_length=64)
    caseSlug: str = Field(default="case_01_revolution_street", min_length=1, max_length=64)
    startSceneId: str = Field(default="photo_lab_2008", min_length=1, max_length=64)
    startEra: str = Field(default="2008", min_length=1, max_length=64)


class ActionRequest(BaseModel):
    """The body shape for POST /v1/runs/:runId/actions.

    Mirrors the brief: runId, sceneId, clientActionId,
    expectedEventSequence, the player-action JSON, and the
    client version.
    """

    runId: str = Field(..., min_length=1, max_length=64)
    sceneId: str = Field(..., min_length=1, max_length=64)
    clientActionId: str = Field(..., min_length=1, max_length=128)
    expectedEventSequence: int = Field(default=0, ge=0)
    playerAction: dict[str, Any] = Field(..., description="PlayerAction JSON (8 schema fields)")
    clientVersion: str | None = Field(default=None, max_length=32)

    @field_validator("playerAction")
    @classmethod
    def _check_player_action(cls, v: dict[str, Any]) -> dict[str, Any]:
        required = {"actionType", "actorId"}
        missing = required - v.keys()
        if missing:
            raise ValueError(f"playerAction missing fields: {sorted(missing)}")
        return v


class EnterSceneRequest(BaseModel):
    userId: str = Field(default="demo-user", min_length=1, max_length=64)
    startEra: str | None = Field(default=None, max_length=64)


class CreateBranchRequest(BaseModel):
    sourceRunId: str = Field(..., min_length=1, max_length=64)
    forkEventSequence: int = Field(..., ge=0)
    label: str = Field(default="", max_length=128)
    branchId: str | None = Field(default=None, max_length=64)


class ResumeRequest(BaseModel):
    userId: str = Field(default="demo-user", min_length=1, max_length=64)
    targetSceneId: str | None = Field(default=None, max_length=64)


class MockConfirmRequest(BaseModel):
    userId: str = Field(default="demo-user", min_length=1, max_length=64)
    productId: str = Field(..., min_length=1, max_length=64)
    credits: int = Field(default=0, ge=0)
    meta: dict[str, Any] = Field(default_factory=dict)


class AnalyticsEventRequest(BaseModel):
    userId: str | None = Field(default=None, max_length=64)
    runId: str | None = Field(default=None, max_length=64)
    eventName: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    clientVersion: str | None = Field(default=None, max_length=32)


# ---------------------------------------------------------------------------
# Product catalog (decision 4)
# ---------------------------------------------------------------------------


PRODUCT_CATALOG: list[dict[str, Any]] = [
    {
        "id": "free_sample",
        "name": "免费样章",
        "priceCents": 0,
        "currency": "CNY",
        "description": "序章 + 三场景缩略（每场 5 分钟）+ 1 次 mandatory echo。",
        "includes": ["序章", "三场景缩略", "1 次 mandatory echo"],
        "availableFromState": ["idle", "unlocked"],
        "unavailableDuring": [],
        "cta": "免费开始",
        "iconKey": "free",
    },
    {
        "id": "passport",
        "name": "案件通行证",
        "priceCents": 2500,
        "currency": "CNY",
        "description": "纵切片完整三场景 + 2 次重演 + 200 积分。",
        "includes": ["完整三场景", "2 次重演", "200 积分"],
        "availableFromState": ["scene_ended", "act_ended", "unlocked"],
        "unavailableDuring": ["scene_active"],
        "cta": "¥25 拿下",
        "iconKey": "passport",
    },
    {
        "id": "collectors",
        "name": "收藏版",
        "priceCents": 4800,
        "currency": "CNY",
        "description": "完整三场景 + 双视角 + 原声 + 私人终章 + 500 积分。",
        "includes": ["完整三场景", "双视角", "原声", "私人终章", "500 积分"],
        "availableFromState": ["scene_ended", "act_ended", "unlocked"],
        "unavailableDuring": ["scene_active"],
        "cta": "¥48 拿下",
        "iconKey": "collectors",
    },
    {
        "id": "parallel_ops",
        "name": "平行演算包",
        "priceCents": 1200,
        "currency": "CNY",
        "description": "5 次额外重演。",
        "includes": ["5 次额外重演"],
        "availableFromState": ["scene_ended", "act_ended", "unlocked"],
        "unavailableDuring": ["scene_active"],
        "cta": "¥12 拿下",
        "iconKey": "parallel",
    },
    {
        "id": "credits",
        "name": "积分包",
        "priceCents": 1200,
        "currency": "CNY",
        "description": "150 次主调用。",
        "includes": ["150 次主调用"],
        "availableFromState": ["idle", "scene_ended", "act_ended", "unlocked"],
        "unavailableDuring": [],
        "cta": "¥12 拿下",
        "iconKey": "credits",
    },
    {
        "id": "pov_unlock",
        "name": "额外人物视角",
        "priceCents": 300,
        "currency": "CNY",
        "description": "1 段额外人物视角。决策 2：付费解锁视角，记忆账本 + 情绪演出 + NPC 内心独白同时变化。",
        "includes": ["1 段人物视角"],
        "availableFromState": ["scene_ended", "act_ended", "unlocked"],
        "unavailableDuring": ["scene_active"],
        "cta": "¥3 拿下",
        "iconKey": "pov",
    },
    {
        "id": "keepsake",
        "name": "私人纪念品",
        "priceCents": 800,
        "currency": "CNY",
        "description": "本局专属信件 + 照片 + 关系报告（可导出）。",
        "includes": ["专属信件", "照片集", "关系报告"],
        "availableFromState": ["run_ended", "unlocked"],
        "unavailableDuring": ["scene_active", "scene_ended", "act_ended"],
        "cta": "¥8 拿下",
        "iconKey": "keepsake",
    },
]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness + DB ping.  The brief-mandated pingServer()."""

    db_health = healthcheck()
    return {
        "status": "ok",
        "service": "g1n-server",
        "version": app.version,
        "uptimeSeconds": int(time.time() - app.state.started_at) if hasattr(app.state, "started_at") else 0,
        "database": db_health,
        "llm": get_default_runtime().to_dict(),
        "activeRuns": get_default_registry().active_count,
    }


# ---------------------------------------------------------------------------
# Catalog + entitlements + purchases + analytics
# ---------------------------------------------------------------------------


@app.get("/v1/catalog")
async def get_catalog() -> dict[str, Any]:
    return {
        "products": PRODUCT_CATALOG,
        "currency": "CNY",
        "version": "1.0.0",
    }


@app.get("/v1/entitlements")
async def get_entitlements(
    userId: str = Query(default="demo-user", min_length=1, max_length=64),
) -> dict[str, Any]:
    repo = get_default_repository()
    items = repo.get_entitlements(userId)
    return {
        "userId": userId,
        "entitlements": items,
        "defaultUser": userId == "demo-user",
    }


@app.post("/v1/purchases/mock-confirm")
async def purchases_mock_confirm(req: MockConfirmRequest) -> dict[str, Any]:
    repo = get_default_repository()
    # Idempotency: the meta carries the receipt id so a re-POST
    # returns the same entitlement row.
    receipt_id = (req.meta or {}).get("receiptId") or str(uuid.uuid4())
    existing_scope = req.productId
    result = repo.upsert_entitlement(
        user_id=req.userId,
        scope=existing_scope,
        credits=req.credits,
        meta={"receiptId": receipt_id, "productId": req.productId, **(req.meta or {})},
    )
    return {
        "ok": True,
        "userId": req.userId,
        "productId": req.productId,
        "entitlement": result,
        "receiptId": receipt_id,
    }


@app.post("/v1/analytics/events")
async def analytics_events(req: AnalyticsEventRequest) -> dict[str, Any]:
    repo = get_default_repository()
    rec = repo.record_analytics(req.model_dump())
    return {"ok": True, "event": rec}


# ---------------------------------------------------------------------------
# Runs: create / read / resume / snapshot
# ---------------------------------------------------------------------------


@app.post("/v1/runs")
async def create_run(req: CreateRunRequest) -> dict[str, Any]:
    repo = get_default_repository()
    run = repo.create_run(
        user_id=req.userId,
        case_slug=req.caseSlug,
        start_scene_id=req.startSceneId,
        start_era=req.startEra,
    )
    # Eagerly open the in-memory active state.
    registry = get_default_registry()
    registry.open(run["runId"], case_slug=req.caseSlug, default_scene_id=req.startSceneId)
    return {
        "ok": True,
        "run": run,
    }


@app.get("/v1/runs/{run_id}")
async def get_run(run_id: str = Path(..., min_length=1, max_length=64)) -> dict[str, Any]:
    repo = get_default_repository()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return run.to_dict()


@app.get("/v1/runs/{run_id}/snapshot")
async def get_snapshot(run_id: str = Path(..., min_length=1, max_length=64)) -> dict[str, Any]:
    repo = get_default_repository()
    snap = repo.get_latest_snapshot(run_id)
    if snap is None:
        # Lazy-create a snapshot for runs that have never had a turn
        # (so the client can hydrate even before the first action).
        registry = get_default_registry()
        try:
            active = registry.open(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "runId": run_id,
            "snapshot": active.snapshot.to_dict(),
            "source": "in-memory",
        }
    return {"runId": run_id, "snapshot": snap, "source": "persisted"}


@app.post("/v1/runs/{run_id}/resume")
async def resume_run(
    req: ResumeRequest,
    run_id: str = Path(..., min_length=1, max_length=64),
) -> dict[str, Any]:
    """Re-hydrate the in-memory active-run state from the database.

    Decision 4 / brief: '续玩' = player connects back to an
    existing run.  We rebuild the in-memory cache from the
    persisted snapshot; the client then resumes with no
    loss of state.
    """

    repo = get_default_repository()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    registry = get_default_registry()
    target_scene = req.targetSceneId or run.current_scene_id
    active = registry.open(run_id, default_scene_id=target_scene)
    if target_scene != active.snapshot.canonicalState.currentSceneId:
        active = registry.transition_to_scene(
            run_id, new_scene_id=target_scene
        )
    return {
        "ok": True,
        "runId": run_id,
        "active": {
            "sceneId": active.snapshot.canonicalState.currentSceneId,
            "era": active.snapshot.canonicalState.era,
            "eventSequence": active.snapshot.eventSequence,
            "phase": active.snapshot.canonicalState.phase,
        },
    }


# ---------------------------------------------------------------------------
# Scenes: enter + meta
# ---------------------------------------------------------------------------


@app.post("/v1/runs/{run_id}/scenes/{scene_id}/enter")
async def enter_scene(
    run_id: str = Path(..., min_length=1, max_length=64),
    scene_id: str = Path(..., min_length=1, max_length=64),
    req: EnterSceneRequest = Body(default_factory=EnterSceneRequest),
) -> dict[str, Any]:
    repo = get_default_repository()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    loader = get_default_loader()
    # W12: case-aware — use the case the run was created with.
    case_slug = getattr(run, "case_slug", CASE_SLUG_DEFAULT) or CASE_SLUG_DEFAULT
    scene = loader.load_scene(case_slug, scene_id)
    registry = get_default_registry()
    active = registry.open(run_id, default_scene_id=scene_id)
    if active.snapshot.canonicalState.currentSceneId != scene_id:
        active = registry.transition_to_scene(
            run_id,
            new_scene_id=scene_id,
            new_era=req.startEra or scene.era,
        )
    repo.update_run_meta(
        run_id,
        current_scene_id=scene_id,
        era=req.startEra or scene.era,
        phase="setup",
    )
    return {
        "ok": True,
        "runId": run_id,
        "sceneId": scene_id,
        "scene": loader.scene_meta_for(case_slug, scene_id),
        "active": {
            "sceneId": active.snapshot.canonicalState.currentSceneId,
            "era": active.snapshot.canonicalState.era,
            "eventSequence": active.snapshot.eventSequence,
            "phase": active.snapshot.canonicalState.phase,
        },
    }


@app.get("/v1/scenes/{scene_id}")
async def get_scene(
    scene_id: str = Path(..., min_length=1, max_length=64),
    case: str | None = Query(default=None, description="W12: case slug (default: case_01)"),
) -> dict[str, Any]:
    loader = get_default_loader()
    case_slug = case or CASE_SLUG_DEFAULT
    try:
        return loader.scene_meta_for(case_slug, scene_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# W12: case selector + case-aware scene metadata
# ---------------------------------------------------------------------------


@app.get("/v1/cases")
async def list_registered_cases() -> dict[str, Any]:
    """List all registered cases (W12: case selector UI)."""

    return {
        "ok": True,
        "cases": list_cases(),
    }


@app.get("/v1/cases/{case_slug}")
async def get_case_metadata(
    case_slug: str = Path(..., min_length=1, max_length=64),
) -> dict[str, Any]:
    """Return case metadata + scene list (W12)."""

    meta = get_case_meta(case_slug)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"unknown case: {case_slug}")
    loader = get_default_loader()
    return {
        "ok": True,
        "case": meta,
        "scenes": [
            {
                "sceneId": s.scene_id,
                "title": s.title,
                "era": s.era,
            }
            for s in loader.all_scenes_for(case_slug)
        ],
    }


@app.get("/v1/cases/{case_slug}/scenes")
async def list_case_scenes(
    case_slug: str = Path(..., min_length=1, max_length=64),
) -> dict[str, Any]:
    """List all scenes for ``case_slug`` (W12)."""

    if case_slug not in CASE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown case: {case_slug}")
    loader = get_default_loader()
    return {
        "ok": True,
        "caseSlug": case_slug,
        "scenes": [
            {
                "sceneId": s.scene_id,
                "title": s.title,
                "era": s.era,
            }
            for s in loader.all_scenes_for(case_slug)
        ],
    }


@app.get("/v1/cases/{case_slug}/scenes/{scene_id}")
async def get_case_scene(
    case_slug: str = Path(..., min_length=1, max_length=64),
    scene_id: str = Path(..., min_length=1, max_length=64),
) -> dict[str, Any]:
    """Scene metadata for ``(case_slug, scene_id)`` (W12)."""

    if case_slug not in CASE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown case: {case_slug}")
    loader = get_default_loader()
    try:
        return loader.scene_meta_for(case_slug, scene_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# The CORE endpoint — POST /v1/runs/:runId/actions
# ---------------------------------------------------------------------------


@app.post("/v1/runs/{run_id}/actions")
async def submit_action(
    req: ActionRequest,
    run_id: str = Path(..., min_length=1, max_length=64),
) -> dict[str, Any]:
    """The core write endpoint.

    Write-domain isolation: this handler **does not** write
    to canonical state directly.  It delegates to
    :class:`server.action_runner.ActionRunner.drive_turn`,
    which is the only place that calls
    :class:`server.agents.resolver.ResolverAgent.resolve_turn`.
    """

    if req.runId != run_id:
        raise HTTPException(
            status_code=400,
            detail=f"runId mismatch: path={run_id!r} body={req.runId!r}",
        )

    runner = get_default_runner()
    try:
        result = await runner.drive_turn(
            run_id=run_id,
            scene_id=req.sceneId,
            client_action_id=req.clientActionId,
            expected_event_sequence=req.expectedEventSequence,
            player_action=req.playerAction,
            client_version=req.clientVersion,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _turn_result_to_response(result)


# ---------------------------------------------------------------------------
# Timeline + archive
# ---------------------------------------------------------------------------


@app.get("/v1/runs/{run_id}/timeline")
async def get_timeline(
    run_id: str = Path(..., min_length=1, max_length=64),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    repo = get_default_repository()
    events = repo.list_events(run_id, limit=limit)
    return {
        "runId": run_id,
        "count": len(events),
        "events": events,
    }


@app.get("/v1/runs/{run_id}/archive")
async def get_archive(run_id: str = Path(..., min_length=1, max_length=64)) -> dict[str, Any]:
    repo = get_default_repository()
    return {
        "runId": run_id,
        "artifacts": repo.list_artifacts(run_id),
        "beliefs": repo.list_beliefs(run_id),
        "memories": repo.list_memories(run_id),
        "causalSeeds": repo.list_seeds(run_id),
        "branches": repo.list_branches(run_id),
        "modelCalls": repo.list_model_calls(run_id, limit=50),
    }


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------


@app.post("/v1/runs/{run_id}/branches")
async def create_branch(
    req: CreateBranchRequest,
    run_id: str = Path(..., min_length=1, max_length=64),
) -> dict[str, Any]:
    repo = get_default_repository()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    if repo.get_run(req.sourceRunId) is None:
        raise HTTPException(
            status_code=400,
            detail=f"sourceRunId not found: {req.sourceRunId}",
        )
    branch = repo.create_branch(
        run_id=run_id,
        source_run_id=req.sourceRunId,
        fork_event_sequence=req.forkEventSequence,
        label=req.label,
        branch_id=req.branchId,
    )
    return {"ok": True, "branch": branch}


@app.get("/v1/runs/{run_id}/branches")
async def list_branches(run_id: str = Path(..., min_length=1, max_length=64)) -> dict[str, Any]:
    repo = get_default_repository()
    branches = repo.list_branches(run_id)
    return {"runId": run_id, "count": len(branches), "branches": branches}


# ---------------------------------------------------------------------------
# Response shaping for /actions
# ---------------------------------------------------------------------------


def _turn_result_to_response(result: TurnResult) -> dict[str, Any]:
    """Turn the ActionRunner's :class:`TurnResult` into the response body."""

    return {
        "ok": True,
        "outcome": result.outcome,
        "snapshot": result.snapshot,
        "clientActionId": result.client_action_id,
        "eventSequence": result.event_sequence,
        "degraded": result.degraded or "none",
        "fallbackUsed": result.fallback_used,
        "latencyMs": result.latency_ms,
        "resolvedText": result.resolved_text,
        "modelCalls": result.model_calls,
        "degradedToL3": result.degraded_to_l3,
    }


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    runtime = get_default_runtime()
    return f"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>革命街 AI 原生 · 服务端</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "PingFang SC", sans-serif;
          margin: 0; padding: 2.5rem 3rem; background: #0d0d0f; color: #e6e6e6; }}
  h1 {{ font-weight: 200; font-size: 2.2rem; letter-spacing: 0.04em; }}
  code {{ background: #1a1a1f; padding: 0.1em 0.4em; border-radius: 3px; }}
  table {{ border-collapse: collapse; margin: 1rem 0; }}
  th, td {{ padding: 0.4rem 1rem; border-bottom: 1px solid #2a2a2f; text-align: left; }}
  th {{ color: #b08cff; font-weight: 400; }}
  .pill {{ display: inline-block; padding: 0.15em 0.7em;
            border-radius: 999px; background: #2a2a2f; color: #b08cff;
            font-size: 0.8rem; letter-spacing: 0.05em; }}
</style>
</head>
<body>
  <h1>革命街 AI 原生 · 服务端</h1>
  <p>
    <span class="pill">v{app.version}</span>
    <span class="pill">LLM: {",".join(runtime.provider_names)}</span>
    <span class="pill">{"mock" if runtime.is_mock else "real"}</span>
  </p>
  <p>本服务由 6 个决策约束（决策 1-6）守护。所有 mutating 端点都通过
     <code>ResolverAgent</code> 写域隔离。</p>
  <h2>端点</h2>
  <table>
    <tr><th>方法</th><th>路径</th><th>说明</th></tr>
    <tr><td>GET</td><td><code>/health</code></td><td>健康检查</td></tr>
    <tr><td>GET</td><td><code>/v1/catalog</code></td><td>商品目录</td></tr>
    <tr><td>GET</td><td><code>/v1/entitlements</code></td><td>用户权益</td></tr>
    <tr><td>POST</td><td><code>/v1/purchases/mock-confirm</code></td><td>模拟购买</td></tr>
    <tr><td>POST</td><td><code>/v1/runs</code></td><td>创建 run</td></tr>
    <tr><td>GET</td><td><code>/v1/runs/:id</code></td><td>读 run</td></tr>
    <tr><td>POST</td><td><code>/v1/runs/:id/scenes/:sceneId/enter</code></td><td>进入场景</td></tr>
    <tr><td>POST</td><td><code>/v1/runs/:id/actions</code></td><td>玩家行为（核心）</td></tr>
    <tr><td>GET</td><td><code>/v1/runs/:id/timeline</code></td><td>时间线</td></tr>
    <tr><td>GET</td><td><code>/v1/runs/:id/archive</code></td><td>档案馆</td></tr>
    <tr><td>POST</td><td><code>/v1/runs/:id/branches</code></td><td>创建重演分支</td></tr>
    <tr><td>GET</td><td><code>/v1/runs/:id/branches</code></td><td>列分支</td></tr>
    <tr><td>POST</td><td><code>/v1/runs/:id/resume</code></td><td>续玩</td></tr>
    <tr><td>GET</td><td><code>/v1/runs/:id/snapshot</code></td><td>当前世界快照</td></tr>
    <tr><td>GET</td><td><code>/v1/scenes/:sceneId</code></td><td>场景元数据</td></tr>
    <tr><td>POST</td><td><code>/v1/analytics/events</code></td><td>埋点</td></tr>
  </table>
  <p>客户端：<code>启动游戏.cmd</code>（mock 模式） / <code>启动完整.cmd</code>（前后端）。</p>
  <p>OpenAPI: <a href="/docs" style="color: #b08cff;">/docs</a></p>
  <h2>W7 留存机制</h2>
  <table>
    <tr><th>方法</th><th>路径</th><th>说明</th></tr>
    <tr><td>POST</td><td><code>/v1/recall/schedule</code></td><td>玩家结束一局后调度 D1/D3/D7</td></tr>
    <tr><td>GET</td><td><code>/v1/recall/pending</code></td><td>玩家回来时拉取未读召回</td></tr>
    <tr><td>POST</td><td><code>/v1/recall/mark-read</code></td><td>标记已读</td></tr>
    <tr><td>POST</td><td><code>/v1/recall/tick</code></td><td>处理到期项（cron 端点）</td></tr>
  </table>
  <p>W7 召回埋点：<code>recall_d1_sent/opened</code>, <code>recall_d3_sent/opened</code>,
     <code>recall_d7_sent/opened</code>, <code>recap_started/completed</code>。</p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for ``python -m server.app``."""

    port = int(os.environ.get("G1N_PORT", "8000"))
    host = os.environ.get("G1N_HOST", "127.0.0.1")
    logger.info("Starting g1n-server on %s:%d", host, port)
    uvicorn.run(
        "server.app:app",
        host=host,
        port=port,
        reload=False,
        log_level=os.environ.get("G1N_LOG_LEVEL", "info").lower(),
        access_log=True,
    )


if __name__ == "__main__":
    main()
