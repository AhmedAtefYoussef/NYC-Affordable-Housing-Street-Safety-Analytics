/* The Generate report sequence. When the reader asks for a report, the screen goes dark and the city is rebuilt from
   its own buildings, the same points of light as the opening, slowly enough to watch:

     veil      every building is a spark of dust, curling on a slow current across the screen
     gather    borough by borough, south to north, the sparks stream home on curved paths, streaked by their speed;
               each borough glows once as its last buildings land
     weave     threads of light join neighbouring buildings, south to north, until the city is a lit street network
     measure   an unseen sweep crosses the city; the buildings it passes flare, and 250 m rings pulse at real sites.
               It loops calmly for as long as the report is still being built
     collapse  when the report is ready, the city draws a breath, then every light spirals into the centre,
               faster and faster, streaked by its own speed
     burst     the gathered light blazes as a star with a long flare, then flies back out, every building on its own
               ray; a shockwave ring runs ahead of it and cuts the dark open onto the report, which zooms out into
               place as the wave passes

   Real steps of the work are named as it runs. Dash's own `running` state on #report (class is-loading) says when
   the work starts and ends; MIN_MS keeps the sequence whole even when the answer is instant. Escape, or a press on
   the screen, skips to the end once the report is ready. Not shown for the report drawn on page load. Under reduced
   motion it is a plain notice with a bar.

   Smoothness. Every frame of light is drawn by reportRenderer below. Where the browser can hand a canvas to a worker
   (OffscreenCanvas), it runs on its own thread, so building the charts on the page never holds up a frame; the
   click is then passed on to Dash almost at once (RELEASE_WORKER_MS) and a slow first answer is hidden inside the
   sequence. Elsewhere the same renderer runs on the page and the click waits until the city has gathered
   (RELEASE_PAGE_MS), so the work falls in the calm of the sweep. The canvas paints its own dark ground and thins it
   itself during the shockwave, so the browser never animates a full-screen mask beside it, and the page moves to the
   report while it is still fully covered. */
