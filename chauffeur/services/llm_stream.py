"""Cancellable urllib model reads. Only answer text leaves the transport."""
from contextvars import copy_context
import json
import queue
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

from services import llm, llm_budget


def _close(resp, *, owner=False):
    # HTTPResponse.close alone can wait on a buffered reader's recv lock.
    # Walk urllib's wrappers and shut down the socket before closing the file.
    pending, seen, has_socket = [resp], set(), False
    while pending:
        obj = pending.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        if isinstance(obj, socket.socket):
            has_socket = True
            try:
                obj.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            # A makefile keeps the descriptor alive after socket.close(). On
            # Windows, shutdown alone can also leave its pending recv asleep.
            # Detach invalidates the Python socket before closing the handle.
            if sys.platform == 'win32':
                try:
                    descriptor = obj.detach()
                    if descriptor >= 0:
                        socket.close(descriptor)
                except OSError:
                    pass
        for name in ('fp', 'raw', '_sock', 'sock'):
            child = getattr(obj, name, None)
            if child is not None:
                pending.append(child)
    # On Unix the reader owns close; shutdown wakes it without recycling a
    # descriptor that OpenSSL may still be using on another thread.
    if owner or not has_socket or sys.platform == 'win32':
        try:
            resp.close()
        except (OSError, ValueError):
            pass


class Cancel:
    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._response = None
        self._socket = None
        self.usage = {'input_tokens': None, 'output_tokens': None, 'complete': False}
        self.produced_chars = 0

    @property
    def cancelled(self):
        return self._event.is_set()

    def cancel(self):
        with self._lock:
            self._event.set()
            self.usage['complete'] = False
            resp = self._response
            sock = self._socket
        def close():
            if sock is not None:
                _close(sock)
            if resp is not None:
                _close(resp)
        threading.Thread(target=close, daemon=True).start()

    def reset(self):
        with self._lock:
            self.usage = {'input_tokens': None, 'output_tokens': None, 'complete': False}
            self.produced_chars = 0
            self._response = self._socket = None

    def before_connect(self):
        self.usage['dispatched'] = False
        if self.cancelled:
            raise RuntimeError('Model call cancelled.')

    def before_send(self):
        if self.cancelled:
            raise RuntimeError('Model call cancelled.')
        self.usage['dispatched'] = True

    def attach_socket(self, sock):
        with self._lock:
            self._socket = sock
            cancelled = self.cancelled
        if cancelled:
            _close(sock)
            raise RuntimeError('Model call cancelled.')

    def attach(self, resp):
        with self._lock:
            self._response = resp
            cancelled = self.cancelled
        if cancelled:
            _close(resp)


def _request(provider, api_key, model, system, user, images, limit, thinking):
    headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
    if provider == 'anthropic':
        content = [{'type': 'text', 'text': user}]
        content.extend({'type': 'image', 'source': {
            'type': 'base64', 'media_type': img.get('mime') or 'image/jpeg', 'data': img['b64']}}
            for img in images or [])
        payload = {'model': model, 'max_tokens': limit, 'stream': True, 'system': system,
                   'messages': [{'role': 'user', 'content': content}],
                   'output_config': {'effort': llm.effort_for(model, thinking, llm._is_pro(model))}}
        url = llm.ANTHROPIC_URL
        headers.update({'x-api-key': api_key, 'anthropic-version': '2023-06-01'})
    else:
        model = model.removeprefix('models/')
        url = ('https://generativelanguage.googleapis.com/v1beta/models/' + model
               + ':streamGenerateContent?alt=sse&' + urllib.parse.urlencode({'key': api_key}))
        parts = [{'text': f'{system}\n\nUser Request: {user}'}]
        parts.extend({'inline_data': {'mime_type': img.get('mime') or 'image/jpeg', 'data': img['b64']}}
                     for img in images or [])
        config = {'maxOutputTokens': limit, 'responseMimeType': 'application/json', 'temperature': 0.1}
        if thinking is not None:
            config['thinkingConfig'] = (
                {'thinkingBudget': {'low': 1024, 'medium': 4096, 'high': 8192}.get(thinking, 1024)}
                if model.startswith('gemini-2.5-') else {'thinkingLevel': thinking})
        payload = {'contents': [{'role': 'user', 'parts': parts}], 'generationConfig': config}
    return urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')


def _events(resp):
    data = []
    while True:
        line = resp.readline()
        if not line:
            break
        line = line.decode('utf-8').rstrip('\r\n')
        if not line:
            if data:
                yield json.loads('\n'.join(data))
                data = []
        elif line.startswith('data:'):
            data.append(line[5:].lstrip(' '))
    if data:
        yield json.loads('\n'.join(data))


