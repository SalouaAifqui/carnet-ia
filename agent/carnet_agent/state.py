"""The data the agent works with.

Two kinds of objects live here:

* Pydantic models: the *shapes* we ask the LLM to fill with `with_structured_output`.
  The LLM never answers with free text when we need data: it fills one of these.
* `AgentState`: the state that flows through the LangGraph graph.
"""
import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

Topic = Literal["llms", "agents", "evaluation", "guardrails"]


# --- Filled by the LLM ---------------------------------------------------------

class SourceNotes(BaseModel):
    """What the `read` node extracts from the source page."""
    title: str = Field(description="Title of the source.")
    content_type: Literal["course lesson", "article", "documentation", "tip", "video transcript", "other"]
    summary: str = Field(description="Two or three sentences: what the source teaches.")
    key_points: list[str] = Field(description="The important ideas, one sentence each.")
    definitions: list[str] = Field(default_factory=list, description="'term: definition' for each new concept.")
    code_snippets: list[str] = Field(default_factory=list, description="Code shown in the source, verbatim.")


class Route(BaseModel):
    """Decision of the `categorize` node: where does this content belong?"""
    reasoning: str = Field(description="Why this placement, in one or two sentences.")
    action: Literal["update", "create"] = Field(
        description="'update' if an existing page covers the same subject, otherwise 'create'.")
    topic: Topic
    folder: str = Field(description="Sub-folder inside the topic, e.g. 'langgraph'. Reuse an existing one when it fits.")
    folder_title: str = Field(description="Human title of the folder, e.g. 'AI Agents in LangGraph'.")
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
    url: str                                   # the source given by the user
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
