"""Database layer — SQLAlchemy 2.0 engine + 11 ORM models.

W4 deliverable: persistent store for runs, snapshots, events,
beliefs, memories, artifacts, model_calls, entitlements,
causal_seeds, narrative_contracts, branch_timelines.

Database selection
------------------

Default = SQLite (no install required).  Production = PostgreSQL
via the ``G1N_DB_URL`` environment variable.

The schema is created lazily on first request via
:meth:`init_db` (``Base.metadata.create_all``); this keeps
the deployment friction near zero.  An Alembic-friendly
schema is shipped under ``server/migrations/`` for production
migrations.

Tables
------

The 11 tables correspond to the v0.1 PRD §3 core data tables
listed in the W4 brief.  Naming is ``snake_case`` to match
the existing ``docs/design/`` vocabulary.

Write-domain isolation
----------------------

The Resolver is the *only* place that mutates
:mod:`server.engine` state.  This module is the persistence
boundary: it does **not** enforce invariants, it only
serialises whatever the Resolver has already validated.  All
HTTP endpoints that mutate canonical state go through the
Resolver (see :mod:`server.app`).
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

logger = logging.getLogger("g1n.db")

# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


def _default_db_url() -> str:
    """Resolve the database URL.

    Priority:
        1. ``G1N_DB_URL`` environment variable.
        2. ``DATABASE_URL`` (Heroku-style convention).
        3. SQLite file under ``./data/g1n.db`` (default).
    """

    url = os.environ.get("G1N_DB_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url

    # Default to a SQLite file inside the project's data/
    # directory.  The directory is created lazily.
    project_root = pathlib.Path(__file__).resolve().parents[1]
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'g1n.db').as_posix()}"


DB_URL: str = _default_db_url()


def build_engine(url: str | None = None) -> Engine:
    """Build a SQLAlchemy engine.

    For SQLite, ``check_same_thread=False`` so FastAPI's
    threadpool can share the connection.  For PostgreSQL, we
    set a sane pool size.
    """

    resolved = url or DB_URL
    if resolved.startswith("sqlite"):
        return create_engine(
            resolved,
            connect_args={"check_same_thread": False},
            future=True,
        )
    return create_engine(
        resolved,
        pool_size=int(os.environ.get("G1N_DB_POOL", "5")),
        max_overflow=int(os.environ.get("G1N_DB_MAX_OVERFLOW", "10")),
        pool_pre_ping=True,
        future=True,
    )


# Single shared engine for the app; tests can build their own.
engine: Engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# ---------------------------------------------------------------------------
# Base + JSON helper
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base for G1N persistent state."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _from_json(value: str | None) -> Any:
    if value is None or value == "":
        return None
    return json.loads(value)


# SQLite needs the same DateTime handling as Postgres for the
# application — we always store timezone-aware UTC.
@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:  # pragma: no cover
    """Set SQLite pragmas on connect.  Postgres connections are a no-op."""

    # Heuristic — only SQLite drivers expose the ``cursor`` attribute
    # with a ``execute`` method that accepts ``PRAGMA``.
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
    except Exception:  # noqa: BLE001
        # Non-SQLite driver; ignore.
        return


# ---------------------------------------------------------------------------
# 11 ORM models
# ---------------------------------------------------------------------------


class GameRun(Base):
    """A player's playthrough — the top-level entity.

    Each run has many snapshots, events, beliefs, and so
    on.  ``current_snapshot_id`` points at the latest
    :class:`WorldSnapshotRow` so a fresh ``GET /v1/runs/:id``
    can hydrate the canonical state without scanning the
    event log.
    """

    __tablename__ = "game_runs"

    run_id = Column(String(64), primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    case_slug = Column(String(64), nullable=False, default="case_01_revolution_street")
    current_scene_id = Column(String(64), nullable=False, default="photo_lab_2008")
    era = Column(String(64), nullable=False, default="2008")
    event_sequence = Column(Integer, nullable=False, default=0)
    phase = Column(String(32), nullable=False, default="setup")
    ending_id = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)
    last_active_at = Column(
        DateTime(timezone=True), default=_now_utc, onupdate=_now_utc, nullable=False
    )
    ended_at = Column(DateTime(timezone=True), nullable=True)
    is_archived = Column(Boolean, default=False, nullable=False)
    is_mock = Column(Boolean, default=True, nullable=False)
    schema_version = Column(String(16), nullable=False, default="1.0.0")
    meta_json = Column(Text, default="{}")

    snapshots = relationship("WorldSnapshotRow", back_populates="run", cascade="all, delete-orphan")
    events = relationship("GameEventRow", back_populates="run", cascade="all, delete-orphan")
    branches = relationship("BranchTimelineRow", back_populates="run", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "userId": self.user_id,
            "caseSlug": self.case_slug,
            "currentSceneId": self.current_scene_id,
            "era": self.era,
            "eventSequence": self.event_sequence,
            "phase": self.phase,
            "endingId": self.ending_id,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "lastActiveAt": self.last_active_at.isoformat() if self.last_active_at else None,
            "endedAt": self.ended_at.isoformat() if self.ended_at else None,
            "isArchived": self.is_archived,
            "isMock": self.is_mock,
            "schemaVersion": self.schema_version,
        }


class WorldSnapshotRow(Base):
    """A complete :class:`engine.world_snapshot.WorldSnapshot` JSON payload.

    Each accepted :class:`engine.resolver.ResolverOutcome`
    produces a new row.  The latest row for a run is the
    canonical state; the older rows are the timeline.
    """

    __tablename__ = "world_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("game_runs.run_id", ondelete="CASCADE"), index=True, nullable=False)
    event_sequence = Column(Integer, nullable=False, index=True)
    snapshot_json = Column(Text, nullable=False)
    checksum = Column(String(128), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "event_sequence", name="uq_world_snapshot_per_event"),
    )

    run = relationship("GameRun", back_populates="snapshots")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "runId": self.run_id,
            "eventSequence": self.event_sequence,
            "snapshot": _from_json(self.snapshot_json),
            "checksum": self.checksum,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class GameEventRow(Base):
    """An :class:`engine.event_log.GameEvent` — append-only event ledger."""

    __tablename__ = "game_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("game_runs.run_id", ondelete="CASCADE"), index=True, nullable=False)
    event_sequence = Column(Integer, nullable=False, index=True)
    scene_id = Column(String(64), nullable=False, index=True)
    actor_id = Column(String(64), nullable=False)
    action_type = Column(String(32), nullable=False)
    action_payload_json = Column(Text, default="{}")
    validated_delta_json = Column(Text, default="{}")
    causal_seed = Column(String(64), nullable=True)
    random_seed = Column(Integer, default=0, nullable=False)
    idempotency_key = Column(String(128), nullable=False, index=True)
    outcome_id = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "idempotency_key", name="uq_event_idempotency"),
    )

    run = relationship("GameRun", back_populates="events")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "runId": self.run_id,
            "eventSequence": self.event_sequence,
            "sceneId": self.scene_id,
            "actorId": self.actor_id,
            "actionType": self.action_type,
            "actionPayload": _from_json(self.action_payload_json) or {},
            "validatedDelta": _from_json(self.validated_delta_json) or {},
            "causalSeed": self.causal_seed,
            "randomSeed": self.random_seed,
            "idempotencyKey": self.idempotency_key,
            "outcomeId": self.outcome_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class CharacterBeliefRow(Base):
    """A snapshot of a single belief entry.

    Beliefs change over time; the row's ``event_sequence``
    is the sequence at which the belief was last updated.
    The Resolver writes one row per
    ``outcome.beliefUpdates`` element; the latest row for a
    ``(runId, characterId, subject)`` tuple is the current
    belief.
    """

    __tablename__ = "character_beliefs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("game_runs.run_id", ondelete="CASCADE"), index=True, nullable=False)
    character_id = Column(String(64), nullable=False, index=True)
    subject = Column(String(128), nullable=False, index=True)
    belief_state = Column(String(32), nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    evidence_memory_id = Column(String(64), nullable=True)
    previous_state = Column(String(32), nullable=True)
    event_sequence = Column(Integer, nullable=False, index=True)
    reason_code = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "character_id",
            "subject",
            "event_sequence",
            name="uq_belief_per_event",
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "runId": self.run_id,
            "characterId": self.character_id,
            "subject": self.subject,
            "beliefState": self.belief_state,
            "confidence": self.confidence,
            "evidenceMemoryId": self.evidence_memory_id,
            "previousState": self.previous_state,
            "eventSequence": self.event_sequence,
            "reasonCode": self.reason_code,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class MemoryRow(Base):
    """A memory item, distinct from the belief state.

    Memories are the *content* a character recalls; beliefs
    are their *interpretation* of that content.  One memory
    can inform many beliefs.
    """

    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("game_runs.run_id", ondelete="CASCADE"), index=True, nullable=False)
    memory_id = Column(String(64), nullable=False, index=True)
    owner_character_id = Column(String(64), nullable=False, index=True)
    summary = Column(Text, nullable=False)
    emotional_weight = Column(Float, default=0.0, nullable=False)
    distortion_type = Column(String(32), nullable=True)
    involved_character_ids_json = Column(Text, default="[]")
    recall_count = Column(Integer, default=0, nullable=False)
    decay_score = Column(Float, default=0.0, nullable=False)
    formed_at_event = Column(Integer, nullable=False)
    last_recalled_at_event = Column(Integer, nullable=True)
    embedding_hash = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "memory_id", name="uq_memory_per_run"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "runId": self.run_id,
            "memoryId": self.memory_id,
            "ownerCharacterId": self.owner_character_id,
            "summary": self.summary,
            "emotionalWeight": self.emotional_weight,
            "distortionType": self.distortion_type,
            "involvedCharacterIds": _from_json(self.involved_character_ids_json) or [],
            "recallCount": self.recall_count,
            "decayScore": self.decay_score,
            "formedAtEvent": self.formed_at_event,
            "lastRecalledAtEvent": self.last_recalled_at_event,
            "embeddingHash": self.embedding_hash,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class ArtifactRow(Base):
    """An artifact's current state (owner, location, revealed flag).

    The full artifact state is also kept inside the
    :class:`WorldSnapshotRow`; this row is the
    queryable / archival mirror that powers the archive
    panel ("show me everything the player has held").
    """

    __tablename__ = "artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("game_runs.run_id", ondelete="CASCADE"), index=True, nullable=False)
    artifact_id = Column(String(64), nullable=False, index=True)
    scene_id = Column(String(64), nullable=True, index=True)
    owner_id = Column(String(64), nullable=False, index=True)
    state = Column(String(64), nullable=False, default="intact")
    is_revealed = Column(Boolean, default=False, nullable=False)
    location = Column(String(128), nullable=True)
    tags_json = Column(Text, default="[]")
    last_event_sequence = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now_utc, onupdate=_now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "artifact_id", name="uq_artifact_per_run"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "runId": self.run_id,
            "artifactId": self.artifact_id,
            "sceneId": self.scene_id,
            "ownerId": self.owner_id,
            "state": self.state,
            "isRevealed": self.is_revealed,
            "location": self.location,
            "tags": _from_json(self.tags_json) or [],
            "lastEventSequence": self.last_event_sequence,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class _PKColumn(BigInteger):
    """Auto-incrementing primary key that works on both SQLite and Postgres.

    SQLite stores BigInteger as a 64-bit INT; the autoincrement
    flag is honoured for both ``INTEGER PRIMARY KEY`` (SQLite)
    and ``BIGSERIAL PRIMARY KEY`` (Postgres).
    """


# Use Integer (autoincrement-friendly on SQLite) and let
# Postgres use BIGSERIAL via the BigInteger variant.  This
# avoids "NOT NULL constraint failed" on SQLite where
# BigInteger + autoincrement sometimes fails to wire up the
# implicit ROWID alias.
_PKInteger = BigInteger().with_variant(Integer, "sqlite")


class ModelCallRow(Base):
    """Audit row for a single LLM call (decision 5 acceptance: every
    call must leave a record).

    Inserted by the :class:`server.model.gateway.ModelGateway`
    after every call, including fallbacks.  Provides the data
    for the per-run cost summary and the P0 alert.
    """

    __tablename__ = "model_calls"

    id = Column(_PKInteger, primary_key=True, autoincrement=True)
    request_id = Column(String(64), nullable=False, index=True)
    run_id = Column(String(64), index=True, nullable=False)
    scene_id = Column(String(64), nullable=True, index=True)
    task_type = Column(String(32), nullable=False)
    agent = Column(String(32), nullable=False)
    model = Column(String(64), nullable=False)
    provider = Column(String(32), nullable=False)
    input_tokens = Column(Integer, default=0, nullable=False)
    output_tokens = Column(Integer, default=0, nullable=False)
    latency_ms = Column(Integer, default=0, nullable=False)
    cost_cny = Column(Float, default=0.0, nullable=False)
    finish_reason = Column(String(32), default="stop", nullable=False)
    degradation_level = Column(String(8), nullable=True)
    used_fallback = Column(Boolean, default=False, nullable=False)
    attempts = Column(Integer, default=1, nullable=False)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "requestId": self.request_id,
            "runId": self.run_id,
            "sceneId": self.scene_id,
            "taskType": self.task_type,
            "agent": self.agent,
            "model": self.model,
            "provider": self.provider,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "latencyMs": self.latency_ms,
            "costCny": self.cost_cny,
            "finishReason": self.finish_reason,
            "degradationLevel": self.degradation_level,
            "usedFallback": self.used_fallback,
            "attempts": self.attempts,
            "metadata": _from_json(self.metadata_json) or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class EntitlementRow(Base):
    """A user's unlocked content (decisions 2 + 4).

    One row per (user, scope) — ``scope`` is one of
    ``passport`` / ``collectors`` / ``parallel_ops`` /
    ``credits`` / ``pov_unlock`` / ``keepsake``.  The
    default user starts with the **free sample** scope and
    200 credits (decision 4: 200 积分 包).

    W8-1 added columns (additive; ``_apply_w8_schema_migrations``
    ALTERs the table on first start against an existing DB):
    * ``auto_renew``            — boolean, subscription auto-renew flag
    * ``payment_provider_txn_id`` — string, the payment gateway txn / charge id
    * ``revoked_reason``        — string, set when an entitlement is refunded / revoked
    """

    __tablename__ = "entitlements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    scope = Column(String(32), nullable=False, index=True)
    credits = Column(Integer, default=0, nullable=False)
    purchased_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    # W8-1 additions (set via ALTER TABLE on existing DBs)
    auto_renew = Column(Boolean, default=False, nullable=False, server_default="0")
    payment_provider_txn_id = Column(String(128), nullable=True, index=True)
    revoked_reason = Column(String(64), nullable=True)
    meta_json = Column(Text, default="{}")

    __table_args__ = (
        UniqueConstraint("user_id", "scope", name="uq_entitlement_user_scope"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "userId": self.user_id,
            "scope": self.scope,
            "credits": self.credits,
            "purchasedAt": self.purchased_at.isoformat() if self.purchased_at else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "autoRenew": bool(self.auto_renew),
            "paymentProviderTxnId": self.payment_provider_txn_id,
            "revokedReason": self.revoked_reason,
            "metadata": _from_json(self.meta_json) or {},
        }


class CausalSeedRow(Base):
    """A causal seed, either dormant (active in a future scene) or fired.

    Dormant seeds propagate across scenes; the Resolver is the
    only writer.  One row per seed per (run, event_sequence)
    transition.
    """

    __tablename__ = "causal_seeds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("game_runs.run_id", ondelete="CASCADE"), index=True, nullable=False)
    seed_id = Column(String(64), nullable=False, index=True)
    source_scene = Column(String(64), nullable=False)
    source_event_id = Column(String(64), nullable=True)
    description = Column(Text, default="", nullable=False)
    trigger_condition_json = Column(Text, default="{}", nullable=False)
    target_scenes_json = Column(Text, default="[]", nullable=False)
    echo_intensity = Column(Float, default=0.5, nullable=False)
    is_secret = Column(Boolean, default=False, nullable=False)
    is_dormant = Column(Boolean, default=True, nullable=False)
    fired_at_event = Column(Integer, nullable=True)
    fired_in_scene_id = Column(String(64), nullable=True)
    linked_character_ids_json = Column(Text, default="[]")
    decay_rate = Column(Float, default=0.0, nullable=False)
    tags_json = Column(Text, default="[]")
    era_span_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "seed_id", name="uq_seed_per_run"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "runId": self.run_id,
            "seedId": self.seed_id,
            "sourceScene": self.source_scene,
            "sourceEventId": self.source_event_id,
            "description": self.description,
            "triggerCondition": _from_json(self.trigger_condition_json) or {},
            "targetScenes": _from_json(self.target_scenes_json) or [],
            "echoIntensity": self.echo_intensity,
            "isSecret": self.is_secret,
            "isDormant": self.is_dormant,
            "firedAtEvent": self.fired_at_event,
            "firedInSceneId": self.fired_in_scene_id,
            "linkedCharacterIds": _from_json(self.linked_character_ids_json) or [],
            "decayRate": self.decay_rate,
            "tags": _from_json(self.tags_json) or [],
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class NarrativeContractRow(Base):
    """A scene's narrative contract (immutable per case).

    Cached on first read; the Resolver consults the row's
    JSON when validating the active scene.  Allows the
    content team to add new scenes without re-deploying the
    server.
    """

    __tablename__ = "narrative_contracts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_slug = Column(String(64), nullable=False, index=True)
    scene_id = Column(String(64), nullable=False, index=True)
    era = Column(String(64), nullable=False)
    title = Column(String(128), nullable=False)
    contract_json = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("case_slug", "scene_id", name="uq_contract_case_scene"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "caseSlug": self.case_slug,
            "sceneId": self.scene_id,
            "era": self.era,
            "title": self.title,
            "contract": _from_json(self.contract_json) or {},
            "isActive": self.is_active,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class BranchTimelineRow(Base):
    """A branch (replay variant) of an existing run.

    Decision 4: the player may pay for "parallel plays" that
    replay from a chosen event_sequence with alternative
    choices.  Each branch is a separate :class:`GameRun`
    row that shares the source run's lineage via
    ``source_run_id`` + ``fork_event_sequence``.
    """

    __tablename__ = "branch_timelines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("game_runs.run_id", ondelete="CASCADE"), index=True, nullable=False)
    branch_id = Column(String(64), nullable=False, index=True)
    label = Column(String(128), nullable=False, default="")
    source_run_id = Column(String(64), nullable=False, index=True)
    fork_event_sequence = Column(Integer, nullable=False)
    ending_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)
    meta_json = Column(Text, default="{}")

    __table_args__ = (
        UniqueConstraint("run_id", "branch_id", name="uq_branch_per_run"),
    )

    run = relationship("GameRun", back_populates="branches")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "runId": self.run_id,
            "branchId": self.branch_id,
            "label": self.label,
            "sourceRunId": self.source_run_id,
            "forkEventSequence": self.fork_event_sequence,
            "endingId": self.ending_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "metadata": _from_json(self.meta_json) or {},
        }


class AnalyticsEventRow(Base):
    """A client-side analytics event (埋点).

    Decision 4 / brief: "POST /v1/analytics/events" must
    exist; this row is its target.  No joins — pure
    write-and-forget; queries are dashboard-side.
    """

    __tablename__ = "analytics_events"

    id = Column(_PKInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=True, index=True)
    run_id = Column(String(64), nullable=True, index=True)
    event_name = Column(String(64), nullable=False, index=True)
    payload_json = Column(Text, default="{}", nullable=False)
    client_version = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "userId": self.user_id,
            "runId": self.run_id,
            "eventName": self.event_name,
            "payload": _from_json(self.payload_json) or {},
            "clientVersion": self.client_version,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


# ===========================================================================
# W8-1 — Real accounts + real payment + cross-device entitlements
# ===========================================================================
#
# W4 was local-mock only.  W8-1 adds 7 new tables (additive; existing
# rows / columns are NOT touched).  New columns on ``entitlements``
# are backfilled by ``_apply_w8_schema_migrations`` below; existing
# rows read as ``auto_renew=false`` / ``payment_provider_txn_id=null``
# / ``revoked_reason=null``.
#
# Design constraints (from the W8-1 brief):
# * Schema validation must apply to the mock provider too (no skipping
#   the JSON-Schema check just because we are running offline).
# * Webhook events must be auditable end-to-end: every incoming event
#   is recorded with ``signature_verified`` + ``provider_event_id``
#   before any entitlement mutation.
# * Refunds must reference both the order and the gateway; partial
#   consumption uses a stored ``prorated_consumption_rate`` so the
#   refund math is reproducible from the row alone.
# * Run ownership rows are the cross-device hand-off; the JWT issued
#   for a cross-device claim is a stateless artifact (verifiable with
#   the server's HMAC secret), but the *binding* (which user owns
#   which run, on which device) is the durable truth.


class UserRow(Base):
    """A real account (W8-1).

    Status flow: ``active`` -> ``suspended`` -> ``deleted``.
    The ``demo-user`` legacy from W4 keeps its row but gets
    ``password_hash=null`` (no real password); the legacy
    endpoint :func:`server.app.get_entitlements` still
    honours ``userId=demo-user`` so the W4 client keeps
    working.
    """

    __tablename__ = "users"

    id = Column(String(64), primary_key=True)
    email = Column(String(255), nullable=True, unique=True, index=True)
    display_name = Column(String(128), nullable=False, default="")
    status = Column(String(16), nullable=False, default="active")
    is_anonymous = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)
    last_active_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)
    meta_json = Column(Text, default="{}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "displayName": self.display_name,
            "status": self.status,
            "isAnonymous": bool(self.is_anonymous),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "lastActiveAt": self.last_active_at.isoformat() if self.last_active_at else None,
            "metadata": _from_json(self.meta_json) or {},
        }


class UserCredentialRow(Base):
    """A bcrypt password hash for an email-password account.

    No plaintext password column exists.  A user with
    ``oauth_bindings`` but no ``user_credentials`` row is
    OAuth-only.
    """

    __tablename__ = "user_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    algorithm = Column(String(16), nullable=False, default="bcrypt")
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)
    rotated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_credential_per_user"),
    )


class OAuthBindingRow(Base):
    """Link a third-party identity to a local user.

    ``provider`` is one of ``email_password`` (legacy link),
    ``wechat``, ``google``, ``apple``, ...  ``provider_user_id``
    is the provider's stable id (Wechat openid, Google sub, ...).
    """

    __tablename__ = "oauth_bindings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    provider = Column(String(32), nullable=False, index=True)
    provider_user_id = Column(String(255), nullable=False, index=True)
    provider_meta_json = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_binding_provider_uid"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "userId": self.user_id,
            "provider": self.provider,
            "providerUserId": self.provider_user_id,
            "providerMeta": _from_json(self.provider_meta_json) or {},
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class PaymentOrderRow(Base):
    """A real paid order (W8-1).

    Lifecycle: ``pending`` -> ``paid`` -> ``refunded`` (full / partial)
    or ``pending`` -> ``cancelled`` / ``expired``.

    The order's ``user_id`` is the *buyer* (i.e. the
    authenticated user).  When the user is not yet logged in
    the brief says: do NOT force a purchase — so the order
    row is only created **after** a successful login, and
    the HTTP layer rejects unauthenticated purchase attempts.
    """

    __tablename__ = "payment_orders"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False)
    product_id = Column(String(32), nullable=False, index=True)
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String(8), nullable=False, default="CNY")
    status = Column(String(16), nullable=False, default="pending", index=True)
    provider = Column(String(32), nullable=False, default="mock")
    provider_session_id = Column(String(128), nullable=True, index=True)
    provider_payment_intent_id = Column(String(128), nullable=True, index=True)
    payment_method = Column(String(32), nullable=True)
    credits_granted = Column(Integer, default=0, nullable=False)
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    refunded_cents = Column(Integer, default=0, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "userId": self.user_id,
            "productId": self.product_id,
            "amountCents": self.amount_cents,
            "currency": self.currency,
            "status": self.status,
            "provider": self.provider,
            "providerSessionId": self.provider_session_id,
            "providerPaymentIntentId": self.provider_payment_intent_id,
            "paymentMethod": self.payment_method,
            "creditsGranted": self.credits_granted,
            "refundedCents": self.refunded_cents,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "paidAt": self.paid_at.isoformat() if self.paid_at else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": _from_json(self.meta_json) or {},
        }


class PaymentWebhookEventRow(Base):
    """Audit row for every incoming webhook event.

    ``signature_verified`` is the gate: any row with
    ``signature_verified=false`` is treated as a tampering
    attempt and **never** mutates an entitlement.  The
    ``provider_event_id`` unique-index dedupes replays
    (Stripe / Wechat may retry the same event id).
    """

    __tablename__ = "payment_webhook_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False, index=True)
    provider_event_id = Column(String(128), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    order_id = Column(String(64), nullable=True, index=True)
    signature_verified = Column(Boolean, nullable=False, default=False)
    raw_payload = Column(Text, nullable=False, default="{}")
    processed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    received_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_webhook_event_per_provider"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "providerEventId": self.provider_event_id,
            "eventType": self.event_type,
            "orderId": self.order_id,
            "signatureVerified": bool(self.signature_verified),
            "rawPayload": _from_json(self.raw_payload) or {},
            "processedAt": self.processed_at.isoformat() if self.processed_at else None,
            "errorMessage": self.error_message,
            "receivedAt": self.received_at.isoformat() if self.received_at else None,
        }


class RefundRow(Base):
    """A refund against a :class:`PaymentOrderRow`.

    ``prorated_consumption_rate`` is captured **at refund
    time** so the math is reproducible from the row alone
    even if the underlying product is later updated.  Range:
    0.0 (no consumption) -> 1.0 (fully consumed / private
    ending already unlocked, refund = 0).
    """

    __tablename__ = "refunds"

    id = Column(String(64), primary_key=True)
    order_id = Column(String(64), ForeignKey("payment_orders.id", ondelete="RESTRICT"), index=True, nullable=False)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False)
    reason = Column(String(64), nullable=False, default="customer_request")
    refund_type = Column(String(16), nullable=False, default="full")  # full | partial | none
    amount_cents = Column(Integer, nullable=False)
    prorated_consumption_rate = Column(Float, nullable=False, default=0.0)
    status = Column(String(16), nullable=False, default="pending", index=True)
    provider_refund_id = Column(String(128), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    requested_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    meta_json = Column(Text, default="{}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "orderId": self.order_id,
            "userId": self.user_id,
            "reason": self.reason,
            "refundType": self.refund_type,
            "amountCents": self.amount_cents,
            "proratedConsumptionRate": self.prorated_consumption_rate,
            "status": self.status,
            "providerRefundId": self.provider_refund_id,
            "errorMessage": self.error_message,
            "requestedAt": self.requested_at.isoformat() if self.requested_at else None,
            "processedAt": self.processed_at.isoformat() if self.processed_at else None,
            "metadata": _from_json(self.meta_json) or {},
        }


class RunOwnershipRow(Base):
    """Cross-device run ownership binding (W8-1).

    A run may be claimed by multiple devices (the user
    starts on Web, continues on App).  Each binding carries
    a ``device_kind`` (``web`` / ``app`` / ``cli``) and a
    ``device_id`` (client-stamped).  The ``last_active_at``
    is the high-watermark for "where they left off"; the
    client polls this on every resume to know which device
    has the freshest state.
    """

    __tablename__ = "run_ownership"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("game_runs.run_id", ondelete="CASCADE"), index=True, nullable=False)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    device_kind = Column(String(16), nullable=False, default="web")
    device_id = Column(String(128), nullable=False)
    device_label = Column(String(128), nullable=True)
    last_active_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)
    last_event_sequence = Column(Integer, default=0, nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "device_id", name="uq_run_ownership_run_device"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "runId": self.run_id,
            "userId": self.user_id,
            "deviceKind": self.device_kind,
            "deviceId": self.device_id,
            "deviceLabel": self.device_label,
            "lastActiveAt": self.last_active_at.isoformat() if self.last_active_at else None,
            "lastEventSequence": self.last_event_sequence,
            "isPrimary": bool(self.is_primary),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create all tables.  Idempotent — safe to call on every startup."""

    Base.metadata.create_all(engine)
    _apply_w8_schema_migrations()
    logger.info(
        "DB schema ready: %s tables on %s",
        len(Base.metadata.tables),
        _safe_db_label(DB_URL),
    )


