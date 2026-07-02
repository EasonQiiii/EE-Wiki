"""Local transformers causal LM backend."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)


def _resolve_torch_device() -> tuple[str, object]:
    import torch

    if torch.cuda.is_available():
        return "cuda", torch.device("cuda")
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps", torch.device("mps")
    return "cpu", torch.device("cpu")


class LocalLlmBackend:
    """Generate text with a local ``transformers`` causal language model."""

    def __init__(self, model_path: Path, *, max_new_tokens: int = 1024) -> None:
        self._model_path = model_path
        self._max_new_tokens = max_new_tokens
        self._device_name, self._device = _resolve_torch_device()
        self._tokenizer = None
        self._model = None

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info("Loading local LLM from %s on %s", self._model_path, self._device_name)
        self._tokenizer = AutoTokenizer.from_pretrained(str(self._model_path))
        self._model = AutoModelForCausalLM.from_pretrained(
            str(self._model_path),
            torch_dtype="auto",
        ).to(self._device)
        self._model.eval()

    def generate(self, prompt: str, *, max_new_tokens: int | None = None) -> str:
        """Generate a completion for the given prompt.

        Args:
            prompt: Fully rendered prompt text.
            max_new_tokens: Optional override for generation length.

        Returns:
            Generated text with prompt tokens stripped when possible.
        """
        import torch

        self._ensure_loaded()
        assert self._tokenizer is not None
        assert self._model is not None

        token_budget = max_new_tokens or self._max_new_tokens
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._device)
        input_len = inputs["input_ids"].shape[-1]

        with torch.no_grad():
            output = self._model.generate(
                **inputs,
                max_new_tokens=token_budget,
                do_sample=False,
            )

        generated = output[0][input_len:]
        text = self._tokenizer.decode(generated, skip_special_tokens=True).strip()
        return text
