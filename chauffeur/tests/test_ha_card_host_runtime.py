"""static/ha_card_host.js, actually RUN.

The host is the environment a stranger's JavaScript wakes up in on a screen in
a kitchen, and two of its properties are contracts rather than choices:

  1. **The theme names.** A card reads `--primary-text-color`; the panel
     defines `--panel-fg`. The map between them is the only reason a card can
     be made to match this wall, and renaming a token would repaint every
     hosted card in the wrong colour with nothing failing anywhere — no error,
     no test, just a card that has quietly gone grey.
  2. **Read-only means read-only.** `interactive` defaults off on the tile,
     and a card that calls a service anyway must be refused HERE as well as at
     the endpoint. Two locks, because the card is somebody else's code.

Same technique as test_home_board_runtime: run it in node against a DOM thin
enough to be honest. What needs a real browser — whether a card DRAWS — was
proven separately against the real tesla-style-solar-power-card and
power-flow-card-plus bundles; see docs/ha_card_hosting.md.

Run from chauffeur/:  python tests/test_ha_card_host_runtime.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'static')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# Only what the module touches while LOADING. Anything else it reaches for
# should fail loudly here rather than quietly on the wall.
HARNESS = r"""
globalThis.window = {};
globalThis.document = { head: {}, createElement: function () { return {}; } };
"""

PROBE = r"""
const H = window.ChauffeurHaCards;
const calls = [];
// Both, because in a browser these are the same function and in node they are
// not — the host calls bare `fetch`, which here would otherwise be node's own.
window.fetch = globalThis.fetch = function (url, opts) {
  calls.push({ url: url, body: JSON.parse((opts || {}).body || '{}') });
  return Promise.resolve({ ok: true });
};

const states = { 'sensor.a': { entity_id: 'sensor.a', state: '3300' } };
// The board's shared pool: what lets a card that DISCOVERS its devices by
// walking hass.states find the house. Named states must win a collision.
H.setStates({ 'media_player.tv': { entity_id: 'media_player.tv', state: 'off' },
              'sensor.a': { entity_id: 'sensor.a', state: 'stale-pool-copy' } });
const ro = H._makeHass({ states: states, interactive: false, apiBase: '' });
const rw = H._makeHass({ states: states, interactive: true, apiBase: '' });

Promise.allSettled([
  ro.callService('light', 'turn_on', { entity_id: 'light.x' }),
  rw.callService('light', 'turn_on', { entity_id: 'light.x' }),
  ro.connection.subscribeMessage({}),
]).then(function (r) {
  console.log(JSON.stringify({
    theme: H._theme,
    fixed: H._themeFixed,
    statesPassThrough: ro.states['sensor.a'].state,
    poolMergedUnder: ro.states['media_player.tv'].state === 'off'
                     && ro.states['sensor.a'].state === '3300',
    readOnlyRejected: r[0].status === 'rejected',
    interactiveAllowed: r[1].status === 'fulfilled',
    statisticsRejected: r[2].status === 'rejected',
    serviceCalls: calls,
    // A card asking for an unknown translation gets HA's own answer, so the
    // `localize(...) || fallback` every card is written around still works.
    localizeEmpty: ro.localize('ui.card.whatever') === '',
    // The shape a real card indexes into. Mushroom reads
    // `translationMetadata.translations[language]` OUTSIDE a try, so an absent
    // one threw mid-render and left an empty box on the wall — with nothing
    // anywhere naming the missing field.
    hasShape: ['translationMetadata', 'entities', 'devices', 'areas', 'config',
               'themes', 'locale', 'user'].filter(k => !ro[k]),
    translationsIndexable: !!(ro.translationMetadata.translations
                              && ro.translationMetadata.translations[ro.language]),
    // Registries are a websocket away and the board does not ship them. EMPTY
    // rather than absent: indexing an empty map gives undefined and a card
    // falls back; indexing `undefined` throws.
    registriesEmptyNotAbsent: typeof ro.entities === 'object'
                              && Object.keys(ro.entities).length === 0,
    formatsAttribute: ro.formatEntityAttributeValue(
      { attributes: { friendly_name: 'Hall' } }, 'friendly_name') === 'Hall',
  }));
});
"""


# The BUILT-IN mount, run for real against a stub runtime. Everything HA's
# own frontend would have provided is faked as thinly as the code path allows
# — a bundle response, a webpack require that resolves, a registry that has
# `hui-area-card` in it — so that what is being tested is our mount, and the
# two properties a real card reads off the element we hand it.
BUILTIN_PROBE = r"""
const H = window.ChauffeurHaCards;

