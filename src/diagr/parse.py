from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from . import fields as f
from .components import expand, instance_fill
from .effects import Actions, Ctx, parse_effects
from .migrations import upgrade
from .model import (
    Component,
    Diagram,
    Edge,
    Effect,
    Grid,
    Group,
    Instance,
    Node,
    Port,
    Scenario,
    Step,
    View,
    edge_id,
    held,
    stack_owners,
)
from .scenario import walk_effects
from .source import DiagramError, Problem, Y, did_you_mean, load
from .syntax import ARROW, DIAGRAM, EDGE, GROUP, ID, NODE, PAIR_GAP, PORT, REF, layout_flow
from .views import check_views

# The id of the scenario written under 'scenario', for views and scripts that name it.
MAIN_SCENARIO = "main"


def _scenario(sid: str, sc: f.Rec, ctx: Ctx) -> Scenario:
    steps = []
    for s in sc.get("steps"):
        effects = parse_effects(s.get("do"), ctx) if s.get("do") is not None else []
        if s.get("focus"):
            loc = s.at("focus")
            effects = [Effect("focus", s.get("focus"), loc=loc), *effects, Effect("focus", ["none"], loc=loc)]
        steps.append(Step(title=s.get("title"), effects=effects, loc=s.loc, **_given(s, "text", "at", "status")))
    return Scenario(steps=steps, loc=sc.loc, id=sid, **_given(sc, "ready", "end", "title", "loop"))


def _given(rec: f.Rec, *keys: str) -> dict:
    """The keys among these that the file sets, for a model record whose own defaults fill in the rest."""
    return {k: rec.values[k] for k in keys if k in rec.values}


def _triggers(d: Diagram, scenarios: list[f.Entry], problems: list[Problem]) -> None:
    """Put each scenario's trigger button on its node, before layout, which makes room for it."""
    for e in scenarios:
        t = e.value.get("trigger")
        if t is None:
            continue
        k = t.get("at")
        if k not in d.nodes:
            problems.append(
                Problem(t.at("at"), f"scenario '{e.key}': trigger at unknown node '{k}'{did_you_mean(k, d.nodes)}")
            )
        elif d.nodes[k].plays:
            problems.append(
                Problem(t.at("at"), f"scenario '{e.key}': node '{k}' already has the trigger of '{d.nodes[k].plays}'")
            )
        else:
            d.nodes[k].trigger, d.nodes[k].plays = t.get("label"), e.key


def _group(e: f.Entry) -> Group:
    return f.build(Group, GROUP, e.value, skip=("groups", "nodes"), id=e.key, loc=e.loc)


def _node(e: f.Entry) -> Node:
    title = "" if e.value.get("junction") else e.key
    return f.build(Node, NODE, e.value, id=e.key, at=None, loc=e.loc, title=title)


def _boxes(
    groups: list[f.Entry],
    nodes: list[f.Entry],
    parent: str | None,
    gout: dict[str, Group],
    nout: dict[str, Node],
    problems: list[Problem],
) -> None:
    """Groups and nodes, with those written inside a group taken out and put in it."""
    for e in groups:
        g = _group(e)
        if e.key in gout:
            problems.append(Problem(e.loc, f"group '{e.key}' is defined twice"))
            continue
        g.parent = parent
        gout[e.key] = g
        _boxes(e.value.get("groups", []), e.value.get("nodes", []), e.key, gout, nout, problems)
    for e in nodes:
        n = _node(e)
        if e.key in nout:
            problems.append(Problem(e.loc, f"node '{e.key}' is defined twice"))
            continue
        n.group = parent
        nout[e.key] = n


def _nodes_from_edges(d: Diagram) -> None:
    """A plain node for each edge end that names no node or box, so that 'web -> api' is a whole diagram. An instance's
    id ('a/db') is never made up: it has to come from the instance."""
    known = set(d.nodes) | set(d.groups) | set(stack_owners(d))
    for e in d.edges.values():
        for end in (e.src.node, e.dst.node):
            if end not in known and "/" not in end:
                d.nodes[end] = Node(id=end, at=None, title=end, loc=e.loc, implied=True)
                known.add(end)


def _tree_order(d: Diagram) -> None:
    """Groups and nodes in the order the nesting reads, each group followed by what it holds. Instances land in
    their group, and a file written out with nesting reads back in the same order."""
    gout: dict[str, Group] = {}
    nout: dict[str, Node] = {}

    def visit(parent: str | None) -> None:
        for part in held(d.groups, d.nodes, parent):
            for x in part:
                if isinstance(x, Group) and x.id not in gout:
                    gout[x.id] = x
                    visit(x.id)
                elif isinstance(x, Node):
                    nout[x.id] = x

    visit(None)
    d.groups = gout | {k: g for k, g in d.groups.items() if k not in gout}
    d.nodes = nout | {k: n for k, n in d.nodes.items() if k not in nout}


