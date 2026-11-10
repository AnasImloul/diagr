"""Write a diagram back out as YAML, with components expanded into plain groups, nodes and edges (`diagr expand`)."""

from __future__ import annotations

import math
from typing import Any

import yaml

from .effects import effect_data
from .model import Diagram, Edge, Effect, Flow, Group, Move, Node, Port
from .parse import PAIR_GAP, held

HEAD = ("id", "title", "description", "theme", "icons", "grid", "step_list", "direction", "align", "layout")
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
    if g.title_at:
        out["title_at"] = g.title_at
    if g.flow:
        out["layout"] = _layout(g.flow)
    if not g.box:
        out["box"] = False
    if g.grow:
        out["grow"] = _n(g.grow)
    if g.behind:
        out["behind"] = dict(g.behind)
    return out


def _layout(fl: Flow) -> dict[str, Any] | str:
    out: dict[str, Any] = {"direction": fl.direction}
    if fl.gap != 24:
        out["gap"] = _n(fl.gap)
    if fl.align != "center":
        out["align"] = fl.align
    if fl.justify != "start":
        out["justify"] = fl.justify
    return fl.direction if list(out) == ["direction"] else out


def _node(n: Node) -> dict[str, Any]:
    out: dict[str, Any] = {"at": _pair(n.at)} if n.at else {}
    for key in ("icon", "tone", "title"):
        if getattr(n, key):
            out[key] = getattr(n, key)
    if n.sub:
        out["sub"] = n.sub[0] if len(n.sub) == 1 else list(n.sub)
    if n.junction:
        out["junction"] = True
    if n.cells:
        out["cells"] = len(n.cells) if not any(n.cells) else list(n.cells)
    if n.stack != 1:
        out["stack"] = n.stack
    for key in ("mark", "hidden", "tooltip", "align_x", "align_y"):
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
    key = f"{_port(e.src)} {'-->' if e.dashed else '->'} {_port(e.dst)}"
    return key if e.id == f"{e.src.node}->{e.dst.node}" else f"{key} as {e.id}"


def _edge(e: Edge, arrow: bool = True) -> dict[str, Any] | str:
    """The edge's value; with arrow, a dashed edge is left to its '-->' key."""
    out: dict[str, Any] = {}
    if e.label:
        out["label"] = e.label
    if e.route is not None:
        out["route"] = [_move(m) for m in e.route]
    if e.via is not None:
        out["via"] = [_pair(v) for v in e.via]
    for key in ("dashed", "mark", "hidden", "tooltip"):
        if getattr(e, key) and not (key == "dashed" and arrow):
            out[key] = getattr(e, key)
    if e.label_at is not None:
        out["label_at"] = e.label_at
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


def _along(pts: list[tuple[float, float]], at: tuple[float, float]) -> float:
    """How far along pts the point at lies, from 0 to 1."""
    lens = [math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False)]
    done = 0.0
    for (a, b), ln in zip(zip(pts, pts[1:], strict=False), lens, strict=True):
        if ln and abs(math.dist(a, at) + math.dist(at, b) - ln) < 0.01:
            return round((done + math.dist(a, at)) / sum(lens), 6)
        done += ln
    return 0.5


def _pin(d: Diagram) -> None:
    """Give edges drawn for placed nodes the route they were drawn with; the nodes already carry their positions."""
    from .build import prepare
    from .layout.route import ENTER, as_route, label_point
    from .layout.text import text_width

    p = prepare(d)
    for k, path in p.layout.edges.items():
        e = d.edges[k]
        if e.route is None and e.via is None and (d.nodes[e.src.node].auto or d.nodes[e.dst.node].auto):
            e.route = as_route(path.points) if len(path.points) > 2 else None
            # Edges into one side are spread along it, and a label can sit past a shared trunk: write both down.
            (x0, y0), (x1, y1) = path.points[-2:]
            side = ENTER["right" if x1 > x0 + 0.01 else "left" if x1 < x0 - 0.01 else "down" if y1 > y0 else "up"]
            b = p.layout.nodes.get(e.dst.node)
            if b is not None and not e.dst.side:
                bx, by = b.port(side)
                if abs(x1 - bx) > 0.01 or abs(y1 - by) > 0.01:
                    e.dst = Port(e.dst.node, side, round(y1 - by if side in ("left", "right") else x1 - bx, 2))
            if path.label_at and e.label_at is None:
                w = text_width(e.label, p.theme.size("label")) + 10
                if math.dist(path.label_at, label_point(path.points, None, w)) > 0.01:
                    e.label_at = _along(path.points, path.label_at)


def to_yaml(d: Diagram, source: dict[str, Any]) -> str:
    """source is the file as plain YAML data: its other keys, such as the scenarios, are kept as written. Placed
    nodes are written with their positions and their edges with routes, so the output draws the same picture."""
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
