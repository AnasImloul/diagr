from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape

from .icons import Icons, SvgIcon, Tile
from .layout.geometry import (
    EdgePath,
    Layout,
    NodeBox,
    Rect,
    behind_title_box,
    group_title_box,
    heading_size,
    title_place,
)
from .layout.route import badge_width, rounded
from .layout.text import text_width
from .model import Diagram, Group
from .scenario import Compiled
from .theme import Theme

SPIN_GLYPH = (
    '<path d="M46 26a15 15 0 0 0-27-5"/><path d="M18 12v10h10"/>'
    '<path d="M18 38a15 15 0 0 0 27 5"/><path d="M46 52V42H36"/>'
)
MARK_TEXT = {"new": "NEW", "removed": "REMOVED", "changed": "CHANGED"}


@dataclass
class El:
    tag: str
    attrs: dict[str, object] = field(default_factory=dict)
    children: list[El | Raw | str] = field(default_factory=list)
    paint: dict[str, str] = field(default_factory=dict)
    only: str | None = None

    def add(self, *items: El | Raw | str) -> El:
        self.children.extend(items)
        return self


@dataclass
class Raw:
    markup: str


def num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def safe_id(s: str) -> str:
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in s)


class SceneBuilder:
    def __init__(self, d: Diagram, t: Theme, lay: Layout, icons: Icons, scenarios: dict[str, Compiled]):
        self.d, self.t, self.lay, self.icons, self.scenarios = d, t, lay, icons, scenarios
        self.comp = next(iter(scenarios.values()), None)
        self.tiles_used: set[str] = set()
        self.symbols: dict[str, SvgIcon] = {}

    def fill_at(self, x: float, y: float) -> str:
        for gid in reversed(list(self.lay.groups)):
            if self.lay.groups[gid].contains((x, y)):
                return f"tone-{self.d.groups[gid].tone}-fill"
        return "bg"

    def icon(
        self, name: str | None, x: float, y: float, size: float, tone: str | None = None, stack: int = 1
    ) -> list[El]:
        ic = self.icons.get(name) if name else None
        if ic is None:
            return [
                El(
                    "rect",
                    {
                        "x": num(x - size / 2),
                        "y": num(y - size / 2),
                        "width": num(size),
                        "height": num(size),
                        "rx": num(size * 10 / 64),
                        "fill-opacity": ".5",
                    },
                    paint={"fill": "muted"},
                )
            ]
        out: list[El] = []
        for k in range(stack - 1, -1, -1):
            dx, dy = 5 * k, -5 * k
            out.append(self._one(ic, x + dx, y + dy, size, tone, faded=k > 0))
        return out

    def _one(self, ic: Tile | SvgIcon, x: float, y: float, size: float, tone: str | None, faded: bool) -> El:
        if isinstance(ic, Tile):
            tone = tone or ic.tone
            self.tiles_used.add(tone)
            g = El(
                "g",
                {
                    "class": "tile",
                    "transform": f"translate({num(x - size / 2)} {num(y - size / 2)}) scale({num(size / 64)})",
                },
            )
            if faded:
                g.attrs["opacity"] = ".55"
            g.add(El("rect", {"width": 64, "height": 64, "rx": 10, "fill": f"url(#tile-{tone})"}))
            g.add(
                El(
                    "g",
                    {
                        "class": "glyph" + (" spins" if ic.spins else ""),
                        "fill": "none",
                        "stroke": "#fff",
                        "stroke-width": 3.2,
                        "stroke-linecap": "round",
                        "stroke-linejoin": "round",
                    },
                    [Raw(ic.glyph)],
                )
            )
            return g
        self.symbols[ic.symbol] = ic
        u = El(
            "use",
            {
                "href": f"#{ic.symbol}",
                "x": num(x - size / 2),
                "y": num(y - size / 2),
                "width": num(size),
                "height": num(size),
            },
        )
        if faded:
            u.attrs["opacity"] = ".55"
        return u

    def defs(self) -> El:
        defs = El("defs")
        for tone in sorted(self.tiles_used):
            g = El("linearGradient", {"id": f"tile-{tone}", "x1": 0, "y1": 0, "x2": 1, "y2": 1})
            g.add(
                El("stop", {"offset": 0}, paint={"stop-color": f"tile-{tone}-0"}),
                El("stop", {"offset": 1}, paint={"stop-color": f"tile-{tone}-1"}),
            )
            defs.add(g)
        for sid, ic in sorted(self.symbols.items()):
            inner = El(
                "g",
                {k: v for k, v in ic.attrs.items() if not (ic.recolour and k == "fill")},
                [Raw(ic.body)],
                paint={"fill": ic.recolour} if ic.recolour else {},
            )
            defs.add(El("symbol", {"id": sid, "viewBox": ic.view_box}, [inner]))
        return defs

    def heading(self, g: Group, tb: Rect) -> list[El | Raw | str]:
        """A `title_at: middle` title: a heading, with the sub text on the line below."""
        t, hs = self.t, heading_size(self.t)
        x, out = tb.x, []
        if g.icon:
            gs = t.size("group_icon")
            out += self.icon(g.icon, x + gs / 2, tb.y + hs / 2, gs)
            x += gs + 8
        out.append(
            El(
                "text",
                {"class": "gtitle", "x": num(x), "y": num(tb.y + hs), "font-size": num(hs), "font-weight": 700},
                [escape(g.title)],
                paint={"fill": "text"},
            )
        )
        if g.sub:
            out.append(
                El(
                    "text",
                    {
                        "class": "gsub",
                        "x": num(x),
                        "y": num(tb.y + hs + t.size("line") + 2),
                        "font-size": num(t.size("group_sub")),
                    },
                    [escape(g.sub)],
                    paint={"fill": "muted"},
                )
            )
        return out

    def edge_badge(self, text: str, x: float, y: float) -> El:
        """A dynamic view's step numbers on an edge, centred on (x, y) and styled like a node's step badge, for the
        view's scenario (its first)."""
        r, w = self.t.size("badge"), badge_width(text, self.t)
        first = next(iter(self.scenarios), "")
        return El(
            "g",
            {"data-badges": first},
            [
                El(
                    "rect",
                    {
                        "class": "badge",
                        "x": num(x - w / 2),
                        "y": num(y - r),
                        "width": num(w),
                        "height": num(2 * r),
                        "rx": num(r),
                    },
                    paint={"fill": "badge"},
                ),
                El(
                    "text",
                    {
                        "class": "badget",
                        "x": num(x),
                        "y": num(y + 3.8),
                        "font-size": 11,
                        "font-weight": 600,
                        "text-anchor": "middle",
                    },
                    [text],
                    paint={"fill": "on-badge"},
                ),
            ],
        )

    def badge_numbers(self) -> dict[str, dict[str, list[int]]]:
        """node -> scenario -> the step numbers its badge shows."""
        out: dict[str, dict[str, list[int]]] = {}
        if self.d.step_list:
            for sid, comp in self.scenarios.items():
                for i, s in enumerate(comp.steps, 1):
                    if s.at:
                        out.setdefault(s.at, {}).setdefault(sid, []).append(i)
        return out

    def build(self) -> tuple[El, Rect]:
        lay = self.lay
        body = El("g", {"class": "dg-body"})
        for gid, r in lay.groups.items():
            if self.d.groups[gid].box:
                body.add(self.group(gid, r))
        labels = El("g", {"class": "labels"})
        for eid, p in lay.edges.items():
            body.add(self.edge(eid, p))
            lab = self.edge_label(eid, p)
            if lab.children:
                labels.add(lab)
        body.add(labels)
        badges = self.badge_numbers()
        for k, nb in lay.nodes.items():
            body.add(self.node(k, nb, badges.get(k, {})))
        return body, lay.bounds

    def group(self, gid: str, r: Rect) -> El:
        g, t = self.d.groups[gid], self.t
        el = El("g", {"class": "grp", "data-id": gid, "id": f"g-{safe_id(gid)}"})
        el.add(*self._behind(g))
        el.add(
            El(
                "rect",
                {
                    "x": num(r.x),
                    "y": num(r.y),
                    "width": num(r.w),
                    "height": num(r.h),
                    "rx": num(t.size("group_radius")),
                    "stroke-width": num(t.size("edge")),
                },
                paint={"fill": f"tone-{g.tone}-fill", "stroke": f"tone-{g.tone}-stroke"},
            )
        )
        own = [nb.box for nb in self.lay.nodes.values() if nb.node.group == gid]
        tb = group_title_box(g, r, t, own)
        if title_place(g) == "middle":
            return el.add(*self.heading(g, tb))
        return el.add(*self.title(g, tb))

    def _behind(self, g: Group) -> list[El]:
        """Boxes stacked behind, deepest first, each with its title in the strip the box in front leaves showing."""
        t, out = self.t, []
        for lid, lr in reversed(self.lay.layers.get(g.id, [])):
            out.append(
                El(
                    "rect",
                    {
                        "x": num(lr.x),
                        "y": num(lr.y),
                        "width": num(lr.w),
                        "height": num(lr.h),
                        "rx": num(t.size("group_radius")),
                        "stroke-width": num(t.size("edge")),
                        "data-layer": lid,
                    },
                    paint={"fill": f"tone-{g.tone}-fill", "stroke": f"tone-{g.tone}-stroke"},
                )
            )
            tb = behind_title_box(g, g.behind[lid], lr, t)
            out.append(
                El(
                    "text",
                    {
                        "class": "gtitle",
                        "x": num(tb.x),
                        "y": num(tb.y1 - 4),
                        "font-size": num(t.size("group_title")),
                        "font-weight": 600,
                    },
                    [escape(g.behind[lid])],
                    paint={"fill": "text"},
                )
            )
        return out

    def title(self, g: Group, tb: Rect) -> list[El]:
        """A group's title in its corner or along its top or bottom edge: icon, title, then the sub text after it."""
        t, out = self.t, []
        hx, hy = tb.x, tb.y + max(t.size("group_title"), t.size("group_icon") if g.icon else 0)
        tx = hx
        if g.icon:
            gs = t.size("group_icon")
            out += self.icon(g.icon, hx + gs / 2, hy - 16 + gs / 2, gs)
            tx = hx + gs + 8
        title = El(
            "text",
            {
                "class": "gtitle",
                "x": num(tx),
                "y": num(hy),
                "font-size": num(t.size("group_title")),
                "font-weight": 600,
            },
            [escape(g.title)],
            paint={"fill": "text"},
        )
        if g.sub:
            title.add(
                El(
                    "tspan",
                    {"class": "gsub", "dx": 8, "font-size": num(t.size("group_sub")), "font-weight": 400},
                    [escape(g.sub)],
                    paint={"fill": "muted"},
                )
            )
        out.append(title)
        return out

    def edge(self, eid: str, p: EdgePath) -> El:
        d, t, e = self.d, self.t, p.edge
        dash = {"stroke-dasharray": "5 4"} if e.dashed else {}
        stroke = {"new": "new", "changed": "changed", "removed": "fail"}.get(e.mark or "", "line")
        path = rounded(p.points, t.size("corner"))
        el = El(
            "g",
            {
                "class": "edge",
                "id": f"e-{safe_id(eid)}",
                "data-id": eid,
                "data-from": e.src.node,
                "data-to": e.dst.node,
            },
        )
        if e.mark:
            el.attrs["data-mark"] = e.mark
            if e.mark == "removed":
                el.attrs["opacity"] = ".45"
        if e.hidden:
            el.attrs["data-hidden"] = "1"
        el.add(
            El(
                "path",
                {"class": "base", "d": path, "fill": "none", "stroke-width": num(t.size("edge")), **dash},
                paint={"stroke": stroke},
            )
        )
        into_junction = e.dst.node in d.nodes and d.nodes[e.dst.node].junction
        if not into_junction and p.tip:
            el.add(El("path", {"class": "head", "d": arrow(p.points)}, paint={"fill": stroke}))
        el.add(
            El(
                "path",
                {"class": "flow", "d": path, "fill": "none", "pathLength": 1, "stroke-width": num(t.size("flow"))},
                paint={"stroke": "accent"},
                only="html",
            )
        )
        if not into_junction and p.tip:
            el.add(El("path", {"class": "head-ok", "d": arrow(p.points)}, paint={"fill": "accent"}, only="html"))
        if e.tooltip:
            el.add(El("title", {}, [escape(e.tooltip)]))
        return el

    def edge_label(self, eid: str, p: EdgePath) -> El:
        """An edge's label and step numbers, drawn after every edge so no edge runs over them."""
        e = p.edge
        lab = El("g", {"class": "elab", "data-edge": eid})
        if e.hidden:
            lab.attrs["data-hidden"] = "1"
        if e.label and p.label_at and p.label_box:
            x, y = p.label_at
            lb = p.label_box
            lab.add(
                El(
                    "rect",
                    {"x": num(lb.x), "y": num(lb.y), "width": num(lb.w), "height": num(lb.h), "rx": 4},
                    paint={"fill": self.fill_at(x, y)},
                )
            )
            lab.add(
                El(
                    "text",
                    {
                        "class": "elabel",
                        "x": num(x),
                        "y": num(y + 4),
                        "font-size": num(self.t.size("label")),
                        "text-anchor": "middle",
                        "data-key": f"t:{eid}:label",
                        "data-default": e.label,
                    },
                    [escape(e.label)],
                    paint={"fill": "muted"},
                )
            )
        if p.badge_at and eid in self.d.numbers:
            # In the label's group, so the player dims and highlights it along with the edge.
            lab.add(self.edge_badge(self.d.numbers[eid], *p.badge_at))
        return lab

    def node(self, k: str, nb: NodeBox, badges: dict[str, list[int]]) -> El:
        t, n = self.t, nb.node
        x, y = nb.x, nb.y
        el = El("g", {"class": "node" + (" junction" if n.junction else ""), "id": f"n-{safe_id(k)}", "data-id": k})
        if n.mark:
            el.attrs["data-mark"] = n.mark
            if n.mark == "removed":
                el.attrs["opacity"] = ".45"
        if n.hidden:
            el.attrs["data-hidden"] = "1"
        if n.tooltip:
            el.add(El("title", {}, [escape(n.tooltip)]))
        if n.junction:
            el.add(El("circle", {"class": "dot", "cx": num(x), "cy": num(y), "r": 3}, paint={"fill": "line"}))
            return el
        half = t.size("icon") / 2
        el.add(
            El(
                "rect",
                {
                    "class": "ring",
                    "x": num(x - half - 8),
                    "y": num(y - half - 8),
                    "width": num(2 * half + 16),
                    "height": num(2 * half + 16),
                    "rx": 14,
                    "fill": "none",
                    "stroke-width": 2.5,
                },
                paint={"stroke": "accent"},
                only="html",
            )
        )
        el.add(*self.icon(n.icon, x, y, t.size("icon"), n.tone, n.stack))
        el.add(*self._node_text(k, nb))
        if nb.strip:
            el.add(*self._strip(k, nb, nb.strip))
        if nb.button:
            el.add(self.button(k, nb.button, n.trigger or ""))
        el.add(*self._badges(nb, badges))
        el.add(*self._status(nb))
        return el

    def _node_text(self, k: str, nb: NodeBox) -> list[El]:
        """The title, its NEW / REMOVED / CHANGED mark, and the sub lines under it."""
        t, n, x = self.t, nb.node, nb.x
        out = [
            El(
                "text",
                {
                    "class": "ntitle",
                    "x": num(x),
                    "y": num(nb.title_y),
                    "font-size": num(t.size("title")),
                    "font-weight": 600,
                    "text-anchor": "middle",
                    "data-key": f"t:{k}:title",
                    "data-default": n.title,
                },
                [escape(n.title)],
                paint={"fill": "text"},
            )
        ]
        if n.mark:
            mx = x + text_width(n.title, t.size("title"), 600) / 2 + 6
            out.append(
                El(
                    "text",
                    {
                        "class": "mark",
                        "x": num(mx),
                        "y": num(nb.title_y - 1),
                        "font-size": 9,
                        "font-weight": 700,
                        "letter-spacing": ".04em",
                    },
                    [MARK_TEXT[n.mark]],
                    paint={"fill": {"removed": "fail"}.get(n.mark, n.mark)},
                )
            )
        for j, sy in enumerate(nb.sub_ys):
            line = n.sub[j] if j < len(n.sub) else ""
            out.append(
                El(
                    "text",
                    {
                        "class": "nsub",
                        "x": num(x),
                        "y": num(sy),
                        "font-size": num(t.size("sub")),
                        "text-anchor": "middle",
                        "data-key": f"t:{k}:sub:{j}",
                        "data-default": line,
                    },
                    [escape(line)],
                    paint={"fill": "muted"},
                )
            )
        return out

    def _strip(self, k: str, nb: NodeBox, s: Rect) -> list[El]:
        """The node's row of cells, and the caption under it that a scenario fills."""
        n = nb.node
        strip = El("g", {"class": "cells"})
        strip.add(
            El(
                "rect",
                {
                    "class": "cellbox",
                    "x": num(s.x),
                    "y": num(s.y),
                    "width": num(s.w),
                    "height": num(s.h),
                    "rx": 9,
                    "stroke-width": 1.2,
                },
                paint={"fill": "bg", "stroke": self._cell_stroke(k)},
            )
        )
        for i in range(len(n.cells)):
            strip.add(
                El(
                    "rect",
                    {
                        "class": "cell",
                        "data-key": f"c:{k}:{i}",
                        "x": num(s.x + 8 + i * 23),
                        "y": num(s.y + 7),
                        "width": 18,
                        "height": 18,
                        "rx": 4,
                        "fill": "none",
                        "stroke-width": 1.2,
                        "stroke-opacity": ".55",
                    },
                    paint={"stroke": "muted"},
                )
            )
        out = [strip]
        if nb.caption_y is not None:
            out.append(
                El(
                    "text",
                    {
                        "class": "cap nsub",
                        "x": num(nb.x),
                        "y": num(nb.caption_y),
                        "font-size": num(self.t.size("sub")),
                        "text-anchor": "middle",
                        "data-key": f"cap:{k}",
                        "data-default": "",
                    },
                    [],
                    paint={"fill": "muted"},
                )
            )
        return out

    def _badges(self, nb: NodeBox, badges: dict[str, list[int]]) -> list[El]:
        """The step numbers by the node's top-left corner, one set per scenario."""
        t, x, y = self.t, nb.x, nb.y
        half, r = t.size("icon") / 2, t.size("badge")
        first = next(iter(self.scenarios), None)
        out = []
        for sid, numbers in badges.items():
            label = ",".join(str(i) for i in numbers)
            w = max(2 * r, text_width(label, 11, 600) + 10)
            bx = x - half - 8
            parts: list[El | Raw | str] = [
                El(
                    "rect",
                    {
                        "class": "badge",
                        "x": num(bx - w / 2),
                        "y": num(y - half - 4 - r),
                        "width": num(w),
                        "height": num(2 * r),
                        "rx": num(r),
                    },
                    paint={"fill": "badge"},
                ),
                El(
                    "text",
                    {
                        "class": "badget",
                        "x": num(bx),
                        "y": num(y - half - 4 + 3.8),
                        "font-size": 11,
                        "font-weight": 600,
                        "text-anchor": "middle",
                    },
                    [label],
                    paint={"fill": "on-badge"},
                ),
            ]
            # The player shows one scenario's badges at a time; static output has only the first's.
            out.append(El("g", {"data-badges": sid}, parts, only=None if sid == first else "html"))
        return out

    def _status(self, nb: NodeBox) -> list[El]:
        """The spinner, tick and cross by the node's top-right corner, which the player shows as it runs."""
        t = self.t
        half, r = t.size("icon") / 2, t.size("badge")
        cx, cy = nb.x + half + 8, nb.y - half - 4
        spin = El("g", {"class": "st st-spin"}, only="html")
        spin.add(El("circle", {"cx": num(cx), "cy": num(cy), "r": num(r)}, paint={"fill": "accent"}))
        spin.add(
            El(
                "g",
                {"class": "rot"},
                [
                    El(
                        "g",
                        {
                            "transform": f"translate({num(cx)} {num(cy)}) scale(0.27) translate(-32 -32)",
                            "fill": "none",
                            "stroke": "#fff",
                            "stroke-width": 7,
                            "stroke-linecap": "round",
                            "stroke-linejoin": "round",
                        },
                        [Raw(SPIN_GLYPH)],
                    )
                ],
            )
        )
        done = El(
            "g",
            {"class": "st st-done"},
            [
                El("circle", {"cx": num(cx), "cy": num(cy), "r": num(r)}, paint={"fill": "accent"}),
                El(
                    "path",
                    {
                        "d": f"M{num(cx - 4.5)} {num(cy)}l3.2 3.2 6-6.4",
                        "fill": "none",
                        "stroke": "#fff",
                        "stroke-width": 2,
                        "stroke-linecap": "round",
                        "stroke-linejoin": "round",
                    },
                ),
            ],
            only="html",
        )
        fail = El(
            "g",
            {"class": "st st-fail"},
            [
                El("circle", {"cx": num(cx), "cy": num(cy), "r": num(r)}, paint={"fill": "fail"}),
                El(
                    "path",
                    {
                        "d": f"M{num(cx - 3.5)} {num(cy - 3.5)}l7 7M{num(cx + 3.5)} {num(cy - 3.5)}l-7 7",
                        "fill": "none",
                        "stroke": "#fff",
                        "stroke-width": 2,
                        "stroke-linecap": "round",
                    },
                ),
            ],
            only="html",
        )
        return [spin, done, fail]

    def _cell_stroke(self, k: str) -> str:
        gid = self.d.nodes[k].group
        return f"tone-{self.d.groups[gid].tone}-stroke" if gid in self.d.groups else "line"

    def button(self, k: str, r: Rect, label: str) -> El:
        cx, cy = r.x + r.w / 2, r.y + r.h / 2
        g = El(
            "g",
            {
                "class": "trigger",
                "data-node": k,
                "role": "button",
                "tabindex": 0,
                "aria-label": f"{label}: play the scenario",
            },
        )
        plays = self.d.nodes[k].plays or next(iter(self.scenarios), None)
        if plays in self.scenarios:
            g.attrs["data-plays"] = plays
            if self.scenarios[plays].title:
                g.attrs["aria-label"] = f"{label}: play {self.scenarios[plays].title}"
        g.add(
            El(
                "rect",
                {"class": "btnbg", "x": num(r.x), "y": num(r.y), "width": num(r.w), "height": num(r.h), "rx": 10},
                paint={"fill": "button"},
            )
        )
        tw = text_width(label, 14, 600)
        ix = cx - (tw + 18) / 2
        g.add(
            El("path", {"class": "btnicon", "d": f"M{num(ix)} {num(cy - 7)}l11 7-11 7z"}, paint={"fill": "on-button"})
        )
        busy = El("g", {"class": "btnbusy"}, only="html")
        busy.add(
            El(
                "g",
                {"class": "rot"},
                [
                    El(
                        "g",
                        {
                            "transform": f"translate({num(ix + 6)} {num(cy)}) scale(0.3) translate(-32 -32)",
                            "fill": "none",
                            "stroke-width": 7,
                            "stroke-linecap": "round",
                            "stroke-linejoin": "round",
                        },
                        [Raw(SPIN_GLYPH)],
                        paint={"stroke": "on-button"},
                    )
                ],
            )
        )
        g.add(busy)
        g.add(
            El(
                "text",
                {
                    "class": "btntext",
                    "x": num(ix + 18 + tw / 2),
                    "y": num(cy + 4.5),
                    "font-size": 14,
                    "font-weight": 600,
                    "text-anchor": "middle",
                    "data-default": label,
                },
                [escape(label)],
                paint={"fill": "on-button"},
            )
        )
        return g


