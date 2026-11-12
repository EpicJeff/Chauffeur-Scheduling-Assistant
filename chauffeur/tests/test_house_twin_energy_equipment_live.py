"""Equipment browser scenarios for Claude. Written only; NOT run by Codex.

Run from chauffeur/: env -u HA_BASE_URL python tests/test_house_twin_energy_equipment_live.py
Uses the real household and the existing placed-HA-device path. UI gestures
create/resize a zone, designate its roof and add an exterior meter. The twin
checks physical endpoint projections, then a removed meter and its prompt.
"""
import copy
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import house_editor_model_harness as H
import house_twin_live_harness as L
from test_house_twin_energy_live import setup

check = H.check


def aim(page, bid, target, eye):
    page.evaluate("([bid,target,eye])=>{" + H._TO_SCENE + """
        window.__twin.setCameraState({position:toScene(eye,bid),target:toScene(target,bid)});
    }""", [bid,target,eye])
    H.settle(page)


def scenario_roof_click_resize_count_source_undo_and_exterior_meter():
    served = setup()
    if served is None:
        return
    from services import twin_store, twin_solar
    model = twin_store.current_model()
    building = next(b for b in model['buildings'] if b.get('solar_zones'))
    original = copy.deepcopy(building['solar_zones'][0])
    bid, rect, plane = building['id'], original['rect'], original['plane']
    def clear(m):
        m=copy.deepcopy(m)
        for b in m['buildings']:
            b['solar_zones']=[]
        m['solar_source_roof']=None
        return m
    twin_store.update_model(clear,'edit',note='Browser: start without zones')
    uv=[(rect[0]+rect[2])/2-2,(rect[1]+rect[3])/2]
    point=twin_solar.point(plane,uv)
    with served.browser(launch_args=L.GPU_ARGS) as page:
        H.open_editor(page,served)
        H.all_floors(page)
        page.evaluate("() => window.__twin.setView('ext')")
        aim(page,bid,point,[point[0],point[1]-20,point[2]+35])
        page.click('#rail-add-solar-zone')
        H.click_world(page,*point,bid)
        page.wait_for_function("() => window.__twin.plan.buildings.some(b=>b.solar_zones?.length)")
        zone=next(b for b in twin_store.current_model()['buildings'] if b['id']==bid)['solar_zones'][0]
        page.evaluate('([id,bid])=>window.__editor.clickPiece(id,bid)',[zone['id'],bid])
        before=len(twin_solar.layout(zone))
        edge=twin_solar.point(plane,[zone['rect'][2],(zone['rect'][1]+zone['rect'][3])/2])
        target=twin_solar.point(plane,[zone['rect'][2]+4,(zone['rect'][1]+zone['rect'][3])/2])
        start=H.screen_of_world(page,*edge,bid);end=H.screen_of_world(page,*target,bid)
        page.mouse.move(*start);page.mouse.down();page.mouse.move(*end,steps=12);page.mouse.up()
        page.wait_for_function('(n)=>document.querySelector("#piece-card").textContent.includes(n+" panels")',arg=before+1)
        check(page.locator('#piece-card').inner_text().find('panels')>=0,'card updates the panel count after resize')
        H.wait_rebuilt(page)  # the resize rebuilds the house; the card's buttons act once it settles
        page.get_by_role('button',name='Solar ribbon starts here',exact=True).click()
        page.wait_for_function('(id)=>window.__twin.plan.solar_source_roof===id',arg=zone['roof'])
        check(page.evaluate("() => {let drawn=false;window.__twin.scene.traverse(o=>{if(o.material?.name==='solar_panel')drawn=true;});return drawn;}"),'panels draw as house geometry')
        # Undo the source designation, then redo it through the existing timeline.
        page.click('#rail-undo');H.wait_rebuilt(page)
        page.click('#rail-redo');H.wait_rebuilt(page)
        # The redo's save lands after the rebuild frames; wait for the store, not two frames.
        deadline=time.time()+10
        while twin_store.current_model().get('solar_source_roof')!=zone['roof'] and time.time()<deadline:
            page.wait_for_timeout(100)
        check(twin_store.current_model()['solar_source_roof']==zone['roof'],'source survives undo/redo')
        # Actual exterior wall ray, at the clear end of the pool-house west wall.
        aim(page,L.POOL,[0,15,4],[-25,15,6])
        count=sum(a.get('kind')=='meter' for b in twin_store.current_model()['buildings'] for a in b.get('anchors',[]))
        page.click('#rail-add-meter');H.click_world(page,0,15,4,L.POOL)
        page.wait_for_function('(n)=>window.__twin.plan.buildings.flatMap(b=>b.anchors||[]).filter(a=>a.kind==="meter").length===n+1',arg=count)
        meter=next(b for b in twin_store.current_model()['buildings'] if b['id']==L.POOL)['anchors'][-1]
        check(meter['kind']=='meter' and meter['host']['side']=='right','meter is on the exterior wall face')
        L.no_errors(served)


def scenario_exact_zone_device_panel_meter_endpoints_and_deleted_meter_prompt():
    served=setup()
    if served is None:
        return
    from services import twin_store,twin_model_ops,twin_energy
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page,served,query='tier=low&test=1&panel=true&kiosk=true')
        page.get_by_role('button',name='Energy',exact=True).click()
        page.wait_for_function("() => window.__twin.live.energy().ribbons.filter(r=>r.visible).length===3")
        results=page.evaluate("""() => {
          const v=window.__twin,s=v.live.energy(),a=s.anchors,c=v.camera,r=v.renderer3.domElement.getBoundingClientRect();c.updateMatrixWorld(true);
          const pixel=p=>{const q=c.position.clone().set(p[0]*.3048,p[2]*.3048,-p[1]*.3048).project(c);return [(q.x+1)*r.width/2,(1-q.y)*r.height/2];};
          return s.ribbons.map(row=>{const [source,target]=row.id.split(':'),from=a[source],to=a[target];
            const error=(p,q)=>Math.hypot(...pixel(p).map((v,i)=>v-pixel(q)[i]));
            return {id:row.id,from:error(row.from,from),to:error(row.to,to)};});
        }""")
        check(all(r['from']<=20 and r['to']<=20 for r in results),('all endpoints project within 20px of the real zone/device/equipment anchors',results))
        ref=twin_energy.read()['locations']['grid']
        twin_store.update_model(lambda m:twin_model_ops.apply(m,dict(op='delete',building=ref['building'],id=ref['id']))[0],
                                'edit',note='Browser: remove meter')
        # Like other structural house edits, the current twin model refreshes on reload.
        page.reload();page.wait_for_function('() => !!window.__twin?.live')
        page.get_by_role('button',name='Energy',exact=True).click()
        page.wait_for_function("() => !window.__twin.live.energy().ribbons.some(r=>r.id.split(':').includes('grid'))")
        check('Place the meter to see grid flow' in page.locator('#twin-mode-legend').inner_text(),'removed meter produces placement prompt')
        L.no_errors(served)


SCENARIOS=[scenario_roof_click_resize_count_source_undo_and_exterior_meter,
           scenario_exact_zone_device_panel_meter_endpoints_and_deleted_meter_prompt]
if __name__=='__main__':L.run(SCENARIOS)