(function () {
  "use strict";

  var NYC = window.NYC;
  // The plain notice (reduced motion, or no canvas) only needs to be readable, not watched: PLAIN_MIN_MS.
  var MIN_MS = 5800, PLAIN_MIN_MS = 1200, OUT_MS = 2500, MAX_WAIT_MS = 15000, POLL_MS = 80, MAX_SCALE = 1.5;
  var RELEASE_WORKER_MS = 300, RELEASE_PAGE_MS = 4300;
  // When each step of the work is named, in ms from the start (matched to the phases drawn below).
  var STEP_AT = [0, 900, 3000, 4500, 5400];
  var BOROUGH_ORDER = ["staten island", "brooklyn", "queens", "manhattan", "bronx"];

  /* The renderer. Self-contained apart from scope.Light (05-light.js, sent in front of it), because it is also sent,
     as text, to a worker. Messages:

       data     { n, x, y, aspect, tone, size, rank }   the buildings, once (x and y from 0 to 1)
       open     { canvas, particles, width, height, scale, lite }   a new overlay: start the sequence (particles: the
                canvas for the lights on the graphics processor, laid over canvas; null to draw them in 2D)
       finish   the report is ready and in place: collapse and burst
       close    stop drawing
       stats    reply with the frame times ({ type: "stats" }) */
  function reportRenderer(scope) {
    "use strict";
    var Light = scope.Light;
    var TONES = [[95, 212, 196], [232, 192, 116], [255, 143, 120], [255, 240, 205]];
    var MAX_POINTS = 5200, LITE_POINTS = 2200, MAX_LINKS = 900, LITE_LINKS = 300, LINK_PX = 18, RINGS = 7;
    var VEIL_MS = 600, GATHER_FROM = 700, BOROUGH_STEP = 400, GATHER_EACH = 1600, GATHER_SPREAD = 400, BOW = 0.3;
    var WEAVE_FROM = 4300, WEAVE_MS = 1000, SCAN_FROM = 5300, SCAN_MS = 2400, FLARE_MS = 600, PULSE_MS = 700;
    // The exit, collapse and shockwave (ms after the report is ready):
    //   inhale    to IMPLODE_FROM             the city draws a breath: it swells by INHALE and brightens
    //   collapse  to BURST_FROM               every light spirals into the centre, faster and faster, streaked by its speed
    //   burst     to BURST_FROM + BURST_MS    the light gathered there blazes as a star (STAR_PX), then flies back out,
    //                                         each building on its own ray; a shockwave ring runs ahead over SHOCK_MS
    //                                         and cuts the dark open onto the report
    var IMPLODE_FROM = 380, BURST_FROM = 1150, BURST_MS = 1300, SHOCK_MS = 1100, INHALE = 0.035, SPIRAL = 0.9;
    var STAR_PX = 150, EXIT_STREAK_PX = 150, SHOCK_EDGE_PX = 70, EXIT_MS = BURST_FROM + BURST_MS;
    var frame = self.requestAnimationFrame ? function (fn) { return self.requestAnimationFrame(fn); }
                                           : function (fn) { return setTimeout(function () { fn(performance.now()); }, 16); };
    var cancel = self.cancelAnimationFrame ? function (id) { self.cancelAnimationFrame(id); } : function (id) { clearTimeout(id); };
    var data = null, canvas = null, context = null, width = 0, height = 0, baseScale = 1, scale = 1, lite = false;
    var sprites = null, streaks = null, ground = null, raf = 0, startedAt = 0, diveAt = 0, prevNow = 0, fresh = true;
    var points = null, links = null, groups = null, rings = [], swirl = [0, 0], cx = 0, cy = 0, cityTop = 0, cityBottom = 0, governor = null;
    var city = null, cityScale = 0;       // the formed city as one image, for the 2D canvas only (cityImage)
    // gl: the lights on the graphics processor (Light.Particles) on a second canvas over this one; context then draws
    // only the ground, the threads, the sweep and the shockwave. Without WebGL2 the lights are drawn here in 2D.
    var gl = null, exitReady = false, reachMax = 0, at = [0, 0];

    function clamp01(t) { return t < 0 ? 0 : t > 1 ? 1 : t; }
    function easeInOut(t) { return t < 0.5 ? 8 * t * t * t * t : 1 - Math.pow(-2 * t + 2, 4) / 2; }

    /* The ground: the page colour with a faint glow behind the city, and a dither of single steps of light and
       shade, so the dark gradient shows no bands on an 8-bit screen. */
    function groundLayer() {
      var layer = Light.surface(Math.round(width * scale), Math.round(height * scale)), g = layer.getContext("2d");
      g.setTransform(scale, 0, 0, scale, 0, 0);
      var glow = g.createRadialGradient(cx, cy, 0, cx, cy, Math.max(width, height) * 0.7);
      glow.addColorStop(0, "#10162b"); glow.addColorStop(1, "#0a0d1a");
      g.fillStyle = glow; g.fillRect(0, 0, width, height);
      var TILE = 64, tile = Light.surface(TILE, TILE), t = tile.getContext("2d"), noise = t.createImageData(TILE, TILE);
      for (var k = 0; k < noise.data.length; k += 4) {
        var roll = Math.random();
        // White at 1/255 lifts a dark pixel one step; black at 12/255 lowers it one step; a third stay as they are.
        if (roll < 0.333) { noise.data[k] = noise.data[k + 1] = noise.data[k + 2] = 255; noise.data[k + 3] = 1; }
        else if (roll < 0.667) { noise.data[k + 3] = 12; }
      }
      t.putImageData(noise, 0, 0);
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.fillStyle = g.createPattern(tile, "repeat"); g.fillRect(0, 0, layer.width, layer.height);
      return layer;
    }

    function applyScale() {
      scale = governor.level >= 1 ? Math.min(baseScale, 1 + (baseScale - 1) * 0.5) : baseScale;
      canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale);
      if (gl) { gl.resize(width, height, scale); }
      sprites = TONES.map(function (rgb) { return Light.sprite(rgb, scale, 1, 12); });
      streaks = TONES.map(function (rgb) { return Light.capsule(rgb, scale, 1, 12); });
      ground = groundLayer();
      context = canvas.getContext("2d");
      city = null;
    }

    /* One record per building drawn: where it starts, where it lands, and its own timing. Then each borough's centre
       and landing time, and the threads between near neighbours. */
    function build() {
      var n = data ? data.n : 2400, aspect = data ? data.aspect : 0.82, out = [], i, k;
      var stride = Math.max(1, n / (lite ? LITE_POINTS : MAX_POINTS));
      var drawH = Math.min(height * 0.68, width * 0.9 / aspect), drawW = drawH * aspect;
      var left = (width - drawW) / 2, top = height * 0.42 - drawH / 2;
      cx = width / 2; cy = height * 0.42; cityTop = top - 30; cityBottom = top + drawH + 30;
      reachMax = Math.sqrt(Math.pow(Math.max(cx, width - cx), 2) + Math.pow(Math.max(cy, height - cy), 2));
      groups = [];
      for (k = 0; k < 5; k++) { groups.push({ x: 0, y: 0, count: 0, done: 0 }); }
      for (k = 0; k < n; k += stride) {
        i = Math.floor(k);
        var angle = Math.random() * 6.283, spread = Math.random();
        var p = {
          sx: width * Math.random(), sy: height * Math.random(),
          vx: Math.cos(angle) * (6 + spread * 14), vy: Math.sin(angle) * (6 + spread * 14),
          tx: data ? left + data.x[i] * drawW : cx + Math.cos(angle) * drawH * 0.3 * Math.sqrt(spread),
          ty: data ? top + (1 - data.y[i]) * drawH : cy + Math.sin(angle) * drawH * 0.3 * Math.sqrt(spread),
          tone: data ? data.tone[i] : (i % 2), size: data ? data.size[i] : 4, rank: data ? data.rank[i] : Math.floor(Math.random() * 5),
          order: Math.random(), bend: (Math.random() < 0.5 ? -1 : 1) * (0.4 + Math.random() * 0.8),
          rate: 0.0012 + Math.random() * 0.0018, phase: Math.random() * 6.283, px: 0, py: 0,
          ex: 0, ey: 0, ea: 0, dirX: 1, dirY: 0, reach: 0, lag: 0, spin: 1
        };
        p.lands = GATHER_FROM + p.rank * BOROUGH_STEP + p.order * GATHER_SPREAD + GATHER_EACH;
        var group = groups[p.rank];
        group.x += p.tx; group.y += p.ty; group.count++; group.done = Math.max(group.done, p.lands);
        out.push(p);
      }
      groups.forEach(function (g) { if (g.count) { g.x /= g.count; g.y /= g.count; } });
      points = out;
      links = weave(out, lite ? LITE_LINKS : MAX_LINKS);
    }

    /* Threads: for sampled buildings, the nearest other building within LINK_PX (found through a grid of LINK_PX
       cells), at most one thread each, ordered from the south of the city to the north. */
    function weave(list, limit) {
      var cells = {}, i, key, found = [];
      for (i = 0; i < list.length; i++) {
        key = Math.floor(list[i].tx / LINK_PX) + ":" + Math.floor(list[i].ty / LINK_PX);
        (cells[key] || (cells[key] = [])).push(i);
      }
      var order = list.map(function (_, index) { return index; });
      for (i = order.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)), swap = order[i]; order[i] = order[j]; order[j] = swap; }
      for (var o = 0; o < order.length && found.length < limit; o++) {
        var a = list[order[o]], gx = Math.floor(a.tx / LINK_PX), gy = Math.floor(a.ty / LINK_PX), best = null, bestD = LINK_PX * LINK_PX;
        for (var ox = -1; ox <= 1; ox++) {
          for (var oy = -1; oy <= 1; oy++) {
            (cells[(gx + ox) + ":" + (gy + oy)] || []).forEach(function (index) {
              var b = list[index], dx = b.tx - a.tx, dy = b.ty - a.ty, d = dx * dx + dy * dy;
              if (d > 4 && d < bestD) { bestD = d; best = b; }
            });
          }
        }
        if (best) { found.push([a.tx, a.ty, best.tx, best.ty, Math.max(a.ty, best.ty)]); }
      }
      found.sort(function (p, q) { return q[4] - p[4]; });
      return found;
    }

    /* Where a building is at e ms: drifting on the current, then on its curved path home. Writes at[]; returns how far
       home it is (0 to 1). */
    function place(p, e) {
      var dx0 = p.sx + p.vx * e / 1000, dy0 = p.sy + p.vy * e / 1000;
      Light.flow(p.sx, p.sy, e, swirl);
      dx0 += swirl[0] * 22; dy0 += swirl[1] * 22;
      var t = Light.easeInOutCubic(clamp01((e - (p.lands - GATHER_EACH)) / GATHER_EACH));
      if (t > 0) {
        var ddx = p.tx - dx0, ddy = p.ty - dy0, u = 1 - t;
        var kx = (dx0 + p.tx) / 2 - ddy * p.bend * BOW, ky = (dy0 + p.ty) / 2 + ddx * p.bend * BOW;
        at[0] = u * u * dx0 + 2 * u * t * kx + t * t * p.tx;
        at[1] = u * u * dy0 + 2 * u * t * ky + t * t * p.ty;
      } else { at[0] = dx0; at[1] = dy0; }
      return t;
    }

    /* The exit starts from wherever each building is (the formed city, or still on its way if the reader skipped):
       its place, its light, the ray it will fly out on and how far. The rays are spread evenly round the full circle
       (golden-angle order), so the blast is symmetric even though the city's weight sits to one side of its centre. */
    function prepareExit(e) {
      for (var i = 0; i < points.length; i++) {
        var p = points[i], t = place(p, e);
        p.ex = at[0]; p.ey = at[1]; p.ea = clamp01(e / VEIL_MS) * (0.3 + 0.6 * t);
        var dx = p.ex - cx, dy = p.ey - cy, ray = i * 2.399963 + (Math.random() - 0.5) * 0.05;
        p.dirX = Math.cos(ray); p.dirY = Math.sin(ray);
        p.reach = (0.35 + 0.75 * Math.sqrt(Math.random())) * reachMax;
        p.lag = Math.random() * 0.35;
        p.spin = (dx * p.vy - dy * p.vx >= 0 ? 1 : -1) * (0.6 + Math.random() * 0.6);
      }
      exitReady = true;
    }

    /* The formed city as one image, for the 2D canvas: once every building has landed and the threads are woven,
       nothing in it moves until the exit, so it is drawn once and stamped each frame. (On the graphics processor
       every light is drawn each frame anyway, at no real cost.) */
    function cityImage() {
      if (city && cityScale === scale) { return city; }
      city = Light.surface(canvas.width, canvas.height); cityScale = scale;
      var g = city.getContext("2d");
      g.setTransform(scale, 0, 0, scale, 0, 0);
      g.globalCompositeOperation = "lighter";
      g.globalAlpha = 0.22; g.strokeStyle = "rgb(150,214,204)"; g.lineWidth = 0.7;
      g.beginPath();
      links.forEach(function (link) { g.moveTo(link[0], link[1]); g.lineTo(link[2], link[3]); });
      g.stroke();
      for (var i = 0; i < points.length; i++) {
        var p = points[i];
        g.globalAlpha = 0.9;
        g.drawImage(sprites[p.tone], p.tx - p.size / 2, p.ty - p.size / 2, p.size, p.size);
      }
      return city;
    }

    /* One light: on the graphics processor, or on the 2D canvas. (vx, vy) in CSS px per ms; zero for no blur. */
    function light(x, y, vx, vy, size, alpha, tone) {
      if (gl) { gl.add(x, y, vx, vy, size, alpha, tone); return; }
      Light.drawLight(context, sprites[tone], vx || vy ? streaks[tone] : null, x, y, vx, vy, size, alpha, scale);
    }

    function draw(now) {
      raf = 0;
      if (!context || !points) { return; }
      if (governor.tick(now)) { applyScale(); }
      var e = now - startedAt, dt = now - prevNow, blur = (gl || !lite) && governor.level < 3 && !fresh && dt > 0 && dt < 100;
      prevNow = now; fresh = false;
      var since = diveAt ? now - diveAt : 0, exiting = diveAt > 0;
      if (exiting && !exitReady) { prepareExit(e - since); }
      var veil = clamp01(e / VEIL_MS), scanning = e > SCAN_FROM && !exiting, scan = ((e - SCAN_FROM) % SCAN_MS) / SCAN_MS;
      var scanY = cityTop + scan * (cityBottom - cityTop), formed = !exiting && e >= SCAN_FROM, i, p, vx, vy;
      // The exit's curves.
      var breath = exiting ? easeInOut(clamp01(since / IMPLODE_FROM)) : 0, swell = 1 + INHALE * breath;
      var burst = exiting ? clamp01((since - BURST_FROM) / BURST_MS) : 0, bursting = exiting && since >= BURST_FROM;
      var shock = bursting ? Light.easeOutCubic(clamp01((since - BURST_FROM) / SHOCK_MS)) : 0;
      var gather = exiting && since < BURST_FROM ? Math.pow(clamp01((since - IMPLODE_FROM - 300) / (BURST_FROM - IMPLODE_FROM - 300)), 2) : 0;
      var star = Math.max(gather, bursting ? Math.exp(-(since - BURST_FROM) / 240) : 0);
      if (gl) { gl.maxStreak = exiting ? EXIT_STREAK_PX : 48; }

      // The ground canvas: the dark, opened by the shockwave; the threads; the sweep and its rings.
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.globalCompositeOperation = "source-over";
      context.clearRect(0, 0, canvas.width, canvas.height);
      var radius = shock * (reachMax + SHOCK_EDGE_PX);
      if (radius < reachMax + SHOCK_EDGE_PX - 1) {
        context.globalAlpha = 1;
        context.drawImage(ground, 0, 0);
        if (radius > 0) {
          // The shockwave cuts the dark away inside its ring, with a soft edge (a fill of the canvas itself, so the
          // browser never animates a full-screen mask beside it).
          context.setTransform(scale, 0, 0, scale, 0, 0);
          context.globalCompositeOperation = "destination-out";
          var hole = context.createRadialGradient(cx, cy, Math.max(0, radius - SHOCK_EDGE_PX), cx, cy, radius);
          hole.addColorStop(0, "rgba(0,0,0,1)"); hole.addColorStop(1, "rgba(0,0,0,0)");
          context.fillStyle = hole;
          context.beginPath(); context.arc(cx, cy, radius, 0, 6.283); context.fill();
        }
      }
      context.setTransform(scale, 0, 0, scale, 0, 0);
      context.globalCompositeOperation = "lighter";
      if (radius > 0 && shock < 1) {
        // The wave front itself: a bright thin ring with a soft halo, fading as it spreads.
        var front = 0.9 * Math.pow(1 - shock, 0.7), at0 = Math.max(1, radius - SHOCK_EDGE_PX * 0.5);
        context.strokeStyle = "rgb(255,236,200)";
        context.globalAlpha = front * 0.16; context.lineWidth = 22;
        context.beginPath(); context.arc(cx, cy, at0, 0, 6.283); context.stroke();
        context.globalAlpha = front; context.lineWidth = 2;
        context.beginPath(); context.arc(cx, cy, at0, 0, 6.283); context.stroke();
      }
      // The threads: woven from the south; in the exit they swell with the city's breath and are gone as it collapses.
      var threads = exiting ? 0.22 * (1 + 1.5 * breath) * (1 - clamp01((since - IMPLODE_FROM) / 350)) : 0.22;
      if (e > WEAVE_FROM && links.length && threads > 0.01 && (gl || !formed)) {
        var shown = exiting ? links.length : Math.floor(links.length * Light.easeInOutCubic(clamp01((e - WEAVE_FROM) / WEAVE_MS)));
        context.setTransform(scale * swell, 0, 0, scale * swell, cx * scale * (1 - swell), cy * scale * (1 - swell));
        context.globalAlpha = threads;
        context.strokeStyle = "rgb(150,214,204)"; context.lineWidth = 0.7;
        context.beginPath();
        for (var l = 0; l < shown; l++) { var link = links[l]; context.moveTo(link[0], link[1]); context.lineTo(link[2], link[3]); }
        context.stroke();
        context.setTransform(scale, 0, 0, scale, 0, 0);
      }
      if (scanning) {
        // The sweep itself is not drawn (no line, no band): it shows only in the buildings it lights as it passes,
        // and in the 250 m rings that pulse at real sites it has just passed.
        if (rings.length < RINGS && Math.random() < 0.05) {
          var pick = points[Math.floor(Math.random() * points.length)];
          if (Math.abs(pick.ty - scanY) < 40) { rings.push({ x: pick.tx, y: pick.ty, born: now }); }
        }
      }
      context.globalCompositeOperation = "source-over";
      rings = rings.filter(function (ring) {
        var age = (now - ring.born) / 1400;
        if (age >= 1 || exiting) { return false; }
        context.globalAlpha = 1;
        context.strokeStyle = "rgba(255,143,120," + (0.7 * (1 - age)).toFixed(3) + ")";
        context.lineWidth = 1.2;
        context.beginPath(); context.arc(ring.x, ring.y, 4 + age * 26, 0, 6.283); context.stroke();
        return true;
      });
      context.globalCompositeOperation = "lighter";

      // The lights.
      if (!gl && formed) {
        // 2D only: the formed city, stamped whole and breathing softly, then the few buildings under the sweep.
        context.setTransform(1, 0, 0, 1, 0, 0);
        context.globalAlpha = 0.94 + 0.06 * Math.sin(now * 0.0021);
        context.drawImage(cityImage(), 0, 0);
        context.setTransform(scale, 0, 0, scale, 0, 0);
      }
      var step = !gl && (governor.level >= 2 || exiting) ? 2 : 1, boost = step > 1 ? 1.2 : 1;
      for (i = 0; i < points.length; i++) {
        p = points[i];
        if (step > 1 && i % step) { continue; }
        var x, y, alpha, size, tone = p.tone;
        if (exiting) {
          if (!bursting) {
            // Collapse: in toward the centre on a tightening spiral, accelerating; brighter as the light gathers.
            var from = IMPLODE_FROM + p.lag * (BURST_FROM - IMPLODE_FROM), k = clamp01((since - from) / (BURST_FROM - from));
            k = k * k * k;
            var turn = k * SPIRAL * p.spin, c = Math.cos(turn), s = Math.sin(turn), ox = (p.ex - cx) * swell * (1 - k), oy = (p.ey - cy) * swell * (1 - k);
            x = cx + ox * c - oy * s; y = cy + ox * s + oy * c;
            alpha = p.ea * (1 + 0.3 * breath) * (1 + 0.8 * k); size = p.size * boost * (1 - 0.5 * k);
          } else {
            // Burst: out along its own ray, fast then slowing, fading as it goes.
            var out = 1 - Math.pow(1 - burst, 4);
            x = cx + p.dirX * p.reach * out; y = cy + p.dirY * p.reach * out;
            alpha = Math.min(1, p.ea * 1.4) * Math.pow(1 - burst, 1.6); size = p.size * boost * (1.35 - 0.6 * burst);
          }
        } else {
          var t = place(p, e);
          x = at[0]; y = at[1];
          var landed = e - p.lands, flare = landed >= 0 && landed < FLARE_MS ? 1 - landed / FLARE_MS : 0;
          var pulseAge = e - groups[p.rank].done, pulse = pulseAge >= 0 && pulseAge < PULSE_MS ? Math.sin(Math.PI * pulseAge / PULSE_MS) : 0;
          var swept = scanning && t >= 1 ? Math.max(0, 1 - Math.abs(y - scanY) / 26) : 0;
          var lit = Math.max(flare * 0.7, pulse * 0.4, swept);
          alpha = veil * (0.3 + 0.6 * t + 0.1 * Math.sin(now * p.rate + p.phase)) + lit * 0.5;
          size = p.size * boost * (1 + flare * 1.2 + pulse * 0.5 + swept * 1.4);
          if (lit > 0.35) { tone = 3; }
          if (!gl && formed && !swept) { p.px = x; p.py = y; continue; }     // 2D: already in the city image
        }
        vx = blur ? (x - p.px) / dt : 0; vy = blur ? (y - p.py) / dt : 0;
        p.px = x; p.py = y;
        if (alpha <= 0.01 || x < -120 || y < -120 || x > width + 120 || y > height + 120) { continue; }
        light(x, y, vx, vy, size, alpha, tone);
      }
      if (star > 0.002) {
        // The star at the centre, and a long thin flare across it (a light swept sideways: the same streak, on purpose).
        var core = 10 + STAR_PX * star;
        if (gl) {
          gl.addSegment(cx, cy, 0, 0, core, Math.min(1, star * 1.2), 3);
          gl.addSegment(cx, cy, width * 0.42 * star, 0, 8 + 6 * star, Math.min(1, star * 1.6), 3);
        } else {
          context.globalAlpha = Math.min(1, star * 1.2);
          context.drawImage(sprites[3], cx - core / 2, cy - core / 2, core, core);
          var flareW = width * 0.84 * star, flareH = 8 + 6 * star;
          context.globalAlpha = Math.min(1, star * 0.6);
          context.drawImage(streaks[3], cx - flareW / 2, cy - flareH / 2, flareW, flareH);
        }
      }
      if (gl) { gl.render(true, true); }
      context.globalAlpha = 1;
      context.globalCompositeOperation = "source-over";

      if (!exiting || since < EXIT_MS) { raf = frame(draw); }
    }

    function handle(message) {
      switch (message.type) {
        case "data": data = message; break;
        case "open":
          if (raf) { cancel(raf); raf = 0; }
          canvas = message.canvas; width = message.width; height = message.height; baseScale = message.scale; lite = message.lite;
          governor = new Light.Governor(3);
          gl = message.particles ? Light.Particles(message.particles, 1) : null;
          if (gl) { gl.setTones(TONES); }
          context = canvas.getContext("2d");
          build();
          applyScale();
          rings = []; diveAt = 0; fresh = true; exitReady = false; startedAt = prevNow = performance.now();
          raf = frame(draw);
          break;
        case "finish": if (canvas && !diveAt) { diveAt = performance.now(); if (!raf) { raf = frame(draw); } } break;
        case "close": if (raf) { cancel(raf); raf = 0; } canvas = context = points = city = gl = null; break;
        case "stats": scope.postMessage({ type: "stats", stats: governor ? governor.stats() : null }); break;
      }
    }
    scope.onmessage = function (event) { handle(event.data); };
  }

  /* The renderer's host: one worker for every report, or this page where a worker cannot draw. */
  var send = null, thread = null, broken = false, sentData = false;
  function canUseWorker() {
    return !broken && !!(window.HTMLCanvasElement && HTMLCanvasElement.prototype.transferControlToOffscreen && window.Worker && window.Blob && window.URL && NYC.lightKit);
  }
  function heard(event) { if (event.data && event.data.type === "stats" && NYC.reportStats) { NYC.reportStats("report", event.data.stats); } }
  function onPage() {
    var local = { postMessage: function (message) { heard({ data: message }); } };
    NYC.lightKit(local);
    reportRenderer(local);
    thread = null;
    send = function (message) { local.onmessage({ data: message }); };
  }
  function connect() {
    if (send) { return; }
    if (!canUseWorker()) { onPage(); return; }
    try {
      var worker = new Worker(URL.createObjectURL(new Blob(["(" + NYC.lightKit + ")(self);(" + reportRenderer + ")(self);"], { type: "text/javascript" })));
      thread = worker;
      worker.onmessage = heard;
      send = function (message, transfer) { worker.postMessage(message, transfer || []); };
      // If the worker fails, later reports draw on the page; this one finishes on the overlay's own ground.
      worker.addEventListener("error", function () {
        worker.terminate(); broken = true; send = null; thread = null; sentData = false;
        if (overlay) { overlay.classList.remove("is-canvas"); }
      });
    } catch (error) { broken = true; onPage(); }
  }
  if (NYC.lightReporter) { NYC.lightReporter(function () { if (send) { send({ type: "stats" }); } }); }

  /* The buildings, once, as the renderer wants them: places from 0 to 1, colour, size and borough order. */
  function sendData() {
    var source = NYC.Stage && NYC.Stage.data;
    if (sentData || !source) { return; }
    var n = source.n, x = new Float32Array(n), y = new Float32Array(n), tone = new Uint8Array(n), size = new Float32Array(n), rank = new Uint8Array(n);
    var lonMax = 1, latMax = 1, i, names = source.boroughs || [];
    for (i = 0; i < n; i++) { lonMax = Math.max(lonMax, source.lon[i]); latMax = Math.max(latMax, source.lat[i]); }
    var midLat = (source.origin[1] + latMax / 2) / source.scale;
    for (i = 0; i < n; i++) {
      x[i] = source.lon[i] / lonMax; y[i] = source.lat[i] / latMax; tone[i] = source.new[i];
      size[i] = Math.min(8, 3.6 + Math.log10(1 + source.units[i]) * 1.4);
      var at = BOROUGH_ORDER.indexOf(String(names[source.borough ? source.borough[i] : -1] || "").toLowerCase().replace(/^the /, ""));
      rank[i] = at < 0 ? BOROUGH_ORDER.length - 1 : at;
    }
    var message = { type: "data", n: n, x: x, y: y, tone: tone, size: size, rank: rank,
                    aspect: Math.cos(midLat * Math.PI / 180) * lonMax / latMax };
    send(message, thread ? [x.buffer, y.buffer, tone.buffer, size.buffer, rank.buffer] : []);
    sentData = true;
  }

  var armed = false, passing = false, overlay = null, startedAt = 0, finishing = false, done = false, skip = false;
  var fallback = 0, poll = 0, drawing = false;

  function steps() {
    var facts = document.getElementById("facts"), d = facts ? facts.dataset : {};
    return ["Reading " + (d.crashes || "") + " crash reports",
            "Placing " + (d.sites || "") + " buildings on the map",
            "Measuring the streets within 250 m of each one",
            "Comparing before and after",
            "Drawing your charts"];
  }

  function open() {
    if (overlay) { return; }
    done = finishing = skip = false;
    startedAt = performance.now();
    overlay = document.createElement("div");
    overlay.className = "gen";
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");
    var canvas = document.createElement("canvas"), lights = document.createElement("canvas");
    canvas.className = lights.className = "gen-canvas"; canvas.setAttribute("aria-hidden", "true"); lights.setAttribute("aria-hidden", "true");
    var panel = document.createElement("div");
    panel.className = "gen-panel";
    var kicker = document.createElement("p"), title = document.createElement("p"), line = document.createElement("p"), bar = document.createElement("div"), hint = document.createElement("p");
    kicker.className = "gen-kicker"; kicker.textContent = "Generate report";
    title.className = "gen-title"; title.textContent = "Building your report";
    line.className = "gen-line"; line.textContent = steps()[0];
    bar.className = "gen-bar"; bar.appendChild(document.createElement("i"));
    hint.className = "gen-hint"; hint.textContent = "Ready. Press Esc to skip";
    panel.appendChild(kicker); panel.appendChild(title); panel.appendChild(line); panel.appendChild(bar); panel.appendChild(hint);
    overlay.appendChild(canvas); overlay.appendChild(lights); overlay.appendChild(panel);
    document.body.appendChild(overlay);
    document.documentElement.style.overflow = "hidden";
    overlay.addEventListener("pointerdown", function () { if (done) { skip = true; maybeFinish(); } });

    var texts = steps(), stepShown = 0;
    drawing = !NYC.reducedMotion();
    if (drawing) {
      connect();
      var lite = !!(NYC.lite && NYC.lite());
      var scale = lite ? 1 : Math.min(window.devicePixelRatio || 1, MAX_SCALE), target = canvas, lightsTarget = lights;
      try { sendData(); if (thread) { target = canvas.transferControlToOffscreen(); lightsTarget = lights.transferControlToOffscreen(); } }
      catch (error) { drawing = false; }
      if (drawing) {
        send({ type: "open", canvas: target, particles: lightsTarget, width: window.innerWidth, height: window.innerHeight, scale: scale, lite: lite },
             thread ? [target, lightsTarget] : []);
        overlay.classList.add("is-canvas");
      }
    }

    // A timer, not a drawing loop, names the steps, fills the bar and ends the sequence: it runs whatever the canvas does.
    poll = window.setInterval(function () {
      var elapsed = performance.now() - startedAt, step = 0;
      while (step + 1 < STEP_AT.length && elapsed >= STEP_AT[step + 1]) { step++; }
      if (step !== stepShown) {
        stepShown = step;
        line.textContent = texts[step];
        line.classList.remove("is-new"); void line.offsetWidth; line.classList.add("is-new");
      }
      bar.firstChild.style.setProperty("--p", Math.min(done ? 1 : 0.94, elapsed / (drawing ? MIN_MS : PLAIN_MIN_MS)).toFixed(3));
      if (done) { overlay && overlay.classList.add("is-ready"); }
      maybeFinish();
    }, POLL_MS);
    fallback = window.setTimeout(function () { done = true; }, MAX_WAIT_MS);   // the page never stays covered
  }

  function maybeFinish() {
    if (!overlay || !done || finishing || (!skip && performance.now() - startedAt < (drawing ? MIN_MS : PLAIN_MIN_MS))) { return; }
    finishing = true;
    window.clearInterval(poll);
    var leaving = overlay, reducedNow = NYC.reducedMotion() || !drawing;
    // 1. While the screen is still covered: move to the report and let the browser lay it out.
    var target = document.getElementById("report");
    document.documentElement.style.overflow = "";
    if (target) { target.scrollIntoView({ block: "start", behavior: "instant" }); }
    // Only the few figures settle one by one; the charts come in with the report as a whole (one layer, see 35-generate.css).
    document.querySelectorAll("#report-tiles .tile, #report-tiles .metric").forEach(function (element, index) { element.style.setProperty("--i", index % 8); });
    // The report gets its own layer now, under cover, so the hand-off below starts on a layer already built.
    document.body.classList.add("gen-ready-layer");
    // 2. Two frames later the city collapses and bursts, and the report zooms out into place behind the shockwave.
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        if (send && drawing) { send({ type: "finish" }); }
        leaving.classList.add("is-out");
        document.body.setAttribute("data-report", "fresh");
        window.setTimeout(function () { document.body.removeAttribute("data-report"); document.body.classList.remove("gen-ready-layer"); }, 4300);
        window.setTimeout(function () {
          if (send && drawing) { send({ type: "close" }); }
          leaving.remove();
          if (overlay === leaving) { overlay = null; }
        }, reducedNow ? 0 : OUT_MS + 40);
      });
    });
  }

  /* The reader asked: from the button, or Enter in the search box. */
  // Capture on the window runs before React's own listener, so the click can be held and passed on later.
  window.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("#generate");
    if (!button || passing) { return; }
    armed = true;
    if (button.disabled || overlay) { open(); return; }
    // The charts are built when the reader first comes near (app/ui/lazy.py). If they are not on the page yet, the
    // click is not passed on: Dash's generate callback would write to charts that do not exist. Building them sets
    // lazy-report-ready, which runs the same callback with the filters as they stand, so the report still comes.
    var frame = document.getElementById("lazy-report");
    if (frame && frame.querySelector(".lazy-frame")) {
      event.stopImmediatePropagation(); event.preventDefault();
      open();
      if (NYC.buildLazy) { NYC.buildLazy("lazy-report"); }
      return;
    }
    if (NYC.reducedMotion()) { open(); return; }
    event.stopImmediatePropagation(); event.preventDefault();
    open();
    window.setTimeout(function () { passing = true; button.click(); passing = false; }, thread ? RELEASE_WORKER_MS : RELEASE_PAGE_MS);
  }, true);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && event.target.id === "search") { armed = true; open(); }
    if (event.key === "Escape" && overlay && done) { skip = true; maybeFinish(); }
  });

  NYC.onMount("#report", function (report) {
    var wasLoading = report.classList.contains("is-loading");
    new MutationObserver(function () {
      var loading = report.classList.contains("is-loading");
      if (wasLoading && !loading && armed) {
        armed = false;
        window.clearTimeout(fallback);
        done = true;
      }
      wasLoading = loading;
    }).observe(report, { attributes: true, attributeFilter: ["class"] });
  });
})();
