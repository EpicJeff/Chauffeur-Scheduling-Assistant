"""Running a REAL Home Assistant card inside a Chauffeur tile.

The `ha_dashboard` tile in home_board is a frame around Home Assistant's own
page, and its docstring makes the honest admission that you cannot run a
Lovelace card outside HA's frontend. This module is the attempt to make that
admission narrower, because the reasoning behind it was never quite right.

A Lovelace card is an ordinary custom element. HA's frontend hands it exactly
three things:

  1. a `hass` object — and the cards worth putting on a wall read one field of
     it, `hass.states`;
  2. a `setConfig(config)` call with the YAML you wrote, parsed;
  3. a pile of CSS custom properties, which is ALL an HA theme has ever been.

None of those needs HA's frontend to exist. What genuinely cannot be
reproduced is the fourth thing HA supplies implicitly: its own element
library — `ha-card`, `ha-icon`, `hui-warning` — which cards render into
without ever importing. Those we define ourselves, in the panel's own
colours, and that inversion is the whole trick: the card renders the shape,
Chauffeur supplies the surface, and the result matches the wall instead of
matching Home Assistant.

WHAT THIS CANNOT DO, stated up front so nobody rediscovers it on the wall:

  - **Built-in cards do not ship as files.** `type: gauge` resolves to
    `hui-gauge-card`, which lives inside HA's frontend bundle and is not a
    loadable resource — only `type: custom:…` cards can be fetched and run
    THIS way. They stopped being out of reach when HA's frontend became
    ES-module chunks: services/ha_frontend borrows the bundle's own runtime
    and the browser mounts the real hui-* elements (ha_card_host
    mountBuiltin), with ha_card_convert's drawings standing as the fallback
    wherever that borrowing fails.
  - **Cards that reach for HA's frontend internals.** Anything calling
    `loadCardHelpers()` or extending `hui-*` classes wants machinery we are
    not hosting. It will fail to define, and the tile says so.
  - **Cards driven by the statistics websocket** — the official energy
    dashboard cards — need a live subscription, not a state snapshot.

Everything that fails, fails ONTO the framed dashboard tile, which is still
there and still works. That is the point of keeping both.
"""

import json
import re
import threading

# Where a card's own JavaScript is allowed to come from. HACS installs land in
# /hacsfiles/, hand-installed ones in /local/ (that is /config/www/), and
# /community_plugin/ is where HACS put things before 2021 — households upgrade
# in their own time and old resource entries survive.
#
# This list is the entire security story of the proxy, so it is a list of
# PREFIXES on the Home Assistant origin and nothing else. The proxy holds a
# supervisor token; without this it would be an authenticated hole straight
# into HA, which is the mistake /api/ha/image already documents having avoided.
RESOURCE_PREFIXES = ('/hacsfiles/', '/local/', '/community_plugin/')

# An entity id, as it appears anywhere in a card's config. Deliberately narrow:
# this is used to decide which states to SEND, and a loose pattern would put
# arbitrary strings from a config into a lookup.
_ENTITY_RE = re.compile(r'^[a-z_]{2,}\.[a-z0-9_]+$')

_MDI_LOCK = threading.Lock()
_MDI_ICONS = {}          # 'solar-power' -> 'M11.45,2v6.55...'
_MDI_MISSING = set()     # asked for, not found — never ask twice
_MDI_META = {'parts': None, 'tried': False}


# --- the card's config ------------------------------------------------------

def parse_config(raw):
    """The YAML a household pasted out of Home Assistant, as a dict.

    Returns `(config, error)`. The error is a SENTENCE, because it goes on
    screen: a card config is hand-edited text and the failure everybody hits
    is a typo, not a subtle semantic problem.

    YAML rather than JSON because that is what HA shows you and what every
    card's documentation is written in. JSON parses as YAML anyway, so pasting
    either works and nobody has to be told which.
    """
    text = (raw or '').strip()
    if not text:
        return None, "Paste the card's YAML — the same text Home Assistant shows you."
    try:
        import yaml
        config = yaml.safe_load(text)
    except Exception as e:
        # yaml's own messages carry line/column and are better than anything
        # written here would be.
        return None, f"That is not valid YAML: {str(e).splitlines()[0]}"
    if not isinstance(config, dict):
        return None, "A card config is a block of `key: value` lines."
    if not config.get('type'):
        return None, "The config needs a `type:` line, e.g. type: custom:my-card"
    return config, None


def card_tag(config):
    """The custom element name a config asks for, or None.

    `type: custom:tesla-style-solar-power-card` is the only shape that names a
    loadable element. A built-in `type: gauge` means `hui-gauge-card`, which
    lives inside HA's own bundle — returning None for it is this module
    admitting the limit rather than fetching a URL that cannot exist.
    """
    t = str((config or {}).get('type') or '').strip()
    return t[len('custom:'):] or None if t.startswith('custom:') else None


