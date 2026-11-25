// Rebuild-only plan geometry. No renderer, DOM, HA state, clocks or randomness.
// Contract: gutterRuns -> {id,building,segments,length,corners,drainsTo?}; downspouts ->
// {id,run,edge,top,mount,path,outlet,share,source,flags,authoredFraction?,authoredIndex?,exact?,merged?}. Plan distances are ft;
// segment/corner/path positions are world metres; segment.outward is local XY.
// top is the outlet at the gutter bottom, centred half the profile width
// outward of the fascia face; path[0] equals top. A vertical outlet drop
// clears the soffit/fascia by 1 in before the offset elbows head to the wall.
// Mounted downspouts end in a short curved elbow: wallBottom sits 0.5 ft
// above the receiving surface and outlet.at is GUTTER.elbowFt (0.5 ft) out
// from the wall/post mount, 4 in above the surface, with horizontal outlet.dir.
// If the straight mouth lands on a walkway, path, step or stair, the elbow
// swivels up to 90 degrees along the wall toward grass or a bed.
// A 'stub' outlet clears its actual receiving surface by 1 in. If the gutter
// bottom is at/below surface + 2 in, 'outlet-blocked' marks a zero-length hole:
// top/path[0]/outlet.at are raised to max(gutter bottom, surface + 1 in), capped
// at drip line - 1 in. No inward offset or wall drop is attempted there.
// Live runs reuse the supplied roofs. Serialised runs have no context and
// downspouts(plan, serialisedRuns) rebuilds plan-only (roofs = null).
// gutterRuns(plan, roofs, prebuilt = null) accepts optional immutable inputs:
// buildingBases: Map<auto-foundation building ID, resolved base in plan ft,
// including offsets>; entries for manual bases are ignored.
// landingSampler: (worldMetresPoint) -> {height, kind, roofEave?}, as returned
// by createEaveLandingSampler(samePlan, sameRoofs, {roofDetails:true}). These
// must describe this exact plan/roof revision; absent fields use normal builds.
// Run IDs are building:roof:firstEdge or building:porch:porchId. When clipping
// disconnects an edge, the lowest authored start fraction keeps that ID and
// later pieces receive ~2, ~3, ... in fraction order (also for porch runs).
// Downspout IDs are always `${runId}:${k}`.
// Shared corners join within 3 in on the same authored roof/section/attachment;
// different roofs retain the 2 in tolerance. Distances still use runJoinFt.
// downspouts() annotates a run without an owned outlet with drainsTo: spout ID.
// Prefer an adjacent outlet at/below its end, otherwise the nearest in the
// building. Owned outlets clear stale drainsTo. Catchment uses run length:
// split an owning run equally, add each linked run to its receiving outlet,
// then normalise share across that owner's outlet set (sum 1 for that set).
// If every outlet in a building is suppressed, keep one flagged 'no-outlet'
// emergency stub as a drainage target; stored overrides remain untouched.
// Corner claims group a building's plan vertex and eave height within 3 in.
// Each group uses one receiving-floor band: the lowest surface over its faces.
// Stacked eaves at different heights stay distinct. Authored overrides precede
// automatic claims. Colliding numeric overrides keep one spout, flagged 'merged-override',
// with merged: [{run, fraction, roof, edge, porch}] recording each dropped run,
// authored fraction and owning edge/attachment.
// Override records also carry authoredFraction: the stored request before it
// snaps to edge.fraction, and authoredIndex (the stored list index).
// {at:f} entries have exact:true: nearest exposed point of that edge, never
// claimed/merged/target-limited. They suppress automatic outlets within 1 ft.
// Fractions use the authored A--B line; exactly 0/1 name exposed drip tips.
// Off-corner distance uses authored feet, counting each tip as its vertex.
// Main's first-face/clamped/<=1 ft corner tier wins unchanged when non-empty;
// only empty tiers open the new corner/clearance and free-end fallbacks.
// Door avoidance always uses the original clamped wall distance.
// Exact drops warn placed-off-corner, over-opening (0.5 ft), no-support (free).
// mount:'free' is a full vertical pipe below the outlet with the normal outward
// elbow, drawn in the existing trim batch. Exact drops never flag hang/stub;
// only a receiver under the gutter can block one. High mount-side receivers
// try another support, then free. Numbers keep corner snapping.
// Corners use the union of footprints below the eave and above the receiving
// roof (when a drop ends on one), sampled at local (+/-0.3, +/-0.3) ft:
// one occupied quadrant is outside, three inner. Filled inner vertices vanish.
// Hangs are emergency stubs (flags 'hang', 'stub'), with no kick-out geometry.
// Their outlet.at is just below the gutter, not at the receiving surface: the
// renderer must use the landing sampler to find the falling water's length.
import { extractEaves, clipExposedEdges, createEaveClipper, createEaveLandingSampler } from './sky/eave_streams.js';
import { roofMeshGroups, supportedRoofAbove, supportedRoofCutters, roofBounds, endKind, heightAt, sectionHeight, authoredRoofShape } from './twin_roof.js';
import { prepareUnderside } from './roof_underside.js';
import { isSupported, roofPoint, supportPoints } from './roof_supports.js';
import { allPorches, buildingHasGutters, planHasGutters } from './gutter_presence.js';
export { buildingHasGutters } from './gutter_presence.js';
import { FASCIA, ROOF_THICKNESS } from './trim_dims.js';
import { withoutSurfaceMaterials, fingerprint } from './bake/geometry_key.js';
import { buildingBase, inPolygon, edgeDistance } from './twin_ground.js';
import { pathOutline, pathSurfacePolygons } from './path_shapes.js';
import { paverSettings } from './paver_layout.js';

export const GUTTER = { runJoinFt: 0.3, runJoinHeightIn: 2, spanFt: 35, maxOverhangFt: 4,
  openingClearFt: 1, openingClearMinFt: 0.5, doorAvoidFt: 6, elbowFt: 0.5, profileIn: 5, spoutIn: [2, 3],
  fasciaFt: FASCIA.depthFt, fasciaProudFt: FASCIA.proudFt, soffitClearIn: 1 };

const GUTTER_BUILDING_FIELDS = ['id', 'position', 'rotation', 'base', 'foundation', 'levels', 'rooms', 'walls', 'joints', 'openings', 'stairs', 'roof', 'roofs', 'porch', 'porches'];
const GUTTER_SITE_FIELDS = ['hardscape', 'paths', 'beds', 'pool', 'terraces', 'lot', 'edges'];
const gutterPlacementCache = new Map();
const emptyPlacement = { runs: [], spouts: [] };
let objectKeys = new WeakMap();

export const _gutterPlacementStats = {
  calls: 0,
  hits: 0,
  lastPlacementMs: 0,
  lastGeometryMs: 0,
  reset() { this.calls = 0; this.hits = 0; this.lastPlacementMs = 0; this.lastGeometryMs = 0; },
  clearCache() { gutterPlacementCache.clear(); objectKeys = new WeakMap(); this.reset(); },
};

function gutterInputKey(plan) {
  const clean = withoutSurfaceMaterials(plan || {});
  const canonical = value => {
    if (Array.isArray(value)) return value.map(canonical);
    if (!value || typeof value !== 'object') return value;
    return Object.fromEntries(Object.keys(value).sort().filter(k => !['gutter_ack', 'src'].includes(k)).map(k => [k, canonical(value[k])]));
  };
  const site = clean.site && Object.fromEntries(GUTTER_SITE_FIELDS.filter(k => k in clean.site).map(k => [k, clean.site[k]]));
  const buildings = (clean.buildings || []).map(b =>
    Object.fromEntries(GUTTER_BUILDING_FIELDS.filter(k => k in b).map(k => [k, b[k]]))
  );
  const h = fingerprint();
  h.add(JSON.stringify(canonical({
    dims: [GUTTER, FASCIA],
    site,
    buildings,
  })));
  return h.key();
}

function gutterMemoKey(plan) {
  const dims = JSON.stringify([GUTTER, FASCIA]);
  let memo = objectKeys.get(plan);
  if (!memo || memo.dims !== dims) { memo = { dims, key: gutterInputKey(plan) }; objectKeys.set(plan, memo); }
  return memo.key;
}

// Closed Check may read the renderer's result, but cannot start placement.
// This reads the same bounded memo; it owns no second cache or result.
export function cachedGutterPlacement(plan) {
  return !planHasGutters(plan) ? emptyPlacement : gutterPlacementCache.get(gutterMemoKey(plan)) || null;
}

export function gutterPlacement(plan, timing = null) {
  if (!planHasGutters(plan)) return emptyPlacement;
  const key = gutterMemoKey(plan);
  if (gutterPlacementCache.has(key)) {
    _gutterPlacementStats.hits++;
    return gutterPlacementCache.get(key);
  }
  const t0 = performance.now();
  const runs = gutterRuns(plan, null);
  const spouts = runs.length ? downspouts(plan, runs) : [];
  const ms = performance.now() - t0;
  _gutterPlacementStats.calls++;
  _gutterPlacementStats.lastPlacementMs += ms;
  if (timing) timing.gutter_placement_ms = (timing.gutter_placement_ms || 0) + ms;
  const result = { runs, spouts };
  if (gutterPlacementCache.size >= 16) gutterPlacementCache.delete(gutterPlacementCache.keys().next().value);
  gutterPlacementCache.set(key, result);
  return result;
}


