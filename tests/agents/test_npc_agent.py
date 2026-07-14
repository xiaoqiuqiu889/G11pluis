"""NpcAgent unit tests.

Covers:

* Happy path — LLM emits a schema-valid NpcProposal
* Retry path — first misshape, retry succeeds
* Failure path — both attempts fail → NpcAgentError
* Four-questions self-check (decision 6) rejects 0-of-4 proposals
* Referenced memories must be in the recall set
* Temperature clamped to [0.3, 0.5]
* Unknown character raises NpcAgentError
* The 12-value vocab is enforced
* Empty recall set still allows a valid proposal
"""

from __future__ import annotations

import sys
import unittest
import uuid

sys.path.insert(0, "server")

from agents import (  # noqa: E402
    InMemoryVectorIndex,
    MemoryManager,
    NPC_AGENT_VERSION,
    NpcAgent,
    NpcAgentError,
    StubModelGateway,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _query_v() -> list[float]:
    return [1.0] + [0.0] * 63


def _scene_contract(
    *,
    forbidden: list[dict] | None = None,
    mandatory: list[dict] | None = None,
    causal: list[str] | None = None,
    cast: list[dict] | None = None,
) -> dict:
    return {
        "sceneId": "photo_lab_2008",
        "title": "地下放映室",
        "era": "2008",
        "core_conflict": "如何分配两张同版毕业照",
        "allowed_actions": [
            "investigate", "reveal", "conceal", "question", "confront",
            "comfort", "give", "destroy", "promise", "wait", "leave", "silence",
        ],
        "allowed_beats": [
            {"beatId": "beat_setup_0", "tier": "setup"},
            {"beatId": "beat_divide_photos", "tier": "rising"},
        ],
        "forbidden_reveals": list(forbidden or []),
        "mandatory_echoes": list(mandatory or []),
        "causal_seeds": list(causal or []),
        "cast": list(cast or [
            {"characterId": "leila", "role": "protagonist"},
            {"characterId": "arash", "role": "ally"},
        ]),
        "max_turns": 8,
        "total_action_budget": 32,
        "legal_endings": [{"endingId": "shared_secret"}],
    }


def _player_action(**overrides) -> dict:
    base = {
        "runId": str(uuid.uuid4()),
        "sceneId": "photo_lab_2008",
        "actionType": "question",
        "actorId": "player",
        "targetId": "arash",
        "utterance": "那张照片里是谁?",
        "tone": "hesitant",
        "disclosureLevel": 0.5,
        "isDeceptive": False,
        "clientActionId": str(uuid.uuid4()),
        "schemaVersion": "1.0.0",
    }
    base.update(overrides)
    return base


def _ok_proposal(**overrides) -> dict:
    def _q05(x: float) -> float:
        """Snap to nearest 0.05 in a way that satisfies jsonschema multipleOf.

        Float-precision trap: ``0.6`` and ``0.15`` are *not*
        multiples of ``0.05`` under IEEE-754 (e.g. ``0.6/0.05`` is
        ``11.9999...``, not ``12.0``), so ``jsonschema``'s
        ``multipleOf`` check rejects them outright.  We snap to the
        nearest multiple of ``0.05`` *that the float representation
        can actually compare equal against*.  The safe grid for
        ``multipleOf=0.05`` is ``{0, 0.05, 0.1, 0.2, 0.25, 0.4, 0.45,
        0.5, 0.55, 0.65, 0.75, 0.8, 0.85, 0.9, 1.0}`` — anything in
        ``{0.15, 0.3, 0.35, 0.6, 0.7, 0.95}`` fails.  We just round
        to the nearest 0.05 and trust the agent's snap pass to
        handle the few precision-failure cases.
        """
        # round-half-to-even via int() (Python's round() does this)
        n = int(round(x / 0.05))
        return n * 0.05

    base = {
        "proposalId": str(uuid.uuid4()),
        "runId": str(uuid.uuid4()),
        "characterId": "arash",
        "proposedAction": "comfort",
        "speechIntent": "comfort",
        "targetId": "leila",
        "referencedMemoryIds": [],
        "beliefUpdatesRequested": [
            {
                "subject": "leila",
                "newState": "reinforced",
                "confidence": _q05(0.55),  # 0.6 is a float-precision trap; 0.55 is safe
            }
        ],
        "reasonCodes": ["memory_resurfaced"],
        "confidence": _q05(0.75),
        "schemaVersion": "1.0.0",
    }
    base.update(overrides)
    # Schema requires multipleOf 0.05 for confidence
    if "confidence" in base and isinstance(base["confidence"], (int, float)):
        base["confidence"] = _q05(float(base["confidence"]))
    if "beliefUpdatesRequested" in base:
        for u in base["beliefUpdatesRequested"]:
            if "confidence" in u and isinstance(u["confidence"], (int, float)):
                u["confidence"] = _q05(float(u["confidence"]))
    return base


def _manager() -> MemoryManager:
    return MemoryManager(
        InMemoryVectorIndex(),
        top_k=4,
        embedder=lambda text: _query_v(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TemperatureClampTests(unittest.TestCase):
    def test_low_boundary_accepted(self) -> None:
        gw = StubModelGateway()
        NpcAgent(gw, _manager(), temperature=0.3)

    def test_high_boundary_accepted(self) -> None:
        gw = StubModelGateway()
        NpcAgent(gw, _manager(), temperature=0.5)

    def test_below_rejected(self) -> None:
        with self.assertRaises(ValueError):
            NpcAgent(StubModelGateway(), _manager(), temperature=0.2)

    def test_above_rejected(self) -> None:
        with self.assertRaises(ValueError):
            NpcAgent(StubModelGateway(), _manager(), temperature=0.6)


class HappyPathTests(unittest.TestCase):
    def test_proposal_emitted(self) -> None:
        gw = StubModelGateway()
        gw.register("npc_agent", "npc_proposal", _ok_proposal())
        agent = NpcAgent(gw, _manager())
        out = agent.propose(
            run_id=str(uuid.uuid4()),
            character_id="arash",
            scene_contract=_scene_contract(),
            player_action=_player_action(),
        )
        self.assertEqual(out.proposal["characterId"], "arash")
        self.assertEqual(out.proposal["proposedAction"], "comfort")
        self.assertTrue(out.four_questions.passes)

    def test_version_pinned(self) -> None:
        self.assertEqual(NPC_AGENT_VERSION, "1.0.0")

    def test_unknown_character_raises(self) -> None:
        gw = StubModelGateway()
        agent = NpcAgent(gw, _manager())
        with self.assertRaises(NpcAgentError):
            agent.propose(
                run_id=str(uuid.uuid4()),
                character_id="nonexistent",
                scene_contract=_scene_contract(),
                player_action=_player_action(),
            )


class RetryPathTests(unittest.TestCase):
    def test_first_failure_recovers_on_retry(self) -> None:
        called = {"n": 0}

        class Flakey:
            def complete(self_inner, request):  # type: ignore[no-untyped-def]
                from agents import ModelResponse
                called["n"] += 1
                if called["n"] == 1:
                    return ModelResponse(
                        payload={"proposalId": "x", "characterId": "arash"},  # missing required fields
                        model="stub",
                        input_tokens=1,
                        output_tokens=1,
                        latency_ms=1,
                    )
                return ModelResponse(
                    payload=_ok_proposal(),
                    model="stub",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=1,
                )

        agent = NpcAgent(Flakey(), _manager())  # type: ignore[arg-type]
        out = agent.propose(
            run_id=str(uuid.uuid4()),
            character_id="arash",
            scene_contract=_scene_contract(),
            player_action=_player_action(),
        )
        self.assertEqual(out.proposal["proposedAction"], "comfort")
        self.assertEqual(called["n"], 2)


class FourQuestionsGateTests(unittest.TestCase):
    def test_proposal_with_zero_questions_rejected(self) -> None:
        gw = StubModelGateway()
        # All-zero proposal: no belief updates, no artifact updates,
        # no fired seeds.  Agent will compute passes=False and raise.
        gw.register("npc_agent", "npc_proposal", {
            "proposalId": str(uuid.uuid4()),
            "runId": str(uuid.uuid4()),
            "characterId": "arash",
            "proposedAction": "silence",
            "speechIntent": "remain_silent",
            "reasonCodes": ["witnessed_action"],
            "confidence": 0.5,
            "schemaVersion": "1.0.0",
            "beliefUpdatesRequested": [],
            "referencedMemoryIds": [],
        })
        agent = NpcAgent(gw, _manager())
        with self.assertRaises(NpcAgentError):
            agent.propose(
                run_id=str(uuid.uuid4()),
                character_id="arash",
                scene_contract=_scene_contract(),
                player_action=_player_action(),
            )


class UngroundedMemoryTest(unittest.TestCase):
    def test_referenced_memory_outside_recall_is_dropped(self) -> None:
        gw = StubModelGateway()
        # Propose referencing a memory not in the recall set.
        gw.register("npc_agent", "npc_proposal", _ok_proposal(
            referencedMemoryIds=["memory_does_not_exist"],
            beliefUpdatesRequested=[{
                "subject": "leila",
                "newState": "reinforced",
                "confidence": 0.55,  # 0.6 fails multipleOf=0.05 under IEEE-754
            }],
        ))
        agent = NpcAgent(gw, _manager())
        out = agent.propose(
            run_id=str(uuid.uuid4()),
            character_id="arash",
            scene_contract=_scene_contract(),
            player_action=_player_action(),
        )
        # The bad ref is dropped; the proposal is accepted.
        self.assertNotIn("memory_does_not_exist", out.proposal["referencedMemoryIds"])


class TwelveValueVocabEnforcementTests(unittest.TestCase):
    def test_invalid_proposed_action_rejected_by_schema(self) -> None:
        gw = StubModelGateway()
        gw.register("npc_agent", "npc_proposal", _ok_proposal(
            proposedAction="hug",  # not in 12-value vocab
            beliefUpdatesRequested=[{
                "subject": "leila",
                "newState": "reinforced",
                "confidence": 0.55,  # 0.6 fails multipleOf=0.05 under IEEE-754
            }],
        ))
        agent = NpcAgent(gw, _manager())
        with self.assertRaises(NpcAgentError):
            agent.propose(
                run_id=str(uuid.uuid4()),
                character_id="arash",
                scene_contract=_scene_contract(),
                player_action=_player_action(),
            )


class DoubleFailurePathTests(unittest.TestCase):
    def test_two_failures_raise_NpcAgentError(self) -> None:
        class AlwaysFail:
            def complete(self_inner, request):  # type: ignore[no-untyped-def]
                from agents import ModelResponse
                return ModelResponse(
                    payload={"proposalId": "x"},
                    model="stub",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=1,
                )

        agent = NpcAgent(AlwaysFail(), _manager())  # type: ignore[arg-type]
        with self.assertRaises(NpcAgentError):
            agent.propose(
                run_id=str(uuid.uuid4()),
                character_id="arash",
                scene_contract=_scene_contract(),
                player_action=_player_action(),
            )


if __name__ == "__main__":
    unittest.main()
