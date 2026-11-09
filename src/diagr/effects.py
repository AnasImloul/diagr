from __future__ import annotations

import difflib
import re

from .model import Effect
from .source import Problem, Y, YMap, YScalar, YSeq

DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|s)")
RANGE = re.compile(r"(\d+)\.\.(\d+)")

TEXT_VERBS = {"set", "status"}
VERBS = {
    "activate": "Node starts working: pulsing ring, spinner badge",
    "done": "Node finished: check badge",
    "fail": "Node failed: red ring and cross; an active cell fails too",
    "draw": "Edge is used: the accent line draws along the path",
    "set": "Replace text: 'set node.title', 'set node.sub', 'set node.sub.1', 'set a->b.label'",
    "cells": "Fill a node's cells one by one, optionally a range 'cells n 1..4'",
    "spin": "Rotate the node's glyph; 'spin n off' stops it",
    "show": "Reveal a hidden node, edge or group",
    "hide": "Hide a node, edge or group",
    "focus": "Dim everything except the targets; 'focus none' clears",
    "wait": "Pause",
    "status": "Replace the status line",
}

EFFECT_SCHEMA = {
    "type": "array",
    "items": {
        "oneOf": [
            {"type": "string", "pattern": "^(" + "|".join(VERBS) + r")\b",
             "description": "verb targets [duration], e.g. 'draw a->b 700ms'. Verbs: "
                            + "; ".join(f"{k}: {v}" for k, v in VERBS.items())},
            {"type": "object", "minProperties": 1, "maxProperties": 1,
             "propertyNames": {"pattern": r"^(set|status)\b"},
             "additionalProperties": {"type": "string"},
             "description": "'verb target [duration]': text, for effects that carry free text"},
            {"type": "object", "required": ["parallel"], "additionalProperties": False,
             "properties": {"parallel": {"$ref": "#/$defs/effects"}},
             "description": "Effects that play together"},
            {"type": "object", "required": ["repeat", "do"], "additionalProperties": False,
             "properties": {"repeat": {"type": "integer", "minimum": 1}, "do": {"$ref": "#/$defs/effects"}},
             "description": "Repeat effects; '{i}' in text is replaced by the round number"},
        ]
    },
}


def _ms(token: str) -> float | None:
    m = DURATION.fullmatch(token)
    if not m:
        return None
    return float(m.group(1)) * (1000 if m.group(2) == "s" else 1)


def _parse_head(head: str, y: Y, problems: list[Problem], text: str | None) -> Effect | None:
    if text is None and re.split(r"[\s:]", head.strip(), maxsplit=1)[0] in TEXT_VERBS and ":" in head:
        head, _, text = head.partition(":")
        text = text.strip()
    tokens = re.sub(r"\s*->\s*", "->", head.strip()).split()
    if not tokens:
        problems.append(Problem(y.loc, "empty effect"))
        return None
    verb, args = tokens[0], tokens[1:]
    if verb not in VERBS:
        close = difflib.get_close_matches(verb, VERBS, n=1)
        hint = f", did you mean '{close[0]}'?" if close else ""
        problems.append(Problem(y.loc, f"unknown effect '{verb}'{hint}"))
        return None
    e = Effect(verb, loc=y.loc)
    if verb in TEXT_VERBS and text is None:
        # String form: 'set n.sub some text' / 'status some text'.
        n = 1 if verb == "set" else 0
        if len(args) < n:
            problems.append(Problem(y.loc, f"'{verb}' needs a target"))
            return None
        e.targets = args[:n]
        rest = args[n:]
        if rest and _ms(rest[0]) is not None:
            e.ms = _ms(rest.pop(0))
        e.text = " ".join(rest).strip('"')
        return e
    if args and _ms(args[-1]) is not None:
        e.ms = _ms(args.pop())
    rng = RANGE.fullmatch(args[-1]) if verb == "cells" and args else None
    if rng:
        args.pop()
        e.range = (int(rng.group(1)), int(rng.group(2)))
    e.targets = args
    e.text = text
    if verb == "wait":
        if e.ms is None or args:
            problems.append(Problem(y.loc, "'wait' takes only a duration, e.g. 'wait 400ms'"))
            return None
    elif verb in TEXT_VERBS:
        if verb == "set" and len(args) != 1:
            problems.append(Problem(y.loc, "'set' takes one target like 'node.sub'"))
            return None
    elif not args:
        problems.append(Problem(y.loc, f"'{verb}' needs at least one target"))
        return None
    return e


def parse_effects(y: Y, problems: list[Problem], depth: int = 0) -> list[Effect]:
    if not isinstance(y, YSeq):
        problems.append(Problem(y.loc, "'do' must be a list of effects"))
        return []
    out: list[Effect] = []
    for item in y.items:
        if isinstance(item, YScalar) and not item.null:
            e = _parse_head(item.value, item, problems, None)
            if e:
                out.append(e)
        elif isinstance(item, YMap):
            keys = item.keys()
            if keys == ["parallel"]:
                children = parse_effects(item.pairs[0][1], problems, depth + 1)
                out.append(Effect("parallel", children=children, loc=item.loc))
            elif sorted(keys) == ["do", "repeat"]:
                vals = dict((k.value, v) for k, v in item.pairs)
                count = vals["repeat"]
                if not (isinstance(count, YScalar) and count.value.isdigit() and int(count.value) >= 1):
                    problems.append(Problem(count.loc, "'repeat' needs a whole number"))
                    continue
                children = parse_effects(vals["do"], problems, depth + 1)
                out.append(Effect("repeat", children=children, count=int(count.value), loc=item.loc))
            elif len(keys) == 1:
                k, v = item.pairs[0]
                if not isinstance(v, YScalar) or v.null:
                    problems.append(Problem(v.loc, f"'{k.value}' expects text after the colon"))
                    continue
                verb = k.value.split()[0] if k.value.split() else ""
                if verb not in TEXT_VERBS:
                    problems.append(Problem(k.loc, f"only 'set' and 'status' take text after a colon, not '{verb}'"
                                                   " (did you forget quotes around the effect?)"))
                    continue
                e = _parse_head(k.value, k, problems, v.value)
                if e:
                    out.append(e)
            else:
                problems.append(Problem(item.loc, "an effect is text, 'verb target: text', {parallel: [...]} "
                                                  "or {repeat: n, do: [...]}"))
        else:
            problems.append(Problem(item.loc, "an effect is text like 'activate node'"))
    return out
