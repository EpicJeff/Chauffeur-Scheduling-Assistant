"""Task 7: support finishes and explicit, reversible patio post conversion."""
import copy
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.pop('HA_BASE_URL', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from services import twin_model, twin_model_roofs, twin_model_ops as ops
from services import twin_model_bridge as bridge, twin_store as store, twin_edit, storage
from services.twin_model_supports import normalize_support
from services.twin_surface_kinds import KINDS, ITEM_PARTS
from twin_editor_dom import PRELUDE, run_node


def patio():
    """Invented pool-house patio, two painted 8-inch columns, one shed."""
    area = [[0, 0], [16, 0], [16, 8], [0, 8]]
    b = dict(id='pool-cottage', name='Demo pool cottage', position=[0, 0], base=0,
             levels=[dict(id='L1', name='Patio', elevation=0, ceiling=10)],
             joints=[dict(id=f'j{i}', level='L1', at=p) for i, p in enumerate(area)],
             walls=[dict(id=f'w{i}', level='L1', joints=[f'j{i}', f'j{(i+1)%4}'],
                         exterior=True, kind='separator', height=10, thickness=.5) for i in range(4)],
             rooms=[dict(id='patio', name='Pool patio', kind='porch', level='L1', polygon=area, joints=[f'j{i}' for i in range(4)])],
             roofs=[twin_model_roofs.from_section(dict(id='shade', level='L1', rect=[0, 0, 16, 8],
                 kind='shed', low_side='y0', plate=10, pitch=3, overhang=1))],
             porches_detail=[dict(id='patio', level='L1', floor=0, polygon=area, screened=False,
                 materials={'column': {'id': 'painted_trim', 'color': '#84715e', 'uv': {'u': .2, 'v': .4, 'rot': 90}}},
                 columns=[dict(at=[1, 1], size=2/3, shape='square'), dict(at=[15, 1], size=2/3, shape='square')])],
             openings=[], anchors=[], items=[], dormers=[], extensions=[], stairs=[], proposals=[], flags=[])
    return twin_model.normalize(dict(schema=twin_model.SCHEMA, units='ft', materials={}, buildings=[b], site={}))[0]


MOVE = dict(op='move_posts_to_roof', building='pool-cottage', porch='patio', roof='shade')


def eligibility_cases():
    """One table, with exact reasons, exercised through server and card code."""
    cases = []
    def add(name, reason=None, *, roof=None, porch=None, columns=None):
        value = patio(); b = value['buildings'][0]
        if roof: b['roofs'][0].update(copy.deepcopy(roof))
        if porch: b['porches_detail'][0].update(copy.deepcopy(porch))
        if columns is not None:
            b['porches_detail'][0]['columns'] = [dict(at=at, size=2/3) for at in columns]
        cases.append(dict(name=name, model=value, reason=reason))
    outside = 'A post would be outside the roof.'
    add('ordinary patio')
    add('review probe', outside, roof={'area': [[0,0],[8,0],[8,8],[0,8]]})
    add('under uniform overhang', columns=[[1,1],[16.8,1]])
    add('within tolerance', columns=[[1,1],[17.04,1]])
    add('on tolerance', columns=[[1,1],[17.05,1]])
    add('beyond tolerance', outside, columns=[[1,1],[17.06,1]])
    add('corner Euclidean tolerance', outside, columns=[[1,1],[17.04,9.04]])
    edges = copy.deepcopy(patio()['buildings'][0]['roofs'][0]['edges'])
    edges[1]['overhang_ft'] = 0
    add('edge disables uniform overhang', outside, roof={'edges':edges}, columns=[[1,1],[16.2,1]])
    edges[1]['overhang_ft'] = 2
    add('edge extends beyond uniform overhang', roof={'overhang':0,'edges':edges}, columns=[[1,1],[17.5,1]])
    from services.twin_model_supports import frame_point
    frame = {'origin':[8,4], 'angle': math.pi/4}
    transform = lambda at: frame_point({'roof_frame':frame}, at)
    add('rotated frame covered', roof={'roof_frame':frame}, columns=[transform([1,1]),transform([16.8,1])])
    add('rotated frame outside', outside, roof={'roof_frame':frame}, columns=[transform([1,1]),transform([17.1,1])])
    add('no columns', 'This porch has no columns to move.', columns=[])
    for state in ('ghost', 'proposal'):
        add('roof '+state, 'Choose a settled roof; ghost and proposal roofs cannot receive posts.', roof={'state':state})
        add('porch '+state, 'Choose a settled porch; ghost and proposal porches cannot move posts.', porch={'state':state})
    add('no overlap', 'No roof overlaps this porch on its floor.', roof={'area':[[30,0],[46,0],[46,8],[30,8]]})
    add('other floor', 'No roof overlaps this porch on its floor.', roof={'level':'upper'})
    add('already supported at zero count', 'This roof already has supports.', roof={'support':{'kind':'post','count':0}})
    edges = copy.deepcopy(patio()['buildings'][0]['roofs'][0]['edges']); edges[2]['setting'] = 'sloped'
    add('walled gable', 'Choose a shed roof; this walled roof is not a shed.', roof={'edges':edges})
    add('too many columns', 'The roof needs at most 40 columns of the same size, from 0.05 to 3 feet.', columns=[[1,1]]*41)
    add('unequal sizes', 'The roof needs at most 40 columns of the same size, from 0.05 to 3 feet.')
    cases[-1]['model']['buildings'][0]['porches_detail'][0]['columns'][1]['size'] = .5
    for size in (.05, 3, .04, 3.01):
        add(f'width {size}', None if .05 <= size <= 3 else 'The roof needs at most 40 columns of the same size, from 0.05 to 3 feet.')
        for column in cases[-1]['model']['buildings'][0]['porches_detail'][0]['columns']: column['size'] = size
    add('concave porch', porch={'polygon':[[0,0],[16,0],[16,4],[8,4],[8,8],[0,8]]})
    return cases


class AwningMaterials(unittest.TestCase):
    def test_underside_material_round_trip_for_hand_and_agent(self):
        for actor in ('person', 'agent'):
            model = patio()
            model, _ = ops.apply(model, dict(op='set_roof_support', building=MOVE['building'], id='shade', support={'kind':'brace'}, underside={'kind':'flat','drop_ft':1}), actor)
            ref = {'id':'painted_trim','color':'#aabbcc','uv':{'u':.2,'v':.4,'rot':90}}
            command = dict(op='set_material', building=MOVE['building'], target={'roof':'shade','part':'underside'}, material=ref)
            after, _ = ops.apply(model, command, actor)
            rebuilt = bridge.assemble(bridge.flatten(after), after)[0]
            self.assertEqual(rebuilt['buildings'][0]['roofs'][0]['materials']['underside'], ref)
            walls, _ = ops.apply(after, dict(op='set_roof_support', building=MOVE['building'], id='shade', support={'kind':'walls'}), actor)
            self.assertEqual(walls['buildings'][0]['roofs'][0]['materials']['underside'], ref)
            cleared, _ = ops.apply(after, dict(command, material=None), actor)
            self.assertNotIn('materials', cleared['buildings'][0]['roofs'][0])

    def test_underside_resolver_picker_and_all_card_roof_records(self):
        code, output = run_node(PRELUDE + r"""
const {undersideMaterialSurface}=await import(file('static/twin/underside_material.js'));
const {resolveSurfaceMaterial}=await import(file('static/twin/surface_material.js'));
const {materialLines}=await import(file('static/twin/editor/library.js'));
const {roofHostChoices}=await import(file('static/twin/editor/roof_support_shelf.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const plan=input.plan,b=plan.buildings[0],roof=b.roofs[0],sent=[];
roof.support={kind:'brace',count:2};roof.underside={kind:'flat',drop_ft:1};
const ref=()=>resolveSurfaceMaterial(plan,undersideMaterialSurface(plan,b,roof)).ref;
assert.deepEqual(ref(),{id:'porch_ceiling'});
plan.materials.soffit={id:'painted_trim',color:'#123456'};assert.deepEqual(ref(),plan.materials.soffit);
b.materials={soffit:{id:'painted_trim',color:'#654321'}};assert.deepEqual(ref(),b.materials.soffit);
b.materials.underside={id:'standing_seam'};assert.deepEqual(ref(),b.materials.underside);
roof.materials={underside:{id:'painted_trim',color:'#abcdef',uv:{u:.2,v:.4,rot:90}}};assert.deepEqual(ref(),roof.materials.underside);
const row=()=>materialLines({kind:'roof',piece:roof,building:b},plan,{}).find(r=>r.target.part==='underside');
assert.equal(row().label,'Ceiling underneath');assert.deepEqual(row().resolved,ref());
const cards=createCards({getPlan:()=>plan,canEdit:()=>true,getLabel:()=> 'Awning',op:async o=>sent.push(o),edit:async()=>{},select(){},ask(){},
 library:{selected:()=>({id:'painted_trim',kind:'material'}),onSelect:()=>()=>{},reveal:async()=>{}}});
cards.draw({pieceId:roof.id,buildingId:b.id,kind:'roof'});
const picker=document.getElementById('piece-card').querySelector('[data-library-slot="Ceiling underneath"]');assert.ok(picker);
click(picker.querySelector('[data-slot-use]'));await new Promise(r=>setTimeout(r,0));
assert.deepEqual(sent,[{op:'set_material',building:b.id,target:{roof:roof.id,part:'underside'},material:{id:'painted_trim'}}]);
delete roof.underside;cards.draw({pieceId:roof.id,buildingId:b.id,kind:'roof'});assert.equal(row(),undefined);
assert.equal(document.getElementById('piece-card').querySelector('[data-library-slot="Ceiling underneath"]'),null);
const original=structuredClone(roof);
for(const kind of ['flat','shed','gable','hip'])for(const shape of ['area','rect','concave','clockwise','rotated']) {
 Object.keys(roof).forEach(k=>delete roof[k]);Object.assign(roof,structuredClone(original),{kind,low_side:'y0',ridge:'x',pitch:kind==='flat'?0:3});
 if(shape==='rect'){roof.rect=[0,0,16,8];delete roof.area;delete roof.edges;}
 if(shape==='concave')roof.area=[[0,0],[16,0],[16,4],[8,4],[8,8],[0,8]];
 if(shape==='clockwise')roof.area.reverse();
 if(shape==='rotated')roof.roof_frame={origin:[8,4],angle:.3};
 assert.doesNotThrow(()=>roofHostChoices(roof,b),kind+' '+shape);
 assert.doesNotThrow(()=>cards.draw({pieceId:roof.id,buildingId:b.id,kind:'roof'}),kind+' '+shape);
}
cards.dispose();
console.log('ceiling resolver, real picker, 20 selectable roof forms');
""", dict(root=ROOT.as_posix(), plan=bridge.flatten(patio())))
        self.assertEqual(code, 0, output)

    def test_shared_server_card_eligibility_table(self):
        cases = eligibility_cases()
        for case in cases:
            for actor in ('person', 'agent'):
                before = copy.deepcopy(case['model'])
                with self.subTest(name=case['name'], actor=actor):
                    if case['reason']:
                        with self.assertRaises(ops.Refused) as caught:
                            ops.apply(case['model'], MOVE, actor)
                        self.assertEqual(str(caught.exception), case['reason'])
                    else:
                        result, _ = ops.apply(case['model'], MOVE, actor)
                        self.assertEqual(result['buildings'][0]['porches_detail'][0]['columns'], [])
                    self.assertEqual(case['model'], before)
                    batch = {'op':'batch', 'ops':[MOVE]}
                    if case['reason']:
                        with self.assertRaises(ops.Refused) as caught:
                            ops.apply(case['model'],batch,actor)
                        self.assertIn(case['reason'],str(caught.exception))
                    else:
                        result,_=ops.apply(case['model'],batch,actor)
                        self.assertEqual(result['buildings'][0]['porches_detail'][0]['columns'],[])
        payload = [dict(name=c['name'], reason=c['reason'], building=bridge.flatten(c['model'])['buildings'][0]) for c in cases]
        code, output = run_node(PRELUDE + r"""
const {postRoofChoices, postRoofReason} = await import(file('static/twin/editor/posts_action.js'));
for (const c of input.cases) {
  const b=c.building, porch=b.porches.find(p=>p.id==='patio'), roof=b.roofs.find(r=>r.id==='shade');
  assert.equal(postRoofReason(b,porch,roof), c.reason, c.name);
  assert.equal(postRoofChoices(b,'patio').length, c.reason ? 0 : 1, c.name);
}
console.log('SHARED_ELIGIBILITY_CASES',input.cases.length);
""", {'root':ROOT.as_posix(), 'cases':payload})
        print(output); self.assertEqual(code, 0, output)

    def test_support_rejects_invalid_tint(self):
        for target in ({'roof':'shade','part':'support'}, {'building':MOVE['building'],'role':'support'}):
            m=patio(); before=copy.deepcopy(m)
            with self.assertRaisesRegex(ops.Refused, 'six-digit hex'):
                ops.apply(m,dict(op='set_material',building=MOVE['building'],target=target,material={'color':'#zzz'}))
            self.assertEqual(m,before)
            after,_=ops.apply(m,dict(op='set_material',building=MOVE['building'],target=target,material={'color':'#aAbB00'}))
            self.assertNotEqual(after,m)

    def test_roof_override_survives_when_porch_has_no_column_material(self):
        for materials in ({'support': {'id':'painted_trim','color':'#111111'}}, {}, None):
            m=patio(); b=m['buildings'][0]; b['porches_detail'][0].pop('materials')
            if materials is not None: b['roofs'][0]['materials']=copy.deepcopy(materials)
            after,_=ops.apply(m,MOVE)
            roof=after['buildings'][0]['roofs'][0]
            if materials: self.assertEqual(roof['materials'],materials)
            else: self.assertNotIn('materials',roof)

    def test_move_posts_to_roof_keeps_the_floor(self):
        before = patio()
        after, words = ops.apply(before, MOVE)
        b, old = after['buildings'][0], before['buildings'][0]
        self.assertEqual(b['rooms'], old['rooms'])
        detail = copy.deepcopy(old['porches_detail'][0]); detail['columns'] = []
        # Provenance is allowed on the two deliberately edited records only.
        actual = copy.deepcopy(b['porches_detail'][0]); actual.pop('src', None)
        detail.pop('src', None)
        self.assertEqual(actual, detail)
        support = b['roofs'][0]['support']
        self.assertEqual(support['kind'], 'post')
        self.assertEqual(support['count'], 2)
        self.assertEqual(support['at'], {'0': [1, 1], '1': [15, 1]})
        self.assertEqual(support['size_ft'], 2/3)
        self.assertEqual(b['roofs'][0]['materials']['support'], old['porches_detail'][0]['materials']['column'])
        self.assertIn('floor', words.lower())
        self.assertEqual(before, patio(), 'input is immutable and conversion is never automatic')
        flat = bridge.flatten(after)
        rebuilt = bridge.assemble(flat, after)[0]
        self.assertEqual(rebuilt['buildings'][0]['roofs'][0]['materials']['support'], b['roofs'][0]['materials']['support'])
        self.assertEqual(rebuilt['buildings'][0]['porches_detail'][0]['columns'], [])

    def test_refusal_reasons_are_atomic_for_person_and_agent(self):
        cases = []
        m = patio(); m['buildings'][0]['porches_detail'][0]['columns'] = []; cases.append((m, 'no columns'))
        m = patio(); m['buildings'][0]['roofs'][0]['area'] = [[30, 0], [46, 0], [46, 8], [30, 8]]; cases.append((m, 'overlaps'))
        m = patio(); m['buildings'][0]['roofs'][0]['edges'][2]['setting'] = 'sloped'; cases.append((m, 'shed'))
        m = patio(); m['buildings'][0]['roofs'][0]['support'] = {'kind': 'post', 'count': 0}; cases.append((m, 'already has supports'))
        m = patio(); m['buildings'][0]['roofs'][0]['level'] = 'upper'; cases.append((m, 'overlaps'))
        for value, reason in cases:
            original = copy.deepcopy(value)
            for actor in ('person', 'agent'):
                with self.subTest(reason=reason, actor=actor), self.assertRaisesRegex(ops.Refused, reason):
                    ops.apply(value, MOVE, actor)
                self.assertEqual(value, original)

    def test_set_material_support_and_brace_default(self):
        m = patio()
        m, _ = ops.apply(m, dict(op='set_material', building=MOVE['building'], target={'roof': 'shade', 'part': 'support'}, material={'id': 'painted_trim'}))
        self.assertEqual(m['buildings'][0]['roofs'][0]['materials'], {'support': {'id': 'painted_trim'}})
        flat = bridge.flatten(m)
        self.assertEqual(flat['buildings'][0]['roof']['sections'][0]['materials']['support'], {'id': 'painted_trim'})
        m, _ = ops.apply(m, dict(op='set_material', building=MOVE['building'], target={'roof': 'shade', 'part': 'support'}, material=None))
        self.assertNotIn('materials', m['buildings'][0]['roofs'][0])
        r = {'support': {'kind': 'brace'}}; normalize_support(r, [])
        self.assertEqual(r['support']['size_ft'], .45)

    def test_agent_and_inherited_column_material(self):
        m = patio(); b = m['buildings'][0]
        b['porches_detail'][0].pop('materials')
        b['materials'] = {'column': {'id': 'painted_trim', 'color': '#556677'}}
        after, _ = ops.apply(m, MOVE, actor='agent')
        self.assertEqual(after['buildings'][0]['porches_detail'][0]['columns'], [])
        self.assertEqual(after['buildings'][0]['materials'], b['materials'])
        text = (ROOT / 'services/agent_tools_v2.py').read_text(encoding='utf-8')
        self.assertIn('move_posts_to_roof (building, porch, roof)', text)
        self.assertIn('{roof, part:support}', text)

    def test_undo_puts_the_posts_back(self):
        settings = {}
        with tempfile.TemporaryDirectory(prefix='posts_history_') as directory, patch.object(store, 'DATA_DIR', directory), \
             patch.object(storage, 'get_settings', side_effect=lambda: copy.deepcopy(settings)), \
             patch.object(storage, 'patch_settings', side_effect=lambda values: settings.update(copy.deepcopy(values))):
            store._invalidate_reads()
            first = store._append_round(store._state(), patio(), 'load')
            before = copy.deepcopy(store.current_model())
            rounds = len(store._state()['rounds'])
            twin_edit.save(MOVE, None)
            self.assertEqual(len(store._state()['rounds']), rounds + 1)
            store._invalidate_reads()
            self.assertEqual(store.current_model()['buildings'][0]['porches_detail'][0]['columns'], [])
            store.revert(first); store._invalidate_reads()
            self.assertEqual(store.current_model(), before)

    def test_support_material_inherits_trim_then_overrides(self):
        self.run_js('materials')

    def test_the_action_is_offered_only_for_a_porch_under_a_supported_or_shed_roof(self):
        self.run_js('action')

    def run_js(self, mode):
        code, output = run_node(DRIVER, dict(root=ROOT.as_posix(), mode=mode, plan=bridge.flatten(patio()), kinds=KINDS, parts=ITEM_PARTS), timeout=180)
        print(output)
        self.assertEqual(code, 0, output)


DRIVER = PRELUDE + r"""
const { supportMaterialSurface } = await import(file('static/twin/support_material.js'));
const { resolveSurfaceMaterial } = await import(file('static/twin/surface_material.js'));
const { materialLines } = await import(file('static/twin/editor/library.js'));
const { KINDS, ITEM_PARTS } = await import(file('static/twin/surface_kinds.js'));
assert.deepEqual(KINDS, input.kinds); assert.deepEqual(ITEM_PARTS, input.parts);
assert.ok(KINDS.some(r => r.kind === 'support' && r.item === 'roof'));
const plan = input.plan, b = plan.buildings[0], roof = b.roof.sections[0];
if (input.mode === 'materials') {
  roof.edges = structuredClone(b.roofs[0].edges);
  b.roofs[0] = roof;
  const ref = () => resolveSurfaceMaterial(plan, supportMaterialSurface(plan, b, roof)).ref;
  roof.support = {kind:'bracket',count:2};
  plan.materials.trim = {id:'painted_trim', color:'#887766', uv:{u:.2,v:.4,rot:90}};
  assert.deepEqual(ref(), plan.materials.trim);
  b.materials = {trim:{id:'painted_trim',color:'#abcdef'}};
  assert.deepEqual(ref(), b.materials.trim);
  roof.materials = {support:{id:'standing_seam',color:'#112233'}};
  assert.deepEqual(ref(), roof.materials.support);
  delete roof.materials;
  roof.support.kind = 'post'; b.materials.column = {id:'painted_trim',color:'#556677'};
  b.materials.support = {id:'standing_seam', color:'#ee0000'};
  assert.deepEqual(ref(), b.materials.column,'posts follow columns even with building support defaults');
  roof.materials = {support:{id:'standing_seam'}}; assert.deepEqual(ref(), roof.materials.support);
  const row = materialLines({kind:'roof',piece:roof,building:b}, plan, {}).find(r => r.target.part === 'support');
  assert.ok(row); assert.equal(row.label,'Supports'); assert.deepEqual(row.target,{roof:'shade',part:'support'});
  assert.deepEqual(row.resolved,roof.materials.support);
  const { createCards } = await import(file('static/twin/editor/cards.js'));
  const sent=[];
  const cards=createCards({getPlan:()=>plan,canEdit:()=>true,getLabel:()=> 'Awning',op:async o=>sent.push(o),edit:async()=>{},select(){},ask(){},
    library:{selected:()=>({id:'painted_trim',kind:'material'}),onSelect:()=>()=>{},reveal:async()=>{}}});
  cards.draw({pieceId:'shade',buildingId:b.id,kind:'roof'});
  const receiving=document.getElementById('piece-card').querySelector('[data-library-slot="Supports"]');
  assert.ok(receiving,'real roof card mounts shared picker');
  click(receiving.querySelector('[data-slot-use]')); await new Promise(r=>setTimeout(r,0));
  assert.deepEqual(sent,[{op:'set_material',building:b.id,target:{roof:'shade',part:'support'},material:{id:'painted_trim'}}]);
  cards.dispose();
  delete b.materials.support;
  const { buildTwin } = await import(file('static/twin/twin_generator.js'));
  const { disposeObject } = await import(file('static/twin/twin_library.js'));
  const { releaseBakeSource } = await import(file('static/twin/bake/source.js'));
  // Bracket awnings outside the patio floor cutter; same level, shared trim.
  b.porches = []; b.rooms = []; b.walls = []; b.roofs = [];
  roof.rect = [0,-5,8,-1]; roof.area = [[0,-5],[8,-5],[8,-1],[0,-1]];
  roof.support = {kind:'bracket',count:2}; roof.fascia=false; delete roof.materials;
  roof.id='aw1'; roof.roof='aw1';
  b.roof.sections = [roof, {...structuredClone(roof),id:'aw2',roof:'aw2',rect:[10,-5,18,-1],area:[[10,-5],[18,-5],[18,-1],[10,-1]]}];
  const kit = {materials:Object.fromEntries(['siding','roof','trim','base','floor','interior_wall','porch_ceiling','window_frame','door','glass'].map(r=>[r,{color:'#999999',roughness:.8}]))};
  const measure = async () => {
    const t=performance.now(), out=buildTwin(structuredClone(plan),kit,'high',{viewing:true}); await out.ready;
    const supports=[], meshes=[];
    out.root.traverse(o=>{if(o.isMesh && !o.layers.isEnabled(31)) {meshes.push(o); if(o.userData.snapRanges?.some(r=>r.part?.startsWith('support:')))supports.push(o);}});
    const triangles=meshes.reduce((n,o)=>n+(o.geometry.index?.count??o.geometry.attributes.position.count)/3,0);
    const result={draws:meshes.length,triangles,ms:performance.now()-t,supports:supports.map(o=>({material:o.material, ranges:o.userData.snapRanges}))};
    // Material fingerprints remain available after disposal.
    result.colors=result.supports.map(o=>o.material.color.getHexString());
    releaseBakeSource(out.root); disposeObject(out.root); return result;
  };
  const before=await measure();
  assert.equal(before.supports.length,1,'two same-material awnings share a support draw');
  b.roof.sections[0].materials={support:{id:'painted_trim',color:'#ff0000'}};
  const after=await measure();
  assert.equal(after.triangles,before.triangles); assert.equal(after.draws,before.draws+1);
  assert.equal(after.supports.length,2); assert.ok(after.colors.includes('ff0000'));
  assert.ok(after.colors.some(c=>c!=='ff0000'),'second awning keeps inherited trim');
  console.log('MATERIAL_COST',JSON.stringify({before:{draws:before.draws,triangles:before.triangles,ms:before.ms},override:{draws:after.draws,triangles:after.triangles,ms:after.ms}}));
} else {
  b.roofs = [];
  const { postRoofChoices, drawPostsAction } = await import(file('static/twin/editor/posts_action.js'));
  const choices=()=>postRoofChoices(b,'patio');
  assert.equal(choices().length,1);
  const host=document.createElement('div'); let sent=[], confirms=[], allowed=true, lifecycle;
  window.promptConfirm=async (...args)=>{confirms.push(args);return allowed;};
  const button=drawPostsAction(host,{kind:'room',piece:b.rooms[0],building:b},{getPlan:()=>plan,canEdit:()=>true,queue:fn=>fn(),op:async o=>sent.push(o),report:e=>{throw e;},ownSlot:r=>{lifecycle=r;}});
  assert.ok(button); assert.equal(button.textContent,'Move posts to the roof'); assert.equal(sent.length,0);
  allowed=false; await button.click(); await new Promise(r=>setTimeout(r,0)); assert.equal(sent.length,0);
  allowed=true; await button.click(); await new Promise(r=>setTimeout(r,0));
  assert.deepEqual(sent,[{op:'move_posts_to_roof',building:b.id,porch:'patio',roof:'shade'}]);
  const words=confirms[0].join(' '); for(const phrase of ['posts','floor stays','walls and gables']) assert.ok(words.includes(phrase),words);
  const { createCards } = await import(file('static/twin/editor/cards.js'));
  const cards=createCards({getPlan:()=>plan,canEdit:()=>true,getLabel:()=> 'Patio',op:async()=>{},edit:async()=>{},select(){},ask(){}});
  cards.draw({pieceId:'patio',buildingId:b.id,kind:'room'});
  assert.ok([...document.getElementById('piece-card').querySelectorAll('button')].some(n=>n.textContent==='Move posts to the roof'),'real porch card mounts action');
  cards.dispose();
  roof.support={kind:'post',count:0}; assert.equal(choices().length,0);
  lifecycle.refresh(); assert.equal(host.querySelector('button'),null,'poll removes ineligible action');
  delete roof.support; lifecycle.refresh(); assert.ok(host.querySelector('button'));
  window.promptConfirm=async()=>{roof.support={kind:'post',count:0};return true;};
  click(host.querySelector('button')); await new Promise(r=>setTimeout(r,0)); assert.equal(sent.length,1,'recheck after confirmation');
  delete roof.support;
  roof.kind='gable'; assert.equal(choices().length,0); roof.kind='shed';
  roof.rect=[30,0,46,8]; assert.equal(choices().length,0); roof.rect=[0,0,16,8];
  b.porches[0].columns=[]; assert.equal(choices().length,0);
  assert.equal(drawPostsAction(document.createElement('div'),{kind:'room',piece:b.rooms[0],building:b},{getPlan:()=>plan,canEdit:()=>true}),null);
}
"""


if __name__ == '__main__':
    unittest.main()
