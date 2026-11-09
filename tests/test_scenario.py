from __future__ import annotations

import unittest

from diagr.scenario import fold
from tests.test_build import BASE, prepared


class Compile(unittest.TestCase):
    def compiled(self, steps: str):
        p = prepared(BASE + "scenario:\n  ready: go\n  end: finished\n  steps:\n" + steps)
        assert p.compiled
        return p.compiled

    def test_state_after_the_last_frame(self):
        c = self.compiled("    - {title: one, do: [activate a, draw a->b, done a]}\n")
        s = fold(c.frames)
        self.assertEqual(s["n:a"], "done")
        self.assertEqual(s["e:a->b"], "drawn")
        self.assertEqual(s["status"], "finished")

    def test_steps_point_at_their_frames(self):
        c = self.compiled("    - {title: one, do: [done a]}\n    - {title: two, do: [done b]}\n")
        self.assertEqual([(s.first, s.last) for s in c.steps], [(1, 1), (2, 3)])

    def test_repeat_unrolls_and_numbers_rounds(self):
        c = self.compiled("    - title: one\n      do:\n        - repeat: 3\n          do: ['status: round {i}']\n")
        self.assertEqual([f.set.get("status") for f in c.frames[2:4]], ["round 2", "round 3"])

    def test_parallel_is_one_frame(self):
        c = self.compiled("    - title: one\n      do:\n        - parallel: [activate a, 'draw a->b 300ms']\n")
        self.assertEqual(len(c.frames), 3)
        self.assertEqual(c.frames[1].dur, 300)


if __name__ == "__main__":
    unittest.main()
