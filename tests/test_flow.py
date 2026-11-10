from __future__ import annotations

import unittest

import yaml

from diagr.parse import loads
from diagr.unparse import to_yaml
from tests.support import ROOT, Case, problems
from tests.test_build import prepared

ROW = """
id: f
groups:
  box:
    title: Box
    tone: blue
    layout: {direction: row, gap: 30}
    nodes:
      a: {icon: api, title: A}
      b: {icon: queue, title: B, sub: [two lines, of text]}
      c: {icon: database, title: C}
"""

STACK = """
id: s
layout: {direction: column, gap: 20, align: stretch}
groups:
  top:
    title: Top
    tone: blue
    layout: row
    nodes:
      a: {icon: api, title: A}
  bottom:
    title: Bottom
    tone: teal
    layout: row
    nodes:
      b: {icon: queue, title: B}
      c: {icon: database, title: C}
  hidden:
    title: Hidden
    box: false
    layout: row
    nodes:
      d: {icon: user, title: D}
"""


class Rows(Case):
    def test_clean(self):
        self.assertClean(problems(ROW))
        self.assertClean(problems(STACK))

    def test_row_goes_left_to_right_in_file_order_with_the_gap(self):
        n = prepared(ROW).layout.nodes
        self.assertLess(n["a"].x, n["b"].x)
        self.assertLess(n["b"].x, n["c"].x)
        self.assertAlmostEqual(n["b"].box.x - n["a"].box.x1, 30)

    def test_nodes_in_a_row_line_up_by_their_icons(self):
        n = prepared(ROW).layout.nodes
        self.assertEqual(n["a"].y, n["b"].y)
        self.assertEqual(n["b"].y, n["c"].y)

    def test_the_box_fits_its_row(self):
        lay = prepared(ROW).layout
        r = lay.groups["box"]
        self.assertLess(r.x, lay.nodes["a"].box.x)
        self.assertGreater(r.x1, lay.nodes["c"].box.x1)


class Columns(Case):
    def test_column_goes_top_to_bottom_and_stretch_fills_the_width(self):
        g = prepared(STACK).layout.groups
        self.assertLess(g["top"].y1, g["bottom"].y)
        self.assertAlmostEqual(g["bottom"].y - g["top"].y1, 20)
        self.assertAlmostEqual(g["top"].w, g["bottom"].w)
        self.assertAlmostEqual(g["top"].x, g["bottom"].x)

    def test_an_invisible_box_draws_nothing(self):
        from diagr.render.svg import render_static

        p = prepared(STACK)
        svg = render_static(p.scene(), p.theme, "light")
        self.assertNotIn(">Hidden<", svg)
        self.assertIn(">Top<", svg)

    def test_at_inside_a_layout_is_an_error(self):
        self.assertReports(problems(ROW.replace("a: {icon: api,", "a: {at: [0, 0], icon: api,")), "remove 'at'")


GROW = """
id: g
layout: {direction: column, align: stretch}
groups:
  wide:
    title: Wide
    tone: neutral
    layout: {direction: row, gap: 0, justify: space-between}
    nodes:
      a: {icon: api, title: A}
      b: {icon: queue, title: B}
      c: {icon: queue, title: C}
      g: {icon: user, title: A much longer title}
  row:
    title: Row
    box: false
    layout: {direction: row, gap: 10}
    groups:
      fixed:
        title: Fixed
        tone: blue
        nodes:
          e: {icon: database, title: E}
      grows:
        title: Grows
        grow: 1
        tone: teal
        nodes:
          f: {icon: user, title: F}
"""


class GrowAndJustify(Case):
    def test_clean(self):
        self.assertClean(problems(GROW))

    def test_grow_takes_the_space_left(self):
        g = prepared(GROW).layout.groups
        self.assertAlmostEqual(g["grows"].x1, g["row"].x1)
        self.assertAlmostEqual(g["grows"].x - g["fixed"].x1, 10)

    def test_space_between_spreads_to_the_edges(self):
        lay = prepared(GROW).layout
        n, r = lay.nodes, lay.groups["wide"]
        self.assertAlmostEqual(n["a"].box.x - r.x, 20, delta=1)
        self.assertAlmostEqual(r.x1 - n["g"].box.x1, 20, delta=1)
        gaps = [n["b"].box.x - n["a"].box.x1, n["c"].box.x - n["b"].box.x1, n["g"].box.x - n["c"].box.x1]
        self.assertAlmostEqual(min(gaps), max(gaps), delta=1)


