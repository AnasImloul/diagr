"""Render ```diagr fenced blocks in Markdown, through the custom fences of pymdownx.superfences (MkDocs Material).

    markdown_extensions:
      - pymdownx.superfences:
          custom_fences:
            - name: diagr
              class: diagr
              format: !!python/name:diagr.markdown.fence
              validator: !!python/name:diagr.markdown.validate

A diagram with a scenario becomes the player, in an iframe that sizes itself to the page and follows the site's light
or dark scheme; one without, or a fence opened with ```diagr mode="static", becomes the static SVGs. Relative paths
(icons, themes) resolve from the working directory, which for `mkdocs build` is the project root.
"""

from __future__ import annotations

import base64
import html
import logging
from pathlib import Path
from typing import Any

from .build import prepare
from .parse import from_tree
from .source import DiagramError, load
from .theme import SCHEMES

log = logging.getLogger("mkdocs.plugins.diagr")

MODES = ("auto", "player", "static")

# Runs in the docs page once the iframe has loaded: match its height to the diagram page, and with MkDocs Material
# follow the palette toggle (hiding the player's own toggle, since the site's applies).
ONLOAD = (
    "(function(f){var d=f.contentDocument,b=document.body;if(!d)return;"
    "new ResizeObserver(function(){f.style.height=d.documentElement.scrollHeight+'px'}).observe(d.documentElement);"
    "if(!b.hasAttribute('data-md-color-scheme'))return;"
    "var t=d.getElementById('toggle');if(t)t.style.display='none';"
    "var s=function(){d.documentElement.setAttribute('data-theme',"
    "b.getAttribute('data-md-color-scheme')==='slate'?'dark':'light')};"
    "s();new MutationObserver(s).observe(b,{attributes:true,attributeFilter:['data-md-color-scheme']})})(this)"
)


def validate(language: str, inputs: dict[str, str], options: dict[str, Any], attrs: dict[str, Any], md: Any) -> bool:
    """Accept `mode="auto|player|static"` on the fence's opening line."""
    mode = inputs.pop("mode", "auto")
    if mode not in MODES:
        return False
    options["mode"] = mode
    return True


def fence(source: str, language: str, css_class: str, options: dict[str, Any], md: Any, **kwargs: Any) -> str:
    try:
        return render(source, options.get("mode", "auto"), css_class or "diagr")
    except DiagramError as e:
        for p in e.problems:
            log.warning("diagr block: %s", p)
        lines = "\n".join(html.escape(str(p)) for p in e.problems)
        return f'<pre class="{css_class or "diagr"} diagr-error"><code>{lines}</code></pre>'


def render(source: str, mode: str = "auto", css_class: str = "diagr") -> str:
    """The HTML for one diagram given as YAML text."""
    from .render.html import render_html
    from .render.svg import render_static

    d = from_tree(load(source, "<diagr block>"), "<diagr block>", Path.cwd())
    p = prepare(d)
    for w in p.warnings:
        log.warning("diagr block: %s", w)
    title = html.escape(d.title or d.id, quote=True)
    if mode == "player" or (mode == "auto" and d.scenarios):
        page = html.escape(render_html(p), quote=True)
        return (
            f'<iframe class="{css_class} diagr-embed" title="{title}" srcdoc="{page}" '
            f'onload="{html.escape(ONLOAD, quote=True)}" allowfullscreen '
            'style="display:block;width:100%;border:0;min-height:240px"></iframe>'
        )
    imgs = []
    for scheme in SCHEMES:
        svg = render_static(p.scene(), p.theme, scheme)
        uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
        imgs.append(f'<img alt="{title}" src="{uri}#only-{scheme}">')
    return f'<p class="{css_class}">{"".join(imgs)}</p>'
