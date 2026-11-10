from __future__ import annotations

import unittest

from diagr.render.html import render_html
from diagr.render.svg import render_static
from tests.support import Case, problems
from tests.test_build import prepared

NESTED = """
id: t
groups:
  outer:
    title: Outer
    tone: neutral
    groups:
      inner:
        title: Inner
        tone: blue
        nodes:
          a: {at: [0, 0], icon: server, title: A}
    nodes:
      b: {at: [2, 0], icon: database, title: B}
edges:
  a -> b: writes
"""

TWO = """
id: t
nodes:
  a: {at: [0, 0], icon: server, title: A}
  b: {at: [1, 0], icon: database, title: B}
edges:
  a -> b: writes
scenarios:
  first:
    title: First
    steps:
      - {title: one, at: a, do: [done a]}
  second:
    title: Second
    trigger: {at: a, label: Go}
    ready: second ready
    steps:
      - {title: two, at: b, do: [draw a->b, done b]}
"""


class NestedGroups(Case):
    def test_parent_surrounds_child(self):
        lay = prepared(NESTED).layout
        outer, inner = lay.groups["outer"], lay.groups["inner"]
        self.assertTrue(outer.x < inner.x and outer.y < inner.y and outer.x1 > inner.x1 and outer.y1 > inner.y1)
        self.assertTrue(outer.contains((lay.nodes["b"].x, lay.nodes["b"].y)))

    def test_label_takes_the_innermost_tint(self):
        p = prepared(NESTED)
        a = p.layout.nodes["a"]
        self.assertEqual(p.scene().fill_at(a.x, a.y), "tone-blue-fill")

    def test_three_levels(self):
        yml = NESTED.replace(
            "      inner:\n        title: Inner\n        tone: blue\n        nodes:\n          a:",
            "      mid:\n        title: Mid\n        tone: teal\n        groups:\n"
            "          inner:\n            title: Inner\n            tone: blue\n            nodes:\n              a:",
        )
        self.assertClean(problems(yml))
        g = prepared(yml).layout.groups
        self.assertEqual(list(g), ["outer", "mid", "inner"])
        self.assertTrue(g["outer"].x < g["mid"].x < g["inner"].x)

    def test_nesting_is_not_an_overlap(self):
        self.assertClean(problems(NESTED))

    def test_fixed_child_outside_its_parent(self):
        yml = NESTED.replace("        title: Inner\n", "        title: Inner\n        at: [5, 3]\n").replace(
            "a: {at: [0, 0]", "a: {at: [5, 3]"
        )
        yml = yml.replace("    tone: neutral\n", "    at: [0, 0]\n    span: [3, 1]\n")
        self.assertReports(problems(yml), "group 'inner' is outside its parent group 'outer'", "error")


class Scenarios(Case):
    def test_each_scenario_is_compiled(self):
        p = prepared(TWO)
        self.assertEqual(list(p.scenarios), ["first", "second"])
        self.assertEqual(p.scenarios["second"].ready, "second ready")

    def test_empty_scenarios(self):
        yml = TWO.split("scenarios:")[0] + "scenarios: {}\n"
        self.assertReports(problems(yml), "must not be empty")

    def test_trigger_at_an_unknown_node(self):
        self.assertReports(problems(TWO.replace("at: a, label: Go", "at: c, label: Go")), "unknown node 'c'", "error")

    def test_one_trigger_per_node(self):
        yml = TWO.replace("    title: First\n", "    title: First\n    trigger: {at: a, label: Run}\n")
        self.assertReports(problems(yml), "node 'a' already has the trigger of 'first'", "error")

    def test_effects_are_checked_in_every_scenario(self):
        self.assertReports(problems(TWO.replace("draw a->b, done b", "done nope")), "unknown node 'nope'")

    def test_shown_by_any_scenario(self):
        yml = TWO.replace("title: B}", "title: B, hidden: true}").replace("a -> b: writes", "a -> b: {hidden: true}")
        yml = yml.replace("[draw a->b, done b]", "[show b a->b, done b]")
        self.assertClean(problems(yml))

    def test_player_has_a_picker_and_a_list_per_scenario(self):
        html = render_html(prepared(TWO))
        self.assertIn('<button type="button" data-scenario="first" aria-pressed="true">First</button>', html)
        self.assertIn('<button type="button" data-scenario="second" aria-pressed="false">Second</button>', html)
        self.assertIn('<ol class="steps" data-scenario="first">', html)
        self.assertIn('<ol class="steps" data-scenario="second" hidden>', html)
        self.assertIn('data-plays="second"', html)
        self.assertIn('<svg class="diagr" data-scenario="first" ', html)

    def test_badges_per_scenario(self):
        p = prepared(TWO)
        html = render_html(p)
        self.assertIn('data-badges="first"', html)
        self.assertIn('data-badges="second"', html)
        static = render_static(p.scene(), p.theme, "light")
        self.assertIn('data-badges="first"', static)
        self.assertNotIn('data-badges="second"', static)

    def test_loop(self):
        p = prepared(TWO.replace("    title: Second\n", "    title: Second\n    loop: true\n"))
        self.assertFalse(p.scenarios["first"].loop)
        self.assertTrue(p.scenarios["second"].loop)
        html = render_html(p)
        self.assertIn('{"id":"first","loop":false,', html)
        self.assertIn('{"id":"second","loop":true,', html)

    def test_loop_is_true_or_false(self):
        self.assertReports(
            problems(TWO.replace("    title: Second\n", "    title: Second\n    loop: yes please\n")), "true or false"
        )

    def test_one_scenario_has_no_picker(self):
        html = render_html(prepared(TWO.split("  second:")[0]))
        self.assertNotIn('class="scenarios"', html)


class LayoutWarnings(Case):
    def test_edge_through_a_node(self):
        yml = NESTED.replace("      b: {at: [2, 0]", "      b: {at: [3, 0]")
        yml = yml.replace("    nodes:\n      b:", "    nodes:\n      c: {at: [2, 0], icon: cube, title: C}\n      b:")
        self.assertReports(problems(yml), "edge 'a->b' passes through node 'c'", "warning")

    def test_node_overlapping_a_group_it_is_not_in(self):
        yml = NESTED.replace("    nodes:\n      b: {at: [2, 0]", "nodes:\n  b: {at: [0.3, 0.2]")
        self.assertReports(problems(yml), "node 'b' overlaps group 'inner', which it is not in", "warning")

    def test_edge_across_a_group_title(self):
        yml = """
id: t
groups:
  g: {title: A long group title, tone: blue, nodes: {in: {at: [0, 0], icon: cube, title: In}}}
nodes:
  a: {at: [-0.28, -1], icon: server, title: A}
  b: {at: [-0.28, 1.3], icon: database, title: B}
edges:
  a -> b: {}
"""
        self.assertReports(problems(yml), "crosses the title of group 'g'", "warning")


if __name__ == "__main__":
    unittest.main()
