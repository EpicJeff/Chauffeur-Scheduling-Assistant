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
  var selectedIndex = 0, selectedUri = '', gesture = null, suppressClickUntil = 0;
  function aim(at) { frame.dataset.radioCamera = at; }
  function arrange(index) {
    var jackets = Array.from(records.children);
    selectedIndex = Math.max(0, Math.min(index, jackets.length - 1));
    jackets.forEach(function (jacket, i) {
      var distance = i - selectedIndex, chosen = distance === 0;
      var offset = Math.min(Math.abs(distance), 3);
      jacket.classList.toggle('is-selected', chosen);
      jacket.style.setProperty('--record-x', (chosen ? 50 : 50 + Math.sign(distance) * (37 + (offset - 1) * 3)) + '%');
      jacket.style.setProperty('--record-angle', (chosen ? 0 : -Math.sign(distance) * (68 + (offset - 1) * 3)) + 'deg');
      jacket.style.setProperty('--record-depth', chosen ? '12px' : 'calc(var(--radio-width) * -.12 - ' + offset * 12 + 'px)');
      jacket.style.zIndex = chosen ? 100 : 50 - Math.abs(distance);
      jacket.hidden = Math.abs(distance) > 3;
      var button = jacket.querySelector('.record-play');
      button.tabIndex = chosen ? 0 : -1;
      button.setAttribute('aria-label', (chosen ? 'Play ' : 'Browse ') + jacket.dataset.name);
      var save = jacket.querySelector('.record-save'); save.hidden = !chosen;
      jacket.querySelector('.record-more').hidden = !chosen;
      if (chosen) selectedUri = button.dataset.uri;
    });
    records.dataset.selected = String(selectedIndex);
    document.getElementById('radio-record-prev').disabled = !jackets.length || selectedIndex === 0;
    document.getElementById('radio-record-next').disabled = !jackets.length || selectedIndex === jackets.length - 1;
    paintButtons();
  }
  function message(text) { status.textContent = text; }
  function el(tag, cls, text) { var node = document.createElement(tag); node.className = cls; if (text) node.textContent = text; return node; }
  function searchMode(on) {
    frame.classList.toggle('radio-searching', on);
    form.hidden = !on;
    Array.from(radio.children).forEach(function (child) { if (!child.classList.contains('radio-glass') && child.id !== 'radio-library') child.inert = on; });
    if (on) { aim('search'); query.focus({preventScroll:true}); }
  }
  function paintButtons() {
    records.querySelectorAll('.record-play').forEach(function (b) { b.disabled = b.parentElement.classList.contains('is-selected') && (!available || busy); });
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
      jacket.dataset.name = item.name || 'Untitled record';
      jacket.style.setProperty('--record-hue', (i * 47 + 24) % 360);
      var back = el('span', 'record-back'); back.setAttribute('aria-hidden', 'true');
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
        if (Date.now() < suppressClickUntil) return;
        if (i !== selectedIndex) { arrange(i); return; }
        if (!active || !available || busy) return;
        var v = visit, owner = member.value;
        await window.HouseRadio.playItem(item, owner);
        if (active && v === visit && member.value === owner) loadShelf();
      });
      play.addEventListener('contextmenu',function(event){event.preventDefault();window.HouseRadioControls.openRecord(item,play);});
      var saved = data.favorites.some(function (f) { return f.uri === item.uri; });
      var save = el('button', 'record-save', saved ? '♥ Saved' : '♡ Save'); save.type = 'button'; save.dataset.uri = item.uri;
      save.setAttribute('aria-label', (saved ? 'Remove ' : 'Save ') + (item.name || 'record') + (saved ? ' from favorites' : ' to favorites'));
      save.setAttribute('aria-pressed', String(saved));
      save.addEventListener('click', function () { toggleFavorite(item, saved); });
      var more=el('button','record-more','More');more.type='button';more.setAttribute('aria-label','More options for '+jacket.dataset.name);
      more.addEventListener('click',function(){window.HouseRadioControls.openRecord(item,more);});
      jacket.append(back, play, save, more); records.append(jacket);
    });
    var rememberedIndex = items.findIndex(function (item) { return item.uri === selectedUri; });
    arrange(rememberedIndex < 0 ? selectedIndex : rememberedIndex);
    if (focused) {
      var target = Array.from(records.querySelectorAll('button')).find(function (b) {
        return b.dataset.uri === focused && b.className === focusClass && !b.disabled;
      });
      (target || records).focus({preventScroll:true});
    }
    if (!items.length) message(mode === 'search' ? 'No records found. Try another search.' : !member.value
      ? 'Choose whose records to browse. Search works without a personal shelf.'
      : mode === 'recent' ? 'Records you play will appear here.' : 'Search for music, then save a record to this shelf.');
    else message(items.length + (mode === 'search' ? ' results' : ' records') + ' · swipe to browse · tap the front album to play');
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
    ++shelfTicket; selectedIndex = 0; selectedUri = ''; data = {favorites:[], recent:[]}; render();
    try { localStorage.setItem('chauffeur_radio_member', member.value); } catch (_) {}
    loadShelf();
  });
  ['favorites', 'recent'].forEach(function (name) {
    document.getElementById('radio-' + name).addEventListener('click', function () {
      ++searchTicket; mode = name; selectedIndex = 0; selectedUri = ''; searchMode(false); aim('records'); render(); loadShelf();
    });
  });
  document.getElementById('radio-search-open').addEventListener('click', function () { searchMode(true); });
  function endSearch() {
    ++searchTicket; searchMode(false); aim('radio'); mode = 'favorites'; render();
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
      results = MusicLogic.flatten(found); selectedIndex = 0; selectedUri = ''; render();
      if (matchMedia('(max-width:700px)').matches) { searchMode(false); aim('records'); }
    } catch (_) {
      if (active && v === visit && ticket === searchTicket) message('Search could not connect. Try again.');
    }
  });
  query.addEventListener('input', function () { ++searchTicket; if (mode === 'search') message('Press Find to search.'); });
  ['prev', 'next'].forEach(function (direction) {
    document.getElementById('radio-record-' + direction).addEventListener('click', function () {
      arrange(selectedIndex + (direction === 'next' ? 1 : -1));
    });
  });
  records.addEventListener('keydown', function (event) {
    suppressClickUntil = 0;
    var index = {ArrowLeft:selectedIndex - 1, ArrowRight:selectedIndex + 1, Home:0, End:records.children.length - 1}[event.key];
    if (index === undefined) return;
    event.preventDefault(); arrange(index);
    var chosen = records.querySelector('.is-selected .record-play');
    if (chosen && !chosen.disabled) chosen.focus({preventScroll:true});
  });
  records.addEventListener('pointerdown', function (event) {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    suppressClickUntil = 0;
    gesture = {id:event.pointerId, x:event.clientX, y:event.clientY};
  });
  records.addEventListener('pointermove', function (event) {
    if (!gesture || gesture.id !== event.pointerId) return;
    if (Math.abs(event.clientX - gesture.x) > 12 && Math.abs(event.clientX - gesture.x) > Math.abs(event.clientY - gesture.y)) records.setPointerCapture(event.pointerId);
  });
  records.addEventListener('pointerup', function (event) {
    if (!gesture || gesture.id !== event.pointerId) return;
    var dx = event.clientX - gesture.x, dy = event.clientY - gesture.y; gesture = null;
    if (Math.abs(dx) > 30 && Math.abs(dx) > Math.abs(dy)) { suppressClickUntil = Date.now() + 350; arrange(selectedIndex + (dx < 0 ? 1 : -1)); }
  });
  records.addEventListener('pointercancel', function () { gesture = null; });
  document.querySelectorAll('[data-radio-camera]').forEach(function (button) {
    button.addEventListener('click', function () { window.HouseRadioControls?.close();searchMode(false); aim(button.dataset.radioCamera); });
  });
  window.addEventListener('radio-player-state', function (event) { available = event.detail.available; busy = event.detail.busy; paintButtons(); });
  window.HouseRecords = {
    refresh: function () { if(active)return loadShelf(); },
    open: async function () {
      active = true; var v = ++visit; shelf.hidden = false; aim('radio'); selectedIndex = 0; selectedUri = ''; mode = 'favorites'; data = {favorites:[], recent:[]}; results = []; render();
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
    close: function () { active = false; ++visit; ++searchTicket; ++shelfTicket; gesture = null; shelf.hidden = true; searchMode(false); query.value = ''; records.replaceChildren(); }
  };
})();
