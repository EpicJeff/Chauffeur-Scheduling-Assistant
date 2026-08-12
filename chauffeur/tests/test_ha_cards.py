"""Hosting a real Home Assistant custom card in a board tile.

The claim this file is defending is narrow and easy to overstate: a CUSTOM
card — one that ships as its own file — can be run outside Home Assistant,
because everything it depends on can be supplied. A BUILT-IN card cannot,
because `type: gauge` resolves to an element that only exists inside HA's own
bundle. The difference is invisible in the YAML and total in the outcome, so
the tile has to explain it rather than fail.

The other half is the proxy. It fetches with a supervisor token, which makes
it the most dangerous endpoint in this app if its allowlist is ever loosened —
the same reasoning /api/ha/image already carries.

What is NOT here is the render itself, which needs a browser. That was proven
against the real tesla-style-solar-power-card and power-flow-card-plus bundles
in jsdom; see docs/ha_card_hosting.md for what each one needed.

Run from chauffeur/:  python tests/test_ha_cards.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_ha_cards_'))

from services import ha_cards  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


SOLAR = """
type: custom:tesla-style-solar-power-card
name: Power
grid_to_house_entity: sensor.grid_to_house
generation_to_house_entity: sensor.solar_to_house
battery_entity: sensor.battery_level
"""


def scenario_yaml_is_what_home_assistant_shows_you():
    """The config field takes the text HA's own code editor shows, which is
    YAML. JSON parses as YAML too, so nobody has to be told which they have."""
    config, err = ha_cards.parse_config(SOLAR)
    check(not err, f"the solar card's own YAML did not parse: {err}")
    check(config['type'] == 'custom:tesla-style-solar-power-card', "wrong type read")

    config, err = ha_cards.parse_config('{"type": "custom:x-card", "entity": "sensor.a"}')
    check(not err and config['entity'] == 'sensor.a', "JSON is valid YAML and must work")


def scenario_a_bad_config_says_what_is_wrong():
    """Every one of these is a SENTENCE on the wall. A card config is
    hand-pasted text, so the failure everybody hits is a typo, and 'could not
    load' sends somebody hunting for a file that was never the problem."""
    for raw, want in (('', 'Paste'),
                      ('type: [unclosed', 'not valid YAML'),
                      ('just a string', '`key: value`'),
                      ('name: no type here', '`type:`')):
        config, err = ha_cards.parse_config(raw)
        check(config is None and err, f"{raw!r} should not have parsed")
        check(want in err, f"{raw!r} -> {err!r}, expected something about {want!r}")


def scenario_built_in_cards_are_refused_by_name():
    """The limit that matters most, because the YAML looks identical.

    `type: gauge` is HA's own card, compiled into its frontend; there is no
    file to fetch and never will be. Saying so — and saying which kind it is —
    is the difference between a household picking a different route and a
    household concluding the feature is broken.
    """
    check(ha_cards.card_tag({'type': 'custom:my-card'}) == 'my-card',
          "a custom card's element name is the type after 'custom:'")
    for built_in in ('gauge', 'entities', 'tile', 'picture-glance'):
        check(ha_cards.card_tag({'type': built_in}) is None,
              f"{built_in} is built in and has no loadable element")
        out = ha_cards.prepare(f'type: {built_in}\nentity: sensor.a')
        check('built-in' in (out.get('error') or ''),
              f"a {built_in} card must be refused as BUILT-IN, got {out.get('error')!r}")


def scenario_only_the_three_card_directories_are_reachable():
    """The allowlist IS the security of the proxy. It holds a supervisor token,
    so anything it will fetch, anyone who can reach the panel can read out of
    Home Assistant."""
    for ok in ('/hacsfiles/foo/foo.js',
               '/hacsfiles/foo/foo.js?hacstag=123',
               '/local/my-card.js',
               '/community_plugin/old/old.js'):
        check(ha_cards.resource_allowed(ok), f"{ok} is where cards live")
    for bad in ('/api/config/core/check_config',      # HA's own API
                '/config/configuration.yaml',
                '/hacsfiles/../../etc/passwd',
                '/local/../secrets.yaml',
                'https://evil.example/card.js',        # not even our origin
                'http://supervisor/core/api/states',
                '',
                'hacsfiles/foo.js'):                   # not rooted
        check(not ha_cards.resource_allowed(bad),
              f"{bad!r} must never be fetchable through the card proxy")


