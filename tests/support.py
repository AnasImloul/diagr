from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from diagr import DiagramError, Problem, prepare
from diagr.parse import from_tree
from diagr.source import load

ROOT = Path(__file__).resolve().parent.parent


def problems(yml: str, base: Path | None = None, theme: str | None = None) -> list[Problem]:
    """Every problem diagr reports for a diagram given as YAML text: errors, or the warnings of a clean build."""
    text = textwrap.dedent(yml)
    try:
        d = from_tree(load(text, "t.yml"), "t.yml", base or ROOT)
        return prepare(d, theme).warnings
    except DiagramError as e:
        return e.problems


class Case(unittest.TestCase):
    def tmp(self) -> Path:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return Path(d.name)

    def assertReports(self, found: list[Problem], text: str, level: str | None = None) -> None:
        hits = [p for p in found if text in p.message and (level is None or p.level == level)]
        if not hits:
            self.fail(f"no {level or 'problem'} containing {text!r}; got:\n" + "\n".join(map(str, found)))

    def assertClean(self, found: list[Problem]) -> None:
        if found:
            self.fail("expected no problems; got:\n" + "\n".join(map(str, found)))
