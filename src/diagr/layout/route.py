from __future__ import annotations

import math

from ..model import Diagram, Edge, Move
from ..theme import Theme
from .geometry import EdgePath, NodeBox, Point, Rect, group_title_box
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


def _forward(a: NodeBox, b: NodeBox, d: Diagram) -> bool:
    return b.y > a.y + 0.5 if d.direction == "down" else b.x > a.x + 0.5


def _along(e: Edge, d: Diagram) -> bool:
    """Whether the edge's sides, if any, leave and enter along the flow, as a lane needs."""
    out, into = ("bottom", "top") if d.direction == "down" else ("right", "left")
    return e.src.side in (None, out) and e.dst.side in (None, into)


def _behind(e: Edge, d: Diagram) -> bool:
    """Whether the edge's sides, if any, suit a route back round the outside."""
    across, near = (("left", "right"), "top") if d.direction == "down" else (("top", "bottom"), "left")
    return e.src.side in (None, *across) and e.dst.side in (None, near)


def _ends(e: Edge, a: NodeBox, b: NodeBox, d: Diagram) -> tuple[Point, Point]:
    if d.direction == "down":
        # Below the whole node, trigger button included.
        return (a.x + e.src.offset, a.box.y1), b.port("top", e.dst.offset)
    return a.port("right", e.src.offset), b.port("left", e.dst.offset)


def _lane(e: Edge, a: NodeBox, b: NodeBox, d: Diagram, turn: float) -> list[Point]:
    """For placed nodes: follow the source's row and turn at `turn`, in the gap before the target."""
    p0, p1 = _ends(e, a, b, d)
    if d.direction == "down":
        return [p0, (p0[0], turn), (p1[0], turn), p1]
    return [p0, (turn, p0[1]), (turn, p1[1]), p1]


def _outer(d: Diagram, gid: str | None) -> set[str]:
    out: set[str] = set()
    while gid in d.groups and gid not in out:
        out.add(gid)
        gid = d.groups[gid].parent
    return out


def _gap(
    d: Diagram, groups: dict[str, Rect], ga: set[str], gb: set[str], lo: float, hi: float, c0: float, c1: float
) -> tuple[float, float]:
    """The free stretch of the main axis between lo and hi: past the groups only the source is in, before those only
    the target is in, and clear of other groups across the cross span c0..c1."""
    down = d.direction == "down"
    lo = max([lo] + [(groups[g].y1 if down else groups[g].x1) for g in ga - gb if g in groups])
    hi = min([hi] + [(groups[g].y if down else groups[g].x) for g in gb - ga if g in groups])
    for g, r in groups.items():
        if g in ga or g in gb:
            continue
        end = r.y1 if down else r.x1
        r0, r1 = (r.x, r.x1) if down else (r.y, r.y1)
        if r0 < c1 and c0 < r1 and lo < end < hi:
            lo = end
    return lo, hi


def _clear(p: Point, to: float, down: bool, rects: list[Rect]) -> bool:
    """Whether a straight line from p across the flow to `to` misses every rect."""
    if down:
        x0, x1 = sorted((p[0], to))
        line = Rect(x0, p[1] - 1, x1 - x0, 2)
    else:
        y0, y1 = sorted((p[1], to))
        line = Rect(p[0] - 1, y0, 2, y1 - y0)
    return not any(r.overlaps(line) for r in rects)


def _jog(pts: list[Point], titles: list[Rect]) -> list[Point]:
    """Flowing down, a lane leaves each group through its bottom edge, where the title is: step right of it."""
    (x, y0), (_, y1) = pts[0], pts[1]
    hit = [r for r in titles if r.x - 4 <= x <= r.x1 + 4 and y0 < r.y < y1]
    top = min((r.y for r in hit), default=y0)
    if top - y0 < 4:
        return pts
    jy, jx = max((y0 + top) / 2, top - 8), max(r.x1 for r in hit) + 10
    return [pts[0], (x, jy), (jx, jy), (jx, y1), *pts[2:]]


