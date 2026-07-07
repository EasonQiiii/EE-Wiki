"""Derive document metadata from ``data/raw/`` paths."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.errors import PathMetadataError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig, Metadata

logger = get_logger(__name__)


def _relative_parts(raw_path: Path, raw_dir: Path) -> tuple[str, ...]:
    """Return path parts relative to ``raw_dir``."""
    resolved = raw_path.resolve()
    root = raw_dir.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise PathMetadataError(f"Path is not under raw_dir ({root}): {raw_path}") from exc
    return relative.parts


def _title_from_filename(filename: str) -> str:
    return Path(filename).stem or filename


def _source_file_label(raw_dir: Path, repo_root: Path | None, parts: tuple[str, ...]) -> str:
    relative = Path(*parts)
    if repo_root is not None:
        try:
            raw_prefix = raw_dir.resolve().relative_to(repo_root.resolve())
            return str(raw_prefix / relative)
        except ValueError:
            pass
    return str(Path("data/raw") / relative)


def parse_path_metadata(
    raw_path: Path,
    layout: DataLayoutConfig,
    *,
    repo_root: Path | None = None,
) -> Metadata:
    """Derive :class:`Metadata` from a file path under ``data/raw/``.

    Supports two layouts:

    - Enterprise: ``{enterprise_project}/{type_folder}/<file>``
    - Project: ``{project}/{build}/{type_folder}/<file>`` (nested subfolders allowed)

    Args:
        raw_path: Absolute or relative path to a file under ``layout.raw_dir``.
        layout: Path naming configuration from ``config/default.yaml``.
        repo_root: Optional repo root for ``source_file`` labels (e.g. ``data/raw/...``).

    Returns:
        Parsed metadata with ``project``, ``build``, and ``document_type`` set.

    Raises:
        PathMetadataError: If the path does not match the expected layout.
    """
    if raw_path.name.startswith("."):
        raise PathMetadataError(f"Ignored hidden file: {raw_path}")

    parts = _relative_parts(raw_path, layout.raw_dir)
    if len(parts) < 2:
        raise PathMetadataError(
            f"Expected at least {{project}}/{{type}}/file, got: {Path(*parts)}"
        )

    type_folders = layout.document_type_folders
    enterprise = layout.enterprise_project
    known_folders = ", ".join(sorted(type_folders))

    def _unknown_type_folder(folder: str, layout_hint: str) -> PathMetadataError:
        return PathMetadataError(
            f"Unknown type folder '{folder}' ({layout_hint}). "
            f"Add '{folder}: <document_type>' to data_layout.document_type_folders "
            f"in config/default.yaml. Known folders: {known_folders}"
        )

    # Enterprise library: global/{type}/file
    if parts[0] == enterprise:
        if len(parts) < 3:
            raise PathMetadataError(f"Missing filename under enterprise path: {Path(*parts)}")
        if parts[1] not in type_folders:
            raise _unknown_type_folder(parts[1], f"{enterprise}/{{type}}/file")
        project = enterprise
        build = enterprise
        type_folder = parts[1]
        filename = parts[-1]
    # Project library: {project}/{build}/{type}/file
    elif len(parts) >= 4:
        if parts[2] not in type_folders:
            raise _unknown_type_folder(parts[2], "{project}/{build}/{type}/file")
        project = parts[0]
        build = parts[1]
        type_folder = parts[2]
        filename = parts[-1]
    else:
        raise PathMetadataError(
            f"Path does not match enterprise ({enterprise}/{{type}}/file) or "
            f"project ({{project}}/{{build}}/{{type}}/file) layout: {Path(*parts)}"
        )

    document_type = type_folders[type_folder]
    source_file = _source_file_label(layout.raw_dir, repo_root, parts)

    metadata = Metadata(
        project=project,
        build=build,
        document_type=document_type,
        title=_title_from_filename(filename),
        source_file=source_file,
    )
    logger.debug(
        "Parsed metadata project=%s build=%s type=%s from %s",
        project,
        build,
        document_type,
        source_file,
    )
    return metadata


def expand_retrieval_scope(
    project: str,
    build: str,
    layout: DataLayoutConfig,
) -> list[tuple[str, str]]:
    """Return ``(project, build)`` pairs to search, highest priority first.

    Implements upward inheritance: build-specific → project ``common`` → enterprise ``global``.

    Args:
        project: Project name filter.
        build: Build name filter.
        layout: Path naming configuration.

    Returns:
        Ordered list of scope pairs to query.
    """
    enterprise = layout.enterprise_project
    common = layout.project_shared_build
    scopes: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(p: str, b: str) -> None:
        key = (p, b)
        if key not in seen:
            seen.add(key)
            scopes.append(key)

    if project == enterprise:
        add(enterprise, enterprise)
        return scopes

    if build and build != common:
        add(project, build)

    if project != enterprise:
        add(project, common)

    add(enterprise, enterprise)
    return scopes
