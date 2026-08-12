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


def scenario_a_real_dashboard_stack_keeps_every_card():
    """Reported from a real board: a stack rendered ONE of its cards.

    The config was the ordinary shape — a custom power-flow card above a gauge,
    beside a column of graph cards. `convert` returned None for everything it
    could not draw itself and the stack filtered those out, so a three-column
    dashboard collapsed to a single gauge with nothing anywhere saying why.

    Two kinds of passenger have to survive: a `custom:` card (which the browser
    can run, so it becomes a host node) and a card this app does not draw at
    all (which becomes a named placeholder, keeping its cell so the columns
    either side do not shuffle up).
    """
    cfg = {'type': 'horizontal-stack', 'cards': [
        {'type': 'vertical-stack', 'cards': [
            {'type': 'custom:tesla-style-solar-power-card',
             'grid_to_house_entity': 'sensor.grid_power'},
            {'type': 'gauge', 'entity': 'sensor.battery', 'min': 0, 'max': 100},
        ]},
        {'type': 'vertical-stack', 'cards': [
            {'type': 'history-graph', 'entities': ['sensor.solar'],
             'title': 'Solar Energy'},
            {'type': 'media-control', 'entity': 'media_player.kitchen'},
        ]},
    ]}
    hosts = {}
    card = conv.convert(cfg, STATES, hosts=hosts)
    check(len(card['cards']) == 2, f"a column was dropped: {len(card['cards'])}")

    left, right = card['cards']
    check(len(left['cards']) == 2, f"the left column lost a card: {left}")
    check(left['cards'][0]['kind'] == 'host',
          f"the custom card was dropped instead of hosted: {left['cards'][0]}")
    check(left['cards'][0]['tag'] == 'tesla-style-solar-power-card',
          f"the hosted card lost its element name: {left['cards'][0]}")
    check(left['cards'][1]['kind'] == 'gauge', "the gauge stopped converting")

    check(len(right['cards']) == 2, f"the column collapsed: {right}")
    for node in right['cards']:
        check(node['kind'] == 'unsupported',
              f"an undrawable card vanished instead of being named: {node}")
    check(right['cards'][0]['name'] == 'Solar Energy',
          "the placeholder does not say which card it stands for")
    check(right['cards'][0]['type'] == 'history-graph',
          f"the placeholder does not name the card type: {right['cards'][0]}")

    # The host is collected so its file can be resolved once for the tree.
    check(list(hosts) == ['h0'] and hosts['h0']['tag'] ==
          'tesla-style-solar-power-card', f"hosts not collected: {hosts}")
    check(left['cards'][0]['host_id'] == 'h0',
          "the drawing cannot find the host it belongs to")

    # And a hosted card's OWN entities are requested, through the shape-based
    # walk — its schema belongs to its author, not to us.
    ids = conv.entity_ids(cfg)
    check('sensor.grid_power' in ids,
          f"a hosted card inside a stack gets no states: {ids}")
    check('sensor.battery' in ids and 'sensor.solar' in ids,
          f"the native cards' entities went missing: {ids}")


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


