"""Synthesis visuals for every Carnet IA note: one SVG per note, 520x300 viewBox."""
from html import escape

INK = "#16202e"
MUTED = "#586174"
LINE = "#d9dee8"
PAPER = "#ffffff"
C = {
    "llms": ("#6741d9", "#f1edfe"),
    "agents": ("#2f54d6", "#eef2ff"),
    "eval": ("#c2255c", "#fdeef4"),
    "guard": ("#0f7a52", "#e8f6ef"),
    "tools": ("#0b7285", "#e6f5f8"),
}
WARN = "#b45309"
WARN_SOFT = "#fff3e2"
BAD = "#c92a2a"
BAD_SOFT = "#fdeceb"
OK = "#0f7a52"


class S:
    def __init__(self, vid, topic):
        self.vid, self.topic = vid, topic
        self.c, self.soft = C[topic]
        self.parts = []
        self.n = 0

    # ---------- primitives ----------
    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size=13, weight=500, fill=INK, anchor="middle", family="Inter, sans-serif", ls=None):
        extra = f' letter-spacing="{ls}"' if ls else ""
        self.add(f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{extra}>{escape(s)}</text>')

    def mono(self, x, y, s, size=11, fill=INK, anchor="middle", weight=500):
        self.text(x, y, s, size, weight, fill, anchor, "JetBrains Mono, monospace")

    def rect(self, x, y, w, h, fill=PAPER, stroke=LINE, rx=10, dash=None, sw=1.2):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}></rect>')

    def node(self, x, y, w, h, label, sub=None, style="white", size=13, color=None):
        c = color or self.c
        if style == "solid":
            self.rect(x, y, w, h, c, c)
            fg, sg = "#ffffff", "#ffffff"
        elif style == "soft":
            self.rect(x, y, w, h, self.soft if not color else PAPER, c)
            fg, sg = c, MUTED
        elif style == "dashed":
            self.rect(x, y, w, h, PAPER, MUTED, dash="4 4")
            fg, sg = MUTED, MUTED
        else:
            self.rect(x, y, w, h, PAPER, LINE)
            fg, sg = INK, MUTED
        cx = x + w / 2
        if sub:
            self.text(cx, y + h / 2 - 3, label, size, 600, fg)
            self.text(cx, y + h / 2 + 13, sub, 11, 400, sg)
        else:
            self.text(cx, y + h / 2 + 4.5, label, size, 600, fg)

    def pill(self, x, y, label, fg=None, bg=None, size=11, w=None, anchor="start"):
        fg = fg or self.c
        bg = bg or self.soft
        w = w or int(len(label) * size * 0.6 + 20)
        if anchor == "middle":
            x = x - w / 2
        h = size + 11
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h/2}" fill="{bg}"></rect>')
        self.text(x + w / 2, y + h / 2 + size * 0.36, label, size, 600, fg)
        return w

    def _marker(self, color):
        self.n += 1
        mid = f"{self.vid}-m{self.n}"
        self.add(f'<defs><marker id="{mid}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{color}"></path></marker></defs>')
        return mid

    def path(self, d, color=None, dash=None, sw=1.6, head=True):
        color = color or MUTED
        mk = f' marker-end="url(#{self._marker(color)})"' if head else ""
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linecap="round"{da}{mk}></path>')

    def arrow(self, x1, y1, x2, y2, color=None, dash=None, sw=1.6, head=True):
        self.path(f"M{x1} {y1} L{x2} {y2}", color, dash, sw, head)

    def circle(self, cx, cy, r, fill=PAPER, stroke=LINE, sw=1.4):
        self.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"></circle>')

    def check(self, cx, cy, r=9, color=OK):
        self.circle(cx, cy, r, color, color)
        self.add(f'<path d="M{cx-4} {cy} L{cx-1} {cy+3} L{cx+4.5} {cy-3.5}" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>')

    def cross(self, cx, cy, r=9, color=BAD):
        self.circle(cx, cy, r, color, color)
        self.add(f'<path d="M{cx-3.5} {cy-3.5} L{cx+3.5} {cy+3.5} M{cx+3.5} {cy-3.5} L{cx-3.5} {cy+3.5}" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"></path>')

    def warn(self, cx, cy, r=9):
        self.circle(cx, cy, r, WARN, WARN)
        self.add(f'<path d="M{cx} {cy-4.5} L{cx} {cy+0.5}" stroke="#fff" stroke-width="2" stroke-linecap="round"></path>')
        self.circle(cx, cy + 4, 1.2, "#fff", "#fff", 0.5)

    def lines(self, x, y, w, n, gap=8, color="#c9d0dc", widths=None):
        for i in range(n):
            ww = w * (widths[i % len(widths)] if widths else (1 if i < n - 1 else 0.6))
            self.add(f'<rect x="{x}" y="{y + i*gap}" width="{ww:.0f}" height="3" rx="1.5" fill="{color}"></rect>')

    def svg(self, label):
        body = "".join(self.parts)
        return (f'<svg viewBox="0 0 520 300" role="img" aria-label="{escape(label)}" '
                f'style="display: block; width: 100%; height: auto; background: {self.soft}">{body}</svg>')


# =====================================================================
# AGENTS
# =====================================================================
def what_is_an_agent():
    s = S("v-agent", "agents")
    s.pill(28, 40, "Question", INK, PAPER, 12, 92)
    s.node(214, 26, 140, 56, "Thought", "the LLM reasons", "solid")
    s.pill(408, 40, "Answer", "#fff", OK, 12, 84)
    s.arrow(120, 53, 210, 53)
    s.arrow(354, 53, 404, 53, OK)
    s.node(366, 192, 136, 56, "Action", "picks a tool")
    s.node(150, 192, 140, 56, "Observation", "your code runs it")
    s.path("M318 84 C 350 130, 405 145, 428 188", s.c)
    s.arrow(366, 220, 294, 220, s.c)
    s.path("M200 190 C 190 140, 220 110, 244 86", s.c)
    s.text(292, 150, "repeat until done", 12, 500, MUTED, family="Inter, sans-serif")
    s.text(292, 166, "(max_turns caps it)", 11, 400, MUTED)
    s.rect(26, 270, 10, 10, s.c, s.c, rx=3)
    s.text(42, 279, "the LLM decides", 11, 500, INK, "start")
    s.rect(150, 270, 10, 10, PAPER, LINE, rx=3)
    s.text(166, 279, "your code executes", 11, 500, INK, "start")
    return s.svg("The ReAct loop: Question, then Thought, Action, Observation repeated until an Answer")


