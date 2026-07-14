"""Unit tests for the LLM providers.

Coverage
--------

* :class:`MockProvider` returns scripted responses in order
* :class:`MockProvider` falls through to default when queue empty
* :class:`OpenAICompatibleProvider` builds the right URL + headers
* :class:`OpenAICompatibleProvider` raises ProviderTimeoutError on
  httpx.TimeoutException
* :class:`OpenAICompatibleProvider` raises ProviderHTTPError on
  non-2xx status
* :class:`OpenAICompatibleProvider` raises ProviderParseError on
  non-JSON body
* :class:`DeepSeekProvider` and :class:`QwenProvider` use the
  right base URLs and env-var names
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "server"))

from model import (  # noqa: E402
    DeepSeekProvider,
    Message,
    MessageRole,
    MockProvider,
    OpenAICompatibleProvider,
    ProviderResult,
    QwenProvider,
)
from model.exceptions import (  # noqa: E402
    ProviderHTTPError,
    ProviderParseError,
    ProviderTimeoutError,
)


def _ok_response(content: str = "hello", input_tokens: int = 10, output_tokens: int = 10) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": content}, "finish_reason": "stop"},
            ],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
            },
        },
    )


# ---------------------------------------------------------------------------
# MockProvider
# ---------------------------------------------------------------------------


class MockProviderTests(unittest.TestCase):

    def test_returns_scripted_response(self) -> None:
        mock = MockProvider(responses=[
            ProviderResult(content="first", model="mock", provider="mock"),
        ])
        result = mock.complete(
            model="m", messages=[Message(role=MessageRole.USER, content="hi")],
            temperature=0.4, max_output_tokens=100, timeout_ms=1000,
        )
        self.assertEqual(result.content, "first")

    def test_falls_through_to_default_when_empty(self) -> None:
        mock = MockProvider(default_response=ProviderResult(
            content="default", model="default", provider="mock",
        ))
        result = mock.complete(
            model="m", messages=[Message(role=MessageRole.USER, content="hi")],
            temperature=0.4, max_output_tokens=100, timeout_ms=1000,
        )
        self.assertEqual(result.content, "default")

    def test_raise_after_triggers_timeout(self) -> None:
        mock = MockProvider(
            responses=[ProviderResult(content="ok", model="m", provider="mock")],
            raise_after=0,
        )
        with self.assertRaises(ProviderTimeoutError):
            mock.complete(
                model="m", messages=[Message(role=MessageRole.USER, content="hi")],
                temperature=0.4, max_output_tokens=100, timeout_ms=1000,
            )

    def test_call_count_increments(self) -> None:
        mock = MockProvider()
        for _ in range(3):
            mock.complete(
                model="m", messages=[Message(role=MessageRole.USER, content="hi")],
                temperature=0.4, max_output_tokens=100, timeout_ms=1000,
            )
        self.assertEqual(mock._call_count, 3)

    def test_push_appends_to_queue(self) -> None:
        mock = MockProvider()
        mock.push(ProviderResult(content="pushed", model="m", provider="mock"))
        result = mock.complete(
            model="m", messages=[Message(role=MessageRole.USER, content="hi")],
            temperature=0.4, max_output_tokens=100, timeout_ms=1000,
        )
        self.assertEqual(result.content, "pushed")


# ---------------------------------------------------------------------------
# OpenAICompatibleProvider (with mocked httpx)
# ---------------------------------------------------------------------------


class OpenAICompatibleProviderTests(unittest.TestCase):

    def test_builds_correct_url_and_headers(self) -> None:
        p = OpenAICompatibleProvider(
            base_url="https://api.example.com/v1",
            api_key="test-key-123",
        )
        # Verify the URL construction
        with patch.object(httpx.Client, "post", return_value=_ok_response()) as m:
            p.complete(
                model="some-model",
                messages=[Message(role=MessageRole.USER, content="hi")],
                temperature=0.5, max_output_tokens=100, timeout_ms=1000,
            )
        args, kwargs = m.call_args
        self.assertEqual(args[0], "https://api.example.com/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key-123")
        body = kwargs["json"]
        self.assertEqual(body["model"], "some-model")
        self.assertEqual(body["temperature"], 0.5)
        self.assertEqual(body["max_tokens"], 100)
        self.assertEqual(body["stream"], False)
        self.assertEqual(body["messages"], [{"role": "user", "content": "hi"}])

    def test_parses_response(self) -> None:
        p = OpenAICompatibleProvider(base_url="https://x", api_key="k")
        with patch.object(httpx.Client, "post", return_value=_ok_response(
            content="model said hi", input_tokens=12, output_tokens=34,
        )):
            r = p.complete(
                model="m", messages=[Message(role=MessageRole.USER, content="hi")],
                temperature=0.4, max_output_tokens=100, timeout_ms=1000,
            )
        self.assertEqual(r.content, "model said hi")
        self.assertEqual(r.input_tokens, 12)
        self.assertEqual(r.output_tokens, 34)
        self.assertEqual(r.finish_reason, "stop")

    def test_timeout_raises_provider_timeout(self) -> None:
        p = OpenAICompatibleProvider(base_url="https://x", api_key="k")
        with patch.object(httpx.Client, "post", side_effect=httpx.TimeoutException("boom")):
            with self.assertRaises(ProviderTimeoutError):
                p.complete(
                    model="m", messages=[Message(role=MessageRole.USER, content="hi")],
                    temperature=0.4, max_output_tokens=100, timeout_ms=1000,
                )

    def test_http_error_raises_provider_http_error(self) -> None:
        p = OpenAICompatibleProvider(base_url="https://x", api_key="k")
        err_response = httpx.Response(429, text="rate limited")
        with patch.object(httpx.Client, "post", return_value=err_response):
            with self.assertRaises(ProviderHTTPError) as ctx:
                p.complete(
                    model="m", messages=[Message(role=MessageRole.USER, content="hi")],
                    temperature=0.4, max_output_tokens=100, timeout_ms=1000,
                )
        self.assertEqual(ctx.exception.status_code, 429)

    def test_invalid_json_raises_parse_error(self) -> None:
        p = OpenAICompatibleProvider(base_url="https://x", api_key="k")
        bad = httpx.Response(200, text="not json")
        with patch.object(httpx.Client, "post", return_value=bad):
            with self.assertRaises(ProviderParseError):
                p.complete(
                    model="m", messages=[Message(role=MessageRole.USER, content="hi")],
                    temperature=0.4, max_output_tokens=100, timeout_ms=1000,
                )


# ---------------------------------------------------------------------------
# DeepSeek + Qwen
# ---------------------------------------------------------------------------


class DeepSeekTests(unittest.TestCase):

    def test_default_base_url(self) -> None:
        p = DeepSeekProvider(api_key="k")
        self.assertEqual(p.base_url, "https://api.deepseek.com/v1")

    def test_default_model(self) -> None:
        from model.providers.deepseek import DEFAULT_MODEL, REASONER_MODEL
        self.assertEqual(DEFAULT_MODEL, "deepseek-chat")
        self.assertEqual(REASONER_MODEL, "deepseek-reasoner")

    def test_uses_env_var_when_no_key(self) -> None:
        import os
        os.environ["DEEPSEEK_API_KEY"] = "env-key"
        p = DeepSeekProvider()
        self.assertEqual(p._api_key, "env-key")

    def test_name_is_deepseek(self) -> None:
        p = DeepSeekProvider(api_key="k")
        self.assertEqual(p.name, "deepseek")


class QwenTests(unittest.TestCase):

    def test_default_base_url(self) -> None:
        p = QwenProvider(api_key="k")
        self.assertEqual(p.base_url, "https://dashscope.aliyuncs.com/compatible-mode/v1")

    def test_default_model(self) -> None:
        from model.providers.qwen import DEFAULT_MODEL, LONG_MODEL, FAST_MODEL
        self.assertEqual(DEFAULT_MODEL, "qwen-plus")
        self.assertEqual(LONG_MODEL, "qwen-max")
        self.assertEqual(FAST_MODEL, "qwen-turbo")

    def test_uses_env_var_when_no_key(self) -> None:
        import os
        os.environ["DASHSCOPE_API_KEY"] = "env-key-qwen"
        p = QwenProvider()
        self.assertEqual(p._api_key, "env-key-qwen")

    def test_name_is_qwen(self) -> None:
        p = QwenProvider(api_key="k")
        self.assertEqual(p.name, "qwen")


# ---------------------------------------------------------------------------
# Provider error mapping
# ---------------------------------------------------------------------------


class ProviderErrorMappingTests(unittest.TestCase):

    def test_provider_http_error_carries_body(self) -> None:
        err = ProviderHTTPError("oops", status_code=500, body="server error")
        self.assertEqual(err.status_code, 500)
        self.assertEqual(err.body, "server error")


if __name__ == "__main__":
    unittest.main()