def scenario_an_icon_follows_what_the_entity_measures():
    """Reported off a real board: a column of energy sensors all drawn as the
    same generic eye.

    The domain map only knows that something is a `sensor`. Home Assistant
    resolves the icon from `device_class` first, which is why its version of
    the same dashboard has a lightning bolt, a battery and a car on it.
    """
    states = {}
    states.update(st('sensor.exported', '24', device_class='energy',
                     friendly_name='Exported'))
    states.update(st('sensor.temp', '71', device_class='temperature'))
    states.update(st('sensor.plain', '3', friendly_name='Something'))
    states.update(st('sensor.chosen', '3', icon='mdi:pool', device_class='energy'))

    card = conv.convert({'type': 'entities', 'entities': [
        'sensor.exported', 'sensor.temp', 'sensor.plain', 'sensor.chosen']}, states)
    icons = [r['icon'] for r in card['rows']]
    check(icons[0] == 'mdi:lightning-bolt', f"an energy sensor drew {icons[0]}")
    check(icons[1] == 'mdi:thermometer', f"a temperature sensor drew {icons[1]}")
    # No device class and no icon: the domain fallback is the LAST resort, and
    # it is allowed to be generic.
    check(icons[2] == 'mdi:eye', f"the fallback changed: {icons[2]}")
    # An icon somebody chose beats everything, including the class.
    check(icons[3] == 'mdi:pool', f"the entity's own icon lost: {icons[3]}")

    # A binary sensor's icon carries its STATE — a door icon that does not
    # change when the door opens is a picture, not a reading.
    binaries = {}
    binaries.update(st('binary_sensor.front', 'on', device_class='door'))
    binaries.update(st('binary_sensor.back', 'off', device_class='door'))
    rows = conv.convert({'type': 'entities', 'entities':
                         ['binary_sensor.front', 'binary_sensor.back']}, binaries)['rows']
    check(rows[0]['icon'] == 'mdi:door-open' and rows[1]['icon'] == 'mdi:door-closed',
          f"an open door and a closed one look the same: "
          f"{[r['icon'] for r in rows]}")

    # And the precision an integration asks for travels to the renderer.
    precise = {}
    precise.update(st('sensor.meter', '1.23456', device_class='gas',
                      suggested_display_precision=3))
    row = conv.convert({'type': 'entities', 'entities': ['sensor.meter']},
                       precise)['rows'][0]
    check(row['precision'] == 3, f"the entity's own precision was dropped: {row}")


def scenario_a_state_is_said_the_way_home_assistant_says_it():
    """Reported side-by-side: a motion sensor reading `on` where HA reads
    `Clear`. That is not merely terser — for a binary sensor, `off` is a word
    most people read as "the sensor is off" rather than "nothing is moving",
    which is the opposite of what it means."""
    states = {}
    states.update(st('binary_sensor.front', 'off', device_class='motion',
                     friendly_name='Front Door Motion'))
    states.update(st('binary_sensor.leak', 'on', device_class='moisture'))
    states.update(st('lock.pool', 'unlocked', friendly_name='Pool'))
    states.update(st('light.hall', 'on'))
    states.update(st('sensor.power', '3300', unit_of_measurement='W'))

    rows = conv.convert({'type': 'entities', 'entities': [
        'binary_sensor.front', 'binary_sensor.leak', 'lock.pool',
        'light.hall', 'sensor.power']}, states)['rows']
    said = [r['state'] for r in rows]
    check(said[0] == 'Clear', f"a quiet motion sensor reads {said[0]!r}")
    check(said[1] == 'Wet', f"a wet leak sensor reads {said[1]!r}")
    check(said[2] == 'Unlocked', f"an unlocked lock reads {said[2]!r}")
    check(said[3] == 'On', f"a light that is on reads {said[3]!r}")
    # A NUMBER is not a state to translate. Rounding is the renderer's job and
    # the raw value has to survive to get there.
    check(said[4] == '3300', f"a numeric reading was mangled: {said[4]!r}")


