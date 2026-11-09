from __future__ import annotations

import math
from html import escape

from ..layout.text import text_width
from ..scenario import Compiled
from ..scene import El, SceneBuilder, num, serialise
from ..theme import Theme

STEP_TITLE = 14
STEP_TEXT = 12.5
STEP_LINE = 17


def wrap(text: str, size: float, width: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and text_width(trial, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def step_list(comp: Compiled, x0: float, y0: float, width: float) -> tuple[list[El], float]:
    cols = 2 if width >= 900 else 1
    per_col = math.ceil(len(comp.steps) / cols)
    col_w = width / cols
    out: list[El] = [El("line", {"x1": num(x0 + 20), "y1": num(y0), "x2": num(x0 + width - 20), "y2": num(y0),
                                 "stroke-width": 1.5}, paint={"stroke": "rule"})]
    bottom = y0
    for c in range(cols):
        y = y0 + 34
        for i in range(c * per_col, min(len(comp.steps), (c + 1) * per_col)):
            s = comp.steps[i]
            x = x0 + 20 + c * col_w
            out.append(El("circle", {"cx": num(x + 10), "cy": num(y - 4), "r": 10}, paint={"fill": "badge"}))
            out.append(El("text", {"x": num(x + 10), "y": num(y - 0.2), "font-size": 11, "font-weight": 600,
                                   "text-anchor": "middle"}, [str(i + 1)], paint={"fill": "on-badge"}))
            out.append(El("text", {"x": num(x + 30), "y": num(y), "font-size": STEP_TITLE, "font-weight": 600},
                          [escape(s.title)], paint={"fill": "text"}))
            lines = wrap(s.text, STEP_TEXT, col_w - 70) if s.text else []
            for j, line in enumerate(lines):
                out.append(El("text", {"x": num(x + 30), "y": num(y + 19 + j * STEP_LINE), "font-size": STEP_TEXT},
                              [escape(line)], paint={"fill": "muted"}))
            y += 19 + len(lines) * STEP_LINE + 22
        bottom = max(bottom, y)
    return out, bottom - y0


def render_static(sb: SceneBuilder, t: Theme, scheme: str) -> str:
    body, b = sb.build()
    extra: list[El] = []
    height = b.h
    if sb.comp and sb.d.step_list and sb.comp.steps:
        items, h = step_list(sb.comp, b.x, b.y1, b.w)
        extra, height = items, b.h + h
    defs = sb.defs()

    def resolve(prop: str, token: str) -> str:
        return t.hex(scheme, token)

    label = escape(sb.d.description or sb.d.title or sb.d.id, quote=True)
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{num(b.x)} {num(b.y)} {num(b.w)} {num(height)}" '
            f'width="{num(b.w)}" height="{num(height)}" font-family="{escape(t.font, quote=True)}" role="img" '
            f'aria-label="{label}">')
    parts = [head]
    if sb.d.title:
        parts.append(f"<title>{escape(sb.d.title)}</title>")
    parts.append(serialise(defs, "static", resolve))
    parts.append(f'<rect x="{num(b.x)}" y="{num(b.y)}" width="{num(b.w)}" height="{num(height)}" '
                 f'fill="{t.hex(scheme, "bg")}"/>')
    parts.append(serialise(body, "static", resolve))
    parts.extend(serialise(e, "static", resolve) for e in extra)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
