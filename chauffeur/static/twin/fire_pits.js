import { inPolygon, edgeDistance, segmentIntersection } from './twin_ground.js';
import { simpleOutline } from './path_shapes.js';
import * as THREE from 'three';
import { polygon, addMesh } from './twin_generator.js';
import { insetPorch, porchFoundationRole } from './twin_porch_foundation.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

export function firePitOptions(pit) {
  const gas = pit.fuel === 'gas';
  return { fuel: gas ? 'gas' : 'wood', body: pit.body || 'stone', top: pit.top ?? (gas ? 'granite' : 'none'),
    height: (pit.height_in ?? (gas ? 18 : 16.8)) / 12, glass: pit.glass || 'amber',
    detailed: ['fuel', 'body', 'top', 'height_in', 'glass', 'entity'].some(key => key in pit) };
}

export const roundPit = pit => (pit.shape || 'round') === 'round';
export function placedPit(shape, at, options = {}) {
  if (shape === 'round') return { shape, at, radius: options.radius ?? 2 };
  const width = shape === 'square' ? options.side ?? 4 : options.width ?? 4;
  const depth = shape === 'square' ? width : options.depth ?? 6;
  const [x, y] = at;
  return { shape, polygon: [[x-width/2, y-depth/2], [x+width/2, y-depth/2], [x+width/2, y+depth/2], [x-width/2, y+depth/2]] };
}
export function firePitOutline(pit) {
  return roundPit(pit) ? Array.from({ length: 24 }, (_, i) => {
    const angle = i * Math.PI / 12 + (pit.rotation || 0) * Math.PI / 180;
    return [pit.at[0] + (pit.radius ?? 2) * Math.cos(angle), pit.at[1] + (pit.radius ?? 2) * Math.sin(angle)];
  }) : pit.polygon;
}
export function firePitRings(pit) {
  let outer = firePitOutline(pit);
  const area = outer.reduce((s, p, i) => s + p[0]*outer[(i+1)%outer.length][1] - p[1]*outer[(i+1)%outer.length][0], 0);
  if (area < 0) outer = [...outer].reverse();
  const edge = (a, b) => { const x=b[0]-a[0], y=b[1]-a[1], l=Math.hypot(x,y); return [x/l,y/l]; };
  const inside = point => inPolygon(outer, ...point);
  // Keep the inset inside concave outlines too. Narrow necks reduce the wall
  // thickness rather than letting the bowl poke through a neighbouring wall.
  for (let width = .35, attempt = 0; attempt < 32; attempt++, width /= 2) {
    const inner = outer.map((p, i) => {
      const a=edge(outer[(i+outer.length-1)%outer.length],p), b=edge(p,outer[(i+1)%outer.length]);
      const den=1+a[0]*b[0]+a[1]*b[1];
      return den > 1e-10 ? [p[0]-(a[1]+b[1])*width/den,p[1]+(a[0]+b[0])*width/den] : [p[0]-b[1]*width,p[1]+b[0]*width];
    });
    if (simpleOutline(inner) && inner.every((p,i) => inside(p) && inside(p.map((v,k)=>(v+inner[(i+1)%inner.length][k])/2)))) return { outer, inner };
  }
  return { outer, inner: [] };
}

// A disk wholly inside the bowl keeps logs, chips and flames off masonry even
// on a narrow or concave drawn outline. Prefer its centre; fall back to triangle
// incentres when the polygon's mean is outside (e.g. an L-shaped pit).
export function firePitLayout(pit) {
  const rings = firePitRings(pit), { inner, outer } = rings;
  const mean = outer.reduce((s,p) => s.map((v,i) => v+p[i]/outer.length), [0,0]);
  if (!inner.length) return { ...rings, centre: mean, radius: 0 };
  const distance = p => Math.min(...inner.map((a,i) => {
    const b=inner[(i+1)%inner.length], dx=b[0]-a[0],dy=b[1]-a[1];
    const t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)));
    return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy);
  }));
  const candidates = [mean, ...THREE.ShapeUtils.triangulateShape(inner.map(p=>new THREE.Vector2(...p)), []).map(ids => {
    const ps=ids.map(i=>inner[i]), weights=ps.map((_,i)=>Math.hypot(...ps[(i+1)%3].map((v,k)=>v-ps[(i+2)%3][k]))), sum=weights.reduce((a,b)=>a+b,0);
    return [0,1].map(k=>ps.reduce((s,p,i)=>s+p[k]*weights[i]/sum,0));
  })].filter(p=>inPolygon(inner,...p));
  candidates.sort((a,b)=>distance(b)-distance(a));
  const centre=candidates[0] || mean;
  return { ...rings, centre, radius: candidates.length ? distance(centre)*.92 : 0 };
}

