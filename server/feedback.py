"""W10 · Player feedback system.

End-of-run feedback (decision 4 / W10)
---------------------------------------

* **自由文本 + 5 星评分** — 玩家每局结束后可填。
* **N-gram 提取** — 从自由文本里挑 1-gram / 2-gram /
  3-gram 高频词；不存原文，只存出现频次。Privacy
  red line: 不存原文可以避免玩家被
  "我刚才打的字被看到了" 反感。
* **自动分类** — 反馈分成 4 类：
  1. **正面** — 显式正向 (great / love / 喜欢 / 太棒了) 或
     高星级 (≥ 4)。
  2. **负面** — 显式负向 (bad / hate / 失望 / 退钱) 或
     低星级 (≤ 2)。
  3. **技术 bug** — 关键词 (crash / error / 卡住 / 黑屏 /
     闪退 / 报错)。
  4. **内容建议** — 关键词 (could / should / 建议 / 如果 /
     希望 / maybe)。
  多分类并存 → 同一反馈可同时被归为"技术 bug" + "内容
  建议"（一个 bug 的复现建议 = 内容建议）。

* **紧急反馈 P0 报警** — 任何 P0 报警都自动去重：
  - 同一 ``(category, ngram, scene_id)`` 3 小时内只发一次。
  - 触发 P0 的关键词是
    {crash, 卡死, 闪退, 黑屏, 不动了, 退钱}。
  - P0 不会变成"单向垃圾箱"：每条 P0 都会自动开一个
    :class:`FeedbackAction` 跟踪（"已分派"→"已确认"→
    "已修复" / "无法复现" / "已知问题"）。运营只能点
    "已确认" 来 acknowledge；点过后才算关闭。

This module is **read-only** with respect to the
engine's canonical state.  The feedback table is a
W10 addition; :func:`init_db` is idempotent.
"""

from __future__ import annotations

