from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .icons import Icons
from .layout.geometry import Layout, layout, sub_slots
from .model import Diagram
from .parse import load_file
from .scenario import Compiled, compile_scenario
from .scene import SceneBuilder
from .source import DiagramError, Problem
from .theme import SCHEMES, Theme, load_theme
from .validate import check_layout, check_model


@dataclass
class Prepared:
    diagram: Diagram
    theme: Theme
    icons: Icons
    layout: Layout
    compiled: Compiled | None
    warnings: list[Problem] = field(default_factory=list)

    def scene(self) -> SceneBuilder:
        return SceneBuilder(self.diagram, self.theme, self.layout, self.icons, self.compiled)


def prepare(d: Diagram, theme: str | None = None) -> Prepared:
    try:
        t = load_theme(theme, Path.cwd()) if theme else load_theme(d.theme, d.base)
    except (FileNotFoundError, KeyError) as e:
        raise DiagramError([Problem(None, f"theme: {e}")]) from None
    icons = Icons([(d.base / f).resolve() for f in d.icons])
    problems = check_model(d, t, icons)
    if any(p.level == "error" for p in problems):
        raise DiagramError(problems)
    lay = layout(d, t)
    problems += check_layout(d, lay)
    if any(p.level == "error" for p in problems):
        raise DiagramError(problems)
    comp = compile_scenario(d, sub_slots(d))
    return Prepared(d, t, icons, lay, comp, problems)


def build_files(path: str | Path, out: str | Path, theme: str | None = None) -> tuple[list[Path], list[Problem]]:
    from .render.html import render_html
    from .render.svg import render_static

    p = prepare(load_file(path), theme)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for scheme in SCHEMES:
        f = out / f"{p.diagram.id}-{scheme}.svg"
        f.write_text(render_static(p.scene(), p.theme, scheme), encoding="utf-8")
        written.append(f)
    f = out / f"{p.diagram.id}.html"
    f.write_text(render_html(p), encoding="utf-8")
    written.append(f)
    return written, p.warnings
