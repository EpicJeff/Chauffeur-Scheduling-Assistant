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
    # a small import site and the big (lovelace) one
    'a=()=>Promise.all([n.e(10021)]).then(n.bind(n,111));'
    'b=()=>Promise.all([n.e(14887),n.e(79381),n.e(29442)]).then(n.bind(n,60368));'
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