def langgraph_levels():
    s = S("v-lg", "agents")
    names = [("Tool", "loop"), ("Router", ""), ("Plan, act,", "reflect"), ("Memory +", "a human"), ("Full", "system")]
    for i, (a, b) in enumerate(names):
        x = 22 + i * 98
        top = 206 - i * 37
        boss = i == 4
        fill = "#d9480f" if boss else (s.c if i >= 2 else PAPER)
        stroke = fill if fill != PAPER else LINE
        s.rect(x, top, 92, 282 - top, fill, stroke, rx=8)
        fg = "#ffffff" if fill != PAPER else s.c
        s.text(x + 46, top + 20, f"LEVEL {i+1}", 10, 700, fg, ls="0.08em")
        s.text(x + 46, top + 40, a, 13, 600, "#ffffff" if fill != PAPER else INK)
        if b:
            s.text(x + 46, top + 56, b, 13, 600, "#ffffff" if fill != PAPER else INK)
        # mini graph above the step: more nodes as the level grows
        k = i + 2
        span = (k - 1) * 13
        x0 = x + 46 - span / 2
        s.add(f'<path d="M{x0} {top-14} L{x0+span} {top-14}" stroke="{MUTED}" stroke-width="1.4"></path>')
        for j in range(k):
            s.circle(x0 + j * 13, top - 14, 4.2, s.c if j == 0 else PAPER, s.c, 1.4)
    s.circle(30, 36, 6, s.c, s.c)
    s.text(44, 40, "nodes do the work", 12, 500, INK, "start")
    s.arrow(24, 62, 38, 62, MUTED)
    s.text(44, 66, "edges pick what runs next", 12, 500, INK, "start")
    s.rect(24, 82, 14, 10, s.soft, s.c, rx=3)
    s.text(44, 92, "one shared state flows through", 12, 500, INK, "start")
    return s.svg("Five levels of agent design with LangGraph, from a tool loop to a full system")


def tools_search():
    s = S("v-tools", "agents")
    s.node(24, 30, 124, 60, "Model", "never runs code", "solid")
    s.node(372, 30, 124, 60, "Your code", "runs the tool")
    s.arrow(150, 50, 368, 50, s.c)
    s.mono(260, 42, '{ name, args }', 11, s.c)
    s.text(260, 28, "tool call", 11, 600, MUTED)
    s.arrow(370, 74, 152, 74, MUTED, dash="5 4")
    s.text(260, 92, "result goes back", 11, 500, MUTED)
    s.text(24, 132, "READY-MADE TOOLS", 10, 700, MUTED, "start", ls="0.08em")
    for i, (a, b) in enumerate([("Integration", "packages"), ("MCP", "servers"), ("Prompt hub", "treat as code")]):
        x = 24 + i * 160
        s.node(x, 142, 150, 56, a, b)
    s.rect(24, 222, 472, 52, PAPER, s.c, rx=26)
    s.circle(52, 248, 8, PAPER, s.c, 2)
    s.add(f'<path d="M58 254 L64 260" stroke="{s.c}" stroke-width="2.2" stroke-linecap="round"></path>')
    s.text(78, 245, "Agentic search", 13, 600, INK, "start")
    s.text(78, 262, "returns clean data, not pages of links", 11, 400, MUTED, "start")
    s.pill(380, 236, "best first tool", s.c, s.soft, 11, 104)
    return s.svg("Tool calling: the model emits a structured call, your code runs it; tools come from packages, MCP servers and hubs; agentic search")


def memory_overview():
    s = S("v-memov", "agents")
    s.text(110, 34, "SHORT-TERM", 10, 700, MUTED, ls="0.08em")
    s.text(358, 34, "LONG-TERM", 10, 700, MUTED, ls="0.08em")
    s.add(f'<path d="M210 20 L210 250" stroke="{LINE}" stroke-width="1.2" stroke-dasharray="3 4"></path>')
    s.node(24, 48, 172, 62, "Checkpointer", "one conversation", "solid")
    s.node(270, 48, 176, 62, "Store", "across all conversations", "solid")
    # thread bubbles under the checkpointer
    s.pill(24, 128, "thread_id", s.c, PAPER, 11, 80)
    for i, w in enumerate([120, 92, 140]):
        x = 24 if i % 2 == 0 else 196 - w
        s.rect(x, 160 + i * 26, w, 18, PAPER if i % 2 == 0 else s.soft, LINE, rx=9)
    # tree to the three kinds
    s.add(f'<path d="M358 110 L358 136 M263 136 L453 136" stroke="{MUTED}" stroke-width="1.4" fill="none"></path>')
    for x in (263, 358, 453):
        s.arrow(x, 136, x, 160, MUTED)
    for x, (a, b) in zip((220, 315, 410), [("Semantic", "facts"), ("Episodic", "examples"), ("Procedural", "how to act")]):
        s.node(x, 164, 86, 62, a, b, "white", 12)
    s.arrow(24, 266, 496, 266, MUTED)
    s.text(110, 288, "this chat", 11, 500, MUTED)
    s.text(358, 288, "every chat", 11, 500, MUTED)
    return s.svg("Agent memory: short-term with the checkpointer, long-term with the store, split into semantic, episodic and procedural")


def short_term():
    s = S("v-short", "agents")
    s.pill(24, 22, "thread_id = \"alice-1\"", s.c, PAPER, 11)
    s.add(f'<path d="M50 120 L430 120" stroke="{s.c}" stroke-width="2.5"></path>')
    for i, x in enumerate([70, 170, 270, 370]):
        s.rect(x - 38, 56, 76, 40, PAPER, LINE, rx=8)
        s.lines(x - 28, 66, 56, 3, 8)
        s.add(f'<path d="M{x} 96 L{x} 112" stroke="{LINE}" stroke-width="1.2"></path>')
        s.circle(x, 120, 8, s.c, s.c)
        s.text(x, 146, f"step {i+1}", 11, 500, MUTED)
    s.arrow(430, 120, 488, 120, OK, sw=2)
    s.text(462, 106, "resume", 11, 600, OK)
    s.text(260, 172, "same id → picks up where it left off, whole history included", 12, 500, INK)
    s.add(f'<path d="M24 196 L496 196" stroke="{LINE}" stroke-width="1"></path>')
    s.pill(24, 214, "thread_id = \"bob-1\"", MUTED, PAPER, 11)
    s.add(f'<path d="M50 262 L200 262" stroke="{LINE}" stroke-width="2.5" stroke-dasharray="4 5"></path>')
    s.circle(70, 262, 8, PAPER, MUTED, 1.6)
    s.text(220, 258, "new id → starts from scratch", 12, 500, MUTED, "start")
    s.text(220, 274, "also what makes pause & resume possible", 11, 400, MUTED, "start")
    return s.svg("Short-term memory: a checkpointer saves state after every step under a thread id")


def long_term():
    s = S("v-long", "agents")
    s.rect(24, 22, 196, 256, PAPER, s.c, rx=14, sw=1.6)
    s.text(122, 46, "Store", 15, 700, s.c)
    s.text(122, 62, "namespaced · searchable by meaning", 10, 400, MUTED)
    rows = [("facts", "Facts", "saved & searched", "through tools"),
            ("examples", "Examples", "past decisions put", "into the prompt"),
            ("instructions", "Instructions", "a prompt rewritten", "from feedback")]
    for i, (ns, title, l1, l2) in enumerate(rows):
        y = 80 + i * 64
        s.rect(38, y, 168, 50, s.soft, s.soft, rx=8)
        s.rect(108, y + 8, 28, 5, s.c, s.c, rx=2.5)
        s.mono(122, y + 36, f"(\"alice\", \"{ns}\")", 10, s.c)
        s.arrow(208, y + 25, 256, y + 25, MUTED)
        s.rect(260, y, 236, 50, PAPER, LINE, rx=10)
        s.text(276, y + 21, title, 13, 600, INK, "start")
        s.text(276, y + 38, f"{l1} {l2}", 11, 400, MUTED, "start")
    s.text(378, 290, "running example: an email assistant that improves", 10, 400, MUTED)
    return s.svg("Long-term memory: one store holding facts, examples and instructions")


