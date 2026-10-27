"""Home Assistant device discovery, open reads and permission-checked control."""
import re
import time
from difflib import SequenceMatcher

from services import ha_api, storage


def _settle():
    time.sleep(0.6)


def _words(value):
    return ' '.join(re.findall(r'\w+', str(value or '').casefold().replace('_', ' ')))


def _catalogue():
    registry = {r['entity_id']: r for r in ha_api.get_entity_registry()}
    areas = ha_api.get_area_map()
    area_names = {a['id']: a['name'] for a in areas}
    entity_areas = {eid: a['name'] for a in areas for eid in a.get('entities', [])}
    states = ha_api.get_states()
    # area_entities() normally includes device inheritance. Only fetch the
    # device registry when the template map leaves an entity without an area.
    devices = {}
    if any(s.get('entity_id') not in entity_areas
           and registry.get(s.get('entity_id'), {}).get('device_id') for s in states):
        devices = {d['id']: d for d in ha_api.get_device_registry()}
    out = []
    for state in states:
        eid = state.get('entity_id', '')
        if not eid or '.' not in eid:
            continue
        row = registry.get(eid, {})
        if row.get('hidden_by') or row.get('disabled_by'):
            continue
        attrs = state.get('attributes') or {}
        name = attrs.get('friendly_name') or row.get('name') or row.get('original_name') or eid
        area_id = row.get('area_id') or devices.get(row.get('device_id'), {}).get('area_id')
        out.append({'entity_id': eid, 'name': name,
                    'area': entity_areas.get(eid) or area_names.get(area_id, ''),
                    'domain': eid.split('.', 1)[0], 'state': state.get('state'),
                    'aliases': list(row.get('aliases') or []), '_state': state,
                    '_device_id': row.get('device_id'),
                    '_names': [name, row.get('name'), row.get('original_name'),
                               *list(row.get('aliases') or []), eid, eid.split('.', 1)[1]]})
    return out


def _candidate(entity):
    return {**{k: entity[k] for k in ('entity_id', 'name', 'domain', 'state', 'aliases')},
            'ha_area': entity['area']}


def _score(query, names):
    tokens = set(query.split())
    best = 0.0
    for name in names:
        name = _words(name)
        if not name:
            continue
        if query == name:
            return 1.0
        overlap = len(tokens & set(name.split())) / max(len(tokens), len(set(name.split())))
        best = max(best, 0.65 * overlap + 0.35 * SequenceMatcher(None, query, name).ratio())
    return best


def _rank(catalogue, query, domain=''):
    query = _words(query)
    if not query:
        return []
    pool = [e for e in catalogue if not domain or e['domain'] == domain]
    area_matches = [e for e in pool if _words(e['area']) == query]
    if area_matches:
        domain_order = {domain: i for i, domain in enumerate((
            'cover', 'lock', 'light', 'switch', 'fan', 'media_player', 'climate',
            'alarm_control_panel', 'device_tracker'))}
        return sorted(((_score(query, e['_names']), e) for e in area_matches),
                      key=lambda pair: (domain_order.get(pair[1]['domain'],
                                        10 if pair[1]['domain'] in ('sensor', 'binary_sensor') else 9),
                                        -pair[0], pair[1]['entity_id']))[:8]
    ranked = [(max(_score(query, e['_names']), _score(query, [e['area']])), e) for e in pool]
    return sorted(((score, e) for score, e in ranked if score >= 0.45),
                  key=lambda pair: (-pair[0], pair[1]['entity_id']))[:8]


def find(query, domain='', catalogue=None):
    ranked = _rank(_catalogue() if catalogue is None else catalogue, query, domain)
    return {'status': 'success', 'candidates': [_candidate(e) for _, e in ranked]}


def resolve(query='', entity_id='', domain='', catalogue=None):
    catalogue = _catalogue() if catalogue is None else catalogue
    wanted = entity_id or query
    exact = next((e for e in catalogue if e['entity_id'] == wanted
                  and (not domain or e['domain'] == domain)), None)
    if exact:
        return exact
    if entity_id:
        return {'status': 'error', 'message': 'That Home Assistant entity is not available.'}
    ranked = _rank(catalogue, query, domain)
    # An area alone is discovery, even when its name resembles a device.
    strong = [e for _, e in ranked if _score(_words(query), e['_names']) >= 0.8]
    if len(strong) == 1:
        return strong[0]
    if ranked:
        return {'status': 'ambiguous', 'candidates': [_candidate(e) for _, e in ranked],
                'message': 'Which device do you mean?'}
    return {'status': 'error', 'message': 'No matching Home Assistant device was found.'}


def _brightness(state):
    attrs = state.get('attributes') or {}
    return {'brightness_pct': round(attrs['brightness'] * 100 / 255)} if 'brightness' in attrs else {}


