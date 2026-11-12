"""Chromium scenarios for Claude. Written but NOT run by Codex.

Run from chauffeur/: env -u HA_BASE_URL timeout 300 python tests/test_house_twin_energy_live.py
Optional TWIN_ENERGY_OUTPUT saves dark wall screenshots outside the repository.
"""
import copy
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import house_twin_live_harness as L

check = L.check


def setup():
    served = L.serve()
    if served is None:
        return None
    L.reset()
    from services import twin_energy, twin_store, twin_model_ops, twin_solar, twin_model
    mapping = {'solar_power': 'sensor.live_solar', 'battery_power': 'sensor.live_battery',
               'grid_power': 'sensor.live_grid', 'house_power': 'sensor.live_house',
               'battery_positive': 'discharge', 'grid_positive': 'import', 'cars': []}
    twin_energy.save(mapping)
    # The glance bar holds only chosen tiles (v2.499.796): choose the four totals here.
    from services import twin_glance
    twin_glance.save([{'entity': 'sensor.live_' + k, 'icon': i, 'label': ''} for k, i in
                      (('solar', 'solar'), ('battery', 'battery'), ('grid', 'grid'), ('house', 'house'))], False)
    for key, value in (('solar', 4000), ('battery', -2000), ('grid', -1500), ('house', 500)):
        eid = 'sensor.live_' + key
        L.FAKE.states[eid] = {'entity_id': eid, 'state': str(value),
                              'attributes': {'device_class': 'power', 'unit_of_measurement': 'W'}}
    L.FAKE.devices[:] = [d for d in L.FAKE.devices if d['id'] != 'energy-camera']
    L.FAKE.devices[:] = [d for d in L.FAKE.devices if d['id'] != 'energy-battery']
    L.FAKE.devices.append({'id':'energy-battery','name':'Placed Powerwall','area_id':'kitchen',
                           'entities':[('sensor.live_battery','-2000',{'device_class':'power','unit_of_measurement':'W'})]})
    L.FAKE.devices.append({'id': 'energy-camera', 'name': 'Kitchen camera', 'area_id': 'kitchen',
                           'entities': [('camera.energy_kitchen', 'idle', {})]})
    L.FAKE.states['camera.energy_kitchen'] = {'entity_id': 'camera.energy_kitchen', 'state': 'idle', 'attributes': {}}

    def place(model):
        model = copy.deepcopy(model)
        building = next(b for b in model['buildings'] if b['id'] == L.POOL)
        building['devices'].append({'id': 'device:energy-camera', 'device': 'energy-camera',
                                    'host': {'floor': L.KITCHEN, 'u': .15, 'v': .2},
                                    'offset': 5, 'facing_deg': 45, 'src': {'person': True}})
        building['devices'].append({'id':'device:energy-battery','device':'energy-battery',
                                    'host':{'floor':L.KITCHEN,'u':.35,'v':.65},'offset':4,'src':{'person':True}})
        # Explicit fixture zones: find a clear 8 x 12 ft rectangle, then persist
        # that roof and plane; production never auto-picks an energy plane.
        found=False
        for b in model['buildings']:
            for face in twin_solar.faces(b):
                poly=face['polygon'];xs=[p[0] for p in poly];ys=[p[1] for p in poly]
                for y in range(int(min(ys))+1,int(max(ys))-12,2):
                    for x in range(int(min(xs))+1,int(max(xs))-8,2):
                        rect=[x,y,x+8,y+12]
                        if twin_model._overlap(twin_solar.rectangle(rect),poly)>96-1e-6:
                            model=twin_model_ops.apply(model,dict(op='add_solar_zone',building=b['id'],roof=face['roof'],plane=list(face['plane']),rect=rect))[0]
                            model=twin_model_ops.apply(model,dict(op='set_solar_source',roof=face['roof']))[0]
                            found=True;break
                    if found:break
                if found:break
            if found:break
        check(found,'fixture has a clear real roof face')
        west='wall:17ec2a8dad9e47d0aefbfe143524c1c2~2'
        locations={'battery':{'type':'device','id':'energy-battery'}}
        for kind,role,side,at in [('meter','grid','right',2.5),('electric_panel','house','left',15)]:
            model=twin_model_ops.apply(model,dict(op='add_equipment',building=L.POOL,kind=kind,host=dict(wall=west,side=side,at=at,z=4)))[0]
            p=next(b for b in model['buildings'] if b['id']==L.POOL)['anchors'][-1]
            locations[role]={'type':'object','id':p['id'],'building':L.POOL}
        twin_energy.save({**mapping,'locations':locations})
        return model
    twin_store.update_model(place, 'edit', note='Energy/security browser fixture')
    return served


