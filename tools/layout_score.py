"""Score how well diagr lays out and routes a set of diagrams, so a change to the engine can be judged by numbers.

    python tools/layout_score.py                    # the examples and the layout test cases
    python tools/layout_score.py a.yml b.yml        # these files
    python tools/layout_score.py --json             # every number, for comparing two runs

For each diagram, and each of its views, it counts what makes a picture harder to read. Hard faults should be zero:
edges through nodes or across group titles, labels covering nodes or other labels, nodes on top of each other. Then,
lower is better: crossings between edges, edges lying on top of each other, bends, jogs (a run shorter than JOG
between two turns), labels on a run too short for them or right by a turn, edges running close along a box they do
not enter, total edge length, and the area of the picture. `score` weighs them into one number. What only a
scenario brings out, a hidden edge or one to a hidden node, counts HIDDEN as much as what the picture shows.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from diagr.build import Prepared, prepare
from diagr.layout.geometry import Point, Rect
from diagr.model import boxes_around
from diagr.parse import load_file, loads
from diagr.validate import check_layout
from diagr.views import view

ROOT = Path(__file__).resolve().parent.parent
JOG = 12.0
HIDDEN = 0.25
HUG = 6.0
LABEL_CLEAR = 10.0
WEIGHTS = {
    "faults": 1000.0,
    "crossings": 20.0,
    "overlaps": 40.0,
    "bends": 2.0,
    "jogs": 15.0,
    "cramped_labels": 10.0,
    "hugs": 5.0,
    "length": 0.002,
    "area": 0.00002,
}


@dataclass
class Score:
    name: str
    faults: int = 0
    crossings: float = 0
    overlaps: float = 0
    bends: float = 0
    jogs: float = 0
    cramped_labels: float = 0
    hugs: float = 0
    length: float = 0.0
    area: float = 0.0
    edges: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return round(sum(WEIGHTS[k] * getattr(self, k) for k in WEIGHTS), 1)


Segment = tuple[Point, Point]


def _segments(pts: list[Point]) -> list[Segment]:
    return [(a, b) for a, b in zip(pts, pts[1:], strict=False) if math.dist(a, b) > 0.01]


def _flat(s: Segment) -> bool:
    return abs(s[0][1] - s[1][1]) < 0.5


def _crosses(s: Segment, t: Segment) -> bool:
    """Whether a horizontal and a vertical segment cross strictly inside both."""
    if _flat(s) == _flat(t):
        return False
    h, v = (s, t) if _flat(s) else (t, s)
    y, x = h[0][1], v[0][0]
    x0, x1 = sorted((h[0][0], h[1][0]))
    y0, y1 = sorted((v[0][1], v[1][1]))
    return x0 + 0.5 < x < x1 - 0.5 and y0 + 0.5 < y < y1 - 0.5


def _overlap(s: Segment, t: Segment) -> float:
    """How long two segments lie on one line together."""
    if _flat(s) != _flat(t):
        return 0.0
    axis = 0 if _flat(s) else 1
    if abs(s[0][1 - axis] - t[0][1 - axis]) > 0.5:
        return 0.0
    a0, a1 = sorted((s[0][axis], s[1][axis]))
    b0, b1 = sorted((t[0][axis], t[1][axis]))
    return max(0.0, min(a1, b1) - max(a0, b0))


def _near(s: Segment, r: Rect) -> bool:
    """Whether a segment runs alongside one of r's sides, within HUG px of it, inside or out, for more than 20px."""
    if _flat(s):
        y = s[0][1]
        x0, x1 = sorted((s[0][0], s[1][0]))
        along = min(x1, r.x1) - max(x0, r.x)
        return along > 20 and (abs(r.y - y) < HUG or abs(y - r.y1) < HUG)
    x = s[0][0]
    y0, y1 = sorted((s[0][1], s[1][1]))
    along = min(y1, r.y1) - max(y0, r.y)
    return along > 20 and (abs(r.x - x) < HUG or abs(x - r.x1) < HUG)


