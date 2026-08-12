"""Home Assistant's BUILT-IN cards, drawn natively.

The hosting route in `ha_cards.py` is closed for these and always will be:
`type: gauge` resolves to an element compiled into HA's frontend bundle, so
there is no file to fetch. The way in is that a built-in card's config
COMPLETELY DESCRIBES IT — `type: entities` with four ids is not a program, it
is a request for four rows of name-and-reading.

Two things this file is really guarding:

  1. **The scope is a closed set, and its edge is stated out loud.** An
     unsupported built-in must be refused BY NAME with somewhere else to go. A
     card that silently renders as an empty box is the exact failure the board
     exists to avoid, and it is what "we support most of them" turns into.
  2. **Everything drawn came out of somebody's house.** Entity names, states
     and markdown content all arrive from Home Assistant, and "our own data" is
     what every injection bug has ever been made of.

Run from chauffeur/:  python tests/test_ha_card_convert.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_convert_'))

from services import ha_card_convert as conv  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def st(entity_id, state, **attrs):
    return {entity_id: {'entity_id': entity_id, 'state': state,
                        'attributes': attrs}}


STATES = {}
STATES.update(st('sensor.grid_power', '3300', unit_of_measurement='W',
                 friendly_name='Grid power'))
STATES.update(st('light.kitchen', 'on', friendly_name='Kitchen'))
STATES.update(st('sensor.battery', '87', unit_of_measurement='%',
                 friendly_name='Battery', icon='mdi:battery'))


def scenario_an_entities_card_is_rows_of_name_and_reading():
    card = conv.convert({
        'type': 'entities', 'title': 'Power',
        'entities': ['sensor.grid_power',
                     {'entity': 'light.kitchen', 'name': 'Kitchen lights'},
                     {'type': 'divider'},
                     {'entity': 'sensor.nope'}],
    }, STATES)
    check(card['kind'] == 'entities' and card['title'] == 'Power', f"wrong shape: {card}")
    rows = card['rows']
    check(rows[0]['name'] == 'Grid power' and rows[0]['state'] == '3300'
          and rows[0]['unit'] == 'W', f"the first row is wrong: {rows[0]}")
    check(rows[1]['name'] == 'Kitchen lights',
          f"a row's own name lost to the entity's: {rows[1]['name']}")
    check(rows[1]['toggleable'] and rows[1]['on'],
          f"a light is not offered as toggleable: {rows[1]}")
    check(rows[2]['kind'] == 'divider', f"the divider was dropped: {rows[2]}")
    # NAMED, not dropped — the same rule the plain entity tile follows.
    check(rows[3]['missing'] and rows[3]['name'] == 'sensor.nope',
          f"a missing entity vanished instead of being named: {rows[3]}")


def scenario_a_gauge_resolves_its_own_severity():
    """Severity is a rule about the CONFIG — "this colour from this value up" —
    so it is resolved here rather than in the browser, whose job is drawing."""
    cfg = {'type': 'gauge', 'entity': 'sensor.battery', 'min': 0, 'max': 100,
           'severity': {'red': 0, 'yellow': 50, 'green': 80}}
    card = conv.convert(cfg, STATES)
    check(card['kind'] == 'gauge' and card['value'] == 87.0, f"wrong value: {card}")
    check(abs(card['pct'] - 0.87) < 0.001, f"wrong fill: {card['pct']}")
    check(card['severity'] == 'green',
          f"87 out of 100 with green from 80 is green, got {card['severity']}")

    # The band BELOW the value wins, not the first one that matches.
    STATES2 = dict(STATES)
    STATES2.update(st('sensor.battery', '55', unit_of_measurement='%'))
    check(conv.convert(cfg, STATES2)['severity'] == 'yellow',
          "a mid-range value picked the wrong severity band")

    # A degenerate range must not divide by zero or invert the arc.
    weird = conv.convert({'type': 'gauge', 'entity': 'sensor.battery',
                          'min': 5, 'max': 5}, STATES)
    check(0.0 <= weird['pct'] <= 1.0, f"a zero-width gauge produced {weird['pct']}")

    # A non-numeric state is not a gauge reading, and must not become 0.
    nan = conv.convert({'type': 'gauge', 'entity': 'light.kitchen'}, STATES)
    check(nan['value'] is None and nan['pct'] is None,
          f"'on' was treated as a number: {nan}")


def scenario_stacks_nest_and_cannot_run_away():
    card = conv.convert({
        'type': 'vertical-stack',
        'cards': [
            {'type': 'horizontal-stack', 'cards': [
                {'type': 'tile', 'entity': 'light.kitchen'},
                {'type': 'gauge', 'entity': 'sensor.battery'},
            ]},
            {'type': 'entities', 'entities': ['sensor.grid_power']},
        ],
    }, STATES)
    check(card['kind'] == 'stack' and card['direction'] == 'vertical',
          f"the outer stack is wrong: {card}")
    check(card['cards'][0]['direction'] == 'horizontal',
          "a stack inside a stack did not survive")
    check(card['cards'][0]['cards'][0]['kind'] == 'tile',
          "a card inside a nested stack did not survive")

    # A config that nests itself is exactly what a hand-edited YAML file
    # produces, and without a fuse it recurses until the stack gives out.
    deep = {'type': 'vertical-stack', 'cards': []}
    node = deep
    for _ in range(12):
        child = {'type': 'vertical-stack', 'cards': [
            {'type': 'tile', 'entity': 'light.kitchen'}]}
        node['cards'].append(child)
        node = child
    conv.convert(deep, STATES)          # must simply return, not raise


def scenario_only_the_entities_a_card_names_are_asked_for():
    """The generic walk in ha_cards looks for anything entity-SHAPED, which is
    right for a custom card's unknown schema. Here the schema is known, so a
    label that happens to look like an entity id is not a state request."""
    ids = conv.entity_ids({
        'type': 'vertical-stack',
        'cards': [
            {'type': 'entities', 'entities': [
                'sensor.grid_power', {'entity': 'light.kitchen',
                                      'name': 'sensor.not_an_entity'}]},
            {'type': 'gauge', 'entity': 'sensor.battery'},
        ],
    })
    check(set(ids) == {'sensor.grid_power', 'light.kitchen', 'sensor.battery'},
          f"wrong entities requested: {ids}")
    check('sensor.not_an_entity' not in ids,
          "a row's NAME was mistaken for an entity id")


def scenario_everything_drawn_is_escaped():
    """Names and states come out of somebody's house. The markdown card is the
    one place raw HTML reaches the page, so its escaping is the load-bearing
    one — and it has to survive the markdown pass, not just precede it."""
    hostile = {}
    hostile.update(st('sensor.x', '<img src=x onerror=alert(1)>',
                      friendly_name='<script>alert(1)</script>'))
    card = conv.convert({'type': 'entities', 'entities': ['sensor.x']}, hostile)
    row = card['rows'][0]
    # The converter passes text through; the ESCAPING for these is the
    # renderer's job, so what matters here is that nothing is pre-rendered
    # into markup on the way past.
    check('<' in row['name'] and '<' in row['state'],
          "the converter is rewriting text it should be passing through")

    out = conv.markdown_to_html('# <script>alert(1)</script>\n\n'
                                '- **bold** and <b>raw</b>\n'
                                '- `<code>`')
    check('<script>' not in out, f"markdown let a script tag through: {out}")
    check('&lt;script&gt;' in out, f"the script tag was not escaped: {out}")
    check('<b>raw</b>' not in out, f"markdown let raw HTML through: {out}")
    # And the subset it DOES allow still works.
    check('<h1>' in out and '<strong>bold</strong>' in out and '<li>' in out,
          f"the markdown subset stopped working: {out}")


def scenario_an_unsupported_built_in_is_refused_by_name():
    """The edge of the closed set, stated out loud. This is what stops "we
    support most of them" from turning into a blank box on a wall."""
    from services import ha_cards
    for kind in ('history-graph', 'thermostat', 'statistic', 'media-control'):
        check(kind not in conv.NATIVE_CARDS, f"{kind} is claimed but untested")
        out = ha_cards.prepare(f'type: {kind}\nentity: sensor.grid_power')
        check(out.get('error'), f"{kind} did not produce an error: {out}")
        check(kind in out['error'] and 'dashboard tile' in out['error'],
              f"{kind}'s refusal does not name it or offer a way round: "
              f"{out['error']}")


