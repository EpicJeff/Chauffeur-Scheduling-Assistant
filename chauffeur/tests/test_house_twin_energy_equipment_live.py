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


def scenario_garage_charger_two_coloured_cars_pulse_card_and_program_reuse():
    """Acceptance scenario for Claude; Codex must not launch Chromium."""
    served=setup()
    if served is None:
        return
    from services import storage, twin_store, twin_model_ops, twin_energy
    from test_house_twin_energy_live import push
    red,blue='garage-red','garage-blue'
    for cid,name,color,tracker,battery in [(red,'Red EV','#cc2222','device_tracker.garage_red','sensor.garage_red_battery'),
                                          (blue,'Blue EV','#2244cc',None,'sensor.garage_blue_battery')]:
        storage.add_car(dict(id=cid,name=name,color_code=color,ha_device_tracker=tracker,ha_battery_entity=battery))
    for eid,state,attrs in [('sensor.garage_charger_power','7000',dict(device_class='power',unit_of_measurement='W')),
                            ('sensor.garage_red_battery','78',dict(unit_of_measurement='%')),
                            ('sensor.garage_blue_battery','65',dict(unit_of_measurement='%')),
                            ('binary_sensor.garage_red_charging','on',{}),('binary_sensor.garage_blue_charging','off',{}),
                            ('device_tracker.garage_red','home',{})]:
        L.FAKE.states[eid]=dict(entity_id=eid,state=state,attributes=attrs)
    mapping=twin_energy.read()
    def equip(model):
        model=copy.deepcopy(model)
        b=next(b for b in model['buildings'] if b['id']==L.POOL)
        b['name']='Garage'
        room=next(r for r in b['rooms'] if r['id']==L.KITCHEN);room['name']='Garage'
        wall=next(w for w in b['walls'] if w['id']=='wall:17ec2a8dad9e47d0aefbfe143524c1c2~2')
        model=twin_model_ops.apply(model,dict(op='add_equipment',building=L.POOL,kind='charger',name='Garage charger',
            power='sensor.garage_charger_power',host=dict(wall=wall['id'],side='left',at=9,z=3)))[0]
        charger=next(b for b in model['buildings'] if b['id']==L.POOL)['anchors'][-1]
        for cid,u in [(red,.3),(blue,.7)]:
            model=twin_model_ops.apply(model,dict(op='add_equipment',building=L.POOL,kind='parking',car=cid,
                host=dict(floor=L.KITCHEN,u=u,v=.5)))[0]
        mapping.update(chargers=[dict(id='garage-evse',name='Garage charger',power='sensor.garage_charger_power',
            anchor=dict(type='object',building=L.POOL,id=charger['id']))],
            cars=[dict(id=red,name='Red EV',battery_level='sensor.garage_red_battery',location='device_tracker.garage_red',charging='binary_sensor.garage_red_charging'),
                  dict(id=blue,name='Blue EV',battery_level='sensor.garage_blue_battery',charging='binary_sensor.garage_blue_charging')])
        twin_energy.save(mapping)
        return model
    twin_store.update_model(equip,'edit',note='Browser: garage charger and two parking spots')
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page,served,query='tier=low&test=1&panel=true&kiosk=true')
        page.get_by_role('button',name='All',exact=True).click()
        page.wait_for_function('() => window.__twin.cars?.snapshot().filter(r=>r.visible).length===2')
        colors=page.evaluate('() => window.__twin.cars.snapshot().map(r=>r.color)')
        check(colors==['#cc2222','#2244cc'],('both icons use fleet colours',colors))
        # Aim at the garage floor so the DOM tap targets are on screen.
        b=next(b for b in twin_store.current_model()['buildings'] if b['id']==L.POOL)
        room=next(r for r in b['rooms'] if r['id']==L.KITCHEN)
        centre=[sum(p[i] for p in room['polygon'])/len(room['polygon']) for i in (0,1)]
        aim(page,L.POOL,[*centre,0],[centre[0],centre[1]-22,35])
        page.locator('[data-car-icon="garage-red"]').click()
        check(page.locator('[data-car-card="garage-red"]').is_visible(),'tap opens car card')
        card=page.locator('[data-car-card="garage-red"]')
        check('78%' in card.inner_text() and 'Garage charger' in card.inner_text(),'card explains battery and charger')
        card.get_by_role('button',name='Close',exact=True).click()
        page.get_by_role('button',name='Energy',exact=True).click()
        page.wait_for_function("() => window.__twin.live.energy().ribbons.some(r=>r.id==='charger:0' && r.visible)")
        links=page.evaluate('() => window.__twin.live.energy().ribbons.filter(r=>r.link && r.visible)')
        spots=next(b for b in twin_store.current_model()['buildings'] if b['id']==L.POOL)['anchors']
        red_spot=next(s for s in spots if s.get('kind')=='parking' and s.get('car')==red)
        check(len(links)==1 and links[0]['id'].endswith(':'+red_spot['id']),('only charging car gets a cable',links))
        check(max(p[1] for p in links[0]['path'])-min(p[1] for p in links[0]['path'])<.001,'cable is flat, not an arc')
        # The first visit to each mode may compile its variants; a second round trip compiles
        # nothing (the repo-wide rule, as in test_house_twin_energy_live's second-entry check).
        modes=['All','Lights','Energy','All']
        for mode in modes:
            page.get_by_role('button',name=mode,exact=True).click()
        page.wait_for_timeout(200)
        programs=page.evaluate('() => window.__twin.renderer3.info.programs.length')
        for mode in modes:
            page.get_by_role('button',name=mode,exact=True).click()
        check(page.evaluate('() => window.__twin.renderer3.info.programs.length')==programs,'a second mode round trip compiles no programs')
        push('device_tracker.garage_red','away')
        page.wait_for_function("() => window.__twin.cars.snapshot().find(r=>r.id==='garage-red').visible===false")
        check(page.evaluate("() => window.__twin.cars.snapshot().find(r=>r.id==='garage-blue').visible"),'other home car remains visible')
        L.no_errors(served)


SCENARIOS=[scenario_roof_click_resize_count_source_undo_and_exterior_meter,
           scenario_exact_zone_device_panel_meter_endpoints_and_deleted_meter_prompt,
           scenario_garage_charger_two_coloured_cars_pulse_card_and_program_reuse]
if __name__=='__main__':L.run(SCENARIOS)
