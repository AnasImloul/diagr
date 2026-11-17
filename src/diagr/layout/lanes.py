"""Routes for edges the layered placer placed: each follows the lanes kept open for it through the layers it passes,
turning only in the gaps between layers.

A forward edge leaves its source on the side facing along the flow and enters its target on the side facing back; a
backward edge the other way round, back through its own lanes. Edges that turn in one gap turn side by side, ordered
so they do not cross there, and those from one source share their first turn, leaving as one trunk. Edges that meet a
node on one side meet it side by side, in the order they come from.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import permutations

from ..model import Diagram, Port, boxes_around
from ..theme import Theme
from .geometry import NodeBox, Point, Rect, group_title_box

# Turns closer than this across the flow are the same line: lanes and nodes can be a rounding apart.
SAME = 1.5
TURN_STEP = 12.0
END_STEP = 12.0
# A step across the flow shorter than this is a jog: an end that close to its lane moves onto it.
JOG = 12.0
# How close to the end of its gap a turn that makes room for a label goes.
END_ROOM = 16.0
# How far apart across the flow, in px, the ends of an edge are before it turns once, into the target's side, rather
# than twice.
MIN_BEND = 60.0


@dataclass
class _Run:
    """A stretch of an edge at one place across the flow: from main coordinate start to end. An end's run is where
    the edge leaves its source or comes into its target."""

    c: float
    start: float
    end: float
    end_run: bool = False


@dataclass
class _Plan:
    edge: str
    a: NodeBox
    b: NodeBox
    out: str
    into: str
    runs: list[_Run] = field(default_factory=list)
    start_shift: float = 0.0
    end_shift: float = 0.0


def lane_routes(
    d: Diagram, ends: dict[str, NodeBox], t: Theme
) -> tuple[dict[str, list[Point]], set[str], dict[str, Port], dict[str, Port]]:
    """Paths for the edges placed by layers, the edges whose first run is a trunk shared with others, and the ports
    routing chose at each end where a side is shared."""
    down = d.direction == "down"
    main, cross = (1, 0) if down else (0, 1)
    fwd_out, fwd_in = ("bottom", "top") if down else ("right", "left")
    plans: dict[str, _Plan] = {}
    for k, (way, stretches) in d.lanes.items():
        e = d.edges.get(k)
        if e is None or way == "across" or e.route is not None or e.via is not None or e.src.side or e.dst.side:
            continue
        a, b = ends.get(e.src.node), ends.get(e.dst.node)
        if a is None or b is None:
            continue
        back = way == "back"
        out, into = (fwd_in, fwd_out) if back else (fwd_out, fwd_in)
        plan = _Plan(k, a, b, out, into)
        sign = -1 if back else 1
        p0, p1 = a.port(out, e.src.offset), b.port(into, e.dst.offset)
        # Where the source's box ends, and the target's begins, along the flow: turns keep clear of their titles.
        leave = _side(a, out, main)
        arrive = _side(b, into, main)
        runs = [_Run(p0[cross], p0[main], leave, True)]
        for s, q in sorted(stretches, key=lambda pq: sign * min(pq[0][main], pq[1][main])):
            lo, hi = sorted((s[main], q[main]))
            m0, m1 = (hi, lo) if back else (lo, hi)
            runs.append(_Run(s[cross], m0, m1))
        runs.append(_Run(p1[cross], arrive, p1[main], True))
        plan.runs = runs
        plans[k] = plan

    routes: dict[str, list[Point]] = {}
    starts: dict[str, Port] = {}
    stops: dict[str, Port] = {}
    for k, pts, start, stop in _bends(d, plans, ends, t):
        routes[k] = pts
        starts[k], stops[k] = start, stop
        del plans[k]
    _spread_ends(d, plans, t)
    _snap_ends(d, plans, t)
    for plan in plans.values():
        plan.runs = _merged(_carried(plan.runs))
    turns = _turns(d, plans, main)
    for k, plan in plans.items():
        e = d.edges[k]
        p0 = plan.a.port(plan.out, e.src.offset + plan.start_shift)
        p1 = plan.b.port(plan.into, e.dst.offset + plan.end_shift)
        runs = plan.runs
        pts: list[Point] = [p0]
        for i in range(len(runs) - 1):
            m = turns[(k, i)]
            pts += [_point(m, runs[i].c, down), _point(m, runs[i + 1].c, down)]
        pts.append(p1)
        routes[k] = _clean(pts)
    for k, pts, start, stop in _outside(d, plans, routes, ends, t):
        routes[k] = pts
        starts[k], stops[k] = start, stop
        del plans[k]
    trunks = {k for k, plan in plans.items() if any(o != k and plans[o].a is plan.a for o in plans) and plan.runs}
    for k, p in plans.items():
        e = d.edges[k]
        if p.start_shift:
            starts[k] = Port(e.src.node, p.out, round(e.src.offset + p.start_shift, 2))
        if p.end_shift:
            stops[k] = Port(e.dst.node, p.into, round(e.dst.offset + p.end_shift, 2))
    return routes, trunks, starts, stops


def _bends(
    d: Diagram, plans: dict[str, _Plan], ends: dict[str, NodeBox], t: Theme
) -> list[tuple[str, list[Point], Port, Port]]:
    """Edges between neighbouring layers whose ends are far apart across the flow that can turn once, into the side
    of the target facing the source, instead of twice: an L rather than a Z. The L runs on along the source's line
    and comes into the target from above or below (beside it, when the flow runs down); when the target is the higher
    one, it leaves the source from above instead, so it never starts or ends below a node's text. It must miss every
    node and box it does not belong to and every title, and be the only edge on the side it leaves and the side it
    takes."""
    down = d.direction == "down"
    main, cross = (1, 0) if down else (0, 1)
    obstacles = _obstacles(d, ends, t)
    # How many edges leave and come into each node side by default. An L may keep a side that other edges only
    # leave by, since they leave as one trunk from its middle, but a side that arrows come into must be its own: they
    # are spread along it, and taking one of a fan off it would leave the fan lopsided.
    leaving: dict[tuple[int, str], int] = defaultdict(int)
    coming: dict[tuple[int, str], int] = defaultdict(int)
    for p in plans.values():
        leaving[(id(p.a), p.out)] += 1
        coming[(id(p.b), p.into)] += 1

    def alone(side: tuple[int, str], leaves: bool) -> bool:
        return (leaving[side], coming[side]) == ((1, 0) if leaves else (0, 1))

    found: dict[tuple[int, str], list[tuple[str, list[Point], Port, Port]]] = defaultdict(list)
    for k, p in plans.items():
        e = d.edges[k]
        runs = _merged([_Run(r.c, r.start, r.end, r.end_run) for r in p.runs])
        if len(runs) != 2 or e.src.offset or e.dst.offset:
            continue
        c0, c1 = runs[0].c, runs[1].c
        if abs(c1 - c0) < MIN_BEND:
            continue
        a, b = p.a, p.b
        lower = c1 > c0
        if lower or down:
            # Along the source's line, then into the target's near side.
            side = ("left" if c1 > c0 else "right") if down else "top"
            start = a.port(p.out)
            stop = b.port(side)
            corner = _point(stop[main], start[cross], down)
            pts, held, port = [start, corner, stop], b, Port(e.dst.node, side, 0.0)
            ports = (Port(e.src.node, p.out, 0.0), port)
        else:
            # Out of the source's top, up to the target's line, then along it.
            side = "top"
            start = a.port(side)
            stop = b.port(p.into)
            corner = _point(start[main], stop[cross], down)
            pts, held, port = [start, corner, stop], a, Port(e.src.node, side, 0.0)
            ports = (port, Port(e.dst.node, p.into, 0.0))
        if held is b:
            fits = alone((id(b), p.into), False) and coming[(id(a), p.out)] == 0
        else:
            fits = alone((id(a), p.out), True) and alone((id(b), p.into), False)
        if held.point or held.area or not fits or _blocked(pts, obstacles, a, b):
            continue
        found[(id(held), side)].append((k, pts, *ports))
    taken = _taken(d, ends)
    return [c[0] for key, c in found.items() if len(c) == 1 and key not in taken]


def _taken(d: Diagram, ends: dict[str, NodeBox]) -> set[tuple[int, str]]:
    """The node sides an edge across the flow meets, which routing here leaves to it."""
    return {
        (id(ends[end]), side)
        for k, (way, _) in d.lanes.items()
        if way == "across" and k in d.edges
        for end in (d.edges[k].src.node, d.edges[k].dst.node)
        if end in ends
        for side in ("top", "bottom", "left", "right")
    }


def _outside(
    d: Diagram, plans: dict[str, _Plan], routes: dict[str, list[Point]], ends: dict[str, NodeBox], t: Theme
) -> list[tuple[str, list[Point], Port, Port]]:
    """Backward edges that cross less going round the outside: out of the source's top (its left, when the flow
    runs down), back along a line past everything, and into the target's near side from just before the boxes it is
    in. Each backward edge takes that way, above or below everything, when it costs less than its lanes back through
    the layers, in crossings first, then bends and length; it must be the only edge on the sides it uses."""
    down = d.direction == "down"
    main, cross = (1, 0) if down else (0, 1)
    before, after = ("left", "right") if down else ("top", "bottom")
    near = "top" if down else "left"
    obstacles = _obstacles(d, ends, t)
    taken = _taken(d, ends)
    used: dict[tuple[int, str], int] = defaultdict(int)
    for p in plans.values():
        used[(id(p.a), p.out)] += 1
        used[(id(p.b), p.into)] += 1
    boxes = [n.box for n in ends.values() if not n.point]
    lo = min((r.y if not down else r.x) for r in boxes) if boxes else 0.0
    hi = max((r.y1 if not down else r.x1) for r in boxes) if boxes else 0.0
    out: list[tuple[str, list[Point], Port, Port]] = []
    lines = {before: 0, after: 0}
    for k, p in sorted(plans.items()):
        if p.out not in ("left", "top") or (id(p.b), near) in taken or used[(id(p.b), near)]:
            continue
        e = d.edges[k]
        a, b = p.a, p.b
        others = [pts for o, pts in routes.items() if o != k]
        best, cost = None, _route_cost(routes[k], others, obstacles, a, b)
        # Just before every box the target is in and the source is not, and the target itself.
        inside = set(boxes_around(d, b.node.group if not b.area else b.node.id))
        inside -= set(boxes_around(d, a.node.group if not a.area else a.node.id))
        starts = [(ends[g].box.x if not down else ends[g].box.y) for g in inside if g in ends]
        turn = min([*starts, b.box.x if not down else b.box.y]) - 16
        for side in (before, after):
            if (id(a), side) in taken or used[(id(a), side)]:
                continue
            c = lo - 24 - 12 * lines[side] if side == before else hi + 24 + 12 * lines[side]
            p0, p1 = a.port(side), b.port(near)
            pts = [p0, _point(p0[main], c, down), _point(turn, c, down), _point(turn, p1[cross], down), p1]
            # Out of a node's bottom is under its text: a little worse.
            extra = 0.0 if side == before else 10.0
            here = _route_cost(pts, others, obstacles, a, b) + extra
            if here < cost - 1:
                best, cost = (side, pts), here
        if best is not None:
            side, pts = best
            lines[side] += 1
            out.append((k, _clean(pts), Port(e.src.node, side, 0.0), Port(e.dst.node, near, 0.0)))
            routes[k] = pts
    return out


def _route_cost(
    pts: list[Point], others: list[list[Point]], obstacles: list[tuple[Rect, set[str]]], a: NodeBox, b: NodeBox
) -> float:
    """What a path costs, as the layout scorer weighs it: a crossing 20, a bend 2, a px of length 0.002, and running
    through a node, a box or a title it does not belong to far more."""
    segs = list(zip(pts, pts[1:], strict=False))
    crossings = sum(1 for s in segs for o in others for q in zip(o, o[1:], strict=False) if _cross(s, q))
    length = sum(abs(q[0] - p[0]) + abs(q[1] - p[1]) for p, q in segs)
    hits = 1000.0 if _blocked(pts, obstacles, a, b) else 0.0
    return hits + 20 * crossings + 2 * max(0, len(segs) - 1) + 0.002 * length


def _cross(s: tuple[Point, Point], t: tuple[Point, Point]) -> bool:
    """Whether a horizontal and an upright segment cross strictly inside both."""
    flat_s, flat_t = abs(s[0][1] - s[1][1]) < 0.5, abs(t[0][1] - t[1][1]) < 0.5
    if flat_s == flat_t:
        return False
    h, v = (s, t) if flat_s else (t, s)
    y, x = h[0][1], v[0][0]
    x0, x1 = sorted((h[0][0], h[1][0]))
    y0, y1 = sorted((v[0][1], v[1][1]))
    return x0 + 0.5 < x < x1 - 0.5 and y0 + 0.5 < y < y1 - 0.5


def _obstacles(d: Diagram, ends: dict[str, NodeBox], t: Theme) -> list[tuple[Rect, set[str]]]:
    """What a path must miss, each with the edge ends it may belong to: nodes, boxes and group titles."""
    out: list[tuple[Rect, set[str]]] = []
    for k, n in ends.items():
        if n.point:
            continue
        if not n.area:
            b = n.box
            out.append((Rect(b.x - 10, b.y - 10, b.w + 20, b.h + 20), {k}))
        elif k in d.groups and d.groups[k].box:
            # A box may be crossed by an edge to or from something inside it.
            inside = {x for x, m in d.nodes.items() if k in boxes_around(d, m.group)}
            inside |= {g for g in d.groups if k in boxes_around(d, g)}
            out.append((n.box, inside))
            out.append((group_title_box(d.groups[k], n.box, t), set()))
    return out


def _blocked(pts: list[Point], obstacles: list[tuple[Rect, set[str]]], a: NodeBox, b: NodeBox) -> bool:
    mine = {a.node.id, b.node.id}
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        seg = Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        for r, allowed in obstacles:
            if mine & allowed:
                continue
            if seg.x < r.x1 and r.x < seg.x1 and seg.y < r.y1 and r.y < seg.y1:
                return True
    return False


def _side(n: NodeBox, side: str, main: int) -> float:
    b = n.box
    return {"left": b.x, "right": b.x1, "top": b.y, "bottom": b.y1}[side]


def _point(m: float, c: float, down: bool) -> Point:
    return (c, m) if down else (m, c)


def _clean(pts: list[Point]) -> list[Point]:
    """pts without repeated points or points in the middle of a straight run."""
    out: list[Point] = []
    for p in pts:
        if out and abs(out[-1][0] - p[0]) < 0.01 and abs(out[-1][1] - p[1]) < 0.01:
            continue
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            if (abs(a[0] - b[0]) < 0.01 and abs(b[0] - p[0]) < 0.01) or (
                abs(a[1] - b[1]) < 0.01 and abs(b[1] - p[1]) < 0.01
            ):
                out[-1] = p
                continue
        out.append(p)
    return out


def _merged(runs: list[_Run]) -> list[_Run]:
    """Neighbouring runs at the same place across the flow, as one: at the place of the end it runs from or to."""
    out = [runs[0]]
    for r in runs[1:]:
        last = out[-1]
        if abs(r.c - last.c) < SAME and not (r.end_run and last.end_run and abs(r.c - last.c) > 0.01):
            c = last.c if last.end_run else r.c
            out[-1] = _Run(c, last.start, r.end, last.end_run or r.end_run)
        else:
            out.append(r)
    return out


def _carried(runs: list[_Run]) -> list[_Run]:
    """An end moved along its side takes the runs next to it along, as far back as the first gap with room to turn
    in: a turn right at the node would run along its side."""
    for order in (range(len(runs) - 1, 0, -1), range(0, len(runs) - 1)):
        for i in order:
            j = i - 1 if order.step < 0 else i + 1
            near, far = runs[i], runs[j]
            gap = abs(near.start - far.end) if j < i else abs(far.start - near.end)
            if abs(near.c - far.c) >= SAME and abs(near.c - far.c) <= 2 * 20.0 and gap < 8 and not far.end_run:
                far.c = near.c
    return runs


def _heading(runs: list[_Run]) -> float:
    """Where an edge runs across the flow once it has crossed the first gap from its end, runs[0]: what it heads for.
    Runs with no gap between them, such as an end and the stretch on to the end of its layer, are one place."""
    for prev, r in zip(runs, runs[1:], strict=False):
        if abs(r.start - prev.end) >= 8:
            return r.c
    return runs[-1].c


def _reversed(runs: list[_Run]) -> list[_Run]:
    return [_Run(r.c, r.end, r.start, r.end_run) for r in runs[::-1]]


def _spread_ends(d: Diagram, plans: dict[str, _Plan], t: Theme) -> None:
    """Edges that meet a node on one side meet it side by side, in the order they come from: an edge into it on its
    own point, the edges out of it, which leave as one trunk, on one point between them. An end with an offset of
    its own (one of a pair, or a port) keeps it."""
    sides: dict[tuple[int, str], list[tuple[float, str, str]]] = defaultdict(list)
    # The edges that run on straight from the side they meet, through at least the next layer.
    level: set[tuple[str, str]] = set()
    for k, p in plans.items():
        e = d.edges[k]
        if not p.a.point and not e.src.offset:
            c = _heading(p.runs)
            sides[(id(p.a), p.out)].append((c, "out", k))
            if abs(c - p.runs[0].c) < SAME:
                level.add(("out", k))
        if not p.b.point and not e.dst.offset:
            c = _heading(_reversed(p.runs))
            sides[(id(p.b), p.into)].append((c, "in", k))
            if abs(c - p.runs[-1].c) < SAME:
                level.add(("in", k))
    for (_, side), found in sides.items():
        # In the order the edges head off in, so none crosses another at the node. Edges out of the side that come
        # next to each other in that order leave as one trunk, a dashed one beside a solid one; an edge coming in
        # between them splits the trunk, rather than the trunk running across it.
        slots: list[tuple[float, list[tuple[str, str]]]] = []
        for c, kind, k in sorted(found):
            last = slots[-1][1][-1] if slots else None
            if kind == "out" and last is not None and last[0] == "out" and d.edges[last[1]].dashed == d.edges[k].dashed:
                slots[-1][1].append((kind, k))
            else:
                slots.append((c, [(kind, k)]))
        if len(slots) < 2:
            continue
        first = next(iter(found))[2]
        n = plans[first].a if any(kind == "out" and k == first for _, kind, k in found) else plans[first].b
        room = t.size("icon") - 12 if not n.area else max(0.0, (n.box.h if side in ("left", "right") else n.box.w) - 48)
        points = min(len(slots), int(room // END_STEP) + 1)
        step = min(20.0, room / (points - 1)) if points > 1 else 0.0
        shifts = [(i * points // len(slots) - (points - 1) / 2) * step for i in range(len(slots))]
        # An edge that runs straight on from the side keeps the middle, so it stays straight, when the others still
        # fit beside it.
        straight = [i for i, (_, members) in enumerate(slots) if any(m in level for m in members)]
        if len(straight) == 1:
            moved = [v - shifts[straight[0]] for v in shifts]
            if max(abs(v) for v in moved) <= room / 2:
                shifts = moved
        for (_, members), shift in zip(slots, [round(v, 1) for v in shifts], strict=True):
            for kind, k in members:
                p = plans[k]
                if kind == "out":
                    p.start_shift = shift
                    p.runs[0].c += shift
                else:
                    p.end_shift = shift
                    p.runs[-1].c += shift


def _snap_ends(d: Diagram, plans: dict[str, _Plan], t: Theme) -> None:
    """An end a little off the lane it heads for moves onto it, so the edge runs straight in rather than with a jog,
    when it stays on the node's side and clear of the other ends there."""
    room = (t.size("icon") - 12) / 2
    ends: dict[tuple[int, str], list[tuple[_Plan, bool]]] = defaultdict(list)
    for p in plans.values():
        ends[(id(p.a), p.out)].append((p, True))
        ends[(id(p.b), p.into)].append((p, False))
    for side in ends.values():
        for p, leaves in side:
            n = p.a if leaves else p.b
            if n.point or n.area:
                continue
            runs = p.runs if leaves else _reversed(p.runs)
            here, ahead = runs[0].c, _heading(runs)
            shift = p.start_shift if leaves else p.end_shift
            centre = here - shift
            want = shift + (ahead - here)
            if not SAME <= abs(ahead - here) < JOG or abs(want) > room:
                continue
            others = [(q.start_shift if lv else q.end_shift) for q, lv in side if q is not p]
            if any(abs(want - o) < END_STEP for o in others):
                continue
            if leaves:
                p.start_shift, p.runs[0].c = want, centre + want
            else:
                p.end_shift, p.runs[-1].c = want, centre + want


