// Feature edges of rendered geometry. Only the editor's draw tool calls this.
import * as THREE from 'three';
import { buildingBase, groundAt, poolDatum } from '../twin_ground.js';
import { hostPoint } from '../twin_hosts.js';
import { roomFloor, roomAt } from '../twin_floors.js';

const FT = .3048, RADIUS = 12, cache = new WeakMap(), boundsCache = new WeakMap();
const scratch = new THREE.Vector3(), end = new THREE.Vector3(), projected = new THREE.Vector3(), boxHit = new THREE.Vector3();
const terrainCache = new WeakMap(), triangleA = new THREE.Vector3(), triangleB = new THREE.Vector3(), triangleC = new THREE.Vector3();
const key = p => p.toArray().map(v => Math.round(v * 1e4)).join(',');
const edgeKey = (a, b) => a < b ? `${a}/${b}` : `${b}/${a}`;
const lot = p => [p.x / FT, -p.z / FT, p.y / FT];
const lists = {wall:'walls',roof:'roofs',floor:'levels',room:'rooms',porch:'porches',stair:'stairs',opening:'openings',item:'items',fixture:'fixtures',light:'lights',anchor:'anchors',solar_zone:'solar_zones'};
const siteLists = {retaining_wall:'terraces',terrace:'terraces',hardscape:'hardscape',fence:'fence'};
const pieces = v => Array.isArray(v) ? v : v ? [v] : [];
const buildingPieces = (b,kind) => kind === 'roof' ? (b.roof?.sections || b.roofs || []).map((p,i)=>({...p,id:p.id || `roof:${i}`})) : pieces(b[lists[kind]]);

function features(geometry) {
  const position = geometry.attributes.position, index = geometry.index;
  const stamp = `${position.version}:${index?.version}:${position.count}:${index?.count}`;
  const ranges = geometry.userData.snapRanges;
  if (cache.get(geometry)?.stamp === stamp && cache.get(geometry).position === position && cache.get(geometry).index === index && cache.get(geometry).ranges === ranges) return cache.get(geometry);
  const edges = new Map(), a = new THREE.Vector3(), b = a.clone(), c = a.clone();
  const count = index?.count ?? position.count, vertex = i => index ? index.getX(i) : i;
  let rangeIndex = 0;
  for (let i = 0; i + 2 < count; i += 3) {
    while (ranges && rangeIndex + 1 < ranges.length && i >= ranges[rangeIndex].start + ranges[rangeIndex].count) rangeIndex++;
    const owner = ranges?.[rangeIndex];
    if (owner && noSource(owner)) continue;
    const prefix = owner ? `${owner.kind}:${owner.buildingId}:${owner.pieceId}/` : '';
    a.fromBufferAttribute(position, vertex(i)); b.fromBufferAttribute(position, vertex(i+1)); c.fromBufferAttribute(position, vertex(i+2));
    const n = b.clone().sub(a).cross(c.clone().sub(a)).normalize();
    if (!n.lengthSq()) continue;
    for (const [p, q] of [[a,b],[b,c],[c,a]]) {
      const pk = key(p), qk = key(q); if (pk === qk) continue;
      const k = prefix + edgeKey(pk, qk);
      if (!edges.has(k)) edges.set(k, {a:p.clone(),b:q.clone(),normals:[],owner});
      edges.get(k).normals.push(n);
    }
  }
  const hard = [...edges.values()].filter(e => e.normals.length === 1 || e.normals.some(n => e.normals.some(m => n.dot(m) < Math.cos(Math.PI/6) - 1e-6)));
  const vertices = new Map();
  for (const e of hard) for (const p of [e.a,e.b]) {
    const k = `${e.owner?.kind}:${e.owner?.buildingId}:${e.owner?.pieceId}/` + key(p);
    if (!vertices.has(k)) vertices.set(k, {point:p,normals:[],owner:e.owner});
    vertices.get(k).normals.push(...e.normals);
  }
  const result = {stamp,position,index,ranges,edges:hard,vertices:[...vertices.values()]};
  cache.set(geometry,result); return result;
}

