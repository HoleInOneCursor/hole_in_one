from __future__ import annotations

import re


def split_feedback(markdown: str, max_chunks: int) -> list[str]:
    """Split Greptile markdown into chunks for parallel fixers (best-effort)."""
    lines = markdown.splitlines()
    chunks: list[str] = []
    cur: list[str] = []

    def flush() -> None:
        t = "\n".join(cur).strip()
        if t:
            chunks.append(t)
        cur.clear()

    def is_bullet(line: str) -> bool:
        return bool(re.match(r"^\s*([-*]|\d+\.)\s+", line))

    for line in lines:
        if not line.strip() and cur:
            flush()
            continue
        if is_bullet(line) and cur and is_bullet(cur[0]):
            flush()
        cur.append(line)
    flush()

    if not chunks and markdown.strip():
        return [markdown.strip()]

    return chunks[: max(1, max_chunks)]