def push(eid, state):
    from services import ha_events
    row = copy.deepcopy(L.FAKE.states[eid])
    row['state'] = str(state)
    L.FAKE.states[eid] = row
    ha_events._publish({'entity_id': eid, 'new_state': row})


def push_totals(solar,battery,grid,house):
    for role,value in [('solar',solar),('battery',battery),('grid',grid),('house',house)]:
        push('sensor.live_'+role,value)


def wait_flows(page,expected):
    page.wait_for_function("""expected => {
      const rows=window.__twin.live.energy().ribbons.filter(r=>r.visible);
      return rows.length===Object.keys(expected).length && rows.every(r=>expected[r.id]===r.watts);
    }""",arg=expected,timeout=5000)


def assert_flow_endpoints(page):
    rows=page.evaluate("""() => {
      const v=window.__twin,s=v.live.energy(),a=s.anchors,c=v.camera,rect=v.renderer3.domElement.getBoundingClientRect();c.updateMatrixWorld(true);
      const pixel=p=>{const q=c.position.clone().set(p[0]*.3048,p[2]*.3048,-p[1]*.3048).project(c);return [(q.x+1)*rect.width/2,(1-q.y)*rect.height/2];};
      const error=(p,q)=>Math.hypot(...pixel(p).map((v,i)=>v-pixel(q)[i]));
      return s.ribbons.filter(r=>r.visible).map(row=>{const [from,to]=row.id.split(':');
        return {id:row.id,from:error(row.from,a[from]),to:error(row.to,a[to])};});
    }""")
    check(all(r['from']<=20 and r['to']<=20 for r in rows),('real flow endpoint projections',rows))


def shot(page, name):
    if os.environ.get('TWIN_ENERGY_OUTPUT'):
        out = Path(os.environ['TWIN_ENERGY_OUTPUT'])
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / name), full_page=True)


def ribbon_apex_pixels(page):
    """Compare actual WebGL pixels with/without ribbons at each world crest.

    Reading the same frame twice avoids judging glow against a guessed sky
    colour. DOM labels cannot contaminate these framebuffer samples.
    """
    return page.evaluate("""() => {
      const v=window.__twin,r=v.renderer3,gl=r.getContext(),canvas=r.domElement;
      v.camera.updateMatrixWorld(true);
      const w=gl.drawingBufferWidth,h=gl.drawingBufferHeight;
      const samples=v.live.energy().ribbons.filter(x=>x.visible).map(row=>{
        const p=v.camera.position.clone().fromArray(row.apex).project(v.camera);
        const x=Math.round((p.x+1)*w/2),y=Math.round((p.y+1)*h/2),radius=8;
        const path=row.path.map(at=>v.camera.position.clone().fromArray(at).project(v.camera));
        const sign=Math.sign(path.at(-1).x-path[0].x),monotonic=sign!==0&&path.slice(1).every((p,i)=>(p.x-path[i].x)*sign>=-1e-7);
        const rise=row.apex[1]/.3048-Math.max(row.from[2],row.to[2]);
        return {id:row.id,hue:row.hue.map(c=>c*255),monotonic,rise,x:Math.max(0,Math.min(w-17,x-radius)),y:Math.max(0,Math.min(h-17,y-radius)),p:p.toArray()};});
      const read=()=>samples.map(s=>{const pixels=new Uint8Array(17*17*4);gl.readPixels(s.x,s.y,17,17,gl.RGBA,gl.UNSIGNED_BYTE,pixels);return pixels;});
      const meshes=[];v.scene.traverse(o=>{if(o.userData.energyRibbon||o.userData.energyRibbonHalo){meshes.push([o,o.visible]);o.visible=false;}});
      let background,lit=[];
      try{
        r.render(v.scene,v.camera);background=read();
        for(let i=0;i<samples.length;i++){
          for(const[o,shown]of meshes)o.visible=shown&&(o.userData.energyRibbon===samples[i].id||o.userData.energyRibbonHalo===samples[i].id);
          r.render(v.scene,v.camera);const pixels=new Uint8Array(17*17*4);
          gl.readPixels(samples[i].x,samples[i].y,17,17,gl.RGBA,gl.UNSIGNED_BYTE,pixels);lit.push(pixels);
        }
      }finally{for(const[o,shown]of meshes)o.visible=shown;r.render(v.scene,v.camera);}
      return samples.map((s,n)=>{let best=-Infinity,selected={delta:0,peak:0,contrast:0,hueDistance:Infinity,whiteDistance:0,rgb:[]};
        for(let i=0;i<lit[n].length;i+=4){const brightness=.2126*lit[n][i]+.7152*lit[n][i+1]+.0722*lit[n][i+2];
          const base=.2126*background[n][i]+.7152*background[n][i+1]+.0722*background[n][i+2];
          const rgb=Array.from(lit[n].slice(i,i+3)),contrast=Math.max(...rgb.map((v,j)=>Math.abs(v-background[n][i+j])));
          if(contrast<18)continue; // Unchanged sky pixels cannot pass a hue check.
          const hueDistance=Math.hypot(...rgb.map((v,j)=>v-s.hue[j])),whiteDistance=Math.hypot(...rgb.map(v=>v-255));
          const margin=whiteDistance-hueDistance;if(margin>best){best=margin;selected={rgb,contrast,hueDistance,whiteDistance,delta:brightness-base,peak:Math.max(...rgb)};}}
        return {id:s.id,monotonic:s.monotonic,rise:s.rise,onscreen:Math.abs(s.p[0])<1&&Math.abs(s.p[1])<1&&Math.abs(s.p[2])<1,...selected};});
    }""")


