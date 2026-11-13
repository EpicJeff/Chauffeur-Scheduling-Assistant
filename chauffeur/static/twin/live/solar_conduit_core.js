// Pure triangle graph and routes. No browser, renderer or import-map dependencies.
export const CONDUIT_OFFSET = 2 / 12;
const WELD = 1 / 12, JOIN = 4 / 12, BRIDGE = 1.5, MAX_TRIANGLES = 50000, MAX_WORK = 2000000;
const FEATURE_COS = Math.cos(10 * Math.PI / 180);
const sub = (a, b) => a.map((v, i) => v - b[i]);
const add = (a, b) => a.map((v, i) => v + b[i]);
const mul = (a, s) => a.map(v => v * s);
const dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0);
const cross3 = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const unit = a => mul(a, 1 / (Math.hypot(...a) || 1));
const distance = (a, b) => Math.hypot(...sub(a, b));
const cross = (a, b) => a[0]*b[1]-a[1]*b[0];
function projection(p, a, b) {
  const d = sub(b, a), t = Math.max(0, Math.min(1, dot(sub(p, a), d) / (dot(d, d) || 1)));
  return {t, at: add(a, mul(d, t))};
}

// Closest point on a filled triangle, including its boundary.
export function trianglePoint(p, [a, b, c]) {
  const ab = sub(b, a), ac = sub(c, a), n = cross3(ab, ac);
  const q = sub(p, mul(n, dot(sub(p, a), n) / (dot(n, n) || 1)));
  const v = sub(q, a), aa = dot(ab, ab), bb = dot(ab, ac), cc = dot(ac, ac), den = aa*cc-bb*bb;
  const u = (dot(v, ab)*cc-dot(v, ac)*bb)/den, w = (dot(v, ac)*aa-dot(v, ab)*bb)/den;
  if (u >= -1e-9 && w >= -1e-9 && u+w <= 1+1e-9) return q;
  return [projection(p,a,b).at, projection(p,b,c).at, projection(p,c,a).at]
    .sort((a,b) => distance(p,a)-distance(p,b))[0];
}

// Bounding trees avoid vertex x edge/triangle scans on detailed cladding.
function bounds(points) {
  return {lo: [0,1,2].map(i => Math.min(...points.map(p => p[i]))),
    hi: [0,1,2].map(i => Math.max(...points.map(p => p[i])))};
}
function tree(items) {
  if (!items.length) return null;
  const box = {lo:[Infinity,Infinity,Infinity],hi:[-Infinity,-Infinity,-Infinity]};
  for (const item of items) for (let i=0;i<3;i++) {
    box.lo[i]=Math.min(box.lo[i],item.lo[i]); box.hi[i]=Math.max(box.hi[i],item.hi[i]);
  }
  if (items.length <= 8) return {...box, items};
  const axis = [0,1,2].sort((a,b) => box.hi[b]-box.lo[b]-(box.hi[a]-box.lo[a]))[0];
  items.sort((a,b) => a.lo[axis]+a.hi[axis]-b.lo[axis]-b.hi[axis]);
  const mid = items.length >> 1;
  return {...box, children: [tree(items.slice(0,mid)), tree(items.slice(mid))]};
}
const boxDistance = (p,b) => Math.hypot(...p.map((v,i) => Math.max(b.lo[i]-v,0,v-b.hi[i])));
function nearby(root, p, radius, visit) {
  if (!root || boxDistance(p,root) > radius) return;
  if (root.items) { for (const item of root.items) if (boxDistance(p,item) <= radius) visit(item); }
  else for (const child of root.children) nearby(child,p,radius,visit);
}
function normalAt(normals) {
  const unique = [];
  for (const n of normals) if (!unique.some(m => dot(n,m) > .999)) unique.push(n);
  return unit(unique.reduce(add,[0,0,0]));
}

