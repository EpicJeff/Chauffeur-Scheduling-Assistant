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


def scenario_built_in_cards_take_the_other_road():
    """The limit that matters most, because the YAML looks identical.

    `type: gauge` is HA's own card, compiled into its frontend; there is no
    file to fetch and never will be. What changed in v2.192.0 is where that
    leads: a built-in card's config completely describes it, so the common ones
    are DRAWN (services/ha_card_convert) rather than refused. The ones that are
    not drawable are still refused by name — see test_ha_card_convert.py, which
    owns that edge.

    What must not change is the routing: no built-in ever tries to fetch a
    file, because there is no file.
    """
    check(ha_cards.card_tag({'type': 'custom:my-card'}) == 'my-card',
          "a custom card's element name is the type after 'custom:'")
    for built_in in ('gauge', 'entities', 'tile', 'picture-glance', 'markdown'):
        check(ha_cards.card_tag({'type': built_in}) is None,
              f"{built_in} is built in and has no loadable element")
        out = ha_cards.prepare(f'type: {built_in}\nentity: sensor.a')
        check(out.get('mode') != 'host' and 'resource' not in out,
              f"a {built_in} card was sent to fetch a file that cannot exist: {out}")
        check(out.get('mode') == 'native' or out.get('error'),
              f"a {built_in} card produced neither a drawing nor a reason: {out}")


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


# --- cards that GO LOOKING for their entities -------------------------------
#
# Reported from the household against two cards of their own (an AI-Media
# router card and a matrix card). Both DISPLAYED, and the parts of them that
# list speakers and TVs were empty. Neither errored, because nothing was wrong
# with either card: a hosted card used to be handed only the entities its
# config NAMES, so a card that discovers devices by walking `hass.states` was
# walking an empty house.
#
#   type: custom:ai-media-router-card   -> names nothing at all -> 0 states
#   type: custom:ai-media-matrix-card   -> names one room       -> 1 state,
#       and its cast list filters out exactly that kind of id, so: nothing.
#
# The answer is the board's shared pool: `states_all()` — the WHOLE house —
# attached ONCE to a board payload that hosts any custom card, merged under
# each card's named states in the browser. Nobody has to know which parts of
# the house a card walks. Affordable because the payload gzips (~97% off,
# measured) and because it is one copy per board, not one per tile. The
# first fix was a per-tile "also send these entities" box; it worked and it
# put a card's internals on the person pasting YAML, so the pool retired it.
#
# The real matrix card builds its list with
#   Object.values(hass.states).filter(s => s.entity_id.startsWith(
#       'media_player.') && !s.entity_id.startsWith('media_player.ai_media_'))
# which `_cast_targets` below reproduces.

ROUTER = "type: custom:ai-media-router-card\nlayout: auto\n"
MATRIX = ("type: custom:ai-media-matrix-card\n"
          "rooms:\n"
          "  - entity: media_player.ai_media_living_room\n"
          "    name: Living Room\n")

_HOUSE = [
    {'entity_id': 'media_player.ai_media_living_room', 'state': 'playing',
     'attributes': {'friendly_name': 'Living Room'}},
    {'entity_id': 'media_player.kitchen_speaker', 'state': 'idle',
     'attributes': {'friendly_name': 'Kitchen Speaker'}},
    {'entity_id': 'media_player.den_tv', 'state': 'off',
     'attributes': {'friendly_name': 'Den TV'}},
    {'entity_id': 'light.kitchen', 'state': 'on', 'attributes': {}},
    {'entity_id': 'sensor.outside_temp', 'state': '71', 'attributes': {}},
]


def _with_house(fn):
    """Run `fn` against a plausible house and a resolvable card file."""
    from services import ha_api
    real_states, real_resolve = ha_api.get_states, ha_cards.resolve_resource
    try:
        ha_api.get_states = lambda *a, **k: _HOUSE
        ha_cards.resolve_resource = lambda tag: {
            'url': '/hacsfiles/x/%s.js' % tag, 'type': 'module'}
        return fn()
    finally:
        ha_api.get_states = real_states
        ha_cards.resolve_resource = real_resolve


def _cast_targets(states):
    return sorted(e for e in states
                  if e.startswith('media_player.')
                  and not e.startswith('media_player.ai_media_'))


def scenario_the_pool_is_the_house_and_feeds_a_discovering_card():
    """End to end at the data level: what the browser merges (pool under the
    card's named states) lets the real cast-list filter find real devices —
    for the card that names nothing AND for the one whose only named id is
    excluded by its own filter."""
    pool = _with_house(ha_cards.states_all)
    check(set(pool) == {s['entity_id'] for s in _HOUSE},
          "the pool is not the whole house: %r" % sorted(pool))
    for raw in (ROUTER, MATRIX):
        prepared = _with_house(lambda: ha_cards.prepare(raw))
        merged = dict(pool)
        merged.update(prepared.get('states') or {})
        check(_cast_targets(merged)
              == ['media_player.den_tv', 'media_player.kitchen_speaker'],
              "a discovering card still cannot build its device list: %r"
              % sorted(merged))


