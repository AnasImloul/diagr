from __future__ import annotations

import unittest

from diagr.icons import _import_svg
from tests.support import ROOT, Case, problems

BASE = """
id: t
nodes:
  a: {at: [0, 0], icon: server, title: A}
  b: {at: [1, 0], icon: database, title: B}
edges:
  a -> b: writes
"""


class Format(Case):
    def test_minimal_diagram_is_clean(self):
        self.assertClean(problems(BASE))

    def test_unknown_key_suggests_the_right_one(self):
        self.assertReports(problems(BASE + "titel: x\n"), "did you mean 'title'?")

    def test_empty_nodes(self):
        self.assertReports(problems("id: t\nnodes: {}\n"), "must not be empty")

    def test_empty_steps(self):
        self.assertReports(problems(BASE + "scenarios: {s: {steps: []}}\n"), "must not be empty")

    def test_nan_is_not_a_number(self):
        self.assertReports(problems("id: t\nnodes:\n  a: {at: [nan, 0], icon: server}\n"), "is not a number")

    def test_label_at_range(self):
        self.assertReports(
            problems(BASE.replace("a -> b: writes", "a -> b: {label: x, label_at: 2}")), "must be at most 1"
        )

    def test_group_span_must_be_positive(self):
        yml = BASE + "groups:\n  g: {title: G, at: [0, 0], span: [-1, 1]}\n"
        self.assertReports(problems(yml), "must be at least 1")

    def test_quoted_repeat_count(self):
        yml = BASE + "scenarios:\n  s:\n    steps:\n    - title: s\n      do:\n        - repeat two: [done a]\n"
        self.assertReports(problems(yml), "'repeat' needs a whole number")


class Flow(Case):
    def step(self, do: str) -> str:
        return BASE + f"scenarios:\n  s:\n    steps:\n    - {{title: s, do: [{do}]}}\n"

    def test_needs_a_path(self):
        self.assertReports(problems(self.step("flow a")), "'flow' takes a path of nodes")

    def test_needs_an_edge_per_hop(self):
        self.assertReports(problems(self.step("flow b -> a")), "no edge from 'b' to 'a'")

    def test_unknown_node(self):
        self.assertReports(problems(self.step("flow a -> bb")), "did you mean 'b'")

    def test_ambiguous_hop(self):
        yml = self.step("flow a -> b").replace(
            "  a -> b: writes\n", "  a -> b as one: writes\n  a -> b as two: twice\n"
        )
        self.assertReports(problems(yml), "several edges go from 'a' to 'b'")

    def test_inside_parallel(self):
        self.assertClean(problems(self.step("parallel: [flow a -> b]")))

    def test_parallel_inside_parallel(self):
        self.assertClean(problems(self.step("parallel: [{parallel: [done a]}, flow a -> b]")))


class Cells(Case):
    def step(self, cells: str, do: str) -> str:
        yml = BASE.replace("title: A}", f"title: A, cells: {cells}}}")
        return yml + f"scenarios:\n  s:\n    steps:\n    - {{title: s, do: [{do}]}}\n"

    def test_unknown_cell_name(self):
        self.assertReports(problems(self.step("[build, test]", "cells a biuld")), "did you mean 'build'")

    def test_names_need_named_cells(self):
        self.assertReports(problems(self.step("3", "cells a build")), "its cells have no names")


class Edges(Case):
    def test_self_loop_without_route(self):
        self.assertReports(problems(BASE + "  a -> a as loop: x\n"), "starts and ends at 'a'", "error")

    def test_self_loop_with_route(self):
        yml = BASE + "  a@right -> a@top as loop: {route: [right 0.3, up 0.5, left, down]}\n"
        self.assertFalse([p for p in problems(yml) if "starts and ends" in p.message])


class Hidden(Case):
    def test_hidden_node_that_nothing_shows(self):
        yml = BASE.replace("title: B}", "title: B, hidden: true}").replace("a -> b: writes", "a -> b: {hidden: true}")
        self.assertReports(problems(yml), "node 'b' is hidden and nothing shows it", "warning")

    def test_mentioning_a_hidden_node_is_not_showing_it(self):
        yml = BASE.replace("title: B}", "title: B, hidden: true}").replace("a -> b: writes", "a -> b: {hidden: true}")
        yml += "scenarios:\n  s:\n    steps:\n    - {title: s, do: [focus b, b.sub: x, show a->b]}\n"
        self.assertReports(problems(yml), "node 'b' is hidden and nothing shows it", "warning")

    def test_shown_node_is_fine(self):
        yml = BASE.replace("title: B}", "title: B, hidden: true}").replace("a -> b: writes", "a -> b: {hidden: true}")
        yml += "scenarios:\n  s:\n    steps:\n    - {title: s, do: [show b a->b]}\n"
        self.assertClean(problems(yml))

    def test_visible_edge_into_hidden_node(self):
        yml = BASE.replace("title: B}", "title: B, hidden: true}")
        yml += "scenarios:\n  s:\n    steps:\n    - {title: s, do: [show b]}\n"
        self.assertReports(problems(yml), "edge 'a->b' is visible but node 'b' starts hidden", "warning")

    def test_hidden_edge_that_nothing_shows(self):
        yml = BASE.replace("a -> b: writes", "a -> b: {hidden: true}")
        self.assertReports(problems(yml), "edge 'a->b' is hidden and nothing shows it", "warning")


