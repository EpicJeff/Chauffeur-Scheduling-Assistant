"""The focus overlay in real chromium against the served app.

Pins cannot see whether Alpine actually mounts the Family Day island, or
whether the hero builder is on the page and escaping. Drive the real page:
the room's focus announcement is a plain CustomEvent, so the test speaks it
directly (the 3D raycast is the room's own business, proven by eye), and
what must follow is board-grade DOM inside the overlay — with zero console
errors, the live-app harness's whole point.

Run from chauffeur/:  python tests/test_kitchen_overlay_live.py
Set KITCHEN_SHOTS=<dir> to also save screenshots of both overlays.
"""
import datetime
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_kitchen_overlay_'))

from live_app import live_app


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _seed():
    """An event TODAY whatever the clock says, so the hero and the
    Family Day both have something to show: upcoming when the evening
    allows, already under way when the test runs close to midnight (an
    on-now run is the hero too — that is the board's own rule)."""
    from services import storage
    now = datetime.datetime.now().replace(microsecond=0)
    late = now.replace(hour=23, minute=59, second=0)
    start = now + datetime.timedelta(minutes=45)
    end = start + datetime.timedelta(hours=1)
    if end > late:   # near midnight: run it NOW, ending at day's edge
        start, end = now - datetime.timedelta(minutes=5), late
    storage.add_driver({'id': 'd1', 'name': 'Alex', 'color': '#38bdf8'})
    # Pin the cache FUNCTION, not the row: the server's own boot refresh
    # rebuilds the cache from the (empty) calendars moments after boot and
    # would silently erase a seeded row mid-test. Same idiom as
    # test_kitchen_state — the server thread shares this process.
    sched = {
        'events': [{'id': 'e1', 'title': 'Soccer practice',
                    'start': start.isoformat(), 'end': end.isoformat()}],
        'assignments': {'e1': 'd1'},
    }
    storage.get_cached_schedule = lambda: sched


RECT = {'left': 420, 'top': 220, 'width': 520, 'height': 380}


def _focus(page, zone):
    page.evaluate(
        "z => window.dispatchEvent(new CustomEvent('chf-kitchen-focus',"
        " { detail: { zone: z, rect: z ? " + json.dumps(RECT) + " : null } }))",
        zone)


