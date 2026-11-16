from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

import yaml

from .model import Loc
from .source import Problem

CORE = Path(__file__).resolve().parent / "iconsets" / "core"
PRESENTATION = (
    "fill",
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "fill-rule",
    "clip-rule",
    "opacity",
    "color",
)
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
# Icon markup is inlined into the HTML page, so only drawing elements may pass. An allowlist, because the HTML parser
# turns some tag names (p, img, div...) into HTML even inside <svg>. No <style>: inlined, it would style the whole page.
SVG_ELEMENTS = frozenset(
    """
    a animate animateMotion animateTransform circle clipPath defs desc ellipse feBlend feColorMatrix
    feComponentTransfer feComposite feConvolveMatrix feDiffuseLighting feDisplacementMap feDistantLight feDropShadow
    feFlood feFuncA feFuncB feFuncG feFuncR feGaussianBlur feImage feMerge feMergeNode feMorphology feOffset
    fePointLight feSpecularLighting feSpotLight feTile feTurbulence filter g image line linearGradient marker mask
    metadata mpath path pattern polygon polyline radialGradient rect stop svg switch symbol text textPath title
    tspan use view
""".split()
)


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


def _clean(markup: str) -> str:
    """The children of the <svg> root in markup, written back from the parsed tree, so comments, processing
    instructions and other namespaces never reach the page. Raises ValueError when the markup does more than draw."""
    if "<![CDATA[" in markup:
        raise ValueError("contains a CDATA section")
    try:
        root = ET.fromstring(markup)
    except ET.ParseError as e:
        raise ValueError(f"is not well-formed XML ({e})") from None
    for key, value in root.attrib.items():
        _attribute("svg", key, value)
    return _children(root)


def _children(el: ET.Element) -> str:
    out = escape(el.text or "", quote=False)
    for child in el:
        out += _element(child) + escape(child.tail or "", quote=False)
    return out


def _element(el: ET.Element) -> str:
    ns, _, tag = el.tag.rpartition("}")
    if ns.lstrip("{") not in ("", SVG_NS):
        return ""
    if tag == "style":
        raise ValueError("contains <style>, which would style the whole page; use presentation attributes instead")
    if tag not in SVG_ELEMENTS:
        raise ValueError(f"contains <{tag}>, which is not an SVG drawing element")
    if tag.startswith("animate") and el.get("attributeName", "").endswith("href"):
        raise ValueError(f"has an <{tag}> that changes a link")
    attrs = ""
    for key, value in el.attrib.items():
        name = _attribute(tag, key, value)
        if name:
            attrs += f' {name}="{escape(value, quote=True)}"'
    inner = _children(el)
    return f"<{tag}{attrs}>{inner}</{tag}>" if inner else f"<{tag}{attrs}/>"


def _internal(ref: str) -> bool:
    return ref.startswith(("#", "data:image/"))


def _attribute(tag: str, key: str, value: str) -> str | None:
    """The name to write an attribute under, or None to leave it out."""
    ns, _, local = key.rpartition("}")
    ns = ns.lstrip("{")
    if local.lower().startswith("on"):
        raise ValueError(f"has an event handler '{local}'")
    flat = re.sub(r"\s", "", value).lower()
    if "javascript:" in flat:
        raise ValueError(f"has a javascript: URL in '{local}'")
    if any(not _internal(ref.strip("'\"")) for ref in re.findall(r"url\(([^)]*)\)", flat)):
        raise ValueError(f"loads an external resource in '{local}'")
    if local == "href" and ns in ("", XLINK_NS):
        if not (_internal(flat) or (tag == "a" and flat.startswith(("http:", "https:", "mailto:")))):
            raise ValueError(f"loads an external resource in '{local}'")
        return "href"
    return local if ns == "" else None


def _attrs(tag: str) -> dict[str, str]:
    return {k: a or b for k, a, b in re.findall(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', tag)}


def _import_svg(name: str, text: str, recolour: str | None) -> SvgIcon:
    text = re.sub(r"<\?xml.*?\?>|<!--.*?-->|<!DOCTYPE.*?>", "", text, flags=re.S)
    root = re.search(r"<svg\b([^>]*)>", text)
    if not root:
        raise ValueError(f"icon '{name}' is not an SVG")
    attrs = _attrs(root.group(1))
    end = text.rfind("</svg>")
    if end < root.end():
        raise ValueError(f"icon '{name}' has no closing </svg>")
    body = text[root.end() : end]
    body = re.sub(r"<title>.*?</title>|<desc>.*?</desc>", "", body, flags=re.S).strip()
    head = root.group(0) if "xmlns:xlink" in root.group(0) else f'<svg xmlns:xlink="{XLINK_NS}"' + root.group(0)[4:]
    try:
        body = _clean(head + body + "</svg>")
    except ValueError as e:
        raise ValueError(f"icon '{name}' {e}") from None
    w, h = attrs.get("width", "64").removesuffix("px"), attrs.get("height", "64").removesuffix("px")
    view_box = attrs.get("viewBox") or f"0 0 {w} {h}"
    sid = _symbol_id(name)
    ids = re.findall(r"""\bid=["']([^"']+)["']""", body)
    for i in ids:
        q = re.escape(i)
        body = re.sub(rf"""\bid=(["']){q}\1""", f'id="{sid}-{i}"', body)
        body = re.sub(rf"url\(#{q}\)", f"url(#{sid}-{i})", body)
        body = re.sub(rf"""href=(["'])#{q}\1""", f'href="#{sid}-{i}"', body)
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
        try:
            glyph = _clean(f'<svg xmlns="{SVG_NS}" xmlns:xlink="{XLINK_NS}">{t["glyph"]}</svg>')
        except ValueError as e:
            problems.append(Problem(where, f"tile '{name}': glyph {e}"))
            continue
        tiles[str(name)] = Tile(str(name), t["tone"], glyph, bool(t.get("spins", False)))
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

    def available(self) -> list[tuple[str, str, Path]]:
        """(name, 'tile' or 'svg', folder) for every icon, as a lookup would find it."""
        found: dict[str, tuple[str, str, Path]] = {}
        for src in self.sources:
            for name in src.tiles:
                found.setdefault(name, (name, "tile", src.folder))
            for path in sorted(src.folder.glob("*.svg")):
                found.setdefault(path.stem, (path.stem, "svg", src.folder))
        return sorted(found.values())
