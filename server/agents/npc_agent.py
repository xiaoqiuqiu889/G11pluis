"""NPC agent — propose a reaction to a PlayerAction.

For every on-stage NPC, the Resolver calls :class:`NpcAgent` once
per turn.  The agent:

1. Recalls 4-8 memories for the NPC (via :class:`MemoryManager`).
2. Builds the system prompt from
   :func:`server.agents.prompts.build_npc_system_prompt`.
3. Calls the model gateway (JSON-mode, temperature 0.3-0.5).
4. Validates the response against ``npc_proposal.schema.json``.
5. Runs the four-questions self-check (decision 6).
6. Returns the proposal dict + meta.  The Resolver merges it.

Per the brief:

* One prompt per NPC (character card + personality + current state).
* Memory recall is integrated (4-8 high-value memories).
* Temperature 0.3-0.5 (decision 5 / brief).
* Every proposal must hit at least one of the four legs.
* The agent does NOT write to canonical state — it emits a
  proposal that the Resolver validates.

Decision 3 (mandatory echo) is enforced *at the Resolver* (the
NPC agent does not have a reliable way to detect "is this an
echo?" — that's the Resolver's job).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Final

import jsonschema

from .four_questions import check_proposal_four_questions, FourQuestionsResult
from .memory_manager import MemoryManager, MemoryRecall
from .model_gateway import ModelCallError, ModelGateway, ModelRequest
from .prompts import build_npc_system_prompt
from .prompts.character_card import get_character_card


NPC_AGENT_VERSION: Final[str] = "1.0.0"


class NpcAgentError(RuntimeError):
    """Raised by the NPC agent on irrecoverable failure.

    Decision 5 L1 mapping: this becomes the L1 fallback (the
    writer-authored NPCFallbackLine).  The Resolver passes the
    fallback line through to the snapshot, so the player still
    gets a meaningful turn.
    """


@dataclass(slots=True)
class NpcProposalWithMeta:
    """The NPC agent's output.

    Attributes
    ----------
    proposal : dict
        The :class:`NpcProposal` JSON, validated against the schema.
    four_questions : FourQuestionsResult
        The result of the four-questions self-check.
    recall : MemoryRecall
        The memory recall set the agent used.
    """

    proposal: dict[str, Any]
    four_questions: FourQuestionsResult
    recall: MemoryRecall


class NpcAgent:
    """Per-NPC proposal generator.

    Parameters
    ----------
    gateway
        The :class:`ModelGateway` to call.
    memory_manager
        The :class:`MemoryManager` for the 6-step recall.
    schema_path
        Path to ``npc_proposal.schema.json``.  Defaults to the
        shipped schema.
    temperature
        Decision 5: 0.3-0.5.  Default 0.4.
    """

    _SCHEMA_FILE: Final[str] = "npc_proposal.schema.json"

    def __init__(
        self,
        gateway: ModelGateway,
        memory_manager: MemoryManager,
        *,
        schema_path: str | None = None,
        temperature: float = 0.4,
    ) -> None:
        if not 0.3 <= temperature <= 0.5:
            raise ValueError(
                f"temperature must be in [0.3, 0.5] (decision 5 / brief); got {temperature}"
            )
        self.gateway = gateway
        self.memory = memory_manager
        self.temperature = float(temperature)
        self._schema = self._load_schema(schema_path)

    # ----- public API ----------------------------------------------------

    def propose(
        self,
        *,
        run_id: str,
        character_id: str,
        scene_contract: dict[str, Any],
        player_action: dict[str, Any],
        belief_matrix: dict[str, Any] | None = None,
        secrets: list[dict[str, Any]] | None = None,
        character_knowledge: set[str] | None = None,
        cast: list[dict[str, Any]] | None = None,
        trigger_player_action_id: str | None = None,
        current_event_sequence: int = 0,
        scene_id: str | None = None,
    ) -> NpcProposalWithMeta:
        """Run the NPC pipeline.

        Raises
        ------
        NpcAgentError
            The agent could not produce a valid proposal even after
            a single retry.  The caller (Resolver) should drop to
            the L1 fallback line.
        """

        scene_id = scene_id or scene_contract.get("sceneId") or player_action.get("sceneId", "?")

        # 1. Recall
        recall_query = self._build_recall_query(
            character_id=character_id,
            player_action=player_action,
            scene_contract=scene_contract,
        )
        recall = self.memory.recall_for(
            character_id=character_id,
            query=recall_query,
            scene_id=scene_id,
            current_event_sequence=current_event_sequence,
            belief_matrix=belief_matrix,
            secrets=secrets,
            character_knowledge=character_knowledge,
        )

        # 2. Build system prompt
        try:
            card = get_character_card(character_id)
        except KeyError as exc:
            raise NpcAgentError(str(exc))

        forbidden_reveals = list(scene_contract.get("forbidden_reveals") or [])
        mandatory_echoes = list(scene_contract.get("mandatory_echoes") or [])
        cast = list(cast or scene_contract.get("cast") or [])

        system_prompt = build_npc_system_prompt(
            character=card,
            era=scene_contract.get("era", "general"),
            scene_contract=scene_contract,
            player_action=player_action,
            belief_matrix=belief_matrix or {"character_knowledge": [], "character_memories": []},
            recall_set=recall.memories,
            forbidden_reveals=forbidden_reveals,
            mandatory_echoes=mandatory_echoes,
            cast=cast,
        )

        # 3. Call the gateway (with one retry on validation failure)
        user_payload = {
            "runId": run_id,
            "sceneId": scene_id,
            "characterId": character_id,
            "triggerPlayerActionId": trigger_player_action_id or player_action.get("clientActionId"),
            "recallMemoryIds": sorted(recall.memory_ids),
        }
        last_err: Exception | None = None
        for attempt in (0, 1):
            try:
                raw = self._call(
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    corrective=attempt == 1,
                )
                # Inject required runId / proposalId / characterId
                # / schemaVersion in case the LLM omitted them.
                raw.setdefault("proposalId", str(uuid.uuid4()))
                raw.setdefault("runId", run_id)
                raw.setdefault("characterId", character_id)
                raw.setdefault("triggerPlayerActionId", user_payload["triggerPlayerActionId"])
                raw.setdefault("schemaVersion", "1.0.0")
                raw.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
                # Schema enforces multipleOf=0.05 on confidence /
                # emotionalTransition.intensity.  Snap defensively to
                # dodge the LLM's float precision issues.
                _snap_to_quantum(raw, "confidence", 0.05)
                for bu in raw.get("beliefUpdatesRequested") or []:
                    _snap_to_quantum(bu, "confidence", 0.05)
                et = raw.get("emotionalTransition")
                if isinstance(et, dict):
                    _snap_to_quantum(et, "intensity", 0.05)
                # Validate schema
                jsonschema.validate(raw, self._schema)
                # 4. Four-questions self-check
                fq = check_proposal_four_questions(
                    raw,
                    scene_contract=scene_contract,
                )
                if not fq.passes:
                    raise NpcAgentError(
                        f"NPC proposal failed 4-questions self-check: {fq.summary}"
                    )
                # Verify referenced memories are in the recall set
                bad_refs = [
                    m for m in raw.get("referencedMemoryIds", [])
                    if m not in recall.memory_ids
                ]
                if bad_refs:
                    # Drop them; the schema enforces this but a
                    # misbehaving LLM might emit them anyway.
                    raw["referencedMemoryIds"] = [
                        m for m in raw.get("referencedMemoryIds", [])
                        if m in recall.memory_ids
                    ]
                return NpcProposalWithMeta(
                    proposal=raw,
                    four_questions=fq,
                    recall=recall,
                )
            except (ModelCallError, jsonschema.ValidationError, ValueError, json.JSONDecodeError) as exc:
                last_err = exc
                continue
        raise NpcAgentError(
            f"NPC agent failed after retry: {type(last_err).__name__}: {last_err}"
        )

    # ----- internals ------------------------------------------------------

    def _call(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        corrective: bool,
    ) -> dict[str, Any]:
        prompt = system_prompt
        if corrective:
            prompt += (
                "\n\nCORRECTION: Your previous response was invalid JSON or "
                "failed the schema.  Emit a SINGLE JSON object matching "
                "npc_proposal.schema.json.  No prose, no markdown, no comments."
            )
        req = ModelRequest(
            agent="npc_agent",
            system_prompt=prompt,
            user_payload=user_payload,
            temperature=self.temperature,
            json_object=True,
            preferred_model="auto",
            max_output_tokens=800,
            schema_hint="npc_proposal",
        )
        response = self.gateway.complete(req)
        if not isinstance(response.payload, dict):
            raise ValueError(
                f"gateway returned non-dict payload: {type(response.payload).__name__}"
            )
        return response.payload

    @staticmethod
    def _build_recall_query(
        *,
        character_id: str,
        player_action: dict[str, Any],
        scene_contract: dict[str, Any],
    ) -> str:
        bits: list[str] = [character_id]
        if player_action.get("actionType"):
            bits.append(str(player_action["actionType"]))
        if player_action.get("targetId"):
            bits.append(f"target={player_action['targetId']}")
        if player_action.get("utterance"):
            bits.append(str(player_action["utterance"])[:120])
        if scene_contract.get("title"):
            bits.append(str(scene_contract["title"]))
        return " | ".join(bits)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snap_to_quantum(target: dict[str, Any], field: str, quantum: float) -> None:
    """Snap ``target[field]`` to the nearest multiple of ``quantum``.

    The NPC / Director schemas declare ``multipleOf=0.05`` on
    confidence / intensity fields; the LLM occasionally emits
    values like 0.6 whose float representation is slightly off
    (0.5999999...) and which then fail schema validation.  This
    helper rounds via :class:`decimal.Decimal` to dodge the
    precision trap.  Only snaps when the field is present and
    numeric; leaves the dict unchanged otherwise.
    """

    if field not in target:
        return
    value = target[field]
    if not isinstance(value, (int, float)):
        return
    from decimal import Decimal, ROUND_HALF_UP
    d_value = Decimal(str(value))
    d_q = Decimal(str(quantum))
    snapped = (d_value / d_q).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    target[field] = float(snapped * d_q)


class _NpcAgentSchemaLoader:  # pragma: no cover — placeholder
    pass


# Re-define the class method that was displaced by the helper
# (kept in a single class block above).  The actual binding
# happens at class-definition time below.
def _load_npc_proposal_schema(schema_path: str | None) -> dict[str, Any]:
    if schema_path is None:
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        schema_path = str(root / "config" / "schemas" / "npc_proposal.schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# Bind as a class method on NpcAgent.
NpcAgent._load_schema = staticmethod(_load_npc_proposal_schema)


__all__ = [
    "NPC_AGENT_VERSION",
    "NpcAgent",
    "NpcAgentError",
    "NpcProposalWithMeta",
]
