/* Stable household features rendered as objects inside the authored house. */
(function () {
  'use strict';
  window.HouseFeatures = { build: function (T, detail) {
    var root = new T.Group(), entries = [], fabric = [], geometries = new Map(), materials = new Map();
    var nice = detail >= 2, high = detail >= 3;
    var wood = 0x926744, ivory = 0xeee5d3, ink = 0x292d30, brass = 0xb99a57;
    function material(color, metal) {
      var key = color + '|' + !!metal;
      if (!materials.has(key)) materials.set(key, high
        ? new T.MeshStandardMaterial({color:color, roughness:metal ? 0.38 : 0.72, metalness:metal ? 0.65 : 0})
        : new T.MeshLambertMaterial({color:color}));
      return materials.get(key);
    }
    function geo(key, create) {
      if (!geometries.has(key)) geometries.set(key, create());
      return geometries.get(key);
    }
    function mesh(group, geometry, color, x, y, z, metal) {
      var item = new T.Mesh(geometry, material(color, metal));
      item.position.set(x, y, z); item.castShadow = high; item.receiveShadow = high;
      group.add(item); return item;
    }
    function box(group, w, h, d, color, x, y, z) {
      var geometry = geo(['box',w,h,d].join('|'), function () {
        if (!nice || Math.min(w,h,d) < 0.035) return new T.BoxGeometry(w,h,d);
        var r = Math.min(0.025,w/8,h/8,d/8), shape = new T.Shape();
        shape.moveTo(-w/2+r,-h/2+r); shape.lineTo(w/2-r,-h/2+r);
        shape.lineTo(w/2-r,h/2-r); shape.lineTo(-w/2+r,h/2-r); shape.closePath();
        var made = new T.ExtrudeGeometry(shape,{depth:d-2*r,bevelEnabled:true,bevelThickness:r,bevelSize:r,bevelSegments:1,steps:1});
        made.translate(0,0,-d/2+r); return made;
      });
      return mesh(group,geometry,color,x,y,z);
    }
    function cylinder(group, top, bottom, height, color, x, y, z, metal) {
      return mesh(group,geo(['cylinder',top,bottom,height].join('|'),function(){
        return new T.CylinderGeometry(top,bottom,height,nice?16:8);
      }),color,x,y,z,metal);
    }
    function rod(group, from, to, radius, color) {
      var a = new T.Vector3(from[0],from[1],from[2]), b = new T.Vector3(to[0],to[1],to[2]);
      var item = cylinder(group,radius,radius,a.distanceTo(b),color,0,0,0,true);
      item.position.copy(a.clone().add(b).multiplyScalar(0.5));
      item.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),b.sub(a).normalize());
    }
    function entry(key, label, room, at, action) {
      var group = new T.Group(); group.position.set(at[0],at[1],at[2]);
      group.userData.room = room; group.userData.houseFeatureKey = key;
      group.userData.houseAction = action;
      root.add(group); entries.push({key:key,label:label,room:room,group:group,action:action});
      return group;
    }
    function fixture(key, room, at) {
      var group = new T.Group(); group.position.set(at[0],at[1],at[2]);
      group.userData.room = room; group.userData.houseFeatureKey = key;
      root.add(group); return group;
    }
    function shellFixture(key, room, at, name, normal) {
      var group = fixture(key, room, at);
      fabric.push({group:group,name:name,normal:normal});
      return group;
    }
    function book(group, color, x, y, z) {
      box(group,.46,.07,.34,color,x,y,z); box(group,.42,.045,.31,ivory,x,y+.053,z);
      box(group,.46,.025,.34,color,x,y+.085,z);
    }
    function clipboard(group, color) {
      box(group,.58,.78,.06,wood,0,.72,0); box(group,.48,.65,.012,ivory,0,.72,.04);
      box(group,.20,.06,.04,brass,0,1.10,.055);
      for (var i=0;i<4;i++) {
        box(group,.05,.05,.012,color,-.16,.91-i*.13,.052);
        box(group,.24,.014,.012,0x8a897d,.045,.91-i*.13,.052);
      }
    }
    function interiorDoor(group, hand) {
      var leaf = 0x39424d, panel = 0x4a5460;
      box(group,1.58,2.84,.14,leaf,0,1.42,0);
      box(group,1.22,1.02,.035,panel,0,2.13,.09);
      box(group,1.22,1.02,.035,panel,0,.72,.09);
      box(group,1.86,.15,.24,ivory,0,2.96,0);
      [-1,1].forEach(function(side){box(group,.15,3.02,.24,ivory,side*.86,1.51,0);});
      cylinder(group,.07,.07,.10,brass,hand*.58,1.43,.16,true).rotation.x = Math.PI / 2;
    }

    // STUDY REFIT (2026-09-16). The user: "That door might actually make
    // a good door for the study as those commonly have double glass
    // doors." So the study's opening wears a pair of glazed doors at the
    // size the retired patio slider's glass was -- 2.65 wide, 3.65 tall
    // -- built here rather than in house.js so the door keeps the
    // `living_study_door` fixture whole: its entry group, its room
    // stamping, its registration and its parent-PIN tap are untouched,
    // and only the leaf it draws changed. One assembly centred in the
    // 0.35 partition with casings on both faces, because the wall is CUT
    // at this opening: a one-sided leaf would leave the reveal open.
    //
    // No new palette: the frame is the same `ivory` every casing in this
    // module is painted with, the glass is `ink`, the handles `brass`.
    function studyGlass() {
      // The glazing gets its OWN material rather than the shared `ink`
      // one. chfShellFabric reports emissiveIntensity off exactly the
      // meshes marked interiorWindow, and the rule it pins -- both sides
      // of this glass are indoors, so it never takes the exterior night
      // glow -- belongs to this door alone. Kept in `materials` so
      // dispose() still frees it.
      if (!materials.has('study-glass')) {
        var glass = high
          ? new T.MeshStandardMaterial({color:ink, roughness:.30, metalness:.12})
          : new T.MeshLambertMaterial({color:ink});
        glass.emissiveIntensity = 0;
        materials.set('study-glass', glass);
      }
      return materials.get('study-glass');
    }
    function glassDoors(group) {
      var W = 2.65, H = 3.65, st = .13, ms = .195, rail = .17, leafT = .14;
      // one lite per leaf, from the meeting stile to the hanging one
      var paneW = W / 2 - st - ms, paneH = H - rail * 2.6;
      var paneX = (ms + W / 2 - st) / 2;
      [-1, 1].forEach(function (side) {
        var cx = side * W / 4;
        var pane = new T.Mesh(geo(['glass',paneW,paneH].join('|'), function () {
          return new T.BoxGeometry(paneW, paneH, .05);
        }), studyGlass());
        pane.position.set(side * paneX, H / 2 + rail * .3, 0);
        pane.receiveShadow = high;
        pane.userData.interiorWindow = true;
        group.add(pane);
        // the hanging stile on the outside edge, and the leaf's rails
        box(group,st,H,leafT,ivory,side * (W / 2 - st / 2),H / 2,0);
        box(group,W / 2,rail,leafT,ivory,cx,H - rail / 2,0);
        box(group,W / 2,rail * 1.6,leafT,ivory,cx,rail * .8,0);
      });
      // the meeting stile the two leaves close on, proud of both leaves
      box(group,ms * 2,H,leafT + .03,ivory,0,H / 2,0);
      // a handle per leaf, on each face, ON the meeting stile where a
      // pair of doors is actually opened from: both rooms get a handle.
      [-1, 1].forEach(function (side) {
        [-1, 1].forEach(function (face) {
          box(group,.09,.34,.04,brass,side * .13,1.34,face * (leafT / 2 + .04));
          cylinder(group,.045,.045,.10,brass,side * .13,1.34,
                   face * (leafT / 2 + .09),true).rotation.x = Math.PI / 2;
        });
      });
      // casing and reveal lining in one: 0.50 deep plugs the 0.35 cut and
      // stands .075 proud on each face, and W + .40 laps both gap edges.
      box(group,W + .40,.16,.50,ivory,0,H + .08,0);
      [-1, 1].forEach(function (side) {
        box(group,.16,H + .16,.50,ivory,side * (W / 2 + .08),(H + .16) / 2,0);
      });
    }

    var item = entry('chores','Chore caddy','mudroom',[-11.6,.06,4.7],'chores');
    box(item,.68,.32,.40,0x6d9187,0,.16,0); box(item,.62,.06,.36,ink,0,.34,0);
    rod(item,[-.25,.3,0],[-.25,.65,0],.028,brass); rod(item,[.25,.3,0],[.25,.65,0],.028,brass);
    rod(item,[-.25,.65,0],[.25,.65,0],.032,wood);
    cylinder(item,.08,.1,.37,ivory,-.16,.46,.06); box(item,.12,.05,.08,0x708ab1,-.14,.68,.06);
    cylinder(item,.07,.075,.28,0xc99763,.17,.44,.04);

    item = entry('routines','Family routine board','mudroom',[-12.45,1.82,6.15],'routines');
    clipboard(item,0x699878); item.rotation.y = Math.PI/2;
    // Household work lives in the home ledger on the living-room console.
    item = entry('tasks','Home ledger','living',[-.50,.86,7.68],'tasks');
    book(item,0x55748a,0,0,0);
    box(item,.26,.025,.22,ivory,0,.10,.03);
    box(item,.16,.018,.018,brass,0,.115,.15);
    item = entry('errands','Errand tote','garage',[-17.58,1.02,8.65],'errands');
    box(item,.65,.64,.4,0xb29265,0,.34,0);
    [-.18,.18].forEach(function(x){rod(item,[x,.58,-.1],[x,.92,-.1],.018,wood);});
    rod(item,[-.18,.92,-.1],[.18,.92,-.1],.018,wood); book(item,0x728d7f,0,.67,0);
    item = entry('programs','Program book','living',[-.50,.86,9.55],'programs');
    book(item,0x536e79,0,0,0);
    // Study wing joins the east side of the living room. Its locked door
    // belongs on that shared wall, across the room from the exterior door.
    // z translated north 2.17 with the study (task 1): 12.10 -> 9.93.
    // STUDY REFIT: glazed double doors, centred in the 0.35 partition
    // (x 6.675) instead of hung on its west face, because house.js cuts
    // the opening right through. Everything else about this fixture is
    // untouched -- the same entry group, the same 'study' action behind
    // the parent PIN, the same name, normal, twoSided and cutawayRoom.
    item = entry('study','Study · Parent PIN','living',[6.675,.02,9.93],'study');
    item.rotation.y = -Math.PI / 2;
    glassDoors(item);
    fabric.push({group:item,name:'living_study_door',normal:[1,0,0],twoSided:true,
                 cutawayRoom:'study'});

    // STUDY REFIT: "then use the study's regular interior door on that
    // other room". The east room's opening at z 5.80 -- the retired
    // patio slider's -- takes the plain interior door, keeping the
    // slider's own registration semantics: normal [1,0,0], room
    // 'kitchen' (so a tap from the east room still walks through to the
    // kitchen), twoSided, and ownerless like every opening. Unlike the
    // back room's door below -- a leaf proud of an UNCUT wall -- this
    // opening is a real hole through the slab, so it wears a leaf on
    // each face with the cut's own lining between them.
    item = fixture('east-room-door','kitchen',[6.675,.02,5.80]);
    [[-.175,-Math.PI / 2,1],[.175,Math.PI / 2,-1]].forEach(function (face) {
      var leafG = new T.Group();
      leafG.position.x = face[0]; leafG.rotation.y = face[1];
      item.add(leafG);
      interiorDoor(leafG,face[2]);
    });
    box(item,.35,.15,1.90,ivory,0,3.02,0);
    [-1,1].forEach(function (side) { box(item,.35,3.02,.10,ivory,0,1.51,side * .85); });
    fabric.push({group:item,name:'east_room_door',normal:[1,0,0],twoSided:true});

    // The back room's door: a leaf proud of the uncut partition, the one
    // opening in this wall that was authored that way.
    item = shellFixture('back-room-door','living',[6.50,.02,2.45],
                        'living_back_room_door',[1,0,0]);
    item.rotation.y = -Math.PI / 2;
    interiorDoor(item,-1);

    root.updateMatrixWorld(true);
    return {group:root, entries:entries, fabric:fabric, dispose:function () {
      materials.forEach(function(m){m.dispose();}); geometries.forEach(function(g){g.dispose();});
    }};
  }};
})();
