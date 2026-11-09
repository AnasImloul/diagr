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
    if (!doc || !doc.documentElement) return;
    var toggle = doc.getElementById("toggle");
    if (toggle) toggle.style.display = "none";
    theme(frame);
    new ResizeObserver(function () {
      frame.style.height = doc.documentElement.scrollHeight + "px";
    }).observe(doc.documentElement);
  }

  var frames = document.querySelectorAll("iframe.diagr-embed");
  frames.forEach(function (frame) {
    frame.addEventListener("load", function () {
      setup(frame);
    });
    if (frame.contentDocument && frame.contentDocument.readyState === "complete") setup(frame);
  });

  new MutationObserver(function () {
    frames.forEach(theme);
  }).observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
})();
