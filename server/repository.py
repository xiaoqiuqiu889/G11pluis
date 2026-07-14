"""Persistence layer — the only place that mutates ``server.db``.

The repository wraps the Resolver's output and writes the
canonical state to the persistent store.  The Resolver is
*still* the only component that decides what to write
(decision 3 / 5 / 6); the repository just makes those
decisions durable.

Write-domain isolation
----------------------

* ``server.agents.resolver.ResolverAgent`` validates and
  produces the :class:`engine.resolver.ResolverOutcome` +
  new :class:`engine.world_snapshot.WorldSnapshot`.
* :class:`RunRepository.save_outcome` then atomically:
    1. INSERTs a row into ``game_events``.
    2. INSERTs a row into ``world_snapshots``.
    3. UPSERTs every ``artifacts`` / ``character_beliefs``
       / ``causal_seeds`` / ``memories`` change.
    4. UPDATEs ``game_runs`` (event_sequence, current scene,
       phase, last_active_at).

The repository is the **only** module that should call
``session.add`` / ``session.commit`` for canonical state.
HTTP endpoints that mutate canonical state go through
``save_outcome``; ad-hoc writes elsewhere are a violation
of the write-domain isolation rule.

The repository also exposes read-only helpers
(``get_run``, ``get_snapshot``, ``list_events``,
``list_artifacts``, etc.) for the HTTP layer.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import (
    AnalyticsEventRow,
    ArtifactRow,
    BranchTimelineRow,
    CausalSeedRow,
    CharacterBeliefRow,
    EntitlementRow,
    GameEventRow,
    GameRun,
    MemoryRow,
    ModelCallRow,
    NarrativeContractRow,
    SessionLocal,
    WorldSnapshotRow,
)

logger = logging.getLogger("g1n.repository")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_json_str(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _from_json_str(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


def _ensure_entitlements_for_default_user(session: Session, user_id: str) -> None:
    """Idempotently seed the default user's free sample entitlements.

    Decision 4: default credits = 200 (matches "案件通行证
    ¥25 → 200 积分" hook in the brief).
    """

    existing = session.execute(
        select(EntitlementRow).where(EntitlementRow.user_id == user_id)
    ).scalars().all()
    scopes = {e.scope for e in existing}
    if "free_sample" not in scopes:
        session.add(EntitlementRow(
            user_id=user_id,
            scope="free_sample",
            credits=200,
            meta_json=json.dumps({"granted_at": _now().isoformat(), "granted_by": "default"}),
        ))
    if "credits" not in scopes:
        session.add(EntitlementRow(
            user_id=user_id,
            scope="credits",
            credits=200,
            meta_json=json.dumps({"granted_at": _now().isoformat(), "granted_by": "default"}),
        ))


def _ensure_narrative_contract(
    session: Session, *, case_slug: str, scene_id: str, era: str, title: str,
    contract: dict[str, Any],
) -> None:
    """Insert the scene contract if missing (idempotent)."""

    existing = session.execute(
        select(NarrativeContractRow).where(
            NarrativeContractRow.case_slug == case_slug,
            NarrativeContractRow.scene_id == scene_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    session.add(NarrativeContractRow(
        case_slug=case_slug,
        scene_id=scene_id,
        era=era,
        title=title,
        contract_json=_to_json_str(contract),
        is_active=True,
    ))


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class RunRepository:
    """Thin façade over the SQLAlchemy session.

    All public methods are idempotent where possible
    (``create_run``, ``save_outcome``, ``record_model_call``,
    ``upsert_artifact``) so a retry from the client is safe.
    """

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory or SessionLocal

    # ----- session helper ------------------------------------------------

    def session(self) -> Session:
        return self._session_factory()

    # ----- reads --------------------------------------------------------

    def get_run(self, run_id: str) -> GameRun | None:
        with self.session() as s:
            return s.get(GameRun, run_id)

    def get_run_or_404(self, run_id: str) -> GameRun:
        run = self.get_run(run_id)
        if run is None:
            raise LookupError(f"run not found: {run_id}")
        return run

    def get_latest_snapshot(self, run_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.execute(
                select(WorldSnapshotRow)
                .where(WorldSnapshotRow.run_id == run_id)
                .order_by(WorldSnapshotRow.event_sequence.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            return _from_json_str(row.snapshot_json)

    def list_events(self, run_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(GameEventRow)
                .where(GameEventRow.run_id == run_id)
                .order_by(GameEventRow.event_sequence.asc())
                .limit(limit)
            ).scalars().all()
            return [r.to_dict() for r in rows]

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(ArtifactRow)
                .where(ArtifactRow.run_id == run_id)
                .order_by(ArtifactRow.artifact_id.asc())
            ).scalars().all()
            return [r.to_dict() for r in rows]

    def list_beliefs(self, run_id: str) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(CharacterBeliefRow)
                .where(CharacterBeliefRow.run_id == run_id)
                .order_by(CharacterBeliefRow.event_sequence.desc())
            ).scalars().all()
            return [r.to_dict() for r in rows]

    def list_memories(self, run_id: str) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(MemoryRow)
                .where(MemoryRow.run_id == run_id)
                .order_by(MemoryRow.memory_id.asc())
            ).scalars().all()
            return [r.to_dict() for r in rows]

    def list_seeds(self, run_id: str) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(CausalSeedRow)
                .where(CausalSeedRow.run_id == run_id)
                .order_by(CausalSeedRow.seed_id.asc())
            ).scalars().all()
            return [r.to_dict() for r in rows]

    def list_branches(self, run_id: str) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(BranchTimelineRow)
                .where(BranchTimelineRow.run_id == run_id)
                .order_by(BranchTimelineRow.fork_event_sequence.asc())
            ).scalars().all()
            return [r.to_dict() for r in rows]

    def list_model_calls(self, run_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(ModelCallRow)
                .where(ModelCallRow.run_id == run_id)
                .order_by(ModelCallRow.created_at.asc())
                .limit(limit)
            ).scalars().all()
            return [r.to_dict() for r in rows]

    def get_entitlements(self, user_id: str) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(EntitlementRow)
                .where(EntitlementRow.user_id == user_id)
            ).scalars().all()
            return [r.to_dict() for r in rows]

    # ----- writes: runs ------------------------------------------------

    def create_run(
        self,
        *,
        run_id: str | None = None,
        user_id: str = "demo-user",
        case_slug: str = "case_01_revolution_street",
        start_scene_id: str = "photo_lab_2008",
        start_era: str = "2008",
    ) -> dict[str, Any]:
        """Create a new run.  Idempotent on run_id collision."""

        rid = run_id or str(uuid.uuid4())
        with self.session() as s:
            existing = s.get(GameRun, rid)
            if existing is not None:
                return existing.to_dict()
            run = GameRun(
                run_id=rid,
                user_id=user_id,
                case_slug=case_slug,
                current_scene_id=start_scene_id,
                era=start_era,
                event_sequence=0,
                phase="setup",
                is_archived=False,
                is_mock=True,
            )
            s.add(run)
            _ensure_entitlements_for_default_user(s, user_id)
            s.commit()
            s.refresh(run)
            return run.to_dict()

    def update_run_meta(
        self,
        run_id: str,
        *,
        current_scene_id: str | None = None,
        era: str | None = None,
        event_sequence: int | None = None,
        phase: str | None = None,
        ending_id: str | None = None,
        ended: bool = False,
        is_archived: bool | None = None,
    ) -> dict[str, Any]:
        with self.session() as s:
            run = s.get(GameRun, run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            if current_scene_id is not None:
                run.current_scene_id = current_scene_id
            if era is not None:
                run.era = era
            if event_sequence is not None:
                run.event_sequence = int(event_sequence)
            if phase is not None:
                run.phase = phase
            if ending_id is not None:
                run.ending_id = ending_id
            if ended:
                run.ended_at = _now()
            if is_archived is not None:
                run.is_archived = bool(is_archived)
            run.last_active_at = _now()
            s.commit()
            s.refresh(run)
            return run.to_dict()

    # ----- writes: outcomes (the core write path) ---------------------

    def save_outcome(
        self,
        *,
        run_id: str,
        snapshot: dict[str, Any],
        outcome: dict[str, Any],
        scene_contract: dict[str, Any] | None = None,
        player_action: dict[str, Any] | None = None,
        npc_proposal: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a Resolver outcome atomically.

        Parameters
        ----------
        run_id
            The run id (must exist; ``create_run`` first).
        snapshot
            The post-resolve :class:`WorldSnapshot.to_dict()` payload.
        outcome
            The :class:`ResolverOutcome.to_dict()` payload.
        scene_contract
            Optional scene contract (cached for the
            narrative_contracts table on first encounter).
        player_action
            The original player-action dict (the
            ``actorId`` / ``actionType`` live here, not in
            the outcome).
        npc_proposal
            The NPC proposal the resolver accepted.  Its
            ``beliefUpdatesRequested`` is persisted so
            NPC-driven belief changes show up in
            ``character_beliefs`` (not just player-driven
            ones from ``outcome.beliefUpdates``).
        """

        with self.session() as s:
            run = s.get(GameRun, run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")

            # The outcome's eventSequence is the *next* sequence
            # (the resolver advances it).  The snapshot carries
            # the same value post-resolve; we read from outcome
            # to be explicit about the "next" semantics.
            event_sequence = int(
                outcome.get("eventSequence")
                or snapshot.get("eventSequence", 0)
            )
            if event_sequence < 1:
                # Defensive: the resolver_outcome schema requires
                # eventSequence >= 1.  Force to 1 so a malformed
                # payload (or a "no-op" outcome) still doesn't
                # break the unique constraint on (run_id, seq).
                event_sequence = 1
            outcome_id = str(outcome.get("outcomeId", uuid.uuid4()))
            idempotency_key = str(outcome.get("idempotencyKey", uuid.uuid4().hex))
            # Actor and action type come from the player_action
            # dict (the outcome only carries the *trigger* id,
            # not the actor).
            if player_action is not None:
                actor_id = str(player_action.get("actorId", ""))[:64] or "system"
                action_type = str(player_action.get("actionType", "player_action"))[:32]
            else:
                actor_id = "system"
                action_type = "system"
            scene_id = str(
                snapshot.get("canonicalState", {}).get("currentSceneId", "")
            )

            # ---- 1. Event log row (idempotent) -------------------------
            existing_event = s.execute(
                select(GameEventRow).where(
                    GameEventRow.run_id == run_id,
                    GameEventRow.idempotency_key == idempotency_key,
                )
            ).scalar_one_or_none()
            if existing_event is not None:
                logger.info("save_outcome: idempotency key replay, returning existing")
                return existing_event.to_dict()

            event_row = GameEventRow(
                run_id=run_id,
                event_sequence=event_sequence,
                scene_id=scene_id,
                actor_id=actor_id[:64],
                action_type=action_type[:32],
                action_payload_json=_to_json_str({
                    "clientActionId": outcome.get("triggerPlayerActionId"),
                    "outcomeId": outcome_id,
                }),
                validated_delta_json=_to_json_str({
                    "checksum": snapshot.get("checksum"),
                    "firedCausalSeeds": list(outcome.get("firedCausalSeeds", [])),
                }),
                causal_seed=(outcome.get("firedCausalSeeds", [None])[0]
                             if outcome.get("firedCausalSeeds") else None),
                random_seed=int(outcome.get("auditTrail", {}).get("randomSeed", 0) or 0),
                idempotency_key=idempotency_key,
                outcome_id=outcome_id,
            )
            s.add(event_row)
            try:
                s.flush()
            except IntegrityError as exc:
                s.rollback()
                logger.warning("save_outcome: integrity error, treating as replay: %s", exc)
                return self.list_events(run_id, limit=1)[0]

            # ---- 2. World snapshot row (one per event) ---------------
            snap_row = WorldSnapshotRow(
                run_id=run_id,
                event_sequence=event_sequence,
                snapshot_json=_to_json_str(snapshot),
                checksum=str(snapshot.get("checksum", "")),
            )
            s.add(snap_row)

            # ---- 3. Artifacts (UPSERT) -------------------------------
            self._upsert_artifacts(s, run_id, snapshot, event_sequence)

            # ---- 4. Beliefs (INSERT history rows) --------------------
            self._record_belief_history(s, run_id, outcome, event_sequence)
            if npc_proposal is not None:
                self._record_npc_belief_updates(
                    s, run_id, npc_proposal, event_sequence
                )

            # ---- 5. Causal seeds (UPSERT) ---------------------------
            self._upsert_seeds(s, run_id, snapshot, event_sequence)

            # ---- 6. Memories (UPSERT) -------------------------------
            self._upsert_memories(s, run_id, snapshot, event_sequence)

            # ---- 7. Run row updates --------------------------------
            canonical = snapshot.get("canonicalState", {}) or {}
            run.current_scene_id = str(canonical.get("currentSceneId", run.current_scene_id))
            run.era = str(canonical.get("era", run.era))
            run.event_sequence = event_sequence
            run.phase = str(canonical.get("phase", run.phase))
            ending_id = canonical.get("endingId")
            if ending_id:
                run.ending_id = str(ending_id)
            run.last_active_at = _now()

            # ---- 8. Scene contract (cache-on-first-use) ------------
            if scene_contract is not None:
                _ensure_narrative_contract(
                    s,
                    case_slug=run.case_slug,
                    scene_id=str(scene_contract.get("sceneId", scene_id)),
                    era=str(scene_contract.get("era", run.era)),
                    title=str(scene_contract.get("title", run.current_scene_id)),
                    contract=scene_contract,
                )

            s.commit()
            return event_row.to_dict()

    # ----- writes: model_calls / analytics / entitlements -------------

    def record_model_call(self, record: dict[str, Any]) -> dict[str, Any]:
        with self.session() as s:
            row = ModelCallRow(
                request_id=str(record.get("requestId", uuid.uuid4())),
                run_id=str(record.get("runId", ""))[:64],
                scene_id=(str(record.get("sceneId")) if record.get("sceneId") else None),
                task_type=str(record.get("taskType", ""))[:32],
                agent=str(record.get("agent", ""))[:32],
                model=str(record.get("model", ""))[:64],
                provider=str(record.get("provider", ""))[:32],
                input_tokens=int(record.get("inputTokens", 0) or 0),
                output_tokens=int(record.get("outputTokens", 0) or 0),
                latency_ms=int(record.get("latencyMs", 0) or 0),
                cost_cny=float(record.get("costCny", 0.0) or 0.0),
                finish_reason=str(record.get("finishReason", "stop"))[:32],
                degradation_level=(
                    str(record.get("degradationLevel"))[:8]
                    if record.get("degradationLevel") else None
                ),
                used_fallback=bool(record.get("usedFallback", False)),
                attempts=int(record.get("attempts", 1) or 1),
                metadata_json=_to_json_str(record.get("metadata", {})),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.to_dict()

    def record_analytics(self, record: dict[str, Any]) -> dict[str, Any]:
        with self.session() as s:
            row = AnalyticsEventRow(
                user_id=(str(record.get("userId"))[:64] if record.get("userId") else None),
                run_id=(str(record.get("runId"))[:64] if record.get("runId") else None),
                event_name=str(record.get("eventName", ""))[:64],
                payload_json=_to_json_str(record.get("payload", {})),
                client_version=(str(record.get("clientVersion"))[:32]
                                if record.get("clientVersion") else None),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.to_dict()

    def upsert_entitlement(
        self,
        *,
        user_id: str,
        scope: str,
        credits: int = 0,
        expires_at: datetime | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.session() as s:
            existing = s.execute(
                select(EntitlementRow).where(
                    EntitlementRow.user_id == user_id,
                    EntitlementRow.scope == scope,
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.credits = int(existing.credits) + int(credits)
                if expires_at is not None:
                    existing.expires_at = expires_at
                if meta is not None:
                    existing.meta_json = _to_json_str(meta)
                s.commit()
                s.refresh(existing)
                return existing.to_dict()
            row = EntitlementRow(
                user_id=user_id,
                scope=scope,
                credits=int(credits),
                expires_at=expires_at,
                meta_json=_to_json_str(meta or {}),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.to_dict()

    # ----- writes: branches -------------------------------------------

    def create_branch(
        self,
        *,
        run_id: str,
        source_run_id: str,
        fork_event_sequence: int,
        label: str = "",
        branch_id: str | None = None,
    ) -> dict[str, Any]:
        with self.session() as s:
            bid = branch_id or str(uuid.uuid4())
            row = BranchTimelineRow(
                run_id=run_id,
                branch_id=bid,
                label=label or f"Branch @ {fork_event_sequence}",
                source_run_id=source_run_id,
                fork_event_sequence=int(fork_event_sequence),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.to_dict()

    # ----- helpers -----------------------------------------------------

    def _upsert_artifacts(
        self,
        session: Session,
        run_id: str,
        snapshot: dict[str, Any],
        event_sequence: int,
    ) -> None:
        """UPSERT artifact rows from the snapshot's ``artifactState``."""

        artifacts = snapshot.get("artifactState", []) or []
        scene_id = snapshot.get("canonicalState", {}).get("currentSceneId")
        for art in artifacts:
            if not isinstance(art, dict):
                continue
            artifact_id = str(art.get("artifactId", ""))[:64]
            if not artifact_id:
                continue
            existing = session.execute(
                select(ArtifactRow).where(
                    ArtifactRow.run_id == run_id,
                    ArtifactRow.artifact_id == artifact_id,
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(ArtifactRow(
                    run_id=run_id,
                    artifact_id=artifact_id,
                    scene_id=(str(scene_id)[:64] if scene_id else None),
                    owner_id=str(art.get("ownerId", ""))[:64],
                    state=str(art.get("state", "intact"))[:64],
                    is_revealed=bool(art.get("isRevealed", False)),
                    location=(str(art.get("location"))[:128]
                              if art.get("location") else None),
                    tags_json=_to_json_str(art.get("tags", []) or []),
                    last_event_sequence=int(event_sequence),
                ))
            else:
                existing.scene_id = str(scene_id)[:64] if scene_id else existing.scene_id
                existing.owner_id = str(art.get("ownerId", existing.owner_id))[:64]
                existing.state = str(art.get("state", existing.state))[:64]
                existing.is_revealed = bool(art.get("isRevealed", existing.is_revealed))
                if art.get("location") is not None:
                    existing.location = str(art.get("location"))[:128]
                existing.tags_json = _to_json_str(art.get("tags", []) or [])
                existing.last_event_sequence = int(event_sequence)

    def _record_belief_history(
        self,
        session: Session,
        run_id: str,
        outcome: dict[str, Any],
        event_sequence: int,
    ) -> None:
        """Append a history row for every belief update.

        The Resolver already enforces decision 1's clamp; we
        just persist the engine's output.
        """

        for bu in outcome.get("beliefUpdates", []) or []:
            if not isinstance(bu, dict):
                continue
            character_id = str(bu.get("characterId", ""))[:64]
            subject = str(bu.get("subject", ""))[:128]
            if not character_id or not subject:
                continue
            session.add(CharacterBeliefRow(
                run_id=run_id,
                character_id=character_id,
                subject=subject,
                belief_state=str(bu.get("newState", "uncertain"))[:32],
                confidence=float(bu.get("confidence", 0.5) or 0.5),
                evidence_memory_id=(
                    str(bu.get("evidenceMemoryId"))[:64]
                    if bu.get("evidenceMemoryId") else None
                ),
                previous_state=(str(bu.get("previousState"))[:32]
                                if bu.get("previousState") else None),
                event_sequence=int(event_sequence),
                reason_code=None,  # engine strips this; we record the
                                   # diagnostic in the audit trail
                                   # instead
            ))

    def _record_npc_belief_updates(
        self,
        session: Session,
        run_id: str,
        npc_proposal: dict[str, Any],
        event_sequence: int,
    ) -> None:
        """Persist NPC proposal's ``beliefUpdatesRequested`` as history rows.

        The engine applies NPC belief updates to the
        snapshot's ``beliefMatrices``; this helper writes a
        row for each requested update so the archive panel
        shows the full NPC + player history.
        """

        for bu in npc_proposal.get("beliefUpdatesRequested", []) or []:
            if not isinstance(bu, dict):
                continue
            character_id = str(bu.get("characterId") or npc_proposal.get("characterId", ""))[:64]
            subject = str(bu.get("subject", ""))[:128]
            if not character_id or not subject:
                continue
            session.add(CharacterBeliefRow(
                run_id=run_id,
                character_id=character_id,
                subject=subject,
                belief_state=str(bu.get("newState", "reinforced"))[:32],
                confidence=float(bu.get("confidence", 0.5) or 0.5),
                evidence_memory_id=(
                    str(bu.get("evidenceMemoryId"))[:64]
                    if bu.get("evidenceMemoryId") else None
                ),
                previous_state=None,
                event_sequence=int(event_sequence),
                reason_code="npc_proposal",
            ))

    def _upsert_seeds(
        self,
        session: Session,
        run_id: str,
        snapshot: dict[str, Any],
        event_sequence: int,
    ) -> None:
        """UPSERT seed rows; mark seeds absent from the active set as
        *fired* if they used to be dormant.
        """

        active = snapshot.get("causalSeedsActive", []) or []
        active_ids = {str(s.get("id")) for s in active if isinstance(s, dict) and s.get("id")}

        # ---- UPSERT the seeds in the snapshot's active set ----
        for s_dict in active:
            if not isinstance(s_dict, dict):
                continue
            seed_id = str(s_dict.get("id", ""))[:64]
            if not seed_id:
                continue
            existing = session.execute(
                select(CausalSeedRow).where(
                    CausalSeedRow.run_id == run_id,
                    CausalSeedRow.seed_id == seed_id,
                )
            ).scalar_one_or_none()
            is_dormant = s_dict.get("firedAt") is None
            if existing is None:
                session.add(CausalSeedRow(
                    run_id=run_id,
                    seed_id=seed_id,
                    source_scene=str(s_dict.get("source_scene", ""))[:64],
                    source_event_id=(
                        str(s_dict.get("source_event_id"))[:64]
                        if s_dict.get("source_event_id") else None
                    ),
                    description=str(s_dict.get("description", "")),
                    trigger_condition_json=_to_json_str(
                        s_dict.get("trigger_condition", {}) or {}
                    ),
                    target_scenes_json=_to_json_str(s_dict.get("target_scenes", []) or []),
                    echo_intensity=float(s_dict.get("echo_intensity", 0.5) or 0.5),
                    is_secret=bool(s_dict.get("is_secret", False)),
                    is_dormant=is_dormant,
                    fired_at_event=(
                        int(s_dict["firedAt"]) if s_dict.get("firedAt") is not None
                        else None
                    ),
                    fired_in_scene_id=(
                        str(s_dict.get("firedInSceneId"))[:64]
                        if s_dict.get("firedInSceneId") else None
                    ),
                    linked_character_ids_json=_to_json_str(
                        s_dict.get("linkedCharacterIds", []) or []
                    ),
                    decay_rate=float(s_dict.get("decayRate", 0.0) or 0.0),
                    tags_json=_to_json_str(s_dict.get("tags", []) or []),
                    era_span_json=_to_json_str(s_dict.get("eraSpan")),
                ))
            else:
                existing.is_dormant = is_dormant
                if not is_dormant:
                    existing.fired_at_event = int(s_dict["firedAt"])
                    existing.fired_in_scene_id = (
                        str(s_dict.get("firedInSceneId"))[:64]
                        if s_dict.get("firedInSceneId") else existing.fired_in_scene_id
                    )

        # ---- Mark seeds that disappeared from the active set as fired
        # (this is what the engine's auto-fire does; we just persist
        # the consequence).
        existing_rows = session.execute(
            select(CausalSeedRow).where(
                CausalSeedRow.run_id == run_id,
                CausalSeedRow.is_dormant.is_(True),
            )
        ).scalars().all()
        for row in existing_rows:
            if row.seed_id not in active_ids:
                row.is_dormant = False
                row.fired_at_event = int(event_sequence)

    def _upsert_memories(
        self,
        session: Session,
        run_id: str,
        snapshot: dict[str, Any],
        event_sequence: int,
    ) -> None:
        for m in snapshot.get("memories", []) or []:
            if not isinstance(m, dict):
                continue
            memory_id = str(m.get("memoryId", ""))[:64]
            if not memory_id:
                continue
            existing = session.execute(
                select(MemoryRow).where(
                    MemoryRow.run_id == run_id,
                    MemoryRow.memory_id == memory_id,
                )
            ).scalar_one_or_none()
            owner = str(m.get("ownerCharacterId", ""))[:64]
            if existing is None:
                session.add(MemoryRow(
                    run_id=run_id,
                    memory_id=memory_id,
                    owner_character_id=owner,
                    summary=str(m.get("summary", "")),
                    emotional_weight=float(m.get("recallWeight", 0.5) or 0.5),
                    distortion_type=None,
                    involved_character_ids_json="[]",
                    recall_count=0,
                    decay_score=float(m.get("decayScore", 0.0) or 0.0),
                    formed_at_event=int(event_sequence),
                    last_recalled_at_event=(
                        int(m["lastRecalledAt"])
                        if m.get("lastRecalledAt") is not None
                        else None
                    ),
                    embedding_hash=str(m.get("embeddingHash", ""))[:128] or None,
                ))
            else:
                if m.get("lastRecalledAt") is not None:
                    existing.last_recalled_at_event = int(m["lastRecalledAt"])
                    existing.recall_count = int(existing.recall_count) + 1


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


_default_repo: RunRepository | None = None


def get_default_repository() -> RunRepository:
    """Return a process-wide repository singleton."""

    global _default_repo
    if _default_repo is None:
        _default_repo = RunRepository()
    return _default_repo


__all__ = ["RunRepository", "get_default_repository"]
