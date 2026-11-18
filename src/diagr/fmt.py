"""`diagr fmt`: lines up a diagram file into columns without touching anything else.

It works on lines, not on parsed YAML, so comments, quoting and blank lines stay as they are. Two kinds of runs of
sibling lines, each run unbroken by a blank line, a comment or a line of another kind, are lined up:

- one-line mappings, `key: {a: 1, b: 2}`, such as nodes: the values start in one column, and so does each item
  whose key is the same in every line from the first item on;
- edges, `a -> b: label`, the lines under `edges:`: arrows start in one column, and so do the labels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ARROW = re.compile(r"\s*(<->|-->|->)\s*")
KEY = re.compile(r"(\s*)([A-Za-z_][\w/-]*):\s+(\{.*)")


@dataclass
class _Row:
    indent: str
    key: str
    items: list[str]
    tail: str


@dataclass
class _Edge:
    indent: str
    first: str
    rest: str
    value: str
    tail: str


def _scan(text: str, start: int) -> tuple[int, list[int]] | None:
    """The end of the flow collection opening at start, and the top-level commas inside it."""
    depth, commas, k = 0, [], start
    while k < len(text):
        c = text[k]
        if c in "\"'":
            end = text.find(c, k + 1)
            if end < 0:
                return None
            k = end
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return k + 1, commas
        elif c == "," and depth == 1:
            commas.append(k)
        k += 1
    return None


def _comment(text: str) -> int:
    """Where a comment starts in a line's text, outside quotes, or its length."""
    k = 0
    while k < len(text):
        c = text[k]
        if c in "\"'":
            end = text.find(c, k + 1)
            k = end if end >= 0 else len(text)
        elif c == "#" and (k == 0 or text[k - 1].isspace()):
            return k - 1 if k else 0
        k += 1
    return len(text)


def _tail(rest: str) -> str | None:
    """What may follow a value on its line: nothing, or a comment."""
    if not rest.strip():
        return ""
    if rest.lstrip().startswith("#") and rest[:1].isspace():
        return rest
    return None


def _row(line: str) -> _Row | None:
    m = KEY.fullmatch(line)
    if not m:
        return None
    indent, key, value = m.groups()
    found = _scan(value, 0)
    if not found:
        return None
    end, commas = found
    tail = _tail(value[end:])
    if tail is None:
        return None
    items = []
    start = 1
    for comma in [*commas, end - 1]:
        items.append(value[start:comma].strip())
        start = comma + 1
    if not all(items):
        return None
    return _Row(indent, key, items, tail)


def _edge(line: str) -> _Edge | None:
    stripped = line.lstrip()
    if not stripped or stripped[0] in "#\"'-":
        return None
    indent = line[: len(line) - len(stripped)]
    m = re.fullmatch(r"(.*?):(?:(\s+)(.*))?", stripped)
    if not m or not ARROW.search(m.group(1)):
        return None
    key, value = m.group(1), m.group(3) or ""
    tail = ""
    if value.startswith(("{", "[")):
        found = _scan(value, 0)
        if not found:
            return None
        tail = _tail(value[found[0] :])
        if tail is None:
            return None
        value = value[: found[0]]
    else:
        cut = _comment(value)
        value, tail = value[:cut].rstrip(), value[cut:]
    first, arrow, rest = ARROW.split(key, maxsplit=1)
    rest = ARROW.sub(lambda a: f" {a.group(1)} ", rest).strip()
    return _Edge(indent, first.strip(), f"{arrow} {rest}", value.strip(), tail)


def _rows(run: list[_Row]) -> list[str]:
    width = max(len(r.key) for r in run) + 1
    # The width of each place, item and comma, while every line with an item after it has the same key there.
    cols: list[int] = []
    for j in range(max(len(r.items) for r in run) - 1):
        have = [r for r in run if len(r.items) > j + 1]
        if len(have) < 2 or len({r.items[j].split(":", 1)[0] for r in have}) != 1:
            break
        cols.append(max(len(r.items[j]) for r in have) + 1)
    out = []
    for r in run:
        inner = ""
        for j, item in enumerate(r.items):
            if j == len(r.items) - 1:
                inner += item
            elif j < len(cols):
                inner += (item + ",").ljust(cols[j] + 1)
            else:
                inner += item + ", "
        out.append(f"{r.indent}{(r.key + ':').ljust(width)} {{{inner}}}{r.tail}")
    return out


# A key this much longer than the shortest labelled one is not lined up with, so one long chain does not push every
# label in the run to the right; its own label follows it after one space.
REACH = 16


def _edges(run: list[_Edge]) -> list[str]:
    first = max(len(e.first) for e in run)
    keys = [f"{e.first.ljust(first)} {e.rest}:" for e in run]
    labelled = [len(k) for k, e in zip(keys, run, strict=True) if e.value]
    width = max((n for n in labelled if n <= min(labelled) + REACH), default=0)
    return [
        f"{e.indent}{k.ljust(width) if e.value else k}{' ' + e.value if e.value else ''}{e.tail}"
        for k, e in zip(keys, run, strict=True)
    ]


def _under_edges(lines: list[str], i: int) -> bool:
    """Whether line i sits directly in an 'edges:' block."""
    indent = len(lines[i]) - len(lines[i].lstrip())
    for k in range(i - 1, -1, -1):
        s = lines[k].strip()
        if not s or s.startswith("#"):
            continue
        d = len(lines[k]) - len(lines[k].lstrip())
        if d < indent:
            return s == "edges:"
        if d > indent:
            continue
    return False


def format_text(text: str) -> str:
    """The text with its runs of one-line mappings and edges lined up."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        edge = _edge(lines[i]) if _under_edges(lines, i) else None
        if edge:
            run = [edge]
            while i + len(run) < len(lines):
                nxt = _edge(lines[i + len(run)])
                if not nxt or nxt.indent != edge.indent:
                    break
                run.append(nxt)
            out += _edges(run) if len(run) > 1 else [lines[i]]
            i += len(run)
            continue
        row = _row(lines[i])
        if row:
            run = [row]
            while i + len(run) < len(lines):
                nxt = _row(lines[i + len(run)])
                if not nxt or nxt.indent != row.indent:
                    break
                run.append(nxt)
            out += _rows(run) if len(run) > 1 else [lines[i]]
            i += len(run)
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)
