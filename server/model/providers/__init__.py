"""LLM provider package — concrete and base providers.

Public API
----------
* :class:`Provider`            — abstract base
* :class:`OpenAICompatibleProvider` — OpenAI-compatible wire format
* :class:`MockProvider`        — deterministic mock for tests
* :class:`DeepSeekProvider`    — DeepSeek-V3 / R1
* :class:`QwenProvider`        — 通义千问 (Qwen) via DashScope
"""

from __future__ import annotations

from .base import Provider
from .deepseek import DeepSeekProvider
from .mock import MockProvider
from .openai_compatible import OpenAICompatibleProvider
from .qwen import QwenProvider

__all__ = [
    "Provider",
    "OpenAICompatibleProvider",
    "MockProvider",
    "DeepSeekProvider",
    "QwenProvider",
]
