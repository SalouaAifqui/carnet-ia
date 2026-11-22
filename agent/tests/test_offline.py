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
from carnet_agent.illustrator import validate_svg  # noqa: E402
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


SYNTHESIS = Synthesis(
    in_30_seconds=["A new summary.", "Inputs are checked before the model.", "Outputs are checked after it."],
    concepts=[ConceptCard(name="Guardrail", text="A check."), ConceptCard(name="Validator", text="A rule."),
              ConceptCard(name="Guard", text="A wrapper.")],
    remember=["Check inputs.", "Check outputs.", "Log what you block."],
    visual_caption="Checks before and after the model.")

# A small visual in the grammar of reference/vis.py, and two broken ones.
SVG = ('<svg viewBox="0 0 520 300" style="display: block; width: 100%; height: auto; background: #e8f6ef">'
       '<defs><marker id="v-m1" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7">'
       '<path d="M0 0 L10 5 L0 10 z" fill="#586174"></path></marker></defs>'
       '<rect x="40" y="110" width="140" height="56" rx="10" fill="#ffffff" stroke="#d9dee8"></rect>'
       '<text x="110" y="143" font-family="Inter, sans-serif" font-size="13" fill="#16202e" text-anchor="middle">Input</text>'
       '<path d="M180 138 L330 138" stroke="#586174" marker-end="url(#v-m1)"></path>'
       '<rect x="340" y="110" width="140" height="56" rx="10" fill="#0f7a52" stroke="#0f7a52"></rect>'
       '<text x="410" y="143" font-family="Inter, sans-serif" font-size="13" fill="#ffffff" text-anchor="middle">Validator</text></svg>')


