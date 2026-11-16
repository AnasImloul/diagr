"""Views: parts of one diagram, each built as its own images and page (`<id>-<view>`)."""

from __future__ import annotations

import copy

from .model import Diagram, Effect, boxes_around, edge_id, stack_owners
from .scenario import resolve_edge
from .source import Problem, did_you_mean


def check_views(d: Diagram) -> list[Problem]:
    problems = []
    ids = set(d.groups) | set(d.nodes)
    for vid, v in d.views.items():
        found = []
        for x in (v.include or []) + v.exclude:
            if x not in ids:
                found.append(Problem(v.loc, f"view '{vid}': unknown group or node '{x}'{did_you_mean(x, ids)}"))
        for s in v.scenarios + ([v.scenario] if v.scenario else []):
            if s not in d.scenarios:
                found.append(Problem(v.loc, f"view '{vid}': unknown scenario '{s}'{did_you_mean(s, d.scenarios)}"))
        # Whether it leaves anything can only be told once its own references are sound.
        if not found and not _chosen(d, vid):
            found.append(Problem(v.loc, f"view '{vid}' leaves no nodes"))
        problems += found
    return problems


def _select(d: Diagram, ids: list[str]) -> set[str]:
    return {k for k in d.nodes if k in ids or any(g in ids for g in boxes_around(d, d.nodes[k].group))}


def story(d: Diagram, sid: str) -> tuple[set[str], set[str], dict[str, list[int]]]:
    """What a scenario uses: its nodes, its edges, and for each edge it draws or flows along, the steps that do."""
    nodes: set[str] = set()
    edges: set[str] = set()
    steps: dict[str, list[int]] = {}

    def edge(ref: str, step: int | None) -> None:
        k = resolve_edge(d, ref)
        if k is None:
            return
        edges.add(k)
        nodes.update((d.edges[k].src.node, d.edges[k].dst.node))
        if step is not None and step not in steps.setdefault(k, []):
            steps[k].append(step)

    def walk(effects: list[Effect], step: int) -> None:
        for e in effects:
            if e.verb == "flow":
                nodes.update(e.targets)
                for a, b in e.links():
                    edge(edge_id(a, b), step)
            else:
                for t in e.targets:
                    head = t.split(".", 1)[0] if e.verb == "set" else t
                    if head in d.nodes:
                        nodes.add(head)
                    else:
                        edge(head, step if e.verb == "draw" else None)
            walk(e.children, step)

    for i, s in enumerate(d.scenarios[sid].steps, 1):
        if s.at in d.nodes:
            nodes.add(s.at)
        walk(s.effects, i)
    return nodes, edges, steps


def _chosen(d: Diagram, vid: str) -> set[str]:
    v = d.views[vid]
    if v.scenario:
        keep = story(d, v.scenario)[0] | (_select(d, v.include) if v.include else set())
    else:
        keep = set(d.nodes) if v.include is None else _select(d, v.include)
    return keep - _select(d, v.exclude)


def view(d: Diagram, vid: str) -> Diagram:
    """The diagram cut down to one view. Nodes that were placed automatically lose their cells, so `prepare` places
    them again and the view closes up; pinned nodes keep theirs. Scenarios are dropped unless the view lists them,
    and so are triggers that would play a dropped one.

    A dynamic view (`scenario`) shows what its scenario uses, plus anything `include` adds, and keeps that scenario
    first. Its edges are the scenario's, plus those between included nodes, and each edge the scenario draws is
    numbered with the steps that draw it."""
    v = d.views[vid]
    keep = _chosen(d, vid)
    out = copy.deepcopy(d)
    out.id, out.title, out.views = f"{d.id}-{vid}", v.title or d.title, {}
    out.nodes = {k: n for k, n in out.nodes.items() if k in keep}
    groups: set[str] = set()
    owner = stack_owners(d)
    for g in [n.group for n in out.nodes.values()] + [owner.get(k, k) for k in keep if owner.get(k, k) in d.groups]:
        groups.update(boxes_around(d, g))
    out.groups = {k: g for k, g in out.groups.items() if k in groups}
    ends = set(out.nodes) | groups | {lid for lid, g in owner.items() if g in groups}
    out.edges = {k: e for k, e in out.edges.items() if e.src.node in ends and e.dst.node in ends}
    out.scenarios = {k: s for k, s in out.scenarios.items() if k in v.scenarios}
    if v.scenario:
        _, edges, steps = story(d, v.scenario)
        extra = _select(d, v.include) if v.include else set()
        out.edges = {k: e for k, e in out.edges.items() if k in edges or (e.src.node in extra and e.dst.node in extra)}
        out.scenarios = {v.scenario: copy.deepcopy(d.scenarios[v.scenario]), **out.scenarios}
        if d.step_list:
            out.numbers = {k: ",".join(map(str, n)) for k, n in steps.items() if k in out.edges}
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
    return out
