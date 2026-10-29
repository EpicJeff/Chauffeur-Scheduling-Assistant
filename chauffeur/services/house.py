"""Home Assistant device discovery, open reads and permission-checked control."""
import re
import time
from difflib import SequenceMatcher

from services import ha_api, storage


def _settle():
    time.sleep(0.6)


_STOP = {'the', 'a', 'an', 'of'}


def _words(value):
    # 'the mercedes doors' is 'mercedes doors'; small words never decide a match.
    return ' '.join(w for w in re.findall(r'\w+', str(value or '').casefold().replace('_', ' ')) if w not in _STOP)


def _catalogue():
    registry = {r['entity_id']: r for r in ha_api.get_entity_registry()}
    areas = ha_api.get_area_map()
    area_names = {a['id']: a['name'] for a in areas}
    entity_areas = {eid: a['name'] for a in areas for eid in a.get('entities', [])}
    states = ha_api.get_states()
    # The device registry names the device an entity belongs to (the Powerwall is
    # "My Home"; its fifty entities say Powerwall) and gives an area to entities
    # the template map left without one.
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
        device = devices.get(row.get('device_id'), {})
        area_id = row.get('area_id') or device.get('area_id')
        device_name = device.get('name_by_user') or device.get('name') or ''
        out.append({'entity_id': eid, 'name': name,
                    'area': entity_areas.get(eid) or area_names.get(area_id, ''),
                    'domain': eid.split('.', 1)[0], 'state': state.get('state'),
                    'aliases': list(row.get('aliases') or []), '_state': state,
                    '_device_id': row.get('device_id'), '_device_name': device_name,
                    '_make': device.get('manufacturer') or '', '_model': device.get('model') or '',
                    '_device_area': area_names.get(device.get('area_id'), ''),
                    '_platform': row.get('platform'),
                    # Every name the thing goes by: the person's, HA's, the integration's, the
                    # maker's and the model's. 'mercedes' and 'gls' both find the VIN-named car.
                    '_own': [name, row.get('name'), row.get('original_name'), *list(row.get('aliases') or []),
                             eid, eid.split('.', 1)[1]],
                    '_names': [name, row.get('name'), row.get('original_name'),
                               *list(row.get('aliases') or []), eid, eid.split('.', 1)[1], device_name,
                               device.get('name') or '', device.get('manufacturer') or '', device.get('model') or '']})
    # What the family taught: 'the entry doors' names these two sensors (argyle_memory
    # vocabulary rows). A taught phrase is the thing's own name on every surface.
    from services import argyle_memory
    vocab = argyle_memory.vocabulary()
    for e in out:
        for phrase in vocab.get(e['entity_id'], ()):
            e['_own'].append(phrase)
            e['_names'].append(phrase)
            e['aliases'].append(phrase)
    _infer_areas(out, list(area_names.values()))
    _mark_kinds(out)
    return out


def _infer_areas(catalogue, room_names):
    """Live 2026-10-29: locks named Pool House Kitchen and Pool House Changing Room sat in no
    HA area and were 'not associated with the pool house'. An entity (or its device) without an
    area whose name starts with a room's name is in that room; the longest room name wins (Pool
    House before Pool); HA's own assignment always wins over the name."""
    rooms = sorted(((_words(n), n) for n in room_names if _words(n)), key=lambda p: -len(p[0]))
    if not rooms:
        return

    def room_for(*names):
        for name in names:
            words = _words(name)
            for key, room in rooms:
                if words == key or words.startswith(key + ' '):
                    return room
        return ''
    for e in catalogue:
        if not e['area']:
            room = room_for(e['name'], e.get('_device_name') or '')
            if room:
                e['area'] = room
                e['_area_inferred'] = True
        if not e.get('_device_area') and e.get('_device_name'):
            e['_device_area'] = room_for(e['_device_name']) or e['area']


KIND_WORDS = {'car': ('car', 'cars', 'vehicle', 'vehicles', 'auto'), 'tv': ('tv', 'tvs', 'television', 'televisions')}


def _kind_of(members):
    """What sort of thing a device is, from what it carries, so 'the car doors' names every car
    and never a phone. A car has a tracker and doors or locks; a phone, a mower and a school
    bus have a tracker and nothing that locks. A TV is a media player HA classes as one, or an Android TV remote."""
    domains = {e['domain'] for e in members}
    classes = {(e['_state'].get('attributes') or {}).get('device_class') for e in members}
    # Live 2026-10-29: a tracker plus distance or speed also fit the robot mower and the school
    # buses; a car is a tracker plus something that locks or a door.
    if 'device_tracker' in domains and ('lock' in domains or classes & {'door', 'lock'}):
        return 'car'
    if classes & {'tv'} or any(e['domain'] == 'remote' and 'activity_list' in (e['_state'].get('attributes') or {})
                               for e in members):
        return 'tv'
    return ''


