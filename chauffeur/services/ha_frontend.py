"""Hosting Home Assistant's OWN built-in cards, by borrowing its frontend.

services/ha_cards.py opens with the admission that built-in cards are out of
reach — `type: gauge` resolves to `hui-gauge-card`, which lives inside HA's
frontend bundle and is not a loadable resource. That was true of the webpack
era. Today's frontend is built by rspack into ES-module chunks, each exporting
its module map (`__webpack_modules__`), and the entrypoint's own runtime loads
them with a plain dynamic `import()`. Nothing about that machinery needs the
app around it — proven on 2026-08-24 by running `hui-thermostat-card`,
`hui-sensor-card` and `hui-area-card` on a bare page against a stub `hass`.

So this module reads three things out of HA's frontend, once per HA release:

  1. **The runtime.** The entrypoint (`app.<hash>.js`) sets up the module
     registry, the chunk filename map and the loader, then boots the app as
     its last statement. Replace that one call with `window.__haWpr = <require>`
     and the file becomes a loader with nothing to load — HA's own runtime,
     bug-for-bug, with no app behind it.
  2. **The chunk set.** A chunk's modules assume every chunk from their
     original import site is present, so the client must load the same set the
     lovelace panel loads. That set is the `Promise.all([...])` in the
     entrypoint whose chunks contain the card registry.
  3. **The card map.** The registry chunk carries HA's own lazy-load table —
     `{"alarm-panel": () => n.e(8537).then(n.bind(n, 25536)), ...}` — and,
     just before it, the eagerly-imported card modules (thermostat, sensor,
     tile, entities, glance, button, light, ...). Types in neither list do not
     exist in that HA release.

Everything here is EXTRACTION FROM MINIFIED CODE and will someday miss.
That is priced in: every consumer falls back to the converter drawings in
ha_card_convert, which keep working exactly as before. A failed extraction
costs the household HA's pixels, never a blank tile.

The extraction runs once per HA release (the app hash is in the filename) and
persists next to the database, so a rebooted add-on does not re-download 30MB
of chunks to relearn what it knew yesterday.
"""

import json
import os
import re
import threading
import time

# Card configs the browser may mount through the borrowed runtime. This is a
# NEGATIVE guard, not a feature list: the map extracted from HA's own frontend
# decides what exists; this only names the families we refuse to host because
# they need machinery we are not lending them (the statistics websocket, the
# energy collection) and would render an eternal spinner instead of failing.
UNHOSTABLE = re.compile(r'^(energy-|power-|water-|statistic)')

_LOCK = threading.Lock()
_BUNDLE = {'data': None, 'ts': 0.0, 'error': None}
_REG_CACHE = {'data': None, 'ts': 0.0}
_FAIL_TTL = 300          # do not hammer a broken HA on every board poll


def _cache_dir():
    from services import storage
    return os.path.join(os.path.dirname(storage.DB_PATH), 'ha_frontend')


# --- reading the entrypoint --------------------------------------------------

def find_app_path(index_html):
    """'/frontend_latest/app.<hash>.js' out of HA's index page, or None."""
    m = re.search(r'/frontend_latest/app\.([0-9a-f]{8,32})\.js',
                  str(index_html or ''))
    return (m.group(0), m.group(1)) if m else (None, None)


# Prepended to the patched entrypoint. HA's elements and the panel's shim
# elements share tag names, and a registry takes each name once — an exact
# duplicate `define` THROWS, and it throws inside a chunk's module
# evaluation, taking every module that shares the chunk down with it. That
# was the wall's "cards mount but features and area images don't": the
# shims defined first, and the chunks defining ha-form, ha-icon and their
# neighbours died mid-evaluation. First definition winning silently is the
# right rule for this page, in both directions.
_DEFINE_GUARD = ('(function(){var d=customElements.define.bind(customElements);'
                 'customElements.define=function(n,c,o){'
                 'if(!customElements.get(n)){d(n,c,o);}};})();')