def _turns(d: Diagram, plans: dict[str, _Plan], main: int) -> dict[tuple[str, int], float]:
    """Where along the flow each turn is. The turns in one gap go side by side, those out of one source sharing one,
    in the order that crosses the fewest lines: a turn's vertical crosses the horizontal of every other turn that
    passes it on its way into or out of the gap. A labelled edge that turns only once turns near one end of its gap,
    so the run on the other side is long enough for its label: early when it leaves as part of a trunk, whose first
    run it shares, late otherwise, its label on the run from its source."""
    turns: list[tuple[float, float, tuple[str, int, float, float, bool, object]]] = []
    for k, p in plans.items():
        back = p.out in ("left", "top")
        for i in range(len(p.runs) - 1):
            r0, r1 = p.runs[i], p.runs[i + 1]
            lo, hi = sorted((r0.end, r1.start))
            # The first turn out of a source is shared with its other edges that leave as one trunk.
            share: object = (id(p.a), p.out, round(r0.c, 1), d.edges[k].dashed) if i == 0 else (k, i)
            turns.append((lo, hi, (k, i, r0.c, r1.c, back, share)))
    out: dict[tuple[str, int], float] = {}
    for (lo, hi), found in _gaps(turns):
        lines: dict[object, _Line] = {}
        for k, i, c0, c1, back, share in found:
            line = lines.setdefault(share, _Line())
            line.members.append((k, i))
            # Which side of the gap each horizontal comes from: a backward edge runs the other way.
            before, after = (c1, c0) if back else (c0, c1)
            line.before.add(round(before, 1))
            line.after.add(round(after, 1))
        order = _channel(list(lines.values()))
        prefs = [_prefers(d, plans, line) for line in order]
        for j, m in enumerate(_spaced(lo, hi, prefs)):
            for k, i in order[j].members:
                out[(k, i)] = m
    return out