def _read(entity):
    state = entity['_state']
    attributes = {}
    for key, value in (state.get('attributes') or {}).items():
        if key in ('access_token', 'token', 'entity_picture', 'id') or key.endswith('_token'):
            continue
        attributes[key] = value
        if len(attributes) == 30:
            break
    return {'status': 'success', 'entity': {
        'entity_id': entity['entity_id'], 'name': entity['name'], 'ha_area': entity['area'],
        'state': state.get('state'), 'attributes': attributes,
        'last_changed': state.get('last_changed'), **_brightness(state),
        'exposed': bool(ha_api.get_exposed().get(entity['entity_id']))}}


def locate(query='', entity_id='', catalogue=None, acting_member=None, voice_context=None, source=None):
    from services import stages, voice_identity

    catalogue = _catalogue() if catalogue is None else catalogue
    trackers = [e for e in catalogue if e['domain'] in ('device_tracker', 'person')]
    members = storage.get_all_members()
    member = None
    query_name = ' '.join(str(query or '').split()).casefold()

    def tokens(value):
        return set(_words(re.sub(r"['’]s\b", '', str(value or ''), flags=re.IGNORECASE)).split())

    query_tokens = tokens(query)

    def token_match(name):
        return bool(query_tokens) and query_tokens <= tokens(name)

    if entity_id:
        entity = next((e for e in trackers if e['entity_id'] == entity_id), None)
    else:
        member = next((m for m in members if query_name and query_name in voice_identity.voice_names(m)), None)
        if member:
            person_id = member.get('ha_person_entity')
            if not person_id:
                return {'status': 'error', 'message': (
                    f"{member['name']} has no person entity linked in Chauffeur or Home Assistant, "
                    'so there is no location to read.')}
            entity = next((e for e in trackers if e['domain'] == 'person'
                           and e['entity_id'] == person_id), None)
        else:
            people = [e for e in trackers if e['domain'] == 'person'
                      and (query_name == str(e['name']).casefold() or token_match(e['name']))]
            ranked = sorted(((_score(_words(query), e['_names']), e) for e in people),
                            key=lambda pair: (-pair[0], pair[1]['entity_id']))
            if not ranked and _words(query):
                ranked = sorted(((max(_score(_words(query), e['_names']),
                                      1.0 if any(token_match(n) for n in e['_names']) else 0.0), e)
                                 for e in trackers if e['domain'] == 'device_tracker'),
                                key=lambda pair: (-pair[0], pair[1]['entity_id']))
                ranked = [pair for pair in ranked if pair[0] >= 0.6]
            entity = ranked[0][1] if ranked else None

    if entity and entity['domain'] == 'person':
        member = member or next((m for m in members
                                 if m.get('ha_person_entity') == entity['entity_id']), None)
    elif entity and entity['domain'] == 'device_tracker':
        # A phone is its owner's whereabouts: asking for "Lily's phone" must
        # meet the same privacy rule as asking for Lily. HA's person entity
        # lists the trackers it is built from; that link is the ownership.
        owners = {e['entity_id']: e for e in trackers if e['domain'] == 'person'}
        for m in members:
            person = owners.get(m.get('ha_person_entity') or '')
            if person and entity['entity_id'] in ((person['_state'].get('attributes') or {}).get('device_trackers') or []):
                member = member or m
                break
    if (member and member.get('role') == 'child' and stages.can(member, 'private_location')
            and not _trusted(acting_member, voice_context, source)):
        return {'status': 'refused', 'message': f"{member['name']} keeps their location private."}
    if entity is None:
        return {'status': 'error', 'message': (
            'No location tracker matches that; the HA room an entity sits in is not where it is.')}

    state = entity['_state']
    attrs = state.get('attributes') or {}
    latitude, longitude = attrs.get('latitude'), attrs.get('longitude')
    if (entity['domain'] == 'person' and (latitude is None or longitude is None)
            and not attrs.get('device_trackers')):
        return {'status': 'error', 'message': (
            f"{entity['name']} has no device tracker assigned to {entity['entity_id']} in Home Assistant.")}
    address = None
    device_id = entity.get('_device_id')
    if device_id:
        # Registry identity, never a shared room or similar name, links siblings.
        siblings = {r['entity_id']: r for r in ha_api.get_entity_registry()
                    if r.get('device_id') == device_id
                    and r.get('entity_id', '').startswith('sensor.')}
        for sibling in ha_api.get_states():
            if sibling.get('entity_id') not in siblings:
                continue
            row = siblings[sibling['entity_id']]
            names = [(sibling.get('attributes') or {}).get('friendly_name'),
                     *(row.get(k) for k in ('entity_id', 'name', 'original_name'))]
            if 'geocoded' not in ' '.join(str(n or '') for n in names).casefold():
                continue
            value = str(sibling.get('state') or '').strip()
            if value and value.casefold() not in ('unknown', 'unavailable'):
                address = value
                break
    if (address is None and state.get('state') != 'home'
            and latitude is not None and longitude is not None):
        from services import maps
        address = maps.reverse_geocode(latitude, longitude)

    name = re.sub(r' Location$', '', entity['name'], flags=re.IGNORECASE)
    zone = state.get('state')
    if zone == 'home':
        message = f'{name} is home' + (f' ({address})' if address else '') + '.'
    elif zone == 'not_home':
        message = f'{name} is away' + (f', near {address}' if address else '') + '.'
    else:
        message = f'{name} is at {zone}' + (f' ({address})' if address else '') + '.'
    return {'status': 'success', 'entity_id': entity['entity_id'], 'name': name,
            'zone': zone, 'latitude': latitude, 'longitude': longitude,
            'gps_accuracy': attrs.get('gps_accuracy'), 'in_zones': attrs.get('in_zones', []),
            'last_updated': state.get('last_updated') or state.get('last_changed'),
            **({'source': next((e['name'] for e in catalogue if e['entity_id'] == attrs.get('source')),
                               attrs.get('source'))} if entity['domain'] == 'person' else {}),
            'address': address, 'message': message}


