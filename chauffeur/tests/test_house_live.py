"""The Home in real chromium against the served app.

Source pins cannot see whether the dollhouse actually boots, whether the
two-level camera enters and leaves, or whether the lean-in still wears the
board's card after the transplant. Drive the real page (source-reading
tests miss runtime breaks): boot at the exterior, walk in, lean in, walk
out — with zero console errors, the live-app harness's whole point.

Run from chauffeur/:  python tests/test_house_live.py
Set HOUSE_SHOTS=<dir> to also save exterior/kitchen/lean-in screenshots.
"""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_house_live_'))

from live_app import live_app


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _seed():
    """An event TODAY whatever the clock says (the overlay-live idiom), so
    the wall calendar's card has something to show on the lean-in."""
    from services import storage
    now = datetime.datetime.now().replace(microsecond=0)
    late = now.replace(hour=23, minute=59, second=0)
    start = now + datetime.timedelta(minutes=45)
    end = start + datetime.timedelta(hours=1)
    if end > late:
        start, end = now - datetime.timedelta(minutes=5), late
    storage.add_driver({'id': 'd1', 'name': 'Alex', 'color': '#38bdf8'})
    # Pin the cache FUNCTION, not the row: the server's own boot refresh
    # rebuilds the cache from the (empty) calendars moments after boot and
    # would silently erase a seeded row mid-test (test_kitchen_state idiom).
    sched = {
        'events': [{'id': 'e1', 'title': 'Soccer practice',
                    'start': start.isoformat(), 'end': end.isoformat()}],
        'assignments': {'e1': 'd1'},
    }
    storage.get_cached_schedule = lambda: sched
    # H2: two cars through the real model (no HA entities: both present,
    # no warnings, garage calm) so the garage has someone to park.
    from models.schemas import Car as CarModel
    storage.add_car(CarModel(name='Red Truck', body_type='truck',
                             color_code='#c9473d', seat_capacity=4).model_dump())
    storage.add_car(CarModel(name='Blue Minivan', body_type='minivan',
                             color_code='#3b82f6', seat_capacity=7).model_dump())
    # H3: children hang backpacks in the mudroom
    storage.add_member({'id': 'k1', 'name': 'Maya', 'role': 'child'})
    storage.add_member({'id': 'k2', 'name': 'Finn', 'role': 'child'})


def scenario_the_house_boots_enters_and_leans_in():
    # Seed AFTER boot: startup refresh rebuilds the schedule cache, so a
    # cache written before the server comes up is gone by the first request.
    served = live_app()
    if served is None:
        return
    _seed()
    shots = os.environ.get('HOUSE_SHOTS', '')
    with served.browser() as page:
        # ?quality=low on purpose: GPU-less machines still exercise the full
        # build path (low skips PBR/shadows but builds every mesh), and the
        # boot benchmark cannot demote-and-reload mid-test on a forced tier.
        page.goto(served.url('house?quality=low'))
        page.wait_for_timeout(1800)   # boot, benchmark warmup, first paint
        has_room = page.evaluate(
            "!!document.querySelector('#room canvas') && "
            "typeof window.chfHouseEnter === 'function'")
        if not has_room:
            print("  skip  no WebGL room here — the fallback owns the page")
            return
        if shots:
            page.screenshot(path=os.path.join(shots, 'house_exterior.png'))

        page.evaluate("window.chfHouseEnter()")
        page.wait_for_timeout(1100)   # 850ms tween + settle
        if shots:
            page.screenshot(path=os.path.join(shots, 'house_kitchen.png'))

        # the lean-in still wears the board's card after the transplant
        page.evaluate("window.chfKitchenFocus('calendar')")
        page.wait_for_selector('#overlay-calendar .agenda-event', timeout=8000)
        check(page.is_visible('#focus-overlay'),
              "the lean-in still wears the board's card")
        check('Soccer practice' in page.inner_text('#overlay-calendar'),
              "the Family Day card names the seeded event")
        if shots:
            page.screenshot(path=os.path.join(shots, 'house_leanin.png'))

        page.evaluate("window.chfHouseExit()")
        page.wait_for_timeout(1100)
        check(not page.is_visible('#focus-overlay'),
              "walking out drops the lean-in card")

        # H2: the garage is a room too
        check(page.evaluate("typeof window.chfHouseEnterGarage === 'function'"),
              "the garage hand path exists")
        page.evaluate("window.chfHouseEnterGarage()")
        page.wait_for_timeout(1100)
        if shots:
            page.screenshot(path=os.path.join(shots, 'house_garage.png'))
        page.evaluate("window.chfHouseExit()")
        page.wait_for_timeout(1100)

        # H3: the mudroom owns the door — the hero card follows it there
        page.evaluate("window.chfHouseEnterRoom('mudroom')")
        page.wait_for_timeout(1100)
        if shots:
            page.screenshot(path=os.path.join(shots, 'house_mudroom.png'))
        page.evaluate("window.chfKitchenFocus('door')")
        page.wait_for_selector('#overlay-door >> text=Soccer practice',
                               timeout=8000)
        check(page.is_visible('#focus-overlay'),
              "the door's hero card mounts in the mudroom")
        page.evaluate("window.chfHouseExit()")
        page.wait_for_timeout(1100)

        # H3: the living room owns the radio — the music widget follows
        page.evaluate("window.chfHouseEnterRoom('living')")
        page.wait_for_timeout(1100)
        if shots:
            page.screenshot(path=os.path.join(shots, 'house_living.png'))
        page.evaluate("window.chfKitchenFocus('radio')")
        page.wait_for_selector('#overlay-music', state='visible', timeout=8000)
        check(page.is_visible('#overlay-music'),
              "the radio still wears the music widget in its new room")
        page.evaluate("window.chfHouseExit()")
        page.wait_for_timeout(1100)

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


if __name__ == '__main__':
    scenario_the_house_boots_enters_and_leans_in()
    print("test_house_live OK")
