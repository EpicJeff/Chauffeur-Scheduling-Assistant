"""Yard-shape browser acceptance. WRITTEN ONLY; do not run in the Codex job."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import house_editor_model_harness as H
from test_house_twin_ground_live import lot_pixel


def seed_yard(plan):
    plan['site'].update(
        hardscape=[{'id': 'yard-patio', 'polygon': [[12, 117], [28, 117], [28, 133], [12, 133]]}],
        pool={'id': 'yard-pool', 'polygon': [[32, 117], [40, 117], [40, 133], [32, 133]], 'depth': 5, 'coping': 1},
        planting=[{'id': 'yard-tree', 'kind': 'tree', 'preset': 'Pine Medium', 'height': 20, 'seed': 1, 'at': [6, 125]}])
    return plan


def scenario_patio_ring_scale_corner_three_undos_pool_and_tree():
    served = H.serve(mutate=seed_yard)
    if served is None:
        raise RuntimeError('Browser acceptance needs the installed live harness.')
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, served)
        page.evaluate("""()=>{const v=window.__twin;v.bake?.stop();v.setView('ext');
          v.setCameraState({position:[20*.3048,80*.3048,-124.999*.3048],target:[20*.3048,0,-125*.3048]});}""")
        page.click('#rail-ground')
        page.locator('#terrain-card').get_by_role('button', name='Path / hardscape 1', exact=True).click()
        page.locator('#piece-card').get_by_label('Angle (degrees)', exact=True).wait_for()
        original = copy.deepcopy(H.model()['site']['hardscape'][0])

        def handle(kind):
            return page.evaluate('(kind)=>window.__twinEditor.handles().find(h=>h.kind===kind).at', kind)

        def drag(start, end):
            page.mouse.move(*lot_pixel(page, start[:2], start[2]))
            page.mouse.down()
            page.mouse.move(*lot_pixel(page, end[:2], end[2]), steps=12)
            page.mouse.up()
            H.settle(page)

        # Count program creations during handle movement, after warming.
        page.evaluate("""async()=>{const v=window.__twin;await v.renderer3.compileAsync(v.scene,v.camera);
          const gl=v.renderer3.getContext(),create=gl.createProgram.bind(gl);window.__yardPrograms=0;
          gl.createProgram=(...args)=>{window.__yardPrograms++;return create(...args);};}""")
        start = handle('site_rotate'); radius = start[0] - 20
        drag(start, [20 + radius / 2**.5, 125 + radius / 2**.5, start[2]])
        page.wait_for_function('window.__twin.plan.site.hardscape[0].rotation===45')
        H.check(page.evaluate('window.__yardPrograms') == 0, 'Rotating the patio compiled a shader')
        start = handle('site_scale')
        drag(start, [20 + (start[0] - 20) * 1.2, 125 + (start[1] - 125) * 1.2, start[2]])
        page.wait_for_function('Math.abs(window.__twin.plan.site.hardscape[0].polygon[0][1]-(125-8*2**.5*1.2))<.02')
        start = handle('site_vertex')
        drag(start, [start[0] + 1, start[1], start[2]])
        H.check(H.model()['site']['hardscape'][0]['polygon'] != original['polygon'], 'Corner did not move')
        for _ in range(3):
            before = H.model()['site']['hardscape'][0]['polygon']
            page.click('#rail-undo')
            page.wait_for_function('(before)=>JSON.stringify(window.__twin.plan.site.hardscape[0].polygon)!==JSON.stringify(before)', arg=before)
        H.check(H.model()['site']['hardscape'][0] == original, 'Three undos did not restore the original patio')
        page.click('#rail-ground')
        page.locator('#terrain-card').get_by_role('button', name='Pool 1', exact=True).click()
        depth = page.locator('#piece-card').get_by_label('Pool depth (ft)', exact=True)
        depth.fill('6'); depth.press('Tab')
        page.wait_for_function('window.__twin.plan.site.pool.depth===6')
        H.check(H.model()['site']['pool']['depth'] == 6, 'Pool depth did not persist')
        # Use the shared object pick path to reach the tree's size control.
        page.evaluate("()=>window.__editor.clickPiece('yard-tree',null)")
        start = handle('object_scale')
        drag(start, [6 + (start[0] - 6) * 1.5, 125 + (start[1] - 125) * 1.5, start[2]])
        page.wait_for_function('Math.abs(window.__twin.plan.site.planting[0].scale-1.5)<.01')
        page.screenshot(path=str(Path(__file__).with_name('yard-shapes-live.png')))


if __name__ == '__main__':
    H.run([scenario_patio_ring_scale_corner_three_undos_pool_and_tree])