# A category is every such thing in the house, by HA domain and device_class, never by name:
# 'doors' is every door sensor and garage cover, 'locks' every lock and lock sensor.
CATEGORIES = {
    'lock': {'words': ('lock', 'locks', 'locked', 'unlocked'), 'domains': {'lock'}, 'classes': {'lock'}},
    'door': {'words': ('door', 'doors'), 'classes': {'door', 'garage_door', 'opening'},
             'cover_classes': {'garage', 'door', 'gate'}},
    'window': {'words': ('window', 'windows'), 'classes': {'window'}, 'cover_classes': {'window'}},
    'light': {'words': ('light', 'lights', 'lamp', 'lamps'), 'domains': {'light'}},
    'camera': {'words': ('camera', 'cameras'), 'domains': {'camera'}},
    'motion': {'words': ('motion', 'occupancy'), 'classes': {'motion', 'occupancy'}},
    'thermostat': {'words': ('thermostat', 'thermostats', 'temperature'), 'domains': {'climate'}},
    'fan': {'words': ('fan', 'fans'), 'domains': {'fan'}},
    'smoke': {'words': ('smoke', 'alarm', 'alarms'), 'classes': {'smoke', 'carbon_monoxide', 'gas'}},
    'leak': {'words': ('leak', 'leaks', 'water'), 'classes': {'moisture'}},
    'battery': {'words': ('battery', 'batteries'), 'classes': {'battery'}},
}
# Words that ask or name a state never narrow a category: 'are the car doors closed' narrows by
# 'car', not by 'closed'.
_CATEGORY_NOISE = {'all', 'every', 'any', 'is', 'are', 'was', 'were', 'in', 'on', 'at', 'house', 'home', 'my',
                   'our', 'and', 'or', 'still', 'now', 'which', 'what', 'how', 'many', 'off', 'open', 'opened',
                   'closed', 'shut', 'locked', 'unlocked', 'low', 'dead', 'detected', 'clear', 'away', 'running',
                   'charging', 'playing', 'idle', 'unavailable', 'available', 'working', 'broken', 'online',
                   'offline', 'secure', 'safe'}
CATEGORY_ROWS = 80


def _in_category(entity, spec):
    attrs = entity['_state'].get('attributes') or {}
    dc = attrs.get('device_class')
    if entity['domain'] in spec.get('domains', ()):
        return True
    if entity['domain'] == 'binary_sensor' and dc in spec.get('classes', ()):
        return True
    if entity['domain'] == 'cover' and dc in spec.get('cover_classes', ()):
        return True
    return entity['domain'] == 'sensor' and dc in spec.get('classes', ()) and spec is CATEGORIES['battery']


def _category_blocks(query, catalogue):
    """Live 2026-10-29: "are all the doors locked" found the Kia's Door Lock alone, by name, and voice
    said Yes while a house lock was offline and both cars were unlocked. A category word puts EVERY
    such entity on the table with a tally the tool computed; the other words (a room, a device)
    narrow it; an empty narrowing stays empty and says so, never the whole house instead."""
    said = [w for w in _words(query).split()]
    cats = [k for k, spec in CATEGORIES.items() if set(said) & set(spec['words'])]
    if not cats:
        return []
    q = ' '.join(said)
    if any(_words(n) == q for e in catalogue for n in (e.get('_own') or e['_names'])):
        return []   # the words said ARE a thing's name ('front door' is the lock, not every door)
    cat_words = {w for k in cats for w in CATEGORIES[k]['words']}
    narrow = {_singular(w) for w in said if w not in cat_words and w not in _CATEGORY_NOISE}
    out = []
    for key in cats:
        spec = CATEGORIES[key]
        members = [e for e in catalogue if _in_category(e, spec)]
        if narrow:
            members = [e for e in members if narrow <= {_singular(w) for n in [*e['_names'], e['area']]
                                                        for w in _words(n).split()}]
        members.sort(key=lambda e: (e.get('_kind') or '', e['area'], e['name']))
        rows, tally, by_state = [], {}, {}
        for e in members:
            shown = _shown(e)
            row = {'entity_id': e['entity_id'], 'name': e['name'], **shown, 'ha_area': e['area']}
            if e.get('_device_name'):
                row['device'] = e['_device_name']
            if e.get('_kind'):
                row['kind'] = e['_kind']
            rows.append(row)
            state = str(shown['state'])
            if e['domain'] == 'sensor':
                # A battery LEVEL tallies as low or ok, never as forty-seven different numbers.
                try:
                    state = 'low' if float(state) < 20 else 'ok'
                except ValueError:
                    pass
            tally[state] = tally.get(state, 0) + 1
            by_state.setdefault(state, []).append(e['name'] + (f" ({e['_kind']})" if e.get('_kind') else ''))
        plural = spec['words'][1] if len(spec['words']) > 1 else spec['words'][0]
        where = f" in {' '.join(sorted(narrow))}" if narrow else ''
        if not rows:
            message = f'no {plural}{where}.'
        else:
            parts = []
            for state, names in sorted(by_state.items(), key=lambda kv: (-len(kv[1]), kv[0])):
                shown_names = ', '.join(names[:12]) + (f' and {len(names) - 12} more' if len(names) > 12 else '')
                parts.append(f'{state}: {shown_names}')
            message = f"{len(rows)} {plural}{where}; " + '; '.join(parts) + '.'
        # 'the car doors' with a car that reports no door at all (the Mercedes, live): say so,
        # or the answer reads as if that car were fine.
        kinds = {k for k, words in KIND_WORDS.items() if narrow & {_singular(w) for w in words}}
        if kinds:
            with_rows = {r.get('device') for r in rows}
            silent = sorted({e['_device_name'] for e in catalogue if e.get('_kind') in kinds
                             and e.get('_device_name') and e['_device_name'] not in with_rows})
            if silent:
                message += f" No {plural} reported by: {', '.join(silent)}."
        block = {'category': key, 'tally': tally, 'message': message, 'entities': rows[:CATEGORY_ROWS]}
        if len(rows) > CATEGORY_ROWS:
            block['more'] = len(rows) - CATEGORY_ROWS
        out.append(block)
    return out


