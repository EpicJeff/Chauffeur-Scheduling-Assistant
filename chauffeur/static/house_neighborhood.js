/* Deterministic, exterior-only facade instances. No household state or frame loop. */
(function (root) {
  'use strict';
  function clone(v) { return JSON.parse(JSON.stringify(v)); }
  function plan(canonical) {
    var placements = [[-51,0,0],[51,0,0],[-51,58,Math.PI],[0,58,Math.PI],[51,58,Math.PI]];
    return placements.map(function (p,i) {
      var s=clone(canonical);
      s.mirror=i%2===1;
      s.style={roof:['charcoal','weathered','brown'][i%3],frame:i%2?'black':'white',door:i%2?'red':'wood',trim:'white'};
      s.roof=[]; s.upper=[]; s.ground=[];
      ['garage','main'].forEach(function (name) {
        var b=s.blocks[name]; b.body=['sage','cream_brick','slate','tan','white'][i];
        b.cladding=['lap','brick','batten'][i%3]; b.depth=i%2?1.2:0;
        b.roof={form:i===2?'hip':'gable',ridge:name==='garage'&&i%2?'z':'x',pitch_deg:27+i*2};
      });
      s.blocks.garage.orientation='front';
      s.ground.push({slot:0,span:3,kind:'garage_door',style:'panel',leaves:2}, {slot:10,span:2,kind:'door',count:i%2?2:1});
      [7,13,16].forEach(function (slot) { s.ground.push({slot:slot,span:2,kind:'window',size:'standard',count:slot===13?2:1,shutters:i%2===0,story:1}); });
      if (i!==2) s.ground.push({slot:9,span:5,kind:'porch',type:'covered',roof:'shed'});
      if (i%2===0) {
        s.upper.push({slot:7,span:7,roof:clone(s.blocks.main.roof)});
        [8,10,12].forEach(function (slot) { s.ground.push({slot:slot,span:1,kind:'window',size:'standard',shutters:false,story:2}); });
      }
      if (i===1 || i===4) s.roof.push({slot:3,span:3,kind:'gable',window:true});
      return {id:'neighbor-'+i,x:p[0],z:p[1],rotation:p[2],spec:s};
    });
  }

  // Same facade schema and physical block envelopes as the active house. This
  // projection builds closed exterior solids, omitting interiors and cutaway fabric.
  function exterior(spec,envelopes,palette,emit) {
    function color(role,value) { return palette[role][value] || palette[role][Object.keys(palette[role])[0]]; }
    function box(w,h,d,x,y,z,c) { emit('box',[w,h,d],[x,y,z],0,c); }
    function roof(b,r,y) {
      var w=b.east-b.west+.6,d=b.south-b.north+.6,turn=r.ridge==='z'?Math.PI/2:0;
      var cross=turn?w:d, rise=Math.tan(r.pitch_deg*Math.PI/180)*cross/2;
      var dims=turn?[d,rise,w]:[w,rise,d],pos=[(b.west+b.east)/2,y,(b.north+b.south)/2];
      emit(r.form==='hip'?'hip':'gable',dims,pos,turn,color('roof',spec.style.roof));
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
      box(b.east-b.west,b.eave,b.south-b.north,(b.west+b.east)/2,b.eave/2,(b.north+b.south)/2,color('body',v.body));
      roof(b,v.roof,b.eave);
      // Low-cost siding courses keep these from reading as untextured cubes.
      if(v.cladding==='lap') for(var y=.6;y<b.eave;y+=.6) box(b.east-b.west,.035,.05,(b.west+b.east)/2,y,b.south+.025,color('trim',spec.style.trim));
      var frame=color('frame',spec.style.frame),side=name==='main'?b.east+.06:b.west-.06;
      [-2,5].forEach(function(z){box(.14,2,1.4,side,3,z,frame);box(.16,1.8,1.2,side+(name==='main'?.04:-.04),3,z,0x354b54);});
      [.25,.7].forEach(function(t){var x=b.west+(b.east-b.west)*t;box(1.5,2,.14,x,3,b.north-.08,frame);box(1.3,1.8,.16,x,3,b.north-.12,0x354b54);});
    });
    spec.upper.forEach(function(u) {
      var e=span(u),base=envelopes[e.block],b={west:e.x-e.w/2,east:e.x+e.w/2,north:base.north,south:e.z};
      box(e.w,e.h,e.z-base.north,e.x,e.h*1.5,(e.z+base.north)/2,color('body',spec.blocks[e.block].body));
      roof(b,u.roof,e.h*2);
    });
    spec.ground.forEach(function(f) {
      var e=span(f),trim=color('frame',spec.style.frame),z=e.z+.1;
      if(f.kind==='porch') {
        box(e.w,.18,3,e.x,.02,z+1.5,0xb3aa94);
        box(e.w,.18,3.3,e.x,3.8,z+1.5,color('roof',spec.style.roof));
        [-1,1].forEach(function(s){box(.18,3.7,.18,e.x+s*(e.w/2-.2),1.9,z+2.8,color('trim',spec.style.trim));});
      } else if(f.kind==='garage_door') {
        box(e.w-.3,3.8,.16,e.x,1.9,z,0xd4d1c6);
        for(var row=1;row<4;row++) box(e.w-.4,.045,.02,e.x,row*.85,z+.1,0x9b9c93);
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
      emit('gable',[3,rise,e.w],[e.x,e.h,e.z-.7],Math.PI/2,color('roof',spec.style.roof));
      if(f.window) box(.65,.8,.15,e.x,e.h+.6,e.z+.85,0x354b54);
    });
  }

  function build(T,canonical,envelopes,palette,materialFactory) {
    var group=new T.Group();group.name='neighborhood';group.userData.yard=true;
    var lots=plan(canonical),buckets={},pieces=0;
    function add(kind,size,pos,turn,color,lot) {
      (buckets[kind]||(buckets[kind]=[])).push({size:size,pos:pos,turn:turn,color:color,lot:lot});pieces++;
    }
    add('box',[153,.15,104],[.5,-.62,30],0,0x81966d,-1);
    // Extend the existing street without overlaying its interactive curb/bus.
    [-1,1].forEach(function(side){
      add('box',[51,.38,5],[side<0?-50:51,-.5,28.5],0,0x4a4f55,-1);
      add('box',[51,.12,1.2],[side<0?-50:51,-.29,25.4],0,0xbebbb0,-1);
      for(var x=29;x<76;x+=7)add('box',[3,.02,.12],[x*side,-.30,28.5],0,0xe0d7ae,-1);
    });
    add('box',[153,.12,1.2],[.5,-.29,31.7],0,0xbebbb0,-1);
    lots.forEach(function(lot,index) {
      function emit(kind,size,pos,turn,c) {add(kind,size,pos,turn,c,index);}
      exterior(lot.spec,envelopes,palette,function(kind,size,pos,turn,c){
        emit(kind,size.map(function(v){return v*.8;}),pos.map(function(v){return v*.8;}),turn,c);
      });
      emit('box',[50,.38,44],[.5,-.50,4],0,0x81966d);
      emit('box',[5,.10,18],[-12,-.25,17],0,0xb0afa8);
      emit('box',[1.5,.10,12],[3,-.24,20],0,0xc8bfae);
      [-20,20].forEach(function(x){
        emit('box',[.4,3,.4],[x,1.5,-7],0,0x66513b);
        emit('tree',[4,5,4],[x,4,-7],0,0x4d7041);
        emit('tree',[1.3,1.3,1.3],[x*.55,.65,18],0,0x4d7041);
      });
    });
    function roofGeometry(hip,caps) {
      var g=new T.BufferGeometry(),v=[];
      var a=[-.5,0,-.5],b=[.5,0,-.5],c=[.5,0,.5],d=[-.5,0,.5],p=[hip?-.25:-.5,1,0],q=[hip?.25:.5,1,0];
      function tri(x,y,z){v.push.apply(v,x.concat(y,z));}
      if(!caps){tri(a,p,q);tri(a,q,b);tri(d,c,q);tri(d,q,p);}
      if(hip||caps){tri(a,d,p);tri(b,q,c);}
      g.setAttribute('position',new T.Float32BufferAttribute(v,3));g.computeVertexNormals();return g;
    }
    var geometries={box:new T.BoxGeometry(1,1,1),gable:roofGeometry(false),caps:roofGeometry(false,true),hip:roofGeometry(true),tree:new T.IcosahedronGeometry(.5,0)};
    var material=materialFactory?materialFactory():new T.MeshStandardMaterial({color:0xffffff,roughness:.95,envMapIntensity:.1});
    material.side=T.DoubleSide;
    var matrices=[],meshes=[],dummy=new T.Object3D(),placement=new T.Object3D();
    Object.keys(buckets).forEach(function(kind){
      var rows=buckets[kind],mesh=new T.InstancedMesh(geometries[kind],material,rows.length),saved=[];
      mesh.frustumCulled=false;mesh.receiveShadow=true;mesh.userData.yard=true;
      rows.forEach(function(r,i){
        dummy.position.set.apply(dummy.position,r.pos);dummy.rotation.set(0,r.turn,0);dummy.scale.set.apply(dummy.scale,r.size);dummy.updateMatrix();
        var m=dummy.matrix.clone();
        if(r.lot>=0){
          var l=lots[r.lot];placement.position.set(l.x,0,l.z);placement.rotation.set(0,l.rotation,0);placement.scale.set(l.spec.mirror?-1:1,1,1);placement.updateMatrix();
          // Negative determinant is unsupported by InstancedMesh: reflect local
          // position/rotation instead, so every instance retains positive scale.
          if(l.spec.mirror){dummy.position.x=-r.pos[0];dummy.rotation.y=-r.turn;dummy.updateMatrix();m.copy(dummy.matrix);placement.scale.x=1;placement.updateMatrix();}
          m.premultiply(placement.matrix);
        }
        mesh.setMatrixAt(i,m);mesh.setColorAt(i,new T.Color(r.color));saved.push(m);
      });
      group.add(mesh);meshes.push(mesh);matrices.push({mesh:mesh,rows:rows,saved:saved});
    });
    var hidden='',visibleLots=lots.length,zero=new T.Matrix4().makeScale(0,0,0);
    function update(camera,target,outside) {
      group.visible=outside;if(!outside)return;
      var dx=camera.x-target.x,dz=camera.z-target.z,len=dx*dx+dz*dz;
      var blocked=lots.map(function(l){
        var t=((l.x-target.x)*dx+(l.z-target.z)*dz)/len;
        var x=target.x+t*dx,z=target.z+t*dz;
        return t>0 && t<1.3 && Math.hypot(l.x-x,l.z-z)<24;
      });
      var key=blocked.join(',');if(key===hidden)return;hidden=key;
      visibleLots=blocked.filter(function(b){return !b;}).length;
      matrices.forEach(function(b){b.rows.forEach(function(r,i){b.mesh.setMatrixAt(i,r.lot>=0&&blocked[r.lot]?zero:b.saved[i]);});b.mesh.instanceMatrix.needsUpdate=true;});
    }
    return {group:group,update:update,stats:function(){return {lots:lots.length,visibleLots:visibleLots,visible:group.visible,batches:meshes.length,instances:pieces,
      triangles:meshes.reduce(function(n,m){return n+(m.geometry.index?m.geometry.index.count:m.geometry.attributes.position.count)/3*m.count;},0),
      placements:lots.map(function(l){return {id:l.id,x:l.x,z:l.z,rotation:l.rotation};})};},
      dispose:function(){meshes.forEach(function(m){m.dispose();});Object.keys(geometries).forEach(function(k){geometries[k].dispose();});material.dispose();group.clear();}};
  }
  root.ChauffeurNeighborhood={plan:plan,exterior:exterior,build:build};
})(typeof window!=='undefined'?window:globalThis);