const FT=.3048, EPS=1e-5, SIDES=['y0','x1','y1','x0'];
const add=(a,b)=>a.length===2?[a[0]+b[0],a[1]+b[1]]:[a[0]+b[0],a[1]+b[1],a[2]+b[2]];
const sub=(a,b)=>a.length===2?[a[0]-b[0],a[1]-b[1]]:[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
const mul=(a,k)=>a.length===2?[a[0]*k,a[1]*k]:[a[0]*k,a[1]*k,a[2]*k];
const dot=(a,b)=>a.length===2?a[0]*b[0]+a[1]*b[1]:(a[0]*b[0]+a[1]*b[1])+a[2]*b[2];
const dist=(a,b)=>a.length===2?Math.hypot(a[0]-b[0],a[1]-b[1]):Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
const unit=a=>mul(a,1/(Math.hypot(...a)||1)),cross=(a,b)=>a[0]*b[1]-a[1]*b[0];
const clamp=x=>Math.max(0,Math.min(1,x));
const key=p=>p.map(v=>v.toFixed(5)).join(',');
const compare=(a,b)=>a<b?-1:a>b?1:0;
const runContexts=new WeakMap();
const candidateSets=new WeakMap();
export function gutterCandidates(plan) {
  return candidateSets.get(gutterPlacement(plan).runs) || [];
}
const placementKey=plan=>JSON.stringify([plan.buildings,plan.site]);
const settled=p=>p.state!=='ghost'&&p.state!=='proposal';
const endpointsTouch=(a,p,b,q,originA,originB)=>Math.hypot(p[0]-q[0],p[2]-q[2])<=GUTTER.runJoinFt*FT+EPS
  &&Math.abs(p[1]-q[1])<=((a.roof!==null&&a.roof===b.roof||originA===originB)?3:GUTTER.runJoinHeightIn)/12*FT+EPS;
function frame(plan,b){
  const angle=(b.rotation||0)*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle),p=b.position||[0,0],base=buildingBase(plan,b);
  return {b,base,world:([x,y,z])=>[(p[0]+c*x-s*y)*FT,(base+z)*FT,-(p[1]+s*x+c*y)*FT],
    local:([x,y,z])=>{const u=x/FT-p[0],v=-z/FT-p[1];return [c*u+s*v,-s*u+c*v,y/FT-base];},
    outward:([x,,z])=>[c*x-s*z,-s*x-c*z]};
}
function wallsOf(b){
  const joints=new Map((b.joints||[]).map(j=>[j.id,j.at]));
  return (b.walls||[]).filter(settled).map(w=>({...w,
    from:w.from||joints.get(w.joints?.[0]),to:w.to||joints.get(w.joints?.[1])})).filter(w=>w.from&&w.to&&dist(w.from,w.to)>EPS);
}
function outlines(b,walls,level){
  const l=b.levels?.find(l=>l.id===level);
  if(l?.outline?.length>=3)return [l.outline];
  // Outline graph edges are not required to have a consistent winding.
  const pending=walls.filter(w=>w.level===level).map(w=>[w.from,w.to]),result=[];
  while(pending.length){const [a,d]=pending.shift(),poly=[a,d];
    while(dist(poly.at(-1),poly[0])>.02){const i=pending.findIndex(e=>e.some(p=>dist(p,poly.at(-1))<.02));if(i<0)break;
      const e=pending.splice(i,1)[0];poly.push(dist(e[0],poly.at(-1))<.02?e[1]:e[0]);}
    if(poly.length>=4&&dist(poly.at(-1),poly[0])<.02)result.push(poly.slice(0,-1));
  }
  return result;
}
function wallNormal(w,polys){
  const d=unit(sub(w.to,w.from)),right=[d[1],-d[0]],mid=mul(add(w.from,w.to),.5);
  return mul(right,polys.some(p=>inPolygon(p,...add(mid,mul(right,.1))))?-1:1);
}
// Union membership needs no polygon tessellation. Include edge intersections:
// an attached porch can introduce a concave vertex in the middle of a wall.
function footprint(polys){
  const points=new Map(polys.flat().map(p=>[key(p),p]));
  const edges=polys.flatMap(p=>p.map((a,i)=>[a,p[(i+1)%p.length]]));
  for(let i=0;i<edges.length;i++)for(let j=i+1;j<edges.length;j++){
    const [a,b]=edges[i],[c,d]=edges[j],v=sub(b,a),w=sub(d,c),den=cross(v,w);if(Math.abs(den)<EPS)continue;
    const t=cross(sub(c,a),w)/den,u=cross(sub(c,a),v)/den;
    if(t>=-EPS&&t<=1+EPS&&u>=-EPS&&u<=1+EPS){const at=add(a,mul(v,t));points.set(key(at),at);}
  }
  const corners=[];
  for(const [id,at] of points){let count=0;
    for(const x of [-.3,.3])for(const y of [-.3,.3])if(polys.some(p=>inPolygon(p,at[0]+x,at[1]+y)))count++;
    if(count===1||count===3)corners.push({at,convex:count===1,key:id});
  }
  return {polys,corners};
}
function prepare(plan,provided){
  const contexts=new Map(),regions=hardRegions(plan);
  for(const b of plan.buildings||[]){
    const rawWalls=wallsOf(b),f=frame(plan,b),porches=allPorches(b).filter(settled),levels=(b.levels||[]).map(l=>({...l,polys:outlines(b,rawWalls,l.id)}));
    const walls=[],mountWalls=[];
    for(const l of levels){
      const edges=l.polys.flatMap(p=>p.map((from,i)=>({from,to:p[(i+1)%p.length]})));
      const real=rawWalls.filter(w=>w.level===l.id).flatMap(w=>{
        const v=unit(sub(w.to,w.from)),length=dist(w.from,w.to);
        const edge=edges.find(e=>Math.abs(cross(v,unit(sub(e.to,e.from))))<Math.sin(.5*Math.PI/180)
          &&Math.abs(cross(v,sub(e.from,w.from)))<.05
          &&Math.min(length,Math.max(dot(sub(e.from,w.from),v),dot(sub(e.to,w.from),v)))
            -Math.max(0,Math.min(dot(sub(e.from,w.from),v),dot(sub(e.to,w.from),v)))>.02);
        return edge?[{...w,normal:wallNormal(edge,l.polys)}]:[];
      });
      for(const w of [...real,...edges.filter(e=>!real.some(w=>edgeDistance(e.from,w.from,w.to)<.05&&edgeDistance(e.to,w.from,w.to)<.05))
        .map((e,i)=>({...e,id:`outline:${l.id}:${i}`,level:l.id,synthetic:true}))]){
        const item={...w,floor:l.elevation||0,top:(l.elevation||0)+(w.height??l.ceiling??0),normal:w.normal||wallNormal(w,l.polys)};
        mountWalls.push(item);if(!w.synthetic)walls.push(item);
      }
    }
    const openingWalls=walls.map(w=>({...w,openings:(b.openings||[]).filter(o=>o.wall===w.id&&settled(o))})).filter(w=>w.openings.length);
    const ctx={plan,b,f,porches,levels,walls,mountWalls,openingWalls,regions,footprints:new Map(),info:new Map(),drops:new Map(),contexts};
    const cached=provided?.get(b.id),sections=cached?.sections||b.roof?.sections||[];
    ctx.sections=sections;
    ctx.hasSupported=sections.some(isSupported);
    ctx.walledSections=ctx.hasSupported?sections.filter(s=>!isSupported(s)):sections;
    if(ctx.hasSupported){
      const polygons=new Map(levels.map(level=>[level.id,level.polys]));
      const cuts=new Map(sections.filter(isSupported).map(section=>
        [section,supportedRoofCutters(section,levels,polygons,section.thickness_ft??ROOF_THICKNESS)]));
      const ceilings=new Map();
      for(const section of sections.filter(isSupported)){
        const id=section.roof||section.id;
        if(ceilings.has(id))continue;
        const siblings=sections.filter(s=>(s.roof||s.id)===id),last=siblings.at(-1);
        const record=b.roofs?.find(r=>r.id===id)||last;
        const prepared=prepareUnderside(authoredRoofShape(record,last),{
          slabBottomAt:(x,y)=>{const z=heightAt(siblings,x,y);return z===null?null:z-(last.thickness_ft??ROOF_THICKNESS);},
          recordEdges:record.edges,
        });
        ceilings.set(id,prepared?.hasFlat?prepared.ceilingZ:null);
      }
      ctx.supportOptions={cuts:section=>cuts.get(section)||[],thickness:ROOF_THICKNESS,underside:true,
        ceilingAt:section=>ceilings.get(section.roof||section.id)??null};
    }
    // Compute each union once for each distinct set of levels below an eave.
    ctx.footprint=(height,floor=-Infinity)=>{const below=levels.filter(l=>(l.elevation||0)<=height+EPS&&(l.elevation||0)>=floor-EPS);
      const eligiblePorches=porches.filter(p=>(p.floor||0)>=floor-EPS&&(p.floor||0)<=height+EPS);
      const id=JSON.stringify([below.map(l=>l.id),eligiblePorches.map(p=>p.id)]);
      if(!ctx.footprints.has(id))ctx.footprints.set(id,footprint([...below.flatMap(l=>l.polys),...eligiblePorches.map(p=>p.polygon)].filter(p=>p?.length>=3)));
      return ctx.footprints.get(id);};
    contexts.set(b.id,ctx);
  }
  return contexts;
}
function projection(p,a,b){const v=sub(b,a),t=clamp(dot(sub(p,a),v)/(dot(v,v)||1));return {at:add(a,mul(v,t)),t};}
function eaveSide(s,side){
  return SIDES.includes(side)&&(s.kind==='flat'||s.kind==='shed'&&s.low_side===side
    ||['hip','gable'].includes(s.kind)&&(side[0]!==s.ridge||endKind(s,side)==='hip'));
}
export function eaveEdgeIndices(building, roof) {
  const sections = building.roof?.sections?.filter(s => (s.roof || s.id) === roof.id) || [];
  return roof.edges.flatMap((edge, index) => edge.setting === 'sloped' && (!sections.length || sections.some(s =>
    SIDES.some(side => (s.plane_edges ? s.plane_edges[side] : SIDES.indexOf(side)) === index && eaveSide(s, side)))) ? [index] : []);
}
function source(b,s,side){
  const id=s.roof||s.id,edge=s.plane_edges? s.plane_edges[side]:SIDES.indexOf(side),r=id==null?null:b.roofs?.find(r=>r.id===id);
  return {id,edge:Number.isInteger(edge)?edge:null,record:r?.edges?.[edge],roof:r};
}

