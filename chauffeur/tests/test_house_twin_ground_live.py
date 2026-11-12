"""Terrain browser acceptance for Claude. Written only; NOT run by Codex.

Run from chauffeur/ with HA_BASE_URL unset, under a 300 s outer timeout.
The CPU tests prove numeric geometry separately; this file exercises the actual
lot UI, history, GPU program reuse and both editor/viewer rendering.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import house_editor_model_harness as H

check = H.check


def lot_pixel(page, point, height=0):
    return page.evaluate("""async ([p,h])=>{
      const T=await import('three'),v=window.__twin,r=v.renderer3.domElement.getBoundingClientRect();
      const q=new T.Vector3(p[0]*.3048,h*.3048,-p[1]*.3048).project(v.camera);
      return [r.left+(q.x+1)*r.width/2,r.top+(1-q.y)*r.height/2];
    }""", [point, height])


def scenario_draw_negative_pad_tree_undo_and_program_reuse():
    served = H.serve()
    if served is None:
        return
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, served)
        page.evaluate("""()=>{const v=window.__twin;v.bake?.stop();v.setView('ext');
          v.setCameraState({position:[20*.3048,90*.3048,-124.999*.3048],target:[20*.3048,0,-125*.3048]});}""")
        before = page.evaluate('()=>window.__twin.plan.site.terraces.length')
        page.click('#rail-ground')
        page.locator('#terrain-card').get_by_role('button', name='Add pad', exact=True).click()
        page.locator('#terrain-card').get_by_label('Pad height (ft)', exact=True).fill('-4')
        page.locator('#terrain-card').get_by_label('Blend (ft)', exact=True).fill('6')
        for point in [[12, 117], [28, 117], [28, 133], [12, 133]]:
            page.mouse.click(*lot_pixel(page, point))
        page.locator('#terrain-card').get_by_role('button', name='Finish pad', exact=True).click()
        page.wait_for_function('(n)=>window.__twin.ready&&window.__twin.plan.site.terraces.length===n+1', arg=before)
        heights = page.evaluate("""async()=>{const {groundAt}=await import('../static/twin/twin_ground.js');
          return [groundAt(window.__twin.plan,20,125),groundAt(window.__twin.plan,9,125),groundAt(window.__twin.plan,0,125)];}""")
        check(heights == [-4, -2, 0], ('pad, blend midpoint and datum', heights))
        page.click('#rail-undo')
        page.wait_for_function('(n)=>window.__twin.ready&&window.__twin.plan.site.terraces.length===n', arg=before)
        page.click('#rail-redo')
        page.wait_for_function('(n)=>window.__twin.ready&&window.__twin.plan.site.terraces.length===n+1', arg=before)
        page.evaluate("""async()=>{await window.__twinEditor.op({op:'add_site_item',list:'planting',asset:'Pine Medium',at:[20,125]});}""")
        page.wait_for_function('()=>window.__twin.ready')
        tree_bottom = page.evaluate("""async()=>{const T=await import('three'),v=window.__twin;
          // Since slice 4a a tree sits inside its object wrapper: find it by world position (ft).
          const p=new T.Vector3();let tree=null;v.groups.site.updateMatrixWorld(true);
          v.groups.site.traverse(o=>{if(tree||(o.name!=='Tree'&&o.constructor.name!=='Tree'))return;o.getWorldPosition(p);
            if(Math.abs(p.x/.3048-20)<.5&&Math.abs(p.z/.3048+125)<.5)tree=o;});
          if(!tree)throw Error('tree on pad was not drawn');const bounds=new T.Box3().setFromObject(tree);return bounds.min.y/.3048;}""")
        check(abs(tree_bottom + 4) < .02, ('tree rests on -4 ft pad', tree_bottom))
        # Warm the first terrain edit before counting actual program creations.
        page.evaluate("""async()=>{const v=window.__twin;await v.renderer3.compileAsync(v.scene,v.camera);v.render();
          const gl=v.renderer3.getContext(),create=gl.createProgram.bind(gl);window.__groundPrograms=0;
          gl.createProgram=(...args)=>{window.__groundPrograms++;return create(...args);};}""")
        pad_id = page.evaluate('()=>window.__twin.plan.site.terraces.at(-1).id')
        page.evaluate("([id])=>window.__twinEditor.terrain.choose('terraces',id)", [pad_id])
        page.locator('#terrain-card').get_by_role('button', name='Up 0.5 ft', exact=True).click()
        page.wait_for_function('()=>window.__twin.ready&&window.__twin.plan.site.terraces.at(-1).height===-3.5')
        H.settle(page, 5)
        check(page.evaluate('()=>window.__groundPrograms') == 0, 'second terrain rebuild creates no GPU programs')


def scenario_auto_foundation_undo_and_viewer():
    served = H.serve()
    if served is None:
        return
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, served)
        bid = page.evaluate("""async()=>{const {buildingFootprint}=await import('../static/twin/twin_ground.js');
          const v=window.__twin,b=v.plan.buildings.find(b=>b.id==='pool-house')||v.plan.buildings[0];
          const a=(b.rotation||0)*Math.PI/180,p=b.position||[0,0],ps=buildingFootprint(b).map(([x,y])=>[p[0]+x*Math.cos(a)-y*Math.sin(a),p[1]+x*Math.sin(a)+y*Math.cos(a)]);
          const xs=ps.map(p=>p[0]),ys=ps.map(p=>p[1]),x0=Math.min(...xs)-2,x1=Math.max(...xs)+2,y0=Math.min(...ys)-2,y1=Math.max(...ys)+2;
          await window.__twinEditor.op({op:'add_pad',polygon:[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],height:-4});return b.id;}""")
        page.evaluate('id=>window.__editor.clickPiece(id,id)', bid)
        page.locator('#piece-card').get_by_label('Foundation mode', exact=True).select_option('auto')
        page.wait_for_function('(id)=>window.__twin.ready&&window.__twin.plan.buildings.find(b=>b.id===id).foundation.mode==="auto"', arg=bid)
        base = page.evaluate("id=>Object.values(window.__twin.groups.levels).flatMap(g=>g.children).find(g=>g.userData.buildingId===id).position.y", bid)
        check(abs(base + 4) < .001, ('auto foundation follows the pad', base))
        page.click('#rail-undo')
        page.wait_for_function('(id)=>window.__twin.ready&&window.__twin.plan.buildings.find(b=>b.id===id).foundation.mode==="fixed"', arg=bid)
        page.click('#rail-redo')
        page.wait_for_function('(id)=>window.__twin.ready&&window.__twin.plan.buildings.find(b=>b.id===id).foundation.mode==="auto"', arg=bid)
        page.goto(served.url('house/twin?tier=low&test=1'))
        page.wait_for_function('()=>window.__twin?.ready', timeout=90000)
        check(page.evaluate("id=>Object.values(window.__twin.groups.levels).flatMap(g=>g.children).find(g=>g.userData.buildingId===id).position.y", bid) == -4, 'viewer uses the same foundation base')
        check(page.evaluate("()=>{let n=0;window.__twin.groups.site.traverse(o=>{if(o.userData.terrain)n++;});return n>0;}"), 'viewer draws the sampled terrain')


def scenario_layered_pads_order_and_history():
    served = H.serve()
    if served is None:
        return
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, served)
        page.evaluate("""()=>{const v=window.__twin;v.bake?.stop();v.setView('ext');
          v.setCameraState({position:[24*.3048,90*.3048,-124.999*.3048],target:[24*.3048,0,-125*.3048]});}""")
        shelf = page.locator('#terrain-card')
        ids = []
        for height, polygon in [(-4, [[12, 117], [28, 117], [28, 133], [12, 133]]),
                                (0, [[24, 119], [36, 119], [36, 131], [24, 131]])]:
            before = page.evaluate('()=>window.__twin.plan.site.terraces.length')
            page.click('#rail-ground')
            shelf.get_by_role('button', name='Add pad', exact=True).click()
            shelf.get_by_label('Pad height (ft)', exact=True).fill(str(height))
            shelf.get_by_label('Blend (ft)', exact=True).fill('6')
            for point in polygon:
                surface = page.evaluate("""async p=>{const {groundAt}=await import('../static/twin/twin_ground.js');
                  return groundAt(window.__twin.plan,...p);}""", point)
                page.mouse.click(*lot_pixel(page, point, surface))
            shelf.get_by_role('button', name='Finish pad', exact=True).click()
            page.wait_for_function('(n)=>window.__twin.ready&&window.__twin.plan.site.terraces.length===n+1', arg=before)
            ids.append(page.evaluate('()=>window.__twin.plan.site.terraces.at(-1).id'))
        heights = page.evaluate("""async()=>{const {groundAt}=await import('../static/twin/twin_ground.js');
          return Array.from({length:601},(_,i)=>groundAt(window.__twin.plan,18+i*.01,125));}""")
        check(abs(heights[0] + 4) < .01 and abs(heights[-1]) < .01, ('yard to patio heights', heights[0], heights[-1]))
        check(all(-4.001 <= h <= .001 for h in heights), 'band stays between the two pad heights')
        check(all(b >= a-.001 for a, b in zip(heights, heights[1:])), 'patio slopes into yard monotonically without a datum dip')
        shelf.get_by_role('button', name=f'Pad {ids[1]}: 0 ft', exact=True).click()
        layers = page.evaluate('()=>window.__twin.plan.site.terraces.length')
        check(shelf.get_by_text(f'Layer {layers} of {layers}', exact=True).is_visible(), 'shelf shows stored order')
        shelf.get_by_role('button', name='Send back', exact=True).click()
        page.wait_for_function('(id)=>window.__twin.ready&&window.__twin.plan.site.terraces.at(-1).id===id', arg=ids[0])
        def overlap_height():
            return page.evaluate("""async()=>{const {groundAt}=await import('../static/twin/twin_ground.js');return groundAt(window.__twin.plan,26,125);}""")
        check(abs(overlap_height()+4) < .01, 'Send back makes the yard the top surface')
        check(shelf.get_by_text(f'Layer {layers-1} of {layers}', exact=True).is_visible(), 'order label updates after save')
        page.click('#rail-undo')
        page.wait_for_function('(id)=>window.__twin.ready&&window.__twin.plan.site.terraces.at(-1).id===id', arg=ids[1])
        check(abs(overlap_height()) < .01, 'undo restores the patio on top')
        page.click('#rail-redo')
        page.wait_for_function('(id)=>window.__twin.ready&&window.__twin.plan.site.terraces.at(-1).id===id', arg=ids[0])
        check(abs(overlap_height()+4) < .01, 'redo restores the yard on top')
        # When Claude runs this, retain the rendered UI proof beside the test output.
        page.screenshot(path=str(Path(__file__).with_name('terrain-layers-live.png')))


if __name__ == '__main__':
    H.run([scenario_draw_negative_pad_tree_undo_and_program_reuse, scenario_auto_foundation_undo_and_viewer,
           scenario_layered_pads_order_and_history])
