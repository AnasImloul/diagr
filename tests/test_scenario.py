from __future__ import annotations

import json
import shutil
import subprocess
import unittest

from diagr import load_file, prepare
from diagr.scenario import Frame, fold
from tests.support import ROOT
from tests.test_build import BASE, prepared

FOLD_JS = ROOT / "src/diagr/render/assets/fold.js"


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
        c = self.compiled("    - title: one\n      do:\n        - repeat 3: ['status: round {i}']\n")
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
        short = prepared(yml + "scenarios:\n  s:\n    steps:\n    - {title: one, do: [flow a 300ms -> b 300ms -> c]}\n")
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
            yml + "scenarios:\n  s:\n    steps:\n    - {title: one, do: [parallel: [flow a 200ms -> b, flow c -> d]]}\n"
        )
        long = prepared(
            yml + "scenarios:\n  s:\n    steps:\n    - title: one\n      do:\n"
            "        - parallel: [activate a 200ms, activate c]\n"
            "        - parallel: [draw a->b, draw c->d]\n"
            "        - parallel: [done a, done c]\n"
        )
        frames = [[f.to_json() for f in p.scenarios["s"].frames] for p in (short, long)]
        self.assertEqual(frames[0], frames[1])

    def test_cells_and_repeat_inside_parallel(self):
        yml = BASE.replace("title: A}", "title: A, cells: [x, y]}") + (
            "scenarios:\n  s:\n    steps:\n    - title: one\n      do:\n"
            "        - parallel: [cells a, flow a -> b, {repeat 2: ['status: round {i}']}]\n"
        )
        frames = prepared(yml).scenarios["s"].frames
        self.assertEqual(frames[1].set["c:a:0"], "act")
        self.assertEqual(frames[1].set["n:a"], "active")
        self.assertEqual(frames[1].set["status"], "round 1")
        self.assertEqual(frames[2].set["c:a:1"], "act")
        self.assertEqual(frames[2].set["e:a->b"], "drawn")
        self.assertEqual(frames[2].set["status"], "round 2")
        self.assertEqual(frames[2].dur, 1400)
        self.assertEqual(frames[3].set, {"c:a:1": "ok", "cap:a": None, "n:a": "done"})

    def test_a_lane_in_a_list_starts_where_the_others_do(self):
        yml = BASE + "scenarios:\n  s:\n    steps:\n    - title: one\n      do:\n"
        listed = prepared(yml + "        - parallel: [[activate a 500ms], flow a -> b]\n")
        plain = prepared(yml + "        - parallel: [activate a 500ms, flow a -> b]\n")
        frames = [[f.to_json() for f in p.scenarios["s"].frames] for p in (listed, plain)]
        self.assertEqual(frames[0], frames[1])

    def test_nested_parallel_is_one_lane(self):
        yml = BASE + "scenarios:\n  s:\n    steps:\n    - title: one\n      do:\n"
        nested = prepared(yml + "        - parallel: [{parallel: [flow a -> b, 'status: go']}, done b]\n")
        flat = prepared(yml + "        - parallel: [flow a -> b, 'status: go', done b]\n")
        frames = [[f.to_json() for f in p.scenarios["s"].frames] for p in (nested, flat)]
        self.assertEqual(frames[0], frames[1])

    def test_parallel_is_one_frame(self):
        c = self.compiled("    - title: one\n      do:\n        - parallel: [activate a, 'draw a->b 300ms']\n")
        self.assertEqual(len(c.frames), 3)
        self.assertEqual(c.frames[1].dur, 300)


@unittest.skipUnless(shutil.which("node"), "needs node")
class PlayerStates(unittest.TestCase):
    def test_the_player_folds_frames_as_python_does(self):
        """The page computes each frame's state with fold.js; it must be the state Python folds for that frame."""
        scenarios = {}
        for example in sorted((ROOT / "examples").glob("*/diagram.yml")):
            for k, c in prepare(load_file(example)).scenarios.items():
                scenarios[f"{example.parent.name}/{k}"] = [f.to_json() for f in c.frames]
        script = (
            f"const states = require({json.dumps(str(FOLD_JS))});"
            "const all = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
            "process.stdout.write(JSON.stringify(Object.fromEntries("
            "Object.entries(all).map(([k, frames]) => [k, states(frames)]))));"
        )
        run = subprocess.run(["node", "-e", script], input=json.dumps(scenarios), capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        js = json.loads(run.stdout)
        for k, frames in scenarios.items():
            with self.subTest(scenario=k):
                frames_py = [Frame(set=f["set"]) for f in frames]
                py = [json.loads(json.dumps(fold(frames_py[1 : i + 1]))) for i in range(len(frames))]
                self.assertEqual(js[k], py)


if __name__ == "__main__":
    unittest.main()
