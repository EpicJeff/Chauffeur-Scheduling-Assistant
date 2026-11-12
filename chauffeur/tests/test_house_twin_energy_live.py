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


def ribbon_midpoint_pixels(page):
    """Compare actual WebGL pixels with/without ribbons at each world crest.

    Reading the same frame twice avoids judging glow against a guessed sky
    colour. DOM labels cannot contaminate these framebuffer samples.
    """
    return page.evaluate("""() => {
      const v=window.__twin,r=v.renderer3,gl=r.getContext(),canvas=r.domElement;
      v.camera.updateMatrixWorld(true);
      const roof=[];
      for(const[id,surface]of v.roofSurfaces){const b=v.plan.buildings.find(b=>b.id===id),a=(b.rotation||0)*Math.PI/180;
        for(let i=0;i<surface.positions.length;i+=3){const[x,y,z]=surface.positions.slice(i,i+3),p=v.camera.position.clone();
          p.set(((b.position?.[0]||0)+Math.cos(a)*x-Math.sin(a)*y)*.3048,(z+(b.base||0))*.3048,
            -((b.position?.[1]||0)+Math.sin(a)*x+Math.cos(a)*y)*.3048);roof.push(p.project(v.camera).y);}}
      const top=Math.max(...roof),rect=canvas.getBoundingClientRect(),w=gl.drawingBufferWidth,h=gl.drawingBufferHeight;
      const samples=v.live.energy().ribbons.filter(x=>x.visible).map(row=>{
        const p=v.camera.position.clone().fromArray(row.midpoint).project(v.camera);
        const x=Math.round((p.x+1)*w/2),y=Math.round((p.y+1)*h/2),radius=8;
        const path=row.path.map(at=>v.camera.position.clone().fromArray(at).project(v.camera));
        const sign=Math.sign(path.at(-1).x-path[0].x),monotonic=sign!==0&&path.slice(1).every((p,i)=>(p.x-path[i].x)*sign>=-1e-7);
        return {id:row.id,hue:row.hue.map(c=>c*255),monotonic,above:p.y>top,x:Math.max(0,Math.min(w-17,x-radius)),y:Math.max(0,Math.min(h-17,y-radius)),p:p.toArray()};});
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
        return {id:s.id,monotonic:s.monotonic,above:s.above,onscreen:Math.abs(s.p[0])<1&&Math.abs(s.p[1])<1&&Math.abs(s.p[2])<1,...selected};});
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
            samples = ribbon_midpoint_pixels(page)
            check(len(samples) == 3 and all(s['above'] and s['onscreen'] for s in samples), (preview, 'crests project above all roof vertices', samples))
            # Capped source colours can be darker than a day sky. The old >=230
            # white-peak test contradicted hue preservation; require contrast
            # plus distance to the actual source hue instead.
            check(all(s['peak'] >= 90 and s['contrast'] >= 18 for s in samples), (preview, 'ribbon colour contrasts against its actual background', samples))
            check(all(s['hueDistance'] < s['whiteDistance'] for s in samples), (preview, 'midpoint colour is closer to its source hue than white', samples))
            # Actual anchors take precedence over the old screen-space bus nudges.
            shot(page, 'energy-ribbons-' + preview + '.png')
        labels = page.locator('.twin-climate-labels span:visible').evaluate_all("nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};})")
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


SCENARIOS = [scenario_energy_ribbons_labels_and_grid_push,
             scenario_security_attention_camera_and_lock_push,
             scenario_no_programs_on_second_entry_to_either_mode]

if __name__ == '__main__':
    L.run(SCENARIOS)
