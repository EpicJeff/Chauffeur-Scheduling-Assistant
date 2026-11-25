"""Final awning regressions: authored indices, visible caps, slots and proxies."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='awning_final_')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from services.twin_model_roofs import to_sections
from services.twin_awning_migration import migrate_awnings
from services.twin_model_bridge import assemble
from test_twin_awning_migration_js import fixture
from test_twin_awning_box_js import DRIVER as BOX_DRIVER
from twin_editor_dom import PRELUDE, run_node


def legacy(native=False):
    raw = fixture()
    if not native:
        return raw
    attachments = raw['buildings'][0]['roof'].pop('extensions')
    result = assemble(raw)[0]
    result['buildings'][0]['extensions'] = attachments
    return result


def orders(area):
    """Same physical edge choices in every start corner and winding."""
    base = dict(id='aw-box', level='L1', area=area, plate=8, pitch=2,
                overhang=0, thickness_ft=.3, fascia=True,
                support=dict(kind='corbel', style='scroll', count=2),
                host=dict(wall='w0', edge=len(area)-2),
                underside=dict(kind='flat', drop_ft=.5),
                ends={str(i): 'closed' for i, p in enumerate(area)
                      if p[0] == area[(i+1) % len(area)][0]})
    base['edges'] = [dict(setting='sloped' if a[1] == b[1] == -4 else 'gable',
                          pitch=2, overhang_ft=0, gutter=a[1] == b[1] == -4)
                     for a, b in zip(area, area[1:]+area[:1])]
    segments = [frozenset(map(tuple, [a, b])) for a, b in zip(area, area[1:]+area[:1])]
    result = []
    for reverse in (False, True):
        points = list(reversed(area)) if reverse else area
        for start in range(len(area)):
            points = points[1:]+points[:1] if start else points
            indices = [segments.index(frozenset(map(tuple, [a, b])))
                       for a, b in zip(points, points[1:]+points[:1])]
            roof = dict(copy.deepcopy(base), area=copy.deepcopy(points),
                        edges=[copy.deepcopy(base['edges'][i]) for i in indices],
                        host=dict(wall='w0', edge=indices.index(len(area)-2)),
                        ends={str(j): base['ends'][str(i)] for j, i in enumerate(indices) if str(i) in base['ends']})
            result.append(dict(record=roof, sections=to_sections(roof)))
    return result


CAPTURE = r"""
registerHooks({load(url,ctx,next){
 if(url===file('static/twin/gutters.js')){const r=next(url,ctx);return {...r,source:String(r.source).replace(
  'return surface===null?ceiling:surface;', 'const top=surface===null?ceiling:surface;globalThis.__finalPostCap?.(c,top);return top;')};}
 if(!url.startsWith(file('static/twin/twin_generator.js')))return next(url,ctx);
 const source=url.endsWith('?baseline')?input.baseline:String(next(url,ctx).source);
 const anchor='  for (const g of mergeGroups) batch(';
 assert.ok(source.includes(anchor));
 return {format:'module',shortCircuit:true,source:source.replace(anchor,'  globalThis.__finalCapture?.(root);\n'+anchor)};
}});
"""
HELPERS = BOX_DRIVER[len(PRELUDE):BOX_DRIVER.index("await test('absent_fields")]
DRIVER = PRELUDE + CAPTURE + HELPERS + r"""
const {resolveSurfaceMaterial}=await import(file('static/twin/surface_material.js'));
const {houseMaterialsShelf}=await import(file('static/twin/editor/house_materials.js'));
const {bakeSource}=await import(file('static/twin/bake/source.js'));
const {_gutterPlacementStats}=await import(file('static/twin/gutters.js'));
const baseline=await import(file('static/twin/twin_generator.js')+'?baseline');
const round=x=>Math.round(x*1e5)/1e5||0;
const sorted=a=>a.sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)));
async function build(plan,module=G){let raw=[];
 globalThis.__finalCapture=root=>{root.updateMatrixWorld(true);root.traverse(m=>{
  if(!m.isMesh||m.layers.isEnabled(31))return;
  const g=m.geometry.index?m.geometry.toNonIndexed():m.geometry,p=g.attributes.position;
  raw.push({piece:m.userData.pieceId,part:m.userData.part||'',kind:m.userData.kind,
   points:Array.from({length:p.count},(_,i)=>new THREE.Vector3().fromBufferAttribute(p,i).toArray())});
  if(g!==m.geometry)g.dispose();
 });};
 const out=module.buildTwin(structuredClone(plan),kit(),'high',{viewing:true});await out.ready;
 globalThis.__finalCapture=undefined;return {out,raw};
}
function dispose(b){releaseBakeSource(b.out.root);disposeObject(b.out.root);}
function planFor(c){const p=housePlan(c.sections,{withFootprint:true});p.buildings[0].roofs=[c.record];return p;}
// Compare oriented surface areas, first moments and bounds by plane. This is
// invariant to a planar polygon's triangulation, start vertex and winding.
function surfaces(rows){const planes=new Map();
 for(const row of rows)for(let i=0;i<row.points.length;i+=3){
  const [a,b,c]=row.points.slice(i,i+3).map(p=>new THREE.Vector3(...p));
  const n=new THREE.Vector3().crossVectors(b.clone().sub(a),c.clone().sub(a)),area=n.length()/2;
  if(area<1e-8)continue;n.normalize();
  const family=row.part.replace(/support:\d+/g,'support').replace(/end:\d+/g,'end');
  const key=JSON.stringify([family,...n.toArray().map(round),round(n.dot(a))]);
  if(!planes.has(key))planes.set(key,{area:0,moment:[0,0,0],lo:[Infinity,Infinity,Infinity],hi:[-Infinity,-Infinity,-Infinity]});
  const r=planes.get(key);r.area+=area;
  for(let j=0;j<3;j++){const pts=[a,b,c].map(p=>p.getComponent(j));r.moment[j]+=area*pts.reduce((s,x)=>s+x,0)/3;
   r.lo[j]=Math.min(r.lo[j],...pts);r.hi[j]=Math.max(r.hi[j],...pts);}
 }
 return sorted([...planes].map(([k,r])=>[k,...[r.area,...r.moment,...r.lo,...r.hi].map(x=>Math.round(x*1e4)/1e4||0)]));
}
function gutters(p){const g=gutterPlacement(p),v=p=>p.map(round);
 return {runs:sorted(g.runs.flatMap(r=>r.segments.map(s=>[sorted([v(s.a),v(s.b)]),v(s.outward)]))),
  spouts:sorted(g.spouts.map(s=>[v(s.top),s.mount,s.path.map(v),v(s.outlet.at)]))};}
