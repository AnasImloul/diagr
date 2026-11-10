from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .icons import Icons
from .layout.auto import place
from .layout.engine import layout, sub_slots
from .layout.geometry import Layout
from .model import Diagram
from .parse import load_file
from .render.html import render_html
from .render.scene import SceneBuilder
from .render.svg import render_static
from .scenario import Compiled, compile_scenarios
from .source import DiagramError, Problem
from .theme import SCHEMES, Theme, load_theme
from .validate import check_layout, check_model
from .views import view


@dataclass
class Prepared:
    diagram: Diagram
    theme: Theme
    icons: Icons
    layout: Layout
    scenarios: dict[str, Compiled]
    warnings: list[Problem] = field(default_factory=list)

    def scene(self) -> SceneBuilder:
        return SceneBuilder(self.diagram, self.theme, self.layout, self.icons, self.scenarios)


def prepare(d: Diagram, theme: str | None = None) -> Prepared:
    place(d)
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


def prepare_all(d: Diagram, theme: str | None = None) -> list[Prepared]:
    """The diagram and each of its views, ready to render. A view's problems name the view."""
    out = [prepare(d, theme)]
    out[0].warnings = d.upgraded + out[0].warnings
    for vid in d.views:
        try:
            p = prepare(view(d, vid), theme)
        except DiagramError as e:
            raise DiagramError([_in_view(vid, x) for x in e.problems]) from None
        p.warnings = [_in_view(vid, x) for x in p.warnings]
        out.append(p)
    return out


def _in_view(vid: str, p: Problem) -> Problem:
    return Problem(p.loc, f"in view '{vid}': {p.message}", p.level)


def build_files(
    path: str | Path, out: str | Path, theme: str | None = None, debug: bool = False, live: bool = False
) -> tuple[list[Path], list[Problem]]:
    ps = prepare_all(load_file(path), theme)
    return [f for p in ps for f in write_files(p, out, debug, live)], [w for p in ps for w in p.warnings]


def write_files(p: Prepared, out: str | Path, debug: bool = False, live: bool = False) -> list[Path]:
    """The two static SVGs and the HTML page; debug adds the authoring overlay, live the reload script."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for scheme in SCHEMES:
        f = out / f"{p.diagram.id}-{scheme}.svg"
        f.write_text(render_static(p.scene(), p.theme, scheme), encoding="utf-8")
        written.append(f)
    f = out / f"{p.diagram.id}.html"
    f.write_text(render_html(p, debug, live), encoding="utf-8")
    written.append(f)
    return written
