"""The art director: one critique round reads renders plus the household's
photos against the kit's brief and returns a revised site and materials
(spec docs/superpowers/specs/2026-11-06-house-digital-twin-design.md
sections 8.4, 8.6; plan Task 8). The model is stubbed at
model_pools.call_pool_json; storage, ledger, plan and kit are real.

Run from chauffeur/:  python tests/test_twin_director.py
"""
import base64
import copy
import io
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_director_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import storage, model_pools  # noqa: E402
from services import twin_compose, twin_library, twin_plan  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_director as tdir  # noqa: E402
from services import twin_store as ts  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_poolhouse.plan.json')
KIT = twin_library.kit('modern_farmhouse')
PRICED = 'gemini-4-argon'


def _png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (16, 10), (90, 120, 80)).save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


def _jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), (180, 180, 175)).save(buf, format='JPEG')
    return buf.getvalue()


def _fresh(photos=2):
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None,
                            'llm_provider': 'gemini', 'llm_gemini_paid_api_key': 'paid-k'})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    with open(_FIXTURE, encoding='utf-8') as f:
        plan = twin_plan.normalize(json.load(f))[0]
    plan, _ = twin_compose.compose(plan, KIT, seed=1)
    for i in range(photos):
        ts.save_source('photo', f'p{i}.jpg', _jpeg())
    rid = ts.push_round(plan, 'draft')
    # The baseline is the raw connected model this draft stored.
    return rid, ts.current()


class Critic:
    def __init__(self, revise=None, done=False, on_call=None):
        self.revise = revise or (lambda site, mats: (site, mats))
        self.done = done
        self.on_call = on_call
        self.calls = []

    def __call__(self, tier, api_key, system_prompt, user_prompt, **kw):
        check(system_prompt == tdir.DIRECTOR_PROMPT, 'the director prompt')
        self.calls.append({'tier': tier, 'key': api_key, 'user': user_prompt, **kw})
        if kw.get('usage') is not None:
            kw['usage'].append({'model': PRICED, 'input_tokens': 5000, 'output_tokens': 1000,
                                'images': len(kw.get('images') or []), 'prompt_chars': len(user_prompt),
                                'max_output_tokens': kw.get('max_output_tokens') or 0})
        if self.on_call:
            self.on_call()
        cur = ts.current()
        site, mats = self.revise(copy.deepcopy(cur['site']), copy.deepcopy(cur['materials']))
        return {'critique': 'Soften the patio edge; add a third shrub group.', 'done': self.done,
                'site': site, 'materials': mats}


def _run(critic, run='run-1', renders=None, cameras=('front', 'top'), base='current'):
    orig = model_pools.call_pool_json
    model_pools.call_pool_json = critic
    try:
        b = ts.current_id() if base == 'current' else base
        return tdir.critique(run, renders or [_png(), _png()], list(cameras), base=b)
    finally:
        model_pools.call_pool_json = orig


def scenario_a_round_changes_only_site_and_materials():
    rid, plan = _fresh()

    def revise(site, mats):
        site['buildings_hint'] = 'ignored'
        mats['roof'] = {'id': 'standing_seam', 'color': '#2f2622'}
        return site, mats
    critic = Critic(revise)
    critic_answer_buildings = copy.deepcopy(plan['buildings'])
    result, err = _run(critic)
    check(err is None and result, err)
    cur = ts.current()
    check(cur['buildings'] == critic_answer_buildings, 'buildings untouched by the director')
    check(cur['materials']['roof']['color'] == '#2f2622', 'materials taken from the director')
    check(result['round'] == ts.current_id() and ts.rounds()[-1]['kind'] == 'director'
          and ts.rounds()[-1]['run'] == 'run-1', ts.rounds()[-1])
    check(result['critique'] and result['done'] is False and result['cost'] > 0, result)
    check([e['stage'] for e in tc.entries()] == ['director'], tc.entries())


