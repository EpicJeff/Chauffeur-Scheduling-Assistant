const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ctx = {window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[2] || require('node:path').join(__dirname,'../static/house_clip.js'),'utf8'),ctx);
const C=ctx.window.HouseClip;
// Independent segment formulation: p = camera + t * (boxPoint - camera).
// Solve the six linear inequalities for a feasible t in [0,1].
function inHull(p,c,b) {
  let lo=0,hi=1;
  function less(a,d) {
    if(Math.abs(a)<1e-12)return d>=-1e-9;
    if(a>0)hi=Math.min(hi,d/a);else lo=Math.max(lo,d/a);
    return lo<=hi+1e-9;
  }
  for(let i=0;i<3;i++) {
    const d=p[i]-c[i];
    if(!less(b[2*i]-c[i],d)||!less(c[i]-b[2*i+1],-d))return false;
  }
  return lo<=hi+1e-9;
}
let samples=0;
for(const c of [[0,12,25],[-12,8,15],[12,8,15],[0,18,0],[0,3,0]]) {
  const b=[-6,6,0,16,-6,14],m=C.maskPlanes(c,b);
  for(let x=-16;x<=16;x+=2)for(let y=-4;y<=24;y+=2)for(let z=-16;z<=32;z+=2) {
    const p=[x,y,z];
    const actual=m.P.every(pl=>pl.n.reduce((s,v,i)=>s+v*p[i],0)-pl.d>=-1e-8);
    assert.equal(actual,inHull(p,c,b),`hull boundary camera=${c} point=${p}`);samples++;
  }
  // A roof-height point beyond the far footprint must never be clipped.
  assert.equal(C.pointMasked([0,17,-12],m),false);
}
console.log(`Bounded camera volume: ${samples} independent membership checks passed`);
