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
  // The opening's order of boroughs, south to north. A building with no known borough comes in with the last.
  var BOROUGH_ORDER = ["staten island", "brooklyn", "queens", "manhattan", "bronx"];
  function boroughRank(name) {
    var at = BOROUGH_ORDER.indexOf(String(name || "").toLowerCase().replace(/^the /, ""));
    return at < 0 ? BOROUGH_ORDER.length - 1 : at;
  }
  var FONT_SANS = "\"Hanken Grotesk\", system-ui, sans-serif", FONT_DISPLAY = "\"Bodoni Moda\", Georgia, serif";

  /* The renderer. Self-contained (it reads nothing from the page around it except scope.Light, the light kit of
     05-light.js, which is sent in front of it), because it is also sent, as text, to a worker. It takes messages
     through scope.onmessage:

       init     { canvas, n, size, rate, phase, delay, tones, rank, lite, reduced, visible }   the canvas and each point's seeds
       resize   { seq, width, height, scale, lite, city, layout }               a new size: snap to the arrangement
       go       { seq, city, layout }                                           travel to a new arrangement
       marks    { seq, image } or { seq, pixels }                               the arrangement's words, painted
       pointer  { x, y }   visible { value }   reduced { value }
       start    { mode }    the opening begins: "full", "quick" (a reload in the same tab), "lite" (phones) or "none"
       skip                 the reader is moving on: the opening finishes within 350 ms
       stats                reply with the frame times ({ type: "stats" })

     It posts back { type: "formed" } once the city has formed, so the page can bring in the words beside it.

     The full opening, about four seconds:
       ignite   the stage is dark; one white-gold point swells at the heart of the city, with a thin flare of light
       burst    every building is fired outward from it and slows to a drift: a ring of light streaks, blurred by speed
       gather   borough by borough, south to north (Staten Island, Brooklyn, Queens, Manhattan, the Bronx), the sparks
                fly home on curved paths, each a little after its neighbour; a faint ring marks each borough as it lands
       wave     one band of light crosses the finished city from south to north
     The quick and phone openings keep the short swirl. The positions are written into the points themselves, so a
     chapter that starts mid-flight simply carries the swarm on to its own arrangement.

     Motion blur: every point that travels (in the opening and between chapters) is drawn as a streak along its own
     velocity (Light.drawLight). A quality governor gives up resolution, then every other point, then the streaks,
     if frames run late, and takes them back once frames are calm again.

     At rest (nothing travelling, pointer still) the twinkle is drawn on every second display frame. */
  function stageRenderer(scope) {
    "use strict";
    var Light = scope.Light;
    var TONES = [[95, 212, 196], [232, 192, 116], [255, 143, 120], [255, 240, 205]];
    var FADE_MS = 260, MOVE_MS = 1250, SPREAD_MS = 520, ARC_PX = 70, REST_FRAME_MS = 33;
    // The short openings: when the gathering starts and how long it lasts.
    var OPENINGS = { full: { full: true }, quick: { from: 80, gather: 520 }, lite: { from: 250, gather: 1350 } };
    // The full opening (ms from its start). The last borough lands at FULL_LAST_LAND.
    var IGNITE_MS = 450, IGNITE_FADE_MS = 650, BURST_TAU = 330, BURST_REACH = 0.55, GATHER_FROM = 1300, BOROUGH_STEP = 260,
        GATHER_EACH = 1050, GATHER_SPREAD = 380, BOROUGHS = 5, BOW = 0.28, RING_MS = 1000, FULL_WAVE_FROM = 3550;
    var FULL_LAST_LAND = GATHER_FROM + (BOROUGHS - 1) * BOROUGH_STEP + GATHER_SPREAD + GATHER_EACH;
    var FULL_FORMED_AT = GATHER_FROM + (BOROUGHS - 1) * BOROUGH_STEP + 0.85 * (GATHER_SPREAD + GATHER_EACH);
    var FLARE_MS = 520, WAVE_FROM = 2200, WAVE_MS = 800, WAVE_PX = 26, SKIP_MS = 350, FORMED_AT = 0.95;   // the words come in as the last sparks are landing
    var frame = self.requestAnimationFrame ? function (fn) { self.requestAnimationFrame(fn); }
                                           : function (fn) { setTimeout(function () { fn(performance.now()); }, 16); };
    var canvas = null, context = null, sprites = null, streaks = null, scale = 1, baseScale = 1, width = 0, height = 0;
    // gl: the points on the graphics processor (Light.Particles), on canvas; context then draws the chart's words and
    // the opening's flares on overlay, a second canvas laid over it. Without WebGL2 everything is drawn on canvas in 2D.
    var gl = null, overlay = null;
    var lite = false, reduced = false, visible = true;
    var n = 0, seeds = null, baseTones = null, rank = null, city = true, seq = 0;
    var current = null, from = null, to = null, startedAt = 0;
    var pointerX = 0, pointerY = 0, driftX = 0, driftY = 0;
    var running = false, lastDrawn = 0, waiting = true, opening = null, home = null, homeTop = 0, homeBottom = 0;
    var spark = null, grow = null, lit = null, prevX = null, prevY = null, prevNow = 0, freshVelocity = true;
    var mix = null, oldTone = null;       // a transition's progress per point, and the colours it leaves
    var heart = { x: 0, y: 0 }, boroughs = [], swirl = [0, 0];
    var markImage = null, oldImage = null, marksIn = 1;
    var governor = new Light.Governor(3);

    function easeInOut(t) { return t < 0.5 ? 8 * t * t * t * t : 1 - Math.pow(-2 * t + 2, 4) / 2; }
    function clamp01(t) { return t < 0 ? 0 : t > 1 ? 1 : t; }
    function copy(layout) {
      return { x: layout.x.slice(), y: layout.y.slice(), alpha: layout.alpha.slice(),
               size: layout.size ? layout.size.slice() : null, tone: layout.tone ? layout.tone.slice() : null };
    }
    function release(image) { if (image && image.close) { image.close(); } }

    /* The resolution follows the governor: level 1 and above draw at a lower device-pixel scale. */
    function applyScale() {
      scale = governor.level >= 1 ? Math.min(baseScale, 1 + (baseScale - 1) * 0.5) : baseScale;
      if (gl) { gl.resize(width, height, scale); overlay.width = Math.round(width * scale); overlay.height = Math.round(height * scale); }
      else { canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale); }
      sprites = TONES.map(function (rgb) { return Light.sprite(rgb, scale); });
      streaks = TONES.map(function (rgb) { return Light.capsule(rgb, scale); });
    }

    /* The words are stamped with the points' parallax, so a chart's dots stay on their axis. The image was painted at
       the page's scale; it is drawn at the canvas's size, whatever scale the governor has chosen since. */
    function stamp(image, opacity) {
      if (opacity <= 0.01 || !image) { return; }
      context.globalCompositeOperation = "source-over";
      context.globalAlpha = opacity;
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.drawImage(image, Math.round(driftX * scale), Math.round(driftY * scale), Math.round(width * scale), Math.round(height * scale));
      context.setTransform(scale, 0, 0, scale, 0, 0);
      context.globalAlpha = 1;
    }

    function settleAt(mode) { var plan = OPENINGS[mode]; return plan.full ? FULL_LAST_LAND + FLARE_MS : plan.from + plan.gather + FLARE_MS; }

    /* Where the city's light gathers from, and each borough's centre and reach, for the opening's rings. */
    function measureHome() {
      var sx = 0, sy = 0, i, b;
      homeTop = Infinity; homeBottom = -Infinity;
      boroughs = [];
      for (b = 0; b < BOROUGHS; b++) { boroughs.push({ x: 0, y: 0, count: 0, reach: 0 }); }
      for (i = 0; i < n; i++) {
        homeTop = Math.min(homeTop, home.y[i]); homeBottom = Math.max(homeBottom, home.y[i]);
        sx += home.x[i]; sy += home.y[i];
        var group = boroughs[rank[i]];
        group.x += home.x[i]; group.y += home.y[i]; group.count++;
      }
      heart.x = n ? sx / n : width / 2; heart.y = n ? sy / n : height / 2;
      boroughs.forEach(function (group) { if (group.count) { group.x /= group.count; group.y /= group.count; } });
      for (i = 0; i < n; i++) {
        var g = boroughs[rank[i]], dx = home.x[i] - g.x, dy = home.y[i] - g.y;
        g.reach += Math.sqrt(dx * dx + dy * dy);
      }
      boroughs.forEach(function (group) { group.reach = group.count ? group.reach / group.count * 1.7 : 0; });
    }

    /* One frame of the full opening. */
    function openFull(elapsed) {
      var reach = Math.sqrt(width * width + height * height) * BURST_REACH, since = Math.max(0, elapsed - IGNITE_MS);
      var out = 1 - Math.exp(-since / BURST_TAU), fadeIn = Math.min(1, since / 220), lit0 = elapsed >= IGNITE_MS;
      var wave = (elapsed - FULL_WAVE_FROM) / WAVE_MS, scanY = homeBottom - wave * (homeBottom - homeTop), i;
      for (i = 0; i < n; i++) {
        var hx = home.x[i], hy = home.y[i];
        var bx = heart.x + spark.bc[i] * spark.reach[i] * reach * out + spark.vx[i] * since / 1000;
        var by = heart.y + spark.bs[i] * spark.reach[i] * reach * out + spark.vy[i] * since / 1000;
        Light.flow(bx, by, elapsed, swirl);
        bx += swirl[0] * 12 * out; by += swirl[1] * 12 * out;     // once the burst has slowed, the sparks curl
        var landsFrom = GATHER_FROM + rank[i] * BOROUGH_STEP + spark.order[i] * GATHER_SPREAD;
        var t = Light.easeInOutCubic(clamp01((elapsed - landsFrom) / GATHER_EACH));
        if (t > 0) {
          // A curved path home: a quadratic curve whose middle is pushed to one side of the straight line.
          var dx = hx - bx, dy = hy - by, bend = spark.spin[i] * BOW, u = 1 - t;
          var kx = (bx + hx) / 2 - dy * bend, ky = (by + hy) / 2 + dx * bend;
          current.x[i] = u * u * bx + 2 * u * t * kx + t * t * hx;
          current.y[i] = u * u * by + 2 * u * t * ky + t * t * hy;
        } else { current.x[i] = bx; current.y[i] = by; }
        current.alpha[i] = lit0 ? home.alpha[i] * fadeIn * (0.5 + 0.5 * t) : 0;
        var landed = elapsed - (landsFrom + GATHER_EACH);
        var flare = landed >= 0 && landed < FLARE_MS ? 1 - landed / FLARE_MS : 0;
        var light = wave > 0 && wave < 1 ? Math.max(0, 1 - Math.abs(hy - scanY) / WAVE_PX) : 0;
        var burst = lit0 && since < 300 ? 1 - since / 300 : 0;   // a flash as the sparks leave the heart
        grow[i] = 1 + flare * 1.6 + light * 1.2 + burst * 0.4; lit[i] = Math.max(flare * 0.6, light, burst);
      }
    }

    /* One frame of the opening: writes each point's place, light and size into current, grow and lit. */
    function open(now) {
      var o = opening, plan = OPENINGS[o.mode], elapsed = now - o.start, i;
      if (o.skipAt) { elapsed = o.skipFrom + (now - o.skipAt) * o.rush; }
      o.elapsed = elapsed;
      var settle = settleAt(o.mode);
      if (plan.full) {
        openFull(elapsed);
        if (!o.formed && elapsed >= FULL_FORMED_AT) { o.formed = true; scope.postMessage({ type: "formed" }); }
        if (elapsed >= (o.skipAt ? settle : Math.max(settle, FULL_WAVE_FROM + WAVE_MS))) { finishOpening(); }
        return;
      }
      var fadeIn = Math.min(1, elapsed / 600), g = (elapsed - plan.from) / plan.gather;
      for (i = 0; i < n; i++) {
        var hx = home.x[i], hy = home.y[i], d = spark.delay[i];
        var t = easeInOut(Math.max(0, Math.min(1, (g - d) / (1 - d * 0.6))));
        var sx = spark.x[i] * width + spark.vx[i] * elapsed / 1000, sy = spark.y[i] * height + spark.vy[i] * elapsed / 1000;
        var turn = (1 - t) * spark.spin[i] * 1.8, dx = sx - hx, dy = sy - hy, cos = Math.cos(turn), sin = Math.sin(turn);
        current.x[i] = hx + (dx * cos - dy * sin) * (1 - t);
        current.y[i] = hy + (dx * sin + dy * cos) * (1 - t);
        current.alpha[i] = home.alpha[i] * Math.min(1, fadeIn * 0.6 + 0.4 * t);
        var since = elapsed - (plan.from + plan.gather * (d + 1 - d * 0.6));
        var flare = since >= 0 && since < FLARE_MS ? 1 - since / FLARE_MS : 0;
        grow[i] = 1 + flare * 1.6; lit[i] = flare * 0.6;
      }
      if (!o.formed && g >= FORMED_AT) { o.formed = true; scope.postMessage({ type: "formed" }); }
      if (elapsed >= settle) { finishOpening(); }
    }
    function finishOpening() {
      if (!opening) { return; }
      if (!opening.formed) { scope.postMessage({ type: "formed" }); }
      opening = null;
      if (home && !to) { current.x.set(home.x); current.y.set(home.y); current.alpha.set(home.alpha); }
      grow.fill(1); lit.fill(0);
    }

    /* The opening's own light, drawn over the points: the heart that ignites, and the ring that marks each borough. */
    function drawOpeningLights(elapsed) {
      if (elapsed < IGNITE_MS + IGNITE_FADE_MS) {
        var swell = Light.easeOutCubic(Math.min(1, elapsed / IGNITE_MS));
        var fade = elapsed < IGNITE_MS ? 1 : 1 - (elapsed - IGNITE_MS) / IGNITE_FADE_MS;
        var core = 8 + 110 * swell + (elapsed >= IGNITE_MS ? 90 * (1 - fade) : 0);
        context.globalAlpha = Math.max(0, fade);
        context.drawImage(sprites[3], heart.x - core / 2, heart.y - core / 2, core, core);
        var flareW = width * 0.9 * swell, flareH = 10 + 6 * swell;
        context.globalAlpha = Math.max(0, fade * 0.75);
        context.drawImage(streaks[3], heart.x - flareW / 2, heart.y - flareH / 2, flareW, flareH);
      }
      context.lineWidth = 1;
      for (var b = 0; b < BOROUGHS; b++) {
        var group = boroughs[b];
        if (!group || !group.count) { continue; }
        var age = (elapsed - (GATHER_FROM + b * BOROUGH_STEP + GATHER_SPREAD + GATHER_EACH * 0.9)) / RING_MS;
        if (age <= 0 || age >= 1) { continue; }
        context.globalAlpha = 0.32 * (1 - age);
        context.strokeStyle = "rgb(232,192,116)";
        context.beginPath(); context.arc(group.x + driftX, group.y + driftY, group.reach * (0.55 + 0.7 * age), 0, 6.283); context.stroke();
      }
      context.globalAlpha = 1;
    }

    function draw(now) {
      running = false;
      if (!current || !sprites || waiting) { return; }
      var count = n, i, more = false, settled = !to;
      if (opening) { open(now); more = true; }
      var resting = settled && !opening && !more && Math.abs(pointerX - driftX) < 0.2 && Math.abs(pointerY - driftY) < 0.2;
      if (resting && !Light.cadence(now, lastDrawn, REST_FRAME_MS)) { if (visible && !reduced) { kick(); } return; }
      lastDrawn = now;
      if (to) {
        var elapsed = now - startedAt, fade = Math.min(1, elapsed / FADE_MS), finished = true;
        for (i = 0; i < count; i++) {
          var local = Math.min(1, Math.max(0, (elapsed - FADE_MS - seeds.delay[i] * SPREAD_MS) / MOVE_MS));
          if (local < 1) { finished = false; }
          var move = easeInOut(local), leaving = to.alpha[i] < from.alpha[i];
          mix[i] = move;
          current.alpha[i] = leaving ? from.alpha[i] + (to.alpha[i] - from.alpha[i]) * fade : from.alpha[i] + (to.alpha[i] - from.alpha[i]) * move;
          // A curved path: the particle swings out to one side and comes back, as if carried by a current.
          var dx = to.x[i] - from.x[i], dy = to.y[i] - from.y[i], bow = Math.sin(Math.PI * move) * seeds.arc[i];
          var length = Math.sqrt(dx * dx + dy * dy) || 1;
          current.x[i] = from.x[i] + dx * move - dy / length * bow;
          current.y[i] = from.y[i] + dy * move + dx / length * bow;
          if (from.size && to.size) { current.size[i] = from.size[i] + (to.size[i] - from.size[i]) * move; }
        }
        marksIn = Math.max(0, Math.min(1, (elapsed - FADE_MS - MOVE_MS * 0.55) / 500));
        if (finished && marksIn >= 1) { from = to = null; oldTone = null; release(oldImage); oldImage = null; current.tone = current.toneNext || current.tone; } else { more = true; }
      }
      if (reduced) { pointerX = pointerY = driftX = driftY = 0; }    // no parallax for a reader who asked for less motion
      driftX += (pointerX - driftX) * 0.06; driftY += (pointerY - driftY) * 0.06;
      if (Math.abs(pointerX - driftX) > 0.2 || Math.abs(pointerY - driftY) > 0.2) { more = true; }

      // Frames that run at the display's full rate are timed; the resting twinkle, throttled on purpose, is not.
      if (more && !lite && !reduced) { if (governor.tick(now)) { applyScale(); } } else { governor.pause(); }
      // Motion blur wherever the points move: in the opening, between chapters, and when the parallax carries them.
      var drifting = Math.abs(pointerX - driftX) > 0.05 || Math.abs(pointerY - driftY) > 0.05;
      // On the graphics processor every moving point is blurred, on a phone too; on the 2D canvas not on a phone.
      var dt = now - prevNow, blur = (gl || !lite) && !reduced && governor.level < 3 && (opening || to || drifting) && !freshVelocity && dt > 0 && dt < 100;
      prevNow = now; freshVelocity = false;

      context.setTransform(scale, 0, 0, scale, 0, 0);
      context.clearRect(0, 0, width, height);
      var tones = current.tone || baseTones;
      if (lite && !gl) {
        // On a phone without WebGL2 each point is a small square of its colour, drawn one colour at a time: no scaled sprites and
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
      var step = governor.level >= 2 ? 2 : 1, boost = step > 1 ? 1.15 : 1;
      for (i = 0; i < count; i++) {
        var x = current.x[i] + driftX, y = current.y[i] + driftY;     // where it is drawn, parallax included
        var vx = blur ? (x - prevX[i]) / dt : 0, vy = blur ? (y - prevY[i]) / dt : 0;
        prevX[i] = x; prevY[i] = y;
        var a = current.alpha[i];
        // Under load every other point is skipped, but never a large one: in a chart of a few big dots (chapter 4)
        // a skipped dot would blink out of the chart.
        if (a <= 0.01 || (step > 1 && i % step && (current.size ? current.size[i] : seeds.size[i]) < 7)) { continue; }
        // Buildings with more homes burn a little larger; in the opening a point flares as it lands.
        var size = (current.size ? current.size[i] : seeds.size[i]) * grow[i] * boost;
        var twinkle = reduced || lite ? 1 : 0.86 + 0.14 * Math.sin(now * seeds.rate[i] + seeds.phase[i]);
        // In a chart the points breathe in place, a pixel at most, so the chart stays exact but alive.
        var float = !reduced && !lite && settled && !city ? Math.sin(now * seeds.rate[i] * 0.7 + seeds.phase[i]) * 0.8 : 0;
        var which = lit[i] > 0.35 ? 3 : tones[i], glow = a * twinkle + lit[i] * 0.5;
        if (oldTone && oldTone[i] !== 255 && oldTone[i] !== which && mix[i] < 1) {
          // A point that changes meaning crossfades from its old colour to its new one along the way.
          var was = oldTone[i];
          if (gl) { gl.add(x, y + float, blur ? vx : 0, blur ? vy : 0, size, glow * (1 - mix[i]), was); }
          else { Light.drawLight(context, sprites[was], blur ? streaks[was] : null, x, y + float, vx, vy, size, glow * (1 - mix[i]), scale); }
          glow *= mix[i];
        }
        if (gl) { gl.add(x, y + float, blur ? vx : 0, blur ? vy : 0, size, glow, which); }
        else { Light.drawLight(context, sprites[which], blur ? streaks[which] : null, x, y + float, vx, vy, size, glow, scale); }
      }
      if (gl) { gl.render(true, true); }            // every light, in one call
      if (lite && !gl) { prevX.set(current.x); prevY.set(current.y); }
      if (opening && OPENINGS[opening.mode].full) { drawOpeningLights(opening.elapsed); }
      context.globalCompositeOperation = "source-over";
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
      if (reduced) { current = target; from = to = null; release(oldImage); oldImage = null; marksIn = 1; freshVelocity = true; return; }
      lastDrawn = 0;
      // The colours a point leaves, so it can crossfade to the colour it will have when it lands.
      oldTone = (current.tone || baseTones).slice();
      current.tone = target.tone || null; current.toneNext = current.tone;
      from = copy(current); to = target; startedAt = performance.now();
      var landing = target.tone || baseTones;
      for (var i = 0; i < n; i++) {
        seeds.arc[i] = (Math.random() - 0.5) * 2 * ARC_PX;
        mix[i] = 0;
        if (oldTone[i] === landing[i]) { oldTone[i] = 255; }       // no crossfade needed (255 matches no tone)
      }
    }

    function handle(message) {
      switch (message.type) {
        case "init":
          canvas = message.canvas; overlay = message.overlay || null; n = message.n; baseTones = message.tones;
          gl = overlay ? Light.Particles(canvas, 0.95) : null;
          if (gl) { gl.setTones(TONES); context = overlay.getContext("2d"); } else { context = canvas.getContext("2d"); }
          seeds = { size: message.size, rate: message.rate, phase: message.phase, delay: message.delay, arc: new Float32Array(message.n) };
          rank = message.rank || new Uint8Array(n);
          lite = message.lite; reduced = message.reduced; visible = message.visible !== false;
          grow = new Float32Array(n).fill(1); lit = new Float32Array(n); prevX = new Float32Array(n); prevY = new Float32Array(n);
          mix = new Float32Array(n).fill(1);
          spark = { x: new Float32Array(n), y: new Float32Array(n), vx: new Float32Array(n), vy: new Float32Array(n),
                    spin: new Float32Array(n), delay: new Float32Array(n), order: new Float32Array(n),
                    bc: new Float32Array(n), bs: new Float32Array(n), reach: new Float32Array(n) };
          for (var k = 0; k < n; k++) {
            var heading = Math.random() * 6.283, pace = 8 + Math.random() * 22, aim = Math.random() * 6.283;
            spark.x[k] = Math.random(); spark.y[k] = Math.random();
            spark.vx[k] = Math.cos(heading) * pace; spark.vy[k] = Math.sin(heading) * pace;
            spark.spin[k] = (Math.random() < 0.5 ? -1 : 1) * (0.6 + Math.random() * 1.1);
            spark.delay[k] = Math.random() * 0.5;
            spark.order[k] = Math.random();
            // The burst: every direction, and reaches spread so the sparks cover the stage evenly, not in a ring.
            spark.bc[k] = Math.cos(aim); spark.bs[k] = Math.sin(aim); spark.reach[k] = 0.12 + 0.88 * Math.sqrt(Math.random());
          }
          break;
        case "resize":
          seq = message.seq; width = message.width; height = message.height; baseScale = message.scale; lite = message.lite; city = message.city;
          applyScale();
          current = copy(message.layout); from = to = null; marksIn = 1; freshVelocity = true;
          if (message.city) {                 // the city is where the opening lands
            home = copy(message.layout);
            measureHome();
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
        case "stats": scope.postMessage({ type: "stats", stats: governor.stats() }); break;
        case "start":
          waiting = false;
          if (OPENINGS[message.mode] && home && !reduced) { opening = { mode: message.mode, start: performance.now(), formed: false, elapsed: 0 }; lastDrawn = 0; }
          else { scope.postMessage({ type: "formed" }); }
          break;
        case "skip":
          if (opening && !opening.skipAt) {
            var o = opening, now = performance.now(), at = now - o.start, finish = settleAt(o.mode);
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
    // The chart's words and the opening's flares are drawn on a second canvas laid over the points (the points are on
    // the graphics processor where it is offered). Hidden from screen readers: the first canvas carries the name.
    function layer(after) {
      var element = document.createElement("canvas");
      element.className = canvas.className; element.setAttribute("aria-hidden", "true");
      after.parentNode.insertBefore(element, after.nextSibling);
      return element;
    }
    var overlay = layer(canvas), overlayTarget = overlay;
    // On a phone (NYC.lite) the canvas draws at one device pixel, plays a shorter opening and draws only while the
    // points travel, so it never competes with the reader's scrolling. The mode is read live (00-motion.js decides it
    // again when the window crosses the phone width), so a window that widens gets the full lights back.
    function isLite() { return !!(NYC.lite && NYC.lite()); }
    function scaleNow() { return isLite() ? 1 : Math.min(window.devicePixelRatio || 1, MAX_SCALE); }

    /* The renderer's host: a worker drawing on the canvas it was handed, or, where that is not offered, this page. */
    function onPage(target, over) {
      overlayTarget = over;
      var local = { postMessage: function (message) { heard({ data: message }); } };
      NYC.lightKit(local);
      stageRenderer(local);
      thread = null;
      send = function (message) { local.onmessage({ data: message }); };
      return target;
    }
    function connect() {
      if (!canvas.transferControlToOffscreen || !window.Worker || !window.Blob || !window.URL) { return onPage(canvas, overlay); }
      var worker;
      try {
        worker = new Worker(URL.createObjectURL(new Blob(["(" + NYC.lightKit + ")(self);(" + stageRenderer + ")(self);"], { type: "text/javascript" })));
      } catch (error) { return onPage(canvas, overlay); }
      var offscreen;
      try { offscreen = canvas.transferControlToOffscreen(); overlayTarget = overlay.transferControlToOffscreen(); }
      catch (error) { worker.terminate(); return onPage(canvas, overlay); }
      thread = worker;
      worker.onmessage = heard;
      send = function (message, transfer) { worker.postMessage(message, transfer || []); };
      // If the worker ever fails, the page takes over on a fresh canvas laid over the first (which it can no longer
      // draw on); the first keeps its accessible name, the new one is hidden from screen readers.
      worker.addEventListener("error", function () {
        if (thread !== worker) { return; }
        worker.terminate();
        var fresh = layer(overlay), freshOver = layer(fresh);
        init.canvas = onPage(fresh, freshOver); init.overlay = freshOver; init.visible = visible;
        send(init);
        resize();
        send({ type: "start", mode: "none" });
      });
      return offscreen;
    }

    /* What the renderer says back: the city has formed, so the words beside it may come in. */
    function heard(event) {
      if (!event.data) { return; }
      if (event.data.type === "formed" && NYC.opened) { NYC.opened(); }
      if (event.data.type === "stats" && NYC.reportStats) { NYC.reportStats("stage", event.data.stats); }
    }
    if (NYC.lightReporter) { NYC.lightReporter(function () { if (send) { send({ type: "stats" }); } }); }

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
      // The opening gathers the boroughs from south to north: each building's place in that order.
      var rank = new Uint8Array(n), names = data.boroughs || [];
      for (i = 0; i < n; i++) { rank[i] = boroughRank(names[data.borough ? data.borough[i] : -1]); }
      var target = connect();
      init = { type: "init", canvas: target, overlay: overlayTarget, n: n, size: seeds.size, rate: seeds.rate, phase: seeds.phase, delay: seeds.delay,
               tones: data.new, rank: rank, lite: isLite(), reduced: NYC.reducedMotion(), visible: visible };
      send(init, thread ? [target, overlayTarget] : []);
      init.canvas = init.overlay = null;            // handed over; a fallback fills in its own
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
