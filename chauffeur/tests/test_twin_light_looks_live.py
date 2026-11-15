"""Render the shared light-look editors in dark Chromium at the wall viewport."""
from pathlib import Path
import house_twin_live_harness as L

OUTPUT = Path(__file__).resolve().parents[2] / '.superpowers/effect-colours'
ENTITY = 'light.ceiling_light'
DEVICE = 'dev-k-ceiling'


def scenario_parent_ring_and_room_editor_and_kiosk_previews():
    served = L.serve()
    if served is None:
        raise AssertionError('Chromium is required for light-look visual verification')
    L.reset()
    from services import twin_light_looks
    L.FAKE.states[ENTITY].update(state='on', attributes={
        'friendly_name': 'Ceiling light', 'effect_list': ['Caribbean', 'Party', 'Deep Blue'],
        'effect': 'Caribbean', 'supported_color_modes': ['rgb'], 'rgb_color': [0, 255, 0], 'brightness': 255})
    twin_light_looks.save({'entity_id': ENTITY, 'look': {'effects': {'caribbean': [[255, 0, 0], [0, 0, 255]]}}})
    with served.browser(launch_args=L.GPU_ARGS, color_scheme='dark', has_touch=True) as page:
        L.H.signed_in(page)
        L.goto_retry(page, served.url('house/twin?tier=low&test=1'))
        page.wait_for_function('() => !!window.__twin?.live', timeout=90000)
        L.wait_markers(page)
        L.aim_kitchen(page)
        page.evaluate('(id) => window.__twin.live.openRing(window.__twin.live.marker(id))', DEVICE)
        edits = page.locator('[data-ring] [data-ring-part="effect-look-edit"]')
        assert edits.count() == 3
        bounds = edits.first.bounding_box()
        assert bounds['width'] >= 44 and bounds['height'] >= 44
        edits.first.click()
        editor = page.locator('[data-ring] [data-ring-part="look-editor"]')
        editor.wait_for(state='visible')
        assert editor.locator('[data-ring-part="look-wheel"]').count() == 2
        page.screenshot(path=str(OUTPUT / 'light-looks-ring-dark.png'))
        before = len(L.FAKE.calls)
        editor.locator('[data-ring-part="look-wheel"]').first.press('Home')
        editor.locator('[data-ring-part="look-done"]').click()
        editor.wait_for(state='detached')
        assert len(L.FAKE.calls) == before
        assert twin_light_looks.read()[ENTITY]['effects']['caribbean'] == [[255, 0, 0], [0, 0, 255]]
        page.evaluate('([building, room]) => window.__twin.live.openRoom(building, room)', [L.POOL, L.KITCHEN])
        switch = page.locator('#twin-room-panel [data-device-id="dev-k-coffee"]')
        switch.locator('[data-ring-part="fixed-look-edit"]').click()
        fixed = switch.locator('[data-ring-part="look-editor"]')
        assert fixed.locator('[data-ring-part="look-wheel"]').count() == 1
        assert fixed.locator('[data-ring-part="look-add"]').count() == 0
        page.screenshot(path=str(OUTPUT / 'light-looks-room-dark.png'))
        L.no_errors(served)
    with served.browser(launch_args=L.GPU_ARGS, color_scheme='dark', has_touch=True) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
        L.aim_kitchen(page)
        page.evaluate('(id) => window.__twin.live.openRing(window.__twin.live.marker(id))', DEVICE)
        assert page.locator('[data-ring] [data-ring-part="effect-look-dot"]').count() == 3
        assert page.locator('[data-ring] [data-ring-part="effect-look-edit"]').count() == 0
        page.screenshot(path=str(OUTPUT / 'light-looks-kiosk-dark.png'))
        L.no_errors(served)


if __name__ == '__main__':
    L.run([scenario_parent_ring_and_room_editor_and_kiosk_previews])
