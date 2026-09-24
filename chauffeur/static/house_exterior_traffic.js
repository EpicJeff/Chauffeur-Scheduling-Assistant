/* Shared fleet/curb state, composed as sprites in the photograph's coordinates. */
(function () {
  'use strict';
  var scene = document.getElementById('exterior-traffic');
  if (!scene) return;
  var photo = document.getElementById('exterior-photo');
  var shortcuts = document.getElementById('exterior-traffic-shortcuts');
  var payload = '', parked = [];
  function project() {
    if (!photo.naturalWidth) return;
    var scale = Math.max(innerWidth/photo.naturalWidth, innerHeight/photo.naturalHeight);
    scene.style.width = photo.naturalWidth*scale+'px';
    scene.style.height = photo.naturalHeight*scale+'px';
    scene.style.left = (innerWidth-photo.naturalWidth*scale)/2+'px';
    scene.style.top = (innerHeight-photo.naturalHeight*scale)+'px';
  }
  function open(key) {
    window.dispatchEvent(new CustomEvent('chf-house-open', {detail:key}));
  }
  function shortcut(text, key, id) {
    var button = document.createElement('button'); button.type = 'button'; button.id = id;
    button.textContent = text; button.addEventListener('click', function () { open(key); });
    shortcuts.appendChild(button);
  }
  function actor(index, point, label, key, id, warn, artwork) {
    var button = document.createElement('button'); button.type = 'button';
    button.className = 'exterior-vehicle'; button.dataset.vehicle = id;
    button.dataset.warn = String(!!warn); button.setAttribute('aria-label', label);
    button.title = label; button.style.left = point[0]*100+'%'; button.style.top = point[1]*100+'%';
    button.style.width = point[2]*100+'%'; button.style.zIndex = String(Math.round(point[1]*100));
    var art = document.createElement('span'); art.className = 'exterior-vehicle-art';
    art.setAttribute('aria-hidden','true');
    art.style.setProperty('--sprite-x', ((index%4)*100/3)+'%');
    art.style.setProperty('--sprite-y', (index < 4 ? 0 : 100)+'%');
    if (artwork && /^(data:image\/(png|webp);base64,|\/?static\/house_hybrid\/vehicles\/)/.test(artwork)) {
      var image = document.createElement('img'); image.alt = ''; image.draggable = false;
      image.src = artwork.startsWith('static/') ? (window.chfBase || '/') + artwork : artwork;
      image.onerror = function () { image.remove(); art.style.removeProperty('background'); };
      art.style.background = 'none'; art.appendChild(image);
    }
    button.appendChild(art);
    var tag = document.createElement('span'); tag.className = 'exterior-vehicle-label'; tag.textContent = label;
    button.appendChild(tag); button.addEventListener('click', function () { open(key); });
    scene.appendChild(button);
  }
  function accept(state) {
    state = state || {};
    var cars = Array.isArray(state.garage?.cars) ? state.garage.cars : [];
    var bus = state.curb?.bus === true;
    var next = JSON.stringify([cars,bus,!!state.curb?.demo]);
    if (next === payload) return;
    payload = next; scene.replaceChildren(); shortcuts.replaceChildren();
    parked = cars.filter(function (car) { return car.present === true; });
    if (cars.length) shortcut('Vehicles · '+parked.length+' home', 'cars', 'exterior-cars-shortcut');
    if (bus) {
      var busLabel = state.curb.demo ? 'Demo · School bus nearby' : 'School bus nearby';
      // Tire contacts sit below the curb, on the street, in source-photo coordinates.
      actor(7,[.13,.95,.24], busLabel, 'schedule', 'school-bus', false);
      shortcut(busLabel, 'schedule', 'exterior-bus-shortcut');
    }
    project();
  }
  window.addEventListener('chf-house-state', function (event) { accept(event.detail); });
  window.addEventListener('chf-exterior-ready', project);
  window.addEventListener('resize', project);
  accept(window.chfHouseState?.());
})();
