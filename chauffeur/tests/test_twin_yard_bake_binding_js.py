"""Every yard triangle the bake charts receives its baked light in the drawn scene.

v2.499.948 moved the bake onto a neutral, material-free copy of the house and yard and
binds the drawn meshes back to it by their named parents. The twin draws the yard under
its 'site' group while the neutral yard sits straight in the bake source, so on a house
with any custom finish not one yard triangle matched: lawn, pool shell, deck, fences and
fire pit all rendered without their baked lights (owner report 2026-11-20, v2.499.962).
A house with only default finishes hid it, because its cloned bake geometry carried a
second copy of the drawn yard. This builds the household fixture the way twin_view does
(yard under groups.site), both with default finishes and with one custom finish.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_twin_tree_once_js import PREFIX  # noqa: E402
from twin_editor_dom import run_node  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HOUSEHOLD = ROOT / 'tests' / 'fixtures' / 'twin_model' / 'household-2026-11-09.json'

DRIVER = PREFIX + r"""
const THREE=await import('three');
THREE.TextureLoader.prototype.load=function(url,done){const t=new THREE.Texture();queueMicrotask(()=>done?.(t));return t;};
window.chfBase=file('');
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {buildAtlas,atlasMesh}=await import(file('static/twin/bake/atlas.js'));
const {defaultBuildingFinishes,releaseBakeSource}=await import(file('static/twin/bake/source.js'));
const options={room:{density:1,page:1024,gutter:2}};
const charts={};
for(const mode of ['default','finished']){
  const plan=structuredClone(input.plan);
  if(mode==='finished'){const room=plan.buildings[0].rooms.find(r=>r.polygon?.length>=3);room.floor_material={id:input.finish};}
  assert.equal(defaultBuildingFinishes(plan,input.kit),mode==='default',mode+' takes the '+(mode==='default'?'clone':'neutral')+' bake source');
  const h=buildTwin(plan,input.kit,'low',{viewing:true});await h.ready;
  const y=await buildYard(plan,input.kit,'low',{viewing:true});
  // As twin_view adopts it: the yard is drawn inside the twin's 'site' group.
  h.groups.site.add(y.group);h.root.updateMatrixWorld(true);
  const atlas=buildAtlas(h.root,plan,options);
  assert.ok(atlas.sourceRoot && atlas.sourceRoot!==h.root,mode+' bakes from a separate source');
  // Measured in world area: an exactly copied mesh keeps the zero-area slivers the
  // atlas never charts (lmRoom -1, nothing drawn), the projected path drops them.
  const area=new THREE.Triangle(),P=[0,1,2].map(()=>new THREE.Vector3());
  const totals={yard:[0,0,0],house:[0,0,0]},lostParts=new Map();
  h.root.traverse(o=>{
    if(!atlasMesh(o))return;
    const a=o.geometry.attributes.lmRoom,pos=o.geometry.attributes.position;assert.ok(a,mode+' every receiver carries lmRoom');
    let inYard=false;for(let p=o;p;p=p.parent)if(p===y.group)inYard=true;
    const t=totals[inYard?'yard':'house'];
    for(let i=0;i<a.count;i+=3){
      P.forEach((v,k)=>v.fromBufferAttribute(pos,i+k).applyMatrix4(o.matrixWorld));
      const s=area.set(...P).getArea();t[0]++;t[1]+=s;
      if(a.getX(i)<-0.5 && s>1e-9){t[2]+=s;const names=[];for(let p=o;p&&p!==h.root;p=p.parent)if(p.name)names.push(p.name);
        const k=o.material.name+' @ '+names.join('<');lostParts.set(k,(lostParts.get(k)||0)+s);}
    }
  });
  const share=t=>t[2]/t[1],top=JSON.stringify([...lostParts].sort((a,b)=>b[1]-a[1]).slice(0,8));
  console.log('AREA '+mode+' yard '+totals.yard[0]+' tris unbound '+(100*share(totals.yard)).toFixed(3)+'%, house '+totals.house[0]+' tris unbound '+(100*share(totals.house)).toFixed(3)+'%');
  assert.ok(totals.yard[0]>1000,mode+' the household yard has receivers: '+totals.yard[0]);
  if(!input.diagnose)assert.equal(totals.yard[2],0,mode+' yard area without a lightmap: '+top);
  // The atlas skips a few house faces by design (no chart), well under half a percent.
  if(!input.diagnose)assert.ok(share(totals.house)<0.005,mode+' house area without a lightmap: '+top);
  // The yard is charted once: its neutral copy, not also a clone of the drawn one.
  const yardCharts=atlas.room.charts.filter(c=>{for(let p=c.mesh;p;p=p.parent)if(p.name==='yard')return true;return false;}).length;
  charts[mode]={all:atlas.room.charts.length,yard:yardCharts};
  console.log('PASS '+mode+' yard and house bound, charts '+JSON.stringify(charts[mode]));
  releaseBakeSource(h.root);
}
assert.ok(charts.default.yard>0,'yard charts exist');
assert.deepEqual(charts.default,charts.finished,'a finish changes no chart; the clone path charts the yard once');
console.log('PASS yard binds under the site group on both bake-source paths');

