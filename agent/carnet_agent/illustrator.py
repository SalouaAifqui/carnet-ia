"""The illustrator: one synthesis visual (SVG) per page, in the grammar of reference/vis.py.

    edit ─▶ illustrate ─▶ finalize
    (LLM 4)  (LLM 7 + code)

The model never sees the raw source: only the title, the topic, the visual idea of the plan, the
"In 30 seconds" bullets and the part titles. What it draws is checked by code (`validate_svg`):
well-formed XML, the 520x300 viewBox, under 15 KB, nothing executable or external, the palette
of vis.py only, every text inside the frame. One retry with the errors; after that, no visual and
a warning in the pull request.
"""
from __future__ import annotations

import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

from langchain_core.messages import HumanMessage, SystemMessage

from .core import text_of

# --- The palette of reference/vis.py -----------------------------------------------------
INK, MUTED, LINE, PAPER = "#16202e", "#586174", "#d9dee8", "#ffffff"
OK, WARN, WARN_SOFT, BAD, BAD_SOFT = "#0f7a52", "#b45309", "#fff3e2", "#c92a2a", "#fdeceb"
C = {   # topic -> (colour, soft background)
    "llms": ("#6741d9", "#f1edfe"),
    "agents": ("#2f54d6", "#eef2ff"),
    "eval": ("#c2255c", "#fdeef4"),
    "guard": ("#0f7a52", "#e8f6ef"),
    "tools": ("#0b7285", "#e6f5f8"),
}
# neutral tints vis.py also uses (placeholder lines, light fills)
TINTS = ["#c9d0dc", "#f4f6f9", "#dfe3ea", "#9aa3b2", "#f3a6c2", "#c9c0f2", "#9fd3bb", "#d9480f"]
PALETTE = {c.lower() for c in [INK, MUTED, LINE, PAPER, "#fff", OK, WARN, WARN_SOFT, BAD, BAD_SOFT, *TINTS]
           } | {c for pair in C.values() for c in pair}

MAX_BYTES = 15_000
WIDTH, HEIGHT = 520, 300
FORBIDDEN_TAGS = {"script", "foreignobject", "image", "iframe", "object", "embed", "use", "audio", "video"}
# anything else is refused: <style> can import, <set> and <animate> can rewrite attributes
ALLOWED_TAGS = {"svg", "g", "defs", "marker", "path", "rect", "circle", "ellipse", "line", "polyline",
                "polygon", "text", "tspan", "title", "desc"}
EXAMPLES = ["what-is-an-agent", "guardrails-for-llm-apps", "validating-evaluators"]


def topic_key(topic: str, folder: str = "") -> str:
    """The vis.py colour family of a page."""
    if topic == "guardrails" or (topic == "evaluation" and folder == "guardrails"):
        return "guard"
    if topic == "evaluation":
        return "eval"
    return {"llms": "llms", "agents": "agents", "toolbox": "tools"}.get(topic, "agents")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def validate_svg(svg: str) -> list[str]:
    """[code] Everything that makes an SVG unsafe or off-style. Empty list = valid."""
    errors = []
    size = len(svg.encode("utf-8"))
    if size >= MAX_BYTES:
        errors.append(f"The SVG is {size} bytes; it must stay under {MAX_BYTES}.")
    if re.search(r"<!(DOCTYPE|ENTITY)", svg, re.I):
        return errors + ["DOCTYPE and entities are not allowed."]
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as error:
        return errors + [f"Not valid XML: {error}."]
    if _local(root.tag) != "svg":
        return errors + ["The root element must be <svg>."]
    view_box = (root.get("viewBox") or "").split()
    if view_box != ["0", "0", str(WIDTH), str(HEIGHT)]:
        errors.append(f'The viewBox must be "0 0 {WIDTH} {HEIGHT}" (got "{root.get("viewBox")}").')
    colours = set()
    for el in root.iter():
        tag = _local(el.tag)
        if tag in FORBIDDEN_TAGS or tag not in ALLOWED_TAGS:
            errors.append(f"<{tag}> is not allowed.")
        for name, value in el.attrib.items():
            attr = _local(name)
            if attr.startswith("on"):
                errors.append(f'Event attribute "{attr}" is not allowed.')
            if attr == "href" and not value.startswith("#"):
                errors.append(f'External reference "{value}" is not allowed (only "#id").')
            if re.search(r"url\(\s*(?!#)", value) or "javascript:" in value.lower():
                errors.append(f'External reference in {attr}="{value}" is not allowed.')
            colours |= {c.lower() for c in re.findall(r"#[0-9a-fA-F]{3,8}\b", value)
                        if not (attr == "href" or "url(" in value)}
            if attr in ("fill", "stroke", "color", "stop-color") and value.strip().lower() not in (
                    "none", "transparent", "currentcolor") and not value.startswith(("#", "url(#")):
                errors.append(f'Colour "{value}" must be a hex colour of the palette.')
        for prop, value in re.findall(r"([\w-]+)\s*:\s*([^;]+)", el.get("style", "")):
            if prop.lower() in ("fill", "stroke", "color", "background", "background-color") and \
                    value.strip().lower() not in PALETTE | {"none", "transparent"}:
                errors.append(f'Colour "{value}" in style must be a hex colour of the palette.')
        if tag in ("text", "tspan"):
            for axis, limit in (("x", WIDTH), ("y", HEIGHT)):
                for raw in re.split(r"[\s,]+", el.get(axis, "0").strip()):  # every coordinate of the list
                    try:
                        number = float(raw)
                    except ValueError:
                        errors.append(f'<text> has a non-numeric {axis}="{raw}".')
                        continue
                    if not 0 <= number <= limit:
                        errors.append(f'<text> "{(el.text or "").strip()[:30]}" is outside the frame ({axis}={raw}).')
    off = sorted(colours - PALETTE)
    if off:
        errors.append("Colours outside the vis.py palette: " + ", ".join(off) + ".")
    return errors


