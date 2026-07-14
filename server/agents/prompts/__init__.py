"""Prompt templates for the AI-native agent package.

The prompts in this package are **deterministic templates** that
the agent classes (:mod:`intent_parser`, :mod:`npc_agent`,
:mod:`director_agent`) consume and feed to the model gateway.

Why a separate package
----------------------
* All narrative-style language lives in one place, so the writers
  and the design team can review it without touching agent code.
* The agent code stays free of any string-literal Chinese / Persian /
  Turkish / Italian prose, which is what a model gateway actually
  cares about.
* Tests can substitute a stub prompt and verify the agent's
  structural behaviour without depending on the prose.
"""

from __future__ import annotations

from .character_card import (
    CHARACTER_CARDS,
    CharacterCard,
    get_character_card,
    ALL_CHARACTER_IDS,
)
from .npc_system_prompt import (
    build_npc_system_prompt,
    NPC_SYSTEM_PROMPT_VERSION,
    NPC_SYSTEM_PROMPT_GUARDRAILS,
)
from .director_system_prompt import (
    build_director_system_prompt,
    DIRECTOR_SYSTEM_PROMPT_VERSION,
    DIRECTOR_SYSTEM_PROMPT_GUARDRAILS,
)
from .style_bible import (
    STYLE_BIBLE_VERSION,
    style_bible_for_era,
    ERA_REGISTER,
    NARRATOR_VOICE_DEFAULT,
)

__all__ = [
    # character_card
    "CHARACTER_CARDS",
    "CharacterCard",
    "get_character_card",
    "ALL_CHARACTER_IDS",
    # npc_system_prompt
    "build_npc_system_prompt",
    "NPC_SYSTEM_PROMPT_VERSION",
    "NPC_SYSTEM_PROMPT_GUARDRAILS",
    # director_system_prompt
    "build_director_system_prompt",
    "DIRECTOR_SYSTEM_PROMPT_VERSION",
    "DIRECTOR_SYSTEM_PROMPT_GUARDRAILS",
    # style_bible
    "STYLE_BIBLE_VERSION",
    "style_bible_for_era",
    "ERA_REGISTER",
    "NARRATOR_VOICE_DEFAULT",
]
