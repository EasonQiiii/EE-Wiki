"""Validate document metadata against config/schema/metadata.schema.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ee_wiki.common.errors import EEWikiError

SCHEMA_RELATIVE_PATH = Path("config/schema/metadata.schema.json")


class MetadataValidationError(EEWikiError):
    """Metadata sidecar payload failed JSON Schema validation."""


@lru_cache(maxsize=4)
def load_metadata_schema(repo_root: Path) -> dict[str, Any]:
    """Load the metadata JSON Schema from the repository.

    Args:
        repo_root: Repository root containing ``config/schema/``.

    Returns:
        Parsed JSON Schema document.

    Raises:
        MetadataValidationError: If the schema file is missing or invalid JSON.
    """
    path = (repo_root / SCHEMA_RELATIVE_PATH).resolve()
    if not path.is_file():
        raise MetadataValidationError(f"Metadata schema not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataValidationError(f"Failed to read metadata schema: {path}") from exc


def validate_metadata_dict(
    data: dict[str, Any],
    *,
    repo_root: Path,
) -> None:
    """Validate a metadata mapping before writing a processed sidecar.

    Args:
        data: Metadata JSON object to validate.
        repo_root: Repository root for schema lookup.

    Raises:
        MetadataValidationError: If validation fails.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError

    schema = load_metadata_schema(repo_root)
    validator = Draft202012Validator(schema)
    try:
        validator.validate(data)
    except ValidationError as exc:
        raise MetadataValidationError(f"Invalid document metadata: {exc.message}") from exc
