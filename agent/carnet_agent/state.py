"""The data the agent works with.

Two kinds of objects live here:

* Pydantic models: the *shapes* we ask the LLM to fill with `with_structured_output`.
  The LLM never answers with free text when we need data: it fills one of these.
* The graph states (`ArticleState` in article.py, `CourseState` here).
"""
import operator
from typing import Annotated, Literal, TypedDict

import re

from pydantic import BaseModel, Field, field_validator

Topic = Literal["llms", "agents", "evaluation", "guardrails", "toolbox"]


# --- Filled by the LLM ---------------------------------------------------------







class Route(BaseModel):
    """Decision of the `categorize` node: where does this content belong?"""
    concept: str = Field(description="The main concept the content teaches, in a few words "
                                     "(not the title of the source).")
    reasoning: str = Field(description="Why this topic, section and page, in one or two sentences.")
    action: Literal["update", "create"] = Field(
        description="'update' if an existing page covers the same concept, otherwise 'create'.")
    topic: Topic
    folder: str = Field(description="The section id, EXACTLY as listed in the site map (e.g. 'memory', "
                                    "'foundation-models'). Only if no section fits: a new id.")
    folder_title: str = Field(description="The section title as listed (or the title of the new section).")
    new_section: bool = Field(default=False, description="True only if no existing section fits.")
    section_description: str = Field(default="", description="Only for a new section: what it will contain.")
    target_path: str = Field(description="For 'update': the path of the page to update, exactly as listed. "
                                         "For 'create': leave empty.")
    title: str = Field(description="Title of the page (new title for 'create', current title for 'update').")
    subtitle: str = Field(description="One-line summary of the page.")


class Query(BaseModel):
    query: str = Field(description="A web search query.")
    why: str = Field(description="The gap in understanding this search should fill.")


class ResearchPlan(BaseModel):
    """Output of `find_gaps` and `research_critique`."""
    gaps: list[str] = Field(description="What a reader would not understand from the source alone.")
    queries: list[Query] = Field(description="At most 3 searches to fill the most important gaps.")


class Finding(BaseModel):
    fact: str = Field(description="The useful information, in your own words.")
    why: str = Field(description="Which gap it fills.")
    source_url: str = Field(description="URL of the search result it comes from. Must be one of the given URLs.")
    source_title: str = Field(description="Title of that page.")


class Findings(BaseModel):
    """Output of `select`: only the findings worth adding."""
    findings: list[Finding]











class Source(BaseModel):
    title: str
    url: str
    role: Literal["primary", "complementary"]





# --- Course mode: a whole course → several concept pages ------------------------

class Lesson(BaseModel):
    """One lesson of a course, as found on the course page (filled by code)."""
    index: int
    url: str
    title: str


class LessonNotes(BaseModel):
    """Detailed notes for ONE lesson (filled by the LLM, then index/url/title set by code)."""
    index: int = 0
    url: str = ""
    title: str = ""
    summary: str = Field(description="What this lesson teaches, in two or three sentences.")
    key_points: list[str] = Field(description="The important ideas, one sentence each.")
    details: list[str] = Field(default_factory=list, description=(
        "Important specifics that must not be lost: numbers, thresholds, conditions, caveats, "
        "steps of a procedure, names of tools and functions mentioned."))
    examples: list[str] = Field(default_factory=list, description=(
        "The concrete examples and scenarios the instructor uses, with their details."))
    definitions: list[str] = Field(default_factory=list, description="'term: definition' for each new concept.")


class PlannedPage(BaseModel):
    """One page of the course plan: where it goes and which lessons feed it."""
    route: Route
    lessons: list[int] = Field(description="Numbers of the lessons whose content goes into this page.")


class CoursePlan(BaseModel):
    """Output of `plan_pages`: the course reorganised into the site's concept pages."""
    pages: list[PlannedPage]
    skipped: list[int] = Field(default_factory=list,
                               description="Lessons with no lasting content (intros, admin), left out.")


class CourseState(TypedDict, total=False):
    url: str                                      # the course page
    course_title: str
    todo: list[Lesson]                            # lessons found on the course page
    lessons: Annotated[list[LessonNotes], operator.add]   # filled in parallel, one per lesson
    plan: CoursePlan
    pages: list[dict]                             # one single-page state per planned page
    human_feedback: str
    written: list[str]                            # paths of the pages written
    pr_url: str


# --- New architecture: librarian → section writers → detail checker → editor -----------

class SectionPlan(BaseModel):
    """One main part ('##') of the article, as planned by the librarian."""
    heading: str = Field(description="Title of the part, short and plain (no '#').")
    kind: Literal["new", "extend"] = Field(
        default="new", description="'extend' = add to an EXISTING part of the page being updated; "
                                   "'new' = a new part.")
    existing_heading: str = Field(
        default="", description="For 'extend': the existing part's title, exactly as listed. For a 'new' part "
                                "in an update: the existing part it goes after ('' = at the end).")
    covers: str = Field(description="What this part explains, in one or two sentences.")
    chunks: list[int] = Field(description="Numbers of the source chunks this part is written from.")
    example: str = Field(description="The concrete example this part will show (from the source).")
    visual: str = Field(description="Its visual element: diagram, table, comparison, steps, example box…")


