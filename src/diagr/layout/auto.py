"""Automatic placement for nodes without `at`.

Nodes are put in layers along the main axis (`direction`: right or down) so edges point forward: a node goes one layer
after the nodes that lead to it. On the cross axis every group gets its own band, nested inside its parent's band and
spaced so the group boxes do not overlap; within a layer, a band's nodes are ordered by where their incoming
neighbours sit, which keeps crossings down. Nodes with `at` keep it, and placed nodes move aside rather than land on
one of them.
"""

from __future__ import annotations

from collections import defaultdict

from ..model import Diagram, Node, boxes_around
from .flow import laid_out
from .geometry import BUTTON_H, STRIP_H

# How far a box reaches past its cells, in px, for the default theme: (before, after) on the cross axis. A node sits
# inside its cell; a group adds padding above and a title band below, and each level of nesting adds to both. On the
# x axis a group sits inside its cells by its inset.
NODE_Y, GROUP_Y, LEVEL_Y = (-40, -14), (40, 26), (12, 40)
NODE_X, GROUP_X, LEVEL_X = (-30, -30), (-12, -12), (12, 12)
MARGIN = 16
# Extra main-axis room where a layer boundary also crosses a group boundary, in cells.
LAYER_GAP = 0.3


def _below(n: Node) -> float:
    """How far a node's box reaches below its centre, in px, as node_box() draws it with the default theme."""
    if n.junction:
        return 4
    last = 46 + 16 * len(n.sub)
    if n.cells:
        last += 8 + STRIP_H + (16 if any(n.cells) else -4)
    bottom = last + 4
    if n.trigger:
        bottom += 17 + BUTTON_H + 4
    return bottom


def _acyclic(order: list[str], edges: list[tuple[str, str]]) -> list[tuple[str, str]]:
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
        stack = [(root, iter(out[root]))]
        while stack:
            v, ahead = stack[-1]
            w = next(ahead, None)
            if w is None:
                state[v] = 2
                stack.pop()
            elif state.get(w) == 1:
                back.add((v, w))
            elif w not in state:
                state[w] = 1
                stack.append((w, iter(out[w])))
    return [e for e in edges if e not in back]


def _topological(order: list[str], edges: list[tuple[str, str]]) -> list[str]:
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


def place(d: Diagram) -> None:
    flowed = laid_out(d)[0]
    free = [k for k, n in d.nodes.items() if n.at is None and k not in flowed]
    if not free:
        return
    for k in free:
        d.nodes[k].auto = True
    p = _Placer(d, free)
    p.assign_layers()
    p.order_boxes()
    p.bands()
    p.spacing()
    p.place_grouped()
    p.place_loose()
    p.write()


