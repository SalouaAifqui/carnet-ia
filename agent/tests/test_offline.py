"""Offline tests: the whole graph runs with fake models and a fake web.

No API key, no cost. Run from the agent/ folder:
    python -m pytest tests -q        or        python tests/test_offline.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

import yaml
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carnet_agent.graph import CarnetAgent, Services  # noqa: E402
from carnet_agent.site import split_front_matter, split_sources  # noqa: E402
from carnet_agent.state import (Finding, Findings, Query, ResearchPlan, Review, Route,  # noqa: E402
                                SourceNotes)

REPO = Path(__file__).resolve().parents[2]
LONG_BODY = "::: {.tldr}\nSummary.\n:::\n\n## Key ideas\n\n" + "Words to make the page long enough. " * 30


class FakeModel:
    """Answers from scripted queues: one queue per structured-output schema, one for plain replies."""

    def __init__(self, structured=None, replies=None):
        self.structured = {k: list(v) for k, v in (structured or {}).items()}
        self.replies = list(replies or [])

    def with_structured_output(self, schema):
        model = self

        class _Runner:
            def invoke(self, messages):
                return model.structured[schema].pop(0)
        return _Runner()

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return self.replies.pop(0) if self.replies else AIMessage(content="Looks fine.")


def make_site_copy() -> Path:
    tmp = Path(tempfile.mkdtemp())
    for name in ["_quarto.yml", "index.qmd", "llms", "agents", "guardrails", "daily-use"]:
        src = REPO / name
        (shutil.copytree if src.is_dir() else shutil.copy)(src, tmp / name)
    return tmp


def test_create_page_in_empty_topic():
    root = make_site_copy()
    notes = SourceNotes(title="Input validation for LLM apps", content_type="article",
                        summary="How to validate inputs.", key_points=["Validate inputs"])
    route = Route(reasoning="New guardrail subject.", action="create", topic="guardrails",
                  folder="Input Validation", folder_title="Input validation", target_path="",
                  title="Validating LLM inputs", subtitle="Check what goes into the model.")
    plan = ResearchPlan(gaps=["What is prompt injection?"],
                        queries=[Query(query="prompt injection definition", why="term not explained")])
    good = Finding(fact="Prompt injection hides instructions in user input.", why="definition",
                   source_url="https://docs.example.com/injection", source_title="Injection docs")
    invented = Finding(fact="Made up.", why="-", source_url="https://not-in-results.com", source_title="?")
    model = FakeModel(
        structured={SourceNotes: [notes], Route: [route], ResearchPlan: [plan],
                    Findings: [Findings(findings=[good, invented])]},
        replies=[
            # 1st draft: the writer first calls a tool, then answers (with things code must strip)
            AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "x"}, "id": "t1"}]),
            AIMessage(content="---\ntitle: x\n---\n" + LONG_BODY + "\n## Sources\n- [x](https://x.com)"),
            AIMessage(content=LONG_BODY + "\n\nNow with the fix."),   # 2nd draft
        ],
    )
    review_model = FakeModel(structured={Review: [
        Review(approved=False, issues=["Explain prompt injection."]),
        Review(approved=True),
    ]})
    tool_calls = []

    class FakeTool:
        name = "web_search"

        def invoke(self, args):
            tool_calls.append(args)
            return "result"

    services = Services(
        root=root, model=model, review_model=review_model,
        fetch=lambda url: "page text",
        search=lambda qs: [{"query": qs[0], "title": "Injection docs",
                            "url": "https://docs.example.com/injection", "content": "..."}],
        tools=[FakeTool()], today="2026-11-15",
    )
    final = CarnetAgent(services).build().invoke({"url": "https://source.example.com/article"})

    page = (root / final["page_path"]).read_text()
    front_matter, body = split_front_matter(page)
    _, sources = split_sources(body)
    urls = [u for _, u in sources]

    assert final["page_path"] == "guardrails/input-validation/validating-llm-inputs.qmd"
    assert final["revision_number"] == 2                       # rewritten once after review
    assert tool_calls == [{"query": "x"}]                      # the LLM's tool call was executed
    assert front_matter["title"] == "Validating LLM inputs" and front_matter["date"] == "2026-11-15"
    assert urls == ["https://source.example.com/article", "https://docs.example.com/injection"]
    assert "not-in-results.com" not in page                    # invented source dropped by code
    assert "https://x.com" not in page                         # writer's own Sources replaced
    assert "[Guardrails]{.pill .t-guardrails}" in page
    index = (root / "guardrails/index.qmd").read_text()
    assert "{#input-validation}" in index and "empty-state" not in index
    sidebar = yaml.safe_load((root / "_quarto.yml").read_text())["website"]["sidebar"]
    guard = next(s for s in sidebar if s["id"] == "guardrails")
    assert {"section": "Input validation", "contents": "guardrails/input-validation/*.qmd"} in guard["contents"]
    print("✓ create: page, sources, menus OK")


def test_update_existing_page():
    root = make_site_copy()
    target = "agents/langgraph/02-langgraph-components.qmd"
    old_front_matter, old_body = split_front_matter((root / target).read_text())
    _, old_sources = split_sources(old_body)
    notes = SourceNotes(title="LangGraph docs: Graph API", content_type="documentation",
                        summary="Nodes and edges.", key_points=["Nodes", "Edges"])
    route = Route(reasoning="Same subject.", action="update", topic="agents", folder="langgraph",
                  folder_title="AI Agents in LangGraph", target_path=target,
                  title="LangGraph Components", subtitle="...")
    model = FakeModel(
        structured={SourceNotes: [notes], Route: [route], ResearchPlan: [ResearchPlan(gaps=[], queries=[])]},
        replies=[AIMessage(content=LONG_BODY)],
    )
    services = Services(root=root, model=model, review_model=FakeModel(structured={Review: [Review(approved=True)]}),
                        fetch=lambda url: "text", search=lambda qs: [], today="2026-11-16")
    final = CarnetAgent(services).build().invoke({"url": "https://docs.example.com/graph-api"})

    front_matter, body = split_front_matter((root / target).read_text())
    _, sources = split_sources(body)
    assert final["page_path"] == target
    assert front_matter["date"] == old_front_matter["date"]          # creation date kept
    assert front_matter["date-modified"] == "2026-11-16"             # modification date added
    assert front_matter.get("aliases") == old_front_matter.get("aliases")
    assert sources[:len(old_sources)] == old_sources                 # old sources kept, in order
    assert sources[-1][1] == "https://docs.example.com/graph-api"    # new source added
    assert body.lstrip().startswith("::: {.lesson-meta}")            # pills kept
    print("✓ update: dates, sources, pills OK")


if __name__ == "__main__":
    test_create_page_in_empty_topic()
    test_update_existing_page()
