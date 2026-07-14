"""Model Gateway — unified LLM wrapper for the AI-native game.

This package is the **single entry point** for LLM calls in the
server.  It implements decision 5 (AI 成本红线 + 4 级降级链)
end-to-end:

* **统一包装层** — :class:`ModelGateway` exposes a single
  ``complete()`` / ``chat()`` interface regardless of which
  provider answers.
* **多供应商路由** — :class:`routing.TaskRouter` picks the
  (provider, model) per task type, with fallbacks.
* **4 级降级链** — :mod:`degradation` (model-layer) and the
  engine-layer chain work together to keep the game running
  when the LLM is unavailable.
* **成本控制** — :mod:`cost_control` enforces the hard red lines
  (20 calls / 800 tokens / 2 calls per turn / P95 4s) and the
  soft target (¥0.8 / run).  P0 alert on 3 consecutive L3 runs.
* **Schema 合规** — :mod:`schema_compliance` validates LLM output
  against the 8 engine JSON Schemas.
* **真实供应商** — :mod:`providers.deepseek` and
  :mod:`providers.qwen` are production-ready; :mod:`providers.mock`
  is the deterministic test double.

Public API
----------

Construction
~~~~~~~~~~~~

.. code-block:: python

    from server.model import build_default_gateway

    gateway = build_default_gateway(
        case_slug="case_01_revolution_street",
        with_real_providers=True,
    )

Per-run lifecycle
~~~~~~~~~~~~~~~~~

.. code-block:: python

    from server.model import ModelRequest, TaskType, Message, MessageRole

    gateway.start_run(run_id=run_id, scene_id=scene_id)
    response = gateway.complete(ModelRequest(
        run_id=run_id,
        scene_id=scene_id,
        task_type=TaskType.NPC_PROPOSER,
        messages=[
            Message(role=MessageRole.SYSTEM, content="You are Leila"),
            Message(role=MessageRole.USER, content="What does she say?"),
        ],
    ))
    gateway.end_run(run_id)

Module map
----------

* :mod:`gateway`           — :class:`ModelGateway` (main entry)
* :mod:`routing`           — :class:`TaskRouter`, :class:`TaskConfig`
* :mod:`degradation`       — model-layer 4-level chain
* :mod:`cost_control`      — per-call audit, per-run cap, P0 alert
* :mod:`schema_compliance` — JSON Schema validator
* :mod:`fallback_loader`   — writer-authored content loader
* :mod:`providers`         — provider implementations
* :mod:`models`            — request/response/audit dataclasses
* :mod:`exceptions`        — model-layer exception hierarchy
"""

from __future__ import annotations

from .cost_control import (
    CostController,
    P0Alert,
    make_cost_record,
)
from .degradation import (
    LEVEL_ORDER as MODEL_DEGRADATION_LEVEL_ORDER,
    ModelDegradationChain,
    ModelDegradationLevel,
    ModelDegradationRecord,
    WriterPayload,
    run_with_chain,
    trigger_l1,
    trigger_l2,
    trigger_l3,
    trigger_l4,
)
from .exceptions import (
    BudgetExceededError,
    CostCapExceededError,
    DegradationEscalatedError,
    ModelCallError,
    ModelError,
    OutputTokenLimitExceededError,
    PersistFailureError,
    ProviderHTTPError,
    ProviderParseError,
    ProviderTimeoutError,
    SchemaValidationError,
)
from .fallback_loader import (
    FallbackContentLoader,
    ModelFallbackContent,
    ModelNPCFallbackLine,
)
from .gateway import ModelGateway, build_default_gateway
from .models import (
    CostRecord,
    Message,
    MessageRole,
    ModelRequest,
    ModelResponse,
    ProviderResult,
    RunCostSummary,
    TASK_TO_SCHEMA,
    TaskType,
    safe_parse_json,
)
from .providers import (
    DeepSeekProvider,
    MockProvider,
    OpenAICompatibleProvider,
    Provider,
    QwenProvider,
)
from .routing import (
    DEFAULT_TASK_CONFIGS,
    ModelRoute,
    TaskConfig,
    TaskRouter,
    build_default_router,
)
from .schema_compliance import (
    SchemaValidator,
    ValidationIssue,
    ValidationReport,
)

__version__ = "1.0.0"

__all__ = [
    # gateway
    "ModelGateway",
    "build_default_gateway",
    # models
    "TaskType",
    "TASK_TO_SCHEMA",
    "Message",
    "MessageRole",
    "ModelRequest",
    "ModelResponse",
    "ProviderResult",
    "CostRecord",
    "RunCostSummary",
    "safe_parse_json",
    # routing
    "ModelRoute",
    "TaskConfig",
    "TaskRouter",
    "DEFAULT_TASK_CONFIGS",
    "build_default_router",
    # providers
    "Provider",
    "OpenAICompatibleProvider",
    "MockProvider",
    "DeepSeekProvider",
    "QwenProvider",
    # degradation
    "ModelDegradationLevel",
    "MODEL_DEGRADATION_LEVEL_ORDER",
    "ModelDegradationRecord",
    "ModelDegradationChain",
    "WriterPayload",
    "run_with_chain",
    "trigger_l1",
    "trigger_l2",
    "trigger_l3",
    "trigger_l4",
    # cost control
    "CostController",
    "P0Alert",
    "make_cost_record",
    # schema compliance
    "SchemaValidator",
    "ValidationIssue",
    "ValidationReport",
    # fallback loader
    "FallbackContentLoader",
    "ModelFallbackContent",
    "ModelNPCFallbackLine",
    # exceptions
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
