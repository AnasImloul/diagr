from __future__ import annotations

from .icons import Icons, SvgIcon, Tile
from .layout.flow import laid_out
from .layout.geometry import Layout, Point, Rect, behind_title_box, group_title_box
from .model import Diagram, Effect, Loc, Scenario
from .scenario import resolve_edge, text_key, walk_effects
from .source import Problem, did_you_mean
from .theme import Theme


def _warn(problems: list[Problem], loc: Loc | None, msg: str) -> None:
    problems.append(Problem(loc, msg, "warning"))


def _icon(p: list[Problem], loc: Loc | None, who: str, name: str, tone: str | None, t: Theme, icons: Icons) -> None:
    ic = icons.get(name)
    if ic is None:
        why = icons.errors.get(name)
        if why:
            p.append(Problem(loc, f"{who}: icon '{name}' cannot be read ({why})"))
        else:
            names = [n for n, _, _ in icons.available()]
            p.append(Problem(loc, f"{who}: icon '{name}' not found{did_you_mean(name, names)}"))
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
    flowed, flowed_groups = laid_out(d)
    for k in flowed:
        if d.nodes[k].at is not None:
            p.append(Problem(d.nodes[k].loc, f"node '{k}' has 'at', but its box's 'layout' places it; remove 'at'"))
    for k in flowed_groups:
        g = d.groups[k]
        root = d.flow is None and (g.parent not in flowed_groups)
        if g.span is not None or (g.at is not None and not root):
            p.append(Problem(g.loc, f"group '{k}' has 'at' or 'span', but a 'layout' places it; remove them"))
    for n in d.nodes.values():
        for key in ("align_x", "align_y"):
            target = getattr(n, key)
            if target is None:
                continue
            if target == n.id:
                p.append(Problem(n.loc, f"node '{n.id}': '{key}' names the node itself"))
            elif target not in d.nodes:
                p.append(
                    Problem(
                        n.loc, f"node '{n.id}': '{key}' names unknown node '{target}'{did_you_mean(target, d.nodes)}"
                    )
                )
            elif _aligns_back(d, target, n.id, key):
                p.append(Problem(n.loc, f"node '{n.id}': '{key}' goes round in a loop back to it"))
    stacked: set[str] = set()
    for g in d.groups.values():
        for lid in g.behind:
            if lid in d.nodes or lid in d.groups or lid in stacked:
                p.append(Problem(g.loc, f"group '{g.id}': box behind it '{lid}' reuses an id; ids must be unique"))
            stacked.add(lid)
    for g in d.groups.values():
        if g.tone not in t.tones:
            p.append(Problem(g.loc, f"group '{g.id}': unknown tone '{g.tone}' (theme has {', '.join(t.tones)})"))
        if g.icon:
            _icon(p, g.loc, f"group '{g.id}'", g.icon, None, t, icons)
        if g.span and g.at is None:
            p.append(Problem(g.loc, f"group '{g.id}': 'span' needs 'at'"))
        if g.parent and g.parent not in d.groups:
            p.append(
                Problem(g.loc, f"group '{g.id}': unknown parent group '{g.parent}'{did_you_mean(g.parent, d.groups)}")
            )
        elif g.parent and _in_loop(d, g.id):
            p.append(Problem(g.loc, f"group '{g.id}' is inside itself through 'in'"))
    seen: dict[tuple[float, float], str] = {}
    for n in d.nodes.values():
        if n.group and n.group not in d.groups:
            p.append(Problem(n.loc, f"node '{n.id}': unknown group '{n.group}'{did_you_mean(n.group, d.groups)}"))
        if n.icon:
            _icon(p, n.loc, f"node '{n.id}'", n.icon, n.tone, t, icons)
        if not n.junction and not n.icon:
            _warn(p, n.loc, f"node '{n.id}' has no icon")
        if n.tone and n.tone not in t.tiles:
            p.append(Problem(n.loc, f"node '{n.id}': unknown tile tone '{n.tone}' (theme has {', '.join(t.tiles)})"))
        if n.at is not None and n.at in seen:
            p.append(Problem(n.loc, f"node '{n.id}' sits on the same cell as '{seen[n.at]}'"))
        if n.at is not None:
            seen[n.at] = n.id
    owner = {lid: g.id for g in d.groups.values() for lid in g.behind}
    ends = set(d.nodes) | set(d.groups) | set(owner)
    for e in d.edges.values():
        for end in (e.src, e.dst):
            if end.node not in ends:
                p.append(
                    Problem(e.loc, f"edge '{e.id}': unknown node or group '{end.node}'{did_you_mean(end.node, ends)}")
                )
        for a, b in ((e.src.node, e.dst.node), (e.dst.node, e.src.node)):
            if a in d.nodes and owner.get(b, b) in d.groups and _within(d, d.nodes[a].group, owner.get(b, b)):
                p.append(Problem(e.loc, f"edge '{e.id}' joins '{a}' to the group '{b}' it is in"))
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
    for sc in d.scenarios.values():
        p += check_scenario(d, sc)
    _check_hidden(d, p)
    return p