def illustrator(answers):
    """A fake illustrator that gives the answers in order (then repeats the last one)."""
    queue = list(answers)
    return Fake(text=lambda messages: queue.pop(0) if len(queue) > 1 else queue[0])


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
    assert [t for t, _ in parts] == ["The ReAct loop", "Who does what", "Building one by hand"]
    assert tail.startswith("::: {.callout-tip}\n## Remember") and find_block(head, "::: {.in30}")
    assert find_block(head, "::: {.concepts}"), "concept cards sit right after In 30 seconds"
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
    watch = good.replace("## Sources {.sources}", "## Watch out\n\nA pitfall.\n\n## Sources {.sources}")
    assert any("'Watch out' heading" in e for e in check_page(watch, []))
    callout = good.replace("## Sources {.sources}", "::: {.callout-warning}\n## Watch out\nA pitfall.\n:::\n\n## Sources {.sources}")
    assert not any("Watch out" in e for e in check_page(callout, [])), "a warning callout is fine"
    code = "```python\n" + "x = 1\n" * 13 + "```"
    long = good.replace("## Sources {.sources}", f"{code}\n\n## Sources {{.sources}}")
    assert any("code-step" in e for e in check_page(long, []))
    stepped = good.replace("## Sources {.sources}", f'::: {{.code-step title="Set x"}}\n{code}\n:::\n\n## Sources {{.sources}}')
    assert not any("code-step" in e for e in check_page(stepped, []))
    print("✓ code checks: visuals, examples, at most 4 parts, no executable code blocks, no lone 'Watch out' "
          "heading, long code in code steps")


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
    r = validate_route(root, Route(topic="guardrails", folder="guardrails", folder_title="x", **base))["route"]
    assert (r.topic, r.new_section) == ("guardrails", False)
    pii = dict(base, title="PII guardrails")
    r = validate_route(root, Route(topic="guardrails", folder="guardrails", folder_title="x", **pii))["route"]
    assert r.target_path == "evaluation/guardrails/pii-guardrails.qmd", "guardrails notes keep their URLs"
    dup = dict(base, title="What is an agent")
    r = validate_route(root, Route(topic="agents", folder="foundations", folder_title="Foundations", **dup))["route"]
    assert (r.action, r.target_path) == ("update", "agents/foundations/what-is-an-agent.qmd"), "no duplicate page"
    print("✓ routing: titles mapped to ids, unknown sections flagged, existing page updated not duplicated")


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
    assert paused and not (root / "evaluation/guardrails/validating-inputs.qmd").exists(), "nothing written before approval"
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
    drawer = illustrator(['<svg viewBox="0 0 400 300"></svg>', SVG])        # wrong viewBox first: one retry
    budget2 = Budget(limit=10)
    graph2 = ArticleAgent(services(root, {"write": writer, "check": check, "edit": editor, "illustrate": drawer},
                                   budget=budget2)).build()
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
    assert final["check_errors"] == [], final["check_errors"]
    order = [body.index(m) for m in ["::: {.synthesis}", "::: {.in30}", "::: {.concepts}", "## Why validate",
                                     "## Inputs", "## Remember", "## Sources"]]
    assert order == sorted(order), "visual, In 30 seconds, cards, parts, Remember, Sources"
    assert "<details" not in body, "no Check yourself questions"
    assert "{.tldr}" not in body and "lesson-meta" not in body
    assert fm["image"] == "/assets/visuals/validating-inputs.svg" and "(/assets/visuals/validating-inputs.svg)" in body
    assert (root / "assets/visuals/validating-inputs.svg").read_text().startswith("<svg xmlns=")
    assert "Checks before and after the model." in body, "the editor's caption is under the visual"
    drawings = drawer.prompts("text")
    assert len(drawings) == 2 and "cannot be used" in drawings[1], "an invalid SVG gets one retry with its errors"
    assert "PARA1" not in drawings[0] and "Inputs are checked before the model." in drawings[0], \
        "the illustrator sees the In-30-seconds bullets, never the source"
    index = (root / "guardrails/index.qmd").read_text()
    assert 'data-folder="guardrails"' in index and "{#guardrails}" in index
    assert final["plan"].route.topic == "guardrails", "guardrails is a topic of its own, with unchanged paths"
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
    drawer = illustrator([SVG])
    models = {"plan": Fake(structured={ArticlePlan: plan}), "write": Fake(text=writer_text),
              "check": Fake(structured={MissingDetails: MissingDetails()}), "edit": Fake(structured={Synthesis: SYNTHESIS}),
              "illustrate": drawer}
    import carnet_agent.article as article_module
    article_module.RESEARCH = False
    try:
        final = ArticleAgent(services(root, models)).build(pause_for_approval=False).invoke({"url": SOURCE, "urls": [SOURCE]})
    finally:
        article_module.RESEARCH = True
    fm, body = split_front_matter((root / target).read_text())
    head, parts, _ = split_parts(split_sources(body)[0])
    titles = [t for t, _ in parts]
    assert len(titles) == 4, "existing 3 parts + 1 new part (the plan respected the 4-part limit)"
    assert "`Guardrail`" in head, "the concept cards are replaced where they are, under In 30 seconds"
    assert titles[:2] == ["The ReAct loop", "Inputs"], "new part inserted after the part named by the librarian"
    assert dict(parts)["The ReAct loop"] == old_parts["The ReAct loop"], "untouched parts stay byte for byte"
    assert dict(parts)["Building one by hand"] == old_parts["Building one by hand"]
    assert dict(parts)["Who does what"].startswith("## Who does what\n\nText for Who does what."), "extended part replaced"
    extend_prompt = next(p for p in models["write"].prompts("text") if "Write the part: Who does what" in p)
    assert "The existing part:" in extend_prompt and "The LLM | The runtime" in extend_prompt
    assert fm["date"] == old_fm["date"] and fm["date-modified"] == "2026-11-16" and fm.get("aliases") == old_fm.get("aliases")
    assert split_sources(body)[1][-1][1] == SOURCE and len(split_sources(body)[1]) == len(split_sources(old_body)[1]) + 1
    assert final["page_path"] == target
    assert drawer.calls == [] and fm["image"] == old_fm["image"], "an update keeps the page's visual"
    assert body.count("::: {.synthesis}") == 1 and "Checks before and after the model." not in body, \
        "the kept visual keeps its caption"
    assert "<details" not in body and body.index("## Remember") < body.index("## Sources"), "no questions"
    print("✓ update: existing parts kept byte for byte, one part extended, one inserted at its place")


OLD_PAGE = """---
title: Old style page
subtitle: Written before the redesign.
date: 2026-11-01
categories:
- Agents
- Foundations
---

::: {.lesson-meta}
[Agents]{.pill .t-agents} [Foundations]{.pill .muted}
:::

::: {.tldr}
This page explains an old summary in one long paragraph.
:::

## First part

""" + "Existing words. " * 80 + """

## Key ideas

::: {.concepts}
::: {.concept}
`Old card`

Old text.
:::
:::

::: {.callout-tip}
## Remember
- Old takeaway.
:::

## Sources {.sources}

- [Old source](https://old.example.com)
"""


