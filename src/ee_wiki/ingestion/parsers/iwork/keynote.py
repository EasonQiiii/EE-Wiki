"""Parse Keynote presentations (``.key``) via macOS PDF export."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig, StandardDocument
from ee_wiki.ingestion.parsers.iwork.errors import IworkParserError
from ee_wiki.ingestion.parsers.iwork.export import export_keynote_to_pdf
from ee_wiki.ingestion.parsers.prose_pdf import parse_prose_pdf
from ee_wiki.ingestion.path_metadata import parse_path_metadata

if TYPE_CHECKING:
    from ee_wiki.common.config import AppConfig

logger = get_logger(__name__)


def parse_keynote(
    raw_path: Path,
    layout: DataLayoutConfig,
    config: AppConfig,
    *,
    repo_root: Path | None = None,
) -> StandardDocument:
    """Convert a ``.key`` file to PDF and reuse the prose PDF text pipeline.

    Args:
        raw_path: Path to a ``.key`` file under ``layout.raw_dir``.
        layout: Data layout configuration for path-derived metadata.
        config: Application configuration (``prose_pdf`` and ``iwork`` settings).
        repo_root: Optional repository root for ``source_file`` labels.

    Returns:
        Parsed document with Markdown content and metadata from the original ``.key``.

    Raises:
        IworkParserError: If iWork ingest is disabled, export fails, or PDF has no text.
    """
    if not config.iwork.enabled:
        raise IworkParserError(
            "Keynote ingest is disabled (set ingestion.iwork.enabled: true on macOS)"
        )

    metadata = parse_path_metadata(raw_path, layout, repo_root=repo_root)
    try:
        with tempfile.TemporaryDirectory(prefix="ee-wiki-key-") as tmp:
            pdf_path = export_keynote_to_pdf(
                raw_path,
                out_dir=Path(tmp),
                timeout=config.iwork.keynote_export_timeout_seconds,
                quit_after=config.iwork.quit_apps_after_export,
            )
            interim = parse_prose_pdf(
                pdf_path,
                layout,
                config,
                repo_root=repo_root,
                metadata=metadata,
            )
    except IworkParserError:
        raise
    except Exception as exc:
        raise IworkParserError(f"Failed to parse Keynote file {raw_path.name}: {exc}") from exc

    if not interim.content.strip():
        raise IworkParserError(f".key produced no text after PDF conversion: {raw_path}")

    document = StandardDocument(
        content=interim.content,
        metadata=metadata,
        source_ref=str(raw_path.resolve()),
    )
    logger.info(
        "Parsed .key %s via Keynote export (%d chars, title=%s)",
        metadata.source_file,
        len(document.content),
        metadata.title,
    )
    return document
