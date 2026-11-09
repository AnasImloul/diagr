from __future__ import annotations

from .icons import Icons, SvgIcon, Tile
from .layout.geometry import Layout, Rect
from .model import Diagram, Effect, Loc
from .scenario import resolve_edge, text_key, walk_effects
from .source import Problem
from .theme import Theme


def _warn(problems: list[Problem], loc: Loc | None, msg: str) -> None:
    problems.append(Problem(loc, msg, "warning"))


def _icon(p: list[Problem], loc: Loc | None, who: str, name: str, tone: str | None, t: Theme, icons: Icons) -> None:
    ic = icons.get(name)
    if ic is None:
        why = icons.errors.get(name)
        p.append(Problem(loc, f"{who}: icon '{name}' " + (f"cannot be read ({why})" if why else "not found")))
    elif isinstance(ic, Tile) and not tone and ic.tone not in t.tiles:
        p.append(
            Problem(
                loc,
                f"{who}: icon '{name}' uses tile tone '{ic.tone}', which the theme does not have "
                f"(theme has {', '.join(t.tiles)})",
            )
        )
    elif isinstance(ic, SvgIcon) and ic.recolour and ic.recolour not in t.tokens["light"]:
        p.append(Problem(loc, f"{who}: icon '{name}' is recoloured with unknown theme token '{ic.recolour}'"))


def check_model(d: Diagram, t: Theme, icons: Icons) -> list[Problem]:
    p: list[Problem] = list(icons.problems)
    for folder in icons.missing:
        p.append(Problem(Loc(d.file, 1, 1), f"icon folder not found: {folder}"))
    for k in d.groups:
        if k in d.nodes:
            p.append(Problem(d.nodes[k].loc, f"'{k}' is both a group and a node; ids must be unique"))
    for g in d.groups.values():
        if g.tone not in t.tones:
            p.append(Problem(g.loc, f"group '{g.id}': unknown tone '{g.tone}' (theme has {', '.join(t.tones)})"))
        if g.icon:
            _icon(p, g.loc, f"group '{g.id}'", g.icon, None, t, icons)
        if g.span and g.at is None:
            p.append(Problem(g.loc, f"group '{g.id}': 'span' needs 'at'"))
        if g.parent and g.parent not in d.groups:
            p.append(Problem(g.loc, f"group '{g.id}': unknown parent group '{g.parent}'"))
        elif g.parent and _in_loop(d, g.id):
            p.append(Problem(g.loc, f"group '{g.id}' is inside itself through 'in'"))
    seen: dict[tuple[float, float], str] = {}
    for n in d.nodes.values():
        if n.group and n.group not in d.groups:
            p.append(Problem(n.loc, f"node '{n.id}': unknown group '{n.group}'"))
        if n.icon:
            _icon(p, n.loc, f"node '{n.id}'", n.icon, n.tone, t, icons)
        if not n.junction and not n.icon:
            _warn(p, n.loc, f"node '{n.id}' has no icon")
        if n.tone and n.tone not in t.tiles:
            p.append(Problem(n.loc, f"node '{n.id}': unknown tile tone '{n.tone}' (theme has {', '.join(t.tiles)})"))
        if n.at in seen:
            p.append(Problem(n.loc, f"node '{n.id}' sits on the same cell as '{seen[n.at]}'"))
        seen[n.at] = n.id
    for e in d.edges.values():
        for end in (e.src, e.dst):
            if end.node not in d.nodes:
                p.append(Problem(e.loc, f"edge '{e.id}': unknown node '{end.node}'"))
        if e.id in d.nodes or e.id in d.groups:
            p.append(Problem(e.loc, f"edge id '{e.id}' is also a node or group id"))
        if e.route is not None and e.via is not None:
            p.append(Problem(e.loc, f"edge '{e.id}': use either 'route' or 'via', not both"))
        if e.src.node == e.dst.node and e.route is None and e.via is None:
            p.append(Problem(e.loc, f"edge '{e.id}' starts and ends at '{e.src.node}'; give it a 'route' or 'via'"))
        if not e.hidden:
            for end in (e.src.node, e.dst.node):
                if end in d.nodes and d.nodes[end].hidden:
                    _warn(
                        p, e.loc, f"edge '{e.id}' is visible but node '{end}' starts hidden; mark the edge hidden too"
                    )
    if d.scenario:
        p += check_scenario(d)
    _check_hidden(d, p)
    return p


def _in_loop(d: Diagram, gid: str) -> bool:
    seen, parent = {gid}, d.groups[gid].parent
    while parent in d.groups:
        if parent in seen:
            return True
        seen.add(parent)
        parent = d.groups[parent].parent
    return False


