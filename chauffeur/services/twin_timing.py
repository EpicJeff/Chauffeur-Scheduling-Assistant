"""Opt-in, request-local house edit spans (milliseconds, exclusive of children)."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

_active = ContextVar('twin_edit_timing', default=None)


@contextmanager
def collect():
    record = {name: 0.0 for name in ('lock', 'apply', 'normalize', 'round', 'read', 'response')}
    token = _active.set((record, []))
    try:
        yield record
    finally:
        _active.reset(token)


@contextmanager
def span(name):
    active = _active.get()
    if active is None:
        yield
        return
    record, stack = active
    frame = [perf_counter(), 0.0]
    stack.append(frame)
    try:
        yield
    finally:
        elapsed = perf_counter() - frame[0]
        stack.pop()
        record[name] = record.get(name, 0.0) + (elapsed - frame[1]) * 1000
        if stack:
            stack[-1][1] += elapsed


def timed(name):
    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            if _active.get() is None:
                return fn(*args, **kwargs)
            with span(name):
                return fn(*args, **kwargs)
        return run
    return decorate


def response(payload, timing, status_code=200):
    import json
    from starlette.responses import JSONResponse
    # Time the ordinary payload construction/serialization. The final encoding
    # includes these measurements, so cannot itself be included in its own span.
    with span('response'):
        result = JSONResponse(payload, status_code=status_code)
    measured = {key: round(value, 3) for key, value in timing.items()}
    # Encode the whole house once. Only the small metadata suffix is re-encoded
    # to find the byte count's fixed point; Unicode counts as its UTF-8 bytes.
    size = 0
    while True:
        suffix = (',"timing":' + json.dumps(measured, separators=(',', ':')) + ',"bytes":' + str(size) + '}').encode('utf-8')
        actual = len(result.body) - 1 + len(suffix)
        if size == actual:
            break
        size = actual
    result.body = result.body[:-1] + suffix
    result.headers['Content-Length'] = str(size)
    result.headers['Server-Timing'] = ', '.join(f'{name};dur={value:.3f}' for name, value in timing.items())
    return result