def test_update_turns_tldr_into_in30():
    root = site_copy()
    target = "agents/foundations/old-style-page.qmd"
    (root / target).write_text(OLD_PAGE)
    route = Route(concept="c", reasoning="r", action="update", topic="agents", folder="foundations",
                  folder_title="Foundations", target_path=target, title="Old style page", subtitle="s")
    plan = ArticlePlan(route=route, summary="More.", visual_idea="Input, then validator, then the model.", sections=[
        SectionPlan(heading="Second part", kind="new", existing_heading="First part", covers="c", chunks=[1],
                    example="e", visual="v")])
    drawer = illustrator([SVG])
    models = {"plan": Fake(structured={ArticlePlan: plan}), "write": Fake(text=writer_text),
              "check": Fake(structured={MissingDetails: MissingDetails()}), "edit": Fake(structured={Synthesis: SYNTHESIS}),
              "illustrate": drawer}
    import carnet_agent.article as article_module
    article_module.RESEARCH = False
    try:
        final = ArticleAgent(services(root, models)).build(pause_for_approval=False).invoke({"url": SOURCE, "urls": [SOURCE]})
    finally:
        article_module.RESEARCH = True
    fm, body = split_front_matter((root / target).read_text())
    assert "{.tldr}" not in body and "This page explains" not in body, "the old summary is replaced"
    assert body.count("::: {.in30}") == 1 and "Inputs are checked before the model." in body
    assert body.index("::: {.synthesis}") < body.index("::: {.in30}") < body.index("## First part")
    assert "`Old card`" not in body and body.count("::: {.concepts}") == 1, "cards replaced where they were"
    assert body.index("## First part") < body.index("## Second part") and "Existing words." in body
    assert fm["image"] == "/assets/visuals/old-style-page.svg" and len(drawer.calls) == 1, \
        "a page without a visual gets one"
    assert "https://old.example.com" in body and SOURCE in body
    assert final["visual_errors"] == []
    print("✓ update of an old page: .tldr becomes .in30, visual added on top, cards replaced in place")


def test_svg_validator():
    assert validate_svg(SVG) == []
    for path in sorted((REPO / "assets" / "visuals").glob("*.svg")):
        assert validate_svg(path.read_text()) == [], f"{path.name} should pass"
    bad = {
        "not xml": SVG.replace("</svg>", ""),
        "viewBox": SVG.replace("0 0 520 300", "0 0 600 300"),
        "script": SVG.replace("</svg>", "<script>alert(1)</script></svg>"),
        "foreignObject": SVG.replace("</svg>", "<foreignObject></foreignObject></svg>"),
        "image": SVG.replace("</svg>", '<image href="x.png"></image></svg>'),
        "external href": SVG.replace("</svg>", '<a href="https://evil.example"><text x="1" y="1">x</text></a></svg>'),
        "style element": SVG.replace("</svg>", '<style>@import "https://evil.example/x.css";</style></svg>'),
        "animation": SVG.replace("</svg>", '<set attributeName="fill" to="red"></set></svg>'),
        "doctype": "<!DOCTYPE svg>" + SVG,
        "style colour": SVG.replace("<rect ", '<rect style="fill: red" ', 1),
        "tspan outside": SVG.replace(">Input<", '><tspan x="600">Input</tspan><'),
        "event": SVG.replace("<rect ", '<rect onclick="x()" ', 1),
        "colour": SVG.replace("#0f7a52", "#ff00ff"),
        "named colour": SVG.replace('fill="#ffffff"', 'fill="red"', 1),
        "text outside": SVG.replace('x="110" y="143"', 'x="110" y="340"'),
        "too big": SVG.replace("</svg>", "<!--" + "x" * 15_000 + "--></svg>"),
    }
    for name, svg in bad.items():
        assert validate_svg(svg), f"{name} must be rejected"
    from carnet_agent.illustrator import complete_svg
    assert validate_svg(complete_svg(SVG, 'R&D "guards" <v2>')) == [], "a title is escaped in the aria-label"
    print("✓ SVG validator: the site's visuals pass; scripts, external links, events, off-palette "
          "colours, text outside the frame, wrong viewBox and oversize files are rejected")


