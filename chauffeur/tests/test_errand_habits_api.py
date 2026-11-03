"""Errand habits: the store, the routes, Argyle's tools and the drawer card (2026-11-02).

Spec: docs/superpowers/specs/2026-11-02-errand-habits-design.md §1, §4, §5, §6.

Run from chauffeur/:  python tests/test_errand_habits_api.py
"""
import os
import sys
import tempfile
import types

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_errand_habits_api_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check  # noqa: E402
from services import storage  # noqa: E402

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')


def _fresh():
    with storage.db_lock:
        storage.app_state_table.truncate()
        storage.daily_schedules_table.truncate()
        storage.drivers_table.truncate()
        storage.drivers_table.insert({'id': 'd1', 'name': 'Jeff', 'home_location': 'Home', 'color_code': '#000'})
        storage.drivers_table.insert({'id': 'd2', 'name': 'Lorena', 'home_location': 'Home', 'color_code': '#000'})
        storage.drivers_table.insert({'id': 'd3', 'name': 'Gone', 'home_location': 'Home', 'color_code': '#000', 'is_disabled': True})


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app), main


JEFF = {'hours': [{'days': [0, 1, 2, 3, 4], 'start': '13:00', 'end': '15:00'}], 'hours_strict': True,
        'separate_trip_mins': None, 'no_separate_trips': False, 'together_kinds': []}
LORENA = {'hours': [], 'hours_strict': True, 'separate_trip_mins': 40, 'no_separate_trips': False,
          'together_kinds': ['groceries', 'pharmacy']}


def scenario_the_store_normalises_and_invalidates():
    _fresh()
    check(storage.get_errand_habits() == {}, "nothing set")
    d = storage.get_driver_errand_habits('d1')
    check(d == {'hours': [], 'hours_strict': True, 'separate_trip_mins': None, 'no_separate_trips': False, 'together_kinds': []},
          f"the defaults are whole: {d}")
    with storage.db_lock:
        storage.daily_schedules_table.insert({'date': '2026-11-03', 'events_hash': 'abc', 'schedule': {'scheduled_errands': []}})
    out = storage.set_errand_habits('d1', {'hours': [{'days': [1, 0], 'start': '13:00', 'end': '15:00'}], 'hours_strict': False})
    check(out['hours'] == [{'days': [0, 1], 'start': '13:00', 'end': '15:00'}] and out['hours_strict'] is False
          and out['separate_trip_mins'] is None and out['no_separate_trips'] is False and out['together_kinds'] == [],
          f"a partial write comes back whole and normalised: {out}")
    check(storage.get_errand_habits() == {'d1': out} and storage.get_driver_errand_habits('d1') == out, "stored by driver id")
    with storage.db_lock:
        rows = storage.daily_schedules_table.all()
    check(rows and all(r.get('events_hash') == 'DIRTY' for r in rows), "the solver reads it: the cached schedule is dirty")
    for bad in ({'hours': [{'days': [], 'start': '13:00', 'end': '15:00'}]},
                {'hours': [{'days': [1], 'start': '15:00', 'end': '13:00'}]},
                {'hours': [{'days': [7], 'start': '13:00', 'end': '15:00'}]},
                {'together_kinds': ['snacks']},
                {'separate_trip_mins': 500}):
        refused = None
        try:
            storage.set_errand_habits('d1', bad)
        except Exception as ex:   # pydantic's ValidationError is a ValueError
            refused = ex
        check(isinstance(refused, ValueError), f"a bad habit is refused with a ValueError: {bad} -> {type(refused).__name__}")
    check(storage.get_driver_errand_habits('d1') == out, "a refused write changes nothing")
    check(storage.set_errand_habits('d1', None)['hours'] == [] and storage.get_errand_habits() == {}, "None clears")


def scenario_describe_habits_says_each_fact():
    from services import errand_prefs
    check(errand_prefs.describe_habits('Jeff', storage.get_driver_errand_habits('zz')) == ['No errand habits set'],
          "nothing set, one line")
    lines = errand_prefs.describe_habits('Jeff', JEFF)
    check(lines == ['Jeff runs errands 13:00-15:00 on weekdays (strict)'], f"{lines}")
    lines = errand_prefs.describe_habits('Lorena', LORENA)
    check(lines == ['Lorena would rather a passing drive add up to 40 min than go out just for it',
                    'Lorena runs groceries and pharmacy runs together'], f"{lines}")
    lines = errand_prefs.describe_habits('Lorena', dict(LORENA, separate_trip_mins=None, no_separate_trips=True,
                                                        hours=[{'days': [5, 6], 'start': '09:00', 'end': '12:00'},
                                                               {'days': [2], 'start': '18:00', 'end': '20:00'}],
                                                        hours_strict=False))
    check(lines[0] == 'Lorena runs errands 09:00-12:00 on weekends and 18:00-20:00 on Wednesdays (preferred)'
          and lines[1] == 'Lorena never makes a separate trip', f"{lines}")


