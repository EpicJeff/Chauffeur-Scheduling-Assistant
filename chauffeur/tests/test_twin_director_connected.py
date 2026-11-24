"""Director publication uses the editor's connected store; no real house writes."""
import copy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='director_connected_'))
os.environ.pop('HA_BASE_URL', None)
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import test_twin_director as d
from services import twin_director as director, twin_model, twin_model_bridge as bridge
from services import twin_place, twin_plan, twin_store as ts


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


class MemoryHouse(ExitStack):
    """Real store mutation/revert; only persistence and external services are stubbed."""
    def __init__(self, model):
        super().__init__()
        self.models = {1: copy.deepcopy(model)}
        self.row = {'current': 1, 'generation': 7, 'rounds': [{'id': 1, 'kind': 'hand'}],
                    'place': twin_place.migrate({}, model), 'sources': [], 'page_roles': [],
                    'registrations': [], 'tombstones': [], 'fixes': [], 'pruned_runs': {}}
        self.appended = []
        ts._invalidate_reads()
        self.callback(ts._invalidate_reads)
        for obj, attr, kw in (
            (ts, '_state', {'side_effect': lambda *a, **k: copy.deepcopy(self.row)}),
            (ts, '_read_round', {'side_effect': lambda row, rid: copy.deepcopy(self.models[rid])}),
            (ts, '_append_round', {'side_effect': self.append}),
            (ts, 'build_running', {'return_value': False}),
            (director.storage, 'get_settings', {'side_effect': lambda: {'house_twin': copy.deepcopy(self.row)}}),
            (director.model_pools, 'credentials', {'return_value': ('stub', 'stub')}),
            (director.twin_cost, 'require_clear', {'return_value': None}),
            (director.twin_cost, 'record', {'return_value': [{'usd': .125}]})):
            self.enter_context(patch.object(obj, attr, **kw))

    def append(self, row, model, kind, note='', cost=None, run=None, base=None, **kw):
        rid = max(self.models) + 1
        record = dict(id=rid, kind=kind, note=note, cost=cost, run=run, base=base,
                      stale=base is not None and base != row['current'], **kw)
        self.models[rid] = json.loads(json.dumps(model, allow_nan=False))
        row['rounds'].append(record)
        if not record['stale']:
            row['current'] = rid
        self.row = copy.deepcopy(row)
        self.appended.append(record)
        if not record['stale']:
            ts._write_through(row, json.dumps(model), kw.get('normalized', False))
        return rid

    def send(self, answer, run='connected', **kw):
        with patch.object(director.model_pools, 'call_pool_json',
                          return_value={'critique': 'Keep the existing yard.', 'done': False, **answer}):
            return director.critique(run, [d._png()], ['front'], base=kw.get('base', self.row['current']))


def fixture():
    d._finished_yard()
    return ts.current_model()


