"""Real HTTP edit spans, exact UTF-8 response size and bounded perf reports."""
import math
import sys
import traceback
from test_twin_ha_routes import Ctx, seed, ts
from services import twin_timing

OP = '/api/house/editor/op'
PERF = '/api/house/twin/perf'
NAMES = {'lock', 'apply', 'normalize', 'round', 'read', 'response'}


def test_real_op_has_spans_bytes_and_unchanged_model():
    seed()
    with Ctx() as c:
        building = ts.current_model()['buildings'][0]['id']
        count = len(ts.rounds())
        r = c.client.post(OP, headers={**c.mum, 'Accept-Encoding': 'identity'}, json={'op': {
            'op': 'set', 'building': building, 'id': 'kitchen', 'field': 'name', 'value': 'Café 🍵'}})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {'round', 'words', 'plan', 'model', 'timing', 'bytes'}
        assert set(body['timing']) == NAMES
        assert all(math.isfinite(v) and v >= 0 for v in body['timing'].values())
        assert all(body['timing'][name] > 0 for name in NAMES - {'lock'})
        header = dict(part.split(';dur=') for part in r.headers['server-timing'].split(', '))
        assert {k: float(v) for k, v in header.items()} == body['timing']
        assert body['bytes'] == len(r.content) == int(r.headers['content-length']), (body['bytes'], len(r.content), r.headers)
        assert body['plan'] == ts.current() and body['model'] == ts.current_model()
        assert len(ts.rounds()) == count + 1
        assert 'Server-Timing' not in c.client.get('/api/house/editor/state', headers=c.mum).headers


def test_refusal_resets_request_context_and_adds_no_round():
    seed()
    with Ctx() as c:
        count = len(ts.rounds())
        r = c.client.post(OP, headers=c.mum, json={'op': {'op': 'not_an_op'}})
        assert r.status_code == 400 and r.json()['error']
        assert set(r.json()['timing']) == NAMES
        assert r.json()['bytes'] == len(r.content)
        assert len(ts.rounds()) == count
        assert twin_timing._active.get() is None
        assert 'Server-Timing' not in c.client.get(PERF, headers=c.mum).headers


def test_edit_timing_report_accepts_thirty_and_rejects_caps():
    with Ctx() as c:
        records = [{'op': 'set', 'total': 12.5, 'request': 5, 'detail': {'generate': 3}} for _ in range(30)]
        body = {'kind': 'edit_timing', 'records': records}
        r = c.client.post(PERF, headers=c.mum, json=body)
        assert r.status_code == 200 and r.json() == body
        assert c.client.get(PERF, headers=c.mum).json()['results'][-1] == body
        for bad in (records + records[:1], [], ['bad'], [{'data': 'x' * (256 * 1024)}]):
            r = c.client.post(PERF, headers=c.mum, json={'kind': 'edit_timing', 'records': bad})
            assert r.status_code == 400, r.text
        try:
            ts.save_perf({'kind': 'edit_timing', 'records': [{'total': float('nan')}]})
            raise AssertionError('NaN report accepted')
        except ValueError:
            pass


def test_legacy_perf_still_round_trips():
    with Ctx() as c:
        body = dict(tier='high', gpu='test', ua='node', at='now', fpsAvg=60, fpsP5=55, drawCalls=50, triangles=100)
        r = c.client.post(PERF, headers=c.mum, json=body)
        assert r.status_code == 200 and r.json() == body


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print('ok  ', test.__name__)
        except Exception:
            print('FAIL', test.__name__)
            traceback.print_exc(limit=6)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
