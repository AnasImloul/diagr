from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from . import fields as f
from .components import expand, instance_fill
from .effects import EFFECT_SCHEMA, Actions, Ctx, parse_effects
from .model import (
    Component,
    Diagram,
    Edge,
    Effect,
    Flow,
    Grid,
    Group,
    Instance,
    Move,
    Node,
    Port,
    Scenario,
    Step,
    View,
)
from .scenario import walk_effects
from .source import DiagramError, Problem, Y, YMap, YScalar, YSeq, did_you_mean, load
from .views import check_views

ID = r"[A-Za-z_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?"
REF = rf"{ID}(?:/{ID})?"
PARAM_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
IDS = "an id: letters, digits, _ and - (not last), optionally 'instance/id' as `diagr expand` writes"
SIDE = r"left|right|top|bottom"
PORT = rf"({REF})(?:@({SIDE})([+-]\d+(?:\.\d+)?)?)?"
_PORT = rf"{REF}(?:@(?:{SIDE})(?:[+-]\d+(?:\.\d+)?)?)?"
_END = rf"(?:{_PORT}|\(\s*{_PORT}(?:\s+{_PORT})*\s*\))"
ARROW = r"<->|-->|->"
EDGE_KEY = rf"{_END}(?:\s*(?:{ARROW})\s*{_END})+(?:\s+as\s+{REF})?"
MOVE = r"(up|down|left|right)(?:\s+(\d+(?:\.\d+)?)(px)?)?"
MARKS = ("new", "removed", "changed")
# How far apart the two edges of a pair 'a <-> b' run, either side of the middle, in px.
PAIR_GAP = 10


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


TITLE_AT = ("bottom-left", "top-left", "top", "bottom", "middle")
DIRECTIONS = ("row", "column")

LAYOUT = f.Obj(
    "layout",
    {
        "direction": f.F(f.Str(enum=DIRECTIONS, description="row or column (default column)")),
        "gap": f.F(f.Num(minimum=0, description="Space between items, in px (default 24)")),
        "align": f.F(
            f.Str(
                enum=("start", "center", "end", "stretch"),
                description="Across the direction: start, center (default), end, or stretch to fill",
            )
        ),
        "justify": f.F(
            f.Str(
                enum=("start", "center", "end", "space-between", "space-around"),
                description="Along the direction, for space left over: start (default), center, end, space-between "
                "or space-around",
            )
        ),
    },
    description="Arrange what the box holds in a row or column, in file order, instead of by cells: "
    "row, column, or a mapping with direction, gap and align",
    shorthand=f.Str(enum=DIRECTIONS),
    shorthand_field="direction",
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
        "title_at": f.F(
            f.Str(
                enum=TITLE_AT,
                description="Where the title goes: bottom-left (default), top-left (default for a stack), "
                "top or bottom (centred along that edge), or middle: a heading beside the box's nodes, sub below",
            )
        ),
        "layout": f.F(LAYOUT),
        "box": f.F(f.Bool(description="false: draw no box or title; the group only arranges what it holds")),
        "grow": f.F(
            f.Num(minimum=0, description="In a box with layout: this group's share of the space left over (default 0)")
        ),
        "behind": f.F(
            f.MapOf(
                f.Str(),
                key_pattern=REF,
                key_description=IDS,
                description="Boxes stacked behind this one, nearest first, as id: title; edges can end at them",
            )
        ),
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
        "junction": f.F(f.Bool(description="A dot where edges meet (a bus); has no icon or text")),
        "align_x": f.F(f.Str(description="A node to line up with, one above the other: same x")),
        "align_y": f.F(f.Str(description="A node to line up with, side by side: same y")),
        "cells": f.F(Cells()),
        "stack": f.F(f.Num(integer=True, minimum=1, description="Draw the icon as a stack of N")),
        "mark": f.F(f.Str(enum=MARKS)),
        "hidden": f.F(f.Bool(description="Start hidden; a scenario can show it")),
        "tooltip": f.F(f.Str()),
    },
    description="A node: icon, title and sub text, centred on a grid cell",
)

GROUP.fields["nodes"] = f.F(
    f.MapOf(NODE, min_items=1, key_pattern=REF, key_description=IDS, description="Nodes inside this group")
)
GROUP.fields["groups"] = f.F(
    f.MapOf(
        f.Ref("group", lambda: GROUP),
        min_items=1,
        key_pattern=REF,
        key_description=IDS,
        description="Groups inside this group",
    )
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
    description="An edge: its label, or a mapping",
)


class EdgeValue(f.T):
    """What an edge key holds: nothing, a label or a mapping for every edge it makes, or a list with one each."""

    def kind(self) -> str:
        return "a label, a mapping or a list"

    def check(self, y, problems):
        if isinstance(y, YScalar) and y.null:
            return f.Rec(y.loc, {}, {})
        if isinstance(y, YSeq):
            out, bad = [], False
            for item in y.items:
                try:
                    out.append(self.check(item, problems) if not isinstance(item, YSeq) else self._fail(item, problems))
                except f.Invalid:
                    bad = True
            if bad:
                raise f.Invalid
            return out
        return EDGE.check(y, problems)

    def schema(self):
        one = {"oneOf": [{"type": "null"}, EDGE.schema()]}
        return {
            "oneOf": [*one["oneOf"], {"type": "array", "items": one, "description": "One label or mapping per edge"}],
            "description": "Nothing, the label, a mapping for every edge the key makes, or a list with one each",
        }


