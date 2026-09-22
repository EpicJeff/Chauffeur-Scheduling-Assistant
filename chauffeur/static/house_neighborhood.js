/* Deterministic, exterior-only facade instances. No household state or frame loop. */
(function (root) {
  'use strict';
  function clone(v) { return JSON.parse(JSON.stringify(v)); }
  // Use the interactive home's wall area to establish one common map scale.
  // A similarity transform preserves street angles and every size ratio while
  // leaving room coordinates, picking and camera navigation in authored units.
  function fitLayout(layout,body) {
    if(!layout || !layout.home || !layout.home.footprint)return layout;
    var out=clone(layout),home=layout.home,f=home.footprint;
    var scale=Math.sqrt(body.width*body.depth/(f.width*f.depth));
    var c=Math.cos(home.rotation),s=Math.sin(home.rotation);
    function point(p){var x=p[0]-home.x,z=p[1]-home.z;return [body.x+(x*c-z*s)*scale,body.z+(x*s+z*c)*scale];}
    out.roads=out.roads.map(function(line){return line.map(point);});
    out.terrain=(out.terrain||[]).map(function(f){return {kind:f.kind,rings:f.rings.map(function(r){return r.map(point);})};});
    out.lots.forEach(function(l){
      var p=point([l.x,l.z]);l.x=p[0];l.z=p[1];l.rotation-=home.rotation;
      if(l.footprint){l.footprint.width*=scale;l.footprint.depth*=scale;l.footprint.outline=l.footprint.outline.map(point);}
      else l.scale=(l.scale||1)*scale;
    });
    out.homeCalibration={scale:scale,rotation:-home.rotation,source:'home-footprint'};
    return out;
  }
  // Facade-compatible style recipes; placement and rendering do not choose style.
  var STYLES = [
    {name:'farmhouse',body:'white',cladding:'batten',roof:'gable',pitch:35,roofColor:'charcoal',frame:'black',trim:'white',porch:'shed',stories:2,count:2},
    {name:'craftsman',body:'sage',cladding:'lap',roof:'gable',pitch:25,roofColor:'brown',frame:'white',trim:'white',porch:'gable',stories:1,count:3},
    {name:'modern',body:'greige',cladding:'stucco',roof:'hip',pitch:22.5,roofColor:'charcoal',frame:'black',trim:'black',porch:'flat',stories:2,count:3},
    {name:'ranch',body:'cream_brick',cladding:'brick',roof:'hip',pitch:22.5,roofColor:'weathered',frame:'white',trim:'white',porch:'shed',stories:1,count:2}
  ];
  function plan(canonical,layout) {
    var placements = [];
    // Paired rows face shared streets, including the block behind the home.
    for (var row=-3;row<=3;row++) for (var col=-3;col<=3;col++) {
      if(row===0 && col===0)continue;
      placements.push([col*51,row*58,Math.abs(row)%2?Math.PI:0,
        Math.abs(row)<=1 && Math.abs(col)<=1?'near':'far']);
    }
    if(layout && layout.source==='mapbox')placements=layout.lots.map(function(l){return [l.x,l.z,l.rotation,l.detail,l.scale||1,l.footprint];});
    var nearIndex=0;
    return placements.map(function (p,i) {
      var s=clone(canonical),recipe=STYLES[i%STYLES.length];
      s.mirror=i%2===1;
      s.style={roof:recipe.roofColor,frame:recipe.frame,door:recipe.name==='modern'?'black':'wood',trim:recipe.trim};
      s.roof=[]; s.upper=[]; s.ground=[];
      ['garage','main'].forEach(function (name) {
        var b=s.blocks[name]; b.body=recipe.body;
        b.cladding=recipe.cladding; b.depth=i%2?1.2:0;
        b.roof={form:recipe.roof,ridge:name==='garage'&&recipe.name==='craftsman'?'z':'x',pitch_deg:recipe.pitch};
      });
      s.blocks.garage.orientation='front';
      s.ground.push({slot:0,span:3,kind:'garage_door',style:recipe.name==='modern'?'glass':'panel',leaves:2}, {slot:10,span:2,kind:'door',count:i%2?2:1});
      [7,13,16].forEach(function (slot) { s.ground.push({slot:slot,span:slot===7?3:2,kind:'window',size:'standard',count:recipe.count,shutters:recipe.name==='ranch',story:1}); });
      s.ground.push({slot:9,span:5,kind:'porch',type:'covered',roof:recipe.porch});
      if (recipe.stories===2) {
        s.upper.push({slot:7,span:7,roof:clone(s.blocks.main.roof)});
        [8,10,12].forEach(function (slot) { s.ground.push({slot:slot,span:1,kind:'window',size:'standard',shutters:false,story:2}); });
      }
      if (recipe.name==='farmhouse' || recipe.name==='craftsman') s.roof.push({slot:3,span:3,kind:'gable',window:true});
      if(p[3]==='near'){
        var variant=Math.floor(nearIndex++/4);
        s.blocks.main.depth=variant?2.4:0;
        s.blocks.garage.depth=variant?0:1.2;
        s.blocks.garage.roof.ridge=variant?'z':'x';
        s.ground.forEach(function(f){if(f.kind==='porch'){f.slot=variant?8:9;f.span=variant?6:4;}});
        s.upper.forEach(function(u){u.slot=variant?8:7;u.span=variant?8:6;});
        s.ground=s.ground.filter(function(f){return f.story!==2;});
        if(s.upper.length)(variant?[9,11,13]:[8,10,12]).forEach(function(slot){s.ground.push({slot:slot,span:1,kind:'window',size:'standard',count:1,shutters:false,story:2});});
      }
      return {id:'neighbor-'+i,x:p[0],z:p[1],rotation:p[2],detail:p[3],scale:p[4]||1,footprint:p[5],style:recipe.name,spec:s};
    });
  }

  // Same facade schema and physical block envelopes as the active house. This
  // projection builds closed exterior solids, omitting interiors and cutaway fabric.
  function exterior(spec,envelopes,palette,emit,detailed) {
    function color(role,value) { return palette[role][value] || palette[role][Object.keys(palette[role])[0]]; }
    function box(w,h,d,x,y,z,c) { emit('box',[w,h,d],[x,y,z],0,c); }
    function wall(b,height,y,body,cladding) {
      emit(detailed?'wall_'+cladding:'box',[b.east-b.west,height,b.south-b.north],[(b.west+b.east)/2,y,(b.north+b.south)/2],0,color('body',body));
      if(!detailed)return;
      var trim=color('trim',spec.style.trim),w=b.east-b.west,d=b.south-b.north;
      box(w,.35,d,(b.west+b.east)/2,y-height/2+.17,(b.north+b.south)/2,0xa19b90);
      [b.west,b.east].forEach(function(x){[b.north,b.south].forEach(function(z){box(.16,height,.16,x,y,z,trim);});});
      box(w+.16,.18,d+.16,(b.west+b.east)/2,y+height/2-.09,(b.north+b.south)/2,trim);
    }
    function roof(b,r,y) {
      var w=b.east-b.west+.6,d=b.south-b.north+.6,turn=r.ridge==='z'?Math.PI/2:0;
      var cross=turn?w:d, rise=Math.tan(r.pitch_deg*Math.PI/180)*cross/2;
      var dims=turn?[d,rise,w]:[w,rise,d],pos=[(b.west+b.east)/2,y,(b.north+b.south)/2];
      emit((detailed?'roof_':'')+(r.form==='hip'?'hip':'gable'),dims,pos,turn,color('roof',spec.style.roof));
      if(r.form!=='hip')emit('caps',dims,pos,turn,color('body',spec.blocks.main.body));
      box(w,.12,.16,pos[0],y,b.south+.3,color('trim',spec.style.trim));
      box(w,.12,.16,pos[0],y,b.north-.3,color('trim',spec.style.trim));
    }
    function span(f) {
      var name=f.slot<6?'garage':'main',b=envelopes[name],n=name==='garage'?6:12,slot=f.slot-(name==='garage'?0:6);
      var width=(b.east-b.west)/n;
      return {x:b.west+(slot+f.span/2)*width,w:f.span*width,z:b.south+spec.blocks[name].depth,h:b.eave,block:name};
    }
    ['garage','main'].forEach(function(name) {
      var b=clone(envelopes[name]),v=spec.blocks[name]; b.south+=v.depth;
      wall(b,b.eave,b.eave/2,v.body,v.cladding);
      var upper=spec.upper.filter(function(u){return (u.slot<6?'garage':'main')===name;})[0];
      if(upper){
        var raised=span(upper),left=raised.x-raised.w/2,right=raised.x+raised.w/2;
        if(left>b.west+.1)roof(Object.assign({},b,{east:left}),v.roof,b.eave);
        if(right<b.east-.1)roof(Object.assign({},b,{west:right}),v.roof,b.eave);
      }else roof(b,v.roof,b.eave);
      // Low-cost siding courses keep these from reading as untextured cubes.
      if(!detailed && v.cladding==='lap') for(var y=1.2;y<b.eave;y+=1.2) box(b.east-b.west,.035,.05,(b.west+b.east)/2,y,b.south+.025,color('trim',spec.style.trim));
      var frame=color('frame',spec.style.frame),side=name==='main'?b.east+.06:b.west-.06;
      [-2,5].forEach(function(z){box(.14,2,1.4,side,3,z,frame);box(.16,1.8,1.2,side+(name==='main'?.04:-.04),3,z,0x354b54);if(detailed){box(.22,.065,1.2,side,3,z,frame);box(.22,1.8,.065,side,3,z,frame);box(.28,.13,1.65,side,1.98,z,frame);}});
      [.25,.7].forEach(function(t){var x=b.west+(b.east-b.west)*t;box(1.5,2,.14,x,3,b.north-.08,frame);box(1.3,1.8,.16,x,3,b.north-.12,0x354b54);if(detailed){box(1.3,.065,.2,x,3,b.north-.15,frame);box(.065,1.8,.2,x,3,b.north-.15,frame);box(1.7,.13,.3,x,1.98,b.north-.12,frame);}});
    });
    spec.upper.forEach(function(u) {
      var e=span(u),base=envelopes[e.block],b={west:e.x-e.w/2,east:e.x+e.w/2,north:base.north,south:e.z};
      wall(b,e.h,e.h*1.5,spec.blocks[e.block].body,spec.blocks[e.block].cladding);
      // Upper walls remain finished and fenestrated from the back/side orbit.
      [.25,.75].forEach(function(t){var x=b.west+e.w*t;box(1.55,2,.15,x,e.h+3,b.north-.09,color('frame',spec.style.frame));box(1.3,1.75,.18,x,e.h+3,b.north-.16,0x354b54);});
      [b.west-.08,b.east+.08].forEach(function(x){box(.15,2,1.55,x,e.h+3,(b.north+b.south)/2,color('frame',spec.style.frame));box(.18,1.75,1.3,x+(x<e.x?-.06:.06),e.h+3,(b.north+b.south)/2,0x354b54);});
      roof(b,u.roof,e.h*2);
    });
    spec.ground.forEach(function(f) {
      var e=span(f),trim=color('frame',spec.style.frame),z=e.z+.1;
      if(f.kind==='porch') {
        box(e.w,.18,3,e.x,.02,z+1.5,0xb3aa94);
        if(f.roof==='gable'){
          emit(detailed?'roof_gable':'gable',[3.5,1.1,e.w+.3],[e.x,3.8,z+1.5],Math.PI/2,color('roof',spec.style.roof));
          emit('caps',[3.5,1.1,e.w+.3],[e.x,3.8,z+1.5],Math.PI/2,color('body',spec.blocks[e.block].body));
        }else box(e.w,.18,3.3,e.x,3.8,z+1.5,color('roof',spec.style.roof));
        [-1,1].forEach(function(s){box(f.roof==='gable'?.4:.18,3.7,f.roof==='gable'?.4:.18,e.x+s*(e.w/2-.3),1.9,z+2.8,color('trim',spec.style.trim));if(f.roof==='gable')box(.65,1.2,.65,e.x+s*(e.w/2-.3),.6,z+2.8,0x9b9685);});
      } else if(f.kind==='garage_door') {
        box(e.w-.3,3.8,.16,e.x,1.9,z,0xd4d1c6);
        for(var row=1;row<4;row++) {
          if(f.style==='glass')box(e.w-.6,.6,.04,e.x,row*.85,z+.11,0x354b54);
          else box(e.w-.4,.045,.02,e.x,row*.85,z+.1,0x9b9c93);
        }
      } else if(f.kind==='door') {
        var w=f.count===2?2.5:1.4;
        box(w+.25,3.4,.14,e.x,1.7,z,trim);
        box(w,3.2,.17,e.x,1.6,z+.08,color('door',spec.style.door));
        if(f.count===2) box(.04,3.2,.04,e.x,1.6,z+.2,trim);
      } else if(f.kind==='window') {
        var count=f.count||1,unit=Math.min(1.3,(e.w-.7)/count),y=3+(f.story===2?e.h:0);
        for(var i=0;i<count;i++) {
          var x=e.x+(i-(count-1)/2)*(unit+.15);
          box(unit+.18,1.95,.12,x,y,z,trim);box(unit,1.75,.14,x,y,z+.06,0x354b54);
          box(.055,1.75,.04,x,y,z+.15,trim);box(unit,.055,.04,x,y,z+.15,trim);
        }
        if(f.shutters) [-1,1].forEach(function(s){box(.27,1.95,.12,e.x+s*(count*(unit+.15)/2+.17),y,z,trim);});
      }
    });
    spec.roof.forEach(function(f) {
      var e=span(f),rise=e.w*.38;
      emit(detailed?'roof_gable':'gable',[3,rise,e.w],[e.x,e.h,e.z-.7],Math.PI/2,color('roof',spec.style.roof));
      emit('caps',[3,rise,e.w],[e.x,e.h,e.z-.7],Math.PI/2,color('body',spec.blocks[e.block].body));
      if(f.window) box(.65,.8,.15,e.x,e.h+.6,e.z+.85,0x354b54);
    });
  }

  // Freeze a finished parametric exterior. No second house build, household
  // state, cutaway groups or lights. Geometry/UV/AO are copied; maps are borrowed.
  function exteriorKit(parts, stats) {
    // Keep disposal outside the capture's scope: a kit must not retain its
    // temporary source scene, attribute work arrays or material buckets.
    stats.parts=parts;
    stats.dispose=function(){parts.forEach(function(p){p.geometry.dispose();p.material.dispose();});};
    return stats;
  }
  function captureExterior(T,root,excluded,parcel) {
    root.updateMatrixWorld(true);
    var skip=new Set(excluded||[]),buckets={},inverse=root.matrixWorld.clone().invert();
    var matrix=new T.Matrix4(),instance=new T.Matrix4(),normal=new T.Matrix3(),v=new T.Vector3(),tint=new T.Color();
    var sourceMeshes=0,sourceInstances=0;
    root.updateMatrixWorld(true);
    root.traverse(function(o){
      if(!o.isMesh || !o.geometry)return;
      for(var parent=o;parent;parent=parent.parent){
        if(skip.has(parent) || !parent.visible || parent.userData.maskOnly || parent.userData.noMirror)return;
        if(parent===root)break;
      }
      // Runtime labels and screens are not architectural detail.
      if(o.userData.zone || o.userData.text)return;
      var g=o.geometry.index?o.geometry.toNonIndexed():o.geometry;
      var attrs=g.attributes,groups=g.groups.length?g.groups:[{start:0,count:attrs.position.count,materialIndex:0}];
      var mats=Array.isArray(o.material)?o.material:[o.material];
      sourceMeshes++;sourceInstances+=o.isInstancedMesh?o.count:1;
      for(var inst=0;inst<(o.isInstancedMesh?o.count:1);inst++){
        matrix.copy(inverse).multiply(o.matrixWorld);tint.setHex(0xffffff);
        if(o.isInstancedMesh){o.getMatrixAt(inst,instance);matrix.multiply(instance);if(o.instanceColor)o.getColorAt(inst,tint);}
        normal.getNormalMatrix(matrix);var reverse=matrix.determinant()<0;
        groups.forEach(function(part){
          var material=mats[Array.isArray(o.material)?(part.materialIndex||0):0];if(!material || !material.visible)return;
          var key=[material.type,material.map&&material.map.uuid,material.normalMap&&material.normalMap.uuid,
            material.normalScale&&material.normalScale.toArray().join(','),material.alphaMap&&material.alphaMap.uuid,material.emissiveMap&&material.emissiveMap.uuid,material.envMap&&material.envMap.uuid,material.roughness,material.metalness,material.transparent,material.opacity,material.alphaTest,
            material.emissive&&material.emissive.getHex(),material.emissiveIntensity,material.side,
            material.blending,material.depthWrite,o.castShadow,o.renderOrder].join('|');
          var b=buckets[key];
          if(!b){
            var m=material.clone();m.color.setHex(0xffffff);m.vertexColors=true;
            b=buckets[key]={material:m,castShadow:o.castShadow,renderOrder:o.renderOrder,position:[],normal:[],uv:[],color:[]};
          }
          for(var i=part.start;i<Math.min(part.start+part.count,attrs.position.count);i++){
            if(parcel && (i-part.start)%3===0){
              var front=0,top=-Infinity;
              for(var corner=0;corner<3;corner++){v.fromBufferAttribute(attrs.position,i+corner).applyMatrix4(matrix);front+=v.z/3;top=Math.max(top,v.y);}
              // Shared streets are built once by the neighborhood, not per lot.
              if((front>=parcel.front && top<.5) || (parcel.buildingOnly && top<.05)){i+=2;continue;}
            }
            var vertex=i,cornerIndex=(i-part.start)%3;
            if(reverse && cornerIndex)vertex=i+(cornerIndex===1?1:-1);
            v.fromBufferAttribute(attrs.position,vertex).applyMatrix4(matrix);b.position.push(v.x,v.y,v.z);
            if(attrs.normal)v.fromBufferAttribute(attrs.normal,vertex).applyMatrix3(normal).normalize();else v.set(0,1,0);
            b.normal.push(v.x,v.y,v.z);
            b.uv.push(attrs.uv?attrs.uv.getX(vertex):0,attrs.uv?attrs.uv.getY(vertex):0);
            var c=material.color,vc=material.vertexColors&&attrs.color;
            b.color.push(c.r*tint.r*(vc?vc.getX(vertex):1),c.g*tint.g*(vc?vc.getY(vertex):1),c.b*tint.b*(vc?vc.getZ(vertex):1));
          }
        });
      }
      if(g!==o.geometry)g.dispose();
    });
    var parts=Object.keys(buckets).filter(function(key){if(buckets[key].position.length)return true;buckets[key].material.dispose();return false;}).map(function(key){
      var b=buckets[key],g=new T.BufferGeometry();
      ['position','normal','uv','color'].forEach(function(k){g.setAttribute(k,new T.Float32BufferAttribute(b[k],k==='uv'?2:3));});
      g.computeBoundingSphere();return {geometry:g,material:b.material,castShadow:b.castShadow,renderOrder:b.renderOrder};
    });
    var geometryHash=2166136261;
    parts.forEach(function(p){var a=p.geometry.attributes.position.array;for(var i=0;i<a.length;i++)geometryHash=Math.imul(geometryHash^Math.round(a[i]*1000),16777619);});
    return exteriorKit(parts,{geometrySignature:(geometryHash>>>0).toString(16),sourceMeshes:sourceMeshes,sourceInstances:sourceInstances,
      triangles:parts.reduce(function(n,p){return n+p.geometry.attributes.position.count/3;},0)});
  }

  function paintedHorizon(T) {
    if(typeof document==='undefined')return null;
    var canvas=document.createElement('canvas');canvas.width=4096;canvas.height=512;
    var g=canvas.getContext('2d'),W=canvas.width,H=canvas.height;
    var ground=g.createLinearGradient(0,280,0,H);ground.addColorStop(0,'#81917a');ground.addColorStop(1,'#81966d');
    g.fillStyle=ground;g.fillRect(0,290,W,H-290);
    // Periodic positions and wrapped copies keep the panorama seam invisible.
    for(var layer=0;layer<3;layer++)for(var i=0;i<100;i++){
      var x=i*W/100,base=300+layer*32,h=18+(i*17+layer*11)%24,w=24+(i*13)%22;
      [-W,0,W].forEach(function(offset){
        var px=x+offset;
        g.fillStyle=['#94a397','#778d75','#5e7a58'][layer];
        g.beginPath();g.ellipse(px,base-h,18+(i%4)*3,h,0,0,Math.PI*2);g.fill();
        if(i%3!==0){
          g.fillStyle=['#bec0ad','#b8b49c','#aca992'][layer];g.fillRect(px,base-h*.55,w,h*.7);
          g.fillStyle=['#89928c','#777c73','#666c64'][layer];g.beginPath();g.moveTo(px-3,base-h*.55);g.lineTo(px+w*.5,base-h*1.2);g.lineTo(px+w+3,base-h*.55);g.fill();
          g.fillStyle='#657770';g.fillRect(px+5,base-h*.4,4,6);g.fillRect(px+w-9,base-h*.4,4,6);
        }
      });
    }
    // Match canvasTex in the active renderer (linear canvas color convention).
    var texture=new T.CanvasTexture(canvas);
    texture.wrapS=T.RepeatWrapping;
    var material=new T.MeshBasicMaterial({map:texture,color:0xcdcdcd,toneMapped:false,transparent:true,alphaTest:.02,side:T.BackSide,depthWrite:false});
    var mesh=new T.Mesh(new T.CylinderGeometry(250,250,90,96,1,true),material);
    mesh.name='neighborhood-horizon';mesh.position.y=35;mesh.userData.yard=true;mesh.raycast=function(){};
    return mesh;
  }

  function build(T,canonical,envelopes,palette,materialFactory,nearTemplate,layout,focus) {
    var group=new T.Group();group.name='neighborhood';group.userData.yard=true;
    var lots=plan(canonical,layout),buckets={},pieces=0;
    var terrainMeshes=[],terrainMaterials={},treeCount=0;
    lots.forEach(function(l){
      var size=l.scale;
      l.transform={sx:size,sy:size,sz:size,x:l.x,z:l.z};
      if(!l.footprint)return;
      // Fit the walls, not the much larger authored garden. The body center
      // is off-origin and reverses when mirrored; compensate before rotation.
      var west=Math.min(envelopes.main.west,envelopes.garage.west),east=Math.max(envelopes.main.east,envelopes.garage.east);
      var north=Math.min(envelopes.main.north,envelopes.garage.north);
      var south=Math.max(envelopes.main.south+l.spec.blocks.main.depth,envelopes.garage.south+l.spec.blocks.garage.depth);
      var sx=l.footprint.width/(east-west),sz=l.footprint.depth/(south-north),sy=Math.sqrt(sx*sz);
      var cx=(west+east)/2*sx*(l.spec.mirror?-1:1),cz=(north+south)/2*sz,c=Math.cos(l.rotation),s=Math.sin(l.rotation);
      l.transform={sx:sx,sy:sy,sz:sz,x:l.x-cx*c-cz*s,z:l.z+cx*s-cz*c};
    });
    var kits=new Map(),lotKits={};
    lots.forEach(function(l,i){
      if(!nearTemplate || l.detail!=='near')return;
      var spec=clone(l.spec);spec.mirror=false;
      var key=JSON.stringify(spec)+'|'+!!l.footprint;
      if(!kits.has(key))kits.set(key,typeof nearTemplate==='function'?nearTemplate(spec,!!l.footprint):nearTemplate);
      lotKits[i]=kits.get(key);
    });
    var uniqueKits=Array.from(new Set(kits.values()));
    function add(kind,size,pos,turn,color,lot) {
      (buckets[kind]||(buckets[kind]=[])).push({size:size,pos:pos,turn:turn,color:color,lot:lot});pieces++;
    }
    var mapScale=layout&&layout.homeCalibration?layout.homeCalibration.scale:1;
    var sceneryRadius=270;
    if(layout && layout.source==='mapbox'){
      layout.roads.forEach(function(line){line.forEach(function(p){sceneryRadius=Math.max(sceneryRadius,Math.hypot(p[0],p[1])+30);});});
      (layout.terrain||[]).forEach(function(f){f.rings.forEach(function(r){r.forEach(function(p){sceneryRadius=Math.max(sceneryRadius,Math.hypot(p[0],p[1])+15);});});});
      lots.forEach(function(l){sceneryRadius=Math.max(sceneryRadius,Math.hypot(l.x,l.z)+(l.footprint?Math.hypot(l.footprint.width,l.footprint.depth)/2:35*l.scale)+30);});
    }
    add('box',[sceneryRadius*2,.15,sceneryRadius*2],[0,-.62,0],0,0x81966d,-1);
    var terrain=layout&&layout.terrain||[];
    var landColors={grass:0x8a9d72,crop:0xa5a178,snow:0xd8e3df,park:0x91a778,scrub:0x758d60,wood:0x60794f,water:0x568e9d};
    terrain.forEach(function(f,index){
      function path(r,Type){var p=new Type();r.forEach(function(v,i){if(i)p.lineTo(v[0],-v[1]);else p.moveTo(v[0],-v[1]);});return p;}
      var shape=path(f.rings[0],T.Shape);f.rings.slice(1).forEach(function(r){shape.holes.push(path(r,T.Path));});
      var geometry=new T.ShapeGeometry(shape);
      if(!terrainMaterials[f.kind])terrainMaterials[f.kind]=new T.MeshStandardMaterial({color:landColors[f.kind],roughness:f.kind==='water'?.3:1,metalness:f.kind==='water'?.12:0,side:T.DoubleSide});
      var mesh=new T.Mesh(geometry,terrainMaterials[f.kind]);mesh.rotation.x=-Math.PI/2;
      mesh.position.y=-.53+['grass','crop','snow','park','scrub','wood','water'].indexOf(f.kind)*.008;
      mesh.name='mapped-'+f.kind+'-'+index;mesh.userData.yard=true;mesh.receiveShadow=true;mesh.raycast=function(){};
      terrainMeshes.push(mesh);group.add(mesh);
    });
    function insideRing(x,z,ring){var yes=false;for(var i=0,j=ring.length-1;i<ring.length;j=i++){
      var a=ring[i],b=ring[j];if((a[1]>z)!==(b[1]>z) && x<(b[0]-a[0])*(z-a[1])/(b[1]-a[1])+a[0])yes=!yes;
    }return yes;}
    function insideLand(x,z,f){return insideRing(x,z,f.rings[0])&&!f.rings.slice(1).some(function(r){return insideRing(x,z,r);});}
    var woods=terrain.filter(function(f){return f.kind==='wood'||f.kind==='scrub';}),water=terrain.filter(function(f){return f.kind==='water';});
    if(woods.length){
      var candidates=[],step=11*mapScale;
      for(var gx=-sceneryRadius;gx<sceneryRadius;gx+=step)for(var gz=-sceneryRadius;gz<sceneryRadius;gz+=step){
        var seed=Math.sin(gx*12.9898+gz*78.233)*43758.5453,noise=seed-Math.floor(seed);
        var x=gx+(noise-.5)*step*.75,z=gz+(Math.sin(seed)*.5)*step*.75;
        if(Math.abs(x)<30&&z>-24&&z<34)continue;
        if(!woods.some(function(f){return insideLand(x,z,f);})||water.some(function(f){return insideLand(x,z,f);}))continue;
        if(lots.some(function(l){var dx=x-l.x,dz=z-l.z,c=Math.cos(l.rotation),s=Math.sin(l.rotation);
          return Math.abs(dx*c-dz*s)<(l.footprint?l.footprint.width/2:26*l.scale)+4*mapScale&&Math.abs(dx*s+dz*c)<(l.footprint?l.footprint.depth/2:24*l.scale)+4*mapScale;
        }))continue;
        if((layout.roads||[]).some(function(line){var a=line[0],b=line[1],dx=b[0]-a[0],dz=b[1]-a[1],len=dx*dx+dz*dz;
          var t=Math.max(0,Math.min(1,((x-a[0])*dx+(z-a[1])*dz)/len));return Math.hypot(x-a[0]-t*dx,z-a[1]-t*dz)<7*mapScale;
        }))continue;
        candidates.push({x:x,z:z,n:noise});
      }
      candidates.sort(function(a,b){return Math.hypot(a.x,a.z)-Math.hypot(b.x,b.z);});
      candidates.slice(0,350).forEach(function(p){
        var h=(5.5+p.n*3)*mapScale,w=(4+p.n*2)*mapScale;
        add('box',[.5*mapScale,h*.6,.5*mapScale],[p.x,h*.3-.5,p.z],0,0x66523a,-1);
        add('tree',[w,h*.8,w],[p.x,h*.65-.5,p.z],0,p.n>.5?0x527444:0x42673c,-1);treeCount++;
      });
    }
    if(layout && layout.source==='mapbox') {
      layout.roads.forEach(function(segment){
        var a=segment[0],b=segment[1],dx=b[0]-a[0],dz=b[1]-a[1],length=Math.hypot(dx,dz),turn=-Math.atan2(dz,dx);
        // Overlapping round ends seal bends/junctions without a second renderer.
        add('box',[length,.12,7.4*mapScale],[(a[0]+b[0])/2,-.40,(a[1]+b[1])/2],turn,0xbebbb0,-1);
        add('box',[length,.14,5*mapScale],[(a[0]+b[0])/2,-.36,(a[1]+b[1])/2],turn,0x4a4f55,-1);
        [a,b].forEach(function(p){add('disc',[7.4*mapScale,.12,7.4*mapScale],[p[0],-.40,p[1]],0,0xbebbb0,-1);add('disc',[5*mapScale,.14,5*mapScale],[p[0],-.36,p[1]],0,0x4a4f55,-1);});
      });
    } else [-203.5,-87.5,28.5,144.5,260.5].forEach(function(z){
      // Keep the active parcel's existing road and curb uncovered.
      if(z===28.5){
        [-1,1].forEach(function(side){add('box',[245,.38,5],[side<0?-147:148,-.5,z],0,0x4a4f55,-1);});
      }else add('box',[540,.38,5],[0,-.5,z],0,0x4a4f55,-1);
      [-1,1].forEach(function(side){add('box',[540,.12,1.2],[0,-.29,z+side*3.1],0,0xbebbb0,-1);});
      for(var x=-266;x<270;x+=7){if(z===28.5 && x>-25 && x<26)continue;add('box',[3,.02,.12],[x,-.30,z],0,0xe0d7ae,-1);}
    });
    lots.forEach(function(lot,index) {
      function emit(kind,size,pos,turn,c) {add(kind,size,pos,turn,c,index);}
      if(nearTemplate && lot.detail==='near')return;
      exterior(lot.spec,envelopes,palette,function(kind,size,pos,turn,c){
        emit(kind,size,pos,turn,c);
      },lot.detail==='near');
      if(lot.footprint)return; // No fixed-size yard attached to a mapped building.
      emit('box',[50,.38,44],[.5,-.50,4],0,0x81966d);
      emit('box',[5,.10,18],[-12,-.25,17],0,0xb0afa8);
      emit('box',[1.5,.10,12],[3,-.24,20],0,0xc8bfae);
      [-20,20].forEach(function(x){
        emit('box',[.4,3,.4],[x,1.5,-7],0,0x66513b);
        emit('tree',[4,5,4],[x,4,-7],0,0x4d7041);
        if(lot.detail==='near'){
          [-1,1].forEach(function(a){emit('tree',[3.5,3.5,3.5],[x+a*1.2,4.3,-7+a],0,a<0?0x638547:0x50723e);});
          if(x<0)for(var f=-18;f<19;f+=2)emit('box',[.12,1.2,.12],[f,.6,-16],0,0xd8d3be);
          if(x<0)emit('box',[38,.12,.12],[0,.85,-16],0,0xd8d3be);
        }
        emit('tree',[1.3,1.3,1.3],[x*.55,.65,18],0,0x4d7041);
      });
    });
    function roofGeometry(hip,caps) {
      var g=new T.BufferGeometry(),v=[],uv=[];
      var a=[-.5,0,-.5],b=[.5,0,-.5],c=[.5,0,.5],d=[-.5,0,.5],p=[hip?-.25:-.5,1,0],q=[hip?.25:.5,1,0];
      function tri(x,y,z){v.push.apply(v,x.concat(y,z));[x,y,z].forEach(function(a){uv.push(a[0]+.5,caps?a[1]:Math.abs(a[2])*2);});}
      if(!caps){tri(a,p,q);tri(a,q,b);tri(d,c,q);tri(d,q,p);}
      if(hip||caps){tri(a,d,p);tri(b,q,c);}
      g.setAttribute('position',new T.Float32BufferAttribute(v,3));g.setAttribute('uv',new T.Float32BufferAttribute(uv,2));g.computeVertexNormals();return g;
    }
    var geometries={box:new T.BoxGeometry(1,1,1),disc:new T.CylinderGeometry(.5,.5,1,16),gable:roofGeometry(false),caps:roofGeometry(false,true),hip:roofGeometry(true),tree:new T.IcosahedronGeometry(.5,1)};
    var materials={};
    function materialFor(kind){
      var surface=kind.indexOf('wall_')===0?kind.slice(5):kind.indexOf('roof_')===0?'shingle':'plain';
      if(!materials[surface]){
        var m=materialFactory?materialFactory(surface):new T.MeshStandardMaterial({color:0xffffff,roughness:.95,envMapIntensity:.1});
        m.side=T.DoubleSide;materials[surface]=m;
      }
      return materials[surface];
    }
    var matrices=[],meshes=[],dummy=new T.Object3D(),placement=new T.Object3D();
    function place(l){var p=l.transform;placement.position.set(p.x,-.31*(1-p.sy),p.z);placement.rotation.set(0,l.rotation,0);placement.scale.set(p.sx,p.sy,p.sz);placement.updateMatrix();}
    Object.keys(buckets).forEach(function(kind){
      var shape=kind.indexOf('wall_')===0?'box':kind.replace('roof_','');
      var rows=buckets[kind],mesh=new T.InstancedMesh(geometries[shape],materialFor(kind),rows.length),saved=[];
      mesh.frustumCulled=false;mesh.receiveShadow=true;mesh.userData.yard=true;
      mesh.raycast=function(){}; // Scenery never participates in room picking.
      rows.forEach(function(r,i){
        dummy.position.set.apply(dummy.position,r.pos);dummy.rotation.set(0,r.turn,0);dummy.scale.set.apply(dummy.scale,r.size);dummy.updateMatrix();
        var m=dummy.matrix.clone();
        if(r.lot>=0){
          var l=lots[r.lot];place(l);
          // Negative determinant is unsupported by InstancedMesh: reflect local
          // position/rotation instead, so every instance retains positive scale.
          if(l.spec.mirror){dummy.position.x=-r.pos[0];dummy.rotation.y=-r.turn;dummy.updateMatrix();m.copy(dummy.matrix);}
          m.premultiply(placement.matrix);
        }
        mesh.setMatrixAt(i,m);mesh.setColorAt(i,new T.Color(r.color));saved.push(m);
      });
      group.add(mesh);meshes.push(mesh);matrices.push({mesh:mesh,rows:rows,saved:saved});
    });
    // One finished exterior geometry per material, instanced across the near ring.
    // Mirrored geometry gets reversed triangle winding (negative instance scales
    // are unsupported by THREE.InstancedMesh).
    var reflected=[];
    uniqueKits.forEach(function(kit){kit.parts.forEach(function(part){
      [false,true].forEach(function(mirror){
        var rows=[];lots.forEach(function(l,i){if(lotKits[i]===kit && l.spec.mirror===mirror)rows.push({lot:i});});
        if(!rows.length)return;
        var geometry=part.geometry;
        if(mirror){
          geometry=geometry.clone();geometry.scale(-1,1,1);
          Object.keys(geometry.attributes).forEach(function(k){var a=geometry.attributes[k];for(var v=0;v<a.count;v+=3)for(var c=0;c<a.itemSize;c++){var first=(v+1)*a.itemSize+c,last=(v+2)*a.itemSize+c,tmp=a.array[first];a.array[first]=a.array[last];a.array[last]=tmp;}a.needsUpdate=true;});
          reflected.push(geometry);
        }
        var mesh=new T.InstancedMesh(geometry,part.material,rows.length),saved=[];
        mesh.castShadow=part.castShadow;mesh.receiveShadow=true;mesh.renderOrder=part.renderOrder;
        mesh.userData.yard=true;mesh.userData.nearExterior=true;mesh.frustumCulled=false;mesh.raycast=function(){};
        rows.forEach(function(r,i){place(lots[r.lot]);saved.push(placement.matrix.clone());mesh.setMatrixAt(i,placement.matrix);});
        group.add(mesh);meshes.push(mesh);matrices.push({mesh:mesh,rows:rows,saved:saved});pieces+=rows.length;
      });
    });
    });
    var horizon=paintedHorizon(T);if(horizon){
      if(layout && layout.source==='mapbox')horizon.scale.set(sceneryRadius/250,1,sceneryRadius/250);
      group.add(horizon);
    }
    // Bounds come from rendered geometry, including roof height and transforms.
    var bounds=lots.map(function(){return new T.Box3();});
    focus=focus||{west:envelopes.garage.west,east:envelopes.main.east,north:envelopes.main.north,south:envelopes.main.south,top:16};
    var focusSamples=[];
    [focus.west+1,(focus.west+focus.east)/2,focus.east-1].forEach(function(x){
      [focus.north+1,(focus.north+focus.south)/2,focus.south-1].forEach(function(z){
        [2,focus.top/2,focus.top-.5].forEach(function(y){focusSamples.push(new T.Vector3(x,y,z));});
      });
    });
    matrices.forEach(function(b){
      if(!b.mesh.geometry.boundingBox)b.mesh.geometry.computeBoundingBox();
      b.rows.forEach(function(r,i){if(r.lot>=0)bounds[r.lot].union(b.mesh.geometry.boundingBox.clone().applyMatrix4(b.saved[i]));});
    });
    var hidden='',visibleLots=lots.length,fadedLots=0,zero=new T.Matrix4().makeScale(0,0,0),ghostMaterials=new Map(),ghosts=[];
    var ray=new T.Ray(),hit=new T.Vector3(),color=new T.Color();
    function translucent(b){
      if(b.ghost)return b.ghost;
      var source=b.mesh.material,material=ghostMaterials.get(source);
      if(!material){material=source.clone();material.transparent=true;material.opacity=source.opacity*.2;material.alphaTest=source.alphaTest*.2;material.depthWrite=false;ghostMaterials.set(source,material);}
      var mesh=new T.InstancedMesh(b.mesh.geometry,material,b.rows.length);
      mesh.frustumCulled=false;mesh.receiveShadow=false;mesh.castShadow=false;mesh.renderOrder=b.mesh.renderOrder;
      mesh.userData.yard=true;mesh.userData.occlusionGhost=true;mesh.raycast=function(){};mesh.count=0;
      group.add(mesh);ghosts.push(mesh);b.ghost=mesh;return mesh;
    }
    function update(camera,target,outside) {
      group.visible=outside;if(!outside)return;
      var blocked=bounds.map(function(box){
        return focusSamples.some(function(p){ray.origin.copy(camera);ray.direction.copy(p).sub(camera).normalize();
          return ray.intersectBox(box,hit)!==null&&hit.distanceTo(camera)<p.distanceTo(camera)-.5;
        });
      });
      var key=blocked.join(',');if(key===hidden)return;hidden=key;
      fadedLots=blocked.filter(Boolean).length;
      matrices.forEach(function(b){var count=0;
        b.rows.forEach(function(r,i){var fade=r.lot>=0&&blocked[r.lot];b.mesh.setMatrixAt(i,fade?zero:b.saved[i]);
          if(fade){var ghost=translucent(b);ghost.setMatrixAt(count,b.saved[i]);if(b.mesh.instanceColor){b.mesh.getColorAt(i,color);ghost.setColorAt(count,color);}count++;}
        });
        b.mesh.instanceMatrix.needsUpdate=true;
        if(b.ghost){b.ghost.count=count;b.ghost.visible=count>0;b.ghost.instanceMatrix.needsUpdate=true;if(b.ghost.instanceColor)b.ghost.instanceColor.needsUpdate=true;}
      });
    }
    return {group:group,update:update,setNight:function(n){if(horizon)horizon.material.color.setHex(n?0x435063:0xcdcdcd);},stats:function(){return {homeCalibration:layout&&layout.homeCalibration||null,sceneryRadius:sceneryRadius,layoutSource:layout&&layout.source==='mapbox'?'mapbox':'generated',roadSegments:layout&&layout.roads?layout.roads.length:0,lots:lots.length,visibleLots:visibleLots,fadedLots:fadedLots,terrainPolygons:terrainMeshes.length,terrainTrees:treeCount,visible:group.visible,nearSource:nearTemplate?'parametric-exterior':'simplified',nearDesigns:uniqueKits.length,nearGeometry:uniqueKits.map(function(k){return k.geometrySignature;}),nearTemplate:nearTemplate?{meshes:uniqueKits.reduce(function(n,k){return n+k.sourceMeshes;},0),instances:uniqueKits.reduce(function(n,k){return n+k.sourceInstances;},0),triangles:uniqueKits.reduce(function(n,k){return n+k.triangles;},0)}:null,nearLots:lots.filter(function(l){return l.detail==='near';}).length,farLots:lots.filter(function(l){return l.detail==='far';}).length,horizon:!!horizon,batches:meshes.length+terrainMeshes.length+ghosts.filter(function(m){return m.visible;}).length+(horizon?1:0),instances:pieces,
      triangles:meshes.concat(ghosts.filter(function(m){return m.visible;})).reduce(function(n,m){return n+(m.geometry.index?m.geometry.index.count:m.geometry.attributes.position.count)/3*m.count;},terrainMeshes.reduce(function(n,m){return n+m.geometry.index.count/3;},horizon?horizon.geometry.index.count/3:0)),
      placements:lots.map(function(l){return {id:l.id,x:l.x,z:l.z,rotation:l.rotation,detail:l.detail,scale:l.scale,footprint:l.footprint,transform:l.transform,style:l.style};})};},
      dispose:function(){terrainMeshes.forEach(function(m){m.geometry.dispose();});Object.keys(terrainMaterials).forEach(function(k){terrainMaterials[k].dispose();});ghosts.forEach(function(m){m.dispose();});ghostMaterials.forEach(function(m){m.dispose();});meshes.forEach(function(m){m.dispose();});Object.keys(geometries).forEach(function(k){geometries[k].dispose();});Object.keys(materials).forEach(function(k){materials[k].dispose();});reflected.forEach(function(g){g.dispose();});uniqueKits.forEach(function(k){k.dispose();});if(horizon){horizon.geometry.dispose();horizon.material.map.dispose();horizon.material.dispose();}group.clear();}};
  }
  root.ChauffeurNeighborhood={plan:plan,fitLayout:fitLayout,exterior:exterior,captureExterior:captureExterior,build:build};
})(typeof window!=='undefined'?window:globalThis);
