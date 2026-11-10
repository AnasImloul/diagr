from __future__ import annotations

import unittest

from tests.support import Case, problems
from tests.test_build import prepared

BOXES = """
id: b
groups:
  top: {title: Top, tone: blue}
  bottom: {title: Bottom, tone: teal}
nodes:
  a: {in: top, at: [0, 0], icon: api, title: A}
  b: {in: top, at: [2, 0], icon: api, title: B}
  c: {in: bottom, at: [0, 2], icon: queue, title: C}
  d: {in: bottom, at: [2, 2], icon: queue, title: D}
  e: {at: [1, 3.5], icon: user, title: E}
edges:
  e -> bottom: deploy
  bottom -> top: {}
  e -> d: {route: [right, up]}
"""


class EdgesToBoxes(Case):
    def test_clean(self):
        self.assertClean(problems(BOXES))

    def test_node_to_box_goes_straight_at_the_node(self):
        lay = prepared(BOXES).layout
        pts = lay.edges["e->bottom"].points
        self.assertEqual(len(pts), 2)
        self.assertEqual(pts[0][0], pts[1][0])
        self.assertEqual(pts[0][0], lay.nodes["e"].x)
        self.assertAlmostEqual(pts[1][1], lay.groups["bottom"].y1)

    def test_box_to_box_goes_straight_in_the_overlap(self):
        lay = prepared(BOXES).layout
        (x0, y0), (x1, y1) = lay.edges["bottom->top"].points
        self.assertEqual(x0, x1)
        self.assertAlmostEqual(y0, lay.groups["bottom"].y)
        self.assertAlmostEqual(y1, lay.groups["top"].y1)

    def test_named_port_on_a_box(self):
        lay = prepared(BOXES.replace("bottom -> top: {}", "bottom@top+40 -> top: {}")).layout
        r = lay.groups["bottom"]
        self.assertEqual(lay.edges["bottom->top"].points[0][0], r.x + r.w / 2 + 40)

    def test_named_port_near_the_edge_of_a_box_still_goes_straight(self):
        lay = prepared(BOXES.replace("bottom -> top: {}", "bottom@top+300 -> top: {}")).layout
        pts = lay.edges["bottom->top"].points
        self.assertEqual(len(pts), 2)
        self.assertLess(lay.groups["top"].x1 - pts[0][0], 12)

    def test_misaligned_ports_on_the_same_axis_take_a_z(self):
        lay = prepared(BOXES.replace("bottom -> top: {}", "bottom@top+190 -> top@bottom-190: {}")).layout
        (x0, y0), (_, ya), (_, yb), (x3, y3) = lay.edges["bottom->top"].points
        self.assertEqual(ya, yb)
        self.assertEqual(ya, (y0 + y3) / 2)
        self.assertNotEqual(x0, x3)

    def test_box_to_box_jogs_round_titles_that_cover_the_overlap(self):
        yml = """
        id: z
        layout: {direction: column, gap: 24, align: start}
        groups:
          ws: {title: dev, tone: neutral, layout: {direction: column, align: stretch}}
          zone: {title: Zone, title_at: top, in: ws, tone: violet}
          stack: {title: prod workspace, behind: {stack-dev: dev workspace}, tone: neutral, layout: row}
          card: {title: Data processing, in: stack, title_at: middle, tone: blue, layout: row}
        nodes:
          z: {in: zone, icon: lake, title: Lake}
          c: {in: card, icon: notebook, title: Notebook}
        edges:
          zone -> card: {}
        """
        self.assertClean(problems(yml))
        self.assertEqual(len(prepared(yml).layout.edges["zone->card"].points), 4)

    def test_unknown_end_and_own_group(self):
        self.assertReports(problems(BOXES.replace("e -> bottom", "e -> botom")), "unknown node or group 'botom'")
        self.assertReports(problems(BOXES.replace("e -> bottom", "c -> bottom")), "to the group 'bottom' it is in")

    def test_flow_passes_through_a_box(self):
        yml = BOXES + "scenarios:\n  go:\n    steps:\n      - title: Go\n        do: [flow e -> bottom -> top]\n"
        self.assertClean(problems(yml))


ALIGN = """
id: a
groups:
  one: {title: One, tone: blue}
  two: {title: Two, tone: teal}
nodes:
  a: {in: one, at: [0.4, 0], icon: api, title: A}
  b: {in: one, at: [2, 0], icon: api, title: B}
  c: {in: two, at: [0, 2], icon: queue, title: C}
  d: {in: two, at: [2.3, 2], icon: queue, title: D}
"""


