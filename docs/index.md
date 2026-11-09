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

See the [examples](examples/index.md) for rendered diagrams with their source, and the
[format reference](format.md) for everything a diagram file can say.

## CLI

| Command | What it does |
|---|---|
| `diagr build FILE... [-o DIR] [--theme T]` | Write the two SVGs and the HTML page for each file |
| `diagr watch FILE... [-o DIR]` | Rebuild when the file, its icon folders or its theme file change |
| `diagr check FILE... [--strict]` | Validate; errors and warnings are printed as `file:line:col` |
| `diagr schema [-o FILE]` | Print the JSON Schema (`schema/diagr.schema.json`) |

## Player keys

Space plays or pauses. Left and Right go to the previous or next step; with Shift they move one frame. Home resets,
End jumps to the end. Clicking a step in the list jumps to it.