ALIGN = """
id: a
layout: {direction: column, align: stretch}
groups:
  ci:
    title: CI
    tone: neutral
    layout: {direction: row, justify: space-between}
    nodes:
      repo: {icon: branch, title: Repo}
      dev: {icon: upload, title: Deploy to dev, sub: REST API}
      prod: {icon: upload, title: Deploy to prod}
  keys:
    title: Keys
    tone: neutral
    layout: {direction: row, justify: space-around}
    nodes:
      k1: {align_x: dev, icon: key, title: Dev key}
      k2: {align_x: prod, icon: key, title: Prod key}
edges:
  k1 -> dev: {}
  k2 -> prod: {}
"""


class LineUp(Case):
    def test_clean_and_straight(self):
        self.assertClean(problems(ALIGN))
        lay = prepared(ALIGN).layout
        for a, b in (("k1", "dev"), ("k2", "prod")):
            self.assertEqual(lay.nodes[a].x, lay.nodes[b].x)
            self.assertEqual(len(lay.edges[f"{a}->{b}"].points), 2)

    def test_targets_stay_put(self):
        n = prepared(ALIGN).layout.nodes
        self.assertEqual(n["repo"].y, n["dev"].y)
        self.assertEqual(n["dev"].y, n["prod"].y)

    def test_stays_inside_its_box(self):
        lay = prepared(ALIGN.replace("title: Prod key}", "title: A prod key with a really long title}")).layout
        r, k = lay.groups["keys"], lay.nodes["k2"]
        self.assertLessEqual(k.box.x1, r.x1)

    def test_bad_targets(self):
        self.assertReports(problems(ALIGN.replace("align_x: dev,", "align_x: dve,")), "did you mean 'dev'")
        self.assertReports(problems(ALIGN.replace("align_x: dev,", "align_x: k1,")), "names the node itself")
        loop = ALIGN.replace("align_x: dev,", "align_x: k2,").replace("align_x: prod,", "align_x: k1,")
        self.assertReports(problems(loop), "loop")


class Centring(Case):
    def test_icon_and_labels_are_centred_in_a_row(self):
        yml = "id: c\ngroups:\n  card:\n    title: Card\n    title_at: middle\n    tone: blue\n    layout: row\n"
        yml += "    nodes:\n      a: {icon: api, title: A}\n"
        p = prepared(yml)
        r, nb = p.layout.groups["card"], p.layout.nodes["a"]
        above = nb.y - p.theme.size("icon") / 2 - r.y
        self.assertAlmostEqual(above, r.y1 - nb.box.y1, delta=0.5)


class HangingButtons(Case):
    def test_a_trigger_button_hangs_below_and_stays_clear_of_the_title(self):
        from diagr.layout.geometry import group_title_box

        yml = """
        id: h
        groups:
          ci:
            title: Development
            tone: neutral
            layout: {direction: row, gap: 60}
            nodes:
              repo: {icon: branch, title: Repos}
              build: {icon: refresh, title: Build}
        scenarios:
          s:
            trigger: {at: repo, label: Go}
            steps:
              - title: Go
                do: [activate build]
        """
        self.assertClean(problems(yml))
        p = prepared(yml)
        r, repo = p.layout.groups["ci"], p.layout.nodes["repo"]
        title = group_title_box(p.diagram.groups["ci"], r, p.theme)
        self.assertLessEqual(repo.box.y1, title.y)


class Expand(Case):
    def test_keeps_layout_and_box_keys(self):
        yml = STACK.replace("    box: false\n", "    box: false\n    title_at: top\n")
        d = loads(yml, "t.yml", ROOT)
        out = yaml.safe_load(to_yaml(d, yaml.safe_load(yml)))
        self.assertEqual(out["groups"]["top"]["layout"], "row")
        self.assertIs(out["groups"]["hidden"]["box"], False)
        self.assertEqual(out["groups"]["hidden"]["title_at"], "top")
        self.assertEqual(out["layout"], {"direction": "column", "gap": 20, "align": "stretch"})

    def test_keeps_boxes_behind(self):
        yml = "\n".join(
            [
                "id: e",
                "groups:",
                "  g:",
                "    title: prod",
                "    behind: {g-dev: dev}",
                "    tone: blue",
                "    nodes:",
                "      a: {at: [0, 0], icon: api}",
            ]
        )
        d = loads(yml, "t.yml", ROOT)
        self.assertEqual(yaml.safe_load(to_yaml(d, yaml.safe_load(yml)))["groups"]["g"]["behind"], {"g-dev": "dev"})


if __name__ == "__main__":
    unittest.main()