def scenario_the_call_carries_brief_photos_and_renders():
    _fresh(photos=6)
    critic = Critic()
    _run(critic, renders=[_png(), _png(), _png()], cameras=('front', 'porch', 'top'))
    c = critic.calls[0]
    check(c['tier'] == 'twin' and c['key'] == 'paid-k' and c.get('max_models') == 1 and c.get('strict_json') is True,
          (c['tier'], c.get('max_models')))
    check((c.get('max_output_tokens') or 0) >= 32768 and (c.get('timeout_s') or 0) >= 180, (c.get('max_output_tokens'), c.get('timeout_s')))
    check(c.get('thinking_level') == 'low', c.get('thinking_level'))
    check(isinstance(c.get('usage'), list), 'usage collected')
    imgs = c['images']
    check(sum(1 for i in imgs if i['mime'] == 'image/jpeg') == 4, 'at most four household photos')
    check(sum(1 for i in imgs if i['mime'] == 'image/png') == 3, 'every render')
    check(KIT['style_guide'][:60] in c['user'], 'the kit brief is in the prompt')
    for cam in ('front', 'porch', 'top'):
        check(cam in c['user'], f'renders are labelled by camera: {cam}')


def scenario_director_rounds_do_not_rerun_compose():
    _fresh()
    gone = {}

    def revise(site, mats):
        shrub = next(i for i in site['planting'] if i.get('by') == 'compose' and i['kind'] == 'shrub')
        gone['id'] = shrub['id']
        site['planting'] = [i for i in site['planting'] if i.get('id') != shrub['id']]
        return site, mats
    _run(Critic(revise))
    cur = ts.current()
    ids = {i.get('id') for i in cur['site']['planting']}
    check(gone['id'] in ids, 'an omitted shrub is kept')
    check(gone['id'] not in cur['site']['compose_overrides']['removed'], 'no removal is recorded')
    _run(Critic())
    check(gone['id'] in {i.get('id') for i in ts.current()['site']['planting']}, 'a second round keeps it too')


def scenario_assets_outside_the_kit_are_refused():
    _fresh()

    def revise(site, mats):
        mats['siding'] = {'id': 'gold_leaf', 'color': '#ffd700'}
        site['planting'].append({'kind': 'tree', 'preset': 'Palm Royal', 'at': [100, -80], 'height': 40, 'seed': 5})
        site['furniture'].append({'asset': 'polyhaven:hot_tub_9000', 'at': [20, -5], 'rotation': 0})
        return site, mats
    result, err = _run(Critic(revise))
    cur = ts.current()
    check(cur['materials']['siding']['id'] != 'gold_leaf', 'an off-kit material is refused')
    check(not any(p.get('preset') == 'Palm Royal' for p in cur['site']['planting']), 'an off-kit plant is refused')
    check(not any('hot_tub_9000' in f.get('asset', '') for f in cur['site']['furniture']), 'an off-kit model is refused')
    notes = ' '.join(result.get('notes', []))
    check('gold_leaf' in notes and 'Palm Royal' in notes and 'hot_tub_9000' in notes, notes)


def scenario_unchanged_hand_items_are_never_refused():
    rid, plan = _fresh()
    p = copy.deepcopy(plan)
    p['site']['furniture'].append({'kind': 'rocker', 'at': [34.0, 9.0], 'rotation': 90})      # kind only, by hand
    p['site']['planting'].append({'kind': 'tree', 'preset': 'Pine Small', 'at': [120.0, -90.0],
                                  'height': 20, 'seed': 77})                               # a preset outside the kit lists
    ts.save_hand_edit(p, 'my rocker and the pine by the gate', base=rid)
    result, err = _run(Critic())                                                            # echoes the site back unchanged
    cur = ts.current()
    check(any(f.get('kind') == 'rocker' for f in cur['site']['furniture']), 'an echoed hand rocker survives')
    check(any(t.get('preset') == 'Pine Small' for t in cur['site']['planting']), 'an echoed hand pine survives')
    check(not any('rocker' in n or 'Pine Small' in n for n in result.get('notes', [])), result.get('notes'))


