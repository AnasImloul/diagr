<div class="dg-hero" markdown>

# diagr

Clean diagrams from a YAML file. One file in; out come a static SVG for light mode, one for dark mode, and a
self-contained HTML page where the diagram can play a scenario step by step.
{ .dg-lead }

<div class="dg-actions" markdown>
[Quick start](#quick-start){ .md-button .md-button--primary }
[Examples](examples/index.md){ .md-button }
</div>

<figure markdown>
<div class="dg-frame" markdown>
![A web app posts an order to the API, which queues it for workers that write it to the orders database.](examples/order-flow/order-flow-light.svg#only-light)
![A web app posts an order to the API, which queues it for workers that write it to the orders database.](examples/order-flow/order-flow-dark.svg#only-dark)
</div>
<figcaption markdown>The [order processing](examples/order-flow.md) example, as `diagr build` writes it.</figcaption>
</figure>

</div>

<div class="dg-points" markdown>

- **Static first.** The SVGs are hand-laid-out on a grid, with rounded orthogonal edges, label pills and tinted
  groups. Icons are inlined and colours are baked in, so they work in READMEs, docs and slides.
- **Interactive on top.** The HTML page has a scenario player: Run, play and pause, step forward and back, scrub,
  speed, keyboard shortcuts. A diagram can have several scenarios, each with its own trigger button. The state at
  each step is computed from the step number, so stepping back and scrubbing show exactly what playing would.
- **One HTML file.** Inline SVG, CSS and JavaScript. No CDN, no framework, nothing to load at runtime.
- **Domain-neutral.** Nothing in the format assumes pipelines or a vendor. Vendor icons go in an icon folder next to
  the diagram.

</div>

## Quick start

```sh
uv sync
uv run diagr build examples/order-flow/diagram.yml -o dist
```

This writes `dist/order-flow-light.svg`, `dist/order-flow-dark.svg` and `dist/order-flow.html`.

See the [examples](examples/index.md) for rendered diagrams with their source, and the
[format reference](format.md) for everything a diagram file can say.

## CLI

| Command | What it does |
|---|---|
| `diagr init [FILE] [--id ID]` | Write a starter diagram (default `diagram.yml`); never overwrites |
| `diagr build FILE... [-o DIR] [--theme T] [--debug]` | Write the two SVGs and the HTML page for each file; `--debug` adds the grid and route overlay to the page (G toggles it) |
| `diagr watch FILE... [-o DIR] [--theme T] [--interval S] [--debug]` | Rebuild when the file, its icon folders or its theme file change; polls every 0.5 s by default |
| `diagr check FILE... [--theme T] [--strict] [--format json]` | Validate; problems are printed as `file:line:col`, or as JSON on stdout |
| `diagr icons [FILE]` | List the core icons, plus the icon folders of `FILE` if given |
| `diagr schema [-o FILE]` | Print the JSON Schema (`schema/diagr.schema.json`) |
| `diagr --version` | Print the installed version |

`--theme` on the command line is resolved against the current folder; `theme:` in a diagram against the diagram's
folder.

## Player keys

++space++ plays or pauses. ++arrow-left++ and ++arrow-right++ go to the previous or next step; with ++shift++ they
move one frame. ++home++ resets, ++end++ jumps to the end. Clicking a step in the list jumps to it. With several
scenarios, the buttons above the progress bar switch between them.