function seeded(pit) {
  let seed=2166136261;
  for (const c of String(pit.id || JSON.stringify(firePitOutline(pit)))) seed=Math.imul(seed^c.charCodeAt(0),16777619);
  return () => { seed=Math.imul(seed,1664525)+1013904223|0; return (seed>>>0)/4294967296; };
}

function joined(parts) {
  const plain=parts.map(g=>g.index?g.toNonIndexed():g);
  const result=mergeGeometries(plain);
  for(const g of new Set([...parts,...plain]))g.dispose();
  return result;
}

// Gas is a solid table with only a shallow pan cutout. Non-round outlines get
// a rectangular pan aligned with their longest edge, including rotated tables.
export function gasTableLayout(pit) {
  const layout=firePitLayout(pit), {outer}=layout;
  const lengths=outer.map((a,i)=>Math.hypot(...outer[(i+1)%outer.length].map((v,k)=>v-a[k])));
  const edge=lengths.indexOf(Math.max(...lengths)), a=outer[edge], b=outer[(edge+1)%outer.length];
  const u=b.map((v,k)=>(v-a[k])/lengths[edge]), v=[-u[1],u[0]];
  const project=p=>[p[0]*u[0]+p[1]*u[1],p[0]*v[0]+p[1]*v[1]];
  const world=([x,y])=>[x*u[0]+y*v[0],x*u[1]+y*v[1]];
  const ps=outer.map(project), lo=[0,1].map(k=>Math.min(...ps.map(p=>p[k]))), hi=[0,1].map(k=>Math.max(...ps.map(p=>p[k])));
  const span=Math.min(hi[0]-lo[0],hi[1]-lo[1]), overhang=Math.min(1/12,span/8);
  // Preserve existing sub-six-inch authored outlines; those cannot physically
  // fit a three-inch border plus a burner, so use a proportional tiny fallback.
  const border=Math.min(Math.max(.25,Math.min(2/3,span*.2)),span*.4);
  const inset=Math.max(.01,border-overhang), slab=insetPorch(outer,-overhang);
  let pan;
  if(roundPit(pit))pan=insetPorch(outer,inset);
  else {
    const centre=project(layout.centre), widths=hi.map((n,k)=>n-lo[k]-2*inset);
    const rectangle=scale=>[[-1,-1],[1,-1],[1,1],[-1,1]].map(sign=>world(centre.map((n,k)=>n+sign[k]*widths[k]*scale/2)));
    for(let scale=1;scale>1e-5;scale*=.85){
      const candidate=rectangle(scale);
      const safe=candidate.every((p,i)=>inPolygon(outer,...p)&&outer.every((q,j)=>
        edgeDistance(p,q,outer[(j+1)%outer.length])>=inset-1e-7&&
        edgeDistance(q,p,candidate[(i+1)%4])>=inset-1e-7&&
        !segmentIntersection(p,candidate[(i+1)%4],q,outer[(j+1)%outer.length])));
      if(safe){pan=candidate;break;}
    }
    pan ||= rectangle(.00001);
  }
  const rimWidth=Math.min(.045,span/40), glass=insetPorch(pan,rimWidth);
  const centre=roundPit(pit)?[...pit.at]:pan.reduce((s,p)=>s.map((n,k)=>n+p[k]/pan.length),[0,0]);
  const radius=Math.min(...glass.map((p,i)=>edgeDistance(centre,p,glass[(i+1)%glass.length])))*.92;
  const lineLength=roundPit(pit)?0:Math.max(0,Math.hypot(...glass[1].map((n,k)=>n-glass[0][k]))-.18);
  const burnerRadius=radius*.68, burnerLength=roundPit(pit)?Math.PI*2*burnerRadius:lineLength;
  return {...layout,centre,radius,slab,pan,glass,overhang,border,slabThickness:1.5/12,u,lineLength,burnerRadius,burnerLength,
    tongues:Math.max(3,Math.min(64,Math.round(burnerLength*3.5)))};
}