class Alignment(Case):
    def test_stacked_boxes_share_their_sides(self):
        g = prepared(ALIGN).layout.groups
        self.assertAlmostEqual(g["one"].x, g["two"].x)
        self.assertAlmostEqual(g["one"].x1, g["two"].x1)
        self.assertClean(problems(ALIGN))

    def test_flush_children_follow_their_parent(self):
        yml = """
        id: f
        groups:
          ws: {title: Workspace, tone: neutral}
          inner: {title: Inner, in: ws, tone: blue, at: [0, 0], span: [2, 1]}
          below: {title: Below, tone: teal}
        nodes:
          a: {in: inner, at: [0.5, 0], icon: api, title: A}
          c: {in: below, at: [0, 2], icon: queue, title: C}
          d: {in: below, at: [1.4, 2], icon: queue, title: D}
        """
        g = prepared(yml).layout.groups
        self.assertAlmostEqual(g["ws"].x1, g["below"].x1)
        self.assertAlmostEqual(g["ws"].x1 - g["inner"].x1, 12)

    def test_contents_stay_centred_when_a_box_grows(self):
        yml = """
        id: c
        groups:
          left: {title: Left, tone: neutral}
          zone: {title: Zone, in: left, tone: violet, at: [0, 0], span: [2, 1]}
          right: {title: Right, tone: neutral}
          below: {title: Below, tone: teal}
        nodes:
          lake: {in: zone, at: [0.5, 0], icon: lake, title: Lake}
          r: {in: right, at: [3, 0], icon: api, title: R}
          c: {in: below, at: [-0.5, 2], icon: queue, title: C}
          d: {in: below, at: [3, 2], icon: queue, title: D}
        """
        lay = prepared(yml).layout
        zone, lake = lay.groups["zone"], lay.nodes["lake"]
        self.assertGreater(lay.groups["zone"].w, 2 * 215 - 24)
        self.assertAlmostEqual(lake.x, zone.x + zone.w / 2, delta=1)

    def test_far_apart_sides_stay(self):
        g = prepared(ALIGN.replace("at: [0.4, 0]", "at: [1.4, 0]")).layout.groups
        self.assertNotAlmostEqual(g["one"].x, g["two"].x)

    def test_can_be_turned_off(self):
        g = prepared(ALIGN.replace("id: a", "id: a\nalign: false")).layout.groups
        self.assertNotAlmostEqual(g["one"].x, g["two"].x)

    def test_never_grows_over_a_node(self):
        yml = ALIGN + "  e: {at: [-0.5, 0], icon: user, title: E}\n"
        g = prepared(yml).layout.groups
        self.assertNotAlmostEqual(g["one"].x, g["two"].x)


class Titles(Case):
    def test_title_at_places_the_title(self):
        from diagr.layout.geometry import group_title_box

        base = """
        id: t
        groups:
          g: {title: Zone, tone: blue%s}
        nodes:
          a: {in: g, at: [0, 0], icon: api, title: A}
        """
        for at, top, centred in (
            ("", False, False),
            ("top", True, True),
            ("top-left", True, False),
            ("bottom", False, True),
        ):
            with self.subTest(at or "default"):
                p = prepared(base % (f", title_at: {at}" if at else ""))
                g, r = p.diagram.groups["g"], p.layout.groups["g"]
                box = group_title_box(g, r, p.theme)
                self.assertEqual(box.y < r.y + r.h / 2, top)
                self.assertEqual(abs(box.x + box.w / 2 - (r.x + r.w / 2)) < 1, centred)

    def test_middle_title_is_a_heading_beside_the_nodes(self):
        from diagr.layout.geometry import group_title_box

        yml = """
        id: t
        groups:
          card: {title: Orchestration of all the jobs, sub: run_every_job, title_at: middle, tone: blue}
        nodes:
          a: {in: card, at: [0, 0], icon: pipeline, title: Pipeline}
        """
        self.assertClean(problems(yml))
        p = prepared(yml)
        r, a = p.layout.groups["card"], p.layout.nodes["a"]
        box = group_title_box(p.diagram.groups["card"], r, p.theme, [a.box])
        self.assertGreater(box.x, a.box.x1)
        self.assertLessEqual(box.x1, r.x1)
        self.assertAlmostEqual(box.y + box.h / 2, r.y + r.h / 2, delta=1)

    def test_a_top_title_gets_room_above_the_contents(self):
        yml = """
        id: t
        groups:
          o: {title: Outer, tone: neutral, title_at: top}
          i: {title: Inner, in: o, tone: blue}
        nodes:
          a: {in: i, at: [0, 0], icon: api, title: A}
        """
        self.assertClean(problems(yml))
        g = prepared(yml).layout.groups
        self.assertGreater(g["i"].y - g["o"].y, 30)
        self.assertLess(g["o"].y1 - g["i"].y1, 20)

    def test_node_over_a_group_title(self):
        yml = """
        id: t
        groups:
          g: {title: A long group title here, tone: blue, at: [0, 0], span: [2, 1]}
        nodes:
          a: {in: g, at: [0.2, 0.45], icon: api, title: A, trigger: Run}
        scenarios:
          s:
            steps:
              - title: Go
                do: [activate a]
        """
        self.assertReports(problems(yml), "node 'a' covers the title of group 'g'", "warning")


