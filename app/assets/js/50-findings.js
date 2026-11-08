/* Findings and Method behaviour, built on window.NYC (00-motion.js). Dash mounts the page after the first paint, so every
   piece is attached with NYC.onMount.

   Findings (#fd-list)
     - A row opens in place: the button toggles aria-expanded and the row's is-open class, and the stylesheet animates
       the height through grid rows. Opening a row also writes #rq3 to the address, so the row can be shared.
     - Filter chips (the "show" group and the "owner" group) fold the other rows away (is-away, inert) and the rest
       close the gap; the live count says how many are left.
     - #rq3 in the address (on load, on hashchange, on a click of such a link) opens that row and scrolls to it.

   Method
     - #md-journey carries a line of light through the stages as the reader scrolls and lights each stage it reaches.
     - #md-clean-filter hides the cleaning-log rows that do not contain every typed word. */
(function () {
  "use strict";

  var NYC = window.NYC;
  if (!NYC) { return; }

  function tick(element) {
    if (!element || NYC.reducedMotion()) { return; }
    element.classList.remove("is-tick");
    void element.offsetWidth;                     // restart the animation
    element.classList.add("is-tick");
  }

  // ---------- Findings ----------
  function rowsOf(list) { return Array.prototype.slice.call(list.querySelectorAll(".fd-row")); }

  function setOpen(row, open) {
    var toggle = row.querySelector(".fd-toggle");
    row.classList.toggle("is-open", open);
    if (toggle) { toggle.setAttribute("aria-expanded", open ? "true" : "false"); }
  }

  function keeps(row, state) {
    var show = state.show;
    var shown = show === "all" || row.getAttribute("data-reading") === show || row.getAttribute("data-scope") === show;
    return shown && (state.owner === "all" || row.getAttribute("data-owner") === state.owner);
  }

  function applyFilters(list, state) {
    var all = rowsOf(list), visible = 0;
    all.forEach(function (row) {
      var keep = keeps(row, state);
      row.classList.toggle("is-away", !keep);
      if (keep) { row.removeAttribute("inert"); visible += 1; } else { row.setAttribute("inert", ""); }
    });
    var count = document.getElementById("fd-count");
    if (count) {
      var text = visible === all.length ? "Showing all " + all.length + " questions"
        : "Showing " + visible + " of " + all.length + " questions";
      if (count.textContent !== text) { count.textContent = text; tick(count); }
    }
    var empty = document.getElementById("fd-empty");
    if (empty) { empty.hidden = visible > 0; }
    document.querySelectorAll(".fd-chip").forEach(function (chip) {
      var group = chip.getAttribute("data-group");
      chip.setAttribute("aria-pressed", chip.getAttribute("data-value") === state[group] ? "true" : "false");
    });
  }

  function addressRow(list) {
    var key = (window.location.hash || "").replace(/^#/, "").toLowerCase();
    if (!/^rq\d+$/.test(key)) { return null; }
    return list.querySelector('.fd-row[data-rq="' + key + '"]');
  }

  function mountFindings(list) {
    var state = { show: "all", owner: "all" };
    var root = document.getElementById("findings") || document;

    function openFromAddress(scroll) {
      var row = addressRow(list);
      if (!row) { return; }
      if (row.classList.contains("is-away")) { state.show = "all"; state.owner = "all"; applyFilters(list, state); }
      setOpen(row, true);
      if (scroll) { row.scrollIntoView({ block: "start", behavior: NYC.reducedMotion() ? "auto" : "smooth" }); }
    }

    function detach() {
      root.removeEventListener("click", onRootClick);
      document.removeEventListener("click", onLinkClick);
      window.removeEventListener("hashchange", onHash);
    }

    function writeAddress(row, open) {
      try {
        var current = (window.location.hash || "").toLowerCase();
        var mine = "#" + row.getAttribute("data-rq");
        if (!open && current !== mine) { return; }
        window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search + (open ? mine : ""));
      } catch (error) { /* the address stays as it was */ }
    }

    function onRootClick(event) {
      if (!list.isConnected) { detach(); return; }
      var target = event.target;
      if (!target || !target.closest) { return; }
      var toggle = target.closest(".fd-toggle");
      if (toggle && list.contains(toggle)) {
        var row = toggle.closest(".fd-row");
        var open = toggle.getAttribute("aria-expanded") !== "true";
        setOpen(row, open);
        writeAddress(row, open);
        return;
      }
      var chip = target.closest(".fd-chip");
      if (chip) {
        state[chip.getAttribute("data-group")] = chip.getAttribute("data-value");
        applyFilters(list, state);
        return;
      }
      if (target.closest("#fd-reset")) {
        state.show = "all"; state.owner = "all";
        applyFilters(list, state);
      }
    }

    // A link to a finding anywhere on the page (the Method chapter has one) opens it, even when the address is already that hash.
    function onLinkClick(event) {
      if (!list.isConnected) { detach(); return; }
      var link = event.target && event.target.closest && event.target.closest("a[href*='#rq']");
      if (link) { window.setTimeout(function () { openFromAddress(true); }, 0); }
    }

    function onHash() {
      if (!list.isConnected) { detach(); return; }
      openFromAddress(true);
    }

    root.addEventListener("click", onRootClick);
    document.addEventListener("click", onLinkClick);
    window.addEventListener("hashchange", onHash);
    applyFilters(list, state);
    openFromAddress(false);

    // The rest of the page keeps settling after a deep link loads, so the row is brought into view until it sits near the
    // top, for about two seconds, and the search stops at once if the reader scrolls.
    if (addressRow(list)) {
      var moved = false, tries = 0;
      ["wheel", "touchstart", "keydown"].forEach(function (name) {
        window.addEventListener(name, function () { moved = true; }, { once: true, passive: true });
      });
      var timer = window.setInterval(function () {
        var row = addressRow(list);
        tries += 1;
        if (!list.isConnected || moved || !row || tries > 14) { window.clearInterval(timer); return; }
        if (Math.abs(row.getBoundingClientRect().top - 96) > 60) { row.scrollIntoView({ block: "start" }); }
        else { window.clearInterval(timer); }
      }, 150);
    }
  }

  // ---------- Method ----------
  function mountJourney(journey) {
    var stages = Array.prototype.slice.call(journey.querySelectorAll(".md-stage"));
    // --p is written on the track alone (it holds only the line and its head): on the journey it would restyle every
    // stage on every scroll frame. The work runs once per frame, and only while the journey is near the window.
    var track = journey.querySelector(".md-track") || journey, shown = -1, ticking = false, near = true;
    function set(progress) {
      var text = progress.toFixed(4);
      if (text === shown) { return; }
      shown = text;
      track.style.setProperty("--p", text);
      stages.forEach(function (stage, index) {
        var lit = progress >= index / stages.length + (index ? 0.04 : -1);
        if (lit !== stage.classList.contains("is-lit")) { stage.classList.toggle("is-lit", lit); }
      });
    }
    if (NYC.reducedMotion()) { set(1); return; }
    journey.classList.add("is-live");
    function measure() {
      ticking = false;
      if (!journey.isConnected) { window.removeEventListener("scroll", update); window.removeEventListener("resize", update); return; }
      var height = window.innerHeight, box = journey.getBoundingClientRect();
      var progress = (height * 0.85 - box.top) / (box.height + height * 0.15);
      set(Math.max(0, Math.min(1, progress)));
    }
    function update() {
      if (ticking || !near) { return; }
      ticking = true;
      window.requestAnimationFrame(measure);
    }
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) { near = entries[0].isIntersecting; if (near) { update(); } },
                               { rootMargin: "25% 0px 25% 0px" }).observe(journey);
    }
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update, { passive: true });
    measure();
  }

  function mountCleaningFilter(input) {
    var body = document.getElementById("md-clean-body");
    var count = document.getElementById("md-clean-count");
    var empty = document.getElementById("md-clean-empty");
    if (!body) { return; }
    var lines = Array.prototype.slice.call(body.querySelectorAll("tr")).map(function (row) {
      return { row: row, text: row.textContent.toLowerCase() };
    });

    function filter() {
      var words = (input.value || "").toLowerCase().split(/\s+/).filter(Boolean);
      var visible = 0;
      lines.forEach(function (line) {
        var keep = words.every(function (word) { return line.text.indexOf(word) >= 0; });
        line.row.hidden = !keep;
        if (keep) { visible += 1; }
      });
      if (count) {
        var text = visible === lines.length ? "Showing all " + lines.length + " rules"
          : "Showing " + visible + " of " + lines.length + " rules";
        if (count.textContent !== text) { count.textContent = text; tick(count); }
      }
      if (empty) { empty.hidden = visible > 0; }
    }

    input.addEventListener("input", filter);
    filter();
  }

  NYC.onMount("#fd-list", mountFindings);
  NYC.onMount("#md-journey", mountJourney);
  NYC.onMount("#md-clean-filter", mountCleaningFilter);
})();
