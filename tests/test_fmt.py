from __future__ import annotations

import re
import textwrap
import unittest

import yaml

from diagr.fmt import format_text
from tests.support import ROOT, Case
from tests.test_build import cli

NODES = """
nodes:
  api: {icon: function, title: API, sub: validates}
  queue: {icon: queue, title: Order queue}
  worker: {icon: server, title: Workers, sub: three replicas, stack: 3}
"""


def fmt(text: str) -> str:
    return format_text(textwrap.dedent(text))


def _edge_keys_spaced(x, edges=False):
    """The YAML data with every edge key written with one space around its arrows, as fmt writes them."""
    if isinstance(x, dict):
        return {
            (re.sub(r"\s*(<->|-->|->)\s*", r" \1 ", k).strip() if edges else k): _edge_keys_spaced(v, k == "edges")
            for k, v in x.items()
        }
    if isinstance(x, list):
        return [_edge_keys_spaced(v) for v in x]
    return x


class Rows(Case):
    def test_lines_up_values_and_items_with_the_same_key(self):
        self.assertEqual(
            fmt(NODES),
            textwrap.dedent("""
                nodes:
                  api:    {icon: function, title: API,     sub: validates}
                  queue:  {icon: queue,    title: Order queue}
                  worker: {icon: server,   title: Workers, sub: three replicas, stack: 3}
            """),
        )

    def test_stops_lining_up_where_the_keys_differ(self):
        out = fmt("""
            nodes:
              a: {icon: api, tone: blue, title: A}
              b: {icon: api, title: B, sub: x}
        """)
        self.assertIn("  a: {icon: api, tone: blue, title: A}\n", out)
        self.assertIn("  b: {icon: api, title: B, sub: x}\n", out)

    def test_a_blank_line_or_a_comment_ends_a_run(self):
        out = fmt("""
            nodes:
              a: {icon: api, title: A}

              longer: {icon: api, title: B}
              # a comment
              c: {icon: api, title: C}
        """)
        self.assertIn("  a: {icon: api, title: A}\n", out)
        self.assertIn("  c: {icon: api, title: C}\n", out)

    def test_keeps_a_trailing_comment(self):
        out = fmt("""
            nodes:
              a: {icon: api, title: A}  # first
              bb: {icon: api, title: B}
        """)
        self.assertIn("  a:  {icon: api, title: A}  # first\n", out)

    def test_leaves_quoted_commas_and_braces_alone(self):
        out = fmt("""
            nodes:
              a: {icon: api, title: "x, {y}"}
              bb: {icon: api, title: B}
        """)
        self.assertIn('  a:  {icon: api, title: "x, {y}"}\n', out)


class Edges(Case):
    def test_lines_up_arrows_and_labels(self):
        out = fmt("""
            edges:
              web -> api: POST /orders
              queue --> dlq: after 3 tries
              api->queue: enqueue
        """)
        self.assertEqual(
            out,
            textwrap.dedent("""
                edges:
                  web   -> api:   POST /orders
                  queue --> dlq:  after 3 tries
                  api   -> queue: enqueue
            """),
        )

    def test_a_long_key_does_not_push_the_others_labels(self):
        out = fmt("""
            edges:
              web -> api -> queue -> worker -> db: [a, b, c, d]
              queue --> dlq: after 3 tries
              worker -> mail: notify
        """)
        self.assertIn("  queue  --> dlq: after 3 tries\n", out)
        self.assertIn("  worker -> mail: notify\n", out)

    def test_an_edge_without_a_label_gets_no_trailing_space(self):
        out = fmt("""
            edges:
              a -> b:
              ccc -> d: x
        """)
        self.assertIn("  a   -> b:\n", out)

    def test_only_lines_under_edges(self):
        text = "views:\n  a -> b: x\n  c -> dd: y\n"
        self.assertEqual(format_text(text), text)


class Whole(Case):
    def test_examples_keep_their_data_lines_and_settle(self):
        for path in sorted((ROOT / "examples").glob("*/diagram.yml")):
            with self.subTest(example=path.parent.name):
                text = path.read_text(encoding="utf-8")
                out = format_text(text)
                self.assertEqual(format_text(out), out)
                self.assertEqual(len(out.split("\n")), len(text.split("\n")))
                self.assertEqual(_edge_keys_spaced(yaml.safe_load(out)), _edge_keys_spaced(yaml.safe_load(text)))

    def test_check_fails_only_when_a_file_would_change(self):
        base = self.tmp()
        path = base / "d.yml"
        path.write_text(textwrap.dedent(NODES), encoding="utf-8")
        self.assertEqual(cli("fmt", "--check", str(path))[0], 1)
        self.assertEqual(path.read_text(encoding="utf-8"), textwrap.dedent(NODES))
        self.assertEqual(cli("fmt", str(path))[0], 0)
        self.assertEqual(cli("fmt", "--check", str(path))[0], 0)


if __name__ == "__main__":
    unittest.main()