def scenario_an_area_card_leads_with_its_photograph():
    """`display_type: picture` is the household saying which they want — they
    bothered to upload a photo of the pool house. The picture lives in the AREA
    REGISTRY, which is websocket-only; there is no template function for it,
    so it is the one thing here that cannot come down the same pipe as the rest.
    """
    from services import ha_api
    real_map, real_reg = ha_api.get_area_map, ha_api.get_area_registry
    try:
        ha_api.get_area_map = lambda ttl=60: [
            {'id': 'pool_house', 'name': 'Pool House',
             'entities': ['light.pool', 'binary_sensor.pool_motion']}]
        ha_api.get_area_registry = lambda ttl=300: [
            {'area_id': 'pool_house', 'name': 'Pool House',
             'picture': '/api/image/serve/abc/original', 'icon': 'mdi:pool'}]
        states = {}
        states.update(st('light.pool', 'on', friendly_name='Pool light'))
        states.update(st('binary_sensor.pool_motion', 'on', device_class='motion',
                         friendly_name='Pool motion'))

        card = conv.convert({'type': 'area', 'area': 'pool_house',
                             'display_type': 'picture',
                             'alert_classes': ['motion']}, states)
        check(card['picture'] == '/api/image/serve/abc/original',
              f"the room's photograph was not found: {card['picture']}")
        check(card['display'] == 'picture', f"the display type was lost: {card}")
        check(card['icon'] == 'mdi:pool', f"the area's own icon was lost: {card}")
        # The alert carries its CLASS's icon. A motion badge drawn as a generic
        # warning triangle says "something is wrong" about a room somebody has
        # just walked through.
        check(card['alerts'][0]['icon'] == 'mdi:motion-sensor',
              f"an alert drew a generic warning: {card['alerts'][0]}")

        # And a card that did NOT ask for a picture does not become one —
        # turning every existing area card into a photograph would be
        # redesigning boards nobody touched.
        plain = conv.convert({'type': 'area', 'area': 'pool_house'}, states)
        check(plain['display'] == 'compact',
              f"an area card promoted itself to a picture: {plain['display']}")
    finally:
        ha_api.get_area_map, ha_api.get_area_registry = real_map, real_reg


def scenario_a_sensor_card_downsamples_its_own_history():
    """The only card here that is not a pure function of a config and a state.

    Downsampled SERVER-side: a day of a chatty sensor is thousands of samples,
    and shipping them to draw a line eighty pixels wide would make the graph
    the largest thing in the board payload by an order of magnitude.
    """
    from services import ha_api
    real = ha_api.get_history
    try:
        # Four hours of readings, one a minute, with two junk values in it —
        # 'unavailable' is not a datum and must not become 0 and dent the line.
        import datetime as dt
        base = dt.datetime(2026, 8, 12, 6, 0, tzinfo=dt.timezone.utc)
        rows = []
        for i in range(240):
            value = 'unavailable' if i in (7, 88) else str(20 + (i % 60) / 10)
            rows.append(((base + dt.timedelta(minutes=i)).isoformat(), value))
        ha_api.get_history = lambda entity_id, hours=24: rows

        card = conv.convert({'type': 'sensor', 'entity': 'sensor.grid_power',
                             'graph': 'line', 'hours_to_show': 4,
                             'name': 'Solar'}, STATES)
        check(card['kind'] == 'sensor' and card['name'] == 'Solar', f"wrong card: {card}")
        check(1 < len(card['points']) <= 96,
              f"the history was not downsampled: {len(card['points'])} points")
        check(all(isinstance(p, float) for p in card['points']),
              "a non-numeric sample became part of the line")
        check(card['min'] <= card['max'], f"the range is inverted: {card}")
        check(card['min'] >= 20.0, f"'unavailable' was counted as a value: {card['min']}")

        # `graph: none` is a reading with no line, and must not query history.
        asked = []
        ha_api.get_history = lambda entity_id, hours=24: (asked.append(1), rows)[1]
        plain = conv.convert({'type': 'sensor', 'entity': 'sensor.grid_power'}, STATES)
        check(plain['points'] == [] and not asked,
              "a card with no graph still went and fetched a day of history")
    finally:
        ha_api.get_history = real


def scenario_a_thermostat_says_what_it_is_doing():
    """The mode and the ACTION disagree constantly — a thermostat set to heat
    is idle most of the time — and the one somebody walking past wants is the
    action."""
    states = {}
    states.update(st('climate.hall', 'heat', friendly_name='Hall',
                     current_temperature=68, temperature=71,
                     min_temp=45, max_temp=95, target_temp_step=1,
                     hvac_action='heating'))
    card = conv.convert({'type': 'thermostat', 'entity': 'climate.hall'}, states)
    check(card['current'] == 68.0 and card['target'] == 71.0, f"wrong readings: {card}")
    check(card['action'] == 'Heating' and card['mode'] == 'heat',
          f"the action and the mode are not both carried: {card}")
    check(card['tone'] == 'warm', "a heating thermostat is not drawn warm")
    # The dial tracks the TARGET, which is the number the arrows move.
    check(abs(card['pct'] - (71 - 45) / (95 - 45)) < 0.001, f"wrong fill: {card['pct']}")

    # A range thermostat carries both ends rather than picking one.
    states.update(st('climate.range', 'heat_cool', current_temperature=70,
                     target_temp_low=68, target_temp_high=74,
                     min_temp=45, max_temp=95))
    both = conv.convert({'type': 'thermostat', 'entity': 'climate.range'}, states)
    check(both['target_low'] == 68.0 and both['target_high'] == 74.0,
          f"a dual setpoint was collapsed: {both}")

    # And a missing entity does not become a thermostat reading 0.
    gone = conv.convert({'type': 'thermostat', 'entity': 'climate.nope'}, states)
    check(gone['missing'] and gone['current'] is None,
          f"a missing thermostat invented a temperature: {gone}")


