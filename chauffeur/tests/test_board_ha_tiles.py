"""The Home Assistant board tiles, and what they do when there is no Home
Assistant.

This app runs both under HA ingress and as a plain add-on on its own port, and
the wall panel can be either. So the interesting half of an HA feature is not
the happy path — it is the household that has no Home Assistant, or whose HA
is down, or who picked an entity that has since been renamed. Every one of
those has to produce a sentence somebody can act on, never a blank card, a
spinner, or a tile that silently disappears.

The other thing worth pinning is the ALLOWLIST. The tile decides what to draw a
control for; the server decides what may actually be operated. Those are
different jobs, and a wall panel in a kitchen is reachable by everybody in the
house including the people who cannot read yet.

Run from chauffeur/:  python tests/test_board_ha_tiles.py
"""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_ha_tiles_'))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')

from services import home_board  # noqa: E402

NOW = datetime.datetime(2026, 9, 7, 17, 30)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


class _HA:
    """Stands in for services.ha_api. `available=False` is the case this whole
    file exists for."""

    def __init__(self, available=True, states=None, raises=False):
        self._available = available
        self._states = states or []
        self._raises = raises
        self.called = []

    def mode(self):
        return 'supervisor' if self._available else 'unconfigured'

    def is_available(self):
        if self._raises:
            raise RuntimeError('boom')
        return self._available

    def get_states(self, ttl=5):
        if self._raises:
            raise RuntimeError('boom')
        return self._states

    def get_state(self, entity_id):
        return next((s for s in self._states if s['entity_id'] == entity_id), None)

    def call_service(self, domain, service, data=None, **kw):
        self.called.append((domain, service, data))
        return {}


def _with_ha(stub, fn):
    """`home_board` imports ha_api INSIDE the functions that use it, so the
    stub goes into sys.modules rather than onto the module."""
    import services
    real = sys.modules.get('services.ha_api')
    sys.modules['services.ha_api'] = stub
    setattr(services, 'ha_api', stub)
    try:
        return fn()
    finally:
        if real is not None:
            sys.modules['services.ha_api'] = real
            setattr(services, 'ha_api', real)


STATES = [
    {'entity_id': 'sensor.back_garden', 'state': '17.4',
     'attributes': {'friendly_name': 'Back garden', 'unit_of_measurement': '°C'}},
    {'entity_id': 'light.kitchen', 'state': 'on',
     'attributes': {'friendly_name': 'Kitchen'}},
    {'entity_id': 'lock.front_door', 'state': 'locked',
     'attributes': {'friendly_name': 'Front door'}},
    {'entity_id': 'camera.driveway', 'state': 'idle',
     'attributes': {'friendly_name': 'Driveway',
                    'entity_picture': '/api/camera_proxy/camera.driveway?token=x'}},
]


# --- no Home Assistant -----------------------------------------------------

def scenario_no_home_assistant_at_all_means_no_tile():
    """NOT the same as "Home Assistant is down", and the board already had a
    rule for this: an unconfigured feature has no tile, which is why a
    household that never made a shopping list has no shopping tile. A first cut
    of these tiles said "Needs Home Assistant" here, which reads fine on its
    own and quietly broke property 1 for every board.

    The household without HA finds out at the PALETTE instead, where the tile
    is offered disabled — see the hand-path scenario below. That is the version
    where nobody adds a tile that could never draw."""
    stub = _HA(available=False)                     # mode() -> unconfigured
    for type_, config in (('ha', {'entities': ['light.kitchen']}),
                          ('ha_image', {'entity': 'camera.driveway'})):
        data = _with_ha(stub, lambda: home_board._BUILDERS[type_](NOW, config=config))
        check(data is None,
              f"with no Home Assistant configured, the {type_} tile returned "
              f"{data!r} — an unconfigured feature has no tile")


def scenario_home_assistant_being_down_is_not_an_exception():
    """Configured but unreachable — a restarting HA, a flat battery on the
    server, a DNS blip. A SET-UP feature that is quiet says so, which is the
    other half of property 1 and the opposite of the case above."""
    stub = _HA(available=True, raises=True)         # configured, then throws
    for type_, config in (('ha', {'entities': ['light.kitchen']}),
                          ('ha_image', {'entity': 'camera.driveway'})):
        data = _with_ha(stub, lambda: home_board._BUILDERS[type_](NOW, config=config))
        check(data is not None,
              f"the {type_} tile vanished when HA went down — that is the "
              f"unconfigured rule applied to a configured household")
        check(data.get('empty'),
              f"the {type_} tile returned {data!r} when HA threw")


