"""W8-1 · 跨端权益同步

Two surfaces:

* **Run ownership** — a run is bound to a user (one
  user, many devices).  The :class:`RunOwnershipService`
  records a row per ``(run, device)`` and the
  ``GET /v1/runs/:id/ownership`` endpoint returns the
  list of devices that have touched the run, so the
  client can show "你在 Web 上玩到这里了" hints.
* **Cross-device JWT** — a short-lived token
  (``scope='run_claim'``) that lets one device hand the
  run over to another device.  The flow is::

      POST /v1/runs/:id/claim  {deviceId, deviceKind, deviceLabel}
        -> {claimToken, runId, userId}
      (other device) POST /v1/runs/:id/resume  Authorization: Bearer <claimToken>
        -> run snapshot

  The claim token is signed with the same secret as the
  user JWT, so a single ``Authorization: Bearer`` header
  serves both surfaces.

The endpoints are gated on the user being authenticated
(``Authorization: Bearer <user-jwt>``).  A device without
the user-jwt can **not** claim a run.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from auth import RUN_CLAIM_TTL_SECONDS, decode_jwt, issue_jwt, require_user
from db import (
    GameRun,
    RunOwnershipRow,
    SessionLocal,
)

logger = logging.getLogger("g1n.cross_device")

DEVICE_KIND_WEB = "web"
DEVICE_KIND_APP = "app"
DEVICE_KIND_CLI = "cli"
VALID_DEVICE_KINDS = frozenset({DEVICE_KIND_WEB, DEVICE_KIND_APP, DEVICE_KIND_CLI})


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RunOwnershipService:
    """Tracks which devices have touched a run and the
    ``last_active_at`` watermark for cross-device resume."""

    def bind(
        self,
        *,
        run_id: str,
        user_id: str,
        device_id: str,
        device_kind: str = DEVICE_KIND_WEB,
        device_label: str | None = None,
        last_event_sequence: int = 0,
        is_primary: bool = False,
    ) -> dict[str, Any]:
        if device_kind not in VALID_DEVICE_KINDS:
            raise HTTPException(status_code=400, detail=f"invalid deviceKind: {device_kind!r}")
        with SessionLocal() as s:
            existing = s.execute(
                select(RunOwnershipRow).where(
                    RunOwnershipRow.run_id == run_id,
                    RunOwnershipRow.device_id == device_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.last_active_at = _now_utc()
                existing.last_event_sequence = max(int(existing.last_event_sequence), int(last_event_sequence))
                if is_primary:
                    existing.is_primary = True
                s.commit()
                s.refresh(existing)
                return existing.to_dict()
            row = RunOwnershipRow(
                run_id=run_id,
                user_id=user_id,
                device_kind=device_kind,
                device_id=device_id,
                device_label=device_label,
                last_active_at=_now_utc(),
                last_event_sequence=int(last_event_sequence),
                is_primary=bool(is_primary),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.to_dict()

    def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as s:
            rows = s.execute(
                select(RunOwnershipRow)
                .where(RunOwnershipRow.run_id == run_id)
                .order_by(RunOwnershipRow.last_active_at.desc())
            ).scalars().all()
            return [r.to_dict() for r in rows]

    def latest_device(self, run_id: str) -> dict[str, Any] | None:
        rows = self.list_for_run(run_id)
        return rows[0] if rows else None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with SessionLocal() as s:
            row = s.get(GameRun, run_id)
            return row.to_dict() if row else None

    def find_user_for_run(self, run_id: str) -> str | None:
        """The owning user.  The W4 server created the run
        with ``userId``; we use that as the owner when
        no :class:`RunOwnershipRow` exists yet."""

        run = self.get_run(run_id)
        if run is None:
            return None
        # Prefer the most-recent ownership row.
        latest = self.latest_device(run_id)
        if latest is not None:
            return latest["userId"]
        return run["userId"]

    def claim(
        self,
        *,
        run_id: str,
        user_id: str,
        device_id: str,
        device_kind: str = DEVICE_KIND_WEB,
        device_label: str | None = None,
    ) -> dict[str, Any]:
        """Create a short-lived run-claim token + bind the
        device to the run.

        The token is verified by :func:`verify_claim_token`
        (used by the resume endpoint).
        """

        # Run must exist.
        run = self.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
        # Bind the device (idempotent on device_id).
        binding = self.bind(
            run_id=run_id,
            user_id=user_id,
            device_id=device_id,
            device_kind=device_kind,
            device_label=device_label,
            last_event_sequence=int(run.get("eventSequence", 0)),
        )
        token = issue_jwt(
            user_id=user_id,
            scope="run_claim",
            ttl_seconds=RUN_CLAIM_TTL_SECONDS,
            run_id=run_id,
            device_id=device_id,
        )
        return {
            "ok": True,
            "runId": run_id,
            "userId": user_id,
            "device": binding,
            "claimToken": token.to_dict(),
        }

    def touch(
        self,
        *,
        run_id: str,
        device_id: str,
        last_event_sequence: int,
    ) -> dict[str, Any] | None:
        """Update the ``last_active_at`` watermark after a turn
        resolves.  Called from :class:`ActionRunner` (or a
        thin adapter) so the cross-device resume endpoint
        always points at the freshest state."""

        with SessionLocal() as s:
            row = s.execute(
                select(RunOwnershipRow).where(
                    RunOwnershipRow.run_id == run_id,
                    RunOwnershipRow.device_id == device_id,
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            row.last_active_at = _now_utc()
            row.last_event_sequence = max(int(row.last_event_sequence), int(last_event_sequence))
            s.commit()
            s.refresh(row)
            return row.to_dict()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_default_service: RunOwnershipService | None = None


def get_default_run_ownership_service() -> RunOwnershipService:
    global _default_service
    if _default_service is None:
        _default_service = RunOwnershipService()
    return _default_service


def reset_default_run_ownership_service() -> None:
    global _default_service
    _default_service = None


# ---------------------------------------------------------------------------
# Token verification helper
# ---------------------------------------------------------------------------


def verify_claim_token(token: str) -> dict[str, Any]:
    """Verify a ``run_claim`` JWT.  Returns the payload::

        {sub: userId, scope: 'run_claim', runId: ..., deviceId: ...}
    """

    payload = decode_jwt(token, expected_scope="run_claim")
    if "runId" not in payload or "deviceId" not in payload:
        raise HTTPException(status_code=401, detail="malformed run_claim token")
    return payload


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


class ClaimRequest(BaseModel):
    deviceId: str = Field(min_length=1, max_length=128)
    deviceKind: str = Field(default=DEVICE_KIND_WEB, max_length=16)
    deviceLabel: str | None = Field(default=None, max_length=128)


class ResumeWithClaimRequest(BaseModel):
    claimToken: str = Field(min_length=8, max_length=2048)
    targetSceneId: str | None = Field(default=None, max_length=64)


def build_cross_device_router() -> APIRouter:
    router = APIRouter(prefix="/v1/runs", tags=["cross_device"])
    svc = get_default_run_ownership_service

    @router.post("/{run_id}/claim")
    async def claim(
        run_id: str,
        req: ClaimRequest,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        return svc().claim(
            run_id=run_id,
            user_id=user["id"],
            device_id=req.deviceId,
            device_kind=req.deviceKind,
            device_label=req.deviceLabel,
        )

    @router.get("/{run_id}/ownership")
    async def ownership(
        run_id: str,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        owner = svc().find_user_for_run(run_id)
        if owner != user["id"]:
            raise HTTPException(status_code=403, detail="not your run")
        return {"ok": True, "runId": run_id, "devices": svc().list_for_run(run_id)}

    @router.post("/{run_id}/resume-with-claim")
    async def resume_with_claim(
        run_id: str,
        req: ResumeWithClaimRequest,
    ) -> dict[str, Any]:
        """The "other device" resume path.

        The device may or may not have its own user JWT —
        the ``claimToken`` is the cross-device proof of
        ownership.  Once the claim is verified, the
        device inherits the user's identity for the
        duration of the claim.
        """

        payload = verify_claim_token(req.claimToken)
        if payload["runId"] != run_id:
            raise HTTPException(status_code=401, detail="claim token does not match runId")
        owner = svc().find_user_for_run(run_id)
        if owner != payload["sub"]:
            raise HTTPException(status_code=403, detail="claim token user mismatch")
        # Touch the watermark so the latest-device pointer
        # tracks *this* device too.
        svc().touch(
            run_id=run_id,
            device_id=payload["deviceId"],
            last_event_sequence=int(svc().get_run(run_id).get("eventSequence", 0)),
        )
        run = svc().get_run(run_id)
        return {
            "ok": True,
            "runId": run_id,
            "userId": payload["sub"],
            "deviceId": payload["deviceId"],
            "targetSceneId": req.targetSceneId or run.get("currentSceneId"),
            "run": run,
            "devices": svc().list_for_run(run_id),
        }

    return router


__all__ = [
    "DEVICE_KIND_WEB",
    "DEVICE_KIND_APP",
    "DEVICE_KIND_CLI",
    "VALID_DEVICE_KINDS",
    "RunOwnershipService",
    "get_default_run_ownership_service",
    "reset_default_run_ownership_service",
    "verify_claim_token",
    "build_cross_device_router",
]