def _aligns_back(d: Diagram, start: str, back_to: str, key: str) -> bool:
    k, seen = start, set()
    while k in d.nodes and k not in seen:
        if k == back_to:
            return True
        seen.add(k)
        k = getattr(d.nodes[k], key)
    return False


def _within(d: Diagram, gid: str | None, outer: str) -> bool:
    seen: set[str] = set()
    while gid in d.groups and gid not in seen:
        if gid == outer:
            return True
        seen.add(gid)
        gid = d.groups[gid].parent
    return False


def _in_loop(d: Diagram, gid: str) -> bool:
    seen, parent = {gid}, d.groups[gid].parent
    while parent in d.groups:
        if parent in seen:
            return True
        seen.add(parent)
        parent = d.groups[parent].parent
    return False


def _check_hidden(d: Diagram, p: list[Problem]) -> None:
    """Hidden nodes and edges nothing brings out: showing, drawing or activating an element reveals it."""
    shown: set[str] = set()
    for e in (e for sc in d.scenarios.values() for e in walk_effects(sc)):
        if e.verb == "flow":
            shown.update(e.targets)
            refs = [f"{a}->{b}" for a, b in e.links()]
        elif e.verb in ("show", "draw", "activate", "done", "fail", "run"):
            refs = e.targets
        else:
            continue
        for x in refs:
            k = resolve_edge(d, x) or x
            shown.add(k)
            if k in d.edges and e.verb != "show":
                shown.update((d.edges[k].src.node, d.edges[k].dst.node))
    for n in d.nodes.values():
        if n.hidden and n.id not in shown:
            _warn(p, n.loc, f"node '{n.id}' is hidden and nothing shows it")
    for e in d.edges.values():
        if e.hidden and e.id not in shown:
            _warn(p, e.loc, f"edge '{e.id}' is hidden and nothing shows it")


def _check_effect(d: Diagram, e: Effect, p: list[Problem]) -> None:
    v = e.verb
    if v in ("activate", "done", "fail", "run", "spin", "cells"):
        for x in e.targets:
            if v == "spin" and x == "off":
                continue
            if x not in d.nodes:
                p.append(Problem(e.loc, f"'{v}': unknown node '{x}'{did_you_mean(x, d.nodes)}"))
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
                hint = (
                    f" (several edges match; use one of: {', '.join(pairs)})"
                    if len(pairs) > 1
                    else did_you_mean(x, d.edges)
                )
                p.append(Problem(e.loc, f"'draw': unknown edge '{x}'{hint}"))
    elif v == "set":
        target = e.targets[0]
        if text_key(d, target, {}) is None:
            head = target.rpartition(".")[0] if "->" in target else target.partition(".")[0]
            known = head in d.nodes or resolve_edge(d, head) is not None
            hint = "" if known else did_you_mean(head, [*d.nodes, *d.edges])
            p.append(
                Problem(e.loc, f"cannot set '{target}'{hint} (use node.title, node.sub, node.sub.N or a->b.label)")
            )
    elif v == "flow":
        ends = set(d.nodes) | set(d.groups) | {lid for g in d.groups.values() for lid in g.behind}
        for x in e.targets:
            if x not in ends:
                p.append(Problem(e.loc, f"'flow': unknown node or group '{x}'{did_you_mean(x, ends)}"))
        for a, b in e.links():
            if a in ends and b in ends and resolve_edge(d, f"{a}->{b}") is None:
                pairs = [k for k, ed in d.edges.items() if ed.src.node == a and ed.dst.node == b]
                why = f"several edges go from '{a}' to '{b}'; use 'draw' with one of: {', '.join(pairs)}"
                p.append(Problem(e.loc, f"'flow': {why if pairs else f'no edge from {a!r} to {b!r}'}"))
    elif v in ("show", "hide", "focus"):
        for x in e.targets:
            if v == "focus" and x == "none":
                continue
            if x not in d.nodes and x not in d.groups and resolve_edge(d, x) is None:
                hint = did_you_mean(x, [*d.nodes, *d.groups, *d.edges])
                p.append(Problem(e.loc, f"'{v}': unknown node, edge or group '{x}'{hint}"))
    for c in e.children:
        _check_effect(d, c, p)


