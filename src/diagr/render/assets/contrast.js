// The contrast button and C: the built-in contrast theme's colours and line widths, live, remembered for the next
// visit. Text sizes stay the same, so the layout does not move.
(function () {
  var b = document.getElementById("contrast"), r = document.documentElement;
  if (!b) return;
  function sync() { b.setAttribute("aria-pressed", r.getAttribute("data-contrast") === "on" ? "true" : "false"); }
  function flip() {
    var on = r.getAttribute("data-contrast") !== "on";
    if (on) r.setAttribute("data-contrast", "on"); else r.removeAttribute("data-contrast");
    try { localStorage.setItem("diagr-contrast", on ? "on" : "off"); } catch (e) {}
    sync();
  }
  b.addEventListener("click", flip);
  // Keys work while focus is in the diagram or the player, so the rest of the page keeps them.
  document.addEventListener("keydown", function (e) {
    var tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || e.metaKey || e.ctrlKey || e.altKey) return;
    if (!(e.target.closest && e.target.closest(".wrap"))) return;
    if (e.key === "c" || e.key === "C") flip();
  });
  sync();
})();
