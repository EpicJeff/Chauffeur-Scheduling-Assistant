/* Constrained authoring recipe renderer. No eval, scripts or external resources.
   Server validates input. This builder is also used by the isolated preview worker. */
(function () {
  'use strict';
  window.HouseRecipe = {build:function(T, recipe, detail) {
    var group=new T.Group(), geometries=[], materials={}, nice=detail>=2, high=detail>=3;
    var palette={wood:0x926744,oak:0xc39b67,ivory:0xeee5d3,ink:0x292d30,brass:0xb99a57,sage:0x58978b,steel:0x858b8b};
    function mat(name) {
      if (!materials[name]) materials[name]=high ? new T.MeshStandardMaterial({color:palette[name],roughness:name==='brass'?.38:.72,metalness:name==='brass'?.65:0}) : new T.MeshLambertMaterial({color:palette[name]});
      return materials[name];
    }
    var expanded=[];
    recipe.parts.forEach(function(p){
      var repeated=p.repeat||{count:1,step:[0,0,0]};
      for(var i=0;i<repeated.count;i++){
        var copy=Object.assign({},p);
        function shifted(v){return v.map(function(n,k){return n+i*repeated.step[k];});}
        if(p.type==='rod'){copy.a=shifted(p.a);copy.b=shifted(p.b);}
        else copy.position=shifted(p.position);
        expanded.push(copy);
      }
    });
    expanded.forEach(function(p) {
      var s=p.size, geometry, pos=p.position||[0,0,0], rot=p.rotation||[0,0,0];
      if(p.type==='box') {
        var r=Math.min(.025,s[0]/8,s[1]/8,s[2]/8);
        if(nice && Math.min.apply(Math,s)>=.035) {
          var shape=new T.Shape();shape.moveTo(-s[0]/2+r,-s[1]/2+r);shape.lineTo(s[0]/2-r,-s[1]/2+r);shape.lineTo(s[0]/2-r,s[1]/2-r);shape.lineTo(-s[0]/2+r,s[1]/2-r);shape.closePath();
          geometry=new T.ExtrudeGeometry(shape,{depth:s[2]-2*r,bevelEnabled:true,bevelThickness:r,bevelSize:r,bevelSegments:1,steps:1});geometry.translate(0,0,-s[2]/2+r);
        } else geometry=new T.BoxGeometry(s[0],s[1],s[2]);
      } else if(p.type==='sphere') {
        geometry=new T.SphereGeometry(.5,nice?16:8,nice?10:6);geometry.scale(s[0],s[1],s[2]);
      } else if(p.type==='cylinder') geometry=new T.CylinderGeometry(s[0],s[1],s[2],nice?24:10);
      else if(p.type==='rod') {
        var a=new T.Vector3().fromArray(p.a), b=new T.Vector3().fromArray(p.b);
        geometry=new T.CylinderGeometry(p.radius,p.radius,a.distanceTo(b),nice?8:5);
        pos=a.clone().add(b).multiplyScalar(.5).toArray();
      } else if(p.type==='shape') {
        var contour=new T.Shape();p.points.forEach(function(v,i){if(i)contour.lineTo(v[0],v[1]);else contour.moveTo(v[0],v[1]);});contour.closePath();
        (p.holes||[]).forEach(function(h){var hole=new T.Path();hole.absarc(h.x,h.y,h.radius,0,Math.PI*2,true);contour.holes.push(hole);});
        geometry=new T.ExtrudeGeometry(contour,{depth:p.depth,bevelEnabled:nice,bevelThickness:.012,bevelSize:.012,bevelSegments:1,curveSegments:nice?12:6,steps:1});geometry.translate(0,0,-p.depth/2);
      } else throw new Error('Unsupported object primitive');
      geometries.push(geometry);
      var mesh=new T.Mesh(geometry,mat(p.material));mesh.position.fromArray(pos);mesh.rotation.set(rot[0],rot[1],rot[2]);
      if(p.type==='rod')mesh.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),b.sub(a).normalize());
      mesh.castShadow=high;mesh.receiveShadow=high;group.add(mesh);
    });
    return {group:group,dispose:function(){geometries.forEach(function(g){g.dispose();});Object.keys(materials).forEach(function(k){materials[k].dispose();});}};
  }};
})();
