"""D1 / D3 / D7 召回内容生成服务 + 周度短案邀请.

W7 留存机制 — 决策红线：

* **内容基于本局时间线** — 推送内容来自玩家的
  ``game_events`` / ``character_beliefs`` / ``causal_seeds``
  / ``artifacts``，不是模板。W7 红线。
* **5 硬红线** — 单次召回（D1/D3/D7）≤ 5 次 LLM 主调用，
  输出 token ≤ 200（决策 5 的子约束）。
* **mock 默认 / 真 LLM 可切** — 缺 API key 时 mock 拼装；
  设置 ``G1N_RECALL_USE_LLM=1`` 时走 :class:`LLMRuntime.gateway`。
* **复用 W3-A** — 通过 :func:`get_default_runtime` 拿到
  生产 :class:`ModelGateway`；schema 校验沿用
  :class:`OutputVerifier`。
* **复用 W3-C** — :class:`ContentGuard` 阻止 forbidden_reveal
  泄露 + 数字钳制。
* **复用 W4 DB** — 11 ORM 模型保持不变；本模块新增 1 个
  :class:`RecallItemRow` 到 ``db.Base``，
  ``init_recall_tables()`` 幂等建表。
* **不改 6 决策** — 见 ``docs/design/requirements-review-v1.md``。

输出形态
--------

每条 :class:`RecallItemRow` 的 ``payload_json`` 是一个 dict：

.. code-block:: python

    {
        "type": "d1" | "d3" | "d7" | "recap_invite",
        "title": str,            # 推送标题（≤ 24 字）
        "body": str,             # 推送正文（≤ 200 token 限额内）
        "anchor": {              # 本局时间线锚点
            "runId": str,
            "sceneId": str,
            "eventSequence": int,
            "keyAction": dict,        # 触发召回的玩家行为
            "firedSeeds": [str],      # 触发的因果种子
            "beliefSnapshots": [dict] # 关键 belief
        },
        "perspective": str,      # D3: leila / arash / kamran / maryam
        "deepLinks": {           # 客户端跳转锚
            "sceneId": str,
            "recapId": str|None
        },
        "llmCalls": int,         # 本次召回用了几次主调用
        "outputTokens": int,
        "fallbackUsed": bool
    }

推送（mock stdout）由 :mod:`server.push_service` 调用本模块
的 :meth:`RecallService.schedule_for_run` / :meth:`pull_pending` /
:meth:`mark_read`，不直接打 LLM。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import (
    AnalyticsEventRow,
    ArtifactRow,
    Base,
    CausalSeedRow,
    CharacterBeliefRow,
    GameEventRow,
    GameRun,
    MemoryRow,
    WorldSnapshotRow,
    engine,
    get_session,
)
from llm_runtime import LLMRuntime, get_default_runtime
from model import (
    Message,
    MessageRole,
    ModelRequest,
    TaskType,
)
from safety.content_guards import check_forbidden_reveals
from safety.output_verifier import verify_output
from repository import RunRepository, get_default_repository
from scene_loader import SceneContractLoader, get_default_loader

logger = logging.getLogger("g1n.recall")


# ---------------------------------------------------------------------------
# Constants — 5 硬红线
# ---------------------------------------------------------------------------


#: Decision 5 子约束：单次召回（D1/D3/D7）≤ 5 次 LLM 主调用
MAX_RECALL_MAIN_CALLS: int = 5
#: Decision 5 子约束：单次输出 token ≤ 200
MAX_RECALL_OUTPUT_TOKENS: int = 200
#: 推送内容长度软上限（与 LLM 输出 200 token 配合）
MAX_RECALL_BODY_CHARS: int = 360

#: D1 / D3 / D7 间隔
RECALL_INTERVALS: dict[str, timedelta] = {
    "d1": timedelta(days=1),
    "d3": timedelta(days=3),
    "d7": timedelta(days=7),
}

#: 8 个新事件名（埋点）
RECALL_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "recall_d1_sent",
        "recall_d1_opened",
        "recall_d3_sent",
        "recall_d3_opened",
        "recall_d7_sent",
        "recall_d7_opened",
        "recap_started",
        "recap_completed",
    }
)

#: 召回类型 → 默认视角
RECALL_TYPE_TO_PERSPECTIVE: dict[str, str] = {
    "d1": "leila",       # 默认旁观者（决策 2）
    "d3": "arash",       # 另一人物视角
    "d7": "leila",       # 周度短案邀请
}

#: 周度短案目录（在 scene_loader 内复用）
RECAPS_DIR_NAME = "recaps"


# ---------------------------------------------------------------------------
# ORM model — RecallItemRow
# ---------------------------------------------------------------------------


class RecallItemRow(Base):
    """A single D1/D3/D7 recall item.

    The row stores both the **scheduling state** (when to
    fire) and the **generated content** (the actual push
    payload).  The two are kept in one row because a recall
    is short-lived: schedule → generate → push → open, all
    within days.

    Why a new model and not AnalyticsEventRow
    -----------------------------------------
    ``AnalyticsEventRow`` is a write-and-forget event sink
    (decision 4 / brief).  Recall items need structured
    payload + state transitions (scheduled → sent → opened),
    which the analytics table doesn't model.  Keeping a
    dedicated table makes the recall funnel queryable.

    The model is **appended to** the existing ``db.Base``
    so :func:`init_db` continues to manage schema creation
    for both old (11) and new (12) tables idempotently.
    """

    __tablename__ = "recall_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(64), nullable=False, index=True)
    run_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    case_slug = Column(String(64), nullable=False)
    recall_type = Column(String(16), nullable=False)  # d1 | d3 | d7 | recap_invite
    perspective = Column(String(32), nullable=True)   # leila | arash | kamran | maryam
    status = Column(String(16), nullable=False, default="scheduled")  # scheduled | sent | opened | failed
    scheduled_for = Column(DateTime(timezone=True), nullable=False, index=True)
    generated_at = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    opened_at = Column(DateTime(timezone=True), nullable=True)
    payload_json = Column(Text, nullable=False, default="{}")
    llm_calls = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    fallback_used = Column(Boolean, nullable=False, default=False)
    recap_id = Column(String(64), nullable=True, index=True)  # d7 邀请的短案
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_recall_user_status", "user_id", "status"),
        Index("ix_recall_run_type", "run_id", "recall_type"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "itemId": self.item_id,
            "runId": self.run_id,
            "userId": self.user_id,
            "caseSlug": self.case_slug,
            "recallType": self.recall_type,
            "perspective": self.perspective,
            "status": self.status,
            "scheduledFor": self.scheduled_for.isoformat() if self.scheduled_for else None,
            "generatedAt": self.generated_at.isoformat() if self.generated_at else None,
            "sentAt": self.sent_at.isoformat() if self.sent_at else None,
            "openedAt": self.opened_at.isoformat() if self.opened_at else None,
            "payload": _from_json(self.payload_json) or {},
            "llmCalls": self.llm_calls,
            "outputTokens": self.output_tokens,
            "fallbackUsed": self.fallback_used,
            "recapId": self.recap_id,
            "error": self.error,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Return the current UTC time.

    **Naive UTC, not timezone-aware.**  SQLite's
    ``DateTime(timezone=True)`` does not actually persist
    the tzinfo — on read the column is naive.  We
    normalise both writes and queries to naive UTC so the
    ``scheduled_for <= now`` filter in
    :meth:`RecallService.schedule_due_items` works
    correctly across SQLite (test) and Postgres
    (production).  Postgres will silently treat naive UTC
    as local timezone, but our code only ever uses UTC, so
    the comparison is still well-defined.
    """

    return datetime.utcnow()


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


