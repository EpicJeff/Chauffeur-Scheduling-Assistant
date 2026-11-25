"""House defaults exercised through the generator, reuse cache and bake atlas."""
import sys
from test_twin_untouched_house_js import COMMON, ROOT, run_node

DRIVER = COMMON + r"""
const S=await import(file('static/twin/surface_kinds.js'));
const originals=out=>[...new Set([...out.pieces].filter(([k])=>k.startsWith('a:')).flatMap(([,v])=>v))].filter(o=>o.isMesh);
const sites=(out,kind)=>[...new Set([...out.pieces].filter(([k])=>k.startsWith('a:')).flatMap(([key,rows])=>rows.filter(o=>{
 if(!o.isMesh)return false;
 const m=o.material.name,id=key.slice(2),d={kind:['window','slider','bifold','garage','door'].includes(id)?'opening':
 ['gable','hip'].includes(id)?'roof':id==='porch'?'porch':id==='stairs'?'stair':
 ['kitchen','vanity','shower'].includes(id)?'fixture':'other',pieceId:id};
 if(['trim','base'].includes(kind))return m===kind;
 if(kind==='fascia')return d.kind==='roof'&&m==='trim';
 if(kind==='casing')return d.kind==='opening'&&m==='trim';
 if(kind==='column')return d.kind==='porch'&&m==='trim';
 if(kind==='soffit')return d.kind==='roof'&&m==='porch_ceiling';
 if(['window_frame','door','pane'].includes(kind))return d.kind==='opening'&&m===(kind==='pane'?'glass':kind);
 if(kind==='screen')return d.kind==='porch'&&m==='screen';
 if(kind.startsWith('stair_'))return d.kind==='stair'&&m===(kind==='stair_tread'?'floor':'porch_ceiling');
 if(['cabinet','counter'].includes(kind))return d.kind==='fixture'&&d.pieceId==='vanity'&&m===kind;
 if(kind==='shower_tile'||kind==='shower_glass')return d.kind==='fixture'&&d.pieceId==='shower'&&m===(kind==='shower_tile'?'ceramic':'glass');
 return false;
})))];
// Columns have child piece ids. Aggregate the porch and its post registries
// before comparing an entire porch across a material-induced bucket split.
const porchPieces=out=>[...new Set([...out.pieces].filter(([key])=>key==='a:porch' || out.pieceBounds.get(key)?.data.parentPieceId==='porch').flatMap(([,objects])=>objects))].filter(o=>o.isMesh);
// A changed material can split a merge bucket. Compare triangles in world
// space, including the original UVs, independently of that batching.
const triangles=(objects,keep=()=>true)=>objects.flatMap(o=>{
 const g=o.geometry,p=g.attributes.position,uv=g.attributes.uv,idx=g.index?.array||Array.from({length:p.count},(_,i)=>i),rows=[];
 for(let i=0;i<idx.length;i+=3){
  const local=Array.from(idx.slice(i,i+3),j=>new THREE.Vector3().fromBufferAttribute(p,j));
  if(!keep(local))continue;
  rows.push(local.map((v,k)=>[...v.applyMatrix4(o.matrixWorld).toArray(),uv.getX(idx[i+k]),uv.getY(idx[i+k])].map(n=>+n.toFixed(6))));
 }
 return rows;
}).map(row=>JSON.stringify(row)).sort();
for(const kind of ['trim','fascia','casing','window_frame','pane','door','column','screen','soffit','base',
 'stair_tread','stair_rail','cabinet','counter','shower_tile','shower_glass']){
 await test('each_building_kind_default_reaches_its_meshes:'+kind,async()=>{
  const p=fixture(),before=await build(p),expected=sites(before,kind);
  assert.ok(expected.length,kind+' baseline sites exist');p.buildings[0].materials[kind]={id:'choice'};
  const after=await build(p),actual=originals(after).filter(o=>o.material.userData.materialId==='choice');
  if(kind==='column'){
   // The old trim batch includes foundation beams/posts below the porch floor.
   // Only the above-floor columns belong to the column kind.
   const floor=p.buildings[0].porches[0].floor;
   const columns=vs=>vs.every(v=>v.y>=floor-1e-6),supports=vs=>vs.every(v=>v.y<floor-1e-6);
   assert.ok(triangles(expected,columns).length);assert.ok(triangles(expected,supports).length);
   assert.deepEqual(triangles(actual),triangles(expected,columns),'column default reaches only columns');
   const unchanged=piece(after,'porch').filter(o=>o.material.name==='trim'&&o.material.userData.materialId!=='choice');
   assert.deepEqual(triangles(unchanged),triangles(expected,supports),'porch supports keep their trim');
   assert.deepEqual(triangles(porchPieces(after)),triangles(porchPieces(before)),'all porch positions and UVs unchanged');
  }else assert.deepEqual(triangles(actual),triangles(expected),kind+' exact geometry at the intended sites');
 });
}
await test('fallback_role_still_drives_unset_kinds',async()=>{
 for(const [role,kinds] of [['porch_ceiling',['soffit','stair_rail']],['trim',['fascia','casing','column']],['floor',['stair_tread']]]){
  const p=fixture(),before=await build(p),expected=triangles(kinds.flatMap(k=>sites(before,k)));
  assert.ok(expected.length);p.buildings[0].materials[role]={id:'choice'};const out=await build(p);
  const counts=new Map();for(const triangle of triangles(originals(out).filter(o=>o.material.userData.materialId==='choice')))
   counts.set(triangle,(counts.get(triangle)||0)+1);
  for(const triangle of expected){assert.ok(counts.get(triangle)>0,role+' reaches each fallback triangle');counts.set(triangle,counts.get(triangle)-1);}
 }
});
await test('opaque_pane_is_named_pane_and_joins_the_atlas',async()=>{
 const p=fixture(),plain=await build(p),key=A.buildAtlas(plain.root,p,layout).key;
 for(const [id,name,receives] of [['choice','pane',true],['blend','glass',false]]){
  p.buildings[0].materials.pane={id};const out=await build(p),panes=rendered(out).filter(o=>o.material.userData.materialId===id);
  assert.ok(panes.length);for(const o of panes){assert.equal(o.material.name,name);assert.equal(A.atlasMesh(o),receives);}
  if(receives)assert.notEqual(A.buildAtlas(out.root,p,layout).key,key);
 }
});
await test('garage_with_windows_takes_pane_and_frame',async()=>{
 const p=fixture();p.buildings[0].materials.pane={id:'blend'};p.buildings[0].materials.window_frame={id:'choice'};
 p.buildings[0].openings.find(o=>o.kind==='garage').lites='top';
 const out=await build(p),own=piece(out,'garage');assert.ok(own.some(o=>o.material.name==='glass'&&o.material.userData.materialId==='blend'));
 assert.ok(own.some(o=>o.material.name==='window_frame'&&o.material.userData.materialId==='choice'));
});
await test('kit_aliases_keep_the_receiving_role_with_and_without_tint',async()=>{
 for(const color of [null,'#234567'])for(const id of ['siding','lattice']){
  const p=fixture(),k=kit();k.materials.lattice.pattern='lattice';
  const slot={id,...(color?{color}:{})};p.buildings[0].materials.pane=slot;p.buildings[0].materials.shower_glass=slot;
  const out=await build(p,k),name=id==='lattice'?'glass':'pane';
  for(const objects of [piece(out,'window'),piece(out,'shower')]){
   const panes=objects.filter(o=>o.material.name===name);assert.ok(panes.length,id+' keeps pane receiving role');
   for(const o of panes){assert.equal(A.atlasMesh(o),id!=='lattice');if(color)assert.equal(o.material.color.getHexString(),color.slice(1));}
  }
  assert.ok(originals(out).some(o=>o.material.name==='siding'),'wall role survives the alias');
 }
});
await test('fixture_colour_beats_house_default',async()=>{
 const p=fixture();p.buildings[0].materials.cabinet={id:'choice'};p.buildings[0].materials.counter={id:'choice'};
 const out=await build(p),own=piece(out,'kitchen');
 assert.equal(own.find(o=>o.material.name==='cabinet').material.color.getHexString(),'112233');
 assert.equal(own.find(o=>o.material.name==='counter').material.color.getHexString(),'8899aa');
 assert.ok(own.every(o=>!o.material.userData.materialId));
 assert.ok(piece(out,'vanity').every(o=>o.material.userData.materialId==='choice'));
});
await test('a_default_changes_the_reuse_key_only_for_its_building',async()=>{
 const p=fixture(),k=kit(),keys=()=>p.buildings.map(b=>JSON.stringify(G.buildingKeyParts(p,b,k,'low'))),before=keys();
 p.buildings[0].materials.pane={id:'choice'};let after=keys();assert.notEqual(after[0],before[0]);assert.equal(after[1],before[1]);
 k.manifest.choice.revision++;const revised=keys();assert.notEqual(revised[0],after[0]);assert.equal(revised[1],before[1]);
 const old=await build(p,k);k.manifest.choice.revision++;const next=G.buildTwin(p,k,'low',{editableLevel:'a:L1',previous:old});await next.ready;
 assert.deepEqual(next.buildingsRebuilt,['a']);assert.deepEqual(next.buildingsReused,['b']);
 assert.notEqual(piece(next,'window')[0].material,piece(old,'window')[0].material);
 delete p.buildings[0].materials.pane;assert.deepEqual(keys(),before);
});
await test('one_material_instance_per_default',async()=>{
 const p=fixture(),before=await build(p);p.buildings[0].materials.pane={id:'blend'};
 const out=await build(p),panes=piece(out,'window').concat(piece(out,'slider'),piece(out,'bifold'),piece(out,'garage'),piece(out,'door'))
  .filter(o=>o.material.userData.materialId==='blend');
 // A default garage is solid; the four remaining glazed openings share glass.
 assert.ok(panes.length>=4);assert.equal(new Set(panes.map(o=>o.material.uuid)).size,1);
 assert.equal(rendered(out).length,rendered(before).length);
});
await test('level_default_precedes_building_and_item_slot_precedes_both',async()=>{
 assert.equal(typeof S.resolveSlot,'function');
 const b={materials:{pane:{id:'choice'}}},l={materials:{pane:{id:'blend'}}};
 assert.deepEqual(S.resolveSlot('pane',{building:b,level:l}),{id:'blend'});
 assert.deepEqual(S.resolveSlot('pane',{building:b}),{id:'choice'});
 assert.equal(S.resolveSlot('pane',{}),null);
 const p=fixture();p.buildings[0].materials.pane={id:'blend'};p.buildings[0].openings[0].materials={pane:{id:'choice'}};
 const ids=meshes(await build(p)).map(o=>o.material.userData.materialId);
 assert.equal(ids.filter(id=>id==='choice').length,1);assert.ok(ids.includes('blend'));
});
await test('new_level_default_invalidates_material_cache',async()=>{
 const p=fixture(),k=kit();p.buildings[0].levels[0].materials={pane:{id:'choice'}};
 const old=await build(p,k);assert.ok(piece(old,'window').some(o=>o.material.userData.materialId==='choice'));
 k.manifest.choice.revision++;const next=G.buildTwin(p,k,'low',{editableLevel:'a:L1',previous:old});await next.ready;
 assert.deepEqual(next.buildingsRebuilt,['a']);assert.deepEqual(next.buildingsReused,['b']);
 const pane=o=>piece(o,'window').find(o=>o.material.userData.materialId==='choice').material;
 assert.notEqual(pane(next),pane(old));
});
await test('roof_section_wins_over_house_default',async()=>{
 const p=fixture();p.buildings[0].materials.roof={id:'choice'};p.buildings[0].roof.sections[0].material={id:'blend'};
 const out=await build(p);assert.ok(piece(out,'gable').some(o=>o.material.userData.materialId==='blend'));
 assert.ok(piece(out,'hip').some(o=>o.material.userData.materialId==='choice'));
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'editable': True}, timeout=180)
    print(output)
    sys.exit(code or 0)
