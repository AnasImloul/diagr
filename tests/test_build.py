from __future__ import annotations

import contextlib
import io
import textwrap
import unittest

from diagr import prepare
from diagr.cli import main
from diagr.parse import from_tree
from diagr.render.svg import render_static
from diagr.source import load
from tests.support import ROOT, Case

BASE = """
diagram: t
nodes:
  a: {at: [0, 0], icon: server, title: A}
  b: {at: [1, 0], icon: database, title: B}
edges:
  a -> b: writes
"""


def prepared(yml: str, theme: str | None = None, base=ROOT):
    return prepare(from_tree(load(textwrap.dedent(yml), "t.yml"), "t.yml", base), theme)


def cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as e:
            code = int(e.code or 0)
    return code, out.getvalue(), err.getvalue()


class Layout(Case):
    def test_ports_follow_the_theme_icon_size(self):
        base = self.tmp()
        (base / "big.yml").write_text("extends: default\nsizes: {icon: 80}\n", encoding="utf-8")
        p = prepared(BASE + "theme: ./big.yml\n", base=base)
        a = p.layout.nodes["a"]
        self.assertEqual(a.port("right"), (a.x + 44, a.y))
        self.assertEqual(a.port("top"), (a.x, a.y - 44))


class Render(Case):
    def test_removed_edge_is_faded_and_red(self):
        p = prepared(BASE.replace("a -> b: writes", "a -> b: {label: writes, mark: removed}"))
        svg = render_static(p.scene(), p.theme, "light")
        self.assertIn('data-mark="removed" opacity=".45"', svg)
        self.assertIn(f'stroke="{p.theme.hex("light", "fail")}"', svg)

    def test_hidden_elements_are_left_out_of_static_svg(self):
        yml = BASE.replace("title: B}", "title: B, hidden: true}").replace("a -> b: writes", "a -> b: {hidden: true}")
        svg = render_static(prepared(yml).scene(), prepared(yml).theme, "light")
        self.assertNotIn('data-id="b"', svg)
        self.assertNotIn('data-id="a->b"', svg)


class Cli(Case):
    def test_version(self):
        code, out, _ = cli("--version")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("diagr "))

    def test_missing_file_is_an_error_not_a_traceback(self):
        code, _, err = cli("check", "nope.yml")
        self.assertEqual(code, 1)
        self.assertIn("cannot read nope.yml", err)

    def test_directory_is_an_error_not_a_traceback(self):
        code, _, err = cli("check", str(self.tmp()))
        self.assertEqual(code, 1)
        self.assertIn("cannot read", err)

    def test_bad_theme_override(self):
        code, _, err = cli("check", str(ROOT / "examples/order-flow/diagram.yml"), "--theme", str(ROOT / "README.md"))
        self.assertEqual(code, 1)
        self.assertIn("error:", err)

    def test_check_ok(self):
        code, out, _ = cli("check", "--strict", str(ROOT / "examples/order-flow/diagram.yml"))
        self.assertEqual(code, 0)
        self.assertIn(": ok", out)

    def test_build_refuses_two_files_with_one_id(self):
        base = self.tmp()
        for name in ("one.yml", "two.yml"):
            (base / name).write_text(textwrap.dedent(BASE), encoding="utf-8")
        code, out, err = cli("build", str(base / "one.yml"), str(base / "two.yml"), "-o", str(base / "out"))
        self.assertEqual(code, 1)
        self.assertIn("diagram id 't' is also used by", err)
        self.assertEqual(sorted(p.name for p in (base / "out").iterdir()), ["t-dark.svg", "t-light.svg", "t.html"])

    def test_build_writes_three_files(self):
        out = self.tmp()
        code, stdout, _ = cli("build", str(ROOT / "examples/order-flow/diagram.yml"), "-o", str(out))
        self.assertEqual(code, 0)
        self.assertEqual(len(stdout.splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