def _gaps(
    turns: list[tuple[float, float, tuple[str, int, float, float, bool, object]]],
) -> list[tuple[tuple[float, float], list[tuple[str, int, float, float, bool, object]]]]:
    """The turns that share a gap between layers, with the stretch of it they all have room in. Each turn's room
    runs from the end of what it leaves to the start of what it comes to, which differs with the sizes of the nodes
    either side, so turns whose rooms overlap are one gap."""
    out: list[tuple[tuple[float, float], list[tuple[str, int, float, float, bool, object]]]] = []
    for lo, hi, turn in sorted(turns, key=lambda t: (t[0], t[1])):
        if out:
            (glo, ghi), members = out[-1]
            if min(ghi, hi) - max(glo, lo) >= 8:
                out[-1] = ((max(glo, lo), min(ghi, hi)), [*members, turn])
                continue
        out.append(((lo, hi), [turn]))
    return out


def _prefers(d: Diagram, plans: dict[str, _Plan], line: _Line) -> str | None:
    """Which end of its gap a line of turns would rather be at, for a label: "early", "late" or None. An edge that
    leaves its source on one line with others, a trunk, has its label after the turn."""
    for k, _ in line.members:
        p = plans[k]
        if not d.edges[k].label or len(p.runs) != 2:
            continue
        e = d.edges[k]
        trunk = any(
            q is not p
            and q.a is p.a
            and q.out == p.out
            and abs(q.runs[0].c - p.runs[0].c) < SAME
            and d.edges[q.edge].dashed == e.dashed
            for q in plans.values()
        )
        return "early" if trunk else "late"
    return None


