/* Exterior shortcuts: tap previews; a deliberate hold visits the object. */
(function () {
  'use strict';
  var rooms = {
    kitchen: [['Moments','moments','fridge'],['Meals','meals','counter'],['Groceries','lists','pantry'],['Calendar','calendar','calendar'],['Weather','weather','window']],
    living: [['Music','music','radio'],['Critters','pets','pet'],['Tasks','tasks','tasks'],['Programs','programs','programs']],
    mudroom: [['Next up','schedule','door'],['Chores','chores','chores'],['Routines','routines','routines']],
    garage: [['Cars','cars','garage'],['Errands','errands','errands']],
    study: [['Study · Parent PIN','study_preview','study']]
  };
  var active = null, fan = null, cancelHold = null;
  function collapse() {
    if (!active) return false;
    if (cancelHold) cancelHold();
    active.classList.remove('expanded'); active.setAttribute('aria-expanded','false');
    active.setAttribute('aria-label',active.dataset.restLabel);
    active.style.left = active.dataset.restX; active.style.top = active.dataset.restY;
    active = null; if (fan) fan.remove(); fan = null;
    return true;
  }
  function expand(marker, room) {
    if (marker === active) { collapse(); return false; }
    collapse(); active = marker;
    marker.dataset.restX = marker.style.left; marker.dataset.restY = marker.style.top;
    marker.dataset.restLabel = marker.getAttribute('aria-label');
    var r = marker.getBoundingClientRect(), radius = Math.min(112,(innerWidth-110)/2);
    var cx = Math.max(radius+52,Math.min(innerWidth-radius-52,r.left+r.width/2));
    var top = radius+115, bottom = innerHeight-radius-150;
    if (innerWidth < 600) document.querySelectorAll('#house-glance:not([hidden]) .glance-clock, #house-glance:not([hidden]) .glance-next:not([hidden])').forEach(function(card){
      top = Math.max(top,card.getBoundingClientRect().bottom+radius+48);
    });
    var cy = Math.min(bottom,Math.max(top,r.top+r.height/2));
    marker.style.left = cx+'px'; marker.style.top = cy+'px';
    marker.classList.add('expanded'); marker.setAttribute('aria-expanded','true');
    marker.setAttribute('aria-label','Enter '+marker.dataset.restLabel.replace(/^Expand /,''));
    fan = document.createElement('div'); fan.className = 'house-marker-fan';
    fan.setAttribute('role','group'); fan.setAttribute('aria-label',room+' quick views');
    var entries = rooms[room], icons = marker.querySelectorAll('.house-hint-icons svg');
    entries.forEach(function (entry,i) {
      var angle = -Math.PI/2 + i*2*Math.PI/entries.length;
      var button = document.createElement('button'); button.type = 'button';
      button.className = 'house-marker-feature'; button.dataset.preview = entry[1];
      button.setAttribute('aria-label',entry[0]+': preview. Hold or Shift+Enter to visit.');
      button.style.left = (cx+Math.cos(angle)*radius)+'px';
      button.style.top = (cy+Math.sin(angle)*radius)+'px';
      var face = document.createElement('span'); face.className = 'house-marker-face';
      if (icons[i]) face.appendChild(icons[i].cloneNode(true));
      face.insertAdjacentHTML('beforeend','<svg class="house-hold-ring" viewBox="0 0 60 60" aria-hidden="true"><circle cx="30" cy="30" r="27" pathLength="100"/></svg>');
      var label = document.createElement('span'); label.className = 'house-feature-label'; label.textContent = entry[0];
      button.appendChild(face); button.appendChild(label); fan.appendChild(button);
      var timer = null, pointer = null, x = 0, y = 0, suppress = false;
      function cancel() { clearTimeout(timer); timer = null; pointer = null; button.classList.remove('holding'); }
      function visit() { suppress = true; cancel(); collapse(); window.chfHouseVisit(entry[2],room); }
      button.addEventListener('pointerdown',function(e) {
        if (!e.isPrimary || e.button !== 0) return;
        suppress = false; pointer = e.pointerId; x=e.clientX; y=e.clientY;
        button.setPointerCapture(pointer); button.classList.add('holding'); cancelHold = cancel;
        timer = setTimeout(visit,500);
      });
      button.addEventListener('pointermove',function(e) {
        if (pointer === e.pointerId && Math.hypot(e.clientX-x,e.clientY-y)>10) { suppress=true; cancel(); }
      });
      button.addEventListener('pointerup',cancel);
      button.addEventListener('pointercancel',function(){suppress=true;cancel();});
      button.addEventListener('lostpointercapture',cancel);
      button.addEventListener('contextmenu',function(e){e.preventDefault();});
      button.addEventListener('keydown',function(e){
        if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); visit(); }
      });
      button.addEventListener('click',function(e){
        e.stopPropagation(); if(suppress){suppress=false;return;}
        window.dispatchEvent(new CustomEvent('chf-house-open',{detail:entry[1]}));
      });
    });
    var help = document.createElement('p'); help.className='house-marker-help';
    help.textContent='Tap to preview · Hold to visit';
    help.style.left=cx+'px'; help.style.top=(cy+radius+55)+'px'; fan.appendChild(help);
    document.getElementById('house-hints').appendChild(fan);
    return true;
  }
  document.addEventListener('click',function(e){
    if (!active || active.contains(e.target) || fan.contains(e.target) || document.body.classList.contains('house-card-open')) return;
    collapse();
    if(e.target.tagName==='CANVAS'){e.preventDefault();e.stopPropagation();}
  },true);
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape' && !document.body.classList.contains('house-card-open') && active){var button=active;collapse();button.focus();e.stopPropagation();}
  },true);
  window.addEventListener('resize',collapse);
  window.addEventListener('blur',function(){if(cancelHold)cancelHold();});
  document.addEventListener('visibilitychange',function(){if(document.hidden && cancelHold)cancelHold();});
  window.ChauffeurMarkers = {expand:expand,collapse:collapse};
})();
