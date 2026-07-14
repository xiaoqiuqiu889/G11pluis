"""通义千问 (Qwen) provider via DashScope's OpenAI-compatible mode.

DashScope exposes an OpenAI-compatible endpoint at
``https://dashscope.aliyuncs.com/compatible-mode/v1``.  We use it
as the second real provider so the routing layer always has at
least one Chinese-domestic fallback when DeepSeek has a blip.

API key
-------
Read from the ``DASHSCOPE_API_KEY`` environment variable.  Never
hard-code.
"""

from __future__ import annotations

import os

from .openai_compatible import OpenAICompatibleProvider

DEFAULT_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_API_KEY_ENV: str = "DASHSCOPE_API_KEY"
DEFAULT_MODEL: str = "qwen-plus"
LONG_MODEL: str = "qwen-max"
FAST_MODEL: str = "qwen-turbo"


class QwenProvider(OpenAICompatibleProvider):
    """通义千问 (Qwen) provider."""

    name: str = "qwen"

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
    "QwenProvider",
    "DEFAULT_BASE_URL",
    "DEFAULT_API_KEY_ENV",
    "DEFAULT_MODEL",
    "LONG_MODEL",
    "FAST_MODEL",
]
