"""Mock provider — deterministic responses for tests and offline dev.

The Mock provider keeps a queue of scripted responses.  Each call
pops the next response and returns it as a :class:`ProviderResult`.
When the queue is empty, it falls through to ``default_response``
(which is itself configurable).

This lets the test suite drive the full 4-level degradation chain
without ever touching a network.  The classic pattern is:

.. code-block:: python

    mock = MockProvider(responses=[
        ProviderResult(content="...", finish_reason="stop"),
        ProviderResult(content="", finish_reason="timeout"),
        ProviderResult(content="...", finish_reason="stop"),
    ])
    gateway = ModelGateway(providers={"mock": mock}, ...)

Why script the whole response
-----------------------------
* Tests need to control ``finish_reason`` (``stop`` / ``length``
  / ``timeout`` / ``error``) to drive the retry and degradation
  paths.
* Tests need to control ``input_tokens`` and ``output_tokens``
  to verify the cost controller's red-line checks.
* Tests need to control ``latency_ms`` to drive the timeout path.
A single ``content=...`` knob is not enough.
"""

from __future__ import annotations

import threading
import time
from typing import Sequence

from ..exceptions import ProviderTimeoutError
from ..models import Message, ProviderResult
from .base import Provider


class MockProvider(Provider):
    """A deterministic, programmable provider for tests."""

    name: str = "mock"

    def __init__(
        self,
        responses: Sequence[ProviderResult] | None = None,
        *,
        default_response: ProviderResult | None = None,
        raise_after: int | None = None,
    ) -> None:
        self._responses: list[ProviderResult] = list(responses or [])
        self._default = default_response or ProviderResult(
            content="{}",
            model="mock-default",
            provider="mock",
            input_tokens=10,
            output_tokens=10,
            finish_reason="stop",
            latency_ms=1,
        )
        # If set, raise ProviderTimeoutError after this many calls.
        self._raise_after = raise_after
        self._call_count = 0
        self._lock = threading.Lock()
        # Audit hook for assertions in tests
        self.calls: list[dict] = []

    def push(self, response: ProviderResult) -> None:
        """Append a response to the queue (thread-safe)."""
        with self._lock:
            self._responses.append(response)

    def reset(self) -> None:
        """Clear the queue and counters."""
        with self._lock:
            self._responses.clear()
            self._call_count = 0
            self.calls.clear()

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        temperature: float,
        max_output_tokens: int,
        timeout_ms: int,
    ) -> ProviderResult:
        with self._lock:
            self._call_count += 1
            call_index = self._call_count
            self.calls.append(
                {
                    "model": model,
                    "messages": [m.to_dict() for m in messages],
                    "temperature": temperature,
                    "maxOutputTokens": max_output_tokens,
                    "timeoutMs": timeout_ms,
                }
            )
            if self._raise_after is not None and self._call_count > self._raise_after:
                raise ProviderTimeoutError(
                    f"mock: forced timeout after {self._call_count} calls"
                )
            if self._responses:
                # Pop the next scripted response and reflect the
                # actual model the gateway asked for in the audit.
                result = self._responses.pop(0)
                # If the scripted response didn't pin a model/provider
                # explicitly, fill in from the call context.
                if not result.model:
                    result.model = model
                if not result.provider:
                    result.provider = self.name
                # Latency is per-call; if the test didn't pin it,
                # measure from start.
                if result.latency_ms == 0:
                    result.latency_ms = 1
                return result

        # Default response: no scripted queue, no forced raise.
        return ProviderResult(
            content=self._default.content,
            model=model or self._default.model,
            provider=self._default.provider or self.name,
            input_tokens=self._default.input_tokens,
            output_tokens=self._default.output_tokens,
            finish_reason=self._default.finish_reason,
            latency_ms=self._default.latency_ms or int(time.monotonic() * 0) + 1,
        )


__all__ = ["MockProvider"]
