"""The Carnet IA agent, one role per step.

    fetch ─▶ librarian ─▶ research ─▶ ⏸ approval ─▶ write_parts ─▶ edit ─▶ finalize ─▶ publish
    (code)    (LLM 1)     (LLM 6,       (you)       (LLM 2 writes each part,   (LLM 4)   (code)    (code:
                           proposals                 LLM 3 checks its details,                    PR + preview)
                           only)                     in parallel)

1. librarian (plan model): reads the source, cut into numbered chunks, and plans WHERE it goes and
   WHICH parts to write, each with its chunk numbers. It writes no content.
6. research (research model): proposes extra facts with their sources. Nothing is added unless
   you approve it (/approve F1 F3, or /approve all).
2. writer (write model): writes ONE part from ITS chunks only.
3. checker (check model): compares the part with its chunks; missing details are added in one
   targeted pass (no full rewrite).
4. editor (edit model): writes the summary, key concepts and "Remember" of the whole page.
   Parts are inserted into an existing page by CODE, so nothing already there is lost.
5. publish: a pull request, with a preview of the page on the website before merging.
"""
from __future__ import annotations

import contextvars
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from . import prompts
from .chunks import chunk_text, fingerprint, numbered, remap
from .config import MAX_QUERIES, RESEARCH, TOPICS
from .core import Services, ask, clean_markdown, feedback_block, text_of, validate_route
from .site import (add_in_practice, check_page, describe_site, ensure_listed, find_block, is_self,
                   join_front_matter, list_pages, render_tool_facts,
                   merge_sources, remember_block, render_sources, render_synthesis_blocks, slugify,
                   split_front_matter, split_parts, split_sources, topic_pills)
from .state import (ArticlePlan, Findings, MissingDetails, Proposal, ResearchPlan, Route, Source,
                    Synthesis, ToolInfo)

STATE_TYPES = [("carnet_agent.state", n) for n in [
    "Route", "ArticlePlan", "SectionPlan", "Proposal", "ToolInfo", "Source", "Synthesis", "ConceptCard",
    "Lesson", "LessonNotes", "PlannedPage", "CoursePlan", "Query", "Finding"]]


class ArticleState(TypedDict, total=False):
    url: str                      # first source
    urls: list[str]               # all sources, read together
    titles: dict                  # url -> page title
    chunks: list[str]             # the sources cut into numbered chunks (not saved at the pause)
    fingerprints: list[str]       # to find the chunks again after the pause
    plan: ArticlePlan             # librarian
    existing_body: str            # current page, when updating
    proposals: list[Proposal]     # research, waiting for approval
    approved: list[str]           # ids of the approved proposals
    human_feedback: str
    parts: dict                   # section index -> markdown
    synthesis: Synthesis
    extra_pages: list[dict]       # a second page planned from the same sources (the tool card of a "mixed" source)
    linked: list[str]             # concept pages that got an "In practice" link to a tool card
    check_errors: list[str]
    page_path: str
    pr_url: str
    preview_url: str


def page_title(text: str, url: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, re.M)
    return match.group(1).strip() if match else url