def _ends(text: str) -> list[Port]:
    text = text.strip()
    out = []
    for item in text[1:-1].split() if text.startswith("(") else [text]:
        m = re.fullmatch(PORT, item)
        assert m
        out.append(Port(m.group(1), m.group(2), float(m.group(3) or 0)))
    return out


def _edges(entries: list[f.Entry], out: dict[str, Edge], problems: list[Problem]) -> None:
    for e in entries:
        key, name = e.key, None
        m = re.fullmatch(rf"(.*?)\s+as\s+({REF})", key)
        if m:
            key, name = m.group(1), m.group(2)
        parts = re.split(rf"\s*({ARROW})\s*", key.strip())
        ends = [_ends(p) for p in parts[0::2]]
        # (source, target, dashed, the index of its twin in a pair, if any)
        made: list[tuple[Port, Port, bool, int | None]] = []
        for a, arrow, b in zip(ends, parts[1::2], ends[1:], strict=False):
            for s in a:
                for t in b:
                    if arrow == "<->":
                        i = len(made)
                        made.append(
                            (
                                replace(s, offset=s.offset - PAIR_GAP),
                                replace(t, offset=t.offset - PAIR_GAP),
                                False,
                                i + 1,
                            )
                        )
                        made.append(
                            (replace(t, offset=t.offset + PAIR_GAP), replace(s, offset=s.offset + PAIR_GAP), False, i)
                        )
                    else:
                        made.append((s, t, arrow == "-->", None))
        v = e.value
        if isinstance(v, list) and len(v) != len(made):
            problems.append(Problem(e.loc, f"'{e.key}' makes {len(made)} edges but lists {len(v)} labels or mappings"))
            continue
        if name and len(made) != 1:
            problems.append(Problem(e.loc, f"'as {name}' names one edge, and '{key}' makes {len(made)}"))
            continue
        ids = [name or edge_id(src.node, dst.node) for src, dst, _, _ in made]
        for eid, (src, dst, dashed, twin), val in zip(
            ids, made, v if isinstance(v, list) else [v] * len(made), strict=True
        ):
            if eid in out:
                problems.append(Problem(e.loc, f"edge '{eid}' is defined twice; give one an id with 'as <name>'"))
                continue
            out[eid] = f.build(
                Edge,
                EDGE,
                val,
                id=eid,
                src=src,
                dst=dst,
                dashed=dashed,
                loc=e.loc,
                twin=ids[twin] if twin is not None else None,
            )


def _cell_names(d: Diagram, problems: list[Problem]) -> None:
    """Turn 'cells n build..test' into positions, now that each node's cell names are known."""
    for sc in d.scenarios.values():
        for e in walk_effects(sc):
            if e.verb != "cells" or not e.range_names or e.targets[0] not in d.nodes:
                continue
            names = d.nodes[e.targets[0]].cells
            spots = []
            for name in e.range_names:
                if name in names:
                    spots.append(names.index(name) + 1)
                else:
                    hint = did_you_mean(name, [n for n in names if n]) if any(names) else " (its cells have no names)"
                    problems.append(Problem(e.loc, f"'cells': node '{e.targets[0]}' has no cell '{name}'{hint}"))
            if len(spots) == 2:
                e.range = (spots[0], spots[1])


def from_tree(tree: Y, file: str, base: Path, name: str = "diagram") -> Diagram:
    """The diagram a checked tree describes, in steps: its own keys and boxes, its components and their instances,
    its actions and scenarios, then its views. Every problem found along the way is raised together at the end."""
    problems: list[Problem] = []
    rec = f.check(DIAGRAM, tree, problems)
    if rec is None:
        raise DiagramError(problems)
    d = _head(rec, file, base, name, problems)
    components = _components(rec, problems)
    instances = _instances(rec)
    expand(d, components, instances, problems)
    _tree_order(d)
    _nodes_from_edges(d)
    if not d.nodes:
        problems.append(Problem(rec.loc, "the diagram needs at least one node"))
        raise DiagramError(problems)
    scenarios = _scenario_entries(rec, problems)
    _triggers(d, scenarios, problems)
    _scenarios(d, rec, scenarios, components, instances, problems)
    _cell_names(d, problems)
    for e in rec.get("views") or []:
        v = e.value
        d.views[e.key] = View(id=e.key, loc=e.loc, **_given(v, "title", "include", "exclude", "scenarios", "scenario"))
    problems += check_views(d)
    if problems:
        raise DiagramError(_once(problems))
    return d


