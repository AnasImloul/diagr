"""Automatic placement for nodes without `at`.

Nodes are put in layers along the main axis (`direction`: right or down) so edges point forward: a node goes one layer
after the nodes that lead to it. On the cross axis every group gets its own band, nested inside its parent's band and
spaced so the group boxes do not overlap; within a layer, a band's nodes are ordered by where their incoming
neighbours sit, which keeps crossings down. Nodes with `at` keep it, and placed nodes move aside rather than land on
one of them.
"""

from __future__ import annotations

from collections import defaultdict

from ..model import Diagram, Node
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

    def walk(v: str) -> None:
        state[v] = 1
        for w in out[v]:
            if state.get(w) == 1:
                back.add((v, w))
            elif w not in state:
                walk(w)
        state[v] = 2

    for v in order:
        if v not in state:
            walk(v)
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
    from .flow import laid_out

    flowed = laid_out(d)[0]
    free = [k for k, n in d.nodes.items() if n.at is None and k not in flowed]
    if not free:
        return
    for k in free:
        d.nodes[k].auto = True
    down = d.direction == "down"
    order = list(d.nodes)
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
    dag = _acyclic(order, [(e.src.node, e.dst.node) for e in placing])
    preds, succs = defaultdict(list), defaultdict(list)
    for a, b in dag:
        preds[b].append(a)
        succs[a].append(b)

    dashed = {(e.src.node, e.dst.node) for e in placing if e.dashed}

    def source(k: str) -> bool:
        return d.nodes[k].at is None and not preds[k]

    # Layers: pinned nodes keep their main coordinate; a free node goes one after its latest predecessor. A free node
    # with no predecessor sits just before its earliest successor rather than at the very start, and its dashed edges
    # do not push their targets along.
    layer: dict[str, float] = {}
    topo = _topological(order, dag)

    def after(k: str) -> float:
        counted = [p for p in preds[k] if p in layer and not ((p, k) in dashed and source(p))]
        return max((layer[p] + 1 for p in counted), default=0)

    for k in topo:
        at = d.nodes[k].at
        layer[k] = (at[1] if down else at[0]) if at is not None else after(k)
    # Then, from the end back, a free node with room before its successors moves up to them; a node with nothing
    # before it goes just before its solid successors.
    for k in reversed(topo):
        ahead = [s for s in succs[k] if (k, s) not in dashed] or succs[k]
        if d.nodes[k].at is None and ahead:
            target = min(layer[s] for s in ahead) - 1
            layer[k] = target if source(k) else max(layer[k], target)

    # Sibling boxes joined by a solid edge go one after the other, so they sit side by side rather than one below the
    # other: the box an edge goes into starts after the box it comes from. Boxes with a pinned node keep their layers.
    def chain(k: str) -> list[str]:
        out: list[str] = []
        g = d.nodes[k].group
        while g in d.groups and g not in out:
            out.append(g)
            g = d.groups[g].parent
        return out[::-1]

    pairs: list[tuple[str, str]] = []
    for a, b in dag:
        ca, cb = chain(a), chain(b)
        i = next((i for i, (x, y) in enumerate(zip(ca, cb, strict=False)) if x != y), min(len(ca), len(cb)))
        if (a, b) not in dashed and i < len(ca) and i < len(cb):
            pairs.append((ca[i], cb[i]))
    within: dict[str, list[str]] = defaultdict(list)
    for k in order:
        for g in chain(k):
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
        for k in topo:
            if d.nodes[k].at is None and preds[k]:
                layer[k] = max(layer[k], after(k))

    # Bands on the cross axis: one per group, children stacked after the group's own nodes.
    children: dict[str | None, list[str]] = defaultdict(list)
    for gid, g in d.groups.items():
        children[g.parent if g.parent in d.groups else None].append(gid)
    own: dict[str | None, list[str]] = defaultdict(list)
    for k in free:
        g = d.nodes[k].group
        own[g if g in d.groups else None].append(k)

    def used(g: str | None) -> bool:
        return bool(own[g]) or any(used(c) for c in children[g])

    def depth(g: str) -> int:
        live = [c for c in children[g] if used(c)]
        return 1 + max((depth(c) for c in live), default=0)

    cell = d.grid.col if down else d.grid.row
    node_ext, group_ext, level_ext = (NODE_X, GROUP_X, LEVEL_X) if down else (NODE_Y, GROUP_Y, LEVEL_Y)

    def inside(g: str | None) -> list[str]:
        return own[g] + [k for c in children[g] if used(c) for k in inside(c)]

    def slot(k: str) -> float:
        """Cross cells a node takes: one, or more on the y axis for a tall node (sub lines, cells, a trigger)."""
        if down:
            return 1.0
        return max(1.0, -(-(_below(d.nodes[k]) + 40 + MARGIN) * 20 // cell) / 20)

    def reach(item: str | None) -> tuple[float, float]:
        """How far an item (a group id, or None for a block of loose nodes) reaches past its cells."""
        tall = 0.0 if down else max((_below(d.nodes[k]) - cell / 2 for k in inside(item)), default=0)
        if item is None:
            return (node_ext[0], max(node_ext[1], tall))
        k = depth(item)
        return (group_ext[0] + level_ext[0] * (k - 1), max(group_ext[1], tall + 40) + level_ext[1] * (k - 1))

    def gap(a: str | None, b: str | None) -> float:
        px = max(0.0, reach(a)[1] + reach(b)[0] + MARGIN)
        return -(-px * 20 // cell) / 20

    def span(g: str | None) -> tuple[float, float]:
        """The first and last layer holding a free node of g, its child groups included."""
        ls = [layer[k] for k in own[g]] + [x for c in children[g] if used(c) for x in span(c)]
        return min(ls), max(ls)

    # A group's band holds its own nodes first, then its child groups. A child shares rows with an earlier sibling
    # when their layers do not overlap, and drops below it only when they do. Loose nodes have no band: they are
    # placed last, next to their neighbours.
    rel: dict[str | None, float] = {}
    size: dict[str | None, float] = {}

    def pack(g: str | None) -> float:
        counts: dict[float, float] = defaultdict(float)
        for k in own[g] if g is not None else []:
            counts[layer[k]] += slot(k)
        # A layer's nodes keep off the rows of edges passing through it from the group's own nodes: room for those.
        mine = set(own[g]) if g is not None else set()
        for v in list(counts):
            counts[v] += sum(1 for u, w in dag if u in mine and layer[u] < v < layer[w])
        placed: list[tuple[float, float, float, float, str | None]] = []
        end = max(counts.values(), default=0.0)
        if counts:
            placed.append((min(counts), max(counts), 0.0, end, None))
        for c in [x for x in children[g] if used(x)]:
            h = pack(c)
            lo, hi = span(c)
            pos, moved = 0.0, True
            while moved:
                moved = False
                for plo, phi, top, bottom, item in placed:
                    share = lo <= phi and plo <= hi
                    if share and pos < bottom + gap(item, c) and pos + h + gap(c, item) > top:
                        pos, moved = bottom + gap(item, c), True
            rel[c] = pos
            placed.append((lo, hi, pos, pos + h, c))
            end = max(end, pos + h)
        size[g] = end
        return end

    pack(None)
    start: dict[str | None, float] = {None: 0.0}

    def resolve(g: str | None) -> None:
        for c in children[g]:
            if c in rel:
                start[c] = start[g] + rel[c]
                resolve(c)

    resolve(None)

    # Main-axis spacing: where the groups present change from one layer to the next, room for the boxes that close
    # and those that open, and never less than LAYER_GAP.
    long = d.grid.row if down else d.grid.col
    m_node, m_group, m_level = (NODE_Y, GROUP_Y, LEVEL_Y) if down else (NODE_X, GROUP_X, LEVEL_X)
    layers = sorted(set(layer.values()))
    at_layer = {v: [k for k in layer if layer[k] == v] for v in layers}
    present: dict[float, set[str]] = {}
    for v in layers:
        present[v] = set()
        for k in at_layer[v]:
            g = d.nodes[k].group
            while g in d.groups and g not in present[v]:
                present[v].add(g)
                g = d.groups[g].parent

    def edge(v: float, gs: set[str], after: int) -> float:
        """How far the boxes of layer v reach past its cells, before it (after=0) or past it (after=1)."""
        tall = max((_below(d.nodes[k]) - long / 2 for k in at_layer[v]), default=0.0) if down and after else 0.0
        px = max(m_node[after], tall)
        for g in gs:
            px = max(px, max(m_group[after], tall + 40 if tall else m_group[after]) + m_level[after] * (depth(g) - 1))
        return px

    main: dict[float, float] = {}
    shift = 0.0
    for i, v in enumerate(layers):
        u = layers[i - 1] if i else None
        if u is not None and present[u] != present[v]:
            px = edge(u, present[u] - present[v], 1) + edge(v, present[v] - present[u], 0) + MARGIN
            shift += max(LAYER_GAP, -(-px * 20 // long) / 20)
        main[v] = v + shift

    cross: dict[str, float] = {k: (n.at[0] if down else n.at[1]) for k, n in d.nodes.items() if n.at is not None}
    taken: list[tuple[float, float, float]] = [(main.get(layer[k], layer[k]), cross[k], 1.0) for k in cross]

    def lanes(v: float) -> set[float]:
        """Rows an edge already placed runs along through layer v; nodes keep off them."""
        return {cross[u] for u, w in dag if u in cross and layer[u] < v < layer[w]}

    def clear(v: float, y: float, h: float, bands: bool) -> bool:
        if any(m == main[v] and y < c + s and c < y + h for m, c, s in taken):
            return False
        if any(abs(y - ln) < 0.5 for ln in lanes(v)):
            return False
        for c in children[None] if bands else []:
            if c in size and span(c)[0] <= v <= span(c)[1]:
                if y + h + gap(None, c) > start[c] and y < start[c] + size[c] + gap(c, None):
                    return False
        return True

    def bary(ns: list[str]) -> float | None:
        ps = [cross[p] for p in ns if p in cross]
        return sum(ps) / len(ps) if ps else None

    # Grouped nodes, layer by layer: a band's nodes are ordered by their predecessors' average cross position.
    for v in layers:
        for g, members in own.items():
            if g is None:
                continue
            here = [k for k in members if layer[k] == v]
            here.sort(key=lambda k: (bary(preds[k]) or float(order.index(k)), order.index(k)))
            at = start[g]
            for k in here:
                while not clear(v, at, slot(k), False):
                    at += 1
                cross[k] = at
                taken.append((main[v], at, slot(k)))
                at += slot(k)

    # Loose nodes: as close as they can get to the average of their neighbours, outside every group's band.
    for k in sorted(own[None], key=lambda k: (layer[k], order.index(k))):
        v, h = layer[k], slot(k)
        want = bary(preds[k] + succs[k])
        want = 0.0 if want is None else want
        options = {want, round(want)}
        options |= {c - h for m, c, _ in taken if m == main[v]} | {c + s for m, c, s in taken if m == main[v]}
        options |= {ln + 0.5 for ln in lanes(v)} | {ln - h - 0.5 for ln in lanes(v)}
        for c in children[None]:
            if c in size:
                options |= {start[c] - gap(None, c) - h, start[c] + size[c] + gap(c, None)}
        # Its edges forward run along its row: keep it off rows where they would pass through a node on the way.
        ends = [main[layer[s]] for s in succs[k] if layer[s] > v]
        # A node's slot starts 40px above its centre (its icon and badge) and ends below its labels and button.
        top = (40 + 8) / cell
        between = [(c - top, c + s - top) for m, c, s in taken if ends and main[v] < m < max(ends)]
        aims = {g for s in succs[k] for g in chain(s)}
        for c in children[None]:
            if ends and c in size and c not in aims and main[v] < main[span(c)[0]] < max(ends):
                # Where its nodes landed, which can be further down than its band when they kept off a lane.
                ins = [n for n in inside(c) if n in cross]
                lo, hi = reach(c)
                between.append(
                    (
                        min(cross[n] for n in ins) - top - (lo + 8) / cell,
                        max(cross[n] + slot(n) for n in ins) - top + (hi + 8) / cell,
                    )
                )
        options |= {lo - 0.01 for lo, _ in between} | {hi + 0.01 for _, hi in between}
        options |= {lo - h - 0.5 for lo, _ in between} | {hi + 0.5 for _, hi in between}
        fits = [y for y in options if clear(v, y, h, True)]
        open_ = [y for y in fits if not any(lo < y < hi for lo, hi in between)]
        fits = open_ or fits
        y = min(fits, key=lambda y: (abs(y - want), -y)) if fits else max(c + s for _, c, s in taken)
        cross[k] = y
        taken.append((main[v], y, h))

    # With nothing pinned, the diagram starts at [0, 0].
    pinned = any(not n.auto for n in d.nodes.values())
    m0 = 0.0 if pinned else min(main[layer[k]] for k in free)
    c0 = 0.0 if pinned else min(cross[k] for k in free)
    for k in free:
        m, c = round(main[layer[k]] - m0, 2), round(cross[k] - c0, 2)
        d.nodes[k].at = (c, m) if down else (m, c)
