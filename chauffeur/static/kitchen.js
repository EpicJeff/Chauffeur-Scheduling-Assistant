/* The Kitchen — the family's ambient room on the wall.
 *
 * Spec: docs/superpowers/specs/2026-09-06-kitchen-design.md. The Study's
 * family-side twin, built on the same contracts (ZONES registry, applyState
 * as the sole data path, focus-then-through, since-you-were-here glow,
 * calm-first fallback) with one new discipline the wall demands:
 *
 *   RENDER ON DEMAND. No perpetual RAF loop. The scene draws a frame when
 *   state changes, while a camera tween runs, or while an HONEST animation
 *   is active (pot steam only when dinner is planned; the radio needle only
 *   while music actually plays). An idle kitchen costs the panel's GPU
 *   nothing — that is what lets a Raspberry Pi hold this page for weeks.
 *
 * The room never writes: this file performs GET only (pinned by test).
 */
(function () {
  'use strict';

  var ROOT = document.getElementById('room');
  var WRAP = document.getElementById('kitchen-wrap');
  var TIP = document.getElementById('tip');
  var CHIP = document.getElementById('chip');
  var FALLBACK = document.getElementById('fallback');
  var FALLROWS = document.getElementById('fallback-rows');
  if (!ROOT) return;

  var BASE = (typeof window.chfBase !== 'undefined' ? window.chfBase : '');
  var VISIT_KEY = 'chf_kitchen_last_visit';
  var POLL_MS = 60000;

  /* ---- since-you-were-here epoch (study idiom, seconds) ---------------- */
  function lastVisit() {
    try {
      var raw = localStorage.getItem(VISIT_KEY);
      var v = raw ? parseFloat(raw) : 0;
      return isFinite(v) ? v : 0;
    } catch (e) { return 0; }
  }
  function stampVisit() {
    try { localStorage.setItem(VISIT_KEY, String(Date.now() / 1000)); }
    catch (e) { /* private mode: the fridge just glows a little more */ }
  }

  /* ---- ZONES: the registry is the room's contract ---------------------- */
  /* Each zone: one signal number, a headline() for tips/fallback, and the
   * family page a tap falls through to. Attention-only furniture: nothing
   * here is decoration pretending to be data. */
  var ZONES = {
    fridge:   { label: 'Fridge',        url: 'moments',
                num: function (s) { return (s.fridge || {}).new_moments || 0; },
                headline: function (s) {
                  var f = s.fridge || {};
                  if (f.calm) return 'No new moments — the door is just a door today.';
                  var names = (f.latest || []).map(function (m) { return m.who || ''; })
                    .filter(Boolean).join(', ');
                  return f.new_moments + ' new moment' + (f.new_moments === 1 ? '' : 's') +
                    (names ? ' — ' + names : '');
                } },
    counter:  { label: 'Counter',       url: 'meals',
                num: function (s) { return (s.counter || {}).count || 0; },
                headline: function (s) {
                  var c = s.counter || {};
                  if (c.calm) return 'Nothing on the stove yet.';
                  var line = 'Tonight: ' + (c.dishes || []).join(', ');
                  if (c.hands_mins) line += ' — about ' + c.hands_mins + ' min hands-on';
                  return line;
                } },
    board:    { label: 'Corkboard',     url: 'lists',
                num: function (s) { return (s.board || {}).items || 0; },
                headline: function (s) {
                  var b = s.board || {};
                  if (b.calm) return 'The list is clear.';
                  return b.items + ' on the list: ' + (b.top || []).join(', ');
                } },
    door:     { label: 'Door',          url: 'home',
                num: function (s) {
                  var d = s.door || {};
                  return d.mins === null || d.mins === undefined ? 0 : 1;
                },
                headline: function (s) {
                  var d = s.door || {};
                  if (d.calm || d.mins === null || d.mins === undefined)
                    return 'Nobody has to leave — the door can stay shut.';
                  return 'Next out in ' + d.mins + ' min — ' + (d.label || '');
                } },
    calendar: { label: 'Wall calendar', url: 'calendar',
                num: function (s) { return (s.calendar || {}).today || 0; },
                headline: function (s) {
                  var c = s.calendar || {};
                  if (c.calm) return 'Nothing left on today.';
                  return c.today + ' still to come: ' + (c.next || []).join(' · ');
                } },
    radio:    { label: 'Radio',         url: 'music',
                num: function (s) { return (s.radio || {}).playing ? 1 : 0; },
                headline: function (s) {
                  var r = s.radio || {};
                  return r.playing ? ('Playing: ' + (r.track || 'something good'))
                                   : 'The radio is quiet.';
                } },
    pet:      { label: 'Pet bowl',      url: 'chores',
                num: function (s) { return (s.pet || {}).count || 0; },
                headline: function (s) {
                  var p = s.pet || {};
                  if (p.calm) return 'No pets at the bowl.';
                  return (p.pets || []).map(function (x) {
                    return x.name + ' (lv ' + x.level + ')';
                  }).join(', ');
                } }
  };
  var ZONE_ORDER = ['door', 'calendar', 'counter', 'fridge', 'board', 'radio', 'pet'];

  function go(slug) { window.location.href = BASE + slug + window.location.search; }

  /* ---- fallback: the DESIGNED weak-hardware experience ----------------- */
  /* textContent only — captions and dish names are family-typed strings and
   * this page renders on the most shared screen in the house. */
  function drawFallback(state) {
    FALLROWS.textContent = '';
    var h = document.createElement('h1');
    h.textContent = 'The Kitchen';
    FALLROWS.appendChild(h);
    ZONE_ORDER.forEach(function (key) {
      var z = ZONES[key];
      var s = state || {};
      var calm = !state || ((s[key] || {}).calm !== false);
      var row = document.createElement('a');
      row.className = 'frow' + (calm ? ' calm' : '');
      row.href = BASE + z.url + window.location.search;
      var name = document.createElement('div');
      name.textContent = z.label;
      var sig = document.createElement('div');
      sig.className = 'sig';
      sig.textContent = state ? z.headline(s) : 'Quiet.';
      row.appendChild(name); row.appendChild(sig);
      FALLROWS.appendChild(row);
    });
    FALLBACK.style.display = 'block';
  }

  /* ---- WebGL room ------------------------------------------------------ */
  var webgl = null;
  function buildRoom() {
    var T = window.THREE;
    if (!T) return null;
    var canvasProbe = document.createElement('canvas');
    var gl = canvasProbe.getContext('webgl2') || canvasProbe.getContext('webgl');
    if (!gl) return null;

    var scene = new T.Scene();
    scene.background = new T.Color(0xbdb3c7);          // the soft lilac of the reference
    var cam = new T.PerspectiveCamera(24, 1, 0.1, 90); // narrow FOV = near-isometric diorama
    var HOME_POS = new T.Vector3(17.5, 13.0, 17.5);
    var HOME_AT = new T.Vector3(-0.2, 0.8, -0.4);
    cam.position.copy(HOME_POS);
    cam.lookAt(HOME_AT);

    var R = new T.WebGLRenderer({ antialias: true });  // near-iso edges alias hard; AA is affordable once frames are on-demand
    R.setPixelRatio(1);                                // the Pi law: never a retina multiplier
    ROOT.appendChild(R.domElement);

    scene.add(new T.AmbientLight(0xfff4e6, 0.62));
    var sun = new T.DirectionalLight(0xfff0d8, 0.5);
    sun.position.set(8, 12, 6);
    scene.add(sun);
    var lamp = new T.PointLight(0xffd9a0, 0.28, 26);
    lamp.position.set(0, 5.2, 0);
    scene.add(lamp);

    /* palette (from the reference: cream shell, white cabinetry, wood tops,
       teal fridge panels, one red accent, one orange curtain) */
    var C = { shell: 0xefe9e2, wall: 0xf4efe8, cab: 0xf7f4ef, cabShade: 0xe6e0d6,
              top: 0xdfc79a, floorA: '#f2eee7', floorB: '#d8d2c8', steel: 0xb9bec4,
              dark: 0x4a4f55, teal: 0x3fbdb2, red: 0xc9473d, orange: 0xe09a3e,
              cork: 0xb5854f, wood: 0x8a6d4c, shadow: 0x3a3340 };

    function mat(c) { return new T.MeshLambertMaterial({ color: c }); }
    function box(w, h, d, c, x, y, z, group) {
      var m = new T.Mesh(new T.BoxGeometry(w, h, d), mat(c));
      m.position.set(x, y, z); (group || scene).add(m); return m;
    }
    function cyl(rt, rb, h, c, x, y, z, group, seg) {
      var m = new T.Mesh(new T.CylinderGeometry(rt, rb, h, seg || 10), mat(c));
      m.position.set(x, y, z); (group || scene).add(m); return m;
    }
    function knob(x, y, z, group) { return cyl(0.035, 0.035, 0.05, C.steel, x, y, z, group, 8); }
    function blobShadow(rx, rz, x, z, group) {
      var m = new T.Mesh(new T.CircleGeometry(1, 20),
        new T.MeshBasicMaterial({ color: C.shadow, transparent: true, opacity: 0.16 }));
      m.rotation.x = -Math.PI / 2;
      m.scale.set(rx, rz, 1);
      m.position.set(x, 0.012, z);
      (group || scene).add(m); return m;
    }

    /* ---- shell: open-corner diorama on a slab -------------------------- */
    box(13.6, 0.5, 11.6, C.shell, 0, -0.27, 0);
    var floorCanvas = document.createElement('canvas');
    floorCanvas.width = floorCanvas.height = 512;
    (function () {
      var g = floorCanvas.getContext('2d'), n = 8, t = 512 / n;
      for (var i = 0; i < n; i++) for (var j = 0; j < n; j++) {
        g.fillStyle = ((i + j) % 2) ? C.floorB : C.floorA;
        g.fillRect(i * t, j * t, t, t);
      }
    })();
    var floorTex = new T.CanvasTexture(floorCanvas);
    floorTex.magFilter = T.NearestFilter;
    var floor = new T.Mesh(new T.PlaneGeometry(13, 11),
      new T.MeshLambertMaterial({ map: floorTex }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = 0.001;
    scene.add(floor);

    box(13, 5.6, 0.35, C.wall, 0, 2.8, -5.55);          // back wall
    box(0.35, 5.6, 11, C.wall, -6.65, 2.8, 0);          // left wall
    box(13.6, 0.28, 0.5, C.shell, 0, 5.66, -5.6);       // wall caps
    box(0.5, 0.28, 11.6, C.shell, -6.7, 5.66, 0);

    /* tiled backsplash band behind the counter run */
    var bsCanvas = document.createElement('canvas');
    bsCanvas.width = 256; bsCanvas.height = 64;
    (function () {
      var g = bsCanvas.getContext('2d');
      g.fillStyle = '#f8f6f1'; g.fillRect(0, 0, 256, 64);
      g.strokeStyle = '#ddd6ca'; g.lineWidth = 2;
      for (var x = 0; x <= 256; x += 32) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, 64); g.stroke(); }
      for (var y = 0; y <= 64; y += 16) { g.beginPath(); g.moveTo(0, y); g.lineTo(256, y); g.stroke(); }
    })();
    var bs = new T.Mesh(new T.PlaneGeometry(8.6, 1.0),
      new T.MeshLambertMaterial({ map: new T.CanvasTexture(bsCanvas) }));
    bs.position.set(-1.2, 1.62, -5.36);
    scene.add(bs);

    var groups = {};
    function zoneGroup(key, x, y, z) {
      var g = new T.Group();
      g.position.set(x, y, z);
      g.userData.zone = key;
      groups[key] = g; scene.add(g); return g;
    }

    /* ---- cabinet run along the back wall (decor + sink + window) ------- */
    function lowerCab(w, x, z, group, doors) {
      var g2 = group || scene;
      box(w, 1.0, 1.4, C.cab, x, 0.56, z, g2);
      var n = doors || Math.max(1, Math.round(w / 0.95));
      for (var i = 0; i < n; i++) {
        var dw = w / n - 0.1, dx = x - w / 2 + (i + 0.5) * (w / n);
        box(dw, 0.78, 0.05, C.cabShade, dx, 0.56, z + 0.71, g2);
        knob(dx + dw / 2 - 0.09, 0.72, z + 0.76, g2);
      }
    }
    function upperCab(w, x, z) {
      box(w, 1.25, 0.72, C.cab, x, 3.75, z);
      var n = Math.max(1, Math.round(w / 0.9));
      for (var i = 0; i < n; i++) {
        var dw = w / n - 0.08, dx = x - w / 2 + (i + 0.5) * (w / n);
        box(dw, 1.05, 0.05, C.cabShade, dx, 3.75, z + 0.37);
        knob(dx + dw / 2 - 0.08, 3.45, z + 0.42);
      }
    }
    lowerCab(5.4, -2.2, -4.6);
    box(5.6, 0.12, 1.56, 0xf3ede2, -2.2, 1.12, -4.6);   // countertop
    upperCab(2.0, -4.3, -5.1);
    upperCab(2.0, 0.3, -5.1);

    /* sink + faucet in the middle of the run */
    box(0.9, 0.06, 0.6, C.steel, -2.2, 1.155, -4.62);
    cyl(0.05, 0.05, 0.45, C.steel, -2.5, 1.4, -4.95);
    box(0.34, 0.06, 0.08, C.steel, -2.35, 1.6, -4.95);

    /* window with orange curtain above the sink */
    box(1.9, 1.7, 0.1, 0xcfe4ec, -2.2, 3.4, -5.42);
    box(2.1, 0.12, 0.16, C.cab, -2.2, 4.32, -5.4);
    box(0.12, 1.9, 0.16, C.cab, -3.22, 3.38, -5.4);
    box(0.12, 1.9, 0.16, C.cab, -1.18, 3.38, -5.4);
    var curtain = box(0.55, 1.2, 0.08, C.orange, -2.85, 3.75, -5.32);
    curtain.rotation.z = 0.08;

    /* counter props: bottles, jar, plate stack */
    cyl(0.07, 0.07, 0.4, C.red, -4.4, 1.38, -4.7, null, 8);
    cyl(0.07, 0.07, 0.34, 0x6a4a2f, -4.2, 1.35, -4.85, null, 8);
    cyl(0.12, 0.12, 0.2, 0xead9b8, -3.6, 1.28, -4.75, null, 10);
    box(0.4, 0.14, 0.4, 0xdad2c2, -0.4, 1.25, -4.8);

    /* ---- STOVE (zone: counter) with hood ------------------------------- */
    var counter = zoneGroup('counter', 1.7, 0, -4.55);
    box(1.5, 1.02, 1.45, C.dark, 0, 0.57, 0, counter);
    box(1.3, 0.62, 0.06, 0x5a6067, 0, 0.5, 0.74, counter);
    box(1.1, 0.06, 0.09, C.steel, 0, 0.86, 0.78, counter);
    box(1.5, 0.05, 1.45, 0x3c4147, 0, 1.11, 0, counter);
    cyl(0.16, 0.16, 0.03, 0x23262a, -0.4, 1.15, 0.3, counter, 12);
    cyl(0.16, 0.16, 0.03, 0x23262a, 0.4, 1.15, 0.3, counter, 12);
    cyl(0.16, 0.16, 0.03, 0x23262a, -0.4, 1.15, -0.35, counter, 12);
    cyl(0.16, 0.16, 0.03, 0x23262a, 0.4, 1.15, -0.35, counter, 12);
    cyl(0.3, 0.3, 0.3, 0x8e969d, -0.4, 1.32, 0.3, counter, 14);
    cyl(0.31, 0.31, 0.05, 0x6f767d, -0.4, 1.5, 0.3, counter, 14);
    cyl(0.26, 0.26, 0.22, C.red, 0.4, 1.28, -0.35, counter, 14);
    var steam = box(0.16, 0.5, 0.16, 0xf2ead6, -0.4, 2.0, 0.3, counter);
    steam.material.transparent = true; steam.material.opacity = 0;
    box(1.7, 0.5, 1.0, C.wall, 0, 3.05, -0.2, counter);
    box(1.1, 1.8, 0.8, C.wall, 0, 4.2, -0.35, counter);
    blobShadow(1.0, 0.85, 1.7, -4.35);

    /* ---- FRIDGE (zone: fridge) — teal panels + moment magnets ---------- */
    var fridge = zoneGroup('fridge', -5.35, 0, -3.4);
    box(1.9, 3.9, 1.6, C.steel, 0, 1.95, 0, fridge);
    box(1.6, 1.55, 0.07, C.teal, 0, 2.9, 0.82, fridge);
    box(1.6, 1.35, 0.07, C.teal, 0, 1.0, 0.82, fridge);
    box(0.07, 1.3, 0.09, C.steel, 0.62, 2.9, 0.87, fridge);
    box(0.07, 1.0, 0.09, C.steel, 0.62, 1.05, 0.87, fridge);
    var magnets = new T.Group();
    magnets.position.set(0, 0, 0.9);
    fridge.add(magnets);
    blobShadow(1.15, 0.95, -5.35, -3.4);

    /* ---- CORKBOARD (zone: board) on the left wall ---------------------- */
    var board = zoneGroup('board', -6.42, 0, -0.6);
    var boardFace = new T.Mesh(new T.PlaneGeometry(2.0, 1.5),
      new T.MeshLambertMaterial({ color: C.cork }));
    boardFace.rotation.y = Math.PI / 2;
    boardFace.position.set(0.06, 2.5, 0);
    board.add(boardFace);
    box(0.06, 1.66, 2.16, 0x8a6335, -0.02, 2.5, 0, board);

    /* ---- WALL CALENDAR (zone: calendar) on the back wall --------------- */
    var calG = zoneGroup('calendar', 3.6, 0, -5.36);
    var calFace = new T.Mesh(new T.PlaneGeometry(1.5, 1.9),
      new T.MeshLambertMaterial({ color: 0xf6f1e4 }));
    calFace.position.set(0, 3.0, 0.05);
    calG.add(calFace);
    box(1.62, 0.1, 0.08, C.red, 0, 4.0, 0.02, calG);

    /* ---- DOOR (zone: door) on the back wall right ---------------------- */
    var doorG = zoneGroup('door', 5.35, 0, -5.32);
    box(1.7, 4.1, 0.14, 0x9b7b53, 0, 2.05, 0, doorG);
    box(1.3, 1.4, 0.05, 0x8a6d49, 0, 2.9, 0.08, doorG);
    box(1.3, 1.2, 0.05, 0x8a6d49, 0, 1.2, 0.08, doorG);
    cyl(0.07, 0.07, 0.1, 0xd8c48a, 0.6, 2.0, 0.1, doorG, 8);
    var plaque = new T.Mesh(new T.PlaneGeometry(1.24, 0.5),
      new T.MeshLambertMaterial({ color: 0xefe6cf }));
    plaque.position.set(0, 4.4, 0.09);
    doorG.add(plaque);

    /* ---- RADIO (zone: radio) on the countertop ------------------------- */
    var radio = zoneGroup('radio', 0.35, 0, -4.62);
    box(0.8, 0.45, 0.4, C.red, 0, 1.41, 0, radio);
    box(0.55, 0.28, 0.03, 0xf2e3b8, -0.06, 1.42, 0.21, radio);
    cyl(0.035, 0.035, 0.1, C.steel, 0.28, 1.68, 0, radio, 8);
    var needle = box(0.04, 0.22, 0.04, 0x3a332a, 0.28, 1.78, 0, radio);

    /* ---- ISLAND (decor) + stools + high chair -------------------------- */
    box(3.4, 1.0, 2.0, C.cab, -0.4, 0.56, 0.9);
    box(3.2, 0.66, 0.05, C.cabShade, -0.4, 0.5, 1.92);
    knob(-1.1, 0.62, 1.97); knob(0.3, 0.62, 1.97);
    box(3.7, 0.14, 2.3, 0xf3ede2, -0.4, 1.13, 0.9);
    box(1.1, 0.06, 0.75, C.red, -1.2, 1.23, 0.7);
    for (var cx = 0; cx < 4; cx++) for (var cz = 0; cz < 2; cz++) {
      cyl(0.09, 0.07, 0.1, 0xf5e6d0, -1.55 + cx * 0.24, 1.31, 0.55 + cz * 0.3, null, 8);
      cyl(0.07, 0.09, 0.08, (cx + cz) % 2 ? C.teal : C.red,
          -1.55 + cx * 0.24, 1.4, 0.55 + cz * 0.3, null, 8);
    }
    cyl(0.34, 0.26, 0.16, 0xead9b8, 0.7, 1.3, 0.9, null, 12);
    cyl(0.09, 0.09, 0.1, C.orange, 0.58, 1.42, 0.85, null, 8);
    cyl(0.09, 0.09, 0.1, C.red, 0.82, 1.42, 0.95, null, 8);
    blobShadow(2.1, 1.4, -0.4, 0.9);
    function stool(x, z) {
      cyl(0.3, 0.26, 0.08, C.wood, x, 0.86, z, null, 10);
      cyl(0.05, 0.07, 0.84, 0x6e5539, x, 0.42, z, null, 8);
      blobShadow(0.34, 0.3, x, z);
    }
    stool(1.9, 0.5); stool(1.9, 1.5);
    var hc = new T.Group(); hc.position.set(2.7, 0, 2.6); scene.add(hc);
    box(0.5, 0.08, 0.45, C.steel, 0, 1.05, 0, hc);
    box(0.5, 0.5, 0.07, C.steel, 0, 1.36, -0.2, hc);
    box(0.07, 1.05, 0.07, C.steel, -0.2, 0.55, -0.16, hc);
    box(0.07, 1.05, 0.07, C.steel, 0.2, 0.55, -0.16, hc);
    box(0.07, 1.0, 0.07, C.steel, -0.16, 0.5, 0.2, hc);
    box(0.07, 1.0, 0.07, C.steel, 0.16, 0.5, 0.2, hc);
    blobShadow(0.4, 0.35, 2.7, 2.6);

    /* ---- PET BOWL (zone: pet) ------------------------------------------ */
    var bowl = zoneGroup('pet', -5.0, 0, 2.8);
    cyl(0.42, 0.32, 0.2, C.red, 0, 0.1, 0, bowl, 14);
    cyl(0.34, 0.34, 0.06, 0x6a4a2f, 0, 0.2, 0, bowl, 14);
    cyl(0.05, 0.05, 0.04, 0x8a6335, 0.5, 0.02, 0.2, bowl, 6);
    cyl(0.05, 0.05, 0.04, 0x8a6335, 0.42, 0.02, -0.25, bowl, 6);
    blobShadow(0.5, 0.42, -5.0, 2.8);

    /* canvas-texture detail (study slice-3 idiom): painted lazily,
       cached per payload change */
    var texCache = {};
    function detailTexture(key, lines) {
      var payload = key + '|' + lines.join('|');
      if (texCache[key] && texCache[key].payload === payload) return texCache[key].tex;
      var c = document.createElement('canvas'); c.width = 256; c.height = 256;
      var g = c.getContext('2d');
      g.fillStyle = key === 'board' ? '#c99a63' : '#f6f1e4';
      g.fillRect(0, 0, 256, 256);
      g.fillStyle = '#3a2f1f'; g.font = '600 20px system-ui';
      var y = 34;
      lines.slice(0, 8).forEach(function (line) {
        g.fillText(String(line).slice(0, 24), 14, y); y += 28;
      });
      var tex = new T.CanvasTexture(c);
      texCache[key] = { payload: payload, tex: tex };
      return tex;
    }

    return {
      T: T, scene: scene, cam: cam, R: R, groups: groups,
      steam: steam, needle: needle, plaque: plaque, calFace: calFace,
      boardFace: boardFace, magnets: magnets,
      HOME_POS: HOME_POS, HOME_AT: HOME_AT, detailTexture: detailTexture
    };
  }

  /* ---- render-on-demand engine ---------------------------------------- */
  var state = null;
  var focused = null;        // zone key while leaned in
  var lookAt = null;         // the camera's CURRENT look target (tween continuity)
  var tween = null;          // {fromP,toP,fromA,toA,t0,ms,cb}
  var rafLive = false;

  function requestFrame() {
    if (!rafLive && webgl) { rafLive = true; requestAnimationFrame(frame); }
  }

  function honestAnimationActive() {
    if (!state) return false;
    var cooking = state.counter && state.counter.calm === false;
    var playing = state.radio && state.radio.playing;
    return !!(cooking || playing);
  }

  function frame(tms) {
    rafLive = false;
    if (!webgl) return;
    var keep = false;

    if (tween) {
      var k = Math.min(1, (performance.now() - tween.t0) / tween.ms);
      var e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      webgl.cam.position.lerpVectors(tween.fromP, tween.toP, e);
      var at = new webgl.T.Vector3().lerpVectors(tween.fromA, tween.toA, e);
      lookAt = at.clone();
      webgl.cam.lookAt(at);
      if (k >= 1) { var cb = tween.cb; tween = null; if (cb) cb(); }
      else keep = true;
    }

    if (honestAnimationActive()) {
      var t = (tms || 0) / 1000;
      if (state.counter && state.counter.calm === false) {
        webgl.steam.material.opacity = 0.35 + 0.2 * Math.sin(t * 2.1);
        webgl.steam.position.y = 2.1 + 0.08 * Math.sin(t * 1.3);
      } else { webgl.steam.material.opacity = 0; }
      if (state.radio && state.radio.playing) {
        webgl.needle.rotation.z = 0.25 * Math.sin(t * 3.0);
      }
      keep = true;
    } else if (webgl.steam) {
      webgl.steam.material.opacity = 0;
    }

    webgl.R.render(webgl.scene, webgl.cam);
    if (keep) { rafLive = true; requestAnimationFrame(frame); }
  }

  function size() {
    if (!webgl) return;
    var w = ROOT.clientWidth || 1, h = ROOT.clientHeight || 1;
    webgl.R.setSize(w, h, false);
    webgl.cam.aspect = w / h;
    webgl.cam.updateProjectionMatrix();
    requestFrame();
  }

  /* ---- applyState: the sole data path ---------------------------------- */
  var glowSet = {};
  function applyState(s) {
    state = s;
    if (!webgl) { drawFallback(s); return; }
    var T = webgl.T;

    Object.keys(ZONES).forEach(function (key) {
      var g = webgl.groups[key];
      if (!g) return;
      var n = ZONES[key].num(s);
      var lit = n > 0 && (s[key] || {}).calm === false;
      g.traverse(function (o) {
        if (o.isMesh && o.material && o.material.emissive) {
          o.material.emissive.setHex(lit ? 0x2a1e08 : 0x000000);
        }
      });
    });

    /* honest detail faces, cheap to repaint only when payloads change */
    var d = s.door || {};
    var doorTex = webgl.detailTexture('door',
      d.calm !== false ? ['—'] : [(d.mins != null ? d.mins + ' min' : ''), d.label || '']);
    if (webgl.plaque.material.map !== doorTex) {
      webgl.plaque.material.map = doorTex;
      webgl.plaque.material.needsUpdate = true;
    }
    var c = s.calendar || {};
    var calTex = webgl.detailTexture('calendar',
      c.calm !== false ? ['Today', 'clear'] : ['Today: ' + c.today].concat(c.next || []));
    if (webgl.calFace.material.map !== calTex) {
      webgl.calFace.material.map = calTex;
      webgl.calFace.material.needsUpdate = true;
    }
    var bd = s.board || {};
    var boardTex = webgl.detailTexture('board',
      bd.calm !== false ? ['The list is clear'] : ['List: ' + bd.items].concat(bd.top || []));
    if (webgl.boardFace.material.map !== boardTex) {
      webgl.boardFace.material.map = boardTex;
      webgl.boardFace.material.needsUpdate = true;
    }

    /* moment magnets on the fridge door: one colored square each, capped */
    var wantMagnets = Math.min(((s.fridge || {}).new_moments || 0), 6);
    if (webgl.magnets.children.length !== wantMagnets) {
      while (webgl.magnets.children.length) webgl.magnets.remove(webgl.magnets.children[0]);
      var MAG_COLORS = [0xc9473d, 0x3fbdb2, 0xe09a3e, 0x5a7fc0, 0x7fae5a, 0xb06ab0];
      for (var mi = 0; mi < wantMagnets; mi++) {
        var mm = new webgl.T.Mesh(new webgl.T.BoxGeometry(0.22, 0.22, 0.03),
          new webgl.T.MeshLambertMaterial({ color: MAG_COLORS[mi % 6] }));
        mm.position.set(-0.45 + (mi % 3) * 0.45, 3.2 - Math.floor(mi / 3) * 0.42, 0);
        webgl.magnets.add(mm);
      }
    }

    requestFrame();
  }

  /* ---- focus-then-through (universal lean-in, generic bbox framing) ----- */
  function frameZone(key, cb) {
    var g = webgl.groups[key];
    var boxb = new webgl.T.Box3().setFromObject(g);
    var center = boxb.getCenter(new webgl.T.Vector3());
    var size3 = boxb.getSize(new webgl.T.Vector3());
    var span = Math.max(size3.x, size3.y, size3.z);
    var dist = (span / 2) / Math.tan((webgl.cam.fov / 2) * Math.PI / 180) * 1.45 + 0.8;
    var dir = new webgl.T.Vector3().subVectors(webgl.cam.position, center).normalize();
    var toP = center.clone().add(dir.multiplyScalar(dist));
    toP.y = Math.max(toP.y, center.y + 0.6);
    tween = { fromP: webgl.cam.position.clone(), toP: toP,
              fromA: (lookAt || webgl.HOME_AT).clone(),
              toA: center, t0: performance.now(), ms: 650, cb: cb };
    requestFrame();
  }
  function goHome() {
    tween = { fromP: webgl.cam.position.clone(), toP: webgl.HOME_POS.clone(),
              fromA: (lookAt || webgl.HOME_AT).clone(), toA: webgl.HOME_AT.clone(),
              t0: performance.now(), ms: 650, cb: null };
    focused = null;
    TIP.style.opacity = 0;
    requestFrame();
  }

  function zoneAt(clientX, clientY) {
    if (!webgl) return null;
    var rect = webgl.R.domElement.getBoundingClientRect();
    var v = new webgl.T.Vector2(((clientX - rect.left) / rect.width) * 2 - 1,
                                -((clientY - rect.top) / rect.height) * 2 + 1);
    var ray = new webgl.T.Raycaster();
    ray.setFromCamera(v, webgl.cam);
    var hits = ray.intersectObjects(webgl.scene.children, true);
    for (var i = 0; i < hits.length; i++) {
      var o = hits[i].object;
      while (o) {
        if (o.userData && o.userData.zone) return o.userData.zone;
        o = o.parent;
      }
    }
    return null;
  }

  function onTap(ev) {
    var key = zoneAt(ev.clientX, ev.clientY);
    if (!key) { if (focused) goHome(); return; }
    if (focused === key) { go(ZONES[key].url); return; }   // second tap: through
    focused = key;
    frameZone(key, function () {
      if (state) {
        TIP.textContent = ZONES[key].label + ' — ' + ZONES[key].headline(state);
        TIP.style.left = '16px';
        TIP.style.bottom = '64px';
        TIP.style.top = 'auto';
        TIP.style.opacity = 1;
      }
    });
  }

  /* ---- poll (60s), one-time outage chip -------------------------------- */
  var chipShown = false;    // once per OUTAGE, re-armed by the next good poll
  function chip(text) {
    if (chipShown) return;
    chipShown = true;
    CHIP.textContent = text;
    CHIP.style.opacity = 1;
    setTimeout(function () { CHIP.style.opacity = 0; }, 6000);
  }
  function clearOutage() {
    chipShown = false;
    CHIP.style.opacity = 0;
  }

  var sinceEpoch = lastVisit();
  function poll() {
    fetch(window.KITCHEN_STATE_URL + '?since=' + encodeURIComponent(sinceEpoch),
          { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      })
      .then(function (s) { clearOutage(); applyState(s); })
      .catch(function () {
        chip('The kitchen lost the house for a moment — showing the last look.');
        if (!state) drawFallback(null);
      });
  }

  /* ---- boot ------------------------------------------------------------ */
  try { webgl = buildRoom(); } catch (e) { webgl = null; }
  if (webgl) {
    webgl.R.domElement.addEventListener('webglcontextlost', function (e) {
      e.preventDefault();
      /* the graceful death: swap to the calm 2D room, stop asking the GPU */
      try { ROOT.style.display = 'none'; } catch (err) {}
      webgl = null;
      drawFallback(state);
    });
    webgl.R.domElement.addEventListener('click', onTap);
    window.addEventListener('resize', size);
    size();
  } else {
    drawFallback(null);
  }

  poll();
  setInterval(function () {
    if (document.visibilityState === 'visible') poll();
  }, POLL_MS);
  setTimeout(stampVisit, 10000);   // study idiom: glows survive a quick reload
})();