def entity_ids(config):
    """Every entity id mentioned anywhere in a card config.

    This is what decides which states travel to the browser. The alternative —
    shipping all of `hass.states` — is several hundred kilobytes of somebody's
    house on every board poll, for a card that reads four sensors.

    A card that reads entities it was never configured with gets nothing for
    them and draws its own "unavailable", which is a card behaving normally
    rather than a tile behaving strangely.
    """
    found, seen = [], set()

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            s = node.strip()
            if _ENTITY_RE.match(s) and s not in seen:
                seen.add(s)
                found.append(s)

    walk(config)
    return found


def _shape(s):
    """One HA state row, in the shape `hass.states` carries it."""
    return {
        'entity_id': s.get('entity_id'),
        'state': s.get('state'),
        'attributes': s.get('attributes') or {},
        'last_changed': s.get('last_changed'),
        'last_updated': s.get('last_updated'),
        # Cards compare these by identity to decide whether to re-render.
        # Ours are rebuilt each poll, so the comparison always says
        # "changed" — correct, if slightly eager.
        'context': {'id': None, 'parent_id': None, 'user_id': None},
    }


def states_all():
    """The WHOLE house, for the board's shared pool.

    Exists because a card that DISCOVERS its entities — builds its own list
    of speakers, or TVs, or lights by walking `hass.states` — cannot be
    served by any slice chosen from its config: it names nothing, that is
    the point of it. The first fix for that was a per-tile "also send these
    entities" box, which worked and put the burden of knowing a card's
    internals on the person pasting YAML. Measurement retired it: a full
    house of states gzips to a few KB, and compression plus ONE copy per
    board payload (not one per tile) costs less than the box cost in
    explanation. The pool travels only when a board actually has a custom
    card on it — home_board attaches it, the host merges it under every
    card's own named states.
    """
    from services import ha_api
    return {s['entity_id']: _shape(s)
            for s in ha_api.get_states(ttl=10) or [] if s.get('entity_id')}


def states_for(ids):
    """`{entity_id: {state, attributes, ...}}` for the ids a card asked for.

    Shaped like HA's own `hass.states` because that is what the card is going
    to index into. Missing entities are simply absent, exactly as they are in
    HA when you name something that does not exist.
    """
    from services import ha_api
    wanted = set(ids or [])
    if not wanted:
        return {}
    out = {}
    for s in ha_api.get_states(ttl=10) or []:
        eid = s.get('entity_id')
        if eid in wanted:
            out[eid] = _shape(s)
    return out


# --- finding the card's own JavaScript --------------------------------------

def list_resources():
    """Home Assistant's registered Lovelace resources: [{url, type}].

    These are the files HA itself loads to make custom cards exist, so this is
    the authoritative answer to "where does this card live" — better than
    asking the household to find a path, and it means a card that works in
    their dashboard works here without being told anything.

    WebSocket-only, like the registries. Empty list when HA is unreachable or
    the household's dashboards are in YAML mode (where resources are declared
    in configuration.yaml and this command returns nothing) — in which case the
    tile's own resource field is the hand path.
    """
    from services import ha_api
    rows = ha_api.ws_command('lovelace/resources')
    out = []
    for r in rows or []:
        url = str((r or {}).get('url') or '').strip()
        if url:
            out.append({'url': url, 'type': (r or {}).get('type') or 'module'})
    return out


def _url_matches_tag(url, tag):
    """Does this resource URL look like it holds `tag`?

    Matching is on the file's stem against the element name, both stripped of
    punctuation: `/hacsfiles/tesla-style-solar-power-card/tesla-style-solar-power-card.js?hacstag=42`
    holds `tesla-style-solar-power-card`. The query string is HACS's cache
    buster and never part of the name.

    A stem is often shorter than the tag it defines (`power-flow-card-plus.js`
    defines `power-flow-card-plus`, but `mini-graph-card-bundle.js` defines
    `mini-graph-card`), so containment either way counts. This is a guess with
    a hand path behind it, not a contract — the tile lets you name the file.
    """
    path = url.split('?')[0].split('#')[0]
    stem = path.rsplit('/', 1)[-1]
    for suffix in ('.js', '.mjs'):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
    a = re.sub(r'[^a-z0-9]', '', stem.lower())
    b = re.sub(r'[^a-z0-9]', '', (tag or '').lower())
    if not a or not b:
        return False
    return a in b or b in a


def resolve_resource(tag, resources=None):
    """The resource row that probably defines `tag` — {url, type} — or None.

    The TYPE travels with the url because it changes how the browser must load
    the file: a bundle registered as a classic script can rely on top-level
    `var` globals, which module scope does not give it. HA knows which it
    registered, so nobody here has to guess.
    """
    if not tag:
        return None
    rows = resources if resources is not None else list_resources()
    for r in rows or []:
        if _url_matches_tag(r.get('url') or '', tag):
            return r
    return None


