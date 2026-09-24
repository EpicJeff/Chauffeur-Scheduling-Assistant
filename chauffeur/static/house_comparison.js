/* Opt-in living-room comparison. Hybrid owns no renderer or animation loop;
   cards, authentication and navigation back from managed pages remain shared. */
(function () {
  'use strict';
  var toolbar = document.getElementById('house-comparison');
  if (!toolbar) return;
  var hybrid = document.body.dataset.houseRender === 'hybrid';
  var light = document.getElementById('house-compare-light');
  var readyLabel = document.getElementById('house-compare-ready');
  var stats = window.chfHouseComparison = { renderer: hybrid ? 'hybrid' : '3d', readyMs: null };
  var query = new URL(location.href);
  light.value = ['day', 'night'].indexOf(query.searchParams.get('light')) >= 0
    ? query.searchParams.get('light') : 'auto';
  function links() {
    toolbar.querySelectorAll('[data-render]').forEach(function (link) {
      var url = new URL(location.href);
      url.searchParams.set('render', link.dataset.render);
      link.href = url.href;
    });
    var exit = new URL(location.href);
    ['compare', 'render', 'light'].forEach(function (key) { exit.searchParams.delete(key); });
    document.getElementById('house-compare-exit').href = exit.href;
  }
  function ready() {
    if (stats.readyMs !== null) return;
    stats.readyMs = Math.round(performance.now());
    readyLabel.textContent = 'Room ready in ' + (stats.readyMs / 1000).toFixed(2) +
      ' s from navigation on this visit. ' + (hybrid ? 'No WebGL scene loaded.' : 'Using the device’s selected 3D quality.');
  }
  links();
  // Shared navigation copies the current query to every anchor on DOM ready.
  // Restore these intentional variant/exit URLs after that decoration runs.
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', links);
  light.addEventListener('change', function () {
    var url = new URL(location.href);
    url.searchParams.delete('day');
    if (light.value === 'auto') url.searchParams.delete('light');
    else url.searchParams.set('light', light.value);
    history.replaceState(history.state, '', url.href);
    window.HOUSE_COMPARE_NIGHT = light.value === 'auto' ? null : light.value === 'night';
    links();
    if (hybrid) paintLight();
    else if (window.chfHouseRefresh) window.chfHouseRefresh();
  });
  window.addEventListener('popstate', function () {
    var choice = new URL(location.href).searchParams.get('light');
    light.value = ['day', 'night'].indexOf(choice) >= 0 ? choice : 'auto';
    window.HOUSE_COMPARE_NIGHT = light.value === 'auto' ? null : light.value === 'night';
    links();
    if (hybrid) paintLight();
  });

  if (!hybrid) {
    if (window.chfHouseEnterRoom) window.chfHouseEnterRoom('living');
    var wait = setInterval(function () {
      var nav = window.chfNavProbe && window.chfNavProbe({ settled: true });
      var labels = Array.from(document.querySelectorAll('.house-hint-label')).map(function (el) { return el.textContent.trim(); });
      if (nav && nav.mode === 'living' && ['Radio', 'Critters', 'Home ledger', 'Program book'].every(function (s) { return labels.indexOf(s) >= 0; })) {
        clearInterval(wait); ready();
      } else if (performance.now() > 120000) {
        clearInterval(wait); readyLabel.textContent = '3D did not become ready within two minutes. Hybrid is available above.';
      }
    }, 100);
    window.addEventListener('pagehide', function () { clearInterval(wait); });
    return;
  }

  var state = null, stateError = false, pictureError = false, paintRevision = 0;
  var sunTimer = null, inFlight = null, controller = null, stopped = false;
  var status = document.getElementById('hybrid-status');
  var day = document.getElementById('hybrid-day'), night = document.getElementById('hybrid-night');
  var imageLoads = new Map();
  var entries = [
    { key: 'music', label: 'Radio', x: .218, y: .256,
      icon: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M5 7l12-4M6 11h7M6 14h7M6 17h7"/><circle cx="17" cy="14" r="2"/>' },
    { key: 'pets', label: 'Critters', x: .445, y: .532,
      icon: '<ellipse cx="12" cy="16" rx="5" ry="4"/><ellipse cx="5" cy="9" rx="2" ry="3"/><ellipse cx="10" cy="5" rx="2" ry="3"/><ellipse cx="16" cy="5" rx="2" ry="3"/><ellipse cx="20" cy="10" rx="2" ry="3"/>' },
    { key: 'tasks', label: 'Home ledger', x: .800, y: .716,
      icon: '<rect x="5" y="3" width="15" height="18" rx="2"/><path d="M8 3v18M11 8h6M11 12h6M11 16h4"/>' },
    { key: 'programs', label: 'Program book', x: .905, y: .661,
      icon: '<path d="M12 5C8 3 4 3 2 4v16c3-1 6-1 10 1 4-2 7-2 10-1V4c-3-1-6-1-10 1v16"/>' }
  ];
  function button(entry, anchored) {
    var el = document.createElement('button'); el.type = 'button';
    el.dataset.card = entry.key; el.setAttribute('aria-label', entry.label);
    el.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + entry.icon + '</svg>';
    var label = document.createElement('span'); label.textContent = entry.label;
    if (anchored) {
      el.className = 'hybrid-marker'; label.className = 'hybrid-marker-label';
      el.style.left = entry.x * 100 + '%'; el.style.top = entry.y * 100 + '%';
    }
    el.appendChild(label);
    var count = document.createElement('span'); count.className = 'hybrid-count'; count.hidden = true;
    el.appendChild(count);
    el.addEventListener('click', function () {
      window.chfHybridEnter(entry, el);
    });
    el.addEventListener('pointerenter', function () { window.chfHybridWarm(entry.key); });
    el.addEventListener('focus', function () { window.chfHybridWarm(entry.key); });
    return el;
  }
  entries.forEach(function (entry) {
    document.getElementById('hybrid-hotspots').appendChild(button(entry, true));
    document.getElementById('hybrid-shortcuts').appendChild(button(entry, false));
  });
  function placeMarkers() {
    entries.forEach(function (entry) {
      var point = window.chfHybridProject(entry);
      var marker = document.querySelector('#hybrid-hotspots [data-card="' + entry.key + '"]');
      marker.style.left = point.x * 100 + '%'; marker.style.top = point.y * 100 + '%';
    });
  }
  placeMarkers();
  window.addEventListener('resize', placeMarkers);
  function message() {
    if (window.chfHybridViewing && window.chfHybridViewing()) return;
    status.textContent = pictureError ? 'Room artwork could not load. The cards are still available.'
      : stateError ? 'Live updates are unavailable. Showing the last room lighting.'
      : 'Choose an object to move closer.';
  }
  function load(image) {
    if (image.complete && image.naturalWidth) return Promise.resolve();
    if (imageLoads.has(image)) return imageLoads.get(image);
    var promise = new Promise(function (resolve, reject) {
      function finish(ok) {
        image.onload = image.onerror = null;
        if (ok) resolve(); else { imageLoads.delete(image); reject(new Error('image unavailable')); }
      }
      image.onload = function () { finish(true); };
      image.onerror = function () { finish(false); };
      image.src = image.dataset.src;
    });
    imageLoads.set(image, promise); return promise;
  }
  function outsideNight() {
    if (typeof window.HOUSE_COMPARE_NIGHT === 'boolean') return window.HOUSE_COMPARE_NIGHT;
    var outside = state && state.window;
    if (!outside || typeof outside.night !== 'boolean') return true;
    var flip = Date.parse(outside.next_sun_change || '');
    return Number.isFinite(flip) && Date.now() >= flip ? !outside.night : outside.night;
  }
  function paintLight() {
    var dark = outsideNight(), image = dark ? night : day, revision = ++paintRevision;
    window.chfHybridLight(dark);
    load(image).then(function () {
      if (revision !== paintRevision || stopped) return;
      day.classList.toggle('is-active', !dark); night.classList.toggle('is-active', dark);
      document.getElementById('hybrid-room-frame').dataset.light = dark ? 'night' : 'day';
      pictureError = false; message(); requestAnimationFrame(function () { requestAnimationFrame(ready); });
    }).catch(function () {
      if (revision === paintRevision) { pictureError = true; message(); }
    });
    clearTimeout(sunTimer);
    var flip = Date.parse(state && state.window && state.window.next_sun_change || '');
    if (light.value === 'auto' && Number.isFinite(flip) && flip > Date.now()) {
      sunTimer = setTimeout(paintLight, Math.min(flip - Date.now() + 50, 2147483647));
    }
  }
  function accept(data) {
    state = data; stateError = false;
    window.dispatchEvent(new CustomEvent('chf-house-state', { detail: state }));
    document.querySelectorAll('#hybrid-room [data-card]').forEach(function (el) {
      var signal = (state.attention || {})[el.dataset.card];
      var n = signal && signal.known && Number.isFinite(signal.count) ? Math.max(0, signal.count) : 0;
      var badge = el.querySelector('.hybrid-count'); badge.hidden = !n; badge.textContent = String(n);
      var entry = entries.find(function (e) { return e.key === el.dataset.card; });
      el.setAttribute('aria-label', entry.label + (n ? ', ' + n + ' need attention' : ''));
    });
    paintLight();
  }
  function poll() {
    if (inFlight || stopped) return inFlight;
    controller = new AbortController();
    var timeout = setTimeout(function () { controller.abort(); }, 10000);
    inFlight = fetch(window.HOUSE_STATE_URL, { credentials: 'same-origin', signal: controller.signal })
      .then(function (response) { if (!response.ok) throw new Error('state unavailable'); return response.json(); })
      .then(accept).catch(function () { if (!stopped) { stateError = true; paintLight(); } })
      .finally(function () { clearTimeout(timeout); inFlight = null; });
    return inFlight;
  }
  window.chfHouseState = function () { return state; };
  window.chfHouseRefresh = poll;
  window.chfHouseMode = function () { return 'living'; };
  var polling = setInterval(function () { if (!document.hidden) poll(); }, 60000);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) { paintLight(); poll(); } });
  window.addEventListener('pagehide', function () {
    stopped = true; clearInterval(polling); clearTimeout(sunTimer); if (controller) controller.abort();
  });
  window.addEventListener('pageshow', function (event) {
    if (!event.persisted) return;
    stopped = false;
    polling = setInterval(function () { if (!document.hidden) poll(); }, 60000);
    paintLight(); poll();
  });
  poll();
})();
