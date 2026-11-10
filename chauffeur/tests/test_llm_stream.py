"""Reader calls stream and can be stopped mid-call (plan docs/superpowers/plans/
2026-11-10-house-guided-build-piece-4.md Task 1; brief .superpowers/sdd/
2026-11-10-house-guided-build-piece-4/task-1-brief.md; Review Focus 1 and 5;
ruling Q3: only Anthropic and Gemini stream, every other provider reads
blocking and Stop closes its socket).

Interfaces under test:
  llm_stream.Cancel()            .cancel(), .cancelled, .attach(resp), .usage
  llm_stream.stream_json(provider, url, api_key, model, system_prompt,
      user_prompt, *, images, max_output_tokens, thinking_level, timeout_s,
      cancel) -> Iterator[str]   answer text deltas only (thinking excluded),
      then cancel.usage = {'input_tokens', 'output_tokens', 'complete'}
  twin_reads.read_stream(kind, context, images, *, cancel, on_text, run, step)
      same pool, credentials, prompt and validation as twin_reads.read;
      raises twin_reads.Cancelled after a cancel
  twin_cost.record(stage, usage, run, *, cancelled=False, produced_chars=0)

No test spends money or opens a socket: llm_budget.urlopen is replaced by a
fake whose bodies are file-like SSE streams, and urllib.request.urlopen and
socket.create_connection raise if anything reaches them. The fake body is
faithful to http.client where a stream reader depends on it: read(n) blocks
until n bytes or the end, read1/readline return what has arrived, and close()
from another thread ends a blocked read (as EOF, or as an error like a closed
socket file).

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_llm_stream.py
"""
import copy
import json
import math
import os
import random
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.request

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_llm_stream_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _no_network(*args, **kwargs):
    raise AssertionError('a test reached the real network; every call must go through the fake urlopen')


urllib.request.urlopen = _no_network
socket.create_connection = _no_network

from services import llm, llm_budget, model_pools, storage  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_reads  # noqa: E402

try:
    from services import llm_stream  # noqa: E402
    _IMPORT_ERROR = None
except ImportError as exc:  # the module does not exist until Task 1 lands
    llm_stream = None
    _IMPORT_ERROR = exc

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
CLAUDE = 'claude-opus-5-5'
GEMINI = 'gemini-3.1-pro-preview'
STOP_WITHIN = 2.0


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _ls():
    if llm_stream is None:
        raise _IMPORT_ERROR
    return llm_stream


def img():
    return {'mime': 'image/png', 'b64': 'iVBORw0KGgo='}


def recorded(name):
    with open(os.path.join(RECORDED, name), encoding='utf-8') as f:
        return json.load(f)