def _mark_kinds(catalogue):
    by_device = {}
    for e in catalogue:
        if e.get('_device_id'):
            by_device.setdefault(e['_device_id'], []).append(e)
    for members in by_device.values():
        kind = _kind_of(members)
        for e in members:
            e['_kind'] = kind
            if kind:
                e['_names'] = [*e['_names'], *KIND_WORDS[kind]]


# What a binary sensor's on/off MEANS, by HA device_class (HA's own frontend words).
# Live 2026-10-29: the Kia's 'Locked' sensor read on while the car was unlocked.
BINARY_WORDS = {
    'battery': ('low', 'normal'), 'battery_charging': ('charging', 'not charging'),
    'carbon_monoxide': ('detected', 'clear'), 'cold': ('cold', 'normal'),
    'connectivity': ('connected', 'disconnected'), 'door': ('open', 'closed'),
    'garage_door': ('open', 'closed'), 'gas': ('detected', 'clear'), 'heat': ('hot', 'normal'),
    'light': ('light detected', 'no light'), 'lock': ('unlocked', 'locked'), 'moisture': ('wet', 'dry'),
    'motion': ('detected', 'clear'), 'moving': ('moving', 'not moving'), 'occupancy': ('occupied', 'clear'),
    'opening': ('open', 'closed'), 'plug': ('plugged in', 'unplugged'), 'power': ('on', 'off'),
    'presence': ('home', 'away'), 'problem': ('problem', 'ok'), 'running': ('running', 'not running'),
    'safety': ('unsafe', 'safe'), 'smoke': ('detected', 'clear'), 'sound': ('detected', 'clear'),
    'tamper': ('tampered', 'clear'), 'update': ('update available', 'up to date'),
    'vibration': ('detected', 'clear'), 'window': ('open', 'closed'),
}


def _shown(entity):
    """The state as HA shows it: a binary sensor's on/off becomes the word its device_class
    means ('on' + lock = unlocked); `raw_state` keeps HA's value when they differ."""
    state = entity['_state'].get('state')
    if entity['domain'] == 'binary_sensor' and state in ('on', 'off'):
        words = BINARY_WORDS.get((entity['_state'].get('attributes') or {}).get('device_class'))
        if words:
            shown = words[0] if state == 'on' else words[1]
            if shown != state:
                return {'state': shown, 'raw_state': state}
    return {'state': state}


def _measure(entity):
    """What makes a sensor's number readable: its unit and HA device class, when it has them."""
    attrs = entity['_state'].get('attributes') or {}
    out = {}
    if attrs.get('unit_of_measurement'):
        out['unit'] = attrs['unit_of_measurement']
    if attrs.get('device_class'):
        out['device_class'] = attrs['device_class']
    return out


def _candidate(entity):
    row = {**{k: entity[k] for k in ('entity_id', 'name', 'domain', 'aliases')}, **_shown(entity),
           'ha_area': entity['area'], **_measure(entity)}
    if entity.get('_area_inferred'):
        row['ha_area_inferred'] = True   # read off the name, not HA's registry
    attrs = entity['_state'].get('attributes') or {}
    if entity['domain'] == 'remote' and 'activity_list' in attrs:
        row['apps'] = list(attrs.get('activity_list') or [])   # an Android TV: what it can open
    if entity.get('_device_name'):
        row['device'] = entity['_device_name']
    return row


DEVICE_ROWS = 60      # entities listed per device; the rest is a count
DEVICE_GROUPS = 5     # devices listed per answer
_DOMAIN_ORDER = {d: i for i, d in enumerate((
    'cover', 'lock', 'light', 'switch', 'fan', 'media_player', 'climate', 'alarm_control_panel',
    'device_tracker', 'number', 'select', 'sensor', 'binary_sensor'))}


