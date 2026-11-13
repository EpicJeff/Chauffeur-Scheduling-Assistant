// Coarse structural planes in lot feet, z up. Render-detail meshes are never
// routing input: cladding relief changes with tier and is not the wall plane.
import {solarPlanes, solarZones, solarPoint} from '../twin_solar.js';
import {roofMesh, stepFaces} from '../twin_roof.js';
import {groundAt, inPolygon, buildingFootprint} from '../twin_ground.js';
import {lotPoint} from './energy_geometry.js';
import {routeConduits} from './solar_conduit_core.js';
export {buildSurfaceGraph, surfacePath, trianglePoint, CONDUIT_OFFSET} from './solar_conduit_core.js';

const centre=z=>[(z.rect[0]+z.rect[2])/2,(z.rect[1]+z.rect[3])/2];
const sub=(a,b)=>a.map((v,i)=>v-b[i]);
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const unit=a=>a.map(v=>v/(Math.hypot(...a)||1));

export function planConduitSurfaces(plan,buildingIds=new Set((plan?.buildings||[]).map(b=>b.id))) {
  const result=new Map();
  for (const b of plan?.buildings||[]) {
    if (!buildingIds.has(b.id)) continue;
    const triangles=[],sections=(b.roof?.sections||[]).filter(s=>s.state!=='ghost');
    const building=sections.length===(b.roof?.sections||[]).length?b:{...b,roof:{...b.roof,sections}};
    const emit=(points,kind)=>triangles.push({points:points.map(p=>lotPoint(b,p,plan)),kind,building:b.id});
    for (const plane of solarPlanes(building)) for (const t of plane.triangles) emit(t.map(uv=>solarPoint(plane.plane,uv)),'roof');
    const levels=new Map((b.levels||[]).map(l=>[l.id,l]));
    for (const w of b.walls||[]) {
      if (!w.exterior || w.kind==='separator' || w.state==='ghost' || !w.from || !w.to) continue;
      const l=levels.get(w.level); if (!l) continue;
      const dx=w.to[0]-w.from[0],dy=w.to[1]-w.from[1],length=Math.hypot(dx,dy); if (!length) continue;
      let outward=[dy/length,-dx/length];
      const mid=[(w.from[0]+w.to[0])/2,(w.from[1]+w.to[1])/2],outline=l.outline?.length>=3?l.outline:buildingFootprint(b);
      if (inPolygon(outline,mid[0]+outward[0]*.1,mid[1]+outward[1]*.1)) outward=outward.map(v=>-v);
      let a=w.from,c=w.to;
      if (w.footprint?.length>=4) {
        // Joint footprints are centred on the wall line; their farthest long
        // edge is the actual mitred exterior face, including its corner ends.
        const corners=[...w.footprint].sort((p,q)=>(q[0]-p[0])*outward[0]+(q[1]-p[1])*outward[1]).slice(0,2)
          .sort((p,q)=>(p[0]-q[0])*dx+(p[1]-q[1])*dy);
        [a,c]=corners;
      }
      // Legacy exterior walls already put their OUTSIDE face on from/to;
      // blindly offsetting these by another thickness would move off the house.
      const floor=l.elevation||0,top=floor+(w.height??l.ceiling??8);
      const A=[...a,floor],B=[...c,floor],C=[...c,top],D=[...a,top];
      const forward=(c[1]-a[1])*outward[0]-(c[0]-a[0])*outward[1]>0;
      for (const t of forward?[[A,B,C],[A,C,D]]:[[A,C,B],[A,D,C]]) emit(t,'wall');
    }
    // Reuse the generator's coarse gable ends and roof-step closures, without
    // its siding tessellation, battens, trim, window cutouts or cut variants.
    const mesh=roofMesh(sections);
    for (const positions of mesh.gables.map(g=>g.positions))
      for (let i=0;i+8<positions.length;i+=9) emit([0,3,6].map(j=>Array.from(positions.slice(i+j,i+j+3))),'wall');
    result.set(b.id,triangles);
  }
  return result;
}

