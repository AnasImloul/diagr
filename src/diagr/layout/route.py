from __future__ import annotations

import math

from ..model import Diagram, Edge
from ..theme import Theme
from .geometry import EdgePath, NodeBox, Point, Rect
from .text import text_width

EXIT = {"right": "right", "left": "left", "down": "bottom", "up": "top"}
ENTER = {"right": "left", "left": "right", "down": "top", "up": "bottom"}
VEC = {"right": (1, 0), "left": (-1, 0), "down": (0, 1), "up": (0, -1)}


def _default_sides(a: NodeBox, b: NodeBox) -> tuple[str, str, bool]:
    dx, dy = b.x - a.x, b.y - a.y
    if abs(dy) < 0.5:
        return ("right", "left", False) if dx >= 0 else ("left", "right", False)
    if abs(dx) < 0.5:
        return ("bottom", "top", False) if dy >= 0 else ("top", "bottom", False)
    return ("right" if dx > 0 else "left", "top" if dy > 0 else "bottom", True)


def _toward(a: Point, b: Point) -> str:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) >= abs(dy):
        return "right" if dx >= 0 else "left"
    return "down" if dy >= 0 else "up"


def _solve(e: Edge, start: Point, end: Point, d: Diagram, problems: list[str]) -> list[Point]:
    moves = e.route or []
    unit = {"x": d.grid.col, "y": d.grid.row}
    lengths: list[float | None] = []
    for m in moves:
        if m.length is None:
            lengths.append(None)
        else:
            lengths.append(m.length * (1 if m.unit == "px" else unit["x" if m.dir in ("left", "right") else "y"]))
    for axis, i in (("x", 0), ("y", 1)):
        idx = [k for k, m in enumerate(moves) if (m.dir in ("left", "right")) == (axis == "x")]
        need = end[i] - start[i]
        known = sum(VEC[moves[k].dir][i] * (lengths[k] or 0) for k in idx)
        free = [k for k in idx if lengths[k] is None]
        rest = need - known
        if not idx:
            if abs(need) > 0.5:
                problems.append(
                    f"route never moves {'sideways' if axis == 'x' else 'up or down'}, "
                    f"but the target is {abs(need):.0f}px away on that axis"
                )
            continue
        if not free:
            if abs(rest) > 0.5:
                problems.append(f"route lengths on the {axis} axis miss the target by {rest:.0f}px")
            continue
        sign = sum(VEC[moves[k].dir][i] for k in free)
        share = rest / sign if sign else 0
        if share < -0.5:
            problems.append(f"route goes the wrong way on the {axis} axis to reach the target")
        for k in free:
            lengths[k] = share
    pts = [start]
    x, y = start
    for m, ln in zip(moves, lengths, strict=True):
        vx, vy = VEC[m.dir]
        x, y = x + vx * (ln or 0), y + vy * (ln or 0)
        pts.append((x, y))
    pts[-1] = end
    return pts


def _simplify(pts: list[Point]) -> list[Point]:
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) < 0.01 and abs(p[1] - out[-1][1]) < 0.01:
            continue
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            same_x = abs(a[0] - b[0]) < 0.01 and abs(b[0] - p[0]) < 0.01
            same_y = abs(a[1] - b[1]) < 0.01 and abs(b[1] - p[1]) < 0.01
            if same_x or same_y:
                out[-1] = p
                continue
        out.append(p)
    return out


def label_point(pts: list[Point], at: float | None, width: float = 0) -> Point:
    segs = list(zip(pts, pts[1:], strict=False))
    lens = [math.dist(a, b) for a, b in segs]
    if at is None:
        # Pills read best on a horizontal run; fall back to the longest segment when none is long enough.
        flat = [k for k, (a, b) in enumerate(segs) if abs(a[1] - b[1]) < 0.5 and lens[k] >= width + 20]
        i = max(flat or range(len(segs)), key=lambda k: lens[k])
        (ax, ay), (bx, by) = segs[i]
        return ((ax + bx) / 2, (ay + by) / 2)
    target = max(0.0, min(1.0, at)) * sum(lens)
    for (a, b), ln in zip(segs, lens, strict=True):
        if target <= ln and ln > 0:
            f = target / ln
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        target -= ln
    return pts[-1]


def route_edge(e: Edge, nodes: dict[str, NodeBox], d: Diagram, t: Theme) -> EdgePath:
    a, b = nodes[e.src.node], nodes[e.dst.node]
    problems: list[str] = []
    if e.via:
        via = [(c * d.grid.col, r * d.grid.row) for c, r in e.via]
        s_side = e.src.side or EXIT[_toward((a.x, a.y), via[0])]
        t_side = e.dst.side or ENTER[_toward(via[-1], (b.x, b.y))]
        pts = [a.port(s_side, e.src.offset), *via, b.port(t_side, e.dst.offset)]
    elif e.route:
        s_side = e.src.side or EXIT[e.route[0].dir]
        t_side = e.dst.side or ENTER[e.route[-1].dir]
        pts = _solve(e, a.port(s_side, e.src.offset), b.port(t_side, e.dst.offset), d, problems)
    else:
        s_side, t_side, bend = _default_sides(a, b)
        s_side, t_side = e.src.side or s_side, e.dst.side or t_side
        p0, p1 = a.port(s_side, e.src.offset), b.port(t_side, e.dst.offset)
        if bend or (abs(p0[0] - p1[0]) > 0.5 and abs(p0[1] - p1[1]) > 0.5):
            pts = [p0, (p1[0], p0[1]) if s_side in ("left", "right") else (p0[0], p1[1]), p1]
        else:
            pts = [p0, p1]
    pts = _simplify(pts)
    if len(pts) < 2:
        pts = [pts[0], pts[0]]
        problems.append("edge has no length")
    for p, q in zip(pts, pts[1:], strict=False):
        if abs(p[0] - q[0]) > 0.5 and abs(p[1] - q[1]) > 0.5:
            problems.append("edge has a diagonal segment; add a route or via points")
            break
    label = box = None
    if e.label:
        w = text_width(e.label, t.size("label")) + 10
        label = label_point(pts, e.label_at, w)
        box = Rect(label[0] - w / 2, label[1] - 9, w, 18)
    return EdgePath(e, pts, label, box, problems)


def rounded(points: list[Point], r: float = 8) -> str:
    d = [f"M{_n(points[0][0])} {_n(points[0][1])}"]
    for i in range(1, len(points) - 1):
        (x0, y0), (x1, y1), (x2, y2) = points[i - 1], points[i], points[i + 1]
        la, lb = abs(x1 - x0) + abs(y1 - y0), abs(x2 - x1) + abs(y2 - y1)
        a = min(r, la / 2) / max(1, la)
        b = min(r, lb / 2) / max(1, lb)
        d.append(f"L{_n(x1 - (x1 - x0) * a)} {_n(y1 - (y1 - y0) * a)}")
        d.append(f"Q{_n(x1)} {_n(y1)} {_n(x1 + (x2 - x1) * b)} {_n(y1 + (y2 - y1) * b)}")
    d.append(f"L{_n(points[-1][0])} {_n(points[-1][1])}")
    return " ".join(d)


def _n(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s
