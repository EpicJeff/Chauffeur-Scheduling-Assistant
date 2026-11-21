import * as THREE from 'three';
import { groundAt, inPolygon, buildingFootprint } from '../twin_ground.js';
import { grassCovers } from '../yard_grass.js';
import { precipitationVelocity } from './precipitation.js';
import { createSplashSampler } from './precipitation.js';
import { createSkyCover } from './sky_cover.js';
import { seasonHash } from './seasons.js';
import { weatherExtinction } from './weather.js';

const FT=.3048, LEAVES={low:60,medium:100,high:150,max:240};
// About 80% of the steady state at the peak drop rate (rate x 480 s), so the oldest are overwritten.
export const RESTING_LEAVES=Object.freeze({low:200,medium:320,high:480,max:760});
export const LEAF_REST_SECONDS=480,LEAF_FADE_SECONDS=30;
// Leaves per second per metre of crown width at the peak of leaf drop.
export const LEAF_RATE=.07;
const finite=(v,fallback=0)=>Number.isFinite(v)?v:fallback;
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,finite(v,a)));
export function seasonTouchCounts(tier,season={},weather={}, {date=new Date(),sunAltDeg=90,enabled=true}={}) {
  if(!enabled||season.neutral)return {leaves:0,fireflies:0};
  const month=(date.getUTCMonth()+(season.latitude<0?6:0))%12;
  const summer=season.preview==='summer'||(!season.preview&&month>=5&&month<=7&&
    Number.isFinite(weather.temperatureC)&&weather.temperatureC>=18&&!(weather.rate>0&&weather.precip!=='none'));
  return {leaves:season.autumn>.5&&season.presence>0?(LEAVES[tier]||500):0,
    fireflies:sunAltDeg<-4&&summer?(tier==='low'?25:60):0};
}

export function leafDropRate(season={}) {
  if(season.neutral||!(season.presence>0))return 0;
  // Peak drop is a steady few leaves a second across the yard, not a blizzard.
  return season.presence<1?.15:clamp((season.autumn-.5)*2)*.012;
}

// Ground receivers include beds and paving, unlike the firefly lawn sampler.
// Reuse precipitation's authored deck/paver heights; a roof hit is rejected
// rather than allowing the leaf to pass through it and rest beneath it.
export function createLeafLandingSampler(plan={},roofs=new Map(),cover=createSkyCover(plan,roofs)) {
  const beds=plan.site?.beds||[],lot=plan.site?.lot;
  // Rain excludes mulch; leaves must resolve whichever authored receiver is
  // highest, including a bed's .12 ft soil layer and its elevation.
  const hard=createSplashSampler({...plan,site:{...plan.site,beds:[]}},roofs,cover);
  const water=[plan.site?.pool?.polygon,...(plan.site?.pool?.features||[]).filter(f=>f.kind==='spa').map(f=>f.polygon)].filter(Boolean);
  return (worldX,worldZ)=>{
    if(!Number.isFinite(worldX)||!Number.isFinite(worldZ))return null;
    const x=worldX/FT,y=-worldZ/FT;
    if(lot&&!inPolygon(lot,x,y)||water.some(p=>inPolygon(p,x,y)))return null;
    const hit=hard(worldX,worldZ);if(hit?.kind==='roof')return null;
    const ground=finite(groundAt(plan,x,y));let height=ground*FT+.006;
    for(const bed of beds)if(bed.polygon?.length>=3&&inPolygon(bed.polygon,x,y))height=Math.max(height,(ground+finite(bed.elevation)+.12)*FT+.006);
    if(hit)height=Math.max(height,hit.position[1]);
    const position=[worldX,height,worldZ];
    return cover.blocked(...position)?null:position;
  };
}

