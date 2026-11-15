"""Offline tests: the whole graph runs with fake models and a fake web.

No API key, no cost. From the agent/ folder:
    python tests/test_offline.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

import yaml
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carnet_agent import hitl  # noqa: E402
from carnet_agent.config import TOPICS  # noqa: E402
from carnet_agent.graph import CarnetAgent, Services  # noqa: E402
from carnet_agent.run import new_thread, resume, run  # noqa: E402
from carnet_agent.site import split_front_matter, split_sources  # noqa: E402
from carnet_agent.state import (Finding, Findings, OutlineSection, PageOutline, Query,  # noqa: E402
                                ResearchPlan, Review, Route, Source, SourceNotes)

REPO = Path(__file__).resolve().parents[2]
LONG_BODY = ("::: {.tldr}\nSummary.\n:::\n\n```{mermaid}\nflowchart LR\n  A --> B\n```\n\n"
             "| a | b |\n|---|---|\n| 1 | 2 |\n\n::: {.example}\n**An example.** Text.\n:::\n\n## Key ideas\n\n"
             + "Words to make the page long enough. " * 30)
OUTLINE = PageOutline(sections=[OutlineSection(heading="Key ideas", points=["What a guardrail is"])],
                      code_examples=["A minimal input check"])


class FakeModel:
    """Answers from scripted queues: one queue per structured-output schema, one for plain replies.
    It also records every prompt it receives, so tests can check what the LLM was told."""

    def __init__(self, structured=None, replies=None):
        self.structured = {k: list(v) for k, v in (structured or {}).items()}
        self.replies = list(replies or [])
        self.prompts = []

    def with_structured_output(self, schema):
        model = self

        class _Runner:
            def invoke(self, messages):
                model.prompts.append(messages[-1].content)
                return model.structured[schema].pop(0)
        return _Runner()

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.prompts.append(messages[-1].content)
        return self.replies.pop(0) if self.replies else AIMessage(content="Looks fine.")


class FakeTool:
    name = "web_search"

    def __init__(self):
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        return "result"


def make_site_copy() -> Path:
    tmp = Path(tempfile.mkdtemp())
    for name in ["_quarto.yml", "index.qmd", *TOPICS]:
        src = REPO / name
        (shutil.copytree if src.is_dir() else shutil.copy)(src, tmp / name)
    return tmp


def services(root, model, review_model, tool=None, today="2026-11-15"):
    return Services(
        root=root, model=model, review_model=review_model,
        fetch=lambda url: "page text",
        search=lambda qs: [{"query": qs[0], "title": "Injection docs",
                            "url": "https://docs.example.com/injection", "content": "..."},
                           {"query": qs[0], "title": "Our own site",
                            "url": "https://salouaaifqui.github.io/carnet-ia/agents/", "content": "..."}],
        tools=[tool] if tool else [], today=today,
    )


NOTES = SourceNotes(title="Input validation for LLM apps", content_type="article",
                    summary="How to validate inputs.", key_points=["Validate inputs"])
ROUTE = Route(concept="input validation", reasoning="New guardrail subject.", action="create", topic="guardrails",
              folder="Input Validation", folder_title="Input validation", target_path="",
              title="Validating LLM inputs", subtitle="Check what goes into the model.")
PLAN = ResearchPlan(gaps=["What is prompt injection?"],
                    queries=[Query(query="prompt injection definition", why="term not explained")])
GOOD = Finding(fact="Prompt injection hides instructions in user input.", why="definition",
               source_url="https://docs.example.com/injection", source_title="Injection docs")
INVENTED = Finding(fact="Made up.", why="-", source_url="https://not-in-results.com", source_title="?")
SELF = Finding(fact="From our own site.", why="-", source_url="https://salouaaifqui.github.io/carnet-ia/agents/",
               source_title="Our own site")


def test_pause_then_approve_creates_page():
    root = make_site_copy()

    # ---- Run 1: until the pause (like the GitHub "plan" step)
    planner = FakeModel(structured={SourceNotes: [NOTES], Route: [ROUTE], ResearchPlan: [PLAN],
                                    Findings: [Findings(findings=[GOOD, INVENTED, SELF])], PageOutline: [OUTLINE]})
    graph = CarnetAgent(services(root, planner, FakeModel())).build()
    state, paused = run(graph, {"url": "https://source.example.com/article"}, new_thread())
    assert paused, "the graph must stop before writing"
    assert not (root / "guardrails/input-validation").exists(), "nothing is written before approval"
    comment = hitl.plan_comment(state)
    assert "Validating LLM inputs" in comment and "What a guardrail is" in comment
    assert "not-in-results.com" not in comment, "invented source dropped by code"
    assert "salouaaifqui.github.io" not in comment, "the site never cites itself"

    # ---- The state travels through the comment, then a NEW process resumes
    blob = comment.split(f"<!-- {hitl.MARKER}", 1)[1].split("-->", 1)[0].strip()
    saved = hitl.load_state(blob)
    assert saved["route"].title == ROUTE.title and saved["outline"] == OUTLINE

    tool = FakeTool()
    writer = FakeModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "x"}, "id": "t1"}]),
        AIMessage(content="---\ntitle: x\n---\n" + LONG_BODY + "\n## Sources\n- [x](https://x.com)"),
        AIMessage(content=LONG_BODY + "\n\nNow with the fix."),
    ])
    reviewer = FakeModel(structured={Review: [Review(approved=False, issues=["Explain prompt injection."]),
                                              Review(approved=True)]})
    graph2 = CarnetAgent(services(root, writer, reviewer, tool)).build()
    command, feedback = hitl.parse_command("/approve\nKeep it short.")
    final, paused = resume(graph2, saved, command, feedback, root=root)

    assert not paused
    assert "Keep it short." in writer.prompts[0], "the human's instructions reach the writer"
    assert "Approved outline" in writer.prompts[0], "the approved outline reaches the writer"
    page = (root / final["page_path"]).read_text()
    front_matter, body = split_front_matter(page)
    _, sources = split_sources(body)
    assert final["page_path"] == "guardrails/input-validation/validating-llm-inputs.qmd"
    assert final["revision_number"] == 2
    assert tool.calls == [{"query": "x"}]
    assert front_matter["title"] == "Validating LLM inputs"
    assert [u for _, u in sources] == ["https://source.example.com/article", "https://docs.example.com/injection"]
    assert "https://x.com" not in page and "[Guardrails]{.pill .t-guardrails}" in page
    index = (root / "guardrails/index.qmd").read_text()
    assert "{#input-validation}" in index and "empty-state" not in index
    sidebar = yaml.safe_load((root / "_quarto.yml").read_text())["website"]["sidebar"]
    guard = next(s for s in sidebar if s["id"] == "guardrails")
    assert {"section": "Input validation", "contents": "guardrails/input-validation/*.qmd"} in guard["contents"]
    print("✓ pause → plan comment → /approve in a new process → page, sources, menus")


def test_replan_redoes_the_plan_with_instructions():
    root = make_site_copy()
    saved = {"url": "https://source.example.com/article", "notes": NOTES, "route": ROUTE,
             "sources": [Source(title="Input validation", url="https://source.example.com/article",
                                role="primary")],
             "findings": [GOOD], "outline": OUTLINE}
    new_route = ROUTE.model_copy(update={"topic": "agents", "folder": "safety", "folder_title": "Safety"})
    model = FakeModel(structured={Route: [new_route], ResearchPlan: [ResearchPlan(gaps=[], queries=[])],
                                  PageOutline: [OUTLINE]})
    graph = CarnetAgent(services(root, model, FakeModel())).build()
    state, paused = resume(graph, saved, "replan", "Put it in agents.", root=root)
    assert paused, "after /replan the agent stops again with a new plan"
    assert state["route"].topic == "agents"
    assert "Put it in agents." in model.prompts[0], "instructions reach categorize"
    assert state.get("findings") == [], "old research is not carried over"
    print("✓ /replan → categorize again with the instructions → new plan, paused again")


def test_update_existing_page():
    root = make_site_copy()
    target = "agents/foundations/building-agents-with-langgraph.qmd"
    old_front_matter, old_body = split_front_matter((root / target).read_text())
    _, old_sources = split_sources(old_body)
    notes = SourceNotes(title="LangGraph docs: Graph API", content_type="documentation",
                        summary="Nodes and edges.", key_points=["Nodes", "Edges"])
    route = Route(concept="graph API", reasoning="Same concept.", action="update", topic="agents", folder="foundations",
                  folder_title="Foundations", target_path=target,
                  title="Building agents with LangGraph", subtitle="...")
    model = FakeModel(
        structured={SourceNotes: [notes], Route: [route], ResearchPlan: [ResearchPlan(gaps=[], queries=[])],
                    PageOutline: [OUTLINE]},
        replies=[AIMessage(content=LONG_BODY)],
    )
    reviewer = FakeModel(structured={Review: [Review(approved=True)]})
    graph = CarnetAgent(services(root, model, reviewer, today="2026-11-16")).build(pause_for_approval=False)
    final = graph.invoke({"url": "https://docs.example.com/graph-api"})

    front_matter, body = split_front_matter((root / target).read_text())
    _, sources = split_sources(body)
    assert final["page_path"] == target
    assert front_matter["date"] == old_front_matter["date"]
    assert front_matter["date-modified"] == "2026-11-16"
    assert front_matter.get("aliases") == old_front_matter.get("aliases")
    assert sources[:len(old_sources)] == old_sources
    assert sources[-1][1] == "https://docs.example.com/graph-api"
    assert body.lstrip().startswith("::: {.lesson-meta}")
    print("✓ update: dates, sources, pills kept")


def route_only(route):
    """Run only the categorize node with a given LLM decision; return the validated route."""
    root = make_site_copy()
    agent = CarnetAgent(services(root, FakeModel(structured={Route: [route]}), FakeModel()))
    return agent.categorize({"notes": NOTES})["route"], root


def test_routing_uses_existing_sections():
    base = dict(concept="x", reasoning="x", action="create", target_path="", title="T", subtitle="S")
    # An EMPTY section is a valid target, chosen by id.
    route, _ = route_only(Route(topic="evaluation", folder="llms", folder_title="LLMs", **base))
    assert (route.folder, route.new_section) == ("llms", False)
    # The model gives the section TITLE instead of its id: code maps it to the id.
    route, _ = route_only(Route(topic="llms", folder="Foundation models", folder_title="Foundation models", **base))
    assert (route.folder, route.folder_title, route.new_section) == ("foundation-models", "Foundation models", False)
    # A section that doesn't exist is flagged as new, even if the model didn't say so…
    route, _ = route_only(Route(topic="evaluation", folder="agent-evaluation", folder_title="Agent Evaluation", **base))
    assert route.new_section is True
    # …and the plan shown to the human says it loudly.
    plan = hitl.plan_comment({"url": "u", "route": route, "outline": OUTLINE, "sources": []})
    assert "New section proposed" in plan
    print("✓ routing: empty sections usable, titles mapped to ids, new sections flagged")


def test_page_must_be_visual():
    from carnet_agent.site import check_page
    flat = "---\ntitle: T\n---\n\n" + "Just words. " * 150 + "\n\n## Sources {.sources}\n\n- [a](https://a.com)\n"
    errors = check_page(flat, [])
    assert any("Not visual enough" in e for e in errors) and any("No concrete example" in e for e in errors)
    rich = "---\ntitle: T\n---\n\n" + LONG_BODY + "\n\n## Sources {.sources}\n\n- [a](https://a.com)\n"
    assert check_page(rich, []) == []
    broken = rich.replace("::: {.example}\n**An example.** Text.\n:::", "::: {.example}\n**An example.** Text.")
    assert any("not closed" in e for e in check_page(broken, []))
    print("✓ a flat page is sent back to the writer, a visual one passes")


def test_parse_command():
    assert hitl.parse_command("/approve") == ("approve", "")
    assert hitl.parse_command("/replan put it in agents") == ("replan", "put it in agents")
    assert hitl.parse_command("/approve\nshorter\nmore code") == ("approve", "shorter\nmore code")
    assert hitl.parse_command("thanks!") == (None, "")
    print("✓ commands parsed")


if __name__ == "__main__":
    test_parse_command()
    test_page_must_be_visual()
    test_routing_uses_existing_sections()
    test_pause_then_approve_creates_page()
    test_replan_redoes_the_plan_with_instructions()
    test_update_existing_page()
