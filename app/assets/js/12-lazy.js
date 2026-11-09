/* Parts of the page built when the reader comes near them (app/ui/lazy.py). Each element with data-lazy="<name>" is
   an empty frame until it is within about two screens of the window; then the store "<name>-seen" is set and Dash
   returns the real content. The report is also built the moment the reader touches the Explore controls, so its
   charts always exist before Generate runs. */
(function () {
  "use strict";

  var NYC = window.NYC = window.NYC || {};
  var asked = {};

  function build(name) {
    if (asked[name] || !window.dash_clientside || !window.dash_clientside.set_props) { return; }
    asked[name] = true;
    window.dash_clientside.set_props(name + "-seen", { data: Date.now() });
  }
  NYC.buildLazy = build;

  var watcher = "IntersectionObserver" in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) { return; }
      watcher.unobserve(entry.target);
      build(entry.target.getAttribute("data-lazy"));
    });
  }, { rootMargin: "200% 0px 200% 0px" }) : null;

  NYC.onMount("[data-lazy]", function (frame) {
    if (watcher) { watcher.observe(frame); } else { build(frame.getAttribute("data-lazy")); }
  });

  ["pointerdown", "focusin", "keydown"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      if (event.target.closest && event.target.closest("#explore")) { build("lazy-report"); }
    }, { passive: true, capture: true });
  });
})();
