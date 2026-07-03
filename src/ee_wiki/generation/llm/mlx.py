"""MLX quantized LLM backend for Apple Silicon."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.generation.llm.errors import LlmLoadError
from ee_wiki.generation.llm.timeout import check_stream_timeout
from ee_wiki.generation.prompt_stats import prompt_size_fields

logger = get_logger(__name__)


def _import_mlx_lm():
    """Import ``mlx_lm`` or raise a clear load error."""
    try:
        import mlx_lm
    except ImportError as exc:
        raise LlmLoadError(
            "mlx-lm is required for generation.llm_backend=mlx: "
            "pip install -e '.[dev,ml,mlx,api]'"
        ) from exc
    return mlx_lm


def _format_prompt(tokenizer: object, prompt: str) -> str:
    """Apply the model chat template when available."""
    apply_chat_template = getattr(tokenizer, "apply_chat_template", None)
    chat_template = getattr(tokenizer, "chat_template", None)
    if not callable(apply_chat_template) or not chat_template:
        return prompt

    messages = [{"role": "user", "content": prompt}]
    try:
        return apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        return apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )


class MlxLlmBackend:
    """Generate text with a local ``mlx-lm`` quantized model."""

    def __init__(
        self,
        model_path: Path,
        *,
        max_new_tokens: int = 1024,
        timeout_seconds: float | None = None,
    ) -> None:
        self._model_path = model_path
        self._max_new_tokens = max_new_tokens
        self._timeout_seconds = timeout_seconds
        self._model = None
        self._tokenizer = None
        self._load_lock = threading.Lock()
        self._generate_lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        with self._load_lock:
            if self._model is not None and self._tokenizer is not None:
                return
            mlx_lm = _import_mlx_lm()

            model_ref = str(self._model_path)
            if not self._model_path.is_dir() and not self._model_path.is_file():
                raise LlmLoadError(f"MLX model path not found: {self._model_path}")

            logger.info("Loading MLX LLM from %s", model_ref)
            started = time.monotonic()
            self._model, self._tokenizer = mlx_lm.load(model_ref)
            logger.info("MLX LLM ready in %.1fs", time.monotonic() - started)

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
        result = "".join(parts).strip()
        logger.info(
            "MLX generation finished in %.1fs (%d chars)",
            time.monotonic() - started,
            len(result),
        )
        return result

    def generate_stream(
        self,
        prompt: str,
        *,
        max_new_tokens: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[str]:
        """Stream generated text chunks for the given prompt."""
        mlx_lm = _import_mlx_lm()
        self._ensure_loaded()
        assert self._model is not None
        assert self._tokenizer is not None

        if cancel_event and cancel_event.is_set():
            return

        token_budget = max_new_tokens or self._max_new_tokens
        formatted = _format_prompt(self._tokenizer, prompt)
        size = prompt_size_fields(formatted)
        logger.info(
            "MLX stream generation started "
            "(max_new_tokens=%d, prompt_chars=%d, prompt_tokens_est=%d)",
            token_budget,
            size["prompt_chars"],
            size["prompt_tokens_est"],
        )

        cancelled = False
        started = time.monotonic()
        token_stream = mlx_lm.stream_generate(
            self._model,
            self._tokenizer,
            formatted,
            max_tokens=token_budget,
        )
        try:
            while True:
                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    break
                with self._generate_lock:
                    check_stream_timeout(
                        started,
                        timeout_seconds=self._timeout_seconds,
                        label="MLX stream generation",
                    )
                    try:
                        response = next(token_stream)
                    except StopIteration:
                        break
                    fragment = response.text or ""
                if fragment:
                    yield fragment
        finally:
            close = getattr(token_stream, "close", None)
            if callable(close):
                close()

        if cancelled:
            logger.info("MLX stream generation cancelled")
