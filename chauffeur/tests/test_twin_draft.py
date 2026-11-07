"""Drafting the twin plan from drawings, photos and the plot plan through
the model APIs (spec docs/superpowers/specs/2026-11-06-house-digital-twin-design.md
sections 8.1, 8.6; plan Task 6). The model is stubbed at
model_pools.call_pool_json; everything else is real.

Run from chauffeur/:  python tests/test_twin_draft.py
"""
import copy
import io
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_draft_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import storage, model_pools  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_draft as td  # noqa: E402
from services import twin_library as tl  # noqa: E402
from services import twin_store as ts  # noqa: E402


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_poolhouse.plan.json')
KIT = tl.kit('modern_farmhouse')
PRICED = 'gemini-4-argon'


def _fixture():
    with open(_FIXTURE, encoding='utf-8') as f:
        return json.load(f)


def _pdf(pages=2):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(612, 792)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), (180, 180, 175)).save(buf, format='JPEG')
    return buf.getvalue()


def _fresh(key=True):
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None,
                            'llm_provider': 'gemini', 'llm_gemini_paid_api_key': 'paid-k' if key else ''})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    drawing = ts.save_source('drawing', 'poolhouse.pdf', _pdf(3))
    plot = ts.save_source('drawing', 'plot.pdf', _pdf(1))
    photo = ts.save_source('photo', 'dusk.jpg', _jpeg())
    return drawing, plot, photo


class Model:
    """Stands in for call_pool_json; answers by stage, records every call."""

    def __init__(self, answers=None, tokens=2000):
        f = _fixture()
        self.answers = {
            'building': {'buildings': f['buildings']},
            'finishes': {'materials': f['materials']},
            'site': {'site': {k: f['site'][k] for k in ('lot', 'hardscape', 'pool', 'fire_pit')}},
        }
        self.answers.update(answers or {})
        self.calls = []
        self.tokens = tokens

    def stage_of(self, system_prompt):
        for stage, prompt in (('building', td.BUILDING_PROMPT), ('finishes', td.FINISHES_PROMPT),
                              ('site', td.SITE_PROMPT)):
            if system_prompt == prompt:
                return stage
        raise AssertionError('unknown system prompt')

    def __call__(self, tier, api_key, system_prompt, user_prompt, **kw):
        stage = self.stage_of(system_prompt)
        self.calls.append({'stage': stage, 'tier': tier, 'key': api_key, 'user': user_prompt, **kw})
        if kw.get('usage') is not None:
            kw['usage'].append({'model': PRICED, 'input_tokens': self.tokens, 'output_tokens': 0,
                                'images': len(kw.get('images') or []), 'prompt_chars': len(user_prompt),
                                'max_output_tokens': kw.get('max_output_tokens') or 0})
        return copy.deepcopy(self.answers[stage])


def _run(model, **kw):
    orig = model_pools.call_pool_json
    model_pools.call_pool_json = model
    try:
        return td.draft(**kw)
    finally:
        model_pools.call_pool_json = orig


def scenario_three_stages_build_one_round():
    drawing, plot, photo = _fresh()
    m = Model()
    result, notes, err = _run(m, drawings=[{'id': drawing, 'pages': [1, 3]}], photos=[photo],
                              site={'id': plot, 'pages': [1]})
    check(err is None and result is not None, (err, notes))
    check([c['stage'] for c in m.calls] == ['building', 'finishes', 'site'], [c['stage'] for c in m.calls])
    for c in m.calls:
        check(c['tier'] == 'twin' and c['key'] == 'paid-k', (c['tier'], c['key']))
        check(c.get('max_models') == 1, 'one provider request per stage')
        check(c.get('strict_json') is True and (c.get('max_output_tokens') or 0) >= 8192, c.get('max_output_tokens'))
        check(c.get('thinking_level') == 'low', f'thinking held low so it cannot eat the output budget: {c.get("thinking_level")}')
        check(isinstance(c.get('usage'), list), 'usage collected')
    check(m.calls[0]['max_output_tokens'] >= 65536, 'the building stage has room for a whole house')
    check(result.get('stale') is False, 'a draft result says whether it landed stale')
    check(len(m.calls[0]['images']) == 2 and len(m.calls[1]['images']) == 1 and len(m.calls[2]['images']) == 1,
          'chosen drawing pages, the photo, the plot page')
    plan = ts.current()
    check(plan == result['plan'] and isinstance(result['round'], int), 'the draft round is current')
    check(plan['buildings'][0]['roof']['main']['pitch'] == 11 and plan['materials']['siding']['id'] == 'board_and_batten',
          'building and finishes from the model')
    check(any(i.get('by') == 'compose' for i in plan['site']['planting']), 'the yard was composed')
    check(ts.rounds()[-1]['kind'] == 'draft' and ts.rounds()[-1]['run'] == result['run'], ts.rounds()[-1])
    check([e['stage'] for e in tc.entries()] == ['building', 'finishes', 'site'], tc.entries())
    check(abs(result['cost'] - tc.total()) < 1e-9 and result['cost'] > 0, result['cost'])


