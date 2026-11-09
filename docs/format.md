# Diagram format (v1)

A diagram is one YAML file. It says what exists (groups, nodes, edges) and, optionally, what happens (a scenario).
Colours, fonts and sizes live in the theme, not here.

```yaml
id: order-flow               # used for output file names
title: Order processing
description: One sentence, used as the accessible label.
theme: default               # built-in name or a path to a theme file
icons: [./icons]             # extra icon folders, searched before the core set
grid: {col: 200, row: 170}   # cell size in px
direction: right             # automatic layout flows right (default) or down
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

### Nested groups

```yaml
groups:
  region:  {title: Region A, tone: neutral}
  cluster: {title: Cluster, in: region, tone: blue}
  web:     {title: Checkout, in: cluster, tone: teal}
```

`in` puts a group inside another, to any depth. A fitted parent surrounds its own nodes and its child groups, with
room for its title below them. A child with `at` keeps its fixed area and must lie inside its parent. Each level adds
a margin around the one inside it, so deeply nested groups reach a little past their columns: leave a fractional
column (`at: [2.2, 0]`) between them and their neighbours. `show`, `hide` and `focus` on a group affect only its box.

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
| `at` | Grid cell `[col, row]`. Fractions are allowed (`[2.5, 1]`). Leave it out to have the node placed for you, see [Automatic layout](#automatic-layout). |
| `title`, `sub` | Text under the icon. `sub` is a string or a list of lines. |
| `icon`, `tone` | Icon name; `tone` recolours a generated tile (`blue`, `teal`, `green`, `violet`, `amber`, `orange`, `slate`, `red`). |
| `in` | Group id. |
| `junction` | A dot where edges meet, for a bus or fan-out. No icon or text. |
| `trigger` | A button under the node that plays a scenario, e.g. `trigger: Run`. |
| `plays` | The scenario id the trigger plays, when there are several; default: the first. |
| `cells` | A strip of progress squares. A list of names (each shows as the caption while active) or a count. |
| `stack` | Draw the icon as a stack of N, for "N workers". |
| `mark` | `new`, `removed` or `changed`, for as-is versus to-be diagrams. |
| `hidden` | Start hidden; a scenario can `show` it. Hidden elements are left out of static SVGs. |
| `tooltip` | Hover text. |

## Edges

The key is the edge. The value is the label, or a mapping.

```yaml
edges:
  web -> api: POST /orders
  queue -> dlq: {label: after 3 tries, dashed: true}
  pipe -> refresh: {label: last step, route: [down, right]}
  dispatcher -> jobs: {label: send, route: [right 70px, up, right]}
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

## Automatic layout

Nodes without `at` are placed for you, so a first draft needs no coordinates at all:

```yaml
id: signup
groups:
  back: {title: Backend, tone: teal}
nodes:
  web:   {icon: browser, title: Web app}
  api:   {in: back, icon: api, title: API}
  users: {in: back, icon: database, title: Users}
  mail:  {icon: mail, title: Welcome email}
edges:
  web -> api: sign up
  api -> users: insert
  api -> mail: send
```

- **Layers.** Edges point along the flow: a node goes one column after the nodes that lead to it (one row, with
  `direction: down`). An edge that would close a loop is drawn back round the outside instead.
- **Groups.** Each group gets its own band across the flow, nested inside its parent's band and spaced so the boxes do
  not overlap. Groups that sit in different columns share rows. Nodes outside any group go as close as they can to the
  nodes they are connected to.
- **Edges** between placed nodes that have no `route` or `via` get a path of their own: along the source's row, then
  across in the gap before the target, with lanes from different sources spread apart.
- **Mixing.** Nodes with `at` keep it, and placed nodes move aside rather than land on them, so you can pin the few
  nodes whose place matters and leave the rest. A group with a fixed area (`at` and `span`) needs its nodes pinned.
- **Pinning everything.** `diagr expand FILE` writes every computed position as `at` and every computed path as a
  `route`, so the output draws the same picture with nothing left to place. Start from it to fine-tune by hand.
- `diagr build --debug` labels each placed node with the cell it got (`[2, 1] auto`).

