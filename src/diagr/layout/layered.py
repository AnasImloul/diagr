"""Layered placement, for a diagram with nothing pinned.

1. Layers, for the whole diagram at once. Every node gets a layer along the flow (`direction`: right or down), so
   edges point forward, found exactly by the network simplex method: the layers that keep edges shortest, with each
   edge at least one layer long. Boxes are constraints rather than walls: a box an edge goes into starts after the
   box it comes from, and `layer: first` or `last` puts an item before or after everything else in its box. A box
   then spans the layers of what it holds, so the layers of boxes side by side line up, like columns.
2. Across the flow, box by box, inside out. In a box, an edge that skips layers gets a point in each layer it passes,
   which keeps a lane open for it, and an edge to something outside the box gets a lane to the box's edge. Each layer
   is sorted by where its neighbours sit, sweeping forward and back and keeping the order with the fewest crossings;
   a child box is in every layer it spans, at one place. Then the positions that make the edges run straightest,
   with every item keeping its order and its distance from its neighbours, are found exactly. The box, as tall as
   that comes to, is one block in its parent.
3. Along the flow, for the whole diagram at once: each layer is as thick as its biggest node, and the gap after it as
   wide as the labels and turns of the edges in it need, between the boxes that end before it and those that start
   after it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from ..model import Diagram, Edge, boxes_around, stack_owners
from ..theme import Theme
from .engine import footprint, group_rect, layout
from .geometry import NodeBox, Point, Rect, node_box, stack
from .simplex import solve
from .text import text_width

# Room in px between items in a layer, across the flow: between two nodes, next to a group, and next to the point an
# edge passes a layer at.
NODE_GAP = 40
GROUP_GAP = 28
LANE_GAP = 14
# Room in px between layers along the flow, as a share of the grid cell; and more for a label, and for each edge that
# turns in the gap.
LAYER_GAP = 0.4
LABEL_ROOM = 64
# Room in px kept either side of the label of an edge across the flow, between it and the items the edge joins.
ACROSS_CLEAR = 22
TURN_ROOM = 12
# How strongly an edge pulls its ends straight: between two lane points, between a lane point and an item, and between
# two items; a dashed edge pulls half as hard. An edge drawn back against the flow pulls a quarter as hard, and only
# as hard as two items between its ends and the items it joins, so it never bends the flow it runs back past.
PULL = {2: 8.0, 1: 2.0, 0: 1.0}
BACK_PULL = 0.25
HIDDEN_PULL = 0.25
# How hard a box holds what it holds together along the flow, against the edges that pull it apart.
HOLD = 0.01
ROUNDS = 24
# How many swaps of neighbours in a layer the order may try to let the edges run straighter.
STRAIGHTEN_TRIES = 200
STRAIGHTEN_WORK = 6000


def acyclic(order: list[str], edges: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The edges minus those that close a cycle, found by a depth-first walk in declaration order."""
    out = defaultdict(list)
    for a, b in edges:
        out[a].append(b)
    state: dict[str, int] = {}
    back: set[tuple[str, str]] = set()
    # With a stack of its own rather than recursion, so a long chain does not reach Python's recursion limit.
    for root in order:
        if root in state:
            continue
        state[root] = 1
        stack_ = [(root, iter(out[root]))]
        while stack_:
            v, ahead = stack_[-1]
            w = next(ahead, None)
            if w is None:
                state[v] = 2
                stack_.pop()
            elif state.get(w) == 1:
                back.add((v, w))
            elif w not in state:
                state[w] = 1
                stack_.append((w, iter(out[w])))
    return [e for e in edges if e not in back]


def topological(order: list[str], edges: list[tuple[str, str]]) -> list[str]:
    indeg = {v: 0 for v in order}
    out = defaultdict(list)
    for a, b in edges:
        out[a].append(b)
        indeg[b] += 1
    ready = [v for v in order if indeg[v] == 0]
    done = []
    while ready:
        v = ready.pop(0)
        done.append(v)
        for w in out[v]:
            indeg[w] -= 1
            if indeg[w] == 0:
                ready.append(w)
    return done


def can_layer(d: Diagram, flowed: set[str], flowed_groups: set[str]) -> bool:
    """Whether the diagram has nothing pinned for the layered placer to work around."""
    if flowed or flowed_groups:
        return False
    return all(n.at is None for n in d.nodes.values()) and all(g.at is None for g in d.groups.values())


@dataclass
class _Mark:
    """Something an edge runs straight along, placed across the flow at c: a lane point through its layer, or the
    stretch from an item out to the gap after its last layer ("after") or in from the gap before its first
    ("before")."""

    edge: str
    kind: str
    layer: int
    c: float
    item: str = ""


@dataclass
class _Block:
    """A node, a laid-out group, a lane point or a port, with what it holds placed across the flow from its start, in
    px. Along the flow, where things go is the same for the whole diagram: each layer's."""

    id: str
    kind: str  # "node", "group", "lane" or "port"
    size: float = 0.0
    # The centre of each node it holds, across the flow.
    centres: dict[str, float] = field(default_factory=dict)
    # Where each group it holds (itself included) starts and ends across the flow.
    spans: dict[str, tuple[float, float]] = field(default_factory=dict)
    marks: list[_Mark] = field(default_factory=list)
    # Where each edge between something inside and something outside crosses the block's edge, across the flow.
    exits: dict[str, float] = field(default_factory=dict)
    # For a lane point or a port: its edge.
    edge: str | None = None


@dataclass
class _Link:
    """An edge between two items of a box."""

    edge: Edge
    a: str
    b: str
    weight: float


@dataclass
class _Segment:
    """A stretch of an edge from one layer to the next: from item a to item b, meeting them at aa and ab across."""

    a: str
    b: str
    aa: float
    ab: float
    weight: float
    edge: str
    # The layer it starts from: the gap it crosses is the one after it.
    layer: int = 0
    # Which stretch of its edge this is, of how many, and whether the edge goes on outside the box.
    index: int = 0
    count: int = 1
    outside: bool = False


