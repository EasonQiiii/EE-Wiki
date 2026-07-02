"""Tests for processed source and asset routes."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_config
from ee_wiki.common.config import load_config


def test_sources_and_assets_routes_serve_processed_files(repo_root: Path, tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    note_dir = processed / "logan/p1/note"
    assets = note_dir / "manual.assets"
    assets.mkdir(parents=True)
    md_path = note_dir / "manual.md"
    md_path.write_text("# Manual\n", encoding="utf-8")
    image_path = assets / "diag.png"
    image_path.write_bytes(b"fakepng")

    config = load_config(repo_root=repo_root)
    from dataclasses import replace

    config = replace(config, processed_dir=processed)

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    source = client.get("/v1/sources/logan/p1/note/manual.md")
    assert source.status_code == 200
    assert "Manual" in source.text

    asset = client.get("/v1/assets/logan/p1/note/manual.assets/diag.png")
    assert asset.status_code == 200
    assert asset.content == b"fakepng"


def test_sources_route_blocks_path_traversal(repo_root: Path, tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "safe.md").write_text("ok", encoding="utf-8")

    config = load_config(repo_root=repo_root)
    from dataclasses import replace

    config = replace(config, processed_dir=processed)

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    assert client.get("/v1/sources/../safe.md").status_code == 404
    assert client.get("/v1/assets/../../etc/passwd").status_code == 404
