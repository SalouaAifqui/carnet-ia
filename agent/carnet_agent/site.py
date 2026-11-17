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


# --- The site map: topics → sections → pages --------------------------------------
#
# Sections are declared on each topic page (topic/index.qmd) as headings like
#     ## Foundation models {.group-title data-folder="foundation-models"}
# followed by a `::: {.group-meta}` description. Empty sections exist too: that is
# why we read the topic pages instead of looking at folders on disk.

SECTION_RE = re.compile(r'^## (.+?) \{([^}]*\.group-title[^}]*)\}\s*$', re.M)


@dataclass
class Section:
    topic: str
    folder: str
    title: str
    description: str


def list_sections(root: Path) -> list[Section]:
    sections = []
    for topic in TOPICS:
        index = root / topic / "index.qmd"
        _, body = split_front_matter(index.read_text()) if index.exists() else ({}, "")
        found = list(SECTION_RE.finditer(body))
        for i, match in enumerate(found):
            attrs = match.group(2)
            folder = re.search(r'data-folder="([^"]+)"', attrs)
            chunk = body[match.end(): found[i + 1].start() if i + 1 < len(found) else len(body)]
            meta = re.search(r"::: \{\.(?:group-meta|empty-state)\}\n(.*?)\n:::", chunk, re.S)
            description = re.sub(r"\*\*|\[|\]\([^)]*\)", "", meta.group(1)).strip() if meta else ""
            sections.append(Section(topic, folder.group(1) if folder else slugify(match.group(1)),
                                    match.group(1).strip(), description))
        # A folder with pages but no declared section still counts.
        declared = {s.folder for s in sections if s.topic == topic}
        if (root / topic).exists():
            for d in sorted(p for p in (root / topic).iterdir() if p.is_dir() and p.name not in declared):
                sections.append(Section(topic, d.name, d.name.replace("-", " ").capitalize(), ""))
    return sections


def topic_description(root: Path, topic: str) -> str:
    index = root / topic / "index.qmd"
    if not index.exists():
        return ""
    hero = re.search(r"::: \{\.topic-hero\}.*?\{\.topic-h1\}\n\n(.*?)\n:::", index.read_text(), re.S)
    return hero.group(1).strip() if hero else ""


def describe_site(root: Path) -> str:
    """The site map given to the `categorize` LLM: every topic, every section
    (including empty ones) with what it is for, and the pages it already has."""
    pages = list_pages(root)
    sections = list_sections(root)
    lines = []
    for topic, (label, _) in TOPICS.items():
        lines.append(f"# Topic `{topic}` ({label}): {topic_description(root, topic)}")
        topic_sections = [s for s in sections if s.topic == topic]
        if not topic_sections:
            lines.append("  (no sections yet)")
        for sec in topic_sections:
            lines.append(f"  ## Section `{sec.folder}` ({sec.title}): {sec.description or 'no description'}")
            in_section = [p for p in pages if p.topic == topic and p.folder == sec.folder]
            for p in in_section:
                lines.append(f"    - page {p.path} | {p.title}: {p.subtitle}")
                _, body = split_front_matter((root / p.path).read_text())
                parts = [t for t, _ in split_parts(split_sources(body)[0])[1]]
                if parts:
                    lines.append("        parts: " + " · ".join(parts))
            if not in_section:
                lines.append("    (empty)")
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


def related_pages(root: Path, topic: str, folder: str, exclude: str = "", limit: int = 2,
                  chars: int = 2500) -> str:
    """Excerpts of other pages of the same section, so the writer can reuse their examples."""
    parts = []
    for page in [p for p in list_pages(root) if p.topic == topic and p.folder == folder and p.path != exclude][:limit]:
        _, body = split_front_matter((root / page.path).read_text())
        parts.append(f"<page path='{page.path}' title='{page.title}'>\n{split_sources(body)[0][:chars]}\n</page>")
    return "\n".join(parts)


VISUALS = {
    "diagram": "```{mermaid}", "table": "|---", "concept cards": "{.concepts}",
    "example box": "{.example}", "comparison": "{.compare}", "steps": "{.steps}", "callout": "{.callout-",
}


# --- Checks done by code in the review step -------------------------------------

def _blocks_balanced(body: str) -> bool:
    """Every '::: {…}' opening has its ':::' closing (code blocks are ignored)."""
    depth, in_code = 0, False
    for line in body.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and re.match(r"^:::+\s*\{", line):
            depth += 1
        elif not in_code and re.match(r"^:::+\s*$", line):
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _main_parts(body: str) -> list[str]:
    """The '##' headings of the page, without Remember, Watch out, Sources and callout titles."""
    parts, previous, in_code = [], "", False
    for line in body.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and line.startswith("## ") and not previous.startswith("::: {.callout"):
            title = re.sub(r"\s*\{[^}]*\}\s*$", "", line[3:]).strip()
            if title.lower() not in ("remember", "watch out", "sources", "key ideas"):
                parts.append(title)
        if line.strip():
            previous = line
    return parts


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
    if re.search(r"^```\{(?!mermaid\})", body, re.M):
        errors.append("A code block uses ```{…} (other than mermaid): Quarto would try to execute it.")
    if not _blocks_balanced(body):
        errors.append("A ::: block is opened and not closed (or closed twice): the page would render badly.")
    if len(body.split()) < 120:
        errors.append("The page is too short to be useful.")
    main_parts = _main_parts(body)
    if len(main_parts) > 4:
        errors.append(f"Too many main parts ({len(main_parts)}: {', '.join(main_parts)}). Group them into at most "
                      "4 '##' parts and use '###' inside.")
    kinds = [name for name, marker in VISUALS.items() if marker in body]
    if len(kinds) < 3:
        errors.append(f"Not visual enough: only {', '.join(kinds) or 'no'} visual elements. Use at least three "
                      "kinds (diagram, table, concept cards, example box, comparison, steps, callout).")
    if "{.example}" not in body:
        errors.append("No concrete example: put at least one example in a ::: {.example} box.")
    return errors


