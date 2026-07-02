"""Build citation URLs for processed documents and embedded images."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from ee_wiki.common.config import ApiConfig, AppConfig

_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def resolve_public_base_url(api: ApiConfig) -> str:
    """Return the public API base URL used in citation links."""
    if api.public_base_url:
        return str(api.public_base_url).rstrip("/")
    host = "localhost" if api.host in {"0.0.0.0", "::"} else api.host
    return f"http://{host}:{api.port}"


def processed_relative_path(target_file: str, processed_dir: Path) -> str:
    """Map a processed ``target_file`` label to a URL path under ``/v1/sources``."""
    path = Path(target_file)
    try:
        rel = path.resolve().relative_to(processed_dir.resolve())
    except ValueError:
        rel = Path(path.name)
    return rel.as_posix()


def section_fragment(chunk_id: str) -> str:
    """Derive an HTML fragment anchor from a chunk id suffix."""
    if "__" not in chunk_id:
        return ""
    suffix = chunk_id.split("__", 1)[1]
    base = re.sub(r"__w\d+$", "", suffix)
    return f"#{base}" if base else ""


def source_document_url(config: AppConfig, *, target_file: str, chunk_id: str) -> str:
    """Build a clickable URL for a processed source document."""
    base = resolve_public_base_url(config.api)
    rel = processed_relative_path(target_file, config.processed_dir)
    fragment = section_fragment(chunk_id)
    return f"{base}/v1/sources/{quote(rel, safe='/')}{fragment}"


def asset_url(config: AppConfig, *, asset_rel: str) -> str:
    """Build a public URL for a file under ``data/processed/``."""
    base = resolve_public_base_url(config.api)
    normalized = PurePosixPath(asset_rel.lstrip("/")).as_posix()
    return f"{base}/v1/assets/{quote(normalized, safe='/')}"


def parse_markdown_image_refs(content: str) -> list[str]:
    """Extract image targets from Markdown ``![alt](path)`` syntax."""
    refs: list[str] = []
    for match in _MARKDOWN_IMAGE_PATTERN.finditer(content):
        target = match.group(1).strip().strip('"').strip("'")
        if target and not target.startswith("#"):
            refs.append(target)
    return refs


def resolve_asset_relative_path(
    target_file: str,
    image_ref: str,
    processed_dir: Path,
) -> str | None:
    """Resolve a Markdown image reference to a processed-relative path."""
    ref = image_ref.strip()
    if not ref or ref.startswith("#"):
        return None
    if ref.startswith(("http://", "https://")):
        return ref

    target_path = Path(target_file)
    if not target_path.is_absolute():
        target_path = (processed_dir / target_path).resolve()
    else:
        target_path = target_path.resolve()

    resolved = (target_path.parent / ref).resolve()
    try:
        rel = resolved.relative_to(processed_dir.resolve())
    except ValueError:
        return None
    if not resolved.is_file():
        return None
    return rel.as_posix()


def citation_image_urls(config: AppConfig, *, target_file: str, content: str) -> tuple[str, ...]:
    """Return public image URLs referenced inside a retrieved chunk."""
    if not target_file:
        return ()

    urls: list[str] = []
    seen: set[str] = set()
    for ref in parse_markdown_image_refs(content):
        if ref.startswith(("http://", "https://")):
            if ref not in seen:
                seen.add(ref)
                urls.append(ref)
            continue
        rel = resolve_asset_relative_path(target_file, ref, config.processed_dir)
        if rel is None:
            continue
        url = asset_url(config, asset_rel=rel)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return tuple(urls)