def scenario_energy_ribbons_labels_and_grid_push():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
        page.get_by_role('button', name='Energy', exact=True).click()
        page.wait_for_function("() => window.__twin.live.energy().ribbons.filter(r=>r.visible).length===3")
        midday={'solar:house':500,'solar:battery':2000,'solar:grid':1500}
        wait_flows(page,midday)
        values = page.evaluate('() => window.__twin.live.energy().ribbons.filter(r=>r.visible)')
        check({r['id']: r['label'] for r in values} == {'solar:house':'0.5 kW','solar:battery':'2 kW','solar:grid':'1.5 kW'},values)
        for label in ('solar to home 0.5 kW','solar to battery 2 kW','solar to grid 1.5 kW'):
            check(page.get_by_text(label,exact=True).count()==1,label)
        assert_flow_endpoints(page)
        check('4.0 kW' in page.locator('#twin-glance').inner_text(),'glance uses kW')
        page.wait_for_timeout(1000)
        programs=page.evaluate('() => window.__twin.renderer3.info.programs.length')
        # Storm watch: the meter feeds both home and the placed Powerwall.
        push_totals(0,-2000,2500,500)
        wait_flows(page,{'grid:house':500,'grid:battery':2000})
        assert_flow_endpoints(page)
        page.wait_for_function("() => document.querySelector('#twin-glance').textContent.includes('charging 2.0 kW') && document.querySelector('#twin-glance').textContent.includes('importing 2.5 kW')")
        shot(page,'energy-grid-to-battery.png')
        # Battery export: Powerwall covers home first, then exports to the meter.
        push_totals(0,6000,-4000,2000)
        wait_flows(page,{'battery:house':2000,'battery:grid':4000})
        assert_flow_endpoints(page)
        page.wait_for_function("() => document.querySelector('#twin-glance').textContent.includes('discharging 6.0 kW') && document.querySelector('#twin-glance').textContent.includes('exporting 4.0 kW')")
        shot(page,'energy-battery-to-grid.png')
        check(page.evaluate('() => window.__twin.renderer3.info.programs.length')==programs,'pairwise flow changes compile no new shader programs')
        push_totals(4000,-2000,-1500,500)
        wait_flows(page,midday)
        for preview in ('day', 'night'):
            page.evaluate('(mode)=>window.__twin.setTime(mode)', preview)
            page.wait_for_timeout(300)
            samples = ribbon_apex_pixels(page)
            check(len(samples) == 3 and all(2-1e-6 <= s['rise'] <= 10+1e-6 and s['onscreen'] for s in samples), (preview, 'gentle apexes stay within 10 ft of their higher endpoint', samples))
            # Capped source colours can be darker than a day sky. The old >=230
            # white-peak test contradicted hue preservation; require contrast
            # plus distance to the actual source hue instead.
            check(all(s['peak'] >= 90 and s['contrast'] >= 18 for s in samples), (preview, 'ribbon colour contrasts against its actual background', samples))
            check(all(s['hueDistance'] < s['whiteDistance'] for s in samples), (preview, 'apex colour is closer to its source hue than white', samples))
            # Actual anchors take precedence over the old screen-space bus nudges.
            shot(page, 'energy-ribbons-' + preview + '.png')
        labels = page.locator('.twin-energy-labels span:visible').evaluate_all("nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};})")
        check(len(labels) == 3, ('three actual energy labels are tested for overlap', labels))
        for i, a in enumerate(labels):
            for b in labels[:i]:
                check(not (a['left'] < b['right'] and a['right'] > b['left'] and a['top'] < b['bottom'] and a['bottom'] > b['top']), ('labels do not overlap', a, b))
        check(page.evaluate("() => {let visible=false;window.__twin.scene.traverse(o=>{if(o.material?.name==='solar_panel')visible=o.visible && o.material.visible;});return visible;}"), 'front-facing roof panels are visible')
        shot(page, 'energy-wall.png')
        L.no_errors(served)


