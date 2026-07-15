"""Build citation URLs for processed documents and embedded images."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from ee_wiki.common.config import ApiConfig, AppConfig
from ee_wiki.ingestion.parsers.schematic_pdf.prompt import schematic_image_slug

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


def raw_relative_path(source_file: str, raw_dir: Path) -> str:
    """Map a raw ``source_file`` label to a URL path under ``/v1/raw``.

    Labels are usually repo-relative (``data/raw/...``) or absolute paths.
    Strip the leading ``data/raw`` segment(s) so the result is relative to
    ``raw_dir`` and safe to embed in a URL.
    """
    path = Path(source_file)
    parts = PurePosixPath(source_file.replace("\\", "/")).parts
    if "raw" in parts:
        idx = len(parts) - 1 - parts[::-1].index("raw")
        stripped = parts[idx + 1 :]
        if stripped:
            return Path(*stripped).as_posix()
    try:
        return path.resolve().relative_to(raw_dir.resolve()).as_posix()
    except ValueError:
        return path.name


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


def raw_document_url(config: AppConfig, *, source_file: str) -> str:
    """Build a clickable download URL for a raw source document.

    Unlike :func:`source_document_url`, this points at the original file under
    ``data/raw/`` (e.g. a ``.pdf`` or ``.docx``) rather than the processed
    ``.md`` mirror. The HTML section fragment is intentionally dropped because
    raw binary documents have no in-page anchors.
    """
    base = resolve_public_base_url(config.api)
    rel = raw_relative_path(source_file, config.raw_dir)
    return f"{base}/v1/raw/{quote(rel, safe='/')}"


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


def _resolve_target_under_processed(target_file: str, processed_dir: Path) -> Path:
    """Map a ``target_file`` label to an absolute path under ``processed_dir``.

    Labels are usually repo-relative (``data/processed/...``); joining them
    directly onto ``processed_dir`` would duplicate the prefix, so strip any
    leading components up to the processed directory name first.
    """
    path = Path(target_file)
    root = processed_dir.resolve()
    if path.is_absolute():
        return path.resolve()

    parts = PurePosixPath(target_file.replace("\\", "/")).parts
    if root.name in parts:
        idx = len(parts) - 1 - parts[::-1].index(root.name)
        stripped = parts[idx + 1 :]
        if stripped:
            return (root / Path(*stripped)).resolve()
    return (root / path).resolve()


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

    target_path = _resolve_target_under_processed(target_file, processed_dir)

    resolved = (target_path.parent / ref).resolve()
    try:
        rel = resolved.relative_to(processed_dir.resolve())
    except ValueError:
        return None
    if not resolved.is_file():
        return None
    return rel.as_posix()


def page_image_url(config: AppConfig, *, target_file: str, page: int) -> str | None:
    """Return the public URL of a saved full-page render for a schematic page.

    Page renders follow the ingestion convention
    ``images/{slug}/{slug}_p{page}_page.png`` next to the processed ``.md``.

    Args:
        config: Application configuration.
        target_file: Processed markdown path label for the citation.
        page: 1-based page number from the citation.

    Returns:
        Public asset URL, or ``None`` when the render does not exist.
    """
    if not target_file or page <= 0:
        return None
    slug = schematic_image_slug(Path(target_file).stem)
    ref = f"images/{slug}/{slug}_p{page}_page.png"
    rel = resolve_asset_relative_path(target_file, ref, config.processed_dir)
    if rel is None:
        return None
    return asset_url(config, asset_rel=rel)


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
