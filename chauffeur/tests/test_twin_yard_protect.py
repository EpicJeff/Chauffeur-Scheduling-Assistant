"""Fix-round adversarial regressions. Real critique/store and real build replays."""
import copy
import json
import os
import sys
import tempfile
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='yard_guard_')
os.environ.pop('HA_BASE_URL', None)
sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__))), os.path.dirname(__file__)]
import test_twin_director as d
from services import twin_build as tb, twin_plan, twin_store as ts, twin_model_ops as ops


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))


def check(value, message):
    if not value:
        raise AssertionError(message)


def yard():
    p = d._finished_yard()
    p['site']['planting'][1]['src'] = {'person': True}
    p['site']['terraces'][0].update(height=2, edges=[
        {'edge': 'sharp', 'wall': {'material': 'stone', 'rail': {'style': 'cable'}}},
        {'edge': 'sharp', 'stair': {}}, {'edge': 'slope'}, {'edge': 'slope'}])
    p['site']['yard_rooms'] = [{'id': 'yr1', 'name': 'Garden', 'ha_area': 'garden',
                              'polygon': [[80, -90], [100, -90], [100, -70], [80, -70]]}]
    p['site']['devices'] = [{'id': 'device:sw1', 'device': 'switch.yard',
                            'host': {'yard_room': 'yr1', 'u': .9, 'v': .9}}]
    p['site']['compose_overrides'] = {'removed': [], 'moved': {'plant-1': [61, -60]},
                                      'properties': {'plant-1': {'scale': 1.4, 'tint': '#abcdef'}}}
    ts.push_round(p, 'hand')
    return ts.current()


def send(site, run='guard', materials=None):
    return d._run(d.Critic(lambda s, m: (site, materials or {})), run=run)


def scenario_adversarial_existing_pieces_never_change():
    before = yard()
    cases = []
    for fields in ({'visible_in': []}, {'visible_in': 5}, {'height': 0}, {'height': -5},
                   {'height': 'tall'}, {'scale': 0}, {'scale': -1}, {'scale': 99},
                   {'at': [90000, 90000]}, {'asset': 'junk'}, {'asset': 'polyhaven:zzz'},
                   {'asset': 5}, {'asset': []}, {'tint': 5}, {'scale_axes': 'x'},
                   {'name': {'a': 1}}, {'kind': 'banana'}, {'read_geometry': None},
                   {'src': None}, {'src': {'sheet': 's', 'page': 1, 'step': 'x'}},
                   {'by': 'director'}, {'device': 'light.other'}, {'state': 'settled'},
                   {'op': 'REMOVE'}, {'_op': 'remove'}, {'removal': True},
                   {'status': 'removed'}, {'REMOVE': True}):
        cases.append({'planting': [{'id': 'plant-1', **fields}]})
    cases += [{'planting': [{'id': 'plant-1', 'at': [5, -90], 'height': 'tall'}]}]
    for fields in ({'asset': None, 'kind': 'lounger'}, {'asset': '', 'kind': 'lounger'},
                   {'asset': 'polyhaven:' + next(iter(d.KIT['furniture'].values()))}, {'kind': 'hot_tub'}):
        cases.append({'furniture': [{'id': 'chair-1', **fields}]})
    for slot, fields in (
            ('beds', {'polygon': [[0, 0]] * 3}), ('beds', {'materials': {}}), ('beds', {'material': None}),
            ('beds', {'materials': {'fill': {'id': 'unknown'}}}),
            ('edges', {'points': [[60, -50]] * 2}),
            ('terraces', {'edges': [{'edge': 'slope'}] * 4}),
            ('terraces', {'edges': [{'edge': 'sharp'}] * 4}), ('terraces', {'height': 0}),
            ('hardscape', {'materials': {'surface': {'id': 'patio_concrete'}}}),
            ('hardscape', {'pavers': {'gap_in': 6}}), ('hardscape', {'materials': 'x'}),
            ('yard_rooms', {'polygon': [[80, -90], [100, -90], [80, -70]], 'ha_area': None}),
            ('devices', {'device': 'switch.other'})):
        cases.append({slot: [{'id': before['site'][slot][0]['id'], **fields}]})
    cases += [{k: v} for k, v in (('fire_pit', [{'id': 'fire-1', 'entity': None}]),
                                  ('fence', []), ('pool', None), ('lot', []),
                                  ('compose_overrides', {'removed': ['plant-1']}) )]
    # Imported and kind-only identities cover I1's other representation paths.
    extra = ts.current()
    extra['site']['planting'].append({'id': 'imported', 'asset': 'import-abc', 'at': [85, -60]})
    extra['site']['furniture'].append({'id': 'kind-only', 'kind': 'lounger', 'at': [85, -65]})
    ts.push_round(extra, 'hand')
    cases += [{'planting': [{'id': 'imported', 'asset': 'polyhaven:zzz'}]},
              {'planting': [{'id': 'imported', 'preset': d.KIT['shrubs'][0]}]},
              {'furniture': [{'id': 'kind-only', 'kind': 'hot_tub'}]}]
    before = ts.current()
    raw_before = ts.current_model()
    failures = []
    for i, answer in enumerate(cases):
        with ts.LIFECYCLE, ts._LOCK:
            ts._append_round(ts._state(), copy.deepcopy(raw_before), 'hand')
        answer = copy.deepcopy(answer)
        answer.setdefault('planting', []).append({'id':f'guard-new-{i}', 'preset':d.KIT['shrubs'][0], 'at':[95,-60]})
        result, err = send(answer, run=f'adversarial-{i}')
        stored = ts.current_model()
        added = stored['site']['planting'].pop()
        passed = (err is None and added['id'] == f'guard-new-{i}' and encoded(stored) == encoded(raw_before)
                  and any('suggested' in n for n in result['notes']))
        print(f'    existing case {i}: {"PASS" if passed else "FAIL"}', flush=True)
        if not passed:
            failures.append(i)
    print('    adversarial answers:', len(cases))
    check(not failures, ('existing pieces or suggestion notes', failures))


