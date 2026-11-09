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


STEP_KINDS = ('sheet_roles', 'outline', 'walls', 'openings', 'rooms', 'registration', 'roof',
              'pitch', 'plot', 'site', 'finishes', 'photo_parts')
DRAFT_KINDS = ('draft', 'draft_level', 'draft_rooms')


def scenario_kinds_and_output_caps_are_pinned():
    # Whole-building draft task 5: the three draft kinds join the step kinds.
    check(twin_reads.KINDS == STEP_KINDS + DRAFT_KINDS + ('roof_check',), twin_reads.KINDS)
    check(twin_reads.MAX_OUTPUT == {'sheet_roles': 2048, 'outline': 4096, 'walls': 16384, 'openings': 16384,
                                    'rooms': 16384, 'registration': 4096, 'roof': 8192, 'pitch': 2048,
                                    'plot': 8192, 'site': 8192, 'finishes': 8192, 'photo_parts': 2048,
                                    'draft': 64000, 'draft_level': 32000, 'draft_rooms': 32000, 'roof_check': 16000},
          twin_reads.MAX_OUTPUT)


def scenario_each_kind_parses_its_fixture():
    # The draft kinds have no crop fixture; test_parse_draft_shape covers them.
    for kind in STEP_KINDS:
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


# ---- repair after the first live build (repair-brief.md R2a, R5a) ----

TRUNCATED = {'error': 'Incomplete Claude JSON response (finish=max_tokens; output_tokens=16384; limit=16384)',
             'transient': False}       # what call_pool_json returned for the reproduction's rooms read


class SeqPool(Pool):
    """A Pool that answers each call in turn from a list."""

    def __init__(self, answers):
        super().__init__()
        self.answers = list(answers)

    def __call__(self, tier, api_key, system_prompt, user_prompt, **kw):
        self.answer = self.answers[min(len(self.calls), len(self.answers) - 1)]
        return super().__call__(tier, api_key, system_prompt, user_prompt, **kw)


def scenario_rooms_output_cap_is_16384():
    check(twin_reads.MAX_OUTPUT['rooms'] == 16384, twin_reads.MAX_OUTPUT)


def scenario_a_truncated_read_is_retried_once_at_twice_the_limit():
    _fresh()
    before = len(tc.entries())
    with SeqPool([TRUNCATED, fixture('rooms')]) as pool:
        out = twin_reads.read('rooms', [img()], {'level': 'L1'}, run='r1', step='rooms:L1')
    check('error' not in out and out.get('rooms'), ('the second read answers', out))
    limits = [c['max_output_tokens'] for c in pool.calls]
    check(len(pool.calls) == 2 and limits == [twin_reads.MAX_OUTPUT['rooms'], 2 * twin_reads.MAX_OUTPUT['rooms']],
          ('retried once, at twice the limit', limits))
    added = tc.entries()[before:]
    check(len(added) == 2 and all(e['stage'] == 'step:rooms' and e['run'] == 'r1' for e in added),
          ('both requests are metered', added))
    # Gemini says it with its own finish reason.
    gemini = {'error': 'Gemini request failed: Incomplete Gemini JSON response (finish=MAX_TOKENS; '
                       'output_tokens=16384; thinking_tokens=0; limit=16384)'}
    with SeqPool([gemini, fixture('walls')]) as pool:
        out = twin_reads.read('walls', [img()], {}, run='r1', step='walls:L1:main')
    check('error' not in out and [c['max_output_tokens'] for c in pool.calls] == [16384, 32768],
          (out, [c['max_output_tokens'] for c in pool.calls]))


def scenario_a_second_truncation_stops_and_other_failures_are_not_retried():
    _fresh()
    with SeqPool([TRUNCATED, TRUNCATED, fixture('rooms')]) as pool:
        out = twin_reads.read('rooms', [img()], {}, run='r1', step='rooms:L1')
    check('error' in out and len(pool.calls) == 2, ('one retry only, then the build stops', out, len(pool.calls)))
    with SeqPool([{'error': '429 Too Many Requests: slow down'}, fixture('rooms')]) as pool:
        out = twin_reads.read('rooms', [img()], {}, run='r1', step='rooms:L1')
    check('error' in out and len(pool.calls) == 1, ('only a cut-off answer is retried', out, len(pool.calls)))
    with SeqPool([{'nonsense': True}, fixture('roof')]) as pool:
        out = twin_reads.read('roof', [img()], {}, run='r1', step='roof')
    check('error' in out and len(pool.calls) == 1, ('a complete but useless answer is not retried', len(pool.calls)))


