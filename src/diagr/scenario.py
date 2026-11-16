from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .model import Diagram, Effect, Scenario

DRAW_MS = 1400
CELL_MS = 1040


@dataclass
class Frame:
    set: dict[str, Any] = field(default_factory=dict)
    dur: float = 0
    step: int = 0
    edges: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> dict:
        out: dict[str, Any] = {"set": self.set, "dur": round(self.dur), "step": self.step}
        if self.edges:
            out["edges"] = {k: round(v) for k, v in self.edges.items()}
        return out


@dataclass
class StepInfo:
    title: str
    text: str
    at: str | None
    first: int
    last: int


@dataclass
class Compiled:
    frames: list[Frame]
    steps: list[StepInfo]
    ready: str
    end: str
    id: str = ""
    title: str = ""
    loop: bool = False


def fold(frames: list[Frame], start: dict[str, Any] | None = None) -> dict[str, Any]:
    s = dict(start or {})
    for f in frames:
        for key, v in f.set.items():
            if v is None:
                s.pop(key, None)
            else:
                s[key] = v
    return s


def walk_effects(sc: Scenario) -> Iterator[Effect]:
    def walk(effects: list[Effect]) -> Iterator[Effect]:
        for e in effects:
            yield e
            yield from walk(e.children)

    for step in sc.steps:
        yield from walk(step.effects)


def resolve_edge(d: Diagram, ref: str) -> str | None:
    if ref in d.edges:
        return ref
    if "->" in ref:
        a, b = ref.split("->", 1)
        hits = [k for k, e in d.edges.items() if e.src.node == a and e.dst.node == b]
        if len(hits) == 1:
            return hits[0]
    return None


def text_key(d: Diagram, path: str, slots: dict[str, int]) -> list[str] | None:
    """Keys a 'set' target writes: 'n.title', 'n.sub' (every line), 'n.sub.1', 'a->b.label'."""
    head, _, rest = path.partition(".")
    if head in d.nodes:
        parts = rest.split(".")
        if parts == ["title"]:
            return [f"t:{head}:title"]
        if parts[0] == "sub" and len(parts) == 1:
            return [f"t:{head}:sub:{j}" for j in range(max(1, slots.get(head, 1)))]
        if parts[0] == "sub" and len(parts) == 2 and parts[1].isdigit():
            return [f"t:{head}:sub:{parts[1]}"]
        return None
    edge_ref, _, fld = path.rpartition(".")
    eid = resolve_edge(d, edge_ref)
    if eid and fld == "label":
        return [f"t:{eid}:label"]
    return None


def _sub(text: str | None, i: int) -> str | None:
    return None if text is None else text.replace("{i}", str(i))


