"""Where edge labels go once every edge has its path: on the run of its edge where the label covers nothing.

A label sits on its edge, centred on the line. Each label in turn tries the middle and either side of every run of
its path and takes the place that covers the fewest things: what shows of nodes and other labels most of all, then
group titles, then other edges' lines. It keeps CLEAR px of line between it and a turn. A horizontal run long enough
for the whole label is better than one it hangs over, and a place near the middle of the path better than one near
an end. A label whose usual place covers nothing stays there.
"""

from __future__ import annotations

from .geometry import EdgePath, Point, Rect
from .route import fraction, label_point

COVER_NODE = 1000.0
COVER_LABEL = 1000.0
COVER_TITLE = 400.0
COVER_LINE = 30.0
OVERHANG = 60.0
UPRIGHT = 12.0
CLEAR = 12.0
NEAR_TURN = 50.0


def place_labels(
    paths: dict[str, EdgePath],
    boxes: list[Rect],
    titles: list[Rect],
    fixed: set[str],
) -> None:
    """Move each label in paths, except those in fixed (placed by the file), to where it covers least. boxes are what
    shows of the nodes, titles the group titles."""
    placed: list[Rect] = [p.label_box for k, p in paths.items() if k in fixed and p.label_box]
    placed += [p.badge_box for p in paths.values() if p.badge_box]
    for k, path in paths.items():
        if k in fixed or path.label_box is None or path.label_at is None:
            continue
        w, h = path.label_box.w, path.label_box.h
        others = [seg for o, p in paths.items() if o != k for seg in _segments(p.points)]
        current = path.label_at
        here = min(_candidates(path.points, w), key=lambda c: _dist(c[0], current), default=(current, 0.0))
        best, best_cost = current, _cost(path, current, w, h, boxes, titles, placed, others)
        best_cost += here[1] if _dist(here[0], current) < 1 else _fits(path.points, current, w)
        if best_cost > 0:
            for at, extra in _candidates(path.points, w):
                c = extra + _cost(path, at, w, h, boxes, titles, placed, others)
                if c < best_cost - 0.01:
                    best, best_cost = at, c
        if _dist(best, current) > 0.01:
            # Where the file would put it as a fraction along the path, so pinning it draws the same picture.
            path.label_frac = fraction(path.points, best)
            best = label_point(path.points, path.label_frac, w)
            path.label_at = best
            path.label_box = Rect(best[0] - w / 2, best[1] - h / 2, w, h)
        placed.append(path.label_box)


def _dist(a: Point, b: Point) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _fits(pts: list[Point], at: Point, w: float) -> float:
    """What a label at a place it was put costs for the run it is on: nothing on a horizontal run it fits on."""
    for a, b in _segments(pts):
        if _on(a, b, at):
            if abs(a[1] - b[1]) < 0.5:
                return 0.0 if abs(b[0] - a[0]) >= w + 2 * CLEAR else OVERHANG
            return UPRIGHT
    return 0.0


def _segments(pts: list[Point]) -> list[tuple[Point, Point]]:
    return list(zip(pts, pts[1:], strict=False))


def _cost(
    path: EdgePath,
    at: Point,
    w: float,
    h: float,
    boxes: list[Rect],
    titles: list[Rect],
    placed: list[Rect],
    others: list[tuple[Point, Point]],
) -> float:
    box = Rect(at[0] - w / 2, at[1] - h / 2, w, h)
    cost = COVER_NODE * sum(1 for b in boxes if b.overlaps(box))
    cost += COVER_LABEL * sum(1 for b in placed if b.overlaps(box))
    cost += COVER_TITLE * sum(1 for b in titles if b.overlaps(box))
    cost += COVER_LINE * sum(1 for a, b in others if _hits(a, b, box))
    # Its own path, other than the run it sits on, running through it.
    own = [(a, b) for a, b in _segments(path.points) if not _on(a, b, at)]
    cost += COVER_LINE * sum(1 for a, b in own if _hits(a, b, box))
    # Too near a turn of its own, where the line it labels is hard to tell.
    half = w / 2 if any(_on(a, b, at) and abs(a[1] - b[1]) < 0.5 for a, b in _segments(path.points)) else h / 2
    if any(abs(at[0] - q[0]) + abs(at[1] - q[1]) < half + CLEAR for q in path.points[1:-1]):
        cost += NEAR_TURN
    return cost


def _on(a: Point, b: Point, p: Point) -> bool:
    across = min(a[0], b[0]) - 0.5 <= p[0] <= max(a[0], b[0]) + 0.5
    return across and min(a[1], b[1]) - 0.5 <= p[1] <= max(a[1], b[1]) + 0.5


def _hits(a: Point, b: Point, r: Rect) -> bool:
    return min(a[0], b[0]) < r.x1 and max(a[0], b[0]) > r.x and min(a[1], b[1]) < r.y1 and max(a[1], b[1]) > r.y


def _candidates(pts: list[Point], w: float) -> list[tuple[Point, float]]:
    """Places along the path to try, each with what it costs for being there rather than in the middle of a long
    horizontal run near the middle of the path."""
    lengths = [abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in _segments(pts)]
    total = sum(lengths) or 1.0
    out: list[tuple[Point, float]] = []
    done = 0.0
    for (a, b), ln in zip(_segments(pts), lengths, strict=True):
        if ln < 1:
            continue
        flat = abs(a[1] - b[1]) < 0.5
        room = ln - w - 2 * CLEAR if flat else ln - 18 - 2 * CLEAR
        for f in (0.5, 0.3, 0.7, 0.15, 0.85, 0.05, 0.95):
            if room > 0:
                lo = (w / 2 + CLEAR) if flat else 9 + CLEAR
                along = lo + room * f
            else:
                along = ln / 2
                if f != 0.5:
                    continue
            p = (a[0] + (b[0] - a[0]) * along / ln, a[1] + (b[1] - a[1]) * along / ln)
            extra = 0.0 if flat else UPRIGHT
            if flat and room <= 0:
                extra += OVERHANG
            # Away from the middle of the path is a little worse.
            extra += 4 * abs((done + along) / total - 0.5)
            out.append((p, extra))
        done += ln
    return out
