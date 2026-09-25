/* Kitchen photographs and live household cards share a coordinate plane. */
(function () {
  'use strict';
  var room = document.getElementById('hybrid-kitchen');
  if (!room) return;
  var overview = document.getElementById('kitchen-overview');
  var detail = document.getElementById('kitchen-detail');
  var plane = document.getElementById('kitchen-detail-plane');
  var controls = document.getElementById('kitchen-controls');
  var back = document.getElementById('kitchen-back');
  var shortcuts = document.getElementById('kitchen-shortcuts');
  var status = document.getElementById('kitchen-status');
  var active = null, trigger = null, dark = false, revision = 0, lightRevision = 0;
  var loads = new Map(), reduced = matchMedia('(prefers-reduced-motion: reduce)');
  var initial=Object.assign({},history.state); delete initial.chfKitchenView;
  history.replaceState(initial,'',location.href);
  var entries = [
    {key:'moments', label:'Family moments', view:'moments', x:.14, y:.28, rect:[315,160,720,730], icon:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="2"/><path d="m4 18 6-6 4 4 3-3 4 5"/>'},
    {key:'meals', label:'Meals', view:'meals', x:.33, y:.36, rect:[423,219,580,421], icon:'<path d="M4 3v7m4-7v7M6 3v18m-2-11h4M17 3c-5 6-5 10 0 10V3v18"/>'},
    {key:'lists', label:'Groceries', view:'pantry', x:.046, y:.36, rect:[578,195,347,430], icon:'<path d="M8 6h13M8 12h13M8 18h13m-18-12 1 1 2-3m-3 8 1 1 2-3m-3 8 1 1 2-3"/>'},
    {key:'calendar', label:'Calendar', view:'board', x:.74, y:.27, rect:[548,190,454,565], icon:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M7 3v4m10-4v4m-10 7h3m4 0h3m-10 4h3"/>'},
    {key:'weather', label:'Weather', view:'weather', x:.884, y:.36, rect:[237,94,227,381], fit:[175,35,1090,690], icon:'<circle cx="10" cy="10" r="4"/><path d="M10 1v2m0 14v2M1 10h2m14 0h2M3 3l2 2m10 10 2 2M17 3l-2 2M3 17l2-2M12 20h9"/>'}
  ];
  function load(img) {
    if (img.complete && img.naturalWidth) return Promise.resolve();
    if (loads.has(img)) return loads.get(img);
    var pending = (async function () { img.src = img.dataset.src; await img.decode(); })()
      .catch(function (error) { loads.delete(img); throw error; });
    loads.set(img, pending); return pending;
  }
  function project() {
    var scale = Math.max(innerWidth/1536, innerHeight/1024);
    entries.forEach(function (entry) {
      var el = document.querySelector('#kitchen-hotspots [data-card="'+entry.key+'"]');
      el.style.left = (entry.x*1536*scale+(innerWidth-1536*scale)/2)+'px';
      el.style.top = (entry.y*1024*scale+(innerHeight-1024*scale)/2)+'px';
    });
    Object.assign(document.getElementById('kitchen-room-surfaces').style,{width:1536*scale+'px',height:1024*scale+'px',left:(innerWidth-1536*scale)/2+'px',top:(innerHeight-1024*scale)/2+'px'});
    if (!active) return;
    var r = active.rect, fit = active.fit || r;
    if(active.key==='weather' && innerWidth<701)fit=[180,60,345,445];
    var top = innerWidth < 701 ? 205 : 155, bottom = 120;
    if (innerHeight < 600) { top = 72; bottom = 20; }
    var width = Math.min(active.key==='weather'?1180:720, innerWidth-48), height = Math.max(160,innerHeight-top-bottom);
    // The registered photograph always covers the viewport. A small screen
    // can pan across the object instead of shrinking it into an inset panel.
    var zoom = Math.max(scale, Math.min(width/(fit[2]+48), height/(fit[3]+48)));
    var wideCalendar=active.key==='calendar' && innerWidth>=1100 && innerWidth>innerHeight;
    window.chfPaperFrame(plane,controls,null);
    Object.assign(plane.style,{width:1536*zoom+'px',height:1024*zoom+'px',left:'0px',top:'0px'});
    detail.scrollLeft=Math.max(0,Math.min(1536*zoom-innerWidth,(fit[0]+fit[2]/2)*zoom-innerWidth/2));
    detail.scrollTop=Math.max(0,Math.min(1024*zoom-innerHeight,(fit[1]+fit[3]/2)*zoom-(top+height/2)));
    Object.assign(controls.style,{left:r[0]/1536*100+'%',top:r[1]/1024*100+'%',width:r[2]/1536*100+'%',height:r[3]/1024*100+'%'});
    if(wideCalendar)window.chfPaperFrame(plane,controls,image(),[272,190,1096,487],[403,282,835,304]);
    if(active.key==='calendar')requestAnimationFrame(function(){window.FamilyCalendar?.get('kitchen-wall-calendar')?.updateSize();});
  }
  function image() { return detail.querySelector('[data-kitchen-view="'+active.view+'"][data-light="'+(dark?'night':'day')+'"]'); }
  async function show() {
    if (!active) return;
    var ticket = ++revision, entry = active, img = image();
    room.setAttribute('aria-busy','true');
    try {
      await load(img);
      if (ticket !== revision || active !== entry) return;
      detail.querySelectorAll('[data-kitchen-view]').forEach(function (other) { other.classList.toggle('is-active',other===img); });
      img.alt = entry.label+' close-up in the kitchen';
      project();
      await new Promise(function (resolve) { setTimeout(resolve,reduced.matches?0:420); });
      if (ticket !== revision || active !== entry) return;
      room.dataset.phase='detail'; room.setAttribute('aria-busy','false');
      status.textContent='';
      window.chfKitchenSurfaces?.view(entry.key);
      if (entry.key !== 'moments' && window.Alpine && Alpine.$data(document.getElementById('house-life')).active !== entry.key)
        window.dispatchEvent(new CustomEvent('chf-house-open',{detail:entry.key}));
    } catch (_) {
      if (ticket === revision) { room.setAttribute('aria-busy','false'); status.textContent='This close-up could not load. Return to the kitchen and try again.'; }
    }
  }
  function enter(key, button, remember) {
    if (active || document.body.dataset.houseScene !== 'kitchen') return;
    var entry=entries.find(function (e) { return e.key===key; });
    if (!entry) return;
    active=entry; trigger=button;
    if (remember) history.pushState(Object.assign({},history.state,{chfKitchenView:key}),'',location.href);
    room.dataset.view=key; room.dataset.phase='loading'; overview.inert=true; shortcuts.inert=true;
    var scale=Math.max(innerWidth/1536,innerHeight/1024);
    overview.style.transformOrigin=(entry.x*1536*scale+(innerWidth-1536*scale)/2)+'px '+(entry.y*1024*scale+(innerHeight-1024*scale)/2)+'px';
    window.chfKitchenSurfaces?.view(key);
    detail.hidden=false; back.hidden=false; back.focus(); status.textContent='Moving closer…'; show();
  }
  function reset(focus) {
    if (!active) return false;
    ++revision; active=null; room.dataset.view='room'; room.dataset.phase='room';
    window.chfKitchenSurfaces?.view('room');
    detail.hidden=true; back.hidden=true; overview.inert=false; shortcuts.inert=false;
    room.setAttribute('aria-busy','false'); status.textContent='Choose an object to move closer.';
    window.dispatchEvent(new CustomEvent('chf-house-close'));
    if (focus && trigger) {
      var target=trigger.offsetWidth?trigger:shortcuts.querySelector('[data-card="'+trigger.dataset.card+'"]');
      target?.focus({preventScroll:true});
    }
    return true;
  }
  function leave() {
    if (!active) return false;
    reset(true);
    if (history.state?.chfKitchenView) history.back();
    return true;
  }
  entries.forEach(function (entry) {
    [document.getElementById('kitchen-hotspots'),shortcuts].forEach(function (host,index) {
      var button=document.createElement('button'); button.type='button';button.dataset.card=entry.key;
      button.className=index?'kitchen-shortcut':'hybrid-marker';button.setAttribute('aria-label',entry.label);
      button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true">'+entry.icon+'</svg><span class="'+(index?'':'hybrid-marker-label')+'">'+entry.label+'</span>';
      button.addEventListener('click',function () { enter(entry.key,button,true); });host.appendChild(button);
    });
  });
  async function paintLight(night) {
    dark=night; room.dataset.light=dark?'night':'day';
    var ticket=++lightRevision, img=room.querySelector('[data-kitchen-room="'+(dark?'night':'day')+'"]');
    if (room.hidden) return;
    try { await load(img); if(ticket!==lightRevision)return;
      overview.querySelectorAll('[data-kitchen-room]').forEach(function (other) { other.classList.toggle('is-active',other===img); });
      if(active)show();
    } catch (_) { status.textContent='Kitchen artwork could not load. Try entering the room again.'; }
  }
  window.chfKitchenReady=async function () {
    var choice=document.getElementById('house-compare-light').value;
    dark=choice==='auto'?document.getElementById('hybrid-room-frame').dataset.light==='night':choice==='night';
    var img=room.querySelector('[data-kitchen-room="'+(dark?'night':'day')+'"]'); await load(img);
    overview.querySelectorAll('[data-kitchen-room]').forEach(function (other) { other.classList.toggle('is-active',other===img); });
    room.dataset.light=dark?'night':'day'; project(); window.chfKitchenSurfaces?.refresh();
  };
  window.chfKitchenVisit=function (zone, remember) { var key={fridge:'moments',counter:'meals',pantry:'lists',board:'lists',calendar:'calendar',window:'weather'}[zone]||zone; enter(key,document.querySelector('#kitchen-hotspots [data-card="'+key+'"]'),remember!==false); };
  window.chfKitchenBack=leave; window.chfKitchenReset=function () { reset(false); };
  window.chfKitchenProbe=function () { return {view:active?.key||'room',phase:room.dataset.phase||'room',light:dark?'night':'day'}; };
  back.addEventListener('click',leave);
  window.addEventListener('chf-house-closed',function () { if(active)leave(); });
  window.addEventListener('chf-house-light',function (event) { paintLight(event.detail); });
  window.addEventListener('resize',project);
  window.addEventListener('popstate',function () {
    var key=history.state?.chfKitchenView;
    if(!key)reset(true);
    else if(!active && document.body.dataset.houseScene==='kitchen')enter(key,document.querySelector('#kitchen-hotspots [data-card="'+key+'"]'),false);
  });
  document.addEventListener('keydown',function (event) {
    if(document.querySelector('[data-moment-overlay]'))return;
    if(event.key==='Escape' && !document.getElementById('simple-event-modal')?.classList.contains('hidden')){event.preventDefault();FamilyCalendar.closeEvent();return;}
    if(event.key==='Escape' && active && !event.defaultPrevented){event.preventDefault();event.stopImmediatePropagation();leave();}
  });
  project();
})();