function snapshots(contexts,provided){
  const result=new Map();
  for(const {b} of contexts.values()){
    const cached=provided?.get(b.id),sections=cached?.sections||b.roof?.sections||[],base=cached?.positions?cached:roofMeshGroups(sections);
    const eaveAttachments=cached?.eaveAttachments||[];
    result.set(b.id,{...base,...cached,sections,eaveAttachments,
      coverPositions:cached?.coverPositions||[...base.positions,...eaveAttachments.flatMap(a=>Array.from(a.positions))]});
  }
  return result;
}
function segmentSource(b,s,raw){
  if(isSupported(s||{})&&!settled(s))return null;
  if(!eaveSide(s,raw.side))return null;
  const src=source(b,s,raw.side);
  if(src.edge!==null&&(src.record?src.record.gutter===true&&src.record.setting==='sloped':s.gutters?.[raw.side]===true))
    return {roof:src.id,edge:src.edge,porch:null};
  // A porch's own roof is identified by its bearing rectangle, never by a
  // house eave that merely happens to pass above part of a porch floor.
  const centre=[(s.rect[0]+s.rect[2])/2,(s.rect[1]+s.rect[3])/2];
  const p=allPorches(b).find(p=>p.gutter===true&&settled(p)&&p.polygon?.length>=3&&inPolygon(p.polygon,...centre));
  return p?{roof:null,edge:null,porch:p.id}:null;
}
function segmentInfo(ctx,segment){
  const {b}=ctx,id=`${segment.roof}:${segment.edge}:${segment.porch}`;
  if(ctx.info.has(id))return ctx.info.get(id);
  let info;
  if(segment.porch!==null){
    const p=ctx.porches.find(p=>p.id===segment.porch);
    const sections=ctx.sections.filter(s=>p&&inPolygon(p.polygon,(s.rect[0]+s.rect[2])/2,(s.rect[1]+s.rect[3])/2));
    info={overhang:Math.max(0,...sections.map(s=>s.overhang||0)),sections};
  }else{
    const r=b.roofs?.find(r=>r.id===segment.roof),sections=ctx.sections.filter(s=>(s.roof||s.id)===segment.roof);
    const section=sections.find(s=>SIDES.some(side=>source(b,s,side).edge===segment.edge));
    const side=section&&SIDES.find(side=>source(b,section,side).edge===segment.edge);
    info={overhang:r?.edges?.[segment.edge]?.overhang_ft
      ??section?.edges?.[SIDES.indexOf(side)]?.overhang_ft??r?.overhang??sections[0]?.overhang??0,sections};
  }
  ctx.info.set(id,info);return info;
}
function segmentOrigin(ctx,segment){
  if(segment.roof!==null)return `roof:${segment.roof}`;
  const info=segmentInfo(ctx,segment);
  // Recover section ownership for supplied/serialised porch runs without
  // adding provenance fields to the public segment contract.
  const p=ctx.f.local(mul(add(segment.a,segment.b),.5));
  const sections=info.sections.map(s=>{const [x0,y0,x1,y1]=roofBounds(s);
    const x=Math.max(x0,Math.min(x1,p[0])),y=Math.max(y0,Math.min(y1,p[1]));
    return {s,gap:Math.hypot(x-p[0],y-p[1],heightAt([s],x,y)-p[2])};})
    .sort((a,b)=>a.gap-b.gap||ctx.sections.indexOf(a.s)-ctx.sections.indexOf(b.s));
  return sections.length?`section:${ctx.sections.indexOf(sections[0].s)}`:segment;
}
function dropFootprint(ctx,segment,at){
  const id=`${segment.roof}:${segment.edge}:${segment.porch}:${key(at)}`;
  if(!ctx.drops.has(id)){
    const p=ctx.f.local(at),mount=mountAt(ctx,segment,at,null),start=ctx.f.world([...mount.at,p[2]-.15]);
    const support=sampleAt(ctx,start),end=sampleAt(ctx,ctx.f.world([...add(mount.at,mul(mount.normal,GUTTER.elbowFt)),p[2]-.16]));
    const roofs=[support,end].filter(v=>v.kind==='roof');
    const floor=roofs.length?Math.max(...roofs.map(v=>(v.roofEave??v.height)/FT-ctx.f.base)):-Infinity;
    ctx.drops.set(id,{...ctx.footprint(p[2],floor),floor});
  }
  return ctx.drops.get(id);
}
// A roof's opposite parallel eave can route to its explicitly bound wall.
// This is a measured host gap, separate from each edge's authored overhang.
function hostWallReach(ctx,segment,w){
  const oh=segmentInfo(ctx,segment).overhang;
  if(!ctx.hasSupported)return oh;
  const roof=segment.roof==null?null:ctx.b.roofs?.find(r=>r.id===segment.roof)
    ||ctx.sections.find(s=>(s.roof||s.id)===segment.roof);

    if(!roof||!isSupported(roof)||w.id!==roof.host?.wall||segment.edge===roof.host.edge)return oh;
    const r=roof.rect,area=roof.area||[[r[0],r[1]],[r[2],r[1]],[r[2],r[3]],[r[0],r[3]]];
    const index=edge=>roof.area?edge:SIDES.findIndex(side=>source(ctx.b,roof,side).edge===edge);
    const i=index(roof.host.edge),j=index(segment.edge);
    if(i<0||j<0||!area[i]||!area[j])return oh;
    const a=roofPoint(roof,area[i]),b=roofPoint(roof,area[(i+1)%area.length]);
    const c=roofPoint(roof,area[j]),d=roofPoint(roof,area[(j+1)%area.length]);
    const u=sub(b,a),v=sub(d,c),length=dist(w.from,w.to);
    if(dot(u,v)>=0||Math.abs(u[0]*v[1]-u[1]*v[0])>1e-6*Math.hypot(...u)*Math.hypot(...v))return oh;
    const mid=mul(add(c,d),.5),wv=sub(w.to,w.from),gap=Math.abs(wv[0]*(mid[1]-w.from[1])-wv[1]*(mid[0]-w.from[0]))/length;
    return Math.max(oh,gap+oh);

}
function cornerReach(ctx,segment){
  const oh=segmentInfo(ctx,segment).overhang;
  if(!ctx.hasSupported||!segmentInfo(ctx,segment).sections.some(isSupported))return oh;
  return Math.max(oh,...ctx.mountWalls.map(w=>hostWallReach(ctx,segment,w)));
}
function endpointCorner(ctx,segment,at){
  const p=ctx.f.local(at),oh=cornerReach(ctx,segment);
  return dropFootprint(ctx,segment,at).corners.filter(c=>Math.max(...sub(c.at,p.slice(0,2)).map(Math.abs))<=oh+1+EPS)
    .sort((a,b)=>dist(a.at,p.slice(0,2))-dist(b.at,p.slice(0,2))||compare(a.key,b.key))[0]||null;
}
function cutEnd(ctx,segment,at){
  // Query the same clipped mesh as the streams, both at the lip and on the
  // eave line. Flush cross-gables can cut the mesh without covering the lip.
  const other=dist(at,segment.a)<EPS?segment.b:segment.a,tangent=unit(sub(at,other));
  const tip=ctx.f.world([...segment.outward,0]),origin=ctx.f.world([0,0,0]),normal=unit(sub(tip,origin));
  return [0,-.012].some(offset=>{const probe={a:add(add(at,mul(tangent,.05*FT)),mul(normal,offset)),
    b:add(add(at,mul(tangent,.15*FT)),mul(normal,offset)),outward:normal,gridStart:0};
    return ctx.clip([probe]).reduce((n,s)=>n+dist(s.a,s.b),0)<.05*FT;});
}

