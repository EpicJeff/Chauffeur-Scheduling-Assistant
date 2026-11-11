"""One Home Assistant state subscription, shared by the cache and live views."""
import json
import queue
import threading
import time

from services import ha_api

BACKOFF_BASE = 1.0
BACKOFF_MAX = 60.0
_TIMEOUT = 8
_lock = threading.Lock()
_thread = None
_halt = None
_connection = None
_subscribers = {}


def _connect(url):
    # Reuse the client already used by ha_api.ws_command; no extra dependency.
    from websockets.sync.client import connect
    return connect(url, open_timeout=_TIMEOUT, close_timeout=1, max_size=None)


def subscribe(entities=None):
    changes = queue.Queue(maxsize=256)
    with _lock:
        _subscribers[changes] = None if entities is None else frozenset(entities)
    return changes


def unsubscribe(changes):
    with _lock:
        _subscribers.pop(changes, None)


def _publish(data):
    entity_id = data.get('entity_id')
    state = data.get('new_state')
    if not isinstance(entity_id, str) or 'new_state' not in data:
        return
    if state is not None and not isinstance(state, dict):
        return
    with ha_api._cache_lock:
        rows = [row for row in ha_api._states_cache['data'] or []
                if row.get('entity_id') != entity_id]
        if state is not None:
            rows.append(state)
        ha_api._states_cache.update(data=rows, ts=time.time(), failed=False)
    change = {'entity_id': entity_id, 'state': state}
    with _lock:
        for changes, entities in _subscribers.items():
            if entities is not None and entity_id not in entities:
                continue
            # A sleeping browser cannot hold up HA or grow memory without limit.
            if changes.full():
                try:
                    changes.get_nowait()
                except queue.Empty:
                    pass
            changes.put_nowait(change)


def _listen(connection, token, halt):
    for _ in range(3):
        message = json.loads(connection.recv(timeout=_TIMEOUT))
        if halt.is_set():
            return
        if message.get('type') == 'auth_required':
            connection.send(json.dumps({'type': 'auth', 'access_token': token}))
        elif message.get('type') == 'auth_ok':
            break
        else:
            raise ConnectionError('Home Assistant authentication refused')
    else:
        raise ConnectionError('Home Assistant authentication timed out')
    connection.send(json.dumps({'id': 1, 'type': 'subscribe_events',
                                'event_type': 'state_changed'}))
    # A snapshot fills holes on first connect and after a restart. Subscribers
    # hear only actual changes, never this initial cache population.
    connection.send(json.dumps({'id': 2, 'type': 'get_states'}))
    while not halt.is_set():
        try:
            message = json.loads(connection.recv(timeout=1))
        except TimeoutError:
            continue
        if message.get('type') == 'result':
            if not message.get('success'):
                raise ConnectionError('Home Assistant subscription refused')
            if message.get('id') == 2 and isinstance(message.get('result'), list):
                with ha_api._cache_lock:
                    ha_api._states_cache.update(data=message['result'], ts=time.time(), failed=False)
        elif message.get('type') == 'event' and message.get('id') == 1:
            event = message.get('event') or {}
            if event.get('event_type') == 'state_changed' and isinstance(event.get('data'), dict):
                _publish(event['data'])


def _run(halt):
    global _connection
    delay = BACKOFF_BASE
    while not halt.is_set():
        connection = None
        connected_at = time.monotonic()
        try:
            url, token = ha_api._ws_url_and_token()
            if not url:
                return
            connection = _connect(url)
            with _lock:
                if halt.is_set():
                    return
                _connection = connection
            _listen(connection, token, halt)
        except Exception:
            # HA restarting, unavailable or unconfigured must never break startup.
            pass
        finally:
            with _lock:
                if _connection is connection:
                    _connection = None
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
        if time.monotonic() - connected_at >= 60:
            delay = BACKOFF_BASE
        if halt.wait(delay):
            return
        delay = min(BACKOFF_MAX, delay * 2)


def start():
    global _thread, _halt
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        try:
            url, _ = ha_api._ws_url_and_token()
        except Exception:
            return
        if not url:
            return
        _halt = threading.Event()
        _thread = threading.Thread(target=_run, args=(_halt,), name='ha-events', daemon=True)
        _thread.start()


def stop():
    with _lock:
        thread, connection = _thread, _connection
        if _halt is not None:
            _halt.set()
    if connection is not None:
        try:
            connection.close()
        except Exception:
            pass
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=_TIMEOUT + 2)
