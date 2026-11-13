// Solar conduit input: the roof planes of the involved buildings in lot feet, z up,
// and the solar zones grouped by roof. Routing itself is solar_conduit_core.js.
import {solarPlanes, solarZones, solarPoint, solarRect} from '../twin_solar.js';
import {groundAt} from '../twin_ground.js';
import {lotPoint} from './energy_geometry.js';
import {routeConduits} from './solar_conduit_core.js';
export {ridgeNetwork, CONDUIT_OFFSET} from './solar_conduit_core.js';

const centre=z=>[(z.rect[0]+z.rect[2])/2,(z.rect[1]+z.rect[3])/2];
const samePlane=(a,b)=>a.every((v,i)=>Math.abs(v-b[i])<1e-5);

export function conduitInput(plan,anchors) {
  const empty={planes:[],groups:[],sources:[],source:null};
  if (!anchors?.solar || !anchors.source) return empty;
  const zones=(plan?.buildings||[]).flatMap(building=>solarZones(building).map(({zone})=>({zone,building})));
  const sources=zones.filter(({zone,building})=>zone.roof===anchors.source && (!plan.solar_source_building || building.id===plan.solar_source_building));
  if (!sources.length || new Set(sources.map(s=>s.building.id)).size!==1) return empty;
  const sourceBuilding=sources[0].building.id;
  const satellites=zones.filter(s=>s.building.id!==sourceBuilding || s.zone.roof!==anchors.source);
  if (!satellites.length) return empty;
  const planes=[];
  for (const building of plan.buildings) {
    if (!zones.some(z=>z.building.id===building.id)) continue;
    const sections=(building.roof?.sections||[]).filter(s=>s.state!=='ghost');
    const live=sections.length===(building.roof?.sections||[]).length?building:{...building,roof:{...building.roof,sections}};
    for (const p of solarPlanes(live)) planes.push({building:building.id,roof:p.roof,plane:p.plane,
      tris:p.triangles.map(t=>t.map(uv=>lotPoint(building,solarPoint(p.plane,uv),plan)))});
  }
  const lot=(building,zone,uv)=>lotPoint(building,solarPoint(zone.plane,uv),plan);
  const entry=({zone,building})=>{
    const i=planes.findIndex(p=>p.building===building.id && p.roof===zone.roof && samePlane(p.plane,zone.plane));
    return i<0?null:{plane:i,centre:lot(building,zone,centre(zone)),rect:solarRect(zone.rect).map(uv=>lot(building,zone,uv))};
  };
  // All zones on one roof count as one zone (user, 2026-11-13): one conduit per roof.
  const byRoof=new Map();
  for (const s of satellites) {
    const id=s.building.id+':'+s.zone.roof;
    if (!byRoof.has(id)) byRoof.set(id,{id,zones:[],entities:new Set()});
    const row=byRoof.get(id),e=entry(s); if (e) row.zones.push(e);
    row.entities.add(s.zone.entity||null);
  }
  const groups=[...byRoof.values()].filter(g=>g.zones.length).map(({id,zones,entities})=>({id,zones,
    // One shared power entity drives its own pulse; mixed or missing use total solar.
    entity:entities.size===1?[...entities][0]:null}));
  // The ribbons start at the weighted centre of the main roof's zones. Lift it onto
  // that roof so it never sits inside the house.
  const sourceEntries=sources.map(entry).filter(Boolean);
  const [x,y]=anchors.solar;
  const tops=sourceEntries.map(e=>{
    const t=planes[e.plane].tris[0],u=t[1].map((v,i)=>v-t[0][i]),v=t[2].map((w,i)=>w-t[0][i]);
    const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];
    return Math.abs(n[2])<1e-9?null:t[0][2]-(n[0]*(x-t[0][0])+n[1]*(y-t[0][1]))/n[2];
  }).filter(Number.isFinite);
  const source=tops.length?[x,y,Math.max(anchors.solar[2]??-Infinity,...tops)]:[...anchors.solar];
  return {planes,groups,sources:sourceEntries,source};
}

// Synchronous entry point retained for pure Node tests.
export function solarConduits(plan,anchors,{debug}={}) {
  return routeConduits(conduitInput(plan,anchors),{groundAt,debug});
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
            if (!job.input.groups.length) {finish(job,[]);return;}
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
