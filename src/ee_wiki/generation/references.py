"""Stream helpers for generated answers."""


def iter_stream_chunks(text: str, *, max_chars: int = 200):
    """Yield stream-sized text pieces for SSE responses."""
    if not text:
        return

    start = 0
    while start < len(text):
        yield text[start : start + max_chars]
        start += max_chars
