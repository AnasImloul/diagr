from __future__ import annotations

import textwrap
import unittest

from diagr.build import build_files, prepare_all
from diagr.parse import from_tree
from diagr.source import load
from tests.support import ROOT, Case, problems

BASE = """
id: t
groups:
  back: {title: Backend, tone: teal}
  data: {title: Data, in: back, tone: amber}
nodes:
  web: {icon: browser, title: Web, trigger: Go}
  api: {in: back, icon: api, title: API}
  db: {in: data, icon: database, title: DB}
  ops: {icon: user, title: Ops}
edges:
  web -> api: {}
  api -> db: {}
  ops -> db: {}
scenarios:
  go:
    steps:
      - title: Go
        do: [flow web -> api -> db]
views:
  backend: {title: Backend only, include: [back]}
  front: {include: [web, back], exclude: [data], scenarios: [go]}
"""


def views(yml: str):
    d = from_tree(load(textwrap.dedent(yml), "t.yml"), "t.yml", ROOT)
    return {p.diagram.id: p for p in prepare_all(d)}


class Views(Case):
    def test_subset_of_nodes_edges_and_groups(self):
        v = views(BASE.replace("exclude: [data], scenarios: [go]", "exclude: [data]"))
        b = v["t-backend"].diagram
        self.assertEqual(set(b.nodes), {"api", "db"})
        self.assertEqual(set(b.edges), {"api->db"})
        self.assertEqual(set(b.groups), {"back", "data"})
        self.assertEqual(b.title, "Backend only")
        f = v["t-front"].diagram
        self.assertEqual(set(f.nodes), {"web", "api"})
        self.assertEqual(set(f.groups), {"back"})

    def test_placed_nodes_close_up(self):
        b = views(BASE.replace("exclude: [data], scenarios: [go]", "exclude: [data]"))["t-backend"].diagram
        self.assertEqual(b.nodes["api"].at, (0, 0))

    def test_scenarios_and_triggers(self):
        v = views(BASE.replace("exclude: [data], scenarios: [go]", "exclude: [data]"))
        self.assertEqual(v["t-front"].diagram.scenarios, {})
        self.assertIsNone(v["t-front"].diagram.nodes["web"].trigger)
        self.assertEqual(v["t"].diagram.nodes["web"].trigger, "Go")

    def test_kept_scenario_must_fit_the_view(self):
        self.assertReports(problems(BASE), "in view 'front'", "error")
        self.assertClean(problems(BASE.replace("exclude: [data], scenarios: [go]", "scenarios: [go]")))

    def test_unknown_ids(self):
        self.assertReports(problems(BASE.replace("include: [back]}", "include: [bak]}")), "did you mean 'back'")
        self.assertReports(problems(BASE.replace("scenarios: [go]", "scenarios: [og]")), "unknown scenario 'og'")
        self.assertReports(problems(BASE.replace("include: [back]}", "include: [web], exclude: [web]}")), "no nodes")

    def test_files(self):
        path = self.tmp() / "t.yml"
        path.write_text(textwrap.dedent(BASE.replace("exclude: [data], scenarios: [go]", "exclude: [data]")))
        names = sorted(f.name for f in build_files(path, self.tmp())[0])
        self.assertIn("t-backend-light.svg", names)
        self.assertIn("t-front.html", names)
        self.assertEqual(len(names), 9)


if __name__ == "__main__":
    unittest.main()
