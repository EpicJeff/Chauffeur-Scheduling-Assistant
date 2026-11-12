"""Real browser setup + authenticated route payloads exercised in Node; no Chromium."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from twin_live_node_rig import run

DRIVER = r"""
const {solarZones,solarPlanes,solarCovered,solarPoint}=await import(file('static/twin/twin_solar.js'));
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {mountEnergySettings}=await import(file('static/twin/live/energy_settings.js'));
const {createSceneTools}=await import(file('static/twin/editor/scene_tools.js'));
const {createDraw}=await import(file('static/twin/editor/draw.js'));
let passed=0;const ok=text=>{passed++;console.log('  ok '+text);};
try {
 const p=config.payload,plan=p.twin.plan,b=plan.buildings.find(b=>b.solar_zones?.length),z=b.solar_zones[0];
 assert.equal(solarZones(b).length,1);assert.equal(solarZones(b)[0].panels.length,p.panels);
 const old={roof:'roof:c8d939d2e6974824af1367e641db38f5',plane:[0,10/12,80/9],rect:[27,17,35,29]};
 const face=solarPlanes(b).find(f=>f.roof===old.roof&&f.plane.every((v,i)=>Math.abs(v-old.plane[i])<1e-6));
 assert.equal(solarCovered(old.rect,face),false);
 ok('real route zone is covered; the former dormer-crossing rectangle is rejected by both geometries');
 const twin=buildTwin(plan,config.kit,{showAnchors:true});await twin.ready;
 let panels=0;twin.root.traverse(o=>{if(o.material?.name==='solar_panel')panels++;});assert.ok(panels);
 ok('generator draws solar panels from the saved schema-3 model through the flat route');
 const t=await rig({devices:[]});t.live.stop();
 const streams=[];globalThis.EventSource=class {constructor(){streams.push(this);}close(){}};
 Object.assign(t.view,{plan,roofSurfaces:twin.roofSurfaces,groups:twin.groups});t.view.scene.add(twin.root);
 let states=structuredClone(p.states);
 const api=async path=>({ok:true,json:async()=>structuredClone(path==='api/house/live'?p.live:path==='api/house/twin/energy'?p.energy:states)});
 // Settings before live: the wall has no editable drawer and still gets its mapping.
 t.view.energySettings=mountEnergySettings(t.view,{api});await t.view.energySettings.reload();
 t.view.live=await liveModule.mountLive(t.view,{api});t.view.live.setMode('energy');
 const visible=()=>Object.fromEntries(t.view.live.energy().ribbons.filter(r=>r.visible).map(r=>[r.id,r.watts]));
 assert.equal(t.view.live.stale(),false);assert.equal(p.energy.can_edit,false);
 assert.deepEqual(visible(),{'solar:house':500,'solar:battery':2000,'solar:grid':1500});
 assert.ok(t.view.live.energy().anchors.solar);
 ok('read-only panel mapping and fetched power states produce the three exact solar allocations');
 states=structuredClone(p.pushed_states);
 for(const role of ['solar','battery','grid','house']){
  const id='sensor.live_'+role;streams.at(-1).onmessage({data:JSON.stringify({entity_id:id,state:states.states[id]})});
 }
 await wait(40);
 assert.deepEqual(visible(),{'solar:house':1000,'battery:house':2000,'grid:house':2500});
 await t.view.live.refresh();assert.deepEqual(visible(),{'solar:house':1000,'battery:house':2000,'grid:house':2500});
 for(const row of t.view.live.energy().ribbons){const [a,b]=row.id.split(':');assert.deepEqual(row.from,t.view.live.energy().anchors[a]);assert.deepEqual(row.to,t.view.live.energy().anchors[b]);}
 ok('HA pushes and polls recompute watts and directions while retaining real endpoint anchors');
 t.view.energySettings.stop();t.view.live.stop();delete t.view.energySources;delete t.view.energySettings;
 // Settings after live: also exercise the other asynchronous startup order.
 states=structuredClone(p.states);t.view.live=await liveModule.mountLive(t.view,{api});
 t.view.energySettings=mountEnergySettings(t.view,{api});await t.view.energySettings.reload();t.view.live.setMode('energy');
 assert.deepEqual(visible(),{'solar:house':500,'solar:battery':2000,'solar:grid':1500});
 t.view.energySettings.stop();t.view.live.stop();
 ok('mapping loaded after live startup also updates the read-only panel');

 // Actual editor delegate -> handle -> op result -> card path, with a slow
 // creation promise still outstanding when the saved zone becomes selectable.
 const ids=['piece-card','editor-floors','editor-drag-hint','editor-drag-outline','draw-note','draw-tools','draw-cancel',
 ...['select','move','rotate','sheet','draw-room','draw-wall','split-room','add-door','add-window','add-anchor','add-solar-zone','add-meter','add-electric-panel','delete','add-level'].map(n=>'rail-'+n)];
 for(const id of ids)if(!document.getElementById(id)){const n=document.createElement('div');n.id=id;document.body.append(n);}
 let current=structuredClone(p.empty.plan),model=p.empty.model,release,created=false,tools;
 const canvas=t.canvas,view=t.view;view.plan=current;view.controls=new THREE.EventDispatcher();view.controls.enabled=true;
 view.state={view:'ext',camera:'front'};view.setView=()=>{};view.floorAt=()=>[10,10];view.screenOfFloor=(x,y)=>[x,y];view.setSelection=()=>0;
 const savedBuilding=p.created.plan.buildings.find(x=>x.solar_zones?.length),savedZone=savedBuilding.solar_zones[0];
 const uv=[(savedZone.rect[0]+savedZone.rect[2])/2,(savedZone.rect[1]+savedZone.rect[3])/2],point=solarPoint(savedZone.plane,uv);
 const world=p=>{const a=(savedBuilding.rotation||0)*Math.PI/180,pos=savedBuilding.position;return new THREE.Vector3((Math.cos(a)*p[0]-Math.sin(a)*p[1]+pos[0])*FT,(p[2]+(savedBuilding.base||0))*FT,-(Math.sin(a)*p[0]+Math.cos(a)*p[1]+pos[1])*FT);};
 view.camera.position.copy(world([point[0],point[1]-20,point[2]+35]));view.camera.lookAt(world(point));view.camera.updateMatrixWorld(true);
 const event=p=>{const q=world(p).project(view.camera);return {pointerId:1,button:0,clientX:(q.x+1)*700,clientY:(1-q.y)*500};};
 const abort=new AbortController(),operations=[];
 globalThis.ResizeObserver=class {observe(){} disconnect(){}};
 const op=async operation=>{
  operations.push(operation);
  const response=operation.op==='add_solar_zone'?p.created:p.resized;
  assert.deepEqual(operation,operation.op==='add_solar_zone'?p.create_op:p.resize_op);
  current=structuredClone(response.plan);model=response.model;view.plan=current;tools.refreshCard();
  if(operation.op==='add_solar_zone'){created=true;await new Promise(resolve=>{release=resolve;});}
 };
 tools=createSceneTools({view,getPlan:()=>current,getModel:()=>model,getKit:()=>config.kit,getSheets:()=>({}),edit:assert.fail,op,
  panel:{clearSelection(){},focusSelection(){},message:assert.fail},canEdit:()=>true,signal:abort.signal,api:{report:assert.fail}});
 const draw=createDraw({view,tools,getPlan:()=>current,op,gesture:work=>work(),canEdit:()=>true,signal:abort.signal,onInteract(){},panel:{message:assert.fail},
  surfaceAt:()=>({building:current.buildings.find(x=>x.id===savedBuilding.id),kind:'roof',piece:{roof:savedZone.roof},point})});
 tools.delegate(draw);window.showGlobalAlert=message=>assert.fail(message);
 await press(document.getElementById('rail-add-solar-zone'));
 for(const type of ['pointerdown','pointerup'])canvas.dispatchEvent(new PointerEvent(type,{bubbles:true,...event(point)}));
 await wait(30);assert.ok(created);tools.select({pieceId:savedZone.id,buildingId:savedBuilding.id});
 assert.ok(document.getElementById('piece-card').textContent.includes('1 panels'));
 const edge=solarPoint(savedZone.plane,[savedZone.rect[2],uv[1]]),end=solarPoint(savedZone.plane,[savedZone.rect[2]+4,uv[1]]);
 canvas.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,...event(edge)}));
 assert.ok(tools.dragging(),'selected resize handle owns the pointer while creation is settling');
 canvas.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,...event(end)}));
 canvas.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,...event(end)}));await wait(30);
 assert.equal(operations.length,2);assert.equal(operations[1].op,'update_solar_zone');
 assert.ok(document.getElementById('piece-card').textContent.includes('2 panels'));
 release();await wait(30);assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);abort.abort();t.host.remove();
 ok('resize owns its pointer during a delayed placement save and the card redraws from the real op result');
 console.log(`${passed+2}/${passed+2} route boundary checks passed (2 Python + ${passed} Node)`);process.exit(0);
}catch(error){console.error(error);process.exit(1);}
"""


def main():
    # setup() serves the app; only served.browser() would launch Chromium.
    import test_house_twin_energy_live as browser
    served = browser.setup()
    if served is None:
        raise AssertionError('The server-side browser fixture could not start')
    try:
        from fastapi.testclient import TestClient
        import main as app
        from services import twin_store, twin_solar, twin_library
        client = TestClient(app.app)
        wall = {'X-Device-Token': browser.L.STATE['panel']}
        parent = {'X-Member-Token': browser.L.H.STATE['token']}
        def get(path):
            response = client.get(path, headers=wall)
            assert response.status_code == 200, response.text
            return response.json()
        payload = {key: get(path) for key, path in [
            ('twin', '/api/house/twin'), ('energy', '/api/house/twin/energy'),
            ('states', '/api/ha/card/states?fresh=1'), ('live', '/api/house/live')]}
        b = next(b for b in twin_store.current_model()['buildings'] if b.get('solar_zones'))
        z = b['solar_zones'][0]
        payload['panels'] = len(twin_solar.layout(z))
        assert payload['energy']['mapping']['solar_power'] == 'sensor.live_solar'
        assert payload['states']['states']['sensor.live_solar']['state'] == '4000'
        assert not payload['energy']['can_edit']
        print('  ok setup + wall-token TestClient routes retain zones, mapping and power states')
        browser.push_totals(1000, 2000, 2500, 5500)
        payload['pushed_states'] = get('/api/ha/card/states?fresh=1')
        def clear(model):
            model = copy.deepcopy(model)
            for building in model['buildings']:
                building['solar_zones'] = []
            model['solar_source_roof'] = None
            return model
        twin_store.update_model(clear, 'edit', note='Route regression: empty roof')
        payload['empty'] = {'plan': twin_store.current(), 'model': twin_store.current_model()}
        def post(operation):
            return client.post('/api/house/editor/op', headers=parent, json={'op': operation})
        before = twin_store.current_id()
        response = post(dict(op='add_solar_zone', building='main-house',
                             roof='roof:c8d939d2e6974824af1367e641db38f5',
                             plane=[0, 10/12, 80/9], rect=[27,17,35,29]))
        assert response.status_code == 400, response.text
        assert twin_store.current_id() == before
        print('  ok actual editor route atomically refuses the former dormer-crossing fixture zone')
        u, v = (z['rect'][0]+z['rect'][2])/2-2, (z['rect'][1]+z['rect'][3])/2
        u, v = round(u*12)/12, round(v*12)/12
        payload['create_op'] = dict(op='add_solar_zone', building=b['id'], roof=z['roof'],
                                    plane=z['plane'], rect=[u-2,v-3,u+2,v+3])
        response = post(payload['create_op'])
        assert response.status_code == 200, response.text
        payload['created'] = response.json()
        added = next(b for b in payload['created']['model']['buildings'] if b.get('solar_zones'))['solar_zones'][0]
        rect = added['rect'][:]
        rect[2] += 4
        payload['resize_op'] = dict(op='update_solar_zone', building=b['id'], id=added['id'], rect=rect)
        response = post(payload['resize_op'])
        assert response.status_code == 200, response.text
        payload['resized'] = response.json()
        return run(DRIVER, {'payload': payload, 'kit': twin_library.kit('modern_farmhouse')}, timeout=60)
    finally:
        served.stop()


if __name__ == '__main__':
    sys.exit(main())
