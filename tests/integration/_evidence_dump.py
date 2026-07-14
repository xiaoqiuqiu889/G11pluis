"""Helper script to dump the cost + echo evidence for the report.

Not a test.  Run manually with::

    python -m tests.integration._evidence_dump
"""

import sys
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "server"))

from tests.integration.test_end_to_end_three_scenes import (  # noqa: E402
    IntegrationHarness, _new_player_action_dict, _new_npc_proposal_dict,
)


def main() -> None:
    h = IntegrationHarness()
    run_id = h.run_id
    print("=" * 60)
    print("COST BREAKDOWN (mock provider, 3 scenes, 5 turns)")
    print("=" * 60)
    print("turn  task                       model           in_tok  out_tok cost_cny")
    print("-" * 60)
    for i, evidence in enumerate(["envelope", "photo_A", "photo_B"]):
        if i == 0:
            target = "arash"
            action_type = "investigate"
        elif i == 1:
            target = "leila"
            action_type = "give"
        else:
            target = "arash"
            action_type = "give"
        h.drive_turn(
            player_action=_new_player_action_dict(
                action_type=action_type,
                scene_id="photo_lab_2008",
                target_id=target,
                evidence_ids=[evidence],
                expected_event_sequence=h.snapshot.eventSequence,
            ),
            npc_proposal=_new_npc_proposal_dict(
                run_id=run_id,
                character_id="arash",
                proposed_action="comfort",
                speech_intent="comfort",
                target_id="leila",
            ),
        )
        if i == 1:
            seed = {
                "id": "photo_in_pocket",
                "source_scene": "photo_lab_2008",
                "source_event": "test",
                "description": "...",
                "trigger_condition": {
                    "type": "scene_match",
                    "predicate": "in",
                    "minEcho": 0.0,
                },
                "target_scenes": ["reunion_2024"],
                "echo_intensity": 0.95,
                "is_secret": False,
                "firedAt": None,
                "firedInSceneId": None,
                "eraSpan": {},
                "linkedCharacterIds": ["leila", "arash"],
                "decayRate": 0.02,
                "tags": [],
                "schemaVersion": "1.0.0",
            }
            h.snapshot = h.snapshot.with_causal_seeds_active(
                list(h.snapshot.causalSeedsActive) + [seed]
            )
        if i == 2:
            seed = {
                "id": "photo_in_book",
                "source_scene": "photo_lab_2008",
                "source_event": "test",
                "description": "...",
                "trigger_condition": {
                    "type": "scene_match",
                    "predicate": "in",
                    "minEcho": 0.0,
                },
                "target_scenes": ["reunion_2024"],
                "echo_intensity": 0.85,
                "is_secret": False,
                "firedAt": None,
                "firedInSceneId": None,
                "eraSpan": {},
                "linkedCharacterIds": ["leila", "arash"],
                "decayRate": 0.02,
                "tags": [],
                "schemaVersion": "1.0.0",
            }
            h.snapshot = h.snapshot.with_causal_seeds_active(
                list(h.snapshot.causalSeedsActive) + [seed]
            )
    h.transition_to_scene(scene_id="farewell_2011", era="2011")
    h.drive_turn(
        player_action=_new_player_action_dict(
            action_type="reveal",
            scene_id="farewell_2011",
            target_id="arash",
            evidence_ids=["envelope_kamran"],
            expected_event_sequence=h.snapshot.eventSequence,
        ),
        npc_proposal=_new_npc_proposal_dict(
            run_id=run_id,
            character_id="arash",
            proposed_action="comfort",
            speech_intent="comfort",
            target_id="leila",
        ),
    )
    h.transition_to_scene(scene_id="reunion_2024", era="2024")
    result_2024 = h.drive_turn(
        player_action=_new_player_action_dict(
            action_type="investigate",
            scene_id="reunion_2024",
            target_id="arash",
            evidence_ids=["poetry_book"],
            expected_event_sequence=h.snapshot.eventSequence,
        ),
        npc_proposal=_new_npc_proposal_dict(
            run_id=run_id,
            character_id="arash",
            proposed_action="reveal",
            speech_intent="reveal_truth",
            belief_subject="photo_in_pocket",
            target_id="leila",
            reason_codes=["memory_resurfaced"],
            referenced_memory_ids=["mem_2008_photo_pocket"],
        ),
        recall_set={"mem_2008_photo_pocket"},
    )
    for rec in h.ledger.records:
        print(
            "%-5d %-26s %-15s %-7d %-7d %.6f"
            % (
                rec.turn_index,
                rec.task_type,
                rec.model,
                rec.input_tokens,
                rec.output_tokens,
                rec.cost_cny,
            )
        )
    print()
    print("=" * 60)
    print("COST TOTAL")
    print("=" * 60)
    print("Total calls: %d" % len(h.ledger.records))
    print("Total cost: CNY %.6f" % h.ledger.total_cost_cny)
    print("Max output tokens: %d" % h.ledger.max_output_tokens)
    per_turn = {}
    for rec in h.ledger.records:
        per_turn.setdefault(rec.turn_index, 0)
        per_turn[rec.turn_index] += 1
    print("Per-turn counts: %s" % per_turn)
    print()
    print("=" * 60)
    print("MANDATORY ECHO EVIDENCE")
    print("=" * 60)
    print(
        "NPC proposal characterId: %s"
        % result_2024.npc_proposal_dict.get("characterId")
    )
    print(
        "NPC proposal speechIntent: %s"
        % result_2024.npc_proposal_dict.get("speechIntent")
    )
    print(
        "NPC proposal belief subject: %s"
        % result_2024.npc_proposal_dict.get("beliefUpdatesRequested")
    )
    print(
        "Mandatory echo: passes=%s"
        % result_2024.mandatory_echo.passes
    )
    print("  summary: %s" % result_2024.mandatory_echo.summary)
    print(
        "  checks: %s"
        % [(c.seed_id, c.matched) for c in result_2024.mandatory_echo.checks]
    )
    print("rejectedNpcActions: %s" % result_2024.outcome.rejectedNpcActions)
    print("firedCausalSeeds: %s" % result_2024.outcome.firedCausalSeeds)
    print("New seeds: %s" % result_2024.outcome.newCausalSeeds)
    print("Belief updates: %s" % result_2024.outcome.beliefUpdates)


if __name__ == "__main__":
    main()
