"""The round store holds the connected model (spec docs/superpowers/specs/
2026-11-09-house-connected-model-design.md sections 4.6a and 4.7; plan
docs/superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md Task 6;
brief .superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/task-6-brief.md).

Plan ruling P1: `current()` returns the flat (schema 2) view, the same shape
callers get today, so the build pipeline is untouched; new code reads
`current_model()` (schema 3).

Interfaces under test (services/twin_store.py, services/twin_record.py, main.py):
  current_model() -> dict | None                schema chauffeur.twin.plan/3
  current() -> dict | None                      schema chauffeur.twin.plan/2
  push_round(flat, kind, ...) / update_current(mutator, kind, ...)
      take a flat plan and store assemble(plan, previous=current_model())
  update_model(mutator, kind='edit', note='', changes=()) -> int
      the mutator receives and returns schema 3
  rounds/{id} may hold schema 2 or 3; _read_round assembles schema 2 on read
  GET /api/house/editor/state adds `model`; the build record includes `model`

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_store_model.py
"""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback
from unittest.mock import patch

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_store_model_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import storage  # noqa: E402
from services import twin_plan  # noqa: E402
from services import twin_record  # noqa: E402
from services import twin_store as ts  # noqa: E402

SCHEMA_2 = 'chauffeur.twin.plan/2'
SCHEMA_3 = 'chauffeur.twin.plan/3'
HOUSEHOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'fixtures', 'twin_model', 'household-2026-11-09.json')
TOL = 1e-6


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------- fixtures

