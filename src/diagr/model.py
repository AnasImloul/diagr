from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
    views: dict[str, View] = field(default_factory=dict)
    base: Path = field(default_factory=Path.cwd)
    file: str = "<memory>"

    @staticmethod
    def from_yaml(path: str | Path) -> Diagram:
        from .parse import load_file

        return load_file(path)
