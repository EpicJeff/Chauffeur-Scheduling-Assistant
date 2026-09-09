"""The Kitchen's one feed: seven family-safe sections, each calm-able.

Laws under test (docs/superpowers/specs/2026-09-06-kitchen-design.md):
every signal one number from GET /api/kitchen/state; poisoned sources fall
to _CALM instead of erroring; nothing sensitive can ride the JSON; the room
never writes.
"""
import datetime
import io
import json
import os
import time

from harness import check
from services import storage, kitchen_room as kitchen


def _reset():
    storage.shopping_items_table.truncate()
    storage.shopping_lists_table.truncate()
    storage.pets_table.truncate()
    storage.chat_channels_table.truncate()
    storage.chat_messages_table.truncate()
    storage.get_settings = lambda: {}


def scenario_all_seven_sections_present_and_calm_on_empty():
    _reset()
    storage.get_cached_schedule = lambda: {}
    st = kitchen.state(since_ts=time.time())
    check(st['status'] == 'ok', "empty house still answers ok")
    for zone in ('fridge', 'counter', 'board', 'door', 'calendar', 'radio',
                 'window', 'pet'):
        check(zone in st, f"{zone} section present")
        check(st[zone].get('calm') is True, f"{zone} is calm when empty")


def scenario_signals_carry_real_numbers():
    _reset()
    now = time.time()
    # moments: an event channel with one photo message
    storage.chat_channels_table.insert({'id': 'ch1', 'kind': 'event',
                                        'event_id': 'e1', 'title': 'Soccer'})
    storage.chat_messages_table.insert({'id': 'm1', 'channel_id': 'ch1',
                                        'attachment': 'x.jpg', 'ts': now,
                                        'body': 'goal!', 'sender_member_id': 'kid'})
    # shopping: two open, one checked — on a real LIST, because that is the
    # only way items exist in the app and because the room reads one list at
    # a time now (a bare get_shopping_items() spans private lists too).
    storage.shopping_lists_table.insert({'id': 'l1', 'name': 'Groceries'})
    storage.shopping_items_table.insert({'id': 's1', 'list_id': 'l1', 'name': 'Milk', 'is_checked': False, 'created_at': 1})
    storage.shopping_items_table.insert({'id': 's2', 'list_id': 'l1', 'name': 'Eggs', 'is_checked': False, 'created_at': 2})
    storage.shopping_items_table.insert({'id': 's3', 'list_id': 'l1', 'name': 'Old', 'is_checked': True, 'created_at': 0})
    # pets: the room must use get_pets (derived level, active-only) —
    # never the raw table, whose stored 'level' is a lie
    storage.get_pets = lambda *a, **k: [{'id': 'p1', 'name': 'Biscuit',
                                         'level': 3, 'active': True}]
    # schedule cache: one assigned event later the same (fixed) day —
    # the clock is pinned so a run near midnight cannot push it to tomorrow
    fixed_now = datetime.datetime(2026, 9, 8, 10, 0)
    start = fixed_now + datetime.timedelta(hours=2)
    storage.get_cached_schedule = lambda: {
        'events': [{'id': 'e1', 'title': 'Practice', 'start': start.isoformat()}],
        'assignments': {'e1': 'drv1'}}
    st = kitchen.state(since_ts=now - 3600, now=fixed_now)
    check(st['fridge']['new_moments'] == 1 and not st['fridge'].get('calm'),
          "a fresh moment lights the fridge")
    check(st['board']['items'] == 2 and st['board']['top'][0] == 'Milk',
          "the corkboard counts only open items, remembered order")
    check(st['pet']['count'] == 1 and st['pet']['pets'][0]['name'] == 'Biscuit'
          and st['pet']['pets'][0]['level'] == 3,
          "the pet bowl knows Biscuit at his DERIVED level")
    check(st['calendar']['today'] == 1
          and any('Practice' in x for x in (st['calendar']['next'] or [])),
          "the wall calendar sees today's remaining event")
    check(st['door']['mins'] is not None and st['door']['mins'] <= 120
          and 'Practice' in st['door']['label'],
          "the door counts down to the next leave")


