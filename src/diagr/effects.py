from __future__ import annotations

import copy
import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .model import Effect, Hop
from .source import Problem, Y, YMap, YScalar, YSeq, did_you_mean

DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|s)")
REPEAT = re.compile(r"repeat(?:\s+(\S+))?")

VERBS = {
    "activate": "Node starts working: pulsing ring, spinner badge",
    "done": "Node finished: check badge",
    "fail": "Node failed: red ring and cross; an active cell fails too",
    "run": "Node works for a while, then finishes: 'run api 800ms' is activate api 800ms, then done api",
    "draw": "Edge is used: the accent line draws along the path, showing the edge if it is hidden",
    "flow": "Follow a path: 'flow a -> b' is activate a, draw a->b, done a. A duration after a stop is how long it "
    "stays active ('flow a 600ms -> b'), '(b c)' is several stops side by side, and 'done' at the end finishes the "
    "last stop, which is otherwise left as it is",
    "cells": "Fill a node's cells one by one, or only some: 'cells n 2..4', 'cells n 3', 'cells n build..test'",
    "spin": "Rotate the node's glyph; 'spin n off' stops it",
    "show": "Reveal a hidden node, edge or group",
    "hide": "Hide a node, edge or group",
    "focus": "Dim everything except the targets and the edges between them; 'focus none' clears",
    "wait": "Pause",
}
NODE_VERBS = ("activate", "done", "fail", "run", "cells", "spin")

_TEXT_KEY = r"^(?!(?:" + "|".join(VERBS) + r"|parallel|repeat)\b)\S+(?:\s+\d+(?:\.\d+)?(?:ms|s))?$"

EFFECT_SCHEMA = {
    "type": "array",
    "items": {
        "oneOf": [
            {
                "type": "string",
                "description": "'verb targets [duration]', e.g. 'draw a->b 700ms', or an action's name and its "
                "instances. Verbs: " + "; ".join(f"{k}: {v}" for k, v in VERBS.items()),
            },
            {
                "type": "object",
                "minProperties": 1,
                "propertyNames": {"pattern": _TEXT_KEY},
                "additionalProperties": {"type": "string"},
                "description": "Text that changes: 'node.sub: text', 'node.title', 'node.sub.N', 'a->b.label' or "
                "'status', each with an optional duration ('api.sub 400ms: text'). Several in one mapping change "
                "together",
            },
            {
                "type": "object",
                "required": ["parallel"],
                "additionalProperties": False,
                "properties": {"parallel": {"$ref": "#/$defs/effects"}},
                "description": "Effects that play together, in lockstep",
            },
            {
                "type": "object",
                "minProperties": 1,
                "maxProperties": 1,
                "propertyNames": {"pattern": r"^repeat\s+\d+$"},
                "additionalProperties": {"$ref": "#/$defs/effects"},
                "description": "'repeat 3: [...]' plays the effects 3 times; '{i}' in text is the round number",
            },
            {"$ref": "#/$defs/effects", "description": "Effects that play one after another, as one lane"},
        ]
    },
}


def _same(s: str) -> str:
    return s


def _ms(token: str) -> float | None:
    m = DURATION.fullmatch(token)
    if not m:
        return None
    return float(m.group(1)) * (1000 if m.group(2) == "s" else 1)


@dataclass
class Ctx:
    """What effects are parsed against: where problems go, the actions they can call, and, inside a component's
    action, how its local ids and {param} text turn into an instance's."""

    problems: list[Problem]
    actions: Actions | None = None
    rename: Callable[[str], str] = _same
    fill: Callable[[str], str] = _same
    own: str | None = None

    def ref(self, ref: str) -> str:
        """A node, group or edge reference ('a', 'a->b', a named edge) as the instance names it."""
        if "->" in ref:
            a, _, b = ref.partition("->")
            return f"{self.rename(a)}->{self.rename(b)}"
        return self.rename(ref)

    def fail(self, y: Y, message: str) -> None:
        self.problems.append(Problem(y.loc, message))


