"""The data the agent works with.

Two kinds of objects live here:

* Pydantic models: the *shapes* we ask the LLM to fill with `with_structured_output`.
  The LLM never answers with free text when we need data: it fills one of these.
* `AgentState`: the state that flows through the LangGraph graph.
"""
import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

Topic = Literal["llms", "agents", "evaluation"]


# --- Filled by the LLM ---------------------------------------------------------

class SourceTitle(BaseModel):
    url: str = Field(description="The URL of one source, exactly as given.")
    title: str = Field(description="The title of that page.")


class SourceNotes(BaseModel):
    """What the `read` node extracts from the source page(s)."""
    title: str = Field(description="Title of the source (or of the common subject, if several sources).")
    source_titles: list[SourceTitle] = Field(default_factory=list,
                                             description="The title of each source page, one entry per URL.")
    content_type: Literal["course lesson", "article", "documentation", "tip", "video transcript", "other"]
    summary: str = Field(description="Two or three sentences: what the source teaches.")
    key_points: list[str] = Field(description="The important ideas, one sentence each.")
    details: list[str] = Field(default_factory=list, description=(
        "Important specifics that must not be lost: numbers, thresholds, conditions, caveats, "
        "limitations, parameter and function names, steps of a procedure, comparisons."))
    examples: list[str] = Field(default_factory=list, description=(
        "The concrete examples and use cases the source gives, with their inputs and outputs."))
    definitions: list[str] = Field(default_factory=list, description="'term: definition' for each new concept.")
    code_snippets: list[str] = Field(default_factory=list, description="Code shown in the source, verbatim.")


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


class OutlineSection(BaseModel):
    heading: str = Field(description="Section heading as it will appear on the page.")
    points: list[str] = Field(description="What this section will say, one short bullet per idea.")
    example: str = Field(default="", description="The concrete example this section will show, and where it "
                                                 "comes from (source, existing site page, or research finding).")
    visual: str = Field(default="", description="The visual element of this section: mermaid diagram, table, "
                                                "example box, before/after comparison, steps, concept cards…")


class PageOutline(BaseModel):
    """Output of the `outline` node: the plan shown to the human before anything is written."""
    sections: list[OutlineSection]
    code_examples: list[str] = Field(default_factory=list,
                                     description="The code examples the page will show, one line each.")


class Review(BaseModel):
    """Output of the `review` node."""
    approved: bool = Field(description="True only if the page is accurate, complete and follows the style guide.")
    issues: list[str] = Field(default_factory=list, description="Concrete problems to fix in the text.")
    missing_topics: list[str] = Field(default_factory=list,
                                      description="Concepts that need more research before the page is complete.")


class Source(BaseModel):
    title: str
    url: str
    role: Literal["primary", "complementary"]


# --- The graph state ------------------------------------------------------------

class AgentState(TypedDict, total=False):
    url: str                                   # the first source (used in titles and messages)
    urls: list[str]                            # all sources given by the user, read together
    raw_text: str                              # page text from `fetch`
    notes: SourceNotes                         # from `read`
    route: Route                               # from `categorize`
    existing_body: str                         # current page content when updating
    gaps: list[str]                            # from `find_gaps`
    queries: list[Query]                       # searches to run next
    search_results: list[dict]                 # raw results from `search`
    # These two grow over the whole run: each research round ADDS to them.
    findings: Annotated[list[Finding], operator.add]
    sources: Annotated[list[Source], operator.add]
    outline: PageOutline                       # from `outline`: what the page will contain
    human_feedback: str                        # instructions given when approving or re-planning
    draft: str                                 # page body written by `write`
    review: Review                             # from `review`
    check_errors: list[str]                    # from the code checks in `review`
    revision_number: int
    page_path: str                             # where the page was written
    pr_url: str                                # from `publish`


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
