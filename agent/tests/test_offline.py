"""Offline tests: the whole agent runs with fake models and a fake web. No API key, no cost.

    cd agent && python tests/test_offline.py
"""
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carnet_agent import hitl  # noqa: E402
from carnet_agent.article import ArticleAgent  # noqa: E402
from carnet_agent.chunks import chunk_text, fingerprint, remap  # noqa: E402
from carnet_agent.config import TOPICS  # noqa: E402
from carnet_agent.core import BudgetExceeded, Services, ask, validate_route  # noqa: E402
from carnet_agent.run import Budget, resume, run  # noqa: E402
from carnet_agent.site import (check_page, find_block, split_front_matter, split_parts,  # noqa: E402
                               split_sources)
from carnet_agent.state import (ArticlePlan, ConceptCard, CoursePlan, Finding, Findings,  # noqa: E402
                                LessonNotes, MissingDetails, PlannedPage, Query, ResearchPlan, Route,
                                SectionPlan, Synthesis)

REPO = Path(__file__).resolve().parents[2]
SOURCE = "https://source.example.com/article"


class Fake:
    """A fake chat model. Answers are computed from the request (calls run in parallel threads),
    and every request is recorded so tests can check what each role was given."""

    def __init__(self, structured=None, text=None):
        self.structured = structured or {}      # schema -> object, or function(messages) -> object
        self.text = text                        # function(messages) -> str
        self.calls = []
        self.lock = threading.Lock()

    def _record(self, kind, messages):
        with self.lock:
            self.calls.append((kind, "\n".join(m.content for m in messages)))

    def with_structured_output(self, schema):
        outer = self

        class _Runner:
            def invoke(self, messages):
                outer._record(schema.__name__, messages)
                answer = outer.structured[schema]
                return answer(messages) if callable(answer) else answer.model_copy(deep=True)
        return _Runner()

    def invoke(self, messages):
        self._record("text", messages)
        return AIMessage(content=self.text(messages))

    def prompts(self, kind):
        return [c for k, c in self.calls if k == kind]


def site_copy() -> Path:
    tmp = Path(tempfile.mkdtemp())
    for name in ["_quarto.yml", "index.qmd", *TOPICS]:
        src = REPO / name
        (shutil.copytree if src.is_dir() else shutil.copy)(src, tmp / name)
    return tmp


# A source of 6 paragraphs of ~180 words: chunked into several numbered chunks.
PARAGRAPHS = [f"PARA{i} " + f"detail{i} about guardrails and validation number {i}. " * 25 for i in range(1, 7)]
SOURCE_TEXT = "# Input validation for LLM apps\n\n" + "\n\n".join(PARAGRAPHS)


def writer_text(messages):
    """Writes the part named in the request; patches add the missing details."""
    prompt = messages[-1].content
    if "Missing details:" in prompt:
        part = prompt.split("The part:\n", 1)[1]
        return part + "\n\nPATCHED: " + prompt.split("Missing details:\n", 1)[1].split("\n", 1)[0]
    heading = re.search(r"Write the part: (.+)", prompt).group(1)
    return (f"## {heading}\n\nText for {heading}.\n\n::: {{.example}}\n**Example.** Concrete.\n:::\n\n"
            f"| a | b |\n|---|---|\n| 1 | 2 |\n\n```{{mermaid}}\nflowchart LR\n  A --> B\n```\n\n" + "Words. " * 130)


def checker(messages):
    written = messages[-1].content
    return MissingDetails(missing=["the number 3"] if "## Inputs" in written else [])


SYNTHESIS = Synthesis(tldr="A new summary.", concepts=[ConceptCard(name="Guardrail", text="A check.")],
                      remember=["Check inputs.", "Check outputs."])


