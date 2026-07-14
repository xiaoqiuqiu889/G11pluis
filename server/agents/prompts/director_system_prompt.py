"""Director agent system prompt — the guardrailed beat selector.

The Director picks **one** beat from the scene contract's
``allowed_beats`` whitelist.  It must:

* respect the whitelist (decision 1: 决策1 = 行为门槛)
* check every ``forbidden_reveals`` entry (decision 3)
* check the ``mandatory_echoes`` for which beats the player has
  already triggered (decision 3)
* keep its output in the ``director_beat.schema.json`` shape
* mark ``allowedByContract: true`` (the schema enforces this as a
  ``const`` — forgetting it is a hard reject).

The output is a single JSON object; the prompt explicitly forbids
prose or markdown.
"""

from __future__ import annotations

from typing import Any, Final

from .style_bible import NARRATOR_VOICE_DEFAULT, style_bible_for_era


DIRECTOR_SYSTEM_PROMPT_VERSION: Final[str] = "1.0.0"


DIRECTOR_SYSTEM_PROMPT_GUARDRAILS: Final[tuple[str, ...]] = (
    # Whitelist
    "RULE 1: `proposedBeat` MUST be one of the `allowed_beats` IDs in the "
    "active scene contract.  Any other value is rejected as "
    "`violates_contract`.  The schema enforces `allowedByContract: true`; "
    "you MUST set it to true and the Resolver independently re-checks.",
    # Forbidden reveals
    "RULE 2: `forbiddenRevealsChecked` MUST list every `revealKey` from "
    "the scene's `forbidden_reveals` array.  Length mismatch is a hard reject.",
    # Mandatory echoes
    "RULE 3: For every past player behaviour that the player's scene would "
    "echo (NPC 主动提起), the beat you select MUST be one of the "
    "`mandatory_echoes`'s allowed targets.  The Resolver will reject the "
    "beat if the echo it would surface is not in the mandatory list.",
    # Phase pressure
    "RULE 4: `pacingPressure` is a float in [0, 1].  If the proposed beat is "
    "tier='climax' or 'resolution' AND `pacingPressure` < 0.7, the Resolver "
    "downgrades the tier; do not pretend a soft beat is a climax.",
    # Tiering
    "RULE 5: Beats follow the tier ladder setup → rising → climax → falling "
    "→ resolution.  You may skip a tier only if the scene's "
    "`elapsedTurnsInScene` is >= 5 AND the previous beat's tier was not "
    "climax.",
    # Cost
    "RULE 6: `reasoning` 10-1000 chars; `involvedCharacterIds` max 16; "
    "`firedCausalSeeds` max 8.  Outputs > 800 tokens trigger L2 fallback.",
    # Output shape
    "OUTPUT: Single JSON object matching `director_beat.schema.json`.  No "
    "prose before or after.  No markdown code fences.",
)


def build_director_system_prompt(
    *,
    era: str,
    scene_contract: dict[str, Any],
    player_action: dict[str, Any],
    fired_anchors: list[str],
    fired_beats: list[str],
    elapsed_turns_in_scene: int,
    actions_spent_in_scene: int,
    recall_echoes: list[dict[str, Any]],
) -> str:
    """Render the Director agent system prompt.

    Parameters
    ----------
    era
        Active era string.
    scene_contract
        Scene narrative contract — must include ``allowed_beats``,
        ``forbidden_reveals``, ``required_anchors``,
        ``legal_endings``, ``mandatory_echoes``.
    player_action
        The PlayerAction that just came in (trigger context).
    fired_anchors
        Anchor IDs already hit in this scene.
    fired_beats
        Beat IDs already fired in this scene (for tier pressure).
    elapsed_turns_in_scene, actions_spent_in_scene
        Director-state bookkeeping.
    recall_echoes
        A list of *resolved* mandatory-echo entries the memory
        manager surfaced; the Director must pick a beat that
        surfaces at least one of these.
    """

    register = style_bible_for_era(era)
    guardrails = "\n".join(f"- {line}" for line in DIRECTOR_SYSTEM_PROMPT_GUARDRAILS)

    beats_lines = "\n".join(
        f"  - id={b.get('beatId', '?')} tier={b.get('tier', '?')} "
        f"label={b.get('label', '?')!r} "
        f"tension_delta={b.get('tensionDelta', 0):+.2f} "
        f"prereq={b.get('prerequisites', [])}"
        for b in scene_contract.get("allowed_beats", [])
    ) or "  (none)"

    forbidden_lines = "\n".join(
        f"  - {fr.get('revealKey', '?')}: {fr.get('reason', '')}"
        for fr in scene_contract.get("forbidden_reveals", [])
    ) or "  (none)"

    mandatory_lines = "\n".join(
        f"  - id={me.get('id', '?')}: {me.get('description', '')}"
        f" [target_scenes={me.get('target_scenes', [])}, "
        f"ai_director_must_invoke={me.get('ai_director_must_invoke', False)}]"
        for me in scene_contract.get("mandatory_echoes", [])
    ) or "  (no mandatory echoes registered)"

    anchors_lines = "\n".join(
        f"  - id={a.get('anchorId', '?')} mandatory={a.get('mandatory', True)}"
        f" desc={a.get('description', '')}"
        for a in scene_contract.get("required_anchors", [])
    ) or "  (none)"

    endings_lines = "\n".join(
        f"  - id={e.get('endingId', '?')} label={e.get('label', '?')!r}"
        for e in scene_contract.get("legal_endings", [])
    ) or "  (none)"

    echo_lines = "\n".join(
        f"  - {e.get('id', '?')}: {e.get('description', '')}"
        for e in recall_echoes
    ) or "  (no past echoes surfaced this turn)"

    pa_action = player_action.get("actionType", "?")
    pa_target = player_action.get("targetId") or "(none)"

    return f"""# Director Agent · prompt v{DIRECTOR_SYSTEM_PROMPT_VERSION}

## Style Bible · current era = {era}
{register}

Default narrator voice: {NARRATOR_VOICE_DEFAULT}

## Active Scene
- Title: {scene_contract.get('title', scene_contract.get('sceneId', '?'))}
- SceneId: {scene_contract.get('sceneId', '?')}
- Core conflict: {scene_contract.get('core_conflict', scene_contract.get('coreConflict', '?'))}
- elapsedTurnsInScene: {elapsed_turns_in_scene}
- actionsSpentInScene: {actions_spent_in_scene}

### Allowed beats (whitelist)
{beats_lines}

### Required anchors
{anchors_lines}

### Forbidden reveals (decision 3)
{forbidden_lines}

### Mandatory echoes (decision 3 / UP-20260715-002)
{mandatory_lines}

### Legal endings
{endings_lines}

### Already fired
- Beats: {fired_beats}
- Anchors: {fired_anchors}

## Trigger
- Player action: {pa_action} (target={pa_target})

## Past echoes surfaced this turn (the memory manager ran the 6-step filter)
{echo_lines}

## Hard rules (DO NOT BREAK)
{guardrails}

## Decision 4 reminder
¥25 per pass.  Director call counts toward the 20-call / 30-45 min cap.
Be decisive.  Pick ONE beat.  Do not hedge.
"""


__all__ = [
    "DIRECTOR_SYSTEM_PROMPT_VERSION",
    "DIRECTOR_SYSTEM_PROMPT_GUARDRAILS",
    "build_director_system_prompt",
]
