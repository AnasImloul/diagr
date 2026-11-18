from __future__ import annotations

import unittest

import yaml

from tests.support import ROOT, Case, problems
from tests.test_build import cli, prepared

CHAIN = """
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

# Edges between three sibling groups in both directions: g before h before k, and edges from k and h back into g.
BOTH_WAYS = """
groups:
  g: {title: G, nodes: {a1: {icon: server, title: A1}, a2: {icon: server, title: A2}}}
  h: {title: H, nodes: {b1: {icon: server, title: B1}, b2: {icon: server, title: B2}}}
  k: {title: K, nodes: {c1: {icon: server, title: C1}, c2: {icon: server, title: C2}}}
edges:
  a1 -> b1: {}
  b1 -> c1: {}
  c1 -> a2: {}
  b2 -> a2: {}
  c2 -> b2: {}
"""

# x goes before y, and a path from y back into x runs through a node of their parent.
THROUGH_PARENT = """
groups:
  p:
    title: P
    nodes:
      u: {icon: server, title: U}
    groups:
      x: {title: X, nodes: {x1: {icon: server, title: X1}, x2: {icon: server, title: X2}}}
      y: {title: Y, nodes: {y1: {icon: server, title: Y1}, y2: {icon: server, title: Y2}}}
edges:
  x1 -> y1: {}
  y2 -> u: {}
  u -> x2: {}
"""


def shared(points: dict[str, list[tuple[float, float]]]) -> list[tuple[str, str]]:
    """Pairs of paths with a stretch longer than 4px on one line."""
    runs = []
    for k, pts in points.items():
        for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
            if abs(ay - by) < 0.5:
                runs.append((k, "h", round(ay, 1), min(ax, bx), max(ax, bx)))
            elif abs(ax - bx) < 0.5:
                runs.append((k, "v", round(ax, 1), min(ay, by), max(ay, by)))
    return [
        (a[0], b[0])
        for i, a in enumerate(runs)
        for b in runs[i + 1 :]
        if a[0] != b[0] and a[1:3] == b[1:3] and min(a[4], b[4]) - max(a[3], b[3]) > 4
    ]


# Three rows p -> m -> q, each with an edge from its q back to its p: the backward edges leave one column and turn
# into another.
BACK = (
    """
nodes:
"""
    + "".join(f"  {k}{i}: {{icon: server, title: {k.upper()}{i}}}\n" for k in "pmq" for i in range(3))
    + """edges:
"""
    + "".join(f"  p{i} -> m{i} -> q{i}: {{}}\n  q{i} -> p{i}: {{}}\n" for i in range(3))
)

# A group with pinned nodes, and one whose nodes are placed after it.
BESIDE_PINNED = """
groups:
  g:
    title: G
    nodes:
      a: {at: [0, 0], icon: server, title: A}
      b: {at: [1, 0], icon: server, title: B}
  h:
    title: H
    nodes:
      x: {icon: server, title: X}
      y: {icon: server, title: Y}
edges:
  a -> b: {}
  a -> x: {}
  b -> y: {}
