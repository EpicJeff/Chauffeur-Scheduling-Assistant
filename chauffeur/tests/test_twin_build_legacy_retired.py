"""The legacy per-floor build path retires (plan
docs/superpowers/plans/2026-11-10-house-guided-build-piece-4.md, Task 9;
spec docs/superpowers/specs/2026-11-09-house-connected-model-design.md
section 8.3 approves the retirement).

- legacy_body_refuses: POST /api/house/editor/build with the old body
  {building: {id}, photos} and no part answers 400 with exactly
  'Build a part of your place.', starts nothing and reads nothing; a {part}
  body in the same place is still accepted.
- stored_legacy_build_reports_stopped: a legacy build saved on disk while in
  progress (running mid-read, paused at its scale_outline pause, or stopped by
  the person) reads stopped after recover() (what app start calls) with
  exactly one 'This build used an older path; start it again.' event, also
  after a second start; Resume never reads anything for it.
- part_builds_unchanged (guard, passes before and after): a part build fed by
  a replay stub reader (the household's recorded pool house reads) runs
  draft, draft_rooms, finishes, compose to done, never asks for a per-floor
  read kind, and settles the recorded levels and rooms.

Self-contained on purpose: no import of test_twin_build, whose legacy
scenarios this task retires. The stub readers stand in for twin_reads.read;
no model is ever called. Sources are blank PDFs and a blank JPEG.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_legacy_retired.py
"""
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import uuid
from unittest.mock import patch

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_build_legacy_retired_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import twin_build as tb  # noqa: E402
from services import twin_reads  # noqa: E402
from services import twin_register  # noqa: E402
from services import twin_store as ts  # noqa: E402

REFUSED = 'Build a part of your place.'
OLDER_PATH = 'This build used an older path; start it again.'
RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
# Read kinds only the per-floor path asks for. 'outline' is not here: a part
# build's draft still takes a disposable first look with it.
LEGACY_KINDS = {'walls', 'openings', 'rooms', 'registration', 'roof', 'pitch'}


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


# --- fixtures and fakes --------------------------------------------------------

def _pdf(pages, w=1224, h=792):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(w, h)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), (90, 120, 160)).save(buf, format='JPEG')
    return buf.getvalue()


def _recorded(name):
    with open(os.path.join(RECORDED, name), encoding='utf-8') as f:
        return json.load(f)


class Recorder:
    """A reader that must never be asked: records each call and answers an error."""

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, kind, images, context, *, run, step):
        with self._lock:
            self.calls.append((kind, step))
        return {'error': 'This reader should not have been asked.'}


class ReplayReader:
    """Answers the household's recorded pool house reads by kind; the first
    look fails (it is disposable), finishes answer empty materials, the roof
    photo reads answer a front view with every side hidden."""

    def __init__(self, draft, rooms):
        self.draft, self.rooms = draft, rooms
        self.kinds = []
        self._lock = threading.Lock()

    def __call__(self, kind, images, context, *, run, step):
        with self._lock:
            self.kinds.append(kind)
        if kind in ('draft', 'draft_level'):
            return copy.deepcopy(self.draft)
        if kind == 'draft_rooms':
            return copy.deepcopy(self.rooms)
        if kind == 'outline':
            return {'error': 'The model did not answer in 120 s.'}
        if kind == 'finishes':
            return {'materials': {}}
        if kind == 'photo_map':
            return {'from_side': 'front', 'blocks': [{'id': b['id'], 'sides': ['front']} for b in context['blocks']]}
        if kind == 'roof_observe':
            return {'blocks': {b['id']: {'sides': {side: {'kind': 'hidden'}
                              for side in ('front', 'rear', 'left', 'right')}} for b in context['blocks']}}
        return {'error': f'The replay has no answer for {kind}.'}


# --- helpers -------------------------------------------------------------------

_real_settings = storage.get_settings


def _enforced():
    return patch.object(storage, 'get_settings', side_effect=lambda: {**_real_settings(), 'auth_enforce': True})


def _fresh():
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    tb._forget()


PARENT = None


def _parent():
    global PARENT
    if PARENT is None:
        storage.add_member({'id': 'p1', 'name': 'Pat', 'role': 'parent'})
        PARENT = {'X-Member-Token': storage.create_member_token('p1')}
    return PARENT


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app)


