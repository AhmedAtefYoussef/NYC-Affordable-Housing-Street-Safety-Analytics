/* The stage: one canvas, one particle per located building, drawn as a point of warm light.

   NYC.Stage.go(layoutName) sends the same particles to a new arrangement. The buildings that leave fade first;
   the rest travel as a swarm, each on its own slightly curved path and a little after its neighbour, so the city
   scatters and regathers instead of sliding. Arrangements live in NYC.Stage.layouts[name] = function (stage) {...}
   and return, in CSS pixels:

     { x, y, alpha: Float32Array, size?: Float32Array, tone?: Uint8Array, marks?: [...] }

   tone picks the light: 0 preservation (teal), 1 new construction (gold), 2 crash (coral), 3 highlight (white gold).
   marks are the chart's words and rules, drawn over the points and faded in once they arrive:
     { t: "text", x, y, text, size?, color?, align?, baseline?, font?: "display" | "sans", weight? }
     { t: "line", x1, y1, x2, y2, color?, width?, dash? }

   Where the work is done. The page computes the arrangements and paints the chart's words (the fonts live here);
   every frame of light is drawn by stageRenderer below. Where the browser can hand a canvas to a worker
   (OffscreenCanvas), the renderer runs on its own thread, so the lights never wait for the page's scripts: Dash's
   first render, a scroll, a chart being built. Elsewhere the same renderer runs on the page, behind the same
   messages, and draws exactly the same frames. */
