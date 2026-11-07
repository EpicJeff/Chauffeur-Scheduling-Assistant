"""The twin cost ledger: prices, conservative estimates, $10/$25/$50
checkpoints, and usage reported per provider request by
model_pools.call_pool_json (spec docs/superpowers/specs/
2026-11-06-house-digital-twin-design.md section 8.6; plan Task 3).

Run from chauffeur/:  python tests/test_twin_cost.py
"""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_cost_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import storage  # noqa: E402


def check(cond, msg):
    # Local on purpose: tests/harness.py replaces storage.get_settings with a
    # fixed stub, which would hide every settings write this file checks.
    if not cond:
        raise AssertionError(msg)

from services import twin_cost as tc  # noqa: E402

M = 1_000_000


def _fresh():
    storage.patch_settings({'house_twin_cost': None})


def _known():
    return sorted(tc.PRICES)[0]


def _hi():
    return max(p[0] for p in tc.PRICES.values()), max(p[1] for p in tc.PRICES.values())


def _usage(model, inp, out, images=0, prompt_chars=0, max_out=8192):
    return {'model': model, 'input_tokens': inp, 'output_tokens': out,
            'images': images, 'prompt_chars': prompt_chars, 'max_output_tokens': max_out}


def _close(a, b):
    return abs(a - b) < 1e-9


def scenario_constants():
    check(tc.CHECKPOINTS == (10.0, 20.0, 30.0, 40.0), tc.CHECKPOINTS)
    check(tc.HARD_STOP == 50.0, tc.HARD_STOP)
    check(tc.ROUND_CAP == 5, tc.ROUND_CAP)
    check(len(tc.PRICES) >= 3 and all(len(v) == 2 and v[0] > 0 and v[1] > 0 for v in tc.PRICES.values()),
          'a price table with positive input and output rates')
    check(any(k.startswith('anthropic:') for k in tc.PRICES) and any(':' not in k for k in tc.PRICES),
          'prices keyed by model_pools ids: prefixed for Claude/OpenAI, bare for Gemini')


def scenario_price_and_record():
    _fresh()
    k = _known()
    usd, priced = tc.price(k, M, 0)
    check(priced and _close(usd, tc.PRICES[k][0]), (usd, priced))
    usd, _ = tc.price(k, 0, M)
    check(_close(usd, tc.PRICES[k][1]), usd)
    entries = tc.record('building', [_usage(k, 2 * M, M)], run='r1')
    check(len(entries) == 1, entries)
    e = entries[0]
    check(e['stage'] == 'building' and e['model'] == k and e['run'] == 'r1' and e['priced'] is True
          and e['basis'] == 'reported' and e['input_tokens'] == 2 * M and e['output_tokens'] == M, e)
    check(_close(e['usd'], 2 * tc.PRICES[k][0] + tc.PRICES[k][1]) and _close(tc.total(), e['usd']), e)


def scenario_unpriced_models_cost_at_the_highest_rate():
    hi_in, hi_out = _hi()
    usd, priced = tc.price('anthropic:not-a-model', M, M)
    check(not priced and _close(usd, hi_in + hi_out), (usd, priced))


def scenario_missing_usage_is_costed_conservatively():
    _fresh()
    hi_in, hi_out = _hi()
    e = tc.record('finishes', [_usage(_known(), None, None, images=2, prompt_chars=4000, max_out=8192)])[0]
    check(e['basis'] == 'estimated', e)
    want = (2 * 1600 + 4000 / 4) / M * hi_in + 8192 / M * hi_out
    check(_close(e['usd'], want), (e['usd'], want))


def scenario_checkpoints_block_until_acknowledged():
    _fresh()
    k = _known()
    per_dollar_in = M / tc.PRICES[k][0]          # input tokens that cost $1
    tc.record('building', [_usage(k, int(per_dollar_in * 9.9), 0)])
    check(tc.blocking_checkpoint() is None, 'under $10: clear')
    tc.require_clear()
    tc.record('site', [_usage(k, int(per_dollar_in * 0.2), 0)])
    check(tc.blocking_checkpoint() == 10.0, tc.blocking_checkpoint())
    try:
        tc.require_clear()
    except tc.CheckpointReached as e:
        check(e.checkpoint == 10.0 and e.total > 10.0, (e.checkpoint, e.total))
    else:
        raise AssertionError('require_clear raises at $10')
    tc.acknowledge(10.0)
    check(tc.blocking_checkpoint() is None, 'acknowledged')
    tc.require_clear()
    tc.record('site', [_usage(k, int(per_dollar_in * 10.5), 0)])
    check(tc.blocking_checkpoint() == 20.0, tc.blocking_checkpoint())
    tc.acknowledge(20.0)
    tc.record('site', [_usage(k, int(per_dollar_in * 25), 0)])
    check(tc.blocking_checkpoint() == 30.0, 'a jump past $40 blocks at 30 first')


