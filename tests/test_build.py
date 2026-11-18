from __future__ import annotations

import contextlib
import io
import json
import re
import textwrap
import unittest
from pathlib import Path

from diagr import DiagramError, build_files, prepare
from diagr.cli import _claim, _watched, main
from diagr.parse import loads
from diagr.render.html import render_html
from diagr.render.svg import render_static
from diagr.theme import BUILTIN, theme_files
from tests.support import ROOT, Case

BASE = """
nodes:
  a: {at: [0, 0], icon: server, title: A}
  b: {at: [1, 0], icon: database, title: B}
edges:
  a -> b: writes
"""


def prepared(yml: str, theme: str | None = None, base=ROOT):
    return prepare(loads(textwrap.dedent(yml), "t.yml", base), theme)


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


def triggered(label: str) -> str:
    return (
        BASE
        + f"scenarios:\n  s:\n    trigger: {{at: a, label: {label}}}\n    steps:\n    - {{title: go, do: [done a]}}\n"
    )


class Buttons(Case):
    def test_long_trigger_label_widens_the_button(self):
        short = prepared(triggered("Run")).layout.nodes["a"].button
        long = prepared(triggered("Send a very long request")).layout.nodes["a"].button
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


GROUPED = """
groups:
  g:
    title: G
    nodes:
      a: {at: [0, 0], icon: server, title: A}
      b: {at: [1, 0], icon: database, title: B}
edges:
  a -> b: writes
"""


class Transparent(Case):
    def test_default_has_the_theme_background(self):
        p = prepared(BASE)
        svg = render_static(p.scene(), p.theme, "dark")
        self.assertIn(f'fill="{p.theme.hex("dark", "bg")}"', svg)
        self.assertNotIn("<mask", svg)

    def test_leaves_out_the_background_and_cuts_the_edge_under_a_label(self):
        p = prepared(BASE)
        svg = render_static(p.scene(), p.theme, "dark", transparent=True)
        self.assertNotIn(f'fill="{p.theme.hex("dark", "bg")}"', svg)
        self.assertIn('<mask id="t-labels" maskUnits="userSpaceOnUse"', svg)
        self.assertIn('fill="black"', svg)
        self.assertRegex(svg, r'<g class="edge"[^>]* mask="url\(#t-labels\)"')
        self.assertIn(">writes</text>", svg)

    def test_label_in_a_group_keeps_its_pill(self):
        p = prepared(GROUPED)
        svg = render_static(p.scene(), p.theme, "dark", transparent=True)
        self.assertNotIn("<mask", svg)
        self.assertIn(f'rx="4" fill="{p.theme.hex("dark", "tone-neutral-fill")}"', svg)

    def test_row_of_cells_shows_what_is_behind_it(self):
        p = prepared(BASE.replace("title: A}", "title: A, cells: [x, y]}"))
        bg = p.theme.hex("dark", "bg")
        self.assertRegex(render_static(p.scene(), p.theme, "dark"), rf'<rect class="cellbox"[^>]* fill="{bg}"')
        svg = render_static(p.scene(), p.theme, "dark", transparent=True)
        self.assertRegex(svg, r'<rect class="cellbox"[^>]* fill="none"')
        self.assertNotIn(f'fill="{bg}"', svg)

    def test_cli_flag(self):
        out = self.tmp()
        code, _, _ = cli(
            "build", "--svg", "--html", str(ROOT / "examples/order-flow/diagram.yml"), "-o", str(out), "--transparent"
        )
        self.assertEqual(code, 0)
        self.assertIn("<mask", (out / "order-flow-dark.svg").read_text(encoding="utf-8"))
        self.assertNotIn("<mask", (out / "order-flow.html").read_text(encoding="utf-8"))


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
        self.assertIn('<div class="stage" tabindex="0" role="group" aria-label="t, diagram"><svg class="diagr"', html)
        self.assertIn('data-zoom="fit"', html)
        self.assertIn('data-zoom="full"', html)
        self.assertIn("window.diagrZoom", html)

    def test_live_script_only_when_serving(self):
        p = prepared(BASE)
        self.assertNotIn("/__diagr/version", render_html(p))
        self.assertIn("/__diagr/version", render_html(p, live=True))

    def test_live_server(self):
        import urllib.error
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
        (folder / "sub").mkdir()
        for path, headers, code in (("/x.html", {"Host": "evil.example"}, 403), ("/sub/", {}, 404)):
            with self.subTest(path=path, headers=headers):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(urllib.request.Request(base + path, headers=headers))
                self.assertEqual(caught.exception.code, code)
                caught.exception.close()


