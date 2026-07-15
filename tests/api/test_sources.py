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


def test_raw_route_serves_original_document(repo_root: Path, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    datasheet_dir = raw / "logan/p1/datasheet"
    datasheet_dir.mkdir(parents=True)
    pdf_path = datasheet_dir / "STM32F4.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    config = load_config(repo_root=repo_root)
    from dataclasses import replace

    config = replace(config, raw_dir=raw)

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    raw_doc = client.get("/v1/raw/logan/p1/datasheet/STM32F4.pdf")
    assert raw_doc.status_code == 200
    assert raw_doc.content == b"%PDF-1.4 fake"


def test_raw_route_blocks_path_traversal(repo_root: Path, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "safe.pdf").write_bytes(b"%PDF-1.4 ok")

    config = load_config(repo_root=repo_root)
    from dataclasses import replace

    config = replace(config, raw_dir=raw)

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    assert client.get("/v1/raw/../../etc/passwd").status_code == 404
