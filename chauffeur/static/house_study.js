/* The approved Study scene, fitted into the house's east room. The furniture
   is built by study.js; this adapter supplies house-scale architecture and
   the same room/zone contracts used by every other house object. */
(function () {
  'use strict';
  window.HouseStudy = { build: function (T, detail, renderer, ceiling) {
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

       So the room is placed by its WALLS now, and this room gets its OWN
       east wall (below) rather than borrowing the block's: a 0.12 box
       with its back on the slab's face, so what you see on both sides of
       this room is the study's own plaster and not the house's. EWF is
       that wall's room-facing side; EGAP is half its thickness, which is
       what puts the study scene's own east wall plane -- the plane the
       window, the calendar and the clock are hung on -- in the MIDDLE of
       the box, exactly where the north wall used to carry the window.
       NFACE is the mirror of EWF on the north: that box is built BEHIND
       its own face rather than centred on it (nothing is hung IN it any
       more, the window having left), so the face is the floor's own
       north edge and everything the room hangs there -- the wall map,
       and the whole turned shelf wall -- stands in front of it. */
    var EFACE = 14.30, EGAP = .06, NFACE = NORTH, EWF = EFACE - .12;
    root.rotation.y = -Math.PI / 2;
    root.scale.setScalar(SCALE);
    root.position.set(EFACE - EGAP - 6.10 * SCALE, .12, NORTH + 7.09 * SCALE);
    root.userData.room = 'study';
    built.shell.visible = false;

    var lights = [];
    root.traverse(function (o) { if (o.isLight) lights.push(o); });
    lights.forEach(function (o) { if (o.parent) o.parent.remove(o); });
    /* No car keys hang in the house's study -- this family's keys live in
       the garage and on the mudroom hooks. study.js hands the whole key
       wall over as ONE tagged group now: only its ZONE meshes used to be
       switched off, and the top rail, the four hooks and every key's own
       shaft and teeth are decoration rather than signal, so they are not
       in that list. They survived, invisible only because they were
       buried in the block's wall slab -- and the moment the room was
       placed clear of it they read as a stick with four rings floating
       beside the window. The group ends the whole class of bug: anything
       hung on that rail later is inside it. The zone meshes are switched
       off as well, here and on every update, so the hiding does not
       depend on the group alone. */
    var keysG = null;
    root.children.forEach(function (o) {
      if (o.userData && o.userData.studyGroup === 'keys') keysG = o;
    });
    if (keysG) keysG.visible = false;
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
    // STUDY REFIT: the window turned onto the EAST wall, so the wall it
    // is cut into turned with it. The NORTH wall is one solid run now --
    // it is the interior wall shared with the east room, and it carries
    // the shelves, the library and the board -- and the EAST wall is the
    // four boxes around the glass, with the sage band and the chair rail
    // splitting around it as well, because the glass reaches below the
    // rail.
    //
    // This room has its OWN east wall now (the four boxes below, at
    // EWF + .06). It used to have one too, but out at EAST, entirely
    // inside the block's `east_wall` slab: dead geometry, and what the
    // room actually showed on that side was the block's own plaster --
    // cream on the north wall, charcoal on the east. The pattern is the
    // north wall's, and it is the same both ways now.
    //
    // The window is read back off the study itself (built.windowAt is
    // study.js's own window centre AFTER its turn, in study units), so
    // this adapter and that scene cannot drift apart. wz lands on world
    // z 11.10, which is where the house's exterior pane on this
    // elevation already is; wy/wh are the sill and the glass height, the
    // same derivation the north wall used to carry.
    // VAULTED PARTITIONS (2026-09-16). User report: "In a real house
    // there would either be dropped ceilings with attic space above or
    // vaulted ceilings where the walls go all the way up. Assume vaulted
    // ceilings, so the walls should go all the way up."
    //
    // This room was authored 4.45 tall for a standalone page with its
    // own shell. In the house it has neither: the eave is 5.6 and the
    // main block's roof clears 8.5 over this room's north wall, so above
    // 4.45 the NORTH wall -- the interior one, shared with the east room
    // -- opened straight into that room's roof space, and the EAST wall
    // showed the block's own `east_wall` plaster (a different cream) for
    // its last 1.15.
    //
    // So the north wall rises to the deck and the east wall to the eave,
    // where the block's `east_wall` ends and `roof_main_end_east`'s
    // gable infill takes over. Both heights are the HOUSE's, handed in
    // by house.js off FULL_HOUSE and the same shellGable arithmetic the
    // roof itself is built from -- this file never re-derives them, so
    // it cannot drift from the roof. No ceiling (the standalone /study
    // page, which calls the factory directly) keeps the authored 4.45.
    var WALL_H=4.45;
    var NTOP=ceiling?ceiling.underside(NORTH):WALL_H;
    var ETOP=ceiling?ceiling.eave:WALL_H;
    var wc=built.windowAt||{x:.98,y:4.35},ws=built.windowSize||{w:4.8,h:3.2};
    var wz=root.position.z+wc.x*SCALE,ww=ws.w*SCALE;
    var wy=.12+wc.y*SCALE,wh=ws.h*SCALE,EW=EWF+.06;
    var northW=wz-ww/2-NORTH,southW=SOUTH-(wz+ww/2);
    box('north',EAST-WEST,NTOP,.12,wall,(WEST+EAST)/2,NTOP/2,NFACE-.06,.94);
    box('east-north',.12,ETOP,northW+.06,wall,EW,ETOP/2,NORTH+(northW+.06)/2,.94);
    box('east-south',.12,ETOP,southW+.06,wall,EW,ETOP/2,wz+ww/2+(southW+.06)/2-.06,.94);
    box('east-low',.12,wy-wh/2,ww-.04,wall,EW,(wy-wh/2)/2,wz,.94);
    box('east-high',.12,ETOP-(wy+wh/2),ww-.04,wall,EW,(ETOP+wy+wh/2)/2,wz,.94);
    box('north-wainscot',EAST-WEST,1.55,.05,sage,(WEST+EAST)/2,.83,NFACE+.025,.9);
    box('east-wainscot-north',.05,1.55,northW,sage,EWF-.025,.83,NORTH+northW/2,.9);
    box('east-wainscot-south',.05,1.55,southW,sage,EWF-.025,.83,wz+ww/2+southW/2,.9);
    box('north-base',EAST-WEST,.13,.18,trim,(WEST+EAST)/2,.16,NFACE+.09,.8);
    box('east-base',.18,.13,SOUTH-NORTH,trim,EWF-.09,.16,(NORTH+SOUTH)/2,.8);
    box('north-rail',EAST-WEST,.11,.17,trim,(WEST+EAST)/2,1.62,NFACE+.085,.8);
    box('east-rail-north',.17,.11,northW,trim,EWF-.085,1.62,NORTH+northW/2,.8);
    box('east-rail-south',.17,.11,southW,trim,EWF-.085,1.62,wz+ww/2+southW/2,.8);

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
    function update(f){built.update(f||{});(built.zones.keys.meshes||[]).forEach(function(m){m.visible=false;});
      // a zone being read when the payload moved owes a fresh paint
      if(shown)built.detail.paint(shown);}

    /* LEAN-IN CARDS (2026-09-22). What a study zone says when the house
       leans into it. Two surfaces, one law -- the kitchen's: a zone whose
       data is a LIST wears an HTML card on its face (the overlay draws it,
       textContent only, from the slice below), and while the card is up
       the room's own painted detail stays down, so the wall never says the
       same thing twice at two sizes. A zone whose signal IS its painted
       surface -- the monitor's cluster labels, the gauge readouts, the
       map's pin labels -- has no card and shows its paint instead. `card`
       is the single predicate both sides read: rows -> card; null -> paint.

       The rows carry the same words the room's own DETAIL paints and the
       /study fallback list prints (kind words, step counts, 'waiting',
       'awaiting answers'), read off study.js's normalised slice so a
       missing section is the calm form, never a throw. Everything here is
       plain data; the overlay owns the DOM. */
    var CARD = {
      board: function (d) {
        return (d.pins || []).map(function (p) {
          return {text: p.label || '', note: p.kind === 'insight' ? 'Argyle noticed' : 'Thread',
                  tone: p.bad ? 'bad' : (p.warn ? 'warn' : null)};
        });
      },
      desk: function (d) {
        return (d || []).map(function (p) {
          var n = p.open_steps | 0;
          return {text: p.line || '', tone: p.due ? 'warn' : null,
                  note: n + ' step' + (n === 1 ? '' : 's') + ' open' + (p.due ? ' · one due' : '')};
        });
      },
      tray: function (d) {
        return (d.items || []).map(function (it) { return {text: it.title || '', note: 'waiting', tone: null}; });
      },
      stickies: function (d) {
        return (d.items || []).map(function (it) {
          return {text: it.line || '', note: it.severity || 'fyi',
                  tone: it.severity === 'decide' ? 'bad' : (it.severity === 'approve' ? 'warn' : null)};
        });
      },
      calendar: function (d) {
        // one row per day the solver answered for, the way the wall
        // calendar's own face draws it: red is a day nobody is covering
        return (d.days || []).map(function (day) {
          var evs = (day.events || []).map(function (e) { return e.title || ''; }).filter(Boolean);
          var extra = (day.more | 0) || 0;
          var note = evs.join(' · ') + (extra > 0 ? (evs.length ? ' · ' : '') + '+' + extra : '');
          var un = day.unassigned | 0;
          return {text: dayLabel(day.date), tone: un > 0 ? 'bad' : null,
                  note: un > 0 ? un + ' uncovered' + (note ? ' · ' + note : '') : (note || 'nothing on')};
        });
      },
      window: function (d) {
        var signs = d.signs || [], nBad = d.ready ? Math.min((d.worse || []).length, signs.length) : 0;
        return signs.map(function (s, k) { return {text: s, note: k < nBad ? 'worse than your baseline' : '', tone: k < nBad ? 'bad' : null}; });
      },
      contracts: function (d) {
        return (d.items || []).map(function (it) { return {text: it.title || '', note: 'awaiting an answer', tone: null}; });
      },
      binders: function (d) {
        return (d || []).map(function (b) {
          return {text: b.title || '', note: (b.pulled ? 'needs a look' : '') + (b.pulled && b.detail ? ' · ' : '') + (b.detail || ''),
                  tone: b.pulled ? 'warn' : null};
        });
      }
    };
    var DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    function dayLabel(iso) {
      var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
      if (!m) return String(iso || '');
      var dt = new Date(+m[1], +m[2] - 1, +m[3]);
      return DAYS[dt.getDay()] + ' ' + (+m[3]);
    }
    function name(key) { return String(key || '').replace(/^study_/, ''); }

    /* FACE-ON (2026-09-22). The kitchen's card zones each name the mesh
       their card sits on (house.js FACE_MESH_MAP) and the lean-in
       approaches along that face's normal, so the pasted card reads square
       -- an oblique wall card reads as a misaligned web element. Study
       zones named nothing and were approached from wherever the camera
       happened to stand. Every zone names its face here: the painted
       detail plane where there is one (a PlaneGeometry, so zoneFaceQuad
       reads the TRUE quad, tilt included), the cork for the board, and for
       the two zones whose signal is spread over several small sheets (the
       desk's three piles, the five binders) one invisible plane spanning
       them, built once, in the parent the sheets already live in so the
       shelf wall's turn carries it. */
    function facePlane(parent, w, h) {
      var m = new T.Mesh(new T.PlaneGeometry(Math.max(w, .05), Math.max(h, .05)),
                         new T.MeshBasicMaterial({visible:false}));
      m.visible = false; m.raycast = function () {}; m.userData.noMirror = true;
      parent.add(m); return m;
    }
    var Z = built.zones, FACE = {
      board: Z.board.parts.cork, calendar: Z.calendar.parts.face,
      window: Z.window.parts.text, tray: Z.tray.parts.label,
      contracts: Z.contracts.parts.label, stickies: Z.monitor.parts.labels,
      monitor: Z.monitor.parts.labels, gauges: Z.gauges.parts.face,
      map: Z.map.parts.labels
    };
    (function () {   /* the desk: one plane over the three paper piles */
      var labels = Z.desk.parts.stacks.map(function (st) { return st.label; });
      if (!labels.length) return;
      var b = new T.Box3();
      labels.forEach(function (l) {
        var pw = l.geometry.parameters.width / 2, ph = l.geometry.parameters.height / 2;
        b.expandByPoint(new T.Vector3(l.position.x - pw, l.position.y, l.position.z - ph));
        b.expandByPoint(new T.Vector3(l.position.x + pw, l.position.y, l.position.z + ph));
      });
      var m = facePlane(labels[0].parent, b.max.x - b.min.x, b.max.z - b.min.z);
      m.rotation.x = -Math.PI / 2;
      m.position.set((b.min.x + b.max.x) / 2, b.max.y + .01, (b.min.z + b.max.z) / 2);
      FACE.desk = m;
    })();
    (function () {   /* the binders: one plane across their spines */
      var bs = Z.binders.parts.binders;
      if (!bs.length) return;
      var b = new T.Box3();
      bs.forEach(function (bd) {
        bd.updateMatrix();
        if (!bd.geometry.boundingBox) bd.geometry.computeBoundingBox();
        b.union(bd.geometry.boundingBox.clone().applyMatrix4(bd.matrix));
      });
      var m = facePlane(bs[0].parent, b.max.x - b.min.x, b.max.y - b.min.y);
      m.position.set((b.min.x + b.max.x) / 2, (b.min.y + b.max.y) / 2, b.max.z + .01);
      FACE.binders = m;
    })();
    function face(key) { return FACE[name(key)] || null; }
    function card(key) {
      var n = name(key), fn = CARD[n];
      if (!fn || !built.zones[n]) return null;
      var rows;
      try { rows = fn(built.data(n)) || []; } catch (e) { rows = []; }
      rows = rows.filter(function (r) { return r && r.text; });
      return rows.length ? {zone: key, rows: rows, summary: built.summary(n)} : null;
    }
    /* the one place a study zone's paint is shown or hidden: the host says
       which zone (if any) is being read, and the paint stands up only for a
       zone that wears no card */
    var shown = null;
    function focus(key) {
      var n = name(key);
      if (shown && shown !== n) { built.detail.show(shown, false); shown = null; }
      if (!n || !built.zones[n] || n === 'keys' || card(key)) return;
      built.detail.paint(n);
      built.detail.show(n, true);
      shown = n;
    }
    function detailState(key) {
      var z = built.zones[name(key)];
      if (!z || !z.detail) return null;
      var on = z.detail.on || [], vis = 0, painted = 0;
      on.forEach(function (m) { if (m.visible) vis++; if (m.userData && m.userData.g) painted++; });
      return {panels: on.length, visible: vis, painted: painted, shown: shown === name(key)};
    }
    return{group:root,architecture:arch,proxies:proxies,zones:zones,count:count,update:update,
      card:card,focus:focus,face:face,detailState:detailState,summary:function(key){return built.summary(name(key));},
      dispose:function(){
      var gs=new Set(),ms=new Set(),ts=new Set();
      [root,arch,proxies].forEach(function(top){top.traverse(function(o){if(o.geometry)gs.add(o.geometry);var a=Array.isArray(o.material)?o.material:[o.material];a.forEach(function(m){if(!m)return;ms.add(m);if(m.map)ts.add(m.map);});});});
      ts.forEach(function(t){t.dispose();});ms.forEach(function(m){m.dispose();});gs.forEach(function(g){g.dispose();});
    }};
  }};
})();
