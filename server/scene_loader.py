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


def _default_contract(scene_id: str) -> LoadedScene:
    """Build a built-in contract for a scene.

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

    raise KeyError(f"unknown scene id: {scene_id!r}")


# ---------------------------------------------------------------------------
# YAML → contract normaliser
# ---------------------------------------------------------------------------


def _normalise_yaml(scene_id: str, raw: dict[str, Any]) -> LoadedScene:
    """Convert a raw YAML dict into a :class:`LoadedScene`."""

    era = str(raw.get("era", ""))
    title = str(raw.get("title", scene_id))

    # ---- cast ----
    cast_raw = raw.get("characters_present", []) or []
    cast = []
    for c in cast_raw:
        if not isinstance(c, dict):
            continue
        role = c.get("role") or _infer_role(c.get("id", ""))
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
            "target_scenes": _infer_seed_targets(s),
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
        cast = _default_contract(scene_id).cast

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


def _infer_role(character_id: str) -> str:
    """Best-effort role guess for the YAML → Resolver contract cast."""

    if character_id in {"leila"}:
        return "protagonist"
    if character_id in {"arash"}:
        return "ally"
    return "witness"


def _infer_seed_targets(seed: dict[str, Any]) -> list[str]:
    """Heuristic: decide which future scenes a seed may fire in.

    The YAML's ``effects`` lines often name a year (e.g. "2011",
    "2024"); we map that to a scene id.  This is the
    case-scoped mapping the W3 integration test relies on.
    """

    effects_text = " ".join(seed.get("effects", []) or [])
    targets: list[str] = []
    for year, scene_id in (
        ("2011", "farewell_2011"),
        ("2024", "reunion_2024"),
    ):
        if year in effects_text and scene_id not in targets:
            targets.append(scene_id)
    if not targets:
        # Default: every seed not in the current scene is dormant
        # for reunion_2024 (the only scene in the case_01
        # vertical slice that fires cross-era echoes).
        src = str(seed.get("source_scene", seed.get("id", "")))
        if src in SCENES_IN_ORDER:
            targets = [s for s in SCENES_IN_ORDER if s != src]
    return targets


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _content_root() -> pathlib.Path:
    """Resolve the project's content/ directory."""

    return pathlib.Path(__file__).resolve().parents[1] / "content"


class SceneContractLoader:
    """Cache + serve the three case_01 scene contracts.

    Usage
    -----

    .. code-block:: python

        loader = SceneContractLoader()
        scene = loader.load("photo_lab_2008")
        budget = loader.build_budget("photo_lab_2008")
    """

    def __init__(self, content_root: pathlib.Path | None = None) -> None:
        self._root = content_root or _content_root()
        self._cache: dict[str, LoadedScene] = {}

    @property
    def content_root(self) -> pathlib.Path:
        return self._root

    def load(self, scene_id: str) -> LoadedScene:
        """Return the :class:`LoadedScene` for ``scene_id``.

        Reads from the YAML on first call; subsequent calls hit
        the in-memory cache.  Falls back to the built-in
        contract on any read error so the demo stays up.
        """

        if scene_id in self._cache:
            return self._cache[scene_id]

        yaml_path = self._root / CASE_SLUG_DEFAULT / "scenes" / f"{scene_id}.yaml"
        loaded: LoadedScene
        if yaml_path.is_file():
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
                loaded = _normalise_yaml(scene_id, raw)
            except (yaml.YAMLError, OSError, KeyError) as exc:
                logger.warning(
                    "scene_loader: failed to parse %s (%s); using built-in contract",
                    yaml_path, exc,
                )
                loaded = _default_contract(scene_id)
        else:
            logger.info(
                "scene_loader: YAML not found at %s; using built-in contract", yaml_path
            )
            loaded = _default_contract(scene_id)

        self._cache[scene_id] = loaded
        return loaded

    def all_scenes(self) -> list[LoadedScene]:
        """Return all scenes in canonical order."""

        return [self.load(s) for s in SCENES_IN_ORDER]

    def reload(self, scene_id: str | None = None) -> list[str]:
        """Invalidate the in-memory cache (W10 hot-reload).

        Returns the list of ``scene_id`` values that were
        evicted.  The next :meth:`load` call re-reads the
        YAML from disk.  This is the *only* supported way
        for the content-workshop to push a策划 YAML update
        without restarting the server.
        """

        if scene_id is None:
            evicted = list(self._cache.keys())
            self._cache.clear()
            return evicted
        if scene_id in self._cache:
            self._cache.pop(scene_id, None)
            return [scene_id]
        return []

    def is_cached(self, scene_id: str) -> bool:
        return scene_id in self._cache

    def build_budget(self, scene_id: str) -> dict[str, int]:
        """Return the per-action budget dict for ``scene_id``."""

        return dict(self.load(scene_id).turn_budget)

    def contract_dict(self, scene_id: str) -> dict[str, Any]:
        """Return just the contract dict (what the Resolver reads)."""

        return dict(self.load(scene_id).contract)

    def scene_meta(self, scene_id: str) -> dict[str, Any]:
        """Return a client-friendly scene metadata dict.

        Mirrors the ``SceneMeta`` shape in
        ``client/src/types/schemas.ts`` so the client can
        render the scene without the YAML.
        """

        s = self.load(scene_id)
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
    "LoadedScene",
    "SceneContractLoader",
    "get_default_loader",
]


if __name__ == "__main__":  # pragma: no cover
    # CLI: dump all three contracts as JSON for sanity checking
    loader = get_default_loader()
    for sid in SCENES_IN_ORDER:
        s = loader.load(sid)
        print(json.dumps(s.to_dict(), ensure_ascii=False, indent=2))