def scenario_an_area_card_asks_home_assistant_what_is_in_the_room():
    """An area card names no entities at all — it names an AREA, and the
    entities come from HA's registry. Without resolving that, the card would be
    handed an empty states map and draw an empty room."""
    from services import ha_api
    real = ha_api.get_area_map
    try:
        ha_api.get_area_map = lambda ttl=60: [
            {'id': 'kitchen', 'name': 'Kitchen',
             'entities': ['light.kitchen', 'sensor.kitchen_temp',
                          'binary_sensor.kitchen_motion', 'sensor.grid_power']},
        ]
        ids = conv.entity_ids({'type': 'area', 'area': 'kitchen'})
        check('light.kitchen' in ids and 'sensor.kitchen_temp' in ids,
              f"the area's entities were not requested: {ids}")

        states = dict(STATES)
        states.update(st('sensor.kitchen_temp', '71',
                         unit_of_measurement='°F', device_class='temperature'))
        states.update(st('binary_sensor.kitchen_motion', 'on',
                         device_class='motion', friendly_name='Motion'))
        card = conv.convert({'type': 'area', 'area': 'kitchen'}, states)
        check(card['name'] == 'Kitchen', f"the area lost its name: {card['name']}")
        check([r['class'] for r in card['readings']] == ['temperature'],
              f"the readings are wrong: {card['readings']}")
        check(len(card['alerts']) == 1 and card['alerts'][0]['class'] == 'motion',
              f"an active alert was missed: {card['alerts']}")
        check([t['entity_id'] for t in card['toggles']] == ['light.kitchen'],
              f"the room's switches are wrong: {card['toggles']}")
        # A sensor in the room that is not a listed class is NOT a reading —
        # an area card is a summary, not a dump of everything in the room.
        check(all(r['class'] in ('temperature', 'humidity') for r in card['readings']),
              "the area card is showing every sensor in the room")

        # An area that does not exist says so rather than drawing a blank room.
        missing = conv.convert({'type': 'area', 'area': 'nowhere'}, states)
        check(missing['empty'], f"an unknown area drew as a real one: {missing}")
    finally:
        ha_api.get_area_map = real


def scenario_an_unsupported_built_in_is_refused_by_name():
    """The edge of the closed set, stated out loud. This is what stops "we
    support most of them" from turning into a blank box on a wall."""
    from services import ha_cards
    for kind in ('history-graph', 'statistic', 'media-control', 'light',
                 'energy-distribution'):
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
// Numbers, as somebody would write them down.
const numbers = [
  [b.fmt('43.6834340349917'), '43.68'],
  [b.fmt('0.430565965008326538477427'), '0.43'],
  [b.fmt('1234.5678'), '1,234.57'],
  [b.fmt('100'), '100'],
  [b.fmt('100', 2), '100.00'],
  [b.fmt('3.4', 0), '3'],
  [b.fmt('on'), 'on'],
  [b.fmt(null), '—'],
];

// A smoothed, filled sparkline.
const spark = b.drawCard({ kind: 'sensor', name: 'Home Usage', icon: 'mdi:home',
  state: '43.6834340349917', unit: 'kWh', missing: false, hours: 24,
  points: [1, 3, 2, 5, 4, 6], min: 1, max: 6 });

