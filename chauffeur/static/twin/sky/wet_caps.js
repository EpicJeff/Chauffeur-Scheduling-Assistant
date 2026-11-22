import { inPolygon, poolDatum } from '../twin_ground.js';
import { offsetOutline, spaCopingLayout } from '../pool_features.js';
import { buildPadEdge } from '../pad_edge_geometry.js';
import { HEIGHT_NONE } from './sky_cover.js';

const FT = .3048;
const same = (a, b) => Math.hypot(a[0]-b[0], a[1]-b[1]) < 1e-6;

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
    const tops=[];
    buildPadEdge(plan,pad,i,g=>g.dispose(),(polygon,top)=>tops.push({polygon,top}));
    caps.push(...joinTops(tops));
  }
  return caps.map(c=>({...c,bounds:[Math.min(...c.polygon.map(p=>p[0])),Math.min(...c.polygon.map(p=>p[1])),
    Math.max(...c.polygon.map(p=>p[0])),Math.max(...c.polygon.map(p=>p[1]))]}));
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
