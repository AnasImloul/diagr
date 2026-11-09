from __future__ import annotations

import unittest

from diagr.scenario import fold
from tests.test_build import BASE, prepared


class Compile(unittest.TestCase):
    def compiled(self, steps: str):
        p = prepared(BASE + "scenarios:\n  s:\n    ready: go\n    end: finished\n    steps:\n" + steps)
        return p.scenarios["s"]

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
            BASE.replace("title: A}", "title: A, cells: [x, y, z]}") + "scenarios:\n  s:\n    steps:\n"
            "    - {title: one, do: [cells a 1..1]}\n    - {title: two, do: [cells a 2..3]}\n"
        )
        s = fold(p.scenarios["s"].frames)
        self.assertEqual([s.get(f"c:a:{i}") for i in range(3)], ["ok", "ok", "ok"])

    def test_cells_by_position_and_name(self):
        yml = BASE.replace("title: A}", "title: A, cells: [x, y, z]}") + "scenarios:\n  s:\n    steps:\n"
        short = prepared(yml + "    - {title: one, do: [cells a x..y, cells a 3]}\n")
        long = prepared(yml + "    - {title: one, do: [cells a 1..2, cells a 3..3]}\n")
        frames = [[f.to_json() for f in p.scenarios["s"].frames] for p in (short, long)]
        self.assertEqual(frames[0], frames[1])

    def test_flow_is_the_long_form(self):
        three = BASE + "  b -> c: x\nnodes2:\n"
        yml = three.replace("nodes2:\n", "").replace("nodes:\n", "nodes:\n  c: {at: [2, 0], icon: cube, title: C}\n")
        short = prepared(yml + "scenarios:\n  s:\n    steps:\n    - {title: one, do: [flow a -> b -> c 300ms]}\n")
        long = prepared(
            yml + "scenarios:\n  s:\n    steps:\n    - title: one\n      do: [activate a 300ms, draw a->b, done a, "
            "activate b 300ms, draw b->c, done b]\n"
        )
        frames = [[f.to_json() for f in p.scenarios["s"].frames] for p in (short, long)]
        self.assertEqual(frames[0], frames[1])

    def test_parallel_flows_advance_in_lockstep(self):
        yml = (
            BASE.replace(
                "nodes:\n", "nodes:\n  c: {at: [0, 1], icon: cube, title: C}\n  d: {at: [1, 1], icon: cube, title: D}\n"
            )
            + "  c -> d: y\n"
        )
        short = prepared(
            yml + "scenarios:\n  s:\n    steps:\n    - {title: one, do: [parallel: [flow a -> b 200ms, flow c -> d]]}\n"
        )
        long = prepared(
            yml + "scenarios:\n  s:\n    steps:\n    - title: one\n      do:\n"
            "        - parallel: [activate a 200ms, activate c]\n"
            "        - parallel: [draw a->b, draw c->d]\n"
            "        - parallel: [done a, done c]\n"
        )
        frames = [[f.to_json() for f in p.scenarios["s"].frames] for p in (short, long)]
        self.assertEqual(frames[0], frames[1])

    def test_parallel_is_one_frame(self):
        c = self.compiled("    - title: one\n      do:\n        - parallel: [activate a, 'draw a->b 300ms']\n")
        self.assertEqual(len(c.frames), 3)
        self.assertEqual(c.frames[1].dur, 300)


if __name__ == "__main__":
    unittest.main()