def control():
    s = S("v-ctrl", "agents")
    xs = [56, 152, 248, 344, 440]
    labels = ["plan", "search", "draft", "send email", "done"]
    s.add(f'<path d="M56 96 L440 96" stroke="{s.c}" stroke-width="2.5"></path>')
    for i, (x, l) in enumerate(zip(xs, labels)):
        s.circle(x, 96, 9, s.c if i < 3 else PAPER, s.c, 2)
        s.text(x, 124, l, 11, 500, INK if i < 4 else MUTED)
    # live stream badge
    s.pill(24, 20, "● streaming steps & tokens", s.c, PAPER, 11)
    # pause gate before send email
    s.rect(330, 44, 28, 34, WARN_SOFT, WARN, rx=6)
    s.add(f'<path d="M340 53 L340 69 M348 53 L348 69" stroke="{WARN}" stroke-width="2.6" stroke-linecap="round"></path>')
    s.text(364, 58, "approve?", 11, 600, WARN, "start")
    # edit pencil on draft
    s.add(f'<path d="M238 70 L252 56 L258 62 L244 76 L236 78 Z" fill="{PAPER}" stroke="{s.c}" stroke-width="1.6" stroke-linejoin="round"></path>')
    # rewind arc
    s.path("M344 140 C 320 176, 176 176, 154 142", MUTED, dash="5 4")
    s.text(250, 184, "time travel: replay from step 2", 11, 500, MUTED)
    btn = [("▶", "Watch", "streaming"), ("❚❚", "Pause", "human in the loop"), ("✎", "Edit", "change the state"), ("◀◀", "Rewind", "time travel")]
    for i, (ic, a, b) in enumerate(btn):
        x = 24 + i * 120
        s.rect(x, 204, 112, 66, PAPER, LINE, rx=12)
        s.text(x + 22, 242, ic, 14, 700, s.c)
        s.text(x + 40, 234, a, 13, 600, INK, "start")
        s.text(x + 40, 251, b, 10, 400, MUTED, "start")
    s.text(260, 292, "all four rely on the checkpointer", 11, 500, MUTED)
    return s.svg("Controlling a running agent: watch, pause, edit and rewind, on top of saved checkpoints")


# =====================================================================
# EVALUATING AGENTS
# =====================================================================
def evaluating_agents():
    s = S("v-evag", "eval")
    s.rect(24, 24, 190, 208, PAPER, LINE, rx=14)
    s.text(40, 46, "AGENT", 10, 700, MUTED, "start", ls="0.08em")
    for i, (a) in enumerate(["Router", "Skills", "Tools"]):
        s.node(40, 58 + i * 56, 158, 38, a, None, "soft" if i else "white", 12)
        if i < 2:
            s.arrow(119, 96 + i * 56, 119, 112 + i * 56, MUTED)
    # traces bar
    s.text(24, 254, "TRACE", 10, 700, MUTED, "start", ls="0.08em")
    for x, w, c in [(70, 140, s.soft), (70, 60, s.c), (134, 46, "#f3a6c2"), (184, 26, s.c)]:
        s.rect(x, 244, w, 12, c, c, rx=4)
    s.rect(24, 266, 190, 8, LINE, LINE, rx=4)
    steps = [("1", "Evaluate each part", "router, skills, tools"),
             ("2", "Evaluate the trajectory", "the path, not only the answer"),
             ("3", "Collect failures", "into a reusable test set"),
             ("4", "Experiment & monitor", "CI, staged evals, red teaming")]
    for i, (n, a, b) in enumerate(steps):
        y = 24 + i * 66
        s.circle(270, y + 24, 14, s.c if i == 0 else PAPER, s.c, 1.6)
        s.text(270, y + 29, n, 12, 700, "#fff" if i == 0 else s.c)
        s.text(294, y + 20, a, 13, 600, INK, "start")
        s.text(294, y + 37, b, 11, 400, MUTED, "start")
        if i < 3:
            s.add(f'<path d="M270 {y+40} L270 {y+64}" stroke="{LINE}" stroke-width="1.6"></path>')
    return s.svg("Evaluating AI agents: break the agent into parts, read traces, judge parts and trajectories, then experiment and monitor")


def eval_workflow():
    import math
    s = S("v-evwf", "eval")
    cx, cy, rx, ry = 260, 152, 186, 102
    labels = [("Traces", "what really happened"), ("Requirements", "from rules & failures"), ("Tests + rubric", "reusable cases"),
              ("Automate", "judge at scale"), ("Improve", "then look again")]
    angles = [-90, -18, 54, 126, 198]
    pts = [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a))) for a in angles]
    for i in range(5):
        a0 = angles[i] + 24
        a1 = angles[(i + 1) % 5] - 24 + (360 if i == 4 else 0)
        ps = []
        for k in range(13):
            a = math.radians(a0 + (a1 - a0) * k / 12)
            ps.append(f"{cx + rx*math.cos(a):.1f} {cy + ry*math.sin(a):.1f}")
        s.path("M" + " L".join(ps), s.c, sw=1.8)
    for i, ((x, y), (a, b)) in enumerate(zip(pts, labels)):
        s.node(x - 64, y - 24, 128, 48, a, b, "solid" if i == 0 else "white", 12)
    s.text(cx, cy - 4, "a loop,", 15, 700, s.c)
    s.text(cx, cy + 15, "not a one-time gate", 12, 500, MUTED)
    return s.svg("Agent evaluation workflow: traces, requirements, tests and rubric, automate, improve, and back to traces")


def traces():
    s = S("v-trace", "eval")
    s.text(24, 30, "one trace = one run", 12, 600, INK, "start")
    s.text(496, 30, "time →", 11, 500, MUTED, "end")
    rows = [(0, "agent.run", 0, 1.0, "root"),
            (1, "llm · plan", 0.02, 0.22, "llm"),
            (1, "tool · search_products", 0.25, 0.30, "bad"),
            (1, "llm · answer", 0.57, 0.28, "llm"),
            (2, "tool · get_stock", 0.88, 0.1, "tool")]
    x0, x1 = 214, 496
    for i, (lvl, name, st, ln, k) in enumerate(rows):
        y = 48 + i * 36
        s.mono(28 + lvl * 16, y + 15, ("└ " if lvl else "") + name, 10.5, INK, "start")
        col = {"root": s.soft, "llm": s.c, "tool": "#f3a6c2", "bad": BAD}[k]
        s.rect(x0 + (x1 - x0) * st, y + 4, (x1 - x0) * ln, 16, col, col, rx=5)
    # annotation on the bad span
    bx = x0 + (x1 - x0) * 0.25
    s.rect(bx - 4, 150, 150, 26, BAD_SOFT, BAD, rx=8)
    s.cross(bx + 10, 163, 7)
    s.text(bx + 24, 167, "label: wrong tool", 11, 600, BAD, "start")
    s.add(f'<path d="M{bx+40} 148 L{bx+40} 140" stroke="{BAD}" stroke-width="1.4"></path>')
    s.text(24, 250, "THEN", 10, 700, MUTED, "start", ls="0.08em")
    x = 66
    for i, l in enumerate(["annotate the run", "group repeats", "rank: frequency × severity"]):
        w = s.pill(x, 236, l, s.c, PAPER, 11)
        if i < 2:
            s.arrow(x + w + 4, 247, x + w + 20, 247, MUTED)
        x += w + 26
    s.text(24, 286, "a span records inputs, outputs, timing and errors", 11, 400, MUTED, "start")
    return s.svg("A trace as a tree of spans on a timeline, with one span labelled as a failure")