def _spaced(lo: float, hi: float, prefs: list[str | None]) -> list[float]:
    """Where, along a gap from lo to hi, its turns go, in order: TURN_STEP apart around the middle, or, when some
    would rather be near one end, those before a split packed from the start and the rest from the end, the split
    where most get their wish."""
    n = len(prefs)
    step = min(TURN_STEP, (hi - lo) / (n + 1)) if hi > lo else 0.0
    mid = (lo + hi) / 2
    centred = [round(mid + (j - (n - 1) / 2) * step, 1) for j in range(n)]
    if not any(prefs) or hi - lo < 2 * END_ROOM + (n - 1) * TURN_STEP:
        return centred
    best = max(
        range(n + 1),
        key=lambda s: (sum(p == "early" for p in prefs[:s]) + sum(p == "late" for p in prefs[s:]), -abs(s - n / 2)),
    )
    first = [lo + END_ROOM + j * TURN_STEP for j in range(best)]
    last = [hi - END_ROOM - (n - best - 1 - j) * TURN_STEP for j in range(n - best)]
    return [round(m, 1) for m in first + last]


@dataclass
class _Line:
    """The turns of one or more edges at one place in a gap: where its horizontals meet it from before the gap and
    from after it, across the flow."""

    members: list[tuple[str, int]] = field(default_factory=list)
    before: set[float] = field(default_factory=set)
    after: set[float] = field(default_factory=set)

    @property
    def span(self) -> tuple[float, float]:
        cs = self.before | self.after
        return min(cs), max(cs)