def extract_svg(answer: str) -> str:
    match = re.search(r"<svg\b.*?</svg>", answer, re.S | re.I)
    return match.group(0).strip() if match else answer.strip()


def complete_svg(svg: str, alt: str) -> str:
    """Same header as the visuals already on the site: namespace, size, accessible name."""
    head = svg[:svg.index(">")]
    extra = []
    if "xmlns=" not in head:
        extra.append('xmlns="http://www.w3.org/2000/svg"')
    if " width=" not in head:
        extra.append(f'width="{WIDTH}" height="{HEIGHT}"')
    if "role=" not in head:
        extra += ['role="img"', 'aria-label="' + escape(alt, {'"': "&quot;"}) + '"']
    return svg.replace("<svg", "<svg " + " ".join(extra), 1) if extra else svg


def examples(root: Path) -> str:
    """2-3 visuals of the site, shown to the model as the style to follow."""
    out = []
    for slug in EXAMPLES:
        path = root / "assets" / "visuals" / f"{slug}.svg"
        if path.exists():
            out.append(f"--- Example: {slug}.svg ---\n{path.read_text()}")
    return "\n\n".join(out)


PROMPT = """You draw the synthesis visual of one page of Carnet IA, a learning notebook on applied AI.
It is the one picture that sums up the whole page, shown under its title and as its thumbnail.

Answer with ONE SVG element only (no explanation, no code fence), following this grammar exactly:
- <svg viewBox="0 0 520 300" ...>, with style="display: block; width: 100%; height: auto; background: {soft}"
- background = the soft topic colour {soft}; boxes are white ({paper}) with a {line} border and rx="10";
  1 or 2 filled elements in the topic colour {colour} (white text on them), the rest white or soft
- text: font-family="Inter, sans-serif", font-size 10 to 15, at least 10 px from every box edge and inside
  the frame (0-520 x 0-300); code names may use font-family="JetBrains Mono, monospace"
- text must fit: count 0.6 x font-size per character (7.2 px at 12px); shorten it or widen the box,
  and never let two elements overlap
- colours ONLY from this palette: {palette}
- arrows are <path> with a <marker> defined in <defs>; ids must be unique (prefix them with "{prefix}-")
- no <script>, <image>, <foreignObject>, external links, event attributes; under 15 KB
- reuse a concrete example of the page (names, numbers, a real case) rather than abstract boxes;
  a few words per box, no sentences

Visuals already on the site, for the style:

{examples}
"""


def illustrate(model, root: Path, title: str, topic: str, folder: str, visual_idea: str,
               bullets: list[str], part_titles: list[str], retries: int = 1) -> tuple[str | None, list[str]]:
    """[LLM + code] Returns (svg, []) or (None, errors). Never sees the source text."""
    colour, soft = C[topic_key(topic, folder)]
    system = PROMPT.format(soft=soft, paper=PAPER, line=LINE, colour=colour, prefix=re.sub(r"\W", "", title)[:8].lower() or "v",
                           palette=", ".join(sorted(PALETTE)), examples=examples(root))
    request = (f"Page: {title}\nTopic colour: {colour} (soft {soft})\nVisual idea: {visual_idea or '(none: choose)'}\n"
               "In 30 seconds:\n" + "\n".join(f"- {b}" for b in bullets) +
               "\nParts: " + " · ".join(part_titles))
    messages = [SystemMessage(system), HumanMessage(request)]
    errors: list[str] = []
    for _ in range(retries + 1):
        svg = extract_svg(text_of(model.invoke(messages)))
        errors = validate_svg(svg)
        if not errors:
            return complete_svg(svg, title.replace('"', "'")), []
        messages = messages + [HumanMessage("This SVG cannot be used:\n- " + "\n- ".join(errors[:12]) +
                                            "\nAnswer again with a corrected SVG only.")]
    return None, errors


def main() -> None:
    """Try the illustrator alone on an existing note, without touching the site:

        python -m carnet_agent.illustrator agents/memory/short-term-memory.qmd --out /tmp/test.svg
    """
    import argparse

    from dotenv import load_dotenv

    from .config import ILLUSTRATOR_MODEL
    from .run import make_model
    from .site import split_front_matter

    parser = argparse.ArgumentParser(description="Draw the synthesis visual of one note (nothing is committed).")
    parser.add_argument("page", help="Path of the note, from the repository root.")
    parser.add_argument("--idea", default="", help="The visual idea (default: let the model choose).")
    parser.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "illustrator-test.svg"), help="Where to write the SVG.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    load_dotenv()
    front_matter, body = split_front_matter((root / args.page).read_text())
    in30 = re.search(r"::: \{\.in30\}\n(.*?)\n:::", body, re.S)
    bullets = re.findall(r"(?m)^- (.+)$", in30.group(1)) if in30 else [front_matter.get("subtitle", "")]
    parts = [h for h in re.findall(r"(?m)^## (.+)$", body) if not h.startswith(("Remember", "Sources", "Watch out"))]
    topic, folder = Path(args.page).parts[0], Path(args.page).parts[1]
    print(f"Illustrator model: {ILLUSTRATOR_MODEL}")
    svg, errors = illustrate(make_model(ILLUSTRATOR_MODEL), root, front_matter.get("title", args.page), topic, folder,
                             args.idea, bullets, parts)
    if svg:
        Path(args.out).write_text(svg)
        print(f"Valid SVG written to {args.out} ({len(svg.encode())} bytes).")
    else:
        print("No valid SVG after one retry:\n- " + "\n- ".join(errors))


if __name__ == "__main__":
    main()
