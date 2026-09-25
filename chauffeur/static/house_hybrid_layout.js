/* Keep overview controls apart after image cropping, resizing and live badges. */
(function () {
  'use strict';
  var movable = '.hybrid-marker,#hybrid-outside,#study-lock,' +
    '#hybrid-shortcuts,#kitchen-shortcuts,.utility-shortcuts,.garage-controls,#panel-chat-orb,#house-comparison';
  var fixed = '#top-nav-bar,#chat-overlay-container,#panel-shelf,#hybrid-walkthrough button';
  var pending = 0, gap = 8, margin = 8;
  function visible(el) {
    return el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true});
  }
  function bounds(el) {
    var overflow = el.matches('.hybrid-marker') ? '.hybrid-marker-label,.hybrid-count' :
      el.id === 'house-comparison' ? '.house-fire-toggle,.house-steam-toggle' : null;
    var parts = [el].concat(overflow ? Array.from(el.querySelectorAll(overflow)).filter(visible) : []);
    var rects = parts.map(function (part) { return part.getBoundingClientRect(); });
    return {left:Math.min(...rects.map(r=>r.left)), top:Math.min(...rects.map(r=>r.top)),
      right:Math.max(...rects.map(r=>r.right)), bottom:Math.max(...rects.map(r=>r.bottom))};
  }
  function overlaps(a,b) {
    return a.left < b.right + gap && a.right + gap > b.left &&
      a.top < b.bottom + gap && a.bottom + gap > b.top;
  }
  function layout() {
    pending = 0;
    document.querySelectorAll(movable).forEach(el=>el.style.translate='none');
    var scene = document.body.dataset.houseScene || 'living';
    var frame = document.getElementById(scene === 'living' ? 'hybrid-room-frame' : 'hybrid-' + scene);
    if (!frame || (scene === 'garage' ? frame.dataset.view === 'dashboard' :
      (scene === 'living' ? frame.dataset.phase : frame.dataset.view) !== 'room')) return;
    var controls = Array.from(document.querySelectorAll(movable)).filter(visible);
    // Room navigation stays at the screen edges; other controls give way to it.
    function place(compact) {
    controls.forEach(el=>el.style.translate='none');
    if(compact)controls.sort(function(a,b){var x=bounds(a),y=bounds(b);return (y.right-y.left)*(y.bottom-y.top)-(x.right-x.left)*(x.bottom-x.top);});
    var occupied = Array.from(document.querySelectorAll(fixed)).filter(visible).map(bounds), fitted=true;
    controls.forEach(function (el) {
      var start = bounds(el), width = start.right-start.left, height = start.bottom-start.top;
      var maxX = innerWidth-margin-width, maxY = innerHeight-margin-height;
      var clampX = x=>Math.max(margin,Math.min(maxX,x));
      var clampY = y=>Math.max(margin,Math.min(maxY,y));
      var xs = [clampX(start.left),margin,maxX], ys = [clampY(start.top),margin,maxY];
      occupied.forEach(function (r) {
        xs.push(clampX(r.left-gap-width),clampX(r.right+gap));
        ys.push(clampY(r.top-gap-height),clampY(r.bottom+gap));
      });
      var best = null, distance = Infinity;
      new Set(xs).forEach(function (x) { new Set(ys).forEach(function (y) {
        var r = {left:x,top:y,right:x+width,bottom:y+height};
        var d = compact ? y*innerWidth+x : (x-start.left)**2+(y-start.top)**2;
        if (d < distance && !occupied.some(other=>overlaps(r,other))) { best=r; distance=d; }
      }); });
      if (best) {
        el.style.translate=(best.left-start.left)+'px '+(best.top-start.top)+'px';
        occupied.push(best);
      } else { fitted=false; occupied.push(start); }
    });
    return fitted;
    }
    // At very small sizes, re-pack whole control groups instead of preserving
    // their preferred positions at the cost of covering another control.
    if(!place(false))place(true);
  }
  function schedule() { if (!pending) pending=requestAnimationFrame(layout); }
  window.addEventListener('resize',schedule);
  window.addEventListener('chf-hybrid-room',schedule);
  document.addEventListener('transitionend',function(event){
    if(event.propertyName==='opacity'||event.propertyName==='transform')schedule();
  });
  document.fonts.ready.then(schedule);
  // Ignore style mutations made by layout itself. Watch view switches, badge
  // text/counts and rebuilt navigation, including returns from object views.
  var observer = new MutationObserver(schedule);
  ['hybrid-room','hybrid-kitchen','hybrid-mudroom','hybrid-study','hybrid-garage','hybrid-walkthrough','panel-chat-orb','chat-overlay-container','house-comparison'].forEach(function (id) {
    var el=document.getElementById(id);
    if(el)observer.observe(el,{subtree:true,childList:true,characterData:true,attributes:true,
      attributeFilter:['hidden','class','data-view','data-phase']});
  });
  var resize = new ResizeObserver(schedule);
  document.querySelectorAll(fixed).forEach(el=>resize.observe(el));
  schedule();
})();
