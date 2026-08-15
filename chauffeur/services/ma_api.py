"""Music Assistant's own API, spoken directly.

`ha_api` already reaches Music Assistant — through Home Assistant, over the six
actions the MA integration exposes (`play_media`, `play_announcement`,
`transfer_queue`, `get_queue`, `search`, `get_library`). That route stays, and
this module is deliberately NOT its replacement: it needs no credential of its
own, it works the moment the add-on boots, and MA's command names carry no
stability promise the way HA's actions do. When this client is not configured
or not answering, every caller here returns None and the HA bridge is what runs.

What the six actions cannot do, and never will:

  * The queue as a LIST you can reorder and delete from. HA's `get_queue`
    answers with the current and next item; a family looking at a kitchen
    panel wants to see what is coming and drop the third thing.
  * REMOVE a favourite. There is no un-favourite anywhere in HA's surface —
    the integration's only write is a per-player button that adds whatever is
    playing right now.
  * Which provider a search result came from. HA's search hands back a reduced
    dict; MA's own carries `provider` and `provider_mappings` per item, which
    is the whole basis of a provider filter.
  * MA's recommendations, recently-played and in-progress shelves; playlist
    writes; the provider list itself (`config/providers`).

Home Assistant has said it does not intend to add further media player actions,
so this is not a gap that closes by waiting.

TRANSPORT — and this is the part worth knowing before assuming a socket:
MA 2.7 serves its ENTIRE command set over plain HTTP as well as over the
WebSocket. `POST http://<host>:8095/api` with `{message_id, command, args}` and
a bearer token, self-documented at `http://<host>:8095/api-docs`. So this is a
request/response client shaped exactly like `ha_api`, not a socket client. The
socket adds only server-pushed events, and the boards deliberately do not want
those: they ride a ten-second poll on purpose so a cached payload can never
disagree with a live one.

AUTH: a long-lived token created by hand in MA's UI (Settings → Profile),
stored as the `ma_token` setting. There is no Supervisor shortcut the way there
is for Home Assistant, so this is the one thing a family has to do themselves —
which is exactly why nothing here may be load-bearing.
"""
import json
import threading
import time

import requests

# MA's HTTP API port. Not the Sendspin audio port (8927) the relay uses.
API_PORT = 8095
_TIMEOUT = 10

# The official Music Assistant add-on's hostname on HA's internal docker
# network. Shared with the Sendspin relay in main.py, which is why it lives
# here rather than being written out twice.
ADDON_HOST = 'd5369777-music-assistant'

_lock = threading.Lock()
# Everything the health endpoint needs to explain itself, kept from the last
# real attempt. A wall panel has no devtools, so "unreachable" is never a good
# enough answer — it has to say which hosts were tried, or the family is left
# guessing between a wrong address, a missing token and a stopped add-on.
_status = {
    'base': None,         # resolved API base, e.g. http://192.168.1.50:8095
    'ok': False,          # last request succeeded
    'detail': '',         # a sentence for a human
    'version': None,      # MA's own version string, from /info
    'tried': [],          # hosts probed during the last resolve
    'checked': 0.0,       # when we last resolved
}


def reset():
    """Forget the resolved host and every diagnosis. Called when the settings
    change (a new URL or token must not wait behind a cached failure) and by
    tests."""
    with _lock:
        _status.update(base=None, ok=False, detail='', version=None,
                       tried=[], checked=0.0)


def _settings():
    from services import storage
    try:
        return storage.get_settings() or {}
    except Exception:
        return {}


def token() -> str:
    return (_settings().get('ma_token') or '').strip()


def configured_host() -> str:
    """The host part of the `ma_server_url` setting, whatever shape it was
    typed in. That setting predates this module — it was written for the
    Sendspin relay, so it may well carry `ws://` and port 8927, neither of
    which means anything here. Only the hostname survives."""
    raw = (_settings().get('ma_server_url') or '').strip()
    if not raw:
        return ''
    for prefix in ('ws://', 'wss://', 'http://', 'https://'):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    host = raw.split('/', 1)[0]
    # Strip a port: the one they typed is for whichever service they were
    # thinking of, and the API is always on 8095.
    if ':' in host:
        host = host.rsplit(':', 1)[0]
    return host.strip()


def fallback_hosts() -> list:
    """Where Music Assistant lives when nobody has said. Ordered by how likely
    it is to be right, and shared with the Sendspin relay so a house that gains
    a new plausible location gains it for both."""
    out = [ADDON_HOST]
    import os
    ha_base = (os.environ.get('HA_BASE_URL', '')
               or _settings().get('ha_base_url', '') or '')
    if ha_base:
        try:
            from urllib.parse import urlparse
            host = urlparse(ha_base).hostname
            # Under the Supervisor `ha_base_url` is `http://supervisor/core`,
            # and `supervisor` is HA's own proxy — never Music Assistant.
            if host and host != 'supervisor':
                out.append(host)
        except Exception:
            pass
    out.append('homeassistant.local')
    seen = set()
    return [h for h in out if h and not (h in seen or seen.add(h))]


def candidate_hosts() -> list:
    """The configured host first, then the guesses."""
    configured = configured_host()
    hosts = ([configured] if configured else []) + fallback_hosts()
    seen = set()
    return [h for h in hosts if not (h in seen or seen.add(h))]


