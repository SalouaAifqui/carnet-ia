"""The Carnet IA agent: a LangGraph graph that turns a URL into a page proposal.

    fetch → read → categorize → find_gaps ─┬→ search → select → write → review ─┬→ finalize → publish
                                           └──────────(no gaps)───────↑          │
                                                                      ├── write ◄┤ (text issues)
                                                research_critique → search ◄─────┘ (missing topics)

Legend used in the comments below:
    [code] plain Python: always runs, no decision
    [LLM]  a model call that returns structured data or text
    [tool] the LLM itself decides to call it
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from . import prompts
from .config import MAX_QUERIES, MAX_REVISIONS, MAX_TOOL_CALLS, TOPICS
from .site import (check_page, describe_site, ensure_listed, join_front_matter, list_pages,
                   merge_sources, render_sources, slugify, split_front_matter, split_sources,
                   topic_pills)
from .state import AgentState, Findings, ResearchPlan, Review, Route, Source, SourceNotes


@dataclass
class Services:
    """What the agent needs from the outside world.

    Passing these in (instead of creating them inside the nodes) lets the tests swap
    real models and real web calls for fakes.
    """
    root: Path                                   # the website repository
    model: object                                # chat model for read / categorize / write
    review_model: object                         # chat model for review
    fetch: Callable[[str], str]                  # url -> page text
    search: Callable[[list[str]], list[dict]]    # queries -> results
    tools: list = field(default_factory=list)    # tools the LLM may call in write / review
    publish: Callable[[AgentState], str] | None = None
    today: str = field(default_factory=lambda: dt.date.today().isoformat())


def text_of(message) -> str:
    """The text of a model reply, whatever format the provider uses."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content if isinstance(block, dict))


def run_with_tools(model, tools, messages, max_calls=MAX_TOOL_CALLS):
    """A small ReAct loop: the model may call tools until it gives a final answer.

    It's the same loop as `take_action` in the LangGraph course, written out in full.
    """
    if not tools:
        reply = model.invoke(messages)
        return reply, messages + [reply]
    by_name = {t.name: t for t in tools}
    llm = model.bind_tools(tools)
    for _ in range(max_calls):
        reply = llm.invoke(messages)
        messages = messages + [reply]
        if not reply.tool_calls:
            return reply, messages
        for call in reply.tool_calls:                               # [tool] chosen by the LLM
            tool = by_name.get(call["name"])
            result = tool.invoke(call["args"]) if tool else f"Unknown tool {call['name']}"
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"], name=call["name"]))
    reply = model.invoke(messages + [HumanMessage("Stop using tools and give your final answer now.")])
    return reply, messages + [reply]