def services(root, models, fetch=lambda url: SOURCE_TEXT, search=None, today="2026-11-16", budget=None):
    return Services(root=root, fetch=fetch, models=models, today=today,
                    search=search or (lambda qs: [
                        {"query": qs[0], "title": "Guard docs", "url": "https://docs.example.com/guard", "content": "…"},
                        {"query": qs[0], "title": "Our own site", "url": "https://salouaaifqui.github.io/carnet-ia/x", "content": "…"}]),
                    check_budget=budget.check if budget else None)


# --------------------------------------------------------------------------- unit tests

def test_chunks():
    chunks = chunk_text("=== Source 1: a ===\n\n" + "\n\n".join(PARAGRAPHS) + "\n\n=== Source 2: b ===\n\nShort.")
    assert len(chunks) >= 4 and chunks[-1].startswith("=== Source 2"), "a chunk never mixes two sources"
    prints = [fingerprint(c) for c in chunks]
    shifted = ["Some new intro paragraph."] + chunks          # the page changed a little on re-fetch
    assert remap(prints, shifted) == {i: i + 1 for i in range(1, len(chunks) + 1)}
    print("✓ chunks: grouped by size, one source per chunk, found back after a re-fetch")


def test_page_blocks():
    body = split_sources(split_front_matter((REPO / "agents/foundations/what-is-an-agent.qmd").read_text())[1])[0]
    head, parts, tail = split_parts(body)
    assert [t for t, _ in parts] == ["The ReAct loop", "Who does what", "Key ideas", "Building one by hand"]
    assert tail.startswith("::: {.callout-tip}\n## Remember") and find_block(head, "::: {.tldr}")
    print("✓ page blocks: summary, parts and Remember found in an existing page")


def test_checks():
    good = "---\ntitle: T\n---\n\n" + writer_text([HumanMessage("Write the part: A")]) + "\n\n## Sources {.sources}\n\n- [a](https://a.com)\n"
    assert check_page(good, []) == []
    flat = "---\ntitle: T\n---\n\n" + "Just words. " * 150 + "\n\n## Sources {.sources}\n\n- [a](https://a.com)\n"
    assert any("Not visual enough" in e for e in check_page(flat, []))
    many = good.replace("## A", "## A\n\n## B\n\n## C\n\n## D\n\n## E")
    assert any("Too many main parts" in e for e in check_page(many, []))
    from carnet_agent.core import clean_markdown
    cleaned = clean_markdown("## A\n\n```{table}\n| a | b |\n|---|---|\n```\n\n```{python}\nx = 1\n```\n\n```{mermaid}\nflowchart LR\n```")
    assert "```{table}" not in cleaned and "| a | b |" in cleaned and "```python" in cleaned and "```{mermaid}" in cleaned
    assert any("execute" in e for e in check_page(good.replace("```{mermaid}", "```{python}"), []))
    fixed = clean_markdown("::: {.example}\nText.\n::}\n\n::: {.mermaid}\nflowchart LR\n  A --> B\n:::")
    assert fixed == "::: {.example}\nText.\n:::\n\n```{mermaid}\nflowchart LR\n  A --> B\n```"
    print("✓ code checks: visuals, examples, at most 4 parts, no executable code blocks")


def test_commands():
    body = ("Source: x\n### URL\n\nhttps://a.com/one\n\n### Notes (optional)\n\nhttps://b.com/two\nFocus on code.\n")
    assert hitl.parse_issue(body) == (["https://a.com/one", "https://b.com/two"], "Focus on code.")
    assert hitl.parse_command("/approve F1 F3\nkeep it short") == ("approve", "F1 F3\nkeep it short")
    assert hitl.parse_approval("F1 F3\nkeep it short", ["F1", "F2", "F3"]) == (["F1", "F3"], "keep it short")
    assert hitl.parse_approval("all", ["F1", "F2"]) == (["F1", "F2"], "")
    assert hitl.parse_approval("", ["F1"]) == ([], "")
    print("✓ commands: several URLs, notes as instructions, /approve F1 F3 or all")


