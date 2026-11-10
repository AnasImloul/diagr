from __future__ import annotations

import math

from ..model import Diagram, Edge, Move, Port, boxes_around
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


def _ends(e: Edge, a: NodeBox, b: NodeBox, d: Diagram, shift: float = 0.0) -> tuple[Point, Point]:
    if d.direction == "down":
        # Below the whole node, trigger button included.
        return (a.x + e.src.offset, a.box.y1), b.port("top", e.dst.offset + shift)
    return a.port("right", e.src.offset), b.port("left", e.dst.offset + shift)


def _lane(e: Edge, a: NodeBox, b: NodeBox, d: Diagram, turn: float, shift: float = 0.0) -> list[Point]:
    """For placed nodes: follow the source's row and turn at `turn`, in the gap before the target."""
    p0, p1 = _ends(e, a, b, d, shift)
    if d.direction == "down":
        return [p0, (p0[0], turn), (p1[0], turn), p1]
    return [p0, (turn, p0[1]), (turn, p1[1]), p1]


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


def _straight(e: Edge, a: NodeBox, b: NodeBox, titles: list[Rect] | None = None) -> list[Point] | None:
    """An edge with a box at one end or both goes straight across when the two line up: at a named port, at the
    node's own x or y, or in the middle of where two boxes overlap (or as near it as misses every title). A side named
    on either end must agree."""

    def end(n: NodeBox, side: str) -> float:
        if n.area:
            return {"top": n.box.y, "bottom": n.box.y1, "left": n.box.x, "right": n.box.x1}[side]
        return {"top": n.y - n.reach, "bottom": n.bottom, "left": n.x - n.reach, "right": n.x + n.reach}[side]

    def span(n: NodeBox, vertical: bool, inset: float) -> tuple[float, float]:
        if n.area:
            lo, hi = (n.box.x, n.box.x1) if vertical else (n.box.y, n.box.y1)
            return lo + inset, hi - inset
        return (n.x, n.x) if vertical else (n.y, n.y)

    for vertical in (True, False):
        # A named port lines up anywhere along a box; the middle of an overlap keeps clear of the corners.
        lo = max(span(a, vertical, 0)[0], span(b, vertical, 0)[0])
        hi = min(span(a, vertical, 0)[1], span(b, vertical, 0)[1])
        if lo > hi + 0.5:
            continue
        if vertical:
            ab, ba = b.box.y >= a.box.y1, a.box.y >= b.box.y1
            sides = ("bottom", "top") if ab else ("top", "bottom") if ba else None
        else:
            ab, ba = b.box.x >= a.box.x1, a.box.x >= b.box.x1
            sides = ("right", "left") if ab else ("left", "right") if ba else None
        if sides is None or e.src.side not in (None, sides[0]) or e.dst.side not in (None, sides[1]):
            continue
        axis = 0 if vertical else 1
        named = [
            n.port(side, end.offset)[axis] for n, side, end in ((a, sides[0], e.src), (b, sides[1], e.dst)) if end.side
        ]
        if len(named) == 2 and abs(named[0] - named[1]) > 0.5:
            continue
        if named:
            c = named[0]
        elif not a.area:
            c = a.x if vertical else a.y
        elif not b.area:
            c = b.x if vertical else b.y
        else:
            lo12 = max(span(a, vertical, 12)[0], span(b, vertical, 12)[0])
            hi12 = min(span(a, vertical, 12)[1], span(b, vertical, 12)[1])
            p0, p1 = end(a, sides[0]), end(b, sides[1])
            found = _clear_of(titles or [], (lo12 + hi12) / 2, lo12, hi12, p0, p1, vertical)
            if found is None:
                # Titles cover the whole overlap: a Z through the gap between the boxes instead, each upright part
                # where it misses them.
                gap = (p0 + p1) / 2
                sa, sb = span(a, vertical, 12), span(b, vertical, 12)
                ca = _clear_of(titles or [], (sa[0] + sa[1]) / 2, sa[0], sa[1], p0, gap, vertical)
                cb = _clear_of(titles or [], (sb[0] + sb[1]) / 2, sb[0], sb[1], gap, p1, vertical)
                if ca is not None and cb is not None:
                    pts = [(ca, p0), (ca, gap), (cb, gap), (cb, p1)]
                    return pts if vertical else [(y, x) for x, y in pts]
                found = (lo12 + hi12) / 2
            c = found
        if not lo - 0.5 <= c <= hi + 0.5:
            continue
        p0, p1 = end(a, sides[0]), end(b, sides[1])
        return [(c, p0), (c, p1)] if vertical else [(p0, c), (p1, c)]
    return None


