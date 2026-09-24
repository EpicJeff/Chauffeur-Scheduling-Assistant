/* Saved eight-view exterior. Only asset loads and existing room APIs at runtime. */
(function () {
  'use strict';
  var exterior = document.getElementById('house-exterior');
  if (!exterior) return;
  var room = document.getElementById('hybrid-room');
  var pictures = document.getElementById('exterior-pictures');
  var images = Array.from(pictures.querySelectorAll('img'));
  var stops = Array.from(document.querySelectorAll('#exterior-stops button'));
  var marker = document.getElementById('exterior-room-marker');
  var enterButton = document.getElementById('exterior-enter');
  var outside = document.getElementById('hybrid-outside');
  var status = document.getElementById('exterior-status');
  var label = document.getElementById('exterior-angle');
  var labels = ['Front right', 'Front', 'Front left', 'Left side', 'Rear left', 'Rear', 'Rear right', 'Right side'];
  var anchors = [[.39,.63],[.52,.66],[.67,.64],null,null,null,null,null];
  var loads = new Map(), revision = 0, journey = 0, active = -1, desired = 0;
  var mode = 'exterior';
  var reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function wrap(n) { return ((n % 8) + 8) % 8; }
  function urlFor(inside) {
    var url = new URL(location.href);
    url.searchParams.set('angle', String(Math.max(0, active)));
    if (inside) url.searchParams.set('scene', 'living'); else url.searchParams.delete('scene');
    return url.href;
  }
  function load(index) {
    var img = images[index];
    if (img.complete && img.naturalWidth) return Promise.resolve(img);
    if (loads.has(index)) return loads.get(index);
    var promise = new Promise(function (resolve, reject) {
      img.onload = function () { img.decode().then(function () { resolve(img); }, reject); };
      img.onerror = function () { reject(new Error('Image unavailable')); };
      img.src = img.dataset.src;
    }).catch(function (error) { loads.delete(index); throw error; });
    loads.set(index, promise);
    return promise;
  }
  function placeMarker() {
    var anchor = anchors[active], img = images[active];
    marker.hidden = !anchor;
    if (!anchor || !img || !img.naturalWidth) return;
    var scale = Math.max(innerWidth / img.naturalWidth, innerHeight / img.naturalHeight);
    var x = anchor[0] * img.naturalWidth * scale + (innerWidth - img.naturalWidth * scale) / 2;
    var y = anchor[1] * img.naturalHeight * scale + (innerHeight - img.naturalHeight * scale) / 2;
    marker.style.left = x + 'px'; marker.style.top = y + 'px';
    marker.hidden = x < 80 || x > innerWidth - 80 || y < 140 || y > innerHeight - 170;
    pictures.style.setProperty('--entry-x', x + 'px');
    pictures.style.setProperty('--entry-y', y + 'px');
  }
  async function view(index) {
    if (mode !== 'exterior') return;
    desired = wrap(index);
    var target = desired, ticket = ++revision;
    exterior.setAttribute('aria-busy', 'true');
    enterButton.disabled = marker.disabled = true;
    status.textContent = 'Opening ' + labels[target].toLowerCase() + '…';
    try {
      await load(target);
      if (ticket !== revision || mode !== 'exterior') return;
      active = target;
      images.forEach(function (img, i) { img.classList.toggle('is-active', i === active); });
      stops.forEach(function (button, i) { button.setAttribute('aria-pressed', String(i === active)); });
      label.textContent = labels[active] + ' · ' + (active + 1) + ' / 8';
      exterior.dataset.angle = String(active);
      history.replaceState(history.state, '', urlFor(false));
      placeMarker();
      status.textContent = 'Swipe or use the arrows to explore';
      [wrap(active - 1), wrap(active + 1)].forEach(function (next) { load(next).catch(function () {}); });
    } catch (error) {
      if (ticket === revision) status.textContent = 'That view could not load. Choose it again to retry.';
    } finally {
      if (ticket === revision) {
        exterior.setAttribute('aria-busy', 'false');
        enterButton.disabled = marker.disabled = active < 0;
      }
    }
  }
  function setMode(next) {
    mode = next; document.body.dataset.houseScene = next;
    room.inert = next !== 'living';
    room.setAttribute('aria-hidden', String(next !== 'living'));
    exterior.inert = next !== 'exterior';
    exterior.setAttribute('aria-hidden', String(next !== 'exterior'));
    outside.hidden = next !== 'living';
  }
  function waitRoom() {
    return new Promise(function (resolve, reject) {
      var start = performance.now();
      function check() {
        var img = document.querySelector('#hybrid-overview img.is-active');
        if (img && img.complete && img.naturalWidth) return resolve();
        if (performance.now() - start > 15000) return reject(new Error('Room unavailable'));
        setTimeout(check, 50);
      }
      check();
    });
  }
  async function enter(remember) {
    if (mode !== 'exterior') return;
    var ticket = ++journey;
    enterButton.disabled = marker.disabled = true;
    status.textContent = 'Opening the living room…';
    try {
      await waitRoom();
      if (ticket !== journey) return;
      ++revision;
      if (remember) history.pushState(Object.assign({}, history.state, {chfExteriorRoom:true}), '', urlFor(true));
      else history.replaceState(history.state, '', urlFor(true));
      exterior.hidden = false;
      setMode('entering');
      await new Promise(function (resolve) { setTimeout(resolve, reduced.matches ? 0 : 700); });
      if (ticket !== journey) return;
      exterior.hidden = true;
      setMode('living');
      outside.focus();
    } catch (error) {
      if (ticket === journey) status.textContent = 'The room artwork could not load. Please try again.';
    } finally {
      if (ticket === journey) enterButton.disabled = marker.disabled = active < 0;
    }
  }
  function revealOutside() {
    ++journey;
    exterior.hidden = false;
    setMode('exterior');
    status.textContent = 'Swipe or use the arrows to explore';
    enterButton.disabled = marker.disabled = active < 0;
    if (active < 0) view(desired);
    enterButton.focus();
  }
  function goOutside() {
    if (mode !== 'living' || window.chfHybridViewing?.()) return;
    if (history.state?.chfExteriorRoom) history.back();
    else revealOutside();
  }
  document.getElementById('exterior-left').addEventListener('click', function () { view(desired - 1); });
  document.getElementById('exterior-right').addEventListener('click', function () { view(desired + 1); });
  stops.forEach(function (button) { button.addEventListener('click', function () { view(Number(button.dataset.angle)); }); });
  marker.addEventListener('click', function () { enter(true); });
  enterButton.addEventListener('click', function () { enter(true); });
  outside.addEventListener('click', goOutside);
  var pointer = null;
  exterior.addEventListener('pointerdown', function (event) {
    if (event.target.closest('button') || !event.isPrimary || event.button !== 0) return;
    pointer = {id:event.pointerId, x:event.clientX, y:event.clientY};
    exterior.setPointerCapture(event.pointerId);
  });
  exterior.addEventListener('pointerup', function (event) {
    if (!pointer || pointer.id !== event.pointerId) return;
    var dx = event.clientX - pointer.x, dy = event.clientY - pointer.y;
    pointer = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) view(desired + (dx < 0 ? 1 : -1));
  });
  exterior.addEventListener('pointercancel', function () { pointer = null; });
  document.addEventListener('keydown', function (event) {
    if (event.defaultPrevented || event.target.closest('input,textarea,select,[contenteditable="true"]')) return;
    if (mode === 'exterior' && ['ArrowLeft','ArrowRight'].includes(event.key)) {
      event.preventDefault(); view(desired + (event.key === 'ArrowRight' ? 1 : -1));
    } else if (mode === 'living' && event.key === 'Escape' && !window.chfHybridViewing?.()) {
      event.preventDefault(); goOutside();
    }
  });
  window.addEventListener('popstate', function () {
    if (history.state?.chfExteriorRoom) { if (mode === 'exterior') enter(false); }
    else if (mode !== 'exterior') revealOutside();
  });
  window.addEventListener('resize', placeMarker);
  window.chfHouseMode = function () { return mode === 'exterior' ? 'exterior' : 'living'; };
  window.chfExteriorProbe = function () { return {mode:mode, angle:active, desired:desired}; };
  var url = new URL(location.href), angle = Number.parseInt(url.searchParams.get('angle') || '0',10);
  var initialInside = url.searchParams.get('scene') === 'living';
  setMode('exterior');
  // The room layer owns its detail history; this layer owns one exterior/room step.
  view(Number.isFinite(angle) ? angle : 0).then(function () {
    if (!initialInside) return;
    if (history.state?.chfExteriorRoom) enter(false);
    else enter(true);
  });
})();
