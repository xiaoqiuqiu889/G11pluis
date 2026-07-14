"""The Model Gateway — the single entry point for LLM calls.

The :class:`ModelGateway` is the only object the rest of the
server talks to.  It owns:

* the **provider registry** (one provider per LLM backend)
* the **router** (per-task model + provider config)
* the **schema validator** (compliance with the 8 engine schemas)
* the **cost controller** (per-call audit + per-run cap + P0 alert)
* the **degradation chain** (per-run, monotonic, 4-level)
* the **fallback content loader** (writer-authored fallbacks)

The public surface is small:

* :meth:`complete` — structured-output call (validates against
  the schema for the task type)
* :meth:`chat` — raw chat call (no schema validation, no parse)
* :meth:`start_run` / :meth:`end_run` — lifecycle hooks for the
  degradation chain + P0 alert
* :meth:`run_summary` — read the current run's cost aggregate

Lifecycle
---------

The gateway is created once at app startup.  Each run gets a
:class:`degradation.ModelDegradationChain` via ``start_run``.
The run ends with ``end_run``, which finalises the cost summary
and fires the P0 alert if 3 consecutive L3-degraded runs have
been observed.

Schema validation
-----------------

For tasks with a schema mapping
(:data:`models.TASK_TO_SCHEMA`), the gateway validates the
parsed JSON against the schema.  If validation fails, the
gateway retries the call *once* (decision 5 acceptance
criteria).  If the second attempt also fails, the gateway
escalates the degradation chain — the response that comes back
is the writer-authored fallback content for the task.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .cost_control import CostController, make_cost_record
from .degradation import (
    ModelDegradationChain,
    ModelFallbackContent,
    WriterPayload,
    run_with_chain,
    trigger_l1,
    trigger_l2,
    trigger_l3,
    trigger_l4,
)
from .exceptions import (
    BudgetExceededError,
    DegradationEscalatedError,
    OutputTokenLimitExceededError,
    PersistFailureError,
    ProviderTimeoutError,
    SchemaValidationError,
)
from .fallback_loader import FallbackContentLoader
from .models import (
    CostRecord,
    Message,
    ModelRequest,
    ModelResponse,
    ProviderResult,
    RunCostSummary,
    TaskType,
    safe_parse_json,
)
from .providers.base import Provider
from .routing import ModelRoute, TaskConfig, TaskRouter
from .schema_compliance import SchemaValidator


# ---------------------------------------------------------------------------
# Per-run state
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _RunState:
    run_id: str
    chain: ModelDegradationChain
    fallback: ModelFallbackContent
    turn_index: int = 0
    ended: bool = False


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


class ModelGateway:
    """The unified LLM entry point.

    Parameters
    ----------
    providers
        Mapping of provider name → :class:`Provider` instance.
        Names must match the names used in the routing config.
    router
        :class:`TaskRouter` used to pick (provider, model) per
        task.  Defaults to the recommended configuration.
    cost_controller
        :class:`CostController` for per-call audit + per-run cap
        + P0 alert.  Defaults to a fresh instance.
    validator
        :class:`SchemaValidator` for the 8 engine schemas.
        Defaults to a fresh instance pointing at the project
        schema dir.
    fallback_loader
        :class:`FallbackContentLoader` for writer content.
        Defaults to a fresh instance pointing at the project
        content root.
    case_slug
        Default case slug for fallback lookup.  Overridable per
        request via :attr:`ModelRequest.metadata`.
    """

    def __init__(
        self,
        *,
        providers: Mapping[str, Provider],
        router: TaskRouter | None = None,
        cost_controller: CostController | None = None,
        validator: SchemaValidator | None = None,
        fallback_loader: FallbackContentLoader | None = None,
        case_slug: str = "case_01_revolution_street",
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self._providers: dict[str, Provider] = dict(providers)
        self._router = router or TaskRouter()
        self._cost = cost_controller or CostController()
        self._validator = validator or SchemaValidator()
        self._loader = fallback_loader or FallbackContentLoader()
        self._default_case_slug = case_slug

        self._lock = threading.Lock()
        self._runs: dict[str, _RunState] = {}

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def start_run(
        self,
        *,
        run_id: str,
        scene_id: str,
        case_slug: str | None = None,
    ) -> ModelDegradationChain:
        """Begin a new run.  Returns the per-run degradation chain."""

        case = case_slug or self._default_case_slug
        chain = ModelDegradationChain(
            run_id=run_id,
            case_slug=case,
            scene_id=scene_id,
        )
        fallback = self._loader.load_for_scene(case_slug=case, scene_id=scene_id)
        with self._lock:
            self._runs[run_id] = _RunState(
                run_id=run_id,
                chain=chain,
                fallback=fallback,
                turn_index=0,
            )
        return chain

    def end_run(self, run_id: str) -> list:
        """End a run.  Returns any P0 alerts fired by the cost controller."""

        with self._lock:
            state = self._runs.pop(run_id, None)
        if state is None:
            return []
        state.ended = True
        return self._cost.note_run_completion(run_id)

    def run_summary(self, run_id: str) -> RunCostSummary:
        return self._cost.run_summary(run_id)

    def degradation_chain(self, run_id: str) -> ModelDegradationChain | None:
        with self._lock:
            state = self._runs.get(run_id)
        return state.chain if state else None

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Run a structured-output completion for the request's task type.

        Validates the LLM output against the schema for the task
        type.  On validation failure, retries once.  On second
        failure (or any non-recoverable error), escalates the
        degradation chain and returns a writer-authored fallback
        payload.

        Parameters
        ----------
        request
            :class:`ModelRequest` describing the call.

        Returns
        -------
        :class:`ModelResponse`
            Always returns a :class:`ModelResponse` (never raises
            for a recoverable failure).  Unrecoverable failures
            (``BudgetExceededError``,
            ``OutputTokenLimitExceededError``) propagate.
        """

        run_state = self._require_run_state(request.run_id)
        task_cfg = self._router.get(request.task_type)

        # ----- pre-call budget checks ---------------------------------
        try:
            self._cost.check_run_budget(run_id=request.run_id)
            self._cost.check_turn_budget(
                run_id=request.run_id,
                turn_idx=run_state.turn_index,
            )
        except BudgetExceededError:
            # Hard stop — propagate.  The caller (engine layer)
            # is expected to handle the budget violation.
            raise

        # Walk the routes, retrying each up to its quota.
        attempts = 0
        last_error: Exception | None = None
        effective_routes = self._resolve_routes(request.task_type)
        for route, retries_left in effective_routes:
            for attempt in range(retries_left + 1):
                attempts += 1
                route_request = self._apply_route_overrides(request, route)
                try:
                    provider_result = self._call_provider(
                        route=route, request=route_request
                    )
                    parsed, finish, response = self._finalize(
                        request=request,
                        route=route,
                        attempts=attempts,
                        provider_result=provider_result,
                        degradation_level=None,
                        used_fallback=False,
                    )
                    self._post_call_record(
                        request=request,
                        turn_idx=run_state.turn_index,
                        route=route,
                        response=response,
                        finish_reason=finish,
                    )
                    run_state.chain.reset_consecutive()
                    return response
                except (ProviderTimeoutError, SchemaValidationError) as exc:
                    last_error = exc
                    # The schema-validation retry is *internal* to
                    # this route — it does NOT count as a separate
                    # cross-task failure for the degradation chain.
                    # We only increment the chain counter when a
                    # route is fully exhausted (i.e. when we move
                    # to the next route in ``effective_routes``).
                    if attempt >= retries_left:
                        run_state.chain.note_failure()
                        break
                    continue

        # All routes failed.  Run the model-layer degradation chain.
        return self._fallback_response(
            request=request,
            run_state=run_state,
            task_cfg=task_cfg,
            attempts=attempts,
            last_error=last_error or ProviderTimeoutError("all routes failed"),
        )

    def chat(self, request: ModelRequest) -> ModelResponse:
        """Like :meth:`complete` but does not parse or validate JSON.

        Used for tasks that have no schema mapping
        (currently :attr:`TaskType.MEMORY_RECALL`) or by callers
        that want to do their own validation.  The degradation
        chain still fires on provider timeouts, but there is no
        retry-on-schema-failure.
        """

        run_state = self._require_run_state(request.run_id)
        self._cost.check_run_budget(run_id=request.run_id)
        self._cost.check_turn_budget(
            run_id=request.run_id,
            turn_idx=run_state.turn_index,
        )

        attempts = 0
        last_error: Exception | None = None
        for route, retries_left in self._resolve_routes(request.task_type):
            for attempt in range(retries_left + 1):
                attempts += 1
                route_request = self._apply_route_overrides(request, route)
                try:
                    provider_result = self._call_provider(
                        route=route, request=route_request
                    )
                    response = self._response_from_provider(
                        request=request,
                        route=route,
                        provider_result=provider_result,
                        parsed=None,
                        degradation_level=None,
                        used_fallback=False,
                        attempts=attempts,
                    )
                    self._post_call_record(
                        request=request,
                        turn_idx=run_state.turn_index,
                        route=route,
                        response=response,
                        finish_reason=response.finish_reason,
                    )
                    run_state.chain.reset_consecutive()
                    return response
                except ProviderTimeoutError as exc:
                    last_error = exc
                    # See complete(): internal retries do not bump
                    # the chain's consecutive counter; only
                    # route-exhaustion does.
                    if attempt >= retries_left:
                        run_state.chain.note_failure()
                        break
                    continue

        return self._fallback_response(
            request=request,
            run_state=run_state,
            task_cfg=self._router.get(request.task_type),
            attempts=attempts,
            last_error=last_error or ProviderTimeoutError("all routes failed"),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_run_state(self, run_id: str) -> _RunState:
        with self._lock:
            state = self._runs.get(run_id)
        if state is None:
            raise KeyError(
                f"run {run_id!r} not started; call start_run() first"
            )
        if state.ended:
            raise RuntimeError(f"run {run_id!r} has already ended")
        return state

    def _apply_route_overrides(
        self, request: ModelRequest, route: ModelRoute
    ) -> ModelRequest:
        """Build a copy of ``request`` with route overrides applied."""

        return ModelRequest(
            run_id=request.run_id,
            scene_id=request.scene_id,
            task_type=request.task_type,
            messages=list(request.messages),
            temperature=(
                route.temperature
                if route.temperature is not None
                else request.temperature
            ),
            max_output_tokens=(
                route.max_output_tokens
                if route.max_output_tokens is not None
                else request.max_output_tokens
            ),
            timeout_ms=(
                route.timeout_ms
                if route.timeout_ms is not None
                else request.timeout_ms
            ),
            schema_name=request.schema_name,
            metadata={
                **request.metadata,
                "provider": route.provider,
                "model": route.model,
            },
        )

    def _call_provider(
        self, *, route: ModelRoute, request: ModelRequest
    ) -> ProviderResult:
        provider = self._providers.get(route.provider)
        if provider is None:
            raise KeyError(
                f"routing requested provider {route.provider!r} "
                f"but no such provider is registered"
            )
        return provider.complete(
            model=route.model,
            messages=request.messages,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            timeout_ms=request.timeout_ms,
        )

    def _resolve_routes(
        self, task_type: TaskType
    ) -> list[tuple[ModelRoute, int]]:
        """Return the effective route list for ``task_type``.

        The router's config may reference providers that are not
        actually registered (e.g. the default router knows
        ``deepseek`` / ``qwen`` but the gateway was constructed
        with only a mock provider for tests / offline dev).
        Routes whose provider is not registered are dropped from
        the effective list.

        If *every* configured route is dropped, the gateway falls
        back to **any** registered provider using a synthetic
        route with the same per-route retry budget as the task's
        first configured route.  This keeps the gateway usable
        when the test suite / offline environment only registered
        a mock provider.
        """

        configured = self._router.iter_routes(task_type)
        effective = [
            (r, retries)
            for r, retries in configured
            if r.provider in self._providers
        ]
        if effective:
            return effective
        # Nothing matches — synthesise a single route on the first
        # registered provider.  Use the first route's retry budget
        # so the chain semantics are preserved.
        first_route, first_retries = configured[0]
        fallback_provider = next(iter(self._providers))
        return [
            (
                ModelRoute(
                    provider=fallback_provider,
                    model=first_route.model,
                ),
                first_retries,
            )
        ]

    def _finalize(
        self,
        *,
        request: ModelRequest,
        route: ModelRoute,
        attempts: int,
        provider_result: ProviderResult,
        degradation_level: str | None,
        used_fallback: bool,
    ) -> tuple[dict | None, str, ModelResponse]:
        """Validate, parse, and build the :class:`ModelResponse`."""

        schema_name = request.schema_name or self._schema_name_for(request.task_type)
        if schema_name is None:
            # No schema enforcement — just pass the content through.
            parsed = safe_parse_json(provider_result.content)
            response = self._response_from_provider(
                request=request,
                route=route,
                provider_result=provider_result,
                parsed=parsed,
                degradation_level=degradation_level,
                used_fallback=used_fallback,
                attempts=attempts,
            )
            return parsed, response.finish_reason, response

        # Schema-validated path.
        report = self._validator.validate(
            schema_name=schema_name, payload=provider_result.content
        )
        if not report.ok:
            raise SchemaValidationError(
                f"schema '{schema_name}' rejected provider output "
                f"({len(report.issues)} issues)",
                errors=[str(i) for i in report.issues],
                schema=schema_name,
            )
        response = self._response_from_provider(
            request=request,
            route=route,
            provider_result=provider_result,
            parsed=report.parsed,
            degradation_level=degradation_level,
            used_fallback=used_fallback,
            attempts=attempts,
        )
        return report.parsed, response.finish_reason, response

    def _response_from_provider(
        self,
        *,
        request: ModelRequest,
        route: ModelRoute,
        provider_result: ProviderResult,
        parsed: dict | None,
        degradation_level: str | None,
        used_fallback: bool,
        attempts: int,
    ) -> ModelResponse:
        # Hard red line: output tokens < 800
        try:
            self._cost.check_output_token_limit(
                model=route.model,
                output_tokens=provider_result.output_tokens,
            )
        except OutputTokenLimitExceededError:
            raise
        cost = self._cost.price(
            provider=route.provider,
            model=route.model,
            input_tokens=provider_result.input_tokens,
            output_tokens=provider_result.output_tokens,
        )
        return ModelResponse(
            content=provider_result.content,
            parsed=parsed,
            model=route.model,
            provider=route.provider,
            task_type=request.task_type,
            input_tokens=provider_result.input_tokens,
            output_tokens=provider_result.output_tokens,
            latency_ms=provider_result.latency_ms,
            cost_cny=round(cost, 6),
            finish_reason=provider_result.finish_reason,
            degradation_level=degradation_level,
            used_fallback=used_fallback,
            attempts=attempts,
        )

    def _post_call_record(
        self,
        *,
        request: ModelRequest,
        turn_idx: int,
        route: ModelRoute,
        response: ModelResponse,
        finish_reason: str,
    ) -> CostRecord:
        record = make_cost_record(
            run_id=request.run_id,
            scene_id=request.scene_id,
            task_type=request.task_type.value,
            agent=request.task_type.value,
            model=route.model,
            provider=route.provider,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            finish_reason=finish_reason,
            degradation_level=response.degradation_level,
            used_fallback=response.used_fallback,
            attempts=response.attempts,
            request_id=response.request_id,
            metadata=dict(request.metadata),
        )
        return self._cost.record(record=record, turn_idx=turn_idx)

    def _fallback_response(
        self,
        *,
        request: ModelRequest,
        run_state: _RunState,
        task_cfg: TaskConfig,
        attempts: int,
        last_error: Exception,
    ) -> ModelResponse:
        """Build the response when all provider routes failed."""

        # L4 — persist failure is a hard error from the engine.
        if isinstance(last_error, PersistFailureError):
            payload = trigger_l4(
                run_state.chain,
                fallback=run_state.fallback,
                error=str(last_error),
            )
            response = self._writer_response(
                request=request,
                writer_payload=payload,
                attempts=attempts,
            )
            return response

        # L3 — escalation due to consecutive failures
        if run_state.chain.consecutive_failures >= 2:
            payload = trigger_l3(
                run_state.chain,
                fallback=run_state.fallback,
                beat_id=str(
                    request.metadata.get("beatId", "fallback_beat")
                ),
                error=str(last_error),
            )
            response = self._writer_response(
                request=request,
                writer_payload=payload,
                attempts=attempts,
            )
            return response

        # L1 / L2 — single-failure fallback for the task type.
        if request.task_type == TaskType.NPC_PROPOSER:
            payload = trigger_l1(
                run_state.chain,
                fallback=run_state.fallback,
                characterId=str(
                    request.metadata.get("characterId", "unknown")
                ),
                actionType=str(
                    request.metadata.get("actionType", "unknown")
                ),
                error=str(last_error),
            )
        elif request.task_type == TaskType.DIRECTOR_PROPOSER:
            payload = trigger_l2(
                run_state.chain,
                fallback=run_state.fallback,
                beat_id=str(
                    request.metadata.get("beatId", "fallback_beat")
                ),
                error=str(last_error),
            )
        else:
            # resolver / player_intent_parser / memory_recall:
            # treat as L2 (skip validation; allow the engine to
            # keep going).
            payload = trigger_l2(
                run_state.chain,
                fallback=run_state.fallback,
                beat_id=str(
                    request.metadata.get("beatId", "fallback_beat")
                ),
                error=str(last_error),
            )
        response = self._writer_response(
            request=request,
            writer_payload=payload,
            attempts=attempts,
        )
        return response

    def _writer_response(
        self,
        *,
        request: ModelRequest,
        writer_payload: WriterPayload,
        attempts: int,
    ) -> ModelResponse:
        response = ModelResponse(
            content=writer_payload.content,
            parsed=writer_payload.parsed,
            model="writer",
            provider="writer",
            task_type=request.task_type,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            cost_cny=0.0,
            finish_reason="fallback",
            degradation_level=writer_payload.level.value,
            used_fallback=True,
            attempts=attempts,
        )
        # Record the fallback as a zero-cost call so the model_calls
        # table has a complete audit trail.
        route = ModelRoute(provider="writer", model="writer")
        self._post_call_record(
            request=request,
            turn_idx=self._runs[request.run_id].turn_index,
            route=route,
            response=response,
            finish_reason=response.finish_reason,
        )
        return response

    def _schema_name_for(self, task_type: TaskType) -> str | None:
        from .models import TASK_TO_SCHEMA
        return TASK_TO_SCHEMA.get(task_type)


__all__ = ["ModelGateway"]


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def build_default_gateway(
    *,
    case_slug: str = "case_01_revolution_street",
    with_real_providers: bool = False,
    api_keys: Mapping[str, str] | None = None,
) -> ModelGateway:
    """Construct a gateway with the recommended default providers.

    Parameters
    ----------
    case_slug
        Default case slug for fallback lookup.
    with_real_providers
        If True, instantiate DeepSeek and Qwen providers (using
        env-var API keys, or ``api_keys`` overrides).  If False,
        only the mock provider is registered — useful for tests
        and offline dev.
    api_keys
        Optional override of API keys.  Keys are
        ``{"deepseek": "...", "qwen": "..."}``.
    """

    from .providers import (
        DeepSeekProvider,
        MockProvider,
        QwenProvider,
    )

    providers: dict[str, Provider] = {"mock": MockProvider()}
    if with_real_providers:
        keys = dict(api_keys or {})
        providers["deepseek"] = DeepSeekProvider(api_key=keys.get("deepseek"))
        providers["qwen"] = QwenProvider(api_key=keys.get("qwen"))
    return ModelGateway(
        providers=providers,
        case_slug=case_slug,
    )
