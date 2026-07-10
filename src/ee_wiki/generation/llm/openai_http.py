"""OpenAI-compatible HTTP LLM backend for external inference servers."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ee_wiki.common.logging import get_logger
from ee_wiki.generation.llm.errors import LlmLoadError, LlmTimeoutError
from ee_wiki.generation.llm.timeout import call_with_timeout, check_stream_timeout
from ee_wiki.generation.prompt_stats import prompt_size_fields

logger = get_logger(__name__)

try:
    import httpx as _HTTPX
except ImportError:
    _HTTPX = None  # type: ignore[assignment]


def _import_httpx():
    if _HTTPX is None:
        raise LlmLoadError(
            "httpx is required for generation.llm_backend=openai: "
            "pip install -e '.[api]'"
        )
    return _HTTPX


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _auth_headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _build_payload(
    *,
    model: str,
    prompt: str,
    max_tokens: int,
    stream: bool,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": stream,
        "temperature": 0,
    }


def _extract_message_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _extract_delta_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content")
    return content if isinstance(content, str) else ""


def _parse_sse_data_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped.startswith("data:"):
        return None
    payload = stripped[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        logger.debug("Skipping non-JSON SSE payload: %s", payload[:80])
        return None
    return parsed if isinstance(parsed, dict) else None


@dataclass
class OpenAiLlmBackend:
    """Delegate generation to an OpenAI-compatible chat completions API."""

    base_url: str
    model: str
    max_new_tokens: int = 1024
    api_key: str | None = None
    timeout_seconds: float | None = None

    def _request_timeout(self) -> float | None:
        if self.timeout_seconds is None or self.timeout_seconds <= 0:
            return None
        return float(self.timeout_seconds)

    def _chat_completions_url(self) -> str:
        return f"{_normalize_base_url(self.base_url)}/chat/completions"

    def _get_client(self) -> _HTTPX.Client:
        """Return a long-lived, reused httpx.Client (connection pool).

        The backend is a process-wide singleton, so creating the client once and
        reusing it across requests avoids per-request TCP/TLS handshakes under
        concurrent load. httpx.Client is thread-safe for sync calls.
        """
        httpx = _import_httpx()
        client = getattr(self, "_client", None)
        if client is None:
            client = httpx.Client(
                timeout=self._request_timeout(),
                headers=_auth_headers(self.api_key),
            )
            self._client = client
        return client

    def generate(
        self,
        prompt: str,
        *,
        max_new_tokens: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Generate a completion for the given prompt."""
        started = time.monotonic()
        parts: list[str] = []
        for chunk in self.generate_stream(
            prompt,
            max_new_tokens=max_new_tokens,
            cancel_event=cancel_event,
        ):
            parts.append(chunk)
        text = "".join(parts).strip()
        logger.info(
            "OpenAI HTTP generation finished in %.1fs (%d chars)",
            time.monotonic() - started,
            len(text),
        )
        return text

    def generate_stream(
        self,
        prompt: str,
        *,
        max_new_tokens: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[str]:
        """Stream generated text chunks from the remote chat API."""
        if cancel_event and cancel_event.is_set():
            return

        token_budget = max_new_tokens or self.max_new_tokens
        size = prompt_size_fields(prompt)
        logger.info(
            "OpenAI HTTP stream started (model=%s, max_tokens=%d, prompt_chars=%d)",
            self.model,
            token_budget,
            size["prompt_chars"],
        )

        payload = _build_payload(
            model=self.model,
            prompt=prompt,
            max_tokens=token_budget,
            stream=True,
        )
        headers = {
            "Content-Type": "application/json",
            **_auth_headers(self.api_key),
        }
        started = time.monotonic()
        timeout = self._request_timeout()

        client = self._get_client()
        try:
            with client.stream(
                "POST",
                self._chat_completions_url(),
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code >= 400:
                    body = response.read().decode("utf-8", errors="replace")
                    raise LlmLoadError(
                        f"OpenAI HTTP chat completion failed "
                        f"({response.status_code}): {body[:500]}"
                    )

                for line in response.iter_lines():
                    check_stream_timeout(
                        started,
                        timeout_seconds=self.timeout_seconds,
                        label="OpenAI HTTP stream generation",
                    )
                    if cancel_event and cancel_event.is_set():
                        logger.info("OpenAI HTTP stream generation cancelled")
                        return
                    if not line:
                        continue
                    data = _parse_sse_data_line(line)
                    if data is None:
                        continue
                    fragment = _extract_delta_content(data)
                    if fragment:
                        yield fragment
        except _HTTPX.TimeoutException as exc:
            limit = f"{timeout:.0f}s" if timeout else "configured timeout"
            raise LlmTimeoutError(
                f"OpenAI HTTP stream generation exceeded {limit}"
            ) from exc
        except _HTTPX.HTTPError as exc:
            raise LlmLoadError(f"OpenAI HTTP request failed: {exc}") from exc

    def generate_blocking(self, prompt: str, *, max_new_tokens: int | None = None) -> str:
        """Non-streaming completion (used internally when streaming is disabled)."""
        token_budget = max_new_tokens or self.max_new_tokens
        payload = _build_payload(
            model=self.model,
            prompt=prompt,
            max_tokens=token_budget,
            stream=False,
        )
        headers = {
            "Content-Type": "application/json",
            **_auth_headers(self.api_key),
        }

        def _post() -> str:
            client = self._get_client()
            response = client.post(
                self._chat_completions_url(),
                json=payload,
                headers=headers,
            )
            if response.status_code >= 400:
                raise LlmLoadError(
                    f"OpenAI HTTP chat completion failed "
                    f"({response.status_code}): {response.text[:500]}"
                )
            data = response.json()
            if not isinstance(data, dict):
                raise LlmLoadError("OpenAI HTTP response was not a JSON object")
            return _extract_message_content(data).strip()

        return call_with_timeout(
            _post,
            timeout_seconds=self.timeout_seconds,
            label="OpenAI HTTP generation",
        )
