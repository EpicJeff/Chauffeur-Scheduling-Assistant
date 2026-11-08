"""The house editor's routes (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md sections 2, 6, 9; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 10): the page
for anyone, every API for parents only (auth enforcement ON), the build
driven end to end through HTTP with a fake reader standing in for
twin_reads.read, edits, start over, the spend reset, state and rounds, and
recovery of an interrupted build at app start.

Run from chauffeur/:  python tests/test_house_editor_routes.py
"""
import copy
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
    ('POST', '/api/house/editor/place/buildings'),
    ('PATCH', '/api/house/editor/place/buildings/garage'),
    ('DELETE', '/api/house/editor/place/buildings/garage'),
    ('POST', '/api/house/editor/place/pages/move'),
    ('PUT', '/api/house/editor/place/photos/abc'),
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
        st = _wait(lambda: c.get(f'/api/house/editor/build/{bid}', headers=PARENT).json(),
                   lambda s: s['state'] == 'paused')
        # Final review I1: Start over stops a paused build instead of refusing.
        r = c.post('/api/house/editor/start-over', headers=PARENT, json={})
        check(r.status_code == 200 and ts.current() is None, r.text)
        check(not tb.running(), 'the paused build was stopped')


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
        # Re-review: the person is told what to change, not a generic line.
        gone = c.post('/api/house/editor/edit', headers=PARENT,
                      json={'edit': {'op': 'set', 'piece': 'no-such-wall', 'field': 'height', 'value': 9}})
        check(gone.status_code == 400 and gone.json()['detail'] == 'Unknown piece no-such-wall.', gone.text)


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


# Slice 1b-i Task 2 (plan docs/superpowers/plans/2026-11-07-house-editor-slice-1b-i.md):
# the place routes, uploads to a part, moving a page, tagging a photo and the
# page hints on suggested roles.
KIND_IDS = ['main_house', 'garage', 'adu', 'pool_house', 'shed', 'greenhouse', 'barn', 'studio', 'workshop',
            'other']
KIND_LABELS = ['Main house', 'Garage', 'ADU or guest house', 'Pool house', 'Shed', 'Greenhouse', 'Barn',
               'Studio or office', 'Workshop', 'Other']
PLACE_ROLES = {'building': ['floor', 'roof', 'elevation', 'other', 'skip'],
               'lot': ['plot', 'survey', 'landscape', 'other', 'skip']}
ROW_KEYS = ('source', 'page', 'role', 'level', 'box', 'building')


def _plain(detail):
    # Global constraint: errors that reach a person are plain sentences.
    return isinstance(detail, str) and 0 < len(detail) <= 160 and not any(ch in detail for ch in '[]{}_=<>|')


def _png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), (120, 140, 160)).save(buf, format='PNG')
    return buf.getvalue()


class SheetReader:
    """Stands in for twin_reads.read on the suggest route; records each call."""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, kind, images, context, *, run, step):
        self.calls.append({'kind': kind, 'images': len(images), 'context': copy.deepcopy(context)})
        return {'pages': copy.deepcopy(self.pages)}


def _rows_for(rows, source, page):
    return [row for row in rows if row['source'] == source and row['page'] == page]


