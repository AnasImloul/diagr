from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .model import Loc
from .source import DiagramError, Problem

BUILTIN = Path(__file__).resolve().parent / "themes"
SCHEMES = ("light", "dark")
SIZES = ("icon", "group_icon", "title", "sub", "line", "label", "group_title", "group_sub", "edge", "flow", "corner",
         "group_radius", "group_inset", "group_top", "group_bottom", "badge", "margin")
TOKENS = ("bg", "text", "muted", "line", "rule", "hover", "accent", "on-accent", "fail", "new", "changed", "button",
          "on-button", "badge", "on-badge")


@dataclass
class Theme:
    name: str
    font: str
    sizes: dict[str, float]
    tokens: dict[str, dict[str, str]]
    tones: list[str]
    tiles: list[str]

    def size(self, key: str) -> float:
        return self.sizes[key]

    def hex(self, scheme: str, token: str) -> str:
        return self.tokens[scheme][token]

    def css_vars(self, scheme: str) -> str:
        return " ".join(f"--{k}: {v};" for k, v in self.tokens[scheme].items())


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _flatten(scheme: dict) -> dict[str, str]:
    flat: dict[str, str] = {}
    for k, v in scheme.items():
        if k == "tones":
            for tone, pair in v.items():
                flat[f"tone-{tone}-fill"] = pair["fill"]
                flat[f"tone-{tone}-stroke"] = pair["stroke"]
        elif k == "tiles":
            for tone, (a, b) in v.items():
                flat[f"tile-{tone}-0"] = a
                flat[f"tile-{tone}-1"] = b
        else:
            flat[k] = str(v)
    return flat


def _error(path: Path, msg: str) -> DiagramError:
    return DiagramError([Problem(None, f"theme {path}: {msg}")])


def _locate(ref: str, base: Path) -> Path:
    path = BUILTIN / f"{ref}.yml"
    return path if path.exists() else (base / ref).resolve()


def theme_files(ref: str, base: Path) -> list[Path]:
    """The theme file and the files it extends, as far as they can be read."""
    files: list[Path] = []
    while True:
        path = _locate(ref, base)
        if not path.is_file() or path in files:
            return files
        files.append(path)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return files
        parent = data.get("extends") if isinstance(data, dict) else None
        if not isinstance(parent, str):
            return files
        ref, base = parent, path.parent


def _read(ref: str, base: Path, seen: tuple[Path, ...] = ()) -> tuple[dict, Path]:
    path = _locate(ref, base)
    if not path.is_file():
        raise DiagramError([Problem(None, f"theme '{ref}' not found (looked in the built-in themes and {base})")])
    if path in seen:
        raise _error(path, "'extends' loops back to this file")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        loc = Loc(str(path), mark.line + 1, mark.column + 1) if mark else None
        raise DiagramError([Problem(loc, f"theme YAML: {e.problem or e.context}")]) from None
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise _error(path, f"cannot read: {e}") from None
    if not isinstance(data, dict):
        raise _error(path, "expected a mapping with font, sizes, light and dark")
    if "extends" in data:
        parent = data.pop("extends")
        if not isinstance(parent, str):
            raise _error(path, "'extends' must be a theme name or path")
        data = _merge(_read(parent, path.parent, (*seen, path))[0], data)
    return data, path


def _is_num(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _check_scheme(name: str, s: object) -> list[str]:
    if not isinstance(s, dict):
        return [f"'{name}' must be a mapping of colour tokens"]
    out = [f"'{name}' is missing token '{k}'" for k in TOKENS if k not in s]
    for k, v in s.items():
        if k == "tones":
            if not isinstance(v, dict):
                out.append(f"'{name}.tones' must be a mapping")
                continue
            for tone, pair in v.items():
                if not (isinstance(pair, dict) and isinstance(pair.get("fill"), str)
                        and isinstance(pair.get("stroke"), str)):
                    out.append(f"'{name}.tones.{tone}' needs 'fill' and 'stroke' colours")
        elif k == "tiles":
            if not isinstance(v, dict):
                out.append(f"'{name}.tiles' must be a mapping")
                continue
            for tone, pair in v.items():
                if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(c, str) for c in pair)):
                    out.append(f"'{name}.tiles.{tone}' must be a pair of colours")
        elif not isinstance(v, str):
            out.append(f"'{name}.{k}' must be a colour")
    return out


def _check(data: dict) -> list[str]:
    out: list[str] = []
    if not isinstance(data.get("font"), str):
        out.append("needs 'font' (a CSS font-family list)")
    sizes = data.get("sizes")
    if not isinstance(sizes, dict):
        out.append("needs 'sizes'")
    else:
        out += [f"'sizes' is missing '{k}'" for k in SIZES if k not in sizes]
        out += [f"'sizes.{k}' must be a number" for k, v in sizes.items() if not _is_num(v)]
    for s in SCHEMES:
        out += _check_scheme(s, data.get(s))
    if out:
        return out
    light, dark = data["light"], data["dark"]
    for group in ("tones", "tiles"):
        a, b = set(light.get(group) or {}), set(dark.get(group) or {})
        out += [f"'{group}.{k}' is in light but not dark" for k in sorted(a - b)]
        out += [f"'{group}.{k}' is in dark but not light" for k in sorted(b - a)]
    a = {k for k in light if k not in ("tones", "tiles")}
    b = {k for k in dark if k not in ("tones", "tiles")}
    out += [f"token '{k}' is in light but not dark" for k in sorted(a - b)]
    out += [f"token '{k}' is in dark but not light" for k in sorted(b - a)]
    return out


def load_theme(ref: str = "default", base: Path | None = None) -> Theme:
    data, path = _read(ref, base or Path.cwd())
    problems = _check(data)
    if problems:
        raise DiagramError([Problem(None, f"theme {path}: {m}") for m in problems])
    tokens = {s: _flatten(data[s]) for s in SCHEMES}
    return Theme(
        name=data.get("name", ref),
        font=data["font"],
        sizes={k: float(v) for k, v in data["sizes"].items()},
        tokens=tokens,
        tones=list(data["light"].get("tones") or {}),
        tiles=list(data["light"].get("tiles") or {}),
    )