def _rect_poly(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _wall(wid, a, b, exterior=False):
    return {'id': wid, 'level': 'L1', 'from': list(a), 'to': list(b), 'exterior': exterior,
            'thickness': 0.5 if exterior else 0.33, 'height': 9}


def _box_walls(east, north=10):
    return [_wall('s', (0, 0), (east, 0), True), _wall('e', (east, 0), (east, north), True),
            _wall('n', (east, north), (0, north), True), _wall('w', (0, north), (0, 0), True)]


def _flat(walls, rooms, openings=()):
    return {'schema': SCHEMA_2, 'units': 'ft', 'materials': {},
            'buildings': [{'id': 'b1', 'name': 'Test house', 'position': [0, 0], 'rotation': 0,
                           'base': 0,
                           'levels': [{'id': 'L1', 'name': 'main floor', 'elevation': 0, 'ceiling': 9}],
                           'walls': list(walls), 'openings': list(openings), 'rooms': list(rooms),
                           'roof': {'sections': [], 'extensions': []},
                           'stairs': [], 'fixtures': [], 'lights': [], 'porches': []}],
            'site': {}}


def _with_free_walls(east, p_x, q_to):
    """A 30-ish x 10 box (east wall at `east`) holding free-standing walls
    p (vertical at x p_x, y 2 to 8) and q (horizontal at y 5, x 15 to q_to),
    with one stored room `hall` filling the box."""
    walls = _box_walls(east) + [_wall('p', (p_x, 2), (p_x, 8)), _wall('q', (15, 5), (q_to, 5))]
    hall = {'id': 'room-hall', 'level': 'L1', 'name': 'hall', 'polygon': _rect_poly(0, 0, east, 10)}
    return _flat(walls, [hall])


def _kitchen_dining():
    """Plan A: a 20 x 10 box split at x 10 by wall `mid`, kitchen west, dining east,
    with a door on mid."""
    walls = _box_walls(20) + [_wall('mid', (10, 0), (10, 10))]
    rooms = [{'id': 'room-k', 'level': 'L1', 'name': 'kitchen', 'polygon': _rect_poly(0, 0, 10, 10)},
             {'id': 'room-d', 'level': 'L1', 'name': 'dining', 'polygon': _rect_poly(10, 0, 20, 10)}]
    door = {'id': 'door-1', 'wall': 'mid', 'at': 5, 'width': 3, 'sill': 0, 'head': 7, 'kind': 'door'}
    return _flat(walls, rooms, [door])


def _household():
    with open(HOUSEHOLD, encoding='utf-8') as fh:
        return json.load(fh)


# ---------------------------------------------------------------- store helpers

def _fresh():
    storage.patch_settings({'house_twin': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)


def _round_file(rid):
    return Path(ts.DATA_DIR) / 'rounds' / f'{rid}.json'


def _old_round(plan, rid=1):
    """Write a round exactly as the store wrote it before this change: the
    normalized schema-2 plan in rounds/{id}.json and its metadata row."""
    flat, _ = twin_plan.normalize(copy.deepcopy(plan))
    check(flat['schema'] == SCHEMA_2, 'the old round is schema 2')
    target = _round_file(rid)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(flat, ensure_ascii=False), encoding='utf-8')
    row = copy.deepcopy(storage.get_settings().get('house_twin') or {})
    row.setdefault('generation', 0)
    row.setdefault('rounds', [])
    row['rounds'].append({'id': rid, 'kind': 'build', 'created': '2026-11-01T00:00:00+00:00',
                          'note': '', 'cost': None, 'run': None, 'stale': False})
    row['current'] = rid
    storage.patch_settings({'house_twin': row})
    return target.read_text(encoding='utf-8')


def _same(value):
    return json.loads(json.dumps(value))


def _by_id(items):
    return {item['id']: item for item in items}


def _near(a, b, tol=TOL):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 <= tol


def _same_segment(a, b, p, q, tol=TOL):
    return (_near(a, p, tol) and _near(b, q, tol)) or (_near(a, q, tol) and _near(b, p, tol))


def _model_ends(building, wall):
    joints = {j['id']: j['at'] for j in building['joints']}
    return joints[wall['joints'][0]], joints[wall['joints'][1]]


def _live(pieces):
    return [p for p in pieces if p.get('state') != 'proposal']


def _joint_at(building, point):
    hits = [j for j in building['joints'] if _near(j['at'], point)]
    check(len(hits) == 1, f'one joint at {point}: {hits}')
    return hits[0]


def _flat_shape(flat):
    """What a flat plan draws, without the derived extras (joint ids, footprints):
    per building, walls by id with ends and kind, rooms by id with name and level,
    openings by id with wall and at."""
    shape = {}
    for b in flat['buildings']:
        shape[b['id']] = {
            'walls': {w['id']: (sorted([[round(v, 6) for v in w['from']], [round(v, 6) for v in w['to']]]),
                                w.get('kind', 'solid'))
                      for w in b['walls']},
            'rooms': {r['id']: (r['name'], r['level']) for r in b['rooms']},
            'openings': {o['id']: (o.get('wall'), round(o['at'], 6)) for o in b['openings']},
        }
    return shape


def _no_dropped(flat, what):
    dropped = [n for n in twin_plan.normalize(copy.deepcopy(flat))[1] if n.startswith('Dropped')]
    check(not dropped, f'{what}: the flat view must normalize without drops: {dropped[:6]}')


# ---------------------------------------------------------------- HTTP helpers (auth enforcement ON)

_real_settings = storage.get_settings
PARENT = MEMBER = None


def _enforced():
    return patch.object(storage, 'get_settings', side_effect=lambda: {**_real_settings(), 'auth_enforce': True})


def _setup_people():
    global PARENT, MEMBER
    if PARENT is None:
        storage.add_member({'id': 'p1', 'name': 'Pat', 'role': 'parent'})
        storage.add_member({'id': 'k1', 'name': 'Kit', 'role': 'child'})
        PARENT = {'X-Member-Token': storage.create_member_token('p1')}
        MEMBER = {'X-Member-Token': storage.create_member_token('k1')}


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app)


# ---------------------------------------------------------------- tests

def test_empty_store_has_no_model_and_no_plan():
    _fresh()
    check(ts.current_model() is None, 'an empty store has no model')
    check(ts.current() is None, 'an empty store has no flat plan')