def scenario_omitted_keys_and_empty_lists_keep_existing_pieces():
    rid, plan = _fresh()

    def partial(site, mats):
        keep = {'planting': site['planting'], 'hardscape': site['hardscape']}
        return keep, {'roof': mats['roof']}
    result, err = _run(Critic(partial))
    cur = ts.current()
    check(cur['site']['pool'] == plan['site']['pool'] and cur['site']['lot'] == plan['site']['lot']
          and cur['site']['beds'] == plan['site']['beds'], 'site keys the model left out are unchanged')
    check(cur['materials']['siding'] == plan['materials']['siding'], 'material roles left out are unchanged')
    check(not cur['site']['compose_overrides']['removed'], 'nothing left out is recorded as removed')
    check(any('unchanged' in n for n in result.get('notes', [])), result.get('notes'))

    def clear_edges(site, mats):
        site['edges'] = []
        return site, mats
    _run(Critic(clear_edges), run='run-2')
    check(ts.current()['site']['edges'] == plan['site']['edges'], 'an explicit empty list keeps edges')


def scenario_director_colours_are_validated():
    _fresh()

    def bad(site, mats):
        mats['trim'] = {'id': mats['trim']['id'], 'color': 'not-a-colour'}
        mats['door'] = 'mocha_oak_veneer'
        return site, mats
    before = copy.deepcopy(ts.current()['materials'])
    result, err = _run(Critic(bad))
    cur = ts.current()['materials']
    check(cur['trim'] == before['trim'] and cur['door'] == before['door'], f'invalid shapes keep the current value: {cur["trim"]}, {cur["door"]}')


def scenario_a_failed_model_call_is_still_costed():
    _fresh()

    def boom(tier, api_key, system_prompt, user_prompt, **kw):
        kw['usage'].append({'model': PRICED, 'input_tokens': None, 'output_tokens': None, 'images': 2,
                            'prompt_chars': len(user_prompt), 'max_output_tokens': kw.get('max_output_tokens') or 0})
        raise RuntimeError('503 upstream')
    orig = model_pools.call_pool_json
    model_pools.call_pool_json = boom
    try:
        result, err = tdir.critique('fail-run', [_png()], ['front'], base=ts.current_id())
    finally:
        model_pools.call_pool_json = orig
    check(result is None and err, err)
    check([e['stage'] for e in tc.entries()] == ['director'] and tc.entries()[0]['basis'] == 'estimated', tc.entries())


def scenario_a_second_concurrent_critique_is_refused():
    import threading
    _fresh()
    gate, release = threading.Event(), threading.Event()
    critic = Critic(on_call=lambda: (gate.set(), release.wait(10)))
    out = {}
    orig = model_pools.call_pool_json
    model_pools.call_pool_json = critic
    try:
        t = threading.Thread(target=lambda: out.setdefault('first', tdir.critique('a', [_png()], ['front'], base=ts.current_id())))
        t.start()
        check(gate.wait(10), 'first round in flight')
        second = tdir.critique('b', [_png()], ['front'], base=ts.current_id())
        release.set()
        t.join(10)
    finally:
        model_pools.call_pool_json = orig
        release.set()
    check(second[0] is None and 'already running' in second[1], second)
    check(out['first'][1] is None, out['first'])


def scenario_a_top_level_null_changes_nothing():
    rid, plan = _fresh()
    before = copy.deepcopy(ts.current())
    for empty, run in ((None, 'null-none'), ([], 'null-empty')):
        result, err = _run(Critic(lambda site, mats, e=empty: (e, e)), run=run)
        check(err is None and result, err)
        cur = ts.current()
        check(cur['site']['lot'] == before['site']['lot'] and cur['site']['pool'] == before['site']['pool']
              and cur['materials'] == before['materials'] and not cur['site']['compose_overrides']['removed'],
              f'site/materials of {empty!r} keep the yard')
        check(any('unchanged' in n for n in result.get('notes', [])), result.get('notes'))


def scenario_the_director_cannot_move_the_lot_or_the_pool():
    _fresh()
    before = copy.deepcopy(ts.current()['site'])

    def move(site, mats):
        site['lot'] = [[0, 0], [10, 0], [10, 10]]
        site['pool']['polygon'] = [[50, 50], [60, 50], [60, 60], [50, 60]]
        return site, mats
    result, err = _run(Critic(move))
    cur = ts.current()['site']
    check(cur['lot'] == before['lot'] and cur['pool'] == before['pool'], 'plot-plan facts stay put')
    notes = ' '.join(result.get('notes', []))
    check('lot' in notes and 'pool' in notes, notes)


