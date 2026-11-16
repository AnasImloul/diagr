"""Authoring overlay for the HTML page: grid cells with their coordinates, node ids and positions, route points."""

from __future__ import annotations

import math
from html import escape
from typing import TYPE_CHECKING

from .scene import num

if TYPE_CHECKING:
    from ..build import Prepared

INK = "#d6336c"


def _coord(v: float) -> str:
    return f"{v:g}"


def overlay(p: Prepared) -> str:
    d, lay = p.diagram, p.layout
    b, col, row = lay.bounds, d.grid.col, d.grid.row
    c0, c1 = math.floor(b.x / col + 0.5), math.ceil(b.x1 / col - 0.5)
    r0, r1 = math.floor(b.y / row + 0.5), math.ceil(b.y1 / row - 0.5)
    out = [f'<g class="dg-debug" pointer-events="none" font-size="10" fill="{INK}" stroke="none">']
    for c in range(c0, c1 + 2):
        x = num((c - 0.5) * col)
        out.append(f'<line x1="{x}" y1="{num(b.y)}" x2="{x}" y2="{num(b.y1)}" stroke="{INK}" stroke-opacity=".25"/>')
    for r in range(r0, r1 + 2):
        y = num((r - 0.5) * row)
        out.append(f'<line x1="{num(b.x)}" y1="{y}" x2="{num(b.x1)}" y2="{y}" stroke="{INK}" stroke-opacity=".25"/>')
    for c in range(c0, c1 + 1):
        for r in range(r0, r1 + 1):
            out.append(f'<circle cx="{num(c * col)}" cy="{num(r * row)}" r="1.5" fill-opacity=".5"/>')
            out.append(
                f'<text x="{num((c - 0.5) * col + 4)}" y="{num((r - 0.5) * row + 11)}" opacity=".7">{c},{r}</text>'
            )
    for k, nb in lay.nodes.items():
        x, y = nb.node.at or (0, 0)
        at = f"[{_coord(x)}, {_coord(y)}]" + (" auto" if nb.node.auto else "")
        out.append(
            f'<text x="{num(nb.x)}" y="{num(nb.box.y - 4)}" text-anchor="middle" font-weight="600">'
            f"{escape(k)} {at}</text>"
        )
    g = '<g pointer-events="all">'
    for k, path in lay.edges.items():
        for i, (x, y) in enumerate(path.points):
            label = escape(
                f"{k}: point {i + 1} of {len(path.points)}, {x / col:.2f}, {y / row:.2f} cells ({x:g}, {y:g} px)"
            )
            g += (
                f'<circle cx="{num(x)}" cy="{num(y)}" r="3.5" fill="none" stroke="{INK}" stroke-width="1.5">'
                f"<title>{label}</title></circle>"
            )
    out.append(g + "</g></g>")
    return "".join(out)


TOGGLE = (
    "<script>document.addEventListener('keydown',function(e){var t=(e.target&&e.target.tagName)||'';"
    "if(e.key!=='g'||e.metaKey||e.ctrlKey||e.altKey||t==='INPUT'||t==='SELECT'||t==='TEXTAREA'"
    "||!(e.target.closest&&e.target.closest('.wrap')))return;"
    "document.querySelectorAll('.dg-debug').forEach(function(o){o.style.display=o.style.display==='none'?'':'none'})"
    "});</script>"
)
