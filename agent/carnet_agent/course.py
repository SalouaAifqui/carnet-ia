"""Course mode: a whole course becomes several concept pages, in one pull request.

    expand ─┬─ Send ─▶ read_lesson (lesson 1) ─┐
            ├─ Send ─▶ read_lesson (lesson 2) ─┼─▶ plan_pages ─▶ prepare_pages ─▶ ⏸ approval ─▶ write_pages ─▶ publish
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
from .article import STATE_TYPES, ArticleAgent, describe_plan
from .config import TOPICS
from .core import Services, ask, feedback_block
from .site import describe_site, slugify
from .state import CoursePlan, CourseState, Lesson, LessonNotes

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


def merge_dicts(left: dict, right: dict) -> dict:
    return {**(left or {}), **(right or {})}


class CourseRunState(CourseState, total=False):
    texts: Annotated[dict, merge_dicts]       # lesson url -> cleaned transcript, filled in parallel
    approved: list[str]


class CourseAgent:
    def __init__(self, services: Services):
        self.s = services
        # The article agent, with a fetch that keeps only the instructor's words on lesson pages.
        cleaning = lambda url: clean_lesson_text(services.fetch(url)) if "/lesson/" in url else services.fetch(url)  # noqa: E731
        self.article = ArticleAgent(replace(services, fetch=cleaning))

    def expand(self, state: CourseRunState):
        """[code] Read the course page and list its lessons."""
        landing = self.s.fetch(state["url"])
        todo = list_lessons(landing, course_slug(state["url"]))
        if not todo:
            raise RuntimeError("No readable lessons found on this course page.")
        title = re.search(r"^# (.+)$", landing, re.M)
        return {"todo": todo, "course_title": title.group(1).strip() if title else course_slug(state["url"])}

    def dispatch(self, state: CourseRunState):
        """[code] One Send per lesson: LangGraph runs these `read_lesson` calls in parallel (map)."""
        return [Send("read_lesson", {"lesson": lesson}) for lesson in state["todo"]]

    def read_lesson(self, payload: dict):
        """[code] fetch + clean, then [LLM, read model] short notes for ONE lesson, used to plan the pages."""
        lesson = payload["lesson"]
        try:
            text = self.article.s.fetch(lesson.url)
        except Exception as error:  # noqa: BLE001 - one unreadable lesson must not stop the course
            print(f"Could not read lesson {lesson.index} ({error})")
            return {"lessons": []}
        if not text:
            print(f"No transcript found for lesson {lesson.index}: {lesson.title}")
            return {"lessons": []}
        notes = ask(self.s.m("read"), LessonNotes, [
            SystemMessage(prompts.READ_LESSON),
            HumanMessage(f"Lesson {lesson.index}: {lesson.title}\n\n{text}"),
        ])
        notes.index, notes.url, notes.title = lesson.index, lesson.url, lesson.title
        return {"lessons": [notes], "texts": {lesson.url: text}}

    def plan_pages(self, state: CourseRunState):
        """[LLM, plan model] Regroup the course by concept (reduce); [code] keeps valid lesson numbers."""
        lessons = sorted(state["lessons"], key=lambda l: l.index)
        listing = "\n\n".join(
            f"Lesson {l.index}: {l.title}\nSummary: {l.summary}\nKey points: " + "; ".join(l.key_points)
            for l in lessons)
        messages = [
            SystemMessage(prompts.COURSE_PLAN.format(site=describe_site(self.s.root),
                                                     max_lessons=MAX_LESSONS_PER_PAGE)),
            HumanMessage(f"Course: {state['course_title']}\n\n{listing}" + feedback_block(state)),
        ]
        plan = ask(self.s.m("plan"), CoursePlan, messages)
        too_big = [p.route.title for p in plan.pages if len(p.lessons) > MAX_LESSONS_PER_PAGE]
        if too_big:
            plan = ask(self.s.m("plan"), CoursePlan, messages + [HumanMessage(
                f"These pages cover more than {MAX_LESSONS_PER_PAGE} lessons: {', '.join(too_big)}. "
                "Split them into more focused concept pages and give the whole plan again.")])
        known = {l.index for l in lessons} - set(plan.skipped)
        for page in plan.pages:
            page.lessons = [i for i in page.lessons if i in known]
        plan.pages = [p for p in plan.pages if p.lessons]
        return {"plan": plan}

    def prepare_pages(self, state: CourseRunState):
        """For each planned page: the librarian plans its parts from ITS lessons' chunks, and the
        research step proposes extra facts. Nothing is written yet."""
        by_index = {l.index: l for l in state["lessons"]}
        texts = state.get("texts") or {}
        pages = []
        for n, planned in enumerate(state["plan"].pages, 1):
            lessons = [by_index[i] for i in planned.lessons]
            page = {"url": lessons[0].url, "urls": [l.url for l in lessons],
                    "titles": {l.url: f"Lesson: {l.title}" for l in lessons},
                    "human_feedback": state.get("human_feedback", "")}
            page |= self.article.fetch_from_texts(page, {l.url: texts.get(l.url, "") for l in lessons})
            page |= self.article.librarian(page, fixed_route=planned.route)
            page |= self.article.research(page, prefix=f"P{n}.F")
            pages.append(page)
        return {"pages": pages}

    def human_approval(self, state: CourseRunState):
        """[code] Nothing: the graph stops BEFORE this step and waits for a person."""
        return {}

    def write_pages(self, state: CourseRunState):
        """Each page: parts written and checked (in parallel), editor, illustrator, then merged into the site."""
        written = []
        for page in state["pages"]:
            page = dict(page) | {"approved": state.get("approved") or [],
                                 "human_feedback": state.get("human_feedback", "")}
            page |= self.article.write_parts(page)
            page |= self.article.edit(page)
            page |= self.article.illustrate(page)
            page |= self.article.finalize(page)
            written.append(page)
        return {"pages": written, "written": [p["page_path"] for p in written]}

    def publish(self, state: CourseRunState):
        if self.s.publish is None:
            return {"pr_url": ""}
        return self.s.publish(state)

    def build(self, pause_for_approval: bool = True):
        g = StateGraph(CourseRunState)
        for name in ["expand", "read_lesson", "plan_pages", "prepare_pages", "human_approval",
                     "write_pages", "publish"]:
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "expand")
        g.add_conditional_edges("expand", self.dispatch, ["read_lesson"])     # map
        g.add_edge("read_lesson", "plan_pages")                              # reduce
        for a, b in [("plan_pages", "prepare_pages"), ("prepare_pages", "human_approval"),
                     ("human_approval", "write_pages"), ("write_pages", "publish"), ("publish", END)]:
            g.add_edge(a, b)
        if not pause_for_approval:
            return g.compile()
        memory = MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES))
        return g.compile(checkpointer=memory, interrupt_before=["human_approval"])


# --- What the human sees ---------------------------------------------------------------

def describe_course_plan(state: dict) -> str:
    lessons = {l.index: l for l in state.get("lessons") or []}
    lines = [f"## 📚 Plan for the course: {state['course_title']}", "",
             f"**Course:** {state['url']}",
             f"**Lessons read:** {len(lessons)} (labs and quizzes are not readable from outside and are left out)"]
    if state.get("human_feedback"):
        lines.append(f"📝 **Your notes:** {state['human_feedback']}")
    pages = state.get("pages") or []
    lines += ["", f"### {len(pages)} page(s)"]
    for n, page in enumerate(pages, 1):
        body = describe_plan(page).split("\n", 2)[2]          # drop the per-page title line
        lines += ["", f"#### Page {n}: {page['plan'].route.title}", body]
    skipped = [lessons[i].title for i in state["plan"].skipped if i in lessons] if state.get("plan") else []
    if skipped:
        lines += ["", "**Left out:** " + ", ".join(skipped)]
    return "\n".join(lines)


def describe_course_run(state: dict) -> str:
    lines = [f"**Course:** {state['url']} ({state.get('course_title', '')})", "", "### Pages"]
    for page in state.get("pages") or []:
        route = page["plan"].route
        flag = "⚠️" if page.get("check_errors") else "✅"
        lines.append(f"- {flag} **{route.action}** `{page.get('page_path')}`: {route.title}")
        lines += [f"  - {e}" for e in page.get("check_errors") or []]
        if page.get("visual_errors"):
            lines.append("  - ⚠️ no synthesis visual: the illustrator's SVG was rejected twice ("
                         + "; ".join(page["visual_errors"][:2]) + ")")
    if state.get("cost") is not None:
        lines += ["", f"**Cost of this run:** ${state['cost']:.3f}"]
    return "\n".join(lines)
