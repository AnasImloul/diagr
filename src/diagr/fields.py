"""Type descriptors that both check a YAML tree (with line numbers) and emit the JSON Schema."""

from __future__ import annotations

import difflib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .model import Loc
from .source import Problem, Y, YMap, YScalar, YSeq


class Invalid(Exception):
    pass


@dataclass
class Rec:
    loc: Loc
    values: dict[str, Any]
    locs: dict[str, Loc]

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def at(self, name: str) -> Loc:
        return self.locs.get(name, self.loc)


@dataclass
class Entry:
    key: str
    loc: Loc
    value: Any


class T:
    description: str = ""

    def check(self, y: Y, problems: list[Problem]) -> Any:
        raise NotImplementedError

    def schema(self) -> dict:
        raise NotImplementedError

    def kind(self) -> str:
        return "a value"

    def _fail(self, y: Y, problems: list[Problem], message: str | None = None) -> Any:
        problems.append(Problem(y.loc, message or f"expected {self.kind()}"))
        raise Invalid


def _too_few(n: int) -> str:
    return "must not be empty" if n == 1 else f"needs at least {n} items"


def _describe(s: dict, description: str) -> dict:
    if description:
        s["description"] = description
    return s


@dataclass
class Str(T):
    description: str = ""
    enum: tuple[str, ...] | None = None
    pattern: str | None = None

    def kind(self) -> str:
        return "one of " + ", ".join(self.enum) if self.enum else "text"

    def check(self, y, problems):
        if not isinstance(y, YScalar) or y.null:
            return self._fail(y, problems)
        if self.enum and y.value not in self.enum:
            return self._fail(y, problems, f"'{y.value}' is not {self.kind()}")
        if self.pattern and not re.fullmatch(self.pattern, y.value):
            return self._fail(y, problems, f"'{y.value}' is not valid here ({self.description or self.pattern})")
        return y.value

    def schema(self):
        s: dict = {"type": "string"}
        if self.enum:
            s["enum"] = list(self.enum)
        if self.pattern:
            s["pattern"] = f"^(?:{self.pattern})$"
        return _describe(s, self.description)


@dataclass
class Num(T):
    description: str = ""
    integer: bool = False
    minimum: float | None = None
    maximum: float | None = None

    def kind(self) -> str:
        return "a whole number" if self.integer else "a number"

    def check(self, y, problems):
        if not isinstance(y, YScalar) or y.quoted:
            return self._fail(y, problems)
        try:
            v = int(y.value) if self.integer else float(y.value)
        except ValueError:
            return self._fail(y, problems, f"'{y.value}' is not {self.kind()}")
        if not math.isfinite(v):
            return self._fail(y, problems, f"'{y.value}' is not {self.kind()}")
        if self.minimum is not None and v < self.minimum:
            return self._fail(y, problems, f"must be at least {self.minimum:g}")
        if self.maximum is not None and v > self.maximum:
            return self._fail(y, problems, f"must be at most {self.maximum:g}")
        return v

    def schema(self):
        s: dict = {"type": "integer" if self.integer else "number"}
        if self.minimum is not None:
            s["minimum"] = self.minimum
        if self.maximum is not None:
            s["maximum"] = self.maximum
        return _describe(s, self.description)


@dataclass
class Bool(T):
    description: str = ""

    def kind(self) -> str:
        return "true or false"

    def check(self, y, problems):
        if isinstance(y, YScalar) and not y.quoted and y.value in ("true", "false"):
            return y.value == "true"
        return self._fail(y, problems)

    def schema(self):
        return _describe({"type": "boolean"}, self.description)


@dataclass
class Pair(T):
    description: str = ""
    minimum: float | None = None

    def kind(self) -> str:
        return "a pair like [2, 1]"

    def check(self, y, problems):
        if not isinstance(y, YSeq) or len(y.items) != 2:
            return self._fail(y, problems)
        a, b = (Num(minimum=self.minimum).check(i, problems) for i in y.items)
        return (a, b)

    def schema(self):
        return _describe(
            {"type": "array", "items": Num(minimum=self.minimum).schema(), "minItems": 2, "maxItems": 2},
            self.description,
        )


