/* A radio-shaped surface over the shared Music Assistant API. No second player,
   hidden music widget, autoplay on entry, or persistent polling after exit. */
(function () {
  'use strict';
  var root = document.getElementById('house-radio');
  if (!root) return;
  var opts = {apiBase:window.chfBase || ''};
  var output = document.getElementById('radio-output');
  var stationSelect = document.getElementById('radio-stations');
  var power = document.getElementById('radio-power');
  var volume = document.getElementById('radio-volume');
  var tune = document.getElementById('radio-tune');
  var players = [], stations = [], selected = '', stationIndex = 0;
  var active = false, online = false, busy = false, epoch = 0, readTicket = 0;
  var timer = null, drag = null, preview = false, error = '', visitSerial = 0;
  try { selected = localStorage.getItem('chauffeur_music_player') || ''; } catch (_) {}
  if (selected === MusicLogic.LOCAL) selected = '';
  function current() { return players.find(function (p) { return p.entity_id === selected; }); }
  function usable() { var p = current(); return active && online && p && !['unavailable','unknown'].includes(p.state); }
  function put(id, text) { document.getElementById(id).textContent = text || ''; }
  function clamp(value, max) { return Math.max(0, Math.min(max, value)); }
  function dial(el, value, max, text) {
    el.dataset.value = value;
    el.style.setProperty('--turn', (-130 + (max ? value / max : 0) * 260) + 'deg');
    el.setAttribute('aria-valuenow', el === tune ? value + 1 : value);
    el.setAttribute('aria-valuetext', text);
  }
  function paint() {
    var p = current(), available = usable(), playing = available && p.state === 'playing';
    root.classList.toggle('is-playing', !!playing);
    power.disabled = !available || busy;
    power.setAttribute('aria-pressed', String(!!playing));
    power.setAttribute('aria-label', playing ? 'Pause music' : 'Play music');
    volume.disabled = !available || busy || !Number.isFinite(p.volume_level);
    tune.disabled = !available || busy || !stations.length;
    stationSelect.disabled = !available || busy || !stations.length;
    root.setAttribute('aria-busy', String(busy));
    if (!drag || drag.el !== volume) {
      var v = p && Number.isFinite(p.volume_level) ? Math.round(clamp(p.volume_level * 100, 100)) : 0;
      dial(volume, v, 100, volume.disabled && !busy ? 'Unavailable' : v + ' percent');
      put('radio-volume-label', p && Number.isFinite(p.volume_level) ? v + '%' : '—');
    }
    var station = stations[stationIndex];
    tune.setAttribute('aria-valuemax', Math.max(1, stations.length));
    dial(tune, stationIndex, Math.max(0, stations.length - 1), station ? station.name : 'No saved stations');
    stationSelect.value = station ? String(stationIndex) : '';
    var message = !online ? 'Speakers unavailable' : !selected ? 'Choose a speaker'
      : !available ? 'Speaker unavailable' : busy ? 'Sending…' : preview && station ? 'Ready · press tuning'
      : playing ? 'Playing' : 'Standby';
    put('radio-state', message.toUpperCase());
    put('radio-title', preview && station ? station.name : (p && p.media_title) || 'The living room radio');
    put('radio-subtitle', (p && p.media_artist) || (p && p.name) || 'Choose the brass speaker selector below');
    put('radio-notice', error || (!stations.length && online ? 'Save stations in Music Assistant to tune here.' : ''));
  }
  function paintPlayers() {
    output.replaceChildren(new Option('Choose speaker', ''));
    players.forEach(function (p) { output.add(new Option(p.name || p.entity_id, p.entity_id)); });
    if (selected && !current()) output.add(new Option('Selected speaker unavailable', selected));
    output.value = selected;
  }
  async function refresh() {
    if (!active || document.hidden) return;
    var visit = epoch, ticket = ++readTicket;
    var data = await MusicLogic.players(opts);
    if (!active || visit !== epoch || ticket !== readTicket) return;
    online = Array.isArray(data);
    if (online) {
      players = data;
      // Only a sole speaker is an unambiguous default. Never silently reroute
      // a missing selected speaker to a different room.
      if (!selected && players.length === 1) selected = players[0].entity_id;
      paintPlayers();
    }
    paint();
  }
  async function action(send) {
    if (!usable() || busy) return;
    var visit = epoch, target = selected;
    busy = true; error = ''; ++readTicket; paint();
    try {
      if (!await send(target)) throw new Error('The speaker did not accept that change. Try again.');
      if (active && visit === epoch && selected === target) preview = false;
    } catch (_) {
      if (active && visit === epoch && selected === target) error = 'The speaker did not accept that change. Try again.';
    } finally {
      if (active && visit === epoch && selected === target) { busy = false; paint(); await refresh(); }
    }
  }
  function playStation() {
    var station = stations[stationIndex];
    if (station) action(function (target) { return MusicLogic.play(target, station.uri, station.media_type || 'radio', opts); });
  }
  output.addEventListener('change', function () {
    selected = output.value; ++epoch; ++readTicket; busy = false; drag = null; preview = false; error = '';
    try { localStorage.setItem('chauffeur_music_player', selected); } catch (_) {}
    paint(); refresh();
  });
  stationSelect.addEventListener('change', function () {
    stationIndex = clamp(Number(stationSelect.value) || 0, Math.max(0, stations.length - 1));
    preview = true; paint(); playStation();
  });
  power.addEventListener('click', function () {
    var command = current() && current().state === 'playing' ? 'pause' : 'play';
    action(function (target) { return MusicLogic.command(target, command, {}, opts); });
  });
  function setValue(el, value) {
    if (el === volume) {
      value = Math.round(clamp(value, 100)); dial(el, value, 100, value + ' percent');
      put('radio-volume-label', value + '%');
    } else {
      stationIndex = Math.round(clamp(value, Math.max(0, stations.length - 1)));
      preview = true; paint();
    }
  }
  function commit(el, value) {
    if (el === tune) playStation();
    else action(function (target) { return MusicLogic.command(target, 'volume_set', {volume:value / 100}, opts); });
  }
  [volume, tune].forEach(function (el) {
    el.addEventListener('pointerdown', function (event) {
      if (el.disabled || (event.pointerType === 'mouse' && event.button !== 0)) return;
      event.preventDefault(); el.focus();
      drag = {el:el, id:event.pointerId, y:event.clientY, value:Number(el.dataset.value), target:selected};
      el.setPointerCapture(event.pointerId);
    });
    el.addEventListener('pointermove', function (event) {
      if (!drag || drag.el !== el || drag.id !== event.pointerId) return;
      var change = (drag.y - event.clientY) / (el === volume ? 2 : 24);
      setValue(el, drag.value + change);
    });
    el.addEventListener('pointerup', function (event) {
      if (!drag || drag.el !== el || drag.id !== event.pointerId) return;
      var previous = drag; drag = null;
      if (el.hasPointerCapture(event.pointerId)) el.releasePointerCapture(event.pointerId);
      var value = Number(el.dataset.value);
      if (previous.target === selected && (el === tune || value !== previous.value)) commit(el, value);
    });
    el.addEventListener('pointercancel', function () { drag = null; paint(); });
    el.addEventListener('lostpointercapture', function () { if (drag && drag.el === el) { drag = null; paint(); } });
    el.addEventListener('keydown', function (event) {
      var delta = {ArrowUp:1, ArrowRight:1, ArrowDown:-1, ArrowLeft:-1}[event.key];
      var value = Number(el.dataset.value), max = el === volume ? 100 : stations.length - 1;
      if (delta) value += delta * (el === volume ? (event.shiftKey ? 10 : 2) : 1);
      else if (event.key === 'Home') value = 0;
      else if (event.key === 'End') value = max;
      else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); if (el === tune) playStation(); return; }
      else return;
      event.preventDefault(); setValue(el, clamp(value, max));
      if (el === volume) commit(el, Number(el.dataset.value));
    });
    // Assistive-technology activation has no pointer gesture.
    el.addEventListener('click', function (event) { if (event.detail === 0 && el === tune) playStation(); });
  });
  function stopPolling() { clearInterval(timer); timer = null; }
  function startPolling() { stopPolling(); if (active && !document.hidden) { refresh(); timer = setInterval(refresh, 5000); } }
  window.HouseRadio = {
    open: function () {
      if (active) return;
      active = true; ++epoch; ++visitSerial; root.hidden = false; error = ''; preview = false; busy = false;
      paint(); startPolling();
      var visit = visitSerial;
      MusicLogic.favorites('radio', 50, opts).then(function (items) {
        if (!active || visit !== visitSerial) return;
        stations = items.filter(function (item) { return item && typeof item.uri === 'string' && item.uri; });
        stationIndex = clamp(stationIndex, Math.max(0, stations.length - 1));
        stationSelect.replaceChildren();
        if (!stations.length) stationSelect.add(new Option('No saved stations', ''));
        stations.forEach(function (s, i) { stationSelect.add(new Option(s.name || 'Station ' + (i + 1), String(i))); });
        paint();
      });
    },
    close: function () { active = false; ++epoch; ++readTicket; drag = null; busy = false; root.hidden = true; stopPolling(); }
  };
  document.addEventListener('visibilitychange', function () { drag = null; if (document.hidden) stopPolling(); else startPolling(); });
  window.addEventListener('pagehide', stopPolling);
  window.addEventListener('pageshow', function (event) { if (event.persisted) startPolling(); });
})();