class _Compiler:
    def __init__(self, d: Diagram, slots: dict[str, int]):
        self.d, self.slots = d, slots
        self.state: dict[str, Any] = {}

    def _reveal(self, f: Frame, ids: list[str]) -> None:
        """Show the nodes and edges among ids that are hidden, and the ends of those edges: what a scenario draws or
        activates is meant to be seen."""
        d = self.d
        ends = [end for x in ids if x in d.edges for end in (d.edges[x].src.node, d.edges[x].dst.node)]
        for k in dict.fromkeys([*ids, *ends]):
            item = d.nodes.get(k) or d.edges.get(k)
            v = self.state.get(f"v:{k}")
            if v == "hidden" or (v is None and getattr(item, "hidden", False)):
                f.set[f"v:{k}"] = "shown"

    def _ids(self, targets: list[str]) -> list[str]:
        """Node and group ids as given, and each edge reference as the id of its edge."""
        d = self.d
        return [t if t in d.nodes or t in d.groups else resolve_edge(d, t) or t for t in targets]

    def frames(self, e: Effect, step: int, i: int = 0) -> list[Frame]:
        d, v = self.d, e.verb
        if v in ("activate", "done", "fail"):
            status = {"activate": "active", "done": "done", "fail": "failed"}[v]
            f = Frame({f"n:{t}": status for t in e.targets}, e.ms or 0, step)
            if v == "fail":
                for t in e.targets:
                    for k in range(len(d.nodes[t].cells) if t in d.nodes else 0):
                        if self.state.get(f"c:{t}:{k}") == "act":
                            f.set[f"c:{t}:{k}"] = "fail"
            self._reveal(f, e.targets)
            return [f]
        if v == "run":
            return [
                *self.frames(Effect("activate", e.targets, ms=e.ms), step),
                Frame({f"n:{t}": "done" for t in e.targets}, 0, step),
            ]
        if v == "draw":
            ms = e.ms or DRAW_MS
            ids = [resolve_edge(d, t) or t for t in e.targets]
            f = Frame({f"e:{k}": "drawn" for k in ids}, ms, step, {k: ms for k in ids})
            self._reveal(f, ids)
            return [f]
        if v == "set":
            keys = text_key(d, e.targets[0], self.slots) or []
            text = _sub(e.text, i) or ""
            return [Frame({k: (text if j == 0 else "") for j, k in enumerate(keys)}, e.ms or 0, step)]
        if v == "status":
            return [Frame({"status": _sub(e.text, i) or ""}, e.ms or 0, step)]
        if v == "cells":
            t = e.targets[0]
            names = d.nodes[t].cells
            lo, hi = e.range or (1, len(names))
            out = []
            for k in range(lo - 1, hi):
                f = Frame({f"c:{t}:{k}": "act"}, e.ms or CELL_MS, step)
                if k > lo - 1:
                    f.set[f"c:{t}:{k - 1}"] = "ok"
                else:
                    # A range continues an earlier one: the cell that range left active is now done.
                    for j in range(lo - 1):
                        if self.state.get(f"c:{t}:{j}") == "act":
                            f.set[f"c:{t}:{j}"] = "ok"
                if names[k]:
                    f.set[f"cap:{t}"] = names[k]
                out.append(f)
            if hi == len(names):
                out.append(Frame({f"c:{t}:{hi - 1}": "ok", f"cap:{t}": None}, 0, step))
            return out
        if v == "spin":
            off = e.targets[-1] == "off"
            return [Frame({f"s:{t}": None if off else 1 for t in e.targets if t != "off"}, e.ms or 0, step)]
        if v in ("show", "hide"):
            ids = self._ids(e.targets)
            return [Frame({f"v:{t}": "shown" if v == "show" else "hidden" for t in ids}, e.ms or 0, step)]
        if v == "focus":
            if e.targets == ["none"]:
                return [Frame({"focus": None}, e.ms or 0, step)]
            ids = self._ids(e.targets)
            ids += [k for k, ed in d.edges.items() if k not in ids and {ed.src.node, ed.dst.node} <= set(ids)]
            return [Frame({"focus": ids}, e.ms or 0, step)]
        if v == "flow":
            out = []
            for h, after in zip(e.hops, e.hops[1:], strict=False):
                # A box on the path is passed through: it has no active or done state of its own.
                nodes = [k for k in h.ids if k in d.nodes]
                subs = [Effect("draw", [f"{a}->{b}" for a in h.ids for b in after.ids], loc=e.loc)]
                if nodes:
                    subs = [*subs, Effect("done", nodes, loc=e.loc)]
                    # A stop that is already active, with no time to hold, just carries on.
                    if h.ms is not None or any(self.state.get(f"n:{k}") != "active" for k in nodes):
                        subs = [Effect("activate", nodes, ms=h.ms, loc=e.loc), *subs]
                for sub in subs:
                    out += self._run(sub, step, i)
            last = [k for k in e.hops[-1].ids if k in d.nodes]
            if last and e.hops[-1].ms is not None:
                out += self._run(Effect("activate", last, ms=e.hops[-1].ms, loc=e.loc), step, i)
            if last and e.finish:
                out += self._run(Effect("done", last, loc=e.loc), step, i)
            return out
        if v == "seq":
            out = []
            for c in e.children:
                out += self._run(c, step, i)
            return out
        if v == "wait":
            return [Frame({}, e.ms or 0, step)]
        if v == "parallel":
            # Lockstep: frame k plays every child's k-th frame together and lasts as long as the slowest of them,
            # so flows side by side advance one hop at a time. Each lane starts from the state before the block, not
            # from what the lanes before it did.
            start, lanes = self.state, []
            for c in e.children:
                self.state = dict(start)
                lanes.append(self.frames(c, step, i))
            self.state = start
            out = []
            for k in range(max((len(lane) for lane in lanes), default=0)):
                merged = Frame(step=step)
                for lane in lanes:
                    if k < len(lane):
                        merged.set.update(lane[k].set)
                        merged.edges.update(lane[k].edges)
                        merged.dur = max(merged.dur, lane[k].dur)
                out.append(merged)
            return out or [Frame(step=step)]
        if v == "repeat":
            out = []
            for n in range(1, e.count + 1):
                for c in e.children:
                    out += self._run(c, step, n)
            return out
        raise ValueError(f"unknown effect {v}")

    def _run(self, e: Effect, step: int, i: int) -> list[Frame]:
        out = []
        for f in self.frames(e, step, i):
            self.state = fold([f], self.state)
            out.append(f)
        return out


def compile_scenarios(d: Diagram, slots: dict[str, int]) -> dict[str, Compiled]:
    return {k: compile_scenario(d, sc, slots) for k, sc in d.scenarios.items()}


def compile_scenario(d: Diagram, sc: Scenario, slots: dict[str, int]) -> Compiled:
    c = _Compiler(d, slots)
    frames = [Frame()]
    steps: list[StepInfo] = []
    n = len(sc.steps)
    for idx, s in enumerate(sc.steps, 1):
        first = len(frames)
        produced: list[Frame] = []
        for e in s.effects:
            produced += c._run(e, idx, 0)
        if not produced:
            produced = [Frame(step=idx)]
        head = {"step": idx, "status": f"Step {idx} of {n}: {s.status or s.title}..."}
        if idx == 1:
            head["running"] = 1
        produced[0].set = {**head, **produced[0].set}
        frames += produced
        steps.append(StepInfo(s.title, s.text, s.at, first, len(frames) - 1))
    frames.append(Frame({"step": n + 1, "status": sc.end or "Done."}, 0, n))
    steps[-1].last = len(frames) - 1
    return Compiled(frames, steps, sc.ready, sc.end, sc.id, sc.title, sc.loop)