def action_eval():
    s = S("v-act", "eval")
    calls = [("lookup_order", "id=42", "right tool, right args", "ok"),
             ("issue_refund", "amount=?", "missing info: should ask", "warn"),
             ("delete_account", "user=42", "forbidden action", "bad")]
    for i, (fn, arg, verdict, k) in enumerate(calls):
        x = 24 + i * 166
        s.rect(x, 30, 150, 92, PAPER, LINE, rx=12)
        s.circle(x + 20, 50, 11, s.soft, s.soft)
        s.text(x + 20, 54.5, str(i + 1), 11, 700, s.c)
        s.mono(x + 38, 54, fn + "(", 11, INK, "start", 600)
        s.mono(x + 38, 74, arg, 11, s.c, "start")
        s.mono(x + 38, 94, ")", 11, INK, "start", 600)
        if i < 2:
            s.arrow(x + 152, 76, x + 164, 76, MUTED)
        y = 146
        (s.check if k == "ok" else s.warn if k == "warn" else s.cross)(x + 14, y)
        s.text(x + 30, y + 4, verdict, 11, 600, {"ok": OK, "warn": WARN, "bad": BAD}[k], "start")
    s.add(f'<path d="M24 178 L496 178" stroke="{LINE}" stroke-width="1"></path>')
    s.text(24, 204, "EXPECTED ORDER", 10, 700, MUTED, "start", ls="0.08em")
    x = 136
    for i, l in enumerate(["lookup", "confirm", "refund"]):
        w = s.pill(x, 190, l, "#fff", s.c, 11)
        if i < 2:
            s.arrow(x + w + 4, 201, x + w + 22, 201, s.c)
        x += w + 28
    x = 24
    for q in ["Right tool?", "Right arguments?", "Required / forbidden?", "Right sequence?"]:
        w = s.pill(x, 240, q, INK, PAPER, 11)
        x += w + 8
    return s.svg("Tool-use evaluation: judge each call's tool, arguments, required and forbidden actions, and order")


def improvement():
    s = S("v-impr", "eval")
    s.text(24, 30, "WHERE TO INTERVENE", 10, 700, MUTED, "start", ls="0.08em")
    layers = ["Data", "Prompt", "Tools & workflow", "Model", "Sampling"]
    for i, l in enumerate(layers):
        y = 42 + i * 46
        w = 150 + i * 14
        s.rect(24, y, w, 36, s.c if i == 0 else PAPER, s.c if i == 0 else LINE, rx=8)
        s.text(40, y + 23, f"{i+1}", 12, 700, "#fff" if i == 0 else s.c, "start")
        s.text(58, y + 23, l, 13, 600, "#fff" if i == 0 else INK, "start")
    s.text(24, 290, "start with the smallest layer that fits", 11, 500, MUTED, "start")
    # A/B by category
    s.text(286, 30, "BASELINE VS CANDIDATE", 10, 700, MUTED, "start", ls="0.08em")
    cats = [("billing", 0.55, 0.78, False), ("returns", 0.6, 0.72, False), ("shipping", 0.7, 0.48, True)]
    for i, (c, a, b, reg) in enumerate(cats):
        y = 50 + i * 66
        s.text(286, y + 12, c, 11, 600, INK, "start")
        s.rect(286, y + 20, 200 * a, 12, "#c9d0dc", "#c9d0dc", rx=4)
        s.rect(286, y + 36, 200 * b, 12, BAD if reg else s.c, BAD if reg else s.c, rx=4)
        if reg:
            s.text(286 + 200 * b + 8, y + 46, "regression", 11, 700, BAD, "start")
    s.rect(286, 252, 10, 10, "#c9d0dc", "#c9d0dc", rx=3)
    s.text(302, 261, "baseline", 11, 500, MUTED, "start")
    s.rect(370, 252, 10, 10, s.c, s.c, rx=3)
    s.text(386, 261, "candidate", 11, 500, MUTED, "start")
    s.text(286, 290, "one change at a time · read each category", 11, 500, MUTED, "start")
    return s.svg("Improvement experiments: an intervention hierarchy and a baseline versus candidate comparison by category")


def production():
    s = S("v-prod", "eval")
    s.rect(24, 50, 196, 196, PAPER, LINE, rx=14)
    s.text(122, 76, "Production", 14, 700, INK)
    s.text(122, 93, "messy, real traffic", 11, 400, MUTED)
    for i, l in enumerate(["monitoring", "manual review", "user feedback", "A/B tests"]):
        s.pill(122, 108 + i * 32, l, s.c, s.soft, 11, 140, "middle")
    s.rect(300, 50, 196, 196, PAPER, LINE, rx=14)
    s.text(398, 76, "Offline benchmark", 14, 700, INK)
    s.text(398, 93, "stable, comparable", 11, 400, MUTED)
    for i in range(4):
        y = 112 + i * 28
        new = i == 3
        s.rect(330, y, 136, 20, s.c if new else s.soft, s.c if new else s.soft, rx=6)
        s.text(398, y + 14, "new regression test" if new else f"case {i+1}", 10.5, 600, "#fff" if new else s.c)
    s.path("M220 112 C 250 80, 270 80, 298 112", BAD, sw=1.8)
    s.text(260, 40, "failure found", 11, 700, BAD)
    s.text(260, 54, "→ becomes a test", 11, 500, MUTED)
    s.path("M298 196 C 270 228, 250 228, 222 196", s.c, sw=1.8)
    s.text(260, 254, "every new version", 11, 700, s.c)
    s.text(260, 268, "checked before release", 11, 500, MUTED)
    s.text(260, 292, "old bugs never come back", 11, 600, INK)
    return s.svg("Production failures turned into regression tests in the offline benchmark, in a closed loop")


