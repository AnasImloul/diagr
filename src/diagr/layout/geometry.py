from __future__ import annotations

from dataclasses import dataclass, field

from ..model import Edge, Group, Node, Port
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
    # A group's box as an edge end: its ports are on the box's sides, offsets measured from their middles.
    area: bool = False
    # A point, not a box (a junction): edges meet at its middle, and it covers nothing.
    point: bool = False

    def port(self, side: str, offset: float = 0.0) -> Point:
        if self.point:
            return (self.x, self.y)
        if self.area:
            b = self.box
            return {
                "left": (b.x, self.y + offset),
                "right": (b.x1, self.y + offset),
                "top": (self.x + offset, b.y),
            }.get(side, (self.x + offset, b.y1))
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
    badge_at: Point | None = None
    badge_box: Rect | None = None
    # False when the edge ends at a box behind another and stops where it meets the one in front.
    tip: bool = True
    # What routing chose that the edge does not say: the port it ends at, when it meets a side along with other edges,
    # and where along the path (0 to 1) the label sits, when it moved past a trunk.
    port: Port | None = None
    label_frac: float | None = None
    # The port it starts at, when routing moved it along a side it shares with other edges.
    start: Port | None = None


@dataclass
class Layout:
    nodes: dict[str, NodeBox]
    groups: dict[str, Rect]
    edges: dict[str, EdgePath]
    bounds: Rect
    # Group -> the boxes stacked behind it, nearest first, as (id, rect).
    layers: dict[str, list[tuple[str, Rect]]] = field(default_factory=dict)


def node_box(n: Node, x: float, y: float, t: Theme, slots: int) -> NodeBox:
    if n.junction:
        return NodeBox(n, x, y, y, [], None, None, None, y, Rect(x - 4, y - 4, 8, 8), point=True)
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
        # Wide enough for the play icon, the gap and the label, with at least 12px each side.
        w = max(BUTTON_W, text_width(n.trigger, 14, 600) + 18 + 24)
        button = Rect(x - w / 2, bottom + 17, w, BUTTON_H)
        bottom = button.y1 + 4
    widths = [text_width(n.title, t.size("title"), 600)] + [text_width(s, t.size("sub")) for s in n.sub]
    if strip:
        widths.append(strip.w)
    if button:
        widths.append(button.w)
    half_w = max([half + 4] + [w / 2 for w in widths])
    top = y - half - 14
    return NodeBox(
        n,
        x,
        y,
        title_y,
        sub_ys,
        strip,
        caption_y,
        button,
        bottom,
        Rect(x - half_w, top, 2 * half_w, bottom - top),
        half + 4,
    )


def ink(n: NodeBox) -> list[Rect]:
    """What of a node shows, as rects: its icon, with the room above it for a step badge, and the text, cells and
    button below it. Its box also covers the empty corners beside the icon where the text is wider."""
    b, r = n.box, n.reach
    icon = Rect(n.x - r - 6, b.y, 2 * (r + 6), n.y + r - b.y)
    below = Rect(b.x, n.y + r, b.w, b.y1 - n.y - r)
    return [icon, below]


def title_width(g: Group, t: Theme) -> float:
    w = text_width(g.title, t.size("group_title"), 600)
    if g.icon:
        w += t.size("group_icon") + 8
    if g.sub:
        w += 8 + text_width(g.sub, t.size("group_sub"))
    return w


# How far each box stacked behind a group sits up and to the left of the one in front, in px.
BEHIND_X, BEHIND_Y = 24, 28


def stack_reach(g: Group) -> tuple[float, float]:
    """How far the boxes stacked behind g reach up and to the left of it, in px."""
    return BEHIND_X * len(g.behind), BEHIND_Y * len(g.behind)


def stack(g: Group, r: Rect) -> list[tuple[str, Rect]]:
    """The boxes stacked behind g, nearest first, when g's box is r."""
    return [(lid, Rect(r.x - BEHIND_X * i, r.y - BEHIND_Y * i, r.w, r.h)) for i, lid in enumerate(g.behind, 1)]


def title_place(g: Group) -> str:
    return g.title_at or ("top-left" if g.behind else "bottom-left")


def title_on_top(g: Group) -> bool:
    return title_place(g).startswith("top")


def behind_title_box(g: Group, title: str, r: Rect, t: Theme) -> Rect:
    """A stacked box's title, in the strip along its top that the box in front leaves showing: at the left, or
    centred when the group's title is."""
    w = text_width(title, t.size("group_title"), 600)
    x = r.x + (r.w - w) / 2 if title_place(g) in ("top", "bottom") else r.x + 16
    return Rect(x, r.y + 4, w, t.size("group_title") + 4)


def heading_size(t: Theme) -> float:
    """The size of a `title_at: middle` heading: a step up from a box title."""
    return round(t.size("group_title") * 1.3, 1)


def middle_title_box(g: Group, r: Rect, t: Theme, members: list[Rect]) -> Rect:
    """A heading with the sub text on the line below, centred top to bottom, just right of the box's own nodes."""
    hs = heading_size(t)
    icon = t.size("group_icon") + 8 if g.icon else 0
    w = icon + max(text_width(g.title, hs, 700), text_width(g.sub, t.size("group_sub")) if g.sub else 0)
    h = hs + (t.size("line") + 2 if g.sub else 0) + 4
    beside = [m for m in members if m.y < r.y1 and r.y < m.y1]
    x = max([r.x + 16] + [m.x1 + 24 for m in beside])
    return Rect(x, r.y + (r.h - h) / 2, w, h)


def group_title_box(g: Group, r: Rect, t: Theme, members: list[Rect] | None = None) -> Rect:
    """Where the title (with icon and sub text) is drawn, by `title_at`: along the bottom (baseline 16px above the
    edge) or the top, at the left or centred, or as a heading in the middle. A stack's top title sits in the same
    strip as those of the boxes behind it. `members` are the boxes of the group's own nodes, which a middle heading
    sits beside."""
    place, w = title_place(g), title_width(g, t)
    if place == "middle":
        return middle_title_box(g, r, t, members or [])
    h = max(t.size("group_title"), t.size("group_icon") if g.icon else 0)
    x = r.x + (r.w - w) / 2 if place in ("top", "bottom") else r.x + 16
    if not place.startswith("top"):
        return Rect(x, r.y1 - 16 - h, w, h + 4)
    return Rect(x, r.y + (4 if g.behind else 14), w, h + 4)


def title_band(g: Group, t: Theme) -> tuple[float, float]:
    """Room a fitted group leaves above and below what it holds: the title's side gets the band for it."""
    inset = t.size("group_inset")
    if title_place(g) == "middle":
        return inset, inset
    if not title_on_top(g):
        return inset, 2 * t.size("group_bottom")
    return (BEHIND_Y if g.behind else group_title_box(g, Rect(0, 0, 0, 0), t).y1 + 10), inset
