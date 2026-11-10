/* The Generate button's light, kept smooth through every change Dash makes to it.

   Dash changes the button in hard steps: the "filters changed" class (is-stale) comes and goes in one frame, and while
   a report is being built the button is disabled and relabelled. On their own those steps make the light jump: the
   gold pulse would snap from wherever it is to rest, the label would swap in one frame. Here:

     the pulse    is run by this script, fades in when the filters change, and when they match the report again it
                  glides from whatever it is showing at that moment back to rest (it never snaps)
     the label    crossfades when Dash changes it ("Generating…" and back)
     Reset        once the report for the default filters is ready, the button recharges: a bright sheen sweeps
                  across it and a gold bloom settles back to rest, so it reads as ready again

   Every shadow below has the resting shadow's layers in the same order (two inset, then two outer, then the ring), so
   the browser blends them smoothly instead of switching. Nothing runs for a reader who asked for less motion. */
(function () {
  "use strict";

  var NYC = window.NYC;
  var PULSE_MS = 2200, FADE_IN_MS = 520, FADE_OUT_MS = 760, LABEL_MS = 300, BLOOM_MS = 1300, SHEEN_MS = 950;
  var EASE = "cubic-bezier(0.16, 1, 0.3, 1)";
  document.documentElement.classList.add("has-generate-light");    // 30-explore.css hands the pulse to this script

  function gold(alpha) {
    var rgb = getComputedStyle(document.documentElement).getPropertyValue("--gold-rgb").trim() || "229 189 111";
    return "rgb(" + rgb + " / " + alpha + ")";
  }
  // The resting shadow's two inset layers, kept in every frame so each frame has the same structure.
  var INSETS = "inset 0 1px 0 rgb(255 255 255 / 0.55), inset 0 -2px 0 rgb(80 50 10 / 0.22), 0 1px 2px rgb(0 0 0 / 0.4), ";
  function pulseLow() { return INSETS + "0 8px 40px -12px " + gold(0.55) + ", 0 0 0 0 " + gold(0.55); }
  function pulseHigh() { return INSETS + "0 8px 54px -8px " + gold(0.8) + ", 0 0 0 14px " + gold(0); }
  function bloom() { return "inset 0 1px 0 rgb(255 255 255 / 0.75), inset 0 -2px 0 rgb(80 50 10 / 0.12), 0 1px 2px rgb(0 0 0 / 0.35), 0 10px 64px -4px " + gold(0.95) + ", 0 0 0 3px " + gold(0.6); }

  NYC.onMount("#generate", function (button) {
    if (!button.animate) { return; }
    var pulse = null, fading = null, stale = button.classList.contains("is-stale"), label = button.textContent;

    /* The resting shadow as the page draws it now (hover and focus included). Every caller has cancelled this
       script's animations first, so the computed value is the page's own. */
    function rest() { return getComputedStyle(button).boxShadow; }
    function stopFade() { if (fading) { fading.cancel(); fading = null; } }

    function startPulse() {
      if (NYC.reducedMotion() || pulse) { return; }
      stopFade();
      var from = getComputedStyle(button).boxShadow;
      // In from wherever the button is, then the slow breath, started where the fade ends so the two join.
      fading = button.animate([{ boxShadow: from }, { boxShadow: pulseLow() }], { duration: FADE_IN_MS, easing: EASE });
      pulse = button.animate([{ boxShadow: pulseLow() }, { boxShadow: pulseHigh() }, { boxShadow: pulseLow() }],
                             { duration: PULSE_MS, delay: FADE_IN_MS, iterations: Infinity, easing: "ease-in-out" });
      fading.onfinish = function () { fading = null; };
    }
    function endPulse() {
      if (!pulse) { return; }
      // What the light shows at this very moment, then out of it smoothly: to rest, or up into the recharge.
      var from = getComputedStyle(button).boxShadow;
      pulse.cancel(); pulse = null; stopFade();
      if (pendingRecharge) { pendingRecharge = false; recharge(from); return; }
      var to = rest();
      fading = button.animate([{ boxShadow: from }, { boxShadow: to }], { duration: FADE_OUT_MS, easing: EASE });
      fading.onfinish = function () { fading = null; };
    }

    /* The recharge after Reset: a sheen across the button and a bloom that settles to rest. If the pulse is still
       showing (the filters catch up with the new report a moment after it is drawn), it waits for the pulse to end
       and starts from the light the pulse was showing, so the two are one movement. */
    var pendingRecharge = false;
    function recharge(from) {
      if (NYC.reducedMotion()) { return; }
      if (pulse) { pendingRecharge = true; window.setTimeout(function () { pendingRecharge = false; }, 3000); return; }
      stopFade();
      var settle = rest(), frames = from ? [{ boxShadow: from }, { boxShadow: bloom(), offset: 0.22 }, { boxShadow: settle }]
                                         : [{ boxShadow: settle }, { boxShadow: bloom(), offset: 0.18 }, { boxShadow: settle }];
      fading = button.animate(frames, { duration: BLOOM_MS, easing: "ease-out" });
      fading.onfinish = function () { fading = null; };
      try {
        button.animate([{ transform: "translateX(-130%)" }, { transform: "translateX(130%)" }],
                       { duration: SHEEN_MS, easing: "cubic-bezier(0.45, 0, 0.2, 1)", pseudoElement: "::before" });
      } catch (error) { /* a browser without animations on pseudo-elements keeps the bloom alone */ }
    }

    if (stale) { startPulse(); }
    new MutationObserver(function () {
      var now = button.classList.contains("is-stale");
      if (now !== stale) { stale = now; if (now) { startPulse(); } else { endPulse(); } }
      var text = button.textContent;
      if (text !== label) {
        label = text;
        if (!NYC.reducedMotion()) {
          button.animate([{ color: "transparent" }, { color: getComputedStyle(button).color }], { duration: LABEL_MS, easing: "ease-out" });
        }
      }
    }).observe(button, { attributes: true, attributeFilter: ["class"], childList: true, characterData: true, subtree: true });

    // Reset asks for the default report; when it has been drawn, the button recharges.
    var resetAsked = false;
    document.addEventListener("click", function (event) {
      if (event.target.closest && event.target.closest("#reset")) { resetAsked = true; }
    }, true);
    NYC.onMount("#report", function (report) {
      var wasLoading = report.classList.contains("is-loading");
      new MutationObserver(function () {
        var loading = report.classList.contains("is-loading");
        if (wasLoading && !loading && resetAsked) { resetAsked = false; window.setTimeout(function () { recharge(null); }, 60); }
        wasLoading = loading;
      }).observe(report, { attributes: true, attributeFilter: ["class"] });
    });
  });
})();