def test_old_schema_2_round_reads_as_model_and_flat():
    _fresh()
    household = _household()
    stored = _old_round(household)

    model = ts.current_model()
    check(model is not None and model['schema'] == SCHEMA_3, f"current_model is schema 3: {model and model.get('schema')}")
    check([b['id'] for b in model['buildings']] == ['main-house', 'pool-house'],
          f"both buildings: {[b['id'] for b in model['buildings']]}")
    for old, b in zip(household['buildings'], model['buildings']):
        check(all('joints' in w and 'from' not in w for w in b['walls']),
              f"{b['id']}: model walls hang on joints, not from/to")
        rooms = _by_id(b['rooms'])
        for room in old['rooms']:
            check(room['id'] in rooms and rooms[room['id']]['name'] == room['name'],
                  f"{b['id']}: stored room {room['id']} {room['name']!r} survives in the model")

    flat = ts.current()
    check(flat is not None and flat['schema'] == SCHEMA_2, f"current() is the flat view: {flat and flat.get('schema')}")
    check([b['id'] for b in flat['buildings']] == ['main-house', 'pool-house'], 'the flat view keeps both buildings')
    for old, fb in zip(household['buildings'], flat['buildings']):
        check(all('from' in w and 'to' in w for w in fb['walls']), f"{fb['id']}: flat walls carry from/to")
        ids = {w['id'] for w in fb['walls']}
        for wall in old['walls']:
            check(wall['id'] in ids or any(i.startswith(wall['id'] + '~') for i in ids),
                  f"{fb['id']}: old wall {wall['id']} (or its split parts) is in the flat view")
        rooms = _by_id(fb['rooms'])
        for room in old['rooms']:
            check(room['id'] in rooms and rooms[room['id']]['name'] == room['name'],
                  f"{fb['id']}: stored room {room['id']} {room['name']!r} survives in the flat view")
    pool = _by_id(flat['buildings'])['pool-house']
    check({'Pool Lounge', 'SHWR.', 'CHANGING', 'EXERCISE', 'CLOSET'} <= {r['name'] for r in pool['rooms']},
          f"the pool house names are kept: {sorted(r['name'] for r in pool['rooms'])}")
    check(flat['site'] == household['site'], 'the site carries over exactly')
    _no_dropped(flat, 'the migrated household')

    # Reading never rewrites history: the old round stays schema 2 on disk.
    check(_round_file(1).read_text(encoding='utf-8') == stored, 'reading an old round leaves its file untouched')
    check(ts.current_id() == 1 and [r['id'] for r in ts.rounds()] == [1], 'reading adds no round')


def test_push_round_stores_the_model():
    _fresh()
    rid = ts.push_round(_kitchen_dining(), 'build')
    check(type(rid) is int and ts.current_id() == rid, f'push_round returns the new current round id: {rid}')
    stored = json.loads(_round_file(rid).read_text(encoding='utf-8'))
    check(stored['schema'] == SCHEMA_3, f"the round file holds the connected model: {stored.get('schema')}")
    model = ts.current_model()
    check(model['schema'] == SCHEMA_3, model['schema'])
    b = model['buildings'][0]
    check(all('joints' in w for w in b['walls']), 'model walls hang on joints')
    mid = _by_id(b['walls'])['mid']
    check(_same_segment(*_model_ends(b, mid), [10, 0], [10, 10]), f'mid stays at x 10: {_model_ends(b, mid)}')
    rooms = _by_id(b['rooms'])
    check(rooms['room-k']['name'] == 'kitchen' and rooms['room-d']['name'] == 'dining',
          f"kitchen and dining keep id and name: {[(r['id'], r['name']) for r in b['rooms']]}")
    flat = ts.current()
    check(flat['schema'] == SCHEMA_2, flat['schema'])
    fmid = _by_id(flat['buildings'][0]['walls'])['mid']
    check(_same_segment(fmid['from'], fmid['to'], [10, 0], [10, 10]), f'the flat mid runs x 10: {fmid}')
    door = _by_id(flat['buildings'][0]['openings'])['door-1']
    check(door['wall'] == 'mid' and abs(door['at'] - 5) <= TOL, f'the door keeps its wall and place: {door}')
    _no_dropped(flat, 'the pushed plan')


