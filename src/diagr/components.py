"""Components: a block of groups, nodes and edges defined once and used as named instances.

Expansion runs before validation and turns every instance into ordinary groups, nodes and edges named
'<instance>/<id>', offset by the instance's position, with {param} text filled in.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import fields, replace
from typing import Any

from .model import Component, Diagram, Edge, Instance, Loc
from .source import Problem, did_you_mean

# {name} is a parameter; {{ and }} are literal braces.
PARAM = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _check(c: Component, problems: list[Problem]) -> None:
    """Problems in the definition itself, reported once however many instances there are."""

    def scan(loc: Loc | None, what: str, *texts: str | None) -> None:
        for text in texts:
            for m in PARAM.finditer(text or ""):
                if m.group(1) and m.group(1) not in c.params:
                    have = ", ".join(c.params) or "none"
                    problems.append(
                        Problem(loc, f"component '{c.id}': {what} uses unknown parameter {m.group(0)} (params: {have})")
                    )

    for g in c.groups.values():
        scan(g.loc, f"group '{g.id}'", g.title, g.sub)
    for n in c.nodes.values():
        scan(n.loc, f"node '{n.id}'", n.title, n.tooltip, *n.sub)
    for e in c.edges.values():
        scan(e.loc, f"edge '{e.id}'", e.label, e.tooltip)
        for end in (e.src.node, e.dst.node):
            if end not in c.nodes and end not in c.groups:
                problems.append(
                    Problem(e.loc, f"component '{c.id}': edge '{e.id}' goes to '{end}', not one of its nodes or groups")
                )


def instance_fill(c: Component, p: Instance) -> Callable[[str], str]:
    """Fills {param} in text with the instance's value, or the component's default."""
    values = {k: v for k, v in c.params.items() if v is not None} | p.values

    def fill(text: str) -> str:
        return PARAM.sub(lambda m: m.group(0)[0] if not m.group(1) else values.get(m.group(1), m.group(0)), text)

    return fill


def _instantiate(d: Diagram, c: Component, p: Instance, problems: list[Problem]) -> None:
    fill = instance_fill(c, p)
    ox, oy = p.at

    def name(local: str) -> str:
        return f"{p.id}/{local}"

    def shift(at: tuple[float, float]) -> tuple[float, float]:
        return (at[0] + ox, at[1] + oy)

    def edge_id(e: Edge) -> str:
        return name(e.id) if e.id != f"{e.src.node}->{e.dst.node}" else f"{name(e.src.node)}->{name(e.dst.node)}"

    taken = [name(k) for k in c.groups if name(k) in d.groups] + [name(k) for k in c.nodes if name(k) in d.nodes]
    taken += [edge_id(e) for e in c.edges.values() if edge_id(e) in d.edges]
    if taken:
        problems.append(Problem(p.loc, f"instance '{p.id}': {', '.join(taken)} already defined elsewhere in the file"))
        return
    roles: dict[str, Callable[[Any], Any]] = {"text": fill, "id": name, "cell": shift}

    def own(x: Any) -> Any:
        """x with its text filled, its ids renamed and its cells moved, as its fields' metadata say."""
        changes = {}
        for fl in fields(x):
            v, role = getattr(x, fl.name), fl.metadata.get("instance")
            if role is not None and v is not None:
                one = roles[role]
                changes[fl.name] = [one(i) for i in v] if isinstance(v, list) else one(v)
        return replace(x, **changes)

    for g in c.groups.values():
        d.groups[name(g.id)] = replace(
            own(g),
            id=name(g.id),
            parent=name(g.parent) if g.parent else p.parent,
            behind={name(k): fill(v) for k, v in g.behind.items()},
        )
    for n in c.nodes.values():
        d.nodes[name(n.id)] = replace(own(n), id=name(n.id), group=name(n.group) if n.group else p.parent)
    for e in c.edges.values():
        src, dst = replace(e.src, node=name(e.src.node)), replace(e.dst, node=name(e.dst.node))
        eid = edge_id(e)
        d.edges[eid] = replace(own(e), id=eid, src=src, dst=dst, twin=f"{dst.node}->{src.node}" if e.twin else None)


def expand(
    d: Diagram, components: dict[str, Component], instances: dict[str, Instance], problems: list[Problem]
) -> None:
    for c in components.values():
        _check(c, problems)
    for p in instances.values():
        c = components.get(p.component)
        if c is None:
            have = ", ".join(components) or "none"
            problems.append(
                Problem(p.loc, f"instance '{p.id}': unknown component '{p.component}' (components: {have})")
            )
            continue
        unknown = [k for k in p.values if k not in c.params]
        missing = [k for k, v in c.params.items() if v is None and k not in p.values]
        if unknown:
            problems.append(
                Problem(p.loc, f"instance '{p.id}': component '{c.id}' has no parameter {', '.join(unknown)}")
            )
        if missing:
            problems.append(Problem(p.loc, f"instance '{p.id}': component '{c.id}' needs {', '.join(missing)}"))
        _instantiate(d, c, p, problems)
    for p in instances.values():
        if p.parent and p.parent not in d.groups:
            problems.append(
                Problem(p.loc, f"instance '{p.id}': unknown group '{p.parent}'{did_you_mean(p.parent, d.groups)}")
            )
