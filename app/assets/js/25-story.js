/* The story: as each chapter of the opening reaches the middle of the screen, the stage's points regroup into the
   chart that chapter describes. A chapter names its arrangement in data-layout (app/ui/sections/overview.py); the
   arrangements are below, each a pure function of the story data (app/analysis/story_data.py) and the screen size.

     boroughs    five clusters, one per borough, new buildings at the core
     percentile  new buildings stacked by how crash-heavy their streets were before the project, 0 to 100
     funnel      every building, grouped by how far it gets through the fair test
     outcomes    fifty dots, each one fiftieth of the resampled answers, against zero */
(function () {
  "use strict";

  var NYC = window.NYC, Stage = NYC.Stage;
  var INK = "#f6f2e9", INK2 = "#c9cad6", INK3 = "#a9aec3", GOLD = "#ecca85", CORAL = "#ffab95", RULE = "rgba(169,174,195,0.35)";
  var PRESERVATION = 0, NEW = 1, CRASH = 2, BRIGHT = 3, GOLDEN = 2.399963;

  function arrays(n) { return { x: new Float32Array(n), y: new Float32Array(n), alpha: new Float32Array(n), size: new Float32Array(n), tone: new Uint8Array(n) }; }
  function fmt(value) { return Math.round(value).toLocaleString("en-US"); }
  function signed(value, digits) { var text = Math.abs(value).toFixed(digits); return (value < 0 ? "−" : value > 0 ? "+" : "") + text; }
  function hide(out, i, r) { out.x[i] = (r.x0 + r.x1) / 2; out.y[i] = (r.y0 + r.y1) / 2; out.alpha[i] = 0; out.size[i] = 4; }
  function label(r) { return r.wide ? 13 : 11; }

  /* Five clusters in a row, each a sunflower spiral sized by its count. */
  Stage.layouts.boroughs = function (stage) {
    var data = stage.data, n = data.n, out = arrays(n), r = Stage.region(stage), names = data.boroughs, i, b;
    var members = names.map(function () { return []; });
    for (i = 0; i < n; i++) { if (data.borough[i] >= 0) { members[data.borough[i]].push(i); } else { hide(out, i, r); } }
    var order = names.map(function (_, index) { return index; }).sort(function (a, c) { return members[c].length - members[a].length; });
    var roots = order.map(function (index) { return Math.sqrt(members[index].length); });
    var gap = r.wide ? 30 : 14, width = r.x1 - r.x0, height = r.y1 - r.y0;
    var sum = roots.reduce(function (a, c) { return a + c; }, 0);
    var pitch = Math.min((width - gap * (order.length - 1)) / (2 * sum), (height * 0.62) / (2 * roots[0]));
    var cy = r.y0 + height * 0.42, cursor = r.x0 + (width - (2 * pitch * sum + gap * (order.length - 1))) / 2, marks = [];
    order.forEach(function (index, k) {
      var list = members[index].slice().sort(function (a, c) { return data.new[c] - data.new[a]; });
      var radius = pitch * roots[k], cx = cursor + radius;
      list.forEach(function (site, j) {
        var distance = pitch * Math.sqrt(j + 0.5), angle = j * GOLDEN;
        out.x[site] = cx + Math.cos(angle) * distance; out.y[site] = cy + Math.sin(angle) * distance;
        out.alpha[site] = 1; out.size[site] = Math.max(4.4, Math.min(7, pitch * 3)); out.tone[site] = data.new[site];
      });
      var below = cy + Math.max(radius, 18) + (r.wide ? 30 : 20);
      marks.push({ t: "text", x: cx, y: below, text: fmt(list.length), font: "display", size: r.wide ? 24 : 16, color: GOLD, align: "center" });
      marks.push({ t: "text", x: cx, y: below + (r.wide ? 20 : 15), text: r.wide ? names[index] : names[index].replace("Staten Island", "Staten Is."), size: label(r), color: INK2, align: "center" });
      cursor += 2 * radius + gap;
    });
    for (b = 0; b < n; b++) { if (!out.size[b]) { out.size[b] = 4; } }
    return { x: out.x, y: out.y, alpha: out.alpha, size: out.size, tone: out.tone, marks: marks };
  };

  /* A unit histogram: one point per new building, stacked in bins of two percentile points. */
  Stage.layouts.percentile = function (stage) {
    var data = stage.data, n = data.n, out = arrays(n), r = Stage.region(stage), scale = data.percentile_scale, i;
    var BINS = 50, bins = [], sum = 0, count = 0;
    for (i = 0; i < BINS; i++) { bins.push([]); }
    for (i = 0; i < n; i++) {
      var p = data.percentile[i];
      if (data.new[i] === 1 && p >= 0) {
        var value = p / scale;
        bins[Math.min(BINS - 1, Math.floor(value / (100 / BINS)))].push(i);
        sum += value; count++;
      } else { hide(out, i, r); }
    }
    var width = r.x1 - r.x0, height = (r.y1 - r.y0) * 0.78, base = r.y0 + (r.y1 - r.y0) * 0.86, binW = width / BINS;
    var tallest = bins.reduce(function (a, c) { return Math.max(a, c.length); }, 1), pitch = binW, columns = 1;
    // The largest dot pitch at which the tallest bin still fits: more columns per bin, smaller dots.
    for (columns = 1; columns < 12; columns++) {
      pitch = binW / columns;
      if (Math.ceil(tallest / columns) * pitch <= height) { break; }
    }
    bins.forEach(function (list, b) {
      list.forEach(function (site, j) {
        var column = j % columns, row = Math.floor(j / columns);
        out.x[site] = r.x0 + b * binW + (column + 0.5) * pitch; out.y[site] = base - (row + 0.5) * pitch;
        var above = b >= BINS / 2;
        out.alpha[site] = above ? 1 : 0.6; out.size[site] = Math.max(4, Math.min(8, pitch * 2.8)); out.tone[site] = above ? NEW : PRESERVATION;
      });
    });
    var mean = sum / Math.max(1, count), x50 = r.x0 + width * 0.5, xMean = r.x0 + width * mean / 100, top = base - height - 8;
    var marks = [{ t: "line", x1: r.x0, y1: base + 4, x2: r.x1, y2: base + 4, color: RULE }];
    [0, 25, 50, 75, 100].forEach(function (tick) {
      var x = r.x0 + width * tick / 100;
      marks.push({ t: "line", x1: x, y1: base + 4, x2: x, y2: base + 9, color: RULE });
      marks.push({ t: "text", x: x, y: base + 26, text: tick === 0 ? "0" : tick + "th", size: label(r), color: INK3, align: "center" });
    });
    marks.push({ t: "text", x: r.x0, y: base + 48, text: "Percentile of the street's injury crashes, before the project", size: label(r), color: INK3 });
    marks.push({ t: "line", x1: x50, y1: top, x2: x50, y2: base + 4, color: "rgba(201,202,214,0.7)", dash: [3, 4] });
    marks.push({ t: "text", x: x50 - 8, y: top + 4, text: "Typical street, 50th", size: label(r), color: INK2, align: "right" });
    marks.push({ t: "line", x1: xMean, y1: top - 26, x2: xMean, y2: base + 4, color: GOLD, width: 1.5 });
    marks.push({ t: "text", x: xMean - 8, y: top - 18, text: "New buildings, " + Math.round(mean) + "th", font: "display", size: r.wide ? 18 : 14, color: GOLD, align: "right" });
    return { x: out.x, y: out.y, alpha: out.alpha, size: out.size, tone: out.tone, marks: marks };
  };

  /* Bands, one per stage a building stops at, with the few that make the comparison lit brightest. */
  Stage.layouts.funnel = function (stage) {
    var data = stage.data, n = data.n, out = arrays(n), r = Stage.region(stage), i, g;
    var groups = [[], [], [], []], funnel = data.funnel;
    for (i = 0; i < n; i++) { groups[data.stage[i]].push(i); }
    var texts = [fmt(funnel[0] - funnel[1]) + " not completed in a usable year",
                 fmt(funnel[1] - funnel[2]) + " completed, failed the screen",
                 fmt(funnel[2] - funnel[3]) + " passed, preservation",
                 fmt(funnel[3]) + " new buildings compared"];
    var labelW = r.wide ? (r.x1 - r.x0) * 0.34 : (r.x1 - r.x0) * 0.4, gridX = r.x0 + labelW, gridW = r.x1 - gridX;
    var GAP = r.wide ? 18 : 10, MIN_BAND = r.wide ? 40 : 30, height = r.y1 - r.y0, pitch = 6, columns = 1, bands = [];
    for (pitch = 7; pitch > 1.5; pitch -= 0.25) {
      columns = Math.max(1, Math.floor(gridW / pitch));
      bands = groups.map(function (list) { return Math.max(MIN_BAND, Math.ceil(list.length / columns) * pitch); });
      if (bands.reduce(function (a, c) { return a + c; }, 0) + GAP * 3 <= height) { break; }
    }
    var total = bands.reduce(function (a, c) { return a + c; }, 0) + GAP * 3, y = r.y0 + (height - total) / 2, marks = [];
    var shade = [0.32, 0.55, 0.85, 1], tones = [PRESERVATION, PRESERVATION, NEW, BRIGHT];
    for (g = 0; g < 4; g++) {
      var list = groups[g], rows = Math.ceil(list.length / columns), inner = rows * pitch, top = y + (bands[g] - inner) / 2;
      list.forEach(function (site, j) {
        out.x[site] = gridX + (j % columns + 0.5) * pitch; out.y[site] = top + (Math.floor(j / columns) + 0.5) * pitch;
        out.alpha[site] = shade[g]; out.size[site] = g === 3 ? Math.max(5, pitch * 2.8) : Math.max(2.6, pitch * 1.9); out.tone[site] = tones[g];
      });
      var middle = y + bands[g] / 2, words = texts[g].split(" "), figure = words.shift();
      marks.push({ t: "text", x: gridX - 14, y: middle + 2, text: figure, font: "display", size: r.wide ? 22 : 15, color: g === 3 ? GOLD : INK, align: "right" });
      marks.push({ t: "text", x: gridX - 14, y: middle + (r.wide ? 18 : 14), text: shorten(words.join(" "), r.wide ? 40 : 26), size: r.wide ? 11.5 : 10, color: INK3, align: "right" });
      y += bands[g] + GAP;
    }
    return { x: out.x, y: out.y, alpha: out.alpha, size: out.size, tone: out.tone, marks: marks };
  };
  function shorten(text, limit) { return text.length <= limit ? text : text.slice(0, text.lastIndexOf(" ", limit)) + "…"; }

  /* A quantile dotplot: fifty equally likely answers stacked on a line, with zero marked. */
  Stage.layouts.outcomes = function (stage) {
    var data = stage.data, n = data.n, out = arrays(n), r = Stage.region(stage), values = data.outcomes, i;
    var chosen = [];
    for (i = 0; i < n; i++) { if (data.stage[i] === 3 && chosen.length < values.length) { chosen.push(i); } else { hide(out, i, r); } }
    var low = Math.min(-5, Math.floor(Math.min.apply(null, values) / 5) * 5), high = Math.max(5, Math.ceil(Math.max.apply(null, values) / 5) * 5);
    var width = r.x1 - r.x0, base = r.y0 + (r.y1 - r.y0) * 0.78;
    function at(value) { return r.x0 + (value - low) / (high - low) * width; }
    var dot = Math.min(width / 22, (r.y1 - r.y0) * 0.09), stacks = {};
    values.forEach(function (value, k) {
      var site = chosen[k];
      if (site == null) { return; }
      var bin = Math.round((at(value) - r.x0) / dot), row = stacks[bin] = (stacks[bin] || 0) + 1;
      out.x[site] = r.x0 + bin * dot; out.y[site] = base - (row - 0.5) * dot * 0.92;
      out.alpha[site] = 1; out.size[site] = dot * 1.5; out.tone[site] = value < 0 ? NEW : CRASH;
    });
    var tallest = Object.keys(stacks).reduce(function (a, c) { return Math.max(a, stacks[c]); }, 1), top = base - tallest * dot * 0.92 - 18;
    var marks = [{ t: "line", x1: r.x0, y1: base + 6, x2: r.x1, y2: base + 6, color: RULE }];
    for (var tick = low; tick <= high; tick += 5) {
      marks.push({ t: "line", x1: at(tick), y1: base + 6, x2: at(tick), y2: base + 11, color: RULE });
      marks.push({ t: "text", x: at(tick), y: base + 28, text: tick === 0 ? "0" : signed(tick, 0) + "%", size: label(r), color: INK3, align: "center" });
    }
    var zero = at(0);
    marks.push({ t: "line", x1: zero, y1: top - 20, x2: zero, y2: base + 6, color: "rgba(246,242,233,0.75)", dash: [3, 4] });
    marks.push({ t: "text", x: zero, y: top - 28, text: "No change", size: label(r), color: INK, align: "center" });
    var estimate = data.outcomes[Math.floor(values.length / 2)];
    marks.push({ t: "text", x: r.x0, y: base + 50, text: r.wide ? "Change in injury crashes after opening, against comparison sites" : "Change in injury crashes after opening", size: label(r), color: INK3 });
    var below = values.filter(function (value) { return value < 0; }).length;
    marks.push({ t: "text", x: at(estimate) - 8, y: top - 10, text: below + " of 50 below zero", font: "display", size: r.wide ? 18 : 14, color: GOLD, align: "right" });
    marks.push({ t: "text", x: r.x1, y: base + 50, text: "more crashes →", size: label(r), color: CORAL, align: "right", opacity: 0.9 });
    return { x: out.x, y: out.y, alpha: out.alpha, size: out.size, tone: out.tone, marks: marks };
  };

  /* Which chapter is in the middle of the screen. */
  var steps = [], pending = "city", active = null;
  function apply() { if (Stage.go && Stage.data) { Stage.go(pending); } }
  Stage.listeners.push(apply);
  function activate(step) {
    if (step === active) { return; }
    active = step;
    pending = step.getAttribute("data-layout");
    steps.forEach(function (other) { other.classList.toggle("is-active", other === step); });
    var dots = document.querySelectorAll(".story-progress li"), index = steps.indexOf(step);
    Array.prototype.forEach.call(dots, function (dot, k) { dot.classList.toggle("is-active", k === index); dot.classList.toggle("is-past", k < index); });
    apply();
  }
  function choose() {
    var middle = window.innerHeight * 0.55, best = null;
    steps.forEach(function (step) {
      var box = step.getBoundingClientRect();
      if (box.top <= middle && box.bottom > middle * 0.4) { best = step; }
    });
    if (best) { activate(best); }
  }
  var ticking = false;
  window.addEventListener("scroll", function () {
    if (ticking) { return; }
    ticking = true;
    window.requestAnimationFrame(function () { ticking = false; choose(); });
  }, { passive: true });
  NYC.onMount(".story-step[data-layout]", function (step) {
    steps.push(step);
    steps.sort(function (a, b) { return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1; });
    choose();
  });
})();