function bounds(geometry) {
  const p=geometry.attributes.position, previous=boundsCache.get(geometry);
  if (!previous || previous.position !== p || previous.version !== p.version) {
    geometry.computeBoundingBox(); boundsCache.set(geometry,{position:p,version:p.version});
  }
  return geometry.boundingBox;
}

// Frames use east/north/up feet, independent of render batching and instances.
export function pointAnchor(plan, hit, point) {
  const kind = hit?.kind, id = hit?.id || hit?.pieceId, building = hit?.building || hit?.buildingId;
  if (typeof id !== 'string' || !id) return null;
  let frame = new THREE.Matrix4(), host = {kind,id};
  const owners = !building && lists[kind] ? (plan.buildings || []).filter(b => buildingPieces(b,kind).some(p => p.id === id || kind === 'floor' && `floor:${p.id}` === id)) : [];
  if (building || kind === 'building' || owners.length === 1) {
    const b = plan.buildings?.find(b => b.id === (building || owners[0]?.id || id)); if (!b) return null;
    const p = kind === 'building' ? b : buildingPieces(b,kind).find(p => p.id === id || kind === 'floor' && `floor:${p.id}` === id)
      || (kind === 'porch' && (b.porch?.id || 'porch') === id ? b.porch : null);
    if (!p || !lists[kind] && kind !== 'building') return null;
    if (building) host.building = building;
    frame.makeRotationZ((b.rotation || 0)*Math.PI/180); frame.setPosition(...(b.position || [0,0]),buildingBase(plan,b));
    if (['item','fixture'].includes(kind)) {
      let origin;
      try {
        if (p.rect) {
          const l = b.levels?.find(l => l.id === p.level), r = p.host && !p.host.floor ? null
            : b.rooms?.find(r => r.id === p.host?.floor) || roomAt(b,p.level,[(p.rect[0]+p.rect[2])/2,(p.rect[1]+p.rect[3])/2]);
          origin = [(p.rect[0]+p.rect[2])/2,(p.rect[1]+p.rect[3])/2,roomFloor(l,r)+(p.z0 || 0)];
        } else origin = p.host ? hostPoint(b,p.host,p.offset || 0) : [p.at[0],p.at[1],p.at[2] || 0];
      } catch { return null; }
      origin[2] += p.elevation || 0;
      const axes = new THREE.Matrix4().set(1,0,0,0, 0,0,1,0, 0,-1,0,0, 0,0,0,1);
      const rotation = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler((p.pitch || 0)*Math.PI/180,(p.rotation || 0)*Math.PI/180,(p.roll || 0)*Math.PI/180,'YXZ'));
      const local = axes.clone().invert().multiply(rotation).multiply(axes); local.setPosition(...origin); frame.multiply(local);
    }
  } else {
    const site = plan.site || {}, pool = site.pool;
    const p = siteLists[kind] ? pieces(site[siteLists[kind]]).find(p => p.id === id)
      : kind === 'pool' && (pool?.id || 'pool:0') === id ? pool : ['spa','ledge','steps'].includes(kind) ? pool?.features?.find(p => p.id === id && p.kind === kind) : null;
    const first = (p?.polygon || p?.polyline || p?.points)?.[0]; if (!first) return null;
    let z = p.elevation ?? groundAt(plan,...first);
    if (['terrace','retaining_wall'].includes(kind)) z = p.height;
    if (['pool','spa','ledge','steps'].includes(kind)) {
      z = poolDatum(plan,pool);
      if (kind === 'spa') z += .45+((p.mode || 'raised') === 'raised' ? (p.raise_in ?? 12)/12 : 0);
    }
    frame.makeTranslation(first[0],first[1],z);
  }
  return {host,local:new THREE.Vector3(...point).applyMatrix4(frame.invert()).toArray()};
}

