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
    scene.background = new T.Color(0x17130d);
    var cam = new T.PerspectiveCamera(46, 1, 0.1, 60);
    var HOME_POS = new T.Vector3(6.4, 5.0, 8.6);
    var HOME_AT = new T.Vector3(0, 1.4, 0);
    cam.position.copy(HOME_POS);
    cam.lookAt(HOME_AT);

    var R = new T.WebGLRenderer({ antialias: false });
    R.setPixelRatio(1);                       // the Pi law: never a retina multiplier
    ROOT.appendChild(R.domElement);

    scene.add(new T.AmbientLight(0xfff2dc, 0.75));
    var lamp = new T.PointLight(0xffd9a0, 0.9, 30);
    lamp.position.set(0, 5.4, 0);
    scene.add(lamp);

    function mat(c) { return new T.MeshLambertMaterial({ color: c }); }
    function box(w, h, d, c, x, y, z, group) {
      var m = new T.Mesh(new T.BoxGeometry(w, h, d), mat(c));
      m.position.set(x, y, z); (group || scene).add(m); return m;
    }

    /* shell */
    box(14, 0.2, 12, 0x6e5a41, 0, -0.1, 0);                    // floor
    box(14, 6, 0.2, 0x9b8a6a, 0, 3, -6);                       // back wall
    box(0.2, 6, 12, 0x8f7e60, -7, 3, 0);                       // left wall
    box(3.4, 2.2, 0.1, 0xbfd9e8, -2.6, 3.4, -5.93);            // window

    /* furniture, one group per zone */
    var groups = {};
    function zoneGroup(key, x, y, z) {
      var g = new T.Group();
      g.position.set(x, y, z);
      g.userData.zone = key;
      groups[key] = g; scene.add(g); return g;
    }

    var fridge = zoneGroup('fridge', -5.6, 0, -4.2);
    box(1.7, 3.4, 1.5, 0xdfe3e6, 0, 1.7, 0, fridge);
    box(1.5, 0.08, 0.06, 0xb8bcbf, 0, 2.35, 0.78, fridge);     // handle seam

    var counter = zoneGroup('counter', -1.2, 0, -4.9);
    box(4.6, 1.1, 1.6, 0x7a6248, 0, 0.55, 0, counter);
    box(4.6, 0.12, 1.7, 0xcfc4ae, 0, 1.16, 0, counter);        // top
    var pot = box(0.7, 0.42, 0.7, 0x51575c, 0.9, 1.44, 0, counter);
    var steam = box(0.16, 0.5, 0.16, 0xf2ead6, 0.9, 2.1, 0, counter);
    steam.material.transparent = true; steam.material.opacity = 0;

    var board = zoneGroup('board', 2.9, 0, -5.8);
    box(2.4, 1.7, 0.08, 0x9a6f43, 0, 3.2, 0, board);

    var doorG = zoneGroup('door', 5.9, 0, -3.0);
    box(1.7, 3.9, 0.18, 0x6d4f33, 0, 1.95, 0, doorG);
    box(0.16, 0.16, 0.1, 0xd8c48a, 0.55, 1.9, 0.12, doorG);    // knob
    var plaque = box(1.3, 0.5, 0.06, 0xefe6cf, 0, 3.5, 0.14, doorG);

    var calG = zoneGroup('calendar', 0.6, 0, -5.85);
    var calFace = box(1.5, 1.8, 0.06, 0xf4efe2, 0, 3.4, 0, calG);

    var radio = zoneGroup('radio', -3.9, 0, -4.7);
    box(0.9, 0.5, 0.5, 0x8a2f2b, 0, 1.5 + 0.25 + 0.12, 0, radio);
    var needle = box(0.05, 0.3, 0.05, 0xf2e3b8, 0.2, 2.15, 0, radio);

    var bowl = zoneGroup('pet', 3.4, 0, 2.6);
    box(0.8, 0.18, 0.8, 0xc46a4f, 0, 0.09, 0, bowl);

    var table = new T.Group();                                  // decoration only
    box(3.2, 0.14, 2.0, 0x8a6d4c, 0, 1.25, 1.6, table);
    [[-1.4, 0.8], [1.4, 0.8], [-1.4, 2.4], [1.4, 2.4]].forEach(function (p) {
      box(0.14, 1.25, 0.14, 0x6e5539, p[0], 0.62, p[1], table);
    });
    scene.add(table);

    /* canvas-texture detail (study slice-3 idiom): painted lazily on focus,
     * cached per payload change */
    var texCache = {};
    function detailTexture(key, lines) {
      var payload = key + '|' + lines.join('|');
      if (texCache[key] && texCache[key].payload === payload) return texCache[key].tex;
      var c = document.createElement('canvas'); c.width = 256; c.height = 256;
      var g = c.getContext('2d');
      g.fillStyle = '#f4efe2'; g.fillRect(0, 0, 256, 256);
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
      HOME_POS: HOME_POS, HOME_AT: HOME_AT, detailTexture: detailTexture
    };
  }

  /* ---- render-on-demand engine ---------------------------------------- */
  var state = null;
  var focused = null;        // zone key while leaned in
  var tween = null;          // {fromP,toP,fromA,toA,t0,ms,cb}
  var needFrame = false;
  var rafLive = false;

  function requestFrame() {
    needFrame = true;
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
    needFrame = false;
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
    webgl.plaque.material.map = webgl.detailTexture('door',
      d.calm !== false ? ['—'] : [(d.mins != null ? d.mins + ' min' : ''), d.label || '']);
    webgl.plaque.material.needsUpdate = true;
    var c = s.calendar || {};
    webgl.calFace.material.map = webgl.detailTexture('calendar',
      c.calm !== false ? ['Today', 'clear'] : ['Today: ' + c.today].concat(c.next || []));
    webgl.calFace.material.needsUpdate = true;

    requestFrame();
  }

  /* ---- focus-then-through (universal lean-in, generic bbox framing) ----- */
  function frameZone(key, cb) {
    var g = webgl.groups[key];
    var boxb = new webgl.T.Box3().setFromObject(g);
    var center = boxb.getCenter(new webgl.T.Vector3());
    var size3 = boxb.getSize(new webgl.T.Vector3());
    var dist = Math.max(size3.x, size3.y, size3.z) * 1.9 + 1.2;
    var dir = new webgl.T.Vector3().subVectors(webgl.cam.position, center).normalize();
    var toP = center.clone().add(dir.multiplyScalar(dist));
    toP.y = Math.max(toP.y, center.y + 0.6);
    tween = { fromP: webgl.cam.position.clone(), toP: toP,
              fromA: focused ? new webgl.T.Vector3() : webgl.HOME_AT.clone(),
              toA: center, t0: performance.now(), ms: 650, cb: cb };
    tween.fromA = webgl.HOME_AT.clone();
    requestFrame();
  }
  function goHome() {
    tween = { fromP: webgl.cam.position.clone(), toP: webgl.HOME_POS.clone(),
              fromA: webgl.HOME_AT.clone(), toA: webgl.HOME_AT.clone(),
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
  var chipShown = false;
  function chip(text) {
    if (chipShown) return;
    chipShown = true;
    CHIP.textContent = text;
    CHIP.style.opacity = 1;
    setTimeout(function () { CHIP.style.opacity = 0; }, 6000);
  }

  var sinceEpoch = lastVisit();
  function poll() {
    fetch(window.KITCHEN_STATE_URL + '?since=' + encodeURIComponent(sinceEpoch),
          { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      })
      .then(function (s) { applyState(s); })
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
  stampVisit();
})();
