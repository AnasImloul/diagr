"""The parts of the format that keep a diagram short: names from files, nodes made by edges, default titles,
shorthands, one 'scenario', steps keyed by their title, $parameters, edge targets in effects and automatic tones."""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from diagr.build import tone_groups
from diagr.layout.geometry import node_box
from diagr.model import Node
from diagr.parse import diagram_name, loads
from diagr.theme import load_theme
from tests.support import ROOT, Case, problems
from tests.test_build import prepared


def load(yml: str):
    return loads(textwrap.dedent(yml), "t.yml", ROOT)


def targets(do: str) -> list[list[str]]:
    """The targets of each effect in one step's 'do'."""
    d = load(f"edges:\n  (a b) -> c -> d:\n  c <-> e:\n  c --> f:\nscenario:\n  steps:\n    - S: [{do}]\n")
    return [e.targets for e in d.scenarios["main"].steps[0].effects]


class Names(Case):
    def test_a_diagram_is_named_after_its_file_or_its_folder(self):
        self.assertEqual(diagram_name(Path("shop/order-flow.yml")), "order-flow")
        self.assertEqual(diagram_name(Path("shop/order-flow/diagram.yml")), "order-flow")
        self.assertEqual(diagram_name(Path("my flow/diagram.yml")), "my-flow")
        self.assertEqual(diagram_name(Path("01-start.yml")), "d-01-start")
        self.assertEqual(diagram_name(Path("diagram.yml")), "diagram")

    def test_id_is_not_a_key(self):
        self.assertReports(problems("id: x\nedges:\n  a -> b:\n"), "unknown key 'id'")


class NodesFromEdges(Case):
    def test_edges_alone_make_a_diagram(self):
        d = load("edges:\n  web -> api -> db:\n")
        self.assertEqual(list(d.nodes), ["web", "api", "db"])
        self.assertEqual([n.title for n in d.nodes.values()], ["web", "api", "db"])
        self.assertClean(problems("edges:\n  web -> api -> db:\n"))

    def test_an_end_like_a_declared_id_is_a_warning(self):
        found = problems("nodes:\n  worker: Workers\nedges:\n  web -> wrker:\n")
        self.assertReports(found, "'wrker' is not declared, so the edge makes it a new node, did you mean 'worker'?")
        self.assertEqual({p.level for p in found}, {"warning"})

    def test_an_edge_to_a_group_or_a_box_behind_makes_no_node(self):
        d = load("groups:\n  g: {title: G, behind: {g-dev: dev}, nodes: {a: A}}\nedges:\n  x -> g:\n  y -> g-dev:\n")
        self.assertEqual(sorted(d.nodes), ["a", "x", "y"])

    def test_an_instance_id_is_never_made_up(self):
        self.assertReports(problems("edges:\n  a -> b/db:\n"), "unknown node or group 'b/db'")


class Shorthands(Case):
    def test_a_node_is_a_mapping_its_title_or_nothing(self):
        d = load("nodes:\n  api: API\n  web:\n  db: {icon: database}\n  bus: {junction: true}\n  pic: {title: ''}\n")
        self.assertEqual(
            {k: n.title for k, n in d.nodes.items()}, {"api": "API", "web": "web", "db": "db", "bus": "", "pic": ""}
        )

    def test_a_group_title_defaults_to_its_id(self):
        d = load("groups:\n  back:\n    nodes: {a: A}\n")
        self.assertEqual(d.groups["back"].title, "back")

    def test_a_node_without_an_icon_is_not_a_warning(self):
        self.assertClean(problems("nodes:\n  a: A\n  b: B\nedges:\n  a -> b:\n"))


class OneScenario(Case):
    def test_scenario_is_the_scenario_called_main(self):
        d = load("edges:\n  a -> b:\nscenario:\n  steps:\n    - Go: [flow a -> b]\nviews:\n  v: {scenario: main}\n")
        self.assertEqual(list(d.scenarios), ["main"])

    def test_scenario_and_scenarios_together_is_an_error(self):
        yml = "edges:\n  a -> b:\nscenario:\n  steps: [{x: [done a]}]\nscenarios:\n  s:\n    steps: [{x: [done a]}]\n"
        self.assertReports(problems(yml), "use either 'scenario' or 'scenarios', not both")


class Steps(Case):
    def test_a_step_is_its_title_with_effects_fields_or_nothing(self):
        d = load("""
            edges:
              a -> b:
            scenario:
              steps:
                - First: [done a]
                - Second:
                    at: b
                    text: Then b.
                    do: [done b]
                - "Third: the end":
        """)
        steps = d.scenarios["main"].steps
        self.assertEqual([s.title for s in steps], ["First", "Second", "Third: the end"])
        self.assertEqual((steps[1].at, steps[1].text), ("b", "Then b."))
        self.assertEqual(steps[2].effects, [])

    def test_a_step_with_title_beside_its_fields_is_an_error(self):
        found = problems("edges:\n  a -> b:\nscenario:\n  steps:\n    - title: Go\n      do: [done a]\n")
        self.assertReports(found, "expected a step: 'Title: [effects]'")