// Use the lawn's own exclusion geometry, including rotated buildings, stairs,
// paths, beds and pool coping. Keep enough clearance for the whole hover orbit.
export function createLawnSampler(plan={}, {clearance=.16}={}) {
  const lot=plan.site?.lot,covers=grassCovers(plan),margin=clamp(clearance,0,2)/FT;
  const near=(poly,x,y,margin)=>{
    if(inPolygon(poly,x,y))return true;
    for(let i=0;i<poly.length;i++){
      const a=poly[i],b=poly[(i+1)%poly.length],dx=b[0]-a[0],dy=b[1]-a[1];
      const t=clamp(((x-a[0])*dx+(y-a[1])*dy)/Math.max(dx*dx+dy*dy,1e-8));
      if(Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy)<margin)return true;
    }
    return false;
  };
  return (worldX,worldZ)=>{
    if(!Number.isFinite(worldX)||!Number.isFinite(worldZ)||!(lot?.length>=3))return null;
    const x=worldX/FT,y=-worldZ/FT;
    if(!inPolygon(lot,x,y)||covers.some(c=>near(c.polygon,x,y,(c.margin||0)+margin)))return null;
    // Stay inside the lot at every phase of the hover, too.
    for(let i=0;i<lot.length;i++){
      const a=lot[i],b=lot[(i+1)%lot.length],dx=b[0]-a[0],dy=b[1]-a[1];
      const t=clamp(((x-a[0])*dx+(y-a[1])*dy)/Math.max(dx*dx+dy*dy,1e-8));
      if(Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy)<margin)return null;
    }
    const h=groundAt(plan,x,y)*FT;
    return Number.isFinite(h)?[worldX,h,worldZ]:null;
  };
}

