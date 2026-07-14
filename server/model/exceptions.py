"""Model-layer exception hierarchy.

These exceptions are raised inside the Model Gateway (server/model/).
They mirror the engine-layer exception families (see
:mod:`server.engine.exceptions`) but are scoped to the LLM call
boundary:

* :exc:`ModelCallError`        — base for any LLM call failure
* :exc:`ProviderTimeoutError`  — provider did not respond in time
* :exc:`ProviderHTTPError`     — provider returned a non-2xx status
* :exc:`ProviderParseError`    — provider returned unparseable output
* :exc:`SchemaValidationError` — LLM output failed schema validation
* :exc:`CostCapExceededError`  — call would breach a hard cost cap
* :exc:`BudgetExceededError`   — per-turn / per-run call count exceeded
* :exc:`DegradationEscalatedError` — chain moved to a higher level
* :exc:`PersistFailureError`   — resolver write failure (L4)

The engine-layer degradation chain and the model-layer degradation
chain are distinct: engine decides *what to do* (skip beat, use
writer mainline), model decides *whether to call the LLM at all*
and *which fallback content to use*.  Sharing an exception
namespace here would create coupling; we keep them separate.
"""

from __future__ import annotations


class ModelError(Exception):
    """Base class for every error raised inside the Model Gateway."""


# ---------------------------------------------------------------------------
# Provider-level errors
# ---------------------------------------------------------------------------


class ModelCallError(ModelError):
    """Generic LLM call failure (provider raised or returned nothing)."""


class ProviderTimeoutError(ModelCallError):
    """The provider did not respond within the configured deadline."""


class ProviderHTTPError(ModelCallError):
    """The provider returned a non-2xx HTTP status.

    Carries the original status code and response body so the
    routing layer can decide whether to retry or fall through.
    """

    def __init__(self, message: str, status_code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class ProviderParseError(ModelCallError):
    """The provider returned output that could not be JSON-parsed."""


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------


class SchemaValidationError(ModelError):
    """LLM output failed JSON Schema validation.

    Carries the validator's error list for the model_calls audit
    so the team can see *why* the schema rejected the output
    (offending path, expected type, etc.).
    """

    def __init__(
        self,
        message: str,
        errors: list[str] | None = None,
        schema: str = "",
    ) -> None:
        super().__init__(message)
        self.errors = list(errors or [])
        self.schema = schema


# ---------------------------------------------------------------------------
# Cost / budget enforcement
# ---------------------------------------------------------------------------


class CostCapExceededError(ModelError):
    """A call would breach a hard cost cap (per-run ¥0.8, per-turn 2 calls, ...)."""


class BudgetExceededError(CostCapExceededError):
    """Per-turn (≤ 2) or per-run (≤ 20) main-call budget exhausted."""


class OutputTokenLimitExceededError(CostCapExceededError):
    """Single call's output token count would exceed 800 (decision 5 hard red line)."""


# ---------------------------------------------------------------------------
# Degradation chain
# ---------------------------------------------------------------------------


class DegradationEscalatedError(ModelError):
    """The model-layer degradation chain moved to a higher level.

    The Model Gateway wraps this around a payload that *would*
    have come from the LLM but was substituted with a writer
    fallback.  Call sites can branch on the level to decide
    whether to keep going or short-circuit the turn.
    """

    def __init__(self, message: str, level: str = "", payload: object = None) -> None:
        super().__init__(message)
        self.level = level
        self.payload = payload


class PersistFailureError(ModelError):
    """Resolver failed to persist the outcome (L4 trigger)."""


__all__ = [
    "ModelError",
    "ModelCallError",
    "ProviderTimeoutError",
    "ProviderHTTPError",
    "ProviderParseError",
    "SchemaValidationError",
    "CostCapExceededError",
    "BudgetExceededError",
    "OutputTokenLimitExceededError",
    "DegradationEscalatedError",
    "PersistFailureError",
]
