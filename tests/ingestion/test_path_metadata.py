"""Tests for path-derived metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from ee_wiki.common.errors import PathMetadataError
from ee_wiki.ingestion.path_metadata import expand_retrieval_scope, parse_path_metadata


class TestParsePathMetadata:
    def test_enterprise_datasheet(self, data_layout) -> None:
        path = data_layout.raw_dir / "global" / "datasheet" / "tps62840.pdf"
        meta = parse_path_metadata(path, data_layout, repo_root=data_layout.raw_dir.parent.parent)
        assert meta.project == "global"
        assert meta.build == "global"
        assert meta.document_type == "datasheet"
        assert meta.title == "tps62840"
        assert meta.source_file == "data/raw/global/datasheet/tps62840.pdf"

    def test_project_common_sop(self, data_layout) -> None:
        path = data_layout.raw_dir / "logan" / "common" / "sop" / "bringup.md"
        meta = parse_path_metadata(path, data_layout, repo_root=data_layout.raw_dir.parent.parent)
        assert meta.project == "logan"
        assert meta.build == "common"
        assert meta.document_type == "sop"
        assert meta.title == "bringup"

    def test_project_build_schematic(self, data_layout) -> None:
        path = data_layout.raw_dir / "logan" / "p1" / "sch" / "power-tree.pdf"
        meta = parse_path_metadata(path, data_layout, repo_root=data_layout.raw_dir.parent.parent)
        assert meta.project == "logan"
        assert meta.build == "p1"
        assert meta.document_type == "schematic"
        assert meta.title == "power-tree"

    def test_nested_subfolder(self, data_layout) -> None:
        path = data_layout.raw_dir / "logan" / "p1" / "sch" / "rev2" / "main.pdf"
        meta = parse_path_metadata(path, data_layout)
        assert meta.project == "logan"
        assert meta.build == "p1"
        assert meta.document_type == "schematic"
        assert meta.title == "main"

    def test_rejects_path_outside_raw_dir(self, data_layout, tmp_path: Path) -> None:
        outside = tmp_path / "outside.pdf"
        outside.write_text("x")
        with pytest.raises(PathMetadataError, match="not under raw_dir"):
            parse_path_metadata(outside, data_layout)

    def test_rejects_invalid_layout(self, data_layout) -> None:
        path = data_layout.raw_dir / "logan" / "p1" / "unknown" / "file.pdf"
        with pytest.raises(PathMetadataError, match="Unknown type folder"):
            parse_path_metadata(path, data_layout)

    def test_rejects_hidden_file(self, data_layout) -> None:
        path = data_layout.raw_dir / "logan" / "p1" / "sch" / ".hidden.pdf"
        with pytest.raises(PathMetadataError, match="hidden"):
            parse_path_metadata(path, data_layout)


class TestExpandRetrievalScope:
    def test_build_inherits_common_and_global(self, data_layout) -> None:
        scopes = expand_retrieval_scope("logan", "p1", data_layout)
        assert scopes == [("logan", "p1"), ("logan", "common"), ("global", "global")]

    def test_common_inherits_global_only(self, data_layout) -> None:
        scopes = expand_retrieval_scope("logan", "common", data_layout)
        assert scopes == [("logan", "common"), ("global", "global")]

    def test_global_query_is_enterprise_only(self, data_layout) -> None:
        scopes = expand_retrieval_scope("global", "global", data_layout)
        assert scopes == [("global", "global")]

    def test_no_duplicate_scopes(self, data_layout) -> None:
        scopes = expand_retrieval_scope("global", "global", data_layout)
        assert len(scopes) == len(set(scopes))
