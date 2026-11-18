from __future__ import annotations

from collections.abc import Collection
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


def tone_groups(d: Diagram, t: Theme) -> None:
    """A tone for each group without one. A box that holds other boxes is neutral, a frame around them; the others
    take the theme's tones in turn, in the order the file has them, skipping their parent's. A component's group has
    one tone in every instance ('a/data' and 'b/data'), since it is the same thing in each."""
    cycle = [k for k in t.tones if k != "neutral"]
    parents = {g.parent for g in d.groups.values()}
    shared: dict[str, str] = {}
    turn = 0
    for g in d.groups.values():
        if g.tone is not None:
            continue
        if g.id in parents or not g.box or not cycle:
            g.tone = "neutral"
            continue
        local = g.id.partition("/")[2]
        if local in shared:
            g.tone = shared[local]
            continue
        skip = d.groups[g.parent].tone if g.parent in d.groups else None
        g.tone = cycle[turn % len(cycle)]
        turn += 1
        if g.tone == skip:
            g.tone = cycle[turn % len(cycle)]
            turn += 1
        if local:
            shared[local] = g.tone


def prepare(d: Diagram, theme: str | None = None) -> Prepared:
    t = load_theme(theme, Path.cwd()) if theme else load_theme(d.theme, d.base)
    tone_groups(d, t)
    place(d, t)
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


# What a build can write for a diagram and each of its views: the static SVG for each scheme, and the HTML page.
OUTPUTS = (*SCHEMES, "html")


def build_files(
    path: str | Path,
    out: str | Path,
    theme: str | None = None,
    *,
    outputs: Collection[str],
    debug: bool = False,
    live: bool = False,
    background: bool = False,
) -> tuple[list[Path], list[Problem]]:
    ps = prepare_all(load_file(path), theme)
    written = [
        f for p in ps for f in write_files(p, out, outputs=outputs, debug=debug, live=live, background=background)
    ]
    return written, [w for p in ps for w in p.warnings]


def write_files(
    p: Prepared,
    out: str | Path,
    *,
    outputs: Collection[str],
    debug: bool = False,
    live: bool = False,
    background: bool = False,
) -> list[Path]:
    """The files among OUTPUTS that outputs names: 'light' and 'dark' for the static SVGs, 'html' for the page.
    debug adds the authoring overlay to the page, live the reload script, and background paints the theme's background
    behind the SVGs."""
    unknown = sorted(set(outputs) - set(OUTPUTS))
    if unknown:
        raise ValueError(f"unknown output {', '.join(unknown)}; outputs are {', '.join(OUTPUTS)}")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for scheme in SCHEMES:
        if scheme in outputs:
            f = out / f"{p.diagram.id}-{scheme}.svg"
            f.write_text(render_static(p.scene(), p.theme, scheme, background), encoding="utf-8")
            written.append(f)
    if "html" in outputs:
        f = out / f"{p.diagram.id}.html"
        f.write_text(render_html(p, debug, live), encoding="utf-8")
        written.append(f)
    return written