class Themes(Case):
    def theme(self, text: str):
        base = self.tmp()
        (base / "theme.yml").write_text(text, encoding="utf-8")
        return problems(BASE + "theme: ./theme.yml\n", base)

    def test_unknown_theme(self):
        self.assertReports(problems(BASE + "theme: nope\n"), "theme 'nope' not found")

    def test_contrast_builds_every_example_cleanly(self):
        for example in sorted((ROOT / "examples").glob("*/diagram.yml")):
            with self.subTest(example.parent.name):
                self.assertClean(problems(example.read_text(encoding="utf-8"), example.parent, "contrast"))

    def test_broken_yaml(self):
        found = self.theme("light: [\n")
        self.assertReports(found, "theme YAML")
        self.assertTrue(found[0].loc and found[0].loc.file.endswith("theme.yml"))

    def test_not_a_mapping(self):
        self.assertReports(self.theme("just some text\n"), "expected a mapping")

    def test_standalone_theme_needs_everything(self):
        found = self.theme("font: serif\nsizes: {icon: 52}\nlight: {bg: '#fff'}\n")
        self.assertReports(found, "'sizes' is missing 'margin'")
        self.assertReports(found, "'light' is missing token 'accent'")
        self.assertReports(found, "'dark' must be a mapping")

    def test_size_must_be_a_number(self):
        self.assertReports(self.theme("extends: default\nsizes: {icon: big}\n"), "'sizes.icon' must be a number")

    def test_light_and_dark_must_match(self):
        found = self.theme("extends: default\nlight:\n  tones:\n    pink: {fill: '#fee', stroke: '#f99'}\n")
        self.assertReports(found, "'tones.pink' is in light but not dark")

    def test_values_that_could_leave_the_css_are_refused(self):
        found = self.theme(
            "extends: default\n"
            "font: 'x; } </style><script>alert(1)</script>'\n"
            "light:\n  bg: '#fff; } body { display: none'\n  tones:\n    'x}': {fill: '#fff', stroke: '#000'}\n"
            "dark:\n  tones:\n    'x}': {fill: '#fff', stroke: '#000'}\n"
        )
        self.assertReports(found, "'font' may only hold font names")
        self.assertReports(found, "'light.bg' must be a colour")
        self.assertReports(found, "'light.tones.x}': a name may only hold")

    def test_modern_colours_and_quoted_fonts_are_allowed(self):
        found = self.theme(
            "extends: default\nfont: \"Inter, 'Noto Sans JP', sans-serif\"\n"
            "light: {accent: 'oklch(62% 0.2 145 / 0.9)'}\ndark: {accent: 'rgb(10, 20, 30)'}\n"
        )
        self.assertClean(found)

    def test_extends_loop(self):
        self.assertReports(self.theme("extends: ./theme.yml\n"), "'extends' loops back")

    def test_extending_default_is_clean(self):
        self.assertClean(self.theme("extends: default\nlight: {accent: '#ff0000'}\n"))


