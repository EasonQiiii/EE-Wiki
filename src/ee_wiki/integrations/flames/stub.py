"""Offline stub Flames backend with synthetic logs and error extraction."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.flames.parse import extract_errors_from_path
from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.protocols.flames import (
    FailItem,
    FailItemsResult,
    FlamesUnitRef,
    TestRecord,
)

logger = get_logger(__name__)


class StubFlamesBackend:
    """Synthetic Flames stand-in for offline FA triage UX."""

    def resolve_unit(
        self,
        radar_id: str,
        *,
        serial: str | None = None,
    ) -> FlamesUnitRef:
        """Return a synthetic unit keyed by Radar id."""
        rid = normalize_radar_id(radar_id)
        return FlamesUnitRef(
            unit_id=f"stub-unit-{rid}",
            serial=serial or f"SN-STUB-{rid}",
            radar_id=rid,
        )

    def list_test_records(self, unit: FlamesUnitRef) -> list[TestRecord]:
        """Return two synthetic station attempts for ``unit``."""
        rid = unit.radar_id or unit.unit_id
        return [
            TestRecord(
                record_id=f"{rid}-smt-ict",
                station="SMT_ICT",
                stage="post-smt",
                result="FAIL",
                log_uri="stub://smt_ict.log",
            ),
            TestRecord(
                record_id=f"{rid}-fqt",
                station="FQT",
                stage="final",
                result="FAIL",
                log_uri="stub://fqt.log",
            ),
        ]

    def fetch_log(self, record: TestRecord, dest_dir: Path) -> Path:
        """Write a small synthetic log containing ERROR lines."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"{record.station.lower()}.log"
        body = (
            f"# stub flames log for {record.record_id}\n"
            f"station={record.station}\n"
            f"result={record.result}\n"
            f"ERROR: {record.station} measured rail VDD_CORE out of range\n"
            f"INFO: continuing diagnostics\n"
            f"FAIL: {record.station} AAB retry limit exceeded\n"
        )
        path.write_text(body, encoding="utf-8")
        logger.info("Wrote stub Flames log %s", path)
        return path

    def extract_errors(self, log_path: Path) -> list[FailItem]:
        """Extract ERROR/FAIL lines from a cached log."""
        return extract_errors_from_path(log_path)

    def collect_fail_items(
        self,
        radar_id: str,
        *,
        serial: str | None = None,
        cache_dir: Path,
    ) -> FailItemsResult:
        """Resolve unit, cache logs, and extract all error items."""
        rid = normalize_radar_id(radar_id)
        unit = self.resolve_unit(rid, serial=serial)
        records = self.list_test_records(unit)
        cache_dir.mkdir(parents=True, exist_ok=True)
        fail_items: list[FailItem] = []
        cached: list[str] = []
        for record in records:
            log_path = self.fetch_log(record, cache_dir)
            rel = f"fa/{rid}/{log_path.name}"
            cached.append(rel)
            for item in self.extract_errors(log_path):
                fail_items.append(
                    FailItem(
                        message=item.message,
                        station=record.station,
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
            source="stub",
            needs_user_input=False,
            user_prompt=None,
        )
