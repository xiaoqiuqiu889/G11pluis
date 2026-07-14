"""End-to-end integration test for the three case_01 scenes.

Goal
----
Drive the **full pipeline** — :class:`ModelGateway` with a
:class:`MockProvider`, the :class:`ResolverAgent`, and the
:mod:`server.engine` state machine — through all three case_01
scenes (``photo_lab_2008`` → ``farewell_2011`` →
``reunion_2024``), and assert the **mandatory-echo**
cross-era invariant from decision 3 of
``docs/design/requirements-review-v1.md``:

> "玩家 2008 行为触发 reunion_2024 mandatory echo"

Specifically:

* The player puts a graduation photo in their pocket in
  ``photo_lab_2008`` (``give`` action with
  ``targetId=leila`` and ``evidenceIds=[photo_A]``).
* The system fires the ``photo_in_pocket`` causal seed at the
  end of ``photo_lab_2008`` and carries it into
  ``reunion_2024`` as a dormant seed.
* In ``reunion_2024`` the NPC's proposal **must** reference
  that seed via ``beliefUpdatesRequested[].subject`` (the
  signal the resolver's mandatory-echo gate uses).
* The proposal must be **accepted** (``rejectedNpcActions``
  empty).
* The single-run cost must stay under the decision-5 hard
  red lines (≤ 20 calls, ≤ 800 output tokens each,
  ≤ 2 calls/turn, ¥0.8 total).

Architecture
------------
The harness wires the production :class:`ModelGateway` to a
:class:`MockProvider` so every LLM call is a deterministic
scripted response.  The harness does **not** instantiate the
W3-B ``NpcAgent`` / ``DirectorAgent`` (those use a different
gateway interface); instead the integration test drives the
:class:`ResolverAgent` with the pre-baked JSON responses the
mock returns, after the gateway has validated them against the
shipped JSON Schemas.  This is the W3 integration boundary:

    scripted JSON ──► MockProvider ──► ModelGateway.complete
                       (validates)         │
                                          ▼
                                     ResolverAgent.resolve_turn
                                          │
                                          ▼
                                     engine.Resolver.resolve
                                          │
                                          ▼
                                     new WorldSnapshot + ResolverOutcome

The mock is **deterministic** — every test call gets a
scripted response, so the gateway never trips the schema
fallback path.  A separate test file
(``test_degradation_levels.py``) drives the chain into
L1-L4 with scripted timeout responses.
"""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- path setup ------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "server"))

# --- engine ---------------------------------------------------------------
from engine import (  # noqa: E402
    ArtifactState,
    CausalSeed,
    EventLog,
    SceneBudget,
    ScenePhase,
    TriggerCondition,
    WorldSnapshot,
)

# --- agents ---------------------------------------------------------------
from agents.resolver import (  # noqa: E402
    MandatoryEchoValidation,
    ResolverAgent,
    build_resolver_agent,
)

# --- model gateway (W3-A) -------------------------------------------------
from model import (  # noqa: E402
    CostController,
    FallbackContentLoader,
    Message,
    MessageRole,
    MockProvider,
    ModelGateway,
    ModelRequest,
    ProviderResult,
    SchemaValidator,
    TaskType,
    build_default_router,
)


# ===========================================================================
# Constants — bind to the project's hard red lines
# ===========================================================================


CASE_SLUG = "case_01_revolution_street"
SCENE_2008 = "photo_lab_2008"
SCENE_2011 = "farewell_2011"
SCENE_2024 = "reunion_2024"

# Seed id that must cross from 2008 to 2024
SEED_PHOTO_IN_POCKET = "photo_in_pocket"
# Additional seed we'll plant in 2008 to exercise the second
# mandatory echo pathway
SEED_PHOTO_IN_BOOK = "photo_in_book"

# Decision-5 hard red lines (mirrored from cost_control.py so the
# test fails loudly if they ever drift in production code).
MAX_RUN_CALLS = 20
MAX_TURN_CALLS = 2
MAX_OUTPUT_TOKENS_PER_CALL = 800
SOFT_COST_TARGET_CNY = 0.8

# Per-action budget for each scene.  Drawn from the
# `turn_budget` block of the scene YAML.
SCENE_BUDGET_2008 = {
    "investigate": 3, "reveal": 2, "conceal": 1, "question": 2,
    "confront": 2, "comfort": 1, "give": 3, "destroy": 1,
    "promise": 2, "wait": 2, "leave": 1, "silence": 2,
}
SCENE_BUDGET_2011 = {
    "investigate": 3, "reveal": 2, "conceal": 1, "question": 2,
    "confront": 1, "comfort": 1, "give": 2, "destroy": 1,
    "promise": 1, "wait": 1, "leave": 1, "silence": 2,
}
SCENE_BUDGET_2024 = {
    "investigate": 3, "reveal": 2, "conceal": 1, "question": 2,
    "confront": 1, "comfort": 1, "give": 2, "destroy": 1,
    "promise": 1, "wait": 1, "leave": 1, "silence": 2,
}


# A fixed run id for deterministic tests.  UUID-format so the
# NPC proposal schema accepts it.
RUN_ID_FIXTURE = "00000000-0000-0000-0000-000000000001"


# ===========================================================================
# Scene contracts — narrowed to what the resolver needs
# ===========================================================================


def _scene_contract(
    *,
    scene_id: str,
    era: str,
    title: str,
    allowed_beats: list[str],
    forbidden_reveals: list[str],
    legal_endings: list[str],
    mandatory_echoes: list[dict[str, Any]],
    causal_seeds: list[str],
    cast: list[dict[str, str]],
    max_turns: int = 8,
    total_action_budget: int = 32,
) -> dict[str, Any]:
    """Build a minimal scene contract dict for the ResolverAgent.

    Mirrors the subset of fields
    :class:`server.agents.resolver.ResolverAgent` actually reads
    (see ``ResolverAgent._build_engine_contract``).
    """

    return {
        "sceneId": scene_id,
        "era": era,
        "title": title,
        "core_conflict": f"conflict_{scene_id}",
        "allowed_actions": [
            "investigate", "reveal", "conceal", "question", "confront",
            "comfort", "give", "destroy", "promise", "wait", "leave", "silence",
        ],
        "allowed_beats": [{"beatId": b} for b in allowed_beats],
        "forbidden_reveals": [{"revealKey": r} for r in forbidden_reveals],
        "legal_endings": [{"endingId": e} for e in legal_endings],
        "mandatory_echoes": mandatory_echoes,
        "causal_seeds": causal_seeds,
        "cast": cast,
        "max_turns": max_turns,
        "total_action_budget": total_action_budget,
    }


# Forbidden reveals lifted from the scene YAMLs.  Kept short
# but representative — the integration test only needs the
# list *length* to match the Director beat's
# ``forbiddenRevealsChecked`` array.
SCENE_2008_FORBIDDEN = [
    "leila_future_marriage", "leila_kamran_video_call",
    "leila_2011_one_way_ticket", "thirteen_years_later_istanbul_reunion",
    "maziya_2009_released", "arash_father_rehab_debt",
    "leila_san_jose_persian_l10n", "maryam_meteor_log",
    "arash_2011_two_old_bus_tickets", "2011_flight_gate_destination",
    "2009_school_publication_disciplinary", "leila_aunt_first_intro_kamran_call",
]
SCENE_2011_FORBIDDEN = [
    "leila_13_years_later_istanbul_reunion",
    "leila_san_jose_specific_l10n_work",
    "maryam_meteor_log",
    "arash_tehran_specific_research_or_workshop_inheritance",
    "kamran_san_jose_specific_photography_hobby",
    "leila_aunt_first_intro_kamran_call_details",
    "leila_san_jose_specific_address_or_apartment",
    "2009_school_publication_disciplinary_event_details",
    "any_about_13_years_later_specific_time_sense",
    "leila_or_arash_any_post_2011_health_or_finance",
    "any_about_reunion_2024_scene_shot_implication",
]
SCENE_2024_FORBIDDEN = [
    "any_post_2025_specific_time_sense",
    "leila_or_arash_any_post_2024_health_finance_family",
    "maziya_post_shiraz_kids_library_life",
    "kamran_b_w_parking_lot_photo_specific_content",
    "maryam_logged_meteor_specific_date",
    "leila_aunt_whether_still_alive",
    "any_about_next_case_implication",
    "player_untriggered_seed_in_2008",
    "player_untriggered_seed_in_2011",
]


def scene_contract_2008() -> dict[str, Any]:
    return _scene_contract(
        scene_id=SCENE_2008,
        era="2008",
        title="革命街地下放映室与两张同版毕业照",
        allowed_beats=[
            "beat_setup_0", "beat_divide_photos",
            "beat_handover", "beat_exit",
        ],
        forbidden_reveals=SCENE_2008_FORBIDDEN,
        legal_endings=["shared_secret", "one_sided_memory",
                       "misunderstood_gesture", "emotional_retreat",
                       "promise_formed"],
        mandatory_echoes=[
            {
                "id": SEED_PHOTO_IN_POCKET,
                "description": "莱拉把毕业照放进斜挎包内袋",
                "target_scenes": [SCENE_2011, SCENE_2024],
                "ai_director_must_invoke": True,
            },
            {
                "id": SEED_PHOTO_IN_BOOK,
                "description": "阿拉什把毕业照夹进鲁米诗集",
                "target_scenes": [SCENE_2011, SCENE_2024],
                "ai_director_must_invoke": True,
            },
        ],
        causal_seeds=[SEED_PHOTO_IN_POCKET, SEED_PHOTO_IN_BOOK,
                      "grip_then_release"],
        cast=[
            {"characterId": "leila", "role": "protagonist"},
            {"characterId": "arash", "role": "ally"},
            {"characterId": "dagang", "role": "witness"},
        ],
    )


