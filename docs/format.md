# Diagram format

A diagram is one YAML file. It says what exists (groups, nodes, edges) and, optionally, what happens (a scenario).
Colours, fonts and sizes live in the theme, not here. To try any of it without installing diagr, paste it into the
[playground](playground.md).

```yaml
version: 1                   # format version; see Versions
title: Order processing
description: One sentence, used as the accessible label.
theme: default               # built-in name or a path to a theme file
icons: [./icons]             # extra icon folders, searched before the core set
grid: {col: 200, row: 170}   # cell size in px
direction: right             # automatic layout flows right (default) or down
align: true                  # line up the edges of neighbouring boxes that nearly line up (default)
step_list: true              # numbered badges and the step list in static output
```

The files a diagram builds are named after it: `order-flow.yml` writes `order-flow.html`, `order-flow-light.svg`
and `order-flow-dark.svg`. A file called `diagram.yml` is named after its folder instead, so
`order-flow/diagram.yml` writes the same files.

Every id (of a group, a node, a component, an instance, a scenario or a view) is letters, digits, `_` and `-`,
starting with a letter or `_` and not ending in `-`, which would run into an arrow: `a-->b` could be `a-` to `b` or a
dashed edge.

## Groups

```yaml
groups:
  back: {title: Backend, sub: one region, icon: cloud, tone: teal}
  bi:   {title: Reporting, tone: neutral, at: [5, 0], span: [1, 3]}
  lake: {title: Landing zone, title_at: top, tone: violet}
  etl:  {title: Data processing, sub: "ETL: raw to clean", title_at: middle, tone: blue}
```

A group is a tinted box with its title at the bottom left; `title_at` moves it: `top` or `bottom` centres it along
that edge, `top-left` puts it in the top corner, and `middle` makes it a heading, larger and bolder, centred top to
bottom just right of the box's own nodes, with `sub` on the line below as a description (a card with an icon on the
left and its name beside it). A box that fits its contents leaves room for the title on the side it is on. Without
`at` it fits around its member nodes. With `at` (top-left cell) and `span` (cells wide and tall) it covers a fixed
area, which is how you make several groups the same height. Placed automatically, `layer: first` or `last` puts a
group before or after everything else in its parent. Tones come from the theme: `neutral`, `blue`, `teal`, `violet`,
`amber`, `green`, `orange`.

**Tones without `tone`.** A group that leaves out `tone` gets one. A group that holds other groups is `neutral`, a
frame around them; the others take the theme's tones in turn, in the order the file has them, never their parent's.
A component's group takes one tone in all its instances. Set `tone` when the colour means something, such as orange,
neutral and amber for bronze, silver and gold.

