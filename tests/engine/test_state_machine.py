"""Unit tests for the 12-action state-machine reducers.

Verifies, for each of the 12 actions, that:

* the action is in the scene's whitelist
* the reducer produces the expected relationship / artifact / belief
  / causal-seed delta
* per-turn numeric clamps hold (|delta| ≤ 0.25)
* validation gates fire (target required, evidence required, etc.)
"""

from __future__ import annotations

import sys
import unittest
import uuid

sys.path.insert(0, "server")

from engine import (  # noqa: E402
    ActionType,
    ArtifactState,
    Era,
    REDUCERS,
    ReducerOutcome,
    SceneBudget,
    ScenePhase,
    WorldSnapshot,
    apply_reducer_outcome,
    reduce,
)
from engine.exceptions import (  # noqa: E402
    ActionBudgetExceededError,
    ActionRejectedError,
    EvidenceNotFoundError,
    EvidenceRequiredError,
    TargetNotPresentError,
    TargetRequiredError,
)


def _fresh_snapshot(*, with_photo: bool = True) -> WorldSnapshot:
    run_id = str(uuid.uuid4())
    snap = WorldSnapshot.empty(run_id, "photo_lab_2008", Era.Y2012_PRESENT_AI.value)
    snap = snap.with_canonical_state(phase=ScenePhase.RISING.value, globalTension=0.4)
    if with_photo:
        snap = snap.with_artifact_state(
            [
                ArtifactState(
                    artifactId="photo_A",
                    ownerId="leila",
                    state="intact",
                    isRevealed=False,
                ),
                ArtifactState(
                    artifactId="photo_B",
                    ownerId="leila",
                    state="intact",
                    isRevealed=False,
                ),
            ]
        )
    return snap


def _budget() -> SceneBudget:
    return SceneBudget(
        sceneId="photo_lab_2008",
        max_turns=8,
        total_action_budget=32,
        per_action={
            "investigate": 3,
            "reveal": 2,
            "conceal": 1,
            "question": 2,
            "confront": 2,
            "comfort": 1,
            "give": 3,
            "destroy": 1,
            "promise": 2,
            "wait": 2,
            "leave": 1,
            "silence": 2,
        },
        consumed={},
        elapsed_turns=0,
    )


def _cast() -> list[str]:
    return ["leila", "arash", "dagang"]


# ---------------------------------------------------------------------------
# 12 action reducers
# ---------------------------------------------------------------------------