class _Placer:
    """The state the phases of `place` share, in cells: each node's layer on the main axis, each group's band on the
    cross axis, and where nodes land."""

    def __init__(self, d: Diagram, free: list[str]):
        self.d, self.free = d, free
        self.down = down = d.direction == "down"
        self.order = list(d.nodes)
        # An edge pinned to sides across the flow (bottom to top when it runs right) links nodes in one layer.
        across = ("left", "right") if down else ("top", "bottom")
        links = [
            e
            for e in d.edges.values()
            if e.src.node in d.nodes
            and e.dst.node in d.nodes
            and e.src.node != e.dst.node
            and not (e.src.side in across and e.dst.side in across)
        ]
        # A dashed edge is a side link (replication, a wake-up call): it places a node only when nothing solid does, so
        # it counts into a node with no solid edge coming in, or out of a node with no solid edge at all.
        solid = [e for e in links if not e.dashed]
        fed = {e.dst.node for e in solid}
        linked = fed | {e.src.node for e in solid}
        placing = [e for e in links if not e.dashed or e.dst.node not in fed or e.src.node not in linked]
        self.dag = _acyclic(self.order, [(e.src.node, e.dst.node) for e in placing])
        self.preds: dict[str, list[str]] = defaultdict(list)
        self.succs: dict[str, list[str]] = defaultdict(list)
        for a, b in self.dag:
            self.preds[b].append(a)
            self.succs[a].append(b)
        self.dashed = {(e.src.node, e.dst.node) for e in placing if e.dashed}
        self.topo = _topological(self.order, self.dag)
        self.layer: dict[str, float] = {}

        # Bands on the cross axis: one per group, children stacked after the group's own nodes.
        self.children: dict[str | None, list[str]] = defaultdict(list)
        for gid, g in d.groups.items():
            self.children[g.parent if g.parent in d.groups else None].append(gid)
        self.own: dict[str | None, list[str]] = defaultdict(list)
        for k in free:
            g = d.nodes[k].group
            self.own[g if g in d.groups else None].append(k)
        # The size of a cell across the flow, and along it.
        self.cell = d.grid.col if down else d.grid.row
        self.long = d.grid.row if down else d.grid.col
        self.rel: dict[str | None, float] = {}
        self.size: dict[str | None, float] = {}
        self.start: dict[str | None, float] = {None: 0.0}

    def _source(self, k: str) -> bool:
        return self.d.nodes[k].at is None and not self.preds[k]

    def _after(self, k: str) -> float:
        layer = self.layer
        counted = [p for p in self.preds[k] if p in layer and not ((p, k) in self.dashed and self._source(p))]
        return max((layer[p] + 1 for p in counted), default=0)

    def assign_layers(self) -> None:
        """Layers: pinned nodes keep their main coordinate; a free node goes one after its latest predecessor. A free
        node with no predecessor sits just before its earliest successor rather than at the very start, and its dashed
        edges do not push their targets along."""
        d, layer = self.d, self.layer
        for k in self.topo:
            at = d.nodes[k].at
            layer[k] = (at[1] if self.down else at[0]) if at is not None else self._after(k)
        # Then, from the end back, a free node with room before its successors moves up to them; a node with nothing
        # before it goes just before its solid successors.
        for k in reversed(self.topo):
            ahead = [s for s in self.succs[k] if (k, s) not in self.dashed] or self.succs[k]
            if d.nodes[k].at is None and ahead:
                target = min(layer[s] for s in ahead) - 1
                layer[k] = target if self._source(k) else max(layer[k], target)

    def chain(self, k: str) -> list[str]:
        return boxes_around(self.d, self.d.nodes[k].group)[::-1]

    def order_boxes(self) -> None:
        """Sibling boxes joined by a solid edge go one after the other, so they sit side by side rather than one below
        the other: the box an edge goes into starts after the box it comes from. Boxes with a pinned node keep their
        layers."""
        d, layer = self.d, self.layer
        pairs: list[tuple[str, str]] = []
        for a, b in self.dag:
            ca, cb = self.chain(a), self.chain(b)
            i = next((i for i, (x, y) in enumerate(zip(ca, cb, strict=False)) if x != y), min(len(ca), len(cb)))
            if (a, b) not in self.dashed and i < len(ca) and i < len(cb):
                pairs.append((ca[i], cb[i]))
        within: dict[str, list[str]] = defaultdict(list)
        for k in self.order:
            for g in self.chain(k):
                within[g].append(k)
        boxes = [
            (x, y)
            for x, y in _acyclic(list(d.groups), list(dict.fromkeys(pairs)))
            if all(d.nodes[k].at is None for k in within[x] + within[y])
        ]
        for _ in boxes:
            moved = False
            for x, y in boxes:
                need = max(layer[k] for k in within[x]) + 1 - min(layer[k] for k in within[y])
                if need > 0:
                    for k in within[y]:
                        layer[k] += need
                    moved = True
            if not moved:
                break
            for k in self.topo:
                if d.nodes[k].at is None and self.preds[k]:
                    layer[k] = max(layer[k], self._after(k))

    def used(self, g: str | None) -> bool:
        return bool(self.own[g]) or any(self.used(c) for c in self.children[g])

    def depth(self, g: str) -> int:
        live = [c for c in self.children[g] if self.used(c)]
        return 1 + max((self.depth(c) for c in live), default=0)

    def inside(self, g: str | None) -> list[str]:
        return self.own[g] + [k for c in self.children[g] if self.used(c) for k in self.inside(c)]

    def slot(self, k: str) -> float:
        """Cross cells a node takes: one, or more on the y axis for a tall node (sub lines, cells, a trigger)."""
        if self.down:
            return 1.0
        return max(1.0, -(-(_below(self.d.nodes[k]) + 40 + MARGIN) * 20 // self.cell) / 20)

    def reach(self, item: str | None) -> tuple[float, float]:
        """How far an item (a group id, or None for a block of loose nodes) reaches past its cells."""
        down, cell = self.down, self.cell
        node_ext, group_ext, level_ext = (NODE_X, GROUP_X, LEVEL_X) if down else (NODE_Y, GROUP_Y, LEVEL_Y)
        tall = 0.0 if down else max((_below(self.d.nodes[k]) - cell / 2 for k in self.inside(item)), default=0)
        if item is None:
            return (node_ext[0], max(node_ext[1], tall))
        k = self.depth(item)
        return (group_ext[0] + level_ext[0] * (k - 1), max(group_ext[1], tall + 40) + level_ext[1] * (k - 1))

    def gap(self, a: str | None, b: str | None) -> float:
        px = max(0.0, self.reach(a)[1] + self.reach(b)[0] + MARGIN)
        return -(-px * 20 // self.cell) / 20

    def span(self, g: str | None) -> tuple[float, float]:
        """The first and last layer holding a free node of g, its child groups included."""
        ls = [self.layer[k] for k in self.own[g]] + [x for c in self.children[g] if self.used(c) for x in self.span(c)]
        return min(ls), max(ls)

    def bands(self) -> None:
        """A group's band holds its own nodes first, then its child groups. A child shares rows with an earlier sibling
        when their layers do not overlap, and drops below it only when they do. Loose nodes have no band: they are
        placed last, next to their neighbours."""
        self._pack(None)
        self._resolve(None)

    def _pack(self, g: str | None) -> float:
        layer = self.layer
        counts: dict[float, float] = defaultdict(float)
        for k in self.own[g] if g is not None else []:
            counts[layer[k]] += self.slot(k)
        # A layer's nodes keep off the rows of edges passing through it from the group's own nodes: room for those.
        mine = set(self.own[g]) if g is not None else set()
        for v in list(counts):
            counts[v] += sum(1 for u, w in self.dag if u in mine and layer[u] < v < layer[w])
        placed: list[tuple[float, float, float, float, str | None]] = []
        end = max(counts.values(), default=0.0)
        if counts:
            placed.append((min(counts), max(counts), 0.0, end, None))
        for c in [x for x in self.children[g] if self.used(x)]:
            h = self._pack(c)
            lo, hi = self.span(c)
            pos, moved = 0.0, True
            while moved:
                moved = False
                for plo, phi, top, bottom, item in placed:
                    share = lo <= phi and plo <= hi
                    if share and pos < bottom + self.gap(item, c) and pos + h + self.gap(c, item) > top:
                        pos, moved = bottom + self.gap(item, c), True
            self.rel[c] = pos
            placed.append((lo, hi, pos, pos + h, c))
            end = max(end, pos + h)
        self.size[g] = end
        return end

    def _resolve(self, g: str | None) -> None:
        for c in self.children[g]:
            if c in self.rel:
                self.start[c] = self.start[g] + self.rel[c]
                self._resolve(c)

    def spacing(self) -> None:
        """Main-axis spacing: where the groups present change from one layer to the next, room for the boxes that close
        and those that open, and never less than LAYER_GAP."""
        d, layer = self.d, self.layer
        self.layers = layers = sorted(set(layer.values()))
        self.at_layer = {v: [k for k in layer if layer[k] == v] for v in layers}
        present: dict[float, set[str]] = {}
        for v in layers:
            present[v] = set()
            for k in self.at_layer[v]:
                present[v].update(boxes_around(d, d.nodes[k].group))
        self.main: dict[float, float] = {}
        shift = 0.0
        for i, v in enumerate(layers):
            u = layers[i - 1] if i else None
            if u is not None and present[u] != present[v]:
                px = self._edge(u, present[u] - present[v], 1) + self._edge(v, present[v] - present[u], 0) + MARGIN
                shift += max(LAYER_GAP, -(-px * 20 // self.long) / 20)
            self.main[v] = v + shift

    def _edge(self, v: float, gs: set[str], after: int) -> float:
        """How far the boxes of layer v reach past its cells, before it (after=0) or past it (after=1)."""
        down = self.down
        m_node, m_group, m_level = (NODE_Y, GROUP_Y, LEVEL_Y) if down else (NODE_X, GROUP_X, LEVEL_X)
        nodes = self.at_layer[v]
        tall = max((_below(self.d.nodes[k]) - self.long / 2 for k in nodes), default=0.0) if down and after else 0.0
        px = max(m_node[after], tall)
        for g in gs:
            px = max(
                px, max(m_group[after], tall + 40 if tall else m_group[after]) + m_level[after] * (self.depth(g) - 1)
            )
        return px

    def lanes(self, v: float) -> set[float]:
        """Rows an edge already placed runs along through layer v; nodes keep off them."""
        cross, layer = self.cross, self.layer
        return {cross[u] for u, w in self.dag if u in cross and layer[u] < v < layer[w]}

    def clear(self, v: float, y: float, h: float, bands: bool) -> bool:
        start, size = self.start, self.size
        if any(m == self.main[v] and y < c + s and c < y + h for m, c, s in self.taken):
            return False
        if any(abs(y - ln) < 0.5 for ln in self.lanes(v)):
            return False
        for c in self.children[None] if bands else []:
            if c in size and self.span(c)[0] <= v <= self.span(c)[1]:
                if y + h + self.gap(None, c) > start[c] and y < start[c] + size[c] + self.gap(c, None):
                    return False
        return True

    def bary(self, ns: list[str]) -> float | None:
        ps = [self.cross[p] for p in ns if p in self.cross]
        return sum(ps) / len(ps) if ps else None

    def place_grouped(self) -> None:
        """Grouped nodes, layer by layer: a band's nodes are ordered by their predecessors' average cross position."""
        d, layer, main, order = self.d, self.layer, self.main, self.order
        # Pinned nodes hold their places first.
        self.cross = cross = {k: (n.at[0] if self.down else n.at[1]) for k, n in d.nodes.items() if n.at is not None}
        self.taken: list[tuple[float, float, float]] = [(main.get(layer[k], layer[k]), cross[k], 1.0) for k in cross]

        def key(k: str) -> tuple[float, int]:
            b = self.bary(self.preds[k])
            return (float(order.index(k)) if b is None else b, order.index(k))

        for v in self.layers:
            for g, members in self.own.items():
                # own is a defaultdict, and asking used() about a group adds it with no members.
                if g is None or not members:
                    continue
                here = [k for k in members if layer[k] == v]
                here.sort(key=key)
                at = self.start[g]
                for k in here:
                    while not self.clear(v, at, self.slot(k), False):
                        at += 1
                    cross[k] = at
                    self.taken.append((main[v], at, self.slot(k)))
                    at += self.slot(k)

    def place_loose(self) -> None:
        """Loose nodes: as close as they can get to the average of their neighbours, outside every group's band."""
        layer, main, cross, taken = self.layer, self.main, self.cross, self.taken
        start, size, children = self.start, self.size, self.children
        for k in sorted(self.own[None], key=lambda k: (layer[k], self.order.index(k))):
            v, h = layer[k], self.slot(k)
            want = self.bary(self.preds[k] + self.succs[k])
            want = 0.0 if want is None else want
            options = {want, round(want)}
            options |= {c - h for m, c, _ in taken if m == main[v]} | {c + s for m, c, s in taken if m == main[v]}
            options |= {ln + 0.5 for ln in self.lanes(v)} | {ln - h - 0.5 for ln in self.lanes(v)}
            for c in children[None]:
                if c in size:
                    options |= {start[c] - self.gap(None, c) - h, start[c] + size[c] + self.gap(c, None)}
            # Its edges forward run along its row: keep it off rows where they would pass through a node on the way.
            ends = [main[layer[s]] for s in self.succs[k] if layer[s] > v]
            # A node's slot starts 40px above its centre (its icon and badge) and ends below its labels and button.
            top = (40 + 8) / self.cell
            between = [(c - top, c + s - top) for m, c, s in taken if ends and main[v] < m < max(ends)]
            aims = {g for s in self.succs[k] for g in self.chain(s)}
            for c in children[None]:
                if ends and c in size and c not in aims and main[v] < main[self.span(c)[0]] < max(ends):
                    # Where its nodes landed, which can be further down than its band when they kept off a lane.
                    ins = [n for n in self.inside(c) if n in cross]
                    lo, hi = self.reach(c)
                    between.append(
                        (
                            min(cross[n] for n in ins) - top - (lo + 8) / self.cell,
                            max(cross[n] + self.slot(n) for n in ins) - top + (hi + 8) / self.cell,
                        )
                    )
            options |= {lo - 0.01 for lo, _ in between} | {hi + 0.01 for _, hi in between}
            options |= {lo - h - 0.5 for lo, _ in between} | {hi + 0.5 for _, hi in between}
            fits = [y for y in options if self.clear(v, y, h, True)]
            open_ = [y for y in fits if not any(lo < y < hi for lo, hi in between)]
            fits = open_ or fits
            y = min(fits, key=lambda y: (abs(y - want), -y)) if fits else max(c + s for _, c, s in taken)
            cross[k] = y
            taken.append((main[v], y, h))

    def write(self) -> None:
        """Each free node's cell. With nothing pinned, the diagram starts at [0, 0]."""
        d, free, main, cross, layer = self.d, self.free, self.main, self.cross, self.layer
        pinned = any(not n.auto for n in d.nodes.values())
        m0 = 0.0 if pinned else min(main[layer[k]] for k in free)
        c0 = 0.0 if pinned else min(cross[k] for k in free)
        for k in free:
            m, c = round(main[layer[k]] - m0, 2), round(cross[k] - c0, 2)
            d.nodes[k].at = (c, m) if self.down else (m, c)
