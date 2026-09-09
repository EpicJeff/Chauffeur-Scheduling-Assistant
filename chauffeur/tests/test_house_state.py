"""The Home's one feed. H1: the house speaks with the kitchen's voice —
same eight sections, same laws, pinned HERE so H2's garage/curb sections
join an already-lawed file.

Spec: docs/superpowers/specs/2026-09-08-house-design.md.
"""
import io
import json
import os
import time

from harness import check
from services import storage, house_room


def _reset():
    storage.shopping_items_table.truncate()
    storage.pets_table.truncate()
    storage.chat_channels_table.truncate()
    storage.chat_messages_table.truncate()
    storage.get_settings = lambda: {}


def scenario_h1_house_speaks_with_the_kitchens_voice():
    _reset()
    storage.get_cached_schedule = lambda: {}
    st = house_room.state(since_ts=time.time())
    check(st['status'] == 'ok', "the empty house still answers ok")
    for zone in ('fridge', 'counter', 'board', 'door', 'calendar', 'radio',
                 'window', 'pet'):
        check(zone in st, f"{zone} section present")
        check(st[zone].get('calm') is True, f"{zone} calm when empty")


def scenario_family_safe_pin():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'services', 'house_room.py'),
        encoding='utf-8').read()
    for banned in ('from services import threads', 'import missions',
                   'import mind', 'import watchers', 'import occasions',
                   'mailer', 'send_drafted'):
        check(banned not in src, f"house_room.py never touches {banned}")
    _reset()
    storage.get_cached_schedule = lambda: {}
    blob = json.dumps(house_room.state(since_ts=0)).lower()
    for banned in ('counterparty', 'gift', 'sensitive', 'insight', 'finding'):
        check(banned not in blob, f"state JSON never carries '{banned}'")


def scenario_the_house_never_writes():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'services', 'house_room.py'),
        encoding='utf-8').read()
    for verb in ('.insert(', '.update(', '.remove(', 'set_app_state',
                 'add_mission', 'add_finding', 'add_thread'):
        check(verb not in src, f"house_room.py never writes ({verb})")


def scenario_endpoint_and_gate():
    _reset()
    storage.get_cached_schedule = lambda: {}
    import main
    out = main.house_state_api(since=0, request=None)
    check(out['status'] == 'ok' and 'fridge' in out, "the API serves the house")
    auth_src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'services', 'auth.py'),
        encoding='utf-8').read()
    check("'/api/house/state', WALL_OR_SERVICE" in auth_src,
          "wall DEVICES may read the house (family-safe by construction)")
    check("'/house', ANYONE" in auth_src, "the shell serves anyone")


def scenario_house_template_pins():
    p = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'templates', 'house.html')
    check(os.path.exists(p), "house.html exists")
    src = io.open(p, encoding='utf-8').read()
    check('<title>The Home</title>' in src, "the page says its name")
    check('The Kitchen' not in src, "no leftover kitchen copy")
    check('HOUSE_STATE_URL' in src and 'api/house/state' in src,
          "the page points at the house feed")
    check("static/house.js" in src, "the page loads house.js")
    check("static/kitchen_overlay.js" in src,
          "the overlay is reused verbatim until H4 renames it")
    check('panel-page-title' in src, "one-title-per-page marker present")
    check('chfBase' in src, "state URL rides chfBase, never a self-computed depth")
    for dialog in ('alert(', 'confirm(', 'prompt('):
        check(dialog not in src, f"no browser dialogs ({dialog})")


def scenario_garage_knows_the_cars():
    _reset()
    storage.get_cached_schedule = lambda: {}
    from services import cars as cars_svc
    orig = (storage.get_all_cars, cars_svc.car_levels, cars_svc.car_location)
    storage.get_all_cars = lambda: [
        {'id': 'c1', 'doc_id': 1, 'name': 'Minivan', 'color_code': '#3b82f6',
         'body_type': 'minivan', 'seat_capacity': 7},
        {'id': 'c2', 'doc_id': 2, 'name': 'EV', 'color_code': '#c9473d',
         'body_type': 'suv', 'seat_capacity': 4, 'is_disabled': False,
         'ha_device_tracker': 'device_tracker.ev', 'ha_battery_entity': 'sensor.b'},
    ]
    cars_svc.car_levels = lambda c: ({'battery_pct': 12.0, 'fuel_pct': None,
                                      'range': 40.0}
                                     if c.get('id') == 'c2' else
                                     {'battery_pct': None, 'fuel_pct': None,
                                      'range': None})
    cars_svc.car_location = lambda c: ({'state': 'not_home'}
                                       if c.get('id') == 'c2' else None)
    try:
        st = house_room.state(since_ts=0)
    finally:
        (storage.get_all_cars, cars_svc.car_levels, cars_svc.car_location) = orig
    g = st['garage']
    check(g['calm'] is False, "a low battery lights the garage")
    van = [c for c in g['cars'] if c['name'] == 'Minivan'][0]
    ev = [c for c in g['cars'] if c['name'] == 'EV'][0]
    check(van['present'] is True and van['warn'] is False,
          "no tracker = home, no warning")
    check(van['body'] == 'minivan' and van['seats'] == 7
          and van['color'] == '#3b82f6', "the record's shape rides through")
    check(ev['present'] is False and ev['warn'] is True,
          "away and low: the garage says so")


def scenario_curb_sees_the_bus():
    _reset()
    storage.get_cached_schedule = lambda: {}
    st = house_room.state(since_ts=0)
    check(st['curb'].get('calm') is True, "no bus out = calm curb")
    from services import bus as bus_svc
    orig_bus = bus_svc.bus_active
    orig_members = storage.get_all_members
    bus_svc.bus_active = lambda m: True
    storage.get_all_members = lambda **k: [{'id': 'kid1', 'name': 'Maya',
                                            'role': 'child', 'status': 'active'}]
    try:
        st = house_room.state(since_ts=0)
    finally:
        bus_svc.bus_active = orig_bus
        storage.get_all_members = orig_members
    check(st['curb']['calm'] is False and st['curb']['bus'] is True,
          "the bus out lights the curb")


def scenario_body_type_rides_the_car_record():
    from models.schemas import Car
    c = Car(name='Truck', body_type='truck')
    check(c.model_dump().get('body_type') == 'truck', "body_type persists")
    check(Car(name='X').model_dump().get('body_type') is None,
          "unset = generic car")
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'templates', 'config.html'),
        encoding='utf-8').read()
    check('newCar.body_type' in src, "the editor offers the picker (hand path)")
    for t in ('sedan', 'suv', 'truck', 'minivan', 'hatch', 'wagon', 'van'):
        check(f'value="{t}"' in src, f"picker offers {t}")


if __name__ == '__main__':
    scenario_h1_house_speaks_with_the_kitchens_voice()
    scenario_family_safe_pin()
    scenario_the_house_never_writes()
    scenario_endpoint_and_gate()
    scenario_house_template_pins()
    scenario_garage_knows_the_cars()
    scenario_body_type_rides_the_car_record()
    scenario_curb_sees_the_bus()
    print("test_house_state OK")
