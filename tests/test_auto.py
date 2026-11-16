from __future__ import annotations

import unittest

import yaml

from tests.support import Case, problems
from tests.test_build import cli, prepared

CHAIN = """
id: t
nodes:
  a: {icon: api, title: A}
  b: {icon: queue, title: B}
  c: {icon: server, title: C}
  d: {icon: database, title: D}
edges:
  a -> b: {}
  b -> c: {}
  b -> d: {}
  c -> a: {}
"""

GROUPS = """
id: t
groups:
  front:
    title: Front
    tone: blue
    nodes:
      web: {icon: browser, title: Web}
  back:
    title: Back
    tone: teal
    groups:
      data:
        title: Data
        tone: amber
        nodes:
          db: {icon: database, title: DB}
          cache: {icon: database, title: Cache}
    nodes:
      api: {icon: api, title: API}
nodes:
  ops: {icon: user, title: Ops}
edges:
  web -> api: {}
  api -> db: {}
  api -> cache: {}
  ops -> api: {}
"""

FED_FROM_ROW_ZERO = """
id: t
groups:
  src:
    title: Sources
    nodes:
      a: {icon: server, title: A}
      b: {icon: server, title: B}
  dst:
    title: Targets
    nodes:
      q: {icon: server, title: Q}
      f1: {icon: server, title: F1}
      f2: {icon: server, title: F2}
      p: {icon: server, title: P}
edges:
  a -> p: {}
  b -> q: {}
"""


class Placement(Case):
    def test_layers_follow_edges(self):
        nodes = prepared(CHAIN).diagram.nodes
        at = {k: n.at or (-1, -1) for k, n in nodes.items()}
        self.assertEqual(at["a"][0], 0)
        self.assertEqual(at["b"][0], 1)
        self.assertEqual(at["c"][0], at["d"][0])
        self.assertNotEqual(at["c"][1], at["d"][1])
        self.assertTrue(all(n.auto for n in nodes.values()))

    def test_direction_down_swaps_axes(self):
        at = {
            k: n.at or (-1, -1)
            for k, n in prepared(CHAIN.replace("id: t", "id: t\ndirection: down")).diagram.nodes.items()
        }
        self.assertEqual([at["a"][1], at["b"][1]], [0, 1])
        self.assertEqual(at["a"][0], at["b"][0])

    def test_pinned_nodes_keep_their_place(self):
        nodes = prepared(CHAIN.replace("b: {icon", "b: {at: [3, 2], icon")).diagram.nodes
        at = {k: n.at or (-1, -1) for k, n in nodes.items()}
        self.assertEqual(at["b"], (3, 2))
        self.assertFalse(nodes["b"].auto)
        self.assertEqual(at["c"][0], 4)
        self.assertNotEqual(at["c"], at["d"])

    def test_groups_and_cycles_are_clean(self):
        self.assertClean(problems(CHAIN))
        self.assertClean(problems(GROUPS))
        self.assertClean(problems(GROUPS.replace("id: t", "id: t\ndirection: down")))

    def test_nodes_follow_a_predecessor_on_row_zero(self):
        nodes = prepared(FED_FROM_ROW_ZERO).diagram.nodes
        row = {k: (n.at or (-1, -1))[1] for k, n in nodes.items()}
        self.assertLess(row["a"], row["b"])
        self.assertLess(row["p"], row["q"])

    def test_group_boxes_do_not_overlap(self):
        lay = prepared(GROUPS).layout
        self.assertFalse(lay.groups["front"].overlaps(lay.groups["back"]))
        self.assertFalse(lay.nodes["ops"].box.overlaps(lay.groups["back"]))


class Expand(Case):
    def test_writes_positions_and_routes(self):
        path = self.tmp() / "t.yml"
        path.write_text(GROUPS, encoding="utf-8")
        code, out, _ = cli("expand", str(path))
        self.assertEqual(code, 0)
        nodes = yaml.safe_load(out)["nodes"]
        self.assertTrue(all("at" in n for n in nodes.values()))
        a, b = prepared(GROUPS).layout, prepared(out).layout
        for k, p in a.edges.items():
            for (x0, y0), (x1, y1) in zip(p.points, b.edges[k].points, strict=True):
                self.assertAlmostEqual(x0, x1, delta=0.5)
                self.assertAlmostEqual(y0, y1, delta=0.5)


if __name__ == "__main__":
    unittest.main()