def _device_groups(ranked, catalogue):
    """The HA devices the matches belong to, each with EVERY entity on it (state, unit,
    device_class). Live 2026-10-29: 'powerwall' matched one entity, Powerwall Version
    (unavailable), and the percentage charged sat unseen on the same device. The model
    picks the row that fits the question; the tool never guesses which sensor that is."""
    # Only real matches make a device (every word said in the name, or the room named);
    # 'powerwall battery' must not drag in every phone and mower with a battery sensor.
    ranked = [pair for pair in ranked if pair[0] >= 0.8] or ranked[:8]
    hits = {}
    for score, e in ranked:
        if e.get('_device_id'):
            best, count = hits.get(e['_device_id'], (0.0, 0))
            hits[e['_device_id']] = (max(best, score), count + 1)
    ordered = sorted(hits.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))[:DEVICE_GROUPS]
    per = DEVICE_ROWS if len(ordered) <= 2 else 20
    out = []
    for device_id, (best, count) in ordered:
        members = sorted((e for e in catalogue if e.get('_device_id') == device_id),
                         key=lambda e: (_DOMAIN_ORDER.get(e['domain'], 20), e['name'], e['entity_id']))
        rows = [{'entity_id': e['entity_id'], 'name': e['name'], 'domain': e['domain'], **_shown(e),
                 **_measure(e)} for e in members[:per]]
        first = members[0]
        group = {'device': first.get('_device_name') or first['name'],
                 **({'make': first['_make']} if first.get('_make') else {}),
                 **({'model': first['_model']} if first.get('_model') else {}),
                 **({'kind': first['_kind']} if first.get('_kind') else {}),
                 'ha_area': first.get('_device_area') or first['area'], 'entities': rows}
        if len(members) > per:
            group['more'] = len(members) - per
        out.append(group)
    return out


def _singular(word):
    return word[:-1] if len(word) > 3 and word.endswith('s') and not word.endswith('ss') else word


def _score(query, names):
    tokens = {_singular(w) for w in query.split()}   # 'doors' finds 'Front Left Door'
    best = 0.0
    # Every word said somewhere among the names the thing goes by ('car' from its kind,
    # 'door' from its own name, 'kia' from its device) is a strong match too.
    across = {_singular(w) for name in names for w in _words(name).split()}
    if tokens and tokens <= across:
        best = 0.8 + 0.2 * len(tokens) / len(across)
    for name in names:
        name = _words(name)
        if not name:
            continue
        if query == name:
            return 1.0
        name_tokens = {_singular(w) for w in name.split()}
        if tokens and tokens <= name_tokens:
            # Every word said is in the name: 'powerwall' fits 'Powerwall Percentage charged'
            # as well as 'Powerwall Version'; a long name must not lose to a short one, and
            # every such match is strong (0.8+; 0.7 + 0.3/3 fell BELOW 0.8 in floating point
            # and resolve picked Powerwall Version alone, the live failure in another coat).
            best = max(best, 0.8 + 0.2 * len(tokens) / len(name_tokens))
        overlap = len(tokens & name_tokens) / max(len(tokens), len(name_tokens))
        best = max(best, 0.65 * overlap + 0.35 * SequenceMatcher(None, query, name).ratio())
    return best


def _rank(catalogue, query, domain='', limit=8):
    """Every matching entity, best first; `limit` None keeps them all (device grouping)."""
    query = _words(query)
    if not query:
        return []
    pool = [e for e in catalogue if not domain or e['domain'] == domain]
    area_matches = [e for e in pool if _words(e['area']) == query]
    if area_matches:
        domain_order = {domain: i for i, domain in enumerate((
            'cover', 'lock', 'light', 'switch', 'fan', 'media_player', 'climate',
            'alarm_control_panel', 'device_tracker'))}
        # Naming the room is a full match for everything in it; the name score only orders.
        return [(1.0, e) for _, e in sorted(((_score(query, e['_names']), e) for e in area_matches),
                                            key=lambda pair: (domain_order.get(pair[1]['domain'],
                                                              10 if pair[1]['domain'] in ('sensor', 'binary_sensor') else 9),
                                                              -pair[0], pair[1]['entity_id']))[:limit]]
    # A kind word ('car doors', 'the TVs') puts every device of that kind on the table, whether
    # or not the other words hit it: the Mercedes reports no door at all, and the answer for
    # 'the car doors' is still both cars, never the Kia alone.
    kinds = {k for k, words in KIND_WORDS.items() if set(query.split()) & set(words)}
    # The thing's OWN name outranks its device's, maker's or kind's: 'front door' is the lock
    # named Front Door before the doorbell's motion sensor on a device called Front Door.
    ranked = [(max(_score(query, e.get('_own') or e['_names']), min(0.97, _score(query, e['_names'])),
                   _score(query, [e['area']]), 0.8 if e.get('_kind') in kinds else 0.0), e) for e in pool]
    return sorted(((score, e) for score, e in ranked if score >= 0.45),
                  key=lambda pair: (-pair[0], pair[1]['entity_id']))[:limit]