def scenario_director_requests_over_the_size_budget_are_refused():
    _fresh()
    critic = Critic()
    orig = tdir.MAX_REQUEST_B64
    tdir.MAX_REQUEST_B64 = 100
    try:
        result, err = _run(critic)
    finally:
        tdir.MAX_REQUEST_B64 = orig
    check(result is None and err and critic.calls == [], err)


def scenario_round_cap_is_five_per_run():
    _fresh()
    def material_each_round(site, mats):
        mats['roof']['color'] = f'#{len(critic.calls):06x}'
        return site, mats
    critic = Critic(material_each_round)
    for i in range(tc.ROUND_CAP):
        result, err = _run(critic, run='cap-run')
        check(err is None, f'round {i + 1}: {err}')
    result, err = _run(critic, run='cap-run')
    check(result is None and 'round cap reached' in err, err)
    check(len(critic.calls) == tc.ROUND_CAP, 'no model call for the refused round')
    result, err = _run(critic, run='another-run')
    check(err is None, 'a new run starts a new count')


def scenario_checkpoint_blocks_a_round():
    _fresh()
    tc.record('earlier', [{'model': PRICED, 'input_tokens': 1_050_000, 'output_tokens': 0,
                           'images': 0, 'prompt_chars': 0, 'max_output_tokens': 0}])        # $10.50
    critic = Critic()
    try:
        _run(critic)
    except tc.CheckpointReached as e:
        check(e.checkpoint == 10.0, e.checkpoint)
    else:
        raise AssertionError('a blocking checkpoint raises CheckpointReached')
    check(critic.calls == [], 'no model call past a checkpoint')


def scenario_a_revert_during_a_critique_wins():
    first, _ = _fresh()
    p2 = copy.deepcopy(ts.current())
    p2['materials']['trim']['color'] = '#eeeeee'
    second = ts.push_round(p2, 'hand', base=first)
    critic = Critic(lambda site, mats: (site, {**mats, 'roof': {**mats['roof'], 'color': '#123456'}}),
                    on_call=lambda: ts.revert(first))           # a parent reverts while the model thinks
    result, err = _run(critic, base=second)
    check(err is None and result['stale'] is True, result)
    check(ts.rounds()[-1]['stale'] is True and ts.rounds()[-2]['kind'] == 'revert', ts.rounds()[-2:])
    check(ts.current()['materials']['trim']['color'] != '#eeeeee', 'the revert stays current')


def scenario_critique_route():
    _fresh()
    from fastapi.testclient import TestClient
    import main
    from services import auth
    check(auth.resolve('POST', '/api/house/twin/critique') == auth.PARENTS, 'parents only')
    orig = model_pools.call_pool_json
    model_pools.call_pool_json = Critic()
    try:
        c = TestClient(main.app)
        r = c.post('/api/house/twin/critique', json={'run': 'r', 'renders': [_png()], 'cameras': ['front'],
                                                    'base': ts.current_id()})
        check(r.status_code == 200 and r.json()['result']['round'] == ts.current_id(), r.text[:300])
        r = c.post('/api/house/twin/critique', json={'run': 'r', 'renders': ['not-base64!'], 'cameras': ['front'],
                                                    'base': ts.current_id()})
        check(r.status_code == 400, f'a render that is not a PNG is a 400: {r.status_code}')
        r = c.post('/api/house/twin/critique', json={'run': 'r', 'renders': [_png()], 'cameras': ['front', 'top'],
                                                    'base': ts.current_id()})
        check(r.status_code == 400, f'renders and cameras must pair up: {r.status_code}')
        tc.record('earlier', [{'model': PRICED, 'input_tokens': 1_100_000, 'output_tokens': 0,
                               'images': 0, 'prompt_chars': 0, 'max_output_tokens': 0}])
        r = c.post('/api/house/twin/critique', json={'run': 'r', 'renders': [_png()], 'cameras': ['front'],
                                                    'base': ts.current_id()})
        body = r.json()
        detail = body.get('detail', body)
        check(r.status_code == 409 and detail['checkpoint'] == 10.0, r.text)
    finally:
        model_pools.call_pool_json = orig


