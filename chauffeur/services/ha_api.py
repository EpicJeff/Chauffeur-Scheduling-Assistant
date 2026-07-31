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


def _request(method, path, json_body=None, params=None):
    base, token = _base_and_token()
    if not base:
        return None
    try:
        resp = requests.request(
            method, f"{base}{path}",
            headers={'Authorization': f'Bearer {token}',
                     'Content-Type': 'application/json'},
            json=json_body, params=params, timeout=_TIMEOUT)
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


def get_config_entry_id(domain: str):
    """Config entry id for an integration (e.g. 'music_assistant') — required
    by MA's search/get_library services. Uses HA's config-entries HTTP view
    (admin; the supervisor/long-lived token qualifies)."""
    data = _request('GET', f'/config/config_entries/entry?domain={domain}')
    if isinstance(data, list) and data:
        entry = data[0]
        return entry.get('entry_id')
    return None


def call_service(domain: str, service: str, data: dict = None,
                 return_response: bool = False):
    """POST /api/services/{domain}/{service}. With return_response=True the
    result is HA's {'changed_states': [...], 'service_response': {...}} wrapper
    (supported for response-capable services on any recent HA)."""
    params = {'return_response': 'true'} if return_response else None
    return _request('POST', f'/services/{domain}/{service}',
                    json_body=data or {}, params=params)
