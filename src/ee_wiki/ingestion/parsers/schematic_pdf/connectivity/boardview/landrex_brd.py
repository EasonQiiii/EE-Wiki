"""Landrex / TestLink BoardView ``.brd`` decoder and pin–net parser.

Encoding and block layout follow OpenBoardView ``BRDFile.cpp`` (MIT).
"""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    CompanionGraph,
    PinNetBinding,
)

logger = get_logger(__name__)

_ENCODED_HEADER = bytes((0x23, 0xE2, 0x63, 0x28))


def decode_landrex_brd(data: bytes) -> str:
    """Decode Landrex obfuscation when present; otherwise return text as-is.

    Args:
        data: Raw ``.brd`` file bytes.

    Returns:
        Decoded text (CRLF normalized to ``\\n``).
    """
    buf = bytearray(data)
    if len(buf) >= 4 and bytes(buf[:4]) == _ENCODED_HEADER:
        for i, x in enumerate(buf):
            if x in (0x0D, 0x0A, 0):
                continue
            c = x
            buf[i] = (~(((c >> 6) & 3) | (c << 2))) & 0xFF
    return bytes(buf).decode("latin-1", errors="replace").replace("\r\n", "\n")


def parse_landrex_brd(path: Path) -> CompanionGraph | None:
    """Parse a Landrex/TestLink BoardView file into pin–net bindings.

    Args:
        path: Path to a ``.brd`` file.

    Returns:
        :class:`CompanionGraph` with ``evidence=boardview``, or ``None`` if the
        file is not a recognizable Landrex boardview.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        logger.warning("Cannot read boardview %s: %s", path, exc)
        return None

    text = decode_landrex_brd(raw)
    if "Parts:" not in text and "Pins1:" not in text:
        logger.info(
            "Boardview %s is not Landrex/TestLink format — skipping",
            path.name,
        )
        return None
    if "Pins:" not in text and "Pins2:" not in text:
        logger.info("Boardview %s has no Pins block — skipping", path.name)
        return None

    lines = [ln.strip() for ln in text.split("\n")]
    current_block = 0
    parts: list[str] = []
    pin_rows: list[tuple[int, str]] = []

    for line in lines:
        if not line:
            continue
        lower = line.lower()
        if lower == "str_length:":
            current_block = 1
            continue
        if lower == "var_data:":
            current_block = 2
            continue
        if lower == "format:":
            current_block = 3
            continue
        if lower in ("parts:", "pins1:"):
            current_block = 4
            continue
        if lower in ("pins:", "pins2:"):
            current_block = 5
            continue
        if lower == "nails:":
            current_block = 6
            continue

        fields = line.split()
        if current_block == 4 and len(fields) >= 1:
            parts.append(fields[0])
            continue
        if current_block == 5 and len(fields) >= 5:
            try:
                part_idx = int(fields[3])
            except ValueError:
                continue
            net = fields[4]
            if not net or net.upper() in {"NC", "N/C"}:
                continue
            pin_rows.append((part_idx, net))

    if not parts or not pin_rows:
        logger.info("Boardview %s has no Parts/Pins — skipping", path.name)
        return None

    pin_counters: dict[str, int] = {}
    bindings: list[PinNetBinding] = []
    for part_idx, net in pin_rows:
        if not (1 <= part_idx <= len(parts)):
            continue
        refdes = parts[part_idx - 1]
        pin_counters[refdes] = pin_counters.get(refdes, 0) + 1
        bindings.append(
            PinNetBinding(
                refdes=refdes,
                pin=str(pin_counters[refdes]),
                net=net,
                evidence="boardview",
            )
        )

    if not bindings:
        return None

    logger.info(
        "Parsed boardview %s: %d part(s), %d pin–net binding(s)",
        path.name,
        len(parts),
        len(bindings),
    )
    return CompanionGraph(
        evidence="boardview",
        source_path=str(path),
        bindings=bindings,
    )


class LandrexBrdParser:
    """:class:`ConnectivityCompanionParser` for Landrex/TestLink ``.brd``."""

    def kind(self) -> str:
        """Return companion kind."""
        return "boardview"

    def supported_extensions(self) -> tuple[str, ...]:
        """Supported suffixes."""
        return (".brd",)

    def parse(self, path: Path) -> CompanionGraph | None:
        """Parse ``path`` as a Landrex boardview."""
        return parse_landrex_brd(path)
