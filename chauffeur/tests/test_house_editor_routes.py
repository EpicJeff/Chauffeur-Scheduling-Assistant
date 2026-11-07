"""The house editor's routes (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md sections 2, 6, 9; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 10): the page
for anyone, every API for parents only (auth enforcement ON), the build
driven end to end through HTTP with a fake reader standing in for
twin_reads.read, edits, start over, the spend reset, state and rounds, and
recovery of an interrupted build at app start.

Run from chauffeur/:  python tests/test_house_editor_routes.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
from unittest.mock import patch

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_routes_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import storage  # noqa: E402
from services import twin_build as tb  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_reads  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402  (the fake reader and blank PDFs)

PRICED = next(iter(tc.PRICES))
EDITOR_API = [
    ('GET', '/api/house/editor/sheets'),
    ('PUT', '/api/house/editor/sheets/roles'),
    ('GET', '/api/house/editor/sheets/abc/1.png'),
    ('POST', '/api/house/editor/build'),
    ('GET', '/api/house/editor/build/b1'),
    ('POST', '/api/house/editor/build/b1/answer'),
    ('POST', '/api/house/editor/build/b1/reread'),
    ('POST', '/api/house/editor/build/b1/stop'),
    ('POST', '/api/house/editor/build/b1/resume'),
    ('POST', '/api/house/editor/edit'),
    ('POST', '/api/house/editor/start-over'),
    ('POST', '/api/house/editor/cost/reset'),
    ('GET', '/api/house/editor/state'),
    ('GET', '/api/house/twin/rounds/1'),
]


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


_real_settings = storage.get_settings


def _enforced():
    return patch.object(storage, 'get_settings', side_effect=lambda: {**_real_settings(), 'auth_enforce': True})


def _people():
    storage.add_member({'id': 'p1', 'name': 'Pat', 'role': 'parent'})
    storage.add_member({'id': 'k1', 'name': 'Kit', 'role': 'child'})
    return ({'X-Member-Token': storage.create_member_token('p1')},
            {'X-Member-Token': storage.create_member_token('k1')},
            {'X-Device-Token': storage.enrol_device_token('editor-panel', 'Panel')})


def _client(startup=False):
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app)


def _fresh():
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    tb._forget()


def _wait(fn, until, timeout=20):
    deadline = time.time() + timeout
    value = fn()
    while time.time() < deadline and not until(value):
        time.sleep(0.1)
        value = fn()
    return value


PARENT = MEMBER = PANEL = None


def _setup():
    global PARENT, MEMBER, PANEL
    if PARENT is None:
        PARENT, MEMBER, PANEL = _people()


def scenario_every_editor_route_is_parents_only():
    _setup()
    c = _client()
    with _enforced():
        for method, path in EDITOR_API:
            for who in (MEMBER, PANEL, {}):
                r = c.request(method, path, headers=who, json={})
                check(r.status_code in (401, 403), (method, path, who and list(who)[0], r.status_code))


def scenario_page_renders_for_anyone():
    _setup()
    c = _client()
    with _enforced():
        r = c.get('/house/editor')
    check(r.status_code == 200 and 'text/html' in r.headers.get('content-type', ''), r.status_code)


def scenario_sheets_roles_and_page_images():
    _fresh()
    _setup()
    sheets, plot, photo = engine_tests._sources()
    c = _client()
    with _enforced():
        got = c.get('/api/house/editor/sheets', headers=PARENT).json()
        check(len(got['sources']) == 3 and len(got['page_roles']) == 4 and 'registrations' in got, got)
        rows = got['page_roles'][:1]
        r = c.put('/api/house/editor/sheets/roles', headers=PARENT, json={'rows': rows})
        check(r.status_code == 200 and len(ts.page_roles()) == 1, r.text)
        bad = c.put('/api/house/editor/sheets/roles', headers=PARENT,
                    json={'rows': [{**rows[0], 'role': 'attic'}]})
        check(bad.status_code == 400 and len(ts.page_roles()) == 1, bad.text)
        img = c.get(f'/api/house/editor/sheets/{sheets}/1.png', headers=PARENT)
        check(img.status_code == 200 and img.headers['content-type'] == 'image/png', img.status_code)
        check(c.get(f'/api/house/editor/sheets/{sheets}/9.png', headers=PARENT).status_code == 404, 'missing page')


def scenario_build_runs_through_the_api():
    _fresh()
    _setup()
    _, _, photo = engine_tests._sources()
    reader = engine_tests.Reader()
    c = _client()
    with _enforced(), patch.object(twin_reads, 'read', reader):
        r = c.post('/api/house/editor/build', headers=PARENT, json=engine_tests._inputs(photo))
        check(r.status_code == 200, r.text)
        bid = r.json()['id']
        st = _wait(lambda: c.get(f'/api/house/editor/build/{bid}', headers=PARENT).json(),
                   lambda s: s['state'] == 'paused')
        check(st['pause']['kind'] == 'scale_outline', st)
        again = c.post('/api/house/editor/build', headers=PARENT, json=engine_tests._inputs(photo))
        check(again.status_code == 409 and 'already running' in again.json()['detail'], again.text)
        busy = c.post('/api/house/editor/start-over', headers=PARENT, json={})
        check(busy.status_code == 409, busy.text)
        r = c.post(f'/api/house/editor/build/{bid}/answer', headers=PARENT,
                   json={'step': 'outline:L1', 'decision': {'accept': True}})
        check(r.status_code == 200, r.text)
        st = _wait(lambda: c.get(f'/api/house/editor/build/{bid}', headers=PARENT).json(),
                   lambda s: s['state'] == 'paused' and s['pause']['step'] == 'registration:L2')
        check(st['pause']['step'] == 'registration:L2', st['pause'])
        since = c.get(f'/api/house/editor/build/{bid}?since={st["seq"]}', headers=PARENT).json()
        check(since['events'] == [], 'nothing new since the last seq')
        check(c.post(f'/api/house/editor/build/{bid}/stop', headers=PARENT, json={}).status_code == 200, 'stop')
        check(c.post(f'/api/house/editor/build/{bid}/resume', headers=PARENT, json={}).status_code == 200, 'resume')
        r = c.post(f'/api/house/editor/build/{bid}/reread', headers=PARENT, json={'step': 'walls:L1:main'})
        check(r.status_code == 200, r.text)
        check(c.get('/api/house/editor/build/nope', headers=PARENT).status_code == 404, 'unknown build')
        tb.stop(bid)


def scenario_edit_returns_summary_and_plan():
    _fresh()
    _setup()
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_edit_house.plan.json'),
              encoding='utf-8') as f:
        ts.push_round(json.load(f), 'build')
    c = _client()
    with _enforced():
        r = c.post('/api/house/editor/edit', headers=PARENT,
                   json={'edit': {'op': 'set', 'piece': 'roof-1', 'field': 'pitch', 'value': 8}})
        check(r.status_code == 200, r.text)
        body = r.json()
        sec = body['plan']['buildings'][0]['roof']['sections'][0]
        check(body['summary'] and isinstance(body['round'], int) and sec['pitch'] == 8, body['summary'])
        bad = c.post('/api/house/editor/edit', headers=PARENT,
                     json={'edit': {'op': 'set', 'piece': 'wall-1', 'field': 'from', 'value': [0, 0]}})
        check(bad.status_code == 400, bad.text)


def scenario_state_and_rounds():
    _fresh()
    _setup()
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_edit_house.plan.json'),
              encoding='utf-8') as f:
        rid = ts.push_round(json.load(f), 'build')
    c = _client()
    with _enforced():
        st = c.get('/api/house/editor/state', headers=PARENT).json()
        check(st['plan'] and st['rounds'] and set(st['cost']) >= {'total', 'blocking'} and 'build' in st, st.keys())
        r = c.get(f'/api/house/twin/rounds/{rid}', headers=PARENT)
        check(r.status_code == 200 and r.json()['plan']['schema'] == 'chauffeur.twin.plan/2', r.text)
        check(c.get('/api/house/twin/rounds/999', headers=PARENT).status_code == 404, 'unknown round')


def scenario_start_over_and_reset_need_intent():
    _fresh()
    _setup()
    tc.record('step:outline', [{'model': PRICED, 'input_tokens': 1000, 'output_tokens': 100, 'images': 0,
                                'prompt_chars': 1, 'max_output_tokens': 1024}])
    c = _client()
    with _enforced():
        check(c.post('/api/house/editor/cost/reset', headers=PARENT, json={}).status_code == 400, 'no word')
        check(c.post('/api/house/editor/cost/reset', headers=PARENT, json={'confirm': 'yes'}).status_code == 400, 'wrong word')
        check(tc.total() > 0, 'nothing reset yet')
        r = c.post('/api/house/editor/cost/reset', headers=PARENT, json={'confirm': 'reset'})
        check(r.status_code == 200 and tc.total() == 0 and tc.resets()[-1]['by'] == 'p1', r.text)
        r = c.post('/api/house/editor/start-over', headers=PARENT, json={})
        check(r.status_code == 200 and ts.current() is None, r.text)


def scenario_app_start_recovers_an_interrupted_build():
    _fresh()
    _setup()
    _, _, photo = engine_tests._sources()
    reader = engine_tests.Reader(crash_at='walls:L1:garage')
    b = tb.start(engine_tests._inputs(photo), reader=reader, inline=True)
    try:
        tb.answer(b, 'outline:L1', {'accept': True})
    except engine_tests._Crash:
        pass
    tb._forget()
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app):
        pass
    check(tb.status(b)['state'] == 'stopped', tb.status(b)['state'])


def scenario_suggest_roles_reads_once_and_saves_nothing():
    # Task 8 review ruling: the engine never runs sheet_roles; the editor asks
    # for suggestions before Build and the person confirms them.
    _fresh()
    _setup()
    sheets = ts.save_source('drawing', 'lot58.pdf', engine_tests._pdf(3))
    reader = engine_tests.Reader()
    c = _client()
    with _enforced(), patch.object(twin_reads, 'read', reader):
        r = c.post('/api/house/editor/sheets/suggest', headers=PARENT, json={'source': sheets})
    check(r.status_code == 200, r.text)
    rows = r.json()['rows']
    check(rows and all(row['source'] == sheets for row in rows), rows)
    check([c['kind'] for c in reader.calls] == ['sheet_roles'], reader.calls)
    check(ts.page_roles() == [], 'suggestions are not saved until the person confirms them')


def scenario_a_build_from_before_a_start_over_is_gone():
    _fresh()
    _setup()
    _, _, photo = engine_tests._sources()
    b = tb.start(engine_tests._inputs(photo), reader=engine_tests.Reader(), inline=True)
    tb.stop(b)          # paused inline: stopping it frees the house for a start over
    ts.start_over()
    c = _client()
    with _enforced():
        r = c.get(f'/api/house/editor/build/{b}', headers=PARENT)
    check(r.status_code in (404, 409), (r.status_code, r.text))


def scenario_twin_page_has_no_tools_sheet_but_links_to_the_editor():
    _setup()
    c = _client()
    html = c.get('/house/twin').text
    check('twin-tools-sheet' not in html and 'house/editor' in html, 'retired with a way forward')
    panel = c.get('/house/twin?panel=true&kiosk=true').text
    check('house/editor' not in panel, 'no editor link on a wall panel')


if __name__ == '__main__':
    for fn in (scenario_every_editor_route_is_parents_only,
               scenario_page_renders_for_anyone,
               scenario_sheets_roles_and_page_images,
               scenario_build_runs_through_the_api,
               scenario_edit_returns_summary_and_plan,
               scenario_state_and_rounds,
               scenario_start_over_and_reset_need_intent,
               scenario_app_start_recovers_an_interrupted_build,
               scenario_suggest_roles_reads_once_and_saves_nothing,
               scenario_a_build_from_before_a_start_over_is_gone,
               scenario_twin_page_has_no_tools_sheet_but_links_to_the_editor):
        fn()
        print('  ok ', fn.__name__)