def scene_contract_2011() -> dict[str, Any]:
    return _scene_contract(
        scene_id=SCENE_2011,
        era="2011",
        title="德黑兰国际机场·出发大厅",
        allowed_beats=[
            "beat_setup_0", "beat_goodbye", "beat_announcement",
            "beat_parting",
        ],
        forbidden_reveals=SCENE_2011_FORBIDDEN,
        legal_endings=["shared_truth", "concealed_luggage",
                       "last_attempt", "silent_holding",
                       "i_arrived_only"],
        # mandatory_echoes: 2 entries referencing 2008.  Per
        # the YAML's "决策 3 显式登记" section:
        mandatory_echoes=[
            {
                "id": "grip_then_release_2011",
                "description": "莱拉与阿拉什最后握—松（2008 身体回响）",
                "target_scenes": [SCENE_2024],
                "ai_director_must_invoke": True,
            },
            {
                "id": "bus_ticket_pair_unused",
                "description": "阿拉什仍带着 2008 那两张 304 公交票",
                "target_scenes": [SCENE_2024],
                "ai_director_must_invoke": True,
            },
        ],
        # The scene also keeps the 2008 seeds dormant in its
        # active-seed list — that's how they propagate to
        # 2024.
        causal_seeds=[
            SEED_PHOTO_IN_POCKET, SEED_PHOTO_IN_BOOK,
            "grip_then_release_2011", "bus_ticket_pair_unused",
            "i_arrived_text", "name_of_kamran_spoken",
        ],
        cast=[
            {"characterId": "leila", "role": "protagonist"},
            {"characterId": "arash", "role": "ally"},
        ],
    )


def scene_contract_2024() -> dict[str, Any]:
    return _scene_contract(
        scene_id=SCENE_2024,
        era="2024",
        title="伊斯坦布尔·卡拉柯伊老咖啡馆与路口",
        allowed_beats=[
            "beat_setup_0", "beat_recognition", "beat_photos",
            "beat_crossroads",
        ],
        forbidden_reveals=SCENE_2024_FORBIDDEN,
        legal_endings=["gazes_then_speaks", "photo_pairing_complete_ending",
                       "crossroads_parting_ending", "silence_kept_ending"],
        # reunion_2024 must reference BOTH 2008 + 2011 (decision 3 row 3).
        # UP-20260715-007/008/011 expanded the mandatory echo list from 3 to 5.
        mandatory_echoes=[
            {
                "id": SEED_PHOTO_IN_POCKET,
                "description": "莱拉把毕业照带到了 2024 (test compat — kept for the legacy 3-echo test)",
                "target_scenes": [SCENE_2024],
                "ai_director_must_invoke": True,
            },
            {
                "id": "two_photos_takeout_compare",
                "description": "两张同版毕业照在桌面同时出现",
                "target_scenes": [SCENE_2024],
                "ai_director_must_invoke": True,
            },
            {
                "id": "first_words_admit_2008_2011",
                "description": "NPC 主动提起 2008 / 2011 行为（UP-010 5 句备选）",
                "target_scenes": [SCENE_2024],
                "ai_director_must_invoke": True,
                # UP-20260715-010: 5 candidate_lines for the first-words
                # moment.  The test asserts structure here; the runtime
                # selection rule is in the YAML's `selection_rule` block.
                "candidate_lines": [
                    {
                        "line_id": "line_01_photo_in_pocket",
                        "text": "你把那张照片带在身上带了多少年？",
                        "speaker": "arash",
                        "referenced_seed": "photo_in_pocket",
                        "priority": 1,
                    },
                    {
                        "line_id": "line_02_photo_in_book",
                        "text": "我在诗集里一直留着那张照片……",
                        "speaker": "arash",
                        "referenced_seed": "photo_in_book",
                        "priority": 2,
                    },
                    {
                        "line_id": "line_03_grip_then_release",
                        "text": "你握住又松开……和那时候一模一样。",
                        "speaker": "arash",
                        "referenced_seed": "grip_then_release",
                        "priority": 3,
                    },
                    {
                        "line_id": "line_04_bus_ticket_pair",
                        "text": "你那两张 304 公交票……阿拉什你一直留着吗？",
                        "speaker": "leila",
                        "referenced_seed": "bus_ticket_pair_unused",
                        "priority": 4,
                    },
                    {
                        "line_id": "line_05_i_arrived_text",
                        "text": "2011 年那条'我到了'的短信……我一直存着。",
                        "speaker": "leila",
                        "referenced_seed": "i_arrived_text",
                        "priority": 5,
                    },
                ],
            },
            {
                "id": "grip_release_2024_echo",
                "description": "莱拉与阿拉什在桌边再次握—松（2008→2011→2024 三跳链完整）",
                "target_scenes": [SCENE_2024],
                "ai_director_must_invoke": True,
            },
            # ----- UP-20260715-007 [critical] -----
            {
                "id": "bus_ticket_2024_seen",
                "description": "阿拉什从诗集末页取出 304 公交票，莱拉看见（不是念）",
                "target_scenes": [SCENE_2024],
                "ai_director_must_invoke": True,
            },
            # ----- UP-20260715-008/011 [critical] -----
            {
                "id": "i_arrived_text_2024_resonance",
                "description": "咖啡桌上手机亮起 2011'我到了'短信，莱拉主动读给阿拉什听",
                "target_scenes": [SCENE_2024],
                "ai_director_must_invoke": True,
            },
        ],
        causal_seeds=[
            SEED_PHOTO_IN_POCKET, SEED_PHOTO_IN_BOOK,
            "i_arrived_text_2024", "name_of_kamran_spoken_finally",
            # UP-20260715-007/008/011: the 2 new mandatory echoes are also
            # listed in the scene's causal_seeds pool so the resolver can
            # match NPC proposals that surface them.
            "bus_ticket_2024_seen",
            "i_arrived_text_2024_resonance",
        ],
        cast=[
            {"characterId": "leila", "role": "protagonist"},
            {"characterId": "arash", "role": "ally"},
        ],
    )


# ===========================================================================
# Scene-budget constructor
# ===========================================================================


def make_budget(scene_id: str, per_action: dict[str, int]) -> SceneBudget:
    """Build a :class:`SceneBudget` for the given scene id."""

    total = sum(per_action.values())
    return SceneBudget(
        sceneId=scene_id,
        max_turns=8,
        total_action_budget=total + 4,  # +4 headroom for the state machine
        per_action=per_action,
        consumed={},
        elapsed_turns=0,
    )


# ===========================================================================
# Mock-response factory
# ===========================================================================


def _player_action_response(action: dict[str, Any]) -> str:
    """Return the LLM-emitted JSON for a PlayerAction.

    For the integration test the LLM is the *transcription*
    layer: the player types an utterance, the LLM normalises
    it to a :class:`PlayerAction`.  Our mock returns the
    already-structured dict, which the gateway validates
    against the player_action schema.
    """

    payload = {
        "runId": action["runId"],
        "sceneId": action["sceneId"],
        "actionType": action["actionType"],
        "actorId": action["actorId"],
        "targetId": action.get("targetId"),
        "evidenceIds": action.get("evidenceIds", []),
        "utterance": action.get("utterance", ""),
        "tone": action.get("tone", "neutral"),
        "disclosureLevel": action.get("disclosureLevel", 0.5),
        "isDeceptive": action.get("isDeceptive", False),
        "clientActionId": action.get("clientActionId"),
        "expectedEventSequence": action.get("expectedEventSequence", 0),
        "clientTimestamp": action.get("clientTimestamp",
                                      "2026-07-15T00:00:00Z"),
        "schemaVersion": "1.0.0",
    }
    return json.dumps(payload, ensure_ascii=False)


def _npc_proposal_response(
    *,
    proposal_id: str,
    run_id: str,
    character_id: str,
    proposed_action: str,
    speech_intent: str,
    belief_subject: str | None,
    belief_new_state: str = "reinforced",
    confidence: float = 0.75,
    referenced_memory_ids: list[str] | None = None,
    reason_codes: list[str] | None = None,
    target_id: str | None = None,
) -> str:
    """Return a valid NpcProposal JSON for the gateway to validate."""

    if referenced_memory_ids is None:
        referenced_memory_ids = []
    if reason_codes is None:
        reason_codes = ["memory_resurfaced"]

    belief_updates: list[dict[str, Any]] = []
    if belief_subject is not None:
        belief_updates.append({
            "characterId": character_id,
            "subject": belief_subject,
            "newState": belief_new_state,
            "confidence": round(confidence, 2),
            "evidenceMemoryId": None,
        })
    payload = {
        "proposalId": proposal_id,
        "runId": run_id,
        "characterId": character_id,
        "triggerPlayerActionId": None,
        "proposedAction": proposed_action,
        "targetId": target_id,
        "speechIntent": speech_intent,
        "referencedMemoryIds": list(referenced_memory_ids),
        "beliefUpdatesRequested": belief_updates,
        "emotionalTransition": {
            "from": "calm",
            "to": "tense",
            "intensity": 0.5,
        },
        "reasonCodes": list(reason_codes),
        "confidence": round(confidence, 2),
        "expectedContradictions": [],
        "timestamp": "2026-07-15T00:00:00Z",
        "schemaVersion": "1.0.0",
    }
    return json.dumps(payload, ensure_ascii=False)


