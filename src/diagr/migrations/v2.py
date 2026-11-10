"""Version 2, from version 1:

- A group or node goes inside the group that holds it; `in:` on a group or node is gone (an instance keeps it).
- A trigger button is written on the scenario it plays, `trigger: {at: node, label: ...}`, not on the node as
  `trigger` and `plays`.
- `{repeat: 3, do: [...]}` is written `repeat 3: [...]`.
- Text changes are written `node.sub 300ms: text` and `status: text`: the verb `set` is gone, and so are
  `set node.sub text` and `status text` without a colon.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..source import Problem, Y, YMap, YScalar, YSeq, did_you_mean

DURATION = re.compile(r"\d+(?:\.\d+)?(?:ms|s)")


def up(tree: YMap, problems: list[Problem]) -> None:
    components = [c for _, c in _pairs(_get(tree, "components")) if isinstance(c, YMap)]
    for box in [tree, *components]:
        _nest(box, problems)
    _triggers(tree, components, problems)
    # An action may be called 'set' in version 2; then 'set ...' is a call, not a version 1 text change.
    actions = [_get(tree, "actions"), *(_get(c, "actions") for c in components)]
    set_is_text = not any(_get(a, "set") is not None for a in actions)
    for _, sc in _pairs(_get(tree, "scenarios")):
        steps = _get(sc, "steps")
        for step in steps.items if isinstance(steps, YSeq) else []:
            _effects(_get(step, "do"), set_is_text, problems)


def _get(m: Y | None, key: str) -> Y | None:
    for k, v in _pairs(m):
        if k.value == key:
            return v
    return None


def _pairs(m: Y | None) -> list[tuple[YScalar, Y]]:
    return list(m.pairs) if isinstance(m, YMap) else []


def _pop(m: YMap, key: str) -> Y | None:
    v = _get(m, key)
    m.pairs = [(k, x) for k, x in m.pairs if k.value != key]
    return v


def _key(y: Y, text: str) -> YScalar:
    return YScalar(y.loc, text, False, False)


def _text(y: Y, text: str) -> YScalar:
    return YScalar(y.loc, text, True, False)


def _warn(problems: list[Problem], y: Y, message: str) -> None:
    problems.append(Problem(y.loc, f"version 2 {message}", "warning"))


def _groups(m: Y | None) -> Iterator[tuple[str, YMap]]:
    """Every group in m, nested ones too."""
    for k, v in _pairs(_get(m, "groups")):
        if isinstance(v, YMap):
            yield k.value, v
            yield from _groups(v)


def _nest(box: YMap, problems: list[Problem]) -> None:
    """Move each group and node with `in: g` into g's `groups` or `nodes`."""
    groups = dict(_groups(box))
    for section, what in (("groups", "group"), ("nodes", "node")):
        top = _get(box, section)
        moved = False
        for k, v in _pairs(top):
            parent = _pop(v, "in") if isinstance(v, YMap) else None
            if parent is None:
                continue
            name = parent.value if isinstance(parent, YScalar) else ""
            target = groups.get(name)
            if target is None:
                problems.append(
                    Problem(parent.loc, f"{what} '{k.value}' is in unknown group '{name}'{did_you_mean(name, groups)}")
                )
                continue
            if section == "groups" and (target is v or any(g is target for _, g in _groups(v))):
                problems.append(Problem(parent.loc, f"group '{k.value}' is inside itself through 'in'"))
                continue
            assert isinstance(top, YMap)
            top.pairs = [p for p in top.pairs if p[0] is not k]
            held = _get(target, section)
            if not isinstance(held, YMap):
                held = YMap(target.loc, [])
                _pop(target, section)
                target.pairs.append((_key(target, section), held))
            held.pairs.append((k, v))
            moved = True
            _warn(problems, parent, f"writes {what} '{k.value}' inside group '{name}', in place of 'in: {name}'")
        # A section emptied by the moves goes, as version 2 would reject it empty; one written empty stays.
        if moved and isinstance(top, YMap) and not top.pairs:
            _pop(box, section)


def _nodes(m: Y | None) -> Iterator[tuple[YScalar, Y]]:
    yield from _pairs(_get(m, "nodes"))
    for _, g in _pairs(_get(m, "groups")):
        yield from _nodes(g)