def agent_based():
    s = S("v-agb", "eval")
    # human
    s.circle(56, 52, 12, s.soft, s.c, 1.6)
    s.add(f'<path d="M36 86 C 36 70, 76 70, 76 86" fill="{s.soft}" stroke="{s.c}" stroke-width="1.6"></path>')
    s.text(90, 54, "Human", 13, 700, INK, "start")
    s.text(90, 71, "sets goals, decides what “good” means", 11, 400, MUTED, "start")
    s.arrow(56, 96, 56, 128, MUTED)
    s.node(24, 132, 150, 58, "Agent judge", "reads trajectories", "solid")
    s.node(24, 222, 150, 52, "Agent under test", None, "white", 12)
    s.arrow(99, 220, 99, 194, s.c, dash="4 4")
    s.text(112, 210, "trace", 10, 600, s.c, "start")
    s.text(306, 112, "WHERE DID IT FAIL?", 10, 700, MUTED, ls="0.08em")
    for i, (a, b) in enumerate([("Harness", "loop, tools, orchestration"), ("Context", "what it was given"), ("Model", "the LLM itself")]):
        y = 124 + i * 52
        s.rect(220, y, 172, 44, PAPER if i else s.soft, LINE if i else s.c, rx=8)
        s.text(234, y + 19, a, 13, 600, INK, "start")
        s.text(234, y + 35, b, 10.5, 400, MUTED, "start")
    s.arrow(176, 160, 216, 160, MUTED)
    s.rect(408, 124, 88, 148, PAPER, LINE, rx=10, dash="4 4")
    s.text(452, 148, "multi-", 11, 600, INK)
    s.text(452, 162, "agent", 11, 600, INK)
    for j in range(3):
        s.circle(452, 188 + j * 26, 8, s.soft, s.c, 1.4)
    s.text(452, 290, "the whole setup", 10, 500, MUTED)
    return s.svg("Agent-based evaluation: a human sets goals, an agent judge reads trajectories, failures split into harness, context and model")


# =====================================================================
# EVALUATING LLMS
# =====================================================================
def benchmarks():
    s = S("v-bench", "eval")
    s.node(24, 110, 112, 72, "Requirement", "one rule", "solid")
    s.pill(24, 214, "real failures", BAD, BAD_SOFT, 11, 112)
    s.pill(24, 244, "bug reports", WARN, WARN_SOFT, 11, 112)
    for i in range(5):
        y = 36 + i * 46
        s.rect(176, y, 128, 36, PAPER, LINE, rx=8)
        s.rect(186, y + 9, 30, 5, s.c, s.c, rx=2.5)
        s.rect(222, y + 9, 40, 5, "#f3a6c2", "#f3a6c2", rx=2.5)
        s.rect(268, y + 9, 26, 5, OK, OK, rx=2.5)
        s.lines(186, y + 21, 90, 1, 8, "#dfe3ea")
        s.arrow(138, 146, 172, y + 18, LINE, sw=1.2)
    s.text(240, 28, "request · context · expected", 10, 600, MUTED)
    s.add(f'<path d="M318 46 L372 110 L372 186 L318 250" fill="none" stroke="{MUTED}" stroke-width="1.4" stroke-dasharray="4 4"></path>')
    s.text(345, 268, "dedupe,", 11, 500, MUTED)
    s.text(345, 283, "keep hard ones", 11, 500, MUTED)
    s.arrow(374, 148, 394, 148, s.c, sw=1.8)
    # cylinder
    s.add(f'<path d="M398 112 L398 196 C 398 212, 494 212, 494 196 L494 112" fill="{PAPER}" stroke="{s.c}" stroke-width="1.6"></path>')
    s.add(f'<ellipse cx="446" cy="112" rx="48" ry="14" fill="{s.soft}" stroke="{s.c}" stroke-width="1.6"></ellipse>')
    s.text(446, 160, "Benchmark", 13, 700, INK)
    s.text(446, 177, "fixed, versioned", 11, 400, MUTED)
    s.text(446, 234, "compare versions fairly", 11, 500, MUTED)
    return s.svg("From requirements and failures to many test cases, filtered into a stable benchmark")


def judges():
    s = S("v-judge", "eval")
    s.node(24, 30, 150, 52, "Judge model", "swappable")
    s.rect(24, 98, 150, 124, PAPER, s.c, rx=10)
    s.text(40, 118, "Rubric", 13, 700, s.c, "start")
    for i, l in enumerate(["Role", "Criteria", "Inputs", "Labeled examples", "Output instructions"]):
        s.text(40, 138 + i * 17, f"{i+1}  {l}", 11, 500, INK, "start")
    s.node(24, 238, 150, 44, "Run data", "trace + evidence")
    for y in (56, 160, 260):
        s.path(f"M176 {y} C 210 {y}, 210 156, 240 156", MUTED, sw=1.4)
    s.rect(244, 116, 100, 80, s.c, s.c, rx=40)
    s.text(294, 152, "Judge", 14, 700, "#fff")
    s.text(294, 170, "evaluates", 11, 500, "#fff")
    s.arrow(346, 156, 372, 156, s.c, sw=1.8)
    s.rect(376, 104, 120, 104, PAPER, LINE, rx=10)
    s.pill(390, 118, "pass", "#fff", OK, 11, 46)
    s.text(390, 162, "explanation", 11, 600, INK, "start")
    s.lines(390, 172, 90, 3, 8)
    s.text(436, 236, "review the scores,", 11, 500, MUTED)
    s.text(436, 251, "not just the average", 11, 500, MUTED)
    return s.svg("An LLM judge combines a judge model, a five-part rubric and run data into a label and an explanation")


def validating():
    s = S("v-valid", "eval")
    s.text(24, 28, "SPLIT YOUR LABELED CASES", 10, 700, MUTED, "start", ls="0.08em")
    s.rect(24, 38, 300, 22, s.soft, s.soft, rx=6)
    s.rect(324, 38, 172, 22, s.c, s.c, rx=6)
    s.text(174, 53, "dev: tune the judge", 11, 600, s.c)
    s.text(410, 53, "held-out: test it", 11, 600, "#fff")
    # matrix
    ox, oy, cw, ch = 120, 108, 104, 64
    s.text(ox + cw, 98, "HUMAN LABEL", 10, 700, MUTED, ls="0.08em")
    s.text(ox + cw / 2, oy + ch * 2 + 18, "fail", 11, 500, MUTED)
    s.text(ox + cw * 1.5, oy + ch * 2 + 18, "pass", 11, 500, MUTED)
    s.text(62, oy + ch / 2 + 4, "judge: fail", 11, 500, MUTED)
    s.text(62, oy + ch * 1.5 + 4, "judge: pass", 11, 500, MUTED)
    cells = [(0, 0, "agree", s.soft, s.c), (1, 0, "false alarm", BAD_SOFT, BAD), (0, 1, "missed", BAD_SOFT, BAD), (1, 1, "agree", s.soft, s.c)]
    for cx_, cy_, l, bg, fg in cells:
        s.rect(ox + cx_ * cw + 3, oy + cy_ * ch + 3, cw - 6, ch - 6, bg, bg, rx=8)
        s.text(ox + cx_ * cw + cw / 2, oy + cy_ * ch + ch / 2 + 4, l, 12, 600, fg)
    for i, (a, b) in enumerate([("Precision", "are its fails real?"), ("Recall", "does it catch them?"), ("Kappa", "agreement beyond chance")]):
        y = 104 + i * 46
        s.text(352, y + 14, a, 13, 700, INK, "start")
        s.text(352, y + 31, b, 11, 400, MUTED, "start")
    s.rect(24, 262, 472, 28, WARN_SOFT, WARN_SOFT, rx=8)
    s.text(260, 281, "read each disagreement: is the judge wrong, or the label?", 11, 600, WARN)
    return s.svg("Validating an evaluator: a held-out split, a confusion matrix against human labels, precision, recall and kappa")


