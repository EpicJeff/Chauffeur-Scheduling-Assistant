"""Task 2: run Move to actions, both card builders and submenu keyboard paths.

Run from chauffeur/: python tests/test_twin_move_to_action_js.py
"""
from pathlib import Path
import json
import logging
import os
import sys
import tempfile

from twin_editor_dom import PRELUDE, run_node
from test_twin_move_to_js import DRIVER as OPS_DRIVER

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DRIVER = OPS_DRIVER.split("await test(", 1)[0] + r"""
const {moveToAction, drawMoveToButton} = await import(file('static/twin/editor/move_to_action.js'));
const {createContextMenu} = await import(file('static/twin/editor/context_menu.js'));
const {createSelection} = await import(file('static/twin/editor/selection.js'));
const {createVisibility} = await import(file('static/twin/editor/visibility.js'));
const {createCards} = await import(file('static/twin/editor/cards.js'));
const {drawSelectionCard} = await import(file('static/twin/editor/selection_card.js'));
globalThis.fetch=async()=>new Response(JSON.stringify({materials:[],items:[]}));
function rig() {
 const plan=fixture(), selectionStore=createSelection(), visibility=createVisibility({storage:null});
 let editable=true;const calls=[], alerts=[], slots=[];
 window.showGlobalAlert=text=>alerts.push(text);selectionStore.set([chair]);
 const options={getPlan:()=>plan,selectionStore,canEdit:()=>editable,
  applyBatch:async(ops,opts)=>calls.push({ops,...opts}),
  chooseDestination:async key=>{calls.push({destination:key});selectionStore.clear();},
  queue:work=>work(),report:e=>{throw e;},ownSlot:row=>slots.push(row),visibility};
 return {plan,selectionStore,visibility,calls,alerts,options,slots,setEditable:v=>editable=v};
}
await test('action_one_batch_then_destination_then_selection_preserves_visibility',async()=>{
 const r=rig();r.visibility.hide('chair');r.visibility.lock('chair');
 const a=moveToAction({...r.options,refs:[chair]});assert.equal(a.label,'Move to');
 assert.deepEqual(a.children.map(t=>t.label),['Site','House · Ground floor','Pool house · Ground floor']);
 await a.children[0].run();
 assert.equal(r.calls.length,2);assert.equal(r.calls[0].label,'Move to Site');
 assert.deepEqual(r.calls[0].ops.map(o=>o.op),['delete','add_site_item']);
 assert.deepEqual(r.calls[1],{destination:'site'});
 assert.deepEqual(r.selectionStore.members(),[{kind:'furniture',pieceId:'chair'}]);
 assert.ok(r.visibility.isHidden('chair'));assert.ok(r.visibility.isLocked('chair'));
});
await test('named_refusal_is_atomic_and_failure_never_switches_or_selects',async()=>{
 const r=rig();r.plan.buildings[0].items[0].name='Reading chair';
 r.plan.buildings[1].rooms=[];
 await moveToAction({...r.options,refs:[chair]}).children.at(-1).run();
 assert.equal(r.calls.length,0);assert.match(r.alerts[0],/Reading chair: No room under it on Ground floor\./);
 assert.deepEqual(r.selectionStore.members(),[chair]);
 r.plan.buildings[0].items[0].host={ceiling:'upper-room',u:.2,v:.4};
 await moveToAction({...r.options,refs:[chair]}).children[0].run();
 assert.match(r.alerts[1],/Reading chair: Ceiling pieces cannot go to the site\./);
 r.options.applyBatch=async()=>{throw new Error('save failed');};
 r.plan.buildings[0].items[0].host={floor:'upper-room',u:.2,v:.4};
 await assert.rejects(moveToAction({...r.options,refs:[chair]}).children[0].run(),/save failed/);
 assert.equal(r.calls.length,0);assert.deepEqual(r.selectionStore.members(),[chair]);
});
await test('disabled_reasons_readonly_and_nonmovable_only_selection',async()=>{
 const r=rig();r.plan.buildings[0].items[0].host={wall:'wall'};
 let a=moveToAction({...r.options,refs:[chair]});
 assert.ok(a.disabled);assert.equal(a.reason,'Wall and roof pieces stay on their wall or roof.');
 assert.ok(a.children.every(t=>t.disabled&&t.reason===a.reason));
 for(const kind of ['planting','device','opening','light_fixture'])assert.equal(moveToAction({...r.options,refs:[ref(kind,'x')]}),null);
 r.plan.buildings[0].items[0].host={floor:'upper-room',u:.2,v:.4};
 a=moveToAction({...r.options,refs:[chair]});r.setEditable(false);await a.children[0].run();assert.equal(r.calls.length,0);
 assert.ok(moveToAction({...r.options,refs:[chair]}).disabled);
});
await test('mixed_refusal_names_only_blocker_and_never_sends_partial_batch',async()=>{
 const r=rig();r.plan.site.planting[0].name='Oak tree';
 await moveToAction({...r.options,refs:[chair,ref('planting','tree')]}).children[0].run();
 assert.equal(r.calls.length,0);assert.match(r.alerts[0],/Oak tree: Plants stay on the site\./);
 assert.ok(!r.alerts[0].includes('chair:'));
 r.options.getLabel=()=> 'Front oak';
 await moveToAction({...r.options,refs:[chair,ref('planting','tree')]}).children[0].run();
 assert.match(r.alerts[1],/Front oak: Plants stay on the site\./);
});
const menuHost=()=>document.getElementById('editor-context-menu');
const menuButton=text=>[...menuHost().querySelectorAll('button')].find(b=>b.textContent===text);
await test('submenu_click_keyboard_back_dismissal_and_accessible_reason',async()=>{
 const lifecycle=new AbortController();let ran=0;
 const menu=createContextMenu({signal:lifecycle.signal,items:()=>[{label:'Duplicate',run(){}},
  {label:'Move to',children:[{label:'Site',run:()=>++ran},{label:'No room',disabled:true,reason:'The blocker.'}]}]});
 const opener=document.createElement('button');document.body.append(opener);opener.focus();
 menu.open([20,30],{});const move=menuButton('Move to');assert.equal(move.getAttribute('aria-haspopup'),'menu');
 move.focus();await fire(window,'keydown',{key:'ArrowRight'});
 assert.equal(menuHost().getAttribute('aria-label'),'Move to');assert.equal(document.activeElement.textContent,'Site');
 const disabled=menuButton('No room');assert.ok(disabled.disabled);assert.equal(disabled.title,'The blocker.');
 assert.equal(disabled.getAttribute('aria-description'),'The blocker.');
 await fire(window,'keydown',{key:'ArrowLeft'});assert.equal(document.activeElement.textContent,'Move to');
 await click(menuButton('Move to'));await fire(window,'keydown',{key:'End'});assert.equal(document.activeElement.textContent,'Site');
 await click(menuButton('Site'));assert.equal(ran,1);assert.ok(menuHost().hidden);
 opener.focus();menu.open([20,30],{});await click(menuButton('Move to'));await click(menuButton('Back'));assert.ok(menuButton('Duplicate'));
 await fire(window,'keydown',{key:'Escape'});assert.ok(menuHost().hidden);assert.equal(document.activeElement,opener);
 lifecycle.abort();
});
await test('shared_button_and_both_properties_paths_open_same_targets',async()=>{
 const r=rig(),host=document.getElementById('piece-card');
 const options={...r.options,refs:[chair],getKit:()=>({}),getLabel:()=>'',select:next=>r.selectionStore.set(next?[next]:[]),
  op:async()=>{},edit:async()=>{},getSelection:()=>({}),onSaved:()=>{},removeSelection:()=>{}};
 const cards=createCards(options);cards.draw(chair);
 let button=[...host.querySelectorAll('button')].find(b=>b.textContent==='Move to');assert.ok(button,'single card');
 await click(button);assert.ok(menuButton('Site'));assert.equal(menuHost().getAttribute('aria-label'),'Move to');
 await click(menuButton('Site'));await cards.queue(async()=>{});assert.equal(r.calls[0].label,'Move to Site');cards.dispose();
 host.replaceChildren();r.selectionStore.set([chair]);
 drawSelectionCard(host,{...options,prepared:{fields:[],summary:[],sharedSlots:[],materials:[],structure:'test'}});
 button=[...host.querySelectorAll('button')].find(b=>b.textContent==='Move to');assert.ok(button,'set card');
 await click(button);assert.ok(menuButton('Site'));
 r.plan.buildings[0].items[0].host={roof:'roof'};host.replaceChildren();
 const row=drawMoveToButton(host,{...options,getRefs:()=>[chair]});assert.ok(row);
 button=host.querySelector('button');assert.ok(button.disabled);assert.match(button.getAttribute('aria-description'),/wall or roof/);
 r.slots.forEach(row=>row.dispose());
});
finish();
"""

