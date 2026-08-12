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
                          ('ha_image', {'entity': 'camera.driveway'}),
                          ('ha_dashboard', {'path': 'lovelace/0'})):
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
    needs_ha = ('ha', 'ha_image', 'ha_dashboard')
    for w in cat['widgets']:
        if w['key'] in needs_ha:
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

def scenario_the_camera_tile_has_somewhere_to_draw():
    """The bug that made cameras show nothing at all, and the reason it was
    invisible: the picture is a `flex-1 min-h-0` box with an absolutely
    positioned <img> inside it. In a NON-flex parent `flex-1` does nothing, the
    box is zero pixels tall, and the photograph has nowhere to go. No error, no
    console line — a heading over nothing.

    A tile is given `flex flex-col` only when `fillsTile()` says its content is
    drawn INTO the slot rather than read down a list, which is exactly what a
    camera is."""
    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    drawn = tpl[tpl.index('DRAWN_TILES:'):]
    drawn = drawn[:drawn.index(']')]
    for type_ in ('ha_image', 'ha_dashboard'):
        check(f"'{type_}'" in drawn,
              f"{type_} is not a drawn tile, so its container gets no height "
              f"and the tile renders as a heading over nothing")


def scenario_a_camera_does_not_depend_on_a_rotating_token():
    """`entity_picture` on a camera carries `?token=`, which Home Assistant
    rotates every few minutes. This board's payload is cached, then cached
    again by the browser, so a panel can easily be holding a URL whose token
    has expired. `/api/camera_proxy/<entity_id>` needs no token — the proxy hop
    carries our bearer."""
    import base64
    stub = _HA(states=STATES)
    data = _with_ha(stub, lambda: home_board._tile_ha_image(
        NOW, config={'entity': 'camera.driveway'}))
    token = data['url'].rsplit('/', 1)[-1]
    path = base64.urlsafe_b64decode(token + '=' * (-len(token) % 4)).decode()
    check(path == '/api/camera_proxy/camera.driveway',
          f"the camera tile is still pointing at {path!r}")
    check('token=' not in path,
          "the camera URL carries a rotating token that will outlive its cache")


def scenario_an_entity_that_is_not_there_says_that_rather_than_no_picture():
    """'That entity has no picture' and 'that entity does not exist' send a
    household looking in two different places."""
    stub = _HA(states=STATES)
    data = _with_ha(stub, lambda: home_board._tile_ha_image(
        NOW, config={'entity': 'camera.deleted_last_month'}))
    check(data.get('empty') == "That entity is not in Home Assistant.",
          f"a missing entity reported as {data!r}")


# --- the dashboard frame ---------------------------------------------------

def scenario_a_dashboard_view_is_framed_not_reimplemented():
    """The honest answer to "render HA cards". A Lovelace card is a custom
    element wanting a live `hass` object and an authenticated websocket; it
    cannot run here. HA rendering it in a frame can."""
    stub = _HA(states=STATES)
    data = _with_ha(stub, lambda: home_board._tile_ha_dashboard(
        NOW, config={'path': 'lovelace/0'}, settings={}))
    check(data.get('url') == '/lovelace/0',
          f"with no browser base configured the frame should be root-relative "
          f"(ingress, same origin), got {data.get('url')!r}")
    check(data.get('same_origin') is True,
          "the tile no longer reports that it is relying on being under ingress")


def scenario_the_browser_url_is_not_the_server_url():
    """Under the Supervisor `ha_base_url` is `http://supervisor/core` —
    correct for us, meaningless in a browser. The frame needs the address a
    person would type, which is a separate setting on purpose."""
    stub = _HA(states=STATES)
    data = _with_ha(stub, lambda: home_board._tile_ha_dashboard(
        NOW, config={'path': 'lovelace/0'},
        settings={'ha_browser_url': 'http://homeassistant.local:8123/',
                  'ha_base_url': 'http://supervisor/core'}))
    check(data['url'] == 'http://homeassistant.local:8123/lovelace/0',
          f"the frame used the wrong base: {data['url']}")
    check(data['same_origin'] is False,
          "a cross-origin frame is still claiming to be same-origin")

    # And read off the RESOLVED url, not off whether a base is set: a `path`
    # typed as a full https:// address is cross-origin however empty the
    # setting is.
    absolute = _with_ha(stub, lambda: home_board._tile_ha_dashboard(
        NOW, config={'path': 'https://ha.example/lovelace/0'}, settings={}))
    check(absolute['same_origin'] is False,
          "a full https:// path with no base configured reported itself as "
          "same-origin, which is the one thing it cannot be")

    src = open(os.path.join(os.path.dirname(TPL), 'services', 'home_board.py'),
               encoding='utf-8').read()
    block = src[src.index('def ha_browser_base('):]
    block = block[:block.index('\ndef ')]
    check('ha_base_url' not in block.split('"""')[-1],
          "ha_browser_base() reads the SERVER's url, which under the "
          "Supervisor is http://supervisor/core and is not a browser address")


