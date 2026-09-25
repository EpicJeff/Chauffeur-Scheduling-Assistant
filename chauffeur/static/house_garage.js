/* Saved vehicle assignments drive both bays and each car's instruments. */
(function () {
  'use strict';
  var room = document.getElementById('hybrid-garage');
  if (!room) return;
  var vehicles = window.ChauffeurHouseVehicles;
  var isPreview = document.body.dataset.housePreview === 'true';
  var empty = document.getElementById('garage-empty');
  var occupied = document.getElementById('garage-occupied');
  var occupiedRight = document.getElementById('garage-occupied-right');
  var select = document.getElementById('garage-presence');
  var state = document.getElementById('garage-state');
  var carButton = document.getElementById('garage-car');
  var rightButton = document.getElementById('garage-car-right');
  var plane = document.getElementById('garage-images');
  var dashboard = document.getElementById('garage-dashboard');
  var dashboardPlane = document.getElementById('garage-dashboard-plane');
  var clusterPhoto = document.getElementById('garage-cluster-photo');
  var dashboardBack = document.getElementById('garage-dashboard-back');
  var fleet = [], car = null, rightCar = null, activeId = null;
  var dashboardTicket = 0, returnOutside = false, opener = null;
  function current() { return fleet.find(item => String(item.id) === activeId) || null; }
  function garageState() { return car?.present === true ? (rightCar?.present === true ? 'Both' : 'Left') : (rightCar?.present === true ? 'Right' : 'Empty'); }
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
  function clusterSource() {
    var profile = vehicles.profile(current());
    if (profile === 'murano-white') return clusterPhoto.dataset['murano'+garageState()];
    return profile === 'gls450-white-23' ? clusterPhoto.dataset.gls : clusterPhoto.dataset.ev9;
  }
  async function loadCluster() {
    var source = clusterSource(), ticket = dashboardTicket;
    if (clusterPhoto.getAttribute('src') === source && clusterPhoto.naturalWidth) return;
    var image = new Image(); image.src = source; await image.decode();
    if (ticket !== dashboardTicket) return;
    if (source !== clusterSource()) return loadCluster();
    clusterPhoto.src = source; await clusterPhoto.decode(); project();
  }
  function cluster() {
    var selected = current(), profile = vehicles.profile(selected);
    dashboard.dataset.vehicle = selected ? selected.id : '';
    dashboard.dataset.profile = profile || 'ev9-white-black-roof';
    var battery = Number.isFinite(selected?.battery_pct) ? selected.battery_pct : null;
    var fuel = Number.isFinite(selected?.fuel_pct) ? selected.fuel_pct : null;
    var electric = profile === 'ev9-white-black-roof' || (!profile && fuel === null);
    var level = electric ? battery : fuel;
    text('cluster-vehicle', selected ? selected.name : 'Preview');
    text('cluster-presence', selected ? (selected.present === true ? 'HOME' : selected.present === false ? 'AWAY' : 'UNKNOWN') : 'PREVIEW');
    text('cluster-energy-label', electric ? 'BATTERY' : 'FUEL');
    text('cluster-energy', level === null ? '—' : Math.round(level)+'%');
    document.getElementById('cluster-charge-bar').style.width = level === null ? '0%' : Math.max(0,Math.min(100,level))+'%';
    text('cluster-range', Number.isFinite(selected?.range) ? Math.round(selected.range) : '—');
    text('cluster-range-unit', selected?.range_unit || '');
    text('cluster-notice', level === null ? 'Telemetry unavailable' : selected?.warn ? 'Energy level needs attention' : 'Vehicle status');
    document.getElementById('garage-cluster-ui').dataset.warn = String(!!selected?.warn);
  }
  async function leanIn(selected, outside) {
    if (!selected && !(isPreview && select.value === 'home')) return;
    var ticket = ++dashboardTicket;
    activeId = selected ? String(selected.id) : null;
    returnOutside = !!outside; opener = document.activeElement;
    dashboardBack.textContent = outside ? '← Outside' : '← Garage';
    carButton.disabled = rightButton.disabled = true;
    cluster();
    try {
      await loadCluster();
      if (ticket !== dashboardTicket || document.body.dataset.houseScene !== 'garage') return;
      project(); cluster(); dashboard.hidden = false; room.dataset.view = 'dashboard';
      plane.inert = true; dashboardBack.focus();
    } catch (_) { state.textContent = 'Dashboard artwork unavailable. Vehicle information is still available.'; }
    finally { if (ticket === dashboardTicket) carButton.disabled = rightButton.disabled = false; }
  }
  function back(focus) {
    ++dashboardTicket;
    var wasOpen = room.dataset.view === 'dashboard', outside = returnOutside;
    room.dataset.view = 'bay'; dashboard.hidden = true; plane.inert = false;
    activeId = null; returnOutside = false; carButton.disabled = rightButton.disabled = false;
    if (focus && wasOpen) {
      if (outside) window.chfHybridHome?.();
      else (opener?.isConnected && !opener.hidden ? opener : document.getElementById('garage-fleet')).focus();
    }
    return wasOpen;
  }
  function paint() {
    var mode = isPreview ? select.value : 'live';
    var home = mode === 'home' || (mode === 'live' && car?.present === true);
    var rightHome = rightCar?.present === true;
    room.dataset.occupied = String(home); room.dataset.rightOccupied = String(rightHome);
    occupied.style.opacity = home ? '1' : '0'; occupiedRight.style.opacity = rightHome ? '1' : '0';
    carButton.hidden = !home; rightButton.hidden = !rightHome;
    carButton.setAttribute('aria-label', car ? 'View '+car.name+' instrument cluster' : 'Preview instrument cluster');
    rightButton.setAttribute('aria-label', rightCar ? 'View '+rightCar.name+' instrument cluster' : 'Vehicle instruments');
    var label = mode !== 'live' ? 'Preview only' : (car ? car.name : 'Left bay');
    state.textContent = label + ' · ' + (home ? 'Parked' : 'Empty');
    if (mode === 'live' && Number.isFinite(car?.battery_pct)) state.textContent += ' · ' + Math.round(car.battery_pct) + '% battery';
    if (rightCar) state.textContent += ' · ' + rightCar.name + (rightHome ? ' parked' : ' away');
    text('garage-assignment', [car?.name, rightCar?.name].filter(Boolean).join(' · ') || 'No vehicles assigned');
    if (activeId && current()?.present !== true) back(true);
    cluster();
    if (room.dataset.view === 'dashboard') loadCluster().catch(function () { state.textContent = 'Vehicle view could not refresh.'; });
  }
  function accept(data) {
    fleet = Array.isArray(data?.garage?.cars) ? data.garage.cars : [];
    car = (isPreview && room.dataset.carId ? fleet.find(c => String(c.id) === room.dataset.carId) : vehicles.assigned(fleet, 'ev9-white-black-roof')) || null;
    rightCar = vehicles.assigned(fleet, 'gls450-white-23');
    paint();
  }
  function open() { window.dispatchEvent(new CustomEvent('chf-house-open', {detail:'cars'})); }
  window.chfVehicleCluster = async function (id) {
    var selected = fleet.find(item => String(item.id) === String(id));
    if (!selected || selected.present !== true || !vehicles.profile(selected)) { open(); return; }
    var outside = window.chfHouseMode?.() === 'exterior';
    await window.chfHybridGo('garage');
    selected = fleet.find(item => String(item.id) === String(id));
    if (window.chfHouseMode?.() === 'garage' && selected?.present === true) await leanIn(selected, outside);
  };
  dashboardBack.addEventListener('click', function () { back(true); });
  window.chfGarageBack = function () { return back(true); };
  window.chfGarageReset = function () { back(false); };
  window.addEventListener('resize', project);
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && room.dataset.view === 'dashboard' && !document.body.classList.contains('house-card-open')) {
      event.preventDefault(); event.stopImmediatePropagation(); back(true);
    }
  });
  select.addEventListener('change', paint);
  carButton.addEventListener('click', function () { leanIn(car, false); });
  rightButton.addEventListener('click', function () { leanIn(rightCar, false); });
  document.getElementById('cluster-more').addEventListener('click', open);
  document.getElementById('garage-fleet').addEventListener('click', open);
  window.addEventListener('chf-house-state', e => accept(e.detail));
  window.chfGarageReady = async function () {
    await Promise.all([empty, occupied, occupiedRight].map(function (image) {
      if (!image.getAttribute('src')) image.src = image.dataset.src;
      return image.decode();
    }));
    project();
  };
  accept(window.chfHouseState?.());
})();
