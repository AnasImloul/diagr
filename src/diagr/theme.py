from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

BUILTIN = Path(__file__).resolve().parent / "themes"
SCHEMES = ("light", "dark")


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


def _read(ref: str, base: Path) -> dict:
    path = BUILTIN / f"{ref}.yml"
    if not path.exists():
        path = (base / ref).resolve()
    if not path.exists():
        raise FileNotFoundError(f"theme '{ref}' not found (looked in the built-in themes and {base})")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "extends" in data:
        data = _merge(_read(data.pop("extends"), path.parent), data)
    return data


def load_theme(ref: str = "default", base: Path | None = None) -> Theme:
    data = _read(ref, base or Path.cwd())
    tokens = {s: _flatten(data[s]) for s in SCHEMES}
    return Theme(
        name=data.get("name", ref),
        font=data["font"],
        sizes={k: float(v) for k, v in data["sizes"].items()},
        tokens=tokens,
        tones=list(data["light"]["tones"]),
        tiles=list(data["light"]["tiles"]),
    )
