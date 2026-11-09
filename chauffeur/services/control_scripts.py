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
_TARGET_FIELDS = ('target', 'entity_id', 'device_id', 'area_id', 'floor_id', 'label_id')


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

    from services.control_rules import NEVER_DOMAINS, kind_of, targets

    entities, reasons, visited = set(), [], set()

    def named_targets(value):
        ids = [value] if isinstance(value, str) else value or []
        for eid in ids:
            if eid != 'all' and kind_of(eid, None) is None:
                reasons.append(f'The directly named target {eid} could not be classified.')

    def expand(data, domain=None, direct=False):
        found = set()
        for source in (data, data.get('data') or {}):
            if any(_templated(source.get(key)) for key in _TARGET_FIELDS):
                reasons.append('A template target could not be read')
                continue
            if direct:
                named_targets(source.get('entity_id'))
                named_targets((source.get('target') or {}).get('entity_id'))
            try:
                found.update(targets(source, domain=domain))
            except ValueError as exc:
                reasons.append(str(exc))
        return found

    def action_targets(action):
        if 'scene' in action:
            action = {**action, 'service': 'scene.turn_on',
                      'target': {**(action.get('target') or {}), 'entity_id': action['scene']}}
        service = action.get('service', action.get('action', ''))
        service_domain = service.partition('.')[0]
        if service_domain in _IGNORED or any(key in action for key in _IGNORED):
            return set()
        if 'data_template' in action:
            reasons.append('The legacy data_template steps could not be read.')
        if 'service_template' in action:
            reasons.append('The legacy service_template step could not be read.')

        device_action = 'type' in action and 'device_id' in action and 'domain' in action
        if device_action:
            service_domain = action['domain']
        generic = service in ('homeassistant.turn_on', 'homeassistant.turn_off',
                              'homeassistant.toggle')
        if service or device_action:
            if not generic and (service_domain in _OPAQUE or service_domain in NEVER_DOMAINS
                                or service_domain not in domains):
                reasons.append(f'The {service_domain} action could not be read')

        if device_action:
            # Device automations name an entity-registry UUID, not an entity id.
            selection = {key: value for key, value in action.items() if key != 'entity_id'}
            if '.' in (action.get('entity_id') or ''):
                named_targets(action['entity_id'])
        else:
            selection = action
        found = expand(selection, domain=None if generic else service_domain or None, direct=True)
        if device_action:
            named_targets(found)
        if service_domain == 'script' and service and service not in (
            'script.turn_on', 'script.turn_off', 'script.toggle', 'script.reload',
        ):
            found.add(service)
        if service in ('scene.apply', 'scene.create'):
            scene_entities = (action.get('data') or {}).get('entities')
            if isinstance(scene_entities, dict):
                found.update(expand({'entity_id': list(scene_entities)}, direct=True))
            elif scene_entities is not None:
                reasons.append('The scene entities could not be read.')
        if (service or device_action) and not found:
            reasons.append(f'The {service or service_domain} action has targets that could not be read.')
        return found

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
                children = expand({'entity_id': attrs['entity_id']}, direct=True)
            else:
                related = ha_api.ws_command('search/related', item_type='script', item_id=eid)
                children = set()
                if not isinstance(related, dict):
                    reasons.append(_UNREAD)
                else:
                    # Search also returns the room/device owning each reference;
                    # those are not targets of the script's service calls.
                    children.update(expand({'entity_id': related.get('entity')}))
                    for key in ('script', 'scene'):
                        values = related.get(key) or []
                        if isinstance(values, str):
                            values = [values]
                        children.update(value if value.startswith(key + '.') else f'{key}.{value}'
                                        for value in values)

                config = ha_api.ws_command('script/config', entity_id=eid)
                if isinstance(config, dict) and 'config' in config:
                    config = config['config']
                if config is None:
                    config = ha_api.get_script_config(eid.partition('.')[2])
                if not isinstance(config, dict) or not isinstance(config.get('sequence'), (list, dict)):
                    reasons.append("The script's steps could not be read.")
                else:
                    for action in _actions(config['sequence']):
                        children.update(action_targets(action))
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