def scenario_place_crud():
    _fresh()
    _setup()
    c = _client()
    with _enforced():
        r = c.post('/api/house/editor/place/buildings', headers=PARENT, json={'name': 'Garage', 'kind': 'garage'})
        check(r.status_code == 200, r.text)
        body = r.json()
        b = body['building']
        check(b['id'] == 'garage' and b['name'] == 'Garage' and b['kind'] == 'garage', body)
        check(body['summary'] == 'Added Garage.', body)
        check([x['id'] for x in ts.place()['buildings']] == ['garage'], ts.place())

        dup = c.post('/api/house/editor/place/buildings', headers=PARENT, json={'name': 'Garage', 'kind': 'garage'})
        check(dup.status_code == 400 and dup.json()['detail'] == 'There is already a building called Garage.',
              dup.text)
        check(len(ts.place()['buildings']) == 1, 'a refused add changes nothing')
        odd = c.post('/api/house/editor/place/buildings', headers=PARENT, json={'name': 'Folly', 'kind': 'castle'})
        check(odd.status_code == 400 and odd.json()['detail'].startswith('Choose a kind'), odd.text)

        got = c.get('/api/house/editor/sheets', headers=PARENT)
        check(got.status_code == 200, got.text)
        got = got.json()
        place = got['place']
        check([x['id'] for x in place['buildings']] == ['garage'] and {'lot', 'photo_tags'} <= set(place), place)
        check([k['label'] for k in got['kinds']] == KIND_LABELS, got['kinds'])
        check([k['id'] for k in got['kinds']] == KIND_IDS, got['kinds'])
        check(got['roles'] == PLACE_ROLES, got['roles'])
        check(isinstance(got.get('estimates'), dict), ('estimates is an object (Task 3 fills it)', got.get('estimates')))
        check({'sources', 'pages', 'page_roles', 'registrations', 'piece_labels', 'field_labels'} <= set(got),
              'slice 1 keys stay')

        r = c.patch('/api/house/editor/place/buildings/garage', headers=PARENT, json={'shell': {'storeys': 2}})
        check(r.status_code == 200, r.text)
        b = r.json()['building']
        check(b['id'] == 'garage' and b['shell']['storeys'] == 2 and b['shell_from'] == 'person', b)
        check(b['shell']['wall_height'] == 9 and b['shell']['roof'] == 'gable', ('a partial shell keeps the rest', b))
        check(r.json()['summary'] == 'Updated Garage.', r.json())
        check(ts.place()['buildings'][0]['shell']['storeys'] == 2, 'the change is saved')

        bad = c.patch('/api/house/editor/place/buildings/garage', headers=PARENT, json={'shell': {'storeys': 0}})
        check(bad.status_code == 400 and _plain(bad.json()['detail']), bad.text)
        check(ts.place()['buildings'][0]['shell']['storeys'] == 2, 'a refused change changes nothing')
        missing = c.patch('/api/house/editor/place/buildings/nope', headers=PARENT, json={'name': 'Nope'})
        check(missing.status_code in (400, 404), ('an unknown building is refused, never a 500', missing.text))

        r = c.delete('/api/house/editor/place/buildings/garage', headers=PARENT)
        check(r.status_code == 200, r.text)
        check(r.json()['status'] == 'ok' and r.json()['summary'] == 'Removed Garage.', r.json())
        check(ts.place()['buildings'] == [], ts.place())


def scenario_upload_with_part():
    _fresh()
    _setup()
    c = _client()
    with _enforced():
        r = c.post('/api/house/twin/sources', headers=PARENT, data={'kind': 'drawing', 'part': 'lot'},
                   files={'file': ('plot.pdf', engine_tests._pdf(1), 'application/pdf')})
        check(r.status_code == 200 and r.json()['part'] == 'lot', r.text)
        r = c.post('/api/house/twin/sources', headers=PARENT, data={'kind': 'photo', 'part': 'lot'},
                   files={'file': ('yard.png', _png(), 'image/png')})
        check(r.status_code == 200 and r.json()['part'] == 'lot', r.text)
        photo = r.json()['id']
        check(ts.photos_for('lot') == [photo], ts.photos_for('lot'))

        before = len(ts.sources())
        bad = c.post('/api/house/twin/sources', headers=PARENT, data={'kind': 'drawing', 'part': 'nope'},
                     files={'file': ('x.pdf', engine_tests._pdf(1), 'application/pdf')})
        check(bad.status_code == 400 and _plain(bad.json()['detail']), bad.text)
        check(len(ts.sources()) == before, 'a refused upload saves nothing')

        # Controller ruling R3: a drawing with no part (slice 1 callers) goes to house.
        legacy = c.post('/api/house/twin/sources', headers=PARENT, data={'kind': 'drawing'},
                        files={'file': ('lot58.pdf', engine_tests._pdf(1), 'application/pdf')})
        check(legacy.status_code == 200 and legacy.json()['part'] == 'house', legacy.text)
        check('house' in [x['id'] for x in ts.place()['buildings']], 'a legacy drawing adds Main house')


def scenario_photo_parts_route():
    _fresh()
    _setup()
    ts.add_building('Garage', 'garage')
    photo = ts.save_source('photo', 'front.png', _png(), part='lot')
    c = _client()
    with _enforced():
        r = c.put(f'/api/house/editor/place/photos/{photo}', headers=PARENT, json={'parts': ['lot', 'garage']})
        check(r.status_code == 200 and sorted(r.json()['parts']) == ['garage', 'lot'], r.text)
        check(photo in ts.photos_for('garage') and photo in ts.photos_for('lot'), 'tags saved')
        bad = c.put(f'/api/house/editor/place/photos/{photo}', headers=PARENT, json={'parts': ['nope']})
        check(bad.status_code == 400 and _plain(bad.json()['detail']), bad.text)
        check(photo in ts.photos_for('garage'), 'a refused tag change changes nothing')
        gone = c.put('/api/house/editor/place/photos/nope', headers=PARENT, json={'parts': ['lot']})
        check(gone.status_code in (400, 404), ('an unknown photo is refused, never a 500', gone.text))


