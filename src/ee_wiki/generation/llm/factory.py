"""Construct LLM backends from application configuration."""

from __future__ import annotations

from ee_wiki.common.config import AppConfig
from ee_wiki.common.errors import ConfigError
from ee_wiki.common.types import ModelsConfig
from ee_wiki.generation.llm.errors import LlmLoadError
from ee_wiki.generation.llm.format import is_mlx_quantized_checkpoint
from ee_wiki.protocols.llm import LlmBackend


def build_llm_backend(config: AppConfig) -> LlmBackend:
    """Return the configured offline LLM backend.

    Args:
        config: Loaded application configuration.

    Returns:
        An implementation of :class:`~ee_wiki.protocols.llm.LlmBackend`.

    Raises:
        RuntimeError: If the model path for ``generation.llm_backend`` is not configured.
        ConfigError: If ``generation.llm_backend`` is unsupported.
    """
    backend = config.generation.llm_backend
    max_new_tokens = config.generation.max_new_tokens

    if backend not in {"mlx", "transformers"}:
        raise ConfigError(f"Unsupported generation.llm_backend: {backend!r}")

    llm_path = config.models.resolve_llm_model(backend)
    if llm_path is None:
        key = ModelsConfig.llm_config_key(backend)
        raise RuntimeError(
            f"models.{key} is not configured for generation.llm_backend={backend!r}"
        )

    if backend == "mlx":
        from ee_wiki.generation.llm.mlx import MlxLlmBackend

        return MlxLlmBackend(llm_path, max_new_tokens=max_new_tokens)

    if backend == "transformers":
        if is_mlx_quantized_checkpoint(llm_path):
            raise LlmLoadError(
                f"{llm_path.name} is an MLX-quantized checkpoint and cannot be loaded with "
                "generation.llm_backend=transformers. Set generation.llm_backend: mlx, or point "
                "models.llm_transformers_model at a standard Hugging Face weights folder."
            )
        from ee_wiki.generation.llm.local import LocalLlmBackend

        return LocalLlmBackend(llm_path, max_new_tokens=max_new_tokens)
