"""Lay out a whole diagram: place its nodes and boxes, line them up, and route its edges."""

from __future__ import annotations

from ..model import Diagram, Group, Node
from ..scenario import walk_effects
from ..theme import Theme
from .flow import flow
from .geometry import (
    BEHIND_X,
    BEHIND_Y,
    Layout,
    NodeBox,
    Rect,
    _title_width,
    behind_title_box,
    group_title_box,
    middle_title_box,
    node_box,
    title_band,
    title_place,
)
from .route import auto_routes, route_edge


def sub_slots(d: Diagram) -> dict[str, int]:
    """How many sub lines each node needs: its own, or more if a scenario sets a later line."""
    slots = {k: len(n.sub) for k, n in d.nodes.items()}
    for sc in d.scenarios.values():
        for e in walk_effects(sc):
            if e.verb == "set" and e.targets:
                parts = e.targets[0].split(".")
                if len(parts) >= 2 and parts[0] in slots and parts[1] == "sub":
                    need = int(parts[2]) + 1 if len(parts) > 2 and parts[2].isdigit() else 1
                    slots[parts[0]] = max(slots[parts[0]], need)
    return slots


def footprint(r: Rect, layers: list[tuple[str, Rect]]) -> Rect:
    for _, b in layers:
        r = r.union(b)
    return r


def group_depth(d: Diagram, gid: str) -> int:
    depth, seen = 0, {gid}
    parent = d.groups[gid].parent
    while parent in d.groups and parent not in seen:
        seen.add(parent)
        depth += 1
        parent = d.groups[parent].parent
    return depth


def group_rect(
    g: Group, d: Diagram, t: Theme, boxes: dict[str, NodeBox], children: list[Rect] | None = None
) -> Rect | None:
    """A fixed group covers its cells. A fitted one surrounds its nodes and child groups, title band below."""
    children = children or []
    col, row = d.grid.col, d.grid.row
    inset = t.size("group_inset")
    cells = None
    if g.at is not None:
        c0, r0 = g.at
        cw, rh = g.span or (1, 1)
        cells = (c0, c0 + cw - 1, r0, r0 + rh - 1)
    else:
        # Where the nodes are, in cells: their `at`, or where `align_x`/`align_y` moved them.
        members = [(b.x / col, b.y / row) for b in boxes.values() if b.node.group == g.id]
        if members:
            cells = (
                min(m[0] for m in members),
                max(m[0] for m in members),
                min(m[1] for m in members),
                max(m[1] for m in members),
            )
        elif not children:
            return None
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    if cells:
        c0, c1, r0, r1 = cells
        x0 = c0 * col - col / 2 + inset
        x1 = c1 * col + col / 2 - inset
        y0 = r0 * row - row / 2 - t.size("group_top")
        y1 = r1 * row + row / 2 + t.size("group_bottom")
    if g.at is None:
        # A stack's title sits in a strip along its top, like those of the boxes behind it; any other group's sits
        # in a band along its bottom.
        top, bottom = title_band(g, t)
        members = [b.box for b in boxes.values() if b.node.group == g.id]
        if members:
            y1 = max(y1, max(m.y1 for m in members) + bottom)
        for c in children:
            x0, x1 = min(x0, c.x - inset), max(x1, c.x1 + inset)
            y0, y1 = min(y0, c.y - top), max(y1, c.y1 + bottom)
    if title_place(g) == "middle":
        # Wide enough for the heading beside the nodes, and tall enough for its two lines.
        own = [b.box for b in boxes.values() if b.node.group == g.id]
        head = middle_title_box(g, Rect(x0, y0, x1 - x0, y1 - y0), t, own)
        x1 = max(x1, head.x1 + 16)
        if head.h + 2 * inset > y1 - y0:
            grow = (head.h + 2 * inset - (y1 - y0)) / 2
            y0, y1 = y0 - grow, y1 + grow
    else:
        x1 = max(x1, x0 + 32 + _title_width(g, t))
    return Rect(x0, y0, x1 - x0, y1 - y0)


