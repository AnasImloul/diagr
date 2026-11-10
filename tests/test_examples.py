"""Golden-file tests: each example must build without warnings and match tests/golden byte for byte.

After an intended change to the output, refresh the golden files with
    DIAGR_UPDATE_GOLDEN=1 python -m unittest tests.test_examples
and review the diff.
"""

from __future__ import annotations

import json
import os
import unittest

from diagr import build_files, json_schema
from tests.support import ROOT, Case

GOLDEN = ROOT / "tests" / "golden"
EXAMPLES = sorted((ROOT / "examples").glob("*/diagram.yml"))
UPDATE = os.environ.get("DIAGR_UPDATE_GOLDEN") == "1"


class Examples(Case):
    def test_examples_exist(self):
        self.assertTrue(EXAMPLES)

    def test_examples_match_golden_files(self):
        for example in EXAMPLES:
            with self.subTest(example=example.parent.name):
                out = self.tmp()
                written, warnings = build_files(example, out)
                self.assertClean(warnings)
                for f in written:
                    golden = GOLDEN / f.name
                    if UPDATE:
                        golden.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
                        continue
                    self.assertTrue(golden.exists(), f"missing {golden.name}; run with DIAGR_UPDATE_GOLDEN=1")
                    self.assertEqual(
                        f.read_text(encoding="utf-8"),
                        golden.read_text(encoding="utf-8"),
                        f"{f.name} differs from tests/golden; if intended, run with DIAGR_UPDATE_GOLDEN=1",
                    )

    def test_expand_round_trips(self):
        """`diagr expand` output builds to exactly the same files as the original. Expanding pins every position, so
        a view of automatically placed nodes becomes a crop: for those diagrams only the main files must match."""
        import shutil

        import yaml

        from diagr import load_file
        from diagr.unparse import to_yaml

        for example in EXAMPLES:
            with self.subTest(example=example.parent.name):
                folder = self.tmp()
                if (example.parent / "icons").is_dir():
                    shutil.copytree(example.parent / "icons", folder / "icons")
                expanded = folder / "diagram.yml"
                source = yaml.safe_load(example.read_text(encoding="utf-8"))
                d = load_file(example)
                main = {f"{d.id}-light.svg", f"{d.id}-dark.svg", f"{d.id}.html"}
                expanded.write_text(to_yaml(d, source), encoding="utf-8")
                placed = any(n.auto for n in d.nodes.values())
                for original, again in zip(
                    build_files(example, self.tmp())[0], build_files(expanded, self.tmp())[0], strict=True
                ):
                    if placed and original.name not in main:
                        continue
                    self.assertEqual(original.read_text(encoding="utf-8"), again.read_text(encoding="utf-8"))


class Schema(unittest.TestCase):
    def test_committed_schema_is_up_to_date(self):
        committed = json.loads((ROOT / "schema" / "diagr.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(committed, json_schema(), "run: diagr schema -o schema/diagr.schema.json")


if __name__ == "__main__":
    unittest.main()