def check_scenario(d: Diagram, sc: Scenario) -> list[Problem]:
    p: list[Problem] = []
    for s in sc.steps:
        if s.at and s.at not in d.nodes:
            p.append(Problem(s.loc, f"step '{s.title}': unknown node '{s.at}'{did_you_mean(s.at, d.nodes)}"))
        for e in s.effects:
            _check_effect(d, e, p)
    return p


def check_layout(d: Diagram, lay: Layout, t: Theme) -> list[Problem]:
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
    for k, b in lay.nodes.items():
        if b.node.junction:
            continue
        inside = _ancestors(d, b.node.group)
        for g, r in lay.groups.items():
            if g not in inside and d.groups[g].box and r.overlaps(b.box):
                _warn(p, d.nodes[k].loc, f"node '{k}' overlaps group '{g}', which it is not in")
    for k, r in lay.groups.items():
        parent = d.groups[k].parent
        if parent in lay.groups and not _inside(r, lay.groups[parent]):
            p.append(Problem(d.groups[k].loc, f"group '{k}' is outside its parent group '{parent}'"))
    labels = [(k, e.label_box) for k, e in lay.edges.items() if e.label_box]
    labels += [(k, e.badge_box) for k, e in lay.edges.items() if e.badge_box]
    for i, (k, box) in enumerate(labels):
        for k2, box2 in labels[i + 1 :]:
            if box.overlaps(box2) and not (d.edges[k].hidden or d.edges[k2].hidden):
                _warn(p, d.edges[k].loc, f"label of edge '{k}' overlaps the label of '{k2}'")
    for k, box in labels:
        for n, b in lay.nodes.items():
            if n in (d.edges[k].src.node, d.edges[k].dst.node) or b.node.junction:
                continue
            if box.overlaps(b.box):
                _warn(p, d.edges[k].loc, f"label of edge '{k}' overlaps node '{n}'")
    own: dict[str, list[Rect]] = {}
    for nb in lay.nodes.values():
        own.setdefault(nb.node.group or "", []).append(nb.box)
    titles = {k: group_title_box(d.groups[k], r, t, own.get(k, [])) for k, r in lay.groups.items() if d.groups[k].box}
    behind = {
        lid: (k, behind_title_box(d.groups[k], d.groups[k].behind[lid], r, t))
        for k, ls in lay.layers.items()
        for lid, r in ls
    }
    for g, title in titles.items():
        for n, b in lay.nodes.items():
            if not b.node.junction and b.box.overlaps(title):
                _warn(p, d.nodes[n].loc, f"node '{n}' covers the title of group '{g}'")
        for c, r in lay.groups.items():
            if c != g and _within(d, c, g) and r.overlaps(title):
                _warn(p, d.groups[c].loc, f"group '{c}' covers the title of group '{g}'")
    for k, path in lay.edges.items():
        e = d.edges[k]
        segments = list(zip(path.points, path.points[1:], strict=False))
        for n, b in lay.nodes.items():
            if n not in (e.src.node, e.dst.node) and not b.node.junction and _crosses(segments, b.box):
                _warn(p, e.loc, f"edge '{k}' passes through node '{n}'")
        for g, box in titles.items():
            if _crosses(segments, box):
                _warn(p, e.loc, f"edge '{k}' crosses the title of group '{g}'")
        for lid, (g, box) in behind.items():
            if _crosses(segments, box):
                _warn(p, e.loc, f"edge '{k}' crosses the title of '{lid}', stacked behind group '{g}'")
    gl = [(k, r) for k, r in lay.groups.items() if d.groups[k].box]
    for i, (a, ra) in enumerate(gl):
        for b, rb in gl[i + 1 :]:
            if ra.overlaps(rb) and not (_inside(rb, ra) or _inside(ra, rb)):
                _warn(p, d.groups[b].loc, f"group '{b}' overlaps group '{a}'")
    return p


def _crosses(segments: list[tuple[Point, Point]], r: Rect) -> bool:
    for (ax, ay), (bx, by) in segments:
        lo_x, hi_x, lo_y, hi_y = min(ax, bx), max(ax, bx), min(ay, by), max(ay, by)
        if lo_x < r.x1 and hi_x > r.x and lo_y < r.y1 and hi_y > r.y:
            return True
    return False


def _ancestors(d: Diagram, gid: str | None) -> set[str]:
    out: set[str] = set()
    while gid in d.groups and gid not in out:
        out.add(gid)
        gid = d.groups[gid].parent
    return out


def _inside(inner: Rect, outer: Rect) -> bool:
    """Whether inner lies within outer, allowing half a px for rounding where the two share an edge."""
    e = 0.5
    return outer.x - e <= inner.x and inner.x1 <= outer.x1 + e and outer.y - e <= inner.y and inner.y1 <= outer.y1 + e