// A nested stack: the leaf cards get a surface, the cell holding a stack does not.
const nested = b.drawCard({ kind: 'stack', direction: 'vertical', cards: [
  { kind: 'stack', direction: 'horizontal', cards: [
    { kind: 'entities', title: 'A', rows: [] }] },
  { kind: 'gauge', name: 'B', value: 1, pct: 0.5, min: 0, max: 2, missing: false },
]});

const stack = b.drawCard({ kind: 'stack', direction: 'grid', columns: 3,
  cards: [{ kind: 'tile', name: 'A', icon: 'mdi:a', state: '1',
            entity_id: 'light.a', toggleable: false, missing: false, on: false }] });

// TITLED cards in a row. A card with a title draws two top-level elements —
// its heading and its body — and flex counts children, not cards.
const titledRow = b.drawCard({ kind: 'stack', direction: 'horizontal', cards: [
  { kind: 'entities', title: 'Left', rows: [] },
  { kind: 'entities', title: 'Right', rows: [] },
]});
console.log(JSON.stringify({
  hasScript: /<script>/i.test(out + gauge + stack),
  escaped: out.includes('&lt;script&gt;'),
  // An entity id goes into an ATTRIBUTE, so a quote in it would end the
  // attribute and start a new one.
  brokenAttr: /data-toggle="[^"]*"[^>]*onclick/i.test(out),
  gaugeDrawn: gauge.includes('<svg') && gauge.includes('stroke-dasharray'),
  gridColumns: stack.includes('repeat(3,minmax(0,1fr))'),
  // Two cards in the row means two cells, whatever each card drew inside.
  rowCells: (titledRow.match(/class="nc-cell"/g) || []).length,
  rowKeptTitles: titledRow.includes('Left') && titledRow.includes('Right'),
  numbers: numbers,
  sparkSmooth: /C[\d.]+,[\d.]+ /.test(spark),
  sparkFilled: spark.includes('linearGradient') && spark.includes('url(#ncg'),
  sparkClosed: spark.includes('L100,30 L0,30 Z'),
  sparkRounded: spark.includes('43.68') && !spark.includes('43.6834'),
  unitSplit: spark.includes('nc-unit'),
  nestedPlain: nested.includes('class="nc-cell" data-plain'),
  leafSurfaced: /class="nc-cell">/.test(nested),
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
    # One cell per CARD, not per element. A titled card draws its heading and
    # its body as siblings, and flex/grid count children — so two titled cards
    # in a horizontal stack laid out as FOUR equal columns with the headings in
    # two of them, which is the shape every example in HA's own docs uses.
    check(got['rowCells'] == 2,
          f"two cards in a horizontal stack produced {got['rowCells']} cells")
    check(got['rowKeptTitles'], "wrapping the cards dropped their titles")

    # Numbers, as somebody would write them down. An energy sensor's state is
    # `43.6834340349917`, and printing it whole is the difference between a
    # dashboard and a debug view — it also makes the row a different width
    # every time the last digit changes.
    for got_value, want in got['numbers']:
        check(got_value == want, f"formatted {got_value!r}, expected {want!r}")

    # The graph. Straight segments between downsampled buckets make a line look
    # like a seismograph, and every corner is an artefact of the bucketing
    # rather than anything the sensor did.
    check(got['sparkSmooth'], "the sparkline is back to straight segments")
    check(got['sparkFilled'] and got['sparkClosed'],
          "the sparkline lost the area under it, which is what makes it read "
          "as a quantity over time rather than as a scratch")
    check(got['sparkRounded'], "the sensor card is printing a raw float")
    check(got['unitSplit'],
          "the unit is the same weight as the value again, which doubles the "
          "width of every reading and halves how fast one can be read")

    # Each card in a stack gets its own surface — side by side with Home
    # Assistant that was most of the difference. A cell holding another stack
    # stays plain, or the surfaces nest.
    check(got['leafSurfaced'], "a card in a stack has no surface of its own")
    check(got['nestedPlain'], "a stack inside a stack drew a surface inside a surface")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} card-conversion scenarios passed")