def scenario_the_palette_refuses_a_tile_that_could_never_draw():
    """The hand path for the rule above. A household with no Home Assistant
    must not be able to add a Home Assistant tile from the palette and then
    wonder why the wall never shows it."""
    stub = _HA(available=False)
    cat = _with_ha(stub, home_board.catalog)
    for w in cat['widgets']:
        if w['key'] in ('ha', 'ha_image'):
            check(w.get('available') is False,
                  f"{w['key']} is offered as available with no Home Assistant")
            check(w.get('requires'), f"{w['key']} does not say what it needs")
        else:
            check('available' not in w,
                  f"{w['key']} gained an availability flag it does not need")

    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    check("c.available === false" in tpl and ':disabled=' in tpl,
          "the palette no longer disables a tile that cannot exist here")


def scenario_an_unconfigured_ha_is_never_asked_over_the_network():
    """`mode()` reads configuration and answers instantly; `is_available()`
    makes a request. A household with no Home Assistant must not wait on a
    timeout to draw a board that has nothing to do with Home Assistant."""
    class _Counting(_HA):
        def __init__(self):
            super().__init__(available=False)
            self.requests = 0

        def is_available(self):
            self.requests += 1
            return False

    stub = _Counting()
    _with_ha(stub, lambda: home_board.ha_available())
    check(stub.requests == 0,
          "ha_available() made a network request even though mode() already "
          "said there is no Home Assistant configured")


def scenario_the_editor_picker_knows_the_difference_between_absent_and_empty():
    """`available: false` is the whole contract for the editor. A picker
    showing an empty list cannot be told from one showing no matches, and the
    household is left wondering which."""
    stub = _HA(available=False)
    got = _with_ha(stub, home_board.ha_options)
    check(got['available'] is False, f"absent HA reported as available: {got}")
    check(got['entities'] == [] and got['cameras'] == [], f"phantom rows: {got}")

    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    check('haOptions.available' in tpl,
          "the editor no longer branches on whether Home Assistant is there, "
          "so an empty picker looks the same as a disconnected one")
    check('api/home_board/ha_options' in tpl,
          "the editor no longer fetches the entity list lazily — thousands of "
          "entities in the catalog is the thing that endpoint exists to avoid")


def scenario_the_entity_list_stays_out_of_the_catalog():
    """An ordinary HA has hundreds to thousands of entities. In the catalog
    they would be the biggest thing on a page every browser loads to edit a
    board."""
    cat = home_board.catalog()
    check('ha_entities' not in cat.get('sources', {}),
          "HA entities are back in the catalog payload")
    check(set(cat['sources']) == {'members', 'drivers', 'lists', 'trips'},
          f"the catalog's sources grew: {sorted(cat['sources'])}")


# --- with Home Assistant ---------------------------------------------------

def scenario_the_tile_reads_the_entities_it_was_given():
    stub = _HA(states=STATES)
    data = _with_ha(stub, lambda: home_board._tile_ha(
        NOW, config={'entities': ['sensor.back_garden', 'light.kitchen']}))
    rows = {r['entity_id']: r for r in data['rows']}
    check(len(rows) == 2, f"asked for two entities, got {list(rows)}")
    check(rows['sensor.back_garden']['state'] == '17.4'
          and rows['sensor.back_garden']['unit'] == '°C',
          f"the reading lost its value or unit: {rows['sensor.back_garden']}")
    check(rows['light.kitchen']['on'] is True,
          "an entity whose state is 'on' did not read as on")


def scenario_an_entity_that_is_gone_is_named_not_dropped():
    """A row quietly disappearing from a wall is how a household stops trusting
    the wall. Saying "not in HA" is the only version anybody acts on."""
    stub = _HA(states=STATES)
    data = _with_ha(stub, lambda: home_board._tile_ha(
        NOW, config={'entities': ['sensor.back_garden', 'sensor.renamed_away']}))
    ids = [r['entity_id'] for r in data['rows']]
    check('sensor.renamed_away' in ids, f"the missing entity was dropped: {ids}")
    gone = next(r for r in data['rows'] if r['entity_id'] == 'sensor.renamed_away')
    check(gone['missing'] is True, f"it was not flagged as missing: {gone}")


def scenario_a_tile_nobody_configured_says_so():
    """Added from the palette and never opened. "Pick some entities" is a
    thing to do; an empty card is a puzzle."""
    stub = _HA(states=STATES)
    for type_ in ('ha', 'ha_image'):
        data = _with_ha(stub, lambda: home_board._BUILDERS[type_](NOW, config={}))
        check(data and 'board setup' in (data.get('empty') or ''),
              f"an unconfigured {type_} tile said {data!r}")


# --- what a tap may do -----------------------------------------------------

