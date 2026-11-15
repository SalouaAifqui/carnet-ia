"""Course mode: a whole course becomes several concept pages, in one pull request.

    expand ─┬─ Send ─▶ read_lesson (lesson 1) ─┐
            ├─ Send ─▶ read_lesson (lesson 2) ─┼─▶ plan_pages ─▶ prepare_pages ─▶ ⏸ human_approval ─▶ write_pages ─▶ publish
            └─ Send ─▶ read_lesson (lesson N) ─┘

This is the map-reduce pattern of LangGraph:
* map: `Send` starts one `read_lesson` per lesson, in parallel. Each reads ONE lesson in full,
  so nothing is cut to fit a budget.
* reduce: `plan_pages` sees the notes of every lesson and regroups them by concept.

Each planned page then goes through the same steps as the single-page agent (research, outline,
write, review, finalize): the methods of `CarnetAgent` are reused, not rewritten.
"""
from __future__ import annotations

import operator
import re
from dataclasses import replace
from typing import Annotated
from urllib.parse import unquote

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from . import prompts
from .config import TOPICS
from .graph import CarnetAgent, Services, feedback_block
from .site import describe_site, slugify
from .state import CoursePlan, CourseState, Lesson, LessonNotes, Source, SourceNotes

MAX_LESSONS_PER_PAGE = 8

COURSE_RE = re.compile(r"^https?://(?:www\.|learn\.)?deeplearning\.ai/(?:short-)?courses/([a-z0-9-]+)/?(?:[?#].*)?$")
# Lessons we can't read from outside (labs need a login) or that teach nothing lasting.
SKIP = re.compile(r"^(lab\b|lab-|m\d+-graded)|quiz|graded|resources|forum|feedback|certificate", re.I)


# --- Plain code -------------------------------------------------------------------

def course_slug(url: str) -> str | None:
    match = COURSE_RE.match(url.strip())
    return match.group(1) if match else None


def is_course_url(url: str) -> bool:
    return course_slug(url) is not None


def list_lessons(landing_text: str, slug: str) -> list[Lesson]:
    """The lessons linked from the course page, in course order, without labs and quizzes."""
    lessons, seen = [], set()
    for match in re.finditer(rf"/courses/{slug}/lesson/([a-z0-9]+)/([^\s)\"'?#\]]+)", landing_text):
        key, name = match.group(1), match.group(2)
        if key in seen:
            continue
        seen.add(key)
        readable = unquote(name)
        if SKIP.search(readable):
            continue
        title = re.sub(r"\s+", " ", readable.replace("-", " ")).strip(" :")
        lessons.append(Lesson(index=len(lessons) + 1, title=title[:1].upper() + title[1:],
                              url=f"https://learn.deeplearning.ai/courses/{slug}/lesson/{key}/{name}"))
    return lessons