const vertexShader=`
attribute vec3 touchPosition,touchColour;
attribute vec4 touchShape;
attribute vec4 touchRotation;
attribute vec2 touchSize;
uniform float touchKind;
varying vec2 touchUv;varying vec3 touchWorld,touchTint;varying float touchAlpha,touchAutumn;
void main(){
  touchUv=uv;touchTint=touchColour;touchAlpha=touchShape.z;touchAutumn=touchShape.x;touchWorld=touchPosition;
  vec4 eye=viewMatrix*vec4(touchPosition,1.0);
  if(touchKind<.5){
    vec3 leaf=vec3(position.xy*touchSize,0.0);
    leaf+=2.0*cross(touchRotation.xyz,cross(touchRotation.xyz,leaf)+touchRotation.w*leaf);
    eye=viewMatrix*vec4(touchPosition+leaf,1.0);
  }else eye.xy+=position.xy*touchShape.w;
  gl_Position=projectionMatrix*eye;
}`;
const fragmentShader=`
uniform float touchKind,touchExtent,touchRadius,touchExtinction;
uniform vec3 touchAnchor;uniform vec2 touchCentre;
varying vec2 touchUv;varying vec3 touchWorld,touchTint;varying float touchAlpha,touchAutumn;
vec3 safeRGB(vec3 c){return vec3(c.r>=0.0?min(c.r,4096.0):0.0,c.g>=0.0?min(c.g,4096.0):0.0,c.b>=0.0?min(c.b,4096.0):0.0);}
void main(){
  vec2 p=touchUv*2.0-1.0;
  float shape=touchKind<.5?1.0-smoothstep(.7,1.0,abs(p.x)+abs(p.y)*.55):exp(-dot(p,p)*4.0);
  float edge=1.0-smoothstep(touchExtent*.8,max(touchExtent,.001),distance(touchWorld.xz,touchAnchor.xz));
  float haze=1.0-smoothstep(touchRadius,max(touchRadius*1.35,.001),distance(touchWorld.xz,touchCentre));
  float alpha=clamp(shape*touchAlpha*edge*haze*exp(-max(touchExtinction,0.0)*distance(touchWorld,cameraPosition)),0.0,1.0);
  if(alpha<.003)discard;
  gl_FragColor=vec4(safeRGB(touchTint),alpha);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;
const leafFragment='uniform sampler2D touchMap;\nuniform vec3 touchLight;\n'+fragmentShader
  .replace('float shape=touchKind<.5?1.0-smoothstep(.7,1.0,abs(p.x)+abs(p.y)*.55):exp(-dot(p,p)*4.0);',
    `vec4 texel=texture2D(touchMap,touchUv);
  float shape=texel.a;
  float luminance=max(dot(texel.rgb,vec3(.2126,.7152,.0722)),0.0);
  // Lit like the scene's own Lambert materials: albedo/pi times the irradiance the view
  // passes in (owner 2026-11-19: leaves glowed at night).
  vec3 leafColour=mix(texel.rgb,touchTint*luminance,touchAutumn)*touchLight;`)
  .replace('safeRGB(touchTint)','safeRGB(leafColour)');
function geometry(count) {
  const g=new THREE.InstancedBufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute([-.5,-.5,0,.5,-.5,0,.5,.5,0,-.5,.5,0],3));
  g.setAttribute('uv',new THREE.Float32BufferAttribute([0,0,1,0,1,1,0,1],2));g.setIndex([0,1,2,0,2,3]);
  for(const [name,size] of [['touchPosition',3],['touchShape',4],['touchColour',3],['touchRotation',4],['touchSize',2]])
    g.setAttribute(name,new THREE.InstancedBufferAttribute(new Float32Array(count*size),size).setUsage(THREE.DynamicDrawUsage));
  g.instanceCount=0;return g;
}
export function createSeasonTouches(scene,{tier='high',random=Math.random}={}) {
  const group=new THREE.Group();group.name='season-touches';scene.add(group);
  const uniforms={touchAnchor:{value:new THREE.Vector3()},touchExtent:{value:18},touchWind:{value:new THREE.Vector3()},
    touchCentre:{value:new THREE.Vector2()},touchRadius:{value:100},touchExtinction:{value:0},
    touchLight:{value:new THREE.Vector3(1,1,1)}};
  const objects={},seeds=[],particles=[],resting=new Array(RESTING_LEAVES[tier]||1600),batches=[];
  let restCursor=0,serial=0,credit=0,landing=()=>null,autumnTint=0,lastPreview;
  // All six slots exist before warm-up. Changing texture assignments or the
  // season never creates a material, define or program variant.
  const fallback=new THREE.DataTexture(new Uint8Array([255,255,255,255]),1,1);fallback.needsUpdate=true;
  for(let i=0;i<(LEAVES[tier]||500);i++)seeds.push(clamp(random()));
  for(const name of ['leaves','leaves1','leaves2','leaves3','leaves4','leaves5','fireflies']){
    const i=name==='fireflies'?1:0,g=geometry(i?(tier==='low'?25:60):seeds.length+resting.length);
    const material=new THREE.ShaderMaterial({name:i?'season-fireflies':'season-leaves',uniforms:{...uniforms,touchKind:{value:i},...(!i?{touchMap:{value:fallback}}:{})},vertexShader,fragmentShader:i?fragmentShader:leafFragment,
      transparent:true,blending:i?THREE.AdditiveBlending:THREE.NormalBlending,depthWrite:false,depthTest:true,side:THREE.DoubleSide,lights:false,fog:false});
    const o=new THREE.Mesh(g,material);o.name='season-'+name;o.visible=false;o.frustumCulled=false;o.raycast=()=>{};
    o.castShadow=o.receiveShadow=false;o.renderOrder=21;group.add(o);objects[name]=o;
    if(!i)batches.push({object:o,texture:null,count:0});
  }
  let plan={},sample=()=>null,last=null,clock=0,disposed=false,roots=[],rootAnchor=null,houseCentre=null;
  const frustum=new THREE.Frustum(),matrix=new THREE.Matrix4(),sources=[];
  const motion=globalThis.window?.matchMedia?.('(prefers-reduced-motion: reduce)');
  function dirty(o,n){o.geometry.instanceCount=n;o.visible=n>0;for(const a of Object.values(o.geometry.attributes))if(a.isInstancedBufferAttribute)a.needsUpdate=true;}
  const footprints=new WeakMap();
  function leafFootprint(data){
    let box=footprints.get(data);if(box)return box;
    let x0=Infinity,x1=-Infinity,z0=Infinity,z1=-Infinity;const ps=data.positions||[];
    for(let i=0;i<ps.length;i+=3){x0=Math.min(x0,ps[i]);x1=Math.max(x1,ps[i]);z0=Math.min(z0,ps[i+2]);z1=Math.max(z1,ps[i+2]);}
    box=Number.isFinite(x0)?[x1-x0,z1-z0]:[1,1];footprints.set(data,box);return box;
  }
  function collect(root,camera,target,extent){
    sources.length=0;if(!root)return;
    root.updateWorldMatrix(true,true);camera.updateMatrixWorld();
    frustum.setFromProjectionMatrix(matrix.multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse));
    root.traverse(o=>{
      const data=o.seasonLeaves;if(o.userData.seasonKind!=='deciduous'||!data?.count||!data.texture)return;
      for(let p=o;p;p=p.parent)if(!p.visible)return;
      const at=o.getWorldPosition(new THREE.Vector3()),p=plan.site?.planting?.[o.userData.yardPlantIndex];
      const height=Math.max(.5,finite(p?.height,15)*FT*finite(p?.scale,1)*finite(p?.scale_axes?.[1],1));
      const centre=at.clone();centre.y+=height*.6;
      // One measure for every plant: the world footprint of its own leaf positions. The
      // stored canopyArea differed by build path (owner 2026-11-19: three agent-built
      // trees took 92% of all leaves while his own trees barely dropped any).
      const scale=o.getWorldScale(new THREE.Vector3()),box=leafFootprint(data);
      const area=Math.max(1e-6,box[0]*Math.abs(scale.x)*box[1]*Math.abs(scale.z));
      if(Math.hypot(at.x-target.x,at.z-target.z)<extent&&frustum.intersectsSphere(new THREE.Sphere(centre,height*.6)))
        sources.push({at,height,object:o,data,count:data.count,area,texture:data.texture,hue:finite(o.userData.seasonHue)});
    });
  }
  function bindLeafTextures(target,extent){
    const totals=new Map();for(const s of sources)totals.set(s.texture,(totals.get(s.texture)||0)+s.area);
    // Off-screen resting records retain their texture, but do not occupy a
    // draw slot. Returning to them rebinds the same shared map.
    const referenced=new Set([...particles,...resting].filter(p=>p&&Math.hypot(p.position[0]-target.x,p.position[2]-target.z)<extent).map(p=>p.texture));
    for(const texture of referenced)if(!totals.has(texture))totals.set(texture,0);
    for(const batch of batches)if(!referenced.has(batch.texture)&&!totals.has(batch.texture))batch.texture=null;
    for(const [texture] of [...totals].sort((a,b)=>b[1]-a[1])){
      if(batches.some(b=>b.texture===texture))continue;
      const free=batches.find(b=>!b.texture);if(!free)break;free.texture=texture;free.object.material.uniforms.touchMap.value=texture;
    }
    for(let i=sources.length-1;i>=0;i--){const s=sources[i];s.batch=batches.find(b=>b.texture===s.texture);if(!s.batch)sources.splice(i,1);}
    const total=sources.reduce((n,s)=>n+Math.sqrt(s.area),0);for(const s of sources)s.weight=Math.sqrt(s.area)/Math.max(total,1e-6);
  }
  const rotation=new THREE.Quaternion(),axis=new THREE.Vector3(),tilt=new THREE.Quaternion();
  function spawn(){
    if(!sources.length)return;
    const id=serial++,roll=tag=>(seasonHash(id+':'+tag)+clamp(random()))%1;
    let ticket=roll('source'),source=sources[sources.length-1];
    for(const s of sources){ticket-=s.weight;if(ticket<=0){source=s;break;}}
    const index=Math.min(source.count-1,Math.floor(roll('point')*source.count)),data=source.data;
    const at=new THREE.Vector3().fromArray(data.positions,index*3).applyMatrix4(source.object.matrixWorld);
    const scale=source.object.getWorldScale(new THREE.Vector3());
    const hue=source.hue,c=hue<.5?new THREE.Vector3(.9,.62,.045).lerp(new THREE.Vector3(.9,.24,.025),hue*2):
      new THREE.Vector3(.9,.24,.025).lerp(new THREE.Vector3(.65,.045,.018),(hue-.5)*2);
    c.multiplyScalar((.9+roll('tint')*.2)/Math.max(c.dot(new THREE.Vector3(.2126,.7152,.0722)),.0001));
    const spinAxis=new THREE.Vector3(roll('ax')*2-1,roll('ay')*2-1,roll('az')*2-1);
    if(spinAxis.lengthSq()<1e-8)spinAxis.set(1,0,0);spinAxis.normalize();
    return {id,source:source.object,sourceIndex:index,origin:at.toArray(),position:at.toArray(),texture:source.texture,batch:source.batch,colour:c.toArray(),
      size:[Math.abs(data.sizes[index*2]*scale.x),Math.abs(data.sizes[index*2+1]*scale.y)],autumn:autumnTint,
      axis:spinAxis.toArray(),spin:(.7+roll('spin')*4)*(roll('sign')<.5?-1:1),phase:roll('phase')*Math.PI*2,
      flutter:.15+roll('flutter')*.6,frequency:.7+roll('frequency')*2,drag:.035+roll('drag')*.14,
      fall:.35+roll('fall')*.65,age:0,yaw:roll('yaw')*Math.PI*2,tilt:(roll('tilt')-.5)*.14};
  }
  function writeLeaf(p,alpha,rest=false){
    const batch=batches.find(b=>b.texture===p.texture);if(!batch)return;
    p.batch=batch;const i=batch.count++,a=batch.object.geometry.attributes;
    a.touchPosition.setXYZ(i,...p.position);a.touchColour.setXYZ(i,...p.colour);a.touchShape.setXYZW(i,p.autumn,0,alpha,1);
    if(rest){rotation.setFromAxisAngle(axis.set(0,1,0),p.yaw);tilt.setFromAxisAngle(axis.set(1,0,0),-Math.PI/2+p.tilt);rotation.multiply(tilt);}
    else rotation.setFromAxisAngle(axis.fromArray(p.axis),p.phase+p.spin*p.age);
    a.touchRotation.setXYZW(i,rotation.x,rotation.y,rotation.z,rotation.w);a.touchSize.setXY(i,...p.size);
  }
  return {group,objects,uniforms,
    setStage({centre,radius}){if(centre?.every(Number.isFinite))uniforms.touchCentre.value.fromArray(centre);if(Number.isFinite(radius)&&radius>0)uniforms.touchRadius.value=radius;},
    info:()=>({sources,falling:particles,resting:resting.filter(Boolean),restCapacity:resting.length,batches}),
    setPlan(value,roofs,cover){
      plan=value||{};sample=createLawnSampler(plan,{clearance:.4});landing=createLeafLandingSampler(plan,roofs,cover);
      roots=[];rootAnchor=null;particles.length=0;resting.fill(undefined);restCursor=0;credit=0;
      const points=[];
      for(const b of plan.buildings||[]){
        const a=finite(b.rotation)*Math.PI/180,c=Math.cos(a),s=Math.sin(a),pos=b.position||[0,0];
        for(const [x,y] of buildingFootprint(b))points.push([(pos[0]+x*c-y*s)*FT,-(pos[1]+x*s+y*c)*FT]);
      }
      houseCentre=points.length?[(Math.min(...points.map(p=>p[0]))+Math.max(...points.map(p=>p[0])))*.5,
        (Math.min(...points.map(p=>p[1]))+Math.max(...points.map(p=>p[1])))*.5]:null;
    },
    update(now,season,weather,camera,{target=camera.position,plants=null,date=new Date(),sunAltDeg=90,enabled=true,lawn=true,bearing=180,reduced=motion?.matches,extent:extentOverride,light=null}={}){
      if(light?.every?.(Number.isFinite))uniforms.touchLight.value.fromArray(light);
      if(disposed)return;
      const dt=last===null?0:clamp(finite(now)-last,0,1)*(reduced?.35:1);last=finite(now);clock+=dt;
      now=finite(now);const extent=finite(extentOverride,clamp(.75*camera.position.distanceTo(target),18,64));
      uniforms.touchAnchor.value.copy(target);uniforms.touchExtent.value=extent;
      uniforms.touchWind.value.fromArray(precipitationVelocity('snow',weather,bearing));
      uniforms.touchExtinction.value=weatherExtinction(weather);
      const counts=seasonTouchCounts(tier,season,weather,{date,sunAltDeg,enabled});
      autumnTint=clamp(season.autumn);
      if(counts.leaves)collect(plants,camera,target,extent);else sources.length=0;
      // Real time moves through the year gradually and fallen leaves age out on
      // their own. A season preview jumps months, so its ground starts clear.
      const preview=season.preview??null;
      if(lastPreview!==undefined&&preview!==lastPreview){particles.length=0;resting.fill(undefined);restCursor=0;credit=0;}
      lastPreview=preview;
      bindLeafTextures(target,extent);
      for(const b of batches)b.count=0;
      const show=enabled&&!season.neutral;
      if(!show){particles.length=0;credit=0;}
      // Each visible plant drops at its own rate, growing with its crown's width
      // (sqrt of footprint): a 3.5 m crown about one leaf per 4 s at the peak, a 20 m
      // crown about 1.4 a second. The tier count only caps leaves in the air.
      const perSecond=LEAF_RATE*sources.reduce((n,s)=>n+Math.sqrt(s.area),0)*leafDropRate(season)/.15;
      credit=Math.min(12,credit+dt*perSecond);
      while(credit>=1&&particles.length<counts.leaves){credit--;const p=spawn();if(p)particles.push(p);else break;}
      for(let i=particles.length-1;i>=0;i--){
        const p=particles[i];p.age+=dt;const t=p.age,w=uniforms.touchWind.value;
        const flutterX=p.flutter*Math.sin(t*p.frequency+p.phase),flutterZ=p.flutter*Math.cos(t*p.frequency*.79+p.phase*1.7);
        p.position[0]+=dt*(w.x*p.drag*(1+.4*Math.sin(t*.8+p.phase))+flutterX);
        p.position[2]+=dt*(w.z*p.drag*(1+.4*Math.cos(t*.7+p.phase))+flutterZ);
        p.position[1]-=dt*p.fall*(.8+.2*Math.sin(t*p.frequency+p.phase));
        const hit=landing(p.position[0],p.position[2]);
        const floor=hit?.[1]??finite(groundAt(plan,p.position[0]/FT,-p.position[2]/FT))*FT;
        if(p.position[1]<=floor){
          particles.splice(i,1);
          if(hit){p.position=hit;p.born=now;resting[restCursor]=p;restCursor=(restCursor+1)%resting.length;}
        }else if(p.age>90)particles.splice(i,1);
        else if(show)writeLeaf(p,1);
      }
      for(let i=0;i<resting.length;i++){
        const p=resting[i];if(!p)continue;const age=now-p.born;
        if(now>=p.born+LEAF_REST_SECONDS){resting[i]=undefined;continue;}
        if(show&&weather.windMps>10&&particles.length<(LEAVES[tier]||500)&&dt>0&&seasonHash(p.id+':lift:'+Math.floor(now))<dt*.002){
          resting[i]=undefined;p.position[1]+=.25;p.age=0;particles.push(p);continue;
        }
        if(show)writeLeaf(p,1-clamp((age-(LEAF_REST_SECONDS-LEAF_FADE_SECONDS))/LEAF_FADE_SECONDS),true);
      }
      for(const b of batches)dirty(b.object,b.count);
      const fly=objects.fireflies,fa=fly.geometry.attributes;
      if(counts.fireflies&&lawn){
        if(!rootAnchor||rootAnchor.distanceTo(target)>8){
          roots=[];rootAnchor=target.clone();const lot=plan.site?.lot||[];
          if(lot.length>=3){
            const xs=lot.map(p=>p[0]*FT),zs=lot.map(p=>-p[1]*FT),cx=houseCentre?.[0]??(Math.min(...xs)+Math.max(...xs))*.5,cz=houseCentre?.[1]??(Math.min(...zs)+Math.max(...zs))*.5;
            for(let i=0;i<counts.fireflies*80&&roots.length<counts.fireflies;i++){
              // A stable low-discrepancy sequence also works with a deterministic RNG.
              const x=Math.max(Math.min(...xs),target.x-extent)+(Math.min(Math.max(...xs),target.x+extent)-Math.max(Math.min(...xs),target.x-extent))*((i*.754877666+seeds[0])%1);
              const z=Math.max(Math.min(...zs),target.z-extent)+(Math.min(Math.max(...zs),target.z+extent)-Math.max(Math.min(...zs),target.z-extent))*((i*.569840296+seeds[1])%1);
              const hit=Math.hypot(x-cx,z-cz)<=32?sample(x,z):null;if(hit)roots.push(hit);
            }
          }
        }
        for(let i=0;i<roots.length;i++){
          const root=roots[i],phase=i*2.39996,x=root[0]+.10*Math.sin(clock*.4+phase),z=root[2]+.10*Math.cos(clock*.33+phase);
          const y=finite(groundAt(plan,x/FT,-z/FT))*FT+.9+.6*Math.sin(clock*.5+phase);
          fa.touchPosition.setXYZ(i,x,y,z);fa.touchShape.setXYZW(i,0,0,.15+.85*Math.max(0,Math.sin(clock*(.65+i%5*.07)+phase))**4,.09);
          fa.touchColour.setXYZ(i,1.6,2,.45);
        }
      }
      dirty(fly,counts.fireflies&&lawn?roots.length:0);
    },
    dispose(){if(disposed)return;disposed=true;group.removeFromParent();for(const o of Object.values(objects)){o.geometry.dispose();o.material.dispose();}fallback.dispose();roots=[];particles.length=0;resting.fill(undefined);},
  };
}
