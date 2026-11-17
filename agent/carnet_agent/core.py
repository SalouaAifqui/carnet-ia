"""Shared building blocks: services, structured answers, human instructions, placement checks."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from .site import list_pages, list_sections, slugify, split_front_matter, split_sources
from .state import Route


@dataclass
class Services:
    """What the agent needs from the outside world. Passing these in (instead of creating them
    inside the steps) lets the tests swap real models and web calls for fakes."""
    root: Path                                   # the website repository
    fetch: Callable[[str], str]                  # url -> page text
    search: Callable[[list[str]], list[dict]]    # queries -> results
    models: dict = field(default_factory=dict)   # role -> model (read, plan, research, write, check, edit)
    model: object = None                         # fallback for any role not in `models`
    publish: Callable | None = None
    today: str = field(default_factory=lambda: dt.date.today().isoformat())
    check_budget: Callable[[], None] | None = None   # raises BudgetExceeded when the run costs too much

    def m(self, role: str):
        return self.models.get(role) or self.model


def text_of(message) -> str:
    """The text of a model reply, whatever format the provider uses."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content if isinstance(block, dict))


def ask(model, schema, messages, retries: int = 2):
    """[LLM] A structured answer, retried when it comes back incomplete or malformed."""
    for attempt in range(retries + 1):
        try:
            return model.with_structured_output(schema).invoke(messages)
        except (ValidationError, OutputParserException, ValueError) as error:
            if attempt == retries:
                raise
            messages = messages + [HumanMessage(
                f"Your previous answer could not be used ({str(error)[:300]}). Answer again and fill every "
                f"required field of {schema.__name__}.")]


def feedback_block(state: dict) -> str:
    """The human's instructions, if any, formatted for a prompt."""
    if not state.get("human_feedback"):
        return ""
    return f"\n\nInstructions from the human (they take priority):\n{state['human_feedback']}"


def validate_route(root: Path, route: Route) -> dict:
    """[code] Never trust a placement blindly. Returns {"route", "existing_body"}."""
    existing = {p.path: p for p in list_pages(root)}
    if route.action == "update" and route.target_path not in existing:
        route.action, route.target_path = "create", ""
    if route.action == "update":
        page = existing[route.target_path]
        route.topic, route.folder = page.topic, page.folder
    route.folder = slugify(route.folder)
    sections = [s for s in list_sections(root) if s.topic == route.topic]
    match = next((s for s in sections if s.folder == route.folder), None) or \
        next((s for s in sections if slugify(s.title) in (route.folder, slugify(route.folder_title))), None)
    if match:
        route.folder, route.folder_title, route.new_section = match.folder, match.title, False
    else:
        route.new_section = True
    existing_body = ""
    if route.action == "update":
        _, body = split_front_matter((root / route.target_path).read_text())
        existing_body = split_sources(body)[0]
    return {"route": route, "existing_body": existing_body}


def clean_markdown(text: str) -> str:
    """[code] Make a model's markdown safe for the site:
    - strip a code fence wrapping the whole answer;
    - unwrap ```{table} / ```{markdown} blocks (content shown as is);
    - turn any other ```{lang} into ```lang: with braces, Quarto would try to EXECUTE the code
      when building the site (only ```{mermaid} diagrams are allowed)."""
    text = text.strip()
    if text.startswith("```") and text.endswith("```") and not text.startswith("```{"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    text = re.sub(r"(?m)^::\}[ \t]*$", ":::", text)                                     # '::}' typo
    text = re.sub(r"(?ms)^::: \{\.mermaid\}\n(.*?)\n:::[ \t]*$", r"```{mermaid}\n\1\n```", text)  # diagram as a div
    text = re.sub(r"```\{(?:table|markdown|md)\}\n(.*?)\n```", r"\1", text, flags=re.S)
    text = re.sub(r"```\{(?!mermaid\})([a-zA-Z0-9_+-]+)[^}]*\}", r"```\1", text)
    return text.strip()


class BudgetExceeded(RuntimeError):
    """The run went over its cost cap (CARNET_MAX_COST): stopped before spending more."""
