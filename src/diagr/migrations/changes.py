"""The building blocks of a migration step: where in the YAML tree to look, and what to change there.

A step lists its changes; this module walks the tree, rewrites it and reports. Every change keeps the line numbers of
what it moves, and reports each rewrite as a warning that starts with the version and the change's summary, so the
author sees what to edit.

Where to look:

- `Each("nodes.*")` is every entry of the top-level `nodes`; `*` is every entry of a mapping or item of a list, and
  "" is the whole file. `nested="groups.*"` reaches inside nesting: it may repeat any number of times before the
  path's last two parts, so `Each("nodes.*", nested="groups.*")` is every node, inside groups too.
- `Effects("scenarios.*.steps.*.do")` is every effect in those lists, inside `parallel` and `repeat` too.

Text patterns, in `Rewrite` and `RewriteKey`, read like the syntax they match:

    "set {target} [{duration}]: {text}"

`{name}` is a placeholder and `[...]` an optional part. What a placeholder matches depends on its name: `{duration}`
is a duration like 300ms or 2s, `{count}` a whole number, `{text}` the rest of the line, `{plain_text}` the rest of a
line without a colon, with surrounding quotes dropped, `{rest}` the rest of the line, and any other name one word
without a colon. In the replacement, a placeholder puts back what it matched, and an optional part whose placeholders
matched nothing is left out.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import KW_ONLY, dataclass, field

from ..source import Problem, Y, YMap, YScalar, YSeq, did_you_mean

# Placeholder name -> what it matches, and how the match is cleaned up.
KINDS: dict[str, tuple[str, Callable[[str], str]]] = {
    "duration": (r"\d+(?:\.\d+)?(?:ms|s)", str),
    "count": (r"\d+", str),
    "text": (r".*", str.strip),
    "plain_text": (r"[^:]*", lambda s: s.strip().strip('"')),
    "rest": (r".+", str.strip),
}
WORD = (r"[^\s:]+", str)


# Places in the tree.


class Spot:
    """One place in the tree: an entry of a mapping, an item of a list, or the whole file."""

    def __init__(self, parent: YMap | YSeq | None, ref: YScalar | int | Y):
        self.parent, self.ref = parent, ref

    @property
    def key(self) -> str:
        return self.ref.value if isinstance(self.ref, YScalar) else ""

    @property
    def value(self) -> Y:
        if isinstance(self.parent, YMap):
            return next(v for k, v in self.parent.pairs if k is self.ref)
        if isinstance(self.parent, YSeq):
            assert isinstance(self.ref, int)
            return self.parent.items[self.ref]
        assert isinstance(self.ref, Y)
        return self.ref

    def replace(self, y: Y) -> None:
        if isinstance(self.parent, YMap):
            self.parent.pairs = [(k, y if k is self.ref else v) for k, v in self.parent.pairs]
        elif isinstance(self.parent, YSeq):
            assert isinstance(self.ref, int)
            self.parent.items[self.ref] = y

    def remove(self) -> None:
        assert isinstance(self.parent, YMap)
        self.parent.pairs = [(k, v) for k, v in self.parent.pairs if k is not self.ref]

    def children(self) -> list[Spot]:
        v = self.value
        if isinstance(v, YMap):
            return [Spot(v, k) for k, _ in v.pairs]
        if isinstance(v, YSeq):
            return [Spot(v, i) for i in range(len(v.items))]
        return []


def _follow(spots: list[Spot], path: list[str]) -> list[Spot]:
    for part in path:
        spots = [c for s in spots for c in s.children() if part == "*" or c.key == part]
    return spots


class Each:
    """The places at these dotted paths; see the module's docstring."""

    def __init__(self, *paths: str, nested: str = ""):
        self.paths, self.nested = paths, nested

    def spots(self, tree: Y) -> list[Spot]:
        out = []
        for path in self.paths:
            parts = path.split(".") if path else []
            head, tail = (parts[:-2], parts[-2:]) if self.nested else (parts, [])
            reached = frontier = _follow([Spot(None, tree)], head)
            while self.nested and frontier:
                frontier = _follow(frontier, self.nested.split("."))
                reached = reached + frontier
            out += _follow(reached, tail)
        return out


