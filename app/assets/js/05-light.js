/* The light kit: what every canvas of points on the page shares. The stage (20-stage.js) and the Generate report
   sequence (40-generate.js) both draw with it.

   lightKit(scope) is self-contained (it reads nothing from the page around it), because it is also sent, as text,
   to a worker in front of the renderer that uses it: "(" + lightKit + ")(self);(" + renderer + ")(self);".
   It installs scope.Light:

     sprite(rgb, scale, peak?, radius?)   a point of light drawn at the canvas's own resolution
     capsule(rgb, scale, peak?, radius?)  the same light smeared along a line: the true motion blur of a round glow
     drawLight(ctx, sprite, capsule, x, y, vx, vy, size, alpha, scale)
                                          one point, streaked along its velocity (CSS px per ms) when it moves
     Particles(canvas, peak)              every light at once on the graphics processor (WebGL2), each moving one
                                          blurred per pixel along its path; null where WebGL2 is not offered, and the
                                          2D functions above draw instead
     Governor(levels)                     adaptive quality: steps down when frames run late, back up when calm
     flow(x, y, t, out)                   a smooth swirling field, so drifting light curls instead of sliding
     cadence(now, last, target)           frame-aligned throttling for resting frames
     easeInOutCubic, easeOutCubic         the calm curves used for travel

   Motion blur. A camera's shutter stays open for part of each frame, so a moving light is recorded as a streak as
   long as the distance it covered while the shutter was open. Here that time is fixed (SHUTTER_MS), not one frame,
   so the blur looks the same at 60 Hz and at 120 Hz. A streak spreads the same light over a longer shape, so it is
   drawn dimmer in proportion (with a floor, so a fast spark never vanishes). */