def _trusted(acting_member, voice_context, source):
    """A hand that may unlock the house. The wall panel chats as access.HOUSE
    (role adult, no id): a room anyone can walk into is never a trusted hand,
    so only a REAL signed-in parent or adult counts, the admin page (already
    behind the admin gate) when it carries no member, or a VERIFIED voice."""
    from services import access
    member = acting_member if acting_member and not access.is_house(acting_member) else None
    if member and member.get('role') in ('parent', 'adult'):
        return True
    if acting_member is None and source == 'admin':
        return True
    return (voice_context is not None and getattr(voice_context, 'level', None) == 'verified'
            and (voice_context.verified_member() or {}).get('role') in ('parent', 'adult'))


def house(action='', query='', entity_id='', domain='', service='', data=None,
          hours=24, acting_member=None, voice_context=None, source=None):
    """One boundary for every action: failures are plain results, never exceptions."""
    try:
        if ha_api.mode() == 'unconfigured':
            return {'status': 'error', 'message': 'Home Assistant is not connected.'}
        if action not in ('find', 'read', 'history', 'act', 'locate'):
            return {'status': 'error', 'message': 'Unknown house action. Use find, read, history, act or locate.'}
        catalogue = _catalogue()
        if action == 'find':
            if not str(query or '').strip():
                return {'status': 'error', 'message': 'Which device or room should I find?'}
            return find(query, domain, catalogue)
        if action == 'locate':
            return locate(query, entity_id, catalogue, acting_member, voice_context, source)
        entity = resolve(query, entity_id, domain, catalogue)
        if 'status' in entity:
            return entity
        eid = entity['entity_id']
        if action == 'read':
            return _read(entity)
        if action == 'history':
            rows = ha_api.get_history(eid, hours=max(1, min(168, int(hours))))
            changes = sum(rows[i][1] != rows[i - 1][1] for i in range(1, len(rows)))
            if len(rows) > 50:
                rows = [rows[round(i * (len(rows) - 1) / 49)] for i in range(50)]
            return {'status': 'success', 'entity_id': eid,
                    'points': [{'at': at, 'state': state} for at, state in rows], 'changes': changes}
        entity_domain = entity['domain']
        service_domain, _, service_name = str(service).partition('.')
        if not service_name:
            service_name, service_domain = service_domain, entity_domain
        if service_domain != entity_domain or not ha_api.has_service(service_domain, service_name):
            return {'status': 'error', 'message': 'That service is not available for this device.'}
        if not ha_api.get_exposed().get(eid) and not storage.get_settings().get('house_control_unexposed'):
            return {'status': 'refused', 'message': (
                f"{entity['name']} is not exposed to Assist; expose it in Home Assistant, "
                'or allow unexposed control under Config › People › Argyle.')}
        attrs = entity['_state'].get('attributes') or {}
        sensitive = entity_domain in ('lock', 'alarm_control_panel') or (
            entity_domain == 'cover' and attrs.get('device_class') in ('garage', 'door', 'gate'))
        if sensitive and not _trusted(acting_member, voice_context, source):
            return {'status': 'refused', 'message': 'That needs a parent on their phone.'}
        result = ha_api.call_service(service_domain, service_name, {**(data or {}), 'entity_id': eid})
        if result is None:
            return {'status': 'error', 'message': 'Home Assistant could not control that device.'}
        _settle()
        after = next((s for s in ha_api.get_states(ttl=0) if s.get('entity_id') == eid), None)
        if after is None:
            return {'status': 'error', 'message': 'Home Assistant did not report the device state after the action.'}
        return {'status': 'success', 'entity_id': eid, 'service': f'{service_domain}.{service_name}',
                'state_after': after.get('state'), **_brightness(after),
                'message': f"{entity['name']} is {after.get('state')}."}
    except Exception:
        return {'status': 'error', 'message': 'Home Assistant could not answer that request.'}