def test_push_round_of_flat_keeps_joint_ids_and_person_walls():
    _fresh()
    ts.push_round(_with_free_walls(30, 8, 25), 'build')
    model0 = ts.current_model()
    b0 = model0['buildings'][0]
    corner_sw = _joint_at(b0, [0, 0])['id']
    corner_nw = _joint_at(b0, [0, 10])['id']

    # The person drags p to x 9 through update_model (the mutator sees schema 3).
    seen = {}

    def drag_p(model):
        seen['schema'] = model['schema']
        b = model['buildings'][0]
        p = _by_id(b['walls'])['p']
        p['src'] = {'person': True}
        for joint in b['joints']:
            if joint['id'] in p['joints']:
                joint['at'] = [9, joint['at'][1]]
        return model

    edit = ts.update_model(drag_p, note='moved p')
    check(seen.get('schema') == SCHEMA_3, f"update_model's mutator receives schema 3: {seen}")
    check(type(edit) is int and ts.current_id() == edit, f'update_model returns the new current round: {edit}')
    check(ts.rounds()[-1]['kind'] == 'edit' and ts.rounds()[-1]['note'] == 'moved p',
          f"update_model defaults to kind edit and keeps the note: {ts.rounds()[-1]}")
    b1 = ts.current_model()['buildings'][0]
    p_joints = list(_by_id(b1['walls'])['p']['joints'])
    check(_same_segment(*_model_ends(b1, _by_id(b1['walls'])['p']), [9, 2], [9, 8]),
          'the edit is the current model')

    # A new read arrives as a flat plan: east wall at 33, p read 0.4 ft off at x 8.6.
    ts.push_round(_with_free_walls(33, 8.6, 25), 'build')
    b2 = ts.current_model()['buildings'][0]
    walls = _by_id(_live(b2['walls']))
    check(sorted(walls) == ['e', 'n', 'p', 'q', 's', 'w'], f'no duplicate p: {sorted(walls)}')
    p = walls['p']
    check(p['joints'] == p_joints, f"p keeps its joint ids {p_joints}, got {p['joints']}")
    check(_same_segment(*_model_ends(b2, p), [9, 2], [9, 8]), f"p stays where the person put it: {_model_ends(b2, p)}")
    check((p.get('src') or {}).get('person') is True, f"p stays the person's: {p}")
    check(_same_segment(*_model_ends(b2, walls['e']), [33, 0], [33, 10]), 'the untouched east wall takes the read')
    check(_joint_at(b2, [0, 0])['id'] == corner_sw and _joint_at(b2, [0, 10])['id'] == corner_nw,
          'joints the read did not move keep their ids')
    fp = _by_id(ts.current()['buildings'][0]['walls'])['p']
    check(_same_segment(fp['from'], fp['to'], [9, 2], [9, 8]), f'the flat view draws the person\'s p: {fp}')

    # update_current: the mutator sees the flat view and its result is assembled
    # against the current model, so the person's p still survives.
    def shorten_q(plan):
        seen['flat'] = plan['schema']
        q = _by_id(plan['buildings'][0]['walls'])['q']
        q['to'] = [24, 5]
        return plan

    ts.update_current(shorten_q, 'build')
    check(seen.get('flat') == SCHEMA_2, f"update_current's mutator receives the flat view: {seen}")
    b3 = ts.current_model()['buildings'][0]
    walls = _by_id(_live(b3['walls']))
    check(_same_segment(*_model_ends(b3, walls['q']), [15, 5], [24, 5]), f"q takes the change: {_model_ends(b3, walls['q'])}")
    check(walls['p']['joints'] == p_joints and (walls['p'].get('src') or {}).get('person') is True
          and _same_segment(*_model_ends(b3, walls['p']), [9, 2], [9, 8]),
          f"p keeps its ids, place and owner through update_current: {walls['p']}")
    check(_joint_at(b3, [0, 0])['id'] == corner_sw, 'the corner joint keeps its id through update_current')


def test_update_model_records_changes_and_kind():
    _fresh()
    ts.push_round(_kitchen_dining(), 'build')
    change = {'path': 'buildings[id=b1].rooms[id=room-k].name', 'kind': 'extraction',
              'before': 'kitchen', 'after': 'galley', 'reason': 'renamed'}

    def rename(model):
        _by_id(model['buildings'][0]['rooms'])['room-k']['name'] = 'galley'
        return model

    rid = ts.update_model(rename, kind='hand', note='renamed', changes=(change,))
    check(ts.rounds()[-1]['id'] == rid and ts.rounds()[-1]['kind'] == 'hand', f'kind is kept: {ts.rounds()[-1]}')
    fix = ts.fixes()[-1]
    check(fix['round'] == rid and fix['path'] == change['path'] and fix['after'] == 'galley',
          f'the change is logged against the round: {fix}')
    check(_by_id(ts.current_model()['buildings'][0]['rooms'])['room-k']['name'] == 'galley', 'the model has the edit')
    check(_by_id(ts.current()['buildings'][0]['rooms'])['room-k']['name'] == 'galley', 'the flat view has the edit')