def _triggers(tree: YMap, components: list[YMap], problems: list[Problem]) -> None:
    """Move each node's `trigger` and `plays` to the scenario it plays."""
    for c in components:
        for k, v in _nodes(c):
            if isinstance(v, YMap) and _get(v, "trigger") is not None:
                problems.append(
                    Problem(
                        k.loc,
                        "version 2 has no triggers in components: give the scenario "
                        f"'trigger: {{at: <instance>/{k.value}, label: ...}}'",
                    )
                )
    scenarios = _get(tree, "scenarios")
    first = next((k.value for k, _ in _pairs(scenarios)), None)
    for k, v in _nodes(tree):
        if not isinstance(v, YMap):
            continue
        label, plays = _pop(v, "trigger"), _pop(v, "plays")
        if label is None:
            if plays is not None:
                _warn(problems, plays, "drops 'plays' on a node without a trigger")
            continue
        sid = plays.value if isinstance(plays, YScalar) else first
        sc = _get(scenarios, sid) if sid else None
        where = plays or label
        if not isinstance(sc, YMap):
            problems.append(
                Problem(where.loc, f"node '{k.value}' has a trigger, but there is no scenario '{sid}' to play")
            )
        elif _get(sc, "trigger") is not None:
            problems.append(
                Problem(
                    where.loc, f"scenario '{sid}' has two triggers; version 2 gives a scenario one, on the scenario"
                )
            )
        else:
            at = (_key(label, "at"), _text(k, k.value))
            sc.pairs.append((_key(label, "trigger"), YMap(label.loc, [at, (_key(label, "label"), label)])))
            _warn(
                problems, label, f"writes the trigger on scenario '{sid}' as 'trigger: {{at: {k.value}, label: ...}}'"
            )


def _text_change(head: str, text: str | None, set_is_text: bool) -> tuple[str, str] | None:
    """The version 2 key and text for a version 1 'set' or 'status' effect, or None if it is not one."""
    verb = re.split(r"[\s:]", head.strip(), maxsplit=1)[0]
    if verb not in ("set", "status") or (verb == "set" and not set_is_text):
        return None
    if text is None and ":" in head:
        head, _, text = head.partition(":")
    args = re.sub(r"\s*->\s*", "->", head.strip()).split()[1:]
    n = 1 if verb == "set" else 0
    if text is None:
        # 'set n.sub 300ms some text', 'status some text'
        if len(args) < n:
            return None
        target, rest = args[:n], args[n:]
        ms = [rest.pop(0)] if rest and DURATION.fullmatch(rest[0]) else []
        text = " ".join(rest).strip('"')
    else:
        ms = [args.pop()] if args and DURATION.fullmatch(args[-1]) else []
        if len(args) != n:
            return None
        target, text = args, text.strip()
    return " ".join((target if verb == "set" else ["status"]) + ms), text


def _effects(y: Y | None, set_is_text: bool, problems: list[Problem]) -> None:
    if not isinstance(y, YSeq):
        return
    for i, item in enumerate(y.items):
        change = None
        if isinstance(item, YSeq):
            _effects(item, set_is_text, problems)
        elif isinstance(item, YMap) and sorted(item.keys()) == ["do", "repeat"]:
            n, body = _get(item, "repeat"), _get(item, "do")
            _effects(body, set_is_text, problems)
            if isinstance(n, YScalar) and n.value.isdigit() and body is not None:
                y.items[i] = YMap(item.loc, [(_key(n, f"repeat {n.value}"), body)])
                _warn(problems, item, f"writes this as 'repeat {n.value}: [...]'")
        elif isinstance(item, YMap) and len(item.pairs) == 1:
            k, v = item.pairs[0]
            if isinstance(v, YSeq):
                _effects(v, set_is_text, problems)
            elif isinstance(v, YScalar):
                change = _text_change(k.value, v.value, set_is_text)
        elif isinstance(item, YScalar) and not item.null:
            change = _text_change(item.value, None, set_is_text)
        if change:
            key, text = change
            y.items[i] = YMap(item.loc, [(_key(item, key), _text(item, text))])
            _warn(problems, item, f"writes this as '{key}: {text}'")