function excluded(o) {
  const d = o.userData || {};
  return o.visible === false || o.layers?.isEnabled(31) || o.isHelper || d.yardGrass || d.effectFixture || d.effectFixtures || d.fireFlame || d.fixtureId || d.marker || d.helper || d.preview || d.ghost || d.emitter
    || /^(editor-|effect-fixtures|sky|sun|stars|marker|preview|helper)/i.test(o.name || '');
}

function noSource(d) {
  return d.terrain || d.part === 'water' || d.ghost || d.preview || d.marker || d.emitter || d.effectFixture;
}

// Identity comes from the render owner, including the ranges retained by mergeStatic.
function ownerOf(mesh) {
  for (let o = mesh; o; o = o.parent) if (o.userData.kind && o.userData.pieceId) return o.userData;
  return null;
}

// The dense sampled ground remains an occluder, never a feature source. A
// cached triangle tree lets one traversal test the three finalist rays together.
function terrainTree(geometry) {
  const p=geometry.attributes.position, ix=geometry.index, previous=terrainCache.get(geometry);
  if(previous?.p===p && previous.ix===ix && previous.pv===p.version && previous.iv===ix?.version)return previous.tree;
  const triangles=[];
  for(let i=0,n=ix?.count??p.count;i<n;i+=3) {
    const ids=[0,1,2].map(j=>ix?ix.getX(i+j):i+j),box=new THREE.Box3();
    for(const id of ids)box.expandByPoint(scratch.fromBufferAttribute(p,id));
    triangles.push({ids,box});
  }
  function split(rows) {
    const box=new THREE.Box3();for(const t of rows)box.union(t.box);
    if(rows.length<=12)return {box,rows};
    const size=box.getSize(new THREE.Vector3()),axis=size.x>=size.y&&size.x>=size.z?'x':size.y>=size.z?'y':'z';
    rows.sort((a,b)=>(a.box.min[axis]+a.box.max[axis])-(b.box.min[axis]+b.box.max[axis]));
    const middle=Math.floor(rows.length/2);return {box,left:split(rows.slice(0,middle)),right:split(rows.slice(middle))};
  }
  const tree=split(triangles);terrainCache.set(geometry,{p,ix,pv:p.version,iv:ix?.version,tree});return tree;
}

