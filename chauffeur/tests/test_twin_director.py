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
    return ts.push_round(plan, 'draft'), plan


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
    check((c.get('max_output_tokens') or 0) >= 8192 and (c.get('timeout_s') or 0) >= 180, (c.get('max_output_tokens'), c.get('timeout_s')))
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
    check(gone['id'] not in ids, 'the removed shrub stays removed')
    check(gone['id'] in cur['site']['compose_overrides']['removed'], 'and is remembered for any later recompose')
    _run(Critic())
    check(gone['id'] not in {i.get('id') for i in ts.current()['site']['planting']}, 'a second round does not bring it back')


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


def scenario_round_cap_is_five_per_run():
    _fresh()
    critic = Critic()
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
    critic = Critic(on_call=lambda: ts.revert(first))           # a parent reverts while the model thinks
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


if __name__ == '__main__':
    for fn in (scenario_a_round_changes_only_site_and_materials,
               scenario_the_call_carries_brief_photos_and_renders,
               scenario_director_rounds_do_not_rerun_compose,
               scenario_assets_outside_the_kit_are_refused,
               scenario_round_cap_is_five_per_run,
               scenario_checkpoint_blocks_a_round,
               scenario_a_revert_during_a_critique_wins,
               scenario_critique_route):
        fn()
        print('  ok ', fn.__name__)
