/* The stage: one canvas, one particle per located building, drawn as a point of warm light.

   NYC.Stage.go(layoutName) sends the same particles to a new arrangement. The buildings that leave fade first;
   the rest travel as a swarm, each on its own slightly curved path and a little after its neighbour, so the city
   scatters and regathers instead of sliding. Arrangements live in NYC.Stage.layouts[name] = function (stage) {...}
   and return, in CSS pixels:

     { x, y, alpha: Float32Array, size?: Float32Array, tone?: Uint8Array, marks?: [...] }

   tone picks the light: 0 preservation (teal), 1 new construction (gold), 2 crash (coral), 3 highlight (white gold).
   marks are the chart's words and rules, drawn over the points and faded in once they arrive:
     { t: "text", x, y, text, size?, color?, align?, baseline?, font?: "display" | "sans", weight? }
     { t: "line", x1, y1, x2, y2, color?, width?, dash? } */
(function () {
  "use strict";

  var NYC = window.NYC;
  var TONES = [[95, 212, 196], [232, 192, 116], [255, 143, 120], [255, 240, 205]];
  var FADE_MS = 260, MOVE_MS = 1250, SPREAD_MS = 520, SPARK_PX = 14, INTRO_MS = 2200, ARC_PX = 70;
  // Cost: the canvas is held to 1.5 device pixels, and at rest (nothing travelling, pointer still) the twinkle is
  // drawn at about 30 frames a second instead of every frame. Chart labels are drawn once into their own canvas.
  var MAX_SCALE = 1.5, REST_FRAME_MS = 33;
  var FONT_SANS = "\"Hanken Grotesk\", system-ui, sans-serif", FONT_DISPLAY = "\"Bodoni Moda\", Georgia, serif";

  function sprite(rgb) {
    var size = SPARK_PX * 2, canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    var context = canvas.getContext("2d");
    var glow = context.createRadialGradient(SPARK_PX, SPARK_PX, 0, SPARK_PX, SPARK_PX, SPARK_PX);
    var color = rgb.join(",");
    glow.addColorStop(0, "rgba(" + color + ",0.95)");
    glow.addColorStop(0.14, "rgba(" + color + ",0.6)");
    glow.addColorStop(0.4, "rgba(" + color + ",0.05)");
    glow.addColorStop(1, "rgba(" + color + ",0)");
    context.fillStyle = glow;
    context.fillRect(0, 0, size, size);
    return canvas;
  }

  var Stage = NYC.Stage = { layouts: {}, data: null, width: 0, height: 0, listeners: [], layoutName: "city" };

  /* Where a chart may draw: the right of the screen on wide screens, the top half on narrow ones. */
  Stage.region = function (stage) {
    var w = stage.width, h = stage.height;
    if (w > 960) { return { x0: w * 0.5, x1: w * 0.94, y0: h * 0.17, y1: h * 0.84, wide: true }; }
    return { x0: w * 0.07, x1: w * 0.93, y0: h * 0.2, y1: h * 0.5, wide: false };
  };

  Stage.layouts.city = function (stage) {
    var data = stage.data, n = data.n, x = new Float32Array(n), y = new Float32Array(n), alpha = new Float32Array(n);
    var lonMax = 0, latMax = 0, i;
    for (i = 0; i < n; i++) { lonMax = Math.max(lonMax, data.lon[i]); latMax = Math.max(latMax, data.lat[i]); }
    var midLat = (data.origin[1] + latMax / 2) / data.scale;
    var aspect = Math.cos(midLat * Math.PI / 180) * lonMax / latMax;
    var wide = stage.width > 960;
    var boxH = (wide ? 0.9 : 0.62) * stage.height, boxW = (wide ? 0.56 : 0.92) * stage.width;
    var drawH = Math.min(boxH, boxW / aspect), drawW = drawH * aspect;
    var left = wide ? stage.width * 0.97 - drawW : (stage.width - drawW) / 2;
    var top = wide ? (stage.height - drawH) / 2 : stage.height * 0.09;
    for (i = 0; i < n; i++) {
      x[i] = left + data.lon[i] / lonMax * drawW;
      y[i] = top + (1 - data.lat[i] / latMax) * drawH;
      alpha[i] = 1;
    }
    return { x: x, y: y, alpha: alpha };
  };

  NYC.onMount("#ov-stage", function (host) {
    var canvas = host.querySelector("canvas"), context = canvas.getContext("2d");
    var sprites = TONES.map(sprite);
    var scale = 1, current = null, from = null, to = null, startedAt = 0, seeds = null, visible = true;
    var pointerX = 0, pointerY = 0, driftX = 0, driftY = 0;
    // On a phone (NYC.lite) the canvas draws at one device pixel, skips the light-up intro and draws only while the
    // points travel, so it never competes with the reader's scrolling. The mode is read live (00-motion.js decides it
    // again when the window crosses the phone width), so a window that widens gets the full lights back.
    function isLite() { return !!(NYC.lite && NYC.lite()); }
    var intro = !isLite(), running = false, marks = [], oldMarks = [], marksIn = 1, lastDrawn = 0;
    var markLayer = document.createElement("canvas"), oldLayer = document.createElement("canvas");

    function resize() {
      scale = isLite() ? 1 : Math.min(window.devicePixelRatio || 1, MAX_SCALE);
      Stage.width = host.clientWidth; Stage.height = host.clientHeight;
      canvas.width = Math.round(Stage.width * scale); canvas.height = Math.round(Stage.height * scale);
      if (!Stage.data) { return; }
      var layout = Stage.layouts[Stage.layoutName](Stage);
      current = copy(layout); from = to = null; marks = layout.marks || []; oldMarks = []; marksIn = 1;
      paintMarks(markLayer, marks);
      kick();
    }
    function copy(layout) {
      return { x: layout.x.slice(), y: layout.y.slice(), alpha: layout.alpha.slice(),
               size: layout.size ? layout.size.slice() : null, tone: layout.tone ? layout.tone.slice() : null };
    }

    /* The chart's words and rules, painted once per arrangement into a canvas of their own; each frame only
       stamps that canvas with the right opacity. */
    function paintMarks(layer, list) {
      layer.width = canvas.width; layer.height = canvas.height;
      var g = layer.getContext("2d");
      g.setTransform(scale, 0, 0, scale, 0, 0);
      g.clearRect(0, 0, Stage.width, Stage.height);
      list.forEach(function (mark) {
        g.globalAlpha = mark.opacity == null ? 1 : mark.opacity;
        if (mark.t === "line") {
          g.strokeStyle = mark.color || "rgba(201,202,214,0.5)";
          g.lineWidth = mark.width || 1;
          g.setLineDash(mark.dash || []);
          g.beginPath(); g.moveTo(mark.x1, mark.y1); g.lineTo(mark.x2, mark.y2); g.stroke();
          g.setLineDash([]);
        } else {
          var display = mark.font === "display";
          g.font = (mark.weight || (display ? 600 : 500)) + " " + (mark.size || 13) + "px " + (display ? FONT_DISPLAY : FONT_SANS);
          g.fillStyle = mark.color || "#c9cad6";
          g.textAlign = mark.align || "left";
          g.textBaseline = mark.baseline || "alphabetic";
          g.shadowColor = "rgba(10,13,26,0.9)"; g.shadowBlur = 10;
          g.fillText(mark.text, mark.x, mark.y);
          g.shadowBlur = 0;
        }
      });
      layer.empty = !list.length;
    }
    function stamp(layer, opacity) {
      if (opacity <= 0.01 || layer.empty) { return; }
      context.globalCompositeOperation = "source-over";
      context.globalAlpha = opacity;
      context.setTransform(1, 0, 0, 1, 0, 0);
      // The labels travel with the points under the pointer's parallax, so a chart's dots stay on their axis.
      context.drawImage(layer, Math.round(driftX * scale), Math.round(driftY * scale));
      context.setTransform(scale, 0, 0, scale, 0, 0);
      context.globalAlpha = 1;
    }
    // Fonts arrive after the first paint: repaint the labels once they are ready.
    if (document.fonts && document.fonts.ready) { document.fonts.ready.then(function () { paintMarks(markLayer, marks); kick(); }); }

    function draw(now) {
      running = false;
      if (!Stage.data || !current) { return; }
      var n = Stage.data.n, i, more = false, reduced = NYC.reducedMotion(), settled = !to, lite = isLite();
      var resting = settled && !intro && Math.abs(pointerX - driftX) < 0.2 && Math.abs(pointerY - driftY) < 0.2;
      if (resting && now - lastDrawn < REST_FRAME_MS) { if (visible && !reduced) { kick(); } return; }
      lastDrawn = now;
      if (to) {
        var elapsed = now - startedAt, fade = Math.min(1, elapsed / FADE_MS), finished = true;
        for (i = 0; i < n; i++) {
          var local = Math.min(1, Math.max(0, (elapsed - FADE_MS - seeds.delay[i] * SPREAD_MS) / MOVE_MS));
          if (local < 1) { finished = false; }
          var move = NYC.easeInOut(local), leaving = to.alpha[i] < from.alpha[i];
          current.alpha[i] = leaving ? from.alpha[i] + (to.alpha[i] - from.alpha[i]) * fade : from.alpha[i] + (to.alpha[i] - from.alpha[i]) * move;
          // A curved path: the particle swings out to one side and comes back, as if carried by a current.
          var dx = to.x[i] - from.x[i], dy = to.y[i] - from.y[i], bow = Math.sin(Math.PI * move) * seeds.arc[i];
          var length = Math.sqrt(dx * dx + dy * dy) || 1;
          current.x[i] = from.x[i] + dx * move - dy / length * bow;
          current.y[i] = from.y[i] + dy * move + dx / length * bow;
          if (from.size && to.size) { current.size[i] = from.size[i] + (to.size[i] - from.size[i]) * move; }
        }
        marksIn = Math.max(0, Math.min(1, (elapsed - FADE_MS - MOVE_MS * 0.55) / 500));
        if (finished && marksIn >= 1) { from = to = null; oldMarks = []; current.tone = current.toneNext || current.tone; } else { more = true; }
      }
      if (reduced) { pointerX = pointerY = driftX = driftY = 0; }    // no parallax for a reader who asked for less motion
      driftX += (pointerX - driftX) * 0.06; driftY += (pointerY - driftY) * 0.06;
      if (Math.abs(pointerX - driftX) > 0.2 || Math.abs(pointerY - driftY) > 0.2) { more = true; }

      context.setTransform(scale, 0, 0, scale, 0, 0);
      context.clearRect(0, 0, Stage.width, Stage.height);
      var introT = intro && !reduced ? Math.min(1, (now - seeds.start) / INTRO_MS) : 1;
      var city = Stage.layoutName === "city", tones = current.tone || Stage.data.new;
      if (lite) {
        // On a phone each point is a small square of its colour, drawn one colour at a time: no scaled sprites and
        // no additive blending, which are the costly parts of a frame without a fast graphics processor.
        context.globalCompositeOperation = "source-over";
        for (var tone = 0; tone < TONES.length; tone++) {
          context.fillStyle = "rgb(" + TONES[tone].join(",") + ")";
          for (i = 0; i < n; i++) {
            if (tones[i] !== tone || current.alpha[i] <= 0.01) { continue; }
            var side = (current.size ? current.size[i] : seeds.size[i]) * 0.42;
            context.globalAlpha = current.alpha[i];
            context.fillRect(current.x[i] - side / 2, current.y[i] - side / 2, side, side);
          }
        }
        n = 0;                                      // the sprite loop below has nothing left to draw
      }
      context.globalCompositeOperation = "lighter";
      for (i = 0; i < n; i++) {
        var a = current.alpha[i];
        if (a <= 0.01) { continue; }
        var shown = introT < 1 ? Math.max(0, Math.min(1, (introT - seeds.delay[i]) / 0.25)) : 1;
        if (shown <= 0) { continue; }
        // Lights come on across the city, each with a brief flare. Buildings with more homes burn a little larger.
        var flare = introT < 1 ? 1 + (1 - shown) * 1.6 : 1;
        var size = (current.size ? current.size[i] : seeds.size[i]) * flare;
        var twinkle = reduced || lite ? 1 : 0.86 + 0.14 * Math.sin(now * seeds.rate[i] + seeds.phase[i]);
        // In a chart the points breathe in place, a pixel at most, so the chart stays exact but alive.
        var float = !reduced && !lite && settled && !city ? Math.sin(now * seeds.rate[i] * 0.7 + seeds.phase[i]) * 0.8 : 0;
        context.globalAlpha = a * shown * twinkle;
        context.drawImage(sprites[tones[i]], current.x[i] + driftX - size / 2, current.y[i] + driftY + float - size / 2, size, size);
      }
      context.globalAlpha = 1;
      if (oldMarks.length) { stamp(oldLayer, 1 - Math.min(1, (now - startedAt) / FADE_MS)); }
      stamp(markLayer, marksIn);
      if (introT >= 1) { intro = false; }
      if (more || intro || (visible && !reduced && !lite)) { kick(); }
    }
    function kick() { if (running || !visible) { return; } running = true; window.requestAnimationFrame(draw); }

    Stage.go = function (name) {
      if (!Stage.layouts[name] || !current || name === Stage.layoutName) { return; }
      Stage.layoutName = name;
      var layout = Stage.layouts[name](Stage), target = copy(layout);
      oldMarks = marks; marks = layout.marks || []; marksIn = 0;
      var spare = oldLayer; oldLayer = markLayer; markLayer = spare; paintMarks(markLayer, marks);
      if (!target.size) { target.size = seeds.size.slice(); }
      if (!current.size) { current.size = seeds.size.slice(); }
      if (NYC.reducedMotion()) { current = target; from = to = null; oldMarks = []; marksIn = 1; kick(); return; }
      lastDrawn = 0;
      // The new colour shows from the start of the journey, so a point is already what it will mean when it lands.
      current.tone = target.tone || null; current.toneNext = current.tone;
      from = copy(current); to = target; startedAt = performance.now();
      for (var i = 0; i < Stage.data.n; i++) { seeds.arc[i] = (Math.random() - 0.5) * 2 * ARC_PX; }
      kick();
    };

    new ResizeObserver(resize).observe(host);
    // Leaving or entering the light version changes the canvas resolution and the drawing style: redraw at once.
    window.addEventListener("nyc:lite", resize);
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) { visible = entries[0].isIntersecting; if (visible) { kick(); } }).observe(host);
    }
    if (window.matchMedia("(pointer: fine)").matches) {
      window.addEventListener("pointermove", function (event) {
        if (NYC.reducedMotion()) { return; }
        pointerX = (event.clientX / window.innerWidth - 0.5) * -14; pointerY = (event.clientY / window.innerHeight - 0.5) * -10;
        kick();
      }, { passive: true });
    }

    fetch(host.getAttribute("data-url")).then(function (response) {
      if (!response.ok) { throw new Error("story data " + response.status); }
      return response.json();
    }).then(function (data) {
      Stage.data = data;
      var n = data.n, i;
      seeds = { size: new Float32Array(n), rate: new Float32Array(n), phase: new Float32Array(n), delay: new Float32Array(n),
                arc: new Float32Array(n), start: performance.now() };
      for (i = 0; i < n; i++) {
        seeds.size[i] = Math.min(10, 4.5 + Math.log10(1 + data.units[i]) * 1.8);
        seeds.rate[i] = 0.0006 + Math.random() * 0.0016;
        seeds.phase[i] = Math.random() * 6.28;
        seeds.delay[i] = Math.random() * 0.75;
      }
      Stage.seeds = seeds;
      resize();
      Stage.listeners.forEach(function (listener) { listener(data); });
    }).catch(function (error) {
      host.setAttribute("data-failed", String(error));    // the text beside it stands without the canvas
    });
  });
})();
