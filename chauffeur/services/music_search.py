"""Music search, grouped the way Music Assistant answered it.

The first cut of the music surfaces took MA's grouped search response and
FLATTENED it — five of each type, interleaved, in a fixed order. That threw
away the part the family actually missed from MA's own app: seeing the track
results as tracks and the albums as albums, and being able to say "only
playlists" or "only the Spotify ones".

Two paths produce the same shape:

  * Music Assistant directly (`ma_api`), when a token is configured. Full
    `MediaItem` payloads: `provider` and `provider_mappings` (the basis of the
    provider filter — HA's reduced dicts simply do not carry them), `favorite`,
    real artwork metadata.
  * The HA bridge (`music_assistant.search` service) otherwise. Reduced items,
    no provider information — the filter chips quietly don't exist rather than
    lying.

PROVIDER FILTERING IS OURS, not MA's: `music/search` takes media_types, limit
and library_only, but no provider argument — every item instead names where it
came from, so the filter is applied to the returned set. The chips are built
from the same set, which keeps them honest: a provider with nothing in these
results is not offered as a filter for them.

Artwork: MA serves art through its image proxy, reachable three ways depending
on the image. A remotely-accessible https path is used as-is; anything else
goes through MA's `/imageproxy` (by opaque `proxy_id` when the item carries
one, by the legacy double-encoded `path`+`provider` form when it does not).
Those proxy URLs are plain http:// on the LAN, which the browser-side
`MusicLogic.artwork()` already routes through the add-on's own image64 proxy —
the mixed-content rule stays in exactly one place.
"""
import time
from urllib.parse import quote

# Search/display order. Tracks first because that is what a family searching
# by name nearly always wants; the long-form types trail because most houses
# have none and an empty group simply doesn't render.
MEDIA_TYPES = ('track', 'album', 'playlist', 'artist', 'radio',
               'audiobook', 'podcast')

# MA's SearchResults keys per type ('radio' is its own plural).
_RESULT_KEYS = {'track': 'tracks', 'album': 'albums', 'playlist': 'playlists',
                'artist': 'artists', 'radio': 'radio',
                'audiobook': 'audiobooks', 'podcast': 'podcasts'}


class MusicSearchError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


_providers_cache = {'ts': 0.0, 'data': None}


def provider_names(ttl: float = 300) -> dict:
    """{domain: display name} for the configured MUSIC providers, so a chip
    can say "Spotify" rather than "spotify". Empty when MA is not reachable —
    the domain is a perfectly serviceable fallback label."""
    from services import ma_api
    now = time.time()
    if _providers_cache['data'] is not None \
            and now - _providers_cache['ts'] < ttl:
        return _providers_cache['data']
    out = {}
    configs = ma_api.command('config/providers', provider_type='music')
    if not isinstance(configs, list):
        configs = []
    for cfg in configs:
        if not isinstance(cfg, dict):
            continue
        domain = cfg.get('domain')
        if domain and domain not in out:
            out[domain] = cfg.get('name') or domain.replace('_', ' ').title()
    _providers_cache['ts'] = now
    _providers_cache['data'] = out
    return out


def _image_url(item, ma_base):
    """One artwork URL for a full MA item, or None. Prefers the thumb."""
    images = ((item.get('metadata') or {}).get('images')) or []
    img = next((i for i in images if i.get('type') == 'thumb'),
               images[0] if images else None)
    if not img:
        return None
    path = img.get('path') or ''
    if img.get('remotely_accessible') and path.startswith('https://'):
        return path
    if not ma_base:
        return path if path.startswith('http') else None
    if img.get('proxy_id'):
        return f"{ma_base}/imageproxy/{img['proxy_id']}?size=256"
    # Legacy form. The path is encoded twice on purpose — MA's own frontend
    # does the same, because the proxy decodes once at the route layer and
    # once when reading the parameter.
    return (f"{ma_base}/imageproxy?path={quote(quote(path, safe=''), safe='')}"
            f"&provider={img.get('provider') or ''}")


def _row_from_ma(item, ma_base):
    """A full MediaItem down to what a result row draws — same field names the
    HA-path rows already carry, so the surfaces never ask which path ran."""
    mappings = item.get('provider_mappings') or []
    domains = sorted({m.get('provider_domain') for m in mappings
                      if m.get('provider_domain')})
    provider = item.get('provider') or ''
    return {
        'uri': item.get('uri'),
        'name': item.get('name'),
        'media_type': item.get('media_type'),
        'artists': [{'name': a.get('name')} for a in (item.get('artists') or [])],
        'album': ({'name': (item.get('album') or {}).get('name')}
                  if item.get('album') else None),
        'owner': item.get('owner'),
        'image': _image_url(item, ma_base),
        'favorite': bool(item.get('favorite')),
        'in_library': provider == 'library',
        'providers': domains,
    }


