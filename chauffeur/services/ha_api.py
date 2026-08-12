"""Thin REST client for the Home Assistant Core API.

Shared by notifications (notify.*), the family map (person states), and the
Music Assistant bridge (media_player + music_assistant services).

Base/token resolution order:
  1. Supervisor proxy (running as an HA add-on): http://supervisor/core/api
     with the SUPERVISOR_TOKEN env var. Requires `homeassistant_api: true`
     in config.yaml.
  2. Dev fallback: HA_BASE_URL + HA_TOKEN env vars, or `ha_base_url` +
     `ha_token` settings keys (long-lived access token, base like
     http://homeassistant.local:8123).

Every helper degrades to None/[]/False when HA is unreachable — the add-on
must boot and run fully without HA API access.
"""
import os
import threading
import time

import requests

_TIMEOUT = 8
_states_cache = {'ts': 0.0, 'data': None}
_cache_lock = threading.Lock()


def _base_and_token():
    token = os.environ.get('SUPERVISOR_TOKEN')
    if token:
        return 'http://supervisor/core/api', token

    base = os.environ.get('HA_BASE_URL', '')
    token = os.environ.get('HA_TOKEN', '')
    if not (base and token):
        from services import storage
        settings = storage.get_settings()
        base = settings.get('ha_base_url') or ''
        token = settings.get('ha_token') or ''
    if base and token:
        base = base.rstrip('/')
        if not base.endswith('/api'):
            base += '/api'
        return base, token
    return None, None


def mode() -> str:
    if os.environ.get('SUPERVISOR_TOKEN'):
        return 'supervisor'
    base, token = _base_and_token()
    return 'external' if base else 'unconfigured'