def scenario_only_safe_domains_are_ever_toggleable():
    """A wall panel in a kitchen is reachable by everybody in the house,
    including the people who cannot read yet. Locks, covers and alarms are not
    things a mis-tap should operate."""
    for domain in ('lock', 'cover', 'alarm_control_panel', 'climate', 'scene'):
        check(domain not in home_board.HA_TOGGLE_DOMAINS,
              f"'{domain}' entities can be toggled from the wall")
    for domain in ('light', 'switch', 'fan', 'input_boolean'):
        check(domain in home_board.HA_TOGGLE_DOMAINS,
              f"'{domain}' is no longer toggleable, which is most of the point")


def scenario_a_lock_gets_no_button_even_when_tapping_is_on():
    stub = _HA(states=STATES)
    data = _with_ha(stub, lambda: home_board._tile_ha(
        NOW, config={'entities': ['light.kitchen', 'lock.front_door'],
                     'interactive': True}))
    rows = {r['entity_id']: r for r in data['rows']}
    check(rows['light.kitchen']['toggleable'] is True,
          "a light got no toggle with tapping switched on")
    check(rows['lock.front_door']['toggleable'] is False,
          "the front door lock is operable from the kitchen wall")


def scenario_tapping_is_off_until_somebody_asks_for_it():
    """Board rule 3: a display does not change what it is displaying. Somebody
    adding this tile to read a temperature must not get light switches."""
    opt = next(o for w in home_board.WIDGETS if w['key'] == 'ha'
               for o in w['options'] if o['key'] == 'interactive')
    check(opt['default'] is False,
          "the Home Assistant tile now offers controls by default")
    stub = _HA(states=STATES)
    data = _with_ha(stub, lambda: home_board._tile_ha(
        NOW, config={'entities': ['light.kitchen']}))
    check(data['rows'][0]['toggleable'] is False,
          "a light is tappable without the household having asked")


def scenario_the_server_checks_the_domain_too_not_only_the_tile():
    """The tile decides what to draw a control for; the endpoint decides what
    may be operated. A guard that lives only in the markup is not a guard."""
    src = open(os.path.join(os.path.dirname(TPL), 'main.py'), encoding='utf-8').read()
    block = src[src.index('def ha_toggle('):]
    block = block[:block.index('\n@app.')]
    check('HA_TOGGLE_DOMAINS' in block,
          "the toggle endpoint no longer checks the domain allowlist, so any "
          "entity in the house can be operated by a crafted request")
    check('ha_available()' in block,
          "the toggle endpoint no longer checks that HA is reachable")


# --- the camera tile -------------------------------------------------------

def scenario_the_picture_is_a_url_not_bytes():
    """The board payload is refetched every sixty seconds. A tile that inlined
    camera frames would drag a JPEG through every one of those polls."""
    stub = _HA(states=STATES)
    data = _with_ha(stub, lambda: home_board._tile_ha_image(
        NOW, config={'entity': 'camera.driveway'}))
    check(data.get('url', '').startswith('api/ha/image64/'),
          f"the camera tile is not pointing at the image proxy: {data}")
    check(len(str(data)) < 2000, "the payload looks like it contains an image")


def scenario_a_camera_path_is_allowlisted_at_the_proxy():
    """`/api/camera_proxy/` had to be added for this tile. It is the same KIND
    of thing as the three already there — an HA image path — and the list has
    to stay a list."""
    src = open(os.path.join(os.path.dirname(TPL), 'main.py'), encoding='utf-8').read()
    block = src[src.index('_HA_IMAGE_PREFIXES = ('):]
    block = block[:block.index(')')]
    check('/api/camera_proxy/' in block,
          "camera images are not allowlisted, so the tile 400s")
    check('media_player_proxy' in block and 'image_proxy' in block,
          "the existing allowlist entries were lost")


def scenario_an_entity_with_no_picture_says_so():
    stub = _HA(states=STATES)
    data = _with_ha(stub, lambda: home_board._tile_ha_image(
        NOW, config={'entity': 'light.kitchen'}))
    check(data.get('empty') == "That entity has no picture.",
          f"a picture-less entity produced {data!r}")


# --- the board's own rules still apply -------------------------------------

def scenario_neither_tile_is_on_by_default():
    """A household without Home Assistant must never be shown a tile about it,
    and one with HA has to choose which entities matter — there is no sensible
    default set of somebody else's sensors."""
    for type_ in ('ha', 'ha_image'):
        check(type_ not in home_board.DEFAULT_WIDGETS,
              f"'{type_}' is on every board by default")


def scenario_a_tile_with_no_page_is_not_a_link():
    """Every other tile is a door to the page it summarises. These summarise
    nothing of ours, and an <a> to a page that does not exist is a tap that
    empties the wall."""
    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    check("PAGELESS: ['ha', 'ha_image']" in tpl,
          "the Home Assistant tiles are linking somewhere again")
    check('opens(t.type) ? link(t.type) : null' in tpl,
          "the tile's href is unconditional, so a pageless tile is still a link")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} HA-tile scenarios passed")