def scenario_the_dashboard_tile_needs_no_page_and_no_home_assistant_check():
    """Same two rules as the other HA tiles: not a door, and gone entirely
    when there is no Home Assistant configured."""
    stub = _HA(available=False)
    data = _with_ha(stub, lambda: home_board._tile_ha_dashboard(
        NOW, config={'path': 'lovelace/0'}, settings={}))
    check(data is None, f"no Home Assistant, but the frame tile returned {data!r}")

    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    check("'ha_dashboard'" in tpl[tpl.index('PAGELESS:'):tpl.index('PAGELESS:') + 120],
          "the dashboard tile is a link to a Chauffeur page that does not exist")


def scenario_the_frame_is_not_sandboxed():
    """A dashboard needs its own scripts, its websocket and its storage.
    Sandboxing it produces a blank frame and a mysterious console error — and
    it is HA's page on HA's origin, not a place for our containment."""
    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    frame = tpl[tpl.index("t.type === 'ha_dashboard'"):]
    frame = frame[:frame.index('</template>')]
    check('sandbox' not in frame,
          "the dashboard frame is sandboxed, which will render it blank")
    check('haFrameSrc' in frame, "the frame lost its src binding")


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
    check("PAGELESS: ['ha', 'ha_image', 'ha_dashboard']" in tpl,
          "the Home Assistant tiles are linking somewhere again")
    check('opens(t.type) ? link(t.type) : null' in tpl,
          "the tile's href is unconditional, so a pageless tile is still a link")


# --- hiding Home Assistant's own chrome ------------------------------------

CHROME_HARNESS = r"""
const { JSDOM } = require('jsdom');

// A stand-in for Home Assistant's frontend: the same nesting and the same
// element names, with real shadow roots. If HA renames one of these, this
// harness keeps passing and the wall keeps its header — which is why the
// element names are ALSO pinned as literals in the scenario below.
const dom = new JSDOM('<!doctype html><html><body></body></html>');
const d = dom.window.document;

function shadowed(parent, tag) {
  const el = d.createElement(tag);
  el.attachShadow({ mode: 'open' });
  (parent.shadowRoot || parent).appendChild(el);
  return el;
}
const ha = d.createElement('home-assistant');
ha.attachShadow({ mode: 'open' });
d.body.appendChild(ha);
const main = shadowed(ha, 'home-assistant-main');
// `ha-drawer` sits between main and the content, and its OWN shadow root is
// where `.mdc-drawer-app-content` lives — the element carrying the margin that
// leaves a hole where the sidebar was. Missing this level out of the harness
// is what let "sidebar hidden, gap intact" pass.
const drawer = shadowed(main, 'ha-drawer');
const appContent = d.createElement('div');
appContent.className = 'mdc-drawer-app-content';
drawer.shadowRoot.appendChild(appContent);
// LIGHT DOM, as HA has it: `partial-panel-resolver` is a slotted child of
// ha-drawer, so it lives in home-assistant-main's shadow TREE and
// `mainRoot.querySelector` finds it. Putting it inside ha-drawer's shadow root
// instead would be a harness that disagrees with the app it is testing.
const resolver = d.createElement('partial-panel-resolver');
drawer.appendChild(resolver);
const panel = d.createElement('ha-panel-lovelace');
panel.attachShadow({ mode: 'open' });
resolver.appendChild(panel);          // light DOM, as HA has it
shadowed(panel, 'hui-root');

const board = { stripHaChrome: __STRIP__ };
const frame = { contentDocument: d };
board.stripHaChrome.call(board, frame, 0);

const mainRoot = ha.shadowRoot.querySelector('home-assistant-main').shadowRoot;
const drawerRoot = mainRoot.querySelector('ha-drawer').shadowRoot;
const huiHost = mainRoot.querySelector('partial-panel-resolver')
  .querySelector('ha-panel-lovelace').shadowRoot;
const huiRoot = huiHost.querySelector('hui-root').shadowRoot;
console.log(JSON.stringify({
  sidebarStyle: !!mainRoot.querySelector('#chf-no-sidebar'),
  gapStyle: !!drawerRoot.querySelector('#chf-no-gap'),
  gapCss: (drawerRoot.querySelector('#chf-no-gap') || {}).textContent || '',
  headerStyle: !!huiRoot.querySelector('#chf-no-header'),
  headerCss: (huiRoot.querySelector('#chf-no-header') || {}).textContent || '',
  // Run it again: a reload must not stack a second stylesheet in.
  twice: (function () {
    board.stripHaChrome.call(board, frame, 0);
    return mainRoot.querySelectorAll('#chf-no-sidebar').length;
  })(),
}));
"""


def _strip_fn():
    """The `stripHaChrome` method, lifted whole out of the template by brace
    matching so it survives being reformatted."""
    import re as _re
    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    body = next(b for b in _re.findall(r'<script>(.*?)</script>', tpl, _re.S)
                if 'function homeBoard()' in b)
    start = body.index('stripHaChrome(frame, tries) {')
    i = body.index('{', start)
    depth = 0
    for j in range(i, len(body)):
        if body[j] == '{':
            depth += 1
        elif body[j] == '}':
            depth -= 1
            if depth == 0:
                return 'function (frame, tries) ' + body[i:j + 1]
    raise AssertionError('stripHaChrome is unbalanced')


