"""Route-level raw-house preservation. Owner exports stay in memory; counts only."""
import argparse
import copy
from contextlib import ExitStack, redirect_stdout
import io
import json
import logging
import math
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='house_save_stable_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from services import storage, twin_model_bridge as bridge, twin_place, twin_register
from services import twin_store as ts
import main
logging.disable(logging.CRITICAL)


class MemoryHouse(ExitStack):
    """Real store/undo; synthetic rounds use TEMP, owner data stays in memory."""
    def __init__(self, model, state=None, persist=False):
        super().__init__()
        self.models = {1: copy.deepcopy(model)}
        self.row = {'current': 1, 'generation': 0, 'rounds': [{'id': 1, 'kind': 'build'}],
                    'place': twin_place.migrate({}, model), 'sources': [], 'page_roles': [],
                    'registrations': [], 'tombstones': [], 'fixes': [], 'pruned_runs': {}}
        if state:
            self.row.update(copy.deepcopy(state))
        ts._invalidate_reads()
        self.callback(ts._invalidate_reads)
        self.enter_context(patch.object(storage, 'get_settings', side_effect=lambda:
            {'house_twin': copy.deepcopy(self.row), 'auth_enforce': False}))
        if persist:
            root = Path(ts.DATA_DIR) / 'rounds'
            root.mkdir(parents=True, exist_ok=True)
            (root / '1.json').write_text(json.dumps(model), encoding='utf-8')
        else:
            self.enter_context(patch.object(ts, '_read_round', side_effect=lambda row, rid:
                copy.deepcopy(self.models[rid])))
        self.enter_context(patch.object(ts, '_save', side_effect=self.save))
        if not persist:
            self.enter_context(patch.object(ts, '_append_round', side_effect=self.append))
        self.enter_context(patch.object(ts, 'build_running', return_value=False))
        self.enter_context(patch.object(main, 'trigger_background_refresh'))

    def save(self, row):
        self.row = copy.deepcopy(row)
        ts._invalidate_reads()

    def append(self, row, model, kind, note='', cost=None, run=None, base=None, **kw):
        rid = max(self.models) + 1
        self.models[rid] = copy.deepcopy(model)
        row['rounds'].append(dict(id=rid, kind=kind, note=note, **kw))
        row['current'] = rid
        self.save(row)
        ts._write_through(row, json.dumps(model), kw.get('normalized', False))
        return rid


