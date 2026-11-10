"""Write a diagram back out as YAML, with components expanded into plain groups, nodes and edges (`diagr expand`)."""

from __future__ import annotations

from typing import Any

import yaml

from . import fields as f
from .effects import effect_data
from .layout.auto import place
from .model import Diagram, Edge, Effect, Group, Node, Port, held
from .syntax import EDGE, GROUP, NODE, PAIR_GAP, num

HEAD = ("version", "id", "title", "description", "theme", "icons", "grid", "step_list", "direction", "align", "layout")
REPLACED = ("groups", "nodes", "edges", "components", "instances")


def _group(g: Group) -> dict[str, Any]:
    return f.dump(GROUP, g, skip=("groups", "nodes"))


def _node(n: Node) -> dict[str, Any]:
    return f.dump(NODE, n)


def _port(p: Port) -> str:
    if not p.side:
        return p.node
    return f"{p.node}@{p.side}" + (f"{num(p.offset):+}" if p.offset else "")


def _edge_key(e: Edge) -> str:
    key = f"{_port(e.src)} {'-->' if e.dashed else '->'} {_port(e.dst)}"
    return key if e.id == f"{e.src.node}->{e.dst.node}" else f"{key} as {e.id}"


def _edge(e: Edge, arrow: bool = True) -> dict[str, Any] | str:
    """The edge's value; with arrow, a dashed edge is left to its '-->' key."""
    out = f.dump(EDGE, e, skip=("dashed",) if arrow else ())
    return out["label"] if list(out) == ["label"] else out


def _edges(d: Diagram) -> dict[str, Any]:
    out: dict[str, Any] = {}
    written: set[str] = set()
    for e in d.edges.values():
        if e.id in written:
            continue
        if e.twin in d.edges:
            key = f"{_port(_unpaired(e.src))} <-> {_port(_unpaired(e.dst))}"
            out[key] = [_edge(e, arrow=False) or None, _edge(d.edges[e.twin], arrow=False) or None]
            written.add(e.twin)
        else:
            out[_edge_key(e)] = _edge(e)
    return out


def _unpaired(p: Port) -> Port:
    """The port as written in 'a <-> b': the first edge of a pair runs PAIR_GAP before it."""
    return Port(p.node, p.side, p.offset + PAIR_GAP)


def _calls(items: Any, d: Diagram, names: set[str]) -> Any:
    """A list of effects as written, with each call of a component's action replaced by what it does: the
    components are gone from the expanded file."""
    if not isinstance(items, list):
        return items
    out = []
    for item in items:
        if isinstance(item, str) and item.split() and item.split()[0] in names:
            name, *targets = item.split()
            lanes = [d.component_actions[t][name] for t in targets]
            out.append(effect_data(lanes[0] if len(lanes) == 1 else Effect("parallel", children=lanes)))
        elif isinstance(item, dict):
            out.append({k: _calls(v, d, names) for k, v in item.items()})
        else:
            out.append(_calls(item, d, names))
    return out


def _expand_calls(rest: dict[str, Any], d: Diagram) -> None:
    names = {n for acts in d.component_actions.values() for n in acts}
    if not names:
        return
    for k, body in (rest.get("actions") or {}).items():
        rest["actions"][k] = _calls(body, d, names)
    for sc in (rest.get("scenarios") or {}).values():
        for step in sc.get("steps") or []:
            # A step is a mapping with 'do', or 'Title: [effects]'.
            for k in ["do"] if "title" in step else list(step):
                step[k] = _calls(step.get(k), d, names)


def _flow(v: Any) -> str:
    return yaml.safe_dump(v, default_flow_style=True, width=10**9, sort_keys=False, allow_unicode=True).strip()


def _entry(k: str, v: Any) -> str:
    # Dumping each entry as a one-key mapping quotes the key only when YAML needs it.
    return _flow({k: v})[1:-1]


def _section(name: str, items: dict[str, Any]) -> str:
    lines = [f"{name}:"] + [f"  {_entry(k, v)}" for k, v in items.items()]
    return "\n".join(lines) + "\n"


def _held(d: Diagram, parent: str | None, pad: str) -> list[str]:
    """The groups and nodes a box holds, written inside it, in the order they read back."""
    lines = []
    for part in held(d.groups, d.nodes, parent):
        lines.append(f"{pad}{'groups' if isinstance(part[0], Group) else 'nodes'}:")
        for x in part:
            if isinstance(x, Group):
                lines.append(f"{pad}  {_flow([x.id])[1:-1]}:")
                lines += [f"{pad}    {_entry(k, v)}" for k, v in _group(x).items()]
                lines += _held(d, x.id, pad + "    ")
            else:
                lines.append(f"{pad}  {_entry(x.id, _node(x))}")
    return lines


def _pin(d: Diagram) -> None:
    """Give edges drawn for placed nodes the route they were drawn with, and what else routing chose for them: the
    port they end at and where their label sits. The nodes already carry their positions."""
    from .build import prepare
    from .layout.route import as_route

    for k, path in prepare(d).layout.edges.items():
        e = d.edges[k]
        if e.route is None and e.via is None and (d.nodes[e.src.node].auto or d.nodes[e.dst.node].auto):
            e.route = as_route(path.points) if len(path.points) > 2 else None
            if path.port and not e.dst.side:
                e.dst = path.port
            if path.label_frac is not None and e.label_at is None:
                e.label_at = path.label_frac


def to_yaml(d: Diagram, source: dict[str, Any]) -> str:
    """source is the file as plain YAML data: its other keys, such as the scenarios, are kept as written. Placed
    nodes are written with their positions and their edges with routes, so the output draws the same picture."""
    place(d)
    if any(n.auto for n in d.nodes.values()):
        _pin(d)
    head = {k: source[k] for k in HEAD if k in source}
    rest = {k: v for k, v in source.items() if k not in HEAD and k not in REPLACED}
    _expand_calls(rest, d)
    lines = [
        yaml.safe_dump(
            {k: v},
            sort_keys=False,
            allow_unicode=True,
            width=120,
            default_flow_style=None if isinstance(v, dict) else False,
        )
        for k, v in head.items()
    ]
    parts = ["".join(lines)] if head else []
    parts.append("\n".join(_held(d, None, "")) + "\n")
    if d.edges:
        parts.append(_section("edges", _edges(d)))
    if rest:
        parts.append(yaml.safe_dump(rest, sort_keys=False, allow_unicode=True, width=120))
    return "\n".join(parts)
