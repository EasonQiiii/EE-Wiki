"""Configuration loading for EE-Wiki."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from ee_wiki.common.errors import ConfigError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig

logger = get_logger(__name__)


def find_repo_root(start: Path | None = None) -> Path:
    """Locate the repository root by walking up for ``pyproject.toml``.

    Args:
        start: Directory to begin the search from. Defaults to the current directory.

    Returns:
        Absolute path to the repository root.

    Raises:
        ConfigError: If no ``pyproject.toml`` is found.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ConfigError(f"Could not find pyproject.toml from {current}")


@dataclass(frozen=True)
class AppConfig:
    """Loaded application configuration."""

    repo_root: Path
    raw_dir: Path
    processed_dir: Path
    indexes_dir: Path
    graph_dir: Path
    models_dir: Path
    scope_inheritance: bool
    data_layout: DataLayoutConfig


def _resolve_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (repo_root / path).resolve()


def _data_root(repo_root: Path) -> Path:
    """Return the ``data/`` directory, honoring ``EE_WIKI_DATA_DIR`` when set."""
    override = os.environ.get("EE_WIKI_DATA_DIR")
    if override:
        path = Path(override)
        return path if path.is_absolute() else (repo_root / path).resolve()
    return (repo_root / "data").resolve()


def load_config(
    config_path: Path | None = None,
    repo_root: Path | None = None,
) -> AppConfig:
    """Load YAML configuration and apply environment overrides.

    Args:
        config_path: Optional explicit path to ``default.yaml``.
        repo_root: Optional repository root. Inferred when omitted.

    Returns:
        Parsed :class:`AppConfig`.

    Raises:
        ConfigError: If the config file is missing or malformed.
    """
    root = repo_root or find_repo_root()
    path = config_path or (root / "config" / "default.yaml")
    if not path.is_file():
        raise ConfigError(f"Configuration file not found: {path}")

    try:
        with path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Configuration root must be a mapping: {path}")

    data = raw.get("data", {})
    retrieval = raw.get("retrieval", {})
    data_layout = raw.get("data_layout", {})
    models = raw.get("models", {})

    document_type_folders = data_layout.get("document_type_folders", {})
    if not isinstance(document_type_folders, dict) or not document_type_folders:
        raise ConfigError("data_layout.document_type_folders must be a non-empty mapping")

    data_parent = _data_root(root)
    raw_dir = data_parent / Path(data.get("raw_dir", "data/raw")).name
    processed_dir = data_parent / Path(data.get("processed_dir", "data/processed")).name
    indexes_dir = data_parent / Path(data.get("indexes_dir", "data/indexes")).name
    graph_dir = data_parent / Path(data.get("graph_dir", "data/graph")).name

    layout = DataLayoutConfig(
        enterprise_project=str(data_layout.get("enterprise_project", "global")),
        project_shared_build=str(data_layout.get("project_shared_build", "common")),
        document_type_folders={str(k): str(v) for k, v in document_type_folders.items()},
        raw_dir=raw_dir,
        processed_dir=processed_dir,
    )

    config = AppConfig(
        repo_root=root,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        indexes_dir=indexes_dir,
        graph_dir=graph_dir,
        models_dir=_resolve_path(root, models.get("base_dir", "models")),
        scope_inheritance=bool(retrieval.get("scope_inheritance", True)),
        data_layout=layout,
    )
    logger.debug("Loaded config from %s (raw_dir=%s)", path, config.raw_dir)
    return config