class Escaping(Case):
    def with_icon(self, name: str, text: str, icon: str) -> str:
        base = self.tmp()
        (base / "icons").mkdir()
        (base / "icons" / name).write_text(text, encoding="utf-8")
        yml = f"icons: [./icons]\nnodes:\n  a: {{at: [0, 0], icon: {icon}, title: A}}\n"
        return render_html(prepared(yml, base=base))

    def test_comment_in_a_tile_glyph_is_dropped(self):
        # HTML ends this comment at '<!-->', where XML does not, so inlining it as written would run the <img>.
        glyph = '<path d="M0 0"/><!--><img src=x onerror="alert(1)">-->'
        html = self.with_icon("icons.yml", f"tiles:\n  x: {{tone: blue, glyph: '{glyph}'}}\n", "x")
        self.assertIn('<path d="M0 0"/>', html)
        self.assertNotIn("onerror", html)

    def test_processing_instruction_in_an_svg_icon_is_dropped(self):
        # HTML ends a processing instruction at the first '>', so the <img> inside it would run.
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            '<?x > <img src=x onerror="alert(1)"> ?><rect width="64" height="64"/></svg>'
        )
        html = self.with_icon("x.svg", svg, "x")
        self.assertIn('<rect width="64" height="64"/>', html)
        self.assertNotIn("onerror", html)

    def test_text_cannot_end_the_player_data(self):
        # '<!--' then '<script' inside a script element makes the HTML parser swallow the player script after it.
        yml = BASE.replace("title: A", "title: '<!-- <script> A'") + (
            "scenarios:\n  s:\n    steps:\n    - {title: '<!-- <script> go', text: '</script>', do: [done a]}\n"
        )
        html = render_html(prepared(yml))
        data = re.search(r'<script type="application/json" id="diagr-data">(.*?)</script>', html, re.S)
        assert data
        self.assertNotIn("<", data.group(1))
        self.assertIn("<!-- <script> go", json.dumps(json.loads(data.group(1)), ensure_ascii=False))


