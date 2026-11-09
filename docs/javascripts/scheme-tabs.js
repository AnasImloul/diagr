(function () {
  // On example pages, open the static image tab that matches the site's scheme (Light or Dark), on load and when the
  // scheme changes. A tab the reader picks stays until the scheme changes again; Contrast already follows the scheme.
  function scheme() {
    return document.body.getAttribute("data-md-color-scheme") === "slate" ? "Dark" : "Light";
  }

  function sync() {
    var want = scheme();
    document.querySelectorAll(".tabbed-set").forEach(function (set) {
      if (!set.querySelector("img.dg-shot")) return;
      var labels = Array.prototype.slice.call(set.querySelectorAll(".tabbed-labels > label"));
      var inputs = set.querySelectorAll(":scope > input");
      var current = labels.find(function (l, i) { return inputs[i] && inputs[i].checked; });
      if (current && current.textContent.trim() === "Contrast") return;
      labels.forEach(function (l, i) {
        if (l.textContent.trim() === want && inputs[i]) inputs[i].checked = true;
      });
    });
  }

  sync();
  if (window.document$ && typeof window.document$.subscribe === "function") window.document$.subscribe(sync);
  new MutationObserver(sync).observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
})();