def score(p: Prepared, name: str) -> Score:
    d, lay = p.diagram, p.layout
    sc = Score(name, edges=len(lay.edges))
    sc.faults = sum(1 for w in check_layout(d, lay, p.theme))
    sc.area = round(lay.bounds.w * lay.bounds.h)
    segs = {k: _segments(e.points) for k, e in lay.edges.items()}
    weight = {k: HIDDEN if _hidden(d, k) else 1.0 for k in segs}
    keys = list(segs)
    for i, a in enumerate(keys):
        ea = d.edges[a]
        for b in keys[i + 1 :]:
            eb = d.edges[b]
            shared = {ea.src.node, ea.dst.node} & {eb.src.node, eb.dst.node}
            for s in segs[a]:
                for t in segs[b]:
                    if _crosses(s, t):
                        sc.crossings += min(weight[a], weight[b])
                        sc.notes.append(f"crossing: {a} x {b}")
                    # Edges that share an end may share a trunk; any other two must not lie on each other.
                    elif not shared and _overlap(s, t) > 4:
                        sc.overlaps += min(weight[a], weight[b])
                        sc.notes.append(f"overlap: {a} on {b}")
    for k, e in lay.edges.items():
        ss = segs[k]
        sc.bends += weight[k] * max(0, len(ss) - 1)
        sc.length += sum(math.dist(*s) for s in ss)
        for s in ss[1:-1]:
            if math.dist(*s) < JOG:
                sc.jogs += weight[k]
                sc.notes.append(f"jog: {k}")
        if e.label_box and e.label_at:
            # A label needs a clear stretch of line either side of it: LABEL_CLEAR px on a horizontal run, more on
            # an upright one, where it reads across the line.
            on = next((s for s in ss if _on(s, e.label_at)), None)
            flat = on is not None and _flat(on)
            half = e.label_box.w / 2 if flat else e.label_box.h / 2
            clear = LABEL_CLEAR if flat else 2 * LABEL_CLEAR
            room = math.dist(*on) if on else 0.0
            turn = min((math.dist(e.label_at, q) for q in e.points[1:-1]), default=math.inf)
            if room < 2 * (half + clear) or turn < half + clear:
                sc.cramped_labels += weight[k]
                sc.notes.append(f"cramped label: {k}")
        edge = d.edges[k]
        inside = set(boxes_around(d, _group(d, edge.src.node))) | set(boxes_around(d, _group(d, edge.dst.node)))
        boxes = [nb.box for n, nb in lay.nodes.items() if n not in (edge.src.node, edge.dst.node) and not nb.point]
        boxes += [r for g, r in lay.groups.items() if g not in inside and d.groups[g].box]
        for s in ss:
            if any(_near(s, r) for r in boxes):
                sc.hugs += weight[k]
                sc.notes.append(f"hug: {k}")
    sc.length = round(sc.length)
    return sc


def _hidden(d, k: str) -> bool:
    e = d.edges[k]
    return e.hidden or any(d.nodes[n].hidden for n in (e.src.node, e.dst.node) if n in d.nodes)


def _group(d, end: str) -> str | None:
    return d.nodes[end].group if end in d.nodes else end


def _on(s: Segment, p: Point) -> bool:
    (ax, ay), (bx, by) = s
    return min(ax, bx) - 0.5 <= p[0] <= max(ax, bx) + 0.5 and min(ay, by) - 0.5 <= p[1] <= max(ay, by) + 0.5


def cases() -> list[tuple[str, object]]:
    """The examples, and the diagrams the layout tests use."""
    out: list[tuple[str, object]] = [(f.parent.name, f) for f in sorted((ROOT / "examples").glob("*/diagram.yml"))]
    sys.path.insert(0, str(ROOT))
    from tests import test_auto

    for name in ("CHAIN", "GROUPS", "FED_FROM_ROW_ZERO", "BOTH_WAYS", "THROUGH_PARENT", "BACK"):
        out.append((name.lower(), getattr(test_auto, name)))
    return out


def run(items: list[tuple[str, object]]) -> list[Score]:
    out = []
    for name, src in items:
        d = load_file(src) if isinstance(src, Path) else loads(str(src), f"{name}.yml", ROOT)
        out.append(score(prepare(d), name))
        for vid in d.views:
            out.append(score(prepare(view(d, vid)), f"{name}/{vid}"))
    return out


def _num(v: float) -> float | int:
    return int(v) if float(v).is_integer() else round(v, 2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--notes", action="store_true", help="list what each count is made of")
    args = ap.parse_args()
    items = [(f.stem if f.name != "diagram.yml" else f.parent.name, f) for f in args.files] or cases()
    scores = run(items)
    if args.json:
        print(json.dumps([asdict(s) | {"score": s.score} for s in scores], indent=1))
        return
    cols = ["faults", "crossings", "overlaps", "bends", "jogs", "cramped_labels", "hugs", "length", "area"]
    head = ["diagram", *cols, "score"]
    rows = [[s.name, *(_num(getattr(s, c)) for c in cols), s.score] for s in scores]
    total = ["total", *(_num(sum(getattr(s, c) for s in scores)) for c in cols), round(sum(s.score for s in scores), 1)]
    rows.append(total)
    widths = [max(len(str(r[i])) for r in [head, *rows]) for i in range(len(head))]
    for r in [head, *rows]:
        print(
            "  ".join(str(v).rjust(w) if i else str(v).ljust(w) for i, (v, w) in enumerate(zip(r, widths, strict=True)))
        )
    if args.notes:
        for s in scores:
            for n in s.notes:
                print(f"{s.name}: {n}")


if __name__ == "__main__":
    main()