def _finished_yard():
    """Invented owner-shaped yard; no household data in fixtures or logs."""
    _fresh(photos=0)
    plan = ts.current()
    site = plan['site']
    site['planting'] = [dict(id=f'plant-{i}', kind='shrub', preset=KIT['shrubs'][0],
                             at=[60 + i, -60], height=4, seed=i,
                             **({'by': 'compose', 'read_geometry': {'at': [60 + i, -60]}}
                                if i % 2 else {'src': {'person': True}})) for i in range(12)]
    site['beds'] = [dict(id=f'bed-{i}', polygon=[[60, -50], [70, -50], [70, -45], [60, -45]],
                         by='compose') for i in range(2)]
    site['edges'] = [dict(id='edge-1', points=[[60, -50], [70, -50]], src={'person': True})]
    site['furniture'] = [dict(id='chair-1', asset='personal:chair', at=[50, -60], rotation=90)]
    site['terraces'] = []  # populate a valid pad through the shared validator below
    from services import twin_terrain
    site['terraces'] = [dict(id='pad-1', polygon=[[60, -70], [70, -70], [70, -65], [60, -65]],
                             height=0, edge='slope')]
    check(twin_terrain.pad_error(site['terraces'][0]) is None, 'valid synthetic terrace')
    site['fence'] = dict(id='fence-1', points=[[80, -70], [80, -40]], height=4)
    site['fire_pit'] = dict(id='fire-1', at=[60, -80], radius=3)
    plan, _ = twin_plan.normalize(plan)
    check(plan['site']['fence'] and plan['site']['fire_pit'], 'valid synthetic fixtures')
    ts.push_round(plan, 'hand', base=ts.current_id())
    return ts.current()


def scenario_finished_yard_sparse_patch_is_one_undoable_round():
    before = _finished_yard()
    base, rounds = ts.current_id(), len(ts.rounds())
    patch = {'planting': [{'id': 'plant-0', 'height': 7},
                          {'id': 'new-plant', 'kind': 'shrub', 'preset': KIT['shrubs'][0], 'at': [90, -60]},
                          {'kind': 'tree', 'preset': KIT['backdrop_trees'][0], 'at': [90, -80]}]}
    result, err = _run(Critic(lambda site, mats: (patch, {})))
    check(err is None, err)
    after = ts.current()
    check(len(after['site']['planting']) == 14, 'omissions retained; unknown and absent ids add pieces')
    changed = after['site']['planting'][0]
    check(changed == before['site']['planting'][0], 'existing plant is only a suggestion')
    check(after['site']['planting'][1:12] == before['site']['planting'][1:], 'all other plants retained')
    check(any('changing 1 plant' in n for n in result['notes'])
          and not any('removing' in n for n in result['notes']), result['notes'])
    check(len(ts.rounds()) == rounds + 1, 'one history step per round')
    ts.revert(base)
    check(ts.current() == before, 'undo restores the entire yard')


def scenario_finished_yard_removal_suggestions_never_apply():
    for key in ('planting', 'beds', 'edges', 'furniture', 'hardscape', 'terraces'):
        for suggestion in ([], None, {'remove': True}):
            before = _finished_yard()
            merged, notes = twin_plan.overlay_director(before, {'site': {key: suggestion}})
            check(merged['site'][key] == before['site'][key], (key, suggestion))
            if before['site'][key]:
                check(any(f'removing {len(before["site"][key])} ' in n and 'nothing was changed' in n
                          for n in notes), notes)
    before = _finished_yard()
    for marker in ({'remove': True}, {'delete': True}, {'deleted': True}, {'_delete': True},
                   {'op': 'remove'}, {'action': 'delete'}, {'state': 'ghost'}, {'state': 'proposal'}):
        merged, notes = twin_plan.overlay_director(before, {'site': {'planting': [{'id': 'plant-0', **marker}]}})
        check(merged['site']['planting'] == before['site']['planting'], marker)
        check(any('removing 1 plant; nothing was changed' in n for n in notes), notes)


def scenario_non_list_site_values_are_kept_with_notes():
    before = _finished_yard()
    for key in ('fire_pit', 'fence', 'lot', 'pool', 'compose_overrides'):
        for value in (None, [], {'radius': 99}, 'remove'):
            merged, notes = twin_plan.overlay_director(before, {'site': {key: value}})
            check(merged['site'][key] == before['site'][key], (key, value))
            label = 'saved yard edits' if key == 'compose_overrides' else key.replace('_', ' ')
            check(any(label in n and ('suggested' in n or 'Kept' in n) for n in notes), notes)