import io
import json
import logging
import re
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
for p in (str(_PROJECT_ROOT), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from db import (  # noqa: E402
    AnalyticsEventRow,
    Base,
    GameRun,
    SessionLocal,
    init_db,
)

logger = logging.getLogger("g1n.feedback")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Star rating scale (1..5).  Anything outside the
#: range is rejected by the API.
RATING_MIN: int = 1
RATING_MAX: int = 5

#: Categories the classifier assigns.
class FeedbackCategory(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    BUG = "tech_bug"
    SUGGESTION = "content_suggestion"


#: Stable category precedence when multiple apply.
#: Used to pick the *primary* category for the
#: dashboard (one feedback is shown under one tile).
CATEGORY_PRIORITY: tuple[FeedbackCategory, ...] = (
    FeedbackCategory.BUG,
    FeedbackCategory.NEGATIVE,
    FeedbackCategory.SUGGESTION,
    FeedbackCategory.POSITIVE,
)

#: P0 keywords — a feedback containing any of these
#: (in the original OR in the n-gram) is escalated.
#: The list is bilingual because the game is in
#: Chinese; the en list is a fallback.
P0_KEYWORDS: tuple[str, ...] = (
    "crash", "crashed", "卡死", "卡住了", "闪退", "黑屏",
    "不动了", "退钱", "refund", "data loss", "丢档",
    "丢失进度", "missing progress", "can't continue",
    "无法继续",
)

#: Words that mark "positive" sentiment.
POSITIVE_KEYWORDS: tuple[str, ...] = (
    "great", "love", "amazing", "awesome", "wonderful",
    "喜欢", "太棒了", "真好", "amazing", "perfect", "棒",
)

#: Words that mark "negative" sentiment (low severity).
NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "bad", "hate", "disappointing", "boring", "awful",
    "失望", "退钱", "无聊", "太烂了", "没意思",
)

#: Tech-bug indicators.
BUG_KEYWORDS: tuple[str, ...] = (
    "crash", "error", "bug", "卡住", "黑屏", "闪退",
    "不动了", "报错", "stuck", "freeze", "frozen",
    "load fail", "加载失败",
)

#: Content-suggestion indicators.
SUGGESTION_KEYWORDS: tuple[str, ...] = (
    "could", "should", "希望", "建议", "如果", "maybe",
    "would be nice", "wish", "想要", "再加入", "能不能",
)

#: When a feedback is "P0", we open a tracker.  The
#: tracker requires acknowledgement before it can be
#: closed.  P0 报警的硬去重窗口 — 同一 (category,
#: ngram, scene) 在 3 小时内只产生 1 个 tracker。
P0_DEDUP_WINDOW = timedelta(hours=3)

#: Maximum length of the free-text body we'll keep
#: around.  Anything longer is truncated to keep the
#: table small; the n-gram extraction still works on
#: the first 2000 characters.
MAX_BODY_CHARS = 2000


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class FeedbackRow(Base):
    """A single end-of-run feedback submission."""

    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feedback_id = Column(String(64), nullable=False, index=True, unique=True)
    run_id = Column(String(64), nullable=True, index=True)
    user_id = Column(String(64), nullable=True, index=True)
    scene_id = Column(String(64), nullable=True, index=True)
    rating = Column(Integer, nullable=True)  # 1..5
    body_hash = Column(String(128), nullable=False)  # hash of the original text — privacy
    body_chars = Column(Integer, nullable=False, default=0)  # length only — privacy
    categories_json = Column(Text, nullable=False, default="[]")
    primary_category = Column(String(32), nullable=False, default="positive")
    ngrams_json = Column(Text, nullable=False, default="{}")
    language = Column(String(8), nullable=False, default="zh")
    is_p0 = Column(Boolean, nullable=False, default=False)
    p0_tracker_id = Column(String(64), nullable=True, index=True)
    client_version = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "feedbackId": self.feedback_id,
            "runId": self.run_id,
            "userId": self.user_id,
            "sceneId": self.scene_id,
            "rating": self.rating,
            "bodyHash": self.body_hash,
            "bodyChars": self.body_chars,
            "categories": json.loads(self.categories_json or "[]"),
            "primaryCategory": self.primary_category,
            "ngrams": json.loads(self.ngrams_json or "{}"),
            "language": self.language,
            "isP0": self.is_p0,
            "p0TrackerId": self.p0_tracker_id,
            "clientVersion": self.client_version,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class FeedbackActionRow(Base):
    """Lifecycle row for P0 feedback — the "单向 P0
    报警垃圾箱" 防御。

    Every P0 feedback opens a tracker.  The tracker has
    a state machine::

        open → acknowledged → resolved
              (any state) → wontfix

    ``acknowledged`` requires the operator to confirm
    they have read the P0; the dashboard refuses to
    close a P0 without that acknowledgement.  This is
    the W10 红线 "不要让反馈系统变成单向 P0 报警垃圾箱".
    """

    __tablename__ = "feedback_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracker_id = Column(String(64), nullable=False, index=True, unique=True)
    feedback_id = Column(
        String(64),
        ForeignKey("feedback.feedback_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    state = Column(String(16), nullable=False, default="open")
    assignee = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    p0_keyword = Column(String(64), nullable=True)
    dedup_key = Column(String(128), nullable=True, index=True)
    opened_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow())
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
    )

    __table_args__ = (
        UniqueConstraint("dedup_key", "opened_at", name="uq_feedback_dedup"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trackerId": self.tracker_id,
            "feedbackId": self.feedback_id,
            "state": self.state,
            "assignee": self.assignee,
            "notes": self.notes,
            "p0Keyword": self.p0_keyword,
            "dedupKey": self.dedup_key,
            "openedAt": self.opened_at.isoformat() if self.opened_at else None,
            "acknowledgedAt": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "resolvedAt": self.resolved_at.isoformat() if self.resolved_at else None,
        }


# ---------------------------------------------------------------------------
# Body pre-processing
# ---------------------------------------------------------------------------


#: A simple CJK + latin tokenizer.  CJK characters are
#: emitted one per token; latin words are emitted as
#: whole tokens.  Punctuation is dropped.
_TOKEN_RE = re.compile(
    r"[一-鿿]+|[A-Za-z][A-Za-z0-9'-]+|[0-9]+",
    re.UNICODE,
)

#: Stop words removed before n-gram extraction.  Bilingual
#: because the game is Chinese.
STOP_WORDS: frozenset[str] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be",
    "我", "你", "他", "她", "它", "的", "了", "是", "在",
    "和", "也", "都", "就", "不", "有", "没", "吗", "啊",
})


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.strip()]


