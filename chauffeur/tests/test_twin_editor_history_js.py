"""Lost-edit regression: real editor boot, mutations, history, API and cards.

Only transport, the renderer and unrelated panels are doubles. No browser.
"""
from pathlib import Path
import re
import sys
from twin_live_node_rig import run

ROOT = Path(__file__).resolve().parents[1]

STUBS = r"""
import {createCards} from 'CARDS_URL';
export const mountTwin=async()=>globalThis.editorView;
export const runDirector=async()=>{};
export const createPanel=()=>({message(){},readOnly(){},events(){},reset(){},dispose(){}});
export function createSceneTools(options){
 const cards=createCards({...options,getLabel:()=> 'this piece',getSelection:()=>({}),ask(){},select});
 let selection=null;
 function select(value){selection=value;cards.draw(value);}
 return {select,selected:()=>selection,selection:()=>({}),refresh(){cards.draw(selection);},refreshCard(){cards.draw(selection);},
  drawFloors(){},delegate(){},dragging:()=>false,refreshLink:async()=>{},handles:()=>[]};
}
export const createDraw=()=>({cancel(){}});
export const createLotTools=()=>({dragging:()=>false,handles:()=>[]});
export const createTerrainTools=()=>({refresh(){},cancel(){}});
export const streetView=()=>null,streetSegment=()=>null;
export const createRoofTools=()=>({cancel(){},addDormer(){}});
export const createLibrary=()=>({refresh(){}});
export const createFlags=()=>({refresh(){}});
export const createPauses=()=>({sync(){},current:()=>null,dismissed:()=>false,dismiss(){}});
export const applyRegistration=(_,p)=>p,invertRegistration=(_,p)=>p;
export const createTimeline=()=>({sync(){},preview:()=>null});
export const createPlace=()=>({sync(){},isOpen:()=>false});
export const createDevicePlacement=()=>({refresh(){},draw(){},stop(){},cancel(){}});
export const createBuildGhosts=()=>({clear(){},sync(){},settle(){},count:()=>0});
export const createStatusChip=()=>({update(){}});
export const createSteps=()=>({render(){}});
export const createChecks=()=>({sync(){},dismiss(){}});
export const mountHouses=options=>(globalThis.houseOptions=options,{sync(){}});
"""

