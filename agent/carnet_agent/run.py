"""Command line entry point.

    python -m carnet_agent.run https://example.com/article            # full run, opens a PR
    python -m carnet_agent.run https://example.com/article --dry-run  # writes the page locally only
    python -m carnet_agent.run --from-text "issue body with a URL" --issue 12
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from langchain.chat_models import init_chat_model

from .config import MODEL, REVIEW_MODEL
from .graph import CarnetAgent, Services, describe_run
from .publish import make_publisher
from .web import fetch_source, make_tools, run_searches

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn a web page into a Carnet IA note.")
    parser.add_argument("url", nargs="?", help="The source URL.")
    parser.add_argument("--from-text", help="Text containing the URL (e.g. a GitHub issue body).")
    parser.add_argument("--issue", type=int, help="Issue number to close when the PR is merged.")
    parser.add_argument("--dry-run", action="store_true", help="Write the page locally, don't open a PR.")
    args = parser.parse_args()

    url = args.url
    if not url and args.from_text:
        found = re.search(r"https?://\S+", args.from_text)
        url = found.group(0).rstrip(").,>]") if found else None
    if not url:
        parser.error("No URL given.")

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
        publish=None if args.dry_run else make_publisher(REPO_ROOT, args.issue),
    )
    agent = CarnetAgent(services).build()

    state = {}
    # "updates" tells us which node just finished, "values" gives the full state after it.
    for mode, chunk in agent.stream({"url": url}, stream_mode=["updates", "values"]):
        if mode == "updates":
            for node in chunk:
                print(f"✓ {node}", flush=True)
        else:
            state = chunk

    print("\n" + describe_run(state))
    print(f"\nPage: {state.get('page_path')}")
    if state.get("pr_url"):
        print(f"Pull request: {state['pr_url']}")


if __name__ == "__main__":
    main()
