"""Versions of the diagram format, and how an older one is upgraded to the current one.

A file says which version it is written in with `version: N`; a file without it is version 1. Before parsing,
`upgrade` rewrites an older file into the current version, so the parser only ever sees the current format and knows
nothing about older ones, and it warns at each place it changed.

Version 1 is the only one so far, so there is nothing to rewrite yet. A breaking change to the format makes the next
version: it adds a module here with the changes from the one before, and `upgrade` runs it on older files.
"""

from __future__ import annotations

from ..source import DiagramError, Problem, Y, YMap, YScalar

VERSION = 1


def _version(tree: YMap) -> int:
    for k, v in tree.pairs:
        if k.value != "version":
            continue
        if not isinstance(v, YScalar) or v.quoted or not v.value.isdigit() or not 1 <= int(v.value):
            raise DiagramError([Problem(v.loc, f"'version' is a whole number; the current one is {VERSION}")])
        if int(v.value) > VERSION:
            raise DiagramError(
                [Problem(v.loc, f"version {v.value} is newer than this diagr, which reads up to version {VERSION}")]
            )
        return int(v.value)
    return 1


def upgrade(tree: Y) -> tuple[Y, list[Problem]]:
    """The tree in the current version, with its version written in, and a warning for each rewrite."""
    if not isinstance(tree, YMap):
        return tree, []
    _version(tree)
    value = YScalar(tree.loc, str(VERSION), False, False)
    tree.pairs = [(k, v) for k, v in tree.pairs if k.value != "version"]
    tree.pairs.insert(0, (YScalar(tree.loc, "version", False, False), value))
    return tree, []