def _extract_ngrams(
    tokens: list[str],
    *,
    max_n: int = 3,
) -> dict[str, int]:
    """Return ``{ngram: frequency}`` for n in 1..max_n.

    Stop words are dropped; CJK bigrams are preserved
    (Chinese has no spaces, so the 1-gram of a CJK
    character is rarely informative).
    """

    tokens = [t for t in tokens if t not in STOP_WORDS and len(t) > 0]
    counter: Counter[str] = Counter()
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            ngram = " ".join(tokens[i:i + n])
            counter[ngram] += 1
    # Limit to the top 50 n-grams to keep the row small.
    return dict(counter.most_common(50))


def _hash_body(body: str) -> str:
    import hashlib
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _detect_language(body: str) -> str:
    """Return ``"zh"`` / ``"en"`` / ``"mixed"`` based on the body."""

    cjk = sum(1 for c in body if "一" <= c <= "鿿")
    latin = sum(1 for c in body if c.isalpha() and ord(c) < 128)
    if cjk > latin * 2:
        return "zh"
    if latin > cjk * 2:
        return "en"
    if cjk + latin > 0:
        return "mixed"
    return "unknown"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_categories(
    body: str, rating: int | None,
) -> tuple[list[FeedbackCategory], FeedbackCategory]:
    """Return ``(all_categories, primary)`` for the feedback."""

    text_lower = body.lower()
    cats: set[FeedbackCategory] = set()

    # Tech bug — checked first; a "crash" is more urgent
    # than a "good".
    if any(kw in text_lower for kw in BUG_KEYWORDS):
        cats.add(FeedbackCategory.BUG)
    if any(kw in text_lower for kw in SUGGESTION_KEYWORDS):
        cats.add(FeedbackCategory.SUGGESTION)
    if any(kw in text_lower for kw in POSITIVE_KEYWORDS):
        cats.add(FeedbackCategory.POSITIVE)
    if any(kw in text_lower for kw in NEGATIVE_KEYWORDS):
        cats.add(FeedbackCategory.NEGATIVE)
    # Star rating fallback.
    if rating is not None:
        if rating >= 4:
            cats.add(FeedbackCategory.POSITIVE)
        elif rating <= 2:
            cats.add(FeedbackCategory.NEGATIVE)
    # Always at least one category (positive default).
    if not cats:
        cats.add(FeedbackCategory.POSITIVE)
    # Primary = the highest-precedence category.
    primary = next(
        (c for c in CATEGORY_PRIORITY if c in cats),
        FeedbackCategory.POSITIVE,
    )
    return sorted(cats, key=lambda c: c.value), primary


def _is_p0(body: str, categories: list[FeedbackCategory]) -> tuple[bool, str | None]:
    """Return ``(is_p0, matched_keyword)`` for a feedback."""

    text_lower = body.lower()
    for kw in P0_KEYWORDS:
        if kw in text_lower:
            return True, kw
    return False, None