def scenario_footprint_prompts_agree_on_enclosed_walls():
    # R2a: the outline, the registration's lower_outline and the roof all trace
    # the enclosed walls; open porches and decks stay out (as wings at most).
    for kind in ('outline', 'registration', 'roof'):
        prompt = twin_reads.PROMPTS[kind].lower()
        for words in ('enclosed walls', 'porch', 'deck'):
            check(words in prompt, (kind, 'names', words))
    check('lower_outline' in twin_reads.PROMPTS['registration'], 'the registration names lower_outline')


# ---- whole-building draft, task 5 (task-5-brief.md) ----
#
# Lenient JSON is driven through llm._call_llm_json with the provider HTTP
# layer (llm_budget.urlopen) stubbed by a canned Anthropic body, so the
# stop_reason completion check runs for real.

import io  # noqa: E402

from services import llm  # noqa: E402

RECORDED = os.path.join(FIXTURES, 'recorded', 'claude')
DRAFT_TRUNCATED = {'error': 'Incomplete Claude JSON response (finish=max_tokens; output_tokens=64000; limit=64000)',
                   'transient': False}


def spike_answer():
    with open(os.path.join(RECORDED, 'draft-main-spike-answer.json'), encoding='utf-8') as f:
        return json.load(f)


class _Body(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ClaudeStub:
    """Stands in for llm_budget.urlopen with one Anthropic Messages reply."""

    def __init__(self, text, stop_reason='end_turn'):
        self.body = {'content': [{'type': 'text', 'text': text}], 'stop_reason': stop_reason,
                     'usage': {'input_tokens': 100, 'output_tokens': 20}}
        self.requests = []

    def __call__(self, request, timeout=60):
        self.requests.append(request)
        return _Body(json.dumps(self.body).encode('utf-8'))

    def __enter__(self):
        self.original = llm.llm_budget.urlopen
        llm.llm_budget.urlopen = self
        return self

    def __exit__(self, *exc):
        llm.llm_budget.urlopen = self.original
        return False


def _claude_json(text, strict_json='lenient', stop_reason='end_turn'):
    with ClaudeStub(text, stop_reason) as stub:
        out = llm._call_llm_json('anthropic', '', 'k', 'claude-opus-5-5', 'sys', 'user',
                                 strict_json=strict_json, transient_retries=0, max_output_tokens=64000)
    check(len(stub.requests) == 1, 'one provider request')
    return out


def _raises(fn, *words):
    try:
        out = fn()
    except RuntimeError as exc:
        for word in words:
            check(word in str(exc), (word, str(exc)[:300]))
        return
    raise AssertionError(f'expected a RuntimeError, got {out!r}')


def test_lenient_fences_and_lead_text():
    out = _claude_json('Here:\n```json\n{"a":1}\n```')
    check(out == {'a': 1}, out)


def test_lenient_trailing_brace():
    out = _claude_json('{"a":1}}')
    check(out == {'a': 1}, out)
    # Strict JSON is unchanged: it never repairs anything.
    _raises(lambda: _claude_json('{"a":1}}', strict_json=True))


def test_lenient_two_objects_refused():
    _raises(lambda: _claude_json('{"a":1}{"b":2}'), 'Two JSON objects in one reply')


def test_lenient_keeps_truncation_check():
    # A complete-looking object cut off at max_tokens is still a truncated reply.
    _raises(lambda: _claude_json('{"a":1}', stop_reason='max_tokens'),
            'Incomplete Claude JSON response', 'max_tokens')


def test_draft_call_settings():
    _fresh()
    with Pool(answer=spike_answer()) as pool:
        twin_reads.read('draft', [img(), img()], {'building': 'Main house'}, run='r1', step='draft')
    check(len(pool.calls) == 1, ('one request', len(pool.calls)))
    c = pool.calls[0]
    check(c['tier'] == 'twin' and c['system'] == twin_reads.PROMPTS['draft'], (c['tier'], c['system'][:80]))
    check(c['thinking_level'] == 'medium' and c['max_output_tokens'] == 64000 and c['timeout_s'] == 420
          and c['strict_json'] == 'lenient' and c['max_models'] == 1,
          {k: c.get(k) for k in ('thinking_level', 'max_output_tokens', 'timeout_s', 'strict_json', 'max_models')})
    check(len(c['images']) == 2, 'every page image goes in the one request')
    for kind in ('draft_level', 'draft_rooms'):
        with Pool(answer={}) as pool:
            twin_reads.read(kind, [img()], {}, run='r1', step=kind)
        c = pool.calls[0]
        check(len(pool.calls) == 1 and c['thinking_level'] == 'medium' and c['max_output_tokens'] == 32000
              and c['timeout_s'] == 300 and c['strict_json'] == 'lenient' and c['max_models'] == 1,
              (kind, {k: c.get(k) for k in ('thinking_level', 'max_output_tokens', 'timeout_s', 'strict_json')}))
    check(twin_reads.THINKING == {'draft': 'medium', 'draft_level': 'medium', 'draft_rooms': 'medium', 'roof_check': 'medium'},
          twin_reads.THINKING)
    check(twin_reads.TIMEOUT == {'draft': 420, 'draft_level': 300, 'draft_rooms': 300, 'roof_check': 240}, twin_reads.TIMEOUT)
    with Pool(answer=fixture('outline')) as pool:
        twin_reads.read('outline', [img()], {'level': 'Main floor'}, run='r1', step='outline:L1')
    c = pool.calls[0]
    check(c['thinking_level'] == 'low' and c['timeout_s'] == 120 and c['strict_json'] is True, c)


def test_draft_truncated_no_retry():
    _fresh()
    before = len(tc.entries())
    with SeqPool([DRAFT_TRUNCATED, spike_answer()]) as pool:
        out = twin_reads.read('draft', [img()], {}, run='r1', step='draft')
    check(len(pool.calls) == 1, ('64k is the ceiling: no doubled retry', len(pool.calls)))
    check(out.get('truncated') is True and 'error' in out, out)
    check(len(tc.entries()) == before + 1 and tc.entries()[-1]['stage'] == 'step:draft', 'metered once')
    for kind in ('draft_level', 'draft_rooms'):
        with SeqPool([DRAFT_TRUNCATED, {}]) as pool:
            out = twin_reads.read(kind, [img()], {}, run='r1', step=kind)
        check(len(pool.calls) == 1 and 'error' in out, (kind, len(pool.calls), out))


def test_draft_prompt_generic():
    prompt = ' '.join(twin_reads.PROMPTS['draft'].split()).lower()
    for words in ('dimension strings', 'stop reasoning by about 45000', 'half', 'anchors',
                  'prefer the reading where walls, floors and roofs meet'):
        check(words in prompt, ('the draft prompt says', words))
    for words in ('upton', 'lot 58', 'pool house'):
        check(words not in prompt, ('the draft prompt carries no household text', words))


def _pages(*anchors_per_page):
    return [{'image': 1, 'level': 'L1', 'anchors': list(anchors)} for anchors in anchors_per_page]


def test_parse_draft_shape():
    answer = spike_answer()
    check('pages' not in answer, 'the recorded spike answer predates the pages request')
    frag, problems = twin_reads.parse('draft', answer)
    check(problems == [], problems[:10])
    b = frag.get('building') or {}
    src = answer['building']
    check(len(b.get('levels') or []) == len(src['levels']) and len(b.get('walls') or []) == len(src['walls'])
          and len(b.get('openings') or []) == len(src['openings']) and b.get('rooms') == [],
          'a clean building passes through with nothing dropped')
    roof = b.get('roof') or {}
    check(len(roof.get('sections') or []) == len(src['roof']['sections'])
          and len(roof.get('extensions') or []) == len(src['roof']['extensions']), roof.keys())
    check(b.get('porch') and len(b.get('stairs') or []) == len(src['stairs']), 'porch and stairs kept')
    # A missing pages key is allowed: no problem, an empty list.
    check(frag.get('pages') == [], frag.get('pages'))

    a1 = {'px': [0.1, 0.2], 'at': [0, 14.33]}
    a2 = {'px': [0.9, 0.8], 'at': [70, 0]}
    good = _pages([a1, a2])
    frag, problems = twin_reads.parse('draft', {**answer, 'pages': copy.deepcopy(good)})
    check(problems == [] and frag['pages'] == good, (problems, frag.get('pages')))

    wide = {'px': [1.4, 0.2], 'at': [10, 10]}
    frag, problems = twin_reads.parse('draft', {**answer, 'pages': _pages([a1, a2, wide])})
    check(any('pages' in p for p in problems), ('an out-of-range u is named', problems))
    kept = [a for page in frag.get('pages') or [] for a in page.get('anchors') or []]
    check(all(a['px'][0] <= 1 for a in kept) and wide not in kept, ('and never kept', kept))

    frag, problems = twin_reads.parse('draft', {**answer, 'pages': _pages([a1], [a1, a2])})
    check(any('anchors' in p for p in problems), ('fewer than 2 anchors is named', problems))
    check(frag.get('pages') == _pages([a1, a2]), ('only the page with two anchors is kept', frag.get('pages')))


def test_parse_draft_level_shape():
    building = spike_answer()['building']
    for level in building['levels']:
        walls = [w for w in building['walls'] if w['level'] == level['id']]
        wall_ids = {w['id'] for w in walls}
        partial = {'levels': [level], 'walls': walls,
                   'openings': [o for o in building['openings'] if o.get('wall') in wall_ids]}
        pages = [{'image': 0, 'level': level['id'], 'anchors': [
            {'px': [.1, .9], 'at': [-2, 0]}, {'px': [.9, .1], 'at': [70, 65]}]}]
        answer = {'building': partial, 'pages': pages}
        saved = copy.deepcopy(answer)
        fragment, problems = twin_reads.parse('draft_level', answer)
        check(problems == [] and fragment == answer, (fragment, problems))
        check(answer == saved, 'parsing never mutates the partial answer')
    # A roof-only reply may reference settled walls outside this reply.
    roof = {'building': {'roof': building['roof'],
                         'openings': [o for o in building['openings'] if 'section' in o]}}
    fragment, problems = twin_reads.parse('draft_level', roof)
    check(problems == [] and fragment['building'] == roof['building'] and fragment['pages'] == [],
          (fragment, problems))
    fragment, problems = twin_reads.parse('draft_level', {'building': building})
    check(fragment['building']['levels'] == [] and any('only one level' in p for p in problems),
          ('a whole building cannot masquerade as one floor', problems))


def test_parse_draft_rooms_shape():
    room = {'name': '', 'level': 'L2', 'polygon': [[-2, 14], [12, 14], [12, 24], [-2, 24]]}
    wall = {'id': 'partition', 'level': 'L2', 'from': [-2, 14], 'to': [12, 14],
            'height': 8, 'thickness': .33, 'exterior': False}
    answer = {'rooms': [room], 'walls': [wall]}
    saved = copy.deepcopy(answer)
    fragment, problems = twin_reads.parse('draft_rooms', answer)
    expected = {**answer, 'rooms': [{**room, 'name': 'Room'}]}
    check(problems == [] and fragment == expected and answer == saved, (fragment, problems))
    for bad in ({**wall, 'exterior': True}, {**wall, 'thickness': float('inf')}):
        fragment, problems = twin_reads.parse('draft_rooms', {'rooms': [room], 'walls': [bad, wall]})
        check(problems and fragment == expected, ('invalid walls leave valid rooms and siblings intact',
                                               fragment, problems))


def test_parse_draft_rooms_without_walls():
    room = {'name': 'Kitchen', 'level': 'L1', 'polygon': [[1, 15], [10, 15], [10, 25], [1, 25]]}
    for rooms in ([room], []):
        answer = {'rooms': copy.deepcopy(rooms)}
        fragment, problems = twin_reads.parse('draft_rooms', answer)
        check(problems == [] and fragment == {'rooms': rooms, 'walls': []}, (fragment, problems))
        check('walls' not in answer, 'the optional default does not mutate the reply')
        check(twin_reads._usable('draft_rooms', fragment, problems), 'a rooms-only answer is usable')
    # Exercise the actual reader too: it must not turn an omitted walls key into an error.
    _fresh()
    with Pool(answer={'rooms': [room]}) as pool:
        result = twin_reads.read('draft_rooms', [img()], {}, run='r1', step='draft_rooms')
    check(result == {'rooms': [room], 'walls': []} and len(pool.calls) == 1, result)


def test_draft_rooms_prompt_scope():
    prompt = twin_reads.PROMPTS['draft_rooms']
    for words in ('PRINTED DIMENSION STRINGS', 'INTERIOR walls', 'knee walls', 'level ids',
                  'thickness is in feet', 'stop reasoning\nby about 20000'):
        check(words in prompt, ('rooms instructions retain', words))
    for words in ('PAGE REGISTRATIONS', 'anchors:', 'checks:', 'GABLE ENDS', 'Exterior walls follow'):
        check(words not in prompt, ('rooms instructions do not request', words))


def test_small_output_cap_skips_to_fallback():
    check(twin_reads.OUTPUT_CAP == {'anthropic': 64000, 'openai': 64000, 'gemini': 65536}, twin_reads.OUTPUT_CAP)
    _fresh()
    saved = dict(twin_reads.OUTPUT_CAP)
    try:
        twin_reads.OUTPUT_CAP.update({prov: 16000 for prov in saved})
        before = len(tc.entries())
        with Pool(answer=spike_answer()) as pool:
            out = twin_reads.read('draft', [img()], {}, run='r1', step='draft')
        check(pool.calls == [] and len(tc.entries()) == before, ('no request below a 32000 cap', pool.calls))
        check(out.get('truncated') is True and 'too small' in str(out.get('error')), out)
        # The per-level fallback still runs, clamped to the provider's cap.
        with Pool(answer={}) as pool:
            twin_reads.read('draft_level', [img()], {}, run='r1', step='draft_level:L1')
        check(len(pool.calls) == 1 and pool.calls[0]['max_output_tokens'] == 16000,
              [c['max_output_tokens'] for c in pool.calls])
        # At exactly 32000 the whole-building read goes ahead, clamped.
        twin_reads.OUTPUT_CAP.update({prov: 32000 for prov in saved})
        with Pool(answer=spike_answer()) as pool:
            twin_reads.read('draft', [img()], {}, run='r1', step='draft')
        check(len(pool.calls) == 1 and pool.calls[0]['max_output_tokens'] == 32000,
              [c['max_output_tokens'] for c in pool.calls])
    finally:
        twin_reads.OUTPUT_CAP.clear()
        twin_reads.OUTPUT_CAP.update(saved)


# --- Task 11 fix 2 (task-11-fixes.md): rooms keep their printed names --------

def test_parse_draft_rooms_blank_name_becomes_room():
    rooms = [{'name': '', 'level': 'L1', 'polygon': [[0, 0], [10, 0], [10, 8], [0, 8]]},
             {'name': 'BEDROOM 2', 'level': 'L2', 'polygon': [[0, 0], [12, 0], [12, 11], [0, 11]]},
             {'name': 'KITCHEN', 'level': 'L1', 'polygon': [[10, 0], [20, 0], [20, 8], [10, 8]]}]
    answer = {'rooms': copy.deepcopy(rooms), 'walls': []}
    saved = copy.deepcopy(answer)
    fragment, problems = twin_reads.parse('draft_rooms', answer)
    check(problems == [], ('a blank room name is not a problem', problems))
    check([r['name'] for r in fragment['rooms']] == ['Room', 'BEDROOM 2', 'KITCHEN'],
          ('a blank name becomes "Room"; a printed name is kept as printed', [r['name'] for r in fragment['rooms']]))
    check([r['polygon'] for r in fragment['rooms']] == [r['polygon'] for r in rooms], 'the polygons are kept')
    check(answer == saved, 'parse does not mutate the reply')
    # The household's recorded answer came back with every name blank.
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded',
                        'claude', 'draft_rooms-main-house.json')
    with open(path, encoding='utf-8') as f:
        recorded = json.load(f)
    check(recorded['rooms'] and all(r['name'] == '' for r in recorded['rooms']),
          'test setup: the recorded main-house rooms are all unnamed')
    fragment, problems = twin_reads.parse('draft_rooms', recorded)
    check(len(fragment['rooms']) == len(recorded['rooms']) and all(r['name'] == 'Room' for r in fragment['rooms']),
          ('every recorded blank name becomes "Room"', sorted({r['name'] for r in fragment['rooms']})))


