/* Fixed camera destinations: approach, change perspective, use the object, return.
   The existing live card is mounted in the scene rather than a modal backdrop. */
(function () {
  'use strict';
  var frame = document.getElementById('hybrid-room-frame');
  if (!frame) return;
  var overview = document.getElementById('hybrid-overview');
  var detail = document.getElementById('hybrid-detail');
  var controls = document.getElementById('hybrid-detail-controls');
  var shortcuts = document.getElementById('hybrid-shortcuts');
  var back = document.getElementById('hybrid-view-back');
  var status = document.getElementById('hybrid-status');
  var images = Array.from(detail.querySelectorAll('img'));
  var loads = new Map(), visited = new Map();
  var active = null, trigger = null, dark = true, revision = 0, navigation = 0;
  var card = null;
  var motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  controls.appendChild(document.getElementById('house-life'));
  // A refresh returns to the room; only this document owns its camera history.
  var initial = Object.assign({}, history.state); delete initial.chfHybridView;
  history.replaceState(initial, '', location.href);

  // The artwork fills the viewport with a centered cover crop. Project both
  // markers and the approach origin through the same crop as the visible image.
  window.chfHybridProject = function (entry) {
    var width = frame.clientWidth, height = frame.clientHeight;
    var scale = Math.max(width / 1536, height / 1024);
    return {x:(entry.x * 1536 * scale + (width - 1536 * scale) / 2) / width,
      y:(entry.y * 1024 * scale + (height - 1024 * scale) / 2) / height};
  };

  function picture(key) {
    return images.find(function (img) { return img.dataset.view === key && img.dataset.light === (dark ? 'night' : 'day'); });
  }
  function load(img) {
    if (loads.has(img)) return loads.get(img);
    var pending = new Promise(function (resolve, reject) {
      img.onload = function () {
        var decode = img.decode ? img.decode() : Promise.resolve();
        decode.then(resolve, reject);
      };
      img.onerror = function () { reject(new Error('View artwork unavailable')); };
      img.src = img.dataset.src;
    }).catch(function (err) { loads.delete(img); throw err; });
    loads.set(img, pending);
    return pending;
  }
  function phase(name) { frame.dataset.phase = name; }
  function waitForMove() {
    return new Promise(function (resolve) { setTimeout(resolve, motion.matches ? 0 : 560); });
  }
  function show() {
    if (!active) return;
    var entry = active, img = picture(entry.key), ticket = ++revision;
    frame.setAttribute('aria-busy', 'true');
    load(img).then(async function () {
      if (ticket !== revision || active !== entry) return;
      images.forEach(function (other) { other.classList.toggle('is-active', other === img); });
      img.alt = entry.label + ' seen from close by in the living room';
      detail.dataset.light = img.dataset.light;
      if (entry.key === 'pets') frame.style.setProperty('--habitat-art', 'url("' + img.src + '")');
      if (entry.key === 'tasks' || entry.key === 'programs') frame.style.setProperty('--book-art', 'url("' + img.src + '")');
      if (entry.key === 'music') {
        frame.style.setProperty('--radio-art', 'url("' + img.src + '")');
        document.getElementById('house-radio').dataset.light = img.dataset.light;
      }
      if (frame.dataset.phase !== 'detail') {
        phase('entering');
        await waitForMove();
        if (ticket !== revision || active !== entry) return;
        phase('detail');
      }
      frame.setAttribute('aria-busy', 'false');
      status.textContent = entry.label + ' · Return to the living room to choose another object.';
      if (card !== entry.key) {
        card = entry.key;
        if (entry.key === 'music') window.HouseRadio.open();
        else window.dispatchEvent(new CustomEvent('chf-house-open', { detail: entry.key }));
      }
    }).catch(function () {
      if (ticket !== revision || active !== entry) return;
      frame.setAttribute('aria-busy', 'false');
      status.textContent = 'This perspective could not load. Return to the room and try again.';
      back.focus();
    });
  }
  function enter(entry, button, remember) {
    if (active) return;
    active = entry; trigger = button; card = null; ++navigation;
    visited.set(entry.key, {entry:entry, trigger:button});
    if (remember) history.pushState(Object.assign({}, history.state, {chfHybridView:entry.key}), '', location.href);
    frame.dataset.view = entry.key;
    var point = window.chfHybridProject(entry);
    overview.style.transformOrigin = (point.x * 100) + '% ' + (point.y * 100) + '%';
    overview.style.setProperty('--approach-x', ((.35 - point.x) * 100) + '%');
    overview.style.setProperty('--approach-y', ((.5 - point.y) * 100) + '%');
    overview.inert = true; shortcuts.inert = true;
    detail.hidden = false; detail.setAttribute('aria-label', entry.label + ' close-up');
    back.hidden = false; back.focus();
    phase('loading');
    status.textContent = 'Moving closer to ' + entry.label.toLowerCase() + '…';
    show();
  }
  async function leave(fromHistory) {
    if (!active) return;
    active = null; card = null; ++revision;
    window.HouseRadio.close();
    var ticket = ++navigation;
    phase('leaving');
    frame.setAttribute('aria-busy', 'false');
    window.dispatchEvent(new CustomEvent('chf-house-close'));
    if (!fromHistory && history.state && history.state.chfHybridView) history.back();
    await waitForMove();
    if (ticket !== navigation) return;
    detail.hidden = true; back.hidden = true;
    images.forEach(function (img) { img.classList.remove('is-active'); });
    frame.dataset.view = 'room'; phase('room');
    overview.inert = false; shortcuts.inert = false;
    status.textContent = 'Choose an object to move closer.';
    // If the viewport changed during the visit, focus its visible counterpart.
    var destination = trigger;
    if (destination && !destination.offsetWidth) destination = Array.from(document.querySelectorAll('#hybrid-room [data-card]'))
      .find(function (el) { return el.dataset.card === trigger.dataset.card && el.offsetWidth; });
    if (destination) destination.focus({preventScroll:true});
  }
  window.chfHybridEnter = function (entry, button) { enter(entry, button, true); };
  window.chfHybridWarm = function (key) { var img = picture(key); if (img) load(img).catch(function () {}); };
  window.chfHybridViewing = function () { return !!active || frame.dataset.phase === 'leaving'; };
  window.chfHybridLight = function (night) { if (dark === night) return; dark = night; if (active) show(); };
  back.addEventListener('click', function () { leave(false); });
  window.addEventListener('chf-house-closed', function () { leave(false); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && active?.key === 'pets' && !event.defaultPrevented && window.chfHabitatCloseOverlay?.()) { event.preventDefault(); return; }
    if (event.key === 'Escape' && active && !event.defaultPrevented && window.chfBookCloseLesson?.()) { event.preventDefault(); return; }
    if (event.key === 'Escape' && active && !event.defaultPrevented) { event.preventDefault(); leave(false); }
  });
  window.addEventListener('popstate', function () {
    var saved = history.state && visited.get(history.state.chfHybridView);
    if (saved && !active) enter(saved.entry, saved.trigger, false);
    else if (!saved) leave(true);
  });
})();