def _run_chrome():
    import json
    import shutil
    import subprocess
    import tempfile as _tf
    node = shutil.which('node')
    if not node:
        print('  SKIP  node not installed')
        return None
    with _tf.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, 'run.js')
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(CHROME_HARNESS.replace('__STRIP__', _strip_fn()))
        proc = subprocess.run([node, f], capture_output=True, text=True,
                              cwd=os.path.dirname(TPL))
    if proc.returncode != 0:
        if 'Cannot find module' in proc.stderr and 'jsdom' in proc.stderr:
            print('  SKIP  jsdom not installed')
            return None
        raise AssertionError(f"the chrome stripper threw:\n{proc.stderr[-1500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_the_header_and_sidebar_are_actually_removed():
    """Stock Home Assistant has no query parameter for this — `?kiosk` belongs
    to the kiosk-mode integration. What we can do instead is reach into the
    frame, which is same-origin under ingress, and put a stylesheet into each
    shadow root that owns the thing being hidden. A parent stylesheet cannot:
    that is precisely what a shadow root is for.

    Run against a stand-in with HA's nesting and real shadow roots, because
    "did the style land in the right root" is the only claim worth making."""
    got = _run_chrome()
    if got is None:
        return
    check(got['sidebarStyle'],
          "no stylesheet reached home-assistant-main's shadow root, so the "
          "sidebar stays")
    check(got['headerStyle'],
          "no stylesheet reached hui-root's shadow root, so the dashboard "
          "keeps its header")
    for needed in ('.header', 'app-header', 'display: none'):
        check(needed in got['headerCss'], f"the header rule lost {needed!r}")

    # THE GAP, which is a separate failure from the sidebar and was shipped
    # once on its own: hiding `ha-sidebar` removes the sidebar and leaves the
    # hole it sat in, because the space is a MARGIN on the content beside it.
    # That margin is inside `ha-drawer`'s shadow root, one level below the root
    # the sidebar rule goes into, so a rule aimed at the wrong root matches
    # nothing and looks like it worked.
    check(got['gapStyle'],
          "no stylesheet reached ha-drawer's shadow root, so the sidebar is "
          "hidden and the empty space it occupied is still there")
    for needed in ('.mdc-drawer-app-content', 'margin-left: 0',
                   'margin-inline-start: 0'):
        check(needed in got['gapCss'], f"the gap rule lost {needed!r}")
    check(got['twice'] == 1,
          f"a reload stacked {got['twice']} stylesheets into the same root")


def scenario_the_element_names_it_depends_on_are_written_down():
    """The harness above builds the tree it expects, so a Home Assistant
    rename would keep it green while the wall quietly grew its header back.
    Pinning the literals is the honest half: when HA restructures its frontend
    this fails and names what to go and look at."""
    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    # Scoped to the stripper itself: some of these names are querySelector
    # arguments and some are CSS selectors inside the injected stylesheet, so
    # the check is for the NAME, not for a quoted string.
    fn = tpl[tpl.index('stripHaChrome(frame, tries) {'):]
    fn = fn[:fn.index('async toggleEntity')]
    for name in ('home-assistant', 'home-assistant-main', 'partial-panel-resolver',
                 'ha-panel-lovelace', 'hui-root', 'ha-sidebar', 'ha-drawer',
                 'mdc-drawer-app-content'):
        check(name in fn,
              f"the chrome stripper no longer looks for <{name}> — if Home "
              f"Assistant renamed it, update the traversal; if we dropped it, "
              f"the header is coming back")


def scenario_hiding_is_skipped_cross_origin_rather_than_attempted():
    """A cross-origin frame's document is not ours to read, and trying throws
    a SecurityError into the console on every load of a tile that was already
    never going to work."""
    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    fn = tpl[tpl.index('haFrameLoaded(tile, frame) {'):]
    fn = fn[:fn.index('stripHaChrome(frame, tries)')]
    check('tile.data.same_origin' in fn,
          "the chrome stripper runs cross-origin, where it can only throw")
    check("!== 'hide'" in fn,
          "the tile no longer honours 'leave the dashboard as it is'")


def scenario_the_retry_is_bounded():
    """HA builds its component tree after `load`, so the first attempt misses.
    A MutationObserver inside a live dashboard would run for as long as the
    panel is up, on a Raspberry Pi, for three seconds' worth of benefit."""
    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    fn = tpl[tpl.index('stripHaChrome(frame, tries) {'):]
    fn = fn[:fn.index('async toggleEntity')]
    # Comments stripped: this rule is EXPLAINED in a comment right here, and a
    # guard that trips on its own rationale is a guard nobody keeps.
    code = '\n'.join(l for l in fn.splitlines()
                     if not l.strip().startswith('//'))
    check('MutationObserver' not in code,
          "the chrome stripper installs an observer inside the dashboard")
    check('tries > 0' in fn and 'tries - 1' in fn,
          "the retry is no longer bounded, so a dashboard that never matches "
          "retries for as long as the panel is up")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} HA-tile scenarios passed")