def red_team():
    s = S("v-red", "eval")
    s.text(24, 28, "MANUAL ATTACKS", 10, 700, MUTED, "start", ls="0.08em")
    attacks = ["completion bait", "biased question", "instruction injection", "prompt-format exploit"]
    for i, a in enumerate(attacks):
        y = 42 + i * 44
        s.pill(24, y, a, BAD, BAD_SOFT, 11, 152)
        s.path(f"M180 {y+11} C 200 {y+11}, 205 150, 222 150", BAD, sw=1.3)
    # shield app
    s.add(f'<path d="M262 92 L310 106 L310 152 C 310 182, 286 200, 262 210 C 238 200, 214 182, 214 152 L214 106 Z" fill="{PAPER}" stroke="{INK}" stroke-width="1.6"></path>')
    s.text(262, 150, "LLM app", 12, 700, INK)
    s.text(262, 166, "under test", 10, 500, MUTED)
    s.text(410, 28, "AUTOMATED", 10, 700, MUTED, ls="0.08em")
    s.node(340, 40, 156, 50, "Prompt-library scan", "repeat: outputs vary", "white", 12)
    s.node(340, 104, 156, 50, "LLM writes attacks", "adversarial questions", "white", 12)
    s.node(340, 168, 156, 50, "LLM judges outputs", "flags policy failures", "white", 12)
    for y in (65, 129, 193):
        s.arrow(338, y, 314, 150 + (y - 129) * 0.3, MUTED, sw=1.3)
    s.rect(24, 236, 472, 44, s.c, s.c, rx=12)
    s.text(260, 263, "→ a list of real weaknesses to fix, then scan again", 13, 600, "#fff")
    return s.svg("Red teaming: manual attacks and automated scans against an LLM app produce a list of weaknesses")


# =====================================================================
# GUARDRAILS
# =====================================================================
def guardrails_apps():
    s = S("v-gapp", "guard")
    s.rect(24, 22, 472, 40, PAPER, LINE, rx=10, dash="4 4")
    s.text(260, 47, "prompting, RAG, RLHF, fine-tuning help — but never guarantee", 11.5, 500, MUTED)
    xs = [(24, 70, "Input", "white"), (118, 92, "Validator", "solid"), (234, 70, "LLM", "white"), (328, 92, "Validator", "solid"), (444, 52, "", "")]
    s.node(24, 104, 74, 54, "Input")
    s.node(116, 98, 92, 66, "Validator", "input check", "solid", 12)
    s.node(226, 104, 74, 54, "LLM")
    s.node(318, 98, 92, 66, "Validator", "output check", "solid", 12)
    s.node(428, 104, 68, 54, "Reply", None, "white", 12)
    for a, b in [(98, 114), (208, 224), (300, 316), (410, 426)]:
        s.arrow(a, 131, b, 131, s.c)
    for x in (162, 364):
        s.add(f'<path d="M{x} 166 L{x} 188" stroke="{LINE}" stroke-width="1.4"></path>')
    for x in (162, 364):
        for j, (l, fg, bg) in enumerate([("block", BAD, BAD_SOFT), ("fix", s.c, PAPER), ("re-ask", WARN, WARN_SOFT)]):
            s.pill(x, 192 + j * 26, l, fg, bg, 10.5, 64, "middle")
    s.text(260, 290, "rules, regex or small ML models · checked at inference time", 11, 500, MUTED)
    return s.svg("Guardrails: validators check the input before the LLM and the output after it, and can block, fix or re-ask")


def custom_guardrails():
    s = S("v-gcust", "guard")
    s.node(24, 118, 80, 60, "App", "OpenAI-style client", "white", 12)
    s.rect(128, 30, 264, 240, PAPER, s.c, rx=16, sw=1.6)
    s.text(146, 54, "Guardrails Server", 13, 700, s.c, "start")
    s.text(146, 70, "sits in front of the LLM API", 10.5, 400, MUTED, "start")
    s.rect(146, 86, 228, 166, s.soft, s.soft, rx=12)
    s.text(162, 108, "Guard", 13, 700, INK, "start")
    s.text(162, 124, "names the policy + what to do on fail", 10, 400, MUTED, "start")
    for i, (a, b) in enumerate([("Validator", "pass / fail + message"), ("Validator", "optional fixed value")]):
        y = 138 + i * 54
        s.rect(162, y, 196, 44, PAPER, LINE, rx=8)
        s.text(176, y + 19, a, 12, 600, INK, "start")
        s.text(176, y + 34, b, 10.5, 400, MUTED, "start")
    s.node(416, 118, 80, 60, "LLM API")
    s.arrow(106, 148, 124, 148, s.c)
    s.arrow(394, 148, 412, 148, s.c)
    s.text(260, 292, "write the check → wrap it in a guard → route calls through the server", 11, 500, MUTED)
    return s.svg("Custom guardrails: validators inside a guard, inside a Guardrails Server between the app and the LLM API")


def competitor():
    s = S("v-comp", "guard")
    s.rect(24, 22, 472, 46, PAPER, LINE, rx=10)
    s.text(40, 50, "Model output:", 11, 600, MUTED, "start")
    s.text(130, 50, "“For mortgages, ", 12.5, 500, INK, "start")
    s.rect(236, 34, 46, 22, BAD_SOFT, BAD, rx=5)
    s.text(259, 50, "JPMC", 12, 700, BAD)
    s.text(288, 50, "may suit you better.”", 12.5, 500, INK, "start")
    stages = [("1", "Exact match", "“JPMorgan” in text?", "no match", "warn"),
              ("2", "NER", "extract entities", "found “JPMC”", "warn"),
              ("3", "Similarity", "embedding vs list", "≈ JPMorgan → fail", "bad")]
    for i, (n, a, b, r, k) in enumerate(stages):
        x = 24 + i * 164
        s.rect(x, 94, 144, 74, PAPER, LINE if i < 2 else BAD, rx=10)
        s.text(x + 14, 116, n, 11, 700, s.c, "start")
        s.text(x + 28, 116, a, 13, 600, INK, "start")
        s.text(x + 14, 134, b, 10.5, 400, MUTED, "start")
        (s.warn if k == "warn" else s.cross)(x + 22, 152, 7)
        s.text(x + 34, 156, r, 10.5, 600, WARN if k == "warn" else BAD, "start")
        if i < 2:
            s.arrow(x + 146, 131, x + 162, 131, MUTED)
    s.text(260, 192, "cheap checks first, smarter checks only when needed", 11, 500, MUTED)
    s.arrow(260, 200, 260, 220, s.c)
    s.rect(24, 226, 472, 46, s.soft, s.c, rx=10)
    s.text(40, 254, "User sees:", 11, 600, MUTED, "start")
    s.text(116, 254, "“For mortgages, here is what we offer…”", 12.5, 500, INK, "start")
    return s.svg("Competitor-mention guardrail: exact match, then NER, then embedding similarity catch JPMC as JPMorgan")


