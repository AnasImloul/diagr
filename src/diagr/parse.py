from __future__ import annotations

import re
from pathlib import Path

from . import fields as f
from .components import expand
from .effects import EFFECT_SCHEMA, parse_effects
from .layout.auto import place
from .model import Component, Diagram, Edge, Grid, Group, Instance, Move, Node, Port, Scenario, Step, View
from .scenario import walk_effects
from .source import DiagramError, Problem, Y, YMap, YScalar, YSeq, did_you_mean, load
from .views import check_views

ID = r"[A-Za-z_][A-Za-z0-9_-]*"
REF = rf"{ID}(?:/{ID})?"
PARAM_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
IDS = "an id: letters, digits, _ and -, optionally 'instance/id' as `diagr expand` writes"
SIDE = r"left|right|top|bottom"
PORT = rf"({REF})(?:@({SIDE})([+-]\d+(?:\.\d+)?)?)?"
EDGE_KEY = rf"{PORT}\s*->\s*{PORT}(?:\s+as\s+({REF}))?"
MOVE = r"(up|down|left|right)(?:\s+(\d+(?:\.\d+)?)(px)?)?"
MARKS = ("new", "removed", "changed")


class Cells(f.T):
    description = "Progress cells: a list of names (shown as the caption while active) or a count"

    def kind(self) -> str:
        return "a list of names or a count"

    def check(self, y, problems):
        if isinstance(y, YSeq):
            return f.List(f.Str()).check(y, problems)
        n = f.Num(integer=True, minimum=1).check(y, problems)
        return [""] * int(n)

    def schema(self):
        return f._describe(
            {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "integer", "minimum": 1}]},
            self.description,
        )


class Param(f.T):
    description = "The default value, or {required: true} for a parameter every instance must set"

    def kind(self) -> str:
        return "a default value or {required: true}"

    def check(self, y, problems):
        if isinstance(y, YMap):
            rec = f.Obj("parameter", {"required": f.F(f.Bool(), required=True)}).check(y, problems)
            if not rec.get("required"):
                return self._fail(y, problems, "a parameter without a default needs {required: true}")
            return None
        if isinstance(y, YScalar) and y.null:
            return self._fail(y, problems, "give the parameter a default, or write {required: true}")
        return f.Str().check(y, problems)

    def schema(self):
        return f._describe(
            {
                "oneOf": [
                    {"type": "string"},
                    {
                        "type": "object",
                        "properties": {"required": {"const": True}},
                        "required": ["required"],
                        "additionalProperties": False,
                    },
                ]
            },
            self.description,
        )


GROUP = f.Obj(
    "group",
    {
        "title": f.F(f.Str(description="Shown at the bottom left of the group"), required=True),
        "sub": f.F(f.Str(description="Muted text after the title")),
        "icon": f.F(f.Str(description="Icon name, shown before the title")),
        "tone": f.F(f.Str(description="Theme tone: blue, teal, green, violet, amber, orange, neutral")),
        "at": f.F(f.Pair(description="Top-left cell [col, row]; default: fit the member nodes and groups")),
        "span": f.F(f.Pair(minimum=1, description="Size in cells [cols, rows]")),
        "in": f.F(f.Str(description="Parent group id")),
    },
    description="A titled, tinted container around nodes and other groups",
)

NODE = f.Obj(
    "node",
    {
        "at": f.F(f.Pair(description="Grid cell [col, row]; fractions allowed; default: placed automatically")),
        "title": f.F(f.Str()),
        "sub": f.F(f.Lines(description="Muted text under the title")),
        "icon": f.F(f.Str(description="Icon name from the diagram's icon folders or the core set")),
        "tone": f.F(f.Str(description="Tile colour for generated icons")),
        "in": f.F(f.Str(description="Group id")),
        "junction": f.F(f.Bool(description="A dot where edges meet (a bus); has no icon or text")),
        "trigger": f.F(f.Str(description="Label of a button under the node that plays a scenario")),
        "plays": f.F(f.Str(description="Scenario id the trigger plays; default: the first scenario")),
        "cells": f.F(Cells()),
        "stack": f.F(f.Num(integer=True, minimum=1, description="Draw the icon as a stack of N")),
        "mark": f.F(f.Str(enum=MARKS)),
        "hidden": f.F(f.Bool(description="Start hidden; a scenario can show it")),
        "tooltip": f.F(f.Str()),
    },
    description="A node: icon, title and sub text, centred on a grid cell",
)

EDGE = f.Obj(
    "edge",
    {
        "label": f.F(f.Str()),
        "route": f.F(
            f.List(
                f.Str(
                    pattern=MOVE,
                    description="a move: up, down, left or right, with an optional "
                    "length in cells or px, e.g. 'right 0.5' or 'up 40px'",
                ),
                description="Moves from the start node. Moves without a length on the same axis share what is left",
            )
        ),
        "via": f.F(f.List(f.Pair(), description="Explicit waypoints in grid cells (escape hatch)")),
        "dashed": f.F(f.Bool()),
        "mark": f.F(f.Str(enum=MARKS)),
        "label_at": f.F(
            f.Num(
                minimum=0,
                maximum=1,
                description="Label position along the path, 0 to 1; default: middle of the longest segment",
            )
        ),
        "hidden": f.F(f.Bool()),
        "tooltip": f.F(f.Str()),
    },
    shorthand=f.Str(description="The label"),
    shorthand_field="label",
    description="An edge; the key is 'a -> b', with optional ports 'a@bottom+10' and id 'a -> b as name'",
)

