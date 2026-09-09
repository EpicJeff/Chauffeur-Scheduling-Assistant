/* The Home — the dollhouse the panel lives in.
 *
 * Spec: docs/superpowers/specs/2026-09-08-house-design.md. Born as a copy
 * of kitchen.js (frozen until H4 deletes it); the kitchen's world
 * coordinates never moved — the house grows AROUND them. The shared
 * localStorage keys (chf_kitchen_last_visit, chf_kitchen_quality2) and the
 * chf-kitchen-focus event are DELIBERATE: one settled quality tier per
 * device, one fridge-glow epoch, one overlay — renamed together at H4.
 * Contracts unchanged (ZONES registry, applyState as the sole data path,
 * focus-then-through, calm-first fallback) plus the wall's disciplines:
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
    board:    { label: 'Pantry',        url: 'lists',
                num: function (s) { return (s.board || {}).items || 0; },
                headline: function (s) {
                  var b = s.board || {};
                  if (b.calm) return 'The pantry is stocked.';
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
    garage:   { label: 'Garage',        url: 'config',
                num: function (s) {
                  return ((s.garage || {}).cars || []).filter(function (c) {
                    return c.warn; }).length;
                },
                headline: function (s) {
                  var g = s.garage || {};
                  var cars = g.cars || [];
                  if (!cars.length) return 'No cars on the record yet.';
                  var warns = cars.filter(function (c) { return c.warn; });
                  if (!warns.length) return 'Every car is settled.';
                  return warns.map(function (c) {
                    var lvl = (c.battery_pct !== null && c.battery_pct !== undefined)
                      ? c.battery_pct : c.fuel_pct;
                    return c.name + (lvl !== null && lvl !== undefined
                      ? ' at ' + Math.round(lvl) + '%' : ' needs a look');
                  }).join(', ');
                } },
    curb:     { label: 'Curb',          url: 'home',
                num: function (s) { return (s.curb || {}).bus ? 1 : 0; },
                headline: function (s) {
                  return (s.curb || {}).bus ? 'The bus is out.'
                                            : 'No bus right now.';
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
  var ZONE_ORDER = ['door', 'window', 'calendar', 'counter', 'fridge', 'board', 'radio', 'pet', 'garage', 'curb'];

  function go(slug) { window.location.href = BASE + slug + window.location.search; }

  /* ---- fallback: the DESIGNED weak-hardware experience ----------------- */
  /* textContent only — captions and dish names are family-typed strings and
   * this page renders on the most shared screen in the house. */
  function drawFallback(state) {
    FALLROWS.textContent = '';
    var h = document.createElement('h1');
    h.textContent = 'The Home';
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
    var cam = new T.PerspectiveCamera(24, 1, 0.1, 200); // narrow FOV = near-isometric diorama; far covers the yard dome
    var HOME_POS = new T.Vector3(17.5, 13.0, 17.5);
    var HOME_AT = new T.Vector3(-0.2, 0.8, -0.4);
    /* the house from the yard: the panel's resting view */
    var EXT_POS = new T.Vector3(40.0, 26.0, 40.0);
    var EXT_AT = new T.Vector3(-4.6, 1.2, 5.0);
    /* the garage from its own doorway (roof + front hidden inside) */
    var GARAGE_POS = new T.Vector3(-13.9, 11.2, 20.4);
    var GARAGE_AT = new T.Vector3(-15.7, 1.7, 5.2);
    var MUD_POS = new T.Vector3(-5.9, 5.2, 12.0);
    var MUD_AT = new T.Vector3(-9.8, 1.5, 2.9);
    /* the living room: far enough back that the whole hearth wall, both
       built-ins and the reading corner sit inside the safe frame, high
       enough that the floor falls away to the lower right (bible S5.1) */
    var LIV_POS = new T.Vector3(5.2, 13.6, 26.5);
    var LIV_AT = new T.Vector3(-2.9, 2.35, 10.3);
    cam.position.copy(EXT_POS);
    cam.lookAt(EXT_AT);

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
              leaf: 0x5f8f4e, bread: 0xcf9a55,
              /* style-bible roles (docs/house_style_bible.md S2). Dark
                 anchors first: every room needs at least one. Then the
                 accent family - a room picks three or four, never more. */
              ink: 0x23272c, slate: 0x39424d, graphite: 0x5b6169,
              sage: 0x9db3a4, sageDeep: 0x7d968a,
              terracotta: 0xb5713c, terraDeep: 0x8f5528,
              brass: 0xc9a54e, oxblood: 0x8f4038, mustard: 0xd1a13c,
              cream: 0xf2ece1, linen: 0xdcd0bb, stone: 0x7c7368,
              rugF: 0xe8dfcb, rugB: 0xc0ae8e, bayBack: 0x7f9280,
              stoneDk: 0x615a51 };

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
      /* one wood floor through the whole great room (user ruling: no
         flooring transitions in a modern house) — board rows with
         offset seams, the checkerboard retired */
      var g = floorCanvas.getContext('2d'), W = floorCanvas.width;
      g.fillStyle = '#c9a06c'; g.fillRect(0, 0, W, W);
      var rows = 9, bh = W / rows;
      for (var r = 0; r < rows; r++) {
        var off = (r % 3) * (W / 3.7);
        g.fillStyle = 'rgba(120,80,40,' + (0.05 + (r % 3) * 0.045) + ')';
        g.fillRect(0, r * bh, W, bh);
        g.strokeStyle = 'rgba(90,60,30,0.5)'; g.lineWidth = 2;
        g.strokeRect(-4, r * bh, W + 8, bh);
        for (var seg = 0; seg < 3; seg++) {
          var sx = (seg * W / 3 + off) % W;
          g.beginPath(); g.moveTo(sx, r * bh); g.lineTo(sx, r * bh + bh);
          g.stroke();
        }
        if (DETAIL >= 3) {
          g.strokeStyle = 'rgba(120,80,40,0.22)'; g.lineWidth = 1;
          for (var gr = 0; gr < 5; gr++) {
            var gy = r * bh + 4 + Math.random() * (bh - 8);
            g.beginPath(); g.moveTo(0, gy);
            g.lineTo(W, gy + (Math.random() - 0.5) * 5); g.stroke();
          }
        }
      }
    })();
    var floorTex = new T.CanvasTexture(floorCanvas);
    floorTex.magFilter = T.LinearFilter;   /* planks, not pixels */
    var floor = new T.Mesh(new T.PlaneGeometry(13, 11.6),
      PBR ? new T.MeshStandardMaterial({ map: floorTex, roughness: 0.5,
                                         envMapIntensity: 0.1 })
          : new T.MeshLambertMaterial({ map: floorTex }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = 0.001;
    if (SHADOWS) floor.receiveShadow = true;
    scene.add(floor);

    var wallB = box(13, 5.6, 0.35, C.wall, 0, 2.8, -5.55, null, { rough: 0.95 });
    /* west wall in two pieces + header: an open doorway into the
       mudroom at z 2.8..4.4 (architect pass — the kitchen looks through
       to the bench) */
    /* every west-wall piece goes in westWallG: the mudroom lives on the
       far side of it, so its camera hides the wall the way the garage
       hides its door — the dollhouse trick, one wall further in. */
    var westWallG = new T.Group();
    scene.add(westWallG);
    var wallL = box(0.35, 5.6, 4.05, C.wall, -6.65, 2.8, -3.475, westWallG,
                    { rough: 0.95 });
    var wallL1a = box(0.35, 5.6, 2.55, C.wall, -6.65, 2.8, 1.525, westWallG,
                      { rough: 0.95 });
    box(0.35, 2.4, 1.7, C.wall, -6.65, 4.4, -0.6, westWallG, { rough: 0.95 });
    var wallL1b = box(0.35, 5.6, 1.1, C.wall, -6.65, 2.8, 4.95, westWallG,
                      { rough: 0.95 });
    box(0.35, 2.2, 1.6, C.wall, -6.65, 4.5, 3.6, westWallG, { rough: 0.95 });
    if (DETAIL >= 2) {                   /* casing sells the opening */
      box(0.42, 3.5, 0.1, 0xe4ddd1, -6.65, 1.72, 2.82, westWallG);
      box(0.42, 3.5, 0.1, 0xe4ddd1, -6.65, 1.72, 4.38, westWallG);
      box(0.42, 0.1, 1.66, 0xe4ddd1, -6.65, 3.44, 3.6, westWallG);
    }
    if (SHADOWS) { wallB.castShadow = false; wallL.castShadow = false;
                   wallL1b.castShadow = false; }
    box(13.6, 0.28, 0.5, C.shell, 0, 5.66, -5.6);
    box(0.5, 0.28, 11.6, C.shell, -6.7, 5.66, 0);
    if (DETAIL >= 3) {                   /* baseboards: the trim that sells a wall */
      box(13, 0.2, 0.08, 0xe4ddd1, 0, 0.1, -5.34);
      box(0.08, 0.2, 4.0, 0xe4ddd1, -6.44, 0.1, -3.5);
      box(0.08, 0.2, 2.5, 0xe4ddd1, -6.44, 0.1, 1.5);
      box(0.08, 0.2, 1.0, 0xe4ddd1, -6.44, 0.1, 4.95);
    }

    /* ---- the GREAT ROOM extension (architect pass): the kitchen flows
       forward-left into a living room of its own scale — one open
       floorplan, one wood floor, no wall between. ---- */
    box(13.6, 0.5, 8.4, C.shell, 0, -0.27, 9.9);
    var floorTex2 = floorTex.clone();
    floorTex2.needsUpdate = true;
    floorTex2.wrapS = floorTex2.wrapT = T.RepeatWrapping;
    floorTex2.repeat.set(1, 8.5 / 11);
    var floor2 = new T.Mesh(new T.PlaneGeometry(13, 8.5),
      PBR ? new T.MeshStandardMaterial({ map: floorTex2, roughness: 0.5,
                                         envMapIntensity: 0.1 })
          : new T.MeshLambertMaterial({ map: floorTex2 }));
    floor2.rotation.x = -Math.PI / 2;
    floor2.position.set(0, 0.004, 9.95);
    if (SHADOWS) floor2.receiveShadow = true;
    scene.add(floor2);
    var wallL2 = box(0.35, 5.6, 8.4, C.wall, -6.65, 2.8, 10.0, westWallG,
                     { rough: 0.95 });
    if (SHADOWS) wallL2.castShadow = false;
    box(0.5, 0.28, 8.6, C.shell, -6.7, 5.66, 10.1);
    if (DETAIL >= 3) box(0.08, 0.2, 8.2, 0xe4ddd1, -6.44, 0.1, 9.9);
    /* the front door: decorative — the house has a face; the LEAVE
       signal stays the mudroom door zone */
    var fdoor = new T.Mesh(
      NICE ? roundedGeo(0.14, 3.2, 1.4, 0.04) : new T.BoxGeometry(0.14, 3.2, 1.4),
      PBR ? new T.MeshStandardMaterial({ map: woodDoor, roughness: 0.65 })
          : new T.MeshLambertMaterial({ color: 0xc9a06c, map: woodDoor || null }));
    fdoor.position.set(-6.42, 1.6, 13.35);
    /* the front door belongs to the west wall: it hides with it, or it
       fills the mudroom camera from behind */
    finish(fdoor); westWallG.add(fdoor);
    cyl(0.06, 0.06, 0.1, 0xd8c48a, -6.32, 1.6, 12.85, westWallG, 10, CHROME);
    /* ---- LIVING ROOM (studio pipeline, style bible S3/S4) --------------
       The forward half of the great room, built to the bible: casework is
       toe kick + carcass + face frame + inset fronts + hardware + top;
       every open bay carries 3-6 objects; upholstery is a frame with
       separate cushions on fat radii; nothing meets the floor without a
       shadow. Wall-plane things (TV, art, crown) ride westWallG, because
       the mudroom camera cuts that wall away and anything left in the
       scene there floats as a slab in mid-air. ---- */
    (function () {
      function ltag(m) { if (m) m.userData.room = 'living'; return m; }
      var WX = -6.475;                    /* the west wall's inner face */
      var PG = null;                      /* see the westWallG note below */
      var D2 = DETAIL >= 2, D3 = DETAIL >= 3;
      var FAB = { rough: 0.98 };          /* fabric never takes GLOSS */
      var PLASTER = { rough: 0.93 };
      var woodO = NICE ? { rough: 0.62, map: woodLight } : { rough: 0.62 };
      var woodK = NICE ? 0xffffff : 0xc89a66;
      var woodM = NICE ? 0xd2b489 : 0xa8834f;   /* a deeper wood: mantle, beams */
      function lb(w, h, d, c, x, y, z, g, o) { return ltag(box(w, h, d, c, x, y, z, g || PG, o)); }
      function lr(w, h, d, r, c, x, y, z, g, o) { return ltag(rbox(w, h, d, r, c, x, y, z, g || PG, o)); }
      function lc(a, b2, h, c, x, y, z, g, s, o) { return ltag(cyl(a, b2, h, c, x, y, z, g || PG, s, o)); }
      function sph(r, c, x, y, z, sy) {
        var m = new T.Mesh(new T.SphereGeometry(r, D3 ? 12 : 8, D3 ? 10 : 6),
                           mat(c, { rough: 1.0 }));
        m.position.set(x, y, z);
        if (sy) m.scale.y = sy;
        ltag(m); finish(m); (PG || scene).add(m); return m;
      }

      /* ---- the bible's small-prop vocabulary (S3.2) ------------------- */
      var BOOKC = [C.oxblood, C.sage, C.brass, C.slate, C.terracotta, C.cream];
      /* a run of book blocks: widths and heights vary, every fourth leans
         6-10 degrees. A shelf where every block matches is a comb. */
      function books(x, y, z0, n, step, seed) {
        if (!D2) return;
        for (var k = 0; k < n; k++) {
          var h = 0.25 + ((k * 5 + seed) % 4) * 0.032;
          var t = step * (0.58 + ((k + seed) % 3) * 0.11);
          var m = lb(0.21, h, t, BOOKC[(k + seed) % 6], x, y + h / 2,
                     z0 + step * (k + 0.5));
          if (D3 && (k + seed) % 4 === 3) { m.rotation.x = 0.15; m.position.y += 0.014; }
        }
      }
      function jar(x, y, z, r, h, c) {
        if (!D2) return;
        lc(r, r * 0.9, h, c, x, y + h / 2, z, null, 12, GLOSS);
        if (D3) lc(r * 0.62, r * 0.78, 0.05, C.brass, x, y + h + 0.024, z, null, 10, GLOSS);
      }
      function bowl(x, y, z, r, c) {
        if (!D2) return;
        lc(r, r * 0.6, 0.13, c, x, y + 0.065, z, null, 14, GLOSS);
      }
      function plateStack(x, y, z, r, c) {
        if (!D2) return;
        for (var k = 0; k < (D3 ? 3 : 2); k++)
          lc(r, r, 0.032, c, x, y + 0.018 + k * 0.042, z, null, 14, GLOSS);
      }
      /* a framed picture ON THE WALL PLANE, facing +x into the room */
      function picture(g, x, y, z, h, w, art) {
        lr(0.045, h, w, 0.012, C.slate, x, y, z, g, { rough: 0.55 });
        if (D3) lb(0.02, h - 0.05, w - 0.05, C.cream, x + 0.023, y, z, g, { rough: 0.92 });
        lb(0.02, h - 0.13, w - 0.13, art, x + 0.030, y, z, g, { rough: 0.88 });
      }
      /* a 5x7 standing on a shelf, leaning back a touch */
      function photo(x, y, z, h, w, art) {
        if (!D2) return;
        var f = lr(0.035, h, w, 0.01, C.wood2, x, y + h / 2, z, null, WOODM);
        lb(0.015, h - 0.09, w - 0.09, art, x + 0.024, y + h / 2, z, null, { rough: 0.9 });
        f.rotation.z = -0.05;
      }
      /* a potted plant. potO carries the material (ceramic gloss, matte
         terracotta, stone) so no two pots in the room read the same. */
      function plant(x, y0, z, s, potC, potO, stem, shadow) {
        var ph = 0.34 * s;
        lc(0.24 * s, 0.19 * s, ph, potC, x, y0 + ph / 2, z, null, 14, potO);
        if (D3) lc(0.25 * s, 0.25 * s, 0.05, potC, x, y0 + ph - 0.015, z, null, 14, potO);
        var b = y0 + ph;
        if (stem) {
          lc(0.035 * s, 0.048 * s, stem, C.wood2, x, b + stem / 2, z, null, 8, WOODM);
          b += stem * 0.82;
        }
        sph(0.30 * s, C.leaf, x, b + 0.15 * s, z, 0.82);
        if (D2) sph(0.21 * s, 0x527f44, x + 0.15 * s, b + 0.40 * s, z + 0.09 * s, 0.85);
        if (D3) sph(0.17 * s, C.leaf, x - 0.14 * s, b + 0.33 * s, z - 0.11 * s, 0.85);
        if (shadow) blobShadow(0.34 * s, 0.32 * s, x, z);
      }

      /* ================= 1. the rug: field, border stripe, field ======= */
      (function () {
        var rx = -3.40, rz = 9.40, rw = 4.30, rd = 6.00;
        function ply(w, d, y, c) {
          var m = new T.Mesh(new T.PlaneGeometry(w, d), mat(c, { rough: 1.0 }));
          m.rotation.x = -Math.PI / 2;
          m.position.set(rx, y, rz);
          if (SHADOWS) m.receiveShadow = true;
          ltag(m); scene.add(m);
        }
        ply(rw, rd, 0.050, C.rugB);
        if (D2) {
          ply(rw - 0.22, rd - 0.22, 0.055, C.oxblood);
          ply(rw - 0.34, rd - 0.34, 0.060, C.rugF);
        }
      })();

      PG = westWallG;      /* --- everything built into the wall --- */
      /* ================= 2. the hearth wall ============================
         Stone, breast, firebox with a slate surround, a chunky mantle
         with four props, and the TV bracketed above it. */
      var HZ = 8.6;
      /* the room needs a mass here, not a white panel on a white wall:
         the breast is stone (round-2 correction) */
      lb(0.90, 0.22, 2.72, C.stoneDk, WX + 0.45, 0.11, HZ, null, { rough: 0.9 });
      lb(0.44, 4.38, 2.32, C.stone, WX + 0.22, 2.41, HZ, null, PLASTER);
      if (D3) {                     /* a cap and a plinth band on the breast */
        lb(0.50, 0.11, 2.44, C.stoneDk, WX + 0.25, 4.28, HZ, null, PLASTER);
        lb(0.48, 0.09, 2.40, C.stoneDk, WX + 0.24, 2.26, HZ, null, PLASTER);
      }
      /* firebox: a slate surround RING (a solid slab just reads as a
         second TV), a recessed ink box, and a fire inside it */
      lb(0.06, 0.20, 1.56, C.slate, WX + 0.45, 1.42, HZ, null, { rough: 0.5 });
      lb(0.06, 1.40, 0.23, C.slate, WX + 0.45, 0.90, HZ - 0.665, null, { rough: 0.5 });
      lb(0.06, 1.40, 0.23, C.slate, WX + 0.45, 0.90, HZ + 0.665, null, { rough: 0.5 });
      lb(0.20, 1.20, 1.14, 0x14181c, WX + 0.33, 0.80, HZ, null, { rough: 0.95 });
      blobShadow(0.55, 1.42, WX + 0.45, HZ, PG);
      if (D2) {                    /* the hearth slab earns its two props */
        lc(0.20, 0.17, 0.30, C.cork, WX + 0.62, 0.37, HZ - 1.02, null, 12,
           { rough: 0.95 });
        lc(0.055, 0.055, 0.44, C.wood2, WX + 0.60, 0.62, HZ - 1.06, null, 8, WOODM);
        lc(0.055, 0.055, 0.38, C.wood2, WX + 0.66, 0.60, HZ - 0.98, null, 8, WOODM);
        lc(0.12, 0.14, 0.05, C.graphite, WX + 0.62, 0.245, HZ + 1.02, null, 10, STEEL);
        lc(0.02, 0.02, 0.66, C.graphite, WX + 0.62, 0.55, HZ + 1.02, null, 6, STEEL);
        lc(0.02, 0.02, 0.58, C.graphite, WX + 0.62, 0.51, HZ + 1.10, null, 6, STEEL);
      }
      if (D2) {
        var fire = new T.Mesh(new T.BoxGeometry(0.04, 0.58, 0.92),
                              new T.MeshBasicMaterial({ color: 0xf2761c }));
        fire.position.set(WX + 0.320, 0.60, HZ);
        ltag(fire); (PG || scene).add(fire);
        var emb = new T.Mesh(new T.BoxGeometry(0.06, 0.13, 0.86),
                             new T.MeshBasicMaterial({ color: 0xffc46a }));
        emb.position.set(WX + 0.335, 0.38, HZ);
        ltag(emb); (PG || scene).add(emb);
      }
      if (D3) {
        [[-0.13, 0.40], [0.13, 0.42], [0.0, 0.58]].forEach(function (lg) {
          var lgm = lc(0.095, 0.095, 0.84, 0x2f2517, WX + 0.400, lg[1], HZ + lg[0],
                       null, 8, { rough: 0.95 });
          lgm.rotation.x = Math.PI / 2;
        });
        lb(0.14, 0.035, 0.96, C.ink, WX + 0.400, 0.30, HZ, null, { rough: 0.85 });
      }
      /* mantle: a beam with corbels, four props, and a soundbar */
      lb(0.60, 0.20, 2.56, woodM, WX + 0.30, 1.72, HZ, null, woodO);
      if (D3) {
        lb(0.15, 0.17, 0.16, woodM, WX + 0.50, 1.53, HZ - 1.08, null, woodO);
        lb(0.15, 0.17, 0.16, woodM, WX + 0.50, 1.53, HZ + 1.08, null, woodO);
      }
      photo(WX + 0.42, 1.825, HZ - 1.00, 0.44, 0.34, C.sage);
      if (D2) {
        lc(0.05, 0.07, 0.26, C.brass, WX + 0.48, 1.955, HZ - 0.60, null, 10, STEEL);
        lc(0.035, 0.035, 0.10, C.cream, WX + 0.48, 2.135, HZ - 0.60, null, 8);
        lc(0.05, 0.07, 0.20, C.brass, WX + 0.48, 1.925, HZ - 0.42, null, 10, STEEL);
        lc(0.035, 0.035, 0.10, C.cream, WX + 0.48, 2.065, HZ - 0.42, null, 8);
        lb(0.14, 0.12, 0.94, C.graphite, WX + 0.50, 1.885, HZ + 0.12, null, { rough: 0.55 });
      }
      plant(WX + 0.48, 1.825, HZ + 0.98, 0.46, C.cream, GLOSS, 0, false);
      /* the TV: bracket, bezel, screen. westWallG - see the header note. */
      lb(0.12, 0.32, 0.32, C.graphite, WX + 0.44, 3.18, HZ, westWallG, { rough: 0.6 });
      lr(0.09, 1.14, 1.78, 0.025, 0x3a434e, WX + 0.560, 3.18, HZ, westWallG, { rough: 0.72 });
      lb(0.02, 0.96, 1.56, 0x0d1013, WX + 0.616, 3.18, HZ, westWallG,
         { rough: 0.62, metal: 0.0, envInt: 0.04 });
      if (D3) lb(0.02, 0.03, 0.05, C.teal, WX + 0.616, 2.72, HZ - 0.80, westWallG, GLOSS);

      /* ================= 3. the built-ins flanking the hearth ==========
         S3.1 + S3.2: toe kick, carcass, face frame with a centre stile,
         inset shaker fronts with a 0.03 reveal, graphite pulls, a top
         cap, then three open bays over a darker inset back panel. */
      function builtIn(bz, seed) {
        var W0 = 1.25, HH = 2.95, F = WX + 0.46, xc = WX + 0.23;
        lb(0.46, HH, 0.055, C.cabShade, xc, HH / 2, bz - 0.5975, null, PLASTER);
        lb(0.46, HH, 0.055, C.cabShade, xc, HH / 2, bz + 0.5975, null, PLASTER);
        lb(0.50, 0.08, W0 + 0.05, C.cab, xc + 0.02, HH + 0.04, bz, null, PLASTER);
        lb(0.40, 0.16, W0 - 0.12, C.cabShade, xc - 0.03, 0.08, bz);
        lb(0.44, 0.90, W0 - 0.11, C.cabShade, xc, 0.61, bz);
        if (D2) {
          /* face frame: stiles 0.09 wide, 0.04 proud of the carcass */
          [-0.53, 0, 0.53].forEach(function (dz) {
            lb(0.04, 0.90, 0.09, C.cab, F + 0.02, 0.61, bz + dz);
          });
          lb(0.04, 0.09, 1.14, C.cab, F + 0.02, 0.205, bz);
          lb(0.04, 0.09, 1.14, C.cab, F + 0.02, 1.015, bz);
          [-0.265, 0.265].forEach(function (dz) {
            lr(0.03, 0.66, 0.38, 0.02, C.cab, F + 0.028, 0.61, bz + dz);
            if (D3) lr(0.02, 0.54, 0.26, 0.015, C.cabShade, F + 0.043, 0.61, bz + dz);
            lb(0.025, 0.30, 0.025, C.graphite, F + 0.055, 0.61,
               bz + (dz > 0 ? 0.10 : -0.10));
          });
        }
        /* top cap: a different material from the fronts (S3.1.6) */
        lb(0.50, 0.06, W0 + 0.02, woodK, xc + 0.02, 1.09, bz, null, woodO);
        /* the bay: a back panel one shade darker, inset - this is what
           makes a bay read as a bay and not a hole (S3.2) */
        lb(0.02, 1.80, W0 - 0.14, C.bayBack, WX + 0.05, 2.02, bz, null, { rough: 0.95 });
        lb(0.45, 0.06, W0 - 0.11, C.cab, WX + 0.225, 1.72, bz, null, PLASTER);
        lb(0.45, 0.06, W0 - 0.11, C.cab, WX + 0.225, 2.30, bz, null, PLASTER);
        if (D3) {                        /* the shelf's front edge line */
          lb(0.02, 0.062, W0 - 0.11, C.cabShade, WX + 0.445, 1.72, bz);
          lb(0.02, 0.062, W0 - 0.11, C.cabShade, WX + 0.445, 2.30, bz);
        }
        blobShadow(0.34, 0.72, xc, bz, PG);

        if (!D2) return;
        var xs = WX + 0.255;
        /* bay A (y 1.12): a book run, a bowl, a jar */
        books(xs, 1.12, bz - 0.54, 6, 0.088, seed);
        bowl(xs + 0.03, 1.12, bz + 0.14, 0.16, C.terracotta);
        jar(xs - 0.02, 1.12, bz + 0.42, 0.085, 0.22, C.sage);
        /* bay B (y 1.75): plates, two jars, a framed 5x7 */
        plateStack(xs, 1.75, bz - 0.42, 0.15, C.cream);
        jar(xs, 1.75, bz - 0.10, 0.085, 0.26, C.brass);
        jar(xs - 0.03, 1.75, bz + 0.12, 0.065, 0.17, C.terracotta);
        photo(xs + 0.06, 1.75, bz + 0.40, 0.30, 0.24,
              seed % 2 ? C.oxblood : C.sage);
        /* bay C (y 2.33): a plant, a book run, a flat stack */
        plant(xs, 2.33, bz - 0.44, 0.42, seed % 2 ? C.terracotta : C.cream,
              seed % 2 ? { rough: 0.85 } : GLOSS, 0, false);
        books(xs, 2.33, bz - 0.16, 5, 0.086, seed + 2);
        if (D3) {
          lb(0.20, 0.055, 0.30, C.slate, xs, 2.36, bz + 0.42);
          lb(0.19, 0.05, 0.28, C.cream, xs, 2.415, bz + 0.42);
          lb(0.18, 0.05, 0.26, C.oxblood, xs, 2.465, bz + 0.43);
        }
      }
      builtIn(6.795, 0);
      builtIn(10.405, 3);
      PG = null;           /* --- back to free-standing furniture --- */

      /* ================= 4. upholstery (S3.3) ==========================
         One builder for the sofa and both armchairs: legs, base frame,
         individual seat cushions with a 0.02 gap, a back frame with its
         own cushions, two arms, and pillows rotated off-axis. Built
         facing -x, then rotated into place. */
      function seat(x, z, rot, len, body, shade, nc, pillows, dp) {
        var g = new T.Group();
        g.position.set(x, 0, z);
        g.rotation.y = rot;
        ltag(g); scene.add(g);
        var DP = dp || 1.24;
        function sb(w, h, d, r, c, px, py, pz, o) {
          var m = new T.Mesh(
            D2 ? roundedGeo(w, h, d, r) : new T.BoxGeometry(w, h, d),
            mat(c, o || FAB));
          m.position.set(px, py, pz);
          m.userData.room = 'living';
          finish(m); g.add(m); return m;
        }
        [[-DP / 2 + 0.16, -len / 2 + 0.18], [DP / 2 - 0.16, -len / 2 + 0.18],
         [-DP / 2 + 0.16, len / 2 - 0.18], [DP / 2 - 0.16, len / 2 - 0.18]]
          .forEach(function (lg) {
            var m = new T.Mesh(new T.CylinderGeometry(0.05, 0.04, 0.16, 8),
                               mat(C.wood2, WOODM));
            m.position.set(lg[0], 0.08, lg[1]);
            m.userData.room = 'living'; finish(m); g.add(m);
          });
        sb(DP, 0.20, len, 0.16, shade, 0, 0.26, 0);
        var cw = (len - 0.10) / nc, k;
        for (k = 0; k < nc; k++) {                       /* the 0.02 gap */
          sb(DP - 0.16, 0.22, cw - 0.02, 0.16, body, -0.04, 0.47,
             -len / 2 + 0.05 + cw * (k + 0.5));
        }
        sb(0.20, 0.92, len, 0.14, shade, DP / 2 - 0.10, 0.82, 0);
        for (k = 0; k < nc; k++) {
          sb(0.24, 0.58, cw - 0.05, 0.16, body, DP / 2 - 0.30, 0.90,
             -len / 2 + 0.05 + cw * (k + 0.5));
        }
        sb(DP, 0.50, 0.30, 0.14, body, 0, 0.61, -len / 2 + 0.15);
        sb(DP, 0.50, 0.30, 0.14, body, 0, 0.61, len / 2 - 0.15);
        if (D2 && pillows) {
          pillows.forEach(function (p) {
            var m = sb(0.20, 0.50, 0.50, 0.14, p[1], DP / 2 - 0.58, 0.86, p[0]);
            m.rotation.x = p[2];
            m.rotation.z = -0.16;
          });
        }
        if (D3 && len > 2) {                    /* a throw over one arm */
          var th = sb(0.94, 0.09, 0.50, 0.03, C.rugB, -0.12, 0.87, len / 2 - 0.15);
          th.rotation.z = 0.05;
        }
        blobShadow(DP * 0.60, len * 0.52, x, z);
        return g;
      }
      /* the sofa faces the hearth; the armchair closes the triangle at
         44 degrees off it, looking at the fire and the sofa both (S7.1) */
      seat(-2.55, 8.60, 0, 2.95, C.sage, C.sageDeep, 3,
           [[-0.95, C.oxblood, 0.22], [0.95, C.terracotta, -0.24]]);
      /* a matched pair of chairs, one at each end of the table: the
         north one shows the camera its FRONT, which is what makes the
         triangle read at a glance */
      seat(-4.30, 7.15, 0.80, 1.12, C.terracotta, C.terraDeep, 1,
           [[0.0, C.cream, -0.20]], 1.14);
      seat(-4.35, 10.90, -1.05, 1.12, C.terracotta, C.terraDeep, 1,
           [[0.0, C.cream, 0.20]], 1.14);

      /* a console behind the sofa, facing the kitchen half of the great
         room - the piece that keeps the east floor from reading bare */
      (function () {
        var SX = -1.72, SZ = 8.60;
        [-1.10, 1.10].forEach(function (dz) {
          lc(0.045, 0.038, 0.30, C.wood2, SX - 0.14, 0.15, SZ + dz, null, 8, WOODM);
          lc(0.045, 0.038, 0.30, C.wood2, SX + 0.14, 0.15, SZ + dz, null, 8, WOODM);
        });
        lr(0.40, 0.50, 2.44, 0.04, woodK, SX, 0.55, SZ, null, woodO);
        lb(0.46, 0.06, 2.56, C.slate, SX, 0.83, SZ, null, { rough: 0.5 });
        if (D2) {
          lb(0.03, 0.34, 1.04, C.cab, SX + 0.20, 0.55, SZ - 0.56);
          lb(0.03, 0.34, 1.04, C.cab, SX + 0.20, 0.55, SZ + 0.56);
          lb(0.025, 0.025, 0.30, C.graphite, SX + 0.225, 0.55, SZ - 0.56);
          lb(0.025, 0.025, 0.30, C.graphite, SX + 0.225, 0.55, SZ + 0.56);
          /* four props: a vase of branches, a book stack, a tray, a bowl */
          lc(0.13, 0.09, 0.42, C.sageDeep, SX, 1.07, SZ - 0.92, null, 12, GLOSS);
          lc(0.02, 0.02, 0.52, C.wood2, SX - 0.03, 1.50, SZ - 0.94, null, 6);
          lc(0.02, 0.02, 0.44, C.wood2, SX + 0.04, 1.46, SZ - 0.88, null, 6);
          lb(0.26, 0.055, 0.34, C.oxblood, SX, 0.888, SZ - 0.24);
          lb(0.25, 0.05, 0.32, C.brass, SX, 0.940, SZ - 0.25);
          lr(0.30, 0.03, 0.44, 0.015, C.brass, SX, 0.876, SZ + 0.30, null, STEEL);
          bowl(SX, 0.89, SZ + 0.30, 0.13, C.cream);
          if (D3) photo(SX + 0.02, 0.86, SZ + 0.92, 0.34, 0.26, C.terracotta);
        }
        blobShadow(0.3, 1.3, SX, SZ);
      })();

      /* ================= 5. the coffee table ==========================
         The critter laptop's surface (zone: pet) - top at y 0.60. */
      lr(1.70, 0.10, 1.20, 0.03, woodK, -4.45, 0.55, 8.95, null, woodO);
      [[-5.13, 8.45], [-3.77, 8.45], [-5.13, 9.45], [-3.77, 9.45]]
        .forEach(function (p) {
          lc(0.055, 0.045, 0.50, C.wood2, p[0], 0.25, p[1], null, 8, WOODM);
        });
      if (D2) {
        lb(1.44, 0.05, 0.96, woodK, -4.45, 0.26, 8.95, null, woodO);
        lb(0.30, 0.055, 0.22, C.oxblood, -4.80, 0.315, 8.95);
        lb(0.28, 0.05, 0.20, C.cream, -4.80, 0.368, 8.96);
        lc(0.20, 0.22, 0.16, C.cork, -4.05, 0.365, 8.95, null, 12, { rough: 0.9 });
        lr(0.44, 0.035, 0.32, 0.02, C.brass, -3.99, 0.62, 9.32, null, STEEL);
        lc(0.075, 0.065, 0.12, C.cream, -4.07, 0.665, 9.32, null, 10, GLOSS);
        lc(0.075, 0.065, 0.12, C.cream, -3.91, 0.665, 9.32, null, 10, GLOSS);
      }
      if (D3) {
        lc(0.06, 0.06, 0.11, C.cream, -5.03, 0.66, 9.32, null, 10, GLOSS);
        lb(0.22, 0.05, 0.30, C.sage, -5.03, 0.625, 8.62);
      }
      blobShadow(0.9, 0.68, -4.45, 8.95);

      /* ================= 6. a lamp table at the sofa's north end ======= */
      lr(0.62, 0.07, 0.62, 0.02, woodK, -2.95, 0.71, 6.62, null, woodO);
      lc(0.06, 0.06, 0.70, C.wood2, -2.95, 0.35, 6.62, null, 8, WOODM);
      lc(0.24, 0.26, 0.05, C.wood2, -2.95, 0.03, 6.62, null, 12, WOODM);
      if (D2) {
        lc(0.14, 0.10, 0.34, C.terracotta, -3.02, 0.92, 6.62, null, 12, GLOSS);
        var shd = new T.Mesh(new T.CylinderGeometry(0.17, 0.25, 0.26, 14, 1, true),
          PBR ? new T.MeshStandardMaterial({ color: 0xf3e8d2, roughness: 0.8,
                                             emissive: 0xffd9a0, emissiveIntensity: 0.35,
                                             side: T.DoubleSide })
              : new T.MeshLambertMaterial({ color: 0xf3e8d2, side: T.DoubleSide }));
        shd.position.set(-3.02, 1.24, 6.62);
        ltag(shd); finish(shd, true); scene.add(shd);
        lb(0.22, 0.05, 0.16, C.slate, -2.80, 0.77, 6.46);
        lb(0.21, 0.045, 0.15, C.brass, -2.80, 0.818, 6.47);
      }
      blobShadow(0.36, 0.36, -2.95, 6.62);

      /* ================= 7. the console + the gallery wall =============
         S7.2's second anchor: a real sideboard under a grid of five
         frames, filling the wall between the built-in and the front
         door (which moved 0.75 south to make the room). */
      var CZ = 11.85;
      [-0.62, 0.62].forEach(function (dz) {
        lc(0.05, 0.04, 0.30, C.wood2, WX + 0.14, 0.15, CZ + dz, null, 8, WOODM);
        lc(0.05, 0.04, 0.30, C.wood2, WX + 0.42, 0.15, CZ + dz, null, 8, WOODM);
      });
      lr(0.48, 0.58, 1.46, 0.04, woodK, WX + 0.28, 0.59, CZ, null, woodO);
      lb(0.54, 0.07, 1.58, C.slate, WX + 0.29, 0.915, CZ, null, { rough: 0.5 });
      if (D2) {
        [-0.36, 0.36].forEach(function (dz) {
          lr(0.03, 0.42, 0.62, 0.02, C.cab, WX + 0.525, 0.60, CZ + dz);
          if (D3) lr(0.02, 0.30, 0.50, 0.015, C.cabShade, WX + 0.54, 0.60, CZ + dz);
          lb(0.025, 0.025, 0.28, C.graphite, WX + 0.555, 0.60, CZ + dz);
        });
        /* two props minimum on any surface over 0.5u2 (S4) - four here */
        lc(0.15, 0.11, 0.36, C.terracotta, WX + 0.28, 1.13, CZ - 0.52, null, 12, GLOSS);
        var shd2 = new T.Mesh(new T.CylinderGeometry(0.18, 0.27, 0.28, 14, 1, true),
          PBR ? new T.MeshStandardMaterial({ color: 0xf3e8d2, roughness: 0.8,
                                             emissive: 0xffd9a0, emissiveIntensity: 0.35,
                                             side: T.DoubleSide })
              : new T.MeshLambertMaterial({ color: 0xf3e8d2, side: T.DoubleSide }));
        shd2.position.set(WX + 0.28, 1.46, CZ - 0.52);
        ltag(shd2); finish(shd2, true); scene.add(shd2);
        bowl(WX + 0.30, 0.95, CZ - 0.10, 0.17, C.brass);
        lb(0.26, 0.055, 0.34, C.oxblood, WX + 0.28, 0.978, CZ + 0.18);
        lb(0.25, 0.05, 0.32, C.sage, WX + 0.28, 1.030, CZ + 0.19);
        if (D3) lb(0.24, 0.05, 0.30, C.cream, WX + 0.28, 1.080, CZ + 0.17);
      }
      plant(WX + 0.29, 0.95, CZ + 0.56, 0.46, C.linen, { rough: 0.8 }, 0, false);
      if (D3) lc(0.20, 0.24, 0.26, C.cork, WX + 0.30, 0.13, CZ + 0.50, null, 12, { rough: 0.95 });
      blobShadow(0.36, 0.82, WX + 0.30, CZ);
      /* the grid of five (S7.5) - wall plane, so westWallG */
      if (D2) {
        [[2.86, CZ - 0.50], [2.86, CZ], [2.86, CZ + 0.50],
         [2.16, CZ - 0.25], [2.16, CZ + 0.25]].forEach(function (f, i) {
          picture(westWallG, WX + 0.028, f[0], f[1], 0.56, 0.42,
                  [C.sage, C.terracotta, C.oxblood, C.brass, C.slate][i]);
        });
        if (D3) {                       /* a picture light over the grid */
          lb(0.10, 0.05, 0.06, C.brass, WX + 0.08, 3.28, CZ, westWallG, STEEL);
          lc(0.045, 0.045, 0.44, C.brass, WX + 0.16, 3.26, CZ, westWallG, 10, STEEL);
        }
      }

      /* ================= 8. the reading corner =========================
         S7.2's second zone: the bare third of the floor gets a chair, a
         lamp, a side table and a tall plant on their own round rug. */
      (function () {
        var rug = new T.Mesh(new T.CircleGeometry(2.00, D3 ? 28 : 16),
                             mat(C.linen, { rough: 1.0 }));
        rug.rotation.x = -Math.PI / 2;
        rug.position.set(1.10, 0.048, 9.55);
        if (SHADOWS) rug.receiveShadow = true;
        ltag(rug); scene.add(rug);
        if (D2) {
          var ring = new T.Mesh(new T.RingGeometry(1.72, 1.84, 28),
                                mat(C.sageDeep, { rough: 1.0 }));
          ring.rotation.x = -Math.PI / 2;
          ring.position.set(1.10, 0.054, 9.55);
          ltag(ring); scene.add(ring);
        }
      })();
      seat(0.55, 9.60, 0.55, 1.12, C.sage, C.sageDeep, 1,
           [[0.0, C.oxblood, -0.22]], 1.14);
      /* the floor lamp: base, stem, shade. All of it is D2 - a bare pole
         with no shade at the low tier reads as broken geometry. */
      if (D2) {
        lc(0.28, 0.30, 0.05, C.brass, 2.16, 0.03, 8.55, null, 14, STEEL);
        lc(0.035, 0.035, 1.62, C.brass, 2.16, 0.86, 8.55, null, 8, STEEL);
        var lsh2 = new T.Mesh(new T.CylinderGeometry(0.24, 0.34, 0.34, 16, 1, true),
          PBR ? new T.MeshStandardMaterial({ color: 0xf3e8d2, roughness: 0.8,
                                             emissive: 0xffd9a0, emissiveIntensity: 0.45,
                                             side: T.DoubleSide })
              : new T.MeshLambertMaterial({ color: 0xf3e8d2, side: T.DoubleSide }));
        lsh2.position.set(2.16, 1.82, 8.55);
        ltag(lsh2); finish(lsh2, true); scene.add(lsh2);
      }
      blobShadow(0.32, 0.32, 2.16, 8.55);
      /* the side table: pedestal, base, top, three props */
      lc(0.44, 0.44, 0.07, woodK, 1.72, 0.62, 10.22, null, 16, woodO);
      lc(0.065, 0.065, 0.58, C.wood2, 1.72, 0.30, 10.22, null, 10, WOODM);
      lc(0.26, 0.28, 0.05, C.wood2, 1.72, 0.03, 10.22, null, 14, WOODM);
      if (D2) {
        lb(0.28, 0.055, 0.20, C.slate, 1.62, 0.683, 10.14);
        lb(0.26, 0.05, 0.19, C.brass, 1.62, 0.735, 10.15);
        lc(0.085, 0.075, 0.14, C.cream, 1.89, 0.725, 10.34, null, 10, GLOSS);
      }
      blobShadow(0.4, 0.4, 1.72, 10.22);
      /* a pouf bridging the two zones */
      lr(0.66, 0.36, 0.66, 0.17, C.terracotta, -1.30, 0.20, 10.20, null, FAB);
      if (D3) lb(0.60, 0.02, 0.60, C.terraDeep, -1.30, 0.385, 10.20, null, FAB);
      blobShadow(0.38, 0.38, -1.30, 10.20);
      /* a basket and a stack of books beside the reading chair */
      lc(0.26, 0.22, 0.34, C.cork, -0.42, 0.17, 9.05, null, 12, { rough: 0.95 });
      if (D2) lc(0.27, 0.27, 0.05, C.sage, -0.42, 0.36, 9.05, null, 12, FAB);
      blobShadow(0.28, 0.28, -0.42, 9.05);
      /* a stack of books on the floor beside the chair */
      if (D2) {
        lb(0.34, 0.06, 0.26, C.oxblood, 0.55, 0.03, 10.45);
        lb(0.33, 0.055, 0.25, C.cream, 0.55, 0.088, 10.46);
        if (D3) lb(0.31, 0.055, 0.24, C.sage, 0.56, 0.143, 10.44);
      }

      /* a lidded basket of blankets and a floor stack: the rug's south
         half was bare plank in round 3 */
      lc(0.30, 0.26, 0.42, C.cork, -5.05, 0.21, 11.75, null, 14, { rough: 0.95 });
      if (D2) {
        lc(0.31, 0.31, 0.05, C.rugB, -5.05, 0.44, 11.75, null, 14, FAB);
        lr(0.34, 0.16, 0.34, 0.07, C.sage, -5.05, 0.53, 11.75, null, FAB);
      }
      blobShadow(0.33, 0.33, -5.05, 11.75);
      if (D2) {
        lc(0.09, 0.09, 0.46, C.wood2, -2.72, 0.23, 11.70, null, 10, WOODM);
        lc(0.34, 0.34, 0.06, woodK, -2.72, 0.48, 11.70, null, 16, woodO);
        lc(0.24, 0.26, 0.04, C.wood2, -2.72, 0.02, 11.70, null, 12, WOODM);
        lb(0.24, 0.05, 0.18, C.oxblood, -2.78, 0.535, 11.64);
        lc(0.075, 0.065, 0.13, C.brass, -2.60, 0.575, 11.78, null, 10, STEEL);
        blobShadow(0.3, 0.3, -2.72, 11.70);
      }

      /* ================= 9. plants (S4 wants three; five here) ========= */
      plant(-5.42, 0, 13.86, 1.20, C.terracotta, { rough: 0.85 }, 0.55, true);
      plant(0.95, 0, 6.75, 1.14, C.terracotta, { rough: 0.85 }, 0.62, true);
      plant(2.68, 0, 9.05, 1.00, C.linen, { rough: 0.78 }, 0.42, true);

      PG = westWallG;
      /* ================= 10. the radio shelf (zone: radio) ============= */
      lb(0.50, 0.07, 1.34, woodK, WX + 0.25, 1.30, 5.44, null, woodO);
      lb(0.46, 0.06, 1.34, woodK, WX + 0.23, 2.02, 5.44, null, woodO);
      if (D2) {
        [4.88, 6.02].forEach(function (bz) {
          lb(0.30, 0.26, 0.07, C.graphite, WX + 0.15, 1.14, bz);
          lb(0.28, 0.24, 0.06, C.graphite, WX + 0.14, 1.86, bz);
        });
        books(WX + 0.25, 2.05, 5.66, 4, 0.085, 1);
        jar(WX + 0.24, 2.05, 5.10, 0.085, 0.22, C.terracotta);
        photo(WX + 0.27, 2.05, 4.90, 0.28, 0.22, C.brass);
        bowl(WX + 0.26, 1.34, 5.98, 0.15, C.sage);
        plant(WX + 0.26, 1.34, 4.90, 0.46, C.cream, GLOSS, 0, false);
      }

      /* ---- the decorative front door earns its casing and panels ---- */
      PG = westWallG;
      lb(0.13, 3.44, 0.14, 0xe4ddd1, WX + 0.065, 1.72, 12.56);
      lb(0.13, 3.44, 0.14, 0xe4ddd1, WX + 0.065, 1.72, 14.14);
      lb(0.13, 0.14, 1.86, 0xe4ddd1, WX + 0.065, 3.37, 13.35);
      if (D2) {
        lb(0.02, 1.20, 0.90, 0x6f5433, WX + 0.135, 2.14, 13.35, null, WOODM);
        lb(0.02, 0.98, 0.90, 0x6f5433, WX + 0.135, 0.82, 13.35, null, WOODM);
        lb(0.04, 1.04, 0.74, 0xc79b63, WX + 0.150, 2.14, 13.35, null, WOODM);
        lb(0.04, 0.82, 0.74, 0xc79b63, WX + 0.150, 0.82, 13.35, null, WOODM);
        lb(0.03, 0.11, 0.92, 0x6f5433, WX + 0.140, 1.48, 13.35, null, WOODM);
      }
      PG = null;
      if (D2) {                                  /* a mat at the door */
        var mt = new T.Mesh(new T.PlaneGeometry(0.90, 1.40), mat(C.rugB, { rough: 1.0 }));
        mt.rotation.x = -Math.PI / 2;
        mt.position.set(-5.95, 0.046, 12.95);
        if (SHADOWS) mt.receiveShadow = true;
        ltag(mt); scene.add(mt);
        if (D3) {
          var mt2 = new T.Mesh(new T.PlaneGeometry(0.72, 1.22), mat(C.oxblood, { rough: 1.0 }));
          mt2.rotation.x = -Math.PI / 2;
          mt2.position.set(-5.95, 0.051, 12.95);
          ltag(mt2); scene.add(mt2);
        }
      }

      /* ================= 11. crown: the ceiling gap gets filled (S1) === */
      if (D3) {
        lb(0.10, 0.16, 8.30, 0xe4ddd1, WX + 0.05, 4.94, 9.95, westWallG);
        lb(0.06, 0.06, 8.30, C.cabShade, WX + 0.03, 4.84, 9.95, westWallG);
      }
    })();

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
    upperCab(1.4, -3.78, -5.1);
    upperCab(1.8, 0.2, -5.1);

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
    var winG = zoneGroup('window', -1.88, 0, -5.4);
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
    var fridgeDoorTop = rbox(1.6, 1.55, 0.07, 0.03, C.teal, 0, 2.95, 0.77, fridge,
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
    /* the PANTRY (architect pass): a REAL closet. A paneled door hangs
       in the kitchen wall where the corkboard once was; lean in and the
       door steps aside (micro dollhouse trick) showing the shelves and
       the honest jars — a long list still means bare shelves. */
    var boardFace = new T.Mesh(new T.PlaneGeometry(1.6, 3.0),
      new T.MeshBasicMaterial({ visible: false }));
    boardFace.rotation.y = Math.PI / 2;
    boardFace.position.set(0.26, 1.7, 0);
    board.add(boardFace);
    var pantryDoor = new T.Mesh(
      NICE ? roundedGeo(0.12, 3.1, 1.6, 0.04) : new T.BoxGeometry(0.12, 3.1, 1.6),
      PBR ? new T.MeshStandardMaterial({ map: woodDoor, roughness: 0.65 })
          : new T.MeshLambertMaterial({ color: 0xc9a06c,
                                        map: woodDoor || null }));
    pantryDoor.position.set(0.2, 1.6, 0);
    pantryDoor.userData.zone = 'board';
    finish(pantryDoor); board.add(pantryDoor);
    var pknob = cyl(0.055, 0.055, 0.09, 0xd8c48a, 0.3, 1.55, 0.55, board, 10,
                    CHROME);
    pknob.userData.zone = 'board';
    /* the closet itself: a bump-out behind the wall */
    (function () {
      function cmat() {
        /* literals + no map: this block builds before the exterior
           texture pack exists (declaration order) */
        return mat(0xece5da, { rough: 0.95 });
      }
      function cbox(w, h, d, x, y, z, m) {
        var mm = new T.Mesh(new T.BoxGeometry(w, h, d), m || cmat());
        mm.position.set(x, y, z); finish(mm); scene.add(mm); return mm;
      }
      cbox(1.9, 0.5, 2.6, -7.8, -0.27, -0.6, mat(C.shell, { rough: 0.9 }));
      cbox(0.2, 3.4, 2.4, -8.6, 1.7, -0.6);
      cbox(1.6, 3.4, 0.2, -7.8, 1.7, -1.75);
      cbox(1.6, 3.4, 0.2, -7.8, 1.7, 0.55);
      cbox(1.9, 0.18, 2.6, -7.8, 3.48, -0.6, mat(0x55606b, { rough: 0.9 }));
      var pFloorTex = floorTex.clone();
      pFloorTex.needsUpdate = true;
      pFloorTex.wrapS = pFloorTex.wrapT = T.RepeatWrapping;
      pFloorTex.repeat.set(1.5 / 13, 2.1 / 11);
      var pfloor = new T.Mesh(new T.PlaneGeometry(1.5, 2.1),
        PBR ? new T.MeshStandardMaterial({ map: pFloorTex, roughness: 0.55,
                                           envMapIntensity: 0.1 })
            : new T.MeshLambertMaterial({ map: pFloorTex }));
      pfloor.rotation.x = -Math.PI / 2;
      pfloor.position.set(-7.8, 0.03, -0.6);
      finish(pfloor); scene.add(pfloor);
      [0.9, 1.7, 2.5].forEach(function (sy) {
        var sh = new T.Mesh(new T.BoxGeometry(1.2, 0.06, 2.0),
          PBR ? new T.MeshStandardMaterial({ map: woodLight, roughness: 0.7 })
              : new T.MeshLambertMaterial({ color: 0xb98c58,
                                            map: woodLight || null }));
        sh.position.set(-7.95, sy, -0.6);
        sh.userData.zone = 'board';
        finish(sh); scene.add(sh);
      });
    })();
    var pantryJars = [];
    (function () {
      var JAR_C = [0xe09a3e, 0xc9473d, 0x3fbdb2, 0xcf9a55];
      for (var j = 0; j < 8; j++) {
        var jy = j < 4 ? 1.06 : 1.86;
        var jar = cyl(0.1, 0.1, 0.26, JAR_C[j % 4],
                      -1.53, jy, -1.06 + (j % 4) * 0.48, board, 10, GLOSS);
        jar.userData.zone = 'board';
        pantryJars.push(jar);
      }
    })();
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
    var doorG = zoneGroup('door', -9.8, 0, 8.14);   /* the mudroom's street door */
    doorG.rotation.y = Math.PI;   /* the hero card reads from inside */
    doorG.userData.room = 'mudroom';
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
    var radio = zoneGroup('radio', -6.15, 0, 5.5);   /* the living-room shelf */
    radio.userData.room = 'living';
    radio.rotation.y = Math.PI / 2;   /* face east, into the great room */
    rbox(0.8, 0.45, 0.4, 0.06, C.red, 0, 1.41, 0, radio, GLOSS);
    var radioFace = box(0.55, 0.28, 0.03, 0xf2e3b8, -0.06, 1.42, 0.21, radio, { rough: 0.95 });
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

    /* pendant lamps over the island: warm emissive shades. Grouped so a
       lean-in can hide them — a cord across a focused card breaks the
       card-on-the-surface illusion. */
    var pendants = new T.Group();
    scene.add(pendants);
    if (DETAIL >= 3) {
      [-1.1, 0.4].forEach(function (px) {
        var cord = cyl(0.008, 0.008, 1.4, 0x8a8178, px, 4.9, 0.9, pendants, 6);
        cord.castShadow = false;   // a hair-thin cord throws a room-long streak
        var shade = new T.Mesh(new T.CylinderGeometry(0.3, 0.42, 0.34, 18, 1, true),
          new T.MeshStandardMaterial({ color: 0xf0e3c8, roughness: 0.7,
                                       emissive: 0xffdf9e, emissiveIntensity: 0.55,
                                       side: T.DoubleSide }));
        shade.position.set(px, 4.05, 0.9);
        shade.castShadow = false;
        pendants.add(shade);
      });
    }

    /* ---- CRITTER LAPTOP (zone: pet): the game lives on a screen -------
       Critters are a rudimentary Pokemon, not a care loop — and not the
       family's real pets, so no bowl pretending otherwise. A laptop sits
       on the island the way a kid leaves one, its screen carrying the
       roster. */
    var crit = zoneGroup('pet', -4.57, -0.610, 8.72);   /* the coffee table */
    crit.userData.room = 'living';
    rbox(0.66, 0.035, 0.46, 0.012, 0x2a2d34, 0, 1.24, 0.02, crit,
         { rough: 0.35, metal: 0.4, envInt: 0.6 });
    var lid = rbox(0.66, 0.44, 0.028, 0.012, 0x2a2d34, 0, 1.44, -0.24, crit,
                   { rough: 0.35, metal: 0.4, envInt: 0.6 });
    lid.rotation.x = -0.30;
    lid.position.y = 1.445; lid.position.z = -0.175;
    var critFace = new T.Mesh(new T.PlaneGeometry(0.60, 0.38),
                              mat(0x12151c, { rough: 0.6 }));
    critFace.rotation.x = -0.30;
    critFace.position.set(0, 1.4395, -0.157);
    crit.add(critFace); finish(critFace);

    /* ---- the house around the kitchen (H1): everything out here lives
       in extG so the camera modes can reason about "outside". The
       kitchen's world coordinates never moved — the house grew around
       them. ---- */
    var EXTC = { grass: 0x8fae6e, siding: 0xe7e0d5, trim: 0xd8d0c2,
                 roof: 0x55606b, ridge: 0x3f444a, drive: 0xb8b2a6,
                 garage: 0xece5da, trunk: 0x6e5539, leaf: 0x5f8f4e,
                 leafB: 0x527f44 };
    var extG = new T.Group();
    scene.add(extG);
    function ebox(w, h, d, c, x, y, z, opts) {
      return box(w, h, d, c, x, y, z, extG, opts);
    }
    /* the outdoors pays the same tier the kitchen does (user ruling
       2026-09-08): mottled grass, clapboard, offset shingles, jointed
       concrete — canvas-procedural, zero downloads, NICE-gated like the
       wood and marble inside. */
    var grassT = null, sidingT = null, shingleT = null, driveT = null;
    if (NICE) {
      grassT = canvasTex(DETAIL >= 3 ? 512 : 256, function (g, S) {
        g.fillStyle = '#8fae6e'; g.fillRect(0, 0, S, S);
        for (var i = 0; i < S * 3; i++) {
          g.fillStyle = 'rgba(' + (Math.random() < 0.5 ? '110,140,80' : '70,100,55') +
                        ',' + (0.08 + Math.random() * 0.18) + ')';
          g.fillRect(Math.random() * S, Math.random() * S,
                     2 + Math.random() * 3, 2 + Math.random() * 3);
        }
        if (DETAIL >= 3) {
          g.strokeStyle = 'rgba(60,90,50,0.25)'; g.lineWidth = 1;
          for (var b = 0; b < 240; b++) {
            var bx = Math.random() * S, by = Math.random() * S;
            g.beginPath(); g.moveTo(bx, by);
            g.lineTo(bx + (Math.random() - 0.5) * 3, by - 3 - Math.random() * 4);
            g.stroke();
          }
        }
      });
      grassT.wrapS = grassT.wrapT = T.RepeatWrapping;
      grassT.repeat.set(7, 5.5);
      sidingT = canvasTex(256, function (g, S) {
        g.fillStyle = '#e7e0d5'; g.fillRect(0, 0, S, S);
        for (var y = 0; y < S; y += 21) {
          g.fillStyle = 'rgba(110,98,80,0.5)'; g.fillRect(0, y + 18, S, 3);
          g.fillStyle = 'rgba(255,255,255,0.5)'; g.fillRect(0, y, S, 2);
        }
      });
      sidingT.wrapS = sidingT.wrapT = T.RepeatWrapping;
      sidingT.repeat.set(4, 2);
      shingleT = canvasTex(256, function (g, S) {
        g.fillStyle = '#55606b'; g.fillRect(0, 0, S, S);
        var rh = 32;
        for (var r = 0; r < S / rh; r++) {
          var off = (r % 2) ? 32 : 0;
          g.fillStyle = 'rgba(20,24,30,0.5)';
          g.fillRect(0, r * rh + rh - 4, S, 4);
          for (var xx = -1; xx < S / 64 + 1; xx++) {
            g.fillRect(xx * 64 + off, r * rh, 3, rh);
          }
          g.fillStyle = 'rgba(255,255,255,0.06)';
          g.fillRect(0, r * rh, S, 3);
        }
      });
      shingleT.wrapS = shingleT.wrapT = T.RepeatWrapping;
      shingleT.repeat.set(5, 2);
      driveT = canvasTex(256, function (g, S) {
        g.fillStyle = '#b8b2a6'; g.fillRect(0, 0, S, S);
        for (var i = 0; i < 500; i++) {
          g.fillStyle = 'rgba(90,85,75,' + (Math.random() * 0.12) + ')';
          g.fillRect(Math.random() * S, Math.random() * S, 2, 2);
        }
        g.strokeStyle = 'rgba(90,85,75,0.5)'; g.lineWidth = 3;
        [0.33, 0.66].forEach(function (f) {
          g.beginPath(); g.moveTo(0, S * f); g.lineTo(S, S * f); g.stroke();
        });
      });
      driveT.wrapS = driveT.wrapT = T.RepeatWrapping;
      driveT.repeat.set(1, 3);
    }
    /* yard: a grass slab whose top sits just under the kitchen plinth */
    ebox(50, 0.4, 36, NICE ? 0xffffff : EXTC.grass, 0.5, -0.49, 0,
         { rough: 1.0, map: grassT });
    /* facade: siding OUTSIDE the kitchen's two closed walls, up to eaves */
    ebox(15.2, 7.0, 0.3, NICE ? 0xffffff : EXTC.siding, 0.3, 3.5, -5.95,
         { rough: 0.95, map: sidingT });
    ebox(0.3, 7.0, 5.15, NICE ? 0xffffff : EXTC.siding, -7.0, 3.5, -4.025,
         { rough: 0.95, map: sidingT });
    ebox(0.3, 7.0, 2.55, NICE ? 0xffffff : EXTC.siding, -7.0, 3.5, 1.525,
         { rough: 0.95, map: sidingT });
    ebox(0.3, 3.8, 1.7, NICE ? 0xffffff : EXTC.siding, -7.0, 5.1, -0.6,
         { rough: 0.95, map: sidingT });
    ebox(0.3, 7.0, 1.6, NICE ? 0xffffff : EXTC.siding, -7.0, 3.5, 5.2,
         { rough: 0.95, map: sidingT });
    ebox(0.3, 3.6, 1.6, NICE ? 0xffffff : EXTC.siding, -7.0, 5.2, 3.6,
         { rough: 0.95, map: sidingT });
    /* eaves trim */
    ebox(15.6, 0.24, 0.5, EXTC.trim, 0.3, 7.0, -5.95);
    ebox(0.5, 0.24, 13.0, EXTC.trim, -7.0, 7.0, -0.3);
    /* gable roof, BACK HALF ONLY — the front stays open so the exterior
       view still looks down into the kitchen (the dollhouse cutaway).
       Ridge along x at z=-2.0, y=9.2; eaves at y=6.9, z=-6.4. */
    var roofSpan = Math.sqrt(2.3 * 2.3 + 4.4 * 4.4);
    var roof = ebox(16.4, 0.18, roofSpan, NICE ? 0xffffff : EXTC.roof,
                    0.3, 8.05, -4.2, { rough: 0.9, map: shingleT });
    /* NEGATIVE: a +x rotation drops the slab's +z end, and the back slope
       runs NORTH from the ridge — so the sign that makes it descend from
       the ridge cap (z=-2.0, y=9.2) to the eave (z=-6.4, y=6.9) is the
       negative one. The stub below runs the other way and keeps its
       positive sign. */
    roof.rotation.x = -Math.atan2(2.3, 4.4);
    ebox(16.6, 0.26, 0.34, EXTC.ridge, 0.3, 9.24, -2.0);
    /* the FRONT stub slope: the ridge reads as a ridge (both slopes
       present), the cutaway starts just past it */
    var roofStub = ebox(16.4, 0.18, 2.0, NICE ? 0xffffff : EXTC.roof,
                        0.3, 8.78, -1.15, { rough: 0.9, map: shingleT });
    roofStub.rotation.x = Math.atan2(0.85, 1.6);
    ebox(16.5, 0.42, 0.12, EXTC.trim, 0.3, 8.14, -0.28);
    /* left gable end: the triangle under the back slope */
    (function () {
      var s = new T.Shape();
      s.moveTo(-6.4, 6.9); s.lineTo(-2.0, 9.2); s.lineTo(-2.0, 6.9);
      s.lineTo(-6.4, 6.9);
      var m = new T.Mesh(new T.ExtrudeGeometry(s, { depth: 0.3,
        bevelEnabled: false }), mat(EXTC.siding, { rough: 0.95 }));
      m.rotation.y = -Math.PI / 2;   /* shape x-axis lies along world -z */
      m.position.set(-7.0, 0, 0);
      finish(m); extG.add(m);
    })();
    /* garage: opened in H2, moved WEST in the architect pass so the
       mudroom slots between it and the great room. Front pieces + the
       new GABLE roof live in garageDoorG (hidden inside). */
    var garageDoorG = new T.Group();
    var webgl_garageBackWall = null;
    extG.add(garageDoorG);
    var garageInterior = new T.Group();
    extG.add(garageInterior);
    (function () {
      function gtag(m) { if (m) m.userData.room = 'garage'; return m; }
      function itag(m) {
        if (m) { m.userData.room = 'garage'; m.userData.zone = 'garage'; }
        return m;
      }
      gtag(ebox(0.24, 4.6, 8.0, NICE ? 0xffffff : EXTC.garage,
                -18.08, 2.3, 6.0, { rough: 0.95, map: sidingT }));
      gtag(ebox(0.24, 4.6, 8.0, NICE ? 0xffffff : EXTC.garage,
                -12.72, 2.3, 6.0, { rough: 0.95, map: sidingT }));
      var garageBackWall = gtag(ebox(5.6, 4.6, 0.24,
                NICE ? 0xffffff : EXTC.garage,
                -15.4, 2.3, 2.12, { rough: 0.95, map: sidingT }));
      webgl_garageBackWall = garageBackWall;
      gtag(box(5.6, 1.1, 0.24, NICE ? 0xffffff : EXTC.garage,
               -15.4, 4.05, 9.88, garageDoorG,
               NICE ? { rough: 0.95, map: sidingT } : { rough: 0.95 }));
      gtag(box(0.76, 3.5, 0.24, NICE ? 0xffffff : EXTC.garage,
               -17.58, 1.75, 9.88, garageDoorG,
               NICE ? { rough: 0.95, map: sidingT } : { rough: 0.95 }));
      gtag(box(0.76, 3.5, 0.24, NICE ? 0xffffff : EXTC.garage,
               -13.22, 1.75, 9.88, garageDoorG,
               NICE ? { rough: 0.95, map: sidingT } : { rough: 0.95 }));
      gtag(rbox(3.6, 3.0, 0.14, 0.05, EXTC.trim, -15.4, 1.6, 10.02,
                garageDoorG, { rough: 0.85 }));
      if (DETAIL >= 2) {
        gtag(box(3.4, 0.05, 0.06, 0xc4bcae, -15.4, 1.0, 10.1, garageDoorG));
        gtag(box(3.4, 0.05, 0.06, 0xc4bcae, -15.4, 1.8, 10.1, garageDoorG));
        gtag(box(3.4, 0.05, 0.06, 0xc4bcae, -15.4, 2.6, 10.1, garageDoorG));
      }
      if (DETAIL >= 3) {        /* a small window right of the garage door */
        gtag(box(0.86, 0.76, 0.1, EXTC.trim, -13.25, 2.7, 10.04, garageDoorG));
        gtag(box(0.7, 0.6, 0.12, 0x39434e, -13.25, 2.7, 10.05, garageDoorG,
                 GLOSS));
      }
      /* the GABLE: ridge along z, slopes east/west, siding triangles
         front and back — a garage roof that matches the house */
      var gSlope = Math.atan2(1.5, 2.95);
      var gLen = Math.sqrt(1.5 * 1.5 + 2.95 * 2.95) + 0.5;
      var gw = box(gLen, 0.16, 9.0, NICE ? 0xffffff : EXTC.roof,
                   -16.9, 5.6, 6.0, garageDoorG,
                   NICE ? { rough: 0.9, map: shingleT } : { rough: 0.9 });
      gw.rotation.z = gSlope;    /* west slope: HIGH at the ridge, low at
                                    the eave — the sign was inverted, which
                                    made a butterfly roof with a hole into
                                    the bay (invisible until the exterior
                                    camera framed the garage) */
      gtag(gw);
      var ge = box(gLen, 0.16, 9.0, NICE ? 0xffffff : EXTC.roof,
                   -13.9, 5.6, 6.0, garageDoorG,
                   NICE ? { rough: 0.9, map: shingleT } : { rough: 0.9 });
      ge.rotation.z = -gSlope;
      gtag(ge);
      gtag(box(0.34, 0.24, 9.2, EXTC.ridge, -15.4, 6.42, 6.0, garageDoorG));
      (function () {
        var tri = new T.Shape();
        tri.moveTo(-18.3, 4.7); tri.lineTo(-15.4, 6.34); tri.lineTo(-12.5, 4.7);
        tri.lineTo(-18.3, 4.7);
        [10.0, 1.98].forEach(function (tz) {
          var m = new T.Mesh(new T.ExtrudeGeometry(tri, { depth: 0.22,
            bevelEnabled: false }), mat(NICE ? 0xffffff : EXTC.siding,
            NICE ? { rough: 0.95, map: sidingT } : { rough: 0.95 }));
          m.position.set(0, 0, tz);
          gtag(m); finish(m); garageDoorG.add(m);
        });
      })();
      blobShadow(3.0, 4.2, -15.4, 6.0, extG);
      /* interior: wood floor (one floor through the whole house), bench
         wall props */
      var gFloorTex = floorTex.clone();
      gFloorTex.needsUpdate = true;
      gFloorTex.wrapS = gFloorTex.wrapT = T.RepeatWrapping;
      gFloorTex.repeat.set(5.1 / 13, 7.5 / 11);
      var gfloor = new T.Mesh(new T.PlaneGeometry(5.1, 7.5),
        PBR ? new T.MeshStandardMaterial({ map: gFloorTex, roughness: 0.6,
                                           envMapIntensity: 0.1 })
            : new T.MeshLambertMaterial({ map: gFloorTex }));
      gfloor.rotation.x = -Math.PI / 2;
      gfloor.position.set(-15.4, 0.035, 6.0);
      itag(gfloor); finish(gfloor); garageInterior.add(gfloor);
      if (DETAIL >= 2) {
        itag(rbox(2.4, 0.1, 0.7, 0.03, 0xb98c58, -16.0, 1.05, 2.75,
                  garageInterior, { rough: 0.7, map: woodLight }));
        itag(box(0.08, 1.0, 0.08, C.wood2, -17.0, 0.5, 2.55, garageInterior));
        itag(box(0.08, 1.0, 0.08, C.wood2, -15.1, 0.5, 2.55, garageInterior));
        itag(box(0.08, 1.0, 0.08, C.wood2, -17.0, 0.5, 2.95, garageInterior));
        itag(box(0.08, 1.0, 0.08, C.wood2, -15.1, 0.5, 2.95, garageInterior));
      }
      if (DETAIL >= 3) {
        itag(box(2.0, 0.06, 0.5, 0x8a8178, -16.0, 2.6, 2.5, garageInterior));
        itag(cyl(0.11, 0.11, 0.24, C.red, -16.6, 2.75, 2.5, garageInterior, 10));
        itag(cyl(0.11, 0.11, 0.24, C.teal, -16.1, 2.75, 2.5, garageInterior, 10));
        itag(cyl(0.11, 0.11, 0.24, C.orange, -15.6, 2.75, 2.5, garageInterior, 10));
        itag(cyl(0.01, 0.01, 0.8, 0x8a8178, -15.4, 4.2, 6.0, garageInterior, 6));
        var gbulb = new T.Mesh(new T.SphereGeometry(0.13, 10, 8),
          mat(0xffe9b0, { rough: 0.5 }));
        gbulb.position.set(-15.4, 3.75, 6.0);
        itag(gbulb); finish(gbulb); garageInterior.add(gbulb);
      }
      groups.garage = garageInterior;   /* the zone-glow loop lights the room */
    })();
    /* the front path: door to street */
    ebox(2.6, 0.06, 0.9, NICE ? 0xffffff : EXTC.drive, -8.3, -0.24, 12.6,
         { rough: 0.95, map: driveT });
    ebox(0.9, 0.06, 5.2, NICE ? 0xffffff : EXTC.drive, -9.2, -0.24, 15.5,
         { rough: 0.95, map: driveT });
    /* driveway from the garage door to the street */
    ebox(4.4, 0.08, 7.8, NICE ? 0xffffff : EXTC.drive, -15.4, -0.25, 14.3,
         { rough: 0.95, map: driveT });
    /* the street along the yard's front, and its curb */
    var roadT = null;
    if (NICE) {
      roadT = canvasTex(256, function (g, S) {
        g.fillStyle = '#4a4f55'; g.fillRect(0, 0, S, S);
        for (var i = 0; i < 600; i++) {
          g.fillStyle = 'rgba(20,22,26,' + (Math.random() * 0.14) + ')';
          g.fillRect(Math.random() * S, Math.random() * S, 2, 2);
        }
        g.fillStyle = 'rgba(240,230,200,0.8)';
        for (var d = 0; d < S; d += 42) g.fillRect(d, S / 2 - 2, 22, 4);
      });
      roadT.wrapS = roadT.wrapT = T.RepeatWrapping;
      roadT.repeat.set(6, 1);
    }
    ebox(50, 0.38, 5, NICE ? 0xffffff : 0x4a4f55, 0.5, -0.50, 20.5,
         { rough: 0.95, map: roadT });
    ebox(50, 0.1, 0.5, EXTC.trim, 0.5, -0.28, 17.85, { rough: 0.9 });
    /* the school bus, at the curb only while it is actually out */
    var CAR_DARK = 0x22252a;
    var busG = new T.Group();
    busG.visible = false;
    busG.position.set(-5.5, -0.31, 19.8);
    busG.userData.zone = 'curb';
    extG.add(busG);
    (function () {
      function btag(m) { m.userData.zone = 'curb'; finish(m); busG.add(m); return m; }
      var body = new T.Mesh(
        NICE ? roundedGeo(5.4, 1.6, 1.95, 0.12) : new T.BoxGeometry(5.4, 1.6, 1.95),
        mat(0xf2b12e, GLOSS));
      body.position.set(0, 1.15, 0); btag(body);
      var winb = new T.Mesh(new T.BoxGeometry(4.5, 0.5, 1.97),
        mat(0x39434e, GLOSS));
      winb.position.set(-0.2, 1.55, 0); btag(winb);
      var stripe = new T.Mesh(new T.BoxGeometry(5.42, 0.09, 1.96),
        mat(0x1c1c1c, {}));
      stripe.position.set(0, 0.92, 0); btag(stripe);
      [[-1.9, 0.95], [1.9, 0.95], [-1.9, -0.95], [1.9, -0.95]].forEach(function (wp) {
        var wh = new T.Mesh(new T.CylinderGeometry(0.42, 0.42, 0.22, 14),
          mat(CAR_DARK, {}));
        wh.rotation.x = Math.PI / 2;
        wh.position.set(wp[0], 0.42, wp[1]); btag(wh);
      });
      if (DETAIL >= 2) {
        var stop = new T.Mesh(new T.CylinderGeometry(0.2, 0.2, 0.04, 8),
          mat(C.red, GLOSS));
        stop.rotation.x = Math.PI / 2;
        stop.position.set(-1.4, 1.2, 1.05); btag(stop);
      }
      if (DETAIL >= 3) {
        btag(box(0.14, 0.1, 0.1, C.red, -2.6, 2.02, 0.5, busG));
        btag(box(0.14, 0.1, 0.1, C.red, -2.6, 2.02, -0.5, busG));
      }
      groups.curb = busG;
    })();
    /* parametric cars: the family's real records, drawn by shape */
    var CAR_BODIES = {
      sedan:   { L: 3.3, H: 0.5,  W: 1.6,  wheel: 0.3,  cabL: 1.7, cabH: 0.5,  cabOff: -0.1 },
      suv:     { L: 3.5, H: 0.65, W: 1.7,  wheel: 0.36, cabL: 2.1, cabH: 0.6,  cabOff: -0.1 },
      truck:   { L: 3.9, H: 0.6,  W: 1.7,  wheel: 0.38, cabL: 1.3, cabH: 0.62, cabOff: 0.95, bed: true },
      minivan: { L: 3.7, H: 0.62, W: 1.7,  wheel: 0.32, cabL: 2.6, cabH: 0.66, cabOff: 0.05 },
      hatch:   { L: 3.0, H: 0.5,  W: 1.55, wheel: 0.3,  cabL: 1.7, cabH: 0.55, cabOff: -0.3 },
      wagon:   { L: 3.6, H: 0.52, W: 1.6,  wheel: 0.31, cabL: 2.3, cabH: 0.5,  cabOff: -0.15 },
      van:     { L: 3.8, H: 0.85, W: 1.75, wheel: 0.34, cabL: 3.2, cabH: 0.7,  cabOff: 0 }
    };
    var carsG = new T.Group();
    extG.add(carsG);
    function buildCar(c) {
      var p = CAR_BODIES[c.body] || CAR_BODIES.sedan;
      var col = 0x9aa2a9;
      try {
        if (c.color) col = parseInt(String(c.color).replace('#', ''), 16);
        if (!isFinite(col)) col = 0x9aa2a9;
      } catch (e) { col = 0x9aa2a9; }
      var L = Math.min(p.L * 1.25,
        Math.max(p.L * 0.9, p.L * (1 + 0.03 * ((c.seats || 4) - 4))));
      var grp = new T.Group();
      function add(m) {
        m.userData.zone = 'garage'; m.userData.room = 'garage';
        finish(m); grp.add(m); return m;
      }
      var yBody = p.wheel + p.H / 2 - 0.05;
      var body = new T.Mesh(
        NICE ? roundedGeo(p.W, p.H, L, 0.07) : new T.BoxGeometry(p.W, p.H, L),
        mat(col, GLOSS));
      body.position.set(0, yBody, 0);
      add(body);
      var yCab = p.wheel + p.H + p.cabH / 2 - 0.08;
      var cab = new T.Mesh(
        NICE ? roundedGeo(p.W - 0.25, p.cabH, p.cabL, 0.08)
             : new T.BoxGeometry(p.W - 0.25, p.cabH, p.cabL),
        mat(col, GLOSS));
      cab.position.set(0, yCab, p.cabOff);
      add(cab);
      var band = new T.Mesh(
        new T.BoxGeometry(p.W - 0.18, p.cabH * 0.5, Math.max(0.4, p.cabL - 0.35)),
        mat(0x39434e, GLOSS));
      band.position.set(0, yCab + 0.03, p.cabOff);
      add(band);
      if (p.bed) {
        var bedFront = p.cabOff - p.cabL / 2 - 0.08;
        var bedBack = -L / 2 + 0.12;
        var bedLen = bedFront - bedBack;
        var yRail = p.wheel + p.H + 0.12;
        add(new T.Mesh(new T.BoxGeometry(p.W - 0.2, 0.26, 0.07),
          mat(col, GLOSS))).position.set(0, yRail, bedBack + 0.04);
        add(new T.Mesh(new T.BoxGeometry(0.07, 0.26, bedLen),
          mat(col, GLOSS))).position.set(-(p.W / 2 - 0.14), yRail,
                                          bedBack + bedLen / 2);
        add(new T.Mesh(new T.BoxGeometry(0.07, 0.26, bedLen),
          mat(col, GLOSS))).position.set(p.W / 2 - 0.14, yRail,
                                         bedBack + bedLen / 2);
      }
      [[-1, 1], [1, 1], [-1, -1], [1, -1]].forEach(function (wp) {
        var wh = new T.Mesh(
          new T.CylinderGeometry(p.wheel, p.wheel, 0.16, DETAIL >= 3 ? 14 : 10),
          mat(CAR_DARK, {}));
        wh.rotation.z = Math.PI / 2;
        wh.position.set(wp[0] * (p.W / 2 - 0.02), p.wheel,
                        wp[1] * (L / 2 - p.wheel * 1.5));
        add(wh);
        if (DETAIL >= 2) {
          var hub = new T.Mesh(new T.CylinderGeometry(p.wheel * 0.45,
            p.wheel * 0.45, 0.17, 10), mat(C.steel, CHROME));
          hub.rotation.z = Math.PI / 2;
          hub.position.copy(wh.position);
          add(hub);
        }
      });
      if (DETAIL >= 3) {
        add(box(0.16, 0.09, 0.05, 0xfff3c4, -p.W / 4, yBody + 0.08, L / 2 + 0.01, grp, GLOSS));
        add(box(0.16, 0.09, 0.05, 0xfff3c4, p.W / 4, yBody + 0.08, L / 2 + 0.01, grp, GLOSS));
        add(box(0.16, 0.09, 0.05, C.red, -p.W / 4, yBody + 0.08, -L / 2 - 0.01, grp, GLOSS));
        add(box(0.16, 0.09, 0.05, C.red, p.W / 4, yBody + 0.08, -L / 2 - 0.01, grp, GLOSS));
      }
      if (!SHADOWS) {
        var sh = new T.Mesh(new T.CircleGeometry(1, 16),
          new T.MeshBasicMaterial({ color: C.shadow, transparent: true,
                                    opacity: 0.16 }));
        sh.rotation.x = -Math.PI / 2;
        sh.scale.set(p.W * 0.62, L * 0.52, 1);
        sh.position.set(0, 0.012, 0);
        grp.add(sh);
      }
      return grp;
    }
    /* ---- MUDROOM (architect pass): BETWEEN the garage and the great
       room, an open doorway from the kitchen, the leave-door on its
       street-side wall with the driveway right outside. ---- */
    var mudroomRoofG = new T.Group();
    extG.add(mudroomRoofG);
    var mudBagsG = new T.Group();
    scene.add(mudBagsG);
    (function () {
      function mtag(m) { if (m) m.userData.room = 'mudroom'; return m; }
      var mFloorTex = floorTex.clone();
      mFloorTex.needsUpdate = true;
      mFloorTex.wrapS = mFloorTex.wrapT = T.RepeatWrapping;
      mFloorTex.repeat.set(5.8 / 13, 5.6 / 11);
      var mfloor = new T.Mesh(new T.PlaneGeometry(5.8, 5.6),
        PBR ? new T.MeshStandardMaterial({ map: mFloorTex, roughness: 0.55,
                                           envMapIntensity: 0.1 })
            : new T.MeshLambertMaterial({ map: mFloorTex }));
      mfloor.rotation.x = -Math.PI / 2;
      mfloor.position.set(-9.7, 0.03, 5.4);
      mtag(mfloor); finish(mfloor); extG.add(mfloor);
      mtag(ebox(5.6, 4.2, 0.24, NICE ? 0xffffff : EXTC.siding,
                -9.8, 2.1, 2.48, { rough: 0.95, map: sidingT }));
      /* the street end is the mudroom's "garage door": hidden from the
         inside so the camera can look straight into the room */
      var mudFrontWall = mtag(ebox(5.6, 4.2, 0.24, NICE ? 0xffffff : EXTC.siding,
                -9.8, 2.1, 8.32, { rough: 0.95, map: sidingT }));
      mudroomRoofG.add(mudFrontWall);
      var mroof = box(5.9, 0.14, 6.2, NICE ? 0xffffff : EXTC.roof,
                      -9.8, 4.5, 5.4, mudroomRoofG,
                      NICE ? { rough: 0.9, map: shingleT } : { rough: 0.9 });
      mtag(mroof);
      /* bench + hooks on the NORTH wall: they face the camera coming in
         from the south-east */
      mtag(rbox(2.4, 0.1, 0.5, 0.03, 0xb98c58, -10.6, 0.52, 2.95, extG,
                { rough: 0.7, map: woodLight }));
      mtag(box(0.06, 0.5, 0.06, C.wood2, -11.6, 0.26, 2.78, extG));
      mtag(box(0.06, 0.5, 0.06, C.wood2, -9.6, 0.26, 2.78, extG));
      mtag(box(0.06, 0.5, 0.06, C.wood2, -11.6, 0.26, 3.12, extG));
      mtag(box(0.06, 0.5, 0.06, C.wood2, -9.6, 0.26, 3.12, extG));
      if (DETAIL >= 3) {
        mtag(box(0.1, 0.1, 0.1, C.wood2, -11.4, 2.5, 2.66, extG));
        mtag(box(0.1, 0.1, 0.1, C.wood2, -10.6, 2.5, 2.66, extG));
        mtag(box(0.1, 0.1, 0.1, C.wood2, -9.8, 2.5, 2.66, extG));
        mtag(rbox(0.5, 0.85, 0.24, 0.06, C.teal, -10.6, 2.0, 2.80, extG,
                  { rough: 0.9 }));
      }
      blobShadow(2.9, 2.8, -9.7, 5.4, extG);
    })();
    var livingRoofG = new T.Group();   /* open-concept: nothing to hide */
    extG.add(livingRoofG);
    /* two blob trees + a bush: the yard is a place, not a void. They
       live in yardG so an INTERIOR camera can hide them — a tree that
       crosses the near plane eats a third of the garage shot. */
    var yardG = new T.Group();
    extG.add(yardG);
    function tree(x, z, s) {
      cyl(0.16 * s, 0.22 * s, 1.4 * s, EXTC.trunk, x, 0.7 * s, z, yardG, 8);
      var lv = new T.Mesh(new T.SphereGeometry(1.1 * s, DETAIL >= 3 ? 14 : 10,
                                               DETAIL >= 3 ? 10 : 8),
        mat(EXTC.leaf, { rough: 1.0 }));
      lv.position.set(x, 2.0 * s, z); finish(lv); yardG.add(lv);
      var lv2 = new T.Mesh(new T.SphereGeometry(0.75 * s, 10, 8),
        mat(EXTC.leafB, { rough: 1.0 }));
      lv2.position.set(x + 0.7 * s, 1.6 * s, z + 0.3 * s);
      finish(lv2); yardG.add(lv2);
      if (DETAIL >= 3) {
        var lv3 = new T.Mesh(new T.SphereGeometry(0.55 * s, 10, 8),
          mat(EXTC.leaf, { rough: 1.0 }));
        lv3.position.set(x - 0.55 * s, 1.5 * s, z - 0.25 * s);
        finish(lv3); yardG.add(lv3);
      }
      blobShadow(1.25 * s, 1.1 * s, x, z, yardG);
    }
    tree(-20.5, 12.5, 1.4); tree(17.5, -6.0, 1.1);
    var bush = new T.Mesh(new T.SphereGeometry(0.7, 10, 8),
      mat(EXTC.leafB, { rough: 1.0 }));
    bush.position.set(9.6, 0.4, 9.0); finish(bush); yardG.add(bush);
    blobShadow(0.8, 0.7, 9.6, 9.0, yardG);
    /* sky dome: weather-painted from the inside, swapped by applyState.
       The dome IS the background now, so the flat clear color retires. */
    var skyDome = new T.Mesh(new T.SphereGeometry(80, 24, 12),
      new T.MeshBasicMaterial({ side: T.BackSide }));
    skyDome.rotation.y = Math.PI / 4;   /* UV seam behind the house, not the camera */
    extG.add(skyDome);
    scene.background = null;

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
      if (p && p.__blank) {
        return mkTex('critters', 512, 324, 'blank', function (g, w, h) {
          g.fillStyle = '#12151c'; g.fillRect(0, 0, w, h);
          g.fillStyle = '#1d2230'; g.fillRect(0, 0, w, 64);
          g.fillStyle = '#7ee787'; g.font = '800 34px ' + FONT;
          g.fillText('CRITTERS', 26, 44);
        });
      }
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
    function weatherTex(wz) {
      var cond = (wz && wz.cond) || '';
      var temp = (wz && wz.temp !== null && wz.temp !== undefined)
        ? Math.round(wz.temp) : null;
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
    function skyDomeTex(wz) {
      var cond = (wz && wz.cond) || '';
      var hour = new Date().getHours();
      var night = hour < 7 || hour >= 19;
      var payload = ['dome', cond, night].join('|');
      return mkTex('skydome', 512, 256, payload, function (g, w, h) {
        var top = '#7cc4f0', bot = '#d8ecf7';
        if (night) { top = '#1c2748'; bot = '#3a4a78'; }
        else if (cond.indexOf('rain') !== -1 || cond === 'pouring' ||
                 cond.indexOf('lightning') !== -1) { top = '#5b6c7d'; bot = '#8fa0af'; }
        else if (cond.indexOf('snow') !== -1) { top = '#aebfd0'; bot = '#e8eef4'; }
        else if (cond.indexOf('cloud') !== -1 || cond === 'fog') { top = '#8fb0c6'; bot = '#cfdde8'; }
        var grad = g.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, top); grad.addColorStop(0.75, bot);
        grad.addColorStop(1, bot);
        g.fillStyle = grad; g.fillRect(0, 0, w, h);
        if (night) {
          g.fillStyle = 'rgba(255,255,255,0.9)';
          for (var st = 0; st < 40; st++) {
            g.fillRect(((st * 131) % w), ((st * 67) % (h * 0.55)), 3, 3);
          }
        }
        if (!night && cond.indexOf('cloud') === -1 && cond !== 'fog' &&
            cond.indexOf('rain') === -1 && cond.indexOf('snow') === -1) {
          g.fillStyle = 'rgba(255,240,200,0.5)';
          g.beginPath(); g.arc(w * 0.68, h * 0.3, 26, 0, 7); g.fill();
        }
        if (!night && DETAIL >= 2 && cond !== 'fog') {
          g.fillStyle = 'rgba(255,255,255,' +
            (cond.indexOf('cloud') !== -1 ? 0.75 : 0.5) + ')';
          [[0.16, 0.34], [0.46, 0.24], [0.78, 0.4]].forEach(function (pc) {
            var cx = w * pc[0], cy = h * pc[1];
            g.beginPath();
            g.arc(cx - 22, cy, 13, 0, 7); g.arc(cx, cy - 9, 17, 0, 7);
            g.arc(cx + 22, cy, 13, 0, 7); g.fill();
            g.fillRect(cx - 22, cy - 2, 44, 14);
          });
        }
        g.fillStyle = night ? 'rgba(20,28,56,0.55)' : 'rgba(255,255,255,0.35)';
        g.fillRect(0, h * 0.82, w, h * 0.18);   /* horizon haze */
      });
    }
    function carTex(c) {
      var payload = [c.name, c.battery_pct, c.fuel_pct, c.warn].join('|');
      return mkTex('car:' + (c.id || c.name), 256, 128, payload,
                   function (g, w, h) {
        g.clearRect(0, 0, w, h);
        card(g, 6, 6, w - 12, h - 12, c.warn ? '#dc2626' : '#0d9488');
        g.fillStyle = '#111827'; g.font = '800 26px ' + FONT;
        g.fillText(String(c.name || 'Car').slice(0, 12), 26, 44);
        var lvl = (c.battery_pct !== null && c.battery_pct !== undefined)
          ? c.battery_pct : c.fuel_pct;
        if (lvl !== null && lvl !== undefined) {
          g.fillStyle = '#e5e7eb'; rr(g, 26, 64, w - 64, 22, 10); g.fill();
          g.fillStyle = c.warn ? '#dc2626' : '#0d9488';
          rr(g, 26, 64, Math.max(14, (w - 64) * Math.min(1, lvl / 100)), 22, 10);
          g.fill();
          g.fillStyle = '#374151'; g.font = '700 20px ' + FONT;
          g.fillText(Math.round(lvl) + '%', w - 58, 82);
        } else {
          g.fillStyle = '#6b7280'; g.font = '500 20px ' + FONT;
          g.fillText('resting', 26, 80);
        }
      });
    }
    function clearPaint() { texCache = {}; }

    return {
      T: T, scene: scene, cam: cam, R: R, groups: groups,
      steam: steam, steam2: steam2, needle: needle, plaque: plaque,
      calFace: calFace, boardFace: boardFace, magnets: magnets,
      /* boardFace stays exported: the overlay quad rides its plane */
      critFace: critFace, critterTex: critterTex, pendants: pendants,
      radioFace: radioFace, fridgeDoorTop: fridgeDoorTop,
      paneMesh: paneMesh, heroTex: heroTex, calendarTex: calendarTex,
      weatherTex: weatherTex, clearPaint: clearPaint,
      extG: extG, skyDome: skyDome, skyDomeTex: skyDomeTex,
      garageDoorG: garageDoorG, garageInterior: garageInterior,
      pantryJars: pantryJars, pantryDoor: pantryDoor,
      garageBackWall: webgl_garageBackWall,
      carsG: carsG, busG: busG, buildCar: buildCar, carTex: carTex,
      HOME_POS: HOME_POS, HOME_AT: HOME_AT,
      EXT_POS: EXT_POS, EXT_AT: EXT_AT,
      GARAGE_POS: GARAGE_POS, GARAGE_AT: GARAGE_AT,
      MUD_POS: MUD_POS, MUD_AT: MUD_AT, LIV_POS: LIV_POS, LIV_AT: LIV_AT,
      mudroomRoofG: mudroomRoofG, livingRoofG: livingRoofG,
      yardG: yardG, westWallG: westWallG,
      mudBagsG: mudBagsG
    };
  }

  /* ---- render-on-demand engine ---------------------------------------- */
  var state = null;
  var focused = null;        // zone key while leaned in
  var mode = 'exterior';     // 'exterior' | 'kitchen'
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
    webgl.magnets.visible = focused !== 'fridge';
    /* leaned in, the pendants get out of the sightline entirely */
    if (webgl.pendants) webgl.pendants.visible = !focused;
    swap(webgl.plaque, webgl.heroTex(s.door || {}));
    swap(webgl.calFace, webgl.calendarTex(
      focused === 'calendar' ? { __blank: true } : (s.calendar || {})));
    /* leaned in, the pantry door steps aside to show the shelves */
    if (webgl.pantryDoor) webgl.pantryDoor.visible = focused !== 'board';
    /* the pantry's honesty: a long list empties the shelves */
    var stocked = Math.max(0, 8 - Math.min(8, (s.board || {}).items || 0));
    webgl.pantryJars.forEach(function (jar, ji) {
      jar.visible = ji < stocked;
    });
    swap(webgl.critFace, webgl.critterTex(
      focused === 'pet' ? { __blank: true } : (s.pet || {})));
    swap(webgl.paneMesh, webgl.weatherTex(s.window || {}));
    swap(webgl.skyDome, webgl.skyDomeTex(s.window || {}));
    syncGarage(s);
    syncMudroom(s);

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

  /* ---- the garage floor plan: cars rebuilt only when their payload
     changes. Two present cars park inside (with a status plaque on the
     back wall); the rest line the driveway; an absent car is simply not
     built — the empty spot IS the feature. ---- */
  var garagePayload = null;
  function syncGarage(s) {
    if (!webgl) return;
    var g = s.garage || {};
    var cars = g.cars || [];
    var key = JSON.stringify(cars.map(function (c) {
      return [c.id, c.name, c.color, c.body, c.seats, c.present, c.warn,
              c.battery_pct, c.fuel_pct];
    }));
    if (key !== garagePayload) {
      garagePayload = key;
      while (webgl.carsG.children.length)
        webgl.carsG.remove(webgl.carsG.children[0]);
      var inside = 0, outside = 0;
      cars.forEach(function (c) {
        if (!c.present) return;
        var grp = webgl.buildCar(c);
        if (inside < 2) {
          grp.position.set(inside === 0 ? -16.7 : -14.1, 0, 5.6);
          var plate = new webgl.T.Mesh(new webgl.T.PlaneGeometry(1.5, 0.75),
            new webgl.T.MeshBasicMaterial({ transparent: true,
                                            map: webgl.carTex(c) }));
          plate.position.set(grp.position.x, 3.3, 2.4);   /* garage back wall */
          plate.userData.zone = 'garage';
          webgl.carsG.add(plate);
          inside++;
        } else {
          grp.position.set(-15.4, 0, 12.6 + outside * 4.6);
          outside++;
        }
        webgl.carsG.add(grp);
      });
    }
    if (webgl.busG) webgl.busG.visible = !!((s.curb || {}).bus);
  }

  /* backpacks on the mudroom bench: one per child, rebuilt on count change */
  var bagCount = null;
  var BAG_COLORS = [0xc9473d, 0x3fbdb2, 0xe09a3e, 0x5a7fc0];
  var BAG_SPOTS = [[-11.3, 0.87, 2.95], [-9.9, 0.87, 2.95],
                   [-11.6, 0.31, 3.65], [-9.6, 0.31, 3.65]];
  function syncMudroom(s) {
    if (!webgl) return;
    var n = Math.min(4, ((s.mudroom || {}).bags || 0));
    if (n === bagCount) return;
    bagCount = n;
    while (webgl.mudBagsG.children.length)
      webgl.mudBagsG.remove(webgl.mudBagsG.children[0]);
    for (var i = 0; i < n; i++) {
      var bag = new webgl.T.Group();
      var body = new webgl.T.Mesh(new webgl.T.BoxGeometry(0.34, 0.5, 0.26),
        new webgl.T.MeshLambertMaterial({ color: BAG_COLORS[i % 4] }));
      var flap = new webgl.T.Mesh(new webgl.T.BoxGeometry(0.36, 0.2, 0.28),
        new webgl.T.MeshLambertMaterial({ color: 0x3a3330 }));
      flap.position.y = 0.18;
      bag.add(body); bag.add(flap);
      bag.position.set(BAG_SPOTS[i][0], BAG_SPOTS[i][1], BAG_SPOTS[i][2]);
      bag.userData.room = 'mudroom';
      webgl.mudBagsG.add(bag);
    }
  }

  /* ---- focus-then-through (lean-in; card zones approach FACE-ON) ------- */
  /* Which mesh/axis carries a zone's card face — shared by the framing
     (approach along the normal, so the pasted card is seen square) and by
     the quad the page layer maps onto. */
  var FACE_MESH_MAP = { window: 'paneMesh', pet: 'critFace',
                        calendar: 'calFace', board: 'boardFace',
                        radio: 'radioFace', fridge: 'fridgeDoorTop',
                        door: 'plaque' };   /* frame the CARD, not the slab —
                        the whole-door span forces a 15-unit approach that
                        lands outside the mudroom's walls */
  var FACE_AXIS_MAP = { fridge: ['z', 1], board: ['x', 1], counter: ['z', 1],
                        pet: ['z', 1], radio: ['z', 1], door: ['z', 1] };

  function zoneFaceNormal(key) {
    if (!webgl) return null;
    var fmesh = FACE_MESH_MAP[key] && webgl[FACE_MESH_MAP[key]];
    if (fmesh && fmesh.getWorldQuaternion) {
      /* a plane's front is its local +z; the cork face's rotation carries
         it to +x, the laptop screen's tilt carries it up-forward */
      return new webgl.T.Vector3(0, 0, 1)
        .applyQuaternion(fmesh.getWorldQuaternion(new webgl.T.Quaternion()));
    }
    var o = FACE_AXIS_MAP[key];
    if (!o) return null;
    var v = new webgl.T.Vector3();
    v[o[0]] = o[1];
    return v;
  }

  function frameZone(key, cb) {
    var g = webgl.groups[key];
    var fmesh = FACE_MESH_MAP[key] && webgl[FACE_MESH_MAP[key]];
    var boxb = new webgl.T.Box3().setFromObject(fmesh || g);
    var center = boxb.getCenter(new webgl.T.Vector3());
    var size3 = boxb.getSize(new webgl.T.Vector3());
    var span = Math.max(size3.x, size3.y, size3.z);
    var dist = (span / 2) / Math.tan((webgl.cam.fov / 2) * Math.PI / 180) * 1.45 + 0.8;
    /* a zone with a card face is approached ALONG that face's normal (a
       touch of height mixed in so the room keeps its depth): an oblique
       wall card reads as a misaligned web element; a square one reads as
       part of the surface */
    var fn = zoneFaceNormal(key);
    var dir = fn
      ? fn.clone().add(new webgl.T.Vector3(0, 0.22, 0)).normalize()
      : new webgl.T.Vector3().subVectors(webgl.cam.position, center).normalize();
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
  /* ---- ROOMS: every room is a camera home; some hide a group while
     the camera is inside (the dollhouse trick). Zone keys map to the
     room that owns them; unmapped zones belong to the kitchen. ---- */
  function roomsReg() {
    return {
      kitchen: { pos: webgl.HOME_POS, at: webgl.HOME_AT,
                 hide: webgl.yardG },
      garage:  { pos: webgl.GARAGE_POS, at: webgl.GARAGE_AT,
                 hide: [webgl.garageDoorG, webgl.yardG] },
      mudroom: { pos: webgl.MUD_POS, at: webgl.MUD_AT,
                 hide: [webgl.mudroomRoofG, webgl.westWallG, webgl.yardG] },
      living:  { pos: webgl.LIV_POS, at: webgl.LIV_AT,
                 hide: [webgl.livingRoofG, webgl.yardG] }
    };
  }
  var ZONE_ROOM = { garage: 'garage', curb: null,
                    door: 'mudroom', radio: 'living', pet: 'living' };
  function zoneRoom(key) {
    var r = ZONE_ROOM[key];
    return r === undefined ? 'kitchen' : r;
  }
  function enterRoom(name, cb) {
    var rooms = roomsReg();
    var room = rooms[name];
    if (!room) { if (cb) cb(); return; }
    if (mode === name) { if (cb) cb(); return; }
    mode = name;
    Object.keys(rooms).forEach(function (k) {
      var h = rooms[k].hide;
      if (!h) return;
      (Array.isArray(h) ? h : [h]).forEach(function (g) {
        g.visible = true;
      });
    });
    var act = room.hide;
    if (act) (Array.isArray(act) ? act : [act]).forEach(function (g) {
      g.visible = false;
    });
    tween = { fromP: webgl.cam.position.clone(), toP: room.pos.clone(),
              fromA: (lookAt || webgl.EXT_AT).clone(), toA: room.at.clone(),
              t0: performance.now(), ms: 850, cb: cb || null };
    requestFrame();
  }
  function goExterior() {
    mode = 'exterior';
    focused = null;
    TIP.style.opacity = 0;
    var rooms = roomsReg();
    Object.keys(rooms).forEach(function (k) {
      var h = rooms[k].hide;
      if (!h) return;
      (Array.isArray(h) ? h : [h]).forEach(function (g) {
        g.visible = true;
      });
    });
    announceFocus(null);
    tween = { fromP: webgl.cam.position.clone(), toP: webgl.EXT_POS.clone(),
              fromA: (lookAt || webgl.HOME_AT).clone(),
              toA: webgl.EXT_AT.clone(),
              t0: performance.now(), ms: 850, cb: null };
    requestFrame();
  }
  function inExterior(obj) {
    var o = obj;
    while (o) { if (o === webgl.extG) return true; o = o.parent; }
    return false;
  }
  function anyHit(clientX, clientY) {
    var rect = webgl.R.domElement.getBoundingClientRect();
    var v = new webgl.T.Vector2(((clientX - rect.left) / rect.width) * 2 - 1,
                                -((clientY - rect.top) / rect.height) * 2 + 1);
    var ray = new webgl.T.Raycaster();
    ray.setFromCamera(v, webgl.cam);
    var hits = ray.intersectObjects(webgl.scene.children, true);
    return hits.length ? hits[0].object : null;
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

    /* the camera-facing face across the box's THINNEST axis — except for
       props where that guess is wrong (a fridge is deep, a laptop's screen
       tilts): those name their outward face explicitly */
    /* Some zones name the exact MESH their card sits on: the window's
       glass (the zone bbox is dominated by the valance) and the laptop's
       tilted screen (an axis-aligned bbox face floats in front of it).
       A PlaneGeometry's four corners, world-transformed, give the TRUE
       quad — tilt included. */
    var fm = FACE_MESH_MAP[key] && webgl[FACE_MESH_MAP[key]];
    if (fm && !(fm.geometry && fm.geometry.parameters
                && fm.geometry.parameters.width)) {
      /* no clean plane params (rounded/extruded door): the face is still
         THAT mesh's box, not the whole prop's */
      b = new webgl.T.Box3().setFromObject(fm);
      fm = null;
    }
    if (fm) {
      fm.updateWorldMatrix(true, false);
      var pw = fm.geometry.parameters.width / 2;
      var ph = fm.geometry.parameters.height / 2;
      var pq = [], pbad = false;
      [[-pw, ph], [pw, ph], [pw, -ph], [-pw, -ph]].forEach(function (uv) {
        var v3 = new webgl.T.Vector3(uv[0], uv[1], 0)
          .applyMatrix4(fm.matrixWorld);
        var pp = _project(v3, w, h);
        if (pp.z > 1 || pp.z < -1) pbad = true;
        pq.push(pp);
      });
      if (!pbad) {
        pq.sort(function (a, b2) { return a.y - b2.y; });
        var ptop = pq.slice(0, 2).sort(function (a, b2) { return a.x - b2.x; });
        var pbot = pq.slice(2, 4).sort(function (a, b2) { return a.x - b2.x; });
        return { rect: rect, quad: [ptop[0], ptop[1], pbot[1], pbot[0]] };
      }
    }
    var size = b.getSize(new webgl.T.Vector3());
    var c = b.getCenter(new webgl.T.Vector3());
    var ovr = FACE_AXIS_MAP[key];
    var axis = ovr ? ovr[0]
             : (size.x <= size.y && size.x <= size.z) ? 'x'
             : (size.y <= size.z ? 'y' : 'z');
    var toCam = new webgl.T.Vector3().subVectors(webgl.cam.position, c);
    var fixed = ovr ? (ovr[1] > 0 ? b.max[axis] : b.min[axis])
              : (toCam[axis] >= 0 ? b.max[axis] : b.min[axis]);
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
    var target = zoneRoom(key);
    if (target === null) return;   /* exterior-only zones have no lean-in */
    enterRoom(target, function () {
      focused = key;
      announceFocus(null);
      frameZone(key, function () { announceFocus(key); });
    });
  };
  window.chfHouseEnter = function () { if (webgl) enterRoom('kitchen', null); };
  window.chfHouseEnterGarage = function () { if (webgl) enterRoom('garage', null); };
  window.chfHouseEnterRoom = function (name) { if (webgl) enterRoom(name, null); };
  window.chfHouseExit = function () { if (webgl) goExterior(); };
  /* the studio's viewfinder: snap the camera anywhere and repaint once.
     Read-only like its siblings — it moves the eye, nothing else. Set
     builders frame a room through this before they hard-code the pose. */
  window.chfHouseCam = function (px, py, pz, ax, ay, az) {
    if (!webgl) return;
    tween = null;
    webgl.cam.position.set(px, py, pz);
    lookAt = new webgl.T.Vector3(ax, ay, az);
    webgl.cam.lookAt(lookAt);
    requestFrame();
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
    if (!webgl) return;
    if (mode === 'exterior') {
      /* any tap on the HOUSE goes inside — routed by room tag: the
         garage's meshes carry userData.room='garage', everything else
         is the kitchen. Sky and flat yard stay a view. */
      var hit = anyHit(ev.clientX, ev.clientY);
      if (!hit || hit === webgl.skyDome) return;
      var o = hit, room = null;
      while (o) {
        if (o.userData && o.userData.room) { room = o.userData.room; break; }
        o = o.parent;
      }
      if (room && roomsReg()[room]) { enterRoom(room, null); return; }
      if (!inExterior(hit) || hit.position.y > 0.2) enterRoom('kitchen', null);
      return;
    }
    var key = zoneAt(ev.clientX, ev.clientY);
    /* a ray that slips past a wall must not lean into another room */
    if (key && zoneRoom(key) !== mode) key = null;
    if (!key) {
      /* the kitchen keeps its two-step walk-out; small rooms exit direct */
      if (mode === 'kitchen' && focused) { goHome(); return; }
      goExterior();
      return;
    }
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
    fetch(window.HOUSE_STATE_URL + '?since=' + encodeURIComponent(sinceEpoch),
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
  try { webgl = buildRoom(); } catch (e) {
    webgl = null;
    /* the fallback is designed, but a BUILD failure must never be
       silent — that is how a broken room masquerades as weak hardware */
    if (window.console && console.error) console.error('[house] buildRoom failed:', e);
  }
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
