// Smooth scrolling for links to a section of the current page (the sidebar sections, heading permalinks).
// Done here rather than with CSS scroll-behavior, which would also animate Material's scroll reset on page changes.
(function () {
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)");

  window.addEventListener(
    "click",
    function (e) {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      // navigation.instant rewrites links to absolute URLs, so compare the resolved URL with this page.
      var link = e.target.closest && e.target.closest("a[href]");
      if (!link || link.target || !link.hash || link.hash.indexOf("#__") === 0) return;
      if (link.origin !== location.origin || link.pathname !== location.pathname || link.search !== location.search)
        return;
      var href = link.hash;
      var target = document.getElementById(decodeURIComponent(href.slice(1)));
      if (!target) return;

      e.preventDefault();
      e.stopPropagation();
      var drawer = document.getElementById("__drawer");
      if (drawer) drawer.checked = false;
      target.scrollIntoView({ behavior: reduce && reduce.matches ? "auto" : "smooth", block: "start" });
      if (location.hash !== href) history.pushState(null, "", href);
      if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    },
    true
  );
})();