def scenario_suggestion_counts_do_not_invent_omitted_removals():
    before = yard()
    result, err = send({'planting': [{'id': f'plant-{i}', 'height': 8} for i in range(3)] +
                       [{'id': f'plant-{i}', 'op': 'REMOVE'} for i in range(3, 8)]})
    check(err is None, err)
    check(any('changing 3 plants and removing 5' in n for n in result['notes']), result['notes'])
    result, err = send({'planting': before['site']['planting'][:5]}, run='five')
    check(err is None and not any('removing' in n for n in result['notes']), result)
    for i, value in enumerate(([], None)):
        result, err = send({'planting': value}, run=f'empty-{i}')
        check(err is None and any('removing 12' in n for n in result['notes']), result)
    check(encoded(ts.current()['site']) == encoded(before['site']), 'all suggestions preserve the site')


def scenario_additions_use_hand_placing_and_strip_generator_fields():
    from services import twin_library
    before = yard()
    asset = 'polyhaven:' + next(iter(d.KIT['furniture'].values()))
    additions = {
        'planting': [{'id': 'new-plant', 'preset': d.KIT['shrubs'][0], 'at': [95, -60], 'height': 5,
                      'rotation': 30, 'by': 'compose', 'src': {'person': True}, 'read_geometry': {},
                      'confidence': .8, 'visible_in': [], 'device': 'light.x', 'entity': 'switch.x'}],
        'furniture': [{'id': 'new-chair', 'asset': asset, 'at': [96, -60], 'scale': 1.2}],
        'beds': [{'id': 'new-bed', 'polygon': [[90, -50], [94, -50], [94, -46], [90, -46]]}],
        'edges': [{'id': 'new-edge', 'polygon': [[95, -50], [99, -50], [99, -46], [95, -46]]}]}
    base = ts.current_id()
    result, err = send(additions)
    check(err is None, err)
    after = ts.current()
    forbidden = {'by', 'read_geometry', 'state', 'confidence', 'visible_in', 'device', 'entity'}
    for slot in additions:
        new = after['site'][slot][-1]
        check(len(after['site'][slot]) == len(before['site'][slot]) + 1, slot)
        check(not forbidden.intersection(new), new)
        op = {**{k: v for k, v in additions[slot][0].items() if k not in forbidden | {'src'}},
              'op': 'add_site_item' if slot in ('planting', 'furniture') else 'add_site_shape',
              'list': slot, 'require_inside': True}
        if slot == 'planting':
            op['asset'] = op.pop('preset')
        hand = {'site': copy.deepcopy(before['site'])}
        ops._site_op(hand, op, 'person', _batch_inplace=True)
        expected = hand['site'][slot][-1]
        check(encoded(new) == encoded(expected), ('ordinary hand piece', slot, new, expected))
        check(encoded(after['site'][slot][:-1]) == encoded(before['site'][slot]), slot)
    check(after['site']['compose_overrides'] == before['site']['compose_overrides'], 'overrides unchanged')
    ts.revert(base)
    check(encoded(ts.current()) == encoded(before), 'undo restores every byte including overrides')