def scenario_move_page_route():
    _fresh()
    _setup()
    sheets = ts.save_source('drawing', 'lot58.pdf', engine_tests._pdf(2))   # no part: goes to house
    ts.set_page_roles([{'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None,
                        'building': 'house'},
                       {'source': sheets, 'page': 2, 'role': 'roof', 'level': None, 'box': None,
                        'building': 'house'}])
    c = _client()
    with _enforced():
        r = c.post('/api/house/editor/place/pages/move', headers=PARENT,
                   json={'source': sheets, 'page': 1, 'part': 'lot'})
        check(r.status_code == 200, r.text)
        for rows in (r.json()['page_roles'], ts.page_roles()):
            moved = _rows_for(rows, sheets, 1)
            check(len(moved) == 1 and moved[0]['building'] == 'lot' and moved[0]['role'] == 'other'
                  and moved[0]['level'] is None, ('a floor page moved to the lot becomes Other', moved))
        stay = _rows_for(ts.page_roles(), sheets, 2)
        check(len(stay) == 1 and stay[0]['role'] == 'roof' and stay[0]['building'] == 'house', stay)

        before = ts.page_roles()
        bad = c.post('/api/house/editor/place/pages/move', headers=PARENT,
                     json={'source': sheets, 'page': 2, 'part': 'nope'})
        check(bad.status_code == 400 and _plain(bad.json()['detail']), bad.text)
        check(ts.page_roles() == before, 'a refused move changes nothing')


def scenario_move_region_route():
    _fresh()
    _setup()
    sheets = ts.save_source('drawing', 'regions.pdf', engine_tests._pdf(1))
    ts.add_building('Garage', 'garage')
    original = [
        {'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor',
         'box': [0, 0, 0.5, 1], 'building': 'house'},
        {'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Upper floor',
         'box': [0.5, 0, 1, 1], 'building': 'house'}]
    ts.set_page_roles(original)
    c = _client()
    with _enforced():
        before = ts.page_roles()
        bad = c.post('/api/house/editor/place/pages/move', headers=PARENT,
                     json={'source': sheets, 'page': 1, 'part': 'garage', 'region': -1})
        check(bad.status_code == 400 and _plain(bad.json()['detail']), bad.text)
        check(ts.page_roles() == before, 'a negative region changes nothing')

        r = c.post('/api/house/editor/place/pages/move', headers=PARENT,
                   json={'source': sheets, 'page': 1, 'part': 'garage', 'region': 1})
        check(r.status_code == 200, r.text)
        second = {**original[1], 'building': 'garage'}
        check(r.json()['page_roles'] == [second], r.json())
        check(_rows_for(ts.page_roles(), sheets, 1) == [original[0], second],
              ('region one moves only the second row', ts.page_roles()))

        ts.set_page_roles(original)
        r = c.post('/api/house/editor/place/pages/move', headers=PARENT,
                   json={'source': sheets, 'page': 1, 'part': 'garage'})
        check(r.status_code == 200, r.text)
        expected = [{**row, 'building': 'garage'} for row in original]
        check(r.json()['page_roles'] == expected, r.json())
        check(_rows_for(ts.page_roles(), sheets, 1) == expected,
              ('omitting region moves both rows', ts.page_roles()))


def scenario_suggest_null_elsewhere():
    _fresh()
    _setup()
    sheets = ts.save_source('drawing', 'house.pdf', engine_tests._pdf(1))
    c = _client()
    page = {'page': 1, 'role': 'floor', 'level': 'Main', 'box': None}
    for elsewhere in (None, 7):
        reader = SheetReader([{**page, 'elsewhere': elsewhere}])
        with _enforced(), patch.object(twin_reads, 'read', reader):
            r = c.post('/api/house/editor/sheets/suggest', headers=PARENT, json={'source': sheets})
        check(r.status_code == 200, (elsewhere, r.text))
        check(r.json()['rows'] == [{**page, 'source': sheets, 'building': 'house'}],
              ('the row stays without elsewhere or a hint', elsewhere, r.json()))
        check(len(reader.calls) == 1 and ts.page_roles() == [],
              'suggestions read once and stay unsaved')

    # Problems in required fields must still refuse the suggestion.
    reader = SheetReader([{**page, 'role': 'attic', 'elsewhere': 7}])
    with _enforced(), patch.object(twin_reads, 'read', reader):
        bad = c.post('/api/house/editor/sheets/suggest', headers=PARENT, json={'source': sheets})
    check(bad.status_code == 400 and _plain(bad.json()['detail']), bad.text)
    check(ts.page_roles() == [], 'a refused suggestion saves nothing')