def test_retry_and_budget():
    calls = []

    class Flaky:
        def with_structured_output(self, schema):
            class R:
                def invoke(self, messages):
                    calls.append(messages[-1].content)
                    if len(calls) == 1:
                        schema.model_validate({})
                    return ResearchPlan(gaps=[], queries=[])
            return R()
    assert ask(Flaky(), ResearchPlan, [HumanMessage("x")]).queries == [] and len(calls) == 2

    budget = Budget(limit=0.01)
    budget.handler.usage_metadata = {"gpt-5.4-mini-2026-03-17": {"input_tokens": 10_000, "output_tokens": 1_000}}
    assert abs(budget.cost() - (0.0075 + 0.0045)) < 1e-9          # mini, not nano: longest price name wins
    try:
        budget.check()
        raise AssertionError("should stop")
    except BudgetExceeded:
        pass
    print("✓ incomplete answers retried; cost computed per model; run stopped above the cap")


def test_routing():
    root = site_copy()
    base = dict(concept="x", reasoning="x", action="create", target_path="", title="T", subtitle="S")
    r = validate_route(root, Route(topic="evaluation", folder="Evaluating LLMs", folder_title="x", **base))["route"]
    assert (r.folder, r.new_section) == ("llms", False), "section title mapped to its id"
    r = validate_route(root, Route(topic="evaluation", folder="agent-eval", folder_title="Agent eval", **base))["route"]
    assert r.new_section
    print("✓ routing: titles mapped to ids, unknown sections flagged")


# --------------------------------------------------------------------------- whole runs

def test_article_create_with_pause_and_research():
    root = site_copy()
    route = Route(concept="input validation", reasoning="guardrail", action="create", topic="evaluation",
                  folder="guardrails", folder_title="Guardrails", target_path="", title="Validating inputs",
                  subtitle="Check what goes in.")
    plan = ArticlePlan(route=route, summary="How to validate inputs.", sections=[
        SectionPlan(heading="Why validate", covers="why", chunks=[1], example="e", visual="v"),
        SectionPlan(heading="Inputs", covers="how", chunks=[2, 99], example="e", visual="v"),
    ])
    planner = Fake(structured={
        ArticlePlan: plan,
        ResearchPlan: ResearchPlan(gaps=["?"], queries=[Query(query="guardrails", why="?")]),
        Findings: Findings(findings=[
            Finding(fact="A useful fact.", why="?", source_url="https://docs.example.com/guard", source_title="Guard docs"),
            Finding(fact="Invented.", why="?", source_url="https://invented.com", source_title="?"),
            Finding(fact="Self.", why="?", source_url="https://salouaaifqui.github.io/carnet-ia/x", source_title="?")]),
    })
    budget = Budget(limit=10)
    graph = ArticleAgent(services(root, {"plan": planner, "research": planner}, budget=budget)).build()
    state, paused = run(graph, {"url": SOURCE, "urls": [SOURCE]}, budget)
    assert paused and not list((root / "evaluation").glob("guardrails/*.qmd")), "nothing written before approval"
    assert 99 not in state["plan"].sections[1].chunks
    used = sorted(c for s in state["plan"].sections for c in s.chunks)
    assert used == list(range(1, len(state["chunks"]) + 1)), "every chunk is used by some part"
    assert [p.id for p in state["proposals"]] == ["F1"], "invented and self-citing facts dropped by code"
    comment = hitl.plan_comment(state)
    assert "**F1** A useful fact." in comment and "PARA1" not in comment, "plan shown, source text not saved"

    # A new process resumes from the comment, as on GitHub.
    saved = hitl.load_state(comment.split(f"<!-- {hitl.MARKER}\n", 1)[1].split("-->", 1)[0].strip())
    writer, check, editor = Fake(text=writer_text), Fake(structured={MissingDetails: checker}), \
        Fake(structured={Synthesis: SYNTHESIS})
    budget2 = Budget(limit=10)
    graph2 = ArticleAgent(services(root, {"write": writer, "check": check, "edit": editor}, budget=budget2)).build()
    final, paused = resume(graph2, budget2, saved, "approve", "F1\nKeep it short.")
    assert not paused

    writes = [p for p in writer.prompts("text") if "Write the part:" in p]
    why = next(p for p in writes if "Write the part: Why validate" in p)
    assert "PARA1" in why and "PARA6" not in why, "each writer gets only its own chunks"
    assert "A useful fact." in why and "Keep it short." in why, "approved facts and instructions reach the writer"
    assert len([p for p in writer.prompts("text") if "Missing details:" in p]) == 1, "one targeted patch, no rewrite"

    page = (root / final["page_path"]).read_text()
    fm, body = split_front_matter(page)
    head, parts, tail = split_parts(split_sources(body)[0])
    assert final["page_path"] == "evaluation/guardrails/validating-inputs.qmd" and fm["title"] == "Validating inputs"
    assert [t for t, _ in parts] == ["Why validate", "Inputs"] and "PATCHED: - the number 3" in parts[1][1]
    assert "A new summary." in head and "`Guardrail`" in head and "Check outputs." in tail
    assert [u for _, u in split_sources(body)[1]] == [SOURCE, "https://docs.example.com/guard"]
    assert final["check_errors"] == []
    index = (root / "evaluation/index.qmd").read_text()
    assert '## Guardrails {.group-title data-folder="guardrails"}' in index and "{#guardrails}" in index
    print("✓ create: plan → pause → /approve F1 in a new process → parts written from their chunks, "
          "checked, patched, assembled")


