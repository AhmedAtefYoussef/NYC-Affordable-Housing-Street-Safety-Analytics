/* The report's loading line (the gold bar at the top of the report, .report::before in 30-explore.css), with a real
   finish. Dash marks the report is-loading while it is being built, which is often only half a second (a Reset, a
   quick filter change). The line used to run a 4-second CSS growth and, when the work ended early, lost its animation
   and collapsed back to nothing while it faded: it looked as if it had given up.

   Here the line:
     starts     fades in and grows fast at first, then slower and slower, toward 92% (it never claims to be done)
     finishes   when the report is ready, runs on from wherever it is to the full width, flares, and fades out

   The bar's own gradient (30-explore.css) is brightest at its leading end, so a head of light always leads it. Only
   transform and opacity move, so the browser composites it. Under reduced motion the CSS keeps a plain line. */
(function () {
  "use strict";

  var NYC = window.NYC;
  var GROW_MS = 4000, FINISH_MS = 720, MIN_SHOWN_MS = 320, EASE = "cubic-bezier(0.16, 1, 0.3, 1)";
  document.documentElement.classList.add("has-report-progress");   // 30-explore.css hands the growth to this script

  NYC.onMount("#report", function (report) {
    if (!report.animate) { return; }
    var grow = null, finish = null, startedAt = 0, loading = report.classList.contains("is-loading");

    function line(keyframes, options) {
      options.pseudoElement = "::before";
      try { return report.animate(keyframes, options); } catch (error) { return null; }   // no pseudo-element animation
    }
    /* How far the line has got: the horizontal scale of the bar as drawn right now. */
    function reach() {
      var matrix = getComputedStyle(report, "::before").transform;
      var a = matrix && matrix !== "none" ? parseFloat(matrix.split("(")[1]) : 0;
      return isFinite(a) ? Math.max(0, Math.min(1, a)) : 0;
    }

    function start() {
      if (NYC.reducedMotion()) { return; }
      if (finish) { finish.cancel(); finish = null; }
      startedAt = performance.now();
      // Quick at first, then patient: most of the way in the first second, the last stretch held back.
      grow = line([
        { transform: "scaleX(0)", opacity: 0 },
        { transform: "scaleX(0.38)", opacity: 1, offset: 0.12 },
        { transform: "scaleX(0.62)", opacity: 1, offset: 0.35 },
        { transform: "scaleX(0.8)", opacity: 1, offset: 0.65 },
        { transform: "scaleX(0.92)", opacity: 1 }
      ], { duration: GROW_MS, easing: "linear", fill: "forwards" });
    }
    function end() {
      if (!grow) { return; }
      var from = reach();
      grow.cancel(); grow = null;
      // A report that arrives at once still shows the line long enough to be seen running home.
      var wait = Math.max(0, MIN_SHOWN_MS - (performance.now() - startedAt));
      finish = line([
        { transform: "scaleX(" + from + ")", opacity: 1 },
        { transform: "scaleX(1)", opacity: 1, offset: 0.45 },
        { transform: "scaleX(1) scaleY(1.6)", opacity: 0.9, offset: 0.6 },
        { transform: "scaleX(1) scaleY(1)", opacity: 0 }
      ], { duration: FINISH_MS + wait, easing: EASE });
      if (finish) { finish.onfinish = function () { finish = null; }; }
    }

    if (loading) { start(); }
    new MutationObserver(function () {
      var now = report.classList.contains("is-loading");
      if (now === loading) { return; }
      loading = now;
      if (now) { start(); } else { end(); }
    }).observe(report, { attributes: true, attributeFilter: ["class"] });
  });
})();