def _row_from_ha(item, media_type):
    """HA's reduced dict, passed through with the same keys present-but-empty
    where HA has no answer. `favorite`/`in_library` are None rather than False:
    unknown and no are different answers, and a heart drawn hollow off a None
    would claim knowledge the HA path does not have."""
    return {
        'uri': item.get('uri'),
        'name': item.get('name'),
        'media_type': item.get('media_type') or media_type,
        'artists': item.get('artists') or [],
        'album': item.get('album'),
        'owner': item.get('owner'),
        'image': item.get('image') or item.get('image_url'),
        'favorite': None,
        'in_library': None,
        'providers': [],
    }


def _normalize_ha_artists(row):
    # The HA serializer has answered with both shapes over time: a list of
    # dicts and a list of names. subtitleOf reads .name, so strings get lifted.
    artists = row.get('artists') or []
    if artists and isinstance(artists[0], str):
        row['artists'] = [{'name': a} for a in artists]
    album = row.get('album')
    if isinstance(album, str):
        row['album'] = {'name': album}
    return row


def _search_ma(q, media_types, limit, library_only):
    from services import ma_api
    result = ma_api.command('music/search', search_query=q,
                            media_types=list(media_types) or None,
                            limit=limit,
                            library_only=bool(library_only) or None)
    if result is None:
        return None
    ma_base = ma_api.resolve_base()
    groups = []
    for mt in MEDIA_TYPES:
        if media_types and mt not in media_types:
            continue
        items = result.get(_RESULT_KEYS[mt]) or []
        if items:
            groups.append({'type': mt,
                           'items': [_row_from_ma(i, ma_base) for i in items]})
    return groups


def _search_ha(q, media_types, limit, library_only):
    from services import ha_api
    entry = _ha_entry_id()
    if not entry:
        raise MusicSearchError(503, 'Music Assistant integration not found')
    payload = {'config_entry_id': entry, 'name': q, 'limit': limit}
    if media_types:
        payload['media_type'] = list(media_types)
    if library_only:
        payload['library_only'] = True
    result = ha_api.call_service('music_assistant', 'search', payload,
                                 return_response=True)
    if result is None:
        raise MusicSearchError(502, 'Music Assistant search failed')
    data = result.get('service_response', result) or {}
    groups = []
    for mt in MEDIA_TYPES:
        if media_types and mt not in media_types:
            continue
        items = data.get(_RESULT_KEYS[mt]) or []
        if items:
            groups.append({'type': mt,
                           'items': [_normalize_ha_artists(_row_from_ha(i, mt))
                                     for i in items]})
    return groups


def _ha_entry_id():
    # main.py owns the cached config-entry lookup; imported lazily to keep
    # this module loadable in tests that never touch the app.
    import main
    return main._ma_entry_id()


def _provider_chips(groups):
    """The distinct provider domains present in these results, named and
    counted. Built BEFORE the provider filter runs, so the chips offer every
    real choice rather than only the one already chosen."""
    counts = {}
    for g in groups:
        for row in g['items']:
            for domain in row.get('providers') or []:
                counts[domain] = counts.get(domain, 0) + 1
    if not counts:
        return []
    names = provider_names()
    return [{'domain': d, 'name': names.get(d, d.replace('_', ' ').title()),
             'count': n}
            for d, n in sorted(counts.items(), key=lambda kv: -kv[1])]


def _apply_provider(groups, provider):
    if not provider:
        return groups
    out = []
    for g in groups:
        items = [r for r in g['items'] if provider in (r.get('providers') or [])]
        if items:
            out.append({'type': g['type'], 'items': items})
    return out


def search(q, media_types=None, limit=20, library_only=False, provider=None):
    """Grouped results, from MA when it answers and the HA bridge otherwise.

    `provider` narrows to results that exist on that provider (MA path only —
    the HA path has no provider data, and an impossible filter comes back as
    an ordinary empty result rather than an error)."""
    media_types = [t for t in (media_types or []) if t in MEDIA_TYPES]
    limit = max(1, min(int(limit or 20), 100))
    groups = _search_ma(q, media_types, limit, library_only)
    source = 'ma'
    if groups is None:
        source = 'ha'
        groups = _search_ha(q, media_types, limit, library_only)
    providers = _provider_chips(groups) if source == 'ma' else []
    groups = _apply_provider(groups, provider)
    return {'source': source, 'query': q, 'groups': groups,
            'providers': providers,
            'total': sum(len(g['items']) for g in groups)}