SCENE = r"""
await test('production_context_move_next_to_duplicate_and_disabled_card_survives_refresh',async()=>{
 const ed=await mountEditor();
 try {
  const b=ed.plan.buildings[0],p=b.items.find(p=>p.id==='move-chair'),ref={kind:'item',pieceId:p.id,buildingId:b.id};
  const buttons=()=>[...document.getElementById('editor-context-menu').querySelectorAll('button')];
  const button=text=>buttons().find(b=>b.textContent===text);
  ed.tools.selectionStore.set([ref]);ed.tools.chooseFloor(`${b.id}:${b.levels[0].id}`);
  ed.visibility.hide(p.id);ed.visibility.lock(p.id);
  ed.tools.openContextMenu([20,30],{kind:'item',id:p.id,building:b.id});
  assert.equal(buttons().indexOf(button('Move to')),buttons().indexOf(button('Duplicate'))+1);
  await click(button('Move to'));await click(button('Site'));await new Promise(r=>setTimeout(r,10));
  assert.equal(ed.ops.length,1);assert.equal(ed.ops[0].options.label,'Move to Site');
  assert.deepEqual(ed.ops[0].operation.ops.map(o=>o.op),['delete','add_site_item']);
  assert.equal(ed.view.state.view,'ext');assert.deepEqual(ed.tools.selectionStore.members(),[{kind:'furniture',pieceId:p.id}]);
  assert.ok(ed.visibility.isHidden(p.id));assert.ok(ed.visibility.isLocked(p.id));
  p.host={wall:b.walls[0].id,at:2,z:3,side:'left'};ed.tools.selectionStore.set([ref]);ed.tools.refreshCard();
  const move=[...ed.dom.pieceCard.querySelectorAll('button')].find(b=>b.textContent==='Move to');assert.ok(move.disabled);
  ed.tools.refreshCard();assert.ok(move.disabled,'poll must not re-enable wall pieces');
  ed.tools.openContextMenu([20,30],{kind:'item',id:p.id,building:b.id});assert.ok(button('Move to').disabled);
  assert.match(button('Move to').getAttribute('aria-description'),/wall or roof/);
 } finally {ed.dispose();}
});
await test('production_floor_choice_keeps_moved_refs_instead_of_floor_selection',async()=>{
 const p=makeHousehold(),b=p.buildings[0],item=b.items.find(p=>p.id==='move-chair'),room=b.rooms.find(r=>r.id===item.host.floor);
 b.levels.push({id:'move-upper',name:'Move upper',elevation:12,ceiling:8});b.rooms.push({...structuredClone(room),id:'move-upper-room',level:'move-upper'});
 const ed=await mountEditor(p);
 try {
  const ref={kind:'item',pieceId:item.id,buildingId:b.id};ed.tools.selectionStore.set([ref]);
  ed.tools.openContextMenu([20,30],{kind:'item',id:item.id,building:b.id});
  const btn=text=>[...document.getElementById('editor-context-menu').querySelectorAll('button')].find(b=>b.textContent===text);
  await click(btn('Move to'));await click(btn(`${b.name} · Move upper`));await new Promise(r=>setTimeout(r,10));
  assert.equal(ed.ops.length,1);assert.equal(ed.ops[0].operation.ops[0].op,'move_hosted');
  assert.equal(ed.view.state.view,`${b.id}:move-upper`);assert.deepEqual(ed.tools.selectionStore.members(),[ref]);
 } finally {ed.dispose();}
});
finish();
"""

