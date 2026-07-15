"""Runtime state-consistency regressions for resume and write boundaries."""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "server"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import app as app_module  # noqa: E402
from action_runner import ActionRunner  # noqa: E402
from db import Base, build_engine  # noqa: E402
from llm_runtime import LLMRuntime, _default_mock_provider  # noqa: E402
from model import (  # noqa: E402
    CostController,
    FallbackContentLoader,
    ModelGateway,
    SchemaValidator,
    build_default_router,
)
from repository import RunRepository  # noqa: E402
from run_registry import RunRegistry  # noqa: E402
from scene_loader import SceneContractLoader  # noqa: E402

CASE_SLUG = "case_01_revolution_street"
SCENE_ID = "photo_lab_2008"


def _build_stack(tmp_path: Path, monkeypatch):
    engine = build_engine(f"sqlite:///{(tmp_path / 'runtime-state.db').as_posix()}")
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False,
        expire_on_commit=False, future=True,
    )
    Base.metadata.create_all(engine)
    loader = SceneContractLoader()
    repository = RunRepository(session_factory=session_factory)
    registry = RunRegistry(scene_loader=loader, repository=repository)
    provider = _default_mock_provider()
    cost = CostController(hard_turn_call_budget=2, hard_run_call_budget=20)
    fallback = FallbackContentLoader()
    runtime = LLMRuntime(
        gateway=ModelGateway(
            providers={"mock": provider},
            router=build_default_router(),
            cost_controller=cost,
            validator=SchemaValidator(),
            fallback_loader=fallback,
            case_slug=CASE_SLUG,
        ),
        cost_controller=cost,
        fallback_loader=fallback,
        provider_names=["mock"],
    )
    runner = ActionRunner(
        registry=registry, repository=repository,
        runtime=runtime, scene_loader=loader,
    )
    monkeypatch.setattr(app_module, "get_default_repository", lambda: repository)
    monkeypatch.setattr(app_module, "get_default_registry", lambda: registry)
    monkeypatch.setattr(app_module, "get_default_runner", lambda: runner)
    return (
        TestClient(app_module.app, raise_server_exceptions=False),
        engine, repository, registry, provider,
    )


def _create_run(client: TestClient) -> str:
    response = client.post("/v1/runs", json={
        "userId": "runtime-state-user",
        "caseSlug": CASE_SLUG,
        "startSceneId": SCENE_ID,
        "startEra": "2008",
    })
    assert response.status_code == 200, response.text
    return response.json()["run"]["runId"]


def _wait_action(
    run_id: str, *, expected: int, scene_id: str = SCENE_ID,
    client_action_id: str | None = None,
) -> dict:
    action_id = client_action_id or str(uuid.uuid4())
    return {
        "runId": run_id,
        "sceneId": scene_id,
        "clientActionId": action_id,
        "expectedEventSequence": expected,
        "playerAction": {
            "actionType": "wait",
            "actorId": "leila",
            "utterance": "Wait and listen.",
            "tone": "neutral",
            "disclosureLevel": 0.5,
            "isDeceptive": False,
        },
        "clientVersion": "runtime-state-regression",
    }


