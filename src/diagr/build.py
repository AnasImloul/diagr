from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .icons import Icons
from .layout.geometry import Layout, layout, sub_slots
from .model import Diagram
from .parse import load_file
from .scenario import Compiled, compile_scenarios
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
    scenarios: dict[str, Compiled]
    warnings: list[Problem] = field(default_factory=list)

    @property
    def compiled(self) -> Compiled | None:
        """The first scenario, which static output shows."""
        return next(iter(self.scenarios.values()), None)

    def scene(self) -> SceneBuilder:
        return SceneBuilder(self.diagram, self.theme, self.layout, self.icons, self.scenarios)


def prepare(d: Diagram, theme: str | None = None) -> Prepared:
    t = load_theme(theme, Path.cwd()) if theme else load_theme(d.theme, d.base)
    icons = Icons([(d.base / f).resolve() for f in d.icons])
    problems = check_model(d, t, icons)
    if any(p.level == "error" for p in problems):
        raise DiagramError(problems)
    lay = layout(d, t)
    problems += check_layout(d, lay, t)
    if any(p.level == "error" for p in problems):
        raise DiagramError(problems)
    comp = compile_scenarios(d, sub_slots(d))
    return Prepared(d, t, icons, lay, comp, problems)


def build_files(
    path: str | Path, out: str | Path, theme: str | None = None, debug: bool = False
) -> tuple[list[Path], list[Problem]]:
    p = prepare(load_file(path), theme)
    return write_files(p, out, debug), p.warnings


def write_files(p: Prepared, out: str | Path, debug: bool = False) -> list[Path]:
    """The two static SVGs and the HTML page; debug adds the authoring overlay to the page."""
    from .render.html import render_html
    from .render.svg import render_static

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for scheme in SCHEMES:
        f = out / f"{p.diagram.id}-{scheme}.svg"
        f.write_text(render_static(p.scene(), p.theme, scheme), encoding="utf-8")
        written.append(f)
    f = out / f"{p.diagram.id}.html"
    f.write_text(render_html(p, debug), encoding="utf-8")
    written.append(f)
    return written
