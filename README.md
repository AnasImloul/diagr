# diagr

Clean diagrams from a YAML file. One file in; out come a static SVG for light mode, one for dark mode, and a
self-contained HTML page where the diagram can play a scenario step by step.

- **Static first.** The SVGs are hand-laid-out on a grid, with rounded orthogonal edges, label pills and tinted
  groups. Icons are inlined and colours are baked in, so they work in READMEs, docs and slides.
- **Interactive on top.** The HTML page has a scenario player: Run, play and pause, step forward and back, scrub,
  speed, keyboard shortcuts. The state at each step is computed from the step number, so stepping back and scrubbing
  show exactly what playing would.
- **One HTML file.** Inline SVG, CSS and JavaScript. No CDN, no framework, nothing to load at runtime.
- **Domain-neutral.** Nothing in the format assumes pipelines or a vendor. Vendor icons go in an icon folder next to
  the diagram.

## Quick start

```sh
uv sync
uv run diagr build examples/order-flow/diagram.yml -o dist
```

This writes `dist/order-flow-light.svg`, `dist/order-flow-dark.svg` and `dist/order-flow.html`.

```yaml
diagr: 1
diagram: order-flow
title: Order processing
grid: {col: 200, row: 170}

groups:
  front: {title: Frontend, tone: blue}
  back: {title: Backend, sub: one region, tone: teal}

nodes:
  web: {in: front, at: [0, 0], icon: browser, title: Web app, trigger: Place order}
  api: {in: back, at: [1, 0], icon: function, title: API, sub: validates}
  queue: {in: back, at: [2, 0], icon: queue, title: Order queue}
  db: {in: back, at: [3, 0], icon: database, title: Orders}

edges:
  web -> api: POST /orders
  api -> queue: enqueue
  queue -> db: write

scenario:
  steps:
    - {title: Submit, at: web, do: [activate web, draw web->api, done web]}
    - {title: Queue, at: api, do: [activate api 400ms, draw api->queue, done api]}
    - {title: Store, at: db, do: [draw queue->db, activate db 300ms, done db]}
```

In a README, use both static files so the image follows the reader's theme:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="order-flow-dark.svg">
  <img alt="Order processing" src="order-flow-light.svg">
</picture>
```

## CLI

| Command | What it does |
|---|---|
| `diagr build FILE... [-o DIR] [--theme T]` | Write the two SVGs and the HTML page for each file |
| `diagr watch FILE... [-o DIR]` | Rebuild when the file, its icon folders or its theme file change |
| `diagr check FILE... [--strict]` | Validate; errors and warnings are printed as `file:line:col` |
| `diagr schema [-o FILE]` | Print the JSON Schema (`schema/diagr.schema.json`) |

Add `# yaml-language-server: $schema=<path>/diagr.schema.json` at the top of a diagram for autocomplete in
editors that support it.

## Player keys

Space plays or pauses. Left and Right go to the previous or next step; with Shift they move one frame. Home resets,
End jumps to the end. Clicking a step in the list jumps to it.

## Docs

The docs site is built with MkDocs Material and deployed to GitHub Pages by `.github/workflows/docs.yml`. The
examples are built from `examples/` each time the site is built.

```sh
uv sync --group docs
uv run mkdocs serve          # live preview
uv run mkdocs build --strict # writes site/
```

- [Diagram format and effects](docs/format.md)
- [Themes and icons](docs/themes-and-icons.md)
- [Examples](examples/): `order-flow`, `cloud-architecture` (bus, fan-out, dead-letter queue, retries),
  `dashboard-refresh` (a pipeline with progress cells)

## Layout of this repo

| Path | What |
|---|---|
| `src/diagr/` | The package: parser, validator, layout, scenario compiler, renderers, themes, core icons |
| `examples/` | Example diagrams |
| `schema/` | Generated JSON Schema |
| `tools/measure_text.py` | Regenerates the text width table from installed fonts (needs Chrome) |
