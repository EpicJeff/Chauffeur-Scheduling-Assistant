"""One Home Assistant state subscription, shared by the cache and live views."""
import json
import logging
import queue
import threading
import time

from services import ha_api

log = logging.getLogger('chauffeur.ha_events')

BACKOFF_BASE = 1.0
BACKOFF_MAX = 60.0
_TIMEOUT = 8
_lock = threading.Lock()
_thread = None
_halt = None
_connection = None
_subscribers = {}
# Where each entity sits in ha_api's cached list, for the list it was built
# from (review L2): a push replaces one row in place instead of copying the house.
_index = {'rows': None, 'at': {}}
# The last failure said in the log; a new reason is said once (review L1).
_said = {'reason': None}


def _connect(url):
    # Reuse the client already used by ha_api.ws_command; no extra dependency.
    from websockets.sync.client import connect
    return connect(url, open_timeout=_TIMEOUT, close_timeout=1, max_size=None)


def subscribe(entities=None, wake=None):
    """A queue of changes for `entities` (every entity when None). `wake`, when
    given, is called (from the client's thread) after each change is queued, so
    an async reader can sleep until there is something to read (review L11)."""
    changes = queue.Queue(maxsize=256)
    with _lock:
        _subscribers[changes] = (None if entities is None else frozenset(entities), wake)
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
        _remember(entity_id, state)
    with _lock:
        listening = [(changes, wake) for changes, (entities, wake) in _subscribers.items()
                     if entities is None or entity_id in entities]
    if not listening:
        return
    # A camera's tokens stay in the cache above and never reach a page (C9).
    change = {'entity_id': entity_id, 'state': ha_api.public_state(state)}
    for changes, wake in listening:
        # A sleeping browser cannot hold up HA or grow memory without limit.
        if changes.full():
            try:
                changes.get_nowait()
            except queue.Empty:
                pass
        try:
            changes.put_nowait(change)
        except queue.Full:
            continue
        if wake is not None:
            try:
                wake()
            except Exception:
                pass


def _remember(entity_id, state):
    """Write one change into ha_api's states cache; the caller holds its lock.

    The row is replaced where it stands (no copy of the whole house per change);
    the index is rebuilt only when the cache holds a list it was not built
    from. A removed entity copies the list once, so a reader iterating the old
    one never skips a row."""
    rows = ha_api._states_cache.get('data')
    if not isinstance(rows, list):
        rows = []
        ha_api._states_cache['data'] = rows
    if _index['rows'] is not rows:
        _index['rows'] = rows
        _index['at'] = {row.get('entity_id'): i for i, row in enumerate(rows) if isinstance(row, dict)}
    at = _index['at'].get(entity_id)
    if at is not None and (at >= len(rows) or rows[at].get('entity_id') != entity_id):
        _index['at'] = {row.get('entity_id'): i for i, row in enumerate(rows) if isinstance(row, dict)}
        at = _index['at'].get(entity_id)
    if state is None:
        if at is not None:
            rows = rows[:at] + rows[at + 1:]
            ha_api._states_cache['data'] = rows
            _index['rows'] = rows
            _index['at'] = {row.get('entity_id'): i for i, row in enumerate(rows) if isinstance(row, dict)}
    elif at is None:
        _index['at'][entity_id] = len(rows)
        rows.append(state)
    else:
        rows[at] = state
    ha_api._states_cache.update(ts=time.time(), failed=False)


def _say(error):
    reason = f'{type(error).__name__}: {error}'[:200]
    if reason == _said['reason']:
        return
    _said['reason'] = reason
    log.warning('Home Assistant state stream: %s; retrying with back-off', reason)


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
            if message.get('id') == 1:
                _said['reason'] = None      # subscribed: the next failure is news again
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
        except Exception as error:
            # HA restarting, unavailable or unconfigured must never break startup,
            # but a failure that keeps happening (a refused token) is said, once
            # per reason, never once per attempt (review L1).
            if not halt.is_set():
                _say(error)
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


def restart():
    """Home Assistant's address or token was saved (review L3): drop any client
    holding the old ones and start one on the new, or none when HA is gone."""
    stop()
    _said['reason'] = None
    start()