def place_layered(d: Diagram, t: Theme, slots: dict[str, int]) -> None:
    """Place every node. When routing then takes a backward edge round the outside rather than back through the
    lanes kept for it, place again without those lanes, so they leave no empty room."""
    free = [k for k, n in d.nodes.items() if n.at is None]
    d.layered = True
    _place(d, t, slots, set())
    outside = _round_the_outside(d, t)
    if outside:
        for k in free:
            d.nodes[k].at, d.nodes[k].auto = None, False
        d.lanes = {}
        _place(d, t, slots, outside)


def _round_the_outside(d: Diagram, t: Theme) -> set[str]:
    """The backward edges routing takes round the outside: they come into their target on its near side, the one
    facing back along the flow, where a backward edge through its lanes never does."""
    lay = layout(d, t)
    near = "top" if d.direction == "down" else "left"
    return {
        k
        for k, (way, _) in d.lanes.items()
        if way == "back" and k in lay.edges and (stop := lay.edges[k].port) is not None and stop.side == near
    }


def _place(d: Diagram, t: Theme, slots: dict[str, int], outside: set[str]) -> None:
    lay = _Layered(d, t, slots, outside)
    lay.rank()
    root = lay.container(None)
    centres, stretches = lay.along(root)
    xs = [x for x, _ in centres.values()]
    ys = [y for _, y in centres.values()]
    x0, y0 = min(xs, default=0.0), min(ys, default=0.0)
    for k, (x, y) in centres.items():
        n = d.nodes[k]
        n.at = (round((x - x0) / d.grid.col, 2), round((y - y0) / d.grid.row, 2))
        n.auto = True
    for k, way in lay.ways.items():
        # Rounded to a tenth of a px, as `diagr expand` writes routes, so the pinned file draws the same picture.
        d.lanes[k] = (way, [_rounded(p, q, x0, y0) for p, q in stretches.get(k, [])])


def _rounded(p: Point, q: Point, x0: float, y0: float) -> tuple[Point, Point]:
    return (round(p[0] - x0, 1), round(p[1] - y0, 1)), (round(q[0] - x0, 1), round(q[1] - y0, 1))