def test_revert_to_a_schema_2_round_works():
    _fresh()
    stored = _old_round(_kitchen_dining())
    flat_a = ts.current()
    model_a = ts.current_model()
    check(model_a['schema'] == SCHEMA_3, 'the old round reads as schema 3')

    # Round 2: a different house, then a person's wall on top of it (round 3).
    r2 = ts.push_round(_with_free_walls(30, 8, 25), 'build')

    def own_p(model):
        _by_id(model['buildings'][0]['walls'])['p']['src'] = {'person': True}
        return model

    r3 = ts.update_model(own_p)
    flat_3 = ts.current()

    back = ts.revert(1)
    check(type(back) is int and back == r3 + 1 and ts.current_id() == back, f'revert makes a new current round: {back}')
    check(ts.rounds()[-1]['kind'] == 'revert', f"the round is a revert: {ts.rounds()[-1]}")
    model = ts.current_model()
    check(model['schema'] == SCHEMA_3, 'the reverted house is a model')
    b = model['buildings'][0]
    # s and n may come back split at mid's T (s~1 ...); compare by the wall each part came from.
    check(sorted({w['id'].split('~')[0] for w in _live(b['walls'])}) == ['e', 'mid', 'n', 's', 'w'],
          f"the earlier house comes back whole, without the later person's wall: {sorted(w['id'] for w in b['walls'])}")
    check({r['id']: r['name'] for r in b['rooms']} == {'room-k': 'kitchen', 'room-d': 'dining'},
          f"the rooms come back by id and name: {[(r['id'], r['name']) for r in b['rooms']]}")
    check(_flat_shape(ts.current()) == _flat_shape(flat_a),
          f'the flat view equals round 1 as it read: {_flat_shape(ts.current())} vs {_flat_shape(flat_a)}')
    check(_round_file(1).read_text(encoding='utf-8') == stored, 'reverting leaves the old round file untouched')

    # Reverting to a schema-3 round brings back that model, owner marks included.
    again = ts.revert(r3)
    check(ts.current_id() == again, again)
    b = ts.current_model()['buildings'][0]
    check((_by_id(b['walls'])['p'].get('src') or {}).get('person') is True, "round 3's person wall comes back")
    check(_flat_shape(ts.current()) == _flat_shape(flat_3), 'the flat view equals round 3')
    check(r2 < r3, (r2, r3))


def test_state_route_returns_model_and_plan():
    _fresh()
    _setup_people()
    c = _client()
    with _enforced():
        empty = c.get('/api/house/editor/state', headers=PARENT)
        check(empty.status_code == 200, (empty.status_code, empty.text[:300]))
        check(empty.json().get('model', 'missing') is None and empty.json().get('plan') is None,
              f"an empty house: model and plan are null: {empty.json()}")

    old = _old_round(_kitchen_dining())
    rid = ts.push_round(_with_free_walls(30, 8, 25), 'build')
    with _enforced():
        r = c.get('/api/house/editor/state', headers=PARENT)
        check(r.status_code == 200, (r.status_code, r.text[:300]))
        st = r.json()
        check(st['model'] == _same(ts.current_model()) and st['model']['schema'] == SCHEMA_3,
              f"state carries the model: {st.get('model', {}).get('schema') if isinstance(st.get('model'), dict) else st.get('model')}")
        check(st['plan'] == _same(ts.current()) and st['plan']['schema'] == SCHEMA_2, 'state keeps the flat plan')
        check([x['id'] for x in st['rounds']] == [1, rid] and 'cost' in st and 'build' in st,
              f'state keeps rounds, cost and build: {sorted(st)}')
        for who in (MEMBER, {}):
            denied = c.get('/api/house/editor/state', headers=who).status_code
            check(denied in (401, 403), f'state is parents only: {denied}')
        # The timeline: an old schema-2 round and a schema-3 round both read as flat plans.
        for round_id in (1, rid):
            tr = c.get(f'/api/house/twin/rounds/{round_id}', headers=PARENT)
            check(tr.status_code == 200 and tr.json()['plan']['schema'] == SCHEMA_2,
                  (round_id, tr.status_code, tr.text[:300]))
        names = {r['name'] for r in c.get('/api/house/twin/rounds/1', headers=PARENT).json()['plan']['buildings'][0]['rooms']}
        check(names == {'kitchen', 'dining'}, f'the old round reads with its rooms: {names}')
        walls = {w['id'] for w in c.get(f'/api/house/twin/rounds/{rid}', headers=PARENT).json()['plan']['buildings'][0]['walls']}
        check(walls == {'s', 'e', 'n', 'w', 'p', 'q'}, f'the schema-3 round reads flat: {walls}')
    check(_round_file(1).read_text(encoding='utf-8') == old, 'the timeline read leaves the old round untouched')


