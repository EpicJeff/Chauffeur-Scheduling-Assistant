/* Mudroom and private Study: registered photographs, existing household data. */
(function(){
  'use strict';
  var base=window.chfBase||'',rooms={},loads=new Map(),active=null,revision=0,dark=false;
  var furniture={},studyToken=null,studyRevision=0,studyRefresh=0;
  var plantReading=false,gaugeReading=false;
  var icons={
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 3"/>',
    list:'<path d="M8 6h13M8 12h13M8 18h13M3 6h1m-1 6h1m-1 6h1"/>',
    routine:'<path d="M4 11a8 8 0 0 1 14-5l2 2M20 3v5h-5M20 13a8 8 0 0 1-14 5l-2-2M4 21v-5h5"/>',
    board:'<rect x="3" y="3" width="18" height="16" rx="1"/><path d="M8 7v5m-2-3h4m4 5h4M8 19v3m8-3v3"/>',
    book:'<path d="M12 5C8 3 4 3 2 4v16c3-1 6-1 10 1 4-2 7-2 10-1V4c-3-1-6-1-10 1v16"/>',
    screen:'<rect x="2" y="3" width="20" height="14" rx="1"/><path d="M12 17v4M7 21h10"/>',
    calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M7 3v4m10-4v4M7 14h3m4 0h3"/>'
  };
  var entries={mudroom:[
    ['schedule','Next up','next',.437,.28,'clock'],['chores','Chores','chores',.57,.28,'list'],['routines','Routines','routines',.71,.28,'routine']
  ],study:[
    ['board','Connections board','board',.50,.25,'board','mind'],['desk','Plans in hand','desk',.57,.49,'book','mind'],
    ['tray','Intake tray','tray',.43,.50,'list','intake'],['stickies','Findings','findings',.60,.21,'list','dashboard'],
    ['calendar','Coverage calendar','planner',.725,.25,'calendar','dashboard'],['window','Family baseline','plant',.36,.44,'routine','mind'],
    ['contracts','Agreements','agreements',.708,.50,'book','dashboard'],['binders','Program binders','binders',.812,.29,'book','programs'],
    ['gauges','Argyle gauges','gauges',.884,.48,'clock','mind'],['monitor','Household monitor','monitor',.82,.412,'screen','mind'],
    ['map','Travel map','map',.93,.22,'calendar','trips']
  ]};
  var rects={
    'mudroom-next':[566,145,414,610],'mudroom-chores':[530,160,544,422],'mudroom-routines':[536,191,462,532],
    'study-board':[510,170,533,489],'study-desk':[370,389,824,335],'study-planner':[502,154,540,637],
    'study-binders':[488,215,668,518],'study-monitor':[333,197,860,426],
    'study-tray':[429,176,692,574],'study-findings':[574,177,465,662],
    'study-agreements':[307,280,922,448],'study-gauges':[267,246,1006,420],
    'study-map':[302,166,921,550],'study-plant':[974,562,353,228]
  };
  // Clockwise corners of the writable planes, measured in the photographs.
  // Project the actual DOM so text, inputs and pointer hit areas stay together.
  var paperCorners={tray:[[500,176],[1054,178],[1121,750],[429,748]],desk:[[455,389],[1121,389],[1194,724],[370,724]]};
  function paperTransform(corners,rect,zoom){
    var p=corners.map(c=>[(c[0]-rect[0])*zoom,(c[1]-rect[1])*zoom]);
    var [a,b,c,d]=p,dx1=b[0]-c[0],dx2=d[0]-c[0],dy1=b[1]-c[1],dy2=d[1]-c[1];
    var dx3=a[0]-b[0]+c[0]-d[0],dy3=a[1]-b[1]+c[1]-d[1],den=dx1*dy2-dx2*dy1;
    var g=(dx3*dy2-dx2*dy3)/den,h=(dx1*dy3-dx3*dy1)/den,w=rect[2]*zoom,height=rect[3]*zoom;
    return 'matrix3d('+[(b[0]-a[0]+g*b[0])/w,(b[1]-a[1]+g*b[1])/w,0,g/w,
      (d[0]-a[0]+h*d[0])/height,(d[1]-a[1]+h*d[1])/height,0,h/height,
      0,0,1,0,a[0],a[1],0,1].join(',')+')';
  }
  function load(img){
    if(img.complete&&img.naturalWidth)return Promise.resolve();
    if(loads.has(img))return loads.get(img);
    var promise=(async()=>{img.src=img.dataset.src;await img.decode();})().catch(e=>{loads.delete(img);throw e;});loads.set(img,promise);return promise;
  }
  Object.keys(entries).forEach(function(name){
    var el=document.getElementById('hybrid-'+name);if(!el)return;
    var r=rooms[name]={name:name,el:el,overview:el.querySelector('.utility-overview'),detail:el.querySelector('.utility-detail'),plane:el.querySelector('.utility-plane'),controls:el.querySelector('.utility-controls'),back:el.querySelector('.utility-back'),status:el.querySelector('.utility-status'),shortcuts:el.querySelector('.utility-shortcuts')};
    r.entries=entries[name].map(function(a){return {key:a[0],label:a[1],view:a[2],x:a[3],y:a[4],icon:a[5],href:a[6],rect:rects[name+'-'+a[2]]};});
    r.entries.forEach(function(e){[el.querySelector('.utility-hotspots'),r.shortcuts].forEach(function(host,i){
      var b=document.createElement('button');b.type='button';b.dataset.card=e.key;b.className=i?'utility-shortcut':'hybrid-marker';b.setAttribute('aria-label',e.label);
      b.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true">'+icons[e.icon]+'</svg><span class="'+(i?'':'hybrid-marker-label')+'">'+e.label+'</span>';
      b.addEventListener('click',()=>visit(e.key,true,b));host.appendChild(b);
    });});
    r.back.addEventListener('click',back);
    if(name==='study'){r.plantRead=document.createElement('button');r.plantRead.type='button';r.plantRead.className='study-plant-read';r.plantRead.textContent='Read baseline';r.plantRead.addEventListener('click',function(){plantReading=!plantReading;r.plantRead.textContent=plantReading?'View plant':'Read baseline';project();});el.appendChild(r.plantRead);}
    if(name==='study'){r.gaugeRead=document.createElement('button');r.gaugeRead.type='button';r.gaugeRead.className='study-gauge-read';r.gaugeRead.textContent='Research →';r.gaugeRead.addEventListener('click',function(){gaugeReading=!gaugeReading;r.gaugeRead.textContent=gaugeReading?'← Thinking':'Research →';project();});el.appendChild(r.gaugeRead);}
  });
  function project(){
    var cover=Math.max(innerWidth/1536,innerHeight/1024);
    Object.values(rooms).forEach(function(r){
      var image=r.overview.querySelector('img');
      var dx=r.name==='mudroom'&&image.style.left?parseFloat(image.style.left):(innerWidth-1536*cover)/2;
      var dy=r.name==='mudroom'&&image.style.top?parseFloat(image.style.top):(innerHeight-1024*cover)/2;
      r.entries.forEach(function(e){var b=r.el.querySelector('.utility-hotspots [data-card="'+e.key+'"]');b.style.left=e.x*1536*cover+dx+'px';b.style.top=e.y*1024*cover+dy+'px';});
    });
    if(!active)return;
    var r=active.room,q=active.entry.rect,top=innerHeight<600?65:innerWidth<701?200:155,bottom=innerHeight<600?20:120;
    if(active.entry.key==='monitor'&&innerWidth<701&&innerHeight>=600)top=260;
    if(['tray','map'].includes(active.entry.key)&&innerWidth<701&&innerHeight>=600)top=280;
    if(active.entry.key==='contracts'&&innerWidth<701)q=[307,280,390,448];
    var height=Math.max(160,innerHeight-top-bottom),zoom=Math.max(cover,Math.min((innerWidth-48)/(q[2]+45),height/(q[3]+45)));
    var camera=q;
    // Fit the photographed frame as well as its paper; retain the physical object.
    if(r.name==='mudroom' && ['chores','routines'].includes(active.entry.key) && innerWidth>=1100 && innerWidth>innerHeight) {
      q=active.entry.key==='chores'?[332,216,938,267]:[330,447,875,272];
      camera=active.entry.key==='chores'?[224,125,1156,444]:[264,320,1014,475];
      top=90; bottom=100; height=innerHeight-top-bottom;
      zoom=Math.min((innerWidth-64)/camera[2],height/camera[3]);
    }
    if(active.entry.key==='monitor'&&innerWidth<701)zoom=Math.max(cover,(height+120)/q[3]);
    if(['tray','map'].includes(active.entry.key)&&innerWidth<701&&innerHeight>=600)zoom=Math.max(cover,1.12);
    if(active.entry.key==='window'){
      zoom=cover;
      camera=innerWidth<701?(plantReading?q:[320,160,560,730]):[0,0,1536,1024];
    }
    if(active.entry.key==='gauges'&&innerWidth<701){zoom=cover;camera=[gaugeReading?847:267,246,420,420];}
    Object.assign(r.plane.style,{width:1536*zoom+'px',height:1024*zoom+'px'});
    r.detail.scrollLeft=Math.max(0,Math.min(1536*zoom-innerWidth,(camera[0]+camera[2]/2)*zoom-innerWidth/2));
    r.detail.scrollTop=Math.max(0,Math.min(1024*zoom-innerHeight,(camera[1]+camera[3]/2)*zoom-top-height/2));
    Object.assign(r.controls.style,{left:q[0]/1536*100+'%',top:q[1]/1024*100+'%',width:q[2]/1536*100+'%',height:q[3]/1024*100+'%'});
    var corners=r.name==='study'&&paperCorners[active.entry.key];
    r.controls.style.transformOrigin='0 0';r.controls.style.transform=corners?paperTransform(corners,q,zoom):'none';
    r.controls.style.setProperty('--read-width',Math.min(q[2]*zoom,innerWidth-56)+'px');
    r.controls.style.setProperty('--read-height',Math.min(q[3]*zoom,height)+'px');
  }
  function element(tag,text,host,cls){var e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;host.appendChild(e);return e;}
  function studyRows(key){
    var d=furniture[key]||{};
    switch(key){
      case 'board':return(d.pins||[]).map(p=>[p.label,p.kind==='insight'?'Argyle noticed':'Thread']);
      case 'desk':return(Array.isArray(d)?d:[]).map(p=>[p.line,(p.open_steps||0)+' open steps'+(p.due?' · one due':'')]);
      case 'tray':return(d.items||[]).map(i=>[i.title,'Waiting']);
      case 'stickies':return(d.items||[]).map(i=>[i.line,i.severity||'For your information']);
      case 'calendar':return(d.days||[]).map(day=>[day.date,[day.unassigned?day.unassigned+' uncovered':'Covered',(day.events||[]).map(e=>e.title).filter(Boolean).join(' · '),day.more?'+'+day.more+' more':''].filter(Boolean).join(' · ')]);
      case 'window':return(d.signs||[]).map(s=>[s,d.ready?d.label||'Family baseline':'Baseline is still forming']);
      case 'contracts':return(d.items||[]).map(i=>[i.title,'Awaiting an answer']);
      case 'binders':return(Array.isArray(d)?d:[]).map(b=>[b.title,[b.pulled?'Needs a look':'',b.detail].filter(Boolean).join(' · ')]);
      case 'monitor':return(d.clusters||[]).map(c=>[c.name,c.count+' calendar items this week']);
      case 'gauges':return [['Thinking',d.think==null?'Unavailable':d.think+' / '+d.think_cap],['Research',d.research==null?'Unavailable':d.research+' / '+d.research_cap],['Ingest errors',String(d.ingest_errors??'Unavailable')]];
      case 'map':return(d.trips||[]).map(t=>[t.title,[t.location,t.start_ts?new Date(t.start_ts*1000).toLocaleDateString():null].filter(Boolean).join(' · ')]);
    }
    return [];
  }
  function renderStudy(){
    if(!active||active.room.name!=='study')return;
    if(window.chfStudySurfaces?.editing(active.room.controls))return;
    if(window.chfStudySurfaces?.render(active.room.controls,active.entry.key,furniture,fetchStudy))return;
    var r=active.room,e=active.entry;r.controls.replaceChildren();
    var panel=element('section',undefined,r.controls,'study-paper');panel.setAttribute('aria-label',e.label);
    element('h2',e.label,panel);var rows=studyRows(e.key),body=element('div',undefined,panel,'study-rows');
    if(!rows.length)element('p',({board:'The connections board is clear.',desk:'No plans in hand.',tray:'The intake tray is empty.',stickies:'No findings waiting.',calendar:'No coverage items to show.',window:'No baseline signs yet.',contracts:'No agreements awaiting answers.',binders:'No programs running.',monitor:'No household activity to show.',map:'No trips planned.'})[e.key]||'Nothing here yet.',body,'study-empty');
    if(e.key==='calendar'){
      var days=furniture.calendar?.days||[],first=new Date((days[0]?.date||new Date().toISOString().slice(0,10))+'T12:00:00');
      element('p',first.toLocaleDateString(undefined,{month:'long',year:'numeric'}),body,'study-calendar-month');
      var grid=element('div',undefined,body,'study-calendar');grid.setAttribute('aria-label','Monthly coverage calendar');
      ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].forEach(day=>element('strong',day,grid));
      var start=new Date(first.getFullYear(),first.getMonth(),1,12);start.setDate(start.getDate()-start.getDay());
      for(var n=0;n<42;n++){
        var date=new Date(start);date.setDate(start.getDate()+n);
        var iso=date.getFullYear()+'-'+String(date.getMonth()+1).padStart(2,'0')+'-'+String(date.getDate()).padStart(2,'0');
        var day=days.find(d=>d.date===iso),cell=element('article',undefined,grid,date.getMonth()===first.getMonth()?'':'other-month');
        element('h3',String(date.getDate()),cell);
        if(day){if(day.unassigned)element('b',day.unassigned+' uncovered',cell);(day.events||[]).forEach(event=>element('p',event.title,cell));}
      }
    }else rows.forEach(function(row){var item=element('article',undefined,body);element('h3',row[0]||'Untitled',item);if(row[1])element('p',row[1],item);});
    var link=element('a','Open '+({mind:'Argyle',dashboard:'Dashboard',intake:'Intake',programs:'Programs',trips:'Trips'}[e.href]||e.label)+' →',panel,'study-manage');
    link.href=base+e.href+'?panel=false';link.addEventListener('click',function(event){if(!window.chfHouseParent?.()){event.preventDefault();expireStudy();return;}window.chfHouseRemember?.();});
  }
  async function show(){
    if(!active)return;var visit=active,r=visit.room,e=visit.entry,ticket=++revision;
    var view=e.view;if(e.key==='window'){var state=plantState();if(state==='drooping'||state==='wilting')view='plant-'+state;}
    var img=r.el.querySelector('[data-utility-view="'+view+'"][data-light="'+(dark?'night':'day')+'"]');r.el.setAttribute('aria-busy','true');
    try{await load(img);if(ticket!==revision||active!==visit)return;
      r.plane.querySelectorAll('img').forEach(i=>i.classList.toggle('is-active',i===img));img.alt=e.label+' in the '+r.name;project();
      r.el.dataset.phase='detail';r.el.setAttribute('aria-busy','false');r.status.textContent='';
      if(r.name==='study')renderStudy();else if(window.Alpine&&Alpine.$data(document.getElementById('house-life')).active!==e.key)window.dispatchEvent(new CustomEvent('chf-house-open',{detail:e.key}));
    }catch(_){if(ticket===revision){r.el.setAttribute('aria-busy','false');r.status.textContent='This close-up could not load. Return to the room and try again.';}}
  }
  function visit(key,remember,button){
    var r=rooms[document.body.dataset.houseScene];if(!r||active)return;
    key=({door:'schedule',study:'board'})[key]||key;var e=r.entries.find(e=>e.key===key);if(!e)return;
    if(r.name==='study'&&!window.chfHouseParent?.()){expireStudy();return;}
    active={room:r,entry:e,trigger:button||r.el.querySelector('[data-card="'+key+'"]')};
    plantReading=false;gaugeReading=false;if(r.plantRead)r.plantRead.textContent='Read baseline';if(r.gaugeRead)r.gaugeRead.textContent='Research →';
    if(remember!==false)history.pushState(Object.assign({},history.state,{chfUtilityView:key}),'',location.href);
    r.el.dataset.view=key;r.el.dataset.phase='loading';r.el.dataset.surface=e.view==='monitor'||e.view==='next'?'screen':'paper';
    r.overview.inert=true;r.shortcuts.inert=true;r.detail.hidden=false;r.back.hidden=false;r.back.focus();r.status.textContent='Moving closer…';show();
  }
  function reset(focus){
    if(!active)return false;var old=active,r=old.room;active=null;++revision;
    r.el.dataset.view='room';r.el.dataset.phase='room';r.detail.hidden=true;r.back.hidden=true;r.overview.inert=false;r.shortcuts.inert=false;r.el.setAttribute('aria-busy','false');r.status.textContent='Choose an object to move closer.';
    if(r.name==='study'){r.controls.replaceChildren();window.chfStudySurfaces?.clear();}else window.dispatchEvent(new CustomEvent('chf-house-close'));
    if(focus){var b=old.trigger;if(!b?.offsetWidth)b=r.shortcuts.querySelector('[data-card="'+old.entry.key+'"]');b?.focus({preventScroll:true});}return true;
  }
  function back(){if(!reset(true))return false;if(history.state?.chfUtilityView)history.back();return true;}
  function lock(){++studyRevision;furniture={};studyToken=null;studyRefresh=0;rooms.study.controls.replaceChildren();window.chfStudySurfaces?.clear();window.chfHouseEndParent?.();}
  function plantState(){var d=furniture.window||{};return !d.ready?'unknown':d.plant_state||((d.worse||[]).length>1?'wilting':d.worse?.length?'drooping':'thriving');}
  function expireStudy(){lock();if(document.body.dataset.houseScene==='study'){reset(false);window.chfHybridGo('living',false);}}
  async function fetchStudy(){
    var session=window.chfHouseParent?.();if(!session)throw new Error('Study locked');
    var ticket=++studyRevision,response=await fetch(base+'api/study/state',{credentials:'same-origin',headers:{'X-Member-Token':session.token}});
    if(!response.ok){if(response.status===401||response.status===403)expireStudy();throw new Error('Study unavailable');}
    var data=await response.json();if(ticket!==studyRevision||window.chfHouseParent?.()?.token!==session.token)throw new Error('Study locked');
    var oldPlant=plantState();furniture=data.furniture||{};studyToken=session.token;studyRefresh=Date.now();renderStudy();
    if(oldPlant!==plantState()){if(active?.entry.key==='window')show();updatePlantOverview();}
  }
  async function roomReady(name){
    var r=rooms[name],choice=document.getElementById('house-compare-light').value;
    dark=choice==='auto'?document.getElementById('hybrid-room-frame').dataset.light==='night':choice==='night';
    if(name==='study')await fetchStudy();
    var img=r.el.querySelector('[data-room-light="'+(dark?'night':'day')+'"]'+(name==='study'?'[data-plant="'+overviewPlant()+'"]':''));await load(img);
    r.overview.querySelectorAll('img').forEach(i=>i.classList.toggle('is-active',i===img));r.el.dataset.light=dark?'night':'day';project();
  }
  function overviewPlant(){var state=plantState();return state==='drooping'||state==='wilting'?state:'thriving';}
  async function updatePlantOverview(){var r=rooms.study,state=overviewPlant(),light=dark?'night':'day',img=r.el.querySelector('[data-room-light="'+light+'"][data-plant="'+state+'"]');if(!img)return;try{await load(img);if(state!==overviewPlant()||light!==(dark?'night':'day'))return;r.overview.querySelectorAll('img').forEach(i=>i.classList.toggle('is-active',i===img));}catch(_){}}
  window.chfUtilityRooms={ready:roomReady,visit:visit,reset:()=>reset(false),back:back,lock:lock};
  window.chfUtilityProbe=()=>({room:active?.room.name||document.body.dataset.houseScene,view:active?.entry.key||'room',privateLoaded:!!studyToken});
  document.getElementById('study-lock').addEventListener('click',function(){lock();reset(false);window.chfHybridGo('living');});
  window.addEventListener('resize',project);
  window.addEventListener('chf-mudroom-frame',project);
  window.addEventListener('chf-house-closed',function(){if(active?.room.name==='mudroom')back();});
  window.addEventListener('chf-house-light',async function(e){dark=e.detail;var r=rooms[document.body.dataset.houseScene];if(!r)return;try{var light=dark?'night':'day',img=r.el.querySelector('[data-room-light="'+light+'"]'+(r.name==='study'?'[data-plant="'+overviewPlant()+'"]':''));await load(img);if(light!==(dark?'night':'day'))return;r.overview.querySelectorAll('img').forEach(i=>i.classList.toggle('is-active',i===img));r.el.dataset.light=light;if(active)show();}catch(_){r.status.textContent='Room lighting could not load.';}});
  window.addEventListener('popstate',function(){var key=history.state?.chfUtilityView;if(!key)reset(true);else if(!active&&rooms[document.body.dataset.houseScene])visit(key,false);});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&active&&!e.defaultPrevented){e.preventDefault();e.stopImmediatePropagation();back();}});
  // The existing parent visit owns its token and absolute/idle deadlines.
  function checkStudy(){if(document.body.dataset.houseScene!=='study')return;if(!window.chfHouseParent?.()){expireStudy();return;}if(!document.hidden&&Date.now()-studyRefresh>45000){studyRefresh=Date.now();fetchStudy().catch(()=>{rooms.study.status.textContent='Study updates are unavailable. Showing the last loaded information.';});}}
  var timer=setInterval(checkStudy,1000);
  ['pointerdown','keydown'].forEach(function(event){document.addEventListener(event,function(){if(document.body.dataset.houseScene==='study')window.chfHouseTouchParent?.();});});
  document.addEventListener('visibilitychange',function(){if(document.body.dataset.houseScene==='study'&&!window.chfHouseParent?.())expireStudy();});
  window.addEventListener('pagehide',function(){clearInterval(timer);++studyRevision;furniture={};studyToken=null;rooms.study.controls.replaceChildren();window.chfStudySurfaces?.clear();rooms.study.el.hidden=true;});
  window.addEventListener('pageshow',function(e){if(!e.persisted)return;timer=setInterval(checkStudy,1000);if(document.body.dataset.houseScene==='study'){if(!window.chfHouseParent?.())expireStudy();else fetchStudy().then(()=>{rooms.study.el.hidden=false;}).catch(expireStudy);}});
  project();
})();