def resource_allowed(url):
    """Whether the proxy may fetch this. See RESOURCE_PREFIXES.

    Absolute URLs are refused outright — a resource entry pointing at a CDN is
    something the BROWSER can load on its own, and routing it through a proxy
    holding a supervisor token buys nothing and risks everything.
    """
    u = (url or '').split('?')[0]
    if not u.startswith('/') or '..' in u:
        return False
    return u.startswith(RESOURCE_PREFIXES)


def fetch_resource(url):
    """(javascript_text, content_type) for a card's bundle, or None.

    Served back on Chauffeur's own origin, which is the point: a standalone
    panel is a different origin from HA, HA does not send CORS headers for
    these files, and an ES-module card would therefore refuse to load. Proxied,
    the browser sees one origin and the question never comes up.
    """
    from services import ha_api
    if not resource_allowed(url):
        return None
    # fetch_STATIC, not fetch_binary: a card's file is not an API path, and
    # the Supervisor proxy only carries API paths. See ha_api.core_origins.
    result = ha_api.fetch_static(url)
    if not result:
        return None
    content, _ = result
    return content, 'application/javascript; charset=utf-8'


# --- icons ------------------------------------------------------------------
#
# The existing `ha` tile settles for a per-domain emoji, with a comment saying
# this app has no mdi font and a literal `mdi:thermometer` is worse than no
# icon. That was true of a tile drawing its own rows. A hosted card draws
# `<ha-icon icon="mdi:solar-power">` and expects a real icon, so the icons have
# to come from somewhere.
#
# They come from Home Assistant, which already has every one of them: the
# frontend ships MDI split into alphabetical chunks under /static/mdi/, with a
# metadata file naming the ranges. We read the same files HA's own ha-icon
# reads, which means the icon set can never drift from the one the household
# sees in HA.

def _fetch_json(path):
    from services import ha_api
    # `/static/mdi/…` is frontend static content, so the same route a card's
    # own file takes — not the API proxy.
    result = ha_api.fetch_static(path)
    if not result:
        return None
    try:
        return json.loads(result[0])
    except Exception:
        return None


def _mdi_chunk_file(name):
    """Which chunk file holds `name`, per HA's own findIconChunk: the parts are
    in order, each with the first icon name it contains, and an icon belongs to
    the last part whose start is not past it."""
    parts = _MDI_META.get('parts')
    if not parts:
        return None
    last = None
    for chunk in parts:
        start = chunk.get('start')
        if start is not None and name < start:
            break
        last = chunk
    return (last or {}).get('file')


def mdi_path(name):
    """The SVG path data for an mdi icon name, or None.

    `mdi:solar-power`, `solar-power` and an empty string all do the right
    thing. Everything is cached in memory, including the failures — a card
    with a typo'd icon name must not re-ask Home Assistant on every render.
    """
    icon = (name or '').strip()
    if icon.startswith('mdi:'):
        icon = icon[4:]
    if not icon or not re.match(r'^[a-z0-9-]+$', icon):
        return None
    with _MDI_LOCK:
        if icon in _MDI_ICONS:
            return _MDI_ICONS[icon]
        if icon in _MDI_MISSING:
            return None
        if not _MDI_META['tried']:
            _MDI_META['tried'] = True
            meta = _fetch_json('/static/mdi/iconMetadata.json') or {}
            _MDI_META['parts'] = meta.get('parts') or None
        chunk = _mdi_chunk_file(icon)
        if not chunk:
            _MDI_MISSING.add(icon)
            return None
        # A whole chunk arrives at once and is kept — the next icon on the
        # same card is almost certainly in the same alphabetical range.
        icons = _fetch_json(f'/static/mdi/{chunk}.json') or {}
        if not icons:
            _MDI_MISSING.add(icon)
            return None
        _MDI_ICONS.update({k: v for k, v in icons.items() if isinstance(v, str)})
        if icon not in _MDI_ICONS:
            _MDI_MISSING.add(icon)
            return None
        return _MDI_ICONS[icon]


def reset_icon_cache():
    """Tests, and the case of Home Assistant appearing after the panel booted
    (the metadata fetch is tried ONCE, so a panel that started before HA would
    otherwise never draw an icon again)."""
    with _MDI_LOCK:
        _MDI_ICONS.clear()
        _MDI_MISSING.clear()
        _MDI_META.update(parts=None, tried=False)


# --- what a tile needs to render one ----------------------------------------