def scenario_a_built_in_card_comes_back_as_a_drawing_not_a_download():
    """End to end through `prepare`: the two modes are distinguishable, and a
    native card carries no resource to fetch."""
    from services import ha_cards
    real = ha_cards.states_for
    try:
        ha_cards.states_for = lambda ids: {k: v for k, v in STATES.items()
                                           if k in set(ids)}
        out = ha_cards.prepare('type: entities\nentities:\n  - sensor.grid_power')
        check(out.get('mode') == 'native', f"a built-in card was not converted: {out}")
        check('resource' not in out and 'tag' not in out,
              f"a native card is being asked to fetch something: {out}")
        check(out['card']['rows'][0]['state'] == '3300',
              f"the states did not reach the drawing: {out['card']}")
        check(out['missing'] == [], f"nothing should be missing: {out['missing']}")
    finally:
        ha_cards.states_for = real


def scenario_the_gauge_arc_centres_itself():
    """Reported from a real board: the value and the name centred, the arc sat
    against the left edge, and the card read as broken rather than as
    misaligned.

    Tailwind's preflight sets `svg { display: block }`, so the arc is a block
    box capped at its max-width and the parent's `text-align: center` does
    nothing to it — while the text beside it centres perfectly, because that is
    inline. Every other svg on this board is full width, so this is the only
    place the rule shows, which is exactly why it is worth pinning.
    """
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates', 'home.html')
    css = open(tpl, encoding='utf-8').read()
    block = css[css.index('.nc-gauge-svg'):]
    block = block[:block.index('}')]
    check('margin-left: auto' in block and 'margin-right: auto' in block,
          f"the gauge arc no longer centres itself: {block!r}")

    sheet = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'static', 'tailwind.css')
    built = open(sheet, encoding='utf-8').read()
    if 'svg,video{display:block' not in built:
        # If preflight ever stops doing this, the auto margins are harmless and
        # the comment above is stale. Worth saying out loud rather than
        # silently keeping a workaround for a problem that has gone.
        print('  note  preflight no longer forces svg to display:block')


