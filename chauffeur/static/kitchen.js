/* The Kitchen — the family's ambient room on the wall.
 *
 * Spec: docs/superpowers/specs/2026-09-06-kitchen-design.md. The Study's
 * family-side twin, built on the same contracts (ZONES registry, applyState
 * as the sole data path, focus-then-through, since-you-were-here glow,
 * calm-first fallback) with two disciplines the wall demands:
 *
 * RENDER ON DEMAND. No perpetual RAF loop. The scene draws a frame when
 * state changes, while a camera tween runs, or while an HONEST animation is
 * active (pot steam only when dinner is planned; the radio needle only while
 * music actually plays). Because frames are rare, each one can be expensive:
 * the high tier runs real soft shadow maps, physically-based materials,
 * rounded-edge geometry and filmic tone mapping without costing an idle
 * panel anything.
 *
 * QUALITY TIERS, like a game. high -> medium -> low -> 2d. The page boots at
 * its stored tier (default high), measures a burst of frames once, and if
 * the hardware can't hold the budget it persists the next tier down and
 * reloads — so a Raspberry Pi settles into the tier it can afford and stays
 * there, while a desktop gets the full look. `?quality=high|medium|low|2d`
 * overrides and persists. The 2D fallback remains a first-class room.
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
  var QUALITY_KEY = 'chf_kitchen_quality2';  // v2: the v1 benchmark measured shader-compile and demoted everyone
  var POLL_MS = 60000;
  var TIERS = ['high', 'medium', 'low', '2d'];

  /* ---- quality tier: stored, overridable, benchmarked ------------------ */
  function pickQuality() {
    var q = null;
    try {
      q = new URLSearchParams(window.location.search).get('quality');
    } catch (e) { /* ancient parser: stored tier decides */ }
    if (q && TIERS.indexOf(q) !== -1) {
      try { localStorage.setItem(QUALITY_KEY, q); } catch (e) {}
      return q;
    }
    try {
      var stored = localStorage.getItem(QUALITY_KEY);
      if (stored && TIERS.indexOf(stored) !== -1) return stored;
    } catch (e) {}
    return 'high';
  }
  var QUALITY = pickQuality();
  var DETAIL = { high: 3, medium: 2, low: 1 }[QUALITY] || 0;
  var FORCED = false;   // explicit ?quality= means the human chose; no auto-demote
  try {
    FORCED = TIERS.indexOf(new URLSearchParams(window.location.search).get('quality')) !== -1;
  } catch (e) {}

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
    window:   { label: 'Window',        url: 'calendar',
                num: function (s) { return (s.window || {}).calm === false ? 1 : 0; },
                headline: function (s) {
                  var w = s.window || {};
                  if (!w.cond) return 'The sky is keeping to itself.';
                  var t = (w.temp !== null && w.temp !== undefined) ? Math.round(w.temp) + '\u00b0 ' : '';
                  return t + w.cond + (w.calm === false ? ' \u2014 plan for it' : '');
                } },
    pet:      { label: 'Critters',      url: 'chores',
                num: function (s) { return (s.pet || {}).count || 0; },
                headline: function (s) {
                  var p = s.pet || {};
                  if (p.calm) return 'The critters are resting.';
                  return (p.pets || []).map(function (x) {
                    return x.name + ' (lv ' + x.level + ')';
                  }).join(', ');
                } }
  };
  var ZONE_ORDER = ['door', 'window', 'calendar', 'counter', 'fridge', 'board', 'radio', 'pet'];

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
    if (!T || DETAIL < 1) return null;
    var canvasProbe = document.createElement('canvas');
    var gl = canvasProbe.getContext('webgl2') || canvasProbe.getContext('webgl');
    if (!gl) return null;

    var SHADOWS = DETAIL >= 3;            // real soft shadow maps: high only
    var PBR = DETAIL >= 3;                // standard materials vs lambert

    var scene = new T.Scene();
    scene.background = new T.Color(0xbdb3c7);          // the soft lilac of the reference
    var cam = new T.PerspectiveCamera(24, 1, 0.1, 90); // narrow FOV = near-isometric diorama
    var HOME_POS = new T.Vector3(17.5, 13.0, 17.5);
    var HOME_AT = new T.Vector3(-0.2, 0.8, -0.4);
    cam.position.copy(HOME_POS);
    cam.lookAt(HOME_AT);

    var R = new T.WebGLRenderer({ antialias: DETAIL >= 2 });
    R.setPixelRatio(1);                                // the Pi law: never a retina multiplier
    if (PBR) {
      /* frames are rare, so each one can afford the full render look */
      R.toneMapping = T.ACESFilmicToneMapping;
      R.toneMappingExposure = 1.0;
      /* no sRGB output pass: the legacy three build has color management
         off, so the extra encode only bleaches every authored color */
    }
    if (SHADOWS) {
      R.shadowMap.enabled = true;
      R.shadowMap.type = T.PCFSoftShadowMap;
    }
    ROOT.appendChild(R.domElement);

    if (PBR) {
      scene.add(new T.HemisphereLight(0xd9defc, 0xb8926a, 0.45));
      scene.add(new T.AmbientLight(0xfff4e6, 0.14));
    } else {
      scene.add(new T.AmbientLight(0xfff4e6, DETAIL >= 2 ? 0.62 : 0.75));
    }
    var sun = new T.DirectionalLight(0xfff1dc, PBR ? 1.0 : 0.5);
    sun.position.set(10.5, 12, 4.5);
    scene.add(sun);
    if (SHADOWS) {
      sun.castShadow = true;
      sun.shadow.mapSize.set(2048, 2048);
      sun.shadow.camera.left = -10; sun.shadow.camera.right = 10;
      sun.shadow.camera.top = 12; sun.shadow.camera.bottom = -10;
      sun.shadow.camera.near = 2; sun.shadow.camera.far = 45;
      sun.shadow.bias = -0.0006;
      sun.shadow.radius = 3;
    }
    if (DETAIL >= 2) {
      var lamp = new T.PointLight(0xffd9a0, PBR ? 0.5 : 0.28, 26);
      lamp.position.set(0, 5.2, 0);
      scene.add(lamp);
    }

    /* ---- procedural material library (canvas textures, zero downloads) -- */
    var C = { shell: 0xefe9e2, wall: 0xf4efe8, cab: 0xf7f4ef, cabShade: 0xe6e0d6,
              floorA: '#f1ece3', floorB: '#cfc7b8', steel: 0xb9bec4,
              dark: 0x4a4f55, teal: 0x3fbdb2, red: 0xc9473d, orange: 0xe09a3e,
              cork: 0xb5854f, wood: 0x8a6d4c, wood2: 0x6e5539, shadow: 0x3a3340,
              leaf: 0x5f8f4e, bread: 0xcf9a55 };

    function canvasTex(size, draw) {
      var c = document.createElement('canvas');
      c.width = c.height = size;
      draw(c.getContext('2d'), size);
      var t = new T.CanvasTexture(c);
      t.anisotropy = 4;
      return t;
    }
    /* wood grain: base tone + long translucent streaks + fine noise */
    function woodTex(base, streak, vertical) {
      return canvasTex(256, function (g, S) {
        g.fillStyle = base; g.fillRect(0, 0, S, S);
        for (var i = 0; i < 34; i++) {
          g.strokeStyle = 'rgba(' + streak + ',' + (0.10 + Math.random() * 0.22) + ')';
          g.lineWidth = 1 + Math.random() * 3;
          var a = Math.random() * S, wob = (Math.random() - 0.5) * 22;
          g.beginPath();
          if (vertical) { g.moveTo(a, -10); g.bezierCurveTo(a + wob, S * 0.33, a - wob, S * 0.66, a, S + 10); }
          else { g.moveTo(-10, a); g.bezierCurveTo(S * 0.33, a + wob, S * 0.66, a - wob, S + 10, a); }
          g.stroke();
        }
        for (var n = 0; n < 400; n++) {
          g.fillStyle = 'rgba(60,40,20,' + (Math.random() * 0.05) + ')';
          g.fillRect(Math.random() * S, Math.random() * S, 2, 2);
        }
      });
    }
    /* marble: warm white + soft gray veins */
    function marbleTex() {
      return canvasTex(256, function (g, S) {
        g.fillStyle = '#f5f2ec'; g.fillRect(0, 0, S, S);
        for (var i = 0; i < 7; i++) {
          g.strokeStyle = 'rgba(120,120,130,' + (0.12 + Math.random() * 0.15) + ')';
          g.lineWidth = 1 + Math.random() * 2;
          var x = Math.random() * S;
          g.beginPath(); g.moveTo(x, 0);
          g.bezierCurveTo(x + 60 * (Math.random() - 0.5), S * 0.3,
                          x + 90 * (Math.random() - 0.5), S * 0.7,
                          x + 40 * (Math.random() - 0.5), S);
          g.stroke();
        }
        g.fillStyle = 'rgba(200,195,185,0.25)';
        for (var j = 0; j < 60; j++) g.fillRect(Math.random() * S, Math.random() * S, 3, 1);
      });
    }
    /* brushed steel: vertical hairlines over a silver base */
    function steelTex() {
      return canvasTex(256, function (g, S) {
        g.fillStyle = '#c7ccd1'; g.fillRect(0, 0, S, S);
        for (var i = 0; i < 220; i++) {
          var v = 175 + Math.floor(Math.random() * 60);
          g.strokeStyle = 'rgba(' + v + ',' + (v + 3) + ',' + (v + 6) + ',0.5)';
          g.lineWidth = 1;
          var x = Math.random() * S;
          g.beginPath(); g.moveTo(x, 0); g.lineTo(x, S); g.stroke();
        }
      });
    }
    /* sky for the window pane: bright, slightly graded, faintly emissive */
    function skyTex() {
      return canvasTex(128, function (g, S) {
        var grad = g.createLinearGradient(0, 0, 0, S);
        grad.addColorStop(0, '#c7e4f5'); grad.addColorStop(0.7, '#eaf6fc');
        grad.addColorStop(1, '#fdfdf6');
        g.fillStyle = grad; g.fillRect(0, 0, S, S);
        g.fillStyle = 'rgba(255,255,255,0.75)';
        g.beginPath(); g.arc(S * 0.3, S * 0.3, 13, 0, 7); g.fill();
        g.beginPath(); g.arc(S * 0.45, S * 0.32, 17, 0, 7); g.fill();
        g.beginPath(); g.arc(S * 0.6, S * 0.28, 12, 0, 7); g.fill();
      });
    }
    /* tiny procedural cube env: what the metals reflect. Without this, PBR
       metalness has nothing to see and reads as gray plastic. */
    /* Reflections need something WORTH reflecting: a bright sky above, a
       dark warm floor below, and one hot window stripe on a wall so chrome
       gets a highlight streak. PMREM prefilters it so every roughness level
       samples a correctly blurred version — this single step is the
       difference between painted plastic and material. */
    if (PBR) {
      function envFace(draw) {
        var c = document.createElement('canvas'); c.width = c.height = 128;
        draw(c.getContext('2d'));
        return c;
      }
      function wallFace(stripe) {
        return envFace(function (g) {
          var grad = g.createLinearGradient(0, 0, 0, 128);
          grad.addColorStop(0, '#efe4d0'); grad.addColorStop(1, '#8f8270');
          g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
          if (stripe) {
            g.fillStyle = '#ffffff';
            g.fillRect(84, 8, 30, 88);
            g.fillStyle = 'rgba(255,244,214,0.55)';
            g.fillRect(74, 4, 50, 100);
          }
        });
      }
      var envCube = new T.CubeTexture([
        wallFace(true), wallFace(false),
        envFace(function (g) {
          var grad = g.createLinearGradient(0, 0, 0, 128);
          grad.addColorStop(0, '#e9edf6'); grad.addColorStop(1, '#c3cbe2');
          g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
        }),
        envFace(function (g) {
          g.fillStyle = '#6e6152'; g.fillRect(0, 0, 128, 128);
        }),
        wallFace(false), wallFace(true)]);
      envCube.needsUpdate = true;
      var pmrem = new T.PMREMGenerator(R);
      scene.environment = pmrem.fromCubemap(envCube).texture;
    }

    var NICE = DETAIL >= 2;   // textures + rounded edges from medium up
    var woodLight = NICE ? woodTex('#c89a66', '90,60,30', false) : null;
    var woodDoor = NICE ? woodTex('#a97f52', '80,52,26', true) : null;
    var marble = NICE ? marbleTex() : null;
    var brushed = NICE ? steelTex() : null;

    function mat(c, opts) {
      opts = opts || {};
      if (!PBR) {
        var lm = new T.MeshLambertMaterial({ color: c });
        if (opts.map && DETAIL >= 2) lm.map = opts.map;
        return lm;
      }
      var m = new T.MeshStandardMaterial({
        color: c,
        roughness: opts.rough !== undefined ? opts.rough : 0.86,
        metalness: opts.metal !== undefined ? opts.metal : 0.0
      });
      if (opts.map) m.map = opts.map;
      m.envMapIntensity = opts.envInt !== undefined ? opts.envInt
        : (m.metalness > 0.5 ? 1.0 : 0.1);
      return m;
    }
    var STEEL = { rough: 0.3, metal: 0.85, envInt: 1.1 };
    var CHROME = { rough: 0.12, metal: 1.0, envInt: 1.3 };
    var GLOSS = { rough: 0.3, metal: 0.02, envInt: 0.25 };
    var WOODM = { rough: 0.6, metal: 0.0 };

    function finish(m, noShadow) {
      if (SHADOWS && !noShadow) { m.castShadow = true; m.receiveShadow = true; }
      return m;
    }
    function box(w, h, d, c, x, y, z, group, opts) {
      var m = new T.Mesh(new T.BoxGeometry(w, h, d), mat(c, opts));
      m.position.set(x, y, z); finish(m); (group || scene).add(m); return m;
    }
    function roundedGeo(w, h, d, r) {
      r = Math.min(r, w / 2 - 0.01, h / 2 - 0.01, d / 2 - 0.01);
      var x = -w / 2 + r, y = -h / 2 + r, X = w / 2 - r, Y = h / 2 - r;
      var shape = new T.Shape();
      shape.moveTo(-w / 2, y);
      shape.lineTo(-w / 2, Y);
      shape.absarc(x, Y, r, Math.PI, Math.PI / 2, true);
      shape.lineTo(X, h / 2);
      shape.absarc(X, Y, r, Math.PI / 2, 0, true);
      shape.lineTo(w / 2, y);
      shape.absarc(X, y, r, 0, -Math.PI / 2, true);
      shape.lineTo(x, -h / 2);
      shape.absarc(x, y, r, -Math.PI / 2, Math.PI, true);
      var g = new T.ExtrudeGeometry(shape, {
        depth: d - 2 * r, bevelEnabled: true, bevelThickness: r,
        bevelSize: r, bevelSegments: 2, steps: 1, curveSegments: 5 });
      g.center();
      return g;
    }
    function rbox(w, h, d, r, c, x, y, z, group, opts) {
      if (DETAIL < 2) return box(w, h, d, c, x, y, z, group, opts);
      var m = new T.Mesh(roundedGeo(w, h, d, r), mat(c, opts));
      m.position.set(x, y, z); finish(m); (group || scene).add(m); return m;
    }
    function cyl(rt, rb, h, c, x, y, z, group, seg, opts) {
      var m = new T.Mesh(new T.CylinderGeometry(rt, rb, h, seg || (DETAIL >= 3 ? 18 : 10)),
                         mat(c, opts));
      m.position.set(x, y, z); finish(m); (group || scene).add(m); return m;
    }
    function knob(x, y, z, group) {
      if (DETAIL < 2) return null;
      return cyl(0.035, 0.035, 0.05, C.steel, x, y, z, group, 8, CHROME);
    }
    function blobShadow(rx, rz, x, z, group) {
      if (SHADOWS) return null;          // the high tier has the real thing
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
    floorCanvas.width = floorCanvas.height = DETAIL >= 3 ? 1024 : 512;
    (function () {
      var g = floorCanvas.getContext('2d'), n = 8, t = floorCanvas.width / n;
      for (var i = 0; i < n; i++) for (var j = 0; j < n; j++) {
        g.fillStyle = ((i + j) % 2) ? C.floorB : C.floorA;
        g.fillRect(i * t, j * t, t, t);
        if (DETAIL >= 3) {               // faint grout so tiles read as tiles
          g.strokeStyle = 'rgba(90,80,70,0.3)';
          g.lineWidth = 2;
          g.strokeRect(i * t + 1, j * t + 1, t - 2, t - 2);
        }
      }
    })();
    var floorTex = new T.CanvasTexture(floorCanvas);
    floorTex.magFilter = DETAIL >= 3 ? T.LinearFilter : T.NearestFilter;
    var floor = new T.Mesh(new T.PlaneGeometry(13, 11),
      PBR ? new T.MeshStandardMaterial({ map: floorTex, roughness: 0.5,
                                         envMapIntensity: 0.1 })
          : new T.MeshLambertMaterial({ map: floorTex }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = 0.001;
    if (SHADOWS) floor.receiveShadow = true;
    scene.add(floor);

    var wallB = box(13, 5.6, 0.35, C.wall, 0, 2.8, -5.55, null, { rough: 0.95 });
    var wallL = box(0.35, 5.6, 11, C.wall, -6.65, 2.8, 0, null, { rough: 0.95 });
    if (SHADOWS) { wallB.castShadow = false; wallL.castShadow = false; }
    box(13.6, 0.28, 0.5, C.shell, 0, 5.66, -5.6);
    box(0.5, 0.28, 11.6, C.shell, -6.7, 5.66, 0);
    if (DETAIL >= 3) {                   /* baseboards: the trim that sells a wall */
      box(13, 0.2, 0.08, 0xe4ddd1, 0, 0.1, -5.34);
      box(0.08, 0.2, 11, 0xe4ddd1, -6.44, 0.1, 0);
    }

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
    var bs = new T.Mesh(new T.PlaneGeometry(6.9, 1.0),
      PBR ? new T.MeshStandardMaterial({ map: new T.CanvasTexture(bsCanvas), roughness: 0.35,
                                         envMapIntensity: 0.15 })
          : new T.MeshLambertMaterial({ map: new T.CanvasTexture(bsCanvas) }));
    bs.position.set(-1.05, 1.62, -5.36);
    scene.add(bs);

    var groups = {};
    function zoneGroup(key, x, y, z) {
      var g = new T.Group();
      g.position.set(x, y, z);
      g.userData.zone = key;
      groups[key] = g; scene.add(g); return g;
    }

    /* ---- cabinet run along the back wall — fridge owns the corner ------ */
    function lowerCab(w, x, z) {
      rbox(w, 1.0, 1.4, 0.05, C.cab, x, 0.56, z);
      var n = Math.max(1, Math.round(w / 0.95));
      for (var i = 0; i < n; i++) {
        var dw = w / n - 0.1, dx = x - w / 2 + (i + 0.5) * (w / n);
        if (DETAIL >= 2) box(dw, 0.78, 0.05, C.cabShade, dx, 0.56, z + 0.71);
        knob(dx + dw / 2 - 0.09, 0.72, z + 0.76);
      }
    }
    function upperCab(w, x, z) {
      rbox(w, 1.25, 0.72, 0.05, C.cab, x, 3.75, z);
      var n = Math.max(1, Math.round(w / 0.9));
      for (var i = 0; i < n; i++) {
        var dw = w / n - 0.08, dx = x - w / 2 + (i + 0.5) * (w / n);
        if (DETAIL >= 2) box(dw, 1.05, 0.05, C.cabShade, dx, 3.75, z + 0.37);
        knob(dx + dw / 2 - 0.08, 3.45, z + 0.42);
      }
    }
    /* run sits to the RIGHT of the fridge: no clipping, one clean line */
    lowerCab(5.2, -1.8, -4.6);
    rbox(5.4, 0.12, 1.56, 0.04, 0xffffff, -1.8, 1.12, -4.6, null,
         { rough: 0.3, map: woodLight, envInt: 0.4 });   // butcher top
    upperCab(1.4, -3.9, -5.1);
    upperCab(2.0, 0.3, -5.1);

    /* a sink you can SEE: farmhouse apron front proud of the cabinets,
       steel rim above the counter, dark opening, tall gooseneck */
    rbox(1.2, 0.72, 0.16, 0.03, 0xcfd4d9, -2.6, 0.82, -3.84, null, STEEL); // apron
    box(1.24, 0.07, 0.9, 0xc6cbd0, -2.6, 1.215, -4.42, null, STEEL);       // rim
    box(1.06, 0.05, 0.72, 0x4c5157, -2.6, 1.24, -4.42, null,
        { rough: 0.35, metal: 0.6 });                                      // opening
    cyl(0.05, 0.06, 0.62, C.steel, -2.6, 1.55, -4.95, null, 12, CHROME);   // riser
    var neck = cyl(0.04, 0.04, 0.55, C.steel, -2.6, 1.85, -4.72, null, 10, CHROME);
    neck.rotation.x = 1.25;
    var spout = cyl(0.035, 0.035, 0.22, C.steel, -2.6, 1.74, -4.5, null, 8, CHROME);
    cyl(0.05, 0.02, 0.04, C.steel, -2.6, 1.62, -4.5, null, 8, CHROME);     // aerator
    cyl(0.03, 0.03, 0.14, C.steel, -2.25, 1.28, -4.9, null, 8, CHROME);    // handle

    /* WINDOW (zone: window): the weather lives outside the glass. The
       pane is a canvas the painter redraws when the sky changes; unlit
       material so it always reads as daylight coming IN. */
    var winG = zoneGroup('window', -2.2, 0, -5.4);
    var paneMesh = new T.Mesh(new T.BoxGeometry(1.9, 1.7, 0.06),
      new T.MeshBasicMaterial({ color: 0xffffff }));
    paneMesh.position.set(0, 3.4, 0.06);
    if (SHADOWS) paneMesh.castShadow = false;
    winG.add(paneMesh);
    box(2.1, 0.12, 0.16, C.cab, 0, 4.32, 0.1, winG);
    box(2.1, 0.1, 0.16, C.cab, 0, 2.52, 0.1, winG);
    box(0.12, 1.9, 0.16, C.cab, -1.02, 3.38, 0.1, winG);
    box(0.12, 1.9, 0.16, C.cab, 1.02, 3.38, 0.1, winG);
    rbox(2.14, 0.22, 0.14, 0.04, C.orange, 0, 4.14, 0.2, winG, { rough: 0.9 });
    rbox(2.1, 0.2, 0.12, 0.04, 0xd28f36, 0, 3.95, 0.19, winG, { rough: 0.9 });
    rbox(2.06, 0.18, 0.1, 0.04, C.orange, 0, 3.78, 0.18, winG, { rough: 0.9 });

    /* counter props */
    if (DETAIL >= 2) {
      cyl(0.07, 0.07, 0.4, C.red, -3.5, 1.38, -4.7, null, 8, GLOSS);
      cyl(0.07, 0.07, 0.34, 0x6a4a2f, -3.3, 1.35, -4.85, null, 8, GLOSS);
      cyl(0.12, 0.12, 0.2, 0xead9b8, -0.15, 1.28, -4.75, null, 10);
      box(0.4, 0.14, 0.4, 0xdad2c2, -0.55, 1.25, -4.8, null, GLOSS);
    }
    if (DETAIL >= 3) {
      rbox(0.7, 0.05, 0.45, 0.02, 0xb98c58, -0.95, 1.21, -4.5, null,
           { rough: 0.7, map: woodLight });
      cyl(0.1, 0.14, 0.28, C.bread, -0.95, 1.36, -4.5, null, 10);
      cyl(0.16, 0.2, 0.26, C.steel, -1.5, 1.32, -4.75, null, 14, CHROME); // kettle
      cyl(0.03, 0.03, 0.16, C.steel, -1.35, 1.48, -4.75, null, 8, CHROME);
      rbox(0.42, 0.3, 0.24, 0.05, C.steel, -3.95, 1.34, -4.6, null, STEEL); // toaster
    }

    /* ---- STOVE (zone: counter) with hood ------------------------------- */
    var counter = zoneGroup('counter', 1.7, 0, -4.55);
    rbox(1.5, 1.02, 1.45, 0.05, 0x3f444a, 0, 0.57, 0, counter, { rough: 0.45, metal: 0.5 });
    box(1.3, 0.62, 0.06, 0x556069, 0, 0.5, 0.74, counter, STEEL);
    if (DETAIL >= 3) box(0.9, 0.34, 0.02, 0x1c2024, 0, 0.5, 0.78, counter, GLOSS);
    box(1.1, 0.06, 0.09, C.steel, 0, 0.86, 0.78, counter, CHROME);
    box(1.5, 0.05, 1.45, 0x2e3237, 0, 1.11, 0, counter, { rough: 0.35, metal: 0.4 });
    cyl(0.16, 0.16, 0.03, 0x14161a, -0.4, 1.15, 0.3, counter, 12);
    cyl(0.16, 0.16, 0.03, 0x14161a, 0.4, 1.15, 0.3, counter, 12);
    cyl(0.16, 0.16, 0.03, 0x14161a, -0.4, 1.15, -0.35, counter, 12);
    cyl(0.16, 0.16, 0.03, 0x14161a, 0.4, 1.15, -0.35, counter, 12);
    cyl(0.3, 0.3, 0.3, 0x9aa2a9, -0.4, 1.32, 0.3, counter, 16, STEEL);
    cyl(0.31, 0.31, 0.05, 0x7d858c, -0.4, 1.5, 0.3, counter, 16, STEEL);
    cyl(0.26, 0.26, 0.22, C.red, 0.4, 1.28, -0.35, counter, 16, GLOSS);
    var steam = box(0.16, 0.5, 0.16, 0xf2ead6, -0.4, 2.0, 0.3, counter);
    steam.material.transparent = true; steam.material.opacity = 0;
    if (SHADOWS) steam.castShadow = false;
    var steam2 = box(0.1, 0.34, 0.1, 0xf2ead6, -0.32, 2.35, 0.34, counter);
    steam2.material.transparent = true; steam2.material.opacity = 0;
    if (SHADOWS) steam2.castShadow = false;
    rbox(1.7, 0.5, 1.0, 0.06, C.wall, 0, 3.05, -0.2, counter);
    rbox(1.1, 1.8, 0.8, 0.06, C.wall, 0, 4.2, -0.35, counter);
    blobShadow(1.0, 0.85, 1.7, -4.35);

    /* ---- FRIDGE (zone: fridge) — brushed steel, teal panels, magnets --- */
    var fridge = zoneGroup('fridge', -5.55, 0, -4.35);
    var fbody = new T.Mesh(
      NICE ? roundedGeo(1.9, 3.95, 1.5, 0.08) : new T.BoxGeometry(1.9, 3.95, 1.5),
      PBR ? new T.MeshStandardMaterial({ map: brushed, color: 0xdadee2,
                                         roughness: 0.3, metalness: 0.8,
                                         envMapIntensity: 1.1 })
          : new T.MeshLambertMaterial({ color: 0xd7dbdf, map: brushed || null }));
    fbody.position.set(0, 1.97, 0);
    finish(fbody); fridge.add(fbody);
    rbox(1.6, 1.55, 0.07, 0.03, C.teal, 0, 2.95, 0.77, fridge,
         { rough: 0.3, metal: 0.05, envInt: 0.15 });
    rbox(1.6, 1.35, 0.07, 0.03, C.teal, 0, 1.02, 0.77, fridge,
         { rough: 0.3, metal: 0.05, envInt: 0.15 });
    box(0.07, 1.3, 0.09, C.steel, 0.62, 2.95, 0.82, fridge, CHROME);
    box(0.07, 1.0, 0.09, C.steel, 0.62, 1.07, 0.82, fridge, CHROME);
    var magnets = new T.Group();
    magnets.position.set(0, 0, 0.85);
    fridge.add(magnets);
    blobShadow(1.15, 0.9, -5.55, -4.35);

    /* ---- CORKBOARD (zone: board) on the left wall ---------------------- */
    var board = zoneGroup('board', -6.42, 0, -0.6);
    var boardFace = new T.Mesh(new T.PlaneGeometry(2.0, 1.5),
      mat(C.cork, { rough: 0.98 }));
    boardFace.rotation.y = Math.PI / 2;
    boardFace.position.set(0.06, 2.5, 0);
    board.add(boardFace);
    var bframe = new T.Mesh(new T.BoxGeometry(0.06, 1.66, 2.16),
      PBR ? new T.MeshStandardMaterial({ map: woodDoor, roughness: 0.7 })
          : new T.MeshLambertMaterial({ color: 0xb08a5c, map: woodDoor || null }));
    bframe.position.set(-0.02, 2.5, 0);
    finish(bframe); board.add(bframe);

    /* ---- WALL CALENDAR (zone: calendar) on the back wall --------------- */
    var calG = zoneGroup('calendar', 3.6, 0, -5.36);
    var calFace = new T.Mesh(new T.PlaneGeometry(1.5, 1.9), mat(0xf6f1e4, { rough: 0.9 }));
    calFace.position.set(0, 3.0, 0.05);
    calG.add(calFace);
    box(1.62, 0.1, 0.08, C.red, 0, 4.0, 0.02, calG, GLOSS);
    if (DETAIL >= 3) {                  /* wall clock between calendar and door */
      var clockFace = cyl(0.3, 0.3, 0.06, 0xffffff, 4.45, 4.75, -5.34, null, 20, GLOSS);
      clockFace.rotation.x = Math.PI / 2;
      box(0.03, 0.18, 0.02, C.dark, 4.45, 4.8, -5.28);
      box(0.13, 0.03, 0.02, C.dark, 4.5, 4.75, -5.28);
    }

    /* ---- DOOR (zone: door) on the back wall right ---------------------- */
    var doorG = zoneGroup('door', 5.35, 0, -5.32);
    var slabD = new T.Mesh(
      NICE ? roundedGeo(1.7, 4.1, 0.14, 0.04) : new T.BoxGeometry(1.7, 4.1, 0.14),
      PBR ? new T.MeshStandardMaterial({ map: woodDoor, roughness: 0.65 })
          : new T.MeshLambertMaterial({ color: 0xc9a06c, map: woodDoor || null }));
    slabD.position.set(0, 2.05, 0);
    finish(slabD); doorG.add(slabD);
    if (DETAIL >= 2) {
      box(1.3, 1.2, 0.05, 0x8a6d49, 0, 1.2, 0.08, doorG, PBR ? { rough: 0.7, map: woodDoor } : { rough: 0.75 });
    }
    cyl(0.07, 0.07, 0.1, 0xd8c48a, 0.6, 2.0, 0.1, doorG, 10, CHROME);
    /* the next-leave HERO CARD, rendered app-style, big enough to read
       from across the room — it hangs on the door because the door is
       where leaving happens */
    var plaque = new T.Mesh(new T.PlaneGeometry(1.5, 0.94),
      new T.MeshBasicMaterial({ transparent: true }));
    plaque.position.set(0, 3.02, 0.1);
    doorG.add(plaque);

    /* ---- RADIO (zone: radio) on the countertop ------------------------- */
    var radio = zoneGroup('radio', 0.45, 0, -4.62);
    rbox(0.8, 0.45, 0.4, 0.06, C.red, 0, 1.41, 0, radio, GLOSS);
    box(0.55, 0.28, 0.03, 0xf2e3b8, -0.06, 1.42, 0.21, radio, { rough: 0.95 });
    cyl(0.035, 0.035, 0.1, C.steel, 0.28, 1.68, 0, radio, 8, CHROME);
    var needle = box(0.04, 0.22, 0.04, 0x3a332a, 0.28, 1.78, 0, radio);

    /* ---- ISLAND (decor) with a marble top + stools ---------------------- */
    rbox(3.4, 1.0, 2.0, 0.06, C.cab, -0.4, 0.56, 0.9);
    if (DETAIL >= 2) {
      box(3.2, 0.66, 0.05, C.cabShade, -0.4, 0.5, 1.92);
      knob(-1.1, 0.62, 1.97); knob(0.3, 0.62, 1.97);
    }
    var islandTop = new T.Mesh(
      NICE ? roundedGeo(3.7, 0.14, 2.3, 0.05) : new T.BoxGeometry(3.7, 0.14, 2.3),
      PBR ? new T.MeshStandardMaterial({ map: marble, roughness: 0.2,
                                         envMapIntensity: 0.3 })
          : new T.MeshLambertMaterial({ color: 0xffffff, map: marble || null }));
    islandTop.position.set(-0.4, 1.13, 0.9);
    finish(islandTop); scene.add(islandTop);
    if (DETAIL >= 2) {
      rbox(1.1, 0.06, 0.75, 0.02, C.red, -1.2, 1.23, 0.7, null, GLOSS);
      for (var cx = 0; cx < 4; cx++) for (var cz = 0; cz < 2; cz++) {
        cyl(0.09, 0.07, 0.1, 0xf5e6d0, -1.55 + cx * 0.24, 1.31, 0.55 + cz * 0.3, null, 10);
        cyl(0.07, 0.09, 0.08, (cx + cz) % 2 ? C.teal : C.red,
            -1.55 + cx * 0.24, 1.4, 0.55 + cz * 0.3, null, 10, GLOSS);
      }
      cyl(0.34, 0.26, 0.16, 0xead9b8, 0.7, 1.3, 0.9, null, 14);
      cyl(0.09, 0.09, 0.1, C.orange, 0.58, 1.42, 0.85, null, 10, GLOSS);
      cyl(0.09, 0.09, 0.1, C.red, 0.82, 1.42, 0.95, null, 10, GLOSS);
    }
    if (DETAIL >= 3) {
      cyl(0.16, 0.12, 0.2, 0xc9704f, 0.15, 1.3, 1.5, null, 12);
      cyl(0.02, 0.02, 0.3, 0x4e6e3e, 0.15, 1.5, 1.5, null, 6);
      cyl(0.14, 0.02, 0.2, C.leaf, 0.15, 1.66, 1.5, null, 8);
      cyl(0.1, 0.02, 0.16, C.leaf, 0.06, 1.6, 1.44, null, 8);
    }
    blobShadow(2.1, 1.4, -0.4, 0.9);
    function stool(x, z) {
      var seat = new T.Mesh(new T.CylinderGeometry(0.3, 0.26, 0.08, 14),
        PBR ? new T.MeshStandardMaterial({ map: woodLight, roughness: 0.6 })
            : new T.MeshLambertMaterial({ color: 0xc89a66, map: woodLight || null }));
      seat.position.set(x, 0.86, z); finish(seat); scene.add(seat);
      cyl(0.05, 0.07, 0.84, C.wood2, x, 0.42, z, null, 10, WOODM);
      blobShadow(0.34, 0.3, x, z);
    }
    stool(1.9, 0.5); stool(1.9, 1.5);

    /* pendant lamps over the island: warm emissive shades */
    if (DETAIL >= 3) {
      [-1.1, 0.4].forEach(function (px) {
        var cord = cyl(0.008, 0.008, 1.4, 0x8a8178, px, 4.9, 0.9, null, 6);
        cord.castShadow = false;   // a hair-thin cord throws a room-long streak
        var shade = new T.Mesh(new T.CylinderGeometry(0.3, 0.42, 0.34, 18, 1, true),
          new T.MeshStandardMaterial({ color: 0xf0e3c8, roughness: 0.7,
                                       emissive: 0xffdf9e, emissiveIntensity: 0.55,
                                       side: T.DoubleSide }));
        shade.position.set(px, 4.05, 0.9);
        shade.castShadow = false;
        scene.add(shade);
      });
    }

    /* ---- CRITTER LAPTOP (zone: pet): the game lives on a screen -------
       Critters are a rudimentary Pokemon, not a care loop — and not the
       family's real pets, so no bowl pretending otherwise. A laptop sits
       on the island the way a kid leaves one, its screen carrying the
       roster. */
    var crit = zoneGroup('pet', -1.55, 0, 1.45);
    rbox(0.66, 0.035, 0.46, 0.012, 0x2a2d34, 0, 1.225, 0.02, crit,
         { rough: 0.35, metal: 0.4, envInt: 0.6 });
    var lid = rbox(0.66, 0.44, 0.028, 0.012, 0x2a2d34, 0, 1.44, -0.24, crit,
                   { rough: 0.35, metal: 0.4, envInt: 0.6 });
    lid.rotation.x = -0.30;
    lid.position.y = 1.43; lid.position.z = -0.175;
    var critFace = new T.Mesh(new T.PlaneGeometry(0.60, 0.38),
                              mat(0x12151c, { rough: 0.6 }));
    critFace.rotation.x = -0.30;
    critFace.position.set(0, 1.4245, -0.157);
    crit.add(critFace); finish(critFace);
    blobShadow(0.42, 0.30, -1.55, 1.45);

    /* ---- the painters: every data surface drawn like the app draws it —
       Inter type, white cards, accent bars, soft shadows. Cached per
       payload; a poll that changes nothing repaints nothing. ---- */
    var texCache = {};
    var FONT = 'Inter, system-ui, sans-serif';
    function mkTex(key, w, h, payload, draw) {
      var e = texCache[key];
      if (e && e.payload === payload) return e.tex;
      var c = document.createElement('canvas'); c.width = w; c.height = h;
      draw(c.getContext('2d'), w, h);
      var t = new T.CanvasTexture(c);
      t.anisotropy = 4;
      texCache[key] = { payload: payload, tex: t };
      return t;
    }
    function rr(g, x, y, w, h, r) {
      g.beginPath();
      g.moveTo(x + r, y);
      g.arcTo(x + w, y, x + w, y + h, r);
      g.arcTo(x + w, y + h, x, y + h, r);
      g.arcTo(x, y + h, x, y, r);
      g.arcTo(x, y, x + w, y, r);
      g.closePath();
    }
    function card(g, x, y, w, h, accent) {
      g.save();
      g.shadowColor = 'rgba(45,32,18,0.28)';
      g.shadowBlur = 14; g.shadowOffsetY = 5;
      g.fillStyle = '#ffffff';
      rr(g, x, y, w, h, 16); g.fill();
      g.restore();
      g.fillStyle = accent;
      rr(g, x, y, 12, h, 6); g.fill();
    }
    var ACCENTS = ['#2563eb', '#7c3aed', '#0d9488', '#dc2626', '#d97706'];

    function heroTex(d) {
      var calm = !d || d.calm !== false || d.mins === null || d.mins === undefined;
      var lbl = (d && d.label) || '';
      var time = lbl.slice(0, 5), title = lbl.indexOf(' \u2014 ') !== -1
        ? lbl.slice(lbl.indexOf(' \u2014 ') + 3) : lbl.slice(5);
      var payload = calm ? 'calm' : [time, title, d.mins].join('|');
      return mkTex('hero', 512, 320, payload, function (g, w, h) {
        g.clearRect(0, 0, w, h);
        card(g, 14, 14, w - 28, h - 28, calm ? '#0d9488' : '#2563eb');
        if (calm) {
          g.fillStyle = '#111827'; g.font = '800 44px ' + FONT;
          g.fillText('All home', 48, 140);
          g.fillStyle = '#6b7280'; g.font = '500 30px ' + FONT;
          g.fillText('nobody has to leave', 48, 195);
          return;
        }
        g.fillStyle = '#111827'; g.font = '800 88px ' + FONT;
        g.fillText(time, 44, 128);
        g.fillStyle = '#374151'; g.font = '600 36px ' + FONT;
        g.fillText(String(title).slice(0, 22), 46, 190);
        g.fillStyle = '#2563eb'; g.font = '700 32px ' + FONT;
        g.fillText('leave in ' + d.mins + ' min', 46, 258);
      });
    }
    function critterTex(p) {
      var calm = !p || p.calm !== false;
      var pets = (p && p.pets) || [];
      var payload = calm ? 'calm'
        : pets.map(function (x) { return x.name + ':' + x.level; }).join('|');
      return mkTex('critters', 512, 324, payload, function (g, w, h) {
        g.fillStyle = '#12151c'; g.fillRect(0, 0, w, h);
        g.fillStyle = '#1d2230'; g.fillRect(0, 0, w, 64);
        g.fillStyle = '#7ee787'; g.font = '800 34px ' + FONT;
        g.fillText('CRITTERS', 26, 44);
        if (calm) {
          g.fillStyle = '#4a5265'; g.font = '500 30px ' + FONT;
          g.fillText('everyone is resting…', 26, 140);
          return;
        }
        var CC = ['#f87171', '#60a5fa', '#fbbf24', '#34d399'];
        pets.slice(0, 3).forEach(function (x, i) {
          var y = 108 + i * 74;
          g.fillStyle = CC[i % 4];
          g.beginPath(); g.arc(48, y, 22, 0, Math.PI * 2); g.fill();
          g.fillStyle = '#0d1017';
          g.beginPath(); g.arc(41, y - 5, 4, 0, Math.PI * 2); g.fill();
          g.beginPath(); g.arc(55, y - 5, 4, 0, Math.PI * 2); g.fill();
          g.fillStyle = '#e6e9f2'; g.font = '700 32px ' + FONT;
          g.fillText(String(x.name || 'Critter').slice(0, 12), 88, y + 10);
          g.fillStyle = '#8b93a8'; g.font = '600 26px ' + FONT;
          g.fillText('Lv ' + (x.level || 1), w - 110, y + 10);
        });
      });
    }

    function calendarTex(c) {
      if (c && c.__blank) {
        /* focused: the board's own card is ON this sheet — bare paper
           underneath, so the room never says the same thing twice */
        return mkTex('calendar', 512, 640, 'blank', function (g, w, h) {
          g.fillStyle = '#f6f1e4'; g.fillRect(0, 0, w, h);
          g.fillStyle = '#111827'; g.font = '800 40px ' + FONT;
          g.fillText('Today', 30, 66);
        });
      }
      var calm = !c || c.calm !== false;
      var next = (c && c.next) || [];
      var payload = calm ? 'calm' : [c.today].concat(next).join('|');
      return mkTex('calendar', 512, 640, payload, function (g, w, h) {
        g.fillStyle = '#f6f1e4'; g.fillRect(0, 0, w, h);
        g.fillStyle = '#111827'; g.font = '800 40px ' + FONT;
        g.fillText('Today', 30, 66);
        if (!calm) {
          g.fillStyle = '#2563eb'; rr(g, w - 96, 26, 62, 52, 14); g.fill();
          g.fillStyle = '#ffffff'; g.font = '800 34px ' + FONT;
          g.fillText(String(c.today), w - 96 + (String(c.today).length > 1 ? 12 : 22), 64);
        }
        if (calm) {
          g.fillStyle = '#6b7280'; g.font = '500 30px ' + FONT;
          g.fillText('nothing left today', 30, 140);
          return;
        }
        var y = 110;
        next.slice(0, 4).forEach(function (line, i) {
          card(g, 24, y, w - 48, 108, ACCENTS[i % ACCENTS.length]);
          g.fillStyle = '#111827'; g.font = '800 34px ' + FONT;
          g.fillText(String(line).slice(0, 5), 56, y + 48);
          g.fillStyle = '#374151'; g.font = '500 29px ' + FONT;
          g.fillText(String(line).slice(6, 26), 56, y + 90);
          y += 128;
        });
      });
    }
    function boardTex(b) {
      var calm = !b || b.calm !== false;
      var top = (b && b.top) || [];
      var payload = calm ? 'calm' : [b.items].concat(top).join('|');
      return mkTex('board', 512, 384, payload, function (g, w, h) {
        g.fillStyle = '#c08b52'; g.fillRect(0, 0, w, h);
        for (var i = 0; i < 500; i++) {
          g.fillStyle = 'rgba(90,60,30,' + (Math.random() * 0.1) + ')';
          g.fillRect(Math.random() * w, Math.random() * h, 2, 2);
        }
        var notes = calm ? ['all set!'] : top.slice(0, 6);
        var colors = ['#fef08a', '#fda4af', '#a7f3d0', '#bae6fd', '#fde68a', '#ddd6fe'];
        notes.forEach(function (item, i) {
          var nx = 34 + (i % 3) * 155, ny = 40 + Math.floor(i / 3) * 165;
          g.save();
          g.translate(nx + 62, ny + 62);
          g.rotate(((i * 47) % 9 - 4) * 0.02);
          g.shadowColor = 'rgba(60,40,20,0.35)'; g.shadowBlur = 8; g.shadowOffsetY = 4;
          g.fillStyle = colors[i % colors.length];
          g.fillRect(-62, -62, 124, 124);
          g.restore();
          g.fillStyle = '#b91c1c';
          g.beginPath(); g.arc(nx + 62, ny + 10, 6, 0, 7); g.fill();
          g.fillStyle = '#374151'; g.font = '600 24px ' + FONT;
          var word = String(item).slice(0, 9);
          g.fillText(word, nx + 62 - g.measureText(word).width / 2, ny + 70);
        });
      });
    }
    function weatherTex(wz) {
      var cond = (wz && wz.cond) || '';
      var temp = (wz && wz.temp !== null && wz.temp !== undefined) ? Math.round(wz.temp) : null;
      var hour = new Date().getHours();
      var night = hour < 7 || hour >= 19;
      var payload = [cond, temp, night].join('|');
      return mkTex('weather', 320, 288, payload, function (g, w, h) {
        var top = '#7cc4f0', bot = '#d8ecf7';
        if (night) { top = '#1c2748'; bot = '#33406b'; }
        else if (cond.indexOf('rain') !== -1 || cond === 'pouring' || cond.indexOf('lightning') !== -1) { top = '#5b6c7d'; bot = '#8fa0af'; }
        else if (cond.indexOf('snow') !== -1) { top = '#aebfd0'; bot = '#e8eef4'; }
        else if (cond.indexOf('cloud') !== -1 || cond === 'fog') { top = '#8fb0c6'; bot = '#cfdde8'; }
        var grad = g.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, top); grad.addColorStop(1, bot);
        g.fillStyle = grad; g.fillRect(0, 0, w, h);
        if (night) {
          g.fillStyle = '#f5f0dc';
          g.beginPath(); g.arc(w * 0.72, h * 0.28, 26, 0, 7); g.fill();
          g.fillStyle = top;
          g.beginPath(); g.arc(w * 0.68, h * 0.25, 22, 0, 7); g.fill();
          g.fillStyle = 'rgba(255,255,255,0.8)';
          for (var st = 0; st < 14; st++) {
            g.fillRect(((st * 73) % w), ((st * 41) % (h * 0.5)), 2, 2);
          }
        } else if (cond === 'sunny' || cond === 'clear' || cond === '' || cond === 'partlycloudy') {
          g.fillStyle = '#ffd968';
          g.beginPath(); g.arc(w * 0.7, h * 0.26, 30, 0, 7); g.fill();
          g.fillStyle = 'rgba(255,217,104,0.35)';
          g.beginPath(); g.arc(w * 0.7, h * 0.26, 44, 0, 7); g.fill();
        }
        if (cond.indexOf('cloud') !== -1 || cond.indexOf('rain') !== -1 ||
            cond.indexOf('snow') !== -1 || cond === 'pouring' || cond === 'fog') {
          g.fillStyle = night ? 'rgba(200,205,220,0.55)' : 'rgba(255,255,255,0.9)';
          [[0.3, 0.3], [0.62, 0.42]].forEach(function (pos) {
            var cxp = w * pos[0], cyp = h * pos[1];
            g.beginPath();
            g.arc(cxp - 26, cyp, 18, 0, 7); g.arc(cxp, cyp - 12, 24, 0, 7);
            g.arc(cxp + 26, cyp, 18, 0, 7);
            g.fill(); g.fillRect(cxp - 26, cyp - 2, 52, 20);
          });
        }
        if (cond.indexOf('rain') !== -1 || cond === 'pouring' || cond.indexOf('lightning') !== -1) {
          g.strokeStyle = 'rgba(225,240,255,0.75)'; g.lineWidth = 3;
          for (var rn = 0; rn < 16; rn++) {
            var rx = ((rn * 61) % w), ry = h * 0.5 + ((rn * 37) % (h * 0.3));
            g.beginPath(); g.moveTo(rx, ry); g.lineTo(rx - 6, ry + 18); g.stroke();
          }
        }
        if (cond.indexOf('snow') !== -1) {
          g.fillStyle = 'rgba(255,255,255,0.95)';
          for (var sn = 0; sn < 18; sn++) {
            g.beginPath();
            g.arc(((sn * 53) % w), h * 0.45 + ((sn * 29) % (h * 0.4)), 3.5, 0, 7);
            g.fill();
          }
        }
        /* the hills the house looks out on */
        g.fillStyle = night ? '#22321f' : '#4e6e50';
        g.beginPath(); g.moveTo(0, h);
        g.lineTo(0, h * 0.82);
        g.quadraticCurveTo(w * 0.25, h * 0.68, w * 0.5, h * 0.82);
        g.quadraticCurveTo(w * 0.75, h * 0.94, w, h * 0.8);
        g.lineTo(w, h); g.closePath(); g.fill();
        if (temp !== null) {
          g.save();
          g.shadowColor = 'rgba(0,0,0,0.4)'; g.shadowBlur = 8;
          g.fillStyle = '#ffffff'; g.font = '800 54px ' + FONT;
          g.fillText(temp + '\u00b0', 18, h - 20);
          g.restore();
        }
      });
    }
    function clearPaint() { texCache = {}; }

    return {
      T: T, scene: scene, cam: cam, R: R, groups: groups,
      steam: steam, steam2: steam2, needle: needle, plaque: plaque,
      calFace: calFace, boardFace: boardFace, magnets: magnets,
      critFace: critFace, critterTex: critterTex,
      paneMesh: paneMesh, heroTex: heroTex, calendarTex: calendarTex,
      boardTex: boardTex, weatherTex: weatherTex, clearPaint: clearPaint,
      HOME_POS: HOME_POS, HOME_AT: HOME_AT
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
        webgl.steam.position.y = 2.0 + 0.08 * Math.sin(t * 1.3);
        webgl.steam2.material.opacity = 0.22 + 0.16 * Math.sin(t * 1.7 + 1.2);
        webgl.steam2.position.y = 2.35 + 0.1 * Math.sin(t * 1.1 + 0.6);
      } else {
        webgl.steam.material.opacity = 0;
        webgl.steam2.material.opacity = 0;
      }
      if (state.radio && state.radio.playing) {
        webgl.needle.rotation.z = 0.25 * Math.sin(t * 3.0);
      }
      keep = true;
    } else if (webgl.steam) {
      webgl.steam.material.opacity = 0;
      webgl.steam2.material.opacity = 0;
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
    if (focused && !tween) announceFocus(focused);
    requestFrame();
  }

  /* ---- boot benchmark: settle into the tier the hardware affords ------- */
  /* Runs once per tab session, right after the first real frame. If a burst
   * of frames averages slower than the budget, the next tier down is
   * persisted and the page reloads into it — the same one-way ratchet a
   * game's autodetect uses. `?quality=` always wins because it persists. */
  function benchmark() {
    if (!webgl || FORCED) return;
    try {
      if (sessionStorage.getItem('chf_kitchen_benched')) return;
      sessionStorage.setItem('chf_kitchen_benched', '1');
    } catch (e) { return; }
    /* the first frames of any WebGL page pay shader compilation and
       texture upload — measuring them demotes every device on earth. Warm
       up unmeasured, then judge the MEDIAN of a steady burst. */
    var WARM = 8, N = 12, n = 0, times = [], last = 0;
    function tick() {
      var t0 = performance.now();
      webgl.R.render(webgl.scene, webgl.cam);
      var dt = performance.now() - t0;
      n++;
      if (n > WARM) times.push(dt);
      if (times.length < N) { requestAnimationFrame(tick); return; }
      times.sort(function (a, b) { return a - b; });
      var med = times[Math.floor(times.length / 2)];
      var i = TIERS.indexOf(QUALITY);
      if (med > 40 && i >= 0 && i < TIERS.length - 2) {   // never auto-drop into 2d
        try { localStorage.setItem(QUALITY_KEY, TIERS[i + 1]); } catch (e) { return; }
        window.location.reload();
      }
    }
    requestAnimationFrame(tick);
  }

  /* ---- applyState: the sole data path ---------------------------------- */
  function applyState(s) {
    state = s;
    if (!webgl) { drawFallback(s); return; }

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

    /* honest detail faces, repainted only when payloads change */
    function swap(mesh, tex) {
      if (mesh.material.map !== tex) {
        mesh.material.map = tex;
        mesh.material.needsUpdate = true;
      }
    }
    /* a focused surface goes quiet: the board's card IS its detail now,
       and the room must not say the same thing twice at two sizes */
    webgl.plaque.visible = focused !== 'door';
    swap(webgl.plaque, webgl.heroTex(s.door || {}));
    swap(webgl.calFace, webgl.calendarTex(
      focused === 'calendar' ? { __blank: true } : (s.calendar || {})));
    swap(webgl.critFace, webgl.critterTex(s.pet || {}));
    swap(webgl.boardFace, webgl.boardTex(s.board || {}));
    swap(webgl.paneMesh, webgl.weatherTex(s.window || {}));

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
    announceFocus(null);
    requestFrame();
  }

  /* Where a zone sits on the SCREEN, so the page layer can lay the board's
     own card over the furniture the camera just framed. The room never
     draws HTML; it only announces (chf-kitchen-focus: zone, bbox rect, and
     the projected QUAD of the prop's camera-facing face — wall furniture
     is a thin box, so that face lies across the box's thinnest axis. The
     quad is what lets the page layer paste a card ON the surface in the
     room's own perspective rather than floating one in front of it). */
  function _project(v3, w, h) {
    var v = v3.clone().project(webgl.cam);
    return { x: (v.x + 1) / 2 * w, y: (1 - v.y) / 2 * h, z: v.z };
  }

  function zoneFaceQuad(key) {
    var g = webgl.groups[key];
    if (!g) return null;
    webgl.cam.updateMatrixWorld();
    webgl.cam.matrixWorldInverse.copy(webgl.cam.matrixWorld).invert();
    var b = new webgl.T.Box3().setFromObject(g);
    var w = ROOT.clientWidth || 1, h = ROOT.clientHeight || 1;

    /* bbox rect stays: guards, harnesses, any zone without a clean face */
    var xs = [b.min.x, b.max.x], ys = [b.min.y, b.max.y], zs = [b.min.z, b.max.z];
    var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    for (var i = 0; i < 2; i++) for (var j = 0; j < 2; j++) for (var k = 0; k < 2; k++) {
      var p = _project(new webgl.T.Vector3(xs[i], ys[j], zs[k]), w, h);
      if (p.x < minX) minX = p.x; if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y; if (p.y > maxY) maxY = p.y;
    }
    var rect = { left: minX, top: minY, width: maxX - minX, height: maxY - minY };

    /* the camera-facing face across the box's THINNEST axis */
    var size = b.getSize(new webgl.T.Vector3());
    var c = b.getCenter(new webgl.T.Vector3());
    var axis = (size.x <= size.y && size.x <= size.z) ? 'x'
             : (size.y <= size.z ? 'y' : 'z');
    var toCam = new webgl.T.Vector3().subVectors(webgl.cam.position, c);
    var fixed = toCam[axis] >= 0 ? b.max[axis] : b.min[axis];
    var A = axis === 'x' ? ['y', 'z'] : (axis === 'y' ? ['x', 'z'] : ['x', 'y']);
    var quad = [];
    var bad = false;
    [[b.min[A[0]], b.min[A[1]]], [b.max[A[0]], b.min[A[1]]],
     [b.max[A[0]], b.max[A[1]]], [b.min[A[0]], b.max[A[1]]]].forEach(function (uv) {
      var v3 = new webgl.T.Vector3();
      v3[axis] = fixed; v3[A[0]] = uv[0]; v3[A[1]] = uv[1];
      var p = _project(v3, w, h);
      if (p.z > 1 || p.z < -1) bad = true;
      quad.push(p);
    });
    if (bad) return { rect: rect, quad: null };
    /* order in SCREEN space: the top pair then the bottom pair, left first */
    quad.sort(function (a, b2) { return a.y - b2.y; });
    var top = quad.slice(0, 2).sort(function (a, b2) { return a.x - b2.x; });
    var bot = quad.slice(2, 4).sort(function (a, b2) { return a.x - b2.x; });
    return { rect: rect, quad: [top[0], top[1], bot[1], bot[0]] };
  }

  /* The tap's own lean-in, callable by zone name — the hand path a
     deep-link or a harness needs. Read-only: it moves the camera and
     announces; it never taps through. */
  window.chfKitchenFocus = function (key) {
    if (!webgl || !ZONES[key]) return;
    focused = key;
    announceFocus(null);
    frameZone(key, function () { announceFocus(key); });
  };

  function announceFocus(key) {
    if (webgl && state) applyState(state);   /* blank/restore the faces */
    var shape = (key && webgl) ? zoneFaceQuad(key) : null;
    try {
      window.dispatchEvent(new CustomEvent('chf-kitchen-focus',
        { detail: { zone: shape ? key : null,
                    rect: shape ? shape.rect : null,
                    quad: shape ? shape.quad : null } }));
    } catch (e) { /* an ancient browser without CustomEvent just gets the tip */ }
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
    announceFocus(null);   /* the old card must not ride the camera move */
    frameZone(key, function () {
      announceFocus(key);
      if (state) {
        TIP.textContent = ZONES[key].label + ' — ' + ZONES[key].headline(state);
        TIP.style.left = '16px';
        TIP.style.bottom = '64px';
        TIP.style.top = 'auto';
        TIP.style.opacity = 1;
      }
    });
  }

  /* ---- poll (60s), once-per-outage chip -------------------------------- */
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
      announceFocus(null);
      try { ROOT.style.display = 'none'; } catch (err) {}
      webgl = null;
      drawFallback(state);
    });
    webgl.R.domElement.addEventListener('click', onTap);
    window.addEventListener('resize', size);
    size();
    benchmark();
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(function () {
        if (webgl) { webgl.clearPaint(); if (state) applyState(state); }
      });
    }
  } else {
    drawFallback(null);
  }

  poll();
  setInterval(function () {
    if (document.visibilityState === 'visible') poll();
  }, POLL_MS);
  setTimeout(stampVisit, 10000);   // study idiom: glows survive a quick reload
})();