function clip(poly,value) {
  const out=[];
  for (let i=0;i<poly.length;i++) {
    const a=poly[i], b=poly[(i+1)%poly.length], va=value(a), vb=value(b);
    if (va>=0) out.push(a);
    if ((va>=0)!==(vb>=0)) out.push(add(a,mul(sub(b,a),va/(va-vb))));
  }
  return out;
}
// The generator retains lower roofs for peeled floors. Clip those hidden
// parts using the rendered triangles themselves, so a dormant lower face
// cannot carry a conduit through a dormer. New edges remain on the same face.
function exposedRoofs(triangles,budget) {
  const roofs=triangles.filter(t=>t.kind==='roof').flatMap(t=>{
    const [a,b,c]=t.points, n=cross3(sub(b,a),sub(c,a));
    const width=Math.hypot(...n)/Math.max(distance(a,b),distance(b,c),distance(c,a));
    if (Math.abs(n[2])<1e-8 || width<WELD) return []; // sub-inch standing-seam relief
    const height=p=>a[2]-(n[0]*(p[0]-a[0])+n[1]*(p[1]-a[1]))/n[2];
    return [{...t,...bounds(t.points),height}];
  });
  const index=tree([...roofs]), output=triangles.filter(t=>t.kind!=='roof');
  function overlaps(root,box,visit) {
    if (!root || [0,1].some(i=>root.hi[i]<box.lo[i] || root.lo[i]>box.hi[i])) return;
    if (root.items) for (const item of root.items) {
      if ([0,1].every(i=>item.hi[i]>=box.lo[i] && item.lo[i]<=box.hi[i])) visit(item);
    } else for (const child of root.children) overlaps(child,box,visit);
  }
  for (const roof of roofs) {
    let pieces=[roof.points];
    overlaps(index,roof,other=>{
      budget(); if (other===roof || !pieces.length) return;
      let cutter=clip(other.points,p=>other.height(p)-roof.height(p)-1e-4);
      if (cutter.length<3) return;
      const winding=Math.sign(cutter.reduce((s,p,i)=>s+cross(p,cutter[(i+1)%cutter.length]),0));
      if (!winding) return;
      const next=[];
      for (const piece of pieces) {
        let rest=piece;
        for (let i=0;i<cutter.length && rest.length;i++) {
          budget(); const a=cutter[i], d=sub(cutter[(i+1)%cutter.length],a);
          const side=p=>winding*cross(d,sub(p,a));
          const outside=clip(rest,p=>-side(p));
          if (outside.length>=3) next.push(outside);
          rest=clip(rest,side);
        }
      }
      pieces=next;
    });
    for (const piece of pieces) for (let i=1;i+1<piece.length;i++) {
      output.push({points:[piece[0],piece[i],piece[i+1]],kind:'roof',building:roof.building});
      budget();
    }
  }
  return output;
}

