"""The network simplex method, for the positions that make edges as straight as possible.

Given points on a line and constraints `x[v] - x[u] >= minlen`, each with a weight, it finds the positions that
minimise the sum of `weight * (x[v] - x[u])`, the way Graphviz's dot assigns ranks and coordinates (Gansner et al.,
"A technique for drawing directed graphs", 1993). The constraints must not form a cycle.

It starts from the lowest positions that meet every constraint, takes a spanning tree of constraints that are met
exactly, and then swaps tree edges while that lowers the sum: a tree edge whose cut value is negative leaves, and the
edge with the least slack across the cut it leaves enters.
"""

from __future__ import annotations

from collections import defaultdict

EPS = 1e-7


def solve(n: int, edges: list[tuple[int, int, float, float]]) -> list[float]:
    """Positions for points 0..n-1 that meet every (u, v, minlen, weight) constraint, x[v] - x[u] >= minlen, with the
    least sum of weight * (x[v] - x[u]). Each part of the graph that no constraint joins to another is solved alone
    and starts at 0."""
    x = _shortest(n, edges)
    for part in _parts(n, edges):
        _Simplex(x, edges, part).run()
    return x


def _shortest(n: int, edges: list[tuple[int, int, float, float]]) -> list[float]:
    """The positions that meet every constraint with each point as low as it can go, in topological order."""
    indeg = [0] * n
    out: dict[int, list[int]] = defaultdict(list)
    for i, (u, v, _, _) in enumerate(edges):
        out[u].append(i)
        indeg[v] += 1
    x: list[float | None] = [None] * n
    ready = [v for v in range(n) if indeg[v] == 0]
    for v in ready:
        x[v] = 0.0
    while ready:
        u = ready.pop()
        for i in out[u]:
            _, v, m, _ = edges[i]
            at = (x[u] or 0.0) + m
            x[v] = at if x[v] is None else max(x[v] or 0.0, at)
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
    return [v or 0.0 for v in x]


def _parts(n: int, edges: list[tuple[int, int, float, float]]) -> list[list[int]]:
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for u, v, _, _ in edges:
        parent[find(u)] = find(v)
    groups: dict[int, list[int]] = defaultdict(list)
    for v in range(n):
        groups[find(v)].append(v)
    return list(groups.values())


