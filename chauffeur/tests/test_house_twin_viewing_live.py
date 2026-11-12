"""Viewing acceptance in real Chromium. Written here; intentionally NOT run by Codex.

Uses the real household fixture, panel auth and fake HA in house_twin_live_harness.
Run from chauffeur/ with HA_BASE_URL unset, under a 300-second outer timeout.
TWIN_VIEWING_OUTPUT writes zoom-exterior.png, zoom-floor.png and peel.png.
The foreground scenario moves only the in-memory rendered detached building so
the fixture always supplies a blocker within the exterior zoom threshold.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import house_twin_live_harness as L

H = L.H
check = L.check

GEOMETRY = r"""() => {
  const v=window.__twin;
  const b=[...v.plan.buildings].sort((a,b)=>b.levels.length-a.levels.length)[0];
  const levels=[...b.levels].sort((a,b)=>a.elevation-b.elevation);
  const points=b.walls.flatMap(w=>[w.from,w.to]);
  const a=(b.rotation||0)*Math.PI/180, c=Math.cos(a), s=Math.sin(a);
  const world=points.map(([x,y])=>[c*x-s*y+(b.position?.[0]||0),s*x+c*y+(b.position?.[1]||0)]);
  const xs=world.map(p=>p[0]),ys=world.map(p=>p[1]);
  const x=(Math.min(...xs)+Math.max(...xs))/2,y=(Math.min(...ys)+Math.max(...ys))/2;
  const span=Math.max(12,Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys));
  const box=v.groups.levels[`${b.id}:${levels[0].id}`];box.updateWorldMatrix(true,true);
  // The generator's local group records ground + foundation in lot feet.
  const base=box.children.find(g=>g.userData.buildingId===b.id)?.position.y||0;
  return {building:b.id,levels:levels.map(l=>({key:`${b.id}:${l.id}`,elevation:l.elevation,cut:Math.max(1,(l.ceiling||8)-4)})),
    x,y,span,height:base+levels[0].elevation+.1,base};
}"""


def open_view(page, served):
    L.reset()
    L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
    page.evaluate("() => {const v=window.__twin;v.bake?.stop();v.setTime('day');}")
    page.wait_for_timeout(350)
    return page.evaluate(GEOMETRY)


def dolly(page, geometry, ratio):
    page.evaluate("""([g,r]) => {
      const v=window.__twin;
      v.controls.target.set(g.x*.3048,g.height*.3048,-g.y*.3048);
      v.camera.position.set(g.x*.3048,(g.height+g.span*r)*.3048,-g.y*.3048);
      v.controls.update();v.render();
    }""", [geometry, ratio])
    page.wait_for_timeout(300)


def roof_opacity(page, bid):
    return page.evaluate("""id => {
      let alpha=null;
      window.__twin.groups.roof.children.find(g=>g.userData.buildingId===id).traverse(o=>{
        if(o.isMesh&&!o.layers.isEnabled(31))alpha??=o.material.opacity;
      });return alpha;
    }""", bid)


def shot(page, name):
    output = os.environ.get('TWIN_VIEWING_OUTPUT')
    if output:
        path = Path(output)
        path.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path / name), full_page=True)


# Read pixels synchronously after render (the canvas does not preserve its buffer).
# World-space triangle samples keep these checks independent of screenshot framing.
PIXEL_CHECK = r"""async ({kind,geometry:g}) => {
  const T=await import('three'),v=window.__twin,renderer=v.renderer3,gl=renderer.getContext();
  const key=v.state.view,level=v.groups.levels[key],w=gl.drawingBufferWidth,h=gl.drawingBufferHeight;
  const canvas=renderer.domElement.getBoundingClientRect(),floorDef=g.levels.find(l=>l.key===key);
  if(!floorDef)throw Error('selected floor is absent from pixel fixture');
  v.scene.updateMatrixWorld(true);v.camera.updateMatrixWorld(true);
  const visible=[];v.scene.traverseVisible(o=>{if(o.isMesh&&!o.layers.isEnabled(31))visible.push(o);});
  const ray=new T.Raycaster(),pixel=new Uint8Array(4),point=new T.Vector3();
  const candidates=[];
  level.traverseVisible(o=>{
    if(!o.isMesh||o.layers.isEnabled(31)||o.material.name!==(kind==='wall'?'viewing_wall_top':'floor'))return;
    const p=o.geometry.attributes.position,n=o.geometry.attributes.normal,ix=o.geometry.index;
    for(let i=0;i<(ix?ix.count:p.count);i+=3){
      const ids=[0,1,2].map(j=>ix?ix.getX(i+j):i+j);
      if(ids.some(j=>n.getY(j)<.9||Math.abs(p.getY(j)-floorDef.elevation-(kind==='wall'?floorDef.cut:0))>1e-3))continue;
      const local=ids.map(j=>new T.Vector3().fromBufferAttribute(p,j));
      // Interior barycentric points stay clear of edges and antialiasing.
      for(const weight of [[1/3,1/3,1/3],[.6,.2,.2],[.2,.6,.2],[.2,.2,.6]]){
        point.set(0,0,0);local.forEach((p,i)=>point.addScaledVector(p,weight[i]));
        const at=point.clone(),ndc=point.applyMatrix4(o.matrixWorld).project(v.camera);
        const x=Math.floor((ndc.x+1)*w/2),y=Math.floor((ndc.y+1)*h/2);
        const cssX=canvas.left+x/w*canvas.width,cssY=canvas.top+(1-y/h)*canvas.height;
        if(x<2||x>=w-2||y<2||y>=h-2||cssY<95||cssY>innerHeight-155||cssX<5||cssX>innerWidth-5||Math.abs(ndc.z)>1)continue;
        ray.setFromCamera(new T.Vector2((x+.5)/w*2-1,(y+.5)/h*2-1),v.camera);
        // Ignore foreground objects for the floor reference: detecting their veil
        // is exactly the comparison below. Keep walls/fixtures of this floor.
        const hits=ray.intersectObjects(kind==='wall'?visible:visible.filter(m=>{
          for(let a=m;a;a=a.parent)if(a===level)return true;return false;
        }),false);
        const hit=hits.find(hit=>!hit.object.material.clippingPlanes?.some(plane=>plane.distanceToPoint(hit.point)<0));
        if(hit?.object!==o)continue;
        candidates.push({x,y,at});
      }
    }
  });
  let chosen=candidates;
  if(kind==='wall'){
    const b=v.plan.buildings.find(b=>key.startsWith(b.id+':'));
    // Test one continuous wall, rather than mixing separate walls in different shadows.
    const walls=b.walls.filter(w=>key===`${b.id}:${w.level}`).sort((a,b)=>
      Math.hypot(...b.to.map((x,i)=>x-b.from[i]))-Math.hypot(...a.to.map((x,i)=>x-a.from[i])));
    chosen=[];
    for(const wall of walls){
      const dx=wall.to[0]-wall.from[0],dy=wall.to[1]-wall.from[1],len=Math.hypot(dx,dy);
      if(len<8)continue;
      const along=candidates.filter(({at})=>{
        const x=at.x-wall.from[0],y=-at.z-wall.from[1],u=(x*dx+y*dy)/len;
        return u>1&&u<len-1&&Math.abs(x*dy-y*dx)/len<wall.thickness+.01;
      });
      const unique=[...new Map(along.map(p=>[`${p.x},${p.y}`,p])).values()];
      if(unique.length>=12){chosen=unique;break;}
    }
  }else chosen=[...new Map(candidates.map(p=>[`${p.x},${p.y}`,p])).values()].slice(0,200);
  const read=()=>{renderer.render(v.scene,v.camera);gl.finish();return chosen.map(({x,y})=>{
    gl.readPixels(x,y,1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);return [...pixel].slice(0,3);
  });};
  const actual=read(),lum=rgb=>.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];
  if(kind==='wall'){
    const lums=actual.map(lum),mean=lums.reduce((a,b)=>a+b,0)/Math.max(1,lums.length);
    return {count:actual.length,mean,std:Math.sqrt(lums.reduce((s,v)=>s+(v-mean)**2,0)/Math.max(1,lums.length)),
      range:Math.max(...lums)-Math.min(...lums)};
  }
  // Same floor, camera, lighting and samples; only the foreground blockers are
  // removed for a clear reference. Restore every visibility flag after reading.
  const saved=[];
  v.scene.traverse(o=>{if(o.userData.viewingTree||(o.userData.buildingId&&o.userData.buildingId!==g.building)){
    saved.push([o,o.visible]);o.visible=false;
  }});
  let reference;
  try{reference=read();}finally{saved.forEach(([o,visible])=>o.visible=visible);v.render();}
  const saturation=rgb=>{const max=Math.max(...rgb);return max?(max-Math.min(...rgb))/max:0;};
  const deltas=actual.map((rgb,i)=>({lum:Math.abs(lum(rgb)-lum(reference[i])),sat:Math.abs(saturation(rgb)-saturation(reference[i]))}));
  return {count:actual.length,referenceMean:reference.reduce((s,rgb)=>s+lum(rgb),0)/Math.max(1,reference.length),
    maxLuminanceDelta:Math.max(...deltas.map(d=>d.lum)),maxSaturationDelta:Math.max(...deltas.map(d=>d.sat))};
}"""


def check_wall_pixels(page, g):
    result = page.evaluate(PIXEL_CHECK, {'kind': 'wall', 'geometry': g})
    print('    Cut wall pixels:', result)
    check(result['count'] >= 12, ('wall top supplies enough distinct pixels', result))
    check(10 < result['mean'] < 245 and result['std'] <= 12 and result['range'] <= 40,
          ('continuous wall top has low pixel variance', result))


def check_floor_pixels(page, g):
    result = page.evaluate(PIXEL_CHECK, {'kind': 'floor', 'geometry': g})
    print('    Peeled floor pixels versus clear reference:', result)
    # A grazing camera can see the cut floor's walls but none of its floor surface; then there
    # is nothing to compare, and the hidden-domain assertion above carries the peel.
    if result['count'] < 20:
        print('    (floor surface not in view at this camera; pixel comparison skipped)')
        return
    check(result['referenceMean'] > 10, ('visible floor reference', result))
    check(result['maxLuminanceDelta'] <= 8 and result['maxSaturationDelta'] <= .06,
          ('peeled floor is not washed out', result))


def place_foreground(page, g):
    return page.evaluate("""async g=>{
      const v=window.__twin,p=structuredClone(v.plan),b=p.buildings.find(b=>b.id!==g.building);
      if(!b)throw Error('fixture needs detached building');
      const points=b.walls.flatMap(w=>[w.from,w.to]),a=(b.rotation||0)*Math.PI/180;
      const xs=points.map(([x,y])=>Math.cos(a)*x-Math.sin(a)*y),ys=points.map(([x,y])=>Math.sin(a)*x+Math.cos(a)*y);
      b.position=[g.x+g.span*.9-(Math.min(...xs)+Math.max(...xs))/2,g.y-(Math.min(...ys)+Math.max(...ys))/2];
      await v.rebuild(p,{preserveYard:true});v.bake?.stop();return b.id;
    }""", g)


def peel_floor(page, g):
    page.locator('[data-view]').filter(has_text='Exterior').click()
    page.locator(f'[data-view="{g["levels"][0]["key"]}"]').click()
    page.evaluate("""g=>{const v=window.__twin;
      v.controls.target.set(g.x*.3048,g.height*.3048,-g.y*.3048);
      v.camera.position.set((g.x+g.span*1.4)*.3048,(g.height+10)*.3048,-g.y*.3048);
      v.controls.update();v.render();}""", g)
    page.wait_for_timeout(350)


def scenario_zoom_fades_roof_and_cuts_top_floor_flat():
    served = L.serve()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        g = open_view(page, served)
        check(len(g['levels']) >= 2, 'fixture has multiple floors')
        dolly(page, g, 2.2)
        check(roof_opacity(page, g['building']) == 1, 'exterior roof is opaque')
        shot(page, 'zoom-exterior.png')
        # A real dolly through the band, without a floor-button call.
        samples = []
        for ratio in (1.7, 1.5, 1.4, 1.3, 1.23):
            dolly(page, g, ratio)
            samples.append(roof_opacity(page, g['building']))
        check(all(b <= a + .001 for a, b in zip(samples, samples[1:])), ('smooth inward fade', samples))
        check(samples[-1] < .001, ('roof reaches zero', samples))
        selected = page.evaluate('() => window.__twin.state.view')
        check(selected == g['levels'][-1]['key'], ('top floor first', selected))
        caps = page.evaluate("""([key,cut])=>{
          let caps=0,slopes=0;
          window.__twin.groups.levels[key].traverse(g=>{
            if(g.userData.viewingWalls!=='cut'||!g.visible)return;
            g.traverse(o=>{if(!o.isMesh||!['siding','interior_wall','viewing_wall_top'].includes(o.material.name))return;
              const p=o.geometry.attributes.position,n=o.geometry.attributes.normal;
              for(let i=0;i<p.count;i+=3)if(n.getY(i)>.1){
                const ys=[i,i+1,i+2].map(j=>p.getY(j));
                if(ys.every(y=>Math.abs(y-cut)<1e-4))caps++;
                else if(Math.max(...ys)-Math.min(...ys)>1e-4)slopes++;
              }
            });
          });return {caps,slopes};
        }""", [selected, g['levels'][-1]['elevation'] + g['levels'][-1]['cut']])
        check(caps['caps'] > 0 and caps['slopes'] == 0, ('flat closed wall tops', caps))
        L.no_errors(served)


def scenario_deeper_zoom_reveals_next_floor_and_out_restores_roof():
    served = L.serve()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        g = open_view(page, served)
        dolly(page, g, 1.23)
        dolly(page, g, .98)
        selected = page.evaluate('() => window.__twin.state.view')
        check(selected == g['levels'][-2]['key'], ('next floor revealed', selected))
        # Finish the upper floor's distance fade before sampling the revealed wall.
        dolly(page, g, .90)
        check_wall_pixels(page, g)
        shot(page, 'zoom-floor.png')
        dolly(page, g, 2.2)
        check(page.evaluate('() => window.__twin.state.view') == 'ext', 'zoom out restores exterior')
        check(roof_opacity(page, g['building']) == 1, 'roof returns')
        L.no_errors(served)


def scenario_floor_button_peels_foreground_detached_building():
    served = L.serve()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        g = open_view(page, served)
        other = place_foreground(page, g)
        peel_floor(page, g)
        check(roof_opacity(page, other) == 0, 'front building fades to zero')
        hidden = page.evaluate("""id=>{
          const v=window.__twin;
          return [...v.groups.roof.children,...v.groups.gableFull.children,...Object.values(v.groups.levels)]
            .filter(g=>g.userData.buildingId===id).every(g=>!g.visible);
        }""", other)
        check(hidden, 'peeled building domains are hidden and cost no draws')
        shot(page, 'peel.png')
        check_floor_pixels(page, g)
        check(page.evaluate('() => window.__twin.viewingState().pinned') == g['levels'][0]['key'], 'floor stays pinned')
        L.no_errors(served)


def scenario_full_zoom_round_trip_compiles_no_new_programs_after_first_pass():
    served = L.serve()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        g = open_view(page, served)
        place_foreground(page, g)
        ratios = (2.2, 1.5, 1.23, .98, .65, .4, .65, .98, 1.23, 1.5, 2.2)
        for ratio in ratios:
            dolly(page, g, ratio)
        peel_floor(page, g)
        page.locator('[data-view]').filter(has_text='Exterior').click()
        page.wait_for_timeout(350)
        page.evaluate("""()=>{const gl=window.__twin.renderer3.getContext(),create=gl.createProgram.bind(gl);
          window.__viewingPrograms=0;gl.createProgram=(...args)=>{window.__viewingPrograms++;return create(...args);};}""")
        before = page.evaluate('() => window.__twin.renderer3.info.programs.length')
        for ratio in ratios:
            dolly(page, g, ratio)
        peel_floor(page, g)
        page.locator('[data-view]').filter(has_text='Exterior').click()
        page.wait_for_timeout(350)
        after = page.evaluate('() => [window.__viewingPrograms,window.__twin.renderer3.info.programs.length]')
        check(after == [0, before], ('no new GPU programs after zoom and peel', before, after))
        L.no_errors(served)


def scenario_low_tier_frame_time():
    served = L.serve()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        g = open_view(page, served)
        samples = {}
        for name, ratio in (('exterior', 2.2), ('floor', .98)):
            dolly(page, g, ratio)
            samples[name] = page.evaluate("""async()=>{
              const v=window.__twin,gl=v.renderer3.getContext();await v.renderer3.compileAsync(v.scene,v.camera);
              for(let i=0;i<5;i++)v.render();gl.finish();
              const start=performance.now();for(let i=0;i<60;i++)v.render();gl.finish();
              return {ms:(performance.now()-start)/60,...v.stats(),renderer:v.renderer};
            }""")
        print('    Low tier GPU frame times:', samples)
        check(all(0 < row['ms'] < float('inf') for row in samples.values()), ('valid Low frame measurements', samples))
        # The real Pi's smoothness remains a device gate; a desktop GPU is not a Pi measurement.
        L.no_errors(served)


SCENARIOS = [scenario_zoom_fades_roof_and_cuts_top_floor_flat,
             scenario_deeper_zoom_reveals_next_floor_and_out_restores_roof,
             scenario_floor_button_peels_foreground_detached_building,
             scenario_full_zoom_round_trip_compiles_no_new_programs_after_first_pass,
             scenario_low_tier_frame_time]

if __name__ == '__main__':
    H.run(SCENARIOS)