function tableStone(group, outer, base, height, plain, pit) {
  const rng=seeded({...pit,id:String(pit.id||JSON.stringify(outer))+':stone'}), parts=[];
  const courses=Math.max(2,Math.round(height/.23)), course=height/courses;
  for(let row=0;row<courses;row++)outer.forEach((a,i)=>{
    const b=outer[(i+1)%outer.length], dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy), nx=dy/length,nz=dx/length;
    for(let at=-(row%2)*.35;at<length;){
      const end=Math.min(length,at+.4+rng()*.6),start=Math.max(0,at);at=end;
      if(end-start<.025)continue;
      const depth=.025+rng()*.015;
      const g=new THREE.BoxGeometry(end-start-.012,course-.012,depth).rotateY(Math.atan2(dy,dx))
        .translate(a[0]+dx*(start+end)/2/length+nx*depth/2,base+course*(row+.5),-a[1]-dy*(start+end)/2/length+nz*depth/2);
      const shade=.32+rng()*.28, colors=[];
      for(let j=0;j<g.attributes.position.count;j++)colors.push(shade,shade*1.01,shade*.99);
      g.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));parts.push(g);
    }
  });
  return addMesh(group,joined(parts),plain('fire table stone','#ffffff',{vertexColors:true,roughness:.9}));
}

function tableVents(group,pit,outer,base,height,plain) {
  const vents=[], longest=Math.max(...outer.map((p,i)=>Math.hypot(...outer[(i+1)%outer.length].map((n,k)=>n-p[k]))));
  const edges=roundPit(pit)?[0,6,12,18]:outer.map((_,i)=>i);
  for(const i of edges){
    const a=outer[i],b=outer[(i+1)%outer.length],dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy),nx=dy/length,nz=dx/length;
    for(const t of !roundPit(pit)&&length>=longest*.8?[1/3,2/3]:[.5]){
      const g=new THREE.PlaneGeometry(Math.min(.25,length*.8),Math.min(1/6,height*.25)).rotateY(Math.atan2(nx,nz))
        .translate(a[0]+dx*t+nx*.042,base+Math.min(.45,height*.4),-a[1]-dy*t+nz*.042);
      vents.push(addMesh(group,g,plain('fire table vent','#111316',{roughness:1})));
    }
  }
  return vents;
}

export function gasFlameLayout(table,pit) {
  const rng=seeded({...pit,id:String(pit.id||JSON.stringify(table.outer))+':flames'}), profiles=[];
  const maxWidth=Math.min(5/12,table.radius*.8,table.lineLength?table.lineLength*.8:table.burnerRadius*.9);
  for(let i=0;i<table.tongues;i++){
    const t=(i+.5+(rng()-.5)*.60)/table.tongues, across=(rng()-.5)*Math.min(.25,table.radius*.25);
    const width=Math.min(maxWidth,1.5/12+rng()*3.5/12),height=(5.5+rng()*3.5)/12,phase=rng()*Math.PI*2;
    const along=table.lineLength?Math.max(-table.lineLength/2+width/2,Math.min(table.lineLength/2-width/2,(t-.5)*table.lineLength)):t*Math.PI*2;
    const at=table.lineLength?[table.u[0]*along-table.u[1]*across,table.u[1]*along+table.u[0]*across]
      :[Math.cos(along)*(table.burnerRadius+across),Math.sin(along)*(table.burnerRadius+across)];
    profiles.push({at,width,height,phase,along,across});
  }
  return profiles;
}