def test_draft_rooms_prompt_asks_names_as_printed():
    prompt = twin_reads.PROMPTS['draft_rooms']
    check('as printed' in prompt, 'the rooms prompt asks for each room name as printed on the plan')
    check('"Room"' in prompt, 'the rooms prompt names "Room" for a room with nothing printed')
    check('leave an unreadable name blank' not in prompt, 'the rooms prompt no longer asks for blank names')


# --- Task 12: the roof check (brief .superpowers/sdd/2026-11-08-house-editor-
# whole-building-draft/task-12-brief.md). A read after the draft that answers
# corrections only: {"changes":[{id, kind?, ridge?, low_side?, pitch?, plate?,
# rect?}], "add":[<full section>], "remove":[<id>], "notes":[...]}. The read
# sections it may name go in context["sections"].

ROOF_CHECK_SECTIONS = [
    {'id': 'r_left', 'kind': 'gable', 'ridge': 'x', 'low_side': None, 'rect': [0, 14.33, 14.33, 54],
     'plate': 10, 'pitch': 8, 'overhang': 1},
    {'id': 'r_main', 'kind': 'gable', 'ridge': 'y', 'low_side': None, 'rect': [14.33, 13.33, 37.33, 52],
     'plate': 20, 'pitch': 10, 'overhang': 1},
    {'id': 'r_bkfst', 'kind': 'shed', 'ridge': None, 'low_side': 'y1', 'rect': [31, 48, 43.33, 59],
     'plate': 10, 'pitch': 4, 'overhang': 1}]
