/* The Generate report sequence. When the reader asks for a report, the screen goes dark and the city is rebuilt
   from its own buildings, the same points of light as the opening:

     scatter   every building is a spark drifting somewhere on the screen
     gather    the sparks swirl into the shape of New York, each on its own path
     measure   a line of light sweeps the city; the buildings it passes flare, and 250 m rings pulse at real sites
     open      when the report is ready, the city rushes outward and a circle opens onto the finished report

   Real steps of the work are named as it runs. Dash's own `running` state on #report (class is-loading) says
   when the work starts and ends; a short minimum keeps the sequence readable even when the answer is instant.
   Not shown for the report drawn on page load. Under reduced motion it is a plain notice with a bar.

   Smoothness: the canvas paints its own dark ground and opens the closing circle itself (a destination-out fill),
   so the browser never animates a full-screen CSS mask beside it; the canvas is held to 1.5 device pixels; the
   page moves to the report while it is still fully covered, and the circle starts opening two frames later, once
   that layout has been paid for. And the work itself waits for the calm: a click on Generate is held back until
   the city has formed (RELEASE_MS), then passed on to Dash, so the few hundred milliseconds in which the new
   charts are built fall in the steady sweep, not in the middle of the swirl. */
(function () {
  "use strict";

  var NYC = window.NYC;
  var RELEASE_MS = 1750, passing = false;
  var MIN_MS = 3200, STEP_MS = 720, MAX_WAIT_MS = 15000, OUT_MS = 950, POLL_MS = 80, SPARK = 12, RINGS = 7, MAX_POINTS = 5200, LITE_POINTS = 2200, MAX_SCALE = 1.5;
  var TONES = [[95, 212, 196], [232, 192, 116], [255, 143, 120], [255, 240, 205]];
  var armed = false, overlay = null, raf = 0, startedAt = 0, finishing = false, done = false, fallback = 0, poll = 0, leftAt = 0, opening = 0;

  function steps() {
    var facts = document.getElementById("facts"), d = facts ? facts.dataset : {};
    return ["Reading " + (d.crashes || "") + " crash reports",
            "Placing " + (d.sites || "") + " buildings on the map",
            "Measuring the streets within 250 m of each one",
            "Comparing before and after",
            "Drawing your charts"];
  }

  /* A spark drawn at the canvas's own resolution, so its bright core stays sharp on a high-density screen. */
  function sprite(rgb, scale) {
    var r = SPARK * scale, size = Math.ceil(r * 2), canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    var context = canvas.getContext("2d"), glow = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, r), color = rgb.join(",");
    glow.addColorStop(0, "rgba(" + color + ",1)"); glow.addColorStop(0.16, "rgba(" + color + ",0.6)");
    glow.addColorStop(0.45, "rgba(" + color + ",0.05)"); glow.addColorStop(1, "rgba(" + color + ",0)");
    context.fillStyle = glow; context.fillRect(0, 0, size, size);
    return canvas;
  }

  /* One record per building: where it starts, where it lands in the city, and its own timing. */
  function cloud(width, height) {
    var data = NYC.Stage && NYC.Stage.data, out = [], i;
    var n = data ? data.n : 2400, lonMax = 1, latMax = 1, aspect = 0.82;
    var stride = Math.max(1, n / (NYC.lite && NYC.lite() ? LITE_POINTS : MAX_POINTS));   // fewer points on a phone
    if (data) {
      for (i = 0; i < n; i++) { lonMax = Math.max(lonMax, data.lon[i]); latMax = Math.max(latMax, data.lat[i]); }
      var midLat = (data.origin[1] + latMax / 2) / data.scale;
      aspect = Math.cos(midLat * Math.PI / 180) * lonMax / latMax;
    }
    var drawH = Math.min(height * 0.72, width * 0.9 / aspect), drawW = drawH * aspect;
    var left = (width - drawW) / 2, top = height * 0.42 - drawH / 2;
    for (var k = 0; k < n; k += stride) {
      i = Math.floor(k);
      var angle = Math.random() * 6.283, spread = Math.random();
      out.push({
        sx: width * Math.random(), sy: height * Math.random(),
        vx: Math.cos(angle) * (8 + spread * 22), vy: Math.sin(angle) * (8 + spread * 22),
        tx: data ? left + data.lon[i] / lonMax * drawW : width / 2 + Math.cos(angle) * drawH * 0.3 * Math.sqrt(spread),
        ty: data ? top + (1 - data.lat[i] / latMax) * drawH : height * 0.42 + Math.sin(angle) * drawH * 0.3 * Math.sqrt(spread),
        tone: data ? data.new[i] : (i % 2), size: data ? Math.min(8, 3.6 + Math.log10(1 + data.units[i]) * 1.4) : 4,
        delay: Math.random() * 0.5, spin: (Math.random() < 0.5 ? -1 : 1) * (0.6 + Math.random() * 1.1),
        phase: Math.random() * 6.283, out: 0.8 + Math.random() * 0.8
      });
    }
    return { points: out, top: top, bottom: top + drawH, left: left, right: left + drawW };
  }

  /* The overlay's ground, painted once per opening: the page colour with a faint glow behind the city, and a
     dither of single steps of light and shade, so the dark gradient shows no bands on an 8-bit screen. */
  function groundLayer(width, height, scale) {
    var layer = document.createElement("canvas");
    layer.width = Math.round(width * scale); layer.height = Math.round(height * scale);
    var g = layer.getContext("2d");
    g.setTransform(scale, 0, 0, scale, 0, 0);
    var glow = g.createRadialGradient(width / 2, height * 0.42, 0, width / 2, height * 0.42, Math.max(width, height) * 0.7);
    glow.addColorStop(0, "#10162b"); glow.addColorStop(1, "#0a0d1a");
    g.fillStyle = glow; g.fillRect(0, 0, width, height);
    var TILE = 64, tile = document.createElement("canvas"), t = tile.getContext("2d"), noise = t.createImageData(TILE, TILE);
    tile.width = tile.height = TILE;
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

  function open() {
    if (overlay) { return; }
    done = finishing = false; leftAt = 0; opening = 0;
    startedAt = performance.now();
    overlay = document.createElement("div");
    overlay.className = "gen";
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");
    var canvas = document.createElement("canvas");
    canvas.className = "gen-canvas"; canvas.setAttribute("aria-hidden", "true");
    var panel = document.createElement("div");
    panel.className = "gen-panel";
    var kicker = document.createElement("p"), title = document.createElement("p"), line = document.createElement("p"), bar = document.createElement("div");
    kicker.className = "gen-kicker"; kicker.textContent = "Generate report";
    title.className = "gen-title"; title.textContent = "Building your report";
    line.className = "gen-line"; line.textContent = steps()[0];
    bar.className = "gen-bar"; bar.appendChild(document.createElement("i"));
    panel.appendChild(kicker); panel.appendChild(title); panel.appendChild(line); panel.appendChild(bar);
    overlay.appendChild(canvas); overlay.appendChild(panel);
    document.body.appendChild(overlay);
    document.documentElement.style.overflow = "hidden";

    var reduced = NYC.reducedMotion(), texts = steps(), stepShown = 0;
    var context = canvas.getContext("2d"), width = window.innerWidth, height = window.innerHeight, scale = NYC.lite && NYC.lite() ? 1 : Math.min(window.devicePixelRatio || 1, MAX_SCALE);
    canvas.width = width * scale; canvas.height = height * scale;
    context.scale(scale, scale);
    var sprites = TONES.map(function (rgb) { return sprite(rgb, scale); }), city = reduced ? null : cloud(width, height), rings = [];
    // The ground is drawn from its layer on every frame; the sweep's band is built once and moved into place.
    var ground = city ? groundLayer(width, height, scale) : null;
    var band = context.createLinearGradient(0, -40, 0, 40);
    band.addColorStop(0, "rgba(232,192,116,0)"); band.addColorStop(0.5, "rgba(232,192,116,0.10)"); band.addColorStop(1, "rgba(232,192,116,0)");
    if (city) { overlay.classList.add("is-canvas"); }
    var GATHER_FROM = 450, GATHER_MS = 1500, SCAN_FROM = 1700, SCAN_MS = 1500;

    function frame(now) {
      var elapsed = Math.max(0, now - startedAt);
      var step = Math.min(texts.length - 1, Math.floor(elapsed / STEP_MS));
      if (step !== stepShown) {
        stepShown = step;
        line.textContent = texts[step];
        line.classList.remove("is-new"); void line.offsetWidth; line.classList.add("is-new");
      }
      bar.firstChild.style.setProperty("--p", Math.min(done ? 1 : 0.94, elapsed / MIN_MS).toFixed(3));
      if (city) {
        context.globalCompositeOperation = "source-over";
        context.drawImage(ground, 0, 0, width, height);
        context.globalCompositeOperation = "lighter";
        var gather = (elapsed - GATHER_FROM) / GATHER_MS, scan = ((elapsed - SCAN_FROM) % SCAN_MS) / SCAN_MS;
        var scanning = elapsed > SCAN_FROM, scanY = city.top - 30 + scan * (city.bottom - city.top + 60);
        var burst = leftAt ? NYC.easeInOut(Math.min(1, (now - leftAt) / OUT_MS)) : 0;
        var cx = width / 2, cy = height * 0.42;
        for (var i = 0; i < city.points.length; i++) {
          var p = city.points[i], t = NYC.easeInOut(Math.max(0, Math.min(1, (gather - p.delay) / (1 - p.delay * 0.6))));
          var driftX = p.sx + p.vx * elapsed / 1000, driftY = p.sy + p.vy * elapsed / 1000;
          // Swirl: the remaining distance turns around the landing point as it shrinks.
          var swirl = (1 - t) * p.spin * 1.8, dx = driftX - p.tx, dy = driftY - p.ty, cos = Math.cos(swirl), sin = Math.sin(swirl);
          var x = p.tx + (dx * cos - dy * sin) * (1 - t), y = p.ty + (dx * sin + dy * cos) * (1 - t);
          if (burst) { x = cx + (x - cx) * (1 + burst * 2.4 * p.out); y = cy + (y - cy) * (1 + burst * 2.4 * p.out); }
          var lit = scanning && t >= 1 ? Math.max(0, 1 - Math.abs(y - scanY) / 26) : 0;
          var alpha = (0.25 + 0.65 * t + 0.1 * Math.sin(now * 0.002 + p.phase)) * (1 - burst);
          var size = p.size * (1 + lit * 1.4) * (1 - burst * 0.4);
          context.globalAlpha = Math.max(0, Math.min(1, alpha + lit * 0.5));
          context.drawImage(sprites[lit > 0.35 ? 3 : p.tone], x - size / 2, y - size / 2, size, size);
        }
        context.globalAlpha = 1;
        if (scanning && !burst) {
          // The sweep: a soft band of light with a bright core.
          context.translate(0, scanY);
          context.fillStyle = band; context.fillRect(city.left - 40, -40, city.right - city.left + 80, 80);
          context.translate(0, -scanY);
          context.fillStyle = "rgba(255,240,205,0.5)"; context.fillRect(city.left - 40, scanY - 0.5, city.right - city.left + 80, 1);
          // 250 m rings at real sites the sweep has just passed.
          if (rings.length < RINGS && Math.random() < 0.06) {
            var pick = city.points[Math.floor(Math.random() * city.points.length)];
            if (Math.abs(pick.ty - scanY) < 40) { rings.push({ x: pick.tx, y: pick.ty, born: now }); }
          }
        }
        context.globalCompositeOperation = "source-over";
        rings = rings.filter(function (ring) {
          var age = (now - ring.born) / 1400;
          if (age >= 1 || burst) { return false; }
          context.strokeStyle = "rgba(255,143,120," + (0.7 * (1 - age)).toFixed(3) + ")";
          context.lineWidth = 1.2;
          context.beginPath(); context.arc(ring.x, ring.y, 4 + age * 26, 0, 6.283); context.stroke();
          return true;
        });
        if (opening) {
          // The circle that opens onto the report, cut out of the canvas itself.
          var hole = NYC.easeInOut(Math.min(1, (now - opening) / OUT_MS)) * Math.hypot(width, height) * 0.62;
          context.globalCompositeOperation = "destination-out";
          var edge = context.createRadialGradient(width / 2, height * 0.42, Math.max(0, hole - 40), width / 2, height * 0.42, hole + 1);
          edge.addColorStop(0, "rgba(0,0,0,1)"); edge.addColorStop(1, "rgba(0,0,0,0)");
          context.fillStyle = edge;
          context.beginPath(); context.arc(width / 2, height * 0.42, hole + 1, 0, 6.283); context.fill();
          context.globalCompositeOperation = "source-over";
        }
      }
      if (overlay) { raf = window.requestAnimationFrame(frame); }
    }
    raf = window.requestAnimationFrame(frame);
    fallback = window.setTimeout(function () { done = true; }, MAX_WAIT_MS);   // the page never stays covered
    // A timer, not the drawing loop, ends the sequence: it still runs in a hidden tab or if a frame fails.
    poll = window.setInterval(maybeFinish, POLL_MS);
  }

  function maybeFinish() {
    if (!done || finishing || performance.now() - startedAt < MIN_MS) { return; }
    finishing = true;
    window.clearInterval(poll);
    var leaving = overlay, reducedNow = NYC.reducedMotion();
    // 1. While the screen is still covered: move to the report and let the browser lay it out.
    var target = document.getElementById("report");
    document.documentElement.style.overflow = "";
    if (target) { target.scrollIntoView({ block: "start", behavior: "instant" }); }
    document.querySelectorAll(".tile, .figures .metric, .card").forEach(function (element, index) { element.style.setProperty("--i", index % 8); });
    // 2. Two frames later, the city rushes outward and the circle opens.
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        leftAt = opening = performance.now();
        leaving.classList.add("is-out");
        document.body.setAttribute("data-report", "fresh");
        window.setTimeout(function () { document.body.removeAttribute("data-report"); }, 2400);
        window.setTimeout(function () {
          window.cancelAnimationFrame(raf);
          leaving.remove();
          overlay = null;
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
    if (NYC.reducedMotion() || button.disabled || overlay) { open(); return; }
    event.stopImmediatePropagation(); event.preventDefault();
    open();
    window.setTimeout(function () { passing = true; button.click(); passing = false; }, RELEASE_MS);
  }, true);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && event.target.id === "search") { armed = true; open(); }
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