function gasFlameGeometry(table,pit) {
  const parts=[], profiles=gasFlameLayout(table,pit);
  const data=(g,phase,kind,height)=>{
    const values=[];for(let i=0;i<g.attributes.position.count;i++)values.push(phase,kind,height);
    g.setAttribute('fireData',new THREE.Float32BufferAttribute(values,3));return g;
  };
  for(const p of profiles)for(const cross of [0,Math.PI/2]){
    const g=new THREE.PlaneGeometry(p.width,p.height,1,8).translate(0,p.height/2,0)
      .rotateY(p.phase*.13+cross).translate(p.at[0],0,-p.at[1]);
    parts.push(data(g,p.phase,0,p.height));
  }
  // Continuous soft glow at the burner, not a row of bright rigid stems.
  if(table.lineLength){
    const angle=Math.atan2(table.u[1],table.u[0]);
    parts.push(data(new THREE.PlaneGeometry(table.lineLength,.13).translate(0,.065,0).rotateY(angle),0,1,0));
    parts.push(data(new THREE.PlaneGeometry(table.lineLength,.35).rotateX(-Math.PI/2).rotateY(angle).translate(0,.005,0),0,2,0));
  }else{
    parts.push(data(new THREE.CylinderGeometry(table.burnerRadius,table.burnerRadius,.13,64,1,true).translate(0,.065,0),0,1,0));
    const inner=Math.max(.001,table.burnerRadius-.175),outer=table.burnerRadius+.175;
    const ring=new THREE.RingGeometry(inner,outer,64).rotateX(-Math.PI/2).translate(0,.005,0),uv=ring.attributes.uv,p=ring.attributes.position;
    for(let i=0;i<p.count;i++)uv.setXY(i,(Math.atan2(-p.getZ(i),p.getX(i))/Math.PI/2+1)%1,(Math.hypot(p.getX(i),p.getZ(i))-inner)/(outer-inner));
    parts.push(data(ring,0,2,0));
  }
  return joined(parts);
}

