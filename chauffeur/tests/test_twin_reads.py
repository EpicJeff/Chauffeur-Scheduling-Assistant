"""Step reads for the house editor (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md section 7.2; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 7): one small,
metered model request per step on a cropped image, returning a validated
fragment in crop-normalised coordinates. The model is stubbed at
model_pools.call_pool_json; the fixtures under tests/fixtures/twin_reads/ are
hand-written from Reference Plans Lot 58 in each contract's exact shape.

Run from chauffeur/:  python tests/test_twin_reads.py
"""
import copy
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_reads_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import model_pools, storage  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_reads  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads')
PRICED = next(iter(tc.PRICES))


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


def fixture(kind):
    with open(os.path.join(FIXTURES, f'{kind}.json'), encoding='utf-8') as f:
        return json.load(f)


def img():
    return {'mime': 'image/png', 'b64': 'iVBORw0KGgo='}


def _fresh(key=True):
    storage.patch_settings({'house_twin_cost': None, 'llm_provider': 'gemini',
                            'llm_gemini_paid_api_key': 'paid-k' if key else ''})


class Pool:
    """Stands in for call_pool_json; records every call and reports usage."""

    def __init__(self, answer=None, raises=None):
        self.answer, self.raises, self.calls = answer, raises, []

    def __call__(self, tier, api_key, system_prompt, user_prompt, **kw):
        self.calls.append({'tier': tier, 'system': system_prompt, 'user': user_prompt, **kw})
        if kw.get('usage') is not None:
            kw['usage'].append({'model': PRICED, 'input_tokens': 1500, 'output_tokens': 300,
                                'images': len(kw.get('images') or []), 'prompt_chars': len(user_prompt),
                                'max_output_tokens': kw.get('max_output_tokens') or 0})
        if self.raises:
            raise self.raises
        return copy.deepcopy(self.answer)

    def __enter__(self):
        self.original = model_pools.call_pool_json
        model_pools.call_pool_json = self
        return self

    def __exit__(self, *exc):
        model_pools.call_pool_json = self.original
        return False


def scenario_kinds_and_output_caps_are_pinned():
    check(twin_reads.KINDS == ('sheet_roles', 'outline', 'walls', 'openings', 'rooms', 'registration', 'roof',
                               'pitch', 'plot', 'site', 'finishes', 'photo_parts'), twin_reads.KINDS)
    check(twin_reads.MAX_OUTPUT == {'sheet_roles': 2048, 'outline': 4096, 'walls': 16384, 'openings': 16384,
                                    'rooms': 8192, 'registration': 4096, 'roof': 8192, 'pitch': 2048,
                                    'plot': 8192, 'site': 8192, 'finishes': 8192, 'photo_parts': 2048}, twin_reads.MAX_OUTPUT)


def scenario_each_kind_parses_its_fixture():
    for kind in twin_reads.KINDS:
        frag, problems = twin_reads.parse(kind, fixture(kind))
        check(frag and problems == [], (kind, problems))
        check(frag == fixture(kind) or kind in ('outline', 'registration', 'roof', 'plot'),
              f'{kind}: a clean answer passes through unchanged apart from documented defaults')


def scenario_out_of_range_points_are_named_not_kept():
    frag, problems = twin_reads.parse('walls', {'walls': [{'from': [0.1, 0.1], 'to': [1.4, 0.1], 'exterior': True},
                                                          {'from': [0.1, 0.1], 'to': [0.9, 0.1], 'exterior': True}]})
    check(len(frag['walls']) == 1 and any('outside' in p for p in problems), (frag, problems))
    frag, problems = twin_reads.parse('outline', {**fixture('outline'), 'outline': [[0.1, 0.1], [0.2, 0.1]]})
    check(any('outline' in p for p in problems), problems)


def scenario_wrong_shapes_are_problems_not_crashes():
    for kind, bad in (('walls', {'walls': 'none'}), ('openings', None), ('roof', {'sections': [{'kind': 'dome'}]}),
                      ('pitch', {'pitches': [{'section': 'roof-1', 'pitch': 'steep'}]}),
                      ('outline', {'dimension': {'a': [0, 0], 'b': [0, 0], 'feet': 70}}),
                      ('finishes', {'materials': {'roof': {'id': 3}}})):
        frag, problems = twin_reads.parse(kind, bad)
        check(problems, (kind, frag))