def scenario_a_jump_over_two_checkpoints_blocks_at_the_lower():
    _fresh()
    k = _known()
    tc.record('building', [_usage(k, int(M / tc.PRICES[k][0] * 30), 0)])
    check(tc.blocking_checkpoint() == 10.0, 'the smallest unacknowledged checkpoint first')
    tc.acknowledge(10.0)
    check(tc.blocking_checkpoint() == 20.0, 'then the next')


def scenario_a_round_that_crosses_a_checkpoint_is_kept():
    _fresh()
    k = _known()
    per_dollar_in = M / tc.PRICES[k][0]
    tc.record('building', [_usage(k, int(per_dollar_in * 9.8), 0)])
    tc.record('director', [_usage(k, int(per_dollar_in * 0.6), 0)], run='run-x')
    check(len(tc.entries()) == 2 and tc.total() > 10.0 and tc.blocking_checkpoint() == 10.0,
          'the crossing round is recorded in full, and the next call is blocked')


def scenario_call_pool_json_reports_usage():
    from services import llm, model_pools
    calls = []
    orig = llm.call_model

    def stub(model_id, api_key, system_prompt, user_prompt, text=False, **kw):
        calls.append(model_id)
        if len(calls) == 1:
            raise RuntimeError('503 upstream')            # dispatched, no usage came back
        m = kw.get('metrics')
        check(isinstance(m, dict), 'call_model receives a metrics dict when usage is collected')
        m.update({'promptTokenCount': 120, 'candidatesTokenCount': 40, 'thoughtsTokenCount': 10})
        return {'ok': 1}
    llm.call_model = stub
    try:
        usage = []
        res = model_pools.call_pool_json('vision', 'k', 'sys', 'user prompt', max_models=2,
                                         settings={'llm_gemini_api_key': 'k'},
                                         images=[{'mime': 'image/png', 'b64': 'AA=='}],
                                         max_output_tokens=4096, usage=usage)
    finally:
        llm.call_model = orig
    check(res.get('ok') == 1 and len(calls) == 2, (res, calls))
    check(len(usage) == 2, usage)
    check(usage[0]['model'] == calls[0] and usage[0]['input_tokens'] is None and usage[0]['output_tokens'] is None,
          usage[0])
    check(usage[1]['model'] == calls[1] and usage[1]['input_tokens'] == 120 and usage[1]['output_tokens'] == 50,
          usage[1])
    check(all(u['images'] == 1 and u['prompt_chars'] == len('sys') + len('user prompt')
              and u['max_output_tokens'] == 4096 for u in usage), usage)
    # existing callers: no usage list, nothing changes
    llm.call_model = lambda *a, **k: {'ok': 2}
    try:
        check(model_pools.call_pool_json('vision', 'k', 's', 'u', settings={'llm_gemini_api_key': 'k'})['ok'] == 2,
              'callers without usage are unchanged')
    finally:
        llm.call_model = orig


def scenario_unreached_checkpoints_cannot_be_acknowledged():
    _fresh()
    k = _known()
    tc.record('building', [_usage(k, int(M / tc.PRICES[k][0] * 0.4), 0)])
    for cp in (10.0, 20.0, 30.0, 40.0, 50.0):
        try:
            tc.acknowledge(cp)
        except ValueError:
            continue
        raise AssertionError(f'acknowledging {cp} at $0.40 must raise: it would disarm the gate ahead of time')
    tc.record('building', [_usage(k, int(M / tc.PRICES[k][0] * 12), 0)])
    tc.acknowledge(10.0)
    check(tc.blocking_checkpoint() is None, 'a reached checkpoint can be acknowledged')
    try:
        tc.acknowledge(20.0)
    except ValueError:
        pass
    else:
        raise AssertionError('20 is not reached yet at ~$12.40')


def scenario_no_output_limit_is_costed_at_a_ceiling():
    _fresh()
    hi_in, hi_out = _hi()
    e = tc.record('site', [_usage(_known(), None, None, images=0, prompt_chars=400, max_out=0)])[0]
    check(e['basis'] == 'estimated' and _close(e['usd'], 100 / M * hi_in + tc.UNKNOWN_OUTPUT_TOKENS / M * hi_out),
          (e, tc.UNKNOWN_OUTPUT_TOKENS))
    check(tc.UNKNOWN_OUTPUT_TOKENS >= 32768, 'a real ceiling, not zero')