def _text(key: str, text: str, y: Y, ctx: Ctx) -> Effect | None:
    """'status: text' or 'target.field: text', each with an optional duration before the colon."""
    parts = key.split()
    if not parts:
        ctx.fail(y, "empty effect")
        return None
    target, rest = parts[0], parts[1:]
    ms = _ms(rest[0]) if len(rest) == 1 else None
    if target == "set" and len(rest) == 1:
        ctx.fail(y, f"write '{rest[0]}: text', without 'set'")
        return None
    if target in VERBS:
        ctx.fail(
            y,
            f"only 'status' and text like 'node.sub' take text after a colon, not '{target}'"
            " (did you forget quotes around the effect?)",
        )
        return None
    if rest and ms is None:
        ctx.fail(y, f"'{key}': expected 'target [duration]: text', like 'api.sub 400ms: text'")
        return None
    if target == "status":
        return Effect("status", text=ctx.fill(text), ms=ms, loc=y.loc)
    if "." in target:
        head, _, fld = target.partition(".")
        return Effect("set", [f"{ctx.ref(head)}.{fld}"], text=ctx.fill(text), ms=ms, loc=y.loc)
    ctx.fail(y, f"'{target}' takes no text; use node.title, node.sub, node.sub.N, a->b.label or status")
    return None


def _flow(path: str, y: Y, ctx: Ctx) -> Effect | None:
    segments = [s.strip() for s in path.split("->")]
    finish = False
    if segments and segments[-1].endswith(" done") and segments[-1][:-5].strip():
        segments[-1], finish = segments[-1][:-5].strip(), True
    if len(segments) < 2 or not all(segments):
        ctx.fail(y, "'flow' takes a path of nodes, e.g. 'flow a -> b -> c'")
        return None
    hops = []
    for seg in segments:
        ms = None
        m = re.fullmatch(r"(.*?)\s+(\S+)", seg)
        if m and _ms(m.group(2)) is not None:
            seg, ms = m.group(1).strip(), _ms(m.group(2))
        if seg.startswith("(") and seg.endswith(")"):
            ids = seg[1:-1].split()
        else:
            ids = seg.split()
            if len(ids) != 1:
                ctx.fail(y, f"'flow': write stops side by side in parentheses, like '({seg})'")
                return None
        if not ids:
            ctx.fail(y, "'flow': empty parentheses")
            return None
        hops.append(Hop([ctx.ref(i) for i in ids], ms))
    targets = list(dict.fromkeys(i for h in hops for i in h.ids))
    return Effect("flow", targets, hops=hops, finish=finish, loc=y.loc)


def _verb(head: str, y: Y, ctx: Ctx) -> Effect | None:
    word = head.split(maxsplit=1)[0] if head.split() else ""
    if not word:
        ctx.fail(y, "empty effect")
        return None
    if word not in VERBS and ctx.actions and ctx.actions.has(word):
        return ctx.actions.call(word, head.split()[1:], y, ctx)
    if word not in VERBS and ":" in head:
        # Text written as one string, quoted because the text itself has ': ' in it.
        key, _, text = head.partition(":")
        return _text(key, text.strip(), y, ctx)
    if word not in VERBS:
        names = [*VERBS, *(ctx.actions.names() if ctx.actions else [])]
        close = difflib.get_close_matches(word, names, n=1)
        hint = f", did you mean '{close[0]}'?" if close else ""
        ctx.fail(y, f"unknown effect '{word}'{hint}")
        return None
    if word == "flow":
        return _flow(head[len(word) :], y, ctx)
    verb, *args = re.sub(r"\s*->\s*", "->", head.strip()).split()
    e = Effect(verb, loc=y.loc)
    if args and _ms(args[-1]) is not None:
        e.ms = _ms(args.pop())
    if verb == "cells" and len(args) == 2:
        # 'cells n 2..4', 'cells n 3', 'cells n build..test', 'cells n canary'; parse.py resolves the names.
        spec = args.pop()
        lo, _, hi = spec.partition("..")
        hi = hi or lo
        if lo.isdigit() and hi.isdigit():
            e.range = (int(lo), int(hi))
        else:
            e.range_names = (lo, hi)
    if verb == "wait":
        if e.ms is None or args:
            ctx.fail(y, "'wait' takes only a duration, e.g. 'wait 400ms'")
            return None
    elif not args:
        ctx.fail(y, f"'{verb}' needs at least one target")
        return None
    keep = {"spin": "off", "focus": "none"}.get(verb)
    e.targets = [a if a == keep else ctx.ref(a) for a in args]
    return e


