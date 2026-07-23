"""Live Apple ``radarclient`` backend for FA sessions (ADR 0010).

Auth matches the lab demo: SPNego (Kerberos / AppleConnect ticket cache) plus
a ``ClientSystemIdentifier``. Passwords and ``appleconnect`` automations are
**not** handled here — obtain a ticket on the host before starting EE-Wiki.

``radarclient`` is Apple-internal and is **not** vendored in this repository.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ee_wiki.common.errors import ConfigError, IntegrationError
from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.integrations.radar.map_problem import map_radar_problem
from ee_wiki.protocols.radar import (
    AttachmentMeta,
    DiagnosisItem,
    RadarProblem,
    RadarWriteResult,
)

logger = get_logger(__name__)

_ADDITIONAL_FIELDS = (
    "description",
    "diagnosis",
    "attachments",
    "pictures",
    "component",
    "foundInBuild",
    "configurationSummary",
    "assignee",
    "priority",
    "state",
    "substate",
    "title",
)


class RadarclientBackend:
    """Radar backend backed by Apple ``radarclient`` + SPNego."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        client_system_name: str = "EE-Wiki",
        client_system_version: str = "1.0",
    ) -> None:
        """Construct a live Radar client.

        Args:
            client: Optional pre-built ``RadarClient`` (tests inject a mock).
            client_system_name: ``ClientSystemIdentifier`` name sent to Radar.
            client_system_version: ``ClientSystemIdentifier`` version string.

        Raises:
            ConfigError: If ``radarclient`` cannot be imported or the client
                cannot be constructed (usually missing Kerberos ticket).
        """
        if client is not None:
            self._client = client
            return
        try:
            from radarclient import (  # type: ignore[import-not-found]
                AuthenticationStrategySPNego,
                ClientSystemIdentifier,
                RadarClient,
            )
        except ImportError as exc:
            raise ConfigError(
                "fa.radar.backend=radarclient requires the Apple radarclient "
                "package on PYTHONPATH (not vendored in EE-Wiki). "
                "See docs/architecture/integrations-radar.md"
            ) from exc

        try:
            self._client = RadarClient(
                AuthenticationStrategySPNego(),
                ClientSystemIdentifier(
                    client_system_name, client_system_version
                ),
            )
        except Exception as exc:
            raise ConfigError(
                "Failed to construct RadarClient (SPNego). "
                "Ensure AppleConnect / Kerberos ticket is valid on this host, "
                "then retry. See docs/architecture/integrations-radar.md"
            ) from exc
        logger.info(
            "RadarclientBackend ready (system=%s %s)",
            client_system_name,
            client_system_version,
        )

    def get_problem(self, radar_id: str) -> RadarProblem:
        """Fetch a live Radar problem including description and diagnosis."""
        rid = normalize_radar_id(radar_id)
        raw = self._radar_for_id(rid)
        problem = map_radar_problem(raw, radar_id=rid)
        logger.info(
            "Radar get_problem id=%s title=%r desc=%d diagnosis=%d attachments=%d",
            problem.radar_id,
            problem.title[:80],
            len(problem.description),
            len(problem.diagnosis),
            len(problem.attachments),
        )
        return problem

    def list_diagnosis(self, radar_id: str) -> list[DiagnosisItem]:
        """List diagnosis entries for ``radar_id``."""
        return list(self.get_problem(radar_id).diagnosis)

    def list_attachments(self, radar_id: str) -> list[AttachmentMeta]:
        """List attachment and picture metadata for ``radar_id``."""
        return list(self.get_problem(radar_id).attachments)

    def add_diagnosis(
        self,
        radar_id: str,
        text: str,
        *,
        confirm: bool = False,
    ) -> RadarWriteResult:
        """Append a diagnosis entry (commit only when ``confirm`` is true)."""
        rid = normalize_radar_id(radar_id)
        body = text.strip()
        if not body:
            raise IntegrationError("add_diagnosis requires non-empty text")
        if not confirm:
            return RadarWriteResult(
                radar_id=rid,
                action="add_diagnosis",
                committed=False,
                detail="Draft only; pass confirm=true to commit",
                draft_preview=body,
            )

        try:
            from radarclient import DiagnosisEntry  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ConfigError(
                "radarclient.DiagnosisEntry unavailable on PYTHONPATH"
            ) from exc

        radar = self._radar_for_id(rid)
        entry = DiagnosisEntry()
        entry.text = body
        radar.diagnosis.add(entry)
        radar.commit_changes()
        logger.info("Radar diagnosis committed for %s (%d chars)", rid, len(body))
        return RadarWriteResult(
            radar_id=rid,
            action="add_diagnosis",
            committed=True,
            detail="Diagnosis committed via radarclient",
        )

    def upload_attachment(
        self,
        radar_id: str,
        path: Path,
        *,
        confirm: bool = False,
        as_picture: bool = False,
    ) -> RadarWriteResult:
        """Upload a local file (commit only when ``confirm`` is true).

        Uses the lab demo API: ``new_attachment`` + ``set_upload_file`` +
        ``commit_changes``. Picture uploads use the pictures collection when
        ``as_picture`` is true and the client exposes ``new_picture``.
        """
        rid = normalize_radar_id(radar_id)
        file_path = Path(path)
        kind = "picture" if as_picture else "attachment"
        if not confirm:
            return RadarWriteResult(
                radar_id=rid,
                action=f"upload_{kind}",
                committed=False,
                detail="Draft only; pass confirm=true to commit",
                draft_preview=str(file_path),
            )
        if not file_path.is_file():
            raise IntegrationError(f"Attachment file not found: {file_path}")

        radar = self._radar_for_id(rid)
        name = file_path.name
        try:
            if as_picture and hasattr(radar, "new_picture"):
                attachment = radar.new_picture(name)
                collection = radar.pictures
            else:
                attachment = radar.new_attachment(name)
                collection = radar.attachments

            # Prefer file handle API from the lab demo; fall back to content.
            if hasattr(attachment, "set_upload_file"):
                with file_path.open("rb") as handle:
                    attachment.set_upload_file(handle)
                    if hasattr(attachment, "overwrite_existing_file"):
                        attachment.overwrite_existing_file = True
                    collection.add(attachment)
                    radar.commit_changes()
            elif hasattr(attachment, "set_upload_content"):
                attachment.set_upload_content(file_path.read_bytes())
                if hasattr(attachment, "overwrite_existing_file"):
                    attachment.overwrite_existing_file = True
                collection.add(attachment)
                radar.commit_changes()
            else:
                raise IntegrationError(
                    "radarclient attachment object has neither "
                    "set_upload_file nor set_upload_content"
                )
        except IntegrationError:
            raise
        except Exception as exc:
            raise IntegrationError(
                f"Radar {kind} upload failed for rdar://{rid}: {exc}"
            ) from exc

        logger.info("Radar %s uploaded for %s: %s", kind, rid, name)
        return RadarWriteResult(
            radar_id=rid,
            action=f"upload_{kind}",
            committed=True,
            detail=f"{kind} uploaded: {name}",
        )

    def download_attachment(
        self,
        radar_id: str,
        file_name: str,
        dest_path: Path,
    ) -> Path:
        """Download one attachment by file name into ``dest_path``.

        Args:
            radar_id: Target problem id.
            file_name: Exact ``fileName`` as listed on the problem.
            dest_path: Local file path to write (parent dirs created).

        Returns:
            ``dest_path`` after a successful write.

        Raises:
            IntegrationError: If the attachment is missing or download fails.
        """
        rid = normalize_radar_id(radar_id)
        radar = self._radar_for_id(rid)
        target = None
        found_in = None
        # Search attachments first, then fall back to the pictures collection.
        # Live Radar sometimes stores images under either collection while
        # map_problem tags them kind="picture" — so download_attachment must
        # not hard-fail when a .png lives in `pictures` (Problem 5, root A).
        # The API chosen here (download_attachment) is still logged as such;
        # the resolved collection is only a debug aid for live collection gaps.
        for label, collection in (
            ("attachments", getattr(radar, "attachments", None)),
            ("pictures", getattr(radar, "pictures", None)),
        ):
            if collection is None:
                continue
            for entry in list(getattr(collection, "items", lambda: [])()):
                name = getattr(entry, "fileName", None) or getattr(
                    entry, "file_name", None
                )
                if name == file_name:
                    target = entry
                    found_in = label
                    break
            if target is not None:
                break
        if target is None:
            raise IntegrationError(
                f"Attachment {file_name!r} not found on rdar://{rid}"
            )
        if found_in != "attachments":
            logger.debug(
                "Radar attachment %r resolved from %s collection via "
                "download_attachment (called with kind=attachment)",
                file_name,
                found_in,
            )
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with dest_path.open("wb+") as handle:
                target.write_to_file(handle, continue_at=0, client=self._client)
        except Exception as exc:
            raise IntegrationError(
                f"Failed to download {file_name!r} from rdar://{rid}: {exc}"
            ) from exc
        logger.info("Radar attachment downloaded rdar://%s -> %s", rid, dest_path)
        return dest_path

    def download_picture(
        self,
        radar_id: str,
        file_name: str,
        dest_path: Path,
    ) -> Path:
        """Download one picture by file name into ``dest_path``.

        Pictures live in the ``radar.pictures`` collection, not
        ``radar.attachments`` — ``download_attachment`` cannot see them and
        raises "not found". Mirrors :meth:`download_attachment` but scans the
        pictures collection instead.

        Args:
            radar_id: Target problem id.
            file_name: Exact ``fileName`` as listed on the problem.
            dest_path: Local file path to write (parent dirs created).

        Returns:
            ``dest_path`` after a successful write.

        Raises:
            IntegrationError: If the picture is missing or download fails.
        """
        rid = normalize_radar_id(radar_id)
        radar = self._radar_for_id(rid)
        target = None
        found_in = None
        # Search pictures first, then fall back to the attachments collection.
        # Mirror of download_attachment's cross-collection fallback (Problem 5,
        # root A): a file tagged kind="picture" may in fact live under
        # radar.attachments on the live server, so don't hard-fail on miss.
        for label, collection in (
            ("pictures", getattr(radar, "pictures", None)),
            ("attachments", getattr(radar, "attachments", None)),
        ):
            if collection is None:
                continue
            for entry in list(getattr(collection, "items", lambda: [])()):
                name = getattr(entry, "fileName", None) or getattr(
                    entry, "file_name", None
                )
                if name == file_name:
                    target = entry
                    found_in = label
                    break
            if target is not None:
                break
        if target is None:
            raise IntegrationError(
                f"Picture {file_name!r} not found on rdar://{rid}"
            )
        if found_in != "pictures":
            logger.debug(
                "Radar picture %r resolved from %s collection via "
                "download_picture (called with kind=picture)",
                file_name,
                found_in,
            )
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with dest_path.open("wb+") as handle:
                target.write_to_file(handle, continue_at=0, client=self._client)
        except Exception as exc:
            raise IntegrationError(
                f"Failed to download picture {file_name!r} from rdar://{rid}: {exc}"
            ) from exc
        logger.info("Radar picture downloaded rdar://%s -> %s", rid, dest_path)
        return dest_path

    def _radar_for_id(self, radar_id: str) -> Any:
        """Load a Radar problem, requesting FA-relevant additional fields."""
        numeric = int(normalize_radar_id(radar_id))
        try:
            return self._client.radar_for_id(
                numeric,
                additional_fields=list(_ADDITIONAL_FIELDS),
            )
        except TypeError:
            # Older radarclient builds may not accept additional_fields.
            return self._client.radar_for_id(numeric)
        except Exception as exc:
            raise IntegrationError(
                f"radar_for_id({numeric}) failed: {exc}"
            ) from exc
