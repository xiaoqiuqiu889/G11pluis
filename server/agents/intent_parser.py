"""Intent parser — natural language → ``PlayerAction`` JSON.

The intent parser is the **only** entry point for player agency.
Per decision 1 + the player_action.schema.json, the 12-value action
vocabulary is a hard enum; the LLM is asked to map any free-form
utterance onto ONE of these 12 verbs.  Anything else fails the
schema gate and the action is rejected.

Pipeline
--------
1. The parser builds a system prompt that:
   * embeds the 12-value vocab
   * embeds the active scene's allowed_actions
   * embeds the per-action rules (target / evidence constraints)
2. It calls the :class:`ModelGateway` with JSON-mode, temperature
   0.2-0.5 (decision 5 / brief).
3. It validates the response against the JSON schema (P0-1
   ``jsonschema`` validation).  If the schema fails, it retries
   **once** with a corrective prompt; if the retry also fails, it
   falls back to a deterministic 1-action proposal (decision 5
   L3 mainline) — never a free-form chat.

4. It returns a :class:`ParsedPlayerAction` (the validated dict
   plus a confidence score).  The Resolver is the only consumer
   of this object.

Why we don't allow free-form chat
---------------------------------
The V0.1 PRD lesson 1 is explicit: "AI 自由聊天" is the failure
mode that turned the 《崇祯》prototype into a "wrapper around
a chatbot".  The intent parser makes free-form chat structurally
impossible: if the LLM emits prose, the JSON parser fails, and
the parser retries / falls back to a structured action.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import jsonschema
from typing import Final

from .model_gateway import ModelCallError, ModelGateway, ModelRequest
from .prompts import STYLE_BIBLE_VERSION
from .prompts.style_bible import style_bible_for_era


INTENT_PARSER_VERSION: Final[str] = "1.0.0"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IntentParseError(RuntimeError):
    """Raised when the parser cannot produce a valid PlayerAction.

    The 4-level degradation chain (decision 5) maps this to
    ``L3_HARD_DEGRADATION`` only after the in-parser retry has
    been exhausted; the parser itself signals a *recoverable*
    error via the :class:`ParsedPlayerAction.fallbackUsed` flag.
    """


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ParsedPlayerAction:
    """The parser's output — a validated PlayerAction + meta.

    Attributes
    ----------
    action : dict
        The validated PlayerAction JSON, ready to hand to the
        Resolver / state machine.
    confidence : float
        Agent's self-assessed confidence in the parse.
    retries : int
        How many retries the parser used (0..1; brief spec).
    fallback_used : bool
        True iff the parser fell back to a deterministic
        PlayerAction (decision 5 L3 mainline).
    raw_model_output : str
        The raw LLM payload (for the audit trail).
    """

    action: dict[str, Any]
    confidence: float = 0.8
    retries: int = 0
    fallback_used: bool = False
    raw_model_output: str = ""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class IntentParser:
    """Maps free-form player text → validated PlayerAction JSON.

    Parameters
    ----------
    gateway
        A :class:`ModelGateway` (production) or
        :class:`StubModelGateway` (tests).
    schema_path
        Path to ``player_action.schema.json``.  Defaults to the
        shipped schema at ``server/config/schemas/``.
    temperature
        Sampling temperature.  Decision 5: 0.2-0.5.  Defaults to 0.3.
    max_output_tokens
        Decision 5 hard red-line: < 800.
    """

    _SCHEMA_FILE: Final[str] = "player_action.schema.json"

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        schema_path: str | None = None,
        temperature: float = 0.3,
        max_output_tokens: int = 600,
    ) -> None:
        if not 0.2 <= temperature <= 0.5:
            raise ValueError(
                f"temperature must be in [0.2, 0.5] (decision 5 / brief); got {temperature}"
            )
        if max_output_tokens > 800:
            raise ValueError(
                f"max_output_tokens must be <= 800 (decision 5); got {max_output_tokens}"
            )
        self.gateway = gateway
        self.temperature = float(temperature)
        self.max_output_tokens = int(max_output_tokens)
        self._schema = self._load_schema(schema_path)

    # ----- public API ----------------------------------------------------

    def parse(
        self,
        *,
        run_id: str,
        scene_id: str,
        actor_id: str,
        utterance: str,
        scene_contract: dict[str, Any],
        client_action_id: str | None = None,
        expected_event_sequence: int | None = None,
        target_hint: str | None = None,
        evidence_hint: list[str] | None = None,
        tone_hint: str | None = None,
    ) -> ParsedPlayerAction:
        """Run the parser pipeline.

        Returns
        -------
        ParsedPlayerAction
            The validated PlayerAction + meta.  Never raises for
            recoverable errors; the caller (HTTP handler) can
            inspect ``fallback_used`` to know whether the parser
            dropped to the L3 mainline.
        """

        if not utterance or not utterance.strip():
            return ParsedPlayerAction(
                action=self._empty_action(
                    run_id=run_id,
                    scene_id=scene_id,
                    actor_id=actor_id,
                    client_action_id=client_action_id,
                    expected_event_sequence=expected_event_sequence,
                ),
                confidence=1.0,
                fallback_used=True,
            )

        system_prompt = self._build_system_prompt(
            scene_contract=scene_contract,
            tone_hint=tone_hint,
        )
        user_payload = {
            "runId": run_id,
            "sceneId": scene_id,
            "actorId": actor_id,
            "clientActionId": client_action_id,
            "expectedEventSequence": expected_event_sequence,
            "utterance": utterance[:500],  # hard cap per schema
            "targetHint": target_hint,
            "evidenceHint": list(evidence_hint or []),
            "toneHint": tone_hint or "neutral",
        }

        # ---- First attempt --------------------------------------------------
        try:
            raw = self._call(system_prompt, user_payload)
            return ParsedPlayerAction(
                action=self._coerce(
                    raw, run_id, scene_id, actor_id, client_action_id, expected_event_sequence
                ),
                confidence=0.9,
                retries=0,
                raw_model_output=str(raw),
            )
        except (ModelCallError, jsonschema.ValidationError, ValueError, json.JSONDecodeError) as exc:
            first_error = exc

        # ---- Single retry (brief spec) -------------------------------------
        try:
            corrective = (
                "Your previous response was invalid.  Emit a SINGLE JSON object "
                "with the EXACT field names from the player_action schema.  No "
                "prose, no markdown, no comments.  The actionType MUST be one "
                f"of: {', '.join(self._allowed_actions(scene_contract))}."
            )
            raw2 = self._call(system_prompt + "\n\n" + corrective, user_payload)
            return ParsedPlayerAction(
                action=self._coerce(
                    raw2, run_id, scene_id, actor_id, client_action_id, expected_event_sequence
                ),
                confidence=0.7,
                retries=1,
                raw_model_output=str(raw2),
            )
        except (ModelCallError, jsonschema.ValidationError, ValueError, json.JSONDecodeError) as exc:
            second_error = exc
            # ---- L3 hard degradation: deterministic fallback ---------------
            return ParsedPlayerAction(
                action=self._fallback_action(
                    run_id=run_id,
                    scene_id=scene_id,
                    actor_id=actor_id,
                    utterance=utterance,
                    client_action_id=client_action_id,
                    expected_event_sequence=expected_event_sequence,
                    target_hint=target_hint,
                ),
                confidence=0.4,
                retries=1,
                fallback_used=True,
                raw_model_output=(
                    f"[L3 fallback after retries] first={first_error!r} second={second_error!r}"
                ),
            )

    # ----- internals ------------------------------------------------------

    def _call(self, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        req = ModelRequest(
            agent="intent_parser",
            system_prompt=system_prompt,
            user_payload=user_payload,
            temperature=self.temperature,
            json_object=True,
            preferred_model="auto",
            max_output_tokens=self.max_output_tokens,
            schema_hint="player_action",
        )
        response = self.gateway.complete(req)
        if not isinstance(response.payload, dict):
            raise ValueError(
                f"gateway returned non-dict payload: {type(response.payload).__name__}"
            )
        return response.payload

    def _build_system_prompt(
        self,
        *,
        scene_contract: dict[str, Any],
        tone_hint: str | None,
    ) -> str:
        era = scene_contract.get("era", "general")
        register = style_bible_for_era(era)
        actions = self._allowed_actions(scene_contract)
        allowed_str = ", ".join(actions) if actions else "(no actions registered for this scene)"
        return (
            f"# IntentParser · v{INTENT_PARSER_VERSION}\n"
            f"# Style bible version: {STYLE_BIBLE_VERSION}\n"
            f"\n"
            f"## Active scene era: {era}\n"
            f"{register}\n"
            f"\n"
            f"## Active scene allowed_actions (12-value vocab):\n"
            f"{allowed_str}\n"
            f"\n"
            f"## Your job\n"
            f"Map the player's free-form utterance to EXACTLY ONE of the 12 "
            f"atomic actions above.  Emit a JSON object matching the "
            f"player_action schema (runId / sceneId / actionType / actorId / "
            f"optional targetId, evidenceIds, utterance, tone, "
            f"disclosureLevel, isDeceptive, clientActionId, "
            f"expectedEventSequence, clientTimestamp, schemaVersion='1.0.0').\n"
            f"\n"
            f"## Hard rules (DO NOT BREAK)\n"
            f"- actionType MUST be one of the 12 verbs.  No free-form verbs.\n"
            f"- For actionType ∈ {{question, confront, give, comfort}}: "
            f"targetId MUST be a non-null characterId from the on-stage cast.\n"
            f"- For actionType ∈ {{reveal, destroy, give}}: evidenceIds MUST "
            f"contain at least one artifactId that exists in the scene's "
            f"investigatable_objects.\n"
            f"- utterance is capped at 500 chars; do not invent new fields.\n"
            f"- tone is one of: hesitant / firm / gentle / angry / sad / playful / neutral."
            f"{'  Default: ' + tone_hint if tone_hint else ''}\n"
            f"\n"
            f"## Output\n"
            f"Emit a single JSON object.  No prose before or after.  No "
            f"markdown code fences."
        )

    @staticmethod
    def _allowed_actions(scene_contract: dict[str, Any]) -> list[str]:
        # ``allowed_actions`` is the project-side field; fall back to
        # the 12-value vocab if the scene contract didn't declare one.
        return list(scene_contract.get("allowed_actions") or [
            "investigate", "reveal", "conceal", "question", "confront",
            "comfort", "give", "destroy", "promise", "wait", "leave", "silence",
        ])

    def _coerce(
        self,
        raw: dict[str, Any],
        run_id: str,
        scene_id: str,
        actor_id: str,
        client_action_id: str | None,
        expected_event_sequence: int | None,
    ) -> dict[str, Any]:
        """Force the model's output into a schema-valid PlayerAction.

        The LLM is allowed to omit / misname fields; we correct
        the obvious ones and then validate against the schema.
        """

        action = dict(raw)
        # Required fields
        action.setdefault("runId", run_id)
        action.setdefault("sceneId", scene_id)
        action.setdefault("actorId", actor_id)
        action.setdefault("actionType", "silence")
        action.setdefault("schemaVersion", "1.0.0")
        # Optional but commonly missing
        action.setdefault("targetId", None)
        action.setdefault("evidenceIds", [])
        action.setdefault("utterance", "")
        action.setdefault("tone", "neutral")
        action.setdefault("disclosureLevel", 0.5)
        action.setdefault("isDeceptive", False)
        action.setdefault("clientTimestamp", datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
        if client_action_id is not None:
            action.setdefault("clientActionId", client_action_id)
        elif "clientActionId" not in action:
            action["clientActionId"] = str(uuid.uuid4())
        if expected_event_sequence is not None:
            action.setdefault("expectedEventSequence", int(expected_event_sequence))
        # ``schemaVersion`` must be 1.0.0; the schema enforces this.
        action["schemaVersion"] = "1.0.0"
        # Validate.  jsonschema raises on failure; the caller
        # catches it and triggers the retry / fallback.
        jsonschema.validate(action, self._schema)
        return action

    def _empty_action(
        self,
        *,
        run_id: str,
        scene_id: str,
        actor_id: str,
        client_action_id: str | None,
        expected_event_sequence: int | None,
    ) -> dict[str, Any]:
        action: dict[str, Any] = {
            "runId": run_id,
            "sceneId": scene_id,
            "actorId": actor_id,
            "actionType": "silence",
            "targetId": None,
            "evidenceIds": [],
            "utterance": "",
            "tone": "neutral",
            "disclosureLevel": 0.5,
            "isDeceptive": False,
            "clientTimestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "clientActionId": client_action_id or str(uuid.uuid4()),
            "schemaVersion": "1.0.0",
        }
        if expected_event_sequence is not None:
            action["expectedEventSequence"] = int(expected_event_sequence)
        jsonschema.validate(action, self._schema)
        return action

    def _fallback_action(
        self,
        *,
        run_id: str,
        scene_id: str,
        actor_id: str,
        utterance: str,
        client_action_id: str | None,
        expected_event_sequence: int | None,
        target_hint: str | None,
    ) -> dict[str, Any]:
        """L3 deterministic fallback — pick the safest verb.

        The brief specifies L3 = "走策划脚本（不调 LLM）".  When the
        LLM chain fails twice we emit a single ``silence`` action
        with disclosure=0 — the LLM is *not* in the loop.  This
        keeps the run moving (one turn, no state change) while
        the team investigates the prompt.
        """

        action = self._empty_action(
            run_id=run_id,
            scene_id=scene_id,
            actor_id=actor_id,
            client_action_id=client_action_id,
            expected_event_sequence=expected_event_sequence,
        )
        action["actionType"] = "silence"
        action["utterance"] = ""
        action["tone"] = "neutral"
        action["disclosureLevel"] = 0.0
        action["targetId"] = target_hint  # may be None
        # We deliberately do NOT include the raw utterance; the
        # LLM is out of the loop, the player will get a writer-
        # authored silence beat.
        return action

    @staticmethod
    def _load_schema(schema_path: str | None) -> dict[str, Any]:
        if schema_path is None:
            from pathlib import Path
            # server/agents/intent_parser.py → server/config/schemas/...
            root = Path(__file__).resolve().parents[1]  # server/
            schema_path = str(root / "config" / "schemas" / "player_action.schema.json")
        with open(schema_path, "r", encoding="utf-8") as fh:
            return json.load(fh)


__all__ = [
    "INTENT_PARSER_VERSION",
    "IntentParser",
    "IntentParseError",
    "ParsedPlayerAction",
]