def _house_drawings():
    """The Main house with one floor page, one roof page and a photo: the
    shape a legacy body built from."""
    sheets = ts.save_source('drawing', 'house.pdf', _pdf(2))          # no part: Main house, id house
    ts.set_page_roles([
        {'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': sheets, 'page': 2, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'}])
    photo = ts.save_source('photo', 'front.jpg', _jpeg(), part='house')
    return sheets, photo


def _accept_all(bid, limit=20):
    for _ in range(limit):
        st = tb.status(bid)
        if st['state'] != 'paused':
            return st
        tb.answer(bid, st['pause']['step'], {'accept': True})
    raise AssertionError('too many pauses')


def _wait(fn, until, timeout=20):
    deadline = time.time() + timeout
    value = fn()
    while time.time() < deadline and not until(value):
        time.sleep(0.05)
        value = fn()
    return value


def _legacy_step(kind, sid, *, source=None, page=None, level=None, level_name=None, pause=None,
                 status='pending', label=None):
    """A step exactly as the per-floor path saved it (twin_build._step)."""
    return {'id': sid, 'kind': kind, 'label': label or sid, 'pause': pause, 'source': source, 'page': page,
            'level': level, 'box': None, 'status': status, 'level_name': level_name or level}


def _write_legacy_build(state, sheets, photo):
    """Save a legacy {building} build's state.json on disk, as an older add-on
    left it at upgrade, and return its id."""
    bid = uuid.uuid4().hex
    floor = dict(source=sheets, page=1, level='L1', level_name='Main floor')
    outline_status = {'running': 'done', 'paused': 'paused', 'stopped': 'done'}[state]
    walls_status = 'running' if state == 'running' else 'pending'
    steps = [_legacy_step('outline', 'outline:L1', pause='scale_outline', status=outline_status,
                          label='Main floor outline', **floor),
             _legacy_step('openings', 'openings:L1', label='Main floor openings', **floor),
             _legacy_step('rooms', 'rooms:L1', label='Main floor rooms', **floor),
             _legacy_step('roof', 'roof', source=sheets, page=2, label='Roof'),
             _legacy_step('finishes', 'finishes', label='Finishes'),
             _legacy_step('compose', 'compose', label='Compose')]
    if state != 'paused':
        # The outline's wings expanded into walls steps after it was accepted.
        steps.insert(1, _legacy_step('walls', 'walls:L1:main', status=walls_status,
                                     label='Main floor main walls', **floor))
    events = [{'seq': 1, 'type': 'stage', 'step': 'outline:L1', 'label': 'Main floor outline'}]
    pause = None
    if state == 'paused':
        pause = {'id': f'{bid}:outline:L1:2', 'kind': 'scale_outline', 'step': 'outline:L1', 'why': '',
                 'confidence': 0.8, 'registration': twin_register.make(0.0274, origin_px=[1020, 2710]),
                 'rms': 0.0, 'dimension_ft': 70.0, 'size_ft': [70.0, 65.33]}
        events.append({'seq': 2, 'type': 'pause', **copy.deepcopy(pause)})
    build = {'id': bid, 'inputs': {'building': {'id': 'house', 'name': 'Main house'}, 'photos': [photo],
                                   'compose': True, 'then': []},
             'generation': ts.generation(), 'state': state, 'steps': steps,
             'placement': None, 'plot_read': None, 'next': None,
             'events': events, 'seq': len(events), 'pause': pause, 'cost': 0.0, 'existing': False}
    root = os.path.join(ts.DATA_DIR, 'builds', bid)
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, 'state.json'), 'w', encoding='utf-8') as f:
        json.dump(build, f)
    return bid


def _older_path_events(st):
    return [e for e in st['events'] if e.get('text') == OLDER_PATH]


# --- scenarios -----------------------------------------------------------------

def scenario_legacy_body_refuses():
    _fresh()
    headers = _parent()
    _, photo = _house_drawings()
    reader = Recorder()
    c = _client()
    build = '/api/house/editor/build'
    with _enforced(), patch.object(twin_reads, 'read', reader):
        for body in ({'building': {'id': 'house', 'name': 'Main house'}, 'photos': [photo]},
                     {'building': {'id': 'house', 'name': 'Main house'}, 'photos': []},
                     {'building': {'id': 'house'}}):
            r = c.post(build, headers=headers, json=body)
            if r.status_code == 200:
                # Still accepted (the path is not retired yet): stop it so its
                # worker cannot outlive this scenario, then fail.
                started = r.json()['id']
                _wait(lambda: tb.status(started), lambda s: s['state'] != 'running')
                tb.stop(started)
            check(r.status_code == 400,('the legacy body is refused', body, r.status_code, r.text))
            check(r.json().get('detail') == REFUSED, ('in these exact words', body, r.json()))
        check(tb.latest() is None, ('a refused legacy body starts no build', tb.latest()))
        check(not os.path.isdir(os.path.join(ts.DATA_DIR, 'builds'))
              or not os.listdir(os.path.join(ts.DATA_DIR, 'builds')), 'and saves no build record')
        check(reader.calls == [], ('and reads nothing', reader.calls))

        # The part body in the same place is still the way to build.
        replay = ReplayReader(_recorded('draft-pool-house.json'), _recorded('draft_rooms-pool-house.json'))
    with _enforced(), patch.object(twin_reads, 'read', replay):
        r = c.post(build, headers=headers, json={'part': 'house'})
        check(r.status_code == 200 and isinstance(r.json().get('id'), str), ('a part body still builds', r.text))
        bid = r.json()['id']
        st = _wait(lambda: c.get(f'{build}/{bid}', headers=headers).json(), lambda s: s['state'] != 'running')
        check(st['state'] in ('paused', 'done') and st.get('part') == 'house',
              ('the part build runs', st['state'], st.get('part'),
               [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
        if st['state'] != 'done':
            check(c.post(f'{build}/{bid}/stop', headers=headers, json={}).status_code == 200, 'stop')


def scenario_stored_legacy_build_reports_stopped():
    for state in ('running', 'paused', 'stopped'):
        _fresh()
        sheets, photo = _house_drawings()
        bid = _write_legacy_build(state, sheets, photo)
        tb._forget()
        tb.recover()                                      # what app start runs
        st = tb.status(bid)
        check(st['state'] == 'stopped', (state, 'a stored legacy build reads stopped', st['state'], st.get('pause')))
        said = _older_path_events(st)
        check(len(said) == 1, (state, 'it says so once, in these exact words',
                               [(e['type'], e.get('text')) for e in st['events']]))
        check(not any(s['status'] == 'running' for s in st['steps']),
              (state, 'no step is left running', [(s['id'], s['status']) for s in st['steps']]))

        tb._forget()
        tb.recover()                                      # a second start says nothing new
        st = tb.status(bid)
        check(st['state'] == 'stopped' and len(_older_path_events(st)) == 1,
              (state, 'a second start keeps it stopped and says it once', st['state'],
               [(e['type'], e.get('text')) for e in st['events']]))

        reader = Recorder()
        try:
            tb.resume(bid, reader=reader, inline=True)
        except ValueError:
            pass
        time.sleep(0.2)
        check(reader.calls == [], (state, 'Resume never reads for a retired build', reader.calls))
        st = tb.status(bid)
        check(st['state'] not in ('running', 'paused', 'checkpoint', 'done'),
              (state, 'Resume does not carry a retired build on', st['state']))


def scenario_part_builds_unchanged():
    _fresh()
    draft, rooms = _recorded('draft-pool-house.json'), _recorded('draft_rooms-pool-house.json')
    part = ts.add_building('Pool house', 'pool_house')['id']
    source = ts.save_source('drawing', 'pool.pdf', _pdf(3), part=part)
    names = [l['name'] for l in sorted(draft['building']['levels'], key=lambda l: l['elevation'])]
    ts.set_page_roles([
        {'source': source, 'page': 1, 'role': 'floor', 'level': names[0], 'box': None, 'building': part},
        {'source': source, 'page': 2, 'role': 'floor', 'level': names[1], 'box': None, 'building': part},
        {'source': source, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': part}])
    ts.save_source('photo', 'pool.jpg', _jpeg(), part=part)
    reader = ReplayReader(draft, rooms)
    bid = tb.start({'part': part}, reader=reader, inline=True)
    st = _accept_all(bid)
    check(st['state'] == 'done', ('the part build finishes', st['state'], st.get('pause'),
                                  [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    check(st.get('part') == part, st.get('part'))
    check([s['kind'] for s in st['steps']] == ['draft', 'draft_rooms', 'finishes', 'compose'],
          ('its usual steps', [s['id'] for s in st['steps']]))
    check(all(s['status'] == 'done' for s in st['steps']), [(s['id'], s['status']) for s in st['steps']])
    check(reader.kinds.count('draft') == 1 and reader.kinds.count('draft_rooms') == 1,
          ('one draft read and one rooms read', reader.kinds))
    check(not LEGACY_KINDS & set(reader.kinds), ('no per-floor read kind is asked', reader.kinds))
    check(not _older_path_events(st), 'a part build never says it used an older path')
    house = next(h for h in ts.current()['buildings'] if h['id'] == part)
    check(len(house['levels']) == len(draft['building']['levels']),
          ('the recorded levels settle', [l['id'] for l in house['levels']]))
    check(house.get('rooms'), ('the recorded rooms settle', len(house.get('rooms') or [])))


SCENARIOS = (
    scenario_legacy_body_refuses,
    scenario_stored_legacy_build_reports_stopped,
    scenario_part_builds_unchanged,
)


if __name__ == '__main__':
    failed = []
    for fn in SCENARIOS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} passed')
    sys.exit(1 if failed else 0)