(function () {
  "use strict";

  var NYC = window.NYC;
  // Cost: the canvas is held to 1.5 device pixels. Chart labels are drawn once per arrangement into their own canvas.
  var MAX_SCALE = 1.5;
  var FONT_SANS = "\"Hanken Grotesk\", system-ui, sans-serif", FONT_DISPLAY = "\"Bodoni Moda\", Georgia, serif";

  /* The renderer. Self-contained (it reads nothing from the page around it), because it is also sent, as text, to a
     worker. It takes messages through scope.onmessage:

       init     { canvas, n, size, rate, phase, delay, tones, lite, reduced, visible }   the canvas and each point's seeds
       resize   { seq, width, height, scale, lite, city, layout }               a new size: snap to the arrangement
       go       { seq, city, layout }                                           travel to a new arrangement
       marks    { seq, image } or { seq, pixels }                               the arrangement's words, painted
       pointer  { x, y }   visible { value }   reduced { value }
       start    { mode }    the opening begins: "full", "quick" (a reload in the same tab), "lite" (phones) or "none"
       skip                 the reader is moving on: the opening finishes within 350 ms

     It posts back { type: "formed" } once the city has formed, so the page can bring in the words beside it.

     The opening: every building starts as a faint spark somewhere on the stage, drifting on its own heading; then,
     each on its own short delay, the sparks swirl into their places in the city (the remaining distance turns about
     the landing point as it shrinks, as in the Generate sequence), flare as they land, and one band of light crosses
     the city from south to north. The positions are written into the points themselves, so a chapter that starts
     mid-flight simply carries the swarm on to its own arrangement.

     At rest (nothing travelling, pointer still) the twinkle is drawn at about 30 frames a second. */
  function stageRenderer(scope) {
    "use strict";
    var TONES = [[95, 212, 196], [232, 192, 116], [255, 143, 120], [255, 240, 205]];
    var FADE_MS = 260, MOVE_MS = 1250, SPREAD_MS = 520, SPARK_PX = 14, ARC_PX = 70, REST_FRAME_MS = 33;
    // The opening's timings: when the gathering starts, how long it lasts, and the south-to-north wave (full only).
    var OPENINGS = { full: { from: 500, gather: 1800, wave: true }, quick: { from: 80, gather: 520, wave: false },
                     lite: { from: 250, gather: 1350, wave: false } };
    var FLARE_MS = 520, WAVE_FROM = 2200, WAVE_MS = 800, WAVE_PX = 26, SKIP_MS = 350, FORMED_AT = 0.95;   // the words come in as the last sparks are landing
    var frame = self.requestAnimationFrame ? function (fn) { self.requestAnimationFrame(fn); }
                                           : function (fn) { setTimeout(function () { fn(performance.now()); }, 16); };
    var canvas = null, context = null, sprites = null, scale = 1, width = 0, height = 0, lite = false, reduced = false, visible = true;
    var n = 0, seeds = null, baseTones = null, city = true, seq = 0;
    var current = null, from = null, to = null, startedAt = 0;
    var pointerX = 0, pointerY = 0, driftX = 0, driftY = 0;
    var running = false, lastDrawn = 0, waiting = true, opening = null, home = null, homeTop = 0, homeBottom = 0;
    var spark = null, grow = null, lit = null;
    var markImage = null, oldImage = null, marksIn = 1;

    function easeInOut(t) { return t < 0.5 ? 8 * t * t * t * t : 1 - Math.pow(-2 * t + 2, 4) / 2; }
    function surface(size) {
      if (typeof OffscreenCanvas !== "undefined") { return new OffscreenCanvas(size, size); }
      var element = document.createElement("canvas");
      element.width = element.height = size;
      return element;
    }
    /* A point of light drawn at the canvas's own resolution, so its core stays sharp on a high-density screen. */
    function sprite(rgb) {
      var r = SPARK_PX * scale, size = Math.ceil(r * 2), layer = surface(size), g = layer.getContext("2d");
      var glow = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, r), color = rgb.join(",");
      glow.addColorStop(0, "rgba(" + color + ",0.95)");
      glow.addColorStop(0.14, "rgba(" + color + ",0.6)");
      glow.addColorStop(0.4, "rgba(" + color + ",0.05)");
      glow.addColorStop(1, "rgba(" + color + ",0)");
      g.fillStyle = glow;
      g.fillRect(0, 0, size, size);
      return layer;
    }
    function copy(layout) {
      return { x: layout.x.slice(), y: layout.y.slice(), alpha: layout.alpha.slice(),
               size: layout.size ? layout.size.slice() : null, tone: layout.tone ? layout.tone.slice() : null };
    }
    function release(image) { if (image && image.close) { image.close(); } }

    /* The words are stamped with the points' parallax, so a chart's dots stay on their axis. */
    function stamp(image, opacity) {
      if (opacity <= 0.01 || !image) { return; }
      context.globalCompositeOperation = "source-over";
      context.globalAlpha = opacity;
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.drawImage(image, Math.round(driftX * scale), Math.round(driftY * scale));
      context.setTransform(scale, 0, 0, scale, 0, 0);
      context.globalAlpha = 1;
    }

    /* One frame of the opening: writes each point's place, light and size into current, grow and lit. */
    function open(now) {
      var o = opening, plan = OPENINGS[o.mode], elapsed = now - o.start, i;
      if (o.skipAt) { elapsed = o.skipFrom + (now - o.skipAt) * o.rush; }
      var settle = plan.from + plan.gather + FLARE_MS;
      var end = plan.wave && !o.skipAt ? Math.max(settle, WAVE_FROM + WAVE_MS) : settle;
      var fadeIn = Math.min(1, elapsed / 600);
      var wave = plan.wave && !o.skipAt ? (elapsed - WAVE_FROM) / WAVE_MS : -1, scanY = homeBottom - wave * (homeBottom - homeTop);
      var g = (elapsed - plan.from) / plan.gather;
      for (i = 0; i < n; i++) {
        var hx = home.x[i], hy = home.y[i], d = spark.delay[i];
        var t = easeInOut(Math.max(0, Math.min(1, (g - d) / (1 - d * 0.6))));
        var sx = spark.x[i] * width + spark.vx[i] * elapsed / 1000, sy = spark.y[i] * height + spark.vy[i] * elapsed / 1000;
        var swirl = (1 - t) * spark.spin[i] * 1.8, dx = sx - hx, dy = sy - hy, cos = Math.cos(swirl), sin = Math.sin(swirl);
        current.x[i] = hx + (dx * cos - dy * sin) * (1 - t);
        current.y[i] = hy + (dx * sin + dy * cos) * (1 - t);
        current.alpha[i] = home.alpha[i] * Math.min(1, fadeIn * 0.6 + 0.4 * t);
        // As it lands, a point flares and settles; the wave lifts the points it passes.
        var since = elapsed - (plan.from + plan.gather * (d + 1 - d * 0.6));
        var flare = since >= 0 && since < FLARE_MS ? 1 - since / FLARE_MS : 0;
        var light = wave > 0 && wave < 1 ? Math.max(0, 1 - Math.abs(hy - scanY) / WAVE_PX) : 0;
        grow[i] = 1 + flare * 1.6 + light * 1.2; lit[i] = Math.max(flare * 0.6, light);
      }
      if (!o.formed && g >= FORMED_AT) { o.formed = true; scope.postMessage({ type: "formed" }); }
      if (elapsed >= end) { finishOpening(); }
    }
    function finishOpening() {
      if (!opening) { return; }
      if (!opening.formed) { scope.postMessage({ type: "formed" }); }
      opening = null;
      if (home && !to) { current.x.set(home.x); current.y.set(home.y); current.alpha.set(home.alpha); }
      grow.fill(1); lit.fill(0);
    }

    function draw(now) {
      running = false;
      if (!current || !sprites || waiting) { return; }
      var count = n, i, more = false, settled = !to;
      if (opening) { open(now); more = true; }
      var resting = settled && !opening && !more && Math.abs(pointerX - driftX) < 0.2 && Math.abs(pointerY - driftY) < 0.2;
      if (resting && now - lastDrawn < REST_FRAME_MS) { if (visible && !reduced) { kick(); } return; }
      lastDrawn = now;
      if (to) {
        var elapsed = now - startedAt, fade = Math.min(1, elapsed / FADE_MS), finished = true;
        for (i = 0; i < count; i++) {
          var local = Math.min(1, Math.max(0, (elapsed - FADE_MS - seeds.delay[i] * SPREAD_MS) / MOVE_MS));
          if (local < 1) { finished = false; }
          var move = easeInOut(local), leaving = to.alpha[i] < from.alpha[i];
          current.alpha[i] = leaving ? from.alpha[i] + (to.alpha[i] - from.alpha[i]) * fade : from.alpha[i] + (to.alpha[i] - from.alpha[i]) * move;
          // A curved path: the particle swings out to one side and comes back, as if carried by a current.
          var dx = to.x[i] - from.x[i], dy = to.y[i] - from.y[i], bow = Math.sin(Math.PI * move) * seeds.arc[i];
          var length = Math.sqrt(dx * dx + dy * dy) || 1;
          current.x[i] = from.x[i] + dx * move - dy / length * bow;
          current.y[i] = from.y[i] + dy * move + dx / length * bow;
          if (from.size && to.size) { current.size[i] = from.size[i] + (to.size[i] - from.size[i]) * move; }
        }
        marksIn = Math.max(0, Math.min(1, (elapsed - FADE_MS - MOVE_MS * 0.55) / 500));
        if (finished && marksIn >= 1) { from = to = null; release(oldImage); oldImage = null; current.tone = current.toneNext || current.tone; } else { more = true; }
      }
      if (reduced) { pointerX = pointerY = driftX = driftY = 0; }    // no parallax for a reader who asked for less motion
      driftX += (pointerX - driftX) * 0.06; driftY += (pointerY - driftY) * 0.06;
      if (Math.abs(pointerX - driftX) > 0.2 || Math.abs(pointerY - driftY) > 0.2) { more = true; }

      context.setTransform(scale, 0, 0, scale, 0, 0);
      context.clearRect(0, 0, width, height);
      var tones = current.tone || baseTones;
      if (lite) {
        // On a phone each point is a small square of its colour, drawn one colour at a time: no scaled sprites and
        // no additive blending, which are the costly parts of a frame without a fast graphics processor.
        context.globalCompositeOperation = "source-over";
        for (var tone = 0; tone < TONES.length; tone++) {
          context.fillStyle = "rgb(" + TONES[tone].join(",") + ")";
          for (i = 0; i < count; i++) {
            if (tones[i] !== tone || current.alpha[i] <= 0.01) { continue; }
            var side = (current.size ? current.size[i] : seeds.size[i]) * 0.42 * grow[i];
            context.globalAlpha = current.alpha[i];
            context.fillRect(current.x[i] - side / 2, current.y[i] - side / 2, side, side);
          }
        }
        count = 0;                                  // the sprite loop below has nothing left to draw
      }
      context.globalCompositeOperation = "lighter";
      for (i = 0; i < count; i++) {
        var a = current.alpha[i];
        if (a <= 0.01) { continue; }
        // Buildings with more homes burn a little larger; in the opening a point flares as it lands.
        var size = (current.size ? current.size[i] : seeds.size[i]) * grow[i];
        var twinkle = reduced || lite ? 1 : 0.86 + 0.14 * Math.sin(now * seeds.rate[i] + seeds.phase[i]);
        // In a chart the points breathe in place, a pixel at most, so the chart stays exact but alive.
        var float = !reduced && !lite && settled && !city ? Math.sin(now * seeds.rate[i] * 0.7 + seeds.phase[i]) * 0.8 : 0;
        context.globalAlpha = Math.min(1, a * twinkle + lit[i] * 0.5);
        context.drawImage(sprites[lit[i] > 0.35 ? 3 : tones[i]], current.x[i] + driftX - size / 2, current.y[i] + driftY + float - size / 2, size, size);
      }
      context.globalAlpha = 1;
      if (oldImage) { stamp(oldImage, 1 - Math.min(1, (now - startedAt) / FADE_MS)); }
      stamp(markImage, marksIn);
      if (more || (visible && !reduced && !lite)) { kick(); }
    }
    function kick() { if (running || !visible || !context) { return; } running = true; frame(draw); }

    function go(message) {
      seq = message.seq; city = message.city;
      var target = copy(message.layout);
      // A chapter that starts during the opening carries the swarm on from wherever it is.
      if (opening) { if (!opening.formed) { scope.postMessage({ type: "formed" }); } opening = null; grow.fill(1); lit.fill(0); }
      waiting = false;
      release(oldImage); oldImage = markImage; markImage = null; marksIn = 0;
      if (!target.size) { target.size = seeds.size.slice(); }
      if (!current.size) { current.size = seeds.size.slice(); }
      if (reduced) { current = target; from = to = null; release(oldImage); oldImage = null; marksIn = 1; return; }
      lastDrawn = 0;
      // The new colour shows from the start of the journey, so a point is already what it will mean when it lands.
      current.tone = target.tone || null; current.toneNext = current.tone;
      from = copy(current); to = target; startedAt = performance.now();
      for (var i = 0; i < n; i++) { seeds.arc[i] = (Math.random() - 0.5) * 2 * ARC_PX; }
    }

    function handle(message) {
      switch (message.type) {
        case "init":
          canvas = message.canvas; context = canvas.getContext("2d"); n = message.n; baseTones = message.tones;
          seeds = { size: message.size, rate: message.rate, phase: message.phase, delay: message.delay, arc: new Float32Array(message.n) };
          lite = message.lite; reduced = message.reduced; visible = message.visible !== false;
          grow = new Float32Array(n).fill(1); lit = new Float32Array(n);
          spark = { x: new Float32Array(n), y: new Float32Array(n), vx: new Float32Array(n), vy: new Float32Array(n),
                    spin: new Float32Array(n), delay: new Float32Array(n) };
          for (var k = 0; k < n; k++) {
            var heading = Math.random() * 6.283, pace = 8 + Math.random() * 22;
            spark.x[k] = Math.random(); spark.y[k] = Math.random();
            spark.vx[k] = Math.cos(heading) * pace; spark.vy[k] = Math.sin(heading) * pace;
            spark.spin[k] = (Math.random() < 0.5 ? -1 : 1) * (0.6 + Math.random() * 1.1);
            spark.delay[k] = Math.random() * 0.5;
          }
          break;
        case "resize":
          seq = message.seq; width = message.width; height = message.height; scale = message.scale; lite = message.lite; city = message.city;
          canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale);
          sprites = TONES.map(sprite);
          current = copy(message.layout); from = to = null; marksIn = 1;
          if (message.city) {                 // the city is where the opening lands
            home = copy(message.layout); homeTop = Infinity; homeBottom = -Infinity;
            for (var h = 0; h < n; h++) { homeTop = Math.min(homeTop, home.y[h]); homeBottom = Math.max(homeBottom, home.y[h]); }
          } else if (opening) { finishOpening(); }
          release(oldImage); oldImage = null; release(markImage); markImage = null;
          break;
        case "go": if (current) { go(message); } break;
        case "marks":
          if (message.pixels) {               // raw pixels, when the page could not make an image: make it here
            self.createImageBitmap(message.pixels).then(function (image) {
              if (message.seq === seq) { release(markImage); markImage = image; kick(); } else { release(image); }
            });
          } else if (message.seq === seq) { release(markImage); markImage = message.image; } else { release(message.image); }
          break;
        case "pointer": pointerX = message.x; pointerY = message.y; break;
        case "visible": visible = message.value; break;
        case "reduced": reduced = message.value; break;
        case "start":
          waiting = false;
          if (OPENINGS[message.mode] && home && !reduced) { opening = { mode: message.mode, start: performance.now(), formed: false }; lastDrawn = 0; }
          else { scope.postMessage({ type: "formed" }); }
          break;
        case "skip":
          if (opening && !opening.skipAt) {
            var o = opening, plan = OPENINGS[o.mode], now = performance.now(), at = now - o.start;
            var finish = plan.from + plan.gather + FLARE_MS;
            o.skipAt = now; o.skipFrom = Math.min(at, finish); o.rush = Math.max(1, (finish - o.skipFrom) / SKIP_MS);
            if (!o.formed) { o.formed = true; scope.postMessage({ type: "formed" }); }
          }
          break;
      }
      kick();
    }
    scope.onmessage = function (event) { handle(event.data); };
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
    var canvas = host.querySelector("canvas"), send = null, thread = null, init = null, seq = 0, marks = [], visible = true;
    // On a phone (NYC.lite) the canvas draws at one device pixel, plays a shorter opening and draws only while the
    // points travel, so it never competes with the reader's scrolling. The mode is read live (00-motion.js decides it
    // again when the window crosses the phone width), so a window that widens gets the full lights back.
    function isLite() { return !!(NYC.lite && NYC.lite()); }
    function scaleNow() { return isLite() ? 1 : Math.min(window.devicePixelRatio || 1, MAX_SCALE); }

    /* The renderer's host: a worker drawing on the canvas it was handed, or, where that is not offered, this page. */
    function onPage(target) {
      var local = { postMessage: function (message) { heard({ data: message }); } };
      stageRenderer(local);
      thread = null;
      send = function (message) { local.onmessage({ data: message }); };
      return target;
    }
    function connect() {
      if (!canvas.transferControlToOffscreen || !window.Worker || !window.Blob || !window.URL) { return onPage(canvas); }
      var worker;
      try {
        worker = new Worker(URL.createObjectURL(new Blob(["(" + stageRenderer + ")(self);"], { type: "text/javascript" })));
      } catch (error) { return onPage(canvas); }
      var offscreen;
      try { offscreen = canvas.transferControlToOffscreen(); } catch (error) { worker.terminate(); return onPage(canvas); }
      thread = worker;
      worker.onmessage = heard;
      send = function (message, transfer) { worker.postMessage(message, transfer || []); };
      // If the worker ever fails, the page takes over on a fresh canvas laid over the first (which it can no longer
      // draw on); the first keeps its accessible name, the new one is hidden from screen readers.
      worker.addEventListener("error", function () {
        if (thread !== worker) { return; }
        worker.terminate();
        var fresh = document.createElement("canvas");
        fresh.className = canvas.className; fresh.setAttribute("aria-hidden", "true");
        canvas.parentNode.insertBefore(fresh, canvas.nextSibling);
        init.canvas = onPage(fresh); init.visible = visible;
        send(init);
        resize();
        send({ type: "start", mode: "none" });
      });
      return offscreen;
    }

    /* What the renderer says back: the city has formed, so the words beside it may come in. */
    function heard(event) { if (event.data && event.data.type === "formed" && NYC.opened) { NYC.opened(); } }

    /* Which opening to play: none for a reader who asked for less motion, or when the page opened away from the stage
       (a link to a later part, or the hero already released); the quick one on a reload in the same tab; the short
       one on a phone; otherwise the full one. */
    function openingMode() {
      var box = host.getBoundingClientRect();
      if (NYC.reducedMotion() || !(NYC.isOpening && NYC.isOpening()) || box.bottom <= 0 || box.top >= window.innerHeight) { return "none"; }
      var seen = false;
      try { seen = window.sessionStorage.getItem("nyc-opened") === "1"; window.sessionStorage.setItem("nyc-opened", "1"); } catch (error) { /* private mode: play it in full */ }
      return seen ? "quick" : isLite() ? "lite" : "full";      // on a phone the quick one is drawn with the light squares
    }
    /* The reader moving on (a scroll, a key, a press) hurries the opening to its end; the page never waits for it. */
    function hurryOnInput() {
      var events = ["wheel", "touchmove", "keydown", "pointerdown"];
      function hurry() {
        events.forEach(function (name) { window.removeEventListener(name, hurry, true); });
        window.removeEventListener("scroll", hurry);
        if (send) { send({ type: "skip" }); }
      }
      events.forEach(function (name) { window.addEventListener(name, hurry, { capture: true, passive: true }); });
      window.addEventListener("scroll", hurry, { passive: true });
    }

    function plain(layout) {
      return { x: layout.x, y: layout.y, alpha: layout.alpha, size: layout.size || null, tone: layout.tone || null };
    }
    // To a worker the arrangement's arrays are handed over, not copied (each arrangement is freshly built).
    function handOver(layout) {
      if (!thread) { return []; }
      var list = [];
      [layout.x, layout.y, layout.alpha, layout.size, layout.tone].forEach(function (array) {
        if (array && list.indexOf(array.buffer) < 0) { list.push(array.buffer); }
      });
      return list;
    }

    /* The chart's words and rules, painted once per arrangement into a canvas of their own; the renderer only
       stamps it with the right opacity. A worker receives it as an image. */
    function paintMarks(list) {
      marks = list;
      var mine = seq, s = scaleNow(), layer = document.createElement("canvas");
      if (!list.length) { send({ type: "marks", seq: mine, image: null }); return; }
      layer.width = Math.max(1, Math.round(Stage.width * s)); layer.height = Math.max(1, Math.round(Stage.height * s));
      var g = layer.getContext("2d");
      g.setTransform(s, 0, 0, s, 0, 0);
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
      if (thread && window.createImageBitmap) {
        var worker = thread;
        window.createImageBitmap(layer).then(function (image) {
          if (thread === worker) { send({ type: "marks", seq: mine, image: image }, [image]); } else { send({ type: "marks", seq: mine, image: layer }); }
        }, function () {
          // No image could be made here: hand over the raw pixels instead, and the worker makes the image itself.
          var pixels = g.getImageData(0, 0, layer.width, layer.height);
          if (thread === worker) { send({ type: "marks", seq: mine, pixels: pixels }, [pixels.data.buffer]); } else { send({ type: "marks", seq: mine, image: layer }); }
        });
      } else {
        send({ type: "marks", seq: mine, image: layer });
      }
    }

    function resize() {
      Stage.width = host.clientWidth; Stage.height = host.clientHeight;
      if (!Stage.data || !send) { return; }
      var layout = Stage.layouts[Stage.layoutName](Stage);
      seq += 1;
      send({ type: "resize", seq: seq, width: Stage.width, height: Stage.height, scale: scaleNow(), lite: isLite(),
             city: Stage.layoutName === "city", layout: plain(layout) }, handOver(layout));
      paintMarks(layout.marks || []);
    }
    // Fonts arrive after the first paint: repaint the labels once they are ready.
    if (document.fonts && document.fonts.ready) { document.fonts.ready.then(function () { if (send && Stage.data) { paintMarks(marks); } }); }

    Stage.go = function (name) {
      if (!Stage.layouts[name] || !Stage.data || !send || name === Stage.layoutName) { return; }
      Stage.layoutName = name;
      var layout = Stage.layouts[name](Stage);
      seq += 1;
      send({ type: "go", seq: seq, city: name === "city", layout: plain(layout) }, handOver(layout));
      paintMarks(layout.marks || []);
    };

    new ResizeObserver(resize).observe(host);
    // Leaving or entering the light version changes the canvas resolution and the drawing style: redraw at once.
    window.addEventListener("nyc:lite", resize);
    var motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    function onMotion() { if (send) { send({ type: "reduced", value: motion.matches }); } }
    if (motion.addEventListener) { motion.addEventListener("change", onMotion); } else if (motion.addListener) { motion.addListener(onMotion); }
    if ("IntersectionObserver" in window) {
      // Kept here as well, so a renderer that starts later (or takes over after a failure) starts with the right state.
      new IntersectionObserver(function (entries) {
        visible = entries[0].isIntersecting;
        if (send) { send({ type: "visible", value: visible }); }
      }).observe(host);
    }
    if (window.matchMedia("(pointer: fine)").matches) {
      window.addEventListener("pointermove", function (event) {
        if (!send || !visible || NYC.reducedMotion()) { return; }
        send({ type: "pointer", x: (event.clientX / window.innerWidth - 0.5) * -14, y: (event.clientY / window.innerHeight - 0.5) * -10 });
      }, { passive: true });
    }

    fetch(host.getAttribute("data-url")).then(function (response) {
      if (!response.ok) { throw new Error("story data " + response.status); }
      return response.json();
    }).then(function (data) {
      Stage.data = data;
      var n = data.n, i;
      var seeds = { size: new Float32Array(n), rate: new Float32Array(n), phase: new Float32Array(n), delay: new Float32Array(n) };
      for (i = 0; i < n; i++) {
        seeds.size[i] = Math.min(10, 4.5 + Math.log10(1 + data.units[i]) * 1.8);
        seeds.rate[i] = 0.0006 + Math.random() * 0.0016;
        seeds.phase[i] = Math.random() * 6.28;
        seeds.delay[i] = Math.random() * 0.75;
      }
      Stage.seeds = seeds;
      var target = connect();
      init = { type: "init", canvas: target, n: n, size: seeds.size, rate: seeds.rate, phase: seeds.phase, delay: seeds.delay,
               tones: data.new, lite: isLite(), reduced: NYC.reducedMotion(), visible: visible };
      send(init, thread ? [target] : []);
      init.canvas = null;                           // handed over; a fallback fills in its own
      resize();
      // The opening starts at once in a worker, which Dash's first render cannot slow; drawn on the page, it waits
      // for the first idle moment so it plays on a calm thread.
      var begin = function () {
        var mode = openingMode();
        send({ type: "start", mode: mode });
        if (mode !== "none") { hurryOnInput(); if (NYC.openingStarted) { NYC.openingStarted(); } }
      };
      if (thread) { begin(); }
      else if (window.requestIdleCallback) { window.requestIdleCallback(begin, { timeout: 300 }); } else { window.setTimeout(begin, 60); }
      Stage.listeners.forEach(function (listener) { listener(data); });
    }).catch(function (error) {
      host.setAttribute("data-failed", String(error));    // the text beside it stands without the canvas
      if (NYC.opened) { NYC.opened(); }
    });
  });
})();
