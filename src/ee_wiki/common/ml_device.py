"""Torch device resolution for offline ML workloads."""

from __future__ import annotations

from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)

_VALID_DEVICES = frozenset({"auto", "cpu", "mps", "cuda"})


def resolve_torch_device(setting: str) -> str:
    """Resolve a configured device name to a concrete torch device label.

    Args:
        setting: ``auto``, ``cpu``, ``mps``, or ``cuda``.

    Returns:
        One of ``cpu``, ``mps``, or ``cuda``.

    Raises:
        ValueError: If ``setting`` is not a supported device name.
    """
    normalized = setting.casefold().strip()
    if normalized not in _VALID_DEVICES:
        raise ValueError(f"Unsupported torch device setting: {setting!r}")

    if normalized != "auto":
        return normalized

    try:
        import torch
    except ImportError:
        return "cpu"

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def embedding_batch_size(device: str, configured: int) -> int:
    """Return a safe embedding batch size for the target device.

    Args:
        device: Resolved torch device label.
        configured: User-configured batch size.

    Returns:
        Batch size capped for memory-constrained devices.
    """
    if device == "mps":
        return min(configured, 2)
    return configured


def is_mps_embedding_runtime_error(exc: BaseException) -> bool:
    """Return whether an exception looks like a known MPS embedding failure."""
    message = str(exc).casefold()
    return "invalid buffer size" in message or "mps" in message
