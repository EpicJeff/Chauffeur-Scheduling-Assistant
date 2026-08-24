"""Borrowing Home Assistant's frontend for its own built-in cards.

The whole feature is extraction from minified code, so the tests are mostly
fixtures shaped like what rspack actually emits — small enough to read, real
enough that a regex that would miss the fixture would have missed the file it
was lifted from. The live extraction was verified against a real HA
(2026-08-24, app hash d53ce8172fc8c85d): 70 chunks, 34 hostable cards, the
thermostat/sensor/area cards rendering through the production host.

The other half is the promise the feature stands on: every consumer keeps the
converter drawing when any step refuses, so nothing here may throw at a
missing HA — bundle() answers None and says why.

Run from chauffeur/:  python tests/test_ha_frontend.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_haf_'))

from services import ha_frontend, ha_card_convert, ha_cards  # noqa: E402

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')
STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'static')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ── Fixtures, shaped like rspack's output. ──────────────────────────────────

INDEX = ('<html><head><script type="module" src='
         '"/frontend_latest/app.d53ce8172fc8c85d.js"></script></head></html>')

APP = (
    'var x=1;'
    # the filename map: names for worker chunks, hashes for all
    'o.u=e=>(({33921:"recorder-worklet"}[e]||e)+"."+{10021:"aaaa111122223333",'
    '33921:"eeee111122223333",'
    '14887:"bbbb111122223333",79381:"cccc111122223333",'
    '29442:"dddd111122223333"}[e]+".js"),'
    # the default theme: a base run naming the state colours...
    'const light=`--primary-color:#016194;--card-background-color:#fff;'
    + ';'.join(f'--filler-{i}:#000' for i in range(40)) + ';'
    '--state-climate-heat-color:var(--deep-orange-color);'
    '--deep-orange-color:#ff6f22;`;'
    # ...and a dark run repainting the card near-black
    'const dark=`--card-background-color:#1c1c1c;'
    + ';'.join(f'--dfiller-{i}:#111' for i in range(40)) + ';`;'
    # the mode-neutral primitives and the wa form-control layer
    'const prims=`--ha-color-primary-05:#012;'
    + ';'.join(f'--ha-color-scale-{i}:#123' for i in range(24)) + ';`;'
    'const wa=`--wa-form-control-border-color:#456;'
    + ';'.join(f'--wa-token-{i}:#456' for i in range(24)) + ';`;'
    # light semantics first, dark second — HA's emit order
    'const lightsem=`--ha-color-text-primary:var(--x-05);'
    + ';'.join(f'--ha-sem-{i}:#789' for i in range(24)) + ';`;'
    'const darksem=`--ha-color-text-primary:var(--white-color);'
    + ';'.join(f'--ha-dsem-{i}:#abc' for i in range(24)) + ';`;'
    # a small import site and the big (lovelace) one
    'a=()=>Promise.all([n.e(10021)]).then(n.bind(n,111));'
    'b=()=>Promise.all([n.e(14887),n.e(79381),n.e(29442)]).then(n.bind(n,60368));'
    # the UI translation metadata, as the entrypoint embeds it
    'const tm=JSON.parse(\'{"fragments":["app","config","lovelace","map"],'
    '"translations":{"en":{"nativeName":"English",'
    '"hash":"4382c634be91d05dbb6161acf45b495f"}}}\');'
    # the boot call this module exists to remove
    'o(91535);\n//# sourceMappingURL=app.js.map'
)

REGISTRY_CHUNK = (
    'var s=n(37831),a=n(60275),g=n(87206),y=e([s,a,g]);'
    'const v=new Set(["entity","entities","button","entity-button","glance",'
    '"grid","section","light","sensor","thermostat","weather-forecast",'
    '"tile","heading"]),'
    'w={"alarm-panel":()=>n.e(8537).then(n.bind(n,25536)),'
    'area:()=>n.e(29442).then(n.bind(n,56729)),'
    '"energy-date-selection":()=>Promise.all([n.e(63871),n.e(43994)])'
    '.then(n.bind(n,99621)),'
    'gauge:()=>n.e(22820).then(n.bind(n,23535)),'
    'error:()=>Promise.resolve().then(n.bind(n,49888))};'
    # a SECOND table right after — the editors load the same way, keyed by
    # the same names, and a fixed-window scan once bled into it
    'z={area:()=>n.e(99999).then(n.bind(n,11111))};'
)


def scenario_the_entrypoint_is_read_not_guessed():
    path, h = ha_frontend.find_app_path(INDEX)
    check(path == '/frontend_latest/app.d53ce8172fc8c85d.js', f"path: {path}")
    check(h == 'd53ce8172fc8c85d', f"hash: {h}")

    patched = ha_frontend.patch_runtime(APP)
    check(patched is not None, 'the boot call was not found')
    check('window.__haWpr=o;' in patched, 'the runtime export is missing')
    check('o(91535);' not in patched, 'the app still boots')
    # The duplicate-define guard rides in FRONT of everything: HA's chunks
    # and the panel's shims share tag names, and without it a collision
    # throws mid-chunk-evaluation and kills every module sharing the chunk —
    # the wall's "cards mount but features and area images don't".
    check(patched.startswith('(function(){var d=customElements.define'),
          'the duplicate-define guard is not first in the runtime')

    files = ha_frontend.chunk_filenames(APP)
    check(files.get('14887') == 'bbbb111122223333.js'
          or files.get('14887') == '14887.bbbb111122223333.js',
          f"chunk filename: {files.get('14887')}")
    check(files.get('33921', '').startswith('recorder-worklet.'),
          f"worker name lost: {files.get('33921')}")

    sites = ha_frontend.import_sites(APP)
    check(sites[0][0] == ['14887', '79381', '29442'],
          f"largest site first: {sites[0]}")
    check(sites[0][1] == '60368', f"site module: {sites[0][1]}")


def scenario_the_card_table_is_lifted_whole_and_only_it():
    cards = ha_frontend.extract_card_map(REGISTRY_CHUNK)
    check(cards['alarm-panel'] == {'chunks': ['8537'], 'module': 25536},
          f"alarm-panel: {cards.get('alarm-panel')}")
    check(cards['area'] == {'chunks': ['29442'], 'module': 56729},
          f"the EDITOR table overwrote the card table: {cards.get('area')}")
    check(cards['energy-date-selection']['chunks'] == ['63871', '43994'],
          f"promise-all chunks: {cards.get('energy-date-selection')}")
    check('error' in cards, 'the resolve-only form was dropped')

    eager = ha_frontend.extract_eager_modules(REGISTRY_CHUNK)
    check(eager == [37831, 60275, 87206], f"eager modules: {eager}")


def scenario_the_theme_rides_along():
    base, dark = ha_frontend.extract_theme(APP)
    check('--state-climate-heat-color' in base,
          'the base theme lost the state colours')
    check('--card-background-color:#1c1c1c' in dark,
          'the dark overrides were not found')
    # The editors' chrome: primitives, the wa form-control layer and the
    # LIGHT semantics ride the base; the dark semantics ride the dark
    # block. Two runs was never the whole theme — the first cut shipped
    # fields with no borders.
    check('--ha-color-primary-05' in base, 'the colour primitives are lost')
    check('--wa-form-control-border-color' in base,
          'the wa form-control tokens are lost — fields draw borderless')
    check('--ha-color-text-primary:var(--x-05)' in base,
          'the light semantics did not land in the base block')
    check('--ha-color-text-primary:var(--white-color)' in dark,
          'the dark semantics did not land in the dark block')


def scenario_the_ui_strings_are_findable():
    """Every label the real editors show is a ui.* key against HA's
    fingerprinted translation files; without the fingerprints the client
    can only humanize key tails — a feature row literally read "label"."""
    i18n = ha_frontend.extract_i18n(APP)
    check(i18n.get('hash') == '4382c634be91d05dbb6161acf45b495f',
          f"the en hash was not found: {i18n}")
    check('lovelace' in i18n.get('fragments', []),
          f"the fragments list is lost: {i18n}")
    ok = ha_frontend.translations_file_allowed
    check(ok('en-4382c634be91d05dbb6161acf45b495f.json'),
          'the base translation file is refused')
    check(ok('lovelace/en-4382c634be91d05dbb6161acf45b495f.json'),
          'a fragment translation file is refused')
    for bad in ('../secrets.yaml', 'a/b/c.json', 'en.json', 'x/y-zz.json'):
        check(not ok(bad), f"the translations proxy would serve {bad!r}")


def scenario_the_static_proxies_beat_the_static_mount():
    """Starlette matches in REGISTRATION order and app.mount('/static')
    swallows everything under it — the mdi and translation proxies
    registered after it answered 404 off disk. Invisible through ingress
    (page-absolute /static/... goes to HA's own origin there), fatal on
    the app's own origin: the tunnel wall lost every ws-resolved icon."""
    main_src = open(os.path.join(
        os.path.dirname(TPL), 'main.py'), encoding='utf-8').read()
    mount_at = main_src.find("app.mount(\"/static\"")
    check(mount_at > 0, 'the static mount moved — update this test')
    for route in ('@app.get("/static/mdi/{fname}")',
                  '@app.get("/static/translations/{path:path}")'):
        at = main_src.find(route)
        check(0 < at < mount_at,
              f"{route} is registered after the /static mount and the "
              f"mount answers first — the proxy 404s off disk")
    # And the client stores registry pictures root-absolute: hui-image runs
    # every src through hass.hassUrl, which prepends the api base itself —
    # prefixing here too doubled the base and no photograph loaded anywhere.
    host = open(os.path.join(STATIC, 'ha_card_host.js'), encoding='utf-8').read()
    check("a.picture = '/' + a.picture;" in host,
          'registry pictures are not stored root-absolute for hassUrl')
    check("a.picture = API.base + a.picture" not in host,
          'the double-prefix picture bug is back')


def scenario_the_ws_lanes_the_cards_need_are_bridged():
    """Domain and attribute icons — and backend labels — arrive over
    `frontend/get_icons` / `frontend/get_translations`, and the icon path
    checks `connection.haVersion` before asking at all. The client bridges
    exactly those message types; nothing else grows a websocket."""
    host = open(os.path.join(STATIC, 'ha_card_host.js'), encoding='utf-8').read()
    check('function wsBridge(' in host, 'the ws bridge is gone')
    check("msg.type === 'frontend/get_icons'" in host
          and "msg.type === 'frontend/get_translations'" in host,
          'the two bridged message types are not both handled')
    check('haVersion' in host,
          'the connection has no haVersion — icon resolution silently '
          'skips as "too old"')
    check('function loadUiStrings(' in host and 'function localize(' in host,
          'the real ui.* localize is gone — labels fall back to key tails')
    # And the ws answers are CACHED server-side; a board poll must not be
    # a websocket connect per icon category.
    check(callable(getattr(ha_frontend, 'ws_resources', None)),
          'ws_resources is gone from ha_frontend')


def scenario_extraction_end_to_end_against_fixtures():
    files = {'/': (INDEX.encode(), 'text/html'),
             '/frontend_latest/app.d53ce8172fc8c85d.js':
                 (APP.encode(), 'application/javascript'),
             '/frontend_latest/14887.bbbb111122223333.js':
                 (REGISTRY_CHUNK.encode(), 'application/javascript')}
    meta, runtime = ha_frontend._extract(lambda p: files.get(p))
    check(meta['app_hash'] == 'd53ce8172fc8c85d', f"hash: {meta['app_hash']}")
    check(meta['chunks'] == ['14887', '79381', '29442'],
          f"chunk set: {meta['chunks']}")
    check('energy-date-selection' not in meta['cards'],
          'an energy card survived the prune — it can only ever spin')
    check('area' in meta['cards'] and 'gauge' in meta['cards'],
          f"cards: {sorted(meta['cards'])}")
    check(meta['eager_modules'] == [37831, 60275, 87206],
          f"eager: {meta['eager_modules']}")
    check('window.__haWpr=' in runtime, 'runtime not patched')


def scenario_a_new_patch_is_a_new_extraction_and_a_new_url():
    """The app hash only says HA did not change; it cannot say WE did not.
    A guard added to the patch must reach walls whose browsers hold the old
    runtime URL immutable — so the version rides the cache key AND the
    filename."""
    files = {'/': (INDEX.encode(), 'text/html'),
             '/frontend_latest/app.d53ce8172fc8c85d.js':
                 (APP.encode(), 'application/javascript'),
             '/frontend_latest/14887.bbbb111122223333.js':
                 (REGISTRY_CHUNK.encode(), 'application/javascript')}
    meta, runtime = ha_frontend._extract(lambda p: files.get(p))
    check(meta['patch_v'] == ha_frontend.PATCH_V,
          f"the extraction does not stamp its patch version: {meta.keys()}")
    ha_frontend._persist(meta['app_hash'], meta, runtime)
    check(ha_frontend._load_cached(meta['app_hash']) is not None,
          'a fresh persist does not load back')
    check(ha_frontend.runtime_source(meta['app_hash']) is not None,
          'the runtime file is not where runtime_source looks')
    # An older build's cache must be re-extracted, not served.
    import json as _json
    stale = dict(meta, patch_v=ha_frontend.PATCH_V - 1)
    with open(os.path.join(ha_frontend._cache_dir(),
                           f"{meta['app_hash']}.json"), 'w',
              encoding='utf-8') as f:
        _json.dump(stale, f)
    check(ha_frontend._load_cached(meta['app_hash']) is None,
          "yesterday's patch is being served from the cache")


def scenario_the_shims_wait_their_turn():
    """Every tag the shims define is ALSO defined by chunks in the borrowed
    runtime's set (verified against the live bundle: ha-card in 68787,
    ha-icon in 38092, ha-form in 95135, ...). Shims defined at page parse
    made those chunk evaluations throw, killing every module that shared the
    chunk — cards mounted, their feature rows and hui-image died. So the
    form shims define only on demand, and the host asks for the REAL form
    stack first wherever the runtime booted."""
    form = open(os.path.join(STATIC, 'ha_form.js'), encoding='utf-8').read()
    import re as _re
    check(not _re.search(r'^\s*defineAll\(\);\s*$', form, _re.M),
          'ha_form.js still defines its elements at parse time')
    check('ensure: defineAll' in form, 'the on-demand road is gone')
    host = open(os.path.join(STATIC, 'ha_card_host.js'), encoding='utf-8').read()
    check('function ensureForm()' in host, 'ensureForm is gone')
    check('ensureForm: ensureForm' in host, 'ensureForm is not exported')
    check(host.count('ensureForm()') >= 2,
          'the custom-editor path no longer asks for a form layer')


def scenario_the_real_editors_come_off_the_runtime():
    """'Features set in the options' had no way to be true: our declared
    schemas only offer the fields somebody re-typed into them. The REAL
    editors (getConfigElement) carry HA's whole options surface — the
    thermostat's features UI included — so the overlay asks for them first
    and keeps the schema form as the fallback. Verified live in the harness:
    entity picker, mode row, theme, features section, zero console errors."""
    host = open(os.path.join(STATIC, 'ha_card_host.js'), encoding='utf-8').read()
    check('function mountBuiltinEditor(' in host,
          'the real-editor mount is gone')
    check('mountBuiltinEditor: mountBuiltinEditor' in host,
          'mountBuiltinEditor is not exported')
    # The editors consume more of the app shell than the cards do; each of
    # these keys was found unanswered by watching real context-request
    # events, and each unanswered one was a throw inside the editor.
    for key in ("'hassRegistries'", "'hassConnection'", "'hassApi'",
                "'extendedEntities'", "'related'"):
        check('case ' + key + ':' in host,
              f"the {key} context is unanswered — the pickers throw on it")
    home = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    check('mountBuiltinEditor(' in home,
          'the card overlay never asks for the real editor')
    check('ensureForm()' in home,
          'the fallback form path never asks for a form layer, and the '
          'shims no longer define themselves')
    # The editors' hass gaps found by running them: hassUi consumers read
    # `_ui?.themes.darkMode` (the chain guards the context, not the field),
    # and the tile editor reads `hass.services[domain]`.
    check('themes: { darkMode: dark' in host,
          "the hassUi context has no themes object — select boxes throw")
    check('services: {},' in host,
          'hass has no services map — the tile editor throws per domain')


def scenario_the_pool_reaches_cards_inside_custom_tiles():
    """A household whose HA cards all live inside custom container tiles
    has no top-level ha_card tile, and the whole-house states pool never
    shipped: cards drew (each carries its own slice) while the editors —
    fed from the pool alone — saw an empty house. Entity pickers amber,
    every feature 'not compatible', lock icons wrong."""
    import inspect
    from services import home_board
    src = inspect.getsource(home_board.build)
    check("(t.get('cards') or [])" in src,
          'the ha_states condition only scans top-level tiles again')


def scenario_no_home_assistant_is_an_answer_not_an_error():
    """The standing rule: every HA touchpoint degrades gracefully."""
    ha_frontend.reset()
    meta, err = None, None
    try:
        meta, _ = ha_frontend._extract(lambda p: None)
    except ValueError as e:
        err = str(e)
    check(meta is None and err and 'index' in err,
          f"a dead HA should name the failed step: {err!r}")
    # And the public entry point turns that into None + a reason.
    got = ha_frontend.bundle()
    check(got is None, 'bundle() invented a bundle with no HA')
    check(bool(ha_frontend.last_error()), 'the reason was swallowed')
    ha_frontend.reset()


def scenario_the_proxy_serves_chunks_and_nothing_else():
    ok = ha_frontend.frontend_file_allowed
    check(ok('12401.ab12cd34ef56ab78.js'), 'a chunk file was refused')
    check(ok('recorder-worklet.ab12cd34ef56ab78.js'), 'a worker chunk was refused')
    for bad in ('../secrets.yaml', 'a/b.js', 'x.json', 'app.js.map', '',
                'x.js%00', 'con.js.'):
        check(not ok(bad), f"the chunk proxy would serve {bad!r}")


# ── The converter's half: every hostable leaf is a host with its old drawing
#    as the fallback. ─────────────────────────────────────────────────────────

STATES = {'sensor.t': {'entity_id': 'sensor.t', 'state': '71',
                       'attributes': {'unit_of_measurement': '°F'}}}


def scenario_a_hostable_leaf_becomes_a_host_with_its_old_drawing():
    hosts = {}
    node = ha_card_convert.convert(
        {'type': 'gauge', 'entity': 'sensor.t'}, STATES, hosts=hosts)
    check(node['kind'] == 'host', f"kind: {node['kind']}")
    check(node['builtin'] == 'gauge', f"builtin: {node.get('builtin')}")
    check(node['fallback']['kind'] == 'gauge',
          f"the converter drawing is gone: {node.get('fallback')}")
    check(hosts[node['host_id']]['builtin'] == 'gauge',
          f"hosts entry: {hosts}")

    # Types the converter never drew get hosted too — with the honest
    # 'unsupported' line standing until the real card mounts.
    hosts = {}
    node = ha_card_convert.convert(
        {'type': 'light', 'entity': 'light.x'}, STATES, hosts=hosts)
    check(node['kind'] == 'host' and node['builtin'] == 'light',
          f"a light card should be hostable: {node}")
    check(node['fallback']['kind'] == 'unsupported',
          f"fallback: {node.get('fallback')}")


def scenario_the_deliberate_exclusions_stay_drawn_not_hosted():
    """markdown renders templates over a websocket we are not lending, and
    picture-entity's images need auth the page does not have — hosting them
    would trade a working drawing for a spinner."""
    hosts = {}
    node = ha_card_convert.convert(
        {'type': 'markdown', 'content': 'hello'}, STATES, hosts=hosts)
    check(node['kind'] == 'markdown', f"markdown was hosted: {node['kind']}")
    check(not hosts, f"markdown left a host entry: {hosts}")


def scenario_without_a_hosts_dict_nothing_changes():
    """The `hosts=None` callers (and every old test) see the old shapes."""
    node = ha_card_convert.convert({'type': 'gauge', 'entity': 'sensor.t'},
                                   STATES)
    check(node['kind'] == 'gauge', f"kind: {node['kind']}")


def scenario_builtin_hosts_skip_the_resource_lookup():
    """A board of only built-in cards must not pay a websocket round trip to
    list custom-card resources it will never use."""
    import services.ha_cards as hc
    called = {'n': 0}
    orig = hc.list_resources
    hc.list_resources = lambda: called.__setitem__('n', called['n'] + 1) or []
    try:
        out = hc._resolve_hosts(
            {'h0': {'builtin': 'gauge',
                    'config': {'type': 'gauge', 'entity': 'sensor.t'}}},
            STATES)
        check(out['h0']['builtin'] == 'gauge', f"entry: {out['h0']}")
        check(out['h0']['states'].get('sensor.t', {}).get('state') == '71',
              f"the states slice is missing: {out['h0']}")
        check('error' not in out['h0'],
              f"a builtin host grew a resource error: {out['h0']}")
        check(called['n'] == 0,
              'a builtin-only tree still listed custom resources')
    finally:
        hc.list_resources = orig


def scenario_an_area_photograph_rides_the_artwork_proxy():
    """The registry's `picture` is an authenticated HA path, and the real
    area card renders it as a bare <img> on OUR origin — served raw it 404s
    and the card shows its icon instead of the room. Rewritten through the
    same base64url artwork proxy the converter's drawing uses."""
    import base64
    from services import ha_api
    orig = ha_api.ws_command
    rows = {'config/area_registry/list': [
        {'area_id': 'lr', 'name': 'Living Room',
         'picture': '/api/image/serve/abc123/512x512'},
        {'area_id': 'kit', 'name': 'Kitchen', 'picture': None},
    ]}
    ha_api.ws_command = lambda cmd, **kw: rows.get(cmd, [])
    try:
        ha_frontend.reset()
        reg = ha_frontend.registries(ttl=0)
        pic = reg['areas']['lr']['picture']
        check(pic and pic.startswith('api/ha/image64/'),
              f"the picture is not proxied: {pic!r}")
        enc = pic.split('/')[-1]
        back = base64.urlsafe_b64decode(enc + '=' * (-len(enc) % 4)).decode()
        check(back == '/api/image/serve/abc123/512x512',
              f"the proxied path does not decode back: {back!r}")
        check(reg['areas']['kit']['picture'] is None,
              'an area with no photograph grew one')
        # The fields HA's pickers CALL METHODS ON ride along even when
        # empty — `aliases.join` on an absent field killed the area picker.
        check(reg['areas']['lr']['aliases'] == [], 'areas lost aliases')
        check('floor_id' in reg['areas']['lr'], 'areas lost floor_id')
    finally:
        ha_api.ws_command = orig
        ha_frontend.reset()


def scenario_a_poll_moves_the_live_card_instead_of_rebuilding_it():
    """Every board poll re-renders the tile tree, handing each host a NEW
    cell. Rebuilding there flashed the converter fallback for a frame and
    restarted whatever the card animates — reported as 'a flash of the old
    implementation on every load or update'. An unchanged card is adopted
    into the new cell (same task as the re-render, before paint)."""
    host = open(os.path.join(STATIC, 'ha_card_host.js'), encoding='utf-8').read()
    check('function adopt(' in host, 'the adoption path is gone')
    check(host.count('return adopt(live, container, spec,') == 2,
          'one of the two mount paths stopped adopting — that path flashes '
          'its fallback and restarts its animations on every poll')
    # And the new cell gets dressed: a moved card keeps its shape but loses
    # its colours if the theme never lands on the adopting container.
    at = host.index('function adopt(')
    body = host[at:at + 1600]
    check('themeFrom(container)' in body and 'ha-builtin-theme' in body,
          "adopt() does not theme the new cell")


def scenario_the_visual_editor_keeps_the_keys_it_cannot_see():
    """The ha-form editor only knows the schema's fields, and a thermostat's
    YAML legitimately carries `features:` the schema does not name — now
    rendered by the real cards, so silently deleting them on the first form
    edit reads as 'features set in the options don't show'."""
    home = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    check('onChange({ ...config, ...e.detail.value, type: type });' in home,
          "the form's value-changed replaces the config instead of merging "
          "over it, so every key outside the schema dies on first edit")


def scenario_the_wall_draws_fallbacks_and_upgrades_in_place():
    """The template's side of the bargain, read from the source."""
    home = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    check('c.fallback ? this.drawCard(c.fallback, path)' in home,
          "a host cell no longer draws its fallback, so a dead runtime is "
          "a blank cell — the exact failure this design exists to avoid")
    check('mountBuiltin(cell, spec)' in home,
          'syncCards never mounts a builtin host')
    check('bootBuiltin(this.apiBase)' in home,
          'the runtime is never booted, so shims always win the registry '
          'and every builtin chunk fails to define')

    host = open(os.path.join(STATIC, 'ha_card_host.js'), encoding='utf-8').read()
    for needle, why in (
            ('mountBuiltin: mountBuiltin', 'mountBuiltin is not exported'),
            ('context-request', 'the app-shell contexts are not answered'),
            ('history/stream', "the sensor card's history subscription is "
                               'not translated'),
            ('ha-builtin-theme', "HA's default tokens are never applied"),
            ("window.customElements.get(name)",
             'the shims no longer defer to elements the runtime defined')):
        check(needle in host, why)


SCENARIOS = [v for k, v in sorted(globals().items())
             if k.startswith('scenario_')]

if __name__ == '__main__':
    for fn in SCENARIOS:
        fn()
        print(f'  ok  {fn.__name__}')
    print(f'\n{len(SCENARIOS)}/{len(SCENARIOS)} ha-frontend scenarios passed')
