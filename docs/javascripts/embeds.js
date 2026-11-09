(function () {
  function scheme() {
    return document.body.getAttribute("data-md-color-scheme") === "slate" ? "dark" : "light";
  }

  function theme(frame) {
    try {
      frame.contentDocument.documentElement.setAttribute("data-theme", scheme());
    } catch (e) {}
  }

  function setup(frame) {
    var doc;
    try {
      doc = frame.contentDocument;
    } catch (e) {
      return;
    }
    if (!doc || !doc.documentElement || doc.URL === "about:blank" || frame._diagrDoc === doc) return;
    frame._diagrDoc = doc;
    var toggle = doc.getElementById("toggle");
    if (toggle) toggle.style.display = "none";
    theme(frame);
    new ResizeObserver(function () {
      frame.style.height = doc.documentElement.scrollHeight + "px";
    }).observe(doc.documentElement);
  }

  function frames() {
    return document.querySelectorAll("iframe.diagr-embed");
  }

  function init() {
    frames().forEach(function (frame) {
      if (frame._diagrBound) return;
      frame._diagrBound = true;
      frame.addEventListener("load", function () {
        setup(frame);
      });
      if (frame.contentDocument && frame.contentDocument.readyState === "complete") setup(frame);
    });
  }

  // With navigation.instant, Material swaps pages without rerunning this script; document$ fires on each swap.
  init();
  if (window.document$ && typeof window.document$.subscribe === "function") window.document$.subscribe(init);

  new MutationObserver(function () {
    frames().forEach(theme);
  }).observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
})();