class Effects:
    """Every effect in the lists at these paths, and inside them: in a list of effects, in a mapping whose value is a
    list (`parallel: [...]`, `repeat 3: [...]`) and in the `do` of `{repeat: 3, do: [...]}`."""

    def __init__(self, *paths: str):
        self.paths = paths

    def spots(self, tree: Y) -> list[Spot]:
        out: list[Spot] = []

        def visit(y: Y) -> None:
            if not isinstance(y, YSeq):
                return
            for i, item in enumerate(y.items):
                out.append(Spot(y, i))
                if isinstance(item, YSeq):
                    visit(item)
                elif isinstance(item, YMap):
                    for _, v in item.pairs:
                        visit(v)

        for s in Each(*self.paths).spots(tree):
            visit(s.value)
        return out


@dataclass
class Has:
    """Whether the file has anything at one of these paths."""

    paths: tuple[str, ...]

    def __init__(self, *paths: str):
        self.paths = paths

    def __call__(self, tree: Y) -> bool:
        return bool(Each(*self.paths).spots(tree))


@dataclass
class FirstKey:
    """The first key of the mapping at this path, as a default."""

    path: str

    def __call__(self, tree: Y) -> str | None:
        found = Each(self.path + ".*").spots(tree)
        return found[0].key if found else None


# Text patterns.

_PART = re.compile(r"\[[^\]]*\]|\{\w+\}|:|\s+|[^\[\]{}:\s]+")


def _regex(pattern: str) -> str:
    parts = _PART.findall(pattern)
    out: list[str] = []
    i = 0
    while i < len(parts):
        part, after = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        if part.isspace() and after.startswith("["):
            # The space before an optional part is part of it.
            out.append(rf"(?:\s+{_regex(after[1:-1])})?")
            i += 2
            continue
        if part.isspace():
            out.append(r"\s*" if out and out[-1] == r"\s*:" else r"\s+")
        elif part == ":":
            out.append(r"\s*:")
        elif part.startswith("["):
            out.append(rf"(?:{_regex(part[1:-1])})?")
        elif part.startswith("{"):
            out.append(rf"(?P<{part[1:-1]}>{KINDS.get(part[1:-1], WORD)[0]})")
        else:
            out.append(re.escape(part))
        i += 1
    return "".join(out)


def _match(pattern: str, text: str) -> dict[str, str] | None:
    m = re.fullmatch(_regex(pattern), text.strip())
    if m is None:
        return None
    return {k: KINDS.get(k, WORD)[1](v) for k, v in m.groupdict().items() if v is not None}


def _render(template: str, values: dict[str, str]) -> str:
    def optional(m: re.Match[str]) -> str:
        names = re.findall(r"\{(\w+)\}", m.group(2))
        return m.group(1) + m.group(2) if all(values.get(n) for n in names) else ""

    text = re.sub(r"(\s*)\[([^\]]*)\]", optional, template)
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), ""), text)


# Small tree helpers.


def _get(m: Y | None, key: str) -> Y | None:
    if isinstance(m, YMap):
        for k, v in m.pairs:
            if k.value == key:
                return v
    return None


def _pop(m: YMap, key: str) -> Y | None:
    v = _get(m, key)
    m.pairs = [(k, x) for k, x in m.pairs if k.value != key]
    return v


def _word(y: Y, text: str) -> YScalar:
    return YScalar(y.loc, text, False, False)


def _text(y: Y, text: str) -> YScalar:
    return YScalar(y.loc, text, True, False)


def _show(y: Y) -> str:
    """A short form of y for a warning."""
    if isinstance(y, YMap):
        return ", ".join(f"{k.value}: {_show(v)}" for k, v in y.pairs)
    if isinstance(y, YSeq):
        return "[...]"
    return y.value if isinstance(y, YScalar) else ""


def _fill(template: str, found: dict[str, Y], at: Y) -> Y:
    """A value for the template: what a placeholder matched when it is all there is, else text."""
    whole = re.fullmatch(r"\{(\w+)\}", template)
    if whole and whole.group(1) in found:
        return found[whole.group(1)]
    texts = {k: v.value for k, v in found.items() if isinstance(v, YScalar)}
    return _text(at, _render(template, texts))


# Changes.