export function buildSurfaceGraph(triangles) {
  const counts=new Map();
  for (const t of triangles) counts.set(t.building,(counts.get(t.building)||0)+1);
  if (!triangles.length || triangles.length>MAX_TRIANGLES*2 || [...counts.values()].some(n=>n>MAX_TRIANGLES)) return null;
  const nodes = [], faces = [], edges = [], edgeMap = new Map(), cells = new Map();
  let work = 0;
  const budget = () => { if (++work > MAX_WORK) throw new Error('surface work limit'); };
  function node(p, normals = [], weld = false) {
    budget();
    const cell = p.map(v => Math.floor(v/WELD));
    if (weld) for (let x=-1;x<=1;x++) for (let y=-1;y<=1;y++) for (let z=-1;z<=1;z++) {
      for (const id of cells.get([cell[0]+x,cell[1]+y,cell[2]+z].join(',')) || []) {
        if (distance(nodes[id].p,p) <= WELD) {nodes[id].normals.push(...normals); return id;}
      }
    }
    const id = nodes.length; nodes.push({p:[...p], normals:[...normals], links:new Map()});
    if (weld) {const key=cell.join(','); if (!cells.has(key)) cells.set(key,[]); cells.get(key).push(id);}
    return id;
  }
  function link(a,b,factor) {
    budget();
    if (a===b) return;
    const cost=distance(nodes[a].p,nodes[b].p)*factor;
    if (cost < (nodes[a].links.get(b) ?? Infinity)) {nodes[a].links.set(b,cost); nodes[b].links.set(a,cost);}
  }
  try {
    for (const triangle of exposedRoofs(triangles,budget)) {
      const p=triangle.points, n=unit(cross3(sub(p[1],p[0]),sub(p[2],p[0])));
      if (!p.flat().every(Number.isFinite) || Math.hypot(...n)<.9) continue;
      if (triangle.kind==='roof' && n[2]<0) for (let i=0;i<3;i++) n[i]*=-1;
      const planeKey=[...n,dot(n,p[0])].map(v=>Math.round(v*1e4)).join(',');
      const f={...bounds(p), points:p, n, planeKey, kind:triangle.kind, building:triangle.building,
        ids:p.map(p=>node(p,[n],true)), edges:[], inside:[]};
      if (new Set(f.ids).size<3) continue;
      faces.push(f);
      for (let i=0;i<3;i++) {
        const a=f.ids[i], b=f.ids[(i+1)%3], key=[a,b].sort((a,b)=>a-b).join(':');
        if (!edgeMap.has(key)) {
          const e={...bounds([nodes[a].p,nodes[b].p]), a,b,faces:[],splits:[{t:0,id:a},{t:1,id:b}]};
          edgeMap.set(key,e); edges.push(e);
        }
        const e=edgeMap.get(key); e.faces.push(f); f.edges.push(e);
      }
    }
    const faceTree=tree([...faces]), edgeTree=tree([...edges]);
    for (const e of edges) {
      const feature=e.faces.length===1 || e.faces.some(a=>e.faces.some(b=>dot(a.n,b.n)<FEATURE_COS));
      e.factor=(feature?1:2.5)*(e.faces.every(f=>f.kind==='wall')?1.3:1);
    }
    function split(e, at, t) {
      const old=e.splits.find(s=>distance(nodes[s.id].p,at)<1e-6);
      if (old) return old.id;
      const id=node(at,e.faces.map(f=>f.n)); e.splits.push({t,id}); return id;
    }
    const vertexCount=nodes.length, incidentNormals=nodes.map(v=>[...v.normals]);
    for (let id=0;id<vertexCount;id++) {
      const v=nodes[id], nearestEdges=new Map(),nearestFaces=new Map();
      // T junctions: actually split the receiving edge, retaining its cost.
      nearby(edgeTree,v.p,JOIN,e=>{
        budget(); if (e.a===id || e.b===id) return;
        const q=projection(v.p,nodes[e.a].p,nodes[e.b].p);
        const d=distance(q.at,v.p); if (d>JOIN) return;
        for (const f of e.faces) if (d<(nearestEdges.get(f.planeKey)?.d??Infinity)) nearestEdges.set(f.planeKey,{e,q,d});
      });
      for (const {e,q,d} of new Set(nearestEdges.values())) {
        const other=split(e,q.at,q.t); link(id,other,1.3);
        // A coincident junction uses both surface normals for the lift.
        if (d<1e-6) v.normals.push(...nodes[other].normals);
      }
      // A roof endpoint can hit the interior of a tall wall triangle, rather
      // than its edges. Attach there as well; never bridge a large gap.
      nearby(faceTree,v.p,JOIN,f=>{
        budget(); if (f.ids.includes(id) || incidentNormals[id].every(n=>Math.abs(dot(n,f.n))>FEATURE_COS)) return;
        const at=trianglePoint(v.p,f.points),d=distance(at,v.p); if (d>JOIN) return;
        if (d<(nearestFaces.get(f.planeKey)?.d??Infinity)) nearestFaces.set(f.planeKey,{f,at,d});
      });
      for (const {f,at} of nearestFaces.values()) {
        const other=node(at,[f.n]); f.inside.push(other); link(id,other,1.3);
      }
    }
    function edgeLinks(e) {
      e.splits.sort((a,b)=>a.t-b.t);
      for (let i=1;i<e.splits.length;i++) link(e.splits[i-1].id,e.splits[i].id,e.factor);
    }
    for (const e of edges) edgeLinks(e);
    function faceLinks(f,id) {
      const factor=2.5*(f.kind==='wall'?1.3:1);
      for (const e of f.edges) for (const s of e.splits) link(id,s.id,factor);
      for (const other of f.inside) link(id,other,factor);
    }
    for (const f of faces) for (const id of f.inside) faceLinks(f,id);
    // Plan roof planes can stop short of each other where the rendered roofs
    // overlap (a gable ridge ending a foot before the roof it meets). Join each
    // island to the main surface across its shortest gap, up to BRIDGE feet.
    const component=new Int32Array(nodes.length).fill(-1), sizes=[];
    for (let start=0;start<nodes.length;start++) {
      if (component[start]>=0) continue;
      const c=sizes.length, stack=[start]; component[start]=c; let size=0;
      while (stack.length) {const n=stack.pop(); size++; for (const m of nodes[n].links.keys()) if (component[m]<0) {component[m]=c; stack.push(m);}}
      sizes.push(size);
    }
    if (sizes.length>1) {
      const main=sizes.indexOf(Math.max(...sizes)), mainIds=[];
      for (let id=0;id<nodes.length;id++) if (component[id]===main) mainIds.push(id);
      const mainTree=tree(mainIds.map(id=>({...bounds([nodes[id].p]),id})));
      for (let c=0;c<sizes.length;c++) {
        if (c===main) continue;
        let best=null;
        for (let id=0;id<nodes.length;id++) {
          if (component[id]!==c) continue;
          nearby(mainTree,nodes[id].p,BRIDGE,item=>{
            budget(); const d=distance(nodes[id].p,nodes[item.id].p);
            if (d<=BRIDGE && d<(best?.d??Infinity)) best={a:id,b:item.id,d};
          });
        }
        if (best) link(best.a,best.b,3);
      }
    }
    const attached=new Map();
    function attach(p, kind='roof') {
      try {
        const key=JSON.stringify([kind,p]); if (attached.has(key)) return attached.get(key);
        let best=[], span=JOIN;
        nearby(faceTree,p,JOIN,f=>{
          if (kind && f.kind!==kind) return;
          const at=trianglePoint(p,f.points), d=distance(at,p);
          if (d<span-1e-7) {span=d; best=[{f,at}];}
          else if (Math.abs(d-span)<1e-7) best.push({f,at});
        });
        if (!best.length) return null;
        const id=node(best[0].at,best.map(({f})=>f.n));
        // Project onto the triangle's edges so long ridges need no detour to
        // their endpoints just to enter or leave the ridge.
        for (const {f,at} of best) {
          for (const e of f.edges) {
            const q=projection(at,nodes[e.a].p,nodes[e.b].p), other=split(e,q.at,q.t);
            link(id,other,2.5*(f.kind==='wall'?1.3:1)); edgeLinks(e);
          }
          faceLinks(f,id); f.inside.push(id);
        }
        attached.set(key,id); return id;
      } catch (error) {
        if (error.message==='surface work limit') return null;
        throw error;
      }
    }
    return {nodes,faces,edges,faceTree,attach};
  } catch (error) {
    if (error.message==='surface work limit') return null;
    throw error;
  }
}