def fixture():
    flat = json.loads((Path(__file__).parent / 'fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = bridge.assemble(flat)[0]
    # Valid stored legacy details deliberately outside today's normal form.
    for b in model['buildings']:
        b['joints'].reverse()
        b['walls'].reverse()
        b['rooms'].reverse()
        b['levels'][0]['saved_detail'] = 'retain'
    model['site']['saved_detail'] = {'order': [3, 1, 2]}
    return model


def counts(before, after):
    """Count changed existing id records, added records, removed records, reordered lists."""
    result = [0, 0, 0, 0]
    def visit(a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            if 'id' in a and a != b:
                result[0] += 1
            for key in a.keys() & b.keys():
                visit(a[key], b[key])
        elif isinstance(a, list) and isinstance(b, list):
            if a and b and all(isinstance(p, dict) and 'id' in p for p in a + b):
                aa, bb = {p['id']: p for p in a}, {p['id']: p for p in b}
                result[1] += len(bb.keys() - aa.keys())
                result[2] += len(aa.keys() - bb.keys())
                result[3] += [p['id'] for p in a if p['id'] in bb] != [p['id'] for p in b if p['id'] in aa]
                for key in aa.keys() & bb.keys():
                    visit(aa[key], bb[key])
            else:
                for x, y in zip(a, b):
                    visit(x, y)
    visit(before, after)
    return result


def setup_plot(memory, model, bid):
    """Synthetic plot metadata only; the stored house is never normalized."""
    b = next(b for b in bridge.flatten(model)['buildings'] if b['id'] == bid)
    level = min(b['levels'], key=lambda l: l.get('elevation', 0))
    outline = level['outline']
    reg = twin_register.make(1)
    lot = [[0, 0], [500, 0], [500, -500], [0, -500]]
    crop = {'box': [0, 0, 1, 1], 'master': [500, 500], 'size': [500, 500]}
    memory.row['place']['lot']['read'] = {
        'id': 'synthetic-read', 'source': 'synthetic-source', 'page': 1, 'box': None,
        'crop': crop, 'fragment': {'lot': [[0, 0], [1, 0], [1, 1], [0, 1]], 'buildings': []},
        'registration': reg, 'street_edge': [0, 1], 'lot': lot, 'suggestions': []}
    memory.row['sources'].append({'id': 'synthetic-source', 'kind': 'drawing', 'pages': 1, 'part': 'lot'})
    memory.row['page_roles'] = [p for p in memory.row['page_roles'] if p['role'] != 'plot']
    memory.row['page_roles'].append({'source': 'synthetic-source', 'page': 1, 'role': 'plot',
                                    'building': 'lot', 'box': None})
    target = next(b for b in memory.row['place']['buildings'] if b['id'] == bid)
    target['footprint'] = copy.deepcopy(outline)
    # Include rotation as well as translation; every attachment stays local.
    angle = math.radians(31)
    return [[p[0] * math.cos(angle) - p[1] * math.sin(angle) + 13,
             p[0] * math.sin(angle) + p[1] * math.cos(angle) + 17] for p in outline]


def exercise(model, label, state=None):
    failures = []
    bid = next(b['id'] for b in model['buildings'] if not b.get('src', {}).get('person') and b['levels'])
    client = TestClient(main.app)
    for operation in ('rename', 'kind', 'refit'):
        with MemoryHouse(model, state, persist=(label == 'synthetic')) as memory:
            footprint = setup_plot(memory, model, bid)
            old_footprint = copy.deepcopy(next(b for b in memory.row['place']['buildings'] if b['id'] == bid)['footprint'])
            before = copy.deepcopy(model)
            original = next(b for b in model['buildings'] if b['id'] == bid)
            target_kind = 'shed' if original.get('kind') != 'shed' else 'garage'
            expected = copy.deepcopy(before)
            target = next(b for b in expected['buildings'] if b['id'] == bid)
            if operation == 'rename':
                target['name'] = 'Regression building'
            elif operation == 'kind':
                target['kind'] = target_kind
            else:
                flat = bridge.flatten(model)
                building = next(b for b in flat['buildings'] if b['id'] == bid)
                level = min(building['levels'], key=lambda l: l.get('elevation', 0))
                move, _ = twin_register.fit_outline(level['outline'], footprint)
                target.update(position=move['offset'], rotation=move['angle'] % 360)
            rename_to = target['name']
            def request():
                if operation == 'refit':
                    return client.put('/api/house/editor/place/lot/placement', json={
                        'footprints': [{'building': bid, 'outline': footprint}]})
                return client.patch(f'/api/house/editor/place/buildings/{bid}', json={
                    'name': rename_to} if operation == 'rename' else {'kind': target_kind})
            def send():
                # Slow-request middleware prints route ids independently of logging.
                with redirect_stdout(io.StringIO()):
                    return request()
            for turn in (1, 2):
                response = send()
                assert response.status_code == 200, f'{label} {operation}: route failed ({response.status_code})'
                after = ts.current_model()
                assert memory.row['rounds'][-1]['kind'] == 'edit'
                assert memory.row['rounds'][-1]['note']
                print(label, operation, turn, 'changed/added/removed/reordered', counts(before, after),
                      'unexpected', counts(expected, after), flush=True)
                if after != expected:
                    failures.append(f'{label} {operation} {turn}: stored records differ')
                # A second identical request is a no-op, with the same response shape.
                rid = ts.current_id()
                again = send()
                assert again.status_code == 200 and again.json().keys() == response.json().keys()
                if ts.current_id() != rid or ts.current_model() != after:
                    failures.append(f'{label} {operation} {turn}: repeated save drifted')
                if turn == 2:
                    # Two meaningful edits without an intervening undo. A second
                    # identical request alone would not enter the old flat writer.
                    second = copy.deepcopy(expected)
                    second_target = next(b for b in second['buildings'] if b['id'] == bid)
                    if operation == 'rename':
                        rename_to = second_target['name'] = 'Regression building two'
                    elif operation == 'kind':
                        target_kind = second_target['kind'] = 'studio'
                    else:
                        footprint = [[p[0] + 7, p[1] - 9] for p in footprint]
                        move, _ = twin_register.fit_outline(level['outline'], footprint)
                        second_target.update(position=move['offset'], rotation=move['angle'] % 360)
                    response = send()
                    assert response.status_code == 200
                    consecutive = ts.current_model()
                    print(label, operation, 'consecutive', 'changed/added/removed/reordered',
                          counts(expected, consecutive), 'unexpected', counts(second, consecutive), flush=True)
                    if consecutive != second:
                        failures.append(f'{label} {operation}: consecutive edit drifted')
                    undo = client.post('/api/house/twin/revert', json={'round': rid})
                    assert undo.status_code == 200
                    if ts.current_model() != expected:
                        failures.append(f'{label} {operation}: consecutive undo not exact')
                undo = client.post('/api/house/twin/revert', json={'round': 1})
                assert undo.status_code == 200
                if ts.current_model() != before:
                    failures.append(f'{label} {operation} {turn}: undo not exact')
                restored = next(b for b in ts.place()['buildings'] if b['id'] == bid)
                old = next(b for b in twin_place.migrate({}, before)['buildings'] if b['id'] == bid)
                if any(restored[k] != old[k] for k in ('name', 'kind')):
                    failures.append(f'{label} {operation} {turn}: registry undo not exact')
                # Refit metadata remains a confirmed footprint today; explicitly
                # drag it away before the next refit (no house mutation).
                if operation == 'refit':
                    next(b for b in memory.row['place']['buildings'] if b['id'] == bid)['footprint'] = copy.deepcopy(old_footprint)
    return failures


def multi_building_history_jumps(model):
    """History-list jumps must reconcile every raw building edit they cross."""
    failures = []
    client = TestClient(main.app)
    first, second = model['buildings'][:2]
    for ordinary_between in (False, True):
        with MemoryHouse(model, persist=True) as memory, patch.object(
                main, 'require_parent_token', return_value={'id': 'test-parent'}):
            original_place = copy.deepcopy(ts.place())
            def edit_building(building, name, kind):
                response = client.patch(f'/api/house/editor/place/buildings/{building["id"]}',
                                        json={'name': name, 'kind': kind})
                assert response.status_code == 200
            def ordinary_edit(value):
                room = first['rooms'][0]
                response = client.post('/api/house/editor/op', json={'op': {
                    'op': 'set', 'building': first['id'], 'id': room['id'],
                    'field': 'name', 'value': value}})
                assert response.status_code == 200
            def check_details(expected_model, expected_place, label):
                if ts.current_model() != expected_model:
                    failures.append(f'history jump {ordinary_between} {label}: model not exact')
                if ts.place() != expected_place:
                    failures.append(f'history jump {ordinary_between} {label}: place not exact')
            def check_names(expected_model, label):
                expected = {b['id']: (b['name'], b.get('kind')) for b in expected_model['buildings']}
                actual = {b['id']: (b['name'], b.get('kind')) for b in ts.current_model()['buildings']}
                if actual != expected:
                    failures.append(f'history jump {ordinary_between} {label}: undone details returned')
            edit_building(first, 'First renamed', 'studio')
            if ordinary_between:
                ordinary_edit('Room between building edits')
            edit_building(second, 'Second renamed', 'workshop')
            edited_round = ts.current_id()
            edited_model, edited_place = ts.current_model(), copy.deepcopy(ts.place())
            response = client.post('/api/house/twin/revert', json={'round': 1})
            assert response.status_code == 200
            check_details(model, original_place, 'undo')
            ordinary_edit('Room after undo')
            check_names(model, 'ordinary edit after undo')
            response = client.post('/api/house/twin/revert', json={'round': edited_round})
            assert response.status_code == 200
            check_details(edited_model, edited_place, 'redo')
            ordinary_edit('Room after redo')
            check_names(edited_model, 'ordinary edit after redo')
    # A jump over a raw edit still returns a building missing from the place list.
    with MemoryHouse(model, persist=True) as memory, patch.object(
            main, 'require_parent_token', return_value={'id': 'test-parent'}):
        response = client.patch(f'/api/house/editor/place/buildings/{first["id"]}', json={'name': 'Renamed'})
        assert response.status_code == 200
        memory.row['place']['buildings'] = [b for b in memory.row['place']['buildings'] if b['id'] != second['id']]
        response = client.post('/api/house/twin/revert', json={'round': 1})
        assert response.status_code == 200
        if second['id'] not in {b['id'] for b in ts.place()['buildings']}:
            failures.append('history jump: a restored building is missing from the place list')
        if ts.current_model() != model:
            failures.append('history jump: model not exact with a restored building')
    print('multi-building history jumps:', len(failures), 'failed', flush=True)
    return failures


def refusals_and_person_refit(model):
    source = copy.deepcopy(model)
    bid = source['buildings'][0]['id']
    source['buildings'][0].setdefault('src', {})['person'] = True
    with MemoryHouse(source, persist=True) as memory:
        footprint = setup_plot(memory, source, bid)
        client = TestClient(main.app)
        before_state = copy.deepcopy(memory.row)
        for body in ({'name': ''}, {'kind': 'invalid'}, {'footprint': [[0, 0]]}):
            response = client.patch(f'/api/house/editor/place/buildings/{bid}', json=body)
            assert response.status_code == 400
            assert memory.row == before_state and ts.current_model() == source
        response = client.put('/api/house/editor/place/lot/placement', json={
            'footprints': [{'building': bid, 'outline': footprint}]})
        assert response.status_code == 200
        assert ts.current_id() == 1 and ts.current_model() == source
    print('synthetic refusals and person-refit guard passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner-export', type=Path)
    args = parser.parse_args()
    source = fixture()
    failures = multi_building_history_jumps(source)
    failures += exercise(source, 'synthetic')
    refusals_and_person_refit(source)
    if args.owner_export:
        # Read by path only. Never persist or print the document or its fields.
        document = json.loads(args.owner_export.read_text(encoding='utf-8'))
        failures += exercise(document['model'], 'owner', document.get('state'))
    for failure in failures:
        print('FAIL', failure)
    print(f'{len(failures)} failed')
    sys.exit(bool(failures))
