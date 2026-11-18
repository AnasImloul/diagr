"""The diagram format: what each key may hold, which model field it fills, and how its value is read and written
back. Adding a key to a group, node or edge is one line here plus the model field it fills: `parse` builds the model
from these declarations, `unparse` writes it back with them, and they make the JSON Schema."""

from __future__ import annotations

import re
from typing import Any

from . import fields as f
from .effects import EFFECT_SCHEMA
from .migrations import VERSION
from .model import Flow, Move
from .source import YMap, YScalar, YSeq

ID = f.ID
REF = rf"{ID}(?:/{ID})?"
PARAM_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
IDS = "an id: letters, digits, _ and - (not last), optionally 'instance/id' as `diagr expand` writes"
SIDE = r"left|right|top|bottom"
PORT = rf"({REF})(?:@({SIDE})([+-]\d+(?:\.\d+)?)?)?"
# PORT with its groups made non-capturing, to sit inside the edge key pattern.
_PORT = re.sub(r"\((?!\?)", "(?:", PORT)
_END = rf"(?:{_PORT}|\(\s*{_PORT}(?:\s+{_PORT})*\s*\))"
ARROW = r"<->|-->|->"
EDGE_KEY = rf"{_END}(?:\s*(?:{ARROW})\s*{_END})+(?:\s+as\s+{REF})?"
MOVE = r"(up|down|left|right)(?:\s+(\d+(?:\.\d+)?)(px)?)?"
MARKS = ("new", "removed", "changed")
LAYERS = ("first", "last")
LAYER = "Placed automatically: first or last, to go before or after everything else in the box it is in"
# How far apart the two edges of a pair 'a <-> b' run, either side of the middle, in px.
PAIR_GAP = 10


def num(v: float) -> float | int:
    return int(v) if float(v).is_integer() else round(v, 6)


def pair(p: tuple[float, float]) -> list[float | int]:
    return [num(p[0]), num(p[1])]


def moves(items: list[str]) -> list[Move]:
    out = []
    for s in items:
        m = re.fullmatch(MOVE, s)
        assert m
        out.append(Move(m.group(1), float(m.group(2)) if m.group(2) else None, "px" if m.group(3) else "cells"))
    return out


def move_text(m: Move) -> str:
    if m.length is None:
        return m.dir
    return f"{m.dir} {num(m.length)}" + ("px" if m.unit == "px" else "")


def layout_flow(rec: f.Rec | None) -> Flow | None:
    if rec is None:
        return None
    return Flow(
        rec.get("direction", "column"), rec.get("gap", 24), rec.get("align", "center"), rec.get("justify", "start")
    )


def layout_data(fl: Flow) -> dict[str, Any] | str:
    out: dict[str, Any] = {"direction": fl.direction}
    if fl.gap != 24:
        out["gap"] = num(fl.gap)
    if fl.align != "center":
        out["align"] = fl.align
    if fl.justify != "start":
        out["justify"] = fl.justify
    return fl.direction if list(out) == ["direction"] else out


def lines_data(lines: list[str]) -> str | list[str]:
    return lines[0] if len(lines) == 1 else list(lines)


def cells_data(cells: list[str]) -> int | list[str]:
    return len(cells) if not any(cells) else list(cells)


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
        "at": f.F(f.Pair(description="Top-left cell [col, row]; default: fit the member nodes and groups"), write=pair),
        "span": f.F(f.Pair(minimum=1, description="Size in cells [cols, rows]"), write=pair),
        "title_at": f.F(
            f.Str(
                enum=TITLE_AT,
                description="Where the title goes: bottom-left (default), top-left (default for a stack), "
                "top or bottom (centred along that edge), or middle: a heading beside the box's nodes, sub below",
            )
        ),
        "layout": f.F(LAYOUT, attr="flow", read=layout_flow, write=layout_data),
        "box": f.F(f.Bool(description="false: draw no box or title; the group only arranges what it holds")),
        "layer": f.F(f.Str(enum=LAYERS, description=LAYER)),
        "grow": f.F(
            f.Num(minimum=0, description="In a box with layout: this group's share of the space left over (default 0)"),
            write=num,
        ),
        "behind": f.F(
            f.MapOf(
                f.Str(),
                key_pattern=REF,
                key_description=IDS,
                description="Boxes stacked behind this one, nearest first, as id: title; edges can end at them",
            ),
            read=lambda entries: {b.key: b.value for b in entries},
            write=dict,
        ),
    },
    description="A titled, tinted container around nodes and other groups",
)

