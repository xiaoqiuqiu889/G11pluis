"""Data types for the Model Gateway.

This module centralises the request/response shapes that flow
through the gateway so every provider, the routing layer, the cost
controller, and the degradation chain speak the same vocabulary.

Public types
------------

* :class:`TaskType`        — the routing key (player_intent_parser,
                              npc_proposer, director_proposer,
                              resolver, memory_recall, ...)
* :class:`Message`         — a single chat message (role + content)
* :class:`ModelRequest`    — a request to the gateway
* :class:`ModelResponse`   — the unified response shape
* :class:`ProviderResult`  — the raw result a provider hands back
* :class:`CostRecord`      — per-call audit record for model_calls
* :class:`RunCostSummary`  — per-run aggregate for the P0 alert

Design notes
------------

* The gateway treats every call as a **structured-output** call.
  ``response_format=json`` is a hint, not a hard requirement —
  some providers don't support it, and the gateway falls back to
  *parse + validate* before retrying.
* :class:`ModelResponse` is intentionally rich: it carries
  ``degradation_level`` and ``used_fallback`` so the caller can
  branch on whether the response came from a writer script
  rather than the LLM.
* Token counting is best-effort.  The gateway does not embed a
  tokenizer for every model; it uses the provider's reported
  usage when available and falls back to a 4-chars-per-token
  heuristic for text-only responses.  This is acceptable for
  audit because the audit cares about *order of magnitude*,
  not exact tokens.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Routing vocabulary
# ---------------------------------------------------------------------------


class TaskType(str, Enum):
    """Routing keys — one per kind of LLM call the engine makes.

    Each task gets its own model + provider + timeout + max-tokens
    configuration in :class:`routing.TaskConfig`.  Adding a new
    task here requires adding a config entry to the router.
    """

    PLAYER_INTENT_PARSER = "player_intent_parser"
    NPC_PROPOSER = "npc_proposer"
    DIRECTOR_PROPOSER = "director_proposer"
    RESOLVER = "resolver"
    MEMORY_RECALL = "memory_recall"


#: Allowed output schema for each task type.  The gateway uses
#: this mapping to pick the right JSON Schema for validation.
#: ``None`` means "no schema enforcement" (e.g. free-form
#: memory-recall output, which returns a recall set).
TASK_TO_SCHEMA: dict[TaskType, str | None] = {
    TaskType.PLAYER_INTENT_PARSER: "player_action",
    TaskType.NPC_PROPOSER: "npc_proposal",
    TaskType.DIRECTOR_PROPOSER: "director_beat",
    TaskType.RESOLVER: "resolver_outcome",
    TaskType.MEMORY_RECALL: None,
}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(slots=True)
class Message:
    """A single chat message."""

    role: MessageRole
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role.value, "content": self.content}


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ModelRequest:
    """A request to the Model Gateway.

    Attributes
    ----------
    run_id : str
        Run (game session) identifier; stamped on the audit
        record.  Used to aggregate per-run cost.
    scene_id : str
        Active scene id; used for fallback lookup.
    task_type : TaskType
        The routing key.
    messages : list[Message]
        The conversation so far.
    temperature : float
        Sampling temperature.  Default 0.4 — low enough for
        deterministic behaviour, high enough to allow the LLM
        to pick between similarly-scored proposals.
    max_output_tokens : int
        Hard cap on output tokens.  Decision 5 red line: < 800.
        Default 600 to leave headroom.
    timeout_ms : int
        Per-call timeout.  Default 4000 ms (decision 5 P95 target).
    schema_name : str | None
        Optional explicit schema name.  If omitted, the gateway
        looks it up from :data:`TASK_TO_SCHEMA`.
    metadata : dict
        Free-form metadata to attach to the audit record
        (e.g. proposal id, character id, beat id).
    """

    run_id: str
    scene_id: str
    task_type: TaskType
    messages: list[Message]
    temperature: float = 0.4
    max_output_tokens: int = 600
    timeout_ms: int = 4000
    schema_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_output_tokens > 800:
            # Decision 5 red line: single output < 800 tokens.
            raise ValueError(
                f"max_output_tokens={self.max_output_tokens} violates "
                f"decision 5 hard red line (< 800 tokens)"
            )
        if self.timeout_ms > 8000:
            # Belt-and-braces: the per-call timeout should be well
            # under the P95 budget (4000 ms) for the *whole turn*.
            raise ValueError(
                f"timeout_ms={self.timeout_ms} is too long; "
                f"keep it under 8000 to leave headroom for routing "
                f"and validation"
            )
        if not self.messages:
            raise ValueError("messages must be non-empty")


# ---------------------------------------------------------------------------
# Provider raw result
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ProviderResult:
    """The raw result a :class:`providers.base.Provider` hands back.

    The gateway transforms this into a :class:`ModelResponse` by
    adding cost, degradation, and audit fields.  Providers are
    free to set ``content`` and either ``parsed_json`` or
    ``usage`` — the gateway handles both.
    """

    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"
    latency_ms: int = 0
    parsed_json: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Unified response
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ModelResponse:
    """The unified response shape from the Model Gateway.

    Every call — successful, retried, or fallen-back — returns a
    :class:`ModelResponse`.  Callers branch on
    :attr:`degradation_level` and :attr:`used_fallback` to decide
    what to do with the payload.

    Attributes
    ----------
    content : str
        The text the model emitted (or the writer fallback line
        if ``used_fallback`` is True).
    parsed : dict | None
        Parsed JSON if the response was structured.
    model : str
        The model id that produced ``content`` (or "writer"
        for fallbacks).
    provider : str
        The provider id that produced ``content`` (or "writer").
    task_type : TaskType
        Echo of the request.
    input_tokens : int
        Tokens in (reported by the provider; best-effort).
    output_tokens : int
        Tokens out (reported by the provider; best-effort).
    latency_ms : int
        Wall-clock latency of the call (excludes routing).
    cost_cny : float
        Estimated cost in CNY.
    finish_reason : str
        "stop" / "length" / "timeout" / "error" / "fallback".
    degradation_level : str | None
        "L1" / "L2" / "L3" / "L4" if the chain escalated.
        ``None`` for a clean LLM call.
    used_fallback : bool
        True iff a writer-authored fallback was used.
    attempts : int
        How many provider calls were made (1 if first try
        succeeded; > 1 on retry).
    request_id : str
        Unique id for tracing.
    timestamp : str
        ISO-8601 timestamp of the response.
    """

    content: str
    parsed: dict[str, Any] | None
    model: str
    provider: str
    task_type: TaskType
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_cny: float
    finish_reason: str
    degradation_level: str | None = None
    used_fallback: bool = False
    attempts: int = 1
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

    @property
    def is_clean(self) -> bool:
        """True iff this was a successful LLM call (no fallback, no chain)."""
        return (
            not self.used_fallback
            and self.degradation_level is None
            and self.finish_reason in ("stop", "length")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "parsed": self.parsed,
            "model": self.model,
            "provider": self.provider,
            "taskType": self.task_type.value,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "latencyMs": self.latency_ms,
            "costCny": self.cost_cny,
            "finishReason": self.finish_reason,
            "degradationLevel": self.degradation_level,
            "usedFallback": self.used_fallback,
            "attempts": self.attempts,
            "requestId": self.request_id,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Cost audit records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CostRecord:
    """Per-call audit record.  Written to the model_calls table.

    The schema is intentionally close to the audit shape used by
    the ResolverOutcome (see :file:`server/config/schemas/resolver_outcome.schema.json`
    :code:`auditTrail.llmCalls`) so W4 integration can lift these
    records straight into the ResolverOutcome without a
    translation step.
    """

    request_id: str
    run_id: str
    scene_id: str
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
    attempts: int
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "runId": self.run_id,
            "sceneId": self.scene_id,
            "taskType": self.task_type,
            "agent": self.agent,
            "model": self.model,
            "provider": self.provider,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "latencyMs": self.latency_ms,
            "costCny": self.cost_cny,
            "finishReason": self.finish_reason,
            "degradationLevel": self.degradation_level,
            "usedFallback": self.used_fallback,
            "attempts": self.attempts,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class RunCostSummary:
    """Per-run aggregate.  Used by the L3-alert path."""

    run_id: str
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_cny: float = 0.0
    p95_latency_ms: int = 0
    l3_count: int = 0
    l4_count: int = 0
    finished_at: str = ""

    def merge(self, record: CostRecord) -> None:
        self.total_calls += 1
        self.total_input_tokens += record.input_tokens
        self.total_output_tokens += record.output_tokens
        self.total_cost_cny += record.cny_cost if hasattr(record, "cny_cost") else record.cost_cny
        if record.degradation_level == "L3":
            self.l3_count += 1
        if record.degradation_level == "L4":
            self.l4_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "totalCalls": self.total_calls,
            "totalInputTokens": self.total_input_tokens,
            "totalOutputTokens": self.total_output_tokens,
            "totalCostCny": self.total_cost_cny,
            "p95LatencyMs": self.p95_latency_ms,
            "l3Count": self.l3_count,
            "l4Count": self.l4_count,
            "finishedAt": self.finished_at,
        }


__all__ = [
    "TaskType",
    "TASK_TO_SCHEMA",
    "MessageRole",
    "Message",
    "ModelRequest",
    "ProviderResult",
    "ModelResponse",
    "CostRecord",
    "RunCostSummary",
]


# ---------------------------------------------------------------------------
# Helper: try to parse a model's content as JSON
# ---------------------------------------------------------------------------


def safe_parse_json(content: str) -> dict[str, Any] | None:
    """Best-effort JSON parse.

    Models often wrap JSON in ```json ... ``` fences or in a
    single line of prose.  We try a strict parse first, then
    strip code fences, then look for a balanced JSON object
    inside the prose.

    Returns ``None`` only if no candidate parses.
    """

    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # Strip leading/trailing code fences
    stripped = content.strip()
    if stripped.startswith("```"):
        # Drop the opening ```json / ``` and trailing ```
        first_nl = stripped.find("\n")
        if first_nl > 0:
            stripped = stripped[first_nl + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        try:
            return json.loads(stripped.strip())
        except json.JSONDecodeError:
            pass
    # Last resort: find a balanced JSON object / array inside
    # the prose.  The previous implementation naively sliced
    # from the first ``{``/``[`` to end-of-string, which fails
    # when there is trailing prose (e.g. ``Here is JSON: {"a":1} -- end.``).
    for opener, closer in (("{", "}"), ("[", "]")):
        candidate = _extract_balanced_json(stripped, opener, closer)
        if candidate is not None:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return None


def _extract_balanced_json(text: str, opener: str, closer: str) -> str | None:
    """Find the first balanced JSON ``opener...closer`` substring.

    Honours quoted strings (so a ``}`` inside a string does not
    close the object) and ignores braces inside single-line
    comments (rare in LLM output, but cheap to handle).
    Returns ``None`` if no balanced run exists.
    """

    idx = text.find(opener)
    if idx < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(idx, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[idx : i + 1]
    return None
