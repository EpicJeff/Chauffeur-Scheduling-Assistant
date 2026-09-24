/* One saved exterior, shared marker interactions and live vehicle layers. */
(function () {
  'use strict';
  var exterior = document.getElementById('house-exterior');
  if (!exterior) return;
  var room = document.getElementById('hybrid-room');
  var pictures = document.getElementById('exterior-pictures');
  var photo = document.getElementById('exterior-photo');
  var hints = document.getElementById('house-hints');
  var marker = document.createElement('button');
  marker.id = 'exterior-room-marker'; marker.type = 'button';
  marker.className = 'house-hint crowded'; marker.dataset.room = 'living';
  marker.setAttribute('aria-label', 'Expand Living room');
  marker.setAttribute('aria-expanded', 'false');
  var icons = document.createElement('div'); icons.className = 'house-hint-icons';
  document.querySelectorAll('#hybrid-hotspots [data-card] > svg').forEach(function (svg) { icons.appendChild(svg.cloneNode(true)); });
  marker.appendChild(icons);
  var markerLabel = document.createElement('span'); markerLabel.className = 'house-hint-label'; markerLabel.textContent = 'Living room';
  marker.appendChild(markerLabel); hints.appendChild(marker);
  var life = document.getElementById('house-life');
  var lifeHome = life.parentNode;
  var quickviews = document.getElementById('exterior-quickviews');
  var enterButton = document.getElementById('exterior-enter');
  var outside = document.getElementById('hybrid-outside');
  var status = document.getElementById('exterior-status');
  var journey = 0, ready = false, opening = false;
  var mode = 'exterior';
  var reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function urlFor(inside) {
    var url = new URL(location.href);
    url.searchParams.delete('angle');
    if (inside) url.searchParams.set('scene', 'living'); else url.searchParams.delete('scene');
    return url.href;
  }
  function placeMarker() {
    var anchor = [.39,.63], img = photo;
    if (marker.classList.contains('expanded')) return;
    marker.hidden = false;
    if (!img || !img.naturalWidth) { marker.hidden = true; return; }
    var scale = Math.max(innerWidth / img.naturalWidth, innerHeight / img.naturalHeight);
    var x = anchor ? anchor[0] * img.naturalWidth * scale + (innerWidth - img.naturalWidth * scale) / 2 : innerWidth / 2;
    var y = anchor ? anchor[1] * img.naturalHeight * scale + (innerHeight - img.naturalHeight * scale) : innerHeight * .5;
    x = Math.max(70, Math.min(innerWidth - 70, x));
    y = Math.max(235, Math.min(innerHeight - 320, y));
    marker.style.left = x + 'px'; marker.style.top = y + 'px';
    pictures.style.setProperty('--entry-x', x + 'px');
    pictures.style.setProperty('--entry-y', y + 'px');
  }
  function loadPhoto() {
    exterior.setAttribute('aria-busy', 'true');
    photo.onload = function () {
      ready = true; photo.classList.add('is-active'); placeMarker();
      exterior.setAttribute('aria-busy', 'false');
      status.textContent = 'Tap the room to explore';
      window.dispatchEvent(new Event('chf-exterior-ready'));
    };
    photo.onerror = function () {
      exterior.setAttribute('aria-busy', 'false');
      status.textContent = 'Exterior image unavailable. Tap Living room shortcuts to continue.';
      marker.hidden = false; marker.style.left = '50%'; marker.style.top = '45%';
    };
    photo.src = photo.dataset.src;
  }
  function setMode(next) {
    mode = next; document.body.dataset.houseScene = next;
    hints.hidden = next !== 'exterior';
    var destination = next === 'exterior' ? quickviews : lifeHome;
    if (life.parentNode !== destination) {
      var move = function () { destination.appendChild(life); };
      if (window.Alpine) Alpine.mutateDom(move); else move();
    }
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
  async function enter(remember, feature) {
    if (mode !== 'exterior' || opening) return;
    opening = true;
    var ticket = ++journey;
    enterButton.disabled = marker.disabled = true;
    status.textContent = 'Opening the living room…';
    try {
      await waitRoom();
      if (ticket !== journey) return;

      window.ChauffeurMarkers.collapse();
      if (remember) history.pushState(Object.assign({}, history.state, {chfExteriorRoom:true}), '', urlFor(true));
      else history.replaceState(history.state, '', urlFor(true));
      exterior.hidden = false;
      setMode('entering');
      await new Promise(function (resolve) { setTimeout(resolve, reduced.matches ? 0 : 700); });
      if (ticket !== journey) return;
      exterior.hidden = true;
      setMode('living');
      outside.focus();
      if (feature) window.chfHybridVisit(feature);
    } catch (error) {
      if (ticket === journey) status.textContent = 'The room artwork could not load. Please try again.';
    } finally {
      if (ticket === journey) { opening = false; enterButton.disabled = marker.disabled = false; }
    }
  }
  function revealOutside() {
    ++journey;
    exterior.hidden = false;
    setMode('exterior');
    opening = false;
    status.textContent = 'Tap the room to explore';
    enterButton.disabled = marker.disabled = false;
    placeMarker();
    enterButton.focus();
  }
  function goOutside() {
    if (mode !== 'living' || window.chfHybridViewing?.()) return;
    if (history.state?.chfExteriorRoom) history.back();
    else revealOutside();
  }
  function activateMarker() {
    if (mode !== 'exterior') return;
    if (window.ChauffeurMarkers.expand(marker, 'living')) return;
    enter(true);
  }
  marker.addEventListener('click', function (event) { event.stopPropagation(); activateMarker(); });
  enterButton.addEventListener('click', function (event) { event.stopPropagation(); marker.focus(); activateMarker(); });
  window.chfHouseVisit = function (zone, targetRoom) {
    var key = {radio:'music', pet:'pets', tasks:'tasks', programs:'programs'}[zone];
    if (targetRoom === 'living' && key) enter(true, key);
  };
  outside.addEventListener('click', goOutside);
  document.addEventListener('keydown', function (event) {
    if (document.body.classList.contains('house-card-open')) return;
    if (event.defaultPrevented || event.target.closest('input,textarea,select,[contenteditable="true"]')) return;
    if (mode === 'living' && event.key === 'Escape' && !window.chfHybridViewing?.()) {
      event.preventDefault(); goOutside();
    }
  });
  window.addEventListener('popstate', function () {
    if (history.state?.chfExteriorRoom) { if (mode === 'exterior') enter(false); }
    else if (mode !== 'exterior' || opening) revealOutside();
  });
  window.addEventListener('resize', placeMarker);
  window.chfHouseMode = function () { return mode === 'exterior' ? 'exterior' : 'living'; };
  window.chfExteriorProbe = function () { return {mode:mode, ready:ready}; };
  var initialInside = new URL(location.href).searchParams.get('scene') === 'living';
  setMode('exterior'); loadPhoto();
  if (initialInside) {
    if (history.state?.chfExteriorRoom) enter(false);
    else { history.replaceState(history.state, '', urlFor(false)); enter(true); }
  } else {
    var initial = Object.assign({}, history.state); delete initial.chfExteriorRoom;
    history.replaceState(initial, '', urlFor(false));
  }
})();