def hallucination():
    s = S("v-hall", "guard")
    s.rect(24, 30, 170, 230, PAPER, LINE, rx=12)
    s.text(40, 54, "Sources", 13, 700, INK, "start")
    s.text(40, 70, "retrieved context", 10.5, 400, MUTED, "start")
    for i in range(3):
        s.rect(40, 88 + i * 58, 138, 44, "#f4f6f9", "#f4f6f9", rx=6)
        s.lines(50, 98 + i * 58, 116, 3, 9)
    s.rect(326, 30, 170, 230, PAPER, LINE, rx=12)
    s.text(342, 54, "Answer", 13, 700, INK, "start")
    s.text(342, 70, "split into claims", 10.5, 400, MUTED, "start")
    verdicts = [("ok", "entailed"), ("ok", "entailed"), ("bad", "not supported")]
    for i, (k, l) in enumerate(verdicts):
        y = 88 + i * 58
        bg = BAD_SOFT if k == "bad" else s.soft
        s.rect(342, y, 138, 44, bg, bg, rx=6)
        s.lines(352, y + 10, 100, 3, 9, BAD if k == "bad" else "#9fd3bb")
        s.arrow(324, y + 22, 198, y + 22 + (0 if i < 2 else -58), s.c if k == "ok" else BAD, dash=None if k == "ok" else "4 4", sw=1.4)
        (s.check if k == "ok" else s.cross)(260, y + 22 + (0 if i < 2 else -29), 9)
        s.text(260, y + 44 + (0 if i < 2 else -29), l, 10.5, 600, OK if k == "ok" else BAD)
    s.pill(260, 270, "NLI: does the source support each claim?", s.c, PAPER, 11, 260, "middle")
    return s.svg("Hallucination guardrail: each claim of the answer is checked by NLI against the sources; unsupported claims are blocked")


def pii():
    s = S("v-pii", "guard")
    s.text(24, 30, "INPUT", 10, 700, MUTED, "start", ls="0.08em")
    s.rect(24, 40, 472, 48, PAPER, LINE, rx=10)
    s.text(40, 69, "Hi, I'm", 12.5, 500, INK, "start")
    s.rect(88, 53, 72, 22, WARN_SOFT, WARN, rx=5)
    s.text(124, 69, "Jane Doe", 12, 600, WARN)
    s.text(166, 69, ", call me on", 12.5, 500, INK, "start")
    s.rect(244, 53, 110, 22, WARN_SOFT, WARN, rx=5)
    s.text(299, 69, "06 12 34 56 78", 11.5, 600, WARN)
    s.arrow(260, 92, 260, 112, s.c)
    s.node(170, 116, 180, 48, "Detect & redact", "Presidio + your own rules", "solid", 12)
    s.arrow(260, 166, 260, 186, s.c)
    s.rect(24, 190, 472, 48, s.soft, s.c, rx=10)
    s.text(40, 219, "Hi, I'm", 12.5, 500, INK, "start")
    s.mono(90, 219, "<PERSON>", 11.5, s.c, "start", 700)
    s.text(162, 219, ", call me on", 12.5, 500, INK, "start")
    s.mono(240, 219, "<PHONE_NUMBER>", 11.5, s.c, "start", 700)
    for i, (a, b) in enumerate([("Input guard", "before the LLM sees it"), ("Output guard", "while the reply streams")]):
        x = 24 + i * 244
        s.check(x + 10, 268, 8)
        s.text(x + 24, 266, a, 12, 700, INK, "start")
        s.text(x + 24, 282, b, 10.5, 400, MUTED, "start")
    return s.svg("PII guardrail: names and phone numbers are detected and replaced by placeholders, on input and on output")


def topic():
    s = S("v-topic", "guard")
    s.rect(24, 26, 472, 42, PAPER, LINE, rx=10)
    s.text(260, 52, "“Chick-fil-A is closed on Sundays”", 13, 600, INK)
    s.arrow(260, 72, 260, 92, s.c)
    s.pill(260, 96, "zero-shot topic classifier", "#fff", s.c, 11, 190, "middle")
    scores = [("food", 0.672, "allowed"), ("business", 0.179, ""), ("politics", 0.027, "banned")]
    x0, wmax = 128, 300
    for i, (t, v, tag) in enumerate(scores):
        y = 140 + i * 36
        s.text(116, y + 13, t, 12, 600, INK, "end")
        s.rect(x0, y, wmax, 18, "#ffffff", LINE, rx=5)
        s.rect(x0, y, max(wmax * v, 4), 18, s.c if i == 0 else ("#9aa3b2" if i == 1 else BAD), "none", rx=5)
        s.mono(x0 + wmax + 10, y + 13, f"{v:.3f}", 11, INK, "start")
        if tag:
            s.text(496, y + 13, tag, 10.5, 600, OK if tag == "allowed" else BAD, "end")
    tx = x0 + wmax * 0.5
    s.add(f'<path d="M{tx} 130 L{tx} 252" stroke="{INK}" stroke-width="1.4" stroke-dasharray="4 3"></path>')
    s.text(tx, 268, "threshold", 10.5, 600, INK)
    s.text(260, 290, "banned topic above the threshold → the guard blocks it", 11, 500, MUTED)
    return s.svg("Topic guardrail: a zero-shot classifier scores the text per topic; a banned topic above the threshold is blocked")


# =====================================================================
# LLMS + TOOLBOX
# =====================================================================
def transformer():
    s = S("v-trf", "llms")
    s.text(24, 32, "“The cat sat”", 13, 600, INK, "start")
    s.arrow(24, 44, 24, 60, MUTED)
    for i, t in enumerate(["The", " cat", " sat"]):
        s.rect(24, 66 + i * 30, 58, 22, s.soft, s.c, rx=6)
        s.mono(53, 81 + i * 30, t.strip(), 11, s.c)
    s.text(53, 172, "tokens", 11, 500, MUTED)
    s.arrow(86, 107, 104, 107, MUTED)
    for i in range(3):
        for j in range(5):
            op = [0.9, 0.45, 0.7, 0.25, 0.6][(i + j) % 5]
            s.add(f'<rect x="{110 + j*11}" y="{70 + i*30}" width="9" height="16" rx="2" fill="{s.c}" fill-opacity="{op}"></rect>')
    s.text(137, 172, "embeddings", 11, 500, MUTED)
    s.text(137, 188, "+ position", 11, 500, MUTED)
    s.arrow(170, 107, 188, 107, MUTED)
    # stacked blocks
    for k in range(3):
        s.rect(200 + k * 6, 46 + k * 6, 120, 120, PAPER if k < 2 else PAPER, LINE if k < 2 else s.c, rx=12)
    s.rect(220, 72, 96, 34, s.soft, s.soft, rx=8)
    s.text(268, 93, "self-attention", 11, 600, s.c)
    s.rect(220, 116, 96, 34, "#f4f6f9", "#f4f6f9", rx=8)
    s.text(268, 137, "feed-forward", 11, 600, INK)
    s.text(272, 188, "× N transformer blocks", 11, 500, MUTED)
    s.arrow(330, 107, 350, 107, MUTED)
    probs = [("on", 0.62), ("down", 0.21), ("up", 0.09)]
    for i, (w, p) in enumerate(probs):
        y = 70 + i * 30
        s.mono(360, y + 12, w, 11, INK, "start", 600)
        s.rect(400, y + 2, 90 * p / 0.62, 14, s.c if i == 0 else "#c9c0f2", "none", rx=4)
    s.text(430, 172, "next-token odds", 11, 500, MUTED)
    s.path("M400 196 C 380 240, 90 250, 53 178", s.c, dash="5 4", sw=1.5)
    s.text(232, 244, "pick a token, append it, repeat", 11, 600, s.c)
    s.pill(24, 262, "faster: KV cache", s.c, PAPER, 11)
    s.pill(150, 262, "multi-query / grouped attention", s.c, PAPER, 11)
    s.pill(360, 262, "sparse attention", s.c, PAPER, 11)
    return s.svg("How a transformer LLM works: tokens, embeddings with position, N transformer blocks, next-token probabilities, repeated")


