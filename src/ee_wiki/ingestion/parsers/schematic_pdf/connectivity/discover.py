"""Discover companion netlist / boardview files next to a schematic PDF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    CompanionGraph,
    CompanionManifest,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.registry import (
    parse_companion_file,
)

logger = get_logger(__name__)

DEFAULT_NETLIST_EXTENSIONS: tuple[str, ...] = (
    ".net",
    ".kicad_sch",
    ".kicad_pro",
    ".SchDoc",
    ".prjpcb",
    ".PrjPcb",
)
DEFAULT_BOARDVIEW_EXTENSIONS: tuple[str, ...] = (".brd",)


@dataclass(frozen=True)
class DiscoveredCompanions:
    """Paths discovered for each companion kind (preference order preserved)."""

    netlist_paths: tuple[Path, ...] = ()
    boardview_paths: tuple[Path, ...] = ()

    @property
    def all_paths(self) -> list[Path]:
        """Flat list: netlist candidates then boardview candidates."""
        return [*self.netlist_paths, *self.boardview_paths]


@dataclass
class ParsedCompanions:
    """Parsed companion graphs plus manifest for the sidecar."""

    manifest: CompanionManifest
    netlist: CompanionGraph | None = None
    boardview: CompanionGraph | None = None


def _collect_paths(
    pdf_path: Path,
    *,
    suffixes: tuple[str, ...],
) -> list[Path]:
    """Return existing companion paths for ``suffixes``, highest preference first."""
    if not suffixes:
        return []
    suffixes_lower = tuple(s.lower() for s in suffixes)
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


def discover_companions(
    pdf_path: Path,
    *,
    netlist_extensions: tuple[str, ...] | None = None,
    boardview_extensions: tuple[str, ...] | None = None,
) -> DiscoveredCompanions:
    """Discover netlist and boardview companions for ``pdf_path``.

    Args:
        pdf_path: Path to the schematic PDF under ``data/raw/``.
        netlist_extensions: Suffixes for netlist discovery.
        boardview_extensions: Suffixes for boardview discovery.

    Returns:
        Grouped companion paths (may be empty for either kind).
    """
    net_ext = (
        tuple(netlist_extensions)
        if netlist_extensions is not None
        else DEFAULT_NETLIST_EXTENSIONS
    )
    brd_ext = (
        tuple(boardview_extensions)
        if boardview_extensions is not None
        else DEFAULT_BOARDVIEW_EXTENSIONS
    )
    netlist_paths = tuple(_collect_paths(pdf_path, suffixes=net_ext))
    boardview_paths = tuple(_collect_paths(pdf_path, suffixes=brd_ext))
    if not netlist_paths:
        logger.info("Connectivity companions: netlist=absent for %s", pdf_path.name)
    if not boardview_paths:
        logger.info("Connectivity companions: boardview=absent for %s", pdf_path.name)
    return DiscoveredCompanions(
        netlist_paths=netlist_paths,
        boardview_paths=boardview_paths,
    )


def parse_discovered_companions(discovered: DiscoveredCompanions) -> ParsedCompanions:
    """Parse the first successful netlist and boardview from ``discovered``.

    Args:
        discovered: Paths from :func:`discover_companions`.

    Returns:
        Parsed graphs and a :class:`CompanionManifest` of paths that succeeded
        (or were present even if parse failed — see below).

    Notes:
        Manifest records the preferred *path* when a file exists, even if parse
        returns ``None``, so operators can see which companion was attempted.
    """
    netlist_graph: CompanionGraph | None = None
    for path in discovered.netlist_paths:
        netlist_graph = parse_companion_file(path)
        if netlist_graph is not None:
            break
    if discovered.netlist_paths and netlist_graph is None:
        logger.info(
            "Connectivity companions: netlist present but unparsed (%s)",
            discovered.netlist_paths[0].name,
        )

    boardview_graph: CompanionGraph | None = None
    for path in discovered.boardview_paths:
        boardview_graph = parse_companion_file(path)
        if boardview_graph is not None:
            break
    if discovered.boardview_paths and boardview_graph is None:
        logger.info(
            "Connectivity companions: boardview present but unparsed (%s)",
            discovered.boardview_paths[0].name,
        )

    # Manifest: only record paths that produced a graph (clearer for consumers).
    return ParsedCompanions(
        manifest=CompanionManifest(
            netlist=str(netlist_graph.source_path) if netlist_graph else None,
            boardview=str(boardview_graph.source_path) if boardview_graph else None,
        ),
        netlist=netlist_graph,
        boardview=boardview_graph,
    )


def discover_and_parse_companions(
    pdf_path: Path,
    *,
    netlist_extensions: tuple[str, ...] | None = None,
    boardview_extensions: tuple[str, ...] | None = None,
) -> ParsedCompanions:
    """Discover and parse companions for ``pdf_path`` in one call.

    Args:
        pdf_path: Schematic PDF path.
        netlist_extensions: Optional netlist suffixes.
        boardview_extensions: Optional boardview suffixes.

    Returns:
        :class:`ParsedCompanions` (graphs may be ``None`` when absent).
    """
    discovered = discover_companions(
        pdf_path,
        netlist_extensions=netlist_extensions,
        boardview_extensions=boardview_extensions,
    )
    return parse_discovered_companions(discovered)