def align(d: Diagram, keys: list[str], rects: dict[str, Rect], nodes: dict[str, NodeBox]) -> None:
    """Line up sibling boxes that nearly line up: boxes one above the other share their left and right edges when
    those are within a grid column of each other, boxes side by side their top and bottom edges within a row. Boxes
    only grow, and a side moves only if the grown box covers no node or box it did not cover already."""

    def inside(n: str, k: str) -> bool:
        g, seen = d.nodes[n].group, set()
        while g in d.groups and g not in seen:
            if g == k:
                return True
            seen.add(g)
            g = d.groups[g].parent
        return False

    def safe(k: str, new: Rect) -> bool:
        old = rects[k]
        pad = Rect(new.x - 8, new.y - 8, new.w + 16, new.h + 16)
        for n, nb in nodes.items():
            if not inside(n, k) and nb.box.overlaps(pad) and not nb.box.overlaps(old):
                return False
        for g, r in rects.items():
            if g != k and g in keys and r.overlaps(pad) and not r.overlaps(old):
                return False
        return True

    def grow(k: str, x0: float, y0: float, x1: float, y1: float) -> bool:
        r = rects[k]
        new = Rect(min(r.x, x0), min(r.y, y0), max(r.x1, x1) - min(r.x, x0), max(r.y1, y1) - min(r.y, y0))
        if new == r or not safe(k, new):
            return False
        rects[k] = new
        return True

    def between(a: str, b: str, keys: list[str], rects: dict[str, Rect]) -> bool:
        """Whether another sibling box sits between a and b, so they are not neighbours."""
        ra, rb = rects[a], rects[b]
        for c in keys:
            if c in (a, b) or d.groups[c].parent != d.groups[a].parent:
                continue
            rc = rects[c]
            gap_x = rc.x >= min(ra.x1, rb.x1) - 0.5 and rc.x1 <= max(ra.x, rb.x) + 0.5
            gap_y = rc.y >= min(ra.y1, rb.y1) - 0.5 and rc.y1 <= max(ra.y, rb.y) + 0.5
            overlap_y = rc.y < max(ra.y1, rb.y1) and min(ra.y, rb.y) < rc.y1
            overlap_x = rc.x < max(ra.x1, rb.x1) and min(ra.x, rb.x) < rc.x1
            if (gap_x and overlap_y) or (gap_y and overlap_x):
                return True
        return False

    inf = float("inf")
    for _ in range(4):
        changed = False
        for i, a in enumerate(keys):
            for b in keys[i + 1 :]:
                if d.groups[a].parent != d.groups[b].parent:
                    continue
                ra, rb = rects[a], rects[b]
                across = min(ra.x1, rb.x1) - max(ra.x, rb.x) > 0
                down = min(ra.y1, rb.y1) - max(ra.y, rb.y) > 0
                if between(a, b, keys, rects):
                    continue
                moves: list[tuple[str, float, float, float, float]] = []
                if across and not down:
                    if 0.5 < abs(ra.x - rb.x) <= d.grid.col:
                        k = a if ra.x > rb.x else b
                        moves.append((k, min(ra.x, rb.x), inf, -inf, -inf))
                    if 0.5 < abs(ra.x1 - rb.x1) <= d.grid.col:
                        k = a if ra.x1 < rb.x1 else b
                        moves.append((k, inf, inf, max(ra.x1, rb.x1), -inf))
                if down and not across:
                    if 0.5 < abs(ra.y - rb.y) <= d.grid.row:
                        k = a if ra.y > rb.y else b
                        moves.append((k, inf, min(ra.y, rb.y), -inf, -inf))
                    if 0.5 < abs(ra.y1 - rb.y1) <= d.grid.row:
                        k = a if ra.y1 < rb.y1 else b
                        moves.append((k, inf, inf, -inf, max(ra.y1, rb.y1)))
                for k, x0, y0, x1, y1 in moves:
                    changed = grow(k, x0, y0, x1, y1) or changed
        if not changed:
            return


def stack(d: Diagram, k: str, r: Rect) -> list[tuple[str, Rect]]:
    return [
        (lid, Rect(r.x - BEHIND_X * i, r.y - BEHIND_Y * i, r.w, r.h)) for i, lid in enumerate(d.groups[k].behind, 1)
    ]


def follow(d: Diagram, t: Theme, k: str, old: Rect, rects: dict[str, Rect], fixed: set[str]) -> None:
    """After alignment moved a side of box k, its child boxes that sat flush with that side (the usual padding in
    from it) move with it, and so on down."""
    new, inset = rects[k], t.size("group_inset")
    top, bottom = title_band(d.groups[k], t)
    for c, cg in d.groups.items():
        if cg.parent != k or c not in rects or c in fixed:
            continue
        r = rects[c]
        ex, ey = BEHIND_X * len(cg.behind), BEHIND_Y * len(cg.behind)
        x0, y0, x1, y1 = r.x - ex, r.y - ey, r.x1, r.y1
        if new.x < old.x - 0.5 and abs(x0 - (old.x + inset)) < 1.5:
            x0 = new.x + inset
        if new.x1 > old.x1 + 0.5 and abs(x1 - (old.x1 - inset)) < 1.5:
            x1 = new.x1 - inset
        if new.y < old.y - 0.5 and abs(y0 - (old.y + top)) < 1.5:
            y0 = new.y + top
        if new.y1 > old.y1 + 0.5 and abs(y1 - (old.y1 - bottom)) < 1.5:
            y1 = new.y1 - bottom
        moved = Rect(x0 + ex, y0 + ey, x1 - x0 - ex, y1 - y0 - ey)
        if moved != r:
            rects[c] = moved
            follow(d, t, c, r, rects, fixed)