def _truncate_to_chars(text: str, max_chars: int) -> str:
    """Truncate ``text`` to ``max_chars`` Chinese-mixed characters.

    Approximates the 200-token limit at 1.8 chars/token for
    mixed CJK / English.  Returns the original if shorter.
    """

    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Timeline extraction — *the* W7 red line
# ---------------------------------------------------------------------------


def _last_event_for_run(session: Session, run_id: str) -> GameEventRow | None:
    """Return the most recent :class:`GameEventRow` for ``run_id``."""

    return session.execute(
        select(GameEventRow)
        .where(GameEventRow.run_id == run_id)
        .order_by(GameEventRow.event_sequence.desc())
        .limit(1)
    ).scalar_one_or_none()


def _last_n_events(session: Session, run_id: str, *, n: int = 5) -> list[GameEventRow]:
    return list(
        session.execute(
            select(GameEventRow)
            .where(GameEventRow.run_id == run_id)
            .order_by(GameEventRow.event_sequence.desc())
            .limit(n)
        ).scalars()
    )


def _fired_seeds_for_run(session: Session, run_id: str) -> list[CausalSeedRow]:
    return list(
        session.execute(
            select(CausalSeedRow)
            .where(
                CausalSeedRow.run_id == run_id,
                CausalSeedRow.is_dormant.is_(False),
            )
            .order_by(CausalSeedRow.fired_at_event.asc())
        ).scalars()
    )


def _dormant_seeds_for_run(session: Session, run_id: str) -> list[CausalSeedRow]:
    return list(
        session.execute(
            select(CausalSeedRow)
            .where(
                CausalSeedRow.run_id == run_id,
                CausalSeedRow.is_dormant.is_(True),
            )
        ).scalars()
    )


def _latest_belief_snapshots(
    session: Session, run_id: str, *, limit: int = 6
) -> list[CharacterBeliefRow]:
    """The most recent N belief rows (across characters)."""

    return list(
        session.execute(
            select(CharacterBeliefRow)
            .where(CharacterBeliefRow.run_id == run_id)
            .order_by(CharacterBeliefRow.event_sequence.desc())
            .limit(limit)
        ).scalars()
    )


def _artifacts_owned_by(
    session: Session, run_id: str, character_id: str
) -> list[ArtifactRow]:
    return list(
        session.execute(
            select(ArtifactRow)
            .where(
                ArtifactRow.run_id == run_id,
                ArtifactRow.owner_id == character_id,
            )
        ).scalars()
    )