def _clear_of(
    titles: list[Rect], mid: float, lo: float, hi: float, p0: float, p1: float, vertical: bool
) -> float | None:
    """The point nearest mid, between lo and hi, where a straight line from p0 to p1 misses every title, or None."""
    a, b = sorted((p0, p1))

    def clear(c: float) -> bool:
        line = Rect(c - 1, a, 2, b - a) if vertical else Rect(a, c - 1, b - a, 2)
        return not any(r.overlaps(line) for r in titles)

    if clear(mid):
        return mid
    for i in range(1, int(max(0.0, hi - lo) / 8) + 1):
        for c in (mid + 8 * i, mid - 8 * i):
            if lo <= c <= hi and clear(c):
                return c
    return None


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


def auto_routes(
    d: Diagram, nodes: dict[str, NodeBox], groups: dict[str, Rect], t: Theme
) -> tuple[dict[str, list[Point]], set[str], dict[str, Port]]:
    """Routes for edges between placed nodes that have no route of their own, the edges whose first run is a trunk
    shared with the source's other lanes, and the port each edge ends at that meets a side along with others.

    A forward edge follows its source's row and turns midway through the gap before the target, with lanes from
    different sources into one gap spread apart so their lines do not lie on each other. A backward edge leaves its
    source on the far side, runs back above (or beside) everything and comes in on the target's near side."""
    r = _Router(d, nodes, groups, t)
    r.sort_edges()
    trunks = r.share_trunks()
    r.pick_ways()
    r.spread_ends()
    out = r.forward_lanes() | r.back_lanes()
    near = "top" if r.down else "left"
    ports = {k: Port(d.edges[k].dst.node, near, round(d.edges[k].dst.offset + v, 2)) for k, v in r.shift.items() if v}
    return out, trunks, ports


