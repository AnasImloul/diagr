from __future__ import annotations

import re
from pathlib import Path

from . import fields as f
from .effects import EFFECT_SCHEMA, parse_effects
from .model import Diagram, Edge, Grid, Group, Move, Node, Port, Scenario, Step
from .source import DiagramError, Problem, Y, YSeq, load

ID = r"[A-Za-z_][A-Za-z0-9_-]*"
SIDE = r"left|right|top|bottom"
PORT = rf"({ID})(?:@({SIDE})([+-]\d+(?:\.\d+)?)?)?"
EDGE_KEY = rf"{PORT}\s*->\s*{PORT}(?:\s+as\s+({ID}))?"
MOVE = r"(up|down|left|right)(?:\s+(\d+(?:\.\d+)?)(px)?)?"
MARKS = ("new", "removed", "changed")
FORMAT_VERSION = 1


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


GROUP = f.Obj(
    "group",
    {
        "title": f.F(f.Str(description="Shown at the bottom left of the group"), required=True),
        "sub": f.F(f.Str(description="Muted text after the title")),
        "icon": f.F(f.Str(description="Icon name, shown before the title")),
        "tone": f.F(f.Str(description="Theme tone: blue, teal, green, violet, amber, orange, neutral")),
        "at": f.F(f.Pair(description="Top-left cell [col, row]; default: fit the member nodes")),
        "span": f.F(f.Pair(minimum=1, description="Size in cells [cols, rows]")),
    },
    description="A titled, tinted container around nodes",
)

NODE = f.Obj(
    "node",
    {
        "at": f.F(f.Pair(description="Grid cell [col, row]; fractions allowed"), required=True),
        "title": f.F(f.Str()),
        "sub": f.F(f.Lines(description="Muted text under the title")),
        "icon": f.F(f.Str(description="Icon name from the diagram's icon folders or the core set")),
        "tone": f.F(f.Str(description="Tile colour for generated icons")),
        "in": f.F(f.Str(description="Group id")),
        "junction": f.F(f.Bool(description="A dot where edges meet (a bus); has no icon or text")),
        "trigger": f.F(f.Str(description="Label of a button under the node that plays the scenario")),
        "cells": f.F(Cells()),
        "stack": f.F(f.Num(integer=True, minimum=1, description="Draw the icon as a stack of N")),
        "mark": f.F(f.Str(enum=MARKS)),
        "hidden": f.F(f.Bool(description="Start hidden; the scenario can show it")),
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
        "ready": f.F(f.Str(description="Status line before the run")),
        "end": f.F(f.Str(description="Status line after the run")),
        "steps": f.F(f.List(STEP, min_items=1), required=True),
    },
)

DIAGRAM = f.Obj(
    "diagram",
    {
        "diagr": f.F(f.Num(integer=True, minimum=1, maximum=FORMAT_VERSION, description="Format version")),
        "diagram": f.F(f.Str(pattern=ID, description="Diagram id, used for output file names"), required=True),
        "title": f.F(f.Str()),
        "description": f.F(f.Str(description="Accessible description of the whole diagram")),
        "theme": f.F(f.Str(description="Theme name or path to a theme file")),
        "icons": f.F(f.List(f.Str(), description="Icon folders, relative to this file")),
        "grid": f.F(
            f.Obj("grid", {"col": f.F(f.Num(minimum=1)), "row": f.F(f.Num(minimum=1))}, description="Cell size in px")
        ),
        "groups": f.F(f.MapOf(GROUP)),
        "nodes": f.F(f.MapOf(NODE, min_items=1), required=True),
        "edges": f.F(f.MapOf(EDGE, key_pattern=EDGE_KEY, key_description="an edge key like 'a -> b'")),
        "scenario": f.F(SCENARIO),
        "step_list": f.F(f.Bool(description="Show numbered badges and the step list in static output (default true)")),
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


def from_tree(tree: Y, file: str, base: Path) -> Diagram:
    problems: list[Problem] = []
    rec = f.check(DIAGRAM, tree, problems)
    if rec is None:
        raise DiagramError(problems)

    grid = rec.get("grid")
    d = Diagram(
        id=rec.get("diagram"),
        title=rec.get("title", ""),
        description=rec.get("description", ""),
        theme=rec.get("theme", "default"),
        icons=rec.get("icons", []),
        grid=Grid(grid.get("col", 215), grid.get("row", 160)) if grid else Grid(),
        step_list=rec.get("step_list", True),
        base=base,
        file=file,
    )
    for e in rec.get("groups", []):
        g = e.value
        d.groups[e.key] = Group(
            e.key,
            g.get("title"),
            g.get("sub", ""),
            g.get("icon"),
            g.get("tone", "neutral"),
            g.get("at"),
            g.get("span"),
            e.loc,
        )
    for e in rec.get("nodes", []):
        n = e.value
        d.nodes[e.key] = Node(
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
        )
    for e in rec.get("edges", []):
        m = re.fullmatch(EDGE_KEY, e.key)
        assert m
        src = Port(m.group(1), m.group(2), float(m.group(3) or 0))
        dst = Port(m.group(4), m.group(5), float(m.group(6) or 0))
        eid = m.group(7) or f"{src.node}->{dst.node}"
        if eid in d.edges:
            problems.append(Problem(e.loc, f"edge '{eid}' is defined twice; give one an id with 'as <name>'"))
            continue
        v = e.value
        d.edges[eid] = Edge(
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

    sc = rec.get("scenario")
    if sc is not None:
        steps = []
        for s in sc.get("steps"):
            effects = parse_effects(s.get("do"), problems) if s.get("do") is not None else []
            steps.append(Step(s.get("title"), s.get("text", ""), s.get("at"), s.get("status"), effects, s.loc))
        d.scenario = Scenario(steps, sc.get("ready", ""), sc.get("end", ""), sc.loc)

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