def test_record_download_includes_model():
    _fresh()
    _setup_people()
    ts.push_round(_kitchen_dining(), 'build')
    record = twin_record.record()
    check(record.get('model') == ts.current_model() and record['model']['schema'] == SCHEMA_3,
          f"the record carries the model: {sorted(record)}")
    check(record.get('plan') == ts.current() and record['plan']['schema'] == SCHEMA_2,
          'the record keeps the flat plan as before')
    c = _client()
    with _enforced():
        r = c.get('/api/house/editor/record', headers=PARENT)
    check(r.status_code == 200, (r.status_code, r.text[:300]))
    body = r.json()
    check(body.get('model') == _same(ts.current_model()), f"the downloaded record carries the model: {sorted(body)}")
    check(body.get('plan') == _same(ts.current()), 'the downloaded record keeps the flat plan')


def test_update_model_refuses_stale_generation_before_mutating():
    _fresh()
    ts.push_round(_kitchen_dining(), 'build')
    before = copy.deepcopy(storage.get_settings()['house_twin'])
    with patch.object(ts, '_append_round', side_effect=AssertionError('must not publish')):
        try:
            ts.update_model(lambda _: (_ for _ in ()).throw(AssertionError('must not mutate')),
                            generation=ts.generation() + 1)
        except ts.StaleGeneration:
            pass
        else:
            raise AssertionError('stale generation must be refused')
    check(storage.get_settings()['house_twin'] == before, 'stale edits leave the store unchanged')


def test_update_model_refuses_empty_house_before_mutating():
    _fresh()
    try:
        ts.update_model(lambda _: (_ for _ in ()).throw(AssertionError('must not mutate')))
    except ValueError as exc:
        check(str(exc) == 'There is no house yet.', str(exc))
    else:
        raise AssertionError('empty house must be refused')
    check(ts.current_id() is None and ts.rounds() == [], 'empty edits publish nothing')


def test_update_model_reconciles_registry_name_and_kind():
    _fresh()
    building = ts.add_building('Workshop', 'workshop')
    plan = _kitchen_dining()
    plan['buildings'][0].update(id=building['id'], name='Old name', kind='main_house')
    ts.push_round(plan, 'build')

    def edit(model):
        model['buildings'][0].update(name='Invented name', kind='pool_house')
        model['buildings'][0]['rooms'][0]['name'] = 'Edited room'
        return model

    rid = ts.update_model(edit, generation=ts.generation())
    saved = ts.current_model()['buildings'][0]
    check(saved['name'] == building['name'] and saved['kind'] == building['kind'], saved)
    check(any(r['name'] == 'Edited room' for r in saved['rooms']) and ts.current_id() == rid, saved)
    check(ts.place()['buildings'] == [building], ts.place())


TESTS = (
    test_update_model_refuses_stale_generation_before_mutating,
    test_update_model_refuses_empty_house_before_mutating,
    test_update_model_reconciles_registry_name_and_kind,
    test_empty_store_has_no_model_and_no_plan,
    test_old_schema_2_round_reads_as_model_and_flat,
    test_push_round_stores_the_model,
    test_push_round_of_flat_keeps_joint_ids_and_person_walls,
    test_update_model_records_changes_and_kind,
    test_revert_to_a_schema_2_round_works,
    test_state_route_returns_model_and_plan,
    test_record_download_includes_model,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
