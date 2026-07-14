"""Task-based routing — pick the right (provider, model) for each task.

Each :class:`TaskType` has its own :class:`TaskConfig` describing
the ordered list of provider/model pairs to try.  The first
successful one wins; the others are fallbacks.  This is the
*primary* degradation chain for transient errors (network blip,
rate limit) — separate from the *fallback content* chain
(decision 5's 4 levels).

Why a per-task config
---------------------
* The NPC Proposer (high-stakes, mid-session) is a different
  workload from the Player Intent Parser (cheap, every turn).
  Routing them through the same (provider, model) wastes money.
* The default config uses DeepSeek-V3 (cheap, fast) as primary
  and Qwen-Plus (cheap, Chinese-domestic) as fallback.  The
  Director and Resolver can use the reasoner / max models when
  they need depth.
* The config is **mutable at runtime** — the gateway can hot-
  swap the primary if a provider goes down.

Hard-coded defaults
-------------------
The defaults below are *recommendations*.  Production deployments
should override via :func:`build_default_router` or by
constructing :class:`TaskRouter` directly with a custom config.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import TaskType


# ---------------------------------------------------------------------------
# Per-task config
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ModelRoute:
    """One (provider, model) entry in a task's fallback chain."""

    provider: str
    model: str
    # Per-route override; ``None`` means use the request's value.
    timeout_ms: int | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "timeoutMs": self.timeout_ms,
            "maxOutputTokens": self.max_output_tokens,
            "temperature": self.temperature,
        }


@dataclass(slots=True)
class TaskConfig:
    """The per-task routing config."""

    task_type: TaskType
    routes: list[ModelRoute] = field(default_factory=list)
    # Fallback to writer-authored content when ALL routes fail.
    # Always True for production — the cost of falling through
    # to a writer line is less than dropping a turn.
    allow_writer_fallback: bool = True
    # Per-task max retries *within a route* before falling through
    # to the next route.
    max_retries_per_route: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "taskType": self.task_type.value,
            "routes": [r.to_dict() for r in self.routes],
            "allowWriterFallback": self.allow_writer_fallback,
            "maxRetriesPerRoute": self.max_retries_per_route,
        }


# ---------------------------------------------------------------------------
# Default configs
# ---------------------------------------------------------------------------


def _player_intent_parser() -> TaskConfig:
    return TaskConfig(
        task_type=TaskType.PLAYER_INTENT_PARSER,
        routes=[
            ModelRoute(provider="deepseek", model="deepseek-chat"),
            ModelRoute(provider="qwen", model="qwen-turbo"),
        ],
        max_retries_per_route=1,
    )


def _npc_proposer() -> TaskConfig:
    return TaskConfig(
        task_type=TaskType.NPC_PROPOSER,
        routes=[
            ModelRoute(provider="deepseek", model="deepseek-chat"),
            ModelRoute(provider="qwen", model="qwen-plus"),
        ],
        max_retries_per_route=1,
    )


def _director_proposer() -> TaskConfig:
    # The Director weighs multiple beats; we let it use the
    # reasoner as primary when available, with a cheaper fallback.
    return TaskConfig(
        task_type=TaskType.DIRECTOR_PROPOSER,
        routes=[
            ModelRoute(provider="deepseek", model="deepseek-chat"),
            ModelRoute(provider="qwen", model="qwen-plus"),
        ],
        max_retries_per_route=1,
    )


def _resolver() -> TaskConfig:
    # The Resolver is the only writer to canonical state.  We
    # route it to the most reliable model; Qwen-Plus is fine.
    return TaskConfig(
        task_type=TaskType.RESOLVER,
        routes=[
            ModelRoute(provider="deepseek", model="deepseek-chat"),
            ModelRoute(provider="qwen", model="qwen-plus"),
        ],
        max_retries_per_route=1,
    )


def _memory_recall() -> TaskConfig:
    # Memory recall is a cheap, low-stakes task — fastest model
    # wins.  The output is not schema-validated (TASK_TO_SCHEMA is
    # None for this task).
    return TaskConfig(
        task_type=TaskType.MEMORY_RECALL,
        routes=[
            ModelRoute(provider="qwen", model="qwen-turbo"),
            ModelRoute(provider="deepseek", model="deepseek-chat"),
        ],
        max_retries_per_route=1,
    )


DEFAULT_TASK_CONFIGS: dict[TaskType, TaskConfig] = {
    TaskType.PLAYER_INTENT_PARSER: _player_intent_parser(),
    TaskType.NPC_PROPOSER: _npc_proposer(),
    TaskType.DIRECTOR_PROPOSER: _director_proposer(),
    TaskType.RESOLVER: _resolver(),
    TaskType.MEMORY_RECALL: _memory_recall(),
}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class TaskRouter:
    """Per-task routing with hot-swappable configs.

    The router exposes a small surface:

    * :meth:`get` — read the current config for a task.
    * :meth:`set` — replace the config (used by the operator to
      hot-swap a provider outage).
    * :meth:`iter_routes` — walk the routes in order, yielding
      (route, retries_left).  Used by the gateway.
    """

    def __init__(
        self,
        configs: Mapping[TaskType, TaskConfig] | None = None,
    ) -> None:
        self._configs: dict[TaskType, TaskConfig] = dict(
            configs if configs is not None else DEFAULT_TASK_CONFIGS
        )
        self._lock = threading.Lock()

    def get(self, task_type: TaskType) -> TaskConfig:
        with self._lock:
            cfg = self._configs.get(task_type)
        if cfg is None:
            raise KeyError(f"no routing config for task {task_type.value}")
        return cfg

    def set(self, task_type: TaskType, config: TaskConfig) -> None:
        with self._lock:
            self._configs[task_type] = config

    def iter_routes(self, task_type: TaskType) -> list[tuple[ModelRoute, int]]:
        """Return ``[(route, retries_left), ...]`` for the task."""

        cfg = self.get(task_type)
        return [(r, cfg.max_retries_per_route) for r in cfg.routes]

    @property
    def all_configs(self) -> dict[TaskType, TaskConfig]:
        with self._lock:
            return dict(self._configs)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_default_router() -> TaskRouter:
    """Construct a router with the recommended default configs."""

    return TaskRouter()


__all__ = [
    "ModelRoute",
    "TaskConfig",
    "DEFAULT_TASK_CONFIGS",
    "TaskRouter",
    "build_default_router",
]