class TwelveActionTests(unittest.TestCase):
    """Each of the 12 actions has its own test method."""

    # ----- investigate -----

    def test_investigate_evidence(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "investigate",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": ["photo_A"],
            "disclosureLevel": 0.5,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        self.assertTrue(out.accepted)
        self.assertEqual(len(out.relationshipDeltas), 2)  # actor→target, target→actor
        self.assertEqual(len(out.beliefUpdates), 1)
        self.assertEqual(out.beliefUpdates[0]["subject"], "photo_A")
        self.assertFalse(out.consumedTurn)
        new_snap = apply_reducer_outcome(snap, out)
        self.assertEqual(len(new_snap.artifactState), 2)  # unchanged

    # ----- reveal -----

    def test_reveal_evidence(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "reveal",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": ["photo_A"],
            "disclosureLevel": 1.0,
            "isDeceptive": False,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        self.assertTrue(out.accepted)
        self.assertTrue(out.consumedTurn)
        new_snap = apply_reducer_outcome(snap, out)
        photo = next(a for a in new_snap.artifactState if a.artifactId == "photo_A")
        self.assertTrue(photo.isRevealed)

    def test_reveal_deceptive(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "reveal",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": ["photo_A"],
            "disclosureLevel": 0.5,
            "isDeceptive": True,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        self.assertIn("deceptive", " ".join(out.deterministic_decisions))
        self.assertEqual(out.beliefUpdates[0]["newState"], "wrong")

    # ----- conceal -----

    def test_conceal_evidence(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "conceal",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": ["photo_A"],
            "disclosureLevel": 0.4,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        self.assertTrue(out.accepted)
        new_snap = apply_reducer_outcome(snap, out)
        photo = next(a for a in new_snap.artifactState if a.artifactId == "photo_A")
        self.assertFalse(photo.isRevealed)

    # ----- question -----

    def test_question_no_evidence_required(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "question",
            "actorId": "leila",
            "targetId": "arash",
            "disclosureLevel": 0.5,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        self.assertTrue(out.accepted)
        self.assertEqual(out.artifactUpdates, [])

    # ----- confront -----

    def test_confront_raises_unresolved_conflict(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "confront",
            "actorId": "leila",
            "targetId": "arash",
            "disclosureLevel": 0.7,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        self.assertTrue(out.accepted)
        new_snap = apply_reducer_outcome(snap, out)
        pair = next(
            r
            for r in new_snap.relationshipState
            if r.from_ == "leila" and r.to == "arash"
        )
        self.assertGreater(pair.unresolvedConflict, 0.0)

    # ----- comfort -----

    def test_comfort_positive(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "comfort",
            "actorId": "leila",
            "targetId": "arash",
            "disclosureLevel": 1.0,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        new_snap = apply_reducer_outcome(snap, out)
        pair = next(
            r for r in new_snap.relationshipState if r.from_ == "leila" and r.to == "arash"
        )
        self.assertGreater(pair.intimacy, 0.0)
        self.assertGreater(pair.trust, 0.0)

    # ----- give -----

    def test_give_transfers_artifact(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "give",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": ["photo_A"],
            "disclosureLevel": 0.7,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        self.assertTrue(out.accepted)
        new_snap = apply_reducer_outcome(snap, out)
        photo = next(a for a in new_snap.artifactState if a.artifactId == "photo_A")
        self.assertEqual(photo.ownerId, "arash")

    # ----- destroy -----

    def test_destroy_removes_artifact(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "destroy",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": ["photo_B"],
            "disclosureLevel": 0.5,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        new_snap = apply_reducer_outcome(snap, out)
        self.assertNotIn("photo_B", [a.artifactId for a in new_snap.artifactState])
        self.assertIn("photo_A", [a.artifactId for a in new_snap.artifactState])

    # ----- promise -----

    def test_promise_plants_seed(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "promise",
            "actorId": "leila",
            "targetId": "arash",
            "utterance": "I will be at the airport.",
            "disclosureLevel": 1.0,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        self.assertTrue(out.accepted)
        self.assertEqual(len(out.causalSeeds), 1)
        seed = out.causalSeeds[0]
        self.assertTrue(seed.id.startswith("seed_promise_"))
        new_snap = apply_reducer_outcome(snap, out)
        self.assertEqual(len(new_snap.causalSeedsActive), 1)

    # ----- wait -----

    def test_wait_no_delta(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "wait",
            "actorId": "leila",
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        self.assertTrue(out.accepted)
        self.assertEqual(out.relationshipDeltas, [])
        self.assertEqual(out.artifactUpdates, [])
        self.assertTrue(out.consumedTurn)

    # ----- leave -----

    def test_leave_negative_intimacy(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "leave",
            "actorId": "leila",
            "targetId": "arash",
            "disclosureLevel": 0.5,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        new_snap = apply_reducer_outcome(snap, out)
        pair = next(
            r for r in new_snap.relationshipState if r.from_ == "leila" and r.to == "arash"
        )
        self.assertLess(pair.intimacy, 0.0)

    # ----- silence -----

    def test_silence_mild_negative(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "silence",
            "actorId": "leila",
            "targetId": "arash",
            "disclosureLevel": 0.5,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        new_snap = apply_reducer_outcome(snap, out)
        pair = next(
            r for r in new_snap.relationshipState if r.from_ == "leila" and r.to == "arash"
        )
        self.assertLess(pair.intimacy, 0.0)


# ---------------------------------------------------------------------------
# Validation gate tests
# ---------------------------------------------------------------------------


class ValidationGateTests(unittest.TestCase):
    """The validation gate must reject illegal inputs deterministically."""

    def test_reject_off_whitelist(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        # 'forbidden' is not in the 12-action vocab, so the schema
        # would normally reject first; in the state machine, we
        # whitelist a *single* action and try a different one.
        action = {
            "actionType": "investigate",
            "actorId": "leila",
            "evidenceIds": ["photo_A"],
            "clientActionId": str(uuid.uuid4()),
        }
        with self.assertRaises(ActionRejectedError):
            reduce(action, snap, budget, scene_whitelist={"question"}, cast=_cast())

    def test_question_requires_target(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "question",
            "actorId": "leila",
            "targetId": None,
            "clientActionId": str(uuid.uuid4()),
        }
        with self.assertRaises(TargetRequiredError):
            reduce(action, snap, budget, cast=_cast())

    def test_give_requires_target(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "give",
            "actorId": "leila",
            "targetId": None,
            "evidenceIds": ["photo_A"],
            "clientActionId": str(uuid.uuid4()),
        }
        with self.assertRaises(TargetRequiredError):
            reduce(action, snap, budget, cast=_cast())

    def test_reveal_requires_evidence(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "reveal",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": [],
            "clientActionId": str(uuid.uuid4()),
        }
        with self.assertRaises(EvidenceRequiredError):
            reduce(action, snap, budget, cast=_cast())

    def test_destroy_requires_evidence(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "destroy",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": [],
            "clientActionId": str(uuid.uuid4()),
        }
        with self.assertRaises(EvidenceRequiredError):
            reduce(action, snap, budget, cast=_cast())

    def test_evidence_must_exist(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "reveal",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": ["does_not_exist"],
            "clientActionId": str(uuid.uuid4()),
        }
        with self.assertRaises(EvidenceNotFoundError):
            reduce(action, snap, budget, cast=_cast())

    def test_target_must_be_on_stage(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        action = {
            "actionType": "question",
            "actorId": "leila",
            "targetId": "maziar",  # not in cast
            "clientActionId": str(uuid.uuid4()),
        }
        with self.assertRaises(TargetNotPresentError):
            reduce(action, snap, budget, cast=_cast())

    def test_per_action_budget_exhausted(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        budget.consumed["destroy"] = 1  # already used the 1 allowed
        action = {
            "actionType": "destroy",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": ["photo_A"],
            "clientActionId": str(uuid.uuid4()),
        }
        with self.assertRaises(ActionBudgetExceededError):
            reduce(action, snap, budget, cast=_cast())

    def test_turn_budget_exhausted(self) -> None:
        from engine.exceptions import TurnBudgetExceededError

        snap = _fresh_snapshot()
        budget = _budget()
        budget.elapsed_turns = 8  # max_turns hit
        action = {
            "actionType": "wait",
            "actorId": "leila",
            "clientActionId": str(uuid.uuid4()),
        }
        with self.assertRaises(TurnBudgetExceededError):
            reduce(action, snap, budget, cast=_cast())

    def test_scene_budget_rejects_overcommitted_per_action(self) -> None:
        """P0-3: ``SceneBudget.__post_init__`` must reject contracts whose
        ``per_action`` caps sum to more than ``total_action_budget``.

        The hard cap is a *construction-time* invariant (decision 5 cost
        red line + decision 1 12-action whitelist), so a contract that
        violates it must fail at budget build time, not at first
        reducer dispatch.
        """

        # Sum is 5+6=11, total is 10 — over by 1.
        with self.assertRaises(ValueError) as ctx:
            SceneBudget(
                sceneId="bad_scene",
                max_turns=8,
                total_action_budget=10,
                per_action={"investigate": 5, "destroy": 6},
            )
        self.assertIn("exceeds total_action_budget", str(ctx.exception))

    def test_scene_budget_accepts_under_cap_per_action(self) -> None:
        """The opposite boundary: a budget whose per-action caps *do*
        fit under the total must construct cleanly.
        """

        budget = SceneBudget(
            sceneId="ok_scene",
            max_turns=8,
            total_action_budget=20,
            per_action={"investigate": 5, "destroy": 3, "give": 7},
        )
        self.assertEqual(budget.total_action_budget, 20)
        # Sum of per_action is 15, under the 20 cap.
        self.assertLessEqual(sum(budget.per_action.values()), budget.total_action_budget)

    def test_scene_budget_accepts_exact_match(self) -> None:
        """Equality is allowed: sum exactly equal to total is not over.
        Only the strict ``>`` comparison triggers ValueError.
        """

        budget = SceneBudget(
            sceneId="edge_scene",
            max_turns=8,
            total_action_budget=10,
            per_action={"investigate": 4, "give": 6},
        )
        self.assertEqual(sum(budget.per_action.values()), budget.total_action_budget)


# ---------------------------------------------------------------------------
# Numeric clamp tests
# ---------------------------------------------------------------------------


class NumericClampTests(unittest.TestCase):
    """The per-turn |delta| ≤ 0.25 cap must hold even with extreme inputs."""

    def test_trust_delta_capped(self) -> None:
        snap = _fresh_snapshot()
        budget = _budget()
        # Provide disclosure = 2.0 (out of range); default deltas
        # for comfort are trust=0.20, intimacy=0.25; with mag=2.0
        # these would be 0.40 and 0.50.  The per-turn cap should
        # clamp them to 0.25.
        action = {
            "actionType": "comfort",
            "actorId": "leila",
            "targetId": "arash",
            "disclosureLevel": 2.0,
            "clientActionId": str(uuid.uuid4()),
        }
        out = reduce(action, snap, budget, cast=_cast())
        for d in out.relationshipDeltas:
            self.assertLessEqual(abs(d.trust), 0.25)
            self.assertLessEqual(abs(d.intimacy), 0.25)
            self.assertLessEqual(abs(d.respect), 0.25)
            self.assertLessEqual(abs(d.fear), 0.25)
            self.assertLessEqual(abs(d.unresolvedConflict), 0.25)
        new_snap = apply_reducer_outcome(snap, out)
        for pair in new_snap.relationshipState:
            self.assertLessEqual(abs(pair.trust), 1.0)
            self.assertLessEqual(abs(pair.intimacy), 1.0)
            self.assertLessEqual(abs(pair.respect), 1.0)
            self.assertLessEqual(pair.fear, 1.0)
            self.assertLessEqual(pair.unresolvedConflict, 1.0)

    def test_no_double_application_clamp_audit(self) -> None:
        """Two reducers over the same input produce the same outcome."""

        snap = _fresh_snapshot()
        budget1 = _budget()
        budget2 = _budget()
        action = {
            "actionType": "comfort",
            "actorId": "leila",
            "targetId": "arash",
            "disclosureLevel": 1.0,
            "clientActionId": str(uuid.uuid4()),
        }
        out1 = reduce(action, snap, budget1, cast=_cast())
        # Second reduce call on a fresh budget → same outcome
        out2 = reduce(action, snap, budget2, cast=_cast())
        self.assertEqual(
            [d.to_json_dict() for d in out1.relationshipDeltas],
            [d.to_json_dict() for d in out2.relationshipDeltas],
        )


class DispatchTests(unittest.TestCase):
    """The dispatch table covers all 12 action types."""

    def test_dispatch_table_complete(self) -> None:
        self.assertEqual(set(REDUCERS.keys()), set(ActionType._value2member_map_.keys()))
        self.assertEqual(len(REDUCERS), 12)


if __name__ == "__main__":
    unittest.main()
