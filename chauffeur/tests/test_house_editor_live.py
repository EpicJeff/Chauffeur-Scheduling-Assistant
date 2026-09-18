"""House editor tasks, porch placement and responsive layout in Chromium."""
import os
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='house_editor_'))
from live_app import live_app


def scenario_house_editor_tasks_and_layout():
    served = live_app()
    if served is None:
        return
    from services import storage
    storage.add_member({'id': 'editor-parent', 'name': 'Editor Parent', 'role': 'parent', 'status': 'active'})
    token = storage.create_member_token('editor-parent')
    with served.browser() as page:
        page.add_init_script('localStorage.setItem("chauffeur_member_token", ' + json.dumps(token) + ')')
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.set_viewport_size({'width': 1600, 'height': 1100})
        page.goto(served.url('config'))
        page.wait_for_function("document.body._x_dataStack && document.body._x_dataStack[0].facadeDraft")
        page.evaluate("document.body._x_dataStack[0].activeTab = 'family'")
        home = page.locator('#home')
        home.scroll_into_view_if_needed()
        nav = home.get_by_role('navigation', name='House editing tasks')
        assert nav.get_by_role('button').count() == 6
        for task in ['Walls & colours', 'Windows & doors', 'Roof details', 'Second story', 'Porch']:
            nav.get_by_role('button', name=task, exact=True).click()
            assert nav.get_by_role('button', name=task, exact=True).get_attribute('aria-pressed') == 'true'
        home.get_by_role('button', name='Slot 11:', exact=False).click()
        home.locator('select[x-model="facadeCell.porch.roof"]').select_option('mixed')
        page.wait_for_function("document.body._x_dataStack[0].facadeDraft.ground.some(g => g.kind === 'porch' && g.roof === 'mixed')")
        start = home.get_by_label('Gable starting slot')
        assert start.is_visible()
        last = start.locator('option').last.get_attribute('value')
        start.select_option(last)
        page.wait_for_function("(last) => document.body._x_dataStack[0].facadeDraft.ground.some(g => g.kind === 'porch' && g.slot + g.gable_offset === Number(last))", arg=last)
        assert start.input_value() == last
        assert not home.locator('select[x-model="facadeCell.ground.kind"]').is_visible()
        nav.get_by_role('button', name='House shape', exact=True).click()
        home.locator('select[x-model="facadeDraft.blocks.garage.orientation"]:visible').select_option('side')
        page.wait_for_function("document.body._x_dataStack[0].facadeDraft.blocks.garage.side_door")
        home.get_by_label('Door style').filter(visible=True).select_option('glass')
        page.wait_for_function("document.body._x_dataStack[0].facadeDraft.blocks.garage.side_door.style === 'glass'")
        home.get_by_label('Add a third bay (separate single door)').filter(visible=True).check()
        page.wait_for_function("document.body._x_dataStack[0].facadeDraft.blocks.garage.side_door.projection === 1.8")
        home.get_by_label('Third bay shape (behind main door)').filter(visible=True).select_option('0')
        page.wait_for_function("document.body._x_dataStack[0].facadeDraft.blocks.garage.side_door.projection === 0")
        home.get_by_label('Third bay shape (behind main door)').filter(visible=True).select_option('2.8')
        home.get_by_label('Garage door colour').filter(visible=True).select_option('white')
        home.get_by_label('Distance from front corner').filter(visible=True).select_option('2')
        page.wait_for_function("document.body._x_dataStack[0].facadeDraft.blocks.garage.side_door.third_bay && document.body._x_dataStack[0].facadeDraft.blocks.garage.door_colour === 'white' && document.body._x_dataStack[0].facadeDraft.blocks.garage.side_door.front_setback === 2")
        home.get_by_role('button', name='Preview in 3D', exact=True).click()
        page.wait_for_function("document.body._x_dataStack[0].facadePreviewToken")
        page.frame_locator('#facade-preview-frame').locator('#room canvas').wait_for(timeout=30000)
        assert not page.frame_locator('#facade-preview-frame').locator('nav').is_visible()
        nav.get_by_role('button', name='Porch', exact=True).click()
        shots = os.environ.get('HOUSE_SHOTS')
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(shots, 'editor-desktop.png')))
        page.set_viewport_size({'width': 390, 'height': 844})
        home.scroll_into_view_if_needed()
        box = home.bounding_box()
        assert box and box['width'] <= 390, box
        assert home.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), 'editor overflows phone width'
        assert start.is_visible()
        if shots:
            start.scroll_into_view_if_needed()
            page.screenshot(path=str(Path(shots, 'editor-mobile.png')))
        # Existing account-scope controls outside #home lack initial Alpine state.
        unexpected = [e for e in errors if e not in ('scopeTuneOpen is not defined', 'scopeMeta is not defined')]
        assert not unexpected, unexpected
        print('House editor task navigation, gable placement and responsive layout passed')


if __name__ == '__main__':
    scenario_house_editor_tasks_and_layout()
