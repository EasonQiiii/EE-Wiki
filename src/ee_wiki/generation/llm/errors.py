"""Shared LLM backend errors."""


class LlmLoadError(RuntimeError):
    """LLM weights could not be loaded."""