def find(query, domain='', catalogue=None):
    catalogue = _catalogue() if catalogue is None else catalogue
    ranked = _rank(catalogue, query, domain, limit=None)
    out = {'status': 'success', 'candidates': [_candidate(e) for _, e in ranked[:8]],
           'devices': _device_groups(ranked, catalogue)}
    categories = _category_blocks(query, catalogue)
    if categories:
        out['categories'] = categories
    return out


def resolve(query='', entity_id='', domain='', catalogue=None):
    catalogue = _catalogue() if catalogue is None else catalogue
    wanted = entity_id or query
    exact = next((e for e in catalogue if e['entity_id'] == wanted
                  and (not domain or e['domain'] == domain)), None)
    if exact:
        return exact
    if entity_id:
        return {'status': 'error', 'message': 'That Home Assistant entity is not available.'}
    ranked = _rank(catalogue, query, domain, limit=None)
    # An area alone is discovery, even when its name resembles a device: 'hall' lists
    # the hall, it never picks the Hall Light.
    q = _words(query)
    names_an_area = any(_words(e['area']) == q for e in catalogue)
    strong = [e for _, e in ranked if _score(q, e['_names']) >= (1.0 if names_an_area else 0.8)]
    if len(strong) == 1:
        return strong[0]
    if ranked:
        return {'status': 'ambiguous', 'candidates': [_candidate(e) for _, e in ranked[:8]],
                'devices': _device_groups(ranked, catalogue), 'message': 'Which device do you mean?'}
    return {'status': 'error', 'message': 'No matching Home Assistant device was found.'}


def _brightness(state):
    attrs = state.get('attributes') or {}
    return {'brightness_pct': round(attrs['brightness'] * 100 / 255)} if 'brightness' in attrs else {}


def _read(entity, catalogue=None):
    state = entity['_state']
    attributes = {}
    for key, value in (state.get('attributes') or {}).items():
        if key in ('access_token', 'token', 'entity_picture', 'id') or key.endswith('_token'):
            continue
        attributes[key] = value
        if len(attributes) == 30:
            break
    out = {'entity_id': entity['entity_id'], 'name': entity['name'], 'ha_area': entity['area'],
           **_shown(entity), 'attributes': attributes,
           'last_changed': state.get('last_changed'), **_brightness(state),
           'exposed': bool(ha_api.get_exposed().get(entity['entity_id']))}
    faces = _tv_faces(entity, catalogue or [])
    if faces:
        tv = tv_now({e['entity_id']: e['_state'] for e in catalogue}, faces, entity['name'])
        if tv:
            out['tv'] = tv    # what the TV is showing, from every face of it
    return {'status': 'success', 'entity': out}


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


# --- apps on a TV -----------------------------------------------------------
# The Android TV Remote integration launches an app from a string the TV
# resolves itself: a web link the app claims, or a package id. DEVICE-FOUND
# 2026-10-28 on a TCL Google TV: package ids launch NOTHING; links do. So each
# app carries the link that is sent and the package id the TV reports back.
# A link the TV cannot hand to an app opens its browser or the Play Store,
# which is how "not installed" shows up. HA's remote lists configured app
# NAMES (activity_list) and reports the name back as current_activity when it
# knows the id; the media_player twin reports the package id.
# (name, package id, spoken aliases, link). Links marked verified opened the
# app on that TV; the rest are the app's own domain, unverified.
KNOWN_APPS = (
    ('Netflix', 'com.netflix.ninja', (), 'https://www.netflix.com/browse'),                      # verified
    ('YouTube', 'com.google.android.youtube.tv', ('you tube',), 'https://www.youtube.com'),         # verified
    ('YouTube TV', 'com.google.android.youtube.tvunplugged', ('you tube tv',), 'https://tv.youtube.com'),
    ('YouTube Kids', 'com.google.android.youtube.tvkids', ('you tube kids',), 'https://www.youtubekids.com'),
    ('Disney+', 'com.disney.disneyplus', ('disney plus', 'disney'), 'https://www.disneyplus.com'),   # verified
    ('Prime Video', 'com.amazon.amazonvideo.livingroom',
     ('prime', 'amazon prime', 'amazon prime video', 'amazon video'), 'https://app.primevideo.com'),  # verified
    ('Hulu', 'com.hulu.livingroomplus', (), 'https://www.hulu.com'),
    ('Max', 'com.wbd.stream', ('hbo max', 'hbo'), 'https://play.max.com'),                          # verified
    ('Plex', 'com.plexapp.android', (), 'https://app.plex.tv'),
    ('Spotify', 'com.spotify.tv.android', (), 'https://open.spotify.com'),
    ('Paramount+', 'com.cbs.ott', ('paramount plus', 'paramount'), 'https://www.paramountplus.com'),
    ('Peacock', 'com.peacocktv.peacockandroid', (), 'https://www.peacocktv.com'),
    ('Apple TV', 'com.apple.atve.androidtv.appletv', ('apple tv plus', 'apple tv+'), 'https://tv.apple.com'),  # verified
    ('DIRECTV STREAM', 'com.att.tv', ('directv', 'direct tv', 'directv stream'), 'https://stream.directv.com'),
    ('Twitch', 'tv.twitch.android.app', (), 'https://www.twitch.tv'),
    ('Pluto TV', 'tv.pluto.android', ('pluto',), 'https://pluto.tv'),
    ('Tubi', 'com.tubitv', (), 'https://tubitv.com'),                                               # verified
    ('Crunchyroll', 'com.crunchyroll.crunchyroid', (), 'https://www.crunchyroll.com'),
    ('ESPN', 'com.espn.score_center', (), 'https://www.espn.com/watch'),
    ('Apple Music', 'com.apple.android.music', (), 'https://music.apple.com'),
    ('Pandora', 'com.pandora.android.atv', (), 'https://www.pandora.com'),
    ('Play Store', 'com.android.vending', ('google play', 'google play store', 'app store'),
     'https://play.google.com/store'),                                                             # verified
    ('Kodi', 'org.xbmc.kodi', (), None),
    ('Jellyfin', 'org.jellyfin.androidtv', (), None),
    ('Emby', 'tv.emby.embyatv', (), None),
    ('Steam Link', 'com.valvesoftware.steamlink', (), None),
    ('Philo', 'com.philo.philo.google', (), 'https://www.philo.com'),
    ('Xfinity Stream', 'com.xfinity.cloudtvr.tenfoot', ('xfinity',), 'https://www.xfinity.com/stream'),
)
NOT_AN_APP = ('browser', 'com.android.vending', 'launcherx')   # where a launch lands when the app is missing
def _app_display(value):
    """A reported app as a person would say it: HA's configured name stays, a package id becomes
    the catalogue name when known, the Google TV launcher is the home screen."""
    value = str(value or '')
    if not value:
        return ''
    if 'launcherx' in value:
        return 'the home screen'
    if _PACKAGE_RE.match(value) and ' ' not in value:
        return next((n for n, p, _a, _l in KNOWN_APPS if p == value), value)
    return value