export function buildFirePit(group, pit, base, { mat, plain, id }) {
  const options=firePitOptions(pit), gas=options.fuel==='gas', table=gas?gasTableLayout(pit):null;
  const {outer,centre,radius}=table||firePitLayout(pit), inner=table?.glass||firePitRings(pit).inner, top=base+options.height;
  const finishedTop=top+(options.top==='none'?0:gas?table.slabThickness:.16), panFloor=finishedTop-2/12;
  const bodyGeometry=gas?joined([polygon(outer,base,panFloor),polygon(outer,panFloor,top,[table.pan])])
    :polygon(outer,base,top,inner.length?[inner]:[]);
  const body=addMesh(group,bodyGeometry,mat(porchFoundationRole(options.body)));
  const result={body, logs:[], chips:[], flame:null, cap:null, pan:null};
  if(gas){
    result.table=table;
    if(options.body==='stone')result.veneer=tableStone(group,outer,base,options.height,plain,pit);
    result.vents=tableVents(group,pit,outer,base,options.height,plain);
  }
  if (options.top !== 'none' && inner.length) {
    const lip=Math.min(.08,radius/8);
    result.cap=addMesh(group,gas?polygon(table.slab,top,finishedTop,[table.pan]):polygon(insetPorch(outer,-lip),top,top+.16,[insetPorch(inner,lip)]),mat(options.top==='granite'?'granite':'patio_concrete'));
  }
  if (!inner.length) return result;
  const bed=gas?finishedTop-.075:base+.15;
  const metal=gas?plain('fire burner pan','#a2a7ad',{metalness:.85,roughness:.22}):null;
  result.pan=addMesh(group,polygon(inner,gas?panFloor:base+.05,gas?panFloor+.01:bed),gas?metal:mat('counter'));
  if(gas){
    result.panWalls=addMesh(group,polygon(table.pan,panFloor,finishedTop,[inner]),metal);
    result.rim=addMesh(group,polygon(table.pan,finishedTop-.025,finishedTop+.004,[inner]),metal);
  }
  if (!options.detailed || radius <= .005) return result;
  const rng=seeded(pit), [x,y]=centre;
  if (gas) {
    const color={amber:'#a36a32',blue:'#1d3a50',clear:'#283e52'}[options.glass];
    const unlit={emissive:'#000000',emissiveIntensity:0};
    const material=plain('fire glass '+options.glass,color,{...unlit,roughness:.10,metalness:.35});
    const backing=plain('fire glass backing '+options.glass,new THREE.Color(color).multiplyScalar(.35),{...unlit,roughness:.85});
    result.glassBed=addMesh(group,polygon(inner,bed+.005,bed+.025),backing);
    // A close, jittered chip layer replaces sparse random shards. One instanced
    // draw, at most 4096 chips, with no transmission or self-lit backing plate.
    const lo=[0,1].map(k=>Math.min(...inner.map(p=>p[k]))),hi=[0,1].map(k=>Math.max(...inner.map(p=>p[k])));
    const spacing=Math.max(Math.min(.055,radius/8),Math.sqrt((hi[0]-lo[0])*(hi[1]-lo[1])/4096));
    const size=Math.min(spacing*.92,radius/8), placements=[];
    const contained=p=>inPolygon(inner,...p)&&inner.every((a,i)=>{
      const b=inner[(i+1)%inner.length],dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)));
      return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)>size*1.25;
    });
    for(let row=0,v=lo[1]+spacing/2;v<hi[1];row++,v+=spacing)for(let u=lo[0]+spacing*(row%2?1:.5);u<hi[0];u+=spacing) {
      const p=[u+(rng()-.5)*spacing*.14,v+(rng()-.5)*spacing*.14];
      if(contained(p)&&placements.length<4096)placements.push(p);
    }
    if(!placements.length)placements.push(centre);
    const chips=new THREE.InstancedMesh(new THREE.OctahedronGeometry(size),material,placements.length), dummy=new THREE.Object3D();
    for(const [i,p] of placements.entries()) {
      dummy.position.set(p[0],bed+.025+size*.25,-p[1]); dummy.rotation.set(0,rng()*Math.PI*2,0);dummy.scale.set(.9+rng()*.35,.45+rng()*.2,.9+rng()*.35);
      dummy.updateMatrix();chips.setMatrixAt(i,dummy.matrix);result.chips.push([...p]);
    }
    chips.receiveShadow=true; group.add(chips);result.glass=chips;
    const burner=table.lineLength?new THREE.CylinderGeometry(.02,.02,table.lineLength,6).rotateZ(Math.PI/2).rotateY(Math.atan2(table.u[1],table.u[0]))
      :new THREE.TorusGeometry(table.burnerRadius,Math.min(.025,radius*.04),5,64).rotateX(Math.PI/2);
    result.burner=addMesh(group,burner.translate(x,bed+.07,-y),plain('fire burner ring','#55565a',{metalness:.8,roughness:.35}));
  } else {
    addMesh(group,polygon(inner,bed,bed+.025),plain('fire ash','#423e39'));
    const bark=plain('fire logs','#493023'), ends=plain('fire log ends','#956541');
    for(let i=0;i<4;i++) {
      const angle=rng()*Math.PI, length=radius*(1.25+rng()*.3), r=Math.min(.14,radius*.12), shift=(i%2?1:-1)*radius*.16;
      const at=[x+Math.sin(angle)*shift,y+Math.cos(angle)*shift], h=bed+r+i*r*.55;
      // Bark and end grain batch independently across all wood pits.
      addMesh(group,new THREE.CylinderGeometry(r,r,length,8,1,true).rotateZ(Math.PI/2).rotateY(angle).translate(at[0],h,-at[1]),bark);
      for(const sign of [-1,1]) addMesh(group,new THREE.CircleGeometry(r,8).rotateY(sign*Math.PI/2+angle).translate(at[0]+sign*Math.cos(angle)*length/2,h,-at[1]-sign*Math.sin(angle)*length/2),ends);
      result.logs.push({at,height:h,radius:r,length,angle});
    }
    const ember=plain('fire embers','#8c3016',{emissive:'#000000',emissiveIntensity:0});
    for(let i=0;i<12;i++){const a=rng()*Math.PI*2,d=Math.sqrt(rng())*radius*.8;addMesh(group,new THREE.OctahedronGeometry(Math.min(.07,radius*.06)).translate(x+Math.cos(a)*d,bed+.04,-y+Math.sin(a)*d),ember);}
  }
  if (pit.entity) {
    const key='fire flame:'+id+':'+pit.entity+':'+options.fuel;
    // plain() is a cache too; shader materials use the same yard-owned map.
    const material=plain(key,'#ff9a3c',{fireShader:true});
    // Local yard feet, transformed by the live layer just like the geometry.
    material.userData.objectLight={id,entity:pit.entity,on:false,color:'#ff9a3c',fire:true,intensityScale:.5,fireLightAt:[x,finishedTop+4,-y]};
    material.uniforms.gas.value=gas?1:0;
    if(gas)material.uniforms.tongues.value=table.tongues;
    const height=Math.min(2.3,radius*1.8);
    const geometry=gas?gasFlameGeometry(table,pit):new THREE.PlaneGeometry(radius*1.25,height).translate(0,height/2,0);
    const flame=new THREE.Mesh(geometry,material);
    flame.position.set(x,bed+(gas ? .09 : Math.min(.5,radius*.5)),-y);
    flame.visible=false;flame.userData.fireFlame=true;flame.geometry.userData.bakeExcluded=true;
    group.add(flame); result.flame=flame;
    // Wood retains its crossed tall plume; gas is one ring or row mesh.
    if(!gas){const cross=flame.clone();cross.rotation.y=Math.PI/2;group.add(cross);}
  }
  return result;
}

