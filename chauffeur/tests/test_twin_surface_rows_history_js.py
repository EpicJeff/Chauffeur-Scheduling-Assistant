"""Real household: UI-generated new-row payloads round-trip through HTTP undo."""
import copy
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DRIVER = PRELUDE + r"""
globalThis.fetch=async()=>new Response(JSON.stringify({materials:[],items:[]}));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {materialLines}=await import(file('static/twin/editor/library.js'));
const {siteMaterialSlots}=await import(file('static/twin/editor/site_shape_shelf.js'));
const {houseMaterialsShelf}=await import(file('static/twin/editor/house_materials.js'));
const library={selected:()=>({kind:'material',id:'wood_floor',name:'Oak'}),onSelect:()=>()=>{},reveal:async()=>{}};
const sent=[],owned=[],plan=input.plan,host=document.getElementById('piece-card');
const send=async op=>{
 sent.push(op);
 if(op.op==='update_pool_feature'){
  const feature=plan.site.pool.features.find(f=>f.id===op.id);feature.materials={...feature.materials,...op.materials};
  for(const key of Object.keys(feature.materials))if(!feature.materials[key])delete feature.materials[key];
 }
};
const cards=createCards({getPlan:()=>plan,getKit:()=>input.kit,getLabel:()=>'',canEdit:()=>true,select(){},edit:async()=>{},library,
 op:send,haLink:{draw(){},state:()=>({available:false})}});
const settle=async()=>{await new Promise(r=>setTimeout(r,0));await cards.queue(async()=>{});};
const exercise=async(getRow,target,base)=>{
 const count=sent.length;
 await click(getRow().querySelector('[data-slot-use]'));await settle();
 assert.deepEqual(sent.at(-1),{...base,...(target.materials?{materials:{[target.materials]:{id:'wood_floor'}}}:{target:target.target,material:{id:'wood_floor'}})});
 const tint=getRow().querySelector('input[type="color"]');tint.value='#123456';await fire(tint,'change');await settle();
 const u=getRow().querySelector('[data-slot-u]');u.value='1.05';await fire(u,'change');await settle();
 const rot=getRow().querySelector('[data-slot-rotation]');rot.value='270';await fire(rot,'change');await settle();
 const expected={id:'wood_floor',color:'#123456',uv:{u:.05,v:0,rot:270}};
 assert.deepEqual(sent.at(-1),{...base,...(target.materials?{materials:{[target.materials]:expected}}:{target:target.target,material:expected})});
 await click(getRow().querySelector('[data-slot-offset-reset]'));await settle();
 await click(getRow().querySelector('[data-slot-clear]'));await settle();
 assert.equal(sent.length-count,6,'one history step per control');
};
await test('new_rows_post_exact_task1_payloads_on_real_household',async()=>{
 let planes=0,features=0,roles=0;
 for(const b of plan.buildings)for(const section of b.roof?.sections||[]){
  const lines=materialLines({kind:'roof',piece:section,building:b},plan,input.kit).filter(line=>line.target.plane!==undefined);
  if(!lines.length)continue;cards.draw({pieceId:section.id,buildingId:b.id});
  for(const line of lines){await exercise(()=>host.querySelector(`[data-library-slot="${line.label}"]`),{target:line.target},{op:'set_material',building:b.id});planes++;}
 }
 for(const feature of plan.site.pool.features.filter(f=>['ledge','steps'].includes(f.kind))){
  cards.draw({pieceId:feature.id});
  for(const [part,label] of siteMaterialSlots(feature.kind,feature)){
   await exercise(()=>host.querySelector(`[data-library-slot="${label}"]`),{materials:part},{op:'update_pool_feature',id:feature.id});features++;
  }
 }
 const b=plan.buildings[0],shelf=document.createElement('div');
 houseMaterialsShelf(shelf,b,{getPlan:()=>plan,getKit:()=>input.kit,library,ownSlot:r=>owned.push(r),canEdit:()=>true,
  op:async op=>sent.push(op),settingsRequest:async()=>({lawn:{grass_type:'cool'}})});
 for(const [role,label] of [['paving','Paving'],['mulch','Mulch'],['patio_concrete','Patio concrete'],['fence','Fence'],
  ['pool_interior','Pool interior'],['pool_waterline','Pool waterline'],['pool_coping','Pool coping']]){
  await exercise(()=>shelf.querySelector(`[data-library-slot="${label}"]`),{target:{site:true,role}},{op:'set_material',building:b.id});roles++;
 }
 assert.ok(planes>0&&features>=4&&roles===7);cards.dispose();owned.forEach(r=>r.dispose());
 console.log('PAYLOADS '+JSON.stringify(sent));console.log('  UI census '+JSON.stringify({planes,features,roles,operations:sent.length}));
});finish();
"""

if __name__ == '__main__':
    os.environ.pop('HA_BASE_URL', None)
    with tempfile.TemporaryDirectory(prefix='chauffeur_surface_row_history_', ignore_cleanup_errors=True) as scratch:
        os.environ['CHAUFFEUR_DATA_DIR'] = scratch
        from services import twin_store, twin_library
        from test_twin_model_ops_more import _client, _people, _enforced
        logging.getLogger('httpx').setLevel(logging.WARNING)
        twin_store.push_round(json.loads((ROOT/'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8')), 'build')
        with _enforced():
            client, headers = _client(), _people()['parent']
            # The real fixture has ledges; add valid steps so both new row families execute.
            pool = twin_store.current_model()['site']['pool']
            for kind in ('ledge','steps'):
                if not any(f['kind'] == kind for f in pool.get('features', [])):
                    response = client.post('/api/house/editor/op', headers=headers, json={'op':{
                        'op':'add_pool_feature', 'kind':kind, 'polygon':copy.deepcopy(pool['polygon'])}})
                    assert response.status_code == 200, response.text
            plan = twin_store.current()
            code, output = run_node(DRIVER, {'root':ROOT.as_posix(), 'plan':plan, 'kit':twin_library.kit('modern_farmhouse')}, timeout=180)
            print('\n'.join(line for line in output.splitlines() if not line.startswith('PAYLOADS ')))
            assert code == 0, output
            payloads = json.loads(next(line[9:] for line in output.splitlines() if line.startswith('PAYLOADS ')))
            for operation in payloads:
                before_id, before = twin_store.current_id(), twin_store.current_model()
                response = client.post('/api/house/editor/op', headers=headers, json={'op':operation})
                assert response.status_code == 200, (operation, response.text)
                after_id, after = twin_store.current_id(), twin_store.current_model()
                if before_id == after_id:
                    continue  # Choosing/clearing an already identical ref is intentionally a no-op.
                response = client.post('/api/house/twin/revert', headers=headers, json={'round':before_id})
                assert response.status_code == 200, response.text
                assert twin_store.current_model() == before, operation
                response = client.post('/api/house/twin/revert', headers=headers, json={'round':after_id})
                assert response.status_code == 200, response.text
                assert twin_store.current_model() == after, operation
            print(f'PASS {len(payloads)} UI-generated operations accepted; undo/redo restores connected household')
