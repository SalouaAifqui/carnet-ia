"""Everything that touches the web.

Two different things live here, and the difference matters:

* `fetch_source` and `run_searches` are plain functions. The GRAPH calls them,
  always, at a fixed step (`fetch` and `search` nodes).
"""
from __future__ import annotations

import re

import httpx
from langchain_tavily import TavilyExtract, TavilySearch

from .config import MAX_SOURCE_CHARS, PREFERRED_DOMAINS, RESULTS_PER_QUERY


# --- Plain functions used by graph nodes -----------------------------------------

def fetch_source(url: str) -> str:
    """Return the readable text of any web page.

    Websites all look different, so we don't parse HTML ourselves: Tavily Extract
    returns the main content as clean markdown. If it fails, we fall back to a
    plain download with the HTML tags stripped.
    """
    try:
        result = TavilyExtract(extract_depth="advanced").invoke({"urls": [url]})
        pages = result.get("results", []) if isinstance(result, dict) else []
        if pages and pages[0].get("raw_content"):
            return pages[0]["raw_content"][:MAX_SOURCE_CHARS]
    except Exception as error:  # noqa: BLE001 - any failure → fallback
        print(f"Tavily Extract failed ({error}), falling back to a plain download.")
    html = httpx.get(url, follow_redirects=True, timeout=30,
                     headers={"User-Agent": "carnet-ia-agent"}).text
    html = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s{2,}", "\n", text)[:MAX_SOURCE_CHARS]


def run_searches(queries: list[str]) -> list[dict]:
    """Run each query and return a flat list of {query, title, url, content}."""
    search = TavilySearch(max_results=RESULTS_PER_QUERY)
    results = []
    for query in queries:
        try:
            response = search.invoke({"query": query})
        except Exception as error:  # noqa: BLE001 - a failed search must not stop the run
            print(f"Search failed for {query!r}: {error}")
            continue
        if not isinstance(response, dict):      # Tavily returns a message string on errors / no results
            print(f"No results for {query!r}: {str(response)[:200]}")
            continue
        for r in response.get("results", []):
            results.append({"query": query, "title": r.get("title", r["url"]),
                            "url": r["url"], "content": r.get("content", "")})
    # Results from documentation and research sites first.
    results.sort(key=lambda r: not any(d in r["url"] for d in PREFERRED_DOMAINS))
    return results