def _deltas(provider, event, cancel):
    usage = cancel.usage
    if provider == 'anthropic':
        kind = event.get('type')
        if kind == 'message_start':
            usage['input_tokens'] = (event.get('message', {}).get('usage') or {}).get('input_tokens')
        elif kind == 'message_delta':
            if 'output_tokens' in (event.get('usage') or {}):
                usage['output_tokens'] = event['usage']['output_tokens']
            usage['finish_reason'] = (event.get('delta') or {}).get('stop_reason')
        elif kind == 'message_stop':
            usage['complete'] = usage.get('finish_reason') == 'end_turn'
        elif kind == 'content_block_delta':
            delta = event.get('delta') or {}
            cancel.produced_chars += len(delta.get('text', '') or delta.get('thinking', ''))
            if delta.get('type') == 'text_delta' and delta.get('text'):
                yield delta['text']
        elif kind == 'error':
            raise RuntimeError((event.get('error') or {}).get('message', 'Model stream failed.'))
    else:
        reported = event.get('usageMetadata') or {}
        if 'promptTokenCount' in reported:
            usage['input_tokens'] = reported['promptTokenCount']
        if 'candidatesTokenCount' in reported or 'thoughtsTokenCount' in reported:
            usage['output_tokens'] = reported.get('candidatesTokenCount', 0) + reported.get('thoughtsTokenCount', 0)
        candidate = (event.get('candidates') or [{}])[0]
        if 'finishReason' in candidate:
            usage['finish_reason'] = candidate['finishReason']
            usage['complete'] = candidate['finishReason'] == 'STOP'
        for part in (candidate.get('content') or {}).get('parts', []):
            text = part.get('text', '')
            cancel.produced_chars += len(text)
            if text and not part.get('thought'):
                yield text


def stream_json(provider, url, api_key, model, system_prompt, user_prompt, *,
                images, max_output_tokens, thinking_level, timeout_s, cancel, strict_json='lenient'):
    """Yield live answer deltas, or one answer for a blocking provider.

    The worker owns connect and reads; the consumer never waits on socket I/O.
    A late response is attached (and closed) even after the consumer has left.
    """
    cancel.reset()
    if cancel.cancelled:
        return
    events = queue.Queue(maxsize=32)
    done = threading.Event()

    def send(kind, value):
        while not done.is_set() and not cancel.cancelled:
            try:
                events.put((kind, value), timeout=0.05)
                return
            except queue.Full:
                pass

    def work():
        resp = None
        metrics = {}
        try:
            if cancel.cancelled:
                return
            cancel.usage['dispatched'] = True
            if provider in ('anthropic', 'gemini'):
                req = _request(provider, api_key, model, system_prompt, user_prompt,
                               images, max_output_tokens, thinking_level)
                resp = llm_budget.urlopen(req, timeout=timeout_s, connection_hook=cancel)
                cancel.attach(resp)
                if not cancel.cancelled and not done.is_set():
                    for event in _events(resp):
                        send('event', event)
                        if done.is_set() or cancel.cancelled:
                            break
            else:
                with llm.cancel_requests(cancel):
                    answer = llm._call_llm_json(
                        provider, url, api_key, model, system_prompt, user_prompt, images=images,
                        max_output_tokens=max_output_tokens, thinking_level=thinking_level,
                        timeout_s=timeout_s, transient_retries=0, metrics=metrics, text=True,
                        strict_json=strict_json)
                send('answer', (answer, metrics))
        except llm_budget.Deferred as exc:
            cancel.usage['dispatched'] = False
            send('error', exc)
        except Exception as exc:
            if isinstance(exc, urllib.error.HTTPError):
                metrics['http_status'] = exc.code
                body = exc.read().decode('utf-8', errors='replace')
                exc = RuntimeError(f'{exc}\nDetails: {body}')
            send('error', (exc, metrics))
        finally:
            if resp is not None:
                _close(resp, owner=True)
            send('end', None)

    context = copy_context()
    threading.Thread(target=lambda: context.run(work), daemon=True).start()
    try:
        while not cancel.cancelled:
            try:
                kind, value = events.get(timeout=0.05)
            except queue.Empty:
                continue
            if cancel.cancelled or kind == 'end':
                break
            if kind == 'error':
                if isinstance(value, tuple):
                    value, metrics = value
                    for source, target in (('http_status', 'http_status'),
                                           ('promptTokenCount', 'input_tokens'),
                                           ('candidatesTokenCount', 'output_tokens'),
                                           ('finish_reason', 'finish_reason')):
                        if source in metrics:
                            cancel.usage[target] = metrics[source]
                cancel.usage['complete'] = False
                if isinstance(value, urllib.error.HTTPError):
                    cancel.usage['http_status'] = value.code
                raise value
            if kind == 'event':
                yield from _deltas(provider, value, cancel)
            else:
                answer, metrics = value
                cancel.usage.update(input_tokens=metrics.get('promptTokenCount'),
                                    output_tokens=metrics.get('candidatesTokenCount'),
                                    complete=metrics.get('finish_reason') in ('completed', 'stop', 'end_turn'),
                                    finish_reason=metrics.get('finish_reason'))
                if metrics.get('http_status'):
                    cancel.usage['http_status'] = metrics['http_status']
                if 'error' in answer:
                    raise RuntimeError(answer['error'])
                text = answer.get('text', '')
                cancel.produced_chars += len(text)
                if text:
                    yield text
    finally:
        done.set()
        if cancel._response is not None and not cancel.cancelled:
            _close(cancel._response)
        if cancel.cancelled:
            cancel.usage['complete'] = False