def _apply_w8_schema_migrations() -> None:
    """Idempotent ALTER TABLE pass for the W8-1 additions.

    ``Base.metadata.create_all`` is happy with new tables but
    does not backfill new columns on pre-existing tables.
    For the ``entitlements`` table we have to do that by
    hand, and SQLite (the default) does not support
    ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` until
    recent versions.  We use ``PRAGMA table_info`` to make
    the migration deterministic across SQLite / Postgres.
    """

    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if not inspector.has_table("entitlements"):
        # Fresh DB — ``create_all`` already produced the new
        # columns via the ORM model.  Nothing to do.
        return
    existing = {col["name"] for col in inspector.get_columns("entitlements")}

    dialect = engine.dialect.name
    additions = [
        ("auto_renew", "BOOLEAN NOT NULL DEFAULT 0"),
        ("payment_provider_txn_id", "VARCHAR(128)"),
        ("revoked_reason", "VARCHAR(64)"),
    ]
    with engine.begin() as conn:
        for col_name, col_type in additions:
            if col_name in existing:
                continue
            # SQLite uses INTEGER (not BOOLEAN) for the type
            # of ``auto_renew``; use the dialect-appropriate
            # representation.
            if dialect == "sqlite" and col_name == "auto_renew":
                col_type = "INTEGER NOT NULL DEFAULT 0"
            if dialect == "sqlite":
                col_type = col_type.replace("VARCHAR", "TEXT")
            conn.execute(text(f'ALTER TABLE entitlements ADD COLUMN "{col_name}" {col_type}'))
            logger.info("migration: entitlements.%s added", col_name)


