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
 *   fridge / corkboard / counter / critter laptop / window → the board's
 *               own tile body, one include, mounted per zone through the
 *               kitchenTileIsland shim below; data from ONE lazy
 *               api/home_board?widgets=… fetch, interactive forced off.
 *               The radio keeps its tip: the music card needs the whole
 *               Music Assistant runtime, and a display-only mount of it
 *               would be dead transport chrome.
 *
 * Never writes: every fetch here is a GET, and innerHTML is only ever fed
 * by HeroCard.html, which escapes every field it prints (or cleared).
 */
/* The generic tile island's scope: `t` (the mounted tile) plus the few
   board-scope helpers the mounted branches reach for. Layout shims are
   deliberately dumb — collageSpan '' falls back to a uniform grid — and
   the write-side ones (openPetEditor and friends) stay UNDEFINED, which
   the branches themselves treat as "draw disabled". Defined before Alpine
   boots (alpine.min.js is deferred; this file is a classic script). */
/* Whether the overlay is handing a REAL height down to the card it is
   wearing. A `fill` zone gives one (the layout caps the element in pixels);
   a `fit` zone does not — it measures the content, so a card that put
   `flex-1` on itself there would measure zero. The board answers the same
   question with `fillsHere`, and the branches that ask it are the ones with
   a scroll box inside (drives, cars). Written by the focus listener below,
   before the island is handed its tile. */