def scenario_security_attention_camera_and_lock_push():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
        L.aim_kitchen(page)
        page.get_by_role('button', name='Security', exact=True).click()
        page.wait_for_timeout(1000)
        push('lock.back_door', 'unlocked')
        page.wait_for_function("""() => {let red=false;window.__twin.scene.traverse(o=>{if(o.userData.securityAttention==='dev-back-lock')red=o.visible;});return red;}""", timeout=3000)
        check(True, 'unlocked back door shows red emphasis')
        page.wait_for_function("""() => {let cone=false;window.__twin.scene.traverse(o=>{if(o.userData.cameraCone?.device==='energy-camera')cone=o.visible;});return cone;}""")
        check(True, 'placed camera cone is visible')
        shot(page, 'security-open-wall.png')
        push('lock.back_door', 'locked')
        page.wait_for_function("""() => {let red=true;window.__twin.scene.traverse(o=>{if(o.userData.securityAttention==='dev-back-lock')red=o.visible;});return !red;}""", timeout=3000)
        check(True, 'locking removes emphasis')
        L.no_errors(served)


def scenario_no_programs_on_second_entry_to_either_mode():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=high&test=1&panel=true&kiosk=true')
        for mode in ('Energy', 'Security'):
            page.get_by_role('button', name=mode, exact=True).click()
            page.wait_for_timeout(750)
            before = page.evaluate('() => window.__twin.renderer3.info.programs.length')
            page.get_by_role('button', name='All', exact=True).click()
            page.wait_for_timeout(250)
            page.get_by_role('button', name=mode, exact=True).click()
            page.wait_for_timeout(750)
            after = page.evaluate('() => window.__twin.renderer3.info.programs.length')
            check(before == after, (mode, 'no new programs on re-entry', before, after))
        L.no_errors(served)


def scenario_energy_check_explains_removed_meter():
    served = setup()
    if served is None:
        return
    from services import twin_store

    def remove_meter(model):
        model = copy.deepcopy(model)
        for building in model['buildings']:
            building['anchors'] = [p for p in building.get('anchors', []) if p.get('kind') != 'meter']
        return model

    # Keep the saved grid location pointing at the removed object. Nothing
    # may silently replace it with a guessed device or a building centre.
    twin_store.update_model(remove_meter, 'edit', note='Remove meter for Energy check scenario')
    push_totals(0, -2000, 2500, 500)
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
        page.get_by_role('button', name='Energy', exact=True).click()
        page.wait_for_function("() => window.__twin.live.energy().check?.summary === 'No ribbons because Meter / grid not placed'")
        page.get_by_role('link', name='Why no ribbons?', exact=True).click()
        panel = page.locator('#twin-mode-legend .twin-energy-check')
        meter = panel.locator('[data-energy-role="grid"]')
        check(meter.get_attribute('data-status') == 'unplaced', 'removed meter is unplaced')
        check('sensor.live_grid' in meter.inner_text() and 'add a meter object' in meter.inner_text(), meter.inner_text())
        for flow in ('grid:house', 'grid:battery'):
            row = panel.locator('[data-energy-flow="' + flow + '"]')
            check('no ribbon: Meter / grid not placed' in row.inner_text(), row.inner_text())
        check(page.evaluate('() => window.__twin.live.energy().ribbons.every(r => !r.visible)'), 'no grid ribbon without its real meter')
        page.evaluate("() => window.__twin.setTime('night')")
        shot(page, 'energy-check-removed-meter-night-wall.png')
        L.no_errors(served)