def test_valid_action_after_resume_hydrates_event_log_and_advances_atomically(
    tmp_path: Path, monkeypatch,
) -> None:
    client, engine, repository, registry, provider = _build_stack(
        tmp_path, monkeypatch
    )
    run_id = _create_run(client)
    first_action_id = str(uuid.uuid4())
    first = client.post(
        f"/v1/runs/{run_id}/actions",
        json=_wait_action(
            run_id, expected=0, client_action_id=first_action_id
        ),
    )
    assert first.status_code == 200, first.text
    assert first.json()["eventSequence"] == 1
    assert provider._call_count == 2
    assert registry.open(run_id).scene_budget.elapsed_turns == 1

    registry.close(run_id)
    resumed = client.post(
        f"/v1/runs/{run_id}/resume",
        json={"userId": "runtime-state-user"},
    )
    assert resumed.status_code == 200, resumed.text
    reopened = registry.open(run_id)
    assert reopened.event_log.last_sequence == 1
    assert [
        event.actionPayload.get("clientActionId")
        for event in reopened.event_log
    ] == [first_action_id]
    assert reopened.scene_budget.elapsed_turns == 1
    assert reopened.scene_budget.consumed == {"wait": 1}

    replay = client.post(
        f"/v1/runs/{run_id}/actions",
        json=_wait_action(
            run_id, expected=1, client_action_id=first_action_id
        ),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["eventSequence"] == 1
    assert replay.json()["outcome"]["nextBeat"]["beatId"] == "rejected_action"
    assert provider._call_count == 2
    assert [event["eventSequence"] for event in repository.list_events(run_id)] == [1]

    second = client.post(
        f"/v1/runs/{run_id}/actions",
        json=_wait_action(run_id, expected=1),
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["eventSequence"] == 2
    assert body["snapshot"]["eventSequence"] == 2
    assert body["outcome"]["eventSequence"] == 2
    assert [event["eventSequence"] for event in repository.list_events(run_id)] == [1, 2]
    assert repository.get_latest_snapshot(run_id)["eventSequence"] == 2
    assert repository.get_run(run_id).event_sequence == 2
    engine.dispose()


def test_sequence_and_scene_mismatches_are_free_noncanonical_rejections(
    tmp_path: Path, monkeypatch,
) -> None:
    client, engine, repository, _registry, provider = _build_stack(
        tmp_path, monkeypatch
    )
    run_id = _create_run(client)

    future = client.post(
        f"/v1/runs/{run_id}/actions",
        json=_wait_action(run_id, expected=999),
    )
    assert future.status_code == 200, future.text
    assert future.json()["eventSequence"] == 0
    assert future.json()["outcome"]["nextBeat"]["beatId"] == "rejected_action"

    wrong_scene = client.post(
        f"/v1/runs/{run_id}/actions",
        json=_wait_action(run_id, expected=0, scene_id="farewell_2011"),
    )
    assert wrong_scene.status_code == 200, wrong_scene.text
    assert wrong_scene.json()["snapshot"]["canonicalState"]["currentSceneId"] == SCENE_ID
    assert provider._call_count == 0
    assert repository.list_events(run_id) == []
    assert repository.list_model_calls(run_id) == []

    accepted = client.post(
        f"/v1/runs/{run_id}/actions",
        json=_wait_action(run_id, expected=0),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["eventSequence"] == 1
    assert provider._call_count == 2

    stale = client.post(
        f"/v1/runs/{run_id}/actions",
        json=_wait_action(run_id, expected=0),
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["eventSequence"] == 1
    assert stale.json()["outcome"]["nextBeat"]["beatId"] == "rejected_action"
    assert provider._call_count == 2
    assert [event["eventSequence"] for event in repository.list_events(run_id)] == [1]
    assert len(repository.list_model_calls(run_id)) == 2
    engine.dispose()


def test_repository_rejects_outcome_snapshot_sequence_mismatch(
    tmp_path: Path,
) -> None:
    engine = build_engine(f"sqlite:///{(tmp_path / 'repository-guard.db').as_posix()}")
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False,
        expire_on_commit=False, future=True,
    )
    Base.metadata.create_all(engine)
    repository = RunRepository(session_factory=session_factory)
    run = repository.create_run(user_id="repository-guard")

    with pytest.raises(ValueError, match="non-atomic event sequence"):
        repository.save_outcome(
            run_id=run["runId"],
            snapshot={"eventSequence": 0},
            outcome={
                "outcomeId": str(uuid.uuid4()),
                "eventSequence": 1,
                "idempotencyKey": "repository-guard-idempotency",
            },
        )

    assert repository.list_events(run["runId"]) == []
    assert repository.get_run(run["runId"]).event_sequence == 0
    engine.dispose()


def test_save_outcome_failure_rolls_back_process_state_and_reuses_sequence(
    tmp_path: Path, monkeypatch,
) -> None:
    client, engine, repository, registry, provider = _build_stack(
        tmp_path, monkeypatch
    )
    run_id = _create_run(client)
    runner = app_module.get_default_runner()
    active = registry.open(run_id)
    initial_snapshot = active.snapshot.to_dict()
    action_id = str(uuid.uuid4())
    payload = _wait_action(
        run_id, expected=0, client_action_id=action_id
    )

    original_save_outcome = repository.save_outcome
    save_attempts = 0

    def fail_first_save_outcome(**kwargs):
        nonlocal save_attempts
        save_attempts += 1
        if save_attempts == 1:
            raise RuntimeError("injected save_outcome failure")
        return original_save_outcome(**kwargs)

    monkeypatch.setattr(repository, "save_outcome", fail_first_save_outcome)

    failed = client.post(f"/v1/runs/{run_id}/actions", json=payload)
    assert failed.status_code == 500, failed.text
    assert save_attempts == 1
    assert provider._call_count == 2

    # A repository failure happens after resolution, so the rollback boundary
    # must restore every process-local canonical structure as well as the DB.
    active_after_failure = registry.open(run_id)
    assert active_after_failure.snapshot.to_dict() == initial_snapshot
    assert active_after_failure.event_log.last_sequence == 0
    assert list(active_after_failure.event_log) == []
    assert active_after_failure.scene_budget.elapsed_turns == 0
    assert active_after_failure.scene_budget.consumed == {}
    assert runner._resolver_for(run_id).idempotency_cache == {}
    assert repository.list_events(run_id) == []
    assert repository.list_model_calls(run_id) == []
    assert repository.get_latest_snapshot(run_id) is None
    assert repository.get_run(run_id).event_sequence == 0

    # Retrying the exact client action after storage recovers must own slot 1;
    # the failed attempt must not look like an idempotent replay.
    recovered = client.post(f"/v1/runs/{run_id}/actions", json=payload)
    assert recovered.status_code == 200, recovered.text
    body = recovered.json()
    assert body["eventSequence"] == 1
    assert body["snapshot"]["eventSequence"] == 1
    assert body["outcome"]["eventSequence"] == 1
    assert body["clientActionId"] == action_id
    assert body["outcome"]["triggerPlayerActionId"] == action_id
    assert [event["eventSequence"] for event in repository.list_events(run_id)] == [1]
    assert repository.list_events(run_id)[0]["actionPayload"]["clientActionId"] == action_id
    assert repository.get_latest_snapshot(run_id)["eventSequence"] == 1
    assert repository.get_run(run_id).event_sequence == 1
    engine.dispose()


def test_top_level_and_nested_client_action_ids_must_match_before_models(
    tmp_path: Path, monkeypatch,
) -> None:
    client, engine, repository, registry, provider = _build_stack(
        tmp_path, monkeypatch
    )
    run_id = _create_run(client)
    top_level_id = str(uuid.uuid4())
    mismatched = _wait_action(
        run_id, expected=0, client_action_id=top_level_id
    )
    mismatched["playerAction"]["clientActionId"] = str(uuid.uuid4())

    rejected = client.post(
        f"/v1/runs/{run_id}/actions", json=mismatched
    )
    assert rejected.status_code == 200, rejected.text
    rejected_body = rejected.json()
    assert rejected_body["eventSequence"] == 0
    assert rejected_body["snapshot"]["eventSequence"] == 0
    assert rejected_body["outcome"]["nextBeat"]["beatId"] == "rejected_action"
    assert rejected_body["clientActionId"] == top_level_id
    assert provider._call_count == 0
    assert repository.list_events(run_id) == []
    assert repository.list_model_calls(run_id) == []
    active = registry.open(run_id)
    assert active.event_log.last_sequence == 0
    assert active.scene_budget.elapsed_turns == 0
    assert active.scene_budget.consumed == {}

    consistent = _wait_action(
        run_id, expected=0, client_action_id=top_level_id
    )
    consistent["playerAction"]["clientActionId"] = top_level_id
    accepted = client.post(
        f"/v1/runs/{run_id}/actions", json=consistent
    )
    assert accepted.status_code == 200, accepted.text
    accepted_body = accepted.json()
    assert accepted_body["eventSequence"] == 1
    assert accepted_body["clientActionId"] == top_level_id
    assert accepted_body["outcome"]["triggerPlayerActionId"] == top_level_id
    events = repository.list_events(run_id)
    assert len(events) == 1
    assert events[0]["actionPayload"]["clientActionId"] == top_level_id
    assert provider._call_count == 2
    engine.dispose()


def test_concurrent_actions_for_one_run_are_serialized_by_active_lock(
    tmp_path: Path, monkeypatch,
) -> None:
    client, engine, repository, registry, provider = _build_stack(
        tmp_path, monkeypatch
    )
    run_id = _create_run(client)
    runner = app_module.get_default_runner()
    original_drive_turn = runner.drive_turn
    inside_drive_turn = 0
    max_inside_drive_turn = 0

    async def observed_drive_turn(**kwargs):
        nonlocal inside_drive_turn, max_inside_drive_turn
        inside_drive_turn += 1
        max_inside_drive_turn = max(
            max_inside_drive_turn, inside_drive_turn
        )
        try:
            # Make simultaneous handler calls overlap at the runner boundary.
            # The endpoint's per-run lock must keep the second call out.
            await asyncio.sleep(0.05)
            return await original_drive_turn(**kwargs)
        finally:
            inside_drive_turn -= 1

    monkeypatch.setattr(runner, "drive_turn", observed_drive_turn)
    payloads = [
        _wait_action(run_id, expected=0),
        _wait_action(run_id, expected=0),
    ]

    async def submit_concurrently() -> list[dict]:
        return await asyncio.gather(*[
            app_module.submit_action(
                req=app_module.ActionRequest(**payload),
                run_id=run_id,
            )
            for payload in payloads
        ])

    responses = asyncio.run(submit_concurrently())

    assert all(response["ok"] is True for response in responses)
    assert max_inside_drive_turn == 1
    events = repository.list_events(run_id)
    assert [event["eventSequence"] for event in events] == [1]
    assert len({event["eventSequence"] for event in events}) == len(events)
    assert repository.get_run(run_id).event_sequence == 1
    active = registry.open(run_id)
    assert active.snapshot.eventSequence == 1
    assert active.event_log.last_sequence == 1
    assert active.scene_budget.elapsed_turns == 1
    assert provider._call_count == 2
    engine.dispose()
