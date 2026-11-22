"""Pre-render step: one index of every note, used for reading times, lesson numbers and counts.

Reads the topic pages (their `## … {.group-title data-folder="…"}` sections, in order) and the notes
in each section folder (sorted by `order`, then title). Writes, in `_carnet/` (not committed):
- notes.json: read by the Lua filter (`_filters/carnet.lua`) for the meta line under each title;
- notes-data.html: the same data inlined in every page, for the sidebar, listings and home counts.

Standard library only: it runs in GitHub Actions before `quarto render`.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPICS = ["llms", "agents", "evaluation", "guardrails", "toolbox"]       # navbar order
WORDS_PER_MINUTE = 200
SECTION = re.compile(r'^## (.+?) \{([^}]*\.group-title[^}]*)\}\s*$', re.M)


def front_matter(text: str) -> tuple[dict, str]:
    """The simple `key: value` lines of the front matter (enough for title, order, dates, image)."""
    if not text.startswith("---"):
        return {}, text
    head, _, body = text[3:].partition("\n---")
    meta = {}
    for line in head.splitlines():
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m and m.group(2):
            meta[m.group(1)] = m.group(2).strip().strip("'\"").replace("''", "'")
    return meta, body.split("\n", 1)[1] if "\n" in body else ""


def word_count(body: str) -> int:
    """Words a reader goes through: prose, code and tables, without markup lines and HTML tags."""
    body = re.sub(r"(?m)^:::.*$", " ", body)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\{[.#][^}]*\}", " ", body)
    return len(re.findall(r"[\w][\w'’.-]*", body))


def minutes(words: int) -> int:
    return max(1, math.floor(words / WORDS_PER_MINUTE + 0.5))


def build() -> dict:
    topics, notes = {}, {}
    for topic in TOPICS:
        index = ROOT / topic / "index.qmd"
        if not index.exists():
            continue
        meta, body = front_matter(index.read_text(encoding="utf-8"))
        sections = []
        for title, attrs in SECTION.findall(body):
            folder = re.search(r'data-folder="([^"]+)"', attrs)
            if not folder:
                continue
            files = []
            where = re.search(r'data-dir="([^"]+)"', attrs)      # notes kept elsewhere (URLs unchanged)
            notes_dir = ROOT / where.group(1) if where else ROOT / topic / folder.group(1)
            for path in sorted(notes_dir.glob("*.qmd")):
                note_meta, note_body = front_matter(path.read_text(encoding="utf-8"))
                order = note_meta.get("order")
                try:
                    order = float(order)
                except (TypeError, ValueError):
                    order = 1e9
                files.append((order, note_meta.get("title", path.stem).lower(), path, note_meta, note_body))
            files.sort(key=lambda f: (f[0], f[1]))
            keys = []
            for _, _, path, note_meta, note_body in files:
                key = path.relative_to(ROOT).with_suffix("").as_posix()
                words = word_count(note_body)
                notes[key] = {
                    "title": note_meta.get("title", path.stem),
                    "subtitle": note_meta.get("subtitle", ""),
                    "date": note_meta.get("date-modified") or note_meta.get("date", ""),
                    "topic": topic, "section": folder.group(1), "sectionTitle": title.strip(),
                    "words": words, "minutes": minutes(words),
                }
                keys.append(key)
            sections.append({"folder": folder.group(1), "title": title.strip(),
                             "planned": ".planned" in attrs, "notes": keys})
        tracks = meta.get("path") == "tracks"
        topics[topic] = {"title": meta.get("title", topic), "tracks": tracks, "sections": sections}

    # Lesson numbers, previous/next: within each track for topics read as tracks, else across the topic.
    for topic, info in topics.items():
        groups = [s["notes"] for s in info["sections"]] if info["tracks"] else \
                 [[k for s in info["sections"] for k in s["notes"]]]
        for group in groups:
            for i, key in enumerate(group):
                notes[key].update(lesson=i + 1, of=len(group),
                                  next=group[i + 1] if i + 1 < len(group) else None)
        all_keys = [k for s in info["sections"] for k in s["notes"]]
        info["count"] = len(all_keys)
        info["minutes"] = sum(notes[k]["minutes"] for k in all_keys)
        for s in info["sections"]:
            s["count"] = len(s["notes"])
            s["minutes"] = sum(notes[k]["minutes"] for k in s["notes"])
    return {"topics": topics, "notes": notes}


def main() -> None:
    data = build()
    out = ROOT / "_carnet"
    out.mkdir(exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    (out / "notes.json").write_text(text, encoding="utf-8")
    inline = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    (out / "notes-data.html").write_text(
        f'<script id="carnet-data" type="application/json">{inline}</script>\n', encoding="utf-8")


if __name__ == "__main__":
    main()