var chfOverlayFills = false;
window.kitchenTileIsland = function () {
  var base = (window.chfBase !== undefined ? window.chfBase : '');
  return {
    t: null,
    apiBase: base,
    board: {},
    hero: {},
    collageSpan: function () { return ''; },
    fillsHere: function () { return chfOverlayFills; },
    momentSrc: function (m) {
      var att = (m && m.attachment) || {};
      var u = (m && (m.poster_url || m.media_url)) || att.url || '';
      return u ? base + String(u).replace(/^\//, '') : (att.data_url || '');
    },
    openBoardMoment: function (ev, m) {
      /* the same full-screen overlay a fresh moment pops on the wall —
         moments_hearth is already on this page */
      if (typeof window.showMomentOverlayKiosk === 'function') {
        window.showMomentOverlayKiosk(m);
      }
    },
    link: function () { return '#'; },
    tone: function (hex, fb) {
      return window.HeroCard ? HeroCard.tone(hex, fb, true) : (hex || fb);
    }
  };
};

(function () {
  'use strict';
  var BASE = (window.chfBase !== undefined ? window.chfBase : '');
  var WRAP = document.getElementById('kitchen-wrap');
  var OV = document.getElementById('focus-overlay');
  var DOOR = document.getElementById('overlay-door');
  var CAL = document.getElementById('overlay-calendar');
  var TILE = document.getElementById('overlay-tile');
  var MUSIC = document.getElementById('overlay-music');
  var OPEN = document.getElementById('overlay-open');
  if (!WRAP || !OV || !DOOR || !CAL || !TILE) return;

  /* where the open-chip goes: the zone's own family page. Card taps now do
     card things, so the ↗ is the door through. */
  var PAGES = { door: 'home', calendar: 'calendar', fridge: 'moments',
                board: 'lists', counter: 'meals', pet: 'chores',
                window: 'calendar', radio: 'music',
                /* the garage's page is the CAR EDITOR: /cars is not a route,
                   the fleet lives in Config beside the drivers */
                garage: 'config' };
  /* ADMIN destinations are desktop-only. A wall panel is the most shared
     screen in the house and must never land on Config, so the open-chip
     simply does not appear there — the fleet card already answers. */
  var ADMIN_PAGES = { garage: true };
  var IS_PANEL = /[?&]panel=true/.test(window.location.search);
  function pageFor(zone) {
    var p = PAGES[zone];
    return (p && ADMIN_PAGES[zone] && IS_PANEL) ? '' : (p || '');
  }

  /* which board tile a zone wears on focus. The garage's card is the whole
     fleet, and that is the point of it: the bay parks two cars, so a
     household with four had no surface that showed them all. The kitchen
     page has no garage zone, so this entry is inert there. */
  var ZONE_TILES = { fridge: 'moments', board: 'shopping_list',
                     counter: 'meals', pet: 'pets', window: 'weather',
                     garage: 'cars' };
  var WIDGETS = 'moments,shopping_list,meals,pets,weather,cars';

  /* board payload, cached briefly: a lean-in is a moment, not a poll.
     One request carries the hero (top-level, always) and the five tile
     types the zones wear — `?widgets=` builds exactly those, not the
     household's whole wall. */
  var payload = null, payloadAt = 0, heroTick = null;
  var hero = null;
  var BOARD_TTL = 60000;

  function fetchBoard(cb, isRetry) {
    if (payload !== null && Date.now() - payloadAt < BOARD_TTL) { cb(payload); return; }
    fetch(BASE + 'api/home_board?widgets=' + WIDGETS, { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      })
      .then(function (b) {
        payloadAt = Date.now();
        payload = b || {};
        var h = payload.hero || {};
        /* the screensaver's own test: a done day has no "next" */
        hero = (!h.all_done && h.next) ? h.next : false;
        cb(payload);
      })
      .catch(function () {
        /* one retry: a page's very first request is occasionally aborted
           (proxied setups, cold connections) and a lean-in should not
           lose its card to that */
        if (!isRetry) {
          setTimeout(function () { fetchBoard(cb, true); }, 350);
        } else {
          cb(null);
        }
      });
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
    radio: { mode: 'fit', top: null },
    door: { mode: 'fit', top: 0.07 },
    fridge: { mode: 'fill', top: 0.06, bottom: 0.94 },
    board: { mode: 'fill', top: 0.07, bottom: 0.93 },
    counter: { mode: 'fit', top: null },
    pet: { mode: 'fill', top: 0.05, bottom: 0.95 },
    window: { mode: 'fit', top: 0.34 },
    /* the garage's face is its BACK WALL, and the fleet list is pinned to
       the upper part of it — the bottom of that wall is behind the cars and
       the workbench, and a card hung down there would be reading a list off
       a bonnet. `fill` because the rows scroll: a fourth car lengthens the
       scroll inside the card, never the card. */
    garage: { mode: 'fill', top: 0.15, bottom: 0.66 }
  };

  function placeQuad(q, zone) {
    var cfg = LAYOUT[zone] || { mode: 'fit', top: null };
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
      /* NEVER stretch or squish a fit card: the mapped slice is exactly
         the content's own height on the face (maxHeight already caps
         srcH, so the cap can't distort either). A stretched card is what
         breaks the on-the-surface illusion. */
      frac = Math.min(capFrac, (srcH * scale) / faceH);
      t0 = cfg.top !== null ? cfg.top : Math.max(0.04, (1 - frac) / 2);
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
    TILE.style.display = ZONE_TILES[zone] ? 'flex' : 'none';   /* flex: the height chain collage grids need */
    /* leaving a tile zone for the door, the calendar or the radio hides the
       island but does NOT unmount the card — only `hide()` cleared `t`, and
       these three branches never call it. The card then sat behind a hidden
       overlay still polling. Dropping the tile here tears it down, which is
       what stops its timers (components/card_timers.html). */
    if (!ZONE_TILES[zone]) {
      var tc = tileScope();
      if (tc && tc.t) tc.t = null;
    }
    if (MUSIC) MUSIC.style.display = zone === 'radio' ? 'block' : 'none';
    if (OPEN) {
      var page = pageFor(zone);
      OPEN.href = page ? BASE + page : '#';
      OPEN.style.display = page ? '' : 'none';
    }
    if (d.quad) placeQuad(d.quad, zone); else place(d.rect);
    requestAnimationFrame(function () { OV.classList.add('on'); });
  }

  function tileScope() {
    try { return window.Alpine && window.Alpine.$data(TILE); }
    catch (e) { return null; }
  }

  function hide() {
    OV.classList.remove('on');
    OV.style.display = 'none';
    DOOR.style.display = 'none';
    CAL.style.display = 'none';
    TILE.style.display = 'none';
    if (MUSIC) MUSIC.style.display = 'none';
    var c = tileScope();
    if (c && c.t) c.t = null;
    if (heroTick) { clearInterval(heroTick); heroTick = null; }
  }

  /* A late fetch or Alpine tick cannot restore a superseded focus. */
  var focusRevision = 0;
  window.addEventListener('chf-kitchen-focus', function (ev) {
    var revision = ++focusRevision;
    var d = (ev && ev.detail) || {};
    /* set BEFORE the island renders (`c.t = tile` below is what draws it),
       not in `show`, which runs a tick later — a card asking `fillsHere` on
       its first render would otherwise read the previous zone's answer */
    chfOverlayFills = ((LAYOUT[d.zone] || {}).mode === 'fill');
    if (!d.zone || !d.rect) { hide(); return; }
    if (d.zone === 'door') {
      fetchBoard(function (b) {
        if (revision !== focusRevision) return;
        if (!b || !hero) { hide(); return; }   /* calm or unreachable: the tip answers */
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
    } else if (d.zone === 'radio' && MUSIC) {
      if (!MUSIC.__started && typeof window.startMusicWidget === 'function') {
        MUSIC.__started = true;
        try { window.startMusicWidget(); } catch (e) { /* MA absent: the
          widget's own empty states answer */ }
      }
      show('radio', d);
    } else if (ZONE_TILES[d.zone]) {
      var want = ZONE_TILES[d.zone];
      fetchBoard(function (b) {
        if (revision !== focusRevision) return;
        var tiles = (b && b.tiles) || [];
        var tile = null;
        for (var i = 0; i < tiles.length; i++) {
          if (tiles[i] && tiles[i].type === want) { tile = tiles[i]; break; }
        }
        /* a quiet tile keeps the tip: an empty card on a wall answers
           nothing the one-line headline was not already answering */
        if (!tile || !tile.data || tile.data.empty) { hide(); return; }
        var c = tileScope();
        if (!c) { hide(); return; }
        c.t = tile;
        /* Alpine renders the island on its own tick; place after it, so a
           fit-mode zone measures real content instead of an empty div */
        window.Alpine.nextTick(function () {
          if (revision === focusRevision) show(d.zone, d);
        });
      });
    } else {
      hide();   /* a zone without a card yet keeps today's tip-only lean-in */
    }
  });
})();