"""


class Placement(Case):
    def test_layers_follow_edges(self):
        nodes = prepared(CHAIN).diagram.nodes
        at = {k: n.at or (-1, -1) for k, n in nodes.items()}
        self.assertEqual(at["a"][0], 0)
        self.assertGreater(at["b"][0], at["a"][0])
        self.assertGreater(at["c"][0], at["b"][0])
        self.assertEqual(at["c"][0], at["d"][0])
        self.assertNotEqual(at["c"][1], at["d"][1])
        self.assertTrue(all(n.auto for n in nodes.values()))

    def test_direction_down_swaps_axes(self):
        at = {k: n.at or (-1, -1) for k, n in prepared("direction: down\n" + CHAIN).diagram.nodes.items()}
        self.assertEqual(at["a"][1], 0)
        self.assertGreater(at["b"][1], at["a"][1])
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
        self.assertClean(problems("direction: down\n" + GROUPS))

    def test_nodes_follow_a_predecessor_on_row_zero(self):
        nodes = prepared(FED_FROM_ROW_ZERO).diagram.nodes
        row = {k: (n.at or (-1, -1))[1] for k, n in nodes.items()}
        self.assertLess(row["a"], row["b"])
        self.assertLess(row["p"], row["q"])

    def test_long_chain(self):
        n = 1100
        nodes = "".join(f"  n{i}: {{icon: server, title: N{i}}}\n" for i in range(n))
        edges = "".join(f"  n{i} -> n{i + 1}: {{}}\n" for i in range(n - 1))
        self.assertClean(problems(f"nodes:\n{nodes}edges:\n{edges}"))

    def test_edges_against_the_group_order_do_not_push_groups_apart(self):
        for yml, last in ((BOTH_WAYS, 6), (THROUGH_PARENT, 3)):
            with self.subTest(last=last):
                nodes = prepared(yml).diagram.nodes
                self.assertLessEqual(max((n.at or (0, 0))[0] for n in nodes.values()), last)

    def test_backward_edge_turns_before_the_groups_it_enters(self):
        self.assertClean(problems(BOTH_WAYS))
        lay = prepared(BOTH_WAYS).layout
        self.assertLess(lay.edges["c1->a2"].points[-2][0], lay.groups["g"].x)

    def test_rows_fit_the_theme_in_use(self):
        base = self.tmp()
        (base / "big.yml").write_text(
            "extends: default\nsizes: {icon: 110, title: 22, line: 30, group_top: 70}\n", encoding="utf-8"
        )
        tall = ", sub: [one, two]}"
        yml = (
            "theme: ./big.yml\nnodes:\n  s: {icon: server, title: S}\n"
            + "".join(f"  {k}: {{icon: server, title: {k.upper()}{tall}\n" for k in "abc")
            + "edges:\n  s -> (a b c): {}\n"
        )
        self.assertClean(problems(yml, base))

    def test_wide_nodes_side_by_side_when_the_flow_runs_down(self):
        yml = """
        direction: down
        nodes:
          s: {icon: server, title: Source}
          a: {icon: server, title: Customer relationship management platform}
          b: {icon: server, title: Enterprise resource planning integration hub}
          c: {icon: server, title: Customer records}
        edges:
          s -> (a b c): {}
        """
        self.assertClean(problems(yml))

    def test_wide_node_keeps_its_neighbours_along_the_flow_apart(self):
        yml = """
        nodes:
          s: {icon: server, title: S}
          a: {icon: server, title: A customer relationship management platform for every region}
          t: {icon: server, title: T}
        edges:
          s -> a -> t: {}
        """
        self.assertClean(problems(yml))

    def test_lane_turns_late_rather_than_run_along_a_busy_row(self):
        yml = """
        groups:
          g:
            title: G
            nodes:
              a: {icon: server, title: A}
              b: {icon: server, title: B}
              x: {icon: server, title: X}
          h:
            title: H
            nodes:
              c: {icon: server, title: C}
              d: {icon: server, title: D}
              z: {icon: server, title: Z}
        edges:
          a -> b: {}
          b -> x: {}
          x -> z: {}
          a -> c: {}
          b -> d: {}
        """
        self.assertClean(problems(yml))

    def test_lanes_turn_clear_of_a_wide_title(self):
        yml = """
        nodes:
          s: {icon: server, title: Source}
          a: {icon: server, title: Customer relationship management platform}
          b: {icon: server, title: Enterprise resource planning integration hub}
          c: {icon: server, title: Customer records}
          e: {icon: server, title: Stock}
        edges:
          s -> (a b c e): {}
        """
        self.assertClean(problems(yml))

    def test_loose_nodes_keep_clear_of_groups_with_a_bigger_theme(self):
        theme = self.tmp() / "big.yml"
        theme.write_text("extends: default\nsizes: {icon: 110, title: 22, line: 30, group_top: 70}\n", encoding="utf-8")
        example = ROOT / "examples/event-driven/diagram.yml"
        self.assertClean(problems(example.read_text(encoding="utf-8"), example.parent, str(theme)))

    def test_backward_edges_run_on_lines_of_their_own(self):
        lay = prepared(BACK).layout
        self.assertEqual(shared({f"q{i}->p{i}": lay.edges[f"q{i}->p{i}"].points for i in range(3)}), [])

    def test_arrowheads_into_a_full_side_share_points(self):
        sources = " ".join(f"s{i}" for i in range(8))
        nodes = "".join(f"  s{i}: {{icon: server, title: S{i}}}\n" for i in range(8))
        lay = prepared(f"nodes:\n{nodes}  t: {{icon: server, title: T}}\nedges:\n  ({sources}) -> t: {{}}\n").layout
        ends = sorted({round(lay.edges[f"s{i}->t"].points[-1][1], 1) for i in range(8)})
        self.assertEqual(len(ends), 4)
        self.assertGreaterEqual(min(b - a for a, b in zip(ends, ends[1:], strict=False)), 12)

    def test_output_does_not_depend_on_string_hashing(self):
        import os
        import subprocess
        import sys

        folder = self.tmp()
        files = []
        for name, yml in (("back", BACK), ("groups", GROUPS), ("both", BOTH_WAYS)):
            (folder / f"{name}.yml").write_text(yml, encoding="utf-8")
            files.append(str(folder / f"{name}.yml"))
        seen = set()
        for seed in ("1", "2", "3"):
            out = folder / seed
            subprocess.run(
                [sys.executable, "-m", "diagr", "build", "--svg", *files, "-o", str(out)],
                env={**os.environ, "PYTHONHASHSEED": seed},
                check=True,
                capture_output=True,
            )
            seen.add(tuple(sorted(f.read_text(encoding="utf-8") for f in out.glob("*.svg"))))
        self.assertEqual(len(seen), 1)

    def test_a_group_moves_past_one_with_pinned_nodes(self):
        lay = prepared(BESIDE_PINNED).layout
        self.assertGreater(lay.groups["h"].x, lay.groups["g"].x1)

    def test_lane_turns_before_a_pinned_neighbour_on_its_row(self):
        self.assertClean(problems(BESIDE_PINNED))

    def test_px_round_up_to_a_twentieth_of_a_cell(self):
        from diagr.layout.auto import _cells

        self.assertEqual([_cells(px, 160) for px in (0, 1, 8, 160, 161)], [0, 0.05, 0.05, 1.0, 1.05])

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
