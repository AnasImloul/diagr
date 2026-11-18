# Docs and CI

Two ways to keep diagrams next to the text that explains them: render them while the docs are built, or rebuild the
SVGs in CI whenever a diagram changes.

## Diagrams in MkDocs

With [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) (or anything else that uses
`pymdownx.superfences`), a fenced block marked `diagr` is turned into a diagram at build time. Add the fence to
`mkdocs.yml`:

```yaml
markdown_extensions:
  - pymdownx.superfences:
      custom_fences:
        - name: diagr
          class: diagr
          format: !!python/name:diagr.markdown.fence
          validator: !!python/name:diagr.markdown.validate
```

`diagr` has to be installed where MkDocs runs. Then write the diagram in the page:

````markdown
```diagr
nodes:
  web:   {icon: browser, title: Web app}
  api:   {icon: api, title: API}
  users: {icon: database, title: Users}
edges:
  web -> api: sign up
  api -> users: insert
```
````

which comes out as:

```diagr
nodes:
  web:   {icon: browser, title: Web app}
  api:   {icon: api, title: API}
  users: {icon: database, title: Users}
edges:
  web -> api: sign up
  api -> users: insert
```

- **Without a scenario** the block becomes the static SVG, in light or dark to match the site.
- **With a scenario** it becomes the player, in an iframe that grows to fit and follows the site's light and dark
  toggle. Its own light and dark button is hidden, since the site's applies; its contrast button stays.
- `mode="static"` or `mode="player"` on the opening line (```` ```diagr mode="static" ````) picks one regardless.
- A diagram with errors shows them in place of the picture, with line numbers counted from the top of the block, and
  MkDocs logs them as warnings, so `mkdocs build --strict` fails on them.
- Relative paths in the block, such as `icons: [./icons]`, resolve from the directory MkDocs runs in.

And with a scenario and a group:

```diagr
title: Sign-up
groups:
  back:
    title: Backend
    nodes:
      api:   {icon: api, title: API}
      users: {icon: database, title: Users}
nodes:
  web:   {icon: browser, title: Web app}
  mail:  {icon: mail, title: Welcome email}
edges:
  web -> api: sign up
  api -> (users mail): [insert, send]
scenario:
  trigger: {at: web, label: Sign up}
  ready: Press Sign up.
  end: The account exists and the email is on its way.
  steps:
    - Submit: [flow web -> api]
    - Store and send: [flow api -> (users mail) done]
```

## Rebuilding SVGs in CI

For a README or any site that shows the SVG files themselves, commit them next to the diagrams and let CI rebuild
them. This GitHub Actions workflow rebuilds the images whenever a diagram on `main` changes and commits the result:

```yaml
# .github/workflows/diagrams.yml
name: diagrams

on:
  push:
    branches: [main]
    paths: ["diagrams/**.yml"]
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      # diagr is not on PyPI yet: install it from its repository.
      - run: pip install "diagr @ git+https://github.com/<owner>/diagr"
      - run: diagr check --strict diagrams/*.yml
      - run: diagr build diagrams/*.yml --svg -o diagrams/out
      - name: Commit the images if they changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898341+github-actions[bot]@users.noreply.github.com"
          git add diagrams/out
          git diff --cached --quiet || (git commit -m "chore: rebuild diagrams" && git push)
```

The commit it pushes does not start the workflow again: pushes made with the workflow's own token never do.

To keep `main` free of bot commits, check pull requests instead: build, then fail if the committed images differ
from what the diagrams produce.

```yaml
      - run: diagr build diagrams/*.yml --svg -o diagrams/out
      - run: git diff --exit-code -- diagrams/out
```

Either way, `diagr check --strict` fails the run on warnings as well as errors, such as an edge through a node.
