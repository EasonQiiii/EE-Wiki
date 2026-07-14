"""Discover companion CAD / netlist files next to a schematic PDF."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)

# Default extensions — overridden by config when provided.
DEFAULT_CAD_EXTENSIONS: tuple[str, ...] = (
    ".net",
    ".kicad_sch",
    ".kicad_pro",
    ".SchDoc",
    ".prjpcb",
    ".PrjPcb",
)


def discover_cad_companions(
    pdf_path: Path,
    *,
    extensions: tuple[str, ...] | None = None,
) -> list[Path]:
    """Return candidate CAD/netlist paths for ``pdf_path``, highest preference first.

    Search order:

    1. Same directory, same stem + each extension
    2. Same directory, any file with a configured extension
    3. Sibling ``cad/`` directory with the same stem

    Args:
        pdf_path: Path to the schematic PDF under ``data/raw/``.
        extensions: File suffixes to accept (including the leading dot).

    Returns:
        Deduplicated existing paths in preference order.
    """
    suffixes = tuple(extensions) if extensions is not None else DEFAULT_CAD_EXTENSIONS
    suffixes_lower = tuple(suffix.lower() for suffix in suffixes)
    directory = pdf_path.parent
    stem = pdf_path.stem
    found: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            return
        seen.add(resolved)
        found.append(path)

    for suffix in suffixes:
        _add(directory / f"{stem}{suffix}")

    try:
        for child in sorted(directory.iterdir()):
            if child.suffix.lower() in suffixes_lower and child.is_file():
                _add(child)
    except OSError as exc:
        logger.warning("Cannot list schematic directory %s: %s", directory, exc)

    cad_dir = directory / "cad"
    if cad_dir.is_dir():
        for suffix in suffixes:
            _add(cad_dir / f"{stem}{suffix}")
        try:
            for child in sorted(cad_dir.iterdir()):
                if child.suffix.lower() in suffixes_lower and child.is_file():
                    _add(child)
        except OSError as exc:
            logger.warning("Cannot list cad companion directory %s: %s", cad_dir, exc)

    return found


def try_parse_cad_module_nets(
    companions: list[Path],
) -> dict[str, list[str]] | None:
    """Best-effort parse of companion CAD/netlist into module→nets.

    Phase 1: discovery + logging only for unsupported formats. Returns ``None``
    so callers fall through to PDF geometry. KiCad/Altium parsers land later
    behind the same entry point.

    Args:
        companions: Preferred-order CAD paths from :func:`discover_cad_companions`.

    Returns:
        Module label → net names when a parser succeeds; otherwise ``None``.
    """
    if not companions:
        return None
    for path in companions:
        logger.info(
            "Schematic CAD companion present but no parser yet for %s — "
            "falling back to PDF geometry / OCR spatial",
            path.name,
        )
    return None
