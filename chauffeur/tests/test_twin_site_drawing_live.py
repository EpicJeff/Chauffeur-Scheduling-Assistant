"""Browser acceptance for drawn outlines and paths. WRITTEN ONLY for this job."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import house_editor_model_harness as H
from test_house_twin_ground_live import lot_pixel


def seed(plan):
    plan['site'].update(hardscape=[], beds=[], edges=[], fire_pit=None, fence=None)
    return plan


def scenario_l_patio_curved_paver_path_width_and_undo():
    served = H.serve(mutate=seed)
    if served is None:
        raise RuntimeError('Browser acceptance needs the installed live harness.')
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, served)
        page.evaluate("""()=>{const v=window.__twin;v.bake?.stop();v.setView('ext');
          v.setCameraState({position:[20*.3048,80*.3048,-124.999*.3048],target:[20*.3048,0,-125*.3048]});}""")
        original = copy.deepcopy(H.model()['site']['hardscape'])
        page.click('#rail-ground')
        page.locator('#terrain-card').get_by_role('button', name='Draw patio / hard surface', exact=True).click()
        # Warm the shared drawing material, then count compilations during drawing.
        page.evaluate("""async()=>{const v=window.__twin;await v.renderer3.compileAsync(v.scene,v.camera);
          const gl=v.renderer3.getContext(),create=gl.createProgram.bind(gl);window.__drawPrograms=0;
          gl.createProgram=(...args)=>{window.__drawPrograms++;return create(...args);};}""")
        page.keyboard.down('Shift')
        for p in [[10, 118], [22, 118], [22, 124], [16, 124], [16, 132], [10, 132]]:
            page.mouse.click(*lot_pixel(page, p, 0))
        page.keyboard.up('Shift')
        H.check(page.evaluate('window.__drawPrograms') == 0, 'Drawing compiled a shader')
        page.locator('#terrain-card').get_by_role('button', name='Finish', exact=True).click()
        page.wait_for_function('window.__twin.plan.site.hardscape.length===1')
        H.check(len(H.model()['site']['hardscape'][0]['polygon']) == 6, 'L patio lost its corners')
        page.locator('#terrain-card').get_by_role('button', name='Paver path', exact=True).click()
        page.locator('#terrain-card').get_by_label('Smooth curve', exact=True).select_option('yes')
        page.keyboard.down('Shift')
        for p in [[25, 118], [29, 122], [26, 128], [30, 134]]:
            page.mouse.click(*lot_pixel(page, p, 0))
        page.keyboard.up('Shift')
        page.keyboard.press('Enter')
        page.wait_for_function('window.__twin.plan.site.hardscape.length===2')
        page.locator('#terrain-card').get_by_role('button', name='Path / hardscape 2', exact=True).click()
        width = page.locator('#piece-card').get_by_label('Width (ft)', exact=True)
        width.fill('4'); width.press('Tab')
        page.wait_for_function('window.__twin.plan.site.hardscape[1].width===4')
        path = H.model()['site']['hardscape'][1]
        H.check(path['smooth'] and path['material'] == 'paving' and len(path['points']) == 4, 'Curved paver path did not persist')
        # Shelf width is its own step; each completed drawing is one step.
        page.click('#rail-undo')
        page.wait_for_function('window.__twin.plan.site.hardscape[1].width===3')
        page.click('#rail-undo')
        page.wait_for_function('window.__twin.plan.site.hardscape.length===1')
        page.click('#rail-undo')
        page.wait_for_function('window.__twin.plan.site.hardscape.length===0')
        H.check(H.model()['site']['hardscape'] == original, 'Undo did not restore the yard')
        page.click('#rail-ground')
        page.locator('#terrain-card').get_by_role('button', name='Add fire pit', exact=True).click()
        page.locator('#terrain-card').get_by_label('Shape', exact=True).select_option('rect')
        page.keyboard.down('Shift'); page.mouse.click(*lot_pixel(page, [12, 122], 0)); page.keyboard.up('Shift')
        page.wait_for_function("window.__twin.plan.site.fire_pit?.shape==='rect'")
        pit = H.model()['site']['fire_pit']
        H.check(pit['polygon'] == [[10, 119], [14, 119], [14, 125], [10, 125]], 'Rectangle fire pit dimensions or placement were wrong')
        page.locator('#terrain-card').get_by_role('button', name='Add fire pit', exact=True).click()
        page.locator('#terrain-card').get_by_label('Shape', exact=True).select_option('outline')
        page.keyboard.down('Shift')
        for p in [[24, 120], [30, 120], [30, 124], [27, 128], [24, 126]]:
            page.mouse.click(*lot_pixel(page, p, 0))
        page.keyboard.up('Shift'); page.keyboard.press('Enter')
        page.wait_for_function("Array.isArray(window.__twin.plan.site.fire_pit)&&window.__twin.plan.site.fire_pit.length===2")
        pits = H.model()['site']['fire_pit']
        H.check(pits[0] == pit and pits[1]['shape'] == 'outline' and len(pits[1]['polygon']) == 5, 'Adding an outline pit changed the first pit')
        page.locator('#terrain-card').get_by_role('button', name='Draw fence', exact=True).click()
        page.keyboard.down('Shift')
        for p in [[6, 118], [6, 132], [18, 134]]:
            page.mouse.click(*lot_pixel(page, p, 0))
        page.keyboard.up('Shift'); page.keyboard.press('Enter')
        page.wait_for_function('window.__twin.plan.site.fence?.polyline?.length===3')
        H.check(H.model()['site']['fence']['height'] == 6, 'Fence default height did not persist')
        page.click('#rail-undo'); page.wait_for_function('!window.__twin.plan.site.fence')
        page.click('#rail-undo'); page.wait_for_function("window.__twin.plan.site.fire_pit?.shape==='rect'")
        page.click('#rail-undo'); page.wait_for_function('!window.__twin.plan.site.fire_pit')


if __name__ == '__main__':
    H.run([scenario_l_patio_curved_paver_path_width_and_undo])
