"""DeepSeek provider.

DeepSeek exposes an OpenAI-compatible API at
``https://api.deepseek.com/v1``.  The default model
``deepseek-chat`` is the production chat model
(DeepSeek-V3 family).  ``deepseek-reasoner`` is the R1 reasoning
model — useful for director_proposer where the LLM has to weigh
multiple beat candidates.

API key
-------
Read from the ``DEEPSEEK_API_KEY`` environment variable.  Never
hard-code.
"""

from __future__ import annotations

import os

from .openai_compatible import OpenAICompatibleProvider

DEFAULT_BASE_URL: str = "https://api.deepseek.com/v1"
DEFAULT_API_KEY_ENV: str = "DEEPSEEK_API_KEY"
DEFAULT_MODEL: str = "deepseek-chat"
REASONER_MODEL: str = "deepseek-reasoner"


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek-V3 (chat) and DeepSeek-R1 (reasoner) provider."""

    name: str = "deepseek"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        timeout_ms: int = 8000,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key or os.environ.get(api_key_env),
            api_key_env=api_key_env,
            name=self.name,
            timeout_ms=timeout_ms,
        )


__all__ = [
    "DeepSeekProvider",
    "DEFAULT_BASE_URL",
    "DEFAULT_API_KEY_ENV",
    "DEFAULT_MODEL",
    "REASONER_MODEL",
]