export function fireFlameMaterial() {
  return new THREE.ShaderMaterial({transparent:true,depthWrite:false,side:THREE.DoubleSide,forceSinglePass:true,
    defaultAttributeValues:{color:[1,1,1],uv:[0,0],uv1:[0,0],fireData:[0,0,0]},
    blending:THREE.AdditiveBlending,toneMapped:false,uniforms:{time:{value:0},gas:{value:0},tongues:{value:24}},
    vertexShader:`uniform float time; uniform float gas; attribute vec3 fireData;
      varying vec2 vUv; varying vec3 vFire;
      void main(){vUv=uv;vFire=fireData;vec3 p=position;
        if(gas>.5&&fireData.y<.5){
          float phase=fireData.x;
          float pulse=.94+.10*sin(time*2.3+phase)+.05*sin(time*4.7-phase);
          float lick=(4./12.)*pow(max(0.,sin(time*.65+phase)),32.);
          p.y=vUv.y*min(14./12.,fireData.z*pulse+lick);
          p.x+=.055*sin(time*2.3+phase+vUv.y*4.)*vUv.y*vUv.y;
          p.z+=.035*cos(time*1.7+phase+vUv.y*3.)*vUv.y*vUv.y;
        }
        gl_Position=projectionMatrix*modelViewMatrix*vec4(p,1.);}`,
    fragmentShader:`uniform float time; uniform float gas; varying vec2 vUv; varying vec3 vFire;
      void main(){
        if(gas>.5){
          if(vFire.y>.5){
            float mask=vFire.y>1.5?1.-smoothstep(.15,.5,abs(vUv.y-.5)):exp(-vUv.y*4.);
            mask*=smoothstep(0.,.04,vUv.x)*(1.-smoothstep(.96,1.,vUv.x));
            gl_FragColor=vec4(1.,.35,.07,mask*.18);return;
          }
          float y=vUv.y,x=vUv.x-.5,phase=vFire.x;
          x+=.12*sin(time*2.1+phase+y*5.)*y*y;
          float width=.49*pow(max(0.,1.-y),.65);
          float mask=(1.-smoothstep(width*.35,width+.035,abs(x)))*(1.-smoothstep(.72,1.,y));
          float wisps=.76+.12*sin(time*4.+phase+y*13.)+.08*sin(x*22.+y*18.-time*3.);
          float core=(1.-smoothstep(0.,width,abs(x)))*(1.-smoothstep(.25,.85,y));
          vec3 color=mix(vec3(1.1,.24,.025),vec3(1.5,1.15,.5),core);
          color=mix(vec3(.15,.24,.45),color,smoothstep(0.,.035,y));
          gl_FragColor=vec4(color,mask*wisps*.58);return;
        }
        float y=vUv.y;float x=vUv.x-.5;
        x+=sin(y*12.-time*4.)*.045*y;
        float tongues=.12*sin(vUv.x*39.+sin(time*2.))+ .07*sin(vUv.x*71.-time*3.);
        float edge=(1.-y)*(.42+tongues);
        float mask=(1.-smoothstep(edge-.1,edge,abs(x)))*(1.-smoothstep(.45,1.,y));
        float pulse=.85+.1*sin(time*9.+y*11.);
        vec3 color=mix(vec3(1.,.68,.18),vec3(1.,.16,.015),y);
        gl_FragColor=vec4(color,mask*pulse*.8);}`});
}