export function gutterRuns(plan={},roofs=null,prebuilt=null){
  const original=plan,signature=placementKey(plan);
  plan=placementPlan(plan,prebuilt);
  const contexts=prepare(plan,roofs),surfaces=snapshots(contexts,roofs),frames=[...contexts.values()].map(c=>c.f),raw=extractEaves(plan,surfaces),flat=[];
  const sample=memoSampler(plan,surfaces,prebuilt);
  for(const ctx of contexts.values())ctx.sample=sample;
  // Flat roofs have no downhill stream edge. Explicitly enabled perimeter
  // gutters still use the same exposure clip, without changing stream rules.
  for(const f of frames)for(const [section,s] of surfaces.get(f.b.id).sections.entries())if(s.kind==='flat'){
    const [x0,y0,x1,y1]=roofBounds(s),p=[[x0,y0,s.plate],[x1,y0,s.plate],[x1,y1,s.plate],[x0,y1,s.plate]];
    SIDES.forEach((side,i)=>{const n=[[0,-1],[1,0],[0,1],[-1,0]][i],tip=f.world([...n,0]),origin=f.world([0,0,0]);
      flat.push({a:f.world(p[i]),b:f.world(p[(i+1)%4]),building:f.b.id,section,side,kind:'flat',gridStart:0,
        outward:[tip[0]-origin[0],0,tip[2]-origin[2]]});});
  }
  raw.push(...clipExposedEdges(flat,frames,surfaces));
  const output=[];
  for(const f of frames){
    const b=f.b,sections=surfaces.get(b.id).sections,ctx=contexts.get(b.id),seen=new Set(),origins=new WeakMap();
    const segments=raw.filter(e=>e.building===b.id).flatMap(e=>{
      const src=segmentSource(b,sections[e.section],{...e,frame:f});if(!src)return [];
      const k=[e.a,e.b].map(key).sort().join(':');if(seen.has(k))return [];seen.add(k);
      const segment={...src,a:[...e.a],b:[...e.b],outward:unit(f.outward(e.outward))};
      origins.set(segment,e.kind==='attachment'?`attachment:${src.porch}`:`section:${e.section}`);
      return [segment];
    }).sort((a,b)=>compare(`${a.roof??''}:${a.porch??''}`,`${b.roof??''}:${b.porch??''}`)||(a.edge??0)-(b.edge??0)
      ||Math.min(edgeFraction(ctx,a,a.a),edgeFraction(ctx,a,a.b))-Math.min(edgeFraction(ctx,b,b.a),edgeFraction(ctx,b,b.b))
      ||compare(key(a.a),key(b.a)));
    const touches=(a,p,b,q)=>endpointsTouch(a,p,b,q,origins.get(a),origins.get(b));
    const reverse=s=>{const flipped={...s,a:s.b,b:s.a};origins.set(flipped,origins.get(s));return flipped;};
    const remaining=new Set(segments),usedIds=new Map();
    while(remaining.size){
      const seed=remaining.values().next().value,component=[seed];remaining.delete(seed);
      for(let i=0;i<component.length;i++)for(const other of remaining)
        if([component[i].a,component[i].b].some(p=>[other.a,other.b].some(q=>touches(component[i],p,other,q)))){component.push(other);remaining.delete(other);}
      const ordered=[],todo=new Set(component);
      let start=component.find(s=>[s.a,s.b].some(p=>!component.some(o=>o!==s&&[o.a,o.b].some(q=>touches(s,p,o,q)))))||component[0];
      const endFree=!component.some(o=>o!==start&&[o.a,o.b].some(q=>touches(start,start.b,o,q)));
      if(endFree)start=reverse(start);
      todo.delete(component.find(s=>s===start||s.a===start.b&&s.b===start.a));ordered.push(start);
      while(todo.size){const last=ordered.at(-1),tail=last.b,next=[...todo].find(s=>touches(last,tail,s,s.a)||touches(last,tail,s,s.b));
        if(!next){ordered.push(...todo);break;}todo.delete(next);ordered.push(touches(last,tail,next,next.a)?next:reverse(next));}
      const first=component[0],base=first.porch!==null?`${b.id}:porch:${first.porch}`:`${b.id}:${first.roof}:${first.edge}`;
      const serial=usedIds.get(base)||0;usedIds.set(base,serial+1);
      // Disconnected exposed pieces of the same authored edge need distinct
      // deterministic run IDs; the contract's unsuffixed ID is the first one.
      const id=serial?`${base}~${serial+1}`:base,corners=[],cornerKeys=new Set();
      ordered.forEach((s,segIndex)=>{for(const at of [s.a,s.b]){const c=endpointCorner(ctx,s,at),k=key(at);
        if(c&&!cornerKeys.has(k)){cornerKeys.add(k);corners.push({at:[...at],convex:c.convex,segIndex});}}});
      output.push({id,building:b.id,segments:ordered,length:ordered.reduce((n,s)=>n+dist(s.a,s.b)/FT,0),corners});
    }
  }
  output.sort((a,b)=>compare(a.id,b.id));
  runContexts.set(output,{original,signature,plan,contexts,surfaces});
  return output;
}