class ToolInfo(BaseModel):
    """Identity card of a tool or framework made by a company or a project."""
    name: str = Field(description="The product's name, e.g. 'NeMo Agent Toolkit'.")
    maker: str = Field(description="Company or project that makes it, e.g. 'NVIDIA'.")
    summary: str = Field(description="What it is, in one neutral sentence (no marketing words).")
    open_source: Literal["yes", "no", "partly", "unknown"] = "unknown"
    licence: str = Field(default="", description="Licence name if the source states it, else ''.")
    website: str = Field(default="", description="Official documentation or site URL, ONLY if it appears in the source.")
    topics: list[Literal["llms", "agents", "evaluation", "guardrails"]] = Field(
        description="The site topics this tool touches, the MAIN one first: its card is shown in that theme. "
                    "At least one.")
    implements: list[str] = Field(description="The concepts it implements, a few words each "
                                              "(e.g. 'tracing', 'LLM judges', 'input guardrails').")
    related_pages: list[str] = Field(default_factory=list, description=(
        "Paths of existing CONCEPT pages of the site this tool puts into practice, exactly as listed."))


class ArticlePlan(BaseModel):
    """Output of the librarian: where the content goes, and the parts to write."""
    source_kind: Literal["concept", "tool", "mixed"] = Field(
        default="concept", description="'concept': general knowledge. 'tool': mainly presents one product or "
        "framework made by a company or project. 'mixed': teaches general concepts through a product.")
    tool: ToolInfo | None = Field(default=None, description="Fill it for 'tool' and 'mixed' sources.")
    route: Route
    summary: str = Field(description="What the article will teach, in two or three sentences.")
    sections: list[SectionPlan] = Field(description="The parts to write: at most 4.")
    visual_idea: str = Field(default="", description=(
        "The synthesis visual of the page, in one or two sentences: the ONE diagram that sums up the whole "
        "page, built on a concrete example from the source (e.g. 'the ReAct loop: Question, then Thought, "
        "Action, Observation repeated until an Answer, on the dog-weight example'). Boxes and arrows, "
        "a few words per box."))
    visual: Literal["keep", "new"] = Field(default="keep", description=(
        "Updates only: 'keep' the page's existing synthesis visual (the default), or draw a 'new' one "
        "when the page's subject changes a lot."))


class Proposal(BaseModel):
    """A fact found on the web, proposed to the human. Used only if approved."""
    id: str = ""
    fact: str
    why: str
    source_url: str
    source_title: str


class MissingDetails(BaseModel):
    """Output of the detail checker for one part."""
    missing: list[str] = Field(default_factory=list, description=(
        "Important details of the source chunks that the part leaves out: numbers, conditions, caveats, "
        "steps, named tools, examples. Empty if nothing important is missing."))


class ConceptCard(BaseModel):
    name: str = Field(description="The concept, in a few words or a code name.")
    text: str = Field(description="One or two sentences.")


def _words(text: str) -> int:
    return len(re.sub(r"[*`_]", "", text).split())


class Synthesis(BaseModel):
    """Output of the editor: the blocks that frame the article (they never repeat each other)."""
    in_30_seconds: list[str] = Field(description=(
        "Exactly 3 bullets, 25 words max each: the three things to retain from the whole page. Never start "
        "with 'This page explains'."))
    concepts: list[ConceptCard] = Field(description="3 or 4 key concepts, defined without repeating the bullets.")
    remember: list[str] = Field(description="3 to 5 takeaways that can be applied as they are.")
    visual_caption: str = Field(description="One English sentence under the synthesis visual: what it shows.")

    # Checked in code: a wrong answer is sent back to the model (core.ask retries on ValueError).
    @field_validator("in_30_seconds")
    @classmethod
    def _three_short_bullets(cls, v):
        if len(v) != 3:
            raise ValueError(f"in_30_seconds needs exactly 3 bullets, got {len(v)}")
        for b in v:
            if _words(b) > 25:
                raise ValueError(f"in_30_seconds bullet longer than 25 words: {b!r}")
            if b.strip().lower().startswith(("this page", "the page")):
                raise ValueError(f"in_30_seconds must not start with 'This page…': {b!r}")
        return v

    @field_validator("concepts")
    @classmethod
    def _three_or_four_cards(cls, v):
        if not 3 <= len(v) <= 4:
            raise ValueError(f"concepts needs 3 or 4 cards, got {len(v)}")
        return v

    @field_validator("remember")
    @classmethod
    def _three_to_five(cls, v):
        if not 3 <= len(v) <= 5:
            raise ValueError(f"remember needs 3 to 5 bullets, got {len(v)}")
        return v