EDGES = f.MapOf(
    EdgeValue(),
    key_pattern=EDGE_KEY,
    key_description="an edge key like 'a -> b', 'a -> b -> c', '(a b) -> c', 'a --> b' or 'a <-> b'",
    description="Edges. The key is 'a -> b', with optional ports 'a@bottom+10' and id 'a -> b as name'. A chain "
    "'a -> b -> c' makes an edge per arrow, '(a b) -> c' one from each, '-->' a dashed edge and '<->' a pair, one "
    "each way, side by side",
)

STEP_FIELDS = {
    "title": f.F(f.Str(), required=True),
    "text": f.F(f.Str(description="Longer explanation for the step list")),
    "at": f.F(f.Str(description="Node that carries the step's number badge")),
    "status": f.F(f.Str(description="Status line while the step plays; default: the title")),
    "focus": f.F(
        f.List(f.Str(), min_items=1, description="Dim everything but these, and the edges between them, for the step")
    ),
    "do": f.F(f.Raw({"$ref": "#/$defs/effects"}, description="Effects, in order")),
}
STEP = f.Obj("step", STEP_FIELDS)


class StepT(f.T):
    """A step, or 'Title: [effects]' for one with nothing else to say."""

    def kind(self) -> str:
        return "a mapping"

    def check(self, y, problems):
        if isinstance(y, YMap) and len(y.pairs) == 1 and y.pairs[0][0].value not in STEP_FIELDS:
            k, v = y.pairs[0]
            if isinstance(v, YSeq):
                return f.Rec(y.loc, {"title": k.value, "do": v}, {"title": k.loc, "do": v.loc})
        return STEP.check(y, problems)

    def schema(self):
        short = {
            "type": "object",
            "minProperties": 1,
            "maxProperties": 1,
            "additionalProperties": {"$ref": "#/$defs/effects"},
            "description": "'Title: [effects]', for a step with no text",
        }
        return {"oneOf": [STEP.schema(), short]}


TRIGGER = f.Obj(
    "trigger",
    {
        "at": f.F(f.Str(description="The node the button hangs under"), required=True),
        "label": f.F(f.Str(description="The button's label"), required=True),
    },
    description="A button under a node that plays this scenario",
)

SCENARIO = f.Obj(
    "scenario",
    {
        "title": f.F(f.Str(description="Name in the player's scenario picker")),
        "trigger": f.F(TRIGGER),
        "loop": f.F(
            f.Bool(description="Replay forever; the first looping scenario starts on its own when the page loads")
        ),
        "ready": f.F(f.Str(description="Status line before the run")),
        "end": f.F(f.Str(description="Status line after the run")),
        "steps": f.F(f.List(StepT(), min_items=1), required=True),
    },
)

ACTIONS = f.MapOf(
    f.Raw({"$ref": "#/$defs/effects"}),
    description="Named lists of effects, called in a step's 'do' by their name",
)

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
        "groups": f.F(f.MapOf(f.Ref("group", lambda: GROUP))),
        "nodes": f.F(f.MapOf(NODE, min_items=1)),
        "edges": f.F(EDGES),
        "actions": f.F(
            f.MapOf(
                f.Raw({"$ref": "#/$defs/effects"}),
                description="Named lists of effects in the component's own ids, called with the instances they run "
                "on: 'pull a b' runs pull on instances a and b side by side",
            )
        ),
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
        "scenario": f.F(
            f.Str(
                description="Make it a dynamic view: show what this scenario uses, keep it, and number its edges "
                "by step"
            )
        ),
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
        "groups": f.F(f.MapOf(f.Ref("group", lambda: GROUP), key_pattern=REF, key_description=IDS)),
        "nodes": f.F(f.MapOf(NODE, min_items=1, key_pattern=REF, key_description=IDS)),
        "edges": f.F(EDGES),
        "components": f.F(f.MapOf(COMPONENT)),
        "instances": f.F(f.MapOf(INSTANCE)),
        "actions": f.F(ACTIONS),
        "scenarios": f.F(
            f.MapOf(SCENARIO, min_items=1, description="Scenarios by id; the first is the default and static output's")
        ),
        "step_list": f.F(f.Bool(description="Show numbered badges and the step list in static output (default true)")),
        "direction": f.F(f.Str(enum=("right", "down"), description="Which way automatically placed nodes flow")),
        "align": f.F(f.Bool(description="Line up the edges of sibling boxes that nearly line up (default true)")),
        "layout": f.F(LAYOUT),
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
        "$defs": {"effects": EFFECT_SCHEMA, "group": GROUP.schema()},
    }