def _minutes(seconds):
    try:
        return f'{int(round(float(seconds) / 60))} min'
    except (TypeError, ValueError):
        return ''


def tv_now(states, candidates, tv_name=''):
    """What a TV is showing, stitched from its faces: the Android TV remote and its twin know the
    APP, a Cast player in the same room knows the TITLE and position, Music Assistant's face knows
    only music and is left to the music tool. None when no face says anything."""
    rows = [states[e] for e in dict.fromkeys(candidates) if e in states]
    app = ''
    for r in rows:
        a = r.get('attributes') or {}
        if r['entity_id'].startswith('remote.') and r.get('state') == 'on' and a.get('current_activity'):
            app = _app_display(a['current_activity'])
            tv_name = tv_name or a.get('friendly_name') or ''
            break
    if not app:
        for r in rows:
            a = r.get('attributes') or {}
            if (r['entity_id'].startswith('media_player.') and 'mass_player_type' not in a
                    and r.get('state') in ('on', 'playing', 'paused') and a.get('app_name')):
                app = _app_display(a['app_name'])
                break
    video = next((r for r in rows if r['entity_id'].startswith('media_player.')
                  and 'mass_player_type' not in (r.get('attributes') or {})
                  and r.get('state') in ('playing', 'paused')
                  and (r.get('attributes') or {}).get('media_title')), None)
    if not app and video is None:
        return None
    tv_name = tv_name or (rows[0].get('attributes') or {}).get('friendly_name') or 'The TV'
    out = {'app': app or None, 'title': None, 'artist': None, 'state': None,
           'position_min': None, 'duration_min': None}
    if video is not None:
        a = video.get('attributes') or {}
        out.update(title=a.get('media_title'), artist=a.get('media_artist') or a.get('media_series_title'),
                   state=video.get('state'), position_min=_minutes(a.get('media_position')) or None,
                   duration_min=_minutes(a.get('media_duration')) or None)
        if not app:
            out['app'] = _app_display(a.get('app_name')) or None
        by = f" ({out['artist']})" if out['artist'] else ''
        where = f", {out['position_min']} in of {out['duration_min']}" if out['position_min'] and out['duration_min'] else ''
        on = f" on {out['app']}" if out['app'] else ''
        out['message'] = f"{tv_name} is{on}, {out['state']} {out['title']}{by}{where}."
    else:
        out['state'] = 'on'
        out['message'] = f"{tv_name} is on {app}."
    return out


def _tv_faces(entity, catalogue):
    """Entity ids of the same TV: everything on its HA device plus every media face in its room."""
    if not (entity['domain'] in ('remote', 'media_player')):
        return []
    device = entity.get('_device_id')
    on_device = [e for e in catalogue if device and e.get('_device_id') == device]
    android = any(e in _android_remotes(catalogue) for e in on_device) or entity in _android_remotes(catalogue)
    if not android:
        return []
    room = entity['area']
    # Device 2026-10-28: the Cast face ("Office Google TV Media Player") sits in no HA area at
    # all, so a face whose name starts with the room's name counts as in the room.
    prefix = _words(room) + ' ' if room else None
    in_room = [e for e in catalogue if room and e['domain'] in ('remote', 'media_player')
               and (e['area'] == room or _words(e['name']).startswith(prefix))]
    return [e['entity_id'] for e in (on_device + in_room)]