def scenario_the_routes_as_a_parent():
    _fresh()
    client, main = _client()
    from services import auth
    check(auth.resolve('GET', '/api/errands/habits') == auth.PARENTS, "listing is parents only")
    check(auth.resolve('PUT', '/api/errands/habits/{driver_id}') == auth.PARENTS, "writing is parents only")
    check(auth.resolve('DELETE', '/api/errands/habits/{driver_id}') == auth.PARENTS, "clearing is parents only")
    check(auth.resolve('GET', '/api/errands') != auth.PARENTS, "the errands list itself stays as it was")
    r = client.get('/api/errands/habits')
    check(r.status_code == 200, f"{r.status_code} {r.text}")
    drivers = r.json()['drivers']
    check([d['name'] for d in drivers] == ['Jeff', 'Lorena'], f"active drivers in name order, the disabled one left out: {drivers}")
    check(drivers[0]['habits']['hours'] == [] and drivers[0]['text'] == ['No errand habits set'], f"{drivers[0]}")
    r = client.put('/api/errands/habits/d1', json=JEFF)
    check(r.status_code == 200 and r.json()['habits']['hours'] == JEFF['hours'], f"{r.status_code} {r.text}")
    r = client.put('/api/errands/habits/d2', json=LORENA)
    check(r.status_code == 200, f"{r.status_code} {r.text}")
    r = client.get('/api/errands/habits')
    by = {d['id']: d for d in r.json()['drivers']}
    check(by['d1']['text'] == ['Jeff runs errands 13:00-15:00 on weekdays (strict)'] and by['d2']['habits']['together_kinds'] == ['groceries', 'pharmacy'],
          f"{by}")
    r = client.put('/api/errands/habits/d1', json={'hours': [{'days': [1], 'start': '15:00', 'end': '13:00'}]})
    check(r.status_code == 422, f"a row that ends before it starts is refused: {r.status_code}")
    r = client.put('/api/errands/habits/nobody', json=JEFF)
    check(r.status_code == 404, f"an unknown driver: {r.status_code}")
    r = client.delete('/api/errands/habits/d1')
    check(r.status_code == 200 and storage.get_driver_errand_habits('d1')['hours'] == [], f"{r.status_code} {r.text}")


def scenario_argyle_reads_and_sets_by_name():
    _fresh()
    from services import agent_tools_v2 as tools
    check('get_errand_habits' in tools.ADMIN_TOOLS and 'set_errand_habits' in tools.ADMIN_TOOLS, "both admin tools")
    check('set_errand_habits' in tools.SCHEDULE_MUTATING_ADMIN_TOOLS and 'get_errand_habits' not in tools.SCHEDULE_MUTATING_ADMIN_TOOLS,
          "setting moves the schedule, reading does not")
    check('get_errand_habits' in tools.TOOL_SCHEMAS and 'set_errand_habits' in tools.TOOL_SCHEMAS, "both have schemas")
    out = tools.handle_set_errand_habits({'driver_name': 'jeff', 'hours': [{'days': [0, 1, 2, 3, 4], 'start': '13:00', 'end': '15:00'}]})
    check(out['status'] == 'success' and storage.get_driver_errand_habits('d1')['hours'] == JEFF['hours'], f"{out}")
    out = tools.handle_set_errand_habits({'driver_name': 'Jeff', 'separate_trip_mins': 10})
    h = storage.get_driver_errand_habits('d1')
    check(h['separate_trip_mins'] == 10 and h['hours'] == JEFF['hours'], f"a partial set keeps the rest: {h}")
    out = tools.handle_set_errand_habits({'driver_name': 'Jeff', 'separate_trip_mins': -1, 'clear_hours': True,
                                          'together_kinds': ['groceries'], 'no_separate_trips': True})
    h = storage.get_driver_errand_habits('d1')
    check(h == {'hours': [], 'hours_strict': True, 'separate_trip_mins': None, 'no_separate_trips': True, 'together_kinds': ['groceries']},
          f"-1 is back to the household number, clear_hours empties the rows: {h}")
    out = tools.handle_set_errand_habits({'driver_name': 'Nobody', 'no_separate_trips': True})
    check(out['status'] == 'error', f"{out}")
    out = tools.handle_set_errand_habits({'driver_name': 'Jeff', 'together_kinds': ['snacks']})
    check(out['status'] == 'error', f"a bad kind is refused: {out}")
    out = tools.handle_get_errand_habits({})
    check(out['status'] == 'success' and [d['name'] for d in out['drivers']] == ['Jeff', 'Lorena'], f"{out}")
    jeff = next(d for d in out['drivers'] if d['id'] == 'd1')
    check(jeff['text'] == ['Jeff never makes a separate trip', 'Jeff runs groceries together'], f"{jeff}")


