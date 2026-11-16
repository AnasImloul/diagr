from __future__ import annotations

import unittest

from diagr import json_schema
from diagr.icons import _import_svg
from tests.support import ROOT, Case, problems
from tests.test_build import prepared

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

    def test_ids_do_not_end_in_a_dash(self):
        node = "nodes:\n      x: {at: [0, 0], icon: api}\n"
        cases = {
            "component": f"id: t\ncomponents:\n  box-:\n    {node}instances:\n  i: {{component: box-}}\n",
            "instance": f"id: t\ncomponents:\n  box:\n    {node}instances:\n  east-: {{component: box}}\n",
            "node in a component": "id: t\ncomponents:\n  box:\n    nodes:\n      x-: {at: [0, 0], icon: api}\n"
            "instances:\n  i: {component: box}\n",
            "scenario": BASE + "scenarios:\n  go-: {steps: [{title: s, do: [done a]}]}\n",
        }
        for what, yml in cases.items():
            with self.subTest(what):
                self.assertReports(problems(yml), "is not an id: letters, digits, _ and - (not last)")

    def test_unquoted_number_as_text_passes_the_parser_and_the_schema(self):
        self.assertClean(problems(BASE + "title: 2024\nscenarios: {s: {steps: [{title: yes, do: [done a]}]}}\n"))
        self.assertEqual(json_schema()["properties"]["title"]["type"], ["string", "number", "boolean"])

    def test_list_inside_an_edge_list(self):
        yml = BASE.replace("a -> b: writes", "a -> b: [[x, y]]")
        self.assertReports(problems(yml), "one label or mapping per edge, not another list")

    def test_short_step_named_like_a_step_field(self):
        found = problems(BASE + "scenarios:\n  s:\n    steps:\n    - status: [done a]\n")
        self.assertReports(found, "'status' is a step's own field")
        self.assertReports(found, "write 'Status: [...]'")

    def test_quoted_repeat_count(self):
        yml = BASE + "scenarios:\n  s:\n    steps:\n    - title: s\n      do:\n        - repeat two: [done a]\n"
        self.assertReports(problems(yml), "'repeat' needs a whole number")


THREE = "nodes:\n  a: {at: [0, 0], icon: api}\n  b: {at: [1, 0], icon: api}\n  c: {at: [2, 0], icon: api}\n"


def edges(yml: str):
    return prepared("id: t\n" + THREE + "edges:\n" + yml).diagram.edges


class EdgeKeys(Case):
    def test_a_chain_makes_an_edge_per_arrow_with_a_label_each(self):
        found = edges("  a -> b -> c: [x, y]\n")
        self.assertEqual({k: e.label for k, e in found.items()}, {"a->b": "x", "b->c": "y"})

    def test_a_fan_makes_an_edge_from_each(self):
        self.assertEqual(sorted(edges("  (a b) -> c: {}\n")), ["a->c", "b->c"])

    def test_dashed_arrow(self):
        self.assertTrue(edges("  a --> b: {}\n")["a->b"].dashed)

    def test_a_pair_makes_one_edge_each_way(self):
        found = edges("  a <-> b: [go, back]\n")
        self.assertEqual((found["a->b"].label, found["b->a"].label), ("go", "back"))
        self.assertEqual((found["a->b"].twin, found["b->a"].twin), ("b->a", "a->b"))

    def test_as_names_the_edge(self):
        self.assertEqual(list(edges("  a -> b as feed: {}\n")), ["feed"])

    def test_ports(self):
        e = edges("  a@bottom+10 -> b@top: {}\n")["a->b"]
        self.assertEqual((e.src.side, e.src.offset, e.dst.side, e.dst.offset), ("bottom", 10, "top", 0))

    def test_too_many_labels(self):
        found = problems("id: t\n" + THREE + "edges:\n  a -> b -> c: [x, y, z]\n")
        self.assertReports(found, "'a -> b -> c' makes 2 edges but lists 3 labels or mappings")

    def test_as_on_a_key_that_makes_several_edges(self):
        found = problems("id: t\n" + THREE + "edges:\n  a -> b -> c as e: {}\n")
        self.assertReports(found, "'as e' names one edge, and 'a -> b -> c' makes 2")


class ErrorPaths(Case):
    def test_each_is_reported(self):
        cases = {
            "id: t\n" + THREE + "  a: {at: [3, 0], icon: api}\n": "duplicate key 'a' (first defined at line 3)",
            "id: t\nnodes:\n  [a, b]: {icon: api}\n": "keys must be plain text",
            "": "file is empty",
            "id: t\ngroups:\n  g: {title: G, nodes: {a: {at: [0, 0], icon: api}}}\n"
            "nodes:\n  a: {at: [1, 0], icon: api}\n": "node 'a' is defined twice",
            "id: t\ngroups:\n  a: {title: G}\nnodes:\n  a: {at: [0, 0], icon: api}\n": "is both a group and a node",
            "id: t\n" + THREE + "edges:\n  a -> b as c: {}\n": "edge id 'c' is also a node or group id",
            "id: t\n" + THREE + "edges:\n  a -> b: {route: [right], via: [[0.5, 1]]}\n": "either 'route' or 'via'",
            "id: t\ngroups:\n  g: {title: G, span: [2, 1]}\n" + THREE: "group 'g': 'span' needs 'at'",
            "id: t\nnodes:\n  a: {at: [0, 0], icon: api}\n  b: {at: [0, 0], icon: api}\n": "on the same cell as 'a'",
            "id: t\n" + THREE + "actions:\n  go: [go]\nscenarios: {s: {steps: [{title: s, do: [go]}]}}\n": (
                "action 'go' calls itself"
            ),
            "id: t\n" + THREE + "actions:\n  go: [activate a]\nscenarios: {s: {steps: [{title: s, do: [go x]}]}}\n": (
                "action 'go' takes no instances"
            ),
        }
        for yml, message in cases.items():
            with self.subTest(message):
                self.assertReports(problems(yml), message)


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