def _resolve_hosts(hosts, states):
    """Each custom card found inside a native tree, with its file located.

    The resource list is fetched ONCE for the whole tree — it is a websocket
    round trip to Home Assistant, and a stack with three custom cards in it
    would otherwise make three of them on every board rebuild.

    A card whose file cannot be found keeps its place and carries an `error`.
    The cell it was given still exists, so the columns either side of it do not
    shuffle up to fill a hole that has no explanation in it.
    """
    if not hosts:
        return {}
    resources = None
    out = {}
    for host_id, host in hosts.items():
        entry = {'config': host['config'],
                 # The states this card asked for, out of the ones the whole
                 # tree already gathered — no second trip for a card that
                 # shares its sensors with the gauge beside it.
                 'states': {k: v for k, v in (states or {}).items()
                            if k in set(entity_ids(host['config']))}}
        # A BUILT-IN leaf: no file to find — the browser mounts it out of
        # HA's own frontend (services/ha_frontend), or leaves the converter
        # fallback standing. Nothing to resolve and nothing to get wrong.
        if host.get('builtin'):
            entry['builtin'] = host['builtin']
            out[host_id] = entry
            continue
        if resources is None:
            resources = list_resources()
        row = resolve_resource(host['tag'], resources)
        url = (row or {}).get('url')
        entry['tag'] = host['tag']
        if not url:
            entry['error'] = (f"Nothing in Home Assistant's resources looks "
                              f"like it defines `{host['tag']}`.")
        elif not resource_allowed(url):
            entry['error'] = ("That card's file is somewhere this cannot "
                              "fetch from.")
        else:
            entry['resource'] = url
            entry['resource_type'] = (row or {}).get('type') or 'module'
        out[host_id] = entry
    return out


def prepare(raw_config, resource_override=''):
    """Everything the browser needs to run one card, or an `error` sentence.

    Assembled server-side and shipped inside the board payload rather than
    fetched by the tile, because the board is ONE request per tick by design
    (home_board rule 2) and a card's states are just more board data.

    The states here are only the ids the config NAMES — enough for the
    native converter and the `missing` warning. A hosted card additionally
    receives the board's shared `states_all` pool in the browser, so a card
    that discovers its own devices sees the house without anyone having to
    know which parts of it the card walks.
    """
    config, error = parse_config(raw_config)
    if error:
        return {'error': error}

    tag = card_tag(config)
    if not tag:
        # A BUILT-IN card. Not loadable — `hui-gauge-card` lives inside HA's
        # frontend bundle — but its config completely describes it, so the ones
        # worth drawing are drawn natively instead. See ha_card_convert.
        from services import ha_card_convert
        kind = str(config.get('type') or '').strip().lower()
        if kind in ha_card_convert.NATIVE_CARDS \
                or kind in ha_card_convert.HOSTED_BUILTINS:
            ids = ha_card_convert.entity_ids(config)
            states = states_for(ids)
            hosts = {}
            card = ha_card_convert.convert(config, states, hosts=hosts)
            if card:
                return {'mode': 'native', 'card': card, 'config': config,
                        # A real dashboard's stacks are MIXED — a custom
                        # power-flow card above a gauge is the config people
                        # actually write. Each custom card inside the tree gets
                        # its file resolved here, once, and the browser runs it
                        # in the cell the drawing left for it. A BUILT-IN leaf
                        # is a host too now, mounted out of HA's own frontend
                        # (services/ha_frontend) over its converter fallback.
                        'hosts': _resolve_hosts(hosts, states),
                        'missing': [e for e in ids if e not in states]}
        # Refused BY NAME, with the way to get it anyway. A built-in that
        # rendered as an empty box is the failure the whole board is built to
        # avoid, and "could not load" would send somebody hunting for a file
        # that was never the problem.
        return {'error': f"`{config.get('type')}` is one of Home Assistant's "
                         "built-in cards, and one of the few Chauffeur can "
                         "neither draw nor host (most need Home Assistant's "
                         "live websocket). Use a dashboard tile for it."}

    override = (resource_override or '').strip()
    row = None if override else resolve_resource(tag)
    url = override or (row or {}).get('url')
    if not url:
        return {'error': f"Nothing in Home Assistant's resources looks like it "
                         f"defines `{tag}`. Name the file yourself if it is "
                         f"installed somewhere unusual."}
    if not resource_allowed(url):
        return {'error': "A card's file has to live under /hacsfiles/, /local/ "
                         "or /community_plugin/ on Home Assistant."}

    ids = entity_ids(config)
    states = states_for(ids)
    return {
        'mode': 'host',
        'tag': tag,
        'resource': url,
        'resource_type': (row or {}).get('type') or 'module',
        'config': config,
        'states': states,
        # NAMED, not silently dropped — the same rule the `ha` tile follows for
        # a renamed entity. A power flow card missing one sensor draws a
        # plausible-looking diagram with a hole in it, and the household needs
        # to be told which.
        'missing': [e for e in ids if e not in states],
    }
