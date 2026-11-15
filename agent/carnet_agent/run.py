"""Command line entry point.

On your computer (interactive approval in the terminal):
    python -m carnet_agent.run https://example.com/article
    python -m carnet_agent.run https://example.com/article --dry-run      # no pull request

In GitHub Actions (approval through issue comments):
    python -m carnet_agent.run --mode plan   --issue 12 --from-text "<issue title and body>"
    python -m carnet_agent.run --mode resume --issue 12 --command "<the comment, e.g. /approve>"
"""
from __future__ import annotations

import argparse
import re
import uuid
from pathlib import Path

from langchain.chat_models import init_chat_model

from . import hitl
from .config import MODEL, REVIEW_MODEL
from .graph import CarnetAgent, Services, describe_plan, describe_run
from .publish import make_publisher
from .web import fetch_source, make_tools, run_searches

REPO_ROOT = Path(__file__).resolve().parents[2]


def build_agent(dry_run: bool, issue: int | None, pause: bool = True):
    try:                                   # local runs: read keys from a .env file if present
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    services = Services(
        root=REPO_ROOT,
        model=init_chat_model(MODEL),
        review_model=init_chat_model(REVIEW_MODEL),
        fetch=fetch_source,
        search=run_searches,
        tools=make_tools(),
        publish=None if dry_run else make_publisher(REPO_ROOT, issue),
    )
    return CarnetAgent(services).build(pause_for_approval=pause)


def new_thread() -> dict:
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def run(graph, graph_input, config) -> tuple[dict, bool]:
    """Stream the graph, printing each node. Returns (state, paused?)."""
    for update in graph.stream(graph_input, config, stream_mode="updates"):
        for node in update:
            if node != "__interrupt__":
                print(f"✓ {node}", flush=True)
    snapshot = graph.get_state(config)
    return snapshot.values, bool(snapshot.next)


def finish(state: dict) -> None:
    print("\n" + describe_run(state))
    print(f"\nPage: {state.get('page_path')}")
    if state.get("pr_url"):
        print(f"Pull request: {state['pr_url']}")


def resume(graph, saved: dict, command: str, feedback: str, root: Path = REPO_ROOT) -> tuple[dict, bool]:
    """Load a saved plan into a fresh thread and continue, like update_state + stream(None)."""
    config = new_thread()
    # The issue's notes and the instructions given with the command both apply.
    feedback = "\n".join(part for part in [saved.get("human_feedback", ""), feedback] if part)
    if command == "approve":
        values = saved | {"human_feedback": feedback, "revision_number": 0,
                          "existing_body": hitl.existing_body(root, saved["route"])}
        graph.update_state(config, values, as_node="human_approval")   # next node: write
    else:  # replan: keep the source, redo categorize → research → outline with the instructions
        primary = [s for s in saved.get("sources", []) if s.role == "primary"]
        values = {"url": saved["url"], "urls": saved.get("urls") or [saved["url"]],
                  "notes": saved["notes"], "sources": primary,
                  "human_feedback": feedback, "revision_number": 0}
        graph.update_state(config, values, as_node="read")             # next node: categorize
    return run(graph, None, config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn a web page into a Carnet IA note.")
    parser.add_argument("urls", nargs="*", help="One or more source URLs about the same subject.")
    parser.add_argument("--from-text", help="Text containing the URL (e.g. a GitHub issue).")
    parser.add_argument("--mode", choices=["local", "plan", "resume"], default="local")
    parser.add_argument("--issue", type=int, help="GitHub issue number (plan / resume modes).")
    parser.add_argument("--command", help="The human's answer (resume mode), e.g. '/approve'.")
    parser.add_argument("--dry-run", action="store_true", help="Write the page locally, no pull request.")
    parser.add_argument("--yes", action="store_true", help="Skip the approval step (not recommended).")
    args = parser.parse_args()

    graph = build_agent(args.dry_run, args.issue, pause=not args.yes)

    # ---- resume: a person answered on the issue
    if args.mode == "resume":
        command, feedback = hitl.parse_command(args.command or "")
        if command is None:
            print("Not a command, nothing to do.")
            return
        if command == "cancel":
            hitl.close_issue(args.issue, "Cancelled. Nothing was written.")
            return
        state, paused = resume(graph, hitl.latest_saved_state(args.issue), command, feedback)
        if paused:                                       # after /replan: a new plan to approve
            hitl.post_comment(args.issue, hitl.plan_comment(state))
        else:
            finish(state)
            hitl.post_comment(args.issue, f"✅ Page written. Pull request: {state.get('pr_url') or '(dry run)'}")
        return

    # ---- plan / local: start from a URL
    urls, instructions = list(args.urls), ""
    if not urls and args.from_text:
        urls, instructions = hitl.parse_issue(args.from_text)
    if not urls:
        parser.error("No URL given.")

    start = {"url": urls[0], "urls": urls}
    if instructions:
        start["human_feedback"] = instructions        # the issue's notes guide every step
    state, paused = run(graph, start, new_thread())

    if args.mode == "plan":                              # GitHub: post the plan and stop
        hitl.post_comment(args.issue, hitl.plan_comment(state))
        print("Plan posted on the issue. Waiting for /approve, /replan or /cancel.")
        return

    # local: approve in the terminal
    while paused:
        print("\n" + describe_plan(state))
        answer = input("\n/approve [instructions] · /replan <instructions> · /cancel\n> ")
        command, feedback = hitl.parse_command(answer)
        if command == "cancel":
            print("Cancelled. Nothing was written.")
            return
        if command is None:
            print("Please answer with /approve, /replan or /cancel.")
            continue
        state, paused = resume(graph, {k: v for k, v in state.items()}, command, feedback)
    finish(state)


if __name__ == "__main__":
    main()
