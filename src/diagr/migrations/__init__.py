"""Older versions of the diagram format, and how each is upgraded to the next.

A file says which version it is written in with `version: N`; a file without it is version 1. Before parsing,
`upgrade` runs the migrations from the file's version up to the current one, so the parser only ever sees the current
format and knows nothing about older ones.

Each version is a module `vN.py` holding a `Migration`: the list of changes from version N-1, declared with the
building blocks in `changes.py`, each with a summary and an example. A change only rewrites what version N rejects,
so a file written for version N without a `version` key passes through unchanged.

A breaking change to the format adds a module here and appends its migration to STEPS. That bumps VERSION; nothing
else changes.
"""

from __future__ import annotations

from ..source import DiagramError, Problem, Y, YMap, YScalar
from . import v2

STEPS = [v2.MIGRATION]
VERSION = len(STEPS) + 1
assert [m.version for m in STEPS] == list(range(2, VERSION + 1)), "STEPS must hold versions 2, 3, ... in order"


def _version(tree: YMap) -> int:
    for k, v in tree.pairs:
        if k.value != "version":
            continue
        if not isinstance(v, YScalar) or v.quoted or not v.value.isdigit() or not 1 <= int(v.value):
            raise DiagramError([Problem(v.loc, f"'version' is a whole number from 1 to {VERSION}")])
        if int(v.value) > VERSION:
            raise DiagramError(
                [Problem(v.loc, f"version {v.value} is newer than this diagr, which reads up to version {VERSION}")]
            )
        return int(v.value)
    return 1


def upgrade(tree: Y) -> tuple[Y, list[Problem]]:
    """The tree in the current version, and a warning for each rewrite."""
    if not isinstance(tree, YMap):
        return tree, []
    problems: list[Problem] = []
    for migration in STEPS[_version(tree) - 1 :]:
        migration.up(tree, problems)
    if any(p.level == "error" for p in problems):
        raise DiagramError(problems)
    value = YScalar(tree.loc, str(VERSION), False, False)
    tree.pairs = [(k, v) for k, v in tree.pairs if k.value != "version"]
    tree.pairs.insert(0, (YScalar(tree.loc, "version", False, False), value))
    return tree, problems