def scenario_energy_check_warns_about_battery_as_house_and_mapping_repair_shows_ribbon():
    served = setup()
    if served is None:
        return
    from services import twin_energy

    mapping = twin_energy.read()
    twin_energy.save({**mapping, 'house_power': 'sensor.live_battery'})
    push_totals(0, 0, 1800, 1800)
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
        page.get_by_role('button', name='Energy', exact=True).click()
        expected = "No ribbons because the readings don't balance — check the Electric panel / house sensor"
        page.wait_for_function('(summary) => window.__twin.live.energy().check?.summary === summary', arg=expected)
        page.get_by_role('link', name='Why no ribbons?', exact=True).click()
        panel = page.locator('#twin-mode-legend .twin-energy-check')
        house = panel.locator('[data-energy-role="house"]')
        check(house.get_attribute('data-status') == 'unbalanced', house.inner_text())
        check('sensor.live_battery' in house.inner_text(), 'warning identifies the wrong house sensor')
        check("readings don't balance: solar + battery + grid = 1.8 kW, house reads 0.0 kW" in house.inner_text(), house.inner_text())
        check(house.locator('[data-energy-mark]').inner_text() == '⚠', 'house has a warning mark')
        check(house.locator('[data-energy-mark]').evaluate('(node) => getComputedStyle(node).color') == 'rgb(251, 191, 36)', 'warning mark is amber')
        check(house.locator('p').first.evaluate('(node) => getComputedStyle(node).color') == 'rgb(229, 231, 235)', 'check text is light')
        check(house.locator('strong').evaluate('(node) => Number(getComputedStyle(node).fontWeight) >= 700'), 'role name is bold')
        check(panel.locator('[data-energy-summary]').evaluate('(node) => parseFloat(getComputedStyle(node).fontSize) >= 16'), 'summary is larger')
        check(page.evaluate('() => window.__twin.live.energy().ribbons.every(r => !r.visible)'), 'wrong zero house produces no invented ribbon')
        shot(page, 'energy-check-wrong-house.png')

        # Repair through the real parents-only endpoint, then reload the wall's
        # saved mapping. The panel remains paired with its read-only token.
        response = page.request.put(served.url('api/house/twin/energy'),
                                    headers={'X-Member-Token': L.H.STATE['token']}, data=mapping)
        check(response.status == 200, response.text())
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
        page.get_by_role('button', name='Energy', exact=True).click()
        wait_flows(page, {'grid:house': 1800})
        page.wait_for_function("() => window.__twin.live.energy().check.roles.find(r => r.id === 'house').status === 'ok'")
        assert_flow_endpoints(page)
        shot(page, 'energy-check-repaired-house.png')
        L.no_errors(served)