def arrow(points: list[tuple[float, float]], length: float = 10.5, width: float = 10.5) -> str:
    (x0, y0), (x1, y1) = points[-2], points[-1]
    ang = math.atan2(y1 - y0, x1 - x0)
    tipx, tipy = x1 + math.cos(ang) * 1, y1 + math.sin(ang) * 1
    bx, by = tipx - math.cos(ang) * length, tipy - math.sin(ang) * length
    px, py = -math.sin(ang) * width / 2, math.cos(ang) * width / 2
    return f"M{num(tipx)} {num(tipy)}L{num(bx + px)} {num(by + py)}L{num(bx - px)} {num(by - py)}z"


def serialise(el: El | Raw | str, mode: str, paint: Callable[[str, str], str]) -> str:
    """mode 'static' bakes colours into attributes; 'html' turns paint(prop, token) into a class."""
    if isinstance(el, str):
        return el
    if isinstance(el, Raw):
        return el.markup
    if el.only and el.only != mode:
        return ""
    if mode == "static" and el.attrs.get("data-hidden"):
        return ""
    attrs = dict(el.attrs)
    if mode == "static":
        attrs = {k: v for k, v in attrs.items() if k not in ("data-key", "data-default")}
    for prop, token in el.paint.items():
        value = paint(prop, token)
        if mode == "static":
            attrs[prop] = value
        else:
            attrs["class"] = f"{attrs['class']} {value}" if "class" in attrs else value
    parts = [el.tag] + [f'{k}="{escape(str(v), quote=True)}"' for k, v in attrs.items()]
    inner = "".join(serialise(c, mode, paint) for c in el.children)
    if not inner and el.tag not in ("text", "g", "title", "tspan", "symbol", "defs"):
        return f"<{' '.join(parts)}/>"
    return f"<{' '.join(parts)}>{inner}</{el.tag}>"
