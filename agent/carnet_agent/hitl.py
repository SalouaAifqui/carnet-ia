"""Human in the loop: pause before writing, show the plan, resume when a person answers.

How the pause works across two separate GitHub Actions runs:

1. Run 1 (issue opened): the graph runs until `interrupt_before=["human_approval"]` stops it.
   The plan is posted as an issue comment, with the graph state saved inside it (hidden in an
   HTML comment, compressed). The source text itself is NOT saved: only chunk fingerprints.
2. The person answers: /approve (optionally with the web facts to keep: /approve F1 F3, or
   /approve all), /replan with instructions, or /cancel.
3. Run 2 (comment posted): a fresh process loads the saved state into a new graph with
   `update_state(..., as_node="human_approval")` and resumes with `stream(None, config)`,
   exactly like in the Human in the Loop lesson. The sources are fetched again and the
   chunks found back from their fingerprints.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import zlib

from .state import ArticlePlan, Proposal

MARKER = "carnet-agent-state"
COURSE_MARKER = "carnet-agent-course-state"
COMMANDS = ("approve", "replan", "cancel")

# What we save at the pause (no source text: it is fetched again).
_MODELS = {"plan": ArticlePlan}
_LISTS = {"proposals": Proposal}
_PLAIN = ["url", "urls", "titles", "fingerprints", "human_feedback", "existing_body"]


# --- Saving and restoring the state ------------------------------------------------

def _dump(state: dict) -> dict:
    data = {k: state[k].model_dump() for k in _MODELS if state.get(k)}
    data |= {k: [x.model_dump() for x in state.get(k) or []] for k in _LISTS}
    if state.get("extra_pages"):
        data["extra_pages"] = [_dump(e) for e in state["extra_pages"]]
    return data | {k: state[k] for k in _PLAIN if state.get(k)}


def _load(data: dict) -> dict:
    state = {k: model.model_validate(data[k]) for k, model in _MODELS.items() if k in data}
    state |= {k: [model.model_validate(x) for x in data.get(k, [])] for k, model in _LISTS.items()}
    if data.get("extra_pages"):
        state["extra_pages"] = [_load(e) for e in data["extra_pages"]]
    return state | {k: data[k] for k in _PLAIN if k in data}


def _pack(data: dict) -> str:
    return base64.b64encode(zlib.compress(json.dumps(data).encode(), 9)).decode()


def _unpack(blob: str) -> dict:
    return json.loads(zlib.decompress(base64.b64decode(blob)))


def save_state(state: dict) -> str:
    return _pack(_dump(state))


def load_state(blob: str) -> dict:
    return _load(_unpack(blob))


def save_course_state(state: dict) -> str:
    return _pack({"url": state["url"], "course_title": state.get("course_title", ""),
                  "human_feedback": state.get("human_feedback", ""),
                  "pages": [_dump(p) for p in state.get("pages") or []]})


def load_course_state(blob: str) -> dict:
    data = _unpack(blob)
    return {"url": data["url"], "course_title": data["course_title"],
            "human_feedback": data.get("human_feedback", ""), "pages": [_load(p) for p in data["pages"]]}


# --- The comments shown to the human ------------------------------------------------

_HOW_TO_ANSWER = (
    "\n\n---\n**Reply with one of:**\n"
    "- `/approve`: write as planned, without the web facts.\n"
    "- `/approve F1 F3`: write, and use the web facts F1 and F3 (or `/approve all`).\n"
    "  Instructions can follow on the next lines, e.g. *keep the examples short*.\n"
    "- `/replan` followed by instructions: redo the plan, e.g. `/replan put it in agents, memory`.\n"
    "- `/cancel`: stop here.\n")


def _with_state(text: str, marker: str, blob: str) -> str:
    if len(blob) > 60_000:
        raise RuntimeError("The plan is too large to save in a GitHub comment: split the sources over several issues.")
    return f"{text}{_HOW_TO_ANSWER}\n<!-- {marker}\n{blob}\n-->"


def plan_comment(state: dict) -> str:
    from .article import describe_plan
    return _with_state(describe_plan(state), MARKER, save_state(state))


def course_plan_comment(state: dict) -> str:
    from .course import describe_course_plan
    return _with_state(describe_course_plan(state), COURSE_MARKER, save_course_state(state))


def parse_approval(feedback: str, proposal_ids: list[str]) -> tuple[list[str], str]:
    """'F1 F3 keep it short' -> (['F1', 'F3'], 'keep it short'); 'all …' -> every id."""
    first, _, rest = feedback.partition("\n")
    wanted = re.findall(r"\b(?:P\d+\.)?F\d+\b", first)
    if re.match(r"^\s*all\b", first, re.I):
        wanted, first = list(proposal_ids), re.sub(r"^\s*all\b", "", first, flags=re.I)
    first = re.sub(r"\b(?:P\d+\.)?F\d+\b", "", first)
    instructions = "\n".join(part.strip() for part in [first, rest] if part.strip())
    return [w for w in wanted if w in proposal_ids], instructions


def parse_issue(text: str) -> tuple[list[str], str]:
    """Read a 'New source' issue: every URL in it is a source, and the rest of the
    Notes field is an instruction for the agent.

    'Source: … ### URL https://a ### Notes (optional) https://b  focus on code'
    -> (['https://a', 'https://b'], 'focus on code')
    """
    urls = []
    for url in re.findall(r"https?://[^\s<>()\[\]]+", text):
        url = url.rstrip(".,;:!?'\"")
        if url not in urls:
            urls.append(url)
    notes = text.split("### Notes", 1)[1] if "### Notes" in text else ""
    notes = re.sub(r"^\s*\(optional\)", "", notes)
    notes = re.sub(r"https?://\S+", "", notes).replace("_No response_", "")
    notes = "\n".join(line.strip(" -*") for line in notes.splitlines() if line.strip(" -*"))
    return urls, notes.strip()


def parse_command(text: str) -> tuple[str | None, str]:
    """'/approve\\nkeep it short' -> ('approve', 'keep it short')."""
    text = text.strip()
    if not text.startswith("/"):
        return None, ""
    first, _, rest = text[1:].partition("\n")
    word, _, inline = first.partition(" ")
    command = word.lower().strip()
    if command not in COMMANDS:
        return None, ""
    return command, (inline + "\n" + rest).strip()


# --- GitHub issue comments (plain code, through the gh CLI) ---------------------------

def _gh(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(["gh", *args], input=stdin, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout


def _repo() -> str:
    return os.getenv("GITHUB_REPOSITORY") or json.loads(
        _gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"]


def post_comment(issue: int, body: str) -> None:
    _gh("issue", "comment", str(issue), "--repo", _repo(), "--body-file", "-", stdin=body)


def close_issue(issue: int, comment: str) -> None:
    _gh("issue", "close", str(issue), "--repo", _repo(), "--comment", comment)


def latest_saved_state(issue: int) -> tuple[str, dict]:
    """Find the most recent plan comment on the issue and restore its state.
    Returns ("page", state) or ("course", state)."""
    comments = json.loads(_gh("api", f"repos/{_repo()}/issues/{issue}/comments", "--paginate"))
    for comment in reversed(comments):
        body = comment.get("body") or ""
        for kind, marker, loader in [("course", COURSE_MARKER, load_course_state), ("page", MARKER, load_state)]:
            if f"<!-- {marker}\n" in body:
                blob = body.split(f"<!-- {marker}\n", 1)[1].split("-->", 1)[0].strip()
                return kind, loader(blob)
    raise RuntimeError("No saved plan found on this issue. Re-add the 'source' label to start over.")
