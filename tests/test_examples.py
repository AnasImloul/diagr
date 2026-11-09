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


class Schema(unittest.TestCase):
    def test_committed_schema_is_up_to_date(self):
        committed = json.loads((ROOT / "schema" / "diagr.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(committed, json_schema(), "run: diagr schema -o schema/diagr.schema.json")


if __name__ == "__main__":
    unittest.main()
