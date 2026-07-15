"""Scene contract loader.

Loads the three scene YAMLs from
``content/case_01_revolution_street/scenes/`` and returns
canonical contract dicts that the
:class:`server.agents.resolver.ResolverAgent` can consume.

The loader is the only piece of code that knows about the
on-disk shape of the YAML — everything else (the Resolver,
the AI agents, the FastAPI layer) sees a uniform dict that
matches the fields :class:`server.agents.resolver.ResolverAgent`
reads (per its ``_build_engine_contract`` and
``_validate_mandatory_echo`` methods).

If a YAML is missing or malformed, the loader falls back to
the in-memory default contracts (kept in sync with the
client mock data so the W4 demo works on a fresh checkout
even before the YAMLs are read).
"""

from __future__ import annotations

import json
import logging
import pathlib
from dataclasses import dataclass
from typing import Any

import yaml

logger = logging.getLogger("g1n.scene_loader")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


CASE_SLUG_DEFAULT = "case_01_revolution_street"

SCENES_IN_ORDER: list[str] = [
    "photo_lab_2008",
    "farewell_2011",
    "reunion_2024",
]


# ---------------------------------------------------------------------------
# Case registry (W12)
# ---------------------------------------------------------------------------
#
# V5 命题"内容可规模化"的工程层落地：每案注册一次，所有 case 共用
# 同一套 _normalise_yaml / _default_contract 逻辑。V6 残留命名、6
# 决策硬约束段不动；case_02 与 case_01 复用 100% schema、100% 12
# 行为词汇表、100% mandatory echo 双轨制。
# ---------------------------------------------------------------------------

# 案场对场景 ID 的映射 — case_01 沿用旧行为（2011/2024 推断 target）
# case_02 直接从 YAML 的 target_scenes 字段读（1985/1989/2008 显式给出）
CASE_REGISTRY: dict[str, dict[str, Any]] = {
    "case_01_revolution_street": {
        "display_name": "革命街没有尽头",
        "subtitle": "德黑兰 · 伊斯坦布尔 · 13 年",
        "scenes_in_order": ["photo_lab_2008", "farewell_2011", "reunion_2024"],
        "year_to_scene": {"2011": "farewell_2011", "2024": "reunion_2024"},
        "default_actor_id": "leila",
        "default_ally_id": "arash",
        "fallback_built_in": True,
        "display_order": 1,
    },
    "case_02_moscow_no_fairy_tale": {
        "display_name": "莫斯科没有童话",
        "subtitle": "莫斯科 · 维也纳 · 柏林 · 19 年",
        "scenes_in_order": [
            "1985_meeting",
            "1989_farewell",
            "2008_reunion",
        ],
        "year_to_scene": {
            "1989": "1989_farewell",
            "2008": "2008_reunion",
        },
        "default_actor_id": "natasha_roschina",
        "default_ally_id": "ilya_berman",
        "fallback_built_in": True,
        "display_order": 2,
    },
}


def list_cases() -> list[dict[str, Any]]:
    """Return all registered cases in display order (W12: case selector)."""

    out: list[dict[str, Any]] = []
    for slug, meta in CASE_REGISTRY.items():
        out.append({
            "caseSlug": slug,
            "displayName": meta["display_name"],
            "subtitle": meta["subtitle"],
            "sceneCount": len(meta["scenes_in_order"]),
            "displayOrder": meta.get("display_order", 99),
        })
    out.sort(key=lambda c: c["displayOrder"])
    return out


def get_case_meta(case_slug: str) -> dict[str, Any] | None:
    """Return the registered metadata for ``case_slug`` (or None)."""

    entry = CASE_REGISTRY.get(case_slug)
    if entry is None:
        return None
    return {
        "caseSlug": case_slug,
        "displayName": entry["display_name"],
        "subtitle": entry["subtitle"],
        "scenesInOrder": list(entry["scenes_in_order"]),
        "defaultActorId": entry["default_actor_id"],
        "defaultAllyId": entry["default_ally_id"],
        "displayOrder": entry.get("display_order", 99),
    }


# ---------------------------------------------------------------------------
# Cached contract
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LoadedScene:
    """One scene contract, normalised for the Resolver.

    Attributes
    ----------
    scene_id : str
        E.g. ``"photo_lab_2008"``.
    era : str
        E.g. ``"2008"``.
    title : str
        The display title.
    contract : dict
        The canonical contract dict the Resolver consumes.
    cast : list
        ``[{"characterId": ..., "role": ...}, ...]`` from the
        YAML's ``characters_present`` (or hard-coded fallback).
    turn_budget : dict
        ``{action_type: cap}`` for the scene's
        :class:`engine.state_machine.SceneBudget`.
    investigatable_objects : list
        The objects the player can interact with.
    causal_seeds : list
        The seed list (with target_scenes, decay_rate, etc.).
    """

    scene_id: str
    era: str
    title: str
    contract: dict[str, Any]
    cast: list[dict[str, str]]
    turn_budget: dict[str, int]
    investigatable_objects: list[dict[str, Any]]
    causal_seeds: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sceneId": self.scene_id,
            "era": self.era,
            "title": self.title,
            "contract": self.contract,
            "cast": self.cast,
            "turnBudget": self.turn_budget,
            "investigatableObjects": self.investigatable_objects,
            "causalSeeds": self.causal_seeds,
        }


