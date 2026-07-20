"""Manual Flames backup: user-supplied logs/errors via Open WebUI."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.errors import IntegrationError
from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.flames.parse import extract_errors_from_path, extract_errors_from_text
from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.protocols.flames import (
    FailItem,
    FailItemsResult,
    FlamesUnitRef,
    TestRecord,
)

logger = get_logger(__name__)

_USER_PROMPT = (
    "Flames API is not available — please paste either:\n"
    "1) the test **log** (preferred), or\n"
    "2) a bullet list of **error / fail items**.\n"
    "Optional: station name and serial (SN)."
)


class ManualFlamesBackend:
    """Collect fail evidence from the user instead of calling Flames.

    ``collect_fail_items`` never invents errors: without prior
    :meth:`ingest_user_evidence` it returns ``needs_user_input=True``.
    """

    def resolve_unit(
        self,
        radar_id: str,
        *,
        serial: str | None = None,
    ) -> FlamesUnitRef:
        """Return a manual unit ref keyed by Radar id."""
        rid = normalize_radar_id(radar_id)
        return FlamesUnitRef(
            unit_id=f"manual-unit-{rid}",
            serial=serial,
            radar_id=rid,
        )

    def list_test_records(self, unit: FlamesUnitRef) -> list[TestRecord]:
        """No remote records in manual mode."""
        return []

    def fetch_log(self, record: TestRecord, dest_dir: Path) -> Path:
        """Manual mode has no remote log fetch."""
        raise IntegrationError(
            "Manual Flames backend cannot fetch remote logs; "
            "use ingest_user_evidence with pasted text"
        )

    def extract_errors(self, log_path: Path) -> list[FailItem]:
        """Extract ERROR/FAIL (or bullet) items from a cached log."""
        return extract_errors_from_path(log_path)

    def collect_fail_items(
        self,
        radar_id: str,
        *,
        serial: str | None = None,
        cache_dir: Path,
    ) -> FailItemsResult:
        """Return cached user evidence if present; otherwise ask the user.

        Args:
            radar_id: FA session Radar id.
            serial: Optional serial from the user.
            cache_dir: ``data/cache/fa/{radar_id}/``.

        Returns:
            Prior ingested result, or empty result with ``needs_user_input``.
        """
        rid = normalize_radar_id(radar_id)
        unit = self.resolve_unit(rid, serial=serial)
        cache_dir.mkdir(parents=True, exist_ok=True)
        logs = sorted(cache_dir.glob("user_*.log")) + sorted(
            cache_dir.glob("user_*.txt")
        )
        if not logs:
            return FailItemsResult(
                unit=unit,
                records=(),
                fail_items=(),
                cached_logs=(),
                source="manual",
                needs_user_input=True,
                user_prompt=_USER_PROMPT,
            )

        fail_items: list[FailItem] = []
        cached: list[str] = []
        records: list[TestRecord] = []
        for path in logs:
            rel = f"fa/{rid}/{path.name}"
            cached.append(rel)
            station = _station_from_filename(path.name)
            record = TestRecord(
                record_id=path.stem,
                station=station or "user_paste",
                result="FAIL",
                log_uri=f"manual://{path.name}",
            )
            records.append(record)
            for item in self.extract_errors(path):
                fail_items.append(
                    FailItem(
                        message=item.message,
                        station=station,
                        record_id=record.record_id,
                        log_rel_path=rel,
                        line_no=item.line_no,
                    )
                )

        return FailItemsResult(
            unit=unit,
            records=tuple(records),
            fail_items=tuple(fail_items),
            cached_logs=tuple(cached),
            source="manual",
            needs_user_input=len(fail_items) == 0,
            user_prompt=_USER_PROMPT if not fail_items else None,
        )

    def ingest_user_evidence(
        self,
        radar_id: str,
        text: str,
        *,
        cache_dir: Path,
        station: str | None = None,
        serial: str | None = None,
        filename: str | None = None,
    ) -> FailItemsResult:
        """Cache user-pasted log/errors and extract fail items.

        Args:
            radar_id: FA session Radar id.
            text: Pasted log or fail list (must be non-empty).
            cache_dir: ``data/cache/fa/{radar_id}/``.
            station: Optional station label.
            serial: Optional unit serial.
            filename: Optional cache file name (default ``user_paste.log``).

        Returns:
            Extracted fail items and downloadable cache paths.

        Raises:
            IntegrationError: If ``text`` is empty.
        """
        body = text.strip()
        if not body:
            raise IntegrationError("User evidence text is empty")

        rid = normalize_radar_id(radar_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        name = filename or _default_filename(station)
        path = cache_dir / name
        header_lines = [
            f"# manual FA evidence for rdar://{rid}",
            f"# station={station or ''}",
            f"# serial={serial or ''}",
            "",
            body,
            "",
        ]
        path.write_text("\n".join(header_lines), encoding="utf-8")
        logger.info("Cached manual FA evidence for %s → %s", rid, path)

        parsed = extract_errors_from_text(body)
        if not parsed:
            # Keep the file for download, but signal insufficient parse.
            unit = self.resolve_unit(rid, serial=serial)
            rel = f"fa/{rid}/{path.name}"
            return FailItemsResult(
                unit=unit,
                records=(
                    TestRecord(
                        record_id=path.stem,
                        station=station or "user_paste",
                        result="UNKNOWN",
                        log_uri=f"manual://{path.name}",
                    ),
                ),
                fail_items=(),
                cached_logs=(rel,),
                source="manual",
                needs_user_input=True,
                user_prompt=(
                    "Saved your paste, but could not find ERROR/FAIL lines "
                    "or a bullet list. Please paste errors again "
                    "(e.g. `ERROR: …` or `- item`)."
                ),
            )

        return self.collect_fail_items(rid, serial=serial, cache_dir=cache_dir)


def _default_filename(station: str | None) -> str:
    if station:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in station)
        return f"user_{safe.lower()}.log"
    return "user_paste.log"


def _station_from_filename(name: str) -> str | None:
    """Recover station from ``user_{station}.log`` filenames."""
    stem = Path(name).stem
    if stem.startswith("user_") and stem != "user_paste":
        return stem.removeprefix("user_")
    return None
