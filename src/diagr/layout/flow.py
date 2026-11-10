"""Row and column layout, like CSS flexbox: a group (or the diagram) with `layout` places its nodes and child groups
one after another in file order, sized by what they hold, instead of by grid cells.

Measuring goes inside out (a box is as big as its contents plus padding and its title's band); placing goes outside
in. Inside a laid-out box every node and group is laid out too: a child group without `layout` is a column.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model import Diagram, Flow, Group
from ..theme import Theme
from .geometry import (
    Rect,
    _title_width,
    group_title_box,
    middle_title_box,
    node_box,
    stack_reach,
    title_band,
    title_on_top,
    title_place,
)

PAD = 20  # Space inside a laid-out box, on the sides without a title.
HEADING_GAP = 24  # Space between a box's nodes and a `title_at: middle` heading.
BADGE_ROOM = 14  # Room a node's box keeps above its icon, for a step badge.


@dataclass
class _Item:
    kind: str  # "node" or "group"
    id: str
    w: float = 0
    h: float = 0
    ox: float = 0  # For a node: its box's top-left relative to its centre.
    oy: float = 0
    core: float = 0  # For a node: the height of its icon and labels, without the trigger button hanging below.


def laid_out(d: Diagram) -> tuple[set[str], set[str]]:
    """The nodes and groups whose places come from a layout rather than from their cells."""
    if d.flow is not None:
        return set(d.nodes), set(d.groups)
    groups = {k for k in d.groups if _under_flow(d, k)}
    nodes = {k for k, n in d.nodes.items() if n.group in groups}
    return nodes, groups


def _under_flow(d: Diagram, gid: str) -> bool:
    g, seen = gid, set()
    while g in d.groups and g not in seen:
        if d.groups[g].flow is not None:
            return True
        seen.add(g)
        g = d.groups[g].parent
    return False


def flow(d: Diagram, t: Theme, slots: dict[str, int]) -> tuple[dict[str, tuple[float, float]], dict[str, Rect]]:
    """Node centres and group boxes, in px, for everything laid out."""
    nodes, groups = laid_out(d)
    centres: dict[str, tuple[float, float]] = {}
    frames: dict[str, Rect] = {}
    if not groups and not nodes:
        return centres, frames
    lay = _Layout(d, t, slots, nodes, groups, centres, frames)
    if d.flow is not None:
        items = lay.children(None)
        w, h = lay.measure_items(items, d.flow, 0, 0)
        lay.place_items(items, d.flow, Rect(0, 0, w, h))
    else:
        for k in groups:
            parent = d.groups[k].parent
            if parent in groups:
                continue
            item = lay.item("group", k)
            g = d.groups[k]
            x = y = 0.0
            if g.at is not None:
                x = g.at[0] * d.grid.col - d.grid.col / 2 + t.size("group_inset")
                y = g.at[1] * d.grid.row - d.grid.row / 2 - t.size("group_top")
            lay.place(item, Rect(x, y, item.w, item.h))
    return centres, frames


class _Layout:
    def __init__(self, d, t, slots, nodes, groups, centres, frames):
        self.d, self.t, self.slots = d, t, slots
        self.nodes, self.groups = nodes, groups
        self.centres, self.frames = centres, frames
        self.sizes: dict[str, tuple[float, float]] = {}

    def children(self, gid: str | None) -> list[_Item]:
        """A group's nodes and child groups, in the order they appear in the file."""
        d = self.d
        found = [(g.loc, "group", k) for k, g in d.groups.items() if g.parent == gid and k in self.groups]
        found += [(n.loc, "node", k) for k, n in d.nodes.items() if n.group == gid and k in self.nodes]
        found.sort(key=lambda f: (f[0].file, f[0].line, f[0].col) if f[0] else ("", 0, 0))
        return [self.item(kind, k) for _, kind, k in found]

    def item(self, kind: str, k: str) -> _Item:
        if kind == "node":
            # Measured from the top of the icon to the bottom of the labels: what shows. The node's box also keeps
            # room above the icon for a step badge, which would make the node look low when centred.
            n = self.d.nodes[k]
            nb = node_box(n, 0, 0, self.t, self.slots[k])
            top = nb.box.y if n.junction else -self.t.size("icon") / 2
            core = (nb.button.y - 17 if nb.button else nb.box.y1) - top
            return _Item("node", k, nb.box.w, nb.box.y1 - top, nb.box.x, top, core)
        w, h = self.measure_group(k)
        return _Item("group", k, w, h)

    def pads(self, g: Group) -> tuple[float, float, float, float]:
        """Left, top, right and bottom space inside a group, its title's band and a stack's offsets included."""
        if not g.box:
            return 0, 0, 0, 0
        top, bottom = title_band(g, self.t)
        if title_on_top(g):
            # Nodes are measured from their icons, but keep room above for a step badge, clear of the title.
            top += BADGE_ROOM
        return PAD, max(PAD, top), PAD, max(PAD, bottom)

    def measure_group(self, k: str) -> tuple[float, float]:
        if k in self.sizes:
            return self.sizes[k]
        g = self.d.groups[k]
        fl = g.flow or Flow()
        left, top, right, bottom = self.pads(g)
        items = self.children(k)
        w, h = self.measure_items(items, fl, 0, 0)
        if g.box and title_place(g) == "middle":
            head = middle_title_box(g, Rect(0, 0, 0, 0), self.t, [])
            w += (HEADING_GAP if items else 0) + head.w
            h = max(h, head.h)
        w, h = w + left + right, h + top + bottom
        if g.box:
            w = max(w, 32 + _title_width(g, self.t))
        # The space a stack takes includes the boxes behind it, up and to the left of the front one.
        ex, ey = stack_reach(g)
        w, h = w + ex, h + ey
        self.sizes[k] = (w, h)
        return w, h

    def measure_items(self, items: list[_Item], fl: Flow, w: float, h: float) -> tuple[float, float]:
        if not items:
            return w, h
        gaps = fl.gap * (len(items) - 1)
        if fl.direction == "row":
            return sum(i.w for i in items) + gaps, max(i.h for i in items)
        return max(i.w for i in items), sum(i.h for i in items) + gaps

    def place(self, item: _Item, r: Rect) -> None:
        if item.kind == "node":
            self.centres[item.id] = (r.x - item.ox + (r.w - item.w) / 2, r.y - item.oy + (r.h - item.h) / 2)
            return
        g = self.d.groups[item.id]
        # A stack's boxes behind sit up and to the left: keep them inside the space given.
        ex, ey = stack_reach(g)
        box = Rect(r.x + ex, r.y + ey, r.w - ex, r.h - ey) if g.behind else r
        self.frames[item.id] = box
        left, top, right, bottom = self.pads(g)
        inner = Rect(box.x + left, box.y + top, box.w - left - right, box.h - top - bottom)
        items = self.children(item.id)
        if g.box and title_place(g) == "middle":
            head = middle_title_box(g, Rect(0, 0, 0, 0), self.t, [])
            inner = Rect(inner.x, inner.y, inner.w - head.w - (HEADING_GAP if items else 0), inner.h)
        fl = g.flow or Flow()
        # A row clear of a bottom title, side to side, centres on the whole box rather than above the title's band.
        clear_of = None
        if g.box and fl.direction == "row" and title_place(g) in ("bottom-left", "bottom") and bottom > top:
            clear_of = (group_title_box(g, box, self.t), Rect(inner.x, inner.y, inner.w, box.y1 - top - inner.y))
        self.place_items(items, fl, inner, clear_of)

    def place_items(self, items: list[_Item], fl: Flow, r: Rect, clear_of: tuple[Rect, Rect] | None = None) -> None:
        row = fl.direction == "row"
        length = r.w if row else r.h

        def offset(size: float) -> float:
            return {"start": 0.0, "end": span - size}.get(fl.align, (span - size) / 2)

        # Along the direction: growing groups share the space left over; failing that, `justify` spreads it.
        mains = [it.w if row else it.h for it in items]
        free = length - sum(mains) - fl.gap * max(0, len(items) - 1)
        grows = [self.d.groups[it.id].grow if it.kind == "group" else 0.0 for it in items]
        gap, pos = fl.gap, r.x if row else r.y
        if free > 0.5 and sum(grows) > 0:
            mains = [m + free * g / sum(grows) for m, g in zip(mains, grows, strict=True)]
        elif free > 0.5 and items:
            if fl.justify == "center":
                pos += free / 2
            elif fl.justify == "end":
                pos += free
            elif fl.justify == "space-between" and len(items) > 1:
                gap += free / (len(items) - 1)
            elif fl.justify == "space-around":
                gap += free / len(items)
                pos += free / len(items) / 2
            elif fl.justify == "space-between":
                pos += free / 2

        span = r.h if row else r.w

        # In a row, nodes line up by their icons, like text on a baseline. Centred, the icons and labels (a trigger
        # button hangs below, left out) sit in the middle of the box, of the whole box when its title is at the
        # bottom; then the line moves up as far as needed for every node to fit, a node over the title above it.
        band = max((it.h for it in items if it.kind == "node"), default=0.0)
        line = None
        nodes = [(it, main) for it, main in zip(items, mains, strict=True) if it.kind == "node"]
        if row and nodes and fl.align in ("center", "stretch"):
            title, whole = clear_of if clear_of else (None, r)
            core = max(it.core for it, _ in nodes)
            line = whole.y + (whole.h - core) / 2
            x = pos
            for it, main in zip(items, mains, strict=True):
                if it.kind == "node":
                    x0, x1 = x + (main - it.w) / 2, x + (main + it.w) / 2
                    over = title is not None and x0 < title.x1 and title.x < x1
                    line = min(line, (r.y1 if over else whole.y1) - it.h)
                x += main + gap
            line = max(line, r.y)

        for it, main in zip(items, mains, strict=True):
            size = it.h if row else it.w
            if it.kind == "group" and fl.align == "stretch":
                size, off = span, 0.0
            elif it.kind == "node" and row:
                off = line - r.y if line is not None else offset(band)
                size = it.h
            else:
                off = offset(size) if fl.align != "stretch" else (span - size) / 2
            if row:
                self.place(it, Rect(pos, r.y + off, main, size))
            else:
                self.place(it, Rect(r.x + off, pos, size, main))
            pos += main + gap