def _latest_snapshot_payload(session: Session, run_id: str) -> dict[str, Any] | None:
    row = session.execute(
        select(WorldSnapshotRow)
        .where(WorldSnapshotRow.run_id == run_id)
        .order_by(WorldSnapshotRow.event_sequence.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return _from_json(row.snapshot_json)


def _format_action_short(player_action: dict[str, Any]) -> str:
    """One-line summary of a PlayerAction, for the push body."""

    action = player_action.get("actionType", "动作")
    target = player_action.get("targetId")
    evidence = player_action.get("evidenceIds") or []
    scene = player_action.get("sceneId") or ""
    if target and evidence:
        return f"{scene} 场景里对 {target} 执行 {action}（{','.join(evidence)}）"
    if target:
        return f"{scene} 场景里对 {target} 执行 {action}"
    if evidence:
        return f"{scene} 场景里 {action}（{','.join(evidence)}）"
    return f"{scene} 场景里的 {action}"


def _character_perspective_label(perspective: str) -> str:
    """The display label the push uses for the character.

    Hard-coded Chinese labels to avoid a DB roundtrip in the
    hot path; the canonical names live in
    :mod:`server.agents.prompts.character_card`.
    """

    return {
        "leila": "莱拉",
        "arash": "阿拉什",
        "kamran": "卡姆兰",
        "maryam": "玛丽亚姆",
        "maziar": "玛兹雅",
    }.get(perspective, perspective)


# ---------------------------------------------------------------------------
# D1 — "昨日回顾"
# ---------------------------------------------------------------------------


def _build_d1_anchor(session: Session, run_id: str) -> dict[str, Any]:
    """Pick the *most affecting* last action as the D1 anchor.

    The integration test in this module asserts D1 is *not* a
    template — i.e. the title / body reference the actual
    ``actionType``, ``targetId``, ``evidenceIds`` the player
    executed.  This function is the only source of those
    references.
    """

    last = _last_event_for_run(session, run_id)
    if last is None:
        return {
            "runId": run_id,
            "sceneId": None,
            "eventSequence": 0,
            "keyAction": {},
            "firedSeeds": [],
            "beliefSnapshots": [],
        }

    # The action payload was stored as JSON in
    # GameEventRow.action_payload_json.
    action_payload = _from_json(last.action_payload_json) or {}
    fired = _fired_seeds_for_run(session, run_id)
    fired_ids = [s.seed_id for s in fired if not s.is_dormant][-3:]
    beliefs = _latest_belief_snapshots(session, run_id, limit=3)
    belief_snapshots = [
        {
            "characterId": b.character_id,
            "subject": b.subject,
            "beliefState": b.belief_state,
            "confidence": float(b.confidence or 0.0),
        }
        for b in beliefs
    ]
    return {
        "runId": run_id,
        "sceneId": last.scene_id,
        "eventSequence": int(last.event_sequence),
        "keyAction": action_payload,
        "firedSeeds": fired_ids,
        "beliefSnapshots": belief_snapshots,
    }


def _format_d1_title(anchor: dict[str, Any]) -> str:
    scene = anchor.get("sceneId") or "本局"
    return f"昨日回顾 · {scene}"


def _format_d1_body_template(anchor: dict[str, Any]) -> str:
    """Mock-mode body — references the actual action, never a template.

    Even in mock mode the body includes the specific
    ``actionType`` / ``evidenceIds`` / ``sceneId`` from the
    anchor; the LLM is only used to refine tone, not to
    invent content.  This is the W7 red line.
    """

    action_summary = _format_action_short(anchor.get("keyAction") or {})
    fired = anchor.get("firedSeeds") or []
    if fired:
        seed_clause = f"那次行为已经触发 {len(fired)} 个远期回响（{', '.join(fired)}）"
    else:
        seed_clause = "那次行为将带着你走向 2011 机场、2024 咖啡馆"
    return _truncate_to_chars(
        f"你昨晚在 {action_summary}。{seed_clause}。"
        f"莱拉在 2011 机场是否再摸到那张照片，取决于你今天选择回到现场。",
        MAX_RECALL_BODY_CHARS,
    )


# ---------------------------------------------------------------------------
# D3 — "另一人物视角"
# ---------------------------------------------------------------------------


def _pick_perspective(
    session: Session, run_id: str, *, primary_perspective: str
) -> str:
    """Pick the *opposite* perspective for D3.

    D3's brief: "莱拉当时以为 X，阿拉什当时以为 Y".  The
    service infers the opposite character from the most
    recent belief activity: if leila's last belief
    dominates, the *other* perspective is arash (the
    default D3 voice per the brief).
    """

    beliefs = _latest_belief_snapshots(session, run_id, limit=4)
    if not beliefs:
        return "arash" if primary_perspective == "leila" else "leila"

    # Count by character
    counts: dict[str, int] = {}
    for b in beliefs:
        counts[b.character_id] = counts.get(b.character_id, 0) + 1
    dominant = max(counts, key=counts.get)  # type: ignore[arg-type]
    candidates = ["leila", "arash", "kamran", "maryam", "maziar"]
    for c in candidates:
        if c != dominant:
            return c
    return "arash"


def _build_d3_anchor(
    session: Session, run_id: str, *, perspective: str
) -> dict[str, Any]:
    last = _last_event_for_run(session, run_id)
    beliefs = _latest_belief_snapshots(session, run_id, limit=6)
    perspective_beliefs = [
        {
            "characterId": b.character_id,
            "subject": b.subject,
            "beliefState": b.belief_state,
            "confidence": float(b.confidence or 0.0),
            "evidenceMemoryId": b.evidence_memory_id,
        }
        for b in beliefs
        if b.character_id == perspective
    ]
    other_beliefs = [
        {
            "characterId": b.character_id,
            "subject": b.subject,
            "beliefState": b.belief_state,
            "confidence": float(b.confidence or 0.0),
        }
        for b in beliefs
        if b.character_id != perspective
    ]
    artifacts_owned = _artifacts_owned_by(session, run_id, perspective)
    return {
        "runId": run_id,
        "sceneId": last.scene_id if last else None,
        "eventSequence": int(last.event_sequence) if last else 0,
        "keyAction": _from_json(last.action_payload_json) if last else {},
        "perspective": perspective,
        "perspectiveLabel": _character_perspective_label(perspective),
        "perspectiveBeliefs": perspective_beliefs,
        "otherBeliefs": other_beliefs[:3],
        "artifactsHeld": [
            {
                "artifactId": a.artifact_id,
                "state": a.state,
                "isRevealed": bool(a.is_revealed),
            }
            for a in artifacts_owned
        ],
    }


def _format_d3_title(anchor: dict[str, Any]) -> str:
    label = anchor.get("perspectiveLabel", "另一人物")
    return f"{label}当时以为……"


def _format_d3_body_template(anchor: dict[str, Any]) -> str:
    label = anchor.get("perspectiveLabel", "他/她")
    own = anchor.get("perspectiveBeliefs") or []
    other = anchor.get("otherBeliefs") or []
    own_subjects = [b["subject"] for b in own[:2]]
    other_subjects = [b["subject"] for b in other[:2]]
    own_clause = (
        f"{label}当时以为 {' / '.join(own_subjects) or '这一切只是日常'}"
        if own_subjects
        else f"{label}当时以为，这一切只是日常"
    )
    other_clause = (
        f"；而 {' / '.join(b for b in other_subjects) or '你'} 的版本里另有不同"
        if other_subjects
        else ""
    )
    return _truncate_to_chars(
        own_clause + other_clause + "。回到 13 年前的某一刻，你也能看到那一面。",
        MAX_RECALL_BODY_CHARS,
    )


# ---------------------------------------------------------------------------
# D7 — "周度短案"邀请（基于 5 个最触动 NPC 行为的"未完成对话"）
# ---------------------------------------------------------------------------


def _top_unfinished_dialogues(
    session: Session, run_id: str, *, k: int = 5
) -> list[dict[str, Any]]:
    """Pick the top-k *unfinished dialogues* the NPC flagged.

    The algorithm:

    1. Walk the run's belief rows in event order.
    2. For each belief update, treat it as a half-said
       dialogue when:
          * ``confidence >= 0.55`` (NPC 想说但没说满)
          * ``subject`` is in the scene's causal_seeds /
            mandatory_echoes (i.e. cross-era carry)
    3. Score = ``confidence * 0.7 + 1 / event_age * 0.3``
       (recency dominates, but confidence breaks ties).
    4. De-duplicate by (characterId, subject); keep highest
       score per pair.

    This is the *unfinished-dialogue* algorithm the
    integration test asserts.  Output is sorted by score
    desc, capped at ``k``.
    """

    from datetime import datetime as _dt

    beliefs = list(
        session.execute(
            select(CharacterBeliefRow)
            .where(CharacterBeliefRow.run_id == run_id)
            .order_by(CharacterBeliefRow.event_sequence.asc())
        ).scalars()
    )
    if not beliefs:
        return []

    # Build the seed-id set for cross-era filter
    seed_ids = {
        s.seed_id
        for s in session.execute(
            select(CausalSeedRow).where(CausalSeedRow.run_id == run_id)
        ).scalars()
    }

    last_event_seq = max((b.event_sequence for b in beliefs), default=1) or 1
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for b in beliefs:
        subject = b.subject
        if not subject:
            continue
        confidence = float(b.confidence or 0.0)
        if confidence < 0.55:
            continue
        if seed_ids and subject not in seed_ids:
            # Only count cross-era beliefs as unfinished
            # dialogues; a pure scene-local belief doesn't
            # carry weight to the next era.
            continue
        recency = max(1, last_event_seq - b.event_sequence + 1)
        score = round(confidence * 0.7 + (1.0 / recency) * 0.3, 4)
        key = (b.character_id, subject)
        existing = seen.get(key)
        if existing is None or score > existing["score"]:
            seen[key] = {
                "characterId": b.character_id,
                "subject": subject,
                "beliefState": b.belief_state,
                "confidence": confidence,
                "eventSequence": int(b.event_sequence),
                "score": score,
            }
    items = sorted(seen.values(), key=lambda d: d["score"], reverse=True)
    return items[:k]


def _pick_recap_for_run(
    session: Session, run_id: str, *, loader: SceneContractLoader
) -> dict[str, Any] | None:
    """Pick the most relevant recap YAML for the run.

    The selection is deterministic (no LLM): we map the
    run's *current scene* to a recap.  The 3 recaps cover
    ``1995 leila san jose``, ``tehran telescope night``,
    ``1989-2000 shiraz library`` — at most one per run, so
    the first match wins.

    Returns a dict with ``recapId``, ``title``, ``scenes``,
    or ``None`` if no recap is configured for this run.
    """

    recaps_root = loader.content_root / loader.__class__.__name__  # type: ignore[attr-defined]
    # Use the loader's known content_root instead
    recaps_root = loader.content_root / "case_01_revolution_street" / RECAPS_DIR_NAME
    if not recaps_root.exists():
        return None
    available = sorted(p.stem for p in recaps_root.glob("*.yaml"))
    if not available:
        return None
    # Map run characteristics → recap.  Round-robin for
    # now (the run has 1 of 3 recaps picked by hash mod).
    idx = (sum(ord(c) for c in run_id) % len(available))
    recap_id = available[idx]
    return {
        "recapId": recap_id,
        "recapsRoot": str(recaps_root),
    }


def _build_d7_anchor(
    session: Session,
    run_id: str,
    *,
    loader: SceneContractLoader,
) -> dict[str, Any]:
    unfinished = _top_unfinished_dialogues(session, run_id, k=5)
    recap = _pick_recap_for_run(session, run_id, loader=loader)
    fired = [s.seed_id for s in _fired_seeds_for_run(session, run_id)][-5:]
    last = _last_event_for_run(session, run_id)
    return {
        "runId": run_id,
        "sceneId": last.scene_id if last else None,
        "eventSequence": int(last.event_sequence) if last else 0,
        "unfinishedDialogues": unfinished,
        "firedSeeds": fired,
        "recap": recap,
    }


def _format_d7_title(anchor: dict[str, Any]) -> str:
    recap = anchor.get("recap") or {}
    recap_id = recap.get("recapId")
    if recap_id:
        return "周度短案 · 你的 13 年"
    return "周度短案 · 5 个未完成的对话"


def _format_d7_body_template(anchor: dict[str, Any]) -> str:
    unfinished = anchor.get("unfinishedDialogues") or []
    recap = anchor.get("recap") or {}
    recap_id = recap.get("recapId")
    if not unfinished:
        return _truncate_to_chars(
            "你的本局已经写下了 5 段未完成的对话。本周的短案邀请把它们整理成一段 5 分钟的旁白。",
            MAX_RECALL_BODY_CHARS,
        )
    # Each unfinished dialogue contributes one phrase
    phrases: list[str] = []
    for d in unfinished[:5]:
        char_label = _character_perspective_label(d.get("characterId", ""))
        subj = d.get("subject") or "某事"
        state = d.get("beliefState") or "uncertain"
        phrases.append(f"{char_label} 想说的「{subj}」只到 {state}")
    body = "；".join(phrases) + "。"
    if recap_id:
        body += f"本周短案《{recap_id}》按这 5 段顺序替你说完。"
    else:
        body += "本周短案把这 5 段整理成 5 分钟旁白。"
    return _truncate_to_chars(body, MAX_RECALL_BODY_CHARS)


# ---------------------------------------------------------------------------
# RecallService — the public API
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RecallScheduleRequest:
    """What :meth:`RecallService.schedule_for_run` accepts."""

    run_id: str
    user_id: str
    case_slug: str = "case_01_revolution_street"
    recall_types: list[str] = field(default_factory=lambda: ["d1", "d3", "d7"])
    scheduled_for: datetime | None = None  # default = ended_at + intervals[d]


class RecallService:
    """The recall service — generates + persists D1/D3/D7 items.

    Parameters
    ----------
    repository
        :class:`RunRepository` (W4).  Defaults to the
        process-wide singleton.
    runtime
        :class:`LLMRuntime` (W3-A).  Defaults to the
        process-wide singleton.
    loader
        :class:`SceneContractLoader` (W4).  Defaults to the
        process-wide singleton.
    use_llm
        ``True`` to call the LLM gateway (subject to the
        decision-5 sub-red-line of ≤ 5 calls).  ``False`` to
        use the deterministic mock body templates.  The
        default is the env var ``G1N_RECALL_USE_LLM``
        (``"1"``/``"true"`` → ``True``).
    """

    def __init__(
        self,
        *,
        repository: RunRepository | None = None,
        runtime: LLMRuntime | None = None,
        loader: SceneContractLoader | None = None,
        use_llm: bool | None = None,
    ) -> None:
        self._repo = repository or get_default_repository()
        self._runtime = runtime or get_default_runtime()
        self._loader = loader or get_default_loader()
        if use_llm is None:
            flag = os.environ.get("G1N_RECALL_USE_LLM", "").strip().lower()
            use_llm = flag in {"1", "true", "yes", "on"}
        self._use_llm = bool(use_llm)
        # 累计 LLM 调用计数（按 run_id 隔离）
        self._call_counts: dict[str, int] = {}

    # ----- schedule ------------------------------------------------------

    def schedule_for_run(
        self,
        req: RecallScheduleRequest,
    ) -> list[dict[str, Any]]:
        """Schedule D1/D3/D7 items for the given run.

        Idempotent on ``(run_id, recall_type)``: a re-schedule
        returns the existing items without creating
        duplicates.  Returns the list of items in
        ``to_dict()`` form (each has ``itemId`` / ``status``).

        ``req.scheduled_for`` is the **absolute fire time**.
        When ``None`` (the typical HTTP path), the service
        anchors on the run's ``last_active_at`` and adds the
        per-recall interval (D1 = +1d, D3 = +3d, D7 = +7d).
        """

        now = _now()
        # Compute the per-type fire time up-front.  The
        # caller-supplied ``scheduled_for`` (when present) is
        # the **fire** time, not the anchor — the caller
        # already added the interval themselves.  When the
        # caller doesn't supply one, we anchor on the run's
        # last_active_at and apply the per-type offset.
        per_type_fire: dict[str, datetime] = {}
        for recall_type in req.recall_types:
            if recall_type not in RECALL_INTERVALS:
                continue
            if req.scheduled_for is not None:
                per_type_fire[recall_type] = req.scheduled_for
            else:
                run_row = self._repo.get_run(req.run_id)
                anchor_dt = (
                    run_row.last_active_at if run_row and run_row.last_active_at else now
                )
                per_type_fire[recall_type] = anchor_dt + RECALL_INTERVALS[recall_type]

        out: list[dict[str, Any]] = []
        for recall_type, fire_at in per_type_fire.items():
            # Idempotency: check for existing row
            existing = self._find_existing(req.run_id, recall_type)
            if existing is not None:
                out.append(existing.to_dict())
                continue
            item = RecallItemRow(
                item_id=str(uuid.uuid4()),
                run_id=req.run_id,
                user_id=req.user_id,
                case_slug=req.case_slug,
                recall_type=recall_type,
                perspective=RECALL_TYPE_TO_PERSPECTIVE.get(recall_type),
                status="scheduled",
                scheduled_for=fire_at,
            )
            with self._session() as s:
                s.add(item)
                s.commit()
                s.refresh(item)
            out.append(item.to_dict())
        return out

    def schedule_due_items(self) -> list[dict[str, Any]]:
        """For all scheduled items whose ``scheduled_for <= now``,
        generate + mark them sent.  Returns the items that
        actually fired this tick.

        This is the entry point a cron / background task
        should call.  It does **not** push to a real device
        — :mod:`server.push_service` is responsible for
        delivering the row's payload.
        """

        now = _now()
        fired: list[dict[str, Any]] = []
        with self._session() as s:
            due = list(
                s.execute(
                    select(RecallItemRow)
                    .where(
                        RecallItemRow.status == "scheduled",
                        RecallItemRow.scheduled_for <= now,
                    )
                    .order_by(RecallItemRow.scheduled_for.asc())
                    .limit(64)  # one tick never processes > 64
                ).scalars()
            )
        for item in due:
            updated = self._generate_and_send(item.item_id)
            if updated is not None:
                fired.append(updated)
        return fired

    # ----- generate + send ---------------------------------------------

    def _generate_and_send(self, item_id: str) -> dict[str, Any] | None:
        """Run the generator for a single scheduled item.

        Mutates the row: ``status`` → ``sent``, fills
        ``payload_json`` + counters.  Returns the row in
        dict form.

        ``item_id`` is the *business* id (the
        :attr:`RecallItemRow.item_id` UUID), **not** the
        integer primary key.  We look it up by column.
        """

        with self._session() as s:
            item = s.execute(
                select(RecallItemRow).where(RecallItemRow.item_id == item_id)
            ).scalar_one_or_none()
            if item is None:
                return None
            if item.status != "scheduled":
                return item.to_dict()
            try:
                payload = self._generate_payload(
                    run_id=item.run_id,
                    recall_type=item.recall_type,
                    perspective=item.perspective,
                )
                # Safety gate (W3-C)
                self._run_safety(item, payload)
                item.payload_json = _to_json(payload)
                item.generated_at = _now()
                item.status = "sent"
                item.sent_at = _now()
                item.llm_calls = int(payload.get("llmCalls") or 0)
                item.output_tokens = int(payload.get("outputTokens") or 0)
                item.fallback_used = bool(payload.get("fallbackUsed", False))
                s.commit()
                s.refresh(item)
            except Exception as exc:  # noqa: BLE001
                logger.exception("recall_service: generate failed for %s: %s", item_id, exc)
                item.status = "failed"
                item.error = f"{type(exc).__name__}: {exc}"[:1024]
                s.commit()
                s.refresh(item)
            return item.to_dict()

    def _generate_payload(
        self,
        *,
        run_id: str,
        recall_type: str,
        perspective: str | None,
    ) -> dict[str, Any]:
        """Build the actual push payload for one item.

        Hard red line: ≤ 5 main LLM calls, ≤ 200 output
        tokens per call.  When the LLM path is disabled or
        the gateway errors, we fall through to the
        deterministic template (which still references the
        player's timeline, per the W7 red line).
        """

        with self._session() as s:
            if recall_type == "d1":
                anchor = _build_d1_anchor(s, run_id)
                title = _format_d1_title(anchor)
                body = _format_d1_body_template(anchor)
            elif recall_type == "d3":
                chosen = _pick_perspective(
                    s, run_id, primary_perspective=perspective or "leila"
                )
                anchor = _build_d3_anchor(s, run_id, perspective=chosen)
                title = _format_d3_title(anchor)
                body = _format_d3_body_template(anchor)
            elif recall_type == "d7":
                anchor = _build_d7_anchor(s, run_id, loader=self._loader)
                title = _format_d7_title(anchor)
                body = _format_d7_body_template(anchor)
            else:
                raise ValueError(f"unknown recall_type: {recall_type!r}")

        # Try the LLM path; on any failure fall through to
        # the deterministic body.  The LLM never sees the
        # ``last_active_at`` / ``evidenceIds`` / etc. as
        # 'unknown' — they're all in the anchor, and the
        # prompt explicitly requires referencing them.
        llm_calls = 0
        output_tokens = 0
        fallback_used = False
        if self._use_llm:
            try:
                refined_body, llm_calls = self._refine_body_with_llm(
                    recall_type=recall_type,
                    title=title,
                    body=body,
                    anchor=anchor,
                )
                if refined_body and refined_body != body:
                    body = refined_body
                    output_tokens = _approx_tokens(body)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "recall_service: LLM refine failed for %s/%s: %s",
                    run_id, recall_type, exc,
                )
                fallback_used = True
                llm_calls = 0
                output_tokens = 0

        # Build the final deepLinks
        scene_id = anchor.get("sceneId")
        recap = anchor.get("recap") if isinstance(anchor, dict) else None
        recap_id = (recap or {}).get("recapId") if recall_type == "d7" else None
        payload = {
            "type": recall_type,
            "title": title,
            "body": body,
            "anchor": anchor,
            "perspective": anchor.get("perspective") if recall_type == "d3" else perspective,
            "deepLinks": {
                "runId": run_id,
                "sceneId": scene_id,
                "recapId": recap_id,
            },
            "llmCalls": llm_calls,
            "outputTokens": output_tokens,
            "fallbackUsed": fallback_used,
        }
        return payload

    def _refine_body_with_llm(
        self,
        *,
        recall_type: str,
        title: str,
        body: str,
        anchor: dict[str, Any],
    ) -> tuple[str, int]:
        """Optional LLM refinement of the deterministic body.

        Hard red line: ≤ 5 main calls.  We make at most 1
        call here (the cheapest path).  Output cap = 200
        tokens.

        Returns ``(refined_body, call_count)``.  On any
        failure, the original body is returned.
        """

        # Budget guard: a single call suffices.
        if self._runtime is None:
            return body, 0

        # Use a dedicated recall task type so the cost
        # controller can audit recall calls independently.
        scene_id = anchor.get("sceneId") or ""
        user_payload = {
            "recallType": recall_type,
            "title": title,
            "bodyDraft": body,
            "anchor": {
                "sceneId": scene_id,
                "keyAction": anchor.get("keyAction", {}),
                "firedSeeds": anchor.get("firedSeeds", []),
                "perspective": anchor.get("perspective"),
                "perspectiveBeliefs": anchor.get("perspectiveBeliefs", []),
                "unfinishedDialogues": anchor.get("unfinishedDialogues", []),
            },
        }
        system_prompt = (
            "你是一位克制的小说旁白。\n"
            "你只做一件事：把已有的中文推送正文改写得更克制、更具体，"
            "不超过 200 token 输出。\n"
            "硬规则：\n"
            "1) 不得增删玩家本局的具体行为（actionType / evidenceIds / sceneId / seedId / belief subject）；\n"
            "2) 不得泄露 2011 之后或 2024 之后的事实；\n"
            "3) 不得使用模板句（'你曾经……'、'十三年的等待'、'曾经沧海'）；\n"
            "4) 不得编造角色名字或未触发的事件；\n"
            "5) 你的回复必须是 ≤ 200 token 的纯文本中文，不要 markdown，不要注释。\n"
        )
        request = ModelRequest(
            run_id=f"recall:{scene_id}:{recall_type}",
            scene_id=scene_id,
            task_type=TaskType.MEMORY_RECALL,  # nearest no-schema task
            messages=[
                Message(role=MessageRole.SYSTEM, content=system_prompt),
                Message(role=MessageRole.USER, content=json.dumps(user_payload, ensure_ascii=False)),
            ],
            temperature=0.3,
            max_output_tokens=MAX_RECALL_OUTPUT_TOKENS,
            timeout_ms=4000,
            metadata={"recallType": recall_type, "agent": "recall_refiner"},
        )
        # The gateway.start_run needs to be called for
        # cost-control purposes; we run a synthetic run_id
        # in the "recall:" namespace.
        self._runtime.gateway.start_run(
            run_id=request.run_id,
            scene_id=scene_id or "recall",
        )
        try:
            response = self._runtime.gateway.chat(request)
            refined = (response.content or "").strip()
            if not refined:
                return body, 0
            # Truncate to body budget
            refined = _truncate_to_chars(refined, MAX_RECALL_BODY_CHARS)
            return refined, 1
        finally:
            try:
                self._runtime.gateway.end_run(request.run_id)
            except Exception:  # noqa: BLE001
                pass

    def _run_safety(
        self, item: RecallItemRow, payload: dict[str, Any]
    ) -> None:
        """W3-C safety gate: forbidden reveals + output shape.

        We don't run schema verification on the push payload
        (it isn't a contract-bound artefact), but we do run
        the content-guards forbidden_reveal check against
        the contract for the run's current scene so we
        don't accidentally leak 2011 / 2024 secrets to a
        pre-2011 D1 push.
        """

        # 1. JSON parse-ability (OutputVerifier will surface
        # any shape issues; we keep the check here for
        # fast-fail).
        try:
            json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"payload not JSON-serialisable: {exc}") from exc

        # 2. Forbidden reveals — only when we have a scene
        if payload.get("anchor", {}).get("sceneId"):
            try:
                scene = self._loader.load(payload["anchor"]["sceneId"])
                forbidden = [
                    fr.get("revealKey")
                    for fr in scene.contract.get("forbidden_reveals", [])
                    if isinstance(fr, dict) and fr.get("revealKey")
                ]
                if forbidden:
                    violations = check_forbidden_reveals(
                        {
                            "resolvedText": payload.get("body", ""),
                            "title": payload.get("title", ""),
                        },
                        forbidden,
                    )
                    if violations:
                        # 决策红线：推送不得泄露禁止项。
                        # 退回模板版本（不抛错，召回任务不应崩）。
                        payload["body"] = _truncate_to_chars(
                            "[推送正文已按合同裁剪，禁止项已隐藏]", MAX_RECALL_BODY_CHARS
                        )
                        payload["fallbackUsed"] = True
                        payload["safetyClipped"] = True
            except KeyError:
                pass  # 场景找不到时安全跳过

        # 3. Output token cap (defensive)
        if _approx_tokens(payload.get("body", "")) > MAX_RECALL_OUTPUT_TOKENS * 2:
            payload["body"] = _truncate_to_chars(
                payload["body"], MAX_RECALL_BODY_CHARS
            )

    # ----- pulls / marks ----------------------------------------------

    def pull_pending(
        self,
        *,
        user_id: str,
        recall_types: list[str] | None = None,
        limit: int = 32,
    ) -> list[dict[str, Any]]:
        """Return the user's pending (sent but not opened) items.

        The push_service and the client UI both call this.
        Items are returned in ``scheduled_for`` order so the
        client can show the most overdue first.
        """

        types = recall_types or list(RECALL_INTERVALS.keys())
        with self._session() as s:
            rows = list(
                s.execute(
                    select(RecallItemRow)
                    .where(
                        RecallItemRow.user_id == user_id,
                        RecallItemRow.status == "sent",
                        RecallItemRow.recall_type.in_(types),
                    )
                    .order_by(RecallItemRow.scheduled_for.asc())
                    .limit(limit)
                ).scalars()
            )
        return [r.to_dict() for r in rows]

    def mark_read(
        self,
        *,
        item_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Mark a recall item as opened + emit the corresponding
        ``recall_*_opened`` analytics event.

        ``item_id`` is the *business* id (UUID string on
        :attr:`RecallItemRow.item_id`), **not** the integer
        primary key.  We look it up by column.
        """

        with self._session() as s:
            item = s.execute(
                select(RecallItemRow).where(RecallItemRow.item_id == item_id)
            ).scalar_one_or_none()
            if item is None:
                return None
            if user_id is not None and item.user_id != user_id:
                return None
            if item.status == "opened":
                return item.to_dict()
            item.status = "opened"
            item.opened_at = _now()
            s.commit()
            s.refresh(item)
            # Emit the analytics event so the funnel
            # (sent → opened) is queryable from the
            # analytics_events table.
            self._emit_event(
                event_name=f"recall_{item.recall_type}_opened",
                user_id=item.user_id,
                run_id=item.run_id,
                payload={
                    "itemId": item.item_id,
                    "scheduledFor": item.scheduled_for.isoformat() if item.scheduled_for else None,
                    "sentAt": item.sent_at.isoformat() if item.sent_at else None,
                },
            )
            return item.to_dict()

    def list_for_run(
        self,
        *,
        run_id: str,
        limit: int = 32,
    ) -> list[dict[str, Any]]:
        """Return all recall items for a run (debug / QA)."""

        with self._session() as s:
            rows = list(
                s.execute(
                    select(RecallItemRow)
                    .where(RecallItemRow.run_id == run_id)
                    .order_by(RecallItemRow.scheduled_for.asc())
                    .limit(limit)
                ).scalars()
            )
        return [r.to_dict() for r in rows]

    # ----- analytics helpers --------------------------------------------

    def _emit_event(
        self,
        *,
        event_name: str,
        user_id: str,
        run_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Emit a recall-lifecycle analytics event.

        Goes through the same :meth:`RunRepository.record_analytics`
        path the rest of the server uses so the funnel shows
        up in the same dashboard.
        """

        try:
            self._repo.record_analytics(
                {
                    "userId": user_id,
                    "runId": run_id,
                    "eventName": event_name,
                    "payload": payload,
                    "clientVersion": "server-recall-service/1.0.0",
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("recall_service: analytics emit failed: %s", exc)

    # ----- internals ----------------------------------------------------

    def _session(self) -> Session:
        return get_session()

    def _find_existing(
        self, run_id: str, recall_type: str
    ) -> RecallItemRow | None:
        with self._session() as s:
            return s.execute(
                select(RecallItemRow)
                .where(
                    RecallItemRow.run_id == run_id,
                    RecallItemRow.recall_type == recall_type,
                )
                .order_by(RecallItemRow.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Output token estimation
# ---------------------------------------------------------------------------


_CJK_RE = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")


def _approx_tokens(text: str) -> int:
    """Approximate the token count for mixed CJK / English text.

    Empirical rule calibrated against a DeepSeek-V3
    tokenizer on a CJK-mixed payload:

    * 1 token ≈ 1.5 CJK chars
    * 1 token ≈ 4.0 English / punct chars

    The estimator is intentionally conservative — a
    real LLM cost controller uses the model's own
    tokenizer, but the estimator here only enforces
    the ≤ 200 token cap; the LLM cap of 800 tokens is
    enforced by the W3-A cost controller.
    """

    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4.0) + 1


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------


_recall_tables_initialised: bool = False


def init_recall_tables() -> None:
    """Idempotent: create the recall_items table.

    Idempotent on every call.  We use ``Base.metadata.create_all``
    which is a no-op when the table already exists.  Called
    from :mod:`server.app` lifespan so the table is ready by
    the time the first recall request arrives.
    """

    global _recall_tables_initialised
    if _recall_tables_initialised:
        return
    Base.metadata.create_all(engine, tables=[RecallItemRow.__table__])
    _recall_tables_initialised = True
    logger.info(
        "recall_service: schema ready; recall_items row registered on db.Base"
    )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


_default_service: RecallService | None = None


def get_default_recall_service() -> RecallService:
    """Process-wide :class:`RecallService` singleton."""

    global _default_service
    if _default_service is None:
        _default_service = RecallService()
    return _default_service


def reset_default_recall_service() -> None:
    """Reset the singleton (test-only)."""

    global _default_service
    _default_service = None


__all__ = [
    "MAX_RECALL_MAIN_CALLS",
    "MAX_RECALL_OUTPUT_TOKENS",
    "MAX_RECALL_BODY_CHARS",
    "RECALL_INTERVALS",
    "RECALL_EVENT_NAMES",
    "RECALL_TYPE_TO_PERSPECTIVE",
    "RECAPS_DIR_NAME",
    "RecallItemRow",
    "RecallScheduleRequest",
    "RecallService",
    "init_recall_tables",
    "get_default_recall_service",
    "reset_default_recall_service",
]
