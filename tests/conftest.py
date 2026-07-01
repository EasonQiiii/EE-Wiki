"""Pytest fixtures for EE-Wiki."""

from __future__ import annotations

from pathlib import Path

import pytest

from ee_wiki.common.config import load_config


@pytest.fixture
def repo_root() -> Path:
    """Repository root for tests."""
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def app_config(repo_root: Path):
    """Loaded application configuration."""
    return load_config(repo_root=repo_root)


@pytest.fixture
def data_layout(app_config):
    """Data layout section from application config."""
    return app_config.data_layout