@dataclass
class List(T):
    item: T
    description: str = ""
    min_items: int = 0

    def kind(self) -> str:
        return "a list"

    def check(self, y, problems):
        if not isinstance(y, YSeq):
            return self._fail(y, problems)
        if len(y.items) < self.min_items:
            return self._fail(y, problems, _too_few(self.min_items))
        out, bad = [], False
        for i in y.items:
            try:
                out.append(self.item.check(i, problems))
            except Invalid:
                bad = True
        if bad:
            raise Invalid
        return out

    def schema(self):
        s: dict = {"type": "array", "items": self.item.schema()}
        if self.min_items:
            s["minItems"] = self.min_items
        return _describe(s, self.description)


@dataclass
class Lines(T):
    description: str = ""

    def kind(self) -> str:
        return "text or a list of lines"

    def check(self, y, problems):
        if isinstance(y, YSeq):
            return List(Str()).check(y, problems)
        return [Str().check(y, problems)]

    def schema(self):
        return _describe(
            {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}, self.description
        )


@dataclass
class Raw(T):
    """Passed through unchecked; the caller parses it (effects)."""

    json: dict = field(default_factory=dict)
    description: str = ""

    def check(self, y, problems):
        return y

    def schema(self):
        return _describe(dict(self.json), self.description)


@dataclass
class Ref(T):
    """A type defined once in the schema's $defs, so it can hold itself (a group inside a group)."""

    name: str
    target: Callable[[], T]

    def kind(self) -> str:
        return self.target().kind()

    def check(self, y, problems):
        return self.target().check(y, problems)

    def schema(self):
        return {"$ref": f"#/$defs/{self.name}"}


@dataclass
class F:
    type: T
    required: bool = False


@dataclass
class Obj(T):
    name: str
    fields: dict[str, F]
    description: str = ""
    shorthand: T | None = None
    shorthand_field: str | None = None

    def kind(self) -> str:
        return "a mapping"

    def check(self, y, problems):
        if self.shorthand and self.shorthand_field and not isinstance(y, YMap):
            v = self.shorthand.check(y, problems)
            return Rec(y.loc, {self.shorthand_field: v}, {self.shorthand_field: y.loc})
        if not isinstance(y, YMap):
            return self._fail(y, problems)
        values, locs, bad = {}, {}, False
        for k, v in y.pairs:
            spec = self.fields.get(k.value)
            if spec is None:
                close = difflib.get_close_matches(k.value, self.fields, n=1)
                hint = f", did you mean '{close[0]}'?" if close else ""
                problems.append(Problem(k.loc, f"unknown key '{k.value}' in {self.name}{hint}"))
                bad = True
                continue
            try:
                values[k.value] = spec.type.check(v, problems)
                locs[k.value] = v.loc
            except Invalid:
                bad = True
        for name, spec in self.fields.items():
            if spec.required and name not in values and not bad:
                problems.append(Problem(y.loc, f"{self.name} needs '{name}'"))
                bad = True
        if bad:
            raise Invalid
        return Rec(y.loc, values, locs)

    def schema(self):
        s: dict = {
            "type": "object",
            "properties": {k: f.type.schema() for k, f in self.fields.items()},
            "additionalProperties": False,
        }
        req = [k for k, f in self.fields.items() if f.required]
        if req:
            s["required"] = req
        if self.shorthand:
            s = {"oneOf": [self.shorthand.schema(), s]}
        return _describe(s, self.description)


@dataclass
class MapOf(T):
    value: T
    key_pattern: str = r"[A-Za-z_][A-Za-z0-9_-]*"
    key_description: str = "an id: letters, digits, _ and -"
    description: str = ""
    min_items: int = 0

    def kind(self) -> str:
        return "a mapping"

    def check(self, y, problems):
        if not isinstance(y, YMap):
            return self._fail(y, problems)
        if len(y.pairs) < self.min_items:
            return self._fail(y, problems, _too_few(self.min_items))
        out, bad = [], False
        for k, v in y.pairs:
            if not re.fullmatch(self.key_pattern, k.value):
                problems.append(Problem(k.loc, f"'{k.value}' is not {self.key_description}"))
                bad = True
                continue
            try:
                out.append(Entry(k.value, k.loc, self.value.check(v, problems)))
            except Invalid:
                bad = True
        if bad:
            raise Invalid
        return out

    def schema(self):
        s: dict = {
            "type": "object",
            "propertyNames": {"pattern": f"^(?:{self.key_pattern})$"},
            "additionalProperties": self.value.schema(),
        }
        if self.min_items:
            s["minProperties"] = self.min_items
        return _describe(s, self.description)


def check(t: T, y: Y, problems: list[Problem]) -> Any:
    try:
        return t.check(y, problems)
    except Invalid:
        return None
