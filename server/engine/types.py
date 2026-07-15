"""Shared types and constants for the AI-native game engine.

This module centralises the enums, type aliases and small immutable
helpers used by every other module in the engine.  All values come
from the JSON Schemas under ``server/config/schemas/`` so the engine
stays schema-aligned by construction.

Why this module exists
----------------------
The 12 atomic actions, the 5 belief states, the 8 causal-seed
trigger conditions, the 10 distortion types, the 4 scene phases and
the 13 era tags each appear in multiple places.  Centralising them
prevents drift between modules, makes a single import line the
source of truth, and gives the rest of the package a stable
namespace to import from in tests.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

SCHEMA_VERSION: Final[str] = "1.0.0"


# ---------------------------------------------------------------------------
# Atomic player action vocabulary (12) - matches player_action.schema.json
# ---------------------------------------------------------------------------


class ActionType(str, Enum):
    """The 12 structured behaviours the engine accepts.

    These are the **only** action verbs the player (or NPC) may
    submit.  Free-form LLM output must be mapped to one of these
    before it reaches the state machine.
    """

    INVESTIGATE = "investigate"
    REVEAL = "reveal"
    CONCEAL = "conceal"
    QUESTION = "question"
    CONFRONT = "confront"
    COMFORT = "comfort"
    GIVE = "give"
    DESTROY = "destroy"
    PROMISE = "promise"
    WAIT = "wait"
    LEAVE = "leave"
    SILENCE = "silence"


# Actions that require a non-null target character (NPC) — per player_action
# schema "allOf" rule.  validate_player_action enforces this at runtime.
TARGET_REQUIRED_ACTIONS: Final[frozenset[ActionType]] = frozenset(
    {ActionType.QUESTION, ActionType.CONFRONT, ActionType.GIVE, ActionType.COMFORT}
)

# Actions that require a non-empty evidence list (artifact IDs).
EVIDENCE_REQUIRED_ACTIONS: Final[frozenset[ActionType]] = frozenset(
    {ActionType.REVEAL, ActionType.DESTROY, ActionType.GIVE}
)


# ---------------------------------------------------------------------------
# Belief matrix vocabulary
# ---------------------------------------------------------------------------


class BeliefState(str, Enum):
    """5 belief states - matches belief_matrix.schema.json character_knowledge."""

    CERTAIN = "certain"
    UNCERTAIN = "uncertain"
    WRONG = "wrong"
    DENIED = "denied"
    REINFORCED = "reinforced"


BELIEF_STATES: Final[frozenset[str]] = frozenset(s.value for s in BeliefState)


class DistortionType(str, Enum):
    """10 distortion types - matches belief_matrix.schema.json character_memories."""

    NONE = "none"
    TRAUMATIC_EXAGGERATION = "traumatic_exaggeration"
    TRAUMATIC_SUPPRESSION = "traumatic_suppression"
    ROSY_RETROSPECTION = "rosy_retrospection"
    SELF_SERVING_BIAS = "self_serving_bias"
    CONFABULATION = "confabulation"
    MISATTRIBUTION = "misattribution"
    MORAL_REFRAMING = "moral_reframing"
    TIME_COMPRESSION = "time_compression"
    TIME_EXPANSION = "time_expansion"


DISTORTION_TYPES: Final[frozenset[str]] = frozenset(d.value for d in DistortionType)


# ---------------------------------------------------------------------------
# Causal seed trigger condition types
# ---------------------------------------------------------------------------


class TriggerType(str, Enum):
    """8 trigger types - matches causal_seed.schema.json trigger_condition.type."""

    SCENE_MATCH = "scene_match"
    CHARACTER_PRESENT = "character_present"
    ERA_MATCH = "era_match"
    BELIEF_STATE = "belief_state"
    MEMORY_RECALL = "memory_recall"
    ARTIFACT_PRESENT = "artifact_present"
    LOCATION_MATCH = "location_match"
    COMPOSITE = "composite"


TRIGGER_TYPES: Final[frozenset[str]] = frozenset(t.value for t in TriggerType)


# ---------------------------------------------------------------------------
# Scene / canonical state vocabulary
# ---------------------------------------------------------------------------


class ScenePhase(str, Enum):
    """6 scene phases - matches world_snapshot.schema.json canonicalState.phase."""

    SETUP = "setup"
    RISING = "rising"
    CLIMAX = "climax"
    FALLING = "falling"
    RESOLUTION = "resolution"
    ENDED = "ended"


class Era(str, Enum):
    """13 era tags - matches world_snapshot.schema.json canonicalState.era."""

    PRE_1911_QING = "pre_1911_qing"
    Y1911_1927_REPUBLIC = "1911_1927_republic"
    Y1927_1937_NANJING = "1927_1937_nanjing_decade"
    Y1937_1945_WAR = "1937_1945_war"
    Y1945_1949_CIVIL_WAR = "1945_1949_civil_war"
    Y1949_1965_SOCIALIST = "1949_1965_socialist_build"
    Y1966_1976_CULTURAL = "1966_1976_cultural_revolution"
    Y1977_1989_REFORM = "1977_1989_reform_early"
    Y1989_2000_BOOM = "1989_2000_boom"
    Y2000_2012_GLOBALIZATION = "2000_2012_globalization"
    Y2012_PRESENT_AI = "2012_present_ai_age"
    PRESENT = "present"
    EPILOGUE = "epilogue"


# ---------------------------------------------------------------------------
# Per-case era overrides (ADR 0007)
# ---------------------------------------------------------------------------
#
# The Era enum above is a 13-value catalogue aligned with the
# world_snapshot schema (it covers a planned multi-case / multi-era
# project that includes 《崇祯》and other historical works).
# The first shipped case — *case_01_revolution_street* — only
# touches four era values, all four written as short year-strings
# that the team uses everywhere in scene YAML, contracts and the
# client.  Mapping them here keeps the engine schema-aligned (Era
# enum unchanged, world_snapshot.schema.json unchanged) while
# letting scene contracts use the team's short, year-style
# identifiers without having to bend the canonical 13-value enum
# to fit a single case.
#
# Adding a new case:
#   1. Pick a case slug (e.g. ``case_02_xxx``)
#   2. Add a new key to ``CASE_ERAS`` whose value is a
#      ``dict[sceneId, era_string]``
#   3. The era_string may be either an :class:`Era` value or a
#      case-scoped shorthand (typically a year string)
#   4. The Resolver and contract loader use
#      :func:`is_valid_era_for_case` to validate
#
# Compatibility:
#   * The Era enum is unchanged — all 13 canonical values remain
#     valid ``canonicalState.era`` strings.
#   * Case-scoped shorthands are *additive* — they do not replace
#     the canonical values, they extend the accepted set on a
#     per-case basis.
#   * The world_snapshot schema's ``canonicalState.era`` enum is
#     a closed list today.  When a case adds new era strings, the
#     schema must be updated *in the same PR* to add the new
#     values to its enum.  ``is_valid_era_for_case`` is the
#     runtime check; the schema is the static check.
# ---------------------------------------------------------------------------


#: Mapping ``case_slug -> {sceneId: era_string}``.
#:
#: A case-scoped era is acceptable only when it appears as a value
#: for the matching case.  The values may be either an :class:`Era`
#: value or a case-specific shorthand (typically a year).
CASE_ERAS: Final[dict[str, dict[str, str]]] = {
    "case_01_revolution_street": {
        "2008_photo_lab": "2008",
        "2011_farewell": "2011",
        "2024_reunion": "2024",
        "epilogue": "EPILOGUE",
    },
    # W12: 第二案 A《莫斯科没有童话》· 3 scene era 短映射
    "case_02_moscow_no_fairy_tale": {
        "1985_meeting": "1985",
        "1989_farewell": "1989",
        "2008_reunion": "2008",
    },
}


def is_valid_era_for_case(era: str, case_slug: str) -> bool:
    """Return True iff ``era`` is a legal value for ``case_slug``.

    An era is legal if:

    1. It is one of the 13 canonical :class:`Era` enum values, **or**
    2. It appears in :data:`CASE_ERAS` for the given case slug.

    This is the **P0-7** runtime check.  The Resolver calls it on
    every snapshot hydration / canonical-state update.

    Parameters
    ----------
    era : str
        The era string to validate.  ``Era`` enum instances are
        accepted and converted to their value via ``.value``.
    case_slug : str
        The case identifier (``"case_01_revolution_street"`` for
        the first shipped case).

    Returns
    -------
    bool
        True iff the era is in either the canonical 13-value set
        or the case-scoped overrides.
    """

    if isinstance(era, Era):
        era = era.value
    canonical = {e.value for e in Era}
    if era in canonical:
        return True
    case_map = CASE_ERAS.get(case_slug, {})
    return era in set(case_map.values())


def legal_eras_for_case(case_slug: str) -> set[str]:
    """Return the set of all legal era strings for ``case_slug``.

    Combines the 13 canonical :class:`Era` values with the
    case-scoped overrides.  Useful for tests and for the
    content-studio validation surface.
    """

    legal = {e.value for e in Era}
    legal.update(CASE_ERAS.get(case_slug, {}).values())
    return legal


# ---------------------------------------------------------------------------
# Numeric clamps - match the schema multipleOf / minimum / maximum fields
# ---------------------------------------------------------------------------


# Trust / intimacy / respect ∈ [-1, 1]
# Per-turn |delta| <= 0.25 (decision 1 hard cap)
MIN_RELATIONSHIP: Final[float] = -1.0
MAX_RELATIONSHIP: Final[float] = 1.0
MAX_RELATIONSHIP_DELTA: Final[float] = 0.25
RELATIONSHIP_QUANTUM: Final[float] = 0.01  # schema multipleOf

# Fear / unresolvedConflict / globalTension / echo_intensity / recallWeight /
# decayScore / leakageRisk / confidence ∈ [0, 1]
MIN_UNIT: Final[float] = 0.0
MAX_UNIT: Final[float] = 1.0
UNIT_QUANTUM: Final[float] = 0.01

# Per-turn relationship delta quantum (multipleOf 0.01)
DELTA_QUANTUM: Final[float] = 0.01

# emotional_intensity quantum
EMOTION_QUANTUM: Final[float] = 0.05
MIN_EMOTION: Final[float] = 0.0
MAX_EMOTION: Final[float] = 1.0

# pacingPressure quantum
PACING_QUANTUM: Final[float] = 0.05

# expectedTensionDelta range
MIN_TENSION_DELTA: Final[float] = -1.0
MAX_TENSION_DELTA: Final[float] = 1.0
TENSION_DELTA_QUANTUM: Final[float] = 0.05


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def clamp(value: float, lo: float, hi: float, quantum: float | None = None) -> float:
    """Clamp ``value`` to ``[lo, hi]`` and optionally snap to a quantum grid.

    The engine uses this everywhere a numeric field is touched by a
    reducer so that overflow is impossible by construction.  When
    ``quantum`` is given the result is rounded to the nearest multiple
    of ``quantum`` to mirror the JSON Schema ``multipleOf`` rule.

    Implementation note
    -------------------
    The snap uses a ``Decimal``-backed integer to dodge the
    classic ``0.95 / 0.01 = 94.99999999999999`` floating-point
    hazard, then re-emits a float.  This keeps the JSON Schema's
    ``multipleOf`` rule satisfied without binary noise.
    """

    if value < lo:
        value = lo
    elif value > hi:
        value = hi
    if quantum is not None and quantum > 0:
        from decimal import Decimal, ROUND_HALF_UP
        d_value = Decimal(str(value))
        d_quantum = Decimal(str(quantum))
        snapped = (d_value / d_quantum).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        value = float(snapped * d_quantum)
    return float(value)


def clamp_unit(value: float) -> float:
    """Convenience wrapper for [0, 1] + 0.01 quantum."""

    return clamp(value, MIN_UNIT, MAX_UNIT, UNIT_QUANTUM)


def clamp_relationship(value: float) -> float:
    """Convenience wrapper for [-1, 1] + 0.01 quantum."""

    return clamp(value, MIN_RELATIONSHIP, MAX_RELATIONSHIP, RELATIONSHIP_QUANTUM)


def clamp_relationship_delta(value: float) -> float:
    """Apply per-turn delta cap (|delta| ≤ 0.25) and quantise.

    This is the **hard cap** that prevents runaway love / hate values
    that would otherwise accumulate over a 30-45 minute session.  See
    decision 1 + experience-lesson rule 4 ("don't expose a love meter").
    """

    return clamp(value, -MAX_RELATIONSHIP_DELTA, MAX_RELATIONSHIP_DELTA, DELTA_QUANTUM)


__all__ = [
    "SCHEMA_VERSION",
    "ActionType",
    "TARGET_REQUIRED_ACTIONS",
    "EVIDENCE_REQUIRED_ACTIONS",
    "BeliefState",
    "BELIEF_STATES",
    "DistortionType",
    "DISTORTION_TYPES",
    "TriggerType",
    "TRIGGER_TYPES",
    "ScenePhase",
    "Era",
    "CASE_ERAS",
    "is_valid_era_for_case",
    "legal_eras_for_case",
    "MIN_RELATIONSHIP",
    "MAX_RELATIONSHIP",
    "MAX_RELATIONSHIP_DELTA",
    "RELATIONSHIP_QUANTUM",
    "MIN_UNIT",
    "MAX_UNIT",
    "UNIT_QUANTUM",
    "DELTA_QUANTUM",
    "EMOTION_QUANTUM",
    "MIN_EMOTION",
    "MAX_EMOTION",
    "PACING_QUANTUM",
    "MIN_TENSION_DELTA",
    "MAX_TENSION_DELTA",
    "TENSION_DELTA_QUANTUM",
    "clamp",
    "clamp_unit",
    "clamp_relationship",
    "clamp_relationship_delta",
]