STEP = f.Obj(
    "step",
    {
        "title": f.F(f.Str(), required=True),
        "text": f.F(f.Str(description="Longer explanation for the step list")),
        "at": f.F(f.Str(description="Node that carries the step's number badge")),
        "status": f.F(f.Str(description="Status line while the step plays; default: the title")),
        "do": f.F(f.Raw(EFFECT_SCHEMA, description="Effects, in order")),
    },
)

SCENARIO = f.Obj(
    "scenario",
    {
        "title": f.F(f.Str(description="Name in the player's scenario picker")),
        "loop": f.F(
            f.Bool(description="Replay forever; the first looping scenario starts on its own when the page loads")
        ),
        "ready": f.F(f.Str(description="Status line before the run")),
        "end": f.F(f.Str(description="Status line after the run")),
        "steps": f.F(f.List(STEP, min_items=1), required=True),
    },
)

EDGES = f.MapOf(EDGE, key_pattern=EDGE_KEY, key_description="an edge key like 'a -> b'")

COMPONENT = f.Obj(
    "component",
    {
        "params": f.F(
            f.MapOf(
                Param(),
                key_pattern=PARAM_NAME,
                key_description="a parameter name: letters, digits and _",
                description="Text parameters, used as {name} in titles, sub text, labels, tooltips and triggers",
            )
        ),
        "groups": f.F(f.MapOf(GROUP)),
        "nodes": f.F(f.MapOf(NODE, min_items=1), required=True),
        "edges": f.F(EDGES),
    },
    description="A reusable block of groups, nodes and edges in its own grid cells; 'instances' uses it",
)

INSTANCE = f.Obj(
    "instance",
    {
        "component": f.F(f.Str(pattern=ID, description="Component id"), required=True),
        "at": f.F(f.Pair(description="Grid cell where the component's [0, 0] goes; default [0, 0]")),
        "in": f.F(f.Str(description="Group that holds the instance's outermost groups and nodes")),
        "with": f.F(
            f.MapOf(
                f.Str(),
                key_pattern=PARAM_NAME,
                key_description="a parameter name: letters, digits and _",
                description="Parameter values",
            )
        ),
    },
    description="An instance of a component; its groups, nodes and edges are named '<instance>/<id>'",
)

VIEW = f.Obj(
    "view",
    {
        "title": f.F(f.Str(description="Title of the view's page and images; default: the diagram's")),
        "include": f.F(f.List(f.Str(), description="Group and node ids to show, groups with everything inside them")),
        "exclude": f.F(f.List(f.Str(), description="Group and node ids to leave out of what include selects")),
        "scenarios": f.F(f.List(f.Str(), description="Scenarios the view keeps; default: none")),
    },
)

DIAGRAM = f.Obj(
    "diagram",
    {
        "id": f.F(f.Str(pattern=ID, description="Diagram id, used for output file names"), required=True),
        "title": f.F(f.Str()),
        "description": f.F(f.Str(description="Accessible description of the whole diagram")),
        "theme": f.F(f.Str(description="Theme name or path to a theme file")),
        "icons": f.F(f.List(f.Str(), description="Icon folders, relative to this file")),
        "grid": f.F(
            f.Obj("grid", {"col": f.F(f.Num(minimum=1)), "row": f.F(f.Num(minimum=1))}, description="Cell size in px")
        ),
        "groups": f.F(f.MapOf(GROUP, key_pattern=REF, key_description=IDS)),
        "nodes": f.F(f.MapOf(NODE, min_items=1, key_pattern=REF, key_description=IDS), required=True),
        "edges": f.F(EDGES),
        "components": f.F(f.MapOf(COMPONENT)),
        "instances": f.F(f.MapOf(INSTANCE)),
        "scenarios": f.F(
            f.MapOf(SCENARIO, min_items=1, description="Scenarios by id; the first is the default and static output's")
        ),
        "step_list": f.F(f.Bool(description="Show numbered badges and the step list in static output (default true)")),
        "direction": f.F(f.Str(enum=("right", "down"), description="Which way automatically placed nodes flow")),
        "views": f.F(
            f.MapOf(
                VIEW,
                key_pattern=ID,
                description="Parts of the diagram built as their own images and page, <id>-<view>",
            )
        ),
    },
)


def json_schema() -> dict:
    s = DIAGRAM.schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "diagr diagram",
        **s,
        "$defs": {"effects": EFFECT_SCHEMA},
    }


def _moves(items: list[str]) -> list[Move]:
    out = []
    for s in items:
        m = re.fullmatch(MOVE, s)
        assert m
        out.append(Move(m.group(1), float(m.group(2)) if m.group(2) else None, "px" if m.group(3) else "cells"))
    return out