ROOF_CHECK_DORMER = {'id': 'r_dormer', 'kind': 'gable', 'ridge': 'y', 'rect': [22.67, 13.33, 37.33, 26],
                     'plate': 20, 'pitch': 12, 'overhang': 1}
ROOF_CHECK_EMPTY = {'changes': [], 'add': [], 'remove': [], 'notes': []}


def _roof_check_context():
    return {'building': {'name': 'Main house'}, 'sections': copy.deepcopy(ROOF_CHECK_SECTIONS),
            'levels': [{'id': 'L1', 'elevation': 0, 'outline': [[0, 14.33], [70, 22], [59, 65.33], [0, 54]]},
                       {'id': 'L2', 'elevation': 11, 'outline': [[14.33, 14.33], [37, 13.33], [37, 52], [14.33, 52]]}]}


def test_roof_check_call_settings():
    check('roof_check' in twin_reads.KINDS, twin_reads.KINDS)
    check(twin_reads.MAX_OUTPUT.get('roof_check') == 16000, twin_reads.MAX_OUTPUT.get('roof_check'))
    check(twin_reads.THINKING.get('roof_check') == 'medium', twin_reads.THINKING)
    check(twin_reads.TIMEOUT.get('roof_check') == 240, twin_reads.TIMEOUT)
    check(tc.IMAGE_TOKENS.get('roof_check') == tc.IMAGE_TOKENS['draft'],
          ('the roof check is estimated with the draft image token count', tc.IMAGE_TOKENS))
    check(tc.estimate('roof_check', 3) > tc.estimate('roof_check', 0) > 0, 'the roof check has an estimate')
    _fresh()
    with Pool(answer=copy.deepcopy(ROOF_CHECK_EMPTY)) as pool:
        out = twin_reads.read('roof_check', [img(), img()], _roof_check_context(), run='r1', step='draft')
    check(len(pool.calls) == 1, ('one request', len(pool.calls)))
    c = pool.calls[0]
    check(c['tier'] == 'twin' and c['system'] == twin_reads.PROMPTS['roof_check'], (c['tier'], c['system'][:80]))
    check(c['thinking_level'] == 'medium' and c['max_output_tokens'] == 16000 and c['timeout_s'] == 240
          and c['strict_json'] == 'lenient' and c['max_models'] == 1,
          {k: c.get(k) for k in ('thinking_level', 'max_output_tokens', 'timeout_s', 'strict_json', 'max_models')})
    check(len(c['images']) == 2, 'every image goes in the one request')
    check('error' not in out, ('an answer with nothing to correct is a good answer', out))
    # No doubled retry: a truncated roof check is one metered request and an error.
    before = len(tc.entries())
    with SeqPool([DRAFT_TRUNCATED, copy.deepcopy(ROOF_CHECK_EMPTY)]) as pool:
        out = twin_reads.read('roof_check', [img()], _roof_check_context(), run='r1', step='draft')
    check(len(pool.calls) == 1 and 'error' in out, ('no doubled retry', len(pool.calls), out))
    check(len(tc.entries()) == before + 1 and tc.entries()[-1]['stage'] == 'step:roof_check', 'metered once')