# --- Registering a new folder in the site's menus --------------------------------

def ensure_listed(root: Path, topic: str, folder: str, folder_title: str, description: str = "") -> None:
    """Make sure topic/<folder> appears on the topic page and in the sidebar."""
    _add_listing_to_topic_page(root / topic / "index.qmd", folder, folder_title, description)
    _add_folder_to_sidebar(root / "_quarto.yml", topic, folder, folder_title)


def _add_listing_to_topic_page(index_file: Path, folder: str, folder_title: str, description: str = "") -> None:
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
    sections = list(SECTION_RE.finditer(body))
    for i, section in enumerate(sections):
        declared = re.search(r'data-folder="([^"]+)"', section.group(2))
        if (declared and declared.group(1) == folder) or \
                (not declared and slugify(section.group(1)) in (folder, slugify(folder_title))):
            end = sections[i + 1].start() if i + 1 < len(sections) else len(body)
            chunk = body[section.end():end]
            new_chunk = re.sub(r"::: \{\.empty-state\}.*?\n:::", placeholder, chunk, count=1, flags=re.S)
            if new_chunk == chunk:
                new_chunk = chunk.rstrip() + "\n\n" + placeholder + "\n\n"
            heading = body[section.start():section.end()].replace(" .planned", "")   # no longer "coming soon"
            body = body[:section.start()] + heading + new_chunk + body[end:]
            break
    else:
        # 2. Otherwise drop a lone "coming soon" box (topics with no sections yet) and add a section.
        if not sections:
            body = re.sub(r"::: \{\.empty-state\}.*?\n:::\n?", "", body, flags=re.S)
        meta = f"::: {{.group-meta}}\n{description}\n:::\n\n" if description else ""
        body = body.rstrip() + (f'\n\n## {folder_title} {{.group-title data-folder="{folder}"}}\n\n'
                                f"{meta}{placeholder}\n")
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


# --- Reading and rebuilding a page made of blocks ------------------------------------
#
# A page body is: pills, summary (.tldr), concept cards (.concepts), then '##' parts, with the
# "Remember" callout at the end. The editor rewrites summary, cards and Remember; parts are
# inserted or replaced by code, so existing content is never silently dropped.

def find_block(body: str, opener: str) -> tuple[int, int] | None:
    """Character span of the ':::' block whose first line starts with `opener` (nested ::: counted)."""
    lines = body.split("\n")
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    for i, line in enumerate(lines):
        if line.startswith(opener):
            depth = 0
            for j in range(i, len(lines)):
                if re.match(r"^:::+\s*\{", lines[j]):
                    depth += 1
                elif re.match(r"^:::+\s*$", lines[j]):
                    depth -= 1
                    if depth == 0:
                        return offsets[i], offsets[j] + len(lines[j])
            return None
    return None


def remember_block(body: str) -> tuple[int, int] | None:
    match = re.search(r"^::: \{\.callout-tip\}\n## Remember\n", body, re.M)
    if not match:
        return None
    span = find_block(body[match.start():], "::: {.callout-tip}")
    return (match.start(), match.start() + span[1]) if span else None


def split_parts(body: str) -> tuple[str, list[tuple[str, str]], str]:
    """(before the first part, [(title, full text of the part)], after the parts).
    'After' starts at the Remember callout, if any."""
    remember = remember_block(body)
    tail = body[remember[0]:] if remember else ""
    main = body[:remember[0]] if remember else body
    starts, in_code, previous, pos = [], False, "", 0
    for line in main.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and line.startswith("## ") and not previous.startswith("::: {.callout"):
            starts.append(pos)
        if line.strip():
            previous = line
        pos += len(line) + 1
    if not starts:
        return main.rstrip(), [], tail
    head = main[:starts[0]].rstrip()
    parts = []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(main)
        text = main[start:end].rstrip()
        title = re.sub(r"\s*\{[^}]*\}\s*$", "", text.split("\n", 1)[0][3:]).strip()
        parts.append((title, text))
    return head, parts, tail


def render_synthesis_blocks(tldr: str, concepts: list, remember: list[str]) -> tuple[str, str, str]:
    """Markdown for the summary, the concept cards and the Remember callout."""
    tldr_md = f"::: {{.tldr}}\n{tldr.strip()}\n:::"
    cards = "\n".join(f"::: {{.concept}}\n`{c.name}`\n\n{c.text.strip()}\n:::" for c in concepts)
    concepts_md = f"::: {{.concepts}}\n{cards}\n:::"
    remember_md = "::: {.callout-tip}\n## Remember\n" + "\n".join(f"- {r.strip()}" for r in remember) + "\n:::"
    return tldr_md, concepts_md, remember_md
