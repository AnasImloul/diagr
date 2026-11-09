from __future__ import annotations

import contextlib
import io
import json
import re
import textwrap
import unittest

from diagr import prepare
from diagr.cli import STARTER, _watched, main
from diagr.parse import from_tree
from diagr.render.html import render_html
from diagr.render.svg import render_static
from diagr.source import load
from diagr.theme import BUILTIN, theme_files
from tests.support import ROOT, Case

BASE = """
id: t
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


class Buttons(Case):
    def test_long_trigger_label_widens_the_button(self):
        short = prepared(BASE.replace("title: A}", "title: A, trigger: Run}")).layout.nodes["a"].button
        long = (
            prepared(BASE.replace("title: A}", "title: A, trigger: Send a very long request}")).layout.nodes["a"].button
        )
        assert short and long
        self.assertEqual(short.w, 132)
        self.assertGreater(long.w, 132)
        self.assertAlmostEqual(long.x + long.w / 2, 0)


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


class Watch(Case):
    def test_watches_the_whole_extends_chain(self):
        base = self.tmp()
        (base / "a.yml").write_text("extends: ./b.yml\n", encoding="utf-8")
        (base / "b.yml").write_text("extends: default\n", encoding="utf-8")
        (base / "d.yml").write_text(textwrap.dedent(BASE) + "theme: ./a.yml\n", encoding="utf-8")
        files = _watched(base / "d.yml", None)
        self.assertIn((base / "a.yml").resolve(), files)
        self.assertIn((base / "b.yml").resolve(), files)
        self.assertIn(BUILTIN / "default.yml", files)

    def test_keeps_watching_a_broken_theme(self):
        base = self.tmp()
        (base / "a.yml").write_text("extends: ./b.yml\n", encoding="utf-8")
        (base / "b.yml").write_text("light: [\n", encoding="utf-8")
        self.assertEqual(theme_files("./a.yml", base), [(base / "a.yml").resolve(), (base / "b.yml").resolve()])

    def test_theme_override(self):
        base = self.tmp()
        (base / "t.yml").write_text("extends: default\n", encoding="utf-8")
        (base / "d.yml").write_text(textwrap.dedent(BASE), encoding="utf-8")
        self.assertIn((base / "t.yml").resolve(), _watched(base / "d.yml", str(base / "t.yml")))


class Authoring(Case):
    def test_debug_overlay_only_when_asked(self):
        p = prepared(BASE)
        self.assertNotIn("dg-debug", render_html(p))
        html = render_html(p, debug=True)
        self.assertIn('class="dg-debug"', html)
        self.assertIn("a [0, 0]", html)
        self.assertIn("a-&gt;b: point 1 of 2", html)

    def test_contrast_switch_unless_already_contrast(self):
        html = render_html(prepared(BASE))
        self.assertIn('id="contrast"', html)
        self.assertIn(':root[data-contrast="on"][data-theme="dark"] { --bg: #010409;', html)
        self.assertNotIn('id="contrast"', render_html(prepared(BASE, theme="contrast")))

    def test_every_page_can_zoom(self):
        html = render_html(prepared(BASE))
        self.assertIn('<div class="stage"><svg class="diagr"', html)
        self.assertIn('data-zoom="fit"', html)
        self.assertIn('data-zoom="full"', html)
        self.assertIn("window.diagrZoom", html)

    def test_live_script_only_when_serving(self):
        p = prepared(BASE)
        self.assertNotIn("/__diagr/version", render_html(p))
        self.assertIn("/__diagr/version", render_html(p, live=True))

    def test_live_server(self):
        import urllib.request

        from diagr.live import LiveServer

        folder = self.tmp()
        (folder / "x.html").write_text("hi", encoding="utf-8")
        server = LiveServer(folder, 0)
        self.addCleanup(server.close)
        base = f"http://127.0.0.1:{server.port}"
        with urllib.request.urlopen(base + "/__diagr/version") as r:
            self.assertEqual(r.read(), b"0")
            self.assertEqual(r.headers["Cache-Control"], "no-store")
        server.bump()
        with urllib.request.urlopen(base + "/__diagr/version") as r:
            self.assertEqual(r.read(), b"1")
        with urllib.request.urlopen(base + "/x.html") as r:
            self.assertEqual(r.read(), b"hi")


class Accessibility(Case):
    def test_svg_with_triggers_is_a_group(self):
        html = render_html(
            prepared(
                BASE.replace("title: A}", "title: A, trigger: Run}")
                + "scenarios:\n  s:\n    steps:\n    - {title: go, do: [done a]}\n"
            )
        )
        self.assertIn('role="group"', html)
        self.assertIn('role="button"', html)

    def test_svg_without_triggers_is_an_image(self):
        self.assertIn('role="img"', render_html(prepared(BASE)))

    def test_steps_are_buttons(self):
        html = render_html(prepared(BASE + "scenarios:\n  s:\n    steps:\n    - {title: go, do: [done a]}\n"))
        self.assertIn('<button type="button" aria-label="Step 1: go">go</button>', html)


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

    def test_check_json(self):
        base = self.tmp()
        (base / "bad.yml").write_text("id: t\nnodes:\n  a: {at: [0, 0], icon: nope}\n", encoding="utf-8")
        code, out, err = cli(
            "check", "--format", "json", str(base / "bad.yml"), str(ROOT / "examples/order-flow/diagram.yml")
        )
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        found = json.loads(out)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["line"], 3)
        self.assertEqual(found[0]["level"], "error")
        self.assertIn("icon 'nope' not found", found[0]["message"])

    def test_check_json_clean(self):
        code, out, _ = cli("check", "--format", "json", str(ROOT / "examples/order-flow/diagram.yml"))
        self.assertEqual((code, json.loads(out)), (0, []))

    def test_icons_lists_core(self):
        code, out, _ = cli("icons")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^server\s+tile\s+core$")

    def test_icons_includes_the_diagram_folders(self):
        base = self.tmp()
        (base / "icons").mkdir()
        (base / "icons" / "icons.yml").write_text("tiles:\n  mine: {tone: blue, glyph: '<path/>'}\n", encoding="utf-8")
        (base / "d.yml").write_text(
            "id: t\nicons: [./icons]\nnodes:\n  a: {at: [0, 0], icon: mine}\n", encoding="utf-8"
        )
        code, out, _ = cli("icons", str(base / "d.yml"))
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^mine\s+tile\s+.*icons$")

    def test_init_writes_a_clean_diagram(self):
        path = self.tmp() / "my flow" / "diagram.yml"
        code, _, _ = cli("init", str(path))
        self.assertEqual(code, 0)
        self.assertIn("id: my-flow\n", path.read_text(encoding="utf-8"))
        self.assertEqual(cli("check", "--strict", str(path))[0], 0)

    def test_init_takes_an_id(self):
        path = self.tmp() / "x.yml"
        cli("init", str(path), "--id", "orders")
        self.assertIn("id: orders\n", path.read_text(encoding="utf-8"))

    def test_init_never_overwrites(self):
        path = self.tmp() / "x.yml"
        path.write_text("mine", encoding="utf-8")
        code, _, err = cli("init", str(path))
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertEqual(path.read_text(encoding="utf-8"), "mine")

    def test_readme_shows_the_starter(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        block = re.search(r"```yaml\n(.*?)```", readme, re.S)
        assert block
        self.assertEqual(block.group(1), STARTER.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
