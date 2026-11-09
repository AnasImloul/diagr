"""MkDocs hook: build every example with diagr and publish it as a docs page."""

import contextlib
import io
import tempfile
from pathlib import Path

import yaml
from mkdocs.structure.files import File

from diagr.cli import main as diagr

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

## Source

```yaml
{source}
```
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
            status = diagr(["build", str(yml), "-o", str(built)])
            contrast = diagr(["build", str(yml), "-o", str(built / "contrast"), "--theme", "contrast"])
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
        lines = [ln for ln in yml.read_text().splitlines() if not ln.startswith("# yaml-language-server")]
        page = PAGE.format(id=id_, title=title, description=description, source="\n".join(lines).strip())
        files.append(File.generated(config, f"examples/{id_}.md", content=page))
        items.append(ITEM.format(id=id_, title=title, description=description))
    files.append(File.generated(config, "examples/index.md", content=INDEX.format(items="\n".join(items))))
    return files