def test_article_update_keeps_existing_content():
    root = site_copy()
    target = "agents/foundations/what-is-an-agent.qmd"
    old_fm, old_body = split_front_matter((root / target).read_text())
    old_parts = dict(split_parts(split_sources(old_body)[0])[1])
    route = Route(concept="agents", reasoning="same", action="update", topic="agents", folder="foundations",
                  folder_title="Foundations", target_path=target, title="What is an agent", subtitle="…")
    plan = ArticlePlan(route=route, summary="More on agents.", sections=[
        SectionPlan(heading="Who does what", kind="extend", existing_heading="Who does what", covers="c",
                    chunks=[1], example="e", visual="v"),
        SectionPlan(heading="Inputs", kind="new", existing_heading="The ReAct loop", covers="c",
                    chunks=[2], example="e", visual="v"),
    ])
    models = {"plan": Fake(structured={ArticlePlan: plan}), "write": Fake(text=writer_text),
              "check": Fake(structured={MissingDetails: MissingDetails()}), "edit": Fake(structured={Synthesis: SYNTHESIS})}
    import carnet_agent.article as article_module
    article_module.RESEARCH = False
    try:
        final = ArticleAgent(services(root, models)).build(pause_for_approval=False).invoke({"url": SOURCE, "urls": [SOURCE]})
    finally:
        article_module.RESEARCH = True
    fm, body = split_front_matter((root / target).read_text())
    _, parts, _ = split_parts(split_sources(body)[0])
    titles = [t for t, _ in parts if t != "Key ideas"]
    assert len(titles) == 4, "existing 3 parts + 1 new part (the plan respected the 4-part limit)"
    assert "`Guardrail`" in dict(parts)["Key ideas"], "the concept cards are replaced where they are"
    assert titles[:2] == ["The ReAct loop", "Inputs"], "new part inserted after the part named by the librarian"
    assert dict(parts)["The ReAct loop"] == old_parts["The ReAct loop"], "untouched parts stay byte for byte"
    assert dict(parts)["Building one by hand"] == old_parts["Building one by hand"]
    assert dict(parts)["Who does what"].startswith("## Who does what\n\nText for Who does what."), "extended part replaced"
    extend_prompt = next(p for p in models["write"].prompts("text") if "Write the part: Who does what" in p)
    assert "The existing part:" in extend_prompt and "The LLM | The runtime" in extend_prompt
    assert fm["date"] == old_fm["date"] and fm["date-modified"] == "2026-11-16" and fm.get("aliases") == old_fm.get("aliases")
    assert split_sources(body)[1][-1][1] == SOURCE and len(split_sources(body)[1]) == len(split_sources(old_body)[1]) + 1
    assert final["page_path"] == target
    print("✓ update: existing parts kept byte for byte, one part extended, one inserted at its place")