def _paid_fallback_stubs(model_pools, state):
    from services import paid_fallback
    saved = (model_pools.api_key_for_pool, paid_fallback.status, paid_fallback.note_throttle, paid_fallback.count_call)
    model_pools.api_key_for_pool = lambda pool, settings: 'paid-key'
    paid_fallback.status = lambda settings, now=None: {'active': state['active'], 'configured': True,
                                                       'used_today': 0, 'cap': 100}
    paid_fallback.note_throttle = lambda settings, now=None: state.update(active=True)
    paid_fallback.count_call = lambda settings, now=None: True

    def restore():
        (model_pools.api_key_for_pool, paid_fallback.status,
         paid_fallback.note_throttle, paid_fallback.count_call) = saved
    return restore


def scenario_one_request_cap_holds_across_the_paid_fallback():
    from services import llm, model_pools
    calls = []
    orig = llm.call_model

    def failing(model_id, *a, **kw):
        calls.append(model_id)
        raise RuntimeError('503 upstream')
    llm.call_model = failing
    restore = _paid_fallback_stubs(model_pools, {'active': False})
    try:
        usage = []
        res = model_pools.call_pool_json('vision', 'k', 's', 'u', max_models=1,
                                         settings={'llm_gemini_api_key': 'k', 'llm_paid_fallback_mode': 'auto'},
                                         max_output_tokens=1024, usage=usage)
    finally:
        restore()
        llm.call_model = orig
    check(len(calls) == 1 and len(usage) == 1, f'one billed request at most, even with paid fallback: {calls}')
    check('503' in str(res.get('error')) and res.get('transient') is True,
          f'the real error and its transient flag survive the spent budget: {res}')


def scenario_partial_metrics_are_estimated_not_zero():
    from services import llm, model_pools
    orig = llm.call_model

    def half(model_id, *a, **kw):
        kw['metrics'].update({'candidatesTokenCount': 300})       # no promptTokenCount came back
        return {'ok': 1}
    llm.call_model = half
    try:
        usage = []
        model_pools.call_pool_json('vision', 'k', 's', 'u', max_models=1,
                                   settings={'llm_gemini_api_key': 'k'}, max_output_tokens=1024, usage=usage)
    finally:
        llm.call_model = orig
    check(usage and usage[0]['input_tokens'] is None, f'missing prompt count stays unknown: {usage}')
    _fresh()
    e = tc.record('x', usage)[0]
    check(e['basis'] == 'estimated', e)


def scenario_the_hard_stop_cannot_be_acknowledged():
    _fresh()
    k = _known()
    tc.record('building', [_usage(k, int(M / tc.PRICES[k][0] * 51), 0)])
    for cp in tc.CHECKPOINTS:
        tc.acknowledge(cp)
    try:
        tc.require_clear()
    except tc.CheckpointReached as e:
        check(e.checkpoint == 50.0, e.checkpoint)
    else:
        raise AssertionError('past $50 nothing runs')
    try:
        tc.acknowledge(50.0)
    except ValueError:
        pass
    else:
        raise AssertionError('the $50 stop cannot be acknowledged')
    check(tc.blocking_checkpoint() == 50.0, 'and it keeps blocking')


def scenario_cost_routes():
    _fresh()
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app)
    k = _known()
    tc.record('building', [_usage(k, int(M / tc.PRICES[k][0] * 11), 0)])
    r = c.get('/api/house/twin/cost')
    body = r.json()
    check(r.status_code == 200 and body['blocking'] == 10.0 and len(body['entries']) == 1 and body['total'] > 10, r.text)
    r = c.post('/api/house/twin/cost/ack', json={'checkpoint': 10.0})
    check(r.status_code == 200 and c.get('/api/house/twin/cost').json()['blocking'] is None, r.text)
    r = c.post('/api/house/twin/cost/ack', json={'checkpoint': 7})
    check(r.status_code == 400, f'only real checkpoints can be acknowledged: {r.status_code}')
    from services import auth
    check(auth.resolve('GET', '/api/house/twin/cost') == auth.PARENTS, 'cost read is parents only')
    check(auth.resolve('POST', '/api/house/twin/cost/ack') == auth.PARENTS, 'ack is parents only')


if __name__ == '__main__':
    for fn in (scenario_constants,
               scenario_price_and_record,
               scenario_unpriced_models_cost_at_the_highest_rate,
               scenario_missing_usage_is_costed_conservatively,
               scenario_checkpoints_block_until_acknowledged,
               scenario_a_jump_over_two_checkpoints_blocks_at_the_lower,
               scenario_a_round_that_crosses_a_checkpoint_is_kept,
               scenario_call_pool_json_reports_usage,
               scenario_unreached_checkpoints_cannot_be_acknowledged,
               scenario_no_output_limit_is_costed_at_a_ceiling,
               scenario_one_request_cap_holds_across_the_paid_fallback,
               scenario_partial_metrics_are_estimated_not_zero,
               scenario_the_hard_stop_cannot_be_acknowledged,
               scenario_cost_routes):
        fn()
        print('  ok ', fn.__name__)
