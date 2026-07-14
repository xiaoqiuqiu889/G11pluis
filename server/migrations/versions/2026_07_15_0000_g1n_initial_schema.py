"""initial schema — 11 tables

Revision ID: 2026_07_15_0000
Revises:
Create Date: 2026-07-15 00:00:00.000000

The 11 tables correspond to the v0.1 PRD §3 core data tables
listed in the W4 brief:

* game_runs            — top-level run
* world_snapshots      — full WorldSnapshot JSON, one per event
* game_events          — append-only event ledger
* character_beliefs    — per-(character, subject) belief row
* memories             — recallable memory items
* artifacts            — artifact state mirror
* model_calls          — LLM call audit (decision 5)
* entitlements         — user purchase state (decision 4)
* causal_seeds         — dormant / fired cross-era seeds
* narrative_contracts  — cached scene contracts
* branch_timelines     — replay branches (decision 4)

The migration matches ``server/db.py`` 1:1 — running this on
an empty database is equivalent to calling ``init_db()``.  The
``init_db`` path is the W4 dev/CI default; this migration is
the production escape hatch.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "2026_07_15_0000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- game_runs ------------------------------------------------------
    op.create_table(
        "game_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("case_slug", sa.String(64), nullable=False, server_default="case_01_revolution_street"),
        sa.Column("current_scene_id", sa.String(64), nullable=False, server_default="photo_lab_2008"),
        sa.Column("era", sa.String(64), nullable=False, server_default="2008"),
        sa.Column("event_sequence", sa.Integer, nullable=False, server_default="0"),
        sa.Column("phase", sa.String(32), nullable=False, server_default="setup"),
        sa.Column("ending_id", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_archived", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_mock", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("schema_version", sa.String(16), nullable=False, server_default="1.0.0"),
        sa.Column("meta_json", sa.Text, server_default="{}"),
    )
    op.create_index("ix_game_runs_user", "game_runs", ["user_id"])

    # ---- world_snapshots ------------------------------------------------
    op.create_table(
        "world_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("game_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_sequence", sa.Integer, nullable=False),
        sa.Column("snapshot_json", sa.Text, nullable=False),
        sa.Column("checksum", sa.String(128), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "event_sequence", name="uq_world_snapshot_per_event"),
    )
    op.create_index("ix_world_snapshots_run", "world_snapshots", ["run_id"])
    op.create_index("ix_world_snapshots_event", "world_snapshots", ["event_sequence"])

    # ---- game_events ----------------------------------------------------
    op.create_table(
        "game_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("game_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_sequence", sa.Integer, nullable=False),
        sa.Column("scene_id", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("action_payload_json", sa.Text, server_default="{}"),
        sa.Column("validated_delta_json", sa.Text, server_default="{}"),
        sa.Column("causal_seed", sa.String(64), nullable=True),
        sa.Column("random_seed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("outcome_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "idempotency_key", name="uq_event_idempotency"),
    )
    op.create_index("ix_game_events_run", "game_events", ["run_id"])
    op.create_index("ix_game_events_event", "game_events", ["event_sequence"])
    op.create_index("ix_game_events_scene", "game_events", ["scene_id"])
    op.create_index("ix_game_events_idem", "game_events", ["idempotency_key"])
    op.create_index("ix_game_events_outcome", "game_events", ["outcome_id"])

    # ---- character_beliefs ---------------------------------------------
    op.create_table(
        "character_beliefs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("game_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("character_id", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(128), nullable=False),
        sa.Column("belief_state", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("evidence_memory_id", sa.String(64), nullable=True),
        sa.Column("previous_state", sa.String(32), nullable=True),
        sa.Column("event_sequence", sa.Integer, nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id", "character_id", "subject", "event_sequence",
            name="uq_belief_per_event",
        ),
    )
    op.create_index("ix_character_beliefs_run", "character_beliefs", ["run_id"])
    op.create_index("ix_character_beliefs_char", "character_beliefs", ["character_id"])
    op.create_index("ix_character_beliefs_subj", "character_beliefs", ["subject"])
    op.create_index("ix_character_beliefs_event", "character_beliefs", ["event_sequence"])

    # ---- memories -------------------------------------------------------
    op.create_table(
        "memories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("game_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_id", sa.String(64), nullable=False),
        sa.Column("owner_character_id", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("emotional_weight", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("distortion_type", sa.String(32), nullable=True),
        sa.Column("involved_character_ids_json", sa.Text, server_default="[]"),
        sa.Column("recall_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("decay_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("formed_at_event", sa.Integer, nullable=False),
        sa.Column("last_recalled_at_event", sa.Integer, nullable=True),
        sa.Column("embedding_hash", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "memory_id", name="uq_memory_per_run"),
    )
    op.create_index("ix_memories_run", "memories", ["run_id"])
    op.create_index("ix_memories_memory", "memories", ["memory_id"])
    op.create_index("ix_memories_owner", "memories", ["owner_character_id"])

    # ---- artifacts ------------------------------------------------------
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("game_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_id", sa.String(64), nullable=False),
        sa.Column("scene_id", sa.String(64), nullable=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(64), nullable=False, server_default="intact"),
        sa.Column("is_revealed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("location", sa.String(128), nullable=True),
        sa.Column("tags_json", sa.Text, server_default="[]"),
        sa.Column("last_event_sequence", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "artifact_id", name="uq_artifact_per_run"),
    )
    op.create_index("ix_artifacts_run", "artifacts", ["run_id"])
    op.create_index("ix_artifacts_artifact", "artifacts", ["artifact_id"])
    op.create_index("ix_artifacts_owner", "artifacts", ["owner_id"])
    op.create_index("ix_artifacts_scene", "artifacts", ["scene_id"])

    # ---- model_calls ----------------------------------------------------
    op.create_table(
        "model_calls",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("scene_id", sa.String(64), nullable=True),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("agent", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_cny", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("finish_reason", sa.String(32), nullable=False, server_default="stop"),
        sa.Column("degradation_level", sa.String(8), nullable=True),
        sa.Column("used_fallback", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="1"),
        sa.Column("metadata_json", sa.Text, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_calls_request", "model_calls", ["request_id"])
    op.create_index("ix_model_calls_run", "model_calls", ["run_id"])
    op.create_index("ix_model_calls_scene", "model_calls", ["scene_id"])

    # ---- entitlements ---------------------------------------------------
    op.create_table(
        "entitlements",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("credits", sa.Integer, nullable=False, server_default="0"),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta_json", sa.Text, server_default="{}"),
        sa.UniqueConstraint("user_id", "scope", name="uq_entitlement_user_scope"),
    )
    op.create_index("ix_entitlements_user", "entitlements", ["user_id"])
    op.create_index("ix_entitlements_scope", "entitlements", ["scope"])

    # ---- causal_seeds ---------------------------------------------------
    op.create_table(
        "causal_seeds",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("game_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("seed_id", sa.String(64), nullable=False),
        sa.Column("source_scene", sa.String(64), nullable=False),
        sa.Column("source_event_id", sa.String(64), nullable=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("trigger_condition_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("target_scenes_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("echo_intensity", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("is_secret", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_dormant", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("fired_at_event", sa.Integer, nullable=True),
        sa.Column("fired_in_scene_id", sa.String(64), nullable=True),
        sa.Column("linked_character_ids_json", sa.Text, server_default="[]"),
        sa.Column("decay_rate", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("tags_json", sa.Text, server_default="[]"),
        sa.Column("era_span_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "seed_id", name="uq_seed_per_run"),
    )
    op.create_index("ix_causal_seeds_run", "causal_seeds", ["run_id"])
    op.create_index("ix_causal_seeds_seed", "causal_seeds", ["seed_id"])

    # ---- narrative_contracts -------------------------------------------
    op.create_table(
        "narrative_contracts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("case_slug", sa.String(64), nullable=False),
        sa.Column("scene_id", sa.String(64), nullable=False),
        sa.Column("era", sa.String(64), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("contract_json", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_slug", "scene_id", name="uq_contract_case_scene"),
    )
    op.create_index("ix_narrative_contracts_case", "narrative_contracts", ["case_slug"])
    op.create_index("ix_narrative_contracts_scene", "narrative_contracts", ["scene_id"])

    # ---- branch_timelines ----------------------------------------------
    op.create_table(
        "branch_timelines",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("game_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("source_run_id", sa.String(64), nullable=False),
        sa.Column("fork_event_sequence", sa.Integer, nullable=False),
        sa.Column("ending_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meta_json", sa.Text, server_default="{}"),
        sa.UniqueConstraint("run_id", "branch_id", name="uq_branch_per_run"),
    )
    op.create_index("ix_branch_timelines_run", "branch_timelines", ["run_id"])
    op.create_index("ix_branch_timelines_branch", "branch_timelines", ["branch_id"])
    op.create_index("ix_branch_timelines_source", "branch_timelines", ["source_run_id"])

    # ---- analytics_events ----------------------------------------------
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("event_name", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("client_version", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analytics_events_user", "analytics_events", ["user_id"])
    op.create_index("ix_analytics_events_run", "analytics_events", ["run_id"])
    op.create_index("ix_analytics_events_name", "analytics_events", ["event_name"])


def downgrade() -> None:
    # Drop in reverse order
    op.drop_table("analytics_events")
    op.drop_table("branch_timelines")
    op.drop_table("narrative_contracts")
    op.drop_table("causal_seeds")
    op.drop_table("entitlements")
    op.drop_table("model_calls")
    op.drop_table("artifacts")
    op.drop_table("memories")
    op.drop_table("character_beliefs")
    op.drop_table("game_events")
    op.drop_table("world_snapshots")
    op.drop_table("game_runs")
