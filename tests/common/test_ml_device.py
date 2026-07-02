"""Tests for torch device resolution."""

from __future__ import annotations

import pytest

from ee_wiki.common.ml_device import (
    embedding_batch_size,
    is_mps_embedding_runtime_error,
    resolve_torch_device,
)


def test_resolve_torch_device_explicit_cpu() -> None:
    assert resolve_torch_device("cpu") == "cpu"


def test_resolve_torch_device_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        resolve_torch_device("tpu")


def test_embedding_batch_size_caps_mps() -> None:
    assert embedding_batch_size("mps", 8) == 2
    assert embedding_batch_size("cpu", 8) == 8


def test_is_mps_embedding_runtime_error() -> None:
    assert is_mps_embedding_runtime_error(RuntimeError("Invalid buffer size: 32.00 GiB"))
    assert not is_mps_embedding_runtime_error(RuntimeError("disk full"))