def recentre(
    d: Diagram,
    t: Theme,
    sized: dict[str, Rect],
    rects: dict[str, Rect],
    nodes: dict[str, NodeBox],
    slots: dict[str, int],
    fixed: set[str],
) -> None:
    """Keep what a box holds where it was relative to the box after alignment grew it: its pinned nodes and the child
    boxes that did not grow with it move by the shift of the box's middle. On each axis the move is skipped if it would
    bend an edge that runs straight along it to a node outside, or one with its own route or via."""
    for k in sorted(rects, key=lambda k: group_depth(d, k)):
        old, new = sized[k], rects[k]
        if old == new or k in fixed:
            continue
        still = [c for c, cg in d.groups.items() if cg.parent == k and c in rects and rects[c] == sized[c]]
        boxes = set(still)
        for c in list(still):
            boxes |= {g for g in d.groups if g in rects and _inside(d, g, c)}
        moving = {n for n, nb in nodes.items() if nb.node.group == k or nb.node.group in boxes}
        if any(nodes[n].node.auto for n in moving):
            # Placed nodes are where the placer put them; `diagr expand` pins them there.
            continue
        shift = [(new.x + new.w / 2) - (old.x + old.w / 2), (new.y + new.h / 2) - (old.y + old.h / 2)]
        for e in d.edges.values():
            ends = (e.src.node, e.dst.node)
            inside = [n in moving for n in ends]
            if not any(inside) or all(inside):
                continue
            if e.route is not None or e.via is not None:
                shift = [0.0, 0.0]
                break
            a, b = (nodes.get(n) for n in ends)
            if a is not None and b is not None:
                if abs(a.x - b.x) < 0.5:
                    shift[0] = 0.0
                if abs(a.y - b.y) < 0.5:
                    shift[1] = 0.0
        dx, dy = shift
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            continue
        for n in moving:
            nb = nodes[n]
            nodes[n] = node_box(nb.node, nb.x + dx, nb.y + dy, t, slots[n])
        for g in boxes:
            r = rects[g]
            rects[g] = sized[g] = Rect(r.x + dx, r.y + dy, r.w, r.h)


def _inside(d: Diagram, gid: str, outer: str) -> bool:
    g, seen = d.groups[gid].parent, set()
    while g in d.groups and g not in seen:
        if g == outer:
            return True
        seen.add(g)
        g = d.groups[g].parent
    return False


def line_up(
    d: Diagram, t: Theme, centres: dict[str, tuple[float, float]], frames: dict[str, Rect], slots: dict[str, int]
) -> None:
    """Move nodes with `align_x` or `align_y` onto the x or y of the node they name, targets first. A node in a
    laid-out box stays inside it, its padding included."""
    done: set[str] = set()

    def settle(k: str, seen: tuple[str, ...]) -> None:
        if k in done or k in seen or k not in centres:
            return
        n = d.nodes[k]
        for target in (n.align_x, n.align_y):
            if target in d.nodes:
                settle(target, (*seen, k))
        done.add(k)
        if not (n.align_x in centres or n.align_y in centres):
            return
        x, y = centres[k]
        frame = frames.get(n.group or "")
        box = node_box(n, 0, 0, t, slots[k]).box
        # Only the axis lined up moves, and in a laid-out box, only as far as its padding.
        if n.align_x in centres:
            x = centres[n.align_x][0]
            if frame is not None:
                x = min(max(x, frame.x + 20 - box.x), frame.x1 - 20 - box.x1)
        if n.align_y in centres:
            y = centres[n.align_y][1]
            if frame is not None:
                y = min(max(y, frame.y + 20 - box.y), frame.y1 - 20 - box.y1)
        centres[k] = (x, y)

    for k, n in d.nodes.items():
        if n.align_x or n.align_y:
            settle(k, ())