def scenario_every_existing_piece_is_only_a_suggestion():
    before = _finished_yard()
    # Fire pits and fences also have legacy list forms; they follow the same rule.
    for key in ('fire_pit', 'fence'):
        before['site'][key] = [before['site'][key], {**before['site'][key], 'id': key + '-2'}]
    for key in ('planting', 'beds', 'edges', 'furniture', 'hardscape', 'terraces', 'fire_pit', 'fence'):
        original = before['site'][key]
        check(original, ('fixture has pieces', key))
        patch = {'id': original[0]['id'], 'name': 'Updated name'}
        after, _ = twin_plan.overlay_director(before, {'site': {key: [patch]}})
        check(after['site'][key] == original, key)
        for suggestion in ([], None, [{'id': original[0]['id'], 'delete': True}]):
            after, _ = twin_plan.overlay_director(before, {'site': {key: suggestion}})
            check(after['site'][key] == original, (key, suggestion))
    result, err = _run(Critic(lambda site, mats: ({'planting': [{'id': 'plant-0', 'at': None}]}, {})))
    check(err is None, err)
    check(ts.current()['site']['planting'] == before['site']['planting'], 'invalid edit cannot normalize a plant away')


def scenario_off_kit_updates_keep_all_existing_fields():
    before = _finished_yard()
    patch = {'planting': [{'id': 'plant-0', 'preset': 'Palm Royal', 'height': 9}],
             'furniture': [{'id': 'chair-1', 'asset': 'polyhaven:hot_tub_9000', 'rotation': 45}]}
    result, err = _run(Critic(lambda site, mats: (patch, {})))
    check(err is None, err)
    after = ts.current()['site']
    check(after == before['site'], 'all changes to existing pieces are suggestions')
    check(any('changing 1 plant' in n for n in result['notes'])
          and any('changing 1 furnishing' in n for n in result['notes']), result['notes'])
    # An existing off-kit piece may still be moved without being refused.
    result, err = _run(Critic(lambda site, mats: ({'furniture': [{'id': 'chair-1', 'rotation': 10}]}, {})), run='move')
    check(err is None and ts.current()['site']['furniture'][0]['rotation'] == before['site']['furniture'][0]['rotation'], err)


def scenario_new_piece_id_cannot_steal_another_lists_identity():
    before = _finished_yard()
    new_bed = {**before['site']['beds'][0], 'id': 'plant-0'}
    result, err = _run(Critic(lambda site, mats: ({'beds': [new_bed]}, {})))
    check(err is None, err)
    after = ts.current()['site']
    check(after['planting'] == before['site']['planting'], 'all existing plant identities and fields survive')
    check(after['beds'] == before['site']['beds'], 'a colliding id is refused')
    check(result['notes'], 'duplicate identity is explained')


if __name__ == '__main__':
    for fn in (scenario_a_round_changes_only_site_and_materials,
               scenario_the_call_carries_brief_photos_and_renders,
               scenario_director_rounds_do_not_rerun_compose,
               scenario_assets_outside_the_kit_are_refused,
               scenario_unchanged_hand_items_are_never_refused,
               scenario_omitted_keys_and_empty_lists_keep_existing_pieces,
               scenario_director_colours_are_validated,
               scenario_a_failed_model_call_is_still_costed,
               scenario_a_second_concurrent_critique_is_refused,
               scenario_a_top_level_null_changes_nothing,
               scenario_the_director_cannot_move_the_lot_or_the_pool,
               scenario_director_requests_over_the_size_budget_are_refused,
               scenario_round_cap_is_five_per_run,
               scenario_checkpoint_blocks_a_round,
               scenario_a_revert_during_a_critique_wins,
               scenario_critique_route,
               scenario_finished_yard_sparse_patch_is_one_undoable_round,
               scenario_finished_yard_removal_suggestions_never_apply,
               scenario_non_list_site_values_are_kept_with_notes,
               scenario_every_existing_piece_is_only_a_suggestion,
               scenario_off_kit_updates_keep_all_existing_fields,
               scenario_new_piece_id_cannot_steal_another_lists_identity):
        fn()
        print('  ok ', fn.__name__)