def test_roof_check_prompt_generic():
    prompt = ' '.join(twin_reads.PROMPTS['roof_check'].split()).lower()
    for words in ('hip', 'gable', 'ridge', 'dormer', 'cross gable', 'never simplify a hip to a gable',
                  '"changes"', '"add"', '"remove"', '"notes"'):
        check(words in prompt, ('the roof check prompt says', words))
    for words in ('upton', 'lot 58', 'pool house', 'main house', 'r_main'):
        check(words not in prompt, ('the roof check prompt carries no household text', words))


def test_parse_roof_check_shapes():
    answer = {'changes': [{'id': 'r_main', 'kind': 'hip', 'ridge': 'x'},
                          {'id': 'r_left', 'pitch': 10, 'plate': 10.5, 'rect': [0, 14.33, 14.33, 54]},
                          {'id': 'r_bkfst', 'low_side': 'y0'}],
              'add': [copy.deepcopy(ROOF_CHECK_DORMER)],
              'remove': ['r_left'],
              'notes': ['The centre block is a hip with a front gable dormer.']}
    frag, problems = twin_reads.parse('roof_check', copy.deepcopy(answer))
    check(problems == [], problems)
    for key in ('changes', 'add', 'remove', 'notes'):
        check(frag.get(key) == answer[key], (key, 'a clean answer passes through unchanged', frag.get(key)))

    bad = {'changes': [{'kind': 'hip', 'ridge': 'x'},                        # no id
                       {'id': 'r_main', 'kind': 'mansard'},                  # unknown kind
                       {'id': 'r_left', 'ridge': 'z'},                       # unknown ridge
                       {'id': 'r_bkfst', 'rect': [40, 50, 30, 45]},          # no size
                       'r_main'],                                            # not an object
           'add': [{'id': 'r_a', 'kind': 'gable', 'rect': [0, 0, 10, 10], 'plate': 10, 'pitch': 8,
                    'overhang': 1},                                          # a gable needs a ridge
                   {'id': 'r_b', 'kind': 'hip', 'ridge': 'x', 'plate': 10, 'pitch': 8, 'overhang': 1},   # no rect
                   copy.deepcopy(ROOF_CHECK_DORMER)],
           'remove': [7, 'r_left'],
           'notes': []}
    frag, problems = twin_reads.parse('roof_check', copy.deepcopy(bad))
    for key in ('changes', 'add', 'remove'):
        check(any(key in p for p in problems), (key, 'a bad item is named as a problem', problems))
    changes = frag.get('changes')
    check(isinstance(changes, list), ('the changes list stays a list', frag))
    check(all(isinstance(c, dict) and isinstance(c.get('id'), str) for c in changes),
          ('every kept change is an object naming its section', changes))
    check(not any(c.get('kind') == 'mansard' or c.get('ridge') == 'z' or c.get('rect') == [40, 50, 30, 45]
                  for c in changes), ('an invalid value is never kept', changes))
    check(frag.get('add') == [ROOF_CHECK_DORMER], ('added sections are validated like draft sections', frag.get('add')))
    check(frag.get('remove') == ['r_left'], ('a remove entry that is not an id is dropped', frag.get('remove')))