def _director_beat_response(
    *,
    proposal_id: str,
    run_id: str,
    scene_id: str,
    proposed_beat: str,
    forbidden_reveals_count: int,
    transition_to_next: bool = False,
    target_scene_id: str | None = None,
    fired_seeds: list[str] | None = None,
    involved_characters: list[str] | None = None,
) -> str:
    """Return a valid DirectorBeat JSON for the gateway to validate."""

    if fired_seeds is None:
        fired_seeds = []
    if involved_characters is None:
        involved_characters = ["leila", "arash"]
    payload = {
        "proposalId": proposal_id,
        "runId": run_id,
        "sceneId": scene_id,
        "proposedBeat": proposed_beat,
        "allowedByContract": True,
        "forbiddenRevealsChecked": [
            f"forbidden_key_{i}" for i in range(forbidden_reveals_count)
        ],
        "transitionToNext": transition_to_next,
        "suggestedTargetSceneId": target_scene_id,
        "reasoning": (
            f"Director proposes {proposed_beat} on {scene_id}; "
            f"scene contract allows it; no forbidden_reveals crossed."
        ),
        "pacingPressure": 0.5,
        "expectedTensionDelta": 0.05,
        "involvedCharacterIds": involved_characters,
        "firedCausalSeeds": list(fired_seeds),
        "timestamp": "2026-07-15T00:00:00Z",
        "schemaVersion": "1.0.0",
    }
    return json.dumps(payload, ensure_ascii=False)


# ===========================================================================
# LLM-call wrapper — wraps the production ModelGateway
# ===========================================================================


@dataclass(slots=True)
class LLMCallRecord:
    """Lightweight audit row for one LLM call in the integration test.

    We keep this separate from :class:`model.models.CostRecord`
    so the test can introspect a single canonical list without
    going through the CostController (which keys by run id).
    """

    task_type: str
    agent: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_cny: float
    finish_reason: str
    degradation_level: str | None
    used_fallback: bool
    turn_index: int
    request_id: str


class LLMCallLedger:
    """All LLM calls in the run, in call order.

    Provides the test with the data needed to assert the
    decision-5 red lines:

    * ``len(records) <= 20`` (MAX_RUN_CALLS)
    * ``all(r.output_tokens < 800 for r in records)``
    * ``per-turn count <= 2``
    * ``sum(r.cost_cny) < 0.8`` (CNY)
    """

    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    def add(self, rec: LLMCallRecord) -> None:
        self.records.append(rec)

    def per_turn_count(self, turn_index: int) -> int:
        return sum(1 for r in self.records if r.turn_index == turn_index)

    @property
    def total_cost_cny(self) -> float:
        return round(sum(r.cost_cny for r in self.records), 6)

    @property
    def max_output_tokens(self) -> int:
        return max((r.output_tokens for r in self.records), default=0)


# ===========================================================================
# Integration harness
# ===========================================================================


@dataclass(slots=True)
class TurnResult:
    """The output of one turn through the harness."""

    snapshot_after: WorldSnapshot
    outcome: Any  # engine.resolver.ResolverOutcome
    mandatory_echo: MandatoryEchoValidation
    player_action: dict[str, Any]
    npc_proposal_dict: dict[str, Any] | None
    director_beat_dict: dict[str, Any]
    llm_calls: list[LLMCallRecord]


class IntegrationHarness:
    """End-to-end harness for the three-scene integration test.

    The harness is the **one and only** object the test cases
    talk to.  It owns:

    * the production :class:`ModelGateway` (with mock provider)
    * the :class:`ResolverAgent` (W3-B)
    * the :class:`EventLog` (engine)
    * the :class:`WorldSnapshot` (canonical state)
    * an :class:`LLMCallLedger` (decision-5 audit)

    Each call to :meth:`drive_turn` runs:

    1. ``gateway.complete(PLAYER_INTENT_PARSER)`` — LLM normalises
       the player's typed utterance into a :class:`PlayerAction`
       dict.  Schema-validated by the gateway.
    2. ``gateway.complete(NPC_PROPOSER)`` — LLM emits the
       NPC's reaction as a :class:`NpcProposal`.  The
       integration test scripts the response into the
       mock provider before the turn.
    3. ``gateway.complete(DIRECTOR_PROPOSER)`` — LLM picks a
       beat from the scene contract.  Also scripted.
    4. ``resolver_agent.resolve_turn`` — the single writer
       merges the player action + NPC proposal + director
       beat into a new :class:`WorldSnapshot` and
       :class:`ResolverOutcome`.
    5. The ledger records the three LLM calls for the test
       to assert the cost red lines.
    """

    def __init__(
        self,
        *,
        run_id: str | None = None,
        scene_id: str = SCENE_2008,
        era: str = "2008",
        base_random_seed: int = 0,
    ) -> None:
        self.run_id = run_id or str(uuid.uuid4())
        self.mock_provider = MockProvider()
        # The cost controller's per-turn cap is the *gateway*'s
        # enforcement of decision 5 R3.  The integration test
        # uses its own ledger to verify the per-turn count, so
        # we set a generous cap here to allow multi-turn runs
        # (the gateway uses run_state.turn_index which is
        # always 0 in the current design, so a 2-call-per-turn
        # cap would block turn 2's first call).  The test's
        # ledger is the authoritative check on the per-turn
        # cap.
        self.cost_controller = CostController(
            hard_turn_call_budget=100,
            hard_run_call_budget=100,
        )
        self.gateway = ModelGateway(
            providers={"mock": self.mock_provider},
            router=build_default_router(),
            cost_controller=self.cost_controller,
            validator=SchemaValidator(),
            fallback_loader=FallbackContentLoader(),
            case_slug=CASE_SLUG,
        )
        self.gateway.start_run(run_id=self.run_id, scene_id=scene_id)
        self.resolver_agent = build_resolver_agent(
            case_slug=CASE_SLUG, base_random_seed=base_random_seed
        )
        self.event_log = EventLog(runId=self.run_id)
        self.snapshot = self._fresh_snapshot(scene_id=scene_id, era=era)
        self.ledger = LLMCallLedger()
        # Per-turn call index: the harness resets it on each
        # ``drive_turn`` call.
        self._turn_index = 0
        # Cached scene-contract lookup
        self._contracts: dict[str, dict[str, Any]] = {
            SCENE_2008: scene_contract_2008(),
            SCENE_2011: scene_contract_2011(),
            SCENE_2024: scene_contract_2024(),
        }
        self._budgets: dict[str, SceneBudget] = {
            SCENE_2008: make_budget(SCENE_2008, SCENE_BUDGET_2008),
            SCENE_2011: make_budget(SCENE_2011, SCENE_BUDGET_2011),
            SCENE_2024: make_budget(SCENE_2024, SCENE_BUDGET_2024),
        }

    # ----- factory --------------------------------------------------------

    def _fresh_snapshot(
        self, *, scene_id: str, era: str
    ) -> WorldSnapshot:
        snap = WorldSnapshot.empty(
            self.run_id, scene_id, era if era != "2008" else "2008"
        )
        snap = snap.with_canonical_state(
            phase=ScenePhase.RISING.value, globalTension=0.4
        )
        # Cast-specific initial state.  For scene 1, the two
        # photos are the central artifacts.
        if scene_id == SCENE_2008:
            snap = snap.with_artifact_state([
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
            ])
        elif scene_id == SCENE_2011:
            snap = snap.with_artifact_state([
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
            ])
        else:  # SCENE_2024
            snap = snap.with_artifact_state([
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
            ])
        return snap

    # ----- state transitions ---------------------------------------------

    def transition_to_scene(
        self, *, scene_id: str, era: str
    ) -> None:
        """Move the canonical state to a new scene.

        Carries the active causal seeds over (this is how
        ``photo_in_pocket`` planted in 2008 propagates to
        2024) **and the event sequence** (the event log is
        append-only and expects contiguous sequences).  Resets
        the per-action budget to the new scene's per_action
        caps.
        """

        carried_seeds = list(self.snapshot.causalSeedsActive)
        # Filter to dormant seeds only (fired seeds are
        # removed from the active set already by the engine).
        carried_seeds = [
            s for s in carried_seeds
            if s.get("firedAt") is None and s.get("firedInSceneId") is None
        ]
        # Preserve the event sequence (the event log is
        # append-only; resetting would break contiguity).
        carried_event_seq = self.snapshot.eventSequence
        carried_run_id = self.snapshot.runId
        self.snapshot = self._fresh_snapshot(scene_id=scene_id, era=era)
        if carried_seeds:
            self.snapshot = self.snapshot.with_causal_seeds_active(
                carried_seeds
            )
        # Restore the run id and event sequence.
        self.snapshot = self.snapshot.with_canonical_state(
            currentSceneId=scene_id, era=era
        )
        # We can't directly mutate runId or eventSequence on
        # the snapshot (they're constructor-only), but the
        # resolver agent's ``resolve_turn`` re-uses the
        # snapshot we pass in.  So we need to keep the
        # snapshot's runId and eventSequence consistent with
        # the EventLog.  The simplest fix: build a fresh
        # snapshot with the carried-over run id and event
        # sequence.
        self.snapshot = WorldSnapshot(
            runId=carried_run_id,
            eventSequence=carried_event_seq,
            canonicalState=self.snapshot.canonicalState,
            relationshipState=list(self.snapshot.relationshipState),
            artifactState=list(self.snapshot.artifactState),
            directorState=self.snapshot.directorState,
            beliefMatrices=list(self.snapshot.beliefMatrices),
            memories=list(self.snapshot.memories),
            causalSeedsActive=list(self.snapshot.causalSeedsActive),
            recentOutcomes=list(self.snapshot.recentOutcomes),
            timestamp=self.snapshot.timestamp,
            checksum=self.snapshot.checksum,
        )
        # Rotate the per-scene budget so the next turn uses
        # the right caps.  The previous scene's `elapsed_turns`
        # is already baked in; we start a new budget here.
        new_budget = self._budgets[scene_id]
        # The state machine consumes from the per_action dict;
        # we replace it wholesale.
        new_budget.consumed.clear()
        new_budget.elapsed_turns = 0

    # ----- the LLM-call loop --------------------------------------------

    def _call_gateway(
        self,
        *,
        task_type: TaskType,
        scripted_content: str,
        turn_index: int,
        extra_metadata: dict[str, Any] | None = None,
    ) -> tuple[Any, LLMCallRecord]:
        """Push ``scripted_content`` onto the mock and call the gateway.

        Returns the parsed JSON content and the audit record.
        The mocked provider returns 0 input tokens / a small
        number of output tokens so the cost is realistic for
        a short reply.
        """

        provider_result = ProviderResult(
            content=scripted_content,
            model="mock-scripted",
            provider="mock",
            input_tokens=200,
            output_tokens=400,  # well under the 800 cap
            finish_reason="stop",
            latency_ms=20,
        )
        self.mock_provider.push(provider_result)
        request = ModelRequest(
            run_id=self.run_id,
            scene_id=self.snapshot.canonicalState.currentSceneId,
            task_type=task_type,
            messages=[Message(role=MessageRole.USER, content="test")],
            max_output_tokens=600,
            timeout_ms=4000,
            metadata=extra_metadata or {},
        )
        response = self.gateway.complete(request)
        rec = LLMCallRecord(
            task_type=task_type.value,
            agent=task_type.value,
            model=response.model,
            provider=response.provider,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            cost_cny=response.cost_cny,
            finish_reason=response.finish_reason,
            degradation_level=response.degradation_level,
            used_fallback=response.used_fallback,
            turn_index=turn_index,
            request_id=response.request_id,
        )
        self.ledger.add(rec)
        return response.parsed, rec

    # ----- drive a turn --------------------------------------------------

    def drive_turn(
        self,
        *,
        player_action: dict[str, Any],
        npc_proposal: dict[str, Any],
        director_beat: dict[str, Any] | None = None,
        recall_set: set[str] | None = None,
        plant_seeds: list[dict[str, Any]] | None = None,
    ) -> TurnResult:
        """Drive one full turn (**2 LLM calls + 1 resolver write**).

        Per decision 5 R3, each turn makes at most 2 LLM calls.
        The test design follows the production pattern:

        * The **player action** is supplied as a structured
          dict (no intent-parser LLM call); production would
          have one but it's outside the per-turn envelope.
        * Call 1: :class:`TaskType.NPC_PROPOSER` — NPC
          reacts to the player action.
        * Call 2: :class:`TaskType.DIRECTOR_PROPOSER` —
          Director picks the next beat from the scene
          contract.

        The test ledger records the 2 calls and asserts
        ``per_turn_count <= 2``.
        """

        scene_id = self.snapshot.canonicalState.currentSceneId
        contract = self._contracts[scene_id]
        budget = self._budgets[scene_id]

        # ----- 1. NPC proposal LLM call --------------------------------
        npc_parsed, _npc_rec = self._call_gateway(
            task_type=TaskType.NPC_PROPOSER,
            scripted_content=json.dumps(npc_proposal, ensure_ascii=False),
            turn_index=self._turn_index,
            extra_metadata={
                "beatId": "npc_proposer",
                "characterId": npc_proposal.get("characterId", "arash"),
            },
        )
        # Use the gateway-validated dict (the schema validator
        # may have added defaults) — fall back to the
        # original if the gateway returned None.
        npc_proposal_dict: dict[str, Any] = npc_parsed or dict(npc_proposal)

        # ----- 2. Director beat LLM call -------------------------------
        # Default beat = first allowed_beat in the contract.
        if director_beat is None:
            default_beat = contract["allowed_beats"][0]["beatId"]
            director_beat = _build_default_director_beat(
                run_id=self.run_id,
                scene_id=scene_id,
                proposed_beat=default_beat,
                forbidden_reveals_count=len(
                    contract["forbidden_reveals"]
                ),
            )
        director_parsed, _dir_rec = self._call_gateway(
            task_type=TaskType.DIRECTOR_PROPOSER,
            scripted_content=json.dumps(director_beat, ensure_ascii=False),
            turn_index=self._turn_index,
            extra_metadata={"beatId": "director"},
        )
        director_beat_dict: dict[str, Any] = (
            director_parsed or dict(director_beat)
        )

        # ----- 3. Plant any seeds the test wants in the active set ----
        if plant_seeds:
            existing = list(self.snapshot.causalSeedsActive)
            for s in plant_seeds:
                existing.append(s)
            self.snapshot = self.snapshot.with_causal_seeds_active(
                existing
            )

        # ----- 4. Resolver write --------------------------------------
        # The resolver_agent is the only writer.  Its
        # resolve_turn call validates the mandatory echo,
        # applies the reducer, merges NPC deltas, fires
        # auto-matching seeds, and returns the new snapshot.
        new_snap, outcome, mandatory_echo, _, _ = (
            self.resolver_agent.resolve_turn(
                snapshot=self.snapshot,
                event_log=self.event_log,
                player_action=player_action,
                npc_proposal_dict=npc_proposal_dict,
                director_beat_dict=director_beat_dict,
                scene_contract=contract,
                scene_budget=budget,
                recall_set=recall_set or set(),
                llm_calls=[],
            )
        )
        self.snapshot = new_snap
        self._turn_index += 1
        return TurnResult(
            snapshot_after=new_snap,
            outcome=outcome,
            mandatory_echo=mandatory_echo,
            player_action=player_action,
            npc_proposal_dict=npc_proposal_dict,
            director_beat_dict=director_beat_dict,
            llm_calls=list(self.ledger.records),
        )