def layout(d: Diagram, t: Theme) -> Layout:
    slots = sub_slots(d)
    # Nodes and groups in a `layout` box get their places from it; the rest from their cells.
    centres, frames = flow(d, t, slots)
    for k, n in d.nodes.items():
        if k not in centres and n.at is not None:
            centres[k] = (n.at[0] * d.grid.col, n.at[1] * d.grid.row)
    line_up(d, t, centres, frames, slots)
    nodes = {k: node_box(d.nodes[k], x, y, t, slots[k]) for k, (x, y) in centres.items()}
    fitted: dict[str, Rect] = {}
    sized: dict[str, Rect] = {}
    layers: dict[str, list[tuple[str, Rect]]] = {}
    # Deepest groups first, a level at a time, so each parent fits around children already lined up, boxes stacked
    # behind them included.
    for depth in sorted({group_depth(d, k) for k in d.groups}, reverse=True):
        level = [k for k in d.groups if group_depth(d, k) == depth]
        for k in level:
            children = [
                footprint(fitted[c], layers.get(c, [])) for c, cg in d.groups.items() if cg.parent == k and c in fitted
            ]
            r = frames.get(k) or group_rect(d.groups[k], d, t, nodes, children)
            if r:
                fitted[k] = sized[k] = r
        if d.align:
            # Line up whole stacks: each box with the boxes stacked behind it, then put the front box back inside.
            keys = [k for k in level if k in fitted and k not in frames]
            ext = {k: (BEHIND_X * len(d.groups[k].behind), BEHIND_Y * len(d.groups[k].behind)) for k in keys}
            hull = {
                k: Rect(r.x - ext[k][0], r.y - ext[k][1], r.w + ext[k][0], r.h + ext[k][1])
                for k, r in fitted.items()
                if k in ext
            }
            align(d, keys, hull, nodes)
            for k in keys:
                (ex, ey), r = ext[k], hull[k]
                old, fitted[k] = fitted[k], Rect(r.x + ex, r.y + ey, r.w - ex, r.h - ey)
                if fitted[k] != old:
                    follow(d, t, k, old, fitted, set(frames))
        for k in level:
            if k in fitted and d.groups[k].behind:
                layers[k] = stack(d, k, fitted[k])
    if d.align:
        recentre(d, t, sized, fitted, nodes, slots, set(frames))
    # A box may have grown with its parent since its level: place the boxes behind it again.
    layers = {k: stack(d, k, fitted[k]) for k in layers}
    # Outer groups first, so inner ones are drawn on top and fill_at() finds the innermost.
    groups = {k: fitted[k] for k in sorted(fitted, key=lambda k: group_depth(d, k))}
    auto, trunks, ports = auto_routes(d, nodes, groups, t)
    ends = dict(nodes)
    covers: dict[str, list[Rect]] = {}
    boxes = [(k, k, r) for k, r in groups.items()] + [(k, lid, r) for k, ls in layers.items() for lid, r in ls]
    for k, end, r in boxes:
        cx, cy = r.x + r.w / 2, r.y + r.h / 2
        ends[end] = NodeBox(Node(end, None, group=k), cx, cy, cy, [], None, None, None, r.y1, r, area=True)
    for k, ls in layers.items():
        for i, (lid, _) in enumerate(ls):
            covers[lid] = [groups[k]] + [r for _, r in ls[:i]]
    # Titles, so a straight edge between two boxes can pick a line that misses them.
    titles = [
        group_title_box(d.groups[k], r, t, [nb.box for nb in nodes.values() if nb.node.group == k])
        for k, r in groups.items()
        if d.groups[k].box
    ] + [behind_title_box(d.groups[k], d.groups[k].behind[lid], r, t) for k, ls in layers.items() for lid, r in ls]
    edges = {
        k: route_edge(e, ends, d, t, auto.get(k), covers, titles, k in trunks, ports.get(k))
        for k, e in d.edges.items()
        if e.src.node in ends and e.dst.node in ends
    }

    rects = list(groups.values()) + [b.box for b in nodes.values()] + [r for ls in layers.values() for _, r in ls]
    rects += [p.label_box for p in edges.values() if p.label_box]
    rects += [p.badge_box for p in edges.values() if p.badge_box]
    for p in edges.values():
        xs, ys = [q[0] for q in p.points], [q[1] for q in p.points]
        rects.append(Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
    bounds = rects[0]
    for r in rects[1:]:
        bounds = bounds.union(r)
    m = t.size("margin")
    bounds = Rect(bounds.x - m, bounds.y - m, bounds.w + 2 * m, bounds.h + 2 * m)
    return Layout(nodes, groups, edges, bounds, layers)
