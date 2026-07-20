"""Derive document metadata from ``data/raw/`` paths (canonical hierarchy).

The canonical raw layout has three scope levels — ``product`` / ``project`` /
``build`` — plus two reserved words (``global`` and ``common``). See ADR 0011:

- ``global/{type}/<file>`` → enterprise library (product=project=build=``global``)
- ``{product}/common/{type}/<file>`` → product common (project=build=``common``)
- ``{product}/{project}/common/{type}/<file>`` → project common (build=``common``)
- ``{product}/{project}/{build}/{type}/<file>`` → build truth

This is a strict cutover: there is no legacy two-level fallback parser.
"""

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

    Supported canonical layouts (see module docstring / ADR 0011):

    - Enterprise library: ``global/{type}/<file>``
    - Product common: ``{product}/common/{type}/<file>``
    - Project common: ``{product}/{project}/common/{type}/<file>``
    - Build truth: ``{product}/{project}/{build}/{type}/<file>``

    Nested subfolders below ``{type}`` are allowed. The reserved words
    ``global`` and ``common`` may not appear as ordinary product/project/build
    slugs.

    Args:
        raw_path: Absolute or relative path to a file under ``layout.raw_dir``.
        layout: Path naming configuration from ``config/default.yaml``.
        repo_root: Optional repo root for ``source_file`` labels (e.g. ``data/raw/...``).

    Returns:
        Parsed metadata with ``product``, ``project``, ``build``, and
        ``document_type`` set.

    Raises:
        PathMetadataError: If the path does not match a canonical layout or
            uses a reserved word in an ordinary segment.
    """
    if raw_path.name.startswith("."):
        raise PathMetadataError(f"Ignored hidden file: {raw_path}")

    parts = _relative_parts(raw_path, layout.raw_dir)

    type_folders = layout.document_type_folders
    global_seg = layout.global_segment
    common_seg = layout.common_segment
    known_folders = ", ".join(sorted(type_folders))

    def _unknown_type_folder(folder: str, layout_hint: str) -> PathMetadataError:
        return PathMetadataError(
            f"Unknown type folder '{folder}' ({layout_hint}). "
            f"Add '{folder}: <document_type>' to data_layout.document_type_folders "
            f"in config/default.yaml. Known folders: {known_folders}"
        )

    def _require_type_folder(folder: str, layout_hint: str) -> None:
        if folder not in type_folders:
            raise _unknown_type_folder(folder, layout_hint)

    def _reject_reserved(segment: str, value: str) -> None:
        if value in layout.reserved_segments:
            raise PathMetadataError(
                f"Reserved name '{value}' cannot be used as a {segment} segment: "
                f"{Path(*parts)}"
            )

    # Enterprise library: global/{type}/<file>
    if parts and parts[0] == global_seg:
        if len(parts) < 3:
            raise PathMetadataError(f"Missing filename under enterprise path: {Path(*parts)}")
        _require_type_folder(parts[1], f"{global_seg}/{{type}}/file")
        product = global_seg
        project = global_seg
        build = global_seg
        type_folder = parts[1]
    # Product common: {product}/common/{type}/<file>
    elif len(parts) >= 4 and parts[1] == common_seg:
        _reject_reserved("product", parts[0])
        _require_type_folder(parts[2], f"{{product}}/{common_seg}/{{type}}/file")
        product = parts[0]
        project = common_seg
        build = common_seg
        type_folder = parts[2]
    # Project common: {product}/{project}/common/{type}/<file>
    elif len(parts) >= 5 and parts[2] == common_seg:
        _reject_reserved("product", parts[0])
        _reject_reserved("project", parts[1])
        _require_type_folder(parts[3], f"{{product}}/{{project}}/{common_seg}/{{type}}/file")
        product = parts[0]
        project = parts[1]
        build = common_seg
        type_folder = parts[3]
    # Build truth: {product}/{project}/{build}/{type}/<file>
    elif len(parts) >= 5:
        _reject_reserved("product", parts[0])
        _reject_reserved("project", parts[1])
        _reject_reserved("build", parts[2])
        _require_type_folder(parts[3], "{product}/{project}/{build}/{type}/file")
        product = parts[0]
        project = parts[1]
        build = parts[2]
        type_folder = parts[3]
    else:
        raise PathMetadataError(
            "Path does not match a canonical layout "
            f"({global_seg}/{{type}}/file | {{product}}/{common_seg}/{{type}}/file | "
            f"{{product}}/{{project}}/{common_seg}/{{type}}/file | "
            f"{{product}}/{{project}}/{{build}}/{{type}}/file): {Path(*parts)}"
        )

    filename = parts[-1]
    document_type = type_folders[type_folder]
    source_file = _source_file_label(layout.raw_dir, repo_root, parts)

    metadata = Metadata(
        product=product,
        project=project,
        build=build,
        document_type=document_type,
        title=_title_from_filename(filename),
        source_file=source_file,
    )
    logger.debug(
        "Parsed metadata product=%s project=%s build=%s type=%s from %s",
        product,
        project,
        build,
        document_type,
        source_file,
    )
    return metadata


def expand_retrieval_scope(
    product: str,
    project: str,
    build: str,
    layout: DataLayoutConfig,
) -> list[tuple[str, str, str]]:
    """Return ``(product, project, build)`` triples to search, highest priority first.

    Implements upward inheritance:
    build truth → project common → product common → enterprise ``global``.

    Args:
        product: Product name filter.
        project: Project name filter.
        build: Build name filter.
        layout: Path naming configuration.

    Returns:
        Ordered list of scope triples to query, most specific first.
    """
    global_seg = layout.global_segment
    common_seg = layout.common_segment
    scopes: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(p: str, pr: str, b: str) -> None:
        key = (p, pr, b)
        if key not in seen:
            seen.add(key)
            scopes.append(key)

    # Enterprise queries never inherit downward — the global library is terminal.
    if product == global_seg:
        add(global_seg, global_seg, global_seg)
        return scopes

    # Build truth (only when a concrete build is requested).
    if build and build != common_seg:
        add(product, project, build)

    # Project common (only when a concrete project is requested).
    if project and project != common_seg:
        add(product, project, common_seg)

    # Product common.
    add(product, common_seg, common_seg)

    # Enterprise library.
    add(global_seg, global_seg, global_seg)
    return scopes


def allowed_scope_triples(
    layout: DataLayoutConfig,
    *,
    product: str | None,
    project: str | None,
    build: str | None,
    scope_inheritance: bool = True,
) -> set[tuple[str, str, str]] | None:
    """Return allowed ``(product, project, build)`` triples for a scope filter.

    Membership is always keyed on the full triple so identical project/build
    slugs under two different products can never leak into each other's scope.
    Missing axes fall back to the reserved segments (missing ``product`` →
    enterprise library only; missing ``project``/``build`` → the shared
    ``common`` tier), which fails closed rather than widening the filter.

    Args:
        layout: Path naming configuration.
        product: Optional product filter.
        project: Optional project filter.
        build: Optional build filter.
        scope_inheritance: When true, expand upward via
            :func:`expand_retrieval_scope`; otherwise match the exact triple.

    Returns:
        Allowed scope triples, or ``None`` when no filter was requested.
    """
    if not product and not project and not build:
        return None
    prod = product or layout.global_segment
    proj = project or layout.common_segment
    bld = build or layout.common_segment
    if not scope_inheritance:
        return {(prod, proj, bld)}
    return set(expand_retrieval_scope(prod, proj, bld, layout))
