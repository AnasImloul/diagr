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

    def test_cell_ranges_continue(self):
        p = prepared(
            BASE.replace("title: A}", "title: A, cells: [x, y, z]}") + "scenario:\n  steps:\n"
            "    - {title: one, do: [cells a 1..1]}\n    - {title: two, do: [cells a 2..3]}\n"
        )
        assert p.compiled
        s = fold(p.compiled.frames)
        self.assertEqual([s.get(f"c:a:{i}") for i in range(3)], ["ok", "ok", "ok"])

    def test_flow_is_the_long_form(self):
        three = BASE + "  b -> c: x\nnodes2:\n"
        yml = three.replace("nodes2:\n", "").replace("nodes:\n", "nodes:\n  c: {at: [2, 0], icon: cube, title: C}\n")
        short = prepared(yml + "scenario:\n  steps:\n    - {title: one, do: [flow a -> b -> c 300ms]}\n")
        long = prepared(
            yml + "scenario:\n  steps:\n    - title: one\n      do: [activate a 300ms, draw a->b, done a, "
            "activate b 300ms, draw b->c, done b]\n"
        )
        assert short.compiled and long.compiled
        self.assertEqual([f.to_json() for f in short.compiled.frames], [f.to_json() for f in long.compiled.frames])

    def test_parallel_is_one_frame(self):
        c = self.compiled("    - title: one\n      do:\n        - parallel: [activate a, 'draw a->b 300ms']\n")
        self.assertEqual(len(c.frames), 3)
        self.assertEqual(c.frames[1].dur, 300)


if __name__ == "__main__":
    unittest.main()
