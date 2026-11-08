/* The two tools: "Your block" (#block, ids bk-) and "Try to break the result" (#lab, ids sc-).

   Everything is drawn from JSON the server sends (/api/block/*, /api/scenario); no number is typed here.
   All text from the data goes in through textContent, never as markup. Both tools keep their state in the
   address bar (?site=, ?zip=, ?scenario=) so any view can be shared, and every change of a figure is
   animated unless the reader asked for less motion. */
(function () {
  "use strict";

  var NYC = window.NYC || (window.NYC = {});
  var MINUS = "−";
  var SVG_NS = "http://www.w3.org/2000/svg";

  function reduced() { return NYC.reducedMotion ? NYC.reducedMotion() : false; }
  function el(tag, cls, text, attrs) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    if (attrs) { Object.keys(attrs).forEach(function (name) { node.setAttribute(name, attrs[name]); }); }
    return node;
  }
  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } return node; }
  function num(value) { return Number(value).toLocaleString("en-US"); }
  function signed(value, digits) {
    var text = Math.abs(value).toFixed(digits === undefined ? 1 : digits);
    if (parseFloat(text) === 0) { return text; }
    return (value > 0 ? "+" : MINUS) + text;
  }
  function ordinal(value) {
    var n = Math.round(value), tail = n % 100;
    var suffix = (tail >= 11 && tail <= 13) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
    return n + suffix;
  }
  function frame(fn) { return window.setTimeout(fn, 60); }       // a timer, not rAF: rAF stops in a hidden tab

  /* Tween a number. Snaps when motion is off or the tab is hidden. Returns a cancel function. */
  function tween(from, to, ms, write, done) {
    if (reduced() || document.hidden || !isFinite(from) || from === to) { write(to); if (done) { done(); } return function () {}; }
    var start = null, stopped = false;
    function step(now) {
      if (stopped) { return; }
      if (start === null) { start = now; }
      var t = Math.min(1, (now - start) / ms);
      write(from + (to - from) * (NYC.easeOut ? NYC.easeOut(t) : t));
      if (t < 1) { window.requestAnimationFrame(step); } else { write(to); if (done) { done(); } }
    }
    window.requestAnimationFrame(step);
    return function () { stopped = true; };
  }

  /* The address bar: replaceState keeps Back for the page, and the query carries the views. */
  function getParam(name) { try { return new URLSearchParams(window.location.search).get(name); } catch (e) { return null; } }
  function setParams(changes) {
    try {
      var url = new URL(window.location.href);
      Object.keys(changes).forEach(function (name) {
        if (changes[name] === null || changes[name] === "") { url.searchParams.delete(name); } else { url.searchParams.set(name, changes[name]); }
      });
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    } catch (e) { /* a sandboxed frame may refuse; the tool still works */ }
  }
  function copyLink(button, status) {
    var text = window.location.href, said = "Link copied.";
    function fallback() {
      var area = el("textarea", "visually-hidden", text);
      document.body.appendChild(area); area.select();
      try { document.execCommand("copy"); } catch (e) { said = "Select the address bar to copy the link."; }
      document.body.removeChild(area);
    }
    function announce() {
      status.textContent = said;
      button.classList.add("is-done");
      window.setTimeout(function () { button.classList.remove("is-done"); }, 1600);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text).then(announce, function () { fallback(); announce(); }); }
    else { fallback(); announce(); }
  }
  function getJSON(url, signal) {
    return fetch(url, { signal: signal, headers: { Accept: "application/json" } }).then(function (response) {
      if (response.status === 404) { return null; }
      if (!response.ok) { throw new Error("status " + response.status); }
      return response.json();
    });
  }
  function scrollTo(node) { node.scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "start" }); }
  function inView(node) { var box = node.getBoundingClientRect(); return box.top >= 0 && box.top < window.innerHeight * 0.6; }
  /* Side by side: the tools show their answer in a panel that stays in view, so nothing needs to scroll to it. */
  var sideBySide = window.matchMedia("(min-width: 1100px)");
  function wide() { return sideBySide.matches; }

  /* ================================================================== YOUR BLOCK */

  function initBlock(root) {
    var config = {};
    try { config = JSON.parse(root.getAttribute("data-config") || "{}"); } catch (e) { config = {}; }
    var search = document.getElementById("bk-search"), record = document.getElementById("bk-record"), ranked = document.getElementById("bk-ranked");
    if (!search || !record || !ranked) { return; }
    var years = config.baselineYears || [], span = years.length === 2 ? years[0] + " to " + years[1] : "the baseline years";
    var buffer = config.bufferM;
    var openSeq = 0, openController = null;

    /* ---- the search field ---- */
    var field = el("div", "bk-field");
    var label = el("label", "bk-label", "Find a place", { for: "bk-q" });
    var ring = el("div", "bk-ring");
    var input = el("input", "bk-input", null, {
      id: "bk-q", type: "search", role: "combobox", autocomplete: "off", spellcheck: "false", maxlength: "64",
      "aria-expanded": "false", "aria-controls": "bk-results", "aria-autocomplete": "list",
      placeholder: "A ZIP code, a project name or a borough" });
    var list = el("ul", "bk-results", null, { id: "bk-results", role: "listbox", "aria-label": "Matches", hidden: "" });
    var status = el("p", "visually-hidden", "", { role: "status", "aria-live": "polite" });
    ring.appendChild(input);
    ring.appendChild(el("span", "bk-ring-light", null, { "aria-hidden": "true" }));   // the arc that turns on focus (50-tools.css)
    field.appendChild(label); field.appendChild(ring); field.appendChild(list); field.appendChild(status);
    search.appendChild(field);

    var results = [], active = -1, timer = null, searchSeq = 0;
    function closeList() { list.hidden = true; input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant"); active = -1; }
    function setActive(index) {
      active = index;
      Array.prototype.forEach.call(list.children, function (node, i) {
        node.classList.toggle("is-active", i === index);
        node.setAttribute("aria-selected", i === index ? "true" : "false");
      });
      if (index >= 0 && list.children[index]) {
        input.setAttribute("aria-activedescendant", list.children[index].id);
        list.children[index].scrollIntoView({ block: "nearest" });
      } else { input.removeAttribute("aria-activedescendant"); }
    }
    function drawResults(data) {
      results = data.results || [];
      clear(list);
      if (!data.query) { closeList(); return; }
      if (!results.length) {
        list.appendChild(el("li", "bk-none", "No match. Try a ZIP code, part of a project name or a borough.", { role: "presentation" }));
        status.textContent = "No match.";
      } else {
        results.forEach(function (item, index) {
          var option = el("li", "bk-option", null, { id: "bk-opt-" + index, role: "option", "aria-selected": "false" });
          option.style.setProperty("--i", index);
          option.appendChild(el("span", "bk-option-label", item.label));
          option.appendChild(el("span", "bk-option-detail", item.detail));
          option.addEventListener("mousedown", function (event) { event.preventDefault(); choose(item); });
          option.addEventListener("mousemove", function () { if (active !== index) { setActive(index); } });
          list.appendChild(option);
        });
        status.textContent = results.length + (results.length === 1 ? " match" : " matches") + (data.n_sites > results.length ? " shown of " + num(data.n_sites) + " sites" : "") + ".";
      }
      list.hidden = false; input.setAttribute("aria-expanded", "true"); active = -1;
    }
    function runSearch() {
      var query = input.value.trim(), seq = ++searchSeq;
      if (!query) { closeList(); return; }
      getJSON("/api/block/search?q=" + encodeURIComponent(query)).then(function (data) {
        if (seq === searchSeq && data) { drawResults(data); }
      }).catch(function () { status.textContent = "Search is unavailable. Try again."; });
    }
    input.addEventListener("input", function () { window.clearTimeout(timer); timer = window.setTimeout(runSearch, 140); });
    input.addEventListener("focus", function () { if (input.value.trim() && results.length) { list.hidden = false; input.setAttribute("aria-expanded", "true"); } });
    input.addEventListener("blur", function () { window.setTimeout(closeList, 120); });
    input.addEventListener("keydown", function (event) {
      var count = list.querySelectorAll("[role=option]").length;
      if (event.key === "ArrowDown") { event.preventDefault(); if (list.hidden && results.length) { list.hidden = false; } if (count) { setActive((active + 1) % count); } }
      else if (event.key === "ArrowUp") { event.preventDefault(); if (count) { setActive(active <= 0 ? count - 1 : active - 1); } }
      else if (event.key === "Enter") {
        event.preventDefault();
        if (active >= 0 && results[active]) { choose(results[active]); }
        else if (results.length && !list.hidden) { choose(results[0]); }
        else { window.clearTimeout(timer); runSearch(); }
      } else if (event.key === "Escape") { if (!list.hidden) { event.preventDefault(); closeList(); } }
    });
    function choose(item) {
      closeList();
      if (item.kind === "site") { input.value = item.label; openSite(item.id, true); }
      else if (item.kind === "zip") { input.value = item.label; opened = true; openZip(item.id, true); }
      else { input.value = item.label; ranking.borough = item.id; ranking.offset = 0; syncFilters(); loadRanked(false); setParams({ site: null, zip: null }); clearRecord(); scrollTo(ranked); }
    }

    /* ---- the record ---- */
    function clearRecord() { openSeq++; clear(record); record.classList.remove("is-open"); drawWelcome(); }
    function drawWelcome() {
      var box = el("div", "bk-record-inner bk-welcome");
      box.appendChild(el("p", "bk-welcome-kicker", "The chosen site"));
      box.appendChild(el("p", "bk-welcome-title", "Pick a site from the list, or search for one"));
      box.appendChild(el("p", "bk-text", "Its record opens here: where its streets rank in the borough, the crashes around it before it was built, and the sites near it."));
      clear(record); record.appendChild(box);
    }
    var currentSite = null;
    function markRow() {
      listEl.querySelectorAll(".bk-row").forEach(function (row) {
        var mine = currentSite !== null && row.getAttribute("data-site") === String(currentSite);
        row.classList.toggle("is-selected", mine);
        if (mine) { row.setAttribute("aria-current", "true"); } else { row.removeAttribute("aria-current"); }
      });
    }
    function show(node, quiet) {
      clear(record); record.appendChild(node); record.classList.add("is-open");
      node.classList.add("bk-enter");
      record.scrollTop = 0;
      if (!quiet && !wide() && !inView(record)) { scrollTo(record); }
      frame(function () { node.classList.add("is-on"); node.querySelectorAll("[data-travel]").forEach(travel); });
    }
    function travel(node) {                                     // a light that runs from the left edge to its place
      var to = node.getAttribute("data-travel");
      if (reduced()) { node.style.setProperty("--at", to); return; }
      node.style.setProperty("--at", "0"); void node.offsetWidth; node.style.setProperty("--at", to);
    }
    function failure(message) {
      var box = el("div", "bk-record-inner bk-miss");
      box.appendChild(el("p", "bk-miss-text", message));
      show(box);
    }
    function fact(labelText, value, count) {
      var item = el("div", "bk-fact");
      item.appendChild(el("dt", "bk-fact-label", labelText));
      var dd = el("dd", "bk-fact-value", value);
      if (count !== undefined && count !== null) { dd.setAttribute("data-countup", String(count)); dd.setAttribute("data-final", value); }
      item.appendChild(dd);
      return item;
    }
    function section(titleText, className) {
      var box = el("section", "bk-part " + (className || ""));
      box.appendChild(el("h4", "bk-part-title", titleText));
      return box;
    }
    function siteLinks(sites, openFn, extra) {
      var ul = el("ul", "bk-links");
      sites.forEach(function (item, index) {
        var link = el("a", "bk-link", null, { href: "?site=" + item.site_id + "#block" });
        link.style.setProperty("--i", index);
        link.appendChild(el("span", "bk-link-name", item.project));
        link.appendChild(el("span", "bk-link-meta", extra(item)));
        link.addEventListener("click", function (event) { event.preventDefault(); openFn(item.site_id, true); });
        var li = el("li"); li.appendChild(link); ul.appendChild(li);
      });
      return ul;
    }
    function actions(extraLink) {
      var row = el("div", "bk-actions");
      var copy = el("button", "button button-secondary", "Copy link to this view", { type: "button" });
      var note = el("span", "visually-hidden", "", { role: "status", "aria-live": "polite" });
      copy.addEventListener("click", function () { copyLink(copy, note); });
      row.appendChild(copy); row.appendChild(note);
      if (extraLink) { row.appendChild(extraLink); }
      return row;
    }

    function stripPart(r) {
      var part = section("Where its streets rank in " + r.borough);
      if (!r.has_baseline || r.percentile === null) {
        part.appendChild(el("p", "bk-text", "The records give no crash baseline for this site, so it cannot be placed among the streets of " + r.borough + "."));
        return part;
      }
      var strip = r.strip, shares = strip.shares, top = Math.max.apply(null, shares) || 1;
      var rail = el("div", "bk-strip", null, { role: "img",
        "aria-label": "Streets of " + r.borough + " from the quietest to the most crash-heavy. This site is at the " + ordinal(r.percentile) + " percentile; the 50th, a typical street point, is marked in the middle." });
      var bars = el("div", "bk-bars");
      shares.forEach(function (share, index) {
        var bar = el("span", "bk-bar");
        bar.style.setProperty("--h", (100 * share / top).toFixed(1) + "%");
        bar.style.setProperty("--i", index);
        bar.style.setProperty("--heat", (index / (shares.length - 1)).toFixed(3));
        bars.appendChild(bar);
      });
      rail.appendChild(bars);
      rail.appendChild(el("span", "bk-mid"));
      rail.appendChild(el("span", "bk-mid-label", "50th: a typical street point"));
      var light = el("span", "bk-light", null, { "data-travel": r.percentile.toFixed(1) });
      light.appendChild(el("span", "bk-light-tag", ordinal(r.percentile)));
      rail.appendChild(light);
      part.appendChild(rail);
      var ends = el("div", "bk-ends");
      ends.appendChild(el("span", null, "Quietest streets")); ends.appendChild(el("span", null, "Most crash-heavy"));
      part.appendChild(ends);
      part.appendChild(el("p", "bk-text", "This site's streets sit at the " + ordinal(r.percentile) + " percentile of " + r.borough +
        ". The bars show where the borough's " + num(strip.n_sites) + " located sites fall" +
        (strip.share_above_50 !== null ? "; " + Math.round(strip.share_above_50) + "% of them are above the 50th, because sites were built where crashes already happen." : ".")));
      return part;
    }

    function versusPart(r) {
      var part = section("Crashes before it was built", "bk-versus");
      if (!r.has_baseline || r.baseline_crashes === null) { part.appendChild(el("p", "bk-text", "No baseline crash count is recorded for this site.")); return part; }
      var big = el("p", "bk-big is-crash", num(r.baseline_crashes), { "data-countup": String(r.baseline_crashes), "data-final": num(r.baseline_crashes) });
      part.appendChild(big);
      part.appendChild(el("p", "bk-big-label", "injury crashes within " + buffer + " m, " + span));
      var median = r.borough_median, maxValue = Math.max(r.baseline_crashes, median || 0, 1);
      var bars = el("div", "bk-vs");
      [["This site", r.baseline_crashes, "is-site"], ["Median site in " + r.borough, median, "is-median"]].forEach(function (row) {
        if (row[1] === null || row[1] === undefined) { return; }
        var line = el("div", "bk-vs-row");
        line.appendChild(el("span", "bk-vs-name", row[0]));
        var track = el("span", "bk-vs-track"); var fill = el("span", "bk-vs-fill " + row[2]);
        fill.style.setProperty("--w", (100 * row[1] / maxValue).toFixed(1) + "%");
        track.appendChild(fill); line.appendChild(track);
        line.appendChild(el("span", "bk-vs-num", num(Math.round(row[1]))));
        bars.appendChild(line);
      });
      part.appendChild(bars);
      if (median) {
        var diff = r.baseline_crashes - median;
        part.appendChild(el("p", "bk-text", diff === 0 ? "That is the same as the median site in " + r.borough + "."
          : "That is " + num(Math.abs(Math.round(diff))) + (diff > 0 ? " more" : " fewer") + " than the median site in " + r.borough + " (" + num(Math.round(median)) + "). These crashes happened before construction; they describe the streets, not the building."));
      }
      return part;
    }

    function eventPart(r) {
      var ev = r.event;
      if (!ev) {
        var none = section("Before and after");
        none.appendChild(el("p", "bk-text", "This site is not in the before-and-after comparison, so there is no before and after to show."));
        return none;
      }
      var tested = ev.role === "tested";
      var part = section(tested ? "Before and after it opened" : "Used as a comparison site");
      var top = Math.max.apply(null, ev.years.map(function (y) { return y.count; }).concat([1]));
      var chart = el("div", "bk-years", null, { role: "img",
        "aria-label": "Injury crashes within " + buffer + " m by year: " + ev.years.map(function (y) { return y.year + ", " + y.count; }).join("; ") + "." });
      ev.years.forEach(function (y, index) {
        var col = el("div", "bk-year" + (y.year < ev.cohort ? " is-before" : y.year > ev.cohort ? " is-after" : " is-mid"));
        col.style.setProperty("--i", index);
        col.appendChild(el("span", "bk-year-count", String(y.count)));
        var bar = el("span", "bk-year-bar"); bar.style.setProperty("--h", (100 * y.count / top).toFixed(1) + "%");
        col.appendChild(bar); col.appendChild(el("span", "bk-year-label", String(y.year)));
        chart.appendChild(col);
      });
      part.appendChild(chart);
      var window_ = config.window || 3;
      if (tested) {
        part.appendChild(el("p", "bk-text", "Completed in " + ev.cohort + ": " + ev.before + " injury crashes in the " + window_ + " years before and " + ev.after + " in the " + window_ + " years after. One site is too noisy to conclude anything; counts this small rise and fall by chance. Only the pooled result across " + num(config.testedSites || 0) + " sites says anything, and it cannot be told from no change."));
      } else {
        part.appendChild(el("p", "bk-text", "This site was not yet completed when the window around " + ev.cohort + " ended, so its counts stand in for \"no new building\". One site is too noisy to conclude anything."));
      }
      return part;
    }

    function renderSite(r) {
      var box = el("article", "bk-record-inner", null, { "aria-labelledby": "bk-name" });
      var head = el("header", "bk-head");
      head.appendChild(el("h3", "bk-name", r.project, { id: "bk-name" }));
      var facts = el("dl", "bk-facts");
      facts.appendChild(fact("Borough", r.borough));
      facts.appendChild(fact("ZIP", r.zip));
      facts.appendChild(fact("Type", r.type));
      facts.appendChild(fact("Units", num(r.units), r.units));
      facts.appendChild(fact("Completed", r.completion_year === null ? "Not recorded" : String(r.completion_year)));
      head.appendChild(facts);
      box.appendChild(head);
      var body = el("div", "bk-body");
      body.appendChild(stripPart(r)); body.appendChild(versusPart(r)); body.appendChild(eventPart(r));
      box.appendChild(body);
      var nearby = section("Nearby sites within " + r.buffer_m + " m", "bk-nearby");
      if (r.nearby.length) {
        nearby.appendChild(siteLinks(r.nearby, openSite, function (item) { return item.distance_m + " m, " + num(item.units) + " units, " + item.type; }));
        if (r.nearby_total > r.nearby.length) { nearby.appendChild(el("p", "aside", "and " + num(r.nearby_total - r.nearby.length) + " more nearby.")); }
      } else { nearby.appendChild(el("p", "bk-text", "No other located site is within " + r.buffer_m + " m.")); }
      box.appendChild(nearby);
      var lab = el("a", "button button-primary", "Try breaking the result for sites like this", { href: (r.event && r.event.scenario_link) || "#lab" });
      lab.addEventListener("click", function (event) {
        var target = (r.event && r.event.scenario_link) || "#lab";
        if (target.indexOf("?scenario=") === 0) { event.preventDefault(); NYC.setScenario({ sites: "preservation" }); }
      });
      box.appendChild(actions(lab));
      return box;
    }

    function renderZip(r) {
      var box = el("article", "bk-record-inner", null, { "aria-labelledby": "bk-name" });
      var head = el("header", "bk-head");
      head.appendChild(el("h3", "bk-name", "ZIP " + r.zip, { id: "bk-name" }));
      var facts = el("dl", "bk-facts");
      facts.appendChild(fact("Borough", r.borough));
      facts.appendChild(fact("Located sites", num(r.n_sites), r.n_sites));
      if (r.in_panel) { facts.appendChild(fact("Homes completed", num(r.total_units), r.total_units)); facts.appendChild(fact("Injury crashes", num(r.total_injury), r.total_injury)); }
      head.appendChild(facts); box.appendChild(head);
      var body = el("div", "bk-body");
      if (r.in_panel) {
        var part = section("Year by year in this ZIP");
        var top = Math.max.apply(null, r.years.map(function (y) { return y.injury; }).concat([1]));
        var chart = el("div", "bk-years", null, { role: "img",
          "aria-label": "Injury crashes by year in ZIP " + r.zip + ": " + r.years.map(function (y) { return y.year + ", " + y.injury; }).join("; ") + "." });
        r.years.forEach(function (y, index) {
          var col = el("div", "bk-year is-before"); col.style.setProperty("--i", index);
          col.appendChild(el("span", "bk-year-count", String(y.injury)));
          var bar = el("span", "bk-year-bar"); bar.style.setProperty("--h", (100 * y.injury / top).toFixed(1) + "%");
          col.appendChild(bar); col.appendChild(el("span", "bk-year-label", String(y.year)));
          chart.appendChild(col);
        });
        part.appendChild(chart);
        part.appendChild(el("p", "bk-text", "Injury crashes here are higher than in " + Math.round(r.injury_percentile) + "% of the other " + (r.n_panel_zips - 1) + " ZIPs in the panel, and homes completed are higher than in " + Math.round(r.units_percentile) + "%. Bars show injury crashes per year."));
        body.appendChild(part);
        if (r.imputed_share !== null && r.imputed_share !== undefined) {
          var caveat = section("A caveat about the ZIP");
          caveat.appendChild(el("p", "bk-text", num(r.imputed_injury) + " of the " + num(r.total_injury) + " injury crashes here (" + r.imputed_share.toFixed(0) + "%) had their ZIP recovered from the crash location rather than recorded; across the city it is " + r.city_imputed_share.toFixed(0) + "%."));
          body.appendChild(caveat);
        }
      } else {
        var out = section("Crash counts");
        out.appendChild(el("p", "bk-text", "This ZIP is not in the ZIP crash panel, so there are no yearly counts for it. Its located sites are listed below."));
        body.appendChild(out);
      }
      box.appendChild(body);
      var sites = section("Sites in this ZIP", "bk-nearby");
      if (r.sites.length) {
        sites.appendChild(siteLinks(r.sites, openSite, function (item) { return num(item.units) + " units, " + item.type; }));
        if (r.n_sites > r.sites.length) { sites.appendChild(el("p", "aside", "and " + num(r.n_sites - r.sites.length) + " more in this ZIP.")); }
      } else { sites.appendChild(el("p", "bk-text", "No located site is in this ZIP.")); }
      box.appendChild(sites); box.appendChild(actions());
      return box;
    }

    function open(url, render, params, missing, quiet) {
      var seq = ++openSeq;
      if (openController) { openController.abort(); }
      openController = typeof AbortController === "function" ? new AbortController() : null;
      record.classList.add("is-loading");
      return getJSON(url, openController ? openController.signal : undefined).then(function (data) {
        if (seq !== openSeq) { return; }
        record.classList.remove("is-loading");
        if (!data) { failure(missing); setParams({ site: null, zip: null }); return; }
        currentSite = params.site ? params.site : null; markRow();
        show(render(data), quiet); if (!quiet) { setParams(params); }
      }).catch(function (error) {
        if (error && error.name === "AbortError") { return; }
        if (seq === openSeq) { record.classList.remove("is-loading"); failure("The record could not be loaded. Try again."); }
      });
    }
    function openSite(id, fromUser, quiet) {
      if (fromUser) { setParams({ zip: null }); }
      return open("/api/block/site?id=" + encodeURIComponent(id), renderSite, { site: String(id), zip: null }, "No located site has that id. Confidential records cannot be looked up.", quiet);
    }
    function openZip(code, fromUser) {
      if (fromUser) { setParams({ site: null }); }
      return open("/api/block/zip?zip=" + encodeURIComponent(code), renderZip, { zip: String(code), site: null }, "That ZIP code is not in the records.");
    }

    /* ---- the ranked list ---- */
    var ranking = { borough: "all", type: "all", sort: "baseline", dir: "desc", offset: 0, rows: 0 };
    /* Four equal cells: two menus (many choices) above two pill groups (few choices). */
    var controls = el("div", "bk-filters");
    var boroughPick = NYC.picker({ id: "bk-borough", label: "Borough", value: ranking.borough,
      options: [["all", "All boroughs"]].concat((config.boroughs || []).map(function (name) { return [name, name]; })),
      onChange: function (v) { ranking.borough = v; loadRanked(false); } });
    var sortPick = NYC.picker({ id: "bk-sort", label: "Sort by", value: ranking.sort,
      options: [["baseline", "Crashes nearby"], ["percentile", "Percentile in borough"], ["units", "Units"], ["completion", "Completion year"], ["project", "Project name"]],
      onChange: function (v) { ranking.sort = v; ranking.dir = v === "project" ? "asc" : "desc"; loadRanked(false); } });
    var typeSeg = NYC.segmented({ id: "bk-type", label: "Type", value: ranking.type, cols: 3,
      options: [["all", "All"], ["New Construction", "New"], ["Preservation", "Preservation"]],
      onChange: function (v) { ranking.type = v; loadRanked(false); } });
    var dirSeg = NYC.segmented({ id: "bk-dir", label: "Order", value: ranking.dir, cols: 2,
      options: [["desc", "Highest first"], ["asc", "Lowest first"]],
      onChange: function (v) { ranking.dir = v; loadRanked(false); } });
    [boroughPick, sortPick, typeSeg, dirSeg].forEach(function (control) { controls.appendChild(control.el); });
    var listEl = el("ol", "bk-rank-list", null, { "aria-label": "Sites on the most crash-heavy streets" });
    var foot = el("div", "bk-rank-foot");
    var total = el("p", "bk-total", "", { role: "status", "aria-live": "polite" });
    var more = el("button", "button button-primary", "Show 25 more", { type: "button" });
    var csv = el("a", "button button-secondary", "Download CSV", { href: "/block/ranked.csv", download: "sites_on_crash_heavy_streets.csv" });
    var buttons = el("div", "bk-rank-buttons"); buttons.appendChild(more); buttons.appendChild(csv);
    foot.appendChild(total); foot.appendChild(buttons);
    /* Above the rows: how many sites the filters leave, counted as it changes, and the filters in words. */
    var summary = el("p", "bk-summary", null, { "aria-hidden": "true" });
    var summaryNum = el("span", "bk-summary-num", "0"), summaryText = el("span", "bk-summary-text", "");
    summary.appendChild(summaryNum); summary.appendChild(summaryText);
    var shownTotal = 0, cancelTotal = null;
    function drawSummary(totalRows) {
      if (cancelTotal) { cancelTotal(); }
      cancelTotal = tween(shownTotal, totalRows, 650, function (v) { summaryNum.textContent = num(Math.round(v)); });
      shownTotal = totalRows;
      var parts = [ranking.borough === "all" ? "all boroughs" : ranking.borough,
                   ranking.type === "all" ? "both types" : ranking.type.toLowerCase()];
      summaryText.textContent = (totalRows === 1 ? " site" : " sites") + " · " + parts.join(" · ");
      summary.classList.remove("is-new"); void summary.offsetWidth; summary.classList.add("is-new");
    }
    ranked.appendChild(controls); ranked.appendChild(summary); ranked.appendChild(listEl); ranked.appendChild(foot);

    function query(extra) {
      var parts = ["borough=" + encodeURIComponent(ranking.borough), "type=" + encodeURIComponent(ranking.type),
        "sort=" + ranking.sort, "dir=" + ranking.dir];
      return parts.concat(extra || []).join("&");
    }
    function syncFilters() {
      boroughPick.set(ranking.borough); sortPick.set(ranking.sort); typeSeg.set(ranking.type); dirSeg.set(ranking.dir);
      csv.setAttribute("href", "/block/ranked.csv?" + query());
    }
    function rankRow(row, index) {
      var li = el("li", "bk-row", null, { "data-site": String(row.site_id) });
      li.style.setProperty("--i", index);
      // A bar behind the row: this site's crashes against the most on the list, so the ranking reads at a glance.
      li.style.setProperty("--w", ranking.top ? Math.max(0.02, Math.min(1, row.baseline_crashes / ranking.top)).toFixed(3) : "0");
      li.appendChild(el("span", "bk-row-rank", String(row.rank)));
      var main = el("div", "bk-row-main");
      var link = el("a", "bk-row-name", row.project, { href: "?site=" + row.site_id + "#block" });
      link.addEventListener("click", function (event) { event.preventDefault(); openSite(row.site_id, true); });
      main.appendChild(link);
      main.appendChild(el("span", "bk-row-meta", row.borough + " " + row.zip + " · " + row.type + " · " + num(row.units) + " units · " + (row.completion_year === null ? "completion not recorded" : "completed " + row.completion_year)));
      li.appendChild(main);
      var figure = el("div", "bk-row-fig");
      figure.appendChild(el("span", "bk-row-num", num(row.baseline_crashes)));
      figure.appendChild(el("span", "bk-row-unit", ordinal(row.percentile) + " percentile"));
      li.appendChild(figure);
      return li;
    }
    var rankSeq = 0, opened = false;
    function loadRanked(append) {
      var seq = ++rankSeq;
      if (!append) { ranking.offset = 0; }
      syncFilters();
      ranked.classList.add("is-loading");
      return getJSON("/api/block/ranked?" + query(["offset=" + ranking.offset, "limit=25"])).then(function (data) {
        if (seq !== rankSeq || !data) { return; }
        ranked.classList.remove("is-loading");
        if (!append) {
          clear(listEl); ranking.rows = 0;
          ranking.top = data.rows.reduce(function (top, row) { return Math.max(top, row.baseline_crashes || 0); }, 0);
        }
        data.rows.forEach(function (row, index) { listEl.appendChild(rankRow(row, index)); });
        markRow();
        // On arrival the record panel shows the top site, so the panel is never empty and the reader sees what a
        // record holds before choosing. The address is left alone: nothing was chosen yet.
        if (!append && !opened && data.rows.length) { opened = true; openSite(data.rows[0].site_id, false, true); }
        ranking.rows += data.rows.length; ranking.offset = ranking.rows;
        total.textContent = data.total ? "Showing " + num(ranking.rows) + " of " + num(data.total) + " sites with a crash baseline." : "No site matches these filters.";
        if (!append) { drawSummary(data.total || 0); }
        more.hidden = !data.has_more;
        more.textContent = "Show " + Math.min(25, data.total - ranking.rows) + " more";
      }).catch(function () { ranked.classList.remove("is-loading"); total.textContent = "The list could not be loaded. Try again."; });
    }
    more.addEventListener("click", function () { loadRanked(true); });
    syncFilters();
    loadRanked(false);

    /* ---- a shared link opens its record ---- */
    var siteParam = getParam("site"), zipParam = getParam("zip");
    var started = null;
    drawWelcome();
    if (siteParam) { opened = true; started = openSite(siteParam, false); }
    else if (zipParam) { opened = true; started = openZip(zipParam, false); }
    if (started && !window.location.hash && !getParam("scenario")) { started.then(function () { scrollTo(root); }); }
  }

  /* ================================================================== TRY TO BREAK THE RESULT */

  function initLab(root) {
    var reference = {}, options = {};
    try { reference = JSON.parse(root.getAttribute("data-reference") || "{}"); options = JSON.parse(root.getAttribute("data-options") || "{}"); } catch (e) { return; }
    var defaults = reference.defaults || {}, published = reference.published || {};
    var KEYS = Object.keys(defaults);
    var valueEl = document.getElementById("sc-value"), rangeEl = document.getElementById("sc-range"), tagEl = document.getElementById("sc-tag");
    var axisEl = document.getElementById("sc-axis"), sentenceEl = document.getElementById("sc-sentence"), emptyEl = document.getElementById("sc-empty");
    var statusEl = document.getElementById("sc-status"), countEl = document.getElementById("sc-count"), noteEl = document.getElementById("sc-count-note");
    var historyEl = document.getElementById("sc-history"), backBtn = document.getElementById("sc-back"), resetBtn = document.getElementById("sc-reset"), copyBtn = document.getElementById("sc-copy");
    if (!valueEl || !axisEl || !historyEl) { return; }

    /* the axis: fixed to the largest published interval, zero in the middle */
    var reach = Math.max.apply(null, (reference.rows || []).map(function (row) { return Math.max(Math.abs(row.low), Math.abs(row.high)); }).concat([Math.abs(published.low || 0), Math.abs(published.high || 0), 20]));
    var domain = Math.ceil(reach * 1.12 / 20) * 20;
    function pos(value) { return Math.max(0, Math.min(100, 50 + 50 * value / domain)); }
    function place(bar, low, high) {
      var left = pos(low), right = pos(high);
      bar.style.left = left + "%"; bar.style.width = Math.max(0.6, right - left) + "%";
      bar.classList.toggle("clip-l", low < -domain); bar.classList.toggle("clip-r", high > domain);
    }
    var plot = el("div", "sc-plot");
    var rowNow = el("div", "sc-row"), rowRef = el("div", "sc-row");
    rowNow.appendChild(el("span", "sc-row-name", "This scenario")); rowRef.appendChild(el("span", "sc-row-name", "Published result"));
    var trackNow = el("div", "sc-track"), trackRef = el("div", "sc-track");
    var ghost = el("span", "sc-bar sc-ghost"), barNow = el("span", "sc-bar sc-now"), dotNow = el("span", "sc-dot");
    var barRef = el("span", "sc-bar sc-ref"), dotRef = el("span", "sc-dot sc-dot-ref");
    ghost.style.opacity = "0";
    trackNow.appendChild(ghost); trackNow.appendChild(barNow); trackNow.appendChild(dotNow);
    trackRef.appendChild(barRef); trackRef.appendChild(dotRef);
    rowNow.appendChild(trackNow); rowRef.appendChild(trackRef);
    var zero = el("span", "sc-zero"); zero.appendChild(el("span", "sc-zero-label", "0, no change"));
    var ticks = el("div", "sc-ticks");
    for (var t = -domain; t <= domain; t += domain / 2) { var tick = el("span", "sc-tick", t === 0 ? "" : signed(t, 0) + "%"); tick.style.left = pos(t) + "%"; ticks.appendChild(tick); }
    plot.appendChild(rowNow); plot.appendChild(rowRef); plot.appendChild(zero); plot.appendChild(ticks);
    axisEl.setAttribute("role", "img");
    axisEl.appendChild(plot);
    place(barRef, published.low, published.high); dotRef.style.setProperty("--at", pos(published.estimate));

    /* Every scenario tried leaves a faint mark on the axis, so the reader sees how far the answer has wandered. */
    var trail = [], TRAIL = 12;
    function drawTrail(result) {
      if (result.status !== "ok") { return; }
      var mark = el("span", "sc-trail" + (result.excludes_zero ? " is-excl" : ""));
      mark.style.left = pos(result.estimate) + "%";
      trackNow.insertBefore(mark, trackNow.firstChild);
      trail.push(mark);
      while (trail.length > TRAIL) { trail.shift().remove(); }
      trail.forEach(function (node, k) { node.style.opacity = (0.15 + 0.5 * (k + 1) / trail.length).toFixed(2); });
    }

    /* On a narrow screen the answer sits above the choices; a small readout floats at the foot while it is out of view. */
    var floatEl = document.getElementById("sc-float"), panelEl = root.querySelector(".sc-panel"), labInView = false, panelInView = true;
    function drawFloat(result) {
      if (!floatEl) { return; }
      clear(floatEl);
      floatEl.appendChild(el("span", "sc-float-label", "This scenario"));
      floatEl.appendChild(el("span", "sc-float-value" + (result.status === "ok" && result.excludes_zero ? " is-excl" : ""), result.status === "ok" ? signed(result.estimate) + "%" : "No estimate"));
      floatEl.appendChild(el("span", "sc-float-tag", result.status !== "ok" ? "too few sites" : result.excludes_zero ? "excludes zero" : "cannot be told from zero"));
    }
    function placeFloat() { if (floatEl) { floatEl.classList.toggle("is-on", !wide() && labInView && !panelInView); } }
    if ("IntersectionObserver" in window && floatEl && panelEl) {
      // Only while the choices cross the middle of the screen, so the readout never lies over the next section.
      new IntersectionObserver(function (entries) { labInView = entries[0].isIntersecting; placeFloat(); },
                               { rootMargin: "-35% 0px -35% 0px" }).observe(root.querySelector(".sc-pane-controls") || root);
      new IntersectionObserver(function (entries) { panelInView = entries[0].isIntersecting; placeFloat(); }, { threshold: 0.35 }).observe(panelEl);
    }

    var level = reference.level_text || "95%";
    var state = { spec: Object.assign({}, defaults), past: [], history: [], tried: {}, tries: 0, excluding: 0, shown: published.estimate, last: null, seq: 0, controller: null, cancel: null, drawn: null };
    var syncing = false;

    function specKey(spec) { return KEYS.map(function (k) { return spec[k]; }).join("|"); }
    function isDefault(spec) { return specKey(spec) === specKey(defaults); }
    function encodeSpec(spec) {
      return KEYS.filter(function (k) { return spec[k] !== defaults[k]; }).map(function (k) { return k + ":" + spec[k]; }).join(",");
    }
    function decodeSpec(text) {
      var spec = Object.assign({}, defaults);
      String(text || "").slice(0, 400).split(",").forEach(function (pair) {
        var cut = pair.indexOf(":");
        if (cut < 1) { return; }
        var k = pair.slice(0, cut), v = pair.slice(cut + 1);
        if (KEYS.indexOf(k) >= 0 && (options[k] || []).indexOf(v) >= 0) { spec[k] = v; }
      });
      return spec;
    }
    NYC.setScenario = function (partial) { setSpec(Object.assign({}, state.spec, partial), true); var lab = document.getElementById("lab"); if (lab) { scrollTo(lab); } };

    function group(key) { return document.getElementById("sc-" + key); }
    function readSpec() {
      var spec = Object.assign({}, state.spec);
      KEYS.forEach(function (k) {
        var g = group(k), inputs = g ? Array.prototype.slice.call(g.querySelectorAll("input")) : [];
        for (var i = 0; i < inputs.length; i++) { if (inputs[i].checked && options[k] && options[k][i] !== undefined) { spec[k] = options[k][i]; } }
      });
      return spec;
    }
    function syncRadios(spec) {
      syncing = true;
      KEYS.forEach(function (k) {
        var g = group(k); if (!g) { return; }
        var want = g.querySelectorAll("input")[(options[k] || []).indexOf(spec[k])];
        if (want && !want.checked) { want.click(); }
      });
      syncing = false;
    }
    function updateButtons() {
      backBtn.disabled = !state.past.length;
      resetBtn.disabled = isDefault(state.spec);
      // Each control that differs from the published comparison carries a gold mark beside its name.
      KEYS.forEach(function (k) {
        var g = group(k), control = g && g.closest(".sc-control");
        if (control) { control.classList.toggle("is-changed", state.spec[k] !== defaults[k]); }
      });
    }
    function pulse(key) {
      var g = group(key), control = g && g.closest(".sc-control");
      if (!control || reduced()) { return; }
      control.classList.remove("is-pulse"); void control.offsetWidth; control.classList.add("is-pulse");
    }

    /* How far this scenario sits from the published answer, in points, counted as it changes. */
    var deltaEl = el("p", "sc-delta", "", { "aria-hidden": "true" });
    var deltaArrow = el("span", "sc-delta-arrow"), deltaNum = el("span", "sc-delta-num"), deltaText = el("span", "sc-delta-text");
    deltaEl.appendChild(deltaArrow); deltaEl.appendChild(deltaNum); deltaEl.appendChild(deltaText);
    if (tagEl && tagEl.parentNode) { tagEl.parentNode.insertBefore(deltaEl, tagEl.nextSibling); }
    var shownDelta = 0, cancelDelta = null;
    function drawDelta(result) {
      if (cancelDelta) { cancelDelta(); }
      if (result.status !== "ok") { deltaEl.className = "sc-delta is-none"; deltaNum.textContent = ""; deltaText.textContent = "No estimate to compare"; return; }
      var diff = result.estimate - published.estimate;
      if (result.is_default || Math.abs(diff) < 0.05) {
        deltaEl.className = "sc-delta is-same"; deltaNum.textContent = ""; deltaText.textContent = "The published result"; shownDelta = 0; return;
      }
      deltaEl.className = "sc-delta " + (diff > 0 ? "is-up" : "is-down");
      deltaText.textContent = diff > 0 ? " points above published" : " points below published";
      cancelDelta = tween(shownDelta, Math.abs(diff), 700, function (v) { deltaNum.textContent = v.toFixed(1); });
      shownDelta = Math.abs(diff);
    }

    /* the big figure counts to the new estimate; the axis slides; the ghost stays where it was */
    function setFigure(value, text) {
      if (state.cancel) { state.cancel(); }
      if (value === null) { valueEl.textContent = text; valueEl.classList.add("is-empty"); return; }
      valueEl.classList.remove("is-empty");
      var from = isFinite(state.shown) ? state.shown : value;
      state.cancel = tween(from, value, 800, function (v) { valueEl.textContent = signed(v) + "%"; }, function () { valueEl.textContent = signed(value) + "%"; });
      state.shown = value;
    }
    function moveBar(result) {
      var prior = state.drawn;
      if (prior) { place(ghost, prior.low, prior.high); ghost.style.opacity = "0.5"; }
      if (result.status === "ok") {
        barNow.style.opacity = "1"; dotNow.style.opacity = "1";
        place(barNow, result.low, result.high); dotNow.style.setProperty("--at", pos(result.estimate));
        barNow.classList.toggle("is-excl", result.excludes_zero);
        state.drawn = { low: result.low, high: result.high };
      } else { barNow.style.opacity = "0"; dotNow.style.opacity = "0"; }
    }
    function describeAxis(result) {
      var text = "Interval axis from " + signed(-domain, 0) + "% to " + signed(domain, 0) + "%, zero in the middle. Published result " + signed(published.estimate) + "%, " + signed(published.low) + "% to " + signed(published.high) + "%.";
      if (result.status === "ok") { text += " This scenario " + signed(result.estimate) + "%, " + signed(result.low) + "% to " + signed(result.high) + "%."; }
      else { text += " This scenario has no estimate."; }
      axisEl.setAttribute("aria-label", text);
    }

    function render(result) {
      var ok = result.status === "ok";
      emptyEl.hidden = ok; clear(emptyEl);
      if (ok) {
        setFigure(result.estimate);
        rangeEl.textContent = level + " interval " + signed(result.low) + "% to " + signed(result.high) + "%, from " + num(result.n_tested_sites) + " tested and " + num(result.n_comparison_sites) + " comparison sites";
        tagEl.textContent = result.excludes_zero ? "Excludes zero: an unadjusted association" : "Cannot be told from no change";
        tagEl.className = "sc-tag " + (result.excludes_zero ? "is-excl" : "is-null");
        var diff = result.estimate - published.estimate;
        sentenceEl.textContent = result.sentence + (result.is_default ? " This is the published result." : " The published result is " + signed(published.estimate) + "%, so this choice moves the estimate by " + Math.abs(diff).toFixed(1) + " points " + (diff >= 0 ? "up" : "down") + ".")
          + (result.excludes_zero ? " An interval that leaves zero out is an unadjusted association between building and crashes, not a cause; the comparison cannot adjust for where sites were chosen." : "");
      } else {
        setFigure(null, "No estimate");
        rangeEl.textContent = num(result.n_tested_sites) + " tested sites and " + num(result.n_comparison_sites) + " comparison sites";
        tagEl.textContent = "Too few sites to say"; tagEl.className = "sc-tag is-null";
        sentenceEl.textContent = result.message;
        emptyEl.appendChild(el("p", "sc-empty-title", "Undo a choice to get an estimate back:"));
        var row = el("div", "sc-loosen");
        (result.loosen || []).forEach(function (move) {
          var button = el("button", "button button-quiet", "Undo " + move.label + " (" + num(move.n_tested_sites) + " tested sites)" , { type: "button" });
          button.addEventListener("click", function () { var next = Object.assign({}, state.spec); next[move.key] = move.value; setSpec(next, true); });
          row.appendChild(button);
        });
        emptyEl.appendChild(row);
      }
      moveBar(result); describeAxis(result); drawTrail(result); drawFloat(result); drawDelta(result);
      if (panelEl && !reduced()) { panelEl.classList.remove("is-fresh"); void panelEl.offsetWidth; panelEl.classList.add("is-fresh"); }
      statusEl.textContent = ok ? "Estimate " + signed(result.estimate) + " percent. " + (result.excludes_zero ? "Excludes zero." : "Cannot be told from no change.") : "No estimate for this choice.";
      state.last = result;
    }

    /* tries, history */
    function record(result) {
      var key = specKey(result.spec);
      if (!state.tried[key]) {
        state.tried[key] = true; state.tries += 1;
        if (result.status === "ok" && result.excludes_zero) { state.excluding += 1; }
      }
      state.history = state.history.filter(function (item) { return item.key !== key; });
      state.history.unshift({ key: key, spec: result.spec, label: result.label, status: result.status, estimate: result.estimate, excludes: result.excludes_zero });
      state.history = state.history.slice(0, 8);
      drawTally(); drawHistory();
    }
    var shownTries = 0;
    function drawTally() {
      var n = state.tries;
      tween(shownTries, n, 500, function (v) { countEl.textContent = (n === 1 ? "You have tried " : "You have tried ") + Math.round(v) + (n === 1 ? " scenario." : " scenarios."); });
      shownTries = n;
      var parts = [];
      if (state.excluding) { parts.push(state.excluding + " of " + n + " had an interval that excludes zero."); }
      parts.push("Each interval is built so that about 1 in 20 would leave out zero by chance even if no building did anything. Try enough ways to cut the data and one will. If you stop at the one that excludes zero, you have not found an effect; you have tried " + n + (n === 1 ? " time." : " times."));
      noteEl.textContent = parts.join(" ");
    }
    function drawHistory() {
      clear(historyEl);
      state.history.forEach(function (item, index) {
        var li = el("li", "sc-hist"); li.style.setProperty("--i", index);
        var button = el("button", "sc-hist-btn", null, { type: "button" });
        if (item.key === specKey(state.spec)) { button.setAttribute("aria-current", "true"); }
        button.appendChild(el("span", "sc-hist-label", item.label));
        button.appendChild(el("span", "sc-hist-val " + (item.excludes ? "is-excl" : ""), item.status === "ok" ? signed(item.estimate) + "%" : "no estimate"));
        if (item.excludes) { button.appendChild(el("span", "sc-hist-flag", "excludes zero")); }
        button.addEventListener("click", function () { setSpec(item.spec, true); });
        li.appendChild(button); historyEl.appendChild(li);
      });
      if (!state.history.length) { historyEl.appendChild(el("li", "aside", "Scenarios you try appear here.")); }
    }

    function run() {
      var seq = ++state.seq, spec = state.spec;
      if (state.controller) { state.controller.abort(); }
      state.controller = typeof AbortController === "function" ? new AbortController() : null;
      root.classList.add("is-working");
      var query = KEYS.map(function (k) { return k + "=" + encodeURIComponent(spec[k]); }).join("&");
      getJSON("/api/scenario?" + query, state.controller ? state.controller.signal : undefined).then(function (result) {
        if (seq !== state.seq || !result) { return; }
        root.classList.remove("is-working");
        render(result); record(result); updateButtons();
      }).catch(function (error) {
        if (error && error.name === "AbortError") { return; }
        if (seq === state.seq) { root.classList.remove("is-working"); statusEl.textContent = "This scenario could not be computed. Try again."; sentenceEl.textContent = "This scenario could not be computed. Try again."; }
      });
    }
    function setSpec(spec, push) {
      if (specKey(spec) === specKey(state.spec)) { return; }
      if (push) { state.past.push(state.spec); if (state.past.length > 50) { state.past.shift(); } }
      state.spec = Object.assign({}, spec);
      syncRadios(state.spec);
      setParams({ scenario: encodeSpec(state.spec) });
      updateButtons(); run();
    }

    root.addEventListener("change", function (event) {
      if (syncing || !event.target || event.target.type !== "radio") { return; }
      var g = event.target.closest(".segmented");
      if (g && g.id) { pulse(g.id.replace(/^sc-/, "")); }
      setSpec(readSpec(), true);
    });
    backBtn.addEventListener("click", function () { if (state.past.length) { setSpec(state.past.pop(), false); } });
    resetBtn.addEventListener("click", function () { setSpec(defaults, true); });
    copyBtn.addEventListener("click", function () { copyLink(copyBtn, statusEl); });

    /* open with the spec from the address, or with the published comparison */
    var wanted = getParam("scenario");
    drawHistory(); drawTally();
    if (wanted) {
      var spec = decodeSpec(wanted);
      state.spec = spec; syncRadios(spec); setParams({ scenario: encodeSpec(spec) || null });
      if (!window.location.hash && !getParam("site")) { frame(function () { scrollTo(document.getElementById("lab")); }); }
    }
    updateButtons(); run();
  }

  NYC.onMount("#bk-root", initBlock);
  NYC.onMount("#sc-root", initLab);
})();