def scenario_energy_ribbon_pixels_cover_an_intervening_real_roof():
    served = setup()
    if served is None:
        return
    push_totals(0, 0, 1800, 1800)
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
        page.get_by_role('button', name='Energy', exact=True).click()
        wait_flows(page, {'grid:house': 1800})
        samples = page.evaluate("""async () => {
          const THREE=await import('three'),v=window.__twin,r=v.renderer3,gl=r.getContext();
          v.scene.updateMatrixWorld(true);
          const visible=o=>{for(let p=o;p;p=p.parent)if(!p.visible)return false;return o.material?.visible!==false;};
          const roofs=[],saved=[];let core;
          v.groups.roof.traverse(o=>{if(o.isMesh&&visible(o))roofs.push(o);});
          v.scene.traverse(o=>{if(o.userData.energyRibbon||o.userData.energyRibbonHalo){saved.push([o,o.visible]);
            if(o.userData.energyRibbon==='grid:house')core=o;}});
          if(!core||!roofs.length)throw Error('The fixture must have a visible grid ribbon and real roofs');
          const roofSet=new Set(roofs),ray=new THREE.Raycaster();ray.layers.enableAll();ray.camera=v.camera;
          const candidates=[];
          // Look through the centre of an actual roof triangle toward a low
          // part of the real ribbon. This proves occlusion rather than merely
          // sampling a crest against the sky. No roof or ribbon is moved.
          for(const t of [.02,.05,.95,.98]){
            const point=core.geometry.parameters.path.getPoint(t);
            for(const roof of roofs){const pos=roof.geometry.attributes.position,index=roof.geometry.index;
              const count=index?index.count:pos.count,step=Math.max(3,Math.floor(count/90)*3);
              for(let i=0;i+2<count;i+=step){
                const centre=new THREE.Vector3();for(let j=0;j<3;j++)centre.add(new THREE.Vector3().fromBufferAttribute(pos,index?index.getX(i+j):i+j));
                centre.multiplyScalar(1/3).applyMatrix4(roof.matrixWorld);
                if(centre.y<=point.y+.3)continue;
                candidates.push({point,position:centre.clone().add(centre.clone().sub(point).normalize().multiplyScalar(20))});
              }
            }
          }
          const read=(x,y)=>{const a=new Uint8Array(4);gl.readPixels(x,y,1,1,gl.RGBA,gl.UNSIGNED_BYTE,a);return Array.from(a.slice(0,3));};
          const hue=v.live.energy().ribbons.find(row=>row.id==='grid:house').hue.map(x=>x*255),results=[];
          try{
            for(const {point,position}of candidates){
              ray.set(position,point.clone().sub(position).normalize());
              const first=ray.intersectObject(v.scene,true).find(hit=>hit.object.isMesh&&visible(hit.object)&&
                !hit.object.userData.energyRibbon&&!hit.object.userData.energyRibbonHalo);
              if(!first||!roofSet.has(first.object)||first.distance>=position.distanceTo(point)-.3)continue;
              v.setCameraState({position:position.toArray(),target:point.toArray()});v.scene.updateMatrixWorld(true);
              const p=point.clone().project(v.camera),w=gl.drawingBufferWidth,h=gl.drawingBufferHeight;
              const x=Math.round((p.x+1)*w/2),y=Math.round((p.y+1)*h/2);
              if(x<5||y<5||x>=w-5||y>=h-5)continue;
              const pixels=[];
              for(let dy=-4;dy<=4;dy++)for(let dx=-4;dx<=4;dx++){
                ray.setFromCamera(new THREE.Vector2(2*(x+dx+.5)/w-1,2*(y+dy+.5)/h-1),v.camera);
                const hit=ray.intersectObject(v.scene,true).find(hit=>hit.object.isMesh&&visible(hit.object)&&
                  !hit.object.userData.energyRibbon&&!hit.object.userData.energyRibbonHalo);
                if(hit&&roofSet.has(hit.object)&&hit.distance<v.camera.position.distanceTo(point)-.3)pixels.push({x:x+dx,y:y+dy});
              }
              for(const[o]of saved)o.visible=false;r.render(v.scene,v.camera);
              for(const pixel of pixels)pixel.roof=read(pixel.x,pixel.y);
              for(const[o,shown]of saved)o.visible=shown;r.render(v.scene,v.camera);
              for(const pixel of pixels){const rgb=read(pixel.x,pixel.y),contrast=Math.max(...rgb.map((c,i)=>Math.abs(c-pixel.roof[i])));
                const hueDistance=Math.hypot(...rgb.map((c,i)=>c-hue[i])),roofHueDistance=Math.hypot(...pixel.roof.map((c,i)=>c-hue[i]));
                if(contrast>=18&&hueDistance<roofHueDistance&&hueDistance<Math.hypot(...rgb.map(c=>c-255)))
                  results.push({rgb,roof:pixel.roof,contrast,hueDistance,roofHueDistance});
              }
              // A camera with confirmed roof-covered pixels must pass; do not
              // search for a camera that happens to escape the old depth mask.
              if(pixels.length)return results;
            }
            throw Error('No roof-covered ribbon pixels found; the scenario must not pass vacuously');
          }finally{for(const[o,shown]of saved)o.visible=shown;r.render(v.scene,v.camera);}
        }""")
        check(len(samples) > 0, ('roof-covered pixels have the ribbon hue instead of the roof colour', samples))
        shot(page, 'energy-ribbon-over-roof.png')
        L.no_errors(served)


