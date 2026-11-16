(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("diagr-data").textContent);
  var svg = document.querySelector("svg.diagr");
  var scenarios = data.scenarios, byId = {};
  scenarios.forEach(function (x) { byId[x.id] = x; });
  var sc, frames, steps, N, states, items = [];
  var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var K = reduced ? 0.35 : 1;

  function index(sel, attr) {
    var m = new Map();
    svg.querySelectorAll(sel).forEach(function (el) { m.set(el.getAttribute(attr), el); });
    return m;
  }
  var nodes = index(".node", "data-id"), edges = index(".edge", "data-id"),
      labels = index(".elab", "data-edge"), groups = index(".grp", "data-id"), keyed = index("[data-key]", "data-key");
  var panel = document.getElementById("panel"), statusEl = document.getElementById("status"),
      fill = document.getElementById("fill"), lists = panel ? panel.querySelectorAll("ol.steps") : [],
      picker = panel ? panel.querySelectorAll(".scenarios button") : [], controls = document.querySelector(".controls"), scrub = document.getElementById("scrub"),
      speedEl = document.getElementById("speed"), triggers = svg.querySelectorAll(".trigger");

  var k = 0, cur = {}, timer = null, playing = false, speed = 1;
  // A looping scenario replays after holding its last frame; any input from the viewer stops the loop.
  var HOLD = 2000, looping = false, hold = null, inView = true;

  function attr(el, name, v) {
    if (!el) return;
    if (v === undefined || v === null) el.removeAttribute(name); else el.setAttribute(name, v);
  }
  function target(id) { return nodes.get(id) || edges.get(id) || groups.get(id); }

  function setKey(key, v, frame, animate) {
    var p = key.indexOf(":"), kind = p < 0 ? key : key.slice(0, p), rest = p < 0 ? "" : key.slice(p + 1);
    switch (kind) {
      case "n": attr(nodes.get(rest), "data-status", v); break;
      case "e":
        var el = edges.get(rest);
        if (el && animate && frame.edges && frame.edges[rest] !== undefined)
          el.style.setProperty("--dur", (frame.edges[rest] * K / speed) + "ms");
        attr(el, "data-status", v); attr(labels.get(rest), "data-status", v); break;
      case "c": attr(keyed.get(key), "data-status", v); break;
      case "t": case "cap":
        var t = keyed.get(key);
        if (t) t.textContent = (v === undefined || v === null) ? t.getAttribute("data-default") : v;
        break;
      case "s": attr(nodes.get(rest), "data-spin", v); break;
      case "v":
        var x = target(rest), lab = labels.get(rest);
        [x, lab].forEach(function (e) {
          if (!e) return;
          var start = e.getAttribute("data-hidden0");
          if (v === "hidden") attr(e, "data-hidden", "1");
          else if (v === "shown") attr(e, "data-hidden", null);
          else attr(e, "data-hidden", start);
        });
        break;
      case "focus":
        svg.classList.toggle("focusing", !!v);
        svg.querySelectorAll("[data-focused]").forEach(function (e) { e.removeAttribute("data-focused"); });
        (v || []).forEach(function (id) {
          [target(id), labels.get(id)].forEach(function (e) { if (e) e.setAttribute("data-focused", ""); });
        });
        break;
      case "status": if (statusEl) statusEl.textContent = v === undefined ? sc.ready : v; break;
      case "step":
        var n = v || 0;
        items.forEach(function (li, idx) {
          li.classList.toggle("done", idx < n - 1 || n > steps.length);
          li.classList.toggle("active", idx === n - 1);
          attr(li, "aria-current", idx === n - 1 ? "step" : null);
        });
        if (panel) panel.classList.toggle("idle", !n);
        break;
      case "running": svg.classList.toggle("running", !!v); break;
    }
  }

  function goTo(j, animate) {
    j = Math.max(0, Math.min(N, j));
    var next = states[j], frame = frames[j];
    if (!animate) document.documentElement.classList.add("seeking");
    var keys = new Set(Object.keys(cur).concat(Object.keys(next)));
    keys.forEach(function (key) {
      var a = cur[key], b = next[key];
      if (JSON.stringify(a) !== JSON.stringify(b)) setKey(key, b, frame, animate);
    });
    cur = next; k = j;
    if (fill) fill.style.width = (N ? k / N * 100 : 0) + "%";
    if (scrub) scrub.value = String(k);
    if (!animate) {
      svg.getBoundingClientRect();
      requestAnimationFrame(function () { document.documentElement.classList.remove("seeking"); });
    }
    svg.setAttribute("data-frame", String(k));
  }

  function setPlaying(on) {
    playing = on;
    if (controls) controls.setAttribute("data-playing", on ? "1" : "0");
    triggers.forEach(function (t) { attr(t, "aria-disabled", on ? "true" : null); });
  }
  function tick() {
    if (k >= N) {
      halt();
      if (looping) hold = setTimeout(function () { hold = null; if (visible()) start(); }, HOLD);
      return;
    }
    goTo(k + 1, true);
    timer = setTimeout(tick, frames[k].dur * K / speed);
  }
  function start() {
    if (playing) return;
    if (k >= N) goTo(0, false);
    setPlaying(true);
    timer = setTimeout(tick, k === 0 ? 30 : 0);
  }
  function halt() { clearTimeout(timer); timer = null; setPlaying(false); }
  function play() { looping = !!sc.loop; start(); }
  function pause() { looping = false; clearTimeout(hold); hold = null; halt(); }
  function visible() { return inView && !document.hidden; }
  // Off screen or in a background tab, a loop waits instead of running.
  function onVisibility() {
    if (!looping) return;
    if (!visible()) halt();
    else if (!playing && !hold) start();
  }
  function seek(j) { pause(); goTo(j, false); }
  function stepOf(j) { return j === 0 ? 0 : frames[j].step; }
  function back() {
    var s = stepOf(k);
    seek(s >= 2 ? steps[s - 2].last : 0);
  }
  function next() {
    var s = stepOf(k);
    if (s === 0) return seek(steps[0].last);
    seek(k < steps[s - 1].last ? steps[s - 1].last : steps[Math.min(s, steps.length - 1)].last);
  }
  function run() { if (!playing) { goTo(0, false); play(); } }

  // Each scenario has its own frames and step list; switching resets the diagram to its start.
  function load(id) {
    sc = byId[id] || scenarios[0];
    frames = sc.frames; steps = sc.steps; N = frames.length - 1;
    states = [{}];
    for (var i = 1; i <= N; i++) {
      var s = Object.assign({}, states[i - 1]), set = frames[i].set;
      for (var key in set) { if (set[key] === null) delete s[key]; else s[key] = set[key]; }
      states.push(s);
    }
    lists.forEach(function (ol) {
      var on = ol.getAttribute("data-scenario") === sc.id;
      ol.hidden = !on;
      if (on) items = ol.querySelectorAll("li");
    });
    picker.forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-scenario") === sc.id)); });
    svg.setAttribute("data-scenario", sc.id);
    if (scrub) scrub.max = String(N);
    api.frames = N;
  }
  function choose(id) {
    if (!byId[id] || sc.id === id) return;
    pause();
    items.forEach(function (li) { li.classList.remove("done", "active"); li.removeAttribute("aria-current"); });
    load(id);
    goTo(0, false);
    if (panel) panel.classList.add("idle");
    if (statusEl) statusEl.textContent = sc.ready;
  }
  function trigger(t) {
    if (playing && !looping) return;
    pause();
    var id = t.getAttribute("data-plays");
    if (id) choose(id);
    run();
  }

  var api = { play: play, pause: pause, seek: seek, back: back, next: next, run: run,
              frame: function () { return k; }, frames: 0, state: function (j) { return states[j]; },
              scenarios: scenarios.map(function (x) { return x.id; }),
              scenario: function (id) { if (id) choose(id); return sc.id; },
              looping: function () { return looping; } };
  window.diagr = api;

  triggers.forEach(function (t) {
    t.addEventListener("click", function () { trigger(t); });
    t.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); trigger(t); } });
  });
  picker.forEach(function (b) { b.addEventListener("click", function () { choose(b.getAttribute("data-scenario")); }); });
  if (controls) controls.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    var act = b.getAttribute("data-act");
    if (act === "play") play(); else if (act === "pause") pause(); else if (act === "back") back();
    else if (act === "next") next(); else if (act === "reset") seek(0);
  });
  if (scrub) scrub.addEventListener("input", function () { seek(+scrub.value); });
  if (speedEl) speedEl.addEventListener("change", function () { speed = +speedEl.value || 1; });
  lists.forEach(function (ol) {
    ol.querySelectorAll("li").forEach(function (li, idx) { li.addEventListener("click", function () { seek(steps[idx].last); }); });
  });
  // Keys work while focus is in the diagram or the player, so the rest of the page keeps them.
  document.addEventListener("keydown", function (e) {
    var tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || e.metaKey || e.ctrlKey || e.altKey) return;
    if (!(e.target.closest && e.target.closest(".wrap"))) return;
    if (e.key === " " && !(e.target.closest && e.target.closest(".trigger, button"))) {
      e.preventDefault(); if (playing) pause(); else play();
    } else if (e.key === "ArrowRight") { e.preventDefault(); if (e.shiftKey) seek(k + 1); else next(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); if (e.shiftKey) seek(k - 1); else back(); }
    else if (e.key === "Home") { e.preventDefault(); seek(0); }
    else if (e.key === "End") { e.preventDefault(); seek(N); }
  });

  svg.querySelectorAll("[data-hidden]").forEach(function (e) { e.setAttribute("data-hidden0", e.getAttribute("data-hidden")); });
  load(svg.getAttribute("data-scenario") || scenarios[0].id);
  if (statusEl) statusEl.textContent = sc.ready;
  goTo(0, false);

  document.addEventListener("visibilitychange", onVisibility);
  if (window.IntersectionObserver) {
    new IntersectionObserver(function (entries) { inView = entries[0].isIntersecting; onVisibility(); }).observe(svg);
  }
  var auto = scenarios.filter(function (x) { return x.loop; })[0];
  if (auto && !reduced) { choose(auto.id); play(); }
})();
