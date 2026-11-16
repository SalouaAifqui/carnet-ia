"""[code] Cut the source into numbered chunks, and find them again after a pause.

The librarian plans each part of the article with the NUMBERS of the chunks it is based on.
Each writer then receives only its chunks: smaller prompts, nothing important drowned out.

The chunks themselves are not saved in the plan comment (too big, and it would republish course
transcripts). After the pause the sources are fetched again and cut again; each chunk is found
back from a short fingerprint saved with the plan.
"""
from __future__ import annotations

import difflib
import re

CHUNK_WORDS = 300


def chunk_text(text: str, words: int = CHUNK_WORDS) -> list[str]:
    """Group paragraphs into chunks of about `words` words. Headers like '=== Source 2 … ==='
    always start a new chunk, so a chunk never mixes two sources."""
    chunks, current, count = [], [], 0
    for paragraph in [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]:
        n = len(paragraph.split())
        starts_source = paragraph.startswith("=== ")
        if current and (count + n > words or starts_source):
            chunks.append("\n\n".join(current))
            current, count = [], 0
        if n > words * 2:                                   # one huge paragraph: split it by sentences
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            for sentence in sentences:
                current.append(sentence)
                count += len(sentence.split())
                if count >= words:
                    chunks.append(" ".join(current))
                    current, count = [], 0
            continue
        current.append(paragraph)
        count += n
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def numbered(chunks: list[str], ids: list[int] | None = None) -> str:
    """'[C3] text…' blocks, for a prompt. Chunk numbers start at 1."""
    ids = ids or list(range(1, len(chunks) + 1))
    return "\n\n".join(f"[C{i}]\n{chunks[i - 1]}" for i in ids if 1 <= i <= len(chunks))


def fingerprint(chunk: str) -> str:
    return re.sub(r"\W+", " ", chunk).strip()[:120]


def remap(saved_fingerprints: list[str], chunks: list[str]) -> dict[int, int]:
    """Old chunk number -> new chunk number, matching fingerprints (exact, then closest)."""
    new_prints = [fingerprint(c) for c in chunks]
    mapping = {}
    for old, fp in enumerate(saved_fingerprints, 1):
        if fp in new_prints:
            mapping[old] = new_prints.index(fp) + 1
            continue
        close = difflib.get_close_matches(fp, new_prints, n=1, cutoff=0.6)
        if close:
            mapping[old] = new_prints.index(close[0]) + 1
    return mapping