def scenario_a_cards_file_is_found_by_its_own_name():
    """Households should not have to know a path. HA already knows which files
    it loads to make custom cards exist, so the tile asks it."""
    rows = [
        {'url': '/hacsfiles/lovelace-mushroom/mushroom.js', 'type': 'module'},
        {'url': '/hacsfiles/tesla-style-solar-power-card/'
                'tesla-style-solar-power-card.js?hacstag=1234', 'type': 'js'},
    ]
    hit = ha_cards.resolve_resource('tesla-style-solar-power-card', rows)
    check(hit and hit['url'].startswith('/hacsfiles/tesla-style'),
          f"the solar card was not matched to its own file: {hit}")
    # The TYPE travels too: a bundle registered as a classic script must not be
    # loaded as a module, where its top-level `var` globals would vanish.
    check(hit['type'] == 'js', "the resource's declared type must survive lookup")

    # A stem shorter than the element it defines still counts — bundles are
    # routinely named for the family rather than the card.
    check(ha_cards._url_matches_tag('/hacsfiles/mini-graph-card/mini-graph-card-bundle.js',
                                    'mini-graph-card'),
          "a bundle named for its family must still match")
    check(ha_cards.resolve_resource('some-other-card', rows) is None,
          "a card nobody has installed must not match a random file")


def scenario_only_the_entities_a_card_asked_for_travel():
    """A card reads four sensors; `hass.states` is the whole house. Shipping
    the house on every board poll would cost more than everything else on the
    board put together, so the config is read for entity ids and only those
    are sent."""
    config, _ = ha_cards.parse_config(SOLAR)
    ids = ha_cards.entity_ids(config)
    check(set(ids) == {'sensor.grid_to_house', 'sensor.solar_to_house',
                       'sensor.battery_level'},
          f"wrong entities pulled out of the config: {ids}")
    check('Power' not in ids and 'custom:tesla-style-solar-power-card' not in ids,
          "a name and a card type are not entity ids")

    # Nested exactly as power-flow-card-plus writes them.
    nested, _ = ha_cards.parse_config(
        'type: custom:power-flow-card-plus\n'
        'entities:\n'
        '  grid:\n'
        '    entity: sensor.grid_power\n'
        '  solar:\n'
        '    entity: [sensor.solar_a, sensor.solar_b]\n')
    check(set(ha_cards.entity_ids(nested)) ==
          {'sensor.grid_power', 'sensor.solar_a', 'sensor.solar_b'},
          "entities nested in dicts and lists must still be found")


def scenario_a_renamed_entity_is_named_not_dropped():
    """A power flow card missing one sensor draws a perfectly plausible
    diagram with a hole in it. Nothing about the picture says which number is
    not real, so the tile has to."""
    real_states, real_resolve = ha_cards.states_for, ha_cards.resolve_resource
    try:
        ha_cards.states_for = lambda ids: {
            'sensor.grid_to_house': {'entity_id': 'sensor.grid_to_house',
                                     'state': '3300', 'attributes': {}}}
        ha_cards.resolve_resource = lambda tag, resources=None: {
            'url': '/hacsfiles/t/t.js', 'type': 'module'}
        out = ha_cards.prepare(SOLAR)
        check(not out.get('error'), f"unexpected error: {out.get('error')}")
        check(set(out['missing']) == {'sensor.solar_to_house', 'sensor.battery_level'},
              f"the missing entities must be named: {out.get('missing')}")
        check(out['tag'] == 'tesla-style-solar-power-card', "wrong tag prepared")
        check(out['resource_type'] == 'module', "the load type must reach the browser")
    finally:
        ha_cards.states_for = real_states
        ha_cards.resolve_resource = real_resolve


