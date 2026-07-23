"""Startup readiness warnings for lab / serve (missing companions, indexes, …)."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.discover import (
    discover_companions,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.registry import (
    parse_companion_file,
)

logger = get_logger(__name__)

_MAX_PDF_EXAMPLES = 8


def _schematic_folder_names(config: AppConfig) -> frozenset[str]:
    """Return raw folder names mapped to ``schematic`` document type."""
    return frozenset(
        folder
        for folder, dtype in config.data_layout.document_type_folders.items()
        if dtype == "schematic"
    )


def _sop_folder_names(config: AppConfig) -> frozenset[str]:
    """Return raw folder names mapped to ``sop`` document type."""
    return frozenset(
        folder
        for folder, dtype in config.data_layout.document_type_folders.items()
        if dtype == "sop"
    )


def _iter_schematic_pdfs(raw_dir: Path, sch_folders: frozenset[str]) -> list[Path]:
    """List schematic PDFs under ``raw_dir`` (any ``sch`` segment in the path)."""
    if not raw_dir.is_dir():
        return []
    pdfs: list[Path] = []
    for path in sorted(raw_dir.rglob("*.pdf")):
        if not path.is_file():
            continue
        try:
            parts = path.relative_to(raw_dir).parts
        except ValueError:
            continue
        if any(part in sch_folders for part in parts):
            pdfs.append(path)
    return pdfs


def _has_sop_docs(raw_dir: Path, sop_folders: frozenset[str]) -> bool:
    """Return whether any file exists under a sop-type folder."""
    if not raw_dir.is_dir() or not sop_folders:
        return False
    for folder in sop_folders:
        for path in raw_dir.rglob(folder):
            if path.is_dir() and any(path.rglob("*")):
                # at least one file somewhere under this sop dir
                if any(p.is_file() for p in path.rglob("*")):
                    return True
    return False


def _connectivity_sidecar_for_pdf(
    pdf_path: Path,
    *,
    raw_dir: Path,
    processed_dir: Path,
) -> Path | None:
    """Return expected ``*.connectivity.json`` path next to processed markdown."""
    try:
        rel = pdf_path.relative_to(raw_dir)
    except ValueError:
        return None
    return (processed_dir / rel).with_suffix(".connectivity.json")


def warn_lab_readiness(config: AppConfig) -> None:
    """Emit WARNING logs for common lab gaps (companions, indexes, FA template).

    Does not raise; intended for ``scripts/serve.py`` and API lifespan.

    Args:
        config: Loaded application configuration.
    """
    raw_dir = config.raw_dir
    if not raw_dir.is_dir():
        logger.warning(
            "Lab readiness: raw_dir missing (%s) — place documents under "
            "data/raw/{product}/{project}/{build}/… then ingest.",
            raw_dir,
        )
        return

    conn = config.schematic_pdf.connectivity
    sch_folders = _schematic_folder_names(config)
    pdfs = _iter_schematic_pdfs(raw_dir, sch_folders)

    if not pdfs:
        logger.warning(
            "Lab readiness: no schematic PDFs under %s (folders %s) — "
            "FA-grade pin/net trace needs sch/*.pdf plus companions.",
            raw_dir,
            sorted(sch_folders) or ["sch"],
        )
    elif conn.enabled:
        missing_netlist: list[str] = []
        missing_boardview: list[str] = []
        missing_sidecar: list[str] = []
        unparsed_netlist: list[str] = []
        net_ext = conn.netlist_extensions or conn.cad_extensions
        brd_ext = conn.boardview_extensions

        for pdf in pdfs:
            discovered = discover_companions(
                pdf,
                netlist_extensions=net_ext,
                boardview_extensions=brd_ext,
            )
            rel = str(pdf.relative_to(raw_dir))
            if not discovered.netlist_paths:
                missing_netlist.append(rel)
            else:
                parsed_any = any(
                    parse_companion_file(p) is not None for p in discovered.netlist_paths
                )
                if not parsed_any:
                    unparsed_netlist.append(
                        f"{rel} (tried {discovered.netlist_paths[0].name})"
                    )
            if not discovered.boardview_paths:
                missing_boardview.append(rel)

            sidecar = _connectivity_sidecar_for_pdf(
                pdf,
                raw_dir=raw_dir,
                processed_dir=config.processed_dir,
            )
            if sidecar is not None and not sidecar.is_file():
                # Only nag about sidecar when at least one companion exists
                # (otherwise ingest still won't produce authoritative truth).
                if discovered.netlist_paths or discovered.boardview_paths:
                    missing_sidecar.append(rel)

        if missing_netlist:
            examples = ", ".join(missing_netlist[:_MAX_PDF_EXAMPLES])
            more = len(missing_netlist) - _MAX_PDF_EXAMPLES
            suffix = f" (+{more} more)" if more > 0 else ""
            logger.warning(
                "Lab readiness: %d schematic PDF(s) have no netlist companion "
                "(.net / configured netlist extensions) next to the PDF or under "
                "sch/cad/. Authoritative pin–net trace will refuse for these. "
                "Examples: %s%s",
                len(missing_netlist),
                examples,
                suffix,
            )
        if missing_boardview:
            examples = ", ".join(missing_boardview[:_MAX_PDF_EXAMPLES])
            more = len(missing_boardview) - _MAX_PDF_EXAMPLES
            suffix = f" (+{more} more)" if more > 0 else ""
            logger.warning(
                "Lab readiness: %d schematic PDF(s) have no BoardView (.brd) "
                "companion (optional but recommended). Examples: %s%s",
                len(missing_boardview),
                examples,
                suffix,
            )
        if unparsed_netlist:
            examples = ", ".join(unparsed_netlist[:_MAX_PDF_EXAMPLES])
            logger.warning(
                "Lab readiness: netlist file(s) present but not parsed "
                "(unsupported format or stub parser). Supported today: "
                "simple line-oriented .net and light KiCad sexpr extract; "
                "Altium/KiCad project files are stubs. Examples: %s",
                examples,
            )
        if missing_sidecar:
            examples = ", ".join(missing_sidecar[:_MAX_PDF_EXAMPLES])
            logger.warning(
                "Lab readiness: companions exist but *.connectivity.json sidecar "
                "missing under processed/ — re-run ingest for: %s",
                examples,
            )
    else:
        logger.warning(
            "Lab readiness: schematic_pdf.connectivity.enabled is false — "
            "pin–net authority gate is off.",
        )

    sop_folders = _sop_folder_names(config)
    if not _has_sop_docs(raw_dir, sop_folders):
        logger.warning(
            "Lab readiness: no SOP / station docs under %s (folders %s) — "
            "station procedures will not be retrievable until you add files "
            "and ingest+index.",
            raw_dir,
            sorted(sop_folders) or ["sop"],
        )

    indexes = config.indexes_dir
    chunks = indexes / "chunks.jsonl"
    if not chunks.is_file():
        logger.warning(
            "Lab readiness: index missing (%s) — run scripts/index.py (or sync) "
            "after ingest before chat/RAG.",
            chunks,
        )

    if config.fa.enabled:
        template = config.repo_root / "assets" / "templates" / "fa" / "one_page.key"
        if not template.is_file():
            logger.info(
                "FA Keynote: no company template at %s — export creates a "
                "one-slide Keynote from Radar fields (Summary / FA Steps / "
                "Conclusion), or Markdown-only ``FA_summary.md`` when "
                "Keynote.app is unavailable. "
                "Optional placeholders: assets/templates/fa/README.md.",
                template,
            )
