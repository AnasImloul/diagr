# How diagr compares

diagr sits between two families of tools: diagram languages that draw a picture from text, and architecture tools
that let you step through how a system behaves. This page sets out where it overlaps with them and where it does not.
It is based on each tool's own documentation, read in November 2026; features change, so check the linked pages
before relying on a detail.

## At a glance

| Tool | Source | Step through a story | Output | Layout |
|---|---|---|---|---|
| **diagr** | YAML in your repository | Scenarios: nodes go active, done or failed, edges draw, text changes, frame by frame | Static SVG for light and dark, and one self-contained HTML page with the player | Manual, on a grid |
| [D2](https://d2lang.com/tour/composition/) | D2 language in your repository | Layers, scenarios and steps: whole diagrams that inherit from each other | SVG, PNG, PDF; an SVG that cycles through the steps | Automatic |
| [Mermaid](https://mermaid.js.org/syntax/flowchart.html) | Mermaid syntax, often inline in Markdown | Not built in; edges can carry a continuous dash animation | Rendered in the page by a JavaScript library | Automatic |
| [Structurizr](https://docs.structurizr.com/ui/diagrams/animation) | Structurizr DSL, one model with many views | Animation steps that reveal elements and relationships; dynamic views for a use case | Its own diagram viewer and exports | Automatic, with manual adjustment |
| [LikeC4](https://likec4-docs-astro.pages.dev/tooling/cli) | LikeC4 DSL, one model with many views | Dynamic views with a walkthrough | A static website built by its CLI | Automatic |
| [Ilograph](https://ilograph.com/docs/editing/perspectives/sequence-perspectives) | YAML (its own diagram language) | Sequence perspectives and walkthroughs with Next and Back | Its web and desktop apps; standalone interactive HTML exported by the desktop CLI | Automatic |
| [IcePanel](https://docs.icepanel.io/features/flows) | A visual modelling app | Flows: step-by-step messages over an existing diagram | Inside the IcePanel app | Manual, on a canvas |

## The tools in more detail

**D2** is the closest open-source relative: a declarative language with a CLI that compiles to SVG. It composes
diagrams out of [layers, scenarios and steps](https://d2lang.com/tour/composition/), where a scenario inherits from
the base diagram and a step inherits from the one before. The
[`--animate-interval` flag](https://d2lang.com/blog/animation/) packs several boards into one SVG that switches
between them on a timer. The difference from diagr is the unit of change: D2 swaps whole diagrams, while a diagr
scenario changes the state of parts of one diagram (a node is active, an edge is drawn, a cell is filled), and the
viewer can pause, step back and scrub.

**Mermaid** is the usual choice for diagrams inside READMEs and docs, because many platforms render it directly.
Flowchart edges can be
[animated](https://mermaid.js.org/syntax/flowchart.html) with a moving dash (`e1@{ animate: true }`), which shows
that something flows but not in what order. Step-by-step playback comes from separate projects, such as
[Mermaid Flow Player](https://jagreehal.github.io/mermaid-flow-player/features/).

**Structurizr** is architecture as code built on the C4 model: you describe the system once and generate many views
from it. Views can have an [animation](https://docs.structurizr.com/ui/diagrams/animation) made of steps that reveal
elements and relationships, and [dynamic views](https://docs.structurizr.com/ui/diagrams/dynamic-view) show how a
use case works. Its strength is the shared model; diagr diagrams are independent files.

**LikeC4** is another open-source architecture-as-code tool with a model and several
[view types](https://likec4-docs-astro.pages.dev/tooling/cli), including dynamic views with a walkthrough, and its
CLI builds a static website of the diagrams.

**Ilograph** is the closest in spirit. Diagrams are written in YAML, organised into perspectives, and
[sequence perspectives](https://ilograph.com/docs/editing/perspectives/sequence-perspectives) and
[walkthroughs](https://www.ilograph.com/blog/posts/feature-spotlight-walkthroughs/) let a viewer step through a
scenario. Its desktop app can
[export standalone interactive HTML files](https://www.ilograph.com/docs/cli-and-export-api/). It lays diagrams out
automatically, it is a commercial product rather than an open-source CLI, and its sequences move control between
resources rather than changing what each part of the diagram shows.

**IcePanel** is a visual modelling tool in the browser. Its [flows](https://docs.icepanel.io/features/flows) build a
sequence of steps on top of an existing diagram, with step types for messages, alternate paths and links to other
flows. You work on a canvas rather than in text files in your repository.

## What diagr does differently

None of these is unique on its own; the combination is what diagr is for.

- **A story told with states.** A step can make a node active, done or failed, fill progress cells, replace text,
  show or hide parts and draw edges, several of them at once and in lockstep.
- **Exact scrubbing.** Each frame only sets values, so stepping back or dragging the slider shows exactly what
  playing would.
- **Three outputs from one file.** A static SVG for light mode and one for dark mode, for READMEs and slides, plus a
  single HTML page with the player that needs nothing else at runtime.
- **Checks that point at the line.** Errors and warnings carry the file, line and column, with a suggestion for
  typos, and they cover layout problems you would otherwise only spot in the picture: edges through nodes, edges
  across a group's title, nodes over groups they are not in.
- **Reuse within a file.** Components with text parameters, nested groups, several scenarios with their own
  triggers, and looping for screens nobody touches.

## When another tool fits better

- **You want the layout done for you**, or the diagram has dozens of nodes: D2, Mermaid and Graphviz place nodes
  automatically. diagr asks you to place each node on the grid.
- **You want one model of the whole system** and many views generated from it: Structurizr, LikeC4 or IcePanel.
- **The diagram lives in a Markdown file on a platform that renders Mermaid**: Mermaid needs no build step.
- **You only need a picture**, not a story: any of the diagram languages will do, and diagr's static SVGs are one
  option among several.
