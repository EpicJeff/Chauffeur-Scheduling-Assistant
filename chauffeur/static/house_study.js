/* The approved Study scene, fitted into the house's east room. The furniture
   is built by study.js; this adapter supplies house-scale architecture and
   the same room/zone contracts used by every other house object. */
(function () {
  'use strict';
  window.HouseStudy = { build: function (T, detail, renderer) {
    if (!window.StudyFactory) return null;
    var quality = detail >= 3 ? 'high' : detail >= 2 ? 'medium' : 'low';
    // STUDY REFIT (2026-09-16): the house's study has an EXTERIOR east
    // wall (the main block's own side elevation, already carrying a pane
    // at z 11.10) and an INTERIOR north wall shared with the east room.
    // A window on the north wall looked into another room; the shelves
    // and the evidence board were on the only wall that could hold a
    // window. So the factory turns them: window east, shelf wall north.
    // The standalone /study page keeps the authored north window.
    var built = window.StudyFactory({THREE:T, quality:quality, renderer:renderer,
                                     windowWall:'east'});
    var root = built.group, zones = {}, proxies = new T.Group();
    var SCALE = .42, EAST = 14.52, NORTH = 7.71, SOUTH = 14.45, WEST = 6.92;
    /* EFACE: what the room's east wall actually IS, as opposed to where
       this module nominally ends. house.js's `east_wall` slab presents
       its inner plaster face at x 14.30 and is SOLID from the study --
       the study owns it, so no cutaway ever takes it away -- which means
       everything the study hangs on this wall has to stand in front of
       14.30 or it is buried inside a wall slab.

       Until this refit nothing did. The room was placed off its nominal
       EAST (14.52), so the study's own east wall plane landed at 14.44
       and the wainscot, the base, the chair rail, the wall calendar, the
       clock and the evidence board were all built east of the slab's
       face: none of them has been visible from inside this room since
       the study moved into the main block. (Look at the east wall in any
       study shot before v2.499.42 -- bare plaster, no sage band, no
       rail, where the north wall carries all three.) Moving the window
       onto this wall is what made it impossible to leave alone.

       So the room is placed by its WALLS now. EFACE is the slab's own
       inner face, and the study scene's east wall plane (local z =
       -6.10) lands EGAP clear of it: 0.12, the clearance the deepest
       thing on this wall needs, which is the window sill -- it reaches
       .088 behind its own plane, because in the room this scene was
       authored for the wall behind it is .05 thick with nothing beyond.
       NFACE is the same idea on the north: that wall box is built BEHIND
       its own face rather than centred on it, so the face is the floor's
       own north edge and everything the room hangs there -- the wall
       map, and now the whole turned shelf wall -- stands in front of
       it. */
    var EFACE = 14.30, EGAP = .12, NFACE = NORTH;
    root.rotation.y = -Math.PI / 2;
    root.scale.setScalar(SCALE);
    root.position.set(EFACE - EGAP - 6.10 * SCALE, .12, NORTH + 7.09 * SCALE);
    root.userData.room = 'study';
    built.shell.visible = false;

    var lights = [];
    root.traverse(function (o) { if (o.isLight) lights.push(o); });
    lights.forEach(function (o) { if (o.parent) o.parent.remove(o); });
    (built.zones.keys.meshes || []).forEach(function (m) { m.visible = false; });

    // The house chair rail is higher than the standalone Study's. Lift the
    // entire evidence-board assembly together so no frame, pin, or string
    // crosses the moulding after the scene is scaled into this room.
    //
    // STUDY REFIT: study.js hands the assembly over as one tagged group
    // now -- the corkboard, its four decorative rails and all fourteen
    // pin groups, gathered where they are built. This used to pick them
    // out of the scene by where they happened to sit (a z on the east
    // wall, plus an x/y envelope), which after the turn would have
    // selected nothing at all and left the board crossing the moulding.
    var boardG = null;
    root.children.forEach(function (o) {
      if (o.userData && o.userData.studyGroup === 'board') boardG = o;
    });
    if (boardG) boardG.position.y += .72 / SCALE;

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
    // STUDY REFIT: the window turned onto the EAST wall, so the wall
    // finish turned with it. The NORTH wall is one solid run now -- it
    // is the interior wall shared with the east room, and it carries the
    // shelves, the library and the board -- and the EAST wall's sage
    // band and chair rail split around the window, because the glass
    // reaches below the rail. Both are built at EFACE, on the room side
    // of the house's own slab, where they can be seen.
    //
    // There is no wall box to cut a hole in on the east: the slab behind
    // (house.js `east_wall`) IS this wall, and the window's own sky
    // plane covers the glass against it, exactly the way the wall
    // calendar and the clock cover their own patch of it. `east` below
    // stays where it always was, inside the slab -- a belt-and-braces
    // enclosure that costs one box and is never seen.
    //
    // The window is read back off the study itself (built.windowAt is
    // study.js's own window centre AFTER its turn, in study units), so
    // this adapter and that scene cannot drift apart. wz lands on world
    // z 11.10, which is where the house's exterior pane on this
    // elevation already is.
    var wc=built.windowAt||{x:.98},ws=built.windowSize||{w:4.8};
    var wz=root.position.z+wc.x*SCALE,ww=ws.w*SCALE;
    var northW=wz-ww/2-NORTH,southW=SOUTH-(wz+ww/2);
    box('north',EAST-WEST,4.45,.12,wall,(WEST+EAST)/2,2.225,NFACE-.06,.94);
    box('east',.12,4.45,SOUTH-NORTH,wall,EAST,2.225,(NORTH+SOUTH)/2,.94);
    box('north-wainscot',EAST-WEST,1.55,.05,sage,(WEST+EAST)/2,.83,NFACE+.025,.9);
    box('east-wainscot-north',.05,1.55,northW,sage,EFACE-.025,.83,NORTH+northW/2,.9);
    box('east-wainscot-south',.05,1.55,southW,sage,EFACE-.025,.83,wz+ww/2+southW/2,.9);
    box('north-base',EAST-WEST,.13,.18,trim,(WEST+EAST)/2,.16,NFACE+.09,.8);
    box('east-base',.18,.13,SOUTH-NORTH,trim,EFACE-.09,.16,(NORTH+SOUTH)/2,.8);
    box('north-rail',EAST-WEST,.11,.17,trim,(WEST+EAST)/2,1.62,NFACE+.085,.8);
    box('east-rail-north',.17,.11,northW,trim,EFACE-.085,1.62,NORTH+northW/2,.8);
    box('east-rail-south',.17,.11,southW,trim,EFACE-.085,1.62,wz+ww/2+southW/2,.8);

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
