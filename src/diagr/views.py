"""Views: parts of one diagram, each built as its own images and page (`<id>-<view>`)."""

from __future__ import annotations

import copy

from .layout.auto import place
from .model import Diagram
from .source import Problem, did_you_mean


def check_views(d: Diagram) -> list[Problem]:
    problems = []
    ids = set(d.groups) | set(d.nodes)
    for vid, v in d.views.items():
        for x in (v.include or []) + v.exclude:
            if x not in ids:
                problems.append(Problem(v.loc, f"view '{vid}': unknown group or node '{x}'{did_you_mean(x, ids)}"))
        for s in v.scenarios:
            if s not in d.scenarios:
                problems.append(Problem(v.loc, f"view '{vid}': unknown scenario '{s}'{did_you_mean(s, d.scenarios)}"))
        if not problems and not _chosen(d, vid):
            problems.append(Problem(v.loc, f"view '{vid}' leaves no nodes"))
    return problems


def _inside(d: Diagram, node: str, gid: str) -> bool:
    g, seen = d.nodes[node].group, set()
    while g in d.groups and g not in seen:
        if g == gid:
            return True
        seen.add(g)
        g = d.groups[g].parent
    return False


def _select(d: Diagram, ids: list[str]) -> set[str]:
    return {k for k in d.nodes if k in ids or any(g in d.groups and _inside(d, k, g) for g in ids)}


def _chosen(d: Diagram, vid: str) -> set[str]:
    v = d.views[vid]
    keep = set(d.nodes) if v.include is None else _select(d, v.include)
    return keep - _select(d, v.exclude)


def view(d: Diagram, vid: str) -> Diagram:
    """The diagram cut down to one view. Nodes that were placed automatically are placed again, so the view closes
    up; pinned nodes keep their cells. Scenarios are dropped unless the view lists them, and so are triggers that
    would play a dropped one."""
    v = d.views[vid]
    keep = _chosen(d, vid)
    out = copy.deepcopy(d)
    out.id, out.title, out.views = f"{d.id}-{vid}", v.title or d.title, {}
    out.nodes = {k: n for k, n in out.nodes.items() if k in keep}
    groups: set[str] = set()
    for n in out.nodes.values():
        g = n.group
        while g in d.groups and g not in groups:
            groups.add(g)
            g = d.groups[g].parent
    out.groups = {k: g for k, g in out.groups.items() if k in groups}
    out.edges = {k: e for k, e in out.edges.items() if e.src.node in keep and e.dst.node in keep}
    out.scenarios = {k: s for k, s in out.scenarios.items() if k in v.scenarios}
    first = next(iter(d.scenarios), None)
    for n in out.nodes.values():
        if n.auto:
            n.at, n.auto = None, False
        if n.trigger:
            plays = n.plays or first
            if plays in out.scenarios:
                n.plays = plays
            else:
                n.trigger, n.plays = None, None
    place(out)
    return out
