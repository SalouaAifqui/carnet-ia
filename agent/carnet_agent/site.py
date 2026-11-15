"""Plain-code operations on the Carnet IA site. No LLM in this file.

Reading pages, building the list of existing pages, rendering the Sources section,
and registering a new folder in the menus: all of this must happen the same way
every time, so it is ordinary Python, not a decision for a model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import SELF_URLS, TOPICS
from .state import Finding, Source

SOURCES_HEADING = "## Sources {.sources}"


# --- Small helpers --------------------------------------------------------------

def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", text)[:60] or "page"


def split_front_matter(text: str) -> tuple[dict, str]:
    """'---\\nyaml\\n---\\nbody' -> (dict, body)."""
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not match:
        return {}, text
    return yaml.safe_load(match.group(1)) or {}, match.group(2)


def join_front_matter(front_matter: dict, body: str) -> str:
    fm = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True, width=1000).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


# --- The list of existing pages (the agent's "semantic memory" of the site) -----

@dataclass
class PageInfo:
    path: str          # e.g. "agents/langgraph/02-langgraph-components.qmd"
    topic: str
    folder: str
    title: str
    subtitle: str


def list_pages(root: Path) -> list[PageInfo]:
    """Every note of the site. Notes always live in topic/<folder>/<page>.qmd."""
    pages = []
    for topic in TOPICS:
        for file in sorted((root / topic).glob("*/*.qmd")):
            fm, _ = split_front_matter(file.read_text())
            pages.append(PageInfo(
                path=str(file.relative_to(root)), topic=topic, folder=file.parent.name,
                title=str(fm.get("title", file.stem)), subtitle=str(fm.get("subtitle", "")),
            ))
    return pages


def list_folders(root: Path) -> dict[str, list[str]]:
    return {t: sorted(p.name for p in (root / t).iterdir() if p.is_dir()) for t in TOPICS}


def describe_site(root: Path) -> str:
    """A compact text version of the site, given to the `categorize` LLM."""
    lines = []
    folders = list_folders(root)
    pages = list_pages(root)
    for topic, (label, _) in TOPICS.items():
        lines.append(f"# Topic `{topic}` ({label})")
        if not folders[topic]:
            lines.append("  (no folders yet)")
        for folder in folders[topic]:
            lines.append(f"  ## Folder `{folder}`")
            for p in (p for p in pages if p.topic == topic and p.folder == folder):
                lines.append(f"    - {p.path} | {p.title}: {p.subtitle}")
    return "\n".join(lines)


# --- Sources ------------------------------------------------------------------

def is_self(url: str) -> bool:
    """True for pages of this website or its repository: the site never cites itself."""
    return any(s.lower() in url.lower() for s in SELF_URLS)


def split_sources(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Separate the Sources section from the rest. Returns (body, [(title, url)])."""
    index = body.find("## Sources")
    if index == -1:
        return body.rstrip(), []
    sources_md = body[index:]
    links = re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", sources_md)
    links += [(url, url) for url in re.findall(r"<(https?://[^>\s]+)>", sources_md)]
    return body[:index].rstrip(), links


def merge_sources(existing: list[tuple[str, str]], new: list[Source]) -> list[tuple[str, str]]:
    """Existing sources first, then new ones. Each URL appears once."""
    merged, seen = [], set()
    for title, url in existing + [(s.title, s.url) for s in new]:
        key = url.rstrip("/")
        if key not in seen and not is_self(url):
            seen.add(key)
            merged.append((title, url))
    return merged


def render_sources(sources: list[tuple[str, str]]) -> str:
    items = "\n".join(f"- [{title}]({url})" for title, url in sources)
    return f"{SOURCES_HEADING}\n\n{items}\n"


def topic_pills(topic: str, folder_title: str) -> str:
    label, css = TOPICS[topic]
    return f"::: {{.lesson-meta}}\n[{label}]{{.pill .{css}}} [{folder_title}]{{.pill .muted}}\n:::"


# --- Checks done by code in the review step -------------------------------------

def check_page(text: str, findings: list[Finding]) -> list[str]:
    """Mechanical checks. Each returned string is a problem the writer must fix."""
    errors = []
    fm, body = split_front_matter(text)
    if not fm.get("title"):
        errors.append("The page has no title.")
    if SOURCES_HEADING not in body:
        errors.append("The Sources section is missing.")
    _, links = split_sources(body)
    listed = {url.rstrip("/") for _, url in links}
    for f in findings:
        if f.source_url.rstrip("/") not in listed:
            errors.append(f"Finding from {f.source_url} is not listed in Sources.")
    if body.count("```") % 2:
        errors.append("A code block is not closed (odd number of ```).")
    if len(body.split()) < 120:
        errors.append("The page is too short to be useful.")
    return errors


# --- Registering a new folder in the site's menus --------------------------------

def ensure_listed(root: Path, topic: str, folder: str, folder_title: str) -> None:
    """Make sure topic/<folder> appears on the topic page and in the sidebar."""
    _add_listing_to_topic_page(root / topic / "index.qmd", folder, folder_title)
    _add_folder_to_sidebar(root / "_quarto.yml", topic, folder, folder_title)


def _add_listing_to_topic_page(index_file: Path, folder: str, folder_title: str) -> None:
    fm, body = split_front_matter(index_file.read_text())
    listings = fm.get("listing") or []
    if isinstance(listings, dict):
        listings = [listings]
    if any(lst.get("id") == folder for lst in listings):
        return
    listings.append({"id": folder, "contents": f"{folder}/*.qmd", "type": "grid",
                     "grid-columns": 2, "sort": "date desc", "fields": ["title", "subtitle"]})
    fm["listing"] = listings

    placeholder = f"::: {{#{folder}}}\n:::"
    # 1. A section with this name already exists (e.g. "Foundation models"): replace its empty state.
    sections = list(re.finditer(r"^## (.+?) \{\.group-title\}\s*$", body, re.M))
    for i, section in enumerate(sections):
        if slugify(section.group(1)) in (folder, slugify(folder_title)):
            end = sections[i + 1].start() if i + 1 < len(sections) else len(body)
            chunk = body[section.end():end]
            new_chunk = re.sub(r"::: \{\.empty-state\}.*?\n:::", placeholder, chunk, count=1, flags=re.S)
            if new_chunk == chunk:
                new_chunk = chunk.rstrip() + "\n\n" + placeholder + "\n\n"
            body = body[:section.end()] + new_chunk + body[end:]
            break
    else:
        # 2. Otherwise drop a lone "coming soon" box (topics with no sections yet) and add a section.
        if not sections:
            body = re.sub(r"::: \{\.empty-state\}.*?\n:::\n?", "", body, flags=re.S)
        body = body.rstrip() + f"\n\n## {folder_title} {{.group-title}}\n\n{placeholder}\n"
    index_file.write_text(join_front_matter(fm, body))


def _add_folder_to_sidebar(config_file: Path, topic: str, folder: str, folder_title: str) -> None:
    config = yaml.safe_load(config_file.read_text())
    glob = f"{topic}/{folder}/*.qmd"
    for sidebar in config["website"]["sidebar"]:
        if sidebar.get("id") == topic:
            contents = sidebar.setdefault("contents", [])
            if not any(isinstance(c, dict) and c.get("contents") == glob for c in contents):
                contents.append({"section": folder_title, "contents": glob})
                config_file.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True, width=1000))
            return
