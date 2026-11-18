---
title: Playground
description: Write a diagr diagram in the browser and see it render as you type.
hide: [navigation, toc, footer]
---

<div class="dg-play" id="dg-play" data-examples="examples.json">
<div class="dg-play__bar">
<h1>Playground</h1>
<label class="dg-play__field">Start from <select id="dg-play-example"></select></label>
<p class="dg-play__status" id="dg-play-status" role="status">Loading</p>
<button class="dg-play__button" id="dg-play-format" type="button" title="Line up nodes and edges into columns">Format</button>
<button class="dg-play__button" id="dg-play-share" type="button">Copy link</button>
</div>
<div class="dg-play__panes">
<section class="dg-play__editor" aria-label="Diagram source">
<div class="dg-play__source" id="dg-play-editor"><textarea id="dg-play-source" spellcheck="false" aria-label="Diagram YAML"></textarea></div>
<ol class="dg-play__problems" id="dg-play-problems" aria-label="Problems" hidden></ol>
</section>
<div class="dg-play__split" id="dg-play-split" role="separator" tabindex="0" aria-orientation="vertical" aria-label="Resize the editor" aria-valuemin="20" aria-valuemax="75" aria-valuenow="40"></div>
<section class="dg-play__preview" aria-label="Preview">
<div class="dg-play__bar dg-play__bar--preview">
<div class="dg-play__tabs" role="group" aria-label="Show">
<button type="button" data-mode="player" aria-pressed="true">Player</button>
<button type="button" data-mode="image" aria-pressed="false">Image</button>
</div>
<label class="dg-play__field" id="dg-play-view-field" hidden>View <select id="dg-play-view"></select></label>
<button class="dg-play__button" id="dg-play-contrast" type="button" aria-pressed="false">Contrast</button>
<span class="dg-play__spacer"></span>
<span class="dg-play__downloads" role="group" aria-label="Download">
<button class="dg-play__button" type="button" data-download="light">Light SVG</button>
<button class="dg-play__button" type="button" data-download="dark">Dark SVG</button>
<button class="dg-play__button" type="button" data-download="html">HTML</button>
</span>
</div>
<div class="dg-play__stage" id="dg-play-stage">
<div class="dg-play__empty" id="dg-play-empty" aria-hidden="true"><span class="dg-play__spinner"></span></div>
</div>
</section>
</div>
</div>