def scenario_overlay_lives_on_the_real_page():
    # Seed AFTER boot: startup refresh rebuilds the schedule cache, so a
    # cache written before the server comes up is gone by the first request.
    served = live_app()
    if served is None:
        return
    _seed()
    shots = os.environ.get('KITCHEN_SHOTS', '')
    with served.browser() as page:
        # forced tier: the boot benchmark on a headless GPU can demote and
        # RELOAD the page mid-test, aborting whatever fetch was in flight
        page.goto(served.url('kitchen?quality=high'))
        page.wait_for_selector('#focus-overlay', state='attached')
        page.wait_for_timeout(600)   # alpine boot

        # calendar -> the Family Day card, the board's own read-only mode
        _focus(page, 'calendar')
        page.wait_for_selector('#overlay-calendar .agenda-event', timeout=8000)
        check(page.is_visible('#focus-overlay'), "overlay shows on calendar focus")
        check('Soccer practice' in page.inner_text('#overlay-calendar'),
              "the Family Day card names the seeded event")
        check(page.evaluate(
                  "Alpine.$data(document.getElementById('overlay-calendar'))"
                  ".pkInteractive") is True,
              "the Family Day island mounts interactive — the card IS the board")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_calendar_overlay.png'))

        # door -> the hero card, the screensaver's compact form
        _focus(page, None)
        _focus(page, 'door')
        page.wait_for_selector('#overlay-door >> text=Soccer practice', timeout=8000)
        check(page.is_visible('#focus-overlay'), "overlay shows on door focus")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_door_overlay.png'))

        # unfocus -> gone
        _focus(page, None)
        page.wait_for_timeout(150)
        check(not page.is_visible('#focus-overlay'), "unfocus hides the overlay")

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_the_real_lean_in_wears_the_card():
    """The vision, end to end: the tap's own camera move (chfKitchenFocus
    drives the exact frameZone path), then the board's card ON the framed
    furniture — filling the zone's projected rect, not the old centred
    toast. Skipped politely when this machine's chromium has no WebGL,
    because then there is no room to lean into (the 2D fallback owns the
    page and draws its own detail)."""
    served = live_app()
    if served is None:
        return
    _seed()
    shots = os.environ.get('KITCHEN_SHOTS', '')
    with served.browser() as page:
        # forced tier: the boot benchmark on a headless GPU can demote and
        # RELOAD the page mid-test, aborting whatever fetch was in flight
        page.goto(served.url('kitchen?quality=high'))
        page.wait_for_timeout(1800)   # boot, benchmark warmup, first paint
        has_room = page.evaluate(
            "!!document.querySelector('#room canvas') && "
            "typeof window.chfKitchenFocus === 'function'")
        if not has_room:
            print("  skip  no WebGL room here — the fallback owns the page")
            return

        page.evaluate(
            "window.__rect = null;"
            "window.addEventListener('chf-kitchen-focus',"
            " e => { if (e.detail && e.detail.rect) window.__rect = e.detail.rect; })")
        page.evaluate("window.chfKitchenFocus('calendar')")
        page.wait_for_selector('#overlay-calendar .agenda-event', timeout=8000)
        page.wait_for_timeout(450)    # tween settled + fade done
        geo = page.evaluate(
            "(() => { const r = document.getElementById('focus-overlay')"
            ".getBoundingClientRect();"
            " return { l: r.left, w: r.width, z: window.__rect }; })()")
        check(geo['z'] is not None, "the room announced the framed rect")
        ov_cx = geo['l'] + geo['w'] / 2
        zone_cx = geo['z']['left'] + geo['z']['width'] / 2
        check(abs(ov_cx - zone_cx) < 48,
              "the card sits ON the framed furniture, centred on its face")
        check(geo['w'] >= 300, "the card stays readable")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_calendar_leanin.png'))

        page.evaluate("window.chfKitchenFocus('door')")
        page.wait_for_selector('#overlay-door >> text=Soccer practice',
                               timeout=8000)
        page.wait_for_timeout(450)
        check(not page.is_visible('#overlay-calendar'),
              "switching zones swaps the card, never stacks them")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_door_leanin.png'))

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_other_zones_wear_their_cards():
    """The port: corkboard wears the real shopping-list card, the window
    wears the weather card — mounted through the board's own tile body,
    read-only, from one ?widgets= payload. A zone whose tile is empty
    (nothing seeded) keeps the tip, and that path is the fridge here."""
    served = live_app()
    if served is None:
        return
    _seed()
    from services import storage, ha_api
    storage.shopping_lists_table.truncate()
    storage.shopping_items_table.truncate()
    storage.add_shopping_list({'id': 'grocery', 'name': 'Groceries',
                               'is_default': True})
    storage.shopping_items_table.insert(
        {'id': 's1', 'name': 'Oat milk', 'list_id': 'grocery',
         'is_checked': False, 'created_at': 1})
    storage.shopping_items_table.insert(
        {'id': 's2', 'name': 'Eggs', 'list_id': 'grocery',
         'is_checked': False, 'created_at': 2})
    base = datetime.datetime.now().replace(hour=12, minute=0, second=0,
                                           microsecond=0)
    days = [{'condition': 'sunny', 'temperature': 70 + i, 'templow': 55,
             'precipitation_probability': 0,
             'datetime': (base + datetime.timedelta(days=i)).isoformat()}
            for i in range(5)]
    ha_api.get_weather_forecast = lambda e=None, kind='daily': days
    # the board payload is TTL-cached server-side; the previous scenario
    # already built it WITHOUT this stub, so drop that copy
    from services import home_board
    home_board.invalidate_cache()

    shots = os.environ.get('KITCHEN_SHOTS', '')
    with served.browser() as page:
        # forced tier: the boot benchmark on a headless GPU can demote and
        # RELOAD the page mid-test, aborting whatever fetch was in flight
        page.goto(served.url('kitchen?quality=high'))
        page.wait_for_timeout(1800)
        has_room = page.evaluate(
            "!!document.querySelector('#room canvas') && "
            "typeof window.chfKitchenFocus === 'function'")
        if not has_room:
            print("  skip  no WebGL room here — the fallback owns the page")
            return

        page.evaluate("window.chfKitchenFocus('board')")
        page.wait_for_selector('#overlay-tile >> text=Eggs', timeout=8000)
        live_buttons = page.evaluate(
            "Array.from(document.querySelectorAll('#overlay-tile button'))"
            ".filter(b => b.offsetParent !== null && !b.disabled).length")
        check(live_buttons > 0,
              "the shopping card mounts interactive: real ticks, enabled")
        check(page.evaluate(
                  "document.getElementById('overlay-open').getAttribute('href')"
                  ".indexOf('lists') !== -1"),
              "the open chip is the door to the zone's own page")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_board_leanin.png'))

        page.evaluate("window.chfKitchenFocus('window')")
        page.wait_for_selector('#overlay-tile >> text=70', timeout=8000)
        check(not page.is_visible('#overlay-calendar'),
              "zone switch swaps the mounted card")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_window_leanin.png'))

        # the radio wears the real Music Assistant player widget.
        # Condition-waits, not fixed sleeps: under a saturated sweep the
        # 650ms focus tween alone can outlive a 1400ms nap (flaked twice
        # on the 12-worker run, passed every standalone run).
        page.evaluate("window.chfKitchenFocus('radio')")
        page.wait_for_selector('#overlay-music', state='visible', timeout=8000)
        check(page.is_visible('#overlay-music'),
              "the radio wears the music widget (player half)")

        # nothing seeded for moments: the fridge keeps its tip-only lean-in
        page.evaluate("window.chfKitchenFocus('fridge')")
        page.wait_for_selector('#focus-overlay', state='hidden', timeout=8000)
        check(not page.is_visible('#focus-overlay'),
              "an empty tile hides the overlay instead of showing blank paper")

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


if __name__ == '__main__':
    scenario_overlay_lives_on_the_real_page()
    scenario_the_real_lean_in_wears_the_card()
    scenario_other_zones_wear_their_cards()
    print("test_kitchen_overlay_live OK")
