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
  /* the study's card surface: only the house page carries it (the kitchen
     has no study zones), so every study branch below is inert without it */
  var STUDY = document.getElementById('overlay-study');
  if (!WRAP || !OV || !DOOR || !CAL || !TILE) return;

  /* where the open-chip goes: the zone's own family page. Card taps now do
     card things, so the ↗ is the door through. */
  var PAGES = { door: 'home', calendar: 'calendar', fridge: 'moments',
                board: 'lists', counter: 'meals', pet: 'chores',
                window: 'calendar', radio: 'music',
                /* the garage's page is the CAR EDITOR: /cars is not a route,
                   the fleet lives in Config beside the drivers */
                garage: 'config',
                /* the study's zones open the same pages the room's own
                   second tap does (house.js STUDY_ZONE_META) */
                study_board: 'mind', study_desk: 'mind', study_tray: 'intake',
                study_stickies: 'dashboard', study_calendar: 'dashboard',
                study_window: 'mind', study_contracts: 'dashboard',
                study_binders: 'programs', study_map: 'trips' };
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
        hero = payload.hero || {};
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
    if (hero && hero.next && window.HeroCard) {
      DOOR.innerHTML = HeroCard.html(hero.next, { isLight: true });
      return;
    }
    var title = hero && hero.all_done ? "Everyone's home 🏠"
              : hero && hero.unbuilt ? 'Building the schedule…'
              : 'No drives today';
    var detail = hero && hero.all_done ? 'Nothing left to drive today.'
               : hero && hero.unbuilt ? 'Nothing has been worked out yet.'
               : 'Nothing on the schedule needs a driver.';
    /* the BOARD's own band (not the screensaver's dark scrim): its inks are
       panel-text/panel-dim, which kitchen.html defines inside the overlay
       as the room's own paper-and-ink palette */
    renderDoorMessage(title, detail);
  }

  function renderDoorMessage(title, detail) {
    DOOR.textContent = '';
    var box = document.createElement('div');
    box.className = 'p-6 text-center';
    var heading = document.createElement('div');
    heading.className = 'text-2xl font-black panel-text';
    heading.textContent = title;
    box.appendChild(heading);
    if (detail) {
      var copy = document.createElement('div');
      copy.className = 'panel-dim mt-1';
      copy.textContent = detail;
      box.appendChild(copy);
    }
    DOOR.appendChild(box);
  }

  function renderDoorLoading() {
    renderDoorMessage('Checking what’s next…', '');
  }

  /* ---- the study's card -------------------------------------------------
     PIN-scoped by construction: the rows come from window.chfStudyCard,
     which house.js builds off the furniture it fetched with the parent's
     own visit token -- never from api/home_board, which a wall device reads
     without a person. Every word here is family-typed (a thread title, a
     finding's sentence) and every one of them lands through textContent;
     this function assigns no innerHTML (the escaping-sink pin in
     tests/test_kitchen_overlay.py holds for the whole file).

     Shape, by sibling: the heading is the door card's own two-line message
     (renderDoorMessage above -- panel-text over panel-dim, the overlay's
     paper inks); each row is the agenda's row vocabulary (docs/
     ui_design_guide.md, components/agenda_row.html: `rounded-lg px-2.5
     py-1.5` on the `.agenda-event` fill the overlay already remaps to
     paper, a 4px left bar carrying the row's state) with the study's OWN
     painted inks on the bar -- the red its calendar face gives an uncovered
     day, the amber its desk gives a due step (study.js DETAIL). */
  var STUDY_TONE = { bad: '#a8452e', warn: '#a05a18' };
  var STUDY_TITLE = { study_board: 'Connections board', study_desk: 'Plans in hand',
                      study_tray: 'Intake tray', study_stickies: 'Findings',
                      study_calendar: 'Coverage calendar', study_window: 'Family baseline',
                      study_contracts: 'Agreements', study_binders: 'Program binders',
                      study_map: 'Travel map' };
  function renderStudy(card) {
    STUDY.textContent = '';
    var head = document.createElement('div');
    head.className = 'flex items-start gap-2 mb-2';
    var title = document.createElement('div');
    title.className = 'text-sm font-bold panel-text';
    title.textContent = STUDY_TITLE[card.zone] || 'Study';
    head.appendChild(title);
    /* the header's summary only beside rows: an empty card's one sentence
       is the summary already, and it must not be said twice */
    if (card.summary && card.rows.length) {
      var sum = document.createElement('div');
      sum.className = 'text-[11px] font-semibold panel-dim ml-auto text-right';
      sum.textContent = card.summary;
      head.appendChild(sum);
    }
    STUDY.appendChild(head);
    if (!card.rows.length) {
      /* the honest empty state (docs/ui_design_guide.md): a muted sentence,
         never a blank card -- the /study fallback's own 'All quiet' stance */
      var empty = document.createElement('div');
      empty.className = 'text-xs italic panel-dim';
      empty.textContent = card.empty || 'Nothing here';
      STUDY.appendChild(empty);
      return;
    }
    var list = document.createElement('div');
    list.className = 'flex flex-col gap-1';
    card.rows.forEach(function (r) {
      var row = document.createElement('div');
      row.className = 'agenda-event rounded-lg px-2.5 py-1.5 flex items-start gap-2';
      var bar = document.createElement('div');
      bar.className = 'w-1 self-stretch rounded shrink-0';
      bar.style.background = STUDY_TONE[r.tone] || 'rgba(43,35,24,.18)';
      row.appendChild(bar);
      var body = document.createElement('div');
      body.className = 'min-w-0 flex-1';
      var text = document.createElement('div');
      text.className = 'text-sm font-bold panel-text break-words leading-snug';
      text.textContent = r.text;
      body.appendChild(text);
      if (r.note) {
        var note = document.createElement('div');
        note.className = 'text-[11px] font-semibold panel-dim';
        note.textContent = r.note;
        body.appendChild(note);
      }
      row.appendChild(body);
      list.appendChild(row);
    });
    STUDY.appendChild(list);
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
    garage: { mode: 'fill', top: 0.15, bottom: 0.66 },
    /* the study's card zones. The connections board is a cork face like
       the kitchen's, so it takes the same band; the wall calendar is a
       sheet; the window's card stands on the sill, so it anchors low on
       the glass rather than across it; everything else is a prop on the
       desk or shelf and takes its height from what it has to say. */
    study_board: { mode: 'fill', top: 0.07, bottom: 0.93 },
    study_calendar: { mode: 'fill', top: 0.12, bottom: 0.96 },
    /* the baseline list hangs on the window GLASS (the face is the pane,
       not the sill card): anchored high, as tall as its six signs */
    study_window: { mode: 'fit', top: 0.06 },
    /* the wall map: the trip list hangs from the top of the sheet and is
       as tall as its trips (one trip is not a sheet of empty paper) */
    study_map: { mode: 'fit', top: 0.08 }
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
    if (STUDY) STUDY.style.display = /^study_/.test(zone) ? 'block' : 'none';
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
    /* emptied, not just hidden: the rows are parent-only words and the
       card must not outlive the focus that earned it */
    if (STUDY) { STUDY.style.display = 'none'; STUDY.textContent = ''; }
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
      renderDoorLoading();
      show('door', d);
      fetchBoard(function (b) {
        if (revision !== focusRevision) return;
        if (!b) {
          hero = { unbuilt: true };
        }
        renderDoor();
        show('door', d);
        /* the countdown pill recomputes from the event's own times on each
           render — the screensaver redraws it the same way */
        if (hero && hero.next && !heroTick)
          heroTick = setInterval(renderDoor, 1000);
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
    } else if (STUDY && /^study_/.test(d.zone)) {
      /* no fetch: the rows are already on the page, fetched with the
         parent's token when the study was unlocked. A zone with nothing to
         list keeps the tip (the kitchen's own quiet-tile rule) and the
         room shows its painted detail instead -- house_study.js's `card`
         is the one predicate both sides read. */
      var sc = window.chfStudyCard ? window.chfStudyCard(d.zone) : null;
      if (!sc) { hide(); return; }   /* an instrument zone: its paint answers */
      renderStudy(sc);
      show(d.zone, d);
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
