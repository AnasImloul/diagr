from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .model import Loc
from .source import Problem

CORE = Path(__file__).resolve().parent / "iconsets" / "core"
PRESENTATION = ("fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "fill-rule", "clip-rule",
                "opacity", "color")


@dataclass
class Tile:
    name: str
    tone: str
    glyph: str
    spins: bool = False


@dataclass
class SvgIcon:
    name: str
    symbol: str
    view_box: str
    body: str
    attrs: dict[str, str] = field(default_factory=dict)
    recolour: str | None = None


Icon = Tile | SvgIcon


def _symbol_id(name: str) -> str:
    return "i-" + re.sub(r"[^A-Za-z0-9_-]", "_", name)


def _import_svg(name: str, text: str, recolour: str | None) -> SvgIcon:
    text = re.sub(r"<\?xml.*?\?>|<!--.*?-->|<!DOCTYPE.*?>", "", text, flags=re.S)
    root = re.search(r"<svg\b([^>]*)>", text)
    if not root:
        raise ValueError(f"icon '{name}' is not an SVG")
    attrs = dict(re.findall(r'([\w:-]+)\s*=\s*"([^"]*)"', root.group(1)))
    end = text.rfind("</svg>")
    if end < root.end():
        raise ValueError(f"icon '{name}' has no closing </svg>")
    body = text[root.end():end]
    body = re.sub(r"<title>.*?</title>|<desc>.*?</desc>", "", body, flags=re.S).strip()
    w, h = attrs.get("width", "64").removesuffix("px"), attrs.get("height", "64").removesuffix("px")
    view_box = attrs.get("viewBox") or f"0 0 {w} {h}"
    sid = _symbol_id(name)
    ids = re.findall(r'\bid="([^"]+)"', body)
    for i in ids:
        body = re.sub(rf'\bid="{re.escape(i)}"', f'id="{sid}-{i}"', body)
        body = re.sub(rf"url\(#{re.escape(i)}\)", f"url(#{sid}-{i})", body)
        body = re.sub(rf'href="#{re.escape(i)}"', f'href="#{sid}-{i}"', body)
    keep = {k: v for k, v in attrs.items() if k in PRESENTATION}
    return SvgIcon(name, sid, view_box, body, keep, recolour)


@dataclass
class IconSource:
    folder: Path
    tiles: dict[str, Tile]
    recolour: dict[str, str]


def _read_source(folder: Path, problems: list[Problem]) -> IconSource:
    tiles: dict[str, Tile] = {}
    recolour: dict[str, str] = {}
    meta = folder / "icons.yml"
    if not meta.exists():
        return IconSource(folder, tiles, recolour)
    where = Loc(str(meta), 1, 1)
    try:
        data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
    except yaml.MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        loc = Loc(str(meta), mark.line + 1, mark.column + 1) if mark else where
        problems.append(Problem(loc, f"YAML: {e.problem or e.context}"))
        return IconSource(folder, tiles, recolour)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        problems.append(Problem(where, f"cannot read: {e}"))
        return IconSource(folder, tiles, recolour)
    if not isinstance(data, dict):
        problems.append(Problem(where, "expected a mapping with 'tiles' and/or 'recolour'"))
        return IconSource(folder, tiles, recolour)
    for k in data:
        if k not in ("tiles", "recolour"):
            problems.append(Problem(where, f"unknown key '{k}' (expected 'tiles' or 'recolour')"))
    raw_tiles = data.get("tiles") or {}
    if not isinstance(raw_tiles, dict):
        problems.append(Problem(where, "'tiles' must be a mapping of name to {tone, glyph}"))
        raw_tiles = {}
    for name, t in raw_tiles.items():
        if not (isinstance(t, dict) and isinstance(t.get("tone"), str) and isinstance(t.get("glyph"), str)):
            problems.append(Problem(where, f"tile '{name}' needs 'tone' and 'glyph' (SVG markup)"))
            continue
        tiles[str(name)] = Tile(str(name), t["tone"], t["glyph"], bool(t.get("spins", False)))
    raw_recolour = data.get("recolour") or {}
    if isinstance(raw_recolour, dict) and all(isinstance(v, str) for v in raw_recolour.values()):
        recolour = {str(k): v for k, v in raw_recolour.items()}
    else:
        problems.append(Problem(where, "'recolour' must map icon names to theme tokens"))
    return IconSource(folder, tiles, recolour)


class Icons:
    def __init__(self, folders: list[Path]):
        self.problems: list[Problem] = []
        self.errors: dict[str, str] = {}
        self.sources = [_read_source(f, self.problems) for f in folders if f.is_dir()]
        self.sources.append(_read_source(CORE, self.problems))
        self.missing = [f for f in folders if not f.is_dir()]
        self._cache: dict[str, Icon | None] = {}

    def get(self, name: str) -> Icon | None:
        if name not in self._cache:
            self._cache[name] = self._find(name)
        return self._cache[name]

    def _find(self, name: str) -> Icon | None:
        for src in self.sources:
            if name in src.tiles:
                return src.tiles[name]
            path = src.folder / f"{name}.svg"
            if path.exists():
                try:
                    return _import_svg(name, path.read_text(encoding="utf-8"), src.recolour.get(name))
                except (OSError, UnicodeDecodeError, ValueError) as e:
                    self.errors[name] = f"{path}: {e}"
                    return None
        return None

    def names(self) -> list[str]:
        out: set[str] = set()
        for src in self.sources:
            out.update(src.tiles)
            out.update(p.stem for p in src.folder.glob("*.svg"))
        return sorted(out)