def scenario_bad_new_pieces_are_refused():
    before = yard()
    valid = {'preset': d.KIT['shrubs'][0], 'at': [95, -60]}
    cases = [('planting', {**valid, **f}) for f in (
        {'preset': 'Palm Royal'}, {'asset': 'import-zzz'}, {'asset': 5}, {'asset': []},
        {'height': 0}, {'height': -1}, {'height': 'tall'}, {'scale': 0}, {'scale': -1}, {'scale': 99},
        {'at': [90000, 90000]}, {'at': [True, -60]}, {'tint': 5}, {'scale_axes': 'x'},
        {'kind': 'banana'}, {'name': {}}, {'id': []}, {'unknown': 1}, {'by': 5},
        {'src': None}, {'confidence': True}, {'visible_in': 5}, {'device': []})]
    cases += [('furniture', {'asset': 'polyhaven:zzz', 'at': [95, -60]}),
              ('beds', {'polygon': [[0, 0]] * 3}), ('edges', {'points': [[0, 0]] * 2}),
              ('beds', {'polygon': [[90000, 90000], [90005, 90000], [90000, 90005]]}),
              ('beds', {'id': 'plant-1', 'polygon': [[90, -50], [94, -50], [90, -46]]}),
              ('planting', {**valid, 'at': before['site']['planting'][0]['at']})]
    cases += [('planting', {**valid, 'at': [float(v) for v in before['site']['planting'][0]['at']]}),
              ('planting', {**valid, 'id': before['buildings'][0]['rooms'][0]['id']}),
              ('edges', {'points': [[95, -55], [99, -55]], 'material': None})]
    failures = []
    for i, (slot, piece) in enumerate(cases):
        ts.push_round(before, 'hand')
        result, err = send({slot: [piece]}, run=f'new-bad-{i}')
        passed = err is None and encoded(ts.current()['site']) == encoded(before['site']) and bool(result['notes'])
        print(f'    new-piece case {i}: {"PASS" if passed else "FAIL"}', flush=True)
        if not passed:
            failures.append(i)
    print('    rejected new-piece answers:', len(cases))
    check(not failures, ('invalid new pieces or rejection notes', failures))


def scenario_additions_are_limited_and_duplicates_are_not_added():
    before = yard()
    pieces = [{'preset': d.KIT['shrubs'][0], 'at': [80+i, -95]} for i in range(26)]
    result, err = send({'planting': pieces + [pieces[0]]})
    check(err is None, err)
    check(len(ts.current()['site']['planting']) == len(before['site']['planting']) + 25, '25 additions maximum')
    check(any('25' in n for n in result['notes']), result['notes'])


def scenario_terrace_interplay_survives_critique_and_store():
    p = yard()
    house = p['buildings'][0]
    house['base'] = 0
    house['foundation'] = {'mode': 'fixed', 'offset_ft': 0, 'thickness_ft': 1}
    poly = [[-5, -5], [45, -5], [45, 30], [-5, 30]]
    p['site']['terraces'] = [{'id': 'hill', 'polygon': poly, 'height': 3, 'blend': 0, 'src': {'person': True}},
                              {'id': 'cut', 'polygon': poly, 'height': 0, 'blend': 0, 'src': {'person': True}}]
    ts.push_round(p, 'hand')
    before = ts.current()
    check(len(before['site']['terraces']) == 2, 'both terrain layers exist')
    raw_before = ts.current_model()
    result, err = send({'terraces': [{'id': 'cut', 'polygon': [[-5, -5], [20, -5], [20, 30], [-5, 30]]}],
                        'planting':[{'id':'accepted-new','preset':d.KIT['shrubs'][0],'at':[95,-60]}]})
    check(err is None, err)
    stored = ts.current_model()
    check(stored['site']['planting'].pop()['id'] == 'accepted-new', 'C1 reaches publication')
    check(encoded(stored) == encoded(raw_before), 'C1 every raw connected record preserved in stored model')
    check(result['notes'], 'terrace edit is a suggestion')


