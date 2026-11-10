from __future__ import annotations

import textwrap
import unittest

from diagr.build import build_files, prepare_all
from diagr.parse import loads
from tests.support import ROOT, Case, problems

BASE = """
id: t
groups:
  back:
    title: Backend
    tone: teal
    groups:
      data:
        title: Data
        tone: amber
        nodes:
          db: {icon: database, title: DB}
    nodes:
      api: {icon: api, title: API}
nodes:
  web: {icon: browser, title: Web}
  ops: {icon: user, title: Ops}
edges:
  web -> api: {}
  api -> db: {}
  ops -> db: {}
scenarios:
  go:
    trigger: {at: web, label: Go}
    steps:
      - title: Go
        do: [flow web -> api -> db]
views:
  backend: {title: Backend only, include: [back]}
  front: {include: [web, back], exclude: [data], scenarios: [go]}
"""


def views(yml: str):
    d = loads(textwrap.dedent(yml), "t.yml", ROOT)
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


DYNAMIC = """
id: d
nodes:
  web: {icon: browser, title: Web}
  api: {icon: api, title: API}
  db: {icon: database, title: DB}
  cache: {icon: cache, title: Cache}
  ops: {icon: user, title: Ops}
edges:
  web -> api: request
  api -> db: write
  api -> cache: {}
  ops -> db: {}
  web -> ops: {}
scenarios:
  go:
    steps:
      - title: Ask
        do: [flow web -> api]
      - title: Store
        do:
          - parallel: [flow api -> db, flow api -> cache]
      - title: Again
        do: [draw web->api]
views:
  story: {scenario: go}
"""


class DynamicViews(Case):
    def test_keeps_what_the_scenario_uses(self):
        v = views(DYNAMIC)["d-story"].diagram
        self.assertEqual(set(v.nodes), {"web", "api", "db", "cache"})
        self.assertEqual(set(v.edges), {"web->api", "api->db", "api->cache"})
        self.assertEqual(list(v.scenarios), ["go"])

    def test_edges_are_numbered_by_step(self):
        v = views(DYNAMIC)["d-story"]
        self.assertEqual(v.diagram.numbers, {"web->api": "1,3", "api->db": "2", "api->cache": "2"})
        self.assertTrue(all(v.layout.edges[k].badge_box for k in v.diagram.numbers))
        self.assertEqual(views(DYNAMIC)["d"].diagram.numbers, {})

    def test_no_numbers_without_a_step_list(self):
        self.assertEqual(views(DYNAMIC.replace("id: d", "id: d\nstep_list: false"))["d-story"].diagram.numbers, {})

    def test_include_adds_context(self):
        v = views(DYNAMIC.replace("{scenario: go}", "{scenario: go, include: [ops, db]}"))["d-story"].diagram
        self.assertIn("ops", v.nodes)
        self.assertIn("ops->db", v.edges)
        self.assertNotIn("web->ops", v.edges)

    def test_unknown_scenario(self):
        self.assertReports(problems(DYNAMIC.replace("{scenario: go}", "{scenario: og}")), "unknown scenario 'og'")

    def test_clean(self):
        self.assertClean(problems(DYNAMIC))


if __name__ == "__main__":
    unittest.main()
