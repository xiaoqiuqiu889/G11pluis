"""API regression for the two mutually exclusive 2008 photo choices."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

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


def _artifact_map(snapshot: dict) -> dict[str, tuple[str, str]]:
    return {
        item["artifactId"]: (item["ownerId"], item["state"])
        for item in snapshot["artifactState"]
    }


def _seed_ids(snapshot: dict) -> set[str]:
    return {
        str(seed["id"])
        for seed in snapshot["causalSeedsActive"]
        if seed.get("id")
    }


def _action_body(run_id: str, target_id: str) -> dict:
    return {
        "runId": run_id,
        "sceneId": SCENE_ID,
        "clientActionId": str(uuid.uuid4()),
        "expectedEventSequence": 0,
        "playerAction": {
            "actionType": "give",
            "actorId": "leila",
            "targetId": target_id,
            "evidenceIds": ["photo_pair"],
            "utterance": "One each." if target_id == "arash" else "I will keep both.",
            "tone": "gentle",
            "disclosureLevel": 0.5,
            "isDeceptive": False,
        },
        "clientVersion": "meaningful-choice-regression",
    }


def test_two_fresh_runs_persist_distinct_photo_futures(tmp_path: Path, monkeypatch) -> None:
    engine = build_engine(f"sqlite:///{(tmp_path / 'choice.db').as_posix()}")
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
    client = TestClient(app_module.app)

    scenarios = {
        "arash": {
            "ending": "shared_secret",
            "seeds": {"photo_in_pocket", "photo_in_book"},
            "artifacts": {
                "photo_A": ("leila", "in_pocket"),
                "photo_B": ("arash", "in_book"),
            },
        },
        "leila": {
            "ending": "one_sided_memory",
            "seeds": {"both_photos_with_one"},
            "artifacts": {
                "photo_A": ("leila", "in_pocket"),
                "photo_B": ("leila", "in_pocket"),
            },
        },
    }
    results: dict[str, dict] = {}
    run_ids: set[str] = set()
    for target_id, expected in scenarios.items():
        created = client.post("/v1/runs", json={
            "userId": "meaningful-choice-user",
            "caseSlug": CASE_SLUG,
            "startSceneId": SCENE_ID,
            "startEra": "2008",
        })
        assert created.status_code == 200, created.text
        run_id = created.json()["run"]["runId"]
        run_ids.add(run_id)
        response = client.post(
            f"/v1/runs/{run_id}/actions",
            json=_action_body(run_id, target_id),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        snapshot = body["snapshot"]
        assert body["eventSequence"] == 1
        assert body["fallbackUsed"] is False
        assert body["degraded"] == "none"
        assert body["degradedToL3"] is False
        assert len(body["modelCalls"]) == 2
        assert body["outcome"]["nextBeat"]["transition"] == "end_scene"
        assert body["outcome"]["nextBeat"]["legalEndingId"] == expected["ending"]
        assert snapshot["canonicalState"]["endingId"] == expected["ending"]
        assert _seed_ids(snapshot) == expected["seeds"]
        artifacts = _artifact_map(snapshot)
        assert "photo_pair" not in artifacts
        assert {
            key: artifacts[key] for key in expected["artifacts"]
        } == expected["artifacts"]
        photo_b_owner = "arash" if target_id == "arash" else "leila"
        photo_b_state = "in_book" if target_id == "arash" else "in_pocket"
        artifact_updates = [
            (
                update["artifactId"], update["operation"],
                update.get("newOwnerId"), update.get("newState"),
                update["reasonCode"],
            )
            for update in body["outcome"]["artifactUpdates"]
        ]
        assert artifact_updates == [
            ("photo_A", "transfer", "leila", None, "photo_pair_choice"),
            ("photo_A", "modify_state", None, "in_pocket", "photo_pair_choice"),
            ("photo_B", "transfer", photo_b_owner, None, "photo_pair_choice"),
            ("photo_B", "modify_state", None, photo_b_state, "photo_pair_choice"),
            ("photo_pair", "destroy", None, None, "photo_pair_choice_resolved"),
        ]
        if target_id == "leila":
            assert body["outcome"]["relationshipDelta"] == []
            assert all(
                relation["from"] != relation["to"]
                for relation in snapshot["relationshipState"]
            )

        assert {row["seedId"] for row in repository.list_seeds(run_id)} == expected["seeds"]
        registry.close(run_id)
        resumed = client.post(
            f"/v1/runs/{run_id}/resume",
            json={"userId": "meaningful-choice-user"},
        )
        assert resumed.status_code == 200, resumed.text
        reopened = registry.open(run_id).snapshot.to_dict()
        assert reopened == snapshot
        run_row = client.get(f"/v1/runs/{run_id}")
        assert run_row.status_code == 200, run_row.text
        assert run_row.json()["endingId"] == expected["ending"]
        results[target_id] = snapshot

    assert results["arash"]["canonicalState"]["endingId"] != results["leila"]["canonicalState"]["endingId"]
    assert _seed_ids(results["arash"]) != _seed_ids(results["leila"])
    assert _artifact_map(results["arash"]) != _artifact_map(results["leila"])
    assert len(run_ids) == 2
    assert provider._call_count == 4
    engine.dispose()