def test_illustrator_gives_up_after_one_retry():
    from carnet_agent.article import describe_run
    root = site_copy()
    route = Route(concept="c", reasoning="r", action="create", topic="agents", folder="foundations",
                  folder_title="Foundations", target_path="", title="No picture", subtitle="s")
    plan = ArticlePlan(route=route, summary="s", sections=[
        SectionPlan(heading="Only part", covers="c", chunks=[1], example="e", visual="v")])
    drawer = illustrator(['<svg viewBox="0 0 520 300"><script>x</script></svg>'])
    models = {"plan": Fake(structured={ArticlePlan: plan}), "write": Fake(text=writer_text),
              "check": Fake(structured={MissingDetails: MissingDetails()}), "edit": Fake(structured={Synthesis: SYNTHESIS}),
              "illustrate": drawer}
    import carnet_agent.article as article_module
    article_module.RESEARCH = False
    try:
        final = ArticleAgent(services(root, models)).build(pause_for_approval=False).invoke({"url": SOURCE, "urls": [SOURCE]})
    finally:
        article_module.RESEARCH = True
    fm, body = split_front_matter((root / final["page_path"]).read_text())
    assert len(drawer.calls) == 2 and "image" not in fm and "{.synthesis}" not in body
    assert not (root / "assets/visuals/no-picture.svg").exists()
    assert "No synthesis visual" in describe_run(final), "the pull request says the visual is missing"
    print("✓ illustrator: two invalid SVGs → no visual, and a warning in the pull request")


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


def test_mixed_source_gives_concept_page_and_tool_card():
    import carnet_agent.article as article_module
    from carnet_agent.state import ToolInfo
    root = site_copy()
    tool = ToolInfo(name="NeMo Agent Toolkit", maker="NVIDIA", summary="A toolkit to profile and evaluate agents.",
                    open_source="yes", licence="Apache 2.0", website="https://docs.nvidia.com/nemo/agent-toolkit",
                    topics=["agents", "evaluation"], implements=["tracing", "evaluation"],
                    related_pages=["agents/foundations/what-is-an-agent.qmd", "not/a/page.qmd"])
    concept = Route(concept="agent reliability", reasoning="r", action="create", topic="evaluation", folder="agents",
                    folder_title="Evaluating agents", target_path="", title="Making agents reliable", subtitle="s")

    def librarian(messages):
        if "This page is a TOOL CARD" in messages[0].content:     # the second, focused call: the card
            return ArticlePlan(source_kind="tool", tool=tool, route=concept, summary="Card.", sections=[
                SectionPlan(heading=h, covers="c", chunks=[i + 1], example="e", visual="v")
                for i, h in enumerate(["What it is", "What it does", "How to use it", "When to use it"])])
        return ArticlePlan(source_kind="mixed", tool=tool, route=concept, summary="Concepts.", sections=[
            SectionPlan(heading="Why reliability", covers="c", chunks=[1, 2], example="e", visual="v")])

    planner = Fake(structured={ArticlePlan: librarian})
    models = {"plan": planner, "write": Fake(text=writer_text),
              "check": Fake(structured={MissingDetails: MissingDetails()}), "edit": Fake(structured={Synthesis: SYNTHESIS})}
    article_module.RESEARCH = False
    try:
        agent = ArticleAgent(services(root, models))
        state = {"url": SOURCE, "urls": [SOURCE]} | agent.fetch({"url": SOURCE, "urls": [SOURCE]})
        state |= agent.librarian(state)
        comment = hitl.plan_comment(state)
        assert "concept page **and** a tool card" in comment and "NeMo Agent Toolkit by NVIDIA" in comment
        saved = hitl.load_state(comment.split(f"<!-- {hitl.MARKER}\n", 1)[1].split("-->", 1)[0].strip())
        assert saved["extra_pages"][0]["plan"].route.topic == "toolbox", "the tool card survives the pause"
        final = agent.build(pause_for_approval=False).invoke({"url": SOURCE, "urls": [SOURCE]})
    finally:
        article_module.RESEARCH = True

    card_path = "toolbox/tools/nemo-agent-toolkit.qmd"
    assert final["page_path"] == "evaluation/agents/making-agents-reliable.qmd"
    assert final["extra_pages"][0]["page_path"] == card_path
    card = (root / card_path).read_text()
    fm, body = split_front_matter(card)
    assert fm["categories"] == ["Agents", "Evaluation"], "the card is tagged with the topics it touches"
    assert fm["image"] == "/assets/visuals/toolbox-card.svg" and "{.synthesis}" not in body, "cards share the template"
    assert "| **Made by** | NVIDIA |" in body and "Yes (Apache 2.0)" in body, "fact sheet written by code"
    assert [t for t, _ in split_parts(split_sources(body)[0])[1]] == ["What it is", "What it does", "How to use it",
                                                                     "When to use it"]
    assert final["linked"] == ["agents/foundations/what-is-an-agent.qmd"], "invented page paths are dropped"
    concept_page = (root / "agents/foundations/what-is-an-agent.qmd").read_text()
    assert "## In practice: tools" in concept_page and "](../../toolbox/tools/nemo-agent-toolkit.qmd)" in concept_page
    assert concept_page.index("## In practice: tools") < concept_page.index("## Remember"), "placed before Remember"
    index = (root / "agents/index.qmd").read_text()
    assert "theme" not in fm, "`theme` is reserved by Quarto: it would replace the design of the site"
    assert fm["tool-theme"] == "agents", "shown in the main topic of the tool (the first one)"
    assert index.count('data-theme="agents"') == 1 and index.count("[**Tools in practice**") == 1, "one track"
    assert card_path in (root / "_quarto.yml").read_text(), "in the sidebar of its theme"
    assert "data-theme" not in (root / "evaluation/index.qmd").read_text(), "not in its other topics"
    print("✓ mixed source: vendor-neutral concept page + tool card (fact sheet, tags) + 'In practice' link")


