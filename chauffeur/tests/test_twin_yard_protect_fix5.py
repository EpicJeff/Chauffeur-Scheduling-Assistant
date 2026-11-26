"""Final local regressions: raw snapshots, real history, and isolated workers."""
import copy
from contextlib import ExitStack
from itertools import product
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='yard_fix5_'))
os.environ.pop('HA_BASE_URL', None)
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import test_twin_director as d
from test_twin_director_connected import MemoryHouse, encoded
from test_twin_yard_protect_fix4 import raw_house, plant, build_fixture
from services import storage, twin_store as ts, twin_director as director, twin_build as tb


def seed_disk():
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    model = raw_house()
    with ts.LIFECYCLE, ts._LOCK:
        row = ts._state()
        ts._follow_place(row, model)
        ts._append_round(row, model, 'hand')
    return model


def publish_director():
    with ExitStack() as stack:
        stack.enter_context(patch.object(director.model_pools, 'credentials', return_value=('stub','stub')))
        stack.enter_context(patch.object(director.model_pools, 'call_pool_json', return_value={
            'critique':'Add one plant.', 'done':False, 'site':{'planting':[plant()]}}))
        stack.enter_context(patch.object(director.twin_cost, 'require_clear'))
        stack.enter_context(patch.object(director.twin_cost, 'record', return_value=[]))
        result, err = director.critique('fix5', [d._png()], ['front'], base=ts.current_id())
    assert err is None and result, err
    return result


def scenario_return_to_earlier_house_syncs_renamed_building():
    source = seed_disk(); bid = source['buildings'][0]['id']
    ts.update_building(bid, {'name':'Renamed building'})
    before_director = ts.current_id()
    # A stale historical answer must not become the logical undo target.
    with ts.LIFECYCLE, ts._LOCK:
        ts._append_round(ts._state(), ts.current_model(), 'director', base=-1)
    assert ts.current_id() == before_director
    publish_director()
    ts.revert(1)
    shown = next(b for b in ts.current()['buildings'] if b['id'] == bid)
    registered = next(b for b in ts.place()['buildings'] if b['id'] == bid)
    assert shown['name'] == registered['name'] == 'Renamed building'
    ts.update_building(bid, {'name':'Edited after return'})
    assert ts.current()['buildings'][0]['name'] == 'Edited after return'


def scenario_return_restores_building_to_registry_and_editing():
    source = seed_disk(); bid = source['buildings'][0]['id']
    ts.update_model(lambda m: dict(m, buildings=[]))
    ts.remove_building(bid)
    assert not ts.place()['buildings']
    publish_director()
    ts.revert(1)
    assert any(b['id'] == bid for b in ts.current()['buildings'])
    assert any(b['id'] == bid for b in ts.place()['buildings']), 'restored building missing from registry'
    ts.update_building(bid, {'name':'Restored and editable'})
    assert ts.current()['buildings'][0]['name'] == 'Restored and editable'


def scenario_exact_director_undo_skips_sync_even_with_stale_history():
    source = seed_disk(); bid = source['buildings'][0]['id']
    with ts.LIFECYCLE, ts._LOCK:
        row = ts._state()
        row['place']['buildings'][0]['name'] = 'Registry differs'
        ts._save(row)
        ts._append_round(ts._state(), source, 'director', base=-1)
    original = (Path(ts.DATA_DIR)/'rounds/1.json').read_bytes()
    publish_director()
    rid = ts.revert(1)
    assert (Path(ts.DATA_DIR)/f'rounds/{rid}.json').read_bytes() == original
    assert ts.current_model() == source
    assert ts.place()['buildings'][0]['name'] == 'Registry differs'
    assert ts.current_model()['buildings'][0]['id'] == bid


def scenario_unconfirmed_empty_yard_never_grants_later_approval():
    for touched in (False, True):
        for confirm in ('missing', 'true', 1, False, None, True):
            source = raw_house()
            if touched:
                source['site']['edges'] = [{'id':'hand-edge','points':[[10,10],[20,10]],'material':'lawn'}]
            with MemoryHouse(source) as memory, patch.object(tb, '_save'):
                build, step = build_fixture()
                dispatched = []
                def dispatch(b, ticket, reader, inline):
                    granted = tb._recompose_allowed(b, step)
                    assert granted is (confirm is True), 'approval was granted implicitly'
                    # A yard edit arrives while an earlier read is running.
                    arrival = {'id':'arrived-edge','points':[[10,10],[20,10]],'material':'lawn'}
                    memory.models[memory.row['current']]['site']['edges'] = [arrival]
                    ts._invalidate_reads()
                    tb._settle(b, step, {'fragment':{}})
                    if confirm is not True:
                        assert arrival in ts.current_model()['site']['edges']
                        assert any('Kept your yard.' in e.get('text','') for e in b['events'])
                    dispatched.append(True)
                    b['state'] = 'done'; tb._idle(b, ticket)
                kwargs = {} if confirm == 'missing' else {'confirm':confirm}
                with patch.object(tb, '_dispatch', side_effect=dispatch):
                    if touched and confirm is not True:
                        try: tb.reread(build['id'], step['id'], inline=True, **kwargs)
                        except ValueError: pass
                        else: raise AssertionError('touched yard accepted unconfirmed compose')
                        assert not dispatched
                    else:
                        tb.reread(build['id'], step['id'], inline=True, **kwargs)
                        assert dispatched