def test_course_mode():
    from carnet_agent.course import CourseAgent, describe_course_plan, list_lessons
    course = "https://www.deeplearning.ai/courses/my-course"
    landing = ("# My Course\n\n[a](/courses/my-course/lesson/aaa/what-agents-do)"
               "[b](/courses/my-course/lesson/bbb/using-an-llm-judge)"
               "[c](/courses/my-course/lesson/ccc/lab-1%3A-build)[d](/courses/my-course/lesson/ddd/module-1-quiz)")
    assert [l.title for l in list_lessons(landing, "my-course")] == ["What agents do", "Using an llm judge"]
    prose = "The instructor explains SPECIFIC_DETAIL about judges and agents in a long sentence here. " * 12

    def fetch(url):
        return landing if url == course else "[menu](/x)\n\nSign up $30\n\n" + prose + ("LESSON_B" if "bbb" in url else "LESSON_A")

    root = site_copy()
    judge = Route(concept="LLM judges", reasoning="l2", action="create", topic="evaluation", folder="llms",
                  folder_title="Evaluating LLMs", target_path="", title="LLM judges", subtitle="Models grading models.")
    planner = Fake(structured={
        LessonNotes: LessonNotes(summary="s", key_points=["k"]),
        CoursePlan: CoursePlan(pages=[PlannedPage(route=judge, lessons=[2, 99])], skipped=[1]),
        ArticlePlan: lambda m: ArticlePlan(route=judge, summary="Judges.", sections=[
            SectionPlan(heading="Using a judge", covers="c", chunks=[1], example="e", visual="v")]),
        ResearchPlan: ResearchPlan(gaps=[], queries=[]),
    })
    budget = Budget(limit=10)
    graph = CourseAgent(services(root, {"read": planner, "plan": planner, "research": planner}, fetch=fetch,
                                 budget=budget)).build()
    state, paused = run(graph, {"url": course}, budget)
    assert paused and len(state["lessons"]) == 2 and len(state["pages"]) == 1
    assert state["plan"].pages[0].lessons == [2], "unknown and skipped lessons are dropped"
    assert "Page 1: LLM judges" in describe_course_plan(state)
    comment = hitl.course_plan_comment(state)
    saved = hitl.load_course_state(comment.split(f"<!-- {hitl.COURSE_MARKER}\n", 1)[1].split("-->", 1)[0].strip())

    writer = Fake(text=writer_text)
    budget2 = Budget(limit=10)
    graph2 = CourseAgent(services(root, {"write": writer, "check": Fake(structured={MissingDetails: MissingDetails()}),
                                         "edit": Fake(structured={Synthesis: SYNTHESIS})}, fetch=fetch,
                                  budget=budget2)).build()
    final, paused = resume(graph2, budget2, saved, "approve", "", course=True)
    assert not paused and final["written"] == ["evaluation/llms/llm-judges.qmd"]
    prompt = writer.prompts("text")[0]
    assert "LESSON_B" in prompt and "LESSON_A" not in prompt and "Sign up" not in prompt, \
        "the writer gets the cleaned transcript of ITS lesson only, fetched again after the pause"
    print("✓ course: lessons read in parallel, grouped by concept, parts planned, approved, written")


if __name__ == "__main__":
    for test in [test_chunks, test_page_blocks, test_checks, test_commands, test_retry_and_budget, test_routing,
                 test_article_create_with_pause_and_research, test_article_update_keeps_existing_content,
                 test_course_mode]:
        test()