// The shared path builder's predicates with a bounding-box broad phase, which
// also drops rounding-noise false crossings on straight diagonal smooth paths.
// The resulting outline/swept receivers cover the same area; exact internal
// seam hits can differ. Non-simple paths still use the shared swept builder.
function pathPolygons(h){
  const poly=pathOutline(h),edges=poly.map((a,i)=>{const b=poly[(i+1)%poly.length];
    return {a,b,x0:Math.min(a[0],b[0]),x1:Math.max(a[0],b[0]),y0:Math.min(a[1],b[1]),y1:Math.max(a[1],b[1])};});
  const side=(a,b,c)=>cross(sub(b,a),sub(c,a));
  const on=(p,a,b)=>Math.abs(side(a,b,p))<1e-8&&p.every((v,i)=>v>=Math.min(a[i],b[i])-1e-8&&v<=Math.max(a[i],b[i])+1e-8);
  for(let i=0;i<edges.length;i++){
    const e=edges[i],{a,b}=e;if(dist(a,b)<1e-8)return pathSurfacePolygons(h);
    for(let j=i+2;j<edges.length;j++){
      if(i===0&&j===edges.length-1)continue;const f=edges[j],{a:c,b:d}=f;
      if(e.x1<f.x0-1e-8||f.x1<e.x0-1e-8||e.y1<f.y0-1e-8||f.y1<e.y0-1e-8)continue;
      if(side(a,b,c)*side(a,b,d)<0&&side(c,d,a)*side(c,d,b)<0||on(c,a,b)||on(d,a,b)||on(a,c,d)||on(b,c,d))return pathSurfacePolygons(h);
    }
  }
  return poly.length>=4?[poly]:pathSurfacePolygons(h);
}
function placementPlan(plan,prebuilt=null){
  // Keep authored data untouched. Non-paver paths can feed their exact receiver
  // polygons to both the landing sampler and hard-region classifier once.
  const hardscape=(plan.site?.hardscape||[]).flatMap(h=>h.kind==='path'&&!paverSettings(h)
    ?pathPolygons(h).map(polygon=>({...h,kind:'gutter-path',polygon})): [h]);
  // Resolve auto foundations once, then share the exact base with every query.
  const buildings=(plan.buildings||[]).map(b=>{
    if(b.foundation?.mode!=='auto')return b;
    const supplied=prebuilt?.buildingBases?.get(b.id);
    if(Number.isFinite(supplied))return {...b,base:supplied,foundation:{...b.foundation,mode:'manual'}};
    return {...b,base:buildingBase(plan,b),foundation:{...b.foundation,mode:'manual'}};
  });
  return {...plan,buildings,site:{...plan.site,hardscape}};
}
function memoSampler(plan,surfaces,prebuilt=null){
  const sample=prebuilt?.landingSampler||createEaveLandingSampler(plan,surfaces,{roofDetails:true}),hits=new Map();
  return at=>{const id=at.join(',');if(!hits.has(id))hits.set(id,sample(at));return hits.get(id);};
}
function hardRegions(plan){
  return (plan.site?.hardscape||[]).flatMap(h=>(h.kind==='path'?pathSurfacePolygons(h):[h.polygon])
    .filter(p=>p?.length>=3).map(polygon=>({polygon,kind:h.kind==='driveway'||h.preset==='driveway'?'driveway'
      :['patio','terrace'].includes(h.kind)||['patio','terrace'].includes(h.preset)?'patio':'hard'})));
}
function stairContains(b,p){
  return (b.stairs||[]).some(s=>{if(s.polygon)return inPolygon(s.polygon,...p);
    if(!s.from||!s.to)return false;const q=projection(p,s.from,s.to);return dist(q.at,p)<(s.width||3)/2+.15;});
}
function sampleAt(ctx,at){
  const hit=ctx.sample(at);
  let best=null;
  // roofMesh clips lower roofs in 2D under an upper roof's overhang; recover the
  // continuous flashed lower-roof plane analytically when an elbow lands under it.
  for(const c of ctx.contexts.values()){
    const q=c.f.local(at);
    for(const s of c.sections){
      const z=sectionHeight(s,q[0],q[1]);
      if(z===null)continue;
      const h=(c.f.base+z)*FT;
      if(h>=at[1]-.005||h<=hit.height)continue;
      if(!best||h>best.height){
        const bounds=roofBounds(s);
        const eaveZ=s.edges?.some(edge=>edge?.overhang_ft!==undefined)
          ?Math.min(...[[bounds[0],bounds[1]],[bounds[2],bounds[1]],[bounds[2],bounds[3]],[bounds[0],bounds[3]]]
            .map(point=>sectionHeight(s,...point)))
          :s.plate-(s.overhang||0)*((s.pitch||0)/12);
        best={height:h,kind:'roof',roofEave:(c.f.base+eaveZ)*FT};
      }
    }
  }
  return best||hit;
}
function landing(ctx,at){
  const hit=sampleAt(ctx,at),world=[at[0]/FT,-at[2]/FT],p=ctx.f.local(at).slice(0,2);
  if([...ctx.contexts.values()].some(c=>stairContains(c.b,c.f.local(at).slice(0,2))))return {...hit,lands:'hard',allowed:false};
  if(hit.kind==='water'||hit.kind==='cap')return {...hit,lands:'hard',allowed:false};
  if(hit.kind==='roof'||hit.kind==='deck')return {...hit,lands:hit.kind,allowed:true};
  if(ctx.plan.site?.pool?.polygon&&inPolygon(ctx.plan.site.pool.polygon,...world))return {...hit,lands:'hard',allowed:false};
  // Use the sampler's height ordering: a raised bed wins over paving; a
  // ground-level bed cannot erase the walkway that actually draws above it.
  if(hit.kind==='bed')return {...hit,lands:'bed',allowed:true};
  const hard=ctx.regions.filter(h=>inPolygon(h.polygon,...world));
  if(hard.length)return {...hit,lands:hard.every(h=>h.kind==='driveway')?'driveway':'hard',allowed:hard.every(h=>h.kind!=='hard')};
  if(hit.kind==='hardscape')return {...hit,lands:'hard',allowed:false};
  if(ctx.plan.site?.beds?.some(b=>b.polygon&&inPolygon(b.polygon,...world)))return {...hit,lands:'bed',allowed:true};
  // Never turn a kick-out through an indoor floor to call its landing grass.
  if(ctx.levels.some(l=>l.polys.some(poly=>inPolygon(poly,...p))))return {...hit,lands:'hard',allowed:false};
  return {...hit,lands:'grass',allowed:true};
}
function pointNearPoly(poly,pt,tol=.25){
  if(!poly||poly.length<3)return false;
  if(inPolygon(poly,pt[0],pt[1]))return true;
  for(let i=0;i<poly.length;i++)if(edgeDistance(pt,poly[i],poly[(i+1)%poly.length])<=tol+EPS)return true;
  return false;
}
function porchDeckHeight(ctx,po){
  const room=ctx.b.rooms?.find(r=>r.kind==='porch'&&r.level===(po.level||ctx.b.levels?.[0]?.id)&&inPolygon(r.polygon,...po.polygon[0]));
  return (ctx.f.base+(po.floor||0)+(room?.floor_offset_ft||0))*FT;
}
function rimExitDistance(poly,origin,dir,maxDist,backDist){
  let maxT=-Infinity;
  for(let i=0;i<poly.length;i++){
    const a=poly[i],b=poly[(i+1)%poly.length],e=sub(b,a),den=cross(dir,e);
    if(Math.abs(den)<EPS){
      if(Math.abs(cross(dir,sub(a,origin)))<1e-4)for(const pt of [a,b]){
        const t=dot(sub(pt,origin),dir);if(t>=-backDist-EPS&&t<=maxDist+EPS)maxT=Math.max(maxT,t);
      }
      continue;
    }
    const q=sub(a,origin),t=cross(q,e)/den,u=cross(q,dir)/den;
    if(u>=-EPS&&u<=1+EPS&&t>=-backDist-EPS&&t<=maxDist+EPS)maxT=Math.max(maxT,t);
  }
  return maxT;
}
function mountAt(ctx,segment,top,corner,all=false,nearest=false){
  const p=ctx.f.local(top),oh=segmentInfo(ctx,segment).overhang,postClear=GUTTER.spoutIn[0]/24+.02;
  const roof=ctx.hasSupported&&segment.roof!=null
    ?ctx.b.roofs?.find(r=>r.id===segment.roof)||ctx.sections.find(s=>(s.roof||s.id)===segment.roof):null;
  const supported=!!roof&&isSupported(roof);
  const postTop=c=>{
    const ceiling=heightAt(ctx.walledSections,...c.at)??ctx.b.levels?.[0]?.ceiling??0;
    if(!ctx.hasSupported)return ceiling;
    const surface=supportedRoofAbove(ctx.sections,...c.at,c.floor,ceiling,ctx.supportOptions);
    return surface===null?ceiling:surface;
  };
  // The dropped-ceiling route may descend a roof-owned post too. Opt in only
  // for positive drops: exposed and zero-drop roofs retain their exact routing.
  const roofPosts=supported&&roof.support.kind==='post'&&roof.underside?.kind==='flat'&&roof.underside.drop_ft>0
    ?supportPoints(roof).map(c=>({at:c.at,floor:ctx.b.levels?.find(l=>l.id===roof.level)?.elevation||0,size:roof.support.size_ft||.5})):[];
  // The pipe stays outside a dropped face before turning onto the post below
  // the ceiling. That attachment needs the post to reach the lower turn.
  const postAttachHeight=supported&&roof.underside?.kind==='flat'&&roof.underside.drop_ft>0
    ?Math.min(p[2],...segmentInfo(ctx,segment).sections.map(s=>ctx.supportOptions.ceilingAt(s)??Infinity)):p[2];
  const posts=[...ctx.porches.flatMap(po=>(po.columns||[]).filter(c=>c.at&&pointNearPoly(po.polygon,c.at,.25))
      .map(c=>({at:c.at,floor:po.floor||0,size:c.size||.5,porch:po}))),...roofPosts]
    .filter(c=>Math.max(...sub(c.at,p.slice(0,2)).map(Math.abs))<=oh+1+EPS&&c.floor<postAttachHeight
      &&postTop(c)>=postAttachHeight-.75)
    .sort((a,b)=>dist(a.at,p.slice(0,2))-dist(b.at,p.slice(0,2))||compare(key(a.at),key(b.at)));
  const wallReach=w=>hostWallReach(ctx,segment,w);
  const candidates=ctx.mountWalls.filter(w=>(!supported||w.id===roof.host?.wall)
      &&w.floor<p[2]&&w.top>=p[2]-.75&&wallReach(w)<=GUTTER.maxOverhangFt
      &&p[0]>=Math.min(w.from[0],w.to[0])-wallReach(w)-1-EPS&&p[0]<=Math.max(w.from[0],w.to[0])+wallReach(w)+1+EPS
      &&p[1]>=Math.min(w.from[1],w.to[1])-wallReach(w)-1-EPS&&p[1]<=Math.max(w.from[1],w.to[1])+wallReach(w)+1+EPS)
    .map(w=>({w,at:projection(p.slice(0,2),w.from,w.to).at,reach:wallReach(w),floor:w.floor,top:w.top,normal:w.normal}))
    .filter(w=>(!corner||edgeDistance(corner.at,w.w.from,w.w.to)<.05)
      &&Math.max(...sub(w.at,p.slice(0,2)).map(Math.abs))<=w.reach+1+EPS)
    .sort((a,b)=>dist(a.at,p.slice(0,2))-dist(b.at,p.slice(0,2))||b.floor-a.floor
      ||dot(b.normal,segment.outward)-dot(a.normal,segment.outward)||compare(a.w.id,b.w.id));
  const mounts=[];
  if(nearest){
    const choices=[...posts.map(c=>({kind:'post',at:add(c.at,mul(segment.outward,c.size/2+postClear)),normal:segment.outward,porch:c.porch,gap:dist(c.at,p.slice(0,2))})),
      ...candidates.map(w=>({kind:'wall',at:add(w.at,mul(w.normal,(w.w.thickness||.5)/2+.08)),normal:w.normal,gap:dist(w.at,p.slice(0,2))}))]
      .sort((a,b)=>a.gap-b.gap);
    if(!choices.length)choices.push({kind:'hang',at:p.slice(0,2),normal:segment.outward});
    return all?choices:choices[0];
  }
  if(posts.length&&(segment.porch!==null||!candidates.length||dist(posts[0].at,p.slice(0,2))<=dist(candidates[0].at,p.slice(0,2))+.1))
    mounts.push({kind:'post',at:add(posts[0].at,mul(segment.outward,posts[0].size/2+postClear)),normal:segment.outward,porch:posts[0].porch});
  for(const w of candidates){const at=corner?.at||w.at;
    mounts.push({kind:'wall',at:add(at,mul(w.normal,(w.w.thickness||.5)/2+.08)),normal:w.normal});
    if(!all)break;}
  if(!mounts.length)mounts.push({kind:'hang',at:p.slice(0,2),normal:segment.outward});
  return all?mounts:mounts[0];
}
function openingCheck(ctx,mount,top,bottom,clearance=GUTTER.openingClearFt,inclusive=false,legacy=true){
  let door=false;const low=bottom/FT-ctx.f.base,high=top[1]/FT-ctx.f.base;
  for(const w of ctx.openingWalls){const v=sub(w.to,w.from),length=Math.hypot(...v),q=projection(mount.at,w.from,w.to);
    if(dist(q.at,mount.at)>(w.thickness||.5)/2+.25)continue;
    const level=ctx.b.levels?.find(l=>l.id===w.level),floor=level?.elevation||0;
    for(const o of w.openings){
      const z0=floor+(o.sill||0)+(o.floor_reference_ft||0),z1=floor+(o.head??7)+(o.floor_reference_ft||0);
      if(z0>high)continue;
      const clamped=Math.abs(q.t*length-o.at)-(o.width||0)/2;
      const along=dot(sub(mount.at,w.from),v)/length;
      const distance=legacy?clamped:Math.abs(along-o.at)-(o.width||0)/2;
      if(z1>=low&&(legacy||inclusive?distance<=clearance+EPS:distance<clearance-EPS))return {blocked:true,door};
      if(['door','slider','bifold','garage'].includes(o.kind)&&clamped<=GUTTER.doorAvoidFt)door=true;
    }
  }
  return {blocked:false,door};
}
function candidate(ctx,segment,top,corner,flags=[],clearance=GUTTER.openingClearFt,attempt=null,legacy=false){
  let mounts=attempt?.mounts;
  if(!mounts){mounts=!legacy&&corner?mountAt(ctx,segment,top,corner,true):[mountAt(ctx,segment,top,corner)];
    if(attempt?.skipFirst)mounts=mounts.slice(1);}
  if(attempt){attempt.mounts=mounts;attempt.opening=false;}
  for(const mount of mounts){
    const value=mountedCandidate(ctx,segment,top,corner,flags,clearance,mount,false,attempt,legacy);
    if(value)return value;
  }
  return null;
}
function mountedCandidate(ctx,segment,top,corner,flags,clearance,mount,exact=false,attempt=null,legacy=false){
  const p=ctx.f.local(top),n=mount.normal;
  if(mount.kind==='hang')return null;
  let dropShift=0,deckH=null;
  if(mount.kind==='post'&&mount.porch?.polygon?.length>=3){
    deckH=porchDeckHeight(ctx,mount.porch);
    const mouth0=add(mount.at,mul(n,GUTTER.elbowFt)),sample0=sampleAt(ctx,ctx.f.world([...mouth0,p[2]-.16]));
    if(!inPolygon(mount.porch.polygon,mouth0[0],mouth0[1])&&sample0.height<deckH-.01*FT){
      const rimClear=GUTTER.spoutIn[0]/24+.02;
      const tExit=rimExitDistance(mount.porch.polygon,mount.at,n,GUTTER.elbowFt,rimClear);
      if(Number.isFinite(tExit))dropShift=Math.max(0,tExit+rimClear);
    }
  }
  const dropAt=dropShift>EPS?add(mount.at,mul(n,dropShift)):mount.at;
  const start=ctx.f.world([...dropAt,p[2]-.15]),support=sampleAt(ctx,start);
  const end=add(dropAt,mul(n,GUTTER.elbowFt)),probe=ctx.f.world([...end,p[2]-.16]);
  const choices=[{end,dir:n,swiveled:false}];
  // Preserve the vertical corner position. If the straight elbow mouth lands on
  // a walkway/path/step/stair, swivel the elbow up to 90 degrees along the wall.
  const initial=landing(ctx,probe),tangent=[-n[1],n[0]];
  if(!initial.allowed&&mount.kind!=='free')for(const deg of [15,30,45,60,75,90])for(const sign of [1,-1]){
    const rad=deg*Math.PI/180,dir=add(mul(n,Math.cos(rad)),mul(tangent,Math.sin(rad)*sign));
    choices.push({end:add(dropAt,mul(dir,GUTTER.elbowFt)),dir,swiveled:true});
  }
  let chosen=null,paved=null;
  for(const option of choices){const sample=landing(ctx,ctx.f.world([...option.end,p[2]-.16]));
    if(!sample.allowed)continue;
    if(['driveway','hard','deck'].includes(sample.lands)){paved??={...option,sample};continue;}
    if(option.swiveled&&!['grass','bed'].includes(sample.lands))continue;
    chosen={...option,sample};break;}
  chosen??=paved;
  // Landing is independent of mounting and opening clearance. Preserve a real
  // outside-corner drop even when every receiving surface needs attention.
  if(!chosen){if(!exact&&!corner?.convex)return null;chosen={...choices[0],sample:initial};}
  const surface=mount.kind==='free'?support.height:Math.max(support.height,chosen.sample.height),outletTop=gutterBottom(ctx,segment,top);
  // Only the receiver under the gutter can block an exact outlet. A high
  // mount-side receiver rejects this support so another face/free can be tried.
  if(exact&&outletTop[1]<=surface+2/12*FT)return null;
  const bottom=surface+(exact?Math.min(.5*FT,Math.max(0,(outletTop[1]-surface)*.4)):.5*FT);
  const openMount=openingCheck(ctx,mount,top,bottom,clearance,exact,legacy);
  const openDrop=dropShift>EPS?openingCheck(ctx,{...mount,at:dropAt},top,bottom,clearance,exact,legacy):openMount;
  const opening={blocked:openMount.blocked||openDrop.blocked,door:openMount.door||openDrop.door};
  if(opening.blocked&&!exact){if(attempt)attempt.opening=true;return null;}
  if(top[1]-.04*FT<=bottom+.1*FT&&!exact)return null;
  const under=[...outletTop];
  under[1]=Math.min(outletTop[1],top[1]-GUTTER.fasciaFt*FT)-GUTTER.soffitClearIn/12*FT;
  // A dropped flat ceiling closes the eave face below the old soffit. Keep
  // the vertical outlet outside that face until the same 1-inch clearance
  // is available below its lowest edge, before any inward offset.
  for(const section of segmentInfo(ctx,segment).sections){
    if(!isSupported(section)||section.underside?.kind!=='flat'||!(section.underside.drop_ft>0))continue;
    const local={...section,roof_frame:null},[x0,y0,x1,y1]=roofBounds(local);
    const low=Math.min(...[[x0,y0],[x1,y0],[x1,y1],[x0,y1]].map(at=>sectionHeight(local,...at)));
    const ceiling=low-(section.thickness_ft??ROOF_THICKNESS)-section.underside.drop_ft;
    under[1]=Math.min(under[1],(ctx.f.base+ceiling)*FT-GUTTER.soffitClearIn/12*FT);
  }
  if(under[1]<=bottom+.1*FT){if(!exact)return null;under[1]=outletTop[1];}
  const rimBotY=deckH!==null?Math.max(deckH+.06*FT,bottom+.35*FT):null;
  const rimTopY=rimBotY!==null?rimBotY+dropShift*FT:null;
  let upperAt=dropAt,useJog=false;
  if(dropShift>.06&&rimTopY!==null){
    const postXY=ctx.f.world([...mount.at,p[2]]),postH=Math.hypot(postXY[0]-under[0],postXY[2]-under[2]);
    const postElb=Math.max(0,Math.min(.5*FT,postH/2,(under[1]-bottom)/4));
    if(under[1]-2*postElb>rimTopY+.05*FT){upperAt=mount.at;useJog=true;}
  }
  const wallXY=ctx.f.world([...upperAt,p[2]]),horizontal=Math.hypot(wallXY[0]-under[0],wallXY[2]-under[2]);
  const elbow=Math.max(0,Math.min(.5*FT,horizontal/2,(under[1]-bottom)/4)),toward=unit([wallXY[0]-under[0],0,wallXY[2]-under[2]]);
  const first=add(under,mul(toward,elbow));first[1]-=elbow;
  const leader=[wallXY[0]-toward[0]*elbow,first[1],wallXY[2]-toward[2]*elbow];
  const wallTop=[wallXY[0],under[1]-2*elbow,wallXY[2]],wallBottom=ctx.f.world([...dropAt,bottom/FT-ctx.f.base]);
  const outlet=ctx.f.world([...chosen.end,(surface+(exact?Math.min(4/12*FT,(bottom-surface)*2/3):4/12*FT))/FT-ctx.f.base]);
  const path=[outletTop,under];if(elbow>EPS)path.push(first);if(horizontal>2*elbow+EPS)path.push(leader);
  path.push(wallTop);
  if(useJog)path.push(ctx.f.world([...mount.at,rimTopY/FT-ctx.f.base]),ctx.f.world([...dropAt,rimBotY/FT-ctx.f.base]));
  path.push(wallBottom,outlet);
  const dirLocal=chosen.dir,origin=ctx.f.world([0,0,0]),tip=ctx.f.world([...dirLocal,0]);
  return {top:outletTop,mount:mount.kind,path,outlet:{at:outlet,dir:unit([tip[0]-origin[0],0,tip[2]-origin[2]]),lands:chosen.sample.lands},
    flags:[...flags,...(exact&&opening.blocked?['over-opening']:[]),...(!chosen.sample.allowed?['no-safe-landing']:[])],door:opening.door,
    rank:!chosen.sample.allowed?2:['driveway','hard','deck'].includes(chosen.sample.lands)?1:0};
}
function gutterBottom(ctx,segment,at){
  const p=ctx.f.local(at),offset=GUTTER.fasciaProudFt+GUTTER.profileIn/24;
  return ctx.f.world([...add(p.slice(0,2),mul(segment.outward,offset)),p[2]-GUTTER.profileIn/12]);
}
function hangingEnd(ctx,c,flags){
  // A diagnostic stub still gives the runoff consumer an endpoint when no
  // full drop is safe. Do not route a pipe through an opening or pretend that
  // a prohibited receiving surface is grass. The Check list must resolve it.
  const top=gutterBottom(ctx,c.segment,c.at);
  // Start the ray at the drip-line height: a receiver can already be above
  // the gutter bottom, so a ray starting at top would silently miss it.
  const hit=landing(ctx,[top[0],c.at[1],top[2]]),blocked=top[1]<=hit.height+2/12*FT;
  // Accepted: the drip-line cap can leave this point under a receiver within 1 in of the drip line.
  if(blocked)top[1]=Math.min(c.at[1]-FT/12,Math.max(top[1],hit.height+FT/12));
  const outlet=[...top];if(!blocked)outlet[1]=Math.max(top[1]-.5*FT,hit.height+FT/12);
  // Keep door and warning arbitration at the original diagnostic probe.
  const probe=[...c.at];probe[1]-=.54*FT;
  const reference=[...c.at];reference[1]-=.04*FT;
  const diagnostic=landing(ctx,probe),origin=ctx.f.world([0,0,0]),tip=ctx.f.world([...c.segment.outward,0]);
  const opening=openingCheck(ctx,mountAt(ctx,c.segment,c.at,c.corner),reference,diagnostic.height+.4*FT);
  return {top,mount:'hang',path:[top,outlet],outlet:{at:outlet,dir:unit([tip[0]-origin[0],0,tip[2]-origin[2]]),lands:hit.lands},
    flags:[...flags,'hang','stub',...(blocked?['outlet-blocked']:[]),...(!diagnostic.allowed?['no-safe-landing']:[])],door:opening.door,rank:diagnostic.lands==='driveway'?1:0};
}
function exactBlocked(ctx,c,flags,mount){
  const value=hangingEnd(ctx,c,flags);
  value.mount=mount.kind;value.flags=value.flags.filter(f=>f!=='hang'&&f!=='stub');
  if(!value.flags.includes('outlet-blocked'))value.flags.push('outlet-blocked');
  return value;
}
function exactCandidate(ctx,c,flags){
  const {segment,at}=c,top=gutterBottom(ctx,segment,at);
  const mounts=mountAt(ctx,segment,at,null,true,true);
  const hit=landing(ctx,[top[0],at[1],top[2]]);
  const free={kind:'free',at:ctx.f.local(top).slice(0,2),normal:segment.outward};
  if(top[1]<=hit.height+2/12*FT){const mount=mounts.find(m=>m.kind!=='hang')||free;
    return exactBlocked(ctx,c,mount.kind==='free'?[...flags,'no-support']:flags,mount);}
  for(const mount of mounts){if(mount.kind==='hang')continue;
    const value=mountedCandidate(ctx,segment,at,null,flags,GUTTER.openingClearMinFt,mount,true);
    if(value)return value;
  }
  return mountedCandidate(ctx,segment,at,null,[...flags,'no-support'],GUTTER.openingClearMinFt,free,true);
}
function edgeLine(ctx,segment){
  const r=ctx.b.roofs?.find(r=>r.id===segment.roof),area=r?.area;
  if(area&&Number.isInteger(segment.edge))return [roofPoint(r,area[segment.edge]),roofPoint(r,area[(segment.edge+1)%area.length])];
  if(segment.roof!==null){const s=ctx.b.roof?.sections?.find(s=>(s.roof||s.id)===segment.roof),side=s&&SIDES.find(side=>source(ctx.b,s,side).edge===segment.edge);
    if(s&&side){const [x0,y0,x1,y1]=s.rect,a=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],i=SIDES.indexOf(side);return [roofPoint(s,a[i]),roofPoint(s,a[(i+1)%4])];}}
  const porch=ctx.porches.find(v=>v.id===segment.porch),poly=porch?.polygon||[];
  if(poly.length){const mid=ctx.f.local(mul(add(segment.a,segment.b),.5)).slice(0,2);
    const edges=poly.map((a,i)=>({a,b:poly[(i+1)%poly.length]})).sort((a,b)=>edgeDistance(mid,a.a,a.b)-edgeDistance(mid,b.a,b.b));
    return [edges[0].a,edges[0].b];}
  return [ctx.f.local(segment.a).slice(0,2),ctx.f.local(segment.b).slice(0,2)];
}
function edgeFraction(ctx,segment,top){
  return projection(ctx.f.local(top).slice(0,2),...edgeLine(ctx,segment)).t;
}
function overrides(ctx,segment){
  if(segment.roof===null)return null;
  const r=ctx.b.roofs?.find(r=>r.id===segment.roof),edge=r?.edges?.[segment.edge];
  if(edge)return edge.gutter===true&&edge.setting==='sloped'&&Array.isArray(edge.downspouts)?edge.downspouts:null;
  const s=ctx.b.roof?.sections?.find(s=>(s.roof||s.id)===segment.roof),side=s&&SIDES.find(side=>source(ctx.b,s,side).edge===segment.edge);
  return s&&eaveSide(s,side)&&s.gutters?.[side]===true&&Array.isArray(s.downspouts?.[side])?s.downspouts[side]:null;
}