def toolbox_card():
    s = S("v-tbx", "tools")
    s.rect(60, 20, 400, 262, PAPER, LINE, rx=14)
    s.rect(80, 40, 40, 40, s.soft, s.soft, rx=10)
    s.add(f'<path d="M93 66 L107 52 M96 52 L107 52 L107 63" stroke="{s.c}" stroke-width="2" fill="none" stroke-linecap="round"></path>')
    s.text(134, 58, "[Tool name]", 15, 700, INK, "start")
    s.text(134, 75, "by [maker] · open source / paid", 11, 400, MUTED, "start")
    rows = [("What it does", 0.9), ("How to use it", 0.75), ("When to choose it", 0.85), ("When not to", 0.6)]
    for i, (l, w) in enumerate(rows):
        y = 104 + i * 34
        s.text(80, y + 12, l, 11, 600, MUTED, "start")
        s.rect(200, y + 6, 240 * w, 6, "#dfe3ea", "none", rx=3)
    x = 80
    for t, top in [("Agents", "agents"), ("Evaluation", "eval"), ("Guardrails", "guard")]:
        w = s.pill(x, 246, t, C[top][0], C[top][1], 10.5)
        x += w + 8
    return s.svg("Template for a Toolbox card: name, maker, what it does, how to use it, when to choose it, topic tags")


VISUALS = {
    # key: (topic, title, caption, fn)
    "what-is-an-agent": ("agents", "What is an agent", "La boucle ReAct en un coup d’œil : ce que décide le LLM (plein) et ce qu’exécute ton code (blanc).", what_is_an_agent),
    "building-agents-with-langgraph": ("agents", "Building agents with LangGraph", "Un escalier des 5 niveaux : chaque marche ajoute un nœud au graphe, la dernière est le « boss ».", langgraph_levels),
    "tools-and-agentic-search": ("agents", "Tools and agentic search", "Le contrat du tool call, d’où viennent les outils prêts à l’emploi, et la recherche faite pour les agents.", tools_search),
    "memory-overview": ("agents", "Agent memory: overview", "La carte mentale de la mémoire : deux échelles de temps, deux mécanismes, trois types.", memory_overview),
    "short-term-memory": ("agents", "Short-term memory", "Un fil de checkpoints : même thread_id = on reprend, nouveau = page blanche.", short_term),
    "long-term-memory": ("agents", "Long-term memory", "Le store comme un classeur à trois tiroirs, et comment chaque tiroir est utilisé.", long_term),
    "controlling-a-running-agent": ("agents", "Controlling a running agent", "Une télécommande : regarder, mettre en pause, éditer, rembobiner, posée sur la ligne des checkpoints.", control),
    "evaluating-ai-agents": ("eval", "Evaluating AI Agents", "L’agent décomposé en parties + la trace, à gauche ; la démarche en 4 étapes, à droite.", evaluating_agents),
    "agent-evaluation-workflow": ("eval", "Agent evaluation workflow", "Le cycle en 5 étapes qui ne s’arrête jamais : des traces à l’amélioration, et retour.", eval_workflow),
    "traces-and-run-inspection": ("eval", "Traces and run inspection", "Une trace façon « Gantt » : l’arbre de spans dans le temps, avec un span étiqueté en échec.", traces),
    "action-and-tool-use-evaluation": ("eval", "Action and tool-use evaluation", "Trois appels d’outils notés (bon / incomplet / interdit) et l’ordre attendu.", action_eval),
    "improvement-experiments": ("eval", "Improvement experiments", "La hiérarchie d’intervention + une comparaison par catégorie qui révèle une régression cachée.", improvement),
    "production-monitoring-and-regression-tests": ("eval", "Production monitoring and regression tests", "Deux mondes reliés par une boucle : chaque échec en prod devient un test permanent.", production),
    "agent-based-evaluation-in-practice": ("eval", "Agent-based evaluation in practice", "Qui juge quoi : l’humain fixe le cap, l’agent juge lit les trajectoires, l’échec se localise par couche.", agent_based),
    "test-cases-and-benchmarks": ("eval", "Test cases and benchmarks", "Un entonnoir : une exigence devient plusieurs cas, filtrés en un benchmark stable et versionné.", benchmarks),
    "llm-judges-and-custom-rubrics": ("eval", "LLM judges and custom rubrics", "Trois ingrédients séparés (modèle, grille en 5 parties, données) → un verdict + une explication.", judges),
    "validating-evaluators": ("eval", "Validating evaluators", "Le split dev / held-out et la matrice juge vs humain qui donne précision, rappel et kappa.", validating),
    "red-teaming-llm-applications": ("eval", "Red teaming LLM applications", "L’app au centre, attaquée à gauche à la main, à droite de façon automatisée.", red_team),
    "guardrails-for-llm-apps": ("guard", "Guardrails for LLM apps", "Le pipeline de base : un validateur avant et après le LLM, et ses trois réponses possibles.", guardrails_apps),
    "building-custom-guardrails": ("guard", "Building custom guardrails", "Des poupées russes : validateurs dans un guard, dans le Guardrails Server, entre l’app et l’API.", custom_guardrails),
    "competitor-mention-guardrails": ("guard", "Competitor-mention guardrails", "L’exemple JPMC de la note, suivi à travers la cascade en 3 étages.", competitor),
    "hallucination-guardrails": ("guard", "Hallucination guardrails", "Sources à gauche, réponse découpée en affirmations à droite : NLI relie, valide ou rejette.", hallucination),
    "pii-guardrails": ("guard", "PII guardrails", "Avant / après : les données perso surlignées puis remplacées par des balises.", pii),
    "topic-guardrails": ("guard", "Topic guardrails", "L’exemple Chick-fil-A de la note, avec ses vrais scores et un seuil de blocage.", topic),
    "how-transformer-llms-work": ("llms", "How Transformer LLMs Work", "Le trajet d’une phrase de gauche à droite, et la boucle qui génère token après token.", transformer),
    "toolbox-card": ("tools", "Toolbox — modèle de fiche", "Pas encore de notes : le visuel est le gabarit commun de chaque fiche outil.", toolbox_card),
}


def get(key):
    return VISUALS[key][3]()