def test_tool_source_gives_only_a_tool_card():
    import carnet_agent.article as article_module
    from carnet_agent.state import ToolInfo
    root = site_copy()
    tool = ToolInfo(name="Phoenix", maker="Arize AI", summary="An open-source tracing and evaluation platform.",
                    topics=["evaluation"], implements=["tracing", "LLM judges"])
    wrong = Route(concept="x", reasoning="r", action="create", topic="evaluation", folder="agents",
                  folder_title="Evaluating agents", target_path="", title="Phoenix", subtitle="s")

    def librarian(messages):
        kind = "tool"
        return ArticlePlan(source_kind=kind, tool=tool, route=wrong, summary="Card.", sections=[
            SectionPlan(heading="What it is", covers="c", chunks=[1], example="e", visual="v")])

    models = {"plan": Fake(structured={ArticlePlan: librarian}), "write": Fake(text=writer_text),
              "check": Fake(structured={MissingDetails: MissingDetails()}), "edit": Fake(structured={Synthesis: SYNTHESIS})}
    article_module.RESEARCH = False
    try:
        final = ArticleAgent(services(root, models)).build(pause_for_approval=False).invoke({"url": SOURCE, "urls": [SOURCE]})
    finally:
        article_module.RESEARCH = True
    assert final["page_path"] == "toolbox/tools/phoenix.qmd" and not final.get("extra_pages")
    assert not (root / "evaluation/agents/phoenix.qmd").exists(), "a tool never lands in a concept section"
    index = (root / "evaluation/index.qmd").read_text()
    assert split_front_matter((root / final["page_path"]).read_text())[0]["tool-theme"] == "evaluation"
    assert index.index("## Evaluating agents") < index.index("## Tools in practice") < index.index("## Measure, then protect"), \
        "the first card of a theme creates its track, below the concept tracks"
    from carnet_agent.site import ensure_listed, list_sections
    assert all(s.folder != "tools-in-practice" for s in list_sections(root)), "never offered for concept notes"
    ensure_listed(root, "evaluation", "costs", "Evaluation costs")
    index = (root / "evaluation/index.qmd").read_text()
    assert index.index("## Evaluation costs") < index.index("## Tools in practice"), "tools stay at the bottom"
    print("✓ tool source: one card in the Toolbox, never in a concept section")


if __name__ == "__main__":
    for test in [test_chunks, test_page_blocks, test_checks, test_commands, test_retry_and_budget, test_routing,
                 test_article_create_with_pause_and_research, test_article_update_keeps_existing_content,
                 test_update_turns_tldr_into_in30, test_svg_validator, test_illustrator_gives_up_after_one_retry,
                 test_course_mode, test_mixed_source_gives_concept_page_and_tool_card,
                 test_tool_source_gives_only_a_tool_card]:
        test()
