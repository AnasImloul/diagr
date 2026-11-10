"""Older versions of the diagram format, and how each is upgraded to the next.

A file says which version it is written in with `version: N`; a file without it is version 1. Before parsing,
`upgrade` runs the steps from the file's version up to the current one, so the parser only ever sees the current
format and knows nothing about older ones.

Each step is a module `vN.py` with `up(tree, problems)`, which rewrites a version N-1 tree into version N in place.
It works on the YAML tree, so what it moves keeps its line numbers, and it reports each rewrite as a warning, so the
author can update the file. A step only rewrites what version N rejects: a file written for version N without a
`version` key passes through it unchanged.

A breaking change to the format adds a step here and appends it to STEPS. That bumps VERSION; nothing else changes.
"""

from __future__ import annotations

from ..source import DiagramError, Problem, Y, YMap, YScalar
from . import v2

STEPS = [v2.up]
VERSION = len(STEPS) + 1


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
    for step in STEPS[_version(tree) - 1 :]:
        step(tree, problems)
    if any(p.level == "error" for p in problems):
        raise DiagramError(problems)
    value = YScalar(tree.loc, str(VERSION), False, False)
    tree.pairs = [(k, v) for k, v in tree.pairs if k.value != "version"]
    tree.pairs.insert(0, (YScalar(tree.loc, "version", False, False), value))
    return tree, problems
