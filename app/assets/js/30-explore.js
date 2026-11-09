/* Explore, in the browser.

   1. The address. After Generate the server sends the query that reopens the selection (?borough=Bronx&from=2019).
      It is written into the address bar with history.replaceState, so the back button is not filled with one entry
      per report. A default selection leaves the address alone.
   2. Copy link, with a confirmation beside the button for a few seconds.
   3. The four figures count up again each time the report changes. React updates the same elements in place, so a
      watcher notices a changed data-final and plays NYC.countUp again, once the full-screen Generate sequence has
      opened onto the report (or at once when there is none).
   4. The search box types and erases the example queries while it is empty and not focused (never under reduced
      motion; then the plain placeholder stays). Pointing at an example, or focusing it, shows that whole query in
      the box at once as a preview, fading in; the typing pauses until the pointer leaves.
   5. A link that names filters scrolls to the report once.

   1 and 2 are Dash clientside functions (window.dash_clientside.explore), registered in app/ui/callbacks.py. */
(function () {
  "use strict";

  var NYC = window.NYC = window.NYC || {};
  var STATUS_MS = 3000;
  var statusTimer = 0;

  function noUpdate() { return window.dash_clientside.no_update; }

  function say(text) {
    window.clearTimeout(statusTimer);
    statusTimer = window.setTimeout(function () {
      window.dash_clientside.set_props("copy-status", { children: "" });
    }, STATUS_MS);
    return text;
  }

  function fallbackCopy(text) {
    var field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    var copied = false;
    try { copied = document.execCommand("copy"); } catch (error) { copied = false; }
    document.body.removeChild(field);
    return copied;
  }

  function addressFor(query) {
    var q = typeof query === "string" && query.charAt(0) === "?" ? query : "";
    return window.location.pathname + q + (q ? "#explore" : window.location.hash);
  }

  window.dash_clientside = Object.assign({}, window.dash_clientside, {
    explore: {
      mirrorUrl: function (query) {
        if (typeof query !== "string") { return noUpdate(); }
        if (!query && !window.location.search) { return noUpdate(); }
        try { window.history.replaceState(window.history.state, "", addressFor(query)); } catch (error) { /* sandboxed frame */ }
        return noUpdate();
      },

      copyLink: function (clicks, query) {
        if (!clicks) { return noUpdate(); }
        var q = typeof query === "string" && query.charAt(0) === "?" ? query : "";
        var address = window.location.origin + window.location.pathname + q + "#explore";
        if (navigator.clipboard && navigator.clipboard.writeText) {
          return navigator.clipboard.writeText(address).then(
            function () { return say("Link copied"); },
            function () { return say(fallbackCopy(address) ? "Link copied" : "Copy the address from the bar"); });
        }
        return say(fallbackCopy(address) ? "Link copied" : "Copy the address from the bar");
      }
    }
  });

  /* ---- figures count up on every new report ---- */
  function sequenceOpen() { return !!document.querySelector(".gen:not(.is-out)"); }

  function replay(strip) {
    var changed = [];
    strip.querySelectorAll("[data-countup]").forEach(function (element) {
      var final = element.getAttribute("data-final");
      if (element._shown !== final) {
        if (element._shown !== undefined) { changed.push(element); }
        element._shown = final;
      }
    });
    if (!changed.length) { return; }
    (function wait() {
      if (sequenceOpen()) { window.setTimeout(wait, 100); return; }
      changed.forEach(function (element) { NYC.countUp(element); });
    })();
  }

  var watched = null;
  function watchFigures() {
    var strip = document.getElementById("report-tiles");
    if (!strip || strip === watched || !NYC.countUp) { return; }
    watched = strip;
    strip.querySelectorAll("[data-countup]").forEach(function (element) { element._shown = element.getAttribute("data-final"); });
    new MutationObserver(function () { replay(strip); })
      .observe(strip, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-final"] });
  }

  /* ---- the typewriter placeholder ---- */
  var typing = { on: false, visible: true, preview: null };
  function startTypewriter(box) {
    if (typing.on || NYC.reducedMotion()) { return; }
    var input = box.querySelector(".search-input"), ghost = box.querySelector(".search-type");
    var lines = Array.prototype.map.call(document.querySelectorAll(".examples .example"), function (button) {
      return button.getAttribute("aria-label") || button.textContent;
    }).filter(Boolean);
    if (!input || !ghost || !lines.length) { return; }
    typing.on = true;
    var line = 0, count = 0, erasing = false, timer = 0;
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) { typing.visible = entries[0].isIntersecting; }).observe(box);
    }

    function idle() { return !input.value && document.activeElement !== input && typing.visible && !document.hidden; }
    function show() {
      box.classList.add("is-typing");
      ghost.textContent = lines[line].slice(0, count);
    }
    function hide() { box.classList.remove("is-typing"); ghost.textContent = ""; }

    function tick() {
      var delay = 60;
      if (typing.preview !== null) {
        count = 0; erasing = false; delay = 160;
      } else if (!idle()) {
        hide(); count = 0; erasing = false; delay = 400;
      } else {
        show();
        if (!erasing && count < lines[line].length) { count += 1; delay = 55 + Math.random() * 45; }
        else if (!erasing) { erasing = true; delay = 1700; }
        else if (count > 0) { count -= 1; delay = 26; }
        else { erasing = false; line = (line + 1) % lines.length; delay = 450; }
      }
      timer = window.setTimeout(tick, delay);
    }
    tick();
    return timer;
  }
  NYC.onMount(".search-box", startTypewriter);

  /* ---- the example preview ---- */
  function preview(button) {
    var box = document.querySelector(".search-box"), input = box && box.querySelector(".search-input"), ghost = box && box.querySelector(".search-type");
    if (!ghost || !input || input.value) { return; }
    typing.preview = button.getAttribute("aria-label") || button.textContent;
    ghost.textContent = typing.preview;
    box.classList.add("is-typing", "is-preview");
    ghost.classList.remove("is-fresh"); void ghost.offsetWidth; ghost.classList.add("is-fresh");
  }
  function endPreview() {
    var box = document.querySelector(".search-box"), ghost = box && box.querySelector(".search-type");
    typing.preview = null;
    if (box) { box.classList.remove("is-preview", "is-typing"); }
    if (ghost) { ghost.textContent = ""; }
  }
  document.addEventListener("pointerover", function (event) {
    var button = event.target.closest && event.target.closest(".examples .example");
    if (button) { preview(button); }
  });
  document.addEventListener("pointerout", function (event) {
    var button = event.target.closest && event.target.closest(".examples .example");
    if (button && !button.contains(event.relatedTarget)) { endPreview(); }
  });
  document.addEventListener("focusin", function (event) { if (event.target.matches && event.target.matches(".examples .example")) { preview(event.target); } });
  document.addEventListener("focusout", function (event) { if (event.target.matches && event.target.matches(".examples .example")) { endPreview(); } });

  /* ---- a link that names filters opens at the report ---- */
  var linked = /[?&](borough|from|to|type|size|factor|time|who|where)=/.test(window.location.search);
  if (linked) {
    NYC.onMount("#report", function () {
      var done = false;
      function go() {
        if (done) { return; }
        done = true;
        var section = document.getElementById("explore");
        if (section) { section.scrollIntoView({ block: "start", behavior: "instant" }); }
      }
      window.setTimeout(go, 600);
    });
  }

  function start() {
    new MutationObserver(watchFigures).observe(document.body, { childList: true, subtree: true });
    watchFigures();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