def _request(method, path, json_body=None, params=None, timeout=None):
    base, token = _base_and_token()
    if not base:
        return None
    try:
        resp = requests.request(
            method, f"{base}{path}",
            headers={'Authorization': f'Bearer {token}',
                     'Content-Type': 'application/json'},
            json=json_body, params=params, timeout=timeout or _TIMEOUT)
        if resp.status_code >= 400:
            print(f"[ha_api] {method} {path} -> {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json() if resp.text else {}
    except Exception as e:
        print(f"[ha_api] {method} {path} failed: {e}")
        return None


def is_available() -> bool:
    return _request('GET', '/config') is not None


def get_states(ttl: float = 5) -> list:
    """All entity states, with a short in-memory TTL so bursts of per-member
    lookups (map polls) cost one HTTP call. Serves the stale copy if HA is
    temporarily unreachable."""
    now = time.time()
    with _cache_lock:
        if _states_cache['data'] is not None and now - _states_cache['ts'] < ttl:
            return _states_cache['data']
    data = _request('GET', '/states')
    with _cache_lock:
        if data is None:
            return _states_cache['data'] or []
        _states_cache['ts'] = now
        _states_cache['data'] = data
        return data


def get_state(entity_id: str):
    for s in get_states():
        if s.get('entity_id') == entity_id:
            return s
    return None


def get_entities(domain: str) -> list:
    """[{entity_id, name, state}] for a domain ('person', 'media_player', ...),
    sorted by friendly name. Backed by the states cache."""
    prefix = domain.rstrip('.') + '.'
    out = []
    for s in get_states(ttl=30):
        eid = s.get('entity_id', '')
        if eid.startswith(prefix):
            out.append({
                'entity_id': eid,
                'name': (s.get('attributes') or {}).get('friendly_name') or eid,
                'state': s.get('state'),
            })
    return sorted(out, key=lambda e: (e['name'] or '').lower())


def list_notify_services() -> list:
    """Service names under the notify domain (e.g. 'mobile_app_jeffs_iphone')."""
    data = _request('GET', '/services')
    for domain in data or []:
        if domain.get('domain') == 'notify':
            return sorted((domain.get('services') or {}).keys())
    return []


def has_service(domain: str, service: str) -> bool:
    data = _request('GET', '/services')
    for d in data or []:
        if d.get('domain') == domain:
            return service in (d.get('services') or {})
    return False


def fetch_binary(path: str):
    """Fetch a binary asset (entity_picture / media proxy image). HA-relative
    paths go to the HA origin with our token. Absolute URLs (e.g. Music
    Assistant's http://<lan>:8095/imageproxy/...) are fetched directly and
    WITHOUT the HA token — never leak it to non-HA hosts. Returns
    (content, content_type) or None. Callers validate the target."""
    try:
        if path.startswith(('http://', 'https://')):
            resp = requests.get(path, timeout=10)
        else:
            base, token = _base_and_token()
            if not base:
                return None
            root = base[:-len('/api')] if base.endswith('/api') else base
            resp = requests.get(f"{root}{path}",
                                headers={'Authorization': f'Bearer {token}'},
                                timeout=10)
        if resp.status_code >= 400:
            return None
        return resp.content, resp.headers.get('Content-Type', 'image/jpeg')
    except Exception as e:
        print(f"[ha_api] GET {path} (binary) failed: {e}")
        return None


def core_origins() -> list:
    """Where Home Assistant's own web server can be reached, in order to try.

    NOT the Supervisor proxy, and that distinction cost a shipped release. The
    proxy at `http://supervisor/core` forwards `/core/api` and
    `/core/websocket` and nothing else — it is a proxy to the API, not to Home
    Assistant. Every existing caller of `fetch_binary` passes an `/api/…` path
    (see main._HA_IMAGE_PREFIXES), so this limit stayed invisible until
    something asked for `/local/…` and got a 404 dressed up as "Home Assistant
    would not hand over that file".

    Add-ons share a network with the Core container, which answers to the
    hostname `homeassistant` on 8123. That is the route to anything HA serves
    that is not the API.
    """
    out = []
    if os.environ.get('SUPERVISOR_TOKEN'):
        out.append('http://homeassistant:8123')
    base = os.environ.get('HA_BASE_URL', '')
    if not base:
        from services import storage
        base = (storage.get_settings() or {}).get('ha_base_url') or ''
    base = (base or '').rstrip('/')
    if base.endswith('/api'):
        base = base[:-len('/api')]
    if base and base not in out:
        out.append(base)
    return out


def fetch_static(path: str):
    """(content, content_type) for one of HA's UNAUTHENTICATED static files —
    `/local/…` (which is /config/www), `/hacsfiles/…`, `/static/…` — or None.

    Deliberately tokenless. Home Assistant serves these without auth (its own
    frontend has to load before anybody has signed in), and the token would not
    be valid against the Core container directly anyway. Callers validate the
    path; nothing here should ever be handed a caller's raw input.
    """
    if not path.startswith('/'):
        return None
    for origin in core_origins():
        try:
            resp = requests.get(f"{origin}{path}", timeout=10)
        except Exception as e:
            print(f"[ha_api] static {origin}{path[:60]} failed: {e}")
            continue
        if resp.status_code < 400:
            return resp.content, resp.headers.get('Content-Type',
                                                  'application/octet-stream')
        print(f"[ha_api] static {origin}{path[:60]} -> {resp.status_code}")
    return None


_history_cache = {}
_HISTORY_TTL = 300


def get_history(entity_id: str, hours: int = 24) -> list:
    """[(datetime, state_string)] for one entity over the last `hours`.

    Cached for five minutes, which is not laziness: the board rebuilds every
    twenty seconds and a graph card would otherwise run a history query per
    sensor per rebuild, forever, on a display nobody is looking at. A 24-hour
    line does not visibly change in five minutes.

    `minimal_response` and `no_attributes` are what keep this cheap — the full
    shape carries every attribute on every sample, and a graph needs a number
    and a timestamp.
    """
    import datetime as _dt
    key = (entity_id, int(hours))
    now = time.time()
    with _cache_lock:
        held = _history_cache.get(key)
        if held and now - held[0] < _HISTORY_TTL:
            return held[1]
    start = (_dt.datetime.now(_dt.timezone.utc)
             - _dt.timedelta(hours=max(1, int(hours))))
    data = _request('GET', f'/history/period/{start.isoformat()}', params={
        'filter_entity_id': entity_id,
        'minimal_response': '',
        'no_attributes': '',
        'significant_changes_only': '0',
    })
    rows = []
    for series in (data or []):
        for point in (series or []):
            stamp = point.get('last_changed') or point.get('last_updated')
            if stamp and point.get('state') is not None:
                rows.append((stamp, point.get('state')))
    with _cache_lock:
        # A failed fetch caches NOTHING, so a graph that could not load tries
        # again on the next rebuild rather than showing an empty line for five
        # minutes because Home Assistant was restarting.
        if data is not None:
            _history_cache[key] = (now, rows)
            if len(_history_cache) > 40:
                _history_cache.pop(next(iter(_history_cache)), None)
        elif held:
            return held[1]
    return rows


def get_config_entry_id(domain: str):
    """Config entry id for an integration (e.g. 'music_assistant') — required
    by MA's search/get_library services. Uses HA's config-entries HTTP view
    (admin; the supervisor/long-lived token qualifies)."""
    data = _request('GET', f'/config/config_entries/entry?domain={domain}')
    if isinstance(data, list) and data:
        entry = data[0]
        return entry.get('entry_id')
    return None


def fire_event(event_type: str, data: dict = None):
    """POST /api/events/{event_type} — put an event on the HA bus so the
    family's automations can react (e.g. `chauffeur_moment` → browser_mod
    popup on the wall panel). Payloads must stay small: URLs, never media
    bytes. Returns None when HA is unreachable, like everything here."""
    return _request('POST', f'/events/{event_type}', json_body=data or {})


def call_service(domain: str, service: str, data: dict = None,
                 return_response: bool = False, timeout: float = None):
    """POST /api/services/{domain}/{service}. With return_response=True the
    result is HA's {'changed_states': [...], 'service_response': {...}} wrapper
    (supported for response-capable services on any recent HA). `timeout`
    overrides the module default for services HA holds open while they run
    (assist_satellite.announce blocks until the satellite finishes speaking)."""
    params = {'return_response': 'true'} if return_response else None
    return _request('POST', f'/services/{domain}/{service}',
                    json_body=data or {}, params=params, timeout=timeout)


def render_template(template: str):
    """POST /api/template — render a Jinja template on the HA side. The
    registry functions (areas, area_name, area_entities, area_id) are only
    reachable this way over REST; the registries themselves are WebSocket-only
    and this app deliberately speaks REST alone. Callers must end the template
    with `| to_json` — the endpoint returns the rendered TEXT, and _request
    parses it as JSON. Returns None when HA is unreachable or the render
    errors (HA answers 400)."""
    return _request('POST', '/template', json_body={'template': template})


_area_cache = {'ts': 0.0, 'data': None}


def get_area_map(ttl: float = 60) -> list:
    """[{'id', 'name', 'entities': [entity_ids]}] for every HA area, via the
    template API. area_entities() resolves device-inherited membership — most
    entities carry no area_id of their own and get it from their device —
    which is exactly the logic not worth reimplementing client-side. Cached
    like get_states; serves the stale copy when HA is unreachable."""
    now = time.time()
    with _cache_lock:
        if _area_cache['data'] is not None and now - _area_cache['ts'] < ttl:
            return _area_cache['data']
    tpl = ("[{% for a in areas() %}"
           "{{ {'id': a, 'name': area_name(a),"
           " 'entities': area_entities(a) | list} | to_json }}"
           "{{ ',' if not loop.last else '' }}"
           "{% endfor %}]")
    data = render_template(tpl)
    with _cache_lock:
        if not isinstance(data, list):
            return _area_cache['data'] or []
        _area_cache['ts'] = now
        _area_cache['data'] = data
        return data


def _ws_url_and_token():
    token = os.environ.get('SUPERVISOR_TOKEN')
    if token:
        return 'ws://supervisor/core/websocket', token
    base, token = _base_and_token()
    if not base:
        return None, None
    ws = base.replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)
    return f"{ws}/websocket", token          # base already ends with /api


