"""Synthesis visuals for notes added after vis.py was written, with the same primitives and palette.

    python reference/vis_extra.py      # writes assets/visuals/<slug>.svg
"""
from pathlib import Path

from vis import INK, LINE, MUTED, OK, PAPER, S


def what_skills_are():
    s = S("v-skills", "agents")
    s.text(124, 30, "THE SKILL FOLDER", 10, 700, MUTED, ls="0.08em")
    s.text(380, 30, "WHAT THE AGENT LOADS", 10, 700, MUTED, ls="0.08em")
    s.rect(24, 40, 200, 196, PAPER, s.c, rx=14, sw=1.6)
    s.mono(124, 62, "analyzing-campaign/", 11, s.c, weight=600)
    s.node(40, 74, 168, 62, "SKILL.md", "name · description · steps", "solid")
    s.rect(40, 148, 168, 34, PAPER, LINE, rx=8)
    s.mono(124, 169, "references/rules.md", 10, INK)
    s.rect(40, 192, 168, 30, PAPER, MUTED, rx=8, dash="4 4")
    s.text(124, 211, "scripts · assets", 11, 500, MUTED)
    rows = [("always", "name + description", "soft"), ("on a match", "the full SKILL.md", "white"),
            ("only if needed", "reference files, scripts", "dashed")]
    for i, (when, what, style) in enumerate(rows):
        y = 44 + i * 64
        s.node(264, y, 232, 50, what, None, style, 13)
        s.pill(272, y - 9, when, s.c if i < 2 else MUTED, PAPER, 10)
    s.arrow(208, 92, 260, 69, MUTED)
    s.arrow(208, 118, 260, 133, MUTED)
    s.arrow(208, 168, 260, 197, MUTED, dash="3 4")
    s.add(f'<path d="M24 252 L496 252" stroke="{LINE}" stroke-width="1"></path>')
    s.text(24, 278, "The skill is the workflow:", 12, 600, INK, "start")
    x = 196
    for label in ("tools", "MCP data", "sub-agents"):
        x += s.pill(x, 265, label, s.c, PAPER, 11) + 10
    return s.svg("A skill folder: SKILL.md with name and description always in context, full instructions loaded "
                 "on a match, reference files only when needed")


def designing_custom_skills():
    s = S("v-skilldesign", "agents")
    s.text(130, 30, "WRITE IT", 10, 700, MUTED, ls="0.08em")
    s.text(386, 30, "CHECK IT", 10, 700, MUTED, ls="0.08em")
    s.rect(24, 40, 212, 236, PAPER, LINE, rx=14)
    s.mono(130, 62, "SKILL.md", 12, s.c, weight=600)
    s.rect(40, 72, 180, 46, s.soft, s.soft, rx=8)
    s.mono(52, 90, "name: generating-…", 10, s.c, anchor="start")
    s.mono(52, 107, "description: what + when", 10, s.c, anchor="start")
    for i, step in enumerate(["read the input", "run checks in order", "edge cases · skip if…"]):
        y = 132 + i * 30
        s.circle(52, y + 9, 9, s.c, s.c)
        s.text(52, y + 13, str(i + 1), 10, 700, PAPER)
        s.text(70, y + 13, step, 12, 500, INK, "start")
    s.text(130, 236, "under 500 lines", 11, 500, MUTED)
    x = 40
    for label in ("scripts/", "references/", "assets/"):
        w = int(len(label) * 6.3 + 14)
        s.rect(x, 246, w, 20, PAPER, MUTED, rx=6, dash="3 3")
        s.mono(x + w / 2, 260, label, 10, MUTED)
        x += w + 6
    checks = [("Review skill", "skill-creator scores it", "solid"), ("Test harness", "files, formats, order", "white"),
              ("Across models", "every model you plan to use", "white")]
    for i, (a, b, style) in enumerate(checks):
        y = 44 + i * 70
        s.node(284, y, 204, 54, a, b, style)
        if i:
            s.arrow(386, y - 16, 386, y - 2, MUTED)
    s.arrow(236, 158, 278, 71, MUTED)
    s.check(470, 262, 10, OK)
    s.text(456, 266, "ready for production", 12, 600, OK, "end")
    return s.svg("Designing a custom skill: a short SKILL.md with name, description and ordered steps, extra files on "
                 "the side, then review, test harness and checks across models")


VISUALS = {"what-skills-are": what_skills_are, "designing-custom-skills": designing_custom_skills}

if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "assets" / "visuals"
    for slug, fn in VISUALS.items():
        svg = fn().replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" width="520" height="300" ', 1)
        (out / f"{slug}.svg").write_text(svg)
        print("wrote", slug)
