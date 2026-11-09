# Diagram format (v1)

A diagram is one YAML file. It says what exists (groups, nodes, edges) and, optionally, what happens (a scenario).
Colours, fonts and sizes live in the theme, not here.

```yaml
diagr: 1
diagram: order-flow          # id, used for output file names
title: Order processing
description: One sentence, used as the accessible label.
theme: default               # built-in name or a path to a theme file
icons: [./icons]             # extra icon folders, searched before the core set
grid: {col: 200, row: 170}   # cell size in px
step_list: true              # numbered badges and the step list in static output
```

## Groups

```yaml
groups:
  back: {title: Backend, sub: one region, icon: cloud, tone: teal}
  bi:   {title: Reporting, tone: neutral, at: [5, 0], span: [1, 3]}
```

A group is a tinted box with its title at the bottom left. Without `at` it fits around its member nodes. With `at`
(top-left cell) and `span` (cells wide and tall) it covers a fixed area, which is how you make several groups the
same height. Tones come from the theme: `neutral`, `blue`, `teal`, `green`, `violet`, `amber`, `orange`.

## Nodes

```yaml
nodes:
  api:    {in: back, at: [1, 0], icon: function, title: API, sub: validates}
  worker: {in: back, at: [3, 0], icon: server, title: Workers, sub: [three replicas, autoscaled], stack: 3}
  nb:     {at: [2, 0], icon: notebook, title: Notebook, cells: [ingest, clean, join]}
  bus:    {at: [2.5, 1], junction: true}
```

| Key | Meaning |
|---|---|
| `at` | Grid cell `[col, row]`, required. Fractions are allowed (`[2.5, 1]`). |
| `title`, `sub` | Text under the icon. `sub` is a string or a list of lines. |
| `icon`, `tone` | Icon name; `tone` recolours a generated tile (`blue`, `teal`, `green`, `violet`, `amber`, `orange`, `slate`, `red`). |
| `in` | Group id. |
| `junction` | A dot where edges meet, for a bus or fan-out. No icon or text. |
| `trigger` | A button under the node that plays the scenario, e.g. `trigger: Run`. |
| `cells` | A strip of progress squares. A list of names (each shows as the caption while active) or a count. |
| `stack` | Draw the icon as a stack of N, for "N workers". |
| `mark` | `new`, `removed` or `changed`, for as-is versus to-be diagrams. |
| `hidden` | Start hidden; the scenario can `show` it. Hidden elements are left out of static SVGs. |
| `tooltip` | Hover text. |

## Edges

The key is the edge. The value is the label, or a mapping.

```yaml
edges:
  web -> api: POST /orders
  queue -> dlq: {label: after 3 tries, dashed: true}
  pipe -> refresh: {label: last step, route: [down, right]}
  bus -> transcode: {label: start task, route: [up 1.5, right, down]}
  jobs@bottom+15 -> dlq: {label: three failures, route: [down, right]}
  dlq -> jobs@bottom-15 as redrive: {route: [right 0.45, down 0.45, left, up], dashed: true}
```

- **Default path.** Nodes on the same row or column get a straight edge. Otherwise the edge goes sideways, then up or
  down.
- **`route`** is a list of moves from the start node: `up`, `down`, `left`, `right`, each with an optional length in
  cells (`right 0.5`) or px (`up 40px`). Moves without a length on the same axis share what is left, so
  `[down, right]` is an L and `[right, down, right]` is a Z with the bend halfway. The first move picks the side the
  edge leaves from, the last move the side it enters.
- **Ports.** `node@side` forces a side (`left`, `right`, `top`, `bottom`), and `+15` or `-15` shifts the point along
  that side in px. Use it when two edges share a side.
- **`via`** lists explicit waypoints in grid cells, as an escape hatch.
- **`as name`** gives the edge an id. The default id is `a->b`; a second edge between the same pair needs a name.
- Other keys: `dashed`, `mark`, `label_at` (0 to 1 along the path; the default is the middle of the longest
  horizontal run), `hidden`, `tooltip`.

## Scenario

```yaml
scenario:
  ready: Press Place order to follow one order.
  end: Order stored.
  steps:
    - title: Validate and queue
      at: api                      # the node that gets the step's number badge
      status: Validating           # status line while the step plays; default: the title
      text: The API checks the order and puts it on the queue.
      do:
        - activate api 400ms
        - "set api.sub: order is valid"
        - draw api->queue
        - done api
```

A scenario compiles to a list of frames. Each frame only assigns values (node `api` is active, edge `api->queue` is
drawn, a text is replaced), and the state at frame k is all assignments up to k. That is what makes step back,
scrub and replay exact: the player jumps to any frame and the page shows the same thing it shows when playing up to
it.

### Effects

An effect is `verb targets [duration]`. The duration is how long the frame holds before the next one.

| Effect | Meaning | Default |
|---|---|---|
| `activate a [b ...]` | Node starts working: pulsing ring, spinner badge | 0 ms |
| `done a [b ...]` | Node finished: check badge | 0 ms |
| `fail a` | Node failed: red ring and cross. An active cell fails too | 0 ms |
| `draw a->b` | The accent line draws along the edge, then its arrow turns accent | 700 ms |
| `set n.title: text`, `set n.sub: text`, `set n.sub.1: text`, `set a->b.label: text` | Replace text. `n.sub` replaces every line | 0 ms |
| `cells n [1..4] [ms]` | Fill the cells one by one; a range stops early and leaves the last cell active | 520 ms per cell |
| `spin n`, `spin n off` | Rotate the node's glyph | 0 ms |
| `show x`, `hide x` | Reveal or hide a node, edge or group | 0 ms |
| `focus x y`, `focus none` | Dim everything except the targets | 0 ms |
| `wait 400ms` | Pause | |
| `status: text` | Replace the status line | 0 ms |
| `parallel: [...]` | Effects that play in one frame (not `cells`, `repeat` or `parallel`) | longest |
| `repeat: 3` with `do: [...]` | Unrolled at build time; `{i}` in text becomes the round number | |

Effects that take free text use a colon: `set api.sub 400ms: order is valid`. In YAML, quote the whole item when the
text itself contains `: ` (`"set nb.sub: stages 1 to 9: passed"`).

Durations are `ms` or `s`. Generated tiles marked `spins` (the core `refresh` icon) rotate while their node is
active.

## Validation

`diagr check` reports problems as `file:line:col: error: message`: unknown keys (with a suggestion), duplicate
keys and ids, unknown nodes, groups, icons and tones, edges to nowhere, edges from a node to itself without a
`route` or `via`, routes that cannot reach their target, diagonal segments, two nodes on one cell, nodes outside their
group, effects that reference nothing, a format version newer than this diagr, and broken theme or `icons.yml` files.
Overlapping nodes, labels over nodes, overlapping groups, hidden nodes or edges that no `show` reveals, and visible
edges into hidden nodes are warnings; `--strict` makes them fail.

## Python

```python
import diagr

d = diagr.Diagram.from_yaml("diagram.yml")
d.nodes["nb"].cells = ["ingest", "clean", "join"]   # e.g. stage names read from another file
p = diagr.prepare(d)
```

`prepare` validates, lays out and compiles; `diagr.render.svg.render_static(p.scene(), p.theme, "dark")` and
`diagr.render.html.render_html(p)` return the outputs as strings.
