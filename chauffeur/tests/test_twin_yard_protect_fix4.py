"""Round-4 regressions start with RAW stored houses, never pre-normalized ones."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='yard_fix4_'))
os.environ.pop('HA_BASE_URL', None)
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import test_twin_director as d
from test_twin_director_connected import MemoryHouse, encoded
from services import twin_build as tb, twin_model_bridge as bridge, twin_store as ts
from services import twin_director as director, twin_model_ops as ops, twin_plan


def raw_house(name='twin_poolhouse.plan.json'):
    path = Path(__file__).parent/'fixtures'/name
    flat = json.loads(path.read_text(encoding='utf-8'))
    # The old flat fixture omits room ids. Supply identities for the bridge;
    # do not normalize the connected result used as our stored baseline.
    for b in flat['buildings']:
        for name in ('rooms', 'openings', 'walls', 'stairs'):
            for i, piece in enumerate(b.get(name, [])):
                piece.setdefault('id', f'fixture-{name}-{i}')
    model, _ = bridge.assemble(flat)
    model['site'].update(lot=[[0,0],[200,0],[200,200],[0,200]], planting=[], beds=[], edges=[], furniture=[])
    return model


def plant(ident='fresh', x=150):
    return {'id': ident, 'preset': d.KIT['shrubs'][0], 'at': [x,150], 'height': 4}


def exact_round(model, label='raw'):
    """Reusable for the private owner export: never emit house contents."""
    with MemoryHouse(model) as memory:
        result, err = memory.send({'site': {'planting': [plant()]}})
        assert err is None and result and len(memory.appended) == 1, (label, err)
        after = ts.current_model()
        piece = after['site']['planting'][-1]
        restored = copy.deepcopy(after)
        restored['site']['planting'] = restored['site']['planting'][:-1]
        assert encoded(restored) == encoded(model), (label, 'existing raw records changed')
        assert piece['id'] == 'fresh' and piece['src'] == {'person': True}, (label, 'hand mark')
        ts.revert(1)
        assert encoded(ts.current_model()) == encoded(model), (label, 'raw undo changed records')
        return after


def scenario_raw_fixtures_stale_ids_and_registry_mismatch():
    for name in ('twin_poolhouse.plan.json', 'twin_model/household-2026-11-09.json'):
        source = raw_house(name)
        exact_round(source, name)
        missing = copy.deepcopy(source)
        missing.pop('materials', None)
        for b in missing['buildings']: b.pop('materials', None)
        exact_round(missing, 'missing materials')
        stale = copy.deepcopy(source)
        stale['buildings'][0]['walls'][0]['id'] = 'stale-wall-id'
        stale['buildings'][0]['rooms'][0]['id'] = 'stale-room-id'
        exact_round(stale, 'stale identities')
    source = raw_house()
    with MemoryHouse(source) as memory:
        memory.row['place']['buildings'][0]['name'] = 'Registry differs'
        result, err = memory.send({'site': {'planting': [plant()]}})
        assert err is None and result and len(memory.appended) == 1, err
        after = ts.current_model()
        assert encoded(after['buildings']) == encoded(source['buildings'])
        assert memory.appended[0].get('normalized') is False
        ts.revert(1)
        assert encoded(ts.current_model()) == encoded(source), 'director undo must not sync a mismatched registry'


def scenario_refused_material_roles_keep_stored_choices():
    for role in ('water', 'pool_interior', 'pool_waterline', 'pool_coping', 'roof'):
        for invalid in ({'id':'zzz','color':'#111111'}, {'id':'standing_seam','color':'bad'}, 'wrong type'):
            source = raw_house()
            source['materials'][role] = {'id':'personal-choice', 'color':'#abcdef'}
            with MemoryHouse(source) as memory:
                result, err = memory.send({'materials': {role: invalid}})
                assert err is None and result, (role, err)
                assert encoded(ts.current_model()) == encoded(source), role
                assert not memory.appended and any('kept' in n.lower() for n in result['notes']), role


def scenario_generation_forwarding_through_critique():
    source = raw_house()
    with MemoryHouse(source) as memory:
        def start_over(*a, **kw):
            memory.row['generation'] += 1
            return {'critique':'Add one', 'done':False, 'site':{'planting':[plant()]}}
        with patch.object(director.model_pools, 'call_pool_json', side_effect=start_over):
            result, err = director.critique('generation', [d._png()], ['front'], base=1)
        assert result is None and err and not memory.appended, 'critique must forward its captured generation'


def scenario_no_lot_matches_hand_placement_and_mixed_cap():
    source = raw_house()
    source['site'].pop('lot')
    additions = {'planting':[plant()], 'beds':[{'id':'bed', 'polygon':[[130,130],[140,130],[140,140],[130,140]]}],
                 'edges':[{'id':'edge', 'points':[[145,130],[155,130]]}],
                 'furniture':[{'id':'chair','asset':'polyhaven:'+next(iter(d.KIT['furniture'].values())), 'at':[160,160]}]}
    with MemoryHouse(source) as memory:
        result, err = memory.send({'site':additions})
        assert err is None and len(memory.appended) == 1, err
        after = ts.current_model()
        for name in additions:
            piece = after['site'][name][-1]
            assert piece['src'] == {'person':True}, name
            values = copy.deepcopy(additions[name][0])
            if name == 'planting': values['asset'] = values.pop('preset')
            op = dict(values, op='add_site_item' if name in ('planting','furniture') else 'add_site_shape',
                      list=name, require_inside=True)
            hand = {'site':copy.deepcopy(source['site'])}
            if name == 'edges':
                from services import twin_site_shapes
                expected = dict(values, material='lawn', src={'person':True})
                twin_site_shapes.validate(name, expected)
            else:
                ops._site_op(hand, op, 'person', _batch_inplace=True)
                expected = hand['site'][name][-1]
            assert encoded(piece) == encoded(expected), name
    source = raw_house()
    answer = {'planting':[plant(f'p-{i}',100+i) for i in range(20)],
              'beds':[{'id':f'b-{i}','polygon':[[10+i*3,100],[12+i*3,100],[12+i*3,102],[10+i*3,102]]} for i in range(10)],
              'furniture':[{'asset':'polyhaven:'+next(iter(d.KIT['furniture'].values())), 'at':[180,180]}]}
    with MemoryHouse(source) as memory:
        result, err = memory.send({'site':answer})
        assert err is None, err
        assert sum(len(ts.current_model()['site'][k]) for k in twin_plan.DIRECTOR_LISTS) == 25
        assert any('25' in n for n in result['notes'])


def scenario_collection_cap_and_unexpected_piece_error():
    source = raw_house()
    source['site']['planting'] = [dict(plant(f'old-{i}',i/10), by='compose') for i in range(290)]
    with MemoryHouse(source) as memory:
        result, err = memory.send({'site':{'planting':[plant(f'new-{i}',100+i) for i in range(25)]}})
        assert err is None, err
        assert len(ts.current_model()['site']['planting']) == 300
        assert any('300' in n for n in result['notes']), 'collection cap must be explained'
    source = raw_house()
    real = director._ordinary_addition
    def unexpected(name, raw, *a, **kw):
        if raw.get('id') == 'bad': raise RuntimeError('unexpected piece failure.')
        return real(name, raw, *a, **kw)
    with MemoryHouse(source) as memory, patch.object(director, '_ordinary_addition', side_effect=unexpected):
        result, err = memory.send({'site':{'planting':[plant('bad'),plant('good',152)]}})
        assert err is None and len(ts.current_model()['site']['planting']) == 1, err
        assert any('unexpected piece failure.' in n and '..' not in n for n in result['notes'])


def build_fixture(state='done'):
    bid = 'e'*32
    tb._BUILDS.clear(); tb._WORKERS.clear()
    step = tb._step('compose'); step['status'] = 'pending'
    build = {'id':bid, 'generation':7, 'inputs':{'part':'lot'}, 'steps':[step], 'state':state,
             'events':[], 'seq':0, 'pause':None, 'cost':0}
    tb._BUILDS[bid] = build
    return build,step


def has_consent(build):
    return any(s.get('recompose') for s in build['steps']) or bool(tb._WORKERS.get(build['id'],{}).get('recompose'))


def scenario_direct_confirm_refused_start_launch_stop_and_restart():
    source = raw_house(); source['site']['planting'] = [dict(plant('hand'),src={'person':True})]
    with MemoryHouse(source), patch.object(tb,'_save'):
        for invalid in (1,1.0,'true','yes',None,False):
            b,s = build_fixture()
            try: tb.reread(b['id'],s['id'],confirm=invalid,inline=True)
            except ValueError: pass
            else: raise AssertionError('direct reread accepted truthy confirmation')
            assert not has_consent(b)
        b,s=build_fixture()
        other=copy.deepcopy(b);other.update(id='f'*32,state='paused');tb._BUILDS[other['id']]=other
        try: tb.reread(b['id'],s['id'],confirm=True,inline=True)
        except ValueError: pass
        else: raise AssertionError('another active build must refuse')
        assert not has_consent(b), 'refused start retained consent'
        b,s=build_fixture()
        with patch.object(tb,'_launch',side_effect=OSError('launch failed')):
            try: tb.reread(b['id'],s['id'],confirm=True,inline=True)
            except OSError: pass
        assert not has_consent(b), 'failed launch retained consent'
        b,s=build_fixture()
        with patch.object(tb,'_dispatch',side_effect=OSError('dispatch failed')):
            try: tb.reread(b['id'],s['id'],confirm=True,inline=True)
            except OSError: pass
        assert not has_consent(b), 'failed dispatch retained consent'
    # Legacy persisted markers are dropped on load, even for done builds.
    with MemoryHouse(source) as memory:
        b,s=build_fixture();s['recompose']=True
        tb._save(b)
        path=tb._root(b['id'])/'state.json'
        tb._BUILDS.clear();tb._WORKERS.clear()
        loaded=tb._get(b['id'])
        assert not has_consent(loaded) and not any(x.get('recompose') for x in json.loads(path.read_text())['steps'])
        # Stop must persist removal even when the build is already done.
        loaded['steps'][0]['recompose']=True;tb._save(loaded)
        tb.stop(b['id'])
        assert not any(x.get('recompose') for x in json.loads(path.read_text())['steps'])


def scenario_each_attempt_exit_clears_consent_independently(only=None):
    source=raw_house()
    for exit_kind in ((only,) if only else ('checkpoint','failed','finally','settle','stop','resume','recover')):
        with MemoryHouse(source), patch.object(tb,'_save') as save:
            b,s=build_fixture('running')
            runtime={'ticket':'ticket', 'busy':True, 'cancels':[], 'recompose':(s['id'],'ticket')}
            tb._WORKERS[b['id']]=runtime
            # Also seed old disk-style consent: each exit must clear both forms.
            s['recompose']='ticket'
            if exit_kind in ('checkpoint','failed'):
                error = d.tc.CheckpointReached(10,10) if exit_kind=='checkpoint' else RuntimeError('read failed')
                def saved(build):
                    if build['state'] in ('checkpoint','failed'):
                        assert not has_consent(build), exit_kind+' did not clear before saving'
                save.side_effect=saved
                with patch.object(tb,'_obtain',side_effect=error),patch.object(tb,'_spend'):
                    tb._run(b,'ticket',None)
                assert not has_consent(b), exit_kind
            elif exit_kind=='finally':
                with patch.object(tb,'_obtain',return_value=None): tb._run(b,'ticket',None)
                assert not has_consent(b), 'worker finally retained consent'
            elif exit_kind=='settle':
                with patch.object(ts,'update_current',side_effect=RuntimeError('store failed')):
                    try: tb._settle(b,s,{'fragment':{},'problems':[]})
                    except RuntimeError: pass
                assert not has_consent(b), 'settle alone retained consent'
            elif exit_kind=='stop':
                tb.stop(b['id']);assert not has_consent(b)
            elif exit_kind=='resume':
                b['state']='stopped';runtime['busy']=False
                other=copy.deepcopy(b);other.update(id='f'*32,state='paused');tb._BUILDS[other['id']]=other
                try: tb.resume(b['id'])
                except ValueError: pass
                else: raise AssertionError('another build should refuse resume')
                assert not has_consent(b), 'plain resume reused an old attempt'
            else:
                b['state']='stopped';s['status']='pending'
                with patch.object(Path,'glob',return_value=[Path('e'*32)/'state.json']): tb.recover()
                assert not has_consent(b), 'recover retained consent'


def scenario_history_does_not_lock_untouched_yard():
    source=raw_house()
    source['site']['planting']=[dict(plant('generated'),by='compose')]
    with MemoryHouse(source) as memory:
        result,err=memory.send({'materials':{'roof':{'id':'standing_seam','color':'#123456'}}})
        assert err is None, err
        assert not tb.yard_occupied(ts.current_model()), 'material-only history locked yard'
        ts.revert(1)
        assert not tb.yard_occupied(ts.current_model()), 'undone history locked yard'
        memory.row['pruned_runs']={'old':{'director':5}}
        assert not tb.yard_occupied(ts.current_model()), 'pruned history locked yard'


def scenario_confirmation_description_is_short_and_explicit():
    from services.agent_tools_v2 import HouseDesignTool
    text=HouseDesignTool.model_fields['confirm'].description
    assert len(text)<=100 and 'explicit approval' in text and 'ask first' in text


def scenario_confirmed_reread_keeps_all_director_additions():
    source=raw_house()
    with MemoryHouse(source) as memory,patch.object(tb,'_save'):
        answer={'planting':[plant(f'close-{i}',150+i*.6) for i in range(3)],
                'beds':[{'id':'new-bed','polygon':[[130,130],[140,130],[140,140],[130,140]]}],
                'edges':[{'id':'new-edge','points':[[145,130],[155,130]]}],
                'furniture':[{'id':'new-chair','asset':'polyhaven:'+next(iter(d.KIT['furniture'].values())), 'at':[160,160]}]}
        result,err=memory.send({'site':answer});assert err is None,err
        before=ts.current_model()
        b,s=build_fixture()
        tb.reread(b['id'],s['id'],confirm=True,inline=True)
        after=ts.current_model()
        for name in answer:
            for piece in before['site'][name]:
                assert piece in after['site'][name], ('re-read lost hand-equivalent addition',name)
        assert not has_consent(b)


if __name__=='__main__':
    failed=[]
    for name,fn in list(globals().items()):
        if name.startswith('scenario_'):
            try: fn();print('PASS',name,flush=True)
            except Exception:
                import traceback;traceback.print_exc();failed.append(name);print('FAIL',name,flush=True)
    sys.exit(bool(failed))