def scenario_a_partial_model_answer_still_drafts():
    drawing, plot, photo = _fresh()
    m = Model({'finishes': {'error': 'model unavailable'}})
    result, notes, err = _run(m, drawings=[{'id': drawing, 'pages': [1]}], photos=[photo], site={'id': plot, 'pages': [1]})
    check(err is None and result is not None, err)
    mats = ts.current()['materials']
    check(mats['siding'] == {'id': KIT['materials']['siding']['asset'], 'color': KIT['materials']['siding']['color']},
          f'kit defaults stand in: {mats.get("siding")}')
    check(any('finishes' in n for n in notes), notes)


def scenario_finishes_outside_the_kit_are_replaced():
    drawing, plot, photo = _fresh()
    mats = copy.deepcopy(_fixture()['materials'])
    mats['siding'] = {'id': 'gold_leaf', 'color': '#ffd700'}
    m = Model({'finishes': {'materials': mats}})
    result, notes, err = _run(m, drawings=[{'id': drawing, 'pages': [1]}], photos=[photo], site={'id': plot, 'pages': [1]})
    check(ts.current()['materials']['siding']['id'] == KIT['materials']['siding']['asset'], 'kit asset used')
    check(any('gold_leaf' in n for n in notes), notes)


def scenario_checkpoint_stops_before_the_next_stage():
    drawing, plot, photo = _fresh()
    tc.record('earlier', [{'model': PRICED, 'input_tokens': 999_000, 'output_tokens': 0,
                           'images': 0, 'prompt_chars': 0, 'max_output_tokens': 0}])      # $9.99 at $10/M
    m = Model(tokens=2000)                                                                # +$0.02
    from fastapi.testclient import TestClient
    import main
    orig = model_pools.call_pool_json
    model_pools.call_pool_json = m
    try:
        c = TestClient(main.app)
        r = c.post('/api/house/twin/draft', json={'drawings': [{'id': drawing, 'pages': [1]}],
                                                  'photos': [photo], 'site': {'id': plot, 'pages': [1]}})
        check(r.status_code == 409, f'{r.status_code} {r.text}')
        body = r.json()
        detail = body.get('detail', body)
        check(detail['checkpoint'] == 10.0 and detail['total'] > 10 and detail['run'], detail)
        check([x['stage'] for x in m.calls] == ['building'], 'finishes never called')
        check(ts.rounds() == [], 'no round yet')

        tc.acknowledge(10.0)
        r = c.post('/api/house/twin/draft', json={'drawings': [{'id': drawing, 'pages': [1]}], 'photos': [photo],
                                                  'site': {'id': plot, 'pages': [1]}, 'run': detail['run']})
        check(r.status_code == 200, r.text)
    finally:
        model_pools.call_pool_json = orig
    check([x['stage'] for x in m.calls] == ['building', 'finishes', 'site'],
          f'the resumed run did not pay for the building stage again: {[x["stage"] for x in m.calls]}')
    check(len([r for r in ts.rounds() if r['kind'] == 'draft']) == 1, 'one draft round')


