// While diagr watch serves the page: reload when the build changes, keeping the scenario, frame and scroll.
(function () {
  var key = "diagr-live:" + location.pathname, seen = null;
  try {
    var s = JSON.parse(sessionStorage.getItem(key) || "null");
    sessionStorage.removeItem(key);
    if (s && window.diagr) {
      if (s.scenario) diagr.scenario(s.scenario);
      diagr.seek(Math.min(s.frame, diagr.frames));
      if (s.looping) diagr.play();
    }
    if (s) window.scrollTo(0, s.y);
  } catch (e) {}
  function save() {
    var s = { y: window.scrollY };
    if (window.diagr) { s.scenario = diagr.scenario(); s.frame = diagr.frame(); s.looping = diagr.looping(); }
    try { sessionStorage.setItem(key, JSON.stringify(s)); } catch (e) {}
  }
  function poll() {
    fetch("__VERSION__", { cache: "no-store" }).then(function (r) { return r.text(); }).then(function (v) {
      if (seen === null) seen = v;
      else if (v !== seen) { save(); location.reload(); }
    }).catch(function () {}).then(function () { setTimeout(poll, 500); });
  }
  poll();
})();
