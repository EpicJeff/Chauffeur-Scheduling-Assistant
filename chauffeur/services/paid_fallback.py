"""Persisted, capped paid-key relief for foreground free-tier throttles."""
import datetime
import logging
import threading
import time

from services import storage

logger = logging.getLogger(__name__)
_STATE_KEY = 'llm_paid_fallback'
_WINDOW = 30 * 60
_lock = threading.RLock()
_state = None


def notify_parents(text):
    """One Argyle DM to every parent, never to a child: paid spending is a
    parent's matter. Same path a mission's asks take (missions._dm_person).
    Never raises: a failed notice must not fail the chat turn that found
    the throttle."""
    logger.info('[paid-fallback] %s', text)
    try:
        from services.agent_tools_v2 import _post_chat_message
        argyle = storage.ensure_argyle_member()
        for m in storage.get_all_members():
            if m.get('role') == 'parent' and not m.get('system'):
                _post_chat_message(storage.get_or_create_dm(argyle['id'], m['id']), argyle, text)
    except Exception as e:
        logger.warning(f"[paid-fallback] parent notice failed: {e}")


def _save():
    storage.set_app_state(_STATE_KEY, _state)


def _load(now):
    """The state for `now`: a new local day resets the counters, old events
    fall out of the window, an expired activation ends. Written back only
    when something changed: this runs on every foreground call."""
    global _state
    if _state is None:
        _state = dict(storage.get_app_state(_STATE_KEY) or {})
    before = dict(_state, events=list(_state.get('events', [])))
    day = datetime.datetime.fromtimestamp(now).astimezone().date().isoformat()
    if _state.get('day') != day:
        _state.update(day=day, used_today=0, asked_today=False, notified_today=False,
                      until=0, activated_by=None)
    _state['events'] = [ts for ts in _state.get('events', []) if ts > now - _WINDOW]
    if now >= _state.get('until', 0):
        _state['until'] = 0
    if _state != before:
        _save()
    return _state


def _options(settings):
    from services import model_pools
    s = settings or {}
    mode = s.get('llm_paid_fallback_mode', 'ask')
    if mode not in ('off', 'ask', 'auto'):
        mode = 'ask'
    configured = mode != 'off' and bool(model_pools.api_key_for_pool('pro', s))
    return (configured, mode, max(1, int(s.get('llm_paid_fallback_failures', 3))),
            max(0, int(s.get('llm_paid_fallback_daily_cap', 300))))


def status(settings, now=None):
    now = time.time() if now is None else now
    with _lock:
        row = _load(now)
        configured, mode, threshold, cap = _options(settings)
        if (not configured or row['used_today'] >= cap) and row['until']:
            row['until'] = 0
            _save()
        return dict(configured=configured, mode=mode, threshold=threshold,
                    failures_recent=len(row['events']), active=row['until'] > now,
                    until=row['until'], used_today=row['used_today'], cap=cap,
                    asked_today=row['asked_today'], activated_by=row['activated_by'])


def activate(settings, now=None, by='parent'):
    now = time.time() if now is None else now
    if by not in ('parent', 'auto'):
        raise ValueError('Activation must be by parent or auto')
    with _lock:
        st = status(settings, now)
        if not st['configured'] or st['used_today'] >= st['cap']:
            return 0
        local = datetime.datetime.fromtimestamp(now).astimezone()
        midnight = (local + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        _state.update(until=midnight.timestamp(), activated_by=by)
        _save()
        return _state['until']


def deactivate():
    with _lock:
        global _state
        if _state is None:
            _state = dict(storage.get_app_state(_STATE_KEY) or {})
        _state['until'] = 0
        _save()


def note_throttle(settings, now=None):
    now = time.time() if now is None else now
    with _lock:
        st = status(settings, now)
        if not st['configured']:
            return None
        _state['events'].append(now)
        _save()
        failures = len(_state['events'])
        if failures < st['threshold'] or st['active']:
            return None
        if st['mode'] == 'auto':
            until = activate(settings, now, by='auto')
            if not until:
                return None
            if not _state['notified_today']:
                _state['notified_today'] = True
                _save()
                notify_parents(f'The free tier is throttled; paid fallback is on until '
                               f'local midnight, with a daily cap of {st["cap"]} requests.')
            return {'action': 'activated', 'until': until}
        if not _state['asked_today']:
            _state['asked_today'] = True
            _save()
            notify_parents(f'The free tier failed {failures} times in the last 30 minutes. '
                           'Would you like to switch on paid fallback until midnight?')
            return {'action': 'ask'}
        return None


def count_call(settings, now=None):
    """Reserve one paid provider request atomically, including failed requests."""
    now = time.time() if now is None else now
    with _lock:
        st = status(settings, now)
        if not st['active']:
            return False
        _state['used_today'] += 1
        if _state['used_today'] >= st['cap']:
            _state['until'] = 0
        _save()
        return True


def reset(memory_only=False):
    """Test hook: discard the cache, optionally retaining persisted state."""
    global _state
    with _lock:
        _state = None
        if not memory_only:
            storage.set_app_state(_STATE_KEY, {})