# ---------------------------------------------------------------------------
# Built-in fallback contracts
# ---------------------------------------------------------------------------
#
# These mirror the integration test's contract dicts (see
# tests/integration/test_end_to_end_three_scenes.py).  The
# server uses them when a YAML is missing or malformed so
# the demo still works on a fresh checkout.
# ---------------------------------------------------------------------------


_DEFAULT_TURN_BUDGET: dict[str, int] = {
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
}


_DEFAULT_2008_FORBIDDEN = [
    "leila_future_marriage", "leila_kamran_video_call",
    "leila_2011_one_way_ticket", "thirteen_years_later_istanbul_reunion",
    "maziya_2009_released", "arash_father_rehab_debt",
    "leila_san_jose_persian_l10n", "maryam_meteor_log",
    "arash_2011_two_old_bus_tickets", "2011_flight_gate_destination",
    "2009_school_publication_disciplinary", "leila_aunt_first_intro_kamran_call",
]
_DEFAULT_2011_FORBIDDEN = [
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
_DEFAULT_2024_FORBIDDEN = [
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


def _default_contract(case_slug: str, scene_id: str) -> LoadedScene:
    """Build a built-in contract for a scene (W12: case-aware).

    Mirrors the integration test fixtures so the demo works
    on a checkout where the YAMLs are still being authored.
    """

    if scene_id == "photo_lab_2008":
        return LoadedScene(
            scene_id="photo_lab_2008",
            era="2008",
            title="革命街地下放映室与两张同版毕业照",
            cast=[
                {"characterId": "leila", "role": "protagonist"},
                {"characterId": "arash", "role": "ally"},
                {"characterId": "dagang", "role": "witness"},
            ],
            turn_budget=dict(_DEFAULT_TURN_BUDGET),
            investigatable_objects=[],
            causal_seeds=[
                {"id": "photo_in_pocket", "source_scene": "photo_lab_2008", "target_scenes": ["reunion_2024"], "echo_intensity": 0.95},
                {"id": "photo_in_book", "source_scene": "photo_lab_2008", "target_scenes": ["reunion_2024"], "echo_intensity": 0.85},
                {"id": "grip_then_release", "source_scene": "photo_lab_2008", "target_scenes": ["farewell_2011", "reunion_2024"], "echo_intensity": 0.7},
            ],
            contract={
                "sceneId": "photo_lab_2008",
                "era": "2008",
                "title": "革命街地下放映室与两张同版毕业照",
                "core_conflict": "是否把两张同版毕业照分别交给两人",
                "allowed_beats": [
                    {"beatId": "beat_setup_0"},
                    {"beatId": "beat_divide_photos"},
                    {"beatId": "beat_handover"},
                    {"beatId": "beat_exit"},
                ],
                "forbidden_reveals": [{"revealKey": k} for k in _DEFAULT_2008_FORBIDDEN],
                "legal_endings": [
                    {"endingId": "shared_secret"},
                    {"endingId": "one_sided_memory"},
                    {"endingId": "misunderstood_gesture"},
                    {"endingId": "emotional_retreat"},
                    {"endingId": "promise_formed"},
                ],
                "causal_seeds": ["photo_in_pocket", "photo_in_book", "grip_then_release"],
                "mandatory_echoes": [
                    {"id": "photo_in_pocket", "target_scenes": ["reunion_2024"], "ai_director_must_invoke": True},
                    {"id": "photo_in_book", "target_scenes": ["reunion_2024"], "ai_director_must_invoke": True},
                ],
                "max_turns": 8,
                "total_action_budget": 32,
                "cast": [
                    {"characterId": "leila", "role": "protagonist"},
                    {"characterId": "arash", "role": "ally"},
                    {"characterId": "dagang", "role": "witness"},
                ],
            },
        )

    if scene_id == "farewell_2011":
        return LoadedScene(
            scene_id="farewell_2011",
            era="2011",
            title="德黑兰国际机场·出发大厅",
            cast=[
                {"characterId": "leila", "role": "protagonist"},
                {"characterId": "arash", "role": "ally"},
            ],
            turn_budget={
                "investigate": 3, "reveal": 2, "conceal": 1, "question": 2,
                "confront": 1, "comfort": 1, "give": 2, "destroy": 1,
                "promise": 1, "wait": 1, "leave": 1, "silence": 2,
            },
            investigatable_objects=[],
            causal_seeds=[
                {"id": "grip_then_release_2011", "source_scene": "farewell_2011", "target_scenes": ["reunion_2024"], "echo_intensity": 0.8},
                {"id": "bus_ticket_pair_unused", "source_scene": "farewell_2011", "target_scenes": ["reunion_2024"], "echo_intensity": 0.6},
            ],
            contract={
                "sceneId": "farewell_2011",
                "era": "2011",
                "title": "德黑兰国际机场·出发大厅",
                "core_conflict": "是否在最后几分钟里把卡姆兰、婚姻、机票三件事一起说完",
                "allowed_beats": [
                    {"beatId": "beat_setup_0"},
                    {"beatId": "beat_goodbye"},
                    {"beatId": "beat_announcement"},
                    {"beatId": "beat_parting"},
                ],
                "forbidden_reveals": [{"revealKey": k} for k in _DEFAULT_2011_FORBIDDEN],
                "legal_endings": [
                    {"endingId": "all_said"},
                    {"endingId": "kept_back"},
                    {"endingId": "tag_with_word"},
                ],
                "causal_seeds": [
                    "photo_in_pocket", "photo_in_book",
                    "grip_then_release_2011", "bus_ticket_pair_unused",
                    "i_arrived_text", "name_of_kamran_spoken",
                ],
                "mandatory_echoes": [
                    {"id": "grip_then_release_2011", "target_scenes": ["reunion_2024"], "ai_director_must_invoke": True},
                    {"id": "bus_ticket_pair_unused", "target_scenes": ["reunion_2024"], "ai_director_must_invoke": True},
                ],
                "max_turns": 8,
                "total_action_budget": 32,
                "cast": [
                    {"characterId": "leila", "role": "protagonist"},
                    {"characterId": "arash", "role": "ally"},
                ],
            },
        )

    if scene_id == "reunion_2024":
        return LoadedScene(
            scene_id="reunion_2024",
            era="2024",
            title="伊斯坦布尔·卡拉柯伊老咖啡馆与路口",
            cast=[
                {"characterId": "leila", "role": "protagonist"},
                {"characterId": "arash", "role": "ally"},
            ],
            turn_budget={
                "investigate": 3, "reveal": 2, "conceal": 1, "question": 2,
                "confront": 1, "comfort": 1, "give": 2, "destroy": 1,
                "promise": 1, "wait": 1, "leave": 1, "silence": 2,
            },
            investigatable_objects=[],
            causal_seeds=[
                {"id": "photos_aligned", "source_scene": "reunion_2024", "target_scenes": ["reunion_2024"], "echo_intensity": 0.99},
                {"id": "i_arrived_re_read", "source_scene": "reunion_2024", "target_scenes": ["reunion_2024"], "echo_intensity": 0.9},
            ],
            contract={
                "sceneId": "reunion_2024",
                "era": "2024",
                "title": "伊斯坦布尔·卡拉柯伊老咖啡馆与路口",
                "core_conflict": "13 年后第一眼落在何处；是否在桌上对齐两张同版照片",
                "allowed_beats": [
                    {"beatId": "beat_setup_0"},
                    {"beatId": "beat_recognition"},
                    {"beatId": "beat_photos"},
                    {"beatId": "beat_crossroads"},
                ],
                "forbidden_reveals": [{"revealKey": k} for k in _DEFAULT_2024_FORBIDDEN],
                "legal_endings": [
                    {"endingId": "open_crossroad"},
                    {"endingId": "two_photos_aligned"},
                    {"endingId": "kamran_said"},
                ],
                "causal_seeds": [
                    "photo_in_pocket", "photo_in_book",
                    "i_arrived_text_2024", "name_of_kamran_spoken_finally",
                ],
                "mandatory_echoes": [
                    {"id": "photo_in_pocket", "target_scenes": ["reunion_2024"], "ai_director_must_invoke": True},
                    {"id": "two_photos_takeout_compare", "target_scenes": ["reunion_2024"], "ai_director_must_invoke": True},
                    {"id": "first_words_admit_2008_2011", "target_scenes": ["reunion_2024"], "ai_director_must_invoke": True},
                ],
                "max_turns": 8,
                "total_action_budget": 32,
                "cast": [
                    {"characterId": "leila", "role": "protagonist"},
                    {"characterId": "arash", "role": "ally"},
                ],
            },
        )

    # ----- W12: case_02 fallback contracts (Moscow no fairy tale) -----
    if case_slug == "case_02_moscow_no_fairy_tale":
        if scene_id == "1985_meeting":
            return LoadedScene(
                scene_id="1985_meeting",
                era="1985",
                title="莫斯科音乐学院 · 305 琴房与两份同版手抄谱",
                cast=[
                    {"characterId": "natasha_roschina", "role": "protagonist"},
                    {"characterId": "ilya_berman", "role": "protagonist"},
                    {"characterId": "room_administrator_305", "role": "witness"},
                ],
                turn_budget=dict(_DEFAULT_TURN_BUDGET),
                investigatable_objects=[],
                causal_seeds=[
                    {"id": "seed_ilya_pencil_page_in_notebook", "source_scene": "1985_meeting", "target_scenes": ["1989_farewell", "2008_reunion"], "echo_intensity": 0.95},
                    {"id": "seed_manuscript_stays_in_305", "source_scene": "1985_meeting", "target_scenes": ["1989_farewell", "2008_reunion"], "echo_intensity": 0.85},
                    {"id": "seed_natasha_keeps_manuscript", "source_scene": "1985_meeting", "target_scenes": ["1989_farewell", "2008_reunion"], "echo_intensity": 0.92},
                ],
                contract={
                    "sceneId": "1985_meeting",
                    "era": "1985",
                    "title": "莫斯科音乐学院 · 305 琴房与两份同版手抄谱",
                    "core_conflict": "总谱只能由一人带离琴房；谁带、抄一份、谁先说'你留'",
                    "allowed_beats": [
                        {"beatId": "opening_first_measure"},
                        {"beatId": "petrof_schellack_stain"},
                        {"beatId": "ilya_pencil_circles"},
                        {"beatId": "natasha_first_not_absent"},
                        {"beatId": "21_40_door_knock"},
                        {"beatId": "copy_offer_nov_7"},
                        {"beatId": "parting_at_door"},
                    ],
                    "forbidden_reveals": [
                        {"revealKey": "ilya_1989_emigration"},
                        {"revealKey": "natasha_1988_warning"},
                        {"revealKey": "sasha_natasha_marriage"},
                        {"revealKey": "lisa_vienna"},
                        {"revealKey": "post_soviet_dissolution"},
                    ],
                    "legal_endings": [
                        {"endingId": "ending_pencil_admit", "label": "铅笔圈注承认"},
                        {"endingId": "ending_pencil_silent", "label": "铅笔圈注沉默"},
                        {"endingId": "ending_copy_offer", "label": "抄一份给你"},
                        {"endingId": "ending_parting_at_door", "label": "两人各自离开"},
                        {"endingId": "ending_first_not_absent", "label": "第一次把不在场说出口"},
                    ],
                    "causal_seeds": [
                        "seed_ilya_pencil_page_in_notebook",
                        "seed_manuscript_stays_in_305",
                        "seed_natasha_keeps_manuscript",
                        "seed_petroff_schellack_stain_in_2008_cafe",
                        "seed_red_notebook_first_entry_1985",
                    ],
                    "mandatory_echoes": [
                        {"id": "pencil_circles_visible_in_1989", "target_scenes": ["1989_farewell", "2008_reunion"], "ai_director_must_invoke": True},
                        {"id": "red_notebook_1985_first_page", "target_scenes": ["2008_reunion"], "ai_director_must_invoke": True},
                        {"id": "petroff_schellack_stain_visible_in_2008", "target_scenes": ["2008_reunion"], "ai_director_must_invoke": True},
                    ],
                    "max_turns": 12,
                    "total_action_budget": 30,
                    "cast": [
                        {"characterId": "natasha_roschina", "role": "protagonist"},
                        {"characterId": "ilya_berman", "role": "protagonist"},
                        {"characterId": "room_administrator_305", "role": "witness"},
                    ],
                },
            )

        if scene_id == "1989_farewell":
            return LoadedScene(
                scene_id="1989_farewell",
                era="1989",
                title="莫斯科谢列梅捷沃机场 · 出境大厅与第三小节",
                cast=[
                    {"characterId": "natasha_roschina", "role": "protagonist"},
                    {"characterId": "ilya_berman", "role": "protagonist"},
                    {"characterId": "sasha_kuzmin", "role": "ally"},
                    {"characterId": "lisa_hoffmann", "role": "ally"},
                    {"characterId": "svo2_baggage_handler", "role": "bystander"},
                ],
                turn_budget=dict(_DEFAULT_TURN_BUDGET),
                investigatable_objects=[],
                causal_seeds=[
                    {"id": "seed_lisa_relays_third_bar", "source_scene": "1989_farewell", "target_scenes": ["2008_reunion"], "echo_intensity": 0.95},
                    {"id": "seed_walkman_tape_in_1989_luggage", "source_scene": "1989_farewell", "target_scenes": ["2008_reunion"], "echo_intensity": 0.85},
                    {"id": "seed_aeroflot_tag_in_page_7", "source_scene": "1989_farewell", "target_scenes": ["2008_reunion"], "echo_intensity": 0.8},
                ],
                contract={
                    "sceneId": "1989_farewell",
                    "era": "1989",
                    "title": "莫斯科谢列梅捷沃机场 · 出境大厅与第三小节",
                    "core_conflict": "四个人分处两个地点，通过一个 4 秒延迟的电话同时在场",
                    "allowed_beats": [
                        {"beatId": "opening_taganka_wardrobe"},
                        {"beatId": "sasha_hand_on_shoulder"},
                        {"beatId": "opening_svo2_lisa"},
                        {"beatId": "ilya_glance_at_notebook"},
                        {"beatId": "5_55_phone_rings"},
                        {"beatId": "4_second_pickup"},
                        {"beatId": "third_bar_oral_message"},
                        {"beatId": "6_15_announcement"},
                        {"beatId": "su355_takeoff"},
                    ],
                    "forbidden_reveals": [
                        {"revealKey": "1992_lisa_ilya_marriage"},
                        {"revealKey": "1993_sasha_natasha_marriage"},
                        {"revealKey": "anya_1994_birth"},
                        {"revealKey": "1991_dissolution"},
                        {"revealKey": "2008_berlin_reunion"},
                    ],
                    "legal_endings": [
                        {"endingId": "ending_third_bar_spoken"},
                        {"endingId": "ending_lisa_silent"},
                        {"endingId": "ending_ilya_notebook_page_1"},
                        {"endingId": "ending_ilya_notebook_page_7"},
                        {"endingId": "ending_natasha_silent_4_seconds"},
                        {"endingId": "ending_su355_takeoff"},
                    ],
                    "causal_seeds": [
                        "seed_lisa_relays_third_bar",
                        "seed_lisa_keeps_silence",
                        "seed_ilya_glances_page_1",
                        "seed_ilya_glances_page_7",
                        "seed_natasha_4_second_silence",
                        "seed_aeroflot_tag_in_page_7",
                        "seed_walkman_tape_in_1989_luggage",
                    ],
                    "mandatory_echoes": [
                        {"id": "third_bar_oral_message_1989", "target_scenes": ["2008_reunion"], "ai_director_must_invoke": True},
                        {"id": "walkman_tape_carries_to_vienna", "target_scenes": ["2008_reunion"], "ai_director_must_invoke": True},
                    ],
                    "max_turns": 14,
                    "total_action_budget": 32,
                    "cast": [
                        {"characterId": "natasha_roschina", "role": "protagonist"},
                        {"characterId": "ilya_berman", "role": "protagonist"},
                        {"characterId": "sasha_kuzmin", "role": "ally"},
                        {"characterId": "lisa_hoffmann", "role": "ally"},
                    ],
                },
            )

        if scene_id == "2008_reunion":
            return LoadedScene(
                scene_id="2008_reunion",
                era="2008",
                title="柏林 · 十字山区老式咖啡馆与 U1 线街口",
                cast=[
                    {"characterId": "natasha_roschina", "role": "protagonist"},
                    {"characterId": "ilya_berman", "role": "protagonist"},
                    {"characterId": "kreuzberg_cafe_owner", "role": "witness"},
                    {"characterId": "sasha_kuzmin_remote", "role": "off_stage"},
                    {"characterId": "lisa_hoffmann_remote", "role": "off_stage"},
                ],
                turn_budget=dict(_DEFAULT_TURN_BUDGET),
                investigatable_objects=[],
                causal_seeds=[
                    {"id": "seed_two_programs_takeout_compare", "source_scene": "2008_reunion", "target_scenes": ["2008_reunion"], "echo_intensity": 0.99},
                    {"id": "seed_first_words_admit_1985_1989", "source_scene": "2008_reunion", "target_scenes": ["2008_reunion"], "echo_intensity": 0.95},
                    {"id": "seed_postcard_wien_1995_unveiled", "source_scene": "2008_reunion", "target_scenes": ["2008_reunion"], "echo_intensity": 0.9},
                ],
                contract={
                    "sceneId": "2008_reunion",
                    "era": "2008",
                    "title": "柏林 · 十字山区老式咖啡馆与 U1 线街口",
                    "core_conflict": "19 年后第一眼落在何处；是否在桌上对齐两份节目单；是否承认 1985/1989 具体行为",
                    "allowed_beats": [
                        {"beatId": "opening_18_30_philharmonie_end"},
                        {"beatId": "natasha_buys_program_op40"},
                        {"beatId": "kreuzberg_cafe_arrival"},
                        {"beatId": "ilya_enters_with_notebook"},
                        {"beatId": "first_gaze_choice"},
                        {"beatId": "two_programs_align"},
                        {"beatId": "red_notebook_page_7_visible"},
                        {"beatId": "postcard_wien_1995_on_table"},
                        {"beatId": "21_00_walk_to_u1"},
                        {"beatId": "21_05_red_to_green"},
                        {"beatId": "simultaneous_turn_and_smile"},
                    ],
                    "forbidden_reveals": [
                        {"revealKey": "2009_post_reunion"},
                        {"revealKey": "next_case"},
                        {"revealKey": "case_01_leila_arash"},
                    ],
                    "legal_endings": [
                        {"endingId": "ending_two_programs_align"},
                        {"endingId": "ending_first_words_admit"},
                        {"endingId": "ending_postcard_unveiled"},
                        {"endingId": "ending_crossroads_parting"},
                        {"endingId": "ending_silent_keeping"},
                        {"endingId": "ending_reality_lives_convergence"},
                    ],
                    "causal_seeds": [
                        "seed_two_programs_takeout_compare",
                        "seed_first_words_admit_1985_1989",
                        "seed_postcard_wien_1995_unveiled",
                        "seed_petroff_schellack_stain_in_2008_cafe",
                        "seed_aeroflot_tag_visible_in_page_7",
                        "seed_walkman_tape_remembered",
                        "seed_third_bar_oral_message_remembered",
                        "seed_4_second_symmetry",
                    ],
                    "mandatory_echoes": [
                        {"id": "two_programs_takeout_compare", "target_scenes": ["2008_reunion"], "ai_director_must_invoke": True},
                        {"id": "first_words_admit_1985_1989", "target_scenes": ["2008_reunion"], "ai_director_must_invoke": True},
                        {"id": "4_second_symmetry_2008", "target_scenes": ["2008_reunion"], "ai_director_must_invoke": True},
                    ],
                    "max_turns": 16,
                    "total_action_budget": 36,
                    "cast": [
                        {"characterId": "natasha_roschina", "role": "protagonist"},
                        {"characterId": "ilya_berman", "role": "protagonist"},
                        {"characterId": "kreuzberg_cafe_owner", "role": "witness"},
                    ],
                },
            )

    raise KeyError(f"unknown scene id: {scene_id!r} (case={case_slug!r})")


# ---------------------------------------------------------------------------
# YAML → contract normaliser
# ---------------------------------------------------------------------------


def _normalise_yaml(case_slug: str, scene_id: str, raw: dict[str, Any]) -> LoadedScene:
    """Convert a raw YAML dict into a :class:`LoadedScene` (W12: case-aware)."""

    era = str(raw.get("era", ""))
    title = str(raw.get("title", scene_id))

    # ---- cast ----
    cast_raw = raw.get("characters_present", []) or []
    cast = []
    for c in cast_raw:
        if not isinstance(c, dict):
            continue
        role = c.get("role") or _infer_role(case_slug, c.get("id", ""))
        cast.append({"characterId": str(c.get("id", "")), "role": str(role)})

    # ---- turn_budget ----
    tb_raw = raw.get("turn_budget", {}) or {}
    turn_budget: dict[str, int] = {}
    for k, v in tb_raw.items():
        if k == "total":
            continue
        try:
            turn_budget[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    if not turn_budget:
        turn_budget = dict(_DEFAULT_TURN_BUDGET)

    # ---- investigatable_objects ----
    inv_raw = raw.get("investigatable_objects", []) or []
    investigatable_objects: list[dict[str, Any]] = []
    for obj in inv_raw:
        if not isinstance(obj, dict):
            continue
        investigatable_objects.append({
            "id": str(obj.get("id", "")),
            "name": str(obj.get("name", "")),
            "description": str(obj.get("description", "")),
            "initialLocation": str(obj.get("initial_location", "")),
            "keywords": list(obj.get("keywords", []) or []),
            "requires": list(obj.get("requires", []) or []),
            "leadsTo": list(obj.get("leads_to", []) or []),
        })

    # ---- causal_seeds ----
    cs_raw = raw.get("causal_seeds", []) or []
    causal_seeds: list[dict[str, Any]] = []
    for s in cs_raw:
        if not isinstance(s, dict):
            continue
        causal_seeds.append({
            "id": str(s.get("id", "")),
            "source_scene": scene_id,
            "description": str(s.get("description", "")),
            "trigger": str(s.get("trigger", "")),
            "target_scenes": _infer_seed_targets(case_slug, scene_id, s),
            "echo_intensity": 0.8,
        })

    # ---- mandatory_echoes (decision 3) ----
    me_raw = raw.get("mandatory_echoes", []) or []
    mandatory_echoes = [
        {
            "id": str(m.get("id", "")),
            "description": str(m.get("description", "")),
            "trigger": str(m.get("trigger", "")),
            "target_scenes": list(m.get("target_scenes", []) or []),
            "ai_director_must_invoke": bool(m.get("ai_director_must_invoke", True)),
        }
        for m in me_raw
        if isinstance(m, dict) and m.get("id")
    ]

    # ---- allowed_beats ----
    ab_raw = raw.get("allowed_beats", []) or []
    allowed_beats = [{"beatId": str(b), "label": str(b)} for b in ab_raw if isinstance(b, str)]

    # ---- forbidden_reveals ----
    fr_raw = raw.get("forbidden_reveals", []) or []
    forbidden_reveals = [{"revealKey": str(r), "reason": ""} for r in fr_raw if isinstance(r, str)]

    # ---- legal_endings ----
    le_raw = raw.get("legal_endings", []) or []
    legal_endings: list[dict[str, Any]] = []
    for e in le_raw:
        if isinstance(e, dict):
            legal_endings.append({
                "endingId": str(e.get("id", "")),
                "label": str(e.get("label", "")),
                "description": str(e.get("description", "")),
                "conditions": list(e.get("causal_seed_required", []) or []),
            })
        elif isinstance(e, str):
            legal_endings.append({"endingId": e, "label": e})

    # ---- cast of the contract (must be there even if YAML has none) ----
    if not cast:
        cast = _default_contract(case_slug, scene_id).cast

    # ---- build the contract the Resolver reads ----
    contract = {
        "sceneId": scene_id,
        "era": era,
        "title": title,
        "core_conflict": "；".join(raw.get("core_conflict", []) or []) or f"conflict_{scene_id}",
        "allowed_beats": allowed_beats or [{"beatId": "beat_setup_0"}],
        "forbidden_reveals": forbidden_reveals,
        "legal_endings": legal_endings,
        "causal_seeds": [c["id"] for c in causal_seeds],
        "mandatory_echoes": mandatory_echoes,
        "max_turns": int(raw.get("turn_budget", {}).get("total", 8) or 8),
        "total_action_budget": int(sum(turn_budget.values()) + 4),
        "cast": cast,
    }

    return LoadedScene(
        scene_id=scene_id,
        era=era,
        title=title,
        contract=contract,
        cast=cast,
        turn_budget=turn_budget,
        investigatable_objects=investigatable_objects,
        causal_seeds=causal_seeds,
    )


def _infer_role(case_slug: str, character_id: str) -> str:
    """Best-effort role guess for the YAML → Resolver contract cast (W12 case-aware)."""

    if case_slug == "case_02_moscow_no_fairy_tale":
        if character_id in {"natasha_roschina"}:
            return "protagonist"
        if character_id in {"ilya_berman"}:
            return "protagonist"
        return "witness"
    # case_01 (default)
    if character_id in {"leila"}:
        return "protagonist"
    if character_id in {"arash"}:
        return "ally"
    return "witness"


def _infer_seed_targets(case_slug: str, scene_id: str, seed: dict[str, Any]) -> list[str]:
    """Heuristic: decide which future scenes a seed may fire in (W12 case-aware).

    V5 命题的关键：case_02 YAML 的 causal_seeds_extended 显式带
    ``target_scenes`` 字段，优先读这个；case_01 的旧 YAML 没有这个字段，
    退回到"按 year 在 effects 文本中查找"启发式。
    """

    explicit = seed.get("target_scenes")
    if isinstance(explicit, list) and explicit:
        return [str(s) for s in explicit]

    # Backward-compat: case_01 用 year-to-scene 推断
    entry = CASE_REGISTRY.get(case_slug, CASE_REGISTRY[CASE_SLUG_DEFAULT])
    year_to_scene = entry.get("year_to_scene", {})

    effects_text = " ".join(seed.get("effects", []) or [])
    targets: list[str] = []
    for year, scene_target in year_to_scene.items():
        if year in effects_text and scene_target not in targets:
            targets.append(scene_target)
    if not targets:
        # Default: every seed not in the current scene is dormant
        # for the latest scene (the only scene in the vertical
        # slice that fires cross-era echoes).
        src = str(seed.get("source_scene", scene_id))
        scenes_in_order = entry.get("scenes_in_order", SCENES_IN_ORDER)
        if src in scenes_in_order:
            targets = [s for s in scenes_in_order if s != src]
    return targets


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _content_root() -> pathlib.Path:
    """Resolve the project's content/ directory."""

    return pathlib.Path(__file__).resolve().parents[1] / "content"


class SceneContractLoader:
    """Cache + serve scene contracts for any registered case (W12).

    Usage
    -----

    .. code-block:: python

        # Backward-compatible: defaults to case_01
        loader = SceneContractLoader()
        scene = loader.load("photo_lab_2008")

        # W12: case-aware
        loader2 = SceneContractLoader()
        scene = loader2.load_scene("case_02_moscow_no_fairy_tale", "1985_meeting")
    """

    def __init__(self, content_root: pathlib.Path | None = None) -> None:
        self._root = content_root or _content_root()
        # (case_slug, scene_id) -> LoadedScene
        self._cache: dict[tuple[str, str], LoadedScene] = {}

    @property
    def content_root(self) -> pathlib.Path:
        return self._root

    def _cache_key(self, case_slug: str, scene_id: str) -> tuple[str, str]:
        return (case_slug, scene_id)

    def load(self, scene_id: str) -> LoadedScene:
        """Backward-compat: load scene from default case (case_01)."""

        return self.load_scene(CASE_SLUG_DEFAULT, scene_id)

    def load_scene(self, case_slug: str, scene_id: str) -> LoadedScene:
        """Return the :class:`LoadedScene` for (case_slug, scene_id).

        Reads from the YAML on first call; subsequent calls hit
        the in-memory cache.  Falls back to the built-in
        contract on any read error so the demo stays up.
        """

        if case_slug not in CASE_REGISTRY:
            logger.warning(
                "scene_loader: unknown case_slug=%s; falling back to default", case_slug
            )
            case_slug = CASE_SLUG_DEFAULT

        key = self._cache_key(case_slug, scene_id)
        if key in self._cache:
            return self._cache[key]

        yaml_path = self._root / case_slug / "scenes" / f"{scene_id}.yaml"
        loaded: LoadedScene
        if yaml_path.is_file():
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
                loaded = _normalise_yaml(case_slug, scene_id, raw)
            except (yaml.YAMLError, OSError, KeyError) as exc:
                logger.warning(
                    "scene_loader: failed to parse %s (%s); using built-in contract",
                    yaml_path, exc,
                )
                loaded = _default_contract(case_slug, scene_id)
        else:
            logger.info(
                "scene_loader: YAML not found at %s; using built-in contract", yaml_path
            )
            loaded = _default_contract(case_slug, scene_id)

        self._cache[key] = loaded
        return loaded

    def all_scenes(self) -> list[LoadedScene]:
        """Return all scenes for default case in canonical order."""

        return self.all_scenes_for(CASE_SLUG_DEFAULT)

    def all_scenes_for(self, case_slug: str) -> list[LoadedScene]:
        """Return all scenes for ``case_slug`` in canonical order."""

        if case_slug not in CASE_REGISTRY:
            return []
        return [self.load_scene(case_slug, s) for s in CASE_REGISTRY[case_slug]["scenes_in_order"]]

    def scenes_in_order(self, case_slug: str) -> list[str]:
        """Return the registered scene-id list for ``case_slug``."""

        entry = CASE_REGISTRY.get(case_slug)
        if entry is None:
            return []
        return list(entry["scenes_in_order"])

    def reload(self, scene_id: str | None = None) -> list[str]:
        """Invalidate the in-memory cache (W10 hot-reload).

        Returns the list of ``scene_id`` values that were
        evicted.  The next :meth:`load` call re-reads the
        YAML from disk.  This is the *only* supported way
        for the content-workshop to push a策划 YAML update
        without restarting the server.
        """

        if scene_id is None:
            evicted = [sid for (_cs, sid) in self._cache.keys()]
            self._cache.clear()
            return evicted
        # default case_slug for backward compat
        if (CASE_SLUG_DEFAULT, scene_id) in self._cache:
            self._cache.pop((CASE_SLUG_DEFAULT, scene_id), None)
            return [scene_id]
        return []

    def is_cached(self, scene_id: str) -> bool:
        return (CASE_SLUG_DEFAULT, scene_id) in self._cache

    def build_budget(self, scene_id: str) -> dict[str, int]:
        """Return the per-action budget dict for ``scene_id`` (default case)."""

        return dict(self.load(scene_id).turn_budget)

    def build_budget_for(self, case_slug: str, scene_id: str) -> dict[str, int]:
        """Return the per-action budget dict for (case_slug, scene_id)."""

        return dict(self.load_scene(case_slug, scene_id).turn_budget)

    def contract_dict(self, scene_id: str) -> dict[str, Any]:
        """Return just the contract dict (what the Resolver reads)."""

        return dict(self.load(scene_id).contract)

    def scene_meta(self, scene_id: str) -> dict[str, Any]:
        """Return a client-friendly scene metadata dict (default case).

        Mirrors the ``SceneMeta`` shape in
        ``client/src/types/schemas.ts`` so the client can
        render the scene without the YAML.
        """

        return self.scene_meta_for(CASE_SLUG_DEFAULT, scene_id)

    def scene_meta_for(self, case_slug: str, scene_id: str) -> dict[str, Any]:
        """Return a client-friendly scene metadata dict (W12: case-aware)."""

        s = self.load_scene(case_slug, scene_id)
        return {
            "sceneId": s.scene_id,
            "title": s.title,
            "era": s.era,
            "location": "",
            "atmosphere": [],
            "contract": s.contract,
            "investigatableObjects": s.investigatable_objects,
            "charactersPresent": [
                {
                    "id": c["characterId"],
                    "name": c["characterId"],
                    "initialState": "",
                    "visibility": "主角视角可见",
                    "stateNotes": [],
                }
                for c in s.cast
            ],
            "turnBudget": s.turn_budget,
            "causalSeeds": s.causal_seeds,
            "legalEndings": [
                {
                    "id": e["endingId"],
                    "label": e.get("label", e["endingId"]),
                    "description": e.get("description", ""),
                    "causalSeedRequired": e.get("conditions", []),
                }
                for e in s.contract.get("legal_endings", [])
            ],
            "caseSlug": case_slug,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


_default_loader: SceneContractLoader | None = None


def get_default_loader() -> SceneContractLoader:
    """Return a process-wide loader singleton."""

    global _default_loader
    if _default_loader is None:
        _default_loader = SceneContractLoader()
    return _default_loader


__all__ = [
    "CASE_SLUG_DEFAULT",
    "SCENES_IN_ORDER",
    "CASE_REGISTRY",
    "list_cases",
    "get_case_meta",
    "LoadedScene",
    "SceneContractLoader",
    "get_default_loader",
]


if __name__ == "__main__":  # pragma: no cover
    # CLI: dump every registered case's contracts as JSON
    loader = get_default_loader()
    for case_meta in list_cases():
        slug = case_meta["caseSlug"]
        for sid in loader.scenes_in_order(slug):
            s = loader.load_scene(slug, sid)
            print(json.dumps({"caseSlug": slug, **s.to_dict()}, ensure_ascii=False, indent=2))