def scenario_energy_fan_apexes_and_labels_follow_the_camera():
    served = setup()
    if served is None:
        return
    push_totals(0, -2000, 2500, 500)
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
        page.get_by_role('button', name='Energy', exact=True).click()
        wait_flows(page, {'grid:house': 500, 'grid:battery': 2000})
        for position in ([0, 18, .1], [.5, 16, 8]):
            page.evaluate("""async offset => {
              const THREE=await import('three'),v=window.__twin,rows=v.live.energy().ribbons.filter(r=>r.visible);
              const centre=rows.reduce((sum,r)=>sum.add(new THREE.Vector3().fromArray(r.apex)),new THREE.Vector3()).multiplyScalar(1/rows.length);
              v.setCameraState({position:centre.clone().add(new THREE.Vector3().fromArray(offset)).toArray(),target:centre.toArray()});
            }""", position)
            page.wait_for_timeout(150)
            rows = page.evaluate("""() => {
              const v=window.__twin,rect=v.renderer3.domElement.getBoundingClientRect();v.camera.updateMatrixWorld(true);
              return v.live.energy().ribbons.filter(row=>row.visible).map(row=>{
                const node=document.querySelector('[data-energy-label="'+row.id+'"]'),box=node.getBoundingClientRect();
                const p=v.camera.position.clone().fromArray(row.apex).project(v.camera);
                const x=rect.left+(p.x+1)*rect.width/2,y=rect.top+(1-p.y)*rect.height/2;
                const cx=(box.left+box.right)/2,cy=(box.top+box.bottom)/2;
                const along=[.4,.6,.3,.7,.2,.8,.1,.9].map(t=>{
                  let core;v.scene.traverse(o=>{if(o.userData.energyRibbon===row.id)core=o;});
                  const q=core.geometry.parameters.path.getPoint(t).project(v.camera);
                  return Math.hypot(cx-(rect.left+(q.x+1)*rect.width/2),cy-(rect.top+(1-q.y)*rect.height/2));
                });
                return {id:row.id,visible:!node.hidden&&box.width>0,distance:Math.hypot(cx-x,cy-y),
                  ribbonDistance:Math.min(...along),placement:node.dataset.energyLabelPlacement,
                  rise:row.apex[1]/.3048-Math.max(row.from[2],row.to[2]),apex:row.apex,width:row.width,
                  left:box.left,right:box.right,top:box.top,bottom:box.bottom};
              });
            }""")
            check(len(rows) == 2 and all(r['visible'] for r in rows), ('both grid fan labels are visible', rows))
            check(all(r['distance'] <= 24.01 or r['ribbonDistance'] <= 1 or r['placement'] == 'stack' for r in rows), ('each label follows its own ribbon or uses the visible crowding stack', rows))
            check(all(2-1e-6 <= r['rise'] <= 10+1e-6 for r in rows), ('apexes never exceed 10 ft above their higher endpoint', rows))
            a, b = rows
            separation = sum((x-y)**2 for x, y in zip(a['apex'], b['apex']))**.5
            check(separation >= 2*max(r['width'] for r in rows), ('shared-meter fan separates apexes by two ribbon widths', rows))
            check(not (a['left'] < b['right'] and a['right'] > b['left'] and a['top'] < b['bottom'] and a['bottom'] > b['top']), ('fan labels never stack', rows))
        shot(page, 'energy-gentle-fan-labels.png')
        L.no_errors(served)


SCENARIOS = [scenario_energy_ribbons_labels_and_grid_push,
             scenario_security_attention_camera_and_lock_push,
             scenario_no_programs_on_second_entry_to_either_mode,
             scenario_energy_check_explains_removed_meter,
             scenario_energy_check_warns_about_battery_as_house_and_mapping_repair_shows_ribbon,
             scenario_energy_ribbon_pixels_cover_an_intervening_real_roof,
             scenario_energy_fan_apexes_and_labels_follow_the_camera]

if __name__ == '__main__':
    L.run(SCENARIOS)
