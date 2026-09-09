"""The studio's shared eye: serve the app, walk the house, save screenshots.

Every studio-pipeline agent (set builders, vehicle artist, lighting artist,
art director) iterates through THIS one command instead of hand-rolling
playwright probes:

    python tools/house_probe.py --views exterior,living --out ../probe_shots
    python tools/house_probe.py --views all --quality high
    python tools/house_probe.py --views garage --clip 300,60,900,600

Views: exterior, kitchen, living, mudroom, garage, and lean_<zone> for any
zone (lean_board, lean_door, lean_radio, lean_calendar, ...). `all` = the
five room views. Seeds a standard fixture set (two children, a driver, an
event today, three shopping items, three cars of different bodies) so every
signal has something honest to show. Requires playwright (skips loudly
without it, exit 0 — the same bargain live_app makes).

Run from chauffeur/. Screenshots land as <out>/<view>.png, 1400x1000.
"""
import argparse
import datetime
import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), 'tests'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_house_probe_'))

ROOM_VIEWS = ['exterior', 'kitchen', 'living', 'mudroom', 'garage']


def _seed():
    from services import storage
    from models.schemas import Car
    storage.add_member({'id': 'k1', 'name': 'Maya', 'role': 'child'})
    storage.add_member({'id': 'k2', 'name': 'Finn', 'role': 'child'})
    storage.add_driver({'id': 'd1', 'name': 'Alex', 'color': '#38bdf8'})
    now = datetime.datetime.now().replace(microsecond=0)
    start = now + datetime.timedelta(minutes=45)
    sched = {'events': [{'id': 'e1', 'title': 'Soccer practice',
                         'start': start.isoformat(),
                         'end': (start + datetime.timedelta(hours=1)).isoformat()}],
             'assignments': {'e1': 'd1'}}
    storage.get_cached_schedule = lambda: sched
    for n in ('Milk', 'Eggs', 'Bread'):
        storage.add_shopping_item({'id': uuid.uuid4().hex, 'name': n,
                                   'is_checked': False, 'created_at': 1})
    storage.add_car(Car(name='Red Truck', body_type='truck',
                        color_code='#c9473d', seat_capacity=4).model_dump())
    storage.add_car(Car(name='Blue Minivan', body_type='minivan',
                        color_code='#3b82f6', seat_capacity=7).model_dump())
    storage.add_car(Car(name='Green Wagon', body_type='wagon',
                        color_code='#5f8f4e', seat_capacity=5).model_dump())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--views', default='exterior')
    ap.add_argument('--quality', default='high',
                    choices=['high', 'medium', 'low'])
    ap.add_argument('--out', default=os.environ.get('HOUSE_PROBE_OUT',
                                                    'probe_shots'))
    ap.add_argument('--clip', default='',
                    help='x,y,w,h crop of the 1400x1000 page')
    ap.add_argument('--no-seed', action='store_true')
    args = ap.parse_args()

    views = ROOM_VIEWS[:] if args.views == 'all' else [
        v.strip() for v in args.views.split(',') if v.strip()]
    os.makedirs(args.out, exist_ok=True)

    from live_app import live_app
    served = live_app(None if args.no_seed else _seed)
    if served is None:
        print('SKIP: playwright not installed')
        return 0

    clip = None
    if args.clip:
        x, y, w, h = [int(v) for v in args.clip.split(',')]
        clip = {'x': x, 'y': y, 'width': w, 'height': h}

    with served.browser() as page:
        errors = []
        page.on('console', lambda m: errors.append(m.text)
                if m.type == 'error' else None)
        page.goto(served.url('house?quality=' + args.quality))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        for view in views:
            if view == 'exterior':
                page.evaluate("window.chfHouseExit && window.chfHouseExit()")
            elif view == 'kitchen':
                page.evaluate("window.chfHouseEnter()")
            elif view.startswith('lean_'):
                page.evaluate(
                    "window.chfKitchenFocus(" + repr(view[5:]) + ")")
            else:
                page.evaluate(
                    "window.chfHouseEnterRoom(" + repr(view) + ")")
            page.wait_for_timeout(1500)
            path = os.path.join(args.out, view + '.png')
            page.screenshot(path=path, clip=clip)
            print('shot', path)
        if errors:
            print('CONSOLE ERRORS:', errors[:5])
            return 1
    print('ok: no console errors')
    return 0


if __name__ == '__main__':
    sys.exit(main())