def _head(rec: f.Rec, file: str, base: Path, name: str, problems: list[Problem]) -> Diagram:
    """The diagram's own keys, and the groups, nodes and edges it writes out."""
    grid = rec.get("grid")
    d = Diagram(
        id=name,
        grid=Grid(**_given(grid, "col", "row")) if grid else Grid(),
        flow=layout_flow(rec.get("layout")),
        base=base,
        file=file,
        **_given(rec, "title", "description", "theme", "icons", "step_list", "direction", "align"),
    )
    _boxes(rec.get("groups", []), rec.get("nodes", []), None, d.groups, d.nodes, problems)
    _edges(rec.get("edges", []), d.edges, problems)
    return d


def _components(rec: f.Rec, problems: list[Problem]) -> dict[str, Component]:
    components = {}
    for e in rec.get("components", []):
        c = e.value
        comp = Component(e.key, {p.key: p.value for p in c.get("params", [])}, loc=e.loc)
        _boxes(c.get("groups", []), c.get("nodes", []), None, comp.groups, comp.nodes, problems)
        if not comp.nodes:
            problems.append(Problem(e.loc, f"component '{e.key}' needs at least one node"))
        _edges(c.get("edges", []), comp.edges, problems)
        comp.actions = {a.key: a.value for a in c.get("actions", [])}
        components[e.key] = comp
    return components


def _instances(rec: f.Rec) -> dict[str, Instance]:
    instances = {}
    for e in rec.get("instances", []):
        v = e.value
        values = {p.key: p.value for p in v.get("with", [])}
        instances[e.key] = Instance(
            id=e.key, component=v.get("component"), parent=v.get("in"), values=values, loc=e.loc, **_given(v, "at")
        )
    return instances


def _scenario_entries(rec: f.Rec, problems: list[Problem]) -> list[f.Entry]:
    """The scenarios by id: 'scenario' is the one scenario of a diagram that has one, with the id 'main'."""
    one = rec.get("scenario")
    if one is None:
        return rec.get("scenarios") or []
    if rec.get("scenarios") is not None:
        problems.append(Problem(rec.at("scenario"), "use either 'scenario' or 'scenarios', not both"))
    return [f.Entry(MAIN_SCENARIO, rec.at("scenario"), one)]


def _scenarios(
    d: Diagram,
    rec: f.Rec,
    scenarios: list[f.Entry],
    components: dict[str, Component],
    instances: dict[str, Instance],
    problems: list[Problem],
) -> None:
    """The scenarios, with the actions they call: the diagram's own, and each component's on its instances."""
    actions = Actions(problems)
    for e in rec.get("actions", []):
        actions.add(None, e.key, e.value)
    for c in components.values():
        for k, body in c.actions.items():
            actions.add(c.id, k, body)
    for p in instances.values():
        if p.component in components:
            actions.instances[p.id] = (p.component, instance_fill(components[p.component], p))
    actions.check_names()
    ctx = Ctx(problems, actions)
    for e in scenarios:
        d.scenarios[e.key] = _scenario(e.key, e.value, ctx)
    d.component_actions = actions.check_all()


def _once(problems: list[Problem]) -> list[Problem]:
    """Each problem once: an action's body is parsed once for each instance it runs on."""
    seen: set[tuple[object, str]] = set()
    unique = []
    for p in problems:
        if (p.loc, p.message) not in seen:
            seen.add((p.loc, p.message))
            unique.append(p)
    return unique


def diagram_name(path: Path) -> str:
    """What a diagram's outputs are named after: its file, or its folder for a file called diagram.yml."""
    name = path.parent.name if path.stem == "diagram" else path.stem
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "diagram"
    return name if re.fullmatch(ID, name) else f"d-{name}"


def loads(text: str, file: str, base: Path, name: str | None = None) -> Diagram:
    """A diagram from YAML text, upgraded from an older format version first. Its outputs are named `name`, or after
    `file` as given."""
    tree, upgraded = upgrade(load(text, file))
    try:
        d = from_tree(tree, file, base, name or diagram_name(Path(file)))
    except DiagramError as e:
        raise DiagramError(upgraded + e.problems) from None
    d.upgraded = upgraded
    return d


def load_file(path: str | Path) -> Diagram:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise DiagramError([Problem(None, f"cannot read {path}: {e.strerror or e}")]) from None
    except UnicodeDecodeError:
        raise DiagramError([Problem(None, f"cannot read {path}: not UTF-8 text")]) from None
    return loads(text, str(path), path.resolve().parent, diagram_name(path.resolve()))
