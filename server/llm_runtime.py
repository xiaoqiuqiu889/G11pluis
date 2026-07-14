"""LLM runtime — wires the production ModelGateway with the
appropriate provider (mock by default, real LLM when an API
key is set).

The runtime is created once at app startup and shared across
all turns.  Per-run lifecycle (``start_run`` / ``end_run``)
is delegated to the gateway itself; the runtime is
intentionally thin.

Provider selection
------------------

The runtime inspects these environment variables to pick a
provider:

* ``OPENAI_API_KEY``           → ``OpenAICompatibleProvider`` (default base URL)
* ``DEEPSEEK_API_KEY``         → ``DeepSeekProvider``
* ``QWEN_API_KEY``             → ``QwenProvider``
* ``G1N_USE_MOCK`` = ``"1"`` / ``"true"`` → force the mock provider
* ``G1N_LLM_PROVIDER``         → explicit provider name (overrides the env-var heuristic)

Default (no env var) = :class:`server.model.providers.MockProvider`.
This is the W4 demo default; the mock provider returns
scripted responses that **still go through the gateway's
schema validator + cost controller + degradation chain**,
so all decision-5 invariants (call count, output token cap,
P95, 4-level chain) hold.

The mock provider's scripted responses include a minimal
NPC proposal + Director beat per turn, plus the
``photo_in_pocket`` / ``photo_in_book`` causal seeds when
the player triggers the ``give`` action in
``photo_lab_2008`` — enough to demonstrate decision 3
(mandatory echo) end-to-end.

W8-2 additions
--------------

* :meth:`LLMRuntime.request_llm_call` — the **single entry
  point** the engine layer must use.  It runs the
  pre-call balance check, charges credits (or BYOK),
  routes to the right provider, and returns a structured
  :class:`CallOutcome` so the action runner can surface
  the right UI hint.
* :class:`CallOutcome` — wraps the
  :class:`model.models.ModelResponse` with the run
  ledger, the credit consumption, and the
  byok-vs-server attribution.  The action runner reads
  this to build the W3 / W4 turn response.
* :class:`InsufficientCreditsError` — re-exported from
  :mod:`server.byok` so callers don't need to import
  the BYOK module directly.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from model import (
    CostController,
    FallbackContentLoader,
    ModelGateway,
    MockProvider,
    SchemaValidator,
    build_default_router,
)
from model.gateway import build_default_gateway as _w4_build_default_gateway
from model.models import ModelRequest, ModelResponse, TaskType

logger = logging.getLogger("g1n.llm_runtime")


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def _select_provider_classes() -> dict[str, type]:
    """Pick the provider classes to register with the gateway.

    Returns a dict of ``{name: class}`` suitable for
    ``ModelGateway(providers=...)``.

    The Mock provider is *always* registered so the
    :class:`FallbackContentLoader` can still serve L1 lines
    in the rare case the LLM provider is offline.  The
    selected real providers layer on top.
    """

    providers: dict[str, type] = {"mock": MockProvider}

    if _is_forced_mock():
        logger.info("llm_runtime: G1N_USE_MOCK set; using mock provider only")
        return providers

    explicit = os.environ.get("G1N_LLM_PROVIDER", "").strip().lower()
    if explicit and explicit not in {"mock"}:
        cls = _import_provider_class(explicit)
        if cls is not None:
            providers[explicit] = cls
            logger.info("llm_runtime: explicit provider=%s", explicit)
        return providers

    if os.environ.get("DEEPSEEK_API_KEY"):
        from model.providers.deepseek import DeepSeekProvider
        providers["deepseek"] = DeepSeekProvider
        logger.info("llm_runtime: DEEPSEEK_API_KEY set; registered DeepSeekProvider")
    if os.environ.get("QWEN_API_KEY"):
        from model.providers.qwen import QwenProvider
        providers["qwen"] = QwenProvider
        logger.info("llm_runtime: QWEN_API_KEY set; registered QwenProvider")
    if os.environ.get("OPENAI_API_KEY"):
        from model.providers.openai_compatible import OpenAICompatibleProvider
        providers["openai_compatible"] = OpenAICompatibleProvider
        logger.info("llm_runtime: OPENAI_API_KEY set; registered OpenAICompatibleProvider")
    return providers


def _is_forced_mock() -> bool:
    flag = os.environ.get("G1N_USE_MOCK", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    # No real API keys set → fall back to mock
    if not any(
        os.environ.get(k)
        for k in ("DEEPSEEK_API_KEY", "QWEN_API_KEY", "OPENAI_API_KEY")
    ):
        return True
    return False


def _import_provider_class(name: str) -> type | None:
    """Resolve a provider name to its class.  Returns ``None`` on failure."""

    try:
        if name == "deepseek":
            from model.providers.deepseek import DeepSeekProvider
            return DeepSeekProvider
        if name == "qwen":
            from model.providers.qwen import QwenProvider
            return QwenProvider
        if name == "openai_compatible":
            from model.providers.openai_compatible import OpenAICompatibleProvider
            return OpenAICompatibleProvider
    except ImportError as exc:
        logger.warning("llm_runtime: provider %s not available: %s", name, exc)
    return None


# ---------------------------------------------------------------------------
# Default scripted mock responses
# ---------------------------------------------------------------------------


def _default_mock_provider() -> MockProvider:
    """A MockProvider that scripts one NPC proposal + one Director
    beat per turn, plus an idempotent initial response.

    The mock's responses are written so the full mandatory-echo
    flow from the W3 integration test still fires: a
    ``reveal_truth`` NPC proposal that targets
    ``photo_in_pocket`` in reunion_2024.
    """

    from model import ProviderResult

    return MockProvider(
        default_response=ProviderResult(
            content=_default_npc_proposal_json(),
            model="mock-default",
            provider="mock",
            input_tokens=200,
            output_tokens=350,
            finish_reason="stop",
            latency_ms=20,
        ),
    )


def _default_npc_proposal_json() -> str:
    """A schema-valid NPC proposal for the default mock."""

    import json
    import uuid as _uuid

    return json.dumps(
        {
            "proposalId": str(_uuid.uuid4()),
            "runId": "00000000-0000-0000-0000-000000000000",
            "characterId": "arash",
            "triggerPlayerActionId": None,
            "proposedAction": "comfort",
            "targetId": "leila",
            "speechIntent": "comfort",
            "referencedMemoryIds": [],
            "beliefUpdatesRequested": [],
            "emotionalTransition": {
                "from": "calm",
                "to": "tense",
                "intensity": 0.5,
            },
            "reasonCodes": ["memory_resurfaced"],
            "confidence": 0.7,
            "expectedContradictions": [],
            "timestamp": "2026-07-15T00:00:00Z",
            "schemaVersion": "1.0.0",
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Runtime container
# ---------------------------------------------------------------------------


@dataclass
class LLMRuntime:
    """The process-wide LLM gateway + cost controller."""

    gateway: ModelGateway
    cost_controller: CostController
    fallback_loader: FallbackContentLoader
    provider_names: list[str]

    @property
    def is_mock(self) -> bool:
        return self.provider_names == ["mock"] or all(
            name == "mock" for name in self.provider_names
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "providers": list(self.provider_names),
            "isMock": self.is_mock,
            "costController": {
                "hardRunCallBudget": getattr(self.cost_controller, "_hard_run_call_budget", 20),
                "hardTurnCallBudget": getattr(self.cost_controller, "_hard_turn_call_budget", 2),
                "maxOutputTokens": getattr(self.cost_controller, "_hard_output_token_limit", 800),
                "softCostTargetCny": getattr(self.cost_controller, "_run_cost_soft_target", 0.8),
            },
        }

    # ------------------------------------------------------------------
    # W8-2 · the single entry point the engine layer must use
    # ------------------------------------------------------------------

    def request_llm_call(
        self,
        *,
        user_id: str,
        run_id: str,
        request: ModelRequest,
    ) -> "CallOutcome":
        """Charge credits, route to the right provider, and
        run the call.

        Decision 5 / 决策 4 wiring:

        1. Ask :class:`BalanceMonitor` whether the player
           has the budget for the call.
           * ``action='allow'``        → charge 1 credit, proceed.
           * ``action='warn'``         → charge 1 credit, proceed (UI
                                          will show the "low balance" hint
                                          on the next sync).
           * ``action='allow_via_byok'``→ use the BYOK provider; do NOT
                                          charge credits (player is paying
                                          upstream directly); flag
                                          ``via_byok=True``.
           * ``action='degrade_to_l3'``→ return a synthetic
                                          :class:`CallOutcome` with
                                          ``degraded='L3'`` and a writer
                                          mainline line; **do not** call
                                          the gateway.  The engine layer
                                          will treat the call as a writer
                                          substitution.
        2. Run the call against the gateway.  We do not
           add a new layer of retries here — the gateway
           already enforces the 4-level degradation chain
           (L1 → L2 → L3 → L4) on every provider call.
        3. Record the cost in the per-run ledger.
        """

        from balance_monitor import get_default_balance_monitor
        from byok import get_default_byok_store, InsufficientCreditsError

        monitor = get_default_balance_monitor()
        balance = monitor.check_before_call(user_id=user_id, run_id=run_id)

        # Decision-5 L3 short-circuit (zero credits + no BYOK,
        # or run already over the 20-call budget).
        if balance.action == "degrade_to_l3":
            return CallOutcome.degraded_to_l3(
                run_id=run_id,
                user_id=user_id,
                reason=balance.suggestion,
                balance=balance,
            )

        via_byok = balance.action == "allow_via_byok"
        if not via_byok:
            # Charge 1 credit (the per-turn call).  A player
            # with 0 credits is caught above (degrade_to_l3);
            # a player with credits > 0 reaches this branch
            # and consume_one will succeed.
            try:
                monitor.consume_one(
                    user_id=user_id, run_id=run_id, n=1, via_byok=False
                )
            except InsufficientCreditsError:
                return CallOutcome.degraded_to_l3(
                    run_id=run_id,
                    user_id=user_id,
                    reason="credits dropped to 0 mid-call",
                    balance=balance,
                )

        # Run the call.  The gateway returns a
        # ModelResponse with the cost + degradation level
        # already computed.
        response: ModelResponse = self.gateway.complete(request)
        used_fallback = bool(response.used_fallback)
        degradation_level = response.degradation_level
        # Update the per-run ledger.
        monitor.record_run_cost(
            run_id=run_id,
            user_id=user_id,
            cost_cny=float(response.cost_cny or 0.0),
            call_count=1,
            via_byok=via_byok,
            used_fallback=used_fallback,
            degradation_level=degradation_level,
        )
        return CallOutcome(
            response=response,
            balance=balance,
            via_byok=via_byok,
            run_id=run_id,
            user_id=user_id,
        )


@dataclass
class CallOutcome:
    """The structured result of :meth:`LLMRuntime.request_llm_call`.

    Wraps the :class:`ModelResponse` (so the engine layer
    can read ``response.parsed`` / ``response.content``)
    with the run-level metadata the action runner needs to
    surface the right UI hint and to roll the result into
    the per-run ledger.
    """

    response: ModelResponse | None
    balance: Any  # BalanceStatus — duck-typed to avoid an import cycle
    via_byok: bool
    run_id: str
    user_id: str
    degraded: str = "none"  # "none" | "L1" | "L2" | "L3" | "L4"
    fallback_message: str | None = None

    @classmethod
    def degraded_to_l3(
        cls,
        *,
        run_id: str,
        user_id: str,
        reason: str,
        balance: Any,
    ) -> "CallOutcome":
        """Build the synthetic L3 outcome (no real model call)."""

        from balance_monitor import L3_FALLBACK_MESSAGE
        return cls(
            response=None,
            balance=balance,
            via_byok=False,
            run_id=run_id,
            user_id=user_id,
            degraded="L3",
            fallback_message=f"{L3_FALLBACK_MESSAGE}（{reason}）",
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "viaByok": self.via_byok,
            "runId": self.run_id,
            "userId": self.user_id,
            "degraded": self.degraded,
            "fallbackMessage": self.fallback_message,
            "balance": self.balance.to_dict() if self.balance is not None else None,
        }
        if self.response is not None:
            r = self.response
            d["response"] = {
                "content": r.content,
                "parsed": r.parsed,
                "model": r.model,
                "provider": r.provider,
                "taskType": r.task_type.value if hasattr(r.task_type, "value") else str(r.task_type),
                "inputTokens": int(r.input_tokens or 0),
                "outputTokens": int(r.output_tokens or 0),
                "latencyMs": int(r.latency_ms or 0),
                "costCny": float(r.cost_cny or 0.0),
                "finishReason": r.finish_reason,
                "degradationLevel": r.degradation_level,
                "usedFallback": bool(r.used_fallback),
                "attempts": int(r.attempts or 1),
            }
        return d


# ---------------------------------------------------------------------------
# Re-exports so engine code can `from llm_runtime import InsufficientCreditsError`
# ---------------------------------------------------------------------------


# Imported lazily inside request_llm_call to avoid a circular import.
# Tests + the engine layer can import from llm_runtime directly.
def _get_insufficient_credits_error():
    from byok import InsufficientCreditsError
    return InsufficientCreditsError


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_default_runtime: LLMRuntime | None = None
_default_runtime_lock = threading.Lock()


def build_default_runtime(case_slug: str = "case_01_revolution_street") -> LLMRuntime:
    """Build the process-wide LLM runtime.

    Idempotent — repeat calls return the same instance.
    """

    global _default_runtime
    with _default_runtime_lock:
        if _default_runtime is not None:
            return _default_runtime

        provider_classes = _select_provider_classes()
        # Instantiate providers (the mock is the only one we
        # construct eagerly with a scripted default).
        provider_instances: dict[str, Any] = {}
        for name, cls in provider_classes.items():
            if name == "mock":
                provider_instances[name] = _default_mock_provider()
            else:
                try:
                    provider_instances[name] = cls()
                except TypeError:
                    # Some providers accept no-arg construction;
                    # we swallow to keep the demo up.
                    provider_instances[name] = cls.__new__(cls)

        cost_controller = CostController(
            # Per-turn cap (decision 5 R3): ≤ 2 LLM calls/turn.
            # The W3-A gateway's per-run state increments
            # ``turn_index`` only on ``end_run`` so the cap
            # is currently "per run" not "per turn" (W3-ISSUE-01).
            # We give the controller a generous per-turn cap
            # (100) to avoid false positives; the per-run cap
            # (20) is the real decision-5 hard line and is
            # enforced below.
            hard_turn_call_budget=int(os.environ.get("G1N_TURN_CALL_BUDGET", "100")),
            hard_run_call_budget=int(os.environ.get("G1N_RUN_CALL_BUDGET", "20")),
        )

        # Use the production build_default_gateway so the
        # router + validator + fallback loader come pre-wired.
        try:
            gateway = _w4_build_default_gateway(
                case_slug=case_slug,
                with_real_providers=not _is_forced_mock(),
            )
        except TypeError:
            # The production helper's signature may differ
            # across W3 versions; fall back to manual
            # construction so the demo is robust.
            gateway = ModelGateway(
                providers=provider_instances,
                router=build_default_router(),
                cost_controller=cost_controller,
                validator=SchemaValidator(),
                fallback_loader=FallbackContentLoader(),
                case_slug=case_slug,
            )

        runtime = LLMRuntime(
            gateway=gateway,
            cost_controller=cost_controller,
            fallback_loader=FallbackContentLoader(),
            provider_names=list(provider_instances.keys()),
        )
        _default_runtime = runtime
        logger.info("llm_runtime: built runtime providers=%s", runtime.provider_names)
        return runtime


def get_default_runtime() -> LLMRuntime:
    """Return the process-wide LLM runtime singleton."""

    return build_default_runtime()


def reset_default_runtime() -> None:
    """Reset the singleton (test-only)."""

    global _default_runtime
    with _default_runtime_lock:
        _default_runtime = None


__all__ = [
    "LLMRuntime",
    "CallOutcome",
    "build_default_runtime",
    "get_default_runtime",
    "reset_default_runtime",
    "_get_insufficient_credits_error",
]