def scenario_suggest_hint():
    _fresh()
    _setup()
    sheets = ts.save_source('drawing', 'house.pdf', engine_tests._pdf(5))   # no part: goes to house
    check(next(s for s in ts.sources() if s['id'] == sheets)['part'] == 'house', 'the source belongs to house')
    ts.add_building('Garage', 'garage')
    reader = SheetReader([
        {'page': 1, 'role': 'floor', 'level': 'Main', 'box': None, 'elsewhere': 'garage'},
        {'page': 2, 'role': 'floor', 'level': 'Upper', 'box': None, 'elsewhere': 'nope'},    # unknown part
        {'page': 3, 'role': 'roof', 'level': None, 'box': None, 'elsewhere': 'house'},      # its own part
        {'page': 4, 'role': 'plot', 'level': None, 'box': None},                            # R4: lot role
        {'page': 5, 'role': 'survey', 'level': None, 'box': None}])                         # R4: lot role
    c = _client()
    with _enforced(), patch.object(twin_reads, 'read', reader):
        r = c.post('/api/house/editor/sheets/suggest', headers=PARENT, json={'source': sheets})
        check(r.status_code == 200, r.text)
        got = r.json()['rows']
        rows = {row['page']: row for row in got}
        check(len(got) == 5 and sorted(rows) == [1, 2, 3, 4, 5], got)
        check(all(row['source'] == sheets and row['building'] == 'house' for row in got), got)
        one = rows[1]
        check(one['role'] == 'floor' and one['level'] == 'Main', one)
        check(one['elsewhere'] == 'garage' and one['hint'] == 'Page 1 looks like the Garage.', one)
        for page in (2, 3):
            check(rows[page].get('elsewhere') is None and rows[page].get('hint') is None,
                  ('an elsewhere naming an unknown part or the source\'s own part is dropped', rows[page]))
        check(rows[2]['role'] == 'floor' and rows[3]['role'] == 'roof', (rows[2], rows[3]))
        check(rows[4]['role'] == 'other' and rows[5]['role'] == 'other',
              ('R4: a lot role suggested for a building source becomes other', rows[4], rows[5]))

        check([call['kind'] for call in reader.calls] == ['sheet_roles'], reader.calls)
        ctx = reader.calls[0]['context']
        check(ctx['source'] == sheets and ctx['pages'] == 5, ctx)
        check(ctx['part'] == {'id': 'house', 'name': 'Main house', 'kind': 'main_house'}, ctx['part'])
        parts = {p['id']: p for p in ctx['parts']}
        check(parts.get('garage') == {'id': 'garage', 'name': 'Garage', 'kind': 'garage'}
              and parts.get('house') == {'id': 'house', 'name': 'Main house', 'kind': 'main_house'}, ctx['parts'])
        check(ts.page_roles() == [], 'suggestions are not saved until the person confirms them')
        # Every suggested row is valid for its part: confirming them as offered saves.
        put = c.put('/api/house/editor/sheets/roles', headers=PARENT,
                    json={'rows': [{k: row[k] for k in ROW_KEYS} for row in got]})
        check(put.status_code == 200 and len(_rows_for(ts.page_roles(), sheets, 4)) == 1, put.text)

    plot = ts.save_source('drawing', 'plot.pdf', engine_tests._pdf(3), part='lot')
    reader = SheetReader([
        {'page': 1, 'role': 'floor', 'level': 'Main', 'box': None},
        {'page': 2, 'role': 'plot', 'level': None, 'box': None},
        {'page': 3, 'role': 'elevation', 'level': None, 'box': None}])
    with _enforced(), patch.object(twin_reads, 'read', reader):
        r = c.post('/api/house/editor/sheets/suggest', headers=PARENT, json={'source': plot})
        check(r.status_code == 200, r.text)
        got = r.json()['rows']
        rows = {row['page']: row for row in got}
        check(len(got) == 3 and all(row['building'] == 'lot' for row in got), got)
        check(rows[1]['role'] == 'other' and rows[1]['level'] is None,
              ('a floor suggestion for a lot source becomes other and its level clears', rows[1]))
        check(rows[2]['role'] == 'plot', rows[2])
        check(rows[3]['role'] == 'other', ('R4: a building role suggested for a lot source becomes other', rows[3]))
        check(reader.calls[0]['context']['part']['id'] == 'lot', reader.calls[0]['context'])
        put = c.put('/api/house/editor/sheets/roles', headers=PARENT,
                    json={'rows': [{k: row[k] for k in ROW_KEYS} for row in got]})
        check(put.status_code == 200, put.text)