_PACKAGE_RE = re.compile(r'^[a-zA-Z][\w]*(\.[\w]+)+$')


def _app_forms(value):
    """The ways one app name gets said: 'the Hulu app', 'Disney plus', 'Sling'.
    The exact words come first; the core (no trailing 'tv'/'plus') is a fallback,
    so 'YouTube TV' never collapses into YouTube."""
    words = _words(value)
    words = re.sub(r'^the ', '', words)
    words = re.sub(r' app$', '', words)
    core = re.sub(r' (tv|plus)$', '', words)
    return [f for f in (words, core) if f]


def _resolve_app(app, listed):
    """-> (display name, package id, what to send as `activity`) or None."""
    app = str(app or '').strip()
    if not app:
        return None
    if app.startswith(('http://', 'https://')) or (_PACKAGE_RE.match(app) and ' ' not in app):
        return app, app, app
    known = {}
    for name, package, aliases, link in KNOWN_APPS:
        for form in (name, *aliases):
            for f in _app_forms(form):
                known.setdefault(f, (name, package, link or package))

    def known_for(ha_name):
        return next((known[f] for f in _app_forms(ha_name) if f in known), None)
    wanted = _app_forms(app)
    for depth in (0, 1):      # exact words everywhere before any core form
        w = wanted[min(depth, len(wanted) - 1)]
        for name in listed:
            forms = _app_forms(name)
            if w == forms[min(depth, len(forms) - 1)]:
                return known_for(name) or (name, name, name)
        if w in known:
            return known[w]
    best, best_score = None, 0.0
    for name in listed:
        score = max(_score(w, [name]) for w in wanted)
        if score > best_score:
            best, best_score = (known_for(name) or (name, name, name)), score
    for name, package, aliases, link in KNOWN_APPS:
        score = max(_score(w, [name, *aliases]) for w in wanted)
        if score > best_score:
            best, best_score = (name, package, link or package), score
    return best if best_score >= 0.6 else None


def _android_remotes(catalogue):
    """Android TV remotes, by HA's integration or by the app list only it publishes;
    an offline one is still a TV (it answers 'offline', never 'not a TV')."""
    return [e for e in catalogue if e['domain'] == 'remote'
            and (e.get('_platform') == 'androidtv_remote'
                 or 'activity_list' in (e['_state'].get('attributes') or {}))]


def _tv_list(remotes):
    return ', '.join(e['name'] for e in remotes) or 'none'


def _remote_for(query, entity_id, catalogue):
    """The Android TV remote a person means, by its id, its media_player twin's id, its name or its room."""
    remotes = _android_remotes(catalogue)
    if not remotes:
        return {'status': 'error', 'message': 'No Android TV is connected to Home Assistant, so no TV can open an app.'}
    if entity_id:
        exact = next((e for e in catalogue if e['entity_id'] == entity_id), None)
        if exact is None:
            return {'status': 'error', 'message': 'That Home Assistant entity is not available.'}
        hit = next((e for e in remotes if e is exact or (
            e['_device_id'] and e['_device_id'] == exact['_device_id'])), None)
        if hit is None:
            return {'status': 'error', 'message': (
                f"{exact['name']} is not an Android TV remote. TVs that can open apps: {_tv_list(remotes)}.")}
        return hit
    q = _words(query)
    if not q:
        return {'status': 'error', 'message': f'Which TV? TVs that can open apps: {_tv_list(remotes)}.'}
    strong = [e for e in remotes if _score(q, e['_names']) >= 0.8]
    if not strong:
        strong = [e for e in remotes if _words(e['area']) == q]
    if not strong:
        # 'pool house' for the Pool House Lounge TV: every word said is in the TV's name.
        said = set(q.split())
        strong = [e for e in remotes if any(said <= set(_words(n).split()) for n in e['_names'])]
    if len(strong) == 1:
        return strong[0]
    if strong:
        return {'status': 'ambiguous', 'candidates': [_candidate(e) for e in strong], 'message': 'Which TV do you mean?'}
    other = _rank(catalogue, query)
    if other and other[0][0] >= 0.8:
        return {'status': 'error', 'message': (
            f"{other[0][1]['name']} is not an Android TV. TVs that can open apps: {_tv_list(remotes)}.")}
    return {'status': 'error', 'message': f'No Android TV called {query}. TVs that can open apps: {_tv_list(remotes)}.'}