def scenario_read_is_one_metered_request():
    _fresh()
    with Pool(answer=fixture('outline')) as pool:
        frag = twin_reads.read('outline', [img()], {'level': 'Main floor'}, run='r1', step='outline:L1')
    check(frag.get('outline') and 'error' not in frag, frag)
    c = pool.calls
    check(len(c) == 1 and c[0]['tier'] == 'twin' and c[0]['max_models'] == 1 and c[0]['max_output_tokens'] == 4096,
          c)
    check(c[0]['strict_json'] is True and c[0]['thinking_level'] == 'low' and c[0]['timeout_s'] == 120, c)
    check(len(c[0]['images']) == 1, 'the crop is the only image')
    e = tc.entries()[-1]
    check(e['stage'] == 'step:outline' and e['run'] == 'r1', e)


def scenario_failure_is_recorded_and_returned():
    _fresh()
    with Pool(raises=RuntimeError('boom')):
        out = twin_reads.read('walls', [img()], {}, run='r1', step='walls:L1:main')
    check('error' in out and 'boom' in out['error'], out)
    check(tc.entries()[-1]['stage'] == 'step:walls', 'charged even on failure')


def scenario_unparseable_answer_is_an_error_with_cost():
    _fresh()
    with Pool(answer={'nonsense': True}):
        out = twin_reads.read('roof', [img()], {}, run='r1', step='roof')
    check('error' in out, out)
    check(tc.entries()[-1]['stage'] == 'step:roof', 'spent and recorded')


def scenario_checkpoint_propagates_before_spend():
    _fresh()
    tc.record('step:walls', [{'model': PRICED, 'input_tokens': 10_000_000, 'output_tokens': 10_000_000,
                              'images': 0, 'prompt_chars': 0, 'max_output_tokens': 0}])
    check(tc.blocking_checkpoint() is not None, 'a checkpoint is due')
    with Pool(answer=fixture('walls')) as pool:
        try:
            twin_reads.read('walls', [img()], {}, run='r', step='s')
        except tc.CheckpointReached:
            pass
        else:
            raise AssertionError('a due checkpoint must stop the read')
    check(pool.calls == [], 'no request made')


def scenario_no_key_no_spend():
    _fresh(key=False)
    with Pool(answer=fixture('walls')) as pool:
        out = twin_reads.read('walls', [img()], {}, run='r', step='s')
    check('error' in out and pool.calls == [] and tc.entries() == [], (out, pool.calls))


def scenario_finishes_prompt_moved_from_p0():
    from services import twin_draft
    check(twin_reads.PROMPTS['finishes'] == twin_draft.FINISHES_PROMPT, 'one finishes prompt, shared')


def scenario_a_partial_read_reports_its_problems():
    # Review finding: dropped items must not vanish silently; the engine turns them into ghost reasons.
    _fresh()
    answer = {'walls': [{'from': [0.1, 0.1], 'to': [1.4, 0.1], 'exterior': True},
                        {'from': [0.1, 0.1], 'to': [0.9, 0.1], 'exterior': True}]}
    with Pool(answer=answer):
        out = twin_reads.read('walls', [img()], {}, run='r1', step='walls:L1:main')
    check(len(out['walls']) == 1 and any('outside' in p for p in out['problems']), out)
    with Pool(answer=fixture('walls')):
        out = twin_reads.read('walls', [img()], {}, run='r1', step='walls:L1:main')
    check('problems' not in out, 'a clean read carries no problems key')


def scenario_checkpoint_inside_the_pool_call_is_recorded_once():
    _fresh()
    before = len(tc.entries())
    with Pool(raises=tc.CheckpointReached(10.0, 10.2)):
        try:
            twin_reads.read('walls', [img()], {}, run='r', step='s')
        except tc.CheckpointReached:
            pass
        else:
            raise AssertionError('must propagate')
    check(len(tc.entries()) == before + 1, 'the request that crossed it is still recorded once')