def patch_runtime(src):
    """The entrypoint with its boot call swapped for a window export, and a
    duplicate-define guard in front.

    The last statement of the entrypoint is `<require>(<entry module>);` —
    everything before it is runtime setup. Replacing that single call is the
    entire patch: the module registry, filename map and loader stay exactly
    as HA shipped them, and nothing boots.
    """
    src = str(src or '')
    tail = re.search(
        r'([A-Za-z_$][\w$]*)\((\d+)\);\s*(?:$|//# sourceMappingURL)',
        src[-2000:])
    if not tail:
        return None
    call = f'{tail.group(1)}({tail.group(2)});'
    at = src.rfind(call)
    if at < 0:
        return None
    return (_DEFINE_GUARD + src[:at]
            + f'window.__haWpr={tail.group(1)};' + src[at + len(call):])


def chunk_filenames(src):
    """chunk id -> filename, from the runtime's own `u` function.

    The entrypoint builds chunk filenames as
    `(({33921:"recorder-worklet",...}[e]||e)+"."+{10021:"e6d8...",...}[e]+".js")`
    — a names map for the handful of worker chunks and a hash map for all of
    them. Both dicts are lifted verbatim.
    """
    m = re.search(
        r'\(\((\{[^{}]*?\})\[([A-Za-z_$][\w$]*)\]\|\|\2\)\+"\."\+'
        r'(\{[^{}]*?\})\[\2\]\+"\.js"', str(src or ''))
    if not m:
        return {}
    names = dict(re.findall(r'(\d+):"([^"]+)"', m.group(1)))
    hashes = dict(re.findall(r'(\d+):"([0-9a-f]{8,32})"', m.group(3)))
    return {cid: f'{names.get(cid, cid)}.{h}.js' for cid, h in hashes.items()}


def import_sites(src):
    """Every `Promise.all([x.e(1),...]).then(x.bind(x,MOD))` in the
    entrypoint, as (chunk ids, module id), largest chunk set first — the
    lovelace panel's is the biggest thing the app lazy-loads, so the card
    registry is found in the first site or two rather than the fortieth.
    """
    out = []
    for m in re.finditer(
            r'Promise\.all\(\[((?:[A-Za-z_$][\w$]*\.e\([\d.e]+\),?)+)\]\)'
            r'\.then\([A-Za-z_$][\w$]*\.bind\([A-Za-z_$][\w$]*,(\d+)\)\)',
            str(src or '')):
        chunks = [str(int(float(c)))
                  for c in re.findall(r'\.e\(([\d.e]+)\)', m.group(1))]
        out.append((chunks, m.group(2)))
    out.sort(key=lambda s: -len(s[0]))
    return out


# --- reading the card registry chunk -----------------------------------------