def test_parse_roof_check_empty_lists_valid():
    for answer in (copy.deepcopy(ROOF_CHECK_EMPTY), {'changes': [], 'add': [], 'remove': []}):
        frag, problems = twin_reads.parse('roof_check', answer)
        check(problems == [], (answer, problems))
        check(frag.get('changes') == [] and frag.get('add') == [] and frag.get('remove') == [],
              ('empty lists mean the roof is right', frag))
    _fresh()
    with Pool(answer=copy.deepcopy(ROOF_CHECK_EMPTY)) as pool:
        out = twin_reads.read('roof_check', [img()], _roof_check_context(), run='r1', step='draft')
    check('error' not in out and out.get('changes') == [] and out.get('add') == [] and out.get('remove') == [],
          ('an empty answer is usable, not an error', out))
    check(not out.get('problems'), out.get('problems'))


def test_roof_check_unknown_id_dropped():
    _fresh()
    answer = {'changes': [{'id': 'r_main', 'kind': 'hip', 'ridge': 'x'},
                          {'id': 'r_nowhere', 'kind': 'hip', 'ridge': 'x'}],
              'add': [copy.deepcopy(ROOF_CHECK_DORMER)],
              'remove': ['r_gone', 'r_bkfst'],
              'notes': []}
    with Pool(answer=answer) as pool:
        out = twin_reads.read('roof_check', [img()], _roof_check_context(), run='r1', step='draft')
    check('error' not in out, out)
    check(out.get('changes') == [{'id': 'r_main', 'kind': 'hip', 'ridge': 'x'}],
          ('a change naming a section the check was not given is dropped', out.get('changes')))
    check(out.get('remove') == ['r_bkfst'], ('a removal naming an unknown section is dropped', out.get('remove')))
    check(out.get('add') == [ROOF_CHECK_DORMER], ('added sections are kept', out.get('add')))
    problems = out.get('problems') or []
    check(any('r_nowhere' in p for p in problems) and any('r_gone' in p for p in problems),
          ('each dropped id is named as a problem', problems))


