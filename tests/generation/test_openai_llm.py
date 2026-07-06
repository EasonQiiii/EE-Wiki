"""Tests for OpenAI-compatible HTTP LLM backend."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import httpx
import pytest

from ee_wiki.generation.llm.errors import LlmLoadError, LlmTimeoutError
from ee_wiki.generation.llm.openai_http import OpenAiLlmBackend


class _MockStreamResponse:
    """Minimal httpx response for ``client.stream`` context manager."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        lines: list[str] | None = None,
        body: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self._lines = lines or []
        self._body = body

    def __enter__(self) -> _MockStreamResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def iter_lines(self) -> list[str]:
        return iter(self._lines)

    def read(self) -> bytes:
        return self._body


def _backend() -> OpenAiLlmBackend:
    return OpenAiLlmBackend(
        base_url="http://127.0.0.1:8000/v1/",
        model="test-model",
        max_new_tokens=128,
        timeout_seconds=30,
    )


def test_generate_stream_yields_delta_chunks() -> None:
    backend = _backend()
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        "data: [DONE]",
    ]
    mock_client = MagicMock()
    mock_client.stream.return_value = _MockStreamResponse(lines=lines)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("ee_wiki.generation.llm.openai_http._import_httpx") as import_httpx:
        import_httpx.return_value.Client.return_value = mock_client
        chunks = list(backend.generate_stream("prompt text"))

    assert chunks == ["Hel", "lo"]
    payload = mock_client.stream.call_args.kwargs["json"]
    assert payload["model"] == "test-model"
    assert payload["stream"] is True
    assert payload["messages"] == [{"role": "user", "content": "prompt text"}]


def test_generate_joins_stream_chunks() -> None:
    backend = _backend()
    lines = [
        'data: {"choices":[{"delta":{"content":"answer"}}]}',
        "data: [DONE]",
    ]
    mock_client = MagicMock()
    mock_client.stream.return_value = _MockStreamResponse(lines=lines)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("ee_wiki.generation.llm.openai_http._import_httpx") as import_httpx:
        import_httpx.return_value.Client.return_value = mock_client
        text = backend.generate("prompt")

    assert text == "answer"


def test_generate_stream_honours_cancel_event() -> None:
    backend = _backend()
    cancel = threading.Event()
    cancel.set()
    chunks = list(backend.generate_stream("prompt", cancel_event=cancel))
    assert chunks == []


def test_generate_stream_raises_on_http_error() -> None:
    backend = _backend()
    mock_client = MagicMock()
    mock_client.stream.return_value = _MockStreamResponse(
        status_code=503,
        body=b"server overloaded",
    )
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("ee_wiki.generation.llm.openai_http._import_httpx") as import_httpx:
        import_httpx.return_value.Client.return_value = mock_client
        with pytest.raises(LlmLoadError, match="503"):
            list(backend.generate_stream("prompt"))


def test_generate_blocking_parses_message_content() -> None:
    backend = _backend()
    response = httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"role": "assistant", "content": "static reply"}},
            ],
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = request.read()
        assert b'"stream": false' in body or b'"stream":false' in body
        return response

    transport = httpx.MockTransport(handler)
    with patch("ee_wiki.generation.llm.openai_http._import_httpx", return_value=httpx):
        with httpx.Client(transport=transport) as _:
            with patch("httpx.Client", return_value=httpx.Client(transport=transport)):
                text = backend.generate_blocking("hello")

    assert text == "static reply"


def test_generate_stream_timeout_maps_to_llm_timeout_error() -> None:
    backend = _backend()
    mock_client = MagicMock()
    mock_client.stream.side_effect = httpx.TimeoutException("timed out")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("ee_wiki.generation.llm.openai_http._import_httpx") as import_httpx:
        import_httpx.return_value.Client.return_value = mock_client
        with pytest.raises(LlmTimeoutError):
            list(backend.generate_stream("prompt"))