def extract_card_map(chunk_src):
    """HA's lazy card table: type -> {'chunks': [...], 'module': id}.

    The table is the frontend's own `{"alarm-panel": () => ...}` — the same
    one HA's card picker loads from — so a type present here is a type this
    HA release can actually build.
    """
    src = str(chunk_src or '')
    at = src.find('"alarm-panel":()=>')
    if at < 0:
        return {}
    # Only the map LITERAL. `alarm-panel` is its first key, so the nearest
    # `{` before the anchor opens it; balancing braces finds where it ends.
    # A fixed window overran into the next table (the editors load the same
    # way, keyed by the same type names) and quietly overwrote half the
    # entries with editor modules — a card map that mounts editors is worse
    # than none.
    open_at = src.rfind('{', 0, at)
    if open_at < 0:
        return {}
    depth, end = 0, len(src)
    for i in range(open_at, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    out = {}
    for m in re.finditer(
            r'"?([a-z][a-z0-9-]*)"?:\(\)=>'
            r'(Promise\.all\(\[[^\]]*\]\)|[A-Za-z_$][\w$]*\.e\([\d.e]+\)|'
            r'Promise\.resolve\(\))'
            r'\.then\([A-Za-z_$][\w$]*\.bind\([A-Za-z_$][\w$]*,(\d+)\)\)',
            src[open_at:end]):
        chunks = [str(int(float(c)))
                  for c in re.findall(r'\.e\(([\d.e]+)\)', m.group(2))]
        out[m.group(1)] = {'chunks': chunks, 'module': int(m.group(3))}
    return out


def extract_theme(app_src):
    """(base_vars, dark_vars) — HA's default theme, out of the entrypoint.

    The cards' and editors' tokens are applied by the app shell we do not
    boot, so the real cards drew geometry with no stroke — and the real
    editors drew fields with no outlines — until these were found. The
    entrypoint carries them as several big runs of CSS variable
    declarations, and the first cut of this took only two of them (the
    state-colour set and the dark background overrides), which left every
    `--ha-color-*` primitive, the semantic text/surface/form tokens and the
    whole `--wa-*` form-control layer undefined. A field with no
    `--wa-form-control-border-color` is a field with no border.

    Buckets, by marker:
      - BASE: the run naming the state colours, plus every mode-neutral
        run — the colour primitives (`--ha-color-primary-05`), the
        `--wa-*` component tokens, fonts, layout metrics.
      - LIGHT: the FIRST run defining `--ha-color-text-primary` (HA emits
        light semantics before dark).
      - DARK: the near-black background overrides plus the SECOND
        `--ha-color-text-primary` run.

    Served as a stylesheet CLASS on the host cell, which is what keeps the
    panel's own branding in charge: the panel tokens go on as inline
    properties, and inline beats class.
    """
    runs = [m.group(0) for m in
            re.finditer(r'(?:--[\w-]+\s*:[^;{}"`]+;)+', str(app_src or ''))
            if m.group(0).count('--') >= 20]
    base_parts, dark_parts, semantics = [], [], []
    for r in runs:
        if 'state-climate-heat-color' in r:
            base_parts.insert(0, r)
        elif ('--card-background-color:#1c1c1c' in r
                or '--primary-background-color:#11' in r):
            dark_parts.insert(0, r)
        elif '--ha-color-text-primary' in r:
            semantics.append(r)
        elif ('--ha-color-primary-05' in r or '--wa-' in r
                or '--ha-font-family-body' in r or '--header-height' in r):
            base_parts.append(r)
    if semantics:
        base_parts.append(semantics[0])          # light
        dark_parts.extend(semantics[1:2])        # dark, when HA ships one
    return ''.join(base_parts), ''.join(dark_parts)


def extract_i18n(app_src):
    """{'hash': <en file hash>, 'fragments': [...]} — the UI translation
    metadata, embedded in the entrypoint as a JSON.parse literal.

    The real editors' every label is a `ui.*` key resolved against
    fingerprinted files under /static/translations/ — `<lang>-<hash>.json`
    for the base and `<fragment>/<lang>-<hash>.json` for the rest, one hash
    per language across all of them. Without these the client can only
    humanize key tails, which is how a feature row came to be called
    "label"."""
    src = str(app_src or '')
    at = src.find('{"fragments":')
    if at < 0:
        return {}
    depth, end = 0, -1
    for i in range(at, min(len(src), at + 200000)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return {}
    try:
        meta = json.loads(src[at:end].replace("\'", "'"))
    except Exception:
        return {}
    en = ((meta.get('translations') or {}).get('en') or {})
    if not en.get('hash'):
        return {}
    return {'hash': en['hash'],
            'fragments': [f for f in (meta.get('fragments') or [])
                          if isinstance(f, str)]}


def extract_eager_modules(chunk_src):
    """The module ids of the cards the lovelace panel imports STATICALLY.

    The registry keeps a `new Set(["entity","entities",...])` of types that
    need no lazy load because their modules were imported right above it —
    `var s=n(37831),a=n(60275),...`. Those requires are the eager card
    modules; the client requires each one and the cards define themselves.
    """
    src = str(chunk_src or '')
    at = src.find('new Set(["entity","entities"')
    if at < 0:
        return []
    window = src[max(0, at - 1200):at]
    fns = re.findall(r'[A-Za-z_$][\w$]*=([A-Za-z_$][\w$]*)\((\d+)\)', window)
    if not fns:
        return []
    # The require function's minified name varies; the majority name in the
    # window is it, and anything called through another name is not a require.
    names = {}
    for fn, _ in fns:
        names[fn] = names.get(fn, 0) + 1
    require = max(names, key=names.get)
    seen, out = set(), []
    for fn, mod in fns:
        if fn == require and mod not in seen:
            seen.add(mod)
            out.append(int(mod))
    return out


# --- the bundle ---------------------------------------------------------------

# Bumped whenever what _extract PRODUCES changes shape — the patched
# runtime's prelude, a new meta field — so a cached extraction from an older
# build is redone rather than served with yesterday's patch. The app hash
# only says HA did not change; it cannot say WE did not.
PATCH_V = 4


def _load_cached(app_hash):
    try:
        meta_path = os.path.join(_cache_dir(), f'{app_hash}.json')
        runtime = os.path.join(_cache_dir(),
                               f'runtime.{app_hash}.p{PATCH_V}.js')
        if not (os.path.exists(meta_path) and os.path.exists(runtime)):
            return None
        with open(meta_path, encoding='utf-8') as f:
            meta = json.load(f)
        if meta.get('patch_v') != PATCH_V:
            return None
        return meta
    except Exception:
        return None


def _persist(app_hash, meta, runtime_src):
    try:
        os.makedirs(_cache_dir(), exist_ok=True)
        with open(os.path.join(_cache_dir(),
                               f'runtime.{app_hash}.p{PATCH_V}.js'),
                  'w', encoding='utf-8') as f:
            f.write(runtime_src)
        with open(os.path.join(_cache_dir(), f'{app_hash}.json'),
                  'w', encoding='utf-8') as f:
            json.dump(meta, f)
    except Exception as e:
        # A cache that cannot be written costs a re-extraction next boot,
        # nothing else.
        print(f'[ha_frontend] persist failed: {e}')


def runtime_source(app_hash):
    """The patched entrypoint for a bundle already extracted, or None. The
    file is named for the app hash AND our patch version: the URL is cached
    immutable in browsers, and a guard added to the patch must be a new URL
    or every wall keeps yesterday's runtime until somebody clears a cache."""
    if not re.match(r'^[0-9a-f]{8,32}$', str(app_hash or '')):
        return None
    try:
        with open(os.path.join(_cache_dir(),
                               f'runtime.{app_hash}.p{PATCH_V}.js'),
                  encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None


def _extract(fetch):
    """One full extraction against a live HA. Returns (meta, runtime) or
    raises ValueError naming the step that failed — the error is the useful
    part, because 'hosting broke' on some future HA release starts here."""
    index = fetch('/')
    if not index:
        raise ValueError('Home Assistant did not serve its index page')
    html = index[0] if isinstance(index, tuple) else index
    if isinstance(html, bytes):
        html = html.decode('utf-8', 'replace')
    app_path, app_hash = find_app_path(html)
    if not app_path:
        raise ValueError('no /frontend_latest/app.<hash>.js in the index page')

    cached = _load_cached(app_hash)
    if cached:
        return cached, None            # runtime already on disk

    app = fetch(app_path)
    if not app:
        raise ValueError(f'could not fetch {app_path}')
    app_src = app[0] if isinstance(app, tuple) else app
    if isinstance(app_src, bytes):
        app_src = app_src.decode('utf-8', 'replace')

    patched = patch_runtime(app_src)
    if not patched:
        raise ValueError('the entrypoint boot call was not where expected')
    files = chunk_filenames(app_src)
    if not files:
        raise ValueError('no chunk filename map in the entrypoint')
    sites = import_sites(app_src)
    if not sites:
        raise ValueError('no lazy import sites in the entrypoint')

    # The registry chunk is somewhere in the lovelace panel's import site.
    # Walk the largest sites, fetching one chunk at a time and stopping at
    # the first that carries the lazy card table.
    for chunks, _module in sites[:3]:
        for cid in chunks:
            fname = files.get(cid)
            if not fname:
                continue
            got = fetch(f'/frontend_latest/{fname}')
            if not got:
                continue
            src = got[0] if isinstance(got, tuple) else got
            if isinstance(src, bytes):
                src = src.decode('utf-8', 'replace')
            if '"alarm-panel":()=>' not in src:
                continue
            cards = extract_card_map(src)
            eager = extract_eager_modules(src)
            if not cards:
                raise ValueError('found the registry chunk but not its table')
            theme_base, theme_dark = extract_theme(app_src)
            meta = {
                'app_hash': app_hash,
                'patch_v': PATCH_V,
                'i18n': extract_i18n(app_src),
                'chunks': chunks,
                'files': files,
                'eager_modules': eager,
                'cards': {k: v for k, v in cards.items()
                          if not UNHOSTABLE.match(k)},
                'theme_base': theme_base,
                'theme_dark': theme_dark,
                'extracted_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            }
            return meta, patched
    raise ValueError('no chunk in the top import sites carries the card table')


def bundle(force=False):
    """The extracted frontend bundle, or None with the reason in last_error().

    Cached in memory for the process and on disk per app hash. `force` skips
    the in-memory copy (the deploy workflow's force_refresh path), not the
    per-hash disk cache — a hash that has not changed is a frontend that has
    not changed.
    """
    from services import ha_api
    now = time.time()
    with _LOCK:
        if not force and _BUNDLE['data'] is not None:
            return _BUNDLE['data']
        if not force and _BUNDLE['error'] and now - _BUNDLE['ts'] < _FAIL_TTL:
            return None
    try:
        meta, runtime = _extract(ha_api.fetch_static)
        if runtime is not None:
            _persist(meta['app_hash'], meta, runtime)
        with _LOCK:
            _BUNDLE.update(data=meta, ts=now, error=None)
        return meta
    except Exception as e:
        with _LOCK:
            _BUNDLE.update(data=None, ts=now, error=str(e))
        print(f'[ha_frontend] extraction failed: {e}')
        return None


def last_error():
    with _LOCK:
        return _BUNDLE['error']


def reset():
    """Test hook, and the force_refresh path's."""
    with _LOCK:
        _BUNDLE.update(data=None, ts=0.0, error=None)
        _REG_CACHE.update(data=None, ts=0.0)


# --- what the cards' hass needs beyond states ---------------------------------

def registries(ttl=300):
    """Slim entity/device/area registries plus HA's config, for the client's
    `hass`. The real cards read display precision, area membership and names
    from these; the fields kept are the fields read. HA absent -> empty maps,
    and the cards degrade the way HA's own do with a sparse registry."""
    now = time.time()
    with _LOCK:
        held = _REG_CACHE['data']
        if held is not None and now - _REG_CACHE['ts'] < ttl:
            return held
    from services import ha_api
    out = {'entities': {}, 'devices': {}, 'areas': {}, 'config': {}}
    rows = ha_api.ws_command('config/entity_registry/list') or []
    for r in rows:
        if not isinstance(r, dict) or not r.get('entity_id'):
            continue
        opts = r.get('options') or {}
        sensor = opts.get('sensor') or {}
        # `aliases` and friends ride along even when empty: HA's pickers
        # iterate these rows and call list methods on fields the app shell
        # always supplies — `aliases.join` on an absent field killed the
        # area picker outright.
        out['entities'][r['entity_id']] = {
            'entity_id': r['entity_id'],
            'name': r.get('name'),
            'icon': r.get('icon'),
            'area_id': r.get('area_id'),
            'device_id': r.get('device_id'),
            'translation_key': r.get('translation_key'),
            'platform': r.get('platform'),
            'display_precision': sensor.get('display_precision'),
            'hidden': bool(r.get('hidden_by')),
            'entity_category': r.get('entity_category'),
            'original_name': r.get('original_name'),
            'aliases': r.get('aliases') or [],
            'labels': r.get('labels') or [],
        }
    for r in ha_api.ws_command('config/device_registry/list') or []:
        if not isinstance(r, dict) or not r.get('id'):
            continue
        out['devices'][r['id']] = {
            'id': r['id'],
            'name': r.get('name_by_user') or r.get('name'),
            'name_by_user': r.get('name_by_user'),
            'area_id': r.get('area_id'),
            'model': r.get('model'),
            'manufacturer': r.get('manufacturer'),
            'labels': r.get('labels') or [],
        }
    for r in ha_api.ws_command('config/area_registry/list') or []:
        if not isinstance(r, dict) or not r.get('area_id'):
            continue
        # An area's photograph is an AUTHENTICATED HA path (/api/image/...),
        # and the real area card renders it as a bare <img> on our origin —
        # so it is rewritten through the same artwork proxy the converter's
        # drawing already uses (base64url form, because encoded slashes in a
        # query read like a traversal probe to some reverse proxies). The
        # client prefixes its apiBase; ha_image validates the decoded path.
        pic = r.get('picture')
        if pic:
            import base64
            enc = base64.urlsafe_b64encode(
                str(pic).encode('utf-8')).decode('ascii').rstrip('=')
            pic = f'api/ha/image64/{enc}'
        out['areas'][r['area_id']] = {
            'area_id': r['area_id'],
            'name': r.get('name'),
            'picture': pic,
            'icon': r.get('icon'),
            'floor_id': r.get('floor_id'),
            'aliases': r.get('aliases') or [],
            'labels': r.get('labels') or [],
        }
    cfg = ha_api.ws_command('get_config') or {}
    if isinstance(cfg, dict) and cfg:
        out['config'] = {
            'components': cfg.get('components') or [],
            'unit_system': cfg.get('unit_system') or {},
            'time_zone': cfg.get('time_zone'),
            'version': cfg.get('version'),
            'latitude': cfg.get('latitude'),
            'longitude': cfg.get('longitude'),
            'state': 'RUNNING',
        }
    # An empty answer is not worth caching for five minutes — HA may be a
    # second from finishing its boot.
    if out['entities'] or out['config']:
        with _LOCK:
            _REG_CACHE.update(data=out, ts=now)
    return out


_WS_PROXY_CACHE = {}
_WS_PROXY_TTL = 3600


def ws_resources(command, **fields):
    """One `frontend/get_icons` / `frontend/get_translations` answer, cached.

    The real cards resolve domain and attribute icons — and the editors
    their backend labels — over the websocket we are not lending the
    browser; the connection shim routes those exact message types here.
    The answers change on an HA update, so an hour of cache is plenty and
    a dead HA serves the stale copy rather than a hole."""
    key = (command, tuple(sorted(fields.items())))
    now = time.time()
    with _LOCK:
        held = _WS_PROXY_CACHE.get(key)
        if held and now - held[0] < _WS_PROXY_TTL:
            return held[1]
    from services import ha_api
    out = ha_api.ws_command(command, **fields)
    if not isinstance(out, dict):
        with _LOCK:
            held = _WS_PROXY_CACHE.get(key)
        return held[1] if held else {'resources': {}}
    with _LOCK:
        _WS_PROXY_CACHE[key] = (now, out)
        if len(_WS_PROXY_CACHE) > 64:
            _WS_PROXY_CACHE.pop(next(iter(_WS_PROXY_CACHE)), None)
    return out


def translations_file_allowed(path):
    """/static/translations proxy gate: fragment dir + fingerprinted json,
    nothing else."""
    return bool(re.match(r'^(?:[A-Za-z0-9_-]+/)?[A-Za-z-]+-[0-9a-f]{16,64}'
                         r'\.json$', str(path or '')))


def frontend_file_allowed(name):
    """Whether the chunk proxy may serve this filename. Chunk names only —
    one path segment, .js, no traversal. The proxy is tokenless (frontend
    files are unauthenticated) but staying narrow costs nothing."""
    return bool(re.match(r'^[A-Za-z0-9_-]+(\.[0-9a-f]{8,32})?\.js$',
                         str(name or '')))
