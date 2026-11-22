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

from .config import SECTION_DIRS, SELF_URLS, TOPICS
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


def section_dir(topic: str, folder: str) -> str:
    """The folder where the notes of a section live."""
    return SECTION_DIRS.get((topic, folder), f"{topic}/{folder}")


def owner_of(topic: str, folder: str) -> tuple[str, str]:
    """The (topic, section) that the notes of the folder <topic>/<folder> belong to."""
    return next((key for key, where in SECTION_DIRS.items() if where == f"{topic}/{folder}"), (topic, folder))


def list_pages(root: Path) -> list[PageInfo]:
    """Every note of the site. Notes always live in topic/<folder>/<page>.qmd."""
    pages = []
    for topic in TOPICS:
        for file in sorted((root / topic).glob("*/*.qmd")):
            fm, _ = split_front_matter(file.read_text())
            owner, folder = owner_of(topic, file.parent.name)
            pages.append(PageInfo(
                path=str(file.relative_to(root)), topic=owner, folder=folder,
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
            for d in sorted(p for p in (root / topic).iterdir() if p.is_dir() and p.name not in declared
                            and owner_of(topic, p.name) == (topic, p.name)):
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
    "margin note": "{.column-margin", "code steps": "{.code-step",
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
    if re.search(r"(?m)^#{2,3} Watch out[ \t]*$", _without_callout_titles(body)):
        errors.append("A 'Watch out' heading on its own: put the warning in a ::: {.column-margin .watch} note "
                      "(or a callout-warning inside its section).")
    long_code = _long_code_outside_steps(body)
    if long_code:
        errors.append(f"{long_code} code block(s) over 12 lines outside a ::: {{.code-step title=\"…\"}} block.")
    return errors


def _without_callout_titles(body: str) -> str:
    """The body without the '## Title' line that opens a callout (it is the callout's title, not a section)."""
    return re.sub(r"(?m)^(::: \{\.callout[^}]*\})\n## [^\n]*", r"\1", body)


def _long_code_outside_steps(body: str) -> int:
    count, in_step = 0, False
    lines, i = body.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("::: {.code-step"):
            in_step = True
        elif in_step and re.match(r"^:::\s*$", line):
            in_step = False
        elif line.startswith("```") and not line.startswith("```{mermaid"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            if j - i - 1 > 12 and not in_step:
                count += 1
            i = j
        elif line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            i = j
        i += 1
    return count


# --- Registering a new folder in the site's menus --------------------------------

def ensure_listed(root: Path, topic: str, folder: str, folder_title: str, description: str = "") -> None:
    """Make sure topic/<folder> appears on the topic page and in the sidebar."""
    if (topic, folder) in SECTION_DIRS:
        return                                  # declared by hand, with its folder
    _add_listing_to_topic_page(root / topic / "index.qmd", folder, folder_title, description)
    _add_folder_to_sidebar(root / "_quarto.yml", topic, folder, folder_title)


def _add_listing_to_topic_page(index_file: Path, folder: str, folder_title: str, description: str = "") -> None:
    fm, body = split_front_matter(index_file.read_text())
    listings = fm.get("listing") or []
    if isinstance(listings, dict):
        listings = [listings]
    if any(lst.get("id") == folder for lst in listings):
        return
    # a numbered reading path (see _templates/path.ejs), in the `order` of the notes
    listing = {"id": folder, "contents": f"{folder}/*.qmd", "template": "../_templates/path.ejs",
               "sort": "order", "fields": ["title", "subtitle", "image"]}
    if index_file.parent.name == "toolbox":            # the catalogue: tags shown and filterable by topic
        listing = {"id": folder, "contents": f"{folder}/*.qmd", "type": "grid", "grid-columns": 3, "sort": "title",
                   "fields": ["image", "title", "subtitle", "categories"], "categories": True}
    listings.append(listing)
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
# A page body is: synthesis visual (.synthesis), In 30 seconds (.in30, formerly .tldr), concept
# cards (.concepts), then '##' parts, then the "Remember" callout.
# The editor rewrites In 30 seconds, cards and Remember; parts are inserted or replaced
# by code, so existing content is never silently dropped.

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


def render_synthesis_blocks(synthesis, visual: str | None = None) -> dict[str, str]:
    """Markdown for the blocks the editor writes, by name, in page order:
    synthesis (the visual and its caption), in30, concepts, remember."""
    blocks = {}
    if visual:
        caption = (synthesis.visual_caption or "").strip().replace("\n", " ")
        blocks["synthesis"] = f"::: {{.synthesis}}\n![{caption}]({visual})\n:::"
    blocks["in30"] = "::: {.in30}\n" + "\n".join(f"- {b.strip()}" for b in synthesis.in_30_seconds) + "\n:::"
    cards = "\n".join(f"::: {{.concept}}\n`{c.name}`\n\n{c.text.strip()}\n:::" for c in synthesis.concepts)
    blocks["concepts"] = f"::: {{.concepts}}\n{cards}\n:::"
    blocks["remember"] = ("::: {.callout-tip}\n## Remember\n"
                          + "\n".join(f"- {r.strip()}" for r in synthesis.remember) + "\n:::")
    return blocks


# --- Toolbox: identity card of a tool, and links from concept pages ---------------------

def render_tool_facts(tool) -> str:
    """[code] The fact sheet at the top of a tool card, always in the same format."""
    rows = [("Made by", tool.maker),
            ("Open source", {"yes": "Yes", "no": "No", "partly": "Partly", "unknown": "Not stated"}[tool.open_source]
             + (f" ({tool.licence})" if tool.licence else "")),
            ("Topics", ", ".join(TOPICS[t][0] for t in tool.topics)),
            ("Implements", ", ".join(tool.implements))]
    if tool.website:
        rows.append(("Documentation", f"<{tool.website}>"))
    table = "\n".join(f"| **{k}** | {v} |" for k, v in rows)
    return f"::: {{.tool-facts}}\n| | |\n|---|---|\n{table}\n:::"


IN_PRACTICE = "::: {.callout-note .in-practice}"


def add_in_practice(root: Path, tool_page: str, tool) -> list[str]:
    """[code] Add (or complete) an "In practice: tools" box on each concept page the tool puts into
    practice, linking to its card. Returns the pages that changed."""
    import os
    changed = []
    for page in tool.related_pages:
        path = root / page
        if not path.exists():
            continue
        front_matter, body = split_front_matter(path.read_text())
        body, sources = split_sources(body)
        link = os.path.relpath(root / tool_page, path.parent)
        line = f"- [{tool.name}]({link}) ({tool.maker}): {tool.summary}"
        span = find_block(body, IN_PRACTICE)
        if span:
            block = body[span[0]:span[1]]
            if f"]({link})" in block:
                continue
            block = block[:block.rfind("\n:::")] + f"\n{line}\n:::"
            body = body[:span[0]] + block + body[span[1]:]
        else:
            block = f"{IN_PRACTICE}\n## In practice: tools\n{line}\n:::"
            remember = remember_block(body)
            body = (body[:remember[0]] + block + "\n\n" + body[remember[0]:]) if remember else f"{body.rstrip()}\n\n{block}"
        path.write_text(join_front_matter(front_matter, f"{body.rstrip()}\n\n{render_sources(sources)}"))
        changed.append(page)
    return changed