def scenario_rooms_are_named_with_or_without_ha():
    from services import ha_api
    drawing, plot, photo = _fresh()
    f = _fixture()
    for room in f['buildings'][0]['rooms']:
        room['name'] = ''
    orig = ha_api.get_area_registry
    ha_api.get_area_registry = lambda *a, **k: [{'area_id': 'gym', 'name': 'Gym'}, {'area_id': 'ph', 'name': 'Pool House'}]
    try:
        m = Model({'building': {'buildings': f['buildings']}})
        _run(m, drawings=[{'id': drawing, 'pages': [1]}], photos=[photo], site={'id': plot, 'pages': [1]})
    finally:
        ha_api.get_area_registry = orig
    check('Gym' in m.calls[0]['user'] and 'Pool House' in m.calls[0]['user'], 'HA area names reach the building prompt')

    drawing, plot, photo = _fresh()

    def down(*a, **k):
        raise OSError('no Home Assistant')
    ha_api.get_area_registry = down
    try:
        m = Model({'building': {'buildings': f['buildings']}})
        result, notes, err = _run(m, drawings=[{'id': drawing, 'pages': [1]}], photos=[photo],
                                  site={'id': plot, 'pages': [1]})
    finally:
        ha_api.get_area_registry = orig
    check(err is None, err)
    check(all(r['name'] for r in ts.current()['buildings'][0]['rooms']), 'every room has a name without HA')


def scenario_stages_get_real_timeouts_and_their_own_images():
    drawing, plot, photo = _fresh()
    m = Model()
    _run(m, drawings=[{'id': drawing, 'pages': [1]}], photos=[photo], site={'id': plot, 'pages': [1]})
    by = {c['stage']: c for c in m.calls}
    check((by['building'].get('timeout_s') or 0) >= 300, f'building timeout {by["building"].get("timeout_s")}')
    check((by['finishes'].get('timeout_s') or 0) >= 180 and (by['site'].get('timeout_s') or 0) >= 180,
          'finishes and site timeouts >= 180 s')
    check(all(i['mime'] == 'image/png' for i in by['building']['images']), 'building reads drawing pages')
    check(all(i['mime'] == 'image/jpeg' for i in by['finishes']['images']), 'finishes reads the photos')
    check(all(i['mime'] == 'image/png' for i in by['site']['images']), 'site reads the plot pages')


def scenario_stages_with_nothing_to_read_are_skipped():
    drawing, plot, photo = _fresh()
    m = Model()
    result, notes, err = _run(m, drawings=[{'id': drawing, 'pages': [1]}], photos=[], site=None)
    check(err is None and [c['stage'] for c in m.calls] == ['building'],
          f'no paid call for a stage with no images: {[c["stage"] for c in m.calls]}')
    plan = ts.current()
    check(plan['materials']['siding']['id'] == KIT['materials']['siding']['asset'], 'kit finishes without photos')
    check(not plan['site'].get('pool') and not plan['site'].get('hardscape'), 'no invented site without a plot plan')
    check(any('finishes' in n for n in notes) and any('site' in n for n in notes), notes)
    drawing, plot, photo = _fresh()
    m = Model()
    result, notes, err = _run(m, drawings=[], photos=[photo], site={'id': plot, 'pages': [1]})
    check(result is None and err and m.calls == [], 'no drawing pages: refused before any call')


def scenario_blank_rooms_get_descriptive_names_not_random_ha_areas():
    from services import ha_api
    drawing, plot, photo = _fresh()
    f = _fixture()
    rooms = f['buildings'][0]['rooms']
    rooms[0]['name'] = 'Sitting'
    rooms[2]['name'] = ''
    orig = ha_api.get_area_registry
    ha_api.get_area_registry = lambda *a, **k: [{'area_id': 'k', 'name': 'Kitchen'}, {'area_id': 'g', 'name': 'Garage'}]
    try:
        m = Model({'building': {'buildings': f['buildings']}})
        _run(m, drawings=[{'id': drawing, 'pages': [1]}], photos=[photo], site={'id': plot, 'pages': [1]})
    finally:
        ha_api.get_area_registry = orig
    names = [r['name'] for r in ts.current()['buildings'][0]['rooms']]
    check(names[0] == 'Sitting', names)
    check(names[2] and names[2] not in ('Kitchen', 'Garage'), f'a blank room is not handed an unrelated HA area: {names}')
    check(len(names) == len(set(names)), f'names are unique: {names}')


def scenario_an_unusable_building_stops_before_paying_for_more():
    drawing, plot, photo = _fresh()
    m = Model({'building': {'buildings': []}})
    result, notes, err = _run(m, drawings=[{'id': drawing, 'pages': [1]}], photos=[photo], site={'id': plot, 'pages': [1]})
    check(result is None and err and 'building' in err.lower(), err)
    check([c['stage'] for c in m.calls] == ['building'], 'finishes and site are never paid for')


