from __future__ import annotations

import textwrap
import unittest

import yaml

from diagr import DiagramError, build_files
from diagr.migrations import VERSION, upgrade
from diagr.parse import loads
from diagr.source import data, load
from diagr.unparse import to_yaml
from tests.support import ROOT, Case, problems

V1 = """
id: m
groups:
  outer: {title: Outer, tone: blue}
  inner: {title: Inner, tone: teal, in: outer}
nodes:
  a: {at: [0, 0], icon: api, title: A, in: inner, trigger: Go}
  b: {at: [1, 0], icon: queue, title: B, sub: idle, in: outer, trigger: Again, plays: second}
  c: {at: [3, 0], icon: database, title: C, sub: idle}
edges:
  a -> b: {}
  b -> c: {}
scenarios:
  first:
    steps:
      - title: One
        do:
          - activate a
          - set c.sub 300ms busy now
          - "set c.title: Store"
          - status working
          - {set b.sub: queued}
          - repeat: 2
            do: [draw a->b, "status 100ms: round {i}"]
  second:
    steps:
      - title: Two
        do: [activate b]
"""

V2 = """
version: 2
id: m
groups:
  outer:
    title: Outer
    tone: blue
    groups:
      inner:
        title: Inner
        tone: teal
        nodes:
          a: {at: [0, 0], icon: api, title: A}
    nodes:
      b: {at: [1, 0], icon: queue, title: B, sub: idle}
nodes:
  c: {at: [3, 0], icon: database, title: C, sub: idle}
edges:
  a -> b: {}
  b -> c: {}
scenarios:
  first:
    trigger: {at: a, label: Go}
    steps:
      - title: One
        do:
          - activate a
          - c.sub 300ms: busy now
          - c.title: Store
          - status: working
          - b.sub: queued
          - repeat 2: [draw a->b, "status 100ms: round {i}"]
  second:
    trigger: {at: b, label: Again}
    steps:
      - title: Two
        do: [activate b]
"""


class Upgrade(Case):
    def built(self, yml: str) -> list[str]:
        f = self.tmp() / "diagram.yml"
        f.write_text(textwrap.dedent(yml), encoding="utf-8")
        return [p.read_text(encoding="utf-8") for p in build_files(f, self.tmp())[0]]

    def test_version_1_builds_as_its_version_2_rewrite(self):
        self.assertEqual(self.built(V1), self.built(V2))

    def test_each_rewrite_is_a_warning_at_its_line(self):
        found = loads(V1, "t.yml", ROOT).upgraded
        self.assertEqual(len(found), 11)
        self.assertTrue(all(p.level == "warning" and p.message.startswith("version 2 ") for p in found))
        self.assertReports(found, "writes node 'a' inside group 'inner', in place of 'in: inner'")
        self.assertEqual([p.loc and p.loc.line for p in found if "'repeat 2: [...]'" in p.message], [23])
        self.assertReports(problems(V1), "writes the trigger on scenario 'second'", "warning")

    def test_current_files_without_a_version_pass_unchanged(self):
        for example in sorted((ROOT / "examples").glob("*/diagram.yml")):
            text = example.read_text(encoding="utf-8").replace(f"version: {VERSION}\n", "")
            with self.subTest(example=example.parent.name):
                self.assertEqual(loads(text, str(example), example.parent).upgraded, [])

    def test_an_action_called_set_is_not_a_text_change(self):
        yml = """
        id: s
        nodes:
          a: {at: [0, 0], icon: api}
        actions:
          set: [activate a]
        scenarios:
          go:
            steps:
              - title: Go
                do: [set]
        """
        self.assertEqual(loads(textwrap.dedent(yml), "t.yml", ROOT).upgraded, [])

    def test_expand_writes_the_current_version(self):
        d = loads(V1, "t.yml", ROOT)
        out = to_yaml(d, data(upgrade(load(V1, "t.yml"))[0]))
        self.assertEqual(yaml.safe_load(out)["version"], VERSION)
        self.assertEqual(loads(out, "t.yml", ROOT).upgraded, [])

    def test_version_problems(self):
        newer = problems(f"version: {VERSION + 1}\nid: v\nnodes: {{a: {{icon: api}}}}\n")
        self.assertReports(newer, f"newer than this diagr, which reads up to version {VERSION}")
        self.assertReports(problems("version: two\nid: v\nnodes: {a: {icon: api}}\n"), "'version' is a whole number")


class Version2(Case):
    def test_unknown_or_circular_groups(self):
        unknown = "id: n\ngroups:\n  g: {title: G}\nnodes:\n  a: {icon: api, in: h}\n"
        self.assertReports(problems(unknown), "node 'a' is in unknown group 'h'")
        loop = "id: n\ngroups:\n  g: {title: G, in: h}\n  h: {title: H, in: g}\nnodes:\n  a: {icon: api}\n"
        self.assertReports(problems(loop), "group 'h' is inside itself through 'in'")

    def test_a_scenario_gets_one_trigger(self):
        yml = """
        id: t
        nodes:
          a: {at: [0, 0], icon: api, trigger: One}
          b: {at: [1, 0], icon: api, trigger: Two}
        scenarios:
          go: {steps: [{title: Go, do: [activate a]}]}
        """
        self.assertReports(problems(yml), "scenario 'go' has two triggers")

    def test_no_triggers_in_components(self):
        yml = """
        id: t
        components:
          c:
            nodes:
              x: {at: [0, 0], icon: api, trigger: Go}
        instances:
          i: {component: c}
        scenarios:
          go: {steps: [{title: Go, do: [activate i/x]}]}
        """
        self.assertReports(problems(yml), "no triggers in components")

    def test_upgrade_problems_come_with_parse_errors(self):
        try:
            loads("id: t\nnodes:\n  a: {icon: api, in: g, bad: 1}\ngroups:\n  g: {title: G}\n", "t.yml", ROOT)
        except DiagramError as e:
            self.assertReports(e.problems, "writes node 'a' inside group 'g'", "warning")
            self.assertReports(e.problems, "unknown key 'bad'", "error")
        else:
            self.fail("expected an error")


if __name__ == "__main__":
    unittest.main()