# ---- R35: retry malformed draft JSON once, at the same output size ----

MALFORMED_DRAFT = {'error': "Failed to parse LLM JSON: Expecting ',' delimiter: line 1 column 3153"}


def test_draft_parse_failure_retries_once_and_meters_both_attempts():
    answers = {'draft': spike_answer(),
               'draft_level': {'building': {'roof': spike_answer()['building']['roof']}},
               'draft_rooms': {'rooms': []}, 'roof_check': ROOF_CHECK_EMPTY}
    for kind, valid in answers.items():
        for error in (MALFORMED_DRAFT, {'error': 'Two JSON objects in one reply'}):
            _fresh()
            with SeqPool([error, valid]) as pool:
                out = twin_reads.read(kind, [img()], {}, run='r35', step=kind)
            check('error' not in out, (kind, out))
            check(len(pool.calls) == 2, (kind, len(pool.calls)))
            check([c['max_output_tokens'] for c in pool.calls] == [twin_reads.MAX_OUTPUT[kind]] * 2,
                  ('parse retries keep the output size', kind, pool.calls))
            entries = tc.entries()
            check(len(entries) == 2 and all(e['stage'] == f'step:{kind}' and e['run'] == 'r35'
                                           for e in entries), ('both attempts are charged', entries))


def test_draft_two_parse_failures_stop_after_two_attempts():
    _fresh()
    second = {'error': 'Two JSON objects in one reply'}
    with SeqPool([MALFORMED_DRAFT, second, spike_answer()]) as pool:
        out = twin_reads.read('draft', [img()], {}, run='r35', step='draft')
    check(out == second and len(pool.calls) == 2, (out, len(pool.calls)))
    check(len(tc.entries()) == 2, ('both failed attempts are charged', tc.entries()))