def _moves(items: list[str]) -> list[Move]:
    out = []
    for s in items:
        m = re.fullmatch(MOVE, s)
        assert m
        out.append(Move(m.group(1), float(m.group(2)) if m.group(2) else None, "px" if m.group(3) else "cells"))
    return out


def _scenario(sid: str, sc: f.Rec, ctx: Ctx) -> Scenario:
    steps = []
    for s in sc.get("steps"):
        effects = parse_effects(s.get("do"), ctx) if s.get("do") is not None else []
        if s.get("focus"):
            loc = s.at("focus")
            effects = [Effect("focus", s.get("focus"), loc=loc), *effects, Effect("focus", ["none"], loc=loc)]
        steps.append(Step(s.get("title"), s.get("text", ""), s.get("at"), s.get("status"), effects, s.loc))
    return Scenario(
        steps, sc.get("ready", ""), sc.get("end", ""), sc.loc, sid, sc.get("title", ""), sc.get("loop", False)
    )


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
        behind={b.key: b.value for b in g.get("behind", [])},
        title_at=g.get("title_at", ""),
        flow=_flow(g.get("layout")),
        box=g.get("box", True),
        grow=g.get("grow", 0),
    )


def _flow(rec: f.Rec | None) -> Flow | None:
    if rec is None:
        return None
    return Flow(
        rec.get("direction", "column"), rec.get("gap", 24), rec.get("align", "center"), rec.get("justify", "start")
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
        junction=n.get("junction", False),
        cells=n.get("cells", []),
        stack=n.get("stack", 1),
        mark=n.get("mark"),
        hidden=n.get("hidden", False),
        tooltip=n.get("tooltip"),
        loc=e.loc,
        align_x=n.get("align_x"),
        align_y=n.get("align_y"),
    )


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


def _file_order(x: Group | Node) -> tuple[int, int]:
    return (x.loc.line, x.loc.col) if x.loc else (0, 0)


def held(groups: dict[str, Group], nodes: dict[str, Node], parent: str | None) -> list[list[Group] | list[Node]]:
    """What a box (or, with no parent, the diagram) holds, as its groups and its nodes, each in file order, the one
    written first first."""
    gs = sorted((g for g in groups.values() if g.parent == parent), key=_file_order)
    ns = sorted((n for n in nodes.values() if n.group == parent), key=_file_order)
    parts: list[list[Group] | list[Node]] = [p for p in (gs, ns) if p]
    return sorted(parts, key=lambda p: _file_order(p[0]))


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
        ids = [name or f"{src.node}->{dst.node}" for src, dst, _, _ in made]
        for eid, (src, dst, dashed, twin), val in zip(
            ids, made, v if isinstance(v, list) else [v] * len(made), strict=True
        ):
            if eid in out:
                problems.append(Problem(e.loc, f"edge '{eid}' is defined twice; give one an id with 'as <name>'"))
                continue
            out[eid] = Edge(
                id=eid,
                src=src,
                dst=dst,
                label=val.get("label", ""),
                route=_moves(val.get("route")) if val.get("route") is not None else None,
                via=val.get("via"),
                dashed=val.get("dashed", dashed),
                mark=val.get("mark"),
                label_at=val.get("label_at"),
                hidden=val.get("hidden", False),
                tooltip=val.get("tooltip"),
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
        align=rec.get("align", True),
        flow=_flow(rec.get("layout")),
        base=base,
        file=file,
    )
    _boxes(rec.get("groups", []), rec.get("nodes", []), None, d.groups, d.nodes, problems)
    _edges(rec.get("edges", []), d.edges, problems)
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
    instances = {}
    for e in rec.get("instances", []):
        v = e.value
        values = {p.key: p.value for p in v.get("with", [])}
        instances[e.key] = Instance(e.key, v.get("component"), v.get("at") or (0, 0), v.get("in"), values, e.loc)
    expand(d, components, instances, problems)
    _tree_order(d)
    if not d.nodes:
        problems.append(Problem(rec.loc, "the diagram needs at least one node"))
        raise DiagramError(problems)
    _triggers(d, rec.get("scenarios") or [], problems)

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
    for e in rec.get("scenarios") or []:
        d.scenarios[e.key] = _scenario(e.key, e.value, ctx)
    d.component_actions = actions.check_all()
    _cell_names(d, problems)
    for e in rec.get("views") or []:
        v = e.value
        d.views[e.key] = View(
            e.key,
            v.get("title", ""),
            v.get("include"),
            v.get("exclude", []),
            v.get("scenarios", []),
            v.get("scenario"),
            e.loc,
        )
    problems += check_views(d)

    if problems:
        seen: set[tuple[object, str]] = set()
        unique = []
        for p in problems:
            # An action's body is parsed once for each instance it runs on; report each problem once.
            if (p.loc, p.message) not in seen:
                seen.add((p.loc, p.message))
                unique.append(p)
        raise DiagramError(unique)
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