@dataclass
class Report:
    version: int
    summary: str
    problems: list[Problem]

    def _say(self, y: Y, what: str, level: str) -> None:
        summary = self.summary[0].lower() + self.summary[1:]
        self.problems.append(Problem(y.loc, f"version {self.version}: {summary}: {what}", level))

    def rewrote(self, y: Y, what: str) -> None:
        self._say(y, what, "warning")

    def cannot(self, y: Y, why: str) -> None:
        self._say(y, why, "error")


@dataclass
class Change:
    """One change from the previous version. `before` and `after` are an example of it, which the tests run."""

    summary: str
    _: KW_ONLY
    before: str = ""
    after: str = ""

    def apply(self, tree: YMap, report: Report) -> None:
        raise NotImplementedError


@dataclass(kw_only=True)
class Nest(Change):
    """In each mapping `within`, moves each entry of `sections` that names its group with `key` into that group's
    own section of the same name."""

    key: str
    sections: list[str]
    within: Each

    def apply(self, tree: YMap, report: Report) -> None:
        for box in self.within.spots(tree):
            here = box.value
            if not isinstance(here, YMap):
                continue
            groups = {s.key: s.value for s in Each("groups.*", nested="groups.*").spots(here)}
            for section in self.sections:
                what = section.removesuffix("s")
                top = _get(here, section)
                moved = False
                for entry in Each(section + ".*").spots(here):
                    owner = _pop(entry.value, self.key) if isinstance(entry.value, YMap) else None
                    if owner is None:
                        continue
                    name = owner.value if isinstance(owner, YScalar) else ""
                    group = groups.get(name)
                    if not isinstance(group, YMap):
                        hint = did_you_mean(name, groups)
                        report.cannot(owner, f"{what} '{entry.key}' is in unknown group '{name}'{hint}")
                        continue
                    inside = [s.value for s in Each("groups.*", nested="groups.*").spots(entry.value)]
                    if group is entry.value or any(g is group for g in inside):
                        report.cannot(owner, f"group '{entry.key}' is inside itself through '{self.key}'")
                        continue
                    value = entry.value
                    entry.remove()
                    held = _get(group, section)
                    if not isinstance(held, YMap):
                        held = YMap(group.loc, [])
                        _pop(group, section)
                        group.pairs.append((_word(group, section), held))
                    assert isinstance(entry.ref, YScalar)
                    held.pairs.append((entry.ref, value))
                    moved = True
                    report.rewrote(owner, f"move {what} '{entry.key}' into group '{name}', without '{self.key}'")
                # A section the moves emptied goes, as an empty one is rejected; one written empty stays.
                if moved and isinstance(top, YMap) and not top.pairs:
                    _pop(here, section)


@dataclass(kw_only=True)
class MoveTo(Change):
    """For each entry at `each` that has the key `when`, takes the keys in `take` off it and writes `value` at the
    path `to`. In `to` and `value`, `{key}` is the entry's own key and `{name}` what the taken key `name` held;
    `defaults` fills a taken key the entry leaves out."""

    each: Each
    when: str
    take: list[str]
    to: str
    value: dict[str, str]
    defaults: dict[str, FirstKey] = field(default_factory=dict)

    def apply(self, tree: YMap, report: Report) -> None:
        for entry in self.each.spots(tree):
            if not isinstance(entry.value, YMap) or _get(entry.value, self.when) is None:
                continue
            here = entry.value
            assert isinstance(entry.ref, YScalar)
            found: dict[str, Y] = {"key": _text(entry.ref, entry.key)}
            for name in self.take:
                y = _pop(here, name)
                if y is None and name in self.defaults and (default := self.defaults[name](tree)):
                    y = _text(here, default)
                if y is not None:
                    found[name] = y
            at = found[self.when]
            path = _render(self.to, {k: v.value for k, v in found.items() if isinstance(v, YScalar)})
            *parent_path, last = path.split(".")
            parent = next((s.value for s in Each(".".join(parent_path)).spots(tree)), None)
            if not isinstance(parent, YMap):
                report.cannot(at, f"there is no '{'.'.join(parent_path)}' to move it to")
                continue
            if _get(parent, last) is not None:
                report.cannot(at, f"'{path}' is already set")
                continue
            moved = YMap(at.loc, [(_word(at, k), _fill(v, found, at)) for k, v in self.value.items()])
            parent.pairs.append((_word(at, last), moved))
            report.rewrote(at, f"write '{path}: {{{_show(moved)}}}'")