def _render_errands(query=None):
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/errands'), query_params=query or {})
    return main.templates.env.get_template('errands.html').render(request=req)


def scenario_the_card_is_in_the_drawer_and_never_on_a_panel():
    page = _render_errands()
    check('errandHabitsPanel()' in page and 'id="errand-habits"' in page, "the habits block is in the Errands drawer")
    i = page.index('id="errand-habits"')
    check(page.index('id="errand-settings"') < i < page.index('id="errand-learned"'),
          "between 'Where errands land' and the rules")
    check('How people run errands' in page, "the heading")
    check('alert(' not in page[i:i + 20000].replace('showGlobalAlert(', ''), "no browser dialogs")
    comp = open(os.path.join(TPL, 'components', 'errand_habits.html'), encoding='utf-8').read()
    check(':disabled="!!' in comp or ':disabled="!' in comp, "disabled bindings are coerced (vendored Alpine)")
    check('type="time"' in comp and 'together_kinds' in comp and 'no_separate_trips' in comp, "the three facts are on the card")
    panel = _render_errands({'panel': 'true'})
    check('errandHabitsPanel()' not in panel, "a panel never draws it")


def scenario_the_card_saves_the_whole_record():
    from test_moment_media_token import _function_text, _run_node
    comp = open(os.path.join(TPL, 'components', 'errand_habits.html'), encoding='utf-8').read()
    logic = _function_text(comp, 'function errandHabitsPanel()')
    got = _run_node(r"""var window = globalThis; window.chfBase = '';
var showGlobalAlert = () => {}; var promptConfirm = async () => true;
window.chfSettingsSaving = () => {}; window.chfSettingsSaved = () => true;
window.addEventListener = () => {};
""" + logic + r"""
(async () => {
  const P = errandHabitsPanel();
  const calls = [];
  const DRIVERS = [
    {id: 'd1', name: 'Jeff', habits: {hours: [], hours_strict: true, separate_trip_mins: null, no_separate_trips: false, together_kinds: []}, text: ['No errand habits set']},
    {id: 'd2', name: 'Lorena', habits: {hours: [{days: [5], start: '09:00', end: '12:00'}], hours_strict: true, separate_trip_mins: 40, no_separate_trips: false, together_kinds: ['groceries']}, text: ['x']},
  ];
  globalThis.fetch = async (url, init) => {
    const method = (init && init.method) || 'GET';
    calls.push({url, method, body: init && init.body ? JSON.parse(init.body) : null});
    if (method === 'PUT') return {ok: true, status: 200, json: async () => ({status: 'saved', habits: JSON.parse(init.body), text: ['saved']})};
    return {ok: true, status: 200, json: async () => ({drivers: DRIVERS.map(d => JSON.parse(JSON.stringify(d)))})};
  };
  await P.load();
  const n0 = P.drivers.length;
  P.addHours('d1');
  P.toggleDay('d1', 0, 0); P.toggleDay('d1', 0, 1);
  P.toggleKind('d1', 'groceries');
  await P.save('d1');
  const put = calls.filter(c => c.method === 'PUT');
  console.log(JSON.stringify({n0, put, lorena: P.drivers.find(d => d.id === 'd2').habits}));
})();
""")
    if got is None:
        return
    check(got['n0'] == 2, f"{got}")
    check(len(got['put']) == 1 and got['put'][0]['url'] == 'api/errands/habits/d1', f"{got['put']}")
    body = got['put'][0]['body']
    check(body['hours'] == [{'days': [0, 1], 'start': '13:00', 'end': '15:00'}] or (len(body['hours']) == 1 and sorted(body['hours'][0]['days']) == [0, 1]),
          f"the new row with its days (the default times are the card's to pick): {body['hours']}")
    check(body['together_kinds'] == ['groceries'] and body['hours_strict'] is True and body['no_separate_trips'] is False
          and 'separate_trip_mins' in body, f"the whole card goes back: {body}")
    check(got['lorena']['together_kinds'] == ['groceries'] and got['lorena']['separate_trip_mins'] == 40, "the other card is untouched")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} errand-habits api scenarios passed")