STACKED = """
id: s
groups:
  ws: {title: prod workspace, behind: {ws-dev: dev workspace}, tone: neutral}
nodes:
  a: {in: ws, at: [0, 0], icon: api, title: A}
  b: {in: ws, at: [2, 0], icon: api, title: B}
  dev: {at: [0.5, 2], icon: upload, title: Deploy to dev}
  prod: {at: [1.5, 2], icon: upload, title: Deploy to prod}
  up: {at: [-1.5, -1.2], icon: user, title: Above}
edges:
  dev -> ws-dev: dev workspace
  prod -> ws: prod workspace
  up -> ws-dev: {route: [right, down]}
"""


class Stacked(Case):
    def test_clean(self):
        self.assertClean(problems(STACKED))

    def test_box_behind_is_offset_up_and_left(self):
        lay = prepared(STACKED).layout
        front, (lid, back) = lay.groups["ws"], lay.layers["ws"][0]
        self.assertEqual(lid, "ws-dev")
        self.assertEqual((front.x - back.x, front.y - back.y), (24, 28))
        self.assertEqual((back.w, back.h), (front.w, front.h))

    def test_edge_to_the_box_behind_stops_at_the_front_without_a_tip(self):
        lay = prepared(STACKED).layout
        dev, prod = lay.edges["dev->ws-dev"], lay.edges["prod->ws"]
        self.assertFalse(dev.tip)
        self.assertAlmostEqual(dev.points[-1][1], lay.groups["ws"].y1)
        self.assertTrue(prod.tip)

    def test_edge_reaching_the_visible_strip_keeps_its_tip(self):
        lay = prepared(STACKED).layout
        p = lay.edges["up->ws-dev"]
        self.assertTrue(p.tip)
        self.assertAlmostEqual(p.points[-1][1], lay.layers["ws"][0][1].y)

    def test_ids_must_be_unique(self):
        self.assertReports(problems(STACKED.replace("ws-dev: dev workspace", "a: dev workspace")), "reuses an id")

    def test_alignment_uses_the_whole_stack(self):
        yml = """
        id: h
        groups:
          ws: {title: prod, behind: {ws-dev: dev}, tone: neutral}
          ci: {title: CI, tone: blue}
        nodes:
          a: {in: ws, at: [0.3, 0], icon: api, title: A}
          b: {in: ws, at: [2, 0], icon: api, title: B}
          c: {in: ci, at: [0, 2], icon: queue, title: C}
          d: {in: ci, at: [2, 2], icon: queue, title: D}
        """
        lay = prepared(yml).layout
        back = lay.layers["ws"][0][1]
        self.assertAlmostEqual(back.x, lay.groups["ci"].x)
        self.assertAlmostEqual(lay.groups["ws"].x1, lay.groups["ci"].x1)
        self.assertAlmostEqual(lay.groups["ws"].x - back.x, 24)

    def test_parent_fits_the_whole_stack(self):
        yml = STACKED.replace("  ws: {title", "  outer: {title: Outer, tone: blue}\n  ws: {in: outer, title")
        lay = prepared(yml).layout
        back = lay.layers["ws"][0][1]
        self.assertLess(lay.groups["outer"].x, back.x)
        self.assertLess(lay.groups["outer"].y, back.y)


if __name__ == "__main__":
    unittest.main()