@dataclass(kw_only=True)
class Drop(Change):
    """Takes `key` off each entry at `each` that has it."""

    each: Each
    key: str

    def apply(self, tree: YMap, report: Report) -> None:
        for entry in self.each.spots(tree):
            if isinstance(entry.value, YMap) and (y := _pop(entry.value, self.key)) is not None:
                report.rewrote(y, f"delete '{self.key}'")


@dataclass(kw_only=True)
class Forbid(Change):
    """Stops the upgrade where an entry at `each` has `key`, as there is nothing it can be rewritten as. `fix` says
    what to write instead; `{key}` in it is the entry's own key."""

    each: Each
    key: str
    fix: str

    def apply(self, tree: YMap, report: Report) -> None:
        for entry in self.each.spots(tree):
            if (y := _get(entry.value, self.key)) is not None:
                report.cannot(y, self.fix.replace("{key}", entry.key))


@dataclass(kw_only=True)
class Reshape(Change):
    """Rewrites each mapping at `each` with exactly the keys of `match` into `into`. `match` says what each key
    holds, as a placeholder; `into` puts those back, in its keys as text."""

    each: Each | Effects
    match: dict[str, str]
    into: dict[str, str]

    def apply(self, tree: YMap, report: Report) -> None:
        for spot in self.each.spots(tree):
            y = spot.value
            if not isinstance(y, YMap) or sorted(y.keys()) != sorted(self.match):
                continue
            found = {self.match[k.value][1:-1]: v for k, v in y.pairs}
            if any(
                isinstance(v, YScalar) and name in KINDS and _match("{" + name + "}", v.value) is None
                for name, v in found.items()
            ):
                continue
            texts = {k: v.value for k, v in found.items() if isinstance(v, YScalar)}
            new = YMap(y.loc, [(_word(y, _render(k, texts)), _fill(v, found, y)) for k, v in self.into.items()])
            spot.replace(new)
            report.rewrote(y, f"write '{_show(new)}'")


@dataclass(kw_only=True)
class Rewrite(Change):
    """Rewrites each text at `each` that matches the pattern `match` into `into`: a pattern for text, or a mapping of
    them for a mapping. Nothing is rewritten when `unless` holds for the file."""

    each: Each | Effects
    match: str
    into: str | dict[str, str]
    unless: Has | None = None

    def apply(self, tree: YMap, report: Report) -> None:
        if self.unless and self.unless(tree):
            return
        for spot in self.each.spots(tree):
            y = spot.value
            if not isinstance(y, YScalar) or y.null or (found := _match(self.match, y.value)) is None:
                continue
            if isinstance(self.into, str):
                new: Y = _text(y, _render(self.into, found))
            else:
                pairs: list[tuple[YScalar, Y]] = [
                    (_word(y, _render(k, found)), _text(y, _render(v, found))) for k, v in self.into.items()
                ]
                new = YMap(y.loc, pairs)
            spot.replace(new)
            report.rewrote(y, f"write '{_show(new)}'")


@dataclass(kw_only=True)
class RewriteKey(Change):
    """Rewrites the key of each one-key mapping at `each` that matches the pattern `match` into `into`. Nothing is
    rewritten when `unless` holds for the file."""

    each: Each | Effects
    match: str
    into: str
    unless: Has | None = None

    def apply(self, tree: YMap, report: Report) -> None:
        if self.unless and self.unless(tree):
            return
        for spot in self.each.spots(tree):
            y = spot.value
            if not isinstance(y, YMap) or len(y.pairs) != 1:
                continue
            k, v = y.pairs[0]
            if (found := _match(self.match, k.value)) is None:
                continue
            new = YMap(y.loc, [(_word(k, _render(self.into, found)), v)])
            spot.replace(new)
            report.rewrote(y, f"write '{_show(new)}'")


@dataclass
class Migration:
    """One version of the format, as the changes from the version before it."""

    version: int
    changes: list[Change]

    def up(self, tree: YMap, problems: list[Problem]) -> None:
        for change in self.changes:
            change.apply(tree, Report(self.version, change.summary, problems))
