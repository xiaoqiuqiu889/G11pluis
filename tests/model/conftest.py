"""Shared pytest fixtures for the model package tests.

The fixtures here are designed to give every test a *clean*
gateway + cost controller state, so test order does not matter.

Key fixtures
------------

* :func:`gateway` — a fully wired :class:`ModelGateway` with
  a single :class:`MockProvider`.  Tests push scripted
  responses onto the mock.
* :func:`cost_controller` — a fresh :class:`CostController`
  with a recording alert sink.
* :func:`schema_validator` — a fresh :class:`SchemaValidator`
  pointing at the project schema dir.
* :func:`fallback_loader` — a fresh :class:`FallbackContentLoader`.
* :func:`valid_npc_proposal` / :func:`valid_player_action` /
  etc. — schema-valid sample payloads for testing.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

# Make ``server`` importable as a top-level package.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "server") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "server"))

from model import (  # noqa: E402
    CostController,
    FallbackContentLoader,
    MockProvider,
    ModelGateway,
    SchemaValidator,
    TaskRouter,
    build_default_router,
)
from model.models import ProviderResult  # noqa: E402


# ---------------------------------------------------------------------------
# Provider fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_provider() -> MockProvider:
    """A fresh mock provider with no scripted responses."""

    return MockProvider()


@pytest.fixture
def gateway(mock_provider: MockProvider) -> ModelGateway:
    """A fully wired gateway with one mock provider."""

    return ModelGateway(
        providers={"mock": mock_provider},
        router=build_default_router(),
        cost_controller=CostController(),
        validator=SchemaValidator(),
        fallback_loader=FallbackContentLoader(),
    )


@pytest.fixture
def cost_controller() -> CostController:
    """A fresh cost controller with a recording alert sink."""

    alerts: list = []
    cc = CostController(alert_sink=lambda a: alerts.append(a))
    cc._alerts_test_sink = alerts  # type: ignore[attr-defined]
    return cc


@pytest.fixture
def schema_validator() -> SchemaValidator:
    """A fresh schema validator pointing at the project schema dir."""

    return SchemaValidator()


@pytest.fixture
def fallback_loader() -> FallbackContentLoader:
    """A fresh fallback content loader."""

    return FallbackContentLoader()


@pytest.fixture
def started_gateway(gateway: ModelGateway):
    """A gateway with one run already started."""

    run_id = str(uuid.uuid4())
    chain = gateway.start_run(run_id=run_id, scene_id="photo_lab_2008")
    return {"gateway": gateway, "run_id": run_id, "chain": chain}


# ---------------------------------------------------------------------------
# Sample valid payloads (one per schema)
# ---------------------------------------------------------------------------


VALID_PLAYER_ACTION: dict = {
    "runId": "00000000-0000-0000-0000-000000000001",
    "sceneId": "photo_lab_2008",
    "actionType": "question",
    "actorId": "player",
    "targetId": "arash",
    "utterance": "那张照片里是谁?",
    "tone": "hesitant",
    "disclosureLevel": 0.5,
    "isDeceptive": False,
    "schemaVersion": "1.0.0",
}


VALID_NPC_PROPOSAL: dict = {
    "proposalId": "00000000-0000-0000-0000-000000000002",
    "runId": "00000000-0000-0000-0000-000000000001",
    "characterId": "arash",
    "proposedAction": "comfort",
    "speechIntent": "comfort",
    "reasonCodes": ["player_disclosed_truth", "memory_resurfaced"],
    "confidence": 0.7,
    "schemaVersion": "1.0.0",
}


VALID_DIRECTOR_BEAT: dict = {
    "proposalId": "00000000-0000-0000-0000-000000000003",
    "runId": "00000000-0000-0000-0000-000000000001",
    "sceneId": "photo_lab_2008",
    "proposedBeat": "beat_divide_photos",
    "allowedByContract": True,
    "forbiddenRevealsChecked": ["leila_future_marriage"],
    "transitionToNext": False,
    "reasoning": "Player has asked about the photo, anchor 1 needs to fire.",
    "pacingPressure": 0.6,
    "schemaVersion": "1.0.0",
}


VALID_RESOLVER_OUTCOME: dict = {
    "outcomeId": "00000000-0000-0000-0000-000000000004",
    "runId": "00000000-0000-0000-0000-000000000001",
    "eventSequence": 1,
    "idempotencyKey": "idem-1234567890",
    "acceptedNpcAction": {
        "proposalId": "00000000-0000-0000-0000-000000000002",
        "characterId": "arash",
        "proposedAction": "comfort",
        "speechIntent": "comfort",
    },
    "nextBeat": {
        "sceneId": "photo_lab_2008",
        "beatId": "beat_divide_photos",
        "transition": "continue",
    },
    "timestamp": "2026-07-15T00:00:00Z",
    "schemaVersion": "1.0.0",
}


@pytest.fixture
def valid_player_action() -> dict:
    return dict(VALID_PLAYER_ACTION)


@pytest.fixture
def valid_npc_proposal() -> dict:
    return dict(VALID_NPC_PROPOSAL)


@pytest.fixture
def valid_director_beat() -> dict:
    return dict(VALID_DIRECTOR_BEAT)


@pytest.fixture
def valid_resolver_outcome() -> dict:
    return dict(VALID_RESOLVER_OUTCOME)
