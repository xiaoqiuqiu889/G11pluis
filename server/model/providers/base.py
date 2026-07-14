"""Provider abstract base class.

A :class:`Provider` is the lowest-level abstraction in the Model
Gateway.  It knows how to talk to *one* LLM backend (or a mock
thereof) and produce a :class:`ProviderResult`.  Everything else
in the gateway — routing, cost, schema, degradation — is layered
on top.

Why a thin base class
---------------------
* The OpenAI-compatible family (DeepSeek / 千问 / Claude-via-proxy /
  GPT) all share the same wire format.  We implement it once in
  :class:`OpenAICompatibleProvider` and specialise the base URL
  and default model in subclasses.
* The :class:`MockProvider` is used by the test suite.  Tests pin
  a deterministic sequence of responses so the degradation chain
  is exercised in isolation.
* The base class intentionally does NOT do retries, timeouts, or
  schema validation — those live in the gateway layer.  Providers
  just talk to the wire and surface their failures via
  :class:`exceptions.ModelCallError` subclasses.
"""

from __future__ import annotations

import abc
from typing import Sequence

from ..models import Message, ProviderResult


class Provider(abc.ABC):
    """Abstract base for an LLM provider."""

    #: Stable identifier (e.g. ``"openai_compatible"``, ``"mock"``,
    #: ``"deepseek"``, ``"qwen"``).  Used in audit records and in
    #: routing configs.
    name: str = "abstract"

    @abc.abstractmethod
    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        temperature: float,
        max_output_tokens: int,
        timeout_ms: int,
    ) -> ProviderResult:
        """Run a single completion and return the raw result.

        Parameters
        ----------
        model
            The model id the provider should use (e.g.
            ``"deepseek-chat"``, ``"qwen-plus"``).  The provider
            may refuse unknown models; the gateway is responsible
            for routing only to configured models.
        messages
            Ordered conversation.
        temperature
            Sampling temperature.  Providers should clamp the
            value into their legal range.
        max_output_tokens
            Hard cap on output tokens.  Providers should pass
            this through (or set their own cap if lower).
        timeout_ms
            Per-call timeout.  Providers are responsible for
            enforcing it and raising :class:`ProviderTimeoutError`
            on expiry.

        Raises
        ------
        ProviderTimeoutError
            The call did not complete within ``timeout_ms``.
        ProviderHTTPError
            The provider returned a non-2xx status.
        ProviderParseError
            The provider returned output the gateway could not
            parse.
        """

        raise NotImplementedError


__all__ = ["Provider"]
