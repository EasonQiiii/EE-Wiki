"""Tests for metadata JSON Schema validation."""

from __future__ import annotations

import pytest

from ee_wiki.common.metadata_schema import MetadataValidationError, validate_metadata_dict


def _valid_metadata() -> dict:
    return {
        "product": "logan",
        "project": "m2",
        "build": "p1",
        "document_type": "engineering_note",
        "title": "sample",
        "source_file": "data/raw/logan/m2/p1/note/sample.md",
        "target_file": "data/processed/logan/m2/p1/note/sample.md",
        "source_mtime": 1.0,
        "source_size": 42,
    }


def test_validate_metadata_dict_accepts_valid_payload(repo_root) -> None:
    validate_metadata_dict(_valid_metadata(), repo_root=repo_root)


def test_validate_metadata_dict_rejects_missing_project(repo_root) -> None:
    payload = _valid_metadata()
    del payload["project"]
    with pytest.raises(MetadataValidationError, match="Invalid document metadata"):
        validate_metadata_dict(payload, repo_root=repo_root)


def test_validate_metadata_dict_rejects_missing_product(repo_root) -> None:
    payload = _valid_metadata()
    del payload["product"]
    with pytest.raises(MetadataValidationError, match="Invalid document metadata"):
        validate_metadata_dict(payload, repo_root=repo_root)


def test_validate_metadata_dict_rejects_empty_title(repo_root) -> None:
    payload = _valid_metadata()
    payload["title"] = ""
    with pytest.raises(MetadataValidationError, match="Invalid document metadata"):
        validate_metadata_dict(payload, repo_root=repo_root)