# Slice 1b-i Task 3 (plan docs/superpowers/plans/2026-11-07-house-editor-slice-1b-i.md,
# amendments A4-A6): the plot plan read, its suggestions, the lot placement,
# photo suggestions and estimates, through the real twin_reads.read with
# model_pools.call_pool_json stubbed.
PLOT_API = [
    ('POST', '/api/house/editor/place/plot/read'),
    ('POST', '/api/house/editor/place/plot/suggestions/plot-1'),
    ('PUT', '/api/house/editor/place/lot/placement'),
    ('POST', '/api/house/editor/place/photos/suggest'),
]


class PlacePool:
    """Stands in for model_pools.call_pool_json: the plot fixture for the plot
    read, a photo answer for the photo read; each call reports usage."""

    def __init__(self, photo_answer):
        self.photo_answer, self.calls = photo_answer, []

    def __call__(self, tier, api_key, system_prompt, user_prompt, **kw):
        plot = system_prompt == twin_reads.PROMPTS.get('plot')
        self.calls.append({'kind': 'plot' if plot else 'other', 'images': len(kw.get('images') or [])})
        if kw.get('usage') is not None:
            kw['usage'].append({'model': PRICED, 'input_tokens': 1500, 'output_tokens': 300,
                                'images': len(kw.get('images') or []), 'prompt_chars': len(user_prompt),
                                'max_output_tokens': kw.get('max_output_tokens') or 0})
        return copy.deepcopy(engine_tests.fixture('plot') if plot else self.photo_answer)


