"""Mode key acceptance and screenshots in real Chromium (Claude's browser gate).

Run from chauffeur/: python tests/test_house_twin_mode_key_live.py
Set TWIN_LEGEND_OUTPUT to save desktop/phone default-overview captures, open/closed.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import house_twin_live_harness as L

check = L.check
CARD = '#twin-mode-key'
MODES = ['climate', 'energy', 'security']


def setup():
    served = L.serve()
    if served is None:
        return None
    L.reset()
    L.FAKE.devices[:] = [d for d in L.FAKE.devices if not d['id'].startswith('legend-')]
    from services import twin_glance
    twin_glance.save([{'entity': 'sensor.kitchen_temperature', 'icon': 'thermometer', 'label': 'Kitchen'},
                     {'entity': 'climate.kitchen', 'icon': 'thermometer', 'label': 'Thermostat'}], False)
    for suffix, state in [('front', 'armed_home'), ('back', 'armed_home'), ('garage', 'disarmed')]:
        eid = 'alarm_control_panel.' + suffix
        L.FAKE.devices.append({'id': 'legend-' + suffix, 'name': suffix.title(), 'area_id': 'kitchen',
                               'entities': [(eid, state, {'friendly_name': suffix.title()})]})
        L.FAKE.states[eid] = {'entity_id': eid, 'state': state, 'attributes': {'friendly_name': suffix.title()}}
    return served


def open_view(page, served, wall=True):
    page.emulate_media(color_scheme='dark')
    L.open_twin(page, served, query='tier=low&test=1&panel=true' + ('&kiosk=true' if wall else ''))
    page.evaluate('(modes) => window.__twin.live.setModes(modes)', MODES)


def toggle(page):
    page.get_by_role('button', name='Legend', exact=True).click()


def shot(page, name):
    folder = os.environ.get('TWIN_LEGEND_OUTPUT')
    if folder:
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path / name))


def scenario_closed_by_default_no_legend_text():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        open_view(page, served)
        check(page.locator('#twin-mode-legend').count() == 0, 'old joined legend is removed')
        check(page.locator(CARD).is_hidden(), 'key is closed by default')
        check(page.get_by_role('button', name='Legend').get_attribute('aria-expanded') == 'false', 'collapsed ARIA state')
        check(page.get_by_text('Heating', exact=True).is_hidden(), 'legend rows are off screen until requested')
        L.no_errors(served)


def scenario_button_opens_card_with_three_sections():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        open_view(page, served)
        toggle(page)
        card = page.get_by_role('dialog', name='Legend', exact=True)
        check(card.is_visible(), 'button opens dialog')
        check(card.locator('h2').all_text_contents() == ['Climate', 'Energy', 'Security'], 'three sections in strip order')
        check(card.locator('.twin-key-row').count() == 9, 'swatches include all three keys')
        disclosure = card.locator('details')
        check(not disclosure.evaluate('(n) => n.open'), 'mixed panels start collapsed')
        check(disclosure.locator('summary').inner_text() == 'Alarm · armed home (2 of 3)', 'one most-common alarm chip')
        disclosure.locator('summary').click()
        check('Garage: disarmed' in disclosure.inner_text(), 'full mixed list is reachable')
        page.evaluate("() => window.__twin.live.toggleMode('energy')")
        check(card.locator('h2').all_text_contents() == ['Climate', 'Security'], 'removed mode disappears while open')
        page.evaluate('() => window.__twin.live.setModes([])')
        check(page.locator(CARD).is_hidden(), 'last keyed mode closes card')
        check(page.get_by_role('button', name='Legend', include_hidden=True).is_hidden(), 'no key button without keys')
        L.no_errors(served)


def scenario_escape_closes_and_returns_focus():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        open_view(page, served)
        button = page.get_by_role('button', name='Legend', exact=True)
        # Tab from the last mode reaches the native button; Enter/Space get their
        # real browser activation rather than a synthetic click in a fake DOM.
        page.get_by_role('button', name='Security', exact=True).focus()
        page.keyboard.press('Tab')
        check(button.evaluate('(n) => document.activeElement === n'), 'Legend is in tab order')
        page.keyboard.press('Enter')
        check(page.locator(CARD).is_visible(), 'Enter opens')
        page.get_by_role('link', name='Why no ribbons?', exact=True).focus()
        page.keyboard.press('Escape')
        check(page.locator(CARD).is_hidden(), 'Escape closes')
        check(button.evaluate('(n) => document.activeElement === n'), 'Escape returns focus to button')
        page.keyboard.press('Space')
        check(page.locator(CARD).is_visible(), 'Space opens')
        page.keyboard.press('Space')
        check(page.locator(CARD).is_hidden(), 'Space toggles closed')
        L.no_errors(served)


def scenario_state_survives_reload():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        open_view(page, served)
        toggle(page)
        page.reload()
        page.wait_for_function('() => !!window.__twin?.live')
        check(page.locator(CARD).is_visible(), 'open state survives reload')
        toggle(page)
        page.reload()
        page.wait_for_function('() => !!window.__twin?.live')
        check(page.locator(CARD).is_hidden(), 'closed state survives reload')
        L.no_errors(served)


def scenario_energy_check_reachable():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS, has_touch=True) as page:
        open_view(page, served)
        page.get_by_role('button', name='Legend', exact=True).tap()
        link = page.locator('[data-mode-key="energy"]').get_by_role('link', name='Why no ribbons?', exact=True)
        link.tap()
        panel = page.locator(CARD + ' .twin-energy-check')
        check(panel.is_visible(), 'wall Energy check opens inside Energy')
        check(panel.locator('[data-energy-summary]').is_visible(), 'read-only summary remains readable')
        check(panel.locator('input,select,button').count() == 0, 'wall check has no settings controls')
        check(page.locator(CARD).is_visible(), 'inside tap leaves card open')
        # A real touch on the scene (well away from the central card).
        page.touchscreen.tap(20, 500)
        check(page.locator(CARD).is_hidden(), 'scene tap dismisses on wall')
        L.no_errors(served)


def scenario_card_clear_of_glance_bar():
    served = setup()
    if served is None:
        return
    # Cover both the wall and the regular viewer's lower phone mode-strip offset.
    for wall in (True, False):
        for width, height in ((1920, 1080), (390, 844)):
            with served.browser(launch_args=L.GPU_ARGS) as page:
                page.set_viewport_size({'width': width, 'height': height})
                open_view(page, served, wall=wall)
                page.wait_for_function('() => document.querySelector("#twin-glance")?.getBoundingClientRect().height > 0')
                name = ('wall' if wall else 'viewer') + f'-{width}x{height}'
                shot(page, name + '-closed.png')
                toggle(page)
                box = page.locator(CARD).bounding_box()
                strip = page.locator('#twin-modes').bounding_box()
                glance = page.locator('#twin-glance-home').bounding_box()
                check(box and strip and glance, 'card, strip and chosen glance tiles are drawn')
                check(200 <= box['width'] <= 240 and box['height'] <= height * .6 + 1, ('compact card bounds', box))
                check(box['y'] >= strip['y'] + strip['height'], ('card drops below strip', box, strip))
                check(box['y'] + box['height'] <= glance['y'] - 8, ('card is clear of glance bar', box, glance))
                check(box['x'] >= 0 and box['x'] + box['width'] <= width, ('card stays on phone', box))
                shot(page, name + '-open.png')
                page.locator('[data-mode-key="energy"] a').click()
                page.locator(CARD).evaluate('(n) => n.scrollTop = n.scrollHeight')
                check(page.locator(CARD).evaluate('(n) => n.scrollHeight > n.clientHeight && n.scrollTop > 0'), 'expanded Energy check scrolls')
                box = page.locator(CARD).bounding_box()
                check(box['y'] + box['height'] <= glance['y'] - 8, 'expanded check still clears glance')
                L.no_errors(served)


SCENARIOS = [scenario_closed_by_default_no_legend_text,
             scenario_button_opens_card_with_three_sections,
             scenario_escape_closes_and_returns_focus,
             scenario_state_survives_reload,
             scenario_energy_check_reachable,
             scenario_card_clear_of_glance_bar]

if __name__ == '__main__':
    L.run(SCENARIOS)