// Binary heap reverse Dijkstra, shared by a building pair during a rebuild.
function shortest(graph,start,end) {
  const cached=graph.search;
  if (cached?.end===end && cached.size===graph.nodes.length) {
    if (!cached.dist.has(start)) return null;
    const path=[start]; while (path.at(-1)!==end) path.push(cached.prev.get(path.at(-1))); return path;
  }
  const heap=[], dist=new Map([[end,0]]), prev=new Map();
  function push(item) {
    let i=heap.length; heap.push(item);
    while (i) {const parent=(i-1)>>1; if (heap[parent][0]<=item[0]) break; heap[i]=heap[parent]; i=parent;}
    heap[i]=item;
  }
  push([0,end]);
  while (heap.length) {
    const [cost,id]=heap[0], last=heap.pop();
    if (heap.length) {
      let i=0;
      while (i*2+1<heap.length) {
        let j=i*2+1; if (j+1<heap.length && heap[j+1][0]<heap[j][0]) j++;
        if (heap[j][0]>=last[0]) break; heap[i]=heap[j]; i=j;
      }
      heap[i]=last;
    }
    if (cost!==dist.get(id)) continue;
    for (const [next,weight] of graph.nodes[id].links) if (cost+weight<(dist.get(next)??Infinity)) {
      dist.set(next,cost+weight); prev.set(next,id); push([cost+weight,next]);
    }
  }
  graph.search={end,size:graph.nodes.length,dist,prev};
  if (!dist.has(start)) return null;
  const path=[start]; while (path.at(-1)!==end) path.push(prev.get(path.at(-1))); return path;
}
function compact(points) {
  const out=[];
  for (const p of points) {
    if (out.length && distance(out.at(-1),p)<1e-6) continue;
    while (out.length>1) {
      const a=out.at(-2), b=out.at(-1), q=projection(b,a,p);
      if (distance(q.at,b)>1e-7) break;
      out.pop();
    }
    out.push(p);
  }
  return out;
}
function liftedPath(graph,ids) {
  return ids?.map(id=>{const v=graph.nodes[id]; return add(v.p,mul(normalAt(v.normals),CONDUIT_OFFSET));});
}
function onSurface(graph,points) {
  const cache=graph.surfaceNear ||= new Map(),limit=2.5/12;
  const facesAt=p=>{
    const key=p.join(',');if(cache.has(key))return cache.get(key);
    const faces=new Set();
    nearby(graph.faceTree,p,limit+1e-7,f=>{if(distance(p,trianglePoint(p,f.points))<=limit+1e-7)faces.add(f);});
    cache.set(key,faces);return faces;
  };
  // Distance to a convex triangle is convex. If both ends are close to the
  // SAME triangle, the whole span is close: this proves clearance without
  // inch-by-inch sampling. Short seam bridges subdivide until covered too.
  const covered=(a,b,depth=0)=>{
    const left=facesAt(a),right=facesAt(b);
    if(!left.size||!right.size)return false;
    // A short island bridge (see BRIDGE): both ends lie on the surface.
    if(depth===0&&distance(a,b)<=BRIDGE+limit)return true;
    for(const f of left)if(right.has(f))return true;
    if(depth===10)return false;
    const mid=mul(add(a,b),.5);
    return covered(a,mid,depth+1)&&covered(mid,b,depth+1);
  };
  for(let i=0;i<points.length;i++)if(!covered(points[Math.max(0,i-1)],points[i]))return false;
  return true;
}
export function surfacePath(graph,from,to,{keepEnd=false}={}) {
  if (!graph) return null;
  const a=graph.attach(from), b=graph.attach(to);
  if (a===null || b===null) return null;
  const points=liftedPath(graph,shortest(graph,a,b)); if (!points) return null;
  if (keepEnd) points[points.length-1]=[...to];
  const result=compact(points); return onSurface(graph,result)?result:null;
}