class ArticleAgent:
    def __init__(self, services: Services):
        self.s = services
        self.style = (Path(__file__).parent.parent / "STYLE.md").read_text()

    # ------------------------------------------------------------------ fetch (code)
    def fetch(self, state: ArticleState):
        """Download every source, cut it into numbered chunks."""
        urls = state.get("urls") or [state["url"]]
        blocks, titles = [], dict(state.get("titles") or {})
        for i, url in enumerate(urls, 1):
            try:
                text = self.s.fetch(url)
            except Exception as error:  # noqa: BLE001 - one broken link must not stop the others
                print(f"Could not read {url} ({error})")
                continue
            titles.setdefault(url, page_title(text, url))
            blocks.append(f"=== Source {i}: {url} ===\n\n{text}")
        if not blocks:
            raise RuntimeError("None of the sources could be read.")
        chunks = chunk_text("\n\n".join(blocks))
        return {"urls": urls, "url": urls[0], "titles": titles, "chunks": chunks,
                "fingerprints": [fingerprint(c) for c in chunks]}

    @staticmethod
    def fetch_from_texts(state: ArticleState, texts: dict) -> dict:
        """Same chunks as `fetch`, from texts already downloaded (course mode)."""
        blocks = [f"=== Source {i}: {url} ===\n\n{text}" for i, (url, text) in enumerate(texts.items(), 1) if text]
        chunks = chunk_text("\n\n".join(blocks))
        return {"chunks": chunks, "fingerprints": [fingerprint(c) for c in chunks]}

    def ensure_chunks(self, state: ArticleState) -> dict:
        """After a pause the chunks are gone: fetch again and map the saved numbers to the new ones."""
        if state.get("chunks"):
            return {}
        fresh = self.fetch(state)
        mapping = remap(state.get("fingerprints") or [], fresh["chunks"])

        def moved(plan: ArticlePlan) -> ArticlePlan:
            plan = plan.model_copy(deep=True)
            for section in plan.sections:
                section.chunks = sorted({mapping[c] for c in section.chunks if c in mapping})
            return plan
        update = {"chunks": fresh["chunks"], "plan": moved(state["plan"])}
        if state.get("extra_pages"):
            update["extra_pages"] = [e | {"plan": moved(e["plan"])} for e in state["extra_pages"]]
        return update

    # ------------------------------------------------------------------ 1. librarian (LLM)
    def librarian(self, state: ArticleState, fixed_route: Route | None = None):
        """Classify the source, plan where it goes and which parts to write. [code] then checks the plan.
        concept → one page. tool → one tool card in the Toolbox. mixed → a vendor-neutral concept
        page + a tool card (planned by a second, focused call)."""
        fixed = prompts.LIBRARIAN_FIXED.format(route=fixed_route.model_dump_json()) if fixed_route else ""
        if fixed_route and fixed_route.topic == "toolbox":
            fixed = prompts.TOOL_CARD + fixed
        plan = ask(self.s.m("plan"), ArticlePlan, [
            SystemMessage(prompts.LIBRARIAN.format(site=describe_site(self.s.root), fixed=fixed)),
            HumanMessage(f"Source chunks:\n\n{numbered(state['chunks'])}" + feedback_block(state)),
        ])
        if fixed_route:
            plan.route = fixed_route
        elif plan.source_kind == "tool" and plan.tool:
            return self.plan_tool_card(state, plan.tool)              # the whole page is a tool card
        checked = validate_route(self.s.root, plan.route)
        plan.route = checked["route"]
        self.check_sections(plan, checked["existing_body"], len(state["chunks"]))
        if plan.route.topic == "toolbox" and plan.tool:               # [code] only real concept pages
            concept_pages = {p.path for p in list_pages(self.s.root) if p.topic != "toolbox"}
            plan.tool.related_pages = [p for p in plan.tool.related_pages if p in concept_pages]
        update = {"plan": plan, "existing_body": checked["existing_body"]}
        if not fixed_route and plan.source_kind == "mixed" and plan.tool:
            update["extra_pages"] = [self.plan_tool_card(state, plan.tool)]
        return update

    def plan_tool_card(self, state: ArticleState, tool: ToolInfo) -> dict:
        """[code] The card's place is fixed (toolbox/tools/<name>.qmd, updated if it exists),
        then [LLM] the librarian plans its four standard parts."""
        path = f"toolbox/tools/{slugify(tool.name)}.qmd"
        exists = (self.s.root / path).exists()
        route = Route(concept=tool.name, reasoning=f"Tool card for {tool.name} ({tool.maker}).",
                      action="update" if exists else "create", topic="toolbox", folder="tools",
                      folder_title="Tools", target_path=path if exists else "", title=tool.name,
                      subtitle=tool.summary)
        card = self.librarian(state, fixed_route=route)
        card["plan"].source_kind = "tool"
        if card["plan"].tool is None:
            card["plan"].tool = tool
        return card

    @staticmethod
    def check_sections(plan: ArticlePlan, existing_body: str, n_chunks: int) -> None:
        """[code] Valid chunk numbers; 'extend' only on parts that exist; every chunk used; ≤ 4 parts."""
        existing = [t for t, _ in split_parts(existing_body)[1] if t.lower() != "key ideas"] if existing_body else []
        for section in plan.sections:
            section.chunks = sorted({c for c in section.chunks if 1 <= c <= n_chunks})
            if section.kind == "extend" and section.existing_heading not in existing:
                match = next((t for t in existing if slugify(t) == slugify(section.existing_heading)), None)
                if match:
                    section.existing_heading = match
                else:
                    section.kind = "new"
            if section.kind == "new" and section.existing_heading not in existing:
                section.existing_heading = ""
        plan.sections = [s for s in plan.sections if s.chunks] or plan.sections[:1]
        new_parts = [s for s in plan.sections if s.kind == "new"]
        while len(existing) + len(new_parts) > 4 and len(plan.sections) > 1:
            extra = new_parts.pop()               # too many parts: fold the last new one into another
            plan.sections.remove(extra)
            target = plan.sections[-1]
            target.chunks = sorted(set(target.chunks) | set(extra.chunks))
            target.covers += f" Also: {extra.covers}"
        used = {c for s in plan.sections for c in s.chunks}
        for c in range(1, n_chunks + 1):           # a chunk no part uses goes to the part of its neighbours
            if c not in used and plan.sections:
                nearest = min(plan.sections, key=lambda s: min(abs(c - x) for x in s.chunks) if s.chunks else 99)
                nearest.chunks = sorted(set(nearest.chunks) | {c})

    # ------------------------------------------------------------------ 6. research (LLM, proposals only)
    def research(self, state: ArticleState, prefix: str = "F"):
        if not RESEARCH:
            return {"proposals": []}
        plan = state["plan"]
        outline = "\n".join(f"- {s.heading}: {s.covers}" for s in plan.sections)
        queries = ask(self.s.m("research"), ResearchPlan, [
            SystemMessage(prompts.RESEARCH_PROPOSE.format(max_queries=MAX_QUERIES)),
            HumanMessage(f"Page: {plan.route.title}\n{plan.summary}\n\nParts:\n{outline}" + feedback_block(state)),
        ]).queries[:MAX_QUERIES]
        results = [r for r in self.s.search([q.query for q in queries]) if not is_self(r["url"])] if queries else []
        if not results:
            return {"proposals": []}
        listing = "\n\n".join(f"[{i}] {r['title']}\nURL: {r['url']}\n{r['content'][:1200]}"
                              for i, r in enumerate(results, 1))
        picked = ask(self.s.m("research"), Findings, [
            SystemMessage(prompts.SELECT),
            HumanMessage(f"Planned page:\n{plan.summary}\n{outline}\n\nSearch results:\n{listing}"),
        ])
        allowed = {r["url"].rstrip("/") for r in results}
        proposals = [Proposal(id=f"{prefix}{i}", fact=f.fact, why=f.why, source_url=f.source_url,
                              source_title=f.source_title)
                     for i, f in enumerate([f for f in picked.findings if f.source_url.rstrip("/") in allowed], 1)]
        return {"proposals": proposals}

    def human_approval(self, state: ArticleState):
        """[code] Nothing: the graph stops BEFORE this step and waits for a person."""
        return {}

    # ------------------------------------------------------------------ 2 + 3. write and check each part
    def write_part(self, state: ArticleState, index: int) -> str:
        if self.s.check_budget:
            self.s.check_budget()
        plan, section = state["plan"], state["plan"].sections[index]
        chunks = numbered(state["chunks"], section.chunks)
        approved = [p for p in state.get("proposals") or [] if p.id in (state.get("approved") or [])]
        existing_part = ""
        if section.kind == "extend":
            existing_part = dict(split_parts(state.get("existing_body", ""))[1]).get(section.existing_heading, "")
        outline = "\n".join(f"- {s.heading}" for s in plan.sections)
        context = [
            f"Page: {plan.route.title} ({plan.route.subtitle})\nAll parts of the page:\n{outline}",
            f"Write the part: {section.heading}\nIt covers: {section.covers}\n"
            f"Example to show: {section.example}\nVisual: {section.visual}",
            f"Source chunks:\n{chunks}",
        ]
        if approved:
            context.append("Approved web findings you may use:\n" +
                           "\n".join(f"- {p.fact} ({p.source_url})" for p in approved))
        if existing_part:
            context.append(f"The existing part:\n<existing>\n{existing_part}\n</existing>")
        system = (prompts.WRITE_SECTION.format(extend=prompts.WRITE_EXTEND if existing_part else "")
                  + f"\n\n<style_guide>\n{self.style}\n</style_guide>")      # same prefix every call: cached
        draft = clean_markdown(text_of(self.s.m("write").invoke([
            SystemMessage(system), HumanMessage("\n\n".join(context) + feedback_block(state))])))
        if not draft.startswith("## "):
            draft = f"## {section.heading}\n\n{draft}"

        # 3. the checker compares the part with ITS chunks only
        missing = ask(self.s.m("check"), MissingDetails, [
            SystemMessage(prompts.CHECK_DETAILS),
            HumanMessage(f"Source chunks:\n{chunks}\n\nWritten part:\n{draft}"),
        ]).missing
        if missing:                              # one targeted pass: add, don't rewrite
            draft = clean_markdown(text_of(self.s.m("write").invoke([
                SystemMessage(prompts.PATCH_SECTION),
                HumanMessage(f"Missing details:\n" + "\n".join(f"- {m}" for m in missing) +
                             f"\n\nSource chunks:\n{chunks}\n\nThe part:\n{draft}")])))
        return draft

    @staticmethod
    def sub(state: ArticleState, extra: dict) -> dict:
        """An extra page shares the sources, approvals and instructions of the run."""
        return dict(state) | extra

    def _write_all(self, state: ArticleState) -> dict:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {i: pool.submit(contextvars.copy_context().run, self.write_part, state, i)
                       for i in range(len(state["plan"].sections))}
            return {str(i): f.result() for i, f in futures.items()}

    def write_parts(self, state: ArticleState):
        """All parts are written and checked in parallel (one thread each), for every page."""
        state = dict(state) | self.ensure_chunks(state)
        update = {"parts": self._write_all(state), "chunks": state["chunks"], "plan": state["plan"]}
        if state.get("extra_pages"):
            update["extra_pages"] = [e | {"parts": self._write_all(self.sub(state, e))} for e in state["extra_pages"]]
        return update

    # ------------------------------------------------------------------ 4. editor (LLM) + merge (code)
    def edit(self, state: ArticleState):
        update = {"synthesis": self._synthesis(state)}
        if state.get("extra_pages"):
            update["extra_pages"] = [e | {"synthesis": self._synthesis(self.sub(state, e))}
                                     for e in state["extra_pages"]]
        return update

    def _synthesis(self, state: ArticleState) -> Synthesis:
        plan = state["plan"]
        openings = "\n\n".join(" ".join(text.split()[:90]) for text in state["parts"].values())
        existing = ""
        if state.get("existing_body"):
            head, parts, _ = split_parts(state["existing_body"])
            existing = ("This updates an existing page. Its current parts are: "
                        + " · ".join(t for t, _ in parts) + ". Its current summary:\n" + head[-1500:])
        return ask(self.s.m("edit"), Synthesis, [
            SystemMessage(prompts.EDITOR.format(existing=existing)),
            HumanMessage(f"Page: {plan.route.title}: {plan.route.subtitle}\n\nOpenings of the new parts:\n{openings}"),
        ])

    def assemble(self, state: ArticleState) -> tuple[Path, str]:
        """[code] Build the page: blocks from the editor, parts inserted at their place, sources."""
        route, plan = state["plan"].route, state["plan"]
        tldr, concepts, remember = render_synthesis_blocks(
            state["synthesis"].tldr, state["synthesis"].concepts, state["synthesis"].remember)
        parts = [state["parts"][str(i)] for i in range(len(plan.sections))]
        approved = [p for p in state.get("proposals") or [] if p.id in (state.get("approved") or [])]
        sources = [Source(title=(state.get("titles") or {}).get(u, u), url=u, role="primary")
                   for u in state.get("urls") or [state["url"]]]
        sources += [Source(title=p.source_title, url=p.source_url, role="complementary") for p in approved]

        if route.action == "update":
            path = self.s.root / route.target_path
            front_matter, old = split_front_matter(path.read_text())
            front_matter["date-modified"] = self.s.today
            old, old_sources = split_sources(old)
            head, existing_parts, tail = split_parts(old)
            body_parts = [text for _, text in existing_parts]
            titles = [t for t, _ in existing_parts]
            blocks = [("::: {.tldr}", tldr), ("::: {.concepts}", concepts)]
            if plan.tool:
                blocks.insert(0, ("::: {.tool-facts}", render_tool_facts(plan.tool)))
            for opener, block in blocks:
                span = find_block(head, opener)               # usually at the top, sometimes in a part
                if span:
                    head = head[:span[0]] + block + head[span[1]:]
                    continue
                k = next((i for i, text in enumerate(body_parts) if find_block(text, opener)), None)
                if k is None:
                    head = head + "\n\n" + block
                else:
                    s, e = find_block(body_parts[k], opener)
                    body_parts[k] = body_parts[k][:s] + block + body_parts[k][e:]
            for section, text in zip(plan.sections, parts):
                if section.kind == "extend" and section.existing_heading in titles:
                    body_parts[titles.index(section.existing_heading)] = text
                elif section.existing_heading in titles:
                    k = titles.index(section.existing_heading) + 1
                    body_parts.insert(k, text)
                    titles.insert(k, section.heading)
                else:
                    body_parts.append(text)
                    titles.append(section.heading)
            span = remember_block(tail)
            tail = tail[:span[0]] + remember + tail[span[1]:] if span else (tail + "\n\n" + remember).strip()
            body = "\n\n".join([head.strip(), *body_parts, tail.strip()])
        else:
            path = self.s.root / route.topic / route.folder / f"{slugify(route.title)}.qmd"
            n = 2
            while path.exists():
                path, n = path.with_name(f"{slugify(route.title)}-{n}.qmd"), n + 1
            categories = [TOPICS[route.topic][0], route.folder_title]
            if plan.tool:                                   # a tool card is tagged with the topics it touches
                categories = [TOPICS[t][0] for t in plan.tool.topics] or ["Toolbox"]
            front_matter = {"title": route.title, "subtitle": route.subtitle, "date": self.s.today,
                            "categories": categories}
            old_sources = []
            facts = [render_tool_facts(plan.tool)] if plan.tool else []
            body = "\n\n".join([topic_pills(route.topic, route.folder_title), *facts, tldr, concepts, *parts, remember])
        page = join_front_matter(front_matter, f"{body}\n\n{render_sources(merge_sources(old_sources, sources))}")
        return path, page

    def finalize(self, state: ArticleState):
        update = self._finalize_one(state)
        pages = [(state, update)]
        if state.get("extra_pages"):
            update["extra_pages"] = []
            for extra in state["extra_pages"]:
                done = self._finalize_one(self.sub(state, extra))
                update["extra_pages"].append(extra | done)
                pages.append((extra, done))
        linked = []
        for page, done in pages:                                  # [code] "In practice" links to tool cards
            tool = page["plan"].tool if page["plan"].route.topic == "toolbox" else None
            if tool:
                linked += add_in_practice(self.s.root, done["page_path"], tool)
        update["linked"] = linked
        return update

    def _finalize_one(self, state: ArticleState) -> dict:
        path, page = self.assemble(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page)
        approved = [p for p in state.get("proposals") or [] if p.id in (state.get("approved") or [])]
        route = state["plan"].route
        if route.action == "create":
            ensure_listed(self.s.root, route.topic, route.folder, route.folder_title, route.section_description)
        return {"page_path": str(path.relative_to(self.s.root)), "check_errors": check_page(page, approved)}

    def publish(self, state: ArticleState):
        if self.s.publish is None:
            return {"pr_url": ""}
        return self.s.publish(state)

    # ------------------------------------------------------------------ the graph
    def build(self, pause_for_approval: bool = True):
        g = StateGraph(ArticleState)
        for name in ["fetch", "librarian", "research", "human_approval", "write_parts", "edit", "finalize", "publish"]:
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "fetch")
        for a, b in [("fetch", "librarian"), ("librarian", "research"), ("research", "human_approval"),
                     ("human_approval", "write_parts"), ("write_parts", "edit"), ("edit", "finalize"),
                     ("finalize", "publish"), ("publish", END)]:
            g.add_edge(a, b)
        if not pause_for_approval:
            return g.compile()
        memory = MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES))
        return g.compile(checkpointer=memory, interrupt_before=["human_approval"])


