"""Regression coverage for the M1 photo-pair action boundary."""
from __future__ import annotations

import sys
import uuid

sys.path.insert(0, "server")

from action_runner import _merge_mandatory_seeds, _select_mandatory_seeds  # noqa: E402
from agents.resolver import build_resolver_agent  # noqa: E402
from engine import EventLog, NarrativeContract, Resolver, SceneBudget, WorldSnapshot  # noqa: E402
from run_registry import _initial_artifacts_for_scene  # noqa: E402


def _budget() -> SceneBudget:
    return SceneBudget(
        sceneId="photo_lab_2008", max_turns=8, total_action_budget=32,
        per_action={}, consumed={}, elapsed_turns=0,
    )


def _action() -> dict:
    return {
        "actionType": "give",
        "actorId": "leila",
        "targetId": "arash",
        "evidenceIds": ["photo_pair"],
        "disclosureLevel": 0.5,
        "isDeceptive": False,
        "clientActionId": str(uuid.uuid4()),
        "expectedEventSequence": 1,
    }


def test_photo_pair_is_canonical_initial_evidence_and_ends_scene() -> None:
    run_id = str(uuid.uuid4())
    artifacts = _initial_artifacts_for_scene("photo_lab_2008")
    assert "photo_pair" in {artifact.artifactId for artifact in artifacts}
    seeds = _select_mandatory_seeds(
        scene_id="photo_lab_2008", action_type="give",
        target_id="arash", evidence_ids=["photo_pair"],
    )
    snapshot = WorldSnapshot.empty(run_id, "photo_lab_2008", "2008")
    snapshot = snapshot.with_artifact_state(artifacts)
    snapshot = snapshot.with_causal_seeds_active(_merge_mandatory_seeds([], seeds))
    contract = NarrativeContract(
        sceneId="photo_lab_2008", allowed_beats=[], forbidden_reveals=[],
        legal_endings=[{"endingId": "shared_secret",
                        "conditions": ["photo_in_pocket", "photo_in_book"]}],
        max_turns=8, total_action_budget=32,
    )
    new_snapshot, outcome = Resolver().resolve(
        snapshot=snapshot, event_log=EventLog(runId=run_id),
        player_action=_action(), npc_proposal=None, director_beat=None,
        contract=contract, scene_budget=_budget(),
    )
    assert new_snapshot.eventSequence == 1
    assert outcome.eventSequence == 1
    assert outcome.nextBeat["transition"] == "end_scene"
    pair = next(a for a in new_snapshot.artifactState if a.artifactId == "photo_pair")
    assert pair.ownerId == "arash"


def test_first_turn_rejection_is_schema_valid_without_l4_cascade() -> None:
    run_id = str(uuid.uuid4())
    snapshot = WorldSnapshot.empty(run_id, "photo_lab_2008", "2008")
    agent = build_resolver_agent("case_01_revolution_street")
    new_snapshot, outcome, *_ = agent.resolve_turn(
        snapshot=snapshot, event_log=EventLog(runId=run_id),
        player_action=_action(), npc_proposal_dict=None,
        director_beat_dict=None,
        scene_contract={
            "sceneId": "photo_lab_2008", "allowed_beats": [],
            "forbidden_reveals": [], "legal_endings": [],
            "max_turns": 8, "total_action_budget": 32,
        },
        scene_budget=_budget(),
    )
    assert new_snapshot.eventSequence == 0
    assert outcome.eventSequence == 1
    assert any(
        "rejected player action" in decision
        for decision in outcome.auditTrail["deterministicDecisions"]
    )
