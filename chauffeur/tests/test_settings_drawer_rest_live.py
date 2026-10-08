"""Trips and Map settings drawers, actually clicked (settings-drawer arc, task 14).

Trips: the trip hashtags live in the Trips drawer. Map: Argyle's voice and a
speaker pin for EACH room live in the Map drawer (the announce strip keeps only
the sending controls). No test env has Home Assistant, so the rooms the pins
need are served to the page by a routed /api/announce/rooms.

Set CHF_SHOTS=<dir> to save the screenshots the arc requires.
Run from chauffeur/:  python tests/test_settings_drawer_rest_live.py
"""
import json
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='settings_drawer_rest_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

SHOTS = os.environ.get('CHF_SHOTS')

ROOMS = [
    {'id': 'kitchen', 'name': 'Kitchen', 'pinned': None,
     'candidates': [{'entity_id': 'media_player.kitchen', 'name': 'Kitchen speaker'},
                    {'entity_id': 'media_player.hall', 'name': 'Hall speaker'}]},
    {'id': 'den', 'name': 'Den', 'pinned': None,
     'candidates': [{'entity_id': 'media_player.den', 'name': 'Den speaker'}]},
]


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _visible(page, sel):
    return page.evaluate(
        "(s) => { const el = document.querySelector(s);"
        " return !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden'; }", sel)


