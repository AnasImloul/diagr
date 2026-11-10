from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Loc:
    file: str
    line: int
    col: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.col}"


@dataclass
class Grid:
    col: float = 215
    row: float = 160


@dataclass
class Flow:
    """How a box (or the diagram) arranges what it holds, like CSS flexbox: in a row or a column, in file order."""

    direction: str = "column"
    gap: float = 24
    align: str = "center"
    justify: str = "start"


@dataclass
class Group:
    id: str
    title: str
    sub: str = ""
    icon: str | None = None
    tone: str = "neutral"
    at: tuple[float, float] | None = None
    span: tuple[float, float] | None = None
    loc: Loc | None = None
    parent: str | None = None
    # Boxes stacked behind this one, nearest first: id -> title. Edges can end at them like at any box.
    behind: dict[str, str] = field(default_factory=dict)
    # Where the title goes: bottom-left, top-left, top or bottom; "" is bottom-left, or top-left for a stack.
    title_at: str = ""
    # Arrange the group's nodes and child groups in a row or column instead of by their cells.
    flow: Flow | None = None
    # False for a group that only arranges what it holds: no box or title is drawn.
    box: bool = True
    # In a box with `layout`: the share of the leftover space along its direction this group takes, like flex-grow.
    grow: float = 0


@dataclass
class Node:
    id: str
    at: tuple[float, float] | None
    title: str = ""
    sub: list[str] = field(default_factory=list)
    icon: str | None = None
    tone: str | None = None
    group: str | None = None
    junction: bool = False
    trigger: str | None = None
    cells: list[str] = field(default_factory=list)
    stack: int = 1
    mark: str | None = None
    hidden: bool = False
    tooltip: str | None = None
    loc: Loc | None = None
    plays: str | None = None
    auto: bool = False
    # Line the node up with another node, wherever each is: same x (one above the other) or same y (side by side).
    align_x: str | None = None
    align_y: str | None = None


@dataclass
class Port:
    node: str
    side: str | None = None
    offset: float = 0.0


@dataclass
class Move:
    dir: str
    length: float | None = None
    unit: str = "cells"


@dataclass
class Edge:
    id: str
    src: Port
    dst: Port
    label: str = ""
    route: list[Move] | None = None
    via: list[tuple[float, float]] | None = None
    dashed: bool = False
    mark: str | None = None
    label_at: float | None = None
    hidden: bool = False
    tooltip: str | None = None
    loc: Loc | None = None
    # The edge going back the other way, for a pair written 'a <-> b'.
    twin: str | None = None


@dataclass
class Hop:
    """One stop on a flow path: a node or box, or several side by side, and how long its nodes stay active."""

    ids: list[str]
    ms: float | None = None


@dataclass
class Effect:
    verb: str
    targets: list[str] = field(default_factory=list)
    text: str | None = None
    ms: float | None = None
    range: tuple[int, int] | None = None
    range_names: tuple[str, str] | None = None
    children: list[Effect] = field(default_factory=list)
    count: int = 1
    loc: Loc | None = None
    hops: list[Hop] = field(default_factory=list)
    # A flow written '... -> c done' finishes its last stop.
    finish: bool = False

    def links(self) -> list[tuple[str, str]]:
        """For a flow, the (from, to) of each edge it follows: every stop to every stop after it."""
        return [(a, b) for h, after in zip(self.hops, self.hops[1:], strict=False) for a in h.ids for b in after.ids]


@dataclass
class Step:
    title: str
    text: str = ""
    at: str | None = None
    status: str | None = None
    effects: list[Effect] = field(default_factory=list)
    loc: Loc | None = None


@dataclass
class Scenario:
    steps: list[Step]
    ready: str = ""
    end: str = ""
    loc: Loc | None = None
    id: str = ""
    title: str = ""
    loop: bool = False


@dataclass
class Component:
    id: str
    params: dict[str, str | None] = field(default_factory=dict)
    groups: dict[str, Group] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    loc: Loc | None = None
    # Action name -> its effects as written, in the component's own ids; parsed for each instance.
    actions: dict[str, Any] = field(default_factory=dict)


@dataclass
class Instance:
    id: str
    component: str
    at: tuple[float, float] = (0, 0)
    parent: str | None = None
    values: dict[str, str] = field(default_factory=dict)
    loc: Loc | None = None


@dataclass
class View:
    id: str
    title: str = ""
    include: list[str] | None = None
    exclude: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)
    scenario: str | None = None
    loc: Loc | None = None


@dataclass
class Diagram:
    id: str
    title: str = ""
    description: str = ""
    theme: str = "default"
    icons: list[str] = field(default_factory=list)
    grid: Grid = field(default_factory=Grid)
    groups: dict[str, Group] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    scenarios: dict[str, Scenario] = field(default_factory=dict)
    step_list: bool = True
    direction: str = "right"
    align: bool = True
    flow: Flow | None = None
    views: dict[str, View] = field(default_factory=dict)
    # Edge id -> the step numbers its badge shows, for a dynamic view: "2" or "2,5".
    numbers: dict[str, str] = field(default_factory=dict)
    # Instance id -> action name -> what the action does on that instance, for `diagr expand`.
    component_actions: dict[str, dict[str, Effect]] = field(default_factory=dict)
    base: Path = field(default_factory=Path.cwd)
    file: str = "<memory>"