def scenario_the_pool_rows_are_shaped_like_hass_states():
    """Cards index into these exactly as they would into HA's own object, so
    the pool and the named slice must be the same shape — one `_shape`, not
    two hand-kept copies that drift."""
    pool = _with_house(ha_cards.states_all)
    named = _with_house(
        lambda: ha_cards.states_for(['media_player.den_tv']))
    check(pool['media_player.den_tv'] == named['media_player.den_tv'],
          "the pool and the named slice disagree about the same entity")
    row = pool['light.kitchen']
    for key in ('entity_id', 'state', 'attributes', 'last_changed',
                'last_updated', 'context'):
        check(key in row, "a pool row is missing %r" % key)


def scenario_per_card_states_still_only_carry_what_is_named():
    """The pool did not turn every TILE into a copy of the house. The board
    attaches the pool once at payload level; each card's own `states` stays
    the named slice `missing` is computed against."""
    prepared = _with_house(lambda: ha_cards.prepare(MATRIX))
    check(list(prepared.get('states') or {})
          == ['media_player.ai_media_living_room'],
          "a card's own slice grew beyond what its config names: %r"
          % sorted(prepared.get('states') or {}))
    router = _with_house(lambda: ha_cards.prepare(ROUTER))
    check(router.get('states') == {},
          "a card naming nothing was handed per-tile states anyway")


def scenario_a_named_typo_is_still_named_not_drowned():
    """`missing` must survive the pool: a config naming an entity that does
    not exist still gets the amber warning, because the pool cannot contain
    the thing that is missing and the card will draw a hole."""
    raw = ("type: custom:ai-media-matrix-card\n"
           "rooms:\n"
           "  - entity: media_player.nosuch\n")
    prepared = _with_house(lambda: ha_cards.prepare(raw))
    check('media_player.nosuch' in (prepared.get('missing') or []),
          "a typo in the config was quietly drowned by the pool: %r" % prepared)


def scenario_the_board_attaches_the_pool_and_the_host_merges_it():
    """The hand path, in three parts, because any one of them missing makes
    the other two dead code: home_board attaches `ha_states` to the payload
    (only when a custom card is on the board), home.html hands it to the
    host before mounting, and the host merges it under the card's own
    states."""
    import inspect
    import os as _os
    from services import home_board
    src = inspect.getsource(home_board)
    check("'ha_states': ha_states" in src and 'states_all()' in src,
          "the board payload never carries the pool")
    check("t['data'].get('mode') == 'host'" in src,
          "the pool travels on boards with no custom card on them")
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    host = open(_os.path.join(root, 'static', 'ha_card_host.js'),
                encoding='utf-8').read()
    check('setStates' in host and 'statesPool' in host,
          "the host has nowhere to put the pool")
    check(host.index('for (k in statesPool)')
          < host.index("for (k in (spec.states || {}))"),
          "the pool must merge UNDER the named states, not over them")
    home = open(_os.path.join(root, 'templates', 'home.html'),
                encoding='utf-8').read()
    check('setStates(this.board && this.board.ha_states)' in home,
          "the board never hands the pool to the host")


def scenario_the_entities_box_is_gone_with_its_job():
    """The v2.359.0 box put a card's internals on the person pasting YAML.
    The pool does its job without the knowledge, so the box, its parser and
    the sent-no-entities note are all retired — pinned so a partial revert
    cannot bring back half of it."""
    from services import home_board
    entry = next(c for c in home_board.WIDGETS if c['key'] == 'ha_card')
    check(not any(o['key'] == 'entities' for o in entry['options']),
          "the Card tile still offers the superseded entities box")
    for gone in ('parse_entity_patterns', 'expand_patterns'):
        check(not hasattr(ha_cards, gone), "ha_cards still exposes %s" % gone)
    blind = _with_house(lambda: ha_cards.prepare(ROUTER))
    check('note' not in blind,
          "prepare still emits the sent-no-entities note the pool obsoleted")


def scenario_cards_see_state_change_between_board_polls():
    """The live refresher, as a hand path in three parts. The board poll is
    a minute apart and its payload 20s cached, so without this a lock
    toggled from a card looked dead until the next poll: the server must
    answer /api/ha/card/states, the host must poll it while cards are
    mounted and ask again right after a service call, and the merge must
    keep the NEWEST copy of a row so a stale cached payload landing between
    ticks cannot drag a card backwards."""
    import inspect
    import os as _os
    import main
    src = inspect.getsource(main)
    check('/api/ha/card/states' in src and 'states_all(ttl=0 if fresh else' in src,
          "the server has no live states endpoint for the card host")
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    host = open(_os.path.join(root, 'static', 'ha_card_host.js'),
                encoding='utf-8').read()
    check("api/ha/card/states" in host and 'function refreshStates' in host,
          "the host never asks for states between board polls")
    check('watchStates' in host and 'setInterval' in host,
          "the refresher has no clock — cards still wait for the board poll")
    check(host.count('refreshStates(true)') >= 2,
          "a service call must trigger an immediate refresh (and a second "
          "for slow actuators), or a tapped lock still looks dead")
    check('function newerRow' in host and 'last_updated' in host,
          "without newest-wins merging, a cached board payload drags a "
          "just-toggled card back to its old state")
    check('if (!pool) return;' in host,
          "setStates(null) must keep the refresher's pool, not blank it")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} hosted-card scenarios passed")