def wait_until(cond, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# ---------------------------------------------------------------- the fake wire

class Body:
    """A streaming HTTP response body. `hold` delivers only the first `hold`
    chunks until release() or close(); a read that reaches a held chunk blocks
    (and sets `waiting`)."""
    status = 200
    reason = 'OK'

    def __init__(self, chunks, *, hold=None, closed_raises=False):
        self._chunks = [bytes(c) for c in chunks]
        self._next = 0
        self._buf = bytearray()
        self._open_upto = len(self._chunks) if hold is None else hold
        self._cv = threading.Condition()
        self.closed = False
        self.closed_raises = closed_raises
        self.waiting = threading.Event()
        self.headers = {'Content-Type': 'text/event-stream'}

    # -- control from the test
    def release(self):
        with self._cv:
            self._open_upto = len(self._chunks)
            self._cv.notify_all()

    def close(self):
        with self._cv:
            self.closed = True
            self._cv.notify_all()

    # -- http.client-like surface
    def _ended(self):
        if self.closed_raises:
            raise ValueError('I/O operation on closed file.')
        return b''

    def _more(self):
        while True:
            if self.closed or self._next >= len(self._chunks):
                return False
            if self._next < self._open_upto:
                self._buf += self._chunks[self._next]
                self._next += 1
                return True
            self.waiting.set()
            self._cv.wait(timeout=30)

    def _take(self, n):
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def read(self, n=-1):
        with self._cv:
            if self.closed:
                return self._ended()
            if n is None or n < 0:
                while self._more():
                    pass
                return self._ended() if self.closed else self._take(len(self._buf))
            while len(self._buf) < n and self._more():
                pass
            return self._ended() if self.closed else self._take(n)

    def read1(self, n=-1):
        with self._cv:
            if self.closed:
                return self._ended()
            if not self._buf:
                self._more()
            if self.closed:
                return self._ended()
            return self._take(len(self._buf) if n is None or n < 0 else n)

    def readline(self, limit=-1):
        with self._cv:
            if self.closed:
                return self._ended()
            while b'\n' not in self._buf and self._more():
                pass
            if self.closed:
                return self._ended()
            i = self._buf.find(b'\n')
            end = i + 1 if i >= 0 else len(self._buf)
            if limit is not None and limit >= 0:
                end = min(end, limit)
            return self._take(end)

    def readinto(self, b):
        data = self.read1(len(b))
        b[:len(data)] = data
        return len(data)

    def __iter__(self):
        while True:
            line = self.readline()
            if not line:
                return
            yield line

    def readable(self):
        return True

    def isclosed(self):
        return self.closed

    def getcode(self):
        return self.status

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def info(self):
        return self.headers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class Wire:
    """Stands in for llm_budget.urlopen. `gate`, when given, holds urlopen
    itself (the connect / time-to-first-byte window) until it is set."""

    def __init__(self, respond, gate=None):
        self.respond = respond
        self.gate = gate
        self.requests, self.bodies = [], []
        self.called = threading.Event()

    def __call__(self, request, timeout=60):
        self.requests.append(request)
        self.called.set()
        if self.gate is not None:
            self.gate.wait(10)
        body = self.respond(request)
        self.bodies.append(body)
        return body

    def payload(self, i=0):
        return json.loads(self.requests[i].data.decode('utf-8'))

    def __enter__(self):
        self.original = llm_budget.urlopen
        llm_budget.urlopen = self
        return self

    def __exit__(self, *exc):
        llm_budget.urlopen = self.original
        if self.gate is not None:
            self.gate.set()
        for body in self.bodies:
            body.close()
        return False


class Run:
    """Drive a call on a daemon thread so the test can cancel it."""

    def __init__(self, call):
        self.deltas, self.error, self.result = [], None, None
        self.first, self.done = threading.Event(), threading.Event()

        def go():
            try:
                out = call()
                if hasattr(out, '__next__') or (hasattr(out, '__iter__') and not isinstance(out, (dict, str))):
                    for delta in out:
                        self.deltas.append(delta)
                        self.first.set()
                else:
                    self.result = out
            except BaseException as exc:  # noqa: BLE001 - recorded for the test
                self.error = exc
            finally:
                self.done.set()

        threading.Thread(target=go, daemon=True).start()


def drain(iterator_factory):
    """(deltas, error) for a call run to its end on this thread."""
    deltas = []
    try:
        for delta in iterator_factory():
            deltas.append(delta)
    except Exception as exc:  # noqa: BLE001
        return deltas, exc
    return deltas, None


# ---------------------------------------------------------------- SSE bodies

def _pieces(text, size):
    return [text[i:i + size] for i in range(0, len(text), size)]


def anthropic_events(text_parts, *, thinking_parts=(), input_tokens=1234, output_tokens=5000,
                     stop_reason='end_turn', end=True):
    """Messages API stream events, each its own bytes, as the API writes them."""
    events = [('message_start', {'type': 'message_start', 'message': {
        'id': 'msg_01Stream', 'type': 'message', 'role': 'assistant', 'model': CLAUDE,
        'content': [], 'stop_reason': None, 'stop_sequence': None,
        'usage': {'input_tokens': input_tokens, 'cache_creation_input_tokens': 0,
                  'cache_read_input_tokens': 0, 'output_tokens': 1}}})]
    index = 0
    if thinking_parts:
        events.append(('content_block_start', {'type': 'content_block_start', 'index': 0,
                                               'content_block': {'type': 'thinking', 'thinking': '', 'signature': ''}}))
        for part in thinking_parts:
            events.append(('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                                   'delta': {'type': 'thinking_delta', 'thinking': part}}))
        events.append(('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                               'delta': {'type': 'signature_delta',
                                                         'signature': 'EqQBCgIYAhIM1gbcDa9GJwZA2b3hGgxDYzVk'}}))
        events.append(('content_block_stop', {'type': 'content_block_stop', 'index': 0}))
        index = 1
    events.append(('content_block_start', {'type': 'content_block_start', 'index': index,
                                           'content_block': {'type': 'text', 'text': ''}}))
    events.append(('ping', {'type': 'ping'}))
    for part in text_parts:
        events.append(('content_block_delta', {'type': 'content_block_delta', 'index': index,
                                               'delta': {'type': 'text_delta', 'text': part}}))
    if end:
        events.append(('content_block_stop', {'type': 'content_block_stop', 'index': index}))
        events.append(('message_delta', {'type': 'message_delta',
                                         'delta': {'stop_reason': stop_reason, 'stop_sequence': None},
                                         'usage': {'output_tokens': output_tokens}}))
        events.append(('message_stop', {'type': 'message_stop'}))
    return [(name, f'event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'.encode('utf-8'))
            for name, data in events]


def gemini_events(text_parts, *, thought_parts=(), prompt=2100, candidates=800, thoughts=450,
                  finish='STOP', end=True, model=GEMINI):
    """streamGenerateContent?alt=sse chunks (CRLF framed, as Google sends them)."""
    chunks = []

    def chunk(parts, last=False):
        candidate = {'content': {'parts': parts, 'role': 'model'}, 'index': 0}
        usage = {'promptTokenCount': prompt, 'totalTokenCount': prompt, 'thoughtsTokenCount': thoughts}
        if last:
            candidate['finishReason'] = finish
            usage = {'promptTokenCount': prompt, 'candidatesTokenCount': candidates,
                     'thoughtsTokenCount': thoughts, 'totalTokenCount': prompt + candidates + thoughts,
                     'promptTokensDetails': [{'modality': 'TEXT', 'tokenCount': prompt}]}
        return {'candidates': [candidate], 'usageMetadata': usage, 'modelVersion': model,
                'responseId': 'aBcDeFgHiJ'}

    thought_parts = list(thought_parts)
    text_parts = list(text_parts)
    for part in thought_parts[:-1]:
        chunks.append(('thought', chunk([{'text': part, 'thought': True}])))
    if thought_parts and text_parts:
        # A chunk that carries the last thought summary and the first answer text.
        chunks.append(('mixed', chunk([{'text': thought_parts[-1], 'thought': True}, {'text': text_parts[0]}],
                                      last=end and len(text_parts) == 1)))
        text_parts = text_parts[1:]
    elif thought_parts:
        chunks.append(('thought', chunk([{'text': thought_parts[-1], 'thought': True}])))
    for i, part in enumerate(text_parts):
        chunks.append(('text', chunk([{'text': part}], last=end and i == len(text_parts) - 1)))
    return [(name, f'data: {json.dumps(data, ensure_ascii=False)}\r\n\r\n'.encode('utf-8')) for name, data in chunks]


def rechunk(events, seed, top=23):
    """Split the joined stream at random byte boundaries (mid-line and mid
    UTF-8 character included), the way TCP delivers it."""
    data = b''.join(raw for _, raw in events)
    rng = random.Random(seed)
    out, i = [], 0
    while i < len(data):
        n = rng.randint(1, top)
        out.append(data[i:i + n])
        i += n
    return out


def halves(events):
    """Each event split in two chunks; returns (chunks, chunk index after each event)."""
    chunks, ends = [], []
    for _, raw in events:
        cut = max(1, len(raw) // 2)
        chunks += [raw[:cut], raw[cut:]]
        ends.append(len(chunks))
    return chunks, ends


TEXT = ('{"building":{"name":"Café ½ bath","walls":[{"id":"w1","from":[0,0],"to":[31.5,0]},'
        '{"id":"w2","from":[31.5,0],"to":[31.5,24.0]}],"notes":["5\'-8\\" = 5.667 — checked"]}}')


def _stream(provider, cancel, *, model=None, key='test-key', system='SYS', user='USER', images=None,
            max_output_tokens=64000):
    return _ls().stream_json(provider, '', key, model or (CLAUDE if provider == 'anthropic' else GEMINI),
                             system, user, images=[img(), img()] if images is None else images,
                             max_output_tokens=max_output_tokens, thinking_level='medium', timeout_s=600,
                             cancel=cancel)


def _usage(cancel):
    usage = getattr(cancel, 'usage', None)
    check(isinstance(usage, dict) and {'input_tokens', 'output_tokens', 'complete'} <= set(usage),
          f'cancel.usage must be set to input_tokens, output_tokens and complete: {usage!r}')
    return usage


# ---------------------------------------------------------------- tests

def anthropic_sse_yields_text_and_usage():
    ls = _ls()
    parts = _pieces(TEXT, 9)
    events = anthropic_events(parts, thinking_parts=['Reading the sheets. ', 'The front is at the bottom.'])
    for seed in (1, 2, 3):
        with Wire(lambda r: Body(rechunk(events, seed))) as wire:
            cancel = ls.Cancel()
            out, error = drain(lambda: _stream('anthropic', cancel))
        check(error is None, f'a complete stream ends cleanly: {error!r}')
        check(''.join(out) == TEXT, f'the answer text comes back whole (seed {seed}): {"".join(out)[:120]!r}')
        check(len(out) > 1, f'the answer arrives as deltas, not one blob at the end: {len(out)} pieces')
        check(all(isinstance(d, str) for d in out), 'deltas are text')
        usage = _usage(cancel)
        check(usage['input_tokens'] == 1234 and usage['output_tokens'] == 5000 and usage['complete'] is True,
              f'input from message_start, output from message_delta, complete at message_stop: {usage}')
        check(cancel.cancelled is False, 'a finished call was never cancelled')
    request = wire.requests[0]
    check(len(wire.requests) == 1 and request.full_url == llm.ANTHROPIC_URL,
          f'one request to the Messages API: {[r.full_url for r in wire.requests]}')
    check(request.get_header('X-api-key') == 'test-key' and request.get_header('Anthropic-version'),
          'the request carries the key and the API version')
    payload = wire.payload()
    check(payload.get('stream') is True, f'the request asks for a stream: {payload.get("stream")!r}')
    check(payload.get('model') == CLAUDE and payload.get('max_tokens') == 64000 and payload.get('system') == 'SYS',
          {k: payload.get(k) for k in ('model', 'max_tokens', 'system')})
    content = payload['messages'][0]['content']
    check(any(c.get('type') == 'text' and c.get('text') == 'USER' for c in content)
          and sum(c.get('type') == 'image' for c in content) == 2,
          f'the user prompt and both images go in the one message: {[c.get("type") for c in content]}')

    # Max tokens: the text that arrived comes back, but the reply is not complete.
    events = anthropic_events(parts, stop_reason='max_tokens', output_tokens=64000)
    with Wire(lambda r: Body(rechunk(events, 4))):
        cancel = ls.Cancel()
        out, _ = drain(lambda: _stream('anthropic', cancel))
    check(''.join(out) == TEXT, 'max tokens still yields what was written')
    usage = _usage(cancel)
    check(usage['complete'] is False and usage['output_tokens'] == 64000,
          f'a max-tokens stop is not complete: {usage}')

    # The connection drops mid-reply: no message_delta, no message_stop.
    events = anthropic_events(parts[:4], end=False)
    with Wire(lambda r: Body(rechunk(events, 5))):
        cancel = ls.Cancel()
        out, _ = drain(lambda: _stream('anthropic', cancel))
    check(''.join(out) == ''.join(parts[:4]), f'a dropped stream yields what arrived: {"".join(out)!r}')
    usage = _usage(cancel)
    check(usage['complete'] is False and usage['input_tokens'] == 1234 and usage['output_tokens'] is None,
          'a dropped stream is not complete and has no reported output (message_start\'s placeholder '
          f'output_tokens is not the reply\'s output): {usage}')


def gemini_sse_yields_text_and_usage():
    ls = _ls()
    parts = _pieces(TEXT, 11)
    events = gemini_events(parts, thought_parts=['**Reading the plan**\n\nThe sheet shows two levels.'])
    for seed in (1, 2, 3):
        with Wire(lambda r: Body(rechunk(events, seed))) as wire:
            cancel = ls.Cancel()
            out, error = drain(lambda: _stream('gemini', cancel, key='paid-k'))
        check(error is None, f'a complete stream ends cleanly: {error!r}')
        check(''.join(out) == TEXT, f'the answer text comes back whole (seed {seed}): {"".join(out)[:120]!r}')
        check(len(out) > 1, f'the answer arrives as deltas: {len(out)} pieces')
        usage = _usage(cancel)
        check(usage['input_tokens'] == 2100 and usage['output_tokens'] == 800 + 450 and usage['complete'] is True,
              f'input is promptTokenCount, output is candidates + thoughts (as llm._request_json counts '
              f'them), complete on finishReason STOP: {usage}')
    request = wire.requests[0]
    url = request.full_url
    check(len(wire.requests) == 1 and f'/models/{GEMINI}:streamGenerateContent' in url and 'alt=sse' in url,
          f'one streamGenerateContent?alt=sse request: {url}')
    check('key=paid-k' in url or request.get_header('X-goog-api-key') == 'paid-k', 'the request carries the key')
    payload = wire.payload()
    user_parts = payload['contents'][0]['parts']
    check(any('USER' in (p.get('text') or '') for p in user_parts)
          and sum('inline_data' in p or 'inlineData' in p for p in user_parts) == 2,
          f'the user prompt and both images go in the request: {[list(p) for p in user_parts]}')
    config = payload.get('generationConfig') or {}
    check(config.get('maxOutputTokens') == 64000, f'max output tokens is sent: {config}')
    check('SYS' in json.dumps(payload), 'the system prompt is sent')

    events = gemini_events(parts, finish='MAX_TOKENS')
    with Wire(lambda r: Body(rechunk(events, 6))):
        cancel = ls.Cancel()
        out, _ = drain(lambda: _stream('gemini', cancel, key='paid-k'))
    check(''.join(out) == TEXT, 'max tokens still yields what was written')
    check(_usage(cancel)['complete'] is False, f'finishReason MAX_TOKENS is not complete: {cancel.usage}')


def thinking_deltas_are_not_text():
    ls = _ls()
    decoy = '{"building":{"walls":[{"id":"thought-wall"}]}} not the answer'
    events = anthropic_events(_pieces(TEXT, 13), thinking_parts=[decoy[:20], decoy[20:]])
    with Wire(lambda r: Body(rechunk(events, 8))):
        cancel = ls.Cancel()
        out, error = drain(lambda: _stream('anthropic', cancel))
    joined = ''.join(out)
    check(error is None and joined == TEXT, f'Claude thinking_delta and signature_delta are not answer text: {joined[:160]!r}')
    check('thought-wall' not in joined, 'no thinking text leaks into the answer')

    events = gemini_events(_pieces(TEXT, 13), thought_parts=[decoy[:25], decoy[25:]])
    with Wire(lambda r: Body(rechunk(events, 9))):
        cancel = ls.Cancel()
        out, error = drain(lambda: _stream('gemini', cancel, key='paid-k'))
    joined = ''.join(out)
    check(error is None and joined == TEXT, f'Gemini parts marked thought are not answer text: {joined[:160]!r}')
    check('thought-wall' not in joined, 'no thought summary leaks into the answer')


def cancel_from_another_thread_ends_within_2s():
    ls = _ls()
    # attach() closes an attached response; attaching after a cancel closes at once.
    cancel, body = ls.Cancel(), Body([b'x'])
    cancel.attach(body)
    check(cancel.cancelled is False and not body.closed, 'attaching does not close')
    cancel.cancel()
    check(cancel.cancelled is True and body.closed, 'cancel() closes the attached response')
    late, body = ls.Cancel(), Body([b'x'])
    late.cancel()
    late.attach(body)
    check(body.closed, 'a response attached after cancel() is closed at once')

    parts = _pieces('{"building":{"walls":[' + ','.join(f'{{"id":"w{i}","from":[{i},0],"to":[{i},9]}}'
                                                        for i in range(40)) + ']}}', 17)
    for provider, closed_raises in (('anthropic', False), ('gemini', True)):
        if provider == 'anthropic':
            events = anthropic_events(parts, thinking_parts=['Measuring.'])
            first_text = next(i for i, (name, raw) in enumerate(events) if b'text_delta' in raw)
        else:
            events = gemini_events(parts)
            first_text = 0
        chunks, ends = halves(events)
        hold = ends[first_text + 1]  # the first two answer deltas have arrived; the rest is held
        body = Body(chunks, hold=hold, closed_raises=closed_raises)
        with Wire(lambda r: body):
            cancel = ls.Cancel()
            run = Run(lambda: _stream(provider, cancel, key='paid-k' if provider == 'gemini' else 'test-key'))
            check(run.first.wait(STOP_WITHIN),
                  f'{provider}: the first answer delta must arrive while the rest of the body is still open '
                  '(read lines as they come, never a fixed-size block)')
            check(body.waiting.wait(STOP_WITHIN), f'{provider}: the reader is blocked on the open body')
            started = time.monotonic()
            cancel.cancel()
            ended = run.done.wait(STOP_WITHIN)
            took = time.monotonic() - started
        check(ended, f'{provider}: the iterator must end within {STOP_WITHIN} s of cancel(); still running')
        check(took < STOP_WITHIN, f'{provider}: ended after {took:.2f} s')
        check(body.closed, f'{provider}: the response is closed so the provider stops generating')
        check(cancel.cancelled is True, 'cancelled reads true')
        got = ''.join(run.deltas)
        check(got and ''.join(parts[:2]).startswith(got),
              f'{provider}: only what arrived before Stop is yielded: {got!r}')
        usage = _usage(cancel)
        check(usage['complete'] is False, f'{provider}: a cancelled call is never complete: {usage}')
        if provider == 'anthropic':
            check(usage['input_tokens'] == 1234 and usage['output_tokens'] is None,
                  f'input from message_start; no output was reported before Stop: {usage}')


def cancel_before_first_byte_ends():
    ls = _ls()
    events = anthropic_events(_pieces(TEXT, 9))

    # A. Stop before the call starts.
    with Wire(lambda r: Body(rechunk(events, 1), hold=0)) as wire:
        cancel = ls.Cancel()
        cancel.cancel()
        run = Run(lambda: _stream('anthropic', cancel))
        check(run.done.wait(STOP_WITHIN), 'a call cancelled before it starts ends at once')
        check(run.deltas == [], f'nothing is yielded: {run.deltas}')
        check(all(b.closed for b in wire.bodies), 'any response it opened is closed')
    check(_usage(cancel)['complete'] is False, 'not complete')

    # B. Stop in the connect / time-to-first-byte window: urlopen itself is blocked.
    gate = threading.Event()
    body = Body(rechunk(events, 2), hold=0)
    with Wire(lambda r: body, gate=gate) as wire:
        cancel = ls.Cancel()
        run = Run(lambda: _stream('anthropic', cancel))
        check(wire.called.wait(STOP_WITHIN), 'the request was sent')
        started = time.monotonic()
        cancel.cancel()
        ended = run.done.wait(STOP_WITHIN)
        check(ended, f'Stop inside urlopen (before any byte) must end the iterator within {STOP_WITHIN} s '
                     f'(Review Focus 1); still waiting after {time.monotonic() - started:.2f} s')
        check(run.deltas == [], f'nothing is yielded: {run.deltas}')
        gate.set()  # the reply arrives after Stop
        check(wait_until(lambda: body.closed, STOP_WITHIN),
              'a reply that arrives after Stop is closed at once, so the provider stops generating')
    usage = _usage(cancel)
    check(usage['complete'] is False and usage['output_tokens'] in (None, 0),
          f'no output before the first byte: {usage}')

    # C. urlopen returned, the first read blocks.
    body = Body(rechunk(events, 3), hold=0)
    with Wire(lambda r: body):
        cancel = ls.Cancel()
        run = Run(lambda: _stream('anthropic', cancel))
        check(body.waiting.wait(STOP_WITHIN), 'the reader is waiting for the first byte')
        cancel.cancel()
        check(run.done.wait(STOP_WITHIN), f'Stop before the first byte ends the iterator within {STOP_WITHIN} s')
    check(run.deltas == [] and body.closed, f'nothing yielded and the body closed: {run.deltas}')
    check(_usage(cancel)['complete'] is False, 'not complete')

    # D. Through read_stream: Cancelled, and only the input is charged.
    _read_stream_fn(), _cancelled()
    _fresh_anthropic()
    before = len(tc.entries())
    gate = threading.Event()
    body = Body(rechunk(events, 4), hold=0)
    with Wire(lambda r: body, gate=gate) as wire:
        cancel = ls.Cancel()
        run = Run(lambda: _read_stream('draft', {'building': 'Main house'}, [img()], cancel=cancel,
                                       on_text=lambda d: None, run='r1', step='draft'))
        check(wire.called.wait(STOP_WITHIN), 'the request was sent')
        cancel.cancel()
        check(run.done.wait(STOP_WITHIN), f'read_stream ends within {STOP_WITHIN} s of a Stop before the first byte')
        gate.set()
    check(isinstance(run.error, _cancelled()), f'read_stream raises twin_reads.Cancelled: {run.error!r} {run.result!r}')
    added = tc.entries()[before:]
    check(len(added) == 1, f'the sent request is charged once: {added}')
    entry = added[0]
    check(entry['output_tokens'] == 0 and entry['input_tokens'] > 0 and entry['stage'] == 'step:draft'
          and entry['run'] == 'r1',
          f'Stop before the first byte charges the input only: {entry}')
    usd, _ = tc.price(entry['model'], entry['input_tokens'], 0)
    check(math.isclose(entry['usd'], usd), f'priced on input alone: {entry}')


def cancelled_call_charges_input_plus_produced_not_max():
    _fresh_anthropic()
    model = 'anthropic:' + CLAUDE
    row = {'model': model, 'input_tokens': 2000, 'output_tokens': None, 'images': 2,
           'prompt_chars': 40000, 'max_output_tokens': 64000}

    try:
        added = tc.record('step:draft', [dict(row)], 'r1', cancelled=True, produced_chars=4003)
    except TypeError as exc:
        raise AssertionError(f'twin_cost.record takes cancelled= and produced_chars=: {exc}') from None
    e = added[0]
    check(e['input_tokens'] == 2000 and e['output_tokens'] == 1000,
          f'a cancelled call is charged its input plus produced characters / 4: {e}')
    check(math.isclose(e['usd'], tc.price(model, 2000, 1000)[0]), f'priced on those tokens: {e}')

    e = tc.record('step:draft', [dict(row, input_tokens=None)], 'r1', cancelled=True, produced_chars=800)[0]
    check(e['input_tokens'] == 1600 * 2 + math.ceil(40000 / 4) and e['output_tokens'] == 200,
          f'unknown input is estimated as before; output is still produced / 4, never max: {e}')

    e = tc.record('step:draft', [dict(row, output_tokens=321)], 'r1', cancelled=True, produced_chars=8000)[0]
    check(e['output_tokens'] == 321, f'output the stream reported wins over the character estimate: {e}')

    e = tc.record('step:draft', [dict(row)], 'r1')[0]
    check(e['output_tokens'] == 64000, f'a call that was not cancelled and reported nothing still charges max: {e}')

    # Through read_stream: Stop after some text has arrived.
    ls = _ls()
    _read_stream_fn(), _cancelled()
    answer_text = json.dumps(recorded('draft-pool-house.json'))
    parts = _pieces(answer_text, 50)
    thinking = ['Reading the dimension strings on the first floor. ', 'The overall is 24 by 30.']
    events = anthropic_events(parts, thinking_parts=thinking)
    chunks, ends = halves(events)
    first_text = next(i for i, (name, raw) in enumerate(events) if b'text_delta' in raw)
    hold = ends[first_text + 9]  # ten answer deltas (500 characters) arrive, then the stream stalls
    body = Body(chunks, hold=hold)
    before = len(tc.entries())
    seen = []
    with Wire(lambda r: body):
        cancel = ls.Cancel()
        run = Run(lambda: _read_stream('draft', {'building': 'Pool house'}, [img(), img()], cancel=cancel,
                                       on_text=seen.append, run='r2', step='draft'))
        check(body.waiting.wait(STOP_WITHIN) and wait_until(lambda: len(''.join(seen)) >= 500, STOP_WITHIN),
              f'on_text receives the deltas as they arrive: {len("".join(seen))} characters')
        cancel.cancel()
        check(run.done.wait(STOP_WITHIN), f'read_stream ends within {STOP_WITHIN} s of Stop')
    check(isinstance(run.error, _cancelled()), f'read_stream raises twin_reads.Cancelled: {run.error!r} {run.result!r}')
    added = tc.entries()[before:]
    check(len(added) == 1, f'one ledger entry for the stopped call: {added}')
    e = added[0]
    produced = len(''.join(seen))
    everything = produced + len(''.join(thinking))
    check(e['model'] == model and e['input_tokens'] == 1234 and e['run'] == 'r2' and e['stage'] == 'step:draft',
          f'the input message_start reported is charged: {e}')
    check(produced // 4 <= e['output_tokens'] <= everything // 4 + 2,
          f'output is the characters produced / 4 ({produced} answer characters), never max_output_tokens: {e}')
    check(math.isclose(e['usd'], tc.price(model, 1234, e['output_tokens'])[0]), f'priced on those tokens: {e}')


def non_streaming_provider_yields_once_and_cancel_closes():
    ls = _ls()
    reply = {'id': 'resp_1', 'status': 'completed', 'usage': {'input_tokens': 100, 'output_tokens': 20},
             'output': [{'type': 'reasoning', 'summary': []},
                        {'type': 'message', 'role': 'assistant',
                         'content': [{'type': 'output_text', 'text': '  {"a": [1, 2]}\n'}]}]}
    with Wire(lambda r: Body([json.dumps(reply).encode('utf-8')])) as wire:
        cancel = ls.Cancel()
        out, error = drain(lambda: _stream('openai', cancel, model='gpt-6.1-sol', images=[]))
    check(error is None and out == ['{"a": [1, 2]}'], f'OpenAI reads blocking and yields the whole text once: {out!r} {error!r}')
    check(len(wire.requests) == 1 and wire.requests[0].full_url == llm.OPENAI_URL,
          'one request through the existing OpenAI path')
    check('stream' not in wire.payload() or wire.payload()['stream'] is False, 'OpenAI is not asked to stream')
    usage = _usage(cancel)
    check(usage['input_tokens'] == 100 and usage['output_tokens'] == 20 and usage['complete'] is True,
          f'the blocking reply\'s usage is reported: {usage}')

    body = Body([json.dumps(reply).encode('utf-8')], hold=0)
    with Wire(lambda r: body):
        cancel = ls.Cancel()
        run = Run(lambda: _stream('openai', cancel, model='gpt-6.1-sol', images=[]))
        check(body.waiting.wait(STOP_WITHIN), 'the blocking read is waiting on the reply')
        cancel.cancel()
        check(run.done.wait(STOP_WITHIN), f'Stop ends a blocking provider call within {STOP_WITHIN} s (Review Focus 5)')
    check(body.closed, 'Stop closes the blocking call\'s socket')
    check(run.deltas == [], f'nothing is yielded after Stop: {run.deltas}')
    check(_usage(cancel)['complete'] is False, 'a stopped blocking call is not complete')


def read_stream_validates_like_read():
    ls = _ls()
    rs = _read_stream_fn()
    answer = recorded('draft-main-house.json')
    context = {'building': 'Main house'}

    expected = _blocking_read('draft', answer, context)
    check('error' not in expected and expected.get('building', {}).get('levels'), 'the blocking read accepts the answer')

    text = json.dumps(answer)
    for label, written in (('compact', text), ('fenced', '```json\n' + json.dumps(answer, indent=1) + '\n```')):
        _fresh_anthropic()
        before = len(tc.entries())
        events = anthropic_events(_pieces(written, 97), thinking_parts=['Checking the strings.'])
        seen = []
        with Wire(lambda r: Body(rechunk(events, 11, top=4096))) as wire:
            out = rs('draft', context, [img(), img()], cancel=ls.Cancel(), on_text=seen.append, run='r1', step='draft')
        check(out == expected, f'{label}: read_stream returns what read returns for the same answer: '
                               f'{json.dumps(out)[:200]}')
        check(''.join(seen) == written and len(seen) > 1, f'{label}: on_text gets every delta in order')
        payload = wire.payload()
        check(len(wire.requests) == 1 and payload.get('stream') is True and payload['system'] == twin_reads.PROMPTS['draft']
              and payload['max_tokens'] == 64000 and payload['model'] == CLAUDE,
              f'{label}: one streamed request with the draft prompt and limit: '
              f'{ {k: payload.get(k) for k in ("stream", "max_tokens", "model")} }')
        user = next(c['text'] for c in payload['messages'][0]['content'] if c.get('type') == 'text')
        check(json.loads(user) == {'step': 'draft', 'context': context}, f'{label}: the same user prompt as read: {user[:120]}')
        check(sum(c.get('type') == 'image' for c in payload['messages'][0]['content']) == 2, 'both images are sent')
        added = tc.entries()[before:]
        check(len(added) == 1 and added[0]['stage'] == 'step:draft' and added[0]['run'] == 'r1'
              and added[0]['input_tokens'] == 1234 and added[0]['output_tokens'] == 5000
              and added[0]['basis'] == 'reported',
              f'{label}: one ledger entry from the reported usage: {added}')

    # An answer read rejects is rejected the same way.
    bad = {'building': {'walls': []}, 'notes': []}
    expected_bad = _blocking_read('draft', bad, context)
    _fresh_anthropic()
    with Wire(lambda r: Body(rechunk(anthropic_events(_pieces(json.dumps(bad), 20)), 12))):
        out = rs('draft', context, [img()], cancel=ls.Cancel(), on_text=lambda d: None, run='r1', step='draft')
    check('error' in expected_bad and out == expected_bad, f'an unusable answer is the same error as read: {out} vs {expected_bad}')

    # A max-tokens reply is a truncated draft, as read reports it.
    _fresh_anthropic()
    with Wire(lambda r: Body(rechunk(anthropic_events(_pieces(text[:4000], 200), stop_reason='max_tokens',
                                                      output_tokens=64000), 13))):
        out = rs('draft', context, [img()], cancel=ls.Cancel(), on_text=lambda d: None, run='r1', step='draft')
    check('error' in out and out.get('truncated') is True, f'a max-tokens stream is a truncated draft: {out}')

    # Gemini: same credentials choice as read (the twin tier's pro pool on the paid key).
    rooms = recorded('draft_rooms-pool-house.json')
    expected = _blocking_read('draft_rooms', rooms, {'building': 'Pool house'}, gemini=True)
    _fresh_gemini()
    model, _ = model_pools.credentials('twin', storage.get_settings())
    seen = []
    with Wire(lambda r: Body(rechunk(gemini_events(_pieces(json.dumps(rooms), 64), thought_parts=['Tracing rooms.'],
                                                   model=model), 14))) as wire:
        out = rs('draft_rooms', {'building': 'Pool house'}, [img()], cancel=ls.Cancel(), on_text=seen.append,
                 run='r3', step='draft_rooms')
    check(out == expected, f'Gemini: read_stream returns what read returns: {json.dumps(out)[:200]}')
    url = wire.requests[0].full_url
    check(f'/models/{model}:streamGenerateContent' in url and 'alt=sse' in url,
          f'Gemini: the twin pool\'s model, streamed: {url}')
    check('key=paid-k' in url or wire.requests[0].get_header('X-goog-api-key') == 'paid-k', 'the paid key bills it')
    check(''.join(seen) == json.dumps(rooms), 'Gemini: on_text gets the answer text, no thoughts')
    e = tc.entries()[-1]
    check(e['run'] == 'r3' and e['input_tokens'] == 2100 and e['output_tokens'] == 1250, f'Gemini usage is charged: {e}')


# ---------------------------------------------------------------- helpers using twin_reads

def _fresh_anthropic():
    model_pools.reset_cooldowns()
    storage.patch_settings({'house_twin_cost': None, 'llm_provider': 'anthropic',
                            'llm_anthropic_api_key': 'test-key', 'llm_gemini_paid_api_key': '',
                            'model_pool_pro': ''})


def _fresh_gemini():
    model_pools.reset_cooldowns()
    storage.patch_settings({'house_twin_cost': None, 'llm_provider': 'gemini', 'llm_anthropic_api_key': '',
                            'llm_gemini_paid_api_key': 'paid-k', 'model_pool_pro': GEMINI})


def _read_stream_fn():
    fn = getattr(twin_reads, 'read_stream', None)
    check(callable(fn), 'twin_reads.read_stream(kind, context, images, *, cancel, on_text, run, step) is missing')
    return fn


def _read_stream(*args, **kwargs):
    return _read_stream_fn()(*args, **kwargs)


def _cancelled():
    cls = getattr(twin_reads, 'Cancelled', None)
    check(isinstance(cls, type) and issubclass(cls, BaseException), 'twin_reads.Cancelled is missing')
    return cls


class _Pool:
    def __init__(self, answer):
        self.answer = answer

    def __call__(self, tier, api_key, system_prompt, user_prompt, **kw):
        if kw.get('usage') is not None:
            kw['usage'].append({'model': next(iter(tc.PRICES)), 'input_tokens': 1, 'output_tokens': 1})
        return copy.deepcopy(self.answer)


def _blocking_read(kind, answer, context, gemini=False):
    """What twin_reads.read returns for this answer (the model stubbed at the pool)."""
    (_fresh_gemini if gemini else _fresh_anthropic)()
    original = model_pools.call_pool_json
    model_pools.call_pool_json = _Pool(answer)
    try:
        return twin_reads.read(kind, [img()], context, run='r0', step=kind)
    finally:
        model_pools.call_pool_json = original


TESTS = [
    anthropic_sse_yields_text_and_usage,
    gemini_sse_yields_text_and_usage,
    thinking_deltas_are_not_text,
    cancel_from_another_thread_ends_within_2s,
    cancel_before_first_byte_ends,
    cancelled_call_charges_input_plus_produced_not_max,
    non_streaming_provider_yields_once_and_cancel_closes,
    read_stream_validates_like_read,
]


if __name__ == '__main__':
    passed = 0
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            print(f'FAIL {fn.__name__}: {type(exc).__name__}: {" ".join(str(exc).split())[:300]}')
            if not isinstance(exc, (AssertionError, ImportError)):
                traceback.print_exc(limit=4)
        else:
            passed += 1
            print(f'ok   {fn.__name__}')
    print(f'{passed}/{len(TESTS)} passed')
    sys.exit(0 if passed == len(TESTS) else 1)