def _texts(item: YMap, ctx: Ctx) -> Effect | None:
    """A mapping of text changes, which play together."""
    out = []
    for k, v in item.pairs:
        if not isinstance(v, YScalar) or v.null:
            ctx.fail(v, f"'{k.value}' expects text after the colon")
            continue
        e = _text(k.value, v.value, k, ctx)
        if e:
            out.append(e)
    if len(out) != len(item.pairs):
        return None
    return out[0] if len(out) == 1 else Effect("parallel", children=out, loc=item.loc)


def parse_effects(y: Y, ctx: Ctx) -> list[Effect]:
    if not isinstance(y, YSeq):
        ctx.fail(y, "'do' must be a list of effects")
        return []
    out: list[Effect] = []
    for item in y.items:
        e = None
        if isinstance(item, YScalar) and not item.null:
            e = _verb(item.value.strip(), item, ctx)
        elif isinstance(item, YSeq):
            e = Effect("seq", children=parse_effects(item, ctx), loc=item.loc)
        elif isinstance(item, YMap) and item.pairs:
            k, v = item.pairs[0]
            repeat = REPEAT.fullmatch(k.value)
            if k.value == "parallel" and len(item.pairs) == 1:
                e = Effect("parallel", children=parse_effects(v, ctx), loc=item.loc)
            elif repeat and len(item.pairs) == 1:
                count = repeat.group(1) or ""
                if not count.isdigit() or int(count) < 1:
                    ctx.fail(k, "'repeat' needs a whole number, like 'repeat 3: [...]'")
                    continue
                e = Effect("repeat", children=parse_effects(v, ctx), count=int(count), loc=item.loc)
            elif any(key in ("parallel", "do") or REPEAT.fullmatch(key) for key in item.keys()):
                ctx.fail(item, "write 'parallel: [...]' or 'repeat 3: [...]' on its own")
                continue
            else:
                e = _texts(item, ctx)
        else:
            ctx.fail(
                item,
                "an effect is text like 'activate node', 'node.sub: text', a list, "
                "'parallel: [...]' or 'repeat 3: [...]'",
            )
        if e:
            out.append(e)
    return out