def open_app(query='', entity_id='', app='', catalogue=None):
    """Launch an app on an Android TV through its HA remote; the TV is read back, never trusted."""
    catalogue = _catalogue() if catalogue is None else catalogue
    remote = _remote_for(query, entity_id, catalogue)
    if 'status' in remote:
        return remote
    if remote['state'] in ('unavailable', 'unknown', None):
        return {'status': 'error', 'message': f"{remote['name']} is offline right now, so it cannot open an app."}
    listed = list((remote['_state'].get('attributes') or {}).get('activity_list') or [])
    if not str(app or '').strip():
        return {'status': 'error', 'message': f"Which app? {remote['name']} lists: {', '.join(listed) or 'no apps yet'}."}
    resolved = _resolve_app(app, listed)
    if resolved is None:
        return {'status': 'error', 'message': (
            f"I don't know an app called {app}. {remote['name']} lists: {', '.join(listed) or 'no apps yet'}.")}
    name, package, activity = resolved
    eid = remote['entity_id']
    exposed = ha_api.get_exposed()
    twins = [e['entity_id'] for e in catalogue if remote['_device_id'] and e['_device_id'] == remote['_device_id']]
    if not any(exposed.get(t) for t in (eid, *twins)) and not storage.get_settings().get('house_control_unexposed'):
        return {'status': 'refused', 'message': (
            f"{remote['name']} is not exposed to Assist; expose it in Home Assistant, "
            'or allow unexposed control under Config › People › Argyle.')}
    if not ha_api.has_service('remote', 'turn_on'):
        return {'status': 'error', 'message': 'Home Assistant cannot launch apps on that TV.'}
    # Fresh, not the catalogue's cached copy: the TV may have moved since the catalogue was built.
    live = next((s for s in ha_api.get_states(ttl=0) if s.get('entity_id') == eid), remote['_state'])
    before = (live.get('attributes') or {}).get('current_activity')
    result = ha_api.call_service('remote', 'turn_on', {'entity_id': eid, 'activity': activity})
    if result is None:
        return {'status': 'error', 'message': f"Home Assistant could not reach {remote['name']}."}
    # HA reports the configured NAME on the remote and the package on the twin; the link is never echoed.
    expected = {name, package, activity}
    # An app takes a few seconds to come up and the TV passes through its home screen on the
    # way; read until it reports the app, a browser or the Play Store, six reads at most.
    for _ in range(6):
        _settle()
        after = {s.get('entity_id'): s for s in ha_api.get_states(ttl=0)}
        seen = {(after.get(t) or {}).get('attributes', {}).get('app_id') for t in twins}
        seen.add((after.get(eid) or {}).get('attributes', {}).get('current_activity'))
        seen.discard(None)
        if seen & expected or before in expected or any(
                mark in s for s in seen if s != before for mark in ('browser', 'vending')):
            break
    already = before in expected
    # A TV already on that app proves nothing about the launch; say so rather than claim it.
    landed = bool(seen & expected) and not already
    elsewhere = next((s for s in seen if s != before and any(mark in s for mark in NOT_AN_APP)), None)
    if already:
        message = f"{remote['name']} was already on {name}."
    elif landed:
        message = f"{remote['name']} is on {name}."
    elif elsewhere:
        where = ('the Play Store' if 'vending' in elsewhere else
                 'the home screen' if 'launcherx' in elsewhere else 'its browser')
        message = f"{remote['name']} opened {where} instead of {name}; the app may not be installed on that TV."
    else:
        message = f"Asked {remote['name']} to open {name}; the TV has not reported the switch yet."
    return {'status': 'success', 'entity_id': eid, 'app': name, 'app_id': package, 'sent': activity,
            'landed': landed, 'already': already, 'state_after': (after.get(eid) or {}).get('state'),
            'message': message}


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
          hours=24, app='', acting_member=None, voice_context=None, source=None):
    """One boundary for every action: failures are plain results, never exceptions."""
    try:
        if ha_api.mode() == 'unconfigured':
            return {'status': 'error', 'message': 'Home Assistant is not connected.'}
        if action not in ('find', 'read', 'history', 'act', 'locate', 'app'):
            return {'status': 'error', 'message': 'Unknown house action. Use find, read, history, act, app or locate.'}
        catalogue = _catalogue()
        if action == 'app':
            return open_app(query, entity_id, app, catalogue)
        if action == 'find':
            if not str(query or '').strip():
                return {'status': 'error', 'message': 'Which device or room should I find?'}
            return find(query, domain, catalogue)
        if action == 'locate':
            return locate(query, entity_id, catalogue, acting_member, voice_context, source)
        if action == 'read' and not entity_id:
            categories = _category_blocks(query, catalogue)
            if categories:
                # 'Are all the doors locked' is a question about every lock, never about one.
                return {'status': 'success', 'categories': categories}
        entity = resolve(query, entity_id, domain, catalogue)
        if 'status' in entity:
            if action == 'read' and entity['status'] == 'ambiguous' and len(entity.get('devices') or []) == 1:
                # One device, many sensors ('read the powerwall'): the whole device is the answer.
                device = entity['devices'][0]
                on_it = {r['entity_id'] for r in device['entities']}
                return {'status': 'success', 'device': device,
                        'other': [_candidate(e) for _, e in _rank(catalogue, query, domain, limit=None)
                                  if e['entity_id'] not in on_it][:8]}
            return entity
        eid = entity['entity_id']
        if action == 'read':
            return _read(entity, catalogue)
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