def _probe(host: str):
    """MA's unauthenticated `/info` — the same endpoint its own discovery uses.
    Probing with this rather than a real command separates the two failures
    that look identical from the outside: a wrong address answers nothing, a
    wrong TOKEN answers /info happily and then refuses the command. Telling
    those apart is most of the value of the health endpoint."""
    url = f'http://{host}:{API_PORT}/info'
    try:
        resp = requests.get(url, timeout=4)
        if resp.status_code >= 400:
            return None
        return resp.json() or {}
    except Exception:
        return None


def resolve_base(force: bool = False):
    """The API base for this house, or None. Cached for a minute after a
    failure so a music card polling every ten seconds does not re-probe four
    hosts each time — the discovery is the expensive part, not the command."""
    with _lock:
        if _status['base'] and not force:
            return _status['base']
        if not force and _status['checked'] and time.time() - _status['checked'] < 60:
            return None
        tried = []
    for host in candidate_hosts():
        tried.append(host)
        info = _probe(host)
        if info is not None:
            base = f'http://{host}:{API_PORT}'
            with _lock:
                _status.update(
                    base=base, tried=tried, checked=time.time(),
                    version=info.get('server_version') or info.get('version'))
            print(f"[ma_api] Music Assistant found at {base} "
                  f"(version {_status['version']})")
            return base
    with _lock:
        _status.update(base=None, ok=False, tried=tried, checked=time.time(),
                       detail='Music Assistant did not answer on port '
                              f'{API_PORT} at: ' + ', '.join(tried))
    return None


def command(name: str, timeout: float = None, **args):
    """One MA command. Returns its result, or None for every kind of failure —
    no host, no token, a refused token, an error from MA itself. Callers are
    all fall-back-shaped, so a raise here would only be caught and dropped one
    frame up; the reason lands in `_status` instead, where the health endpoint
    can say it out loud."""
    tok = token()
    if not tok:
        with _lock:
            _status.update(ok=False, detail='No Music Assistant token yet — '
                           'create one in Music Assistant under Settings → '
                           'Profile and paste it into Chauffeur’s settings.')
        return None
    base = resolve_base()
    if not base:
        return None
    payload = {'message_id': str(int(time.time() * 1000)),
               'command': name,
               'args': {k: v for k, v in args.items() if v is not None}}
    try:
        resp = requests.post(f'{base}/api', json=payload,
                             headers={'Authorization': f'Bearer {tok}',
                                      'Content-Type': 'application/json'},
                             timeout=timeout or _TIMEOUT)
    except Exception as e:
        with _lock:
            _status.update(ok=False, base=None,
                           detail=f'{name} could not reach {base}: {e}')
        return None
    if resp.status_code in (401, 403):
        with _lock:
            _status.update(ok=False, detail='Music Assistant refused the '
                           'token. Create a fresh long-lived token under '
                           'Settings → Profile and paste it in again.')
        print(f"[ma_api] {name} -> {resp.status_code} (token refused)")
        return None
    if resp.status_code >= 400:
        with _lock:
            _status.update(ok=False,
                           detail=f'{name} failed: HTTP {resp.status_code}')
        print(f"[ma_api] {name} -> {resp.status_code}: {resp.text[:200]}")
        return None
    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError):
        with _lock:
            _status.update(ok=False, detail=f'{name} returned no JSON')
        return None
    # MA answers a command with {message_id, result} and a failure with an
    # error_code plus details. Both are HTTP 200, so the status code alone
    # never tells you whether the command worked.
    if isinstance(body, dict):
        if body.get('error_code') or body.get('error'):
            detail = (body.get('details') or body.get('error')
                      or body.get('error_code'))
            with _lock:
                _status.update(ok=False, detail=f'{name}: {detail}')
            print(f"[ma_api] {name} error: {detail}")
            return None
        if 'result' in body:
            with _lock:
                _status.update(ok=True, detail='')
            # Void commands (queue edits, favourites writes) answer with
            # result: null on SUCCESS. None is this module's failure value,
            # so a successful nothing comes back as {} — callers test
            # `is not None`, and null-success must not read as failure.
            return body['result'] if body['result'] is not None else {}
    with _lock:
        _status.update(ok=True, detail='')
    return body


def available() -> bool:
    """Whether the MA path can be used at all. Cheap: no request when there is
    no token, and the host resolution behind it is cached."""
    return bool(token()) and bool(resolve_base())


def health() -> dict:
    """What a settings page shows next to the token field, and the first thing
    to read when the music surface is behaving oddly."""
    tok = bool(token())
    base = resolve_base() if tok else None
    if tok and base:
        # A real command, because reaching /info proves only that something is
        # listening — the token is still unverified at this point.
        ok = command('players/all') is not None
    else:
        ok = False
        if not tok:
            with _lock:
                _status['detail'] = ('No Music Assistant token yet — create '
                                     'one in Music Assistant under Settings → '
                                     'Profile.')
    with _lock:
        return {'configured': tok, 'base': _status['base'], 'ok': bool(ok),
                'version': _status['version'], 'detail': _status['detail'],
                'tried': list(_status['tried']),
                'host_setting': configured_host()}
