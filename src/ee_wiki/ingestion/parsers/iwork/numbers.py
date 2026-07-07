"""Parse Numbers spreadsheets (``.numbers``) via macOS Excel export."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig, StandardDocument
from ee_wiki.ingestion.parsers.excel import ExcelParserError, parse_excel
from ee_wiki.ingestion.parsers.iwork.errors import IworkParserError
from ee_wiki.ingestion.parsers.iwork.export import export_numbers_to_xlsx
from ee_wiki.ingestion.path_metadata import parse_path_metadata

if TYPE_CHECKING:
    from ee_wiki.common.config import AppConfig

logger = get_logger(__name__)


def parse_numbers(
    raw_path: Path,
    layout: DataLayoutConfig,
    config: AppConfig,
    *,
    repo_root: Path | None = None,
) -> StandardDocument:
    """Convert a ``.numbers`` file to Excel and reuse the Excel ingest pipeline.

    Args:
        raw_path: Path to a ``.numbers`` file under ``layout.raw_dir``.
        layout: Data layout configuration for path-derived metadata.
        config: Application configuration (``excel`` and ``iwork`` settings).
        repo_root: Optional repository root for ``source_file`` labels.

    Returns:
        Parsed document with Markdown content and metadata from the original ``.numbers``.

    Raises:
        IworkParserError: If iWork ingest is disabled, export fails, or sheets are empty.
    """
    if not config.iwork.enabled:
        raise IworkParserError(
            "Numbers ingest is disabled (set ingestion.iwork.enabled: true on macOS)"
        )

    metadata = parse_path_metadata(raw_path, layout, repo_root=repo_root)
    try:
        with tempfile.TemporaryDirectory(prefix="ee-wiki-numbers-") as tmp:
            xlsx_path = export_numbers_to_xlsx(
                raw_path,
                out_dir=Path(tmp),
                timeout=config.iwork.numbers_export_timeout_seconds,
                quit_after=config.iwork.quit_apps_after_export,
            )
            interim = parse_excel(
                xlsx_path,
                layout,
                config.excel,
                repo_root=repo_root,
                metadata=metadata,
            )
    except IworkParserError:
        raise
    except ExcelParserError as exc:
        raise IworkParserError(str(exc)) from exc
    except Exception as exc:
        raise IworkParserError(f"Failed to parse Numbers file {raw_path.name}: {exc}") from exc

    document = StandardDocument(
        content=interim.content,
        metadata=metadata,
        source_ref=str(raw_path.resolve()),
    )
    logger.info(
        "Parsed .numbers %s via Numbers export (%d chars, title=%s)",
        metadata.source_file,
        len(document.content),
        metadata.title,
    )
    return document