def ws_command(command: str, timeout: float = 8, **fields):
    """One-shot Core WebSocket command: connect → auth → one command → close.

    Assist pipeline config (and the registries proper) live behind the
    WebSocket API only. This deliberately stays a ONE-SHOT — the REST-only
    rule was protecting against a persistent client to keep alive, not
    against the transport itself. Extra fields ride the command message
    (engine_id, pipeline_id, …). Returns the command's `result` or None."""
    url, token = _ws_url_and_token()
    if not url:
        return None
    try:
        import json as _json
        from websockets.sync.client import connect
        with connect(url, open_timeout=timeout, close_timeout=timeout) as ws:
            for _ in range(3):
                msg = _json.loads(ws.recv(timeout))
                if msg.get('type') == 'auth_required':
                    ws.send(_json.dumps({'type': 'auth', 'access_token': token}))
                elif msg.get('type') == 'auth_ok':
                    break
                elif msg.get('type') == 'auth_invalid':
                    return None
            else:
                return None
            ws.send(_json.dumps({'id': 1, 'type': command, **fields}))
            while True:
                msg = _json.loads(ws.recv(timeout))
                if msg.get('id') == 1 and msg.get('type') == 'result':
                    return msg.get('result') if msg.get('success') else None
    except Exception as e:
        print(f"[ha_api] ws {command} failed: {e}")
        return None


_pipeline_cache = {'ts': 0.0, 'data': None}


