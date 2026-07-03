"""Shared LLM backend errors."""


class LlmLoadError(RuntimeError):
    """LLM weights could not be loaded."""


class LlmTimeoutError(RuntimeError):
    """LLM generation exceeded the configured time limit."""