# ------------------------------------------------------------------ what the human sees

def describe_plan(state: dict) -> str:
    plan = state["plan"]
    route = plan.route
    target = route.target_path if route.action == "update" else f"{route.topic}/{route.folder}/{slugify(route.title)}.qmd"
    lines = [
        f"## 📝 Plan: {route.title}",
        f"*{route.subtitle}*",
        "",
        "**Sources:** " + " · ".join(state.get("urls") or [state["url"]]),
        f"**Decision:** {route.action} `{target}` in **{TOPICS[route.topic][0]}** › {route.folder_title}",
        f"> {route.reasoning}",
        "",
    ]
    if state.get("human_feedback"):
        lines += [f"📝 **Your notes:** {state['human_feedback']}", ""]
    if route.new_section:
        lines += [f"⚠️ **New section proposed:** {route.folder_title}: {route.section_description}", ""]
    kind = {"concept": "🧠 a concept", "tool": "🧰 a tool (tool card in the Toolbox)",
            "mixed": "🧠 + 🧰 concepts taught through a product: a vendor-neutral concept page **and** a tool card"}
    lines += [f"**Source type:** {kind[plan.source_kind]}", ""]
    if plan.tool and route.topic == "toolbox":
        t = plan.tool
        lines += [f"**Tool:** {t.name} by {t.maker} · open source: {t.open_source} · topics: "
                  + ", ".join(TOPICS[x][0] for x in t.topics),
                  f"**Implements:** {', '.join(t.implements)}",
                  "**Linked from:** " + (", ".join(f"`{p}`" for p in t.related_pages) or "(no concept page yet)"), ""]
    lines += [plan.summary, "", "### Parts"]
    for s in plan.sections:
        where = (f"extends **{s.existing_heading}**" if s.kind == "extend"
                 else f"new part{f', after {s.existing_heading}' if s.existing_heading else ''}")
        lines += [f"- **{s.heading}** ({where}, {len(s.chunks)} source chunk(s))",
                  f"  - {s.covers}", f"  - 💡 {s.example}", f"  - 🎨 {s.visual}"]
    for extra in state.get("extra_pages") or []:
        lines += ["", "---", "", describe_plan({**state, **extra, "extra_pages": [], "proposals": []})]
    proposals = state.get("proposals") or []
    if proposals:
        lines += ["", "### Extra facts found on the web (added only if you approve them)"]
        lines += [f"- **{p.id}** {p.fact} ([{p.source_title}]({p.source_url}))" for p in proposals]
    return "\n".join(lines)