def _scenario(sid: str, sc: f.Rec, problems: list[Problem]) -> Scenario:
    steps = []
    for s in sc.get("steps"):
        effects = parse_effects(s.get("do"), problems) if s.get("do") is not None else []
        steps.append(Step(s.get("title"), s.get("text", ""), s.get("at"), s.get("status"), effects, s.loc))
    return Scenario(
        steps, sc.get("ready", ""), sc.get("end", ""), sc.loc, sid, sc.get("title", ""), sc.get("loop", False)
    )


def _group(e: f.Entry) -> Group:
    g = e.value
    return Group(
        e.key,
        g.get("title"),
        g.get("sub", ""),
        g.get("icon"),
        g.get("tone", "neutral"),
        g.get("at"),
        g.get("span"),
        e.loc,
        parent=g.get("in"),
    )


def _node(e: f.Entry) -> Node:
    n = e.value
    return Node(
        id=e.key,
        at=n.get("at"),
        title=n.get("title", ""),
        sub=n.get("sub", []),
        icon=n.get("icon"),
        tone=n.get("tone"),
        group=n.get("in"),
        junction=n.get("junction", False),
        trigger=n.get("trigger"),
        cells=n.get("cells", []),
        stack=n.get("stack", 1),
        mark=n.get("mark"),
        hidden=n.get("hidden", False),
        tooltip=n.get("tooltip"),
        loc=e.loc,
        plays=n.get("plays"),
    )


def _edges(entries: list[f.Entry], out: dict[str, Edge], problems: list[Problem]) -> None:
    for e in entries:
        m = re.fullmatch(EDGE_KEY, e.key)
        assert m
        src = Port(m.group(1), m.group(2), float(m.group(3) or 0))
        dst = Port(m.group(4), m.group(5), float(m.group(6) or 0))
        eid = m.group(7) or f"{src.node}->{dst.node}"
        if eid in out:
            problems.append(Problem(e.loc, f"edge '{eid}' is defined twice; give one an id with 'as <name>'"))
            continue
        v = e.value
        out[eid] = Edge(
            id=eid,
            src=src,
            dst=dst,
            label=v.get("label", ""),
            route=_moves(v.get("route")) if v.get("route") is not None else None,
            via=v.get("via"),
            dashed=v.get("dashed", False),
            mark=v.get("mark"),
            label_at=v.get("label_at"),
            hidden=v.get("hidden", False),
            tooltip=v.get("tooltip"),
            loc=e.loc,
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


def from_tree(tree: Y, file: str, base: Path) -> Diagram:
    problems: list[Problem] = []
    rec = f.check(DIAGRAM, tree, problems)
    if rec is None:
        raise DiagramError(problems)

    grid = rec.get("grid")
    d = Diagram(
        id=rec.get("id"),
        title=rec.get("title", ""),
        description=rec.get("description", ""),
        theme=rec.get("theme", "default"),
        icons=rec.get("icons", []),
        grid=Grid(grid.get("col", 215), grid.get("row", 160)) if grid else Grid(),
        step_list=rec.get("step_list", True),
        direction=rec.get("direction", "right"),
        base=base,
        file=file,
    )
    for e in rec.get("groups", []):
        d.groups[e.key] = _group(e)
    for e in rec.get("nodes", []):
        d.nodes[e.key] = _node(e)
    _edges(rec.get("edges", []), d.edges, problems)
    components = {}
    for e in rec.get("components", []):
        c = e.value
        comp = Component(e.key, {p.key: p.value for p in c.get("params", [])}, loc=e.loc)
        comp.groups = {g.key: _group(g) for g in c.get("groups", [])}
        comp.nodes = {n.key: _node(n) for n in c.get("nodes", [])}
        _edges(c.get("edges", []), comp.edges, problems)
        components[e.key] = comp
    instances = {}
    for e in rec.get("instances", []):
        v = e.value
        values = {p.key: p.value for p in v.get("with", [])}
        instances[e.key] = Instance(e.key, v.get("component"), v.get("at") or (0, 0), v.get("in"), values, e.loc)
    expand(d, components, instances, problems)
    place(d)

    for e in rec.get("scenarios") or []:
        d.scenarios[e.key] = _scenario(e.key, e.value, problems)
    _cell_names(d, problems)
    for e in rec.get("views") or []:
        v = e.value
        d.views[e.key] = View(
            e.key, v.get("title", ""), v.get("include"), v.get("exclude", []), v.get("scenarios", []), e.loc
        )
    problems += check_views(d)

    if problems:
        raise DiagramError(problems)
    return d


def load_file(path: str | Path) -> Diagram:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise DiagramError([Problem(None, f"cannot read {path}: {e.strerror or e}")]) from None
    except UnicodeDecodeError:
        raise DiagramError([Problem(None, f"cannot read {path}: not UTF-8 text")]) from None
    return from_tree(load(text, str(path)), str(path), path.resolve().parent)