NODE = f.Obj(
    "node",
    {
        "at": f.F(
            f.Pair(description="Grid cell [col, row]; fractions allowed; default: placed automatically"), write=pair
        ),
        "title": f.F(f.Str()),
        "sub": f.F(f.Lines(description="Muted text under the title"), write=lines_data),
        "icon": f.F(f.Str(description="Icon name from the diagram's icon folders or the core set")),
        "tone": f.F(f.Str(description="Tile colour for generated icons")),
        "junction": f.F(f.Bool(description="A dot where edges meet (a bus); has no icon or text")),
        "align_x": f.F(f.Str(description="A node to line up with, one above the other: same x")),
        "align_y": f.F(f.Str(description="A node to line up with, side by side: same y")),
        "layer": f.F(f.Str(enum=LAYERS, description=LAYER)),
        "cells": f.F(Cells(), write=cells_data),
        "stack": f.F(f.Num(integer=True, minimum=1, description="Draw the icon as a stack of N")),
        "mark": f.F(f.Str(enum=MARKS)),
        "hidden": f.F(f.Bool(description="Start hidden; a scenario can show it")),
        "tooltip": f.F(f.Str()),
    },
    shorthand=f.Str(description="The title"),
    shorthand_field="title",
    empty=True,
    description="A node: icon, title and sub text, centred on a grid cell; its title, or nothing",
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
            ),
            read=moves,
            write=lambda ms: [move_text(m) for m in ms],
        ),
        "via": f.F(
            f.List(f.Pair(), description="Explicit waypoints in grid cells (escape hatch)"),
            write=lambda vs: [pair(v) for v in vs],
        ),
        "dashed": f.F(f.Bool()),
        "constraint": f.F(f.Bool(description="false: drawn, but left out when placing nodes automatically")),
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
                    if isinstance(item, YSeq):
                        self._fail(item, problems, "a list here holds one label or mapping per edge, not another list")
                    out.append(self.check(item, problems))
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
    """A step: its title as the key, with its effects under it, or a mapping of its other fields."""

    def kind(self) -> str:
        return "a step: 'Title: [effects]', or 'Title:' with 'at', 'text', 'status', 'focus' and 'do' under it"

    def check(self, y, problems):
        if not isinstance(y, YMap) or len(y.pairs) != 1:
            return self._fail(y, problems)
        k, v = y.pairs[0]
        if isinstance(v, YSeq):
            rec = f.Rec(y.loc, {"do": v}, {"do": v.loc})
        elif isinstance(v, YScalar) and v.null:
            rec = f.Rec(y.loc, {}, {})
        else:
            rec = STEP.check(v, problems)
        rec.values["title"], rec.locs["title"] = k.value, k.loc
        return rec

    def schema(self):
        return {
            "type": "object",
            "minProperties": 1,
            "maxProperties": 1,
            "additionalProperties": {"oneOf": [{"$ref": "#/$defs/effects"}, STEP.schema(), {"type": "null"}]},
            "description": "A step: its title, with its effects or its other fields under it",
        }


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
                description="Text parameters, used as $name in titles, sub text, labels, tooltips and triggers",
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
        "version": f.F(
            f.Num(
                integer=True,
                minimum=1,
                maximum=VERSION,
                description=f"Format version the file is written in; default 1. The current one is {VERSION}",
            )
        ),
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
        "scenario": f.F(SCENARIO),
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