RENDER_HARNESS = r"""
globalThis.window = {
  location: { search: '', pathname: '/home' },
  matchMedia: function () { return { matches: false }; },
  addEventListener: function () {}, removeEventListener: function () {}
};
globalThis.document = {
  documentElement: { getAttribute: function () { return 'dark'; } },
  getElementById: function () { return null; },
  addEventListener: function () {}
};
globalThis.setInterval = function () { return 0; };
"""

RENDER_PROBE = r"""
const b = homeBoard();
const hostile = '<script>alert(1)</script>';
const out = b.drawCard({
  kind: 'entities', title: hostile,
  rows: [{ kind: 'entity', entity_id: 'light.x"onclick="evil()', name: hostile,
           state: hostile, unit: hostile, icon: 'mdi:x" onload="evil()',
           toggleable: true, missing: false, on: true }],
});
const gauge = b.drawCard({ kind: 'gauge', name: hostile, unit: hostile,
                           value: 42, pct: 0.42, severity: 'green', missing: false });
const stack = b.drawCard({ kind: 'stack', direction: 'grid', columns: 3,
  cards: [{ kind: 'tile', name: 'A', icon: 'mdi:a', state: '1',
            entity_id: 'light.a', toggleable: false, missing: false, on: false }] });
console.log(JSON.stringify({
  hasScript: /<script>/i.test(out + gauge + stack),
  escaped: out.includes('&lt;script&gt;'),
  // An entity id goes into an ATTRIBUTE, so a quote in it would end the
  // attribute and start a new one.
  brokenAttr: /data-toggle="[^"]*"[^>]*onclick/i.test(out),
  gaugeDrawn: gauge.includes('<svg') && gauge.includes('stroke-dasharray'),
  gridColumns: stack.includes('repeat(3,minmax(0,1fr))'),
}));
"""


def scenario_the_renderer_escapes_what_the_converter_passed_through():
    """The converter deliberately passes text through; escaping is the
    renderer's job because it is the thing building markup. So this is where
    the guarantee actually lives, and an entity id is the sharpest case — it
    goes into an ATTRIBUTE, where one quote ends the attribute and starts
    whatever the name felt like."""
    import json
    import re
    import shutil
    import subprocess

    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed')
        return
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates', 'home.html')
    src = open(tpl, encoding='utf-8').read()
    body = next(b for b in re.findall(r'<script>(.*?)</script>', src, re.S)
                if 'function homeBoard()' in b)
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'run.mjs')
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(RENDER_HARNESS + body + RENDER_PROBE)
        proc = subprocess.run([node, f], capture_output=True, text=True, timeout=60)
    check(proc.returncode == 0, f"the renderer threw:\n{proc.stderr[-1200:]}")
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    check(not got['hasScript'], "a script tag reached the drawn card")
    check(got['escaped'], "the hostile text was dropped rather than escaped — "
                          "which hides the problem instead of showing it safely")
    check(not got['brokenAttr'], "a quote in an entity id escaped its attribute")
    check(got['gaugeDrawn'], "the gauge no longer draws an arc")
    check(got['gridColumns'], "a grid stack lost its column count")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} card-conversion scenarios passed")