// Roof-only edit reusing the drawn yard: writeWeatherOpen(yard, newCover) must
// re-clip the neutral bake copy identically so every yard triangle still binds
// cleanly with identical pre-atlas topology and zero unbound area.
{
  const {bakeSource}=await import(file('static/twin/bake/source.js'));
  const {writeWeatherOpen}=await import(file('static/twin/sky/sky_cover.js'));
  const plan1=structuredClone(input.plan);
  const room=plan1.buildings[0].rooms.find(r=>r.polygon?.length>=3);
  room.floor_material={id:input.finish};
  const h1=buildTwin(plan1,input.kit,'low',{viewing:true});await h1.ready;
  const y=await buildYard(plan1,input.kit,'low',{viewing:true,skyCover:h1.skyCover});
  h1.groups.site.add(y.group);h1.root.updateMatrixWorld(true);

  const plan2=structuredClone(plan1);
  for(const sec of plan2.buildings[0].roof?.sections||[])sec.overhang=(sec.overhang??1.5)+3;
  const h2=buildTwin(plan2,input.kit,'low',{viewing:true});await h2.ready;
  assert.notEqual(h2.skyCover.staticKey,h1.skyCover.staticKey,'roof overhang edit changes static cover key');
  y.group.removeFromParent();h2.groups.site.add(y.group);h2.root.updateMatrixWorld(true);
  const yardVertsBefore=[];y.group.traverse(o=>{if(atlasMesh(o))yardVertsBefore.push(o.geometry.attributes.position.count);});
  writeWeatherOpen(y.group,h2.skyCover);
  const yardVertsAfter=[];y.group.traverse(o=>{if(atlasMesh(o))yardVertsAfter.push(o.geometry.attributes.position.count);});
  assert.notDeepEqual(yardVertsAfter,yardVertsBefore,'roof overhang edit actually re-clipped drawn yard meshes');
  // Before buildAtlas runs, the neutral yard copy must have bit-for-bit
  // identical positions to the drawn yard on every receiver mesh (same clip).
  const srcRoot=bakeSource(h2.root);
  const drawnPos=[],neutralPos=[];
  y.group.traverse(o=>{if(atlasMesh(o))drawnPos.push(Array.from(o.geometry.attributes.position.array));});
  srcRoot.traverse(o=>{if(atlasMesh(o)){let inYard=false;for(let p=o;p;p=p.parent)if(p.name==='yard')inYard=true;if(inYard)neutralPos.push(Array.from(o.geometry.attributes.position.array));}});
  assert.equal(neutralPos.length,drawnPos.length,'same number of yard receiver meshes in drawn and neutral copies');
  for(let k=0;k<drawnPos.length;k++)assert.deepEqual(neutralPos[k],drawnPos[k],`yard receiver ${k} clipped identically in drawn and neutral bake copy`);
  const atlas2=buildAtlas(h2.root,plan2,options);
  assert.ok(atlas2.sourceRoot && atlas2.sourceRoot!==h2.root);
  let unbound=0,yardTris=0;
  y.group.traverse(o=>{
    if(!atlasMesh(o))return;
    const a=o.geometry.attributes.lmRoom,pos=o.geometry.attributes.position;
    assert.ok(a,'roof-edit yard mesh carries lmRoom');
    const tri=new THREE.Triangle(),pts=[0,1,2].map(()=>new THREE.Vector3());
    for(let i=0;i<a.count;i+=3){
      yardTris++;
      pts.forEach((v,k)=>v.fromBufferAttribute(pos,i+k).applyMatrix4(o.matrixWorld));
      if(a.getX(i)<-0.5 && tri.set(...pts).getArea()>1e-9)unbound++;
    }
  });
  assert.equal(unbound,0,'roof-only edit leaves zero unbound yard triangles');
  // Also verify a subsequent roof edit after releaseBakeSource still re-clips
  // the retained neutral yard cleanly with zero unbound triangles.
  releaseBakeSource(h2.root);
  const plan3=structuredClone(plan1);
  for(const sec of plan3.buildings[0].roof?.sections||[])sec.overhang=(sec.overhang??1.5)+6;
  const h3=buildTwin(plan3,input.kit,'low',{viewing:true});await h3.ready;
  y.group.removeFromParent();h3.groups.site.add(y.group);h3.root.updateMatrixWorld(true);
  writeWeatherOpen(y.group,h3.skyCover);
  buildAtlas(h3.root,plan3,options);
  let unbound3=0;
  y.group.traverse(o=>{
    if(!atlasMesh(o))return;
    const a=o.geometry.attributes.lmRoom,pos=o.geometry.attributes.position;
    const tri=new THREE.Triangle(),pts=[0,1,2].map(()=>new THREE.Vector3());
    for(let i=0;i<a.count;i+=3){
      pts.forEach((v,k)=>v.fromBufferAttribute(pos,i+k).applyMatrix4(o.matrixWorld));
      if(a.getX(i)<-0.5 && tri.set(...pts).getArea()>1e-9)unbound3++;
    }
  });
  assert.equal(unbound3,0,'second roof edit after releaseBakeSource leaves zero unbound yard triangles');
  console.log(`PASS roof-only edit re-clipped drawn & neutral yard identically (${drawnPos.length} meshes, ${yardTris} tris, 0 unbound)`);
  releaseBakeSource(h3.root);
}
process.exit(0);
"""


def main():
    plan = json.loads(HOUSEHOLD.read_text(encoding='utf-8'))
    kit = json.loads((ROOT / 'twin_kits' / 'modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    finish = next(k for k in (kit.get('materials') or {}) if k not in ('floor', 'interior_floor'))
    payload = {'root': ROOT.as_posix(), 'plan': plan, 'kit': kit, 'finish': finish, 'diagnose': bool(os.environ.get('DIAGNOSE'))}
    code, output = run_node(DRIVER, payload, timeout=600)
    print(output, flush=True)
    if code is None:
        return
    assert code == 0, output


if __name__ == '__main__':
    main()
