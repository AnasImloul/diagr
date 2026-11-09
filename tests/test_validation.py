from __future__ import annotations

import unittest

from diagr.icons import _import_svg
from tests.support import Case, problems

BASE = """
diagram: t
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
        self.assertReports(problems("diagram: t\nnodes: {}\n"), "must not be empty")

    def test_empty_steps(self):
        self.assertReports(problems(BASE + "scenario: {steps: []}\n"), "must not be empty")

    def test_newer_format_version(self):
        self.assertReports(problems("diagr: 99\n" + BASE), "must be at most 1")
        self.assertClean(problems("diagr: 1\n" + BASE))

    def test_nan_is_not_a_number(self):
        self.assertReports(problems("diagram: t\nnodes:\n  a: {at: [nan, 0], icon: server}\n"), "is not a number")

    def test_label_at_range(self):
        self.assertReports(
            problems(BASE.replace("a -> b: writes", "a -> b: {label: x, label_at: 2}")), "must be at most 1"
        )

    def test_group_span_must_be_positive(self):
        yml = BASE + "groups:\n  g: {title: G, at: [0, 0], span: [-1, 1]}\n"
        self.assertReports(problems(yml), "must be at least 1")

    def test_quoted_repeat_count(self):
        yml = BASE + "scenario:\n  steps:\n    - title: s\n      do:\n        - repeat: '2'\n          do: [done a]\n"
        self.assertReports(problems(yml), "'repeat' needs a whole number")


class Flow(Case):
    def step(self, do: str) -> str:
        return BASE + f"scenario:\n  steps:\n    - {{title: s, do: [{do}]}}\n"

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

    def test_not_inside_parallel(self):
        self.assertReports(problems(self.step("parallel: [flow a -> b]")), "'flow' cannot run inside 'parallel'")


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
        yml += "scenario:\n  steps:\n    - {title: s, do: [activate b, show a->b]}\n"
        self.assertReports(problems(yml), "node 'b' is hidden and nothing shows it", "warning")

    def test_shown_node_is_fine(self):
        yml = BASE.replace("title: B}", "title: B, hidden: true}").replace("a -> b: writes", "a -> b: {hidden: true}")
        yml += "scenario:\n  steps:\n    - {title: s, do: [show b a->b]}\n"
        self.assertClean(problems(yml))

    def test_visible_edge_into_hidden_node(self):
        yml = BASE.replace("title: B}", "title: B, hidden: true}")
        yml += "scenario:\n  steps:\n    - {title: s, do: [show b]}\n"
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
        yml = f"diagram: t\nicons: [./icons]\nnodes:\n  a: {{at: [0, 0], {node}}}\n"
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

    def test_unsafe_tile_glyph_is_refused(self):
        found = self.icons(
            {"icons.yml": "tiles:\n  x: {tone: blue, glyph: '<path onload=\"alert(1)\"/>'}\n"}, "icon: server"
        )
        self.assertReports(found, "tile 'x': glyph has an event handler")


if __name__ == "__main__":
    unittest.main()
