"""[code] Publishing = a pull request + a preview of the page on the website. Never done by an LLM.

The agent never writes to `main`. It pushes a branch, opens a pull request, then asks the site
workflow to rebuild: the workflow also builds every open agent pull request under
/preview/pr-<number>/, so you can read the page as it will look before merging.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path
from typing import Callable

from .site import slugify

SITE_URL = "https://salouaaifqui.github.io/carnet-ia"


def _run(root: Path, *args: str, stdin: str | None = None) -> str:
    result = subprocess.run(args, cwd=root, input=stdin, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def page_url(page_path: str, number: str | None = None) -> str:
    html = re.sub(r"\.qmd$", ".html", page_path)
    return f"{SITE_URL}/preview/pr-{number}/{html}" if number else f"{SITE_URL}/{html}"


def _open_pr(root: Path, branch_name: str, title: str, body: str, issue: int | None,
             pages: list[str]) -> dict:
    branch = f"agent/{slugify(branch_name)[:40]}-{dt.datetime.now().strftime('%Y%m%d-%H%M')}"
    _run(root, "git", "checkout", "-b", branch)
    _run(root, "git", "add", "-A")
    _run(root, "git", "commit", "-m", f"{title}\n\nProposed by the Carnet IA agent.")
    _run(root, "git", "push", "-u", "origin", branch)
    if issue:
        body += f"\n\nCloses #{issue}"
    body += "\n\n---\n🤖 Proposed by the Carnet IA agent (`agent/`). Merge to publish, or close to discard."
    pr_url = _run(root, "gh", "pr", "create", "--base", "main", "--head", branch, "--title", title,
                  "--body-file", "-", stdin=body)
    number = pr_url.rstrip("/").rsplit("/", 1)[-1]
    previews = "\n".join(f"- {page_url(p, number)}" for p in pages)
    _run(root, "gh", "pr", "comment", number, "--body-file", "-",
         stdin=f"### 👀 Preview\nReady in a few minutes, before you merge:\n{previews}")
    try:                           # rebuild the site with the preview (workflow_dispatch is allowed from Actions)
        _run(root, "gh", "workflow", "run", "publish.yml", "--ref", "main")
    except RuntimeError as error:
        print(f"Preview not triggered: {error}")
    return {"pr_url": pr_url, "preview_url": page_url(pages[0], number) if pages else ""}


def make_publisher(root: Path, issue: int | None = None, cost: Callable[[], float] | None = None):
    def publish(state) -> dict:
        from .article import describe_run
        route = state["plan"].route
        verb = "Update" if route.action == "update" else "Add"
        body = describe_run(state | {"cost": cost() if cost else None})
        return _open_pr(root, route.title, f"{verb} note: {route.title}", body, issue, [state["page_path"]])
    return publish


def make_course_publisher(root: Path, issue: int | None = None, cost: Callable[[], float] | None = None):
    def publish(state) -> dict:
        from .course import describe_course_run
        title = state.get("course_title") or "course"
        body = describe_course_run(state | {"cost": cost() if cost else None})
        return _open_pr(root, f"course-{title}", f"Notes from the course: {title}", body, issue,
                        state.get("written") or [])
    return publish
