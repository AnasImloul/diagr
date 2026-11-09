from __future__ import annotations

import json
from html import escape
from pathlib import Path

from ..build import Prepared
from ..scenario import Compiled
from ..scene import num, serialise

ASSETS = Path(__file__).resolve().parent / "assets"
PROPS = {"fill": "fill", "stroke": "stroke", "stop-color": "stop-color"}

ICONS = {
    "reset": '<path d="M3 2h2v12H3zM14 2v12L6 8z"/>',
    "back": '<path d="M2 2h2v12H2zM14 2v12L5 8z"/>',
    "play": '<path d="M4 2v12l10-6z"/>',
    "pause": '<path d="M3 2h4v12H3zM9 2h4v12H9z"/>',
    "next": '<path d="M12 2h2v12h-2zM2 2v12l9-6z"/>',
}
TOGGLE = (
    '<button id="toggle" type="button" aria-label="Switch between light and dark mode" '
    'title="Switch theme"><svg class="moon" viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/></svg>'
    '<svg class="sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/>'
    '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4'
    'M17.7 6.3l1.4-1.4"/></svg></button>'
)
THEME_BOOT = (
    '<script>(function(){var t=null;try{t=localStorage.getItem("diagr-theme")}catch(e){}'
    'if(t!=="light"&&t!=="dark")t=window.matchMedia&&matchMedia("(prefers-color-scheme: dark)").matches'
    '?"dark":"light";document.documentElement.setAttribute("data-theme",t)})();</script>'
)
THEME_TOGGLE = (
    '<script>document.getElementById("toggle").addEventListener("click",function(){var r=document.'
    'documentElement,n=r.getAttribute("data-theme")==="dark"?"light":"dark";r.setAttribute("data-theme",n);'
    'try{localStorage.setItem("diagr-theme",n)}catch(e){}});</script>'
)


def _button(act: str, label: str) -> str:
    return (
        f'<button type="button" class="{act}" data-act="{act}" aria-label="{label}" title="{label}">'
        f'<svg viewBox="0 0 16 16" aria-hidden="true">{ICONS[act]}</svg></button>'
    )


def _steps(c: Compiled, hidden: bool, tagged: bool) -> str:
    items = "\n".join(
        f'<li data-s="{i}"><span class="num" aria-hidden="true">{i}</span><div><h3><button type="button" '
        f'aria-label="Step {i}: {escape(s.title, quote=True)}">{escape(s.title)}</button></h3>'
        + (f"<p>{escape(s.text)}</p>" if s.text else "")
        + "</div></li>"
        for i, s in enumerate(c.steps, 1)
    )
    attrs = (f' data-scenario="{escape(c.id, quote=True)}"' if tagged else "") + (" hidden" if hidden else "")
    return f'<ol class="steps"{attrs}>\n{items}\n</ol>'


def _json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_html(p: Prepared) -> str:
    d, t = p.diagram, p.theme
    sb = p.scene()
    body, b = sb.build()
    defs = sb.defs()
    used: set[tuple[str, str]] = set()

    def paint(prop: str, token: str) -> str:
        used.add((prop, token))
        return f"p-{prop}-{token}"

    label = escape(d.description or d.title or d.id, quote=True)
    # role=img would hide the trigger buttons inside from assistive tech.
    role = "group" if any(n.trigger for n in d.nodes.values()) else "img"
    comps = list(p.scenarios.values())
    current = f'data-scenario="{escape(comps[0].id)}" ' if len(comps) > 1 else ""
    svg = (
        f'<svg class="diagr" {current}id="dg-{escape(d.id)}" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{num(b.x)} {num(b.y)} {num(b.w)} {num(b.h)}" font-family="{escape(t.font, quote=True)}" '
        f'role="{role}" aria-label="{label}">'
        + serialise(defs, "html", paint)
        + serialise(body, "html", paint)
        + "</svg>"
    )

    paint_css = "\n".join(f".p-{prop}-{tok} {{ {PROPS[prop]}: var(--{tok}); }}" for prop, tok in sorted(used))
    root = (
        f":root {{ --font: {t.font}; --page-width: {num(b.w)}px; {t.css_vars('light')} }}\n"
        f':root[data-theme="dark"] {{ {t.css_vars("dark")} }}\n'
    )
    css = root + (ASSETS / "page.css").read_text(encoding="utf-8") + "\n" + paint_css

    panel = ""
    script = ""
    if comps:
        first = comps[0]
        lists = "\n".join(_steps(c, hidden=c is not first, tagged=len(comps) > 1) for c in comps)
        picker = ""
        if len(comps) > 1:
            picker = (
                '<div class="scenarios" role="group" aria-label="Scenario">'
                + "".join(
                    f'<button type="button" data-scenario="{escape(c.id, quote=True)}" '
                    f'aria-pressed="{"true" if c is first else "false"}">{escape(c.title or c.id)}</button>'
                    for c in comps
                )
                + "</div>"
            )
        controls = (
            '<div class="controls" role="toolbar" aria-label="Scenario" data-playing="0">'
            + _button("reset", "Reset (Home)")
            + _button("back", "Previous step (Left)")
            + _button("play", "Play (Space)")
            + _button("pause", "Pause (Space)")
            + _button("next", "Next step (Right)")
            + f'<input id="scrub" type="range" min="0" max="{len(first.frames) - 1}" step="1" value="0" '
            'aria-label="Position">' + '<select id="speed" aria-label="Speed"><option value="0.5">0.5x</option>'
            '<option value="1" selected>1x</option><option value="2">2x</option></select></div>'
        )
        panel = (
            f'<div class="panel idle" id="panel">{picker}<div class="bar"><i id="fill"></i></div>'
            f'<div class="row"><div id="status" aria-live="polite">{escape(first.ready)}</div>{controls}</div>'
            f"{lists}</div>"
        )
        payload = {
            "scenarios": [
                {
                    "id": c.id,
                    "ready": c.ready,
                    "frames": [f.to_json() for f in c.frames],
                    "steps": [{"first": s.first, "last": s.last} for s in c.steps],
                }
                for c in comps
            ]
        }
        script = (
            f'<script type="application/json" id="diagr-data">{_json(payload)}</script>\n'
            f"<script>\n{(ASSETS / 'player.js').read_text(encoding='utf-8')}</script>"
        )
        if len(comps) > 1:
            css += "\n" + "\n".join(
                f'svg.diagr[data-scenario="{c.id}"] [data-badges]:not([data-badges="{c.id}"]) {{ display: none; }}'
                for c in comps
            )

    title = escape(d.title or d.id)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{css}
</style>
{THEME_BOOT}
</head>
<body>
{TOGGLE}
<div class="wrap">
{svg}
{panel}
</div>
{THEME_TOGGLE}
{script}
</body>
</html>
"""
