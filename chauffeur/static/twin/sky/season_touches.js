import * as THREE from 'three';
import { groundAt, inPolygon, buildingFootprint } from '../twin_ground.js';
import { grassCovers } from '../yard_grass.js';
import { precipitationVelocity } from './precipitation.js';

const FT=.3048, LEAVES={low:150,medium:300,high:500,max:800};
const finite=(v,fallback=0)=>Number.isFinite(v)?v:fallback;
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,finite(v,a)));
export function seasonTouchCounts(tier,season={},weather={}, {date=new Date(),sunAltDeg=90,enabled=true}={}) {
  if(!enabled||season.neutral)return {leaves:0,fireflies:0};
  const month=(date.getUTCMonth()+(season.latitude<0?6:0))%12;
  const summer=season.preview==='summer'||(!season.preview&&month>=5&&month<=7&&
    Number.isFinite(weather.temperatureC)&&weather.temperatureC>=18&&!(weather.rate>0&&weather.precip!=='none'));
  return {leaves:season.autumn>0&&season.presence>0?(LEAVES[tier]||500):0,
    fireflies:sunAltDeg<-4&&summer?(tier==='low'?25:60):0};
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
uniform float touchKind;
varying vec2 touchUv;varying vec3 touchWorld,touchTint;varying float touchAlpha;
void main(){
  touchUv=uv;touchTint=touchColour;touchAlpha=touchShape.z;touchWorld=touchPosition;
  vec4 eye=viewMatrix*vec4(touchPosition,1.0);
  if(touchKind<.5){
    float a=touchShape.x,b=touchShape.y;
    vec3 leaf=vec3(position.x*cos(a)-position.y*sin(a),position.x*sin(a)+position.y*cos(a),0.0)*touchShape.w;
    leaf.yz=vec2(leaf.y*cos(b),leaf.y*sin(b));
    eye=viewMatrix*vec4(touchPosition+leaf,1.0);
  }else eye.xy+=position.xy*touchShape.w;
  gl_Position=projectionMatrix*eye;
}`;
const fragmentShader=`
uniform float touchKind,touchExtent,touchRadius;
uniform vec3 touchAnchor;uniform vec2 touchCentre;
varying vec2 touchUv;varying vec3 touchWorld,touchTint;varying float touchAlpha;
vec3 safeRGB(vec3 c){return vec3(c.r>=0.0?min(c.r,4096.0):0.0,c.g>=0.0?min(c.g,4096.0):0.0,c.b>=0.0?min(c.b,4096.0):0.0);}
void main(){
  vec2 p=touchUv*2.0-1.0;
  float shape=touchKind<.5?1.0-smoothstep(.7,1.0,abs(p.x)+abs(p.y)*.55):exp(-dot(p,p)*4.0);
  float edge=1.0-smoothstep(touchExtent*.8,max(touchExtent,.001),distance(touchWorld.xz,touchAnchor.xz));
  float haze=1.0-smoothstep(touchRadius,max(touchRadius*1.35,.001),distance(touchWorld.xz,touchCentre));
  float alpha=clamp(shape*touchAlpha*edge*haze,0.0,1.0);
  if(alpha<.003)discard;
  gl_FragColor=vec4(safeRGB(touchTint),alpha);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;
function geometry(count) {
  const g=new THREE.InstancedBufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute([-.5,-.5,0,.5,-.5,0,.5,.5,0,-.5,.5,0],3));
  g.setAttribute('uv',new THREE.Float32BufferAttribute([0,0,1,0,1,1,0,1],2));g.setIndex([0,1,2,0,2,3]);
  for(const [name,size] of [['touchPosition',3],['touchShape',4],['touchColour',3]])
    g.setAttribute(name,new THREE.InstancedBufferAttribute(new Float32Array(count*size),size).setUsage(THREE.DynamicDrawUsage));
  g.instanceCount=0;return g;
}
export function createSeasonTouches(scene,{tier='high',random=Math.random}={}) {
  const group=new THREE.Group();group.name='season-touches';scene.add(group);
  const uniforms={touchAnchor:{value:new THREE.Vector3()},touchExtent:{value:18},touchWind:{value:new THREE.Vector3()},
    touchCentre:{value:new THREE.Vector2()},touchRadius:{value:100}};
  const objects={},seeds=[],particles=[];
  for(let i=0;i<(LEAVES[tier]||500);i++)seeds.push(clamp(random()));
  for(const [i,name] of ['leaves','fireflies'].entries()){
    const g=geometry(i?(tier==='low'?25:60):seeds.length);
    const material=new THREE.ShaderMaterial({name:'season-'+name,uniforms:{...uniforms,touchKind:{value:i}},vertexShader,fragmentShader,
      transparent:true,blending:i?THREE.AdditiveBlending:THREE.NormalBlending,depthWrite:false,depthTest:true,side:THREE.DoubleSide,lights:false,fog:false});
    const o=new THREE.Mesh(g,material);o.name='season-'+name;o.visible=false;o.frustumCulled=false;o.raycast=()=>{};
    o.castShadow=o.receiveShadow=false;o.renderOrder=21;group.add(o);objects[name]=o;
  }
  let plan={},sample=()=>null,last=null,clock=0,disposed=false,roots=[],rootAnchor=null,houseCentre=null;
  const frustum=new THREE.Frustum(),matrix=new THREE.Matrix4(),sources=[];
  const motion=globalThis.window?.matchMedia?.('(prefers-reduced-motion: reduce)');
  function dirty(o,n){o.geometry.instanceCount=n;o.visible=n>0;for(const a of Object.values(o.geometry.attributes))if(a.isInstancedBufferAttribute)a.needsUpdate=true;}
  function collect(root,camera,target,extent){
    sources.length=0;if(!root)return;
    root.updateWorldMatrix(true,true);camera.updateMatrixWorld();
    frustum.setFromProjectionMatrix(matrix.multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse));
    root.traverse(o=>{
      if(o.userData.seasonKind!=='deciduous')return;
      for(let p=o;p;p=p.parent)if(!p.visible)return;
      const at=o.getWorldPosition(new THREE.Vector3()),p=plan.site?.planting?.[o.userData.yardPlantIndex];
      const height=Math.max(.5,finite(p?.height,15)*FT*finite(p?.scale,1)*finite(p?.scale_axes?.[1],1));
      const centre=at.clone();centre.y+=height*.6;
      if(Math.hypot(at.x-target.x,at.z-target.z)<extent&&frustum.intersectsSphere(new THREE.Sphere(centre,height*.6)))sources.push({at,height,object:o});
    });
  }
  return {group,objects,uniforms,
    setStage({centre,radius}){if(centre?.every(Number.isFinite))uniforms.touchCentre.value.fromArray(centre);if(Number.isFinite(radius)&&radius>0)uniforms.touchRadius.value=radius;},
    setPlan(value){
      plan=value||{};sample=createLawnSampler(plan,{clearance:.4});roots=[];rootAnchor=null;particles.length=0;
      const points=[];
      for(const b of plan.buildings||[]){
        const a=finite(b.rotation)*Math.PI/180,c=Math.cos(a),s=Math.sin(a),pos=b.position||[0,0];
        for(const [x,y] of buildingFootprint(b))points.push([(pos[0]+x*c-y*s)*FT,-(pos[1]+x*s+y*c)*FT]);
      }
      houseCentre=points.length?[(Math.min(...points.map(p=>p[0]))+Math.max(...points.map(p=>p[0])))*.5,
        (Math.min(...points.map(p=>p[1]))+Math.max(...points.map(p=>p[1])))*.5]:null;
    },
    update(now,season,weather,camera,{target=camera.position,plants=null,date=new Date(),sunAltDeg=90,enabled=true,lawn=true,bearing=180,reduced=motion?.matches}={}){
      if(disposed)return;
      const dt=last===null?0:clamp(finite(now)-last,0,1)*(reduced?.35:1);last=finite(now);clock+=dt;
      const extent=clamp(.75*camera.position.distanceTo(target),18,64);
      uniforms.touchAnchor.value.copy(target);uniforms.touchExtent.value=extent;
      uniforms.touchWind.value.fromArray(precipitationVelocity('snow',weather,bearing));
      const counts=seasonTouchCounts(tier,season,weather,{date,sunAltDeg,enabled});
      if(counts.leaves)collect(plants,camera,target,extent);else sources.length=0;
      const leaf=objects.leaves,la=leaf.geometry.attributes;
      for(let i=0;i<(sources.length?counts.leaves:0);i++){
        const seed=seeds[i],source=sources[i%sources.length];let p=particles[i];
        const fall=7+seed*5,rest=3+seed*2,life=fall+rest;
        if(!p||p.tree!==source.object||p.age>=life){
          const age=p?0:seed*life;
          p=particles[i]={tree:source.object,age,x:source.at.x+Math.sin(i*2.4)*source.height*.18,
            z:source.at.z+Math.cos(i*2.4)*source.height*.18,top:source.at.y+source.height*(.5+seed*.45)};
          p.x+=uniforms.touchWind.value.x*.14*Math.min(age,fall);p.z+=uniforms.touchWind.value.z*.14*Math.min(age,fall);
        }else p.age+=dt;
        if(p.age<fall){p.x+=uniforms.touchWind.value.x*.14*dt;p.z+=uniforms.touchWind.value.z*.14*dt;}
        const ground=finite(groundAt(plan,p.x/FT,-p.z/FT))*FT+.025;
        const flying=p.age<fall,y=flying?Math.max(ground,p.top*(1-p.age/fall)+ground*p.age/fall):ground;
        la.touchPosition.setXYZ(i,p.x,y,p.z);
        la.touchShape.setXYZW(i,seed*6.28+clock*(flying?2:0),flying?clock*(1+seed):Math.PI/2,
          1-clamp((p.age-fall-rest*.5)/Math.max(rest*.5,.001)),.12+seed*.09);
        la.touchColour.setXYZ(i,.38+seed*.25,.07+seed*.23,.012);
      }
      dirty(leaf,sources.length?counts.leaves:0);
      if(!leaf.visible)particles.length=0;
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
    dispose(){if(disposed)return;disposed=true;group.removeFromParent();for(const o of Object.values(objects)){o.geometry.dispose();o.material.dispose();}roots=[];particles.length=0;},
  };
}
