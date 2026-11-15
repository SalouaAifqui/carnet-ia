"""Human in the loop: pause before writing, show the plan, resume when a person answers.

How the pause works across two separate GitHub Actions runs:

1. Run 1 (issue opened): the graph runs until `interrupt_before=["human_approval"]` stops it.
   We post the plan as an issue comment, with the graph state saved inside it
   (hidden in an HTML comment, compressed).
2. The person answers with /approve, /replan or /cancel.
3. Run 2 (comment posted): a fresh process starts. We read the saved state back from the
   issue, load it into a new graph with `update_state(..., as_node=...)` and resume with
   `stream(None, config)`, exactly like in the Human in the Loop lesson.

`as_node` decides where the graph restarts:
* as_node="human_approval" → the next node is `write`   (approve)
* as_node="read"           → the next node is `categorize` (re-plan with new instructions)
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import zlib

from .graph import describe_plan
from .site import split_front_matter, split_sources
from .state import Finding, PageOutline, Query, Route, Source, SourceNotes

MARKER = "carnet-agent-state"
COMMANDS = ("approve", "replan", "cancel")

# What we save at the pause. The raw page text is not needed any more, so it is left out.
_MODELS = {"notes": SourceNotes, "route": Route, "outline": PageOutline}
_LISTS = {"findings": Finding, "sources": Source, "queries": Query}
_PLAIN = ["url", "gaps", "human_feedback"]


# --- Saving and restoring the state ------------------------------------------------

def save_state(state: dict) -> str:
    data = {k: state[k].model_dump() for k in _MODELS if state.get(k)}
    data |= {k: [x.model_dump() for x in state.get(k) or []] for k in _LISTS}
    data |= {k: state[k] for k in _PLAIN if state.get(k)}
    return base64.b64encode(zlib.compress(json.dumps(data).encode())).decode()


def load_state(blob: str) -> dict:
    data = json.loads(zlib.decompress(base64.b64decode(blob)))
    state = {k: model.model_validate(data[k]) for k, model in _MODELS.items() if k in data}
    state |= {k: [model.model_validate(x) for x in data.get(k, [])] for k, model in _LISTS.items()}
    state |= {k: data[k] for k in _PLAIN if k in data}
    return state


def existing_body(root, route: Route) -> str:
    """When updating a page, the writer needs its current content (re-read from disk)."""
    if route.action != "update":
        return ""
    _, body = split_front_matter((root / route.target_path).read_text())
    return split_sources(body)[0]


# --- The comment shown to the human -------------------------------------------------

def plan_comment(state: dict) -> str:
    return (
        describe_plan(state)
        + "\n\n---\n**Reply with one of:**\n"
        "- `/approve`: write the page as planned. Add instructions on the next lines if you want, "
        "e.g. `/approve` then *keep it short, add a table comparing X and Y*.\n"
        "- `/replan` followed by instructions: redo the plan, e.g. `/replan put it in agents, "
        "folder memory, and focus on the code`.\n"
        "- `/cancel`: stop here.\n"
        f"\n<!-- {MARKER}\n{save_state(state)}\n-->"
    )


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


def latest_saved_state(issue: int) -> dict:
    """Find the most recent plan comment on the issue and restore its state."""
    comments = json.loads(_gh("api", f"repos/{_repo()}/issues/{issue}/comments", "--paginate"))
    for comment in reversed(comments):
        body = comment.get("body") or ""
        if f"<!-- {MARKER}" in body:
            blob = body.split(f"<!-- {MARKER}", 1)[1].split("-->", 1)[0].strip()
            return load_state(blob)
    raise RuntimeError("No saved plan found on this issue. Re-add the 'source' label to start over.")