def _check_hidden(d: Diagram, p: list[Problem]) -> None:
    effects = walk_effects(d.scenario) if d.scenario else []
    shown = {resolve_edge(d, x) or x for e in effects if e.verb == "show" for x in e.targets}
    for n in d.nodes.values():
        if n.hidden and n.id not in shown:
            _warn(p, n.loc, f"node '{n.id}' is hidden and nothing shows it")
    for e in d.edges.values():
        if e.hidden and e.id not in shown:
            _warn(p, e.loc, f"edge '{e.id}' is hidden and nothing shows it")


def _check_effect(d: Diagram, e: Effect, p: list[Problem]) -> None:
    v = e.verb
    if v in ("activate", "done", "fail", "spin", "cells"):
        for x in e.targets:
            if v == "spin" and x == "off":
                continue
            if x not in d.nodes:
                p.append(Problem(e.loc, f"'{v}': unknown node '{x}'"))
            elif v == "cells" and not d.nodes[x].cells:
                p.append(Problem(e.loc, f"'cells': node '{x}' has no cells"))
            elif v == "cells" and e.range and not (1 <= e.range[0] <= e.range[1] <= len(d.nodes[x].cells)):
                lo, hi = e.range
                p.append(Problem(e.loc, f"'cells': range {lo}..{hi} is outside 1..{len(d.nodes[x].cells)}"))
        if v == "cells" and len(e.targets) != 1:
            p.append(Problem(e.loc, "'cells' takes one node"))
    elif v == "draw":
        for x in e.targets:
            if resolve_edge(d, x) is None:
                a, _, b = x.partition("->")
                pairs = [k for k, ed in d.edges.items() if ed.src.node == a and ed.dst.node == b]
                hint = f" (several edges match; use one of: {', '.join(pairs)})" if len(pairs) > 1 else ""
                p.append(Problem(e.loc, f"'draw': unknown edge '{x}'{hint}"))
    elif v == "set":
        if text_key(d, e.targets[0], {}) is None:
            p.append(
                Problem(
                    e.loc, f"'set': cannot set '{e.targets[0]}' (use node.title, node.sub, node.sub.N or a->b.label)"
                )
            )
    elif v in ("show", "hide", "focus"):
        for x in e.targets:
            if v == "focus" and x == "none":
                continue
            if x not in d.nodes and x not in d.groups and resolve_edge(d, x) is None:
                p.append(Problem(e.loc, f"'{v}': unknown node, edge or group '{x}'"))
    elif v == "parallel":
        for c in e.children:
            if c.verb in ("cells", "repeat", "parallel"):
                p.append(Problem(c.loc, f"'{c.verb}' cannot run inside 'parallel'"))
    for c in e.children:
        _check_effect(d, c, p)


def check_scenario(d: Diagram) -> list[Problem]:
    p: list[Problem] = []
    sc = d.scenario
    assert sc
    for s in sc.steps:
        if s.at and s.at not in d.nodes:
            p.append(Problem(s.loc, f"step '{s.title}': unknown node '{s.at}'"))
        for e in s.effects:
            _check_effect(d, e, p)
    return p


def check_layout(d: Diagram, lay: Layout) -> list[Problem]:
    p: list[Problem] = []
    for k, path in lay.edges.items():
        for msg in path.problems:
            p.append(Problem(d.edges[k].loc, f"edge '{k}': {msg}"))
    boxes = [(k, b.box) for k, b in lay.nodes.items() if not b.node.junction]
    for i, (a, ra) in enumerate(boxes):
        for b, rb in boxes[i + 1 :]:
            if ra.overlaps(rb):
                _warn(p, d.nodes[b].loc, f"node '{b}' overlaps node '{a}'")
    for k, b in lay.nodes.items():
        g = b.node.group
        if g in lay.groups and not lay.groups[g].contains((b.x, b.y)):
            p.append(Problem(d.nodes[k].loc, f"node '{k}' is outside its group '{g}'"))
    for k, r in lay.groups.items():
        parent = d.groups[k].parent
        if parent in lay.groups and not _inside(r, lay.groups[parent]):
            p.append(Problem(d.groups[k].loc, f"group '{k}' is outside its parent group '{parent}'"))
    labels = [(k, e.label_box) for k, e in lay.edges.items() if e.label_box]
    for k, box in labels:
        for n, b in lay.nodes.items():
            if n in (d.edges[k].src.node, d.edges[k].dst.node) or b.node.junction:
                continue
            if box.overlaps(b.box):
                _warn(p, d.edges[k].loc, f"label of edge '{k}' overlaps node '{n}'")
    gl = list(lay.groups.items())
    for i, (a, ra) in enumerate(gl):
        for b, rb in gl[i + 1 :]:
            if ra.overlaps(rb) and not (_inside(rb, ra) or _inside(ra, rb)):
                _warn(p, d.groups[b].loc, f"group '{b}' overlaps group '{a}'")
    return p


def _inside(inner: Rect, outer: Rect) -> bool:
    return outer.contains((inner.x, inner.y)) and outer.contains((inner.x1, inner.y1))
