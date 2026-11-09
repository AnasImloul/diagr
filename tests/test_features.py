from __future__ import annotations

import unittest

from tests.support import Case, problems
from tests.test_build import prepared

NESTED = """
diagram: t
groups:
  outer: {title: Outer, tone: neutral}
  inner: {title: Inner, in: outer, tone: blue}
nodes:
  a: {in: inner, at: [0, 0], icon: server, title: A}
  b: {in: outer, at: [2, 0], icon: database, title: B}
edges:
  a -> b: writes
"""


class NestedGroups(Case):
    def test_parent_surrounds_child(self):
        lay = prepared(NESTED).layout
        outer, inner = lay.groups["outer"], lay.groups["inner"]
        self.assertTrue(outer.x < inner.x and outer.y < inner.y and outer.x1 > inner.x1 and outer.y1 > inner.y1)
        self.assertTrue(outer.contains((lay.nodes["b"].x, lay.nodes["b"].y)))

    def test_outer_groups_are_drawn_first(self):
        yml = NESTED.replace(
            "  outer: {title: Outer, tone: neutral}\n  inner: {title: Inner, in: outer, tone: blue}\n",
            "  inner: {title: Inner, in: outer, tone: blue}\n  outer: {title: Outer, tone: neutral}\n",
        )
        self.assertEqual(list(prepared(yml).layout.groups), ["outer", "inner"])

    def test_label_takes_the_innermost_tint(self):
        p = prepared(NESTED)
        a = p.layout.nodes["a"]
        self.assertEqual(p.scene().fill_at(a.x, a.y), "tone-blue-fill")

    def test_three_levels(self):
        yml = NESTED.replace(
            "  inner: {title: Inner, in: outer, tone: blue}\n",
            "  mid: {title: Mid, in: outer, tone: teal}\n  inner: {title: Inner, in: mid, tone: blue}\n",
        )
        self.assertClean(problems(yml))
        g = prepared(yml).layout.groups
        self.assertEqual(list(g), ["outer", "mid", "inner"])
        self.assertTrue(g["outer"].x < g["mid"].x < g["inner"].x)

    def test_nesting_is_not_an_overlap(self):
        self.assertClean(problems(NESTED))

    def test_unknown_parent(self):
        self.assertReports(problems(NESTED.replace("in: outer, tone: blue", "in: nope, tone: blue")), "unknown parent")

    def test_loop(self):
        yml = NESTED.replace(
            "  outer: {title: Outer, tone: neutral}", "  outer: {title: Outer, in: inner, tone: neutral}"
        )
        self.assertReports(problems(yml), "is inside itself", "error")

    def test_fixed_child_outside_its_parent(self):
        yml = NESTED.replace(
            "  inner: {title: Inner, in: outer, tone: blue}",
            "  inner: {title: Inner, in: outer, at: [5, 3], tone: blue}",
        ).replace("  a: {in: inner, at: [0, 0]", "  a: {in: inner, at: [5, 3]")
        yml = yml.replace("  outer: {title: Outer, tone: neutral}", "  outer: {title: Outer, at: [0, 0], span: [3, 1]}")
        self.assertReports(problems(yml), "group 'inner' is outside its parent group 'outer'", "error")


if __name__ == "__main__":
    unittest.main()
