// Shared by the generator, editor and energy anchors. Building-local feet, z up.
import { roofMesh, planes as sidePlanes } from './twin_roof.js';
export const SOLAR_DEFAULTS = {panel_width: 65/12, panel_height: 39/12, orientation: 'portrait', gap: 1/12, setback: 0, count: null, entity: null};
const dot = (a, b) => a.reduce((s, v, i) => s + v*b[i], 0);
const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const unit = a => a.map(v => v/Math.hypot(...a));
export const solarRect = ([x,y,X,Y]) => [[x,y],[X,y],[X,Y],[x,Y]];
export function solarFrame(plane) {
  const n = unit([-plane[0], -plane[1], 1]), u = unit([1-n[0]*n[0], -n[0]*n[1], -n[0]*n[2]]);
  return {origin: [0,0,plane[2]], u, v: cross(n,u), n};
}
export function solarPoint(plane, [x,y], offset = 0) {
  const {origin,u,v,n} = solarFrame(plane);
  return origin.map((p,i) => p+u[i]*x+v[i]*y+n[i]*offset);
}
export function solarUV(plane, point) {
  const {origin,u,v} = solarFrame(plane), p = point.map((x,i) => x-origin[i]);
  return [dot(p,u),dot(p,v)];
}
const planeCache = new WeakMap();
export function solarPlanes(building, envelope = null) {
  if(!envelope && planeCache.get(building)?.sections===building.roof?.sections)return planeCache.get(building)?.result || [];
  const sections = building.roof?.sections || [], mesh = envelope || roofMesh(sections), groups = new Map();
  for (let i=0; i<mesh.positions.length; i+=9) {
    const p=[0,3,6].map(j=>Array.from(mesh.positions.slice(i+j,i+j+3))), n=cross(p[1].map((v,j)=>v-p[0][j]),p[2].map((v,j)=>v-p[0][j]));
    if (Math.abs(n[2])<1e-8) continue;
    const section=sections[mesh.section[i/9]], roof=section?.roof || section?.id;
    const plane=sidePlanes(section).sort((a,b)=>Math.abs(a[0]*p[0][0]+a[1]*p[0][1]+a[2]-p[0][2])+Math.abs(a[0]+n[0]/n[2])+Math.abs(a[1]+n[1]/n[2])-(Math.abs(b[0]*p[0][0]+b[1]*p[0][1]+b[2]-p[0][2])+Math.abs(b[0]+n[0]/n[2])+Math.abs(b[1]+n[1]/n[2])))[0];
    const key=roof+':'+plane.join(',');
    if(!groups.has(key))groups.set(key,{roof,plane,triangles:[]});
    groups.get(key).triangles.push(p.map(q=>solarUV(plane,q)));
  }
  const result=[...groups.values()];
  if(!envelope)planeCache.set(building,{sections:building.roof?.sections,result});
  return result;
}
const area = poly => Math.abs(poly.reduce((s,p,i)=>{const q=poly[(i+1)%poly.length];return s+p[0]*q[1]-p[1]*q[0];},0))/2;
export function solarCovered(rect, plane) {
  if (!plane) return false;
  const covered=plane.triangles.reduce((sum,t)=>{
    let poly=t;
    for(const [axis,edge,sign] of [[0,rect[0],1],[0,rect[2],-1],[1,rect[1],1],[1,rect[3],-1]]){
      const out=[];
      for(let i=0;i<poly.length;i++){
        const a=poly[i],b=poly[(i+1)%poly.length],ain=sign*(a[axis]-edge)>=0,bin=sign*(b[axis]-edge)>=0;
        if(ain)out.push(a);
        if(ain!==bin){const f=(edge-a[axis])/(b[axis]-a[axis]);out.push(a.map((v,j)=>v+f*(b[j]-v)));}
      }poly=out;
    }return sum+area(poly);
  },0);
  return covered >= (rect[2]-rect[0])*(rect[3]-rect[1])-1e-4;
}
export function solarLayout(zone) {
  const z={...SOLAR_DEFAULTS,...zone}, r=z.rect, g=z.gap,s=z.setback;
  let [w,h]=[z.panel_width,z.panel_height].sort((a,b)=>a-b);
  if(z.orientation==='landscape')[w,h]=[h,w];
  if(!r || w<=0 || h<=0 || g<0 || s<0)return [];
  const cols=Math.max(0,Math.floor((r[2]-r[0]-2*s+g+1e-7)/(w+g))), maxRows=Math.max(0,Math.floor((r[3]-r[1]-2*s+g+1e-7)/(h+g)));
  const count=Math.min(cols*maxRows,z.count ?? cols*maxRows,10000), out=[];
  if(count<=0)return out;
  const rows=Math.ceil(count/cols),y=(r[1]+r[3]-(rows*h+(rows-1)*g))/2;
  for(let row=0;row<rows;row++){
    const n=Math.min(cols,count-out.length),x=(r[0]+r[2]-(n*w+(n-1)*g))/2;
    for(let i=0;i<n;i++)out.push([x+i*(w+g),y+row*(h+g),x+i*(w+g)+w,y+row*(h+g)+h]);
  }return out;
}
export function solarZones(building, envelope = null) {
  const planes=solarPlanes(building,envelope);
  return (building.solar_zones || []).filter(z=>z.state!=='ghost').flatMap(zone=>{
    const plane=planes.find(p=>p.roof===zone.roof && p.plane.every((v,i)=>Math.abs(v-zone.plane[i])<1e-5));
    return solarCovered(zone.rect,plane)?[{zone,panels:solarLayout(zone).filter(r=>solarCovered(r,plane))}]:[];
  });
}
