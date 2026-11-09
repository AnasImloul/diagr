"""Write a diagram back out as YAML, with components expanded into plain groups, nodes and edges (`diagr expand`)."""

from __future__ import annotations

from typing import Any

import yaml

from .model import Diagram, Edge, Group, Move, Node, Port

HEAD = ("id", "title", "description", "theme", "icons", "grid", "step_list", "direction")
REPLACED = ("groups", "nodes", "edges", "components", "instances")


def _n(v: float) -> float | int:
    return int(v) if float(v).is_integer() else round(v, 6)


def _pair(p: tuple[float, float]) -> list[float | int]:
    return [_n(p[0]), _n(p[1])]


def _group(g: Group) -> dict[str, Any]:
    out: dict[str, Any] = {"title": g.title}
    if g.sub:
        out["sub"] = g.sub
    if g.icon:
        out["icon"] = g.icon
    out["tone"] = g.tone
    if g.at is not None:
        out["at"] = _pair(g.at)
    if g.span is not None:
        out["span"] = _pair(g.span)
    if g.parent:
        out["in"] = g.parent
    return out


def _node(n: Node) -> dict[str, Any]:
    out: dict[str, Any] = {"at": _pair(n.at)} if n.at else {}
    if n.group:
        out["in"] = n.group
    for key in ("icon", "tone", "title"):
        if getattr(n, key):
            out[key] = getattr(n, key)
    if n.sub:
        out["sub"] = n.sub[0] if len(n.sub) == 1 else list(n.sub)
    if n.junction:
        out["junction"] = True
    if n.trigger:
        out["trigger"] = n.trigger
    if n.plays:
        out["plays"] = n.plays
    if n.cells:
        out["cells"] = len(n.cells) if not any(n.cells) else list(n.cells)
    if n.stack != 1:
        out["stack"] = n.stack
    for key in ("mark", "hidden", "tooltip"):
        if getattr(n, key):
            out[key] = getattr(n, key)
    return out


def _port(p: Port) -> str:
    if not p.side:
        return p.node
    return f"{p.node}@{p.side}" + (f"{_n(p.offset):+}" if p.offset else "")


def _move(m: Move) -> str:
    if m.length is None:
        return m.dir
    return f"{m.dir} {_n(m.length)}" + ("px" if m.unit == "px" else "")


def _edge_key(e: Edge) -> str:
    key = f"{_port(e.src)} -> {_port(e.dst)}"
    return key if e.id == f"{e.src.node}->{e.dst.node}" else f"{key} as {e.id}"


def _edge(e: Edge) -> dict[str, Any] | str:
    out: dict[str, Any] = {}
    if e.label:
        out["label"] = e.label
    if e.route is not None:
        out["route"] = [_move(m) for m in e.route]
    if e.via is not None:
        out["via"] = [_pair(v) for v in e.via]
    for key in ("dashed", "mark", "hidden", "tooltip"):
        if getattr(e, key):
            out[key] = getattr(e, key)
    if e.label_at is not None:
        out["label_at"] = e.label_at
    return out["label"] if list(out) == ["label"] else out


def _flow(v: Any) -> str:
    return yaml.safe_dump(v, default_flow_style=True, width=10**9, sort_keys=False, allow_unicode=True).strip()


def _section(name: str, items: dict[str, Any]) -> str:
    # Dumping each entry as a one-key mapping quotes the key only when YAML needs it.
    lines = [f"{name}:"] + [f"  {_flow({k: v})[1:-1]}" for k, v in items.items()]
    return "\n".join(lines) + "\n"


def _pin(d: Diagram) -> None:
    """Give edges drawn for placed nodes the route they were drawn with; the nodes already carry their positions."""
    from .build import prepare
    from .layout.route import as_route

    edges = prepare(d).layout.edges
    for k, path in edges.items():
        e = d.edges[k]
        if e.route is None and e.via is None and (d.nodes[e.src.node].auto or d.nodes[e.dst.node].auto):
            e.route = as_route(path.points) if len(path.points) > 2 else None


def to_yaml(d: Diagram, source: dict[str, Any]) -> str:
    """source is the file as plain YAML data: its other keys, such as the scenarios, are kept as written. Placed
    nodes are written with their positions and their edges with routes, so the output draws the same picture."""
    if any(n.auto for n in d.nodes.values()):
        _pin(d)
    head = {k: source[k] for k in HEAD if k in source}
    rest = {k: v for k, v in source.items() if k not in HEAD and k not in REPLACED}
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
    if d.groups:
        parts.append(_section("groups", {k: _group(g) for k, g in d.groups.items()}))
    parts.append(_section("nodes", {k: _node(n) for k, n in d.nodes.items()}))
    if d.edges:
        parts.append(_section("edges", {_edge_key(e): _edge(e) for e in d.edges.values()}))
    if rest:
        parts.append(yaml.safe_dump(rest, sort_keys=False, allow_unicode=True, width=120))
    return "\n".join(parts)