def describe_run(state: dict) -> str:
    route = state["plan"].route
    approved = [p for p in state.get("proposals") or [] if p.id in (state.get("approved") or [])]
    lines = [
        "**Sources:** " + " · ".join(state.get("urls") or [state["url"]]),
        f"**Decision:** {route.action} `{state.get('page_path')}` in **{TOPICS[route.topic][0]}** › {route.folder_title}",
        "",
        "### Parts written",
        *[f"- {s.heading} ({'extended' if s.kind == 'extend' else 'new'})" for s in state["plan"].sections],
        "",
        "### Web facts added (approved)",
        *([f"- {p.fact} — [{p.source_title}]({p.source_url})" for p in approved] or ["- (none)"]),
    ]
    for extra in state.get("extra_pages") or []:
        r = extra["plan"].route
        lines += ["", f"**Also:** {r.action} `{extra.get('page_path')}` in **{TOPICS[r.topic][0]}** › {r.folder_title}"]
        lines += [f"- ⚠️ {e}" for e in extra.get("check_errors") or []]
    if state.get("linked"):
        lines += ["", "**\"In practice\" links added to:** " + ", ".join(f"`{p}`" for p in state["linked"])]
    if state.get("check_errors"):
        lines += ["", "### ⚠️ To check", *[f"- {e}" for e in state["check_errors"]]]
    if state.get("cost") is not None:
        lines += ["", f"**Cost of this run:** ${state['cost']:.3f}"]
    return "\n".join(lines)