def _safe_db_label(url: str) -> str:
    """Sanitise a DB URL for log output (strip password)."""

    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            _, host = rest.split("@", 1)
            return f"{scheme}://***@{host}"
    return url


def get_session() -> Session:
    """Get a new Session.  Caller is responsible for closing."""

    return SessionLocal()


def healthcheck() -> dict[str, Any]:
    """Return a health snapshot for /health."""

    try:
        with SessionLocal() as session:
            from sqlalchemy import text
            session.execute(text("SELECT 1"))
        return {"db": "ok", "url": _safe_db_label(DB_URL)}
    except Exception as exc:  # noqa: BLE001
        return {"db": "error", "url": _safe_db_label(DB_URL), "error": str(exc)}


__all__ = [
    "Base",
    "engine",
    "SessionLocal",
    "init_db",
    "get_session",
    "healthcheck",
    "GameRun",
    "WorldSnapshotRow",
    "GameEventRow",
    "CharacterBeliefRow",
    "MemoryRow",
    "ArtifactRow",
    "ModelCallRow",
    "EntitlementRow",
    "CausalSeedRow",
    "NarrativeContractRow",
    "BranchTimelineRow",
    "AnalyticsEventRow",
    # W8-1 additions
    "UserRow",
    "UserCredentialRow",
    "OAuthBindingRow",
    "PaymentOrderRow",
    "PaymentWebhookEventRow",
    "RefundRow",
    "RunOwnershipRow",
    # W8-2 additions
    "ByokKeyRow",
    "RunCostLedgerRow",
    "CreditLedgerRow",
]