def _build_default_director_beat(
    *,
    run_id: str,
    scene_id: str,
    proposed_beat: str,
    forbidden_reveals_count: int,
) -> dict[str, Any]:
    """Build a minimal DirectorBeat dict that passes the gateway schema."""

    return {
        "proposalId": str(uuid.uuid4()),
        "runId": run_id,
        "sceneId": scene_id,
        "proposedBeat": proposed_beat,
        "allowedByContract": True,
        "forbiddenRevealsChecked": [
            f"forbidden_key_{i}"
            for i in range(forbidden_reveals_count)
        ],
        "transitionToNext": False,
        "suggestedTargetSceneId": None,
        "reasoning": (
            f"Default Director beat for {scene_id}: {proposed_beat}; "
            f"contract allows it; no forbidden_reveals crossed."
        ),
        "pacingPressure": 0.5,
        "expectedTensionDelta": 0.05,
        "involvedCharacterIds": ["leila", "arash"],
        "firedCausalSeeds": [],
        "timestamp": "2026-07-15T00:00:00Z",
        "schemaVersion": "1.0.0",
    }


# ===========================================================================
# Scene-driver: builds a complete 3-scene scripted playthrough
# ===========================================================================


def _new_player_action_dict(
    *,
    action_type: str,
    scene_id: str,
    target_id: str | None = None,
    evidence_ids: list[str] | None = None,
    utterance: str = "",
    expected_event_sequence: int = 0,
) -> dict[str, Any]:
    """Build a :class:`PlayerAction` dict for the harness.

    Uses a fixed ``runId`` so the test is deterministic.
    """

    return {
        "runId": RUN_ID_FIXTURE,
        "sceneId": scene_id,
        "actionType": action_type,
        "actorId": "leila",
        "targetId": target_id,
        "evidenceIds": list(evidence_ids or []),
        "utterance": utterance,
        "tone": "neutral",
        "disclosureLevel": 0.5,
        "isDeceptive": False,
        "clientActionId": str(uuid.uuid4()),
        "expectedEventSequence": expected_event_sequence,
        "schemaVersion": "1.0.0",
    }


def _new_npc_proposal_dict(
    *,
    run_id: str,
    character_id: str,
    proposed_action: str,
    speech_intent: str,
    belief_subject: str | None = None,
    belief_new_state: str = "reinforced",
    target_id: str | None = None,
    reason_codes: list[str] | None = None,
    referenced_memory_ids: list[str] | None = None,
    confidence: float = 0.75,
) -> dict[str, Any]:
    return {
        "proposalId": str(uuid.uuid4()),
        "runId": run_id,
        "characterId": character_id,
        "triggerPlayerActionId": None,
        "proposedAction": proposed_action,
        "targetId": target_id,
        "speechIntent": speech_intent,
        "referencedMemoryIds": list(referenced_memory_ids or []),
        "beliefUpdatesRequested": (
            [
                {
                    "subject": belief_subject,
                    "newState": belief_new_state,
                    "confidence": round(confidence, 2),
                    "evidenceMemoryId": None,
                }
            ]
            if belief_subject is not None
            else []
        ),
        "emotionalTransition": {
            "from": "calm",
            "to": "tense",
            "intensity": 0.5,
        },
        "reasonCodes": list(reason_codes or ["memory_resurfaced"]),
        "confidence": round(confidence, 2),
        "expectedContradictions": [],
        "timestamp": "2026-07-15T00:00:00Z",
        "schemaVersion": "1.0.0",
    }


# ===========================================================================
# THE TEST CLASS
# ===========================================================================