SERVER = PRELUDE + r"""
const {moveToAction}=await import(file('static/twin/editor/move_to_action.js'));
const p=structuredClone(input.plan),b=p.buildings[0],piece=b.items.find(p=>p.id==='move-chair'),saves=[];
const options={getPlan:()=>p,refs:[{kind:'item',pieceId:piece.id,buildingId:b.id}],canEdit:()=>true,
 applyBatch:async ops=>saves.push({op:'batch',ops}),selectionStore:{set(){}},chooseDestination(){}};
await moveToAction(options).children.find(t=>t.label==='Site').run();
const added=saves[0].ops[1];b.items=b.items.filter(p=>p.id!==piece.id);
p.site.furniture.push({...added});
await moveToAction({...options,refs:[{kind:'furniture',pieceId:piece.id}]}).children.find(t=>t.label===`${b.name} · ${b.levels.find(l=>l.id===b.rooms.find(r=>r.id===piece.host.floor).level).name}`).run();
console.log('PAYLOADS '+JSON.stringify(saves));
"""


def integration():
    os.environ.pop('HA_BASE_URL', None)
    with tempfile.TemporaryDirectory(prefix='chauffeur_move_to_action_', ignore_cleanup_errors=True) as scratch:
        os.environ['CHAUFFEUR_DATA_DIR'] = scratch
        from services import twin_store, twin_library
        from test_twin_model_ops_more import _client, _people, _enforced
        logging.getLogger('httpx').setLevel(logging.WARNING)
        plan = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf8'))
        b = plan['buildings'][0]
        b.setdefault('items', []).append({'id': 'move-chair', 'name': 'Reading chair',
            'asset': 'mid_century_lounge_chair', 'host': {'floor': b['rooms'][0]['id'], 'u': .5, 'v': .5},
            'rotation': 17, 'scale': 1.1, 'tint': '#7a6040', 'casts_shadow': False,
            'object_kind': 'decor', 'elevation': .2, 'state': 'settled'})
        twin_store.push_round(plan, 'build')
        payload = {'root': ROOT.as_posix(), 'flat': twin_store.current(), 'plan': twin_store.current(),
                   'model': twin_store.current_model(), 'kit': twin_library.kit('modern_farmhouse'),
                   'objectSchema': json.loads((ROOT / 'static/twin/object_schema.json').read_text(encoding='utf8'))}
        code, output = run_node(SERVER, payload)
        assert code == 0, output
        batches = json.loads(next(line[9:] for line in output.splitlines() if line.startswith('PAYLOADS ')))
        assert len(batches) == 2
        with _enforced():
            client, headers = _client(), _people()['parent']
            for batch in batches:
                before, round_id, count = twin_store.current_model(), twin_store.current_id(), len(twin_store.rounds())
                response = client.post('/api/house/editor/op', headers=headers, json={'op': batch})
                assert response.status_code == 200, response.text
                assert len(twin_store.rounds()) == count + 1, 'one batch must add exactly one undo step'
                after = twin_store.current_model()
                item = next(p for p in before['buildings'][0]['items'] if p['id'] == 'move-chair') if batch is batches[0] else next(p for p in before['site']['furniture'] if p['id'] == 'move-chair')
                moved = next(p for p in after['site']['furniture'] if p['id'] == 'move-chair') if batch is batches[0] else next(p for p in after['buildings'][0]['items'] if p['id'] == 'move-chair')
                for key in ('id', 'name', 'asset', 'scale', 'tint', 'casts_shadow', 'object_kind', 'elevation'):
                    assert moved[key] == item[key], key
                response = client.post('/api/house/twin/revert', headers=headers, json={'round': round_id})
                assert response.status_code == 200 and twin_store.current_model() == before, 'undo restores original list, id, host and every property'
                if batch is batches[0]:
                    response = client.post('/api/house/editor/op', headers=headers, json={'op': batch})
                    assert response.status_code == 200, response.text
            print('PASS UI-generated cross-list moves in both directions: one round, properties carried, exact model restored by undo')
        from test_twin_selection_js import DRIVER as SCENE_DRIVER
        scene_driver = SCENE_DRIVER.rsplit('finish();', 1)[0].replace('await test(', 'await skipPriorScenario(')
        code, output = run_node('const skipPriorScenario=async()=>{};\n' + scene_driver + SCENE, payload, timeout=180)
        print(output)
        assert code == 0, output


def main():
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    assert code == 0, output
    integration()


if __name__ == '__main__':
    main()
