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

    var item = entry('chores','Chore caddy','mudroom',[-11.6,.06,4.7],'chores');
    box(item,.68,.32,.40,0x6d9187,0,.16,0); box(item,.62,.06,.36,ink,0,.34,0);
    rod(item,[-.25,.3,0],[-.25,.65,0],.028,brass); rod(item,[.25,.3,0],[.25,.65,0],.028,brass);
    rod(item,[-.25,.65,0],[.25,.65,0],.032,wood);
    cylinder(item,.08,.1,.37,ivory,-.16,.46,.06); box(item,.12,.05,.08,0x708ab1,-.14,.68,.06);
    cylinder(item,.07,.075,.28,0xc99763,.17,.44,.04);

    item = entry('routines','Family routine board','mudroom',[-12.45,1.10,6.15],'routines');
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
    item = entry('study','Study · Parent PIN','living',[6.50,.02,12.10],'study');
    item.rotation.y = -Math.PI / 2;
    interiorDoor(item,1);
    fabric.push({group:item,name:'living_study_door',normal:[1,0,0],twoSided:true,
                 cutawayRoom:'study'});

    // The two-sided patio slider is part of the house shell, so its inside
    // and outside views are the same physical assembly. This module adds
    // only the separate hinged door into the rear east room.
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
