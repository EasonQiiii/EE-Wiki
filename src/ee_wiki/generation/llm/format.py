"""Detect local model checkpoint formats for backend selection."""

from __future__ import annotations

import json
from pathlib import Path


def is_mlx_quantized_checkpoint(model_path: Path) -> bool:
    """Return True when ``model_path`` looks like an ``mlx-lm`` 4-bit checkpoint.

    MLX converted weights keep ``quantization_config`` with ``bits`` / ``group_size``
    but no Hugging Face ``quant_method`` field, which ``transformers`` expects.
    """
    config_path = model_path / "config.json"
    if not config_path.is_file():
        return False

    config = json.loads(config_path.read_text(encoding="utf-8"))
    quantization = config.get("quantization_config")
    if not isinstance(quantization, dict):
        return False

    return "bits" in quantization and "quant_method" not in quantization