def scenario_storage_guard_refuses_a_changed_existing_piece():
    yard()
    before, rid, rounds = ts.current(), ts.current_id(), len(ts.rounds())
    real = d.tdir._enforce_kit
    def corrupt(*a, **kw):
        model = real(*a, **kw)
        model['site']['devices'] = []
        return model
    with patch.object(d.tdir, '_enforce_kit', side_effect=corrupt):
        result, err = send({})
    check(result is None and err and 'Nothing was saved' in err, (result, err))
    check(ts.current_id() == rid and len(ts.rounds()) == rounds and encoded(ts.current()) == encoded(before), 'failed guard saves nothing')


def scenario_nonconverging_normalization_saves_nothing():
    from services import twin_model
    yard()
    rid, rounds = ts.current_id(), len(ts.rounds())
    real = twin_model.normalize
    def unstable(plan, **kw):
        out, notes = real(plan, **kw)
        out['normalizer_probe'] = not plan.get('normalizer_probe', False)
        return out, notes
    with patch.object(twin_model, 'normalize', side_effect=unstable):
        result, err = send({})
    check(result is None and 'stable plan' in err and 'Nothing was saved' in err, (result, err))
    check(ts.current_id() == rid and len(ts.rounds()) == rounds, 'no unstable round is stored')


def scenario_storage_guard_covers_records_hidden_by_flatten():
    from services import twin_model_bridge
    yard()
    model = ts.current_model()
    hidden = {**copy.deepcopy(model['buildings'][0]['walls'][0]), 'id': 'hidden-wall', 'state': 'proposal'}
    model['buildings'][0]['walls'].append(hidden)
    with ts.LIFECYCLE, ts._LOCK:
        ts._append_round(ts._state(), model, 'hand')
    before, rid, rounds = ts.current_model(), ts.current_id(), len(ts.rounds())
    check(not any(w['id'] == 'hidden-wall' for w in ts.current()['buildings'][0]['walls']), 'proposal hidden in flat view')
    real = d.tdir._enforce_kit
    def omit_hidden(*a, **kw):
        out = real(*a, **kw)
        out['buildings'][0]['walls'] = [w for w in out['buildings'][0]['walls'] if w['id'] != 'hidden-wall']
        return out
    with patch.object(d.tdir, '_enforce_kit', side_effect=omit_hidden):
        result, err = send({})
    check(result is None and err and 'Nothing was saved' in err, (result, err))
    check(ts.current_id() == rid and len(ts.rounds()) == rounds and encoded(ts.current_model()) == encoded(before), 'serialized proposal is preserved')


def scenario_idless_extensions_do_not_break_person_edits():
    d._fresh(photos=0)
    yard()
    ts._invalidate_reads()
    model = ts.current_model()
    building = model['buildings'][0]
    # The fixture's id-less awnings have already migrated by this load. They
    # must have stable, usable identities, including across cold store reads.
    awnings = [p for p in building['roofs'] if p.get('support', {}).get('kind') == 'bracket']
    check(awnings and all(p.get('id') for p in awnings), 'legacy awnings became identified roofs')
    ts._invalidate_reads()
    check(ts.current_model() == model, 'two cold loads keep awning ids and all other records stable')
    # An unrelated id-less legacy extension must still survive ordinary edits.
    legacy = {'kind': 'legacy-detail', 'notes': 'Retained authored detail'}
    building['extensions'].append(legacy)
    room = building['rooms'][0]
    changed, _ = ops.apply(model, {'op': 'set', 'building': building['id'], 'id': room['id'], 'field': 'name', 'value': 'Den'})
    check(next(p for p in changed['buildings'][0]['rooms'] if p['id'] == room['id'])['name'] == 'Den', 'ordinary person edit works')
    check(changed['buildings'][0]['extensions'] == building['extensions'], 'id-less non-awning extension survives')
    check(changed['buildings'][0]['roofs'] == building['roofs'], 'person edit preserves migrated awnings')
    check(changed['site'] == model['site'] and tb.yard_occupied(changed), 'person edit keeps the protected yard')
    expected = copy.deepcopy(model)
    expected['buildings'][0]['rooms'][0].update(name='Den', src=changed['buildings'][0]['rooms'][0].get('src'))
    # Diagnostic derivation may reorder flags; protect their complete contents.
    for value in (expected, changed):
        value['buildings'][0]['flags'].sort(key=encoded)
    check(changed == expected, 'only the person edit and its provenance change; complete flag contents retained')


