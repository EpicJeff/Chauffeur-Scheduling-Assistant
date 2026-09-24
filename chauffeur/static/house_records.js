/* Real personal music shelves, rendered as record sleeves on the radio shelf. */
(function () {
  'use strict';
  var shelf = document.getElementById('radio-library');
  if (!shelf) return;
  var frame = document.getElementById('hybrid-room-frame'), radio = document.getElementById('house-radio');
  var records = document.getElementById('radio-records'), member = document.getElementById('radio-member');
  var form = document.getElementById('radio-search-form'), query = document.getElementById('radio-query');
  var status = document.getElementById('radio-library-status');
  var opts = {apiBase:window.chfBase || ''};
  var active = false, visit = 0, searchTicket = 0, shelfTicket = 0;
  var mode = 'favorites', data = {favorites:[], recent:[]}, results = [], available = false, busy = false;
  var favoriteWrites = new Set();
  function message(text) { status.textContent = text; }
  function el(tag, cls, text) { var node = document.createElement(tag); node.className = cls; if (text) node.textContent = text; return node; }
  function searchMode(on) {
    frame.classList.toggle('radio-searching', on);
    form.hidden = !on;
    Array.from(radio.children).forEach(function (child) { if (!child.classList.contains('radio-glass')) child.inert = on; });
    if (on) query.focus({preventScroll:true});
  }
  function paintButtons() {
    records.querySelectorAll('.record-play').forEach(function (b) { b.disabled = !available || busy; });
    records.querySelectorAll('.record-save').forEach(function (b) { b.disabled = !member.value || favoriteWrites.has(b.dataset.uri); });
  }
  function render() {
    var focused = records.contains(document.activeElement) && document.activeElement.dataset.uri;
    var focusClass = focused && document.activeElement.className;
    records.replaceChildren();
    var items = mode === 'search' ? results : data[mode];
    document.getElementById('radio-favorites').setAttribute('aria-pressed', String(mode === 'favorites'));
    document.getElementById('radio-recent').setAttribute('aria-pressed', String(mode === 'recent'));
    items.filter(function (item) { return item && typeof item.uri === 'string' && item.uri; }).forEach(function (item, i) {
      var jacket = el('article', 'record-jacket');
      jacket.style.setProperty('--record-hue', (i * 47 + 24) % 360);
      var play = el('button', 'record-play'); play.type = 'button'; play.dataset.uri = item.uri;
      play.setAttribute('aria-label', 'Play ' + (item.name || 'Untitled record'));
      var cover = el('span', 'record-cover');
      cover.append(el('span', 'record-fallback', item.name || 'Untitled record'));
      var art = MusicLogic.imageOf(item, opts);
      if (art) {
        var img = el('img', 'record-art'); img.alt = ''; img.loading = 'lazy'; img.src = art;
        img.addEventListener('error', function () { img.remove(); }); cover.append(img);
      }
      play.append(cover, el('span', 'record-name', item.name || 'Untitled record'),
        el('span', 'record-credit', (MusicLogic.GROUP_LABEL[item.media_type] || 'Music') + ' · ' + (MusicLogic.subtitleOf(item) || 'Music Assistant')));
      play.addEventListener('click', async function () {
        if (!active || !available || busy) return;
        var v = visit, owner = member.value;
        await window.HouseRadio.playItem(item, owner);
        if (active && v === visit && member.value === owner) loadShelf();
      });
      var saved = data.favorites.some(function (f) { return f.uri === item.uri; });
      var save = el('button', 'record-save', saved ? '♥ Saved' : '♡ Save'); save.type = 'button'; save.dataset.uri = item.uri;
      save.setAttribute('aria-label', (saved ? 'Remove ' : 'Save ') + (item.name || 'record') + (saved ? ' from favorites' : ' to favorites'));
      save.setAttribute('aria-pressed', String(saved));
      save.addEventListener('click', function () { toggleFavorite(item, saved); });
      jacket.append(play, save); records.append(jacket);
    });
    paintButtons();
    if (focused) {
      var target = Array.from(records.querySelectorAll('button')).find(function (b) {
        return b.dataset.uri === focused && b.className === focusClass && !b.disabled;
      });
      (target || records).focus({preventScroll:true});
    }
    if (!items.length) message(mode === 'search' ? 'No records found. Try another search.' : !member.value
      ? 'Choose whose records to browse. Search works without a personal shelf.'
      : mode === 'recent' ? 'Records you play will appear here.' : 'Search for music, then save a record to this shelf.');
    else message(mode === 'search' ? items.length + ' search results · tap a sleeve to play' : 'Swipe through ' + items.length + ' records · tap a sleeve to play');
  }
  async function loadShelf() {
    var v = visit, ticket = ++shelfTicket, owner = member.value;
    if (!owner) { data = {favorites:[], recent:[]}; render(); return; }
    var next = await MusicLogic.myShelf(owner, opts);
    if (!active || v !== visit || ticket !== shelfTicket || owner !== member.value) return;
    data = {favorites:next.favorites || [], recent:next.recent || []}; render();
  }
  async function toggleFavorite(item, saved) {
    var owner = member.value, v = visit;
    if (!active || !owner || favoriteWrites.has(item.uri)) return;
    favoriteWrites.add(item.uri); paintButtons();
    try {
      if (saved) await MusicLogic.removeFavorite(owner, item.uri, opts);
      else await MusicLogic.addFavorite(owner, item, opts);
      if (active && v === visit && owner === member.value) await loadShelf();
    } catch (_) {
      if (active && v === visit && owner === member.value) message('Could not update this shelf. Try again.');
    } finally { favoriteWrites.delete(item.uri); paintButtons(); }
  }
  member.addEventListener('change', function () {
    ++shelfTicket; data = {favorites:[], recent:[]}; render();
    try { localStorage.setItem('chauffeur_radio_member', member.value); } catch (_) {}
    loadShelf();
  });
  ['favorites', 'recent'].forEach(function (name) {
    document.getElementById('radio-' + name).addEventListener('click', function () {
      ++searchTicket; mode = name; searchMode(false); render(); records.scrollLeft = 0; loadShelf();
    });
  });
  document.getElementById('radio-search-open').addEventListener('click', function () { searchMode(true); });
  function endSearch() {
    ++searchTicket; searchMode(false); mode = 'favorites'; render();
    document.getElementById('radio-search-open').focus({preventScroll:true});
  }
  document.getElementById('radio-search-close').addEventListener('click', endSearch);
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && active && !form.hidden) { event.preventDefault(); endSearch(); }
  });
  form.addEventListener('submit', async function (event) {
    event.preventDefault(); var q = query.value.trim(); if (!q || !active) return;
    var ticket = ++searchTicket, v = visit; mode = 'search'; results = []; render(); message('Searching Music Assistant…');
    try {
      var found = await MusicLogic.search(q, {limit:20, types:['artist','album','track','playlist','radio']}, opts);
      if (!active || v !== visit || ticket !== searchTicket) return;
      results = MusicLogic.flatten(found); render(); records.scrollLeft = 0;
    } catch (_) {
      if (active && v === visit && ticket === searchTicket) message('Search could not connect. Try again.');
    }
  });
  query.addEventListener('input', function () { ++searchTicket; if (mode === 'search') message('Press Find to search.'); });
  ['prev', 'next'].forEach(function (direction) {
    document.getElementById('radio-record-' + direction).addEventListener('click', function () {
      records.scrollBy({left:(direction === 'next' ? 1 : -1) * records.clientWidth * .8,
        behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    });
  });
  window.addEventListener('radio-player-state', function (event) { available = event.detail.available; busy = event.detail.busy; paintButtons(); });
  window.HouseRecords = {
    open: async function () {
      active = true; var v = ++visit; shelf.hidden = false; mode = 'favorites'; data = {favorites:[], recent:[]}; results = []; render();
      member.replaceChildren(new Option('Whose records?', ''));
      try {
        var response = await fetch(opts.apiBase + 'api/members'); if (!response.ok) throw new Error();
        var members = await response.json(); if (!active || v !== visit) return;
        members.forEach(function (m) { member.add(new Option(m.name, m.id)); });
        var remembered = ''; try { remembered = localStorage.getItem('chauffeur_radio_member') || ''; } catch (_) {}
        if (members.some(function (m) { return m.id === remembered; })) member.value = remembered;
        loadShelf();
      } catch (_) { if (active && v === visit) message('Personal shelves unavailable. You can still search and play.'); }
    },
    close: function () { active = false; ++visit; ++searchTicket; ++shelfTicket; shelf.hidden = true; searchMode(false); query.value = ''; records.replaceChildren(); }
  };
})();