def _cost(a: _Line, b: _Line) -> int:
    """The crossings when a turns before b: a's horizontals on to the end of the gap cross b's vertical, and b's
    horizontals from the start of the gap cross a's."""
    (alo, ahi), (blo, bhi) = a.span, b.span
    n = sum(1 for c in a.after if blo + 0.5 < c < bhi - 0.5)
    return n + sum(1 for c in b.before if alo + 0.5 < c < ahi - 0.5)


def _channel(lines: list[_Line]) -> list[_Line]:
    """The lines of one gap in the order, along the flow, that crosses the fewest: every order for a few lines, and
    for more, sorted and then improved by swapping neighbours."""
    if len(lines) <= 1:
        return lines
    pair = {(i, j): _cost(a, b) for i, a in enumerate(lines) for j, b in enumerate(lines) if i != j}

    def total(order: tuple[int, ...] | list[int]) -> int:
        return sum(pair[(order[x], order[y])] for x in range(len(order)) for y in range(x + 1, len(order)))

    # Lines heading towards higher cross values turn earlier the further along they start, and those heading the
    # other way earlier the further back: the order to start from, and the one kept on a tie.
    def key(i: int) -> tuple[int, float]:
        ln = lines[i]
        rise = sum(ln.after) / len(ln.after) - sum(ln.before) / len(ln.before)
        c0 = min(ln.before) if rise <= 0 else max(ln.before)
        return (0, -c0) if rise > 0 else (1, c0)

    start = sorted(range(len(lines)), key=key)
    if len(lines) <= 7:
        best = min(permutations(start), key=lambda o: (total(o), [start.index(i) for i in o]))
        return [lines[i] for i in best]
    order = list(start)
    better = True
    while better:
        better = False
        for x in range(len(order) - 1):
            a, b = order[x], order[x + 1]
            if pair[(b, a)] < pair[(a, b)]:
                order[x], order[x + 1] = b, a
                better = True
    return [lines[i] for i in order]