def exercise_house(model, label='synthetic'):
    """Also callable on the owner export in memory; outputs only counts/booleans."""
    names = ('planting', 'beds', 'edges', 'furniture', 'hardscape', 'terraces', 'fence')
    count = lambda p: [len(v) if isinstance(v, list) else int(bool(v)) for name in names
                       for v in [p['site'].get(name)]]
    rows = [('Before', count(model), True, 0)]
    site = model['site']
    plant = site['planting'][0]
    answers = [('Full echo', copy.deepcopy(site)),
               ('Move a plant', {'planting': [{'id': plant['id'], 'at': [90000, 90000]}]}),
               ('Five plants', {'planting': copy.deepcopy(site['planting'][:5])}),
               ('Beds []', {'beds': []})]
    for case, answer in answers:
        with MemoryHouse(model) as memory:
            result, err = memory.send({'site': answer})
            assert err is None and result, (label, case, err)
            assert not memory.appended, (label, case, 'no-op published a round')
            assert result['round'] == 1 and result['notes'], (label, case, 'suggestions/no-op note')
            assert any('Nothing was saved' in n for n in result['notes']), (label, case, 'no-op explained')
            assert encoded(ts.current_model()) == encoded(model), (label, case, 'existing house changed')
            rows.append((case, count(ts.current_model()), True, len(memory.appended)))
    # Pick two distinct empty points inside this house's lot with the real validator.
    from services import twin_terrain
    lot = site['lot']
    xs, ys = zip(*lot)
    pieces = []
    for i in range(1, 40):
        for j in range(1, 40):
            at = [min(xs) + (max(xs)-min(xs))*i/40, min(ys)+(max(ys)-min(ys))*j/40]
            raw = {'id': f'director-new-{len(pieces)}', 'preset': d.KIT['shrubs'][0], 'at': at, 'height': 4}
            if not twin_terrain.inside(lot, at):
                continue
            if director._position(raw) in {director._position(p) for p in site['planting']}:
                continue
            pieces.append(raw)
            if len(pieces) == 2:
                break
        if len(pieces) == 2:
            break
    assert len(pieces) == 2
    with MemoryHouse(model) as memory, patch.object(ts, 'push_round', side_effect=AssertionError('flat publish')):
        result, err = memory.send({'site': {'planting': pieces}})
        assert err is None and result, (label, 'two additions', err)
        after = ts.current_model()
        assert len(after['site']['planting']) == len(site['planting']) + 2
        restored = copy.deepcopy(after)
        restored['site']['planting'] = restored['site']['planting'][:-2]
        assert encoded(restored) == encoded(model), (label, 'an existing connected record changed')
        assert len(memory.appended) == 1
        meta = memory.appended[0]
        assert meta['kind'] == 'director' and meta['run'] == 'connected' and meta['base'] == 1
        assert meta['cost'] == .125 and meta['note'] and not meta['stale']
        rows.append(('Two new plants', count(after), True, 1))
        ts.revert(1)
        assert encoded(ts.current_model()) == encoded(model), (label, 'undo was not exact')
        rows.append(('Undo', count(ts.current_model()), True, 1))
    return rows


def scenario_noops_additions_and_undo_use_connected_store():
    exercise_house(fixture())


def scenario_connected_fixture_records_are_preserved():
    path = Path(__file__).parent/'fixtures/twin_model/household-2026-11-09.json'
    flat = json.loads(path.read_text(encoding='utf-8'))
    model = bridge.assemble(flat)[0]
    # Seed a yard without touching the fixture's connected building records.
    model['site'] = copy.deepcopy(fixture()['site'])
    exercise_house(model, 'connected fixture')


def scenario_store_refuses_existing_record_corruption():
    source = fixture()
    # Exercise the real update_model guard directly, independent of answer filtering.
    source['site']['yard_rooms'] = [{'id': 'yard', 'name': 'Garden', 'ha_area': 'garden',
                                   'polygon': [[80,-90],[100,-90],[100,-70],[80,-70]]}]
    source['site']['devices'] = [{'id': 'device:probe', 'device': 'switch.probe',
                                  'host': {'yard_room': 'yard', 'u': .9, 'v': .9}}]
    assert source['site']['devices'] and source['site']['terraces']
    for label, mutate in (
            ('wall', lambda m: m['buildings'][0]['walls'].pop()),
            ('room', lambda m: m['buildings'][0]['rooms'].pop()),
            ('joint', lambda m: m['buildings'][0]['joints'].reverse()),
            ('terrace', lambda m: m['site']['terraces'].clear()),
            ('device', lambda m: m['site']['devices'].clear()),
            ('missing site', lambda m: m.pop('site')),
            ('wrong site type', lambda m: m.update(site=None)),
            ('new top-level field', lambda m: m.update(injected=True))):
        with MemoryHouse(source) as memory:
            def corruption(m):
                mutate(m)
                return m
            try:
                ts.update_model(corruption, 'director', base=1, generation=7)
            except twin_plan.DirectorUnsafe as err:
                assert 'Nothing was saved' in str(err), label
            else:
                raise AssertionError(label + ' was accepted')
            assert not memory.appended and encoded(ts.current_model()) == encoded(source), label