def scenario_plot_routes():
    from services import model_pools
    _fresh()
    _setup()
    saved = {k: _real_settings().get(k) for k in ('llm_provider', 'llm_gemini_paid_api_key')}
    storage.patch_settings({'llm_provider': 'gemini', 'llm_gemini_paid_api_key': 'paid-k'})
    try:
        house = ts.save_source('drawing', 'house.pdf', engine_tests._pdf(1))      # no part: Main house
        plot = ts.save_source('drawing', 'plot.pdf', engine_tests._pdf(1), part='lot')
        photo = ts.save_source('photo', 'yard.png', _png(), part='lot')
        ts.set_page_roles([
            {'source': house, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
            {'source': plot, 'page': 1, 'role': 'plot', 'level': None, 'box': None, 'building': 'lot'}])
        pool = PlacePool({'photos': [{'index': 0, 'parts': ['house', 'lot']}], 'shells': []})
        c = _client()
        with _enforced(), patch.object(model_pools, 'call_pool_json', pool):
            for method, path in PLOT_API:
                for who in (MEMBER, PANEL, {}):
                    r = c.request(method, path, headers=who, json={})
                    check(r.status_code in (401, 403), ('parents only', method, path, r.status_code))
            check(pool.calls == [] and ts.place()['lot']['read'] is None, 'a refused caller reads nothing')

            r = c.post('/api/house/editor/place/plot/read', headers=PARENT, json={})
            check(r.status_code == 200, r.text)
            body = r.json()
            read = body['lot']['read']
            check([s['id'] for s in read['suggestions']] == ['plot-1', 'plot-2'], read['suggestions'])
            check(read['street_edge'] == [1, 2] and read['source'] == plot, read)
            check(read['cost'] > 0 and abs(body['cost'] - read['cost']) < 1e-9,
                  ('the route returns the ledger entry as cost', body.get('cost'), read['cost']))
            check([call['kind'] for call in pool.calls] == ['plot'] and pool.calls[0]['images'] == 1, pool.calls)
            check(ts.place()['lot']['read']['id'] == read['id'], 'the read is saved')

            r = c.post('/api/house/editor/place/plot/suggestions/plot-1', headers=PARENT,
                       json={'action': 'accept', 'name': 'Shed', 'kind': 'shed', 'read': read['id']})
            check(r.status_code == 200, r.text)
            body = r.json()
            check({'lot', 'place', 'summary'} <= set(body) and isinstance(body['summary'], str) and body['summary'],
                  body)
            shed = next((b for b in body['place']['buildings'] if b['id'] == 'shed'), None)
            check(shed is not None and shed['footprint_from'] == 'plot', body['place'])
            first = next(s for s in body['lot']['read']['suggestions'] if s['id'] == 'plot-1')
            check(first['state'] == 'accepted' and first['building'] == 'shed', first)
            again = c.post('/api/house/editor/place/plot/suggestions/plot-1', headers=PARENT,
                           json={'action': 'dismiss', 'read': read['id']})
            check(again.status_code == 400 and again.json()['detail'] == 'This suggestion was already answered.',
                  again.text)
            stale = c.post('/api/house/editor/place/plot/suggestions/plot-2', headers=PARENT,
                           json={'action': 'dismiss', 'read': '0' * 32})
            check(stale.status_code == 400
                  and stale.json()['detail'] == 'This plot plan read is out of date. Read it again.', stale.text)
            r = c.post('/api/house/editor/place/plot/suggestions/plot-2', headers=PARENT,
                       json={'action': 'accept', 'building': 'house', 'read': read['id']})
            check(r.status_code == 200, r.text)
            check(next(b for b in ts.place()['buildings'] if b['id'] == 'house')['footprint_from'] == 'plot',
                  ts.place()['buildings'])

            bow = c.put('/api/house/editor/place/lot/placement', headers=PARENT,
                        json={'footprints': [{'building': 'shed', 'outline': [[0, 0], [10, 10], [10, 0], [0, 10]]}]})
            check(bow.status_code == 400 and bow.json()['detail'] == 'A footprint cannot cross itself.', bow.text)
            check(ts.place()['lot']['placement'] is None, 'a refused placement saves nothing')
            r = c.put('/api/house/editor/place/lot/placement', headers=PARENT,
                      json={'street_edge': [0, 1], 'footprints': []})
            check(r.status_code == 200, r.text)
            placement = r.json()['lot']['placement']
            check(placement['confirmed'] is True and placement['street_edge'] == [0, 1]
                  and placement['source'] == plot, placement)
            check(ts.registration(plot, 1, None) == placement['registration'], 'the build will use this registration')

            got = c.get('/api/house/editor/sheets', headers=PARENT)
            check(got.status_code == 200, got.text)
            draft, rooms = tc.estimate('draft', 1), tc.estimate('draft_rooms', 1)
            check(got.json()['estimates'] == {'plot': tc.estimate('plot', 1), 'photos': tc.estimate('photo_parts', 1),
                  'build': {'house': {'draft': draft, 'draft_rooms': rooms, 'total': draft + rooms}}},
                  got.json()['estimates'])

            r = c.post('/api/house/editor/place/photos/suggest', headers=PARENT, json={})
            check(r.status_code == 200, r.text)
            photo_read = r.json()['photo_read']
            check(photo_read['photos'] == [{'source': photo, 'parts': ['house', 'lot']}], photo_read)
            check(photo_read['cost'] > 0 and abs(r.json()['cost'] - photo_read['cost']) < 1e-9,
                  (r.json().get('cost'), photo_read['cost']))
            check(ts.place()['photo_tags'][photo] == ['lot'], 'a suggestion never retags a photo')

            # A checkpoint answers 409 before any paid request, as the build route does.
            tc.record('step:outline', [{'model': PRICED, 'input_tokens': 1_100_000, 'output_tokens': 0}])
            calls = len(pool.calls)
            for path in ('/api/house/editor/place/plot/read', '/api/house/editor/place/photos/suggest'):
                r = c.post(path, headers=PARENT, json={})
                check(r.status_code == 409 and r.json()['detail']['checkpoint'] == 10.0, (path, r.status_code, r.text))
            check(len(pool.calls) == calls, ('nothing is asked past a checkpoint', pool.calls[calls:]))
            check(ts.place()['lot']['read']['id'] == read['id'], 'the earlier read stays')
    finally:
        storage.patch_settings(saved)


def scenario_build_part_route():
    # Slice 1b-i Task 6: the build route takes {part}, a string; the legacy
    # {building, photos} body still builds; a body with neither is refused.
    _fresh()
    _setup()
    reader = engine_tests.Reader()
    c = _client()
    build = '/api/house/editor/build'

    def status(bid):
        return c.get(f'{build}/{bid}', headers=PARENT).json()

    with _enforced(), patch.object(twin_reads, 'read', reader):
        r = c.post(build, headers=PARENT, json={})
        check(r.status_code == 400 and r.json()['detail'] == 'Choose what to build.', r.text)
        r = c.post(build, headers=PARENT, json={'part': 5})
        check(r.status_code == 400, ('a part is a string', r.status_code, r.text))
        r = c.post(build, headers=PARENT, json={'part': 'place'})
        check(r.status_code == 400 and r.json()['detail'] == 'Add a building with drawings or a footprint first.',
              r.text)
        check(tb.latest() is None and reader.calls == [], 'a refused build starts nothing')

        ts.add_building('Shed', 'shed')
        ts.update_building('shed', {'footprint': [[0, 0], [10, 0], [10, 12], [0, 12]], 'footprint_from': 'typed'})
        r = c.post(build, headers=PARENT, json={'part': 'place'})
        check(r.status_code == 200 and isinstance(r.json().get('id'), str), r.text)
        bid = r.json()['id']
        st = _wait(lambda: status(bid), lambda s: s['state'] != 'running')
        check(st['state'] == 'done' and st['part'] == 'shed' and st['next'] is None,
              ('the whole place is the shed', st['state'], st.get('part'), st.get('next')))
        r = c.post(build, headers=PARENT, json={'part': 'shed'})
        check(r.status_code == 200 and isinstance(r.json().get('id'), str), r.text)
        one = r.json()['id']
        st = _wait(lambda: status(one), lambda s: s['state'] != 'running')
        check(st['state'] == 'done' and st['part'] == 'shed', (st['state'], st.get('part')))
        check(reader.calls == [], ('a shell is never read', reader.calls))

        sheets = ts.save_source('drawing', 'house.pdf', engine_tests._pdf(1))     # no part: Main house
        ts.set_page_roles([{'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None,
                            'building': 'house'}])
        r = c.post(build, headers=PARENT, json={'building': {'id': 'house', 'name': 'Main house'}, 'photos': []})
        check(r.status_code == 200 and isinstance(r.json().get('id'), str), ('the legacy body still builds', r.text))
        legacy = r.json()['id']
        st = _wait(lambda: status(legacy), lambda s: s['state'] == 'paused')
        check(st['state'] == 'paused' and st['pause']['step'] == 'outline:L1', (st['state'], st.get('pause')))
        check(c.post(f'{build}/{legacy}/stop', headers=PARENT, json={}).status_code == 200, 'stop')


def scenario_sheets_migrates_before_returning_sources_and_rows():
    _fresh()
    _setup()
    sid = ts.save_source('drawing', 'legacy.pdf', engine_tests._pdf(1))
    with ts._LOCK:
        row = ts._state()
        row.pop('place', None)
        row['sources'][0].pop('part', None)
        row['page_roles'] = [{'source': sid, 'page': 1, 'role': 'plot', 'level': None, 'box': None, 'building': 'house'}]
        ts._save(row)
    with _enforced():
        r = _client().get('/api/house/editor/sheets', headers=PARENT)
    check(r.status_code == 200, r.text)
    data = r.json()
    check(data['page_roles'][0]['building'] == 'lot', data['page_roles'])
    check(data['sources'][0].get('part') == 'lot', data['sources'])


def scenario_suggest_roles_after_moving_one_page_reads_only_remaining_pages():
    _fresh()
    _setup()
    garage = ts.add_building('Garage', 'garage')['id']
    sid = ts.save_source('drawing', 'shared.pdf', engine_tests._pdf(3), part='house')
    ts.move_page(sid, 2, garage)
    stored = copy.deepcopy(ts.page_roles())
    calls = []

    def reader(kind, images, context, **kw):
        calls.append((kind, len(images), context))
        return {'pages': [{'page': p, 'role': 'floor', 'level': 'Floor', 'box': None} for p in (1, 3)]}

    with _enforced(), patch.object(twin_reads, 'read', reader):
        r = _client().post('/api/house/editor/sheets/suggest', headers=PARENT, json={'source': sid})
    check(r.status_code == 200, r.text)
    check(len(calls) == 1 and calls[0][1] == 2, calls)
    check(calls[0][2]['page_numbers'] == [1, 3], calls)
    check([row['page'] for row in r.json()['rows']] == [1, 3], r.json())
    check(ts.page_roles() == stored, 'the moved page stays saved and suggestions stay unsaved')


# Repair after the first live build (repair-brief.md R7): one download holds
# everything needed to see why a build came out as it did, and no secret.
SECRETS = {'llm_anthropic_api_key': 'sk-ant-record-SECRET-0001', 'llm_openai_api_key': 'sk-proj-record-SECRET-0002',
           'llm_gemini_paid_api_key': 'AIzaRecordSECRET0003', 'llm_gemini_api_key': 'AIzaRecordSECRET0004'}


def scenario_build_record_route():
    _fresh()
    _setup()
    sheets = ts.save_source('drawing', 'house.pdf', engine_tests._pdf(1))     # no part: Main house
    ts.set_page_roles([{'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None,
                        'building': 'house'}])
    ts.add_building('Shed', 'shed')
    ts.update_building('shed', {'footprint': [[100, 0], [110, 0], [110, 12], [100, 12]], 'footprint_from': 'typed'})
    reader = engine_tests.Reader()
    first = tb.start({'part': 'place'}, reader=reader, inline=True)
    st = engine_tests._accept_all(first)
    check(st['state'] == 'done' and st['next'], ('the house hands on to the shed', st['state'], st.get('next')))
    second = st['next']
    check(tb.status(second)['state'] == 'done', tb.status(second)['state'])
    tc.record('step:draft', [{'model': PRICED, 'input_tokens': 1000, 'output_tokens': 100, 'images': 1,
                                'prompt_chars': 1, 'max_output_tokens': 4096}], first)
    previous = {k: (storage.get_settings() or {}).get(k) for k in SECRETS}
    storage.patch_settings(SECRETS)
    calls = len(reader.calls)
    c = _client()
    try:
        with _enforced(), patch.object(twin_reads, 'read', reader):
            r = c.get('/api/house/editor/record', headers=PARENT)
            others = {list(who)[0] if who else 'nobody': c.get('/api/house/editor/record', headers=who).status_code
                      for who in (MEMBER, PANEL, {})}
    finally:
        storage.patch_settings(previous)
    check(r.status_code == 200, ('a parent downloads the build record', r.status_code, r.text[:300]))
    check(all(code in (401, 403) for code in others.values()), ('parents only', others))
    check(len(reader.calls) == calls, ('a record never reads', reader.calls[calls:]))
    text = r.text
    check(not any(secret in text for secret in SECRETS.values()) and 'api_key' not in text.lower(),
          'no key or settings secret in the record')
    record = r.json()
    same = lambda value: json.loads(json.dumps(value))
    check(record.get('plan') == same(ts.current()), ('the current plan', sorted(record)))
    check(record.get('place') == same(ts.place()), ('the place, with the lot read and placement', record.get('place')))
    check(record.get('registrations') == same(ts.registrations()), record.get('registrations'))
    check(record.get('ledger') == same(tc.entries()) and any(e.get('run') == first for e in record['ledger']),
          ('the cost ledger rows', record.get('ledger')))
    builds = record.get('builds')
    check(isinstance(builds, list) and [b.get('id') for b in builds] == [first, second],
          ('every build of the latest chain, in order', [b.get('id') for b in builds or []]))
    for build in builds:
        status = same(tb.status(build['id']))
        for key in ('state', 'events', 'pause', 'cost'):
            check(build.get(key) == status[key], (build['id'], key))
        check([s['id'] for s in build.get('steps', [])] == [s['id'] for s in status['steps']], build.get('steps'))
    steps = {s['id']: s for s in builds[0]['steps']}
    draft = steps['draft']['answer']
    check(draft['fragment']['building']['levels'] and len(draft['fragment']['building']['walls']) == 4,
          ('the whole-building answer is recorded', draft))
    check(draft['crop'] is None and draft['context']['pages'] ==
          [{'image': 0, 'role': 'floor', 'level_name': 'Main floor'}],
          ('the draft records its whole-page context instead of a wing crop', draft))
    rooms = steps['draft_rooms']['answer']
    check(rooms['fragment'] == {'rooms': [], 'walls': []}
          and len(rooms['context']['settled']['walls']) == 4,
          ('the rooms answer and its settled draft are recorded', rooms))


if __name__ == '__main__':
    failed = []
    for fn in (scenario_sheets_migrates_before_returning_sources_and_rows,
               scenario_suggest_roles_after_moving_one_page_reads_only_remaining_pages,
               scenario_every_editor_route_is_parents_only,
               scenario_page_renders_for_anyone,
               scenario_sheets_roles_and_page_images,
               scenario_build_runs_through_the_api,
               scenario_edit_returns_summary_and_plan,
               scenario_state_and_rounds,
               scenario_start_over_and_reset_need_intent,
               scenario_app_start_recovers_an_interrupted_build,
               scenario_suggest_roles_reads_once_and_saves_nothing,
               scenario_a_build_from_before_a_start_over_is_gone,
               scenario_twin_page_has_no_tools_sheet_but_links_to_the_editor,
               scenario_place_crud,
               scenario_upload_with_part,
               scenario_photo_parts_route,
               scenario_move_page_route,
               scenario_move_region_route,
               scenario_suggest_null_elsewhere,
               scenario_suggest_hint,
               scenario_plot_routes,
               scenario_build_part_route,
               scenario_build_record_route):
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, '-', type(exc).__name__, exc)
        else:
            print('  ok ', fn.__name__)
    if failed:
        print('FAILED:', ', '.join(failed))
        sys.exit(1)
