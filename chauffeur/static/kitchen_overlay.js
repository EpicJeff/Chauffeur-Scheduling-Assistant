/* The kitchen's focus overlay — page-layer glue between the room and the
 * board's own card builders. The room (kitchen.js) never draws HTML; it
 * announces focus as a chf-kitchen-focus event carrying the zone and its
 * screen rect. This file answers two zones for now:
 *
 *   door      → the hero card, HeroCard.html(next, {compact: true}) — the
 *               exact renderer the screensaver's Next-up corner uses, so a
 *               third surface still cannot drift from the board.
 *   calendar  → the Family Day card (packingCard island in kitchen.html,
 *               mounted with interactive: false — the board's own read-only
 *               mode). No x-init: the island fetches NOTHING until the first
 *               lean-in, so the idle room still speaks to one endpoint.
 *
 * Never writes: every fetch here is a GET, and innerHTML is only ever fed
 * by HeroCard.html, which escapes every field it prints (or cleared).
 */
(function () {
  'use strict';
  var BASE = (window.chfBase !== undefined ? window.chfBase : '');
  var WRAP = document.getElementById('kitchen-wrap');
  var OV = document.getElementById('focus-overlay');
  var DOOR = document.getElementById('overlay-door');
  var CAL = document.getElementById('overlay-calendar');
  if (!WRAP || !OV || !DOOR || !CAL) return;

  /* hero payload, cached briefly: a lean-in is a moment, not a poll */
  var hero = null, heroAt = 0, heroTick = null;
  var HERO_TTL = 60000;

  function fetchHero(cb) {
    if (hero !== null && Date.now() - heroAt < HERO_TTL) { cb(hero); return; }
    fetch(BASE + 'api/home_board', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      })
      .then(function (b) {
        heroAt = Date.now();
        var h = (b || {}).hero || {};
        /* the screensaver's own test: a done day has no "next" */
        hero = (!h.all_done && h.next) ? h.next : false;
        cb(hero);
      })
      .catch(function () { cb(null); });
  }

  function renderDoor() {
    if (!hero || !window.HeroCard) { DOOR.innerHTML = ''; return; }
    /* the BOARD's own band (not the screensaver's dark scrim): its inks are
       panel-text/panel-dim, which kitchen.html defines inside the overlay
       as the room's own paper-and-ink palette */
    DOOR.innerHTML = HeroCard.html(hero, { isLight: true });
  }

  /* ---- pasting the card ONTO the surface -------------------------------
     The room announces the projected QUAD of the furniture's face. The
     card lays out flat at a readable width, then a projective transform
     (matrix3d) maps its rectangle onto a centred slice of that quad — the
     same perspective the room drew the face with, so the card reads as ON
     the calendar sheet / door, not floating in front of the diorama. */
  function _adj3(m) {
    return [m[4] * m[8] - m[5] * m[7], m[2] * m[7] - m[1] * m[8], m[1] * m[5] - m[2] * m[4],
            m[5] * m[6] - m[3] * m[8], m[0] * m[8] - m[2] * m[6], m[2] * m[3] - m[0] * m[5],
            m[3] * m[7] - m[4] * m[6], m[1] * m[6] - m[0] * m[7], m[0] * m[4] - m[1] * m[3]];
  }
  function _mul3(a, b) {
    var r = [], i, j, k, s2;
    for (i = 0; i < 3; i++) for (j = 0; j < 3; j++) {
      s2 = 0;
      for (k = 0; k < 3; k++) s2 += a[3 * i + k] * b[3 * k + j];
      r[3 * i + j] = s2;
    }
    return r;
  }
  function _mulV3(m, v) {
    return [m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
            m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
            m[6] * v[0] + m[7] * v[1] + m[8] * v[2]];
  }
  function _basis(p1, p2, p3, p4) {
    var m = [p1.x, p2.x, p3.x, p1.y, p2.y, p3.y, 1, 1, 1];
    var v = _mulV3(_adj3(m), [p4.x, p4.y, 1]);
    return _mul3(m, [v[0], 0, 0, 0, v[1], 0, 0, 0, v[2]]);
  }
  function _quadTransform(w, h, q) {
    var src = _basis({ x: 0, y: 0 }, { x: w, y: 0 }, { x: w, y: h }, { x: 0, y: h });
    var t = _mul3(_basis(q[0], q[1], q[2], q[3]), _adj3(src));
    for (var i = 0; i < 9; i++) t[i] /= t[8];
    return 'matrix3d(' + [t[0], t[3], 0, t[6],
                          t[1], t[4], 0, t[7],
                          0, 0, 1, 0,
                          t[2], t[5], 0, t[8]].join(',') + ')';
  }
  function _lerp(a, b, t) { return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }; }
  function _len(a, b) { var dx = a.x - b.x, dy = a.y - b.y; return Math.sqrt(dx * dx + dy * dy); }

  /* Where on the face each card sits — the user's own markup, verbatim:
     the calendar card IS the sheet's writing area (below the Today
     header, down the whole page); the door card is a block anchored high
     on the door, where the plaque lived. `fill` forces the card to the
     region's full height (content flows from its top, the rest is
     paper); `fit` anchors at `top` and takes its height from the
     content, never less than `min` of the face. */
  var LAYOUT = {
    calendar: { mode: 'fill', top: 0.17, bottom: 0.97 },
    door: { mode: 'fit', top: 0.07, min: 0.30 }
  };

  function placeQuad(q, zone) {
    var cfg = LAYOUT[zone] || { mode: 'fit', top: null, min: 0.14 };
    var faceW = (_len(q[0], q[1]) + _len(q[3], q[2])) / 2;
    var faceH = (_len(q[0], q[3]) + _len(q[1], q[2])) / 2;
    /* layout width: the card composes at a readable width and the
       transform scales it to the face — text on a small prop simply
       renders smaller, which is what "on the surface" means */
    var srcW = Math.max(340, Math.min(640, Math.round(faceW)));
    var scale = faceW / srcW;
    var capFrac = cfg.mode === 'fill' ? (cfg.bottom - cfg.top)
                                      : 0.92 - (cfg.top || 0.04);
    var capPx = Math.max(140, Math.round((faceH * capFrac) / scale));
    OV.style.transform = 'none';
    OV.style.left = '0px';
    OV.style.top = '0px';
    OV.style.width = srcW + 'px';
    OV.style.height = cfg.mode === 'fill' ? capPx + 'px' : 'auto';
    OV.style.maxHeight = capPx + 'px';
    OV.style.visibility = 'hidden';
    OV.style.display = 'block';
    var srcH = OV.offsetHeight || 1;
    var frac, t0;
    if (cfg.mode === 'fill') {
      t0 = cfg.top;
      frac = cfg.bottom - cfg.top;
    } else {
      frac = Math.min(capFrac, Math.max(cfg.min || 0, (srcH * scale) / faceH));
      t0 = cfg.top !== null ? cfg.top : Math.max(0.04, (1 - frac) / 2);
      /* a fit card padded up to its minimum keeps the measured height —
         the transform stretches it the small remaining way instead */
    }
    var quad = [_lerp(q[0], q[3], t0), _lerp(q[1], q[2], t0),
                _lerp(q[1], q[2], t0 + frac), _lerp(q[0], q[3], t0 + frac)];
    OV.style.transformOrigin = '0 0';
    OV.style.transform = _quadTransform(srcW, srcH, quad);
    OV.style.visibility = '';
  }

  /* bbox fallback for a face the camera cannot see cleanly */
  function place(rect) {
    var wrapW = WRAP.clientWidth || 1, wrapH = WRAP.clientHeight || 1;
    var margin = 12;
    var pad = Math.round(Math.min(rect.width, rect.height) * 0.06);
    var w = Math.max(280, rect.width - 2 * pad);
    w = Math.min(w, wrapW - 2 * margin);
    var left = rect.left + rect.width / 2 - w / 2;
    left = Math.max(margin, Math.min(left, wrapW - w - margin));
    var topMin = Math.max(76, rect.top + pad);
    var maxH = Math.max(160, Math.min(rect.height - 2 * pad,
                                      wrapH - topMin - 110));
    OV.style.transform = 'none';
    OV.style.width = w + 'px';
    OV.style.maxHeight = maxH + 'px';
    OV.style.left = left + 'px';
    OV.style.visibility = 'hidden';
    OV.style.display = 'block';
    var h = Math.min(OV.offsetHeight || 0, maxH);
    var top = rect.top + (rect.height - h) / 2;
    top = Math.max(topMin, Math.min(top, wrapH - h - 110));
    OV.style.top = top + 'px';
    OV.style.visibility = '';
  }

  function show(zone, d) {
    DOOR.style.display = zone === 'door' ? 'block' : 'none';
    CAL.style.display = zone === 'calendar' ? 'block' : 'none';
    if (d.quad) placeQuad(d.quad, zone); else place(d.rect);
    requestAnimationFrame(function () { OV.classList.add('on'); });
  }

  function hide() {
    OV.classList.remove('on');
    OV.style.display = 'none';
    DOOR.style.display = 'none';
    CAL.style.display = 'none';
    if (heroTick) { clearInterval(heroTick); heroTick = null; }
  }

  window.addEventListener('chf-kitchen-focus', function (ev) {
    var d = (ev && ev.detail) || {};
    if (!d.zone || !d.rect) { hide(); return; }
    if (d.zone === 'door') {
      fetchHero(function (h) {
        if (!h) { hide(); return; }   /* calm or unreachable: the tip answers */
        renderDoor();
        show('door', d);
        /* the countdown pill recomputes from the event's own times on each
           render — the screensaver redraws it the same way */
        if (!heroTick) heroTick = setInterval(renderDoor, 1000);
      });
    } else if (d.zone === 'calendar') {
      try {
        var comp = window.Alpine && window.Alpine.$data(CAL);
        if (comp && comp.loadPacking) comp.loadPacking();
      } catch (e) { /* island not up: the room's own tip still answers */ }
      show('calendar', d);
    } else {
      hide();   /* a zone without a card yet keeps today's tip-only lean-in */
    }
  });
})();
