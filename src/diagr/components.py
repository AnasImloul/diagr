"""Components: a block of groups, nodes and edges defined once and used as named instances.

Expansion runs before validation and turns every instance into ordinary groups, nodes and edges named
'<instance>/<id>', offset by the instance's position, with {param} text filled in.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .model import Component, Diagram, Instance, Loc
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
        if g.parent and g.parent not in c.groups:
            problems.append(
                Problem(g.loc, f"component '{c.id}': group '{g.id}' is in '{g.parent}', not one of its groups")
            )
    for n in c.nodes.values():
        scan(n.loc, f"node '{n.id}'", n.title, n.tooltip, n.trigger, *n.sub)
        if n.group and n.group not in c.groups:
            problems.append(
                Problem(n.loc, f"component '{c.id}': node '{n.id}' is in '{n.group}', not one of its groups")
            )
    for e in c.edges.values():
        scan(e.loc, f"edge '{e.id}'", e.label, e.tooltip)
        for end in (e.src.node, e.dst.node):
            if end not in c.nodes:
                problems.append(
                    Problem(e.loc, f"component '{c.id}': edge '{e.id}' goes to '{end}', not one of its nodes")
                )


def _instantiate(d: Diagram, c: Component, p: Instance, problems: list[Problem]) -> None:
    values = {k: v for k, v in c.params.items() if v is not None} | p.values
    ox, oy = p.at

    def fill(text: str) -> str:
        return PARAM.sub(lambda m: m.group(0)[0] if not m.group(1) else values.get(m.group(1), m.group(0)), text)

    def name(local: str) -> str:
        return f"{p.id}/{local}"

    def shift(at: tuple[float, float]) -> tuple[float, float]:
        return (at[0] + ox, at[1] + oy)

    taken = [name(k) for k in c.groups if name(k) in d.groups] + [name(k) for k in c.nodes if name(k) in d.nodes]
    if taken:
        problems.append(Problem(p.loc, f"instance '{p.id}': {', '.join(taken)} already defined elsewhere in the file"))
        return
    for g in c.groups.values():
        d.groups[name(g.id)] = replace(
            g,
            id=name(g.id),
            title=fill(g.title),
            sub=fill(g.sub),
            at=shift(g.at) if g.at else None,
            parent=name(g.parent) if g.parent else p.parent,
        )
    for n in c.nodes.values():
        d.nodes[name(n.id)] = replace(
            n,
            id=name(n.id),
            at=shift(n.at),
            title=fill(n.title),
            sub=[fill(s) for s in n.sub],
            tooltip=fill(n.tooltip) if n.tooltip else None,
            trigger=fill(n.trigger) if n.trigger else None,
            group=name(n.group) if n.group else p.parent,
        )
    for e in c.edges.values():
        src, dst = replace(e.src, node=name(e.src.node)), replace(e.dst, node=name(e.dst.node))
        named = e.id != f"{e.src.node}->{e.dst.node}"
        eid = name(e.id) if named else f"{src.node}->{dst.node}"
        d.edges[eid] = replace(
            e,
            id=eid,
            src=src,
            dst=dst,
            label=fill(e.label),
            tooltip=fill(e.tooltip) if e.tooltip else None,
            via=[shift(v) for v in e.via] if e.via else e.via,
        )


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
