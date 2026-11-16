from __future__ import annotations

import unittest

import yaml

from diagr.parse import loads
from diagr.scenario import fold
from diagr.unparse import to_yaml
from tests.support import ROOT, Case, problems
from tests.test_build import prepared

BASE = """
id: t
components:
  pair:
    params: {name: {required: true}, note: default note}
    groups:
      box:
        title: "{name}"
        sub: "{note}"
        tone: blue
        nodes:
          api: {at: [0, 0], icon: api, title: "{name} API"}
          db: {at: [1, 0], icon: database, title: Store, tooltip: "{note}"}
    edges:
      api -> db: "writes for {name}"
      api -> db as backup: {label: backup, route: [up 40px, right, down]}
instances:
  a: {component: pair, at: [0, 0], with: {name: Alpha}}
  b: {component: pair, at: [0, 2], in: outer, with: {name: Beta, note: custom}}
groups:
  outer: {title: Outer, tone: neutral}
nodes:
  lb: {at: [-1, 1], icon: globe, title: LB}
edges:
  lb -> a/api: {route: [up, right]}
  lb -> b/api: {route: [down, right]}
"""


class Expansion(Case):
    def test_is_clean(self):
        self.assertClean(problems(BASE))

    def test_copies_are_prefixed_and_offset(self):
        d = prepared(BASE).diagram
        self.assertEqual(d.nodes["a/api"].at, (0, 0))
        self.assertEqual(d.nodes["b/db"].at, (1, 2))
        self.assertEqual(d.nodes["b/api"].group, "b/box")
        self.assertIn("a/api->a/db", d.edges)
        self.assertIn("a/backup", d.edges)
        self.assertEqual(d.edges["a/backup"].src.node, "a/api")

    def test_parameters_and_defaults(self):
        d = prepared(BASE).diagram
        self.assertEqual(d.groups["a/box"].title, "Alpha")
        self.assertEqual(d.groups["a/box"].sub, "default note")
        self.assertEqual(d.groups["b/box"].sub, "custom")
        self.assertEqual(d.nodes["b/api"].title, "Beta API")
        self.assertEqual(d.nodes["a/db"].tooltip, "default note")
        self.assertEqual(d.edges["b/api->b/db"].label, "writes for Beta")

    def test_literal_braces(self):
        d = prepared(BASE.replace('title: Store, tooltip: "{note}"', 'title: "{{name}} is {name}"')).diagram
        self.assertEqual(d.nodes["a/db"].title, "{name} is Alpha")

    def test_empty_parameter_is_an_error(self):
        self.assertReports(problems(BASE.replace("name: {required: true}", "name: ")), "write {required: true}")

    def test_in_puts_the_outermost_groups_in_a_parent(self):
        d = prepared(BASE).diagram
        self.assertEqual(d.groups["b/box"].parent, "outer")
        self.assertIsNone(d.groups["a/box"].parent)

    def test_fixed_group_and_via_are_offset(self):
        yml = BASE.replace("      box:\n", "      box:\n        at: [0, 0]\n        span: [2, 1]\n").replace(
            "route: [up 40px, right, down]", "via: [[0, -0.3], [1, -0.3]]"
        )
        d = prepared(yml).diagram
        self.assertEqual(d.groups["b/box"].at, (0, 2))
        self.assertEqual(d.edges["b/backup"].via, [(0, 1.7), (1, 1.7)])

    def test_scenarios_reach_into_copies(self):
        yml = BASE + (
            "scenarios:\n  s:\n    steps:\n    - title: go\n      do:\n"
            "        - draw lb->b/api\n        - 'b/db.sub: busy'\n        - 'lb->a/api.label: idle'\n"
            "        - done b/api\n"
        )
        s = fold(prepared(yml).scenarios["s"].frames)
        self.assertEqual(s["e:lb->b/api"], "drawn")
        self.assertEqual(s["t:b/db:sub:0"], "busy")
        self.assertEqual(s["t:lb->a/api:label"], "idle")
        self.assertEqual(s["n:b/api"], "done")

    def test_expand_keeps_a_step_without_effects(self):
        action = "    actions:\n      go: [activate api]\n    edges:\n      api -> db:"
        yml = (
            BASE.replace("    edges:\n      api -> db:", action)
            + "scenarios:\n  s:\n    steps:\n    - {title: Intro, text: Nothing yet}\n    - Go: [go a]\n"
        )
        out = to_yaml(loads(yml, "t.yml", ROOT), yaml.safe_load(yml))
        self.assertClean(problems(out))
        steps = yaml.safe_load(out)["scenarios"]["s"]["steps"]
        self.assertEqual(steps[0], {"title": "Intro", "text": "Nothing yet"})
        self.assertEqual(steps[1], {"Go": ["activate a/api"]})


class Errors(Case):
    def test_unknown_component(self):
        self.assertReports(
            problems(BASE.replace("component: pair, at: [0, 2]", "component: nope, at: [0, 2]")),
            "unknown component 'nope'",
        )

    def test_unknown_parameter_in_with(self):
        self.assertReports(
            problems(BASE.replace("with: {name: Alpha}", "with: {name: Alpha, colour: red}")), "has no parameter colour"
        )

    def test_missing_required_parameter(self):
        self.assertReports(problems(BASE.replace("with: {name: Alpha}", "with: {note: x}")), "needs name")

    def test_unknown_placeholder_is_reported_once(self):
        found = problems(BASE.replace('title: Store, tooltip: "{note}"', 'title: "{nmae}"'))
        hits = [p for p in found if "unknown parameter {nmae}" in p.message]
        self.assertEqual(len(hits), 1)

    def test_edge_to_a_node_outside_the_component(self):
        self.assertReports(problems(BASE.replace("api -> db: ", "api -> lb: ")), "not one of its nodes")

    def test_place_in_unknown_group(self):
        self.assertReports(problems(BASE.replace("in: outer, with", "in: nowhere, with")), "unknown group 'nowhere'")

    def test_copy_name_clash(self):
        yml = BASE.replace("  lb: {at: [-1, 1]", "  a/api: {at: [5, 5], icon: api, title: X}\n  lb: {at: [-1, 1]")
        self.assertReports(problems(yml), "instance 'a': a/api already defined elsewhere")

    def test_typos_get_suggestions(self):
        yml = BASE.replace("lb -> b/api:", "lb -> b/aip:") + (
            "scenarios:\n  s:\n    steps:\n"
            "    - {title: s, at: a/dbb, do: [activate b/apl, draw lb->a/apii, a/bd.sub: x]}\n"
        )
        found = problems(yml.replace("icon: database", "icon: databse"))
        for text in (
            "did you mean 'b/api'",
            "did you mean 'a/db'",
            "did you mean 'lb->a/api'",
            "did you mean 'database'",
        ):
            self.assertReports(found, text)

    def test_reference_to_a_missing_copy(self):
        self.assertReports(problems(BASE.replace("lb -> b/api:", "lb -> c/api:")), "unknown node or group 'c/api'")


if __name__ == "__main__":
    unittest.main()
