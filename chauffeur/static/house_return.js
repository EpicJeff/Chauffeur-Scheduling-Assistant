/* A house visit can cross pages; a parent visit must not outlive its user. */
(function () {
  'use strict';
  var base = window.chfBase || '';
  var home = new URL(base + 'house', location.href);
  var onHouse = location.pathname.replace(/\/$/, '') === home.pathname;
  var returnKey = 'chauffeur_house_return', parentKey = 'chauffeur_house_parent';
  var IDLE = 5 * 60 * 1000, timer = null;
  function read(key) { try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch (_) { return null; } }
  function save(key, value) { sessionStorage.setItem(key, JSON.stringify(value)); }
  function target() {
    var saved = read(returnKey);
    try {
      var url = new URL(saved, location.href);
      if (url.origin === home.origin && url.pathname === home.pathname) return url.href;
    } catch (_) {}
    return home.href;
  }
  window.chfHouseParent = function () {
    var session = read(parentKey);
    return session && session.token && Date.now() < session.expires &&
      Date.now() - session.active < IDLE ? session : null;
  };
  function lock(go) {
    var session = read(parentKey);
    sessionStorage.removeItem(parentKey);
    if (session && session.token) {
      fetch(base + 'api/house/session/end', { method: 'POST', keepalive: true,
        headers: { 'X-Member-Token': session.token } }).catch(function () {});
    }
    if (go) { document.documentElement.style.visibility = 'hidden'; location.replace(target()); }
  }
  window.chfHouseRemember = function () {
    var url = new URL(location.href);
    if (onHouse) {
      ['member_token', 'device_token', 'service_token'].forEach(function (key) { url.searchParams.delete(key); });
      save(returnKey, url.href);
    }
  };
  window.chfHouseStartParent = function (result) {
    window.chfHouseRemember();
    save(parentKey, { token: result.token, member: result.member,
      expires: Date.now() + result.expires_in * 1000, active: Date.now() });
  };
  window.chfHouseEndParent = function () { lock(false); };
  window.chfHouseTouchParent = function () {
    var session=window.chfHouseParent();
    if(session){session.active=Date.now();save(parentKey,session);}
  };
  window.chfHouseReturn = function () { lock(true); };
  if (onHouse) lock(false);
  // History entries remember that this was a parent visit even if Back
  // reloads the page instead of restoring it from the browser's cache.
  var protectedVisit = !onHouse && (!!read(parentKey) || !!(history.state || {}).chfHouseVisit);
  if (protectedVisit && window.chfHouseParent())
    history.replaceState(Object.assign({}, history.state || {}, { chfHouseVisit: true }), '', location.href);
  function check() {
    if (protectedVisit && !window.chfHouseParent()) { lock(true); return false; }
    return true;
  }
  function mount() {
    if (!check() || onHouse || !read(returnKey)) return;
    var button = document.createElement('button');
    button.id = 'house-return'; button.type = 'button';
    button.textContent = protectedVisit ? '← Lock & return to house' : '← Back to house';
    button.style.cssText = 'position:fixed;right:16px;top:76px;z-index:100;border:1px solid #bca77b;border-radius:22px;padding:10px 16px;background:#27231eee;color:#fff4da;font:600 14px system-ui;cursor:pointer';
    button.addEventListener('click', window.chfHouseReturn);
    document.body.appendChild(button);
  }
  if (protectedVisit && !window.chfHouseParent()) lock(true);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
  if (protectedVisit) {
    timer = setInterval(check, 1000);
    ['pointerdown', 'keydown'].forEach(function (event) {
      document.addEventListener(event, function () {
        if (!check()) return;
        var session = window.chfHouseParent();
        session.active = Date.now(); save(parentKey, session);
      });
    });
    window.addEventListener('pagehide', function () {
      clearInterval(timer);
      document.documentElement.style.visibility = 'hidden';
    });
    window.addEventListener('pageshow', function () {
      if (check()) { document.documentElement.style.visibility = ''; clearInterval(timer); timer = setInterval(check, 1000); }
    });
    document.addEventListener('visibilitychange', check);
  }
})();