class _Router:
    """What the phases of `auto_routes` share: the gap each forward edge turns in, the backward edges and the side
    each goes round, and how far each edge's end moves along the side it meets."""

    def __init__(self, d: Diagram, nodes: dict[str, NodeBox], groups: dict[str, Rect], t: Theme):
        self.d, self.nodes, self.groups, self.t = d, nodes, groups, t
        self.down = down = d.direction == "down"
        self.main, self.cross = (1, 0) if down else (0, 1)
        self.cell = d.grid.row if down else d.grid.col
        # Forward edge -> the stretch of the main axis it turns in, and where it starts and ends on the cross axis.
        self.found: dict[str, tuple[float, float, float, float]] = {}
        # Forward edge with no clear gap -> the stretch it could turn anywhere in.
        self.room: dict[str, tuple[float, float]] = {}
        self.back: list[str] = []
        self.rects = list(groups.values()) + [n.box for n in nodes.values()]
        # Where backward edges run past everything, before it or after it on the cross axis, and the side they leave.
        self.outside = {
            "before": min((r.x if down else r.y) for r in self.rects) - 24,
            "after": max((r.x1 if down else r.y1) for r in self.rects) + 24,
        }
        self.sides = {"before": "left" if down else "top", "after": "right" if down else "bottom"}
        self.ways: dict[str, str] = {}
        self.shift: dict[str, float] = {}

    def sort_edges(self) -> None:
        """Forward edges, with the gap each turns in, and backward edges."""
        d, nodes, main, cross, down = self.d, self.nodes, self.main, self.cross, self.down
        for k, e in d.edges.items():
            a, b = nodes.get(e.src.node), nodes.get(e.dst.node)
            if a is None or b is None or e.via or e.route or not (a.node.auto or b.node.auto):
                continue
            if _forward(a, b, d) and _along(e, d):
                p0, p1 = _ends(e, a, b, d)
                ga, gb = set(boxes_around(d, a.node.group)), set(boxes_around(d, b.node.group))
                lo, hi = _gap(d, self.groups, ga, gb, p0[main], p1[main], *sorted((p0[cross], p1[cross])))
                if hi - lo < 8:
                    # No clear gap: any turn between the two ends will do, so it can join the source's other lanes.
                    self.room[k] = (p0[main] + 8, p1[main] - 8)
                    mid = max(p0[main], (b.y if down else b.x) - self.cell / 2)
                    lo, hi = mid - 12, mid + 12
                self.found[k] = (lo, hi, p0[cross], p1[cross])
            elif (b.y < a.y - 0.5 if down else b.x < a.x - 0.5) and _behind(e, d):
                self.back.append(k)

    def share_trunks(self) -> set[str]:
        """Lanes from one source share one turn where their gaps overlap, so they leave as a single trunk. The edges
        of each source with more than one lane."""
        found, room = self.found, self.room
        by_source: dict[str, list[str]] = {}
        for k in found:
            by_source.setdefault(self.d.edges[k].src.node, []).append(k)
        for keys in by_source.values():
            if len(keys) > 1:
                lo = max(room[k][0] if k in room else found[k][0] for k in keys)
                hi = min(room[k][1] if k in room else found[k][1] for k in keys)
                if hi - lo >= 8:
                    for k in keys:
                        found[k] = (lo, hi, found[k][2], found[k][3])
        return {k for keys in by_source.values() if len(keys) > 1 for k in keys}

    def pick_ways(self) -> None:
        """The side each backward edge goes round: the one its source's side names, or the one that is clear."""
        d, nodes, sides = self.d, self.nodes, self.sides
        for k in self.back:
            e = d.edges[k]
            a = nodes[e.src.node]
            ga = boxes_around(d, a.node.group)
            others = [r for r in self.rects if r is not a.box and all(r is not self.groups.get(g) for g in ga)]
            clear = {
                w: _clear(a.port(sides[w], e.src.offset), self.outside[w], self.down, others) for w in self.outside
            }
            if e.src.side:
                self.ways[k] = "before" if e.src.side == sides["before"] else "after"
            else:
                self.ways[k] = "before" if clear["before"] or not clear["after"] else "after"

    def spread_ends(self) -> None:
        """Edges that come into a node on one side meet it side by side, in the order they come from, rather than on
        one point; an edge with a port of its own keeps it."""
        d, nodes = self.d, self.nodes
        coming: dict[str, list[tuple[float, str]]] = {}
        for k in [*self.found, *self.back]:
            e = d.edges[k]
            if e.dst.side is None and not e.dst.offset and not nodes[e.dst.node].point:
                if k in self.found:
                    at = self.found[k][2]
                else:
                    at = -math.inf if self.ways[k] == "before" else math.inf
                coming.setdefault(e.dst.node, []).append((at, k))
        for ins in coming.values():
            if len(ins) > 1:
                step = min(20.0, (self.t.size("icon") - 12) / (len(ins) - 1))
                for i, (_, k) in enumerate(sorted(ins)):
                    self.shift[k] = (i - (len(ins) - 1) / 2) * step

    def forward_lanes(self) -> dict[str, list[Point]]:
        d, nodes, found = self.d, self.nodes, self.found
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
            # A little before the middle, so the run after the turn is the longest and carries the label: the run
            # before it is often shared with the source's other edges.
            step = min(12.0, (hi - lo) / (len(sources) + 1))
            mid = lo + (hi - lo) * 0.4
            at = {s[0]: mid + (i - (len(sources) - 1) / 2) * step for i, s in enumerate(sources)}
            for k in keys:
                e = d.edges[k]
                a, b = nodes[e.src.node], nodes[e.dst.node]
                out[k] = _lane(e, a, b, d, at[e.src.node], self.shift.get(k, 0.0))
                if self.down:
                    left = set(boxes_around(d, a.node.group)) - set(boxes_around(d, b.node.group))
                    titles = [group_title_box(d.groups[g], self.groups[g], self.t) for g in left if g in self.groups]
                    out[k] = _jog(out[k], titles)
        return out

    def back_lanes(self) -> dict[str, list[Point]]:
        d, nodes, main, cross, down = self.d, self.nodes, self.main, self.cross, self.down
        out: dict[str, list[Point]] = {}
        count = {"before": 0, "after": 0}
        for k in self.back:
            e = d.edges[k]
            a, b = nodes[e.src.node], nodes[e.dst.node]
            ga, gb = set(boxes_around(d, a.node.group)), set(boxes_around(d, b.node.group))
            way = self.ways[k]
            p0 = a.port(self.sides[way], e.src.offset)
            p1 = b.port("top" if down else "left", e.dst.offset + self.shift.get(k, 0.0))
            side = self.outside[way] + (-12 if way == "before" else 12) * count[way]
            count[way] += 1
            lo, hi = _gap(d, self.groups, ga, gb, p1[main] - self.cell, p1[main], *sorted((side, p1[cross])))
            turn = (lo + hi) / 2
            if down:
                out[k] = [p0, (side, p0[1]), (side, turn), (p1[0], turn), p1]
            else:
                out[k] = [p0, (p0[0], side), (turn, side), (turn, p1[1]), p1]
        return out