def scenario_odd_shapes_in_a_paid_answer_do_not_crash_the_draft():
    drawing, plot, photo = _fresh()
    f = _fixture()
    f['buildings'][0]['porch']['polygon'] = [{'x': 31, 'y': 0}, {'x': 38, 'y': 0}, {'x': 38, 'y': 22}]
    site = {k: f['site'][k] for k in ('lot', 'hardscape', 'fire_pit')}
    site['pool'] = {'polygon': 'abc'}
    m = Model({'building': {'buildings': f['buildings']}, 'site': {'site': site}})
    result, notes, err = _run(m, drawings=[{'id': drawing, 'pages': [1]}], photos=[photo], site={'id': plot, 'pages': [1]})
    check(err is None and result, err)
    check(any('porch' in n for n in notes) and any('pool' in n for n in notes), notes)


def scenario_requests_over_the_size_budget_are_refused_before_paying():
    drawing, plot, photo = _fresh()
    m = Model()
    orig = td.MAX_REQUEST_B64
    td.MAX_REQUEST_B64 = 100
    try:
        result, notes, err = _run(m, drawings=[{'id': drawing, 'pages': [1]}], photos=[photo], site={'id': plot, 'pages': [1]})
    finally:
        td.MAX_REQUEST_B64 = orig
    check(result is None and err and m.calls == [], (err, len(m.calls)))
    check(td.MAX_REQUEST_B64 <= 18 * 1024 * 1024, td.MAX_REQUEST_B64)


def scenario_a_stopped_draft_resumes_without_its_run_id():
    drawing, plot, photo = _fresh()
    tc.record('earlier', [{'model': PRICED, 'input_tokens': 999_000, 'output_tokens': 0,
                           'images': 0, 'prompt_chars': 0, 'max_output_tokens': 0}])
    m = Model(tokens=2000)
    kw = dict(drawings=[{'id': drawing, 'pages': [1]}], photos=[photo], site={'id': plot, 'pages': [1]})
    try:
        _run(m, **kw)
    except tc.CheckpointReached:
        pass
    tc.acknowledge(10.0)
    result, notes, err = _run(m, **kw)                     # same inputs, no run id
    check(err is None, err)
    check([c['stage'] for c in m.calls] == ['building', 'finishes', 'site'], [c['stage'] for c in m.calls])


def scenario_no_key_is_an_error_not_a_call():
    drawing, plot, photo = _fresh(key=False)
    m = Model()
    result, notes, err = _run(m, drawings=[{'id': drawing, 'pages': [1]}], photos=[photo], site={'id': plot, 'pages': [1]})
    check(result is None and err and m.calls == [], (err, m.calls))


def scenario_unknown_sources_are_refused():
    _fresh()
    m = Model()
    result, notes, err = _run(m, drawings=[{'id': 'nope', 'pages': [1]}], photos=[], site=None)
    check(result is None and err and m.calls == [], 'an unknown source id is an error before any model call')


def scenario_draft_route_and_tier():
    from services import auth
    check(auth.resolve('POST', '/api/house/twin/draft') == auth.PARENTS, 'parents only')
    check(model_pools.TIER_CHAINS['twin'] == ['pro'], model_pools.TIER_CHAINS.get('twin'))


if __name__ == '__main__':
    for fn in (scenario_three_stages_build_one_round,
               scenario_a_partial_model_answer_still_drafts,
               scenario_finishes_outside_the_kit_are_replaced,
               scenario_checkpoint_stops_before_the_next_stage,
               scenario_rooms_are_named_with_or_without_ha,
               scenario_stages_get_real_timeouts_and_their_own_images,
               scenario_stages_with_nothing_to_read_are_skipped,
               scenario_blank_rooms_get_descriptive_names_not_random_ha_areas,
               scenario_an_unusable_building_stops_before_paying_for_more,
               scenario_odd_shapes_in_a_paid_answer_do_not_crash_the_draft,
               scenario_requests_over_the_size_budget_are_refused_before_paying,
               scenario_a_stopped_draft_resumes_without_its_run_id,
               scenario_no_key_is_an_error_not_a_call,
               scenario_unknown_sources_are_refused,
               scenario_draft_route_and_tier):
        fn()
        print('  ok ', fn.__name__)