def scenario_stored_null_fields_are_no_cost_noops():
    for name, key in product((*ts.twin_plan.DIRECTOR_LISTS, 'materials'), (None, 'stub')):
        source = raw_house()
        if name == 'materials': source[name] = None
        else: source['site'][name] = None
        with MemoryHouse(source) as memory, patch.object(director.model_pools, 'call_pool_json') as call, \
                patch.object(director.twin_cost, 'record') as record, \
                patch.object(director.model_pools, 'credentials', return_value=('stub',key)):
            result, err = director.critique('null-preflight',[d._png()],['front'],base=1)
            assert err is None and result and result['cost'] == 0, (name,err)
            assert not call.called and not record.called, 'known no-op must not make a paid call'
            assert not memory.appended and encoded(ts.current_model()) == encoded(source)
            assert any('Nothing was saved' in n for n in result['notes'])


def scenario_empty_answer_fields_keep_raw_house_and_null_role():
    answers = [{}, {'site':None}, {'materials':None}, {'materials':{}},
               *({'site':{name:None}} for name in ts.twin_plan.DIRECTOR_LISTS)]
    for answer in answers:
        source = raw_house(); source['materials']['water'] = None
        with MemoryHouse(source) as memory:
            result, err = memory.send(answer)
            assert err is None and result, (answer,err)
            assert not memory.appended and encoded(ts.current_model()) == encoded(source), answer
            assert any('Nothing was saved' in n for n in result['notes'])
    # Explicit null in the answer still has its documented role-removal meaning.
    with MemoryHouse(source) as memory:
        result, err = memory.send({'materials':{'water':None}})
        assert err is None and len(memory.appended) == 1
        assert 'water' not in ts.current_model()['materials']


def scenario_drawn_pieces_outside_lot_are_refused():
    outside = [[190,190],[210,190],[210,210],[190,210]]
    for name,piece in (('beds',{'polygon':outside}), ('edges',{'polygon':outside}),
                       ('edges',{'points':[[190,190],[210,190]]})):
        source = raw_house()
        with MemoryHouse(source) as memory:
            result, err = memory.send({'site':{name:[dict(piece,id='outside')]}})
            assert err is None and result, err
            assert not memory.appended and encoded(ts.current_model()) == encoded(source)
            assert any('Refused' in n for n in result['notes'])


def scenario_missing_site_lists_accept_exact_additions():
    pieces = {'planting':plant(), 'beds':{'id':'bed','polygon':[[10,10],[20,10],[20,20],[10,20]]},
              'edges':{'id':'edge','points':[[30,10],[40,10]]},
              'furniture':{'id':'chair','asset':'polyhaven:'+next(iter(d.KIT['furniture'].values())), 'at':[50,50]}}
    for name,piece in pieces.items():
        source = raw_house(); source['site'].pop(name)
        with MemoryHouse(source) as memory:
            result, err = memory.send({'site':{name:[piece]}})
            assert err is None and len(memory.appended) == 1, (name,err)
            after = ts.current_model()
            added = after['site'].pop(name)
            assert len(added) == 1 and added[0]['id'] == piece['id'] and added[0]['src'] == {'person':True}
            assert encoded(after) == encoded(source)
            ts.revert(1)
            assert encoded(ts.current_model()) == encoded(source)


def scenario_approval_requires_live_busy_matching_worker():
    source = raw_house()
    source['site']['edges'] = [{'id':'old-edge','points':[[10,10],[20,10]],'material':'lawn'}]
    for fault in ('ticket','step','busy','running',None):
        with MemoryHouse(source), patch.object(tb,'_save'):
            build, step = build_fixture('running')
            runtime = {'ticket':'live','busy':True,'recompose':(step['id'],'live')}
            tb._WORKERS[build['id']] = runtime
            if fault == 'ticket': runtime['recompose'] = (step['id'],'expired')
            if fault == 'step': runtime['recompose'] = ('another-step','live')
            if fault == 'busy': runtime['busy'] = False
            if fault == 'running': build['state'] = 'stopped'
            assert tb._recompose_allowed(build,step) is (fault is None), fault
            if fault:
                tb._settle(build,step,{'fragment':{}})
                assert source['site']['edges'] == ts.current_model()['site']['edges'], fault
                assert any('Kept your yard.' in e.get('text','') for e in build['events'])


if __name__ == '__main__':
    failures = []
    for name, fn in list(globals().items()):
        if name.startswith('scenario_'):
            try:
                fn(); print('PASS',name,flush=True)
            except Exception:
                import traceback
                traceback.print_exc(); print('FAIL',name,flush=True); failures.append(name)
    assert not failures, failures
