/* One scene-matched bay. Preview overrides are local and never command a car. */
(function () {
  'use strict';
  var room = document.getElementById('hybrid-garage');
  if (!room) return;
  var occupied = document.getElementById('garage-occupied');
  var empty = document.getElementById('garage-empty');
  var select = document.getElementById('garage-presence');
  var state = document.getElementById('garage-state');
  var carButton = document.getElementById('garage-car');
  var car = null;
  function paint() {
    var home = select.value === 'home' || (select.value === 'live' && (!car || car.present === true));
    room.dataset.occupied = String(home);
    occupied.style.opacity = home ? '1' : '0';
    carButton.hidden = !home;
    var label = select.value !== 'live' ? 'Preview only' : (car ? car.name : 'Example EV9');
    state.textContent = label + ' · ' + (home ? 'Parked' : 'Away · bay empty');
    if (select.value === 'live' && car && Number.isFinite(car.battery_pct)) state.textContent += ' · ' + Math.round(car.battery_pct) + '% battery';
  }
  function accept(data) {
    car = (data?.garage?.cars || []).find(c => /\bev9\b/i.test(c.name || '') || /kia-ev9/.test(c.exterior_image || '')) || null;
    paint();
  }
  function open() { window.dispatchEvent(new CustomEvent('chf-house-open', {detail:'cars'})); }
  select.addEventListener('change', paint);
  carButton.addEventListener('click', open);
  document.getElementById('garage-fleet').addEventListener('click', open);
  window.addEventListener('chf-house-state', e => accept(e.detail));
  window.chfGarageReady = async function () {
    await Promise.all([empty, occupied].map(function (image) {
      if (!image.getAttribute('src')) image.src = image.dataset.src;
      return image.decode();
    }));
  };
  accept(window.chfHouseState?.());
})();