# ===========================================================================
# W8-2 · BYOK + 余额监控 + LLM runtime 串联
# ===========================================================================


class ByokKeyRow(Base):
    """An encrypted, player-supplied LLM API key (W8-2).

    Why a separate table (not on ``users``)?

    * The lifetime of a key is independent of the user row.
      A user may register several keys for several providers
      (OpenAI / DeepSeek / Qwen) and revoke them individually.
    * Key rotation is a per-key operation — the same user
      may want to swap the DeepSeek key without touching
      the OpenAI key.
    * The ``key_fingerprint`` is exposed to the client (so
      the user can tell which key is which); the
      ``encrypted_key`` is **never** exposed.

    Red-line enforcement
    --------------------

    * The plaintext API key is **never** written to logs.
      ``to_dict`` and :class:`server.byok` strip the
      ``encrypted_key`` column on every read path.
    * The fingerprint is a SHA-256 of the plaintext; it
      lets the client label "OpenAI key #a3f1..." without
      revealing the secret.
    * The encryption envelope is AES-GCM via
      :class:`cryptography.fernet.Fernet`.  The master key
      comes from :envvar:`G1N_BYOK_ENCRYPTION_KEY`; the
      module generates an ephemeral key on first use if the
      env var is missing (with a loud log warning).

    Rate limiting
    -------------

    * ``rate_limit_per_minute`` is the per-user call cap
      the BYOK manager enforces (token bucket).
    * ``consecutive_failures`` is incremented on every
      transport / HTTP error and reset on success; a
      streak of 5 in a row flips ``status='disabled'`` and
      the manager falls back to the server key.
    """

    __tablename__ = "byok_keys"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    provider = Column(String(32), nullable=False, index=True)  # openai_compatible / deepseek / qwen
    label = Column(String(64), nullable=False, default="")
    # SHA-256 of the plaintext key (first 16 hex chars).  Exposed.
    key_fingerprint = Column(String(32), nullable=False, index=True)
    # Fernet ciphertext.  NEVER returned to the client.
    encrypted_key = Column(Text, nullable=False)
    # Optional overrides (e.g. a user-supplied proxy URL).
    base_url = Column(String(256), nullable=True)
    model = Column(String(64), nullable=True)
    # Lifecycle.
    status = Column(String(16), nullable=False, default="active")  # active | disabled | revoked
    rate_limit_per_minute = Column(Integer, nullable=False, default=20)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    last_error = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    meta_json = Column(Text, default="{}")

    __table_args__ = (
        UniqueConstraint("user_id", "provider", "label", name="uq_byok_key_user_provider_label"),
    )

    def to_dict(self, *, include_secret: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "userId": self.user_id,
            "provider": self.provider,
            "label": self.label,
            "keyFingerprint": self.key_fingerprint,
            "baseUrl": self.base_url,
            "model": self.model,
            "status": self.status,
            "rateLimitPerMinute": int(self.rate_limit_per_minute),
            "consecutiveFailures": int(self.consecutive_failures),
            "lastError": self.last_error,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "lastUsedAt": self.last_used_at.isoformat() if self.last_used_at else None,
            "revokedAt": self.revoked_at.isoformat() if self.revoked_at else None,
            "metadata": _from_json(self.meta_json) or {},
        }
        if include_secret:
            # Only the BYOK manager's internal callers use
            # this; the HTTP surface strips it.  Documented
            # in the class docstring's red-line block.
            d["encryptedKey"] = self.encrypted_key
        return d