class _Layered:
    def __init__(self, d: Diagram, t: Theme, slots: dict[str, int], outside: set[str] | None = None):
        self.d, self.t, self.slots = d, t, slots
        # Backward edges routed round the outside: they set layers, but keep no lanes and pull nothing.
        self.outside = outside or set()
        self.down = d.direction == "down"
        self.owner = stack_owners(d)
        self.children: dict[str | None, list[str]] = defaultdict(list)
        for gid, g in d.groups.items():
            self.children[g.parent if g.parent in d.groups else None].append(gid)
        self.own: dict[str | None, list[str]] = defaultdict(list)
        for k, n in d.nodes.items():
            self.own[n.group if n.group in d.groups else None].append(k)
        self.links = self._links()
        # Each node's layer, and the layers each item (node or group) spans.
        self.layer: dict[str, int] = {}
        self.range: dict[str, tuple[int, int]] = {}
        # Each edge placed, and which way it runs where its two ends meet: forward, back or across the flow.
        self.ways: dict[str, str] = {}
        # The gap each edge's label sits in, and how wide the label is.
        self.labels: dict[str, tuple[int, float]] = {}
        # Each edge stretch from one layer to the next, as the gap it crosses and where it starts and ends across.
        self.turns: list[tuple[int, float, float]] = []
        # In the box being laid out: the room an edge's label needs between two items it joins across the flow.
        self.label_gaps: dict[tuple[str, str], float] = {}
        # In the box being laid out: the lane points of each edge that passes more than one layer, in order.
        self.chains: list[list[str]] = []

    # The edges that place things, and how hard each pulls.

    def _links(self) -> list[tuple[Edge, float, bool]]:
        """Every edge between two ends, with its pull and whether it sets layers. A dashed edge is a side link
        (replication, a dead-letter queue, a wake-up call): it sets the layer of a node it leads into only when no
        solid edge does, and never that of a node it comes from, which goes beside what it is joined to instead. A
        dashed or hidden edge to a node that has no other edge, in the same box, is a side leaf (a dead-letter queue,
        a monitor, something a scenario reveals): the node goes beside the one it hangs off rather than after it. An
        edge pinned to sides across the flow joins two items in one layer, and an edge with `constraint: false`
        places nothing."""
        d = self.d
        across = ("left", "right") if self.down else ("top", "bottom")
        ends = set(d.nodes) | set(d.groups) | set(self.owner)
        edges = [
            e
            for e in d.edges.values()
            if e.src.node in ends and e.dst.node in ends and e.src.node != e.dst.node and e.constraint
        ]
        solid = [e for e in edges if not e.dashed]
        fed = {e.dst.node for e in solid}
        linked = fed | {e.src.node for e in solid}
        degree: dict[str, int] = defaultdict(int)
        for e in edges:
            degree[e.src.node] += 1
            degree[e.dst.node] += 1
        out = []
        for e in edges:
            layers = not (e.src.side in across and e.dst.side in across)
            layers = layers and (not e.dashed or (e.dst.node not in fed and e.src.node in linked))
            reveals = (
                (e.hidden or e.dashed)
                and degree[e.dst.node] == 1
                and e.src.node in d.nodes
                and e.dst.node in d.nodes
                and d.nodes[e.src.node].group == d.nodes[e.dst.node].group
            )
            layers = layers and not reveals
            pull = 0.5 if e.dashed else 1.0
            # An edge that only a scenario brings out pulls less: the picture as it first shows comes first.
            if e.hidden or any(d.nodes[n].hidden for n in (e.src.node, e.dst.node) if n in d.nodes):
                pull *= HIDDEN_PULL
            out.append((e, pull, layers))
        return out

    def _path(self, end: str) -> list[str]:
        """The boxes around an edge end, outermost first, then the end itself."""
        end = self.owner.get(end, end)
        if end in self.d.groups:
            return boxes_around(self.d, end)[::-1]
        return [*boxes_around(self.d, self.d.nodes[end].group)[::-1], end]

    def _item(self, end: str, box: str | None) -> str | None:
        """The item of box that holds an edge end (or is it), or None when the end is outside the box."""
        path = self._path(end)
        if box is None:
            return path[0]
        if box in path and path.index(box) + 1 < len(path):
            return path[path.index(box) + 1]
        return None

    def _lca(self, a: str, b: str) -> str | None:
        """The smallest box both ends are in, or None for the diagram."""
        pa, pb = self._path(a), self._path(b)
        common = [x for x, y in zip(pa, pb, strict=False) if x == y and x in self.d.groups]
        return common[-1] if common else None

    def _used(self, g: str) -> bool:
        return bool(self.own[g]) or any(self._used(c) for c in self.children[g])

    def _items(self, gid: str | None) -> list[str]:
        """What a box holds, in file order: its nodes, and its child groups with anything in them."""
        return sorted([c for c in self.children[gid] if self._used(c)] + self.own[gid], key=self._order)

    def _order(self, k: str) -> tuple[int, int, int]:
        x = self.d.groups.get(k) or self.d.nodes.get(k)
        loc = x.loc if x is not None else None
        index = list(self.d.groups).index(k) if k in self.d.groups else len(self.d.groups) + list(self.d.nodes).index(k)
        return (loc.line, loc.col, index) if loc else (0, 0, index)

    def _hint(self, k: str) -> str | None:
        x = self.d.groups.get(k) or self.d.nodes.get(k)
        return getattr(x, "layer", None)

    # 1. Layers, for the whole diagram.

    def rank(self) -> None:
        """Each node's layer: the shortest edges, weighted, with every edge going at least one layer forward, a box
        an edge goes into after the box it comes from, and items marked first or last before or after the rest of
        their box. A node that nothing places goes in the layer of what it is joined to."""
        d = self.d
        used = [g for g in d.groups if self._used(g)]
        # Each item's first and last point along the flow: a node's layer, or a box's start and end.
        start = {g: f"\0start:{g}" for g in used}
        end = {g: f"\0end:{g}" for g in used}

        def first(k: str) -> str:
            k = self.owner.get(k, k)
            return start[k] if k in start else k

        def last(k: str) -> str:
            k = self.owner.get(k, k)
            return end[k] if k in end else k

        placing = [(e, w) for e, w, layers in self.links if layers]
        placed = {x for e, _ in placing for x in (e.src.node, e.dst.node)}
        placed = {self.owner.get(x, x) for x in placed}
        # Nodes in a box that something places: the box holds them together.
        holds = {g: any(n in placed for n in self._nodes_in(g)) or g in placed for g in used}
        structural: list[tuple[str, str, float, float]] = []
        for g in used:
            if not holds[g]:
                continue
            for k in self.own[g]:
                if k in placed:
                    structural += [(start[g], k, 0, HOLD), (k, end[g], 0, HOLD)]
            for c in self.children[g]:
                if c in start and holds[c]:
                    structural += [(start[g], start[c], 0, HOLD), (end[c], end[g], 0, HOLD)]
            structural.append((start[g], end[g], 0, 0.0))
        # A box (or node) an edge goes into starts after the box (or node) it comes from, among what one box holds,
        # so the two sit side by side rather than one beside the other in shared layers.
        pairs: list[tuple[str, str]] = []
        for e, _ in placing:
            if e.dashed:
                continue
            box = self._lca(e.src.node, e.dst.node)
            a, b = self._item(e.src.node, box), self._item(e.dst.node, box)
            if a is None or b is None or a == b or (a not in start and b not in start):
                continue
            # As for edges: nothing leads into an item that goes first, nor out of one that goes last.
            if self._hint(b) == "first" or self._hint(a) == "last":
                a, b = b, a
            if all(k in placed or (k in start and holds[k]) for k in (a, b)):
                pairs.append((a, b))
        for a, b in acyclic(list(d.groups) + list(d.nodes), list(dict.fromkeys(pairs))):
            structural.append((last(a), first(b), 1, 0.0))
        # Items marked first or last.
        for box in [None, *used]:
            items = [k for k in self._items(box) if k in placed or (k in start and holds[k])]
            for hint, before in (("first", True), ("last", False)):
                marked = [k for k in items if self._hint(k) == hint]
                rest = [k for k in items if self._hint(k) != hint]
                if not marked or not rest:
                    continue
                pin = f"\0{hint}:{box}"
                for k in marked:
                    structural.append((last(k), pin, 0, 0.0) if before else (pin, first(k), 1, 0.0))
                for k in rest:
                    structural.append((pin, first(k), 1, 0.0) if before else (last(k), pin, 0, 0.0))
        graph: dict[str, list[str]] = defaultdict(list)
        constraints = []
        for u, v, mn, w in structural:
            # Order and hints that contradict each other: the first written holds.
            if not _reaches(graph, v, u):
                graph[u].append(v)
                constraints.append((u, v, mn, w))
        for e, w in placing:
            src, dst = e.src.node, e.dst.node
            box = self._lca(src, dst)
            a, b = self._item(src, box), self._item(dst, box)
            # Nothing leads into an item that goes first, and nothing out of one that goes last.
            if (b is not None and self._hint(b) == "first") or (a is not None and self._hint(a) == "last"):
                src, dst = dst, src
            u, v = last(src), first(dst)
            # An edge that would close a loop is drawn back against the flow instead.
            if _reaches(graph, v, u):
                continue
            graph[u].append(v)
            constraints.append((u, v, 1, w))
        names = sorted({x for u, v, _, _ in constraints for x in (u, v)} | placed, key=str)
        index = {k: i for i, k in enumerate(names)}
        x = solve(len(names), [(index[u], index[v], m, w) for u, v, m, w in constraints])
        layer = {k: round(x[index[k]]) for k in placed if k in d.nodes}
        # A node that nothing places goes in the layer of what it is joined to, the middle one of them; one joined to
        # nothing goes at the start of its box.
        for _ in range(3):
            for k in d.nodes:
                if k in placed:
                    continue
                near = sorted(
                    layer[o]
                    for e, _, _ in self.links
                    for o in ((e.dst.node,) if e.src.node == k else (e.src.node,) if e.dst.node == k else ())
                    if o in layer
                )
                if near:
                    layer[k] = near[(len(near) - 1) // 2]
        for k in d.nodes:
            if k not in layer:
                g = d.nodes[k].group
                inside = [layer[n] for n in self._nodes_in(g) if n in layer] if g in d.groups else []
                layer[k] = min(inside, default=min(layer.values(), default=0))
        low = min(layer.values(), default=0)
        self.layer = {k: v - low for k, v in layer.items()}
        for k, v in self.layer.items():
            self.range[k] = (v, v)
        for g in used:
            ls = [self.layer[n] for n in self._nodes_in(g)]
            self.range[g] = (min(ls), max(ls))

    def _nodes_in(self, g: str | None) -> list[str]:
        """Every node in a box, in the boxes inside it too."""
        out = list(self.own[g])
        for c in self.children[g]:
            out += self._nodes_in(c)
        return out

    def _span_of(self, end: str) -> tuple[int, int]:
        end = self.owner.get(end, end)
        return self.range.get(end, (0, 0))

    # Sizes.

    def _gap(self, a: _Block, b: _Block) -> float:
        if a.kind in ("lane", "port") or b.kind in ("lane", "port"):
            return LANE_GAP
        base = GROUP_GAP if a.kind == "group" or b.kind == "group" else NODE_GAP
        # Two items an edge with a label joins across the flow keep room for the label between them.
        return max(base, self.label_gaps.get((a.id, b.id), 0.0), self.label_gaps.get((b.id, a.id), 0.0))

    def _box(self, k: str) -> Rect:
        """A node's box, around its centre at (0, 0)."""
        return node_box(self.d.nodes[k], 0, 0, self.t, self.slots[k]).box

    def node(self, k: str) -> _Block:
        b = self._box(k)
        lo, size = (b.x, b.w) if self.down else (b.y, b.h)
        return _Block(k, "node", size, {k: -lo})

    def _at(self, b: _Block, end: str, edge: str | None = None) -> float:
        """Where an edge end inside block b meets it, across the flow, from the block's start: where the edge crosses
        the block's edge, if it has a lane inside."""
        if b.kind in ("lane", "port"):
            return 0.0
        end = self.owner.get(end, end)
        if edge in b.exits:
            return b.exits[edge]
        if end in b.centres:
            return b.centres[end]
        if end in b.spans:
            lo, hi = b.spans[end]
            return (lo + hi) / 2
        return b.size / 2

    # 2. Across the flow, a box at a time.

    def container(self, gid: str | None) -> _Block:
        d = self.d
        blocks = [self.container(c) if c in d.groups else self.node(c) for c in self._items(gid)]
        items = {b.id: b for b in blocks}
        span = {k: self.range[k] for k in items}
        lo = min((s[0] for s in span.values()), default=0)
        hi = max((s[1] for s in span.values()), default=0)
        links = self._inside(gid)
        ports = self._ports(gid, lo, hi, items, span) if gid is not None else []
        self.label_gaps = {}
        self.chains = []
        rows, segments, flats = self._chains(items, span, links + ports, lo, hi)
        rows = self._order_rows(items, rows, segments, flats)
        self._one_side(items, rows)
        rows = self._straighten(items, rows, segments, flats)
        cross = self._positions(items, rows, segments)
        for lk in links:
            (a0, a1), (b0, b1) = self._span_of(lk.edge.src.node), self._span_of(lk.edge.dst.node)
            self.ways[lk.edge.id] = "forward" if a1 < b0 else "back" if b1 < a0 else "across"

        centres: dict[str, float] = {}
        spans: dict[str, tuple[float, float]] = {}
        marks: list[_Mark] = []
        exits: dict[str, float] = {}
        for sg in segments:
            ca, cb = cross[sg.a] + sg.aa, cross[sg.b] + sg.ab
            self.turns.append((sg.layer, ca, cb))
            e = d.edges[sg.edge]
            if e.label and sg.index == sg.count // 2 and not sg.outside:
                self.labels[sg.edge] = (sg.layer, text_width(e.label, self.t.size("label")))
            # An edge out of an item runs on to the gap after it before it turns, and one into an item comes in
            # from the gap before it, so turns stay in the gaps between layers.
            if items[sg.a].kind in ("node", "group"):
                marks.append(_Mark(sg.edge, "after", sg.layer, ca, sg.a))
            if items[sg.b].kind in ("node", "group"):
                marks.append(_Mark(sg.edge, "before", sg.layer + 1, cb, sg.b))
        for k, b in items.items():
            c = cross[k]
            if b.kind == "lane":
                marks.append(_Mark(b.edge or "", "lane", int(k.rsplit(":", 1)[1]), c))
                continue
            if b.kind == "port":
                exits[b.edge or ""] = c
                continue
            for n, at in b.centres.items():
                centres[n] = c + at
            for g, (s0, s1) in b.spans.items():
                spans[g] = (c + s0, c + s1)
            marks += [_Mark(m.edge, m.kind, m.layer, c + m.c, m.item) for m in b.marks]
        if gid is None:
            return _Block("", "group", 0.0, centres, spans, marks)
        return self._frame(gid, centres, spans, marks, exits)

    def _inside(self, gid: str | None) -> list[_Link]:
        """The edges between two items of a box."""
        out = []
        for e, w, _ in self.links:
            a, b = self._item(e.src.node, gid), self._item(e.dst.node, gid)
            if a is not None and b is not None and a != b:
                out.append(_Link(e, a, b, w))
        return out

    def _ports(
        self, gid: str, lo: int, hi: int, items: dict[str, _Block], span: dict[str, tuple[int, int]]
    ) -> list[_Link]:
        """Edges between an item of the box and something outside it, each to a port: a point just before the box's
        first layer for an edge to something before the box, or just past its last for one to something past it, so
        the edge has a lane through the layers it crosses inside. An edge to something beside the box, in its
        layers, leaves across the flow and needs no port."""
        out: list[_Link] = []
        for e, w, _ in self.links:
            a, b = self._item(e.src.node, gid), self._item(e.dst.node, gid)
            if (a is None) == (b is None) or e.id in self.outside:
                continue
            other = e.dst.node if a is not None else e.src.node
            o0, o1 = self._span_of(other)
            if lo <= o0 <= hi or lo <= o1 <= hi or (o0 < lo and o1 > hi):
                continue
            port = f"\0port{len(out)}:{e.id}"
            items[port] = _Block(port, "port", edge=e.id)
            span[port] = (hi + 1, hi + 1) if o0 > hi else (lo - 1, lo - 1)
            out.append(_Link(e, a, port, w) if a is not None else _Link(e, port, b or "", w))
        return out

    def _chains(
        self,
        items: dict[str, _Block],
        span: dict[str, tuple[int, int]],
        links: list[_Link],
        lo: int,
        hi: int,
    ) -> tuple[list[list[str]], list[_Segment], list[tuple[str, str]]]:
        """The layers of the box, from a port before it to one after, each with the items it spans in file order and
        a lane point for each edge passing it; the stretches of every edge from one layer to the next; and the pairs
        of items an edge joins across the flow, in layers they share."""
        base = min([lo, *(s[0] for s in span.values())])
        top = max([hi, *(s[1] for s in span.values())])
        rows: list[list[str]] = [[] for _ in range(top - base + 1)]
        for k, (s0, s1) in span.items():
            for v in range(s0, s1 + 1):
                rows[v - base].append(k)
        segments: list[_Segment] = []
        flats: list[tuple[str, str]] = []
        for i, lk in enumerate(links):
            if lk.edge.id in self.outside:
                continue
            a, b = items[lk.a], items[lk.b]
            (a0, a1), (b0, b1) = span[lk.a], span[lk.b]
            aa, ab = self._at(a, lk.edge.src.node, lk.edge.id), self._at(b, lk.edge.dst.node, lk.edge.id)
            if not (a1 < b0 or b1 < a0):
                flats.append((lk.a, lk.b))
                if lk.edge.label:
                    across = 18 if not self.down else text_width(lk.edge.label, self.t.size("label")) + 10
                    key = (lk.a, lk.b)
                    self.label_gaps[key] = max(self.label_gaps.get(key, 0.0), across + 2 * ACROSS_CLEAR)
                continue
            s0, s1 = self._span_of(lk.edge.src.node), self._span_of(lk.edge.dst.node)
            back = s0[0] > s1[1]
            if b1 < a0:
                a, b, aa, ab, (a0, a1), (b0, b1) = b, a, ab, aa, (b0, b1), (a0, a1)
            chain = [a.id]
            for v in range(a1 + 1, b0):
                lane = _Block(f"\0lane{i}:{v}", "lane", edge=lk.edge.id)
                items[lane.id] = lane
                span[lane.id] = (v, v)
                rows[v - base].append(lane.id)
                chain.append(lane.id)
            chain.append(b.id)
            if len(chain) > 3:
                self.chains.append(chain[1:-1])
            ats = [aa] + [0.0] * (len(chain) - 2) + [ab]
            outside = a.kind == "port" or b.kind == "port"
            for j, (u, w) in enumerate(zip(chain, chain[1:], strict=False)):
                kinds = (items[u].kind in ("lane", "port")) + (items[w].kind in ("lane", "port"))
                # Drawn back, the edge keeps its own lane straight but pulls the items it joins only a little.
                weight = lk.weight * (BACK_PULL * (PULL[2] if kinds == 2 else 1.0) if back else PULL[kinds])
                layer = a1 + j
                sg = _Segment(u, w, ats[j], ats[j + 1], weight, lk.edge.id, layer, j, len(chain) - 1, outside)
                segments.append(sg)
        self.base = base
        return rows, segments, flats

    def _stacked(self, items: dict[str, _Block], row: list[str]) -> dict[str, float]:
        """Where each item of a row starts across the flow, packed in order."""
        pos, at, prev = {}, 0.0, None
        for k in row:
            if prev is not None:
                at += self._gap(items[prev], items[k])
            pos[k] = at
            at += items[k].size
            prev = k
        return pos

    def _centred(self, items: dict[str, _Block], row: list[str]) -> dict[str, float]:
        pos = self._stacked(items, row)
        if not row:
            return pos
        last = row[-1]
        mid = (pos[last] + items[last].size) / 2
        return {k: v - mid for k, v in pos.items()}

    def _row_positions(self, items: dict[str, _Block], rows: list[list[str]]) -> dict[tuple[int, str], float]:
        out: dict[tuple[int, str], float] = {}
        for i, row in enumerate(rows):
            for k, v in self._centred(items, row).items():
                out[(i, k)] = v
        return out

    def _crossings(self, segs: list[_Segment], i: int, pos: dict[tuple[int, str], float]) -> float:
        ends = [(pos[(i, s.a)] + s.aa, pos[(i + 1, s.b)] + s.ab, s.weight) for s in segs]
        n = 0.0
        for j, (a0, b0, w0) in enumerate(ends):
            for a1, b1, w1 in ends[j + 1 :]:
                if (a0 - a1) * (b0 - b1) < 0:
                    n += w0 * w1
        return n

    def _between(self, rows: list[list[str]], segments: list[_Segment]) -> dict[int, list[_Segment]]:
        out: dict[int, list[_Segment]] = defaultdict(list)
        for sg in segments:
            out[sg.layer - self.base].append(sg)
        return out

    def _tangle(
        self,
        items: dict[str, _Block],
        rows: list[list[str]],
        between: dict[int, list[_Segment]],
        flats: list[tuple[str, str]],
    ) -> float:
        """What an order costs in crossings, and in items between two that an edge joins across the flow."""
        pos = self._row_positions(items, rows)
        crossings = sum(self._crossings(between[i], i, pos) for i in range(len(rows) - 1))
        return crossings + sum(_apart(row, flats) for row in rows)

    def _order_rows(
        self,
        items: dict[str, _Block],
        rows: list[list[str]],
        segments: list[_Segment],
        flats: list[tuple[str, str]],
    ) -> list[list[str]]:
        """Each layer sorted by where its neighbours in the layer before (or after) sit, sweeping forward and back,
        and the order with the fewest crossings kept. An item spanning several layers is sorted once, where it
        starts (or ends), and keeps that place in every layer it spans."""
        between = self._between(rows, segments)
        file_order = {k: i for i, k in enumerate(items)}
        spanning = {k for k in items if sum(k in r for r in rows) > 1}
        pulled = defaultdict(int)
        for s in segments:
            pulled[s.a] += 1
            pulled[s.b] += 1

        def huddle(row: list[str]) -> None:
            """Items an edge joins across the flow go next to each other: the one with fewer other edges moves."""
            for u, v in flats:
                if u in row and v in row and abs(row.index(u) - row.index(v)) > 1:
                    mover, stay = (u, v) if pulled[u] <= pulled[v] else (v, u)
                    if mover in spanning:
                        mover, stay = stay, mover
                    if mover in spanning:
                        continue
                    was = row.index(mover)
                    row.remove(mover)
                    at = row.index(stay)
                    row.insert(at if was < at + 1 else at + 1, mover)

        def sweep(rs: list[list[str]], forward: bool) -> list[list[str]]:
            rs = [list(r) for r in rs]
            pos = self._row_positions(items, rs)
            keys: dict[str, tuple[float, int]] = {}
            seq = range(len(rs)) if forward else range(len(rs) - 1, -1, -1)
            for i in seq:
                pulls: dict[str, list[float]] = defaultdict(list)
                near = i - 1 if forward else i + 1
                if 0 <= near < len(rs):
                    for s in between[i - 1] if forward else between[i]:
                        if forward:
                            pulls[s.b].append(pos[(i - 1, s.a)] + s.aa - s.ab + items[s.b].size / 2)
                        else:
                            pulls[s.a].append(pos[(i + 1, s.b)] + s.ab - s.aa + items[s.a].size / 2)
                for k in rs[i]:
                    if k in keys:
                        continue
                    ps = pulls.get(k)
                    mid = sum(ps) / len(ps) if ps else pos[(i, k)] + items[k].size / 2
                    keys[k] = (mid, file_order.get(k, 0))
                rs[i].sort(key=keys.__getitem__)
                huddle(rs[i])
                for k, v in self._centred(items, rs[i]).items():
                    pos[(i, k)] = v
            return rs

        for row in rows:
            huddle(row)
        best, best_n = rows, self._tangle(items, rows, between, flats)
        current = rows
        for r in range(ROUNDS):
            current = sweep(current, forward=r % 2 == 0)
            current = self._transpose(items, current, between, flats, spanning)
            n = self._tangle(items, current, between, flats)
            if n < best_n - 1e-9:
                best, best_n = current, n
            if best_n == 0:
                break
        return best

    def _transpose(
        self,
        items: dict[str, _Block],
        rows: list[list[str]],
        between: dict[int, list[_Segment]],
        flats: list[tuple[str, str]],
        spanning: set[str],
    ) -> list[list[str]]:
        """Neighbours in a layer swap places while that crosses fewer edges; two items that both span several layers
        keep their order, which holds in every layer they share."""
        rows = [list(r) for r in rows]
        pos = self._row_positions(items, rows)

        def local(i: int) -> float:
            n = _apart(rows[i], flats) + (self._crossings(between[i], i, pos) if i < len(rows) - 1 else 0.0)
            return n + (self._crossings(between[i - 1], i - 1, pos) if i > 0 else 0.0)

        def place(i: int) -> None:
            for k, v in self._centred(items, rows[i]).items():
                pos[(i, k)] = v

        for _ in range(4):
            better = False
            for i, row in enumerate(rows):
                for j in range(len(row) - 1):
                    if _held(row[j], row[j + 1], spanning, items):
                        continue
                    before = local(i)
                    row[j], row[j + 1] = row[j + 1], row[j]
                    place(i)
                    if local(i) < before - 1e-9:
                        better = True
                    else:
                        row[j], row[j + 1] = row[j + 1], row[j]
                        place(i)
            if not better:
                break
        return rows

    def _one_side(self, items: dict[str, _Block], rows: list[list[str]]) -> None:
        """An edge's lane keeps to one side of a box it runs past, the side most of its layers have it on: a lane
        above a box in one layer and below it in the next would turn through it."""
        spanning = [k for k in items if sum(k in r for r in rows) > 1]
        for chain in self.chains:
            for box in spanning:
                shared = [(r, k) for r in rows for k in chain if k in r and box in r]
                if len(shared) < 2:
                    continue
                before = [r.index(k) < r.index(box) for r, k in shared]
                side = sum(before) * 2 >= len(before) if before.count(True) != before.count(False) else before[0]
                for r, k in shared:
                    if (r.index(k) < r.index(box)) != side:
                        r.remove(k)
                        at = r.index(box)
                        r.insert(at if side else at + 1, k)

    def _straighten(
        self,
        items: dict[str, _Block],
        rows: list[list[str]],
        segments: list[_Segment],
        flats: list[tuple[str, str]],
    ) -> list[list[str]]:
        """Of the orders that cross no more edges, the one whose edges can run straightest: neighbours in a layer
        swap places while that lets the positions bend the edges less, as the positions would place them. Two
        orders that cross as much can differ a lot here: a lane between the nodes a node fans out to lets the lane
        run straight on, one beside them bends it."""
        between = self._between(rows, segments)
        spanning = {k for k in items if sum(k in r for r in rows) > 1}
        pulls = self._pulls(items, segments)

        def bend(rs: list[list[str]]) -> float:
            pos = self._positions(items, rs, segments)
            return sum(w * abs(pos[a] + aa - pos[b] - ab) for a, aa, b, ab, w in pulls)

        rows = [list(r) for r in rows]
        tangle, cost = self._tangle(items, rows, between, flats), bend(rows)
        # Each try solves the positions again: a big box gets fewer.
        budget = min(STRAIGHTEN_TRIES, STRAIGHTEN_WORK // (len(items) + len(pulls) + 1))
        better = True
        while better and budget > 0:
            better = False
            for row in rows:
                for j in range(len(row) - 1):
                    if budget <= 0:
                        break
                    if _held(row[j], row[j + 1], spanning, items):
                        continue
                    row[j], row[j + 1] = row[j + 1], row[j]
                    t = self._tangle(items, rows, between, flats)
                    c = bend(rows) if t <= tangle + 1e-9 else math.inf
                    budget -= 1
                    if c < cost - 0.5:
                        tangle, cost, better = t, c, True
                    else:
                        row[j], row[j + 1] = row[j + 1], row[j]
        return rows

    def _positions(self, items: dict[str, _Block], rows: list[list[str]], segments: list[_Segment]) -> dict[str, float]:
        """Where each item starts across the flow: the positions that make the edges, weighted, run as straight as
        they can while every item keeps its order and its distance from its neighbours in each layer, found exactly
        by the network simplex method. Then an item free to move without bending anything more sits in the middle of
        that room."""
        index = {k: i for i, k in enumerate(items)}
        constraints: list[tuple[int, int, float, float]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            for a, b in zip(row, row[1:], strict=False):
                if (a, b) in seen:
                    continue
                seen.add((a, b))
                constraints.append((index[a], index[b], items[a].size + self._gap(items[a], items[b]), 0.0))
        pulls = self._pulls(items, segments)
        # Each pull |x_a + at_a - x_b - at_b| becomes a point below both ends: x_a - p >= -at_a and x_b - p >= -at_b.
        n = len(index)
        for a, at_a, b, at_b, w in pulls:
            constraints += [(n, index[a], -at_a, w), (n, index[b], -at_b, w)]
            n += 1
        x = solve(n, constraints)
        pos = {k: x[i] for k, i in index.items()}
        self._settle(items, rows, pulls, pos)
        return pos

    def _pulls(self, items: dict[str, _Block], segments: list[_Segment]) -> list[tuple[str, float, str, float, float]]:
        """Each edge stretch as a pull between the two items it joins, (a, where it meets a, b, where it meets b,
        weight). The edges on each side of a node share its pull on that side: a node with one edge in and two out
        lines up with the one coming in, and one fanning out to two sits between them. In a group, that is each node
        it holds, not the group as a whole, which may have many edges coming in to different nodes."""
        before, after = defaultdict(int), defaultdict(int)
        for sg in segments:
            after[(sg.a, round(sg.aa, 1))] += 1
            before[(sg.b, round(sg.ab, 1))] += 1
        out = [
            (
                sg.a,
                sg.aa,
                sg.b,
                sg.ab,
                sg.weight * (1 / after[(sg.a, round(sg.aa, 1))] + 1 / before[(sg.b, round(sg.ab, 1))]) / 2,
            )
            for sg in segments
        ]
        for n in self.d.nodes.values():
            # A node lined up with another across the flow is pulled to it hard.
            target = n.align_x if self.down else n.align_y
            if target and n.id in items and target in items:
                out.append((n.id, self._at(items[n.id], n.id), target, self._at(items[target], target), 20.0))
        return out

    def _settle(
        self,
        items: dict[str, _Block],
        rows: list[list[str]],
        pulls: list[tuple[str, float, str, float, float]],
        pos: dict[str, float],
    ) -> None:
        """An item whose edges all go one way and pull it equally over a stretch (a node fanning out to two, between
        them) moves to the middle of the stretch, as far as its neighbours in every layer it spans let it. It bends
        nothing more. An item with edges both ways stays where one of them runs straight through it."""
        mine: dict[str, list[tuple[str, float, float, float]]] = defaultdict(list)
        for a, at_a, b, at_b, w in pulls:
            mine[a].append((b, at_b, at_a, w))
            mine[b].append((a, at_a, at_b, w))
        first = {}
        for i, row in enumerate(rows):
            for k in row:
                first.setdefault(k, i)
        for _ in range(3):
            for k in items:
                if not mine[k] or len({first[o] > first[k] for o, *_ in mine[k] if o in first}) > 1:
                    continue
                wants = sorted((pos[o] + at_o - at_me, w) for o, at_o, at_me, w in mine[k])
                lo, hi = _flat_stretch(wants)
                if hi - lo < 0.5 or not lo - 0.5 <= pos[k] <= hi + 0.5:
                    continue
                room_lo, room_hi = -math.inf, math.inf
                for row in rows:
                    if k not in row:
                        continue
                    j = row.index(k)
                    if j > 0:
                        prev = row[j - 1]
                        room_lo = max(room_lo, pos[prev] + items[prev].size + self._gap(items[prev], items[k]))
                    if j + 1 < len(row):
                        nxt = row[j + 1]
                        room_hi = min(room_hi, pos[nxt] - items[k].size - self._gap(items[k], items[nxt]))
                pos[k] = min(max((lo + hi) / 2, room_lo, lo), room_hi, hi)

    def _frame(
        self,
        gid: str,
        centres: dict[str, float],
        spans: dict[str, tuple[float, float]],
        marks: list[_Mark],
        exits: dict[str, float],
    ) -> _Block:
        """The group's box across the flow, the way the engine fits it around what it holds, and the block it
        makes, boxes stacked behind it included. Along the flow the box does not change how big it is across, so
        each node sits at its layer, a cell apart, for this."""
        d, t = self.d, self.t
        g = d.groups[gid]
        cell = d.grid.row if self.down else d.grid.col

        def at(k: str, c: float) -> tuple[float, float]:
            m = self.layer[k] * cell * 4
            return (c, m) if self.down else (m, c)

        boxes: dict[str, NodeBox] = {
            k: node_box(d.nodes[k], *at(k, c), t, self.slots[k]) for k, c in centres.items() if d.nodes[k].group == gid
        }
        children = []
        for c in self.children[gid]:
            if c in spans:
                s0, s1 = spans[c]
                r0, r1 = self.range[c]
                m0, m1 = r0 * cell * 4, r1 * cell * 4 + 1
                r = Rect(s0, m0, s1 - s0, m1 - m0) if self.down else Rect(m0, s0, m1 - m0, s1 - s0)
                children.append(r)
        r = group_rect(g, d, t, boxes, children) or Rect(0, 0, 0, 0)
        fp = footprint(r, stack(g, r))
        lo, hi = (fp.x, fp.x1) if self.down else (fp.y, fp.y1)
        spans = dict(spans)
        spans[gid] = (r.x, r.x1) if self.down else (r.y, r.y1)
        return _Block(
            gid,
            "group",
            hi - lo,
            {k: c - lo for k, c in centres.items()},
            {k: (s0 - lo, s1 - lo) for k, (s0, s1) in spans.items()},
            [_Mark(m.edge, m.kind, m.layer, m.c - lo, m.item) for m in marks],
            {e: c - lo for e, c in exits.items()},
        )

    # 3. Along the flow, for the whole diagram.

    def along(self, root: _Block) -> tuple[dict[str, tuple[float, float]], dict[str, list[tuple[Point, Point]]]]:
        """Every node's centre, and the stretches each edge runs straight along. Each layer is as thick as its
        biggest node; the gap after it at least LAYER_GAP of a cell, or what the labels and turns of the edges in it
        need, between the end of everything that ends in the layer and the start of everything that starts in the
        next, boxes included."""
        d, t = self.d, self.t
        cell = d.grid.row if self.down else d.grid.col
        depth = max(self.layer.values(), default=0) + 1
        boxes = {k: self._box(k) for k in d.nodes}

        def main_span(r: Rect) -> tuple[float, float]:
            return (r.y, r.y1) if self.down else (r.x, r.x1)

        before = [0.0] * depth
        after = [0.0] * depth
        for k, v in self.layer.items():
            s0, s1 = main_span(boxes[k])
            before[v], after[v] = max(before[v], -s0), max(after[v], s1)
        need = [LAYER_GAP * cell] * depth
        for v, w in self.labels.values():
            if 0 <= v < depth:
                need[v] = max(need[v], (18 if self.down else w) + LABEL_ROOM)
        turning: dict[int, int] = defaultdict(int)
        for v, c0, c1 in self.turns:
            if abs(c0 - c1) > 0.5:
                turning[v] += 1
        for v, n in turning.items():
            if 0 <= v < depth:
                need[v] = max(need[v], TURN_ROOM * (n + 1))
        m = [0.0] * depth
        for v in range(1, depth):
            m[v] = m[v - 1] + after[v - 1] + need[v - 1] + before[v]

        def centre(k: str) -> tuple[float, float]:
            c, at = root.centres[k], m[self.layer[k]]
            return (c, at) if self.down else (at, c)

        def rects() -> dict[str, Rect]:
            nbs = {k: node_box(d.nodes[k], *centre(k), t, self.slots[k]) for k in d.nodes}
            out: dict[str, Rect] = {}
            for g in sorted(self.range, key=lambda g: -len(boxes_around(d, g)) if g in d.groups else 0):
                if g not in d.groups:
                    continue
                kids = [footprint(out[c], stack(d.groups[c], out[c])) for c in self.children[g] if c in out]
                r = group_rect(d.groups[g], d, t, nbs, kids)
                if r is not None:
                    out[g] = r
            return out

        def gaps(found: dict[str, Rect]) -> tuple[list[float], list[float]]:
            """Where, along the flow, everything ending in each layer ends, and everything starting in it starts."""
            ends = [m[v] + after[v] for v in range(depth)]
            starts = [m[v] - before[v] for v in range(depth)]
            for g, r in found.items():
                f0, f1 = main_span(footprint(r, stack(d.groups[g], r)))
                r0, r1 = self.range[g]
                ends[r1] = max(ends[r1], f1)
                starts[r0] = min(starts[r0], f0)
            return ends, starts

        for v in range(depth - 1):
            ends, starts = gaps(rects())
            short = need[v] - (starts[v + 1] - ends[v])
            if short > 0.5:
                for w in range(v + 1, depth):
                    m[w] += short
        found = rects()
        ends, starts = gaps(found)
        centres = {k: centre(k) for k in d.nodes}

        def stretch(c: float, a: float, b: float) -> tuple[Point, Point]:
            return ((c, a), (c, b)) if self.down else ((a, c), (b, c))

        out: dict[str, list[tuple[Point, Point]]] = defaultdict(list)
        for mk in root.marks:
            if mk.kind == "lane":
                # Through the layer, from where what starts in it starts to where what ends in it ends.
                out[mk.edge].append(stretch(mk.c, starts[mk.layer], ends[mk.layer]))
                continue
            item = mk.item
            if item in d.nodes:
                s0, s1 = main_span(boxes[item])
                i0, i1 = m[self.layer[item]] + s0, m[self.layer[item]] + s1
            elif item in found:
                i0, i1 = main_span(footprint(found[item], stack(d.groups[item], found[item])))
            else:
                continue
            if mk.kind == "after":
                a, b = i1, max(i1, ends[mk.layer])
            else:
                a, b = min(i0, starts[mk.layer]), i0
            if b - a > 0.5:
                out[mk.edge].append(stretch(mk.c, a, b))
        return centres, dict(out)


def _held(a: str, b: str, spanning: set[str], items: dict[str, _Block]) -> bool:
    """Whether two neighbours in a layer keep their order: two items spanning several layers, which share it in each,
    or a lane point and such an item, which keeps the lane to one side of it."""
    if a in spanning and b in spanning:
        return True
    return (a in spanning and items[b].kind == "lane") or (b in spanning and items[a].kind == "lane")


def _reaches(graph: dict[str, list[str]], start: str, goal: str) -> bool:
    seen, todo = {start}, [start]
    while todo:
        v = todo.pop()
        if v == goal:
            return True
        for w in graph.get(v, ()):
            if w not in seen:
                seen.add(w)
                todo.append(w)
    return False


def _apart(row: list[str], flats: list[tuple[str, str]]) -> float:
    """How far apart the pairs an edge joins across the flow are in a row, as a cost: each item between them would
    sit on the edge."""
    n = 0.0
    for u, v in flats:
        if u in row and v in row:
            n += 4 * max(0, abs(row.index(u) - row.index(v)) - 1)
    return n


def _flat_stretch(wants: list[tuple[float, float]]) -> tuple[float, float]:
    """Where a sum of weighted distances to sorted values is least: one value, or the stretch between two when the
    weights on either side of it are equal."""
    total = sum(w for _, w in wants)
    run = 0.0
    for i, (v, w) in enumerate(wants):
        run += w
        if abs(run - total / 2) < 1e-9 and i + 1 < len(wants):
            return v, wants[i + 1][0]
        if run > total / 2:
            return v, v
    return wants[-1][0], wants[-1][0]