function groundRun(plan,a,b,groundAt) {
  const ts=new Set([0,1]), length=Math.hypot(a[0]-b[0],a[1]-b[1]);
  for (let i=1;i<Math.ceil(length);i++) ts.add(i/Math.ceil(length));
  const delta=sub(b,a);
  for (const pad of plan.site?.terraces||[]) for (let i=0;i<pad.polygon.length;i++) {
    const p=pad.polygon[i], q=pad.polygon[(i+1)%pad.polygon.length], edge=sub(q,p), den=cross(delta,edge);
    if (Math.abs(den)<1e-9) continue;
    const v=sub(p,a), t=cross(v,edge)/den, u=cross(v,delta)/den;
    if (t>0 && t<1 && u>=0 && u<=1) for (const d of [-1e-6,0,1e-6]) ts.add(Math.max(0,Math.min(1,t+d)));
  }
  return [...ts].sort((a,b)=>a-b).map(t=>{
    const x=a[0]+delta[0]*t, y=a[1]+delta[1]*t;
    return [x,y,groundAt(plan,x,y)+CONDUIT_OFFSET];
  });
}

function groundPath(graph,from,to,fromBuilding,toBuilding,plan,groundAt) {
  const a=graph.attach(from), b=graph.attach(to); if (a===null || b===null) return null;
  if (shortest(graph,a,b)) return null; // Ground is only for disconnected buildings.
  const bases=id=>graph.edges.filter(e=>e.faces.some(f=>f.building===id && f.kind==='wall') &&
    [e.a,e.b].every(i=>Math.abs(graph.nodes[i].p[2]-groundAt(plan,...graph.nodes[i].p))<JOIN));
  const left=bases(fromBuilding), right=bases(toBuilding); let best=null, span=Infinity, work=0;
  for (const e of left) for (const f of right) {
    if (++work>MAX_WORK) return null;
    const x=graph.nodes[e.a].p, y=graph.nodes[e.b].p, u=graph.nodes[f.a].p, v=graph.nodes[f.b].p;
    for (const p of [x,y]) {const q=projection(p,u,v).at, r=projection(q,x,y).at, d=distance(q,r);
      if (d<span) {span=d; best=[r,q];}}
    for (const p of [u,v]) {const q=projection(p,x,y).at, r=projection(q,u,v).at, d=distance(q,r);
      if (d<span) {span=d; best=[q,r];}}
  }
  if (!best) return null;
  const c=graph.attach(best[0],'wall'), d=graph.attach(best[1],'wall'); if (c===null || d===null) return null;
  const down=liftedPath(graph,shortest(graph,a,c)), up=liftedPath(graph,shortest(graph,d,b));
  if (!down || !up) return null;
  up[up.length-1]=[...to];
  if (!onSurface(graph,down) || !onSurface(graph,up)) return null;
  return compact([...down,...groundRun(plan,down.at(-1),up[0],groundAt),...up]);
}

