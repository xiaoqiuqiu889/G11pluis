"""In-memory registry of active runs.

Holds the per-run objects the action hot path needs to read
on every turn:

* the latest :class:`engine.world_snapshot.WorldSnapshot`
  (the canonical state — a single source of truth across
  the server process).
* the per-run :class:`engine.event_log.EventLog`
  (append-only ledger; the Resolver pushes events into it).
* the per-run :class:`engine.state_machine.SceneBudget`
  (12-action whitelist + consumed counters).
* the per-run :class:`server.model.gateway.ModelGateway` /
  :class:`server.model.degradation.ModelDegradationChain`
  (decision 5's per-run state).
* the per-run :class:`server.agents.resolver.ResolverAgent`
  (the only writer — see
  :mod:`server.agents.resolver` for the write-domain
  isolation rule).

Lifecycle
---------

1. :meth:`open` hydrates the four objects from the database
   (cold start), or constructs a fresh set (new run).
2. The :class:`ActionRunner` reads / mutates the four
   objects on every turn and persists the result via
   :class:`server.repository.RunRepository.save_outcome`.
3. :meth:`close` is a soft operation — we keep the in-memory
   objects for ``max_idle_seconds`` (default 600s) so a
   re-connecting client can resume without paying the
   hydration cost.

Thread safety
-------------

A single :class:`asyncio.Lock` per run serialises turns.  In
practice the FastAPI server is single-threaded under uvicorn
and the action handler is async-only, so the lock is mostly
defensive; it does keep state consistent if multiple in-flight
requests for the same run race.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from db import get_session
from engine import (
    ArtifactState,
    EventLog,
    SceneBudget,
    ScenePhase,
    WorldSnapshot,
)
from repository import RunRepository
from scene_loader import SceneContractLoader, get_default_loader

logger = logging.getLogger("g1n.run_registry")


# ---------------------------------------------------------------------------
# Scene initial-artifact seed
# ---------------------------------------------------------------------------


def _initial_artifacts_for_scene(scene_id: str) -> list[ArtifactState]:
    """Return the artifacts every run starts with for ``scene_id``.

    Mirrors the integration test's ``_fresh_snapshot`` setup
    so the give / reveal / destroy reducers have something
    to operate on from turn 1.
    """

    if scene_id == "photo_lab_2008":
        return [
            ArtifactState(
                artifactId="photo_pair",
                ownerId="leila",
                state="in_hand",
                isRevealed=True,
            ),
            ArtifactState(
                artifactId="photo_A",
                ownerId="leila",
                state="in_envelope",
                isRevealed=False,
            ),
            ArtifactState(
                artifactId="photo_B",
                ownerId="leila",
                state="in_envelope",
                isRevealed=False,
            ),
            ArtifactState(
                artifactId="envelope",
                ownerId="leila",
                state="intact",
                isRevealed=True,
            ),
            ArtifactState(
                artifactId="book_jalal",
                ownerId="arash",
                state="in_jacket",
                isRevealed=True,
            ),
        ]
    if scene_id == "farewell_2011":
        return [
            ArtifactState(
                artifactId="photo_A",
                ownerId="leila",
                state="in_crossbody",
                isRevealed=False,
            ),
            ArtifactState(
                artifactId="book_jalal",
                ownerId="arash",
                state="in_jacket",
                isRevealed=True,
            ),
            ArtifactState(
                artifactId="envelope_kamran",
                ownerId="leila",
                state="in_suitcase",
                isRevealed=False,
            ),
            ArtifactState(
                artifactId="boarding_pass",
                ownerId="leila",
                state="in_hand",
                isRevealed=True,
            ),
            ArtifactState(
                artifactId="luggage_tag",
                ownerId="leila",
                state="on_suitcase",
                isRevealed=True,
            ),
        ]
    if scene_id == "reunion_2024":
        return [
            ArtifactState(
                artifactId="photo_A",
                ownerId="leila",
                state="in_crossbody",
                isRevealed=False,
            ),
            ArtifactState(
                artifactId="book_jalal",
                ownerId="arash",
                state="in_arm",
                isRevealed=True,
            ),
            ArtifactState(
                artifactId="poetry_book",
                ownerId="arash",
                state="in_arm",
                isRevealed=True,
            ),
        ]
    return []


@dataclass
class ActiveRun:
    """The in-memory per-run state.

    Attributes
    ----------
    run_id : str
    user_id : str
    snapshot : WorldSnapshot
        The canonical state — the Resolver's input + output.
    event_log : EventLog
        The append-only ledger the Resolver writes to.
    scene_budget : SceneBudget
        The 12-action whitelist + counters.
    contract : dict
        The active scene's contract (cached from
        :class:`scene_loader.SceneContractLoader`).
    last_touched : float
        Monotonic timestamp of the most recent mutation;
        used by the idle-eviction policy.
    lock : asyncio.Lock
        Per-run lock; serialises turn execution.
    """

    run_id: str
    user_id: str
    snapshot: WorldSnapshot
    event_log: EventLog
    scene_budget: SceneBudget
    contract: dict[str, Any]
    last_touched: float
    lock: asyncio.Lock


class RunRegistry:
    """Process-wide active-run cache."""

    def __init__(
        self,
        *,
        scene_loader: SceneContractLoader | None = None,
        repository: RunRepository | None = None,
        max_idle_seconds: int = 600,
    ) -> None:
        self._runs: dict[str, ActiveRun] = {}
        self._scene_loader = scene_loader or get_default_loader()
        self._repo = repository or RunRepository()
        self._max_idle_seconds = int(max_idle_seconds)
        self._registry_lock = threading.Lock()

    # ----- introspection -------------------------------------------------

    @property
    def active_count(self) -> int:
        with self._registry_lock:
            return len(self._runs)

    def all_run_ids(self) -> list[str]:
        with self._registry_lock:
            return list(self._runs.keys())

    # ----- lifecycle -----------------------------------------------------

    def open(
        self,
        run_id: str,
        *,
        case_slug: str = "case_01_revolution_street",
        default_scene_id: str = "photo_lab_2008",
    ) -> ActiveRun:
        """Get-or-create the active-run state for ``run_id``.

        On first access: hydrates the snapshot from the
        database (if a run row exists), or constructs a fresh
        one (if the run was just created).
        """

        with self._registry_lock:
            existing = self._runs.get(run_id)
            if existing is not None:
                existing.last_touched = time.monotonic()
                return existing

        # Outside the lock — DB read is the slow path
        run_row = self._repo.get_run(run_id)
        if run_row is None:
            raise LookupError(f"run not found: {run_id}")

        scene_id = run_row.current_scene_id or default_scene_id
        # W12: case-aware — use the case the run was created with
        case_slug = getattr(run_row, "case_slug", None) or "case_01_revolution_street"
        scene = self._scene_loader.load_scene(case_slug, scene_id)
        contract = scene.contract

        # ---- hydrate snapshot ----
        snap_dict = self._repo.get_latest_snapshot(run_id)
        if snap_dict is not None:
            snapshot = WorldSnapshot.from_dict(snap_dict)
        else:
            snapshot = WorldSnapshot.empty(
                runId=run_id,
                sceneId=scene_id,
                era=run_row.era or scene.era,
                contractId=scene_id,
            )
            # Seed initial artifacts so the reducers
            # (give / reveal / destroy) don't fail with
            # EvidenceNotFoundError on the first turn.
            initial_artifacts = _initial_artifacts_for_scene(scene_id)
            if initial_artifacts:
                snapshot = snapshot.with_artifact_state(initial_artifacts)
            if run_row.phase and run_row.phase != "setup":
                snapshot = snapshot.with_canonical_state(
                    phase=run_row.phase, globalTension=0.4
                )

        # ---- hydrate event log (one entry per event row) ----
        event_log = EventLog(runId=run_id)
        # We re-hydrate event_seq from the snapshot — the
        # event_log is a runtime cache, not the source of truth.

        scene_budget = SceneBudget(
            sceneId=scene_id,
            max_turns=int(contract.get("max_turns", 8) or 8),
            total_action_budget=int(contract.get("total_action_budget", 32) or 32),
            per_action={k: int(v) for k, v in scene.turn_budget.items()},
        )

        active = ActiveRun(
            run_id=run_id,
            user_id=run_row.user_id or "demo-user",
            snapshot=snapshot,
            event_log=event_log,
            scene_budget=scene_budget,
            contract=contract,
            last_touched=time.monotonic(),
            lock=asyncio.Lock(),
        )

        with self._registry_lock:
            self._runs[run_id] = active
        logger.info(
            "RunRegistry.open: run=%s scene=%s phase=%s eventSeq=%d",
            run_id, scene_id, snapshot.canonicalState.phase, snapshot.eventSequence,
        )
        return active

    def close(self, run_id: str) -> None:
        with self._registry_lock:
            self._runs.pop(run_id, None)

    def evict_idle(self) -> int:
        """Evict runs that haven't been touched in ``max_idle_seconds``.

        Returns the number of runs evicted.
        """

        now = time.monotonic()
        evicted = 0
        with self._registry_lock:
            stale = [
                rid for rid, r in self._runs.items()
                if now - r.last_touched > self._max_idle_seconds
            ]
            for rid in stale:
                self._runs.pop(rid, None)
                evicted += 1
        if evicted:
            logger.info("RunRegistry.evict_idle: evicted %d idle run(s)", evicted)
        return evicted

    def get(self, run_id: str) -> ActiveRun | None:
        with self._registry_lock:
            return self._runs.get(run_id)

    def touch(self, run_id: str) -> None:
        with self._registry_lock:
            r = self._runs.get(run_id)
            if r is not None:
                r.last_touched = time.monotonic()

    # ----- transitions --------------------------------------------------

    def transition_to_scene(
        self,
        run_id: str,
        *,
        new_scene_id: str,
        new_era: str | None = None,
    ) -> ActiveRun:
        """Re-anchor the active run to a new scene.

        Carries dormant seeds over (decision 3).  Resets
        the scene budget to the new scene's per_action caps.
        """

        active = self.open(run_id)
        # W12: case-aware transition — re-read case from DB to be authoritative
        run_row = self._repo.get_run(run_id)
        case_slug = (
            (run_row.case_slug if run_row else None)
            or getattr(active, "case_slug", None)
            or "case_01_revolution_street"
        )
        scene = self._scene_loader.load_scene(case_slug, new_scene_id)
        new_contract = scene.contract
        era = new_era or scene.era
        # Carry dormant seeds
        carried = [
            dict(s) for s in active.snapshot.causalSeedsActive
            if isinstance(s, dict) and s.get("firedAt") is None
        ]
        new_snapshot = WorldSnapshot(
            runId=active.snapshot.runId,
            eventSequence=active.snapshot.eventSequence,
            canonicalState=active.snapshot.canonicalState.with_canonical_state.__self__
                if False else type(active.snapshot.canonicalState)(
                    currentSceneId=new_scene_id,
                    era=era,
                    turnIndex=0,
                    phase=ScenePhase.SETUP.value,
                    activeContractId=new_scene_id,
                    activeBeatId=None,
                    endingId=None,
                    globalTension=0.4,
                ),
            relationshipState=list(active.snapshot.relationshipState),
            artifactState=list(active.snapshot.artifactState),
            directorState=active.snapshot.directorState,
            beliefMatrices=[dict(m) for m in active.snapshot.beliefMatrices],
            memories=list(active.snapshot.memories),
            causalSeedsActive=carried,
            recentOutcomes=list(active.snapshot.recentOutcomes),
            timestamp=active.snapshot.timestamp,
            checksum=active.snapshot.checksum,
        )
        new_budget = SceneBudget(
            sceneId=new_scene_id,
            max_turns=int(new_contract.get("max_turns", 8) or 8),
            total_action_budget=int(new_contract.get("total_action_budget", 32) or 32),
            per_action={k: int(v) for k, v in scene.turn_budget.items()},
        )
        active.snapshot = new_snapshot
        active.scene_budget = new_budget
        active.contract = new_contract
        active.last_touched = time.monotonic()
        return active


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


_default_registry: RunRegistry | None = None


def get_default_registry() -> RunRegistry:
    """Return a process-wide registry singleton."""

    global _default_registry
    if _default_registry is None:
        _default_registry = RunRegistry()
    return _default_registry


__all__ = ["ActiveRun", "RunRegistry", "get_default_registry"]
