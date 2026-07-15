"""M1 regression tests for authoritative causal scene endings."""
from __future__ import annotations

import sys
import uuid

sys.path.insert(0, "server")

from action_runner import (  # noqa: E402
    _merge_mandatory_seeds,
    _select_mandatory_seed,
    _select_mandatory_seeds,
)
from engine import EventLog, NarrativeContract, Resolver, SceneBudget, WorldSnapshot  # noqa: E402
from engine.event_log import GameEvent  # noqa: E402


def _budget() -> SceneBudget:
    return SceneBudget(
        sceneId="photo_lab_2008", max_turns=8, total_action_budget=32,
        per_action={}, consumed={}, elapsed_turns=0,
    )


def _contract(conditions: list[str]) -> NarrativeContract:
    return NarrativeContract(
        sceneId="photo_lab_2008",
        allowed_beats=[{"beatId": "beat_setup_0"}],
        forbidden_reveals=[],
        legal_endings=[{"endingId": "shared_secret", "conditions": conditions}],
        max_turns=8,
        total_action_budget=32,
    )


def _photo_pair_seeds():
    return _select_mandatory_seeds(
        scene_id="photo_lab_2008", action_type="give",
        target_id="arash", evidence_ids=["photo_pair"],
    )


def test_photo_pair_plants_both_once_and_preserves_single_selector() -> None:
    seeds = _photo_pair_seeds()
    assert [seed.id for seed in seeds] == ["photo_in_pocket", "photo_in_book"]
    merged = _merge_mandatory_seeds([], seeds)
    merged = _merge_mandatory_seeds(merged, seeds)
    assert [seed["id"] for seed in merged] == ["photo_in_pocket", "photo_in_book"]
    legacy = _select_mandatory_seed(
        scene_id="photo_lab_2008", action_type="give",
        target_id="arash", evidence_ids=["photo_B"],
    )
    assert legacy is not None and legacy.id == "photo_in_book"


def test_resolver_ends_scene_from_planted_seeds() -> None:
    run_id = str(uuid.uuid4())
    snapshot = WorldSnapshot.empty(run_id, "photo_lab_2008", "2008")
    snapshot = snapshot.with_causal_seeds_active(
        [seed.to_dict() for seed in _photo_pair_seeds()]
    )
    new_snapshot, outcome = Resolver().resolve(
        snapshot=snapshot, event_log=EventLog(runId=run_id),
        player_action=None, npc_proposal=None, director_beat=None,
        contract=_contract(["photo_in_pocket", "photo_in_book"]),
        scene_budget=_budget(),
    )
    assert new_snapshot.canonicalState.phase == "ended"
    assert new_snapshot.canonicalState.endingId == "shared_secret"
    assert outcome.nextBeat["transition"] == "end_scene"
    assert outcome.nextBeat["legalEndingId"] == "shared_secret"


def test_resolver_matches_prior_fired_seeds_and_single_seed_endings() -> None:
    run_id = str(uuid.uuid4())
    snapshot = WorldSnapshot.empty(run_id, "photo_lab_2008", "2008")
    snapshot = snapshot.with_event_sequence(1)
    event_log = EventLog(runId=run_id)
    event_log.append(GameEvent(
        sequence=1, sceneId="photo_lab_2008", actorId="leila",
        actionType="give", actionPayload={},
        validatedDelta={"firedCausalSeeds": ["photo_in_pocket"]},
        causalSeed="photo_in_pocket", idempotencyKey="prior-event-key-0001",
        runId=run_id, outcomeId=str(uuid.uuid4()),
    ))
    new_snapshot, outcome = Resolver().resolve(
        snapshot=snapshot, event_log=event_log,
        player_action=None, npc_proposal=None, director_beat=None,
        contract=_contract(["photo_in_pocket"]), scene_budget=_budget(),
    )
    assert new_snapshot.canonicalState.phase == "ended"
    assert outcome.nextBeat["legalEndingId"] == "shared_secret"