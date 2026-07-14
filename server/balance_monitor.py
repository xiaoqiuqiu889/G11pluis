"""W8-2 · 余额监控 + 告警 + L3 降级

What this module does
---------------------

把 W8-1 的 "consume_credits" 从"权益写一行 audit" 升级为
"balance / cost / degradation 决策中心":

* **余额查询** — `GET /v1/balance/me` 返回玩家当前 credits
  + status (healthy / low / empty) + UI 提示
* **单局成本** — `GET /v1/balance/run/:run_id` 返回这一局已
  用的主调用次数 / 成本 / 降级状态
* **降级决策** — `BalanceMonitor.check_before_call()` 在
  每次 LLM 调用前判断：
  1. 余额 > 10 主调用 → `action='allow'`，走正常 LLM
  2. 余额 ≤ 10 但 > 0 → `action='warn'`，LLM 走但 UI 提示
     "购买积分包或 BYOK"
  3. 余额 = 0 + 有 BYOK key → `action='allow_via_byok'`
  4. 余额 = 0 + 无 BYOK key → `action='degrade_to_l3'`
     （决策 5 L3 硬要求："主线走策划脚本"）

* **退款 reset** — `BalanceMonitor.note_refund()` 写
  `credit_ledger` 一行 `entry_type='refund'`，这样
  运营 dashboard 能看到 "refund → credits → 0" 的完整
  时间线（W8-1 issue #5 闭环）

* **L3 sticky 维护** — 一旦某个 run 进入 L3，本局剩余回合
  都不再调 LLM（决策 5 的 "monotonic" 语义）。W3-A 的
  `ModelDegradationChain` 已经实现 sticky，我们只是 read。

Decision 5 red-line enforcement
--------------------------------

* **单局 ¥0.8** (软目标) — `BalanceMonitor.record_run_cost`
  累加；超 ¥0.8 触发 soft 告警但仍允许 LLM
* **20 主调用** (硬红线) — 累加 main_calls > 20 触发
  R1 报警；本 run 后续调用强制走 L3
* **4s P95** — 由 model_calls 表里 latency_ms 字段聚合，
  balance_monitor 只 read 不 write

Refund-reset behaviour (W8-1 issue #5)
---------------------------------------

* 玩家 7 天内全额退款 → `EntitlementService.revoke` 把
  credits 置 0 + `revoked_reason='refunded'`
* 玩家重买（任何 product）→ `EntitlementService.issue` 把
  `revoked_reason=None` 解除 + 加新 credits
* `CreditLedgerRow` 留下 `entry_type='refund'` → `'reissue'`
  的完整轨迹，运营可查
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import select

from auth import require_user
from db import (
    CreditLedgerRow,
    EntitlementRow,
    ModelCallRow,
    RunCostLedgerRow,
    SessionLocal,
)
from entitlements import get_default_entitlement_service

logger = logging.getLogger("g1n.balance")

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

#: Low-balance threshold (decision 4 + decision 5 协同约束):
#: "10+ 局 / 200 积分" → 200 / 20 = 10 局。剩 ≤ 10 局时提示。
LOW_BALANCE_REMAINING_CALLS: int = 10

#: Decision 5 硬红线：30-45 min 纵切片主调用 ≤ 20。
HARD_RUN_CALL_BUDGET: int = 20

#: Decision 5 软目标：单局 AI 成本 < ¥0.8。
SOFT_RUN_COST_TARGET_CNY: float = 0.8

#: Decision 5 4 级降级链里的 L3 文案（"主线走策划脚本"）。
L3_FALLBACK_MESSAGE: str = "正在为你切换到主线内容（不消耗 AI 算力）"

#: 提示玩家升级的两个口子：购买积分包 / BYOK 自购算力。
UPSELL_PURCHASE_HINT: str = "购买积分包 (¥12 / 150 次主调用)"
UPSELL_BYOK_HINT: str = "BYOK 自购算力 (OpenAI / DeepSeek / Qwen)"


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class BalanceStatus:
    """The output of :meth:`BalanceMonitor.check_user_balance`."""

    user_id: str
    credits_remaining: int
    status: str  # "healthy" | "low" | "empty" | "byok_only"
    remaining_calls: int  # estimated (credits / 1 per main call)
    suggestion: str
    action: str  # "allow" | "warn" | "allow_via_byok" | "degrade_to_l3"
    upsell_purchase: str
    upsell_byok: str
    byok_available: bool

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Wire convention is camelCase (matches W8-1
        # EntitlementRow / PaymentOrderRow / RefundRow).
        return {
            "userId": d["user_id"],
            "creditsRemaining": d["credits_remaining"],
            "status": d["status"],
            "remainingCalls": d["remaining_calls"],
            "suggestion": d["suggestion"],
            "action": d["action"],
            "upsellPurchase": d["upsell_purchase"],
            "upsellByok": d["upsell_byok"],
            "byokAvailable": d["byok_available"],
        }


@dataclass(slots=True, frozen=True)
class RunCostSnapshot:
    """The output of :meth:`BalanceMonitor.run_cost_snapshot`."""

    run_id: str
    user_id: str
    main_calls: int
    fallback_calls: int
    byok_calls: int
    server_key_calls: int
    cost_cny: float
    soft_cost_target: float
    hard_call_budget: int
    over_soft: bool
    over_hard: bool
    last_degradation: str | None
    remaining_budget: int
    status: str  # "within_budget" | "near_soft" | "over_hard"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {
            "runId": d["run_id"],
            "userId": d["user_id"],
            "mainCalls": d["main_calls"],
            "fallbackCalls": d["fallback_calls"],
            "byokCalls": d["byok_calls"],
            "serverKeyCalls": d["server_key_calls"],
            "costCny": d["cost_cny"],
            "softCostTarget": d["soft_cost_target"],
            "hardCallBudget": d["hard_call_budget"],
            "overSoft": d["over_soft"],
            "overHard": d["over_hard"],
            "lastDegradation": d["last_degradation"],
            "remainingBudget": d["remaining_budget"],
            "status": d["status"],
        }


# ---------------------------------------------------------------------------
# Credit ledger helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _record_credit_entry(
    *,
    user_id: str,
    scope: str,
    entry_type: str,
    quantity: int,
    balance_after: int,
    related_order_id: str | None = None,
    related_refund_id: str | None = None,
    related_run_id: str | None = None,
    note: str | None = None,
) -> None:
    """Append a row to ``credit_ledger``.  Best-effort; the
    ledger is audit-only and an insert failure must not
    propagate to the request path.
    """

    try:
        with SessionLocal() as s:
            row = CreditLedgerRow(
                user_id=user_id,
                scope=scope,
                entry_type=entry_type,
                quantity=int(quantity),
                balance_after=int(balance_after),
                related_order_id=related_order_id,
                related_refund_id=related_refund_id,
                related_run_id=related_run_id,
                note=(note or "")[:256] or None,
            )
            s.add(row)
            s.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "g1n.balance: credit_ledger insert failed user=%s scope=%s type=%s: %s",
            user_id, scope, entry_type, exc,
        )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class BalanceMonitor:
    """Owns the balance / degradation decisions.

    The service is stateless from the caller's perspective
    — every method opens its own DB session.  The single
    instance is the :data:`_default_monitor` singleton.
    """

    def __init__(self) -> None:
        self._entitlement_svc = get_default_entitlement_service()

    # ------------------------------------------------------------------
    # User-level balance
    # ------------------------------------------------------------------

    def credits_remaining(self, user_id: str, scope: str = "credits") -> int:
        ent = self._entitlement_svc.get_one(user_id, scope)
        if ent is None or ent.get("revokedReason"):
            return 0
        return int(ent.get("credits", 0) or 0)

    def byok_available(self, user_id: str) -> bool:
        with SessionLocal() as s:
            from db import ByokKeyRow
            row = s.execute(
                select(ByokKeyRow).where(
                    ByokKeyRow.user_id == user_id,
                    ByokKeyRow.status == "active",
                )
            ).scalars().first()
            return row is not None

    def check_user_balance(self, user_id: str) -> BalanceStatus:
        """Snapshot the user's balance + decide what action
        the LLM runtime should take next.

        This is **read-only** with respect to the
        ``entitlements`` table; the caller (LLM runtime) is
        the one that calls :func:`consume_credits`.
        """

        credits = self.credits_remaining(user_id, "credits")
        has_byok = self.byok_available(user_id)
        if credits <= 0:
            if has_byok:
                return BalanceStatus(
                    user_id=user_id,
                    credits_remaining=0,
                    status="byok_only",
                    remaining_calls=0,
                    suggestion="credits 已用完；当前走你提供的 BYOK key（自购算力）",
                    action="allow_via_byok",
                    upsell_purchase=UPSELL_PURCHASE_HINT,
                    upsell_byok=UPSELL_BYOK_HINT,
                    byok_available=True,
                )
            return BalanceStatus(
                user_id=user_id,
                credits_remaining=0,
                status="empty",
                remaining_calls=0,
                suggestion="credits 已用完；将自动降级到主线内容（不消耗 AI 算力）",
                action="degrade_to_l3",
                upsell_purchase=UPSELL_PURCHASE_HINT,
                upsell_byok=UPSELL_BYOK_HINT,
                byok_available=False,
            )
        if credits <= LOW_BALANCE_REMAINING_CALLS:
            return BalanceStatus(
                user_id=user_id,
                credits_remaining=credits,
                status="low",
                remaining_calls=credits,
                suggestion=f"余额还剩 {credits} 次主调用；考虑购买积分包或 BYOK",
                action="warn",
                upsell_purchase=UPSELL_PURCHASE_HINT,
                upsell_byok=UPSELL_BYOK_HINT,
                byok_available=has_byok,
            )
        return BalanceStatus(
            user_id=user_id,
            credits_remaining=credits,
            status="healthy",
            remaining_calls=credits,
            suggestion="余额充足",
            action="allow",
            upsell_purchase=UPSELL_PURCHASE_HINT,
            upsell_byok=UPSELL_BYOK_HINT,
            byok_available=has_byok,
        )

    # ------------------------------------------------------------------
    # Pre-call decision (the gate the LLM runtime calls)
    # ------------------------------------------------------------------

    def check_before_call(self, *, user_id: str, run_id: str | None = None) -> BalanceStatus:
        """Decide what to do for the next LLM call.

        The :class:`LLMRuntime` calls this before
        :func:`EntitlementService.consume_credits`; on
        ``action='degrade_to_l3'`` the runtime short-circuits
        to the writer mainline and **does not** call
        ``consume_credits`` (the L3 path is free).
        """

        snap = self.check_user_balance(user_id)
        if run_id is not None:
            run_snap = self.run_cost_snapshot(run_id)
            if run_snap.over_hard:
                # Decision 5 R1 hard red line: a run that
                # has already hit 20 main calls must not
                # consume any more.  The runtime will route
                # to L3.
                return BalanceStatus(
                    user_id=user_id,
                    credits_remaining=snap.credits_remaining,
                    status="over_hard",
                    remaining_calls=max(0, run_snap.remaining_budget),
                    suggestion=(
                        f"本局已用满 {HARD_RUN_CALL_BUDGET} 次主调用"
                        f"（决策 5 R1 硬红线）；降级到主线内容"
                    ),
                    action="degrade_to_l3",
                    upsell_purchase=UPSELL_PURCHASE_HINT,
                    upsell_byok=UPSELL_BYOK_HINT,
                    byok_available=snap.byok_available,
                )
        return snap

    # ------------------------------------------------------------------
    # consume_credits (the wire-up that W8-1 left as a gap)
    # ------------------------------------------------------------------

    def consume_one(
        self,
        *,
        user_id: str,
        run_id: str | None = None,
        n: int = 1,
        via_byok: bool = False,
    ) -> int:
        """Deduct ``n`` credits from the ``credits`` scope.

        Returns the number of credits actually deducted (may
        be less than ``n`` if the user runs out).  Raises
        :class:`InsufficientCreditsError` (from
        :mod:`server.byok`) when the player has zero
        credits *and* no BYOK key — the LLM runtime
        translates that to L3.

        The credit_ledger gets a ``consume`` row so the
        "credits dropped to 0" event is auditable.
        """

        if via_byok:
            # BYOK calls do not deduct credits — the player
            # is paying the upstream provider directly.  We
            # still update the run ledger so the cost
            # controller can show "5 BYOK + 3 server" in
            # the ops dashboard.
            if run_id is not None:
                self._bump_run_ledger(run_id=run_id, byok_calls=n)
            return 0
        taken = self._entitlement_svc.consume_credits(
            user_id=user_id, scope="credits", n=n
        )
        if taken < n:
            # The user ran out mid-batch.  Log the partial
            # take and let the LLM runtime re-check
            # (next call will trigger L3).
            logger.info(
                "g1n.balance: partial consume user=%s requested=%d took=%d",
                user_id, n, taken,
            )
        balance_after = self.credits_remaining(user_id, "credits")
        _record_credit_entry(
            user_id=user_id,
            scope="credits",
            entry_type="consume",
            quantity=-taken,
            balance_after=balance_after,
            related_run_id=run_id,
            note="llm_runtime.consume_one",
        )
        if run_id is not None:
            self._bump_run_ledger(
                run_id=run_id,
                server_key_calls=n,
                cost_cny=0.0,  # The cost controller fills this in.
            )
        if taken == 0 and not self.byok_available(user_id):
            # Hard fail the LLM path.
            from byok import InsufficientCreditsError
            raise InsufficientCreditsError(
                f"user {user_id} has no credits and no BYOK key; "
                f"degrading to L3 mainline"
            )
        return taken

    # ------------------------------------------------------------------
    # Refund + re-issue hooks
    # ------------------------------------------------------------------

    def note_refund(
        self,
        *,
        user_id: str,
        scope: str,
        refund_id: str,
        order_id: str,
        amount_credits: int,
    ) -> None:
        """Write a ``refund`` ledger entry when a refund
        successfully clawed back the entitlement (decision
        4 + decision 5 协同约束：退款是"消耗"的对立事件)."""

        balance_after = self.credits_remaining(user_id, scope)
        _record_credit_entry(
            user_id=user_id,
            scope=scope,
            entry_type="refund",
            quantity=-int(amount_credits),
            balance_after=balance_after,
            related_order_id=order_id,
            related_refund_id=refund_id,
            note="refund_service.refund",
        )

    def note_restore(
        self,
        *,
        user_id: str,
        scope: str,
        new_credits: int,
        order_id: str | None = None,
    ) -> None:
        """Write a ``reissue`` / ``restore`` ledger entry
        when the player re-purchases after a refund.
        """

        balance_after = self.credits_remaining(user_id, scope)
        # Re-purchase always shows up as a positive quantity.
        # We use 'reissue' if the order id is present (the
        # new top-up came from a paid order); 'restore' if
        # the operator flipped a flag manually.
        entry_type = "reissue" if order_id else "restore"
        _record_credit_entry(
            user_id=user_id,
            scope=scope,
            entry_type=entry_type,
            quantity=int(new_credits),
            balance_after=balance_after,
            related_order_id=order_id,
            note="re-purchase after refund",
        )

    # ------------------------------------------------------------------
    # Per-run cost roll-up
    # ------------------------------------------------------------------

    def _bump_run_ledger(
        self,
        *,
        run_id: str,
        main_calls: int = 0,
        byok_calls: int = 0,
        server_key_calls: int = 0,
        fallback_calls: int = 0,
        cost_cny: float = 0.0,
        last_degradation: str | None = None,
    ) -> None:
        with SessionLocal() as s:
            row = s.execute(
                select(RunCostLedgerRow).where(
                    RunCostLedgerRow.run_id == run_id,
                    RunCostLedgerRow.scope == "main",
                )
            ).scalar_one_or_none()
            if row is None:
                row = RunCostLedgerRow(
                    run_id=run_id,
                    user_id="",
                    scope="main",
                )
                s.add(row)
                s.flush()
            row.main_calls = int(row.main_calls) + int(main_calls)
            row.byok_calls = int(row.byok_calls) + int(byok_calls)
            row.server_key_calls = int(row.server_key_calls) + int(server_key_calls)
            row.fallback_calls = int(row.fallback_calls) + int(fallback_calls)
            row.cost_cny = float(row.cost_cny) + float(cost_cny)
            if last_degradation is not None:
                row.last_degradation = last_degradation
            s.commit()

    def record_run_cost(
        self,
        *,
        run_id: str,
        user_id: str,
        cost_cny: float,
        call_count: int = 1,
        via_byok: bool = False,
        used_fallback: bool = False,
        degradation_level: str | None = None,
    ) -> None:
        """Update the per-run ledger after one or more LLM calls."""

        kwargs: dict[str, Any] = {"run_id": run_id}
        if via_byok:
            kwargs["byok_calls"] = call_count
        else:
            kwargs["server_key_calls"] = call_count
        if used_fallback:
            kwargs["fallback_calls"] = call_count
        else:
            kwargs["main_calls"] = call_count
        kwargs["cost_cny"] = cost_cny
        if degradation_level is not None:
            kwargs["last_degradation"] = degradation_level
        with SessionLocal() as s:
            row = s.execute(
                select(RunCostLedgerRow).where(
                    RunCostLedgerRow.run_id == run_id,
                    RunCostLedgerRow.scope == "main",
                )
            ).scalar_one_or_none()
            if row is None:
                row = RunCostLedgerRow(
                    run_id=run_id,
                    user_id=user_id,
                    scope="main",
                )
                s.add(row)
                s.flush()
            # Stamp user_id on first write.
            if not row.user_id:
                row.user_id = user_id
            row.main_calls = int(row.main_calls) + kwargs.get("main_calls", 0)
            row.byok_calls = int(row.byok_calls) + kwargs.get("byok_calls", 0)
            row.server_key_calls = int(row.server_key_calls) + kwargs.get("server_key_calls", 0)
            row.fallback_calls = int(row.fallback_calls) + kwargs.get("fallback_calls", 0)
            row.cost_cny = float(row.cost_cny) + float(kwargs.get("cost_cny", 0.0))
            if degradation_level is not None:
                row.last_degradation = degradation_level
            s.commit()

    def run_cost_snapshot(self, run_id: str) -> RunCostSnapshot:
        with SessionLocal() as s:
            row = s.execute(
                select(RunCostLedgerRow).where(
                    RunCostLedgerRow.run_id == run_id,
                    RunCostLedgerRow.scope == "main",
                )
            ).scalar_one_or_none()
            if row is None:
                return RunCostSnapshot(
                    run_id=run_id,
                    user_id="",
                    main_calls=0,
                    fallback_calls=0,
                    byok_calls=0,
                    server_key_calls=0,
                    cost_cny=0.0,
                    soft_cost_target=SOFT_RUN_COST_TARGET_CNY,
                    hard_call_budget=HARD_RUN_CALL_BUDGET,
                    over_soft=False,
                    over_hard=False,
                    last_degradation=None,
                    remaining_budget=HARD_RUN_CALL_BUDGET,
                    status="within_budget",
                )
            main = int(row.main_calls)
            cost = float(row.cost_cny)
            over_hard = main > HARD_RUN_CALL_BUDGET
            over_soft = cost > SOFT_RUN_COST_TARGET_CNY
            remaining = max(0, HARD_RUN_CALL_BUDGET - main)
            if over_hard:
                status = "over_hard"
            elif over_soft:
                status = "near_soft"
            else:
                status = "within_budget"
            return RunCostSnapshot(
                run_id=run_id,
                user_id=row.user_id or "",
                main_calls=main,
                fallback_calls=int(row.fallback_calls),
                byok_calls=int(row.byok_calls),
                server_key_calls=int(row.server_key_calls),
                cost_cny=cost,
                soft_cost_target=SOFT_RUN_COST_TARGET_CNY,
                hard_call_budget=HARD_RUN_CALL_BUDGET,
                over_soft=over_soft,
                over_hard=over_hard,
                last_degradation=row.last_degradation,
                remaining_budget=remaining,
                status=status,
            )

    def runs_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as s:
            rows = s.execute(
                select(RunCostLedgerRow)
                .where(RunCostLedgerRow.user_id == user_id)
                .order_by(RunCostLedgerRow.updated_at.desc())
            ).scalars().all()
            return [r.to_dict() for r in rows]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_default_monitor: BalanceMonitor | None = None


def get_default_balance_monitor() -> BalanceMonitor:
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = BalanceMonitor()
    return _default_monitor


def reset_default_balance_monitor() -> None:
    global _default_monitor
    _default_monitor = None


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


def build_balance_router() -> APIRouter:
    router = APIRouter(prefix="/v1/balance", tags=["balance"])
    monitor = get_default_balance_monitor

    @router.get("/me")
    async def get_my_balance(
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        snap = monitor().check_user_balance(user["id"])
        return {"ok": True, "balance": snap.to_dict()}

    @router.get("/run/{run_id}")
    async def get_run_cost(
        run_id: str = Path(..., min_length=1, max_length=64),
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        snap = monitor().run_cost_snapshot(run_id)
        if snap.user_id and snap.user_id != user["id"]:
            raise HTTPException(status_code=403, detail="not your run")
        return {"ok": True, "run": snap.to_dict()}

    @router.get("/runs")
    async def list_my_runs(
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        runs = monitor().runs_for_user(user["id"])
        return {"ok": True, "userId": user["id"], "runs": runs, "count": len(runs)}

    return router


__all__ = [
    "LOW_BALANCE_REMAINING_CALLS",
    "HARD_RUN_CALL_BUDGET",
    "SOFT_RUN_COST_TARGET_CNY",
    "L3_FALLBACK_MESSAGE",
    "UPSELL_PURCHASE_HINT",
    "UPSELL_BYOK_HINT",
    "BalanceStatus",
    "RunCostSnapshot",
    "BalanceMonitor",
    "get_default_balance_monitor",
    "reset_default_balance_monitor",
    "build_balance_router",
]