class _Simplex:
    def __init__(self, x: list[float], edges: list[tuple[int, int, float, float]], part: list[int]):
        self.x, self.all = x, edges
        inside = set(part)
        self.nodes = part
        self.edges = [i for i, (u, _, _, _) in enumerate(edges) if u in inside]
        self.inc: dict[int, list[int]] = defaultdict(list)
        for i in self.edges:
            u, v, _, _ = edges[i]
            self.inc[u].append(i)
            self.inc[v].append(i)
        # What flows into each point less what flows out, by weight: summed over a subtree, its cut value.
        self.net: dict[int, float] = defaultdict(float)
        for i in self.edges:
            u, v, _, w = edges[i]
            self.net[v] += w
            self.net[u] -= w
        self.tree: set[int] = set()

    def slack(self, i: int) -> float:
        u, v, m, _ = self.all[i]
        return self.x[v] - self.x[u] - m

    def run(self) -> None:
        if len(self.nodes) < 2:
            return
        self.feasible_tree()
        for _ in range(20 * len(self.nodes) + 100):
            self.ranges()
            leave = self.leave()
            if leave is None:
                return
            enter = self.enter(leave)
            if enter is None:
                return
            self.exchange(leave, enter)

    def feasible_tree(self) -> None:
        """A spanning tree of constraints met exactly, moving parts of it until every point is in it."""
        while True:
            self.tree = set()
            seen = {self.nodes[0]}
            todo = [self.nodes[0]]
            while todo:
                u = todo.pop()
                for i in self.inc[u]:
                    a, b, _, _ = self.all[i]
                    w = b if a == u else a
                    if w not in seen and abs(self.slack(i)) < EPS:
                        seen.add(w)
                        self.tree.add(i)
                        todo.append(w)
            if len(seen) == len(self.nodes):
                return
            best, gap = None, float("inf")
            for i in self.edges:
                a, b, _, _ = self.all[i]
                if (a in seen) != (b in seen) and self.slack(i) < gap:
                    best, gap = i, self.slack(i)
            if best is None:
                return
            a, _, _, _ = self.all[best]
            delta = gap if a in seen else -gap
            for v in seen:
                self.x[v] += delta

    def ranges(self) -> None:
        """Each point's place in a walk of the tree from its first point: lim, its number after its subtree, low,
        the lowest number in its subtree, and the tree edge to its parent. A subtree's net flow is its cut value."""
        root = self.nodes[0]
        adj: dict[int, list[int]] = defaultdict(list)
        for i in self.tree:
            u, v, _, _ = self.all[i]
            adj[u].append(i)
            adj[v].append(i)
        self.lim: dict[int, int] = {}
        self.low: dict[int, int] = {}
        self.up: dict[int, int] = {}
        self.sub: dict[int, float] = {}
        counter = 0
        stack: list[tuple[int, int | None, int]] = [(root, None, 0)]
        lows: dict[int, int] = {}
        while stack:
            v, via, k = stack.pop()
            if k == 0:
                lows[v] = counter
                if via is not None:
                    self.up[v] = via
            nxt = adj[v]
            while k < len(nxt) and nxt[k] == via:
                k += 1
            if k < len(nxt):
                i = nxt[k]
                a, b, _, _ = self.all[i]
                child = b if a == v else a
                stack.append((v, via, k + 1))
                stack.append((child, i, 0))
            else:
                self.lim[v] = counter
                self.low[v] = lows[v]
                counter += 1
                self.sub[v] = self.net[v] + sum(self.sub[c] for c in self._children(v, adj))

    def _children(self, v: int, adj: dict[int, list[int]]) -> list[int]:
        out = []
        for i in adj[v]:
            if i == self.up.get(v):
                continue
            a, b, _, _ = self.all[i]
            out.append(b if a == v else a)
        return out

    def cut(self, i: int) -> float:
        """The cut value of tree edge i: the weight of edges across it the way it points, less those the other way."""
        u, v, _, _ = self.all[i]
        child = v if self.up.get(v) == i else u
        return self.sub[child] if child == v else -self.sub[child]

    def leave(self) -> int | None:
        best, value = None, -EPS
        for i in sorted(self.tree):
            c = self.cut(i)
            if c < value:
                best, value = i, c
        return best

    def inside(self, v: int, child: int) -> bool:
        return self.low[child] <= self.lim[v] <= self.lim[child]

    def enter(self, leave: int) -> int | None:
        """The non-tree edge with the least slack from the head side of the cut to the tail side."""
        u, v, _, _ = self.all[leave]
        child = v if self.up.get(v) == leave else u
        head_side = child == v
        best, gap = None, float("inf")
        for i in self.edges:
            if i in self.tree:
                continue
            a, b, _, _ = self.all[i]
            ia, ib = self.inside(a, child), self.inside(b, child)
            if ia == ib:
                continue
            # From the head's side to the tail's.
            if (head_side and ia and not ib) or (not head_side and ib and not ia):
                if self.slack(i) < gap:
                    best, gap = i, self.slack(i)
        return best

    def exchange(self, leave: int, enter: int) -> None:
        u, v, _, _ = self.all[leave]
        child = v if self.up.get(v) == leave else u
        delta = self.slack(enter)
        # The head's side moves along, by delta, until the entering edge is met exactly.
        shift = delta if child == v else -delta
        for p in self.nodes:
            if self.inside(p, child):
                self.x[p] += shift
        self.tree.discard(leave)
        self.tree.add(enter)
