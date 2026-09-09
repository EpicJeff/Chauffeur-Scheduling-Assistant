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
    /* the kitchen: pulled in and centred on the run after the studio
       pass filled the room — the old pose spent a third of the frame on
       the living room's edge and the yard (bible S5.1, S7.1) */
    var HOME_POS = new T.Vector3(16.0, 12.0, 16.0);
    var HOME_AT = new T.Vector3(0.4, 1.3, -0.7);
    /* the house from the yard: the panel's resting view. The old pose
       aimed a metre off the ground and spent the bottom-left fifth of
       the frame on tarmac; raised and swung a little north it crops the
       road to a corner and the house and its garden fill the frame
       (bible S5.1). */
    var EXT_POS = new T.Vector3(41.0, 25.5, 39.0);
    var EXT_AT = new T.Vector3(-4.8, 2.9, 3.6);
    /* the garage from its own doorway (roof + front hidden inside).
       The old pose spent half the frame's width on grass and the
       neighbouring roof and cut the bay off at the cars' noses. Lower
       (27 deg, not 32) and aimed a metre and a half deeper into the
       bay, the whole room fits: the back wall with its plaques clear of
       the nav bar, the long wall down the left, and the floor in front
       of the cars where the clutter lives (bible S5.1) */
    var GARAGE_POS = new T.Vector3(-14.05, 9.6, 21.3);
    var GARAGE_AT = new T.Vector3(-15.45, 1.75, 6.05);
    /* the mudroom: the old pose put the street door's BACK across the
       left third of the frame (the wall it hangs in is cut away, the
       slab is not) and showed no west wall at all. Swung east and in,
       the door shrinks to a sliver at the very edge — still tappable,
       which is the whole point of it — and the frame becomes the closed
       north-west corner: garage door left, bench and hooks right
       (bible S5.0/S5.1) */
    var MUD_POS = new T.Vector3(-3.4, 6.2, 11.2);
    var MUD_AT = new T.Vector3(-11.4, 1.7, 4.2);
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
      /* TONE MAPPING (lighting pass). ACES lived here, and it was the
         reason the high tier read PALER and FLATTER than medium: three's
         filmic fit pre-scales by 1/0.6, which LIFTS the midtones, and its
         output matrix desaturates the top end. An authored armchair orange
         (0.82, 0.50, 0.25) came back as (0.82, 0.71, 0.48) - cream. It also
         lifted every dark anchor, which is why `ink` drifted olive.
         Colour management is OFF in this three build, so the shading maths
         already runs in display space: there is no linear HDR for a filmic
         curve to tone-map, only authored hexes to distort. LINEAR is
         identity, and with the light budget below (fill + key summing to
         ~0.9 square to the sun, pools taking the lit patches to ~1.05) the
         only thing that clips is a specular highlight, which is where the
         plates put their white too. */
      R.toneMapping = T.LinearToneMapping;
      R.toneMappingExposure = 1.0;
      /* no sRGB output pass: the legacy three build has color management
         off, so the extra encode only bleaches every authored color */
    }
    if (SHADOWS) {
      R.shadowMap.enabled = true;
      R.shadowMap.type = T.PCFSoftShadowMap;
      /* the shadow map obeys the same law the frame loop does. Nothing in
         this scene moves under its own power, and the sun never travels,
         so redrawing the depth pass on every tween frame is pure waste -
         and once the yard casts too, that waste is ~700 extra meshes 50
         times per camera move. It is marked dirty where the world can
         actually change: aimShadow (the box moved) and applyState (the
         only path that adds, removes or hides anything). */
      R.shadowMap.autoUpdate = false;
      R.shadowMap.needsUpdate = true;
    }
    ROOT.appendChild(R.domElement);

    /* ---- the rig: one budget, three tiers ------------------------------
       COOL FILL, WARM KEY. The old rig was warm everywhere (hemisphere
       ground 0xb8926a, ambient 0xfff4e6, sun 0xfff1dc) and summed past 1.6
       on a lit face, so nothing could be dark and nothing could be neutral:
       `ink` came back olive-brown on the tyres and the TV, and every
       authored hue drowned. Now the fill is DAYLIGHT-COOL and only the key
       is warm, which is the plates' whole read - warm light against a cool
       surround - and it is what lets a near-black stay near-black.

       The budget is shared across tiers ON PURPOSE: a panel that demotes
       itself from high to medium must not change colour, only fidelity.
       Square to the key, fill + key lands near 0.90; the room pools
       (below, and the baked gradients in the floor textures) carry the lit
       patches the rest of the way to ~1.05. Fully shaded sits near 0.40. */
    /* one clock for the whole scene: the sky dome and the rig must never
       disagree about whether it is dark out */
    function isNight() {
      var h = new Date().getHours();
      return h < 7 || h >= 19;
    }
    var SKY_C = 0xcbdcf2, GND_C = 0x9a8b74, SUN_C = 0xfff0d6;
    var HEMI_I = PBR ? 0.34 : (DETAIL >= 2 ? 0.44 : 0.52);
    var AMB_I = PBR ? 0.05 : (DETAIL >= 2 ? 0.10 : 0.16);
    var SUN_I = PBR ? 0.56 : (DETAIL >= 2 ? 0.50 : 0.46);
    /* Lambert takes hemisphere irradiance too: medium and low get the same
       cool-over-warm gradient the high tier does, for one uniform */
    var hemi = new T.HemisphereLight(SKY_C, GND_C, HEMI_I);
    scene.add(hemi);
    var amb = new T.AmbientLight(PBR ? 0xdfe6f0 : 0xe4eaf2, AMB_I);
    scene.add(amb);
    var sun = new T.DirectionalLight(SUN_C, SUN_I);
    scene.add(sun);
    if (SHADOWS) {
      sun.castShadow = true;
      sun.shadow.mapSize.set(2048, 2048);
    }
    /* the wide exterior box gets a bigger map so the resting view - the one
       the panel actually sits on - keeps the interiors' shadow detail. It is
       affordable BECAUSE the depth pass is now on demand: one extra pass per
       room change, never per frame. Capped by the driver's own limit. */
    var SHADOW_HI = Math.min(4096, (R.capabilities && R.capabilities.maxTextureSize) || 2048);

    /* ---- THE SHADOW FRUSTUM, ONE BOX PER VIEW (bible S5.2) -------------
       The documented bug: a single +/-10 orthographic box pinned to the
       house. Anything outside it - the garage bay, the driveway, the kerb,
       the whole garden - either got no shadow or straddled the edge, and
       three returns "fully lit" outside a shadow frustum, so the boundary
       drew a HARD DIAGONAL that read as a different material. It cost three
       builders time (the minivan roof cap, the garage bay, every vehicle),
       and the standing workaround was to switch `receiveShadow` off out
       there and hand-place multiply discs.

       Widening to one +/-40 box was measured and rejected: yard shadows
       appear, every interior's shadows coarsen ~4x.

       A second shadow-casting light was the obvious candidate and does NOT
       work here: three tests `light.layers` against the CAMERA, not against
       each object, so a light cannot be scoped to the yard - a second sun
       would light the whole house twice.

       What does work is that this scene has exactly five cameras and only
       ever sits at one of them. The box now FOLLOWS THE ACTIVE VIEW: sized
       to what that camera can see, centred on what it is looking at. The
       light's DIRECTION never changes (the sun's offset from its target is
       constant), so shading is identical from room to room; only the
       shadow map's footprint moves. Paired with the bigger map below, the
       arithmetic comes out ahead everywhere: the old box put a shadow texel
       at 20/2048 = 9.8mm; the kitchen and living boxes now sit at 6.3mm and
       the mudroom at 5.9mm, while the two that have to reach out into the
       garden - exterior and garage - land at 10.3mm and 10.7mm, within a
       tenth of the old figure while covering four to five times the area
       and carrying shadows that never existed out there at all.

       It is a state change, not a frame loop: aimShadow() is called once at
       build and once per room change, next to the camera tween. */
    var SUN_OFF = new T.Vector3(21, 24, 9);   /* direction only - the length
                                                 just keeps every roof in
                                                 front of the near plane */
    var sunTarget = new T.Object3D();
    scene.add(sunTarget);
    sun.target = sunTarget;
    /* Sized to what each camera can REACH, not to the room's footprint: a
       lean-in stands further off than the room pose, and the first cut of
       this table (garage half 8.5) put the boundary back across the lawn in
       the garage lean. Every box is a half-extent in LIGHT space, so a world
       corner 8.5 out can still land at 10.7 once the sun's basis rotates it.
       Erring wide costs resolution the bigger map pays back; erring tight
       costs a hard diagonal, which is the bug this whole block exists for. */
    var SHADOW_BOX = {          /* centre x, centre z, half-extent */
      exterior: [-5.4, 7.4, 21],
      kitchen: [0.0, 1.5, 13],
      living: [-1.4, 8.6, 13],
      mudroom: [-11.0, 5.6, 12],
      garage: [-15.4, 6.2, 22]
    };
    function aimShadow(name) {
      var b = SHADOW_BOX[name] || SHADOW_BOX.exterior;
      sunTarget.position.set(b[0], 1.2, b[1]);
      sunTarget.updateMatrixWorld();
      sun.position.set(b[0] + SUN_OFF.x, 1.2 + SUN_OFF.y, b[1] + SUN_OFF.z);
      if (!SHADOWS) return;
      var c = sun.shadow.camera, h = b[2];
      c.left = -h; c.right = h; c.top = h; c.bottom = -h;
      c.near = 1; c.far = 52 + h;
      c.updateProjectionMatrix();
      var want = h > 9 ? SHADOW_HI : 2048;
      if (sun.shadow.mapSize.x !== want) {
        sun.shadow.mapSize.set(want, want);
        /* three only allocates the depth target once; drop it and the next
           depth pass builds one at the new size */
        if (sun.shadow.map) { sun.shadow.map.dispose(); sun.shadow.map = null; }
      }
      /* both biases follow the TEXEL, not the box: a wide box on a big map
         has the same footprint as a tight one on a small map, and a bias
         tuned for one acnes or peter-pans on the other */
      var texel = 2 * h / want;
      sun.shadow.normalBias = 0.010 + texel * 2.4;
      sun.shadow.bias = -0.0004 - texel * 0.02;
      R.shadowMap.needsUpdate = true;
    }
    function shadowDirty() { if (SHADOWS) R.shadowMap.needsUpdate = true; }
    aimShadow('exterior');
    /* ---- LIGHT POOLS (bible S4: "light pools; warm patches on the floor
       and counters, cool elsewhere"). One 26-unit lamp over the middle of
       the house used to be the whole answer, and it was doing two wrong
       things at once: reaching every room equally (so nothing pooled) and
       peaking hot enough to clip a stool top to yellow-white now that the
       curve is linear. Replaced by one SHORT-THROW lamp per room, sitting
       where that room's real light fitting is, none of them casting a
       shadow map. They never move and never animate: this is a static rig,
       drawn only when the scene draws.

       The other half of the pooling is BAKED - the warm radial in each
       floor texture below - because that half survives to `low`, where
       there are no lamps at all. */
    var poolLamps = [];
    if (DETAIL >= 2) {
      var POOL = 0xffe2b4;                  /* warm, but not the orange the
                                               old 0xffd9a0 pushed onto wood */
      [[0.4, 4.55, -0.7, 13.5, 0.42],       /* the pendants over the island */
       [-2.4, 4.35, 9.6, 13.0, 0.40],       /* the living room's own corner */
       [-9.9, 3.45, 5.3, 8.5, 0.34],        /* the mudroom's wall light */
       [-15.4, 3.95, 6.3, 10.0, 0.36],      /* the garage's strip light */
       [-17.55, 2.80, 10.4, 7.0, 0.00]      /* the coach lamp: dark by day */
      ].forEach(function (p) {
        var lamp = new T.PointLight(POOL, (PBR ? 1 : 0.72) * p[4], p[3]);
        lamp.position.set(p[0], p[1], p[2]);
        lamp.userData.dayI = (PBR ? 1 : 0.72) * p[4];
        scene.add(lamp);
        poolLamps.push(lamp);
      });
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
    /* y0: rooms whose floor is not the house slab (the mudroom sits at
       0.03, the pantry too) pass their own floor height, or the disc
       renders underneath the boards and nothing reads as touching */
    function blobShadow(rx, rz, x, z, group, y0) {
      if (SHADOWS) return null;          // the high tier has the real thing
      var m = new T.Mesh(new T.CircleGeometry(1, 20),
        new T.MeshBasicMaterial({ color: C.shadow, transparent: true, opacity: 0.16 }));
      m.rotation.x = -Math.PI / 2;
      m.scale.set(rx, rz, 1);
      m.position.set(x, y0 === undefined ? 0.012 : y0, z);
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
    /* ---- BAKED LIGHT POOLS (bible S4, and the arc brief) ---------------
       "Light pools. Warm patches on the floor and counters, cool
       elsewhere." The room lamps above do half of it, but only from
       medium up: at `low` there are no lamps at all, and the great room's
       floor is the surface that fills every frame at every tier. So the
       other half is PAINTED - the same discipline the garage slab's door
       gradient already uses.

       Authored in WORLD units, not texture units, because the kitchen
       floor and the living floor are two planes with DIFFERENT UV scales
       across ONE open room: a gradient authored per-texture puts a visible
       step across the seam at z 5.7. Mapped through each plane's own
       affine world->canvas transform, the cool surround runs continuously
       off one plane and onto the other.

       And the surround is the point. A floor that is only ever LIGHTENED
       ends up flat and pale - which is how the whole tier read before this
       pass. The cool ring goes down first; the warm patches are then a
       difference, not a brightening. */
    var POOLS = [                 /* world x, world z, radius, strength */
      [0.4, -0.9, 5.0, 0.30],     /* under the island pendants */
      [2.3, 2.9, 3.4, 0.17],      /* the dining table's own light */
      [-2.4, 9.7, 4.6, 0.28],     /* the living room's lamps */
      [2.6, 12.4, 3.2, 0.16]      /* the reading corner */
    ];
    function pooledFloorTex(x0, xw, z0, zw) {
      var c = document.createElement('canvas');
      var W = c.width = c.height = floorCanvas.width;
      var g = c.getContext('2d');
      g.drawImage(floorCanvas, 0, 0);
      function px(wx) { return (wx - x0) / xw * W; }
      function py(wz) { return (wz - z0) / zw * W; }
      function radial(wx, wz, r, stops) {
        var rx = Math.abs(px(wx + r) - px(wx)), ry = Math.abs(py(wz + r) - py(wz));
        g.save();
        g.translate(px(wx), py(wz));
        g.scale(rx || 1, ry || 1);
        var gr = g.createRadialGradient(0, 0, 0, 0, 0, 1);
        stops.forEach(function (s) { gr.addColorStop(s[0], s[1]); });
        g.fillStyle = gr;
        g.fillRect(-W, -W, W * 2, W * 2);   /* scaled units: covers all */
        g.restore();
      }
      /* the cool surround, centred on the great room, one ring for both
         planes so the seam at z 5.7 has nothing to show */
      radial(0, 4.2, 13.5, [[0, 'rgba(56,66,94,0)'], [0.42, 'rgba(56,66,94,0.06)'],
                            [1, 'rgba(56,66,94,0.30)']]);
      POOLS.forEach(function (p) {
        radial(p[0], p[1], p[2],
               [[0, 'rgba(255,228,172,' + p[3] + ')'],
                [0.5, 'rgba(255,228,172,' + (p[3] * 0.5).toFixed(3) + ')'],
                [1, 'rgba(255,228,172,0)']]);
      });
      var t = new T.CanvasTexture(c);
      t.anisotropy = 4;
      t.magFilter = T.LinearFilter;
      return t;
    }
    /* the KITCHEN plane: 13 x 11.6 at the origin, repeat 1 - its canvas
       spans world x -6.5..6.5 and z -5.8..5.8 exactly */
    var floorTexK = pooledFloorTex(-6.5, 13, -5.8, 11.6);
    var floor = new T.Mesh(new T.PlaneGeometry(13, 11.6),
      PBR ? new T.MeshStandardMaterial({ map: floorTexK, roughness: 0.5,
                                         envMapIntensity: 0.1 })
          : new T.MeshLambertMaterial({ map: floorTexK }));
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
    /* ---- THE SECTION (docs/house_style_bible.md S7.2) -----------------
       The plates always show a wall's THICKNESS where the cut passes
       through, which is what makes a dollhouse read as a deliberate
       section instead of a house with a wall missing. Every cut edge the
       exterior camera can see gets a band one shade darker than the face
       it caps, and the floor slab gets the poche line at its top. */
    var SECT = { rough: 0.9 };
    box(0.09, 5.6, 0.41, C.linen, 6.53, 2.8, -5.55, null, SECT);
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
    /* the slab's cut faces: the band the plates put under the floor */
    box(13.70, 0.50, 0.05, C.cabShade, 0, -0.27, 14.125, null, { rough: 0.9 });
    box(13.70, 0.13, 0.09, C.stone, 0, -0.045, 14.140, null, { rough: 0.9 });
    box(0.05, 0.50, 19.92, C.cabShade, 6.825, -0.27, 4.14, null, { rough: 0.9 });
    box(0.09, 0.13, 19.92, C.stone, 6.840, -0.045, 4.14, null, { rough: 0.9 });
    /* the LIVING plane: 13 x 8.5 at z 9.95, sampling only the top
       8.5/11 of its texture, so the canvas spans world z 3.2..14.2 -
       which is the range the pool bake is told about, and why the cool
       ring lands on the same world circle it does next door */
    var floorTex2 = pooledFloorTex(-6.5, 13, 3.2, 11.0);
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
    box(0.41, 5.6, 0.09, C.linen, -6.65, 2.8, 14.235, westWallG, { rough: 0.9 });
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
      /* ---- houseplants, not scale-model trees -------------------------
         A trunk with a canopy sphere on top is an oak. A houseplant has
         no visible trunk: the leaf mass starts at the pot rim and fans
         out from it. One broad leaf = a flattened ellipsoid whose base
         sits over the pot's centre and whose tip leans out by `tilt` at
         azimuth `spin`. Three silhouettes so no two plants repeat. */
      var LEAFC = [C.leaf, 0x527f44, 0x74a05a];
      function pLeaf(x, base, z, L, wide, thick, tilt, spin, c) {
        var m = new T.Mesh(new T.SphereGeometry(1, D3 ? 10 : 6, D3 ? 8 : 4),
                           mat(c, { rough: 1.0 }));
        m.scale.set(thick, L, wide);
        m.rotation.set(0, spin, tilt);
        var rad = L * Math.sin(tilt), up = L * Math.cos(tilt);
        m.position.set(x + Math.cos(spin) * rad, base + up, z - Math.sin(spin) * rad);
        ltag(m); finish(m); (PG || scene).add(m); return m;
      }
      /* leaf tables: [halfLength, halfWidth, tilt, spin] in units of s.
         The leaves overlap on purpose - a fan of separated blades reads
         as cut paper, a clump reads as a plant. */
      var PLANTS = {
        /* fiddle-leaf: a few broad leaves on very short stems, upright */
        fiddle: [[0.31, 0.20, 0.20, 0.35], [0.29, 0.19, 0.40, 1.40],
                 [0.27, 0.185, 0.56, 2.50], [0.24, 0.17, 0.74, 3.60],
                 [0.21, 0.16, 0.92, 4.70], [0.18, 0.145, 1.08, 5.70]],
        /* a spray: narrow leaves arcing out of the rim, a dracaena */
        spray: [[0.31, 0.105, 0.20, 0.20], [0.29, 0.100, 0.34, 1.25],
                [0.27, 0.095, 0.48, 2.30], [0.25, 0.090, 0.62, 3.35],
                [0.22, 0.085, 0.76, 4.40], [0.19, 0.080, 0.90, 5.45]],
        /* a low mound, wider than tall: fern / pothos */
        mound: [[0.28, 0.19, 0.42, 0.50], [0.27, 0.185, 0.54, 1.55],
                [0.26, 0.18, 0.66, 2.60], [0.24, 0.17, 0.78, 3.65],
                [0.22, 0.16, 0.88, 4.70], [0.20, 0.15, 0.98, 5.75]]
      };
      var PLIFT = { fiddle: 0, spray: 0.03, mound: 0.11 };
      /* a potted plant. potO carries the material (ceramic gloss, matte
         terracotta, stone) so no two pots in the room read the same. */
      function plant(x, y0, z, s, potC, potO, kind, shadow) {
        var ph = 0.34 * s;
        lc(0.24 * s, 0.19 * s, ph, potC, x, y0 + ph / 2, z, null, 14, potO);
        if (D3) lc(0.25 * s, 0.25 * s, 0.05, potC, x, y0 + ph - 0.015, z, null, 14, potO);
        /* the spreading kinds start a little higher, or their outermost
           leaves hang over the rim and swallow the pot */
        var b = y0 + ph + (PLIFT[kind] || 0) * s - 0.06 * s;
        var tbl = PLANTS[kind] || PLANTS.mound;
        var n = D3 ? tbl.length : (D2 ? 4 : 3);
        /* a squashed clump at the rim: without it the leaves float */
        sph(0.19 * s, LEAFC[1], x, b + 0.05 * s, z, 0.55);
        for (var i = 0; i < n; i++) {
          var lf = tbl[i];
          pLeaf(x, b, z, lf[0] * s, lf[1] * s, 0.045 * s, lf[2], lf[3],
                LEAFC[i % 3]);
        }
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
      /* the room needs a mass here, not a white panel on a white wall,
         but stone in a warm room is a warm grey-taupe, never concrete.
         And the breast steps back above the mantle and stops well short
         of the crown: a chimney is quieter than the casework beside it,
         not the loudest thing in the frame. */
      var STONE = 0x9e9182, STONE_DK = 0x7f7365;
      lb(0.90, 0.22, 2.72, STONE_DK, WX + 0.45, 0.11, HZ, null, { rough: 0.9 });
      lb(0.44, 1.72, 2.32, STONE, WX + 0.22, 1.08, HZ, null, PLASTER);
      lb(0.38, 1.62, 1.86, STONE, WX + 0.19, 2.79, HZ, null, PLASTER);
      if (D3) {           /* the shoulder where it steps back, and a cap */
        lb(0.50, 0.10, 2.40, STONE_DK, WX + 0.25, 1.99, HZ, null, PLASTER);
        lb(0.44, 0.10, 1.98, STONE_DK, WX + 0.22, 3.65, HZ, null, PLASTER);
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
      plant(WX + 0.48, 1.825, HZ + 0.98, 0.38, C.cream, GLOSS, 'mound', false);
      /* the TV: bracket, bezel, screen. A television over a mantle, not
         a cinema screen - it sits inside the stack's width and leaves
         stone above it. westWallG - see the header note. */
      lb(0.12, 0.30, 0.30, C.graphite, WX + 0.44, 2.80, HZ, westWallG, { rough: 0.6 });
      lr(0.09, 0.92, 1.42, 0.025, 0x3a434e, WX + 0.560, 2.80, HZ, westWallG, { rough: 0.72 });
      lb(0.02, 0.74, 1.24, 0x0d1013, WX + 0.616, 2.80, HZ, westWallG,
         { rough: 0.62, metal: 0.0, envInt: 0.04 });
      if (D3) lb(0.02, 0.03, 0.05, C.teal, WX + 0.616, 2.44, HZ - 0.58, westWallG, GLOSS);

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
        plant(xs, 2.33, bz - 0.44, 0.38, seed % 2 ? C.terracotta : C.cream,
              seed % 2 ? { rough: 0.85 } : GLOSS,
              seed % 2 ? 'spray' : 'fiddle', false);
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
      /* the reading corner's chair is NOT a second sofa. An exposed wood
         frame on splayed legs, one thin seat pad, one thin back pad, and
         open arms you can see the floor through - visibly lighter than
         the sofa so the corner reads as the quieter zone. */
      function lightChair(x, z, rot, body, accent) {
        var g = new T.Group();
        g.position.set(x, 0, z);
        g.rotation.y = rot;
        ltag(g); scene.add(g);
        function sb(w, h, d, r, c, px, py, pz, o) {
          var m = new T.Mesh(
            D2 ? roundedGeo(w, h, d, r) : new T.BoxGeometry(w, h, d),
            mat(c, o || FAB));
          m.position.set(px, py, pz);
          m.userData.room = 'living'; finish(m); g.add(m); return m;
        }
        function rod(rt, rb, h, px, py, pz, rx, rz) {
          var m = new T.Mesh(new T.CylinderGeometry(rt, rb, h, D3 ? 10 : 6),
                             mat(C.wood2, WOODM));
          m.position.set(px, py, pz);
          if (rx) m.rotation.x = rx;
          if (rz) m.rotation.z = rz;
          m.userData.room = 'living'; finish(m); g.add(m); return m;
        }
        [[-0.30, -0.30], [-0.30, 0.30], [0.30, -0.30], [0.30, 0.30]]
          .forEach(function (lg) {          /* splayed legs, floor visible */
            rod(0.045, 0.032, 0.48, lg[0], 0.24, lg[1],
                lg[1] < 0 ? 0.10 : -0.10, lg[0] < 0 ? -0.10 : 0.10);
          });
        sb(0.80, 0.07, 0.80, 0.02, woodK, 0, 0.47, 0, woodO);
        sb(0.72, 0.15, 0.72, 0.07, body, -0.02, 0.580, 0);
        [-0.31, 0.31].forEach(function (dz) {   /* raked back uprights */
          rod(0.040, 0.036, 0.68, 0.355, 0.80, dz, 0, 0.14);
          rod(0.032, 0.032, 0.66, 0.02, 0.755, dz, 0, Math.PI / 2);
          rod(0.032, 0.032, 0.28, -0.285, 0.615, dz, 0, 0);
        });
        var bk = sb(0.12, 0.48, 0.70, 0.06, body, 0.375, 0.94, 0);
        bk.rotation.z = 0.14;
        if (D2) {
          var pw = sb(0.16, 0.34, 0.38, 0.09, accent, 0.245, 0.80, 0.02);
          pw.rotation.z = 0.20;
        }
        blobShadow(0.48, 0.48, x, z);
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
      /* the south chair is on the CAMERA's side of the group, so any
         pose that faces the fire shows the lens a flat back. It turns
         off the fire axis to face the coffee table instead - seating
         faces other seating (S8), and that outranks facing the hearth. */
      seat(-4.05, 10.62, -2.25, 1.12, C.terracotta, C.terraDeep, 1,
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
      plant(WX + 0.29, 0.95, CZ + 0.56, 0.39, C.linen, { rough: 0.8 }, 'fiddle', false);
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
        var rug = new T.Mesh(new T.CircleGeometry(1.60, D3 ? 28 : 16),
                             mat(C.linen, { rough: 1.0 }));
        rug.rotation.x = -Math.PI / 2;
        rug.position.set(1.40, 0.048, 9.85);
        if (SHADOWS) rug.receiveShadow = true;
        ltag(rug); scene.add(rug);
        if (D2) {
          var ring = new T.Mesh(new T.RingGeometry(1.36, 1.48, 28),
                                mat(C.sageDeep, { rough: 1.0 }));
          ring.rotation.x = -Math.PI / 2;
          ring.position.set(1.40, 0.054, 9.85);
          ltag(ring); scene.add(ring);
        }
      })();
      lightChair(0.88, 9.88, 0.55, C.sage, C.oxblood);
      /* the floor lamp: base, stem, shade. All of it is D2 - a bare pole
         with no shade at the low tier reads as broken geometry. */
      if (D2) {
        lc(0.28, 0.30, 0.05, C.brass, 0.30, 0.03, 10.90, null, 14, STEEL);
        lc(0.035, 0.035, 1.62, C.brass, 0.30, 0.86, 10.90, null, 8, STEEL);
        var lsh2 = new T.Mesh(new T.CylinderGeometry(0.24, 0.34, 0.34, 16, 1, true),
          PBR ? new T.MeshStandardMaterial({ color: 0xf3e8d2, roughness: 0.8,
                                             emissive: 0xffd9a0, emissiveIntensity: 0.45,
                                             side: T.DoubleSide })
              : new T.MeshLambertMaterial({ color: 0xf3e8d2, side: T.DoubleSide }));
        lsh2.position.set(0.30, 1.82, 10.90);
        ltag(lsh2); finish(lsh2, true); scene.add(lsh2);
      }
      blobShadow(0.32, 0.32, 0.30, 10.90);
      /* the side table: pedestal, base, top, three props */
      lc(0.44, 0.44, 0.07, woodK, 1.86, 0.62, 10.40, null, 16, woodO);
      lc(0.065, 0.065, 0.58, C.wood2, 1.86, 0.30, 10.40, null, 10, WOODM);
      lc(0.26, 0.28, 0.05, C.wood2, 1.86, 0.03, 10.40, null, 14, WOODM);
      if (D2) {
        lb(0.28, 0.055, 0.20, C.slate, 1.76, 0.683, 10.32);
        lb(0.26, 0.05, 0.19, C.brass, 1.76, 0.735, 10.33);
        lc(0.085, 0.075, 0.14, C.cream, 2.03, 0.725, 10.52, null, 10, GLOSS);
      }
      blobShadow(0.4, 0.4, 1.86, 10.40);
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
        lb(0.34, 0.06, 0.26, C.oxblood, 0.82, 0.03, 10.78);
        lb(0.33, 0.055, 0.25, C.cream, 0.82, 0.088, 10.79);
        if (D3) lb(0.31, 0.055, 0.24, C.sage, 0.83, 0.143, 10.77);
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

      /* ================= 9. plants (S4 wants three; eight here) ========
         Houseplants: at most 0.9 units on the floor, 0.35 on a shelf,
         and three silhouettes so the room never repeats one. */
      plant(-5.42, 0, 13.86, 0.96, C.terracotta, { rough: 0.85 }, 'fiddle', true);
      plant(0.95, 0, 6.75, 0.96, C.terracotta, { rough: 0.85 }, 'spray', true);
      plant(2.68, 0, 9.05, 0.98, C.linen, { rough: 0.78 }, 'mound', true);

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
        plant(WX + 0.26, 1.34, 4.90, 0.36, C.cream, GLOSS, 'mound', false);
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

    /* the backsplash moved into the kitchen millwork below: it is no
       longer a band that stops short but a tile field running the whole
       run, counter line to the underside of the uppers (bible S7.4) */

    var groups = {};
    function zoneGroup(key, x, y, z) {
      var g = new T.Group();
      g.position.set(x, y, z);
      g.userData.zone = key;
      groups[key] = g; scene.add(g); return g;
    }

    /* ---- KITCHEN MILLWORK (studio pipeline — docs/house_style_bible.md
       S3.1 / S3.2) ------------------------------------------------------
       A cabinet is never one box. Every run here is toe kick, carcass,
       face frame with a stile between every pair of fronts, inset fronts
       on a 0.03 reveal, hardware, and a top that overhangs. The uppers
       align to the window — sill line to cabinet bottom, head casing to
       cabinet top — and the tile field fills the whole band between the
       counter and the uppers, which is what S7.4 was asking for.
       Palette: casework cream, counters wood, the island walnut; four
       accents and no strays — teal (the fridge is this room's sage),
       terracotta, brass, oxblood. Dark anchors: the hood and the
       cooktop. ---- */
    var KD2 = DETAIL >= 2, KD3 = DETAIL >= 3;
    var NZ = -5.375;                    /* the north wall's inner face */
    var WXK = -6.475;                   /* the west wall's inner face */
    var CT_Y = 1.13, CT_T = 0.09;       /* counter surface + slab (S1) */
    var TOE = 0.16, BASE_D = 1.44;
    var UP_Y0 = 2.52, UP_Y1 = 4.35, UP_D = 0.74;
    var MATT = { rough: 0.9 };
    var kWoodO = NICE ? { rough: 0.55, map: woodLight, envInt: 0.35 }
                      : { rough: 0.6 };
    var kWoodK = NICE ? 0xffffff : 0xc89a66;
    var HW = C.brass;                   /* one hardware finish, room-wide */

    /* the tile field: a running bond with grout lines and tiles that are
       not all one tone, so the wall is a surface and not a sheet */
    var kTileTex = null;
    if (NICE) {
      kTileTex = canvasTex(256, function (g) {
        g.fillStyle = '#d9d0c0'; g.fillRect(0, 0, 256, 256);   /* grout */
        var TW = 64, TH = 32, TONE = ['#f7f3ec', '#f1ebe0', '#f9f6f0', '#ede6d9'];
        for (var r = 0; r < 8; r++) {
          for (var i = -1; i < 5; i++) {
            var x = i * TW + (r % 2 ? TW / 2 : 0);
            g.fillStyle = TONE[(r * 3 + i + 8) % 4];
            g.fillRect(x + 2, r * TH + 2, TW - 4, TH - 4);
          }
        }
      });
      kTileTex.wrapS = kTileTex.wrapT = T.RepeatWrapping;
    }
    function kTile(w, h, x, y, z, rotY) {
      var m;
      if (kTileTex) {
        var t = kTileTex.clone();
        t.needsUpdate = true;
        t.wrapS = t.wrapT = T.RepeatWrapping;
        t.repeat.set(w / 2.0, h / 1.0);
        m = new T.Mesh(new T.PlaneGeometry(w, h),
          PBR ? new T.MeshStandardMaterial({ map: t, roughness: 0.30,
                                             envMapIntensity: 0.2 })
              : new T.MeshLambertMaterial({ map: t }));
      } else {
        m = new T.Mesh(new T.PlaneGeometry(w, h), mat(0xf2ede3, { rough: 0.4 }));
      }
      m.position.set(x, y, z);
      if (rotY) m.rotation.y = rotY;
      if (SHADOWS) m.receiveShadow = true;
      scene.add(m);
      return m;
    }

    /* ---- the case builder (S3.1) --------------------------------------
       Built facing local +z, then dropped into place, so the west wall's
       L-return is the same code as the north wall's run. `rows` runs
       bottom to top; each row's `cells` run left to right. */
    var FF = 0.09;                      /* face-frame stile/rail width */
    function kPull(g, x, y, zf, len, vert) {
      if (!KD2) return;
      var t = 0.028;
      box(vert ? t : len, vert ? len : t, t, HW, x, y, zf + 0.055, g, STEEL);
      if (KD3) {                        /* stand-offs, so it is not a decal */
        var d = (len / 2) - 0.03;
        box(t * 0.7, t * 0.7, 0.05, HW, x + (vert ? 0 : -d), y + (vert ? -d : 0),
            zf + 0.030, g, STEEL);
        box(t * 0.7, t * 0.7, 0.05, HW, x + (vert ? 0 : d), y + (vert ? d : 0),
            zf + 0.030, g, STEEL);
      }
    }
    /* one inset front inside an opening: 0.03 reveal all round, a shaker
       panel proud of it at tier 3, and its pull */
    function kFront(g, x0, x1, y0, y1, zf, kind) {
      var R = 0.03;
      var w = (x1 - x0) - 2 * R, h = (y1 - y0) - 2 * R;
      if (w <= 0.02 || h <= 0.02) return;
      var cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
      rbox(w, h, 0.03, 0.02, kFaceC, cx, cy, zf + 0.010, g, MATT);
      if (KD3 && w > 0.22 && h > 0.22)
        rbox(w - 0.10, h - 0.10, 0.02, 0.015, kBodyC, cx, cy, zf + 0.030, g, MATT);
      if (kind === 'drawer') kPull(g, cx, cy, zf, Math.min(0.30, w * 0.55), false);
      else if (kind === 'left') kPull(g, x1 - 0.09, cy, zf, Math.min(0.30, h * 0.5), true);
      else kPull(g, x0 + 0.09, cy, zf, Math.min(0.30, h * 0.5), true);
    }
    /* one opening's worth of fronts */
    function kCell(g, x0, x1, y0, y1, zf, kind) {
      var i, n, hs, y;
      if (kind === 'doors2') {
        var xm = (x0 + x1) / 2;
        box(FF, y1 - y0, 0.04, kFaceC, xm, (y0 + y1) / 2, zf + 0.02, g, MATT);
        kFront(g, x0, xm - FF / 2, y0, y1, zf, 'left');
        kFront(g, xm + FF / 2, x1, y0, y1, zf, 'right');
      } else if (kind === 'door') {
        kFront(g, x0, x1, y0, y1, zf, 'left');
      } else if (kind === 'drawers3' || kind === 'drawers2') {
        n = kind === 'drawers3' ? 3 : 2;
        hs = (y1 - y0) / (n === 3 ? 4.4 : 2.4);
        y = y0;
        for (i = 0; i < n; i++) {
          var hh = (i === 0 && n === 3) ? hs * 1.8 : (i === 0 ? hs * 1.4 : hs * (n === 3 ? 1.3 : 1.0));
          if (i === n - 1) hh = y1 - y;
          if (i < n - 1) box(x1 - x0, FF * 0.7, 0.04, kFaceC, (x0 + x1) / 2,
                             y + hh, zf + 0.02, g, MATT);
          kFront(g, x0, x1, y, y + hh, zf, 'drawer');
          y += hh;
        }
      } else if (kind === 'dish') {          /* a dishwasher panel (S3.4) */
        rbox(x1 - x0 - 0.05, y1 - y0 - 0.05, 0.04, 0.02, 0xc9ced3,
             (x0 + x1) / 2, (y0 + y1) / 2, zf + 0.015, g, STEEL);
        box(x1 - x0 - 0.16, 0.05, 0.05, C.steel, (x0 + x1) / 2, y1 - 0.10,
            zf + 0.05, g, CHROME);
        if (KD3) box(0.24, 0.035, 0.02, C.ink, (x0 + x1) / 2 - 0.10, y1 - 0.20,
                     zf + 0.045, g, GLOSS);
      } else if (kind === 'open') {
        /* handled by the caller: a bay needs a back panel + contents */
      }
    }
    var kFaceC = C.cab, kBodyC = C.cabShade;    /* the run being built */
    function kCase(cx, cz, rot, W, D, y0, y1, rows, opt) {
      opt = opt || {};
      kFaceC = opt.face || C.cab;
      kBodyC = opt.body || C.cabShade;
      var g = new T.Group();
      g.position.set(cx, 0, cz);
      if (rot) g.rotation.y = rot;
      scene.add(g);
      var zf = D / 2, by0 = y0;
      if (opt.toe) {                                       /* 1. toe kick */
        box(W - 0.02, TOE, D - 0.07, kBodyC, 0, y0 + TOE / 2, -0.035, g, MATT);
        by0 = y0 + TOE;
      }
      var H = y1 - by0, TH = 0.05;
      /* 2. carcass — a shell in cabShade, never the visible surface, and
         hollow so an open bay's contents are not buried inside a block */
      box(W, H, TH, kBodyC, 0, by0 + H / 2, -D / 2 + TH / 2, g, MATT);
      box(TH, H, D, kBodyC, -W / 2 + TH / 2, by0 + H / 2, 0, g, MATT);
      box(TH, H, D, kBodyC, W / 2 - TH / 2, by0 + H / 2, 0, g, MATT);
      box(W, TH, D, kBodyC, 0, by0 + TH / 2, 0, g, MATT);
      box(W, TH, D, kBodyC, 0, y1 - TH / 2, 0, g, MATT);
      /* finished end panels: the exposed gable wears the door colour */
      box(0.05, H, D + 0.03, kFaceC, -W / 2 - 0.005, by0 + H / 2, 0.015, g, MATT);
      box(0.05, H, D + 0.03, kFaceC, W / 2 + 0.005, by0 + H / 2, 0.015, g, MATT);
      var y = by0;
      rows.forEach(function (row) {
        var ry0 = y, ry1 = y + row.h;
        y = ry1;
        if (row.kind === 'ledge') {          /* a counter/shelf break */
          box(W + 0.08, row.h, D + 0.06, kFaceC, 0, (ry0 + ry1) / 2, 0.03, g, MATT);
          return;
        }
        if (row.kind === 'bays') { kBays(g, W, D, ry0, ry1, row); return; }
        /* 3. face frame: rails top and bottom, a stile on every boundary */
        box(W, FF, 0.04, kFaceC, 0, ry0 + FF / 2, zf + 0.02, g, MATT);
        box(W, FF, 0.04, kFaceC, 0, ry1 - FF / 2, zf + 0.02, g, MATT);
        var cells = row.cells, tot = 0, i;
        for (i = 0; i < cells.length; i++) tot += cells[i].w;
        var x = -W / 2, ox = [];
        for (i = 0; i < cells.length; i++) {
          var w = W * cells[i].w / tot;
          ox.push([x, x + w]); x += w;
        }
        for (i = 0; i <= cells.length; i++) {
          var sx = i === 0 ? -W / 2 + FF / 2
                 : (i === cells.length ? W / 2 - FF / 2 : ox[i][0]);
          box(FF, ry1 - ry0, 0.04, kFaceC, sx, (ry0 + ry1) / 2, zf + 0.02, g, MATT);
        }
        for (i = 0; i < cells.length; i++) {
          kCell(g, ox[i][0] + (i === 0 ? FF : FF / 2),
                ox[i][1] - (i === cells.length - 1 ? FF : FF / 2),
                ry0 + FF, ry1 - FF, zf, cells[i].kind);
        }
      });
      return g;
    }

    /* ---- open bays (S3.2) ---------------------------------------------
       Shelf boards with a visible edge, a back panel one shade darker and
       inset, dividers, and 3-6 objects in every bay. The bay contents are
       the finest layer: tier 2 gets three, tier 3 gets the lot. */
    var kBayFill = [];                  /* [group, x0, x1, y, seed] to load */
    function kBays(g, W, D, y0, y1, row) {
      var bays = row.bays || 2, tiers = row.tiers || 2, i, j;
      var zf = D / 2, bd = row.depth || Math.min(D, 0.50);
      /* back panel: darker, inset — this is what makes a bay a bay.
         `row.back` lets a room outside the kitchen pick its own shade. */
      box(W - 0.06, y1 - y0, 0.03, row.back || KBAY, 0, (y0 + y1) / 2,
          zf - bd + 0.03, g, { rough: 0.95 });
      var bh = (y1 - y0) / tiers;
      for (i = 0; i <= tiers; i++) {
        var sy = y0 + i * bh;
        box(W, 0.06, bd, kFaceC, 0, sy + (i === 0 ? 0.03 : -0.03), zf - bd / 2,
            g, MATT);
        if (KD3)                        /* the shelf's front edge line */
          box(W, 0.062, 0.02, kBodyC, 0, sy + (i === 0 ? 0.03 : -0.03),
              zf - 0.01, g, MATT);
      }
      var bw = W / bays;
      for (i = 1; i < bays; i++)
        box(0.05, y1 - y0, bd, kFaceC, -W / 2 + i * bw, (y0 + y1) / 2,
            zf - bd / 2, g, MATT);
      for (i = 0; i < bays; i++) for (j = 0; j < tiers; j++)
        kBayFill.push([g, -W / 2 + i * bw + 0.09, -W / 2 + (i + 1) * bw - 0.09,
                       y0 + j * bh + 0.06, zf - bd / 2, i * 3 + j]);
    }

    /* ---- the small-prop vocabulary, kitchen edition (S3.2) ------------- */
    var KJARC = [C.teal, C.terracotta, C.brass, C.cream, C.oxblood, C.linen];
    var KBAY = 0x4e6c6e;                /* bay backs: the teal family, dark */
    function kJar(g, x, y, z, r, h, c) {
      cyl(r, r * 0.92, h, c, x, y + h / 2, z, g, 12, GLOSS);
      if (KD3) cyl(r * 0.66, r * 0.82, 0.045, HW, x, y + h + 0.022, z, g, 10, STEEL);
    }
    function kBowl(g, x, y, z, r, c) {
      cyl(r, r * 0.58, 0.12, c, x, y + 0.06, z, g, 14, GLOSS);
    }
    function kPlates(g, x, y, z, r, c) {
      for (var k = 0; k < (KD3 ? 4 : 2); k++)
        cyl(r, r, 0.030, c, x, y + 0.016 + k * 0.038, z, g, 14, GLOSS);
    }
    function kCups(g, x, y, z, n, c) {
      for (var k = 0; k < n; k++)
        cyl(0.055, 0.048, 0.10, c, x + k * 0.135, y + 0.05, z, g, 10, GLOSS);
    }
    function kBooks(g, x, y, z0, n, step, seed) {
      for (var k = 0; k < n; k++) {
        var h = 0.20 + ((k * 5 + seed) % 4) * 0.028;
        var m = box(0.17, h, step * 0.62, KJARC[(k + seed) % 6], x, y + h / 2,
                    z0 + step * (k + 0.5), g);
        if (KD3 && (k + seed) % 4 === 3) { m.rotation.x = 0.16; m.position.y += 0.012; }
      }
    }
    /* a cake stand: the plates put one in nearly every bay */
    function kCake(g, x, y, z, c) {
      cyl(0.05, 0.09, 0.10, c, x, y + 0.05, z, g, 12, GLOSS);
      cyl(0.16, 0.16, 0.025, c, x, y + 0.112, z, g, 14, GLOSS);
      if (KD3) cyl(0.11, 0.13, 0.09, 0xf6e6c8, x, y + 0.17, z, g, 12, MATT);
    }
    /* a houseplant that reads as a houseplant: a clump at the rim and a
       fan of leaves out of it, never a trunk with a ball on top */
    var KLEAF = [C.leaf, 0x527f44, 0x74a05a];
    var KPL = {
      fiddle: [[0.31, 0.20, 0.20, 0.35], [0.29, 0.19, 0.40, 1.40],
               [0.27, 0.185, 0.56, 2.50], [0.24, 0.17, 0.74, 3.60],
               [0.21, 0.16, 0.92, 4.70], [0.18, 0.145, 1.08, 5.70]],
      spray: [[0.31, 0.105, 0.20, 0.20], [0.29, 0.100, 0.34, 1.25],
              [0.27, 0.095, 0.48, 2.30], [0.25, 0.090, 0.62, 3.35],
              [0.22, 0.085, 0.76, 4.40], [0.19, 0.080, 0.90, 5.45]],
      mound: [[0.28, 0.19, 0.42, 0.50], [0.27, 0.185, 0.54, 1.55],
              [0.26, 0.18, 0.66, 2.60], [0.24, 0.17, 0.78, 3.65],
              [0.22, 0.16, 0.88, 4.70], [0.20, 0.15, 0.98, 5.75]]
    };
    var KLIFT = { fiddle: 0, spray: 0.03, mound: 0.11 };
    function kSph(g, r, c, x, y, z, sy) {
      var m = new T.Mesh(new T.SphereGeometry(r, KD3 ? 10 : 6, KD3 ? 8 : 4),
                         mat(c, { rough: 1.0 }));
      m.position.set(x, y, z);
      if (sy) m.scale.y = sy;
      finish(m); (g || scene).add(m); return m;
    }
    function kLeaf(g, x, base, z, L, wide, thick, tilt, spin, c) {
      var m = new T.Mesh(new T.SphereGeometry(1, KD3 ? 10 : 6, KD3 ? 8 : 4),
                         mat(c, { rough: 1.0 }));
      m.scale.set(thick, L, wide);
      m.rotation.set(0, spin, tilt);
      var rad = L * Math.sin(tilt), up = L * Math.cos(tilt);
      m.position.set(x + Math.cos(spin) * rad, base + up, z - Math.sin(spin) * rad);
      finish(m); (g || scene).add(m); return m;
    }
    function kPlant(g, x, y0, z, s, potC, potO, kind, shadow) {
      var ph = 0.34 * s;
      cyl(0.24 * s, 0.19 * s, ph, potC, x, y0 + ph / 2, z, g, 14, potO);
      if (KD3) cyl(0.25 * s, 0.25 * s, 0.05, potC, x, y0 + ph - 0.015, z, g, 14, potO);
      var b = y0 + ph + (KLIFT[kind] || 0) * s - 0.06 * s;
      var tbl = KPL[kind] || KPL.mound;
      var n = KD3 ? tbl.length : (KD2 ? 4 : 3);
      kSph(g, 0.19 * s, KLEAF[1], x, b + 0.05 * s, z, 0.55);
      for (var i = 0; i < n; i++) {
        var lf = tbl[i];
        kLeaf(g, x, b, z, lf[0] * s, lf[1] * s, 0.045 * s, lf[2], lf[3],
              KLEAF[i % 3]);
      }
      if (shadow) blobShadow(0.34 * s, 0.32 * s, x, z);
    }

    /* ---- the runs ------------------------------------------------------ */
    var BZ = NZ + BASE_D / 2;           /* base run centre on the north wall */
    /* run A: doors, the apron sink under the window, a dishwasher, drawers */
    kCase(-1.825, BZ, 0, 5.35, BASE_D, 0, CT_Y - CT_T, [
      { h: CT_Y - CT_T - TOE, cells: [
        { w: 1.72, kind: 'doors2' }, { w: 1.80, kind: 'apron' },
        { w: 1.03, kind: 'dish' }, { w: 0.80, kind: 'drawers3' }] }
    ], { toe: true });
    /* run B: under the wall calendar, east of the range */
    kCase(3.70, BZ, 0, 2.30, BASE_D, 0, CT_Y - CT_T, [
      { h: CT_Y - CT_T - TOE, cells: [
        { w: 1.15, kind: 'drawers3' }, { w: 1.15, kind: 'doors2' }] }
    ], { toe: true });
    /* the L-return on the west wall: plate 9's L-run, and the piece that
       stops the pantry corner reading as bare floor */
    kCase(-6.275, -2.20, Math.PI / 2, 1.30, 0.75, 0, CT_Y - CT_T, [
      { h: CT_Y - CT_T - TOE, cells: [
        { w: 0.65, kind: 'drawers3' }, { w: 0.65, kind: 'door' }] }
    ], { toe: true });
    /* countertops: a slab that overhangs the fronts by 0.05 (S3.1.6) */
    function kTop(w, d, x, z) {
      var m = new T.Mesh(
        NICE ? roundedGeo(w, CT_T, d, 0.02) : new T.BoxGeometry(w, CT_T, d),
        PBR ? new T.MeshStandardMaterial({ map: woodLight, color: kWoodK,
                                           roughness: 0.42, envMapIntensity: 0.35 })
            : new T.MeshLambertMaterial({ color: 0xc89a66, map: woodLight || null }));
      m.position.set(x, CT_Y - CT_T / 2, z);
      finish(m); scene.add(m); return m;
    }
    /* the worktop breaks either side of the apron sink: a counter that
       runs THROUGH the bowl leaves the basin a tray sitting on top */
    kTop(1.77, 1.49, -3.665, NZ + 0.745);
    kTop(1.88, 1.49, -0.040, NZ + 0.745);
    kTop(2.40, 1.49, 3.70, NZ + 0.745);
    kTop(0.80, 1.40, WXK + 0.400, -2.20);
    blobShadow(2.7, 0.75, -1.825, BZ);
    blobShadow(1.2, 0.75, 3.70, BZ);
    blobShadow(0.68, 0.9, WXK + 0.65, -2.65);

    /* the tile field: counter line to the underside of the uppers, the
       whole run, both walls (S7.4) */
    kTile(9.40, UP_Y0 - CT_Y, 0.15, (CT_Y + UP_Y0) / 2, NZ + 0.012);
    kTile(1.85, UP_Y0 - CT_Y, WXK + 0.012, (CT_Y + UP_Y0) / 2, -2.65, Math.PI / 2);

    /* ---- the uppers ---------------------------------------------------
       Left of the window: open bays, loaded (S7.3). Right of it: a closed
       run with all six parts of S3.1. Both align to the window. */
    kCase(-3.75, NZ + 0.25, 0, 1.50, 0.50, UP_Y0, UP_Y1, [
      { h: 1.83, kind: 'bays', bays: 2, tiers: 3, depth: 0.48 }
    ]);
    kCase(0.01, NZ + UP_D / 2, 0, 1.58, UP_D, UP_Y0, UP_Y1, [
      { h: 1.33, cells: [{ w: 1, kind: 'doors2' }] },
      { h: 0.50, cells: [{ w: 1, kind: 'doors2' }] }
    ]);
    /* crown: the ceiling-to-upper gap gets filled (S1) */
    if (KD2) {
      box(1.62, 0.10, 0.60, C.cab, -3.75, UP_Y1 + 0.05, NZ + 0.30);
      box(1.70, 0.10, UP_D + 0.08, C.cab, 0.01, UP_Y1 + 0.05, NZ + UP_D / 2 + 0.04);
      box(1.56, 0.07, 0.52, C.cabShade, -3.75, UP_Y1 + 0.135, NZ + 0.28);
      box(1.64, 0.07, UP_D, C.cabShade, 0.01, UP_Y1 + 0.135, NZ + UP_D / 2);
    }

    /* ---- the larder: a full-height hutch closing the east end --------- */
    kCase(5.65, NZ + 0.40, 0, 1.50, 0.80, 0, UP_Y1, [
      { h: 1.74, cells: [{ w: 1, kind: 'doors2' }] },
      { h: 0.10, kind: 'ledge' },
      { h: 1.30, kind: 'bays', bays: 2, tiers: 2, depth: 0.56 },
      { h: 1.05, cells: [{ w: 1, kind: 'doors2' }] }
    ], { toe: true });
    if (KD2) {
      box(1.62, 0.10, 0.88, C.cab, 5.65, UP_Y1 + 0.05, NZ + 0.44);
      box(1.56, 0.07, 0.80, C.cabShade, 5.65, UP_Y1 + 0.135, NZ + 0.40);
    }
    blobShadow(0.78, 0.45, 5.65, NZ + 0.40);

    /* ---- bay contents: 3-6 objects, never the same height twice ------- */
    if (KD2) kBayFill.forEach(function (b) {
      var g = b[0], x0 = b[1], x1 = b[2], y = b[3], z = b[4], s = b[5];
      var w = x1 - x0, xm = (x0 + x1) / 2;
      if (s % 4 === 0) {
        kPlates(g, x0 + 0.13, y, z, 0.115, C.cream);
        kJar(g, xm + 0.02, y, z - 0.02, 0.075, 0.20, KJARC[s % 6]);
        kBowl(g, x1 - 0.12, y, z + 0.03, 0.115, C.terracotta);
        if (KD3) kCups(g, x0 + 0.06, y, z + 0.14, 2, C.teal);
      } else if (s % 4 === 1) {
        kBooks(g, x0 + 0.10, y, z - 0.20, 4, 0.075, s);
        kCake(g, xm + 0.14, y, z, C.cream);
        if (KD3) kJar(g, x1 - 0.10, y, z + 0.06, 0.06, 0.15, C.brass);
      } else if (s % 4 === 2) {
        kJar(g, x0 + 0.11, y, z - 0.02, 0.085, 0.26, C.teal);
        kJar(g, x0 + 0.30, y, z + 0.02, 0.065, 0.18, C.terracotta);
        kPlates(g, x1 - 0.14, y, z - 0.01, 0.105, C.linen);
        if (KD3) kCups(g, xm - 0.02, y, z + 0.15, 3, C.cream);
      } else {
        kPlant(g, x0 + 0.13, y, z, 0.30, C.cream, GLOSS, 'mound', false);
        kBowl(g, xm + 0.10, y, z - 0.02, 0.13, C.terracotta);
        kJar(g, x1 - 0.11, y, z + 0.04, 0.075, 0.22, C.oxblood);
        if (KD3) kPlates(g, xm + 0.10, y, z + 0.16, 0.09, C.cream);
      }
    });

    /* ---- the sink: a farmhouse apron proud of the run, under the window */
    (function () {
      var SX = -1.88, SZF = NZ + BASE_D + 0.055;   /* apron face */
      /* the apron runs up to the bowl's rim, and the bowl stands proud of
         the worktop: a flat grey rectangle on the counter reads as a tray */
      var CER = { rough: 0.22, metal: 0.0, envInt: 0.45 };
      /* the apron IS the bowl's front: it runs to the rim, proud of the run */
      rbox(1.72, 1.10, 0.14, 0.03, 0xf1eee7, SX, 0.640,
           SZF - 0.06, null, CER);
      if (KD3) box(1.64, 0.03, 0.02, C.cabShade, SX, 0.20, SZF, null, MATT);
      /* four rim bars, not a solid block: the dark interior has to be
         visible through the opening or the sink reads as a grey tray */
      box(1.80, 0.55, 0.10, 0xf1eee7, SX, 0.910, -5.10, null, CER);
      box(1.80, 0.55, 0.10, 0xf1eee7, SX, 0.910, -4.04, null, CER);
      box(0.10, 0.55, 0.96, 0xf1eee7, SX - 0.85, 0.910, -4.57, null, CER);
      box(0.10, 0.55, 0.96, 0xf1eee7, SX + 0.85, 0.910, -4.57, null, CER);
      box(1.60, 0.42, 0.96, 0x454b51, SX, 0.865, -4.57, null,
          { rough: 0.35, metal: 0.55 });
      if (KD3) {                            /* a drain, and a wet sheen */
        cyl(0.075, 0.075, 0.02, C.steel, SX, 1.082, -4.57, null, 12, CHROME);
        box(1.52, 0.01, 0.88, 0x5b656d, SX, 1.080, -4.57, null,
            { rough: 0.12, metal: 0.7 });
      }
      cyl(0.05, 0.06, 0.52, C.steel, SX, CT_Y + 0.26, NZ + 0.30, null, 12, CHROME);
      var neck = cyl(0.04, 0.04, 0.50, C.steel, SX, CT_Y + 0.50, NZ + 0.50,
                     null, 10, CHROME);
      neck.rotation.x = 1.25;
      cyl(0.035, 0.035, 0.20, C.steel, SX, CT_Y + 0.40, NZ + 0.72, null, 8, CHROME);
      cyl(0.05, 0.02, 0.04, C.steel, SX, CT_Y + 0.29, NZ + 0.72, null, 8, CHROME);
      cyl(0.028, 0.028, 0.13, C.steel, SX + 0.34, CT_Y + 0.10, NZ + 0.26,
          null, 8, CHROME);
      if (KD2) {                            /* the sink is a used sink */
        cyl(0.10, 0.12, 0.16, C.teal, SX + 0.52, CT_Y + 0.08, NZ + 0.28,
            null, 12, GLOSS);
        cyl(0.02, 0.02, 0.20, C.wood2, SX + 0.50, CT_Y + 0.22, NZ + 0.28,
            null, 6, WOODM);
        cyl(0.02, 0.02, 0.18, C.wood2, SX + 0.55, CT_Y + 0.21, NZ + 0.31,
            null, 6, WOODM);
      }
    })();

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
    rbox(2.14, 0.22, 0.14, 0.04, C.terracotta, 0, 4.14, 0.2, winG, { rough: 0.9 });
    rbox(2.1, 0.2, 0.12, 0.04, C.terraDeep, 0, 3.95, 0.19, winG, { rough: 0.9 });
    rbox(2.06, 0.18, 0.1, 0.04, C.terracotta, 0, 3.78, 0.18, winG, { rough: 0.9 });

    /* the window earns a real sill, and the sill earns its plants — two
       of the three kitchen plates put them there (S7.7) */
    box(2.24, 0.07, 0.34, C.cab, 0, 2.535, 0.185, winG, MATT);
    if (KD3) box(2.30, 0.05, 0.05, C.cabShade, 0, 2.485, 0.34, winG, MATT);
    if (KD2) {
      kPlant(winG, -0.74, 2.57, 0.20, 0.39, C.terracotta, { rough: 0.85 },
             'mound', false);
      kPlant(winG, 0.72, 2.57, 0.19, 0.38, C.cream, GLOSS, 'spray', false);
      kJar(winG, 0.13, 2.57, 0.22, 0.06, 0.17, C.teal);
    }

    /* ---- counter clutter (S7.6, S4) -----------------------------------
       Every surface over 0.5u2 carries at least two props: a coffee
       machine and mugs, a canister set, a crock of utensils, a board with
       produce, a kettle, a fruit bowl, a bread bin, a plant. */
    if (DETAIL >= 2) {
      /* the coffee station, run A left */
      rbox(0.46, 0.50, 0.40, 0.04, C.ink, -4.02, 1.38, -4.78, null, { rough: 0.5 });
      box(0.50, 0.06, 0.44, C.graphite, -4.02, 1.66, -4.78, null, STEEL);
      box(0.34, 0.05, 0.05, HW, -4.02, 1.19, -4.56, null, STEEL);
      if (KD3) {
        box(0.16, 0.10, 0.02, C.cream, -4.02, 1.52, -4.575, null, GLOSS);
        cyl(0.055, 0.05, 0.09, C.cream, -4.02, 1.185, -4.60, null, 10, GLOSS);
      }
      kCups(null, -3.62, 1.13, -4.30, 2, C.teal);
      /* canister set, three heights */
      kJar(null, -3.36, 1.13, -5.06, 0.105, 0.32, C.cream);
      kJar(null, -3.12, 1.13, -5.08, 0.090, 0.25, C.terracotta);
      kJar(null, -2.92, 1.13, -5.05, 0.075, 0.19, C.oxblood);
      /* the crock of utensils, run A right */
      cyl(0.115, 0.100, 0.30, C.terracotta, -0.86, 1.28, -5.04, null, 12, GLOSS);
      cyl(0.020, 0.020, 0.30, C.wood2, -0.90, 1.52, -5.06, null, 6, WOODM);
      cyl(0.020, 0.020, 0.26, C.wood2, -0.82, 1.50, -5.02, null, 6, WOODM);
      /* a board with produce on it */
      rbox(0.76, 0.05, 0.52, 0.02, kWoodK, -0.24, 1.155, -4.44, null, kWoodO);
      kSph(null, 0.085, C.oxblood, -0.40, 1.24, -4.48, 0.9);
      kSph(null, 0.075, C.oxblood, -0.24, 1.23, -4.36, 0.9);
      kSph(null, 0.070, C.leaf, -0.08, 1.23, -4.52, 0.8);
      /* the kettle: a body, a lid, a spout and a handle */
      cyl(0.175, 0.155, 0.26, C.terracotta, 0.44, 1.26, -4.94, null, 14, GLOSS);
      cyl(0.085, 0.105, 0.05, C.terracotta, 0.44, 1.415, -4.94, null, 12, GLOSS);
      if (KD3) {
        var sp = cyl(0.025, 0.055, 0.20, C.terracotta, 0.60, 1.34, -4.86,
                     null, 8, GLOSS);
        sp.rotation.z = -0.75; sp.rotation.y = 0.5;
        var hd = box(0.03, 0.03, 0.26, HW, 0.44, 1.47, -4.94, null, STEEL);
        hd.rotation.x = 0.0;
      }
      /* run B: a fruit bowl, a bread bin, bowls and a plant */
      cyl(0.26, 0.20, 0.15, C.cream, 2.98, 1.205, -4.60, null, 16, GLOSS);
      kSph(null, 0.075, C.oxblood, 2.90, 1.30, -4.62, 0.9);
      kSph(null, 0.070, C.brass, 3.06, 1.29, -4.55, 0.9);
      if (KD3) kSph(null, 0.065, C.leaf, 3.00, 1.31, -4.70, 0.85);
      rbox(0.54, 0.30, 0.36, 0.05, C.teal, 3.72, 1.28, -4.98, null, GLOSS);
      if (KD3) box(0.46, 0.02, 0.30, 0x2f9a92, 3.72, 1.44, -4.96, null, GLOSS);
      kPlates(null, 3.66, 1.13, -4.34, 0.135, C.linen);
      kPlant(null, 4.48, 1.13, -4.66, 0.39, C.terracotta, { rough: 0.85 },
             'fiddle', false);
      kJar(null, 4.14, 1.13, -5.08, 0.085, 0.24, C.teal);
      /* the L-return: a toaster, jars and a plant */
      rbox(0.44, 0.28, 0.30, 0.05, C.steel, -6.30, 1.28, -2.62, null, STEEL);
      if (KD3) {
        box(0.02, 0.05, 0.20, C.graphite, -6.07, 1.30, -2.62, null, STEEL);
        box(0.30, 0.03, 0.12, C.cabShade, -6.30, 1.43, -2.62, null, MATT);
      }
      kJar(null, -6.36, 1.13, -2.24, 0.095, 0.28, C.oxblood);
      kJar(null, -6.34, 1.13, -2.02, 0.075, 0.20, C.cream);
      kPlant(null, -6.22, 1.13, -1.78, 0.38, C.linen, { rough: 0.8 },
             'spray', false);
    }

    /* ---- STOVE (zone: counter) with hood ------------------------------- */
    var counter = zoneGroup('counter', 1.7, 0, -4.55);
    box(1.40, 0.07, 1.32, C.ink, 0, 0.035, 0, counter, { rough: 0.7 });
    rbox(1.5, 1.02, 1.45, 0.05, 0x3f444a, 0, 0.57, 0, counter, { rough: 0.45, metal: 0.5 });
    box(1.3, 0.62, 0.06, 0x556069, 0, 0.5, 0.74, counter, STEEL);
    if (DETAIL >= 3) box(0.9, 0.34, 0.02, 0x1c2024, 0, 0.5, 0.78, counter, GLOSS);
    box(1.1, 0.06, 0.09, C.steel, 0, 0.86, 0.78, counter, CHROME);
    box(1.5, 0.05, 1.45, 0x2e3237, 0, 1.11, 0, counter, { rough: 0.35, metal: 0.4 });
    cyl(0.16, 0.16, 0.03, 0x14161a, -0.4, 1.15, 0.3, counter, 12);
    cyl(0.16, 0.16, 0.03, 0x14161a, 0.4, 1.15, 0.3, counter, 12);
    cyl(0.16, 0.16, 0.03, 0x14161a, -0.4, 1.15, -0.35, counter, 12);
    cyl(0.16, 0.16, 0.03, 0x14161a, 0.4, 1.15, -0.35, counter, 12);
    if (DETAIL >= 3) {                 /* grates: a cooktop, not a slab */
      [-0.4, 0.4].forEach(function (gx) {
        [0.3, -0.35].forEach(function (gz) {
          box(0.40, 0.022, 0.05, C.graphite, gx, 1.175, gz, counter, MATT);
          box(0.05, 0.022, 0.40, C.graphite, gx, 1.175, gz, counter, MATT);
        });
      });
    }
    cyl(0.3, 0.3, 0.3, 0x9aa2a9, -0.4, 1.32, 0.3, counter, 16, STEEL);
    cyl(0.31, 0.31, 0.05, 0x7d858c, -0.4, 1.5, 0.3, counter, 16, STEEL);
    cyl(0.26, 0.26, 0.22, C.terracotta, 0.4, 1.28, -0.35, counter, 16, GLOSS);
    var steam = box(0.16, 0.5, 0.16, 0xf2ead6, -0.4, 2.0, 0.3, counter);
    steam.material.transparent = true; steam.material.opacity = 0;
    if (SHADOWS) steam.castShadow = false;
    var steam2 = box(0.1, 0.34, 0.1, 0xf2ead6, -0.32, 2.35, 0.34, counter);
    steam2.material.transparent = true; steam2.material.opacity = 0;
    if (SHADOWS) steam2.castShadow = false;
    /* ---- the HOOD: every kitchen plate has one and it is the room's
       dark anchor (S7.5). A lip, a tapered canopy, a chimney to the line
       the uppers stop on, brass banding, and two warm downlights so the
       cooktop sits in a pool of light. ---- */
    (function () {
      /* the lip hangs a working distance over the cooktop, not up level
         with the uppers — a hood that high reads as a chimney breast */
      /* sized to the RANGE, not to the wall: the lip is the cooktop's
         1.50 plus a 0.04 reveal each side, and the canopy is shallower
         than the counter, so the hood never leans out over the aisle.
         A hood wider than the appliance reads as extraction plant. */
      var HY0 = 2.10, LIPW = 1.58, LIPD = 1.06, WZ = NZ + 4.55;  /* wall, local */
      box(LIPW, 0.09, LIPD, C.ink, 0, HY0 + 0.045, WZ + LIPD / 2, counter,
          { rough: 0.45 });
      if (KD2) box(LIPW + 0.03, 0.045, LIPD + 0.03, HW, 0, HY0 + 0.012,
                   WZ + LIPD / 2, counter, STEEL);
      var hg = new T.Group();
      hg.position.set(0, HY0 + 0.40, WZ + 0.53);
      hg.scale.z = 0.672;
      counter.add(hg);
      var can = cyl(0.556, 1.061, 0.62, C.ink, 0, 0, 0, hg, 4, { rough: 0.45 });
      can.rotation.y = Math.PI / 4;
      box(0.76, 1.44, 0.46, C.ink, 0, HY0 + 1.440, WZ + 0.23, counter,
          { rough: 0.45 });
      if (KD2) {
        box(0.80, 0.05, 0.50, HW, 0, HY0 + 0.750, WZ + 0.23, counter, STEEL);
        box(0.80, 0.05, 0.50, HW, 0, HY0 + 2.110, WZ + 0.23, counter, STEEL);
      }
      /* the underside is not the same black: a lit hood glows */
      var und = new T.Mesh(new T.PlaneGeometry(LIPW - 0.16, LIPD - 0.16),
        PBR ? new T.MeshStandardMaterial({ color: 0x30363c, roughness: 0.6,
                                           emissive: 0xffca7a,
                                           emissiveIntensity: 0.16 })
            : new T.MeshLambertMaterial({ color: 0x4a5158 }));
      und.rotation.x = Math.PI / 2;
      und.position.set(0, HY0 - 0.002, WZ + LIPD / 2);
      counter.add(und);
      if (KD3) [-0.42, 0.42].forEach(function (lx) {
        var lp = new T.Mesh(new T.CircleGeometry(0.085, 12),
          new T.MeshBasicMaterial({ color: 0xffe6b4 }));
        lp.rotation.x = Math.PI / 2;
        lp.position.set(lx, HY0 - 0.006, WZ + LIPD / 2);
        counter.add(lp);
      });
    })();
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
    if (DETAIL >= 2)                    /* a plinth: appliances have feet */
      box(1.72, 0.13, 0.06, C.graphite, 0, 0.065, 0.72, fridge, { rough: 0.6 });
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
    if (DETAIL >= 2) {
      /* a door is stiles, rails and two panels (S3.1). These are CHILDREN
         of the slab so they step aside with it on the board lean-in. */
      [[0.62, 1.10], [-0.72, 1.26]].forEach(function (pn) {
        box(0.02, pn[1], 1.12, 0x6f5433, 0.07, pn[0], 0, pantryDoor,
            { rough: 0.8 }).userData.zone = 'board';
        box(0.04, pn[1] - 0.18, 0.94, 0xc79b63, 0.085, pn[0], 0, pantryDoor,
            PBR ? { rough: 0.7, map: woodDoor } : { rough: 0.75 })
          .userData.zone = 'board';
      });
      box(0.03, 0.12, 1.22, 0x6f5433, 0.075, -0.02, 0, pantryDoor,
          { rough: 0.8 }).userData.zone = 'board';
      /* casing stays on the wall: it frames the card when the door opens */
      box(0.22, 3.36, 0.14, 0xe4ddd1, 0.16, 1.68, -0.87, board);
      box(0.22, 3.36, 0.14, 0xe4ddd1, 0.16, 1.68, 0.87, board);
      box(0.22, 0.14, 1.88, 0xe4ddd1, 0.16, 3.29, 0, board);
    }
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
      /* ---- the closet's §3.2 treatment (bible S7 mudroom.4) -----------
         Shelf boards with a visible front edge on a back panel one shade
         darker and inset, a divider, and STOCK: tins, boxes, a crock, a
         sack. None of it is a jar and none of it sits on the jars' line
         at x -8.05..-7.85, because the JARS are the signal — one leaves
         for every open shopping item, and a long list still has to make
         these shelves look bare. */
      var PD2 = DETAIL >= 2, PD3 = DETAIL >= 3;
      function ptag(m) {
        if (m) { m.userData.zone = 'board'; m.userData.room = 'kitchen'; }
        return m;
      }
      function pb(w, h, d, c, x, y, z, o) {
        return ptag(box(w, h, d, c, x, y, z, null, o));
      }
      function pr(w, h, d, r, c, x, y, z, o) {
        return ptag(rbox(w, h, d, r, c, x, y, z, null, o));
      }
      function pc(rt, rb, h, c, x, y, z, s, o) {
        return ptag(cyl(rt, rb, h, c, x, y, z, null, s, o));
      }
      pb(0.03, 3.10, 2.00, KBAY, -8.46, 1.75, -0.60, { rough: 0.95 });
      [0.9, 1.7, 2.5].forEach(function (sy) {
        pb(0.02, 0.065, 2.00, C.cabShade, -7.345, sy, -0.60, MATT);
        if (PD3) {
          pb(1.16, 0.03, 0.04, C.cabShade, -7.95, sy - 0.045, -1.58, MATT);
          pb(1.16, 0.03, 0.04, C.cabShade, -7.95, sy - 0.045, 0.38, MATT);
        }
      });
      pb(1.05, 3.10, 0.05, C.cab, -7.925, 1.75, -0.94, MATT);
      /* the stock. Tins and boxes, never jars. */
      function tin(x, y, z, r, h, c) {
        pc(r, r, h, c, x, y + h / 2, z, 12, GLOSS);
        if (PD3) pc(r * 1.06, r * 1.06, 0.035, C.cabShade, x, y + h - 0.01, z,
                    12, MATT);
      }
      function crock(x, y, z, r, h, c) {
        pc(r * 0.86, r, h, c, x, y + h / 2, z, 14, GLOSS);
        pc(r * 0.72, r * 0.9, 0.06, c, x, y + h + 0.02, z, 14, GLOSS);
      }
      function sack(x, y, z, r, h, c) {
        pc(r * 0.62, r, h, c, x, y + h / 2, z, 12, { rough: 0.98 });
        if (PD3) pc(r * 0.30, r * 0.60, 0.10, c, x, y + h + 0.04, z, 10,
                    { rough: 0.98 });
      }
      function carton(x, y, z, w, h, d, c) {
        pr(w, h, d, 0.02, c, x, y + h / 2, z, MATT);
        if (PD3) pb(w * 0.62, h * 0.42, 0.01, C.cabShade, x, y + h * 0.6,
                    z + d / 2 + 0.006, MATT);
      }
      if (PD2) {
        /* shelf 1 (top 0.93) — the jars own the middle band */
        sack(-8.28, 0.93, -1.30, 0.16, 0.30, C.linen);
        crock(-8.26, 0.93, -0.30, 0.15, 0.24, C.terracotta);
        tin(-7.56, 0.93, -1.44, 0.085, 0.20, C.sage);
        tin(-7.56, 0.93, -1.16, 0.075, 0.16, C.cream);
        carton(-7.56, 0.93, 0.10, 0.22, 0.26, 0.20, C.cork);
        if (PD3) tin(-7.58, 0.93, 0.34, 0.07, 0.13, C.stone);
        /* shelf 2 (top 1.73) */
        carton(-8.28, 1.73, -1.24, 0.24, 0.22, 0.26, C.linen);
        carton(-8.28, 1.95, -1.24, 0.20, 0.16, 0.22, C.cream);
        crock(-8.26, 1.73, -0.26, 0.13, 0.20, C.cream);
        tin(-7.56, 1.73, -1.48, 0.08, 0.22, C.stone);
        pr(0.24, 0.20, 0.34, 0.03, C.cork, -7.58, 1.83, -0.56, { rough: 0.98 });
        carton(-7.56, 1.73, 0.12, 0.20, 0.24, 0.18, C.sage);
        /* shelf 3 (top 2.53) — no jars here, so it carries a full bay */
        pr(0.30, 0.26, 0.42, 0.03, C.cork, -7.95, 2.66, -1.28, { rough: 0.98 });
        if (PD3) pb(0.33, 0.05, 0.45, 0x8f6a3f, -7.95, 2.77, -1.28, MATT);
        carton(-8.20, 2.53, -0.72, 0.24, 0.28, 0.22, C.linen);
        tin(-7.60, 2.53, -0.76, 0.09, 0.24, C.cream);
        crock(-7.94, 2.53, -0.12, 0.16, 0.26, C.stone);
        tin(-8.24, 2.53, 0.18, 0.085, 0.19, C.sage);
        if (PD3) carton(-7.58, 2.53, 0.24, 0.20, 0.20, 0.18, C.cork);
        /* the closet floor: a crate, a bin and a sack of potatoes */
        pr(0.60, 0.36, 0.52, 0.03, C.cork, -7.90, 0.24, -1.24, { rough: 0.98 });
        if (PD3) pb(0.63, 0.05, 0.55, 0x8f6a3f, -7.90, 0.44, -1.24, MATT);
        pc(0.19, 0.16, 0.46, C.stone, -7.66, 0.26, -0.42, 12, MATT);
        sack(-8.16, 0.03, 0.14, 0.20, 0.44, C.linen);
      }
    })();
    var pantryJars = [];
    (function () {
      /* the kitchen's four accents, no strays (bible S2/S4) */
      var JAR_C = [C.terracotta, C.oxblood, C.teal, C.brass];
      for (var j = 0; j < 8; j++) {
        var jy = j < 4 ? 1.06 : 1.86;
        var jar = cyl(0.1, 0.1, 0.26, JAR_C[j % 4],
                      -1.53, jy, -1.06 + (j % 4) * 0.48, board, 10, GLOSS);
        jar.userData.zone = 'board';
        pantryJars.push(jar);
      }
    })();
    /* ---- WALL CALENDAR (zone: calendar) on the back wall --------------- */
    var calG = zoneGroup('calendar', 3.92, 0, -5.36);
    var calFace = new T.Mesh(new T.PlaneGeometry(1.5, 1.9), mat(0xf6f1e4, { rough: 0.9 }));
    calFace.position.set(0, 3.0, 0.05);
    calG.add(calFace);
    box(1.62, 0.1, 0.08, C.oxblood, 0, 4.0, 0.02, calG, GLOSS);
    if (DETAIL >= 3) {                  /* wall clock between calendar and door */
      var clockFace = cyl(0.3, 0.3, 0.06, 0xffffff, 3.92, 4.88, -5.34, null, 20, GLOSS);
      clockFace.rotation.x = Math.PI / 2;
      cyl(0.34, 0.34, 0.04, HW, 3.92, 4.88, -5.35, null, 20, STEEL)
        .rotation.x = Math.PI / 2;
      box(0.03, 0.18, 0.02, C.dark, 3.92, 4.93, -5.28);
      box(0.13, 0.03, 0.02, C.dark, 3.97, 4.88, -5.28);
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

    /* ---- ISLAND: walnut casework under a marble top ---------------------
       The room was cream on cream; the island is the biggest object below
       the counter line, so it carries the mid-dark note that gives the
       floor plane an edge. Real casework (S3.1) on the face the camera
       actually sees — the south side. */
    kCase(-0.4, 0.9, 0, 3.40, 2.00, 0, CT_Y - CT_T, [
      { h: CT_Y - CT_T - TOE, cells: [
        { w: 1.10, kind: 'drawers3' }, { w: 1.30, kind: 'doors2' },
        { w: 1.00, kind: 'drawers2' }] }
    ], { toe: true, face: 0x6f5540, body: 0x584129 });
    var islandTop = new T.Mesh(
      NICE ? roundedGeo(3.74, CT_T, 2.34, 0.03) : new T.BoxGeometry(3.74, CT_T, 2.34),
      PBR ? new T.MeshStandardMaterial({ map: marble, color: 0xe4dfd5,
                                         roughness: 0.24, envMapIntensity: 0.3 })
          : new T.MeshLambertMaterial({ color: 0xe4dfd5, map: marble || null }));
    islandTop.position.set(-0.4, CT_Y - CT_T / 2, 0.9);
    finish(islandTop); scene.add(islandTop);
    if (DETAIL >= 2) {
      /* a rail on the east end: an island is a place people put a towel */
      cyl(0.02, 0.02, 0.90, HW, 1.36, 0.86, 0.90, null, 8, STEEL).rotation.x = Math.PI / 2;
      rbox(0.26, 0.44, 0.05, 0.02, C.teal, 1.36, 0.68, 0.72, null, { rough: 0.98 });
      /* the top carries six things, none of them the same height (S4) */
      rbox(1.06, 0.05, 0.70, 0.02, kWoodK, -1.30, 1.155, 0.86, null, kWoodO);
      kCups(null, -1.62, 1.18, 0.72, 3, C.cream);
      cyl(0.09, 0.11, 0.15, C.teal, -1.06, 1.255, 0.94, null, 12, GLOSS);
      cyl(0.30, 0.22, 0.16, C.cream, 0.62, 1.21, 0.72, null, 16, GLOSS);
      kSph(null, 0.080, C.terracotta, 0.52, 1.31, 0.68, 0.9);
      kSph(null, 0.075, C.brass, 0.72, 1.30, 0.78, 0.9);
      kSph(null, 0.070, C.leaf, 0.64, 1.31, 0.62, 0.85);
      /* a cookbook left open, and a jug of branches */
      box(0.34, 0.06, 0.26, C.oxblood, -0.28, 1.16, 1.52, null, MATT);
      box(0.32, 0.05, 0.24, C.cream, -0.28, 1.215, 1.53, null, MATT);
      cyl(0.11, 0.13, 0.30, C.terracotta, 0.96, 1.28, 1.44, null, 12, GLOSS);
      cyl(0.02, 0.02, 0.42, C.wood2, 0.94, 1.60, 1.44, null, 6, WOODM);
      cyl(0.02, 0.02, 0.34, C.wood2, 1.00, 1.56, 1.50, null, 6, WOODM);
    }
    if (DETAIL >= 3) {
      kSph(null, 0.075, C.leaf, 0.92, 1.80, 1.42, 0.8);
      kSph(null, 0.065, C.leaf, 1.02, 1.72, 1.51, 0.8);
      kPlant(null, -1.94, 1.13, 1.42, 0.37, C.terracotta, { rough: 0.85 },
             'mound', false);
      box(0.30, 0.05, 0.22, C.slate, -0.32, 1.265, 1.51, null, MATT);
    }
    blobShadow(2.1, 1.4, -0.4, 0.9);
    /* a stool: a turned column, a footring and a saddle seat */
    function stool(x, z) {
      var seat = new T.Mesh(new T.CylinderGeometry(0.30, 0.26, 0.08, 14),
        PBR ? new T.MeshStandardMaterial({ map: woodLight, roughness: 0.6 })
            : new T.MeshLambertMaterial({ color: 0xc89a66, map: woodLight || null }));
      seat.position.set(x, 0.86, z); finish(seat); scene.add(seat);
      cyl(0.05, 0.07, 0.84, C.wood2, x, 0.42, z, null, 10, WOODM);
      if (DETAIL >= 2) {
        cyl(0.20, 0.22, 0.03, C.wood2, x, 0.26, z, null, 12, WOODM);
        cyl(0.17, 0.19, 0.03, C.wood2, x, 0.04, z, null, 12, WOODM);
      }
      blobShadow(0.34, 0.3, x, z);
    }
    stool(1.90, 0.12); stool(1.90, 1.08);
    stool(-1.32, 2.62); stool(0.18, 2.62);

    /* ---- the kitchen floor (S7.1) --------------------------------------
       Bare plank was over half the frame and the island was the only
       object below the counter line. A runner down the work aisle, a mat
       at the pantry, floor plants, and a family table with four chairs on
       its own rug in the east half — which is the foreground. */
    function kRug(w, d, x, z, fieldC, borderC, round) {
      /* below tier 2 the field never draws, so the base plane wears the
         field colour there: a Pi should see a rug, not a dark slab */
      var m = new T.Mesh(round ? new T.CircleGeometry(w, KD3 ? 30 : 16)
                               : new T.PlaneGeometry(w, d),
                         mat(KD2 ? borderC : fieldC, { rough: 1.0 }));
      m.rotation.x = -Math.PI / 2;
      m.position.set(x, 0.045, z);
      if (SHADOWS) m.receiveShadow = true;
      scene.add(m);
      if (KD2) {
        var m2 = new T.Mesh(round ? new T.CircleGeometry(w - 0.17, KD3 ? 30 : 16)
                                  : new T.PlaneGeometry(w - 0.26, d - 0.26),
                            mat(fieldC, { rough: 1.0 }));
        m2.rotation.x = -Math.PI / 2;
        m2.position.set(x, 0.052, z);
        scene.add(m2);
      }
      if (KD3) {                 /* the inner line every woven rug has */
        [[0.46, borderC, 0.057], [0.58, fieldC, 0.062]].forEach(function (k) {
          var mi = new T.Mesh(round ? new T.CircleGeometry(w - k[0], 30)
                                    : new T.PlaneGeometry(w - k[0], d - k[0]),
                              mat(k[1], { rough: 1.0 }));
          mi.rotation.x = -Math.PI / 2;
          mi.position.set(x, k[2], z);
          scene.add(mi);
        });
      }
      return m;
    }
    /* a chair: splayed legs, a seat with a pad, and a raked back */
    function kChair(x, z, rot) {
      var g = new T.Group();
      g.position.set(x, 0, z);
      g.rotation.y = rot || 0;
      scene.add(g);
      [[-0.21, -0.21], [0.21, -0.21], [-0.21, 0.21], [0.21, 0.21]]
        .forEach(function (lg) {
          var m = cyl(0.034, 0.026, 0.58, C.wood2, lg[0], 0.29, lg[1], g, 8, WOODM);
          m.rotation.z = lg[0] < 0 ? -0.07 : 0.07;
          m.rotation.x = lg[1] < 0 ? 0.07 : -0.07;
        });
      rbox(0.52, 0.06, 0.50, 0.02, kWoodK, 0, 0.585, 0, g, kWoodO);
      if (KD2) rbox(0.46, 0.08, 0.44, 0.03, C.linen, 0, 0.652, 0.01, g,
                    { rough: 0.98 });
      [-0.23, 0.23].forEach(function (dx) {
        var u = cyl(0.028, 0.028, 0.64, C.wood2, dx, 0.90, -0.245, g, 8, WOODM);
        u.rotation.x = -0.11;
      });
      rbox(0.50, 0.10, 0.05, 0.02, kWoodK, 0, 1.185, -0.30, g, kWoodO);
      if (KD2) rbox(0.46, 0.07, 0.04, 0.02, kWoodK, 0, 0.94, -0.26, g, kWoodO);
      blobShadow(0.30, 0.30, x, z);
      return g;
    }
    /* the family table: the foreground the room did not have */
    (function () {
      var TX = 4.45, TZ = 1.35;
      kRug(1.92, 0, TX, TZ, 0x9a8360, 0x7d4531, true);
      cyl(0.98, 0.98, 0.08, kWoodK, TX, 0.940, TZ, null, KD3 ? 28 : 14, kWoodO);
      if (KD3) cyl(0.96, 0.92, 0.05, C.wood2, TX, 0.878, TZ, null, 28, WOODM);
      cyl(0.13, 0.17, 0.84, C.wood2, TX, 0.46, TZ, null, 12, WOODM);
      [0, 1, 2, 3].forEach(function (i) {
        var a = i * Math.PI / 2 + Math.PI / 4;
        var f = box(0.66, 0.09, 0.15, C.wood2, TX + Math.cos(a) * 0.26, 0.055,
                    TZ + Math.sin(a) * 0.26, null, WOODM);
        f.rotation.y = -a;
      });
      blobShadow(0.95, 0.95, TX, TZ);
      kChair(TX, TZ - 1.58, 0);
      kChair(TX - 1.42, TZ, Math.PI / 2);
      kChair(TX + 1.42, TZ, -Math.PI / 2);
      kChair(TX + 0.10, TZ + 1.62, Math.PI);
      if (DETAIL >= 2) {                       /* laid, not staged */
        cyl(0.24, 0.19, 0.13, C.cream, TX - 0.06, 1.045, TZ - 0.10, null, 16, GLOSS);
        kSph(null, 0.075, C.oxblood, TX - 0.12, 1.13, TZ - 0.14, 0.9);
        kSph(null, 0.070, C.brass, TX + 0.02, 1.12, TZ - 0.05, 0.9);
        cyl(0.085, 0.10, 0.26, C.teal, TX + 0.44, 1.11, TZ + 0.30, null, 12, GLOSS);
        cyl(0.018, 0.018, 0.34, C.wood2, TX + 0.43, 1.38, TZ + 0.30, null, 6, WOODM);
        kSph(null, 0.07, C.leaf, TX + 0.42, 1.55, TZ + 0.29, 0.8);
        kSph(null, 0.06, C.leaf, TX + 0.50, 1.48, TZ + 0.34, 0.8);
        rbox(0.34, 0.02, 0.26, 0.01, C.oxblood, TX - 0.48, 0.988, TZ + 0.34, null,
             { rough: 0.98 });
        rbox(0.34, 0.02, 0.26, 0.01, C.oxblood, TX + 0.42, 0.988, TZ - 0.36, null,
             { rough: 0.98 });
        if (KD3) {
          kPlates(null, TX - 0.48, 0.998, TZ + 0.34, 0.115, C.cream);
          kPlates(null, TX + 0.42, 0.998, TZ - 0.36, 0.115, C.cream);
        }
      }
    })();
    /* the work aisle gets a runner; the pantry gets a mat */
    kRug(5.30, 1.14, -1.85, -2.92, 0x7c4130, 0x4a2a24, false);
    /* floor plants: three, no two of them the same silhouette, and each
       one set against something a person would stand it beside — the
       larder, the island's west end, the table's east chair. A plant
       alone on open plank decorates a gap; it does not furnish a room
       (S1's 0.6 rule). Under the 0.9-unit floor cap, and smaller than
       the furniture they stand next to. */
    kPlant(null, 5.98, 0, -3.72, 0.86, C.terracotta, { rough: 0.85 }, 'fiddle', true);
    kPlant(null, -3.06, 0, 1.78, 0.76, C.linen, { rough: 0.8 }, 'spray', true);
    kPlant(null, 1.72, 0, 2.42, 0.82, C.cream, GLOSS, 'mound', true);
    /* the path in from the mudroom door, so the south-west corner is a
       route and not an empty plank field */
    kRug(3.20, 1.10, -4.85, 3.60, 0x8d5a3c, 0x4a2a24, false);
    /* a drop bench under the prints: this is where a family puts a bag
       down, and it is what stopped the west wall reading as a blank */
    (function () {
      var BX = -6.14, BZ = 1.78;
      rbox(0.62, 0.08, 1.58, 0.02, kWoodK, BX, 0.615, BZ, westWallG, kWoodO);
      [[-0.22, -0.66], [0.22, -0.66], [-0.22, 0.66], [0.22, 0.66]]
        .forEach(function (lg) {
          cyl(0.045, 0.036, 0.58, C.wood2, BX + lg[0], 0.29, BZ + lg[1],
              westWallG, 8, WOODM);
        });
      box(0.50, 0.05, 1.38, C.wood2, BX, 0.24, BZ, westWallG, WOODM);
      if (DETAIL >= 2) {
        cyl(0.19, 0.16, 0.26, C.cork, BX, 0.38, BZ - 0.46, westWallG, 12,
            { rough: 0.95 });
        rbox(0.40, 0.26, 0.40, 0.04, C.linen, BX, 0.38, BZ + 0.44, westWallG,
             { rough: 0.95 });
        rbox(0.36, 0.15, 0.36, 0.07, C.teal, BX + 0.02, 0.73, BZ - 0.48,
             westWallG, { rough: 0.98 });
        if (KD3) {
          box(0.30, 0.06, 0.22, C.oxblood, BX + 0.04, 0.685, BZ + 0.42, westWallG);
          box(0.28, 0.05, 0.20, C.cream, BX + 0.04, 0.740, BZ + 0.43, westWallG);
        }
      }
      blobShadow(0.34, 0.82, BX, BZ, westWallG);
    })();
    if (DETAIL >= 2) {
      cyl(0.22, 0.19, 0.62, C.graphite, -4.30, 0.31, -3.42, null, 12,
          { rough: 0.5, metal: 0.4 });
      cyl(0.23, 0.23, 0.05, C.steel, -4.30, 0.645, -3.42, null, 12, STEEL);
      blobShadow(0.26, 0.26, -4.30, -3.42);
      cyl(0.30, 0.25, 0.36, C.cork, -6.02, 0.18, -1.92, null, 12, { rough: 0.95 });
      kSph(null, 0.10, C.terracotta, -6.06, 0.40, -1.96, 0.8);
      kSph(null, 0.09, C.leaf, -5.96, 0.39, -1.88, 0.8);
      blobShadow(0.32, 0.32, -6.02, -1.92);
    }
    /* a rolling prep cart: the west half of the floor was a 6-unit hole
       between the island and the pantry, and a cart is what a kitchen
       actually puts there */
    (function () {
      var RX = -4.20, RZ = 1.35;
      rbox(1.00, 0.08, 0.58, 0.02, kWoodK, RX, 0.98, RZ, null, kWoodO);
      [[-0.42, -0.22], [0.42, -0.22], [-0.42, 0.22], [0.42, 0.22]]
        .forEach(function (lg) {
          cyl(0.032, 0.032, 0.86, C.graphite, RX + lg[0], 0.51, RZ + lg[1],
              null, 8, STEEL);
          if (DETAIL >= 2)
            cyl(0.055, 0.055, 0.06, C.ink, RX + lg[0], 0.06, RZ + lg[1],
                null, 8, { rough: 0.6 });
        });
      box(0.92, 0.05, 0.50, C.wood2, RX, 0.58, RZ, null, WOODM);
      box(0.92, 0.05, 0.50, C.wood2, RX, 0.26, RZ, null, WOODM);
      cyl(0.02, 0.02, 0.62, C.graphite, RX + 0.53, 0.98, RZ, null, 8, STEEL)
        .rotation.x = Math.PI / 2;
      if (DETAIL >= 2) {
        kJar(null, RX - 0.34, 1.02, RZ - 0.10, 0.085, 0.24, C.terracotta);
        kJar(null, RX - 0.16, 1.02, RZ + 0.06, 0.070, 0.17, C.teal);
        kBowl(null, RX + 0.10, 1.02, RZ - 0.06, 0.145, C.cream);
        kPlant(null, RX + 0.36, 1.02, RZ + 0.04, 0.36, C.linen, { rough: 0.8 },
               'fiddle', false);
        cyl(0.155, 0.145, 0.16, C.oxblood, RX - 0.26, 0.665, RZ, null, 12, GLOSS);
        kPlates(null, RX + 0.22, 0.605, RZ, 0.145, C.linen);
        rbox(0.32, 0.42, 0.05, 0.02, C.teal, RX + 0.53, 0.78, RZ, null,
             { rough: 0.98 });
        if (KD3) {
          rbox(0.36, 0.20, 0.30, 0.04, C.cork, RX - 0.28, 0.365, RZ, null,
               { rough: 0.95 });
          kJar(null, RX + 0.22, 0.285, RZ - 0.02, 0.075, 0.20, C.brass);
        }
      }
      blobShadow(0.54, 0.34, RX, RZ);
    })();
    /* the two floor baskets: neither one stands on open plank any more.
       The lidded one goes at the foot of the larder, beside its plant;
       the cushioned one is pushed under the island's overhang between
       two stools, which is where a family actually keeps one. */
    if (DETAIL >= 2) {
      cyl(0.30, 0.25, 0.40, C.cork, 5.20, 0.20, -3.70, null, 14, { rough: 0.95 });
      cyl(0.31, 0.31, 0.05, C.linen, 5.20, 0.425, -3.70, null, 14, { rough: 0.95 });
      blobShadow(0.32, 0.32, 5.20, -3.70);
      cyl(0.27, 0.23, 0.34, C.cork, -0.57, 0.17, 2.66, null, 12, { rough: 0.95 });
      rbox(0.30, 0.13, 0.30, 0.06, C.teal, -0.57, 0.40, 2.66, null, { rough: 0.98 });
      blobShadow(0.29, 0.29, -0.57, 2.66);
    }

    /* the west wall's blank panel: two prints and a sconce (S4) */
    function kArt(y, z, h, w, art) {
      rbox(0.05, h, w, 0.012, C.slate, WXK + 0.025, y, z, westWallG,
           { rough: 0.55 });
      if (KD3) box(0.02, h - 0.05, w - 0.05, C.cream, WXK + 0.050, y, z,
                   westWallG, MATT);
      box(0.02, h - 0.13, w - 0.13, art, WXK + 0.058, y, z, westWallG, MATT);
    }
    if (DETAIL >= 2) {
      kArt(2.72, 1.05, 0.74, 0.56, C.teal);
      kArt(2.72, 1.83, 0.74, 0.56, C.terracotta);
      if (KD3) kArt(1.92, 1.44, 0.52, 0.40, C.oxblood);
      /* the one wall light (plate 7). It hangs over the prints, NOT over
         the L-return: the fridge lean-in flies up that stretch of wall and
         anything on it lands on the fridge door's card. */
      box(0.07, 0.16, 0.16, HW, WXK + 0.035, 3.62, 1.44, westWallG, STEEL);
      cyl(0.02, 0.02, 0.26, HW, WXK + 0.16, 3.62, 1.44, westWallG, 8, STEEL);
      var scs = new T.Mesh(new T.CylinderGeometry(0.13, 0.19, 0.20, 14, 1, true),
        PBR ? new T.MeshStandardMaterial({ color: 0xf3e8d2, roughness: 0.8,
                                           emissive: 0xffd9a0,
                                           emissiveIntensity: 0.4,
                                           side: T.DoubleSide })
            : new T.MeshLambertMaterial({ color: 0xf3e8d2, side: T.DoubleSide }));
      scs.position.set(WXK + 0.29, 3.56, 1.44);
      finish(scs, true); westWallG.add(scs);
    }

    /* pendant lamps over the island: warm emissive shades. Grouped so a
       lean-in can hide them — a cord across a focused card breaks the
       card-on-the-surface illusion. */
    var pendants = new T.Group();
    scene.add(pendants);
    if (DETAIL >= 3) {
      /* centred on the island's long axis (x -2.27..1.47) and on its
         short axis (z 0.9), spaced along the run. They used to hang 1.8
         units over the marble — a room light, not a task light, and from
         the diorama camera that much air reads as a pendant over the
         walkway. 1.05 units (0.79 m) is where a pendant belongs. */
      [[-1.10, 0.9], [0.40, 0.9]].forEach(function (p) {
        var cord = cyl(0.008, 0.008, 3.17, 0x8a8178, p[0], 4.035, p[1], pendants, 6);
        cord.castShadow = false;   // a hair-thin cord throws a room-long streak
        var shade = new T.Mesh(new T.CylinderGeometry(0.24, 0.34, 0.30, 18, 1, true),
          new T.MeshStandardMaterial({ color: 0xf0e3c8, roughness: 0.7,
                                       emissive: 0xffdf9e, emissiveIntensity: 0.55,
                                       side: T.DoubleSide }));
        shade.position.set(p[0], 2.30, p[1]);
        shade.castShadow = false;
        pendants.add(shade);
        var cap = cyl(0.05, 0.05, 0.06, C.brass, p[0], 2.45, p[1], pendants, 10,
                      STEEL);
        cap.castShadow = false;
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
    /* the siding's own cut, where the facade runs past the wall */
    ebox(0.09, 7.0, 0.36, C.linen, 7.93, 3.5, -5.95, { rough: 0.9 });
    /* a corner board: clapboard always ends in one, and it is what
       makes the mass read as a built volume, not a sliced solid */
    ebox(0.26, 7.0, 0.10, EXTC.trim, 7.77, 3.5, -5.75, { rough: 0.9 });
    ebox(0.10, 7.0, 0.36, EXTC.trim, 7.95, 3.5, -5.95, { rough: 0.9 });
    /* the one exterior wall this camera sees square on: give it a real
       window - casing, sill, mullions and GLAZING the lighting pass can
       make warm from the inside (S7.3) */
    (function () {
      var wx = 7.10, wy = 3.60;          /* the siding's face is z = -5.80 */
      var gl = ebox(0.84, 1.34, 0.03, 0x9fc4dc, wx, wy, -5.775,
                    { rough: 0.16, metal: 0.0, envInt: 0.6 });
      gl.userData.glazing = true;        /* the lighting pass looks for this */
      ebox(1.12, 0.13, 0.16, EXTC.trim, wx, wy + 0.735, -5.73, { rough: 0.9 });
      [-0.555, 0.555].forEach(function (dx) {
        ebox(0.14, 1.60, 0.16, EXTC.trim, wx + dx, wy, -5.73, { rough: 0.9 });
      });
      ebox(1.28, 0.10, 0.30, EXTC.trim, wx, wy - 0.745, -5.68, { rough: 0.9 });
      if (DETAIL >= 2) {
        ebox(0.06, 1.34, 0.06, EXTC.trim, wx, wy, -5.752, { rough: 0.9 });
        ebox(0.84, 0.06, 0.06, EXTC.trim, wx, wy, -5.752, { rough: 0.9 });
      }
    })();
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
    ebox(16.5, 0.10, 0.06, C.stone, 0.3, 7.90, -0.315, { rough: 0.9 });
    /* rake boards: the roof's own cut edge, both gable ends of both
       slopes, offset down the slope so they hang under the shingles */
    [[-4.2, roofSpan, -Math.atan2(2.3, 4.4)],
     [-1.15, 2.0, Math.atan2(0.85, 1.6)]].forEach(function (rf) {
      var ca = Math.cos(rf[2]), sa = Math.sin(rf[2]);
      [-8.26, 8.26].forEach(function (dx) {
        var m = ebox(0.12, 0.40, rf[1], EXTC.trim, 0.3 + dx,
                     (rf[0] === -4.2 ? 8.05 : 8.78) - 0.11 * ca,
                     rf[0] - 0.11 * sa, { rough: 0.9 });
        m.rotation.x = rf[2];
      });
    });
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
      /* the lintel: the header stopped at y 3.5 and the door at 3.1, so
         a 0.4 slot ran the width of the bay and the resting camera
         looked straight through it at the shelves */
      gtag(box(5.6, 0.46, 0.24, NICE ? 0xffffff : EXTC.garage,
               -15.4, 3.27, 9.88, garageDoorG,
               NICE ? { rough: 0.95, map: sidingT } : { rough: 0.95 }));
      gtag(box(3.9, 0.16, 0.16, EXTC.trim, -15.4, 3.16, 10.00, garageDoorG));
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
      /* the bay's daylight, and the only exterior windows the resting
         camera sees square on: real glazing in a real casing, left
         emissive-capable for the lighting pass (bible S7.3). All of it
         rides garageDoorG, so the inside camera still sees a bare wall
         where the door is. */
      if (DETAIL >= 2) {
        var GLZ = { rough: 0.16, metal: 0.0, envInt: 0.6 };
        function gGlass(w, h, x, y, z, gp) {
          var m = box(w, h, 0.03, 0x9fc4dc, x, y, z, gp || garageDoorG, GLZ);
          m.userData.glazing = true;      /* the lighting pass looks for this */
          return gtag(m);
        }
        /* the window in the pier east of the door */
        gGlass(0.58, 0.68, -13.22, 2.68, 10.02);
        gtag(box(0.74, 0.09, 0.10, EXTC.trim, -13.22, 3.07, 10.03, garageDoorG));
        gtag(box(0.80, 0.08, 0.18, EXTC.trim, -13.22, 2.29, 10.06, garageDoorG));
        [-0.345, 0.345].forEach(function (dx) {
          gtag(box(0.09, 0.86, 0.10, EXTC.trim, -13.22 + dx, 2.68, 10.03,
                   garageDoorG));
        });
        if (DETAIL >= 3) {
          gtag(box(0.05, 0.68, 0.05, EXTC.trim, -13.22, 2.68, 10.04, garageDoorG));
          gtag(box(0.58, 0.05, 0.05, EXTC.trim, -13.22, 2.68, 10.04, garageDoorG));
        }
        /* the row of lights every sectional door carries in its top panel */
        [-16.42, -15.74, -15.06, -14.38].forEach(function (lx) {
          gGlass(0.52, 0.30, lx, 2.86, 10.10);
          gtag(box(0.60, 0.38, 0.05, 0xd8d0c2, lx, 2.86, 10.085, garageDoorG));
        });
        /* the gable's half-round, and a coach lamp beside the door */
        gGlass(0.44, 0.44, -15.40, 5.36, 10.27);
        gtag(cyl(0.34, 0.34, 0.09, EXTC.trim, -15.40, 5.36, 10.24,
                 garageDoorG, 16)).rotation.x = Math.PI / 2;
        if (DETAIL >= 3) {
          gtag(box(0.05, 0.42, 0.05, EXTC.trim, -15.40, 5.36, 10.28, garageDoorG));
          gtag(box(0.42, 0.05, 0.05, EXTC.trim, -15.40, 5.36, 10.28, garageDoorG));
        }
        gtag(box(0.10, 0.34, 0.09, C.ink, -17.58, 2.96, 10.02, garageDoorG,
                 { rough: 0.5 }));
        gtag(box(0.34, 0.09, 0.26, C.ink, -17.58, 3.16, 10.13, garageDoorG,
                 { rough: 0.5 }));
        var lamp2 = gtag(cyl(0.06, 0.185, 0.34, 0xf7e8c2, -17.58, 2.76, 10.16,
                             garageDoorG, 4, GLOSS));
        lamp2.userData.lamp = true;       /* geometry only: the pass lights it */
        lamp2.userData.glazing = true;
        lamp2.rotation.y = Math.PI / 4;
        gtag(cyl(0.075, 0.075, 0.06, C.ink, -17.58, 2.96, 10.16, garageDoorG,
                 8, { rough: 0.5 }));
        gtag(cyl(0.20, 0.20, 0.05, C.ink, -17.58, 2.57, 10.16, garageDoorG,
                 4, { rough: 0.5 })).rotation.y = Math.PI / 4;
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
      /* ================= THE BAY (style bible S7 garage) ================
         Plates 3, 4 and 5: a working garage, not a shed. A concrete slab
         with saw-cut joints (a garage floor is never plank), lined walls,
         a bench that reads as used under a pegboard of tools, a shelf of
         boxes down the long wall, a tyre on the wall, a strip light, and
         the floor clutter a family actually keeps: a tool chest, cartons,
         a mower, a wheelie bin.

         Four accents and no strays (S4): mustard, oxblood, teal and
         terracotta, the last only on a plant pot. Cardboard, wood and
         concrete are materials, not accents. Dark anchors: the pegboard
         and the tyre on the back wall, the bin, the bike and the tool
         chest on the floor.

         NOTHING IN HERE TAKES A SHADOW. The sun's shadow camera is a
         +/-10 box centred on the house and its EDGE runs diagonally
         across this bay: half the room sampled the map (and came back in
         the house's shadow), half fell outside it and was forced lit, so
         a hard diagonal lay across the floor, the back wall and the roof
         of whichever car parked in the east bay. Contact is drawn by
         hand instead, with the same multiply discs the vehicles use -
         they work at every tier, which the real shadow map does not. */
      var GD2 = DETAIL >= 2, GD3 = DETAIL >= 3;
      var GX0 = -17.96, GX1 = -12.84;    /* the side walls' structural faces */
      var GZ0 = 2.24, GZ1 = 9.76;        /* back wall face -> door line */
      /* the lining is 0.05 proud of all three: everything hung on a wall
         measures from THESE, or it renders inside the boards */
      var GXW = GX0 + 0.05, GXE = GX1 - 0.05, GZW = GZ0 + 0.05;
      var GFY = 0.035;                   /* the slab, not the house floor */
      var GWALL = 0xe4ded2, GCARD = 0xc0956a, GCARDD = 0xa27b55;
      var GMATT = { rough: 0.92 }, GPLAST = { rough: 0.95 };
      var gWoodO = NICE ? { rough: 0.62, map: woodLight } : { rough: 0.62 };
      var gWoodK = NICE ? 0xffffff : 0xc89a66;

      /* the bay is BACK ON the shadow map (lighting pass): the frustum
         now follows the camera, and the garage view's box is centred on
         this room, so there is no boundary running across it to draw the
         diagonal that forced this off in the first place. */
      function gt(m) {                   /* tag only */
        if (!m) return m;
        m.userData.room = 'garage'; m.userData.zone = 'garage';
        return m;
      }
      function gb(w, h, d, c, x, y, z, o, gp) {
        return gt(box(w, h, d, c, x, y, z, gp || garageInterior, o));
      }
      function gr(w, h, d, r, c, x, y, z, o, gp) {
        return gt(rbox(w, h, d, r, c, x, y, z, gp || garageInterior, o));
      }
      function gc(a, b2, h, c, x, y, z, s, o, gp) {
        return gt(cyl(a, b2, h, c, x, y, z, gp || garageInterior, s, o));
      }
      function gGroup(x, z, rot) {
        var g = new T.Group();
        g.position.set(x, 0, z);
        if (rot) g.rotation.y = rot;
        gt(g); garageInterior.add(g); return g;
      }
      /* contact BELOW tier 3. It used to draw at every tier, because the
         bay had no real shadow at any tier; now that it does, a hand disc
         under a real cast shadow just doubles the tone. A grey disc
         multiplied into the slab can only darken it. */
      function gsh(rx, rz, x, z, tone) {
        if (SHADOWS) return null;
        var d = new T.Mesh(new T.CircleGeometry(1, GD2 ? 18 : 10),
          new T.MeshBasicMaterial({ color: tone || 0xa9a5ad, transparent: true,
                                    blending: T.MultiplyBlending,
                                    depthWrite: false }));
        d.rotation.x = -Math.PI / 2;
        d.scale.set(rx, rz, 1);
        d.position.set(x, GFY + 0.007, z);
        d.renderOrder = -1;
        gt(d); garageInterior.add(d); return d;
      }

      /* ---- 0. the slab: concrete, saw-cut, oil-marked ------------------
         The bay wore the house's plank floor. A garage floor is a poured
         slab: control joints on a grid, aggregate speckle, two dark
         patches where the cars drip, and a whisper of shade where the
         walls meet it. Drawn once into a canvas, so the joints land on
         exact world coordinates and cost no meshes. */
      var concT = canvasTex(GD3 ? 512 : 256, function (g, S) {
        g.fillStyle = '#aaa599'; g.fillRect(0, 0, S, S);
        for (var i = 0; i < S * 5; i++) {           /* aggregate */
          g.fillStyle = 'rgba(' + (Math.random() < 0.5 ? '132,127,118' : '206,202,193')
                      + ',' + (0.06 + Math.random() * 0.22) + ')';
          g.fillRect(Math.random() * S, Math.random() * S, 2, 2);
        }
        [[0.245, 0.447], [0.755, 0.447]].forEach(function (o) {
          var rg = g.createRadialGradient(o[0] * S, o[1] * S, 2,
                                          o[0] * S, o[1] * S, S * 0.13);
          rg.addColorStop(0, 'rgba(74,70,64,0.30)');
          rg.addColorStop(1, 'rgba(74,70,64,0)');
          g.fillStyle = rg;
          g.fillRect(0, 0, S, S);
        });
        /* control joints: world z 4.75 and 7.25 across, world x -15.40
           down the middle (the plane is 5.1 x 7.5 at repeat 1, and the
           canvas top edge is the back wall) */
        g.strokeStyle = 'rgba(104,99,90,0.95)';
        g.lineWidth = Math.max(2, S / 150);
        [(4.75 - 2.25) / 7.5, (7.25 - 2.25) / 7.5].forEach(function (f) {
          g.beginPath(); g.moveTo(0, f * S); g.lineTo(S, f * S); g.stroke();
        });
        g.beginPath(); g.moveTo(0.5 * S, 0); g.lineTo(0.5 * S, S); g.stroke();
        /* the walls' own shade, baked: a diorama floor that meets its
           walls with a hard line reads as a decal */
        var e = S * 0.09;
        [[0, 0, S, e, 0, 1], [0, S - e, S, e, 0, -1],
         [0, 0, e, S, 1, 0], [S - e, 0, e, S, -1, 0]].forEach(function (sd) {
          var x0 = sd[4] > 0 ? sd[0] : (sd[4] < 0 ? sd[0] + sd[2] : sd[0]);
          var y0 = sd[5] > 0 ? sd[1] : (sd[5] < 0 ? sd[1] + sd[3] : sd[1]);
          var x1 = sd[4] > 0 ? sd[0] + sd[2] : (sd[4] < 0 ? sd[0] : sd[0]);
          var y1 = sd[5] > 0 ? sd[1] + sd[3] : (sd[5] < 0 ? sd[1] : sd[1]);
          var lg = g.createLinearGradient(x0, y0, x1, y1);
          lg.addColorStop(0, 'rgba(90,86,80,0.28)');
          lg.addColorStop(1, 'rgba(90,86,80,0)');
          g.fillStyle = lg;
          g.fillRect(sd[0], sd[1], sd[2], sd[3]);
        });
      });
      if (GD2) {
        var doorGlowT = canvasTex(64, function (g, S) {
          var lg = g.createLinearGradient(0, 0, 0, S);
          lg.addColorStop(0, 'rgba(255,241,209,0)');
          lg.addColorStop(0.55, 'rgba(255,241,209,0.45)');
          lg.addColorStop(1, 'rgba(255,241,209,1)');
          g.fillStyle = lg; g.fillRect(0, 0, S, S);
        });
        var dg = new T.Mesh(new T.PlaneGeometry(4.5, 3.0),
          new T.MeshBasicMaterial({ map: doorGlowT, transparent: true,
                                    opacity: 0.16, depthWrite: false,
                                    blending: T.AdditiveBlending }));
        dg.rotation.x = -Math.PI / 2;
        dg.position.set(-15.40, GFY + 0.004, 8.20);
        dg.renderOrder = -3;
        gt(dg); garageInterior.add(dg);
      }
      var gfloor = new T.Mesh(new T.PlaneGeometry(5.1, 7.5),
        PBR ? new T.MeshStandardMaterial({ map: concT, roughness: 0.88,
                                           envMapIntensity: 0.06 })
            : new T.MeshLambertMaterial({ map: concT }));
      gfloor.rotation.x = -Math.PI / 2;
      gfloor.position.set(-15.4, GFY, 6.0);
      gt(gfloor); garageInterior.add(gfloor);

      /* ---- 1. the three walls get an inside -----------------------------
         They wore exterior clapboard on their inner faces. Lined now: a
         painted board field, a splash board with its cap at the floor, a
         ledger at bench height, and battens for rhythm. */
      var gWallT = NICE ? canvasTex(256, function (g, S) {
        g.fillStyle = '#ddd5c6'; g.fillRect(0, 0, S, S);
        for (var i = 0; i < 320; i++) {
          g.fillStyle = 'rgba(134,123,106,' + (Math.random() * 0.14) + ')';
          g.fillRect(Math.random() * S, Math.random() * S, 3, 2);
        }
        for (var y = 0; y < S; y += 64) {
          g.fillStyle = 'rgba(128,117,100,0.50)'; g.fillRect(0, y, S, 2);
          g.fillStyle = 'rgba(255,252,244,0.50)'; g.fillRect(0, y + 2, S, 2);
        }
      }) : null;
      if (gWallT) {
        gWallT.wrapS = gWallT.wrapT = T.RepeatWrapping;
        gWallT.repeat.set(3, 1.4);
      }
      var gWallO = NICE ? { rough: 0.95, map: gWallT } : GPLAST;
      var gWallC = NICE ? 0xffffff : GWALL;
      function gWall(axis, face, dir, a0, a1, battens) {
        var L = a1 - a0, mid = (a0 + a1) / 2;
        function plate(h, d0, d1, c, y, o) {
          var d = d1 - d0, ctr = face + dir * ((d0 + d1) / 2);
          return axis === 'z' ? gb(L, h, d, c, mid, y, ctr, o)
                              : gb(d, h, L, c, ctr, y, mid, o);
        }
        plate(4.58, 0, 0.05, gWallC, 2.29, gWallO);
        plate(0.34, 0.05, 0.13, C.cabShade, 0.17, GMATT);   /* splash board */
        plate(0.06, 0.05, 0.16, C.cab, 0.37, GMATT);        /* its cap */
        if (!GD2) return;
        plate(0.07, 0.05, 0.14, C.cab, 1.24, GMATT);        /* the ledger */
        plate(0.14, 0.05, 0.18, C.cab, 4.42, GMATT);        /* the top plate:
             the wall head, or the long wall runs off the top of the frame
             as a cliff */
        if (GD3) plate(0.05, 0.05, 0.13, C.cabShade, 4.32);
        if (!battens) return;
        var n = Math.max(2, Math.round(L / 0.90));
        for (var i = 1; i < n; i++) {
          var a = a0 + i * (L / n), ctr = face + dir * 0.075;
          gt(axis === 'z' ? box(0.07, 3.16, 0.045, C.cab, a, 2.94, ctr,
                                garageInterior, GMATT)
                          : box(0.045, 3.16, 0.07, C.cab, ctr, 2.94, a,
                                garageInterior, GMATT));
        }
      }
      gWall('z', GZ0, 1, GX0, GX1, true);        /* the back wall */
      gWall('x', GX0, 1, GZ0, GZ1, true);        /* the long west wall */
      gWall('x', GX1, -1, GZ0, GZ1, false);      /* the east wall, edge-on */

      /* ---- 2. the workbench (plate 4: a bench that reads as used) ------
         Six parts like the casework: steel legs, a stretcher shelf, an
         apron, a drawer bank, an overhanging wood top, and the mess of a
         bench somebody actually works at. */
      var BWX = -16.77, BWZ = 2.56, BWW = 2.22, BWD = 0.64, BWY = 1.02;
      (function () {
        var lx = BWW / 2 - 0.08, lz = BWD / 2 - 0.09;
        [[-1, -1], [-1, 1], [1, -1], [1, 1]].forEach(function (s) {
          gb(0.09, BWY - 0.09, 0.09, C.graphite, BWX + s[0] * lx,
             (BWY - 0.09) / 2 + GFY, BWZ + s[1] * lz, { rough: 0.55 });
        });
        gb(BWW - 0.24, 0.05, BWD - 0.20, C.wood2, BWX, 0.30, BWZ, gWoodO);
        if (GD2) {
          gb(BWW - 0.22, 0.05, 0.05, C.graphite, BWX, 0.30, BWZ + lz,
             { rough: 0.55 });
          gb(BWW - 0.06, 0.10, 0.06, C.graphite, BWX, BWY - 0.16,
             BWZ + BWD / 2 - 0.02, { rough: 0.55 });
          var dx = BWX + 0.66, dw = 0.72, dz = BWZ + 0.02, df = BWD / 2 - 0.04;
          gb(dw, 0.60, BWD - 0.10, C.cabShade, dx, 0.63, dz, GMATT);
          [0.44, 0.79].forEach(function (dy) {
            gb(dw - 0.07, 0.29, 0.04, C.cab, dx, dy, dz + df, GMATT);
            gb(0.28, 0.03, 0.03, C.graphite, dx, dy, dz + df + 0.03,
               { rough: 0.5 });
          });
        }
        gr(BWW + 0.08, 0.09, BWD + 0.08, 0.02, gWoodK, BWX, BWY - 0.045,
           BWZ + 0.02, gWoodO);
        if (GD3) gb(BWW + 0.09, 0.02, BWD + 0.09, C.wood2, BWX, BWY - 0.092,
                    BWZ + 0.02, gWoodO);
        /* the vice, bolted to the left end */
        if (GD2) {
          gb(0.16, 0.20, 0.30, C.graphite, BWX - 0.94, BWY + 0.10, BWZ + 0.16,
             { rough: 0.5 });
          gb(0.24, 0.15, 0.09, C.ink, BWX - 0.94, BWY + 0.14, BWZ + 0.34,
             { rough: 0.5 });
          if (GD3) {
            gc(0.02, 0.02, 0.30, C.steel, BWX - 0.94, BWY + 0.13, BWZ + 0.42,
               8, STEEL).rotation.z = Math.PI / 2;
            gb(0.24, 0.15, 0.05, C.graphite, BWX - 0.94, BWY + 0.14, BWZ + 0.08,
               { rough: 0.5 });
          }
        }
        /* on the top: an open toolbox, a tin of drivers, a jar, a rag */
        if (GD2) {
          var tbx = BWX - 0.30;
          gr(0.52, 0.22, 0.30, 0.03, C.oxblood, tbx, BWY + 0.11, BWZ + 0.12,
             { rough: 0.6 });
          gb(0.50, 0.05, 0.28, 0x6d2f28, tbx, BWY + 0.24, BWZ + 0.12,
             { rough: 0.7 });
          gc(0.015, 0.015, 0.44, C.steel, tbx, BWY + 0.26, BWZ + 0.12, 8,
             STEEL).rotation.z = Math.PI / 2;
          gc(0.09, 0.09, 0.17, C.mustard, BWX + 0.24, BWY + 0.085, BWZ + 0.14,
             12, GLOSS);
          if (GD3) {
            [[-0.03, 0.30, 0.05], [0.02, 0.30, -0.03], [0.04, 0.28, 0.05]]
              .forEach(function (d) {
                gc(0.012, 0.012, d[1], C.steel, BWX + 0.24 + d[0],
                   BWY + 0.30, BWZ + 0.14 + d[2], 6, STEEL);
              });
            gc(0.07, 0.065, 0.13, C.teal, BWX + 0.06, BWY + 0.065, BWZ + 0.20,
               12, GLOSS);
            gr(0.20, 0.04, 0.15, 0.02, C.linen, BWX + 0.52, BWY + 0.02,
               BWZ + 0.10, { rough: 0.98 });
          }
        }
        /* under it, on the stretcher: paint tins and a jerry can */
        if (GD2) {
          gc(0.13, 0.13, 0.22, C.teal, BWX - 0.72, 0.435, BWZ, 12, GLOSS);
          gc(0.13, 0.13, 0.22, C.cream, BWX - 0.44, 0.435, BWZ + 0.06, 12,
             GLOSS);
          gr(0.22, 0.34, 0.14, 0.03, C.mustard, BWX + 0.02, 0.495, BWZ,
             { rough: 0.6 });
          if (GD3) {
            gc(0.135, 0.135, 0.02, C.steel, BWX - 0.72, 0.555, BWZ, 12, STEEL);
            gc(0.135, 0.135, 0.02, C.steel, BWX - 0.44, 0.555, BWZ + 0.06, 12,
               STEEL);
            gc(0.03, 0.03, 0.07, C.ink, BWX + 0.02, 0.70, BWZ, 8, GLOSS);
          }
        }
        gsh(1.14, 0.38, BWX, BWZ + 0.04, 0xc4c0c8);
      })();

      /* ---- 3. the pegboard, above the bench (plate 3) ------------------ */
      (function () {
        var PX = -16.77, PY = 1.88, PW = 2.10, PH = 1.16, PZ = GZW + 0.018;
        var pegT = NICE ? canvasTex(GD3 ? 256 : 128, function (g, S) {
          g.fillStyle = '#626871'; g.fillRect(0, 0, S, S);
          var st = S / 10;
          g.fillStyle = 'rgba(24,27,31,0.85)';
          for (var y = st / 2; y < S; y += st)
            for (var x = st / 2; x < S; x += st) {
              g.beginPath(); g.arc(x, y, Math.max(1, S / 74), 0, 7); g.fill();
            }
        }) : null;
        if (pegT) {
          pegT.wrapS = pegT.wrapT = T.RepeatWrapping;
          pegT.repeat.set(6, 3.5);
        }
        gb(PW, PH, 0.035, NICE ? 0xffffff : C.graphite, PX, PY, PZ,
           NICE ? { rough: 0.88, map: pegT } : { rough: 0.88 });
        gb(PW + 0.06, 0.05, 0.05, C.cab, PX, PY + PH / 2 + 0.02, PZ + 0.01,
           GMATT);
        gb(PW + 0.06, 0.05, 0.05, C.cab, PX, PY - PH / 2 - 0.02, PZ + 0.01,
           GMATT);
        if (!GD2) return;
        var tz = PZ + 0.05;
        gc(0.018, 0.018, 0.30, C.wood2, PX - 0.86, PY + 0.10, tz, 6, GMATT);
        gb(0.16, 0.07, 0.07, C.ink, PX - 0.86, PY + 0.27, tz, { rough: 0.55 });
        gb(0.44, 0.16, 0.02, C.steel, PX - 0.40, PY + 0.24, tz, STEEL);
        gb(0.13, 0.13, 0.05, C.oxblood, PX - 0.66, PY + 0.24, tz,
           { rough: 0.6 });
        gb(0.62, 0.06, 0.05, C.mustard, PX + 0.38, PY + 0.38, tz, GLOSS);
        var coil = new T.Mesh(new T.TorusGeometry(0.15, 0.038,
          GD3 ? 8 : 5, GD3 ? 14 : 8), mat(C.teal, { rough: 0.7 }));
        coil.position.set(PX + 0.82, PY - 0.22, tz + 0.02);
        gt(coil); garageInterior.add(coil);
        gb(1.00, 0.05, 0.20, C.cab, PX - 0.52, PY - 0.36, PZ + 0.10, GMATT);
        [[-0.86, C.oxblood], [-0.60, C.teal], [-0.34, C.mustard]]
          .forEach(function (t) {
            gc(0.075, 0.075, 0.16, t[1], PX + t[0], PY - 0.255, PZ + 0.10,
               10, GLOSS);
          });
        if (!GD3) return;
        [[-0.06, 0.30], [0.04, 0.30], [0.14, 0.28]].forEach(function (d) {
          gc(0.012, 0.012, d[1], C.steel, PX + d[0], PY + 0.20, tz, 6, STEEL);
          gc(0.024, 0.024, 0.10, C.oxblood, PX + d[0], PY + 0.01, tz, 6, GLOSS);
        });
        gb(0.05, 0.24, 0.03, C.steel, PX + 0.60, PY + 0.04, tz, STEEL);
        gb(0.04, 0.28, 0.03, C.steel, PX + 0.70, PY + 0.08, tz, STEEL);
        gb(0.09, 0.09, 0.035, C.graphite, PX + 0.60, PY + 0.17, tz,
           { rough: 0.5 });
        gb(0.13, 0.13, 0.06, C.mustard, PX + 0.36, PY + 0.08, tz, GLOSS);
        gb(0.11, 0.19, 0.05, C.oxblood, PX + 0.86, PY + 0.30, tz,
           { rough: 0.6 });
        gb(0.05, 0.15, 0.05, C.graphite, PX + 0.86, PY + 0.14, tz,
           { rough: 0.5 });
      })();

      /* ---- 4. the back wall's right half: a shelf of cartons, a tyre --- */
      (function () {
        var SX = -14.72, SW = 1.56, SD = 0.38, SZ = GZW + SD / 2;
        gb(SW, 1.00, 0.03, C.cabShade, SX, 2.02, GZW + 0.016, GMATT);
        [1.58, 2.24].forEach(function (y) {
          gb(SW, 0.06, SD, C.cab, SX, y, SZ, GMATT);
          if (GD3) gb(SW, 0.065, 0.02, C.cabShade, SX, y, SZ + SD / 2 - 0.01,
                      GMATT);
        });
        gb(0.05, 1.00, SD, C.cab, SX - SW / 2 + 0.02, 2.02, SZ, GMATT);
        gb(0.05, 1.00, SD, C.cab, SX + SW / 2 - 0.02, 2.02, SZ, GMATT);
        if (GD2) {
          gb(0.05, 0.68, SD, C.cab, SX, 1.94, SZ, GMATT);
          gb(0.38, 0.32, 0.30, GCARD, SX - 0.52, 1.77, SZ, GMATT);
          gc(0.09, 0.09, 0.18, C.teal, SX - 0.24, 1.70, SZ - 0.02, 10, GLOSS);
          gb(0.16, 0.22, 0.22, C.wood2, SX - 0.09, 1.72, SZ + 0.04, gWoodO);
          gb(0.34, 0.26, 0.26, GCARD, SX + 0.20, 1.74, SZ, GMATT);
          gc(0.08, 0.08, 0.16, C.mustard, SX + 0.46, 1.69, SZ - 0.03, 10,
             GLOSS);
          gb(0.14, 0.14, 0.20, C.cream, SX + 0.63, 1.68, SZ + 0.03, GMATT);
          gc(0.10, 0.10, 0.20, C.oxblood, SX - 0.32, 2.37, SZ, 10, GLOSS);
          gc(0.10, 0.10, 0.20, C.cream, SX - 0.54, 2.37, SZ - 0.13, 10, GLOSS);
          gb(0.44, 0.28, 0.28, C.wood2, SX + 0.38, 2.41, SZ, gWoodO);
          if (GD3) {
            gb(0.39, 0.05, 0.10, GCARDD, SX - 0.52, 1.925, SZ, GMATT);
            gb(0.35, 0.05, 0.09, GCARDD, SX + 0.20, 1.865, SZ, GMATT);
            gc(0.105, 0.105, 0.02, C.steel, SX - 0.54, 2.48, SZ - 0.13, 10, STEEL);
            gb(0.45, 0.05, 0.06, C.wood, SX + 0.38, 2.56, SZ, gWoodO);
          }
        } else {
          gb(0.44, 0.32, 0.30, GCARD, SX - 0.44, 1.77, SZ, GMATT);
          gb(0.36, 0.26, 0.26, GCARD, SX + 0.30, 1.74, SZ, GMATT);
        }
        /* the tyre on the wall (plate 3) - the wall's dark anchor */
        var TY = -13.44, TYY = 2.10;
        var ty = new T.Mesh(new T.TorusGeometry(0.30, 0.115,
          GD3 ? 9 : 5, GD3 ? 18 : 10), mat(C.ink, { rough: 0.94 }));
        ty.position.set(TY, TYY, GZW + 0.13);
        gt(ty); garageInterior.add(ty);
        if (GD2) {
          gc(0.20, 0.20, 0.09, C.steel, TY, TYY, GZW + 0.13, 12, STEEL)
            .rotation.x = Math.PI / 2;
          gb(0.86, 0.07, 0.07, C.cab, TY, 1.32, GZW + 0.04, GMATT);
          [-0.28, 0, 0.28].forEach(function (dx) {
            gb(0.035, 0.13, 0.035, C.graphite, TY + dx, 1.24, GZW + 0.08,
               { rough: 0.5 });
          });
          var hose = new T.Mesh(new T.TorusGeometry(0.22, 0.055,
            GD3 ? 8 : 5, GD3 ? 14 : 8), mat(C.teal, { rough: 0.82 }));
          hose.position.set(TY + 0.02, 1.02, GZW + 0.14);
          gt(hose); garageInterior.add(hose);
        }
      })();

      /* ---- 5. the long wall: a shelf of boxes and a ladder (plate 3) --- */
      (function () {
        var WD = 0.40, WXf = GXW + WD / 2, Z0 = 3.55, Z1 = 9.20;
        var WZ = (Z0 + Z1) / 2, WL = Z1 - Z0;
        [2.10, 2.80].forEach(function (y) {
          gb(WD, 0.06, WL, C.cab, WXf, y, WZ, GMATT);
          if (GD3) gb(0.02, 0.065, WL, C.cabShade, GXW + WD - 0.01, y, WZ,
                      GMATT);
          if (GD2) [Z0 + 0.35, WZ, Z1 - 0.35].forEach(function (bz) {
            gb(WD - 0.06, 0.05, 0.05, C.graphite, WXf - 0.02, y - 0.055, bz,
               { rough: 0.5 });
          });
        });
        if (GD2) {
          gb(0.34, 0.34, 0.46, GCARD, WXf, 2.30, Z0 + 0.42, GMATT);
          gb(0.32, 0.28, 0.40, GCARD, WXf, 2.27, Z0 + 1.00, GMATT);
          gb(0.34, 0.30, 0.52, C.wood2, WXf, 2.28, Z0 + 1.72, gWoodO);
          gc(0.11, 0.11, 0.22, C.mustard, WXf, 2.24, Z0 + 2.34, 10, GLOSS);
          gc(0.11, 0.11, 0.22, C.oxblood, WXf, 2.24, Z0 + 2.62, 10, GLOSS);
          gb(0.30, 0.36, 0.50, GCARD, WXf, 2.31, Z0 + 3.24, GMATT);
          gr(0.26, 0.38, 0.18, 0.03, C.mustard, WXf, 3.02, Z0 + 0.55,
             { rough: 0.6 });
          gb(0.32, 0.30, 0.44, GCARD, WXf, 2.98, Z0 + 1.24, GMATT);
          gc(0.12, 0.12, 0.24, C.teal, WXf, 2.95, Z0 + 1.90, 10, GLOSS);
          gb(0.30, 0.26, 0.38, GCARD, WXf, 2.96, Z0 + 2.52, GMATT);
          gc(0.11, 0.11, 0.20, C.cream, WXf, 2.93, Z0 + 3.10, 10, GLOSS);
          /* the run carries on over the tool chest to the door end */
          gb(0.32, 0.34, 0.48, GCARD, WXf, 2.30, Z0 + 4.06, GMATT);
          gb(0.34, 0.26, 0.40, C.wood2, WXf, 2.26, Z0 + 4.72, gWoodO);
          gc(0.11, 0.11, 0.22, C.teal, WXf, 2.24, Z0 + 5.26, 10, GLOSS);
          gr(0.24, 0.34, 0.17, 0.03, C.mustard, WXf, 3.00, Z0 + 4.10,
             { rough: 0.6 });
          gb(0.30, 0.30, 0.42, GCARD, WXf, 2.98, Z0 + 4.80, GMATT);
          gc(0.10, 0.10, 0.19, C.oxblood, WXf, 2.92, Z0 + 5.32, 10, GLOSS);
          if (GD3) {
            gb(0.35, 0.05, 0.16, GCARDD, WXf, 2.475, Z0 + 0.42, GMATT);
            gb(0.33, 0.05, 0.14, GCARDD, WXf, 2.415, Z0 + 1.00, GMATT);
            gb(0.31, 0.05, 0.14, GCARDD, WXf, 2.49, Z0 + 3.24, GMATT);
            gb(0.33, 0.05, 0.15, GCARDD, WXf, 3.135, Z0 + 1.24, GMATT);
            gb(0.31, 0.05, 0.13, GCARDD, WXf, 3.115, Z0 + 2.52, GMATT);
            gb(0.33, 0.05, 0.16, GCARDD, WXf, 2.485, Z0 + 4.06, GMATT);
            gb(0.31, 0.05, 0.14, GCARDD, WXf, 3.145, Z0 + 4.80, GMATT);
          }
        } else {          /* the Pi gets the storage, just not the jars:
             two bare planks read as a mistake, not as restraint */
          gb(0.34, 0.34, 0.46, GCARD, WXf, 2.30, Z0 + 0.42, GMATT);
          gb(0.32, 0.30, 0.44, GCARD, WXf, 2.98, Z0 + 1.30, GMATT);
          gb(0.30, 0.32, 0.44, GCARD, WXf, 2.29, Z0 + 4.10, GMATT);
        }
        if (GD2) {                /* the long handles, hung in a row: the
             long wall was blank from the splash board to the shelf */
          gb(0.10, 0.06, 1.00, C.cab, GXW + 0.06, 2.02, 4.50, GMATT);
          [[4.15, C.wood, C.oxblood], [4.50, C.wood2, C.graphite],
           [4.85, C.wood, C.teal]].forEach(function (tl, i) {
            gc(0.030, 0.030, 1.00, tl[1], GXW + 0.10, 1.50, tl[0],
               GD3 ? 8 : 6, gWoodO);
            gb(0.06, 0.16, i === 1 ? 0.36 : 0.22, tl[2], GXW + 0.10, 1.02,
               tl[0], { rough: 0.7 });
          });
        }
        if (GD2) {                /* the bike, hung over the tool chest:
             the wall between the shelf and the chest was the last blank
             panel wider than two units in the room (S4) */
          var BKX = GXW + 0.15, BKZ = 8.42, BKY = 1.48, BR = 0.30;
          [-0.56, 0.56].forEach(function (dz) {
            var wh = new T.Mesh(new T.TorusGeometry(BR, 0.035,
              GD3 ? 8 : 5, GD3 ? 16 : 10), mat(C.ink, { rough: 0.9 }));
            wh.rotation.y = Math.PI / 2;
            wh.position.set(BKX, BKY, BKZ + dz);
            gt(wh); garageInterior.add(wh);
            if (GD3) gc(0.075, 0.075, 0.04, C.steel, BKX, BKY, BKZ + dz, 10,
                        STEEL).rotation.z = Math.PI / 2;
          });
          /* the frame, drawn as tubes in the wall's own z-y plane */
          [[0.52, 0.06, -0.20, -0.395], [0.68, 0.04, 0.16, 0.869],
           [0.72, 0.28, 0.06, 1.626], [0.30, 0.13, 0.49, 2.646]]
            .forEach(function (tb) {
              gb(0.045, tb[0], 0.045, C.oxblood, BKX, BKY + tb[1],
                 BKZ + tb[2], { rough: 0.55 }).rotation.x = tb[3];
            });
          if (GD3) {
            [[0.49, -0.09, -0.33, -1.198], [0.40, 0.15, -0.43, -2.428]]
              .forEach(function (tb) {
                gb(0.04, tb[0], 0.04, C.oxblood, BKX, BKY + tb[1],
                   BKZ + tb[2], { rough: 0.55 }).rotation.x = tb[3];
              });
            gb(0.07, 0.05, 0.22, C.ink, BKX, BKY + 0.34, BKZ - 0.32,
               { rough: 0.7 });
            gb(0.26, 0.045, 0.045, C.graphite, BKX + 0.03, BKY + 0.30,
               BKZ + 0.44, { rough: 0.5 });
          }
          [-1, 1].forEach(function (sgn) {
            gb(0.10, 0.07, 0.07, C.graphite, GXW + 0.05, BKY + 0.30,
               BKZ + sgn * 0.40, { rough: 0.5 });
          });
        }
        if (GD2) {                          /* the ladder, hung flat */
          var LY = 3.44, LZ = 5.72, LL = 3.70, LXf = GXW + 0.13;
          [-0.17, 0.17].forEach(function (dy) {
            gb(0.07, 0.07, LL, C.wood, LXf, LY + dy, LZ, gWoodO);
          });
          if (GD3) for (var i = 0; i < 8; i++)
            gb(0.05, 0.30, 0.05, C.wood2, LXf, LY,
               LZ - LL / 2 + 0.24 + i * ((LL - 0.48) / 7), gWoodO);
          [-1, 1].forEach(function (s) {
            gb(0.09, 0.09, 0.09, C.graphite, GXW + 0.04, LY,
               LZ + s * (LL / 2 - 0.30), { rough: 0.5 });
          });
        }
      })();

      /* ---- 6. the east wall, seen edge-on: a reel and a hook rail ------ */
      if (GD2) {
        var EXf = GXE - 0.06;
        gb(0.18, 0.10, 0.10, C.graphite, EXf, 1.62, 4.60, { rough: 0.5 });
        var reel = new T.Mesh(new T.TorusGeometry(0.26, 0.085,
          GD3 ? 8 : 5, GD3 ? 14 : 8), mat(C.teal, { rough: 0.82 }));
        reel.rotation.y = Math.PI / 2;
        reel.position.set(EXf - 0.10, 1.62, 4.60);
        gt(reel); garageInterior.add(reel);
        gb(0.10, 0.07, 1.90, C.cab, GXE - 0.04, 2.36, 7.00, GMATT);
        [6.30, 6.86, 7.42].forEach(function (hz) {
          gb(0.14, 0.13, 0.035, C.graphite, GXE - 0.11, 2.28, hz,
             { rough: 0.5 });
        });
        gr(0.20, 0.25, 0.19, 0.08, C.mustard, GXE - 0.15, 2.13, 6.30,
           { rough: 0.7 });
        gr(0.17, 0.22, 0.22, 0.09, C.oxblood, GXE - 0.14, 2.15, 7.42,
           { rough: 0.7 });
      }

      /* ---- 7. the strip light (plate 3) -------------------------------
         Hung ACROSS the bay, not down it: run lengthwise it points its
         3-unit top face straight at a camera looking down the bay and
         reads as a pale plank across the middle of the frame. Its two
         drops are placed in the gap between the car plaques so they
         cross nothing that has to be read. */
      (function () {
        var LY = 3.20, LZ = 3.66, LW = 2.30;
        [-15.75, -15.05].forEach(function (rx) {
          gc(0.018, 0.018, 1.40, C.steel, rx, LY + 0.76, LZ, 6, STEEL);
        });
        gb(LW, 0.09, 0.28, C.graphite, -15.40, LY, LZ, { rough: 0.5 });
        [-0.075, 0.075].forEach(function (dz) {   /* twin tubes, exposed:
             a shop light seen from above is its tubes, and a closed
             body just reads as a lintel across the wall */
          gc(0.045, 0.045, LW - 0.12, 0xfff8e4, -15.40, LY + 0.075, LZ + dz,
             GD3 ? 10 : 6, { rough: 0.35 }).rotation.z = Math.PI / 2;
        });
        if (GD3) [-1, 1].forEach(function (s) {
          gb(0.07, 0.19, 0.30, C.steel, -15.40 + s * (LW / 2 - 0.02),
             LY + 0.04, LZ, STEEL);
        });
      })();

      /* ---- 8. the floor in front of the cars: the clutter --------------
         S1's 0.6 rule - two groups, not a scatter. West: a tool chest
         against the wall with cartons and the mower beside it. East: the
         bin with two tyres and a watering can. */
      (function () {
        var TCX = -17.58, TCZ = 8.40, TCW = 1.16, TCD = 0.60;
        if (GD2) {
          var tc = kCase(TCX, TCZ, Math.PI / 2, TCW, TCD, GFY, GFY + 0.92,
                         [{ h: 0.92, cells: [{ w: 1, kind: 'drawers3' }] }],
                         { toe: true, face: C.oxblood,
                           body: shadeHex(C.oxblood, 0.74) });
          garageInterior.add(tc);
          tc.traverse(gt);
          gr(TCD + 0.08, 0.08, TCW + 0.08, 0.02, C.mustard, TCX, GFY + 0.96,
             TCZ, { rough: 0.55 });
        } else {
          gb(TCD, 0.92, TCW, C.oxblood, TCX, GFY + 0.46, TCZ, { rough: 0.7 });
          gb(TCD + 0.08, 0.08, TCW + 0.08, C.mustard, TCX, GFY + 0.96, TCZ,
             { rough: 0.55 });
        }
        gsh(0.44, 0.72, TCX, TCZ);
        gb(0.56, 0.42, 0.50, GCARD, -16.86, GFY + 0.21, 9.02, GMATT);
        gb(0.48, 0.36, 0.44, GCARD, -16.90, GFY + 0.60, 8.98, GMATT);
        if (GD2) gb(0.40, 0.30, 0.38, GCARD, -16.84, GFY + 0.93, 9.04, GMATT);
        if (GD3) {
          gb(0.57, 0.05, 0.17, GCARDD, -16.86, GFY + 0.40, 9.02, GMATT);
          gb(0.49, 0.05, 0.15, GCARDD, -16.90, GFY + 0.755, 8.98, GMATT);
          gb(0.41, 0.05, 0.13, GCARDD, -16.84, GFY + 1.055, 9.04, GMATT);
        }
        gsh(0.36, 0.32, -16.87, 9.01);
        if (GD2) {                                  /* the mower (plate 3) */
          var mw = gGroup(-16.06, 8.58, -0.42);
          gr(0.66, 0.17, 0.80, 0.05, C.mustard, 0, GFY + 0.24, 0, GLOSS, mw);
          gb(0.40, 0.20, 0.34, C.ink, 0, GFY + 0.42, -0.10, { rough: 0.6 }, mw);
          if (GD3) {
            gc(0.06, 0.06, 0.13, C.steel, 0.14, GFY + 0.56, -0.10, 8, STEEL,
               mw);
            gb(0.18, 0.10, 0.12, C.oxblood, -0.16, GFY + 0.48, -0.16,
               { rough: 0.6 }, mw);
          }
          [[-0.27, 0.30], [0.27, 0.30], [-0.27, -0.30], [0.27, -0.30]]
            .forEach(function (w) {
              gc(0.14, 0.14, 0.09, C.ink, w[0], GFY + 0.14, w[1],
                 GD3 ? 12 : 8, { rough: 0.9 }, mw).rotation.z = Math.PI / 2;
            });
          [-1, 1].forEach(function (s) {
            gb(0.05, 0.86, 0.05, C.graphite, s * 0.28, GFY + 0.62, -0.42,
               { rough: 0.5 }, mw).rotation.x = -0.62;
          });
          gb(0.62, 0.05, 0.05, C.graphite, 0, GFY + 0.96, -0.70,
             { rough: 0.5 }, mw);
          gsh(0.42, 0.48, -16.06, 8.58);
        }
        var BNX = -13.28, BNZ = 8.46;               /* the wheelie bin */
        gr(0.60, 0.92, 0.54, 0.05, C.slate, BNX, GFY + 0.50, BNZ,
           { rough: 0.7 });
        gr(0.64, 0.08, 0.58, 0.03, C.ink, BNX, GFY + 0.98, BNZ,
           { rough: 0.7 });
        if (GD2) {
          gb(0.44, 0.05, 0.05, C.ink, BNX, GFY + 1.06, BNZ - 0.20,
             { rough: 0.6 });
          [-1, 1].forEach(function (s) {
            gc(0.09, 0.09, 0.07, C.ink, BNX + s * 0.26, GFY + 0.09, BNZ - 0.20,
               8, { rough: 0.9 }).rotation.z = Math.PI / 2;
          });
        }
        gsh(0.36, 0.34, BNX, BNZ);
        if (GD2) {
          for (var t = 0; t < 2; t++) {
            var tr = new T.Mesh(new T.TorusGeometry(0.30, 0.115,
              GD3 ? 8 : 5, GD3 ? 16 : 10), mat(C.ink, { rough: 0.94 }));
            tr.rotation.x = Math.PI / 2;
            tr.position.set(-14.16, GFY + 0.12 + t * 0.23, 8.48);
            gt(tr); garageInterior.add(tr);
          }
          gsh(0.34, 0.34, -14.16, 8.48);
          gr(0.22, 0.26, 0.20, 0.05, C.teal, -13.74, GFY + 0.13, 7.86,
             { rough: 0.7 });
          if (GD3) gc(0.02, 0.02, 0.26, C.teal, -13.60, GFY + 0.20, 7.86, 6,
                      GLOSS).rotation.z = 1.1;
          gsh(0.16, 0.15, -13.74, 7.86);
        }
      })();

      /* ---- 9. three plants (S4) - the pots a family keeps in here ------ */
      (function () {
        function gPlant(x, y0, z, s, potC, kind) {
          var g = gGroup(x, z, 0);
          kPlant(g, 0, y0, 0, s, potC, { rough: 0.85 }, kind, false);
          g.traverse(gt);
          return g;
        }
        gPlant(-14.92, 2.30, GZW + 0.19, 0.50, C.terracotta, 'spray');
        if (GD2) {
          gPlant(-17.76, 2.16, 7.24, 0.44, C.cream, 'mound');
          gPlant(-17.56, GFY + 0.97, 8.02, 0.42, C.cream, 'fiddle');
        }
      })();
      groups.garage = garageInterior;   /* the zone-glow loop lights the room */
    })();
    /* the front path (door to street) is laid in flags down in the yard
       block: it was one poured ribbon here, which is the defect S7.1
       names. */
    /* driveway from the garage door to the street. Plate 3 scores its
       apron with expansion joints, so the slab reads as poured concrete
       and not as a painted plane; it also stopped half a unit short of
       the garage door, leaving a ribbon of grass under the threshold.
       Now it runs from the door line to the kerb and is saw-cut on a
       grid, the joints proud by a hair so they catch the light. */
    ebox(4.6, 0.08, 8.7, NICE ? 0xffffff : EXTC.drive, -15.4, -0.25, 13.95,
         { rough: 0.95, map: driveT });
    if (DETAIL >= 2) {
      [10.85, 12.60, 14.35, 16.10, 17.60].forEach(function (jz) {
        ebox(4.6, 0.014, 0.055, 0x8e887d, -15.4, -0.204, jz, { rough: 0.95 });
      });
      ebox(0.055, 0.014, 8.7, 0x8e887d, -15.4, -0.204, 13.95, { rough: 0.95 });
      /* the apron's own edge, where the slab meets the lawn */
      [-1, 1].forEach(function (sx) {
        ebox(0.10, 0.10, 8.7, EXTC.trim, -15.4 + sx * 2.30, -0.245, 13.95,
             { rough: 0.9 });
      });
      /* and the thing every driveway ends in */
      ebox(0.10, 0.92, 0.10, C.wood2, -12.95, 0.17, 17.30, { rough: 0.8 });
      ebox(0.26, 0.24, 0.44, C.slate, -12.95, 0.74, 17.30, { rough: 0.7 });
      if (DETAIL >= 3) {
        ebox(0.05, 0.16, 0.04, C.red, -12.80, 0.80, 17.30, GLOSS);
        ebox(0.28, 0.05, 0.46, C.dark, -12.95, 0.87, 17.30, { rough: 0.7 });
      }
    }
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
    /* ================= VEHICLES (docs/house_style_bible.md S6) ==========
       Plate 10 is a low-poly car pack: faceted bodies, hard chamfers,
       inset blue glass, a grille, headlight blocks and a cut arch over
       every wheel. The first pass built a body box, a cab box and a
       flush window band - the three tells of a block car. This kit
       replaces all three.

       A vehicle is a SIDE PROFILE, traced once as a T.Shape in (z
       forward, y up) and extruded across the width with ONE bevel
       segment: two or more and the chamfer goes soft plastic. The glass
       is its own extrusion set 0.06 inside the body sides, so the
       pillars and the roof cap stand proud of it from every angle. The
       arch is cut INTO the profile with 0.05 of air round the tyre.

       One builder serves all seven car bodies and the school bus - the
       bus is a long profile with a bonnet, not a different craft. */
    var CAR_GLASS = 0x7fb6d9;            /* S6: the plate window blue */
    var CAR_LAMP = 0xfdf6e3;             /* S6: headlight block */

    function shadeHex(hex, k) {
      function cl(v) { return Math.max(0, Math.min(255, Math.round(v))); }
      return (cl(((hex >> 16) & 255) * k) << 16)
           | (cl(((hex >> 8) & 255) * k) << 8) | cl((hex & 255) * k);
    }
    function lumaHex(hex) {
      return (0.299 * ((hex >> 16) & 255) + 0.587 * ((hex >> 8) & 255)
              + 0.114 * (hex & 255)) / 255;
    }
    /* ExtrudeGeometry pushes along ITS own +z, so the mesh takes a
       quarter turn and slides back half a width; after that the shape
       coordinates ARE vehicle coordinates.

       bevelOffset is load-bearing. Without it three.js runs the BODY of
       the extrusion at shape+bevelSize and the two end caps at the shape
       itself - so the silhouette comes out 0.05 fat in every direction,
       the beltline rises over the roof cap and the wheel arches lose the
       whole of their clearance. bevelOffset:-bevelSize puts the shape
       back on the body and chamfers the caps IN, which is the plate's
       hard edge and the geometry this file's numbers assume. */
    function profileMesh(shape, width, colour, opts) {
      var bev = DETAIL >= 2, bt = 0.05;
      var m = new T.Mesh(new T.ExtrudeGeometry(shape, {
        depth: width - (bev ? 2 * bt : 0), bevelEnabled: bev,
        bevelThickness: bt, bevelSize: bt, bevelOffset: -bt,
        bevelSegments: 1, steps: 1,
        curveSegments: DETAIL >= 3 ? 7 : 3 }), mat(colour, opts || GLOSS));
      m.rotation.y = -Math.PI / 2;
      m.position.x = width / 2 - (bev ? bt : 0);
      return m;
    }
    /* the arch: the sill drops away, the profile lifts over the wheel
       with 0.05 of air and comes back down. No arch reads as a toy. */
    function archCut(sh, wz, wr, sill) {
      var aR = wr + 0.05;
      sh.lineTo(wz - aR, sill);
      sh.lineTo(wz - aR, wr);
      sh.absarc(wz, wr, aR, Math.PI, 0, true);
      sh.lineTo(wz + aR, sill);
    }
    /* Every profile keeps belt > 2*wr + 0.09 (the arch has to clear the
       beltline) and sill < wr (the arch needs a lip to cut). */
    function buildVehicle(grp, p, col, tag) {
      var zF = p.L / 2, zR = -p.L / 2, hw = p.W / 2;
      /* The cabin comes in 0.09 a side from the body (S6's taper) and
         the glass another 0.06 in from THAT, so every pillar and the
         roof cap stand proud of the glass. Insetting the glass from the
         body alone leaves no room: the tub's own 0.05 chamfer at the
         beltline eats it, and the pillars come out as fins. */
      var cabX = hw - 0.09, glassW = 2 * (cabX - 0.06);
      var trimC = p.trim !== undefined ? p.trim
                : (lumaHex(col) > 0.60 ? shadeHex(col, 0.56) : C.cabShade);

      /* -- 1. the tub: sill, both arches, nose, bonnet, beltline, tail */
      var sh = new T.Shape();
      sh.moveTo(zR, p.sill);
      archCut(sh, p.rw, p.wr, p.sill);
      archCut(sh, p.fw, p.wr, p.sill);
      sh.lineTo(zF, p.sill);
      sh.lineTo(zF, p.nose);                       /* the nose face */
      sh.lineTo(zF - 0.16, p.hood);                /* bonnet break */
      sh.lineTo(p.wsB, p.hood);
      if (Math.abs(p.belt - p.hood) > 0.01) sh.lineTo(p.wsB, p.belt);
      if (p.bed) {                                 /* a truck: open well */
        sh.lineTo(p.bed.z0, p.belt);
        sh.lineTo(p.bed.z0, p.bed.floor);
        sh.lineTo(p.bed.z1, p.bed.floor);
        sh.lineTo(p.bed.z1, p.bed.rail);
        sh.lineTo(zR, p.bed.rail);
      } else {
        sh.lineTo(p.blB, p.belt);
        if (Math.abs(p.belt - p.deck) > 0.01) sh.lineTo(p.blB, p.deck);
        sh.lineTo(zR + 0.03, p.deck);
      }
      sh.lineTo(zR, p.sill + 0.12);                /* the tail tucks in */
      sh.closePath();
      tag(profileMesh(sh, p.W, col, p.paint || GLOSS));

      /* -- 2. the greenhouse: ONE glass mesh, 0.06 inside the body
         sides. Flush glass is the clearest tell of a block car; this is
         the line that removes it. It plunges 0.14 into the tub so there
         is no seam at the beltline. */
      var gh = new T.Shape();
      var gy = p.belt - 0.14;
      gh.moveTo(p.wsB, gy);
      gh.lineTo(p.wsT, p.roof);
      gh.lineTo(p.blT, p.roof);
      gh.lineTo(p.blB, gy);
      gh.closePath();
      tag(profileMesh(gh, glassW, p.glass || CAR_GLASS,
                      { rough: 0.34, metal: 0.0, envInt: 0.16 }));

      /* -- 3. the roof cap: painted, capping the glass, drawn in from
         the body sides so the cabin is narrower than the body (S6). */
      var capZ0 = p.wsT + 0.03, capZ1 = p.blT - 0.03;
      if (capZ0 > capZ1 + 0.05) {
        tag(box(2 * cabX + 0.01, 0.075, capZ0 - capZ1, col, 0,
                p.roof - 0.018, (capZ0 + capZ1) / 2, grp, GLOSS));
      }

      /* -- 4. pillars, at the BODY width: A, C and the cabin uprights
         all stand 0.06 proud of the glass. */
      function pillar(z0, z1, w) {
        var dz = z1 - z0, dy = p.roof - p.belt;
        var len = Math.sqrt(dz * dz + dy * dy) + 0.11;
        [-1, 1].forEach(function (sx) {
          var m = box(w, len, 0.07, col, sx * (cabX - w / 2),
                      (p.belt + p.roof) / 2 - 0.05, (z0 + z1) / 2, grp,
                      GLOSS);
          m.rotation.x = Math.atan2(dz, dy);
          tag(m);
        });
      }
      if (DETAIL >= 2) {
        pillar(p.wsB, p.wsT, 0.062);
        pillar(p.blB, p.blT, 0.070);
        (p.pil || []).forEach(function (t) {
          var z = p.wsB + t * (p.blB - p.wsB);
          pillar(z, z, 0.050);
        });
      }

      /* -- 5. wheels: tyre in ink, rim at 0.62 radius set 0.02 inside
         the tyre face, a proud hub cap at tier 3. */
      function wheelAt(sx, wz, off) {
        var xo = sx * (hw - 0.03) - sx * (off || 0);
        var tw = p.wr * 0.30, t;
        if (DETAIL >= 2) {
          t = new T.Mesh(new T.TorusGeometry(p.wr - tw, tw,
            DETAIL >= 3 ? 8 : 5, DETAIL >= 3 ? 16 : 10),
            mat(C.ink, { rough: 0.92 }));
          t.rotation.y = Math.PI / 2;
          t.position.set(xo - sx * tw, p.wr, wz);
        } else {
          t = new T.Mesh(new T.CylinderGeometry(p.wr, p.wr, 0.20, 8),
            mat(C.ink, { rough: 0.92 }));
          t.rotation.z = Math.PI / 2;
          t.position.set(xo - sx * 0.10, p.wr, wz);
        }
        t.userData.round = true;
        tag(t);
        if (DETAIL >= 2) {
          var r = new T.Mesh(new T.CylinderGeometry(p.wr * 0.62,
            p.wr * 0.62, 0.07, 12), mat(C.steel, STEEL));
          r.rotation.z = Math.PI / 2;
          r.position.set(xo - sx * 0.055, p.wr, wz);
          r.userData.round = true;
          tag(r);
        }
        if (DETAIL >= 3) {
          var h = new T.Mesh(new T.CylinderGeometry(p.wr * 0.26,
            p.wr * 0.26, 0.05, 8), mat(C.graphite, STEEL));
          h.rotation.z = Math.PI / 2;
          h.position.set(xo - sx * 0.024, p.wr, wz);
          h.userData.round = true;
          tag(h);
        }
      }
      [-1, 1].forEach(function (sx) {
        wheelAt(sx, p.fw, 0);
        wheelAt(sx, p.rw, 0);
        if (p.dual) wheelAt(sx, p.rw, 0.21);     /* a bus twin rear */
      });

      /* -- 6. bumpers 0.10 proud of the body; above them one band
         carrying the grille and the light blocks, below the bonnet
         break. The plate's cars read from the front, so this band is
         the whole front-three-quarter silhouette. */
      var bumpH = 0.19, bumpY = p.sill + bumpH / 2 + 0.01;
      tag(box(p.W * 0.90, bumpH, 0.15, trimC, 0, bumpY, zF + 0.015, grp,
              { rough: 0.55 }));
      tag(box(p.W * 0.90, bumpH, 0.15, trimC, 0, bumpY, zR - 0.015, grp,
              { rough: 0.55 }));
      var gBot = p.sill + bumpH + 0.05;
      var gTop = Math.max(gBot + 0.11, p.nose - 0.05);
      var gMid = (gTop + gBot) / 2, gHt = gTop - gBot;
      tag(box(p.W * 0.42, gHt, 0.08, C.graphite, 0, gMid, zF + 0.005, grp,
              { rough: 0.5 }));
      if (DETAIL >= 3) {
        for (var si = 0; si < 4; si++) {
          tag(box(p.W * 0.38, gHt / 10, 0.03, C.ink, 0,
                  gBot + gHt * (si + 0.5) / 4, zF + 0.05, grp,
                  { rough: 0.6 }));
        }
      }
      var tailY = p.bed ? p.bed.rail - 0.24 : p.deck - 0.22;
      [-1, 1].forEach(function (sx) {
        var lx = sx * (hw - p.W * 0.155), ly = gMid + gHt * 0.06;
        if (DETAIL >= 2) {         /* a bezel, or a cream lamp on a cream
                                      bumper is just more trim */
          tag(box(p.W * 0.25, gHt * 0.80, 0.05, C.graphite, lx, ly,
                  zF + 0.002, grp, { rough: 0.5 }));
          tag(box(p.W * 0.21, gHt * 0.78, 0.05, C.ink, sx * (hw - p.W * 0.15),
                  Math.max(p.sill + 0.40, tailY), zR - 0.002, grp,
                  { rough: 0.5 }));
        }
        tag(box(p.W * 0.21, gHt * 0.60, 0.07, CAR_LAMP, lx, ly,
                zF + 0.012, grp, GLOSS));
        tag(box(p.W * 0.17, gHt * 0.58, 0.07, C.oxblood,
                sx * (hw - p.W * 0.15),
                Math.max(p.sill + 0.40, tailY), zR - 0.012, grp, GLOSS));
      });
      /* the plate's cars are two-tone: a trim band along the rocker
         picks up the bumpers and breaks the flank's flat slab */
      if (DETAIL >= 2) {
        var rkA = p.fw - p.wr - 0.10, rkB = p.rw + p.wr + 0.10;
        [-1, 1].forEach(function (sx) {
          tag(box(0.05, 0.11, rkA - rkB, trimC, sx * (hw + 0.004),
                  p.sill + 0.065, (rkA + rkB) / 2, grp, { rough: 0.55 }));
        });
      }

      /* -- 7. mirrors, handles, badge: the finest layer */
      if (DETAIL >= 2 && !p.noMirror) {
        [-1, 1].forEach(function (sx) {
          tag(box(0.13, 0.09, 0.09, col, sx * (hw + 0.045), p.belt + 0.07,
                  p.wsB - 0.10, grp, GLOSS));
        });
      }
      if (DETAIL >= 3) {
        var cabL = p.wsB - p.blB, hs = [0.34];
        if (cabL > 1.5) hs.push(0.74);
        [-1, 1].forEach(function (sx) {
          hs.forEach(function (t) {
            var hz = p.wsB - t * cabL;
            tag(box(0.05, 0.07, 0.28, C.graphite, sx * (hw + 0.014),
                    p.belt - 0.17, hz, grp, STEEL));
            tag(box(0.02, p.belt - p.sill - 0.16, 0.035,
                    shadeHex(col, 0.72), sx * (hw + 0.006),
                    (p.belt + p.sill) / 2 + 0.02, hz + 0.30, grp,
                    { rough: 0.8 }));
          });
        });
        tag(box(0.16, 0.06, 0.03, C.steel, 0, tailY + 0.24, zR - 0.02,
                grp, CHROME));
        [-1, 1].forEach(function (sx) {      /* the shoulder crease */
          tag(box(0.035, 0.032, p.L - 0.48, shadeHex(col, 0.80),
                  sx * (hw + 0.002), p.belt - 0.085, -0.04, grp,
                  { rough: 0.6 }));
        });
      }

      /* -- 8. a truck bed: the profile cuts the well, two side panels
         close it, and the floor sits a shade below the paint. */
      if (p.bed) {
        var bL = p.bed.z0 - p.bed.z1, bC = (p.bed.z0 + p.bed.z1) / 2;
        [-1, 1].forEach(function (sx) {
          tag(box(0.12, p.bed.rail - p.bed.floor + 0.08, bL, col,
                  sx * (hw - 0.06),
                  (p.bed.rail + p.bed.floor) / 2 - 0.04, bC, grp, GLOSS));
        });
        if (DETAIL >= 2) {
          tag(box(p.W - 0.26, 0.05, bL - 0.08, shadeHex(col, 0.70), 0,
                  p.bed.floor + 0.035, bC, grp, { rough: 0.8 }));
        }
      }

      /* -- 9. nothing floats (S4), at EVERY tier. The sun's shadow
         camera is a +/-10 orthographic box centred on the house, and
         every vehicle - garage bay (x -16.7), driveway apron (x -15.4),
         kerb (z 19.8) - projects outside it, so the tier-3 shadow map
         does not reach them. Verified by widening the box to +/-40: the
         cast shadow appears, and every other room's shadows coarsen 4x,
         which is why the frustum is not the thing to change here. Drop
         this the day the lighting pass gives the yard its own light.

         The pool MULTIPLIES rather than blending a dark disc over the
         floor: blobShadow's flat C.shadow quad LIGHTENS the garage bay,
         whose boards sit darker than #3a3340, and came out as a halo
         round every car. Grey multiplied into whatever is underneath
         can only darken it. Two rings give the pool an edge instead of
         a cut-out, and they HUG THE FOOTPRINT: the outer one stops just
         inside the body's own outline, because a contact shadow is the
         shape of the thing touching the floor, softened. The first pass
         ran them half a car's width past the bumpers on every side and
         they read as dark pools parked around the cars rather than
         under them. The rings ride inside the group, so they land on
         the garage slab (y 0.038) and the apron (y -0.206) alike. */
      if (!SHADOWS) [[0.44, 0.45, 0x9d99a3], [0.58, 0.54, 0xcfccd4]].forEach(
        function (ring, ri) {
          /* both rings at every tier: a lone hard-edged 12-gon pokes a
             visible triangle out from under the bumper at low, and two
             circles are ~40 triangles - not a tier concern */
          var d = new T.Mesh(new T.CircleGeometry(1, DETAIL >= 2 ? 22 : 16),
            new T.MeshBasicMaterial({ color: ring[2], transparent: true,
                                      blending: T.MultiplyBlending,
                                      depthWrite: false }));
          d.rotation.x = -Math.PI / 2;
          d.scale.set(p.W * ring[0], p.L * ring[1], 1);
          d.position.set(0, 0.012 + ri * 0.004, 0);
          d.renderOrder = -2 + ri;
          grp.add(d);
        });
      /* ...and at tier 3 a car RECEIVES one again. The seam that ran
         across the minivan's roof cap - half the cap sampling the map,
         half forced lit - was the +/-10 box's boundary crossing the bay
         at x ~ -14.1. The box now follows the camera and always contains
         the room it is looking at, so there is no boundary to cross.
         Below tier 3 the two painted rings above are still the whole
         shadow. */
    }

    /* the school bus, at the curb only while it is actually out. Same
       kit as the cars: a conventional bonnet, a window band cut by the
       cabin uprights, black rub rails, a stop arm on the traffic side. */
    /* GLOSS, like every other painted-metal body (bible S2). The bus was
       authored MATTE (rough 0.55, envInt 0.10) because ACES bleached its
       yellow to cream; that was the renderer, not the paint, and the
       lighting pass fixed the renderer. Reverted and re-shot: the yellow
       holds at #efa41c with a sheen on the roof and bonnet. */
    var BUS_BODY = { paint: { rough: 0.3, metal: 0.02, envInt: 0.25 },
                     L: 5.6, W: 2.05, wr: 0.42, sill: 0.30, nose: 1.16,
                     hood: 1.34, belt: 1.48, deck: 1.48, roof: 2.40,
                     fw: 2.02, rw: -1.82, wsB: 1.86, wsT: 1.62,
                     blT: -2.62, blB: -2.74, dual: true,
                     pil: [0.12, 0.27, 0.42, 0.57, 0.72, 0.88],
                     trim: 0x23272c, noMirror: true };
    var busG = new T.Group();
    busG.visible = false;
    busG.position.set(-5.5, -0.31, 19.8);
    busG.userData.zone = 'curb';
    extG.add(busG);
    (function () {
      var BUSY = 0xefa41c;
      /* built nose-forward and turned a quarter: the bus runs along the
         street (world +x) and shows the camera its left flank, which is
         the side the stop arm lives on. */
      var inner = new T.Group();
      inner.rotation.y = Math.PI / 2;
      busG.add(inner);
      function btag(m) {
        if (!m) return m;
        m.userData.zone = 'curb';
        finish(m);
        if (m.parent !== inner) inner.add(m);
        return m;
      }
      buildVehicle(inner, BUS_BODY, BUSY, btag);
      var hwB = BUS_BODY.W / 2;
      if (DETAIL >= 2) {                 /* the rub rails, and the door */
        [-1, 1].forEach(function (sx) {
          [BUS_BODY.belt - 0.22, BUS_BODY.belt - 0.60].forEach(function (y) {
            btag(box(0.04, 0.08, BUS_BODY.L - 1.30, C.ink,
                     sx * (hwB + 0.012), y, -0.55, inner, { rough: 0.7 }));
          });
        });
        /* the entrance: a glazed panel behind the front wheel, kerb side */
        btag(box(0.05, 1.02, 0.50, C.ink, hwB + 0.012, 0.92, 1.30, inner,
                 { rough: 0.6 }));
        btag(box(0.03, 0.86, 0.38, CAR_GLASS, hwB + 0.03, 0.96, 1.30,
                 inner, GLOSS));
        /* the stop arm, on the traffic side */
        var arm = new T.Mesh(new T.CylinderGeometry(0.27, 0.27, 0.05, 8),
          mat(C.red, GLOSS));
        arm.rotation.z = Math.PI / 2;
        arm.position.set(-(hwB + 0.13), BUS_BODY.belt - 0.10, 0.35);
        btag(arm);
        if (DETAIL >= 3) {
          var ring = new T.Mesh(new T.CylinderGeometry(0.17, 0.17, 0.055, 8),
            mat(C.cream, GLOSS));
          ring.rotation.z = Math.PI / 2;
          ring.position.set(-(hwB + 0.145), BUS_BODY.belt - 0.10, 0.35);
          btag(ring);
          btag(box(0.06, 0.10, 0.16, C.ink, -(hwB + 0.05),
                   BUS_BODY.belt - 0.10, 0.35, inner, { rough: 0.7 }));
        }
      }
      if (DETAIL >= 3) {                 /* roof beacons, front and back */
        [-1, 1].forEach(function (sx) {
          btag(box(0.16, 0.12, 0.12, C.red, sx * 0.52, BUS_BODY.roof + 0.06,
                   BUS_BODY.wsT - 0.16, inner, GLOSS));
          btag(box(0.16, 0.12, 0.12, C.red, sx * 0.52, BUS_BODY.roof + 0.06,
                   BUS_BODY.blT + 0.16, inner, GLOSS));
        });
      }
      groups.curb = busG;
    })();

    /* the family real cars, drawn by shape. color_code is the paint;
       seat_capacity stretches the car along z (the tyres are counter-
       scaled so they stay round). */
    var CAR_BODIES = {
      /* a boot deck below the beltline, a raked backlight */
      sedan:   { L: 3.35, W: 1.62, wr: 0.27, sill: 0.15, nose: 0.56,
                 hood: 0.65, belt: 0.70, deck: 0.64, roof: 1.21,
                 fw: 1.02, rw: -1.02, wsB: 0.68, wsT: 0.30,
                 blT: -0.50, blB: -0.86, pil: [0.50] },
      /* tall, upright, roof almost to the tail */
      suv:     { L: 3.55, W: 1.74, wr: 0.35, sill: 0.27, nose: 0.76,
                 hood: 0.86, belt: 0.94, deck: 0.94, roof: 1.56,
                 fw: 1.10, rw: -1.08, wsB: 0.82, wsT: 0.46,
                 blT: -1.40, blB: -1.60, pil: [0.30, 0.62] },
      /* a short cab and an open bed with a tailgate */
      truck:   { L: 3.95, W: 1.76, wr: 0.32, sill: 0.25, nose: 0.80,
                 hood: 0.90, belt: 0.98, deck: 0.98, roof: 1.62,
                 fw: 1.30, rw: -1.06, wsB: 0.92, wsT: 0.56,
                 blT: -0.12, blB: -0.20, pil: [],
                 bed: { z0: -0.30, z1: -1.84, floor: 0.76, rail: 1.08 } },
      /* long tall cabin, sloped nose, a slab flank */
      minivan: { L: 3.75, W: 1.74, wr: 0.30, sill: 0.18, nose: 0.66,
                 hood: 0.76, belt: 0.84, deck: 0.84, roof: 1.58,
                 fw: 1.18, rw: -1.12, wsB: 1.08, wsT: 0.62,
                 blT: -1.50, blB: -1.72, pil: [0.28, 0.58] },
      /* short, steep backlight landing on the tail */
      hatch:   { L: 3.02, W: 1.56, wr: 0.27, sill: 0.15, nose: 0.56,
                 hood: 0.65, belt: 0.70, deck: 0.70, roof: 1.25,
                 fw: 0.91, rw: -0.91, wsB: 0.62, wsT: 0.26,
                 blT: -0.80, blB: -1.20, pil: [0.45] },
      /* the sedan nose, a roof carried flat to a near-vertical tail */
      wagon:   { L: 3.62, W: 1.64, wr: 0.28, sill: 0.16, nose: 0.58,
                 hood: 0.67, belt: 0.72, deck: 0.72, roof: 1.26,
                 fw: 1.09, rw: -1.09, wsB: 0.76, wsT: 0.40,
                 blT: -1.44, blB: -1.66, pil: [0.30, 0.62] },
      /* tallest, barely any bonnet, a slab flank */
      van:     { L: 3.85, W: 1.80, wr: 0.32, sill: 0.20, nose: 0.92,
                 hood: 0.98, belt: 1.04, deck: 1.04, roof: 1.96,
                 fw: 1.30, rw: -1.16, wsB: 1.56, wsT: 1.32,
                 blT: -1.66, blB: -1.83, pil: [0.24, 0.50, 0.76] }
    };
    var carsG = new T.Group();
    extG.add(carsG);
    function buildCar(c) {
      var p = CAR_BODIES[c.body] || CAR_BODIES.sedan;   /* unset = sedan */
      var col = 0x9aa2a9;
      try {
        if (c.color) col = parseInt(String(c.color).replace('#', ''), 16);
        if (!isFinite(col)) col = 0x9aa2a9;
      } catch (e) { col = 0x9aa2a9; }
      var grp = new T.Group();
      grp.userData.zone = 'garage';
      grp.userData.room = 'garage';
      function tag(m) {
        if (!m) return m;
        m.userData.zone = 'garage'; m.userData.room = 'garage';
        finish(m);
        if (m.parent !== grp) grp.add(m);
        return m;
      }
      buildVehicle(grp, p, col, tag);
      /* seat_capacity still nudges the length: a z stretch on the whole
         car, tyres counter-scaled so they stay round */
      var k = Math.max(0.94, Math.min(1.12, 1 + 0.022 * ((c.seats || 4) - 4)));
      if (Math.abs(k - 1) > 0.004) {
        grp.scale.z = k;
        grp.traverse(function (o) {
          if (o.userData && o.userData.round) o.scale.z = 1 / k;
        });
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
    var makeBag = null;                  /* set below; used by syncMudroom */
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
      /* ============ the studio pass (docs/house_style_bible.md) =========
         The room inherited exterior siding from the architect pass and
         read as a covered porch. It is a finished room now: a shiplap
         wainscot in sage under a cap rail, plaster above, a baseboard —
         the hard-wearing lower wall the plates give a mudroom. Its four
         accents were picked to sit BESIDE the kitchen's (teal,
         terracotta, brass, oxblood), because the kitchen doorway looks
         straight in here: sage, brass, oxblood, terracotta. Dark
         anchors: the garage door on the west wall and the shoe cabinet
         on the north, one at each end of the frame. */
      var D2 = DETAIL >= 2, D3 = DETAIL >= 3;
      var PLASTER = { rough: 0.94 }, FAB = { rough: 0.98 };
      var woodO = NICE ? { rough: 0.62, map: woodLight } : { rough: 0.62 };
      var woodK = NICE ? 0xffffff : 0xc89a66;
      var SAGE = C.sage, SAGED = C.sageDeep, TRIM = C.cab;
      var NWF = 2.60;                 /* the north wall's inner face */
      var WWF = -12.60;               /* the west wall's inner face */
      var FLR = 0.03;                 /* the mudroom floor, not the slab */
      function mb(w, h, d, c, x, y, z, o) { return mtag(box(w, h, d, c, x, y, z, extG, o)); }
      function mr(w, h, d, r, c, x, y, z, o) { return mtag(rbox(w, h, d, r, c, x, y, z, extG, o)); }
      function mc(a, b2, h, c, x, y, z, s, o) { return mtag(cyl(a, b2, h, c, x, y, z, extG, s, o)); }
      function msh(rx, rz, x, z) { return blobShadow(rx, rz, x, z, extG, FLR + 0.015); }
      /* the kitchen's case builder, dropped into the shell group so the
         mudroom's props hide and tag with the rest of the room */
      function mCase(cx, cz, rot, W, D, y0, y1, rows, opt) {
        var g = kCase(cx, cz, rot, W, D, y0, y1, rows, opt);
        extG.add(g);
        g.traverse(function (o) { o.userData.room = 'mudroom'; });
        return g;
      }
      /* the kitchen's houseplant, three silhouettes, in its own group so
         it carries the room tag and its own contact shadow */
      function mPlant(x, y0, z, s, potC, potO, kind, shadow) {
        var g = new T.Group();
        extG.add(g);
        kPlant(g, x, y0, z, s, potC, potO, kind, false);
        g.traverse(function (o) { o.userData.room = 'mudroom'; });
        if (shadow) msh(0.34 * s, 0.32 * s, x, z);
        return g;
      }
      /* ---- one run of finished wall: plaster field, shiplap dado, cap
         rail, baseboard. axis 'z' = the north wall (face looks +z),
         axis 'x' = the west wall (face looks +x). One builder, both. */
      function wallRun(axis, face, a0, a1, top, dado) {
        var L = a1 - a0, mid = (a0 + a1) / 2;
        function plate(h, d0, d1, c, y, o) {
          var d = d1 - d0, ctr = face + (d0 + d1) / 2;
          return axis === 'z' ? mb(L, h, d, c, mid, y, ctr, o)
                              : mb(d, h, L, c, ctr, y, mid, o);
        }
        plate(top, 0, 0.05, C.wall, top / 2, PLASTER);
        if (!dado) return;
        plate(1.32, 0.05, 0.12, SAGE, 0.88, { rough: 0.92 });
        if (D3) [0.45, 0.68, 0.90, 1.12, 1.34].forEach(function (y) {
          plate(0.018, 0.113, 0.132, SAGED, y);          /* board seams */
        });
        plate(0.10, 0.05, 0.21, TRIM, 1.59, MATT);       /* cap rail */
        if (D3) plate(0.045, 0.05, 0.155, C.cabShade, 1.512);
        plate(0.22, 0.05, 0.17, TRIM, 0.11, MATT);       /* baseboard */
      }
      wallRun('z', NWF, -12.60, -6.85, 4.20, true);
      if (D2) {                       /* crown: the wall head gets a line */
        mb(5.75, 0.14, 0.14, TRIM, -9.725, 4.11, NWF + 0.12, MATT);
        mb(0.14, 0.14, 5.75, TRIM, WWF + 0.12, 4.11, 5.425, MATT);
        if (D3) {
          mb(5.75, 0.05, 0.09, C.cabShade, -9.725, 4.00, NWF + 0.095, MATT);
          mb(0.09, 0.05, 5.75, C.cabShade, WWF + 0.095, 4.00, 5.425, MATT);
        }
      }
      /* the west wall breaks either side of the garage door */
      wallRun('x', WWF, 2.55, 2.97, 4.20, true);
      wallRun('x', WWF, 4.43, 8.30, 4.20, true);
      mb(0.05, 1.28, 1.46, C.wall, WWF + 0.025, 3.56, 3.70, PLASTER);
      /* the east side is the great room's face of the mudroom wall: it
         closes the frame's right edge, so it gets plaster, not siding */
      /* the east side is the great room's face of the mudroom wall, and
         it closes the frame's right edge. Below the room's wall head it
         wears the room's finish; above it the wall runs on to the eaves,
         so a crown marks where the room stops and the rest goes quiet
         instead of standing there as a white cliff. */
      wallRun('x', -6.85, 4.40, 6.02, 4.20, true);
      mb(0.05, 2.84, 1.62, 0xdcd5c8, -6.825, 5.62, 5.21, PLASTER);
      /* and its cut end wears the plates' wall-thickness band, or the
         camera reads raw clapboard down the frame's right edge */
      mb(0.34, 7.00, 0.06, C.cabShade, -7.00, 3.50, 6.03, MATT);

      /* ================= 1. the garage door (S7 mudroom.3) =============
         The west wall is the garage connection and was blank. A cased
         opening now: casing boards proud of the wall, a panelled slab in
         slate — the room's first dark anchor — a brass knob, a
         threshold, and a jamb the wall dies into. */
      [3.03, 4.37].forEach(function (cz) {
        mb(0.06, 2.92, 0.14, TRIM, WWF + 0.03, 1.46, cz, MATT);
      });
      mb(0.06, 0.14, 1.62, TRIM, WWF + 0.03, 2.85, 3.70, MATT);
      if (D2) mb(0.15, 0.09, 1.80, TRIM, WWF + 0.075, 2.97, 3.70, MATT);
      if (D3) {                        /* the casing's inner bead */
        [3.09, 4.31].forEach(function (cz) {
          mb(0.10, 2.86, 0.03, C.cabShade, WWF + 0.05, 1.43, cz, MATT);
        });
        mb(0.10, 0.03, 1.28, C.cabShade, WWF + 0.05, 2.79, 3.70, MATT);
      }
      mb(0.10, 2.72, 1.18, C.slate, WWF + 0.05, 1.38, 3.70, { rough: 0.62 });
      if (D2) {                        /* stiles, rails and two panels */
        [[0.86, 1.02], [1.94, 0.94]].forEach(function (pn) {
          mb(0.02, pn[1], 0.86, 0x4a5460, WWF + 0.108, pn[0], 3.70,
             { rough: 0.6 });
          if (D3) mb(0.02, pn[1] - 0.14, 0.72, C.slate, WWF + 0.122, pn[0],
                     3.70, { rough: 0.6 });
        });
        mc(0.05, 0.05, 0.09, C.brass, WWF + 0.16, 1.36, 4.16, 10, CHROME)
          .rotation.z = Math.PI / 2;
        mb(0.30, 0.05, 1.20, woodK, WWF + 0.15, FLR + 0.025, 3.70, woodO);
      }

      /* ================= 2. the bench (S7 mudroom.1) ===================
         It was a plank on four posts. Now it is casework: toe kick,
         carcass, face frame, three open shoe cubbies over a darker back,
         a wood seat that overhangs, and a cushion. */
      var BX = -11.45, BZ = 3.08;
      mCase(BX, BZ, 0, 1.90, 0.62, 0, 0.52, [
        { h: 0.36, kind: 'bays', bays: 3, tiers: 1, depth: 0.56, back: SAGED }
      ], { toe: true });
      mb(2.04, 0.06, 0.68, woodK, BX, 0.55, BZ + 0.02, woodO);
      mr(1.80, 0.17, 0.56, 0.08, C.linen, BX, 0.665, BZ + 0.02, FAB);
      if (D2) [-0.20, 0.20].forEach(function (dz) {
        mb(1.78, 0.026, 0.026, C.oxblood, BX, 0.732, BZ + 0.02 + dz, FAB);
      });
      if (D3) [-0.56, 0.56].forEach(function (dx) {
        mb(0.026, 0.16, 0.54, C.oxblood, BX + dx, 0.665, BZ + 0.02, FAB);
      });
      msh(1.08, 0.38, BX, BZ);
      /* a folded throw at the far end: S4 wants two things on any
         surface this size, and the backpacks are a count, not a given */
      if (D2) {
        mr(0.28, 0.10, 0.44, 0.03, SAGED, -12.26, 0.80, BZ - 0.06, FAB);
        mr(0.26, 0.08, 0.42, 0.03, C.linen, -12.26, 0.89, BZ - 0.06, FAB);
      }
      /* shoes in the cubbies: a sole, an upper and a toe, not a block */
      function shoe(x, y, z, c, flip) {
        mr(0.12, 0.085, 0.26, 0.04, c, x, y + 0.075, z, { rough: 0.7 });
        mc(0.055, 0.055, 0.11, c, x, y + 0.105, z - 0.09, 10, { rough: 0.7 })
          .rotation.z = Math.PI / 2;
        if (D3) mb(0.135, 0.035, 0.28, C.graphite, x, y + 0.018, z,
                   { rough: 0.8 }).rotation.y = flip ? 0.06 : -0.06;
      }
      if (D2) {
        [[-12.083, C.oxblood], [-11.45, C.slate], [-10.817, 0x6f7f74]]
          .forEach(function (b, i) {
            shoe(b[0] - 0.10, 0.22, BZ + 0.03, b[1], false);
            shoe(b[0] + 0.10, 0.22, BZ + 0.03, b[1], true);
            if (D3) mr(0.22, 0.10, 0.30, 0.03, i % 2 ? C.linen : C.cork,
                       b[0] + 0.26, 0.28, BZ + 0.02, FAB);
          });
      }

      /* ================= 3. the hook rail (S7 mudroom.1) ===============
         Three cubes became a mounting rail with real hooks: a back
         plate, an arm angling out and down, and an upturned tip. */
      mb(1.90, 0.30, 0.06, woodK, BX, 2.02, NWF + 0.08, woodO);
      if (D2) mb(1.94, 0.05, 0.12, TRIM, BX, 2.195, NWF + 0.11, MATT);
      var HOOKX = [-12.16, -11.70, -11.24, -10.78];
      HOOKX.forEach(function (hx) {
        mr(0.09, 0.17, 0.03, 0.014, C.brass, hx, 1.99, NWF + 0.125, STEEL);
        if (!D2) return;
        mc(0.023, 0.023, 0.19, C.brass, hx, 1.96, NWF + 0.216, 8, STEEL)
          .rotation.x = 2.0;
        mc(0.023, 0.023, 0.07, C.brass, hx, 1.955, NWF + 0.303, 8, STEEL);
      });
      /* coats: a body, shoulders, a collar and two sleeves — a rounded
         slab is a bath towel, not a coat */
      function coat(hx, len, c, cd) {
        var z = NWF + 0.245, top = 1.82;
        /* shoulders across the hook, a flat body under them, and two
           sleeves clear of the body's silhouette — a rounded slab with
           no sleeve line reads as a sleeping bag, which is what the
           first pass built */
        mr(0.34, len, 0.14, 0.05, c, hx, top - len / 2, z, FAB);
        mr(0.40, 0.13, 0.16, 0.05, c, hx, top - 0.02, z, FAB);
        mr(0.15, 0.09, 0.13, 0.04, cd, hx, top + 0.075, z - 0.015, FAB);
        [-1, 1].forEach(function (sn) {
          var sl = mr(0.105, len * 0.74, 0.115, 0.045, c, hx + sn * 0.192,
                      top - 0.06 - len * 0.37, z + 0.008, FAB);
          sl.rotation.z = sn * 0.055;
          if (D3) mr(0.10, 0.05, 0.11, 0.03, cd, hx + sn * 0.20,
                     top - 0.09 - len * 0.74, z + 0.008, FAB);
        });
        if (D3) {
          mb(0.025, len - 0.16, 0.015, cd, hx, top - 0.04 - len / 2,
             z + 0.074, FAB);
          mb(0.10, 0.085, 0.015, cd, hx - 0.085, top - 0.30 - len / 2,
             z + 0.074, FAB);
        }
      }
      if (D2) {
        coat(-12.16, 0.96, C.oxblood, 0x71322b);
        coat(-11.24, 0.82, SAGED, 0x5f7a6d);
        coat(-10.78, 0.64, C.terracotta, 0x8f5528);
        /* a tote on the spare hook — the plates always hang a bag */
        mr(0.28, 0.32, 0.15, 0.05, C.terracotta, -11.70, 1.64, NWF + 0.25, FAB);
        [-1, 1].forEach(function (s) {
          var st = mr(0.035, 0.30, 0.05, 0.015, C.cork, -11.70 + s * 0.095,
                      1.87, NWF + 0.25, FAB);
          st.rotation.z = s * 0.22;
        });
        if (D3) mb(0.20, 0.09, 0.02, 0x8f5528, -11.70, 1.71, NWF + 0.327, FAB);
      }

      /* ================= 4. the shelf over the hooks (S3.2) ============ */
      mb(2.00, 0.07, 0.42, woodK, BX, 2.60, NWF + 0.26, woodO);
      if (D3) mb(2.00, 0.075, 0.02, C.cabShade, BX, 2.60, NWF + 0.46, MATT);
      if (D2) [-12.28, -10.62].forEach(function (bx) {
        mb(0.05, 0.24, 0.32, TRIM, bx, 2.44, NWF + 0.21, MATT);
      });
      /* a basket: a body, a darker rim, and woven handle slots */
      function basket(x, w, d, h, c, cd) {
        mr(w, h, d, 0.035, c, x, 2.635 + h / 2, NWF + 0.26, { rough: 0.98 });
        mb(w + 0.03, 0.05, d + 0.03, cd, x, 2.635 + h - 0.02, NWF + 0.26,
           { rough: 0.95 });
        if (D3) [-1, 1].forEach(function (s) {
          mb(0.10, 0.035, 0.02, cd, x + s * w * 0.22, 2.635 + h * 0.6,
             NWF + 0.26 + d / 2, { rough: 0.9 });
        });
      }
      if (D2) {
        basket(-12.14, 0.52, 0.34, 0.30, C.cork, 0x8f6a3f);
        basket(-11.56, 0.44, 0.32, 0.26, C.linen, 0xbdac92);
        mr(0.36, 0.26, 0.28, 0.03, SAGED, -11.06, 2.755, NWF + 0.26, MATT);
        mb(0.39, 0.05, 0.31, 0x5f7a6d, -11.06, 2.90, NWF + 0.26, MATT);
        mPlant(-10.60, 2.635, NWF + 0.26, 0.33, C.terracotta,
               { rough: 0.85 }, 'mound', false);
        if (D3) {
          mr(0.28, 0.07, 0.22, 0.02, C.cream, -11.06, 2.96, NWF + 0.26, FAB);
          mr(0.26, 0.06, 0.20, 0.02, C.oxblood, -11.06, 3.02, NWF + 0.26, FAB);
        }
      }

      /* ================= 5. the shoe cabinet (S3.1) ====================
         The north wall's east panel is over two units wide, so it earns
         a piece of furniture, art and a light. The cabinet is the room's
         second dark anchor and balances the garage door across frame. */
      var CX = -9.75, CZ2 = NWF + 0.43;
      mCase(CX, CZ2, 0, 1.45, 0.52, 0, 1.02, [
        { h: 0.46, cells: [{ w: 1, kind: 'drawers2' }] },
        { h: 0.40, cells: [{ w: 1, kind: 'doors2' }] }
      ], { toe: true, face: C.slate, body: 0x2b3138 });
      mb(1.56, 0.07, 0.62, woodK, CX, 1.055, CZ2 + 0.02, woodO);
      msh(0.82, 0.34, CX, CZ2);
      if (D2) {
        kBowl(extG, CX - 0.48, 1.09, CZ2 - 0.02, 0.16, C.brass);
        mb(0.30, 0.05, 0.22, C.oxblood, CX - 0.02, 1.115, CZ2 + 0.04, MATT);
        mb(0.28, 0.045, 0.20, C.cream, CX - 0.01, 1.163, CZ2 + 0.05, MATT);
        mPlant(CX + 0.34, 1.09, CZ2 - 0.01, 0.36, C.terracotta,
               { rough: 0.85 }, 'spray', false);
        if (D3) {
          mb(0.26, 0.04, 0.18, SAGE, CX - 0.02, 1.208, CZ2 + 0.03, MATT);
          mc(0.055, 0.05, 0.10, C.cream, CX - 0.22, 1.14, CZ2 + 0.16, 10, GLOSS);
        }
      }
      /* art: a pair of frames, mat and image, on the wall plane */
      function art(x, y, w, h, c) {
        mr(w, h, 0.05, 0.015, C.slate, x, y, NWF + 0.075, { rough: 0.55 });
        if (D3) mb(w - 0.06, h - 0.06, 0.02, C.cream, x, y, NWF + 0.104, MATT);
        mb(w - 0.15, h - 0.15, 0.02, c, x, y, NWF + 0.112, MATT);
      }
      if (D2) {
        art(-10.18, 2.36, 0.46, 0.58, SAGE);
        art(-9.60, 2.36, 0.42, 0.58, C.terracotta);
      }
      /* the wall light the plates always give a mudroom */
      if (D2) {
        mr(0.13, 0.20, 0.05, 0.02, C.brass, -10.30, 2.86, NWF + 0.075, STEEL);
        mc(0.022, 0.022, 0.22, C.brass, -10.30, 2.86, NWF + 0.19, 8, STEEL)
          .rotation.x = Math.PI / 2;
        var scShade = new T.Mesh(
          new T.CylinderGeometry(0.10, 0.18, 0.18, 14, 1, true),
          PBR ? new T.MeshStandardMaterial({ color: 0xf3e8d2, roughness: 0.8,
                                             emissive: 0xffd9a0,
                                             emissiveIntensity: 0.45,
                                             side: T.DoubleSide })
              : new T.MeshLambertMaterial({ color: 0xf3e8d2, side: T.DoubleSide }));
        scShade.position.set(-10.30, 2.77, NWF + 0.30);
        mtag(scShade); finish(scShade, true); extG.add(scShade);
      }

      /* ================= 6. the floor (S4) =============================
         A runner in front of the bench, a boot tray with two pairs, and
         a mat at the street door. Nothing floats: every one of them has
         a contact shadow on the mudroom's own floor height. */
      function mrug(w, d, x, z, c, lift) {
        var m = new T.Mesh(new T.PlaneGeometry(w, d), mat(c, { rough: 1.0 }));
        m.rotation.x = -Math.PI / 2;
        m.position.set(x, FLR + 0.012 + (lift || 0), z);
        if (SHADOWS) m.receiveShadow = true;
        mtag(m); extG.add(m); return m;
      }
      /* the quiet tone is the base layer: at the low tier only the base
         draws, and a rug that is all border reads as a red slab. The
         stripe is the layer that waits for tier 3. */
      mrug(1.66, 0.76, -11.55, 3.92, C.rugB);
      if (D3) mrug(1.52, 0.64, -11.55, 3.92, C.oxblood, 0.006);
      if (D2) mrug(1.44, 0.56, -11.55, 3.92, C.rugF, 0.012);
      mrug(1.10, 0.72, -9.80, 7.55, C.rugB);
      if (D3) mrug(1.00, 0.62, -9.80, 7.55, SAGED, 0.006);
      if (D2) mrug(0.92, 0.56, -9.80, 7.55, C.rugF, 0.012);
      /* the boot tray: a lipped pan, not a slab */
      mb(1.04, 0.05, 0.50, C.graphite, -10.20, FLR + 0.025, 3.80, { rough: 0.6 });
      if (D2) {
        mb(0.96, 0.03, 0.42, 0x3c434a, -10.20, FLR + 0.062, 3.80, { rough: 0.7 });
        [-0.495, 0.495].forEach(function (dx) {
          mb(0.05, 0.09, 0.50, C.graphite, -10.20 + dx, FLR + 0.075, 3.80,
             { rough: 0.6 });
        });
      }
      function boot(x, z, c) {
        mc(0.085, 0.095, 0.32, c, x, FLR + 0.21, z, 10, { rough: 0.78 });
        mr(0.17, 0.115, 0.28, 0.05, c, x, FLR + 0.115, z + 0.10, { rough: 0.78 });
        if (D3) {
          mb(0.185, 0.035, 0.30, C.ink, x, FLR + 0.048, z + 0.10, { rough: 0.85 });
          mc(0.088, 0.088, 0.03, 0xd8cfc0, x, FLR + 0.37, z, 10, FAB);
        }
      }
      if (D2) {
        boot(-10.55, 3.74, C.slate); boot(-10.36, 3.74, C.slate);
        boot(-10.04, 3.74, 0x4f5b52); boot(-9.85, 3.74, 0x4f5b52);
      }
      msh(0.56, 0.30, -10.20, 3.82);

      /* ================= 7. the west wall's floor pieces ===============
         An umbrella stand and the room's tall plant, both inside the
         0.6-unit rule off the garage door. */
      if (D2) {
        mc(0.17, 0.145, 0.44, C.terracotta, -12.24, FLR + 0.22, 4.86, 14, GLOSS);
        mc(0.18, 0.18, 0.05, C.terracotta, -12.24, FLR + 0.42, 4.86, 14, GLOSS);
        [[-0.04, -0.05, SAGED, 0.10], [0.05, 0.04, C.oxblood, -0.08]]
          .forEach(function (u) {
            var sh = mc(0.032, 0.032, 0.86, u[2], -12.24 + u[0], FLR + 0.66,
                        4.86 + u[1], 8, { rough: 0.7 });
            sh.rotation.z = u[3];
            mc(0.018, 0.072, 0.30, u[2], -12.24 + u[0] + u[3] * 0.72,
               FLR + 0.94, 4.86 + u[1], 8, { rough: 0.7 }).rotation.z = u[3];
            if (D3) mc(0.024, 0.024, 0.13, C.wood2,
                       -12.24 + u[0] + u[3] * 1.05, FLR + 1.20, 4.86 + u[1],
                       8, WOODM).rotation.z = u[3];
          });
        msh(0.22, 0.22, -12.24, 4.86);
      }
      mPlant(-12.12, FLR, 5.46, 0.90, C.terracotta, { rough: 0.85 },
             'fiddle', true);
      if (D2) {                       /* the garden can lives by the door */
        mc(0.125, 0.145, 0.30, C.steel, -11.66, FLR + 0.15, 5.08, 12, STEEL);
        mc(0.132, 0.132, 0.035, C.steel, -11.66, FLR + 0.315, 5.08, 12, STEEL);
        var wcs = mc(0.05, 0.075, 0.42, C.steel, -11.85, FLR + 0.30, 5.22,
                     10, STEEL);
        wcs.rotation.z = -0.95; wcs.rotation.y = 0.55;
        mc(0.085, 0.055, 0.06, C.steel, -12.02, FLR + 0.44, 5.34, 10, STEEL)
          .rotation.z = -0.95;
        if (D3) [-1, 1].forEach(function (sn) {   /* an arched handle */
          var hd = mc(0.024, 0.024, 0.24, C.steel, -11.66 + sn * 0.055,
                      FLR + 0.44, 5.08, 8, STEEL);
          hd.rotation.z = sn * 0.55;
        });
        msh(0.17, 0.17, -11.70, 5.12);
      }
      /* the west wall's south panel is 3.9 units wide, so S4 wants
         something on it: a clock, which is what a mudroom wall is for */
      if (D2) {
        mc(0.30, 0.30, 0.05, C.brass, WWF + 0.045, 2.74, 5.30, 20, STEEL)
          .rotation.z = Math.PI / 2;
        mc(0.26, 0.26, 0.05, C.cream, WWF + 0.075, 2.74, 5.30, 20, GLOSS)
          .rotation.z = Math.PI / 2;
        /* the hands are what makes it a clock rather than a brass
           ring on a cream wall — they cannot wait for tier 3 */
        mb(0.02, 0.17, 0.025, C.dark, WWF + 0.105, 2.80, 5.30, MATT);
        mb(0.02, 0.025, 0.13, C.dark, WWF + 0.105, 2.74, 5.35, MATT);
        if (D3) mc(0.028, 0.028, 0.02, C.dark, WWF + 0.11, 2.74, 5.30, 10,
                   MATT).rotation.z = Math.PI / 2;
        /* a print over the umbrella stand, and a peg with a sun hat:
           the wall between the garage door and the clock was bare */
        mr(0.05, 0.54, 0.42, 0.015, C.slate, WWF + 0.025, 2.52, 4.72,
           { rough: 0.55 });
        if (D3) mb(0.02, 0.48, 0.36, C.cream, WWF + 0.055, 2.52, 4.72, MATT);
        mb(0.02, 0.40, 0.28, C.terracotta, WWF + 0.063, 2.52, 4.72, MATT);
        mr(0.05, 0.38, 0.32, 0.015, C.slate, WWF + 0.025, 3.10, 4.72,
           { rough: 0.55 });
        if (D3) mb(0.02, 0.33, 0.27, C.cream, WWF + 0.055, 3.10, 4.72, MATT);
        mb(0.02, 0.26, 0.20, SAGE, WWF + 0.063, 3.10, 4.72, MATT);
      }

      /* ================= 8. the street door's jamb =====================
         The wall it hangs in is cut away for the camera, so the opening
         gets the plates' visible wall-thickness band (S7 exterior.2) —
         otherwise the slab is a plank floating in a gap. */
      function jamb(m) { m.userData.zone = 'door'; return m; }
      [-10.71, -8.89].forEach(function (jx) {
        jamb(mb(0.12, 4.20, 0.26, C.cabShade, jx, 2.10, 8.21, MATT));
      });
      jamb(mb(1.94, 0.12, 0.26, C.cabShade, -9.80, 4.14, 8.21, MATT));
      jamb(mb(1.94, 0.07, 0.30, woodK, -9.80, FLR + 0.035, 8.19, woodO));
      /* and the slab's STREET face, which is the face this camera sees:
         a glazed upper light, two raised panels, a lockset and a kick
         plate. Everything stays inside the wall's 0.24 of thickness so
         the exterior view still reads as a solid clapboard wall. They
         carry the door's zone, so the tap target is the whole door. */
      if (D2) {
        var dz0 = 8.235;
        function dpart(m) {
          m.userData.zone = 'door'; m.userData.room = 'mudroom'; return m;
        }
        dpart(mb(1.44, 0.05, 0.05, 0x8a6d49, -9.80, 2.16, dz0, WOODM));
        [[2.98, 1.36], [1.44, 0.86], [0.66, 0.52]].forEach(function (pn) {
          dpart(mb(1.16, pn[1], 0.05, 0x8a6d49, -9.80, pn[0], dz0, WOODM));
          dpart(mb(1.02, pn[1] - 0.14, 0.04, 0xc79b63, -9.80, pn[0],
                   dz0 + 0.035, WOODM));
        });
        /* the upper panel is glass: a light in the door, the one thing
           that says street side rather than cupboard */
        dpart(mb(0.98, 1.18, 0.04, 0x9dbccd, -9.80, 2.98, dz0 + 0.05, GLOSS));
        if (D3) [-0.32, 0.32].forEach(function (dx) {
          dpart(mb(0.03, 1.18, 0.03, 0x8a6d49, -9.80 + dx, 2.98, dz0 + 0.072,
                   WOODM));
        });
        dpart(mb(1.36, 0.20, 0.03, C.brass, -9.80, 0.28, dz0 + 0.02, STEEL));
        dpart(mr(0.16, 0.34, 0.04, 0.02, C.brass, -9.16, 1.98, dz0 + 0.02,
                 STEEL));
        dpart(mc(0.06, 0.06, 0.10, C.brass, -9.16, 2.06, dz0 + 0.075, 10,
                 CHROME)).rotation.x = Math.PI / 2;
      }

      /* ---- the backpacks syncMudroom deals onto the bench ------------
         One per active child — the count is real data. The bag itself is
         built here, where the rounded-box and material helpers live. */
      makeBag = function (c) {
        var g = new T.Group();
        function part(m) { m.userData.room = 'mudroom'; finish(m); g.add(m); return m; }
        function pb(w, h, d, r, col, x, y, z, o) {
          var m = new T.Mesh(D2 ? roundedGeo(w, h, d, r) : new T.BoxGeometry(w, h, d),
                             mat(col, o || FAB));
          m.position.set(x, y, z); return part(m);
        }
        pb(0.34, 0.46, 0.26, 0.07, c, 0, 0, 0);
        pb(0.345, 0.15, 0.265, 0.05, 0x3a3330, 0, 0.185, 0.01);
        if (D2) {
          pb(0.26, 0.18, 0.08, 0.03, 0x3a3330, 0, -0.09, 0.15);
          [-0.10, 0.10].forEach(function (sx) {
            pb(0.05, 0.36, 0.05, 0.02, 0x3a3330, sx, 0.00, -0.15);
          });
        }
        if (D3) {
          pb(0.11, 0.05, 0.05, 0.02, 0x3a3330, 0, 0.27, -0.03);
          pb(0.05, 0.03, 0.03, 0.01, 0xc9a54e, 0, -0.02, 0.19, STEEL);
        }
        if (!SHADOWS) {
          var sh = new T.Mesh(new T.CircleGeometry(1, 16),
            new T.MeshBasicMaterial({ color: C.shadow, transparent: true,
                                      opacity: 0.16 }));
          sh.rotation.x = -Math.PI / 2;
          sh.scale.set(0.22, 0.17, 1);
          sh.position.set(0, -0.228, 0.01);
          g.add(sh);
        }
        return g;
      };
    })();
    var livingRoofG = new T.Group();   /* open-concept: nothing to hide */
    extG.add(livingRoofG);
    /* ============ THE YARD (docs/house_style_bible.md S7, exterior) =====
       The plinth was a bare green plane with two lollipop trees and one
       sphere of a bush, and half the resting frame was empty grass.
       Plates 1 and 2 line the plinth with planting: beds against the
       foundation, shrubs of three sizes GROUPED rather than dotted, a
       path laid in real units, a picket fence, pots and a chair on the
       lawn. This is that yard.

       Everything here lives in yardG, which an interior camera hides - a
       tree that crosses the near plane eats a third of the garage shot.

       NOTHING out here takes a shadow map. The sun's shadow camera is a
       +/-10 box centred on the house and every one of these props sits
       outside it, so the map clamps at its boundary and lays a hard
       diagonal over whatever samples it - the bug that ate the garage
       bay and the minivan's roof. Contact is drawn by hand with the same
       multiply discs the garage uses; those work at every tier.

       Accents (S4), three and no strays: terracotta (pots, brick),
       oxblood (blooms), mustard (the one ornamental tree plate 2 stands
       on the lawn). Green and stone are materials, not accents; the
       slate roofs stay the dark anchor. */
    var yardG = new T.Group();
    extG.add(yardG);
    (function () {
      var Y2 = DETAIL >= 2, Y3 = DETAIL >= 3;
      var GY = -0.29;                     /* the lawn's top face */
      var LEAF = [0x487436, 0x2f5a2a, 0x5d8443, 0x224b27, 0x71803c,
                  0x74856f];   /* the grey-leaved shrub: a border needs
                                      one value it is not */
      var GOLD = [0xc09b3f, 0x9e8130];
      var BLOOM = [0x8f4038, 0xf2ece1, 0xd1a13c];
      var BARK = 0x6b543c, BARKD = 0x54432f, MULCH = 0x6b5340;
      var EDGE = 0xa87a4c;                /* brick: plate 2 edges in it */
      var PAVER = 0x8b8475, PAVER2 = 0x776f61;
      var JOINT = 0x504b44, PICKET = 0xf1ece2, RAILC = 0xe3dcd0;
      var MATT = { rough: 1.0 }, STONEO = { rough: 0.92 };

      /* ON the shadow map again (lighting pass): the exterior view's box
         is the whole property now, so the planting casts and the lawn
         receives. See the aimShadow block. */
      function yt(m) { return m; }
      function yb(w, h, d, c, x, y, z, o, g) {
        return yt(box(w, h, d, c, x, y, z, g || yardG, o));
      }
      function yr(w, h, d, r, c, x, y, z, o, g) {
        return yt(rbox(w, h, d, r, c, x, y, z, g || yardG, o));
      }
      function yl(a, b, h, c, x, y, z, s, o, g) {
        return yt(cyl(a, b, h, c, x, y, z, g || yardG, s, o));
      }
      function ysph(r, c, x, y, z, sy, g) {
        var m = new T.Mesh(new T.SphereGeometry(r, Y3 ? 12 : 7, Y3 ? 9 : 5),
                           mat(c, MATT));
        m.position.set(x, y, z);
        if (sy) m.scale.y = sy;
        yt(m); (g || yardG).add(m); return m;
      }
      /* contact BELOW tier 3 only: tier 3 casts a real one out here now */
      function ysh(rx, rz, x, z, tone) {
        if (SHADOWS) return null;
        var m = new T.Mesh(new T.CircleGeometry(1, Y2 ? 16 : 8),
          new T.MeshBasicMaterial({ color: tone || 0xa8a4aa, transparent: true,
            blending: T.MultiplyBlending, depthWrite: false }));
        m.rotation.x = -Math.PI / 2;
        m.scale.set(rx, rz, 1);
        m.position.set(x, GY + 0.009, z);
        m.renderOrder = -1;
        yardG.add(m); return m;
      }
      var YUP = new T.Vector3(0, 1, 0);

      /* ---- ground: mulch beds, paving in units, the sidewalk --------- */
      function bed(x0, z0, x1, z1, sides) {
        var w = x1 - x0, d = z1 - z0, cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
        yb(w, 0.10, d, MULCH, cx, GY + 0.03, cz, MATT);
        if (!Y2) return;
        var e = 0.16;                     /* the kerb that makes a bed a bed */
        if (sides.indexOf('S') >= 0) yb(w, e, e, EDGE, cx, GY + 0.05, z1 - e / 2, STONEO);
        if (sides.indexOf('N') >= 0) yb(w, e, e, EDGE, cx, GY + 0.05, z0 + e / 2, STONEO);
        if (sides.indexOf('E') >= 0) yb(e, e, d, EDGE, x1 - e / 2, GY + 0.05, cz, STONEO);
        if (sides.indexOf('W') >= 0) yb(e, e, d, EDGE, x0 + e / 2, GY + 0.05, cz, STONEO);
      }
      function pave(x0, z0, x1, z1, u, border) {
        var w = x1 - x0, d = z1 - z0;
        /* below tier 2 the flags never draw, so the base slab wears the
           FLAG colour there: a Pi should see paving, not a dark hole */
        yb(w, 0.10, d, Y2 ? JOINT : PAVER, (x0 + x1) / 2, GY + 0.01,
           (z0 + z1) / 2, STONEO);
        if (border && Y2) {              /* a soldier course: the edge that
                                            stops paving reading as a plane */
          yb(w + 0.24, 0.13, 0.14, EDGE, (x0 + x1) / 2, GY + 0.045, z1 + 0.07, STONEO);
          yb(0.14, 0.13, d + 0.28, EDGE, x1 + 0.07, GY + 0.045, (z0 + z1) / 2, STONEO);
          yb(w + 0.24, 0.13, 0.14, EDGE, (x0 + x1) / 2, GY + 0.045, z0 - 0.07, STONEO);
        }
        if (!Y2) return;
        var nx = Math.max(1, Math.round(w / u)), nz = Math.max(1, Math.round(d / u));
        var uw = w / nx, ud = d / nz;
        for (var i = 0; i < nx; i++) {
          for (var j = 0; j < nz; j++) {
            yb(uw - 0.07, 0.06, ud - 0.07,
               ((i * 3 + j * 5) % 4 === 0) ? PAVER2 : PAVER,
               x0 + uw * (i + 0.5), GY + 0.05, z0 + ud * (j + 0.5), STONEO);
          }
        }
      }

      /* ---- a tree, built as a tree (S7.4): a flared trunk that forks,
         limbs you can see at tier 3, and a crown of five to seven
         overlapping FLATTENED masses in three greens. Two spheres on a
         stick is the defect the houseplants had, at garden scale.
         [dx, dy, dz, r, tone, squash] measured from the crown base. */
      var CROWN = {
        broad: [[0.00, 1.58, 0.00, 1.24, 0, 0.76],
                [-1.02, 1.06, 0.34, 0.90, 1, 0.82],
                [0.94, 1.20, -0.30, 0.96, 2, 0.78],
                [0.16, 0.92, 0.94, 0.78, 3, 0.84],
                [-0.40, 2.18, -0.32, 0.74, 2, 0.72],
                [0.58, 2.02, 0.50, 0.58, 0, 0.76],
                [-0.82, 0.58, -0.70, 0.54, 3, 0.88],
                [1.24, 0.52, 0.44, 0.42, 1, 0.90]],
        open:  [[-0.66, 1.20, 0.14, 1.02, 0, 0.70],
                [0.84, 1.46, -0.24, 0.92, 2, 0.68],
                [0.10, 2.10, 0.48, 0.66, 1, 0.74],
                [-1.26, 1.74, -0.38, 0.58, 3, 0.78],
                [1.22, 0.80, 0.52, 0.62, 3, 0.82],
                [-0.26, 0.72, -0.92, 0.52, 1, 0.84],
                [0.34, 2.46, -0.10, 0.40, 0, 0.80]],
        gold:  [[0.00, 1.20, 0.00, 0.94, 4, 0.94],
                [-0.60, 0.80, 0.22, 0.70, 5, 0.98],
                [0.58, 0.90, -0.18, 0.66, 4, 0.96],
                [0.04, 1.84, 0.08, 0.58, 5, 0.90],
                [0.30, 0.58, 0.54, 0.50, 4, 1.00]]
      };
      var LIMBS = {
        broad: [[-0.62, 0.72, 0.26, 1.05], [0.66, 0.70, -0.22, 1.00]],
        open:  [[-0.70, 0.62, 0.14, 1.25], [0.72, 0.66, -0.20, 1.15],
                [0.08, 0.86, 0.60, 0.90]],
        gold:  [[-0.44, 0.80, 0.18, 0.80], [0.46, 0.78, -0.14, 0.76]]
      };
      function tree(x, z, s, kind, spin) {
        var g = new T.Group();
        g.position.set(x, GY, z);
        g.rotation.y = spin || 0;
        yardG.add(g);
        var th = (kind === 'gold' ? 1.10 : 1.60) * s;
        yl(0.15 * s, 0.27 * s, th, BARK, 0, th / 2, 0, Y3 ? 10 : 6, MATT, g);
        if (Y2) yl(0.28 * s, 0.44 * s, 0.24 * s, BARKD, 0, 0.11 * s, 0,
                   Y3 ? 10 : 6, MATT, g);
        /* the crown sits INTO the trunk below tier 3: the fine masses
           that close the junction are the ones the lower tiers drop */
        var cb = th - (Y3 ? 0.14 : 0.70) * s;
        if (Y3) (LIMBS[kind] || LIMBS.broad).forEach(function (L) {
          var d = new T.Vector3(L[0], L[1], L[2]).normalize(), ln = L[3] * s;
          var m = yl(0.05 * s, 0.10 * s, ln, BARK, d.x * ln / 2,
                     cb - 0.16 * s + d.y * ln / 2, d.z * ln / 2, 6, MATT, g);
          m.quaternion.setFromUnitVectors(YUP, d);
        });
        var tbl = CROWN[kind] || CROWN.broad;
        var n = Y3 ? tbl.length : (Y2 ? Math.min(4, tbl.length) : 2);
        for (var i = 0; i < n; i++) {
          var b = tbl[i];
          var tc = b[4] < 4 ? LEAF[b[4]] : GOLD[b[4] - 4];
          ysph(b[3] * s, shadeHex(tc, 0.82 + Math.min(0.40, b[1] * 0.17)),
               b[0] * s, cb + b[1] * s, b[2] * s, b[5], g);
        }
        ysh(1.30 * s, 1.10 * s, x + 0.30 * s, z + 0.20 * s);
        return g;
      }

      /* ---- a shrub: three to four overlapping masses, never one
         sphere. [dx, dy, dz, r, squash] */
      var SHRUB = {
        mound: [[0, 0.46, 0, 0.60, 0.80], [-0.34, 0.32, 0.16, 0.46, 0.84],
                [0.32, 0.30, -0.14, 0.44, 0.86], [0.06, 0.28, 0.36, 0.38, 0.88]],
        ball:  [[0, 0.60, 0, 0.54, 0.96], [-0.22, 0.42, 0.12, 0.38, 0.94],
                [0.24, 0.44, -0.10, 0.36, 0.94]],
        column:[[0, 0.62, 0, 0.34, 1.75], [0, 1.24, 0, 0.23, 1.55],
                [-0.15, 0.38, 0.11, 0.27, 1.15], [0.13, 0.34, -0.10, 0.25, 1.15]],
        low:   [[0, 0.26, 0, 0.44, 0.66], [-0.30, 0.20, 0.10, 0.32, 0.70],
                [0.28, 0.22, -0.12, 0.30, 0.72], [0.02, 0.20, 0.30, 0.26, 0.72]]
      };
      function shrub(x, z, s, kind, tone, bloom) {
        var g = new T.Group();
        g.position.set(x, GY, z);
        g.rotation.y = (x * 1.7 + z * 0.9) % 3.14;
        yardG.add(g);
        var tbl = SHRUB[kind] || SHRUB.mound;
        var n = Y3 ? tbl.length : (Y2 ? Math.min(3, tbl.length) : 1);
        /* ONE tone per shrub, its masses shaded off it - a shrub whose
           lobes are four different greens is confetti, not a plant */
        var base = LEAF[tone % 6], KS = [1, 1.10, 0.80, 1.04];
        for (var i = 0; i < n; i++) {
          var b = tbl[i];
          ysph(b[3] * s, i ? shadeHex(base, KS[i % 4]) : base,
               b[0] * s, b[1] * s, b[2] * s, b[4], g);
        }
        if (bloom && Y2) {
          var bc = BLOOM[(bloom - 1) % 3], top = tbl[0];
          for (var k = 0; k < (Y3 ? 9 : 4); k++) {
            var a = k * 1.97, rr = (0.30 + (k % 3) * 0.09) * s;
            ysph(0.115 * s, bc, Math.cos(a) * rr,
                 (top[1] * top[4] * 0.94 + 0.10 + (k % 2) * 0.08) * s,
                 Math.sin(a) * rr, 0.85, g);
          }
        }
        ysh(0.80 * s, 0.72 * s, x + 0.07, z + 0.05);
        return g;
      }
      /* ---- ornamental grass: blades, not a blob */
      function tuft(x, z, s, tone) {
        var g = new T.Group();
        g.position.set(x, GY, z);
        yardG.add(g);
        var n = Y3 ? 11 : (Y2 ? 6 : 3);
        for (var i = 0; i < n; i++) {
          var a = i * 1.97, lean = 0.20 + (i % 3) * 0.11;
          var h = (0.62 + (i % 4) * 0.13) * s;
          var m = yb(0.055 * s, h, 0.035 * s,
                     shadeHex(LEAF[tone % 6], 1 + (i % 3) * 0.10),
                     Math.cos(a) * 0.13 * s, h / 2 * 0.92,
                     Math.sin(a) * 0.13 * s, MATT, g);
          m.rotation.z = -Math.cos(a) * lean;
          m.rotation.x = Math.sin(a) * lean;
        }
        ysh(0.44 * s, 0.40 * s, x, z);
        return g;
      }
      /* ---- a planted group: one call, one clump of three habits ------ */
      function planting(list) {
        (Y2 ? list : list.filter(function (_, i) { return i % 2 === 0; }))
          .forEach(function (p) {
            if (p[3] === 'tuft') tuft(p[0], p[1], p[2], p[4]);
            else shrub(p[0], p[1], p[2], p[3], p[4], p[5]);
          });
      }

      /* ---- a picket fence (plate 2) ---------------------------------- */
      function fence(axis, a0, a1, fx) {
        var PH = 0.94, L = a1 - a0;
        function at(a, w, h, t, c, y, o) {   /* w along the run, t across */
          return axis === 'x' ? yb(w, h, t, c, a, y, fx, o)
                              : yb(t, h, w, c, fx, y, a, o);
        }
        var np = Math.max(2, Math.round(L / 2.30));
        for (var i = 0; i <= np; i++) {
          var a = a0 + L * i / np;
          at(a, 0.15, PH + 0.16, 0.15, PICKET, GY + (PH + 0.16) / 2, STONEO);
          if (Y3) at(a, 0.20, 0.09, 0.20, PICKET, GY + PH + 0.20, STONEO);
        }
        [0.30, 0.70].forEach(function (f) {
          at(a0 + L / 2, L, 0.09, 0.07, RAILC, GY + PH * f, STONEO);
        });
        if (!Y2) return;
        var nk = Math.floor(L / 0.34);
        for (var k = 0; k < nk; k++) {
          var a2 = a0 + 0.20 + (L - 0.40) * k / (nk - 1);
          at(a2, 0.13, PH, 0.045, PICKET, GY + PH / 2, STONEO);
          if (Y3) at(a2, 0.13, 0.055, 0.05, PICKET, GY + PH + 0.02, STONEO);
        }
      }

      /* ---- terrace furniture: plate 2 stands a chair on the lawn ----- */
      function gChair(x, z, rot, body, cush) {
        var g = new T.Group();
        g.position.set(x, GY, z); g.rotation.y = rot;
        yardG.add(g);
        var WD = { rough: 0.66 }, dk = shadeHex(body, 0.80),
            lt = shadeHex(body, 1.14);
        [[-0.26, -0.24], [0.26, -0.24], [-0.26, 0.24], [0.26, 0.24]]
          .forEach(function (lg) {
            yb(0.09, 0.44, 0.09, dk, lg[0], 0.22, lg[1], WD, g);
          });
        yb(0.62, 0.08, 0.58, body, 0, 0.48, 0, WD, g);      /* the seat deck */
        if (Y3) [-0.19, 0.00, 0.19].forEach(function (dz) {
          yb(0.60, 0.035, 0.13, lt, 0, 0.535, dz, WD, g);
        });
        yr(0.56, 0.15, 0.52, 0.06, cush, 0, 0.585, 0.01, { rough: 0.98 }, g);
        [-0.26, 0.26].forEach(function (dx) {               /* raked back */
          var u = yb(0.09, 0.80, 0.09, dk, dx, 0.86, -0.29, WD, g);
          u.rotation.x = -0.13;
        });
        [0.76, 1.00, 1.22].forEach(function (yy, i) {
          if (!Y2 && i) return;
          var b2 = yb(0.54, 0.15, 0.05, body, 0, yy, -0.29 + (yy - 0.86) * 0.13,
                      WD, g);
          b2.rotation.x = -0.13;
        });
        if (Y2) [-0.32, 0.32].forEach(function (dx) {       /* arms */
          yb(0.08, 0.07, 0.54, body, dx, 0.74, -0.03, WD, g);
          yb(0.08, 0.28, 0.08, dk, dx, 0.60, 0.22, WD, g);
        });
        ysh(0.48, 0.48, x, z);
        return g;
      }
      function gTable(x, z, r) {
        yl(r, r, 0.09, C.wood2, x, GY + 0.60, z, Y3 ? 20 : 10, { rough: 0.62 });
        if (Y3) yl(r - 0.05, r - 0.05, 0.03, shadeHex(C.wood2, 1.16),
                   x, GY + 0.655, z, 20, { rough: 0.62 });
        yl(0.075, 0.095, 0.56, C.graphite, x, GY + 0.28, z, 8, { rough: 0.55 });
        yl(0.30, 0.34, 0.06, C.graphite, x, GY + 0.03, z, Y3 ? 14 : 8,
           { rough: 0.55 });
        ysh(0.46, 0.44, x, z);
      }
      /* a planter box: the long green mass a terrace needs at its edge */
      function planter(x, z, len, rot) {
        var g = new T.Group();
        g.position.set(x, GY, z); g.rotation.y = rot || 0;
        yardG.add(g);
        yr(len, 0.44, 0.52, 0.03, C.wood2, 0, 0.22, 0, { rough: 0.66 }, g);
        if (Y2) {
          yr(len + 0.06, 0.06, 0.58, 0.02, shadeHex(C.wood2, 1.2), 0, 0.47, 0,
             { rough: 0.66 }, g);
          yb(len - 0.10, 0.06, 0.42, MULCH, 0, 0.45, 0, MATT, g);
        }
        var n = Math.max(2, Math.round(len / 0.62));
        for (var i = 0; i < n; i++) {
          var px = -len / 2 + len * (i + 0.5) / n;
          ysph((0.20 + (i % 3) * 0.05), shadeHex(LEAF[(i + 2) % 6], 1 + (i % 2) * 0.12),
               px, 0.56 + (i % 2) * 0.07, (i % 2 ? 0.07 : -0.06), 0.88, g);
          if (Y3) ysph(0.13, shadeHex(LEAF[(i + 4) % 6], 0.9), px + 0.14,
                       0.52, 0.12, 0.9, g);
        }
        ysh(len * 0.52, 0.34, x, z);
        return g;
      }
      /* a pot: the kitchen's plant, dropped on the lawn without its
         shadow (blobShadow is quiet at tier 3; ysh is not) */
      function pot(x, z, s, potC, kind) {
        var g = new T.Group();
        yardG.add(g);
        kPlant(g, x, GY, z, s, potC, { rough: 0.85 }, kind, false);
        g.traverse(yt);
        ysh(0.40 * s, 0.38 * s, x + 0.04, z + 0.03);
        return g;
      }

      /* ================= THE PLAN ==================================== */
      /* the sidewalk: the line every front yard has, and the thing that
         stops the lawn bleeding into the kerb */
      yb(38, 0.10, 1.20, 0xa9a294, -2.0, GY + 0.015, 16.95, STONEO);
      if (Y2) {
        for (var sw = -20; sw < 17; sw += 1.55) {
          yb(0.05, 0.014, 1.20, 0x7d776c, sw, GY + 0.072, 16.95, STONEO);
        }
      }
      /* the front path, relaid in flags (it was one poured ribbon) */
      pave(-9.62, 12.16, -7.02, 13.04, 0.66);
      pave(-9.66, 13.04, -8.74, 16.35, 0.62);
      /* the terrace off the great room's open east side */
      pave(6.86, 4.20, 10.30, 9.80, 0.80, true);

      /* foundation beds: they wrap the corner the camera looks at */
      bed(-8.70, 14.24, 8.30, 16.00, 'SEW');
      bed(6.84, -6.10, 8.30, 4.14, 'NES');
      bed(6.84, 9.86, 8.30, 14.12, 'NE');
      /* the front bed, three groups with nothing further than 0.6 from a
         neighbour (S1) and a skyline that rises and falls */
      planting([
        [-8.10, 15.34, 0.92, 'mound', 5, 0],  [-7.46, 15.62, 0.58, 'low', 2, 2],
        [-6.94, 15.26, 0.74, 'tuft', 5, 0],
        [-6.30, 15.42, 1.42, 'column', 1, 0], [-5.54, 15.28, 0.98, 'mound', 5, 0],
        [-4.92, 15.60, 0.56, 'low', 2, 1],    [-4.32, 15.30, 0.74, 'tuft', 4, 0],
        [-3.50, 15.46, 1.04, 'mound', 3, 0],  [-2.84, 15.26, 0.62, 'ball', 1, 0],
        [-2.22, 15.62, 0.54, 'low', 0, 3],    [-1.56, 15.34, 0.96, 'mound', 5, 0],
        [-0.92, 15.60, 0.70, 'tuft', 1, 0],   [-0.16, 15.28, 1.18, 'column', 0, 0],
        [0.56, 15.58, 0.58, 'low', 3, 1],     [1.22, 15.30, 0.98, 'mound', 1, 0],
        [1.90, 15.60, 0.64, 'ball', 4, 0],    [2.60, 15.28, 0.90, 'mound', 2, 3],
        [3.26, 15.58, 0.68, 'tuft', 3, 0],    [3.96, 15.30, 1.06, 'mound', 5, 0],
        [4.64, 15.58, 0.56, 'low', 2, 1],     [5.30, 15.28, 1.46, 'column', 1, 0],
        [6.04, 15.56, 0.88, 'mound', 3, 0],   [6.74, 15.28, 0.62, 'ball', 0, 3],
        [7.46, 15.56, 0.96, 'mound', 4, 0],   [7.98, 15.26, 0.72, 'tuft', 1, 0],
        [-5.90, 14.66, 0.50, 'low', 3, 0],    [-3.10, 14.66, 0.52, 'low', 0, 0],
        [-0.50, 14.64, 0.48, 'low', 2, 0],    [2.10, 14.66, 0.52, 'low', 1, 0],
        [4.90, 14.64, 0.50, 'low', 3, 0],     [7.10, 14.66, 0.48, 'low', 0, 0]
      ]);
      /* the east bed, up the side the camera sees most */
      planting([
        [7.52, 13.34, 0.86, 'mound', 0, 0],   [7.48, 12.62, 0.58, 'low', 2, 1],
        [7.56, 11.94, 1.40, 'column', 1, 0],  [7.46, 11.24, 0.76, 'ball', 3, 0],
        [7.54, 10.56, 0.62, 'tuft', 4, 0],    [7.50, 10.02, 0.96, 'mound', 2, 0],
        [7.52, 3.68, 0.98, 'mound', 1, 0],    [7.46, 2.92, 0.62, 'low', 4, 3],
        [7.56, 2.20, 1.08, 'column', 2, 0],   [7.48, 1.50, 0.82, 'ball', 1, 0],
        [7.52, 0.80, 0.70, 'tuft', 3, 0],     [7.50, 0.08, 0.92, 'mound', 5, 0],
        [7.54, -0.64, 0.78, 'low', 2, 1],     [7.46, -1.36, 1.00, 'mound', 5, 0],
        [7.52, -2.10, 0.72, 'ball', 0, 0],    [7.50, -2.82, 0.88, 'mound', 3, 0],
        [7.54, -3.54, 0.66, 'tuft', 1, 0],    [7.46, -4.26, 1.04, 'column', 0, 0],
        [7.52, -5.00, 0.84, 'mound', 2, 3],   [7.50, -5.70, 0.70, 'low', 1, 0]
      ]);
      /* the lawn groups: three specimens and their skirts, so the grass
         reads as a garden and not as a mat */
      planting([
        [11.70, 14.30, 1.06, 'mound', 0, 0],  [12.44, 14.90, 0.62, 'low', 2, 1],
        [12.20, 13.60, 0.80, 'ball', 1, 0],   [11.20, 13.55, 0.66, 'tuft', 3, 0],
        [12.50, 6.10, 1.16, 'mound', 5, 0],   [12.10, 6.86, 0.60, 'low', 4, 3],
        [12.30, 5.32, 0.82, 'ball', 2, 0],    [11.62, 6.02, 0.64, 'tuft', 0, 0],
        [12.05, 9.90, 0.92, 'mound', 3, 0],   [12.60, 10.55, 0.58, 'low', 0, 1],
        [11.55, 10.45, 0.70, 'ball', 4, 0],
        [-11.40, 13.60, 1.00, 'mound', 2, 0], [-11.95, 14.20, 0.62, 'low', 0, 1],
        [-10.85, 14.25, 0.74, 'ball', 3, 0],  [-12.15, 13.10, 0.66, 'tuft', 1, 0]
      ]);

      /* the neighbour's hedge, beyond the fence: the far corner of the
         frame is a boundary, not a void */
      planting([
        [15.20, 15.30, 1.10, 'mound', 1, 0], [15.60, 14.10, 1.20, 'mound', 3, 0],
        [15.30, 12.90, 1.06, 'mound', 0, 0], [15.70, 11.70, 1.16, 'mound', 1, 0],
        [15.40, 10.50, 1.02, 'mound', 3, 0], [15.80, 9.30, 1.14, 'mound', 0, 0],
        [15.50, 8.10, 1.08, 'mound', 1, 0],  [15.85, 6.90, 1.18, 'mound', 3, 0]
      ]);
      /* the drive's east edge and the mailbox foot: the left of the
         frame was a driveway and a mown void */
      bed(-12.98, 10.90, -11.72, 16.30, 'SEN');
      planting([
        [-12.40, 15.72, 0.94, 'mound', 0, 0], [-12.34, 15.02, 0.56, 'low', 2, 1],
        [-12.42, 14.34, 1.06, 'column', 1, 0], [-12.36, 13.64, 0.74, 'ball', 3, 0],
        [-12.40, 12.96, 0.62, 'tuft', 4, 0],  [-12.34, 12.26, 0.90, 'mound', 2, 0],
        [-12.42, 11.56, 0.58, 'low', 1, 3],   [-12.40, 16.02, 0.60, 'mound', 3, 1],
        [-12.86, 15.34, 0.50, 'low', 0, 2]
      ]);
      pot(-10.35, 12.85, 0.90, C.terracotta, 'spray');
      pot(-10.30, 13.78, 0.76, C.cream, 'mound');

      /* the fence: an L round the side garden, clear of the bus (which
         stands at x -8.3..-2.7, z 18.8..20.8) and of the path */
      fence('x', 2.20, 13.20, 16.30);
      fence('z', 3.00, 16.30, 13.20);
      ysh(5.50, 0.24, 7.75, 16.44);       /* nothing floats, S4 */
      ysh(0.24, 6.70, 13.34, 9.62);
      /* a birdbath on the side lawn: the vertical the grass wanted */
      (function () {
        var bx = 10.90, bz = 5.60;   /* the lawn's vertical */
        yl(0.13, 0.20, 0.86, EDGE, bx, GY + 0.43, bz, Y3 ? 14 : 8, STONEO);
        yl(0.30, 0.30, 0.06, EDGE, bx, GY + 0.03, bz, Y3 ? 14 : 8, STONEO);
        yl(0.42, 0.30, 0.16, EDGE, bx, GY + 0.92, bz, Y3 ? 16 : 8, STONEO);
        if (Y2) yl(0.35, 0.35, 0.03, 0x8fb6c4, bx, GY + 0.995, bz,
                   Y3 ? 16 : 8, GLOSS);
        ysh(0.34, 0.32, bx + 0.05, bz + 0.04);
      })();

      /* the terrace: a chair that faces another chair (S8) */
      gTable(8.52, 6.70, 0.56);
      gChair(8.50, 5.58, Math.PI, C.wood2, C.linen);
      gChair(8.54, 7.82, 0, C.wood2, C.linen);
      gChair(7.36, 6.66, -Math.PI / 2, C.wood2, C.linen);
      planter(9.86, 8.30, 2.30, Math.PI / 2);
      /* a bench along the plinth, and the two things every garden owns */
      (function () {
        var bx = 7.42, bz = 8.60, WD = { rough: 0.66 };
        var g = new T.Group();
        g.position.set(bx, GY, bz); g.rotation.y = -Math.PI / 2;
        yardG.add(g);
        [-0.66, 0.66].forEach(function (dx) {
          yb(0.10, 0.42, 0.44, shadeHex(C.wood2, 0.82), dx, 0.21, 0, WD, g);
        });
        yb(1.56, 0.09, 0.50, C.wood2, 0, 0.465, 0, WD, g);
        if (Y3) [-0.16, 0.16].forEach(function (dz) {
          yb(1.52, 0.035, 0.15, shadeHex(C.wood2, 1.14), 0, 0.52, dz, WD, g);
        });
        if (Y2) {
          [-0.66, 0.66].forEach(function (dx) {
            var u = yb(0.09, 0.62, 0.09, shadeHex(C.wood2, 0.82), dx, 0.80,
                       -0.20, WD, g);
            u.rotation.x = -0.12;
          });
          [0.78, 1.00].forEach(function (yy) {
            var b2 = yb(1.44, 0.14, 0.05, C.wood2, 0, yy, -0.22, WD, g);
            b2.rotation.x = -0.12;
          });
          yr(0.42, 0.14, 0.36, 0.06, C.terracotta, -0.42, 0.58, 0.03,
             { rough: 0.98 }, g);
        }
        ysh(0.90, 0.42, bx, bz);
      })();
      if (Y2) {                          /* a watering can by the pots */
        yl(0.15, 0.17, 0.30, C.steel, 9.34, GY + 0.15, 4.30, 10, STEEL);
        yb(0.05, 0.05, 0.30, C.steel, 9.34, GY + 0.26, 4.12, STEEL)
          .rotation.x = 0.5;
        if (Y3) {
          var sp = yl(0.035, 0.06, 0.42, C.steel, 9.44, GY + 0.24, 4.52, 8,
                      STEEL);
          sp.rotation.x = -0.9; sp.rotation.z = -0.3;
        }
        ysh(0.20, 0.20, 9.34, 4.32);
      }
      pot(7.22, 4.74, 0.92, C.terracotta, 'spray');
      pot(9.94, 4.72, 0.80, C.terracotta, 'fiddle');
      pot(9.92, 9.42, 0.86, C.cream, 'mound');

      /* four trees, three silhouettes (S7.4). The old pair were two
         spheres on a stick, and one of them stood at x 17.5 - entirely
         outside the frame. */
      tree(-19.60, 13.90, 1.45, 'broad', 0.5);
      tree(13.60, 4.60, 1.12, 'open', 2.2);
      tree(12.20, 12.70, 1.05, 'gold', 1.1);
      /* the back line: four crowns that break the skyline, so the roofs
         sit against something instead of floating in a quarter-frame of
         empty sky */
      tree(-3.50, -12.20, 1.85, 'broad', 1.9);
      tree(-19.80, -5.00, 1.60, 'broad', 2.7);
      tree(8.60, -12.60, 1.75, 'open', 0.8);
      tree(-11.60, -13.20, 1.50, 'broad', 0.3);
    })();
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
      var night = isNight();       /* one clock for the whole scene */
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
      var night = isNight();
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
    /* ---- NIGHT (plate 1: warm interiors against a cool night) ----------
       The exterior builder left the hooks and this is the pass that lights
       them: every pane carries userData.glazing, the coach lamp carries
       userData.lamp, and the sky dome already repaints itself at 07:00 and
       19:00 because skyDomeTex bakes `night` into its cache payload.

       It is a STATE CHANGE, not an animation. applyState is the only caller
       and it already runs on the 60s poll, so the house crosses into
       evening on the same tick its sky does, and NOTHING runs between
       ticks - no RAF, no flicker, no timer.

       What dusk does: the sun drops to a cold sliver and the sky fill goes
       deep blue, so the outside reads as night; every room lamp roughly
       doubles, so the inside stays legible and now reads WARM against that
       cool surround; the coach lamp by the garage door comes on; and the
       glazing turns emissive, which IS the plate - a dark house with lit
       windows. The interiors are lit by their own lamps after dark, which
       is both honest and the reason the rooms do not go dark when the panel
       is looked at in the evening. */
    var glazing = [], lampGlass = [];
    scene.traverse(function (o) {
      if (!o.isMesh || !o.userData) return;
      if (o.userData.lamp) lampGlass.push(o);
      else if (o.userData.glazing) glazing.push(o);
    });
    /* The cheapest tier has no lamps at all - the Pi law gates every point
       light at DETAIL >= 2 - so `low` cannot be lit from inside after dark.
       Dimming it as hard as the other two left a wall panel unreadable all
       evening, which is a regression, not a look. Low gets a gentler curve
       and a WARM ambient standing in for the lamps it cannot afford: dusk
       rather than midnight, which is the honest degradation the checklist
       asks for ("degraded but not broken"). */
    var NIGHT_F = DETAIL >= 2
      ? { sun: 0.22, hemi: 0.46, amb: 0.70, ambC: 0xdfe6f0, sky: 0x2c3d6b }
      : { sun: 0.34, hemi: 0.62, amb: 1.90, ambC: 0xffd3a4, sky: 0x41537f };
    var nightNow = null;
    function setNight(n) {
      if (n === nightNow) return;
      nightNow = n;
      hemi.intensity = n ? HEMI_I * NIGHT_F.hemi : HEMI_I;
      hemi.color.setHex(n ? NIGHT_F.sky : SKY_C);
      hemi.groundColor.setHex(n ? 0x1b1c22 : GND_C);
      amb.intensity = n ? AMB_I * NIGHT_F.amb : AMB_I;
      amb.color.setHex(n ? NIGHT_F.ambC : (PBR ? 0xdfe6f0 : 0xe4eaf2));
      sun.intensity = n ? SUN_I * NIGHT_F.sun : SUN_I;
      sun.color.setHex(n ? 0x9db4dd : SUN_C);   /* a moon, not a sun */
      poolLamps.forEach(function (l, i) {
        /* the coach lamp is the last one and is DARK by day */
        l.intensity = n ? (i === poolLamps.length - 1 ? 0.34 : l.userData.dayI * 2.1)
                        : l.userData.dayI;
      });
      glazing.forEach(function (m) {
        if (!m.material || !m.material.emissive) return;
        m.material.emissive.setHex(n ? 0xffb35a : 0x000000);
        m.material.emissiveIntensity = n ? 0.92 : 0;
        m.material.needsUpdate = true;
      });
      lampGlass.forEach(function (m) {
        if (!m.material || !m.material.emissive) return;
        m.material.emissive.setHex(n ? 0xffd07a : 0x000000);
        m.material.emissiveIntensity = n ? 1.0 : 0;
        m.material.needsUpdate = true;
      });
      shadowDirty();
    }
    setNight(isNight());

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
      aimShadow: aimShadow, shadowDirty: shadowDirty,
      setNight: setNight, isNight: isNight,
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
      mudBagsG: mudBagsG, makeBag: makeBag
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
          /* the live-zone glow. 0x2a1e08 was authored against ACES, which
             compressed it; under a linear curve the same value added a
             sixth of full red straight onto the surface and turned a lit
             door mustard. Halved and cooled - it still says "this one is
             awake" without repainting the prop. */
          o.material.emissive.setHex(lit ? 0x120c03 : 0x000000);
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

    /* dusk and dawn ride the same tick the sky dome does */
    webgl.setNight(webgl.isNight());
    /* the only path that can change what the depth pass would draw */
    webgl.shadowDirty();

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
          /* the garage boards sit at 0.035 and the driveway apron at
             -0.21: a car parked at y 0 sinks into one and floats over
             the other, and its contact shadow goes with it */
          grp.position.set(inside === 0 ? -16.7 : -14.1, 0.038, 5.6);
          var plate = new webgl.T.Mesh(new webgl.T.PlaneGeometry(1.5, 0.75),
            new webgl.T.MeshBasicMaterial({ transparent: true,
                                            map: webgl.carTex(c) }));
          plate.position.set(grp.position.x, 3.3, 2.4);   /* garage back wall */
          plate.userData.zone = 'garage';
          webgl.carsG.add(plate);
          inside++;
        } else {
          grp.position.set(-15.4, -0.206, 12.6 + outside * 4.6);
          outside++;
        }
        webgl.carsG.add(grp);
      });
    }
    if (webgl.busG) webgl.busG.visible = !!((s.curb || {}).bus);
  }

  /* backpacks on the mudroom bench: one per child, rebuilt on count change */
  var bagCount = null;
  /* the mudroom's own accents (sage, brass, oxblood, terracotta) plus
     one teal, the kitchen's, because the two rooms share a sightline */
  var BAG_COLORS = [0x8f4038, 0x3fbdb2, 0xb5713c, 0x7d968a];
  /* two on the cushion (top 0.75, bag half-height 0.23), two on the
     floor (0.03) either side of the bench */
  var BAG_SPOTS = [[-12.00, 0.98, 3.14], [-10.86, 0.98, 3.14],
                   [-12.32, 0.26, 3.66], [-9.30, 0.26, 3.62]];
  function syncMudroom(s) {
    if (!webgl) return;
    var n = Math.min(4, ((s.mudroom || {}).bags || 0));
    if (n === bagCount) return;
    bagCount = n;
    while (webgl.mudBagsG.children.length)
      webgl.mudBagsG.remove(webgl.mudBagsG.children[0]);
    for (var i = 0; i < n; i++) {
      var bag;
      if (webgl.makeBag) {
        bag = webgl.makeBag(BAG_COLORS[i % 4]);
      } else {                       /* the 2D-adjacent tiers keep a block */
        bag = new webgl.T.Group();
        var body = new webgl.T.Mesh(new webgl.T.BoxGeometry(0.34, 0.46, 0.26),
          new webgl.T.MeshLambertMaterial({ color: BAG_COLORS[i % 4] }));
        var flap = new webgl.T.Mesh(new webgl.T.BoxGeometry(0.36, 0.18, 0.28),
          new webgl.T.MeshLambertMaterial({ color: 0x3a3330 }));
        flap.position.y = 0.17;
        bag.add(body); bag.add(flap);
      }
      bag.position.set(BAG_SPOTS[i][0], BAG_SPOTS[i][1], BAG_SPOTS[i][2]);
      bag.rotation.y = (i % 2 ? 0.22 : -0.18);
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
    webgl.aimShadow(name);        /* the sun's shadow box follows the camera */
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
    webgl.aimShadow('exterior');  /* the whole property, for the one view
                                     that can see the whole property */
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
  /* the GARDEN is scenery, not a door. The old rule let any exterior mesh
     standing above y 0.2 walk you into the kitchen, which two blob trees
     already broke and ~700 yard meshes would break constantly: a tap meant
     for a shrub opened a room. Anything under yardG is now inert, so the
     spec's "sky and flat yard stay a view" holds for the planting too. */
  function inYard(obj) {
    var o = obj;
    while (o) { if (o === webgl.yardG) return true; o = o.parent; }
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
      if (inYard(hit)) return;                 /* scenery: look, do not enter */
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
