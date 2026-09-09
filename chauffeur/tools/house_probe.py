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
event today, three shopping items, three cars of different bodies, two prep
kits with only one of them claimed) so every signal has something honest to
show - including the mudroom bench, which needs a packed AND an unpacked
group to show both of its backpack states. Requires playwright (skips loudly
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
    storage.add_driver({'id': 'd1', 'name': 'Alex', 'color_code': '#38bdf8'})
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
    # FOUR cars, because two is the number the garage bay holds and every
    # scaling bug in this room hides above it. Each one carries a different
    # telemetry state so a single screenshot judges the whole ladder: fuel,
    # charge, a car low enough to warn, and one that is out.
    storage.add_car(Car(name='Red Truck', body_type='truck',
                        color_code='#c9473d', seat_capacity=4,
                        ha_fuel_entity='sensor.truck_fuel').model_dump())
    storage.add_car(Car(name='Blue Minivan', body_type='minivan',
                        color_code='#3b82f6', seat_capacity=7,
                        ha_battery_entity='sensor.minivan_battery',
                        ha_range_entity='sensor.minivan_range').model_dump())
    storage.add_car(Car(name='Green Wagon', body_type='wagon',
                        color_code='#5f8f4e', seat_capacity=5,
                        ha_fuel_entity='sensor.wagon_fuel').model_dump())
    storage.add_car(Car(name='Silver Hatch', body_type='hatch',
                        color_code='#9aa2a9', seat_capacity=5,
                        ha_device_tracker='device_tracker.hatch',
                        ha_battery_entity='sensor.hatch_battery').model_dump())
    # No Home Assistant here, so the entities above read as nothing and every
    # car would come back "resting" — the same hole the weather stub below
    # fills. Patch the two readers the fleet is built from (the idiom
    # tests/test_house_state.py already uses) rather than ha_api itself, so
    # nothing else in the app starts believing there is an HA.
    from services import cars as cars_svc
    _LEVELS = {'Red Truck': {'battery_pct': None, 'fuel_pct': 68.0, 'range': 340.0},
               'Blue Minivan': {'battery_pct': 82.0, 'fuel_pct': None, 'range': 208.0},
               'Green Wagon': {'battery_pct': None, 'fuel_pct': 14.0, 'range': 41.0},
               'Silver Hatch': {'battery_pct': 47.0, 'fuel_pct': None, 'range': 96.0}}
    cars_svc.car_levels = lambda c: dict(_LEVELS.get(
        (c.get('name') if isinstance(c, dict) else None) or '',
        {'battery_pct': None, 'fuel_pct': None, 'range': None}))
    cars_svc.car_location = lambda c: (
        {'state': 'not_home'}
        if (c.get('name') if isinstance(c, dict) else None) == 'Silver Hatch'
        else None)
    # the mudroom bench draws one backpack per PACKING GROUP, open while the
    # group is still short. Two kits match the seeded event, and only one of
    # them is claimed, so a screenshot carries both states at once — the same
    # reason the window carries a forecast.
    from models.schemas import PrepKit
    for kit in (PrepKit(id='kit_soccer', name='Soccer bag',
                        items=['Water bottle', 'Shin guards'],
                        keywords=['soccer']),
                PrepKit(id='kit_snack', name='Team snack',
                        items=['Orange slices', 'Cooler'],
                        keywords=['soccer'], per_person=False)):
        storage.add_prep_kit(kit.model_dump())
    for item in ('kit_soccer:water bottle', 'kit_soccer:shin guards'):
        storage.add_packing_claim('d1:e1', item, now.date().isoformat())
    # the window is a zone too: with no HA there is no forecast, so the pane
    # renders blank and the weather signal cannot be judged in a screenshot.
    from services import ha_api
    ha_api.get_weather_forecast = lambda _e=None: [
        {'condition': 'partlycloudy', 'temperature': 86,
         'precipitation_probability': 10},
        {'condition': 'sunny', 'temperature': 93, 'precipitation_probability': 0},
        {'condition': 'rainy', 'temperature': 85,
         'precipitation_probability': 60}]


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
    ap.add_argument('--cam', default='',
                    help='px,py,pz,ax,ay,az camera override, applied after '
                         'the view is entered (studio viewfinder)')
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
            # A lean-in is three waits back to back, not one: the room tween
            # (850 ms), the zone tween (650 ms), and only THEN the focus
            # event that fetches the board and mounts the card. At 1500 the
            # shot landed before the card did, at random — which reads in a
            # screenshot as "the zone has no card", the exact thing these
            # views exist to judge.
            page.wait_for_timeout(2800 if view.startswith('lean_') else 1500)
            if args.cam:
                page.evaluate('window.chfHouseCam(' + args.cam + ')')
                page.wait_for_timeout(400)
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