class IconFolders(Case):
    def icons(self, files: dict[str, str], node: str):
        base = self.tmp()
        (base / "icons").mkdir()
        for name, text in files.items():
            (base / "icons" / name).write_text(text, encoding="utf-8")
        yml = f"id: t\nicons: [./icons]\nnodes:\n  a: {{at: [0, 0], {node}}}\n"
        return problems(yml, base)

    def test_tile_needs_tone_and_glyph(self):
        self.assertReports(
            self.icons({"icons.yml": "tiles:\n  x: {tone: blue}\n"}, "icon: server"),
            "tile 'x' needs 'tone' and 'glyph'",
        )

    def test_tile_tone_must_exist_in_theme(self):
        found = self.icons({"icons.yml": "tiles:\n  x: {tone: pink, glyph: '<path/>'}\n"}, "icon: x")
        self.assertReports(found, "uses tile tone 'pink'")

    def test_node_tone_overrides_tile_tone(self):
        found = self.icons({"icons.yml": "tiles:\n  x: {tone: pink, glyph: '<path/>'}\n"}, "icon: x, tone: blue")
        self.assertClean(found)

    def test_broken_yaml(self):
        self.assertReports(self.icons({"icons.yml": "tiles: [\n"}, "icon: server"), "YAML:")

    def test_svg_without_closing_tag(self):
        self.assertReports(
            self.icons({"x.svg": '<svg viewBox="0 0 10 10"><path/>'}, "icon: x"), "icon 'x' cannot be read"
        )

    def test_recolour_with_unknown_token(self):
        found = self.icons(
            {"x.svg": '<svg viewBox="0 0 10 10"><path/></svg>', "icons.yml": "recolour: {x: nope}\n"}, "icon: x"
        )
        self.assertReports(found, "unknown theme token 'nope'")

    def test_recolour_with_known_token(self):
        found = self.icons(
            {"x.svg": '<svg viewBox="0 0 10 10"><path/></svg>', "icons.yml": "recolour: {x: text}\n"}, "icon: x"
        )
        self.assertClean(found)

    def test_single_quoted_attributes(self):
        svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path id='p'/><use href='#p'/></svg>"
        ic = _import_svg("x", svg, None)
        self.assertEqual(ic.view_box, "0 0 24 24")
        self.assertIn('id="i-x-p"', ic.body)
        self.assertIn('href="#i-x-p"', ic.body)

    def test_unsafe_svg_icons_are_refused(self):
        cases = {
            "script": '<svg viewBox="0 0 10 10"><script>alert(1)</script></svg>',
            "event handler": '<svg viewBox="0 0 10 10"><rect onclick="alert(1)"/></svg>',
            "javascript: URL": '<svg viewBox="0 0 10 10"><a href=" JavaScript:alert(1)"><rect/></a></svg>',
            "html breakout": '<svg viewBox="0 0 10 10"><p/></svg>',
            "foreign object": '<svg viewBox="0 0 10 10"><foreignObject/></svg>',
            "cdata": '<svg viewBox="0 0 10 10"><text><![CDATA[x]]></text></svg>',
            "not xml": '<svg viewBox="0 0 10 10"><rect></svg>',
            "event handler on the root": '<svg viewBox="0 0 10 10" onload="alert(1)"><rect/></svg>',
            "style": '<svg viewBox="0 0 10 10"><style>rect{fill:red}</style><rect/></svg>',
            "external image": '<svg viewBox="0 0 10 10"><image href="https://example.com/x.png"/></svg>',
            "external use": (
                '<svg xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
                '<use xlink:href="https://example.com/s.svg#a"/></svg>'
            ),
            "external url()": '<svg viewBox="0 0 10 10"><rect fill="url(https://example.com/x)"/></svg>',
            "external url() in style": """<svg viewBox="0 0 10 10"><rect style="fill: url( 'http://e/x' )"/></svg>""",
            "animated link": '<svg viewBox="0 0 10 10"><a href="#r"><animate attributeName="href" to="x"/></a></svg>',
        }
        for why, svg in cases.items():
            with self.subTest(why):
                self.assertReports(self.icons({"x.svg": svg}, "icon: x"), "icon 'x' cannot be read")

    def test_editor_metadata_is_allowed(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10"><inkscape:grid/>'
            '<defs><linearGradient id="g"/></defs><rect fill="url(#g)" xlink:href="#g"/></svg>'
        )
        self.assertClean(self.icons({"x.svg": svg}, "icon: x"))
        ic = _import_svg("x", svg, None)
        self.assertNotIn("inkscape", ic.body)
        self.assertIn('<rect fill="url(#i-x-g)" href="#i-x-g"/>', ic.body)

    def test_internal_references_data_images_and_links_are_kept(self):
        body = (
            '<image href="data:image/png;base64,AAAA"/><a href="https://example.com"><rect/></a>'
            "<text>a &amp; b &lt; c</text>"
        )
        ic = _import_svg("x", f'<svg viewBox="0 0 10 10">{body}</svg>', None)
        self.assertEqual(ic.body, body)

    def test_unsafe_tile_glyph_is_refused(self):
        found = self.icons(
            {"icons.yml": "tiles:\n  x: {tone: blue, glyph: '<path onload=\"alert(1)\"/>'}\n"}, "icon: server"
        )
        self.assertReports(found, "tile 'x': glyph has an event handler")


if __name__ == "__main__":
    unittest.main()
