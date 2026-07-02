"""Abstract interfaces for LLM backends."""

from __future__ import annotations

from typing import Protocol


class LlmBackend(Protocol):
    """Offline text generation backend."""

    def generate(self, prompt: str, *, max_new_tokens: int = 1024) -> str:
        """Generate a completion for the given prompt.

        Args:
            prompt: Fully rendered prompt text.
            max_new_tokens: Maximum tokens to generate.

        Returns:
            Generated text from the model.
        """
        ...