await test('all_eight_corner_orders_and_all_concave_orders_draw_the_same_surfaces',async()=>{
 for(const cases of input.orders){let control=null,water=null;
  for(const c of cases){const p=planFor(c),b=await build(p),parts=b.raw.filter(r=>r.piece?.startsWith('aw-box')&&/^(support:|underside|end:)/.test(r.part));
   assert.ok(parts.some(r=>r.part.startsWith('support:'))&&parts.some(r=>r.part.startsWith('underside'))&&parts.some(r=>r.part.startsWith('end:')),'fixture draws supports, ceiling and closed ends');
   const shape=surfaces(parts),rain=gutters(p);
   if(control){assert.deepEqual(shape,control,'same supports and closed box surfaces');assert.deepEqual(rain,water,'same gutters and outlets');}
   else {control=shape;water=rain;}dispose(b);
  }
 }
});
await test('canonical_and_migrated_draw_buffers_remain_byte_identical_to_branch_head',async()=>{
 for(const p of [planFor(input.orders[0][0]),...input.migrated]){
  const current=await build(p),old=await build(p,baseline);
  assert.equal(hashRoot(current.out.root),hashRoot(old.out.root),'drawn position/normal/UV/index bytes');dispose(current);dispose(old);
 }
});
await test('flat_ceiling_caps_lamps_columns_screens_and_baked_casters_at_every_drop',async()=>{
 for(const drop of [null,0,.5,2]){
  const c=structuredClone(input.orders[0][0]);
  if(drop===null)delete c.record.underside;else c.record.underside.drop_ft=drop;
  c.sections=c.sections.map(s=>{s={...s};if(drop===null)delete s.underside;else s.underside={kind:'flat',drop_ft:drop};return s;});
  const p=planFor(c),house=p.buildings[0];house.levels[0].ceiling=30;
  house.porches=[{id:'porch',polygon:rect(5,-3.8,15,-.5),floor:0,screened:true,columns:[{at:[5,-3.8],size:.5},{at:[15,-3.8],size:.5}]}];
  house.lights=[{id:'lamp',level:'L1',at:[10,-1],room:'room'}];
  const b=await build(p),ceiling=7.7-(drop??0),parts=b.raw.filter(r=>r.piece==='porch'&&['column','screen'].includes(r.part));
  assert.ok(parts.some(r=>r.part==='column')&&parts.some(r=>r.part==='screen'));
  if(drop===null){const old=await build(p,baseline);assert.equal(hashRoot(b.out.root),hashRoot(old.out.root));dispose(old);}
  else {
   assert.ok(Math.abs(b.out.roomLights[0].position.y-ceiling)<1e-6,'actual lamp mounts to ceiling');
   for(const part of parts)assert.ok(Math.abs(Math.max(...part.points.map(p=>p[1]))-ceiling)<1e-5,'drawn column/screen cap');
   const cap=b.raw.filter(r=>r.piece==='aw-box'&&r.part==='underside');
   assert.ok(cap.length&&cap.every(r=>r.points.every(p=>Math.abs(p[1]-ceiling)<.011)),'drawn ceiling caster uses same cap');
   const source=bakeSource(b.out.root),ray=new THREE.Raycaster(new THREE.Vector3(10,ceiling-1,1).multiplyScalar(.3048),new THREE.Vector3(0,1,0));
   const hits=ray.intersectObject(source,true).filter(h=>h.object.isMesh&&!h.object.layers.isEnabled(31));
   assert.ok(hits.length&&Math.abs(hits[0].point.y/.3048-ceiling)<.011,'actual bake source has the ceiling caster');
   const posts=[];globalThis.__finalPostCap=(c,z)=>posts.push(z);_gutterPlacementStats.clearCache();gutters(p);globalThis.__finalPostCap=undefined;
   assert.ok(posts.length&&posts.every(z=>Math.abs(z-ceiling)<1e-6),'gutter post eligibility uses the flat ceiling');
  }
  dispose(b);
 }
});
await test('every_pick_proxy_retains_plain_roof_attributes',async()=>{
 for(const c of [input.orders[0][0],input.orders[1][0]]){const b=await build(planFor(c));
  const plain=b.out.pickObjects.get('b:main'),attrs=Object.keys(plain.geometry.attributes).sort();assert.ok(attrs.includes('normal'));
  for(const proxy of b.out.pickObjects.values())assert.deepEqual(Object.keys(proxy.geometry.attributes).sort(),attrs,'shared pick attribute set');
  dispose(b);
 }
});
await test('migrated_and_handmade_roofs_follow_later_building_finish_changes',()=>{
 for(const p of input.migrated){const b=p.buildings[0],r=b.roof.sections.find(r=>r.id==='shade');
  assert.equal(r.material,undefined,'ordinary migration leaves inheritance live');
  const handmade={...r};delete handmade.material;
  for(const color of ['#123456','#abcdef']){b.materials={roof:{id:'shingle',color}};
   const resolve=r=>resolveSurfaceMaterial(p,{role:'roof',building:b,level:r.level,parents:[r.material,r.materials?.roof]}).ref;
   assert.deepEqual(resolve(r),{id:'shingle',color});assert.deepEqual(resolve(r),resolve(handmade));}
 }
});
await test('house_materials_has_editable_and_clearable_ceiling_underneath_row',async()=>{
 const host=document.createElement('div'),plan=housePlan(),b=plan.buildings[0],sent=[];document.body.append(host);
 b.materials={underside:{id:'roof',color:'#123456'}};
 houseMaterialsShelf(host,b,{getPlan:()=>plan,library:{selected:()=>({id:'painted_trim',kind:'material'}),onSelect:()=>()=>{},reveal:async()=>{}},
  canEdit:true,op:async o=>sent.push(o),settingsRequest:async()=>({})});
 const row=host.querySelector('[data-library-slot="Ceiling underneath"]');assert.ok(row);
 click(row.querySelector('[data-slot-use]'));await new Promise(r=>setTimeout(r,0));
 assert.deepEqual(sent[0],{op:'set_material',building:'b',target:{building:'b',role:'underside'},material:{id:'painted_trim'}});
 const clear=row.querySelector('[data-slot-clear]');assert.ok(clear);click(clear);await new Promise(r=>setTimeout(r,0));
 assert.equal(sent.at(-1).material,null);
});
finish();
"""


class Final(unittest.TestCase):
    def test_migration_is_idempotent_and_idless_legacy_ids_are_stable(self):
        for native in (False, True):
            raw = legacy(native)
            b = raw['buildings'][0]
            (b['extensions'] if native else b['roof']['extensions'])[0].pop('id')
            first, _ = migrate_awnings(raw)
            self.assertEqual(migrate_awnings(raw)[0], first, 'two loads of an undone legacy record')
            self.assertEqual(migrate_awnings(first), (first, []), 'already migrated is a no-op')
            rows = first['buildings'][0].get('roofs', first['buildings'][0].get('roof', {}).get('sections'))
            self.assertTrue(next(r['id'] for r in rows if r.get('support')))

    def test_concave_overhang_maps_only_to_a_boundary_the_section_touches(self):
        area = [[0,0],[8,0],[8,4],[4,4],[4,8],[0,8]]
        for index in range(len(area)):
            r = dict(id='L', area=area, plate=8, pitch=0, overhang=0,
                     edges=[dict(setting='sloped', pitch=0) for _ in area])
            r['edges'][index]['overhang_ft'] = 1.25
            for s in to_sections(r):
                self.assertEqual(len(s['edges']), 4)
                for j, side in enumerate(('y0','x1','y1','x0')):
                    self.assertEqual(s['edges'][j].get('overhang_ft', 0),
                                     1.25 if s['plane_edges'][side] == index else 0)

    def test_runtime(self):
        baseline = subprocess.check_output(['git', 'show', 'HEAD:chauffeur/static/twin/twin_generator.js'], cwd=ROOT, text=True, encoding='utf-8')
        migrated = [migrate_awnings(legacy())[0]]
        code, output = run_node(DRIVER, dict(root=ROOT.as_posix(), baseline=baseline,
            orders=[orders([[5,-4],[15,-4],[15,0],[5,0]]),
                    orders([[5,-4],[15,-4],[15,-2],[12,-2],[12,0],[5,0]])], migrated=migrated), timeout=240)
        print(output)
        self.assertEqual(code, 0, output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
