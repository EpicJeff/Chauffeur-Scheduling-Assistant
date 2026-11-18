"""Browser acceptance for paver paths: drawing, the card, undo, and a look on High."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import house_editor_model_harness as H
from test_house_twin_ground_live import lot_pixel

DEFAULTS = {'layout': 'grid', 'length_in': 24, 'width_in': 24, 'gap_in': 3, 'rotation': 0, 'edge': 'whole', 'joint': 'grass'}
PAVER_MESHES = """()=>{const ids=new Set();window.__twin.scene.traverse(o=>{if(!o.isMesh)return;
  for(const r of o.userData.snapRanges||[o.userData])if(r.part==='pavers')ids.add(r.pieceId);});return [...ids];}"""
IDS = '(' + PAVER_MESHES + ')()'


def seed(plan):
    plan['site'].update(beds=[], edges=[], fire_pit=None, fence=None, hardscape=[
        {'id': 'pv-grid', 'kind': 'path', 'points': [[8, 110], [30, 110]], 'width': 4, 'material': 'paving',
         'corner': 'rounded', 'smooth': False, 'edging': 'none', 'pavers': dict(DEFAULTS)},
        {'id': 'pv-herring', 'kind': 'path', 'points': [[8, 104], [30, 104]], 'width': 4, 'material': 'paving',
         'corner': 'rounded', 'smooth': False, 'edging': 'none',
         'pavers': {**DEFAULTS, 'layout': 'herringbone', 'length_in': 8, 'width_in': 4, 'gap_in': .5, 'edge': 'cut', 'joint': 'sand'}}])
    return plan


def meshes(page):
    return page.evaluate(IDS)


def scenario_paver_path_draw_card_and_undo():
    served = H.serve(mutate=seed)
    if served is None:
        raise RuntimeError('Browser acceptance needs the installed live harness.')
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, served)
        page.evaluate("""()=>{const v=window.__twin;v.bake?.stop();v.setView('ext');
          v.setCameraState({position:[20*.3048,80*.3048,-124.999*.3048],target:[20*.3048,0,-125*.3048]});}""")
        page.wait_for_function(IDS + '.length===2', timeout=30000)
        page.click('#rail-ground')
        page.locator('#terrain-card').get_by_role('button', name='Paver path', exact=True).click()
        page.keyboard.down('Shift')
        for p in [[25, 118], [29, 122], [26, 128], [30, 134]]:
            page.mouse.click(*lot_pixel(page, p, 0))
        page.keyboard.up('Shift')
        page.keyboard.press('Enter')
        page.wait_for_function('window.__twin.plan.site.hardscape.length===3')
        drawn = H.model()['site']['hardscape'][2]
        H.check(drawn.get('pavers') == DEFAULTS, f'A new Paver path did not get the default pavers: {drawn.get("pavers")}')
        page.wait_for_function(IDS + f'.includes({drawn["id"]!r})', timeout=30000)
        page.locator('#terrain-card').get_by_role('button', name='Path / hardscape 3', exact=True).click()
        card = page.locator('#piece-card')
        H.check(card.get_by_label('Surface', exact=True).input_value() == 'pavers', 'The card does not show Pavers')
        card.get_by_label('Layout', exact=True).select_option('herringbone')
        page.wait_for_function("window.__twin.plan.site.hardscape[2].pavers?.layout==='herringbone'")
        H.check(H.model()['site']['hardscape'][2]['pavers'] == {**DEFAULTS, 'layout': 'herringbone'}, 'Layout change sent more than the layout')
        page.click('#rail-undo')
        page.wait_for_function("window.__twin.plan.site.hardscape[2].pavers?.layout==='grid'")
        card = page.locator('#piece-card')
        card.get_by_label('Surface', exact=True).select_option('solid')
        page.wait_for_function('!window.__twin.plan.site.hardscape[2].pavers')
        page.wait_for_function(IDS + f'.length===2 && !{IDS}.includes({drawn["id"]!r})', timeout=30000)
        H.check('pavers' not in H.model()['site']['hardscape'][2], 'Solid did not remove the pavers')
        page.click('#rail-undo')
        page.wait_for_function(IDS + f'.includes({drawn["id"]!r})', timeout=30000)


def scenario_paver_paths_look_on_high():
    served = H.serve(mutate=seed)
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, served)
        page.wait_for_function(IDS + ".includes('pv-grid')", timeout=30000)
        page.evaluate("""()=>{const v=window.__twin;v.bake?.stop();v.setView('ext');
          v.setCameraState({position:[14*.3048,9*.3048,-97*.3048],target:[20*.3048,0,-107*.3048]});}""")
        H.settle(page, 20)
        out = os.environ.get('PAVER_SHOTS')
        if out:
            page.screenshot(path=str(Path(out) / 'paver_paths_high.png'))


if __name__ == '__main__':
    H.run([scenario_paver_path_draw_card_and_undo, scenario_paver_paths_look_on_high])