def scenario_first_build_and_lot_then_buildings_match_main():
    import test_twin_build_chain as chain
    chain._place()
    ids = chain._follow(tb.start({'part': 'place'}, reader=chain.ThreadReader(), inline=True))
    check([len(ts.current()['site'][n]) for n in ('planting', 'beds', 'edges')] == [22, 3, 14], 'I5 first chain table')
    chain._place()
    counts = []
    for part in ('lot', 'house', 'shed'):
        chain._follow(tb.start({'part': part}, reader=chain.ThreadReader(), inline=True))
        counts.append(len(ts.current()['site']['planting']))
    check(counts == [61, 49, 22], ('I7 successive builds table', counts))
    final = [len(ts.current()['site'][n]) for n in ('planting', 'beds', 'edges')]
    # On this repository's standard fixture main has 13 generated edges plus
    # its retained read edge. Verified by replaying HEAD's build source.
    check(final == [22, 3, 14], ('I7 final layout', final))
    from services import twin_compose
    footprints, _, _ = twin_compose._building_geometry(ts.current()['buildings'], [])
    check(not any(twin_compose._inside(p['at'], poly) for p in ts.current()['site']['planting'] for poly in footprints), 'no plants inside footprints')


def scenario_compose_occupancy_and_foundation_notes():
    import test_twin_compose as ct
    import test_twin_build_chain as chain
    table = [(meta, occupied, {}, False) for meta, occupied in (
             ({'by': 'compose'}, False), ({'by': 'compose', 'src': {'person': True}}, True),
             ({}, True), ({'src': {'sheet': 's', 'page': 1, 'step': 'site'}}, False),
             ({'src': {'person': True}}, True), ({'state': 'ghost'}, False), ({'state': 'proposal'}, False))]
    table += [({'by': 'compose'}, True, override, False) for override in (
        {'removed': ['old']}, {'moved': {'old': [1, 2]}}, {'properties': {'old': {'scale': 1.4}}})]
    table += [({'by': 'compose'}, False, {}, True)]
    for i, (meta, occupied, overrides, history) in enumerate(table):
        chain._place()
        p = ct._plan()
        p['site'].update(planting=[], beds=[], edges=[{'id': 'edge-one', 'points': [[60, -50], [70, -50]], **meta}])
        p['site']['compose_overrides'] = overrides
        captured = {}
        def update(mutator, **kw): captured['plan'] = mutator(copy.deepcopy(p))
        b = {'id': 'occupancy', 'inputs': {'part': 'lot'}, 'generation': ts.generation(), 'cost': 0, 'events': [], 'seq': 0}
        s = tb._step('compose'); b['steps'] = [s]
        real = tb.twin_compose.compose
        def compose(*a, **kw):
            out, notes = real(*a, **kw)
            return out, notes + ['Foundations were skipped for the House: its outside walls do not close yet.']
        with patch.object(ts, 'update_current', side_effect=update), patch.object(tb.twin_compose, 'compose', side_effect=compose), \
                patch.object(ts, 'has_director_rounds', return_value=history, create=True):
            tb._settle(b, s, {'fragment': {}, 'problems': []})
        logs = [e.get('text', '') for e in b['events']]
        check(any('Foundations were skipped' in n for n in logs), ('M4', i))
        check(('Kept your yard. Plants and beds are laid out only in an empty yard.' in logs) == occupied, ('edges table', i, logs))
        if occupied:
            normal = twin_plan.normalize(p)[0]
            check(all(encoded(captured['plan']['site'][n]) == encoded(normal['site'][n])
                      for n in ('planting', 'beds', 'edges')), ('occupied lists unchanged', i))
        else:
            check(captured['plan']['site']['planting'] and captured['plan']['site']['beds'], ('untouched yard relaid', i))
    with patch.object(ts, '_state', return_value={'rounds': [], 'pruned_runs': {'old': {'director': 1}}}):
        check(not tb.yard_occupied({'site':{'planting':[{'by':'compose'}]}}), 'pruned history does not lock a yard')


