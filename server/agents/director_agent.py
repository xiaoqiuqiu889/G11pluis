"""Director agent — propose the next beat from the scene contract.

The Director is the **only** component allowed to pick a beat
from the active scene's ``allowed_beats`` whitelist.  Per the
brief:

* The proposed beat must come from the whitelist (decision 1).
* ``forbiddenRevealsChecked`` must equal the contract's
  ``forbidden_reveals`` length (decision 3).
* ``allowedByContract: true`` is schema-enforced (the schema
  declares it as a ``const``).

The Director's prompt surfaces the **mandatory_echoes** so the
LLM can pick a beat that actually fires one of them — this is
the decision-3 / UP-20260715-002 mechanism, enforced by the
:class:`server.agents.resolver.ResolverAgent`.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Final

import jsonschema

from .four_questions import check_proposal_four_questions, FourQuestionsResult
from .model_gateway import ModelCallError, ModelGateway, ModelRequest
from .prompts import build_director_system_prompt


DIRECTOR_AGENT_VERSION: Final[str] = "1.0.0"


class DirectorAgentError(RuntimeError):
    """Raised when the Director cannot produce a valid beat.

    Decision 5 L2 mapping: the Resolver skips the beat-validation
    step and uses a ``beat_skip`` placeholder.  Two consecutive
    failures escalate to L3.
    """


@dataclass(slots=True)
class DirectorBeatWithMeta:
    """The Director agent's output."""

    proposal: dict[str, Any]
    four_questions: FourQuestionsResult
    recall_echoes: list[dict[str, Any]]


