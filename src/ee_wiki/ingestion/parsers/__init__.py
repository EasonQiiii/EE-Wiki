"""File format parsers for document ingestion."""

from ee_wiki.ingestion.parsers.markdown import MARKDOWN_SUFFIXES, parse_markdown
from ee_wiki.ingestion.parsers.schematic_pdf import PDF_SUFFIXES, parse_schematic_pdf

__all__ = [
    "MARKDOWN_SUFFIXES",
    "PDF_SUFFIXES",
    "parse_markdown",
    "parse_schematic_pdf",
]
