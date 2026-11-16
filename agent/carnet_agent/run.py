"""Command line entry point.

On your computer (approval in the terminal):
    python -m carnet_agent.run https://example.com/article [more URLs…]
    python -m carnet_agent.run https://www.deeplearning.ai/courses/<course>     # course mode
    add --dry-run to write the page locally without a pull request

In GitHub Actions (approval through issue comments):
    python -m carnet_agent.run --mode plan   --issue 12 --from-text "<issue title and body>"
    python -m carnet_agent.run --mode resume --issue 12 --command "<the comment, e.g. /approve F1>"
"""
from __future__ import annotations

import argparse
import uuid
from pathlib import Path

from langchain.chat_models import init_chat_model
from langchain_core.callbacks import UsageMetadataCallbackHandler

from . import hitl
from .article import ArticleAgent, describe_plan, describe_run
from .config import MAX_COST, MAX_COST_COURSE, MODELS, PRICES
from .core import BudgetExceeded, Services
from .course import CourseAgent, describe_course_plan, describe_course_run, is_course_url
from .publish import make_course_publisher, make_publisher
from .web import fetch_source, run_searches

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- Models and cost ------------------------------------------------------------------

def make_model(name: str):
    """'provider:model'. DeepSeek runs with thinking disabled (needed for structured answers)."""
    if name.startswith("deepseek:"):
        return init_chat_model(name, extra_body={"thinking": {"type": "disabled"}})
    return init_chat_model(name)


class Budget:
    """Counts the tokens of every model call of the run, and stops the run above a cap."""

    def __init__(self, limit: float):
        self.limit = limit
        self.handler = UsageMetadataCallbackHandler()

    def cost(self) -> float:
        total = 0.0
        for model, usage in self.handler.usage_metadata.items():
            price = next((p for name, p in sorted(PRICES.items(), key=lambda kv: -len(kv[0]))
                          if model.startswith(name)), None)
            if price:
                total += usage["input_tokens"] / 1e6 * price[0] + usage["output_tokens"] / 1e6 * price[1]
        return total

    def check(self) -> None:
        if self.cost() > self.limit:
            raise BudgetExceeded(f"Stopped: this run cost ${self.cost():.2f}, above the cap of ${self.limit:.2f} "
                                 "(CARNET_MAX_COST).")


def make_services(dry_run: bool, issue: int | None, course: bool, budget: Budget) -> Services:
    try:                                   # local runs: read keys from a .env file if present
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    publisher = make_course_publisher if course else make_publisher
    return Services(
        root=REPO_ROOT, fetch=fetch_source, search=run_searches,
        models={role: make_model(name) for role, name in MODELS.items()},
        publish=None if dry_run else publisher(REPO_ROOT, issue, cost=budget.cost),
        check_budget=budget.check,
    )


def build(dry_run: bool, issue: int | None, course: bool):
    budget = Budget(MAX_COST_COURSE if course else MAX_COST)
    services = make_services(dry_run, issue, course, budget)
    agent = CourseAgent(services) if course else ArticleAgent(services)
    return agent.build(), budget


# --- Running and resuming --------------------------------------------------------------

def _stream(graph, graph_input, budget: Budget) -> tuple[dict, bool]:
    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "callbacks": [budget.handler]}
    if graph_input is not None and "__resume__" in graph_input:        # approve: load the saved plan first
        graph.update_state(config, graph_input["__resume__"], as_node="human_approval")
        graph_input = None
    for update in graph.stream(graph_input, config, stream_mode="updates"):
        for node in update:
            if node != "__interrupt__":
                print(f"✓ {node}  (${budget.cost():.3f} so far)", flush=True)
        budget.check()
    snapshot = graph.get_state(config)
    return snapshot.values | {"cost": budget.cost()}, bool(snapshot.next)


def run(graph, graph_input, budget: Budget) -> tuple[dict, bool]:
    """Stream the graph on a new thread, printing each step and checking the budget."""
    return _stream(graph, graph_input, budget)


