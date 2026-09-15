/* The approved Study scene, fitted into the house's east room. The furniture
   is built by study.js; this adapter supplies house-scale architecture and
   the same room/zone contracts used by every other house object. */
(function () {
  'use strict';
  window.HouseStudy = { build: function (T, detail, renderer) {
    if (!window.StudyFactory) return null;
    var quality = detail >= 3 ? 'high' : detail >= 2 ? 'medium' : 'low';
    var built = window.StudyFactory({THREE:T, quality:quality, renderer:renderer});
    var root = built.group, zones = {}, proxies = new T.Group();
    var SCALE = .42, EAST = 14.52, NORTH = 9.88, SOUTH = 16.62, WEST = 6.92;
    root.rotation.y = -Math.PI / 2;
    root.scale.setScalar(SCALE);
    root.position.set(EAST - 6.3 * SCALE, .12, NORTH + 7.09 * SCALE);
    root.userData.room = 'study';
    built.shell.visible = false;

    var lights = [];
    root.traverse(function (o) { if (o.isLight) lights.push(o); });
    lights.forEach(function (o) { if (o.parent) o.parent.remove(o); });
    (built.zones.keys.meshes || []).forEach(function (m) { m.visible = false; });

    // The house chair rail is higher than the standalone Study's. Lift the
    // entire evidence-board assembly together so no frame, pin, or string
    // crosses the moulding after the scene is scaled into this room.
    var boardParts = new Set();
    (built.zones.board.meshes || []).forEach(function (m) {
      var p = m;
      while (p.parent && p.parent !== root) p = p.parent;
      if (p.parent === root) boardParts.add(p);
    });
    // The authored frame rails are intentionally decorative and therefore
    // are not zone meshes. Include every root-level part inside the board's
    // authored envelope so the face, frame, pins, and notes move as one.
    root.children.forEach(function (o) {
      var p = o.position;
      if (o !== built.shell && p.z < -5.75 && p.x > -2.6 && p.x < 3.6 &&
          p.y > 2.55 && p.y < 6.65) boardParts.add(o);
    });
    boardParts.forEach(function (o) { o.position.y += .72 / SCALE; });

    var zoneMaterials = new Map();
    root.updateMatrixWorld(true);
    Object.keys(built.zones).forEach(function (name) {
      if (name === 'keys') return;
      var key = 'study_' + name, z = built.zones[name];
      z.meshes.forEach(function (m) {
        m.userData.zone = key; m.userData.room = 'study';
        if (!m.material || Array.isArray(m.material)) return;
        var mk = key + '|' + m.material.uuid;
        if (!zoneMaterials.has(mk)) zoneMaterials.set(mk, m.material.clone());
        m.material = zoneMaterials.get(mk);
      });
      var b = new T.Box3();
      z.meshes.forEach(function (m) { b.expandByObject(m); });
      var g = new T.Group(); g.userData.zone = key; g.userData.room = 'study';
      if (!b.isEmpty()) {
        var c = b.getCenter(new T.Vector3()), s = b.getSize(new T.Vector3());
        var marker = new T.Mesh(new T.BoxGeometry(Math.max(s.x,.05),Math.max(s.y,.05),Math.max(s.z,.05)),
          new T.MeshBasicMaterial({transparent:true,opacity:0,depthWrite:false,colorWrite:false}));
        marker.position.copy(c); marker.raycast = function () {};
        g.add(marker);
      }
      proxies.add(g); zones[key] = g;
    });
    proxies.userData.room = 'study';

    var arch = new T.Group(); arch.userData.room = 'study';
    var geometries = new Map(), materials = new Map();
    function geo(k,w,h,d){if(!geometries.has(k))geometries.set(k,new T.BoxGeometry(w,h,d));return geometries.get(k);}
    function material(k,c,rough){
      if(!materials.has(k))materials.set(k,detail>=3
        ?new T.MeshStandardMaterial({color:c,roughness:rough,metalness:0})
        :new T.MeshLambertMaterial({color:c}));
      return materials.get(k);
    }
    function box(k,w,h,d,c,x,y,z,rough){
      var m=new T.Mesh(geo(k+'|'+w+'|'+h+'|'+d,w,h,d),material(k,c,rough == null ? .88 : rough));
      m.position.set(x,y,z);m.receiveShadow=detail>=3;m.castShadow=detail>=3;arch.add(m);return m;
    }
    var wall=0xd8d0c2,trim=0xeee7da,sage=0x71877d,floor=0xa9784d;
    box('floor',EAST-WEST,.10,SOUTH-NORTH,floor,(WEST+EAST)/2,.05,(NORTH+SOUTH)/2,.82);
    for(var p=0;p<8;p++)box('joint',EAST-WEST-.12,.018,.025,0x65452f,(WEST+EAST)/2,.105,NORTH+.43+p*.80,.9);
    var wx=root.position.x-.20*SCALE,ww=4.8*SCALE,wy=.12+4.35*SCALE,wh=3.2*SCALE;
    var leftW=wx-ww/2-WEST,rightW=EAST-(wx+ww/2);
    box('north-left',leftW+.06,4.45,.12,wall,WEST+(leftW+.06)/2,2.225,NORTH,.94);
    box('north-right',rightW+.06,4.45,.12,wall,wx+ww/2+(rightW+.06)/2-.06,2.225,NORTH,.94);
    box('north-low',ww-.04,wy-wh/2,.12,wall,wx,(wy-wh/2)/2,NORTH,.94);
    box('north-high',ww-.04,4.45-(wy+wh/2),.12,wall,wx,(4.45+wy+wh/2)/2,NORTH,.94);
    box('east',.12,4.45,SOUTH-NORTH,wall,EAST,2.225,(NORTH+SOUTH)/2,.94);
    box('north-wainscot-left',leftW,1.55,.05,sage,WEST+leftW/2,.83,NORTH+.08,.9);
    box('north-wainscot-right',rightW,1.55,.05,sage,wx+ww/2+rightW/2,.83,NORTH+.08,.9);
    box('east-wainscot',.05,1.55,SOUTH-NORTH,sage,EAST-.08,.83,(NORTH+SOUTH)/2,.9);
    box('north-base',EAST-WEST,.13,.18,trim,(WEST+EAST)/2,.16,NORTH+.10,.8);
    box('east-base',.18,.13,SOUTH-NORTH,trim,EAST-.10,.16,(NORTH+SOUTH)/2,.8);
    box('north-rail-left',leftW,.11,.17,trim,WEST+leftW/2,1.62,NORTH+.09,.8);
    box('north-rail-right',rightW,.11,.17,trim,wx+ww/2+rightW/2,1.62,NORTH+.09,.8);
    box('east-rail',.17,.11,SOUTH-NORTH,trim,EAST-.09,1.62,(NORTH+SOUTH)/2,.8);

    function count(f,key){
      f=f||{};var gauges=f.gauges||{};
      if(key==='study_board')return((f.board||{}).pins||[]).length;
      if(key==='study_desk')return(f.desk||[]).reduce(function(n,d){return n+(d.open_steps||0);},0);
      if(key==='study_tray')return(f.tray||{}).count||0;
      if(key==='study_stickies')return(f.stickies||{}).count||0;
      if(key==='study_calendar')return((f.calendar||{}).days||[]).reduce(function(n,d){return n+(d.unassigned||0);},0);
      if(key==='study_window')return((f.window||{}).worse||[]).length;
      if(key==='study_contracts')return(f.contracts||{}).count||0;
      if(key==='study_binders')return(f.binders||[]).filter(function(b){return b.pulled;}).length;
      if(key==='study_gauges'){var n=gauges.ingest_errors||0;if(gauges.think_cap&&gauges.think>=gauges.think_cap)n++;if(gauges.research_cap&&gauges.research>=gauges.research_cap)n++;return n;}
      if(key==='study_monitor')return((f.monitor||{}).clusters||[]).length;
      if(key==='study_map')return((f.map||{}).trips||[]).filter(function(t){return t.upcoming;}).length;
      return 0;
    }
    function update(f){built.update(f||{});(built.zones.keys.meshes||[]).forEach(function(m){m.visible=false;});}
    return{group:root,architecture:arch,proxies:proxies,zones:zones,count:count,update:update,dispose:function(){
      var gs=new Set(),ms=new Set(),ts=new Set();
      [root,arch,proxies].forEach(function(top){top.traverse(function(o){if(o.geometry)gs.add(o.geometry);var a=Array.isArray(o.material)?o.material:[o.material];a.forEach(function(m){if(!m)return;ms.add(m);if(m.map)ts.add(m.map);});});});
      ts.forEach(function(t){t.dispose();});ms.forEach(function(m){m.dispose();});gs.forEach(function(g){g.dispose();});
    }};
  }};
})();