class Parameters(Case):
    COMPONENT = """
        components:
          box:
            params: {name: {required: true}, version: "1"}
            nodes:
              a: {icon: api, title: $name, sub: v$version costs $5 and $$name}
            actions:
              go: [{repeat 2: ['a.sub: try $i of 2']}]
        instances:
          x: {component: box, with: {name: Alpha, version: 3}}
    """

    def test_dollar_name_fills_in_and_double_dollar_is_a_dollar(self):
        d = load(self.COMPONENT)
        self.assertEqual(d.nodes["x/a"].title, "Alpha")
        self.assertEqual(d.nodes["x/a"].sub, ["v3 costs $5 and $name"])

    def test_dollar_i_is_the_round_of_a_repeat(self):
        p = prepared(textwrap.dedent(self.COMPONENT) + "scenario:\n  steps:\n    - Go: [go x]\n")
        frames = [f.to_json()["set"] for f in p.scenarios["main"].frames]
        texts = [v for f in frames for k, v in f.items() if k.startswith("t:x/a:sub")]
        self.assertEqual(texts, ["try 1 of 2", "try 2 of 2"])

    def test_an_unknown_parameter_is_reported(self):
        found = problems(self.COMPONENT.replace("title: $name", "title: $nmae"))
        self.assertReports(found, "uses unknown parameter $nmae")


class EdgeTargets(Case):
    def test_targets_are_written_as_edge_keys_are(self):
        self.assertEqual(targets("draw (a b) -> c -> d"), [["a->c", "b->c", "c->d"]])
        self.assertEqual(targets("draw c <-> e"), [["c->e", "e->c"]])
        self.assertEqual(targets("draw c --> f, draw c->f"), [["c->f"], ["c->f"]])
        self.assertEqual(targets("done (a b) c"), [["a", "b", "c"]])
        self.assertEqual(targets("draw a -> c b -> c 700ms"), [["a->c", "b->c"]])

    def test_a_label_change_names_its_edge_with_spaces(self):
        d = load("edges:\n  a --> b: x\nscenario:\n  steps:\n    - S: ['a --> b.label: y', a -> b.label: z]\n")
        self.assertEqual([e.targets for e in d.scenarios["main"].steps[0].effects], [["a->b.label"], ["a->b.label"]])

    def test_a_dangling_arrow_or_parenthesis_is_an_error(self):
        base = "edges:\n  a -> b:\nscenario:\n  steps:\n    - S: [{}]\n"
        self.assertReports(problems(base.format("draw a ->")), "'draw': '->' needs a target on each side")
        self.assertReports(problems(base.format("draw (a b -> b")), "write targets side by side in one pair")
        self.assertReports(problems(base.format("draw a) -> b")), "')' without '('")


class Tones(Case):
    def tones(self, yml: str) -> dict[str, str | None]:
        d = load(yml)
        tone_groups(d, load_theme("default", ROOT))
        return {k: g.tone for k, g in d.groups.items()}

    def test_boxes_holding_boxes_are_neutral_and_the_rest_take_turns(self):
        tones = self.tones("""
            groups:
              outer:
                groups:
                  one: {nodes: {a: A}}
                  two: {nodes: {b: B}}
              three: {nodes: {c: C}}
        """)
        self.assertEqual(tones, {"outer": "neutral", "one": "blue", "two": "teal", "three": "violet"})

    def test_a_set_tone_stays_and_a_child_skips_its_parents(self):
        tones = self.tones("""
            groups:
              set: {tone: amber, nodes: {a: A}}
              outer:
                tone: blue
                groups:
                  inner: {nodes: {b: B}}
              plain: {box: false, nodes: {c: C}}
        """)
        self.assertEqual(tones, {"set": "amber", "outer": "blue", "inner": "teal", "plain": "neutral"})

    def test_a_components_group_has_one_tone_in_every_instance(self):
        tones = self.tones("""
            components:
              region:
                groups:
                  data: {nodes: {db: DB}}
            instances:
              a: {component: region}
              b: {component: region}
            groups:
              other: {nodes: {x: X}}
        """)
        self.assertEqual(tones, {"a/data": "blue", "b/data": "blue", "other": "teal"})


class Marks(Case):
    def test_a_nodes_box_reaches_its_mark(self):
        t = load_theme("default", ROOT)
        plain = node_box(Node("a", None, title="Queue"), 0, 0, t, 0).box
        marked = node_box(Node("a", None, title="Queue", mark="removed"), 0, 0, t, 0).box
        self.assertGreater(marked.w, plain.w + 2 * 40)


if __name__ == "__main__":
    unittest.main()
