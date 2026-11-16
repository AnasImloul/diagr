(function () {
  "use strict";
  // Zoom and pan by rewriting the viewBox, so text and lines stay sharp at any scale.
  var svg = document.querySelector("svg.diagr"), stage = svg && svg.closest(".stage");
  if (!svg || !stage) return;
  var vb = svg.viewBox.baseVal, X = vb.x, Y = vb.y, W = vb.width, H = vb.height;
  var MAX = 6, z = 1, cx = X + W / 2, cy = Y + H / 2;
  var pointers = new Map(), drag = null, pinch = null;

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function apply() {
    var w = W / z, h = H / z;
    cx = clamp(cx, X + w / 2, X + W - w / 2);
    cy = clamp(cy, Y + h / 2, Y + H - h / 2);
    svg.setAttribute("viewBox", [cx - w / 2, cy - h / 2, w, h].join(" "));
    var zoomed = z > 1.001;
    stage.classList.toggle("zoomed", zoomed);
    svg.style.touchAction = zoomed ? "none" : "pan-x pan-y";
  }
  // Zoom to nz keeping the diagram point under (px, py) on screen where it is.
  function zoomAt(nz, px, py) {
    var r = svg.getBoundingClientRect(), fx = (px - r.left) / r.width, fy = (py - r.top) / r.height;
    var w = W / z, h = H / z, x = cx - w / 2 + fx * w, y = cy - h / 2 + fy * h;
    z = clamp(nz, 1, MAX);
    cx = x - (fx - 0.5) * (W / z);
    cy = y - (fy - 0.5) * (H / z);
    apply();
  }
  function zoomCenter(nz) {
    var r = svg.getBoundingClientRect();
    zoomAt(nz, r.left + r.width / 2, r.top + r.height / 2);
  }
  function fit() { z = 1; cx = X + W / 2; cy = Y + H / 2; apply(); }

  svg.addEventListener("wheel", function (e) {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    zoomAt(z * Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.002)), e.clientX, e.clientY);
  }, { passive: false });

  svg.addEventListener("pointerdown", function (e) {
    if (e.button !== 0 || (e.target.closest && e.target.closest(".trigger"))) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) {
      var p = Array.from(pointers.values());
      pinch = { d: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y), z: z };
      drag = null;
    } else if (z > 1.001) {
      drag = { x: e.clientX, y: e.clientY, moved: false };
    }
  });
  svg.addEventListener("pointermove", function (e) {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && pointers.size === 2) {
      var p = Array.from(pointers.values());
      zoomAt(pinch.z * Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) / pinch.d, (p[0].x + p[1].x) / 2, (p[0].y + p[1].y) / 2);
    } else if (drag) {
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) < 3) return;
      if (!drag.moved) {
        drag.moved = true;
        stage.classList.add("panning");
        try { svg.setPointerCapture(e.pointerId); } catch (err) {}
      }
      var r = svg.getBoundingClientRect();
      cx -= dx / r.width * (W / z);
      cy -= dy / r.height * (H / z);
      drag.x = e.clientX; drag.y = e.clientY;
      apply();
    }
  });
  function release(e) {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (pointers.size === 0) { drag = null; stage.classList.remove("panning"); }
  }
  svg.addEventListener("pointerup", release);
  svg.addEventListener("pointercancel", release);

  // Full screen shows the diagram and its player controls together; Esc or the button leaves it.
  var page = stage.closest(".wrap") || stage, full = stage.querySelector('[data-zoom="full"]');
  function toggleFull() {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (page.requestFullscreen) page.requestFullscreen().catch(function () {});
  }
  if (full && !document.fullscreenEnabled) full.hidden = true;
  document.addEventListener("fullscreenchange", function () {
    var on = document.fullscreenElement === page;
    if (full) {
      full.setAttribute("aria-label", on ? "Leave full screen (F)" : "Full screen (F)");
      full.title = full.getAttribute("aria-label");
    }
  });

  stage.querySelectorAll(".zoom button").forEach(function (b) {
    b.addEventListener("click", function () {
      var act = b.getAttribute("data-zoom");
      if (act === "in") zoomCenter(z * 1.5);
      else if (act === "out") zoomCenter(z / 1.5);
      else if (act === "fit") fit();
      else if (act === "full") toggleFull();
    });
  });
  // Keys work while focus is in the diagram or the player, so the rest of the page keeps them.
  document.addEventListener("keydown", function (e) {
    var tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || e.metaKey || e.ctrlKey || e.altKey) return;
    if (!(e.target.closest && e.target.closest(".wrap"))) return;
    if (e.key === "+" || e.key === "=") zoomCenter(z * 1.5);
    else if (e.key === "-" || e.key === "_") zoomCenter(z / 1.5);
    else if (e.key === "0") fit();
    else if ((e.key === "f" || e.key === "F") && document.fullscreenEnabled) toggleFull();
  });

  window.diagrZoom = { zoom: function (nz) { if (nz) zoomCenter(nz); return z; }, fit: fit, fullscreen: toggleFull };
  apply();
})();
