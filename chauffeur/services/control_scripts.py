"""Read what scripts and scenes affect, without following automation triggers."""
import threading
import time

from services import ha_api


_TTL = 300
_cache: dict[str, tuple[float, set[str], list[str]]] = {}
_cache_lock = threading.Lock()
_UNREAD = 'Home Assistant could not be read'
_OPAQUE = frozenset({
    'rest_command', 'shell_command', 'pyscript', 'python_script', 'hassio', 'conversation',
})
_IGNORED = frozenset({
    'delay', 'wait_template', 'wait_for_trigger', 'notify', 'tts',
    'persistent_notification', 'logbook', 'system_log', 'stop', 'variables', 'condition',
})
_TARGET_FIELDS = ('target', 'entity_id', 'device_id', 'area_id')


def clear_cache() -> None:
    """Refresh script analysis on demand as well as after its short TTL."""
    with _cache_lock:
        _cache.clear()


def _templated(value) -> bool:
    if isinstance(value, str):
        return '{{' in value
    if isinstance(value, dict):
        return any(_templated(item) for item in value.values())
    if isinstance(value, list):
        return any(_templated(item) for item in value)
    return False


def _actions(sequence):
    """Walk every possible branch, including repeat, choose and parallel actions."""
    if isinstance(sequence, list):
        for item in sequence:
            yield from _actions(item)
    elif isinstance(sequence, dict):
        yield sequence
        if any(key in sequence for key in _IGNORED):
            return
        for key in ('sequence', 'parallel', 'then', 'else', 'default', 'choose', 'repeat'):
            if key in sequence:
                yield from _actions(sequence[key])


def touched(entity_id: str) -> tuple[set[str], list[str]]:
    """Return leaf entity ids and unreadable reasons, cached per root for 300 s.

    Only complete root traversals are cached: caching a partial node while a
    cycle is in progress could hide effects when that node is requested later.
    """
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(entity_id)
        if cached is not None and now - cached[0] < _TTL:
            return set(cached[1]), list(cached[2])

    from services.control_rules import targets

    entities, reasons, visited = set(), [], set()

    def expand(data):
        for source in (data, data.get('data') or {}):
            if any(_templated(source.get(key)) for key in _TARGET_FIELDS):
                reasons.append('A template target could not be read')
                continue
            found = targets(source)
            if not found and any(source.get(key) for key in _TARGET_FIELDS):
                reasons.append('The target entities could not be read')
            yield from found

    def visit(eid):
        if eid in visited:
            return
        visited.add(eid)
        domain = eid.partition('.')[0]
        if domain not in ('script', 'scene'):
            entities.add(eid)
            return
        try:
            if domain == 'scene':
                attrs = (states.get(eid) or {}).get('attributes') or {}
                if 'entity_id' not in attrs:
                    reasons.append(_UNREAD)
                    return
                children = set(expand({'entity_id': attrs['entity_id']}))
            else:
                related = ha_api.ws_command('search/related', item_type='script', item_id=eid)
                children = set()
                if not isinstance(related, dict):
                    reasons.append(_UNREAD)
                else:
                    children.update(expand({
                        'entity_id': related.get('entity'), 'device_id': related.get('device'),
                        'area_id': related.get('area'),
                    }))
                    for key in ('script', 'scene'):
                        values = related.get(key) or []
                        if isinstance(values, str):
                            values = [values]
                        children.update(value if value.startswith(key + '.') else f'{key}.{value}'
                                        for value in values)

                config = ha_api.ws_command('script/config', entity_id=eid)
                if not isinstance(config, dict):
                    config = ha_api.get_script_config(eid.partition('.')[2])
                device_actions = False
                if config is not None:
                    for action in _actions(config.get('sequence') or []):
                        service = action.get('service', action.get('action', ''))
                        service_domain = service.partition('.')[0]
                        if service_domain in _IGNORED or any(key in action for key in _IGNORED):
                            continue
                        if service:
                            if service_domain in _OPAQUE or service_domain not in domains:
                                reasons.append(f'The {service_domain} action could not be read')
                            device_actions = True
                            if service_domain == 'script' and service not in (
                                'script.turn_on', 'script.turn_off', 'script.toggle', 'script.reload',
                            ):
                                children.add(service)
                        children.update(expand(action))
                if device_actions and not children:
                    reasons.append('The script has actions whose targets could not be read')
            for child in sorted(children):
                visit(child)
        except Exception:
            reasons.append(_UNREAD)

    try:
        if ha_api.mode() == 'unconfigured':
            reasons.append(_UNREAD)
        else:
            states = {row['entity_id']: row for row in ha_api.get_states()}
            domains = {eid.partition('.')[0] for eid in states} | {'script', 'scene'}
            visit(entity_id)
    except Exception:
        reasons.append(_UNREAD)
    reasons = list(dict.fromkeys(reasons))
    with _cache_lock:
        _cache[entity_id] = (now, set(entities), list(reasons))
    return entities, reasons


def unreadable_scripts() -> list[dict]:
    """Explain scripts that need every kind's permission on the rules page."""
    try:
        states = ha_api.get_states()
    except Exception:
        return []
    rows = []
    for state in states:
        eid = state.get('entity_id', '')
        if eid.startswith('script.'):
            _, reasons = touched(eid)
            if reasons:
                rows.append({
                    'entity_id': eid,
                    'name': (state.get('attributes') or {}).get('friendly_name') or eid,
                    'reason': '; '.join(reasons),
                })
    return rows