def test_draft_truncation_and_other_errors_still_stop_after_one_attempt():
    for kind in DRAFT_KINDS + ('roof_check',):
        for error in (DRAFT_TRUNCATED, {**MALFORMED_DRAFT, 'truncated': True},
                      {'error': 'Claude refused the request'}, {'error': '429 Too Many Requests'},
                      {'nonsense': True}):
            _fresh()
            with SeqPool([error, spike_answer()]) as pool:
                out = twin_reads.read(kind, [img()], {}, run='r35', step=kind)
            check('error' in out and len(pool.calls) == 1, (kind, out, len(pool.calls)))
            if error is DRAFT_TRUNCATED or error.get('truncated'):
                check(out.get('truncated') is True, out)
            check(len(tc.entries()) == 1, ('one attempted read is charged', tc.entries()))
    _fresh()
    with SeqPool([MALFORMED_DRAFT, fixture('outline')]) as pool:
        out = twin_reads.read('outline', [img()], {}, run='r35', step='outline')
    check(out == MALFORMED_DRAFT and len(pool.calls) == 1, ('crop parse errors do not retry', out))


def test_draft_parse_retry_checks_checkpoint_even_when_first_check_was_shared():
    _fresh()
    original = tc.require_clear
    checks = []

    def blocked():
        checks.append(True)
        raise tc.CheckpointReached(10, 10)

    tc.require_clear = blocked
    try:
        with SeqPool([MALFORMED_DRAFT, spike_answer()]) as pool:
            try:
                twin_reads.read('draft', [img()], {}, run='r35', step='draft', checkpoint_checked=True)
            except tc.CheckpointReached:
                pass
            else:
                raise AssertionError('a newly due checkpoint must stop the retry')
        check(checks == [True] and len(pool.calls) == 1 and len(tc.entries()) == 1,
              ('the first attempt is charged; the retry checks before spending', checks, len(pool.calls)))
    finally:
        tc.require_clear = original


if __name__ == '__main__':
    failed = []
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
               scenario_sheet_roles_elsewhere,
               scenario_rooms_output_cap_is_16384,
               scenario_a_truncated_read_is_retried_once_at_twice_the_limit,
               scenario_a_second_truncation_stops_and_other_failures_are_not_retried,
               scenario_footprint_prompts_agree_on_enclosed_walls,
               test_lenient_fences_and_lead_text,
               test_lenient_trailing_brace,
               test_lenient_two_objects_refused,
               test_lenient_keeps_truncation_check,
               test_draft_call_settings,
               test_draft_truncated_no_retry,
               test_draft_prompt_generic,
               test_parse_draft_shape,
               test_parse_draft_level_shape,
               test_parse_draft_rooms_shape,
               test_parse_draft_rooms_without_walls,
               test_draft_rooms_prompt_scope,
               test_small_output_cap_skips_to_fallback,
               test_parse_draft_rooms_blank_name_becomes_room,
               test_draft_rooms_prompt_asks_names_as_printed,
               test_roof_check_call_settings,
               test_roof_check_prompt_generic,
               test_parse_roof_check_shapes,
               test_parse_roof_check_empty_lists_valid,
               test_roof_check_unknown_id_dropped,
               test_draft_parse_failure_retries_once_and_meters_both_attempts,
               test_draft_two_parse_failures_stop_after_two_attempts,
               test_draft_truncation_and_other_errors_still_stop_after_one_attempt,
               test_draft_parse_retry_checks_checkpoint_even_when_first_check_was_shared):
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:200])
        else:
            print('  ok ', fn.__name__)
    if failed:
        print(f'{len(failed)} failed')
        sys.exit(1)