@dataclass
class Actions:
    """Named lists of effects. A top-level action is called by its name; a component's action by its name and the
    instances it runs on, side by side: 'pull orders clicks'. Inside a component's action, the others of the same
    component are called by name alone and run on the same instance."""

    problems: list[Problem]
    top: dict[str, Y] = field(default_factory=dict)
    components: dict[str, dict[str, Y]] = field(default_factory=dict)
    instances: dict[str, tuple[str, Callable[[str], str]]] = field(default_factory=dict)
    parsed: dict[tuple[str | None, str], Effect | None] = field(default_factory=dict)
    busy: set[tuple[str | None, str]] = field(default_factory=set)

    def add(self, component: str | None, name: str, body: Y) -> None:
        if name in VERBS or name in ("parallel", "repeat", "status"):
            self.problems.append(Problem(body.loc, f"action '{name}' has the name of an effect; pick another"))
            return
        if component is None:
            self.top[name] = body
        else:
            self.components.setdefault(component, {})[name] = body

    def check_names(self) -> None:
        for c, acts in self.components.items():
            for name, body in acts.items():
                if name in self.top:
                    self.problems.append(
                        Problem(body.loc, f"action '{name}' is defined at the top level and in component '{c}'")
                    )

    def names(self) -> list[str]:
        return [*self.top, *(n for acts in self.components.values() for n in acts)]

    def has(self, name: str) -> bool:
        return name in self.top or any(name in acts for acts in self.components.values())

    def call(self, name: str, targets: list[str], y: Y, ctx: Ctx) -> Effect | None:
        own = self.instances.get(ctx.own or "", (None,))[0]
        if not targets:
            if own and name in self.components.get(own, {}):
                return self._get(ctx.own, name, y)
            if name in self.top:
                return self._get(None, name, y)
            owners = ", ".join(c for c, acts in self.components.items() if name in acts)
            ctx.fail(y, f"'{name}' is an action of component {owners}: name the instances it runs on")
            return None
        if name in self.top:
            ctx.fail(y, f"action '{name}' takes no instances")
            return None
        lanes = []
        for t in targets:
            if t not in self.instances:
                ctx.fail(y, f"'{name}': unknown instance '{t}'{did_you_mean(t, self.instances)}")
                return None
            comp = self.instances[t][0]
            if name not in self.components.get(comp, {}):
                ctx.fail(y, f"'{name}': component '{comp}' of instance '{t}' has no action '{name}'")
                return None
            lane = self._get(t, name, y)
            if lane is None:
                return None
            lanes.append(lane)
        return lanes[0] if len(lanes) == 1 else Effect("parallel", children=lanes, loc=y.loc)

    def _get(self, inst: str | None, name: str, y: Y) -> Effect | None:
        key = (inst, name)
        if key in self.busy:
            self.problems.append(Problem(y.loc, f"action '{name}' calls itself"))
            return None
        if key not in self.parsed:
            self.busy.add(key)
            if inst is None:
                ctx = Ctx(self.problems, self)
                body = self.top[name]
            else:
                comp, fill = self.instances[inst]
                ctx = Ctx(self.problems, self, lambda s: f"{inst}/{s}", fill, inst)
                body = self.components[comp][name]
            self.parsed[key] = Effect("seq", children=parse_effects(body, ctx), loc=body.loc)
            self.busy.discard(key)
        e = self.parsed[key]
        return copy.deepcopy(e) if e else None

    def check_all(self) -> dict[str, dict[str, Effect]]:
        """Parse every action, called or not, so its problems are reported. Returns each instance's actions."""
        for name, body in self.top.items():
            self._get(None, name, body)
        out: dict[str, dict[str, Effect]] = {}
        for inst, (comp, _) in self.instances.items():
            for name, body in self.components.get(comp, {}).items():
                e = self._get(inst, name, body)
                if e:
                    out.setdefault(inst, {})[name] = e
        return out


def _dur(ms: float | None) -> str:
    if ms is None:
        return ""
    return f" {int(ms) if float(ms).is_integer() else ms}ms"


def effect_data(e: Effect) -> Any:
    """An effect as the YAML data that parses back to it."""
    v = e.verb
    if v == "flow":
        stops = [(f"({' '.join(h.ids)})" if len(h.ids) > 1 else h.ids[0]) + _dur(h.ms) for h in e.hops]
        return "flow " + " -> ".join(stops) + (" done" if e.finish else "")
    if v == "set":
        return {e.targets[0] + _dur(e.ms): e.text or ""}
    if v == "status":
        return {"status" + _dur(e.ms): e.text or ""}
    if v == "parallel":
        return {"parallel": [effect_data(c) for c in e.children]}
    if v == "repeat":
        return {f"repeat {e.count}": [effect_data(c) for c in e.children]}
    if v == "seq":
        return effect_data(e.children[0]) if len(e.children) == 1 else [effect_data(c) for c in e.children]
    if v == "wait":
        return "wait" + _dur(e.ms)
    args = list(e.targets)
    if v == "cells" and e.range:
        args.append(f"{e.range[0]}..{e.range[1]}")
    elif v == "cells" and e.range_names:
        args.append(f"{e.range_names[0]}..{e.range_names[1]}")
    return f"{v} {' '.join(args)}{_dur(e.ms)}"
