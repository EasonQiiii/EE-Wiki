"""Local transformers causal LM backend."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.generation.llm.errors import LlmLoadError
from ee_wiki.generation.llm.timeout import check_stream_timeout

logger = get_logger(__name__)


def _resolve_torch_device() -> tuple[str, object]:
    import torch

    if torch.cuda.is_available():
        return "cuda", torch.device("cuda")
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps", torch.device("mps")
    return "cpu", torch.device("cpu")


def _move_inputs_to_device(inputs: object, device: object) -> dict:
    if isinstance(inputs, dict):
        import torch

        return {
            key: value.to(device) if isinstance(value, torch.Tensor) else value
            for key, value in inputs.items()
        }
    return inputs.to(device)


def detect_model_kind(model_path: Path) -> str:
    """Return ``causal`` or ``qwen3_vl`` for a local model directory.

    Raises:
        LlmLoadError: If the directory is missing or uses an unsupported format.
    """
    config_path = model_path / "config.json"
    if not config_path.is_file():
        raise LlmLoadError(f"Model config not found: {config_path}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    model_type = str(config.get("model_type", ""))
    architectures = [str(item) for item in config.get("architectures", [])]

    if config.get("quantization_config") and any("Qwen3_5" in arch for arch in architectures):
        raise LlmLoadError(
            f"{model_path.name} is an NVFP4 quantized checkpoint and is not supported by "
            "EE-Wiki's transformers backend. Set models.llm_transformers_model to a standard "
            "Hugging Face weights folder such as Qwen3-VL-8B-Instruct in config/default.yaml."
        )

    if model_type == "qwen3_vl" or any("Qwen3VL" in arch for arch in architectures):
        return "qwen3_vl"
    return "causal"


def _format_causal_prompt(tokenizer: object, prompt: str) -> str:
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


class LocalLlmBackend:
    """Generate text with a local ``transformers`` model."""

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
        self._device_name, self._device = _resolve_torch_device()
        self._model_kind = detect_model_kind(model_path)
        self._tokenizer = None
        self._processor = None
        self._model = None
        self._load_lock = threading.Lock()
        self._generate_lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            if self._model_kind == "qwen3_vl":
                self._load_qwen3_vl()
            else:
                self._load_causal()

    def _load_causal(self) -> None:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info(
            "Loading causal LLM from %s on %s",
            self._model_path,
            self._device_name,
        )
        self._tokenizer = AutoTokenizer.from_pretrained(str(self._model_path))
        self._model = AutoModelForCausalLM.from_pretrained(
            str(self._model_path),
            torch_dtype="auto",
        ).to(self._device)
        self._model.eval()

    def _load_qwen3_vl(self) -> None:
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

        dtype = torch.float16 if self._device_name in {"cuda", "mps"} else torch.float32
        logger.info(
            "Loading Qwen3-VL LLM from %s on %s (dtype=%s)",
            self._model_path,
            self._device_name,
            dtype,
        )
        self._processor = AutoProcessor.from_pretrained(
            str(self._model_path),
            trust_remote_code=True,
        )
        if self._device_name == "cuda":
            self._model = Qwen3VLForConditionalGeneration.from_pretrained(
                str(self._model_path),
                torch_dtype=dtype,
                device_map="auto",
                trust_remote_code=True,
            )
        else:
            self._model = Qwen3VLForConditionalGeneration.from_pretrained(
                str(self._model_path),
                torch_dtype=dtype,
                trust_remote_code=True,
            ).to(self._device)
        self._model.eval()

    def _prepare_generation_inputs(self, prompt: str) -> tuple[dict, int]:
        if self._model_kind == "qwen3_vl":
            assert self._processor is not None
            assert self._model is not None
            messages = [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ]
            inputs = self._processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
            inputs = _move_inputs_to_device(inputs, self._model.device)
            return inputs, int(inputs["input_ids"].shape[-1])

        assert self._tokenizer is not None
        formatted = _format_causal_prompt(self._tokenizer, prompt)
        inputs = self._tokenizer(formatted, return_tensors="pt").to(self._device)
        return inputs, int(inputs["input_ids"].shape[-1])

    def _decode_generation(self, inputs: dict, output: object, input_len: int) -> str:
        if self._model_kind == "qwen3_vl":
            assert self._processor is not None
            input_ids = inputs["input_ids"]
            generated = output
            trimmed = [
                out_ids[len(in_ids) :]
                for in_ids, out_ids in zip(input_ids, generated, strict=False)
            ]
            return self._processor.batch_decode(
                trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0].strip()

        assert self._tokenizer is not None
        generated = output[0][input_len:]
        return self._tokenizer.decode(generated, skip_special_tokens=True).strip()

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
            "LLM generation finished in %.1fs (%d chars)",
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
        """Stream generated text chunks for the given prompt."""
        from threading import Thread

        from transformers import TextIteratorStreamer

        if cancel_event and cancel_event.is_set():
            return

        self._ensure_loaded()
        assert self._model is not None

        token_budget = max_new_tokens or self._max_new_tokens
        inputs, _input_len = self._prepare_generation_inputs(prompt)
        decode_source = self._processor if self._model_kind == "qwen3_vl" else self._tokenizer
        assert decode_source is not None

        streamer = TextIteratorStreamer(
            decode_source,
            skip_prompt=True,
            skip_special_tokens=True,
        )
        generation_kwargs = {
            **inputs,
            "max_new_tokens": token_budget,
            "do_sample": False,
            "streamer": streamer,
        }

        cancelled = False
        started = time.monotonic()
        logger.info("LLM stream generation started (max_new_tokens=%d)", token_budget)
        with self._generate_lock:
            thread = Thread(
                target=self._model.generate,
                kwargs=generation_kwargs,
                daemon=True,
            )
            thread.start()
            try:
                for text in streamer:
                    check_stream_timeout(
                        started,
                        timeout_seconds=self._timeout_seconds,
                        label="LLM stream generation",
                    )
                    if cancel_event and cancel_event.is_set():
                        cancelled = True
                        break
                    if text:
                        yield text
            finally:
                if not cancelled:
                    thread.join()
                elif thread.is_alive():
                    logger.info("LLM stream generation abandoned (daemon thread)")

        if cancelled:
            logger.info("LLM stream generation cancelled")