def auto_routes(d: Diagram, nodes: dict[str, NodeBox], groups: dict[str, Rect], t: Theme) -> dict[str, list[Point]]:
    """Routes for edges between placed nodes that have no route of their own.

    A forward edge follows its source's row and turns midway through the gap before the target, with lanes from
    different sources into one gap spread apart so their lines do not lie on each other. A backward edge leaves its
    source on the far side, runs back above (or beside) everything and comes in on the target's near side."""
    down = d.direction == "down"
    main, cross = (1, 0) if down else (0, 1)
    cell = d.grid.row if down else d.grid.col
    found: dict[str, tuple[float, float, float, float]] = {}
    room: dict[str, tuple[float, float]] = {}
    back: list[str] = []
    for k, e in d.edges.items():
        a, b = nodes.get(e.src.node), nodes.get(e.dst.node)
        if a is None or b is None or e.via or e.route or not (a.node.auto or b.node.auto):
            continue
        if _forward(a, b, d) and _along(e, d):
            p0, p1 = _ends(e, a, b, d)
            ga, gb = _outer(d, a.node.group), _outer(d, b.node.group)
            lo, hi = _gap(d, groups, ga, gb, p0[main], p1[main], *sorted((p0[cross], p1[cross])))
            if hi - lo < 8:
                # No clear gap: any turn between the two ends will do, so it can join the source's other lanes.
                room[k] = (p0[main] + 8, p1[main] - 8)
                mid = max(p0[main], (b.y if down else b.x) - cell / 2)
                lo, hi = mid - 12, mid + 12
            found[k] = (lo, hi, p0[cross], p1[cross])
        elif (b.y < a.y - 0.5 if down else b.x < a.x - 0.5) and _behind(e, d):
            back.append(k)
    # Lanes from one source share one turn where their gaps overlap, so they leave as a single trunk.
    by_source: dict[str, list[str]] = {}
    for k in found:
        by_source.setdefault(d.edges[k].src.node, []).append(k)
    for keys in by_source.values():
        if len(keys) > 1:
            lo = max(room[k][0] if k in room else found[k][0] for k in keys)
            hi = min(room[k][1] if k in room else found[k][1] for k in keys)
            if hi - lo >= 8:
                for k in keys:
                    found[k] = (lo, hi, found[k][2], found[k][3])
    out: dict[str, list[Point]] = {}
    gaps: dict[tuple[int, int], list[str]] = {}
    for k, (lo, hi, _, _) in found.items():
        gaps.setdefault((round(lo), round(hi)), []).append(k)
    for (lo, hi), keys in gaps.items():
        # One turn per source; a lane heading towards higher cross values turns later the lower it starts.
        sources = sorted(
            {(d.edges[k].src.node, found[k][2], found[k][3] > found[k][2]) for k in keys},
            key=lambda s: (s[2], -s[1] if s[2] else s[1]),
        )
        # A little before the middle, so the run after the turn is the longest and carries the label: the run before
        # it is often shared with the source's other edges.
        step = min(12.0, (hi - lo) / (len(sources) + 1))
        mid = lo + (hi - lo) * 0.4
        at = {s[0]: mid + (i - (len(sources) - 1) / 2) * step for i, s in enumerate(sources)}
        for k in keys:
            e = d.edges[k]
            a, b = nodes[e.src.node], nodes[e.dst.node]
            out[k] = _lane(e, a, b, d, at[e.src.node])
            if down:
                left = _outer(d, a.node.group) - _outer(d, b.node.group)
                out[k] = _jog(out[k], [group_title_box(d.groups[g], groups[g], t) for g in left if g in groups])
    if back:
        rects = list(groups.values()) + [n.box for n in nodes.values()]
        edges = {
            "before": min((r.x if down else r.y) for r in rects) - 24,
            "after": max((r.x1 if down else r.y1) for r in rects) + 24,
        }
        sides = {"before": "left" if down else "top", "after": "right" if down else "bottom"}
        count = {"before": 0, "after": 0}
        for k in back:
            e = d.edges[k]
            a, b = nodes[e.src.node], nodes[e.dst.node]
            ga, gb = _outer(d, a.node.group), _outer(d, b.node.group)
            others = [r for r in rects if r is not a.box and all(r is not groups.get(g) for g in ga)]
            clear = {w: _clear(a.port(sides[w], e.src.offset), edges[w], down, others) for w in edges}
            if e.src.side:
                way = "before" if e.src.side == sides["before"] else "after"
            else:
                way = "before" if clear["before"] or not clear["after"] else "after"
            p0, p1 = a.port(sides[way], e.src.offset), b.port("top" if down else "left", e.dst.offset)
            side = edges[way] + (-12 if way == "before" else 12) * count[way]
            count[way] += 1
            lo, hi = _gap(d, groups, ga, gb, p1[main] - cell, p1[main], *sorted((side, p1[cross])))
            turn = (lo + hi) / 2
            if down:
                out[k] = [p0, (side, p0[1]), (side, turn), (p1[0], turn), p1]
            else:
                out[k] = [p0, (p0[0], side), (turn, side), (turn, p1[1]), p1]
    return out


def as_route(pts: list[Point]) -> list[Move]:
    """The moves that draw pts, in px, with the last move on each axis left free to reach the target."""
    moves: list[Move] = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if abs(x1 - x0) > 0.01:
            moves.append(Move("right" if x1 > x0 else "left", round(abs(x1 - x0), 2), "px"))
        elif abs(y1 - y0) > 0.01:
            moves.append(Move("down" if y1 > y0 else "up", round(abs(y1 - y0), 2), "px"))
    for horizontal in (True, False):
        same = [m for m in moves if (m.dir in ("left", "right")) == horizontal]
        if same:
            same[-1].length = None
    return moves


def route_edge(e: Edge, nodes: dict[str, NodeBox], d: Diagram, t: Theme, auto: list[Point] | None = None) -> EdgePath:
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
    elif auto is not None:
        pts = auto
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
