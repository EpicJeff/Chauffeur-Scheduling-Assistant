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
  var car = null, dashboardTicket = 0;
  var plane = document.getElementById('garage-images');
  var dashboard = document.getElementById('garage-dashboard');
  var dashboardPlane = document.getElementById('garage-dashboard-plane');
  var clusterPhoto = document.getElementById('garage-cluster-photo');
  var dashboardBack = document.getElementById('garage-dashboard-back');
  function project() {
    [[empty, plane, innerWidth < 700 ? .25 : .5], [clusterPhoto, dashboardPlane, .5]].forEach(function (entry) {
      var image = entry[0], target = entry[1];
      if (!image.naturalWidth) return;
      var scale = Math.max(innerWidth/image.naturalWidth, innerHeight/image.naturalHeight);
      target.style.width = image.naturalWidth*scale+'px'; target.style.height = image.naturalHeight*scale+'px';
      target.style.left = (innerWidth-image.naturalWidth*scale)*entry[2]+'px';
      target.style.top = (innerHeight-image.naturalHeight*scale)/2+'px';
    });
  }
  function text(id, value) { document.getElementById(id).textContent = value; }
  function cluster() {
    var battery = car && Number.isFinite(car.battery_pct) ? car.battery_pct : null;
    var fuel = car && Number.isFinite(car.fuel_pct) ? car.fuel_pct : null;
    var level = battery !== null ? battery : fuel;
    text('cluster-vehicle', car ? car.name : 'Illustrative EV9');
    text('cluster-presence', car ? (car.present ? 'HOME' : 'AWAY') : 'PREVIEW');
    text('cluster-energy-label', battery !== null || fuel === null ? 'BATTERY' : 'FUEL');
    text('cluster-energy', level === null ? '—' : Math.round(level)+'%');
    document.getElementById('cluster-charge-bar').style.width = level === null ? '0%' : Math.max(0,Math.min(100,level))+'%';
    text('cluster-range', car && Number.isFinite(car.range) ? Math.round(car.range) : '—');
    text('cluster-range-unit', car?.range_unit || '');
    text('cluster-notice', !car || level === null ? 'Telemetry unavailable' : car.warn ? 'Energy level needs attention' : 'Vehicle status');
    document.getElementById('garage-cluster-ui').dataset.warn = String(!!car?.warn);
  }
  async function leanIn() {
    var ticket = ++dashboardTicket;
    carButton.disabled = true;
    try {
      if (!clusterPhoto.getAttribute('src')) clusterPhoto.src = clusterPhoto.dataset.src;
      await clusterPhoto.decode();
      if (ticket !== dashboardTicket || document.body.dataset.houseScene !== 'garage') return;
      project(); cluster(); dashboard.hidden = false; room.dataset.view = 'dashboard';
      plane.inert = true;
      dashboardBack.focus();
    } catch (_) { state.textContent = 'Dashboard artwork unavailable. Vehicle information is still available.'; }
    finally { carButton.disabled = false; }
  }
  function back(focus) {
    ++dashboardTicket;
    var wasOpen = room.dataset.view === 'dashboard';
    room.dataset.view = 'bay'; dashboard.hidden = true;
    plane.inert = false;
    if (focus && wasOpen) (carButton.hidden ? document.getElementById('garage-fleet') : carButton).focus();
    return wasOpen;
  }
  dashboardBack.addEventListener('click', function () { back(true); });
  window.chfGarageBack = function () { return back(true); };
  window.chfGarageReset = function () { back(false); };
  window.addEventListener('resize', project);
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && room.dataset.view === 'dashboard' && !document.body.classList.contains('house-card-open')) {
      event.preventDefault(); event.stopImmediatePropagation(); back(true);
    }
  });
  function paint() {
    var home = select.value === 'home' || (select.value === 'live' && (!car || car.present === true));
    room.dataset.occupied = String(home);
    occupied.style.opacity = home ? '1' : '0';
    carButton.hidden = !home;
    var label = select.value !== 'live' ? 'Preview only' : (car ? car.name : 'Example EV9');
    state.textContent = label + ' · ' + (home ? 'Parked' : 'Away · bay empty');
    if (select.value === 'live' && car && Number.isFinite(car.battery_pct)) state.textContent += ' · ' + Math.round(car.battery_pct) + '% battery';
    cluster();
  }
  function accept(data) {
    car = (data?.garage?.cars || []).find(c => room.dataset.carId && String(c.id) === room.dataset.carId) || null;
    paint();
  }
  function open() { window.dispatchEvent(new CustomEvent('chf-house-open', {detail:'cars'})); }
  select.addEventListener('change', paint);
  carButton.addEventListener('click', leanIn);
  document.getElementById('cluster-more').addEventListener('click', open);
  document.getElementById('garage-fleet').addEventListener('click', open);
  window.addEventListener('chf-house-state', e => accept(e.detail));
  window.chfGarageReady = async function () {
    await Promise.all([empty, occupied].map(function (image) {
      if (!image.getAttribute('src')) image.src = image.dataset.src;
      return image.decode();
    }));
    project();
  };
  accept(window.chfHouseState?.());
})();
