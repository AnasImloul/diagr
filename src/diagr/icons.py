from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

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
    body = text[root.end():text.rindex("</svg>")]
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


def _read_source(folder: Path) -> IconSource:
    tiles: dict[str, Tile] = {}
    recolour: dict[str, str] = {}
    meta = folder / "icons.yml"
    if meta.exists():
        data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
        for name, t in (data.get("tiles") or {}).items():
            tiles[name] = Tile(name, t["tone"], t["glyph"], bool(t.get("spins", False)))
        recolour = dict(data.get("recolour") or {})
    return IconSource(folder, tiles, recolour)


class Icons:
    def __init__(self, folders: list[Path]):
        self.sources = [_read_source(f) for f in folders if f.is_dir()] + [_read_source(CORE)]
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
                return _import_svg(name, path.read_text(encoding="utf-8"), src.recolour.get(name))
        return None

    def names(self) -> list[str]:
        out: set[str] = set()
        for src in self.sources:
            out.update(src.tiles)
            out.update(p.stem for p in src.folder.glob("*.svg"))
        return sorted(out)