def scenario_the_corkboard_never_draws_a_private_list():
    """SECURITY, and the module's own stated law: family-safe by
    construction, because the youngest eye in the house is the audience.

    This feed is served at WALL tier with nobody signed in, so §7's anonymous
    test is the whole gate — `audience_allows(l, 'shopping_list', None)`
    passes a household list and refuses a private one, whose audience IS its
    `shared_with` and which a place can never be on. Reading every item there
    was (`get_shopping_items()` with no list_id spans every list in the
    house) put the present on the corkboard.
    """
    _reset()
    storage.get_cached_schedule = lambda: {}
    storage.shopping_lists_table.insert({'id': 'l1', 'name': 'Groceries'})
    storage.shopping_lists_table.insert({'id': 'l2', 'name': "Maya's present",
                                         'audience': 'private',
                                         'shared_with': ['mom']})
    storage.shopping_items_table.insert({'id': 's1', 'list_id': 'l1',
                                         'name': 'Milk', 'is_checked': False,
                                         'created_at': 1})
    storage.shopping_items_table.insert({'id': 's2', 'list_id': 'l2',
                                         'name': 'Racing bike',
                                         'is_checked': False, 'created_at': 2})
    st = kitchen.state(since_ts=0)
    check(st['board']['items'] == 1 and st['board']['top'] == ['Milk'],
          f"the corkboard counts and names only the open list, got {st['board']}")
    blob = json.dumps(st).lower()
    check('racing bike' not in blob and "maya's present" not in blob,
          "no trace of the private list anywhere in the room's JSON")


def scenario_every_source_poisoned_still_answers():
    _reset()
    boom = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('down'))
    storage.get_cached_schedule = boom
    orig = (storage.count_event_moments_since, storage.get_recent_event_moments,
            storage.get_shopping_items, storage.get_shopping_lists)
    storage.count_event_moments_since = boom
    storage.get_recent_event_moments = boom
    storage.get_shopping_items = boom
    storage.get_shopping_lists = boom
    try:
        st = kitchen.state(since_ts=0)
    finally:
        (storage.count_event_moments_since, storage.get_recent_event_moments,
         storage.get_shopping_items, storage.get_shopping_lists) = orig
    check(st['status'] == 'ok', "poisoned sources never break the room")
    for zone in ('fridge', 'board', 'door', 'calendar'):
        check(st[zone].get('calm') is True, f"{zone} fell to calm, not to error")


def scenario_family_safe_pin():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'services', 'kitchen_room.py'),
        encoding='utf-8').read()
    for banned in ('from services import threads', 'import missions',
                   'import mind', 'import watchers', 'import occasions',
                   'mailer', 'send_drafted'):
        check(banned not in src, f"kitchen.py never touches {banned}")
    _reset()
    storage.get_cached_schedule = lambda: {}
    blob = json.dumps(kitchen.state(since_ts=0)).lower()
    for banned in ('counterparty', 'gift', 'sensitive', 'insight', 'finding'):
        check(banned not in blob, f"state JSON never carries '{banned}'")


def scenario_the_room_never_writes():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'services', 'kitchen_room.py'),
        encoding='utf-8').read()
    for verb in ('.insert(', '.update(', '.remove(', 'set_app_state',
                 'add_mission', 'add_finding', 'add_thread'):
        check(verb not in src, f"kitchen.py never writes ({verb})")



def scenario_endpoint_and_gate():
    _reset()
    storage.get_cached_schedule = lambda: {}
    import main
    out = main.kitchen_state_api(since=0, request=None)
    check(out['status'] == 'ok' and 'fridge' in out, "the API serves the room")
    auth_src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'services', 'auth.py'),
        encoding='utf-8').read()
    check("'/api/kitchen/state', WALL_OR_SERVICE" in auth_src,
          "wall DEVICES may read the kitchen (family-safe by construction)")
    check("'/kitchen', ANYONE" in auth_src, "the shell serves anyone")