def _fraction(pts: list[Point], at: Point) -> float:
    """How far along pts the point at lies, from 0 to 1."""
    lens = [math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False)]
    done = 0.0
    for (a, b), ln in zip(zip(pts, pts[1:], strict=False), lens, strict=True):
        if ln and abs(math.dist(a, at) + math.dist(at, b) - ln) < 0.01:
            return round((done + math.dist(a, at)) / sum(lens), 6)
        done += ln
    return 0.5


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


def _cut(pts: list[Point], rects: list[Rect]) -> list[Point] | None:
    """pts up to where they first enter one of rects, or None if they never do (or start inside one)."""
    if any(r.x < pts[0][0] < r.x1 and r.y < pts[0][1] < r.y1 for r in rects):
        return None
    for i, (p, q) in enumerate(zip(pts, pts[1:], strict=False)):
        best: float | None = None
        for r in rects:
            for t in _entries(p, q, r):
                best = t if best is None else min(best, t)
        if best is not None:
            hit = (p[0] + (q[0] - p[0]) * best, p[1] + (q[1] - p[1]) * best)
            return [*pts[: i + 1], hit]
    return None


def _entries(p: Point, q: Point, r: Rect) -> list[float]:
    """Where along the segment p-q (0 to 1) it crosses into r through one of its sides."""
    out = []
    for axis, lo, hi in ((0, r.x, r.x1), (1, r.y, r.y1)):
        other = 1 - axis
        olo, ohi = (r.y, r.y1) if axis == 0 else (r.x, r.x1)
        span = q[axis] - p[axis]
        if abs(span) < 1e-9:
            continue
        for edge in (lo, hi):
            t = (edge - p[axis]) / span
            if 0 < t <= 1:
                o = p[other] + (q[other] - p[other]) * t
                if olo < o < ohi:
                    out.append(t)
    return out


