"""OpenAI-compatible provider — used for DeepSeek / 千问 / Claude-via-proxy / GPT.

The OpenAI HTTP API is the de-facto industry standard; most new
Chinese and open-source providers (DeepSeek, 通义千问, 智谱 GLM,
Moonshot Kimi, etc.) expose an OpenAI-compatible endpoint.  This
provider implements the wire format once and is specialised by
the DeepSeek and Qwen subclasses (and any future provider that
speaks the same shape).

Wire format
-----------
* ``POST {base_url}/chat/completions``
* ``Authorization: Bearer {api_key}``
* Request body: ``{"model", "messages", "temperature", "max_tokens"}``
* Response body: ``{"choices": [{"message": {"content": ...}}], "usage": {...}}``

Why httpx
---------
We use ``httpx`` rather than the OpenAI Python SDK so the gateway
has no hard dependency on the SDK version.  Any provider that
speaks the OpenAI wire format can be added by changing two
fields (``base_url`` and ``api_key_env``).
"""

from __future__ import annotations

import json
import os
import time
from typing import Sequence

import httpx

from ..exceptions import (
    ProviderHTTPError,
    ProviderParseError,
    ProviderTimeoutError,
)
from ..models import Message, ProviderResult
from .base import Provider


# Conservative default for Chinese domestic APIs.  Override in the
# subclass for faster/closer endpoints.
DEFAULT_TIMEOUT_MS: int = 8000


class OpenAICompatibleProvider(Provider):
    """A provider that talks OpenAI's chat-completions wire format.

    Parameters
    ----------
    base_url
        The provider's API root.  The gateway appends
        ``/chat/completions`` to it.  Examples:
        ``https://api.deepseek.com/v1``,
        ``https://dashscope.aliyuncs.com/compatible-mode/v1``,
        ``https://api.openai.com/v1``.
    api_key
        The bearer token.  If ``None``, the constructor reads
        ``api_key_env`` from the environment.  This is the only
        way API keys enter the system; they are never hard-coded.
    api_key_env
        Name of the environment variable to read the API key
        from when ``api_key`` is ``None``.  Defaults to
        ``"OPENAI_API_KEY"`` (which the real OpenAI provider uses).
    name
        The provider's audit-stable identifier.
    timeout_ms
        Default per-call timeout in milliseconds.  Individual
        calls may override via :class:`models.ModelRequest`.
    """

    name: str = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        name: str = "openai_compatible",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key or os.environ.get(api_key_env, "")
        if not self._api_key:
            # We don't raise here — providers can be constructed
            # for unit tests or for fallback paths that never
            # actually hit the wire.  The first call will raise
            # a clear ProviderHTTPError.
            self._api_key = ""
        self._api_key_env = api_key_env
        self.name = name
        self._default_timeout_ms = timeout_ms
        # Keep an httpx.Client around for connection pooling.  If
        # the caller passed one in, use it; otherwise create a
        # short-lived client per call to avoid the cost of
        # connection pool teardown in tests.
        self._external_client = client

    # ------------------------------------------------------------------
    # Provider interface
    # ------------------------------------------------------------------

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        temperature: float,
        max_output_tokens: int,
        timeout_ms: int,
    ) -> ProviderResult:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "temperature": float(temperature),
            "max_tokens": int(max_output_tokens),
            "stream": False,
        }
        timeout_s = max(timeout_ms, 1) / 1000.0
        start = time.monotonic()
        try:
            if self._external_client is not None:
                response = self._external_client.post(
                    url, headers=headers, json=payload, timeout=timeout_s
                )
            else:
                with httpx.Client(timeout=timeout_s) as client:
                    response = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"{self.name} timed out after {timeout_ms}ms"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderHTTPError(
                f"{self.name} HTTP error: {exc}", status_code=0, body=str(exc)
            ) from exc
        latency_ms = int((time.monotonic() - start) * 1000)

        if response.status_code >= 400:
            raise ProviderHTTPError(
                f"{self.name} returned {response.status_code}",
                status_code=response.status_code,
                body=response.text[:500],
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderParseError(
                f"{self.name} returned non-JSON body: {response.text[:200]!r}"
            ) from exc

        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderParseError(
                f"{self.name} response missing choices[0].message.content: {exc}"
            ) from exc

        usage = data.get("usage") or {}
        return ProviderResult(
            content=content if isinstance(content, str) else str(content),
            model=model,
            provider=self.name,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            finish_reason=str(choice.get("finish_reason") or "stop"),
            latency_ms=latency_ms,
        )


__all__ = ["OpenAICompatibleProvider", "DEFAULT_TIMEOUT_MS"]