export function conduitInput(plan,anchors,triangles=null) {
  const empty={triangles:[],zones:[],sourcePlanes:[],anchor:null,sourceBuilding:null,site:plan?.site};
  if (!anchors?.solar || !anchors.source) return empty;
  const zones=(plan?.buildings||[]).flatMap(building=>solarZones(building).map(({zone})=>({zone,building})));
  const sources=zones.filter(({zone,building})=>zone.roof===anchors.source && (!plan.solar_source_building || building.id===plan.solar_source_building));
  if (!sources.length || new Set(sources.map(s=>s.building.id)).size!==1) return empty;
  const sourceBuilding=sources[0].building.id,satellites=zones.filter(s=>s.building.id!==sourceBuilding || s.zone.roof!==anchors.source);
  if (!satellites.length) return empty;
  const sourcePlanes=sources.map(({zone,building})=>{
    const p=lotPoint(building,solarPoint(zone.plane,[0,0]),plan);
    const u=lotPoint(building,solarPoint(zone.plane,[1,0]),plan),v=lotPoint(building,solarPoint(zone.plane,[0,1]),plan);
    return {p,n:unit(cross(sub(u,p),sub(v,p))),building:building.id};
  });
  const ids=new Set([sourceBuilding,...satellites.map(s=>s.building.id)]);
  return {triangles:triangles||[...planConduitSurfaces(plan,ids).values()].flat(),sourcePlanes,sourceBuilding,anchor:[...anchors.solar],site:plan.site,
    zones:satellites.map(({zone,building})=>({id:building.id+':'+zone.id,entity:zone.entity||null,building:building.id,
      start:lotPoint(building,solarPoint(zone.plane,centre(zone)),plan)}))};
}

// Synchronous entry point retained for pure Node tests and benchmarks.
export function solarConduits(plan,anchors,{triangles=null,debug}={}) {
  return routeConduits(conduitInput(plan,anchors,triangles),{groundAt,debug});
}

function afterPaint(work) {
  const idle=()=>setTimeout(()=>globalThis.requestIdleCallback?globalThis.requestIdleCallback(work,{timeout:100}):work(),0);
  const frame=globalThis.requestAnimationFrame;
  if (frame) frame(()=>frame(idle));
  else setTimeout(idle,16);
}

export function createConduitRouter({urls=globalThis.window?.chfSolarConduitWorker,debug=message=>console.debug(message)}={}) {
  let worker=null,pending=null,serial=0,stopped=false,disabled=false;
  const finish=(job,routes)=>{
    if (pending!==job || stopped) return;
    clearTimeout(job.timer);pending=null;job.resolve(routes);
  };
  function fallback(job) {
    clearTimeout(job.timer);worker?.terminate();worker=null;disabled=true;
    afterPaint(()=>{
      if (pending!==job || stopped) return;
      try {finish(job,routeConduits(job.input,{groundAt,debug}));}
      catch (error) {debug('Solar conduit skipped: '+error.message);finish(job,[]);}
    });
  }
  return {
    run(plan,anchors) {
      if (stopped) return Promise.resolve(null);
      if (pending) {clearTimeout(pending.timer);pending.resolve(null);pending=null;}
      // Snapshot now, prepare the small triangle payload after paint. Neither
      // extraction nor the worker-unavailable fallback can block mount.
      const snapshot=structuredClone({plan,anchors}),id=++serial;
      return new Promise(resolve=>{
        const job=pending={id,resolve,input:null};
        afterPaint(()=>{
          if (pending!==job || stopped) return;
          try {
            job.input=conduitInput(snapshot.plan,snapshot.anchors);
            if (!job.input.zones.length) {finish(job,[]);return;}
            if (!disabled && globalThis.Worker && urls) {
              if (!worker) {
                worker=new Worker(urls.worker,{type:'module',name:'solar-conduit'});
                worker.onmessage=({data})=>{
                  const current=pending;if (!current || data.id!==current.id || stopped) return;
                  if (data.error) {fallback(current);return;}
                  for (const message of data.messages||[]) debug(message);
                  finish(current,data.routes||[]);
                };
                worker.onerror=worker.onmessageerror=()=>{if (pending) fallback(pending);};
              }
              job.timer=setTimeout(()=>{if (pending===job) fallback(job);},5000);
              worker.postMessage({id,coreUrl:urls.core,groundUrl:urls.ground,input:job.input});
            } else fallback(job);
          } catch (error) {
            if (job.input) fallback(job);else {debug('Solar conduit skipped: '+error.message);finish(job,[]);}
          }
        });
      });
    },
    stop() {stopped=true;serial++;worker?.terminate();worker=null;if (pending) {clearTimeout(pending.timer);pending.resolve(null);pending=null;}}
  };
}
