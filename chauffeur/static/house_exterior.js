/* Exterior previews and connected photographic rooms share one navigation owner. */
(function(){
  'use strict';
  var exterior=document.getElementById('house-exterior');if(!exterior)return;
  var life=document.getElementById('house-life'),lifeHome=life.parentNode;
  var hints=document.getElementById('house-hints'),photo=document.getElementById('exterior-photo'),pictures=document.getElementById('exterior-pictures');
  var status=document.getElementById('exterior-status'),outside=document.getElementById('hybrid-outside'),walk=document.getElementById('hybrid-walkthrough');
  var mode='exterior',visiting='living',journey=0,ready=false,opening=false,studyRemember=true;
  var reduced=matchMedia('(prefers-reduced-motion: reduce)');
  var rooms={
    living:{label:'Living room',id:'hybrid-room',marker:'exterior-room-marker',shortcut:'exterior-enter',icons:'#hybrid-hotspots [data-card]>svg',anchor:[.35,.65],links:[['kitchen',.90,.72],['study',.10,.72]]},
    kitchen:{label:'Kitchen',id:'hybrid-kitchen',marker:'exterior-kitchen-marker',shortcut:'exterior-kitchen-enter',icons:'#kitchen-hotspots [data-card]>svg',anchor:[.51,.48],links:[['living',.12,.65],['mudroom',.30,.80]]},
    mudroom:{label:'Mudroom',id:'hybrid-mudroom',marker:'exterior-mudroom-marker',shortcut:'exterior-mudroom-enter',icons:'#mudroom-hotspots [data-card]>svg',anchor:[.53,.64],links:[['kitchen',.88,.67],['garage',.12,.72]]},
    garage:{label:'Garage',id:'hybrid-garage',marker:'exterior-garage-marker',anchor:[.79,.63],links:[['mudroom',.88,.70]]},
    study:{label:'Study',id:'hybrid-study',marker:'exterior-study-marker',shortcut:'exterior-study-enter',icons:'#study-hotspots [data-card=board]>svg',anchor:[.23,.48],links:[['living',.13,.67]]}
  };
  Object.keys(rooms).forEach(function(key){
    var r=rooms[key];r.el=document.getElementById(r.id);
    var b=document.createElement('button');b.id=r.marker;b.type='button';b.className='house-hint crowded';b.dataset.room=key;
    b.setAttribute('aria-label','Expand '+r.label);b.setAttribute('aria-expanded','false');
    var icons=document.createElement('div');icons.className='house-hint-icons';
    if(r.icons)document.querySelectorAll(r.icons).forEach(svg=>icons.appendChild(svg.cloneNode(true)));
    else icons.innerHTML='<svg viewBox="0 0 24 24"><path d="m5 11 2-5h10l2 5M4 11h16v7H4zM7 14h2m6 0h2M6 18v3m12-3v3"/></svg><svg viewBox="0 0 24 24"><path d="M5 7h14l1 14H4L5 7zm3 0V5a4 4 0 0 1 8 0v2"/></svg>';
    b.appendChild(icons);var label=document.createElement('span');label.className='house-hint-label';label.textContent=r.label;b.appendChild(label);hints.appendChild(b);r.button=b;
    function activate(e){e.stopPropagation();if(mode!=='exterior')return;if(window.ChauffeurMarkers.expand(b,key))return;enter(true,null,key);}
    b.addEventListener('click',activate);if(r.shortcut)document.getElementById(r.shortcut).addEventListener('click',activate);
  });
  function urlFor(target){var u=new URL(location.href);u.searchParams.delete('angle');if(rooms[target])u.searchParams.set('scene',target);else u.searchParams.delete('scene');return u.href;}
  function roomState(from){var s=Object.assign({},history.state,{chfExteriorRoom:true,chfFromRoom:from});['chfKitchenView','chfHybridView','chfUtilityView'].forEach(k=>delete s[k]);return s;}
  function placeMarker(){
    if(!photo.naturalWidth||Object.values(rooms).some(r=>r.button.classList.contains('expanded')))return;
    var scale=Math.max(innerWidth/photo.naturalWidth,innerHeight/photo.naturalHeight);
    Object.values(rooms).forEach(function(r,i){
      var x=r.anchor[0]*photo.naturalWidth*scale+(innerWidth-photo.naturalWidth*scale)/2,y=r.anchor[1]*photo.naturalHeight*scale+innerHeight-photo.naturalHeight*scale;
      if(innerWidth<701){x=innerWidth*[.23,.73,.50,.77,.22][i];y=innerHeight*[.43,.43,.57,.60,.60][i];}
      r.button.style.left=Math.max(65,Math.min(innerWidth-65,x))+'px';r.button.style.top=Math.max(240,Math.min(innerHeight-(innerWidth<701?285:210),y))+'px';
    });
  }
  function drawWalk(){
    walk.replaceChildren();walk.hidden=!rooms[mode];if(!rooms[mode])return;
    ['left','right'].forEach(function(side){
      var group=document.createElement('div');group.className='walk-side';group.dataset.side=side;
      rooms[mode].links.filter(link=>(link[1]<.5?'left':'right')===side).forEach(function(link){
        var b=document.createElement('button');b.type='button';b.dataset.room=link[0];b.dataset.side=side;b.setAttribute('aria-label','Go to '+rooms[link[0]].label);
        b.innerHTML='<span class="walk-ring" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m15 5-7 7 7 7"/></svg></span><span>'+rooms[link[0]].label+'</span>';
        b.addEventListener('click',()=>enter(true,null,link[0]));group.appendChild(b);
      });
      if(group.children.length)walk.appendChild(group);
    });
  }
  function resetCurrent(){window.chfKitchenReset?.();window.chfGarageReset?.();window.chfUtilityRooms?.reset();window.chfHybridReset?.();window.dispatchEvent(new CustomEvent('chf-house-close'));}
  function setMode(next){
    mode=next;document.body.dataset.houseScene=next;hints.hidden=next!=='exterior';exterior.inert=next!=='exterior';exterior.setAttribute('aria-hidden',String(next!=='exterior'));
    var destination=next==='living'?lifeHome:next==='kitchen'?document.getElementById('kitchen-controls'):next==='mudroom'?document.getElementById('mudroom-controls'):document.getElementById('exterior-quickviews');
    if(life.parentNode!==destination){var move=()=>destination.appendChild(life);if(window.Alpine)Alpine.mutateDom(move);else move();}
    Object.keys(rooms).forEach(function(key){var el=rooms[key].el;el.hidden=next!==key&&!(next==='entering'&&visiting===key);el.inert=next!==key;el.setAttribute('aria-hidden',String(next!==key));});
    if(next==='kitchen')window.chfKitchenSurfaces?.refresh();outside.hidden=!rooms[next];drawWalk();window.dispatchEvent(new CustomEvent('chf-hybrid-room',{detail:next}));
  }
  function waitRoom(){return new Promise(function(resolve,reject){var start=performance.now();function check(){var img=document.querySelector('#hybrid-overview img.is-active');if(img?.complete&&img.naturalWidth)return resolve();if(performance.now()-start>15000)return reject(new Error('Room unavailable'));setTimeout(check,50);}check();});}
  function disable(value){Object.values(rooms).forEach(r=>r.button.disabled=value);walk.querySelectorAll('button').forEach(b=>b.disabled=value);}
  async function enter(remember,feature,target){
    target=rooms[target]?target:'living';if(opening||mode===target)return;
    if(target==='study'&&!window.chfHouseParent?.()){
      studyRemember=remember;await Alpine.$data(life).study();
      if(mode!=='study'&&!opening&&new URL(location.href).searchParams.get('scene')==='study')history.replaceState(mode==='exterior'?{}:roomState(history.state?.chfFromRoom),'',urlFor(mode));
      return;
    }
    opening=true;visiting=target;var previous=mode,ticket=++journey;disable(true);status.textContent='Opening the '+rooms[target].label.toLowerCase()+'…';
    try{
      if(target==='garage')await window.chfGarageReady();else if(target==='kitchen')await window.chfKitchenReady();else if(target==='mudroom'||target==='study')await window.chfUtilityRooms.ready(target);else await waitRoom();
      if(ticket!==journey)return;
      window.ChauffeurMarkers.collapse();resetCurrent();if(previous==='study'&&target!=='study')window.chfUtilityRooms.lock();
      if(remember)history.pushState(roomState(previous),'',urlFor(target));
      else history.replaceState(new URL(location.href).searchParams.get('scene')===target?Object.assign({},history.state,{chfExteriorRoom:true}):roomState(previous),'',urlFor(target));
      if(previous==='exterior'){pictures.style.setProperty('--entry-x',rooms[target].button.style.left);pictures.style.setProperty('--entry-y',rooms[target].button.style.top);setMode('entering');await new Promise(resolve=>setTimeout(resolve,reduced.matches?0:700));if(ticket!==journey)return;}
      exterior.hidden=true;setMode(target);outside.focus();
      if(target==='living'&&feature)window.chfHybridVisit(feature);
      if(target==='kitchen'&&(feature||history.state?.chfKitchenView))window.chfKitchenVisit(feature||history.state.chfKitchenView,!!feature);
      if((target==='mudroom'||target==='study')&&(feature||history.state?.chfUtilityView))window.chfUtilityRooms.visit(feature||history.state.chfUtilityView,!!feature);
      if(target==='garage'&&feature==='errands')window.dispatchEvent(new CustomEvent('chf-house-open',{detail:'errands'}));
    }catch(error){if(ticket===journey){status.textContent='The room could not load. Please try again.';if(previous!=='exterior')window.showGlobalAlert?.('The room could not load. Please try again.');}}
    finally{if(ticket===journey){opening=false;disable(false);}}
  }
  function revealOutside(){++journey;opening=false;resetCurrent();if(mode==='study')window.chfUtilityRooms.lock();exterior.hidden=false;setMode('exterior');disable(false);status.textContent='Tap a room to explore';placeMarker();rooms[visiting].button.focus();}
  function goOutside(){
    if(mode==='garage'&&window.chfGarageBack?.())return;if(mode==='kitchen'&&window.chfKitchenBack?.())return;if(window.chfUtilityRooms?.back())return;
    if(!rooms[mode]||(mode==='living'&&window.chfHybridViewing?.()))return;
    if(history.state?.chfExteriorRoom&&history.state?.chfFromRoom==='exterior')history.back();else{history.pushState({},'',urlFor('exterior'));revealOutside();}
  }
  window.chfHybridHome=function(){history.replaceState({},'',urlFor('exterior'));revealOutside();return true;};
  window.chfHybridGo=(target,remember)=>enter(remember!==false,null,target);
  window.chfHouseUnlockStudy=()=>enter(studyRemember,null,'study');
  window.chfHouseVisit=function(zone,target){enter(true,target==='living'?({radio:'music',pet:'pets',tasks:'tasks',programs:'programs'}[zone]):zone,target);};
  outside.addEventListener('click',goOutside);
  document.addEventListener('keydown',function(e){
    if(!document.getElementById('cc-input-modal')?.classList.contains('hidden')){if(e.key==='Escape'){e.preventDefault();document.getElementById('cc-input-cancel-btn').click();}return;}
    if(e.defaultPrevented||document.body.classList.contains('house-card-open')||e.target.closest('input,textarea,select,[contenteditable="true"]'))return;
    if(rooms[mode]&&e.key==='Escape'){e.preventDefault();goOutside();}
  });
  window.addEventListener('popstate',function(){
    if(opening){++journey;opening=false;disable(false);if(visiting==='study')window.chfUtilityRooms.lock();}
    var target=new URL(location.href).searchParams.get('scene');
    if(history.state?.chfExteriorRoom&&rooms[target]){if(mode!==target)enter(false,null,target);}
    else if(mode!=='exterior')revealOutside();
  });
  window.addEventListener('resize',function(){placeMarker();drawWalk();});window.chfHouseMode=()=>mode;window.chfExteriorProbe=()=>({mode:mode,ready:ready});
  photo.onload=function(){ready=true;window.ChauffeurHome?.ready();photo.classList.add('is-active');placeMarker();exterior.setAttribute('aria-busy','false');status.textContent='Tap a room to explore';window.dispatchEvent(new Event('chf-exterior-ready'));};
  photo.onerror=function(){exterior.setAttribute('aria-busy','false');status.textContent='Exterior image unavailable. Use a room shortcut to continue.';};
  var initial=new URL(location.href).searchParams.get('scene');setMode('exterior');photo.src=photo.dataset.src;
  function initialEntry(){if(rooms[initial]){if(history.state?.chfExteriorRoom)enter(false,null,initial);else{history.replaceState({},'',urlFor('exterior'));enter(true,null,initial);}}else history.replaceState({},'',urlFor('exterior'));}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialEntry);else initialEntry();
})();
