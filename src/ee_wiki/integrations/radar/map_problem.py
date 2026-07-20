"""Map Apple ``radarclient`` objects onto EE-Wiki Radar protocols."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.integrations.radar.evidence import is_radar_history_entry
from ee_wiki.protocols.radar import (
    AttachmentMeta,
    DescriptionItem,
    DiagnosisItem,
    RadarComponentRef,
    RadarProblem,
)


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    """Return the first present attribute / dict key among ``names``."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj[name] is not None:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    # Person / enum-like objects often stringify usefully.
    text = str(value).strip()
    return text or None


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return None


def _collection_items(container: Any) -> list[Any]:
    """Return items from a radarclient collection or plain sequence."""
    if container is None:
        return []
    if hasattr(container, "items") and callable(container.items):
        try:
            return list(container.items())
        except TypeError:
            # dict.items() takes no radar-style args; still fine.
            return list(container.items())
    if isinstance(container, (list, tuple)):
        return list(container)
    try:
        return list(container)
    except TypeError:
        return []


def map_component(raw: Any) -> RadarComponentRef | None:
    """Map ``radar.component`` (dict or object) to :class:`RadarComponentRef`."""
    if raw is None:
        return None
    name = _as_str(_attr(raw, "name", "Name"))
    version = _as_str(_attr(raw, "version", "Version")) or ""
    if not name and not version:
        return None
    raw_id = _attr(raw, "id", "ID", "Id")
    comp_id: int | None
    try:
        comp_id = int(raw_id) if raw_id is not None else None
    except (TypeError, ValueError):
        comp_id = None
    return RadarComponentRef(id=comp_id, name=name or "", version=version)


def map_description_entry(entry: Any) -> DescriptionItem | None:
    """Map one ``DescriptionEntry`` to :class:`DescriptionItem`."""
    text = _as_str(_attr(entry, "text", "Text", "summary", "Summary"))
    if not text:
        return None
    return DescriptionItem(
        text=text,
        added_by=_as_str(_attr(entry, "addedBy", "added_by", "author")),
        added_at=_as_datetime(_attr(entry, "addedAt", "added_at", "createdAt")),
    )


def map_diagnosis_entry(entry: Any) -> DiagnosisItem | None:
    """Map one ``DiagnosisEntry`` to :class:`DiagnosisItem`."""
    text = _as_str(_attr(entry, "text", "Text"))
    if not text:
        return None
    entry_type = "history" if is_radar_history_entry(text) else "user"
    return DiagnosisItem(
        text=text,
        added_by=_as_str(_attr(entry, "addedBy", "added_by", "author")),
        added_at=_as_datetime(_attr(entry, "addedAt", "added_at", "createdAt")),
        entry_type=entry_type,
    )


def map_attachment(entry: Any, *, kind: str) -> AttachmentMeta | None:
    """Map one attachment / picture entry to :class:`AttachmentMeta`."""
    name = _as_str(
        _attr(entry, "fileName", "file_name", "filename", "name", "Name")
    )
    if not name:
        return None
    size_raw = _attr(entry, "fileSize", "file_size", "size")
    size: int | None
    try:
        size = int(size_raw) if size_raw is not None else None
    except (TypeError, ValueError):
        size = None
    return AttachmentMeta(
        file_name=name,
        file_size=size,
        kind=kind,
        added_by=_as_str(_attr(entry, "addedBy", "added_by", "author")),
        added_at=_as_datetime(
            _attr(entry, "addedAt", "added_at", "createdAt", "created_at")
        ),
    )


def map_radar_problem(raw: Any, *, radar_id: str | int) -> RadarProblem:
    """Normalize a live ``radarclient`` Radar object to :class:`RadarProblem`.

    Args:
        raw: Object returned by ``RadarClient.radar_for_id``.
        radar_id: Requested id (used when the live object omits ``id``).

    Returns:
        EE-Wiki problem snapshot including description, diagnosis, attachments.
    """
    rid = normalize_radar_id(str(_attr(raw, "id", "ID") or radar_id))
    title = _as_str(_attr(raw, "title", "Title")) or f"rdar://{rid}"

    description = tuple(
        item
        for item in (
            map_description_entry(e)
            for e in _collection_items(_attr(raw, "description", "Description"))
        )
        if item is not None
    )
    diagnosis = tuple(
        item
        for item in (
            map_diagnosis_entry(e)
            for e in _collection_items(_attr(raw, "diagnosis", "Diagnosis"))
        )
        if item is not None
    )
    attachments: list[AttachmentMeta] = []
    for entry in _collection_items(_attr(raw, "attachments", "Attachments")):
        meta = map_attachment(entry, kind="attachment")
        if meta is not None:
            attachments.append(meta)
    for entry in _collection_items(_attr(raw, "pictures", "Pictures")):
        meta = map_attachment(entry, kind="picture")
        if meta is not None:
            attachments.append(meta)

    found_raw = _attr(raw, "foundInBuild", "found_in_build", "foundInBuilds")
    found: list[str] = []
    if isinstance(found_raw, (list, tuple)):
        found = [s for s in (_as_str(x) for x in found_raw) if s]
    else:
        one = _as_str(found_raw)
        if one:
            found = [one]

    return RadarProblem(
        radar_id=rid,
        title=title,
        state=_as_str(_attr(raw, "state", "State")),
        substate=_as_str(_attr(raw, "substate", "Substate")),
        component=map_component(_attr(raw, "component", "Component")),
        found_in_builds=tuple(found),
        configuration_summary=_as_str(
            _attr(
                raw,
                "configurationSummary",
                "configuration_summary",
                "ConfigurationSummary",
            )
        ),
        assignee=_as_str(_attr(raw, "assignee", "Assignee")),
        priority=_as_str(_attr(raw, "priority", "Priority")),
        description=description,
        diagnosis=diagnosis,
        attachments=tuple(attachments),
    )
