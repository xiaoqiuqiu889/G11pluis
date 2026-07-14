"""NPC agent system prompt — the guardrailed prompt template.

The NPC agent runs once per turn for every on-stage NPC.  The
prompt is structured so the LLM can only output what the Resolver
will accept (a :class:`engine.NPCProposal` JSON object).

The prompt encodes the **decisions 1, 3, 5, 6** rules from
``requirements-review-v1.md``:

* **Decision 1** — the LLM may only emit a 12-value ``proposedAction``;
  free-form chat is structurally forbidden by the schema.
* **Decision 3** — any echo / reference to a past event must come
  from the recall set OR be the result of a ``mandatory_echo`` the
  Resolver pre-approved.  The prompt makes the LLM declare which.
* **Decision 5** — the LLM is reminded that the L1 fallback exists;
  a low-confidence or timed-out call lands on the writer-authored
  fallback line.
* **Decision 6** — the LLM must satisfy at least one of the
  four-questions (changes_world_state / changes_knowledge /
  changes_actions / future_echo).  The agent-side 4-check tool
  rejects the proposal if all four are zero.

The actual output is **JSON in `npc_proposal.schema.json` shape**.
The prompt instructs the model to emit a single JSON object, not
prose.  The agent code wraps the call with the JSON-mode flag and
the Resolver validates the structure.
"""

from __future__ import annotations

from typing import Any, Final

from .character_card import CharacterCard, get_character_card
from .style_bible import NARRATOR_VOICE_DEFAULT, style_bible_for_era


# Bump when the prompt template changes.  The agent code asserts
# against this on import; if a deployment lags behind, tests fail
# loudly.
NPC_SYSTEM_PROMPT_VERSION: Final[str] = "1.0.0"


