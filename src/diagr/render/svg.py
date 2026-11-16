from __future__ import annotations

import math
from html import escape

from ..layout.text import text_width
from ..scenario import Compiled
from ..theme import Theme
from .scene import El, SceneBuilder, num, safe_id, serialise

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
    out: list[El] = [
        El(
            "line",
            {"x1": num(x0 + 20), "y1": num(y0), "x2": num(x0 + width - 20), "y2": num(y0), "stroke-width": 1.5},
            paint={"stroke": "rule"},
        )
    ]
    bottom = y0
    for c in range(cols):
        y = y0 + 34
        for i in range(c * per_col, min(len(comp.steps), (c + 1) * per_col)):
            s = comp.steps[i]
            x = x0 + 20 + c * col_w
            out.append(El("circle", {"cx": num(x + 10), "cy": num(y - 4), "r": 10}, paint={"fill": "badge"}))
            out.append(
                El(
                    "text",
                    {"x": num(x + 10), "y": num(y - 0.2), "font-size": 11, "font-weight": 600, "text-anchor": "middle"},
                    [str(i + 1)],
                    paint={"fill": "on-badge"},
                )
            )
            out.append(
                El(
                    "text",
                    {"x": num(x + 30), "y": num(y), "font-size": STEP_TITLE, "font-weight": 600},
                    [s.title],
                    paint={"fill": "text"},
                )
            )
            lines = wrap(s.text, STEP_TEXT, col_w - 70) if s.text else []
            for j, line in enumerate(lines):
                out.append(
                    El(
                        "text",
                        {"x": num(x + 30), "y": num(y + 19 + j * STEP_LINE), "font-size": STEP_TEXT},
                        [line],
                        paint={"fill": "muted"},
                    )
                )
            y += 19 + len(lines) * STEP_LINE + 22
        bottom = max(bottom, y)
    return out, bottom - y0


def _uncover_labels(el: El, edges: list[El], holes: list[dict[str, object]]) -> None:
    """Take out the pills that hide the edges under labels outside any group, keeping where they were."""
    for child in el.children:
        if not isinstance(child, El):
            continue
        kind = child.attrs.get("class")
        if kind == "edge":
            edges.append(child)
        elif kind == "elab":
            pills = [c for c in child.children if isinstance(c, El) and c.tag == "rect" and c.paint.get("fill") == "bg"]
            if not child.attrs.get("data-hidden"):
                holes.extend(p.attrs for p in pills)
            child.children = [c for c in child.children if c not in pills]
        else:
            _uncover_labels(child, edges, holes)


def label_mask(mask_id: str, x: float, y: float, w: float, h: float, holes: list[dict[str, object]]) -> str:
    """A mask that cuts the edges where a label sits, as the label's pill does on a background of its own."""
    cut = "".join(
        f'<rect x="{a["x"]}" y="{a["y"]}" width="{a["width"]}" height="{a["height"]}" rx="{a.get("rx", 0)}" '
        'fill="black"/>'
        for a in holes
    )
    box = f'x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}"'
    return f'<defs><mask id="{mask_id}" maskUnits="userSpaceOnUse" {box}><rect {box} fill="white"/>{cut}</mask></defs>'


def render_static(sb: SceneBuilder, t: Theme, scheme: str, transparent: bool = False) -> str:
    """The diagram as an SVG with its colours baked in. transparent leaves out the background, for any page colour."""
    body, b = sb.build()
    extra: list[El] = []
    height = b.h
    if sb.comp and sb.d.step_list and sb.comp.steps:
        items, h = step_list(sb.comp, b.x, b.y1, b.w)
        extra, height = items, b.h + h
    defs = sb.defs()
    mask = ""
    if transparent:
        edges: list[El] = []
        holes: list[dict[str, object]] = []
        _uncover_labels(body, edges, holes)
        if holes:
            mask_id = f"{safe_id(sb.d.id)}-labels"
            mask = label_mask(mask_id, b.x, b.y, b.w, height, holes)
            for e in edges:
                e.attrs["mask"] = f"url(#{mask_id})"

    def resolve(prop: str, token: str) -> str:
        # Without a background the page colour is whatever the SVG sits on, so nothing is painted with it.
        if transparent and token == "bg":
            return "none"
        return t.hex(scheme, token)

    # Named by its title and described by its description; the ids carry the scheme, so the light and the dark image
    # can sit in one page.
    name = f"{safe_id(sb.d.id)}-{scheme}"
    described = f' aria-describedby="{name}-desc"' if sb.d.description else ""
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{num(b.x)} {num(b.y)} {num(b.w)} {num(height)}" '
        f'width="{num(b.w)}" height="{num(height)}" font-family="{escape(t.font, quote=True)}" role="img" '
        f'aria-labelledby="{name}-title"{described}>'
    )
    parts = [head, f'<title id="{name}-title">{escape(sb.d.title or sb.d.id)}</title>']
    if sb.d.description:
        parts.append(f'<desc id="{name}-desc">{escape(sb.d.description)}</desc>')
    parts.append(serialise(defs, "static", resolve))
    if mask:
        parts.append(mask)
    if not transparent:
        box = f'x="{num(b.x)}" y="{num(b.y)}" width="{num(b.w)}" height="{num(height)}"'
        parts.append(f'<rect {box} fill="{t.hex(scheme, "bg")}"/>')
    parts.append(serialise(body, "static", resolve))
    parts.extend(serialise(e, "static", resolve) for e in extra)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