class Accessibility(Case):
    def test_svg_with_triggers_is_a_group(self):
        html = render_html(prepared(triggered("Run")))
        self.assertIn('role="group"', html)
        self.assertIn('role="button"', html)

    def test_svg_without_triggers_is_an_image(self):
        self.assertIn('role="img"', render_html(prepared(BASE)))

    def test_static_svg_is_named_by_its_title_and_described_by_its_description(self):
        p = prepared(BASE + "title: Writes\ndescription: A writes to B.\n")
        svg = render_static(p.scene(), p.theme, "dark")
        self.assertIn('aria-labelledby="t-dark-title" aria-describedby="t-dark-desc"', svg)
        self.assertIn('<title id="t-dark-title">Writes</title>', svg)
        self.assertIn('<desc id="t-dark-desc">A writes to B.</desc>', svg)
        self.assertNotIn("aria-label=", svg.split(">", 1)[0])

    def test_shortcuts_only_act_inside_the_player(self):
        html = render_html(
            prepared(BASE + "scenarios:\n  s:\n    steps:\n    - {title: go, do: [done a]}\n"), debug=True
        )
        self.assertIn('<div class="stage" tabindex="0" role="group" aria-label="t, diagram">', html)
        # The player, zoom, contrast and debug keys each act only while focus is inside the player.
        page_keys = html.count('document.addEventListener("keydown"') + html.count(
            "document.addEventListener('keydown'"
        )
        scoped = html.count('e.target.closest(".wrap")') + html.count("e.target.closest('.wrap')")
        self.assertEqual(page_keys, 4)
        self.assertEqual(scoped, page_keys)

    def test_a_looping_scenario_is_not_read_out_until_the_reader_takes_over(self):
        html = render_html(
            prepared(BASE + "scenarios:\n  s:\n    loop: true\n    steps:\n    - {title: go, do: [done a]}\n")
        )
        self.assertIn('<div id="status" aria-live="polite">', html)
        self.assertIn('statusEl.setAttribute("aria-live", "off")', html)
        self.assertIn('wrap.addEventListener("keydown", listen, { once: true })', html)

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

    def test_build_refuses_two_files_with_one_name(self):
        base = self.tmp()
        for folder in ("one", "two"):
            (base / folder).mkdir()
            (base / folder / "t.yml").write_text(textwrap.dedent(BASE), encoding="utf-8")
        code, out, err = cli(
            "build",
            "--svg",
            "--html",
            str(base / "one" / "t.yml"),
            str(base / "two" / "t.yml"),
            "-o",
            str(base / "out"),
        )
        self.assertEqual(code, 1)
        self.assertIn("diagram 't' writes t.html and its SVGs, which diagram 't' in", err)
        self.assertEqual(sorted(p.name for p in (base / "out").iterdir()), ["t-dark.svg", "t-light.svg", "t.html"])

    def write(self, base, name: str, views: str = "") -> str:
        text = textwrap.dedent(BASE) + (f"views:\n{views}" if views else "")
        (base / f"{name}.yml").write_text(text, encoding="utf-8")
        return str(base / f"{name}.yml")

    def test_build_refuses_a_view_that_writes_another_diagrams_files(self):
        base = self.tmp()
        first = self.write(base, "shop-front")
        second = self.write(base, "shop", "  front: {include: [a]}\n")
        code, _, err = cli("build", "--svg", "--html", first, second, "-o", str(base / "out"))
        self.assertEqual(code, 1)
        self.assertIn(
            "shop.yml: view 'front' of 'shop' writes shop-front.html and its SVGs, which diagram 'shop-front' in", err
        )
        self.assertEqual(
            sorted(p.name for p in (base / "out").iterdir()),
            ["shop-front-dark.svg", "shop-front-light.svg", "shop-front.html"],
        )

    def test_build_refuses_two_views_with_one_name(self):
        base = self.tmp()
        first = self.write(base, "a", "  b-c: {include: [a]}\n")
        second = self.write(base, "a-b", "  c: {include: [a]}\n")
        code, _, err = cli("build", "--svg", "--html", first, second, "-o", str(base / "out"))
        self.assertEqual(code, 1)
        self.assertIn("view 'c' of 'a-b' writes a-b-c.html and its SVGs, which view 'b-c' of 'a' in", err)

    def test_watch_claims_names_again_on_each_rebuild(self):
        base = self.tmp()
        names: dict[str, tuple[str, str]] = {}
        shop = self.write(base, "shop", "  front: {include: [a]}\n")
        _claim(names, "shop.yml", loads(Path(shop).read_text(encoding="utf-8"), shop, base))
        other = self.write(base, "shop-front")
        with self.assertRaises(DiagramError):
            _claim(names, "other.yml", loads(Path(other).read_text(encoding="utf-8"), other, base))
        # shop.yml drops its view: the name is free again.
        shop = self.write(base, "shop")
        _claim(names, "shop.yml", loads(Path(shop).read_text(encoding="utf-8"), shop, base))
        _claim(names, "other.yml", loads(Path(other).read_text(encoding="utf-8"), other, base))
        self.assertEqual(names["shop-front"][0], "other.yml")

    def test_build_writes_what_it_is_asked_for(self):
        order = str(ROOT / "examples/order-flow/diagram.yml")
        for switches, names in (
            (["--light"], ["order-flow-light.svg"]),
            (["--dark"], ["order-flow-dark.svg"]),
            (["--svg"], ["order-flow-dark.svg", "order-flow-light.svg"]),
            (["--html"], ["order-flow.html"]),
            (["--light", "--html"], ["order-flow-light.svg", "order-flow.html"]),
            (["--svg", "--html"], ["order-flow-dark.svg", "order-flow-light.svg", "order-flow.html"]),
        ):
            with self.subTest(switches=switches):
                out = self.tmp()
                code, stdout, _ = cli("build", *switches, order, "-o", str(out))
                self.assertEqual(code, 0)
                self.assertEqual(sorted(p.name for p in out.iterdir()), names)
                self.assertEqual(len(stdout.splitlines()), len(names))

    def test_views_follow_the_choice(self):
        out = self.tmp()
        code, _, _ = cli("build", "--html", str(ROOT / "examples/data-platform/diagram.yml"), "-o", str(out))
        self.assertEqual(code, 0)
        self.assertEqual(
            sorted(p.name for p in out.iterdir()),
            ["data-platform-ingestion.html", "data-platform-serving.html", "data-platform.html"],
        )

    def test_build_needs_to_be_told_what_to_write(self):
        out = self.tmp()
        code, _, err = cli("build", str(ROOT / "examples/order-flow/diagram.yml"), "-o", str(out))
        self.assertEqual(code, 2)
        self.assertIn("say what to build: --light, --dark, --svg or --html", err)
        self.assertFalse(out.exists() and any(out.iterdir()))

    def test_options_for_files_not_being_written_warn(self):
        order = str(ROOT / "examples/order-flow/diagram.yml")
        _, _, err = cli("build", "--html", "--transparent", order, "-o", str(self.tmp()))
        self.assertIn("--transparent only changes the SVGs", err)
        _, _, err = cli("build", "--svg", "--debug", order, "-o", str(self.tmp()))
        self.assertIn("--debug only changes the HTML page", err)

    def test_unknown_output_in_python(self):
        with self.assertRaisesRegex(ValueError, "unknown output png; outputs are light, dark, html"):
            build_files(ROOT / "examples/order-flow/diagram.yml", self.tmp(), outputs=["png"])

    def test_check_json(self):
        base = self.tmp()
        (base / "bad.yml").write_text("nodes:\n  a: {at: [0, 0], icon: nope}\n", encoding="utf-8")
        code, out, err = cli(
            "check", "--format", "json", str(base / "bad.yml"), str(ROOT / "examples/order-flow/diagram.yml")
        )
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        found = json.loads(out)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["line"], 2)
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
        (base / "d.yml").write_text("icons: [./icons]\nnodes:\n  a: {at: [0, 0], icon: mine}\n", encoding="utf-8")
        code, out, _ = cli("icons", str(base / "d.yml"))
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^mine\s+tile\s+.*icons$")

    def test_init_writes_a_clean_diagram(self):
        base = self.tmp()
        path = base / "my flow" / "diagram.yml"
        code, _, _ = cli("init", str(path))
        self.assertEqual(code, 0)
        self.assertEqual(cli("check", "--strict", str(path))[0], 0)
        self.assertEqual(cli("build", "--html", str(path), "-o", str(base / "out"))[0], 0)
        self.assertEqual([p.name for p in (base / "out").iterdir()], ["my-flow.html"])

    def test_init_never_overwrites(self):
        path = self.tmp() / "x.yml"
        path.write_text("mine", encoding="utf-8")
        code, _, err = cli("init", str(path))
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertEqual(path.read_text(encoding="utf-8"), "mine")

    def test_readme_shows_the_starter(self):
        """The README's first YAML block is what its quick start's `diagr init my-flow.yml` writes."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        block = re.search(r"```yaml\n(.*?)```", readme, re.S)
        assert block
        path = self.tmp() / "my-flow.yml"
        self.assertEqual(cli("init", str(path))[0], 0)
        self.assertEqual(block.group(1), path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