(function () {
  "use strict";

  function lightKit(scope) {
    "use strict";
    var SHUTTER_MS = 16, MIN_STREAK_PX = 0.5, MAX_STREAK_PX = 48, CAPSULE_RATIO = 6, BLEND_FROM = 3, SPARK_PX = 14, MIN_ALPHA_SHARE = 0.35;

    function surface(width, height) {
      if (typeof OffscreenCanvas !== "undefined") { return new OffscreenCanvas(width, height); }
      var element = document.createElement("canvas");
      element.width = width; element.height = height;
      return element;
    }

    function sprite(rgb, scale, peak, radius) {
      var r = (radius || SPARK_PX) * scale, size = Math.ceil(r * 2), layer = surface(size, size), g = layer.getContext("2d");
      var glow = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, r), color = rgb.join(",");
      glow.addColorStop(0, "rgba(" + color + "," + (peak == null ? 0.95 : peak) + ")");
      glow.addColorStop(0.15, "rgba(" + color + ",0.6)");
      glow.addColorStop(0.42, "rgba(" + color + ",0.05)");
      glow.addColorStop(1, "rgba(" + color + ",0)");
      g.fillStyle = glow;
      g.fillRect(0, 0, size, size);
      return layer;
    }

    /* The left half of the glow, its middle column stretched, then the right half: a round light swept along a line. */
    function capsule(rgb, scale, peak, radius) {
      var dot = sprite(rgb, scale, peak, radius), d = dot.width, half = Math.floor(d / 2), w = d * CAPSULE_RATIO;
      var layer = surface(w, d), g = layer.getContext("2d");
      g.drawImage(dot, 0, 0, half, d, 0, 0, half, d);
      g.drawImage(dot, half, 0, 1, d, half, 0, w - 2 * half, d);
      g.drawImage(dot, d - half, 0, half, d, w - half, 0, half, d);
      return layer;
    }

    /* Draws with the context's transform set to (scale, 0, 0, scale, 0, 0) and leaves it so. Returns true when the
       point was streaked. */
    function drawLight(ctx, dot, streak, x, y, vx, vy, size, alpha, scale) {
      var speed = Math.sqrt(vx * vx + vy * vy), length = streak ? Math.min(MAX_STREAK_PX, speed * SHUTTER_MS) : 0;
      // Everything below changes continuously with the length, so a light that speeds up or slows down never jumps in
      // shape or brightness: at no length it is exactly the round light.
      var total = size + length, share = size / total, a = alpha * (share > MIN_ALPHA_SHARE ? share : MIN_ALPHA_SHARE);
      if (a > 1) { a = 1; }
      if (length < MIN_STREAK_PX) {
        ctx.globalAlpha = a;
        ctx.drawImage(dot, x - size / 2, y - size / 2, size, size);
        return false;
      }
      var cos = vx / speed, sin = vy / speed, ratio = total / size;
      // A short smear is the round light stretched along its path; a long one is the capsule, the true smear of a
      // round light. Between BLEND_FROM and CAPSULE_RATIO times its size the two are crossfaded. (Squeezing the
      // capsule into a short box, as before, turned a slow large light into a thin sliver and back, frame to frame.)
      var k = ratio <= BLEND_FROM ? 0 : ratio >= CAPSULE_RATIO ? 1 : (ratio - BLEND_FROM) / (CAPSULE_RATIO - BLEND_FROM);
      ctx.setTransform(scale * cos, scale * sin, -scale * sin, scale * cos, x * scale, y * scale);
      if (k < 1) { ctx.globalAlpha = a * (1 - k); ctx.drawImage(dot, -total / 2, -size / 2, total, size); }
      if (k > 0) { ctx.globalAlpha = a * k; ctx.drawImage(streak, -total / 2, -size / 2, total, size); }
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      return true;
    }

    /* Adaptive quality. tick(now) on every frame that is meant to run at the display's full rate (pause() when the
       renderer throttles itself on purpose). The refresh interval is learned from the fast end of recent frames (the
       10th percentile, so one stray short interval cannot fool it); when the smoothed interval stays well above it,
       and below about 55 frames a second, one level is given up. Returns true when the level changed. */
    var SAMPLES = 120, WARMUP_MS = 400, LATE = 1.3, LATE_FLOOR_MS = 18, LATE_FRAMES = 30, CALM_MS = 3000, GAP_MS = 250;
    function Governor(levels) {
      this.levels = levels; this.level = 0; this.ema = 0; this.best = Infinity; this.last = 0; this.started = 0;
      this.late = 0; this.calm = 0; this.samples = new Float32Array(SAMPLES); this.k = 0; this.count = 0;
    }
    Governor.prototype.pause = function () { this.last = 0; };
    Governor.prototype.tick = function (now) {
      if (!this.last) { this.last = now; if (!this.started) { this.started = now; } return false; }
      var dt = now - this.last;
      this.last = now;
      if (dt > GAP_MS || dt <= 0) { return false; }        // a hidden tab or a paused loop, not a slow frame
      this.samples[this.k] = dt; this.k = (this.k + 1) % SAMPLES; this.count = Math.min(this.count + 1, SAMPLES);
      if (this.count >= 20 && this.k % 10 === 0) {
        var list = Array.prototype.slice.call(this.samples, 0, this.count).sort(function (a, b) { return a - b; });
        this.best = Math.max(6, list[Math.floor(list.length * 0.1)]);
      } else if (this.best === Infinity) { this.best = 16.7; }
      this.ema = this.ema ? this.ema * 0.9 + dt * 0.1 : dt;
      if (now - this.started < WARMUP_MS) { return false; }
      if (this.ema > Math.max(this.best * LATE, LATE_FLOOR_MS)) { this.late++; this.calm = 0; } else { this.calm += dt; if (this.late > 0) { this.late--; } }
      if (this.late > LATE_FRAMES && this.level < this.levels) { this.level++; this.late = 0; this.ema = this.best; return true; }
      if (this.calm > CALM_MS && this.level > 0) { this.level--; this.calm = 0; return true; }
      return false;
    };
    Governor.prototype.stats = function () {
      var list = Array.prototype.slice.call(this.samples, 0, this.count).sort(function (a, b) { return a - b; });
      var sum = 0;
      list.forEach(function (v) { sum += v; });
      return { level: this.level, refreshMs: +(this.best === Infinity ? 0 : this.best).toFixed(2),
               averageMs: +(list.length ? sum / list.length : 0).toFixed(2),
               p95Ms: +(list.length ? list[Math.min(list.length - 1, Math.floor(list.length * 0.95))] : 0).toFixed(2),
               frames: list.length };
    };

    /* Two crossed waves in each direction: nearly free of sources and sinks, so light circulates. Unit-sized. */
    function flow(x, y, t, out) {
      out[0] = Math.sin(y * 0.0062 + t * 0.00042) + 0.6 * Math.sin((x + y) * 0.0031 - t * 0.00031);
      out[1] = Math.cos(x * 0.0058 - t * 0.00037) + 0.6 * Math.cos((x - y) * 0.0029 + t * 0.00027);
      return out;
    }

    /* A 4 ms allowance, so "every 33 ms" lands on every second vsync at 60 Hz instead of wavering between two and three. */
    function cadence(now, last, target) { return now - last >= target - 4; }

    /* Particles on the graphics processor (WebGL2). Every light is one instance of a small quad and all of them are
       drawn in a single call, so seven thousand lights cost about what one did on the 2D canvas, where each was its
       own drawImage (and its own transform when streaked).

       The motion blur is computed per pixel. A light that moved is drawn as its glow swept along the segment it
       covered while the shutter was open: the brightness at a pixel follows its distance to that segment, not to a
       point. At no motion that is exactly the round light, and it lengthens continuously with speed, so there is no
       shape to switch and nothing to pop. The glow's profile is the sprite's (the same stops), and a streak keeps the
       light's total brightness (share), as drawLight does on the 2D canvas.

       Particles(canvas, peak) returns null where WebGL2 is not offered (the renderers then draw on the 2D canvas as
       before). Then: resize(width, height, scale); add(x, y, vx, vy, size, alpha, tone) for a light moving at (vx, vy)
       CSS px per ms; addSegment(x, y, hx, hy, ...) for a light swept from (x - hx, y - hy) to (x + hx, y + hy);
       render(clear, additive) draws everything added since the last render. maxStreak caps a streak's length. */
    var VERTEX = [
      "#version 300 es",
      "precision highp float;",
      "layout(location = 0) in vec2 corner;",
      "layout(location = 1) in vec4 placeAndStreak;",   // x, y, half streak x, half streak y (CSS px)
      "layout(location = 2) in vec4 sizeAlphaTone;",    // size, alpha, tone, unused
      "uniform vec2 view;",
      "uniform vec4 tones[4];",
      "out vec2 local;",
      "out float halfLength;",
      "out float radius;",
      "out vec3 color;",
      "out float strength;",
      "void main() {",
      "  float r = max(0.5, sizeAlphaTone.x * 0.5);",
      "  vec2 streak = placeAndStreak.zw;",
      "  float L = length(streak);",
      "  vec2 axis = L > 0.0001 ? streak / L : vec2(1.0, 0.0);",
      "  vec2 across = vec2(-axis.y, axis.x);",
      "  local = corner * vec2(L + r, r);",
      "  vec2 position = placeAndStreak.xy + axis * local.x + across * local.y;",
      "  gl_Position = vec4(position.x / view.x * 2.0 - 1.0, 1.0 - position.y / view.y * 2.0, 0.0, 1.0);",
      "  halfLength = L;",
      "  radius = r;",
      "  strength = min(1.0, sizeAlphaTone.y * max(" + MIN_ALPHA_SHARE.toFixed(2) + ", r / (r + L)));",
      "  color = tones[int(sizeAlphaTone.z + 0.5)].rgb;",
      "}"
    ].join("\n");
    var FRAGMENT = [
      "#version 300 es",
      "precision highp float;",
      "in vec2 local;",
      "in float halfLength;",
      "in float radius;",
      "in vec3 color;",
      "in float strength;",
      "uniform float peak;",
      "out vec4 fragColor;",
      "void main() {",
      "  vec2 q = vec2(max(abs(local.x) - halfLength, 0.0), local.y);",   // to the nearest point of the swept segment
      "  float d = length(q) / radius;",
      "  if (d >= 1.0) { discard; }",
      "  float a = d < 0.15 ? mix(peak, 0.6, d / 0.15) : (d < 0.42 ? mix(0.6, 0.05, (d - 0.15) / 0.27) : mix(0.05, 0.0, (d - 0.42) / 0.58));",
      "  a *= strength;",
      "  fragColor = vec4(color * a, a);",                                 // premultiplied, as the canvas expects
      "}"
    ].join("\n");
    var FLOATS = 8;

    function Particles(canvas, peak) {
      var gl = null;
      try {
        gl = canvas.getContext("webgl2", { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false,
                                           preserveDrawingBuffer: false, powerPreference: "high-performance" });
      } catch (error) { gl = null; }
      if (!gl) { return null; }
      var self = { count: 0, maxStreak: MAX_STREAK_PX, width: 1, height: 1, lost: false };
      var program = null, uView = null, uTones = null, uPeak = null, vao = null, instances = null, uploaded = 0;
      var data = new Float32Array(4096 * FLOATS), capacity = 4096, tones = new Float32Array(16), peakValue = peak == null ? 0.95 : peak;

      function compile(type, source) {
        var shader = gl.createShader(type);
        gl.shaderSource(shader, source); gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) { throw new Error(gl.getShaderInfoLog(shader) || "shader"); }
        return shader;
      }
      function setup() {
        program = gl.createProgram();
        gl.attachShader(program, compile(gl.VERTEX_SHADER, VERTEX));
        gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAGMENT));
        gl.linkProgram(program);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) { throw new Error(gl.getProgramInfoLog(program) || "program"); }
        uView = gl.getUniformLocation(program, "view"); uTones = gl.getUniformLocation(program, "tones"); uPeak = gl.getUniformLocation(program, "peak");
        vao = gl.createVertexArray();
        gl.bindVertexArray(vao);
        gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
        gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
        instances = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, instances);
        gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, FLOATS * 4, 0); gl.vertexAttribDivisor(1, 1);
        gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 4, gl.FLOAT, false, FLOATS * 4, 16); gl.vertexAttribDivisor(2, 1);
        gl.bindVertexArray(null);
        gl.disable(gl.DEPTH_TEST); gl.enable(gl.BLEND);
        uploaded = 0;
      }
      try { setup(); } catch (error) { return null; }
      // A lost context (the graphics driver reset) draws nothing until it is restored, then is built again.
      if (canvas.addEventListener) {
        canvas.addEventListener("webglcontextlost", function (event) { event.preventDefault(); self.lost = true; });
        canvas.addEventListener("webglcontextrestored", function () { try { setup(); self.lost = false; } catch (error) { /* stays lost */ } });
      }

      self.setTones = function (list) {
        list.forEach(function (rgb, k) { tones[k * 4] = rgb[0] / 255; tones[k * 4 + 1] = rgb[1] / 255; tones[k * 4 + 2] = rgb[2] / 255; tones[k * 4 + 3] = 1; });
      };
      self.resize = function (width, height, scale) {
        canvas.width = Math.max(1, Math.round(width * scale)); canvas.height = Math.max(1, Math.round(height * scale));
        self.width = width; self.height = height;
      };
      self.addSegment = function (x, y, hx, hy, size, alpha, tone) {
        if (alpha <= 0.004 || size <= 0) { return; }
        if (self.count >= capacity) {
          var bigger = new Float32Array(capacity * 2 * FLOATS);
          bigger.set(data); data = bigger; capacity *= 2;
        }
        var o = self.count * FLOATS;
        data[o] = x; data[o + 1] = y; data[o + 2] = hx; data[o + 3] = hy;
        data[o + 4] = size; data[o + 5] = alpha; data[o + 6] = tone; data[o + 7] = 0;
        self.count++;
      };
      self.add = function (x, y, vx, vy, size, alpha, tone) {
        var speed = Math.sqrt(vx * vx + vy * vy), hx = 0, hy = 0;
        if (speed > 0) {
          var length = Math.min(self.maxStreak, speed * SHUTTER_MS);
          if (length >= MIN_STREAK_PX) { hx = vx / speed * length / 2; hy = vy / speed * length / 2; }
        }
        self.addSegment(x, y, hx, hy, size, alpha, tone);
      };
      self.render = function (clear, additive) {
        var count = self.count;
        self.count = 0;
        if (self.lost) { return; }
        gl.viewport(0, 0, canvas.width, canvas.height);
        if (clear) { gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); }
        if (!count) { return; }
        gl.useProgram(program);
        gl.uniform2f(uView, self.width, self.height);
        gl.uniform4fv(uTones, tones);
        gl.uniform1f(uPeak, peakValue);
        gl.blendFunc(gl.ONE, additive ? gl.ONE : gl.ONE_MINUS_SRC_ALPHA);
        gl.bindBuffer(gl.ARRAY_BUFFER, instances);
        if (uploaded < capacity) { gl.bufferData(gl.ARRAY_BUFFER, data.byteLength, gl.DYNAMIC_DRAW); uploaded = capacity; }
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, data, 0, count * FLOATS);
        gl.bindVertexArray(vao);
        gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, count);
        gl.bindVertexArray(null);
      };
      return self;
    }

    scope.Light = {
      sprite: sprite, capsule: capsule, drawLight: drawLight, Governor: Governor, flow: flow, cadence: cadence, surface: surface,
      Particles: Particles,
      easeInOutCubic: function (t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; },
      easeOutCubic: function (t) { return 1 - Math.pow(1 - t, 3); }
    };
  }

  var NYC = window.NYC = window.NYC || {};
  NYC.lightKit = lightKit;

  /* NYC.fps() in the console: every renderer that registered reports its frame times and quality level. */
  var reporters = [];
  NYC.lightReporter = function (fn) { reporters.push(fn); };
  NYC.fps = function () {
    if (!reporters.length) { console.info("No light renderer is running yet."); return; }
    reporters.forEach(function (fn) { fn(); });
  };
  NYC.reportStats = function (name, stats) { console.info("[" + name + "] frames", stats); };
})();
