from __future__ import annotations

from dataclasses import dataclass, field

from ..model import Diagram, Edge, Group, Node
from ..theme import Theme
from .text import text_width

Point = tuple[float, float]

CELL_H = 18
CELL_W = 18
CELL_GAP = 5
STRIP_PAD = 8
STRIP_H = 32
BUTTON_W = 132
BUTTON_H = 34


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def x1(self) -> float:
        return self.x + self.w

    @property
    def y1(self) -> float:
        return self.y + self.h

    def contains(self, p: Point) -> bool:
        return self.x <= p[0] <= self.x1 and self.y <= p[1] <= self.y1

    def overlaps(self, o: Rect) -> bool:
        return self.x < o.x1 and o.x < self.x1 and self.y < o.y1 and o.y < self.y1

    def union(self, o: Rect) -> Rect:
        x, y = min(self.x, o.x), min(self.y, o.y)
        return Rect(x, y, max(self.x1, o.x1) - x, max(self.y1, o.y1) - y)


@dataclass
class NodeBox:
    node: Node
    x: float
    y: float
    title_y: float
    sub_ys: list[float]
    strip: Rect | None
    caption_y: float | None
    button: Rect | None
    bottom: float
    box: Rect
    reach: float = 0

    def port(self, side: str, offset: float = 0.0) -> Point:
        if self.node.junction:
            return (self.x, self.y)
        half = self.reach
        if side == "left":
            return (self.x - half, self.y + offset)
        if side == "right":
            return (self.x + half, self.y + offset)
        if side == "top":
            return (self.x + offset, self.y - half)
        return (self.x + offset, self.bottom)


@dataclass
class EdgePath:
    edge: Edge
    points: list[Point]
    label_at: Point | None
    label_box: Rect | None
    problems: list[str] = field(default_factory=list)


@dataclass
class Layout:
    nodes: dict[str, NodeBox]
    groups: dict[str, Rect]
    edges: dict[str, EdgePath]
    bounds: Rect


def sub_slots(d: Diagram) -> dict[str, int]:
    """How many sub lines each node needs: its own, or more if the scenario sets a later line."""
    slots = {k: len(n.sub) for k, n in d.nodes.items()}
    if d.scenario:
        from ..scenario import walk_effects
        for e in walk_effects(d.scenario):
            if e.verb == "set" and e.targets:
                parts = e.targets[0].split(".")
                if len(parts) >= 2 and parts[0] in slots and parts[1] == "sub":
                    need = int(parts[2]) + 1 if len(parts) > 2 and parts[2].isdigit() else 1
                    slots[parts[0]] = max(slots[parts[0]], need)
    return slots


def node_box(n: Node, x: float, y: float, t: Theme, slots: int) -> NodeBox:
    if n.junction:
        return NodeBox(n, x, y, y, [], None, None, None, y, Rect(x - 4, y - 4, 8, 8))
    half = t.size("icon") / 2
    title_y = y + half + 20
    sub_ys = [title_y + t.size("line") * (j + 1) for j in range(slots)]
    last = sub_ys[-1] if sub_ys else title_y
    strip = caption_y = None
    if n.cells:
        w = len(n.cells) * (CELL_W + CELL_GAP) - CELL_GAP + 2 * STRIP_PAD
        strip = Rect(x - w / 2, last + 8, w, STRIP_H)
        caption_y = strip.y1 + t.size("line")
        last = caption_y if any(n.cells) else strip.y1 - 4
    bottom = last + 4
    button = None
    if n.trigger:
        button = Rect(x - BUTTON_W / 2, bottom + 17, BUTTON_W, BUTTON_H)
        bottom = button.y1 + 4
    widths = [text_width(n.title, t.size("title"), 600)] + [text_width(s, t.size("sub")) for s in n.sub]
    if strip:
        widths.append(strip.w)
    if button:
        widths.append(BUTTON_W)
    half_w = max([half + 4] + [w / 2 for w in widths])
    top = y - half - 14
    return NodeBox(n, x, y, title_y, sub_ys, strip, caption_y, button, bottom,
                   Rect(x - half_w, top, 2 * half_w, bottom - top), half + 4)


def group_rect(g: Group, d: Diagram, t: Theme, boxes: dict[str, NodeBox]) -> Rect | None:
    if g.at is not None:
        c0, r0 = g.at
        cw, rh = g.span or (1, 1)
        c1, r1 = c0 + cw - 1, r0 + rh - 1
    else:
        members = [n.at for n in d.nodes.values() if n.group == g.id]
        if not members:
            return None
        c0, c1 = min(m[0] for m in members), max(m[0] for m in members)
        r0, r1 = min(m[1] for m in members), max(m[1] for m in members)
    col, row = d.grid.col, d.grid.row
    inset = t.size("group_inset")
    x0 = c0 * col - col / 2 + inset
    x1 = c1 * col + col / 2 - inset
    y0 = r0 * row - row / 2 - t.size("group_top")
    y1 = r1 * row + row / 2 + t.size("group_bottom")
    members = [b.box for b in boxes.values() if b.node.group == g.id]
    if members and g.at is None:
        y1 = max(y1, max(m.y1 for m in members) + 2 * t.size("group_bottom"))
    need = 32 + text_width(g.title, t.size("group_title"), 600)
    if g.icon:
        need += t.size("group_icon") + 8
    if g.sub:
        need += 8 + text_width(g.sub, t.size("group_sub"))
    x1 = max(x1, x0 + need)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def layout(d: Diagram, t: Theme) -> Layout:
    from .route import route_edge

    slots = sub_slots(d)
    nodes = {k: node_box(n, n.at[0] * d.grid.col, n.at[1] * d.grid.row, t, slots[k]) for k, n in d.nodes.items()}
    groups = {}
    for k, g in d.groups.items():
        r = group_rect(g, d, t, nodes)
        if r:
            groups[k] = r
    edges = {k: route_edge(e, nodes, d, t) for k, e in d.edges.items()
             if e.src.node in nodes and e.dst.node in nodes}

    rects = list(groups.values()) + [b.box for b in nodes.values()]
    rects += [p.label_box for p in edges.values() if p.label_box]
    for p in edges.values():
        xs, ys = [q[0] for q in p.points], [q[1] for q in p.points]
        rects.append(Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
    bounds = rects[0]
    for r in rects[1:]:
        bounds = bounds.union(r)
    m = t.size("margin")
    bounds = Rect(bounds.x - m, bounds.y - m, bounds.w + 2 * m, bounds.h + 2 * m)
    return Layout(nodes, groups, edges, bounds)
