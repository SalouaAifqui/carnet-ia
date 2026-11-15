"""[code] Publishing = opening a pull request. Never done by an LLM.

The agent never writes to `main` directly. It pushes a branch and opens a pull request,
so a human reads the proposal and decides to merge it: human in the loop.
"""
from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

from .graph import describe_run
from .site import slugify
from .state import AgentState


def _run(root: Path, *args: str, stdin: str | None = None) -> str:
    result = subprocess.run(args, cwd=root, input=stdin, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def make_publisher(root: Path, issue: int | None = None):
    def publish(state: AgentState) -> str:
        route = state["route"]
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
        branch = f"agent/{slugify(route.title)[:40]}-{stamp}"
        verb = "Update" if route.action == "update" else "Add"

        _run(root, "git", "checkout", "-b", branch)
        _run(root, "git", "add", "-A")
        _run(root, "git", "commit", "-m", f"{verb} note: {route.title}\n\nProposed by the Carnet IA agent from {state['url']}")
        _run(root, "git", "push", "-u", "origin", branch)

        body = describe_run(state)
        if issue:
            body += f"\n\nCloses #{issue}"
        body += "\n\n---\n🤖 Proposed by the Carnet IA agent (`agent/`). Merge to publish, or close to discard."
        return _run(root, "gh", "pr", "create", "--base", "main", "--head", branch,
                    "--title", f"{verb} note: {route.title}", "--body-file", "-", stdin=body)
    return publish