# Hard rules that are appended to every NPC prompt.  Keeping them
# in a constant lets the test suite assert the rules are still in
# the prompt and not silently edited out.
NPC_SYSTEM_PROMPT_GUARDRAILS: Final[tuple[str, ...]] = (
    # Decision 1 — 12-action vocab
    "RULE 1: `proposedAction` MUST be one of the 12 atomic verbs "
    "(investigate / reveal / conceal / question / confront / comfort / "
    "give / destroy / promise / wait / leave / silence). NEVER free-form chat.",
    # Decision 1 — target / evidence constraints
    "RULE 2: If `proposedAction` is question / confront / give / comfort, "
    "`targetId` MUST be a non-null string from the on-stage cast. If "
    "`proposedAction` is reveal / destroy / give, `evidenceIds` MUST contain "
    "at least one artifactId from the active scene.",
    # Decision 3 — memory grounding
    "RULE 3: Every memory you reference (`referencedMemoryIds`) MUST be in "
    "the supplied recall set. Any claim about the past is ungrounded and the "
    "Resolver will reject it as `ungrounded_memory`.",
    # Decision 3 — mandatory echo allowlist
    "RULE 4: If your proposal SURFACES a past event the player experienced "
    "(NPC主动提起), the surfaced event MUST appear in the scene's "
    "`mandatory_echoes` list.  This is the decision-3 / UP-20260715-002 rule.  "
    "If your `speechIntent` is `reveal_truth` or `conceal_truth`, the "
    "referenced fact must also be in the recall set; do not invent secrets.",
    # Decision 3 — forbidden reveals
    "RULE 5: NEVER surface any information listed in the scene's "
    "`forbidden_reveals` array.  The Resolver will reject the proposal as "
    "`forbidden_reveal` and the run will be blocked.",
    # Decision 6 — four-questions
    "RULE 6: At least ONE of these four must be true for your proposal to "
    "be accepted: (a) it changes the world state (artifact / event log); "
    "(b) it changes a character's knowledge (belief matrix); (c) it changes "
    "the available actions for the rest of the scene; (d) it fires a causal "
    "seed that will echo into a future scene.  Pick the most truthful one "
    "and name it in `reasonCodes`.",
    # Decision 5 — cost
    "RULE 7: Keep the proposal short.  Token cost is monitored; outputs > 800 "
    "tokens trigger the L1 fallback (writer-authored line).  `reasonCodes` "
    "max 8; `beliefUpdatesRequested` max 16; `referencedMemoryIds` max 8.",
    # Output shape
    "OUTPUT: Emit a SINGLE JSON object that matches `npc_proposal.schema.json`. "
    "No prose before or after the JSON.  No markdown code fences.  No comments.",
)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_npc_system_prompt(
    *,
    character: CharacterCard | str,
    era: str,
    scene_contract: dict[str, Any],
    player_action: dict[str, Any],
    belief_matrix: dict[str, Any],
    recall_set: list[dict[str, Any]],
    forbidden_reveals: list[dict[str, str]],
    mandatory_echoes: list[dict[str, Any]],
    cast: list[dict[str, Any]],
) -> str:
    """Render the NPC agent system prompt.

    Parameters
    ----------
    character
        Either a :class:`CharacterCard` or a ``characterId`` string.
        Strings are looked up via :func:`get_character_card`.
    era
        The active era string.  One of the case-scoped shorts
        (``2008``/``2011``/``2024``/``EPILOGUE``) or a canonical
        Era value.
    scene_contract
        A dict with at least ``title``, ``core_conflict``,
        ``allowed_actions`` (list of action names).
    player_action
        The PlayerAction the player just submitted (used as the
        trigger context).
    belief_matrix
        The current :class:`BeliefMatrix` for ``character``, as a
        JSON-friendly dict.  Only this NPC's matrix is passed.
    recall_set
        The 4-8 memories the memory manager recalled for this
        character in the active scene.  Each item is a dict.
    forbidden_reveals
        The scene's ``forbidden_reveals`` array, verbatim.
    mandatory_echoes
        The scene's ``mandatory_echoes`` array, verbatim.
    cast
        The scene's cast list (used for `targetId` whitelist).
    """

    if isinstance(character, str):
        character = get_character_card(character)

    register = style_bible_for_era(era)
    guardrails = "\n".join(f"- {line}" for line in NPC_SYSTEM_PROMPT_GUARDRAILS)

    forbidden_lines = "\n".join(
        f"  - {fr.get('revealKey', '?')}: {fr.get('reason', '')}"
        for fr in forbidden_reveals
    ) or "  (none)"

    mandatory_lines = "\n".join(
        f"  - id={me.get('id', '?')}: {me.get('description', '')}"
        f" [target_scenes={me.get('target_scenes', [])}]"
        for me in mandatory_echoes
    ) or "  (none)"

    recall_lines = "\n".join(
        f"  - {mem.get('memoryId', '?')} "
        f"(weight={mem.get('recallWeight', 0):.2f}, "
        f"decay={mem.get('decayScore', 0):.2f}): "
        f"{mem.get('summary', '')}"
        for mem in recall_set
    ) or "  (no recalled memories for this character in this scene)"

    cast_lines = "\n".join(
        f"  - {c.get('characterId', '?')} ({c.get('role', '?')})"
        for c in cast
    ) or "  (no on-stage cast)"

    actions_line = ", ".join(scene_contract.get("allowed_actions", ())) or "(none)"

    # The prompt deliberately does NOT show the player_action's
    # `expectedEventSequence` — that's the resolver's job.
    pa_action = player_action.get("actionType", "?")
    pa_target = player_action.get("targetId") or "(none)"
    pa_evidence = ", ".join(player_action.get("evidenceIds", []) or []) or "(none)"
    pa_utterance = player_action.get("utterance", "").strip() or "(no utterance)"

    return f"""# NPC Agent · {character.displayName} ({character.characterId}) · prompt v{NPC_SYSTEM_PROMPT_VERSION}

## Identity
You are **{character.displayName}** in the narrative of 《革命街没有尽头》.
- Role in this run: {character.roleInRun}
- Age band: {character.age}
- Era(s): {character.era}
- Appearance: {character.appearance}
- Speech style: {character.speechStyle}
- Motivation (current run): {character.motivation}
- Core anchors: {', '.join(character.coreAnchors)}
- Era register: {character.eraRegister}

## Style Bible · current era = {era}
{register}

Default narrator voice: {NARRATOR_VOICE_DEFAULT}

## Active Scene
- Title: {scene_contract.get('title', scene_contract.get('sceneId', '?'))}
- SceneId: {scene_contract.get('sceneId', '?')}
- Core conflict: {scene_contract.get('core_conflict', scene_contract.get('coreConflict', '?'))}
- Allowed actions for the player: {actions_line}

### On-stage cast
{cast_lines}

## Trigger
The player just submitted a PlayerAction.  You must respond to it.
- actionType: {pa_action}
- targetId: {pa_target}
- evidenceIds: {pa_evidence}
- utterance: {pa_utterance}

## Your current belief matrix (only your layer 2 / layer 3 are shown)
```json
{belief_matrix}
```

## Recalled memories (4-8 max; the 6-step filter has already run)
{recall_lines}

## Hard rules (DO NOT BREAK)
{guardrails}

## Scene forbidden_reveals (decision 3 — these are FORBIDDEN in this scene)
{forbidden_lines}

## Scene mandatory_echoes (decision 3 / UP-20260715-002 — you may ONLY surface these past events)
{mandatory_lines}

## Decision 4 reminder
The player pays ¥25 once; AI cost per turn must stay < ¥0.04 (¥0.8/20 turns).
Be concise.  Do not pad.
"""


__all__ = [
    "NPC_SYSTEM_PROMPT_VERSION",
    "NPC_SYSTEM_PROMPT_GUARDRAILS",
    "build_npc_system_prompt",
]
