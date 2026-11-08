/* The page's motion, as window.NYC. Text stays plain and readable until this script improves it, and it does nothing
   but count-free final states under prefers-reduced-motion.

     NYC.onMount(selector, fn)  runs fn(element) once per matching element, whenever it appears (Dash mounts late)
     NYC.reducedMotion()        true when the reader asked for less motion
     NYC.easeOut(t)             the page's settle curve
     NYC.easeInOut(t)           a slow start and a slow landing, for things that travel
     NYC.countUp(element)       rolls a [data-countup] figure into place, digit by digit, ending exactly on its text

   Declared in the markup:
     data-kinetic="words"       words rise out of a mask when the element enters the window
     data-kinetic="lines"       the element lifts in
     data-scrub="words"         words light up with the scroll position
     .button                    a press sends a soft glow from the finger (the hover is pure CSS: 20-components.css)
     .nav                       a lit pill glides under the link that is pointed at, or the section in view
     .spot                      a soft light trails the pointer and lights the nearest stretch of border
     data-tint on a section     the page's ground drifts to that tint while it is in view */
(function () {
  "use strict";

  var NYC = window.NYC = window.NYC || {};
  var motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var fine = window.matchMedia("(hover: hover) and (pointer: fine)");
  var ROLL_MS = 1500, ROLL_STAGGER_MS = 70, SCRUB_LOW = 0.2, SCRUB_SOFT = 5;
  // One family of night blues, so the coral and the gold read the same on every chapter.
  var TINTS = { midnight: "#0a0d1a", harbor: "#081521", plum: "#0d0f22", ember: "#0e1220" };

  NYC.reducedMotion = function () { return motion.matches; };
  /* Hover styles apply wherever any pointer can hover (see 00-base.css): a phone has none, a touchscreen laptop with
     a mouse does. Decided again if a pointer is added or removed. */
  var anyHover = window.matchMedia("(any-hover: hover)");
  function markHover() { document.documentElement.classList.toggle("can-hover", anyHover.matches); }
  markHover();
  if (anyHover.addEventListener) { anyHover.addEventListener("change", markHover); } else if (anyHover.addListener) { anyHover.addListener(markHover); }
  /* Phones, touch screens and small processors get the light version: the same states, no blur filters, no
     scroll-lit words and a canvas that only draws while it moves. Two threads or fewer counts as a small processor;
     four is common on ordinary laptops, and some browsers report a low count on purpose, so four is not a phone. */
  var phoneLike = window.matchMedia("(max-width: 760px), (pointer: coarse)");
  function measureLite() { return phoneLike.matches || (navigator.hardwareConcurrency || 8) <= 2; }
  var lite = measureLite();
  NYC.lite = function () { return lite; };
  document.documentElement.classList.toggle("is-lite", lite);
  /* Decided again whenever the window crosses the phone width or the pointer changes, so a page that loaded in a
     narrow window gets its lights back when the window widens. Listeners hear "nyc:lite" on window. */
  function remeasureLite() {
    var next = measureLite();
    if (next === lite) { return; }
    lite = next;
    document.documentElement.classList.toggle("is-lite", lite);
    window.dispatchEvent(new CustomEvent("nyc:lite", { detail: { lite: lite } }));
  }
  if (phoneLike.addEventListener) { phoneLike.addEventListener("change", remeasureLite); }
  else if (phoneLike.addListener) { phoneLike.addListener(remeasureLite); }
  NYC.easeOut = function (t) { return 1 - Math.pow(1 - t, 4); };
  NYC.easeInOut = function (t) { return t < 0.5 ? 8 * t * t * t * t : 1 - Math.pow(-2 * t + 2, 4) / 2; };

  var watchers = [], mounted = new WeakMap(), pending = false;
  function scan() {
    watchers.forEach(function (watcher) {
      document.querySelectorAll(watcher.selector).forEach(function (element) {
        var seen = mounted.get(element) || [];
        if (seen.indexOf(watcher) >= 0) { return; }
        seen.push(watcher);
        mounted.set(element, seen);
        watcher.fn(element);
      });
    });
  }
  NYC.onMount = function (selector, fn) { watchers.push({ selector: selector, fn: fn }); scan(); };
  function schedule() {
    if (pending) { return; }
    pending = true;
    window.setTimeout(function () { pending = false; scan(); }, 40);   // a timer, not rAF: rAF stops in a hidden tab
  }

  /* Enter the window once. */
  var entrance = "IntersectionObserver" in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) { return; }
      entrance.unobserve(entry.target);
      entry.target.classList.add("is-in");
      if (entry.target.__onEnter) { entry.target.__onEnter(); }
    });
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 }) : null;
  function whenSeen(element, fn) {
    if (!entrance) { element.classList.add("is-in"); if (fn) { fn(); } return; }
    if (fn) { element.__onEnter = fn; }
    entrance.observe(element);
  }

  /* Replace an element's text with spans. Its accessible name stays the whole sentence. */
  function splitWords(element, wrap) {
    var text = element.textContent;
    if (!text.trim() || element.children.length) { return null; }
    element.textContent = "";
    // Screen readers read this one copy of the sentence; the animated words below are hidden from them.
    var spoken = document.createElement("span");
    spoken.className = "visually-hidden"; spoken.textContent = text;
    element.appendChild(spoken);
    var words = [];
    text.trim().split(/\s+/).forEach(function (word, index, all) {
      var node = wrap(word, index);
      node.setAttribute("aria-hidden", "true");
      words.push(node);
      element.appendChild(node);
      if (index < all.length - 1) { element.appendChild(document.createTextNode(" ")); }
    });
    return words;
  }

  NYC.onMount("[data-kinetic='words']", function (element) {
    if (NYC.reducedMotion()) { return; }
    var done = splitWords(element, function (word, index) {
      var outer = document.createElement("span"), inner = document.createElement("span");
      outer.className = "kw"; inner.className = "kw-i";
      inner.style.setProperty("--i", index);
      inner.textContent = word;
      outer.appendChild(inner);
      return outer;
    });
    if (done) { whenSeen(element); }
  });

  NYC.onMount("[data-kinetic='lines']", function (element) {
    if (NYC.reducedMotion()) { return; }
    element.classList.add("lift");
    whenSeen(element);
  });
  NYC.onMount(".lift", function (element) { whenSeen(element); });

  /* Words that light up as the paragraph moves through the window. */
  var scrubbing = [];
  NYC.onMount("[data-scrub='words']", function (element) {
    if (NYC.reducedMotion() || lite) { return; }
    var words = splitWords(element, function (word) {
      var span = document.createElement("span");
      span.className = "sw"; span.textContent = word;
      return span;
    });
    if (words) { scrubbing.push({ element: element, words: words }); onScroll(); }
  });
  function updateScrub(height) {
    scrubbing.forEach(function (item) {
      var box = item.element.getBoundingClientRect();
      if (box.bottom < -height * 0.2 || box.top > height * 1.2) { return; }
      var progress = (height * 0.9 - box.top) / (height * 0.5 + box.height);
      var lit = Math.max(0, Math.min(1, progress)) * (item.words.length + SCRUB_SOFT);
      item.words.forEach(function (word, index) {
        word.style.opacity = SCRUB_LOW + (1 - SCRUB_LOW) * Math.max(0, Math.min(1, (lit - index) / SCRUB_SOFT));
      });
    });
  }

  /* Figures roll into place when seen: each digit is a reel that spins down to its value, the right-most first,
     like the drum of a counter, while the figure comes into focus. The element's own nodes are put back at the end,
     so React still owns the text it rendered and the accessible name never changes. */
  NYC.countUp = function (element) {
    var final = element.getAttribute("data-final") || element.textContent;
    if (NYC.reducedMotion() || element.__rolling || element.textContent !== final) { return; }
    element.__rolling = true;
    var original = Array.prototype.slice.call(element.childNodes), reels = [], digits = 0;
    var holder = document.createElement("span");
    holder.className = "od"; holder.setAttribute("aria-hidden", "true");
    Array.prototype.forEach.call(final, function (character) { if (/\d/.test(character)) { digits++; } });
    var seen = 0;
    Array.prototype.forEach.call(final, function (character) {
      var cell = document.createElement("span");
      if (/\d/.test(character)) {
        var value = +character, strip = document.createElement("span"), spins = 1 + (digits - seen) % 2;
        cell.className = "od-cell"; strip.className = "od-strip";
        for (var k = 0; k <= spins * 10 + value; k++) {
          var digit = document.createElement("span");
          digit.className = "od-d"; digit.textContent = String(k % 10);
          strip.appendChild(digit);
        }
        strip.style.setProperty("--to", String(spins * 10 + value));
        strip.style.transitionDelay = ((digits - 1 - seen) * ROLL_STAGGER_MS) + "ms";
        strip.style.transitionDuration = ROLL_MS + "ms";
        cell.appendChild(strip);
        reels.push(strip);
        seen++;
      } else {
        cell.className = "od-c"; cell.textContent = character;
      }
      holder.appendChild(cell);
    });
    var spoken = document.createElement("span");
    spoken.className = "visually-hidden"; spoken.textContent = final;
    element.classList.add("is-rolling");
    element.replaceChildren(spoken, holder);
    void holder.offsetWidth;
    element.classList.add("is-rolled");
    window.setTimeout(function () {
      element.replaceChildren.apply(element, original);
      element.classList.remove("is-rolling", "is-rolled");
      element.__rolling = false;
    }, ROLL_MS + digits * ROLL_STAGGER_MS + 120);
  };
  NYC.onMount("[data-countup]", function (element) { whenSeen(element, function () { NYC.countUp(element); }); });

  /* The pointer's light on a .spot area trails the pointer: each frame it covers a fifth of the way that is left,
     and the loop stops as soon as it has caught up, so a still pointer costs nothing. */
  var light = { el: null, layer: null, x: 0, y: 0, tx: 0, ty: 0, raf: 0, fresh: false };
  /* The area's light layer: added on first use, and again if a re-render cleared the area's children. */
  function layerOf(spot) {
    var layer = spot.firstElementChild;
    if (layer && layer.classList.contains("spot-layer")) { return layer; }
    layer = document.createElement("span");
    layer.className = "spot-layer"; layer.setAttribute("aria-hidden", "true");
    spot.insertBefore(layer, spot.firstChild);
    return layer;
  }
  function follow() {
    light.raf = 0;
    if (!light.el) { return; }
    if (!light.layer || light.layer.parentNode !== light.el) { light.layer = layerOf(light.el); light.layer.style.setProperty("--lit", "1"); }
    light.x += (light.tx - light.x) * 0.2; light.y += (light.ty - light.y) * 0.2;
    light.layer.style.setProperty("--mx", light.x.toFixed(1) + "px");
    light.layer.style.setProperty("--my", light.y.toFixed(1) + "px");
    if (Math.abs(light.tx - light.x) > 0.5 || Math.abs(light.ty - light.y) > 0.5) { light.raf = window.requestAnimationFrame(follow); }
  }

  /* Hover and press, delegated so Dash re-renders never lose them. */
  document.addEventListener("pointermove", function (event) {
    if (!fine.matches || NYC.reducedMotion() || !event.target.closest) { return; }
    var spot = event.target.closest(".spot");
    if (spot !== light.el) {
      if (light.layer) { light.layer.style.setProperty("--lit", "0"); }
      light.el = spot; light.layer = spot ? layerOf(spot) : null;
      if (spot) { light.fresh = true; light.layer.style.setProperty("--lit", "1"); }
    }
    if (spot) {
      var area = spot.getBoundingClientRect();
      light.tx = event.clientX - area.left; light.ty = event.clientY - area.top;
      if (light.fresh) { light.x = light.tx; light.y = light.ty; light.fresh = false; }
      if (!light.raf) { light.raf = window.requestAnimationFrame(follow); }
    }
  }, { passive: true });
  document.addEventListener("pointerleave", function () { if (light.layer) { light.layer.style.setProperty("--lit", "0"); } light.el = light.layer = null; });
  document.addEventListener("pointerdown", function (event) {
    var button = event.target.closest && event.target.closest(".button");
    if (!button || NYC.reducedMotion()) { return; }
    var box = button.getBoundingClientRect(), ripple = document.createElement("span");
    ripple.className = "ripple"; ripple.style.left = (event.clientX - box.left) + "px"; ripple.style.top = (event.clientY - box.top) + "px";
    ripple.setAttribute("aria-hidden", "true");
    ripple.addEventListener("animationend", function () { ripple.remove(); });
    button.appendChild(ripple);
  }, { passive: true });

  /* The navigation's lit pill: it rests under the section in view and glides to a link while it is pointed at. */
  var pill = null, nav = null;
  function placePill(link) {
    if (!pill || !nav) { return; }
    if (!link) { pill.style.opacity = "0"; return; }
    pill.style.opacity = "1";
    pill.style.width = link.offsetWidth + "px";
    pill.style.transform = "translateX(" + (link.offsetLeft - nav.scrollLeft) + "px)";
  }
  function restingLink() { return nav && nav.querySelector(".nav-link[aria-current]"); }
  NYC.onMount(".nav", function (element) {
    nav = element;
    pill = document.createElement("span");
    pill.className = "nav-pill"; pill.setAttribute("aria-hidden", "true");
    element.insertBefore(pill, element.firstChild);
    element.addEventListener("pointerover", function (event) { var link = event.target.closest(".nav-link"); if (link) { placePill(link); } });
    element.addEventListener("focusin", function (event) { var link = event.target.closest(".nav-link"); if (link) { placePill(link); } });
    element.addEventListener("pointerleave", function () { placePill(restingLink()); });
    element.addEventListener("focusout", function () { placePill(restingLink()); });
    window.addEventListener("resize", function () { placePill(restingLink()); }, { passive: true });
  });

  /* Reading position, section in view, ground tint. */
  var ticking = false, sections = [], links = [], shownTint = null, page = null, thread = null, scrolled = null, read = null;
  NYC.onMount(".page", function (element) { page = element; scrolled = null; });
  NYC.onMount("#thread", function (element) { thread = element; read = null; });
  function update() {
    ticking = false;
    var doc = document.documentElement, height = window.innerHeight, top = window.scrollY;
    // Each is written only when it changes: a write, even of the same value, invalidates the styles beneath it.
    if (page && (top > 40) !== scrolled) { scrolled = top > 40; if (scrolled) { page.setAttribute("data-scrolled", ""); } else { page.removeAttribute("data-scrolled"); } }
    // getClientRects, not offsetParent: a fixed element has no offsetParent, so that test never let the thread fill.
    if (thread && thread.getClientRects().length) {
      var next = Math.min(1, top / Math.max(1, doc.scrollHeight - height)).toFixed(4);
      if (next !== read) { read = next; thread.style.setProperty("--read", next); }
    }
    updateScrub(height);
    var current = null;
    sections.forEach(function (section) {
      var box = section.getBoundingClientRect();
      if (box.top < height * 0.45 && box.bottom > height * 0.45) { current = section; }
    });
    if (current) {
      var tint = TINTS[current.getAttribute("data-tint")] || TINTS.midnight;
      // Only when it changes: setting it restyles the whole document, which on every scroll frame cost a phone dearly.
      if (tint !== shownTint) { shownTint = tint; document.documentElement.style.setProperty("--tint", tint); }
      var changed = false;
      links.forEach(function (link) {
        var mine = link.getAttribute("href") === "#" + current.id;
        if (mine !== link.hasAttribute("aria-current")) { changed = true; }
        if (mine) { link.setAttribute("aria-current", "true"); } else { link.removeAttribute("aria-current"); }
      });
      if (changed && nav && !nav.matches(":hover")) { placePill(restingLink()); }
    }
  }
  function onScroll() {
    if (ticking) { return; }
    ticking = true;
    window.requestAnimationFrame(update);
  }
  NYC.onMount("[data-tint]", function (section) { sections.push(section); onScroll(); });
  NYC.onMount(".nav-link", function (link) { links.push(link); });

  function start() {
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    scan();
    onScroll();
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", start); } else { start(); }
})();