def scenario_no_home_assistant_is_a_sentence_not_a_blank_tile():
    """The rule the whole board runs on. With no HA there are no resources, so
    the card cannot be found — and the tile says that, in words, rather than
    showing an empty rectangle nobody can tell from a broken one."""
    real = ha_cards.list_resources
    try:
        ha_cards.list_resources = lambda: []
        out = ha_cards.prepare(SOLAR)
        check(out.get('error') and 'tesla-style-solar-power-card' in out['error'],
              f"a missing card must be named in the message: {out}")
        check('Name the file yourself' in out['error'],
              "the message must point at the hand path (the resource field)")
    finally:
        ha_cards.list_resources = real


def scenario_a_cards_file_does_not_go_through_the_api_proxy():
    """The bug that shipped in v2.187.0, pinned.

    `http://supervisor/core` proxies `/core/api` and `/core/websocket` — it is
    a proxy to Home Assistant's API, not to Home Assistant. A card lives at
    `/hacsfiles/…` or `/local/…`, neither of which is an API path, so routing
    it through `fetch_binary` produced a 404 that reached the wall as "Home
    Assistant would not hand over that card's file".

    Every other caller of `fetch_binary` passes an `/api/…` path, which is why
    nothing caught this. So the assertion is about WHICH DOOR is used, not
    about the bytes that come back.
    """
    from services import ha_api
    real_static, real_binary = ha_api.fetch_static, ha_api.fetch_binary
    asked = []
    try:
        ha_api.fetch_static = lambda p: (asked.append(('static', p)), (b'/*card*/', 'x'))[1]
        ha_api.fetch_binary = lambda p: (asked.append(('binary', p)), (b'', 'x'))[1]
        out = ha_cards.fetch_resource('/local/community/some-card/some-card.js')
        check(out and out[0] == b'/*card*/', f"the card's file did not come back: {out}")
        check(asked == [('static', '/local/community/some-card/some-card.js')],
              f"a card's file must be fetched as STATIC content, not through "
              f"the API proxy: {asked}")

        asked.clear()
        ha_cards.reset_icon_cache()
        ha_cards.mdi_path('solar-power')
        check(asked and asked[0][0] == 'static' and asked[0][1].startswith('/static/mdi/'),
              f"mdi icons are frontend static content too: {asked}")
    finally:
        ha_api.fetch_static, ha_api.fetch_binary = real_static, real_binary
        ha_cards.reset_icon_cache()


def scenario_the_static_route_is_home_assistant_itself():
    """Add-ons reach the Core container directly at `homeassistant:8123`, and
    the files a card needs are served there WITHOUT authentication — HA's own
    frontend has to load before anybody has signed in. So no token goes out,
    and the supervisor URL is not in the list at all."""
    import os
    from services import ha_api
    had = os.environ.get('SUPERVISOR_TOKEN')
    try:
        os.environ['SUPERVISOR_TOKEN'] = 'pretend'
        origins = ha_api.core_origins()
        check(origins and origins[0] == 'http://homeassistant:8123',
              f"an add-on's route to HA's own files is the Core container: {origins}")
        check(not any('supervisor' in o for o in origins),
              f"the API proxy cannot serve static files and must not be tried: {origins}")
    finally:
        if had is None:
            os.environ.pop('SUPERVISOR_TOKEN', None)
        else:
            os.environ['SUPERVISOR_TOKEN'] = had


def scenario_an_icon_name_is_never_trusted():
    """The icon endpoint takes a name straight off a card's config and turns it
    into a path on Home Assistant. Anything that is not an mdi name must stop
    here rather than at HA."""
    for bad in ('../../secrets', 'foo/bar', 'Solar Power', '', 'a b',
                'mdi:../etc', 'x' * 200 + '/..'):
        check(ha_cards.mdi_path(bad) is None,
              f"{bad!r} must never reach Home Assistant as an icon name")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} hosted-card scenarios passed")