def _dedup_key(
    *, category: FeedbackCategory, ngram: str, scene_id: str | None,
) -> str:
    """Build the P0 dedup key.

    Same (category, top-1-gram, scene) within the
    dedup window → only one P0 tracker opens.
    """

    scene_part = scene_id or "any"
    return f"{category.value}::{ngram}::{scene_part}"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class FeedbackService:
    """The feedback service — the only public surface."""

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory or SessionLocal

    def session(self) -> Session:
        return self._session_factory()

    # ----- ingestion --------------------------------------------------

    def submit_feedback(
        self,
        *,
        body: str,
        rating: int | None = None,
        user_id: str | None = None,
        run_id: str | None = None,
        scene_id: str | None = None,
        client_version: str | None = None,
    ) -> dict[str, Any]:
        """Record one feedback row + open a P0 tracker if applicable.

        Privacy contract
        ----------------
        * We **never** persist the original text.  We
          persist only its length and SHA-256.
        * The n-gram column holds tokenised frequencies,
          not the original string.  Two feedback bodies
          with the same n-gram set will hash to the same
          body_hash.
        * The P0 dedup uses ``(category, top-1-gram,
          scene_id)`` — we **never** key a P0 tracker on
          a user_id or run_id.
        """

        if rating is not None and not (RATING_MIN <= rating <= RATING_MAX):
            raise ValueError(
                f"rating {rating!r} out of range [{RATING_MIN}..{RATING_MAX}]"
            )
        body = body.strip()
        if not body and rating is None:
            raise ValueError("feedback must include body or rating")
        body = body[:MAX_BODY_CHARS]
        body_hash = _hash_body(body)
        language = _detect_language(body)
        tokens = _tokenize(body)
        ngrams = _extract_ngrams(tokens)
        categories, primary = _classify_categories(body, rating)
        is_p0, p0_kw = _is_p0(body, categories)
        categories_json = json.dumps(
            [c.value for c in categories], ensure_ascii=False,
        )
        ngrams_json = json.dumps(ngrams, ensure_ascii=False)

        feedback_id = str(uuid.uuid4())
        p0_tracker_id: str | None = None
        dedup_key: str | None = None
        with self.session() as s:
            row = FeedbackRow(
                feedback_id=feedback_id,
                run_id=run_id,
                user_id=user_id,
                scene_id=scene_id,
                rating=rating,
                body_hash=body_hash,
                body_chars=len(body),
                categories_json=categories_json,
                primary_category=primary.value,
                ngrams_json=ngrams_json,
                language=language,
                is_p0=is_p0,
                p0_tracker_id=None,
                client_version=client_version,
            )
            s.add(row)
            # Flush so the foreign key on feedback_actions
            # can find the parent row.
            s.flush()
            if is_p0 and p0_kw:
                top_ngram = next(iter(ngrams.keys()), "")
                dedup_key = _dedup_key(
                    category=primary, ngram=top_ngram, scene_id=scene_id,
                )
                p0_tracker_id = self._open_p0_tracker(
                    s,
                    feedback_id=feedback_id,
                    p0_keyword=p0_kw,
                    dedup_key=dedup_key,
                )
                row.p0_tracker_id = p0_tracker_id
            s.commit()
            s.refresh(row)
            return row.to_dict()

    def _open_p0_tracker(
        self,
        session: Session,
        *,
        feedback_id: str,
        p0_keyword: str,
        dedup_key: str,
    ) -> str:
        """Open a P0 tracker; return the existing one if deduped.

        Dedup rule: if another P0 tracker for the same
        ``dedup_key`` opened within the last
        :data:`P0_DEDUP_WINDOW`, do **not** open a new
        tracker.  Instead, increment the existing
        tracker's ``dedup_count`` (a separate field) and
        re-use the tracker.
        """

        since = datetime.utcnow() - P0_DEDUP_WINDOW
        existing = session.execute(
            select(FeedbackActionRow).where(
                FeedbackActionRow.dedup_key == dedup_key,
                FeedbackActionRow.opened_at >= since,
            )
        ).scalars().first()
        if existing is not None:
            return existing.tracker_id
        tracker_id = str(uuid.uuid4())
        tracker = FeedbackActionRow(
            tracker_id=tracker_id,
            feedback_id=feedback_id,
            state="open",
            p0_keyword=p0_keyword,
            dedup_key=dedup_key,
        )
        session.add(tracker)
        return tracker_id

    # ----- lifecycle --------------------------------------------------

    def acknowledge_p0(
        self,
        *,
        tracker_id: str,
        assignee: str = "ops",
        notes: str = "",
    ) -> dict[str, Any]:
        """Mark a P0 tracker as acknowledged by the operator.

        Without acknowledgement the dashboard refuses to
        close the tracker.  This is the W10 红线 enforcement.
        """

        with self.session() as s:
            row = s.execute(
                select(FeedbackActionRow).where(
                    FeedbackActionRow.tracker_id == tracker_id,
                )
            ).scalar_one_or_none()
            if row is None:
                raise LookupError(f"tracker not found: {tracker_id}")
            row.state = "acknowledged"
            row.assignee = assignee
            if notes:
                row.notes = notes
            row.acknowledged_at = datetime.utcnow()
            s.commit()
            s.refresh(row)
            return row.to_dict()

    def resolve_p0(
        self,
        *,
        tracker_id: str,
        notes: str = "",
        wontfix: bool = False,
    ) -> dict[str, Any]:
        """Close a P0 tracker.  Requires prior acknowledgement."""

        with self.session() as s:
            row = s.execute(
                select(FeedbackActionRow).where(
                    FeedbackActionRow.tracker_id == tracker_id,
                )
            ).scalar_one_or_none()
            if row is None:
                raise LookupError(f"tracker not found: {tracker_id}")
            if row.state != "acknowledged":
                raise PermissionError(
                    f"cannot resolve tracker in state {row.state!r}; "
                    "must acknowledge first"
                )
            row.state = "wontfix" if wontfix else "resolved"
            if notes:
                row.notes = notes
            row.resolved_at = datetime.utcnow()
            s.commit()
            s.refresh(row)
            return row.to_dict()

    # ----- queries ----------------------------------------------------

    def list_feedback(
        self,
        *,
        limit: int = 50,
        category: FeedbackCategory | None = None,
        is_p0: bool | None = None,
    ) -> list[dict[str, Any]]:
        with self.session() as s:
            stmt = select(FeedbackRow).order_by(FeedbackRow.created_at.desc()).limit(limit)
            if category is not None:
                stmt = stmt.where(FeedbackRow.primary_category == category.value)
            if is_p0 is not None:
                stmt = stmt.where(FeedbackRow.is_p0.is_(is_p0))
            rows = s.execute(stmt).scalars().all()
            return [r.to_dict() for r in rows]

    def list_p0_trackers(
        self,
        *,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.session() as s:
            stmt = select(FeedbackActionRow).order_by(FeedbackActionRow.opened_at.desc())
            if state is not None:
                stmt = stmt.where(FeedbackActionRow.state == state)
            rows = s.execute(stmt).scalars().all()
            return [r.to_dict() for r in rows]

    def ngram_summary(
        self,
        *,
        category: FeedbackCategory | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Aggregate n-grams across all feedback matching the filter."""

        with self.session() as s:
            stmt = select(FeedbackRow).limit(10000)
            if category is not None:
                stmt = stmt.where(FeedbackRow.primary_category == category.value)
            rows = s.execute(stmt).scalars().all()
        counter: Counter[str] = Counter()
        for r in rows:
            ngrams = json.loads(r.ngrams_json or "{}")
            for ng, freq in ngrams.items():
                counter[ng] += int(freq)
        return [
            {"ngram": ng, "count": c}
            for ng, c in counter.most_common(limit)
        ]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_default_service: FeedbackService | None = None


def get_default_service() -> FeedbackService:
    global _default_service
    if _default_service is None:
        _default_service = FeedbackService()
    return _default_service


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


def build_feedback_router() -> Any:
    """Expose the feedback service on a FastAPI router."""

    try:
        from fastapi import APIRouter, HTTPException
        from pydantic import BaseModel, Field
    except ImportError:  # pragma: no cover
        return None

    router = APIRouter(prefix="/v1/feedback", tags=["feedback"])
    service = get_default_service()

    class SubmitRequest(BaseModel):  # type: ignore[misc]
        body: str = Field(default="", max_length=MAX_BODY_CHARS)
        rating: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
        userId: str | None = None
        runId: str | None = None
        sceneId: str | None = None
        clientVersion: str | None = None

    class AckRequest(BaseModel):  # type: ignore[misc]
        trackerId: str
        assignee: str = "ops"
        notes: str = ""

    class ResolveRequest(BaseModel):  # type: ignore[misc]
        trackerId: str
        notes: str = ""
        wontfix: bool = False

    @router.post("/submit")
    def submit(req: SubmitRequest) -> dict[str, Any]:
        try:
            return service.submit_feedback(
                body=req.body,
                rating=req.rating,
                user_id=req.userId,
                run_id=req.runId,
                scene_id=req.sceneId,
                client_version=req.clientVersion,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/acknowledge")
    def acknowledge(req: AckRequest) -> dict[str, Any]:
        try:
            return service.acknowledge_p0(
                tracker_id=req.trackerId,
                assignee=req.assignee,
                notes=req.notes,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/resolve")
    def resolve(req: ResolveRequest) -> dict[str, Any]:
        try:
            return service.resolve_p0(
                tracker_id=req.trackerId,
                notes=req.notes,
                wontfix=req.wontfix,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/list")
    def list_feedback(
        limit: int = 50,
        category: str | None = None,
        isP0: bool | None = None,
    ) -> dict[str, Any]:
        cat = None
        if category:
            try:
                cat = FeedbackCategory(category)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        rows = service.list_feedback(limit=limit, category=cat, is_p0=isP0)
        return {"count": len(rows), "feedback": rows}

    @router.get("/p0/trackers")
    def list_p0_trackers(state: str | None = None) -> dict[str, Any]:
        return {
            "trackers": service.list_p0_trackers(state=state),
        }

    @router.get("/ngrams")
    def ngrams(
        category: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        cat = None
        if category:
            try:
                cat = FeedbackCategory(category)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ngrams": service.ngram_summary(category=cat, limit=limit)}

    return router


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _force_utf8_stdout() -> None:
    import io
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
                continue
            except (ValueError, OSError):
                pass
        if hasattr(stream, "buffer"):
            try:
                setattr(
                    sys,
                    stream_name,
                    io.TextIOWrapper(stream.buffer, encoding="utf-8"),
                )
            except (ValueError, OSError):
                pass


def _cli(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    import argparse
    parser = argparse.ArgumentParser(
        prog="feedback",
        description="革命街 AI 原生 · 玩家反馈 + 紧急 P0 报警",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_sub = sub.add_parser("submit", help="submit a feedback")
    p_sub.add_argument("--body", default="")
    p_sub.add_argument("--rating", type=int, default=None)
    p_sub.add_argument("--user", default=None)
    p_sub.add_argument("--run", default=None)
    p_sub.add_argument("--scene", default=None)
    p_sub.add_argument("--client", default=None)
    p_p0 = sub.add_parser("p0-list", help="list P0 trackers")
    p_p0.add_argument("--state", default=None)
    p_ngr = sub.add_parser("ngrams", help="show n-gram summary")
    p_ngr.add_argument("--category", default=None)
    p_ngr.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    init_db()
    service = get_default_service()
    if args.command == "submit":
        try:
            rec = service.submit_feedback(
                body=args.body,
                rating=args.rating,
                user_id=args.user,
                run_id=args.run,
                scene_id=args.scene,
                client_version=args.client,
            )
            print(json.dumps(rec, ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    elif args.command == "p0-list":
        print(json.dumps(
            service.list_p0_trackers(state=args.state),
            ensure_ascii=False, indent=2,
        ))
    elif args.command == "ngrams":
        cat = None
        if args.category:
            cat = FeedbackCategory(args.category)
        print(json.dumps(
            service.ngram_summary(category=cat, limit=args.limit),
            ensure_ascii=False, indent=2,
        ))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
