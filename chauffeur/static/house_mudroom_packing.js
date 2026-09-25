/* Photographic backpacks use the existing Family Day data and claim controller. */
(function () {
  'use strict';
  var host = document.getElementById('mudroom-packing');
  if (!host) return;
  var row = host.querySelector('.mudroom-pack-row');
  var model = packingCard({data:{interactive:true,days:1}}, window.chfBase || '');
  var activities = new Map(), nodes = new Map(), selected = null, opener = null;
  var pending = null, writing = false, timer = null, pageIndex = 0;
  var room = document.getElementById('hybrid-mudroom');
  // Full-room regions include the photographed straps and contact shadows.
  var slots = [[325,580,230,255],[567,590,220,235],[802,604,197,215],[993,610,208,240]];
  var masks = slots.map(function (q) {
    return 'url("data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1536" height="1024" viewBox="0 0 1536 1024"><defs><filter id="soft"><feGaussianBlur stdDeviation="5"/></filter></defs><rect x="'+q[0]+'" y="'+q[1]+'" width="'+q[2]+'" height="'+q[3]+'" rx="15" fill="white" filter="url(#soft)"/></svg>') + '")';
  });
  ['openDay','closedDay','openNight','closedNight'].forEach(function (key) {
    host.style.setProperty('--'+key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase()),'url("'+new URL(host.dataset[key],document.baseURI).href+'")');
  });
  var pages = document.createElement('nav');pages.className = 'mudroom-pack-pages';pages.setAttribute('aria-label','More activity backpacks');
  pages.innerHTML = '<button type="button" aria-label="Previous backpacks">&#8249;</button><span></span><button type="button" aria-label="Next backpacks">&#8250;</button>';host.appendChild(pages);
  var previous = pages.firstElementChild, next = pages.lastElementChild;
  previous.addEventListener('click',function () {pageIndex--;layout();});
  next.addEventListener('click',function () {pageIndex++;layout();});
  function layout() {
    var small = innerWidth < 701 || innerHeight < 600, count = small ? 2 : 4;
    pageIndex = Math.max(0,Math.min(pageIndex,Math.ceil(activities.size/count)-1));
    var start = pageIndex*count, scale = Math.max(innerWidth/1536,innerHeight/1024);
    var shown = Math.min(count,activities.size-start), first = start%4;
    var group = slots.slice(first,first+shown), left=(innerWidth-1536*scale)/2, top=(innerHeight-1024*scale)/2;
    if (group.length) {
      var x0=group[0][0], last=group[group.length-1], x1=last[0]+last[2];
      left=Math.max(innerWidth-1536*scale,Math.min(0,innerWidth/2-(x0+x1)/2*scale));
      top=Math.max(innerHeight-1024*scale,Math.min(0,innerHeight-155-850*scale));
    }
    // The camera moves the room and bags together, preserving their floor contact.
    room.querySelectorAll('.utility-overview>img').forEach(function (img) {
      Object.assign(img.style,{left:left+'px',top:top+'px',width:1536*scale+'px',height:1024*scale+'px'});
    });
    Array.from(activities.keys()).forEach(function (key,index) {
      var node = nodes.get(key), local = index-start, slot=index%4, q=slots[slot];node.hidden = local<0 || local>=count;node.dataset.slot=slot;
      if (node.hidden) return;
      Object.assign(node.style,{left:left+q[0]*scale+'px',top:top+q[1]*scale+'px',width:q[2]*scale+'px',height:q[3]*scale+'px'});
      Object.assign(node.querySelector('.mudroom-pack-art').style,{left:-q[0]*scale+'px',top:-q[1]*scale+'px',width:1536*scale+'px',height:1024*scale+'px',maskImage:masks[slot]});
    });
    pages.hidden=activities.size<=count;previous.disabled=pageIndex===0;next.disabled=start+count>=activities.size;
    pages.querySelector('span').textContent=(start+1)+'–'+Math.min(start+count,activities.size)+' of '+activities.size;
    window.dispatchEvent(new Event('chf-mudroom-frame'));
  }
  function visible() { return !document.hidden && window.chfHouseMode?.() === 'mudroom'; }
  function collect() {
    var result = new Map(), now = Date.now();
    function add(block, event, groups) {
      groups = groups.filter(g => (g.items || []).some(it => it.needed > 0));
      if (!groups.length || !event.id) return;
      var source = block.for_key || block.key, key = source + ':' + event.id;
      var needed = 0, packed = 0;
      groups.forEach(g => g.items.forEach(it => {needed += it.needed || 0;packed += Math.min(it.packed || 0, it.needed || 0);}));
      result.set(key, {key:key, source:source, block:block, groups:groups, title:event.title || 'Activity', start:event.start, passengers:event.passengers || [], needed:needed, packed:packed, ready:packed >= needed});
    }
    // Source blocks take precedence over their earlier preparation tiles.
    model.blocks.filter(b => b.kind !== 'prep').forEach(function (b) {
      if (b.canceled || (b.end && new Date(b.end).getTime() <= now)) return;
      var events = b.kind === 'outing' ? b.events || [] : [{id:b.event_id,title:b.title,start:b.start,passengers:b.passengers}];
      events.forEach(e => add(b, e, (b.groups || []).filter(g => !(g.event_ids || []).length || g.event_ids.includes(e.id))));
    });
    model.blocks.filter(b => b.kind === 'prep').forEach(function (b) {
      if (b.canceled || (b.window_ends && new Date(b.window_ends).getTime() <= now)) return;
      (b.tiles || []).forEach(function (t) {
        if (!result.has(t.for_key + ':' + t.event_id)) add(t, {id:t.event_id,title:t.title,start:t.start,passengers:t.passengers}, t.groups || []);
      });
    });
    return new Map(Array.from(result).sort((a,b) => String(a[1].start || '').localeCompare(String(b[1].start || ''))));
  }
  function ownsDialog() { return selected && window.packDialog?.openFor() === 'mudroom:' + selected; }
  function paint() {
    activities = collect();host.hidden = !activities.size;
    nodes.forEach(function (node, key) {if (!activities.has(key)) {node.remove();nodes.delete(key);}});
    activities.forEach(function (activity, key) {
      var button = nodes.get(key);
      if (!button) {
        button = document.createElement('button');button.type = 'button';button.className = 'mudroom-pack';button.dataset.activity = key;
        button.innerHTML = '<span class="mudroom-pack-art" aria-hidden="true"></span><span class="mudroom-pack-label"><strong></strong><small></small></span>';
        button.addEventListener('click', function () {open(key,button);});nodes.set(key,button);row.appendChild(button);
      }
      button.dataset.ready = String(activity.ready);
      button.querySelector('strong').textContent = activity.title;
      var status = activity.ready ? 'Packed' : activity.packed + ' of ' + activity.needed + ' packed';
      button.querySelector('small').textContent = status;
      button.setAttribute('aria-label', activity.title + ': ' + status + '. Open packing list');
      button.title = activity.title + ' - ' + status;
    });
    layout();
    if (ownsDialog()) {
      var current = activities.get(selected);
      if (current) window.packDialog.update({groups:current.groups});else close();
    }
  }
  function close() {
    if (ownsDialog()) window.packDialog.close();
    selected = null;
    if (opener?.isConnected && visible()) opener.focus({preventScroll:true});
  }
  function open(key, button) {
    var activity = activities.get(key);if (!activity) return;
    selected = key;opener = button;
    window.packDialog.open({tileKey:'mudroom:' + key,title:activity.title,passengers:activity.passengers,groups:activity.groups,interactive:true,onClaim:async function (itemKey, delta) {
      if (writing) return;
      var current = activities.get(key), item = current?.groups.flatMap(g => g.items || []).find(it => it.key === itemKey);
      if (!item) return;
      writing = true;
      try {var claim = model.pkClaim(current.block, item, delta);paint();await claim;}
      finally {writing = false;paint();await refresh();}
    }});
    document.querySelector('#pack-dialog-root [data-pack-close]')?.focus();
  }
  async function refresh() {
    if (!visible() || writing) return;
    if (pending) return pending;
    pending = model.loadPacking().then(paint).finally(function () {pending = null;});return pending;
  }
  function sync() {
    clearInterval(timer);timer = null;
    if (visible()) {refresh();timer = setInterval(refresh,30000);}
    else close();
  }
  window.addEventListener('chf-hybrid-room',sync);
  window.addEventListener('resize',layout);
  document.addEventListener('visibilitychange',sync);
  document.addEventListener('chf-pack-change',refresh);
  document.addEventListener('chf-server-update',refresh);
  document.addEventListener('click',function () {if (selected && !window.packDialog.isOpen()) close();});
  document.addEventListener('keydown',function (event) {
    if (!ownsDialog()) return;
    if (event.key === 'Escape') {event.preventDefault();event.stopImmediatePropagation();close();}
    if (event.key === 'Tab') {
      var controls = Array.from(document.querySelectorAll('#pack-dialog-root button:not([disabled])'));
      var first = controls[0], last = controls[controls.length-1];
      if (event.shiftKey && document.activeElement === first) {event.preventDefault();last?.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault();first?.focus();}
    }
  },true);
  window.addEventListener('pagehide',function () {clearInterval(timer);close();});
  window.addEventListener('pageshow',sync);
  window.chfMudroomPacking = {refresh:refresh};
  sync();
})();