class CarnetAgent:
    def __init__(self, services: Services):
        self.s = services
        self.style = (Path(__file__).parent.parent / "STYLE.md").read_text()

    # ---------------------------------------------------------------- 1. fetch
    def fetch(self, state: AgentState):
        """[code] Download the page and keep its readable text."""
        return {"raw_text": self.s.fetch(state["url"]), "revision_number": 0}

    # ---------------------------------------------------------------- 2. read
    def read(self, state: AgentState):
        """[LLM] Turn the raw page into structured notes."""
        notes = self.s.model.with_structured_output(SourceNotes).invoke([
            SystemMessage(prompts.READ),
            HumanMessage(f"Source URL: {state['url']}\n\n{state['raw_text']}"),
        ])
        primary = Source(title=notes.title, url=state["url"], role="primary")
        return {"notes": notes, "sources": [primary]}

    # ---------------------------------------------------------------- 3. categorize
    def categorize(self, state: AgentState):
        """[code] describe the site, [LLM] decide update/create, [code] validate the decision."""
        route = self.s.model.with_structured_output(Route).invoke([
            SystemMessage(prompts.CATEGORIZE.format(site=describe_site(self.s.root))),
            HumanMessage(state["notes"].model_dump_json(indent=2)),
        ])
        # Never trust a path blindly: an "update" must point to a page that exists.
        existing = {p.path: p for p in list_pages(self.s.root)}
        if route.action == "update" and route.target_path not in existing:
            route.action, route.target_path = "create", ""
        route.folder = slugify(route.folder)

        update = {"route": route, "existing_body": ""}
        if route.action == "update":
            page = existing[route.target_path]
            route.topic, route.folder = page.topic, page.folder
            _, body = split_front_matter((self.s.root / page.path).read_text())
            update["existing_body"] = split_sources(body)[0]
        return update

    # ---------------------------------------------------------------- 4. research
    def find_gaps(self, state: AgentState):
        """[LLM] What would a learner miss? Which searches would fill it?"""
        existing = ""
        if state.get("existing_body"):
            existing = ("\nThe page being updated already explains the following; "
                        f"do not search for it again:\n{state['existing_body'][:6000]}\n")
        plan = self.s.model.with_structured_output(ResearchPlan).invoke([
            SystemMessage(prompts.FIND_GAPS.format(existing=existing, max_queries=MAX_QUERIES)),
            HumanMessage(state["notes"].model_dump_json(indent=2)),
        ])
        return {"gaps": plan.gaps, "queries": plan.queries[:MAX_QUERIES]}

    def research_critique(self, state: AgentState):
        """[LLM] The reviewer found missing topics: plan targeted searches."""
        plan = self.s.model.with_structured_output(ResearchPlan).invoke([
            SystemMessage(prompts.RESEARCH_CRITIQUE.format(max_queries=MAX_QUERIES)),
            HumanMessage("\n".join(state["review"].missing_topics)),
        ])
        return {"queries": plan.queries[:MAX_QUERIES]}

    def search(self, state: AgentState):
        """[code] Run the planned searches."""
        return {"search_results": self.s.search([q.query for q in state["queries"]])}

    def select(self, state: AgentState):
        """[LLM] keep what matters, [code] drop anything whose URL wasn't in the results."""
        results = state.get("search_results") or []
        if not results:
            return {"findings": []}
        listing = "\n\n".join(f"[{i}] {r['title']}\nURL: {r['url']}\n{r['content'][:1500]}"
                              for i, r in enumerate(results, 1))
        picked = self.s.model.with_structured_output(Findings).invoke([
            SystemMessage(prompts.SELECT),
            HumanMessage(f"Notes:\n{state['notes'].model_dump_json()}\n\nSearch results:\n{listing}"),
        ])
        allowed = {r["url"].rstrip("/") for r in results}
        findings = [f for f in picked.findings if f.source_url.rstrip("/") in allowed]
        sources = [Source(title=f.source_title, url=f.source_url, role="complementary") for f in findings]
        return {"findings": findings, "sources": sources}

    # ---------------------------------------------------------------- 5. write
    def write(self, state: AgentState):
        """[LLM] + [tool] Write (or rewrite) the page body."""
        route = state["route"]
        parts = [
            f"Action: {route.action} the page '{route.title}' ({route.subtitle}).",
            f"Source notes:\n{state['notes'].model_dump_json(indent=2)}",
        ]
        if state.get("findings"):
            parts.append("Complementary findings to integrate where they help understanding:\n" +
                         "\n".join(f"- {f.fact} (from {f.source_url})" for f in state["findings"]))
        if state.get("existing_body"):
            parts.append("Current page to extend. Keep what is still right, merge the new content in, "
                         f"do not duplicate:\n<current_page>\n{state['existing_body']}\n</current_page>")
        if state.get("draft"):
            feedback = list(state.get("check_errors") or []) + list(state["review"].issues)
            parts.append(f"Your previous draft:\n<draft>\n{state['draft']}\n</draft>\n"
                         "Fix these problems:\n" + "\n".join(f"- {i}" for i in feedback))

        reply, _ = run_with_tools(self.s.model, self.s.tools, [
            SystemMessage(prompts.WRITE.format(style=self.style)),
            HumanMessage("\n\n".join(parts)),
        ])
        return {"draft": clean_draft(text_of(reply)), "revision_number": state["revision_number"] + 1}

    # ---------------------------------------------------------------- 6. review
    def review(self, state: AgentState):
        """[code] mechanical checks, then [LLM] + [tool] critical review."""
        _, page = self.assemble(state)
        errors = check_page(page, state.get("findings") or [])

        messages = [
            SystemMessage(prompts.REVIEW.format(style=self.style)),
            HumanMessage(f"Source notes:\n{state['notes'].model_dump_json(indent=2)}\n\n"
                         f"Page to review:\n<page>\n{page}\n</page>"),
        ]
        _, messages = run_with_tools(self.s.review_model, self.s.tools, messages)
        verdict = self.s.review_model.with_structured_output(Review).invoke(
            messages + [HumanMessage("Give your verdict now.")])
        return {"review": verdict, "check_errors": errors}

    def should_continue(self, state: AgentState):
        """[code] Decide what happens after a review."""
        review = state["review"]
        if (review.approved and not state["check_errors"]) or state["revision_number"] > MAX_REVISIONS:
            return "finalize"
        if review.missing_topics:
            return "research_critique"
        return "write"

    # ---------------------------------------------------------------- 7. finalize + publish
    def assemble(self, state: AgentState) -> tuple[Path, str]:
        """[code] Build the final file: front matter + pills + body + Sources."""
        route = state["route"]
        if route.action == "update":
            path = self.s.root / route.target_path
            front_matter, old_body = split_front_matter(path.read_text())
            front_matter["date-modified"] = self.s.today
            old_body, old_sources = split_sources(old_body)
            pills = old_body.split(":::", 2)
            pills = ":::" + pills[1] + ":::" if old_body.lstrip().startswith("::: {.lesson-meta}") else ""
        else:
            folder_dir = self.s.root / route.topic / route.folder
            path = folder_dir / f"{slugify(route.title)}.qmd"
            n = 2
            while path.exists():
                path, n = folder_dir / f"{slugify(route.title)}-{n}.qmd", n + 1
            front_matter = {"title": route.title, "subtitle": route.subtitle, "date": self.s.today,
                            "categories": [TOPICS[route.topic][0], route.folder_title]}
            old_sources = []
            pills = topic_pills(route.topic, route.folder_title)

        sources = merge_sources(old_sources, state.get("sources") or [])
        body = f"{pills}\n\n{state['draft'].strip()}\n\n{render_sources(sources)}"
        return path, join_front_matter(front_matter, body)

    def finalize(self, state: AgentState):
        """[code] Write the page and register its folder in the menus."""
        path, page = self.assemble(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page)
        route = state["route"]
        if route.action == "create":
            ensure_listed(self.s.root, route.topic, route.folder, route.folder_title)
        return {"page_path": str(path.relative_to(self.s.root))}

    def publish(self, state: AgentState):
        """[code] Open a pull request (or do nothing in dry-run mode)."""
        if self.s.publish is None:
            return {"pr_url": ""}
        return {"pr_url": self.s.publish(state)}

    # ---------------------------------------------------------------- the graph
    def build(self):
        g = StateGraph(AgentState)
        for name in ["fetch", "read", "categorize", "find_gaps", "search", "select", "write",
                     "review", "research_critique", "finalize", "publish"]:
            g.add_node(name, getattr(self, name))

        g.add_edge(START, "fetch")
        g.add_edge("fetch", "read")
        g.add_edge("read", "categorize")
        g.add_edge("categorize", "find_gaps")
        # No gaps found → skip the search and write directly.
        g.add_conditional_edges("find_gaps", lambda s: "search" if s.get("queries") else "write",
                                {"search": "search", "write": "write"})
        g.add_edge("search", "select")
        g.add_edge("select", "write")
        g.add_edge("write", "review")
        g.add_conditional_edges("review", self.should_continue,
                                {"finalize": "finalize", "write": "write",
                                 "research_critique": "research_critique"})
        g.add_edge("research_critique", "search")
        g.add_edge("finalize", "publish")
        g.add_edge("publish", END)
        return g.compile()