class DirectorAgent:
    """Director beat selector.

    Parameters
    ----------
    gateway
        The :class:`ModelGateway` to call.
    schema_path
        Path to ``director_beat.schema.json``.  Defaults to the
        shipped schema.
    temperature
        Director is more deterministic than NPC: 0.2-0.4.
    """

    _SCHEMA_FILE: Final[str] = "director_beat.schema.json"

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        schema_path: str | None = None,
        temperature: float = 0.3,
    ) -> None:
        if not 0.2 <= temperature <= 0.4:
            raise ValueError(
                f"Director temperature must be in [0.2, 0.4]; got {temperature}"
            )
        self.gateway = gateway
        self.temperature = float(temperature)
        self._schema = self._load_schema(schema_path)

    # ----- public API ----------------------------------------------------

    def propose(
        self,
        *,
        run_id: str,
        scene_contract: dict[str, Any],
        player_action: dict[str, Any],
        fired_anchors: list[str] | None = None,
        fired_beats: list[str] | None = None,
        elapsed_turns_in_scene: int = 0,
        actions_spent_in_scene: int = 0,
        recall_echoes: list[dict[str, Any]] | None = None,
        npc_proposal: dict[str, Any] | None = None,
        trigger_player_action_id: str | None = None,
    ) -> DirectorBeatWithMeta:
        """Run the Director pipeline.

        Raises
        ------
        DirectorAgentError
            The agent could not produce a valid beat after a single
            retry.  The Resolver drops to L2 (skip beat validation).
        """

        fired_anchors = list(fired_anchors or [])
        fired_beats = list(fired_beats or [])
        recall_echoes = list(recall_echoes or [])

        system_prompt = build_director_system_prompt(
            era=scene_contract.get("era", "general"),
            scene_contract=scene_contract,
            player_action=player_action,
            fired_anchors=fired_anchors,
            fired_beats=fired_beats,
            elapsed_turns_in_scene=elapsed_turns_in_scene,
            actions_spent_in_scene=actions_spent_in_scene,
            recall_echoes=recall_echoes,
        )

        user_payload = {
            "runId": run_id,
            "sceneId": scene_contract.get("sceneId", "?"),
            "triggerPlayerActionId": trigger_player_action_id or player_action.get("clientActionId"),
            "firedAnchors": list(fired_anchors),
            "firedBeats": list(fired_beats),
            "elapsedTurnsInScene": int(elapsed_turns_in_scene),
            "actionsSpentInScene": int(actions_spent_in_scene),
            "recallEchoes": recall_echoes,
            "npcProposal": npc_proposal,
        }

        last_err: Exception | None = None
        for attempt in (0, 1):
            try:
                raw = self._call(system_prompt, user_payload, corrective=attempt == 1)
                # Inject required fields
                raw.setdefault("proposalId", str(uuid.uuid4()))
                raw.setdefault("runId", run_id)
                raw.setdefault("sceneId", scene_contract.get("sceneId", "?"))
                raw.setdefault("schemaVersion", "1.0.0")
                raw.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
                # Schema enforces multipleOf=0.05 on
                # pacingPressure / expectedTensionDelta (when
                # present).  Snap defensively to dodge the LLM's
                # float precision issues (e.g. 0.6 / 0.05 isn't a
                # clean integer under IEEE-754).
                from .npc_agent import _snap_to_quantum  # shared helper
                _snap_to_quantum(raw, "pacingPressure", 0.05)
                _snap_to_quantum(raw, "expectedTensionDelta", 0.05)
                # Sanity: the beat must be in the whitelist.
                whitelist = {
                    b.get("beatId") for b in scene_contract.get("allowed_beats", []) or []
                }
                if raw.get("proposedBeat") not in whitelist:
                    raise DirectorAgentError(
                        f"Director proposed beat {raw.get('proposedBeat')!r} "
                        f"not in allowed_beats whitelist"
                    )
                # Sanity: forbiddenRevealsChecked length must equal
                # the contract's forbidden_reveals length.
                expected = len(scene_contract.get("forbidden_reveals", []) or [])
                if len(raw.get("forbiddenRevealsChecked", []) or []) != expected:
                    raise DirectorAgentError(
                        f"forbiddenRevealsChecked length "
                        f"{len(raw.get('forbiddenRevealsChecked', []) or [])} != contract {expected}"
                    )
                # Schema-validate
                jsonschema.validate(raw, self._schema)
                # Four-questions self-check
                fq = check_proposal_four_questions(
                    raw,
                    scene_contract=scene_contract,
                    budget_delta={
                        scene_contract.get("sceneId", "?"): 1,
                    },
                )
                if not fq.passes:
                    # The director's "beat" itself changes the
                    # available actions (Q3) and may fire a seed
                    # (Q4).  If neither, the beat is inert and we
                    # reject.
                    raise DirectorAgentError(
                        f"Director beat failed 4-questions self-check: {fq.summary}"
                    )
                return DirectorBeatWithMeta(
                    proposal=raw,
                    four_questions=fq,
                    recall_echoes=recall_echoes,
                )
            except (ModelCallError, jsonschema.ValidationError, ValueError, json.JSONDecodeError, DirectorAgentError) as exc:
                last_err = exc
                continue
        raise DirectorAgentError(
            f"Director failed after retry: {type(last_err).__name__}: {last_err}"
        )

    # ----- internals ------------------------------------------------------

    def _call(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        *,
        corrective: bool,
    ) -> dict[str, Any]:
        prompt = system_prompt
        if corrective:
            prompt += (
                "\n\nCORRECTION: Your previous response was invalid.  Emit a "
                "SINGLE JSON object matching director_beat.schema.json.  "
                "No prose, no markdown, no comments.  `proposedBeat` MUST be "
                "one of the `allowed_beats` IDs above.  "
                "`forbiddenRevealsChecked` MUST list every `revealKey` from "
                "the scene's `forbidden_reveals` (one entry per revealKey)."
            )
        req = ModelRequest(
            agent="director_agent",
            system_prompt=prompt,
            user_payload=user_payload,
            temperature=self.temperature,
            json_object=True,
            preferred_model="auto",
            max_output_tokens=600,
            schema_hint="director_beat",
        )
        response = self.gateway.complete(req)
        if not isinstance(response.payload, dict):
            raise ValueError(
                f"gateway returned non-dict payload: {type(response.payload).__name__}"
            )
        return response.payload

    @staticmethod
    def _load_schema(schema_path: str | None) -> dict[str, Any]:
        if schema_path is None:
            from pathlib import Path
            root = Path(__file__).resolve().parents[1]
            schema_path = str(root / "config" / "schemas" / "director_beat.schema.json")
        with open(schema_path, "r", encoding="utf-8") as fh:
            return json.load(fh)


__all__ = [
    "DIRECTOR_AGENT_VERSION",
    "DirectorAgent",
    "DirectorAgentError",
    "DirectorBeatWithMeta",
]
