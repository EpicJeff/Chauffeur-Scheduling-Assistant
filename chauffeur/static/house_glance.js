/* Exterior clock and next activity use the screensaver's presentation. */
(function () {
  'use strict';
  var root = document.getElementById('house-glance');
  if (!root) return;
  var clock = root.querySelector('.glance-clock');
  var card = root.querySelector('.glance-next');
  var next = null, timer = null, pending = false, fetchedAt = 0;
  var base = window.chfBase !== undefined ? window.chfBase : '';
  function visible() {
    return !document.hidden && window.chfHouseMode &&
      window.chfHouseMode() === 'exterior';
  }
  function paint() {
    window.chfGlanceClock(clock);
    var over = next && next.end && Date.now() > new Date(next.end).getTime() + 120000;
    card.hidden = !next || !!over;
    if (!card.hidden) card.innerHTML = HeroCard.html(next, { compact: true });
  }
  async function refresh(force) {
    if (!visible() || pending || (!force && Date.now() - fetchedAt < 180000)) return;
    pending = true;
    try {
      var response = await fetch(base + 'api/home_board?widgets=hero', { credentials: 'same-origin' });
      if (response.ok) {
        var hero = ((await response.json()) || {}).hero || {};
        next = !hero.all_done && hero.next ? hero.next : null;
        fetchedAt = Date.now();
      }
    } finally { pending = false; }
    if (visible()) paint();
  }
  function tick() { paint(); refresh(false).catch(function () {}); }
  function sync() {
    root.hidden = !visible();
    if (timer) { clearInterval(timer); timer = null; }
    if (!root.hidden) { tick(); timer = setInterval(tick, 15000); }
  }
  window.addEventListener('chf-house-view', sync);
  window.addEventListener('chf-hybrid-room', sync);
  window.addEventListener('pageshow', sync);
  document.addEventListener('visibilitychange', sync);
  function invalidate() {
    fetchedAt = 0;
    refresh(true).catch(function () {});
  }
  document.addEventListener('chf-server-update', invalidate);
  document.addEventListener('chf-pack-change', invalidate);
  window.addEventListener('pagehide', function () { clearInterval(timer); });
  sync();
})();