def clean_lesson_text(text: str) -> str:
    """Keep the instructor's words, drop the page around them (menus, plans, sign-up).
    The transcript comes as long prose paragraphs; navigation comes as short, link-heavy blocks."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text)]
    prose = [p for p in paragraphs if len(p) > 200 and p.count("](") < 2 and "$" not in p]
    cleaned = "\n\n".join(prose)
    return cleaned if len(cleaned.split()) >= 80 else ""      # no transcript found: don't feed page noise


def merge_notes(title: str, lessons: list[LessonNotes]) -> SourceNotes:
    """[code] The notes of the lessons that feed one page, as one set of notes."""
    return SourceNotes(
        title=title, content_type="course lesson",
        summary=" ".join(f"[{l.title}] {l.summary}" for l in lessons),
        key_points=[p for l in lessons for p in l.key_points],
        details=[d for l in lessons for d in l.details],
        examples=[e for l in lessons for e in l.examples],
        definitions=[d for l in lessons for d in l.definitions],
    )


def merge_dicts(left: dict, right: dict) -> dict:
    return {**(left or {}), **(right or {})}


class CourseRunState(CourseState, total=False):
    texts: Annotated[dict, merge_dicts]       # lesson url -> cleaned transcript, filled in parallel


# --- The course agent ---------------------------------------------------------------

class CourseAgent:
    def __init__(self, services: Services):
        self.s = services
        # The single-page agent, with a fetch that cleans lesson pages (also used after a pause).
        cleaning = lambda url: clean_lesson_text(services.fetch(url)) if "/lesson/" in url else services.fetch(url)  # noqa: E731
        self.page = CarnetAgent(replace(services, fetch=cleaning))

    def expand(self, state: CourseRunState):
        """[code] Read the course page and list its lessons."""
        landing = self.s.fetch(state["url"])
        todo = list_lessons(landing, course_slug(state["url"]))
        if not todo:
            raise RuntimeError("No readable lessons found on this course page.")
        title = re.search(r"^# (.+)$", landing, re.M)
        return {"todo": todo, "course_title": title.group(1).strip() if title else course_slug(state["url"])}

    def dispatch(self, state: CourseRunState):
        """[code] One Send per lesson: LangGraph runs these `read_lesson` calls in parallel."""
        return [Send("read_lesson", {"lesson": lesson}) for lesson in state["todo"]]

    def read_lesson(self, payload: dict):
        """[code] fetch + clean, then [LLM] detailed notes for ONE lesson."""
        lesson = payload["lesson"]
        try:
            text = self.page.s.fetch(lesson.url)
        except Exception as error:  # noqa: BLE001 - one unreadable lesson must not stop the course
            print(f"Could not read lesson {lesson.index} ({error})")
            return {"lessons": []}
        if not text:
            print(f"No transcript found for lesson {lesson.index}: {lesson.title}")
            return {"lessons": []}
        notes = self.s.model.with_structured_output(LessonNotes).invoke([
            SystemMessage(prompts.READ_LESSON),
            HumanMessage(f"Lesson {lesson.index}: {lesson.title}\n\n{text}"),
        ])
        notes.index, notes.url, notes.title = lesson.index, lesson.url, lesson.title
        return {"lessons": [notes], "texts": {lesson.url: text}}

    def plan_pages(self, state: CourseRunState):
        """[LLM] Regroup the whole course by concept, then [code] keep only valid lesson numbers."""
        lessons = sorted(state["lessons"], key=lambda l: l.index)
        listing = "\n\n".join(
            f"Lesson {l.index}: {l.title}\nSummary: {l.summary}\nKey points: " + "; ".join(l.key_points)
            for l in lessons)
        messages = [
            SystemMessage(prompts.COURSE_PLAN.format(site=describe_site(self.s.root),
                                                     max_lessons=MAX_LESSONS_PER_PAGE)),
            HumanMessage(f"Course: {state['course_title']}\n\n{listing}" + feedback_block(state)),
        ]
        plan = self.s.model.with_structured_output(CoursePlan).invoke(messages)
        # [code] Pages that swallow too many lessons squeeze the content: ask once for a finer plan.
        too_big = [p.route.title for p in plan.pages if len(p.lessons) > MAX_LESSONS_PER_PAGE]
        if too_big:
            plan = self.s.model.with_structured_output(CoursePlan).invoke(messages + [HumanMessage(
                f"These pages cover more than {MAX_LESSONS_PER_PAGE} lessons: {', '.join(too_big)}. "
                "Split them into more focused concept pages and give the whole plan again.")])
        known = {l.index for l in lessons} - set(plan.skipped)        # skipped lessons feed no page
        for page in plan.pages:
            page.lessons = [i for i in page.lessons if i in known]
        plan.pages = [p for p in plan.pages if p.lessons]
        return {"plan": plan}

    def prepare_pages(self, state: CourseRunState):
        """For each planned page: [code] check the placement, then research and outline it
        with the single-page steps. Nothing is written yet."""
        by_index = {l.index: l for l in state["lessons"]}
        texts = state.get("texts") or {}
        course_source = Source(title=state["course_title"], url=state["url"], role="primary")
        pages = []
        for planned in state["plan"].pages:
            checked = self.page.validate_route(planned.route)
            lessons = [by_index[i] for i in planned.lessons]
            urls = [l.url for l in lessons]
            page = {
                "url": urls[0], "urls": urls, "route": checked["route"],
                "existing_body": checked["existing_body"],
                "notes": merge_notes(checked["route"].title, lessons),
                "raw_text": "\n\n".join(f"=== Lesson {l.index}: {l.title} ({l.url}) ===\n{texts.get(l.url, '')}"
                                        for l in lessons),
                "sources": [course_source] + [Source(title=f"Lesson: {l.title}", url=l.url, role="primary")
                                              for l in lessons],
                "findings": [], "revision_number": 0, "human_feedback": state.get("human_feedback", ""),
            }
            page |= self.page.find_gaps(page)
            if page.get("queries"):
                page |= self.page.search(page)
                picked = self.page.select(page)
                page["findings"] += picked["findings"]
                page["sources"] += picked.get("sources", [])
            page |= self.page.outline(page)
            pages.append(page)
        return {"pages": pages}

    def human_approval(self, state: CourseRunState):
        """[code] Nothing: the graph stops BEFORE this node and waits for a person."""
        return {}

    def write_pages(self, state: CourseRunState):
        """Each page: write ⇄ review (with research when needed), then finalize."""
        written = []
        for page in state["pages"]:
            page = dict(page) | {"human_feedback": state.get("human_feedback", ""), "revision_number": 0}
            page.pop("draft", None)
            page.pop("review", None)
            while True:
                page |= self.page.write(page)
                page |= self.page.review(page)
                step = self.page.should_continue(page)
                if step == "finalize":
                    break
                if step == "research_critique":
                    page |= self.page.research_critique(page)
                    page |= self.page.search(page)
                    picked = self.page.select(page)
                    page["findings"] = (page.get("findings") or []) + picked["findings"]
                    page["sources"] = (page.get("sources") or []) + picked.get("sources", [])
            page |= self.page.finalize(page)
            written.append(page)
        return {"pages": written, "written": [p["page_path"] for p in written]}

    def publish(self, state: CourseRunState):
        if self.s.publish is None:
            return {"pr_url": ""}
        return {"pr_url": self.s.publish(state)}

    def build(self, pause_for_approval: bool = True):
        g = StateGraph(CourseRunState)
        for name in ["expand", "read_lesson", "plan_pages", "prepare_pages", "human_approval",
                     "write_pages", "publish"]:
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "expand")
        g.add_conditional_edges("expand", self.dispatch, ["read_lesson"])     # map
        g.add_edge("read_lesson", "plan_pages")                              # reduce
        g.add_edge("plan_pages", "prepare_pages")
        g.add_edge("prepare_pages", "human_approval")
        g.add_edge("human_approval", "write_pages")
        g.add_edge("write_pages", "publish")
        g.add_edge("publish", END)
        if pause_for_approval:
            types = [("carnet_agent.state", n) for n in ["SourceNotes", "SourceTitle", "Route", "Query", "Finding",
                     "Source", "PageOutline", "OutlineSection", "Review", "Lesson", "LessonNotes", "PlannedPage",
                     "CoursePlan"]]
            memory = MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=types))
            return g.compile(checkpointer=memory, interrupt_before=["human_approval"])
        return g.compile()


# --- What the human sees ---------------------------------------------------------------

def describe_course_plan(state: dict) -> str:
    plan, pages = state["plan"], state["pages"]
    lessons = {l.index: l for l in state.get("lessons") or []}
    lines = [
        f"## 📚 Plan for the course: {state['course_title']}",
        "",
        f"**Course:** {state['url']}",
        f"**Lessons read:** {len(lessons)} (labs and quizzes are not readable from outside and are left out)",
    ]
    if state.get("human_feedback"):
        lines.append(f"📝 **Your notes:** {state['human_feedback']}")
    lines += ["", f"### {len(pages)} page(s)"]
    for n, page in enumerate(pages, 1):
        route = page["route"]
        target = route.target_path if route.action == "update" else \
            f"{route.topic}/{route.folder}/{slugify(route.title)}.qmd"
        lines += ["", f"#### {n}. {route.title}",
                  f"*{route.subtitle}*",
                  f"- **{route.action}** `{target}` in **{TOPICS[route.topic][0]}** › {route.folder_title}"]
        if route.new_section:
            lines.append(f"- ⚠️ **New section proposed:** {route.folder_title}: {route.section_description}")
        used = [l for l in plan.pages[n - 1].lessons] if n - 1 < len(plan.pages) else []
        lines.append("- **Lessons:** " + ", ".join(f"{i}. {lessons[i].title}" for i in used if i in lessons))
        lines.append("- **Outline:** " + " → ".join(s.heading for s in page["outline"].sections))
        if page.get("findings"):
            lines.append(f"- **Added from research:** {len(page['findings'])} fact(s), with sources")
    skipped = [lessons[i].title for i in plan.skipped if i in lessons]
    if skipped:
        lines += ["", "**Left out:** " + ", ".join(skipped)]
    return "\n".join(lines)


def describe_course_run(state: dict) -> str:
    used = {u for page in state.get("pages") or [] for u in page.get("urls") or []}
    lines = [f"**Course:** {state['url']} ({state.get('course_title', '')})",
             f"**Lessons used:** {len(used)}", "", "### Pages"]
    for page in state.get("pages") or []:
        route, review = page["route"], page.get("review")
        ok = review and review.approved and not page.get("check_errors")
        lines.append(f"- {'✅' if ok else '⚠️'} **{route.action}** `{page.get('page_path')}`: {route.title}")
        if not ok:
            lines += [f"  - {i}" for i in (page.get("check_errors") or []) + (review.issues if review else [])]
    return "\n".join(lines)
