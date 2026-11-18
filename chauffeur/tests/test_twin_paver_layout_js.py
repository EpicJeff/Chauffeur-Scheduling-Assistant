"""Pure lot-foot paver placement and joint clearance through the real Node module."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
const {PAVER_DEFAULTS,MAX_PAVERS,paverSettings,paverEstimate,paverLayout}=await import(file('static/twin/paver_layout.js'));
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} near ${b}`);
const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
const area=p=>Math.abs(p.reduce((sum,a,i)=>{const b=p[(i+1)%p.length];return sum+a[0]*b[1]-a[1]*b[0];},0))/2;
const inside=(p,q)=>p.every((a,i)=>cross(a,p[(i+1)%p.length],q)>=-1e-8);
function intersection(a,b){
 let out=a;
 for(let i=0;i<b.length;i++){
  const c=b[i],d=b[(i+1)%b.length],input=out;out=[];
  input.forEach((q,j)=>{const p=input[(j+input.length-1)%input.length],u=cross(c,d,p),v=cross(c,d,q);
   if((u>=0)!==(v>=0))out.push(p.map((x,k)=>x+(q[k]-x)*u/(u-v)));
   if(v>=0)out.push(q);
  });
 }
 return area(out);
}
const path={points:[[0,0],[20,0]],width:6,pavers:{layout:'grid',length_in:24,width_in:24,gap_in:3}};
const layout=(pavers={},other={})=>paverLayout({...path,...other,pavers:{...path.pavers,...pavers}});
const inStrip=(p,width=6,length=20)=>p.polygon.every(([x,y])=>x>=-1e-6&&x<=length+1e-6&&Math.abs(y)<=width/2+1e-6);
const noOverlap=(ps,fraction)=>{for(let i=0;i<ps.length;i++)for(let j=0;j<i;j++)assert.ok(intersection(ps[i].polygon,ps[j].polygon)<=fraction*Math.min(area(ps[i].polygon),area(ps[j].polygon))+1e-4,`overlap ${i},${j}`);};
const grid=layout();assert.equal(grid.pavers.length,18,'straight_grid: nine rows, two across');
for(const p of grid.pavers){assert.equal(p.polygon.length,4);assert.ok(inStrip(p));p.polygon.forEach((a,i)=>near(Math.hypot(...a.map((v,k)=>v-p.polygon[(i+1)%4][k])),2));}
const rows=[...new Set(grid.pavers.map(p=>p.centre[0]))];for(let i=1;i<rows.length;i++)near(rows[i]-rows[i-1],27/12);
console.log('ok straight_grid');
const stepping=layout({layout:'stepping'},{width:10});assert.equal(stepping.pavers.length,9);stepping.pavers.forEach((p,i)=>{near(p.centre[1],0);if(i)near(p.centre[0]-stepping.pavers[i-1].centre[0],27/12);});
console.log('ok stepping_ignores_width');
const narrow=layout({edge:'whole'},{width:1});assert.equal(narrow.pavers.length,9);narrow.pavers.forEach(p=>near(p.centre[1],0));
const narrowCut=layout({edge:'cut'},{width:1});assert.ok(narrowCut.pavers.length);narrowCut.pavers.forEach(p=>assert.ok(inStrip(p,1)));
console.log('ok at_least_one_across');
const bond=layout({layout:'running_bond'}).pavers,bondRows=[...new Set(bond.map(p=>p.centre[0]))];
for(let i=1;i<bondRows.length;i++){const first=s=>Math.min(...bond.filter(p=>p.centre[0]===s).map(p=>p.centre[1]));near(Math.abs(first(bondRows[i])-first(bondRows[i-1])),27/24);}
console.log('ok running_bond_offset');
const cut=layout({layout:'diagonal',edge:'cut'});assert.ok(cut.pavers.length);assert.ok(cut.pavers.some(p=>p.polygon.length!==4));
cut.pavers.forEach(p=>{assert.ok(inStrip(p));assert.ok(area(p.polygon)>=.4-1e-6);});
console.log('ok cut_clips');
const whole=layout({layout:'diagonal',edge:'whole'});assert.ok(whole.pavers.length);whole.pavers.forEach(p=>{assert.equal(p.polygon.length,4);assert.ok(inStrip(p));});
console.log('ok whole_keeps_whole');
for(const rotation of [0,17,-45]){
 const ps=layout({layout:'herringbone',length_in:16,width_in:8,gap_in:.5,rotation}).pavers;assert.ok(ps.length>10);
 assert.ok(ps.some(p=>Math.abs(Math.sin(p.angle-ps[0].angle))>.99),'both orientations');
 ps.forEach(p=>{assert.equal(p.polygon.length,4);const sides=p.polygon.map((a,i)=>Math.hypot(...a.map((v,k)=>v-p.polygon[(i+1)%4][k]))).sort((a,b)=>a-b);near(sides[0],8/12);near(sides[3],16/12);near(Math.sin(2*(p.angle-ps[0].angle)),0);});noOverlap(ps,0);
}
for(const [length_in,width_in,gap_in] of [[17,10,0],[8,16,.5]])noOverlap(layout({layout:'herringbone',length_in,width_in,gap_in}).pavers,0);
assert.deepEqual(layout({layout:'herringbone'}),grid,'square herringbone falls back to grid');
console.log('ok herringbone');
for(const shape of [{smooth:true,corner:'rounded',radius:3},{corner:'rounded',radius:3},{corner:'mitred'}]){
 const ps=layout({}, {...shape,points:[[0,0],[10,0],[10,10]]}).pavers;assert.ok(ps.length);noOverlap(ps,.1);
}
console.log('ok curve_no_overlap');
near(grid.jointWidth,.25);assert.ok(grid.joints.some(([a,b])=>Math.abs(a[0]-b[0])<1e-6));assert.ok(grid.joints.some(([a,b])=>Math.abs(a[1]-b[1])<1e-6));
const curvedSteps=layout({layout:'stepping',length_in:12,width_in:8},{points:[[0,0],[10,0],[10,10]],smooth:true});
assert.ok(curvedSteps.joints.some(([a,b])=>Math.abs(a[0]-b[0])>1e-4&&Math.abs(a[1]-b[1])>1e-4),'joints follow a bend between nonparallel stones');
for(const result of [grid,cut,curvedSteps,layout({layout:'herringbone',length_in:16,width_in:8,gap_in:.5}),layout({}, {points:[[0,0],[10,0],[10,10]],corner:'rounded',radius:3})]){
 assert.ok(result.joints.length);for(const [a,b] of result.joints)for(const t of [0,.25,.5,.75,1])assert.ok(result.pavers.every(p=>!inside(p.polygon,a.map((v,k)=>v+(b[k]-v)*t))),'joint stays outside stones');
}
console.log('ok joints_in_gaps');
const huge={...path,points:[[0,0],[100,0]],width:4,pavers:{length_in:2,width_in:2,gap_in:0}};
assert.equal(paverEstimate(huge),14400);assert.ok(paverEstimate(huge)>MAX_PAVERS);assert.throws(()=>paverLayout(huge),/Use larger pavers or a shorter path\./);
near(paverEstimate({...path,pavers:{layout:'stepping'}}),Math.ceil(20*2/(2.25*2.25)));
console.log('ok estimate');
assert.deepEqual(paverLayout({points:[[0,0],[5,0]],width:3}),{pavers:[],joints:[],jointWidth:0});
assert.equal(paverSettings({...path,pavers:null}),null);assert.deepEqual(paverSettings({...path,pavers:{}}),PAVER_DEFAULTS);
assert.deepEqual(layout(),grid,'deterministic');assert.deepEqual(layout({gap_in:0}).joints,[]);
console.log('ok none_without_field');
"""


def run():
    with tempfile.TemporaryDirectory(prefix='chauffeur_paver_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix()}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=60)
        print(result.stdout, end='')
        assert result.returncode == 0, result.stderr


if __name__ == '__main__':
    run()
