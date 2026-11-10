# Themes and icons

## Themes

A theme is a YAML file with a font, sizes, and two token sets of the same names: `light` and `dark`. Two themes are
built in, in `src/diagr/themes/`:

- **`default`**, used when a diagram names none.
- **`contrast`**, for projectors, printouts and readers who need more contrast: black or white text, darker lines and
  group borders and thicker edges. It changes colours and line widths only, so every player page can switch to it
  live with its contrast button (or ++c++), whatever theme the diagram uses. For static images, build with
  `diagr build --theme contrast`; every [example](examples/index.md) shows them in its Contrast tab.

Either way, the colours reach both outputs:

- Static SVGs bake the colours in, one file per scheme, so they work in slides, PDF tools and `<img>` tags.
- The HTML page writes the tokens as CSS variables and switches between them with the light and dark button (or the
  reader's system setting on first visit). The contrast button next to it swaps in the `contrast` tokens.

A brand theme only needs the tokens it changes:

```yaml
extends: default
name: acme
light:
  accent: "#d03801"
  tones:
    blue: {fill: "#eef4ff", stroke: "#1d4ed8"}
dark:
  accent: "#ff7a45"
```

Use it with `theme: ./acme.yml` in the diagram, or `diagr build --theme ./acme.yml` to recolour without editing
the diagram.

Tokens: `bg`, `text`, `muted`, `line`, `rule`, `hover`, `accent`, `on-accent`, `fail`, `new`, `changed`, `button`,
`on-button`, `badge`, `on-badge`, `tones.<tone>.fill|stroke` for groups, and `tiles.<tone>: [from, to]` for the
gradient of generated icon tiles.

## Icons

Icons are looked up by name: first in the diagram's `icons:` folders, in order, then in the core set
(`src/diagr/iconsets/core/icons.yml`).

The core set is neutral on purpose. These are all of its icons, each with the tone its tile uses unless the node
sets `tone`; `diagr icons` lists them in the terminal, along with those in a diagram's own folders.

<!-- icon-gallery -->

An icon folder holds either kind of icon:

- **SVG files.** `name.svg` is inlined as a `<symbol>` with its ids prefixed, so several icons never clash and the
  output stays one self-contained file.
- **Generated tiles.** An `icons.yml` with tiles: a theme tone plus a white line glyph on a 64 by 64 grid.

```yaml
tiles:
  ledger: {tone: green, glyph: '<path d="M18 12h28v40H18z"/><path d="M24 22h16M24 30h16"/>'}
  sync: {tone: violet, spins: true, glyph: '<path d="..."/>'}
recolour:
  logo: text        # a monochrome logo.svg in this folder follows the theme's text colour
```

Vendor marks (cloud providers, products) belong in an icon folder next to the diagram, or in a separate kit, never
in the core set. Check the vendor's terms before you redistribute their icons. Microsoft's Azure and Fabric icon
terms, for example, allow them in diagrams and documentation but not cropped, flipped or rotated, so a diagram that
uses them should not use `spin` on them.