DRIVER = r"""
let passed=0;const ok=text=>{passed++;console.log('  ok '+text);};
try {
 for(const id of config.ids){const node=document.createElement('div');node.id=id;document.body.append(node);}
 const alerts=[];window.showGlobalAlert=text=>alerts.push(text);window.promptConfirm=async()=>true;
 location.search='?test=1';
 const {createHistory,CHANGED_SINCE}=await import(file('static/twin/editor/history.js'));
 const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
 const until=async predicate=>{for(let i=0;i<200&&!predicate();i++)await wait(5);assert.ok(predicate(),'operation completes within the test deadline');};

 // The shared owner must serialize work itself, including work outside cards.
 let round='a',entered=[],editable=true;
 const firstGate=deferred(),abort=new AbortController();
 const h=createHistory({getRound:()=>round,getBuild:()=>null,canEdit:()=>editable,refresh:async()=>{},signal:abort.signal});
 const first=h.perform(async()=>{entered.push(round);await firstGate.promise;round='b';return 1;});
 const second=h.perform(async()=>{entered.push(round);round='c';return 2;});
 // Observe rejection immediately too, so the pre-fix failure is diagnostic.
 const both=Promise.all([first,second]);both.catch(()=>{});
 await wait(10);assert.deepEqual(entered,['a']);firstGate.resolve();assert.deepEqual(await both,[1,2]);
 assert.deepEqual(entered,['a','b']);abort.abort();
 ok('back-to-back mutations wait and the second runs against the first completed round');

 // Boot the actual editor with the actual history/API/cards. The fake server
 // stores complete rounds and honours op, legacy edit and revert requests.
 let plan={buildings:[{id:'b',name:'House',levels:[{id:'L1',elevation:0,ceiling:10}],rooms:[],walls:[],roofs:[],
  solar_zones:[{id:'z',roof:'roof',plane:[0,0,10],rect:[28,28,32,34]}],
  openings:[{id:'door',kind:'door',width:3,sill:0,head:7,at:4,state:'ghost'}]}],site:{}};
 let seq=0,rounds=[{id:'r0'}],saved=new Map([['r0',structuredClone(plan)]]),holdResponse=null,holdRender=null;
 const writes=[],reverts=[];let sheetReads=0,failSheets=false;
 const response=(status,body)=>({ok:status<400,status,text:async()=>JSON.stringify(body)});
 const state=()=>({plan:structuredClone(plan),model:structuredClone(plan),rounds:structuredClone(rounds),cost:{},build:null});
 const record=()=>{const id='r'+(++seq);saved.set(id,structuredClone(plan));rounds.push({id});return id;};
 const piece=id=>plan.buildings[0].solar_zones.concat(plan.buildings[0].openings).find(p=>p.id===id);
 globalThis.fetch=window.fetch=async(url,init={})=>{
  const path=String(url).split('api/house/')[1];
  if(path==='editor/sheets'){sheetReads++;if(failSheets)throw Error('Sheets temporarily unavailable');return response(200,{sources:[],page_roles:[],place:{buildings:[{id:'b'}]}});}
  if(path==='twin/kit/modern_farmhouse')return response(200,{});
  if(path==='editor/state')return response(200,state());
  if(path==='twin/revert'){
   const {round}=JSON.parse(init.body);reverts.push(round);plan=structuredClone(saved.get(round));return response(200,{round:record()});
  }
  const body=JSON.parse(init.body),op=body.op||body.edit;writes.push({path,op:structuredClone(op)});
  if(holdResponse){const gate=holdResponse;holdResponse=null;await gate.promise;}
  if(op.op==='refuse')return response(400,{error:'That opening no longer exists. Reload the house and choose another.'});
  if(op.op==='update_solar_zone')Object.assign(piece(op.id),op);
  else if(op.op==='set_solar_source')plan.solar_source_roof=op.roof;
  else if(op.op==='resize_opening')piece(op.id).width=op.width;
  else if(op.op==='accept')for(const id of op.pieces)piece(id).state='settled';
  else if(op.op==='set')piece(op.id||op.piece)[op.field]=op.value;
  else assert.fail('unexpected mutation '+JSON.stringify(op));
  record();return response(200,{...state(),words:'Saved the change.',summary:'Saved the change.'});
 };
 globalThis.editorView={scene:{},plan:null,state:{time:'now',unlit:false},
  setTime(time){this.state.time=time;},setUnlit(on){this.state.unlit=on;},dispose(){},rebuild:async p=>{
  editorView.plan=p;if(holdRender){const gate=holdRender;holdRender=null;await gate.promise;}
 }};
 const stubs='data:text/javascript,'+encodeURIComponent(config.stubs.replace('CARDS_URL',file('static/twin/editor/cards.js')));
 registerHooks({resolve(spec,ctx,next){
  if(ctx.parentURL===file('static/twin/editor/editor.js')&&!['./api.js','./history.js','./lighting.js'].includes(spec))return {url:stubs,shortCircuit:true};
  return next(spec,ctx);
 }});
 const {boot}=await import(file('static/twin/editor/editor.js'));await boot();assert.ok(window.__editor.ready);
 assert.equal(editorView.state.time,'day');assert.equal(editorView.state.unlit,false);
 const hooks=window.__twinEditor,card=document.getElementById('piece-card');
 const button=text=>card.querySelectorAll('button').find(b=>b.textContent===text);
 const current=()=>rounds.at(-1).id;

 const zoneResize=hooks.op({op:'update_solar_zone',building:'b',id:'z',rect:[28,28,36,34]});
 // Hold the rebuild after the real op response updates the card, exactly as
 // Chromium did: the count is new while perform() is still awaiting render.
 // Set the gate synchronously before the request continuation runs.
 const renderGate=deferred();holdRender=renderGate;
 window.__editor.clickPiece('z','b');await until(()=>card.textContent.includes('2 panels'));
 const beforeSource=writes.length;await press(button('Solar ribbon starts here'));
 assert.equal(writes.length,beforeSource);assert.equal(plan.solar_source_roof,undefined);
 renderGate.resolve();await zoneResize;await until(()=>editorView.plan.solar_source_roof==='roof');
 assert.deepEqual(piece('z').rect,[28,28,36,34]);assert.equal(writes.at(-1).op.op,'set_solar_source');
 assert.deepEqual(alerts,[]);
 ok('actual solar card source click survives the resize save and delayed rebuild');

 await until(()=>!document.getElementById('rail-undo').disabled);
 await press(document.getElementById('rail-undo'));await until(()=>reverts.length===1&&!document.getElementById('rail-redo').disabled);
 assert.equal(plan.solar_source_roof,undefined);assert.deepEqual(piece('z').rect,[28,28,36,34]);
 await press(document.getElementById('rail-redo'));await until(()=>reverts.length===2&&!document.getElementById('rail-undo').disabled);
 assert.equal(plan.solar_source_roof,'roof');assert.deepEqual(piece('z').rect,[28,28,36,34]);
 ok('queued edits keep distinct fresh-round undo and redo steps');

 window.__editor.clickPiece('door','b');
 const responseGate=deferred();holdResponse=responseGate;
 const resize=hooks.op({op:'resize_opening',building:'b',id:'door',width:5});
 await until(()=>writes.at(-1).op.op==='resize_opening');
 const beforeAccept=writes.length;await press(button('Looks right'));assert.equal(writes.length,beforeAccept);
 responseGate.resolve();await resize;await until(()=>piece('door').state==='settled');
 assert.equal(piece('door').width,5);assert.equal(writes.at(-1).path,'editor/edit');assert.equal(writes.at(-1).op.op,'accept');
 ok('an opening card button waits behind an in-flight handle op and uses the legacy edit path');

 await until(()=>!document.getElementById('rail-undo').disabled);
 const errorGate=deferred();holdResponse=errorGate;
 const lead=hooks.op({op:'resize_opening',building:'b',id:'door',width:6});
 const failure=hooks.op({op:'refuse'});const observed=failure.then(()=>assert.fail('refusal must reject'),error=>error.message);
 const recovery=hooks.op({op:'resize_opening',building:'b',id:'door',width:7});
 errorGate.resolve();await lead;assert.match(await observed,/no longer exists/);
 assert.match(document.getElementById('editor-status').textContent,/That opening no longer exists/);
 await recovery;assert.equal(piece('door').width,7);
 assert.equal(alerts.length,1);assert.match(alerts[0],/no longer exists/);
 ok('a queued refusal reaches the caller and plain status line while the following edit still lands');

 const beforeLoad=current(),beforeSheets=sheetReads,beforeReverts=reverts.length;
 await houseOptions.history.perform(async()=>{
  plan.buildings[0].name='Loaded house';const round=record();await houseOptions.afterLoad({round});
 });
 assert.ok(sheetReads>beforeSheets,'loading refreshes Your place');
 const afterLoadSheets=sheetReads;
 await press(document.getElementById('rail-undo'));await until(()=>reverts.length===beforeReverts+1&&!document.getElementById('rail-redo').disabled);
 assert.equal(reverts.at(-1),beforeLoad);assert.ok(sheetReads>afterLoadSheets,'Undo reloads the restored Your place too');
 assert.notEqual(editorView.plan.buildings[0].name,'Loaded house');
 ok('real editor load and Undo both refresh model and Your place');
 const beforeFailedLoad=current();
 failSheets=true;
 await assert.rejects(houseOptions.history.perform(async()=>{
  plan.buildings[0].name='Loaded before read failed';const round=record();await houseOptions.afterLoad({round});
 }),/Sheets temporarily unavailable/);
 failSheets=false;
 assert.equal(document.getElementById('rail-undo').disabled,false,'a completed load remains undoable after a read failure');
 const beforeUndoFailure=reverts.length;
 await press(document.getElementById('rail-undo'));await until(()=>reverts.length===beforeUndoFailure+1&&!document.getElementById('rail-redo').disabled);
 assert.equal(reverts.at(-1),beforeFailedLoad);
 ok('load remains undoable when its following sheet read fails');

 const count=reverts.length;plan.buildings[0].name='Someone else changed this';record();
 await press(document.getElementById('rail-undo'));await wait(30);
 assert.equal(reverts.length,count);assert.equal(alerts.at(-1),CHANGED_SINCE);
 ok('external rounds still prevent undo from overwriting another edit');
 assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
 window.dispatchEvent(new Event('pagehide'));
 console.log(`${passed}/${passed} mutation history checks passed`);process.exit(0);
}catch(error){console.error(error);process.exit(1);}
"""


if __name__ == '__main__':
    ids = set(re.findall(r'id="([\w-]+)"', (ROOT / 'templates/house_editor.html').read_text(encoding='utf-8')))
    ids.update(['piece-card', 'rail-undo', 'rail-redo'])
    sys.exit(run(DRIVER, {'stubs': STUBS, 'ids': sorted(ids)}, timeout=45))
