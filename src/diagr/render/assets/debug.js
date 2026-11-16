// G shows or hides the authoring overlay: the grid and the routes.
document.addEventListener("keydown", function (e) {
  var tag = (e.target && e.target.tagName) || "";
  if (e.key !== "g" || e.metaKey || e.ctrlKey || e.altKey) return;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  if (!(e.target.closest && e.target.closest(".wrap"))) return;
  document.querySelectorAll(".dg-debug").forEach(function (o) { o.style.display = o.style.display === "none" ? "" : "none"; });
});
