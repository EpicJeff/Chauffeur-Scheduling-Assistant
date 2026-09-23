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
 * music actually plays; outdoor precipitation while visible). Because frames are rare, each one can be expensive:
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
  var BACK = document.getElementById('house-back');
  var HINT = document.getElementById('house-hints');
  /* ORBIT (spec section 4): the two chevrons, the exterior's own hand path */
  var ORBIT_BTNS = document.querySelectorAll('.house-orbit');
  var FALLBACK = document.getElementById('fallback');
  var FALLROWS = document.getElementById('fallback-rows');
  if (!ROOT) return;

  var BASE = (typeof window.chfBase !== 'undefined' ? window.chfBase : '');
  var VISIT_KEY = 'chf_kitchen_last_visit';
  var QUALITY_KEY = 'chf_kitchen_quality2';  // v2: the v1 benchmark measured shader-compile and demoted everyone
  var POLL_MS = 60000;
  var WEATHER_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)');
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

  /* ---- SCENERY: one knob for the whole hierarchy -----------------------
   * Five set-builder passes took the room from "a few props" to well over a
   * thousand meshes, and the ten things a person can actually TOUCH — door,
   * radio, pet, board, calendar, counter, fridge, window, garage, curb —
   * stopped standing out among them. The fix is art direction, not
   * decoration: scenery quietly loses saturation and contrast so the
   * touchable props read as the subject. Nothing moves, hides, resizes or
   * outlines; colour and material response only.
   *
   * Deliberately NOT a glow. Zones already glow when they genuinely need a
   * person (applyState's emissive loop), and ten permanent glows would
   * destroy that signal. Quiet room = success.
   *
   *   0    nothing recedes — every pixel exactly as authored
   *   0.45 the default. Measured, not guessed: below k = 0.42 the room's
   *        DECORATIVE teal (jars, stool cushions, the toaster) renders at
   *        a higher chroma than the fridge's — the set dressing literally
   *        out-saturates the zone it sits next to, which is the complaint
   *        this knob exists to answer. 0.45 puts the zone in front with a
   *        margin, and costs the kitchen 3.9% of its mean brightness, so
   *        the room still reads warm and lit rather than foggy.
   *   1    maximum recession — scenery goes nearly monochrome
   *
   * Three ways in, because a knob you cannot turn is a constant:
   *   - this constant
   *   - ?scenery=0.5 on the URL (parsed like ?quality=)
   *   - window.chfHouseScenery(k) at runtime — read-only in the same sense
   *     as its chfHouse* siblings: it changes appearance, never state. This
   *     is the hook a reveal-on-demand control would call, with a bigger k.
   *     Called with no argument it changes nothing and just reports where
   *     the knob stands. Out-of-range and non-numeric values are ignored
   *     or clamped, never trusted.
   *
   * Applied INSIDE A ROOM only. At the exterior the whole house is the
   * subject, so the effective value there is 0. Re-applied on room change
   * — a state change, never a frame loop.
   */
  var SCENERY = 0.45;                  // 0 .. 1
  try {
    var _sq = new URLSearchParams(window.location.search).get('scenery');
    if (_sq !== null && _sq !== '' && isFinite(parseFloat(_sq)))
      SCENERY = Math.max(0, Math.min(1, parseFloat(_sq)));
  } catch (e) { /* ancient parser: the constant decides */ }
  /* `low` takes two thirds. Not because it is dim — measured, the knob
     costs the low tier under 1% of its mean brightness at any value —
     but because at low mat() drops every texture, so the floor, the
     counters and the walls are flat colours that recede along with the
     props instead of holding still under them. The Pi also draws far
     less clutter to suppress in the first place (the DETAIL >= 2 loops
     never run), so it needs less of the effect to get the same read. */
  var SCENERY_TIER = DETAIL >= 2 ? 1 : 0.66;

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
    /* admin: Config is the car editor, and it is a DESKTOP destination.
       A wall panel must never land there — the fleet card already carries
       the answer, so on a panel this zone simply has no way through. */
    garage:   { label: 'Garage',        url: 'config', admin: true,
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
  var studyFurniture = {};
  var STUDY_ZONE_META = {
    study_board:     ['Connections board','mind'],
    study_desk:      ['Plans in hand','mind'],
    study_tray:      ['Intake tray','intake'],
    study_stickies:  ['Findings','dashboard'],
    study_calendar:  ['Coverage calendar','dashboard'],
    study_window:    ['Family baseline','mind'],
    study_contracts: ['Agreements','dashboard'],
    study_binders:   ['Program binders','programs'],
    study_gauges:    ['Argyle gauges','mind'],
    study_monitor:   ['Household monitor','mind'],
    study_map:       ['Travel map','trips']
  };
  function studyZoneCount(key) {
    return webgl && webgl.studyWorld ? webgl.studyWorld.count(studyFurniture,key) : 0;
  }
  function studyZoneHeadline(key) {
    var n = studyZoneCount(key), label = STUDY_ZONE_META[key][0];
    if (!n) return label + ' is quiet.';
    if (key === 'study_map') return n + ' upcoming trip' + (n === 1 ? '' : 's') + '.';
    if (key === 'study_binders') return n + ' program' + (n === 1 ? '' : 's') + ' needs a look.';
    if (key === 'study_monitor') return n + ' household cluster' + (n === 1 ? '' : 's') + '.';
    if (key === 'study_window') return n + ' baseline change' + (n === 1 ? '' : 's') + '.';
    if (key === 'study_calendar') return n + ' uncovered item' + (n === 1 ? '' : 's') + '.';
    return n + ' item' + (n === 1 ? '' : 's') + ' needs attention.';
  }
  Object.keys(STUDY_ZONE_META).forEach(function (key) {
    ZONES[key] = {label:STUDY_ZONE_META[key][0],url:STUDY_ZONE_META[key][1],
      num:function(){return studyZoneCount(key);},
      headline:function(){return studyZoneHeadline(key);}};
  });
  var ZONE_ORDER = ['door', 'window', 'calendar', 'counter', 'fridge', 'board', 'radio', 'pet', 'garage', 'curb'];

  var PANEL = /[?&]panel=true/.test(window.location.search);
  function go(slug) { window.location.href = BASE + slug + window.location.search; }
  /* a zone's way through, or '' when this device must not go there */
  function zoneUrl(key) {
    var z = ZONES[key] || {};
    return (z.admin && PANEL) ? '' : (z.url || '');
  }

  /* ---- fallback: the DESIGNED weak-hardware experience ----------------- */
  /* textContent only — captions and dish names are family-typed strings and
   * this page renders on the most shared screen in the house. */
  function drawFallback(state) {
    if (window.ChauffeurHome && window.ChauffeurHome.fallback()) return;
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
      var href = zoneUrl(key);
      if (href) row.href = BASE + href + window.location.search;
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
  // Both the interactive home and scenery use the same parametric geometry.
  // Exterior builds accept explicit input, share the renderer, and return only
  // an owned static kit; they never attach UI or start household behavior.
  function ownExteriorTextures(kit, textures) {
    var release = kit.dispose;
    kit.dispose = function () { release(); textures.forEach(function(t){t.dispose();}); };
    return kit;
  }
  function buildDetailedExterior(spec, renderer, footprintOnly) {
    return buildRoom({ exteriorOnly: true, spec: spec, renderer: renderer, footprintOnly: footprintOnly });
  }
  function buildRoom(options) {
    options = options || {};
    var exteriorOnly = !!options.exteriorOnly;
    var facadeInput = options.spec ? {spec: options.spec} : window.HOUSE_FACADE;
    var T = window.THREE;
    if (!T || DETAIL < 1) return null;
    if (!exteriorOnly) {
      var canvasProbe = document.createElement('canvas');
      var gl = canvasProbe.getContext('webgl2') || canvasProbe.getContext('webgl');
      if (!gl) return null;
    }

    var SHADOWS = DETAIL >= 3;            // real soft shadow maps: high only
    var PBR = DETAIL >= 3;                // standard materials vs lambert

    var scene = new T.Scene();
    scene.background = new T.Color(0xbdb3c7);          // the soft lilac of the reference
    var neighborhoodEnabled = !exteriorOnly && !!window.ChauffeurNeighborhood && new URLSearchParams(location.search).get('editor') !== '1';
    var cam = new T.PerspectiveCamera(24, 1, 0.1, neighborhoodEnabled ? 1000 : 200);
    var neighborhood = null;
    /* ---- THE MIRROR (spec 2026-09-17 section 3.4) ----------------------
       A mirrored plan is ONE reflection of the finished house, applied to
       a root group at the very end of the build (see `houseRoot`, after
       bakeAO). NOTHING between here and there is authored twice: every
       coordinate in this file is HOUSE-LOCAL, the masks/clips/AO/merges
       all run on the unflipped fabric, and the only values that cross
       into world space before the reflection exists are the CAMERA's.

       toWorldX/toWorld are that boundary, and they are their own inverse
       (a world point handed back through toWorld lands in house-local
       space again), which is what lets chfNavProbe reflect a stored
       house-local box on its way to the screen.

       MIRROR is read from the injected facade rather than from SPEC0,
       which is not assigned until the facade section ~3700 lines below:
       the resting camera pose is computed HERE (orbitPos, a dozen lines
       down), long before SPEC0 exists. It is `!!SPEC0.mirror` by
       construction -- SPEC0 is `FACADE ? FACADE.spec : CANONICAL_JS` and
       CANONICAL_JS.mirror is false. */
    var MIRROR = !!(facadeInput && facadeInput.spec && facadeInput.spec.mirror);
    function toWorldX(x) { return MIRROR ? -x : x; }
    function toWorld(v) {
      return MIRROR ? new T.Vector3(-v.x, v.y, v.z) : v.clone();
    }
    /* false until the houseRoot pass has run. Read by textMesh(), which
       leaves the counter-flip to that pass while it is false and applies
       it itself afterwards -- see its own comment. */
    var REFLECTED = false;
    /* the kitchen. SUPERSEDED, both of them, by the cutaway-ownership
       note below -- kept as the record of what this pose used to be
       bought with, not as a description of what it is now:
         - "pulled in and centred on the run after the studio pass
           filled the room: the old pose spent a third of the frame on
           the living room's edge and the yard (bible S5.1, S7.1)".
         - "swung west once the calendar moved onto the wall between the
           pantry and mudroom doors: the old pose put that wall at the
           frame's edge, which is the opposite of making the calendar
           visible".
       The street pose re-creates BOTH conditions, and knowingly: the
       living room stands in the foreground again (it is the only
       direction the kitchen can be seen from now, see below), and the
       calendar wall runs back along the left edge, small and oblique
       instead of square to the eye. Ruled acceptable -- the calendar
       has its own lean-in (chfKitchenFocus('calendar'), which did not
       move) and the wall is still tappable at this pose, so what is
       lost is prominence, not reach. If a later pass wants the calendar
       square to the camera again it has to come from the room's own
       south side, which is where the wall the calendar hangs on faces. */
    /* CUTAWAY OWNERSHIP (fix, 2026-09-16): moved SOUTH, from x 14.6 to
       the great room's own x-range. The old pose stood EAST of the main
       block and looked north-west through what used to be the patio
       notch -- massing arc 1 enclosed that notch as the east room, so
       the only way that view still worked was by ghosting the east
       rooms' own walls and roof, which is exactly the bug. From the
       street, inside the great room's own x span, the only fabric
       between this camera and the kitchen is the great room's OWN: the
       south wall, the west half of the main roof and the facade
       features on them. HOME_AT is unchanged. */
    var HOME_POS = new T.Vector3(4.64, 13.8, 23.0);
    var HOME_AT = new T.Vector3(-1.3, 1.7, -0.2);
    /* Resting exterior: a shallow downward angle leaves a band of horizon above
       the roofs. Keep the same horizontal distance/FOV and bounded scenery;
       raise the aim slightly so the front walls stay readable below the sky. */
    var EXT_POS = new T.Vector3(59.0, 18.0, 62.0);
    var EXT_AT = new T.Vector3(-3.9, 6.5, 7.0);
    /* MASSING ARC 1 (orbit spec section 4): the exterior is eight stops at
       45 degrees around one pivot, not one fixed pose. The pivot is the
       TWO-BLOCK bounding box centre in x/z (main -7.15..14.65 / garage
       block -18.20..-7.15 gives -1.8; -6.10..14.55 gives 4.2) with
       EXT_AT's own height kept, so the house sits in the middle of the
       frame from every side rather than swinging around a corner.

       radius and a0 are MEASURED off EXT_POS above rather than typed, so
       stop 0 stands exactly where the resting view always stood and a
       future change to the resting pose carries the whole ring with it.
       The look target does move at stop 0 (EXT_AT -> the pivot, 2.1 west
       and 2.8 north): a ring cannot keep a per-stop aim point and stay a
       ring, and the spec ruled the pivot for every stop. */
    var ORBIT = {
      pivot: new T.Vector3(-1.8, EXT_AT.y, 4.2),
      height: EXT_POS.y,
      radius: 0, a0: 0,
      /* the CURRENT stop, 0..7. ?angle=N boots here; chfOrbitTo moves it. */
      stop: 0
    };
    ORBIT.radius = Math.sqrt(Math.pow(EXT_POS.x - ORBIT.pivot.x, 2) +
                             Math.pow(EXT_POS.z - ORBIT.pivot.z, 2));
    ORBIT.a0 = Math.atan2(EXT_POS.z - ORBIT.pivot.z, EXT_POS.x - ORBIT.pivot.x);
    function orbitPos(k) {
      var a = ORBIT.a0 + k * Math.PI / 4;
      /* THE MIRROR (section 3.4): the ring's CENTRE moves to the mirrored
         house; the eight ANGLES do not. Stop 0 stays the resting street
         view and every stop keeps its name, so ?angle=N, the swipe and
         the idle return all mean what they meant. */
      return new T.Vector3(toWorldX(ORBIT.pivot.x) + ORBIT.radius * Math.cos(a),
                           ORBIT.height,
                           ORBIT.pivot.z + ORBIT.radius * Math.sin(a));
    }
    ORBIT.stop = (function () {
      var raw = null;
      try { raw = new URLSearchParams(location.search).get('angle'); }
      catch (e) { raw = null; }
      var n = parseInt(raw || '0', 10);
      return isFinite(n) ? ((n % 8) + 8) % 8 : 0;
    })();
    /* the garage from its own doorway (roof + front hidden inside).
       The old pose spent half the frame's width on grass and the
       neighbouring roof and cut the bay off at the cars' noses. Lower
       (27 deg, not 32) and aimed a metre and a half deeper into the
       bay, the whole room fits: the back wall with its plaques clear of
       the nav bar, the long wall down the left, and the floor in front
       of the cars where the clutter lives (bible S5.1) */
    var GARAGE_POS = new T.Vector3(-18.0, 10.5, 21.3);
    var GARAGE_AT = new T.Vector3(-14.3, 1.7, 4.8);
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
    var LIV_POS = new T.Vector3(0, 12.8, 26.5);
    var LIV_AT = new T.Vector3(0, 2.35, 10.3);
    /* STUDY REFIT fix round 1: pulled back 20% along its OWN axis
       (STUDY_AT unchanged, so the desk stays the centre of the shot).
       The shelf wall turned onto the north wall is 5.19 units wide
       and its west end -- the shelf, its binders and the photograph
       frame under it -- ran off the left of the old frame. The room
       cannot shift east: the board's east end meets the wall map.
       Still east of x 6.85, the great-room/east-rooms line, so the
       only street face between the camera and the study is the
       study's own (v2.499.41's reason for moving it here at all). */
    var STUDY_POS = new T.Vector3(7.02, 4.75, 18.82);
    var STUDY_AT = new T.Vector3(12.30, 1.45, 10.68);
    cam.position.copy(orbitPos(ORBIT.stop));
    cam.lookAt(toWorld(ORBIT.pivot));   /* the camera lives in world space */

    var R = exteriorOnly ? options.renderer : new T.WebGLRenderer({ antialias: DETAIL >= 2 });
    if (!exteriorOnly) {
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
    }

    /* ---- the rig: one budget, three tiers ------------------------------
       COOL FILL, WARM KEY. The old rig was warm everywhere (hemisphere
       ground 0xb8926a, ambient 0xfff4e6, sun 0xfff1dc) and summed past 1.6
       on a lit face, so nothing could be dark and nothing could be neutral:
       `ink` came back olive-brown on the tyres and the TV, and every
       authored hue drowned. Now the fill is DAYLIGHT-COOL and only the key
       is warm, which is the plates' whole read - warm light against a cool
       surround - and it is what lets a near-black stay near-black.

       The budget is shared across tiers ON PURPOSE: a panel that demotes
       itself from high to medium must not change colour, only fidelity -
       L found and fixed one violation of this rule (the hood's underside
       glow, search "a lit hood glows" below: the Lambert branch had gone
       flat grey with no emissive at all, instead of the same charcoal
       rendered with less fidelity - the warm-glow HALF of that authored
       pair turns out never to reach the screen in EITHER branch, fix
       round 1 finding 3, see below). Square to the key, fill + key lands
       near 0.90; the room pools (below, and the baked gradients in the
       floor textures) carry the lit patches the rest of the way to
       ~1.05. Fully shaded sits near 0.40.

       L (quality spec §5): SUN_I/HEMI_I/AMB_I above never changed - what
       moved is SUN_OFF's direction (x=21 dominant, arriving close enough
       to the camera's own azimuth to light every camera-facing form
       (counters, car hoods, the island) almost flat -> x=9,z=24, raked
       toward the south-east so camera-facing and key-facing are no
       longer the same surface). That gradient was the point; the price is
       whatever the old azimuth used to hit close to square that the new
       one now grazes, chiefly the kitchen's north run. `fillN` buys that
       back on its own separate budget line: 0xdfe8f2 @ 0.14 (PBR) / 0.10
       (else), no shadow map. It hits a north-facing wall harder than it
       hits a south-facing one, which is what makes it a fill for THIS
       problem rather than a second key - PIL-measured, the kitchen wall's
       region mean is 0.94x its pre-rake reading right after the rake and
       back to 1.02x with fillN on, while the range and hood's OWN shaded
       faces (checked square-on) keep the same gradient with or without
       it. It is dim enough that it does not rewrite the ~0.90/~1.05/~0.40
       figures above; it only refuses to let the shaded case include the
       one wall this room is framed around.

       Fix round 1 (finding 1): the 0.94x->1.02x pair above was measured
       while `fillN` rode `sunTarget` - the SAME point aimShadow() moves
       to a new room's shadow box on every room change - so the fill's
       own direction was silently re-aiming itself at whatever room the
       camera last entered (x +2 in the kitchen out to x -13.4 in the
       garage from one fixed lamp position), not at the north run it is
       named for. Re-pointed at `fillNTarget`, a static Object3D fixed at
       wallB's own centre (0, 2.8, -5.55) - the kitchen's north wall,
       every room, forever. Re-measured PIL-style: the kitchen gate is
       effectively unchanged (0.94x post-rake -> 1.0175x with the fill,
       against 1.02x from the old room-chasing version - the room this
       light exists for never depended on the bug). Every OTHER room's
       whole-frame mean drops some from its old (buggy, self-flattering)
       reading, because it no longer gets a fill custom-aimed at itself,
       but every room still sits above its ORIGINAL pre-rake brightness
       (garage 95.585 pre-rake -> 119.809 now; mudroom 93.165 -> 102.796;
       full table in the task-11 fix-round-1 report). The ~0.90/~1.05/
       ~0.40 figures still hold - fillN was never the term that set them,
       the sun and pools were. */
    /* one clock for the whole scene: the sky dome and the rig must never
       disagree about whether it is dark out */
    function isNight() {
      /* MASSING ARC 2 task 10: ?day=1 pins the scene to daylight. A
         screenshot taken after seven in the evening photographed a dark
         house, so every probe and live test had to monkey-patch
         Date.prototype.getHours from an init script; the URL says it now,
         once, for the one clock the whole scene reads. */
      try {
        if (new URLSearchParams(location.search).get('day') === '1') return false;
      } catch (e) {}
      var outside = state && state.window;
      if (!outside || typeof outside.night !== 'boolean') return true;
      var flip = Date.parse(outside.next_sun_change || '');
      return Number.isFinite(flip) && Date.now() >= flip ? !outside.night : outside.night;
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
    var SUN_OFF = new T.Vector3(9, 24, 24);   /* direction only - the length
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
      exterior: [-5.4, 9.4, 25],
      kitchen: [0.0, 1.5, 13],
      living: [-1.4, 8.6, 13],
      mudroom: [-11.0, 5.6, 12],
      garage: [-15.4, 6.2, 22],
      study: [10.7, 12.1, 10]
    };
    function aimShadow(name) {
      var b = SHADOW_BOX[name] || SHADOW_BOX.exterior;
      /* THE MIRROR (section 3.4): the boxes above are house-local, like
         every other coordinate here, and the sun and its target live in
         `scene` (outside houseRoot), so the CENTRE has to be reflected or
         the frustum sits on empty lawn and the whole house draws the hard
         diagonal this block exists to prevent. SUN_OFF is NOT reflected:
         the sun keeps its own world side, so a mirrored house is lit from
         the same compass direction as an unmirrored one. */
      var bx = toWorldX(b[0]);
      sunTarget.position.set(bx, 1.2, b[1]);
      sunTarget.updateMatrixWorld();
      sun.position.set(bx + SUN_OFF.x, 1.2 + SUN_OFF.y, b[1] + SUN_OFF.z);
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
    /* L (quality spec §5): the rake's ransom - a dim cool fill aimed at
       the north run so raking the key for form does not price the
       kitchen's subject wall into shadow. No shadow map; it is a fill.
       Fix round 1 (finding 1): this used to ride `sunTarget` (the SAME
       Object3D aimShadow() re-points at every room change), so the fill's
       OWN direction silently swung with it too - x +2 in the kitchen out
       to x -13.4 in the garage, from one fixed lamp position. A fill that
       re-aims itself at whichever room the camera last entered is not a
       fill for the kitchen's north run any more, it is a roaming second
       key with the rake's own gradient bug. Given its own STATIC target
       instead: `fillNTarget` sits once, forever, at wallB's own centre -
       the kitchen's north wall itself, world (0, 2.8, -5.55) (see the
       box() call for `wallB` and the AO_OCCLUDERS row that names it,
       both further down this file) - so the direction this light exists
       to hold steady can no longer move just because some other room's
       shadow box did. */
    var fillNTarget = new T.Object3D();
    fillNTarget.position.set(0, 2.8, -5.55);
    scene.add(fillNTarget);
    var fillN = new T.DirectionalLight(0xdfe8f2, PBR ? 0.14 : 0.10);
    fillN.position.set(-2, 9, 26);
    fillN.target = fillNTarget;
    scene.add(fillN);
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
    var poolLamps = [], exteriorLamps = [], exteriorAnchors = [], exteriorGlowMeshes = [], porchPools = [];
    var interiorLightRoot = new T.Group(), exteriorLightRoot = new T.Group();
    interiorLightRoot.name = 'interior_lights'; exteriorLightRoot.name = 'exterior_lights';
    interiorLightRoot.visible = false;
    scene.add(interiorLightRoot); scene.add(exteriorLightRoot);
    if (DETAIL >= 2) {
      var POOL = 0xffe2b4;                  /* warm, but not the orange the
                                               old 0xffd9a0 pushed onto wood */
      [[0.4, 4.55, -0.7, 13.5, 0.42],       /* the pendants over the island */
       [-2.4, 4.35, 9.6, 13.0, 0.40],       /* the living room's own corner */
       [-9.9, 3.45, 5.3, 8.5, 0.34],        /* the mudroom's wall light */
       [-15.4, 3.95, 6.3, 10.0, 0.36],      /* the garage's strip light */
       [10.6, 3.85, 12.1, 9.0, 0.40]        /* the Study's reading lamp */
      ].forEach(function (p) {
        var lamp = new T.PointLight(POOL, (PBR ? 1 : 0.72) * p[4], p[3]);
        lamp.position.set(p[0], p[1], p[2]);
        lamp.userData.dayI = (PBR ? 1 : 0.72) * p[4];
        lamp.userData.lightRole = 'interior';
        interiorLightRoot.add(lamp);
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
    /* L (quality spec §5): the wall's own bake - cream at the ceiling
       line fading to 6% darker at the floor, so a flat plaster box
       reads as one continuous run instead of a paint swatch. A MAPPED
       material takes no lightness pull from applyScenery (scenTint's
       `pull = m.map ? 0 : SCEN_CON`, ~L7010) - correct here on purpose:
       architecture is the ground the props stand on and should not
       recede with them, and this gradient is architecture's own baked
       light, not scenery. Saturation still recedes normally. */
    function wallGradTex() {
      return canvasTex(128, function (g, S) {
        var grad = g.createLinearGradient(0, 0, 0, S);
        grad.addColorStop(0, '#ffffff');    /* cream top: unmodified C.wall */
        grad.addColorStop(1, '#f0f0f0');    /* 240/255 = 0.94 - 6% darker */
        g.fillStyle = grad; g.fillRect(0, 0, S, S);
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
    var wallTex = NICE ? wallGradTex() : null;   /* null below medium, same
                                                     as every other map here -
                                                     mat()'s Lambert branch
                                                     only reads opts.map at
                                                     DETAIL >= 2 anyway */
    /* the shared wall material (kitchen + living, the west-wall group):
       one opts object so every C.wall box() call below hands mat() the
       identical key. The mudroom's own wall run (S3, rough 0.94) keeps
       its own PLASTER opts and its own material - same map, different
       rough, by original design (see wallRun) - not something this
       slice unifies. */
    var WALL_O = { rough: 0.95, map: wallTex };

    var matCache = {};
    function makeMat(c, opts) {
      if (!PBR) {
        var lm = new T.MeshLambertMaterial({ color: c });
        if (opts.map && DETAIL >= 2) lm.map = opts.map;
        return lm;
      }
      /* K3 (quality spec §3): a small finish vocabulary on top of the
         Standard-material default below. PBR-only by construction (this
         whole branch sits past the !PBR return above) — below PBR, finish
         is silently ignored and the prop falls through to Standard or
         Lambert. Values are the calibrated numbers, not the spike's: the
         spike's clearcoat blew highlights under LinearToneMapping, so
         these were tuned against real probe screenshots (task-3 report). */
      if (opts.finish && PBR) {
        var pm;
        if (opts.finish === 'enamel') {
          pm = new T.MeshPhysicalMaterial({ color: c,
            roughness: opts.rough !== undefined ? opts.rough : 0.34,
            metalness: 0, clearcoat: 1.0, clearcoatRoughness: 0.09 });
          pm.envMapIntensity = opts.envInt !== undefined ? opts.envInt : 0.4;
        } else if (opts.finish === 'glassy') {
          /* Tinted glass by ALPHA, never `transmission`. One visible
             transmissive material makes three render every opaque object
             a second time, into an offscreen target, on every frame -- and
             the jars sit inside the frustum from every view, the exterior
             included, behind walls that hide them. Measured on a desktop
             GPU: exterior 3502 draw calls / 47 ms with them, 1838 / 18.5
             ms without; kitchen 16 -> 6.5 ms. Pinned in test_house_live
             (scenario_high_tier_draws_the_scene_once_per_frame). The tint
             is deepened and the env dimmed because alpha lightens toward
             the pale wall behind, where transmission darkened; `thick` is
             unread now. */
          pm = new T.MeshPhysicalMaterial({
            color: new T.Color(c).multiplyScalar(0.45),
            roughness: 0.06, metalness: 0,
            transparent: true, opacity: 0.62, depthWrite: false });
          pm.envMapIntensity = 0.5;
        } else {                                   /* ceramic */
          pm = new T.MeshPhysicalMaterial({ color: c,
            roughness: opts.rough !== undefined ? opts.rough : 0.2,
            metalness: 0, clearcoat: 0.8, clearcoatRoughness: 0.12 });
          pm.envMapIntensity = opts.envInt !== undefined ? opts.envInt : 0.6;
        }
        if (opts.map) pm.map = opts.map;
        return pm;
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
    /* B1 (batching spec): one material per LOOK, not per mesh. The cache
       key is every input makeMat reads. forceUnique is the L1 valve: a
       zone-bound mesh gets a private material the glow loop may paint. */
    function mat(c, opts, forceUnique) {
      opts = opts || {};
      if (forceUnique || opts.unique) return makeMat(c, opts);
      var key = (PBR ? 'p|' : 'l|') + c +
                '|' + (opts.rough !== undefined ? opts.rough : '') +
                '|' + (opts.metal !== undefined ? opts.metal : '') +
                '|' + (opts.envInt !== undefined ? opts.envInt : '') +
                '|' + (opts.map ? opts.map.uuid : '') +
                '|' + (opts.finish || '') +
                '|' + (opts.thick !== undefined ? opts.thick : '');
      var m = matCache[key];
      if (!m) {
        m = matCache[key] = makeMat(c, opts);
        m.userData.shared = true;
      }
      return m;
    }
    function inZoneGroup(g) {
      for (var p = g; p; p = p.parent)
        if (p.userData && p.userData.zone) return true;
      return false;
    }
    /* B1 (batching spec): geometry is immutable here — every helper sets
       position/rotation/scale on the MESH, so identical dimensions can
       share one BufferGeometry. Also a boot-time win (L7): roundedGeo
       runs a full Shape triangulation per call, and cabinet fronts
       repeat their dimensions dozens of times. */
    var geoCache = {};
    function cgeo(key, make) {
      var g = geoCache[key];
      if (!g) {
        g = geoCache[key] = make();
        g.userData.cached = true;
      }
      return g;
    }
    /* ---- SHELL (shell spec section 3): the fabric registry -------------
       Every shell piece registers itself where it is built. The solver
       (section 4, just below) reads FABRIC; mergeStatic and the fence
       sets read it so shell membership is declared exactly once. */
    var FABRIC = [];
    /* SHELL (spec section 5, the navigation law): every registered piece
       stamps the room it fronts onto its own group (`o.room`), exactly
       the way south_wall/east_wall used to hand-stamp themselves at their
       own build sites (that per-site convention is now generalized here,
       the one place every piece already passes through). onTap's ancestor
       walk (interior AND exterior branches) climbs looking for the first
       userData.room, so this single line does the work every hand stamp
       used to. `o.room` absent/undefined (a future massing piece with
       nothing behind it yet, per T8) leaves userData.room unset —
       deliberately NOT a fallback 'kitchen': userData.fabric marks the
       group as a REGISTERED shell piece regardless, so stampHouse's own
       y>0.6 fallback (below) can tell "a registered piece that chose no
       room" apart from "ordinary untagged decor" and skip the guess
       rather than mis-route a future inert massing piece into the
       kitchen. */
    /* VIEW-VOLUME MASKING (task 2, corrected): a fabric row's convexity
       has to be read at THIS moment -- registration -- not from a single
       bulk pass over FABRIC later. Two different lifetimes collide
       otherwise: buildRoom()'s own rows are complete when regFabric()
       runs on them but get merged by the per-fabric mergeStatic loop a
       few hundred lines below (a snapshot taken after that loop would
       count fused composites, not the boxes Task 3's buildRoomShells()
       clips); house_features.js's door fixtures register even later,
       through syncWorld()'s first call, well after that merge loop has
       already run and finished -- a snapshot taken before the loop would
       simply never see them. Scanning right here, per row, at the
       instant its own group is complete, is correct for both. `refabBox`
       already has this exact problem for the world AABB (west_wall and
       mudroom_front grow more content hundreds of lines after they
       register) and already solves it by re-measuring explicitly at the
       point the fold happens; `refabConvexity` below is the same fix for
       this new field, called at those same two sites AND at `yard`,
       whose own late fold is instanceYard() replacing hundreds of
       individual props with a couple dozen InstancedMesh objects right
       after yard's own regFabric() call.

       INSTANCEDMESH (fix round 1) is never counted convex and is never
       expected to be: the controller ruling exempts every InstancedMesh
       from the mask outright (planting decor; no room camera looks
       through a bush at its own room), so Task 3 keeps each one whole in
       every room shell rather than trying to keep/drop it individually
       by its own bounding box -- worldTris() (above) would need
       instanceMatrix to build a per-copy solid and does not have it, so
       it throws if ever called on one instead of returning a silently
       wrong triangle list. `nonconvex` still reports 'InstancedMesh' by
       name so the inventory stays honest about what is in a row, not
       because Task 3 is expected to do anything per-instance with it. */
    function scanConvexity(g) {
      var meshes = 0, convex = 0, nonconvex = [];
      g.traverse(function (m) {
        if (!m.isMesh) return;
        meshes += 1;
        if (m.userData && m.userData.convex) { convex += 1; return; }
        nonconvex.push(m.isInstancedMesh ? 'InstancedMesh'
                      : (m.geometry ? m.geometry.type : 'Unknown'));
      });
      return { meshes: meshes, convex: convex, nonconvex: nonconvex };
    }
    /* VIEW-VOLUME MASKING (task 4, spec section 5): a fabric row is
       {name, n, box, room, kit} and nothing else. The verdict solver's
       own fields -- `owners` (the cutaway-ownership table), `cutawayRoom`,
       `twoSided`, `mode: 'hide'`, `plane`, `pad` -- are retired: the
       per-room mask (buildRoomShells, far below) reads the room box and
       the room camera and cuts each mesh where it stands between them,
       so no row has to say which room may remove it, from which side,
       or how far the corridor reaches. `n` stays for the AO derivation
       (wall-like test) and the registry's own reporting. */
    function regFabric(group, o) {
      group.userData.fabric = true;
      if (o.room) group.userData.room = o.room;
      FABRIC.push({ g: group, name: o.name,
                    n: new T.Vector3(o.n[0], o.n[1], o.n[2]).normalize(),
                    box: o.box, edges: null,
                    /* VIEW-VOLUME MASKING (task 2, design spec section 3):
                       a kit is non-convex fabric (a door, window, porch or
                       lamp assembly) that the mask keeps or drops WHOLE
                       rather than clipping mesh by mesh -- task 3 reads
                       this flag exactly where it reads userData.convex on
                       a fabric mesh. */
                    kit: !!o.kit,
                    convexity: scanConvexity(group) });
    }
    /* box helper for regFabric call sites: a plain Box3 does not survive
       structured-clone back to a test harness, and the spec wants six
       plain numbers anyway (section 3's world AABB), so every call site
       converts once, here, instead of hand-unpacking min/max five times
       over. updateMatrixWorld(true) first matches mergeStatic's own call
       (below) — build time only, the group never moves after. */
    function fabBox(g) {
      g.updateMatrixWorld(true);
      var b = new T.Box3().setFromObject(g);
      return [b.min.x, b.max.x, b.min.y, b.max.y, b.min.z, b.max.z];
    }
    /* VIEW-VOLUME MASKING (task 2, design spec section 3): the world-
       space triangle list of ONE mesh, in the shape house_clip.js's
       solids already speak (position, uv, slot 0 -- ao is the vault's
       to add, task 3 does not read it here). Task 3 calls this on every
       fabric mesh stamped userData.convex to build the solid it clips.
       Handles indexed and non-indexed geometry alike.

       INSTANCEDMESH (task 2, fix round 1): NEVER a valid argument here.
       This function reads only `mesh.matrixWorld` -- one transform for
       the whole draw call -- and has no notion of `instanceMatrix`, the
       per-instance transform an InstancedMesh actually draws each copy
       with; the vendored three's own Box3.expandByObject has the same
       blind spot (fabBox's own comment above, on yardG, already
       verified this against the vendored r150 build). An InstancedMesh
       is therefore never stamped userData.convex (scanConvexity below
       reports its type as 'InstancedMesh', never convex) and the
       controller ruling exempts every InstancedMesh from the mask
       outright -- Task 3 keeps it whole in every room shell, the same
       way it keeps a kit whole, and so is never supposed to reach this
       function with one. Throws rather than silently returning `[]`:
       a caller that reaches here with an InstancedMesh has a bug (it
       would otherwise silently clip a bush by its single base-geometry
       transform, not its planted copies), and a loud failure is safer
       than a quietly wrong triangle list. */
    function worldTris(mesh) {
      if (mesh.isInstancedMesh)
        throw new Error('worldTris: InstancedMesh has no single ' +
          'matrixWorld solid -- instanced props are exempt from the ' +
          'mask and must be kept whole, never clipped');
      var g = mesh.geometry, pos = g.getAttribute('position'), uv = g.getAttribute('uv');
      mesh.updateWorldMatrix(true, false);
      var M = mesh.matrixWorld, tris = [], tmp = new T.Vector3();
      function vert(i) {
        tmp.fromBufferAttribute(pos, i).applyMatrix4(M);
        return { p: [tmp.x, tmp.y, tmp.z], uv: uv ? [uv.getX(i), uv.getY(i)] : [0, 0] };
      }
      var n = g.index ? g.index.count : pos.count;
      for (var i = 0; i < n; i += 3) {
        var i0 = g.index ? g.index.getX(i) : i, i1 = g.index ? g.index.getX(i + 1) : i + 1, i2 = g.index ? g.index.getX(i + 2) : i + 2;
        tris.push({ a: vert(i0), b: vert(i1), c: vert(i2), slot: 0 });
      }
      return tris;
    }
    /* Massing arc 1: two pieces the arc FOLDED into an already-registered
       group (the mudroom's east finish into west_wall, its street door
       and jamb into mudroom_front) are built hundreds of lines after
       those registrations, so their group's box was measured without
       them. Re-measure rather than leave a stale row: the solver's
       corridor test reads f.box, and a fold that grows a piece must grow
       the box it is solved with. */
    function refabBox(name, g) {
      FABRIC.forEach(function (f) { if (f.name === name) f.box = fabBox(g); });
    }
    /* VIEW-VOLUME MASKING (task 2, corrected): the same re-measurement
       refabBox does, for convexity -- a fold that adds meshes after
       registration must re-scan them too, or the row's convexity/kit
       verdict is judged on the group it registered with instead of the
       one it ends up holding. */
    function refabConvexity(name, g) {
      FABRIC.forEach(function (f) {
        if (f.name === name) f.convexity = scanConvexity(g);
      });
    }
    /* ---- SHELL (spec section 4): the shell swap ------------------------
       Camera-settle only (enterRoom, goExterior, frameZone's lean-in) —
       never per frame; render-on-demand law intact. VIEW-VOLUME MASKING
       (task 3) replaced the half-space solver that lived here: the
       per-room cut is decided ONCE at build time (buildRoomShells, far
       below, beside the merge loop) and solveShell only swaps what is
       visible. boxOk stays: the mask's box guard reads it (task 4
       retired the corridor rule's own helpers with the verdicts). */
    /* Controller ruling: a piece registered before its group ever grows
       real geometry carries three.js's untouched Box3-empty sentinel:
       min=(+Inf,+Inf,+Inf), max=(-Inf,-Inf,-Inf). That box is unusable
       for centre/dot math (an Infinity centre only ever produces NaN
       dot products, which
       compare false either way and would leave the piece SOLID by
       accident rather than by contract) and geometrically means "no
       fabric exists yet to occlude anything" — so it verdicts solid on
       purpose, checked BEFORE any centre/dot math ever runs on it. Once
       a later task hangs real geometry on such a group, fabBox at its
       (now-complete) build site measures a real box and this guard
       simply stops matching — no solver change required. */
    function boxOk(b) {
      return b[1] >= b[0] && b[3] >= b[2] && b[5] >= b[4] &&
             isFinite(b[0]) && isFinite(b[1]) && isFinite(b[2]) &&
             isFinite(b[3]) && isFinite(b[4]) && isFinite(b[5]);
    }
    function solveShell(camPos, subject) {
      if (neighborhood) neighborhood.update(camPos, toWorld(ORBIT.pivot), !subject);
      // Unshadowed interior pools must not shine through the closed exterior.
      interiorLightRoot.visible = !!subject;
      exteriorLightRoot.visible = !subject;
      /* VIEW-VOLUME MASKING (task 3, spec section 4): the verdicts and
         the corridor rule are gone; this is a SWAP. subject.room names
         the room shell to show; every mesh whose maskPattern names that
         room hides and its remnant (in the shell) stands in. subject
         null (the exterior, every orbit stop) and a room with no shell:
         everything on, every shell off -- the sealed house. camPos is
         no longer read (the masks were built from the room cameras at
         build time; a lean-in keeps its room's shell, no recompute),
         kept in the signature so every caller stays as it was. */
      var room = subject && subject.room && roomShellGroups[subject.room] ? subject.room : null;
      var tag = room ? '|' + room + '|' : null;
      FABRIC.forEach(function (f) {
        f.verdict = (room && f.shells && f.shells[room] && f.shells[room].fraction > 0)
                  ? 'masked' : 'solid';
        /* Permanent wireframes obscured the room on touch panels, so
           ghost edges remain off. */
        if (f.edges) f.edges.visible = false;
      });
      MASK_TOGGLES.forEach(function (o) {
        var ud = o.userData;
        if (ud.maskOnly) o.visible = !!tag && ud.maskOnly.indexOf(tag) >= 0;
        else o.visible = !tag || ud.maskPattern.indexOf(tag) < 0;
      });
      Object.keys(roomShellGroups).forEach(function (r) {
        roomShellGroups[r].visible = (r === room);
      });
      if (webgl) webgl.shadowDirty();
    }
    /* ---- SHELL (spec section 3): the one shared ghost-line material ----
       LineBasicMaterial (LineSegments only, never a fill) — ONE instance
       for every ghosted piece in the house, per the spec's "ONE shared
       LineBasicMaterial"; a per-piece clone would be the batching arc's
       own lesson broken one material at a time. Declared here, beside
       FABRIC/regFabric/solveShell (the SHELL helper layer) rather than at
       the build step's own call site far below: the build step itself
       must run after every regFabric() call site in the file (FABRIC
       only reaches its final membership once buildRoom() is nearly
       done), so IT necessarily lives down near mergeStatic — but the
       MATERIAL has no such ordering dependency and reads better beside
       the rest of its own family. */
    var GHOST_MAT = new T.LineBasicMaterial({ color: 0x2d2018,
      transparent: true, opacity: 0.55 });
    var discMatCache = {};
    function discMat(color, opacity, blending, depthWrite) {
      var k4 = color + '|' + opacity + '|' +
               (blending !== undefined ? blending : 'none') + '|' +
               (depthWrite === undefined ? 'true' : depthWrite);
      var m = discMatCache[k4];
      if (!m) {
        var spec = { color: color, transparent: true, opacity: opacity };
        if (blending !== undefined) spec.blending = blending;
        if (depthWrite !== undefined) spec.depthWrite = depthWrite;
        m = discMatCache[k4] = new T.MeshBasicMaterial(spec);
        m.userData.shared = true;
      }
      return m;
    }
    /* ---- L1 rail (spec 2026-09-10-house-batching-design.md) ----------
       A zone never shares a material: the glow loop writes emissive on
       every mesh a zone owns, wherever it hangs. Materials handed out by
       the cache (Task B1b) carry userData.shared; own() trades a shared
       material for a private clone, and zoneTag() is the ONE way a mesh
       outside a zoneGroup joins a zone. */
    function own(m) {
      if (m && m.isMesh && m.material && m.material.userData &&
          m.material.userData.shared) {
        var src = m.material, b = src.userData._scBase;
        m.material = src.clone();
        m.material.userData.shared = false;
        /* a shared material may be wearing the scenery tint: the clone
           must be born AUTHORED, and must not carry the knob's books */
        if (b) {
          m.material.color.copy(b.c);
          if (b.r !== undefined) m.material.roughness = b.r;
          if (b.e !== undefined) m.material.envMapIntensity = b.e;
        }
        delete m.material.userData._scBase;
        delete m.material.userData._scEpoch;
        delete m.material.userData._scSlot;
        delete m.material.userData._scDim;
      }
      return m;
    }
    function zoneTag(m, zone, room) {
      if (!m) return m;
      m.userData.zone = zone;
      if (room) m.userData.room = room;
      return own(m);
    }
    var STEEL = { rough: 0.3, metal: 0.85, envInt: 1.1 };
    var CHROME = { rough: 0.12, metal: 1.0, envInt: 1.3 };
    var GLOSS = { rough: 0.3, metal: 0.02, envInt: 0.25 };
    var WOODM = { rough: 0.6, metal: 0.0 };

    function finish(m, noShadow) {
      if (SHADOWS && !noShadow) { m.castShadow = true; m.receiveShadow = true; }
      return m;
    }
    /* ---- TEXT MESHES (spec 2026-09-17 section 3.4) ----------------------
       A reflection turns lettering into its own mirror image, and there is
       no amount of camera work that reads that back. So the ONE creator of
       every mesh that wears a painted, text-bearing canvas STAMPS
       userData.noMirror -- and nothing else. The counter-flip itself is
       applied by the houseRoot pass, after the AO bake, because
       CONSTRUCTION NEVER FLIPS: a negative scale carried through
       worldTris, the room masks, the clipper, the AO bake and the merge
       passes is exactly the thing this arc's ruling forbids, and it
       would hand every one of them a mirrored triangle winding to reason
       about. Built, measured and batched square; reflected at the end.
       The maths, once the pass has run: world = F . T . R . S with
       F = diag(-1,1,1) from houseRoot and S = diag(-1,1,1) from the
       counter-flip, so the determinant comes back +1 -- a proper rigid
       transform, not a reflection, and the words read forward on the
       mirrored wall.

       The manifest below is the contract the pure test reads back: every
       canvas-drawn word in this file is written inside one of these
       named painters, and each painter's canvas is worn by a mesh built
       here. Add a painter that letters a surface and it goes in the list
       or the test says so.

       finish() is deliberately NOT called from inside: four of the six
       wearers set their own shadow flags (the weather pane switches
       castShadow OFF on purpose, the hero plaque and the calendar sheet
       never cast at all), so folding it in would change what the
       unmirrored house renders -- which this task is not allowed to do.
       `group` is optional for the same reason: the bus stop arm is
       parented by btag(), which also tags its zone. */
    /* TEXT_PAINTERS: stopArm, heroFace, calFace, critFace, paneFace, carPlaque */
    function textMesh(geo, material, group) {
      var m = new T.Mesh(geo, material);
      m.userData.noMirror = true;
      /* REFLECTED says the one-shot pass has already been and gone. A
         mesh built before it (every wearer in this file) is left square
         and the pass flips it; a mesh built AFTER it -- syncGarage's car
         plaques, rebuilt on every telemetry change -- has missed the
         pass, so it takes the same flip here. Never both. */
      if (MIRROR && REFLECTED) m.scale.x *= -1;
      if (group) group.add(m);
      return m;
    }
    /* Exterior patterns use the main facade and main roof as their scale
       references. BoxGeometry otherwise maps every face to 0..1, which puts
       the same number of battens/shingles on a 3.5-unit wing and a 14-unit
       wall. Scale UVs by local world dimensions; materials and textures stay
       shared, so this adds no texture or material allocation. */
    /* MASSING ARC 2 (spec 2026-09-17 section 3.1): ALL SIX claddings
       share this one body reference -- it is the main facade's own
       dimensions, and every wall tile is authored at that scale, so a
       lap course, a brick and a stone read the same size on a 3.5-unit
       wing as on the 14-unit wall. cladTex stamps it on every tile it
       builds (arc 4's separate SIDING_UV_REF said the same numbers
       twice and is gone). */
    var BATTEN_UV_REF = [13, 5.6, 13];
    var SHINGLE_UV_REF = [14.64, 5.6, 11.521];
    /* MASSING ARC 2 (spec 2026-09-17 section 3.1): `key` is the MATERIAL
       name now, and two materials can share a name across two references
       -- the roof's own shingle tile (SHINGLE_UV_REF) and the wall
       cladding called 'shingle' (the body reference). So the reference
       itself is part of the cache key: a geometry cached for one must
       never be handed to the other. */
    function tiledBoxGeo(w, h, d, ref, key) {
      return cgeo('bt|' + key + '|' + ref.join(',') + '|' + w + '|' + h + '|' + d, function () {
        var g = new T.BoxGeometry(w, h, d);
        var uv = g.attributes.uv, no = g.attributes.normal;
        var scale = [w / ref[0], h / ref[1], d / ref[2]];
        for (var i = 0; i < uv.count; i++) {
          var ax = Math.abs(no.getX(i)), ay = Math.abs(no.getY(i));
          var az = Math.abs(no.getZ(i)), su, sv;
          if (ax >= ay && ax >= az) { su = scale[2]; sv = scale[1]; }
          else if (ay >= az)       { su = scale[0]; sv = scale[2]; }
          else                     { su = scale[0]; sv = scale[1]; }
          uv.setXY(i, uv.getX(i) * su, uv.getY(i) * sv);
        }
        uv.needsUpdate = true;
        return g;
      });
    }
    function box(w, h, d, c, x, y, z, group, opts) {
      if (opts && opts.facadeBlock && SPEC0 && (SPEC0.story_finishes || SPEC0.finishes))
        return finishWallBox(w, h, d, c, x, y, z, group, opts);
      var g0 = group || scene;
      var ch = opts && opts.ch !== undefined ? opts.ch
             : (NICE ? 0.022 : 0);
      /* MASSING ARC 2 (spec 2026-09-17 section 3.1): the tile CARRIES its
         own world reference (cladTex stamps userData.uvRef/uvKey), so
         this is one read rather than a three-way identity test that only
         ever knew the three tiles this file happened to build. */
      var uvRef = null, uvKey = '';
      if (NICE && opts && opts.map && opts.map.userData && opts.map.userData.uvRef) {
        uvRef = opts.map.userData.uvRef; uvKey = opts.map.userData.uvKey;
      }
      var m = new T.Mesh(
        ch > 0 ? chamferGeo(w, h, d, ch)
               : uvRef ? tiledBoxGeo(w, h, d, uvRef, uvKey)
               : cgeo('b|' + w + '|' + h + '|' + d, function () {
                   return new T.BoxGeometry(w, h, d);
                 }),
        mat(c, opts, inZoneGroup(g0)));
      /* VIEW-VOLUME MASKING (task 2): every shape box() can hand back --
         a plain BoxGeometry, the UV-remapped tiledBoxGeo (same box, only
         its uv attribute differs) or chamferGeo's chamfered corners -- is
         a convex polyhedron. Task 3's clipper reads this to decide
         whether a fabric mesh is clipped in place (convex) or kept/
         dropped whole (a kit, see regFabric). */
      m.userData.convex = true;
      m.position.set(x, y, z); finish(m); g0.add(m); return m;
    }
    /* ---- K1 (quality spec §3): the chamfered box ----------------------
       44 triangles: 6 faces, 12 one-segment chamfer strips, 8 corner
       tris. Normals are position-averaged after computeVertexNormals so
       the strip SHADES like a fillet — a flat corner facet square to the
       sun reads as a white triangle (the spike's first draft). UVs are
       planar per dominant axis, which matches how the box-face canvas
       maps are authored. Cheap enough to build 254 times on a Pi, which
       roundedGeo (a Shape triangulation) never was. */
    function chamferRaw(w, h, d, ch) {
      var full = [w / 2, h / 2, d / 2];
      var c = Math.max(1e-4, Math.min(ch, full[0] * 0.49, full[1] * 0.49,
                                      full[2] * 0.49));
      var inner = [full[0] - c, full[1] - c, full[2] - c];
      var pos = [], uv = [];
      function tri(a, b, e) {
        var ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
        var vx = e[0] - a[0], vy = e[1] - a[1], vz = e[2] - a[2];
        var nx = uy * vz - uz * vy, ny = uz * vx - ux * vz,
            nz = ux * vy - uy * vx;
        var cx = (a[0] + b[0] + e[0]) / 3, cy = (a[1] + b[1] + e[1]) / 3,
            cz = (a[2] + b[2] + e[2]) / 3;
        if (nx * cx + ny * cy + nz * cz < 0) { var t = b; b = e; e = t; }
        var an = Math.abs(nx), bn = Math.abs(ny), dn = Math.abs(nz);
        var i0 = 0, i1 = 1;
        if (an >= bn && an >= dn) { i0 = 2; i1 = 1; }
        else if (bn >= dn) { i0 = 0; i1 = 2; }
        [a, b, e].forEach(function (p) {
          pos.push(p[0], p[1], p[2]);
          uv.push((p[i0] + full[i0]) / (2 * full[i0]),
                  (p[i1] + full[i1]) / (2 * full[i1]));
        });
      }
      function quad(a, b, e, f) { tri(a, b, e); tri(a, e, f); }
      function V() { return [0, 0, 0]; }
      var a, b, e, sa, sb, sc;
      for (a = 0; a < 3; a++) {
        b = (a + 1) % 3; e = (a + 2) % 3;
        for (sa = -1; sa <= 1; sa += 2) {
          var q = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(function (s) {
            var p = V(); p[a] = sa * full[a]; p[b] = s[0] * inner[b];
            p[e] = s[1] * inner[e]; return p;
          });
          quad(q[0], q[1], q[2], q[3]);
        }
      }
      for (a = 0; a < 3; a++) {
        b = (a + 1) % 3; e = (a + 2) % 3;
        for (sa = -1; sa <= 1; sa += 2) for (sb = -1; sb <= 1; sb += 2) {
          var p1 = V(); p1[a] = sa * full[a]; p1[b] = sb * inner[b]; p1[e] = -inner[e];
          var p2 = V(); p2[a] = sa * full[a]; p2[b] = sb * inner[b]; p2[e] = inner[e];
          var p3 = V(); p3[a] = sa * inner[a]; p3[b] = sb * full[b]; p3[e] = inner[e];
          var p4 = V(); p4[a] = sa * inner[a]; p4[b] = sb * full[b]; p4[e] = -inner[e];
          quad(p1, p2, p3, p4);
        }
      }
      for (sa = -1; sa <= 1; sa += 2) for (sb = -1; sb <= 1; sb += 2)
        for (sc = -1; sc <= 1; sc += 2) {
          tri([sa * full[0], sb * inner[1], sc * inner[2]],
              [sa * inner[0], sb * full[1], sc * inner[2]],
              [sa * inner[0], sb * inner[1], sc * full[2]]);
        }
      var g = new T.BufferGeometry();
      g.setAttribute('position', new T.Float32BufferAttribute(pos, 3));
      g.setAttribute('uv', new T.Float32BufferAttribute(uv, 2));
      g.computeVertexNormals();
      var na = g.attributes.normal, pa = g.attributes.position, acc = {}, k, i;
      for (i = 0; i < pa.count; i++) {
        k = (pa.getX(i) * 1e4 | 0) + '_' + (pa.getY(i) * 1e4 | 0) + '_' +
            (pa.getZ(i) * 1e4 | 0);
        var s2 = acc[k] || (acc[k] = [0, 0, 0]);
        s2[0] += na.getX(i); s2[1] += na.getY(i); s2[2] += na.getZ(i);
      }
      for (i = 0; i < pa.count; i++) {
        k = (pa.getX(i) * 1e4 | 0) + '_' + (pa.getY(i) * 1e4 | 0) + '_' +
            (pa.getZ(i) * 1e4 | 0);
        var v2 = acc[k], L2 = Math.sqrt(v2[0] * v2[0] + v2[1] * v2[1] +
                                        v2[2] * v2[2]) || 1;
        na.setXYZ(i, v2[0] / L2, v2[1] / L2, v2[2] / L2);
      }
      na.needsUpdate = true;
      return g;
    }
    function chamferGeo(w, h, d, ch) {
      return cgeo('b|' + w + '|' + h + '|' + d + '|' + ch, function () {
        return chamferRaw(w, h, d, ch);
      });
    }
    /* K1: architecture (walls, slabs, roofs, trim that sells an edge)
       opts out of the prop-tier chamfer default — sharp() forces ch:0
       without disturbing whatever else the call site already passed. */
    function sharp(o) {
      var r2 = {}; if (o) for (var k3 in o) r2[k3] = o[k3]; r2.ch = 0; return r2;
    }
    /* ---- K2 (quality spec §3): lathe + sweep, the detail vocabulary ---
       Profiles are UNIT-SCALE [x, y] outlines (max radius ~0.5, height
       ~1.0); latheAt() puts size in mesh scale, so every jar shares one
       geometry per segment tier — the batching lesson applied from
       birth. Segment counts tier like cyl(). */
    var PROFILES = {
      jar:    [[0, 0], [0.36, 0], [0.40, 0.06], [0.40, 0.72], [0.32, 0.82],
               [0.34, 0.88], [0.27, 0.92], [0.27, 1.0], [0, 1.0]],
      lid:    [[0, 0], [0.36, 0], [0.37, 0.55], [0.28, 0.8], [0, 1.0]],
      bowl:   [[0, 0.08], [0.18, 0], [0.44, 0.35], [0.50, 0.9], [0.47, 1.0],
               [0.41, 0.42], [0.16, 0.12], [0, 0.2]],
      plate:  [[0, 0], [0.30, 0], [0.48, 0.5], [0.50, 1.0], [0.44, 0.55],
               [0.27, 0.18], [0, 0.18]],
      cup:    [[0, 0], [0.30, 0], [0.34, 0.1], [0.36, 1.0], [0.30, 1.0],
               [0.28, 0.16], [0, 0.16]],
      vase:   [[0, 0], [0.26, 0], [0.38, 0.3], [0.20, 0.75], [0.24, 1.0],
               [0, 1.0]],
      knob:   [[0, 0], [0.18, 0], [0.20, 0.35], [0.42, 0.55], [0.46, 0.8],
               [0.38, 1.0], [0, 1.0]],
      foot:   [[0, 0], [0.46, 0], [0.46, 0.35], [0.30, 0.55], [0.27, 1.0],
               [0, 1.0]],
      hinge:  [[0, 0], [0.30, 0], [0.30, 0.2], [0.40, 0.28], [0.40, 0.72],
               [0.30, 0.8], [0.30, 1.0], [0, 1.0]],
      pull:   [[0, 0], [0.42, 0], [0.46, 0.25], [0.30, 0.5], [0.46, 0.75],
               [0.42, 1.0], [0, 1.0]],
      finial: [[0, 0], [0.20, 0], [0.34, 0.3], [0.12, 0.6], [0.20, 0.85],
               [0, 1.0]],
      shade:  [[0.22, 0], [0.50, 0], [0.34, 1.0], [0.20, 1.0]]
    };
    function latheGeo(key, seg) {
      var sg = seg || (DETAIL >= 3 ? 16 : 10);
      return cgeo('L|' + key + '|' + sg, function () {
        var pts = PROFILES[key].map(function (p) {
          return new T.Vector2(p[0], p[1]);
        });
        return new T.LatheGeometry(pts, sg);
      });
    }
    function latheAt(key, s, c, x, y, z, group, opts) {
      var g0 = group || scene;
      var m = new T.Mesh(latheGeo(key, opts && opts.seg),
                         mat(c, opts, inZoneGroup(g0)));
      if (typeof s === 'number') m.scale.set(s, s, s);
      else m.scale.set(s[0], s[1], s[2]);
      m.position.set(x, y, z); finish(m); g0.add(m); return m;
    }
    /* R4 fix-round: route through cgeo like every other geometry helper.
       buildCar() minted a fresh TubeGeometry on every call (bumper trim +
       mirror stalk), and syncGarage's rebuild key includes live
       battery/fuel values, so a car rebuilds often while its old group is
       removed without dispose — orphaned GPU geometry. Sweep points are
       baked into the geometry, so identical inputs (finite per body_type)
       now share one cached mesh, matching cyl()'s resolve-then-key shape. */
    function sweepGeo(pts, r, seg, rad) {
      var sg = seg || (DETAIL >= 3 ? 24 : 14);
      var rd = rad || (DETAIL >= 3 ? 10 : 7);
      return cgeo('S|' + JSON.stringify(pts) + '|' + r + '|' + sg + '|' + rd,
        function () {
          return new T.TubeGeometry(new T.CatmullRomCurve3(
            pts.map(function (p) { return new T.Vector3(p[0], p[1], p[2]); })),
            sg, r, rd, false);
        });
    }
    function sweepAt(pts, r, c, group, opts) {
      var g0 = group || scene;
      var m = new T.Mesh(sweepGeo(pts, r, opts && opts.seg,
                                  opts && opts.rad),
                         mat(c, opts, inZoneGroup(g0)));
      finish(m); g0.add(m); return m;
    }
    function rbox(w, h, d, r, c, x, y, z, group, opts) {
      var o = {}, k2;
      if (opts) for (k2 in opts) o[k2] = opts[k2];
      o.ch = DETAIL < 2 ? 0 : r;
      return box(w, h, d, c, x, y, z, group, o);
    }
    function cyl(rt, rb, h, c, x, y, z, group, seg, opts) {
      var g0 = group || scene;
      var sg = seg || (DETAIL >= 3 ? 18 : 10);
      var m = new T.Mesh(cgeo('c|' + rt + '|' + rb + '|' + h + '|' + sg, function () {
        return new T.CylinderGeometry(rt, rb, h, sg);
      }), mat(c, opts, inZoneGroup(g0)));
      m.position.set(x, y, z); finish(m); g0.add(m); return m;
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
      var m = new T.Mesh(cgeo('circ|20', function () { return new T.CircleGeometry(1, 20); }),
        discMat(C.shadow, 0.16));
      m.rotation.x = -Math.PI / 2;
      m.scale.set(rx, rz, 1);
      m.position.set(x, y0 === undefined ? 0.012 : y0, z);
      (group || scene).add(m); return m;
    }

    /* ---- shell: open-corner diorama on a slab -------------------------- */
    box(13.6, 0.5, 11.6, C.shell, 0, -0.27, 0, null, sharp());
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
      /* L (quality spec §5): this used to sit at (2.6, 12.4), a full 1.7
         x / 1.5 z away from the reading corner's own floor lamp (shade
         at 0.90, 1.65, 10.90 - see `ll`/`ls` calls below) - closer to
         the open floor past the side table than to the lamp it was
         named for. Moved to sit under the lamp it is actually the pool
         for; the existing idiom (extend to sit under ITS lamp). */
      [0.90, 10.90, 3.2, 0.16]    /* the reading corner's own floor lamp */
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
    var floor = new T.Mesh(new T.PlaneGeometry(13, 11.6, 26, 24),
      PBR ? new T.MeshStandardMaterial({ map: floorTexK, roughness: 0.5,
                                         envMapIntensity: 0.1 })
          : new T.MeshLambertMaterial({ map: floorTexK }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = 0.001;
    if (SHADOWS) floor.receiveShadow = true;
    /* SHELL (spec section 4): the kitchen's own room tag. This whole
       kitchen.js-heritage build predates the room-tag system (stampHouse,
       far below, only patches up the NEWER extG-built rooms) — the
       kitchen's floor is otherwise the one totally untagged surface a
       room-footprint traversal would ever cross, so it is tagged here,
       at its own build site, exactly like every other room's floor
       already is (mtag(mfloor), gtag's garage floor). */
    floor.userData.room = 'kitchen';
    scene.add(floor);

    var wallB = box(13, 5.6, 0.35, C.wall, 0, 2.8, -5.55, null, sharp(WALL_O));
    /* the shell's wall thickness, read off the one wall that defines it.
       Declared HERE rather than beside WALL_H4/WALL_Y4 further down
       (massing arc 2): baseBand() is called at the north cladding, which
       is built before that line, and `var` hoisting lifts only the
       declaration -- the VALUE has to be assigned above every reader. */
    var WALL_T4 = wallB.geometry.parameters.depth;      /* 0.35 */
    /* SHELL (Task 4, spec section 3): north_wall registers wallB directly
       — a bare mesh needs no wrapping group (fabBox/regFabric both accept
       any Object3D, and nothing is ever added to a Mesh the way things
       get added to a Group), so it has been "complete" since this exact
       line. n is [0,0,-1]: wallB's own physical outward face — a true
       exterior boundary (only yard beyond it), not an interior partition
       like west_wall, so no flip is needed (unlike west_wall's T2 flip,
       read at its own registration site far below). */
    regFabric(wallB, { name: 'north_wall', n: [0, 0, -1], box: fabBox(wallB),
                       room: 'kitchen' });
    /* west wall in two pieces + header: an open doorway into the
       mudroom at z 2.8..4.4 (architect pass — the kitchen looks through
       to the bench) */
    /* every west-wall piece goes in westWallG: the mudroom lives on the
       far side of it, so its camera hides the wall the way the garage
       hides its door — the dollhouse trick, one wall further in. */
    var westWallG = new T.Group();
    scene.add(westWallG);
    var wallL = box(0.35, 5.6, 4.05, C.wall, -6.65, 2.8, -3.475, westWallG,
                    sharp(WALL_O));
    var wallL1a = box(0.35, 5.6, 2.55, C.wall, -6.65, 2.8, 1.525, westWallG,
                      sharp(WALL_O));
    box(0.35, 2.4, 1.7, C.wall, -6.65, 4.4, -0.6, westWallG, sharp(WALL_O));
    var wallL1b = box(0.35, 5.6, 1.1, C.wall, -6.65, 2.8, 4.95, westWallG,
                      sharp(WALL_O));
    box(0.35, 2.2, 1.6, C.wall, -6.65, 4.5, 3.6, westWallG, sharp(WALL_O));
    if (DETAIL >= 2) {                   /* casing sells the opening */
      box(0.42, 3.5, 0.1, 0xe4ddd1, -6.65, 1.72, 2.82, westWallG, sharp());
      box(0.42, 3.5, 0.1, 0xe4ddd1, -6.65, 1.72, 4.38, westWallG, sharp());
      box(0.42, 0.1, 1.66, 0xe4ddd1, -6.65, 3.44, 3.6, westWallG, sharp());
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
    box(0.09, 5.6, 0.41, C.linen, 6.53, 2.8, -5.55, null, sharp(SECT));
    box(13.6, 0.28, 0.5, C.shell, 0, 5.66, -5.6, null, sharp());
    box(0.5, 0.28, 11.6, C.shell, -6.7, 5.66, 0, null, sharp());
    if (DETAIL >= 3) {                   /* baseboards: the trim that sells a wall */
      box(13, 0.2, 0.08, 0xe4ddd1, 0, 0.1, -5.34, null, sharp());
      box(0.08, 0.2, 4.0, 0xe4ddd1, -6.44, 0.1, -3.5, null, sharp());
      box(0.08, 0.2, 2.5, 0xe4ddd1, -6.44, 0.1, 1.5, null, sharp());
      box(0.08, 0.2, 1.0, 0xe4ddd1, -6.44, 0.1, 4.95, null, sharp());
    }

    /* ---- the GREAT ROOM extension (architect pass): the kitchen flows
       forward-left into a living room of its own scale — one open
       floorplan, one wood floor, no wall between. ---- */
    box(13.6, 0.5, 8.4, C.shell, 0, -0.27, 9.9, null, sharp());
    /* the slab's cut faces: the band the plates put under the floor */
    box(13.70, 0.50, 0.05, C.cabShade, 0, -0.27, 14.125, null, sharp({ rough: 0.9 }));
    box(13.70, 0.13, 0.09, C.stone, 0, -0.045, 14.140, null, sharp({ rough: 0.9 }));
    box(0.05, 0.50, 19.92, C.cabShade, 6.825, -0.27, 4.14, null, sharp({ rough: 0.9 }));
    box(0.09, 0.13, 19.92, C.stone, 6.840, -0.045, 4.14, null, sharp({ rough: 0.9 }));
    /* the LIVING plane: 13 x 8.5 at z 9.95, sampling only the top
       8.5/11 of its texture, so the canvas spans world z 3.2..14.2 -
       which is the range the pool bake is told about, and why the cool
       ring lands on the same world circle it does next door */
    var floorTex2 = pooledFloorTex(-6.5, 13, 3.2, 11.0);
    floorTex2.wrapS = floorTex2.wrapT = T.RepeatWrapping;
    floorTex2.repeat.set(1, 8.5 / 11);
    var floor2 = new T.Mesh(new T.PlaneGeometry(13, 8.5, 26, 18),
      PBR ? new T.MeshStandardMaterial({ map: floorTex2, roughness: 0.5,
                                         envMapIntensity: 0.1 })
          : new T.MeshLambertMaterial({ map: floorTex2 }));
    floor2.rotation.x = -Math.PI / 2;
    floor2.position.set(0, 0.004, 9.95);
    if (SHADOWS) floor2.receiveShadow = true;
    /* SHELL (spec section 4): living's own room tag — see floor's own
       comment above. floor (z -5.8..5.8) and floor2 (z 5.7..14.2) are
       already two separate PlaneGeometry meshes despite reading as one
       continuous wood floor, so tagging each with its own room is
       exactly what a room-footprint traversal needs to tell kitchen and
       living apart, with no hand-typed box for either. */
    floor2.userData.room = 'living';
    scene.add(floor2);
    var wallL2 = box(0.35, 5.6, 8.4, C.wall, -6.65, 2.8, 10.0, westWallG,
                     sharp(WALL_O));
    box(0.41, 5.6, 0.09, C.linen, -6.65, 2.8, 14.235, westWallG, sharp({ rough: 0.9 }));
    if (SHADOWS) wallL2.castShadow = false;
    box(0.5, 0.28, 8.6, C.shell, -6.7, 5.66, 10.1, null, sharp());
    if (DETAIL >= 3) box(0.08, 0.2, 8.2, 0xe4ddd1, -6.44, 0.1, 9.9, null, sharp());
    /* the front door: decorative — the house has a face; the LEAVE
       signal stays the mudroom door zone */
    var fdoor = new T.Mesh(
      NICE ? chamferGeo(0.14, 3.2, 1.4, 0.04) : new T.BoxGeometry(0.14, 3.2, 1.4),
      PBR ? new T.MeshStandardMaterial({ map: woodDoor, roughness: 0.65 })
          : new T.MeshLambertMaterial({ color: 0xc9a06c, map: woodDoor || null }));
    fdoor.position.set(-6.42, 1.6, 13.35);
    /* the front door belongs to the west wall: it hides with it, or it
       fills the mudroom camera from behind */
    /* VIEW-VOLUME MASKING (task 2): a plain or chamfered box, built
       directly (its material isn't box()'s mat() shape) -- still
       convex either way. */
    fdoor.userData.convex = true;
    finish(fdoor); westWallG.add(fdoor);
    /* R5: the plain knob becomes a lathe at the same position, rotated
       to protrude toward +x (into the room) — the same "protrude along
       the face's own outward axis" convention every other door's knob
       in the file already uses for ITS axis. A backplate sits just
       behind it and the kick plate at the base is the same chamfered-
       strip language R2 gave the range's kick strip. fdoor is
       decorative, not a zoneGroup, so all three stay shared (non-
       unique) materials and fold into westWallG's own merge pass. */
    latheAt('knob', [0.06, 0.1, 0.06], 0xd8c48a, -6.32, 1.6, 12.85, westWallG,
            CHROME).rotation.z = -Math.PI / 2;
    rbox(0.03, 0.30, 0.14, 0.015, 0xd8c48a, -6.34, 1.6, 12.85, westWallG,
         STEEL);
    box(0.03, 0.36, 1.10, C.ink, -6.335, 0.30, 13.35, westWallG,
        { rough: 0.85, ch: 0.010 });
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
      /* R1 (quality spec §4): the same PG-fallback convention as lb/lr/lc,
         for the K2 lathe/sweep kit. latheAt/sweepAt default their OWN
         group arg to `scene`, not PG - ll/ls close that gap so detail
         parts on wall-plane props (built-ins, hearth) still ride
         westWallG and hide with it under the mudroom camera. */
      function ll(key, s, c, x, y, z, g, o) { return ltag(latheAt(key, s, c, x, y, z, g || PG, o)); }
      function ls(pts, r, c, g, o) { return ltag(sweepAt(pts, r, c, g || PG, o)); }
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
        /* R1 (quality spec §4): pots are `vase` lathes on a `foot` ring now.
           GLOSS's flat glaze upgrades to K3's real ceramic clearcoat; the
           matte terracotta/stone pots keep their own opts untouched - the
           bible's "vary pot material" rule stays true prop to prop. */
        var pf = potO === GLOSS ? { finish: 'ceramic' } : potO;
        ll('vase', [s, ph, s], potC, x, y0, z, null, pf);
        ll('foot', [0.65 * s, 0.05 * s, 0.65 * s], potC, x, y0, z, null, pf);
        if (D3) lc(0.25 * s, 0.25 * s, 0.05, potC, x, y0 + ph - 0.015, z, null, 14, pf);
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
        var rx = -2.395, rz = 9.20, rw = 4.70, rd = 5.50;
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
        /* R1: the log bucket is a squashed `vase` lathe (a coal-scuttle
           silhouette, not a plain taper) - same footprint the cyl held:
           base on the hearth stone (y 0.22), radius/height matched. */
        ll('vase', [0.53, 0.30, 0.53], C.cork, WX + 0.62, 0.22, HZ - 1.02,
           null, { rough: 0.95 });
        lc(0.055, 0.055, 0.44, C.wood2, WX + 0.60, 0.62, HZ - 1.06, null, 8, WOODM);
        lc(0.055, 0.055, 0.38, C.wood2, WX + 0.66, 0.60, HZ - 0.98, null, 8, WOODM);
        lc(0.12, 0.14, 0.05, C.graphite, WX + 0.62, 0.245, HZ + 1.02, null, 10, STEEL);
        lc(0.02, 0.02, 0.66, C.graphite, WX + 0.62, 0.55, HZ + 1.02, null, 6, STEEL);
        /* R1: the fire-tool stand's post earns a `finial` cap, and the
           second bare rod becomes three short `sweepAt` tools (poker,
           tongs, brush) leaning out from it at floor level - the plain
           straight rod was one undifferentiated hint, not a set. */
        ll('finial', [0.15, 0.08, 0.15], C.graphite, WX + 0.62, 0.88,
           HZ + 1.02, null, STEEL);
        ls([[WX + 0.62, 0.78, HZ + 1.02], [WX + 0.615, 0.50, HZ + 0.97],
            [WX + 0.60, 0.26, HZ + 0.90]], 0.014, C.graphite, null, STEEL);
        ls([[WX + 0.62, 0.76, HZ + 1.02], [WX + 0.645, 0.48, HZ + 1.08],
            [WX + 0.66, 0.25, HZ + 1.16]], 0.014, C.graphite, null, STEEL);
        ls([[WX + 0.62, 0.74, HZ + 1.02], [WX + 0.66, 0.47, HZ + 1.03],
            [WX + 0.70, 0.25, HZ + 1.02]], 0.014, C.graphite, null, STEEL);
      }
      if (D2) {
        var fire = new T.Mesh(new T.BoxGeometry(0.04, 0.58, 0.92),
                              new T.MeshBasicMaterial({ color: 0xf2761c }));
        fire.position.set(WX + 0.320, 0.60, HZ);
        /* VIEW-VOLUME MASKING (task 2): plain boxes, built directly. */
        fire.userData.convex = true;
        ltag(fire); (PG || scene).add(fire);
        var emb = new T.Mesh(new T.BoxGeometry(0.06, 0.13, 0.86),
                             new T.MeshBasicMaterial({ color: 0xffc46a }));
        emb.position.set(WX + 0.335, 0.38, HZ);
        emb.userData.convex = true;
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
      /* R1: one subtle power cable, screen to soundbar - routed past the
         screen's right edge (0.62) AND the soundbar's (0.59) so it reads
         in the gap toward the mantle's corbel (1.08) instead of vanishing
         behind the screen's own proud face (probe-verified: z 0.52 sat
         fully behind the screen from the room camera; 0.75 clears it).
         D2-gated like the room's other fine cosmetic touches - a Pi's
         low tier shows the TV, not its wiring. */
      if (D2) ls([[WX + 0.50, 2.40, HZ + 0.75], [WX + 0.53, 2.12, HZ + 0.75],
                  [WX + 0.50, 1.95, HZ + 0.75]], 0.008, C.ink, null,
                 { rough: 0.6 });

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
        /* R1: the plinth shadow-gap - a thin ink strip proud of the toe
           kick's own lower edge, at the floor, so the recess actually
           reads dark instead of relying on AO alone below tier 3. */
        lb(0.40, 0.026, W0 - 0.13, C.ink, xc - 0.02, 0.013, bz, null,
           { rough: 0.92 });
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
            /* R1: a `knob` lathe pull, rotated so its stem-to-bulb axis
               (local +Y) points +X - straight out of the door face. */
            var kb = ll('knob', [0.07, 0.06, 0.07], C.graphite, F + 0.03,
              0.61, bz + (dz > 0 ? 0.10 : -0.10), null, STEEL);
            kb.rotation.z = -Math.PI / 2;
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
            D2 ? chamferGeo(w, h, d, r) : new T.BoxGeometry(w, h, d),
            mat(c, o || FAB));
          m.position.set(px, py, pz);
          m.userData.room = 'living';
          finish(m); g.add(m); return m;
        }
        /* R1: `foot` lathes - the pad-then-shaft turned silhouette - in
           place of the plain cylinder, same floor-to-0.16 footprint. */
        [[-DP / 2 + 0.16, -len / 2 + 0.18], [DP / 2 - 0.16, -len / 2 + 0.18],
         [-DP / 2 + 0.16, len / 2 - 0.18], [DP / 2 - 0.16, len / 2 - 0.18]]
          .forEach(function (lg) {
            var m = latheAt('foot', [0.12, 0.16, 0.12], C.wood2, lg[0], 0,
                            lg[1], g, WOODM);
            m.userData.room = 'living';
          });
        sb(DP, 0.20, len, 0.16, shade, 0, 0.26, 0);
        var cw = (len - 0.10) / nc, k;
        for (k = 0; k < nc; k++) {                       /* the 0.02 gap */
          sb(DP - 0.16, 0.22, cw - 0.02, 0.16, body, -0.04, 0.47,
             -len / 2 + 0.05 + cw * (k + 0.5));
        }
        if (D2) {          /* R1: seam piping along the seat cushions' front-
             top edge. The cushion's own chamfer caps at 0.49*halfHeight
             (~0.054, not the nominal 0.16 r passed to sb) - nudged 0.03
             proud on both axes so the trim clears the fillet instead of
             sitting embedded in it (probe-verified with a magenta debug
             pass, S5.2's trick: the line traced the seam exactly). `shade`
             (a same-hue deep tone) read as invisible against `body` at
             this radius - contrast piping in the room's existing dark
             neutral reads instead, and isn't a 5th accent hue (S2 keeps
             graphite out of the accent family). */
          var pipX = -0.04 - (DP - 0.16) / 2 - 0.03;
          var pipe = sweepAt([[pipX, 0.61, -len / 2 + 0.10], [pipX, 0.61, 0],
                              [pipX, 0.61, len / 2 - 0.10]], 0.015, C.graphite,
                             g, FAB);
          pipe.userData.room = 'living';
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
            D2 ? chamferGeo(w, h, d, r) : new T.BoxGeometry(w, h, d),
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
      /* The group stands OFF the hearth wall, not against it. A walkway
         runs between the hearth slab and the coffee table; the rug and
         everything standing on it moved east together, so the seating
         occupies the room instead of pinning itself to the stone. The
         sofa is the one piece still square on the hearth axis. */
      seat(-1.35, 8.70, 0, 2.95, C.sage, C.sageDeep, 3,
           [[-0.95, C.oxblood, 0.22], [0.95, C.terracotta, -0.24]]);
      /* BOTH armchairs face the COFFEE TABLE. Not the fire, not the TV,
         not the lens. seat() is built facing -x, so each pose is exactly
         atan2(dz, -dx) of the chair-to-table-centre vector, table centre
         (-3.25, 8.95). Recompute both if the table ever moves. */
      seat(-3.10, 7.22, 1.4843, 1.12, C.terracotta, C.terraDeep, 1,
           [[0.0, C.cream, -0.20]], 1.14);
      seat(-3.85, 10.60, -1.9206, 1.12, C.terracotta, C.terraDeep, 1,
           [[0.0, C.cream, 0.20]], 1.14);

      /* a console behind the sofa, facing the kitchen half of the great
         room - the piece that keeps the east floor from reading bare */
      (function () {
        var SX = -0.52, SZ = 8.70;
        [-1.10, 1.10].forEach(function (dz) {
          lc(0.045, 0.038, 0.30, C.wood2, SX - 0.14, 0.15, SZ + dz, null, 8, WOODM);
          lc(0.045, 0.038, 0.30, C.wood2, SX + 0.14, 0.15, SZ + dz, null, 8, WOODM);
        });
        lr(0.40, 0.50, 2.44, 0.04, woodK, SX, 0.55, SZ, null, woodO);
        lb(0.46, 0.06, 2.56, C.slate, SX, 0.83, SZ, null, { rough: 0.5 });
        if (D2) {
          lb(0.03, 0.34, 1.04, C.cab, SX + 0.20, 0.55, SZ - 0.56);
          lb(0.03, 0.34, 1.04, C.cab, SX + 0.20, 0.55, SZ + 0.56);
          /* R1 (TV/console row): `knob` lathe pulls replace the flat bars */
          [-0.56, 0.56].forEach(function (dz) {
            var kn = ll('knob', [0.07, 0.06, 0.07], C.graphite, SX + 0.21,
              0.55, SZ + dz, null, STEEL);
            kn.rotation.z = -Math.PI / 2;
          });
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
      lr(1.70, 0.10, 1.20, 0.03, woodK, -3.25, 0.55, 8.95, null, woodO);
      /* R1: `foot` lathes for the legs - same floor-to-tabletop span. */
      [[-3.93, 8.45], [-2.57, 8.45], [-3.93, 9.45], [-2.57, 9.45]]
        .forEach(function (p) {
          ll('foot', [0.13, 0.50, 0.13], C.wood2, p[0], 0, p[1], null, WOODM);
        });
      if (D2) {
        lb(1.44, 0.05, 0.96, woodK, -3.25, 0.26, 8.95, null, woodO);
        lb(0.30, 0.055, 0.22, C.oxblood, -3.60, 0.315, 8.95);
        lb(0.28, 0.05, 0.20, C.cream, -3.60, 0.368, 8.96);
        lc(0.20, 0.22, 0.16, C.cork, -2.85, 0.365, 8.95, null, 12, { rough: 0.9 });
        lr(0.44, 0.035, 0.32, 0.02, C.brass, -2.79, 0.62, 9.32, null, STEEL);
        /* R1: the tray's two cups become a `plate`+`cup` lathe pair, ceramic -
           the coffee-table dressing the part list names explicitly. */
        ll('plate', [0.20, 0.025, 0.20], C.cream, -2.79, 0.6375, 9.32, null,
           { finish: 'ceramic' });
        ll('cup', [0.125, 0.07, 0.125], C.cream, -2.74, 0.6625, 9.32, null,
           { finish: 'ceramic' });
      }
      if (D3) {
        lc(0.06, 0.06, 0.11, C.cream, -3.83, 0.66, 9.32, null, 10, GLOSS);
        lb(0.22, 0.05, 0.30, C.sage, -3.83, 0.625, 8.62);
      }
      blobShadow(0.9, 0.68, -3.25, 8.95);

      /* ================= 6. a lamp table at the sofa's north end ======= */
      lr(0.62, 0.07, 0.62, 0.02, woodK, -1.75, 0.71, 6.72, null, woodO);
      lc(0.06, 0.06, 0.70, C.wood2, -1.75, 0.35, 6.72, null, 8, WOODM);
      lc(0.24, 0.26, 0.05, C.wood2, -1.75, 0.03, 6.72, null, 12, WOODM);
      if (D2) {
        lc(0.14, 0.10, 0.34, C.terracotta, -1.82, 0.92, 6.72, null, 12, GLOSS);
        var shd = new T.Mesh(new T.CylinderGeometry(0.17, 0.25, 0.26, 14, 1, true),
          PBR ? new T.MeshStandardMaterial({ color: 0xf3e8d2, roughness: 0.8,
                                             emissive: 0xffd9a0, emissiveIntensity: 0.35,
                                             side: T.DoubleSide })
              : new T.MeshLambertMaterial({ color: 0xf3e8d2, side: T.DoubleSide }));
        shd.position.set(-1.82, 1.24, 6.72);
        ltag(shd); finish(shd, true); scene.add(shd);
        lb(0.22, 0.05, 0.16, C.slate, -1.60, 0.77, 6.56);
        lb(0.21, 0.045, 0.15, C.brass, -1.60, 0.818, 6.57);
      }
      blobShadow(0.36, 0.36, -1.75, 6.72);

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
          /* R1 (TV/console row): `knob` lathe pull replaces the flat bar */
          var kg = ll('knob', [0.07, 0.06, 0.07], C.graphite, WX + 0.54,
            0.60, CZ + dz, null, STEEL);
          kg.rotation.z = -Math.PI / 2;
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
        var rug = new T.Mesh(new T.CircleGeometry(1.45, D3 ? 28 : 16),
                             mat(C.linen, { rough: 1.0 }));
        rug.rotation.x = -Math.PI / 2;
        rug.position.set(2.00, 0.048, 9.85);
        if (SHADOWS) rug.receiveShadow = true;
        ltag(rug); scene.add(rug);
        if (D2) {
          var ring = new T.Mesh(new T.RingGeometry(1.22, 1.34, 28),
                                mat(C.sageDeep, { rough: 1.0 }));
          ring.rotation.x = -Math.PI / 2;
          ring.position.set(2.00, 0.054, 9.85);
          ltag(ring); scene.add(ring);
        }
      })();
      lightChair(1.48, 9.88, 0.55, C.sage, C.oxblood);
      /* the floor lamp: base, stem, shade. All of it is D2 - a bare pole
         with no shade at the low tier reads as broken geometry. */
      if (D2) {
        /* R1 (part list): `foot` lathe base, `sweepAt` arm at the old
           stem's own endpoints (a gentle bow, not a right-angle reading
           arm - the shade never moves), `shade` lathe at the head. The
           shade keeps its own emissive material (mat() has no emissive
           vocabulary) so the lit-from-within read survives the upgrade. */
        ll('foot', [0.65, 0.07, 0.65], C.brass, 0.90, 0, 10.90, null, STEEL);
        ls([[0.90, 0.07, 10.90], [0.94, 0.85, 10.90], [0.90, 1.65, 10.90]],
           0.032, C.brass, null, STEEL);
        var lsh2 = new T.Mesh(latheGeo('shade'),
          PBR ? new T.MeshStandardMaterial({ color: 0xf3e8d2, roughness: 0.8,
                                             emissive: 0xffd9a0, emissiveIntensity: 0.45,
                                             side: T.DoubleSide })
              : new T.MeshLambertMaterial({ color: 0xf3e8d2, side: T.DoubleSide }));
        lsh2.scale.set(0.68, 0.34, 0.68);
        lsh2.position.set(0.90, 1.65, 10.90);
        ltag(lsh2); finish(lsh2, true); scene.add(lsh2);
      }
      blobShadow(0.32, 0.32, 0.90, 10.90);
      /* the side table: pedestal, base, top, three props */
      lc(0.44, 0.44, 0.07, woodK, 2.46, 0.62, 10.40, null, 16, woodO);
      lc(0.065, 0.065, 0.58, C.wood2, 2.46, 0.30, 10.40, null, 10, WOODM);
      lc(0.26, 0.28, 0.05, C.wood2, 2.46, 0.03, 10.40, null, 14, WOODM);
      if (D2) {
        lb(0.28, 0.055, 0.20, C.slate, 2.36, 0.683, 10.32);
        lb(0.26, 0.05, 0.19, C.brass, 2.36, 0.735, 10.33);
        lc(0.085, 0.075, 0.14, C.cream, 2.63, 0.725, 10.52, null, 10, GLOSS);
      }
      blobShadow(0.4, 0.4, 2.46, 10.40);
      /* a pouf bridging the two zones */
      lr(0.66, 0.36, 0.66, 0.17, C.terracotta, -0.10, 0.20, 10.30, null, FAB);
      if (D3) lb(0.60, 0.02, 0.60, C.terraDeep, -0.10, 0.385, 10.30, null, FAB);
      blobShadow(0.38, 0.38, -0.10, 10.30);
      /* a basket and a stack of books beside the reading chair */
      lc(0.26, 0.22, 0.34, C.cork, 0.18, 0.17, 9.05, null, 12, { rough: 0.95 });
      if (D2) lc(0.27, 0.27, 0.05, C.sage, 0.18, 0.36, 9.05, null, 12, FAB);
      blobShadow(0.28, 0.28, 0.18, 9.05);
      /* a stack of books on the floor beside the chair */
      if (D2) {
        lb(0.34, 0.06, 0.26, C.oxblood, 1.42, 0.03, 10.78);
        lb(0.33, 0.055, 0.25, C.cream, 1.42, 0.088, 10.79);
        if (D3) lb(0.31, 0.055, 0.24, C.sage, 1.43, 0.143, 10.77);
      }

      /* a lidded basket of blankets and a floor stack: the rug's south
         half was bare plank in round 3 */
      lc(0.30, 0.26, 0.42, C.cork, -3.20, 0.21, 11.45, null, 14, { rough: 0.95 });
      if (D2) {
        lc(0.31, 0.31, 0.05, C.rugB, -3.20, 0.44, 11.45, null, 14, FAB);
        lr(0.34, 0.16, 0.34, 0.07, C.sage, -3.20, 0.53, 11.45, null, FAB);
      }
      blobShadow(0.33, 0.33, -3.20, 11.45);
      if (D2) {
        lc(0.09, 0.09, 0.46, C.wood2, -1.55, 0.23, 11.05, null, 10, WOODM);
        lc(0.34, 0.34, 0.06, woodK, -1.55, 0.48, 11.05, null, 16, woodO);
        lc(0.24, 0.26, 0.04, C.wood2, -1.55, 0.02, 11.05, null, 12, WOODM);
        lb(0.24, 0.05, 0.18, C.oxblood, -1.61, 0.535, 10.99);
        lc(0.075, 0.065, 0.13, C.brass, -1.43, 0.575, 11.13, null, 10, STEEL);
        blobShadow(0.3, 0.3, -1.55, 11.05);
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

    var groups = {}, studyWorld = null;
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
    var kPullStyle = 'box';             /* 'lathe' on the island run only */
    function kPull(g, x, y, zf, len, vert) {
      if (!KD2) return;
      var t = 0.028;
      if (kPullStyle === 'lathe') {
        /* R2 (island): the `pull` PROFILE is a turned bar — lathed on its
           natural Y axis for a vertical door pull, laid on its side (the
           same rotate-to-protrude trick R1 used on `knob`) for a
           horizontal drawer pull. Same x/y/zf/len every box pull used.
           Final-fix wave: latheAt grows a profile UP from the given y —
           base-pivot — where the box bar it replaced was CENTRE-pivot, so
           the bar landed off by len/2 from where the box bar (and KD3's
           stand-offs below, which still assume a centred bar) sat: shifted
           up for a vertical pull, and shifted left for a horizontal one
           (rotation.z lays local +y along world -x). Offsetting the
           lathe's position by len/2 along the bar's own axis — down for
           vertical, right for horizontal — re-centres it exactly on the
           stand-offs, same as every other lathe conversion in this arc. */
        var pm = latheAt('pull', [0.030, len, 0.030], HW,
                         vert ? x : x + len / 2, vert ? y - len / 2 : y,
                         zf + 0.055, g, STEEL);
        if (!vert) pm.rotation.z = Math.PI / 2;
      } else {
        box(vert ? t : len, vert ? len : t, t, HW, x, y, zf + 0.055, g, STEEL);
      }
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
      kPullStyle = opt.pull || 'box';
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
    /* R2: K2 profiles replace the cyl stand-ins, 1:1 by call site — every
       (x,y,z,r,h) literal at every call site is unchanged (the function's
       own `y` was always a BASE, matching latheAt's own base-pivot), only
       the body each one builds. jar: K3 glassy (the pantry's own recipe,
       §K3); lid stays brass/STEEL, same as the cyl lid it replaces. */
    var KJAR_GLASS = { finish: 'glassy', thick: 0.1 };
    var KCERAMIC = { finish: 'ceramic' };
    function kJar(g, x, y, z, r, h, c) {
      latheAt('jar', [r / 0.40, h, r / 0.40], c, x, y, z, g, KJAR_GLASS);
      if (KD3) latheAt('lid', [r * 0.85 / 0.37, h * 0.12, r * 0.85 / 0.37],
                       HW, x, y + h, z, g, STEEL);
    }
    function kBowl(g, x, y, z, r, c) {
      latheAt('bowl', [r / 0.50, Math.max(0.10, r * 0.8), r / 0.50], c,
              x, y, z, g, KCERAMIC);
    }
    function kPlates(g, x, y, z, r, c) {
      var ph = 0.030;
      for (var k = 0; k < (KD3 ? 4 : 2); k++)
        latheAt('plate', [r / 0.50, ph, r / 0.50], c, x,
                y + k * (ph + 0.008), z, g, KCERAMIC);
    }
    function kCups(g, x, y, z, n, c) {
      for (var k = 0; k < n; k++)
        latheAt('cup', [0.16, 0.11, 0.16], c, x + k * 0.135, y, z, g, KCERAMIC);
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
      /* raw mat() call, not routed through box/rbox/cyl: kPlant(winG, ...)
         (the window sill's plant) hands g=winG, a zone group, so this must
         thread the same L1 valve those helpers do or the leaf-green
         material leaks into every other plant in the house (L1 break). */
      var m = new T.Mesh(new T.SphereGeometry(r, KD3 ? 10 : 6, KD3 ? 8 : 4),
                         mat(c, { rough: 1.0 }, inZoneGroup(g || scene)));
      m.position.set(x, y, z);
      if (sy) m.scale.y = sy;
      finish(m); (g || scene).add(m); return m;
    }
    function kLeaf(g, x, base, z, L, wide, thick, tilt, spin, c) {
      var m = new T.Mesh(new T.SphereGeometry(1, KD3 ? 10 : 6, KD3 ? 8 : 4),
                         mat(c, { rough: 1.0 }, inZoneGroup(g || scene)));
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
    /* L (quality spec §5): per-run counter grain, cached by run id - the
       sink run (A) breaks around the apron sink into two physical slabs
       that still share ONE canvas/material, same idiom as the wall's
       WALL_O above. Same grain painter as woodLight (streaks + fine
       noise) plus a centre-brighter pool: `len` only sizes the streak
       count so a short run and a long run read the same GRAIN DENSITY
       instead of one stretched thin. The pool sits at the run's own
       centre - for run A that centre (x -1.8ish) lands within a few
       tenths of the island pendant's x (0.4, see poolLamps), which is
       the one run actually standing under an overhead light; B and L
       get the same treatment for consistency (bible S4's "warm patches
       on... counters" reads as one family, not one lit counter and two
       flat ones). */
    var counterTexCache = {};
    function counterTex(run, len) {
      var t = counterTexCache[run];
      if (!t) {
        t = counterTexCache[run] = canvasTex(128, function (g, S) {
          g.fillStyle = '#c89a66'; g.fillRect(0, 0, S, S);
          var n = Math.max(14, Math.round(len * 13));
          for (var i = 0; i < n; i++) {
            g.strokeStyle = 'rgba(90,60,30,' + (0.10 + Math.random() * 0.22) + ')';
            g.lineWidth = 1 + Math.random() * 3;
            var a = Math.random() * S, wob = (Math.random() - 0.5) * 22;
            g.beginPath();
            g.moveTo(-10, a);
            g.bezierCurveTo(S * 0.33, a + wob, S * 0.66, a - wob, S + 10, a);
            g.stroke();
          }
          for (var j = 0; j < 400; j++) {
            g.fillStyle = 'rgba(60,40,20,' + (Math.random() * 0.05) + ')';
            g.fillRect(Math.random() * S, Math.random() * S, 2, 2);
          }
          var rg = g.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S * 0.6);
          rg.addColorStop(0, 'rgba(255,238,208,0.08)');    /* +8%, warm */
          rg.addColorStop(1, 'rgba(255,238,208,0)');
          g.fillStyle = rg; g.fillRect(0, 0, S, S);
        });
      }
      return t;
    }
    /* countertops: a slab that overhangs the fronts by 0.05 (S3.1.6).
       `run` is the same A/B/L-return grouping the AO occluder list
       already names (K4, below) - two physical slabs can share one run
       and one baked texture without sharing a bounding box. */
    function kTop(w, d, x, z, run) {
      var ctex = NICE ? counterTex(run, Math.max(w, d)) : null;
      var m = new T.Mesh(
        /* Fix round 1 (finding 5): the chamfered branch was already
           cached (chamferGeo() is cgeo() underneath), but this plain
           BoxGeometry branch built a unique geometry every call - the
           same key-discipline gap box() itself avoids two screens up.
           Routed through cgeo() with box()'s own 'b|w|h|d' key scheme
           for consistency; no dedup expected today (the four kTop
           slabs' w/d all differ), but a future slab that happens to
           match another's dimensions now shares a buffer instead of
           silently getting its own. */
        NICE ? chamferGeo(w, CT_T, d, 0.02)
             : cgeo('b|' + w + '|' + CT_T + '|' + d, function () {
                 return new T.BoxGeometry(w, CT_T, d);
               }),
        /* R2 (tier fix), preserved: kWoodK is white at NICE (the map
           carries the colour) and the low-tier tan below it - mat()'s
           own Lambert branch already applies that rule, so routing
           through the shared cache (instead of a hand-rolled Mesh
           literal, the pre-L11 shape) gets it for free. */
        mat(kWoodK, { rough: 0.42, envInt: 0.35, map: ctex }));
      m.position.set(x, CT_Y - CT_T / 2, z);
      finish(m); scene.add(m); return m;
    }
    /* the worktop breaks either side of the apron sink: a counter that
       runs THROUGH the bowl leaves the basin a tray sitting on top */
    kTop(1.77, 1.49, -3.665, NZ + 0.745, 'A');
    kTop(1.88, 1.49, -0.040, NZ + 0.745, 'A');
    kTop(2.40, 1.49, 3.70, NZ + 0.745, 'B');
    kTop(0.80, 1.40, WXK + 0.400, -2.20, 'L');
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
    /* the calendar used to hang here, beside the range. It moved to the
       west wall (user ruling 2026-09-09) and open shelving took the gap —
       plates 7 and 9 are half open shelving, and a blank patch of tile
       beside a hood is the one thing a real kitchen never has. */
    kCase(3.78, NZ + 0.25, 0, 2.00, 0.50, UP_Y0, UP_Y1, [
      { h: 1.83, kind: 'bays', bays: 2, tiers: 3, depth: 0.48 }
    ]);
    /* crown: the ceiling-to-upper gap gets filled (S1) */
    if (KD2) {
      box(1.62, 0.10, 0.60, C.cab, -3.75, UP_Y1 + 0.05, NZ + 0.30);
      box(1.70, 0.10, UP_D + 0.08, C.cab, 0.01, UP_Y1 + 0.05, NZ + UP_D / 2 + 0.04);
      box(2.12, 0.10, 0.60, C.cab, 3.78, UP_Y1 + 0.05, NZ + 0.30);
      box(2.06, 0.07, 0.52, C.cabShade, 3.78, UP_Y1 + 0.135, NZ + 0.28);
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
      /* R2: the faucet becomes a proper sweepAt gooseneck — a riser and a
         curved arc down to the spout in ONE tube, replacing the riser +
         angled-cylinder "neck" + spout-tip cyl (3 meshes -> 1 sweep). The
         base point matches the old riser's own foot (SX, CT_Y, NZ+0.30). */
      sweepAt([[SX, CT_Y + 0.02, NZ + 0.30], [SX, CT_Y + 0.46, NZ + 0.30],
               [SX, CT_Y + 0.64, NZ + 0.47], [SX, CT_Y + 0.60, NZ + 0.64],
               [SX, CT_Y + 0.39, NZ + 0.72]], 0.032, C.steel, null, CHROME);
      cyl(0.05, 0.02, 0.04, C.steel, SX, CT_Y + 0.29, NZ + 0.72, null, 8, CHROME);
      /* twin knob handles flanking the riser (part list), deck-mounted —
         replaces the single lever the apron-sink faucet had. Sized up
         once already (probe-verified: 0.045 chrome-on-white deck read as
         two pale flecks, same low-contrast lesson as the range knobs, but
         a chrome faucet earns chrome handles, so size carries this one
         instead of a colour swap). */
      [-0.32, 0.32].forEach(function (hx) {
        latheAt('knob', [0.065, 0.14, 0.065], C.steel, SX + hx, CT_Y + 0.02,
                NZ + 0.26, null, CHROME);
      });
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
    var paneMesh = textMesh(new T.BoxGeometry(1.9, 1.7, 0.06),
      new T.MeshBasicMaterial({ color: 0xffffff }), winG);
    paneMesh.position.set(0, 3.4, 0.06);
    if (SHADOWS) paneMesh.castShadow = false;
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
    /* R2: a latch knob at the meeting rail (part list); sill chamfer
       already arrives free (K1's default box ch, no override here) */
    if (KD2) {
      var latch = latheAt('knob', [0.045, 0.05, 0.045], HW, 0, 2.62, 0.13,
                          winG, STEEL);
      latch.rotation.x = Math.PI / 2;
    }
    if (KD2) {
      /* the sill's LEFT end stays clear: the temperature is painted into
         the pane's bottom-left corner, and a plant there hid it. Moving the
         reading was the wrong fix — it only walked into the lean-in card.
         Move the thing doing the blocking, not the signal. */
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
    /* R2 (part list): 5 knob dials along the control rail just built.
       C.graphite, not C.steel — a steel knob on the strip's own C.steel
       read as a bump with no edge (probe-verified: invisible past arm's
       length). Graphite against the chrome strip is the same trick the
       hood's dark canopy plays against its own brass banding. */
    [-0.44, -0.22, 0, 0.22, 0.44].forEach(function (kx) {
      var kn = latheAt('knob', [0.048, 0.05, 0.048], C.graphite, kx, 0.86,
                       0.825, counter, STEEL);
      kn.rotation.x = Math.PI / 2;
    });
    /* the oven door's own pull — a full-width sweepAt bar, proud of the
       body's front face (0.725) the way the fridge's D-pulls are proud of
       its doors */
    sweepAt([[-0.48, 0.38, 0.735], [-0.48, 0.38, 0.775],
             [0.48, 0.38, 0.775], [0.48, 0.38, 0.735]],
            0.020, C.steel, counter, CHROME);
    /* 2 hinge caps, just outside the pull's own ends — grouping them with
       the hardware they hang beside is what makes them read as hinges and
       not stray dots (probe-verified: at the door's true bottom corner,
       against the kick strip's own shadow, they vanished) */
    [-0.50, 0.50].forEach(function (hx) {
      latheAt('hinge', [0.040, 0.06, 0.040], C.steel, hx, 0.15, 0.735,
              counter, STEEL);
    });
    /* a chamfered kick strip — the existing floor pad below (y 0.035,
       z ±0.66) sits entirely behind the body's own front face (0.725) and
       never reads; this one sits AT the face, like the fridge's plinth */
    box(1.30, 0.06, 0.05, C.ink, 0, 0.05, 0.70, counter, { rough: 0.85, ch: 0.012 });
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
      /* the chimney stands on the canopy's own axis and its own top
         footprint, or the duct reads as bolted on crooked. The canopy is a
         4-segment cylinder turned 45 degrees, so its top SIDE is the
         circumradius times root two — 0.556 * 1.414 = 0.786 in x, and
         0.672 of that in z where the group is squashed. It was 0.76 x 0.46
         centred 0.30 nearer the wall than the canopy it sits on, so the
         two met only across part of their depth. */
      box(0.79, 1.44, 0.53, C.ink, 0, HY0 + 1.440, WZ + 0.53, counter,
          { rough: 0.45 });
      if (KD2) {
        box(0.83, 0.05, 0.57, HW, 0, HY0 + 0.750, WZ + 0.53, counter, STEEL);
        box(0.83, 0.05, 0.57, HW, 0, HY0 + 2.110, WZ + 0.53, counter, STEEL);
      }
      /* the underside is not the same black.
         L (tier fix, same family as kTop's R2 fix): the Lambert branch
         used to hardcode a lighter, greyer 0x4a5158 with no emissive at
         all - MeshLambertMaterial supports emissive same as Standard,
         so the medium/low hood underside was going through a real
         colour change (grey vs charcoal) instead of a fidelity drop.
         One authored charcoal now, every tier - that fix is real and
         it is what survives to the screen.
         Fix round 1 (finding 3, corrected): "a lit hood glows" does
         NOT survive to the screen. `und` lives in the `counter` zone
         group, and applyState's live-zone sweep (search "the live-zone
         glow" below) walks every mesh in that group on EVERY call and
         unconditionally setHex()s .emissive to 0x120c03 (zone active)
         or 0x000000 (zone calm) - in BOTH branches, on every tier,
         regardless of whatever was authored here. The emissive pair
         below (0xffca7a @ 0.16) can never render under any zone
         state; it exists only so the two material branches read as
         the same authored intent in source, matching PBR's emissive
         to Lambert's rather than leaving Lambert bare. */
      var und = new T.Mesh(new T.PlaneGeometry(LIPW - 0.16, LIPD - 0.16),
        PBR ? new T.MeshStandardMaterial({ color: 0x30363c, roughness: 0.6,
                                           emissive: 0xffca7a,
                                           emissiveIntensity: 0.16 })
            : new T.MeshLambertMaterial({ color: 0x30363c,
                                          emissive: 0xffca7a,
                                          emissiveIntensity: 0.16 }));
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
      NICE ? chamferGeo(1.9, 3.95, 1.5, 0.08) : new T.BoxGeometry(1.9, 3.95, 1.5),
      PBR ? new T.MeshStandardMaterial({ map: brushed, color: 0xdadee2,
                                         roughness: 0.3, metalness: 0.8,
                                         envMapIntensity: 1.1 })
          : new T.MeshLambertMaterial({ color: 0xd7dbdf, map: brushed || null }));
    fbody.position.set(0, 1.97, 0);
    finish(fbody); fridge.add(fbody);
    var fridgeDoorTop = rbox(1.6, 1.55, 0.07, 0.03, C.teal, 0, 2.95, 0.77, fridge,
         { finish: 'enamel' });
    rbox(1.6, 1.35, 0.07, 0.03, C.teal, 0, 1.02, 0.77, fridge,
         { finish: 'enamel' });
    /* R2: the spike's variant C, shipped for real. sweepAt D-pulls replace
       the two box handle bars — same x and the same y-span each one had. */
    [[2.95, 0.65], [1.07, 0.50]].forEach(function (p) {
      sweepAt([[0.62, p[0] - p[1], 0.80], [0.62, p[0] - p[1], 0.92],
               [0.62, p[0] + p[1], 0.92], [0.62, p[0] + p[1], 0.80]],
              0.028, C.steel, fridge, CHROME);
    });
    /* 4 hinges, the west edge — opposite the pulls, top and bottom of
       each door */
    [3.68, 2.22, 1.65, 0.40].forEach(function (hy) {
      latheAt('hinge', [0.045, 0.09, 0.045], C.steel, -0.83, hy, 0.79,
              fridge, STEEL);
    });
    /* 4 feet, one per corner */
    [[-0.80, -0.62], [0.80, -0.62], [-0.80, 0.62], [0.80, 0.62]]
      .forEach(function (fp) {
        latheAt('foot', [0.12, 0.09, 0.12], C.graphite, fp[0], 0, fp[1],
                fridge, STEEL);
      });
    /* the maker's badge, lower-left of the top door, clear of the pull */
    var badge = latheAt('plate', [0.045, 0.012, 0.045], HW, 0.28, 2.35,
                        0.807, fridge, STEEL);
    badge.rotation.x = Math.PI / 2;
    /* door gasket frames: 4 thin ch strips per door, inset from its edge */
    [[2.95, 1.55], [1.07, 1.35]].forEach(function (dp) {
      var cy = dp[0], hh = dp[1] / 2 - 0.035;
      [cy - hh, cy + hh].forEach(function (ry) {
        box(1.53, 0.03, 0.012, C.ink, 0, ry, 0.808, fridge,
            { rough: 0.9, ch: 0.006 });
      });
      [-0.765, 0.765].forEach(function (rx) {
        box(0.03, dp[1] - 0.07, 0.012, C.ink, rx, cy, 0.808, fridge,
            { rough: 0.9, ch: 0.006 });
      });
    });
    if (DETAIL >= 2)                    /* a plinth: appliances have feet */
      box(1.72, 0.13, 0.06, C.graphite, 0, 0.065, 0.72, fridge, { rough: 0.6 });
    var magnets = new T.Group();
    magnets.position.set(0, 0, 0.85);
    fridge.add(magnets);
    blobShadow(1.15, 0.9, -5.55, -4.35);

    /* ---- CORKBOARD (zone: board) on the left wall ---------------------- */
    var board = zoneGroup('board', -6.42, 0, -0.6);
    /* The pantry is an open, cased doorway like the mudroom transition.
       Its shelves stay legible in the room view; the invisible face keeps
       the whole opening as the pantry tap target. */
    var boardFace = new T.Mesh(new T.PlaneGeometry(1.6, 3.0),
      new T.MeshBasicMaterial({ visible: false }));
    boardFace.rotation.y = Math.PI / 2;
    boardFace.position.set(0.26, 1.7, 0);
    board.add(boardFace);
    var pantryDoor = null;
    if (DETAIL >= 2) {
      /* Casing grounds the opening even when the pantry card is absent. */
      box(0.22, 3.36, 0.14, 0xe4ddd1, 0.16, 1.68, -0.87, board);
      box(0.22, 3.36, 0.14, 0xe4ddd1, 0.16, 1.68, 0.87, board);
      box(0.22, 0.14, 1.88, 0xe4ddd1, 0.16, 3.29, 0, board);
    }
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
        zoneTag(sh, 'board');
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
        if (m) { zoneTag(m, 'board', 'kitchen'); }
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
    var pantryLids = [];
    (function () {
      /* the kitchen's four accents, no strays (bible S2/S4) */
      var JAR_C = [C.terracotta, C.oxblood, C.teal, C.brass];
      /* K3: a private opts literal, not GLOSS — GLOSS is a shared constant
         read by ~95 other call sites, and glassy ignores rough/metal/envInt
         anyway (its own alpha-glass recipe in makeMat), so nothing of
         GLOSS's intent carries over. jar.visible count semantics (below, in the
         webgl runtime) are untouched by this — only the material changes. */
      var JAR_GLASS = { finish: 'glassy', thick: 0.1 };
      var JR = 0.1, JH = 0.26;
      for (var j = 0; j < 8; j++) {
        var jy = j < 4 ? 1.06 : 1.86;
        var jar = cyl(JR, JR, JH, JAR_C[j % 4],
                      -1.53, jy, -1.06 + (j % 4) * 0.48, board, 10, JAR_GLASS);
        zoneTag(jar, 'board');
        pantryJars.push(jar);
        /* R3: a brass lid, CHILD of the jar mesh (not a sibling in
           `board`) — the stock toggle below sets jar.visible per item, and
           parenting the lid means it hides for free through three's
           parent-visibility cascade instead of a second parallel index to
           keep in sync. Same recipe kJar already uses for the kitchen's
           own shelf jars (r*0.85/0.37, h*0.12); local to the jar's own
           centre-pivot origin, so y=JH/2 sits the lid's base on its top.
           S4/S7 name jar lids as the DETAIL>=3 example — gated to match. */
        if (DETAIL >= 3)
          pantryLids.push(latheAt('lid',
            [JR * 0.85 / 0.37, JH * 0.12, JR * 0.85 / 0.37],
            HW, 0, JH / 2, 0, jar, STEEL));
      }
    })();
    /* ---- WALL CALENDAR (zone: calendar) on the back wall --------------- */
    /* The family calendar hangs on the WEST wall panel between the pantry
       door and the mudroom doorway (user ruling 2026-09-09) — the wall you
       pass on the way out, which is where a household actually puts it. It
       rides westWallG so the mudroom camera cuts it away with the wall it
       hangs on, exactly as the TV and the built-ins do. */
    var calG = zoneGroup('calendar', WXK, 0, 1.52);
    calG.rotation.y = Math.PI / 2;      /* face east, into the great room */
    westWallG.add(calG);
    /* L1: lands straight on calG (a zone group) with no zoneTag wrapper
       after it, so the cache must be forced unique right here. */
    var calFace = textMesh(new T.PlaneGeometry(1.5, 1.9),
                           mat(0xf6f1e4, { rough: 0.9 }, true));
    /* VIEW-VOLUME MASKING (task 2): a flat rectangle is a degenerate
       convex polygon -- worldTris/clipConvex handle it the same as any
       other convex solid's faces. Its map texture is repainted over
       time, but the geometry (and this stamp) never changes. */
    calFace.userData.convex = true;
    calFace.position.set(0, 2.50, 0.05);
    calG.add(calFace);
    box(1.62, 0.1, 0.08, C.oxblood, 0, 3.50, 0.02, calG, GLOSS);
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
      NICE ? chamferGeo(1.7, 4.1, 0.14, 0.04) : new T.BoxGeometry(1.7, 4.1, 0.14),
      PBR ? new T.MeshStandardMaterial({ map: woodDoor, roughness: 0.65 })
          : new T.MeshLambertMaterial({ color: 0xc9a06c, map: woodDoor || null }));
    slabD.position.set(0, 2.05, 0);
    /* VIEW-VOLUME MASKING (task 2): a plain or chamfered box, built
       directly -- convex either way, same as fdoor above. */
    slabD.userData.convex = true;
    finish(slabD); doorG.add(slabD);
    if (DETAIL >= 2) {
      box(1.3, 1.2, 0.05, 0x8a6d49, 0, 1.2, 0.08, doorG, PBR ? { rough: 0.7, map: woodDoor } : { rough: 0.75 });
      /* R3: rails/stiles relief — the frame above is now the surround;
         this inset panel, proud and lighter (dpart's own street-face
         recipe below), is the field it frames (S3.1's two-panel minimum) */
      box(1.14, 1.02, 0.03, 0xc79b63, 0, 1.2, 0.095, doorG,
          PBR ? { rough: 0.65, map: woodDoor, ch: 0.008 } : { rough: 0.70, ch: 0.008 });
    }
    /* R3: knob handle upgrade to lathe — same position and the same
       protrude-toward-camera rotation dpart's street-face knob already
       uses below; only the plain cylinder becomes the turned profile */
    latheAt('knob', [0.07, 0.1, 0.07], 0xd8c48a, 0.6, 2.0, 0.1, doorG, CHROME)
      .rotation.x = Math.PI / 2;
    /* the next-leave HERO CARD, rendered app-style, big enough to read
       from across the room — it hangs on the door because the door is
       where leaving happens */
    var plaque = textMesh(new T.PlaneGeometry(1.5, 0.94),
      new T.MeshBasicMaterial({ transparent: true }), doorG);
    plaque.position.set(0, 3.02, 0.1);

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
    ], { toe: true, face: 0x6f5540, body: 0x584129, pull: 'lathe' });
    var islandTop = new T.Mesh(
      NICE ? chamferGeo(3.74, CT_T, 2.34, 0.03) : new T.BoxGeometry(3.74, CT_T, 2.34),
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
            /* R2 (tier fix): kWoodK, not the low-tier flat tan — see kTop */
            : new T.MeshLambertMaterial({ color: kWoodK, map: woodLight || null }));
      seat.position.set(x, 0.86, z); finish(seat); scene.add(seat);
      cyl(0.05, 0.07, 0.84, C.wood2, x, 0.42, z, null, 10, WOODM);
      if (DETAIL >= 2) {
        cyl(0.20, 0.22, 0.03, C.wood2, x, 0.26, z, null, 12, WOODM);
        cyl(0.17, 0.19, 0.03, C.wood2, x, 0.04, z, null, 12, WOODM);
        /* R2 (part list): 4 `foot` lathes, C.ink, at the base ring */
        [0.785, 2.356, 3.927, 5.498].forEach(function (ang) {
          latheAt('foot', [0.045, 0.035, 0.045], C.ink,
                  x + Math.cos(ang) * 0.13, 0, z + Math.sin(ang) * 0.13,
                  null, MATT);
        });
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
    /* This panel is the CALENDAR's now (user ruling 2026-09-09), and it
       keeps a clean wall: three prints behind a thing you are meant to read
       across a room is exactly the competition the scenery knob exists to
       settle. The sconce stays, because it lights what hangs here. */
    if (DETAIL >= 2) {
      /* the one wall light (plate 7). It sits ABOVE the calendar now, not
         over the prints — and still not over the L-return, because the
         fridge lean-in flies up that stretch of wall and anything on it
         lands on the fridge door's card. */
      box(0.07, 0.16, 0.16, HW, WXK + 0.035, 4.12, 1.52, westWallG, STEEL);
      cyl(0.02, 0.02, 0.26, HW, WXK + 0.16, 4.12, 1.52, westWallG, 8, STEEL);
      var scs = new T.Mesh(new T.CylinderGeometry(0.13, 0.19, 0.20, 14, 1, true),
        PBR ? new T.MeshStandardMaterial({ color: 0xf3e8d2, roughness: 0.8,
                                           emissive: 0xffd9a0,
                                           emissiveIntensity: 0.4,
                                           side: T.DoubleSide })
            : new T.MeshLambertMaterial({ color: 0xf3e8d2, side: T.DoubleSide }));
      scs.position.set(WXK + 0.29, 4.06, 1.52);
      finish(scs, true); westWallG.add(scs);
    }

    /* SHELL: west_wall is complete here — every wall-mounted item above
       (TV, sconce, calendar, kitchen toe-kick trim, ...) is already
       parented in, and nothing later in this file adds to westWallG (the
       fence assembly ~6500 only reads it). Registering any earlier would
       under-measure the box against a piece still being decorated.

       VIEW-VOLUME MASKING (task 4): `n` decides no verdict any more --
       the mask cuts this wall where the mudroom's box projects onto it
       (measured 0.37 of the row from the mudroom camera, 0.20 from the
       kitchen's for the pantry nook, 0 elsewhere) and only the AO
       derivation's wall-like test (|n.y| < 0.5) and the registry's own
       report read `n`. The paragraph that follows is the retired
       solver's record of why the flip was chosen; kept, not load-bearing.
       Solver tuning (Task 2, spec section 4): n is [1,0,0], pointing EAST
       toward the kitchen, not west toward the mudroom the wall's own
       compass direction would suggest. This wall is an INTERIOR partition
       (kitchen <-> mudroom), not a house/exterior boundary like yard or
       garage_door, so "outward" cannot mean "away from the interior" the
       way it does for those — it has to mean "the side whose room stays
       solid by default", which LEGACY says is the kitchen (only the
       mudroom's own hide: array ever listed this wall). Checked against
       every camera: with n east, camOut is true for HOME_POS/LIV_POS/
       MUD_POS (x 4.64 / 0 / -3.4 -- HOME_POS moved south and west in the
       cutaway-ownership fix and is still east of the wall's box centre,
       so this derivation stands unchanged) (all sit east of the wall's
       box centre x -6.2175, itself
       pulled east of the physical -6.65 wall panel by the TV/sconce/
       calendar it carries) and false for GARAGE_POS (x -18.0, further
       west than the wall itself) — of the three where camOut clears,
       only the mudroom's OWN aabb centre (x -9.62) sits west of -6.2175
       satisfying subIn; the kitchen's (x -2.785) and living's (x 0) sit
       east of it, same side as their cameras, same as before the flip. */
    /* spec section 5: west_wall FRONTS the mudroom, not the kitchen it
       sits inside of. Adjacency, not compass direction: the mudroom's
       own footprint (fabBox measured centre x -9.62, per westWallG's own
       T2 comment above) sits entirely WEST of this wall's inner face
       (WXK -6.475), the kitchen's entirely east of it (floor centre x 0,
       half-width 6.5) — so walking THROUGH this wall, from either room,
       always lands in the mudroom. Matches the solver's own n=[1,0,0]
       flip immediately above: this piece only ever ghosts for the
       mudroom's own camera (subIn true only when the subject sits west
       of the wall), i.e. it is the mudroom's fabric first and the
       kitchen's boundary second — a tap on it belongs where it ghosts. */
    /* VIEW-VOLUME MASKING (task 4): the partition between the mudroom
       and the great room. The mask cuts it where the mudroom's box
       projects onto it from the mudroom camera and nowhere else -- the
       solver's `owners` and explicit `plane` that used to say the same
       thing are retired. */
    regFabric(westWallG, { name: 'west_wall', n: [1, 0, 0],
                            box: fabBox(westWallG), room: 'mudroom' });

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
    var crit = zoneGroup('pet', -3.37, -0.610, 8.72);   /* the coffee table */
    crit.userData.room = 'living';
    rbox(0.66, 0.035, 0.46, 0.012, 0x2a2d34, 0, 1.24, 0.02, crit,
         { rough: 0.35, metal: 0.4, envInt: 0.6 });
    var lid = rbox(0.66, 0.44, 0.028, 0.012, 0x2a2d34, 0, 1.44, -0.24, crit,
                   { rough: 0.35, metal: 0.4, envInt: 0.6 });
    lid.rotation.x = -0.30;
    lid.position.y = 1.445; lid.position.z = -0.175;
    /* L1: lands straight on crit (a zone group) with no zoneTag wrapper
       after it, so the cache must be forced unique right here. */
    var critFace = textMesh(new T.PlaneGeometry(0.60, 0.38),
                            mat(0x12151c, { rough: 0.6 }, true));
    critFace.rotation.x = -0.30;
    critFace.position.set(0, 1.4395, -0.157);
    crit.add(critFace); finish(critFace);

    /* ---- the house around the kitchen (H1): everything out here lives
       in extG so the camera modes can reason about "outside". The
       kitchen's world coordinates never moved — the house grew around
       them. ---- */
    /* FARMHOUSE (spec section 6b, user-ratified 2026-09-11 with a
       reference image): the modern-farmhouse conversion's one named
       palette table. Every restyled surface below reads its color from
       HERE — arc 4 lifts this exact table to its own style enums, so
       nothing about this conversion may scatter a second hand-typed hex
       for a role this table already owns. */
    /* FACADE (arc 4, facade spec §3 + §6): PALETTE is that table lifted
       to the spec's own style enums -- one row per role, palette NAMES
       only, because the model and the stored spec never see hex. FARMHOUSE
       is then REBUILT from the active style at build time, so all 68
       existing FARMHOUSE.* read sites below keep working unchanged and
       nothing has to learn the enum names. stoop/windowDark/curtainGlow/
       curtainIntensity carry no enum (the spec gives no role for masonry
       or curtain light), so they stay literal here. */
    var PALETTE = {
      /* MASSING ARC 2 (spec 2026-09-17 section 3.1): the five masonry/
         render tones the six claddings need -- services/house_facade.py's
         STYLE.body carries the same ten names. */
      body:  { white: 0xf4f1e9, greige: 0xd9d2c5, sage: 0xb7c2ad, slate: 0x6f7b85, navy: 0x2f3e55,
               brick_red: 0x8e3b2f, tan: 0xcbb69a, cream_brick: 0xe3d5b8,
               stone_grey: 0x8b8a84, painted_brick: 0xece6dc },
      roof:  { charcoal: 0x2b2f33, weathered: 0x7d7a72, brown: 0x5a4636 },
      frame: { black: 0x1b1c1e, white: 0xf7f5ef },
      door:  { wood: 0x6b4a30, black: 0x1b1c1e, red: 0x9b2f2a, sage: 0x7d8f74 },
      trim:  { white: 0xf7f5ef, black: 0x1b1c1e },
      /* VIEW-VOLUME MASKING (spec 2026-09-16 masking section 2, choice
         A): the ONE neutral section tone every cut face of every room
         shell wears -- a light plaster grey, the same for every piece.
         Carries no facade enum (the stored spec has no role for it), so
         the single row is read by its own name below. Hex lives here
         and nowhere else. */
      section: { plaster: 0xe9e4da }
    };
    /* The server injects the active facade before this file loads (spec
       §3.1/§6: build-once, from the payload the page already fetched). A
       page served without it -- only the 2D fallback path can reach that
       -- falls back to CANONICAL_JS, the V2 literal just below. */
    var FACADE = (facadeInput && facadeInput.spec) ? facadeInput : null;
    /* THE CANONICAL FACADE, field for field services/house_facade.py's
       own CANONICAL (arc-2 spec plus the upper-span insert: VERSION 3,
       with per-block depth/roof/cladding/base/body and top-level upper,
       porch owning its gable, and `style` down to the four roles that
       are not a block's own skin). Only a page served WITHOUT the
       injection -- nothing but the 2D fallback path can reach that --
       ever builds from this literal; the pure test parses it out of this
       file and asserts it EQUALS CANONICAL, no upgrade table in between.

       DECLARED HERE, far above buildElevation()'s own fallback read,
       because `var` hoisting lifts the DECLARATION only: the VALUE is
       whatever was last assigned when a reader runs, and SPEC0 three
       lines below is the earliest reader. */
    var CANONICAL_JS = {
      version: 3,
      mirror: false,
      pitch_deg: 34.8,
      blocks: {
        main:   { depth: 0.0,
                  roof: { form: 'gable', ridge: 'x', pitch_deg: 22.5 },
                  cladding: 'batten', base: null, body: 'white' },
        garage: { depth: 0.0,
                  roof: { form: 'gable', ridge: 'x', pitch_deg: 22.5 },
                  cladding: 'batten', base: null, body: 'white',
                  orientation: 'front' }
      },
      style: { roof: 'charcoal', frame: 'black', door: 'wood', trim: 'white' },
      ground: [
        { slot: 0, span: 3, kind: 'garage_door', style: 'carriage', leaves: 1 },
        { slot: 7, span: 1, kind: 'window', size: 'tall', shutters: false, story: 1 },
        /* the porch OWNS its roof: the old free gable at slot 8 is this */
        { slot: 8, span: 4, kind: 'porch', type: 'sitting', roof: 'gable' },
        { slot: 9, span: 1, kind: 'window', size: 'tall', shutters: false, story: 1 },
        { slot: 10, span: 1, kind: 'door' },
        { slot: 12, span: 1, kind: 'window', size: 'tall', shutters: false, story: 1 },
        { slot: 15, span: 1, kind: 'window', size: 'standard', shutters: false, story: 1 },
        { slot: 16, span: 1, kind: 'window', size: 'standard', shutters: false, story: 1 }
      ],
      roof: [
        { slot: 0, span: 3, kind: 'gable' }
      ],
      upper: [],
      unexpressed: []
    };
    /* MASSING ARC 2 + 2b: THE BLOCK MODEL. The
       house is no longer one body colour and one cladding -- each block
       carries its own depth, ground roof {form, ridge, pitch_deg},
       cladding, base band and body, and `style` keeps only roof/frame/
       door/trim. Top-level upper spans own their second-story roofs. A
       spec reaches this file already normalized (the store
       upgrades a V1 save before it is ever served), so `blocks` is
       always there; the canonical row is the belt-and-braces fallback
       for a hand-built payload that skipped normalize. */
    var SPEC0 = FACADE ? FACADE.spec : CANONICAL_JS;
    var BLOCKS = SPEC0.blocks || CANONICAL_JS.blocks;
    var UPPER = SPEC0.upper || [];
    var MASSES = SPEC0.masses || [];
    function upperOverlapsX(name, x0, x1) {
      var first = name === 'garage' ? 0 : 6, count = name === 'garage' ? 6 : 12;
      var west = name === 'garage' ? -18.20 : -7.15;
      var east = name === 'garage' ? -7.15 : 14.65;
      var w = (east - west) / count;
      return UPPER.some(function (u) {
        if (u.slot < first || u.slot >= first + count) return false;
        var a = west + (u.slot - first) * w;
        var b = west + (u.slot - first + u.span) * w;
        return x0 < b - 1e-6 && a < x1 - 1e-6;
      });
    }
    var BLOCK_OF_FACE = { garage_block: 'garage', main: 'main' };
    var FSTYLE = SPEC0.style || CANONICAL_JS.style;   /* roof, frame, door, trim */
    function blockPitch(name) {
      return BLOCKS[name].roof.pitch_deg * Math.PI / 180;
    }
    /* which block's skin a registered piece wears. The garage BLOCK
       carries both the garage bay and the mudroom (massing arc 1); every
       other piece is the main block's. */
    function blockOfName(name) {
      return (name.indexOf('garage') === 0 || name.indexOf('mudroom') === 0 ||
              name.indexOf('facade_garage_block') === 0) ? 'garage' : 'main';
    }
    function pal(role, name, fallback) {
      var t = PALETTE[role];
      return (t && t[name] !== undefined) ? t[name] : fallback;
    }
    var FARMHOUSE = {
      /* the MAIN block's body is the house's default body tone wherever
         one colour is wanted (spec 2026-09-17 section 3.1); a block with
         its own body paints through CLAD()/cladColour() instead. */
      body:     pal('body', BLOCKS.main.body, 0xf4f1e9), // cladding, every exterior face
      roofTone: pal('roof', FSTYLE.roof, 0x2b2f33),    // shingle tone
      frame:    pal('frame', FSTYLE.frame, 0x1b1c1e),  // window frames + grilles
      wood:     pal('door', FSTYLE.door, 0x6b4a30),    // front door, garage door, posts
      trim:     pal('trim', FSTYLE.trim, 0xf7f5ef),    // fascia, corner boards, gutters
      section:  pal('section', FSTYLE.section || 'plaster', 0xe9e4da), // mask cut faces
      stoop:    0x8a8175,   // masonry-tone stoop
      windowDark: 0x273438,
      curtainGlow: 0xd9ae73,
      curtainIntensity: 0.68
    };
    /* The canvas painters below take CSS colour strings, not ints. */
    function hex6(c) { return '#' + ('000000' + c.toString(16)).slice(-6); }
    /* Small projecting gables keep the steep farmhouse pitch. The broad
       main and service roofs use 22.5 degrees to stay subordinate to
       the overall elevation after rotating their ridges across the house. */
    var PITCH_RISE4 = 2.05, PITCH_RUN4 = 2.95;
    /* FACADE (spec §3): pitch is the STREET FEATURE pitch -- every gable
       and dormer the generator builds. The broad main/service roofs keep
       their own Math.PI/8 rule at their own call sites. CANONICAL's
       34.8 degrees IS atan2(2.05, 2.95) rounded to the spec's precision. */
    var PITCH_FAMILY = FACADE ? FACADE.spec.pitch_deg * Math.PI / 180
                              : Math.atan2(PITCH_RISE4, PITCH_RUN4);
    var EXTC = { grass: 0x8fae6e, siding: FARMHOUSE.body, trim: FARMHOUSE.trim,
                 roof: FARMHOUSE.roofTone, ridge: 0x24272a, drive: 0xb8b2a6,
                 /* the GARAGE block's own body (spec 2026-09-17 section 2) */
                 garage: pal('body', BLOCKS.garage.body, 0xf4f1e9),
                 trunk: 0x6e5539, leaf: 0x5f8f4e,
                 leafB: 0x527f44 };
    var extG = new T.Group();
    scene.add(extG);
    /* K1: every ebox() call defaults to sharp exterior shell fabric
       (siding, roof, trim, driveway, street) unless the call is a
       genuine prop standing out there (the mailbox calls box(...,
       extG, ...) directly instead). The default only fills in when the
       caller hasn't set opts.ch itself, so a future exterior PROP built
       through ebox() can opt back into the chamfer with an explicit
       { ch: ... } rather than needing to bypass this wrapper. */
    function ebox(w, h, d, c, x, y, z, opts) {
      return box(w, h, d, c, x, y, z, extG,
                 (!opts || opts.ch === undefined) ? sharp(opts) : opts);
    }
    /* the outdoors pays the same tier the kitchen does (user ruling
       2026-09-08): mottled grass, clapboard, offset shingles, jointed
       concrete — canvas-procedural, zero downloads, NICE-gated like the
       wood and marble inside. */
    /* Spec 2026-09-17 blocks section 3.1: one tile per (material, body),
       world-scaled through userData.uvRef so seams and phase hold across
       pieces. Build-time textures, never disposed (lifecycle law -- mkTex
       owns the runtime ones, these are canvasTex tiles like every other
       build-time surface in this file). */
    var CLAD_CACHE = {};
    var CLAD_PAINT = {
      batten: function (g, S, body) {
        g.fillStyle = body; g.fillRect(0, 0, S, S);
        for (var bx = 0; bx < S; bx += 32) {
          g.fillStyle = 'rgba(255,255,255,0.5)'; g.fillRect(bx, 0, 3, S);
          g.fillStyle = 'rgba(110,98,80,0.5)'; g.fillRect(bx + 3, 0, 4, S);
        }
      },
      lap: function (g, S, body) {
        g.fillStyle = body; g.fillRect(0, 0, S, S);
        for (var y = 0; y < S; y += 21) {
          g.fillStyle = 'rgba(110,98,80,0.5)'; g.fillRect(0, y + 18, S, 3);
          g.fillStyle = 'rgba(255,255,255,0.5)'; g.fillRect(0, y, S, 2);
        }
      },
      brick: function (g, S, body) {
        g.fillStyle = '#b9b2a6'; g.fillRect(0, 0, S, S);           /* mortar */
        var ch = 16, bw = 64;
        for (var r = 0; r < S / ch; r++) {
          var off = (r % 2) ? bw / 2 : 0;
          for (var x = -bw; x < S + bw; x += bw) {
            var j = ((r * 7 + x / bw) % 5) * 6 - 12;                  /* per-brick tone jitter, deterministic */
            g.fillStyle = shade(body, j);
            g.fillRect(x + off + 1, r * ch + 1, bw - 3, ch - 3);
          }
        }
      },
      stone: function (g, S, body) {
        g.fillStyle = '#a9a49b'; g.fillRect(0, 0, S, S);
        var y = 0, r = 0;
        while (y < S) {
          var h = 24 + ((r * 5) % 3) * 8, x = -((r * 13) % 40);
          while (x < S) {
            var w = 40 + ((x / 7 + r) % 4) * 16;
            g.fillStyle = shade(body, ((r + x / 8) % 4) * 5 - 8);
            g.fillRect(x + 2, y + 2, w - 4, h - 4);
            x += w;
          }
          y += h; r += 1;
        }
      },
      stucco: function (g, S, body) {
        g.fillStyle = body; g.fillRect(0, 0, S, S);
        for (var i = 0; i < 1400; i++) {
          g.fillStyle = 'rgba(0,0,0,' + (0.03 + ((i * 31) % 7) * 0.01) + ')';
          g.fillRect((i * 97) % S, (i * 57) % S, 2, 2);
          g.fillStyle = 'rgba(255,255,255,0.06)';
          g.fillRect((i * 61) % S, (i * 89) % S, 1, 1);
        }
      },
      shingle: function (g, S, body) {                          /* wall shingle: staggered short courses */
        g.fillStyle = body; g.fillRect(0, 0, S, S);
        var ch = 24, sw = 20;
        for (var r = 0; r < S / ch; r++) {
          var off = (r % 2) ? sw / 2 : 0;
          g.fillStyle = 'rgba(60,50,40,0.45)'; g.fillRect(0, r * ch + ch - 3, S, 3);
          for (var x = -sw; x < S + sw; x += sw) {
            g.fillStyle = 'rgba(60,50,40,0.35)'; g.fillRect(x + off, r * ch, 2, ch);
          }
        }
      }
    };
    /* darken/lighten a '#rrggbb' by `d` per channel */
    function shade(css, d) {
      var n = parseInt(css.slice(1), 16);
      function c(v) { return Math.max(0, Math.min(255, v + d)); }
      return '#' + ('000000' + ((c(n >> 16) << 16) | (c((n >> 8) & 255) << 8) | c(n & 255)).toString(16)).slice(-6);
    }
    function cladTex(material, bodyHex) {
      if (!NICE) return null;
      var key = material + '|' + bodyHex;
      if (CLAD_CACHE[key]) return CLAD_CACHE[key];
      var paint = CLAD_PAINT[material] || CLAD_PAINT.batten;
      var t = canvasTex(256, function (g, S) { paint(g, S, hex6(bodyHex)); });
      t.wrapS = t.wrapT = T.RepeatWrapping;
      t.repeat.set(4, 2);
      t.userData = { uvRef: BATTEN_UV_REF, uvKey: material };
      CLAD_CACHE[key] = t;
      return t;
    }
    /* the tile a BLOCK's walls wear, and the flat colour behind it at the
       tiers that drop maps (!NICE): the block's own body, not the house's. */
    function CLAD(block) {
      var b = BLOCKS[block || 'main'];
      return cladTex(b.cladding, pal('body', b.body, 0xf4f1e9));
    }
    function cladColour(block) {
      return NICE ? 0xffffff
                  : pal('body', BLOCKS[block || 'main'].body, 0xf4f1e9);
    }
    // Split the actual wall, never overlay a second coplanar skin.
    function wallFinish(block, story, slot) {
      var b = BLOCKS[block], value = { cladding: b.cladding, body: b.body };
      Object.assign(value, ((SPEC0.story_finishes || {})[block] || {})[story] || {});
      (SPEC0.finishes || []).slice().reverse().forEach(function (f) {
        if (f.story === story && slot >= f.slot && slot < f.slot + f.span) {
          if (f.cladding) value.cladding = f.cladding;
          if (f.body) value.body = f.body;
        }
      });
      return value;
    }
    function finishWallBox(w, h, d, c, x, y, z, group, opts) {
      var block = opts.facadeBlock, story = y >= 5.6 ? 2 : 1;
      var first = block === 'garage' ? 0 : 6, count = block === 'garage' ? 6 : 12;
      var west = block === 'garage' ? -18.20 : -7.15, east = block === 'garage' ? -7.15 : 14.65;
      var step = (east - west) / count;
      var south = (block === 'garage' ? 10.10 : 14.55) + BLOCKS[block].depth;
      var front = w > d && Math.abs(z - south) < 0.4;
      var cuts = [x - w / 2, x + w / 2];
      if (front) for (var i = 0; i <= count; i++) {
        var edge = west + i * step;
        if (edge > cuts[0] + 1e-6 && edge < x + w / 2 - 1e-6) cuts.push(edge);
      }
      cuts.sort(function (a, b) { return a - b; });
      var runs = [];
      for (var j = 1; j < cuts.length; j++) {
        var mid = (cuts[j - 1] + cuts[j]) / 2;
        var slot = front ? first + Math.max(0, Math.min(count - 1, Math.floor((mid - west) / step))) : -1;
        var f = wallFinish(block, story, slot), last = runs[runs.length - 1];
        if (last && last.f.cladding === f.cladding && last.f.body === f.body) last.end = cuts[j];
        else runs.push({start: cuts[j - 1], end: cuts[j], f: f});
      }
      var parent = group || scene, result = runs.length > 1 ? new T.Group() : null;
      if (result) parent.add(result);
      runs.forEach(function (run) {
        var clean = Object.assign({}, opts); delete clean.facadeBlock;
        clean.map = cladTex(run.f.cladding, pal('body', run.f.body, 0xf4f1e9));
        var piece = box(run.end - run.start, h, d,
                        NICE ? 0xffffff : pal('body', run.f.body, 0xf4f1e9),
                        (run.start + run.end) / 2, y, z, result || parent, clean);
        // Preserve the original wall's texture phase at every material seam.
        if (runs.length > 1 && clean.map && piece.geometry.attributes.uv) {
          var ref = clean.map.userData.uvRef, offset = run.start - (x - w / 2);
          piece.geometry = cgeo('finish|' + piece.geometry.uuid + '|' + offset, function () {
            var geo = piece.geometry.clone(), uv = geo.attributes.uv, no = geo.attributes.normal;
            for (var k = 0; k < uv.count; k++) {
              if (Math.abs(no.getX(k)) < 0.5)
                uv.setX(k, uv.getX(k) + (no.getZ(k) < -0.5 ? w - (run.end - run.start) - offset : offset) / ref[0]);
            }
            uv.needsUpdate = true; return geo;
          });
        }
        piece.userData.wallFinish = { block: block, story: story, cladding: run.f.cladding, body: run.f.body };
        if (!result) result = piece;
      });
      return result;
    }
    var grassT = null, sidingT = null, shingleT = null, driveT = null,
        battenT = null;
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
      /* MASSING ARC 2: the lap painter moved into CLAD_PAINT (one tile per
         (material, body), cached). sidingT is that cache's `lap` entry at
         the MAIN block's body -- the same 256px canvas, the same course
         pitch, the same repeat -- kept as a named local because the R5
         normal-map derivation below reads it by name. */
      sidingT = cladTex('lap', FARMHOUSE.body);
      shingleT = canvasTex(256, function (g, S) {
        g.fillStyle = hex6(FARMHOUSE.roofTone); g.fillRect(0, 0, S, S);
                                                            // (spec 6b: dark
                                                            // charcoal shingle,
                                                            // tone constant
                                                            // swap only)
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
      /* the ROOF's shingle: its own world reference, stamped on the tile
         itself now that box()/vaultSection read the map rather than test
         three identities. `uvKey` collides by name with the WALL cladding
         called 'shingle'; tiledBoxGeo's cache key carries the reference
         too, so the two never share a geometry. */
      shingleT.userData = { uvRef: SHINGLE_UV_REF, uvKey: 'shingle' };
      /* battenT (spec section 6b): board-and-batten, the farmhouse
         conversion's own body cladding — vertical battens over a flat
         board, painted the SAME way the lap painter paints horizontal
         clapboard (an alternating highlight/shadow band pair, just turned
         90 degrees) so the two share one visual family and one derivation
         path below. MASSING ARC 2: both painters live in CLAD_PAINT now
         and both tiles come out of one cache, so a block asking for
         'batten' at the main body resolves to THIS object. */
      battenT = cladTex('batten', FARMHOUSE.body);
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
    /* R5 (quality spec §4): a normal map derived from the SAME canvas
       sidingT/shingleT already painted — no second download, just a
       luminance-gradient read of the pixels canvasTex drew a moment
       ago. PBR only: normalMap only matters under real PBR lighting,
       and the two materials it flips are the shared cached instances
       every ebox() siding/roof call already resolves to (mat()'s key
       is color+rough+metal+envInt+map+finish+thick, and NICE forces
       color to 0xffffff on every one of them) — one set() per texture
       reaches every wall and roof plane built through this tier,
       garage and mudroom included, since they share the same opts. */
    if (PBR) {
      var normalFromCanvas = function (srcCanvas, strength) {
        var S = srcCanvas.width, sctx = srcCanvas.getContext('2d');
        var src = sctx.getImageData(0, 0, S, S).data;
        function lum(x, y) {
          x = (x + S) % S; y = (y + S) % S;
          var i = (y * S + x) * 4;
          return (src[i] + src[i + 1] + src[i + 2]) / 765;
        }
        var nc = document.createElement('canvas');
        nc.width = nc.height = S;
        var nctx = nc.getContext('2d'), out = nctx.createImageData(S, S);
        var d = out.data;
        for (var y = 0; y < S; y++) {
          for (var x = 0; x < S; x++) {
            var dx = lum(x + 1, y) - lum(x - 1, y);
            var dy = lum(x, y + 1) - lum(x, y - 1);
            var nx = -dx * strength, ny = -dy * strength, nz = 1;
            var L = Math.sqrt(nx * nx + ny * ny + nz * nz);
            var i = (y * S + x) * 4;
            d[i] = (nx / L * 0.5 + 0.5) * 255;
            d[i + 1] = (ny / L * 0.5 + 0.5) * 255;
            d[i + 2] = (nz / L * 0.5 + 0.5) * 255;
            d[i + 3] = 255;
          }
        }
        nctx.putImageData(out, 0, 0);
        var t = new T.CanvasTexture(nc);
        t.wrapS = t.wrapT = T.RepeatWrapping;
        return t;
      };
      var sidingNT = normalFromCanvas(sidingT.image, 2.2);
      sidingNT.repeat.copy(sidingT.repeat);
      var sidingMat = mat(0xffffff, { map: sidingT, rough: 0.95 });
      sidingMat.normalMap = sidingNT;
      sidingMat.normalScale.set(0.35, 0.35);
      sidingMat.needsUpdate = true;
      /* battenT rides the SAME R5 idiom sidingT just did: a luminance
         gradient read of the canvas it just painted, one normalMap set
         onto the ONE cached material every battenT-mapped ebox()/box()
         call below resolves to (mat()'s key carries map.uuid, so
         battenT's own uuid — different from sidingT's — buckets these
         calls into a NEW shared entry, not sidingT's). Strength 2.2,
         matching sidingT's own board-relief depth (battens read as a
         cladding reveal, not a deep carve). */
      var battenNT = normalFromCanvas(battenT.image, 2.2);
      battenNT.repeat.copy(battenT.repeat);
      var battenMat = mat(0xffffff, { rough: 0.95, map: battenT });
      battenMat.normalMap = battenNT;
      battenMat.normalScale.set(0.35, 0.35);
      battenMat.needsUpdate = true;
      var shingleNT = normalFromCanvas(shingleT.image, 2.6);
      shingleNT.repeat.copy(shingleT.repeat);
      var roofMat = mat(0xffffff, { rough: 0.9, map: shingleT });
      roofMat.normalMap = shingleNT;
      roofMat.normalScale.set(0.35, 0.35);
      roofMat.needsUpdate = true;
    }
    /* yard: a grass slab whose top sits just under the kitchen plinth.
       Built here, in extG, before yardG exists (~6863) -- it cannot live
       IN yardG (that group hides whole in every room view; the lawn must
       stay visible from inside rooms, not vanish with the rest of the
       yard's decor). inYard() needs some way to know this ground is
       still "the yard" for the navigation law (spec section 5, rule 5:
       sky OR yard exits), so it carries the same userData.yard tag
       inYard() now also checks -- grass only, never the driveway/street
       ebox calls elsewhere, which stay ordinary solid exterior fabric. */
    var grassSlab = ebox(50, 0.4, 44, NICE ? 0xffffff : EXTC.grass, 0.5, -0.49, 4,
                         { rough: 1.0, map: grassT });
    grassSlab.userData.yard = true;
    /* Rear cladding is registered with its window, so neither can
       escape the shell's visibility or navigation rules. */
    var northCladdingG = new T.Group(); extG.add(northCladdingG);
    function nbox(w, h, d, c, x, y, z, opts) {
      return box(w, h, d, c, x, y, z, northCladdingG, sharp(opts));
    }
    nbox(14.0, 5.6, 0.3, NICE ? 0xffffff : EXTC.siding, -0.15, 2.8, -5.95,
         { rough: 0.95, facadeBlock: 'main', map: CLAD() });
    var westCladdingG = new T.Group(); extG.add(westCladdingG);
    function wbox(w, h, d, c, x, y, z, opts) {
      return box(w, h, d, c, x, y, z, westCladdingG, sharp(opts));
    }
    wbox(0.3, 5.6, 5.15, NICE ? 0xffffff : EXTC.siding, -7.0, 2.8, -4.025,
         { rough: 0.95, facadeBlock: 'main', map: CLAD() });
    wbox(0.3, 5.6, 2.55, NICE ? 0xffffff : EXTC.siding, -7.0, 2.8, 1.525,
         { rough: 0.95, facadeBlock: 'main', map: CLAD() });
    wbox(0.3, 2.4, 1.7, NICE ? 0xffffff : EXTC.siding, -7.0, 4.4, -0.6,
         { rough: 0.95, facadeBlock: 'main', map: CLAD() });
    wbox(0.3, 5.6, 1.6, NICE ? 0xffffff : EXTC.siding, -7.0, 2.8, 5.2,
         { rough: 0.95, facadeBlock: 'main', map: CLAD() });
    wbox(0.3, 2.2, 1.6, NICE ? 0xffffff : EXTC.siding, -7.0, 4.5, 3.6,
         { rough: 0.95, facadeBlock: 'main', map: CLAD() });
    regFabric(westCladdingG, { name: 'west_cladding', n: [1, 0, 0],
                               box: fabBox(westCladdingG), room: 'mudroom' });
    /* MASSING ARC 1 fix wave: the trim board that used to stand here
       (x 6.76, full height, proud of the siding) was the kitchen's own
       NORTH-EAST CORNER back when the north face ended at x 6.85.
       `north_wall_east` carries the face on to 14.65 now, so that board
       stood mid-elevation on a flat wall -- a full-height seam with
       nothing behind it, read at orbit stops 4-6. Deleted. In its place
       the plinth continues: `shellWall` gives north_wall_east a stoop
       band at its base and this half of the same run had none, so the
       north face's base band stopped dead at 6.85. One box, same
       height/colour/front plane as shellWall's own, and the whole north
       elevation now reads as one wall. */
    nbox(14.0, 0.20, 0.36, FARMHOUSE.stoop, -0.15, 0.10, -5.95);
    /* spec 2026-09-17 section 2: the main block's base band on its rear
       skin, in the band's own material/height/colour. Built BEFORE
       north_cladding registers, so the piece's fabric box carries it. */
    baseBand(northCladdingG, -7.15, -5.95, 6.85, -5.95, [0, 0, -1], 'main');
    /* The rear window stays inside the casing clearance at x=6.67.
       Glazing and frames sit on the exterior (north) face. */
    (function () {
      var wx = 5.20, wy = 3.60;          /* outer siding face z=-6.10 */
      var gl = nbox(0.84, 1.34, 0.03, 0x9fc4dc, wx, wy, -6.145,
                    { rough: 0.16, metal: 0.0, envInt: 0.6 });
      gl.userData.glazing = true;        /* the lighting pass looks for this */
      nbox(1.12, 0.13, 0.16, FARMHOUSE.frame, wx, wy + 0.735, -6.19, { rough: 0.9 });
      [-0.555, 0.555].forEach(function (dx) {
        nbox(0.14, 1.60, 0.16, FARMHOUSE.frame, wx + dx, wy, -6.19, { rough: 0.9 });
      });
      nbox(1.28, 0.10, 0.30, FARMHOUSE.frame, wx, wy - 0.745, -6.24, { rough: 0.9 });
      if (DETAIL >= 2) {
        nbox(0.06, 1.34, 0.06, FARMHOUSE.frame, wx, wy, -6.18, { rough: 0.9 });
        nbox(0.84, 0.06, 0.06, FARMHOUSE.frame, wx, wy, -6.18, { rough: 0.9 });
      }
    })();
    regFabric(northCladdingG, { name: 'north_cladding', n: [0, 0, -1],
                                box: fabBox(northCladdingG), room: 'kitchen' });

    /* ================= SHELL (Task 4, spec section 6): THE SEAL =========
       The great room (kitchen `floor` + living `floor2`) has never had a
       south wall, an east wall, or a roof over its own front two-thirds —
       the "dollhouse with its front sawn off" house-arc.md names. This
       block closes all three, and gives the new south wall a real front
       elevation per the user's own redirect: an offset door under a
       covered gabled porch, not a blank slab with windows.

       Placed HERE, after the siding/shingle materials (sidingT, shingleT,
       EXTC) and the existing roof/gutters, rather than up at wallB's own
       neighbourhood (the brief's file note names that region for "wall
       runs"): the south wall's own exterior face must be a cache hit
       against the SAME shared siding material every ebox() facade call
       already resolves to (R5's normal map rides along only on a cache
       hit), and that material does not exist until the exterior-materials
       block above builds it. */
    var grFloorBox = new T.Box3().setFromObject(floor)
                        .union(new T.Box3().setFromObject(floor2));
    /* WALL_T4 is assigned at wallB's own build site far above (massing
       arc 2: baseBand() runs at the north cladding, which is built
       before this line and needs the thickness). */
    var WALL_H4 = wallB.geometry.parameters.height;     /* 5.6 */
    var WALL_Y4 = wallB.position.y;                     /* 2.8 */
    var WALL_TOP4 = WALL_Y4 + WALL_H4 / 2;               /* 5.6: the room's
                                                             own ceiling line */
    /* Exterior eaves meet the existing 5.6-unit room wall head. */
    var EXT_TOP4 = WALL_TOP4;
    function swtag(m) { if (m) m.userData.room = 'living'; return m; }

    /* ---- the south wall (NEW): the street face ------------------------
       SWZ0 is the inner (room-side) face; SWZ1 is the outer (street-side)
       face, WALL_T4 further out.
       MASSING ARC 1 (spec section 2): the street face is the WHOLE main
       block now, x -7.15 .. 14.65 — the study's own street face is part
       of this wall, not a separate wing front 2.17 further south — so
       the width comes off the envelope (FULL_HOUSE, declared right
       here so the wall can read it) and not off the great room's floor
       union, which only ever measured the two rooms it was built for.
       SWZ0/SWZ1 are unchanged: the front line never moved.
       VIEW-VOLUME MASKING (task 4, spec section 5): ONE wall again. The
       cutaway-ownership fix (v2.499.41) had split it at x 6.85 into
       south_wall + south_wall_east because the verdict solver could only
       ghost a piece WHOLE, and the living room's cutaway took the
       study's street face with it. The mask cuts a wall only where it
       stands between a room camera and that room's box, so the great
       room's view opens the wall over the great room and the study's
       over the study, on the same registered piece. */
    var SWZ0 = grFloorBox.max.z;                          /* ~14.2 */
    var SWZ1 = SWZ0 + WALL_T4;                             /* ~14.55 */
    /* MASSING ARC 2 task 6 (spec 2026-09-17 section 2): DEPTH. A block's
       `depth` pushes its STREET FACE out toward the kerb and nothing
       else -- the room behind it, its north wall and its side walls all
       stay where they are (R-B floors the void that opens between the
       floor's edge and the moved wall). services/house_facade.py's
       normalize() clamps it (0..6, and 2.0 on a face carrying a porch,
       so the porch stays behind the kerb) and its slot_table() moves a
       face's z by exactly this number; facadeSlots() below follows the
       same rule off FACES, which is what keeps the JS and Python slot
       tables pinned to each other at every depth, not just at zero.

       ADDED, never substituted: every street-face coordinate below is
       written `<the old literal> + MAIN_DZ` (or GAR_DZ) rather than
       re-derived from the block row, because `x + 0` is x EXACTLY in
       IEEE754 -- so a canonical build (depth 0/0) is the same numbers,
       the same geometry cache keys and the same picture it was before
       this task, which the canonical mesh and pixel pins hold to. */
    var MAIN_DZ = BLOCKS.main.depth || 0;
    var GAR_DZ = BLOCKS.garage.depth || 0;
    /* MASSING ARC 1 (spec sections 2 and 3): the main block's envelope.
       Declared BEFORE the walls that read it: the south wall right
       here, the east wall below and every massing call further down
       all measure themselves off this row (GARAGE_BLOCK, the second
       block, is declared with the massing block below). */
    /* MASSING ARC 2 task 7 (spec 2026-09-17 section 3.2): STORIES. A
       block's eave is EXT_TOP4 per story -- exactly what
       services/house_facade.py's slot_table() has always published, and
       what house.js did not read, so a two-story spec's JS and Python
       slot tables disagreed on `eave`. Everything that places itself off
       the block row follows for free: the block roof (its shellGable
       call takes THIS number now, not the literal EXT_TOP4), the deck
       planes every street feature stands on, the gable-end infill, the
       facade slot table. The block's own GROUND walls keep their
       EXT_TOP4 height; storyBox() (far below, just above
       buildElevation()) carries the block from there up to this eave. */
    var FULL_HOUSE = {
      west: -7.15, east: 14.65, north: -6.10, south: SWZ1 + MAIN_DZ,
      eave: EXT_TOP4, overhang: 0.32
    };
    var SW_W = FULL_HOUSE.east - FULL_HOUSE.west;            /* 21.8 */
    var SW_CX = (FULL_HOUSE.west + FULL_HOUSE.east) / 2;     /* 3.75 */
    var southWallG = new T.Group();
    /* SHELL (spec section 5): this used to hand-stamp southWallG.userData
       .room = 'kitchen' right here, at group creation — the FIRST such
       stamp in the file, before regFabric grew its own `room` field
       (Task 7). That stamp and regFabric's own (below, at this group's
       registration) are the same group, the same value, both set well
       before anything ever reads userData.room (stampHouse, ROOM_AABB,
       onTap all run at the very end of buildRoom() / at tap time) —
       provably identical either way, so the hand stamp is gone and
       regFabric now does this once for every piece, not just this one. */
    extG.add(southWallG);
    /* room 'living' the whole run, the study's stretch included: a tap
       on the front of the house has always walked into the living room.
       The study is PIN-gated (its own door runs chfHouseUnlockStudy),
       and a shell tap is not a door -- routing one straight into the
       room would be a way past the PIN, not a feature. */

    /* FACADE (arc 4): the elevation used to be authored here -- an
       offset door, a window pair west of it and a single window east.
       It is a SPEC now (see the facade block below): windows on slots 7,
       9 and 12, the door on slot 10, the porch on slot 9 span 4. These
       two constants stay because the landscaping far below still
       anchors the front walk and the shrub line to them, and because
       every main-face window still shares ONE head; the builders publish
       the value they actually built into the first one. */
    var DOOR_X4 = 1.3;
    var WIN_HEAD4 = 4.4;

    /* the wall itself: interior plaster half + exterior siding half, the
       same two-material-per-thickness idiom every ORIGINAL exterior wall
       in this file already uses. WALL_O is wallB's own opts object (T11
       idiom: a MAPPED material takes no lightness pull from
       applyScenery, and architecture is meant to hold still while
       scenery recedes) — reusing it, not a new {rough:0.95,map:wallTex}
       literal, is what makes this a cache hit against wallB's own
       material instead of a new one. Height is EXT_TOP4, not WALL_TOP4:
       this wall sits at the far south end where the new roof's own eave
       (6.9, chosen below to match the existing eave line) is barely
       above WALL_TOP4 — a 5.6-tall wall would leave a gap under that
       eave, the exact wedge bug this whole block exists to avoid. */
    swtag(box(SW_W, EXT_TOP4, WALL_T4 / 2, C.wall, SW_CX, EXT_TOP4 / 2,
              SWZ0 + MAIN_DZ + WALL_T4 / 4, southWallG, sharp(WALL_O)));
    swtag(box(SW_W, EXT_TOP4, WALL_T4 / 2, NICE ? 0xffffff : EXTC.siding,
              SW_CX, EXT_TOP4 / 2, SWZ0 + MAIN_DZ + WALL_T4 * 3 / 4, southWallG,
              sharp({ rough: 0.95, facadeBlock: 'main', map: CLAD() })));
    /* the baseboard: one board, its two ends inset 0.15 each. */
    swtag(box(SW_W - 0.3, 0.2, 0.08, 0xe4ddd1, SW_CX, 0.1,
              SWZ0 + MAIN_DZ - 0.02, southWallG, sharp()));
    /* spec 2026-09-17 section 2: the main block's base band on the
       street face itself. Nothing is built when the block has no base. */
    swtag(baseBand(southWallG, FULL_HOUSE.west, SWZ1 + MAIN_DZ - WALL_T4 / 2,
                   FULL_HOUSE.east, SWZ1 + MAIN_DZ - WALL_T4 / 2, [0, 0, 1], 'main'));

    /* FACADE (arc 4): the door, the porch and the second coach lamp all
       stood here, hand-placed into southWallG. They are spec features
       now -- doorAt(), porchAt() and the lamp doorAt() carries -- each
       built into its OWN registered piece so the solver, the AO
       derivation and the merge fence reach them without new code. The
       porch's depth and eave stay constants: the walk, the shrub line
       and any gable roofing a porch all read them. */
    var PORCH_EAVE4 = 4.8, PORCH_DEPTH4 = 4.6;
    /* porchAt() is the only writer of this (below): a main-face porch
       moves it out to its own front edge. Defaults to SWZ1 -- the wall
       itself -- so a facade with no main-face porch gets a front walk
       that starts at the wall, not 4.6 units out in the grass where a
       porch that was never built would have ended. */
    var PORCH_FRONT_Z4 = SWZ1 + MAIN_DZ;

    /* SHELL: south_wall is the street FACE itself -- the slab, its
       siding skin and its baseboard. Its windows, door, porch and lamp
       are the facade's own registered pieces (arc 4), built below, and
       nothing later in this file ever adds to southWallG. n is [0,0,1]:
       a true exterior boundary (nothing but yard beyond it), so
       "outward" is its own physical compass direction -- no flip needed,
       unlike west_wall's interior-partition flip (T2). */
    regFabric(southWallG, { name: 'south_wall', n: [0, 0, 1],
                            box: fabBox(southWallG), room: 'living' });

    /* ---- MASSING ARC 1 (spec sections 2 and 3): two rectangles --------
       The hand-drawn massing (an east wing past the front, a patio
       notch, a rear room, a rear service block, eleven roof pieces) is
       gone. What is left is two blocks and two block roofs a generator
       can dress. FULL_HOUSE, the main block, is declared with the south
       wall above (which reads it); this is the second block. */
    /* the second block: garage (x -18.2..-12.6) + mudroom (-12.6..-7.15),
       set back 4.45 behind the main front. Its own eave is the main's:
       one eave line across both blocks, which is what lets a roof
       feature run coplanar across the old garage/mudroom boundary. */
    /* task 7: its own stories, the same rule as the main block's above.
       The two eaves can now DIFFER, which is what blockRoofsIdentical()
       reads to decide the blocks' roofs must be clipped against each
       other, and what sharedFaceOwner() reads to decide which of them
       owns the shared face plane at x -7.15. */
    var GARAGE_BLOCK = { west: -18.20, east: -7.15, north: -6.10,
                         south: 10.10 + GAR_DZ,
                         eave: EXT_TOP4 };
    /* MASSING ARC 2 task 8 (spec 2026-09-17 section 2): a SIDE-ENTRY
       garage. The bay's street face stops being a door bay and becomes
       an ordinary walled face with a window (services/house_facade.py's
       normalize() already deletes the street garage_door row and adds
       that window); the door moves to the block's WEST face, centred on
       SIDE_DOOR_Z, and the drive turns an L to reach it. One flag, read
       by the west wall, the bay's street pieces, garageDoorAt, the
       driveway and the car plaques -- every one of them reproduces
       today's front-entry numbers when it is false. */
    var GARAGE_SIDE = BLOCKS.garage.orientation === 'side';
    /* Side openings follow the front corner as block depth changes.
       A third bay adds a separate single-width opening and wall pier. */
    var SIDE_DOOR = BLOCKS.garage.side_door || {style:'carriage', leaves:1, width:3.6, height:3.0};
    var SIDE_FRONT_SETBACK = SIDE_DOOR.front_setback === undefined ? 0.75 : SIDE_DOOR.front_setback;
    var SIDE_THIRD_WIDTH = 2.4, SIDE_PIER = 0.75;
    var SIDE_DOOR_Z = GARAGE_BLOCK.south - SIDE_FRONT_SETBACK - SIDE_DOOR.width / 2;
    // The single bay sits behind the main door, toward the rear of the house.
    var SIDE_THIRD_Z = SIDE_DOOR_Z - SIDE_DOOR.width/2 - SIDE_PIER - SIDE_THIRD_WIDTH/2;
    var SIDE_PROJECTION = GARAGE_SIDE && SIDE_DOOR.third_bay ? (SIDE_DOOR.projection || 0) : 0;
    // A street-facing single bay needs a full door width plus two piers.
    var POP_WIDTH = SIDE_THIRD_WIDTH + 1.2 + Math.max(0, SIDE_PROJECTION-1.8);
    var POP_X = GARAGE_BLOCK.west-POP_WIDTH/2;
    var POP_FRONT = SIDE_DOOR_Z-SIDE_DOOR.width/2-SIDE_PIER;
    var POP_BACK = POP_FRONT-(SIDE_THIRD_WIDTH+1.2);
    var SIDE_OPENINGS = [{z:SIDE_DOOR_Z, width:SIDE_DOOR.width}];
    if (SIDE_DOOR.third_bay && !SIDE_PROJECTION) SIDE_OPENINGS.unshift({z:SIDE_THIRD_Z, width:SIDE_THIRD_WIDTH, third:true});
    var SIDE_OPEN_Z0 = SIDE_PROJECTION ? POP_FRONT : SIDE_DOOR.third_bay ? SIDE_THIRD_Z-SIDE_THIRD_WIDTH/2 : SIDE_DOOR_Z-SIDE_DOOR.width/2;
    var SIDE_OPEN_Z1 = SIDE_DOOR_Z + SIDE_DOOR.width/2;
    /* Every block roof is {form, ridge}: nothing about ridge direction
       is fixed (spec section 3). Canonical is today's look — both blocks
       gabled with the ridge running east/west. window.HOUSE_ROOF_FORMS
       overrides at build time (a probe/init-script hook, and the seam
       spec 2's block model feeds); absent, the canonical row stands. */
    /* MASSING ARC 2 (spec 2026-09-17 section 2): the rows come from the
       BLOCK MODEL now -- each block's own roof {form, ridge} -- and
       window.HOUSE_ROOF_FORMS still overrides on top of them, so a probe
       or an init script can still drive a form/ridge without a spec. */
    var ROOF_FORMS = { main:   { form: BLOCKS.main.roof.form,   ridge: BLOCKS.main.roof.ridge },
                       garage: { form: BLOCKS.garage.roof.form, ridge: BLOCKS.garage.roof.ridge } };
    (function () {
      var o = exteriorOnly ? null : window.HOUSE_ROOF_FORMS;
      if (!o) return;
      Object.keys(ROOF_FORMS).forEach(function (k) {
        if (!o[k]) return;
        if (o[k].form) ROOF_FORMS[k].form = o[k].form;
        if (o[k].ridge) ROOF_FORMS[k].ridge = o[k].ridge;
      });
    })();

    /* ---- VAULTED PARTITIONS: where the roof deck actually is -----------
       User report (2026-09-16, a screenshot of the living view): "There
       isn't any geometry on the right side to cover the top part. In a
       real house there would either be dropped ceilings with attic space
       above or vaulted ceilings where the walls go all the way up.
       Assume vaulted ceilings, so the walls should go all the way up."

       Every interior partition stopped at the eave (EXT_TOP4), so from
       the great room you looked OVER `east_partition` into the east
       rooms' own roof space -- while the west side of the same view is
       closed, because the block's west end carries a gable infill. Same
       for `future_room_partition`, the study's own north wall and the
       wall between the garage and the mudroom.

       Every partition is built HUNDREDS of lines before the roof that
       covers it, so the vault reads the deck off deckPlane (just below:
       the one derivation shellGable itself places its decks by, masking
       task 5) -- `eave + 0.18` is the deck's CENTRE plane where it
       crosses the wall line, the deck climbs tan(pitch) per unit toward
       the ridge, and its lower face sits half the 0.18 deck thickness
       below that centre plane -- measured down the VERTICAL, so
       0.09 / cos(pitch), not 0.09. tests/test_house_live.py derives the
       same numbers from the spec's own dimensions, so moving the deck
       fails a pin there rather than quietly leaving a wall in mid-air.

       VAULT_GAP holds every wall top just BELOW that face: exactly
       coplanar and the two surfaces z-fight the whole length of the
       partition. */
    var VAULT_GAP = 0.02;
    /* ---- THE DECK PLANE: one derivation (masking spec section 6) ------
       A block roof's slope deck is a 0.18-thick slab whose CENTRE plane
       crosses the wall line at `eave + 0.18` and climbs tan(pitch) per
       unit toward the ridge: ridge = eave + 0.18 + half * tan(pitch);
       the deck runs `run = half + overhang` down the slope and is
       centred at ridge - run * tan(pitch) / 2, half a run out from the
       ridge line. shellGable places its decks by this, roofVault reads
       every vaulted partition's head off it, the facade's roof features
       (gableAt / dormerAt / hipEndAt) stand on it and clip their buried
       parts against it, and chfRoofPlane hands it to the tests -- the
       three copies that used to agree by hand (the paragraph above was
       one of them) are this ONE function now. `sign` is -1 for the
       north deck (ridge on x) / the west deck (ridge on z), +1 for the
       south / east one. {n, d} follows the clipper's convention: n is
       the deck's UPWARD normal, and n.p - d >= 0 is above the deck. `c`
       is the deck's centre point; the rest are the numbers a caller
       places its trims and caps by. */
    function deckPlane(x0, x1, z0, z1, eave, ridgeAxis, pitch, sign) {
      var alongZ = (ridgeAxis === 'z' || ridgeAxis === true);
      var half = (alongZ ? x1 - x0 : z1 - z0) / 2;
      var cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
      var rise = half * Math.tan(pitch), roofEave = eave + 0.18;
      var ridge = roofEave + rise, run = half + FULL_HOUSE.overhang;
      var c = [cx + (alongZ ? sign * run / 2 : 0),
               ridge - run * Math.tan(pitch) / 2,
               cz + (alongZ ? 0 : sign * run / 2)];
      var n = alongZ ? [sign * Math.sin(pitch), Math.cos(pitch), 0]
                     : [0, Math.cos(pitch), sign * Math.sin(pitch)];
      return { n: n, d: n[0] * c[0] + n[1] * c[1] + n[2] * c[2], c: c,
               half: half, rise: rise, roofEave: roofEave, ridge: ridge,
               run: run, alongZ: alongZ, pitch: pitch };
    }
    /* the hipped END deck's centre plane, same convention: it rises the
       side decks' own `run * tan(pitch)` over the (clamped) `inset`, from
       an eave line one overhang past the block end -- see shellGable's
       hip paragraph for why the inset clamps at depth / 2. */
    function hipEndPlane(x0, x1, z0, z1, eave, ridgeAxis, pitch, sign) {
      var P = deckPlane(x0, x1, z0, z1, eave, ridgeAxis, pitch, sign);
      var depth = (P.alongZ ? z1 - z0 : x1 - x0) + 2 * FULL_HOUSE.overhang;
      var inset = Math.min(P.run, depth / 2);
      var endRise = P.run * Math.tan(pitch);
      var endPitch = Math.atan2(endRise, inset);
      var eaveY = P.ridge - P.run * Math.tan(pitch);
      var c = P.alongZ
        ? [(x0 + x1) / 2, eaveY, sign < 0 ? z0 - FULL_HOUSE.overhang : z1 + FULL_HOUSE.overhang]
        : [sign < 0 ? x0 - FULL_HOUSE.overhang : x1 + FULL_HOUSE.overhang, eaveY, (z0 + z1) / 2];
      var n = P.alongZ ? [0, Math.cos(endPitch), sign * Math.sin(endPitch)]
                       : [sign * Math.sin(endPitch), Math.cos(endPitch), 0];
      return { n: n, d: n[0] * c[0] + n[1] * c[1] + n[2] * c[2], c: c,
               inset: inset, endRise: endRise, endPitch: endPitch,
               spanEnd: Math.sqrt(inset * inset + endRise * endRise),
               eaveY: eaveY, depth: depth };
    }
    /* the plane's own height over (x, z): its centre line there */
    function planeY(pl, x, z) {
      return (pl.d - pl.n[0] * x - pl.n[2] * z) / pl.n[1];
    }
    function roofVault(block, forms, pitch) {
      /* a ridge on 'x' runs east/west, so the deck SLOPES along z. Both
         decks are read (min of the two centre planes is the roof line
         either side of the ridge), each dropped by half the deck's
         thickness measured down the vertical and the gap. */
      var alongZ = (forms.ridge === 'z');
      var pl = [-1, 1].map(function (sign) {
        return deckPlane(block.west, block.east, block.north, block.south,
                         block.eave, forms.ridge, pitch, sign);
      });
      return { axis: alongZ ? 'x' : 'z', pl: pl,
               under: 0.09 / Math.cos(pitch) + VAULT_GAP,
               at: alongZ ? (block.west + block.east) / 2
                          : (block.north + block.south) / 2,
               y: pl[1].ridge - 0.09 / Math.cos(pitch) - VAULT_GAP };
    }
    /* the deck underside at `u` on the vault's own slope axis */
    function vaultTop(v, u) {
      var x = v.axis === 'x' ? u : 0, z = v.axis === 'z' ? u : 0;
      return Math.min(planeY(v.pl[0], x, z), planeY(v.pl[1], x, z)) - v.under;
    }
    /* the profile of a wall that RUNS along the slope axis: a pentagon
       when the ridge crosses its run, a trapezoid when it does not. */
    function vaultRidgePts(v, u0, u1, yBase) {
      var pts = [[u0, yBase], [u0, vaultTop(v, u0)]];
      if (v.at > u0 && v.at < u1) pts.push([v.at, v.y]);
      pts.push([u1, vaultTop(v, u1)], [u1, yBase]);
      return pts;
    }
    /* the profile of a wall that runs ACROSS the slope axis: the deck is
       at ONE height over the whole run, so the top is cut square at the
       lower of the wall's two faces (`f0`/`f1`). Both faces are inside
       the house and the deck is above the wall either way. */
    function vaultFlatPts(v, u0, u1, yBase, f0, f1) {
      var y = Math.min(vaultTop(v, f0), vaultTop(v, f1));
      return [[u0, yBase], [u0, y], [u1, y], [u1, yBase]];
    }
    /* The section itself: a Shape -> ExtrudeGeometry through cgeo (keyed
       on every dimension), the way the gable-end infills are authored,
       placed by the same quarter-turn idiom shellGable uses. axis 'z' --
       the profile's u is world z -- turns local +x into world +z and
       local +z into world -x, so `face` is the wall's EAST face and the
       section extrudes back through its thickness; axis 'x' needs no
       turn at all and `face` is the wall's NORTH face. */
    function vaultSection(group, pts, yBase, axis, face, thick, colour, opts,
                          vFrom) {
      var u0 = pts[0][0], u1 = pts[pts.length - 1][0];
      /* WHICH MAPPING THIS SECTION OWES THE WALL BELOW IT. box() picks a
         UV reference for the three TILED exterior maps and leaves every
         other box on BoxGeometry's own 0..1-per-face mapping; a section
         continuing one of those walls owes it the SAME choice, so this
         is box()'s own detection block, not a second opinion about it.
         Getting it wrong is not a crash, it is siding at the wrong scale
         above the eave -- which is exactly what shipped in v2.499.45 and
         what this reads off `opts.map` to prevent. */
      var uvRef = null, uvKey = '';
      if (NICE && opts && opts.map && opts.map.userData && opts.map.userData.uvRef) {
        uvRef = opts.map.userData.uvRef; uvKey = opts.map.userData.uvKey;
      }
      /* the y at which the run BELOW this section started its own
         courses, so the section carries their phase across the joint
         instead of restarting them. Only a tiled map can see it. */
      vFrom = vFrom || 0;
      var key = 'vault|' + axis + '|' + thick + '|' + yBase + '|' + uvKey +
                '|' + (uvRef ? uvRef.join(',') : '') + '|' + vFrom + '|' +
                pts.map(function (p) {
                  return p[0].toFixed(4) + ',' + p[1].toFixed(4);
                }).join(';');
      var geo = cgeo(key, function () {
        var s = new T.Shape();
        s.moveTo(pts[0][0], pts[0][1]);
        for (var i = 1; i < pts.length; i++) s.lineTo(pts[i][0], pts[i][1]);
        s.closePath();
        var g2 = new T.ExtrudeGeometry(s, { depth: thick, bevelEnabled: false });
        /* ExtrudeGeometry maps uv in WORLD units; neither wall below a
           section is mapped that way, so both cases below re-map off the
           POSITION attribute (the generated uv means something different
           again on the extruded side faces).

           TILED (siding, battens, shingle): tiledBoxGeo scales a face's
           0..1 by its own world size over the reference, so one world
           unit is 1/ref. The section takes the same unit -- ref[1] up
           the wall, and across it ref[2] when the wall faces +-x (axis
           'z', where the profile's u is world z, tiledBoxGeo's own `d`)
           or ref[0] when it faces +-z. `vFrom` carries the courses'
           phase across the joint. u's phase is arbitrary here in the
           same way it is on a box face, whose two sides already run
           their u in opposite directions; only the DENSITY is a fact
           about the material, and that is what this fixes.

           PLAIN (the interior plaster): BoxGeometry maps every face
           0..1, so the gradient runs the full height of the wall below.
           v = y / yBase is exactly 1 where that box ends and clamps
           above it -- every texture here is a CanvasTexture, so
           ClampToEdge -- to the gradient's cream top. Left in world
           units instead, the whole section would clamp to the
           gradient's DARK end and draw a band across the partition. */
        var pos = g2.attributes.position, uv = g2.attributes.uv;
        var su = uvRef ? 1 / uvRef[axis === 'z' ? 2 : 0] : 1 / (u1 - u0);
        var sv = uvRef ? 1 / uvRef[1] : 1 / yBase;
        var v0 = uvRef ? vFrom : 0;
        for (var j = 0; j < uv.count; j++)
          uv.setXY(j, (pos.getX(j) - u0) * su, (pos.getY(j) - v0) * sv);
        uv.needsUpdate = true;
        return g2;
      });
      var m = new T.Mesh(geo, mat(colour, sharp(opts)));
      /* VIEW-VOLUME MASKING (task 2): `pts` is a pentagon or trapezoid
         (vaultRidgePts) or a rectangle (vaultFlatPts), extruded straight
         through `thick` -- a convex prism either way. */
      m.userData.convex = true;
      if (axis === 'z') { m.rotation.y = -Math.PI / 2; m.position.set(face, 0, 0); }
      else m.position.set(0, 0, face);
      finish(m); group.add(m); return m;
    }
    /* the block roofs' shared family pitch (spec 2026-09-16-regular-house-
       orbit-design.md section 2). Declared here, above every reader --
       roofVault(FULL_HOUSE, ...) below is the earliest -- because `var`
       hoisting only lifts the DECLARATION to the top of this function;
       the VALUE is whatever was last assigned at the point a reader
       runs, so the assignment itself has to sit above all four reads
       (this one, the two shellGable('roof_main'/'garage_block_roof', ...)
       calls, and blockDeckPlanes/faceDeckPlane's own copy below) for
       every one of them to see pi/8 rather than undefined.

       MASSING ARC 2 (spec 2026-09-17 section 2): the pitch is a BLOCK's
       own setting now. The name stays -- every main-block reader below
       means "the main block's pitch" -- and the GARAGE block's readers
       (its roofVault and its shellGable) take blockPitch('garage')
       instead. Canonical is 22.5 degrees on both, which is the pi/8 this
       line has always been, to the bit. */
    var BLOCK_PITCH = blockPitch('main');
    /* the main block's own vault, read once: every partition under
       `roof_main` measures itself off this. */
    var MAIN_VAULT = roofVault(FULL_HOUSE, ROOF_FORMS.main, BLOCK_PITCH);
    /* ROOF_FORMS is a build-time PARAMETER (house_probe injects it, and
       spec 2's block model feeds it), and BOTH of its fields change the
       deck a partition has to meet. A vault is built only for the
       canonical gable on a ridge running x.

       RIDGE. Give the block a ridge on z and the one deck slopes along
       x, not z: `east_partition` then runs ACROSS the slope and
       `future_room_partition` along it -- the opposite profile for each
       of the sections authored below (vaultRidgePts for the partition,
       vaultFlatPts for the future-room wall), and the study's own north
       wall reads its underside at a z. Nothing below is written for
       that mapping, so the vault is not built for it.

       FORM. Give it a HIP and the deck stops being a single plane that
       falls only along z: shellGable's hipped trapezoids pull in from
       each end by `inset` (one `run`, 10.645 on this block against a
       22.44 depth: a proper hip with a 1.15 ridge, task 4 having made
       the roof one piece again), so over x 6.85 the deck is already
       falling toward the east hip while the gable profile below would
       still be rising to 9.94 at the ridge line. That is a wall
       standing out of the roof in every exterior and orbit frame.
       `--roof hip` leaves `ridge` at 'x', so reading the ridge alone
       does not see this at all.

       Under either variant the walls stay at the eave, exactly where
       they stood before this arc, rather than wearing a section that
       pokes through a deck. Every vault below is gated on this flag;
       the garage block reads its OWN row the same way.

       STORIES (task 7, spec section 3.2). A vault is a partition carried
       up INTO the roof space, and a two-story block has no roof space
       over its ground floor: the deck is 5.6 higher with a whole sealed
       story in between, so a section reaching it would be a slab of
       plaster standing through the upper floor. Under two stories every
       partition keeps the flat top at EXT_TOP4 it already has, which is
       also the upper story's own floor line. The garage block reads its
       OWN `stories` at gVault the same way. */
    var VAULTED = (MAIN_VAULT.axis === 'z' && ROOF_FORMS.main.form === 'gable');
    function mainWingVault(x0, x1) { return VAULTED && !upperOverlapsX('main', x0, x1); }

    /* ---- the east PARTITION (was east_wall) ---------------------------
       The wall at x 6.85 stopped being an exterior side elevation the
       moment the main block grew east to 14.65: the study and the two
       future rooms are behind it now, so it is the interior partition
       between the great room and them. Plain wall plaster on BOTH faces
       (no siding half, no exterior baseboard) and three segments rather
       than one run, so the kitchen's slider and the living room's study
       door read as real openings instead of assemblies stuck onto a
       solid slab. The back-room door at z 2.45 keeps the older idiom (a
       leaf proud of an uncut wall): it is the one opening whose leaf
       was authored that way and nothing in this arc asks it to move.

       The south end stops at SWZ0, the south wall's INNER face, not
       SWZ1: an interior partition that ran to the OUTER face would put
       a 0.35-wide band of `C.wall` plaster in the plane of the street
       siding, and a coplanar end face reads as a pale stripe down the
       front elevation (orbit1). The same rule governs the east end of
       `future_room_partition` below. */
    var EPX0_4 = grFloorBox.max.x;                 /* ~6.5 */
    var EPX1_4 = EPX0_4 + WALL_T4;                  /* ~6.85 */
    var EWZ0_4 = wallB.position.z - WALL_T4 / 2;    /* wallB's own outer
                                                        (north) face */
    /* house_features.js hangs BOTH doors in this wall; every gap below
       is cut around one of them, so the two files must stay in step.

       STUDY REFIT (2026-09-16): the two openings swapped doors. The
       patio slider's glass belongs on the study (a study is where a
       pair of glazed doors belongs, and the patio is an inside room
       now), so the study's opening widened 1.80 -> 2.65 to take the
       slider's own 2.65 leaf pair; the opening at z 5.80 narrowed
       2.60 -> 1.80 to take the plain interior door the study gave up. */
    var STUDY_DOOR_Z4 = 9.93, STUDY_DOOR_W4 = 2.65;
    var EAST_ROOM_DOOR_Z4 = 5.80, EAST_ROOM_DOOR_W4 = 1.80;
    var eastPartG = new T.Group();
    extG.add(eastPartG);
    [[EWZ0_4, EAST_ROOM_DOOR_Z4 - EAST_ROOM_DOOR_W4 / 2],  /* 4.90 */
     [EAST_ROOM_DOOR_Z4 + EAST_ROOM_DOOR_W4 / 2,           /* 6.70 */
      STUDY_DOOR_Z4 - STUDY_DOOR_W4 / 2],                  /* 8.605 */
     [STUDY_DOOR_Z4 + STUDY_DOOR_W4 / 2, SWZ0]].forEach(function (seg) { /* 11.255 */
      var len = seg[1] - seg[0], cz = (seg[0] + seg[1]) / 2;
      box(WALL_T4, EXT_TOP4, len, C.wall, EPX0_4 + WALL_T4 / 2,
          EXT_TOP4 / 2, cz, eastPartG, sharp(WALL_O));
      box(0.08, 0.2, len - 0.20, 0xe4ddd1, EPX0_4 - 0.02, 0.1, cz,
          eastPartG, sharp());
    });
    /* HEADERS. A gap cut for a door is a DOORWAY, not a hole: without
       the wall above the head you look over each door into the room
       behind it. Each header starts just BELOW the head of what
       house_features.js actually builds in that opening -- the glass
       doors' casing spans y 3.67..3.83 and plugs the full 0.35 cut, the
       plain door's lining 2.97..3.12 -- so the joint is hidden behind
       the casing instead of leaving a lit slot above it. */
    [[EAST_ROOM_DOOR_Z4, EAST_ROOM_DOOR_W4, 3.05],
     [STUDY_DOOR_Z4, STUDY_DOOR_W4, 3.75]].forEach(function (op) {
      var h = EXT_TOP4 - op[2];
      box(WALL_T4, h, op[1], C.wall, EPX0_4 + WALL_T4 / 2,
          op[2] + h / 2, op[0], eastPartG, sharp(WALL_O));
    });
    /* THE VAULT. The partition runs along the main block's slope axis,
       so its top is a gable profile that follows the deck from the north
       wall, over the ridge at z 4.225, down to the street face -- ONE
       section over the whole run, which is also what finally puts wall
       above BOTH door headers all the way to the roof. Plain plaster on
       both faces, like the segments below it: the gable-end infills'
       battens belong to an OUTSIDE face and this one has none. */
    if (mainWingVault(EPX0_4, EPX1_4))
      vaultSection(eastPartG, vaultRidgePts(MAIN_VAULT, EWZ0_4, SWZ0, EXT_TOP4),
                   EXT_TOP4, 'z', EPX1_4, WALL_T4, C.wall, WALL_O);
    /* room: null — it fronts the kitchen on one face and the future
       rooms/study on the other, so no single room owns a tap on it.
       The mask cuts it only where it stands between a room camera and
       that room's box (today: nowhere -- the study camera stands east
       of it, the great room's boxes end at its west face). */
    regFabric(eastPartG, { name: 'east_partition', n: [1, 0, 0],
                           box: fabBox(eastPartG) });

    /* ---- the east WALL: the main block's own side elevation -----------
       x 14.65, from the north wall to the street face, fronting the back
       room, the east room and the study. One window each (spec section
       4's "what orbit exposes"), so the orbit's east stops do not read
       as a blank slab. room: null — three rooms stand behind it and two
       of them are unbuilt, so a tap on it is inert, exactly like the
       unbuilt massing it replaces. */
    var EWX1_4 = FULL_HOUSE.east;                   /* 14.65 */
    var EWX0_4 = EWX1_4 - WALL_T4;                  /* 14.30 */
    var EWZ1_4 = SWZ1 + MAIN_DZ;                    /* south_wall's own
                                                        outer face, which
                                                        depth moves (task 6) */
    var EW_LEN4 = EWZ1_4 - EWZ0_4;
    var EW_CZ4 = (EWZ0_4 + EWZ1_4) / 2;
    var eastWallG = new T.Group();
    extG.add(eastWallG);
    box(WALL_T4 / 2, EXT_TOP4, EW_LEN4, C.wall, EWX0_4 + WALL_T4 / 4,
        EXT_TOP4 / 2, EW_CZ4, eastWallG, sharp(WALL_O));
    box(WALL_T4 / 2, EXT_TOP4, EW_LEN4, NICE ? 0xffffff : EXTC.siding,
        EWX0_4 + WALL_T4 * 3 / 4, EXT_TOP4 / 2, EW_CZ4, eastWallG,
        sharp({ rough: 0.95, facadeBlock: 'main', map: CLAD() }));
    box(0.08, 0.2, EW_LEN4 - 0.3, 0xe4ddd1, EWX0_4 - 0.02, 0.1, EW_CZ4,
        eastWallG, sharp());
    /* spec 2026-09-17 section 2: the main block's base band, east face */
    baseBand(eastWallG, EWX0_4 + WALL_T4 / 2, EWZ0_4,
             EWX0_4 + WALL_T4 / 2, EWZ1_4, [1, 0, 0], 'main');
    /* study first (a lived room glows at night), then the two future
       rooms, which are empty and stay dark.
       STUDY REFIT (2026-09-16): the study's window turned onto this
       wall, so the pane at z 11.10 is now the STREET SIDE of a window
       the room actually has -- and a window cannot be two sizes
       depending on which side of the wall you stand on. The study's own
       glass is 4.8 x 3.2 at y 4.35 in study units, which at the room's
       0.42 fitting scale is 2.02 x 1.34 centred at y 1.95. The two
       future rooms keep the 1.35 x 2.70 pane at y 2.80: nothing is
       built behind them to disagree with. */
    [[11.10, true, 2.02, 1.34, 1.95],
     [4.60, false, 1.35, 2.70, 2.80],
     [-2.30, false, 1.35, 2.70, 2.80]].forEach(function (w) {
      shellWindow(eastWallG, EWX1_4 + 0.05, w[4], w[0], Math.PI / 2,
                  w[2], w[3], w[1]);
    });
    /* SHELL: east_wall is complete here. n is [1,0,0]: a true exterior
       boundary, its own physical outward compass direction. */
    regFabric(eastWallG, { name: 'east_wall', n: [1, 0, 0],
                           box: fabBox(eastWallG) });

    function shellGroup() { var g = new T.Group(); extG.add(g); return g; }
    /* MASSING ARC 2 task 6: a block roof piece that stood WHOLLY inside
       the neighbour block's volume (the garage's own gable infill at the
       shared face, when the main block owns that plane) comes back from
       clipBuried with nothing left. An empty group must not be
       registered: fabBox() would hand the mask solver an empty Box3
       (min +Infinity) and every reader of that row would carry it. */
    function hasMesh(g) {
      var any = false;
      g.traverse(function (m) { if (m.isMesh) any = true; });
      return any;
    }
    function shellBox(g, w, h, d, c, x, y, z, opts) {
      return box(w, h, d, c, x, y, z, g, sharp(opts));
    }
    /* ROOF VALLEYS (masking spec section 6): every facade row's world
       vertices, snapshotted at registration -- BEFORE mergeStatic folds
       its meshes -- so chfFabricVertices can hand a test the piece as
       built (not the composites it became). Facade rows only: a few
       hundred vertices each. */
    var FEATURE_VERTS = {};
    function wantsVerts(name) {
      /* MASSING ARC 2 task 6: the two BLOCK ROOFS join the facade rows
         here. The block-meet audit has to read a deck, rake or gable
         infill AS BUILT -- after the neighbour-volume clip, before
         mergeStatic folds it -- and the whole roof is a few thousand
         vertices, build-time only, the same order as the facade's. */
      return name.indexOf('facade_') === 0 ||
             name.indexOf('roof_main_') === 0 ||
             name.indexOf('garage_block_roof_') === 0;
    }
    function shellRegister(g, name, normal, room, kit) {
      g.updateMatrixWorld(true);
      if (wantsVerts(name)) {
        var verts = [], v = new T.Vector3();
        g.traverse(function (m) {
          if (!m.isMesh || m.isInstancedMesh) return;
          var p = m.geometry.getAttribute('position');
          for (var i = 0; i < p.count; i++) {
            v.fromBufferAttribute(p, i).applyMatrix4(m.matrixWorld);
            verts.push([v.x, v.y, v.z]);
          }
        });
        FEATURE_VERTS[name] = verts;
      }
      regFabric(g, { name: name, n: normal, box: fabBox(g), room: room,
                     kit: kit });
    }
    /* the one cap material every cut face wears: the room shells'
       remnants (buildRoomShells, far below) and the valley clip here.
       Declared HERE because the facade builds -- and clips -- hundreds
       of lines before the mask code runs; mat() caches by look, so the
       later reader gets this same object. */
    var CAP_MAT = mat(FARMHOUSE.section, { rough: 0.95 });
    /* ---- THE VALLEY CLIP (masking spec section 6) ---------------------
       A facade gable or dormer is a whole solid -- decks, trims, cap,
       infill, box -- that runs back and DOWN under the block roof it
       sits on, into the house. The old whole-piece ghost hid that; the
       mask keeps everything inside a room's own volume, so it drew the
       buried part (a shingled wedge with white battens beside the
       study's glass doors, user report 2026-09-16). This removes it at
       the source, at build, before the row is registered, so the row's
       box, its convexity scan and every room mask see only what stands
       above the roof.

       `region` is the BURIED region as a convex solid: planes whose
       kept side (n.p - d >= 0) is INSIDE it -- under every deck plane
       of the block roof, behind the street face, forward of the
       block's back (buriedRegion, below). Each mesh loses what lies
       inside; what remains is emitted as at most one CONVEX mesh per
       plane (outside plane 1; inside 1 and outside 2; ...), the
       clipper's subtractTris partition kept as separate meshes rather
       than concatenated, because a convex solid cut by a plane is
       convex and the room masks clip convex meshes in place but keep
       or drop a non-convex one whole. Each cut face is capped in
       CAP_MAT; the caps at the deck plane lie inside the parent deck
       (0.09 under its top surface) and the cap at the face line 0.02
       inside the wall slab, so no section ever shows. A mesh nothing
       of which is buried is left exactly as built; one wholly buried
       is removed. The pieces are world-space, at identity under the
       row group (a source under a transformed sub-group -- a dormer
       window's frame -- is re-parented to the row: the frame's own
       transform is already baked into the world triangles). */
    function clipBuried(g, region) {
      var C = window.HouseClip;
      g.updateMatrixWorld(true);
      var meshes = [];
      g.traverse(function (m) { if (m.isMesh && !m.isInstancedMesh) meshes.push(m); });
      meshes.forEach(function (m) {
        var rest = worldTris(m), pieces = [];
        region.forEach(function (pl) {
          var out = C.clipTris(rest, C.flip(pl), 1);
          if (C.triArea(out, 0) > 1e-6) pieces.push(out);
          rest = C.clipTris(rest, pl, 1);
        });
        if (C.triArea(rest, 0) <= 1e-6) return;     /* nothing buried: as built */
        m.parent.remove(m);
        pieces.forEach(function (tris) {
          [trisToMesh(tris, 0, m.material, m, null),
           trisToMesh(tris, 1, CAP_MAT, m, null)].forEach(function (pm) {
            if (!pm) return;
            pm.userData.convex = true;          /* a convex solid cut by planes */
            delete pm.userData.remnant;         /* not a room shell's stand-in */
            g.add(pm);
          });
        });
      });
      g.updateMatrixWorld(true);
    }
    function shellWindow(g, x, y, z, angle, w, h, glow) {
      var frame = new T.Group(); frame.position.set(x, y, z);
      frame.rotation.y = angle; g.add(frame);
      var pane = new T.Mesh(cgeo('shell-pane|' + w + '|' + h, function () {
        return new T.BoxGeometry(w, h, 0.04);
      }), mat(FARMHOUSE.windowDark, { rough: 0.55 }, true));
      pane.userData.shellWindow = true;
      pane.userData.shellGlow = !!glow;
      /* VIEW-VOLUME MASKING (task 2): a plain box, built directly (not
         through box()) because its material is forced unique for the
         night-glow toggle -- still convex. */
      pane.userData.convex = true;
      finish(pane); frame.add(pane);
      [-1, 1].forEach(function (s) {
        shellBox(frame, 0.11, h + 0.22, 0.14, FARMHOUSE.frame,
                 s * (w + 0.11) / 2, 0, 0.04);
        shellBox(frame, w + 0.22, 0.11, 0.14, FARMHOUSE.frame,
                 0, s * (h + 0.11) / 2, 0.04);
      });
      shellBox(frame, 0.06, h, 0.09, FARMHOUSE.frame, 0, 0, 0.08);
      shellBox(frame, w, 0.06, 0.09, FARMHOUSE.frame, 0, 0, 0.08);
      shellBox(frame, w + 0.32, 0.10, 0.24, FARMHOUSE.trim,
               0, -(h + 0.22) / 2, 0.05);
      return frame;
    }
    /* Spec 2026-09-17 section 2: a band at the block's foot in its own
       material, height and colour. A second box run at the wall's own
       thickness, shifted 0.03 along the wall's outward normal, added to
       the wall's OWN group (same registered piece, same room) so it
       masks, ghosts and merges with the wall it belongs to. A block with
       no base (the canonical, both blocks) builds nothing.

       x0/z0..x1/z1 are the wall's CENTRE LINE, exactly as shellWall takes
       them -- a band placed on a wall's OUTER face would stand 0.2 proud
       of it and bury the bottom of any door in that wall.

       THE 0.03 SHIFT IS THE WHOLE OFFSET (review fix, v2.499.75): the
       band reads as 0.03 proud outside and its back face lands 0.03
       INSIDE the wall's mass rather than coplanar with the interior
       surface. A band as thick as the wall + 0.06 put those two faces in
       the same plane, which z-fights from inside the room.

       `thick` (default WALL_T4) is for a run whose wall is not a shell
       wall -- the garage bay's piers are 0.24 deep, and a 0.35 band on
       them would stand proud of their own front face. */
    function baseBand(g, x0, z0, x1, z1, normal, block, thick) {
      var b = BLOCKS[block || 'main']; if (!b || !b.base) return;
      var h = b.base.height, alongX = x0 !== x1;
      var t = thick || WALL_T4;
      var length = alongX ? x1 - x0 : z1 - z0;
      var cx = (x0 + x1) / 2 + (alongX ? 0 : normal[0] * 0.03);
      var cz = (z0 + z1) / 2 + (alongX ? normal[2] * 0.03 : 0);
      return shellBox(g, alongX ? length : t, h, alongX ? t : length,
               NICE ? 0xffffff : pal('body', b.base.body, 0x8b8a84), cx, h / 2, cz,
               { rough: 0.95, map: cladTex(b.base.material,
                                           pal('body', b.base.body, 0x8b8a84)) });
    }
    /* `room` (massing arc 1): a shell wall used to register roomless
       without exception — every caller was unbuilt massing. The garage
       block's street face fronts a REAL room (the mudroom), so the
       argument exists rather than a second hand-rolled wall builder; it
       defaults to null, which is exactly what every older caller got.

       `block` (massing arc 2): which block's skin this wall wears --
       cladding, body and base band. Defaults to the block its NAME says
       (the garage block carries the garage bay and the mudroom). */
    function shellWall(name, x0, z0, x1, z1, height, normal, windows, room, block) {
      var g = shellGroup(), alongX = x0 !== x1;
      var length = alongX ? x1 - x0 : z1 - z0;
      var cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
      block = block || blockOfName(name);
      shellBox(g, alongX ? length : WALL_T4, height,
               alongX ? WALL_T4 : length, cladColour(block),
               cx, height / 2, cz, { rough: 0.95, facadeBlock: block, map: CLAD(block) });
      shellBox(g, alongX ? length : WALL_T4 + 0.06, 0.20,
               alongX ? WALL_T4 + 0.06 : length, FARMHOUSE.stoop,
               cx, 0.10, cz);
      baseBand(g, x0, z0, x1, z1, normal, block);
      [0, 1].forEach(function (end) {
        shellBox(g, 0.18, height, 0.18, FARMHOUSE.trim,
                 end ? x1 : x0, height / 2, end ? z1 : z0);
      });
      (windows || []).forEach(function (a) {
        var p = a[0], angle = alongX ? (normal[2] > 0 ? 0 : Math.PI)
                                      : (normal[0] > 0 ? Math.PI / 2 : -Math.PI / 2);
        shellWindow(g, alongX ? p : cx + normal[0] * (WALL_T4 / 2 + 0.05),
                    2.80, alongX ? cz + normal[2] * (WALL_T4 / 2 + 0.05) : p,
                    angle, a[1] || 1.35, 2.70, a[2]);
      });
      /* VIEW-VOLUME MASKING (task 2, corrected): shellWindow's own boxes
         are stamped convex like any other box() output, so a wall
         carrying a window is NOT a kit -- Task 3's buildRoomShells()
         clips it pre-merge, mesh by mesh, before mergeStatic ever fuses
         those boxes into a composite. No kit flag here. */
      shellRegister(g, name, normal, room || null);
      return g;
    }
    /* Each pitched plane has its own normal and merge/ghost unit. Gable
       infill is a separate vertical piece, so a front camera can see
       through the end without relying on a roof's half-space test.

       MASSING ARC 1 (spec section 3): `ridge` replaces the old boolean
       `alongZ` ('z' is what `true` meant) because a block roof's ridge
       direction is a PARAMETER now, not a fact about one hand-placed
       roof — and `form` grows the hip alongside the gable. A hip keeps
       every other number: same eave, same pitch, same overhang, same
       four registered pieces under the same four names. Only the shapes
       change — the two ridge decks become trapezoids inset by one `run`
       at each end, and the two ends become triangular decks of the same
       pitch instead of vertical clapboard infill (so all four planes
       meet at the same ridge point and no batten infill is needed). */
    /* `cladMap` (task 8): the tile this gable's END INFILL wears when the
       feature that asked for it overrides its block's cladding. Absent
       (every block roof, every canonical feature) the block's own tile
       stands, so nothing about the canonical moves. */
    function shellGable(name, x0, x1, z0, z1, eave, ridgeAxis, room, ends, pitch, slopeRooms, depthEnds, form, buried, cladMap) {
      var alongZ = (ridgeAxis === 'z' || ridgeAxis === true);
      var hip = (form === 'hip');
      /* MASSING ARC 2 task 6: only a BLOCK roof drops a piece the clip
         emptied. A facade gable or dormer the valley clip buries whole
         has always registered as an empty row (the worst case's garage
         bay gable does), and quietly retiring those rows would be a
         behaviour change this task never asked for. */
      var isBlockRoof = (name === 'roof_main' || name === 'garage_block_roof' ||
                         /^main_[uw]\d+_roof$/.test(name) || /^garage_[uw]\d+_roof$/.test(name));
      pitch = pitch || PITCH_FAMILY;
      /* the deck arithmetic is deckPlane's (one derivation, masking task
         5); the +1 plane carries the numbers both signs share */
      var P1 = deckPlane(x0, x1, z0, z1, eave, ridgeAxis, pitch, 1);
      var half = P1.half, rise = P1.rise, roofEave = P1.roofEave;
      var ridge = P1.ridge, run = P1.run;
      var cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
      var span = run / Math.cos(pitch);
      var depth = (alongZ ? z1 - z0 : x1 - x0) + 2 * FULL_HOUSE.overhang;
      /* Adjacent roof sections meet at the partition without overlapping
         decks, while keeping the same ridge height and texture scale. */
      if (depthEnds) {
        var before = depthEnds[0] ? FULL_HOUSE.overhang : 0;
        var after = depthEnds[1] ? FULL_HOUSE.overhang : 0;
        depth = (alongZ ? z1 - z0 : x1 - x0) + before + after;
        if (alongZ) cz += (after - before) / 2;
        else cx += (after - before) / 2;
      }
      /* the hip's ridge is inset from each end by one `run` -- that is
         exactly what makes the end planes take the same pitch as the
         sides. Derived, never typed: the apex sits `run` in from the
         eave because it rises `run * tan(pitch)`, the same rise the
         side decks make over their own `run`.

         THE CLAMP: a block SHORTER along its ridge axis than it is wide
         has no room for that inset -- run past the middle and the
         trapezoid's ridge edge runs backwards against its eave edge, a
         bowtie. `inset` is therefore capped at depth/2, where the two
         ridge corners meet in the middle: the trapezoids collapse to
         triangles, there is no ridge LEFT to cap (capLen 0, so the
         ridge cap is skipped rather than stubbed), and the end planes
         come in steeper than the sides -- their rise is still the
         block's own `run * tan(pitch)`, now over a shorter run. That is
         a pyramid, which is the honest answer to "hip a block whose
         ridge axis is its short one". The canonical garage block with
         ridge 'x' is exactly that case: depth 11.69 against run 8.42.
         Give it ridge 'z' (depth 16.84, the same run) and it hips
         properly, with a 5.15-long ridge. */
      var inset = hip ? Math.min(run, depth / 2) : 0;
      var capLen = hip ? depth - 2 * inset : depth;
      [-1, 1].forEach(function (sign) {
        var g = shellGroup(), deck;
        /* the deck sits on its own centre plane; a depthEnds shift moves
           it along the ridge only, which the plane does not see */
        var P = deckPlane(x0, x1, z0, z1, eave, ridgeAxis, pitch, sign);
        var at = [alongZ ? P.c[0] : cx, P.c[1], alongZ ? cz : P.c[2]];
        if (hip) {
          /* the deck's own local frame is the box deck's: (along-ridge,
             thickness, slope) for a ridge on x, (slope, thickness,
             along-ridge) for a ridge on z. The shape is authored in
             (local x, local z) and rotated a quarter turn about x, so
             the extrusion's depth becomes the 0.18 deck thickness. */
          var gt = cgeo('shell-hipdeck|' + half + '|' + depth + '|' + inset +
                        '|' + span + '|' + alongZ + '|' + sign, function () {
            var u0 = -depth / 2, u1 = depth / 2;
            var vEave = sign * span / 2, vRidge = -sign * span / 2;
            var s = new T.Shape();
            function pt(u, v) { return alongZ ? [v, u] : [u, v]; }
            var a = pt(u0, vEave), b = pt(u1, vEave),
                c = pt(u1 - inset, vRidge), d = pt(u0 + inset, vRidge);
            s.moveTo(a[0], a[1]); s.lineTo(b[0], b[1]);
            s.lineTo(c[0], c[1]);
            /* capLen 0 means c and d are the same point: emit the
               triangle rather than a four-point shape with a repeat. */
            if (capLen > 0.02) s.lineTo(d[0], d[1]);
            s.closePath();
            var geo = new T.ExtrudeGeometry(s, { depth: 0.18, bevelEnabled: false });
            geo.translate(0, 0, -0.09); geo.rotateX(Math.PI / 2);
            // Match box roof decks' world-scaled shingle density. Extrude's
            // default world-unit UVs otherwise shrink the pattern into noise.
            var uv=geo.attributes.uv, positions=geo.attributes.position;
            for(var vertex=0;vertex<uv.count;vertex++)uv.setXY(vertex,
              positions.getX(vertex)/SHINGLE_UV_REF[0],positions.getZ(vertex)/SHINGLE_UV_REF[2]);
            return geo;
          });
          deck = new T.Mesh(gt, mat(NICE ? 0xffffff : FARMHOUSE.roofTone,
                                    { rough: 0.9, map: shingleT }));
          /* VIEW-VOLUME MASKING (task 2): the shape above is a trapezoid
             (eave edge, two slanted sides, an inset ridge edge) or, when
             capLen clamps to zero, a triangle -- either way convex. */
          deck.userData.convex = true;
          deck.position.set(at[0], at[1], at[2]);
          finish(deck); g.add(deck);
        } else {
          deck = shellBox(g, alongZ ? span : depth, 0.18,
                          alongZ ? depth : span, NICE ? 0xffffff : FARMHOUSE.roofTone,
                          at[0], at[1], at[2], { rough: 0.9, map: shingleT });
        }
        if (alongZ) deck.rotation.z = -sign * pitch;
        else deck.rotation.x = sign * pitch;
        var edgeY = ridge - run * Math.tan(pitch) - 0.10;
        shellBox(g, alongZ ? 0.14 : depth, 0.28,
                 alongZ ? depth : 0.14, FARMHOUSE.trim,
                 cx + (alongZ ? sign * run : 0), edgeY,
                 cz + (alongZ ? 0 : sign * run));
        /* Thin dark ridge halves meet without a white seam. A clamped
           hip has no ridge at all, so it gets no cap. */
        if (capLen > 0.02) {
          shellBox(g, alongZ ? 0.14 : capLen, 0.12,
                   alongZ ? capLen : 0.14, EXTC.ridge,
                   cx + (alongZ ? sign * 0.065 : 0), ridge + 0.065,
                   cz + (alongZ ? 0 : sign * 0.065));
        }
        g.updateMatrixWorld(true);
        var n = new T.Vector3(0, 1, 0).applyQuaternion(
          deck.getWorldQuaternion(new T.Quaternion()));
        if (buried) (Array.isArray(buried[0]) ? buried : [buried]).forEach(function (r) { clipBuried(g, r); });
        if (buried && isBlockRoof && !hasMesh(g)) { extG.remove(g); return; }
        shellRegister(g, name + (alongZ ? (sign < 0 ? '_west' : '_east')
                                       : (sign < 0 ? '_north' : '_south')),
                      n.toArray(), slopeRooms ? slopeRooms[sign < 0 ? 0 : 1] : room);
      });
      cx = (x0 + x1) / 2; cz = (z0 + z1) / 2;
      (ends || [-1, 1]).forEach(function (sign) {
        var g = shellGroup();
        if (hip) {
          /* the hipped end: one triangular deck, eave-eave-apex. It
             rises the block's own `run * tan(pitch)` -- the same apex
             the two side decks reach -- over the CLAMPED `inset`. On an
             unclamped block inset === run, so endPitch === pitch and the
             four planes share one slope; on a clamped one the end comes
             in steeper, which is what keeps the apex on the ridge line
             instead of tearing the pyramid open. Local frame (slope,
             thickness, along-eave), same quarter-turn idiom as the
             trapezoids. */
          var E = hipEndPlane(x0, x1, z0, z1, eave, ridgeAxis, pitch, sign);
          var endRise = E.endRise, endPitch = E.endPitch, spanEnd = E.spanEnd;
          var ge = cgeo('shell-hipend|' + run + '|' + inset + '|' + endRise +
                        '|' + sign, function () {
            var s = new T.Shape();
            s.moveTo(0, -run); s.lineTo(0, run);
            s.lineTo(-sign * spanEnd, 0); s.closePath();
            var geo = new T.ExtrudeGeometry(s, { depth: 0.18, bevelEnabled: false });
            geo.translate(0, 0, -0.09); geo.rotateX(Math.PI / 2);
            // Match box roof decks' world-scaled shingle density. Extrude's
            // default world-unit UVs otherwise shrink the pattern into noise.
            var uv=geo.attributes.uv, positions=geo.attributes.position;
            for(var vertex=0;vertex<uv.count;vertex++)uv.setXY(vertex,
              positions.getX(vertex)/SHINGLE_UV_REF[0],positions.getZ(vertex)/SHINGLE_UV_REF[2]);
            return geo;
          });
          var hm = new T.Mesh(ge, mat(NICE ? 0xffffff : FARMHOUSE.roofTone,
                                      { rough: 0.9, map: shingleT }));
          /* VIEW-VOLUME MASKING (task 2): a hip end is one triangular
             deck (eave, eave, apex) -- convex. */
          hm.userData.convex = true;
          var eaveY = E.eaveY;
          hm.rotation.y = alongZ ? -Math.PI / 2 : 0;
          hm.rotation.z = -sign * endPitch;
          hm.position.set(E.c[0], E.c[1], E.c[2]);
          finish(hm); g.add(hm);
          shellBox(g, alongZ ? 2 * run : 0.14, 0.28, alongZ ? 0.14 : 2 * run,
                   FARMHOUSE.trim, alongZ ? cx : (sign < 0 ? x0 : x1) +
                   sign * FULL_HOUSE.overhang, eaveY - 0.10,
                   alongZ ? (sign < 0 ? z0 : z1) + sign * FULL_HOUSE.overhang : cz);
          g.updateMatrixWorld(true);
          var hn = new T.Vector3(0, 1, 0).applyQuaternion(
            hm.getWorldQuaternion(new T.Quaternion()));
          if (buried) (Array.isArray(buried[0]) ? buried : [buried]).forEach(function (r) { clipBuried(g, r); });
          if (buried && isBlockRoof && !hasMesh(g)) { extG.remove(g); return; }
          shellRegister(g, name + (alongZ ? (sign < 0 ? '_back' : '_front')
                                         : (sign < 0 ? '_end_west' : '_end_east')),
                        hn.toArray(), room);
          return;
        }
        var geo = cgeo('shell-gable|' + half + '|' + eave + '|' + pitch, function () {
          var shape = new T.Shape();
          shape.moveTo(-half, eave); shape.lineTo(-half, roofEave);
          shape.lineTo(0, ridge); shape.lineTo(half, roofEave);
          shape.lineTo(half, eave); shape.lineTo(-half, eave);
          return new T.ExtrudeGeometry(shape, { depth: 0.14, bevelEnabled: false });
        });
        var m = new T.Mesh(geo, mat(cladColour(blockOfName(name)),
                                   { rough: 0.95,
                                     map: cladMap || CLAD(blockOfName(name)) }));
        /* VIEW-VOLUME MASKING (task 2): the gable-end shape above is a
           symmetric "house" pentagon -- a rectangle (eave to roofEave)
           with a triangular peak (roofEave to the ridge apex) -- and
           every one of its five interior turns bends the same way, so
           it is convex. */
        m.userData.convex = true;
        if (alongZ) m.position.set(cx, 0, sign < 0 ? z0 - 0.14 : z1);
        else { m.rotation.y = -Math.PI / 2;
               m.position.set(sign < 0 ? x0 : x1 + 0.14, 0, cz); }
        finish(m); g.add(m);
        [-1, 1].forEach(function (side) {
          var rake = shellBox(g, alongZ ? span : 0.16,
                              0.22, alongZ ? 0.16 : span,
                              FARMHOUSE.trim,
                              cx + (alongZ ? side * run / 2 : sign * ((x1 - x0) / 2 + FULL_HOUSE.overhang + 0.08)),
                              ridge - run * Math.tan(pitch) / 2 - 0.10,
                              cz + (alongZ ? sign * ((z1 - z0) / 2 + FULL_HOUSE.overhang + 0.08) : side * run / 2));
          if (alongZ) rake.rotation.z = -side * pitch;
          else rake.rotation.x = side * pitch;
        });
        if (buried) (Array.isArray(buried[0]) ? buried : [buried]).forEach(function (r) { clipBuried(g, r); });
        if (buried && isBlockRoof && !hasMesh(g)) { extG.remove(g); return; }
        shellRegister(g, name + (alongZ ? (sign < 0 ? '_back' : '_front')
                                       : (sign < 0 ? '_end_west' : '_end_east')),
                      alongZ ? [0, 0, sign] : [sign, 0, 0], room);
      });
    }
    /* ================= FACADE: the street elevation ===================
       Arc 4, spec docs/superpowers/specs/2026-09-15-house-facade-
       generator-design.md (sections 2, 2.2, 3 and 6). Everything from
       here to buildElevation() REPLACES the hand-authored street face:
       the south wall's three windows, its door, porch and second coach
       lamp; massing_east_front_south's two hard-coded windows; the
       porch and garage gables; and the garage door's own style block.
       The wall SLABS stay exactly where they are (a face is not a
       feature) and so does every interior, camera, room and zone.

       Build-once: the spec arrives in window.HOUSE_FACADE before this
       file loads and nothing re-reads it at runtime (the lifecycle law
       forbids a rebuild and nothing here needs one). */
    var SLOT_W = 1.85;
    /* Slots are DERIVED from the envelope, never chosen (spec section
       2): street faces, n = max(1, round(width / SLOT_W)) slots each,
       every slot on a face the same width. services/house_facade.py's
       FACES mirrors these rows and its slot_table() the loop below; the
       live pin test asserts the two tables equal, slot by slot, so they
       cannot drift. */
    /* MASSING ARC 1 task 3 (spec section 5): the old four-face table
       (garage/mudroom/main/wing) collapses onto the two blocks task 2
       built -- garage_block fronts the whole driveway side (garage +
       mudroom, one eave, one z) and main absorbs the wing now that it
       sits on the same street line (z SWZ1) as the rest of the front.
       Eighteen slots still (6 + 12), re-snapped: CANONICAL_JS above and
       services/house_facade.py's CANONICAL carry the same numbers
       (task-3-report.md shows the derivation). */
    var FACES = [
      { face: 'garage_block', x0: GARAGE_BLOCK.west, x1: GARAGE_BLOCK.east, z: GARAGE_BLOCK.south, eave: GARAGE_BLOCK.eave, room: 'garage', roof: 'garage_block_roof' },
      /* Per-slot eaves are replaced below from the volume covering x;
         Python's slot_table publishes the same upper-aware result. */
      { face: 'main',         x0: FULL_HOUSE.west,   x1: FULL_HOUSE.east,   z: FULL_HOUSE.south,   eave: FULL_HOUSE.eave,  room: 'living', roof: 'roof_main' }
    ];
    /* Mirrors services/house_facade.py's GARAGE_BAY_SLOTS: the garage
       ROOM's own x range (-18.2..-12.6) nearest-slot-boundary snapped
       onto the garage_block face's six slots. gableAt's garage special
       case and the door's own bay (SLOTS[0..2]) key off this, not the
       whole face, which now also carries the mudroom. Declared HERE,
       above facadeSlots(), because that loop reads it while it builds
       the table.
       VIEW-VOLUME MASKING (task 4): a slot carries its FACE's fronting
       room and nothing about which room's view may remove a feature
       built on it -- the cutaway-ownership table (STUDY_SLOTS /
       slotOwners, mirrored from services/house_facade.py) is retired
       with the verdict solver; the mask keeps or drops a feature by
       where it stands between a room camera and that room's box. */
    var GARAGE_BAY_SLOTS = [0, 2];
    function facadeSlots() {
      var out = [], i = 0;
      FACES.forEach(function (f) {
        var width = f.x1 - f.x0, n = Math.max(1, Math.round(width / SLOT_W)), w = width / n;
        for (var k = 0; k < n; k++) {
          var x0 = f.x0 + k * w, gi = i++;
          var raised = UPPER.some(function (u) { return gi >= u.slot && gi < u.slot + u.span; });
          var mass = MASSES.find(function (m) { return gi >= m.slot && gi < m.slot + m.span; });
          var dz = mass ? mass.depth - (BLOCKS[BLOCK_OF_FACE[f.face]].depth || 0) : 0;
          out.push({ i: gi, face: f.face, x0: x0, x1: x0 + w, cx: x0 + w / 2, z: f.z + dz,
                     eave: raised ? 2 * EXT_TOP4 : EXT_TOP4, room: f.room, roof: f.roof });
        }
      });
      return out;
    }
    var SLOTS = facadeSlots();
    function blockVolumes(name) {
      var face = name === 'garage' ? 'garage_block' : 'main';
      var B = name === 'garage' ? GARAGE_BLOCK : FULL_HOUSE;
      var cells = SLOTS.filter(function (s) { return s.face === face; });
      var spans = UPPER.filter(function (u) {
        return cells.some(function (s) { return s.i === u.slot; });
      });
      var masses = MASSES.filter(function (m) { return cells.some(function (s) { return s.i === m.slot; }); });
      if (!spans.length && !masses.length) return [{ name: name, block: name, k: 0,
        x0: B.west, x1: B.east, north: B.north, south: B.south,
        eave: EXT_TOP4, roof: { form: ROOF_FORMS[name].form,
          ridge: ROOF_FORMS[name].ridge, window: BLOCKS[name].roof.window, pitch_deg: BLOCKS[name].roof.pitch_deg },
        upper: false, canonical: true }];
      function owner(i) {
        return { upper: spans.find(function (u) { return i >= u.slot && i < u.slot + u.span; }) || null,
                 mass: masses.find(function (m) { return i >= m.slot && i < m.slot + m.span; }) || null };
      }
      var runs = [], start = 0, prior = owner(cells[0].i);
      for (var j = 1; j <= cells.length; j++) {
        var next = j < cells.length ? owner(cells[j].i) : null;
        if (j === cells.length || next.upper !== prior.upper || next.mass !== prior.mass) {
          var region = prior.upper || prior.mass;
          var roof = region ? region.roof : { form: ROOF_FORMS[name].form,
            ridge: ROOF_FORMS[name].ridge, window: BLOCKS[name].roof.window, pitch_deg: BLOCKS[name].roof.pitch_deg };
          var k = runs.length;
          runs.push({ name: name + '_' + (prior.upper ? 'u' : 'w') + k, block: name, k: k,
            x0: cells[start].x0, x1: cells[j - 1].x1,
            north: B.north, south: cells[start].z, eave: prior.upper ? 2 * EXT_TOP4 : EXT_TOP4,
            roof: roof, upper: !!prior.upper, canonical: false });
          start = j; prior = next;
        }
      }
      return runs;
    }
    var HOUSE_VOLUMES = { main: blockVolumes('main'), garage: blockVolumes('garage') };
    var ALL_VOLUMES = HOUSE_VOLUMES.garage.concat(HOUSE_VOLUMES.main);
    function volumeAt(face, x) {
      var name = face === 'garage_block' ? 'garage' : 'main';
      var list = HOUSE_VOLUMES[name];
      return list.find(function (v, i) {
        return x >= v.x0 - 1e-6 && (x < v.x1 - 1e-6 || i === list.length - 1);
      }) || list[0];
    }
    /* The canonical facade (spec section 2.2: today's elevation, snapped
       onto the slot grid) is CANONICAL_JS, declared with the block model
       far above -- SPEC0 reads it there, and `var` hoisting means the
       VALUE has to be assigned above its earliest reader. It is the V2
       literal now, field for field services/house_facade.py's CANONICAL:
       no upgrade table in between (massing arc 2, task 5). */
    var SPEC = FACADE ? FACADE.spec : null;
    /* A feature's extent: its own slot's west edge to its last slot's
       east edge. Spans never cross a face (normalize truncates at the
       boundary), so one z, one eave and one room serve the whole span. */
    function spanX(feat) {
      var a = SLOTS[feat.slot], b = SLOTS[feat.slot + feat.span - 1] || a;
      return { x0: a.x0, x1: b.x1, cx: (a.x0 + b.x1) / 2, w: b.x1 - a.x0, slot: a };
    }
    var WINDOW_SIZES = { tall: [1.6, 3.7], standard: [1.55, 2.7], small: [1.0, 1.2] };
    /* The west-most door on the main face carries the front_door entry
       marker (spec section 4.4); PORCH_SPANS lets a gable find the porch
       it roofs; and DOOR_X4 / PORCH_FRONT_Z4 (declared with the south
       wall above, where the landscaping below still reads them) are
       published BY the builders, so a moved door moves its own front
       walk instead of stranding it at the old hand-typed x. */
    var FRONT_DOOR_SLOT = -1;
    var PORCH_SPANS = [];
    var webgl_coachLampGlass2 = null;   /* R5 NO_MERGE anchor, far below */

    function exteriorAnchor(g, lamp, role, reach) {
      lamp.material = lamp.material.clone();
      lamp.userData.lamp = true;
      lamp.userData.exteriorFixture = role;
      exteriorGlowMeshes.push(lamp);
      exteriorAnchors.push({g:g, lamp:lamp, role:role, reach:reach || 4.8});
    }
    function sideGarageLantern(g) {
      var lx=2.04, ly=2.72, lz=WALL_T4/2+0.20;
      box(0.12,0.42,0.10,C.ink,lx,ly,lz-0.1,g,sharp());
      var shade=box(0.23,0.30,0.22,0xf7e8c2,lx,ly,lz,g,{rough:0.45,unique:true});
      box(0.29,0.07,0.27,C.ink,lx,ly+0.19,lz,g,sharp());
      exteriorAnchor(g,shade,'garage',4.8);
    }
    var porchPoolTexture = null;
    function porchLight(g,x,y,z,width,depth) {
      var shade=cyl(0.18,0.22,0.10,0xf7e8c2,x,y,z,g,12,{rough:0.45,unique:true});
      box(0.42,0.06,0.42,C.ink,x,y+0.08,z,g,sharp());
      exteriorAnchor(g,shade,'porch',Math.max(5.2,Math.min(7,width)));
      // A local, soft pool remains available on low quality without point lights.
      if (!porchPoolTexture) porchPoolTexture=canvasTex(64,function(c,S) {
        var r=c.createRadialGradient(S/2,S/2,0,S/2,S/2,S/2);
        r.addColorStop(0,'rgba(255,209,135,0.55)'); r.addColorStop(0.5,'rgba(255,209,135,0.26)');
        r.addColorStop(1,'rgba(255,209,135,0)'); c.fillStyle=r;c.fillRect(0,0,S,S);
      });
      var pool=new T.Mesh(new T.PlaneGeometry(width,depth),new T.MeshBasicMaterial({
        map:porchPoolTexture,transparent:true,opacity:0,depthWrite:false,blending:T.AdditiveBlending}));
      pool.rotation.x=-Math.PI/2;pool.position.set(x,0.135,z);pool.userData.convex=true;
      pool.userData.porchLightPool=true;g.add(pool);porchPools.push(pool);
    }
    /* The bay's own glazing opts, identical to the garage block's GLZ
       (declared inside that closure, out of reach here). Identical
       VALUES are what matter: mat() keys on them, so both resolve to the
       same cached material rather than a second one. */
    var FGLZ = { rough: 0.16, metal: 0.0, envInt: 0.6 };

    /* ROOF VALLEYS (masking spec section 6): the block behind each face
       and the roof it was built with -- the same rows and forms the
       roof_main / garage_block_roof shellGable calls below read, at the
       block roofs' own BLOCK_PITCH -- so a street feature can find the
       deck it stands on from the slot table alone. This replaces the
       ROOF_PLANE_EAVE / roofPlaneEave table (the per-face eave, kept so
       a later per-block eave had one place to diverge): the block row's
       own `eave` IS that place now, read through its deck planes. */
    var FACE_BLOCKS = {
      main:         { block: FULL_HOUSE,   forms: ROOF_FORMS.main,   pitch: blockPitch('main') },
      garage_block: { block: GARAGE_BLOCK, forms: ROOF_FORMS.garage, pitch: blockPitch('garage') }
    };
    /* MASSING ARC 2: each row carries its OWN block's pitch (the model's
       roof.pitch_deg), so a deck plane is derived at the pitch the roof
       was actually built with rather than one shared constant. */
    /* every deck plane of the block's roof: the two slope decks, plus
       the two hipped ends when the form is a hip. The roof surface is
       the LOWEST of them at any (x, z). */
    function volumeDeckPlanes(v) {
      var out = [], pitch = v.roof.pitch_deg * Math.PI / 180;
      [-1, 1].forEach(function (sign) {
        out.push(deckPlane(v.x0, v.x1, v.north, v.south, v.eave,
                           v.roof.ridge, pitch, sign));
      });
      if (v.roof.form === 'hip') [-1, 1].forEach(function (sign) {
        out.push(hipEndPlane(v.x0, v.x1, v.north, v.south, v.eave,
                             v.roof.ridge, pitch, sign));
      });
      return out;
    }
    function blockDeckPlanes(face, x) {
      if (x !== undefined) return volumeDeckPlanes(volumeAt(face, x));
      var name = face === 'garage_block' ? 'garage' : 'main';
      return [].concat.apply([], HOUSE_VOLUMES[name].map(volumeDeckPlanes));
    }
    /* the STREET deck of the block: the south slope when the ridge runs
       x; a ridge on z puts a gable end on the street, so there is no
       one deck under a street feature (null) and the callers below fall
       back to the roof line. */
    function faceDeckPlane(face, x) {
      var v = volumeAt(face, x === undefined ? FACE_BLOCKS[face].block.west : x);
      if (v.roof.ridge === 'z') return null;
      return deckPlane(v.x0, v.x1, v.north, v.south, v.eave,
                       v.roof.ridge, v.roof.pitch_deg * Math.PI / 180, 1);
    }
    /* the roof line over (x, z) on that block: its centre planes' minimum */
    function roofY(face, x, z) {
      return blockDeckPlanes(face, x).reduce(function (y, pl) {
        return Math.min(y, planeY(pl, x, z));
      }, Infinity);
    }
    /* the buried region behind a face (clipBuried's `region`): under
       every deck plane (flipped: kept side below), behind the face --
       0.02 inside its outer plane, so the cut face lands inside the
       wall slab and never coplanar with the siding -- and forward of
       the block's back. No bound at the block's ENDS: a feature spans
       slots of its face and overhangs them by the block roof's own
       0.32, so it never leaves the roof's footprint, and the one thing
       an end bound would have kept is a deck's outer strip poking out
       through the block's gable-end wall under the rake (the bay gable
       at slot 0 did, 0.18 past the garage's west infill) -- which is
       exactly a feature running on where the block roof already is. */
    var FACE_INSET = 0.02;
    function buriedRegion(face, x) {
      var b = FACE_BLOCKS[face].block, C = window.HouseClip;
      var region = blockDeckPlanes(face, x).map(function (pl) { return C.flip(pl); });
      region.push({ n: [0, 0, -1], d: -(b.south - FACE_INSET) });
      region.push({ n: [0, 0, 1], d: b.north });
      return region;
    }
    /* ---- builders: one per kind, each its own registered piece -------
       Every builder makes a shellGroup(), fills it through the existing
       helpers (so materials and geometries stay cache hits) and ends at
       shellRegister() with the slot's fronting room. That registration
       is what gives a generated piece the navigation law, the ghost and
       cutaway verdicts, AO occlusion and NO_MERGE fencing with no new
       solver code at all (shell spec sections 4-5). */
    function windowAt(feat, unit) {
      var count = Math.max(1, Math.min(4, feat.count || 1));
      if (count > 1 && unit === undefined) {
        for (var index = 0; index < count; index++) windowAt(feat, index);
        return;
      }
      var e = spanX(feat), slot = e.slot, g = shellGroup();
      var size = WINDOW_SIZES[feat.size] || WINDOW_SIZES.standard;
      var w = size[0], h = size[1], cx = e.cx, z = slot.z, groupScale = 1;
      if (count > 1) {
        // Reserve outer shutters and casing, then fit adjacent framed units.
        var available = e.w - (feat.shutters ? 0.76 : 0.20);
        w = Math.max(0.35, Math.min(w, (available - 0.40 * count) / count));
        groupScale = Math.min(1, e.w / (count * (w + 0.40) + (feat.shutters ? 0.56 : 0)));
        cx += (unit - (count - 1) / 2) * (w + 0.40);
      }
      /* MASSING ARC 2 task 7 (spec section 3.2): a story-2 window is the
         same window one story higher -- ONE offset, applied to every y
         this builder writes, so there is no second window builder to
         drift. services/house_facade.py's normalize() has already
         dropped a story-2 feature whose block has one story, and it
         resolves overlap PER STORY, so a slot can legitimately carry one
         window on each floor: the piece name below therefore carries an
         `_s2` suffix, or the two would register under one name and the
         second would silently overwrite the first in every reader that
         looks a piece up by name. */
      var s2 = (feat.story === 2), yOff = s2 ? EXT_TOP4 : 0;
      function wtag(m) { if (m) m.userData.room = slot.room; return m; }
      /* SHUTTERS (spec section 3.2, both stories): two 0.28-wide boards,
         one either side, in the window's own FARMHOUSE.frame bucket so
         they cost no new material. The spec has carried `shutters` since
         the model's first version and nothing had ever built them.

         `halfW` is the half-extent of the WIDEST thing the branch below
         already built (the main branch's sill, w + 0.40; shellWindow's
         own sill trim, w + 0.32), and the board's INNER edge lands on
         it: a shutter beside the jambs alone would tuck behind the sill's
         ends and the piece would barely grow, which is not what a
         shutter looks like and not something a test could see. So a
         shuttered window is exactly 2 x 0.28 wider than the same window
         without them. `fz` is the outer face of the frame in that
         branch, so the board is flush with the casing rather than
         floating off it. */
      function shutters(wy, wh, halfW, fz) {
        if (!feat.shutters) return;
        [-1, 1].forEach(function (s) {
          if (count > 1 && ((s < 0 && unit !== 0) || (s > 0 && unit !== count - 1))) return;
          wtag(box(0.28, wh, 0.06, FARMHOUSE.frame,
                   cx + s * (halfW + 0.14), wy, fz, g, sharp()));
        });
      }
      if (slot.face === 'main') {
        /* the old swWindow, parameterised: casing, jambs and sill in
           FARMHOUSE.frame (one shared cache bucket), a 2x3 grille at
           DETAIL 2, a directly-built transparent pane the merge pass
           exempts by construction, and the interior sill at DETAIL 3 on
           the room side of the wall's own thickness. */
        var head = WIN_HEAD4 + yOff, wy = head - h / 2;
        wtag(box(w + 0.24, 0.13, 0.16, FARMHOUSE.frame, cx,
                 head + 0.065, z + 0.02, g, sharp()));
        [-(w / 2 + 0.07), (w / 2 + 0.07)].forEach(function (dx) {
          wtag(box(0.14, h + 0.13, 0.16, FARMHOUSE.frame, cx + dx, wy,
                   z + 0.02, g, sharp()));
        });
        wtag(box(w + 0.40, 0.10, 0.30, FARMHOUSE.frame, cx,
                 wy - h / 2 - 0.05, z + 0.05, g, sharp()));
        if (DETAIL >= 2) {
          wtag(box(0.07, h, 0.07, FARMHOUSE.frame, cx, wy, z + 0.022, g, sharp()));
          [wy - h / 6, wy + h / 6].forEach(function (my) {
            wtag(box(w, 0.07, 0.07, FARMHOUSE.frame, cx, my, z + 0.022, g, sharp()));
          });
        }
        var gl = new T.Mesh(new T.BoxGeometry(w, h, 0.03),
          new T.MeshStandardMaterial({ color: 0x9fc4dc, transparent: true,
                                       opacity: 0.9, roughness: 0.16,
                                       metalness: 0.0 }));
        gl.position.set(cx, wy, z + 0.03);
        gl.userData.glazing = true;      /* the night pass looks for this */
        /* VIEW-VOLUME MASKING (task 2): a plain box, built directly for
           its own transparent material -- still convex. This row is a
           kit anyway (windowAt), but stamping costs nothing and keeps
           chfFabricConvexity's nonconvex inventory honest. */
        gl.userData.convex = true;
        wtag(gl); finish(gl, true); g.add(gl);
        /* the interior sill is the ROOM's side of the wall's thickness,
           and there is no room behind a story-2 window -- the upper
           story is a sealed box -- so a story-2 window does not get one
           rather than hanging a cabinet-toned board inside it. */
        if (DETAIL >= 3 && !s2) {
          wtag(box(w + 0.10, 0.07, 0.30, C.cab, cx, wy - h / 2 - 0.10,
                   z - WALL_T4 - 0.10, g, { rough: 0.9 }));
        }
        /* the jambs stand 0.16 deep centred at z + 0.02, so their outer
           face is z + 0.10; a 0.06 shutter centred at z + 0.07 is flush
           with it. Half-width: the SILL's own outer edge (w/2 + 0.20),
           the widest element above. */
        shutters(wy, h + 0.13, w / 2 + 0.20, z + 0.07);
      } else {
        /* every other face takes the shell's own window idiom (dark pane
           behind a frame, glow at night), proud of the wall's outer skin
           exactly where shellWall placed its own. Head 4.15: today's
           wing head, centre 2.80 plus half of a 2.70 pane. */
        var fz = slot.z + WALL_T4 / 2 + 0.05;
        shellWindow(g, cx, 4.15 + yOff - h / 2, fz, 0, w, h, true);
        /* shellWindow's widest element is its sill trim (w + 0.32); its
           outer casing face is fz + 0.11, so a 0.06 board at fz + 0.08
           is flush with it. */
        shutters(4.15 + yOff - h / 2, h, w / 2 + 0.16, fz + 0.08);
      }
      /* VIEW-VOLUME MASKING (task 2): a window is a frame -- casing,
         jambs and sill boxes arranged around a hole, and on 'main' faces
         a grille -- non-convex as the composite mergeStatic will make of
         it. Kept or dropped whole, never clipped mesh by mesh: a window
         is a hole in a wall, and when the mask takes the wall around it
         the kit rule (box centre masked) takes the window with it, so
         no black frame stands floating in the opening. */
      g.scale.x = groupScale; g.position.x = e.cx * (1 - groupScale);
      shellRegister(g, 'facade_' + slot.face + '_window_' + feat.slot +
                    (s2 ? '_s2' : '') + (count > 1 ? '_unit' + unit : ''), [0, 0, 1], slot.room, true);
    }

    function doorAt(feat) {
      var e = spanX(feat), slot = e.slot, g = shellGroup();
      var x = e.cx, z = slot.z + 0.02;   /* proud of the exterior face:
        the wall carries no cut opening, so a leaf at the wall's own mid-
        thickness would be entombed in solid mass. Casing, panels and
        knob all stack outward from this one anchor. */
      var entry = (feat.slot === FRONT_DOOR_SLOT);
      function dtag(m) {
        if (m) { m.userData.room = slot.room;
                 if (entry) m.userData.entry = 'front_door'; }
        return m;
      }
      /* the leaf: the decorative front door's own chamfered geometry
         rotated 90 degrees (a cache hit, not a second geometry at the
         swapped dimensions). style.door 'wood' keeps the wood map; every
         other door colour drops the map and takes the palette hex,
         because a red door mapped with oak reads as neither. */
      var woodMap = (FSTYLE.door === 'wood') ? woodDoor : null;
      var doorCount = feat.count === 2 ? 2 : 1;
      for (var leafIndex = 0; leafIndex < doorCount; leafIndex++) {
        var leafX = x + (leafIndex - (doorCount - 1) / 2) * 1.4;
        var leaf = new T.Mesh(
          NICE ? chamferGeo(0.14, 3.2, 1.4, 0.04) : new T.BoxGeometry(0.14, 3.2, 1.4),
          PBR ? new T.MeshStandardMaterial(woodMap
                  ? { map: woodMap, roughness: 0.65 }
                  : { color: FARMHOUSE.wood, roughness: 0.65 })
              : new T.MeshLambertMaterial(woodMap
                  ? { color: 0xc9a06c, map: woodMap }
                  : { color: FARMHOUSE.wood }));
        leaf.rotation.y = Math.PI / 2;
        leaf.position.set(leafX, 1.6, z);
        dtag(leaf); finish(leaf); g.add(leaf);
        if (DETAIL >= 2) {
          dtag(box(0.90, 1.20, 0.02, 0x6f5433, leafX, 2.14, z + 0.075, g, WOODM));
          dtag(box(0.90, 0.98, 0.02, 0x6f5433, leafX, 0.82, z + 0.075, g, WOODM));
          dtag(box(0.74, 1.04, 0.04, 0xc79b63, leafX, 2.14, z + 0.080, g, WOODM));
          dtag(box(0.74, 0.82, 0.04, 0xc79b63, leafX, 0.82, z + 0.080, g, WOODM));
        }
        var knob = latheAt('knob', [0.06, 0.1, 0.06], 0xd8c48a, leafX + (leafIndex === 1 ? -0.55 : 0.55),
                           1.6, z + 0.07, g, CHROME);
        knob.rotation.x = Math.PI / 2;
        dtag(knob);
      }
      var halfFrame = doorCount === 2 ? 1.35 : 0.65;
      dtag(box(0.14, 3.44, 0.13, 0xe4ddd1, x - halfFrame, 1.72, z, g, sharp()));
      dtag(box(0.14, 3.44, 0.13, 0xe4ddd1, x + halfFrame, 1.72, z, g, sharp()));
      dtag(box(doorCount === 2 ? 3.26 : 1.86, 0.14, 0.13, 0xe4ddd1, x, 3.37, z, g, sharp()));
      /* the coach lamp beside the door: the garage lamp's own shade,
         finial and cap language (a geometry cache hit through latheAt),
         and the only mesh carrying userData.lamp inside THIS piece's own
         merge pass -- webgl_coachLampGlass2 fences it, far below. Room
         tagged but never entry tagged: a lamp is not a door. */
      var lampX = x - (doorCount === 2 ? 1.65 : 0.85), lampZ = slot.z + 0.05;
      var lamp = latheAt('shade', [0.37, 0.34, 0.37], 0xf7e8c2,
                         lampX, 2.59, lampZ, g, GLOSS);
      lamp.userData.room = slot.room;
      lamp.userData.lamp = true;         /* geometry only: the night pass
                                            lights it */
      lamp.userData.glazing = true;
      exteriorAnchor(g,lamp,'door',4.8);
      if (entry) webgl_coachLampGlass2 = lamp;
      latheAt('finial', [0.22, 0.06, 0.22], C.ink, lampX, 2.93, lampZ, g,
              { rough: 0.5 }).userData.room = slot.room;
      var cap = cyl(0.20, 0.20, 0.05, C.ink, lampX, 2.57, lampZ, g, 4,
                    { rough: 0.5 });
      cap.rotation.y = Math.PI / 4; cap.userData.room = slot.room;
      box(0.10, 0.34, 0.09, C.ink, lampX, 2.96, lampZ - 0.05, g,
          { rough: 0.5 }).userData.room = slot.room;
      box(0.34, 0.09, 0.05, C.ink, lampX, 3.16, lampZ - 0.02, g,
          { rough: 0.5 }).userData.room = slot.room;
      if (entry) DOOR_X4 = x;            /* the front walk follows */
      /* VIEW-VOLUME MASKING (task 2): a door is a leaf, casing, panels,
         a lathe knob and a coach lamp (lathe + cylinder cap) -- a kit,
         never a single convex solid. */
      var doorScale = doorCount === 2 ? Math.min(1, e.w / 3.7) : 1;
      g.scale.x = doorScale; g.position.x = x * (1 - doorScale);
      shellRegister(g, 'facade_' + slot.face + '_door_' + feat.slot,
                    [0, 0, 1], slot.room, true);
    }

    function porchAt(feat) {
      var e = spanX(feat), slot = e.slot, g = shellGroup();
      var type = feat.type || 'covered';
      var W = e.w, X = e.cx, z0 = slot.z;
      /* a stoop is a slab and a step; sitting and covered keep today's
         depth and eave. */
      var depth = (type === 'stoop') ? 1.6 : PORCH_DEPTH4;
      var frontZ = z0 + depth, eave = PORCH_EAVE4;
      function ptag(m) { if (m) m.userData.room = slot.room; return m; }
      ptag(box(W, 0.28, depth, FARMHOUSE.stoop, X, -0.02, z0 + depth / 2, g, sharp()));
      /* the step is 2.4 wide on today's porch and the porch's own width
         on anything narrower, so a span-1 porch does not sprout a step
         wider than the slab it serves. */
      ptag(box(Math.min(2.4, W), 0.14, 0.65, FARMHOUSE.stoop, X, -0.16,
               frontZ + 0.325, g, sharp()));
      if (type !== 'stoop') {
        /* the approach stays clear of whatever door shares this span.
           The porch is no longer centred ON the door the way the hand
           block was (slot 9 span 4 against a door at slot 10), so each
           bench takes the room left on its own side of the door and is
           dropped when there is not enough of it. */
        var doorX = null;
        (((SPEC || CANONICAL_JS).ground) || []).forEach(function (f) {
          if (f.kind === 'door' && f.slot >= feat.slot &&
              f.slot < feat.slot + feat.span) doorX = spanX(f).cx;
        });
        var A = (doorX === null) ? X : doorX;
        [-1, 1].forEach(function (side) {
          var px = X + side * (W / 2 - 0.22);
          [z0 + 0.35, frontZ - 0.20].forEach(function (pz) {
            ptag(box(0.24, eave - 0.12, 0.24, FARMHOUSE.wood,
                     px, (eave + 0.12) / 2, pz, g, sharp(WOODM)));
          });
          ptag(box(0.24, 0.28, depth, FARMHOUSE.wood,
                   px, eave - 0.14, z0 + depth / 2, g, sharp(WOODM)));
          if (type !== 'sitting') return;
          var inner = A + side * 1.0, outer = X + side * (W / 2 - 0.34);
          var bw = Math.min(1.95, Math.abs(outer - inner));
          if (bw < 1.0) return;          /* no room: no bench, no stub */
          var bx = inner + side * bw / 2, bz = z0 + 1.5, dxe = bw / 2 - 0.195;
          ptag(box(bw, 0.14, 0.72, FARMHOUSE.wood, bx, 0.73, bz, g, sharp(WOODM)));
          [-dxe, dxe].forEach(function (dx) {
            [-0.25, 0.25].forEach(function (dz) {
              ptag(box(0.12, 0.54, 0.12, FARMHOUSE.frame,
                       bx + dx, 0.40, bz + dz, g, sharp()));
            });
            ptag(box(0.12, 0.7, 0.12, FARMHOUSE.frame,
                     bx + dx, 1.00, bz - 0.27, g, sharp()));
          });
          [0.99, 1.23].forEach(function (by) {
            ptag(box(bw, 0.18, 0.10, FARMHOUSE.wood,
                     bx, by, bz - 0.30, g, sharp(WOODM)));
          });
        });
        ptag(box(W, 0.28, 0.24, FARMHOUSE.wood, X, eave - 0.14,
                 frontZ - 0.20, g, sharp(WOODM)));
      }
      PORCH_SPANS.push({ slot: feat.slot, span: feat.span, frontZ: frontZ,
                         roof: feat.roof || null });
      if (slot.face === 'main') PORCH_FRONT_Z4 = frontZ;
      if (type !== 'stoop' && feat.roof) {
        var lamps = Math.max(1,Math.ceil(W/6));
        for (var pi=0;pi<lamps;pi++) porchLight(g,e.x0+W*(pi+0.5)/lamps,
                 eave-0.24,z0+depth/2,Math.min(W/lamps,6),depth*0.94);
      }
      /* MASSING ARC 2 task 8 (spec 2026-09-17 section 2): THE PORCH OWNS
         ITS ROOF. `roof: 'gable'` used to be replayed through gableAt by
         a bridge in buildElevation, which registered the porch's own
         roof under a free gable's name (facade_<face>_gable_<slot>_*);
         it is built here now, under the porch's own name, and the bridge
         is gone. Every number is the one that bridge computed -- the
         porch's eave (PORCH_EAVE4, the posts it rests on), its own front
         edge, featureBack's meet with the block deck and PITCH_FAMILY --
         so the canonical's porch roof is the same roof, renamed.
         A stoop has no posts to carry a roof, so it never gets one. */
      if (feat.roof === 'gable' && type !== 'stoop') {
        var ridge = eave + 0.18 + (W / 2) * Math.tan(PITCH_FAMILY);
        shellGable('facade_' + slot.face + '_porch_' + feat.slot + '_roof',
                   e.x0, e.x1, featureBack(slot, X, ridge), frontZ, eave, 'z',
                   slot.room, [1], PITCH_FAMILY, null, null, null,
                   buriedRegion(slot.face, e.cx));
      }
      if ((feat.roof === 'flat' || feat.roof === 'shed' || feat.roof === 'mixed') && type !== 'stoop') {
        // One continuous cover. The gable and shed subtract each other's
        // buried volumes, leaving their higher surfaces joined at valleys.
        var pg = shellGroup(), C = window.HouseClip;
        var angle = feat.roof === 'flat' ? 0 : Math.min(PITCH_FAMILY, Math.atan2(1.0, depth));
        var sn = [0, Math.cos(angle), Math.sin(angle)];
        var sd = sn[1] * (eave + 0.18) + sn[2] * frontZ;
        var zb = z0 - 0.12, zf = frontZ + FULL_HOUSE.overhang;
        var yb = (sd - sn[2] * zb) / sn[1], yf = (sd - sn[2] * zf) / sn[1];
        var pd = shellBox(pg, W + 2 * FULL_HOUSE.overhang, 0.18,
                          Math.hypot(zf - zb, yb - yf), NICE ? 0xffffff : FARMHOUSE.roofTone,
                          X, (yb + yf) / 2, (zb + zf) / 2,
                          { rough: 0.9, map: shingleT });
        pd.rotation.x = angle;
        shellBox(pg, W + 2 * FULL_HOUSE.overhang, 0.22, 0.14,
                 FARMHOUSE.trim, X, yf - 0.1, zf);
        if (feat.roof === 'mixed') {
          var gs = feat.slot + (feat.gable_offset || 0);
          var ge = Math.min(feat.slot + feat.span, gs + (feat.gable_span || 2));
          var gx0 = SLOTS[gs].x0, gx1 = SLOTS[ge - 1].x1;
          var gp = [-1, 1].map(function (sign) {
            return deckPlane(gx0, gx1, zb, frontZ, eave, 'z', PITCH_FAMILY, sign);
          });
          var gableRegion = [
            { n: [1, 0, 0], d: gx0 - FULL_HOUSE.overhang },
            { n: [-1, 0, 0], d: -gx1 - FULL_HOUSE.overhang }
          ].concat(gp.map(function (p) { return C.flip({ n: p.n, d: p.d }); }));
          clipBuried(pg, gableRegion);
          shellGable('facade_' + slot.face + '_porch_' + feat.slot + '_gable',
                     gx0, gx1, zb, frontZ, eave, 'z', slot.room, [1],
                     PITCH_FAMILY, null, null, null,
                     [[C.flip({ n: sn, d: sd })], buriedRegion(slot.face, e.cx)]);
        }
        clipBuried(pg, buriedRegion(slot.face, e.cx));
        shellRegister(pg, 'facade_' + slot.face + '_porch_' + feat.slot + '_shed',
                      [0, 0, 1], slot.room);
      }
      /* VIEW-VOLUME MASKING (task 3, fix round 1 ruling): a porch is NOT
         a kit. Every piece of it is a box() -- slab, step, posts, beam,
         roof deck, rails, the sitting bench -- each convex on its own,
         so it clips per mesh like a wall: a post outside the pyramid
         stays, the roof deck inside it is cut with a cap. Task 2 had it
         a kit, and the kit test (box centre) put the porch's centre
         (~y 2.4, ground to roof) under the room box's floor line, so
         the whole porch -- roof deck included -- stood across the
         living view. */
      shellRegister(g, 'facade_' + slot.face + '_porch_' + feat.slot,
                    [0, 0, 1], slot.room, false);
    }

    function garageDoorAt(feat) {
      /* The one builder that does NOT make its own group: the leaves ride
         garageDoorG so the dollhouse's openable-door trick (the whole
         group hides from inside the bay) keeps working, and that group's
         own regFabric call below still registers it as 'garage_door'.
         (`GDOOR` below is that group, or -- for a side-entry garage --
         the turned sub-group of it the west-face leaf hangs in.) */
      var e = spanX(feat), slot = e.slot, cx = e.cx;
      /* The BAY is fixed: piers at -17.58 and -13.22, 0.76 wide, leaving
         a 3.6 opening -- the one today's single leaf fills. So `leaves`
         sets the leaf COUNT inside that opening, never the opening's
         width: two leaves are half the width each with a centre stile
         between them, and a wider leaf field would simply bury itself in
         the piers. Every applied detail scales with its own leaf (k), so
         a narrow leaf reads as a door and not as a shrunk texture. */
      var FIELD = 3.6, STILE = 0.12;
      var n = (feat.leaves === 2) ? 2 : 1;
      var lw = (FIELD - (n - 1) * STILE) / n, k = lw / FIELD;
      /* MASSING ARC 2 task 6 (fix round 1): + GAR_DZ. Every leaf part
         below is placed off this one `z`, and it was the last piece of
         the bay still nailed to the old face line -- at garage depth 6
         the opening moved out and the door stood six units back inside
         the block, hanging over garage_void_floor. This IS the slot's
         own z less the 0.08 the leaf has always stood inside the face
         (slot.z - 0.08 === 10.02 + GAR_DZ), written as the literal plus
         the depth so the canonical is literally unchanged. */
      var y = 1.6, z = 10.02 + GAR_DZ, dh = 3.0;
      var style = feat.style || 'carriage';
      var garageColour = BLOCKS.garage.door_colour;
      var doorTone = !garageColour || garageColour === 'wood' ? FARMHOUSE.wood
                     : garageColour === 'black' ? 0x252a2d : pal('body', garageColour, 0xf4f1e9);
      var panelTone = garageColour && garageColour !== 'wood'
                      ? new T.Color(doorTone).multiplyScalar(0.84).getHex() : C.wood2;
      var frameTone = garageColour ? doorTone : FARMHOUSE.frame;
      /* SIDE-ENTRY (task 8): the leaf hangs on the block's WEST face, so
         it is built in a group of its own -- a quarter turn about y,
         stood on the block's west line at SIDE_DOOR_Z -- and every
         number below is read in THAT group's local frame. The turn is
         -PI/2 so local +z (the side every applied detail stacks toward:
         seams, straps, bolts, top lights) becomes world -x, the way the
         face actually looks; +PI/2 would point the whole door's face
         east, into the bay. `cx` 0 centres the field on the opening and
         `z` stands the leaf on the wall's OUTER skin (WALL_T4/2 + 0.07),
         exactly as the street leaf stands 0.08 proud of its own piers.
         Nothing else of the bay is built for a side garage: the piers,
         header, lintel, band and their details ARE the street face, and
         shellWall('garage_front_wall') is that face now. */
      var GDOOR = garageDoorG;
      if (GARAGE_SIDE) {
        GDOOR = new T.Group();
        GDOOR.rotation.y = -Math.PI / 2;
        GDOOR.scale.set((feat.sideWidth || SIDE_DOOR.width) / 3.6, SIDE_DOOR.height / 3.0, 1);
        GDOOR.position.set(GARAGE_BLOCK.west - (feat.third ? SIDE_PROJECTION : 0), 0.1 * (1 - GDOOR.scale.y), feat.sideZ === undefined ? SIDE_DOOR_Z : feat.sideZ);
        if (feat.third && SIDE_PROJECTION) {
          GDOOR.rotation.y = 0;
          GDOOR.position.x = POP_X;
          GDOOR.position.z = POP_FRONT;
        }
        garageDoorG.add(GDOOR);
        cx = 0; z = WALL_T4 / 2 + 0.07;
        sideGarageLantern(GDOOR);
      }
      function gtag(m) { if (m) m.userData.room = slot.room; return m; }
      function gGlass(w, h, gx, gy, gz) {
        var m = box(w, h, 0.03, 0x9fc4dc, gx, gy, gz, GDOOR, FGLZ);
        m.userData.glazing = true;       /* the lighting pass looks for this */
        return gtag(m);
      }
      function leafAt(lx) {
        if (style === 'glass') {
          // A grid of panes framed by rails, never glass buried in a solid slab.
          var columns = Math.max(2, Math.round(4 * k)), rows = 4, rail = 0.10;
          for (var col=0; col<=columns; col++)
            gtag(box(rail, dh, 0.14, frameTone, lx-lw/2+col*lw/columns, y, z, GDOOR, {rough:0.35,metal:0.25}));
          for (var row=0; row<=rows; row++)
            gtag(box(lw, rail, 0.14, frameTone, lx, y-dh/2+row*dh/rows, z, GDOOR, {rough:0.35,metal:0.25}));
          for (var col=0; col<columns; col++) for (var row=0; row<rows; row++)
            gGlass(lw/columns-rail, dh/rows-rail,
                   lx-lw/2+(col+0.5)*lw/columns, y-dh/2+(row+0.5)*dh/rows, z+0.06);
          return;
        }
        gtag(rbox(lw, dh, 0.14, 0.05, doorTone, lx, y, z, GDOOR, WOODM));
        if (DETAIL < 2) return;
        if (style === 'panel') {
          /* four raised panels in a 2x2 grid: no brace, no lights. */
          [-1, 1].forEach(function (sx) {
            [-1, 1].forEach(function (sy) {
              gtag(box(lw / 2 - 0.42 * k, dh / 2 - 0.42, 0.04, panelTone,
                       lx + sx * lw / 4, y + sy * dh / 4, z + 0.08,
                       GDOOR, WOODM));
            });
          });
          return;
        }
        /* carriage: board seams, then the strap hardware -- two black
           diagonals crossing the leaf corner to corner plus five bolt
           medallions at the corners and the crossing. Both diagonals
           share one centre, one derived length and one angle, mirrored
           by sign. */
        [1.0, 1.8, 2.6].forEach(function (sy) {
          gtag(box(3.4 * k, 0.05, 0.06, panelTone, lx, sy, z + 0.08, GDOOR));
        });
        var SDX = 1.65 * k, SDY = 1.45;
        var SLEN = Math.sqrt(SDX * SDX * 4 + SDY * SDY * 4);
        var SANG = Math.atan2(SDX * 2, SDY * 2);
        [1, -1].forEach(function (sign) {
          var strap = gtag(box(0.09, SLEN, 0.025, FARMHOUSE.frame,
                               lx, y, z + 0.08, GDOOR, { rough: 0.5 }));
          strap.rotation.z = sign * SANG;
        });
        [[lx - SDX, y - SDY], [lx + SDX, y - SDY], [lx - SDX, y + SDY],
         [lx + SDX, y + SDY], [lx, y]].forEach(function (p) {
          gtag(cyl(0.05, 0.05, 0.03, C.ink, p[0], p[1], z + 0.09,
                   GDOOR, 8, { rough: 0.4, metal: 0.6 }));
        });
        /* the top-light row every carriage door carries: four across
           today's full-width leaf, fewer on a narrow one, spread over
           the same fraction of the leaf (three 0.68 gaps across 3.6). */
        var nl = Math.max(2, Math.round(4 * k)), lspan = lw * 0.5667;
        for (var li = 0; li < nl; li++) {
          var gx = lx + (li - (nl - 1) / 2) * lspan / (nl - 1);
          gGlass(0.52 * k, 0.30, gx, 2.86, z + 0.08);
          gtag(box(0.60 * k, 0.38, 0.05, FARMHOUSE.frame, gx, 2.86,
                   z + 0.065, GDOOR));
        }
      }
      for (var i = 0; i < n; i++) {
        leafAt(cx - FIELD / 2 + lw / 2 + i * (lw + STILE));
      }
      if (n === 2) {
        gtag(box(STILE, dh, 0.06, frameTone, cx, y, z + 0.08, GDOOR));
      }
    }
    /* ROOF VALLEYS (masking spec section 6): where a street feature's
       ridge stands and how far back it runs.

       THE HEIGHT RULE. A feature's eave is set from the roof line at the
       street wall: `eave = roofY(face, cx, face z) - 0.18`, so its own
       roofEave (eave + 0.18, shellGable's deck centre at the wall line)
       IS the parent deck's centre plane there and its ridge stands proud
       of that plane at the wall by exactly its own rise, half * tan
       (PITCH_FAMILY). On a block with ridge x that is the block eave,
       which the bay gable already used; the ordinary street gable used
       to sit 0.8 lower (the block eave - 0.8: the porch beam's height)
       whether or not there was a porch under it.

       THE PORCH EXCEPTION. A gable sharing a span with a porch IS that
       porch's roof, on the porch's posts and beam (PORCH_EAVE4, 4.8),
       and stays there: raised 0.8 to the rule it would float clear of
       the posts it rests on. Its ridge still stands proud at the wall
       -- canonical facade_main_porch_8_roof (the porch's own gable since
       task 8; it was gable_8 while the replay bridge named it):
       7.505 against the plane's 5.78, 1.725, its
       rise 2.525 less the 0.8 -- and in FRONT of the wall its low eaves
       pass under the main eave as the porch roof always has; only what
       is behind the wall and under the deck is buried, and that is what
       the clip removes.

       THE BACK. The feature runs back at least the old 2.8 and, when
       its ridge meets the parent deck further back than that (the ridge
       line rises no further; the deck keeps climbing), to 0.6 past the
       meet point -- so the ridge cap (0.125 over the ridge line) and the
       deck's own top face close at a point on the parent roof, the two
       valleys meeting there, instead of a square cut end hanging above
       it. Everything behind the meet is under the deck and clipped
       away; the 0.6 is what the cap's height and the deck's thickness
       need. A ridge on z has no meet point along z (the roof line does
       not change with z), so the old depth stands. */
    function featureEave(slot, cx) {
      return roofY(slot.face, cx, slot.z) - 0.18;
    }
    function featureBack(slot, cx, ridge) {
      var pl = faceDeckPlane(slot.face, cx), back = slot.z - 2.8;
      if (!pl || Math.abs(pl.n[2]) < 1e-6) return back;
      var meet = (pl.d - pl.n[0] * cx - pl.n[1] * ridge) / pl.n[2];
      return Math.min(back, meet - 0.6);
    }
    function gableWindow(name, x0, x1, front, eave, pitch, room, buried) {
      var rise = (x1 - x0) / 2 * Math.tan(pitch);
      if (rise < 0.8) return;
      var g = shellGroup(), h = Math.min(1.4, rise * 0.42);
      shellWindow(g, (x0 + x1) / 2, eave + rise * 0.40,
                  front + 0.18, 0, Math.min(1.2, (x1 - x0) * 0.24), h, true);
      if (buried) (Array.isArray(buried[0]) ? buried : [buried]).forEach(function (r) { clipBuried(g, r); });
      shellRegister(g, name + '_attic_window', [0, 0, 1], room, true);
    }
    function gableAt(feat) {
      var e = spanX(feat), slot = e.slot;
      var name = 'facade_' + slot.face + '_gable_' + feat.slot;
      var region = buriedRegion(slot.face, e.cx);
      if (feat.slot >= GARAGE_BAY_SLOTS[0] && feat.slot <= GARAGE_BAY_SLOTS[1] &&
          feat.slot + feat.span - 1 <= GARAGE_BAY_SLOTS[1]) {
        /* the street-facing garage gable (spec section 2.1: today's
           garage_gable, reproduced from the spec instead of by hand) --
           it intersects the lower cross roof rather than sitting on the
           bay's own eave, so it keeps that call's z range and eave. Keyed
           on the BAY's own slots, not the face: garage_block also carries
           the mudroom now, and a gable further east on that face (over
           the mudroom) is an ordinary street gable, not this special
           case. The full-span check is defensive: services/house_facade.py's
           normalize() already clips a bay-starting roof feature's span to
           the bay (_clip_to_face), so every spec this actually renders is
           pre-clipped, but a feature that somehow reached here spanning
           past the bay falls through to the ordinary gable below rather
           than stretching the bay's fixed z range over the mudroom. */
        /* the bay's eave IS the block eave (featureEave gives the same
           5.6 on a ridge-x block); its z range 4.0..10.1 already reaches
           past the meet point (5.47 for the canonical bay), so the
           valley closes on its own */
        /* MASSING ARC 2 task 6: + GAR_DZ. The bay's z range is the one
           street feature in this file written as absolutes rather than
           off slot.z, so a garage DEPTH has to carry it out with the
           face; left at 4.0..10.1 it stays where the old face was, which
           at depth 6 is six units inside the block, under the block roof
           -- buriedRegion then clips the whole gable away and the piece
           registers with nothing in it. */
        shellGable(name, e.x0, e.x1, 4.0 + GAR_DZ, 10.1 + GAR_DZ,
                   featureEave(slot, e.cx), 'z',
                   slot.room, [1], PITCH_FAMILY, null, null, null, region);
        if (feat.window) gableWindow(name, e.x0, e.x1, 10.1 + GAR_DZ,
                                     featureEave(slot, e.cx), PITCH_FAMILY, slot.room, region);
        return;
      }
      /* a porch sharing the span carries the gable out to its own front
         edge (today's porch_roof) and hands it the porch's eave;
         otherwise the gable sits on the wall face, with only its roof
         overhang extending toward the street. */
      /* MASSING ARC 2 task 8: ... unless that porch is GABLED, in which
         case the porch built its own roof (porchAt, above) and this is a
         second gable over the same posts. normalize() already drops a
         gable feature covering a gabled porch, so no spec that renders
         reaches this line; the guard is belt and braces for a hand-built
         or replayed feature. */
      var front = slot.z, porch = false;
      PORCH_SPANS.forEach(function (p) {
        if (!volumeAt(slot.face, e.cx).upper &&
            p.slot < feat.slot + feat.span && feat.slot < p.slot + p.span &&
            p.roof !== 'gable' && p.roof !== 'mixed') {
          front = Math.max(front, p.frontZ); porch = true;
        }
      });
      var eave = porch ? PORCH_EAVE4 : featureEave(slot, e.cx);
      var ridge = eave + 0.18 + (e.w / 2) * Math.tan(PITCH_FAMILY);
      shellGable(name, e.x0, e.x1, featureBack(slot, e.cx, ridge), front,
                 eave, 'z', slot.room, [1], PITCH_FAMILY, null, null, null,
                 region, featClad(feat));
      if (feat.window) gableWindow(name, e.x0, e.x1, front, eave, PITCH_FAMILY, slot.room, region);
    }
    /* PER-FEATURE CLADDING (task 8, spec section 2): a roof feature may
       wear a skin its parent block does not -- a shingled shed on a
       board-and-batten wall. `cladding` is the feature's own material
       over the block's own body colour, and absent it the block's tile
       stands, which is every canonical feature. */
    function featClad(feat) {
      return feat && feat.cladding ? cladTex(feat.cladding, FARMHOUSE.body)
                                   : null;
    }

    function dormerAt(feat) {
      /* a box on the face's roof plane with its own mini gable and, by
         default, a window. The roof line under it is the block's own
         deck planes (roofY), whatever form and ridge the block has. */
      var e = spanX(feat), slot = e.slot, g = shellGroup();
      var w = Math.max(1.2, e.w - 0.4);
      var zc = slot.z - 1.6, region = buriedRegion(slot.face, e.cx);
      /* ROOF VALLEYS (masking spec section 6): the box STANDS on the
         roof -- its bottom edge at its front face (zc + 0.8) is the
         roof line there (roofY: the block's own deck planes, no longer
         an assumed Math.PI / 8), so the whole 1.9 of its front, window
         included, is out of the roof; the back of the flat-bottomed box
         is under the deck (the plane climbs 0.66 over the box's 1.6)
         and the clip takes it. It used to be CENTRED on the plane at
         zc, its front face 0.62 buried and the window's sill 0.22 into
         the shingles. */
      var y = roofY(slot.face, e.cx, zc + 0.8) + 0.95;
      /* task 8: the dormer's own `cladding`, when it has one, over the
         block's tile -- box and gable infill alike, so the whole dormer
         reads as one material and not a shingled hat on a batten box. */
      var dclad = featClad(feat);
      var dormerFront = zc + 0.8;
      var dormerRidge = y + 0.95 + 0.18 + w / 2 * Math.tan(PITCH_FAMILY);
      var dormerBack = featureBack(slot, e.cx, dormerRidge);
      var bottom = Math.min(roofY(slot.face, e.cx - w / 2, dormerFront),
                            roofY(slot.face, e.cx + w / 2, dormerFront)) - 0.12;
      var top = y + 0.95;
      shellBox(g, w, top - bottom, dormerFront - dormerBack,
               cladColour(BLOCK_OF_FACE[slot.face]),
               e.cx, (top + bottom) / 2, (dormerBack + dormerFront) / 2,
               { rough: 0.95, map: dclad || CLAD(BLOCK_OF_FACE[slot.face]) });
      if (feat.window !== false) {
        shellWindow(g, e.cx, y, zc + 0.85, 0, Math.min(1.1, w - 0.5), 1.1, true);
      }
      /* VIEW-VOLUME MASKING (task 2, corrected): not a kit -- the box and
         the window's boxes are all stamped convex; Task 3 clips them
         pre-merge, same as any other windowed wall. */
      clipBuried(g, region);
      shellRegister(g, 'facade_' + slot.face + '_dormer_' + feat.slot,
                    [0, 0, 1], slot.room);
      /* _dormer_<slot>_roof, not _dormerroof_<slot>: the registry reads
         kind and slot straight out of the name, and a dormer's roof is
         the same dormer feature. Its eave is the box top, as before
         (the height rule's own form: ridge = box top + 0.18 + rise). */
      shellGable('facade_' + slot.face + '_dormer_' + feat.slot + '_roof',
                 e.cx - w / 2, e.cx + w / 2, dormerBack, dormerFront,
                 y + 0.95, 'z', slot.room, [1], PITCH_FAMILY,
                 null, null, null, region, dclad);
    }

    function shedAt(feat) {
      /* THE SHED (task 8, spec 2026-09-17 section 2): a SINGLE slope,
         the one roof form the elevation could not make. It runs from the
         feature's own front edge (2.2 proud of the face, a dormer's own
         projection) back to the parent deck it dies into, so its high
         back edge sits ON the block's roof line -- which is why nothing
         of it is ever buried, and why it needs no ridge and no end
         infill. With `window` it is a shed DORMER: a clad box under the
         slope carrying one shell window, registered as its OWN row
         (facade_<face>_shed_<slot>_box) so the mask can take the glass
         and leave the deck, exactly as a dormer's roof and box part. */
      var e = spanX(feat), slot = e.slot, g = shellGroup();
      var region = buriedRegion(slot.face, e.cx);
      var clad = featClad(feat) || shingleT;
      var zf = slot.z + 2.2, yf = featureEave(slot, e.cx) - 0.3;
      var zb = slot.z - 0.8, yb = roofY(slot.face, e.cx, zb);
      var len = Math.hypot(zf - zb, yb - yf), pitch = Math.atan2(yb - yf, zf - zb);
      /* the deck's own centre sits 0.09 (half its thickness) above the
         line front-edge -> back-edge, so its UNDER side is that line:
         the back edge lands on the deck plane rather than 0.09 through
         it. */
      var deck = shellBox(g, e.w, 0.18, len, NICE ? 0xffffff : FARMHOUSE.roofTone,
                          e.cx, (yf + yb) / 2 + 0.09, (zf + zb) / 2,
                          { rough: 0.9, map: clad });
      deck.rotation.x = pitch;
      shellBox(g, e.w + 0.16, 0.22, 0.14, FARMHOUSE.trim, e.cx, yf - 0.02, zf + 0.02);
      clipBuried(g, region);
      shellRegister(g, 'facade_' + slot.face + '_shed_' + feat.slot,
                    [0, 0, 1], slot.room);
      if (!feat.window) return;
      var bg = shellGroup(), y = yf - 0.95, w = Math.max(1.2, e.w - 0.4);
      shellBox(bg, w, 1.7, 1.4, cladColour(BLOCK_OF_FACE[slot.face]),
               e.cx, y, slot.z + 1.4,
               { rough: 0.95, map: featClad(feat) || CLAD(BLOCK_OF_FACE[slot.face]) });
      shellWindow(bg, e.cx, y, slot.z + 2.15, 0, Math.min(1.1, w - 0.5), 1.0, true);
      clipBuried(bg, region);
      /* not a kit, for dormerAt's own reason: the box and the window's
         boxes are every one of them convex, so the mask clips them in
         place rather than keeping or dropping the assembly whole. */
      shellRegister(bg, 'facade_' + slot.face + '_shed_' + feat.slot + '_box',
                    [0, 0, 1], slot.room);
    }

    function hipEndAt(feat) {
      /* a clipped triangular return closing the span's ends on the roof
         plane -- the hipped alternative to a gable end. */
      var e = spanX(feat), slot = e.slot, g = shellGroup();
      /* Spec 2026-09-17 blocks section 0: the fin's own plane is the
         FACADE's pitch (PITCH_FAMILY), like every other roof feature
         on this elevation -- it was a second copy of the block pitch's
         literal. The cgeo key already carries depth and rise, so a new
         pitch is a new cached geometry rather than a stale one. */
      var plane = PITCH_FAMILY, depth = 2.2, rise = depth * Math.tan(plane);
      var geo = cgeo('hip|' + depth + '|' + rise, function () {
        var s = new T.Shape();
        s.moveTo(0, 0); s.lineTo(depth, 0); s.lineTo(0, rise); s.lineTo(0, 0);
        return new T.ExtrudeGeometry(s, { depth: 0.14, bevelEnabled: false });
      });
      [-1, 1].forEach(function (sign) {
        var m = new T.Mesh(geo, mat(NICE ? 0xffffff : FARMHOUSE.roofTone,
                                    { rough: 0.9, map: shingleT }));
        /* VIEW-VOLUME MASKING (task 2): the shape above is a right
           triangle (0,0 / depth,0 / 0,rise) -- convex. */
        m.userData.convex = true;
        m.rotation.y = -Math.PI / 2;
        /* the extrusion's 0.14 runs toward -x from where it is placed, so
           the east fin is offset by its own thickness to sit OUTBOARD of
           the span exactly as the west one does -- shellGable's own end
           fills mirror themselves the same way. */
        /* ROOF VALLEYS (masking spec section 6): the fin stands ON the
           roof line at the wall (roofY, the deck's own centre plane
           there: block eave + 0.18 on a ridge-x block, as before) and
           runs 2.2 FORWARD of the face (local +x is world +z after the
           quarter turn), so nothing of it is behind the wall or under
           the deck -- no clip. */
        var fx = sign < 0 ? e.x0 : e.x1 + 0.14;
        m.position.set(fx, roofY(slot.face, fx, slot.z), slot.z);
        finish(m); g.add(m);
      });
      shellRegister(g, 'facade_' + slot.face + '_hip_end_' + feat.slot,
                    [0, 0, 1], slot.room);
    }

    /* The elevation itself: ground layer west to east, then roof. The
       spec is already normalized (services/house_facade.py owns every
       law in section 4), so this loop only dispatches. */
    function buildElevation() {
      var spec = SPEC || CANONICAL_JS;
      SPEC = spec;                       /* chfFacade() reports what BUILT */
      var byKind = { window: windowAt, door: doorAt, porch: porchAt,
                     garage_door: garageDoorAt };
      var roofKind = { gable: gableAt, dormer: dormerAt, hip_end: hipEndAt,
                       shed: shedAt };
      (spec.ground || []).forEach(function (f) {
        if (f.kind !== 'door') return;
        var s = SLOTS[f.slot];
        if (s && s.face === 'main' && (FRONT_DOOR_SLOT < 0 || f.slot < FRONT_DOOR_SLOT))
          FRONT_DOOR_SLOT = f.slot;
      });
      (spec.ground || []).forEach(function (f) {
        if (byKind[f.kind] && SLOTS[f.slot]) byKind[f.kind](f);
      });
      (spec.roof || []).forEach(function (f) {
        if (roofKind[f.kind] && SLOTS[f.slot]) roofKind[f.kind](f);
      });
      /* The last V2 bridge stood here: a replay that rebuilt a gabled
         porch's roof through gableAt, under a free gable's name. Task 8
         retired it -- porchAt owns the roof and registers it as
         facade_<face>_porch_<slot>_roof_*, the same geometry (same eave,
         same front, same featureBack, same PITCH_FAMILY) under the name
         the spec's own rule gives it. */
      /* SIDE-ENTRY GARAGE (task 8): normalize() deletes the street
         garage_door row for a side-entry garage, so no spec feature asks
         for a leaf -- but the block still HAS a garage door; it is on
         the west face. Built from the bay's own slots, so the fabric row
         `garage_door` (and the garage_front marker that finds it) exists
         in both orientations and nothing that could be done in one
         becomes impossible in the other. */
      if (GARAGE_SIDE) SIDE_OPENINGS.forEach(function(opening) {
        garageDoorAt({slot:GARAGE_BAY_SLOTS[0], kind:'garage_door',
                      span:GARAGE_BAY_SLOTS[1]-GARAGE_BAY_SLOTS[0]+1,
                      style:SIDE_DOOR.style, leaves:opening.third ? 1 : SIDE_DOOR.leaves,
                      sideZ:opening.z, sideWidth:opening.width, third:opening.third});
      });
      if (SIDE_PROJECTION) garageDoorAt({slot:GARAGE_BAY_SLOTS[0], kind:'garage_door',
          span:3, style:SIDE_DOOR.style, leaves:1, sideWidth:SIDE_THIRD_WIDTH, third:true});
    }
    /* ================= END FACADE ===================================== */

    /* ---- MASSING ARC 2 task 6: WHERE THE TWO BLOCKS MEET -------------
       Spec 2026-09-17 section 2 (rev2). Three things, in order:

       (a) THE VOID FLOOR (controller ruling R-B). Depth moves a street
       FACE, not the room behind it, so between the room floor's own edge
       and the moved wall there is a strip of ground with no floor on it.
       A plain slab in the stoop tone floors it. Registered as fabric of
       NO room, so the view-volume mask keeps it in every view -- it is
       the ground under all of them, not one room's own.

       (b) THE RETURN WALL. The blocks share the face plane x -7.15. The
       main block's own side of that step is `west_skirt` (built with the
       shell above, and extended to FULL_HOUSE.south by this task), which
       is why there is no `main_return`: a second wall in the same plane
       would only z-fight it. The GARAGE's side has never needed one --
       the main block has always stood further south -- so it is built
       here, and only when a depth actually pushes the garage block past
       the main's street face.

       (c) THE NEIGHBOUR VOLUME. Where the roofs meet, each block's roof
       is clipped against the OTHER block's BOUNDED volume: its footprint
       (with its own depth) from the ground to its ridge, capped by its
       own decks -- never an infinite deck plane, which would cut the
       roof clean off across the whole property. The shared plane belongs
       to ONE block (the higher eave; a tie goes to main): the owner's
       volume carries its overhang across the plane, so the other roof is
       cut back to the owner's rake, and the non-owner's volume stops
       0.02 short of it, so the owner's own deck, rake and gable infill
       survive and no two cut faces ever land coplanar.

       THE DECK BOUND IS THE DECK'S TOP SURFACE, not its centre plane: a
       deck is a 0.18-thick slab whose faces sit 0.09 along its own
       normal either side of the centre, so `d + 0.09` is the shingle
       line. Cutting at the centre plane would leave the buried roof's
       upper half standing inside the neighbour's shingles.

       AND IT RUNS ONLY WHERE THE BLOCKS DIFFER. The spec's own rule ends
       "with equal depth and equal stories nothing changes" -- and
       measurably it cannot: at equal depths the two blocks stand exactly
       as they were hand-built, sharing one eave line and one pitch, so
       their north decks are the SAME plane, and the main roof's west
       rakes have run over the garage's footprint under the garage's own
       roof since long before the block model existed. Subtracting there
       would cut geometry the canonical mesh and pixel pins hold to, for
       no visible gain (all of it is between the two blocks, where no
       camera stands). So the clip is gated on the depths differing. */
    if (MAIN_DZ > 0) (function () {
      var g = shellGroup();
      shellBox(g, SW_W, 0.10, MAIN_DZ + WALL_T4, FARMHOUSE.stoop,
               SW_CX, -0.05, (SWZ0 + FULL_HOUSE.south) / 2);
      shellRegister(g, 'main_void_floor', [0, 1, 0], null);
    })();
    if (GAR_DZ > 0) (function () {
      var g = shellGroup();
      shellBox(g, GARAGE_BLOCK.east - GARAGE_BLOCK.west, 0.10,
               GAR_DZ + WALL_T4, FARMHOUSE.stoop,
               (GARAGE_BLOCK.west + GARAGE_BLOCK.east) / 2, -0.05,
               (10.10 - WALL_T4 + GARAGE_BLOCK.south) / 2);
      shellRegister(g, 'garage_void_floor', [0, 1, 0], null);
    })();
    var SHARED_X = FULL_HOUSE.west;              /* -7.15, both blocks' */
    /* task 7: EXT_TOP4, not GARAGE_BLOCK.eave. Every GROUND wall of a
       block is one story tall; the block's eave is `stories` of them,
       and storyBox() below builds the walls that make up the difference.
       At one story the two numbers are the same value, so this is the
       canonical's own geometry to the bit. Same substitution at the
       three garage-block wall calls below. */
    if (GARAGE_BLOCK.south > FULL_HOUSE.south + 1e-6)
      shellWall('garage_return', SHARED_X, FULL_HOUSE.south,
                SHARED_X, GARAGE_BLOCK.south, EXT_TOP4,
                [1, 0, 0], [], 'mudroom', 'garage');
    /* the block that owns the shared face plane: the higher eave, and a
       tie goes to main. Task 7 made the two eaves genuinely differ (a
       block's `stories` multiplies its own), so this is a live choice
       now, not the standing tie it was written as -- and storyBox()
       reads the SAME answer to decide which block's upper wall closes
       the shared plane at x -7.15. */
    function sharedFaceOwner() {
      return GARAGE_BLOCK.eave > FULL_HOUSE.eave ? 'garage' : 'main';
    }
    /* `name` is the block whose roof is being clipped; the volume is its
       NEIGHBOUR's. Returns clipBuried's region: planes whose kept side
       is INSIDE the volume. */
    function neighbourVolume(name) {
      var other = name === 'main' ? 'garage' : 'main';
      var B = other === 'main' ? FULL_HOUSE : GARAGE_BLOCK;
      var C = window.HouseClip;
      var pl = blockDeckPlanes(other === 'main' ? 'main' : 'garage_block');
      var step = (sharedFaceOwner() === other) ? FULL_HOUSE.overhang : -0.02;
      var west = other === 'main' ? SHARED_X - step : B.west;
      var east = other === 'main' ? B.east : SHARED_X + step;
      var region = [
        { n: [1, 0, 0], d: west }, { n: [-1, 0, 0], d: -east },
        { n: [0, 0, 1], d: B.north }, { n: [0, 0, -1], d: -B.south },
        { n: [0, 1, 0], d: 0 }, { n: [0, -1, 0], d: -pl[0].ridge }
      ];
      pl.forEach(function (q) { region.push(C.flip({ n: q.n, d: q.d + 0.09 })); });
      return region;
    }
    /* WHEN THE CLIP RUNS (fix round 1). Not "the depths differ" -- the
       two blocks meet the same way they always have only when their
       roofs are geometrically IDENTICAL in every input that places a
       deck: depth (where the block ends), form, ridge direction, pitch
       and eave. A hip main beside a gable garage at equal depth, or two
       gables at different pitches, genuinely interpenetrate and must be
       cut. The canonical has all five equal, which is what keeps its
       coplanar north decks, the main roof's west rakes and the two
       gable infills at the shared face exactly as they were built --
       see the paragraph above for why cutting there costs pins and buys
       nothing. ROOF_FORMS, not BLOCKS[*].roof: window.HOUSE_ROOF_FORMS
       can override form and ridge, and the gate has to read what was
       actually built. */
    function blockRoofsIdentical() {
      return MAIN_DZ === GAR_DZ &&
             ROOF_FORMS.main.form === ROOF_FORMS.garage.form &&
             ROOF_FORMS.main.ridge === ROOF_FORMS.garage.ridge &&
             blockPitch('main') === blockPitch('garage') &&
             FULL_HOUSE.eave === GARAGE_BLOCK.eave;
    }
    /* Both volumes are ALWAYS derived, whether or not they are applied:
       window.chfBlockMeet() hands the block-meet audit the very planes
       the clipper used (or would have used), so a test measures the
       result against the same shared-side ownership offsets rather than
       a re-guessed box. */
    var BLOCK_VOLUMES = { main: neighbourVolume('main'),
                          garage: neighbourVolume('garage') };
    var BLOCK_MEET = blockRoofsIdentical()
      ? { main: null, garage: null }
      : { main: BLOCK_VOLUMES.main, garage: BLOCK_VOLUMES.garage };
    function adjacentVolumes(v) {
      var own = HOUSE_VOLUMES[v.block], out = [];
      own.forEach(function (n) {
        if (n !== v && (Math.abs(n.x1 - v.x0) < 1e-5 || Math.abs(n.x0 - v.x1) < 1e-5)) out.push(n);
      });
      if (v === HOUSE_VOLUMES.main[0]) out.push(HOUSE_VOLUMES.garage[HOUSE_VOLUMES.garage.length - 1]);
      if (v === HOUSE_VOLUMES.garage[HOUSE_VOLUMES.garage.length - 1]) out.push(HOUSE_VOLUMES.main[0]);
      return out;
    }
    function seamOwner(a, b) {
      if (a.eave !== b.eave) return a.eave > b.eave ? a : b;
      if (a.block !== b.block) return a.block === 'main' ? a : b;
      return a.x0 < b.x0 ? a : b;
    }
    function sameRoofVolume(a, b) {
      return a.south === b.south && a.north === b.north && a.eave === b.eave &&
             a.roof.form === b.roof.form && a.roof.ridge === b.roof.ridge &&
             a.roof.pitch_deg === b.roof.pitch_deg;
    }
    function clipRegionFor(v, n) {
      var C = window.HouseClip, planes = volumeDeckPlanes(n);
      var west = n.x0, east = n.x1, owner = seamOwner(v, n) === n;
      if (owner && n.x0 >= v.x1 - 1e-5) west -= FULL_HOUSE.overhang;
      if (owner && n.x1 <= v.x0 + 1e-5) east += FULL_HOUSE.overhang;
      var region = [
        { n: [1, 0, 0], d: west }, { n: [-1, 0, 0], d: -east },
        { n: [0, 0, 1], d: n.north }, { n: [0, 0, -1], d: -n.south },
        { n: [0, 1, 0], d: 0 }, { n: [0, -1, 0], d: -planes[0].ridge }
      ];
      planes.forEach(function (q) { region.push(C.flip({ n: q.n, d: q.d + 0.09 })); });
      return region;
    }
    function volumeClips(v) {
      var regions = adjacentVolumes(v).filter(function (n) { return !sameRoofVolume(v, n); })
        .map(function (n) { return clipRegionFor(v, n); });
      return regions.length ? regions : null;
    }
    /* V3 audit surface: every derived wing/upper volume and every
       bounded region actually offered to its roof clipper. */
    var VOLUME_MEETS = ALL_VOLUMES.map(function (v) {
      var regions = volumeClips(v);
      return { name: v.name, block: v.block, upper: v.upper,
               active: !!regions, regions: regions || [] };
    });
    function volumeClosureEnds(v) {
      // Hip ends are sloped decks, not shared vertical gable closures.
      if (v.roof.form === 'hip' || v.roof.ridge !== 'x') return null;
      var neighbours = adjacentVolumes(v), signs = [];
      [-1, 1].forEach(function (sign) {
        var edge = sign < 0 ? v.x0 : v.x1;
        var n = neighbours.find(function (other) {
          return Math.abs((sign < 0 ? other.x1 : other.x0) - edge) < 1e-5;
        });
        /* At an equal-eave mixed-ridge seam, only the ridge-x roof has a
           vertical gable profile to close. Let that profile stand even
           when the rectangular seam wall belongs to the west volume;
           volumeClips() trims it to the neighbour's deck. */
        if (!n || seamOwner(v, n) === v ||
            (v.eave === n.eave && v.roof.ridge === 'x' && n.roof.ridge !== 'x')) signs.push(sign);
      });
      return signs;
    }
    function buildVolumeRoof(v) {
      var base = v.canonical ? (v.block === 'main' ? 'roof_main' : 'garage_block_roof')
                             : v.name + '_roof';
      var rooms = v.block === 'main' ? ['kitchen', 'living'] : ['garage', 'mudroom'];
      shellGable(base, v.x0, v.x1, v.north, v.south, v.eave,
                 v.roof.ridge, null, volumeClosureEnds(v),
                 v.roof.pitch_deg * Math.PI / 180, rooms, null,
                 v.roof.form, volumeClips(v));
      if (v.roof.window && v.roof.form === 'gable' && v.roof.ridge === 'z')
        gableWindow(base, v.x0, v.x1, v.south, v.eave, v.roof.pitch_deg * Math.PI / 180, null, volumeClips(v));
    }
    /* the two blocks' envelopes and the deck planes their roofs were
       placed by, for the read-only window.chfBlockGeometry hook: a test
       rebuilds the neighbour volume from these numbers alone and audits
       the result, rather than reading the clipper's own region back. */
    function blockGeometry() {
      function row(key, B, face) {
        var pl = blockDeckPlanes(face);
        return { west: B.west, east: B.east, north: B.north, south: B.south,
                 eave: B.eave, ridge: pl[0].ridge, depth: BLOCKS[key].depth || 0,
                 decks: pl.map(function (q) { return { n: q.n, d: q.d }; }) };
      }
      return { main: row('main', FULL_HOUSE, 'main'),
               garage: row('garage', GARAGE_BLOCK, 'garage_block'),
               volumes: ALL_VOLUMES.map(function (v) {
                 return { name: v.name, block: v.block, x0:v.x0, x1:v.x1,
                          north:v.north, south:v.south, eave:v.eave, upper:v.upper,
                          roof:JSON.parse(JSON.stringify(v.roof)) };
               }) };
    }

    /* ---- the two block roofs (spec section 3) -------------------------
       Eleven hand-placed roof pieces became these calls plus the
       facade's own features. Both read ROOF_FORMS, so form and ridge
       direction are parameters a later arc sets rather than facts baked
       into this line.

       VIEW-VOLUME MASKING (task 4, spec section 5): ONE roof over the
       whole main block again. The cutaway-ownership fix (v2.499.41) had
       split it at x 6.85 into roof_main_west / roof_main_east, each
       owning what it covered, because the verdict solver could only
       hide a piece whole -- and the split broke the hip (each half
       clamped to a pyramid) and ridge-z forms. The mask cuts a deck
       only where it stands between a room camera and that room's box,
       so one deck opens over the great room for the great room's
       cameras and stays over the study, and the hip is a proper hip
       with a 1.15 ridge (run 10.645 inset from each end of a 22.44
       depth). slopeRooms: north deck kitchen, south deck living, the
       two gable ends roomless -- a tap on the roof over the study walks
       into the room the deck faces, and the study's PIN is not
       something a roof tap may step around. Reads ROOF_FORMS.main, so
       form and ridge stay one parameter. */
    if (!UPPER.length && !MASSES.some(function (m) { return m.slot >= 6; })) {
      shellGable('roof_main', FULL_HOUSE.west, FULL_HOUSE.east,
                 FULL_HOUSE.north, FULL_HOUSE.south, FULL_HOUSE.eave,
                 ROOF_FORMS.main.ridge, null, null, BLOCK_PITCH,
                 ['kitchen', 'living'], null, ROOF_FORMS.main.form,
                 BLOCK_MEET.main);
      if (BLOCKS.main.roof.window && ROOF_FORMS.main.form === 'gable' && ROOF_FORMS.main.ridge === 'z') gableWindow('roof_main', FULL_HOUSE.west, FULL_HOUSE.east,
        FULL_HOUSE.south, FULL_HOUSE.eave, BLOCK_PITCH, null, BLOCK_MEET.main);
    } else HOUSE_VOLUMES.main.forEach(buildVolumeRoof);

    /* ---- the garage block (spec section 2) ----------------------------
       The garage's own three walls (garage_shell) and the mudroom's own
       room walls stay exactly where they are; these are the BLOCK's
       outer faces, 0.12 outboard of them, and the old rear service void
       becomes garage/mudroom depth behind the garage's back wall. No
       floor back there and no camera ever sees it. */
    shellWall('garage_block_north', GARAGE_BLOCK.west, GARAGE_BLOCK.north,
              GARAGE_BLOCK.east, GARAGE_BLOCK.north, EXT_TOP4,
              [0, 0, -1], [], null);
    /* MASSING ARC 2 task 8: the WEST face carries the door on a
       side-entry garage, so it is built as the three pieces an opening
       makes -- the wall north of it, the wall south of it and the head
       over it -- instead of one run. Each is an ordinary shellWall (or
       shellBox) so each gets its own base band, corner boards and
       registration for free. Front-entry builds the single wall it
       always has, window and all, so nothing about the canonical moves.
       The window moves to z 1.0 on the north piece: at its old z 2.0 a
       1.35-wide window would run 0.375 past that piece's own end into
       the opening. */
    if (GARAGE_SIDE) {
      var sideCursor = GARAGE_BLOCK.north;
      SIDE_OPENINGS.forEach(function(opening, index) {
        var lo = opening.z-opening.width/2, hi = opening.z+opening.width/2;
        shellWall(index === 0 ? 'garage_block_west_a' : 'garage_block_west_pier',
                  GARAGE_BLOCK.west, sideCursor, GARAGE_BLOCK.west, lo, EXT_TOP4,
                  [-1,0,0], index === 0 && lo > 2 ? [[1.0,1.35,true]] : [], null, 'garage');
        var hg=shellGroup(), y0=0.1+SIDE_DOOR.height;
        shellBox(hg,WALL_T4,EXT_TOP4-y0,opening.width,cladColour('garage'),
                 GARAGE_BLOCK.west,(y0+EXT_TOP4)/2,opening.z,
                 {rough:0.95,facadeBlock:'garage',map:CLAD('garage')});
        shellRegister(hg,'garage_block_west_head'+(index ? '_third' : ''),[-1,0,0],null);
        sideCursor=hi;
      });
      shellWall('garage_block_west_b',GARAGE_BLOCK.west,sideCursor,
                GARAGE_BLOCK.west,GARAGE_BLOCK.south,EXT_TOP4,[-1,0,0],[],null,'garage');
    } else {
      shellWall('garage_block_west', GARAGE_BLOCK.west, GARAGE_BLOCK.north,
                GARAGE_BLOCK.west, GARAGE_BLOCK.south, EXT_TOP4,
                [-1, 0, 0], [[2.0, 1.35, true]], null);
    }
    /* the mudroom's street face, one story tall like every other GROUND
       wall of the block (task 7: the block's own eave is `stories` of
       these, and storyBox() builds the difference).
       The old front band (mudroom_front_cladding) closed the gap above
       the room's door wall to the underside of a cross roof that no
       longer exists; this is that band re-authored as the face itself,
       and the mudroom's own walls, door and window stay inside it. */
    /* VIEW-VOLUME MASKING (task 2, corrected): mudroomRoofG folds into
       this group hundreds of lines below (mudroomRoofG.add, near
       refabBox('mudroom_front', ...)) and carries a door zone with a
       lathe knob and a coach lamp -- non-box meshes, but Task 3 keeps
       or drops each of those whole by its own box corners rather than
       clipping it, so this row is still not a kit; see chfFabricConvexity's
       `nonconvex` list for the honest inventory of what those are. */
    // Side entry removes the street door assembly, not its enclosing wall.
    if (GARAGE_SIDE) shellWall('garage_front_wall', GARAGE_BLOCK.west, GARAGE_BLOCK.south,
                              -12.60, GARAGE_BLOCK.south, EXT_TOP4,
                              [0,0,1], [], 'garage', 'garage');
    if (SIDE_PROJECTION > 0) {
      var px = GARAGE_BLOCK.west-POP_WIDTH;
      var peave = Math.max(4.1, SIDE_DOOR.height+0.5);
      shellWall('garage_popout_north', px, POP_BACK, GARAGE_BLOCK.west, POP_BACK,
                peave, [0,0,-1], [], 'garage', 'garage');
      shellWall('garage_popout_west', px, POP_BACK, px, POP_FRONT,
                peave, [-1,0,0], [], 'garage', 'garage');
      shellWall('garage_popout_pier_west', px, POP_FRONT, POP_X-SIDE_THIRD_WIDTH/2, POP_FRONT,
                peave, [0,0,1], [], 'garage', 'garage');
      shellWall('garage_popout_pier_east', POP_X+SIDE_THIRD_WIDTH/2, POP_FRONT, GARAGE_BLOCK.west, POP_FRONT,
                peave, [0,0,1], [], 'garage', 'garage');
      var ph = shellGroup(), py = 0.1+SIDE_DOOR.height;
      shellBox(ph, SIDE_THIRD_WIDTH, peave-py, WALL_T4, cladColour('garage'),
               POP_X, (peave+py)/2, POP_FRONT,
               {rough:0.95,facadeBlock:'garage',map:CLAD('garage')});
      shellRegister(ph, 'garage_popout_header', [0,0,1], 'garage');
      // Keep the existing side-facing gable; the single door faces the street.
      shellGable('garage_popout_roof', px, GARAGE_BLOCK.west,
                 POP_BACK, POP_FRONT, peave, 'x', 'garage', [-1], blockPitch('garage'),
                 ['garage','garage'], [true,false], 'gable');
      var pf = shellGroup();
      shellBox(pf, POP_WIDTH, 0.12, POP_FRONT-POP_BACK, FARMHOUSE.stoop,
               POP_X, -0.06, (POP_BACK+POP_FRONT)/2);
      shellRegister(pf, 'garage_popout_floor', [0,1,0], 'garage');
    }
    var mudroomFrontG = shellWall('mudroom_front', -12.60, GARAGE_BLOCK.south,
              GARAGE_BLOCK.east, GARAGE_BLOCK.south, EXT_TOP4,
              [0, 0, 1], [], 'mudroom');
    if (!UPPER.length && !MASSES.some(function (m) { return m.slot < 6; })) {
      shellGable('garage_block_roof', GARAGE_BLOCK.west, GARAGE_BLOCK.east,
                 GARAGE_BLOCK.north, GARAGE_BLOCK.south, GARAGE_BLOCK.eave,
                 ROOF_FORMS.garage.ridge, null, null, blockPitch('garage'),
                 ['garage', 'mudroom'], null, ROOF_FORMS.garage.form,
                 BLOCK_MEET.garage);
      if (BLOCKS.garage.roof.window && ROOF_FORMS.garage.form === 'gable' && ROOF_FORMS.garage.ridge === 'z') gableWindow('garage_block_roof', GARAGE_BLOCK.west, GARAGE_BLOCK.east,
        GARAGE_BLOCK.south, GARAGE_BLOCK.eave, blockPitch('garage'), null, BLOCK_MEET.garage);
    } else HOUSE_VOLUMES.garage.forEach(buildVolumeRoof);

    /* Spec 2026-09-17 blocks section 0: a block roof's pieces are named by
       geometric side (shellGable: _north/_south + _end_west/_end_east on a
       ridge x; _west/_east + _back/_front on a ridge z). Markers and tests
       name the CANONICAL pieces; this map says which registered piece
       stands where the canonical one stood, so a ridge setting never
       strands the Mudroom marker. FABRIC's own `n` is a Vector3 (regFabric
       normalizes the array it was handed), so the picks read .z. */
    var ROOF_ALIAS = {};
    function aliasRoof(base) {
      var volumePrefix = base === 'roof_main' ? 'main_' : 'garage_';
      var rows = FABRIC.filter(function (f) {
        return f.name.indexOf(base + '_') === 0 ||
          ((UPPER.length || MASSES.length) && f.name.indexOf(volumePrefix) === 0 && /^(main|garage)_[uw]\d+_roof_/.test(f.name));
      });
      function pick(sel) {
        var best = null;
        rows.forEach(function (f) { if (!best || sel(f.n) > sel(best.n)) best = f; });
        return best ? best.name : null;
      }
      ROOF_ALIAS[base + '_south'] = pick(function (n) { return n.z; });
      ROOF_ALIAS[base + '_north'] = pick(function (n) { return -n.z; });
    }
    aliasRoof('roof_main'); aliasRoof('garage_block_roof');
    function roofAlias(name) { return ROOF_ALIAS[name] || name; }

    /* ---- the main block's north side ----------------------------------
       The kitchen's own north wall (wallB / north_wall) and its cladding
       run to x 6.85; this carries the same face on to the east wall,
       with one window centred on the back room. Its OUTER face sits on
       FULL_HOUSE.north so it is flush with the cladding beside it --
       the window would otherwise be buried inside that cladding. */
    shellWall('north_wall_east', EPX1_4, FULL_HOUSE.north + WALL_T4 / 2,
              FULL_HOUSE.east, FULL_HOUSE.north + WALL_T4 / 2, EXT_TOP4,
              [0, 0, -1], [[10.75, 1.35, true]], null);

    /* ---- the back door (spec section 2) -------------------------------
       The exterior Kitchen marker used to be the patio slider, which is
       an interior opening now. This is the kitchen's own back door on
       the north wall, with the back patio slab outside it. doorAt()'s
       leaf/casing/knob idiom, built into a group that is then turned to
       face -z; no coach lamp (that belongs to the street elevation the
       facade generator owns). */
    (function backDoorAt(x) {
      var g = shellGroup();
      g.position.set(x, 0, FULL_HOUSE.north);
      g.rotation.y = Math.PI;
      var z = 0.02;                    /* proud of the face, as doorAt */
      function dtag(m) {
        if (m) { m.userData.room = 'kitchen';
                 m.userData.entry = 'back_door'; }
        return m;
      }
      var woodMap = (FSTYLE.door === 'wood') ? woodDoor : null;
      var leaf = new T.Mesh(
        NICE ? chamferGeo(0.14, 3.2, 1.4, 0.04) : new T.BoxGeometry(0.14, 3.2, 1.4),
        PBR ? new T.MeshStandardMaterial(woodMap
                ? { map: woodMap, roughness: 0.65 }
                : { color: FARMHOUSE.wood, roughness: 0.65 })
            : new T.MeshLambertMaterial(woodMap
                ? { color: 0xc9a06c, map: woodMap }
                : { color: FARMHOUSE.wood }));
      leaf.rotation.y = Math.PI / 2;
      leaf.position.set(0, 1.6, z);
      dtag(leaf); finish(leaf); g.add(leaf);
      dtag(box(0.14, 3.44, 0.13, 0xe4ddd1, -0.65, 1.72, z, g, sharp()));
      dtag(box(0.14, 3.44, 0.13, 0xe4ddd1, 0.65, 1.72, z, g, sharp()));
      dtag(box(1.86, 0.14, 0.13, 0xe4ddd1, 0, 3.37, z, g, sharp()));
      if (DETAIL >= 2) {
        dtag(box(0.90, 1.20, 0.02, 0x6f5433, 0, 2.14, z + 0.075, g, WOODM));
        dtag(box(0.90, 0.98, 0.02, 0x6f5433, 0, 0.82, z + 0.075, g, WOODM));
        dtag(box(0.74, 1.04, 0.04, 0xc79b63, 0, 2.14, z + 0.080, g, WOODM));
        dtag(box(0.74, 0.82, 0.04, 0xc79b63, 0, 0.82, z + 0.080, g, WOODM));
      }
      var knob = latheAt('knob', [0.06, 0.1, 0.06], 0xd8c48a, 0.55,
                         1.6, z + 0.07, g, CHROME);
      knob.rotation.x = Math.PI / 2;
      dtag(knob);
      /* VIEW-VOLUME MASKING (task 2): the same door-plus-coach-lamp kit
         doorAt() builds, hand-authored here instead of through the
         facade generator -- a kit for the same reason. */
      shellRegister(g, 'back_door', [0, 0, -1], 'kitchen', true);
    })(-2.0);

    /* ---- the two future rooms (spec section 2) ------------------------
       The old patio notch and the old rear room, enclosed inside the
       main block: floors, the partition between them, and the openings
       the great room already had into both. No props, no zones, no
       cameras -- the user's own ruling ("no purpose other than
       visual"). The roof closes them overhead, so no ceilings either. */
    [[1.50, 7.65], [FULL_HOUSE.north, 1.50]].forEach(function (seg) {
      var d = seg[1] - seg[0];
      box(FULL_HOUSE.east - EPX1_4, 0.1, d, NICE ? 0xffffff : C.wood,
          (EPX1_4 + FULL_HOUSE.east) / 2, -0.05, (seg[0] + seg[1]) / 2,
          extG, sharp(NICE ? { rough: 0.55, map: woodLight } : { rough: 0.55 }));
    });
    /* the partition stops at EWX0_4 (14.30), the east wall's INNER
       face, not at FULL_HOUSE.east: run it to the outer face and its
       0.35-wide `C.wall` end is coplanar with the east siding, which
       draws a full-height plaster stripe down that elevation between
       the second and third east windows (orbit7). Same rule as
       `east_partition`'s south end above. */
    var futurePartG = shellGroup();
    shellBox(futurePartG, EWX0_4 - EPX1_4, EXT_TOP4, WALL_T4,
             C.wall, (EPX1_4 + EWX0_4) / 2, EXT_TOP4 / 2, 1.50,
             WALL_O);
    /* THE VAULT (see roofVault above). This one runs ACROSS the slope
       axis: z 1.50 is north of the ridge at 4.225, the deck is at one
       height over the wall's whole length, and the top is cut square at
       the lower of its two faces. */
    if (mainWingVault(EPX1_4, EWX0_4))
      vaultSection(futurePartG,
                   vaultFlatPts(MAIN_VAULT, EPX1_4, EWX0_4, EXT_TOP4,
                                1.50 - WALL_T4 / 2, 1.50 + WALL_T4 / 2),
                   EXT_TOP4, 'x', 1.50 - WALL_T4 / 2, WALL_T4, C.wall, WALL_O);
    /* between the two future rooms; neither has a room camera, so no
       mask ever reaches it -- always solid. */
    regFabric(futurePartG, { name: 'future_room_partition', n: [0, 0, 1],
                             box: fabBox(futurePartG) });
    /* the back patio: the slab outside the back door, in the yard. Not
       registered -- it is ground, like the drive and the front walk. */
    box(5.2, 0.16, 5.5, EXTC.drive, -2.0, -0.08, -9.0, extG,
        sharp({ rough: 0.95, map: driveT }));

    /* STUDY REFIT (2026-09-16): `patio_slider` is retired. The user's
       reading -- "the patio door is still there even though the patio
       turned into a regular inside room. That door might actually make
       a good door for the study" -- is the whole of it: the glass
       moved to the study's opening at z 9.93 and this one wears the
       plain interior door the study gave up. BOTH doors are built and
       registered in house_features.js now (east_room_door and
       living_study_door), beside living_back_room_door, so the three
       interior doors in this partition share one builder and one set
       of colours instead of one of them being shell and two fixtures. */

    /* Continue west cladding along the living room to the south corner. */
    /* ebox() cannot be reused here — it hardcodes extG as the parent of
       every mesh it builds (see ebox's own definition, above; the
       garage split hit the exact same wrinkle), and fabBox() needs a
       group that holds ONLY these two meshes, not extG's whole loose
       facade. So this is now a dedicated group, built the same way
       south_wall/east_wall/garage_shell are: box() directly (bypassing
       ebox()), passing the SAME sharp(opts) wrapping ebox() itself would
       have applied (K1: ebox defaults every call to ch:0 unless opts.ch
       is already set, which neither of these ever did), into a new
       westSkirtG that is otherwise a pure reparent — no transform is set
       on the group, so both meshes keep the exact absolute x/y/z they
       had as bare extG children. Same siding material, same mat() cache
       key (color + {rough,map:sidingT}) as before — inZoneGroup(g0)
       (the only thing that could split the cache) only checks for a
       userData.zone ancestor, and westSkirtG carries no .zone, so this
       is still the same shared, already-batched siding material every
       other facade run resolves to.

       VIEW-VOLUME MASKING (task 4): the mask reads the box and the room
       cameras, never `n` -- the skirt is cut where it stands between
       the mudroom camera and the mudroom (0.39 of the row) and between
       the street camera and the pantry nook (0.29); the derivation
       below is the retired solver's record of the flip, kept as history.
       n = [1,0,0], NOT the naive "true outward" [-1,0,0] the finding
       first suggested by analogy to south_wall/east_wall/north_wall
       (real exterior boundaries with nothing but yard beyond them, so
       THEIR true compass normal already IS the solver's "outward").
       Checked by the same dot-product law those pieces use and REJECTED
       for this one: with n=[-1,0,0], p=(-6.825,3.5,10.3) (fabBox-
       measured centre), camOut = (cam.x < -6.825) is FALSE for MUD_POS
       (x -3.4) — the mudroom view would verdict this piece SOLID,
       failing the one behaviour this registration exists to produce.
       The reason: unlike south_wall/east_wall, EVERY camera in this
       dollhouse (including MUD_POS, the mudroom's own) is staged on the
       kitchen/living side of the house — none is ever actually outdoors
       to the west — while the mudroom ROOM's own AABB sits further west
       STILL, past this skirt. That is exactly west_wall's own T2 shape
       (a camera and its subject straddling the piece from the SAME
       physical side an honest compass would call "the wrong one"), so
       this piece needs west_wall's own flip, n=[1,0,0], for the same
       reason, even though it is genuine ext siding and west_wall is an
       interior partition. Re-derived, not copied on faith:
         camOut = cam.x > -6.825; subIn = sub.x < -6.825.
         kitchen (HOME_POS.x 4.64, moved south/west by the cutaway-
           ownership fix; 14.6 before): camOut true either way (both are
           > -6.825); kitchen aabb x -2.785, subIn false (-2.785 is NOT
           < -6.825). SOLID, unchanged.
         living (LIV_POS.x 0): camOut true; living aabb x 0, subIn
           false. SOLID.
         mudroom (MUD_POS.x -3.4): camOut true; mudroom aabb x -9.62,
           subIn true (-9.62 < -6.825). Both true -> corridorHits(box,
           MUD_POS, mudroomAabbCentre, 1.5): lo=(-11.12,0.6,3.885),
           hi=(-1.9,7.7,12.7); box=[-7.15,-6.5,0,7,6.0,14.6] sits fully
           inside on every axis. GHOST.
         garage (GARAGE_POS.x -18.0): camOut false (-18.0 is NOT >
           -6.825). SOLID.
         exterior: subject is null -> solid unconditionally (the sealed-
           house case every other piece already relies on). SOLID.
       Matches the fix's own required set exactly: kitchen/exterior stay
       SOLID, mudroom GHOSTs.

       Registered here, at build time — this call executes while
       buildRoom() is still running, hundreds of lines before the
       mergeStatic passes and the FABRIC.forEach fence-feed
       (`EXT_NO_MERGE.add(f.g); NO_MERGE.add(f.g)`) that read FABRIC
       far below (house.js, the batching section). Landing the
       regFabric() call HERE, before that feed ever runs, is what lets
       it add westSkirtG to EXT_NO_MERGE/NO_MERGE in time to fence it
       out of extG's own self-merge pass and the final scene-level pass
       — the same ordering every other Task 3/4 fabric group already
       depends on. westSkirtG also joins the dedicated per-group
       mergeStatic pass list a few hundred lines below (alongside
       south_wall/east_wall/garage_shell) for the same "structural, not
       incidental" reason those three did: today it only holds 2 meshes
       of 2 different materials (under mergeStatic's 4-item floor
       either way, so this is a no-op today), but the next thing hung on
       this group should not have to rediscover that omission. */
    var westSkirtG = new T.Group();
    extG.add(westSkirtG);
    /* MASSING ARC 2 task 6 (spec 2026-09-17 section 2, THE BLOCK MEET):
       this IS the main block's return wall at the shared face x -7.15.
       The main block stands 4.45 deeper than the garage block even at
       depth 0/0, and this piece has carried its cladding, its corner
       board and (task 5) its base band over that step since long before
       the block model existed -- so a main-side depth extends THIS wall
       to the new street line rather than minting a second wall in the
       same plane for it to z-fight. The garage's own return, for when a
       depth pushes the garage block PAST the main's face, is built with
       the block roofs below (`garage_return`). */
    box(0.3, EXT_TOP4, SWZ1 + MAIN_DZ - 6.0, NICE ? 0xffffff : EXTC.siding,
        -7.0, EXT_TOP4 / 2, (6.0 + SWZ1 + MAIN_DZ) / 2, westSkirtG,
        sharp({ rough: 0.95, facadeBlock: 'main', map: CLAD() }));
    box(0.35, EXT_TOP4, 0.1, EXTC.trim, -6.675, EXT_TOP4 / 2, SWZ1 + MAIN_DZ,
        westSkirtG, sharp());
    /* spec 2026-09-17 section 2: the main block's base band, west face
       south of the garage block (the one stretch of it the street sees) */
    baseBand(westSkirtG, -7.0, 6.0, -7.0, SWZ1 + MAIN_DZ, [-1, 0, 0], 'main');
    /* spec section 5: fronts mudroom, same adjacency shape as west_wall's
       own T2/T7 flip immediately above this file's own west_skirt
       derivation — this piece only ever ghosts for the mudroom's camera
       (re-derived exhaustively in the comment above: mudroom GHOST,
       every other view SOLID), so a tap on it belongs where it ghosts. */
    regFabric(westSkirtG, { name: 'west_skirt', n: [1, 0, 0],
                            box: fabBox(westSkirtG), room: 'mudroom' });
    /* ================= END SHELL: the seal ============================ */

    /* garage: opened in H2, moved WEST in the architect pass so the
       mudroom slots between it and the great room. Front pieces + the
       new GABLE roof live in garageDoorG (hidden inside). */
    var garageDoorG = new T.Group();
    var webgl_garageBackWall = null;
    var webgl_coachLampGlass = null;   /* R5: NO_MERGE anchor, see below */
    /* SHELL (Task 4): declared here (outer scope), not with `var` inside
       the garage IIFE below, for the same reason webgl_garageBackWall/
       webgl_coachLampGlass already are — the mergeStatic per-group pass
       and the NO_MERGE fence both read this name from OUTSIDE that
       closure, far below. */
    var garageShellG = null;
    extG.add(garageDoorG);
    var garageInterior = new T.Group();
    extG.add(garageInterior);
    /* ---- MASSING ARC 2 task 7 (spec section 3.2): THE UPPER STORY -----
       A second story is FOUR SHELL WALLS, nothing more exotic: from the
       story-1 eave (EXT_TOP4) up to the block's own eave (EXT_TOP4 x
       stories), in the block's cladding, with the same 0.18 corner
       boards every shellWall carries -- and NO base band, because a base
       band is where a wall meets the ground and this one meets a floor.
       Registered as fabric of NO room: no room's AABB reaches above
       EXT_TOP4 (the occupied wedge stops there), so
       the upper story is not part of anyone's volume -- it is fabric
       standing between a camera and its room, and buildRoomShells()
       opens it exactly the way it opens `south_wall`. The kitchen
       camera (y 13.8) and the living camera (y 12.8) both sit ABOVE this
       box's 11.2 top and look down THROUGH it, which is the whole reason
       it has to be cut like fabric rather than ghosted whole.

       WHERE THE WALL LINE IS. Each block's ground floor already has a
       convention and the upper story matches it, so the two floors are
       flush and a story-2 window lands proud of the skin instead of
       inside it: the MAIN block's envelope numbers are its walls' OUTER
       faces (south_wall runs SWZ0..SWZ1 = FULL_HOUSE.south, east_wall
       14.30..FULL_HOUSE.east, west_skirt -7.15..-6.85), so its upper
       walls are inset half a thickness; the GARAGE block's walls are
       shellWall's own, CENTRED on the envelope line (garage_block_west
       straddles -18.20), so its upper walls are centred too.

       THE SHARED PLANE x -7.15 is one wall, never two: a second slab in
       the same plane is a z-fight, and no slab at all is a hole. Which
       block owns it is sharedFaceOwner()'s answer, already given for the
       block-meet clip above -- see the rule written out at the two side
       walls below. */
    // An observed forward mass extends the street shell, not the rooms behind it.
    // The old face stays inside the extension, as the existing block-depth void does.
    function groundProjection(v) {
      var B = v.block === 'main' ? FULL_HOUSE : GARAGE_BLOCK;
      if (v.south <= B.south + 1e-6) return;
      var io = WALL_T4 / 2, front = v.south - io;
      shellWall(v.name + '_mass_front', v.x0, front, v.x1, front, EXT_TOP4,
                [0, 0, 1], [], null, v.block);
      [-1, 1].forEach(function (sign) {
        var edge = sign < 0 ? v.x0 : v.x1;
        var neighbour = adjacentVolumes(v).find(function (n) {
          return Math.abs((sign < 0 ? n.x1 : n.x0) - edge) < 1e-5;
        });
        var start = Math.max(B.south - io, neighbour ? neighbour.south - io : B.south - io);
        if (start >= front - 1e-6) return;
        shellWall(v.name + '_mass_return_' + sign, edge, start, edge, front, EXT_TOP4,
                  [sign, 0, 0], [], null, v.block);
      });
      var floor = shellGroup();
      shellBox(floor, v.x1-v.x0, .12, v.south-B.south, FARMHOUSE.stoop,
               (v.x0+v.x1)/2, -.06, (v.south+B.south)/2);
      shellRegister(floor, v.name + '_mass_floor', [0,1,0], null);
    }
    ALL_VOLUMES.forEach(groundProjection);
    function storyBox(v) {
      if (!v.upper) return;
      var name = v.block, B = name === 'main' ? FULL_HOUSE : GARAGE_BLOCK;
      var y0 = EXT_TOP4, h = EXT_TOP4;
      /* the main block's envelope lines are outer faces, the garage
         block's are wall centres (see the paragraph above) */
      var io = name === 'main' ? WALL_T4 / 2 : 0;
      var south = v.south - io, north = v.north + io;
      var west = B.west + io, east = B.east - io;
      function wall(suffix, x0, z0, x1, z1, normal) {
        var g = shellGroup(), alongX = x0 !== x1;
        var len = alongX ? x1 - x0 : z1 - z0;
        shellBox(g, alongX ? len : WALL_T4, h, alongX ? WALL_T4 : len,
                 cladColour(name), (x0 + x1) / 2, y0 + h / 2, (z0 + z1) / 2,
                 { rough: 0.95, facadeBlock: name, map: CLAD(name) });
        [0, 1].forEach(function (end) {
          shellBox(g, 0.18, h, 0.18, FARMHOUSE.trim,
                   end ? x1 : x0, y0 + h / 2, end ? z1 : z0);
        });
        shellRegister(g, v.name + '_upper_' + suffix, normal, null);
      }
      west = v.x0 + io; east = v.x1 - io;
      wall('south', west, south, east, south, [0, 0, 1]);
      wall('north', west, north, east, north, [0, 0, -1]);
      /* Each x seam is closed once. seamOwner() chooses the taller
         volume, then west within one block or main across the shared
         block plane. When both sides of the block plane are upper, its
         one wall covers the union of their north/south extents. */
      function sharedEnd(sign) {
        var m = sign < 0 ? FULL_HOUSE.north + WALL_T4 / 2
                         : FULL_HOUSE.south - WALL_T4 / 2;
        var g = sign < 0 ? GARAGE_BLOCK.north : GARAGE_BLOCK.south;
        return sign < 0 ? Math.min(m, g) : Math.max(m, g);
      }
      ['west', 'east'].forEach(function (side) {
        var sign = side === 'west' ? -1 : 1;
        var edge = sign < 0 ? v.x0 : v.x1;
        var neighbour = adjacentVolumes(v).find(function (n) {
          return Math.abs((sign < 0 ? n.x1 : n.x0) - edge) < 1e-5;
        });
        var x = side === 'west' ? west : east;
        var normal = side === 'west' ? [-1, 0, 0] : [1, 0, 0];
        if (neighbour && seamOwner(v, neighbour) !== v) {
          if (v.south > neighbour.south)
            wall(side + '_forward', x, neighbour.south, x, south, normal);
          if (v.north < neighbour.north)
            wall(side + '_rear', x, north, x, neighbour.north, normal);
          return;
        }
        var across = neighbour && neighbour.block !== v.block;
        var both = across && neighbour.upper;
        var z0 = both ? sharedEnd(-1) : north;
        var z1 = both ? sharedEnd(1) : south;
        if (both && MASSES.length) {
          z0 = Math.min(north, neighbour.north);
          z1 = Math.max(south, neighbour.south);
        }
        wall(side, x, z0, x, z1, side === 'west' ? [-1, 0, 0] : [1, 0, 0]);
      });
    }
    /* BEFORE buildElevation(): a story-2 feature is placed on the face
       these walls make, so they have to stand first. */
    HOUSE_VOLUMES.main.forEach(storyBox); HOUSE_VOLUMES.garage.forEach(storyBox);

    /* FACADE (arc 4, spec section 6): the street elevation builds
       HERE. Every helper it uses exists (the shell helpers above,
       garageDoorG just above), and garage_door's own fabBox below is
       measured with the generated leaf already in the group. */
    buildElevation();

    (function () {
      function gtag(m) { if (m) m.userData.room = 'garage'; return m; }
      function itag(m) {
        if (m) { zoneTag(m, 'garage', 'garage'); }
        return m;
      }
      var gWallW = gtag(ebox(0.24, 4.6, 8.0, cladColour('garage'),
                -18.08, 2.3, 6.0, { rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') }));
      var gWallE = gtag(ebox(0.24, 4.6, 8.0, cladColour('garage'),
                -12.72, 2.3, 6.0, { rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') }));
      var garageBackWall = gtag(ebox(5.6, 4.6, 0.24,
                cladColour('garage'),
                -15.4, 2.3, 2.12, { rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') }));
      webgl_garageBackWall = garageBackWall;
      /* MASSING ARC 2 task 6 (spec 2026-09-17 section 2): every piece of
         the BAY is the garage block's street face -- the header, the
         lintel, the two piers and their base band, the pier window, the
         gable's half-round, the coach lamp and the band above -- so a
         garage depth moves all of it with GARAGE_BLOCK.south -- and so
         does the door LEAF, which garageDoorAt() places off one `z` of
         its own (fix round 1: it does NOT read the slot table, and was
         left behind at 10.02 until that `z` learned GAR_DZ too). The
         bay's own jambs
         end up standing proud of the garage ROOM's side walls, which
         stop at z 10.0 -- that is what depth IS (the face moves, the
         room does not), and garage_void_floor floors what opens up. */
      /* SIDE-ENTRY GARAGE (task 8, spec 2026-09-17 section 2): none of
         the BAY is built when the door is on the side. Every piece from
         here to the band below IS the street face -- header, lintel,
         trim, the two piers and their base band, the pier window, the
         gable's half-round, the coach lamp and the band that carries the
         face to the block eave -- and a side-entry garage's street face
         is `garage_front_wall` (a full-height shell wall, built with the
         block's own walls above) with the facade's window in it. The
         leaf itself is not here either: garageDoorAt() hangs it on the
         west face, in a turned sub-group of this same garageDoorG, so
         the openable-door trick and the `garage_door` row are unchanged.
         Front-entry builds exactly what it always did. */
      if (!GARAGE_SIDE) {
        gtag(box(5.6, 1.1, 0.24, cladColour('garage'),
                 -15.4, 4.05, 9.88 + GAR_DZ, garageDoorG,
                 sharp({ rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') })));
        /* the lintel: the header stopped at y 3.5 and the door at 3.1, so
           a 0.4 slot ran the width of the bay and the resting camera
           looked straight through it at the shelves */
        gtag(box(5.6, 0.46, 0.24, cladColour('garage'),
                 -15.4, 3.27, 9.88 + GAR_DZ, garageDoorG,
                 sharp({ rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') })));
        gtag(box(3.9, 0.16, 0.16, EXTC.trim, -15.4, 3.16, 10.00 + GAR_DZ, garageDoorG, sharp()));
        gtag(box(0.76, 3.5, 0.24, cladColour('garage'),
                 -17.58, 1.75, 9.88 + GAR_DZ, garageDoorG,
                 sharp({ rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') })));
        gtag(box(0.76, 3.5, 0.24, cladColour('garage'),
                 -13.22, 1.75, 9.88 + GAR_DZ, garageDoorG,
                 sharp({ rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') })));
        /* Spec 2026-09-17 section 2 (review fix, v2.499.75): the bay's two
           PIERS are the garage block's street face between garage_block_west
           and mudroom_front, and those two get their band from shellWall.
           Without these the water table stopped dead at x -12.60 and picked
           up again at the block's west corner, with the whole bay bare
           between them. The piers' own 0.24 depth, not WALL_T4, and the
           same centre-line rule; they ride garageDoorG so the band hides
           with the piers when the garage camera looks out through the
           opening. The OPENING itself is left bare on purpose -- a water
           table does not run across a garage door -- and so is the 0.24
           between the east pier and mudroom_front, where the face steps
           back 0.22 in z anyway. */
        [-17.58, -13.22].forEach(function (px) {
          gtag(baseBand(garageDoorG, px - 0.38, 9.88 + GAR_DZ, px + 0.38, 9.88 + GAR_DZ,
                        [0, 0, 1], 'garage', 0.24));
        });
        /* FACADE (arc 4): the door leaf, its board seams, strap hardware
           and top-light row used to be authored here. garageDoorAt() (the
           facade block above) builds them into this same garageDoorG from
           the spec's own style enum, so the openable-door trick and this
           group's registration below are untouched. */
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
          /* the window in the pier east of the door — spec 6b: "other
             faces' windows recolor to the black-frame language at their
             current sizes." Every w/h/x/y/z below is unchanged; only the
             casing color moves, EXTC.trim -> FARMHOUSE.frame. */
          gGlass(0.58, 0.68, -13.22, 2.68, 10.02 + GAR_DZ);
          gtag(box(0.74, 0.09, 0.10, FARMHOUSE.frame, -13.22, 3.07, 10.03 + GAR_DZ, garageDoorG));
          gtag(box(0.80, 0.08, 0.18, FARMHOUSE.frame, -13.22, 2.29, 10.06 + GAR_DZ, garageDoorG));
          [-0.345, 0.345].forEach(function (dx) {
            gtag(box(0.09, 0.86, 0.10, FARMHOUSE.frame, -13.22 + dx, 2.68, 10.03 + GAR_DZ,
                     garageDoorG));
          });
          if (DETAIL >= 3) {
            gtag(box(0.05, 0.68, 0.05, FARMHOUSE.frame, -13.22, 2.68, 10.04 + GAR_DZ, garageDoorG));
            gtag(box(0.58, 0.05, 0.05, FARMHOUSE.frame, -13.22, 2.68, 10.04 + GAR_DZ, garageDoorG));
          }
          /* the gable's half-round, and a coach lamp beside the door —
             same black-frame recolor, same unchanged size/position. */
          gGlass(0.44, 0.44, -15.40, 5.36, 10.27 + GAR_DZ);
          gtag(cyl(0.34, 0.34, 0.09, FARMHOUSE.frame, -15.40, 5.36, 10.24 + GAR_DZ,
                   garageDoorG, 16)).rotation.x = Math.PI / 2;
          if (DETAIL >= 3) {
            gtag(box(0.05, 0.42, 0.05, FARMHOUSE.frame, -15.40, 5.36, 10.28 + GAR_DZ, garageDoorG));
            gtag(box(0.42, 0.05, 0.05, FARMHOUSE.frame, -15.40, 5.36, 10.28 + GAR_DZ, garageDoorG));
          }
          gtag(box(0.10, 0.34, 0.09, C.ink, -17.58, 2.96, 10.02 + GAR_DZ, garageDoorG,
                   { rough: 0.5 }));
          gtag(box(0.34, 0.09, 0.26, C.ink, -17.58, 3.16, 10.13 + GAR_DZ, garageDoorG,
                   { rough: 0.5 }));
          /* R5: the shade becomes a lathe on PROFILES.shade — the same
             wide-flare-at-the-rim silhouette the tapered cyl approximated
             with two radii — and the flat disc cap above it becomes a
             squashed `finial` (the trick R4 used for headlight housings).
             latheAt grows a profile UP from the given y, where cyl() grew
             it from its own CENTRE, so the y below is the old span's low
             edge, not the old centre; x/z and the overall span are
             unchanged. The round shade has no "facing" left to turn, so
             the old 45-degree twist is dropped. NO_MERGE is what actually
             keeps the night glow honest here, not the object's rarity
             today: this is still the only mesh carrying userData.lamp,
             and a future bucket crossing mergeStatic's 4-item floor on
             this exact material must not be allowed to fold it into a
             combined mesh and strand the toggle (webgl_coachLampGlass is
             added to NO_MERGE beside webgl_garageBackWall, below). */
          var lamp2 = gtag(latheAt('shade', [0.37, 0.34, 0.37], 0xf7e8c2,
                                   -17.58, 2.59, 10.16 + GAR_DZ, garageDoorG, GLOSS));
          lamp2.userData.lamp = true;       /* geometry only: the pass lights it */
          lamp2.userData.glazing = true;
          exteriorAnchor(garageDoorG,lamp2,'garage',4.8);
          webgl_coachLampGlass = lamp2;
          gtag(latheAt('finial', [0.22, 0.06, 0.22], C.ink, -17.58, 2.93,
                       10.16 + GAR_DZ, garageDoorG, { rough: 0.5 }));
          gtag(cyl(0.20, 0.20, 0.05, C.ink, -17.58, 2.57, 10.16 + GAR_DZ, garageDoorG,
                   4, { rough: 0.5 })).rotation.y = Math.PI / 4;
        }
        [5.10].forEach(function (y) {
          gtag(box(5.60, 1.0, 0.30, cladColour('garage'),
                    -15.4, y, 10.02 + GAR_DZ, garageDoorG,
                    sharp({ rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') })));
        });
      }
      /* The lower cross roof spans both garage and mudroom. The bay
         keeps its original walls and door as separate navigation fabric. */
      garageShellG = new T.Group();
      extG.add(garageShellG);
      [gWallW, gWallE, garageBackWall].forEach(function (m) { garageShellG.add(m); });
      [-18.08, -12.72].forEach(function (x) {
        box(0.30, 1.0, 8.0, cladColour('garage'),
            x, 5.10, 6.0, garageShellG, sharp({ rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') }));
      });
      /* THE VAULT (see roofVault, way above). The two bands just above
         carry these walls to the block's eave; the EAST one is the wall
         between the garage and the mudroom, and above the eave it used
         to stop dead -- so the mudroom's own shelf wall read over the
         top of it. It runs along the garage block's slope axis, whose
         ridge (z 2.00) crosses this wall's north end, so the profile is
         a trapezoid falling from 9.04 at the ridge to the eave at the
         street. The WEST band needs nothing: `garage_block_west` stands
         outboard of it and `garage_block_roof_end_west`'s gable infill
         closes the block above. */
      /* task 7: ... and only on a ONE-story garage block. Two stories put
         a sealed upper floor between this wall's head and the deck (see
         VAULTED's own paragraph, far above), so the wall keeps the flat
         top at EXT_TOP4 that the two bands just above already give it. */
      var gVault = roofVault(GARAGE_BLOCK, ROOF_FORMS.garage, blockPitch('garage'));
      if (gVault.axis === 'z' && ROOF_FORMS.garage.form === 'gable' &&
          !upperOverlapsX('garage', -12.72, -12.42))
        /* vFrom 4.6: the band just above starts ITS courses at its own
           bottom edge, so the section continues them from there rather
           than opening a fresh course at the eave. */
        vaultSection(garageShellG,
                     vaultRidgePts(gVault, 2.0, 10.0, EXT_TOP4),
                     EXT_TOP4, 'z', -12.57, 0.30,
                     cladColour('garage'),
                     { rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') }, 4.6);
      /* VIEW-VOLUME MASKING (task 4): the garage camera's mask grazes
         this row (0.04) and no other room's touches it; `n` is read by
         the AO derivation and the registry report only. The paragraph
         below is the retired solver's record of the choice.
         n [1,0,0]: no single physical face works for a piece that is
         three walls plus a roof wrapped around one room — but the garage
         is the westmost structure on the whole property, so every OTHER
         room's own subject centre (kitchen x -2.785, living x 0, mudroom
         x -9.62 — read off their own ROOM_AABB) sits EAST of
         garage_shell's own box centre (x -15.4), and so does every
         camera except the garage's own (HOME_POS 4.64 -- 14.6 before
         the cutaway-ownership fix moved it south, still far east of
         -15.4 -- LIV_POS 0, MUD_POS -3.4). With n=[1,0,0], camOut is
         therefore true for those
         three and subIn (subject.x < box centre.x) false for all three —
         never ghosts for kitchen, mudroom or living. The garage's OWN
         subject is the one case that ghosts: its ROOM_AABB centre lands
         at this piece's own box centre (both walls and the room they
         enclose are built symmetric around the same x, so the two
         centres coinciding is structural) and the measured dot product
         lands on the ghost side — the same outline treatment garage_door
         itself already gave this room pre-split (a room ghosting its OWN
         enclosing shell while its OWN camera looks at it from outside
         that shell matches mudroom_roof/west_wall's own pattern for
         mudroom, not a new case). Verified against the extended verdict
         table below. */
      regFabric(garageShellG, { name: 'garage_shell', n: [1, 0, 0],
                                box: fabBox(garageShellG), room: 'garage' });
      /* SHELL: garage_door is complete here — the door leaf/frame/
         window/hardware/coach lamp are all in, and the roof/walls just
         moved OUT above, so fabBox now measures only the door assembly
         itself (jambs/piers at z 9.88, header/trim/glazing/lights out to
         z 10.28) — no longer the gable's own full 1.4..10.6 depth. The
         old z-clamp (Task 2) existed only because door + gable roof
         registered as ONE piece, landing this box's centre exactly on
         the garage room's own aabb centre and defeating subIn for every
         camera; that comment's own words said whoever registers the
         split should delete it rather than inherit it, so the clamp is
         gone rather than carried forward. Re-verified against the
         extended verdict table below: the garage view still reads
         garage_door as 'ghost'; kitchen/mudroom/living/exterior all
         still read it 'solid'. */
      var gdBox = fabBox(garageDoorG);
      /* VIEW-VOLUME MASKING (task 2): the leaves, header, glazing,
         lights and coach lamp are a kit, same reasoning as the facade's
         own doors. */
      /* task 8: a side-entry door faces WEST, and `n` is what every
         reader (the AO derivation, the registry report, the nav probe's
         face lookup) takes for the way this piece looks. */
      regFabric(garageDoorG, { name: 'garage_door',
                                n: GARAGE_SIDE ? [-1, 0, 0] : [0, 0, 1],
                                box: gdBox, room: 'garage', kit: true });
      if (GARAGE_SIDE) blobShadow(4.2, 3.0, GARAGE_BLOCK.west - 1.4, SIDE_DOOR_Z, extG);
      else blobShadow(3.0, 4.2, -15.4, 6.0, extG);
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
        zoneTag(m, 'garage', 'garage');
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
          return axis === 'z' ? gb(L, h, d, c, mid, y, ctr, sharp(o))
                              : gb(d, h, L, c, ctr, y, mid, sharp(o));
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
                                garageInterior, sharp(GMATT))
                          : box(0.045, 3.16, 0.07, C.cab, ctr, 2.94, a,
                                garageInterior, sharp(GMATT)));
        }
      }
      gWall('z', GZ0, 1, GX0, GX1, true);        /* the back wall */
      gWall('x', GX0, 1, GZ0, GZ1, true);        /* the long west wall */
      gWall('x', GX1, -1, GZ0, GZ1, false);      /* the east wall, edge-on */

      /* The mudroom connection was authored only from the mudroom side;
         the garage lining consequently covered its back and read as a
         blank wall. Give the same physical opening its garage-facing leaf,
         casing, two-panel relief, brass knob, and threshold. */
      [3.03, 4.37].forEach(function (cz) {
        gb(0.14, 2.92, 0.15, C.cab, -12.97, 1.46, cz, GMATT);
      });
      gb(0.14, 0.15, 1.62, C.cab, -12.97, 2.85, 3.70, GMATT);
      if (GD2) gb(0.09, 0.09, 1.80, C.cab, -13.01, 2.97, 3.70, GMATT);
      gb(0.10, 2.72, 1.18, C.slate, -12.94, 1.38, 3.70, { rough: 0.62 });
      if (GD2) {
        [[0.86, 1.02], [1.94, 0.94]].forEach(function (pn) {
          gb(0.025, pn[1], 0.86, 0x4a5460, -13.00, pn[0], 3.70,
             { rough: 0.60 });
          if (GD3) gb(0.018, pn[1] - 0.14, 0.72, C.slate, -13.02, pn[0],
                      3.70, { rough: 0.60 });
        });
        gc(0.05, 0.05, 0.10, C.brass, -13.04, 1.36, 4.16, 10, CHROME)
          .rotation.z = Math.PI / 2;
        gb(0.30, 0.05, 1.20, gWoodK, -12.98, GFY + 0.025, 3.70, gWoodO);
      }

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
            /* R4: a lid, proud of the box it closes - the strip above is
               a fold seam, this is a separate cap sitting ON the carton,
               the "not one box" tell (style bible S3) the shelf run was
               still missing */
            gb(0.40, 0.045, 0.32, GCARDD, SX - 0.52, 1.9525, SZ, GMATT);
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
          /* R4: a sweepAt coil, judged against the plain ring it
             replaces - loops that wind AND drift in depth read as a
             hose actually coiled on its hook; a single perfect torus
             reads as a hoop. Same wall position the ring held. */
          var coilPts = [];
          for (var hcI = 0; hcI <= 20; hcI++) {
            var hcF = hcI / 20, hcA = hcF * Math.PI * 2 * 1.6,
                hcR = 0.23 - hcF * 0.06;
            coilPts.push([TY + 0.02 + hcR * Math.cos(hcA),
                         1.02 + hcR * Math.sin(hcA), GZW + 0.14 + hcF * 0.09]);
          }
          gt(sweepAt(coilPts, 0.030, C.teal, garageInterior, { rough: 0.82 }));
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
            /* R4: a lid, proud of the front-most carton on this run */
            gb(0.36, 0.045, 0.46, GCARDD, WXf, 2.4925, Z0 + 0.42, GMATT);
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
      /* THE ESCAPE HATCH (see SCENERY at the top). `garage` is the one zone
         aliased to a whole ROOM, so every shelf, carton and bin in here
         would count as touchable and the bay would be the one place where
         nothing recedes. It is exactly backwards: in the garage the CARS
         and their plaques are the subject — and they live in carsG, a
         sibling of this group — while the bay itself is set dressing. So
         the dressing is tagged scenery, and the tag outranks the zone. */
      garageInterior.traverse(function (o) { o.userData.scenery = true; });
    })();
    /* the front path (door to street) is laid in flags down in the yard
       block: it was one poured ribbon here, which is the defect S7.1
       names. */
    var mailboxG = new T.Group(); extG.add(mailboxG);
    /* driveway from the garage door to the street. Plate 3 scores its
       apron with expansion joints, so the slab reads as poured concrete
       and not as a painted plane; it also stopped half a unit short of
       the garage door, leaving a ribbon of grass under the threshold.
       Now it runs from the door line to the kerb and is saw-cut on a
       grid, the joints proud by a hair so they catch the light. */
    /* MASSING ARC 2 task 6: the apron starts at the garage's own door
       line, so a garage depth shortens it from the house end and leaves
       the kerb end (z 26.30) exactly where it was. Its saw-cut joints
       are absolute positions on the lawn, so the ones a deeper garage
       has swallowed are dropped rather than left stranded in the grass
       short of the slab. Written as `9.60 + (GARAGE_BLOCK.south - 10.10)`
       rather than re-derived, so the canonical is the same numbers. */
    var driveDz = GARAGE_BLOCK.south - 10.10, driveZ0 = 9.60 + driveDz;
    var driveLen = 16.7 - driveDz, driveCz = 17.95 + driveDz / 2;
    /* One continuous side driveway: rounded court, eased approach and
       street entrance. Parking, planting and mailbox read this footprint. */
    var SIDE_DRIVE_X = GARAGE_BLOCK.west - 2.30;
    var SIDE_APRON_Z0 = SIDE_OPEN_Z0 - 0.4, SIDE_APRON_Z1 = SIDE_OPEN_Z1 + 0.4;
    function sideDriveSection(z) {
      var t = Math.max(0, Math.min(1, (z-SIDE_APRON_Z1)/(26.30-SIDE_APRON_Z1)));
      var ease = t*t*(3-2*t);
      var center = GARAGE_BLOCK.west-2.60 + 3.0*ease;
      var width = 5.2-0.6*ease;
      var corner = Math.max(0, Math.min(1, (z-SIDE_APRON_Z0)/0.8));
      var round = 0.8*(1-Math.sqrt(Math.max(0,1-(1-corner)*(1-corner))));
      return {left:center-width/2+round, right:center+width/2, center:center};
    }
    if (GARAGE_SIDE) {
      var driveSections = [], driveSteps = 96;
      for (var di=0; di<=driveSteps; di++) {
        var dz = SIDE_APRON_Z0+(26.30-SIDE_APRON_Z0)*di/driveSteps;
        var ds = sideDriveSection(dz); ds.z = dz; driveSections.push(ds);
      }
      function drivewayRibbon(edge) {
        var positions=[], uvs=[];
        function quad(a,b,c,d) {
          [a,b,c,a,c,d].forEach(function(v) {
            positions.push(v[0],v[1],v[2]); uvs.push(v[0]/4.6,v[2]/16.7);
          });
        }
        function bounds(s) {
          return edge === 'left' ? [s.left,s.left+0.16]
               : edge === 'right' ? [s.right-0.16,s.right] : [s.left,s.right];
        }
        var y=edge ? -0.195 : -0.21, bottom=-0.29;
        for (var i=1;i<driveSections.length;i++) {
          var a=driveSections[i-1], b=driveSections[i], aa=bounds(a), bb=bounds(b);
          quad([aa[0],y,a.z],[bb[0],y,b.z],[bb[1],y,b.z],[aa[1],y,a.z]);
          if (!edge) {
            quad([aa[0],bottom,a.z],[bb[0],bottom,b.z],[bb[0],y,b.z],[aa[0],y,a.z]);
            quad([aa[1],y,a.z],[bb[1],y,b.z],[bb[1],bottom,b.z],[aa[1],bottom,a.z]);
          }
        }
        if (!edge) [driveSections[0],driveSections[driveSteps]].forEach(function(s,i) {
          var a=[s.left,bottom,s.z],b=[s.left,y,s.z],c=[s.right,y,s.z],d=[s.right,bottom,s.z];
          if(i) quad(d,c,b,a); else quad(a,b,c,d);
        });
        var geo=new T.BufferGeometry();
        geo.setAttribute('position',new T.Float32BufferAttribute(positions,3));
        geo.setAttribute('uv',new T.Float32BufferAttribute(uvs,2)); geo.computeVertexNormals();
        var m=new T.Mesh(geo,mat(edge ? EXTC.trim : (NICE ? 0xffffff : EXTC.drive),
                      {rough:0.95,map:edge ? null : driveT}));
        m.name=edge ? 'side_driveway_edge_'+edge : 'side_driveway';
        finish(m); extG.add(m);
      }
      drivewayRibbon(null);
      drivewayRibbon('left'); drivewayRibbon('right');
    } else {
      ebox(4.6, 0.08, driveLen, NICE ? 0xffffff : EXTC.drive, -15.4, -0.25, driveCz,
           { rough: 0.95, map: driveT });
    }
    if (DETAIL >= 2) {
      if (GARAGE_SIDE) {
        // Sparse transverse joints; no centre stripe or rotated apron grid.
        for (var jz=SIDE_APRON_Z0+2.6;jz<25.8;jz+=2.6) {
          var js=sideDriveSection(jz);
          ebox(js.right-js.left-0.32,0.009,0.028,0x8e887d,
               (js.left+js.right)/2,-0.202,jz,{rough:0.95});
        }
      } else {
        [10.85, 12.60, 14.35, 16.10, 17.85, 19.60, 21.35, 23.10, 24.85].forEach(function (jz) {
          if (jz < driveZ0 + 0.20) return;
          ebox(4.6, 0.014, 0.055, 0x8e887d, -15.4, -0.204, jz, { rough: 0.95 });
        });
        ebox(0.055, 0.014, driveLen, 0x8e887d, -15.4, -0.204, driveCz, { rough: 0.95 });
        /* the apron's own edge, where the slab meets the lawn */
        [-1, 1].forEach(function (sx) {
          ebox(0.10, 0.10, driveLen, EXTC.trim, -15.4 + sx * 2.30, -0.245, driveCz,
               { rough: 0.9 });
        });
      }
      /* and the thing every driveway ends in */
      /* the mailbox is a PROP standing in the shell fabric's group, not
         shell fabric itself — box() directly, so it keeps the NICE-tier
         chamfer default ebox() now opts out of */
      /* SIDE-ENTRY (task 8, review fix): a mailbox stands at the kerb end
         of the drive people actually use, and on a side garage that is
         the L's approach, four units west. ONE anchor -- every part below
         is written off `mbX`, at the same offsets from it the front
         drive's mailbox has always used (post at 0, flag arm +0.08..
         +0.15, away from the concrete) -- so the side variant cannot
         drift a flag off its own post. -12.95 is 0.15 outboard of the
         front apron's east edge; GARAGE_BLOCK.west + 0.15 is the same
         0.15 outboard of the approach's east edge. */
      /* the front-entry row is the LITERALS it has always been, not the
         anchor plus a delta: sweepGeo keys its cache on JSON.stringify of
         these points, and -12.95 + 0.08 is -12.870000000000001, a
         different key string for the same arm. */
      var MB = GARAGE_SIDE
        ? { x: sideDriveSection(25.30).right+0.30, f0: sideDriveSection(25.30).right+0.38,
            f1: sideDriveSection(25.30).right+0.42, f2: sideDriveSection(25.30).right+0.45 }
        : { x: -12.95, f0: -12.87, f1: -12.83, f2: -12.80 };
      box(0.10, 0.92, 0.10, C.wood2, MB.x, 0.17, 25.30, mailboxG, { rough: 0.8 });
      box(0.26, 0.24, 0.44, C.slate, MB.x, 0.74, 25.30, mailboxG, { rough: 0.7 });
      if (DETAIL >= 3) {
        /* R5: the flag becomes a swept arm carrying the same paddle —
           same paddle position as before, now reached by a rod instead
           of floating beside the body on its own. */
        sweepAt([[MB.f0, 0.66, 25.30], [MB.f1, 0.72, 25.30],
                 [MB.f2, 0.80, 25.30]], 0.012, C.ink, mailboxG, STEEL);
        box(0.05, 0.16, 0.04, C.red, MB.f2, 0.80, 25.30, mailboxG, GLOSS);
        box(0.28, 0.05, 0.46, C.dark, MB.x, 0.87, 25.30, mailboxG, { rough: 0.7 });
        /* the lid's lift handle, at its street-facing tip */
        latheAt('knob', [0.032, 0.045, 0.032], C.dark, MB.x, 0.87, 25.53,
                mailboxG, STEEL).rotation.x = Math.PI / 2;
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
    var parcelRoad = ebox(50, 0.38, 5, NICE ? 0xffffff : 0x4a4f55, 0.5, -0.50, 28.5,
         { rough: 0.95, map: roadT });
    parcelRoad.name='parcel-road';
    if (GARAGE_SIDE) {
      var entry=sideDriveSection(25.85);
      [[-24.5,entry.left-0.1],[entry.right+0.1,25.5]].forEach(function(run) {
        ebox(run[1]-run[0],0.1,0.5,EXTC.trim,(run[0]+run[1])/2,-0.28,25.85,{rough:0.9});
      });
    } else {
    ebox(50, 0.1, 0.5, EXTC.trim, 0.5, -0.28, 25.85, { rough: 0.9 });
    }
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
      var bev = DETAIL >= 2, bt = 0.05, cs = DETAIL >= 3 ? 7 : 3;
      var depth = width - (bev ? 2 * bt : 0);
      /* task 9b: the tub and glass shapes are built from the body-type
         table (p) alone (archCut/lineTo in buildVehicle never read
         anything per-car) -- the same body_type always extrudes the same
         contour, so this shares exactly like the tyre torus beside it.
         syncGarage's rebuild key includes live battery/fuel, so this used
         to mint two fresh ExtrudeGeometry objects (tub+glass) per car on
         every ordinary telemetry poll. extractPoints(cs) samples the
         shape's own contour (arcs included) at the SAME segment count
         the geometry itself extrudes with, so identical inputs key
         identically and different body tables never collide. */
      var pk = shape.extractPoints(cs).shape.map(function (v) {
        return [v.x, v.y];
      });
      var g = cgeo('E|' + JSON.stringify(pk) + '|' + depth + '|' + bev +
        '|' + cs, function () {
          return new T.ExtrudeGeometry(shape, {
            depth: depth, bevelEnabled: bev,
            bevelThickness: bt, bevelSize: bt, bevelOffset: -bt,
            bevelSegments: 1, steps: 1, curveSegments: cs });
        });
      var m = new T.Mesh(g, mat(colour, opts || GLOSS));
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
      /* R4 tried real transmission glass at high (finish:'glassy',
         thick:0.06) through the fresh-material path every car's paint
         already takes — cars sit inside a zone-tagged group, so mat()
         force-uniques every material it hands out here regardless of
         finish (L1), and there is nothing to share-and-corrupt the way a
         static prop's cached material would be, so the PLUMBING was
         never the problem. The picture was: a probe screenshot
         (zoom_truck_d9, task-9 report) showed the transmission pane
         render as a near-black hole where the working pale-blue pane
         used to be — this shell has no interior modelled, so the
         refraction ray looks straight through the windshield, through
         empty cabin, out the backlight, and samples whatever is behind
         the car, which reads as void. Reverted per the room process
         (the screenshot is the judge, not the code): high tier keeps the
         same recipe as every other tier, just glossier — lower
         roughness, a touch of reflectivity, no transparency to break. */
      tag(profileMesh(gh, glassW, p.glass || CAR_GLASS,
                      DETAIL >= 3 ? { rough: 0.20, metal: 0.02, envInt: 0.35 }
                                  : { rough: 0.34, metal: 0.0, envInt: 0.16 }));

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

      /* -- 5. wheels (R4: real assemblies, not flat discs): tyre in ink,
         a RIM lathed from the 'foot' profile at 0.62 radius, a domed
         'knob' hub cap at tier 3. Ink/steel, the wheel's own palette.

         Both lathes are the K2 unit profile (PROFILES.foot / .knob both
         peak at local radius 0.46) scaled per instance, exactly the
         "one shared cgeo geometry, sized by mesh.scale" trick every other
         room's props already use — one LatheGeometry serves every rim on
         every body type, at every seat_capacity. The radius rides in
         scale.x/scale.z; rotation.z=PI/2 (matching the old cylinder rim's
         own rotation, unchanged) lays the lathe's revolution axis (local
         Y) down along the axle. That is the SAME slot the length-stretch
         counter-scale below writes to for every round part, so it now
         multiplies instead of assigning (buildCar) — the tyre torus never
         set its own scale.z, so nothing about its behaviour changes. */
      var RIM_PK = 0.46, HUB_PK = 0.46;      /* PROFILES.foot / .knob peak */
      function wheelAt(sx, wz, off) {
        var xo = sx * (hw - 0.03) - sx * (off || 0);
        var tw = p.wr * 0.30, t;
        if (DETAIL >= 2) {
          /* task 9b: route through cgeo like the rim/hub lathes beside it.
             p.wr is one-per-body-type, so every wheel on every car of the
             same body shares this — and syncGarage's rebuild key includes
             live battery/fuel, so this used to mint fresh every rebuild. */
          var tRad = p.wr - tw, tRs = DETAIL >= 3 ? 8 : 5,
              tTs = DETAIL >= 3 ? 16 : 10;
          t = new T.Mesh(cgeo('t|' + tRad + '|' + tw + '|' + tRs + '|' + tTs,
            function () {
              return new T.TorusGeometry(tRad, tw, tRs, tTs);
            }), mat(C.ink, { rough: 0.92 }));
          t.rotation.y = Math.PI / 2;
          t.position.set(xo - sx * tw, p.wr, wz);
        } else {
          /* final-fix wave: same leak, same cure, DETAIL<2's own cylinder
             stand-in — cgeo keyed like cyl()'s own cache ('c|rt|rb|h|sg')
             so wheels of matching p.wr share across every car. */
          t = new T.Mesh(cgeo('c|' + p.wr + '|' + p.wr + '|0.20|8', function () {
            return new T.CylinderGeometry(p.wr, p.wr, 0.20, 8);
          }), mat(C.ink, { rough: 0.92 }));
          t.rotation.z = Math.PI / 2;
          t.position.set(xo - sx * 0.10, p.wr, wz);
        }
        t.userData.round = true;
        tag(t);
        if (DETAIL >= 2) {
          var rk = (p.wr * 0.62) / RIM_PK;
          var r = latheAt('foot', [rk, 0.075, rk], C.steel,
                          xo - sx * 0.055, p.wr, wz, grp, STEEL);
          r.rotation.z = Math.PI / 2;
          r.userData.round = true;
          tag(r);
        }
        if (DETAIL >= 3) {
          var hk = (p.wr * 0.26) / HUB_PK;
          var h = latheAt('knob', [hk, 0.05, hk], C.graphite,
                          xo - sx * 0.024, p.wr, wz, grp, STEEL);
          h.rotation.z = Math.PI / 2;
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
      /* R4: one sweepAt trim line across the front bumper's face — the
         grille's own slats and both bumpers already chamfer for free
         (K1's default on every box() that doesn't opt out with sharp()),
         so this is the one truly NEW bumper part the budget allows. */
      if (DETAIL >= 2) {
        tag(sweepAt([[-p.W * 0.40, bumpY, zF + 0.086],
                     [0, bumpY, zF + 0.091],
                     [p.W * 0.40, bumpY, zF + 0.086]],
                    0.014, C.steel, grp, STEEL));
      }
      var tailY = p.bed ? p.bed.rail - 0.24 : p.deck - 0.22;
      var LAMP_PK = 0.34;                    /* PROFILES.finial's peak */
      [-1, 1].forEach(function (sx) {
        var lx = sx * (hw - p.W * 0.155), ly = gMid + gHt * 0.06;
        if (DETAIL >= 2) {         /* R4: the housing is a small squashed
             'finial' dome behind the lens, standing in for the old flat
             bezel — paint only, no emissive; the glow stays the zones'
             language (S6), so a housing never wears anything but rough
             paint even where it reads as "the light". */
          var fhk = (gHt * 0.42) / LAMP_PK;
          var fh = latheAt('finial', [fhk, 0.025, fhk], C.graphite, lx, ly,
                           zF - 0.045, grp, { rough: 0.5 });
          fh.rotation.x = Math.PI / 2;
          tag(fh);
          var rhk = (gHt * 0.40) / LAMP_PK;
          var rh = latheAt('finial', [rhk, 0.025, rhk], C.ink,
                           sx * (hw - p.W * 0.15), Math.max(p.sill + 0.40, tailY),
                           zR + 0.045, grp, { rough: 0.5 });
          rh.rotation.x = -Math.PI / 2;
          tag(rh);
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

      /* -- 6b. door seams (R4): a thin ink recess where a front door
         would meet the next panel. The Z position reads off the SAME
         per-body pil[] table that already places the B-pillar (pil[0]) —
         a body with no intermediate pillar (the truck's two-door cab)
         falls back to the cabin's own midpoint. Kept at D2: the budget
         cap's own degrade order ("keep rims, lose hubs; lose mirrors;
         keep seams") keeps this one down through medium, after mirrors
         and hubs are already gone. */
      if (DETAIL >= 2) {
        var doorF = (p.pil && p.pil.length) ? p.pil[0] : 0.5;
        var doorZ = p.wsB + doorF * (p.blB - p.wsB);
        var seamY0 = p.sill + 0.08, seamY1 = Math.min(p.belt - 0.06, seamY0 + 0.60);
        [-1, 1].forEach(function (sx) {
          tag(box(0.016, seamY1 - seamY0, 0.012, C.ink,
                  sx * (hw + 0.006), (seamY0 + seamY1) / 2, doorZ, grp,
                  sharp({ rough: 0.9 })));
        });
      }

      /* -- 7. mirrors, handles, badge: the finest layer. R4: the whole
         mirror - stalk and head - moved from D2 to D3, so it degrades as
         a unit at the first step below high (the cap's own order: "keep
         rims, lose hubs; lose mirrors; keep seams" — mirrors go together
         with the handles/badge that already lived at this tier). */
      /* `sideMirrors: false` on a body params object means this vehicle has no
         wing mirrors (the bus). It is NOT userData.noMirror, which is the text
         contract's counter-flip flag — two different things that used to share
         one name in this file. */
      if (DETAIL >= 3 && p.sideMirrors !== false) {
        [-1, 1].forEach(function (sx) {
          var mx = sx * (hw + 0.05), my = p.belt + 0.075, mz = p.wsB - 0.12;
          tag(sweepAt([[sx * (hw - 0.02), p.belt + 0.02, p.wsB - 0.04],
                       [mx, my, mz]], 0.017, C.graphite, grp, STEEL));
          tag(rbox(0.13, 0.09, 0.10, 0.025, col, mx, my, mz, grp, GLOSS));
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
             circles are ~40 triangles - not a tier concern.
             Final-fix wave: the geometry now routes through cgeo, unit
             circle scaled at the mesh like every other disc in the
             file — a raw CircleGeometry per ring per car leaked every
             syncGarage rebuild at low/medium (the Pi's tiers). The
             material routes through discMat (K5's own recipe) but MUST
             still go through this function's own `tag`, not a bare
             grp.add: buildVehicle serves two different zones (cars
             'garage', the bus 'curb' — same ring colours, same
             discMat cache entries), and every other part it builds
             already relies on tag()'s own() call to privatize a shared
             material per mesh (L1 — a zone material is never shared).
             own() clones the material, not the geometry, so the
             geometry-sharing win above survives untouched. */
          var segs = DETAIL >= 2 ? 22 : 16;
          var d = new T.Mesh(cgeo('circ|' + segs, function () {
            return new T.CircleGeometry(1, segs);
          }), discMat(ring[2], 1, T.MultiplyBlending, false));
          d.rotation.x = -Math.PI / 2;
          d.scale.set(p.W * ring[0], p.L * ring[1], 1);
          d.position.set(0, 0.012 + ri * 0.004, 0);
          d.renderOrder = -2 + ri;
          tag(d);
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
                     trim: 0x23272c, sideMirrors: false };
    var busG = new T.Group();
    busG.visible = false;
    busG.position.set(-5.5, -0.31, 27.8);
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
        zoneTag(m, 'curb');
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
        /* THE MIRROR (section 3.4): the sign says STOP, so it is a text
           mesh -- btag() below does the parenting and the zone tag. */
        var arm = textMesh(new T.CylinderGeometry(0.27, 0.27, 0.05, 8),
          mat(C.red, GLOSS));
        arm.rotation.z = Math.PI / 2;
        arm.position.set(-(hwB + 0.13), BUS_BODY.belt - 0.10, 0.35);
        btag(arm);
        /* R5 (open items: reads as a no-entry circle, not a stop sign)
           — btag's zoneTag already cloned arm.material to a private
           instance (L1: a zone never shares), so painting it here
           touches only this one mesh. The canvas idiom every other
           procedural texture in the file uses: drawn once, cached in
           the closure, never redownloaded. Base colour goes white so
           the map's own red/cream carries the true sign colours
           instead of being multiplied by C.red a second time; the
           octagon's thin rim samples the same map's border ring, which
           is the right colour for an edge anyway. */
        var stopArmTex = canvasTex(128, function stopArm(g, S) {
          g.fillStyle = '#c9473d'; g.fillRect(0, 0, S, S);
          g.strokeStyle = '#f2ece1'; g.lineWidth = S * 0.09;
          g.beginPath(); g.arc(S / 2, S / 2, S * 0.40, 0, Math.PI * 2);
          g.stroke();
          g.fillStyle = '#f2ece1';
          g.font = 'bold ' + Math.round(S * 0.30) + 'px Arial, sans-serif';
          g.textAlign = 'center'; g.textBaseline = 'middle';
          g.fillText('STOP', S / 2, S / 2 + S * 0.01);
        });
        arm.material.color.setHex(0xffffff);
        arm.material.map = stopArmTex;
        arm.material.needsUpdate = true;
        /* the mesh this map lands on came out of textMesh() a few lines
           up, which is what keeps STOP reading forward on a mirrored
           plan; the ring below wears no lettering and is an ordinary
           mesh (spec 2026-09-17 section 3.4). */
        if (DETAIL >= 3) {
          var ring = new T.Mesh(new T.CylinderGeometry(0.17, 0.17, 0.055, 8),
            mat(C.cream, GLOSS));
          ring.rotation.z = Math.PI / 2;
          /* R5: was -(hwB + 0.145) — FARTHER out than the arm itself
             (arm sits at -(hwB + 0.13)), which puts this disc BETWEEN
             the traffic side and the arm's own face and blanks out the
             centre of the octagon exactly where STOP now reads. Tucked
             behind the arm instead (still proud of the mount box at
             -(hwB + 0.05)); its own radius (0.17) is smaller than the
             arm's (0.27), so it stays fully hidden behind the sign
             face from the front, same as it always was from the back. */
          ring.position.set(-(hwB + 0.10), BUS_BODY.belt - 0.10, 0.35);
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
      /* long tall cabin, a LONG flat bonnet, a slab flank. wsB was 1.08
         (R4): from the exterior camera the van and the minivan read as
         the same tall box, so the bonnet plateau (zF-0.16 to wsB) is
         pushed back another 0.22, from 0.64 long to 0.86 — a people-
         mover prow, not a cargo slab. */
      minivan: { L: 3.75, W: 1.74, wr: 0.30, sill: 0.18, nose: 0.66,
                 hood: 0.76, belt: 0.84, deck: 0.84, roof: 1.58,
                 fw: 1.18, rw: -1.12, wsB: 0.86, wsT: 0.62,
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
      /* tallest, barely any bonnet, a slab flank. roof was 1.96 (R4):
         raised again so the van clears the minivan's 1.58 by 0.56, not
         0.38 — a gap the exterior camera can actually resolve at
         house scale, where the old margin read as the same silhouette. */
      van:     { L: 3.85, W: 1.80, wr: 0.32, sill: 0.20, nose: 0.92,
                 hood: 0.98, belt: 1.04, deck: 1.04, roof: 2.14,
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
        zoneTag(m, 'garage', 'garage');
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
          /* R4 multiplies rather than assigns: a lathed rim/hub carries its
             OWN radius in scale.z (a unit lathe + mesh scale is how one
             cached geometry serves every wheel size — see wheelAt), and an
             assignment here would silently overwrite that radius with the
             stretch's reciprocal instead of combining with it. Every
             pre-R4 round part (the tyre) left scale.z at its default 1, so
             multiplying reproduces the old behaviour for those exactly,
             and is the only form that is also correct for the new ones. */
          if (o.userData && o.userData.round) o.scale.z *= 1 / k;
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
      mtag(ebox(5.6, 4.2, 0.24, cladColour('garage'),
                -9.8, 2.1, 2.48, { rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') }));
      /* the street end is the mudroom's "garage door": hidden from the
         inside so the camera can look straight into the room */
      var mudFrontWall = mtag(ebox(5.6, 4.2, 0.24, cladColour('garage'),
                -9.8, 2.1, 8.32, { rough: 0.95, facadeBlock: 'garage', map: CLAD('garage') }));
      mudroomRoofG.add(mudFrontWall);
      /* The cross roof replaces the old flat slab. This legacy registry
         name owns the front wall, street door and trim. Register after
         all those parts join the group, using the actual face normal. */
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
      /* L: same wall bake as the kitchen/living run (wallTex), kept on
         its own opts object because this room's plaster is its own
         rough value (0.94, not 0.95) - not something this slice unifies */
      var PLASTER = { rough: 0.94, map: wallTex }, FAB = { rough: 0.98 };
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
      /* R3 (studio pipeline authored pass): latheAt/sweepAt default their
         own `group` to `scene`, not extG, so every mudroom kit-profile part
         needs the same mtag()+extG wrap mb/mr/mc already give box/rbox/cyl
         — otherwise it neither hides with the room nor tags for tap-routing. */
      function ml(key, s, c, x, y, z, o) { return mtag(latheAt(key, s, c, x, y, z, extG, o)); }
      function msw(pts, r, c, o) { return mtag(sweepAt(pts, r, c, extG, o)); }
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
      function wallRun(axis, face, a0, a1, top, dado, parent) {
        var L = a1 - a0, mid = (a0 + a1) / 2;
        function plate(h, d0, d1, c, y, o) {
          var d = d1 - d0, ctr = face + (d0 + d1) / 2;
          var part = axis === 'z' ? mb(L, h, d, c, mid, y, ctr, sharp(o))
                              : mb(d, h, L, c, ctr, y, mid, sharp(o));
          if (parent) parent.add(part);
          return part;
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
        mb(5.75, 0.14, 0.14, TRIM, -9.725, 4.11, NWF + 0.12, sharp(MATT));
        mb(0.14, 0.14, 5.75, TRIM, WWF + 0.12, 4.11, 5.425, sharp(MATT));
        if (D3) {
          mb(5.75, 0.05, 0.09, C.cabShade, -9.725, 4.00, NWF + 0.095, sharp(MATT));
          mb(0.09, 0.05, 5.75, C.cabShade, WWF + 0.095, 4.00, 5.425, sharp(MATT));
        }
      }
      /* the west wall breaks either side of the garage door */
      wallRun('x', WWF, 2.55, 2.97, 4.20, true);
      wallRun('x', WWF, 4.43, 8.30, 4.20, true);
      mb(0.05, 1.28, 1.46, C.wall, WWF + 0.025, 3.56, 3.70, sharp(PLASTER));
      /* the east side is the great room's face of the mudroom wall: it
         closes the frame's right edge, so it gets plaster, not siding */
      /* the east side is the great room's face of the mudroom wall, and
         it closes the frame's right edge. Below the room's wall head it
         wears the room's finish; above it the wall runs on to the eaves,
         so a crown marks where the room stops and the rest goes quiet
         instead of standing there as a white cliff. */
      /* MASSING ARC 1 (spec section 2): mudroom_east_finish FOLDS into
         west_wall. This is the mudroom's face of the very wall west_wall
         already registers -- same plane, same room, same [1,0,0] flip,
         same verdict in every view -- so the block boundary is one
         registered piece instead of two stacked on each other. The group
         is parented to westWallG (which sits at identity under scene, so
         every absolute coordinate below is unchanged) and west_wall's
         registered box is re-measured to include it. */
      var mudEastG = new T.Group();
      westWallG.add(mudEastG);
      wallRun('x', -6.85, 4.40, 6.02, 4.20, true, mudEastG);
      mudEastG.add(mb(0.05, 1.40, 1.62, 0xdcd5c8, -6.825, 4.90, 5.21, PLASTER));
      /* and its cut end wears the plates' wall-thickness band, or the
         camera reads raw clapboard down the frame's right edge */
      mudEastG.add(mb(0.34, 5.60, 0.06, C.cabShade, -7.00, 2.80, 6.03, MATT));
      mudEastG.traverse(function (m) { m.userData.room = 'mudroom'; });
      refabBox('west_wall', westWallG);
      refabConvexity('west_wall', westWallG);

      /* ================= 1. the garage door (S7 mudroom.3) =============
         The west wall is the garage connection and was blank. A cased
         opening now: casing boards proud of the wall, a panelled slab in
         slate — the room's first dark anchor — a brass knob, a
         threshold, and a jamb the wall dies into.

         This is the door zone: its marker, tap target and next-leave
         card all belong to this slab. The street door is ordinary shell
         fabric and hides with the front wall when looking inside. */
      var heroDoorG = shellGroup();
      heroDoorG.userData.zone = 'door';
      heroDoorG.userData.room = 'mudroom';
      groups.door = heroDoorG;
      doorG.traverse(function (o) { delete o.userData.zone; });
      mudroomRoofG.add(doorG);
      function gd(m) { heroDoorG.add(m); return zoneTag(m, 'door'); }
      [3.03, 4.37].forEach(function (cz) {
        gd(mb(0.06, 2.92, 0.14, TRIM, WWF + 0.03, 1.46, cz, MATT));
      });
      gd(mb(0.06, 0.14, 1.62, TRIM, WWF + 0.03, 2.85, 3.70, MATT));
      if (D2) gd(mb(0.15, 0.09, 1.80, TRIM, WWF + 0.075, 2.97, 3.70, MATT));
      if (D3) {                        /* the casing's inner bead */
        [3.09, 4.31].forEach(function (cz) {
          gd(mb(0.10, 2.86, 0.03, C.cabShade, WWF + 0.05, 1.43, cz, MATT));
        });
        gd(mb(0.10, 0.03, 1.28, C.cabShade, WWF + 0.05, 2.79, 3.70, MATT));
      }
      gd(mb(0.10, 2.72, 1.18, C.slate, WWF + 0.05, 1.38, 3.70, { rough: 0.62 }));
      if (D2) {                        /* stiles, rails and two panels */
        [[0.86, 1.02], [1.94, 0.94]].forEach(function (pn) {
          gd(mb(0.02, pn[1], 0.86, 0x4a5460, WWF + 0.108, pn[0], 3.70,
                { rough: 0.6 }));
          if (D3) gd(mb(0.02, pn[1] - 0.14, 0.72, C.slate, WWF + 0.122, pn[0],
                       3.70, { rough: 0.6 }));
        });
        gd(mc(0.05, 0.05, 0.09, C.brass, WWF + 0.16, 1.36, 4.16, 10, CHROME))
          .rotation.z = Math.PI / 2;
        gd(mb(0.30, 0.05, 1.20, woodK, WWF + 0.15, FLR + 0.025, 3.70, woodO));
      }
      /* the next-leave HERO CARD moves onto this slab. It was built on the
         street door, where this camera reduced it to a few pixels of edge;
         here it is the brightest thing on the west wall and reads as a
         card from the room's resting pose. Just proud of the panels
         (which end at WWF + 0.132), centred on the 1.18-wide slab, on the
         upper panel — the door's head is at 2.74, so the old 3.02 is the
         one thing about it that cannot be kept. */
      if (!plaque.geometry.userData.cached) plaque.geometry.dispose();
      plaque.geometry = new T.PlaneGeometry(1.10, 0.69);
      plaque.position.set(WWF + 0.16, 2.02, 3.70);
      plaque.rotation.y = Math.PI / 2;         /* the face looks east, +x */
      zoneTag(plaque, 'door');
      mtag(plaque);
      heroDoorG.add(plaque);                   /* reparented off street door */

      /* ================= 2. the bench (S7 mudroom.1) ===================
         It was a plank on four posts. Now it is casework: toe kick,
         carcass, face frame, three open shoe cubbies over a darker back,
         a wood seat that overhangs, and a cushion. */
      var BX = -11.45, BZ = 3.08;
      mCase(BX, BZ, 0, 1.90, 0.62, 0, 0.52, [
        { h: 0.36, kind: 'bays', bays: 3, tiers: 1, depth: 0.56, back: SAGED }
      ], { toe: true });
      /* R3: small turned feet at the two corners the room camera actually
         sees — the back pair sits hard against the cubby's own back panel
         and the wall beyond it, so building them would spend budget on a
         corner nothing frames. TRIM/MATT joins the wall-trim bucket the
         room already has several members deep, so this reads for free. */
      [-0.85, 0.85].forEach(function (dx) {
        ml('foot', [0.055, 0.05, 0.055], TRIM, BX + dx, FLR, BZ + 0.28, MATT);
      });
      mb(2.04, 0.06, 0.68, woodK, BX, 0.55, BZ + 0.02, woodO);
      /* R3: a seat-plank groove strip — the cushion covers the middle of
         the seat, so the plank line goes where it will actually read: the
         two bare overhangs either side of the cushion, not buried under it */
      if (D3) [-0.96, 0.96].forEach(function (dx) {
        mb(0.018, 0.008, 0.64, C.cabShade, BX + dx, 0.584, BZ + 0.02, MATT);
      });
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
        /* the RAIL is static: this mount plate never moves, never hides,
           carries no state — only the bags on it are honest count */
        mr(0.09, 0.17, 0.03, 0.014, C.brass, hx, 1.99, NWF + 0.125, STEEL);
        if (!D2) return;
        /* R3: the arm + tip (2 straight cylinders) become one swept
           J-curve — leaves the plate, bows out and down, curls back up
           into the catch a hung coat actually needs. First pass (r=0.02
           over a 0.19-deep curve) read as a fat gold blob, not a hook —
           thinned the rod and gave the curve more room to bend in. */
        msw([[hx, 1.98, NWF + 0.13], [hx, 1.88, NWF + 0.28],
             [hx, 1.80, NWF + 0.38], [hx, 1.85, NWF + 0.43],
             [hx, 1.98, NWF + 0.40]], 0.014, C.brass, STEEL);
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
      /* R3: 'lathe' pulls (the mechanism R2's kitchen island already
         wired into kCase/kCell — pull:'lathe' swaps kPull's box bar for a
         latheAt('pull',...) turned bar, same count/position) — the room's
         only DOORED built-in, so this is where "cubbies get knob pulls"
         actually lands; the bench's own cubbies are open bays (S3.2, no
         fronts to hang a pull on) and keep their box-free dividers/back
         panel/shelf edges as the frame S3.2 already calls for. */
      mCase(CX, CZ2, 0, 1.45, 0.52, 0, 1.02, [
        { h: 0.46, cells: [{ w: 1, kind: 'drawers2' }] },
        { h: 0.40, cells: [{ w: 1, kind: 'doors2' }] }
      ], { toe: true, face: C.slate, body: 0x2b3138, pull: 'lathe' });
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
      function jamb(m) { mudroomRoofG.add(m); return m; }
      [-10.71, -8.89].forEach(function (jx) {
        jamb(mb(0.12, 4.20, 0.26, C.cabShade, jx, 2.10, 8.21, sharp(MATT)));
      });
      jamb(mb(1.94, 0.12, 0.26, C.cabShade, -9.80, 4.14, 8.21, sharp(MATT)));
      jamb(mb(1.94, 0.07, 0.30, woodK, -9.80, FLR + 0.035, 8.19, sharp(woodO)));
      /* and the slab's STREET face, which is the face this camera sees:
         a glazed upper light, two raised panels, a lockset and a kick
         plate. Everything stays inside the wall's 0.24 of thickness so
         the exterior view still reads as a solid clapboard wall. They
         hide with the front wall, including the jamb and hardware. */
      if (D2) {
        var dz0 = 8.235;
        function dpart(m) {
          mudroomRoofG.add(m); return m;
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
        /* R3: knob handle upgrade to lathe — same position/rotation as
           the plain cylinder it replaces */
        dpart(ml('knob', [0.06, 0.10, 0.06], C.brass, -9.16, 2.06,
                 dz0 + 0.075, CHROME)).rotation.x = Math.PI / 2;
        /* R3: hinge x3 on the jamb side — the knob sits near the east
           jamb (-8.89), so the hinges mirror it onto the west one
           (-10.71), standard top/mid/bottom spacing down the slab's own
           4.1-tall span */
        [0.55, 2.05, 3.55].forEach(function (hy) {
          jamb(ml('hinge', [0.045, 0.10, 0.045], C.brass, -10.68, hy,
                  dz0 - 0.015, STEEL));
        });
      }

      /* MASSING ARC 1 (spec section 2): mudroom_roof is gone as a
         registry name. The geometry it owned -- the mudroom's own street
         wall, its door and that door's jamb and hardware -- is the
         INNER layer of the garage block's street face now, 1.78 behind
         it, so it FOLDS into mudroom_front rather than registering
         beside it: both must leave together or the mudroom's camera
         (which stands south of both) looks at a blank clapboard wall
         instead of into the room. Reparenting into a group that sits at
         identity under extG keeps every absolute coordinate; the
         registered box is re-measured to cover both layers. */
      mudroomFrontG.add(mudroomRoofG);
      refabBox('mudroom_front', mudroomFrontG);
      refabConvexity('mudroom_front', mudroomFrontG);

      /* ---- the backpacks syncMudroom deals onto the bench ------------
         One per PACKING GROUP the household has for the day, and the bag
         says which way that group is going: CLOSED and buckled when every
         item on it is claimed, OPEN — flap thrown back off its hinge, a
         dark mouth, and the work still sticking out of it — while it is
         short. Same bag, two states.

         The difference is deliberately carried by the silhouette (a lid
         standing up, a folder above the rim) and not by any tier-2 or
         tier-3 detail, because `low` is the tier a Pi draws and a Pi must
         still be able to tell a packed bag from an unpacked one across
         the room. The bag itself is built here, where the rounded-box and
         material helpers live. */
      makeBag = function (c, gaping) {
        var g = new T.Group();
        function part(m, p) {
          m.userData.room = 'mudroom'; finish(m); (p || g).add(m); return m;
        }
        function pb(w, h, d, r, col, x, y, z, o, p) {
          var m = new T.Mesh(D2 ? chamferGeo(w, h, d, r) : new T.BoxGeometry(w, h, d),
                             mat(col, o || FAB));
          m.position.set(x, y, z); return part(m, p);
        }
        pb(0.34, 0.46, 0.26, 0.07, c, 0, 0, 0);
        /* the flap rides a hinge at the bag's back top edge, so the two
           states are one number: closed it lies exactly where it always
           did (0, 0.185, 0.01), open it swings off the mouth */
        var hinge = new T.Group();
        hinge.position.set(0, 0.185, -0.125);
        hinge.rotation.x = gaping ? -1.72 : 0;
        g.add(hinge);
        pb(0.345, 0.15, 0.265, 0.05, 0x3a3330, 0, 0, 0.135, null, hinge);
        if (gaping) {
          /* a HOLE in the top of the bag, not a band across it: inset far
             enough that the body's own colour rims it on all four sides */
          pb(0.26, 0.08, 0.17, 0.02, 0x241f1d, 0, 0.215, 0.01, MATT);
          /* and the work still to go in: a folder standing proud of the
             rim, which is the half of the read that survives to `low` */
          pb(0.20, 0.26, 0.045, 0.015, C.cream, -0.035, 0.30, 0.035,
             MATT).rotation.z = 0.13;
          if (D3) pb(0.045, 0.24, 0.05, 0.015, C.oxblood, -0.115, 0.295,
                     0.035, MATT).rotation.z = 0.13;
          if (D2) {
            /* the flap's lining, in the bag's own colour: thrown back it
               turns to face the room, which is what says "this bag's lid
               is up" rather than "a dark slab stands behind a bag" */
            pb(0.31, 0.04, 0.235, 0.012, c, 0, -0.095, 0.135, MATT, hinge);
            var bc = function (r, h, col, x, y, z) {   /* a bottle, half in */
              var m = cyl(r, r, h, col, x, y, z, g, 10, GLOSS);
              m.userData.room = 'mudroom'; m.rotation.z = -0.1; return m;
            };
            bc(0.036, 0.24, C.teal, 0.10, 0.29, -0.03);
            bc(0.022, 0.05, C.cream, 0.113, 0.41, -0.03);
          }
        }
        if (D2) {
          pb(0.26, 0.18, 0.08, 0.03, 0x3a3330, 0, -0.09, 0.15);
          [-0.10, 0.10].forEach(function (sx) {
            pb(0.05, 0.36, 0.05, 0.02, 0x3a3330, sx, 0.00, -0.15);
          });
        }
        if (D3) {
          /* the grab handle sits behind the mouth when the bag is open,
             so the thrown-back flap clears it either way */
          pb(0.11, 0.05, 0.05, 0.02, 0x3a3330, 0, 0.27, gaping ? -0.10 : -0.03);
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
    /* Outdoor props belong to the yard, not the kitchen's solver subject. */
    yardG.add(mailboxG);
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
        var m = new T.Mesh(cgeo('s|unit|' + (Y3 ? 12 : 7) + '|' + (Y3 ? 9 : 5),
            function () { return new T.SphereGeometry(1, Y3 ? 12 : 7, Y3 ? 9 : 5); }),
          mat(c, MATT, inZoneGroup(g || yardG)));
        m.position.set(x, y, z);
        m.scale.set(r, r * (sy || 1), r);
        yt(m); (g || yardG).add(m); return m;
      }
      /* contact BELOW tier 3 only: tier 3 casts a real one out here now */
      function ysh(rx, rz, x, z, tone) {
        if (SHADOWS) return null;
        var m = new T.Mesh(cgeo('circ|' + (Y2 ? 16 : 8), function () { return new T.CircleGeometry(1, Y2 ? 16 : 8); }),
          discMat(tone || 0xa8a4aa, 1, T.MultiplyBlending, false));
        m.rotation.x = -Math.PI / 2;
        m.scale.set(rx, rz, 1);
        m.position.set(x, GY + 0.009, z);
        m.renderOrder = -1;
        /* VIEW-VOLUME MASKING (task 2, fix round 1): a circle (any
           regular-polygon approximation of one) is a flat convex
           polygon, same reasoning as calFace's PlaneGeometry -- stamped
           so the yard's convexity inventory does not depend on the
           SHADOWS tier these discs only exist below. */
        m.userData.convex = true;
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
      var walkGap = GARAGE_SIDE ? [sideDriveSection(24.35).left-0.08,
                                  sideDriveSection(25.55).right+0.08] : null;
      if (walkGap) {
        [[-24.5,walkGap[0]],[walkGap[1],17]].forEach(function(run) {
          yb(run[1]-run[0],0.10,1.20,0xa9a294,(run[0]+run[1])/2,GY+0.015,24.95,STONEO);
        });
      } else yb(38, 0.10, 1.20, 0xa9a294, -2.0, GY + 0.015, 24.95, STONEO);
      if (Y2) {
        for (var sw = walkGap ? -23.5 : -20; sw < 17; sw += 1.55) {
          if (walkGap && sw > walkGap[0]-0.05 && sw < walkGap[1]+0.05) continue;
          yb(0.05, 0.014, 1.20, 0x7d776c, sw, GY + 0.072, 24.95, STONEO);
        }
      }
      /* the front path, relaid in flags (it was one poured ribbon).
         MASSING ARC 2 task 6: the mudroom's own leg starts at the
         mudroom door, so it follows the garage block's depth; the main
         walk already follows PORCH_FRONT_Z4, which the porch (or, with
         no main-face porch, the street face itself) publishes. */
      pave(-9.62, 12.16 + GAR_DZ, -7.02, 13.04 + GAR_DZ, 0.66);
      pave(-9.66, 13.04 + GAR_DZ, -8.74, 24.35, 0.62);
      pave(DOOR_X4 - 1.2, PORCH_FRONT_Z4 + 0.65, DOOR_X4 + 1.2, 24.35, 0.80);
      /* foundation beds: they wrap the corner the camera looks at. A
         bed is planted AGAINST the street face, so the main block's
         depth carries the two front ones and the porch pair out with
         it rather than leaving them inside the living room. */
      bed(-8.70, 14.24 + MAIN_DZ, -3.10, 16.00 + MAIN_DZ, 'SEW');
      bed(5.70, 14.24 + MAIN_DZ, 11.85, 16.00 + MAIN_DZ, 'SEW');
      bed(-3.10, 19.30 + MAIN_DZ, -0.10, 20.80 + MAIN_DZ, 'SEW');
      bed(2.70, 19.30 + MAIN_DZ, 5.70, 20.80 + MAIN_DZ, 'SEW');
      /* MASSING ARC 1: the side garden moves out with the wall. The main
         block's east face went from x 10.40 to 14.65, so every east-side
         planting, the birdbath, the fence's north/south run, the hedge
         beyond it and the two side trees all shift by that same 4.25 --
         one translation, so the composition (bed against the wall, lawn,
         fence, hedge past it) is exactly the one plate 2 set. */
      bed(14.64, -6.10, 16.10, 4.14, 'NES');
      bed(14.64, 9.86, 16.10, 14.12, 'NE');
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
      ].map(function (p) {
        if (p[0] > -3.1 && p[0] < 5.7) {
          p[0] = p[0] < DOOR_X4 ? -2.90 + (p[0] + 3.1) * 0.58
                                    : 2.90 + (p[0] - DOOR_X4) * 0.58;
          p[1] += 5.0;
        }
        /* task 6: the front bed rides the street face, porch group and
           all -- see the bed() calls above */
        p[1] += MAIN_DZ;
        return p;
      }));
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
      ].map(function (p) { p[0] += 7.80; return p; }));
      /* the lawn groups: three specimens and their skirts, so the grass
         reads as a garden and not as a mat */
      planting([
        [15.95, 14.30, 1.06, 'mound', 0, 0],  [16.69, 14.90, 0.62, 'low', 2, 1],
        [16.45, 13.60, 0.80, 'ball', 1, 0],   [15.45, 13.55, 0.66, 'tuft', 3, 0],
        [16.75, 6.10, 1.16, 'mound', 5, 0],   [16.35, 6.86, 0.60, 'low', 4, 3],
        [16.55, 5.32, 0.82, 'ball', 2, 0],    [15.87, 6.02, 0.64, 'tuft', 0, 0],
        [16.30, 9.90, 0.92, 'mound', 3, 0],   [16.85, 10.55, 0.58, 'low', 0, 1],
        [15.80, 10.45, 0.70, 'ball', 4, 0],
        /* task 6 (fix round 1): these four stand against the GARAGE
           block's street corner, not the east side the rest of this bed
           runs up, so they ride GAR_DZ the way the main-face planting
           rides MAIN_DZ. */
        [-11.40, 13.60 + GAR_DZ, 1.00, 'mound', 2, 0], [-11.95, 14.20 + GAR_DZ, 0.62, 'low', 0, 1],
        [-10.85, 14.25 + GAR_DZ, 0.74, 'ball', 3, 0],  [-12.15, 13.10 + GAR_DZ, 0.66, 'tuft', 1, 0]
      ]);

      /* the neighbour's hedge, beyond the fence: the far corner of the
         frame is a boundary, not a void */
      planting([
        [19.45, 15.30, 1.10, 'mound', 1, 0], [19.85, 14.10, 1.20, 'mound', 3, 0],
        [19.55, 12.90, 1.06, 'mound', 0, 0], [19.95, 11.70, 1.16, 'mound', 1, 0],
        [19.65, 10.50, 1.02, 'mound', 3, 0], [20.05, 9.30, 1.14, 'mound', 0, 0],
        [19.75, 8.10, 1.08, 'mound', 1, 0],  [20.10, 6.90, 1.18, 'mound', 3, 0]
      ]);
      /* the drive's east edge and the mailbox foot: the left of the
         frame was a driveway and a mown void */
      /* task 6 (fix round 1): the drive's east edge runs FROM the garage
         block's street corner up to the kerb, and the two pots stand at
         the mudroom's own door -- all of it moves out with the garage
         block's depth, exactly as the main-face beds move with the
         main's. The bed's kerb end (16.30) travels with the rest: it is
         the planting's own composition against the face, not a line
         pinned to the pavement. */
      bed(-12.98, 10.90 + GAR_DZ, -11.72, 16.30 + GAR_DZ, 'SEN');
      planting([
        [-12.40, 15.72 + GAR_DZ, 0.94, 'mound', 0, 0], [-12.34, 15.02 + GAR_DZ, 0.56, 'low', 2, 1],
        [-12.42, 14.34 + GAR_DZ, 1.06, 'column', 1, 0], [-12.36, 13.64 + GAR_DZ, 0.74, 'ball', 3, 0],
        [-12.40, 12.96 + GAR_DZ, 0.62, 'tuft', 4, 0],  [-12.34, 12.26 + GAR_DZ, 0.90, 'mound', 2, 0],
        [-12.42, 11.56 + GAR_DZ, 0.58, 'low', 1, 3],   [-12.40, 16.02 + GAR_DZ, 0.60, 'mound', 3, 1],
        [-12.86, 15.34 + GAR_DZ, 0.50, 'low', 0, 2]
      ]);
      pot(-10.35, 12.85 + GAR_DZ, 0.90, C.terracotta, 'spray');
      pot(-10.30, 13.78 + GAR_DZ, 0.76, C.cream, 'mound');

      /* the fence: an L round the side garden, clear of the bus (which
         stands at x -8.3..-2.7, z 18.8..20.8) and of the path */
      fence('x', 2.70, 17.45, 24.30);
      fence('z', 3.00, 24.30, 17.45);
      /* R5: hinge + latch at the gate coordinates — the fence's own
         literals name exactly one distinguished point, the corner post
         both runs share (17.45, 24.30), so that reads as the gate.
         These are small hardware bits mounted ON that EXISTING post,
         not a new swinging panel: the picket run itself (yb, folded
         into InstancedMesh by instanceYard below) is untouched, and
         these ride extG directly so instanceYard's own yardG-scoped
         traversal never reaches them. */
      sweepAt([[17.45, GY + 0.72, 24.40], [17.45, GY + 0.72, 24.34],
               [17.45, GY + 0.60, 24.34]], 0.014, C.brass, extG, STEEL);
      sweepAt([[17.45, GY + 0.38, 24.40], [17.45, GY + 0.38, 24.34],
               [17.45, GY + 0.26, 24.34]], 0.014, C.brass, extG, STEEL);
      latheAt('knob', [0.030, 0.05, 0.030], C.brass, 17.525, GY + 0.55,
              24.30, extG, CHROME).rotation.z = -Math.PI / 2;
      ysh(7.73, 0.24, 9.88, 24.44);       /* nothing floats, S4 */
      ysh(0.24, 10.70, 17.59, 13.62);
      /* a birdbath on the side lawn: the vertical the grass wanted */
      (function () {
        var bx = 15.15, bz = 5.60;   /* the lawn's vertical */
        yl(0.13, 0.20, 0.86, EDGE, bx, GY + 0.43, bz, Y3 ? 14 : 8, STONEO);
        yl(0.30, 0.30, 0.06, EDGE, bx, GY + 0.03, bz, Y3 ? 14 : 8, STONEO);
        yl(0.42, 0.30, 0.16, EDGE, bx, GY + 0.92, bz, Y3 ? 16 : 8, STONEO);
        if (Y2) yl(0.35, 0.35, 0.03, 0x8fb6c4, bx, GY + 0.995, bz,
                   Y3 ? 16 : 8, GLOSS);
        ysh(0.34, 0.32, bx + 0.05, bz + 0.04);
      })();

      /* MASSING ARC 1 (spec section 2): the terrace, its table, chairs,
         planter, bench, watering can and pots all stood on ground that
         is the main block's east room and study now. Deleted with the
         massing they furnished; nothing here was interactive. The three
         pots' own kPlant/yl/yr builders stay in use elsewhere. */

      /* four trees, three silhouettes (S7.4). The old pair were two
         spheres on a stick, and one of them stood at x 17.5 - entirely
         outside the frame. */
      // Side-entry paving occupies the old tree position. Keep the trunk
      // 2.8 units inside the front lawn and ahead of the garage building.
      tree(GARAGE_SIDE ? sideDriveSection(GARAGE_BLOCK.south+4.60).right+2.80 : -19.60,
           GARAGE_SIDE ? GARAGE_BLOCK.south + 4.60 : 13.90,
           1.45, 'broad', 0.5);
      tree(17.85, 4.60, 1.12, 'open', 2.2);
      tree(18.25, 12.70, 1.05, 'gold', 1.1);
      /* the back line: four crowns that break the skyline, so the roofs
         sit against something instead of floating in a quarter-frame of
         empty sky */
      /* MASSING ARC 1 (orbit spec section 4): the big one stood at x
         -3.50, which was a skyline crown while the back of the house
         could only ever be a silhouette. Orbit stop 5 looks straight up
         the north wall, and that sight line passes x ~ -2.2 at this
         tree's own z -- so the tree stood in the BACK DOOR, hiding the
         kitchen's only exterior entry behind a canopy and leaving that
         stop with no marker at all. Slid west to the middle of the gap
         between the stop-4 and stop-5 sight lines (x -9.75 and -2.16 at
         z -12.20), which clears both by ~3.8 against a ~3.5 crown
         half-width. Same z, same size, same silhouette from the street. */
      tree(-5.95, -12.20, 1.85, 'broad', 1.9);
      tree(-22.60, -7.00, 1.60, 'broad', 2.7);
      tree(8.60, -12.60, 1.75, 'open', 0.8);
      tree(-11.60, -13.20, 1.50, 'broad', 0.3);
    })();
    /* ---- B2 (batching spec): bake the garden into instances ----------
       The yard is ~1,043 meshes drawn one call each, and after B1 its
       repeated props already SHARE geometry and material objects — so
       identical (geometry, material) pairs are the buckets, and no
       builder needs to know it is being instanced. One InstancedMesh per
       pair (L3: tinting stays a material property, applyScenery
       untouched). Zone-stamped meshes (bus, curb) keep their own draw
       so taps keep routing (L4). */
    function instanceYard() {
      var MIN = 8;
      var buckets = {}, kill = [];
      yardG.updateMatrixWorld(true);
      var inv = new T.Matrix4().copy(yardG.matrixWorld).invert();
      yardG.traverse(function (o) {
        if (!o.isMesh || o.isInstancedMesh) return;
        for (var p = o; p && p !== yardG; p = p.parent)
          if (p.userData && p.userData.zone) return;
        if (o.userData.zone) return;
        var k = o.geometry.uuid + '|' + o.material.uuid + '|' +
                (o.castShadow ? 1 : 0) + (o.receiveShadow ? 1 : 0) + '|' +
                (o.renderOrder || 0);
        (buckets[k] = buckets[k] || []).push(o);
      });
      var made = 0, folded = 0;
      Object.keys(buckets).forEach(function (k) {
        var list = buckets[k];
        if (list.length < MIN) return;
        var first = list[0];
        var im = new T.InstancedMesh(first.geometry, first.material,
                                     list.length);
        im.frustumCulled = false;
        im.castShadow = first.castShadow;
        im.receiveShadow = first.receiveShadow;
        im.renderOrder = first.renderOrder;
        var m4 = new T.Matrix4();
        list.forEach(function (o, i) {
          m4.copy(inv).multiply(o.matrixWorld);
          im.setMatrixAt(i, m4);
          kill.push(o);
        });
        im.instanceMatrix.needsUpdate = true;
        yardG.add(im);
        made++; folded += list.length;
      });
      kill.forEach(function (o) { if (o.parent) o.parent.remove(o); });
      (function prune(g) {
        for (var i = g.children.length - 1; i >= 0; i--) {
          var ch = g.children[i];
          if (ch.isGroup) { prune(ch); if (!ch.children.length) g.remove(ch); }
        }
      })(yardG);
      return { made: made, folded: folded };
    }
    /* SHELL: yard registers HERE, before instanceYard() runs below, on
       purpose — three's Box3.expandByObject unions a mesh's own
       geometry.boundingBox transformed by that mesh's matrixWorld, with
       no per-instance awareness of InstancedMesh at all (verified
       against the vendored r150 build). Folding the yard's ~1,000
       individual meshes into a handful of InstancedMesh objects first
       would make fabBox(yardG) measure a few base-geometry footprints
       near the origin instead of the true planted footprint. The mask
       never reads this box either (the yard hides whole in every room
       view, by identity -- buildRoomShells' ruling 3 -- not by a
       registered mode), but recording the real one costs nothing and
       avoids a registration-data mystery for whoever reads it next. */
    regFabric(yardG, { name: 'yard', n: [0, 1, 0], box: fabBox(yardG) });
    instanceYard();
    /* VIEW-VOLUME MASKING (task 2, fix round 1): instanceYard() just
       replaced hundreds of individual props with a couple dozen
       InstancedMesh objects -- the row's `convexity` scanned above at
       regFabric() time describes the population BEFORE that swap, same
       staleness refabConvexity already fixes for west_wall/mudroom_front.
       Re-scan now so chfFabricConvexity()/Task 3 see the real, final
       yard population (every InstancedMesh, none carrying
       userData.convex, all exempt from the mask per scanConvexity's own
       comment below). */
    refabConvexity('yard', yardG);
    /* sky dome: weather-painted from the inside, swapped by applyState.
       The dome IS the background now, so the flat clear color retires. */
    var skyDome = new T.Mesh(new T.SphereGeometry(neighborhoodEnabled ? 420 : 80, 24, 12),
      new T.MeshBasicMaterial({ side: T.BackSide }));
    skyDome.rotation.y = Math.PI / 4;   /* UV seam behind the house, not the camera */
    extG.add(skyDome);
    scene.background = null;

    /* ---- THE TAP LAW (batching spec L6) -------------------------------
       onTap used to guess "the house" from hit.position.y — a rule that
       dies the moment merged fabric sits at its group's origin, and the
       rule that once let two blob trees open the kitchen. The judgment
       moves HERE, to build time, while every mesh still stands at its
       own coordinates: shell fabric above the plinth is stamped with the
       room it opens (kitchen, unless something nearer already routed
       it), zone-tagged strays borrow their zone's room, and everything
       else out here is scenery. The tap path then reads tags only. */
    extG.updateMatrixWorld(true);
    (function stampHouse() {
      var bb = new T.Box3();
      extG.traverse(function (o) {
        if (!o.isMesh || o === skyDome) return;
        for (var p = o; p && p !== extG; p = p.parent) {
          if (p === yardG) return;                    /* scenery stays a view */
          if (p.userData && p.userData.room) return;  /* already routed */
          if (p.userData && p.userData.zone) {        /* stray: borrow the room */
            var zr = ZONE_ROOM[p.userData.zone];
            if (zr) o.userData.room = zr;
            return;
          }
          /* SHELL (spec section 5): a registered fabric group that chose
             NO room (regFabric's o.room left absent/null, T8's future
             inert massing) is a deliberate scenery decision, not a gap
             this fallback should paper over with a guessed 'kitchen'. */
          if (p.userData && p.userData.fabric) return;
        }
        bb.setFromObject(o);
        if (bb.max.y > 0.6) o.userData.room = 'kitchen';
      });
    })();

    /* ---- B3 (batching spec): merge the static fabric ------------------
       Same material + same shadow flags + same room tag + same
       hide-group = one mesh. Hand-rolled (BufferGeometryUtils is not in
       the vendored bundle): expand to non-indexed, transform into the
       root's space, concatenate. Triangle count is unchanged; draw
       calls collapse. Transparent materials keep their own draws (order
       semantics), unshared materials are somebody's mutation target and
       are skipped, zones are exempt (L4), and each hide-group merges
       only within itself (L5). */
    function mergeGeoms(meshes, originMatrix) {
      var pos = [], nor = [], uv = [];
      var inv = new T.Matrix4().copy(originMatrix).invert();
      var m4 = new T.Matrix4(), n3 = new T.Matrix3(), v = new T.Vector3();
      meshes.forEach(function (o) {
        var g = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry;
        var p = g.attributes.position, n = g.attributes.normal,
            u = g.attributes.uv;
        m4.copy(inv).multiply(o.matrixWorld);
        n3.getNormalMatrix(m4);
        for (var i = 0; i < p.count; i++) {
          v.fromBufferAttribute(p, i).applyMatrix4(m4);
          pos.push(v.x, v.y, v.z);
          if (n) {
            v.fromBufferAttribute(n, i).applyMatrix3(n3).normalize();
            nor.push(v.x, v.y, v.z);
          }
          if (u) uv.push(u.getX(i), u.getY(i)); else uv.push(0, 0);
        }
        if (g !== o.geometry) g.dispose();   /* the temp non-indexed copy */
      });
      var out = new T.BufferGeometry();
      out.setAttribute('position', new T.Float32BufferAttribute(pos, 3));
      if (nor.length)
        out.setAttribute('normal', new T.Float32BufferAttribute(nor, 3));
      out.setAttribute('uv', new T.Float32BufferAttribute(uv, 2));
      return out;
    }
    function mergeStatic(root, noMerge) {
      root.updateMatrixWorld(true);
      var buckets = {};
      root.traverse(function (o) {
        if (!o.isMesh || o.isInstancedMesh) return;
        if (noMerge.has(o)) return;
        for (var p = o; p && p !== root.parent; p = p.parent) {
          if (p !== o && noMerge.has(p)) return;
          if (p.userData && p.userData.zone) return;       /* L4 */
        }
        if (!o.material.userData || !o.material.userData.shared) return;
        if (o.material.transparent) return;
        var roomTag = '';
        for (var q = o; q && q !== root.parent; q = q.parent)
          if (q.userData && q.userData.room) { roomTag = q.userData.room; break; }
        var k = o.material.uuid + '|' + (o.castShadow ? 1 : 0) +
                (o.receiveShadow ? 1 : 0) + '|' + (o.renderOrder || 0) +
                '|' + roomTag + '|' + (o.visible ? 1 : 0);
        (buckets[k] = buckets[k] || []).push(o);
      });
      function composite(list, k) {
        var first = list[0];
        var mm = new T.Mesh(mergeGeoms(list, root.matrixWorld),
                            first.material);
        mm.castShadow = first.castShadow;
        mm.receiveShadow = first.receiveShadow;
        mm.renderOrder = first.renderOrder;
        mm.visible = first.visible;   /* bucket key now guarantees every
          list member agrees, so this can only ever copy a uniform value
          — but without it a build-time-hidden static's OWN bucket would
          still default to visible (Mesh's own default), rendering
          exactly the geometry the bucket key was just fenced to hide */
        mm.userData.merged = true;    /* lets test invariants count the
          merge-independent population (survivors only), not a post-merge
          draw-call count */
        var rt = k.split('|')[3];
        if (rt) mm.userData.room = rt;
        root.add(mm);
        return mm;
      }
      Object.keys(buckets).forEach(function (k) {
        var list = buckets[k];
        if (list.length < 4) return;
        /* VIEW-VOLUME MASKING (task 3): a fabric mesh the mask cuts in
           some room views carries userData.maskPattern ('|kitchen|living|'
           -- the rooms whose view hides it, its remnant standing in). A
           bucket with none of those merges exactly as before. A bucket
           with some does NOT split by pattern (that was tried: every
           (material x pattern) sub-bucket under the 4-item floor became
           a loose draw, +94 in the exterior, against "exterior
           unchanged"). Instead the FULL composite is built exactly as
           before -- so the exterior and the orbit draw the same list --
           and carries the union of its members' patterns (hidden in any
           room where any member is hidden); then one composite per
           DISTINCT surviving subset stands in for it in the rooms that
           hide that subset (userData.maskOnly: the rooms it is visible
           in, and in no other view). A room view therefore draws one
           composite where it drew one before, plus the room's remnants.
           The price is geometry: the surviving members duplicated once
           per distinct subset (measured and recorded in the report). */
        var rooms = {};
        list.forEach(function (o) {
          var pat = o.userData && o.userData.maskPattern;
          if (pat) pat.split('|').forEach(function (r) { if (r) rooms[r] = true; });
        });
        var full = composite(list, k), union = Object.keys(rooms);
        if (union.length) {
          full.userData.maskPattern = '|' + union.join('|') + '|';
          var subsets = {};
          union.forEach(function (r) {
            var idx = [];
            list.forEach(function (o, i) {
              if ((o.userData.maskPattern || '').indexOf('|' + r + '|') < 0) idx.push(i);
            });
            var sk = idx.join(',');
            (subsets[sk] = subsets[sk] || { idx: idx, rooms: [] }).rooms.push(r);
          });
          Object.keys(subsets).forEach(function (sk) {
            var sub = subsets[sk];
            if (!sub.idx.length) return;      /* every member hidden there: nothing stands in */
            var part = composite(sub.idx.map(function (i) { return list[i]; }), k);
            part.userData.maskOnly = '|' + sub.rooms.join('|') + '|';
            part.visible = false;             /* until solveShell shows a room */
          });
        }
        list.forEach(function (o) { if (o.parent) o.parent.remove(o); });
      });
    }
    // Fixture-owned anchors replace the old world-fixed garage lamp. Limit
    // real lamps to six; every fixture still glows and porches retain pools.
    exteriorAnchors.sort(function(a,b) {
      var rank={porch:0,garage:1,door:2}; return rank[a.role]-rank[b.role];
    });
    if (DETAIL >= 2) exteriorAnchors.slice(0,6).forEach(function(a) {
      a.g.updateMatrixWorld(true);
      var pos=a.lamp.position.clone();
      if(a.role !== 'porch') pos.z+=0.22; else pos.y-=0.12;
      pos.applyMatrix4(a.g.matrixWorld);
      var light=new T.PointLight(0xffe2b4,0,a.reach,2);
      light.position.copy(pos);light.userData.lightRole=a.role;
      light.userData.fixtureAnchor=pos.toArray();light.userData.fixtureId=a.lamp.uuid;light.userData.nightI=a.role==='porch' ? 1.0 : 0.65;
      exteriorLightRoot.add(light);exteriorLamps.push(light);
    });
    /* Dynamic and painted things keep their own draws: state repaints
       their maps, toggles their visibility, or rebuilds them wholesale. */
    var NO_MERGE = new Set([carsG, busG, mudBagsG, magnets, skyDome,
      calFace, boardFace, critFace, radioFace, paneMesh, plaque, needle,
      steam, steam2, pendants, fridgeDoorTop]);
    (pantryJars || []).forEach(function (j) { NO_MERGE.add(j); });
    /* R3: lids ride jar.visible via three's own parent-visibility cascade
       (they're children of the jar mesh, not the merge-eligible `board`
       group), but they still carry the same per-item toggle semantics the
       jars do, so they get the same explicit belt-and-suspenders entry. */
    (pantryLids || []).forEach(function (l) { NO_MERGE.add(l); });
    /* garageBackWall: exported and runtime-painted (FACE_MESH_MAP.garage
       hangs the garage's lean-in card on it), carries room 'garage' but
       no zone tag, and sits directly under extG (built via ebox(), which
       always parents into extG) — nothing structural stops it bucketing
       with the rest of the garage's same-material siding. It survives
       unmerged today only because its material bucket holds exactly 3
       members, one short of mergeStatic's 4-item floor: a data-dependent
       safety, fenced here to make it structural instead. Note the bare
       `garageBackWall` local this mesh is built under (inside the
       garage's own build IIFE) does NOT resolve at this scope — only
       its outer-scope capture, assigned there for exactly this reason,
       does. */
    NO_MERGE.add(webgl_garageBackWall);
    /* R5: the coach lamp's shade is the only mesh carrying
       userData.lamp — mergeStatic runs before the night-glow traverse
       collects that flag, so a fold here would silently delete the
       object the toggle depends on. Structural, not a count to keep
       re-verifying, same reasoning as garageBackWall just above. */
    NO_MERGE.add(webgl_coachLampGlass);
    /* SHELL (Task 4): the south wall's own second coach lamp, same
       reasoning as webgl_coachLampGlass just above — it too is the only
       mesh carrying userData.lamp within ITS OWN merge traversal
       (southWallG's dedicated per-group pass, below), so a fold there
       would delete the object the toggle depends on the same way. A
       cross-piece fold with the garage's own lamp (they share ONE cached
       material, mat(0xf7e8c2, GLOSS)) is already structurally impossible
       — southWallG is itself a registered FABRIC piece, so every
       cross-piece merge pass (extG's self-merge, the final scene-level
       pass) is fenced off from ever reaching INTO it at all, regardless
       of what materials its contents share with a different fenced
       piece. This entry is belt-and-suspenders against southWallG's OWN
       future crowd (a later task adding more props there on this exact
       finish), matching the file's own stated principle: NO_MERGE is
       what keeps the night glow honest, not an object's rarity today. */
    NO_MERGE.add(webgl_coachLampGlass2);
    exteriorGlowMeshes.forEach(function(m){NO_MERGE.add(m);});
    porchPools.forEach(function(m){NO_MERGE.add(m);});
    /* grassSlab: carries userData.yard, which inYard() reads for the
       navigation law (spec section 5, rule 5). A fold into extG's
       siding/ground material bucket would delete that flag along with
       the mesh's own identity. grassSlab is a plain buildRoom-scope
       var (declared far above, ~3943, at the function's own top
       level — not inside a nested IIFE), so it resolves here directly,
       the same as any other single-mesh anchor in this list. */
    NO_MERGE.add(grassSlab);
    /* ---- STUDY: built here, joins the scene later ----------------------
       VIEW-VOLUME MASKING (task 3): the study's footprint is one of the
       five mask boxes, and the shells are cut from the PRE-merge fabric
       (the per-fabric merge loop is just below), so the study has to be
       built before ROOM_AABB is measured here. It is NOT added to the
       scene here: scene.add stays at its original site after the merge
       passes and the AO bake (search "if (studyWorld) {"), so neither
       ever sees it -- its materials are unshared and it was never baked,
       and adding it early would have baked ~500 study meshes and changed
       the study's look. Only the factory call and the zone registration
       moved. */
    if (!exteriorOnly && window.HouseStudy) {
      /* VAULTED PARTITIONS: the study's own architecture is authored
         4.45 tall, against a house whose eave is 5.6 and whose roof
         clears 8.5 over this room's north wall -- so from the east room
         you looked straight over it, and between 4.45 and 5.6 the room
         showed the block's plaster rather than its own. Hand the adapter
         the house's OWN arithmetic rather than let it copy the numbers:
         `underside` is the deck this file builds, `eave` the line every
         exterior wall already reaches. The standalone /study page calls
         the same factory with no ceiling and keeps its authored 4.45. */
      studyWorld = window.HouseStudy.build(T, DETAIL, R, {
        eave: EXT_TOP4,
        underside: function (z) {
          return mainWingVault(EPX1_4, EWX0_4) ? vaultTop(MAIN_VAULT, z) : EXT_TOP4;
        }
      });
      Object.keys(studyWorld.zones).forEach(function (key) {
        groups[key] = studyWorld.zones[key];
      });
    }

    /* ---- SHELL (spec section 4): per-room footprints ------------------
       roomsReg()'s subject box for the room-level views: a box around
       what is actually INSIDE the room (floor, furniture, fixtures), not
       the shell that ENCLOSES it. The long derivation note (why it is
       rooted at `scene`, the two exclusions, the ROOM_CEILING line) is
       kept at its ORIGINAL site far below, beside zoneExtra; only the
       code moved. VIEW-VOLUME MASKING (task 3) hoisted it here because
       the five room masks are built from it and buildRoomShells() below
       must run before the per-fabric merge loop. Nothing between here
       and the original site adds a room-tagged mesh or moves a group
       (verified by reading: the sky dome, the ghost edges and the study
       are the only later scene additions, and the study is built above
       and measured explicitly here -- its roots are not in the scene
       yet, so they are walked by hand with their own matrices updated).
       Measured against the original site before the move: the same
       five boxes to the millimetre, except the living floor's y-min
       (-0.002 -> -0.006: a floor-level prop's box read pre-merge
       instead of through its merged composite), which nothing reads at
       that precision. */
    var ROOM_CEILING = 6.0;
    var ROOM_AABB = {};
    (function () {
      var boxes = {};
      var shellGroups = FABRIC.map(function (f) { return f.g; });
      function inShell(o) {
        for (var i = 0; i < shellGroups.length; i++)
          for (var p = o; p; p = p.parent) if (p === shellGroups[i]) return true;
        return false;
      }
      function visit(o) {
        if (!o.isMesh || o === skyDome) return;
        if (inShell(o)) return;
        var b0 = new T.Box3().setFromObject(o);
        if (b0.max.y > ROOM_CEILING) return;
        var room = null;
        for (var p = o; p && p !== scene; p = p.parent)
          if (p.userData && p.userData.room) { room = p.userData.room; break; }
        if (!room) return;
        if (!boxes[room]) boxes[room] = new T.Box3();
        boxes[room].union(b0);
      }
      scene.updateMatrixWorld(true);
      scene.traverse(visit);
      if (studyWorld) [studyWorld.group, studyWorld.architecture, studyWorld.proxies]
        .forEach(function (root) {
          if (!root) return;
          root.updateMatrixWorld(true);
          root.traverse(visit);
        });
      Object.keys(boxes).forEach(function (r) {
        var b = boxes[r];
        ROOM_AABB[r] = [b.min.x, b.max.x, b.min.y, b.max.y, b.min.z, b.max.z];
      });
    })();

    /* ---- VIEW-VOLUME MASKING (spec 2026-09-16 masking sections 2-4) ----
       One mask per room camera, applied at build time to every fabric
       mesh (pre-merge: the box()/extrude solids Task 2 stamped convex,
       never the fused composites the merge loop below makes of them):
       keep = (mesh outside the pyramid P) union (mesh inside P and inside
       the wedge W). Both pieces are disjoint by construction (the second
       is clipped to P first), so nothing is drawn twice; every cut face
       is capped in CAP_MAT, the one shared section tone.

       WHAT A ROOM SHELL HOLDS -- a deviation from the task brief's "a
       full cut copy of every fabric row per room", recorded in the task
       report: the shells hold ONLY the remnants of meshes the mask
       actually cut. Everything the mask leaves whole (the vast majority
       -- 55k fabric triangles per copy, five copies, would have cost a
       second merge pass and a second AO bake of the yard's 30k-triangle
       planting per room, against a 1500ms buildMs ceiling with ~500ms of
       headroom) stays exactly where it is, in the full shell, and is
       never copied. A mesh the mask cuts or drops in some room's view is
       stamped userData.maskPattern ('|kitchen|living|', the rooms whose
       view hides it); mergeStatic builds such a bucket's full composite
       exactly as before plus one stand-in composite per distinct
       surviving subset (userData.maskOnly), and solveShell toggles them
       (and shows the room's remnant shell) at settle. The exterior and
       every orbit stop toggle everything back on and hide every shell:
       the sealed house, the same draw list as before.

       WHO IS CUT, WHO IS WHOLE (spec section 3, controller rulings):
       - a convex mesh (userData.convex) is clipped to keep, its remnant
         (kept faces in the mesh's own material, caps in CAP_MAT) built
         as a new BufferGeometry in the room's shell;
       - a kit row (f.kit: doors, windows, porches, the garage door) is
         whole or nothing by its registered box: masked whole when the
         box centre is masked OR five or more of its eight corners are;
       - a genuinely non-convex mesh (lathe, cylinder, sphere, tube) is
         whole or nothing by its own box, the same rule;
       - an InstancedMesh (the yard's planting) is EXEMPT: never clipped,
         never toggled, never cloned -- worldTris throws on one, and no
         room camera looks through a bush at its own room;
       - a row that registers AFTER this build (house_features.js's door
         fixtures, through syncWorld) is whole or nothing by its box,
         through maskLateRow at registration.

       The occupied wedge remains floor-to-eave. The bounded camera
       volume uses the same footprint extended through the overhead roof.
       ROOM_AABB is measured from the room's props and
       floor (never its enclosure), so its top is wherever the tallest
       prop stops (living 1.99, kitchen 3.3) -- min(top, eave) would
       read those and cut the roof only where a ray reaches a sofa; the
       spec's "footprint x floor-to-eave" is the walled volume, so the
       top is SET to the eave. Its footprint, for the same reason, runs
       INTO the enclosure it stands against (a floor slab under its
       wall; the study floor 0.25 into the street wall; the roof deck's
       overhang dips 0.19 below the eave line), and a front-face plane
       taken raw would keep the inner sliver of the very wall the mask
       exists to remove -- an opaque 2cm slab hides a room exactly as
       well as a whole wall. So a mesh that STRADDLES a front face
       (pokes into the box by at most STRADDLE_TOL, one wall thickness
       plus the deepest interior casing) is judged against that plane
       moved to its own deepest point (meshMask): the whole mesh counts
       as "in front", and its cut is P alone, on the room's silhouette.
       A mesh that runs deeper than that is the enclosure of the far
       side or a wall perpendicular to the face (the kitchen's north
       wall, the garage's back wall reaching past the bay) and keeps the
       raw plane -- a global inset was tried first and notched a 0.45
       band off every such wall (recorded in the report). P is never
       moved, so the cut edge still projects onto the room's own
       silhouette. */
    /* CAP_MAT is declared with shellRegister (the valley clip uses it
       at facade-build time, long before this runs) */
    var STRADDLE_TOL = WALL_T4 + 0.25;
    /* task 8: the SHED joins the list, and a gabled porch's own roof --
       which is the same deck the free gable used to build, under the
       porch's name now (facade_<face>_porch_<slot>_roof_*) -- keeps the
       ruling it had under the old one. */
    var ROOF_FEATURE = /^facade_.*_(gable|dormer|hip_end|shed)_\d+|^facade_.*_porch_\d+_roof/;   /* ruling 1 */
    var ROOF_FEATURE_MIN_KEPT = 0.2;
    var ROOM_CAMS = { kitchen: HOME_POS, living: LIV_POS, study: STUDY_POS,
                      garage: GARAGE_POS, mudroom: MUD_POS };
    /* MASSING ARC 2 task 7: the look-at target that goes with each of
       those cameras -- the same pairs enterRoom() tweens to. The mask
       reads only the camera (the pyramid's apex); window.chfRoomViewClear
       reads both, because the pin it serves is a RAY from the camera to
       what the room view is actually pointed at. */
    var ROOM_AT = { kitchen: HOME_AT, living: LIV_AT, study: STUDY_AT,
                    garage: GARAGE_AT, mudroom: MUD_AT };
    var ROOM_MASKS = {};        /* room -> {P, W, box, cam} */
    var roomShellGroups = {};   /* room -> THREE.Group 'shell:<room>' */
    var MASK_TOGGLES = [];      /* every object solveShell toggles by pattern */
    function ROOM_AABB_EAVE(room) {
      var b = ROOM_AABB[room].slice();
      b[3] = EXT_TOP4;          /* eave-high (spec section 2 choice A) */
      return b;
    }
    function roomMask(room) {
      var occupied = ROOM_AABB_EAVE(room), box = occupied.slice();
      FABRIC.forEach(function(f) {
        var b = f.box;
        if (f.g !== yardG && boxOk(b) && b[1] >= box[0] && b[0] <= box[1] &&
            b[5] >= box[4] && b[4] <= box[5]) box[3] = Math.max(box[3], b[3] + 0.01);
      });
      var cam = ROOM_CAMS[room].toArray();
      var m = window.HouseClip.maskPlanes(cam, box);
      // Keep the ground-floor interior; the bounded volume removes the
      // overhead shell, including upper stories, without extending past it.
      m.W = window.HouseClip.maskPlanes(cam, occupied).W;
      m.box = box; m.cam = cam;
      return m;
    }
    /* the room mask as ONE mesh (box b) sees it: every W plane the mesh
       straddles by no more than STRADDLE_TOL is moved to the mesh's own
       deepest point (kept side is n.p - d >= 0, so a larger d shrinks
       the kept half-space, i.e. moves the plane INTO the box); P and
       every other W plane are shared with the room mask untouched */
    function meshMask(m, b) {
      var cs = boxCorners(b);
      return { P: m.P, box: m.box, cam: m.cam, W: m.W.map(function (pl) {
        var pen = -Infinity;
        for (var k = 0; k < 8; k++) {
          var sd = pl.n[0]*cs[k][0] + pl.n[1]*cs[k][1] + pl.n[2]*cs[k][2] - pl.d;
          if (sd > pen) pen = sd;
        }
        // Include exact contact: an upper wall's bottom face on the eave
        // otherwise survives as a zero-thickness strip across the view.
        if (pen >= -1e-6 && pen <= STRADDLE_TOL) return { n: pl.n, d: pl.d + Math.max(0, pen) + 1e-4 };
        return pl;
      }) };
    }
    function keepTris(tris, m) {
      var C = window.HouseClip;
      var outside = C.subtractTris(tris, m.P, 1);
      var inside = m.P.reduce(function (t, pl) { return C.clipTris(t, pl, 1); }, tris);
      var kept = m.W.reduce(function (t, pl) { return C.clipTris(t, pl, 1); }, inside);
      return outside.concat(kept);
    }
    function trisToMesh(tris, slot, material, like, room) {
      var sel = tris.filter(function (t) { return t.slot === slot; });
      if (!sel.length) return null;
      var pos = new Float32Array(sel.length * 9), uv = new Float32Array(sel.length * 6);
      sel.forEach(function (t, i) {
        [t.a, t.b, t.c].forEach(function (v, k) {
          pos.set(v.p, i * 9 + k * 3); uv.set(v.uv, i * 6 + k * 2);
        });
      });
      var g = new T.BufferGeometry();
      g.setAttribute('position', new T.BufferAttribute(pos, 3));
      g.setAttribute('uv', new T.BufferAttribute(uv, 2));
      g.computeVertexNormals();
      g.userData.cached = true;   /* lifecycle law: never disposed by a rebuild path */
      var mesh = new T.Mesh(g, material);
      /* the source mesh's own tags travel (glazing/shellWindow/lamp keep
         the night loops honest for the remnant, entry keeps the probe
         box); the room is the RESOLVED one (ancestor walk), so the
         merge bucket and onTap read the remnant exactly as the source */
      mesh.userData = Object.assign({}, like.userData, { convex: false, remnant: true });
      delete mesh.userData.maskPattern;
      if (room) mesh.userData.room = room;
      mesh.castShadow = like.castShadow; mesh.receiveShadow = like.receiveShadow;
      mesh.renderOrder = like.renderOrder; mesh.visible = like.visible;
      return mesh;
    }
    function boxCorners(b) {
      var out = [];
      for (var i = 0; i < 8; i++) out.push([(i & 1) ? b[1] : b[0], (i & 2) ? b[3] : b[2], (i & 4) ? b[5] : b[4]]);
      return out;
    }
    function boxCentre3(b) { return [(b[0]+b[1])/2, (b[2]+b[3])/2, (b[4]+b[5])/2]; }
    /* Classifies a world AABB against a mask without clipping anything:
       'out'   every corner beyond one P plane -> the box misses the
               pyramid, kept whole;
       'keep'  every corner behind every W plane -> inside the wedge,
               kept whole (whatever P says);
       'drop'  every corner inside every P plane AND every corner in
               front of one W plane -> the whole box is masked;
       'mixed' anything else -> only a real clip can decide. */
    function boxClass(b, m) {
      var cs = boxCorners(b), i, k, all;
      function sideOf(pl, p) { return pl.n[0]*p[0] + pl.n[1]*p[1] + pl.n[2]*p[2] - pl.d; }
      for (i = 0; i < m.P.length; i++) {
        all = true;
        for (k = 0; k < 8 && all; k++) if (sideOf(m.P[i], cs[k]) >= -1e-7) all = false;
        if (all) return 'out';
      }
      all = true;
      for (i = 0; i < m.W.length && all; i++)
        for (k = 0; k < 8 && all; k++) if (sideOf(m.W[i], cs[k]) < -1e-7) all = false;
      if (all) return 'keep';
      var inP = true;
      for (i = 0; i < m.P.length && inP; i++)
        for (k = 0; k < 8 && inP; k++) if (sideOf(m.P[i], cs[k]) < -1e-7) inP = false;
      if (inP) for (i = 0; i < m.W.length; i++) {
        all = true;
        for (k = 0; k < 8 && all; k++) if (sideOf(m.W[i], cs[k]) >= -1e-7) all = false;
        if (all) return 'drop';
      }
      return 'mixed';
    }
    /* whole-or-nothing rule for kits and non-convex meshes (spec
       section 3): masked whole when the box centre is masked or five
       or more of the eight corners are */
    function boxMasked(b, m) {
      var C = window.HouseClip;
      if (C.pointMasked(boxCentre3(b), m)) return true;
      return boxCorners(b).filter(function (p) { return C.pointMasked(p, m); }).length >= 5;
    }
    function stampPattern(o, room) {
      o.userData.maskPattern = (o.userData.maskPattern || '|') + room + '|';
    }
    function roomOfMesh(mm, top) {
      for (var p = mm; p; p = p.parent) {
        if (p.userData && p.userData.room) return p.userData.room;
        if (p === top) break;
      }
      return null;
    }
    function buildRoomShells() {
      var C = window.HouseClip, t0 = performance.now();
      var stats = { rooms: 0, clipped: 0, dropped: 0, kitsDropped: 0, featuresDropped: 0,
                    remnantTris: 0, ms: 0 };
      Object.keys(ROOM_CAMS).forEach(function (room) {
        if (!ROOM_AABB[room]) return;
        ROOM_MASKS[room] = roomMask(room);
      });
      /* every fabric mesh once: world box and world triangles (area0).
         The yard (f.g === yardG) is skipped here -- ruling 3 below hides
         it whole in every room view without ever reading row.meshes or
         row.area0, so world-triing its (non-instanced) props was pure
         build-time waste, never a correctness bug. */
      var rows = FABRIC.map(function (f) {
        f.shells = {}; f.verdict = 'solid';
        if (f.g === yardG) return { f: f, meshes: [], area0: 0 };
        var meshes = [], area0 = 0;
        f.g.updateMatrixWorld(true);
        f.g.traverse(function (mm) {
          if (!mm.isMesh || mm.isInstancedMesh) return;   /* InstancedMesh: exempt */
          var b = new T.Box3().setFromObject(mm);
          var tris = worldTris(mm), area = C.triArea(tris);
          area0 += area;
          meshes.push({ m: mm, tris: tris, area: area,
                        box: [b.min.x, b.max.x, b.min.y, b.max.y, b.min.z, b.max.z] });
        });
        return { f: f, meshes: meshes, area0: area0 };
      });
      Object.keys(ROOM_MASKS).forEach(function (room) {
        var m = ROOM_MASKS[room];
        var group = new T.Group(); group.name = 'shell:' + room; group.visible = false;
        roomShellGroups[room] = group;
        stats.rooms++;
        rows.forEach(function (row) {
          var f = row.f, area1 = 0, mirror = {};
          if (f.kit) {
            var gone = boxOk(f.box) && boxMasked(f.box, meshMask(m, f.box));
            if (gone) { stampPattern(f.g, room); stats.kitsDropped++; }
            f.shells[room] = { group: null, fraction: gone ? 1 : 0 };
            return;
          }
          /* RULING 3 (fix round 1): the yard -- the one registered row
             whose mode is 'hide', yardG whole -- hides in every room view
             and shows at the exterior and the orbit, exactly as the old
             verdict did. Its instanced planting is exempt from the mask
             and was drawing in every room view where it never had (the
             kitchen's triangles doubled); the same toggle mechanism as a
             dropped kit, fraction 1 in every room, no remnants. */
          if (f.g === yardG) {
            stampPattern(f.g, room);
            f.shells[room] = { group: null, fraction: 1 };
            return;
          }
          /* the mirrored ancestor chain: every group between f.g and a
             cut mesh is re-created (at identity -- remnants are world-
             space) with the same userData, so the merge bucket (L4: a
             zone subtree never merges), onTap's room walk, inertFabric,
             inYard and the batching invariant's material-per-zone rule
             read a remnant exactly as they read its source. The one
             zone that lives inside a fabric group (the wall calendar,
             on west_wall) keeps its zone tag on the mirrored chain too:
             zoneAt walks hits with no visibility check either way, and
             the remnant occupies the same space as its pattern-hidden
             source, so it adds no answer the source did not already
             give. */
          function mirrorOf(g) {
            if (mirror[g.id]) return mirror[g.id];
            var mg = new T.Group();
            mg.name = 'shell:' + room + ':' + (g === f.g ? f.name : (g.name || g.id));
            mg.userData = Object.assign({}, g.userData);
            delete mg.userData.maskPattern; delete mg.userData.convex;
            mg.matrixAutoUpdate = false;
            if (g === f.g) {
              mg.userData.shellOf = f.name;
              /* g === yardG never reaches here: the yard row returns
                 whole (stampPattern + fraction 1) before cutRow/mirrorOf
                 ever runs, so f.g is never yardG inside this closure. */
              group.add(mg);
            } else mirrorOf(g.parent).add(mg);
            mirror[g.id] = mg;
            return mg;
          }
          /* one pass over the row's meshes: `commit` false only measures
             (area1), true also stamps the patterns and builds remnants */
          function cutRow(commit) {
            area1 = 0;
            row.meshes.forEach(function (e) {
              var mm = meshMask(m, e.box), cls = boxClass(e.box, mm);
              if (cls === 'out' || cls === 'keep') { area1 += e.area; return; }
              if (!e.m.userData.convex) {
                if (cls === 'drop' || boxMasked(e.box, mm)) {
                  if (commit) { stampPattern(e.m, room); stats.dropped++; }
                } else area1 += e.area;
                return;
              }
              if (cls === 'drop') { if (commit) { stampPattern(e.m, room); stats.dropped++; } return; }
              var kept = keepTris(e.tris, mm);
              var a1 = C.triArea(kept, 0);
              /* untouched when the clip took nothing, or next to nothing:
                 a sliver under 0.1% of the mesh's own area (a gable end's
                 far tip grazing a pyramid plane) is a hairline either way
                 and is not worth a remnant, a toggle and a 'masked'
                 verdict for a piece that is whole to the eye */
              if (a1 >= e.area * (1 - 1e-3)) { area1 += e.area; return; }
              area1 += a1;
              if (!commit) return;
              stampPattern(e.m, room);
              if (a1 <= 1e-9) { stats.dropped++; return; }
              stats.clipped++; stats.remnantTris += kept.length;
              /* a row registered as a bare mesh (north_wall) IS its own
                 f.g; its remnant hangs off the mirrored row group directly */
              var parent = mirrorOf(e.m === f.g ? f.g : e.m.parent), rm = roomOfMesh(e.m, f.g);
              var ka = trisToMesh(kept, 0, e.m.material, e.m, rm);
              var kb = trisToMesh(kept, 1, CAP_MAT, e.m, rm);
              if (ka) parent.add(ka);
              if (kb) parent.add(kb);
            });
          }
          /* RULING 1 (fix round 1): a facade ROOF FEATURE row -- every
             piece gableAt/dormerAt/hipEndAt register (facade_*_gable_*,
             facade_*_dormer_*, facade_*_hip_end_*) -- is dropped WHOLE
             when the mask would keep less than a fifth of it, and
             clipped normally otherwise. The living view left the porch
             gable's two decks as floating shards outside the pyramid
             (0.86 cut); the kitchen keeps its clipped quarter. Not the
             kit rule: a kit judged by its box would keep a quarter-deck
             standing in the kitchen's cone. Measured first (no stamps,
             no remnants), then committed one way or the other. */
          if (ROOF_FEATURE.test(f.name)) {
            cutRow(false);
            if (row.area0 && area1 < row.area0 * ROOF_FEATURE_MIN_KEPT) {
              stampPattern(f.g, room); stats.featuresDropped++;
              f.shells[room] = { group: null, fraction: 1 };
              return;
            }
          }
          cutRow(true);
          var fr = row.area0 ? Math.max(0, Math.min(1, 1 - area1 / row.area0)) : 0;
          if (fr < 1e-6) fr = 0;   /* the two sums differ by an ulp when nothing was cut */
          f.shells[room] = { group: mirror[f.g.id] || null, fraction: fr };
        });
        scene.add(group);
        group.updateMatrixWorld(true);
        /* the same per-group merge every fabric row gets (batching
           contract unchanged), run per MIRRORED ROW so a merged remnant
           composite lands under its row group and keeps the shellOf
           ancestry chfNavProbe({piece}) and chfRoomShellVerts read (a
           shell-wide pass parked every composite at the shell root and
           lost the row -- fix round 1); BEFORE the group is fenced: the
           fence below keeps the exterior/scene passes from ever folding
           a shell's remnants across rows or into anything else */
        group.children.slice().forEach(function (rowG) { mergeStatic(rowG, NO_MERGE); });
        NO_MERGE.add(group);
      });
      stats.ms = Math.round(performance.now() - t0);
      scene.userData.shellStats = stats;   /* --budget-reachable via __hpScene */
    }
    /* a row registered after buildRoomShells ran (house_features.js's
       door fixtures, via syncWorld -> webgl.registerFabric): whole or
       nothing per room by its registered box, the kit rule -- there is
       nothing pre-merge left to clip by then, and every such row today
       IS a kit */
    function maskLateRow(f) {
      f.shells = {}; f.verdict = 'solid';
      Object.keys(ROOM_MASKS).forEach(function (room) {
        var gone = boxOk(f.box) && boxMasked(f.box, meshMask(ROOM_MASKS[room], f.box));
        if (gone) stampPattern(f.g, room);
        f.shells[room] = { group: null, fraction: gone ? 1 : 0 };
      });
      if (f.g.userData.maskPattern && MASK_TOGGLES.indexOf(f.g) < 0) MASK_TOGGLES.push(f.g);
    }
    if (!exteriorOnly) buildRoomShells();

    /* Each registered piece owns one merge pass. No roof can be omitted
       from batching when the envelope grows. Groups are sibling merge
       boundaries; the registry also fences the later exterior pass.
       VIEW-VOLUME MASKING (task 2, corrected): every row's `convexity`
       was already scanned at registration time (regFabric/refabConvexity,
       above) -- before ITS OWN merge, not this bulk loop's -- so mergeStatic
       fusing same-material meshes into composites below never touches
       what chfFabricConvexity()/Task 3 read. See scanConvexity's comment
       for why a snapshot taken here (or after) would be too late for
       house_features.js's fixtures, which register even later still. */
    FABRIC.forEach(function (f) { mergeStatic(f.g, NO_MERGE); });
    /* VIEW-VOLUME MASKING (task 3): the toggle list is collected AFTER
       the merge, because that is when the patterned meshes take their
       final form -- a merged composite carries the union of its members'
       patterns and its per-room stand-ins carry maskOnly (mergeStatic,
       above), an unmerged survivor keeps its own pattern, and a
       whole-or-nothing kit carries it on the row group itself. */
    FABRIC.forEach(function (f) {
      /* the row group itself (a kit, the yard, or a roof feature dropped
         whole in some views) AND its members: a roof feature dropped
         whole in the living view is still clipped mesh by mesh in the
         kitchen's, so both levels toggle (fix round 1: an early return
         here left the porch deck's source mesh standing in the kitchen
         cone, in front of the packing bags) */
      if (f.g.userData.maskPattern) MASK_TOGGLES.push(f.g);
      f.g.traverse(function (o) {
        if (o !== f.g && o.userData && (o.userData.maskPattern || o.userData.maskOnly))
          MASK_TOGGLES.push(o);
      });
    });
    var EXT_NO_MERGE = new Set(NO_MERGE);
    if(neighborhoodEnabled)EXT_NO_MERGE.add(parcelRoad);
    /* SHELL (shell spec section 3): the registry feeds both fence sets
       so shell membership is declared exactly once, replacing the four
       hand adds this loop used to be. EFFECTIVE membership is unchanged:
       yardG, garageDoorG and mudroomRoofG land in
       EXT_NO_MERGE exactly as the hand adds did (fencing them out of
       extG's own self-merge pass, two comments above). westWallG's new
       presence in EXT_NO_MERGE is inert — scene.add(westWallG), never
       extG.add (see the westWallG note above), puts it outside extG's
       own subtree, so extG.traverse() never visits it and this
       membership is never tested. NO_MERGE also gains all five, which
       is forward-looking only: the one other place NO_MERGE is read
       (TOP, below) already hand-lists the same five groups, so this
       cannot change TOP's membership either, and the per-group merge
       passes above already ran against NO_MERGE before this line ever
       executes, so they cannot be retroactively affected. */
    FABRIC.forEach(function (f) { EXT_NO_MERGE.add(f.g); NO_MERGE.add(f.g); });
    mergeStatic(extG, EXT_NO_MERGE);
    /* Scene-level pass last: every hide-group (now including extG
       itself, whose loose fabric just became one boundary) is a
       reparenting boundary, so an untagged exterior static (street,
       driveway) can never escape extG into a scene-level mesh — that
       would defeat onTap's !inExterior(hit) fallback (a street tap
       would open the kitchen). */
    var TOP = new Set(NO_MERGE);
    [westWallG, garageDoorG, mudroomRoofG, yardG, extG]
      .forEach(function (g) { TOP.add(g); });
    mergeStatic(scene, TOP);

    /* ---- SHELL (spec section 3): build the ghosts, once -----------------
       AFTER every merge pass above, so each fabric group traverses to only
       a handful of meshes (mergeStatic's own output) instead of the dozens
       it started with. The yard is skipped outright -- outlined scenery
       is still noise, section 3's own words -- and a
       piece whose traversal turns up zero meshes (none today; living_roof
       was the one, deleted with the massing arc -- see boxOk's comment
       above) gets no edges object at all rather than
       an empty one added for nothing: f.edges is left null for it, the
       same as a piece that was never registered.

       ONE LineSegments per piece, not one per surviving mesh (a first
       draft, tried and rejected -- see the report): mergeStatic's 4-item
       merge floor plus its L1/L4 exemptions (an unshared material never
       merges; a zone subtree never merges) leave far more survivors
       standing per fabric group than "a handful" -- measured at 100 for
       west_wall alone (its picture frames, sconce and wall calendar all
       carry their own unshared or zone-exempt materials), 12 for
       garage_door, 2 for mudroom_roof. One EdgesGeometry+LineSegments per
       survivor would cost that many draws per ghosted piece, dead against
       section 7's "ghosts add at most one draw per ghosted piece" and
       section 3's "ONE prebuilt ghost... as LineSegments" (singular).
       So every survivor's EdgesGeometry is computed same as before, but
       only to steal its (already local-space) vertex positions into one
       shared `pos` array -- world-matrix transformed first so a mesh
       three levels deep and a merged mesh sitting at the root both land
       in the same combined array correctly -- and exactly one combined
       BufferGeometry/LineSegments is built from that array per piece.
       EdgesGeometry itself sets nothing but a bare, non-indexed `position`
       attribute (verified by reading the vendored bundle's class body:
       one this.setAttribute("position", ...) call, no index, no normal,
       no uv), which is also all LineBasicMaterial ever reads off a
       LineSegments -- so this loses nothing an unbatched version had.

       Per-mesh transform: NOT a bare copy of o.position/o.rotation/
       o.scale (also tried, also rejected). Two different shapes of
       survivor reach this traversal, and only a world-matrix route gets
       both right with the same code. (1) mergeStatic's own merged mesh
       (mergeGeoms, above): every source vertex is baked into the MERGE
       ROOT's own space, and the merged Mesh's position/rotation/scale
       are never set afterward, so it carries an IDENTITY local transform
       -- and every root this loop traverses (westWallG, mudroomRoofG,
       garageDoorG -- verified by grep: none of the three is ever given a
       .position or .rotation of its own) also sits at identity relative
       to ITS OWN parent, so for a merged survivor, local-to-root and
       local-to-root's-parent are the same numbers regardless of method.
       (2) mergeStatic exempts an entire zone subtree from merging (L4,
       the batching spec), and westWallG carries one such survivor group:
       calG, the wall calendar, reparented in with its own real translate
       PLUS a 90-degree yaw (`calG.rotation.y = Math.PI / 2`, its own
       build site), holding un-merged mesh children two levels below
       westWallG. Their OWN .position/.rotation are relative to calG, not
       to westWallG -- a bare copy would silently drop calG's translate
       and rotate and draw those edges in the wrong place, facing the
       wrong way. A world-matrix transform relative to f.g.parent (the
       combined LineSegments' own new parent, a few lines down) is
       correct for both shapes at once. scene.updateMatrixWorld(true)
       first, once, because the merge passes above added brand-new
       meshes (mergeStatic's `mm`) whose matrixWorld has never been
       computed at all -- Object3D leaves it at its constructor default
       until something asks. */
    scene.updateMatrixWorld(true);
    FABRIC.forEach(function (f) {
      if (f.g === yardG || !f.g.parent) return;    /* the yard; a stray
        future registration with no parent yet -- fail safe, not crash */
      var toParent = new T.Matrix4().copy(f.g.parent.matrixWorld).invert();
      var m4 = new T.Matrix4(), v3 = new T.Vector3();
      var pos = [];
      f.g.traverse(function (o) {
        if (!o.isMesh || !o.geometry) return;
        /* VIEW-VOLUME MASKING (task 3): a per-room stand-in composite
           (mergeStatic's maskOnly) duplicates edges the full composite
           already contributes -- skip it, or the (dormant) ghost carries
           every masked bucket's outline up to six times over */
        if (o.userData && o.userData.maskOnly) return;
        var eg = new T.EdgesGeometry(o.geometry, 35);
        var p = eg.attributes.position;
        m4.multiplyMatrices(toParent, o.matrixWorld);
        for (var i = 0; i < p.count; i++) {
          v3.fromBufferAttribute(p, i).applyMatrix4(m4);
          pos.push(v3.x, v3.y, v3.z);
        }
        eg.dispose();     /* scratch only -- its data is now baked into
                              `pos`; nothing else ever references it */
      });
      if (!pos.length) return;
      var geo = new T.BufferGeometry();
      geo.setAttribute('position', new T.Float32BufferAttribute(pos, 3));
      var ls = new T.LineSegments(geo, GHOST_MAT);
      ls.userData.shellGhost = true;
      /* Tap law (spec section 5): "ghost lines carry no tags... no
         special casing" only holds if a tap can never actually LAND on
         one. Three's own raycaster does not consult .visible at all
         (Raycaster.intersectObject calls object.raycast() unconditionally
         once layers match -- verified against this file's own vendored
         bundle), and its default Line hit-test radius is a full 1 world
         unit -- generous enough, next to a wall's own trim and seams,
         that an untagged edge-line hit could easily reach onTap's
         exterior-mode path BEFORE the real tagged fill mesh occupying
         the same location ever does, and that path trusts hits[0]
         outright with no fallback scan (unlike zoneAt's loop, which
         already tolerates an unrelated hit ahead of the one it wants).
         A no-op raycast makes every ghost line permanently invisible to
         EVERY caster, in every mode, independent of ls.visible -- the
         one change that makes the spec's "no special casing" claim true
         by construction instead of true by coincidence of which piece's
         parent happens to sit inside extG. */
      ls.raycast = function () {};
      /* A SIBLING of f.g (f.g.parent.add), never a CHILD of it: three's
         own render-list walk (WebGLRenderer's projectObject) returns the
         instant an object's .visible is false, before it ever looks at
         that object's children -- so a LineSegments parented INSIDE an
         f.g the solver just hid could never draw no matter what its OWN
         .visible said. Sibling placement is what makes ls's visibility
         independent of the fill's, which is the entire trick the verdict
         application above depends on. */
      ls.visible = false; ls.renderOrder = 5;
      f.g.parent.add(ls); f.edges = ls;
    });

    /* ---- K4 (quality spec §3): the AO occluder list ---------------------
       ~30 world-space AABBs for the scene's big masses, read off each
       builder's own authored literals (box/ebox/cyl args, kCase runs,
       zoneGroup origins). Every group these live in — westWallG, extG,
       garageInterior, the kCase groups, the zoneGroups — sits at either
       an identity transform or a literal position.set() with no
       rotation (except the two kCase runs noted below, whose rotation is
       folded into the box already), so the builders' own numbers ARE
       world coordinates. Row shape: [x0,x1,y0,y1,z0,z1]; a march sample
       point inside ANY row counts as occluded. */
    var AO_OCCLUDERS = [
      [-6.8, 6.8, -0.52, -0.02, -5.8, 5.8],        /* kitchen floor slab */
      [-6.8, 6.8, -0.52, -0.02, 5.7, 14.1],        /* great-room floor slab */
      [-6.5, 6.5, 0.0, 5.6, -5.725, -5.375],       /* wallB: kitchen's north wall */
      [-6.825, -6.475, 0.0, 5.6, -5.5, -1.45],     /* westWallG: wallL */
      [-6.825, -6.475, 0.0, 5.6, 0.25, 2.8],       /* westWallG: wallL1a */
      [-6.825, -6.475, 3.2, 5.6, -1.45, 0.25],     /* westWallG: mudroom doorway header */
      [-6.825, -6.475, 0.0, 5.6, 4.4, 5.5],        /* westWallG: wallL1b */
      [-6.825, -6.475, 3.4, 5.6, 2.8, 4.4],        /* westWallG: second doorway header */
      [-6.825, -6.475, 0.0, 5.6, 5.8, 14.2],       /* westWallG: wallL2, the great room */
      [6.8, 6.85, -0.52, -0.02, -5.82, 14.1],      /* the great-room east line: the slab's
                                                       cut face — the open-corner diorama
                                                       has no full wall here, this band is it */
      [-2.27, 1.47, 0.0, 1.13, -0.27, 2.07],       /* the island */
      [-4.5, 0.85, 0.0, 1.04, -5.375, -3.935],     /* kitchen counter run A (sink run) */
      [2.55, 4.85, 0.0, 1.04, -5.375, -3.935],     /* kitchen counter run B (east of the range) */
      [-6.65, -5.9, 0.0, 1.04, -2.85, -1.55],      /* kitchen L-return counter (rotated kCase,
                                                       W/D already resolved into world x/z) */
      [-4.5, -3.0, 2.52, 4.35, -5.375, -4.875],    /* kitchen uppers: left open bays */
      [-0.78, 0.80, 2.52, 4.35, -5.375, -4.635],   /* kitchen uppers: closed run over the sink */
      [2.78, 4.78, 2.52, 4.35, -5.375, -4.875],    /* kitchen uppers: right open bays */
      [4.9, 6.4, 0.0, 4.35, -5.375, -4.575],       /* the larder — full-height hutch, east end */
      [-6.5, -4.6, 0.0, 3.95, -5.1, -3.6],         /* the fridge */
      [0.95, 2.45, 0.06, 1.08, -5.275, -3.825],    /* the range body */
      [-6.475, -6.015, 0.0, 2.95, 6.17, 7.42],     /* hearth built-in, west bay */
      [-6.475, -6.015, 0.0, 2.95, 9.78, 11.03],    /* hearth built-in, east bay */
      [-6.475, -5.575, 0.0, 3.6, 7.24, 9.96],      /* the hearth mass (stone breast + firebox) */
      [-12.40, -10.50, 0.0, 0.52, 2.77, 3.39],     /* the mudroom bench */
      [-12.6, -7.0, 0.0, 4.2, 2.36, 2.60],         /* mudroom north wall, toward the kitchen */
      [-12.6, -7.0, 0.0, 4.2, 8.20, 8.44],         /* mudroom south wall (the hidden "garage door" side) */
      [-17.96, -12.84, 0.0, 4.7, 2.24, 2.42],      /* garage back wall */
      [-17.96, -17.78, 0.0, 4.7, 2.24, 9.76],      /* garage west wall */
      [-13.02, -12.84, 0.0, 4.7, 2.24, 9.76],      /* garage east wall, edge-on */
      [-17.65, -15.75, 0.0, 1.9, 3.6, 7.6],        /* parked-car envelope, west bay — static,
                                                       whichever car model is parked there */
      [-15.05, -13.15, 0.0, 1.9, 3.6, 7.6],        /* parked-car envelope, east bay */
      [-8.75, -6.85, -0.52, 3.57, -1.9, 0.7],      /* the pantry closet shell */
      [-24.5, 25.5, -0.69, -0.29, -18, 26]         /* exterior grade (the yard's grass slab) */
    ];

    /* SHELL/arc 4 (facade spec §6): these three pieces keep their hand
       rows above rather than deriving from fabBox() -- west_wall and
       garage_shell each carve real door openings (west_wall's two
       doorways, garage_shell's garage door) out of their own mass, and
       one AABB cannot represent an L-shaped cutout: a derived box would
       claim occlusion straight through the opening, darkening the
       walk-through threshold. north_wall's hand row already equals its
       own box (no opening to lose), so excluding it changes nothing —
       it is named here anyway so the exclusion list matches the file's
       actual hand-carved masses, not just the ones that would visibly
       break. A generated facade wall has no cut openings (this file has
       no CSG), so it never needs to join this set. */
    var AO_HAND_CARVED = new Set(['west_wall', 'garage_shell', 'north_wall']);
    /* SHELL/arc 4 (facade spec §6): wall-like fabric occludes by its own
       registered box, so a generated wall needs no hand row. Sloped
       pieces (roof decks, |n.y| >= 0.5) still skip: no honest AABB. */
    FABRIC.forEach(function (f) {
      if (AO_HAND_CARVED.has(f.name)) return;
      if (Math.abs(f.n.y) >= 0.5 || !boxOk(f.box)) return;
      AO_OCCLUDERS.push(f.box.slice());
    });

    /* ---- K4 (quality spec §3): vertex AO, baked once ------------------
       10 hemisphere directions per vertex, marched against authored
       AABBs. Runs after the merge so merged fabric bakes on its final
       vertices; before applyScenery so the knob classifies materials
       that already wear their vertexColors flag. Materials flip
       vertexColors ONLY when every wearer got an attribute — a shared
       material with one bare wearer renders that wearer black. */
    function bakeAO() {
      if (DETAIL < 2) return { meshes: 0, clones: 0, fallback: false, ms: 0 };
      var t0 = performance.now();
      /* buildMs ceiling (spec §3 K4 verify step): the first pass at 10
         dirs x 5 steps measured ~1.16s of bake time alone, pushing
         buildMs past the 1500ms ceiling — halved per the brief's
         prescribed remediation before anything else was tried. */
      var DIRS = [], i;
      for (i = 0; i < 6; i++) {
        var az = (i + 0.5) / 6, th = Math.acos(1 - az * 0.92),
            ph = i * 2.39996;
        DIRS.push([Math.sin(th) * Math.cos(ph), Math.cos(th),
                   Math.sin(th) * Math.sin(ph)]);
      }
      var STEPS = [0.05, 0.15, 0.35, 0.70];
      var STR = 0.62;                       /* max darkening at a corner */
      var MAX_STEP = STEPS[STEPS.length - 1];  /* longest march a sample
         point can travel from a vertex, so a per-mesh occluder pre-cull
         (below) only has to expand that mesh's own AABB by this much to
         stay bit-identical to marching against the full AO_OCCLUDERS list */
      var meshBox = new T.Box3();
      var tmp = new T.Vector3(), nrm = new T.Vector3();
      var up = new T.Vector3(), tx = new T.Vector3(), tz = new T.Vector3();
      var nm = new T.Matrix3();
      var perMat = {};                       /* uuid -> {mat, wearers, baked} */
      var count = 0, clones = 0;
      scene.updateMatrixWorld(true);

      /* ---- shared-geometry guard (spec §3 K4 caveat) ---------------------
         cgeo geometries are SHARED: two meshes with identical dimensions
         wear the SAME BufferGeometry. Writing a colour attribute for
         mesh A and then mesh B leaves EVERY wearer showing B's occlusion
         (computed from B's own transform), not its own. Counted in its
         OWN full-scene pass, unfiltered by bake-eligibility (fix round 1,
         CRITICAL-1b: a transparent/instanced/array-material wearer still
         holds a real reference to the geometry, so it still has to count
         toward "is this shared", even though it never gets baked — the
         eligibility filters below decide who gets WRITTEN, never who
         gets COUNTED). */
      var geoWearers = {}, allGeo = {};
      scene.traverse(function (o) {
        if (!o.isMesh || !o.geometry) return;   /* isInstancedMesh IS isMesh */
        allGeo[o.geometry.uuid] = true;
        geoWearers[o.geometry.uuid] = (geoWearers[o.geometry.uuid] || 0) + 1;
      });

      /* ---- instanced-material guard (fix round 1, CRITICAL-1) -----------
         instanceYard() (batching spec B2) folds repeated yard props into
         InstancedMesh batches that keep wearing the SOURCE mesh's shared
         material, then removes every source mesh from the scene. An
         InstancedMesh never gets a colour attribute of its own (the bake
         skips InstancedMesh by design — SDD ledger ruling, exterior
         grounding stays with cast shadows/contact discs) and three.js's
         disabled-attribute default is (0,0,0,1), so if its material ever
         flips vertexColors the whole batch renders SOLID BLACK. A regular
         mesh elsewhere in the house can easily share that same cached
         material (same colour+opts key) and bake cleanly — that clean
         bake was enough to flip the shared material, with nothing
         tracking the InstancedMesh wearer to veto it. Fix: every
         InstancedMesh still registers itself against its material, so
         the bucket exists and carries `instanced: true`, but it never
         joins `w` — it is never baked, only ever a reason NOT to flip. */
      scene.traverse(function (o) {
        if (!o.isMesh || !o.material) return;
        if (Array.isArray(o.material)) return;
        if (!o.material.isMeshStandardMaterial &&
            !o.material.isMeshLambertMaterial &&
            !o.material.isMeshPhysicalMaterial) return;
        if (o.material.transparent) return;  /* glass keeps its clarity */
        if (o.isInstancedMesh) {
          var e0 = perMat[o.material.uuid] ||
                   (perMat[o.material.uuid] = { m: o.material, w: [] });
          e0.instanced = true;
          return;
        }
        var e = perMat[o.material.uuid] ||
                (perMat[o.material.uuid] = { m: o.material, w: [] });
        e.w.push(o);
      });
      var preGeo = Object.keys(allGeo).length, projected = 0;
      Object.keys(geoWearers).forEach(function (gu) {
        if (geoWearers[gu] > 1) projected += geoWearers[gu] - 1;
      });
      /* budget guard: cloning trades geometry sharing for per-mesh AO. If
         minting every multi-worn clone would push the scene's geometry
         count past +10% of its pre-bake count, mint none instead — bake
         only meshes whose geometry is already unshared (merged fabric,
         the two floor planes, one-off props) and leave any material with
         a multi-worn cached wearer un-flipped, exactly as authored
         (never black, never borrowed). Whole materials are the unit of
         fallback, not individual meshes: a material with a mix of safe
         and unsafe wearers would otherwise spend the bake's time on
         wearers whose material can never flip anyway. */
      var fallback = (preGeo + projected) > preGeo * 1.10;

      var instancedMaterials = 0, instancedRescued = 0;
      Object.keys(perMat).forEach(function (u) {
        if (perMat[u].instanced) instancedMaterials++;
        var wearers = perMat[u].w;
        if (fallback) {
          var skip = false;
          for (var wi = 0; wi < wearers.length; wi++) {
            var wg = wearers[wi].geometry;
            if (wg.userData.cached && geoWearers[wg.uuid] > 1) { skip = true; break; }
          }
          if (skip) return;             /* left exactly as authored */
        }
        var allBaked = true;
        wearers.forEach(function (mesh) {
          var geo = mesh.geometry;
          if (geo.userData.cached && geoWearers[geo.uuid] > 1) {
            geo = mesh.geometry = geo.clone();   /* fallback already skipped this material */
            geo.userData.cached = false;
            clones++;
          }
          var p = geo.attributes.position, n = geo.attributes.normal;
          if (!p || !n) { allBaked = false; return; }
          nm.getNormalMatrix(mesh.matrixWorld);
          var col = geo.attributes.color;
          if (!col || col.count !== p.count) {
            col = new T.BufferAttribute(new Float32Array(p.count * 3), 3);
            geo.setAttribute('color', col);
          }
          /* per-mesh occluder pre-cull (facade spec §6 buildMs ruling): a
             march sample point can never land more than MAX_STEP from the
             vertex it started at, so any occluder box that does not reach
             within MAX_STEP of this mesh's own world AABB could never be
             hit by ANY of its vertices — filtering AO_OCCLUDERS down to
             just the boxes that can is bit-identical to marching the full
             ~94-entry list every time, just cheaper. Recomputed per mesh
             (not hoisted higher) since each wearer has its own transform. */
          meshBox.setFromObject(mesh);
          var mbx0 = meshBox.min.x - MAX_STEP, mbx1 = meshBox.max.x + MAX_STEP;
          var mby0 = meshBox.min.y - MAX_STEP, mby1 = meshBox.max.y + MAX_STEP;
          var mbz0 = meshBox.min.z - MAX_STEP, mbz1 = meshBox.max.z + MAX_STEP;
          var localOcc = [];
          for (var oc = 0; oc < AO_OCCLUDERS.length; oc++) {
            var OB = AO_OCCLUDERS[oc];
            if (OB[1] >= mbx0 && OB[0] <= mbx1 && OB[3] >= mby0 &&
                OB[2] <= mby1 && OB[5] >= mbz0 && OB[4] <= mbz1)
              localOcc.push(OB);
          }
          for (var v = 0; v < p.count; v++) {
            tmp.fromBufferAttribute(p, v).applyMatrix4(mesh.matrixWorld);
            nrm.fromBufferAttribute(n, v).applyMatrix3(nm).normalize();
            up.set(Math.abs(nrm.y) > 0.94 ? 1 : 0,
                   Math.abs(nrm.y) > 0.94 ? 0 : 1, 0);
            tx.crossVectors(up, nrm).normalize();
            tz.crossVectors(nrm, tx);
            var hit = 0;
            for (var d2 = 0; d2 < DIRS.length; d2++) {
              var D = DIRS[d2];
              var dx = tx.x * D[0] + nrm.x * D[1] + tz.x * D[2];
              var dy = tx.y * D[0] + nrm.y * D[1] + tz.y * D[2];
              var dz = tx.z * D[0] + nrm.z * D[1] + tz.z * D[2];
              for (var s3 = 0; s3 < STEPS.length; s3++) {
                var L3 = STEPS[s3];
                var qx = tmp.x + dx * L3, qy = tmp.y + dy * L3,
                    qz = tmp.z + dz * L3;
                var blocked = false;
                for (var ob = 0; ob < localOcc.length; ob++) {
                  var B = localOcc[ob];
                  if (qx > B[0] && qx < B[1] && qy > B[2] && qy < B[3] &&
                      qz > B[4] && qz < B[5]) { blocked = true; break; }
                }
                if (blocked) { hit += 1 - s3 / STEPS.length; break; }
              }
            }
            var ao = 1 - (hit / DIRS.length) * STR;
            col.setXYZ(v, ao, ao, ao);
          }
          col.needsUpdate = true;
          count++;
        });
        if (perMat[u].instanced) {
          /* an InstancedMesh wearer can never carry a colour attribute of
             its own, so it is an automatic veto no matter how cleanly
             every OTHER wearer baked — those siblings keep the attribute
             they just earned (harmless without the flip: dead data on a
             material that stays vertexColors=false), the shared material
             itself just never samples any of it. */
          if (allBaked) instancedRescued++;
          return;
        }
        if (allBaked) {
          perMat[u].m.vertexColors = true;
          perMat[u].m.needsUpdate = true;
        }
      });
      return { meshes: count, clones: clones, fallback: fallback,
               preGeo: preGeo, projected: projected,
               instancedMaterials: instancedMaterials,
               instancedRescued: instancedRescued,
               ms: Math.round(performance.now() - t0) };
    }
    var aoStats = bakeAO();
    scene.userData.aoStats = aoStats;   /* --budget-reachable via __hpScene,
      the same pattern userData.merged already uses for test introspection */

    /* ---- THE REFLECTION (spec 2026-09-17 section 3.4) -------------------
       ONE reflection, applied LAST. Everything geometric above -- the room
       masks and their shells, the clipper, the block-meet volumes, the AO
       bake, every merge pass -- ran in house-local space and never sees a
       flipped value, which is the whole reason the flip waits until here.

       What stays behind in `scene`: the global sky/sun lights and the sun's target
       (so a mirrored house is lit from the same compass direction as an
       unmirrored one -- the sun does not swap sides with the garage), the
       camera, and the sky dome (a mirrored sky is the same sky, and it is
       the one mesh whose own texture is repainted against the world clock
       rather than the house).

       And THEN the counter-flip, not before: every mesh textMesh()
       stamped gets its own scale.x negated back here, once the geometry
       passes above are all behind us. counterFlip() is a function
       because two subtrees join houseRoot after this line -- the study
       (whose meshes were built long before it) and, later still, the
       car plaques (which are built after REFLECTED goes true and so
       flip themselves inside textMesh). */
    var houseRoot = new T.Group(); houseRoot.name = 'houseRoot';
    scene.children.slice().forEach(function (o) {
      if (o.isLight || o.isCamera || o === sunTarget || o === skyDome) return;
      scene.remove(o); houseRoot.add(o);
    });
    scene.add(houseRoot);
    function counterFlip(root) {
      if (!MIRROR || !root) return 0;
      var n = 0;
      root.traverse(function (m) {
        if (m.userData && m.userData.noMirror) { m.scale.x *= -1; n++; }
      });
      return n;
    }
    if (MIRROR) houseRoot.scale.x = -1;
    counterFlip(houseRoot);
    houseRoot.updateMatrixWorld(true);
    REFLECTED = true;
    if (exteriorOnly) {
      // The active home's night pass initializes glazing after construction.
      // Static kits return before that runtime pass, so capture its daytime
      // finish rather than the bright construction-placeholder glass.
      extG.traverse(function(o){
        if(!o.isMesh || !o.material || !o.material.emissive || o.userData.lamp)return;
        if(o.userData.glazing || o.userData.shellWindow){
          o.material.color.setHex(FARMHOUSE.windowDark);
          o.material.emissive.setHex(0x000000);o.material.emissiveIntensity=0;
        }
      });
      var kit = window.ChauffeurNeighborhood.captureExterior(T, extG,
        [garageInterior, carsG, busG, skyDome, webgl_garageBackWall].concat(options.footprintOnly?[yardG]:[]),
        {front:26, buildingOnly:options.footprintOnly, scenery:[yardG]});
      var retainedTextures = new Set(), sourceMaterials = new Set(), sourceGeometry = new Set(), sourceTextures = new Set();
      function textures(material, output) {
        Object.keys(material).forEach(function(k){if(material[k] && material[k].isTexture)output.add(material[k]);});
      }
      kit.parts.forEach(function(p){textures(p.material, retainedTextures);});
      scene.traverse(function(o){
        if(o.geometry)sourceGeometry.add(o.geometry);
        if(o.material)(Array.isArray(o.material)?o.material:[o.material]).forEach(function(m){sourceMaterials.add(m);textures(m,sourceTextures);});
        if(o.isInstancedMesh)o.dispose();
      });
      sourceGeometry.forEach(function(g){g.dispose();});
      sourceMaterials.forEach(function(m){m.dispose();});
      sourceTextures.forEach(function(t){if(!retainedTextures.has(t))t.dispose();});
      scene.clear();
      kit.spec = JSON.parse(JSON.stringify(options.spec));
      return ownExteriorTextures(kit, retainedTextures);
    }
    // Photo/editor captures isolate the active design. Scenery is independent
    // of its mirror, shell masks, household state and room navigation.
    if (neighborhoodEnabled) {
      function makeNeighborhood(layout) {
        var west=Math.min(FULL_HOUSE.west,GARAGE_BLOCK.west),east=Math.max(FULL_HOUSE.east,GARAGE_BLOCK.east);
        var north=Math.min(FULL_HOUSE.north,GARAGE_BLOCK.north),south=Math.max(FULL_HOUSE.south,GARAGE_BLOCK.south);
        layout=window.ChauffeurNeighborhood.fitLayout(layout,{width:east-west,depth:south-north,x:(west+east)/2*(MIRROR?-1:1),z:(north+south)/2});
        return window.ChauffeurNeighborhood.build(T, CANONICAL_JS, {
        main: Object.assign({}, FULL_HOUSE, {south: FULL_HOUSE.south - MAIN_DZ}),
        garage: Object.assign({}, GARAGE_BLOCK, {south: GARAGE_BLOCK.south - GAR_DZ})
      }, PALETTE, function (surface) { return makeMat(0xffffff, {rough:.95, map: surface === 'plain' ? null : cladTex(surface, 0xffffff)}); }, function(spec, footprintOnly) {
        return buildDetailedExterior(spec, R, footprintOnly);
      }, layout, {west:MIRROR?-east:west,east:MIRROR?-west:east,north:north,south:south,
                   top:(SPEC0.upper&&SPEC0.upper.length?11.2:5.6)+Math.tan((SPEC0.pitch_deg||35)*Math.PI/180)*11}); }
      var initialLayout=window.HOUSE_NEIGHBORHOOD;
      neighborhood = makeNeighborhood(initialLayout);
      scene.add(neighborhood.group);
      neighborhood.update(cam.position, toWorld(ORBIT.pivot), true);
      if(initialLayout && initialLayout.source==='mapbox'){
        parcelRoad.visible=false;
        var mapCredit=document.getElementById('house-map-credit');if(mapCredit)mapCredit.hidden=false;
      }
      // Fetch independently of household state. The room is usable throughout;
      // a failed lookup leaves the existing neighborhood intact, without retry.
      if(!initialLayout || initialLayout.source!=='mapbox')fetch((window.chfBase !== undefined ? window.chfBase : '')+'api/house/neighborhood')
        .then(function(r){if(!r.ok)throw new Error('Map unavailable');return r.json();})
        .then(function(layout){
          if(layout.source!=='mapbox' || !webgl || webgl.R!==R)return;
          var next=makeNeighborhood(layout),previous=neighborhood;
          scene.add(next.group);scene.remove(previous.group);
          neighborhood=next;webgl.neighborhood=next;previous.dispose();
          parcelRoad.visible=false;
          next.setNight(isNight());
          next.update(cam.position,toWorld(ORBIT.pivot),mode==='exterior');
          var credit=document.getElementById('house-map-credit');if(credit)credit.hidden=false;
        }).catch(function(){/* Generated neighborhood remains usable. */});
    }
    function noMirrorCount() {
      var n = 0;
      houseRoot.traverse(function (m) {
        if (m.userData && m.userData.noMirror) n++;
      });
      return n;
    }

    /* ---- the painters: every data surface drawn like the app draws it —
       Inter type, white cards, accent bars, soft shadows. Cached per
       payload; a poll that changes nothing repaints nothing. ---- */
    var texCache = {};
    var FONT = 'Inter, system-ui, sans-serif';
    function mkTex(key, w, h, payload, draw) {
      /* Focus temporarily replaces a live information face with a stable
         blank face. Keep that blank beside the latest live payload so
         revisiting an item does not allocate, upload, and dispose two large
         canvas textures on every camera trip. Live payloads remain bounded
         to one entry per surface as their data changes. */
      var cacheKey = payload === 'blank' ? key + ':focus-blank' : key;
      var e = texCache[cacheKey];
      if (e && e.payload === payload) return e.tex;
      var c = document.createElement('canvas'); c.width = w; c.height = h;
      draw(c.getContext('2d'), w, h);
      var t = new T.CanvasTexture(c);
      t.anisotropy = 4;
      /* task 13: e (if present) is the entry this call is about to
         replace. Every key here has exactly one wearer (hero->plaque,
         calendar->calFace, critters->critFace, weather->paneMesh,
         skydome->skyDome, car:<id>->that car's plaque), and the new
         texture is handed straight to that same wearer by the caller
         (swap()/carTex's caller) immediately after this returns — so
         nothing else can still be pointing at the old one. Without this,
         every repaint (a lean-in blanking a face, a lean-out restoring
         it, a countdown minute ticking over) orphaned the replaced
         CanvasTexture on the GPU forever: +4 textures per calendar+pet
         focus cycle, monotonic, never recovering after lean-out.
         Fix round 1 correction: this is now the SOLE disposer for the
         car:<id> key too. syncGarage's carPlates rebuild (55f4b25) used
         to ALSO dispose the plaque's texture on every rebuild — but that
         rebuild's own guard key hashes nine fields across EVERY car, so
         it fires (and used to dispose every plaque's texture, changed or
         not) on any single car's telemetry tick: routine with 2+ cars,
         not the rare departed-then-returned edge the original report
         named. That meant an unchanged car's texture was destroyed above
         and then handed straight back out by THIS function's own
         cache-hit branch a few lines up (`e.payload === payload`),
         moments later in the SAME rebuild — a disposed object back in
         live use. Confirmed via the vendored three.js (r150) source that
         this was never a "blank plaque": `Texture.prototype.dispose` is
         exactly `dispatchEvent({type:'dispose'})`, so the canvas backing
         a texture is untouched by disposing it; the renderer simply
         re-uploads that same intact canvas to a fresh GPU handle next
         time it is bound — a wasted re-upload, not a visual defect.
         carPlates now disposes only the plaque's MATERIAL (never cached,
         always fresh); this overwrite path is the texture's only
         disposer, car plaques included, so there is no second call site
         left that could double-dispose against it. */
      if (e) e.tex.dispose();
      texCache[cacheKey] = { payload: payload, tex: t, draw: draw };
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
      return mkTex('hero', 512, 320, payload, function heroFace(g, w, h) {
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
        return mkTex('critters', 512, 324, 'blank', function critFace(g, w, h) {
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
      return mkTex('critters', 512, 324, payload, function critFace(g, w, h) {
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
        return mkTex('calendar', 512, 640, 'blank', function calFace(g, w, h) {
          g.fillStyle = '#f6f1e4'; g.fillRect(0, 0, w, h);
          g.fillStyle = '#111827'; g.font = '800 40px ' + FONT;
          g.fillText('Today', 30, 66);
        });
      }
      var calm = !c || c.calm !== false;
      var next = (c && c.next) || [];
      var payload = calm ? 'calm' : [c.today].concat(next).join('|');
      return mkTex('calendar', 512, 640, payload, function calFace(g, w, h) {
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
      return mkTex('weather', 320, 288, payload, function paneFace(g, w, h) {
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
          /* Bottom left, and the sill is kept clear there. The middle band
             looks free but the weather card lands on it at lean-in, so the
             only place a reading survives BOTH the room view and the
             lean-in is the corner nothing else wants. */
          g.save();
          g.shadowColor = 'rgba(0,0,0,0.45)'; g.shadowBlur = 10;
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
        if (night) {
          var overcast = /cloud|fog|rain|snow|pouring|lightning|hail/.test(cond);
          top = overcast ? '#252d38' : '#1c2748'; bot = overcast ? '#46515c' : '#3a4a78';
        }
        else if (cond.indexOf('rain') !== -1 || cond === 'pouring' ||
                 cond.indexOf('lightning') !== -1) { top = '#5b6c7d'; bot = '#8fa0af'; }
        else if (cond.indexOf('snow') !== -1) { top = '#aebfd0'; bot = '#e8eef4'; }
        else if (cond.indexOf('cloud') !== -1 || cond === 'fog') { top = '#8fb0c6'; bot = '#cfdde8'; }
        var grad = g.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, top); grad.addColorStop(0.75, bot);
        grad.addColorStop(1, bot);
        g.fillStyle = grad; g.fillRect(0, 0, w, h);
        if (night && !/cloud|fog|rain|snow|pouring|lightning|hail/.test(cond)) {
          g.fillStyle = 'rgba(255,255,255,0.9)';
          for (var st = 0; st < 40; st++) {
            g.fillRect(((st * 131) % w), ((st * 67) % (h * 0.55)), 3, 3);
          }
        }
        if (!night && !/cloud|fog|rain|snow|pouring|lightning|hail/.test(cond)) {
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
       userData.lamp, and the sky dome already repaints itself at sunrise and
       sunset because skyDomeTex bakes `night` into its cache payload.

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
    var glazing = [], lampGlass = [], shellWindows = [];
    scene.traverse(function (o) {
      if (!o.isMesh || !o.userData) return;
      if (o.userData.shellWindow) shellWindows.push(o);
      else if (o.userData.lamp) lampGlass.push(o);
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
    var outdoorCondition = '';
    function setOutdoorLight(condition) {
      outdoorCondition = condition || '';
      var heavy = /rain|pouring|lightning|snow|hail|fog/.test(outdoorCondition);
      var cloudy = /cloud/.test(outdoorCondition);
      var direct = heavy ? .32 : cloudy ? .58 : 1;
      sun.intensity = SUN_I * (nightNow ? NIGHT_F.sun : 1) * direct;
      hemi.intensity = HEMI_I * (nightNow ? NIGHT_F.hemi : 1) * (heavy ? .85 : 1);
      sun.color.setHex(nightNow ? 0x9db4dd : (heavy || cloudy) ? 0xd3dfe9 : SUN_C);
      shadowDirty();
    }
    function setNight(n) {
      if (n === nightNow) return;
      nightNow = n;
      if (neighborhood) neighborhood.setNight(n);
      hemi.intensity = n ? HEMI_I * NIGHT_F.hemi : HEMI_I;
      hemi.color.setHex(n ? NIGHT_F.sky : SKY_C);
      hemi.groundColor.setHex(n ? 0x1b1c22 : GND_C);
      amb.intensity = n ? AMB_I * NIGHT_F.amb : AMB_I;
      amb.color.setHex(n ? NIGHT_F.ambC : (PBR ? 0xdfe6f0 : 0xe4eaf2));
      sun.intensity = n ? SUN_I * NIGHT_F.sun : SUN_I;
      sun.color.setHex(n ? 0x9db4dd : SUN_C);   /* a moon, not a sun */
      setOutdoorLight(outdoorCondition);
      poolLamps.forEach(function(l) { l.intensity=n ? l.userData.dayI*2.1 : l.userData.dayI; });
      exteriorLamps.forEach(function(l) { l.intensity=n ? l.userData.nightI : 0; });
      porchPools.forEach(function(m) { m.material.opacity=n ? (DETAIL >= 2 ? 0.50 : 0.75) : 0; });
      glazing.forEach(function (m) {
        if (!m.material || !m.material.emissive) return;
        if (m.material.color) m.material.color.setHex(FARMHOUSE.windowDark);
        m.material.emissive.setHex(n ? FARMHOUSE.curtainGlow : 0x000000);
        m.material.emissiveIntensity = n ? FARMHOUSE.curtainIntensity : 0;
        m.material.needsUpdate = true;
      });
      shellWindows.forEach(function (m) {
        if (!m.material || !m.material.emissive) return;
        if (m.material.color) m.material.color.setHex(FARMHOUSE.windowDark);
        var glow = n && !m.userData.interiorWindow;
        m.material.emissive.setHex(glow ? FARMHOUSE.curtainGlow : 0x000000);
        m.material.emissiveIntensity = glow ? FARMHOUSE.curtainIntensity : 0;
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
                   function carPlaque(g, w, h) {
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
    function clearPaint() {
      /* Fonts becoming ready changes lettering, not data or ownership.
         Repaint each cached canvas in place: cars may skip rebuilding on
         unchanged telemetry, so dropping their maps here leaves their
         materials holding disposed textures until a later state change. */
      Object.keys(texCache).forEach(function (key) {
        var entry = texCache[key], canvas = entry.tex.image;
        var context = canvas.getContext('2d');
        context.clearRect(0, 0, canvas.width, canvas.height);
        entry.draw(context, canvas.width, canvas.height);
        entry.tex.needsUpdate = true;
      });
    }

    /* ================= SCENERY RECESSION ==============================
       The knob at the top of the file, made real. Read that comment for
       the WHY; this is the how.

       WHAT COUNTS AS TOUCHABLE. A mesh is interactive when it carries
       userData.zone on itself or any ancestor — the same walk zoneAt()
       does for a tap, so what the eye is told and what the finger finds
       are the same set by construction. One escape hatch:
       userData.scenery === true recedes anyway, and it is checked BEFORE
       the zone at every level so it can override one. The garage bay is
       its only user (see the tag beside `groups.garage`).

       THE MATERIAL TRAP. Tinting a scenery mesh naively bleeds onto
       whatever zone prop shares its material, and a shared material is
       invisible from the call site. So each material is CLASSIFIED first
       — who uses it, scenery or zone or both — and only then touched:

         used by scenery only  -> tinted IN PLACE. No clone: the material
                                  already belongs to nobody else, and a
                                  clone would cost a second object per
                                  prop for an identical picture. It also
                                  keeps the mesh's material IDENTITY,
                                  which matters — swap() and the night
                                  pass both reach for a mesh's material
                                  by hand and would write to an orphan.
         used by both          -> ONE clone, shared by every scenery mesh
                                  on it; the zone meshes keep the
                                  original, untouched.
         used by zones only    -> never touched.

       MEASURED (2026-09-09, `applied` stats from chfHouseScenery): 3234
       lit meshes, 3234 distinct lit materials, ZERO shared. mat() really
       does hand out a fresh material per call on every path this room
       uses, so today the classifier finds nothing to clone and the whole
       scene is tinted in place. The clone arm is not dead code — it is
       the guard rail for the first builder who hoists a material into a
       variable and reuses it, which is a one-line change nobody would
       think to flag. It costs one integer of bookkeeping per material.

       Every base colour (and roughness, and envMapIntensity) is cached on
       the material the first time it is seen, so the curve is always
       applied to the ORIGINAL value. Re-applying k = 0.3 twice cannot
       double-desaturate, and k = 0 restores the authored value exactly —
       which is what makes SCENERY = 0 pixel-identical to the room before
       this existed.

       Only LIT materials recede — Standard and Lambert. A basic material
       has no material response to dull: the sky dome, the contact discs,
       the multiply and additive glows and the painted card faces are all
       MeshBasicMaterial, and half of them carry a blend mode where
       "pull toward mid-grey" would mean something else entirely.

       COST. One traverse of the graph per apply, and applies happen on
       build, on room change, and on an explicit chfHouseScenery call —
       never in the frame loop, and colour is a uniform, so nothing here
       recompiles a shader or dirties the shadow map. ---- */
    /* THE CURVE. Desaturation is the effect; the lightness pull is a
       whisper on top of it. Two lessons from the screenshots:

       - Luminance is what reads as "the lights are on". An early pass
         pulled every value 42% of the way to mid at k=1 and dropped the
         kitchen's mean brightness 15%: it stopped looking like art
         direction and started looking like dusk, or a bug. The pull is
         now small enough to soften a dark anchor without dimming a room.
       - A MAPPED material takes no pull at all. Its colour is white and
         multiplies its texture, so the only thing a pull can do there is
         darken the picture — it cannot desaturate it. That exempts the
         floors, the wood counters, the tile and the siding, which is the
         right answer anyway: the architecture is the ground the props
         stand on, and the ground should not move. (At `low` there are no
         maps at all — mat() drops them below tier 2 — so the whole room
         responds, which is exactly why SCENERY_TIER damps that tier.) */
    var SCEN_SAT = 0.86;    /* saturation removed at k = 1 */
    var SCEN_CON = 0.18;    /* lightness pulled toward SCEN_MID at k = 1 */
    var SCEN_MID = 0.66;    /* the value everything converges on. NOT 0.5:
                               the room is cream, and 0.5 grey would drag
                               every wall down into a fog bank */
    var SCEN_ROUGH = 0.14;  /* tier 3: flatter highlights */
    var SCEN_ENV = 0.60;    /* tier 3: less environment sheen */
    var scenEpoch = 0, scenClones = 0, scenSlots = [];
    var scenHSL = { h: 0, s: 0, l: 0 };

    function scenLit(m) {
      return !!(m && m.color &&
                (m.isMeshStandardMaterial || m.isMeshLambertMaterial));
    }
    function scenIsScenery(o) {
      var p = o;
      while (p) {
        var u = p.userData;
        if (u) {
          if (u.scenery === true) return true;
          if (u.zone || u.houseAction) return false;
        }
        p = p.parent;
      }
      return true;                       /* no zone above it: set dressing */
    }
    function scenSlot(m) {
      if (m.userData._scEpoch !== scenEpoch) {
        m.userData._scEpoch = scenEpoch;
        m.userData._scSlot = scenSlots.length;
        scenSlots.push({ m: m, sc: 0, zn: 0 });
      }
      return scenSlots[m.userData._scSlot];
    }
    function scenBase(m) {
      var b = m.userData._scBase;
      if (!b) b = m.userData._scBase = { c: m.color.clone(),
                                         r: m.roughness, e: m.envMapIntensity };
      return b;
    }
    function scenTint(m, b, k) {
      m.color.copy(b.c);
      if (k > 0) {
        m.color.getHSL(scenHSL);
        var pull = m.map ? 0 : SCEN_CON;   /* see the curve note above */
        m.color.setHSL(scenHSL.h,
                       scenHSL.s * (1 - k * SCEN_SAT),
                       scenHSL.l + (SCEN_MID - scenHSL.l) * k * pull);
      }
      /* a Lambert has neither of these: guard, never assume the tier */
      if (b.r !== undefined) m.roughness = Math.min(1, b.r + k * SCEN_ROUGH);
      if (b.e !== undefined) m.envMapIntensity = b.e * (1 - k * SCEN_ENV);
    }

    /* k: 0..1. Returns a small stats object — the studio's read on how
       much sharing there actually is, and what the knob is set to. */
    function applyScenery(k) {
      k = Math.max(0, Math.min(1, isFinite(k) ? k : 0));
      scenEpoch++;
      scenSlots = [];
      var meshes = 0, dressed = 0;
      /* pass 1 — classify. o.userData._scOrig remembers the authored
         material, so a second apply classifies the ORIGINAL and never a
         clone it handed out itself. */
      scene.traverse(function (o) {
        if (!o.isMesh || !o.material || Array.isArray(o.material)) return;
        var orig = o.userData._scOrig || o.material;
        if (!scenLit(orig)) return;
        o.userData._scOrig = orig;
        meshes++;
        var s = scenSlot(orig);
        if (scenIsScenery(o)) { s.sc++; dressed++; } else s.zn++;
      });
      /* pass 2 — tint each distinct material once */
      scenSlots.forEach(function (s) {
        if (!s.sc) return;                       /* zones only: hands off */
        var b = scenBase(s.m);
        if (s.zn) {                              /* shared: one clone */
          var d = s.m.userData._scDim;
          if (!d) { d = s.m.userData._scDim = s.m.clone(); scenClones++; }
          scenTint(d, b, k);
        } else {
          scenTint(s.m, b, k);                   /* nobody else's: in place */
        }
      });
      /* pass 3 — hand each mesh the material it should be wearing */
      scene.traverse(function (o) {
        var orig = o.userData && o.userData._scOrig;
        if (!orig) return;
        /* the epoch check is not paranoia: a mesh pass 1 declined to
           classify (its material swapped for an unlit one, say) still
           carries _scOrig, and its slot index would point into a
           PREVIOUS pass's array. Unclassified means: wear the original. */
        var s = orig.userData._scEpoch === scenEpoch
              ? scenSlots[orig.userData._scSlot] : null;
        var dim = (k > 0 && s && s.zn && s.sc && orig.userData._scDim &&
                   scenIsScenery(o));
        o.material = dim ? orig.userData._scDim : orig;
      });
      return { applied: k, meshes: meshes, dressed: dressed,
               materials: scenSlots.length, clones: scenClones };
    }

    /* Study occupies the authored east-front wing and joins this scene's
       room/zone registries before footprints and scenery are indexed.
       VIEW-VOLUME MASKING (task 3): the study is BUILT earlier now (see
       "studyWorld = window.HouseStudy.build" beside ROOM_AABB, above the
       per-fabric merge loop) because its footprint feeds the study's
       mask box, which has to exist before the shells are cut -- but it
       joins the SCENE here, exactly where it always did: after the merge
       passes and the AO bake, which therefore never see it (its own
       materials are unshared and it was never baked; moving the add
       would have baked ~500 study meshes and changed the study's look). */
    /* THE MIRROR (section 3.4): into houseRoot, not the scene -- the study
       is a room of THIS house at an authored house-local address, and its
       camera pose is reflected with every other room's, so a study left
       behind in the scene would sit on the far side of a mirrored plan
       and the study view would look at empty lawn. */
    if (studyWorld) {
      [studyWorld.group, studyWorld.architecture, studyWorld.proxies]
        .forEach(function (g) {
          if (!g) return;
          houseRoot.add(g);
          /* the study's own lettered meshes (house_study.js stamps
             userData.noMirror on them; it is built before `webgl` exists
             and so cannot call textMesh) missed the root pass by joining
             here -- counter-flip this subtree now, exactly once. */
          counterFlip(g);
        });
    }

    /* on BUILD: the room boots at the exterior, where nothing recedes, so
       this is a k = 0 pass. It is not a no-op — it is what caches every
       authored colour, so the first room entered tints from the original
       and not from whatever it happened to be wearing. */
    applyScenery(0);

    /* Meshes that answer to a zone but live OUTSIDE its group — the
       mudroom's garage door is tagged `door` yet hangs on the west wall,
       not inside doorG. The awake-glow loop walks a zone's group, so
       without this index a zone lights only the half of itself that
       happens to be parented under it. Built once; the scene is static
       apart from the cars and backpacks, which carry no zone glow. */
    var zoneExtra = {};
    scene.traverse(function (o) {
      if (!o.isMesh || !o.userData) return;
      var k = o.userData.zone;
      if (!k || !groups[k]) return;
      var p = o, inside = false;
      while (p) { if (p === groups[k]) { inside = true; break; } p = p.parent; }
      if (!inside) (zoneExtra[k] = zoneExtra[k] || []).push(o);
    });

    /* ---- SHELL (spec section 4): per-room footprints ------------------
       roomsReg()'s solver subject for the room-level views: a box around
       what is actually INSIDE the room (floor, furniture, fixtures), not
       the shell that ENCLOSES it. Deliberately LAST, here beside
       zoneExtra rather than back near stampHouse (spec section 4 was
       first written there, right after stampHouse gives every extG-built
       mesh a resolvable userData.room) — measured directly, a group that
       is TAGGED early in the file (e.g. doorG at its own build site) is
       not always POSITIONED there yet; some groups move again later in
       this same build sequence, the same reason fabBox's own call sites
       wait for "nothing later adds to this group" before measuring.
       Every zone/room tag this build ever sets is resolved by the time
       buildRoom() is about to return (zoneExtra, just above, leans on
       that same fact), so this is the one place in the whole function
       guaranteed safe to measure ALL of them at once. A SEPARATE
       traversal (not fused into stampHouse's own, to leave that
       tap-routing function, and its own test coverage, untouched) that
       walks the same kind of ancestor chain mergeStatic's own roomTag
       derivation uses, so a leaf that inherits its tag from a group (a
       zone stray, mudroomRoofG's traverse-stamp) buckets exactly where
       mergeStatic would bucket it.

       Rooted at `scene`, not `extG`: this file was born as a copy of
       kitchen.js (the header's own words), so the kitchen/living great
       room's own floor and furniture were built and added straight to
       `scene` long before extG exists to hold the newer garage/mudroom/
       roof/yard fabric — stampHouse's extG-only traversal never claimed
       to reach them, and neither would this one at the same root.
       Kitchen and living share one open floorplan but were never one
       mesh: `floor` (kitchen, z -5.8..5.8) and `floor2` (living, z
       5.7..14.2) are two separate PlaneGeometry meshes reading as one
       continuous wood floor, each now tagged with its own room at its
       own build site (see their own comments) for exactly this — so
       kitchen and living end up with two DIFFERENT footprints despite
       standing on the same slab, with no hand-typed box for either.
       Cars and backpacks (added later, at RUNTIME, by syncGarage/
       syncMudroom, long after this return) are correctly absent: a
       room's footprint is its fixed shell, not whatever is parked in it
       today.

       Two exclusions, found by tuning against the LEGACY verdict table
       (test RED without them; both are geometry the room-tag scheme was
       always going to catch, never a fudge against one failing case):

       1. A registered FABRIC group is the SHELL, not the room's own
          interior — the whole point of the solver is to test a room's
          subject against that shell, so the shell cannot also BE the
          subject. Concretely: garageDoorG is tagged 'garage' (gtag) and
          westWallG is fallback-tagged 'kitchen' (both, like every shell
          piece, sit ON the room's boundary), so leaving them in made a
          room's own aabb straddle the very plane it needed to read as
          clearly inward of — garage's z-centre landed EXACTLY on
          garage_door's own z-centre (0 is never < 0), never able to
          verdict a ghost/hide no matter how the piece's own box was
          tuned.
       2. A mesh whose OWN box top exceeds ROOM_CEILING is roofline, not
          occupiable room volume, so it is excluded the same way a
          registered roof piece would be if this build had already
          migrated it (spec section 3 lists a main roof among the pieces
          still to come). Concretely: the main roof over the kitchen/
          great room (ridge/soffit boards, gable ends) is fallback-tagged
          'kitchen' and peaks at y=9.37 with its lowest eave board at
          y=6.8, and a stray mudroom gable/ridge detail outside
          mudroomRoofG reaches y=7.04 — either one left in pulls that
          room's whole box (and so its centre) up toward ceiling height,
          the opposite of "where the room's own furniture is". Measured
          walls top out at 5.6 (the main kitchen/living wall) and 4.2-4.5
          (mudroom/garage), so 6.0 sits in the clear gap between "tallest
          wall" and "lowest eave" for every room this build has today. */
    /* LOAD-BEARING for solver verdicts, not just AABB hygiene: a mesh
       whose top crosses this line silently drops out of ROOM_AABB, moving
       the room's subject CENTRE on all three axes. If any wall or fixture
       height changes near 6.0, re-verify against the LEGACY verdict table
       (scenario_shell_fabric_registry). */
    /* VIEW-VOLUME MASKING (task 3): ROOM_AABB itself is DERIVED ABOVE
       now -- immediately before buildRoomShells(), ahead of the per-
       fabric merge loop -- because the five room masks are built from
       it and the shells must be cut from the pre-merge boxes. Every
       word of the comment above still holds: nothing between that site
       and this one adds a room-tagged mesh or moves a group (verified:
       the only later scene additions are the sky dome, the ghost edges
       and the study, and the study is built there too and measured
       explicitly). The hoisted values were compared against this
       original site's, room by room, before the move: the same to the
       millimetre (the living floor's y-min moved 4mm, pre-merge vs
       merged box of one floor-level prop). */

    return {
      applyScenery: applyScenery,
      T: T, scene: scene, cam: cam, R: R, groups: groups,
      /* THE MIRROR (spec 2026-09-17 section 3.4): the reflection root, the
         flag, the house-local <-> world boundary (its own inverse) and the
         one creator of text-bearing meshes -- syncGarage's car plaques are
         built out here, after the reflection, and need all four. */
      MIRROR: MIRROR, houseRoot: houseRoot, textMesh: textMesh,
      toWorld: toWorld, toWorldX: toWorldX, noMirrorCount: noMirrorCount,
      steam: steam, steam2: steam2, needle: needle, plaque: plaque,
      calFace: calFace, boardFace: boardFace, magnets: magnets,
      /* boardFace stays exported: the overlay quad rides its plane */
      critFace: critFace, critterTex: critterTex, pendants: pendants,
      radioFace: radioFace, fridgeDoorTop: fridgeDoorTop,
      paneMesh: paneMesh, heroTex: heroTex, calendarTex: calendarTex,
      weatherTex: weatherTex, clearPaint: clearPaint,
      weather: window.HouseWeather.build(T, scene, DETAIL),
      extG: extG, skyDome: skyDome, skyDomeTex: skyDomeTex,
      aimShadow: aimShadow, shadowDirty: shadowDirty,
      setNight: setNight, isNight: isNight,
      setOutdoorLight: setOutdoorLight,
      garageDoorG: garageDoorG, garageInterior: garageInterior,
      pantryJars: pantryJars, pantryDoor: pantryDoor,
      garageBackWall: webgl_garageBackWall,
      carsG: carsG, busG: busG, buildCar: buildCar, carTex: carTex,
      cgeo: cgeo,
      HOME_POS: HOME_POS, HOME_AT: HOME_AT,
      /* ORBIT (spec section 4): EXT_POS/EXT_AT stay the names every caller
         already uses — the probe, chfHouseCam's neighbours, goExterior, the
         car plaques that turn to face the eye — but they now REPORT the
         current stop instead of naming one pose. Nothing outside this file
         has to learn the ring, and goExterior gets "exit to the stop you
         left from" for free. Each read hands back a fresh vector; nothing
         in the app has ever mutated these. */
      get EXT_POS() { return orbitPos(ORBIT.stop); },
      /* THE MIRROR (section 3.4): EXT_POS/EXT_AT are the exterior CAMERA's
         pose, so both are world. The five room poses below stay
         house-local on purpose -- the mask solver and ROOM_CAMS read
         them, and a flipped value there would cut the cutaways from the
         wrong side. goHome/enterRoom put them through toWorld at the
         tween, which is the one place they become a camera. */
      get EXT_AT() { return toWorld(ORBIT.pivot); },
      ORBIT: ORBIT, orbitPos: orbitPos,
      GARAGE_POS: GARAGE_POS, GARAGE_AT: GARAGE_AT,
      MUD_POS: MUD_POS, MUD_AT: MUD_AT, LIV_POS: LIV_POS, LIV_AT: LIV_AT,
      STUDY_POS: STUDY_POS, STUDY_AT: STUDY_AT, studyWorld: studyWorld,
      mudroomRoofG: mudroomRoofG,
      yardG: yardG, neighborhood: neighborhood, westWallG: westWallG, zoneExtra: zoneExtra,
      mudBagsG: mudBagsG, makeBag: makeBag, FABRIC: FABRIC,
      ROOF_FORMS: ROOF_FORMS,
      ROOF_ALIAS: ROOF_ALIAS, roofAlias: roofAlias,
      registerFabric: function (group, spec) {
        /* THE MIRROR (spec 2026-09-17 section 3.4): fabBox measures in
           WORLD space, and a row registered out here is already inside
           houseRoot -- so on a mirrored plan its box comes back reflected
           while every row registered at build time is house-local. Bring
           it back, so FABRIC speaks ONE space and the mask below (and
           chfNavProbe's own reflection) read what they expect. */
        var b = fabBox(group);
        if (MIRROR) b = [-b[1], -b[0], b[2], b[3], b[4], b[5]];
        regFabric(group, {name:spec.name, n:spec.normal, box:b,
                          room:spec.room, kit:spec.kit});
        /* VIEW-VOLUME MASKING (task 3): a row registered after the
           shells were built is masked whole-or-nothing, synchronously,
           because syncWorld's own solveShell call follows this at once */
        maskLateRow(FABRIC[FABRIC.length - 1]);
      },
      solveShell: solveShell, ROOM_AABB: ROOM_AABB, AO_OCCLUDERS: AO_OCCLUDERS,
      worldTris: worldTris,
      /* ROOF VALLEYS (masking task 5): the street deck plane under a
         face's features and the facade rows' as-built vertices, for the
         read-only window.chfRoofPlane / chfFabricVertices hooks */
      faceDeckPlane: faceDeckPlane, blockDeckPlanes: blockDeckPlanes,
      FEATURE_VERTS: FEATURE_VERTS,
      /* MASSING ARC 2 task 6: the two blocks' envelopes and deck planes,
         for the read-only window.chfBlockGeometry hook; and (fix round
         1) whether each block's roof was actually clipped against its
         neighbour's volume, with the planes of that volume either way */
      blockGeometry: blockGeometry,
      BLOCK_MEET: BLOCK_MEET, BLOCK_VOLUMES: BLOCK_VOLUMES,
      VOLUME_MEETS: VOLUME_MEETS,
      /* VIEW-VOLUME MASKING (task 3): the five room shells, their masks
         (P, W, box, cam) and the one cap material, for the read-only
         window.chfRoomShell* hooks below */
      roomShellGroups: roomShellGroups, ROOM_MASKS: ROOM_MASKS, CAP_MAT: CAP_MAT,
      /* MASSING ARC 2 task 7: the five room poses, for the read-only
         window.chfRoomViewClear hook (a ray from cam to at) */
      ROOM_CAMS: ROOM_CAMS, ROOM_AT: ROOM_AT,
      /* MASSING ARC 2 (spec 2026-09-17 section 2): the block model the
         scene was built from, for window.chfBlocks */
      BLOCKS: BLOCKS,
      /* task 6: syncGarage parks driveway cars off the apron's own near
         end, which a garage depth moves */
      GARAGE_SOUTH: GARAGE_BLOCK.south,
      SIDE_PARK_X: [-21.4, SIDE_PROJECTION ? POP_X : -21.4],
      SIDE_PARK_TURN: [Math.PI/2, SIDE_PROJECTION ? 0 : Math.PI/2],
      SIDE_PARK_Z: SIDE_PROJECTION ? [SIDE_DOOR_Z, SIDE_OPEN_Z1+3.0] : SIDE_DOOR.third_bay ? [SIDE_DOOR_Z, SIDE_THIRD_Z] : [SIDE_DOOR_Z - 1.4, SIDE_DOOR_Z + 1.4],
      SIDE_DRIVE_SECTION: sideDriveSection,
      SIDE_QUEUE_Z: SIDE_APRON_Z1 + 3.3,
      /* task 8: which way the garage faces -- syncGarage parks the
         driveway cars on the side apron instead of the front one, and
         chfNavProbe's face lookup goes straight to the door row, which
         on a side-entry garage is not street-facing at all. */
      GARAGE_SIDE: GARAGE_SIDE,
      /* FACADE (arc 4): the spec the elevation was BUILT from (never the
         raw injection -- buildElevation() falls back to CANONICAL_JS)
         and the slot table it derived, for chfFacade/chfFacadeSlots. */
      SPEC: SPEC, SLOTS: SLOTS
    };
  }

  /* ---- render-on-demand engine ---------------------------------------- */
  var state = null;
  var focused = null;        // zone key while leaned in
  var mode = 'exterior';     // 'exterior' | 'kitchen'
  var lookAt = null;         // the camera's CURRENT look target (tween continuity)
  var tween = null;          // {fromP,toP,fromA,toA,t0,ms,cb}
  var rafLive = false;

  function updateBack() {
    window.dispatchEvent(new CustomEvent('chf-house-view'));
    updateOrbitControls();   /* the chevrons belong to the exterior only */
    if (!BACK) return;
    BACK.hidden = mode === 'exterior';
    if (mode === 'exterior') return;
    var roomName = mode.charAt(0).toUpperCase() + mode.slice(1);
    if (!focused && mode === 'study') {
      BACK.textContent = '\u2190 Living room';
      BACK.setAttribute('aria-label', 'Return to the living room');
      return;
    }
    BACK.textContent = focused ? '\u2190 ' + roomName : '\u2190 Exterior';
    BACK.setAttribute('aria-label', focused
      ? 'Return to the ' + roomName.toLowerCase()
      : 'Return to the exterior');
  }

  function requestFrame() {
    if (!rafLive && webgl) { rafLive = true; requestAnimationFrame(frame); }
  }

  /* ---- the scenery knob, applied ---------------------------------------
     Inside a room only: at the exterior the whole house IS the subject and
     a receded yard would just look like haze. Called on room change, at
     the end of applyState (so props the state builds — the bay's cars, the
     bench's backpacks — join the hierarchy instead of standing out of it),
     and by chfHouseScenery. Never from frame(). */
  function sceneryK() {
    return mode === 'exterior' ? 0 : SCENERY * SCENERY_TIER;
  }
  function syncScenery() {
    return webgl ? webgl.applyScenery(sceneryK()) : null;
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
    if (document.visibilityState === 'hidden') return;
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

    if (webgl.neighborhood) webgl.neighborhood.update(webgl.cam.position, webgl.EXT_AT, mode === 'exterior');
    if (webgl.weather.update((tms || 0)/1000, mode === 'exterior', WEATHER_MOTION.matches)) keep = true;
    /* the study's monitor graph: drawn once whenever its data moved, and
       animated (ten frames a second, the standalone page's own rate and
       law) only while somebody is leaned into the monitor and motion is
       not reduced -- a settled study costs the GPU nothing */
    if (mode === 'study' && webgl.studyWorld && webgl.studyWorld.tick) {
      webgl.studyWorld.tick((tms || 0) / 1000);
      if (focused === 'study_monitor' && webgl.studyWorld.animates && !tween) keep = true;
    }
    webgl.R.render(webgl.scene, webgl.cam);
    if (keep) { rafLive = true; requestAnimationFrame(frame); }
  }

  function exteriorFov(aspect) {
    // Preserve the house's horizontal framing on portrait panels.
    return Math.min(70, 2 * Math.atan(Math.tan(12 * Math.PI / 180) * Math.max(1, 1.25 / aspect)) * 180 / Math.PI);
  }
  function size() {
    if (!webgl) return;
    var w = ROOT.clientWidth || 1, h = ROOT.clientHeight || 1;
    webgl.R.setSize(w, h, false);
    webgl.cam.aspect = w / h;
    if (mode === 'exterior') webgl.cam.fov = exteriorFov(webgl.cam.aspect);
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
    window.dispatchEvent(new CustomEvent('chf-house-state', { detail: s }));
    refreshAttentionBadges();
    if (!webgl) { drawFallback(s); return; }

    Object.keys(ZONES).forEach(function (key) {
      var g = webgl.groups[key];
      var extra = (webgl.zoneExtra || {})[key] || [];
      if (!g && !extra.length) return;
      var n = ZONES[key].num(s);
      var lit = (key === 'garage' || key === 'pet' || key === 'door') &&
                n > 0 && (s[key] || {}).calm === false;
      if (key === 'calendar') lit = packingAttention() > 0;
      function paint(o) {
        if (o.isMesh && o.material && o.material.emissive) {
          /* the live-zone glow. 0x2a1e08 was authored against ACES, which
             compressed it; under a linear curve the same value added a
             sixth of full red straight onto the surface and turned a lit
             door mustard. Halved and cooled - it still says "this one is
             awake" without repainting the prop. */
          o.material.emissive.setHex(lit ? 0x120c03 : 0x000000);
        }
      }
      if (g) g.traverse(paint);
      extra.forEach(paint);   /* the same zone's parts on another wall */
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
    /* the same law the door plaque and the fridge magnets obey: leaned in,
       the card IS the detail, and the room must not say 68% twice at two
       sizes with the small one half behind the big one */
    carPlates.forEach(function (p) { p.visible = focused !== 'garage'; });
    syncMudroom(s);
    syncWorld(s);

    /* dusk and dawn ride the same tick the sky dome does */
    webgl.setNight(webgl.isNight());
    webgl.setOutdoorLight((s.window || {}).cond);
    webgl.weather.set(s.window || {}, webgl.isNight());
    /* the only path that can change what the depth pass would draw */
    webgl.shadowDirty();

    /* moment magnets on the fridge door: one colored square each, capped */
    var wantMagnets = Math.min(((s.fridge || {}).new_moments || 0), 6);
    if (webgl.magnets.children.length !== wantMagnets) {
      /* task 13: same leak family as mkTex. The geometry is shared below
         through cgeo (every magnet is the same box), so it is guarded by
         the standard userData.cached idiom rather than disposed here —
         but the Lambert material is a fresh mint per magnet (the color
         varies) and this loop used to drop it on the floor every rebuild
         without freeing it. */
      while (webgl.magnets.children.length) {
        var mOld = webgl.magnets.children[0];
        webgl.magnets.remove(mOld);
        if (mOld.material) mOld.material.dispose();
        if (mOld.geometry && !mOld.geometry.userData.cached) mOld.geometry.dispose();
      }
      var MAG_COLORS = [0xc9473d, 0x3fbdb2, 0xe09a3e, 0x5a7fc0, 0x7fae5a, 0xb06ab0];
      for (var mi = 0; mi < wantMagnets; mi++) {
        var mm = new webgl.T.Mesh(webgl.cgeo('b|0.22|0.22|0.03', function () {
          return new webgl.T.BoxGeometry(0.22, 0.22, 0.03);
        }), new webgl.T.MeshLambertMaterial({ color: MAG_COLORS[mi % 6] }));
        mm.position.set(-0.45 + (mi % 3) * 0.45, 3.2 - Math.floor(mi / 3) * 0.42, 0);
        webgl.magnets.add(mm);
      }
    }

    /* the state builds props of its own — the bay's cars, the bench's
       backpacks, these magnets — so the hierarchy is re-read here rather
       than only on room change, or a fresh backpack would sit at full
       saturation in a room that had stepped back around it */
    syncScenery();

    requestFrame();
  }

  /* ---- the garage floor plan: cars rebuilt only when their payload
     changes. Two present cars park in the bay, the rest fill the driveway
     apron two abreast, and an absent car is simply not built — the empty
     spot IS the feature.

     EVERY present car wears its own plaque, floating over its own roof.
     They used to be pinned to the garage back wall and only the first two
     were built at all, so a household with four cars got a status on two
     of them and nothing on the others — the bug this pass exists to fix.
     Riding the car makes the association unarguable and costs one plane
     per car instead of a wall rank that has to be laid out.

     A plaque faces the eye that will actually see it: the bay's face the
     garage camera, the driveway's face the exterior one. Both are
     constants, so this is a lookAt done ONCE per payload change — never a
     billboard, which would be per-frame work the room does not do. ---- */
  var world = null;
  function syncWorld() {
    if (!webgl || !window.HouseFeatures || world) return;
    /* THE MIRROR (spec 2026-09-17 section 3.4): into houseRoot, not the
       scene -- every fixture here stands at an authored HOUSE-LOCAL
       address inside a room, so it has to be reflected with the room it
       stands in. (registerFabric measures its box in world space and
       brings it back to house-local; see its own note.) */
    if (world) { webgl.houseRoot.remove(world.group); world.dispose(); }
    world = window.HouseFeatures.build(webgl.T, DETAIL);
    webgl.houseRoot.add(world.group);
    (world.fabric || []).forEach(function (fixture) {
      webgl.registerFabric(fixture.group, {
        name:fixture.name, normal:fixture.normal,
        room:fixture.group.userData.room, kit:fixture.kit
      });
    });
    if (mode !== 'exterior') {
      var room = roomsReg()[mode];
      if (room) webgl.solveShell(webgl.cam.position, {box:room.aabb, room:mode});
    }
    scheduleHint();
  }
  window.chfHouseFindFeature = function(key) {
    if (!world || !webgl) return false;
    var entry = world.entries.filter(function(e){return e.action === key;})[0];
    if (key === 'packing') {
      if (!(((state || {}).mudroom || {}).packs || []).length) return false;
      if (mode === 'kitchen' && !focused) return false;
      enterRoom('kitchen', null); return true;
    }
    if (!entry) return false;
    if (mode === entry.room && !focused) return false;
    enterRoom(entry.room, null);
    chip('Tap ' + entry.label.toLowerCase() + ' to open ' + key + '.');
    return true;
  };
  var garagePayload = null;
  /* the bay's two slots, and the apron's grid: two columns across the
     driveway's 4.6-unit width, rows 4.2 apart. The old single file at 4.6
     spacing put the fourth car in the street with its nose past the kerb;
     two abreast keeps four of them on the concrete.

     The first row starts at z 13.4, not at the door: the garage camera
     (-14.05, 9.6, 21.3 → -15.45, 1.75, 6.05) drops anything nearer than
     about z 13 into the bottom edge of its frame, where the chat bar is,
     and a plaque aimed at the EXTERIOR camera lands there as a skewed
     sliver. Past 13 the apron is cleanly out of the garage's shot, which
     is the honest answer — you cannot see the car there either. */
  var BAY_X = [-16.7, -14.1], DRIVE_X = [-16.55, -14.25];
  /* SIDE-ENTRY (task 8): the apron in front of a side door runs west
     across z 1.9..6.1, so its two spots stand side by side along z at
     one x and the cars face the door -- a quarter turn from the ones on
     the front drive.
     REVIEW FIX: the apron is CAPPED AT TWO and the rest queue down the
     APPROACH, because the apron is only 5.2 deep and a third row west of
     it would stand on the lawn. Cars 3+ take the approach's own two
     columns (x -21.65 / -19.35, inside its 4.6 width the way DRIVE_X
     sits inside the front apron's) and rows 4.2 apart running south from
     z 9.4, which is clear of the apron's own z 6.1 edge -- two abreast on
     concrete, exactly what the front branch does. They face the street
     (no turn), since that is the way they drove in. */
  var DRIVE_SIDE = [[-21.4, 2.6], [-21.4, 5.4]];
  var DRIVE_SIDE_RUN = [-21.65, -19.35];
  var carPlates = [];        /* the plaques, so the lean-in can blank them */
  /* ORBIT (spec section 4): turn the driveway plaques to the stop the
     camera has arrived at. Called once per landed orbit step — never per
     frame, and never for a bay plaque, which faces its own fixed camera. */
  /* THE MIRROR (spec 2026-09-17 section 3.4): Object3D.lookAt() removes
     the parent's rotation with extractRotation(), which only normalises
     the column lengths -- hand it a REFLECTING parent (houseRoot, scaled
     -1 in x) and it reads diag(-1,1,1) back as if it were a rotation and
     the plaque ends up aimed at nothing. So the aim is taken in the
     plaque's OWN parent space instead: the world eye is brought into that
     space through the full inverse matrix (which handles the reflection
     exactly), and the look matrix is built there. Unmirrored this is
     arithmetically what lookAt() already did. */
  function aimPlate(p, worldEye) {
    var e = worldEye.clone();
    if (p.parent) { p.parent.updateWorldMatrix(true, false); p.parent.worldToLocal(e); }
    p.quaternion.setFromRotationMatrix(
      new webgl.T.Matrix4().lookAt(e, p.position, p.up));
  }
  function aimCarPlates() {
    if (!webgl) return;
    var eye = webgl.EXT_POS;
    carPlates.forEach(function (p) {
      if (p.userData.orbitAimed) aimPlate(p, eye);
    });
  }
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
      /* task 9b, corrected by task 13 fix round 1: the plaque's MATERIAL
         is minted fresh every rebuild and never shared (L1 — see the
         comment below), so it is always safe -- and required -- to
         dispose it here. The TEXTURE it wears is a DIFFERENT lifecycle:
         mkTex caches it by 'car:<id>' and hands back the very same
         object across rebuilds whenever that one car's own carTex
         payload ([name, battery_pct, fuel_pct, warn]) is unchanged. This
         loop fires on ANY car's change (the key above hashes nine fields
         across every car), so with 2+ cars it is routine, not rare, for
         a rebuild to run here while some car's own payload is identical
         to last time. This loop used to dispose that car's texture
         anyway, unconditionally -- destroying an object mkTex's own
         cache-hit branch (`e.payload === payload`) was about to hand
         straight back out to that same car's new plaque, moments later
         in this same rebuild. Not a leak (mkTex's dispose-on-overwrite,
         task 13, is still the only path that ever actually drops a
         texture for good) and not a blank plaque either (three.js
         Texture.dispose() only fires an event; it never touches the
         canvas a still-referenced, already-disposed texture wears) --
         just a wasted GPU re-upload of an already-correct picture, every
         time. Fixed by narrowing this loop to what it alone owns: the
         material. mkTex is now the texture's sole disposer for car
         plaques too, exactly like every other key in its table; carPlates
         is the exact list of the plaques just orphaned from the graph by
         .remove() above; car BODY meshes are not in this list (they wear
         cgeo-cached, shared geometry and mat()-cached materials that must
         never be disposed here). */
      carPlates.forEach(function (p) {
        if (p.material) p.material.dispose();
      });
      carPlates = [];
      var inside = 0, outside = 0;
      cars.forEach(function (c) {
        if (!c.present) return;
        var grp = webgl.buildCar(c);
        var eye, extAim = false;
        if (inside < 2) {
          /* the garage boards sit at 0.035 and the driveway apron at
             -0.21: a car parked at y 0 sinks into one and floats over
             the other, and its contact shadow goes with it */
          grp.position.set(BAY_X[inside], 0.038, 5.6);
          /* THE MIRROR (section 3.4): GARAGE_POS is the house-local room
             pose (the mask solver's copy); aimPlate wants the eye in
             WORLD space, the same space EXT_POS already reports in. */
          eye = webgl.toWorld(webgl.GARAGE_POS);
          inside++;
        } else if (webgl.GARAGE_SIDE) {
          if (outside < 2) {
            var spot = DRIVE_SIDE[outside];
            grp.position.set(webgl.SIDE_PARK_X[outside], -0.206, webgl.SIDE_PARK_Z[outside]);
            grp.rotation.y = webgl.SIDE_PARK_TURN[outside];
          } else {
            var q = outside - 2;
            var queueZ=webgl.SIDE_QUEUE_Z+Math.floor(q/2)*4.2;
            var lane=webgl.SIDE_DRIVE_SECTION(queueZ);
            grp.position.set(lane.center+(q%2 ? 1.1 : -1.1),-0.206,queueZ);
            grp.rotation.y=Math.atan2(webgl.SIDE_DRIVE_SECTION(queueZ+0.05).center-
                                     webgl.SIDE_DRIVE_SECTION(queueZ-0.05).center,0.1);
          }
          eye = webgl.EXT_POS;
          extAim = true;
          outside++;
        } else {
          grp.position.set(DRIVE_X[outside % 2], -0.206,
                           13.4 + Math.max(0, webgl.GARAGE_SOUTH - 10.10) +
                           Math.floor(outside / 2) * 4.2);
          eye = webgl.EXT_POS;
          extAim = true;
          outside++;
        }
        webgl.carsG.add(grp);
        /* the plaque's height comes from the car's OWN box, so a van's
           sits as clear of its roof as a hatchback's does */
        var box = new webgl.T.Box3().setFromObject(grp);
        /* task 9b: the plaque's dims never vary, so the GEOMETRY now
           shares through cgeo exactly like every other cached primitive
           in the room; see the dispose call above for the material and
           texture this leaves behind, which stay fresh on purpose. */
        /* THE MIRROR (section 3.4): the plaque wears the carPlaque
           painter's lettering, so it is built by textMesh -- which stamps
           noMirror and counter-flips it on a mirrored plan. Parented
           below, beside carPlates, exactly as it always was. */
        var plate = webgl.textMesh(
          webgl.cgeo('pq|1.5|0.75', function () {
            return new webgl.T.PlaneGeometry(1.5, 0.75);
          }),
          new webgl.T.MeshBasicMaterial({ transparent: true,
                                          map: webgl.carTex(c) }),
          webgl.carsG);        /* parented HERE (it used to be parented a
             few lines down): aimPlate needs the plaque's real parent to
             bring the world eye into its own space */
        plate.position.set(grp.position.x, box.max.y + 0.86,
                           grp.position.z);
        aimPlate(plate, eye);
        /* ORBIT (spec section 4): a driveway plaque faces the EXTERIOR
           eye, and that eye is a ring of eight now — so it has to be
           re-aimed when the ring moves or it goes edge-on (invisible)
           at seven stops out of eight. Marked here, turned by
           aimCarPlates() when an orbit step lands; a bay plaque faces
           its own fixed garage camera and never moves. */
        plate.userData.orbitAimed = extAim;
        /* fresh material every rebuild: never cache-shared (L1) */
        plate.userData.zone = 'garage';
        plate.userData.room = 'garage';
        carPlates.push(plate);
      });
    }
    if (webgl.busG) webgl.busG.visible = !!((s.curb || {}).bus);
  }

  /* Backpacks on the mudroom bench: ONE PER PACKING GROUP the household
     has for the day in focus, open while that group is still short. With
     no packing groups — no kits, or a day with nothing to carry — the
     bench falls back to what it always drew, one school bag per active
     child, and every one of those is closed.

     A bag is a kit group and not a child, because claims are filed against
     (outing, item) with no member read back: "1 of 2 packed" is sayable,
     "Maya's bottle is packed" is not, and the room does not pretend
     otherwise. Actual packing bags sit in front of the calendar bench
     and open the packing drawer; fallback school bags remain decor. */
  var bagKey = null;         /* the old count guard, widened: a rebuild now
                                also follows a pack flipping ready */
  /* the mudroom's own accents (sage, brass, oxblood, terracotta) plus
     one teal, the kitchen's, because the two rooms share a sightline */
  var BAG_COLORS = [0x8f4038, 0x3fbdb2, 0xb5713c, 0x7d968a];
  /* two on the cushion (top 0.75, bag half-height 0.23), two on the
     floor (0.03) either side of the bench */
  var BAG_SPOTS = [[-12.00, 0.98, 3.14], [-10.86, 0.98, 3.14],
                   [-12.32, 0.26, 3.66], [-9.30, 0.26, 3.62]];
  var PACK_SPOTS = [[-5.46, 0.40, 2.34], [-5.46, 0.40, 1.76],
                    [-5.46, 0.40, 1.18], [-5.46, 0.40, 0.60]];
  function syncMudroom(s) {
    if (!webgl) return;
    var m = s.mudroom || {};
    var packs = (m.packs || []).slice().sort(function (a, b) {
      return Number(!!b.attention) - Number(!!a.attention);
    }).slice(0, 4);
    var n = packs.length || Math.min(4, m.bags || 0);
    var key = packs.length
      ? packs.map(function (p) { return (p.ready ? 'r' : 'o') + (p.attention ? 'a' : 'q'); }).join('')
      : 'n' + n;
    if (key === bagKey) return;
    bagKey = key;
    while (webgl.mudBagsG.children.length) {
      var oldBag = webgl.mudBagsG.children[0];
      oldBag.traverse(function (o) {
        if (o.geometry && !o.geometry.userData.cached) o.geometry.dispose();
        if (o.material && !o.material.userData.shared) o.material.dispose();
      });
      webgl.mudBagsG.remove(oldBag);
    }
    for (var i = 0; i < n; i++) {
      /* no packing data = no claim about packing: a fallback bag is shut */
      var gaping = !!(packs[i] && !packs[i].ready);
      var bag;
      if (webgl.makeBag) {
        bag = webgl.makeBag(BAG_COLORS[i % 4], gaping);
      } else {                       /* the 2D-adjacent tiers keep a block */
        bag = new webgl.T.Group();
        var body = new webgl.T.Mesh(new webgl.T.BoxGeometry(0.34, 0.46, 0.26),
          new webgl.T.MeshLambertMaterial({ color: BAG_COLORS[i % 4] }));
        var flap = new webgl.T.Mesh(new webgl.T.BoxGeometry(0.36, 0.18, 0.28),
          new webgl.T.MeshLambertMaterial({ color: 0x3a3330 }));
        flap.position.set(0, gaping ? 0.30 : 0.17, gaping ? -0.16 : 0);
        if (gaping) flap.rotation.x = -1.72;
        bag.add(body); bag.add(flap);
      }
      var spot = packs.length ? PACK_SPOTS[i] : BAG_SPOTS[i];
      bag.position.set(spot[0], spot[1], spot[2]);
      bag.rotation.y = packs.length ? Math.PI / 2 : (i % 2 ? 0.22 : -0.18);
      bag.userData.room = packs.length ? 'kitchen' : 'mudroom';
      if (packs.length) {
        bag.scale.setScalar(1.6);
        bag.userData.houseAction = 'packing';
        bag.traverse(function (o) {
          o.userData.room = 'kitchen';
          if (!o.isMesh || !o.material || !o.material.emissive || !packs[i].attention) return;
          var material = o.material.userData.shared ? o.material.clone() : o.material;
          material.userData = { houseBagOwned: true };
          material.emissive.setHex(0xa65d13);
          material.emissiveIntensity = 0.35;
          o.material = material;
        });
      }
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
                        /* the garage's card hangs on the BACK WALL — the
                           surface the plaques vacated. Without a face named
                           here the zone framed its whole interior group and
                           the lean-in reversed out of the house to fit it */
                        garage: 'garageBackWall',
                        door: 'plaque' };   /* frame the CARD, not the slab —
                        the whole-door span forces a 15-unit approach that
                        lands outside the mudroom's walls */
  /* the door's card hangs on the GARAGE door on the west wall, whose face
     looks east along +x — the street door's ['z', 1] would approach it
     through the wall */
  var FACE_AXIS_MAP = { fridge: ['z', 1], board: ['x', 1], counter: ['z', 1],
                        pet: ['z', 1], radio: ['x', 1], door: ['x', 1] };
  /* How much of the approach a face actually needs. Every other zone's face
     IS its card — a calendar sheet, a cork board — so framing the whole
     mesh frames the card. The garage's is a five-and-a-half-unit WALL that
     the card only wears a band of, and framing all of it reverses the
     camera twenty units back, clean out of the house: the lean-in showed a
     doll's house with a notice over it instead of a garage with a list on
     the wall. 0.78 is the closest the eye can come and still stay behind a
     car parked on the apron (row one sits at z 13.4, tail near 15.4). */
  var FACE_DIST_MAP = { garage: 0.78,
    /* the study's desk sheets are small faces (a signature slip is a
       quarter of a unit across): frameZone's fixed 0.8 stand-off dominates
       and the card composed on them reads as a postage stamp. Closer, so
       the sheet fills a readable share of the frame; the camera still
       stands well above the desk. */
    study_tray: 0.7, study_contracts: 0.6 };

  /* the mesh a zone's card sits on: the kitchen's from the table above,
     a study zone's from the study itself (house_study.js `face`) */
  function faceMeshOf(key) {
    var m = FACE_MESH_MAP[key] && webgl[FACE_MESH_MAP[key]];
    if (!m && webgl.studyWorld && webgl.studyWorld.face) m = webgl.studyWorld.face(key);
    return m || null;
  }
  function zoneFaceNormal(key) {
    if (!webgl) return null;
    var fmesh = faceMeshOf(key);
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
    /* THE MIRROR (section 3.4): the table above names a HOUSE-LOCAL axis
       ("the garage door's face looks east"); on a mirrored plan that face
       looks west. The branch above needs no such help -- a world
       quaternion is already reflected. */
    return webgl.toWorld(v);
  }

  function frameZone(key, cb) {
    var g = webgl.groups[key];
    var fmesh = faceMeshOf(key);
    var boxb = new webgl.T.Box3().setFromObject(fmesh || g);
    var center = boxb.getCenter(new webgl.T.Vector3());
    var size3 = boxb.getSize(new webgl.T.Vector3());
    var span = Math.max(size3.x, size3.y, size3.z);
    var dist = (span / 2) / Math.tan((webgl.cam.fov / 2) * Math.PI / 180) * 1.45 + 0.8;
    dist *= (FACE_DIST_MAP[key] || 1);
    /* a zone with a card face is approached ALONG that face's normal (a
       touch of height mixed in so the room keeps its depth): an oblique
       wall card reads as a misaligned web element; a square one reads as
       part of the surface */
    /* THE MIRROR (section 3.4): zoneFaceNormal already hands back a WORLD
       normal -- the face-mesh branch reads a world quaternion, and its
       axis-table fallback reflects its own literal. `center` is a world
       Box3 read. So nothing here is flipped a second time. */
    var fn = zoneFaceNormal(key);
    var dir = fn
      ? fn.clone().add(new webgl.T.Vector3(0, 0.22, 0)).normalize()
      : new webgl.T.Vector3().subVectors(webgl.cam.position, center).normalize();
    /* a face that looks UP (the study's in-tray, its desk piles, its
       signature slips) would put the eye straight above it, where lookAt
       has no roll to choose and the room has no depth: lean the approach
       toward where the visitor already stands, ~63 degrees down -- still
       square enough that the pasted card reads flat on the sheet. */
    if (fn && Math.abs(fn.y) > 0.9) {
      var toward = new webgl.T.Vector3().subVectors(webgl.cam.position, center);
      toward.y = 0;
      if (toward.lengthSq() < 1e-6) toward.set(0, 0, 1);
      dir = fn.clone().add(toward.normalize().multiplyScalar(0.5)).normalize();
    }
    var toP = center.clone().add(dir.multiplyScalar(dist));
    toP.y = Math.max(toP.y, center.y + 0.6);
    tween = { fromP: webgl.cam.position.clone(), toP: toP,
              fromA: (lookAt || webgl.HOME_AT).clone(),
              toA: center, t0: performance.now(), ms: 650, cb: cb };
    requestFrame();
  }
  function goHome(name) {
    var room = roomsReg()[name || 'kitchen'];
    if (!room) return;
    webgl.cam.fov = room.fov || 24;
    webgl.cam.updateProjectionMatrix();
    /* A focused view steps back through its room before leaving the house.
       This is essential in the garage, where cars fill the close view. */
    /* THE MIRROR (section 3.4): room.pos/room.at are HOUSE-LOCAL (the mask
       solver below was built from exactly these five poses and must never
       see a flipped one); toWorld turns them into the camera's world pose
       at the tween, and returns a fresh vector, so the .clone() the tween
       used to take is already paid for. */
    webgl.solveShell(room.pos, { box: room.aabb, room:name || 'kitchen' });
    webgl.aimShadow(name || 'kitchen');
    tween = { fromP: webgl.cam.position.clone(), toP: webgl.toWorld(room.pos),
              fromA: (lookAt || webgl.toWorld(room.at)).clone(),
              toA: webgl.toWorld(room.at),
              t0: performance.now(), ms: 650, cb: null };
    focused = null;
    TIP.style.opacity = 0;
    announceFocus(null);
    updateBack();
    scheduleHint();
    requestFrame();
  }
  /* ---- ROOMS: every room is a camera home, and carries the AABB
     (built once, at buildRoom time — see the SHELL comment beside
     stampHouse) the solver treats as "the room" while the camera settles
     inside it. Zone keys map to the room that owns them; unmapped zones
     belong to the kitchen. The hide: arrays this registry used to carry
     are gone — solveShell (spec section 4) owns SHELL visibility now. */
  function roomsReg() {
    var rooms = {
      kitchen: { pos: webgl.HOME_POS, at: webgl.HOME_AT,
                 aabb: webgl.ROOM_AABB.kitchen },
      garage:  { pos: webgl.GARAGE_POS, at: webgl.GARAGE_AT,
                 aabb: webgl.ROOM_AABB.garage },
      mudroom: { pos: webgl.MUD_POS, at: webgl.MUD_AT,
                 aabb: webgl.ROOM_AABB.mudroom },
      living:  { pos: webgl.LIV_POS, at: webgl.LIV_AT, fov: 36,
                 aabb: webgl.ROOM_AABB.living },
      study:   { pos: webgl.STUDY_POS, at: webgl.STUDY_AT, fov: 36,
                 aabb: webgl.ROOM_AABB.study }
    };
    return rooms;
  }
  var ZONE_ROOM = { garage: 'garage', curb: null,
                    door: 'mudroom', radio: 'living', pet: 'living' };
  Object.keys(STUDY_ZONE_META).forEach(function (key) { ZONE_ROOM[key] = 'study'; });
  function zoneRoom(key) {
    var r = ZONE_ROOM[key];
    return r === undefined ? 'kitchen' : r;
  }
  function enterRoom(name, cb) {
    var rooms = roomsReg();
    var room = rooms[name];
    if (!room) { if (cb) cb(); return; }
    if (mode === name) { if (cb) cb(); return; }
    /* A zone's card belongs to the room it hangs in. Walking to another room
       while one is worn left it mounted and visible over the new room until
       the next lean-in — goExterior always dropped focus, this path never
       did. chfKitchenFocus re-announces in its own callback, so clearing
       here costs it nothing. */
    if (focused) {
      focused = null;
      TIP.style.opacity = 0;
      announceFocus(null);
    }
    mode = name;
    if (webgl.studyWorld) {
      webgl.studyWorld.group.visible = name === 'study';
      if (webgl.studyWorld.architecture) webgl.studyWorld.architecture.visible = name === 'study';
      if (webgl.studyWorld.proxies) webgl.studyWorld.proxies.visible = name === 'study';
    }
    webgl.cam.fov = room.fov || 24;
    webgl.cam.updateProjectionMatrix();
    updateBack();
    scheduleHint();
    /* spec section 4: solve against the DESTINATION at tween start (you
       fly through an outline, never a wall) — replaces the show-all-
       then-hide dance that used to run here. */
    webgl.solveShell(room.pos, { box: room.aabb, room:name });
    webgl.aimShadow(name);        /* the sun's shadow box follows the camera */
    syncScenery();                /* inside a room the set dressing steps back */
    /* THE MIRROR (section 3.4): same boundary as goHome -- solveShell got
       the house-local pose above, the camera gets the world one here. */
    tween = { fromP: webgl.cam.position.clone(), toP: webgl.toWorld(room.pos),
              fromA: (lookAt || webgl.EXT_AT).clone(),
              toA: webgl.toWorld(room.at),
              t0: performance.now(), ms: 850, cb: cb || null };
    requestFrame();
  }
  function goExterior() {
    if (mode === 'study' && window.chfHouseEndParent) window.chfHouseEndParent();
    mode = 'exterior';
    if (webgl.studyWorld) {
      webgl.studyWorld.group.visible = false;
      if (webgl.studyWorld.architecture) webgl.studyWorld.architecture.visible = false;
      if (webgl.studyWorld.proxies) webgl.studyWorld.proxies.visible = false;
    }
    webgl.cam.fov = exteriorFov(webgl.cam.aspect);
    webgl.cam.updateProjectionMatrix();
    focused = null;
    updateBack();
    scheduleHint();
    TIP.style.opacity = 0;
    /* spec section 4: the sealed house — every piece solid, destination
       subject null, solved before the tween exactly like enterRoom. */
    webgl.solveShell(webgl.EXT_POS, null);
    announceFocus(null);
    webgl.aimShadow('exterior');  /* the whole property, for the one view
                                     that can see the whole property */
    syncScenery();                /* ... and out here nothing recedes */
    tween = { fromP: webgl.cam.position.clone(), toP: webgl.EXT_POS.clone(),
              fromA: (lookAt || webgl.toWorld(webgl.HOME_AT)).clone(),
              toA: webgl.EXT_AT.clone(),
              t0: performance.now(), ms: 850, cb: null };
    requestFrame();
  }
  /* ---- ORBIT (massing arc 1, spec section 4) ---------------------------
     Eight stops, one tween per step, through the SAME tween slot and the
     same easing goExterior uses — so render-on-demand is untouched: the
     scene renders while the tween runs and idles the moment it lands.
     Interiors ignore all of it (rooms are fixed dioramas); the back
     control exits to whichever stop you left from, which falls out of
     webgl.EXT_POS/EXT_AT reporting the current stop. */
  function orbitStop() { return webgl ? webgl.ORBIT.stop : 0; }
  function orbitTo(k, cb) {
    if (!webgl || mode !== 'exterior') return false;
    k = Math.round(k);
    /* chfOrbitTo('x') / chfOrbitTo(undefined) must not write NaN into
       ORBIT.stop -- NaN survives ((NaN % 8) + 8) % 8 and poisons every
       later orbitPos()/orbitStep() read. Refuse it the way a wrong mode
       is refused. */
    if (!isFinite(k)) return false;
    k = ((k % 8) + 8) % 8;
    webgl.ORBIT.stop = k;
    var to = webgl.orbitPos(k);
    /* the sealed house at every stop: subject null, every piece solid,
       solved once BEFORE the tween exactly as goExterior does. */
    webgl.solveShell(to, null);
    /* the markers are derived from the camera, so they cannot survive the
       move: drop them now, and arm the deferred redraw from the tween's
       OWN callback rather than beside it. scheduleHint's timer is wall
       clock and showHint refuses to draw mid-tween without rescheduling,
       so on a slow tier — a Pi, or software WebGL, where one frame of
       this scene costs seconds — a timer armed here fires while the tween
       is still live and that stop silently draws no markers at all.
       Armed at the landing, the delay is the delay it means. */
    hideHint();
    /* THE MIRROR (section 3.4): EXT_AT is the pivot in WORLD space (the
       raw ORBIT.pivot is house-local, like every other authored point). */
    tween = { fromP: webgl.cam.position.clone(), toP: to,
              fromA: (lookAt || webgl.EXT_AT).clone(),
              toA: webgl.EXT_AT.clone(),
              t0: performance.now(), ms: 850,
              cb: function () { aimCarPlates(); scheduleHint();
                                if (cb) cb(); } };
    requestFrame();
    /* the one thing outside this file that has to know the ring moved:
       the panel's idle return, which snaps the wall back to stop 0. */
    try {
      window.dispatchEvent(new CustomEvent('chf-house-orbit',
                                           { detail: { stop: k } }));
    } catch (e) { /* an ancient browser without CustomEvent just orbits */ }
    return true;
  }
  function orbitStep(d) { return orbitTo(orbitStop() + d); }
  function updateOrbitControls() {
    for (var i = 0; i < ORBIT_BTNS.length; i++)
      ORBIT_BTNS[i].hidden = mode !== 'exterior';
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
     spec's "sky and flat yard stay a view" holds for the planting too.
     The grass ground slab is the one exception to "yard means yardG":
     it is built in extG, before yardG exists, and cannot move into
     yardG without vanishing along with the rest of the yard's decor
     when a room view hides it -- so it stamps its own
     userData.yard instead, checked here alongside the yardG ancestry
     walk (facade spec, the garage exit-tap ruling). */
  function inYard(obj) {
    var o = obj;
    while (o) {
      if (o === webgl.yardG || (o.userData && o.userData.yard)) return true;
      o = o.parent;
    }
    return false;
  }
  /* SHELL (spec section 5): the vendored raycaster (Ou, three.min.js) never
     checks .visible itself — every mesh under a ghosted (solveShell
     verdict 'ghost', .visible=false) fabric group is still fully solid to
     a ray, exactly as solid as a mesh that IS rendered. zoneAt's own loop
     already accounts for this by walking every hit in distance order
     until one resolves to a zone tag, silently stepping past a ghosted
     wall that carries none — "ghosted fills are tag-transparent in the
     hit walk" (arc ledger) describes THAT behavior, not raycaster
     support. A single-hit reader has no such loop, so it would take the
     ghosted wall itself as the answer the moment one sits nearer than
     the room's real fabric behind it — which happens for exactly the
     camera/room pairs solveShell ghosts things for, i.e. every room but
     the sealed exterior. Skips to the first hit that is actually
     visible (every ancestor's own .visible true), matching what the
     eye sees rather than what merely blocks a ray. */
  function anyHit(clientX, clientY) {
    var rect = webgl.R.domElement.getBoundingClientRect();
    var v = new webgl.T.Vector2(((clientX - rect.left) / rect.width) * 2 - 1,
                                -((clientY - rect.top) / rect.height) * 2 + 1);
    var ray = new webgl.T.Raycaster();
    ray.setFromCamera(v, webgl.cam);
    var hits = ray.intersectObjects(webgl.scene.children, true);
    for (var i = 0; i < hits.length; i++) {
      var o = hits[i].object, vis = true;
      for (var p = o; p; p = p.parent) if (p.visible === false) { vis = false; break; }
      if (vis) return o;
    }
    return null;
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
    var fm = faceMeshOf(key);
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
        /* SHELL (spec section 4): the lean-in solve's subject point, in
           WORLD space — unlike quad/rect above (screen pixels + NDC
           depth, useless for a half-space test against a fabric piece's
           world-space AABB centre). A PlaneGeometry sits centred on its
           own local origin, so the four local corners [-pw,ph], [pw,ph],
           [pw,-ph], [-pw,-ph] already average to (0,0,0) before any
           transform — the plane's world position IS their centroid,
           with no need to transform and re-average all four. */
        return { rect: rect, quad: [ptop[0], ptop[1], pbot[1], pbot[0]],
                 centre: fm.getWorldPosition(new webgl.T.Vector3()) };
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
    /* the WORLD-space centre of this same face (see the fm branch's own
       comment above) — the box's centre on the two free axes, pinned to
       the chosen face on the third, exactly where the quad below sits. */
    var centre = new webgl.T.Vector3();
    centre[axis] = fixed;
    centre[A[0]] = (b.min[A[0]] + b.max[A[0]]) / 2;
    centre[A[1]] = (b.min[A[1]] + b.max[A[1]]) / 2;
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
    if (bad) return { rect: rect, quad: null, centre: centre };
    /* order in SCREEN space: the top pair then the bottom pair, left first */
    quad.sort(function (a, b2) { return a.y - b2.y; });
    var top = quad.slice(0, 2).sort(function (a, b2) { return a.x - b2.x; });
    var bot = quad.slice(2, 4).sort(function (a, b2) { return a.x - b2.x; });
    return { rect: rect, quad: [top[0], top[1], bot[1], bot[0]], centre: centre };
  }

  /* SHELL (spec section 4): the lean-in's own solve, shared by both paths
     that can land a camera on a zone (chfKitchenFocus and onTap's direct
     zone tap, just below) — one solver, no per-zone authored ghost
     lists. Called from frameZone's OWN settle callback, never before:
     zoneFaceQuad's non-fm branch picks its face by which side of the box
     the CAMERA currently sits on (`toCam`), so calling this before
     frameZone's tween moves the camera would read the ROOM-level
     position instead of the zone's close-in one and could pick the
     wrong face. The room-level solve enterRoom already ran (before that
     tween started) covers everything up to this point; this refines it
     for the close-up view. */
  function solveLeanIn(key) {
    var shape = zoneFaceQuad(key);
    if (shape && shape.centre) webgl.solveShell(webgl.cam.position,
                                                { point: shape.centre, room:mode });
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
      updateBack();
      announceFocus(null);
      frameZone(key, function () { announceFocus(key); solveLeanIn(key); });
    });
  };
  window.chfHouseVisit = function (key, room) {
    if (!webgl) return;
    hideHint();
    if (room === 'study') { window.dispatchEvent(new CustomEvent('chf-house-open', {detail:'study'})); return; }
    enterRoom(room, null);
    if (ZONES[key]) {
      focused = key; updateBack(); announceFocus(null);
      frameZone(key, function () { announceFocus(key); solveLeanIn(key); });
      return;
    }
    var entry = world && world.entries.find(function(e){return e.action === key;});
    if (!entry) return;
    var box = new webgl.T.Box3().setFromObject(entry.group), center = box.getCenter(new webgl.T.Vector3());
    var direction = webgl.toWorld(roomsReg()[room].pos).sub(center).normalize();
    var distance = Math.max(5, box.getSize(new webgl.T.Vector3()).length()*2.5);
    tween = {fromP:webgl.cam.position.clone(),toP:center.clone().add(direction.multiplyScalar(distance)),
      fromA:(lookAt || webgl.EXT_AT).clone(),toA:center,t0:performance.now(),ms:650,
      cb:function(){webgl.solveShell(webgl.cam.position,{point:center,room:room});scheduleHint();}};
    requestFrame();
  };
  window.chfHouseEnter = function () { if (webgl) enterRoom('kitchen', null); };
  window.chfHouseEnterGarage = function () { if (webgl) enterRoom('garage', null); };
  window.chfHouseEnterRoom = function (name) { if (webgl) enterRoom(name, null); };
  window.chfHouseExit = function () { if (webgl) goExterior(); };
  window.chfHouseUnlockStudy = function () {
    if (!webgl || !webgl.studyWorld) return Promise.resolve(false);
    var visit = window.chfHouseParent && window.chfHouseParent();
    if (!visit) return Promise.resolve(false);
    return fetch(BASE + 'api/study/state', {
      credentials:'same-origin', headers:{'X-Member-Token':visit.token}
    }).then(function (response) {
      if (!response.ok) throw new Error('http ' + response.status);
      return response.json();
    }).then(function (payload) {
      studyFurniture = payload.furniture || {};
      webgl.studyWorld.update(studyFurniture);
      if (state) applyState(state);
      enterRoom('study', null);
      return true;
    }).catch(function () {
      if (window.chfHouseEndParent) window.chfHouseEndParent();
      if (window.showGlobalAlert)
        showGlobalAlert('Could not open the Study. Check the connection and try again.');
      return false;
    });
  };
  /* read-only, the chfHouseScenery stance: reports, never moves */
  window.chfHouseMode = function () { return mode; };
  window.chfNeighborhood = function () { return webgl && webgl.neighborhood ? webgl.neighborhood.stats() : null; };
  /* ORBIT (spec section 4). chfOrbitStop reports; chfOrbitTo/chfOrbitStep
     move the eye and nothing else — the same read-only-about-the-house
     stance chfHouseCam takes. Both return false inside a room. */
  window.chfOrbitStop = function () { return orbitStop(); };
  window.chfOrbitTo = function (k, cb) { return orbitTo(k, cb); };
  window.chfOrbitStep = function (d) { return orbitStep(d); };
  /* the studio's viewfinder: snap the camera anywhere and repaint once.
     Read-only like its siblings — it moves the eye, nothing else. Set
     builders frame a room through this before they hard-code the pose. */
  /* the scenery knob at runtime. Read-only like chfHouseCam: it changes
     how the room LOOKS and never what it knows. The future reveal-on-
     demand control is this call with a bigger k and nothing else. Returns
     the stats the studio tunes against: how many meshes, how many distinct
     materials, and how many of those actually needed a clone. */
  window.chfHouseScenery = function (k) {
    if (!webgl) return null;
    SCENERY = Math.max(0, Math.min(1, isFinite(parseFloat(k))
                                      ? parseFloat(k) : SCENERY));
    var stats = syncScenery();
    requestFrame();
    if (stats) stats.knob = SCENERY;   /* `applied` is the EFFECTIVE value:
         the exterior always reports 0, however the knob is set */
    return stats;
  };
  window.chfHouseCam = function (px, py, pz, ax, ay, az) {
    if (!webgl) return;
    tween = null;
    webgl.cam.position.set(px, py, pz);
    lookAt = new webgl.T.Vector3(ax, ay, az);
    webgl.cam.lookAt(lookAt);
    requestFrame();
  };
  /* SHELL (shell spec section 3): debug/test hook, read-only like its
     siblings above — reports the registry, changes nothing. FABRIC
     itself lives inside buildRoom()'s closure (beside westWallG etc.),
     so it rides out on the same returned webgl object the other groups
     already use to reach this outer scope. edgesVisible is null
     for a piece with no edges object built at all (the yard, a late
     row, or a merge-empty piece — see the build step's own
     comment); retained edge geometry reports false, proving that
     cutaways do not draw permanent wireframes. */
  /* MASSING ARC 1 (spec section 3): what the two block roofs were
     actually BUILT from, after window.HOUSE_ROOF_FORMS had its say --
     read-only, like chfShellFabric below. Spec 2's block model feeds
     the same rows, so a later arc can pin what it asked for against
     what was built without reading the source. */
  window.chfRoofForms = function () {
    return webgl ? webgl.ROOF_FORMS : null;
  };
  /* BLOCKS (spec 2026-09-17 section 0): which registered roof piece stands
     where each canonical one stood, after form and ridge had their say --
     read-only like chfRoofForms above. A test reads it to follow a marker
     across a ridge setting without reading the source. */
  window.chfRoofAlias = function () {
    return webgl ? webgl.ROOF_ALIAS : null;
  };
  window.chfShellFabric = function () {
    if (!webgl) return [];
    return webgl.FABRIC.map(function (f) {
      var interiorGlow = null;
      f.g.traverse(function (m) {
        if (m.userData && m.userData.interiorWindow && m.material)
          interiorGlow = m.material.emissiveIntensity;
      });
      return { name: f.name, visible: f.g.visible,
               room: f.g.userData.room || null, normal: f.n.toArray(), box: f.box,
               kit: !!f.kit,
               n: [f.n.x, f.n.y, f.n.z], /* arc 4 (facade spec §6): the AO
                    derivation's own wall-like test, |n.y| < 0.5, reads
                    this same shape from FABRIC -- exposed here too so the
                    test can assert against exactly what the derivation saw */
               verdict: f.verdict, interiorGlow: interiorGlow,
               /* VIEW-VOLUME MASKING (task 3, spec section 5): the
                  surface area of the piece's original faces the mask
                  removed in each room's view, over its original area --
                  0 untouched, 1 masked whole. `verdict` above is
                  'masked' when the CURRENT view's fraction is > 0 and
                  'solid' otherwise (the exterior: all solid). */
               maskedFraction: maskedFractionOf(f),
               edgesVisible: f.edges ? f.edges.visible : null };
    });
  };
  function maskedFractionOf(f) {
    var out = {};
    Object.keys(webgl.ROOM_MASKS).forEach(function (r) {
      out[r] = f.shells && f.shells[r] ? f.shells[r].fraction : 0;
    });
    return out;
  }
  /* VIEW-VOLUME MASKING (task 3): read-only like chfShellFabric --
     which room shell is visible right now (null: none, the exterior). */
  window.chfRoomShellShown = function () {
    if (!webgl) return null;
    var r = null;
    Object.keys(webgl.roomShellGroups).forEach(function (k) {
      if (webgl.roomShellGroups[k].visible) r = k;
    });
    return r;
  };
  /* MASSING ARC 2 task 7 (spec section 3.2): which fabric rows the mask
     CUT for `room` -- every row whose per-room shell records a removed
     fraction, which is buildRoomShells()'s own record of a cut (a row it
     left whole gets fraction 0). Names only, sorted; read-only. */
  window.chfRoomShellCut = function (room) {
    if (!webgl || !webgl.ROOM_MASKS[room]) return null;
    var out = [];
    webgl.FABRIC.forEach(function (f) {
      var sh = f.shells && f.shells[room];
      if (sh && sh.fraction > 1e-6) out.push(f.name);
    });
    return out.sort();
  };
  /* ... and which rows that view draws NOTHING of: a kit the mask took
     whole (buildRoomShells records `{group: null, fraction: 1}` for one),
     a roof feature dropped under ruling 1, the yard, or a convex mesh
     the clip emptied. `cut` above is the superset; this is the part of it
     that is gone rather than opened, which is the only way to ask "did
     the window go with its wall?" -- a kit is never clipped, so it has no
     remnant to look for. Names only, sorted; read-only. */
  window.chfRoomShellDropped = function (room) {
    if (!webgl || !webgl.ROOM_MASKS[room]) return null;
    var out = [];
    webgl.FABRIC.forEach(function (f) {
      var sh = f.shells && f.shells[room];
      if (sh && sh.fraction >= 1 - 1e-6) out.push(f.name);
    });
    return out.sort();
  };
  /* MASSING ARC 2 task 7: is the upper story out of this room's way? A
     ray from the room camera to its look-at target against ONLY the
     upper-story rows, and only against what that view actually DRAWS of
     them: the source meshes solveShell left visible, plus the room
     shell's own remnants. Anything the ray meets before it reaches the
     target is a piece standing between the camera and the room -- which
     is exactly what the mask exists to remove. */
  window.chfRoomViewClear = function (room) {
    if (!webgl || !webgl.ROOM_CAMS[room]) return null;
    /* THE MIRROR (spec 2026-09-17 section 3.4): this hook casts a ray
       from ROOM_CAMS[room], which is HOUSE-LOCAL by design (the masks
       were built from exactly those five poses), into the WORLD graph.
       On a mirrored plan those two spaces disagree and the answer would
       be a confident lie about the far side of the house. It reports
       nothing rather than something false; the mask itself is unaffected,
       because it never left house-local space. */
    if (webgl.MIRROR) return null;
    var cam = webgl.ROOM_CAMS[room].clone(), at = webgl.ROOM_AT[room].clone();
    var far = cam.distanceTo(at);
    var ray = new webgl.T.Raycaster(cam, at.clone().sub(cam).normalize());
    var upper = [], owner = {};
    function drawn(o) {
      for (var p = o; p; p = p.parent) if (!p.visible) return false;
      return true;
    }
    function collect(root, label) {
      if (!root) return;
      root.updateMatrixWorld(true);
      root.traverse(function (m) {
        if (!m.isMesh || m.isInstancedMesh || !drawn(m)) return;
        upper.push(m); owner[m.id] = label;
      });
    }
    webgl.FABRIC.forEach(function (f) {
      if (f.name.indexOf('_upper_') < 0) return;
      collect(f.g, f.name);
      var sh = f.shells && f.shells[room];
      if (sh && sh.group) collect(sh.group, f.name + ':remnant');
    });
    var hits = ray.intersectObjects(upper, false).filter(function (h) {
      return h.distance < far;
    });
    return { clear: hits.length === 0, blocked: hits.map(function (h) {
      return owner[h.object.id] || h.object.name || 'mesh';
    }) };
  };
  /* the room's mask: the pyramid planes P, the wedge planes W (raw --
     meshMask moves a W plane per straddling mesh at cut time, always
     deeper into the box, so everything a shell keeps is on the kept
     side of these too), the roof-high bounded box, the camera */
  window.chfRoomMask = function (room) {
    if (!webgl || !webgl.ROOM_MASKS[room]) return null;
    var m = webgl.ROOM_MASKS[room];
    return { P: m.P.map(function (pl) { return { n: pl.n.slice(), d: pl.d }; }),
             W: m.W.map(function (pl) { return { n: pl.n.slice(), d: pl.d }; }),
             box: m.box.slice(), cam: m.cam.slice() };
  };
  /* samples up to n vertices of the room shell's meshes (world space)
     and counts those the mask says are masked -- a kept vertex inside
     the mask is a leak. Vertices ON a mask plane (|side| < 1e-3: every
     clipped edge and every cap lies on one) are skipped, since a cap
     vertex sits exactly on the boundary between kept and masked and
     rounds either way. */
  /* RULING 2 (fix round 1): up to n world-space vertices of ONE piece's
     remnants in a room shell (the mirrored row group carries shellOf),
     so a test can pin the straddle rule directly: none of the near
     wall's kept vertices may lie inside P behind the box's near face. */
  window.chfRoomShellVerts = function (room, piece, n) {
    if (!webgl || !webgl.roomShellGroups[room]) return null;
    var verts = [], v = new webgl.T.Vector3();
    webgl.roomShellGroups[room].updateMatrixWorld(true);
    webgl.roomShellGroups[room].traverse(function (o) {
      if (!o.isMesh || !o.geometry) return;
      var mine = false;
      for (var q = o; q; q = q.parent) if (q.userData && q.userData.shellOf === piece) { mine = true; break; }
      if (!mine) return;
      var p = o.geometry.getAttribute('position');
      for (var i = 0; i < p.count; i++) {
        v.fromBufferAttribute(p, i).applyMatrix4(o.matrixWorld);
        verts.push([v.x, v.y, v.z]);
      }
    });
    var step = Math.max(1, Math.floor(verts.length / (n || 2000))), out = [];
    for (var k = 0; k < verts.length; k += step) out.push(verts[k]);
    return out;
  };
  /* fix round 1: the swap's own audit -- how many toggled objects are in
     the WRONG state for the view: a source (maskPattern) still visible in
     a room its pattern names, a stand-in (maskOnly) visible anywhere but
     its rooms, or, at the exterior (room null), any source hidden or any
     stand-in shown. 0 is the only right answer. */
  window.chfMaskLeak = function (room) {
    if (!webgl) return null;
    var tag = room ? '|' + room + '|' : null, bad = 0;
    /* walks the fabric groups themselves, NOT MASK_TOGGLES: an object
       the collection missed is exactly the bug this audit exists for */
    webgl.FABRIC.forEach(function (f) {
      f.g.traverse(function (o) {
        var ud = o.userData;
        if (!ud || !(ud.maskPattern || ud.maskOnly)) return;
        var want = ud.maskOnly ? (!!tag && ud.maskOnly.indexOf(tag) >= 0)
                               : (!tag || ud.maskPattern.indexOf(tag) < 0);
        if (o.visible !== want) bad++;
      });
    });
    return bad;
  };
  window.chfRoomShellLeak = function (room, n) {
    if (!webgl || !webgl.roomShellGroups[room]) return null;
    var m = webgl.ROOM_MASKS[room], C = window.HouseClip;
    var verts = [], v = new webgl.T.Vector3();
    webgl.roomShellGroups[room].updateMatrixWorld(true);
    webgl.roomShellGroups[room].traverse(function (o) {
      if (!o.isMesh || !o.geometry) return;
      var p = o.geometry.getAttribute('position');
      for (var i = 0; i < p.count; i++) {
        v.fromBufferAttribute(p, i).applyMatrix4(o.matrixWorld);
        verts.push([v.x, v.y, v.z]);
      }
    });
    var step = Math.max(1, Math.floor(verts.length / (n || 2000))), bad = 0;
    function onPlane(pl, p) {
      return Math.abs(pl.n[0]*p[0] + pl.n[1]*p[1] + pl.n[2]*p[2] - pl.d) < 1e-3;
    }
    for (var k = 0; k < verts.length; k += step) {
      var p = verts[k], skip = false;
      for (var a = 0; a < m.P.length && !skip; a++) if (onPlane(m.P[a], p)) skip = true;
      for (var b = 0; b < m.W.length && !skip; b++) if (onPlane(m.W[b], p)) skip = true;
      if (!skip && C.pointMasked(p, m)) bad++;
    }
    return bad;
  };
  /* VIEW-VOLUME MASKING (task 2, corrected): read-only like
     chfShellFabric above -- reads the `convexity` each row already
     carries (scanned once at regFabric()/refabConvexity() time, not
     from a live traversal here). A live traversal at READ time would
     count whatever mergeStatic already fused the row's boxes into (a
     window's frame boxes, several wall slabs -- non-convex composites
     even though every source mesh was convex), which is not the
     population Task 3's buildRoomShells() actually clips; scanning at
     registration is also the only way to see house_features.js's door
     fixtures at all, since they register after buildRoom()'s own merge
     loop has already run and finished. A non-kit row is safe for Task
     3's per-mesh clip when every one of its meshes is either convex or
     a recognized non-box primitive (see `nonconvex`); a kit row is kept
     or dropped whole regardless. */
  window.chfFabricConvexity = function () {
    if (!webgl) return [];
    return webgl.FABRIC.map(function (f) {
      var c = f.convexity || { meshes: 0, convex: 0, nonconvex: [] };
      return { name: f.name, meshes: c.meshes, convex: c.convex,
               kit: !!f.kit, nonconvex: c.nonconvex.slice() };
    });
  };
  /* SHELL/arc 4 (facade spec §6): read-only like chfShellFabric above --
     reports the AO occluder list buildRoom() already derived from the
     registry, changes nothing. Sliced so a test mutating the result
     cannot touch the live array. */
  window.chfAoOccluders = function () {
    return webgl && webgl.AO_OCCLUDERS ? webgl.AO_OCCLUDERS.map(function (b) { return b.slice(); }) : [];
  };
  /* VAULTED PARTITIONS (2026-09-16): read-only, like chfShellFabric
     above -- fires ONE raycast against the registered fabric and reports
     the nearest piece it hits. A registered piece's box says only that
     the group grew somewhere; it cannot say whether there is plaster
     above a particular door, or between a wall head and a roof deck, and
     that is the whole of what this arc had to fix. Nothing is cached and
     nothing is mutated; the raycast reads the same build-time geometry
     solveShell already reads. */
  window.chfRayFabric = function (from, dir) {
    if (!webgl || !webgl.FABRIC) return null;
    var T3 = webgl.T;
    var rc = new T3.Raycaster(
      new T3.Vector3(from[0], from[1], from[2]),
      new T3.Vector3(dir[0], dir[1], dir[2]).normalize(), 0.01, 400);
    var best = null;
    webgl.FABRIC.forEach(function (f) {
      var hits = rc.intersectObject(f.g, true);
      if (!hits.length) return;
      if (!best || hits[0].distance < best.distance)
        best = { name: f.name, distance: hits[0].distance,
                 point: hits[0].point.toArray() };
    });
    return best;
  };
  /* Massing arc 1 (task 1): read-only like chfShellFabric above -- reports
     the study's own world bounding box, changes nothing. Unions the
     furniture root, the house-scale architecture (walls/wainscot, built
     directly off NORTH/SOUTH/EAST/WEST in house_study.js), and the zone
     proxies -- three separate top-level scene children, so no single
     Box3.setFromObject call reaches all of them. Walks visibility
     manually rather than delegating to Box3.expandByObject's own
     recursion: house_study.js parents the StudyFactory's standalone-page
     shell under the furniture root and turns it invisible
     (`built.shell.visible = false`), and Box3 does not consult .visible,
     so a plain setFromObject on the root pulls in that hidden shell's
     17x17 floor plate -- authored for the standalone /study page, wider
     than this room -- and reports a box the size of THAT page, not the
     one actually on screen here. */
  window.chfStudyBox = function () {
    if (!webgl || !webgl.studyWorld) return null;
    var sw = webgl.studyWorld, box = new webgl.T.Box3(), any = false;
    function walk(o) {
      if (!o.visible) return;
      if (o.isMesh && o.geometry) {
        if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
        box.union(o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld));
        any = true;
      }
      (o.children || []).forEach(walk);
    }
    [sw.group, sw.architecture, sw.proxies].forEach(function (o) {
      if (!o) return;
      o.updateWorldMatrix(true, false);
      walk(o);
    });
    return any ? [box.min.x, box.max.x, box.min.y, box.max.y, box.min.z, box.max.z] : null;
  };
  /* STUDY REFIT (2026-09-16): read-only, like chfStudyBox above -- the
     world box of ONE of the study's zone proxies, so a test can pin
     which wall a study signal actually hangs on. The proxy is the union
     of that zone's real meshes (house_study.js builds it that way), so
     this reads the scene rather than a constant the scene also reads. */
  window.chfStudyZone = function (key) {
    var sw = webgl && webgl.studyWorld;
    var g = sw && sw.zones ? sw.zones[key] : null;
    if (!g) return null;
    g.updateWorldMatrix(true, true);
    var b = new webgl.T.Box3().setFromObject(g);
    return b.isEmpty() ? null
      : [b.min.x, b.max.x, b.min.y, b.max.y, b.min.z, b.max.z];
  };
  /* STUDY LEAN-IN (2026-09-22): read-only, like the two above. chfStudyCard
     is what the focus overlay draws a study zone's card FROM -- rows built
     off the furniture this page fetched with the parent's own token, never
     off the wall-readable board payload, so a study card can only exist on
     a page that already unlocked the study; leaving it empties the
     furniture (see the BACK/Escape handlers) and the card with it.
     chfStudyDetail reports one zone's painted-detail state for a test. */
  window.chfStudyCard = function (key) {
    var sw = webgl && webgl.studyWorld;
    return sw && sw.card ? sw.card(key) : null;
  };
  window.chfStudyDetail = function (key) {
    var sw = webgl && webgl.studyWorld;
    var out = sw && sw.detailState ? sw.detailState(key) : null;
    if (out && sw.graphDraws) out.graphDraws = sw.graphDraws();
    /* `facing`: how square the eye is to the zone's face right now (1 =
       dead on), so a test can pin the face-on convention */
    var f = out && sw.face ? sw.face(key) : null;
    if (out && f) {
      var n = new webgl.T.Vector3(0, 0, 1)
        .applyQuaternion(f.getWorldQuaternion(new webgl.T.Quaternion()));
      out.facing = -n.dot(webgl.cam.getWorldDirection(new webgl.T.Vector3()));
    }
    return out;
  };
  /* FACADE/arc 4 (facade spec section 6, "hand path parity"): read-only
     like the two above -- the spec the scene was actually built from and
     the slot table it derived from the envelope. The live pin test reads
     both and asserts them against services/house_facade.py, which is
     what keeps the JS and Python slot tables from ever drifting. */
  window.chfFacade = function () { return webgl ? webgl.SPEC : null; };
  /* MASSING ARC 2 + 2b: the VERSION-3 block/upper model the scene was
     built from. Read-only, like chfFacade. */
  window.chfBlocks = function () { return webgl ? webgl.BLOCKS : null; };
  /* ---- THE MIRROR (spec 2026-09-17 section 3.4): read-only hooks, the
     chfBlocks stance -- they report, they never move anything.

     chfMirror     whether this plan is reflected, what the root carries,
                   how many text meshes stand counter-flipped, and the two
                   determinants that say so geometrically.
     chfCamPose    where the eye actually is, in world space.
     chfWorldBox   a registered piece's (or a zone group's) box AFTER the
                   reflection: a live Box3 over the real graph, which is
                   the only honest way to ask which side of the world a
                   thing ended up on. FABRIC's own f.box is house-local
                   and deliberately stays that way.
     chfPlaqueCanvas / chfPlaqueRect
                   the i-th car plaque's painted canvas and where it lands
                   on screen, so a test can prove the lettering reads
                   FORWARD rather than merely present. */
  window.chfMirror = function () {
    if (!webgl) return null;
    /* textDet / fabricDet: the determinant of a world matrix is negative
       exactly when that mesh is being drawn through a reflection, which
       is what turns lettering into its own mirror image. So a mirrored
       house must report fabricDet < 0 (the house IS reflected) and
       textDet > 0 (every lettered mesh is not) -- the geometric statement
       of "the words read forward", with no pixels involved. */
    var textDet = null, fabricDet = null;
    webgl.houseRoot.updateMatrixWorld(true);
    webgl.houseRoot.traverse(function (m) {
      if (!m.isMesh) return;
      var d = m.matrixWorld.determinant();
      if (m.userData && m.userData.noMirror)
        textDet = textDet === null ? d : Math.min(textDet, d);
      else if (fabricDet === null || d > fabricDet) fabricDet = d;
    });
    /* the STUDY reported separately: its lettered panels are stamped in
       study.js (which is built before `webgl` exists and cannot call
       textMesh) and they join houseRoot AFTER the root pass, so they are
       the one set that could silently miss the counter-flip. A test that
       only read the whole-house minimum could not tell a mirrored study
       from a study with no panels built yet. */
    var sCount = 0, sDet = null;
    var study = webgl.studyWorld;
    if (study) [study.group, study.architecture, study.proxies]
      .forEach(function (g) {
        if (!g) return;
        g.updateMatrixWorld(true);
        g.traverse(function (m) {
          if (!m.isMesh || !m.userData || !m.userData.noMirror) return;
          sCount++;
          var d = m.matrixWorld.determinant();
          sDet = sDet === null ? d : Math.min(sDet, d);
        });
      });
    return { mirror: !!webgl.MIRROR, root: webgl.houseRoot.scale.x,
             noMirrorCount: webgl.noMirrorCount(),
             textDet: textDet, fabricDet: fabricDet,
             study: { count: sCount, minDet: sDet } };
  };
  /* where the eye actually IS, in world space -- the read-only twin of
     chfHouseCam, which only ever writes. A lean-in is only provable
     against the card's own world box with both halves in hand. */
  window.chfCamPose = function () {
    if (!webgl) return null;
    var p = webgl.cam.position;
    return { pos: [p.x, p.y, p.z], fov: webgl.cam.fov, mode: mode,
             focused: focused };
  };
  window.chfWorldBox = function (name) {
    if (!webgl) return null;
    var g = null;
    webgl.FABRIC.forEach(function (f) { if (!g && f.name === name) g = f.g; });
    if (!g) g = webgl.groups[name] || null;
    if (!g) return null;
    var box = new webgl.T.Box3().setFromObject(g);
    if (box.isEmpty()) return null;
    return [box.min.x, box.max.x, box.min.y, box.max.y, box.min.z, box.max.z];
  };
  window.chfPlaqueCanvas = function (i) {
    var p = carPlates[i || 0];
    if (!p || !p.material || !p.material.map || !p.material.map.image) return null;
    try { return p.material.map.image.toDataURL('image/png'); }
    catch (e) { return null; }
  };
  window.chfPlaqueRect = function (i) {
    var p = carPlates[i || 0];
    if (!webgl || !p) return null;
    webgl.cam.updateMatrixWorld();
    p.updateWorldMatrix(true, false);
    var rect = webgl.R.domElement.getBoundingClientRect();
    var x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    [[-0.75, -0.375], [0.75, -0.375], [-0.75, 0.375], [0.75, 0.375]]
      .forEach(function (c) {
        var w = p.localToWorld(new webgl.T.Vector3(c[0], c[1], 0));
        var s = _project(w, rect.width, rect.height);
        x0 = Math.min(x0, s.x + rect.left); x1 = Math.max(x1, s.x + rect.left);
        y0 = Math.min(y0, s.y + rect.top); y1 = Math.max(y1, s.y + rect.top);
      });
    if (!isFinite(x0) || x1 <= x0 || y1 <= y0) return null;
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0,
             cw: rect.width, ch: rect.height };
  };
  /* MASSING ARC 2 task 6 (spec 2026-09-17 section 2): where each block
     ACTUALLY stands after its depth -- west/east/north/south, its eave,
     its ridge and the deck planes its roof was placed by. Read-only,
     like chfBlocks. The block-meet audit rebuilds the neighbour volume
     from exactly these numbers. */
  window.chfBlockGeometry = function () {
    return webgl ? webgl.blockGeometry() : null;
  };
  /* MASSING ARC 2 task 6 (fix round 1): the BLOCK MEET as built -- for
     each block, whether its roof was clipped against the neighbour's
     bounded volume, and that volume's own planes (always derived, so a
     test can audit the equal-geometry case against the same region the
     clipper would have used). Read-only, like chfBlockGeometry. */
  window.chfBlockMeet = function () {
    if (!webgl) return null;
    var out = { main: { active: !!webgl.BLOCK_MEET.main,
                        planes: webgl.BLOCK_VOLUMES.main },
                garage: { active: !!webgl.BLOCK_MEET.garage,
                          planes: webgl.BLOCK_VOLUMES.garage } };
    if (webgl.VOLUME_MEETS && webgl.VOLUME_MEETS.length > 2) {
      out.volumes = webgl.VOLUME_MEETS;
      ['main', 'garage'].forEach(function (block) {
        out[block].active = webgl.VOLUME_MEETS.some(function (v) {
          return v.block === block && v.active;
        });
      });
    }
    return out;
  };
  /* ROOF VALLEYS (masking spec section 6): the block deck plane under a
     street face's features, {n, d} with n the deck's upward normal
     (n.p - d >= 0 is above the deck), derived by deckPlane exactly as
     shellGable placed the deck; null for a ridge on z (a gable end on
     the street: no one deck). chfRoofPlanes lists every deck plane of
     the block roof (two, four for a hip). */
  window.chfRoofPlane = function (face) {
    if (!webgl) return null;
    var pl = webgl.faceDeckPlane(face);
    return pl ? { n: pl.n, d: pl.d } : null;
  };
  window.chfRoofPlanes = function (face) {
    if (!webgl) return [];
    return webgl.blockDeckPlanes(face).map(function (pl) { return { n: pl.n, d: pl.d }; });
  };
  /* the world vertices of one facade row's (or block roof's) meshes as
     BUILT -- after the valley clip, before mergeStatic -- [[x, y, z],
     ...]; task 7 adds a query-time fallback for every other row, so an
     interior partition or a plain shell wall answers too. null only for
     a name no registered row carries. */
  window.chfFabricVertices = function (name) {
    if (!webgl) return null;
    if (webgl.FEATURE_VERTS[name]) return webgl.FEATURE_VERTS[name];
    /* MASSING ARC 2 task 7: a row that was never snapshotted at
       registration -- an interior partition (east_partition and friends
       go through regFabric directly, hundreds of lines before
       FEATURE_VERTS exists) or a plain shell wall -- is read off its own
       meshes here instead. mergeStatic bakes each source's world matrix
       into its composite and parks the composite under the same root, so
       the world points are the same either side of the merge; the only
       difference from a snapshot is that a row whose meshes the room
       masks stamped is reported whole, which is what "as built" means. */
    var row = null;
    webgl.FABRIC.forEach(function (f) { if (f.name === name) row = f; });
    if (!row) return null;
    var out = [], v = new webgl.T.Vector3();
    row.g.updateMatrixWorld(true);
    row.g.traverse(function (m) {
      if (!m.isMesh || m.isInstancedMesh || !m.geometry) return;
      var p = m.geometry.getAttribute('position');
      if (!p) return;
      for (var i = 0; i < p.count; i++) {
        v.fromBufferAttribute(p, i).applyMatrix4(m.matrixWorld);
        out.push([v.x, v.y, v.z]);
      }
    });
    return out.length ? out : null;
  };
  /* PER-FEATURE CLADDING (task 8, review fix F1): the distinct cladding
     tiles a registered row actually WEARS, read off its live materials.
     cladTex stamps every tile it makes with `userData.uvKey` (the
     material name: 'batten', 'brick', 'shingle', ...) for the world-UV
     rescale, so the key is already there to read and this hook invents
     no second source of truth. Read-only, called by tests only, and it
     runs AFTER mergeStatic -- a merged composite carries the one
     material its bucket shared, which is exactly the tile the row wears.
     Rows with no mapped material come back as an empty list rather than
     null, so "this row wears nothing" and "no such row" stay different
     answers. */
  window.chfPieceMaps = function (name) {
    if (!webgl) return null;
    var row = null;
    webgl.FABRIC.forEach(function (f) { if (f.name === name) row = f; });
    if (!row) return null;
    var keys = [];
    row.g.traverse(function (m) {
      if (!m.isMesh || !m.material) return;
      [].concat(m.material).forEach(function (mt) {
        var k = mt && mt.map && mt.map.userData && mt.map.userData.uvKey;
        if (k && keys.indexOf(k) < 0) keys.push(k);
      });
    });
    return keys;
  };
  window.chfFacadeSlots = function () { return webgl ? webgl.SLOTS : []; };
  /* MASSING ARC 2 task 10: one frame, one data URL, synchronously. The
     canvas has no preserveDrawingBuffer (it never will -- that costs a
     copy on every frame of every wall panel), so toDataURL only sees
     pixels while the drawing buffer is still unswapped: render here and
     read in the SAME task, never across an await. No per-frame work is
     added; this runs only when something calls it. */
  window.chfCapture = function () {
    if (!webgl) return null;
    webgl.R.render(webgl.scene, webgl.cam);
    return webgl.R.domElement.toDataURL('image/png');
  };
  /* Read-only test hook: find a canvas pixel over actual geometry. Use
     the production hit readers so candidate selection cannot drift from
     pointer handling. Tests still assert the result of a real mouse click.
     A missing candidate means the sampled view cannot reach the target. */
  window.chfNavProbe = function (spec) {
    if (!webgl || !spec) return null;
    if (spec.settled) return tween ? null : { mode: mode, focused: focused };
    webgl.cam.updateMatrixWorld();
    var rect = webgl.R.domElement.getBoundingClientRect();
    var w = rect.width, h = rect.height;
    function project(x, y, z) {
      var p = _project(new webgl.T.Vector3(x, y, z), w, h);
      return { cx: p.x + rect.left, cy: p.y + rect.top, z: p.z };
    }
    function onCanvas(p) {
      var el = document.elementFromPoint(p.cx, p.cy);
      /* the room's own markers stand ON its objects (they are buttons
         now): a point under one is on the room, not behind chrome */
      return el === webgl.R.domElement || !!(el && el.closest && el.closest('#house-hints'));
    }
    /* THE MIRROR (spec 2026-09-17 section 3.4): this hook speaks
       HOUSE-LOCAL, because that is what its callers hold -- an authored
       point (hintChoices' PACK_SPOTS) and FABRIC's boxes, which were
       measured before the reflection and are never re-measured. Both are
       reflected on their way to the screen. The branches further down
       that read a live Box3.setFromObject (zone/action/feature/entry) are
       already WORLD and are left exactly alone. */
    if (spec.point) {
      var pp = project(webgl.toWorldX(spec.point[0]), spec.point[1], spec.point[2]);
      return pp.z >= -1 && pp.z <= 1 && onCanvas(pp) ? pp : null;
    }
    var b = null, target = null, targetName = null, bLocal = false;
    if (spec.piece) {
      /* BLOCKS (spec 2026-09-17 section 0): a caller names the CANONICAL
         piece (the Mudroom marker asks for garage_block_roof_south), and
         roofAlias hands back the piece that stands there under this
         block's form and ridge -- on a ridge z that is the block's own
         street-facing end, under a different registered name. Resolved
         here, beside hintChoices, so the marker the hint places and the
         probe that places it cannot disagree. */
      var pieceName = webgl.roofAlias(spec.piece);
      webgl.FABRIC.forEach(function (f) {
        if (f.name === pieceName) { b = f.box; target = f.g; targetName = f.name; bLocal = true; }
      });
      if (!b) return null;
    } else if (spec.front) {
      /* FACADE (arc 4): a FACE, not a piece. The generator names its
         pieces facade_<face>_<kind>_<slot>, so an exterior marker on a
         face can no longer hard-code one name. Take the first street-
         facing (n.z > 0.5) generated piece on that face; a face whose
         spec generated nothing street-facing falls back to the garage
         door, registered by hand and always present. */
      var face = String(spec.front).replace(/_front$/, '');
      /* SIDE-ENTRY GARAGE (task 8, controller ruling on the review): the
         Garage marker must be offered at the RESTING stop, like every
         other exterior marker. A side garage's door faces WEST, so it is
         behind the block from stop 0 and the marker would simply not
         appear -- functionality dropped by geometry. The marker means
         "the garage", not "that leaf": on a side garage it targets
         `garage_front_wall`, the block's own street face, which is
         visible at every stop and carries room 'garage', so a tap on it
         walks into the garage exactly as a tap on the door does. The
         DOOR is still addressable by name -- {piece:'garage_door'} is
         untouched -- and the first-street-facing-generated-piece rule
         below is skipped here, because on a side garage that piece is
         the bay's WINDOW. */
      var sideGarage = webgl.GARAGE_SIDE &&
                       (face === 'garage' || face === 'garage_block');
      if (sideGarage) webgl.FABRIC.forEach(function (f) {
        if (!b && f.name === 'garage_front_wall') {
          b = f.box; target = f.g; targetName = f.name; bLocal = true;
        }
      });
      else webgl.FABRIC.forEach(function (f) {
        if (b || f.name.indexOf('facade_' + face + '_') !== 0 || f.n.z <= 0.5) return;
        b = f.box; target = f.g; targetName = f.name; bLocal = true;
      });
      if (!b) webgl.FABRIC.forEach(function (f) {
        if (!b && f.name === 'garage_door') {
          b = f.box; target = f.g; targetName = f.name; bLocal = true;
        }
      });
      if (!b) return null;
    } else if (spec.zone || spec.action || spec.feature) {
      if (spec.zone) target = webgl.groups[spec.zone];
      else webgl.scene.traverse(function (o) {
        if (!target && (spec.action && o.userData.houseAction === spec.action || spec.feature && o.userData.houseFeatureKey === spec.feature)) target = o;
      });
      if (!target) return null;
      var box = new webgl.T.Box3().setFromObject(target);
      if (box.isEmpty()) return null;
      b = [box.min.x, box.max.x, box.min.y, box.max.y, box.min.z, box.max.z];
    } else if (spec.entry) {
      var entryBox = new webgl.T.Box3(), entryFound = false;
      webgl.scene.traverse(function (o) {
        if (o.userData && o.userData.entry === spec.entry) {
          entryBox.expandByObject(o); entryFound = true;
        }
      });
      if (!entryFound || entryBox.isEmpty()) return null;
      b = [entryBox.min.x, entryBox.max.x, entryBox.min.y, entryBox.max.y,
           entryBox.min.z, entryBox.max.z];
    } else if (!spec.sky && !spec.empty && !spec.exit) return null;
    /* the reflection, once, for the two branches that read a stored
       house-local box (see the note above spec.point) */
    if (b && bLocal && webgl.MIRROR) b = [-b[1], -b[0], b[2], b[3], b[4], b[5]];
    var minX = rect.left + 2, maxX = rect.right - 2;
    var minY = rect.top + 2, maxY = rect.bottom - 2;
    if (b) {
      var x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (var i = 0; i < 2; i++) for (var j = 0; j < 2; j++) for (var k = 0; k < 2; k++) {
        var p = project(b[i], b[2 + j], b[4 + k]);
        if (p.z < -1 || p.z > 1) continue;
        x0 = Math.min(x0, p.cx); x1 = Math.max(x1, p.cx);
        y0 = Math.min(y0, p.cy); y1 = Math.max(y1, p.cy);
      }
      minX = Math.max(minX, x0); maxX = Math.min(maxX, x1);
      minY = Math.max(minY, y0); maxY = Math.min(maxY, y1);
    }
    if (minX >= maxX || minY >= maxY) return null;
    function matches(px, py) {
      var p = { cx: px, cy: py };
      if (!onCanvas(p)) return false;
      if (spec.zone) return zoneAt(px, py) === spec.zone;
      if (spec.empty) return !zoneAt(px, py);
      if (spec.zoneless && zoneAt(px, py)) return false;
      var hit = anyHit(px, py);
      if (spec.sky) return !hit || hit === webgl.skyDome;
      if (spec.exit) return !hit || hit === webgl.skyDome || inYard(hit);
      if (spec.entry) {
        for (var e = hit; e; e = e.parent)
          if (e.userData && e.userData.entry === spec.entry) return true;
        return false;
      }
      /* VIEW-VOLUME MASKING (task 3): in a room view a piece the mask
         cut is drawn partly by its remnant in the room shell, whose
         mirrored row group carries shellOf = the piece's name */
      for (var o = hit; o; o = o.parent)
        if (o === target || (targetName && o.userData && o.userData.shellOf === targetName)) return true;
      return false;
    }
    var cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
    if (matches(cx, cy)) return { cx: cx, cy: cy };
    var n = spec.sky || spec.empty || spec.exit ? 24 : 8;
    for (var gx = 0; gx <= n; gx++) for (var gy = 0; gy <= n; gy++) {
      var px = minX + (maxX - minX) * gx / n;
      var py = minY + (maxY - minY) * gy / n;
      if (matches(px, py)) return { cx: px, cy: py };
    }
    return null;
  };

  /* Touch-first discovery. Persistent, non-blocking markers identify every
     reachable registered entrance outside and zone group inside. Room icons
     summarize the features waiting within; object markers carry one icon. */
  var hintTimer = null;
  var HINT_PATHS = {
    study: '<path d="M4 4h7l1 2 1-2h7v16h-7l-1 1-1-1H4zM12 6v15"/>',
    moments: '<path d="M3 9a2 2 0 012-2h1l2-3h8l2 3h1a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><circle cx="12" cy="13" r="3"/>',
    meals: '<path d="M3 4h2l2.2 10h10.6L21 7H6"/><circle cx="9" cy="19" r="1"/><circle cx="18" cy="19" r="1"/>',
    lists: '<path d="M7 4h10a2 2 0 012 2v15H5V6a2 2 0 012-2h2"/><path d="M9 3h6v4H9zM9 12h6M9 16h6"/>',
    schedule: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/>',
    music: '<path d="M9 18V6l11-2v11M9 10l11-2"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="15" r="3"/>',
    weather: '<path d="M7 18h11a3 3 0 000-6 6 6 0 00-11-2 4 4 0 000 8z"/><path d="M5 6L3 4M9 4V2M3 10H1"/>',
    garage: '<path d="M4 12l2-5h12l2 5v7h-2v-2H6v2H4zM6 12h12"/><circle cx="8" cy="14" r="1"/><circle cx="16" cy="14" r="1"/>',
    critters: '<path d="M8.5 11.5c-2.5 1.2-4 3.3-3.3 5.5.8 2.5 3.7 2.6 6.8 1.2 3.1 1.4 6 1.3 6.8-1.2.7-2.2-.8-4.3-3.3-5.5-2.1-1-4.9-1-7 0z"/><circle cx="5" cy="9" r="2"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="6" r="2"/><circle cx="19" cy="9" r="2"/>',
    chores: '<path d="M5 4h14v17H5zM8 3h8v4H8zM8 12l2 2 5-5M8 18h8"/>',
    routines: '<path d="M4 10a8 8 0 0114-5l2 2M20 3v4h-4M20 14A8 8 0 016 19l-2-2M4 21v-4h4"/>',
    programs: '<path d="M5 4h6l1 2 1-2h6v16h-6l-1 1-1-1H5zM12 6v15"/>',
    tasks: '<path d="M5 3h14v18H5zM8 7h8M8 12h8M8 17h5"/>',
    errands: '<path d="M4 12l2-5h12l2 5v7h-2v-2H6v2H4zM6 12h12M7 14h2M15 14h2"/>'
  };
  var ZONE_HINT_ICON = {
    fridge: 'moments', counter: 'meals', board: 'lists', door: 'schedule',
    calendar: 'calendar', radio: 'music', window: 'weather', garage: 'garage',
    curb: 'schedule', pet: 'critters',
    study_board: 'study', study_desk: 'tasks', study_tray: 'lists',
    study_stickies: 'tasks', study_calendar: 'calendar', study_window: 'weather',
    study_contracts: 'tasks', study_binders: 'programs',
    study_gauges: 'schedule', study_monitor: 'study', study_map: 'schedule'
  };
  var EXTERIOR_HINTS = [
    ['kitchen', 'Kitchen', ['moments', 'meals', 'lists', 'calendar', 'weather']],
    ['living', 'Living room', ['music', 'critters', 'tasks', 'programs'], ['tasks','programs']],
    ['mudroom', 'Mudroom', ['schedule', 'chores', 'routines'], ['packing','chores','routines']],
    ['garage', 'Garage', ['garage', 'errands'], ['errands']],
    ['study', 'Study (Parent PIN)', ['study'], ['intake','tasks']]
  ];
  function packingAttention() {
    return (((state || {}).mudroom || {}).packs || []).reduce(function (n, p) {
      return n + (p.attention ? Math.max(0, p.needed - p.packed) : 0);
    }, 0);
  }
  function hintAttention(key) {
    var attention = ((state || {}).attention || {})[key];
    if (attention) return attention.count || 0;
    if (key === 'garage_block_roof_south' || key === 'calendar' ||
        key === 'packing') return packingAttention();
    return 0;
  }
  function refreshAttentionBadges() {
    if (!HINT) return;
    HINT.querySelectorAll('.house-hint').forEach(function (marker) {
      var keys = marker.dataset.attention ? marker.dataset.attention.split(',') : [marker.dataset.target];
      var count = keys.reduce(function (sum, key) { return sum + hintAttention(key); }, 0);
      var badge = marker.querySelector('.house-attention-badge');
      if (!count) { if (badge) badge.remove(); return; }
      if (!badge) { badge = document.createElement('span'); badge.className = 'house-attention-badge'; marker.appendChild(badge); }
      badge.textContent = count;
    });
  }
  function hideHint() {
    if (window.ChauffeurMarkers) window.ChauffeurMarkers.collapse();
    if (HINT) { HINT.hidden = true; HINT.textContent = ''; }
  }
  function hintChoices() {
    if (mode === 'exterior') {
      var exterior = EXTERIOR_HINTS.map(function (h) {
        var b = webgl.ROOM_AABB[h[0]];
        return { spec: {point: [(b[0]+b[1])/2, b[3]+0.6, (b[4]+b[5])/2]},
                 label:h[1], key:h[0], room:h[0], icons:h[2], attention:h[3] || [] };
      });
      return exterior;
    }
    var choices = Object.keys(ZONES).filter(function (key) {
      return zoneRoom(key) === mode;
    }).map(function (key) {
      return { spec: { zone: key }, label: ZONES[key].label, key: key,
               icons: [ZONE_HINT_ICON[key]] };
    });
    if (mode === 'kitchen' && (((state || {}).mudroom || {}).packs || []).length)
      choices.push({ spec: { point: PACK_SPOTS[0] }, label: 'Packing', key: 'packing',
        action:'packing', icons: ['lists'] });
    if (world) world.entries.forEach(function(e) {
      if (e.room === mode) choices.push({spec:{feature:e.key},label:e.label,key:e.action || e.key,
        action:e.action,icons:[e.action || 'lists']});
    });
    return choices;
  }
  function markerForRoom(room) { return HINT.querySelector('[data-room="' + room + '"]'); }
  function hintIcon(name) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true">' +
      (HINT_PATHS[name] || '') + '</svg>';
  }
  function showHint() {
    if (!HINT || !webgl || focused || tween ||
        typeof window.chfNavProbe !== 'function') return;
    HINT.textContent = '';
    var choices = hintChoices(), shown = 0, placed = [];
    for (var i = 0; i < choices.length; i++) {
      var choice = choices[i];
      var point = window.chfNavProbe(choice.spec);
      if (choice.room) {
        // Room navigation remains available through the shell from every angle.
        var rect = webgl.R.domElement.getBoundingClientRect();
        point = point || {cx:rect.left + rect.width*(i+1)/(choices.length+1), cy:rect.top+rect.height/2};
        var left = rect.left+50, right = rect.right-50, top = rect.top+60, bottom = rect.bottom-125;
        if (rect.width < 600) {
          bottom = rect.bottom - 180;
          top = Math.max(top, 105);
          document.querySelectorAll('#house-glance:not([hidden]) .glance-clock, #house-glance:not([hidden]) .glance-next:not([hidden])').forEach(function (card) {
            top = Math.max(top, card.getBoundingClientRect().bottom + 45);
          });
          top = Math.min(top, bottom - 210);
        }
        point.cx = Math.max(left,Math.min(right,point.cx));
        point.cy = Math.max(top,Math.min(bottom,point.cy));
        for (var attempt=0; attempt<40; attempt++) {
          if (!placed.some(function(p) { return Math.abs(p.cx-point.cx)<100 && Math.abs(p.cy-point.cy)<100; })) break;
          point.cy += 105;
          if (point.cy>bottom) { point.cy=top; point.cx+=105; if(point.cx>right) point.cx=left; }
        }
        placed.push({cx:point.cx,cy:point.cy});
      }
      if (!point) continue;
      /* IN-ROOM MARKERS ARE BUTTONS (2026-09-22). User report: "Home ledger"
         in the living room did nothing while the exterior Tasks shortcut --
         a real button -- worked. These used to be drawings: #house-hints is
         pointer-events:none, so a tap fell through to whatever mesh lay
         behind the ring. Only its exact centre reached the ledger (a book
         a few pixels wide); 25px off-centre hit the console and did
         nothing, 25px up hit the kitchen floor and WALKED TO THE KITCHEN,
         and the label below the ring was dead. A marker is a promise that
         tapping it does the thing it names, so now it does: a feature
         marker opens its feature exactly as the object does, a zone marker
         leans in exactly as the furniture does.

         And two markers cannot share a spot: the Program book sits 1.9
         units down the same console, and its ring covered the ledger's
         label. A marker that collides with one already placed steps
         straight away from it by just the overlap (the ring still sits on
         its object -- the nudge is a fraction of the ring). */
      if (!choice.room) {
        /* the 78px ring plus its label, which hangs from 8px under the
           ring to ~71px below the centre: two markers stacked need 110px */
        var FOOT_W = 96, FOOT_H = 110;
        for (var step = 0; step < 6; step++) {
          var clash = null;
          for (var pi = 0; pi < placed.length; pi++) {
            var q = placed[pi];
            if (Math.abs(q.cx - point.cx) < FOOT_W && Math.abs(q.cy - point.cy) < FOOT_H) { clash = q; break; }
          }
          if (!clash) break;
          var dxp = point.cx - clash.cx, dyp = point.cy - clash.cy;
          var byY = FOOT_H - Math.abs(dyp), byX = FOOT_W - Math.abs(dxp);
          if (byY <= byX) point.cy += (dyp >= 0 ? 1 : -1) * (byY + 4);
          else point.cx += (dxp >= 0 ? 1 : -1) * (byX + 4);
        }
        placed.push({cx: point.cx, cy: point.cy});
      }
      var marker = document.createElement('button');
      marker.type = 'button';
      if (!choice.room) {
        marker.setAttribute('aria-label', choice.label);
        marker.style.pointerEvents = 'auto';
        marker.addEventListener('click', (function (c) { return function (event) {
          event.stopPropagation();
          /* markers stay: a feature's card opens OVER the room and closing
             it returns to the same room (a lean-in hides them itself,
             through leanIn's own scheduleHint) */
          if (c.action) {
            window.dispatchEvent(new CustomEvent('chf-house-open', {detail: c.action}));
          } else if (c.spec && c.spec.zone && ZONES[c.spec.zone]) {
            leanIn(c.spec.zone);
          }
        }; })(choice));
      }
      if (choice.room) {
        marker.dataset.room = choice.room;
        marker.setAttribute('aria-label', 'Expand ' + choice.label);
        marker.setAttribute('aria-expanded', 'false');
        marker.style.pointerEvents = 'auto';
        marker.addEventListener('click', (function(room) { return function(event) {
          event.stopPropagation();
          if (window.ChauffeurMarkers && window.ChauffeurMarkers.expand(markerForRoom(room), room)) return;
          if (room === 'study') window.dispatchEvent(new CustomEvent('chf-house-open', {detail:'study'}));
          else enterRoom(room,null);
        }; })(choice.room));
      }
      marker.className = 'house-hint' + (choice.icons.length > 3 ? ' crowded' : '');
      marker.dataset.target = choice.key;
      if (choice.action) marker.dataset.houseAction = choice.action;
      if (choice.attention && choice.attention.length) marker.dataset.attention = choice.attention.join(',');
      marker.style.left = point.cx + 'px';
      marker.style.top = point.cy + 'px';
      marker.style.setProperty('--hint-delay', (shown * 0.45) + 's');
      var icons = document.createElement('div');
      icons.className = 'house-hint-icons';
      icons.innerHTML = choice.icons.map(hintIcon).join('');
      var label = document.createElement('span');
      label.className = 'house-hint-label';
      label.textContent = choice.label;
      marker.appendChild(icons); marker.appendChild(label);
      HINT.appendChild(marker); shown++;
    }
    HINT.hidden = shown === 0;
    refreshAttentionBadges();
  }
  function scheduleHint(delay) {
    if (hintTimer) clearTimeout(hintTimer);
    hideHint();
    if (HINT) hintTimer = setTimeout(showHint, delay || 1600);
  }
  function announceFocus(key) {
    if (webgl && state) applyState(state);   /* blank/restore the faces */
    /* STUDY LEAN-IN (2026-09-22): the study's own painted detail stands up
       for the zone being read (and only for a zone that wears no card --
       house_study.js holds the one predicate) and stands down with the
       focus. Until this the 41 detail panels study.js builds were never
       painted or shown in the house at all. */
    if (webgl && webgl.studyWorld) webgl.studyWorld.focus(key);
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

  /* SHELL (spec section 5, the navigation law): the one ancestor-room walk
     both onTap branches need — stamped, not guessed (regFabric's own room
     field, registration time; stampHouse's zone-borrow/y>0.6 fallback,
     build time). Climbs all the way to the scene root regardless of
     extG membership: west_wall's own group sits at scene level, never
     under extG (see its own build-site comment), so a walk that stopped
     at extG would never find its stamp. */
  function roomTagOf(obj) {
    var o = obj;
    while (o) {
      if (o.userData && o.userData.room) return o.userData.room;
      if (o.userData && o.userData.fabric) return null;
      o = o.parent;
    }
    return null;
  }

  function inertFabric(obj) {
    for (var o = obj; o; o = o.parent)
      if (o.userData && o.userData.fabric) return !o.userData.room;
    return false;
  }

  /* ORBIT (spec section 4): a horizontal drag across the canvas steps the
     ring, and the click the browser synthesises at its release must not
     ALSO walk into whatever room the finger happened to lift over. The
     pointerup handler sets this; onTap spends it. */
  var swipeStart = null, swiped = false;

  function onTap(ev) {
    if (!webgl) return;
    if (swiped) { swiped = false; return; }
    if (window.ChauffeurMarkers && window.ChauffeurMarkers.collapse()) return;
    var primaryHit = anyHit(ev.clientX, ev.clientY);
    for (var actionPart = primaryHit; actionPart; actionPart = actionPart.parent) {
      if (actionPart.userData.houseAction) {
        window.dispatchEvent(new CustomEvent('chf-house-open', { detail: actionPart.userData.houseAction }));
        return;
      }
    }
    hideHint();
    if (mode === 'exterior') {
      /* stamped, not guessed: walk up for a room tag; yard and sky stay
         a view; anything INTERIOR seen through the open front is the
         kitchen. */
      var hit = primaryHit;
      if (!hit || hit === webgl.skyDome) return;
      var room = roomTagOf(hit);
      if (room && roomsReg()[room]) { enterRoom(room, null); return; }
      if (inertFabric(hit)) return;
      if (inYard(hit)) return;                 /* scenery: look, do not enter */
      if (!inExterior(hit)) enterRoom('kitchen', null);
      return;
    }
    var ihit = primaryHit;
    /* Shell-only rooms are scenery even when a zone lies behind them.
       The yard retains its separate exit behavior. */
    if (inertFabric(ihit) && !inYard(ihit)) return;
    var key = zoneAt(ev.clientX, ev.clientY);
    if (key && !zoneRoom(key)) key = null;  /* curb belongs to the yard */
    if (key) {
      var kr = zoneRoom(key);
      /* rule 2: a zone belonging to ANOTHER room navigates there — a ray
         that slipped past a wall used to be silenced into `key = null`
         (an ejection, the cross-room null this task deletes) instead of
         the navigation it plainly asked for (the radio, visible from the
         kitchen across the open great room, used to eject a tap that
         should have walked into living). Rule 1 (own-room zone leans in)
         is simply everything below that this `if` does not return out
         of. */
      if (kr !== mode) { enterRoom(kr, null); return; }
    } else {
      /* Visible background keeps the original direct walk-out gesture,
         even from a lean-in. The button owns the deliberate two-step path. */
      if (!ihit || ihit === webgl.skyDome || inYard(ihit)) {
        goExterior();                          /* rule 5 */
        return;
      }
      if (focused) { goHome(mode); return; }
      var iroom = roomTagOf(ihit);
      if (iroom && iroom !== mode && roomsReg()[iroom]) {
        enterRoom(iroom, null);                /* rule 3: another room's
                                                    room-tagged fabric/props */
        return;
      }
      return;   /* rule 4: the current room's own zoneless prop — INERT,
                   no more ejecting an island mis-tap into the sealed
                   exterior */
    }
    if (focused === key) {                                 // second tap: through
      var through = zoneUrl(key);
      if (through) go(through);                            // panel: nowhere to go
      return;
    }
    leanIn(key);
  }
  /* The first tap on a zone: frame it, announce it, say its one line. Shared
     by a tap on the furniture itself and a tap on its in-room marker, so the
     two can never lean in differently. */
  function leanIn(key) {
    focused = key;
    updateBack();
    scheduleHint();
    announceFocus(null);   /* the old card must not ride the camera move */
    frameZone(key, function () {
      announceFocus(key);
      solveLeanIn(key);
      if (state) {
        TIP.textContent = ZONES[key].label + ' — ' + ZONES[key].headline(state);
        TIP.style.left = '16px';
        /* clear of the panel shelf (the wall's tab bar), the same
           expression .house-orbit derives its bottom from; 0px off a panel */
        TIP.style.bottom = 'calc(var(--panel-shelf-h, 0px) + 64px)';
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
  if (webgl && window.ChauffeurHome) window.ChauffeurHome.ready();
  window.chfHouseState = function () { return state; };
  window.chfHouseWeather = function () { return webgl ? webgl.weather.stats() : null; };
  window.chfHouseRefresh = poll;
  if (webgl) {
    if (webgl.studyWorld) {
      webgl.studyWorld.group.visible = false;
      if (webgl.studyWorld.architecture) webgl.studyWorld.architecture.visible = false;
      if (webgl.studyWorld.proxies) webgl.studyWorld.proxies.visible = false;
    }
    if (BACK) BACK.addEventListener('click', function () {
      if (focused) goHome(mode);
      else if (mode === 'study') {
        if (window.chfHouseEndParent) window.chfHouseEndParent();
        studyFurniture = {}; webgl.studyWorld.update(studyFurniture);
        enterRoom('living', null);
      }
      else if (mode !== 'exterior') goExterior();
    });
    for (var ob = 0; ob < ORBIT_BTNS.length; ob++)
      ORBIT_BTNS[ob].addEventListener('click', function () {
        orbitStep(parseInt(this.dataset.dir, 10) || 1);
      });
    updateOrbitControls();
    window.addEventListener('keydown', function (e) {
      if (document.body.classList.contains('house-card-open')) return;
      /* ORBIT (spec section 4): the arrows step the ring at the exterior
         and mean nothing inside a room, where the camera is fixed.

         They also mean nothing while somebody is typing. This page
         carries the Argyle textarea and command field (control_center)
         and the music widget's search box and volume slider; none of
         them set `house-card-open`, and none of their own handlers stop
         an arrow bubbling up to window -- so without this guard "move
         the caret back one character" became an 850 ms tween plus a
         solveShell, and every further caret move spun the house another
         45 degrees. defaultPrevented covers the same ground for any
         handler that has already claimed the key. */
      if (mode === 'exterior' &&
          (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
        var t = e.target;
        if (e.defaultPrevented ||
            (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) ||
                   t.isContentEditable))) return;
        orbitStep(e.key === 'ArrowRight' ? 1 : -1);
        return;
      }
      if (e.key !== 'Escape' || mode === 'exterior') return;
      if (focused) goHome(mode);
      else if (mode === 'study') {
        if (window.chfHouseEndParent) window.chfHouseEndParent();
        studyFurniture = {}; webgl.studyWorld.update(studyFurniture);
        enterRoom('living', null);
      } else goExterior();
    });
    webgl.R.domElement.addEventListener('webglcontextlost', function (e) {
      e.preventDefault();
      /* the graceful death: swap to the calm 2D room, stop asking the GPU */
      announceFocus(null);
      try { ROOT.style.display = 'none'; } catch (err) {}
      if (webgl && webgl.neighborhood) webgl.neighborhood.dispose();
      if (webgl) webgl.weather.dispose();
      webgl = null;
      drawFallback(state);
    });
    /* ORBIT (spec section 4): the swipe. A gesture only counts as one at
       the exterior, past 60px of horizontal travel, more across than down
       (so a scroll-ish drag is never mistaken for a turn) and inside
       800ms (so a slow drag that ends where a tap would have landed is
       still a tap). Two listeners and a stored point — no per-frame work,
       nothing in the ticker. */
    webgl.R.domElement.addEventListener('pointerdown', function (e) {
      swipeStart = { x: e.clientX, y: e.clientY, t: performance.now() };
      swiped = false;
    });
    /* touch: the browser can take the gesture away mid-drag (a pan or a
       zoom wins the slop race) and then `pointerup` never fires on this
       element at all. house.html sets `touch-action: none` on the canvas
       so that should not happen on a touch panel -- this is the belt to
       that brace: a cancelled pointer drops the stored point instead of
       leaving it to pair with whatever pointerup comes next. */
    webgl.R.domElement.addEventListener('pointercancel', function () {
      swipeStart = null;
    });
    webgl.R.domElement.addEventListener('pointerup', function (e) {
      if (!swipeStart) return;
      var dx = e.clientX - swipeStart.x, dy = e.clientY - swipeStart.y,
          dt = performance.now() - swipeStart.t;
      swipeStart = null;
      if (mode !== 'exterior') return;
      if (Math.abs(dx) < 60 || Math.abs(dy) >= Math.abs(dx) || dt >= 800) return;
      /* drag the house to the LEFT and the camera walks clockwise around
         it, the same direction the right chevron goes. */
      swiped = true;
      orbitStep(dx < 0 ? 1 : -1);
    });
    webgl.R.domElement.addEventListener('click', onTap);
    window.addEventListener('resize', function () { size(); scheduleHint(); });
    scheduleHint();
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
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') { poll(); requestFrame(); }
  });
  WEATHER_MOTION.addEventListener('change', requestFrame);
  setInterval(function () {
    if (document.visibilityState === 'visible') poll();
  }, POLL_MS);
  setTimeout(stampVisit, 10000);   // study idiom: glows survive a quick reload
})();
