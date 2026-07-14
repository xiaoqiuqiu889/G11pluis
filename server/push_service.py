"""Push service — D1/D3/D7 推送通道 (mock stdout).

W7 留存机制 — 推送通道。它不调用任何真实外部推送服务
（决策红线：mock only），把生成的召回内容 stdout 到
``g1n.push`` logger，客户端通过 ``GET /v1/recall/pending``
拉取 + ``POST /v1/recall/mark-read`` 回写状态。

红线
----

* **推送内容必须基于玩家本局时间线**（决策红线）：
  本模块只搬运 :class:`RecallService` 生成的 payload，
  绝不组装模板字符串。
* **不调用真实外部服务**（决策红线）：所有"推送"动作只
  是 :func:`print` 到 stdout，落地为 ``g1n.push`` logger
  的 INFO 行。
* **不让模型自决推送时机**（决策红线）：推送时机 = 玩家
  结束一局时 ``POST /v1/recall/schedule`` 调度的 ``fire_at``。
  客户端 poll 拉取，模型不能自决。

API
---

* :class:`PushService` — 业务逻辑
* ``POST /v1/recall/schedule`` — 玩家结束一局后调度 D1/D3/D7
* ``GET /v1/recall/pending?userId=X`` — 玩家回来时拉取未读召回
* ``POST /v1/recall/mark-read`` — 标记已读

集成
----

在 :mod:`server.app` lifespan 中：

.. code-block:: python

    from recall_service import init_recall_tables
    from push_service import build_push_router
    init_recall_tables()
    app.include_router(build_push_router())
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, Field

from db import AnalyticsEventRow
from repository import RunRepository, get_default_repository
from recall_service import (
    MAX_RECALL_MAIN_CALLS,
    MAX_RECALL_OUTPUT_TOKENS,
    RECALL_EVENT_NAMES,
    RECALL_INTERVALS,
    RecallItemRow,
    RecallScheduleRequest,
    RecallService,
    get_default_recall_service,
)

logger = logging.getLogger("g1n.push")

# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class ScheduleRequest(BaseModel):
    """``POST /v1/recall/schedule`` body."""

    runId: str = Field(..., min_length=1, max_length=64)
    userId: str = Field(default="demo-user", min_length=1, max_length=64)
    caseSlug: str = Field(default="case_01_revolution_street", max_length=64)
    recallTypes: list[str] = Field(
        default_factory=lambda: ["d1", "d3", "d7"],
        description="D1/D3/D7 子集；非法类型会被忽略",
    )

    @staticmethod
    def validate_types(types: list[str]) -> list[str]:
        return [t for t in types if t in RECALL_INTERVALS]


class ScheduleResponse(BaseModel):
    ok: bool = True
    runId: str
    scheduled: list[dict[str, Any]]


class MarkReadRequest(BaseModel):
    itemId: str = Field(..., min_length=1, max_length=64)
    userId: str | None = Field(default=None, max_length=64)


class MarkReadResponse(BaseModel):
    ok: bool = True
    item: dict[str, Any] | None


# ---------------------------------------------------------------------------
# PushService — the actual mock push logic
# ---------------------------------------------------------------------------


class PushService:
    """The mock push channel.

    Lifecycle
    ---------
    1. ``schedule_for_run`` (HTTP) — caller calls
       :meth:`RecallService.schedule_for_run` to insert
       ``RecallItemRow`` rows.  PushService does not insert
       rows itself; the row write is the
       :class:`RecallService`'s job.
    2. ``tick`` — every cron tick, the
       :class:`RecallService` calls
       :meth:`RecallService.schedule_due_items` to generate
       content + flip status to ``sent``.  After that,
       :meth:`PushService.dispatch_due` is called to log
       the push to stdout (mock) + emit the
       ``recall_*_sent`` analytics event.
    3. ``pull_pending`` (HTTP) — client polls
       ``GET /v1/recall/pending?userId=X`` to fetch items
       with status ``sent``.  The push "delivery" is
       effectively a server-side store-and-forward.
    4. ``mark_read`` (HTTP) — client posts
       ``POST /v1/recall/mark-read`` when the player opens
       a recall card in the UI.  The row's status flips
       to ``opened`` and the ``recall_*_opened`` event is
       emitted (via :class:`RecallService`).
    """

    def __init__(
        self,
        *,
        recall_service: RecallService | None = None,
        repository: RunRepository | None = None,
        stdout=None,
    ) -> None:
        self._recall = recall_service or get_default_recall_service()
        self._repo = repository or get_default_repository()
        self._stdout = stdout or sys.stdout

    # ----- schedule (delegated to RecallService) ----------------------

    def schedule_for_run(
        self,
        *,
        run_id: str,
        user_id: str,
        case_slug: str = "case_01_revolution_street",
        recall_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Schedule D1/D3/D7 items for the given run.

        The call is forwarded to :class:`RecallService` which
        owns the row writes.  This method just shapes the
        request.
        """

        types = recall_types or list(RECALL_INTERVALS.keys())
        req = RecallScheduleRequest(
            run_id=run_id,
            user_id=user_id,
            case_slug=case_slug,
            recall_types=types,
        )
        items = self._recall.schedule_for_run(req)
        return items

    # ----- tick (mock dispatch) ---------------------------------------

    def dispatch_due(self, *, now=None) -> list[dict[str, Any]]:
        """Process due scheduled items: generate + dispatch.

        For each ``status == scheduled && scheduled_for <= now``:

        1. ``RecallService`` generates the payload.
        2. :class:`PushService` "dispatches" the item —
           logs to stdout, emits the
           ``recall_*_sent`` analytics event.
        """

        fired = self._recall.schedule_due_items()
        for item in fired:
            if item.get("status") != "sent":
                continue
            self._dispatch_one(item)
        return fired

    def _dispatch_one(self, item: dict[str, Any]) -> None:
        """Log a single push to stdout + emit the sent event."""

        recall_type = item.get("recallType", "?")
        user_id = item.get("userId", "?")
        run_id = item.get("runId", "?")
        payload = item.get("payload") or {}
        title = payload.get("title") or ""
        body = payload.get("body") or ""

        # 1. Mock stdout push — the only place the "push" happens.
        line = json.dumps(
            {
                "channel": "mock-stdout",
                "recallType": recall_type,
                "userId": user_id,
                "runId": run_id,
                "itemId": item.get("itemId"),
                "title": title,
                "bodyPreview": body[:64] + ("…" if len(body) > 64 else ""),
                "scheduledFor": item.get("scheduledFor"),
                "sentAt": item.get("sentAt"),
                "deepLinks": payload.get("deepLinks", {}),
                "llmCalls": item.get("llmCalls", 0),
                "outputTokens": item.get("outputTokens", 0),
                "fallbackUsed": item.get("fallbackUsed", False),
            },
            ensure_ascii=False,
        )
        try:
            print(f"[PUSH] {line}", file=self._stdout)
        except Exception:  # noqa: BLE001
            # stdout may be closed in some test environments;
            # fall through to logger so the audit trail still
            # captures the event.
            pass
        logger.info(
            "PUSH mock dispatch user=%s run=%s type=%s llmCalls=%d",
            user_id, run_id, recall_type, item.get("llmCalls", 0),
        )

        # 2. Emit the corresponding ``recall_*_sent`` analytics
        # event so the funnel (sent → opened → recap_started) is
        # queryable from analytics_events.
        try:
            self._repo.record_analytics(
                {
                    "userId": user_id,
                    "runId": run_id,
                    "eventName": f"recall_{recall_type}_sent",
                    "payload": {
                        "itemId": item.get("itemId"),
                        "scheduledFor": item.get("scheduledFor"),
                        "deepLinks": payload.get("deepLinks", {}),
                        "llmCalls": item.get("llmCalls", 0),
                        "outputTokens": item.get("outputTokens", 0),
                    },
                    "clientVersion": "server-push-service/1.0.0",
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("push_service: analytics emit failed: %s", exc)

    # ----- pull / mark_read (client-facing) ---------------------------

    def pull_pending(
        self,
        *,
        user_id: str,
        recall_types: list[str] | None = None,
        limit: int = 32,
    ) -> list[dict[str, Any]]:
        """Return the user's pending (sent, not opened) items."""

        return self._recall.pull_pending(
            user_id=user_id,
            recall_types=recall_types,
            limit=limit,
        )

    def mark_read(
        self,
        *,
        item_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self._recall.mark_read(item_id=item_id, user_id=user_id)

    def emit_recap_event(
        self,
        *,
        event_name: str,
        user_id: str,
        run_id: str,
        recap_id: str | None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Emit ``recap_started`` / ``recap_completed`` events.

        These are the two events the brief's analytics
        requirements ask for; the W4 ``/v1/analytics/events``
        endpoint already accepts arbitrary event names, but
        having a typed wrapper on the push service keeps the
        event-shape contract in one place.
        """

        if event_name not in {"recap_started", "recap_completed"}:
            raise ValueError(
                f"unknown recap event: {event_name!r}; "
                f"allowed: recap_started, recap_completed"
            )
        body = {
            "userId": user_id,
            "runId": run_id,
            "eventName": event_name,
            "payload": {
                "recapId": recap_id,
                **(payload or {}),
            },
            "clientVersion": "server-push-service/1.0.0",
        }
        return self._repo.record_analytics(body)


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


_default_push: PushService | None = None


def get_default_push_service() -> PushService:
    global _default_push
    if _default_push is None:
        _default_push = PushService()
    return _default_push


def reset_default_push_service() -> None:
    global _default_push
    _default_push = None


def build_push_router() -> APIRouter:
    """Build the FastAPI router exposing the push HTTP endpoints.

    The router is mounted on the main app in :mod:`server.app`::

        app.include_router(build_push_router(), prefix="")
    """

    router = APIRouter(prefix="/v1/recall", tags=["recall"])

    @router.post("/schedule", response_model=ScheduleResponse)
    async def schedule_recall(req: ScheduleRequest) -> ScheduleResponse:
        """玩家结束一局后调度 D1/D3/D7。

        Body: ``{ runId, userId, recallTypes }``。
        Returns the list of scheduled (or pre-existing) items
        in ``to_dict()`` form.  Idempotent on ``(runId,
        recallType)``.
        """

        types = ScheduleRequest.validate_types(req.recallTypes)
        push = get_default_push_service()
        items = push.schedule_for_run(
            run_id=req.runId,
            user_id=req.userId,
            case_slug=req.caseSlug,
            recall_types=types,
        )
        return ScheduleResponse(
            ok=True,
            runId=req.runId,
            scheduled=items,
        )

    @router.get("/pending")
    async def pull_pending(
        userId: str = Query(default="demo-user", min_length=1, max_length=64),
        recallTypes: list[str] | None = Query(default=None),
        limit: int = Query(default=32, ge=1, le=128),
    ) -> dict[str, Any]:
        """玩家回来时拉取未读召回。

        Returns the user's pending (sent, not opened) items
        in ``scheduled_for`` order.  Each item has the full
        push payload (title / body / anchor / deepLinks).
        """

        types = [t for t in (recallTypes or []) if t in RECALL_INTERVALS] or None
        push = get_default_push_service()
        items = push.pull_pending(
            user_id=userId,
            recall_types=types,
            limit=limit,
        )
        return {
            "ok": True,
            "userId": userId,
            "count": len(items),
            "items": items,
        }

    @router.post("/mark-read", response_model=MarkReadResponse)
    async def mark_read(req: MarkReadRequest) -> MarkReadResponse:
        """标记已读 + 发射 ``recall_*_opened`` 事件。"""

        push = get_default_push_service()
        item = push.mark_read(item_id=req.itemId, user_id=req.userId)
        return MarkReadResponse(ok=True, item=item)

    @router.post("/tick")
    async def tick() -> dict[str, Any]:
        """Process due items (cron-style endpoint).

        Equivalent to :meth:`PushService.dispatch_due`.  An
        external scheduler (or the W4 server's own background
        loop) hits this on a minute tick.  Returns the
        items that actually fired.
        """

        push = get_default_push_service()
        fired = push.dispatch_due()
        return {
            "ok": True,
            "count": len(fired),
            "items": fired,
        }

    return router


__all__ = [
    "PushService",
    "ScheduleRequest",
    "ScheduleResponse",
    "MarkReadRequest",
    "MarkReadResponse",
    "get_default_push_service",
    "reset_default_push_service",
    "build_push_router",
]
