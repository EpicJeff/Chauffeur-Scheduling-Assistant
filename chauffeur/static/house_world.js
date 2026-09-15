/* Authored object recipes, instantiated from this family's active programs.
   Geometry is built only when the set of programs changes. No animation loop. */
(function () {
  'use strict';
  window.HouseWorld = { build: function (T, detail, programs) {
    var root = new T.Group(), entries = [], geometries = new Map(), materials = new Map();
    var nice = detail >= 2, high = detail >= 3;
    var wood = 0x926744, oak = 0xc39b67, ivory = 0xeee5d3, ink = 0x292d30, brass = 0xb99a57;
    function material(color, metal) {
      var key = String(color) + '|' + !!metal;
      if (!materials.has(key)) materials.set(key, high
        ? new T.MeshStandardMaterial({color:color,roughness:metal ? 0.38 : 0.72,metalness:metal ? 0.65 : 0})
        : new T.MeshLambertMaterial({color:color}));
      return materials.get(key);
    }
    function geo(key, create) { if (!geometries.has(key)) geometries.set(key, create()); return geometries.get(key); }
    function mesh(g, geometry, color, x,y,z, metal) {
      var m = new T.Mesh(geometry, material(color, metal)); m.position.set(x,y,z);
      m.castShadow = high; m.receiveShadow = high; g.add(m); return m;
    }
    function box(g,w,h,d,color,x,y,z) {
      var geometry = geo(['box',w,h,d].join('|'), function () {
        if (!nice || Math.min(w,h,d) < 0.035) return new T.BoxGeometry(w,h,d);
        var r = Math.min(0.025,w/8,h/8,d/8), s = new T.Shape();
        s.moveTo(-w/2+r,-h/2+r); s.lineTo(w/2-r,-h/2+r);
        s.lineTo(w/2-r,h/2-r); s.lineTo(-w/2+r,h/2-r); s.closePath();
        var b = new T.ExtrudeGeometry(s,{depth:d-2*r,bevelEnabled:true,bevelThickness:r,bevelSize:r,bevelSegments:1,steps:1});
        b.translate(0,0,-d/2+r); return b;
      });
      return mesh(g,geometry,color,x,y,z);
    }
    function cyl(g,rt,rb,h,color,x,y,z,metal) {
      return mesh(g,geo(['cyl',rt,rb,h].join('|'),function(){return new T.CylinderGeometry(rt,rb,h,nice?16:8);}),color,x,y,z,metal);
    }
    function ball(g,r,color,x,y,z,sx,sy,sz) {
      var m = mesh(g,geo('ball'+r,function(){return new T.SphereGeometry(r,nice?12:6,nice?8:4);}),color,x,y,z);
      m.scale.set(sx||1,sy||1,sz||1); return m;
    }
    function rod(g,a,b,r,color) {
      var from = new T.Vector3(a[0],a[1],a[2]), to = new T.Vector3(b[0],b[1],b[2]);
      var m = cyl(g,r,r,from.distanceTo(to),color,0,0,0,true);
      m.position.copy(from.clone().add(to).multiplyScalar(.5));
      m.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),to.sub(from).normalize()); return m;
    }
    function entry(key,label,room,at,action,ids) {
      var g = new T.Group(); g.position.set(at[0],at[1],at[2]);
      g.userData.room=room; g.userData.houseWorldKey=key;
      if (action) g.userData.houseAction=action;
      if (ids) g.userData.housePrograms=ids;
      root.add(g); entries.push({key:key,label:label,room:room,group:g,action:action,ids:ids}); return g;
    }
    function book(g,color,x,y,z) {
      box(g,.46,.07,.34,color,x,y,z);box(g,.42,.045,.31,ivory,x,y+.053,z);
      box(g,.46,.025,.34,color,x,y+.085,z);
    }
    function clipboard(g,color) {
      box(g,.58,.78,.06,wood,0,.72,0); box(g,.48,.65,.012,ivory,0,.72,.04);
      box(g,.20,.06,.04,brass,0,1.10,.055);
      for(var i=0;i<4;i++) {
        box(g,.05,.05,.012,color,-.16,.91-i*.13,.052);
        box(g,.24,.014,.012,0x8a897d,.045,.91-i*.13,.052);
      }
    }
    // Actual feature homes: a chore caddy, routine board, task clipboard,
    // errand tote and the family's program book. Attention never moves them.
    var c = entry('chores','Chore caddy','mudroom',[-11.6,.06,4.7],'chores');
    box(c,.68,.32,.40,0x6d9187,0,.16,0);box(c,.62,.06,.36,ink,0,.34,0);
    rod(c,[-.25,.3,0],[-.25,.65,0],.028,brass);rod(c,[.25,.3,0],[.25,.65,0],.028,brass);
    rod(c,[-.25,.65,0],[.25,.65,0],.032,wood);
    cyl(c,.08,.1,.37,ivory,-.16,.46,.06);box(c,.12,.05,.08,0x708ab1,-.14,.68,.06);
    cyl(c,.07,.075,.28,0xc99763,.17,.44,.04);
    c=entry('routines','Daily routine','mudroom',[-10.70,.06,4.70],'routines');clipboard(c,0x699878);
    c=entry('tasks','Household tasks','living',[-.50,.86,7.65],'tasks');clipboard(c,0x55748a);c.rotation.y=Math.PI/2;
    c=entry('errands','Errand tote','garage',[-17.58,1.02,8.65],'errands');
    box(c,.65,.64,.4,0xb29265,0,.34,0);
    [-.18,.18].forEach(function(x){rod(c,[x,.58,-.1],[x,.92,-.1],.018,wood);});
    rod(c,[-.18,.92,-.1],[.18,.92,-.1],.018,wood);book(c,0x728d7f,0,.67,0);
    c=entry('programs','Program book','living',[-.50,.86,9.10],'programs');book(c,0x536e79,0,0,0);
    // A locked folio on the living-room console is the parent-only Study.
    // The room stays honest: the separate admin surface is not a fake door.
    c=entry('study','Study · Parent PIN','living',[-6.18,.97,12.03],'study');
    book(c,0x765338,0,0,0);
    box(c,.16,.18,.045,brass,0,.17,.18);
    box(c,.09,.09,.052,ink,0,.15,.205);
    function guitar(g, color, electric) {
      var s = new T.Shape();
      s.moveTo(0,.16);s.bezierCurveTo(-.55,.14,-.62,.70,-.31,.86);
      s.bezierCurveTo(-.17,.94,-.40,1.21,-.18,1.29);s.lineTo(.18,1.29);
      s.bezierCurveTo(.40,1.21,.17,.94,.31,.86);s.bezierCurveTo(.62,.70,.55,.14,0,.16);
      var body=geo('guitarBody'+electric,function(){return new T.ExtrudeGeometry(s,{depth:electric?.10:.18,bevelEnabled:nice,bevelThickness:.018,bevelSize:.025,bevelSegments:2,curveSegments:nice?12:6,steps:1});});
      mesh(g,body,electric?color:oak,0,0,0);
      box(g,.13,.85,.10,wood,0,1.62,.045);box(g,.115,.89,.025,ink,0,1.62,.108);
      box(g,.19,.28,.10,wood,0,2.16,.04).rotation.z=-.08;
      box(g,.29,.065,.04,wood,0,.47,.21);
      if (!electric) {var hole=cyl(g,.135,.135,.012,ink,0,.96,.205);hole.rotation.x=Math.PI/2;}
      else {box(g,.25,.20,.018,ivory,.17,.77,.125);box(g,.18,.05,.025,ink,0,.93,.14);}
      for(var f=0;f<(nice?12:6);f++) box(g,.12,.009,.014,brass,0,1.26+f*.057,.129);
      for(var t=0;t<3;t++) [-1,1].forEach(function(sign){ball(g,.035,brass,sign*.13,2.08+t*.08,.04);});
      if (nice) for(var st=0;st<6;st++) rod(g,[-.04+st*.016,.48,.23],[-.04+st*.016,2.23,.13],.0025,brass);
      rod(g,[0,.10,-.05],[0,1.13,-.10],.035,ink);
      [-1,1].forEach(function(sign){rod(g,[0,.1,-.05],[sign*.34,.04,.32],.025,ink);});
      box(g,.12,.38,.055,color,.39,.61,.14).rotation.z=-.35;
      g.rotation.z=-.08;
    }
    function piano(g,color) {
      box(g,2.45,1.75,.64,wood,0,.97,0);box(g,2.58,.10,.75,oak,0,1.89,0);
      box(g,2.12,.82,.05,color,0,1.35,.35);box(g,2.30,.12,.63,wood,0,.87,.31);
      box(g,2.16,.05,.45,ink,0,.96,.38);
      for(var i=0;i<28;i++) box(g,.073,.06,.43,ivory,-1.03+i*.077,.99,.40);
      for(var k=0;k<27;k++) if([0,1,3,4,5].indexOf(k%7)>=0) box(g,.04,.055,.24,ink,-.993+k*.077,1.045,.28);
      [-1,1].forEach(function(sign){box(g,.14,.86,.18,wood,sign*1.10,.43,.49);});
      for(var p=0;p<3;p++) box(g,.08,.055,.27,brass,(p-1)*.18,.11,.43);
      box(g,.76,.51,.07,wood,0,1.39,.42).rotation.x=-.18;
      box(g,.63,.42,.025,ivory,0,1.41,.48).rotation.x=-.18;
      for(var line=0;line<5;line++) box(g,.5,.009,.009,0x918977,0,1.27+line*.07,.53);
      box(g,1.05,.16,.55,ink,0,.57,1.18);
      [-.4,.4].forEach(function(x){[-.19,.19].forEach(function(z){box(g,.08,.48,.08,wood,x,.24,1.18+z);});});
    }
    function gym(g,color) {
      box(g,.07,4.32,9.76,ivory,-1.46,2.22,0);
      box(g,2.94,4.32,.07,ivory,0,2.22,-4.87);
      box(g,.09,.18,9.76,wood,-1.40,.18,0);
      box(g,2.94,.18,.09,wood,0,.18,-4.82);
      box(g,.09,1.65,2.35,wood,-1.39,2.08,.4);
      box(g,.035,1.52,2.20,0xa8bfbe,-1.33,2.08,.4);
      for(var hook=0;hook<3;hook++)box(g,.13,.09,.09,brass,-1.32,1.22,2.6+hook*.3);
      box(g,.08,.55,.27,color,-1.26,.93,2.9);
      box(g,2.94,.10,9.80,0x9d998d,0,0,0);
      for(var z=-4;z<=4;z++) box(g,2.86,.015,.92,0x55595b,0,.06,z);
      box(g,1.10,.24,2.10,ink,0,.2,-1.6);box(g,.87,.025,1.73,0x494c4b,0,.334,-1.57);
      for(var r=0;r<9;r++)box(g,.85,.006,.02,0x747879,0,.352,-2.30+r*.18);
      [-.52,.52].forEach(function(x){rod(g,[x,.3,-2.48],[x,1.60,-2.62],.055,0x858b8b);rod(g,[x,1.2,-2.50],[x,1.1,-1.70],.04,ink);});
      box(g,.94,.30,.15,ink,0,1.65,-2.62).rotation.x=-.25;
      box(g,.35,.13,.015,color,0,1.66,-2.525).rotation.x=-.25;
      box(g,.66,.15,1.40,color,0,.64,1.05);
      [-.52,.52].forEach(function(z){box(g,.46,.55,.09,ink,0,.30,1.05+z);});
      rod(g,[-.98,1.42,.3],[.98,1.42,.3],.035,brass);
      [-1,1].forEach(function(sign){rod(g,[sign*.76,.1,.3],[sign*.76,1.43,.3],.045,ink);var w=cyl(g,.24,.24,.13,ink,sign*.83,1.42,.3);w.rotation.z=Math.PI/2;});
      box(g,1.05,.035,1.80,0x748f83,0,.10,3.20);
      [-.25,.25].forEach(function(x){var d=cyl(g,.08,.08,.30,brass,x,.25,3.2);d.rotation.z=Math.PI/2;[-.16,.16].forEach(function(dx){var p=cyl(g,.13,.13,.09,ink,x+dx,.25,3.2);p.rotation.z=Math.PI/2;});});
    }
    function garden(g,color) {
      box(g,2.50,.16,2.0,wood,0,.08,0);box(g,2.32,.07,1.82,0xc9c0a6,0,.19,0);
      if(nice) for(var i=0;i<8;i++) box(g,2.1,.01,.015,0xaaa38e,0,.234,-.72+i*.20);
      ball(g,.34,0x76766c,-.65,.35,-.35,1,.65,.9);ball(g,.23,0x8b8b7d,-.34,.30,-.49,1,.7,1);
      cyl(g,.22,.17,.30,color,.65,.37,-.40);rod(g,[.65,.48,-.40],[.58,1.0,-.43],.045,wood);
      [[.5,1,-.4],[.78,.86,-.39],[.36,.86,-.5]].forEach(function(p){ball(g,.24,0x638055,p[0],p[1],p[2],1.3,.58,1);});
      cyl(g,.39,.42,.12,0x5b7079,0,.32,.45);
      box(g,.36,.14,.36,0x818777,-.80,.30,.55);box(g,.25,.26,.25,ivory,-.80,.50,.55);
      box(g,.40,.08,.40,ink,-.80,.68,.55);
    }
    var groups = {};
    (programs||[]).forEach(function(p){var key=p.kind==='guitar'?'guitar-'+p.variant:p.kind;(groups[key]||(groups[key]=[])).push(p);});
    Object.keys(groups).sort().forEach(function(key){
      var list=groups[key], p=list[0], kind=p.kind, color=/^#[0-9a-f]{6}$/i.test(p.color)?p.color:'#58978b';
      var spot=kind==='piano'?[1.8,.04,5.5]:kind==='guitar'?[key==='guitar-electric'?4.2:3.4,.04,7.0]:kind==='exercise'?[8.83,.02,-.9]:kind==='meditation'?[11.95,.02,6.6]:[.45,.90,9.3];
      var room=kind==='exercise'?'fitness':kind==='meditation'?'garden':'living';
      var label=list.length===1?(p.member_name ? p.member_name+'’s ' : '')+({guitar:'guitar',piano:'piano',exercise:'workout',meditation:'garden',book:'program'}[kind]):({guitar:'Guitar',piano:'Piano',exercise:'Workout room',meditation:'Quiet garden',book:'Programs'}[kind]);
      var g=entry('program-'+key,label,room,spot,null,list.map(function(p){return p.id;}));
      if(kind==='guitar')guitar(g,color,p.variant==='electric');
      else if(kind==='piano')piano(g,color);
      else if(kind==='exercise')gym(g,color);
      else if(kind==='meditation')garden(g,color);
      else book(g,color,0,0,0);
    });
    root.updateMatrixWorld(true);
    return {group:root,entries:entries,fitness:!!groups.exercise,garden:!!groups.meditation,
      dispose:function(){var used=new Set();root.traverse(function(o){if(o.material)used.add(o.material);});used.forEach(function(m){m.dispose();});materials.forEach(function(m){if(!used.has(m))m.dispose();});geometries.forEach(function(g){g.dispose();});}};
  }};
})();