def scenario_compose_confirmation_api_agent_and_failed_attempt():
    import test_twin_build_chain as chain
    from services import agent_tools_v2 as agent
    from fastapi.testclient import TestClient
    import main
    chain._place()
    bid = tb.start({'part': 'shed'}, reader=chain.ThreadReader(), inline=True)
    chain._follow(bid)
    p = ts.current()
    p['site']['planting'].append({'id': 'hand', 'at': [95, -60], 'preset': d.KIT['shrubs'][0], 'height': 4})
    p['site']['edges'].append({'id': 'generated-to-regenerate', 'by': 'compose', 'points': [[80, 80], [90, 80]]})
    ts.push_round(p, 'hand')
    before, rid = ts.current(), ts.current_id()
    c = TestClient(main.app)
    response = c.post(f'/api/house/editor/build/{bid}/reread', json={'step': 'compose'})
    check(response.status_code == 400 and 'confirm' in response.text.lower(), response.text)
    check(ts.current_id() == rid, 'unconfirmed API saves nothing')
    for invalid in ('true', 1, False):
        response = c.post(f'/api/house/editor/build/{bid}/reread', json={'step': 'compose', 'confirm': invalid})
        check(response.status_code == 400 and ts.current_id() == rid, 'API requires literal true')
    with patch.object(agent, 'house_design_status', return_value={'build': bid}):
        result = agent.handle_house_design({'action': 'reread', 'step': 'compose'}, actor={'id': 'parent', 'role': 'parent'})
        check(result['status'] == 'confirmation_required' and '?' in result['message'], result)
        check(ts.current_id() == rid, 'agent asks before changing yard')
        result = agent.handle_house_design({'action': 'reread', 'step': 'compose', 'confirm': 'true'}, actor={'id': 'parent', 'role': 'parent'})
        check(result['status'] == 'error' and ts.current_id() == rid, 'agent requires a real boolean confirmation')
        with patch.object(tb, '_dispatch'):
            result = agent.handle_house_design({'action': 'reread', 'step': 'compose', 'confirm': True}, actor={'id': 'parent', 'role': 'parent'})
        check(result['status'] == 'ok', result)
    tb.stop(bid)
    # Dispatch was deliberately held; retire that fake worker as a real
    # worker's finally block would do before attempting another read.
    tb._WORKERS[bid]['busy'] = False
    check(not any(s.get('recompose') for s in tb._get(bid)['steps']), 'stop clears marker')
    with patch.object(tb, '_settle', side_effect=RuntimeError('failed settle')):
        tb.reread(bid, 'compose', confirm=True, inline=True)
    check(not any(s.get('recompose') for s in tb._get(bid)['steps']), 'failed settle clears marker')
    check(ts.current_id() == rid, 'failed settle saved no house round')
    # The actual API forwards explicit confirmation; dispatch is held for determinism.
    with patch.object(tb, '_dispatch'):
        response = c.post(f'/api/house/editor/build/{bid}/reread', json={'step': 'compose', 'confirm': True})
    check(response.status_code == 200, response.text)
    tb.stop(bid)
    tb._WORKERS[bid]['busy'] = False
    tb.reread(bid, 'compose', confirm=True, inline=True)
    check(not any(p['id'] == 'generated-to-regenerate' for p in ts.current()['site']['edges']), 'confirmed attempt really recomposes')
    check(not any(s.get('recompose') for s in tb._get(bid)['steps']), 'success also consumes confirmation')


SCENARIOS = [value for name, value in list(globals().items()) if name.startswith('scenario_')]
if __name__ == '__main__':
    failed = []
    for fn in SCENARIOS:
        try:
            fn()
            print('  ok ', fn.__name__, flush=True)
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, str(exc)[:500], flush=True)
    print(f'{len(SCENARIOS)-len(failed)}/{len(SCENARIOS)} passed')
    sys.exit(bool(failed))