export function createPointSnap(view, getPlan, {onFeatures = () => {}} = {}) {
  const records = new WeakMap(), ray = new THREE.Raycaster(), mouse = new THREE.Vector2(), instance = new THREE.Matrix4();
  const cameraMatrix = new THREE.Matrix4(), projection = new THREE.Matrix4(), hits = [], meshes = [], candidates = [];
  const pool = Array.from({length:4},()=>({point:new THREE.Vector3(),screen:{}}));
  const grounds=[], groundRecords=new WeakMap(), inverse=new THREE.Matrix4();
  const terrainRays=Array.from({length:3},()=>({ray:new THREE.Ray(),limit:0,blocked:false}));
  let cameraVersion = 0, rectKey = '';
  const screen = (p, rect, out) => {
    projected.copy(p).applyMatrix4(cameraMatrix);
    out.x = rect.left + (projected.x+1)*rect.width/2; out.y = rect.top + (1-projected.y)*rect.height/2; out.z = projected.z;
    return out;
  };
  function record(mesh, matrix, index) {
    let rows = records.get(mesh); if (!rows) { rows = []; records.set(mesh,rows); }
    const g = mesh.geometry, p = g.attributes.position, ix = g.index, old = rows[index];
    if (old && old.geometry === g && old.position === p && old.index === ix && old.pv === p.version && old.iv === ix?.version && old.matrix.equals(matrix) && old.ranges === g.userData.snapRanges) return old;
    const r = {mesh,instanceId:index,geometry:g,position:p,index:ix,pv:p.version,iv:ix?.version,matrix:matrix.clone(),ranges:g.userData.snapRanges,
      box:bounds(g).clone().applyMatrix4(matrix),version:-1,vertices:null,edges:null};
    rows[index] = r; return r;
  }
  function worldFeatures(r) {
    if(r.vertices)return;
    const normalMatrix = new THREE.Matrix3().getNormalMatrix(r.matrix), f = features(r.geometry), owner = ownerOf(r.mesh);
    const normal = ns => {
      let best = null;
      for (const n of ns) { const q = n.clone().applyNormalMatrix(normalMatrix); if (!best || Math.abs(q.y) < Math.abs(best.y)) best = q; }
      return best;
    };
    r.vertices=f.vertices.map(v=>({point:v.point.clone().applyMatrix4(r.matrix),normal:normal(v.normals),owner:v.owner || owner,screen:{}}));
    r.edges=f.edges.map(e=>({a:e.a.clone().applyMatrix4(r.matrix),b:e.b.clone().applyMatrix4(r.matrix),normal:normal(e.normals),owner:e.owner || owner,p:{},q:{}}));
    onFeatures(r.mesh,r.instanceId);
  }
  function project(r, rect) {
    if (r.version === cameraVersion) return;
    r.version = cameraVersion; r.minX = r.minY = Infinity; r.maxX = r.maxY = -Infinity;
    let front = 0;
    for (let i=0;i<8;i++) {
      scratch.set(i&1?r.box.max.x:r.box.min.x,i&2?r.box.max.y:r.box.min.y,i&4?r.box.max.z:r.box.min.z);
      if (end.copy(scratch).applyMatrix4(view.camera.matrixWorldInverse).z >= -view.camera.near) continue;
      front++; screen(scratch,rect,projected);
      r.minX=Math.min(r.minX,projected.x); r.maxX=Math.max(r.maxX,projected.x); r.minY=Math.min(r.minY,projected.y); r.maxY=Math.max(r.maxY,projected.y);
    }
    if (front > 0 && front < 8) { r.minX=r.minY=-Infinity; r.maxX=r.maxY=Infinity; }
    r.projected = false;
  }
  function projectFeatures(r, rect) {
    if (r.projected) return;
    worldFeatures(r);
    r.projected = true;
    for (const v of r.vertices) screen(v.point,rect,v.screen);
    for (const e of r.edges) {
      scratch.copy(e.a); end.copy(e.b);
      const za=-projected.copy(scratch).applyMatrix4(view.camera.matrixWorldInverse).z, zb=-projected.copy(end).applyMatrix4(view.camera.matrixWorldInverse).z;
      e.visible = Math.max(za,zb) >= view.camera.near && Math.min(za,zb) <= view.camera.far;
      if (!e.visible) continue;
      const dz=zb-za;
      let lo=0,hi=1;
      if (Math.abs(dz)>1e-10) {
        const t0=(view.camera.near-za)/dz,t1=(view.camera.far-za)/dz;
        lo=Math.max(0,Math.min(t0,t1)); hi=Math.min(1,Math.max(t0,t1));
      }
      scratch.lerpVectors(e.a,e.b,lo); end.lerpVectors(e.a,e.b,hi);
      e.lo=lo; e.hi=hi; e.za=za+dz*lo; e.zb=za+dz*hi;
      screen(scratch,rect,e.p); screen(end,rect,e.q);
    }
  }
  // Keep just three distinct locks. Nearby duplicates prefer a stable owner,
  // then a vertex; otherwise the original vertex-first draw behaviour holds.
  function compare(a,b) {
    if (Math.abs(a.pixels-b.pixels)<=2) return Number(b.stable)-Number(a.stable) || Number(b.vertex)-Number(a.vertex) || (Math.abs(a.pixels-b.pixels)<.25 ? a.depth-b.depth : a.pixels-b.pixels);
    return Number(b.vertex)-Number(a.vertex) || a.pixels-b.pixels || a.depth-b.depth;
  }
  function add(point, normal, owner, vertex, q, event) {
    const pixels=Math.hypot(q.x-event.clientX,q.y-event.clientY);
    if (q.z < -1 || q.z > 1 || pixels > RADIUS) return;
    const stable=!!owner?.kind && !!owner?.pieceId;
    let c; for(const p of pool)if(!candidates.includes(p)) { c=p; break; }
    c.point.copy(point); Object.assign(c.screen,q);
    c.normal=normal; c.owner=owner; c.vertex=vertex; c.pixels=pixels; c.stable=stable; c.blocked=false; c.depth=view.camera.position.distanceTo(point);
    let duplicate=-1; for(let i=0;i<candidates.length;i++)if(candidates[i].point.distanceToSquared(point)<1e-10) { duplicate=i; break; }
    if (duplicate>=0) { if (compare(c,candidates[duplicate])>=0) return; candidates.splice(duplicate,1); }
    if (candidates.length===3 && compare(c,candidates[2])>=0) return;
    candidates.push(c); candidates.sort(compare); if(candidates.length>3)candidates.pop();
  }
  function visit(o, event, rect) {
    if (excluded(o)) return;
    if (o.isMesh && !o.isSkinnedMesh && o.geometry?.attributes.position && o.material && ![].concat(o.material).every(m=>m.visible === false)) {
      const ranges=o.geometry.userData.snapRanges;
      if(o.userData.terrain || ranges?.length && ranges.every(r=>r.terrain)) {
        let r=groundRecords.get(o);
        const p=o.geometry.attributes.position,ix=o.geometry.index;
        if(!r || r.geometry!==o.geometry || r.position!==p || r.pv!==p.version || r.index!==ix || r.iv!==ix?.version || !r.matrix.equals(o.matrixWorld)) {
          r={mesh:o,geometry:o.geometry,position:p,pv:p.version,index:ix,iv:ix?.version,matrix:o.matrixWorld.clone(),box:bounds(o.geometry).clone().applyMatrix4(o.matrixWorld)};
          groundRecords.set(o,r);
        }
        grounds.push(r);
      }
      if (!noSource(o.userData) && !(['water'].includes(o.material.name)) && !(ranges?.length && ranges.every(noSource))) {
        const count=o.isInstancedMesh?o.count:1;
        for(let i=0;i<count;i++) {
          if(o.isInstancedMesh) { o.getMatrixAt(i,instance); instance.premultiply(o.matrixWorld); }
          const r=record(o,o.isInstancedMesh?instance:o.matrixWorld,i); meshes.push(r); project(r,rect);
          if(event.clientX<r.minX-RADIUS || event.clientX>r.maxX+RADIUS || event.clientY<r.minY-RADIUS || event.clientY>r.maxY+RADIUS)continue;
          projectFeatures(r,rect);
          for(const v of r.vertices)add(v.point,v.normal,v.owner,true,v.screen,event);
          for(const e of r.edges) {
            if(!e.visible)continue;
            const dx=e.q.x-e.p.x,dy=e.q.y-e.p.y,d=dx*dx+dy*dy;
            const t=d?Math.max(0,Math.min(1,((event.clientX-e.p.x)*dx+(event.clientY-e.p.y)*dy)/d)):0;
            if(Math.hypot(e.p.x+t*dx-event.clientX,e.p.y+t*dy-event.clientY)>RADIUS)continue;
            const s=view.camera.isOrthographicCamera?t:t*e.za/((1-t)*e.zb+t*e.za);
            scratch.lerpVectors(e.a,e.b,e.lo+s*(e.hi-e.lo)); screen(scratch,rect,projected);
            add(scratch,e.normal,e.owner,false,projected,event);
          }
        }
      }
    }
    for(const child of o.children)visit(child,event,rect);
  }
  function pick(event) {
    const rect=view.renderer3.domElement.getBoundingClientRect(); candidates.length=meshes.length=grounds.length=0;
    view.scene.updateMatrixWorld(); view.camera.updateMatrixWorld();
    projection.multiplyMatrices(view.camera.projectionMatrix,view.camera.matrixWorldInverse);
    const key=`${rect.left}:${rect.top}:${rect.width}:${rect.height}`;
    if(!cameraMatrix.equals(projection)||rectKey!==key) { cameraMatrix.copy(projection); rectKey=key; cameraVersion++; }
    visit(view.scene,event,rect);
    // Batch terrain occlusion once per mesh/move. Bounds reject rays that
    // cannot reach it before their lock, without scanning its feature grid.
    for(const ground of grounds) {
      let mask=0;inverse.copy(ground.matrix).invert();
      for(let i=0;i<candidates.length;i++) {
        const c=candidates[i],q=terrainRays[i];q.blocked=false;
        mouse.set((c.screen.x-rect.left)/rect.width*2-1,1-(c.screen.y-rect.top)/rect.height*2);ray.setFromCamera(mouse,view.camera);
        const depth=ray.ray.origin.distanceTo(c.point)-.003;
        if(!ground.box.containsPoint(ray.ray.origin) && (!ray.ray.intersectBox(ground.box,boxHit)||boxHit.distanceTo(ray.ray.origin)>=depth))continue;
        q.ray.copy(ray.ray).applyMatrix4(inverse);
        q.limit=q.ray.origin.distanceTo(scratch.copy(c.point).applyMatrix4(inverse))-.003/ground.matrix.getMaxScaleOnAxis();mask|=1<<i;
      }
      if(!mask)continue;
      const p=ground.geometry.attributes.position;
      function test(node,active) {
        let next=0;
        for(let i=0;i<candidates.length;i++)if(active&(1<<i)) {
          const q=terrainRays[i];if(!q.blocked && (node.box.containsPoint(q.ray.origin) || q.ray.intersectBox(node.box,boxHit) && boxHit.distanceTo(q.ray.origin)<q.limit))next|=1<<i;
        }
        if(!next)return;
        if(!node.rows) { test(node.left,next);test(node.right,next);return; }
        for(const t of node.rows) {
          triangleA.fromBufferAttribute(p,t.ids[0]);triangleB.fromBufferAttribute(p,t.ids[1]);triangleC.fromBufferAttribute(p,t.ids[2]);
          for(let i=0;i<candidates.length;i++)if(next&(1<<i)) {
            const q=terrainRays[i];if(!q.blocked && q.ray.intersectTriangle(triangleA,triangleB,triangleC,false,boxHit) && boxHit.distanceTo(q.ray.origin)<q.limit)q.blocked=true;
          }
        }
      }
      test(terrainTree(ground.geometry),mask);
      for(let i=0;i<candidates.length;i++)if((mask&(1<<i)) && terrainRays[i].blocked)candidates[i].blocked=true;
    }
    for(const c of candidates) {
      if(c.blocked)continue;
      const {x,y}=c.screen;
      mouse.set((x-rect.left)/rect.width*2-1,1-(y-rect.top)/rect.height*2); ray.setFromCamera(mouse,view.camera);
      const depth=ray.ray.origin.distanceTo(c.point); ray.far=depth-.003;
      let blocked=false;
      for(const r of meshes) {
        if(!r.box.containsPoint(ray.ray.origin) && (!ray.ray.intersectBox(r.box,boxHit) || boxHit.distanceTo(ray.ray.origin)>=ray.far))continue;
        hits.length=0; r.mesh.raycast(ray,hits);
        if(hits.some(h=>h.distance<ray.far)) { blocked=true; break; }
      }
      if(blocked)continue;
      // Proxies remain an occlusion aid, never the source of a snap's host.
      const hit=view.pick(x,y);
      if(hit?.point && ray.ray.origin.distanceTo(scratch.fromArray(hit.point))<depth-.15)continue;
      const at=lot(c.point), n=c.normal;
      return {at,normal:n?[n.x,-n.z,n.y]:[0,0,1],anchor:pointAnchor(getPlan(),c.owner,at),vertex:c.vertex};
    }
    return null;
  }
  return {pick};
}