def clean_draft(text: str) -> str:
    """[code] Remove what the writer was told not to write, in case it did anyway."""
    text = text.strip()
    if text.startswith("```"):                       # whole answer wrapped in a code fence
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    _, text = split_front_matter(text)
    text, _ = split_sources(text)
    if text.lstrip().startswith("::: {.lesson-meta}"):
        text = text.split(":::", 2)[2].lstrip()
    return text.strip()


def describe_run(state: AgentState) -> str:
    """A readable summary of what the agent did, used as the pull-request description."""
    route, review = state["route"], state.get("review")
    lines = [
        f"**Source:** {state['url']}",
        f"**Decision:** {route.action} `{state.get('page_path', route.target_path)}` "
        f"in **{TOPICS[route.topic][0]}** › {route.folder_title}",
        f"> {route.reasoning}",
        "",
        "### Gaps the agent looked into",
        *[f"- {g}" for g in state.get("gaps") or ["(none)"]],
        "",
        "### Information added from other sources",
    ]
    findings = state.get("findings") or []
    lines += [f"- {f.fact} — [{f.source_title}]({f.source_url})" for f in findings] or ["- (none)"]
    lines += ["", f"### Review (after {state['revision_number']} draft(s))"]
    if review and review.approved and not state.get("check_errors"):
        lines.append("✅ Approved by the reviewer.")
    else:
        lines.append("⚠️ Not fully approved. Remaining points to check:")
        lines += [f"- {i}" for i in (state.get("check_errors") or []) + (review.issues if review else [])]
    return "\n".join(lines)


def to_json(state: AgentState) -> str:
    """Debug helper: the state as JSON."""
    return json.dumps({k: (v.model_dump() if hasattr(v, "model_dump") else v)
                       for k, v in state.items() if k != "raw_text"}, indent=2, default=str)