def _changed(before, after):
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def seed():
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            T = '[data-settings-for~="trips"]'
            page.goto(served.url('trips'), wait_until='networkidle')
            check(not _visible(page, '#trip-hashtags'), 'trip hashtags still sit under the gallery')
            _shot(page, 'trips-closed-desktop')
            page.click('#page-settings-gear')
            page.wait_for_selector(T + '[data-open]')
            box = page.evaluate("(s) => { const r = document.querySelector(s).getBoundingClientRect(); return [r.width, innerWidth]; }", T)
            check(box[0] == box[1], 'the Trips drawer is trapped by .glass-panel')
            before = storage.get_settings()
            page.fill('#newTripHashtagInput', '#holiday')
            page.click(T + ' [data-add-trip-hashtag]')
            page.wait_for_selector(T + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) == {'trip_hashtags'}, 'hashtags saved more than themselves')
            _shot(page, 'trips-open-desktop')
            page.click(T + ' [aria-label="Close settings"]')

            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('trips'), wait_until='networkidle')
            _shot(page, 'trips-closed-phone')
            page.click('#page-settings-gear')
            page.wait_for_selector(T + '[data-open]')
            _shot(page, 'trips-open-phone')

            # Map, no rooms: the drawer says so.
            page.set_viewport_size({'width': 1300, 'height': 900})
            P = '[data-settings-for~="map"]'
            page.goto(served.url('map'), wait_until='networkidle')
            check(page.query_selector('#announce-pin-toggle') is None, "the strip's gear reveal survived")
            page.click('#page-settings-gear')
            page.wait_for_selector(P + '[data-open]')
            check(_visible(page, P + ' #announce-voice-select'), "Argyle's voice is not in the Map drawer")
            check(_visible(page, P + ' #announce-pins-empty'), 'the no-rooms line is not shown')
            _shot(page, 'map-empty-open-desktop')

            # Map, two rooms: a pin per room.
            page.route('**/api/announce/rooms', lambda route: route.fulfill(
                status=200, content_type='application/json', body=json.dumps(ROOMS)))
            page.goto(served.url('map'), wait_until='networkidle')
            check(_visible(page, '#announce-toggle'), 'the Announce button did not appear')
            check(page.query_selector('#announce-strip') is not None, 'the strip lost its new id')
            _shot(page, 'map-closed-desktop')
            page.click('#page-settings-gear')
            page.wait_for_selector(P + '[data-open]')
            page.wait_for_selector(P + ' .announce-pin-select')
            check(page.locator(P + ' .announce-pin-select').count() == 2, 'not one pin per room')
            check(not _visible(page, P + ' #announce-pins-empty'), 'the no-rooms line shows with rooms')
            before = storage.get_settings()
            page.select_option(P + ' .announce-pin-select[data-room="den"]', 'media_player.den')
            page.wait_for_selector(P + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) == {'announce_targets'},
                  'pin saved more than announce_targets')
            check(storage.get_settings().get('announce_targets') == {'den': 'media_player.den'},
                  f"wrong pins saved: {storage.get_settings().get('announce_targets')}")
            page.select_option(P + ' .announce-pin-select[data-room="kitchen"]', 'media_player.hall')
            page.wait_for_timeout(600)
            check(storage.get_settings().get('announce_targets') ==
                  {'den': 'media_player.den', 'kitchen': 'media_player.hall'},
                  'a second pin dropped the first')
            _shot(page, 'map-open-desktop')
            page.click(P + ' [aria-label="Close settings"]')

            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('map'), wait_until='networkidle')
            _shot(page, 'map-closed-phone')
            page.click('#page-settings-gear')
            page.wait_for_selector(P + '[data-open]')
            page.wait_for_selector(P + ' .announce-pin-select')
            _shot(page, 'map-open-phone')
            check(page.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"),
                  'the phone page scrolls sideways')

            # Home, Music and custom boards: the board's settings are the drawer.
            page.set_viewport_size({'width': 1300, 'height': 900})
            H = '[data-settings-for~="home"]'
            page.goto(served.url('home'), wait_until='networkidle')
            check(page.locator('[x-data="homeBoard()"] button:has-text("Settings")').count() == 0,
                  "the board toolbar's Settings survived")
            check(page.locator('button:has-text("Edit")').first.is_visible(), 'Edit left the toolbar')
            _shot(page, 'home-closed-desktop')
            page.click('#page-settings-gear')
            page.wait_for_selector(H + '[data-open]')
            page.fill('#boardSettingsName', 'Our home')
            page.wait_for_timeout(200)
            _shot(page, 'home-open-desktop')
            page.keyboard.press('Escape')
            page.wait_for_timeout(800)
            pages = storage.get_settings().get('panel_pages') or []
            check(any((p.get('name') == 'Our home') for p in pages), 'closing the drawer did not save the board name')
            page.click('#page-settings-gear')
            page.wait_for_selector(H + '[data-open]')
            page.click(H + ' button[title="Icon"]')
            page.click(H + ' button:has-text("🙂")')
            page.wait_for_selector('#emoji-picker-back', state='attached')
            check(page.evaluate("() => { const el = document.querySelector('#emoji-picker-back');"
                                " return getComputedStyle(el).zIndex > 85; }"), 'emoji picker sits below the drawer')
            page.keyboard.press('Escape')
            page.goto(served.url('music'), wait_until='networkidle')
            page.click('#page-settings-gear')
            page.wait_for_selector('[data-settings-for~="music"][data-open]')
            _shot(page, 'music-open-desktop')
            s = storage.get_settings()
            s['panel_pages'] = (s.get('panel_pages') or []) + [
                {'slug': 'hall', 'name': 'Hall', 'icon': '🗂️', 'v': 5, 'widgets': [], 'spans': {}}]
            storage.update_settings(s)
            page.goto(served.url('board/hall'), wait_until='networkidle')
            page.click('#page-settings-gear')
            page.wait_for_selector('[data-settings-for~="board"][data-open]')
            check(page.input_value('#boardSettingsName') == 'Hall', 'the board drawer opened on the wrong board')
            _shot(page, 'board-open-desktop')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('home'), wait_until='networkidle')
            page.click('#page-settings-gear')
            page.wait_for_selector(H + '[data-open]')
            _shot(page, 'home-open-phone')
            page.goto(served.url('home?panel=true'), wait_until='domcontentloaded')
            check(page.query_selector('[data-settings-for]') is None, 'a panel drew the board drawer')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_settings_drawer_rest_live OK')


if __name__ == '__main__':
    main()
