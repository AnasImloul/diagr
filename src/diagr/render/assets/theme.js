// The light and dark button, remembered for the next visit.
document.getElementById("toggle").addEventListener("click", function () {
  var r = document.documentElement, next = r.getAttribute("data-theme") === "dark" ? "light" : "dark";
  r.setAttribute("data-theme", next);
  try { localStorage.setItem("diagr-theme", next); } catch (e) {}
});
