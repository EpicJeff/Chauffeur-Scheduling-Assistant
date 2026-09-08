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
    DOOR.innerHTML = HeroCard.html(hero, { compact: true });
  }

  /* Lay the card over the furniture the camera framed: centred on the
     zone's rect, clamped to a readable width and kept clear of the title
     (76px) and the Ask-Argyle bar (bottom ~110px). */
  function place(rect) {
    var wrapW = WRAP.clientWidth || 1, wrapH = WRAP.clientHeight || 1;
    var margin = 12;
    var w = Math.max(300, Math.min(560, rect.width));
    w = Math.min(w, wrapW - 2 * margin);
    var left = rect.left + rect.width / 2 - w / 2;
    left = Math.max(margin, Math.min(left, wrapW - w - margin));
    var top = Math.max(76, rect.top);
    var maxH = Math.max(180, wrapH - top - 110);
    OV.style.left = left + 'px';
    OV.style.top = top + 'px';
    OV.style.width = w + 'px';
    OV.style.maxHeight = maxH + 'px';
  }

  function show(zone, rect) {
    DOOR.style.display = zone === 'door' ? 'block' : 'none';
    CAL.style.display = zone === 'calendar' ? 'block' : 'none';
    place(rect);
    OV.style.display = 'block';
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
        show('door', d.rect);
        /* the countdown pill recomputes from the event's own times on each
           render — the screensaver redraws it the same way */
        if (!heroTick) heroTick = setInterval(renderDoor, 1000);
      });
    } else if (d.zone === 'calendar') {
      try {
        var comp = window.Alpine && window.Alpine.$data(CAL);
        if (comp && comp.loadPacking) comp.loadPacking();
      } catch (e) { /* island not up: the room's own tip still answers */ }
      show('calendar', d.rect);
    } else {
      hide();   /* a zone without a card yet keeps today's tip-only lean-in */
    }
  });
})();
