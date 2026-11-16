// Before the page draws: the light or dark theme the reader chose last, or else their system's, and the contrast
// switch if they left it on.
(function () {
  var t = null, c = null;
  try { t = localStorage.getItem("diagr-theme"); c = localStorage.getItem("diagr-contrast"); } catch (e) {}
  if (t !== "light" && t !== "dark") {
    t = window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  var r = document.documentElement;
  r.setAttribute("data-theme", t);
  if (c === "on") r.setAttribute("data-contrast", "on");
})();