def _room_src(name):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return io.open(os.path.join(root, name), encoding='utf-8').read()


def scenario_room_pins():
    js = _room_src(os.path.join('static', 'kitchen.js'))
    for banned in ("method:", "'POST'", '"POST"', 'innerHTML', 'alert(',
                   'confirm(', 'prompt('):
        check(banned not in js, f"kitchen.js never uses {banned}")
    for needed in ('webglcontextlost', 'setPixelRatio(1)', 'chfBase',
                   'textContent', 'visibilityState',
                   'chf_kitchen_quality', 'PCFSoftShadowMap',
                   'ACESFilmicToneMapping'):
        check(needed in js, f"kitchen.js carries {needed}")
    html = _room_src(os.path.join('templates', 'kitchen.html'))
    for banned in ('alert(', 'confirm(', 'prompt('):
        check(banned not in html, f"kitchen.html never uses {banned}")
    check('panel-page-title' in html, "one-title-per-page marker present")
    check('chfBase' in html, "state URL rides chfBase, never a self-computed depth")


def scenario_mixed_timezone_stamps_do_not_blank_the_day():
    _reset()
    import datetime as _dt
    now = _dt.datetime(2026, 9, 8, 10, 0)
    aware = (now + _dt.timedelta(hours=1)).astimezone()
    naive = now + _dt.timedelta(hours=3)
    storage.get_cached_schedule = lambda: {
        'events': [
            {'id': 'a', 'title': 'Aware', 'start': aware.isoformat()},
            {'id': 'b', 'title': 'Naive', 'start': naive.isoformat()},
            {'id': 'c', 'title': 'Broken', 'start': 'not-a-date'},
        ],
        'assignments': {'a': 'd1'}}
    st = kitchen.state(since_ts=0, now=now)
    check(st['calendar']['today'] == 2,
          "aware and naive stamps both count; the broken one drops alone")
    check('Aware' in st['door']['label'],
          "the door still sees the sooner (aware) event")


def scenario_window_reads_the_sky_and_degrades():
    _reset()
    storage.get_cached_schedule = lambda: {}
    from services import ha_api
    orig = ha_api.get_weather_forecast
    try:
        ha_api.get_weather_forecast = lambda e=None, kind='daily': [
            {'condition': 'rainy', 'temperature': 64,
             'precipitation_probability': 80}]
        st = kitchen.state(since_ts=0)
        check(st['window']['calm'] is False and st['window']['cond'] == 'rainy'
              and st['window']['temp'] == 64,
              "rain outside lights the window")
        ha_api.get_weather_forecast = lambda e=None, kind='daily': [
            {'condition': 'sunny', 'temperature': 75,
             'precipitation_probability': 0}]
        st = kitchen.state(since_ts=0)
        check(st['window']['calm'] is True and st['window']['temp'] == 75,
              "a sunny day is calm but still shows its temperature")
        ha_api.get_weather_forecast = lambda e=None, kind='daily': (
            (_ for _ in ()).throw(RuntimeError('no HA')))
        st = kitchen.state(since_ts=0)
        check(st['window'].get('calm') is True, "no HA = calm window, never broken")
    finally:
        ha_api.get_weather_forecast = orig

if __name__ == '__main__':
    scenario_all_seven_sections_present_and_calm_on_empty()
    scenario_signals_carry_real_numbers()
    scenario_the_corkboard_never_draws_a_private_list()
    scenario_every_source_poisoned_still_answers()
    scenario_family_safe_pin()
    scenario_the_room_never_writes()
    scenario_endpoint_and_gate()
    scenario_room_pins()
    scenario_mixed_timezone_stamps_do_not_blank_the_day()
    scenario_window_reads_the_sky_and_degrades()
    print("test_kitchen_state OK")
