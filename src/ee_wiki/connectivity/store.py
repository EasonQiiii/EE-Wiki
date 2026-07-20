"""Load schematic ``*.connectivity.json`` sidecars from ``data/processed/``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    SchematicConnectivity,
)

logger = get_logger(__name__)


class ConnectivityStoreError(EEWikiError):
    """Failed to load or parse a connectivity sidecar."""


@dataclass(frozen=True)
class ConnectivityDocument:
    """One loaded connectivity sidecar with path-derived scope."""

    product: str
    project: str
    build: str
    sidecar_path: Path
    connectivity: SchematicConnectivity

    @property
    def source_file(self) -> str:
        """Source schematic path recorded in the sidecar."""
        return self.connectivity.source_file


def _parse_scope_from_processed(
    sidecar_path: Path,
    processed_dir: Path,
    layout: DataLayoutConfig,
) -> tuple[str, str, str] | None:
    """Derive ``(product, project, build)`` from a path under ``processed_dir``.

    Recognized layouts (ADR 0011):

    - ``global/sch/...`` → ``(global, global, global)``
    - ``{product}/common/sch/...`` → ``(product, common, common)``
    - ``{product}/{project}/{build}/sch/...`` → build truth (``build`` may be
      the reserved ``common`` segment for project common).
    """
    try:
        relative = sidecar_path.resolve().relative_to(processed_dir.resolve())
    except ValueError:
        return None
    parts = relative.parts
    sch_folders = {
        folder
        for folder, dtype in layout.document_type_folders.items()
        if dtype == "schematic"
    } or {"sch"}
    global_seg = layout.global_segment
    common_seg = layout.common_segment

    # global/sch/*.connectivity.json
    if len(parts) >= 3 and parts[0] == global_seg and parts[1] in sch_folders:
        return global_seg, global_seg, global_seg
    # {product}/common/sch/*.connectivity.json
    if len(parts) >= 4 and parts[1] == common_seg and parts[2] in sch_folders:
        return parts[0], common_seg, common_seg
    # {product}/{project}/{build}/sch/*.connectivity.json
    if len(parts) >= 5 and parts[3] in sch_folders:
        return parts[0], parts[1], parts[2]
    return None


def load_connectivity_sidecar(path: Path) -> SchematicConnectivity:
    """Parse one ``*.connectivity.json`` file.

    Args:
        path: Absolute path to the sidecar.

    Returns:
        Deserialized :class:`SchematicConnectivity`.

    Raises:
        ConnectivityStoreError: On I/O or JSON/schema problems.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except OSError as exc:
        raise ConnectivityStoreError(f"Cannot read connectivity sidecar: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConnectivityStoreError(f"Invalid JSON in {path}") from exc
    if not isinstance(data, dict):
        raise ConnectivityStoreError(f"Connectivity sidecar root must be object: {path}")
    try:
        return SchematicConnectivity.from_dict(data)
    except (TypeError, ValueError, KeyError) as exc:
        raise ConnectivityStoreError(f"Cannot parse connectivity sidecar {path}: {exc}") from exc


def load_connectivity_documents(
    processed_dir: Path,
    layout: DataLayoutConfig,
    *,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
) -> list[ConnectivityDocument]:
    """Discover and load connectivity sidecars under ``processed_dir``.

    Args:
        processed_dir: Root of the processed mirror (``data/processed/``).
        layout: Data layout for path segment names.
        product: Optional product filter.
        project: Optional project filter.
        build: Optional build filter (exact match; no scope inheritance here —
            callers may expand scope separately).

    Returns:
        Loaded documents sorted by ``(product, project, build, source_file)``.
    """
    if not processed_dir.is_dir():
        logger.warning("Processed directory missing: %s", processed_dir)
        return []

    documents: list[ConnectivityDocument] = []
    for path in sorted(processed_dir.rglob("*.connectivity.json")):
        if not path.is_file():
            continue
        scope = _parse_scope_from_processed(path, processed_dir, layout)
        if scope is None:
            logger.debug("Skipping connectivity sidecar outside sch/ layout: %s", path)
            continue
        doc_product, doc_project, doc_build = scope
        if product is not None and doc_product != product:
            continue
        if project is not None and doc_project != project:
            continue
        if build is not None and doc_build != build:
            continue
        try:
            connectivity = load_connectivity_sidecar(path)
        except ConnectivityStoreError as exc:
            logger.warning("%s", exc)
            continue
        documents.append(
            ConnectivityDocument(
                product=doc_product,
                project=doc_project,
                build=doc_build,
                sidecar_path=path,
                connectivity=connectivity,
            )
        )

    documents.sort(
        key=lambda d: (d.product, d.project, d.build, d.source_file, str(d.sidecar_path))
    )
    logger.info(
        "Loaded %d connectivity sidecar(s) from %s (product=%s project=%s build=%s)",
        len(documents),
        processed_dir,
        product,
        project,
        build,
    )
    return documents
