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
                    '_device_id': row.get('device_id'), '_platform': row.get('platform'),
                    '_names': [name, row.get('name'), row.get('original_name'),
                               *list(row.get('aliases') or []), eid, eid.split('.', 1)[1]]})
    return out


def _candidate(entity):
    row = {**{k: entity[k] for k in ('entity_id', 'name', 'domain', 'state', 'aliases')},
           'ha_area': entity['area']}
    attrs = entity['_state'].get('attributes') or {}
    if entity['domain'] == 'remote' and 'activity_list' in attrs:
        row['apps'] = list(attrs.get('activity_list') or [])   # an Android TV: what it can open
    return row


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
           'state': state.get('state'), 'attributes': attributes,
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
        entity = resolve(query, entity_id, domain, catalogue)
        if 'status' in entity:
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