def scenario_additions_cannot_make_normalization_damage_existing_records():
    source = fixture()
    source['site']['yard_rooms'] = [{'id': 'yard', 'name': 'Garden', 'ha_area': 'garden',
                                   'polygon': [[80,-90],[100,-90],[100,-70],[80,-70]]}]
    source['site']['devices'] = [{'id': 'device:probe', 'device': 'switch.probe',
                                  'host': {'yard_room': 'yard', 'u': .9, 'v': .9}}]
    assert source['site']['devices'] and source['site']['terraces']
    for group, slot in (('site','terraces'), ('site','devices'), ('buildings','rooms'), ('buildings','walls')):
        derived = copy.deepcopy(source)
        owner = derived['site'] if group == 'site' else derived['buildings'][0]
        owner[slot] = []
        def derive(model, **kw):
            return copy.deepcopy(derived), []
        with MemoryHouse(source) as memory, patch.object(twin_model, 'normalize', side_effect=derive):
            result, err = memory.send({'site': {'planting': [{'id': 'new-probe',
                'preset': d.KIT['shrubs'][0], 'at': [95,-60], 'height': 4}]}})
            assert result and err is None and len(memory.appended) == 1, (group,slot,err)
            stored = ts.current_model()
            stored['site']['planting'] = stored['site']['planting'][:-1]
            assert encoded(stored) == encoded(source), (group,slot,'normalization is only a check')


def scenario_guard_checks_the_actual_raw_stored_object():
    source = fixture()
    def corrupt(model):
        model['buildings'][0]['walls'].reverse()
        return copy.deepcopy(model)
    with MemoryHouse(source) as memory, patch.object(ts, '_director_normalize', side_effect=corrupt):
        result, err = memory.send({'materials': {'roof': {'id': 'standing_seam', 'color': '#123456'}}})
        assert result is None and 'Nothing was saved' in err
        assert not memory.appended


def scenario_second_normalization_drift_reports_records():
    source = fixture()
    real = twin_model.normalize
    def drift(model, **kw):
        out, notes = real(model, **kw)
        out['buildings'][0]['walls'][0]['probe'] = not model['buildings'][0]['walls'][0].get('probe', False)
        return out, notes
    with MemoryHouse(source) as memory, patch.object(twin_model, 'normalize', side_effect=drift):
        result, err = memory.send({'site': {}})
        assert result is None and 'Nothing was saved' in err and 'buildings[0].walls[0]' in err, err
        assert not memory.appended


def scenario_generation_base_staleness_and_cap_are_preserved():
    source = fixture()
    with MemoryHouse(source) as memory:
        def roles(m):
            m['materials']['roof'] = {'id': 'standing_seam', 'color': '#123456'}
            return m
        for gen, base in ((6, 1), (7, True)):
            try:
                ts.update_model(roles, 'director', generation=gen, base=base)
            except ValueError:
                pass
            else:
                raise AssertionError('invalid generation/base accepted')
        assert not memory.appended
        # Base 2 was superseded by current 1 (a revert); stale results stay historical.
        memory.models[2] = copy.deepcopy(source)
        rid = ts.update_model(roles, 'director', base=2, generation=7, run='stale', cost=.2)
        assert rid == 3 and memory.row['current'] == 1 and memory.appended[-1]['stale']
        for i in range(d.tc.ROUND_CAP):
            memory.row['rounds'].append({'id': 100+i, 'kind': 'director', 'run': 'capped'})
        try:
            ts.update_model(roles, 'director', run='capped', base=1, generation=7)
        except ValueError as err:
            assert 'round cap reached' in str(err)
        else:
            raise AssertionError('director cap bypassed')
        assert len(memory.appended) == 1


if __name__ == '__main__':
    failures = []
    for name, fn in list(globals().items()):
        if name.startswith('scenario_'):
            try:
                fn()
                print('PASS', name, flush=True)
            except Exception as err:
                import traceback
                traceback.print_exc()
                print('FAIL', name, type(err).__name__, flush=True)
                failures.append(name)
    assert not failures, failures