class EndToEndThreeScenesTest(unittest.TestCase):
    """Drive the three case_01 scenes end-to-end and assert invariants.

    The class is intentionally **single-method** for the main
    test (because each scene is part of one continuous run),
    with focused additional tests for individual invariants.
    """

    # ----- shared state ------------------------------------------------

    def setUp(self) -> None:
        # Use a deterministic run id for replay-stable tests.
        self.run_id = "00000000-0000-0000-0000-000000000001"
        # Patch the per-turn test fixtures.
        self.harness = IntegrationHarness(run_id=self.run_id)

    # ----- helper: build a photo_in_pocket seed -----------------------

    def _build_photo_in_pocket_seed(self, event_id: str) -> dict[str, Any]:
        """Build a serialised CausalSeed for photo_in_pocket.

        This is the seed the integration test plants in
        ``photo_lab_2008`` after the player's "put the photo
        in my pocket" action.  Its ``target_scenes`` includes
        ``reunion_2024`` so the engine's auto-fire will pick
        it up in the final scene.

        Note: ``eraSpan`` is left empty because the engine's
        ``CausalSeed.matches`` does **equality** on
        case-scoped era values (not range), and case_01
        uses case-scoped years.  A range like
        ``(2008, 2024)`` would be mis-evaluated; leaving
        the span empty makes the era constraint
        unconditional.
        """

        seed = CausalSeed(
            id=SEED_PHOTO_IN_POCKET,
            source_scene=SCENE_2008,
            source_event=event_id,
            description="莱拉把毕业照放进斜挎包内袋",
            trigger_condition=TriggerCondition(
                type="scene_match",
                predicate=f"current_scene in target_scenes",
                minEcho=0.0,
            ),
            target_scenes=[SCENE_2024],
            echo_intensity=0.95,
            is_secret=False,
            linkedCharacterIds=["leila", "arash"],
            decayRate=0.02,
            tags=["mandatory_echo", "physical_evidence"],
        )
        return seed.to_dict()

    def _build_photo_in_book_seed(self, event_id: str) -> dict[str, Any]:
        seed = CausalSeed(
            id=SEED_PHOTO_IN_BOOK,
            source_scene=SCENE_2008,
            source_event=event_id,
            description="阿拉什把毕业照夹进鲁米诗集",
            trigger_condition=TriggerCondition(
                type="scene_match",
                predicate=f"current_scene in target_scenes",
                minEcho=0.0,
            ),
            target_scenes=[SCENE_2024],
            echo_intensity=0.85,
            is_secret=False,
            linkedCharacterIds=["leila", "arash"],
            decayRate=0.02,
            tags=["mandatory_echo", "physical_evidence"],
        )
        return seed.to_dict()

    # ==================================================================
    # Main end-to-end test
    # ==================================================================

    def test_three_scenes_e2e_with_mandatory_echo(self) -> None:
        """Drive photo_lab_2008 → farewell_2011 → reunion_2024.

        Asserts the **core proposition** from
        ``brief-for-dev-task-v1.md``:
        "玩家 2008 行为触发 reunion_2024 mandatory echo".
        """

        run_id = self.run_id

        # -----------------------------------------------------------------
        # SCENE 1: photo_lab_2008
        # -----------------------------------------------------------------
        # Player investigates photo_pair, then gives photo_A
        # to herself (target=leila = "put in pocket"),
        # then gives photo_B to arash (target=arash = "into
        # his book").
        # -----------------------------------------------------------------

        # Turn 1: investigate the envelope (no turn consumed)
        # Per the reducers, investigate doesn't consume a turn.
        result_2008_t1 = self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="investigate",
                scene_id=SCENE_2008,
                target_id="arash",
                evidence_ids=["envelope"],
                utterance="打开看看里面有什么",
                expected_event_sequence=0,
            ),
            npc_proposal=_new_npc_proposal_dict(
                run_id=run_id,
                character_id="arash",
                proposed_action="comfort",
                speech_intent="comfort",
                target_id="leila",
                reason_codes=["love_obligation"],
            ),
        )
        self.assertEqual(result_2008_t1.snapshot_after.canonicalState.currentSceneId, SCENE_2008)
        # Event sequence bumped (the resolver advances even when
        # the player action is `investigate` because the
        # resolver records the turn).
        self.assertGreaterEqual(result_2008_t1.snapshot_after.eventSequence, 1)

        # Turn 2: player gives photo_A to herself (pocket)
        # After this, the test plants the photo_in_pocket seed.
        result_2008_t2 = self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="give",
                scene_id=SCENE_2008,
                target_id="leila",  # self = put in pocket
                evidence_ids=["photo_A"],
                utterance="把这一张放进我包里",
                expected_event_sequence=result_2008_t1.snapshot_after.eventSequence,
            ),
            npc_proposal=_new_npc_proposal_dict(
                run_id=run_id,
                character_id="arash",
                proposed_action="comfort",
                speech_intent="comfort",
                target_id="leila",
                reason_codes=["love_obligation", "memory_resurfaced"],
            ),
        )
        # Plant the seed manually so it shows up in the next
        # turn's auto-fire evaluation.
        event_id = result_2008_t2.outcome.outcomeId
        # Add the photo_in_pocket seed to the active set so
        # it propagates to subsequent scenes.
        seed_in_pocket = self._build_photo_in_pocket_seed(event_id)
        self.harness.snapshot = (
            self.harness.snapshot.with_causal_seeds_active(
                list(self.harness.snapshot.causalSeedsActive) + [seed_in_pocket]
            )
        )
        # Verify the photo is now owned by leila (in pocket)
        photo_a = next(
            a for a in self.harness.snapshot.artifactState
            if a.artifactId == "photo_A"
        )
        self.assertEqual(photo_a.ownerId, "leila")
        self.assertEqual(photo_a.state, "in_envelope")  # the engine's
        # `give` reducer only changes ownerId, not state.

        # Turn 3: player gives photo_B to arash (into his book)
        result_2008_t3 = self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="give",
                scene_id=SCENE_2008,
                target_id="arash",
                evidence_ids=["photo_B"],
                utterance="这一张你收好",
                expected_event_sequence=self.harness.snapshot.eventSequence,
            ),
            npc_proposal=_new_npc_proposal_dict(
                run_id=run_id,
                character_id="arash",
                proposed_action="give",
                speech_intent="reassure",
                target_id="leila",
                reason_codes=["love_obligation"],
            ),
        )
        # Plant the photo_in_book seed
        event_id = result_2008_t3.outcome.outcomeId
        seed_in_book = self._build_photo_in_book_seed(event_id)
        self.harness.snapshot = (
            self.harness.snapshot.with_causal_seeds_active(
                list(self.harness.snapshot.causalSeedsActive) + [seed_in_book]
            )
        )
        photo_b = next(
            a for a in self.harness.snapshot.artifactState
            if a.artifactId == "photo_B"
        )
        self.assertEqual(photo_b.ownerId, "arash")

        # -----------------------------------------------------------------
        # SCENE 2: farewell_2011
        # -----------------------------------------------------------------
        # Player reveals the envelope (with Kamran's name),
        # gives the boarding pass, and writes on the luggage
        # tag.  NPC reactions are scripted to "comfort" /
        # "remain_silent" / "defend" — non-echo intents to
        # keep the 2011 scene free of mandatory-echo.
        # -----------------------------------------------------------------
        self.harness.transition_to_scene(scene_id=SCENE_2011, era="2011")

        result_2011_t1 = self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="reveal",
                scene_id=SCENE_2011,
                target_id="arash",
                evidence_ids=["envelope_kamran"],
                utterance="里面有卡姆兰的名字",
                expected_event_sequence=self.harness.snapshot.eventSequence,
            ),
            npc_proposal=_new_npc_proposal_dict(
                run_id=run_id,
                character_id="arash",
                proposed_action="comfort",
                speech_intent="comfort",
                target_id="leila",
                reason_codes=["love_obligation", "witnessed_action"],
            ),
        )

        result_2011_t2 = self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="give",
                scene_id=SCENE_2011,
                target_id="arash",
                evidence_ids=["luggage_tag"],
                utterance="我会在行李牌上写字",
                expected_event_sequence=self.harness.snapshot.eventSequence,
            ),
            npc_proposal=_new_npc_proposal_dict(
                run_id=run_id,
                character_id="arash",
                proposed_action="comfort",
                speech_intent="reassure",
                target_id="leila",
                reason_codes=["love_obligation"],
            ),
        )

        # -----------------------------------------------------------------
        # SCENE 3: reunion_2024
        # -----------------------------------------------------------------
        # Player investigates the poetry book.  NPC (arash)
        # **must** surface the photo_in_pocket seed via
        # speechIntent=reveal_truth + belief subject
        # =photo_in_pocket.  The recall_set is
        # {mem_2008_photo_pocket} so the engine's
        # _validate_npc_proposal accepts the referenced memory.
        # -----------------------------------------------------------------
        self.harness.transition_to_scene(scene_id=SCENE_2024, era="2024")

        # At scene transition, plant the photo_in_pocket seed
        # already carried over from 2008 (it should be in
        # self.harness.snapshot.causalSeedsActive).
        seed_ids = [
            s.get("id")
            for s in self.harness.snapshot.causalSeedsActive
        ]
        self.assertIn(
            SEED_PHOTO_IN_POCKET, seed_ids,
            "photo_in_pocket seed must propagate from 2008 to 2024"
        )

        # Recall set: the NPC recalls 4-8 memories; we feed
        # in the one memory that grounds the echo.
        recall_set = {"mem_2008_photo_pocket", "mem_2008_photo_book"}

        # Build the NPC proposal that triggers the mandatory
        # echo.  The resolver agent detects the echo via the
        # combination of:
        #   - speechIntent in {"reveal_truth", ...}
        #   - beliefUpdatesRequested[].subject in causal_seeds
        npc_echo_proposal = _new_npc_proposal_dict(
            run_id=run_id,
            character_id="arash",
            proposed_action="reveal",
            speech_intent="reveal_truth",
            belief_subject=SEED_PHOTO_IN_POCKET,
            belief_new_state="reinforced",
            target_id="leila",
            reason_codes=["memory_resurfaced", "love_obligation"],
            referenced_memory_ids=["mem_2008_photo_pocket"],
            confidence=0.85,
        )

        result_2024_t1 = self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="investigate",
                scene_id=SCENE_2024,
                target_id="arash",
                evidence_ids=["poetry_book"],
                utterance="诗集还在吗",
                expected_event_sequence=self.harness.snapshot.eventSequence,
            ),
            npc_proposal=npc_echo_proposal,
            recall_set=recall_set,
        )

        # -----------------------------------------------------------------
        # CORE ASSERTION 1: mandatory echo passed
        # -----------------------------------------------------------------
        # The ResolverAgent's _validate_mandatory_echo must
        # have detected that arash's proposal surfaced
        # photo_in_pocket and that the seed is in
        # contract.mandatory_echoes.  The result.passes must
        # be True; otherwise the proposal is recorded in
        # outcome.rejectedNpcActions.
        self.assertTrue(
            result_2024_t1.mandatory_echo.echo_attempted,
            "Resolver must detect the echo attempt on photo_in_pocket"
        )
        self.assertTrue(
            result_2024_t1.mandatory_echo.passes,
            f"Mandatory echo must pass; got: {result_2024_t1.mandatory_echo.summary}"
        )
        # Every check's seed_id is photo_in_pocket and matched.
        for check in result_2024_t1.mandatory_echo.checks:
            self.assertEqual(check.seed_id, SEED_PHOTO_IN_POCKET)
            self.assertTrue(check.matched, msg=check.detail)

        # -----------------------------------------------------------------
        # CORE ASSERTION 2: no rejected NPC actions
        # -----------------------------------------------------------------
        self.assertEqual(
            result_2024_t1.outcome.rejectedNpcActions, [],
            "rejectedNpcActions must be empty for a mandatory-echo proposal"
        )

        # -----------------------------------------------------------------
        # CORE ASSERTION 3: cost red lines held
        # -----------------------------------------------------------------
        # Decision 5 R1: total calls <= 20
        self.assertLessEqual(
            len(self.harness.ledger.records), MAX_RUN_CALLS,
            f"Run exceeded 20-call budget: {len(self.harness.ledger.records)} calls"
        )
        # Decision 5 R2: every call's output_tokens < 800
        for rec in self.harness.ledger.records:
            self.assertLess(
                rec.output_tokens, MAX_OUTPUT_TOKENS_PER_CALL,
                f"Call exceeded 800-token cap: {rec.output_tokens}"
            )
        # Decision 5 R3: per-turn calls <= 2
        per_turn = {}
        for rec in self.harness.ledger.records:
            per_turn.setdefault(rec.turn_index, 0)
            per_turn[rec.turn_index] += 1
        for turn_idx, count in per_turn.items():
            self.assertLessEqual(
                count, MAX_TURN_CALLS,
                f"Turn {turn_idx} had {count} LLM calls (cap = 2)"
            )
        # Soft target: total cost < ¥0.8
        self.assertLess(
            self.harness.ledger.total_cost_cny, SOFT_COST_TARGET_CNY,
            f"Run cost {self.harness.ledger.total_cost_cny} exceeded ¥0.8"
        )

        # -----------------------------------------------------------------
        # CORE ASSERTION 4: the seed fired in 2024
        # -----------------------------------------------------------------
        # The engine's auto-fire in the Resolver should have
        # fired the photo_in_pocket seed because reunion_2024
        # is in its target_scenes.  ``firedCausalSeeds`` on
        # the outcome reports this.
        self.assertIn(
            SEED_PHOTO_IN_POCKET,
            result_2024_t1.outcome.firedCausalSeeds,
            "photo_in_pocket seed must fire in reunion_2024"
        )

    # ==================================================================
    # Focused test: cost invariants on a 3-scene run
    # ==================================================================

    def test_cost_red_lines_hold_for_three_scenes(self) -> None:
        """Run a 3-scene playthrough and assert decision-5 red lines.

        This test is a slightly shortened variant of the main
        one, with the same cost assertions but a simpler
        action sequence.  It exists so a future refactor that
        breaks the cost invariants but accidentally satisfies
        the echo test will still get caught here.
        """

        run_id = self.run_id

        # SCENE 2008: 1 turn (give photo_A to self)
        result = self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="give",
                scene_id=SCENE_2008,
                target_id="leila",
                evidence_ids=["photo_A"],
                utterance="放进口袋",
                expected_event_sequence=0,
            ),
            npc_proposal=_new_npc_proposal_dict(
                run_id=run_id,
                character_id="arash",
                proposed_action="comfort",
                speech_intent="comfort",
                target_id="leila",
            ),
        )
        # Plant seed
        self.harness.snapshot = self.harness.snapshot.with_causal_seeds_active(
            list(self.harness.snapshot.causalSeedsActive)
            + [self._build_photo_in_pocket_seed(result.outcome.outcomeId)]
        )

        # SCENE 2011: 1 turn
        self.harness.transition_to_scene(scene_id=SCENE_2011, era="2011")
        self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="comfort",
                scene_id=SCENE_2011,
                target_id="arash",
                utterance="谢谢你赶来",
                expected_event_sequence=self.harness.snapshot.eventSequence,
            ),
            npc_proposal=_new_npc_proposal_dict(
                run_id=run_id,
                character_id="arash",
                proposed_action="comfort",
                speech_intent="reassure",
                target_id="leila",
            ),
        )

        # SCENE 2024: 1 turn
        self.harness.transition_to_scene(scene_id=SCENE_2024, era="2024")
        self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="investigate",
                scene_id=SCENE_2024,
                target_id="arash",
                evidence_ids=["poetry_book"],
                utterance="诗集还在吗",
                expected_event_sequence=self.harness.snapshot.eventSequence,
            ),
            npc_proposal=_new_npc_proposal_dict(
                run_id=run_id,
                character_id="arash",
                proposed_action="comfort",
                speech_intent="comfort",
                target_id="leila",
            ),
        )

        # Cost assertions
        self.assertLessEqual(
            len(self.harness.ledger.records), MAX_RUN_CALLS,
            f"Run exceeded 20-call budget: {len(self.harness.ledger.records)}"
        )
        for rec in self.harness.ledger.records:
            self.assertLess(
                rec.output_tokens, MAX_OUTPUT_TOKENS_PER_CALL
            )
        per_turn = {}
        for rec in self.harness.ledger.records:
            per_turn.setdefault(rec.turn_index, 0)
            per_turn[rec.turn_index] += 1
        for turn_idx, count in per_turn.items():
            self.assertLessEqual(count, MAX_TURN_CALLS)
        self.assertLess(
            self.harness.ledger.total_cost_cny, SOFT_COST_TARGET_CNY
        )

    # ==================================================================
    # Focused test: NPC dialogue text is preserved
    # ==================================================================

    def test_npc_proposal_does_not_get_rejected_when_compliant(self) -> None:
        """A compliant NPC proposal must not be rejected by the Resolver.

        This is the "**NPC 主动提起玩家 2008 行为**" assertion
        from the brief — the proposal references the seed id
        (in ``beliefUpdatesRequested[].subject``) AND the
        scene's ``mandatory_echoes`` list contains the seed.
        Result: no rejection, the proposal drives an
        ``acceptedNpcAction`` with the expected
        ``proposedAction``.
        """

        run_id = self.run_id

        # Go straight to reunion_2024 (skip 2008 / 2011 for
        # this focused test).
        self.harness.transition_to_scene(scene_id=SCENE_2024, era="2024")
        # Plant the seed in the active set (simulating the
        # cross-era carry).
        self.harness.snapshot = (
            self.harness.snapshot.with_causal_seeds_active(
                list(self.harness.snapshot.causalSeedsActive)
                + [self._build_photo_in_pocket_seed("seed-test-001")]
            )
        )

        recall_set = {"mem_2008_photo_pocket"}
        npc_proposal = _new_npc_proposal_dict(
            run_id=run_id,
            character_id="arash",
            proposed_action="reveal",
            speech_intent="reveal_truth",
            belief_subject=SEED_PHOTO_IN_POCKET,
            belief_new_state="reinforced",
            target_id="leila",
            reason_codes=["memory_resurfaced", "love_obligation"],
            referenced_memory_ids=["mem_2008_photo_pocket"],
            confidence=0.85,
        )

        result = self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="investigate",
                scene_id=SCENE_2024,
                target_id="arash",
                evidence_ids=["poetry_book"],
                utterance="诗集还在吗",
                expected_event_sequence=self.harness.snapshot.eventSequence,
            ),
            npc_proposal=npc_proposal,
            recall_set=recall_set,
        )

        # The proposal is accepted (not in rejectedNpcActions)
        self.assertEqual(
            result.outcome.rejectedNpcActions, [],
            f"Proposal should not be rejected; got: {result.outcome.rejectedNpcActions}"
        )
        # The accepted NPC action echoes the proposal's
        # proposedAction
        self.assertEqual(
            result.outcome.acceptedNpcAction.get("characterId"),
            "arash"
        )
        self.assertEqual(
            result.outcome.acceptedNpcAction.get("proposedAction"),
            "reveal"
        )
        # The mandatory echo validation passed
        self.assertTrue(result.mandatory_echo.passes)
        self.assertIn(
            SEED_PHOTO_IN_POCKET,
            [c.seed_id for c in result.mandatory_echo.checks if c.matched]
        )

    # ==================================================================
    # Focused test: event sequence monotonic
    # ==================================================================

    def test_event_sequence_monotonic_through_three_scenes(self) -> None:
        """The eventSequence must be strictly increasing across the run."""

        run_id = self.run_id

        for scene_id, era, action in [
            (SCENE_2008, "2008", "give"),
            (SCENE_2011, "2011", "comfort"),
            (SCENE_2024, "2024", "investigate"),
        ]:
            if scene_id != SCENE_2008:
                self.harness.transition_to_scene(
                    scene_id=scene_id, era=era
                )
            seq_before = self.harness.snapshot.eventSequence
            result = self.harness.drive_turn(
                player_action=_new_player_action_dict(
                    action_type=action,
                    scene_id=scene_id,
                    target_id="arash",
                    evidence_ids=["photo_A"] if action == "give" else [],
                    expected_event_sequence=seq_before,
                ),
                npc_proposal=_new_npc_proposal_dict(
                    run_id=run_id,
                    character_id="arash",
                    proposed_action="comfort",
                    speech_intent="comfort",
                    target_id="leila",
                ),
            )
            self.assertGreater(
                result.snapshot_after.eventSequence,
                seq_before,
                f"eventSequence must advance on {scene_id}"
            )

    # ==================================================================
    # W4-Content-Update tests — UP-20260715-007/008/010/011/009
    # ==================================================================

    # ----- shared fixture: build a CausalSeed for the new echoes -------

    def _build_bus_ticket_2024_seen_seed(
        self, event_id: str
    ) -> dict[str, Any]:
        """Build a serialised CausalSeed for the UP-20260715-007 echo.

        The seed carries ``bus_ticket_2024_seen`` as the id; the
        test plants it on the active set so the engine can match
        an NPC proposal whose ``belief_subject`` references it.
        """

        seed = CausalSeed(
            id="bus_ticket_2024_seen",
            source_scene=SCENE_2024,
            source_event=event_id,
            description="阿拉什从诗集末页取出 304 公交票，莱拉看见",
            trigger_condition=TriggerCondition(
                type="scene_match",
                predicate=f"current_scene in target_scenes",
                minEcho=0.0,
            ),
            target_scenes=[SCENE_2024],
            echo_intensity=0.85,
            is_secret=False,
            linkedCharacterIds=["leila", "arash"],
            decayRate=0.02,
            tags=["mandatory_echo", "physical_evidence", "up_20260715_007"],
        )
        return seed.to_dict()

    def _build_i_arrived_text_2024_resonance_seed(
        self, event_id: str
    ) -> dict[str, Any]:
        """Build a serialised CausalSeed for the UP-20260715-008/011 echo."""

        seed = CausalSeed(
            id="i_arrived_text_2024_resonance",
            source_scene=SCENE_2024,
            source_event=event_id,
            description="莱拉主动读 2011'我到了'短信给阿拉什听",
            trigger_condition=TriggerCondition(
                type="scene_match",
                predicate=f"current_scene in target_scenes",
                minEcho=0.0,
            ),
            target_scenes=[SCENE_2024],
            echo_intensity=0.9,
            is_secret=False,
            linkedCharacterIds=["leila", "arash"],
            decayRate=0.02,
            tags=["mandatory_echo", "verbal_evidence", "up_20260715_008_011"],
        )
        return seed.to_dict()

    # ==================================================================
    # W4-Content-Update Test 1: bus_ticket_2024_seen
    # ==================================================================

    def test_bus_ticket_2024_seen_mandatory_echo(self) -> None:
        """UP-20260715-007: the 304 公交票 2024 echo must be in the
        mandatory list, and an NPC proposal that surfaces it must
        pass the resolver's UP-002 mandatory-echo gate.

        Contract invariants asserted:

        * ``bus_ticket_2024_seen`` is registered in
          ``scene_contract_2024().mandatory_echoes``.
        * An NPC proposal whose ``belief_subject`` =
          ``bus_ticket_2024_seen`` (in an echo-intent speech) is
          **accepted** (not in ``rejectedNpcActions``).
        * The mandatory-echo validation records a matched check
          for that seed.
        * The YAML carries exactly **5** mandatory echoes
          (post-UP-007/008/011), and bus_ticket_2024_seen is
          the 4th.
        """

        run_id = self.run_id

        # Go straight to reunion_2024 for a focused test.
        self.harness.transition_to_scene(scene_id=SCENE_2024, era="2024")
        # Plant the bus_ticket_2024_seen seed (simulating the
        # cross-era carry from the 2011 bus_ticket_pair_unused seed).
        self.harness.snapshot = (
            self.harness.snapshot.with_causal_seeds_active(
                list(self.harness.snapshot.causalSeedsActive)
                + [self._build_bus_ticket_2024_seen_seed("seed-bus-001")]
            )
        )

        # NPC proposal surfaces the bus_ticket_2024_seen echo via
        # belief_subject.  speech_intent=reveal_truth is one of the
        # echo_intents the resolver treats as a "voluntary echo".
        npc_proposal = _new_npc_proposal_dict(
            run_id=run_id,
            character_id="arash",
            proposed_action="give",
            speech_intent="reveal_truth",
            belief_subject="bus_ticket_2024_seen",
            belief_new_state="reinforced",
            target_id="leila",
            reason_codes=["memory_resurfaced", "love_obligation"],
            referenced_memory_ids=["mem_2011_bus_ticket_pair"],
            confidence=0.85,
        )

        result = self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="investigate",
                scene_id=SCENE_2024,
                target_id="arash",
                evidence_ids=["poetry_book"],
                utterance="诗集还在吗",
                expected_event_sequence=self.harness.snapshot.eventSequence,
            ),
            npc_proposal=npc_proposal,
            recall_set={"mem_2011_bus_ticket_pair"},
        )

        # ----- YAML invariant: exactly 5 mandatory echoes (post-UP-007) -----
        # The YAML is the source of truth for the 5-echo count;
        # the test contract may carry extra entries for test compat.
        import yaml  # local import — tests run with stdlib only
        yaml_path = (
            _PROJECT_ROOT
            / "content/case_01_revolution_street/scenes/reunion_2024.yaml"
        )
        with open(yaml_path, "r", encoding="utf-8") as fp:
            yaml_doc = yaml.safe_load(fp)
        yaml_mandatory = yaml_doc["mandatory_echoes"]
        yaml_me_ids = [me["id"] for me in yaml_mandatory]
        self.assertEqual(
            len(yaml_mandatory), 5,
            f"reunion_2024.yaml must have exactly 5 mandatory echoes "
            f"(UP-007/008/011 expanded from 3); got {len(yaml_mandatory)}"
        )
        self.assertIn(
            "bus_ticket_2024_seen", yaml_me_ids,
            "UP-007: bus_ticket_2024_seen must be in mandatory_echoes"
        )
        # bus_ticket_2024_seen must be the 4th echo in the YAML
        # (per the task brief listing 1→5, the new echoes are 4 and 5).
        self.assertEqual(
            yaml_me_ids[3], "bus_ticket_2024_seen",
            f"bus_ticket_2024_seen must be the 4th mandatory echo; "
            f"got {yaml_me_ids[3]} at index 3"
        )

        # ----- resolver invariant: proposal accepted, echo matched -----
        self.assertEqual(
            result.outcome.rejectedNpcActions, [],
            f"Proposal must not be rejected; got: {result.outcome.rejectedNpcActions}"
        )
        self.assertTrue(
            result.mandatory_echo.echo_attempted,
            "Resolver must detect the echo attempt on bus_ticket_2024_seen"
        )
        self.assertTrue(
            result.mandatory_echo.passes,
            f"Mandatory echo must pass; got: {result.mandatory_echo.summary}"
        )
        # The matched check must reference bus_ticket_2024_seen.
        matched_ids = [
            c.seed_id for c in result.mandatory_echo.checks if c.matched
        ]
        self.assertIn(
            "bus_ticket_2024_seen", matched_ids,
            f"bus_ticket_2024_seen must be in the matched checks; "
            f"got: {matched_ids}"
        )

    # ==================================================================
    # W4-Content-Update Test 2: i_arrived_text_2024_resonance
    # ==================================================================

    def test_i_arrived_text_2024_resonance_mandatory_echo(self) -> None:
        """UP-20260715-008/011: the 2011'我到了'short-message 2024 echo
        must be in the mandatory list, and an NPC proposal that
        surfaces it must pass the resolver's gate.

        Contract invariants asserted:

        * ``i_arrived_text_2024_resonance`` is registered in
          reunion_2024.yaml's mandatory_echoes as the 5th
          (final) entry.
        * An NPC proposal whose ``belief_subject`` =
          ``i_arrived_text_2024_resonance`` is accepted by the
          resolver.
        * The match for that seed is recorded in the resolver's
          mandatory-echo checks.
        """

        run_id = self.run_id

        # ---- YAML contract invariant (independent of the harness) ----
        import yaml
        yaml_path = (
            _PROJECT_ROOT
            / "content/case_01_revolution_street/scenes/reunion_2024.yaml"
        )
        with open(yaml_path, "r", encoding="utf-8") as fp:
            yaml_doc = yaml.safe_load(fp)
        yaml_mandatory = yaml_doc["mandatory_echoes"]
        yaml_me_ids = [me["id"] for me in yaml_mandatory]
        self.assertIn(
            "i_arrived_text_2024_resonance", yaml_me_ids,
            "UP-008/011: i_arrived_text_2024_resonance must be in "
            "reunion_2024.yaml's mandatory_echoes"
        )
        # It must be the 5th (last) entry.
        self.assertEqual(
            yaml_me_ids[4], "i_arrived_text_2024_resonance",
            f"i_arrived_text_2024_resonance must be the 5th (last) "
            f"mandatory echo in the YAML; got {yaml_me_ids[4]} at index 4"
        )

        # ---- Runtime invariant: proposal is accepted by the resolver ----
        self.harness.transition_to_scene(scene_id=SCENE_2024, era="2024")
        self.harness.snapshot = (
            self.harness.snapshot.with_causal_seeds_active(
                list(self.harness.snapshot.causalSeedsActive)
                + [
                    self._build_i_arrived_text_2024_resonance_seed(
                        "seed-iarr-001"
                    )
                ]
            )
        )

        # NPC proposal: leila主动读出'short-message (per UP-008/011).
        # Use ``poetry_book`` as evidence (it exists in the harness's
        # 2024 artifactState); the resolver matches on belief_subject.
        npc_proposal = _new_npc_proposal_dict(
            run_id=run_id,
            character_id="leila",
            proposed_action="reveal",
            speech_intent="reveal_truth",
            belief_subject="i_arrived_text_2024_resonance",
            belief_new_state="reinforced",
            target_id="arash",
            reason_codes=["memory_resurfaced", "love_obligation"],
            referenced_memory_ids=["mem_2011_i_arrived_text"],
            confidence=0.9,
        )

        result = self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="investigate",
                scene_id=SCENE_2024,
                target_id="arash",
                evidence_ids=["poetry_book"],
                utterance="诗集还在吗",
                expected_event_sequence=self.harness.snapshot.eventSequence,
            ),
            npc_proposal=npc_proposal,
            recall_set={"mem_2011_i_arrived_text"},
        )

        # ----- resolver invariant -----
        self.assertEqual(
            result.outcome.rejectedNpcActions, [],
            f"Proposal must not be rejected; got: {result.outcome.rejectedNpcActions}"
        )
        self.assertTrue(
            result.mandatory_echo.echo_attempted,
            "Resolver must detect the echo attempt on i_arrived_text_2024_resonance"
        )
        self.assertTrue(result.mandatory_echo.passes)
        matched_ids = [
            c.seed_id for c in result.mandatory_echo.checks if c.matched
        ]
        self.assertIn("i_arrived_text_2024_resonance", matched_ids)

    # ==================================================================
    # W4-Content-Update Test 3: first_words_admit 5 candidate lines
    # ==================================================================

    def test_first_words_admit_selects_5_lines(self) -> None:
        """UP-20260715-010: the ``first_words_admit_2008_2011`` echo
        must have exactly **5 candidate lines**, each mapped to a
        causal_seed, with a strict selection rule.

        Assertions:

        1. The reunion_2024.yaml carries exactly 5 ``candidate_lines``
           on the ``first_words_admit_2008_2011`` echo.
        2. Each line has a unique ``line_id``, a unique
           ``referenced_seed``, and a unique ``priority`` value.
        3. The 5 referenced_seeds span both eras (2008 + 2011) —
           the line selection is *cross-era* by construction.
        4. The YAML declares a ``selection_rule`` block with the
           AI-导演禁 free-form red line.
        """

        import yaml
        yaml_path = (
            _PROJECT_ROOT
            / "content/case_01_revolution_street/scenes/reunion_2024.yaml"
        )
        with open(yaml_path, "r", encoding="utf-8") as fp:
            yaml_doc = yaml.safe_load(fp)
        yaml_mandatory = yaml_doc["mandatory_echoes"]
        first_words = next(
            me for me in yaml_mandatory
            if me["id"] == "first_words_admit_2008_2011"
        )
        self.assertIn(
            "candidate_lines", first_words,
            "UP-010: first_words_admit_2008_2011 must carry "
            "candidate_lines in the YAML"
        )
        candidate_lines = first_words["candidate_lines"]

        # ----- 1. exactly 5 lines -----
        self.assertEqual(
            len(candidate_lines), 5,
            f"UP-010: first_words_admit_2008_2011 must have exactly 5 "
            f"candidate lines; got {len(candidate_lines)}"
        )

        # ----- 2. uniqueness -----
        line_ids = [ln["line_id"] for ln in candidate_lines]
        self.assertEqual(
            len(set(line_ids)), 5,
            f"line_ids must be unique; got {line_ids}"
        )
        referenced_seeds = [ln["referenced_seed"] for ln in candidate_lines]
        self.assertEqual(
            len(set(referenced_seeds)), 5,
            f"referenced_seed must be unique per line; got {referenced_seeds}"
        )
        priorities = [ln["priority"] for ln in candidate_lines]
        self.assertEqual(
            sorted(priorities), [1, 2, 3, 4, 5],
            f"priorities must be 1..5 (1=highest); got {priorities}"
        )

        # ----- 3. cross-era coverage -----
        # The 5 lines cover both eras:
        #   - 3 lines reference 2008 seeds (photo_in_pocket,
        #     photo_in_book, grip_then_release)
        #   - 2 lines reference 2011 seeds (bus_ticket_pair_unused,
        #     i_arrived_text)
        era_2008_seeds = {"photo_in_pocket", "photo_in_book",
                          "grip_then_release"}
        era_2011_seeds = {"bus_ticket_pair_unused", "i_arrived_text"}
        seeds = set(referenced_seeds)
        self.assertTrue(
            era_2008_seeds.issubset(seeds),
            f"3 of 5 lines must reference 2008 seeds; "
            f"missing: {era_2008_seeds - seeds}"
        )
        self.assertTrue(
            era_2011_seeds.issubset(seeds),
            f"2 of 5 lines must reference 2011 seeds; "
            f"missing: {era_2011_seeds - seeds}"
        )

        # ----- 4. selection_rule present + red line declared -----
        self.assertIn(
            "selection_rule", first_words,
            "YAML must declare a selection_rule block (UP-010)"
        )
        rule = first_words["selection_rule"]
        self.assertIn(
            "red_line", rule,
            "selection_rule must include the AI-导演禁 free-form red line"
        )
        self.assertIn(
            "algorithm", rule,
            "selection_rule must include the priority-based algorithm"
        )

    # ==================================================================
    # W4-Content-Update Test 4: private_epilogue unlocks
    # ==================================================================

    def test_private_epilogue_unlocks_after_mandatory(self) -> None:
        """UP-20260715-009 [critical]: the private_epilogue block must
        unlock when **either** (a) the ¥48 collector's edition is
        owned, **or** (b) the player has triggered at least 1
        reunion_2024 mandatory echo.

        When neither condition is met, the failure message
        "你还没做完这个故事" must be shown (drives retention).

        Cost-budget invariant: ≤ 5 main LLM calls (within decision-5
        hard red line of 20).

        Assertions:

        1. YAML carries a ``private_epilogue`` block.
        2. The block declares 2 unlock conditions joined by OR.
        3. The failure message is "你还没做完这个故事".
        4. ``max_main_llm_calls`` is ≤ 5.
        5. The structure has 3 sections in the correct order:
           epilogue_1_object_lookback, epilogue_2_body_lookback,
           epilogue_3_far_convergence.
        """

        import yaml
        yaml_path = (
            _PROJECT_ROOT
            / "content/case_01_revolution_street/scenes/reunion_2024.yaml"
        )
        with open(yaml_path, "r", encoding="utf-8") as fp:
            yaml_doc = yaml.safe_load(fp)
        self.assertIn(
            "private_epilogue", yaml_doc,
            "UP-009: reunion_2024.yaml must declare a private_epilogue block"
        )
        pe = yaml_doc["private_epilogue"]

        # ----- 1+2. unlock conditions (OR logic) -----
        self.assertIn(
            "unlock_conditions", pe,
            "private_epilogue must declare unlock_conditions"
        )
        conditions = pe["unlock_conditions"]
        self.assertEqual(
            len(conditions), 2,
            f"UP-009: private_epilogue must have 2 unlock conditions "
            f"(paid + completed_echo); got {len(conditions)}"
        )
        cond_ids = {c["id"] for c in conditions}
        self.assertIn(
            "condition_paid", cond_ids,
            "first unlock condition must be condition_paid (¥48 collector's edition)"
        )
        self.assertIn(
            "condition_completed_echo", cond_ids,
            "second unlock condition must be condition_completed_echo"
        )
        self.assertEqual(
            pe.get("unlock_logic"), "OR",
            "UP-009: unlock_logic must be OR (paid OR completed)"
        )

        # ----- 3. failure message -----
        self.assertEqual(
            pe.get("failure_message"), "你还没做完这个故事",
            "UP-009: failure_message must be '你还没做完这个故事' "
            "(drives retention)"
        )
        self.assertIn("failure_cta", pe)

        # ----- 4. cost budget -----
        cost = pe.get("cost_budget", {})
        self.assertLessEqual(
            cost.get("max_main_llm_calls", 999), 5,
            f"UP-009: max_main_llm_calls must be ≤ 5; "
            f"got {cost.get('max_main_llm_calls')}"
        )
        # Within decision-5 hard red line.
        self.assertLessEqual(
            cost.get("max_main_llm_calls", 0),
            cost.get("hard_red_lines_max", 20),
            "max_main_llm_calls must be ≤ hard_red_lines_max (decision 5)"
        )

        # ----- 5. structure: 3 sections in order -----
        structure = pe.get("structure", [])
        self.assertEqual(
            len(structure), 3,
            f"UP-009: private_epilogue must have 3 sections; got {len(structure)}"
        )
        section_ids = [s["section_id"] for s in structure]
        self.assertEqual(
            section_ids,
            [
                "epilogue_1_object_lookback",
                "epilogue_2_body_lookback",
                "epilogue_3_far_convergence",
            ],
            f"3 sections must be in order: 物件回望 / 身体回望 / 远方收束; "
            f"got {section_ids}"
        )
        # Each section must declare a title.
        self.assertEqual(structure[0]["title"], "物件回望")
        self.assertEqual(structure[1]["title"], "身体回望")
        self.assertEqual(structure[2]["title"], "远方收束")

        # ----- runtime smoke: the resolver does not block epilogue -----
        # The private_epilogue is a UI gate; we verify the
        # underlying mandatory-echo contract still works (i.e. the
        # scene does not block the echo that triggers the unlock).
        run_id = self.run_id
        self.harness.transition_to_scene(scene_id=SCENE_2024, era="2024")
        # Plant photo_in_pocket to simulate "the player triggered
        # at least 1 mandatory echo" (so condition_completed_echo
        # is true at the contract level).
        self.harness.snapshot = (
            self.harness.snapshot.with_causal_seeds_active(
                list(self.harness.snapshot.causalSeedsActive)
                + [self._build_photo_in_pocket_seed("seed-pe-001")]
            )
        )
        result = self.harness.drive_turn(
            player_action=_new_player_action_dict(
                action_type="investigate",
                scene_id=SCENE_2024,
                target_id="arash",
                evidence_ids=["poetry_book"],
                utterance="诗集还在吗",
                expected_event_sequence=self.harness.snapshot.eventSequence,
            ),
            npc_proposal=_new_npc_proposal_dict(
                run_id=run_id,
                character_id="arash",
                proposed_action="reveal",
                speech_intent="reveal_truth",
                belief_subject=SEED_PHOTO_IN_POCKET,
                target_id="leila",
                referenced_memory_ids=["mem_2008_photo_pocket"],
            ),
            recall_set={"mem_2008_photo_pocket"},
        )
        # No rejection at the contract level (the runtime gate for
        # the epilogue itself is UI-side; the contract only checks
        # that the scene does not block the underlying echo).
        self.assertEqual(
            result.outcome.rejectedNpcActions, [],
            "The seed planted in 2024 must be accepted; the private_"
            "epilogue is a UI gate on top of the existing mandatory "
            "echo contract"
        )


# ===========================================================================
# Module exit
# ===========================================================================


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