def _pick_argyle_pipeline(listing: dict):
    """The Assist pipeline that fronts THIS app — the one whose conversation
    agent is the chauffeur_conversation entity (its id carries the
    config-entry title, so match 'chauffeur' or 'argyle') — else HA's
    preferred pipeline. Returns the raw pipeline dict or None."""
    pipelines = (listing or {}).get('pipelines') or []
    if not pipelines:
        return None
    pick = next((p for p in pipelines
                 if any(w in (p.get('conversation_engine') or '').lower()
                        for w in ('chauffeur', 'argyle'))), None)
    if not pick:
        pref = (listing or {}).get('preferred_pipeline')
        pick = next((p for p in pipelines if p.get('id') == pref), pipelines[0])
    return pick


def get_pipeline_tts(ttl: float = 300):
    """{'id', 'name', 'engine', 'voice', 'language'} of the Argyle pipeline
    (see _pick_argyle_pipeline). This is how the tts.speak announcement path
    speaks in the SAME voice the satellites answer in. Cached; serves the
    stale copy when the WebSocket is unavailable."""
    now = time.time()
    with _cache_lock:
        if _pipeline_cache['data'] is not None and now - _pipeline_cache['ts'] < ttl:
            return _pipeline_cache['data']
    pick = _pick_argyle_pipeline(ws_command('assist_pipeline/pipeline/list'))
    if not pick:
        return _pipeline_cache['data']
    data = {'id': pick.get('id'), 'name': pick.get('name'),
            'engine': pick.get('tts_engine'), 'voice': pick.get('tts_voice'),
            'language': pick.get('tts_language')}
    with _cache_lock:
        _pipeline_cache['ts'] = now
        _pipeline_cache['data'] = data
    return data


def list_tts_voices(engine_id: str, language: str = None) -> list:
    """[{'voice_id', 'name'}] a TTS engine offers, via tts/engine/voices."""
    fields = {'engine_id': engine_id}
    if language:
        fields['language'] = language
    res = ws_command('tts/engine/voices', **fields)
    return (res or {}).get('voices') or []


# Every field assist_pipeline/pipeline/update expects back. The update is a
# whole-object PUT in websocket clothing — omitting a field would null it on
# the pipeline — and unknown extras fail validation, so an allowlist it is.
_PIPELINE_FIELDS = ('name', 'language', 'conversation_engine',
                    'conversation_language', 'stt_engine', 'stt_language',
                    'tts_engine', 'tts_language', 'tts_voice',
                    'wake_word_entity', 'wake_word_id')


def set_pipeline_voice(voice: str) -> bool:
    """Write a tts_voice onto the Argyle pipeline — the single source of
    truth every mouth reads (satellite replies, satellite announces, and our
    tts.speak fallback via get_pipeline_tts). Chauffeur stores nothing: a
    stored copy would split-brain the moment somebody edited the pipeline in
    HA's own UI. Busts the pipeline cache on success."""
    pick = _pick_argyle_pipeline(ws_command('assist_pipeline/pipeline/list'))
    if not pick or not pick.get('id'):
        return False
    fields = {k: pick.get(k) for k in _PIPELINE_FIELDS}
    fields['tts_voice'] = voice
    ok = ws_command('assist_pipeline/pipeline/update',
                    pipeline_id=pick['id'], **fields)
    if ok is None:
        return False
    with _cache_lock:
        _pipeline_cache.update(ts=0.0, data=None)
    return True


def resolve_area_id(name: str):
    """HA's own area lookup — area_id() matches registered names AND aliases,
    and aliases are not enumerable over REST, so this is the only way spoken
    nicknames ('the pool') resolve without duplicating them in our settings.
    Returns the area id string or None."""
    cleaned = ''.join(c for c in (name or '') if c not in '{}"\'\\')
    if not cleaned.strip():
        return None
    return render_template('{{ area_id("' + cleaned.strip() + '") | to_json }}')


def get_weather_forecast(entity_id: str = None, kind: str = 'daily') -> list:
    """Forecast entries for a weather entity via weather.get_forecasts
    (each ~{datetime, condition, temperature, templow,
    precipitation_probability}). entity_id None/'' auto-detects the first
    weather.* entity. Returns [] whenever HA, the entity, or the service is
    unavailable — weather is garnish and must never break a caller."""
    try:
        if not entity_id:
            ents = get_entities('weather')
            entity_id = ents[0]['entity_id'] if ents else None
        if not entity_id:
            return []
        resp = call_service('weather', 'get_forecasts',
                            {'entity_id': entity_id, 'type': kind},
                            return_response=True)
        sr = (resp or {}).get('service_response') or resp or {}
        forecast = (sr.get(entity_id) or {}).get('forecast')
        return forecast if isinstance(forecast, list) else []
    except Exception as e:
        print(f"[ha_api] weather forecast failed: {e}")
        return []
