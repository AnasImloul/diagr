from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any

import yaml

from .model import Loc

# Built once: data() reads a plain YAML value for every scalar of a file.
_RESOLVER = yaml.resolver.Resolver()
_CONSTRUCTOR = yaml.constructor.SafeConstructor()


@dataclass
class Problem:
    loc: Loc | None
    message: str
    level: str = "error"

    def __str__(self) -> str:
        where = f"{self.loc}: " if self.loc else ""
        return f"{where}{self.level}: {self.message}"


def did_you_mean(name: str, options) -> str:
    """', did you mean 'x'?' for the closest option, or nothing."""
    close = difflib.get_close_matches(name, list(options), n=1, cutoff=0.6)
    return f", did you mean '{close[0]}'?" if close else ""


class DiagramError(Exception):
    def __init__(self, problems: list[Problem]):
        self.problems = problems
        super().__init__("\n".join(str(p) for p in problems))


@dataclass
class Y:
    loc: Loc


@dataclass
class YScalar(Y):
    value: str
    quoted: bool
    null: bool


@dataclass
class YSeq(Y):
    items: list[Y]


@dataclass
class YMap(Y):
    pairs: list[tuple[YScalar, Y]]

    def keys(self) -> list[str]:
        return [k.value for k, _ in self.pairs]


def data(y: Y) -> Any:
    """The tree as plain YAML data, as yaml.safe_load gives it."""
    if isinstance(y, YMap):
        return {k.value: data(v) for k, v in y.pairs}
    if isinstance(y, YSeq):
        return [data(i) for i in y.items]
    assert isinstance(y, YScalar)
    tag = "tag:yaml.org,2002:str" if y.quoted else _RESOLVER.resolve(yaml.ScalarNode, y.value, (True, False))
    # The tag's own constructor, called directly: construct_object would keep every node it has seen.
    return _CONSTRUCTOR.yaml_constructors[tag](_CONSTRUCTOR, yaml.ScalarNode(tag, y.value))


def _loc(file: str, node: yaml.Node) -> Loc:
    return Loc(file, node.start_mark.line + 1, node.start_mark.column + 1)


def _convert(file: str, node: yaml.Node, problems: list[Problem]) -> Y:
    loc = _loc(file, node)
    if isinstance(node, yaml.ScalarNode):
        null = node.tag == "tag:yaml.org,2002:null" and node.style is None
        return YScalar(loc, node.value, node.style is not None, null)
    if isinstance(node, yaml.SequenceNode):
        return YSeq(loc, [_convert(file, n, problems) for n in node.value])
    if isinstance(node, yaml.MappingNode):
        pairs: list[tuple[YScalar, Y]] = []
        seen: dict[str, Loc] = {}
        for k, v in node.value:
            key = _convert(file, k, problems)
            if not isinstance(key, YScalar):
                problems.append(Problem(key.loc, "keys must be plain text"))
                continue
            if key.value in seen:
                first = seen[key.value].line
                problems.append(Problem(key.loc, f"duplicate key '{key.value}' (first defined at line {first})"))
                continue
            seen[key.value] = key.loc
            pairs.append((key, _convert(file, v, problems)))
        return YMap(loc, pairs)
    raise TypeError(node)


def load(text: str, file: str) -> Y:
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        loc = Loc(file, mark.line + 1, mark.column + 1) if mark else None
        raise DiagramError([Problem(loc, f"YAML: {e.problem or e.context}")]) from None
    if node is None:
        raise DiagramError([Problem(Loc(file, 1, 1), "file is empty")])
    problems: list[Problem] = []
    tree = _convert(file, node, problems)
    if problems:
        raise DiagramError(problems)
    return tree