function sourceTarget(graph,anchor,planes) {
  if (!graph) return null;
  let best=null, span=Infinity;
  for (const f of graph.faces) {
    if (f.kind!=='roof' || !planes.some(s=>f.building===s.building && dot(f.n,s.n)>.999 && Math.abs(dot(sub(f.points[0],s.p),s.n))<.1)) continue;
    const at=trianglePoint(anchor,f.points), d=distance(at,anchor);
    if (d<span) {span=d; best={at,n:f.n};}
  }
  if (!best) return null;
  // The weighted centre of zones on opposite slopes can be inside the roof.
  // Preserve existing valid anchors; otherwise put their shared end on the
  // rendered source roof instead of abandoning every satellite connection.
  return span<=2.5/12?[...anchor]:add(best.at,mul(best.n,CONDUIT_OFFSET));
}

export function routeConduits(input,{groundAt=()=>0,debug=message=>console.debug(message)}={}) {
  const timer=globalThis.CONDUIT_PROFILE?performance.now():0;
  const {triangles,zones,sourcePlanes,anchor,sourceBuilding,site}=input;
  if (!anchor || !sourceBuilding || !zones.length) return [];
  const graphs=new Map(),targets=new Map(),prepared=[],routes=[],plan={site}; let logged=false;
  const skip=()=>{if (!logged) {debug('Solar conduit skipped: no connected house surface or surface budget exceeded'); logged=true;}};
  for (const zone of zones) {
    const ids=[...new Set([zone.building,sourceBuilding])].sort(),key=JSON.stringify(ids);
    if (!graphs.has(key)) graphs.set(key,buildSurfaceGraph(triangles.filter(t=>ids.includes(t.building))));
    const graph=graphs.get(key);
    if (!targets.has(key)) targets.set(key,sourceTarget(graph,anchor,sourcePlanes));
    const target=targets.get(key);
    graph?.attach(zone.start); if (target) graph?.attach(target);
    prepared.push({zone,ids,graph,target});
  }
  for (const {zone,ids,graph,target} of prepared) {
    if (globalThis.CONDUIT_PROFILE && zone===zones[0]) console.log('    build/attach',performance.now()-timer,'nodes',[...graphs.values()].map(g=>g?.nodes.length));
    if (!target) {skip();continue;}
    let points=surfacePath(graph,zone.start,target,{keepEnd:true});
    if (!points && graph && ids.length===2) points=groundPath(graph,zone.start,target,zone.building,sourceBuilding,plan,groundAt);
    if (!points) {skip();continue;}
    routes.push({id:zone.id,entity:zone.entity,points});
  }
  if (globalThis.CONDUIT_PROFILE) console.log('    route total',performance.now()-timer);
  return routes;
}