**Alignment.** Neighbouring boxes with the same parent that nearly line up are lined up: boxes one above the other
share their left and right edges when those are within a grid column of each other, boxes side by side share their
top and bottom edges within a row. Boxes only grow, so what they hold stays inside, and a side moves only when the
grown box covers no node or box it did not cover already. A box with `at` keeps its cells. A diagram placed
automatically with nothing pinned is not lined up: the placer sizes its boxes itself. Child boxes that sat flush with a side that moves move with
it, so they keep filling their parent. What a grown box holds keeps its place relative to the box: its pinned nodes
and the child boxes that did not grow with it move by the shift of its middle, so a centred node stays centred. That
move is skipped on an axis where it would bend an edge running straight along it to a node outside the box, or an
edge with its own `route` or `via`; nodes placed automatically stay where they were placed. It happens level by
level, inner boxes first, so a parent fits around children already lined up. A group with [boxes stacked
behind](#stacked-boxes) it lines up by the outline of the whole stack, so the stack never sticks out past its
neighbours. A box much narrower than its neighbour is left as it is: give it `at` and `span` to make it as wide.
`align: false` on the diagram turns it off.

### What a group holds

```yaml
groups:
  back:
    title: Backend
    tone: teal
    nodes:
      api:   {at: [1, 0], icon: function, title: API}
      queue: {at: [2, 0], icon: queue, title: Order queue}
    groups:
      data:
        title: Data
        tone: amber
        nodes:
          db: {at: [3, 0], icon: database, title: Orders}
```

A group holds its own `nodes` and `groups`, to any depth, so the file has the shape of the picture. Writing a node or
group inside a box is the only way to put it there. Ids stay global: edges and scenarios name `db`, not `back/data/db`.

### Nested groups

A fitted parent surrounds its own nodes and its child groups, with room for its title below them. A child with `at` keeps its fixed area and must lie inside its
parent. Each level adds a margin around the one inside it, so deeply nested groups reach a little past their columns:
leave a fractional column (`at: [2.2, 0]`) between them and their neighbours. `show`, `hide` and `focus` on a group
affect only its box.

### Stacked boxes

```yaml
groups:
  compute: {title: prod workspace, behind: {compute-dev: dev workspace}, tone: neutral}
edges:
  deploy-dev -> compute-dev: dev workspace
  deploy-prod -> compute: prod workspace
```

`behind` stacks boxes behind a group, for the same thing in several places (a dev and a prod workspace, say), nearest
first. Each is a copy of the group's box, 24px further left and 28px further up for each step back, with its own id
and its title in the strip along its top that the box in front leaves showing. Every title in a stack, the front
box's included, sits at the top left in the same style (centred along the top with `title_at: top`), and a stack that
fits its contents leaves room above them for it. The nodes and child groups stay on the front box, and a parent fits
around the whole stack.

An edge can end at a box behind like at any box. If its path meets a box in front first, it stops there without a
tip, as if it went on underneath; one that reaches the box on a side that shows (its top or left strip) ends on it
with a tip. An edge from a box behind starts where it comes out from behind. The boxes behind follow the group's
`show`, `hide` and `focus`.

## Nodes

```yaml
nodes:
  api:    {at: [1, 0], icon: function, title: API, sub: validates}
  worker: {at: [3, 0], icon: server, title: Workers, sub: [three replicas, autoscaled], stack: 3}
  nb:     {at: [2, 0], icon: notebook, title: Notebook, cells: [ingest, clean, join]}
  bus:    {at: [2.5, 1], junction: true}
```

Nodes go under `nodes` at the top level, or in the `nodes` of the group they are in. A node can also be just its
title (`api: API`) or nothing at all (`web:`), and a node that no `nodes` declares but an edge names is a plain node
at the top level:

```yaml
edges:
  web -> api -> db: [POST /orders, write]
```

is a whole diagram of three nodes. An edge end that is not declared but is close to an id that is (`wrker` next to
`worker`) is a warning, since it is more likely a typo than a new node. An instance's ids (`a/db`) are never made up
this way.

| Key | Meaning |
|---|---|
| `at` | Grid cell `[col, row]`. Fractions are allowed (`[2.5, 1]`). Leave it out to have the node placed for you, see [Automatic layout](#automatic-layout). |
| `title`, `sub` | Text under the icon; `title` defaults to the node's id, and `title: ""` leaves it out. `sub` is a string or a list of lines. |
| `icon`, `tone` | Icon name; `tone` recolours a generated tile (`blue`, `teal`, `green`, `violet`, `amber`, `orange`, `slate`, `red`). |
| `junction` | A dot where edges meet, for a bus or fan-out. No icon or text. |
| `cells` | A strip of progress squares. A list of names (each shows as the caption while active) or a count. |
| `stack` | Draw the icon as a stack of N, for "N workers". |
| `mark` | `new`, `removed` or `changed`, for as-is versus to-be diagrams. |
| `hidden` | Start hidden; a scenario brings it out by showing, drawing or activating it. Hidden elements are left out of static SVGs. |
| `tooltip` | Hover text. |
| `align_x`, `align_y` | Another node's id: line this node up with it, one above the other (`align_x`, same x) or side by side (`align_y`, same y), wherever each sits. See [Row and column layout](#row-and-column-layout). |
| `layer` | `first` or `last`: placed automatically, the node goes before or after everything else in its group. See [Automatic layout](#automatic-layout). |

## Edges

The key is the edge. The value is the label, a mapping, or nothing.

```yaml
edges:
  web -> api: POST /orders
  queue --> dlq: after 3 tries
  bus -> monitor:
  pipe -> refresh: {label: last step, route: [down, right]}
  dispatcher -> jobs: {label: send, route: [right 70px, up, right]}
  jobs@bottom+15 -> dlq: {label: three failures, route: [down, right]}
  dlq --> jobs@bottom-15 as redrive: {route: [right 0.45, down 0.45, left, up]}
```

One key can make several edges:

```yaml
edges:
  web -> api -> queue -> db: [POST /orders, enqueue, write]   # a chain: one edge per arrow
  (mobile web) -> gateway: HTTPS                              # one from each
  bus -> (stock search notify):                               # one to each
  warehouse <-> dashboards: [data, {label: query, dashed: true}]
```

- **Chains and fans.** `a -> b -> c` is `a -> b` and `b -> c`. Ids in parentheses, separated by spaces, are side by
  side: `(a b) -> c` is an edge from each, `a -> (b c)` one to each, and ports work inside (`(a@top b) -> c`). A
  label or mapping applies to every edge the key makes; a list gives one each, in order (arrow by arrow, and within
  an arrow from each source in turn), and must have as many items as there are edges. `null` in the list is an edge
  with nothing on it.
- **`-->`** is a dashed edge, the same as `dashed: true`.
- **`<->`** is a pair: `a -> b` and `b -> a`, running side by side 10px either side of the middle of the sides they
  use, so they do not draw over each other. A list gives the first value to `a -> b` and the second to `b -> a`.

- **Default path.** Nodes on the same row or column get a straight edge. Otherwise the edge goes sideways, then up or
  down.
- **`route`** is a list of moves from the start node: `up`, `down`, `left`, `right`, each with an optional length in
  cells (`right 0.5`) or px (`up 40px`). Moves without a length on the same axis share what is left, so
  `[down, right]` is an L and `[right, down, right]` is a Z with the bend halfway. The first move picks the side the
  edge leaves from, the last move the side it enters.
- **Ports.** `node@side` forces a side (`left`, `right`, `top`, `bottom`), and `+15` or `-15` shifts the point along
  that side in px. Use it when two edges share a side.
- **`via`** lists explicit waypoints in grid cells, as an escape hatch.
- **Boxes as ends.** Either end can be a group id instead of a node, or a [box stacked behind](#stacked-boxes) one:
  `deploy -> workspace: dev`, `api -> data`. When the two ends line up, the edge goes straight across: at the node's
  own x or y, at the named port, or in the middle of where two boxes overlap. Otherwise it goes to a side the usual
  way, and `group@side+40` picks the side and the point (offsets are from the side's middle). A `flow` path can pass
  through a box, which has no active or done state of its own; `draw` works as for any edge. An edge between a node
  and a group it is in is an error.
- **`as name`** gives the edge an id, for a key that makes one edge. The default id is `a->b`; a second edge between
  the same pair needs a name.
- Other keys: `dashed`, `mark`, `label_at` (0 to 1 along the path; by default the label goes where it covers nothing,
  see [Automatic layout](#automatic-layout)), `hidden`, `tooltip`, and `constraint: false` to leave the edge out when
  placing nodes.

## Automatic layout

Nodes without `at` are placed for you, so most diagrams need no coordinates at all:

```yaml
groups:
  back:
    title: Backend
    tone: teal
    nodes:
      api:   {icon: api, title: API}
      users: {icon: database, title: Users}
nodes:
  web:   {icon: browser, title: Web app}
  mail:  {icon: mail, title: Welcome email}
edges:
  web -> api: sign up
  api -> users: insert
  api -> mail: send
```

When no node or group has `at`, diagr lays the diagram out in layers, the way Graphviz does. The layers are the
whole diagram's, like columns, so nodes in boxes side by side line up. Across the flow it goes one box at a time from
the inside out: each group's contents first, then the group as one block inside its parent, over the layers it spans.
So boxes never overlap, and a box is only as big as what it holds.

- **Layers.** Edges point along the flow (`direction`: `right`, the default, or `down`), each at least one layer
  long, and as short as they can all be together. A box (or node) that an edge goes into starts after the box (or
  node) it comes from, among what one box holds, so the two sit side by side. An edge that would close a loop is
  drawn back against the flow.
- **Order.** Within each layer, nodes and boxes are sorted by where their neighbours sit, sweeping forward and back
  and keeping the order with the fewest crossings; a box keeps one place in every layer it spans. An edge that skips
  layers keeps a lane open in each layer it passes, so it never runs through a node, and an edge that leaves a box
  has a lane to the box's edge.
- **Straight lines.** Each node and box then moves across the flow to where its edges run straight, keeping its order
  and its distance from its neighbours. A chain comes out as a straight line, a node fanning out to several sits in
  the middle of them, and a node with one edge in and several out stays in line with the one coming in.
- **Spacing.** Each layer is as thick as its biggest node. The gap after it, between the boxes that end in it and
  those that start in the next, is wide enough for the labels of the edges crossing it and for the edges that turn
  there; `grid` scales the gaps and the padding inside boxes.
- **Dashed edges** are side links (replication, a dead-letter queue, a wake-up call). One sets the layer of the node it
  leads into only when no solid edge does, and `a/db --> b/db` leaves the replica where its own writes put it. A node
  hanging off another by its only edge, dashed or hidden, such as `queue --> dlq` or something a scenario reveals,
  goes right beside it in the same layer, with the edge running straight across; so does a node whose only edges are
  dashed ones out of it, such as a scheduler or a health check.
- **Hidden edges** pull a quarter as hard as the others, so what only a scenario shows does not bend the picture as it
  first appears.
- **A node that no edge places**, joined only by dashed edges out of it, goes in the layer of what it is joined to: a
  governance box of separate services spreads along under the platform they serve, each service by what it serves.
- **Edges** follow their lanes and turn only in the gaps between layers. Edges that turn in one gap turn side by
  side; those from one node leave it as one trunk, a dashed one beside a solid one. Edges that meet a node on one
  side meet it side by side, in the order they come from, and an edge that runs straight on keeps the middle.
- **Labels** go on their edge where they cover nothing: they move along the path off nodes, other labels, group
  titles and other edges' lines. `label_at` on an edge puts its label where you say.

Three keys steer the layout without coordinates:

| Key | On | Meaning |
|---|---|---|
| `layer: first`, `layer: last` | node, group | Before or after everything else in the box it is in (the diagram, for a top-level node or group): an actor or a side system at one end of the picture. Edges into a `first` item or out of a `last` one are drawn back against the flow. |
| `constraint: false` | edge | Drawn, but left out when placing: for a long edge back to the start, or a side link that should not pull its ends together. |
| `align_x`, `align_y` | node | Line the node up with another one, see [Row and column layout](#row-and-column-layout). |

The [examples](examples/index.md) are all laid out this way: the only layout key in them is `layer: last` on the two
users of the [data platform](examples/data-platform.md).

- **Pinning.** A node with `at` keeps its cell. When some nodes are pinned, the rest are placed around them by a
  simpler placer: in layers, with every group in its own band and placed nodes moving aside rather than landing on a
  pinned one. A group with a fixed area (`at` and `span`) needs its nodes pinned. `layer` only applies when nothing
  is pinned, and `diagr check` says so.
- **Pinning everything.** `diagr expand FILE` writes every computed position as `at` and every computed path as a
  `route`, so the output draws the same picture with nothing left to place. Start from it to fine-tune by hand.
  Its [views](#views) become crops of the pinned diagram.
- `diagr build --html --debug` labels each placed node with the cell it got (`[2, 1] auto`).

## Row and column layout

Instead of cells, a box can arrange what it holds the way CSS flexbox does: one after another, in the order they
appear in the file, each as big as its contents.

```yaml
layout: {direction: row, gap: 24, align: stretch}    # the diagram itself: main column, then dashboarding
groups:
  main:
    title: main
    box: false
    layout: {direction: column, align: stretch}
    groups:
      compute:
        title: Compute
        layout: {direction: column, gap: 24, align: stretch}
        groups:
          pipeline:
            title: Orchestration
            title_at: middle
            layout: row
            nodes:
              orchestrator: {icon: pipeline, title: Data Pipeline}    # no at
      ci: {title: Development & CI/CD, layout: {direction: row, justify: space-between}}
```

- **`layout`** is `row` or `column`, or a mapping: `direction`, `gap` (px between items, default 24), `align`
  across the direction (`start`, `center` (the default), `end`, or `stretch` to make child boxes as wide in a column,
  or as tall in a row, as the box) and `justify` along it, for space left over (`start` (the default), `center`,
  `end`, `space-between` or `space-around`).
- **`grow`** on a group inside such a box gives it a share of the space left over along the direction, like
  `flex-grow`: `grow: 1` on one child makes it fill the rest, and on two splits it evenly. Growing comes before
  `justify`.
- It works on a group, or on the whole diagram at the top level. Everything inside a box with `layout` is laid out
  too: a child group without `layout` is a column. A node or group inside one cannot have `at` or `span`; the
  outermost box with `layout` can take `at` for where it starts.
- **`box: false`** makes a group that only arranges what it holds and draws nothing, like a plain `div`, for rows
  and columns that need no frame.
- In a row, nodes line up by their icons, whatever the length of their labels, so edges between them stay straight.
  Centring places what shows, the icon and its labels, in the middle; a row whose nodes are clear of a bottom title
  centres on the whole box rather than above the title's band.
- **`align_x` and `align_y`** on a node line it up with a node in another box, which a row or column alone cannot
  do: `align_x: deploy-dev` puts a key straight under the step it feeds, so the edge between them is straight. Only
  that axis moves, the node stays inside its box (its padding included), and `diagr check` reports an unknown node,
  a node naming itself, or a loop.
- A box is as big as its contents plus 20px inside, more on the side its title is on; a `title_at: middle` heading
  takes its place after the box's nodes. Edges are routed afterwards as usual: an edge between two boxes that line
  up goes straight across where it misses their titles, or jogs through the gap between them when titles cover the
  whole overlap.

## Components

A component is a block of groups, nodes and edges defined once; `instances` puts named instances of it in the diagram.

```yaml
components:
  region:
    params: {name: {required: true}, role: primary}      # a value is the default
    groups:
      region:
        title: $name
        sub: $role
        tone: neutral
        nodes:
          db: {at: [1, 0], icon: database, title: Orders, sub: $role}
        groups:
          cluster:
            title: Cluster
            tone: blue
            nodes:
              api: {at: [0, 0], icon: api, title: Checkout API}
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
  `b/db.sub: primary`, `draw a/api->a/db`), `step.at` and `trigger.at`. Edge ids follow: `a/api->a/db`, or
  `a/<name>` for an edge declared with `as <name>`.
- **Positions.** A component's cells are relative; the instance's `at` moves all of them, fixed group areas and `via`
  points included. A component whose nodes have no `at` is placed automatically, like any other node.
- **Parameters.** `$param` in titles, sub text, labels, tooltips and the text of its [actions](#actions) is replaced by
  the instance's `with` value or the default from `params`; `{required: true}` instead of a default makes every instance
  set it. It needs no quotes (`title: $name`, `sub: schema v$version`). Write `$$` for a literal `$` before a letter;
  `$5` needs nothing. Parameters are text only: ids, positions and numbers cannot be parameters.
- **`in`** on an instance puts its outermost groups and nodes inside an existing group. It is the one place `in` is
  written: an instance has nowhere to be nested.
- A component's nodes and edges can only use its own groups and nodes. A problem in a component's definition (an
  unknown `$param`, an edge to a node it does not have) is reported once; a problem that depends on the instance, like
  an overlap, names the instance's ids (`a/api`).
- Components cannot contain other components, and scenarios stay at the top level; a component's
  [actions](#actions) say what it does in them.
- `diagr expand FILE` prints the file with every instance written out as plain groups, nodes and edges, to check what
  a component turned into, and every call of a component's action written out as the effects it plays. Its ids keep
  the `instance/id` form, which the format accepts.

## Scenarios

```yaml
scenario:
  trigger: {at: web, label: Place order}   # a button under a node that plays the scenario
  ready: Press Place order to follow one order.
  end: Order stored.
  steps:
    - Validate and queue:
        at: api                      # the node that gets the step's number badge
        status: Validating           # status line while the step plays; default: the title
        text: The API checks the order and puts it on the queue.
        do:
          - activate api 400ms
          - api.sub: order is valid
          - flow api -> queue
    - Store:
        at: db
        focus: [queue, worker, db]   # dim the rest while the step plays
        do: [flow queue -> worker 1200ms -> db 600ms done]
    - Confirm: [run mail 800ms]    # a step with nothing to say but its title
```

- **`trigger`** puts a button under the node `at`, with `label` on it, that plays the scenario. A node carries one
  trigger at most.
- **`focus`** on a step dims everything but the nodes, edges and groups it lists, and the edges between the nodes it
  lists, while the step plays, and clears when the step ends.
- **Steps.** A step's title is its key, so the titles read down the left like a table of contents. Under it go the
  step's effects (`Title: [effects]`), or a mapping of its other keys: `at`, `text`, `status`, `focus` and `do`. A
  title with `: ` in it needs quotes, like any YAML key.

A scenario compiles to a list of frames. Each frame only assigns values (node `api` is active, edge `api->queue` is
drawn, a text is replaced), and the state at frame k is all assignments up to k. That is what makes step back,
scrub and replay exact: the player jumps to any frame and the page shows the same thing it shows when playing up to
it.

`scenario` is a diagram's one scenario. For several, `scenarios` maps ids to scenarios instead, and `title` on each
names it in the player's picker; a file has one key or the other. With more than one, the HTML page gets a picker;
switching resets the diagram and shows that scenario's steps and badges. Each scenario's `trigger` plays it:

```yaml
scenarios:
  checkout: {title: Checkout, trigger: {at: user, label: Place order}, steps: [...]}
  failover: {title: Failover, trigger: {at: health, label: Fail region A}, steps: [...]}
```

The scenario under `scenario` has the id `main`, for the [views](#views) and scripts that name it.

A static SVG can only show one scenario, so it shows the first one's badges and step list. From a script,
`diagr.scenario("failover")` switches and `diagr.scenarios` lists the ids.

`loop: true` on a scenario makes it replay forever: it holds its last frame for two seconds, then starts again. The
first looping scenario starts on its own when the page loads, which suits a diagram on a screen nobody touches. Any
input from the viewer (pause, a step, the scrubber, the picker or a trigger) stops the loop, and Play starts it again.
A loop does not start on its own for viewers who ask for reduced motion, and it waits while the diagram is scrolled
out of view or the tab is in the background.

### Effects

An effect is `verb targets [duration]`. The duration is how long the frame holds before the next one.

Targets are written the way edge keys are. A node, group or named edge is its id, `(a b)` is several side by side,
and arrows between them name the edges along the way: `draw a -> b -> c` draws `a->b` and `b->c`,
`draw (orders clicks stock) -> bus` draws one edge from each, and `draw a <-> b` both edges of a pair. `-->` names
the same edge as `->`, and spaces around arrows are optional (`draw a->b`). Targets with no arrow between them are
separate: `done a b` and `draw a->b c->d`.

| Effect | Meaning | Default |
|---|---|---|
| `activate a [b ...]` | Node starts working: pulsing ring, spinner badge | 0 ms |
| `done a [b ...]` | Node finished: check badge | 0 ms |
| `fail a [b ...]` | Node failed: red ring and cross. An active cell fails too | 0 ms |
| `run a [b ...] [ms]` | Node works for a while, then finishes: `activate a ms`, then `done a` | 0 ms |
| `draw a -> b [c -> d ...]` | The accent line draws along the edge, then its arrow turns accent | 1400 ms |
| `flow a -> b -> c` | Follow a path, see [below](#flow) | |
| `cells n [2..4] [ms]` | Fill the cells one by one. A range by position (`2..4`, or `3` for one cell) or by name (`build..test`, `canary`) fills only those; a range that stops early leaves its last cell active, and the next range completes it | 1040 ms per cell |
| `spin n`, `spin n off` | Rotate the node's glyph | 0 ms |
| `show x`, `hide x` | Reveal or hide a node, edge or group | 0 ms |
| `focus x y`, `focus none` | Dim everything except the targets and the edges between them; a step's own `focus` does this for the step | 0 ms |
| `wait 400ms` | Pause | |
| `n.sub: text` | Replace text: `n.title`, `n.sub` (every line), `n.sub.1` (one line), `a -> b.label` | 0 ms |
| `status: text` | Replace the status line | 0 ms |
| `parallel: [...]` | Effects that play together, in lockstep: each frame plays the next frame of every effect and lasts as long as the slowest, so flows advance one hop at a time, cells fill side by side, a `repeat` runs its rounds alongside and a nested `parallel` plays its own lockstep as one lane | longest |
| `repeat 3: [...]` | Unrolled at build time; `$i` in text becomes the round number | |
| `[...]` | A list inside a list plays one effect after another, as one lane of a `parallel` | |

Drawing or activating something hidden brings it out, along with the ends of an edge it draws, so a node or edge that
starts `hidden` needs no `show` before the effect that uses it. `show` is for bringing one out without animating it.

**Text.** A text change is a mapping from what changes to the new text, with an optional duration before the colon:
`api.sub 400ms: order is valid`. Several in one mapping change together, in one frame:

```yaml
do:
  - a/worker.sub: v2
    b/worker.sub: v2
  - status: Both regions run v2.
```

YAML needs quotes around text that contains `: ` or, inside `[...]`, a comma or braces: `b/db.sub: "replica, in
sync"`. Quoting the whole item works too (`"nb.sub: stages 1 to 9: passed"`).

Durations are `ms` or `s`. Generated tiles marked `spins` (the core `refresh` icon) rotate while their node is
active.

### Flow

`flow` follows a path the way a request travels it:

```yaml
- flow web -> api                          # activate web, draw web->api, done web
- flow queue -> worker 1200ms -> db 600ms done
- flow bus -> (stock search notify) done
```

- Each stop is activated, the edge to the next stop is drawn, and the stop is done. A stop that is already active,
  with no duration, is not activated again.
- **A duration after a stop** is how long it stays active: `worker 1200ms` works for 1.2 s before the edge on to
  `db` draws.
- **The last stop** is left as it is, so the next step can pick it up. With a duration it is activated for that long
  and left active; `done` at the end finishes it.
- **Stops side by side**, in parentheses, play together: `a -> (b c)` draws both edges at once, and `(b c) -> d`
  activates `b` and `c` together before drawing both edges into `d`.
- A box on the path is passed through: it has no active or done state of its own; `draw` works as for any edge.

### Actions

An action is a list of effects with a name, called in `do` by that name:

```yaml
actions:
  refresh: [draw warehouse->dashboards, dashboards.sub: refreshed, done dashboards]

scenarios:
  nightly:
    steps:
      - Publish: [flow marts -> warehouse, refresh]
```

A component's actions use its own ids and are called with the instances they run on. Several instances play side
by side, in lockstep, as in a `parallel`:

```yaml
components:
  feed:
    # groups, nodes and edges with src, ingest and check
    actions:
      pull: [flow src -> ingest]
      validate: [flow ingest -> check 800ms done]

scenarios:
  nightly:
    steps:
      - Pull the feeds: [pull orders clicks stock]
      - Validate: [validate orders clicks stock]
```

Inside a component's action, another action of the same component is called by its name alone and runs on the same
instance, and `$param` in text is the instance's value. An action cannot call itself, and it cannot have the name of
an effect.

## Views

A view is a part of the diagram built as its own images and page, for the slide or the doc section that only needs
that part. The whole diagram is still built too.

```yaml
views:
  ingestion: {title: Ingestion, include: [ingestion, bus], exclude: [quarantine]}
  serving:   {include: [serving, analyst, access], scenarios: [query]}
```

- **Files.** Each view is written next to the diagram's files as `<name>-<view>-light.svg`,
  `<name>-<view>-dark.svg` and `<name>-<view>.html`, where `<name>` is what the diagram's own files are named.
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
- `diagr expand` pins every position, so in the expanded file a view of automatically placed nodes is a crop of the
  whole rather than laid out again.

The [data platform example](examples/data-platform.md#views) has two views and the
[event-driven example](examples/event-driven.md#views) one, each laid out again.

### Dynamic views

A dynamic view shows one scenario as a numbered story, like a dynamic view in the C4 model: only the parts the
scenario uses, with each edge numbered by the step that draws it.

```yaml
views:
  checkout-flow: {title: Checkout request, scenario: checkout}
```

- **What it shows.** `scenario` picks the nodes and edges the scenario uses: those it flows along, draws, activates,
  shows, focuses or changes the text of, and each step's `at` node, with the groups around them. Edges the scenario
  never touches are left out, even between nodes it shows.
- **`include`** adds context the story does not touch, such as a node and the edges between it and the other included
  nodes. `exclude` takes nodes out as usual.
- **Numbers.** Each edge the scenario flows along or draws gets a badge with the number of the step that does it, the
  same number as in the step list and on the node badges. Edges used in one step share its number, whether in one
  flow or in parallel; an edge used again later shows both numbers (`1,3`). With `step_list: false` there are no
  badges.
- The badge sits beside the edge's label when the run has room, otherwise on the label's line or just before the
  arrow. `diagr check` warns if it covers another label or a node.
- The view keeps its scenario, first, so its page plays the story; `scenarios` can keep others as well.

The [multi-region example](examples/multi-region.md#views) and the
[event-driven example](examples/event-driven.md#views) each have a dynamic view.

## Formatting

`diagr fmt FILE` lines the file up into columns, and the playground's Format button does the same:

```yaml
nodes:
  api:    {icon: function, title: API,     sub: validates}
  queue:  {icon: queue,    title: Order queue}
  worker: {icon: server,   title: Workers, sub: three replicas, stack: 3}

edges:
  web   -> api:   POST /orders
  api   -> queue: enqueue
  queue --> dlq:  after 3 tries
```

- **One-line mappings** side by side at one indent, such as nodes, start their values in one column, and each item
  in one column while every line with an item after it has the same key there.
- **Edges** under `edges:` start their arrows in one column, and their labels too. One key much longer than the
  others, such as a long chain, keeps its label one space after it rather than pushing every label to the right.
- A blank line or a comment ends a run, so related lines can be grouped. Comments, quoting, blank lines and
  everything else stay as written, and every line stays on its line.
- `--check` changes nothing and fails if a file would change, for CI.

## Versions

`version` says which version of the format a file is written in; a file without it is version 1, the current one.
`diagr init` and `diagr expand` write it.

When a later version changes the format in a way that breaks older files, diagr will keep reading them: it upgrades
each file as it reads it, and warns at each place it rewrote with what the new version writes there, so
`diagr check` lists what to change.

## Validation

`diagr check` reports problems as `file:line:col: error: message`: unknown keys, nodes, groups, edges, icons and
scenarios (each with a "did you mean" suggestion for typos), duplicate keys and ids, unknown tones, edges from a node to itself without a `route` or `via`, routes that cannot reach their target, diagonal segments, two
nodes on one cell, nodes outside their group, groups outside their parent or inside themselves, triggers at an unknown
node or on a node that already has one, effects that reference nothing, actions that call themselves, unknown components
or parameters, and broken theme or `icons.yml` files. Overlapping nodes, labels over nodes or over other labels,
overlapping groups, nodes over a group they are not in, nodes or child groups over a group's title, edges through a node
they do not connect or across a group's title, hidden nodes or edges that nothing shows, draws or activates, visible
edges into hidden nodes, and edge ends that are not declared but look like a typo of an id that is are warnings; `--strict` makes them fail.

## Python

```python
import diagr

d = diagr.load_file("diagram.yml")
d.nodes["nb"].cells = ["ingest", "clean", "join"]  # e.g. stage names read from another file
p = diagr.prepare(d)
```

`prepare` validates, lays out and compiles; `diagr.render.svg.render_static(p.scene(), p.theme, "dark")` and
`diagr.render.html.render_html(p)` return the outputs as strings. `d.scenarios` maps scenario ids to scenarios,
and `p.scenarios` holds each one compiled to frames.
