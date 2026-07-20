"""Tests for FA export and cache download routes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_config
from ee_wiki.common.config import load_config


def test_exports_and_cache_routes_serve_files(
    repo_root: Path, tmp_path: Path
) -> None:
    exports = tmp_path / "exports"
    cache = tmp_path / "cache"
    fa_export = exports / "fa/12345678"
    fa_cache = cache / "fa/12345678"
    fa_export.mkdir(parents=True)
    fa_cache.mkdir(parents=True)
    summary = fa_export / "FA_summary.key"
    summary.write_text("keynote-bytes", encoding="utf-8")
    log = fa_cache / "smt_ict.log"
    log.write_text("ERROR: boom\n", encoding="utf-8")

    config = load_config(repo_root=repo_root)
    config = replace(config, exports_dir=exports, cache_dir=cache)

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    export_resp = client.get("/v1/exports/fa/12345678/FA_summary.key")
    assert export_resp.status_code == 200
    assert export_resp.content == b"keynote-bytes"

    cache_resp = client.get("/v1/cache/fa/12345678/smt_ict.log")
    assert cache_resp.status_code == 200
    assert b"ERROR" in cache_resp.content


def test_exports_route_blocks_path_traversal(
    repo_root: Path, tmp_path: Path
) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "safe.key").write_text("ok", encoding="utf-8")

    config = load_config(repo_root=repo_root)
    config = replace(config, exports_dir=exports)

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    assert client.get("/v1/exports/../safe.key").status_code == 404
    assert client.get("/v1/exports/../../etc/passwd").status_code == 404