def scenario_lot_on_the_crop_border_keeps_its_street_edge():
    frag, problems = twin_reads.parse('plot', {**fixture('plot'),
                                              'lot': [[0.0, 0.0], [1.03, 0.0], [1.03, 1.0], [0.0, 1.0]],
                                              'street_edge': [1, 2]})
    check(frag.get('street_edge') == [1, 2], (frag, problems))


def scenario_prompts_define_the_terms_models_get_wrong():
    p = twin_reads.PROMPTS
    for kind in ('outline', 'registration', 'plot'):
        check('dimension line' in p[kind] or 'scale' in p[kind], kind)
    check("70'-0\"" in p['outline'] and 'endpoints' in p['outline'], 'architect notation and endpoints')
    check('dashed' in p['outline'] and 'dashed' in p['registration'], 'dashed lines are another floor')
    check('bounding box' in p['outline'], 'a wing box is a tight bounding box')
    check('runs along' in p['roof'] and 'low_side' in p['roof'] and 'slopes down' in p['roof'], 'ridge and shed terms')
    check('street' in p['plot'] and 'adjacent' in p['plot'], 'street_edge is two adjacent lot indices')


def scenario_sheet_roles_elsewhere():
    # Slice 1b-i Task 2: page roles cover both a building's and the lot's
    # pages, and a page may name another listed part it clearly shows.
    page = {'page': 1, 'role': 'survey', 'level': None, 'box': None, 'elsewhere': 'garage'}
    frag, problems = twin_reads.parse('sheet_roles', {'pages': [page]})
    check(problems == [] and frag['pages'] == [page], (frag, problems))
    check(frag['pages'][0]['role'] == 'survey' and frag['pages'][0]['elsewhere'] == 'garage', frag)
    frag, problems = twin_reads.parse('sheet_roles', {'pages': [{**page, 'elsewhere': None}]})
    check(problems == [] and frag['pages'] == [{k: v for k, v in page.items() if k != 'elsewhere'}],
          ('null elsewhere is absent, with no problem or output key', frag, problems))
    for role in ('floor', 'roof', 'plot', 'survey', 'landscape', 'elevation', 'other'):
        frag, problems = twin_reads.parse('sheet_roles', {'pages': [{'page': 1, 'role': role, 'level': None,
                                                                     'box': None}]})
        check(problems == [] and frag['pages'][0]['role'] == role and 'elsewhere' not in frag['pages'][0],
              (role, frag, problems))
    for role in ('skip', 'attic'):
        frag, problems = twin_reads.parse('sheet_roles', {'pages': [{'page': 1, 'role': role, 'level': None,
                                                                     'box': None}]})
        check(problems and frag['pages'] == [], ("skip is the person's choice, never the model's", role, frag))
    # A non-text elsewhere is a problem that drops only that field.
    frag, problems = twin_reads.parse('sheet_roles', {'pages': [
        {'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'elsewhere': 7},
        {'page': 2, 'role': 'landscape', 'level': None, 'box': None, 'elsewhere': 'lot'}]})
    check(frag['pages'] == [{'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None},
                            {'page': 2, 'role': 'landscape', 'level': None, 'box': None, 'elsewhere': 'lot'}],
          (frag, problems))
    check(len(problems) == 1 and 'elsewhere' in problems[0], problems)
    prompt = twin_reads.PROMPTS['sheet_roles']
    for word in ('survey', 'landscape', 'elsewhere'):
        check(word in prompt, ('the sheet_roles prompt names', word))


if __name__ == '__main__':
    for fn in (scenario_kinds_and_output_caps_are_pinned,
               scenario_each_kind_parses_its_fixture,
               scenario_out_of_range_points_are_named_not_kept,
               scenario_wrong_shapes_are_problems_not_crashes,
               scenario_read_is_one_metered_request,
               scenario_failure_is_recorded_and_returned,
               scenario_unparseable_answer_is_an_error_with_cost,
               scenario_checkpoint_propagates_before_spend,
               scenario_no_key_no_spend,
               scenario_finishes_prompt_moved_from_p0,
               scenario_a_partial_read_reports_its_problems,
               scenario_checkpoint_inside_the_pool_call_is_recorded_once,
               scenario_lot_on_the_crop_border_keeps_its_street_edge,
               scenario_prompts_define_the_terms_models_get_wrong,
               scenario_sheet_roles_elsewhere):
        fn()
        print('  ok ', fn.__name__)