The placement is simple and predictable rather than clever. For a dense diagram, pinning a handful of nodes usually
does more than any amount of reordering.

## Components

A component is a block of groups, nodes and edges defined once; `instances` puts named instances of it in the diagram.

```yaml
components:
  region:
    params: {name: {required: true}, role: primary}      # a value is the default
    groups:
      region:  {title: "{name}", sub: "{role}", tone: neutral}
      cluster: {title: Cluster, in: region, tone: blue}
    nodes:
      api: {in: cluster, at: [0, 0], icon: api, title: Checkout API}
      db:  {in: region, at: [1, 0], icon: database, title: Orders, sub: "{role}"}
    edges:
      api -> db: write

instances:
  a: {component: region, at: [2, 0], with: {name: Region A}}
  b: {component: region, at: [2, 2], with: {name: Region B, role: standby}, in: cloud}

edges:
  a/db -> b/db: replication
```

- **Names.** Inside a component, ids are local (`api`, `db`). Each instance prefixes them with its own name, so the rest
  of the file refers to `a/api` and `b/db`: in edges (`lb -> a/api@left`), effects (`fail a/api`,
  `set b/db.sub: primary`, `draw a/api->a/db`), `step.at` and `plays`. Edge ids follow: `a/api->a/db`, or
  `a/<name>` for an edge declared with `as <name>`.
- **Positions.** A component's cells are relative; the instance's `at` moves all of them, fixed group areas and `via`
  points included. A component whose nodes have no `at` is placed automatically, like any other node.
- **Parameters.** `{param}` in titles, sub text, labels, tooltips and trigger labels is replaced by the instance's `with`
  value or the default from `params`; `{required: true}` instead of a default makes every instance set it. Write `{{` and
  `}}` for literal braces. Parameters are text only: ids, positions and numbers cannot be parameters.
- **`in`** on an instance puts its outermost groups and nodes inside an existing group.
- A component's nodes and edges can only use its own groups and nodes. A problem in a component's definition (an
  unknown `{param}`, an edge to a node it does not have) is reported once; a problem that depends on the instance, like
  an overlap, names the instance's ids (`a/api`).
- Components cannot contain other components, and scenarios stay at the top level.
- `diagr expand FILE` prints the file with every instance written out as plain groups, nodes and edges, to check what
  a component turned into. Its ids keep the `instance/id` form, which the format accepts.

## Scenarios

```yaml
scenarios:
  order:                             # scenario id
    title: Place an order            # name in the player's scenario picker, when there are several
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

`scenarios` maps ids to scenarios, and a diagram can have any number. With more than one, the HTML page gets a picker;
switching resets the diagram and shows that scenario's steps and badges. A trigger plays the scenario named by its
node's `plays`, or the first one:

```yaml
nodes:
  health: {at: [0, 0], icon: clock, title: Health checks, trigger: Fail region A, plays: failover}