def route_edge(
    e: Edge,
    nodes: dict[str, NodeBox],
    d: Diagram,
    t: Theme,
    auto: list[Point] | None = None,
    covers: dict[str, list[Rect]] | None = None,
    titles: list[Rect] | None = None,
    trunk: bool = False,
    port: Port | None = None,
) -> EdgePath:
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
    elif (a.area or b.area) and (straight := _straight(e, a, b, titles)):
        pts = straight
    else:
        s_side, t_side, bend = _default_sides(a, b)
        s_side, t_side = e.src.side or s_side, e.dst.side or t_side
        p0, p1 = a.port(s_side, e.src.offset), b.port(t_side, e.dst.offset)
        upright = {"top", "bottom"}
        if (s_side in upright) == (t_side in upright) and abs(p0[0] - p1[0]) > 0.5 and abs(p0[1] - p1[1]) > 0.5:
            # Both ends leave the same way (both up or down, or both sideways): a Z with the bend halfway, so the
            # edge never runs along a side to reach its port.
            if s_side in upright:
                mid = (p0[1] + p1[1]) / 2
                pts = [p0, (p0[0], mid), (p1[0], mid), p1]
            else:
                mid = (p0[0] + p1[0]) / 2
                pts = [p0, (mid, p0[1]), (mid, p1[1]), p1]
        elif bend or (abs(p0[0] - p1[0]) > 0.5 and abs(p0[1] - p1[1]) > 0.5):
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
    # An edge to a box stacked behind another stops, without a tip, where it meets the one in front; one from such a
    # box starts where it comes out from behind.
    tip = True
    if covers and e.dst.node in covers and (cut := _cut(pts, covers[e.dst.node])):
        pts, tip = cut, False
    if covers and e.src.node in covers and (cut := _cut(pts[::-1], covers[e.src.node])):
        pts = cut[::-1]
    label = box = frac = None
    if e.label:
        w = text_width(e.label, t.size("label")) + 10
        # The first run of a trunk is shared with the source's other lanes: the label goes after it when it fits.
        rest = pts[1:] if trunk and e.label_at is None else []
        fits = any(abs(p[1] - q[1]) < 0.5 and abs(p[0] - q[0]) >= w + 20 for p, q in zip(rest, rest[1:], strict=False))
        label = label_point(rest if fits else pts, e.label_at, w)
        box = Rect(label[0] - w / 2, label[1] - 9, w, 18)
        if fits and math.dist(label, label_point(pts, None, w)) > 0.01:
            frac = _fraction(pts, label)
    path = EdgePath(e, pts, label, box, problems, tip=tip, port=port, label_frac=frac)
    if e.id in d.numbers:
        _place_badge(path, d.numbers[e.id], t)
    return path


def _place_badge(path: EdgePath, number: str, t: Theme) -> None:
    """A dynamic view's step badge: just left of the label when its run has room for both, otherwise on the last
    segment, just before the arrow, where no other edge runs."""
    bw, r = badge_width(number, t), t.size("badge")
    pts, lab, box = path.points, path.label_at, path.label_box
    if lab and box:
        whole = bw + 4 + box.w
        for a, b in zip(pts, pts[1:], strict=False):
            flat = abs(a[1] - b[1]) < 0.5 and abs(a[1] - lab[1]) < 0.5 and min(a[0], b[0]) <= lab[0] <= max(a[0], b[0])
            if flat and abs(b[0] - a[0]) >= whole + 20:
                left = lab[0] - whole / 2
                path.label_at = (left + bw + 4 + box.w / 2, lab[1])
                path.label_box = Rect(left + bw + 4, box.y, box.w, box.h)
                path.badge_at = (left + bw / 2, lab[1])
                break
            upright = (
                abs(a[0] - b[0]) < 0.5 and abs(a[0] - lab[0]) < 0.5 and min(a[1], b[1]) <= lab[1] <= max(a[1], b[1])
            )
            if upright:
                # A label on a vertical run: the badge goes just before it, on the side the edge comes from.
                y = box.y - 4 - r if b[1] > a[1] else box.y1 + 4 + r
                if min(a[1], b[1]) + r <= y <= max(a[1], b[1]) - r:
                    path.badge_at = (lab[0], y)
                break
    if path.badge_at is None:
        (ax, ay), (bx, by) = pts[-2], pts[-1]
        length = math.dist((ax, ay), (bx, by)) or 1
        back = min(length / 2, 10.5 + 6 + (bw / 2 if abs(ay - by) < 0.5 else r))
        path.badge_at = (bx - (bx - ax) / length * back, by - (by - ay) / length * back)
        if box and abs(ay - by) < 0.5 and abs(box.y + box.h / 2 - by) < 0.5:
            # The label is on that last run too: sit just before it instead, on the side the edge comes from.
            x = box.x - 4 - bw / 2 if bx > ax else box.x1 + 4 + bw / 2
            path.badge_at = (x, by)
    x, y = path.badge_at
    path.badge_box = Rect(x - bw / 2, y - r, bw, 2 * r)


def badge_width(text: str, t: Theme) -> float:
    return max(2 * t.size("badge"), text_width(text, 11, 600) + 10)


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
