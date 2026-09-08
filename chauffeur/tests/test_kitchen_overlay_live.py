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
        page.goto(served.url('kitchen'))
        page.wait_for_selector('#focus-overlay', state='attached')
        page.wait_for_timeout(600)   # alpine boot

        # calendar -> the Family Day card, the board's own read-only mode
        _focus(page, 'calendar')
        page.wait_for_selector('#overlay-calendar .agenda-event', timeout=8000)
        check(page.is_visible('#focus-overlay'), "overlay shows on calendar focus")
        check('Soccer practice' in page.inner_text('#overlay-calendar'),
              "the Family Day card names the seeded event")
        check(page.locator('#overlay-calendar button').count() == 0,
              "read-only island draws no write affordance")
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


if __name__ == '__main__':
    scenario_overlay_lives_on_the_real_page()
    print("test_kitchen_overlay_live OK")
