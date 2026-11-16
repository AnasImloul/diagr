"""MkDocs hook: build every example with diagr and publish it as a docs page, and draw the core icon gallery."""

import base64
import contextlib
import html
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path

import yaml
from mkdocs.structure.files import File

import diagr as package
from diagr.build import prepare
from diagr.cli import main as diagr
from diagr.icons import Icons, Tile
from diagr.parse import loads
from diagr.render.svg import render_static
from diagr.theme import SCHEMES

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

PAGE = """# {title}

{description}
{{ .dg-lead }}

<iframe class="diagr-embed" src="{id}.html" title="{title}" loading="lazy" allowfullscreen></iframe>

## Static images

=== "Light"

    ![{title}, light]({id}/{id}-light.svg){{ .dg-shot }}

=== "Dark"

    ![{title}, dark]({id}/{id}-dark.svg){{ .dg-shot }}

=== "Contrast"

    ![{title}, contrast theme]({id}/contrast/{id}-light.svg#only-light){{ .dg-shot }}
    ![{title}, contrast theme]({id}/contrast/{id}-dark.svg#only-dark){{ .dg-shot }}

    The same diagram in the built-in `contrast` theme (`diagr build --theme contrast`), in the site's light or dark
    scheme.

{views}## Source

```yaml
{source}
```
"""

VIEWS = """## Views

This diagram has [views](../format.md#views): parts of it built as their own images and pages, next to the whole
diagram's.

{items}
"""

VIEW = """### {title}

{kind}`{key}`: written as `{id}-{key}-light.svg`, `{id}-{key}-dark.svg` and [`{id}-{key}.html`]({id}/{id}-{key}.html).

![{title}]({id}/{id}-{key}-light.svg#only-light){{ .dg-shot .dg-view }}
![{title}]({id}/{id}-{key}-dark.svg#only-dark){{ .dg-shot .dg-view }}
"""

INDEX = """---
hide: [toc]
---

# Examples

Each example is built from its `diagram.yml` when the docs are built. The embedded player is the same self-contained
HTML page that `diagr build` writes.
{{ .dg-lead }}

{items}
"""

ITEM = """<div class="dg-example" markdown>
[![{title}]({id}/{id}-light.svg#only-light)![{title}]({id}/{id}-dark.svg#only-dark)]({id}.md){{ .dg-frame }}

<div markdown>
## [{title}]({id}.md)

{description}
</div>
</div>
"""


def on_files(files, config):
    out = Path(tempfile.mkdtemp(prefix="diagr-docs-"))
    items = []
    for yml in sorted(EXAMPLES.glob("*/diagram.yml")):
        built = out / yml.parent.name
        with contextlib.redirect_stdout(io.StringIO()):
            status = diagr(["build", str(yml), "-o", str(built), "--svg", "--html"])
            contrast = diagr(["build", str(yml), "-o", str(built / "contrast"), "--theme", "contrast", "--svg"])
        if status != 0 or contrast != 0:
            raise RuntimeError(f"diagr build failed for {yml}")
        data = yaml.safe_load(yml.read_text())
        id_, title = data["id"], data["title"]
        description = " ".join(str(data.get("description", "")).split())
        for name in (f"{id_}.html", f"{id_}-light.svg", f"{id_}-dark.svg"):
            files.append(File.generated(config, f"examples/{id_}/{name}", abs_src_path=str(built / name)))
        for name in (f"{id_}-light.svg", f"{id_}-dark.svg"):
            src = str(built / "contrast" / name)
            files.append(File.generated(config, f"examples/{id_}/contrast/{name}", abs_src_path=src))
        views = ""
        if data.get("views"):
            items = []
            for key, v in data["views"].items():
                for name in (f"{id_}-{key}.html", f"{id_}-{key}-light.svg", f"{id_}-{key}-dark.svg"):
                    files.append(File.generated(config, f"examples/{id_}/{name}", abs_src_path=str(built / name)))
                kind = f"A dynamic view of the `{v['scenario']}` scenario. " if v.get("scenario") else ""
                items.append(VIEW.format(id=id_, key=key, kind=kind, title=v.get("title") or title))
            views = VIEWS.format(items="\n".join(items)) + "\n"
        lines = [ln for ln in yml.read_text().splitlines() if not ln.startswith("# yaml-language-server")]
        page = PAGE.format(id=id_, title=title, description=description, views=views, source="\n".join(lines).strip())
        files.append(File.generated(config, f"examples/{id_}.md", content=page))
        items.append(ITEM.format(id=id_, title=title, description=description))
    files.append(File.generated(config, "examples/index.md", content=INDEX.format(items="\n".join(items))))
    _playground(files, config)
    return files


def _playground(files, config):
    """The diagr package as a zip for the playground's worker to unpack, and the examples it offers."""
    src = Path(package.__file__).resolve().parent
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, Path("diagr") / f.relative_to(src))
    files.append(File.generated(config, "playground/diagr.zip", content=buf.getvalue()))
    examples = []
    # The playground opens on the first: the smallest example.
    for yml in sorted(EXAMPLES.glob("*/diagram.yml"), key=lambda y: (y.parent.name != "order-flow", y)):
        lines = [ln for ln in yml.read_text().splitlines() if not ln.startswith("# yaml-language-server")]
        examples.append({"title": yaml.safe_load(yml.read_text())["title"], "source": "\n".join(lines).strip() + "\n"})
    files.append(File.generated(config, "playground/examples.json", content=json.dumps(examples)))


GALLERY = "<!-- icon-gallery -->"


def _icon_gallery() -> str:
    """Every core icon, drawn by diagr itself as a one-node diagram, in light and dark."""
    icons = Icons([])
    cells = []
    for name, _, _ in icons.available():
        d = loads(f"id: icon\nnodes:\n  x: {{icon: {name}}}\n", "<icon>", Path.cwd())
        p = prepare(d)
        # The node sits at [0, 0]: crop the picture to its tile, leaving out the room kept for a title.
        h = p.theme.size("icon") / 2 + 6
        box = f'viewBox="{-h} {-h} {2 * h} {2 * h}" width="{2 * h}" height="{2 * h}"'
        imgs = ""
        for scheme in SCHEMES:
            svg = re.sub(
                r'viewBox="[^"]*" width="[^"]*" height="[^"]*"', box, render_static(p.scene(), p.theme, scheme), count=1
            )
            svg = base64.b64encode(svg.encode()).decode()
            imgs += f'<img alt="" src="data:image/svg+xml;base64,{svg}#only-{scheme}">'
        ic = icons.get(name)
        note = f"{ic.tone}, spins" if isinstance(ic, Tile) and ic.spins else ic.tone if isinstance(ic, Tile) else ""
        cells.append(
            f'<figure class="dg-icon">{imgs}<figcaption><code>{html.escape(name)}</code>'
            f"<span>{html.escape(note)}</span></figcaption></figure>"
        )
    return '<div class="dg-icons">' + "".join(cells) + "</div>"


def on_page_markdown(markdown, page, config, files):
    if GALLERY in markdown:
        return markdown.replace(GALLERY, _icon_gallery())
    return markdown