function fakeEl(tag) {
  return {
    tagName: tag, _config: null, _appended: [],
    style: { setProperty: function () {}, display: '' },
    classList: { add: function () {}, toggle: function () {} },
    setConfig: function (c) { this._config = c; },
    setAttribute: function () {},
    appendChild: function (c) { this._appended.push(c); },
    textContent: '',
  };
}
globalThis.document = {
  head: { appendChild: function () {} },
  createElement: fakeEl,
  addEventListener: function () {},
};
// The hourly picture tick would hold node's event loop open for an hour.
globalThis.setInterval = function () { return 0; };
globalThis.getComputedStyle = function () {
  return { getPropertyValue: function () { return ''; } };
};
window.customElements = {
  get: function (tag) { return tag === 'hui-area-card' ? function () {} : null; },
  define: function () {},
};
// The borrowed runtime, already up: a require that resolves and a chunk
// loader that loads nothing.
var wpr = function () { return Promise.resolve(); };
wpr.e = function () { return Promise.resolve(); };
window.__haWpr = wpr;

var BUNDLE = {
  ok: true, version: 'test', runtime: 'runtime.js',
  cards: { area: { chunks: [], module: 1 } },
  chunks: [], eager_modules: [],
  entities: {}, devices: {},
  areas: { study: { area_id: 'study', name: 'Study', picture: 'api/ha/image?p=1' } },
  config: { version: '2026.8.0' },
  i18n: {},
};
window.fetch = globalThis.fetch = function (url) {
  return Promise.resolve({ ok: true, json: function () {
    return Promise.resolve(BUNDLE);
  } });
};