class RunCostLedgerRow(Base):
    """Per-run AI cost roll-up (W8-2).

    One row per (run, scope) — usually ``scope='main'`` for
    the 30-45 min vertical slice.  Updated by
    :mod:`server.balance_monitor` on each LLM call; the
    balance monitor also reads it on every check so a
    player who's used 18 of 20 main calls sees the right
    "low balance" prompt even if the model_calls table
    has not been aggregated yet.

    Reset semantics (W8-1 issue #5)
    -------------------------------

    The ledger is **not** reset by a refund — refunds revoke
    the entitlement but the AI cost that was already spent
    stays on the books.  What the refund *does* reset is the
    player's :class:`EntitlementRow.credits` (so the next
    purchase starts fresh; see
    :meth:`EntitlementService.issue` for the
    un-revoke + top-up logic).
    """

    __tablename__ = "run_cost_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), index=True, nullable=False)
    user_id = Column(String(64), index=True, nullable=False)
    scope = Column(String(32), nullable=False, default="main")
    main_calls = Column(Integer, nullable=False, default=0)
    fallback_calls = Column(Integer, nullable=False, default=0)
    cost_cny = Column(Float, nullable=False, default=0.0)
    byok_calls = Column(Integer, nullable=False, default=0)
    server_key_calls = Column(Integer, nullable=False, default=0)
    last_degradation = Column(String(8), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now_utc, onupdate=_now_utc, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "scope", name="uq_run_cost_ledger_run_scope"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "runId": self.run_id,
            "userId": self.user_id,
            "scope": self.scope,
            "mainCalls": int(self.main_calls),
            "fallbackCalls": int(self.fallback_calls),
            "costCny": float(self.cost_cny),
            "byokCalls": int(self.byok_calls),
            "serverKeyCalls": int(self.server_key_calls),
            "lastDegradation": self.last_degradation,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class CreditLedgerRow(Base):
    """An explicit credit-movement ledger (W8-2, refund reset trace).

    The :class:`EntitlementRow.credits` column is the
    *current balance* — the source of truth.  This ledger
    is the *append-only* audit log of every change, so
    operations can answer "what happened to user X's
    credits after the refund?" without rebuilding state
    from the model_calls table.

    Entries
    -------
    * ``grant``    — issued by a successful payment webhook.
    * ``consume``  — one or more LLM calls debited the
                     entitlement (the field ``quantity``
                     is the call count).
    * ``refund``   — a refund (full or partial) clawed back
                     the entitlement.
    * ``restore``  — re-purchase after a refund restored
                     the entitlement (so credits > 0 again).
    * ``reissue``  — the entitlement was re-issued
                     (e.g. ``EntitlementService.issue``
                     topped up an existing row).
    """

    __tablename__ = "credit_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), index=True, nullable=False)
    scope = Column(String(32), nullable=False, index=True)
    entry_type = Column(String(16), nullable=False)  # grant | consume | refund | restore | reissue
    quantity = Column(Integer, nullable=False)  # +N for grants/restores, -N for consume/refund
    balance_after = Column(Integer, nullable=False)  # credits column after this entry
    related_order_id = Column(String(64), nullable=True, index=True)
    related_refund_id = Column(String(64), nullable=True, index=True)
    related_run_id = Column(String(64), nullable=True, index=True)
    note = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "userId": self.user_id,
            "scope": self.scope,
            "entryType": self.entry_type,
            "quantity": int(self.quantity),
            "balanceAfter": int(self.balance_after),
            "relatedOrderId": self.related_order_id,
            "relatedRefundId": self.related_refund_id,
            "relatedRunId": self.related_run_id,
            "note": self.note,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
