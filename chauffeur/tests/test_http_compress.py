"""Selective gzip: JSON shrinks, live streams are never touched.

The app had no compression at all, discovered while measuring why shipping
`hass.states` to hosted cards felt expensive (it never was: 29.5 KB of state
JSON gzips to 1.0 KB). The dangerous part of fixing that is the reason it was
never simply `GZipMiddleware`: this app streams for a living, and gzip
buffering a live SSE stream means a chat message sitting in a compressor
while the client sees nothing.

So the middleware's rule is structural — single-shot responses compress,
anything that sends more than one body frame passes through by construction —
and these scenarios drive real ASGI message sequences through it to pin both
halves.

Run from chauffeur/:  python tests/test_http_compress.py
"""
import asyncio
import gzip
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_gzip_'))

from services.http_compress import SelectiveGzipMiddleware  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _scope(accept='gzip, deflate'):
    return {'type': 'http', 'method': 'GET', 'path': '/x',
            'headers': [(b'accept-encoding', accept.encode())] if accept else []}


def _single_shot(ctype, body):
    async def app(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200,
                    'headers': [(b'content-type', ctype),
                                (b'content-length', str(len(body)).encode())]})
        await send({'type': 'http.response.body', 'body': body})
    return app


def _sse(events):
    async def app(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200,
                    'headers': [(b'content-type', b'text/event-stream')]})
        for e in events:
            await send({'type': 'http.response.body', 'body': e,
                        'more_body': True})
        await send({'type': 'http.response.body', 'body': b''})
    return app


def _run(app, scope):
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {'type': 'http.request'}

    asyncio.run(SelectiveGzipMiddleware(app)(scope, receive, send))
    return sent


def _headers(sent):
    return dict(sent[0]['headers'])


def scenario_a_fat_json_response_shrinks():
    body = json.dumps({'states': {('media_player.s%d' % i): {
        'state': 'idle', 'attributes': {'friendly_name': 'Speaker %d' % i}}
        for i in range(50)}}).encode()
    sent = _run(_single_shot(b'application/json', body), _scope())
    h = _headers(sent)
    check(h.get(b'content-encoding') == b'gzip', "state JSON left uncompressed")
    out = sent[1]['body']
    check(len(out) < len(body) / 5, "barely compressed: %d -> %d" % (len(body), len(out)))
    check(gzip.decompress(out) == body, "the payload did not survive the round trip")
    check(int(h[b'content-length']) == len(out), "content-length lies about the gzip body")
    check(h.get(b'vary') == b'Accept-Encoding',
          "no Vary — a cache could hand gzip to a client that never asked")


def scenario_an_event_stream_is_never_buffered():
    """The half that matters. Every frame must come out exactly as it went
    in, the moment it went in — a compressor holding frame one until frame
    three fills its block is a messaging outage wearing a bandwidth win."""
    events = [b'data: one\n\n', b'data: two\n\n', b'data: three\n\n']
    sent = _run(_sse(events), _scope())
    h = _headers(sent)
    check(b'content-encoding' not in h, "gzip wrapped a live event stream")
    bodies = [m.get('body', b'') for m in sent[1:]]
    check(bodies[:3] == events, "stream frames were altered or held: %r" % bodies)


def scenario_a_client_that_never_asked_gets_plain_bytes():
    body = b'{"k": "' + b'v' * 2000 + b'"}'
    sent = _run(_single_shot(b'application/json', body), _scope(accept=''))
    check(b'content-encoding' not in _headers(sent),
          "compressed for a client with no Accept-Encoding: gzip")
    check(sent[1]['body'] == body, "the body was altered anyway")


def scenario_small_and_binary_bodies_pass_through():
    tiny = _run(_single_shot(b'application/json', b'{"ok": true}'), _scope())
    check(b'content-encoding' not in _headers(tiny),
          "a 12-byte body was wrapped in a header bigger than itself")
    png = b'\x89PNG' + b'\x00' * 4000
    sent = _run(_single_shot(b'image/png', png), _scope())
    check(b'content-encoding' not in _headers(sent),
          "recompressing an image wastes CPU to make it bigger")


def scenario_already_encoded_responses_are_left_alone():
    body = gzip.compress(b'x' * 4000)
    async def app(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200,
                    'headers': [(b'content-type', b'application/json'),
                                (b'content-encoding', b'gzip')]})
        await send({'type': 'http.response.body', 'body': body})
    sent = _run(app, _scope())
    check(sent[1]['body'] == body, "double-gzipped a response")


def scenario_the_app_actually_installs_it():
    """A middleware that exists and is not added compresses nothing —
    the saved-and-never-read failure this codebase has shipped before."""
    import main
    names = [getattr(m, 'cls', type(None)).__name__ for m in main.app.user_middleware]
    check('SelectiveGzipMiddleware' in names,
          "main.app never adds the compression middleware: %r" % names)


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print("  ok  %s" % fn.__name__)
    print("\n%d/%d gzip scenarios passed" % (len(SCENARIOS), len(SCENARIOS)))