def resume(graph, budget: Budget, saved: dict, command: str, feedback: str, course: bool = False):
    """/approve: load the saved plan and continue to writing (update_state + stream(None)).
    /replan: plan again from the start with the instructions."""
    previous = saved.get("human_feedback", "")
    if command == "approve":
        ids = [p.id for page in (saved["pages"] if course else [saved]) for p in page.get("proposals") or []]
        approved, instructions = hitl.parse_approval(feedback, ids)
        values = saved | {"approved": approved,
                          "human_feedback": "\n".join(x for x in [previous, instructions] if x)}
        return _stream(graph, {"__resume__": values}, budget)
    start = {"url": saved["url"], "human_feedback": "\n".join(x for x in [previous, feedback] if x)}
    if not course:
        start["urls"] = saved.get("urls") or [saved["url"]]
    return _stream(graph, start, budget)


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn web pages into Carnet IA notes.")
    parser.add_argument("urls", nargs="*", help="One or more source URLs, or one course page.")
    parser.add_argument("--from-text", help="Text containing the URLs (e.g. a GitHub issue).")
    parser.add_argument("--mode", choices=["local", "plan", "resume"], default="local")
    parser.add_argument("--issue", type=int, help="GitHub issue number (plan / resume modes).")
    parser.add_argument("--command", help="The human's answer (resume mode), e.g. '/approve F1'.")
    parser.add_argument("--dry-run", action="store_true", help="Write locally, no pull request.")
    args = parser.parse_args()
    try:
        _main(args)
    except BudgetExceeded as error:
        print(error)
        if args.issue:
            hitl.post_comment(args.issue, f"🛑 {error} Nothing was published.")
        raise SystemExit(1)


def _main(args) -> None:
    # ---- resume: a person answered on the issue
    if args.mode == "resume":
        command, feedback = hitl.parse_command(args.command or "")
        if command is None:
            print("Not a command, nothing to do.")
            return
        if command == "cancel":
            hitl.close_issue(args.issue, "Cancelled. Nothing was written.")
            return
        kind, saved = hitl.latest_saved_state(args.issue)
        course = kind == "course"
        graph, budget = build(args.dry_run, args.issue, course)
        state, paused = resume(graph, budget, saved, command, feedback, course)
        if paused:                                            # after /replan: a new plan
            hitl.post_comment(args.issue, (hitl.course_plan_comment if course else hitl.plan_comment)(state))
            return
        print((describe_course_run if course else describe_run)(state))
        preview = f"\n👀 Preview: {state['preview_url']}" if state.get("preview_url") else ""
        hitl.post_comment(args.issue, f"✅ Written for ${state['cost']:.3f}. Pull request: "
                                      f"{state.get('pr_url') or '(dry run)'}{preview}")
        return

    # ---- plan / local: start from the URLs
    urls, instructions = list(args.urls), ""
    if not urls and args.from_text:
        urls, instructions = hitl.parse_issue(args.from_text)
    if not urls:
        raise SystemExit("No URL given.")
    course = len(urls) == 1 and is_course_url(urls[0])
    graph, budget = build(args.dry_run, args.issue, course)
    start = {"url": urls[0], "human_feedback": instructions} | ({} if course else {"urls": urls})
    state, paused = run(graph, start, budget)
    describe = describe_course_plan if course else describe_plan

    if args.mode == "plan":                                   # GitHub: post the plan and stop
        hitl.post_comment(args.issue, (hitl.course_plan_comment if course else hitl.plan_comment)(state)
                          + f"\n\n*Planning cost: ${state['cost']:.3f}*")
        return

    while paused:                                             # local: approve in the terminal
        print("\n" + describe(state) + f"\n\nPlanning cost: ${state['cost']:.3f}")
        answer = input("\n/approve [F1 F2 | all] [instructions] · /replan <instructions> · /cancel\n> ")
        command, feedback = hitl.parse_command(answer)
        if command == "cancel":
            print("Cancelled. Nothing was written.")
            return
        if command is None:
            continue
        state, paused = resume(graph, budget, dict(state), command, feedback, course)
    print((describe_course_run if course else describe_run)(state))
    print(f"\nTotal cost: ${state['cost']:.3f}")


if __name__ == "__main__":
    main()
