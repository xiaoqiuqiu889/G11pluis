"""Model gateway — the LLM-call boundary.

This module defines the **interface** the agents use to call an
LLM.  The W3-A session ships the production gateway
(``server.model.gateway.ModelGateway``); for the W3-B tests we
need a deterministic stub that the agents can call without
network / cost.

Why an interface
----------------
* The agents are testable without an LLM in the loop.
* Decision 5's 4-level degradation chain can be exercised end-to-end
  by injecting a gateway that raises :exc:`ModelCallError` /
  :exc:`asyncio.TimeoutError`.
* The Resolver's mandatory_echo logic is a *deterministic* check
  that does not depend on the LLM at all; the stub can be
  hard-coded.

The contract
------------
:class:`ModelGateway` is a single method,
:meth:`ModelGateway.complete`, that takes a :class:`ModelRequest`
and returns a :class:`ModelResponse`.  The request carries the
prompt, the agent's name, the requested temperature, the JSON-mode
flag, and the agent's model preference.  The response carries the
JSON payload, the model name used, the input/output token counts,
and the latency in milliseconds — all of which the
:class:`server.agents.resolver.ResolverAgent` records in the
``auditTrail.llmCalls`` field of the :class:`ResolverOutcome`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ModelCallError(RuntimeError):
    """Raised by a ModelGateway when a call fails irrecoverably.

    The 4-level degradation chain (decision 5) maps this to
    ``L1_NPC_TIMEOUT`` / ``L2_DIRECTOR_TIMEOUT`` / ``L3_HARD_DEGRADATION``
    depending on the call site and the consecutive-failure count.
    """


@dataclass(slots=True)
class ModelRequest:
    """A single LLM call.

    Attributes
    ----------
    agent : str
        One of ``"intent_parser"``, ``"npc_agent"``, ``"director_agent"``.
    system_prompt : str
        The system prompt the agent built.
    user_payload : dict
        The JSON-serialisable user-side context (player action, etc.).
    temperature : float
        Sampling temperature.  Decision 5 / brief: 0.2-0.5 for the
        intent parser, 0.3-0.5 for the NPC agent.
    json_object : bool
        When true, the gateway requests JSON-mode (or its equivalent)
        so the model is forced to emit a single JSON object.
    preferred_model : str
        Hint for routing; production gateway may ignore.  The stub
        honours it for record-keeping.
    max_output_tokens : int
        Hard cap.  Decision 5 hard-red-line: < 800.  The stub
        silently truncates beyond this.
    schema_hint : str | None
        When given, the stub uses the schema name to look up a
        canned response.  Production gateways can ignore.
    """

    agent: str
    system_prompt: str
    user_payload: dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.3
    json_object: bool = True
    preferred_model: str = "auto"
    max_output_tokens: int = 800
    schema_hint: str | None = None


@dataclass(slots=True)
class ModelResponse:
    """A gateway's response to a :class:`ModelRequest`."""

    payload: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    raw_text: str = ""


@runtime_checkable
class ModelGateway(Protocol):
    """The interface every LLM gateway must satisfy."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Run one LLM call and return its structured result.

        Implementations **MUST**:

        * raise :exc:`ModelCallError` on irrecoverable failure
        * never silently swallow JSON-parse errors — the caller
          (intent_parser, npc_agent, director_agent) handles them
        * honour ``max_output_tokens`` (decision 5 hard red-line)
        * honour ``json_object=True`` — when set, the returned
          ``payload`` must be a JSON object (not a string)
        """


# ---------------------------------------------------------------------------
# Stub gateway
# ---------------------------------------------------------------------------


class StubModelGateway:
    """Deterministic in-memory gateway for unit tests.

    The stub takes a ``canned_responses`` dict keyed by
    ``(agent, schema_hint)`` tuples; if the tuple is not present
    it returns a small "no-op" payload.  This is enough for the
    W3-B tests to exercise the full agent pipeline without
    network / cost.

    The stub **does not** simulate the LLM's text-generation
    behaviour — it only validates the structural contract (the
    JSON shape, the token count, the latency).  A production
    gateway does the real generation.
    """

    def __init__(
        self,
        canned_responses: dict[tuple[str, str | None], dict[str, Any]] | None = None,
        *,
        latency_ms: int = 5,
    ) -> None:
        self._canned = dict(canned_responses or {})
        self._latency = int(latency_ms)

    def register(self, agent: str, schema_hint: str | None, payload: dict[str, Any]) -> None:
        self._canned[(agent, schema_hint)] = dict(payload)

    def complete(self, request: ModelRequest) -> ModelResponse:
        # Simulate wall-clock latency for the audit trail.
        # The stub is in-process; we record the time even if we
        # don't actually sleep (sleeping in tests would slow CI).
        start = time.monotonic()
        key = (request.agent, request.schema_hint)
        if key not in self._canned:
            # Fall back to (agent, None) so tests can register
            # a single shape per agent.
            fallback_key = (request.agent, None)
            payload = dict(self._canned.get(fallback_key, {}))
        else:
            payload = dict(self._canned[key])
        # The stub approximates input / output tokens by
        # character counts (a real gateway would call a tokenizer).
        approx_in = max(1, len(request.system_prompt) // 4 + sum(
            len(str(v)) for v in request.user_payload.values()
        ) // 4)
        approx_out = max(1, len(str(payload)) // 4)
        approx_out = min(approx_out, request.max_output_tokens)
        elapsed_ms = max(1, int((time.monotonic() - start) * 1000) + self._latency)
        return ModelResponse(
            payload=payload,
            model=request.preferred_model or "stub",
            input_tokens=approx_in,
            output_tokens=approx_out,
            latency_ms=elapsed_ms,
            raw_text=str(payload),
        )


__all__ = [
    "ModelGateway",
    "ModelRequest",
    "ModelResponse",
    "ModelCallError",
    "StubModelGateway",
]