var container = fakeEl('div');
container.clientWidth = 300;
H.mountBuiltin(container, {
  id: 't/h0', type: 'area', apiBase: '',
  config: { type: 'area', area: 'study', name: 'Main House' },
}).then(function (ok) {
  var el = container._appended[0] || {};
  var hass = el.hass || {};
  var stateObj = { entity_id: 'sensor.a',
                   attributes: { friendly_name: 'Sensor A' } };
  console.log(JSON.stringify({
    mounted: ok,
    // What the sections view sets on every card it lays out. The area card
    // reads it to decide whether its photograph is a 16:9 block or fills the
    // space above the name; without it the name is pushed out of the card.
    layout: el.layout === undefined ? null : el.layout,
    isPanel: el.isPanel === undefined ? null : el.isPanel,
    // A card passes its `name:` as the SECOND argument here, and a string
    // there IS the answer. Ignoring it is how a named card reverted to the
    // entity's own name the moment the real card mounted.
    namedByConfig: hass.formatEntityName
      ? hass.formatEntityName(stateObj, 'Main House') : null,
    unnamedFallsBack: hass.formatEntityName
      ? hass.formatEntityName(stateObj) : null,
  }));
});
"""


def _run(probe=None):
    node = shutil.which('node')
    if not node:
        return None
    src = open(os.path.join(STATIC, 'ha_card_host.js'), encoding='utf-8').read()
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                     encoding='utf-8') as fh:
        fh.write(HARNESS + src + (probe or PROBE))
        path = fh.name
    try:
        out = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise AssertionError(f"the host would not run: {out.stderr[:600]}")
        return json.loads(out.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)


def scenario_the_theme_bridge_is_a_contract():
    got = _run()
    if got is None:
        print("  skip  node is not installed")
        return
    theme = got['theme']
    # What a card actually reads. Every one of these appears in the two real
    # bundles this was proven against.
    for var in ('--primary-color', '--primary-text-color', '--secondary-text-color',
                '--card-background-color', '--ha-card-background', '--divider-color'):
        check(var in theme, f"{var} is no longer supplied to hosted cards")
    for var, token in (('--primary-text-color', '--panel-fg'),
                       ('--secondary-text-color', '--panel-dim'),
                       ('--primary-color', '--panel-accent'),
                       ('--divider-color', '--panel-line')):
        check(theme[var] == token,
              f"{var} should follow the panel's {token}, got {theme[var]!r}")

    fixed = got['fixed']
    # The card brings the shape; the TILE brings the surface. A card drawing
    # its own background and shadow inside a panel-card is the seam that gives
    # an embed away.
    check(theme['--ha-card-background'] == 'transparent'
          and fixed['--ha-card-box-shadow'] == 'none',
          "a hosted card must not paint a second card behind itself")
    # Semantic colours are deliberately NOT panel tokens: green means the same
    # thing on every wall, and repainting it in the accent colour erases what
    # the card is saying.
    for var in ('--success-color', '--warning-color', '--error-color'):
        check(fixed.get(var, '').startswith('#'),
              f"{var} must stay a literal colour, not a panel token")


def scenario_a_card_cannot_operate_a_read_only_tile():
    got = _run()
    if got is None:
        print("  skip  node is not installed")
        return
    check(got['readOnlyRejected'],
          "a card called a service on a tile that was not made interactive")
    check(got['interactiveAllowed'], "an interactive tile must let its card act")
    # Two cards asked; one was refused. Exactly one request left the page,
    # which is what proves the refusal happened BEFORE the network rather than
    # after a round trip the server then had to reject.
    check(len(got['serviceCalls']) == 1,
          f"exactly one service call should have left the page, got "
          f"{len(got['serviceCalls'])}")
    check(got['serviceCalls'][0]['body'] == {
        'domain': 'light', 'service': 'turn_on', 'data': {'entity_id': 'light.x'}},
        f"the call reached the server malformed: {got['serviceCalls'][0]}")


def scenario_what_we_cannot_do_fails_fast():
    got = _run()
    if got is None:
        print("  skip  node is not installed")
        return
    check(got['statesPassThrough'] == '3300', "the board's states must reach the card")
    check(got['localizeEmpty'], "localize must answer '' like HA's own does")
    # A card wanting live statistics is asking for a websocket the panel does
    # not hold. Rejecting lets it fall back or say so; a promise that never
    # settles leaves a spinner on the wall forever.
    check(got['statisticsRejected'],
          "a statistics subscription must be refused, not left hanging")


def scenario_the_pool_reaches_a_discovering_card():
    """`setStates` (the board's whole-house pool) merges UNDER a card's own
    named states: a card walking `hass.states` finds the house, and a row the
    card named beats the pool's copy of the same row."""
    out = _run()
    if out is None:
        print("  skip  node is not installed")
        return
    check(out['poolMergedUnder'],
          "the pool is missing from hass.states, or it shadowed a named row")


def scenario_the_hass_shape_is_complete_enough_to_index_into():
    """The failure this guards is the worst kind: silent.

    A mushroom lock card rendered as an EMPTY BOX on a real board, because it
    reads `hass.translationMetadata.translations[language]` outside a try while
    working out how to format. Nothing in the tile said which field was
    missing — the card simply drew nothing. That is the argument for filling in
    the whole shape rather than the parts a known card happens to touch.
    """
    got = _run()
    if got is None:
        print("  skip  node is not installed")
        return
    check(not got['hasShape'],
          f"a card indexing into these gets undefined and throws: {got['hasShape']}")
    check(got['translationsIndexable'],
          "translationMetadata.translations has no entry for the language we "
          "claim, which is exactly the lookup that emptied a card")
    check(got['registriesEmptyNotAbsent'],
          "the entity registry is absent rather than empty — indexing an empty "
          "map gives undefined and a card falls back; indexing undefined throws")
    check(got['formatsAttribute'], "formatEntityAttributeValue does not format")


def scenario_a_hosted_builtin_is_told_it_is_in_a_grid():
    """`layout` is what tells a card it has a box rather than a page.

    A board tile is a grid cell with a height somebody chose, which is exactly
    what HA's sections view is — and HA sets `layout = 'grid'` on every card it
    lays out there. The area card branches on it: in a grid its photograph
    fills whatever is left above the name, and everywhere else it is forced to
    16:9. Unset, the card drew a full 16:9 picture in a fixed-height cell and
    pushed its own name out of the bottom.
    """
    got = _run(BUILTIN_PROBE)
    if got is None:
        print("  skip  node is not installed")
        return
    check(got['mounted'], "the built-in mount did not complete")
    check(got['layout'] == 'grid',
          f"a hosted built-in is laid out in a grid cell but was told "
          f"layout={got['layout']!r} — the area card's picture will be 16:9 "
          f"and its name will be clipped")
    check(got['isPanel'] is False,
          "isPanel must be explicitly false: HA sets it alongside layout, and "
          "`undefined` is not what a card checking it expects")


def scenario_a_cards_own_name_survives_the_real_card():
    """`hass.formatEntityName(stateObj, config.name)` — the second argument.

    Every modern hui-* card asks the hass object to name its entity and passes
    its own `name:` along. HA answers a string there by returning it unchanged.
    Our shim took one argument, so the name a household typed was dropped and
    the card reverted to the entity's friendly name — visibly, a beat after the
    converter fallback had shown the right one.
    """
    got = _run(BUILTIN_PROBE)
    if got is None:
        print("  skip  node is not installed")
        return
    check(got['namedByConfig'] == 'Main House',
          f"a card's own name: was ignored — formatEntityName returned "
          f"{got['namedByConfig']!r}")
    check(got['unnamedFallsBack'] == 'Sensor A',
          f"with no name in the config the entity's own name is the answer, "
          f"not {got['unnamedFallsBack']!r}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} card-host runtime scenarios passed")
