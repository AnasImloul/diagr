from __future__ import annotations

import unittest

from diagr.markdown import fence, validate

STATIC = """
id: t
nodes:
  a: {icon: api, title: A}
  b: {icon: database, title: B}
edges:
  a -> b: {}
"""

PLAYER = (
    STATIC
    + """
scenarios:
  s:
    steps:
      - title: Go
        do: [flow a -> b]
"""
)


class Fence(unittest.TestCase):
    def test_static_without_scenarios(self):
        out = fence(STATIC, "diagr", "diagr", {}, None)
        self.assertIn("#only-light", out)
        self.assertIn("#only-dark", out)
        self.assertNotIn("<iframe", out)

    def test_player_with_scenarios(self):
        out = fence(PLAYER, "diagr", "diagr", {}, None)
        self.assertTrue(out.startswith('<iframe class="diagr diagr-embed"'))
        self.assertIn("srcdoc=", out)

    def test_mode_option(self):
        options: dict = {}
        self.assertTrue(validate("diagr", {"mode": "static"}, options, {}, None))
        self.assertNotIn("<iframe", fence(PLAYER, "diagr", "diagr", options, None))
        self.assertFalse(validate("diagr", {"mode": "movie"}, {}, {}, None))

    def test_errors_show_in_place(self):
        with self.assertLogs("mkdocs.plugins.diagr", "WARNING"):
            out = fence(STATIC.replace("a -> b", "a -> c"), "diagr", "diagr", {}, None)
        self.assertIn("diagr-error", out)
        self.assertIn("&#x27;c&#x27;", out)


if __name__ == "__main__":
    unittest.main()