```

A static SVG can only show one scenario, so it shows the first one's badges and step list. From a script,
`diagr.scenario("failover")` switches and `diagr.scenarios` lists the ids.

`loop: true` on a scenario makes it replay forever: it holds its last frame for two seconds, then starts again. The
first looping scenario starts on its own when the page loads, which suits a diagram on a screen nobody touches. Any
input from the viewer (pause, a step, the scrubber, the picker or a trigger) stops the loop, and Play starts it again.
A loop does not start on its own for viewers who ask for reduced motion, and it waits while the diagram is scrolled
out of view or the tab is in the background.

### Effects

An effect is `verb targets [duration]`. The duration is how long the frame holds before the next one.

| Effect | Meaning | Default |
|---|---|---|
| `activate a [b ...]` | Node starts working: pulsing ring, spinner badge | 0 ms |
| `done a [b ...]` | Node finished: check badge | 0 ms |
| `fail a` | Node failed: red ring and cross. An active cell fails too | 0 ms |
| `draw a->b` | The accent line draws along the edge, then its arrow turns accent | 1400 ms |
| `flow a -> b -> c [ms]` | Follow a path: `activate a`, `draw a->b`, `done a`, then the same from `b`. The last node is left as it is, so the next step can pick it up. A duration applies to each `activate` | |
| `set n.title: text`, `set n.sub: text`, `set n.sub.1: text`, `set a->b.label: text` | Replace text. `n.sub` replaces every line | 0 ms |
| `cells n [2..4] [ms]` | Fill the cells one by one. A range by position (`2..4`, or `3` for one cell) or by name (`build..test`, `canary`) fills only those; a range that stops early leaves its last cell active, and the next range completes it | 1040 ms per cell |
| `spin n`, `spin n off` | Rotate the node's glyph | 0 ms |
| `show x`, `hide x` | Reveal or hide a node, edge or group | 0 ms |
| `focus x y`, `focus none` | Dim everything except the targets | 0 ms |
| `wait 400ms` | Pause | |
| `status: text` | Replace the status line | 0 ms |
| `parallel: [...]` | Effects that play together, in lockstep: each frame plays the next frame of every effect and lasts as long as the slowest, so flows advance one hop at a time, cells fill side by side, a `repeat` runs its rounds alongside and a nested `parallel` plays its own lockstep as one lane | longest |
| `repeat: 3` with `do: [...]` | Unrolled at build time; `{i}` in text becomes the round number | |

Effects that take free text use a colon: `set api.sub 400ms: order is valid`. In YAML, quote the whole item when the
text itself contains `: ` (`"set nb.sub: stages 1 to 9: passed"`).

Durations are `ms` or `s`. Generated tiles marked `spins` (the core `refresh` icon) rotate while their node is
active.

## Views

A view is a part of the diagram built as its own images and page, for the slide or the doc section that only needs
that part. The whole diagram is still built too.

```yaml
views:
  ingestion: {title: Ingestion, include: [ingestion, bus], exclude: [quarantine]}
  serving:   {include: [serving, analyst, access], scenarios: [query]}
```

- **Files.** Each view is written next to the diagram's files as `<id>-<view>-light.svg`, `<id>-<view>-dark.svg` and
  `<id>-<view>.html`.
- **`include`** lists group and node ids; a group brings everything inside it, nested groups included. Without
  `include` the view starts from every node. **`exclude`** takes ids out again in the same way.
- An edge is kept when both its ends are, and a group when it holds a kept node, so the parents of what you include
  come along with it.
- **Layout.** Nodes that were [placed automatically](#automatic-layout) are placed again for the view, so it closes
  up. Pinned nodes keep their cells, which makes a view of a hand-placed diagram a crop of it.
- **`scenarios`** lists the scenarios the view keeps; by default it keeps none, and a trigger that would play a dropped
  scenario is left out. A kept scenario must only use what the view shows; if it does not, `diagr check` reports the
  step, prefixed with the view's name.
- `title` replaces the diagram's title on the view's page.

## Validation

`diagr check` reports problems as `file:line:col: error: message`: unknown keys, nodes, groups, edges, icons and
scenarios (each with a "did you mean" suggestion for typos), duplicate keys and ids, unknown tones, edges to
nowhere, edges from a node to itself without a `route` or `via`, routes that cannot reach their target, diagonal
segments, two nodes on one cell, nodes outside their group, groups outside their parent or inside themselves,
triggers that play an unknown scenario, effects that reference nothing, unknown components or parameters, and broken
theme or `icons.yml` files. Overlapping nodes, labels over nodes, overlapping groups, nodes over a group they are
not in, edges through a node they do not connect or across a group's title, hidden nodes or edges that no `show`
reveals, and visible edges into hidden nodes are warnings; `--strict` makes them fail.

## Python

```python
import diagr

d = diagr.Diagram.from_yaml("diagram.yml")
d.nodes["nb"].cells = ["ingest", "clean", "join"]  # e.g. stage names read from another file
p = diagr.prepare(d)
```

`prepare` validates, lays out and compiles; `diagr.render.svg.render_static(p.scene(), p.theme, "dark")` and
`diagr.render.html.render_html(p)` return the outputs as strings. `d.scenarios` maps scenario ids to scenarios,
and `p.scenarios` holds each one compiled to frames.