// Measure exact-drop warnings along the authored edge, identifying tips with vertices.
function nearRunCorner(ctx,segment,at,c){
  const [a,b]=edgeLine(ctx,segment),same=c.segment.roof===segment.roof&&c.segment.edge===segment.edge&&c.segment.porch===segment.porch;
  if(!same&&(!c.corner||edgeDistance(c.corner.at,a,b)>.05))return false;
  // Clamping identifies the overhanging tip with its authored corner.
  return Math.abs(edgeFraction(ctx,segment,at)-edgeFraction(ctx,segment,c.at))*dist(a,b)<=1+EPS;
}

export function downspouts(plan={},runs=[]){
  for(const run of runs)delete run.drainsTo;
  const cached=runContexts.get(runs);
  // The runs own their rebuild context; no global plan cache can hide edits.
  // Serialised runs (or another plan object) retain the standalone fallback.
  const reuse=cached&&cached.original===plan&&cached.signature===placementKey(plan);
  const prepared=reuse?cached.plan:placementPlan(plan),contexts=reuse?cached.contexts:prepare(prepared,null);
  const surfaces=reuse?cached.surfaces:snapshots(contexts,null),output=[],compiled=[];
  const sample=reuse?contexts.values().next().value?.sample:memoSampler(prepared,surfaces);
  const clip=reuse&&contexts.values().next().value?.clip||createEaveClipper([...contexts.values()].map(c=>c.f),surfaces);
  for(const ctx of contexts.values()){ctx.sample=sample;ctx.clip=clip;}
  const segmentKey=s=>`${s.roof}:${s.edge}:${s.porch}`;
  for(const run of runs){
    const b=plan.buildings?.find(b=>b.id===run.building);if(!b)continue;
    const ctx=contexts.get(b.id),positions=new Map();
    const active=run.segments.filter(s=>{
      if(s.roof===null)return ctx.porches.some(p=>p.id===s.porch&&p.gutter===true);
      const r=b.roofs?.find(r=>r.id===s.roof);if(r)return r.edges?.[s.edge]?.setting==='sloped'&&r.edges[s.edge].gutter===true;
      return b.roof?.sections?.some(v=>(v.roof||v.id)===s.roof&&SIDES.some(side=>source(b,v,side).edge===s.edge&&eaveSide(v,side)&&v.gutters?.[side]===true));
    });
    const origins=new Map(run.segments.map(s=>[s,segmentOrigin(ctx,s)]));
    const endCount=(segment,at)=>run.segments.reduce((n,s)=>n+[s.a,s.b]
      .filter(p=>endpointsTouch(segment,at,s,p,origins.get(segment),origins.get(s))).length,0);
    for(const segment of active)for(const at of [segment.a,segment.b]){
      const corner=endpointCorner(ctx,segment,at),p=ctx.f.local(at),oh=segmentInfo(ctx,segment).overhang;
      const footprint=dropFootprint(ctx,segment,at),inner=footprint.corners.filter(c=>!c.convex);
      const innerDistance=Math.min(Infinity,...inner.map(c=>dist(c.at,p.slice(0,2))));
      const nearInner=inner.some(c=>Math.max(...sub(c.at,p.slice(0,2)).map(Math.abs))<=oh+1+EPS);
      let cut;
      const k=`${key(at)}:${segmentKey(segment)}`,entry={segment,at,corner,convex:!!corner?.convex,
        key:`end:${key(at)}`,floor:footprint.floor,end:endCount(segment,at)===1,
        inner:corner?.convex===false||!corner&&nearInner||innerDistance<=.5+EPS,innerDistance,cut:()=>cut??=cutEnd(ctx,segment,at)};
      if(!positions.has(k)||entry.convex)positions.set(k,entry);
    }
    compiled.push({run,ctx,active,all:[...positions.values()],selected:[],used:new Set()});
  }
  // Both faces of a physical corner must share a claim even if one face
  // drops onto a lower roof and the other reaches the ground. Canonicalise
  // across all runs before resolving either overrides or automatic outlets.
  const corners=new Map();
  for(const state of compiled)for(const c of state.all)if(c.corner){
    const id=`${state.run.building}:${c.corner.key}`;
    if(!corners.has(id))corners.set(id,[]);corners.get(id).push(c);
  }
  for(const entries of corners.values()){
    entries.sort((a,b)=>a.at[1]-b.at[1]);
    for(let i=0;i<entries.length;){let end=i+1;
      while(end<entries.length&&entries[end].at[1]-entries[i].at[1]<=3/12*FT+EPS)end++;
      const group=entries.slice(i,end),floor=Math.min(...group.map(c=>c.floor));
      const band=Number.isFinite(floor)?floor.toFixed(2):'ground';
      const id=`corner:${entries[i].corner.key}:eave:${entries[i].at[1].toFixed(5)}:floor:${band}`;
      for(const c of group)c.key=id;i=end;
    }
  }
  for(const state of compiled){
    const {ctx,all}=state,convex=all.filter(c=>c.convex&&!c.inner);
    const attempts=new Map(),legacyFailures=new Map();
    const checked=(c,flags,clearance)=>{
      let attempt=attempts.get(c);
      if(attempt?.failed?.has(clearance))return null;
      // Less opening clearance cannot repair a missing support or short drop.
      if(clearance===GUTTER.openingClearMinFt&&!attempt?.opening)return null;
      if(!attempt){attempt={skipFirst:legacyFailures.has(c)&&!legacyFailures.get(c).opening};attempts.set(c,attempt);}
      const value=candidate(ctx,c.segment,c.at,c.corner,flags,clearance,attempt);
      if(!value)(attempt.failed??=new Set()).add(clearance);
      return value;
    };
    // Tier 0 is main's original first-face/clamped/inclusive rule verbatim.
    // Its non-empty result is final for this run; new tiers cannot expand it.
    const legacy=(pool,flags)=>pool.map(c=>{
      if(legacyFailures.has(c))return {...c,value:null};
      const attempt={},value=candidate(ctx,c.segment,c.at,c.corner,flags,GUTTER.openingClearFt,attempt,true);
      if(!value)legacyFailures.set(c,attempt);
      return {...c,value};})
      .filter(c=>c.value&&c.value.mount!=='hang');
    let valid=legacy(convex,[]);
    for(const clearance of valid.length?[]:[GUTTER.openingClearFt,GUTTER.openingClearMinFt]){
      valid=convex.map(c=>({...c,value:checked(c,[],clearance)})).filter(c=>c.value&&c.value.mount!=='hang');
      if(valid.length)break;
    }
    const ends=()=>all.filter(c=>c.end&&!c.inner&&!c.cut());
    if(!valid.length)valid=legacy(ends(),['no-outside-corner']);
    if(!valid.length)for(const clearance of [GUTTER.openingClearFt,GUTTER.openingClearMinFt]){
      valid=ends()
        .map(c=>({...c,value:checked(c,['no-outside-corner'],clearance)})).filter(c=>c.value&&c.value.mount!=='hang');
      if(valid.length)break;
    }
    if(!valid.length&&all.length){
      const ends=all.some(c=>c.end)?all.filter(c=>c.end):all;
      const safe=ends.filter(c=>!c.inner&&!c.cut()),nonInner=ends.filter(c=>!c.inner);
      const pool=safe.length?safe:nonInner.length?nonInner:ends;
      // Only the final emergency fallback may use an inner end. Leave it at
      // the eave, farthest from the inner footprint vertex, and flag it.
      valid=pool.map(c=>({...c,value:hangingEnd(ctx,c,[...(!c.convex?['no-outside-corner']:[]),
        ...(c.inner?['inner-end']:[]),...(c.cut()?['clipped-end']:[])])}));
      if(!nonInner.length)valid.sort((a,b)=>b.innerDistance-a.innerDistance||compare(key(a.at),key(b.at)));
    }
    valid.sort((a,b)=>Number(a.inner)-Number(b.inner)||(a.inner&&b.inner?b.innerDistance-a.innerDistance:0)
      ||a.value.rank-b.value.rank||Number(a.value.door)-Number(b.value.door)
      ||Number(a.value.mount==='hang')-Number(b.value.mount==='hang')||(a.segment.edge??0)-(b.segment.edge??0)||compare(key(a.at),key(b.at)));
    state.valid=valid;
  }
  // Resolve each authored override once across all exposed pieces of its edge.
  // A split run cannot multiply a single dragged downspout into two outlets.
  const overrideEdges=new Map();
  for(const state of compiled)for(const segment of state.active){
    const values=overrides(state.ctx,segment);if(values!==null)overrideEdges.set(`${state.run.building}:${segmentKey(segment)}`,values);
  }
  for(const [id,values] of overrideEdges)for(const [authoredIndex,entry] of values.slice(0,8).entries()){
    const exact=entry&&typeof entry==='object'&&!Array.isArray(entry)&&Object.keys(entry).length===1&&'at' in entry;
    const fraction=exact?entry.at:entry;
    if(typeof fraction!=='number'||!Number.isFinite(fraction)||fraction<0||fraction>1)continue;
    if(exact){
      const choices=compiled.flatMap(state=>state.active.filter(segment=>`${state.run.building}:${segmentKey(segment)}`===id).map(segment=>{
        const [a,b]=edgeLine(state.ctx,segment),v=sub(b,a),p=add(a,mul(v,fraction));
        const localA=state.ctx.f.local(segment.a).slice(0,2),localB=state.ctx.f.local(segment.b).slice(0,2);
        const q=projection(p,localA,localB),at=add(segment.a,mul(sub(segment.b,segment.a),q.t));
        const tips=[segment.a,segment.b].map(at=>({at,u:dot(sub(state.ctx.f.local(at).slice(0,2),a),v)/(dot(v,v)||1)}))
          .filter(t=>fraction===0&&t.u<0||fraction===1&&t.u>1).sort((a,b)=>fraction===0?a.u-b.u:b.u-a.u);
        return {state,segment,at,gap:dist(p,q.at),tip:tips[0]};
      })).sort((a,b)=>(Math.abs(a.gap-b.gap)>EPS?a.gap-b.gap:0)||compare(a.state.run.id,b.state.run.id)||compare(key(a.at),key(b.at)));
      const tips=choices.filter(c=>c.tip).sort((a,b)=>(fraction===0?a.tip.u-b.tip.u:b.tip.u-a.tip.u)||compare(a.state.run.id,b.state.run.id));
      const chosen=tips[0]||choices[0];if(!chosen)continue;
      if(chosen.tip)chosen.at=chosen.tip.at;
      const {state,segment,at}=chosen;
      const nearCorner=state.valid.some(c=>c.convex&&!c.inner&&c.value.mount!=='hang'
        &&!c.value.flags.some(f=>['no-safe-landing','outlet-blocked'].includes(f))&&nearRunCorner(state.ctx,segment,at,c));
      const flags=nearCorner?[]:['placed-off-corner'];
      const c={segment,at,key:`exact:${id}:${authoredIndex}`,exact:true,source:'override',overrideFraction:fraction,authoredIndex};
      c.value=exactCandidate(state.ctx,c,flags);state.selected.push(c);continue;
    }
    const choices=compiled.flatMap(state=>state.valid.filter(c=>`${state.run.building}:${segmentKey(c.segment)}`===id)
      .map(c=>({state,c,gap:Math.abs(edgeFraction(state.ctx,c.segment,c.at)-fraction)})))
      .sort((a,b)=>a.gap-b.gap||compare(a.state.run.id,b.state.run.id)||compare(key(a.c.at),key(b.c.at)));
    const chosen=choices[0];if(chosen&&!chosen.state.used.has(chosen.c.key)){
      chosen.state.selected.push({...chosen.c,source:'override',overrideFraction:fraction,authoredIndex});chosen.state.used.add(chosen.c.key);}
  }
  const exacts=compiled.flatMap(state=>state.selected.filter(c=>c.exact).map(c=>({state,c})));
  const dropPoint=c=>c.value.path.at(-2)||c.value.top;
  const nearExact=(state,c)=>exacts.some(v=>v.state.run.building===state.run.building
    &&(dist(v.c.at,c.at)<=FT+EPS||Math.abs(v.c.at[1]-c.at[1])<=3/12*FT+EPS
      &&Math.hypot(dropPoint(v.c)[0]-dropPoint(c)[0],dropPoint(v.c)[2]-dropPoint(c)[2])<FT+EPS));
  compiled.sort((a,b)=>compare(a.run.id,b.run.id));
  for(const state of compiled){const {run,valid,selected,used}=state;
    const target=Math.ceil(run.length/GUTTER.spanFt);
    for(const c of valid){if(selected.length>=target)break;
      if(used.has(c.key)||overrideEdges.has(`${run.building}:${segmentKey(c.segment)}`)||nearExact(state,c)
        ||selected.some(s=>s.exact)&&c.value.flags.includes('stub'))continue;
      selected.push({...c,source:'auto'});used.add(c.key);}
  }
  // Resolve corner ownership across the building and receiving-floor band:
  // authored overrides first, then proposed fraction, then stable run ID.
  const globalKey=(state,c)=>`${state.run.building}:${c.corner?c.key:state.run.id+':'+c.key}`;
  const claimed=new Map(),claims=compiled.flatMap(state=>state.selected.map(c=>({state,c,share:1/state.selected.length})))
    .sort((a,b)=>Number(b.c.source==='override')-Number(a.c.source==='override')||b.share-a.share||compare(a.state.run.id,b.state.run.id));
  for(const claim of claims){const id=globalKey(claim.state,claim.c),winner=claimed.get(id);
    if(!winner)claimed.set(id,claim);
    else if(winner.c.source==='override'&&claim.c.source==='override'&&winner.state!==claim.state){
      const {roof,edge,porch}=claim.c.segment;
      (winner.c.merged??=[]).push({run:claim.state.run.id,fraction:claim.c.overrideFraction,roof,edge,porch});
    }
  }
  for(const state of compiled){const desired=state.selected.length;
    state.selected=state.selected.filter(c=>claimed.get(globalKey(state,c))?.c===c);
    for(const c of state.valid){if(state.selected.length>=desired)break;
      const id=globalKey(state,c);
      if(claimed.has(id)||overrideEdges.has(`${state.run.building}:${segmentKey(c.segment)}`)||nearExact(state,c)
        ||state.selected.some(s=>s.exact)&&c.value.flags.includes('stub'))continue;
      state.selected.push({...c,source:'auto'});claimed.set(id,{state,c});}
  }
  for(const building of contexts.keys()){
    const states=compiled.filter(s=>s.run.building===building&&s.active.length);
    if(states.some(s=>s.selected.length))continue;
    const state=states.find(s=>s.valid.length);if(!state)continue;
    const c=state.valid[0],flags=['no-outlet',...(c.inner?['inner-end']:[]),...(c.cut()?['clipped-end']:[])];
    state.selected.push({...c,source:'auto',value:hangingEnd(state.ctx,c,flags)});
  }
  for(const {run,ctx,selected} of compiled){
    selected.forEach((c,k)=>{const {value,segment}=c;
      output.push({id:`${run.id}:${k}`,run:run.id,edge:{roof:segment.roof,edge:segment.edge,porch:segment.porch,fraction:edgeFraction(ctx,segment,c.at)},
        top:value.top,mount:value.mount,path:value.path,outlet:value.outlet,share:1/selected.length,source:c.source,
        ...(c.source==='override'?{authoredFraction:c.overrideFraction,authoredIndex:c.authoredIndex,...(c.exact?{exact:true}:{})}:{}),
        flags:[...value.flags,...(c.merged?.length?['merged-override']:[])],
        ...(c.merged?.length?{merged:c.merged.sort((a,b)=>compare(a.run,b.run)||a.fraction-b.fraction)}:{})});});
  }
  const byId=new Map(output.map(s=>[s.id,s])),receivers=compiled.flatMap(state=>state.selected.map((c,k)=>({state,c,spout:byId.get(`${state.run.id}:${k}`)})));
  const weights=new Map(receivers.map(({state,spout})=>[spout.id,state.run.length/state.selected.length]));
  for(const state of compiled){
    if(state.selected.length||!state.active.length)continue;
    const ends=state.active.flatMap(s=>[s.a,s.b]);
    const choices=receivers.filter(v=>v.state.run.building===state.run.building).map(v=>{
      // Drainage arbitration stays on its original reference point. The
      // physical outlet's profile offset must not choose a different owner.
      const reference=[...v.c.at];reference[1]-=.04*FT;
      return {...v,
        adjacent:ends.some(p=>Math.hypot(p[0]-v.c.at[0],p[2]-v.c.at[2])<=GUTTER.runJoinFt*FT+EPS&&reference[1]<=p[1]+EPS)
          ||state.valid.some(c=>c.corner&&v.c.corner&&c.corner.key===v.c.corner.key&&reference[1]<=c.at[1]+EPS),
        distance:Math.min(...ends.map(p=>dist(p,reference)))};});
    choices.sort((a,b)=>Number(b.adjacent)-Number(a.adjacent)||a.distance-b.distance||compare(a.spout.id,b.spout.id));
    if(choices.length){const target=choices[0].spout;state.run.drainsTo=target.id;weights.set(target.id,weights.get(target.id)+state.run.length);}
  }
  for(const state of compiled){const outlets=output.filter(s=>s.run===state.run.id),total=outlets.reduce((n,s)=>n+weights.get(s.id),0);
    for(const s of outlets)s.share=weights.get(s.id)/total;}
  // Retain the builder's actual safe candidates for editor Add, without a
  // second placement pass or a second copy of the corner/mounting rules.
  candidateSets.set(runs, compiled.flatMap(state => state.valid.filter(c => c.value.mount !== 'hang'
    && !c.value.flags.some(f => ['no-safe-landing', 'outlet-blocked'].includes(f))).map(c => ({
      building: state.run.building, roof: c.segment.roof, edge: c.segment.edge, porch: c.segment.porch,
      fraction: edgeFraction(state.ctx, c.segment, c.at), occupied: claimed.has(globalKey(state, c))||nearExact(state,c),
    }))));
  return output;
}
