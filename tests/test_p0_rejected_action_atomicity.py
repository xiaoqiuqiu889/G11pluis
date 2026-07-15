"""P0 regression: rejected actions are free, atomic, and non-canonical.

This test deliberately drives the public FastAPI surface.  It uses an
isolated SQLite database plus a fresh registry/runner/runtime so importing
this module can never read or mutate ``data/g1n.db``.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "server") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "server"))

import app as app_module  # noqa: E402
from action_runner import ActionRunner  # noqa: E402
from db import (  # noqa: E402
    Base,
    CausalSeedRow,
    GameEventRow,
    GameRun,
    ModelCallRow,
    WorldSnapshotRow,
    build_engine,
)
from llm_runtime import LLMRuntime  # noqa: E402
from model import (  # noqa: E402
    CostController,
    FallbackContentLoader,
    MockProvider,
    ModelGateway,
    ProviderResult,
    SchemaValidator,
    build_default_router,
)
from repository import RunRepository  # noqa: E402
from run_registry import RunRegistry  # noqa: E402
from scene_loader import SceneContractLoader  # noqa: E402


CASE_SLUG = "case_01_revolution_street"
SCENE_ID = "photo_lab_2008"


def _provider_result(payload: dict) -> ProviderResult:
    return ProviderResult(
        content=json.dumps(payload, ensure_ascii=False),
        model="mock-p0-atomicity",
        provider="mock",
        input_tokens=10,
        output_tokens=10,
        finish_reason="stop",
        latency_ms=1,
    )


def _script_valid_turn(
    provider: MockProvider,
    *,
    run_id: str,
    allowed_beat_id: str,
    forbidden_reveal_ids: list[str],
) -> dict:
    provider.push(_provider_result({
        "proposalId": str(uuid.uuid4()),
        "runId": run_id,
        "characterId": "arash",
        "triggerPlayerActionId": None,
        "proposedAction": "comfort",
        "targetId": "leila",
        "speechIntent": "comfort",
        "referencedMemoryIds": [],
        "beliefUpdatesRequested": [],
        "emotionalTransition": {
            "from": "calm",
            "to": "tense",
            "intensity": 0.5,
        },
        "reasonCodes": ["memory_resurfaced"],
        "confidence": 0.7,
        "expectedContradictions": [],
        "timestamp": "2026-07-15T00:00:00Z",
        "schemaVersion": "1.0.0",
    }))
    director_payload = {
        "proposalId": str(uuid.uuid4()),
        "runId": run_id,
        "sceneId": SCENE_ID,
        "proposedBeat": allowed_beat_id,
        "allowedByContract": True,
        "forbiddenRevealsChecked": forbidden_reveal_ids,
        "transitionToNext": False,
        "reasoning": "Keep the scene inside its declared beat contract.",
        "pacingPressure": 0.5,
        "timestamp": "2026-07-15T00:00:00Z",
        "schemaVersion": "1.0.0",
    }
    provider.push(_provider_result(director_payload))
    return director_payload


def _action_body(
    run_id: str,
    *,
    evidence_ids: list[str],
) -> dict:
    client_action_id = str(uuid.uuid4())
    return {
        "runId": run_id,
        "sceneId": SCENE_ID,
        "clientActionId": client_action_id,
        "expectedEventSequence": 0,
        "playerAction": {
            "actionType": "give",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": evidence_ids,
            "utterance": "One for you, one for me.",
            "tone": "gentle",
            "disclosureLevel": 0.5,
            "isDeceptive": False,
        },
        "clientVersion": "p0-regression",
    }


def _count_rows(session_factory, row_type, run_id: str) -> int:
    with session_factory() as session:
        return int(session.scalar(
            select(func.count())
            .select_from(row_type)
            .where(row_type.run_id == run_id)
        ) or 0)


def test_invalid_evidence_then_valid_action_is_atomic_and_reopenable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "rejected-action-atomicity.db"
    isolated_engine = build_engine(f"sqlite:///{db_path.as_posix()}")
    session_factory = sessionmaker(
        bind=isolated_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    Base.metadata.create_all(isolated_engine)

    loader = SceneContractLoader()
    repository = RunRepository(session_factory=session_factory)
    registry = RunRegistry(scene_loader=loader, repository=repository)
    provider = MockProvider()
    cost_controller = CostController(
        hard_turn_call_budget=2,
        hard_run_call_budget=20,
    )
    fallback_loader = FallbackContentLoader()
    gateway = ModelGateway(
        providers={"mock": provider},
        router=build_default_router(),
        cost_controller=cost_controller,
        validator=SchemaValidator(),
        fallback_loader=fallback_loader,
        case_slug=CASE_SLUG,
    )
    runtime = LLMRuntime(
        gateway=gateway,
        cost_controller=cost_controller,
        fallback_loader=fallback_loader,
        provider_names=["mock"],
    )
    runner = ActionRunner(
        registry=registry,
        repository=repository,
        runtime=runtime,
        scene_loader=loader,
    )

    # Patch only the three dependencies used by these FastAPI endpoints.
    # The app lifespan is intentionally not entered: it would initialise the
    # process-global DB, which is outside this test's authority.
    monkeypatch.setattr(app_module, "get_default_repository", lambda: repository)
    monkeypatch.setattr(app_module, "get_default_registry", lambda: registry)
    monkeypatch.setattr(app_module, "get_default_runner", lambda: runner)
    client = TestClient(app_module.app)

    created_response = client.post("/v1/runs", json={
        "userId": "p0-test-user",
        "caseSlug": CASE_SLUG,
        "startSceneId": SCENE_ID,
        "startEra": "2008",
    })
    assert created_response.status_code == 200, created_response.text
    run_id = created_response.json()["run"]["runId"]
    active = registry.open(run_id)
    allowed_beat_id = active.contract["allowed_beats"][0]["beatId"]
    scripted_director = _script_valid_turn(
        provider,
        run_id=run_id,
        allowed_beat_id=allowed_beat_id,
        forbidden_reveal_ids=[
            reveal["revealKey"] for reveal in active.contract["forbidden_reveals"]
        ],
    )
    assert "involvedCharacterIds" not in scripted_director

    # This action is invalid because one evidence id does not exist.  It also
    # contains photo_pair, so planting seeds before validating the complete
    # evidence list would be observable and fail the regression.
    rejected_response = client.post(
        f"/v1/runs/{run_id}/actions",
        json=_action_body(
            run_id,
            evidence_ids=["photo_pair", "missing_photo"],
        ),
    )
    assert rejected_response.status_code == 200, rejected_response.text
    rejected = rejected_response.json()
    assert rejected["eventSequence"] == 0
    assert rejected["snapshot"]["eventSequence"] == 0
    assert rejected["outcome"]["eventSequence"] == 1
    assert rejected["outcome"]["nextBeat"]["beatId"] == "rejected_action"

    # A deterministic rejection is a free preflight failure: no provider
    # call, no model audit row, no canonical event/snapshot slot, no seeds.
    assert provider._call_count == 0
    assert cost_controller.run_summary(run_id).total_calls == 0
    assert repository.list_model_calls(run_id) == []
    assert repository.list_events(run_id) == []
    assert repository.list_seeds(run_id) == []
    assert registry.open(run_id).snapshot.causalSeedsActive == []
    assert _count_rows(session_factory, ModelCallRow, run_id) == 0
    assert _count_rows(session_factory, GameEventRow, run_id) == 0
    assert _count_rows(session_factory, WorldSnapshotRow, run_id) == 0
    assert _count_rows(session_factory, CausalSeedRow, run_id) == 0
    with session_factory() as session:
        run_before_success = session.get(GameRun, run_id)
        assert run_before_success is not None
        assert run_before_success.event_sequence == 0

    # The valid action must still own the complete two-call turn budget and
    # occupy canonical event slot 1; the rejected request must not cause a
    # uniqueness collision or a 500 here.
    accepted_response = client.post(
        f"/v1/runs/{run_id}/actions",
        json=_action_body(run_id, evidence_ids=["photo_pair"]),
    )
    assert accepted_response.status_code == 200, accepted_response.text
    accepted = accepted_response.json()
    assert accepted["eventSequence"] == 1
    assert accepted["snapshot"]["eventSequence"] == 1
    assert accepted["outcome"]["eventSequence"] == 1
    assert accepted["outcome"]["nextBeat"]["transition"] == "end_scene"
    assert accepted["outcome"]["nextBeat"]["legalEndingId"] == "shared_secret"
    assert accepted["snapshot"]["canonicalState"]["phase"] == "ended"
    assert accepted["snapshot"]["canonicalState"]["endingId"] == "shared_secret"
    assert provider._call_count == 2
    assert cost_controller.run_summary(run_id).total_calls == 2
    expected_forbidden_reveals = [
        item["revealKey"] for item in active.contract["forbidden_reveals"]
    ]
    assert len(expected_forbidden_reveals) > 8
    director_request = json.loads(
        provider.calls[1]["messages"][0]["content"]
    )
    assert director_request["forbiddenReveals"] == expected_forbidden_reveals

    assert _count_rows(session_factory, GameEventRow, run_id) == 1
    assert _count_rows(session_factory, WorldSnapshotRow, run_id) == 1
    assert _count_rows(session_factory, ModelCallRow, run_id) == 2
    with session_factory() as session:
        event_sequences = list(session.scalars(
            select(GameEventRow.event_sequence)
            .where(GameEventRow.run_id == run_id)
            .order_by(GameEventRow.event_sequence)
        ))
        snapshot_rows = list(session.scalars(
            select(WorldSnapshotRow)
            .where(WorldSnapshotRow.run_id == run_id)
            .order_by(WorldSnapshotRow.event_sequence)
        ))
        persisted_run = session.get(GameRun, run_id)
    assert event_sequences == [1]
    assert [row.event_sequence for row in snapshot_rows] == [1]
    assert json.loads(snapshot_rows[0].snapshot_json)["eventSequence"] == 1
    assert persisted_run is not None
    assert persisted_run.event_sequence == 1
    assert persisted_run.phase == "ended"
    assert persisted_run.ending_id == "shared_secret"

    persisted_response = client.get(f"/v1/runs/{run_id}/snapshot")
    assert persisted_response.status_code == 200, persisted_response.text
    persisted = persisted_response.json()
    assert persisted["source"] == "persisted"
    assert persisted["snapshot"] == accepted["snapshot"]

    # Simulate a process-local reopen.  Hydration must reproduce exactly the
    # authoritative persisted snapshot and run sequence/ending.
    registry.close(run_id)
    assert registry.get(run_id) is None
    resume_response = client.post(
        f"/v1/runs/{run_id}/resume",
        json={"userId": "p0-test-user"},
    )
    assert resume_response.status_code == 200, resume_response.text
    assert resume_response.json()["active"] == {
        "sceneId": SCENE_ID,
        "era": "2008",
        "eventSequence": 1,
        "phase": "ended",
    }
    reopened = registry.open(run_id).snapshot.to_dict()
    assert reopened == persisted["snapshot"]
    run_response = client.get(f"/v1/runs/{run_id}")
    assert run_response.status_code == 200, run_response.text
    assert run_response.json()["eventSequence"] == 1
    assert run_response.json()["phase"] == "ended"
    assert run_response.json()["endingId"] == "shared_secret"

    isolated_engine.dispose()
