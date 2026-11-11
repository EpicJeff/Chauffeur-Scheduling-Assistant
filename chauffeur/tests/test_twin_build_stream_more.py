"""Task 3 review regressions. Offline replay only; run as a plain script."""
import copy
import json
import sys
import threading
import time
from unittest.mock import patch

import test_twin_build_stream as s
from test_twin_build_stream import tb, ts, tc, twin_reads, check


def runtime():
    bid = s._pool_house()
    build = tb._create({'part': bid, 'compose': False})
    ticket = tb._launch(build, s.StreamReader(), False)
    step = next(x for x in build['steps'] if x['kind'] == 'draft')
    step['status'] = 'running'
    return build, step, ticket


def test_I1_saves_are_bounded_and_settled_pieces_are_paged():
    build, step, ticket = runtime()
    reader = s.StreamReader(chunk=1)
    with patch.object(tb, '_save', wraps=tb._save) as save:
        tb._read(build, step, reader, ticket, 'draft', [], {})
    check(save.call_count < 20, ('no fsync per piece', save.call_count))
    before = tb.status(build['id'])['events']
    tb._event(build, 'settled', step=step['id'], pieces=[])
    tb._save(build)
    check(not [e for e in build['events'] if e['type'] == 'piece'], 'settled pieces leave state.json')
    # Historical pages retain their sequence numbers, including across reload.
    ts_generation = build['generation']
    tb._forget()
    check(ts.generation() == ts_generation, 'same generation')
    for since in (0, before[len(before)//2]['seq'], before[-1]['seq']):
        got = tb.status(build['id'], since)['events']
        check([e for e in got if e['seq'] <= before[-1]['seq']] ==
              [e for e in before if e['seq'] > since], ('since paging', since))


def test_M1_stopped_poll_does_not_emit_cost():
    build, _, _ = runtime()
    tb.stop(build['id'])
    seq = tb.status(build['id'])['seq']
    for _ in range(10):
        check(tb.status(build['id'])['seq'] == seq, 'unchanged spend creates no events')


def test_M2_auth_error_is_not_a_dropped_stream():
    class Bad(s.StreamReader):
        def _stream(self, kind, run, cancel, on_text):
            on_text('{"building":{"walls":[')
            return {'error': 'HTTP Error 401: Unauthorized'}
    bid = s._pool_house()
    b = tb.start({'part': bid}, reader=Bad(), inline=True)
    text = ' '.join(e.get('text', '') for e in tb.status(b)['events'] if e['type'] == 'question')
    check('ended before' not in text and 'again' in text.lower(), text)


def test_M2_dropped_stream_has_specific_question():
    class Dropped(s.StreamReader):
        def _stream(self, kind, run, cancel, on_text):
            on_text('{"building":{"walls":[')
            return {'error': 'wire lost', 'dropped': True}
    b = tb.start({'part': s._pool_house()}, reader=Dropped(), inline=True)
    check(any('ended before it was complete' in e.get('text', '')
              for e in tb.status(b)['events'] if e['type'] == 'question'), 'dropped reply question')


def test_M3_stop_after_complete_reply_caches_and_continue_reuses():
    bid = s._pool_house()
    original = tb._draft_preview
    stopped = []
    def preview(build, step, fragment):
        if not stopped:
            stopped.append(True)
            tb.stop(build['id'])
        return original(build, step, fragment)
    with patch.object(tb, '_draft_preview', preview):
        b = tb.start({'part': bid}, reader=s.StreamReader(), inline=True)
    check(tb._cache_path(tb._BUILDS[b], s._draft_step(b)).is_file(), 'paid complete reply is cached')
    again = s.StreamReader()
    st = s._continue(b, again)
    check(st['state'] == 'done' and 'draft' not in again.kinds(), ('Continue reuses paid draft', again.kinds()))


def test_M3_stop_after_last_text_before_reader_returns_keeps_reply():
    build, step, ticket = runtime()
    def replay(kind, images, context, *, run, step, cancel, on_text):
        on_text(s._text())
        cancel.produced_chars = len(s._text())
        tb.stop(build['id'])
        raise twin_reads.Cancelled('Read stopped.')
    out = tb._read(build, step, replay, ticket, 'draft', [], {})
    check(out == s.DRAFT, 'complete JSON arriving before Stop is retained')


def test_Q14_complete_non_piece_read_is_kept_without_publishing_pieces():
    import test_twin_reads as reads
    build, step, ticket = runtime()
    answer = reads.fixture('plot')
    def replay(kind, images, context, *, run, step, cancel, on_text):
        on_text(json.dumps(answer))
        tb.stop(build['id'])
        raise twin_reads.Cancelled('Read stopped.')
    out = tb._read(build, step, replay, ticket, 'plot', [], {})
    check(out == answer, 'the complete paid crop reply survives Stop too')
    check(not [e for e in build['events'] if e['type'] == 'piece'], 'non-draft reads still publish no pieces')


def test_Q14_stop_gives_current_piece_a_bounded_grace():
    build, step, ticket = runtime()
    reader = s.StreamReader()
    cut, close = s.after_wall(3, half=True), s.after_wall(4)
    gate, go = threading.Event(), threading.Event()
    def replay(kind, images, context, *, run, step, cancel, on_text):
        text = s._text()
        cancel.produced_chars = cut
        on_text(text[:cut]); gate.set(); go.wait(3)
        time.sleep(.1)
        if not cancel.cancelled:
            cancel.produced_chars = close
            on_text(text[cut:close])
        deadline = time.monotonic() + 3
        while not cancel.cancelled and time.monotonic() < deadline:
            time.sleep(.005)
        reader._charge(kind, run, close if not cancel.cancelled else cancel.produced_chars, cancelled=True)
        raise twin_reads.Cancelled('Read stopped.')
    # The stub mirrors the transport's received-character counter.
    original_charge = reader._charge
    produced = []
    def charge(kind, run, chars, **kw):
        produced.append(chars); original_charge(kind, run, chars, **kw)
    reader._charge = charge
    def run():
        try:
            tb._read(build, step, replay, ticket, 'draft', [], {})
        except twin_reads.Cancelled:
            pass
    thread = threading.Thread(target=run)
    thread.start(); check(gate.wait(2), 'piece in progress')
    start = time.monotonic()
    tb.stop(build['id']); go.set(); thread.join(2)
    check(not thread.is_alive() and time.monotonic() - start < 2, 'Stop ends within 2 seconds')
    got = [e['piece'] for e in tb.status(build['id'])['events'] if e['type'] == 'piece' and e['kind'] == 'wall']
    check(got == s.WALLS[:4], ('the current piece completes in the grace window', len(got)))
    check(tc.entries()[-1]['output_tokens'] == close // 4, 'grace piece is charged')
    tb._keep_partial(build, step, ticket)
    check(s._covered_once(s._house(build['inputs']['part']), s.WALLS[3]), 'grace piece is kept')


def test_Q14_unfinished_piece_is_cut_after_one_second():
    build, step, ticket = runtime()
    reader = s.StreamReader(gate_at=('draft', s.after_wall(3, half=True)))
    def run():
        try:
            tb._read(build, step, reader, ticket, 'draft', [], {})
        except twin_reads.Cancelled:
            pass
    thread = threading.Thread(target=run)
    thread.start(); check(reader.at_gate.wait(2), 'mid piece')
    start = time.monotonic(); tb.stop(build['id']); thread.join(2)
    elapsed = time.monotonic() - start
    check(.85 <= elapsed < 2 and not thread.is_alive(), ('bounded one second grace', elapsed))
    check(len([e for e in tb.status(build['id'])['events'] if e.get('kind') == 'wall']) == 3, 'half wall discarded')


def test_M4_recovery_publishes_persisted_pieces_and_resets_step():
    build, step, ticket = runtime()
    tb._read(build, step, s.StreamReader(), ticket, 'draft', [], {})
    tb._save(build)  # last durable snapshot before process loss
    b, bid = build['id'], build['inputs']['part']
    tb._forget(); tb.recover()
    st = tb.status(b)
    check(st['state'] == 'stopped' and next(x for x in st['steps'] if x['id'] == 'draft')['status'] == 'pending', st['steps'])
    check(any(r.get('partial') for r in ts.rounds()), 'restart keeps persisted pieces in a partial round')
    check(s._covered_once(s._house(bid), s.WALLS[0]), 'recovered wall kept')
    check(any('interrupted' in e.get('text', '') and 'again' in e.get('text', '').lower() for e in st['events']), 'recovery question')


def test_I1_recovery_between_piece_page_and_state_save_keeps_paging_correct():
    build, step, ticket = runtime()
    tb._save(build)
    with patch.object(tb, '_save'):
        tb._read(build, step, s.StreamReader(), ticket, 'draft', [], {})
    # Pieces have their own durable page; the process dies before state.json
    # receives the settled event and the page's most recent sequence number.
    tb._event(build, 'settled', step=step['id'], pieces=[])
    b = build['id']
    tb._forget(); tb.recover()
    st = tb.status(b)
    seqs = [e['seq'] for e in st['events']]
    check(len(seqs) == len(set(seqs)) and max(seqs) <= st['seq'], 'recovery never reuses archived event sequence numbers')
    check(any(r.get('partial') for r in ts.rounds()), 'unsettled durable page becomes a partial round')


def test_M5_fallback_streams_scoped_floors_and_discards_whole_draft():
    build, step, ticket = runtime()
    context = {'level': 'L2'}
    class Floor(s.StreamReader):
        def __call__(self, kind, images, context, *, run, step, cancel=None, on_text=None):
            answer = copy.deepcopy(s.DRAFT)
            answer['building']['levels'] = [s.DRAFT['building']['levels'][1]]
            answer['building']['walls'] = [s.WALLS[4]]
            on_text(json.dumps(answer))
            return answer
    # The abandoned whole read must not leak into the partial fallback.
    tb._read(build, step, s.StreamReader(), ticket, 'draft', [], {})
    tb._read(build, step, Floor(), ticket, 'draft_level', [], context)
    build['state'] = 'stopped'
    tb._keep_partial(build, step, ticket)
    house = s._house(build['inputs']['part'])
    check(s._covered_once(house, s.WALLS[4]) and not s._along(house, s.WALLS[0]),
          ('only floor scope is published', [(w['id'], w['level'], w['from'], w['to']) for w in house['walls']]))
    stream = tb._WORKERS[build['id']]['stream']
    check(any(path == 'building.walls' and p['id'] == 'L2:K1' for path, p in stream['items']), 'scope-prefixed wall ids')


def test_M5_stop_in_second_floor_keeps_paid_first_floor_and_current_pieces():
    class Floors(s.StreamReader):
        def __call__(self, kind, images, context, *, run, step, cancel=None, on_text=None, **kw):
            if kind == 'outline':
                return {'error': 'disposable outline'}
            if kind == 'draft':
                on_text(s._text())
                return {'error': 'max tokens', 'truncated': True}
            check(kind == 'draft_level', ('expected a scoped read', kind))
            scope = context['level']
            floor = {'levels': [l for l in s.DRAFT['building']['levels'] if l['id'] == scope],
                     'walls': [w for w in s.WALLS if w['level'] == scope], 'openings': [], 'rooms': []}
            answer = {'building': floor, 'pages': [], 'checks': {}, 'notes': []}
            text = json.dumps(answer)
            if scope == 'L2':
                next_wall = json.dumps(floor['walls'][1])
                cut = text.index(next_wall) + len(next_wall) // 2
                on_text(text[:cut]); self.at_gate.set()
                self._wait(cancel)
                raise twin_reads.Cancelled('Read stopped.')
            on_text(text)
            return answer
    reader = Floors()
    bid = s._pool_house()
    b = tb.start({'part': bid}, reader=reader, inline=False)
    try:
        check(reader.at_gate.wait(10), 'fallback reached second floor')
        started = time.monotonic(); tb.stop(b)
        s._stopped_with(b, lambda st: any(r.get('partial') for r in s._draft_rounds(0)))
        check(time.monotonic() - started < 2, 'fallback stops within 2 seconds')
        house = s._house(bid)
        check(all(s._covered_once(house, w) for w in s.WALLS[:5]), 'paid first floor and current complete wall kept')
        check(not s._along(house, s.WALLS[5]), 'abandoned whole draft wall is absent')
        cached = json.loads(tb._cache_path(tb._BUILDS[b], s._draft_step(b)).read_text(encoding='utf-8'))
        check(len(cached['level_reads']) == 1, 'paid first floor is cached')
    finally:
        s._release(reader)


def test_M6_failed_partial_publish_still_saves_question_and_idles():
    bid = s._pool_house()
    with patch.object(tb, '_keep_partial', side_effect=OSError('disk full')):
        b = tb.start({'part': bid}, reader=s.StreamReader(end_at=('draft', s.after_wall(3, half=True))), inline=True)
    state = json.loads((tb._root(b) / 'state.json').read_text(encoding='utf-8'))
    check(state['state'] == 'stopped' and any(e['type'] == 'question' for e in state['events']), 'question and stopped state saved')
    check(not tb._WORKERS[b]['busy'], 'worker idles even if partial publish fails')


def test_I2_non_draft_is_cancellable_without_piece_events():
    build, step, ticket = runtime()
    def product(kind, images, context, *, run, step):
        raise AssertionError('blocking reader reached')
    def streamed(kind, context, images, *, cancel, on_text, run, step):
        check(hasattr(cancel, 'cancel'), 'cancellable call')
        on_text(json.dumps(s.DRAFT))
        return {'ok': True}
    with patch.object(tb, '_REAL_READER', product), patch.object(twin_reads, 'read', product), patch.object(twin_reads, 'read_stream', streamed):
        check(tb._read(build, step, product, ticket, 'plot', [], {}) == {'ok': True}, 'product uses cancellable transport')
    check(not [e for e in build['events'] if e['type'] == 'piece'], 'only draft kinds publish pieces')


def test_I2_product_plot_retries_truncation_at_twice_limit():
    import test_twin_reads as reads
    limits = []
    def wire(*args, cancel, max_output_tokens, **kw):
        limits.append(max_output_tokens)
        cancel.reset()
        cancel.usage.update(dispatched=True, input_tokens=100, output_tokens=10,
                            complete=len(limits) > 1, finish_reason='max_tokens' if len(limits) == 1 else 'end_turn')
        yield '{' if len(limits) == 1 else json.dumps(reads.fixture('plot'))
    build, step, ticket = runtime()
    with patch.object(twin_reads.model_pools, 'credentials', return_value=(s.MODEL, 'fake')), \
         patch.object(tb.llm_stream, 'stream_json', wire):
        out = tb._read(build, step, twin_reads.read, ticket, 'plot', [], {})
    check('error' not in out and limits == [8192, 16384], ('crop retry parity', out, limits))
    check(len([e for e in tc.entries() if e.get('run') == build['id']]) == 2, 'one charge per attempt')


TESTS = [v for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]
if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('FAIL', fn.__name__, type(exc).__name__, str(exc)[:400])
        else:
            print('ok', fn.__name__)
        finally:
            s._join()
    print(f'{len(TESTS)-len(failed)}/{len(TESTS)} passed')
    sys.exit(bool(failed))
