import { inPolygon, poolDatum, edgeDistance } from '../twin_ground.js';
import { offsetOutline, spaCopingLayout } from '../pool_features.js';
import { buildPadEdge } from '../pad_edge_geometry.js';
import { RETAINING_WALL_PROUD_FT } from '../twin_retaining_wall.js';
import { HEIGHT_NONE } from './sky_cover.js';

const FT = .3048;
const same = (a, b) => Math.hypot(a[0]-b[0], a[1]-b[1]) < 1e-6;
const withBounds = caps => caps.map(c=>({...c,bounds:polygonBounds(c.polygon)}));
const polygonBounds = polygon => [Math.min(...polygon.map(p=>p[0])),Math.min(...polygon.map(p=>p[1])),
  Math.max(...polygon.map(p=>p[0])),Math.max(...polygon.map(p=>p[1]))];

function padCaps(plan,pad,index) {
  const tops=[];
  buildPadEdge(plan,pad,index,g=>g.dispose(),(polygon,top)=>tops.push({polygon,top}));
  return joinTops(tops);
}

// Join the wall builder's consecutive, coplanar prism tops. Internal prism
// boundaries must not become reflection seams, or cost a raster pass apiece.
function joinTops(tops) {
  const result = [];
  for (const top of tops) {
    const last = result.at(-1);
    let joined = false;
    if (last && Math.abs(last.top-top.top)<1e-6) {
      const a=last.polygon, b=top.polygon;
      for(let i=0;i<a.length&&!joined;i++)for(let j=0;j<b.length&&!joined;j++) {
        if(!same(a[i],b[(j+1)%b.length])||!same(a[(i+1)%a.length],b[j]))continue;
        last.polygon=[...a.slice(i+1),...a.slice(0,i+1),...Array.from({length:b.length-2},(_,k)=>b[(j+2+k)%b.length])];
        // Remove collinear vertices as well as the shared edge.
        last.polygon=last.polygon.filter((p,k,all)=>{
          const q=all[(k+all.length-1)%all.length],r=all[(k+1)%all.length];
          return Math.abs((p[0]-q[0])*(r[1]-p[1])-(p[1]-q[1])*(r[0]-p[0]))>1e-8;
        });
        joined=true;
      }
    }
    if(!joined)result.push(top);
  }
  return result;
}

export function collectCapSurfaces(plan={}) {
  const site=plan.site||{},pool=site.pool,caps=[];
  if(pool?.polygon?.length>=3) {
    const height=poolDatum(plan,pool),spas=(pool.features||[]).filter(f=>f.kind==='spa'&&f.polygon?.length>=3);
    if((pool.coping??1)>0)caps.push({polygon:offsetOutline(pool.polygon,pool.coping??1),
      holes:[pool.polygon,...spas.map(f=>f.polygon)],top:height+.45});
    for(const f of spas) {
      const layout=spaCopingLayout(pool,f,height);
      caps.push(...joinTops(layout.tops.map(t=>({...t,top:layout.copingTop}))));
    }
  }
  for(const pad of site.terraces||[])for(let i=0;i<(pad.polygon?.length||0);i++) {
    const edge=pad.edges?.[i];
    if(edge?.edge!=='sharp'||!(edge.wall?.cap||edge.stair))continue;
    caps.push(...padCaps(plan,pad,i));
  }
  return withBounds(caps);
}

// Feet in the plan frame. No render geometry or per-edge terrain sampling at indexing
// time. groundAt starts at zero and applies ordered replacements/blends, so
// every layer sample stays within this global height interval. Deliberately
// conservative bounds retain narrow depressions, reversed wall sides and
// Float32 wall-body rounding. Exact tops still come from the original builder.
export function createCapSurfaceIndex(plan={}) {
  const site=plan.site||{},pool=site.pool,sources=[];
  // A malformed terrace height must not turn the bounds into NaN and reject every cap.
  const heights=[0,...(site.terraces||[]).map(p=>Number(p.height)).filter(Number.isFinite)];
  const low=Math.min(...heights),high=Math.max(...heights);
  const add=(polygon,heightRange,build,padding=0)=>{
    const bounds=polygonBounds(polygon);
    // Wall bodies round plan coordinates/heights through Float32 buffers.
    const epsilon=Math.max(1,...bounds.map(Math.abs),...heightRange.map(Math.abs))*2**-22+1e-8;
    bounds[0]-=padding+epsilon;bounds[1]-=padding+epsilon;
    bounds[2]+=padding+epsilon;bounds[3]+=padding+epsilon;
    let caps;
    sources.push({bounds,heightRange:[heightRange[0]-epsilon,heightRange[1]+epsilon],
      // A diagonal wall's axis-aligned box can cover most of the yard. Its
      // two-point footprint is a conservative capsule around the edge, with
      // room for either terrain side, the cap overhang and Float32 rounding.
      contains:polygon.length===2?(x,y)=>edgeDistance([x,y],...polygon)<=padding+2*epsilon:()=>true,
      get surfaces(){return caps??(caps=withBounds(build()));}});
  };
  if(pool?.polygon?.length>=3) {
    const height=poolDatum(plan,pool),spas=(pool.features||[]).filter(f=>f.kind==='spa'&&f.polygon?.length>=3);
    if((pool.coping??1)>0) {
      const polygon=offsetOutline(pool.polygon,pool.coping??1),top=height+.45;
      add(polygon,[top,top],()=>[{polygon,holes:[pool.polygon,...spas.map(f=>f.polygon)],top}]);
    }
    for(const f of spas) {
      // This is polygon layout only, shared with the drawn spa; it allocates
      // no meshes. Include inner corners that can extend beyond concave rims.
      const layout=spaCopingLayout(pool,f,height),top=layout.copingTop;
      add(layout.tops.flatMap(t=>t.polygon),[top,top],()=>joinTops(layout.tops.map(t=>({...t,top}))));
    }
  }
  for(const pad of site.terraces||[])for(let i=0;i<(pad.polygon?.length||0);i++) {
    const edge=pad.edges?.[i];
    if(edge?.edge!=='sharp'||!(edge.wall?.cap||edge.stair))continue;
    const a=pad.polygon[i],b=pad.polygon[(i+1)%pad.polygon.length],length=Math.hypot(b[0]-a[0],b[1]-a[1]);
    if(!length)continue;
    if(edge.wall) {
      if(!edge.wall.cap)continue; // wall wins over stair in buildPadEdge
      const cap=edge.wall.cap,above=(edge.wall.above_in??0)/12,thickness=(cap.thickness_in??2)/12;
      add([a,b],[low+above+thickness,high+above+thickness],()=>padCaps(plan,pad,i),
        Math.max(RETAINING_WALL_PROUD_FT,Math.abs((edge.wall.thickness_in??8)/12))+Math.abs((cap.overhang_in??1)/12));
    } else {
      const stair=edge.stair,nose=stair.treads!==false?1/12:0;
      const count=Math.max(1,Math.ceil((pad.height-low)/((stair.riser_in??7)/12))),run=(stair.tread_in??11)/12*count;
      const winding=Math.sign(pad.polygon.reduce((s,p,j)=>{const q=pad.polygon[(j+1)%pad.polygon.length];return s+p[0]*q[1]-p[1]*q[0];},0));
      const out=[(b[1]-a[1])/length*winding,-(b[0]-a[0])/length*winding];
      add([a,b,...[a,b].map(p=>[p[0]+out[0]*(run+nose),p[1]+out[1]*(run+nose)])],
        [low,pad.height],()=>padCaps(plan,pad,i),nose);
    }
  }
  // Keep source order even when queried out of order. Empty sources are cached
  // too; repeated misses inside a box must never rebuild a wall or stair.
  return (x,y,ceiling)=>sources.filter(s=>x>=s.bounds[0]&&x<=s.bounds[2]&&y>=s.bounds[1]&&y<=s.bounds[3]
    &&s.heightRange[0]<ceiling&&s.contains(x,y)).flatMap(s=>s.surfaces);
}

const distance=(poly,x,y)=>{
  let best=Infinity;
  for(let i=0;i<poly.length;i++) {
    const a=poly[i],b=poly[(i+1)%poly.length],dx=b[0]-a[0],dy=b[1]-a[1],length=dx*dx+dy*dy;
    const t=length?Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/length)):0;
    const ex=x-a[0]-t*dx,ey=y-a[1]-t*dy;
    best=Math.min(best,ex*ex+ey*ey);
  }
  return Math.sqrt(best)*FT;
};

// RG16F: cap SDF and its own top, with 0.3 m of height dilation. Work only
// within each top's small box. No full-lot polygon search or per-frame work.
export function createCapBaker(caps,field) {
  const {width,height,bounds}=field,dx=(bounds[2]-bounds[0])/width,dz=(bounds[3]-bounds[1])/height;
  const data=new Float32Array(width*height*2);
  for(let k=0;k<data.length;k+=2){data[k]=-1;data[k+1]=HEIGHT_NONE;}
  const boxes=caps.map(c=>({c,i0:Math.max(0,Math.floor((c.bounds[0]*FT-.3-bounds[0])/dx)),
    i1:Math.min(width-1,Math.floor((c.bounds[2]*FT+.3-bounds[0])/dx)),
    j0:Math.max(0,Math.floor((-c.bounds[3]*FT-.3-bounds[1])/dz)),
    j1:Math.min(height-1,Math.floor((-c.bounds[1]*FT+.3-bounds[1])/dz))}));
  let index=0,row=boxes[0]?.j0??0,done=false;
  const result={cell:dx,width,height,bounds,data};
  function step(budgetMs=Infinity) {
    const end=Number.isFinite(budgetMs)?performance.now()+Math.max(0,budgetMs):Infinity;
    while(index<boxes.length) {
      const {c,i0,i1,j1}=boxes[index];
      while(row<=j1) {
        const y=-(bounds[1]+(row+.5)*dz)/FT;
        for(let i=i0;i<=i1;i++) {
          const x=(bounds[0]+(i+.5)*dx)/FT;
          let d=distance(c.polygon,x,y)*(inPolygon(c.polygon,x,y)?1:-1);
          for(const hole of c.holes||[])d=Math.min(d,distance(hole,x,y)*(inPolygon(hole,x,y)?-1:1));
          const k=(row*width+i)*2;
          if(d>0&&data[k]>0) {
            // A tread's nosing can overhang the next tread: only the upper
            // surface is exposed. Outside both tops the nearest still wins.
            data[k]=Math.min(1,Math.max(data[k],d));data[k+1]=Math.max(data[k+1],c.top*FT);
          } else if(d>data[k]) {data[k]=Math.min(1,d);data[k+1]=d>=-.3?c.top*FT:HEIGHT_NONE;}
        }
        row++;
        if(performance.now()>=end)return false;
      }
      index++;row=boxes[index]?.j0??0;
    }
    done=true;return true;
  }
  return {result,step,finish(){step();return result;},get done(){return done;}};
}
