"""Home Assistant's BUILT-IN cards, drawn natively.

`ha_cards.py` runs a custom card by fetching its own JavaScript. That route is
closed for built-in cards and always will be: `type: gauge` resolves to
`hui-gauge-card`, which is compiled into Home Assistant's frontend bundle and
is not a loadable resource. There is no file to fetch.

The good news is that it does not need to be fetched, because **a built-in
card's config completely describes it**. `type: entities` with four entity ids
is not a program, it is a request for four rows of name-and-reading, and this
module answers that request in the panel's own vocabulary. That makes it better
than hosting rather than a consolation prize: no borrowed CSS variables, no
element shims, nothing to break when a card author ships an update — and the
result can be told to fit its tile, which a hosted card cannot.

The scope is deliberately the HEAD of the distribution, not the tail. Custom
cards are unbounded and bespoke, which is why they are hosted; built-ins are a
CLOSED SET that Home Assistant adds to roughly once a year, so a dozen
renderers is the whole job rather than the first instalment of an endless one.

What is here: entities, glance, tile, gauge, markdown, picture-entity, button,
and the three stacks (vertical, horizontal, grid) that hold them.

What is not, and why:
  - `history-graph`, `sensor`, `statistic` — these need history or the
    statistics websocket, which is a different piece of plumbing rather than a
    different drawing.
  - `thermostat`, `light`, `media-control` — control surfaces with their own
    interaction models. The board's rule is that a display does not change what
    it is displaying; these would need the tile's interactive switch and a
    careful think about what a mis-tap costs.
  - `conditional`, `entity-filter` — these are logic, not layout, and the
    honest place for that logic is a tile option.
An unsupported built-in is REFUSED BY NAME, with the framed dashboard offered
as the way to get it. A card that silently renders as an empty box is the
failure this whole board exists to avoid.
"""

import html
import re

# Everything this module can draw. `ha_cards.prepare` asks before deciding
# whether a config is convertible, hostable, or neither.
NATIVE_CARDS = {
    'entities', 'glance', 'tile', 'gauge', 'markdown', 'picture-entity',
    'button', 'vertical-stack', 'horizontal-stack', 'grid',
    'sensor', 'thermostat', 'area',
}

STACKS = {'vertical-stack': 'vertical', 'horizontal-stack': 'horizontal',
          'grid': 'grid'}

# A per-domain fallback so a row is never iconless. HA picks icons from the
# device class as well, which is a deeper lookup than this needs — an entity
# that cares almost always carries `attributes.icon` anyway.
_DOMAIN_ICON = {
    'light': 'mdi:lightbulb', 'switch': 'mdi:toggle-switch', 'fan': 'mdi:fan',
    'lock': 'mdi:lock', 'cover': 'mdi:window-shutter', 'climate': 'mdi:thermostat',
    'sensor': 'mdi:eye', 'binary_sensor': 'mdi:checkbox-marked-circle',
    'person': 'mdi:account', 'device_tracker': 'mdi:map-marker',
    'media_player': 'mdi:speaker', 'camera': 'mdi:camera',
    'input_boolean': 'mdi:toggle-switch-outline', 'vacuum': 'mdi:robot-vacuum',
    'weather': 'mdi:weather-partly-cloudy', 'sun': 'mdi:white-balance-sunny',
    'automation': 'mdi:robot', 'script': 'mdi:script-text',
    'scene': 'mdi:palette', 'button': 'mdi:gesture-tap-button',
    'number': 'mdi:ray-vertex', 'select': 'mdi:format-list-bulleted',
}

# Domains a tap may operate, kept identical to the entity tile's allowlist —
# see home_board.HA_TOGGLE_DOMAINS. Duplicated as a name rather than imported
# because importing home_board from here would be a cycle.
_TOGGLE_DOMAINS = ('light', 'switch', 'fan', 'input_boolean')


# What an entity MEASURES, which is what Home Assistant picks its icon from.
#
# The domain map below only knows that something is a `sensor`, and a board of
# energy sensors drawn as a column of identical eyes is what that looks like on
# a wall. HA's frontend resolves the icon from `device_class` first, and this is
# the same table for the classes a household actually puts on a dashboard.
_SENSOR_CLASS_ICON = {
    'energy': 'mdi:lightning-bolt', 'power': 'mdi:flash',
    'power_factor': 'mdi:angle-acute', 'current': 'mdi:current-ac',
    'voltage': 'mdi:sine-wave', 'frequency': 'mdi:sine-wave',
    'battery': 'mdi:battery', 'temperature': 'mdi:thermometer',
    'humidity': 'mdi:water-percent', 'pressure': 'mdi:gauge',
    'atmospheric_pressure': 'mdi:thermometer-lines',
    'illuminance': 'mdi:brightness-5', 'signal_strength': 'mdi:wifi',
    'timestamp': 'mdi:clock', 'duration': 'mdi:progress-clock',
    'monetary': 'mdi:cash', 'gas': 'mdi:meter-gas', 'water': 'mdi:water',
    'carbon_dioxide': 'mdi:molecule-co2', 'carbon_monoxide': 'mdi:molecule-co2',
    'pm25': 'mdi:molecule', 'pm10': 'mdi:molecule', 'aqi': 'mdi:air-filter',
    'speed': 'mdi:speedometer', 'wind_speed': 'mdi:weather-windy',
    'precipitation': 'mdi:weather-rainy',
    'precipitation_intensity': 'mdi:weather-pouring',
    'data_size': 'mdi:database', 'data_rate': 'mdi:transmission-tower',
    'distance': 'mdi:arrow-left-right', 'weight': 'mdi:weight',
    'volume': 'mdi:car-coolant-level', 'moisture': 'mdi:water-percent',
    'ph': 'mdi:ph', 'sound_pressure': 'mdi:ear-hearing',
    'irradiance': 'mdi:sun-wireless', 'enum': 'mdi:format-list-bulleted',
}

# Binary sensors are the same idea with a state in it: a door icon that does
# not change when the door opens is a picture, not a reading. (on, off)
_BINARY_CLASS_ICON = {
    'motion': ('mdi:motion-sensor', 'mdi:motion-sensor-off'),
    'occupancy': ('mdi:home', 'mdi:home-outline'),
    'presence': ('mdi:home', 'mdi:home-outline'),
    'door': ('mdi:door-open', 'mdi:door-closed'),
    'garage_door': ('mdi:garage-open', 'mdi:garage'),
    'window': ('mdi:window-open', 'mdi:window-closed'),
    'opening': ('mdi:square-outline', 'mdi:square'),
    'lock': ('mdi:lock-open', 'mdi:lock'),
    'moisture': ('mdi:water', 'mdi:water-off'),
    'smoke': ('mdi:smoke', 'mdi:smoke-detector'),
    'gas': ('mdi:alert-circle', 'mdi:check-circle'),
    'problem': ('mdi:alert-circle', 'mdi:check-circle'),
    'safety': ('mdi:alert-circle', 'mdi:check-circle'),
    'battery': ('mdi:battery-alert', 'mdi:battery'),
    'connectivity': ('mdi:check-network-outline', 'mdi:close-network-outline'),
    'running': ('mdi:play', 'mdi:stop'),
    'power': ('mdi:power-plug', 'mdi:power-plug-off'),
    'sound': ('mdi:music-note', 'mdi:music-note-off'),
    'vibration': ('mdi:vibrate', 'mdi:crop-portrait'),
    'update': ('mdi:package-up', 'mdi:package'),
    'plug': ('mdi:power-plug', 'mdi:power-plug-off'),
    'tamper': ('mdi:alert-circle', 'mdi:check-circle'),
}


def _domain(entity_id):
    return str(entity_id or '').split('.', 1)[0]


def _icon_for(entity_id, attrs, state):
    """What Home Assistant would draw for this entity, in this state.

    Order matters and is HA's: the entity's own icon (somebody chose it), then
    what it measures, then what kind of thing it is. The last of those is the
    one that produces a column of identical eyes, and it is meant to be the
    last resort rather than the answer.
    """
    if attrs.get('icon'):
        return attrs['icon']
    domain = _domain(entity_id)
    cls = str(attrs.get('device_class') or '').lower()
    if domain == 'binary_sensor':
        pair = _BINARY_CLASS_ICON.get(cls)
        if pair:
            return pair[0] if str(state or '').lower() == 'on' else pair[1]
    if cls in _SENSOR_CLASS_ICON:
        return _SENSOR_CLASS_ICON[cls]
    return _DOMAIN_ICON.get(domain) or 'mdi:eye'


# What `on` MEANS, per binary-sensor device class. HA translates these and a
# board that prints the raw state says "on" where Home Assistant says "Clear" —
# which for a motion sensor is not just terser, it is the opposite reading to
# the one somebody glancing at it will take. (on, off)
_BINARY_CLASS_STATE = {
    'motion': ('Detected', 'Clear'), 'occupancy': ('Detected', 'Clear'),
    'presence': ('Home', 'Away'), 'gas': ('Detected', 'Clear'),
    'smoke': ('Detected', 'Clear'), 'moisture': ('Wet', 'Dry'),
    'door': ('Open', 'Closed'), 'garage_door': ('Open', 'Closed'),
    'window': ('Open', 'Closed'), 'opening': ('Open', 'Closed'),
    'lock': ('Unlocked', 'Locked'), 'problem': ('Problem', 'OK'),
    'safety': ('Unsafe', 'Safe'), 'tamper': ('Detected', 'Clear'),
    'connectivity': ('Connected', 'Disconnected'),
    'battery': ('Low', 'Normal'), 'battery_charging': ('Charging', 'Not charging'),
    'running': ('Running', 'Not running'), 'power': ('Detected', 'Clear'),
    'plug': ('Plugged in', 'Unplugged'), 'sound': ('Detected', 'Clear'),
    'vibration': ('Detected', 'Clear'), 'update': ('Available', 'Up-to-date'),
    'cold': ('Cold', 'Normal'), 'heat': ('Hot', 'Normal'),
    'light': ('Detected', 'Clear'), 'moving': ('Moving', 'Not moving'),
}


def _state_label(entity_id, attrs, state):
    """The state as Home Assistant would SAY it.

    A binary sensor's `on` is a machine's word for it. HA prints "Clear" for a
    motion sensor that is off — and printing `off` there is not merely terser,
    it is a word most people read as "the sensor is off" rather than "nothing
    is moving".
    """
    raw = str(state if state is not None else '')
    if not raw:
        return raw
    domain = _domain(entity_id)
    low = raw.lower()
    if domain in ('binary_sensor', 'lock', 'input_boolean', 'switch', 'light',
                  'fan', 'cover', 'person', 'device_tracker'):
        if domain == 'binary_sensor':
            pair = _BINARY_CLASS_STATE.get(
                str(attrs.get('device_class') or '').lower())
            if pair:
                return pair[0] if low == 'on' else (pair[1] if low == 'off' else raw)
        if low in ('on', 'off', 'open', 'closed', 'locked', 'unlocked',
                   'home', 'not_home', 'unavailable', 'unknown', 'idle',
                   'jammed', 'opening', 'closing', 'locking', 'unlocking'):
            return {'not_home': 'Away', 'unavailable': 'Unavailable',
                    'unknown': 'Unknown'}.get(low, low.replace('_', ' ').title())
    return raw


def _row(entity_id, states, name=None, icon=None, secondary=None):
    """One entity, as a reading. The shape every list-ish card here uses.

    A MISSING entity is named rather than dropped, which is the same rule the
    plain entity tile follows: a row quietly vanishing from a wall is how a
    household stops trusting the wall.
    """
    st = (states or {}).get(entity_id)
    attrs = (st or {}).get('attributes') or {}
    domain = _domain(entity_id)
    return {
        'entity_id': entity_id,
        'name': name or attrs.get('friendly_name') or entity_id,
        # Said the way HA says it: a motion sensor reads "Clear", not "off".
        'state': _state_label(entity_id, attrs, (st or {}).get('state')),
        'unit': attrs.get('unit_of_measurement'),
        'icon': icon or _icon_for(entity_id, attrs, (st or {}).get('state')),
        # How many decimals the integration wants shown. Absent for most
        # entities, which is why the renderer's own default (two) is what
        # actually stops `43.6834340349917` reaching a wall.
        'precision': attrs.get('suggested_display_precision'),
        'secondary': secondary,
        'missing': st is None,
        'toggleable': domain in _TOGGLE_DOMAINS,
        'on': str((st or {}).get('state') or '').lower() == 'on',
    }


def _entity_of(item):
    """An `entities:` row is a bare id or a dict. Both, here, once."""
    if isinstance(item, str):
        return item, {}
    if isinstance(item, dict):
        return str(item.get('entity') or '').strip(), item
    return '', {}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --- markdown ---------------------------------------------------------------
#
# A deliberately small subset, and escaped FIRST. Everything that reaches here
# has passed through Home Assistant — a template's output, an entity's state —
# and while that is the household's own data, "our own data" is exactly what
# every injection bug has been made of. So the text is escaped and then a fixed
# set of patterns is allowed back in; nothing can widen that set by containing
# angle brackets.
_MD_INLINE = [
    (re.compile(r'\*\*(.+?)\*\*'), r'<strong>\1</strong>'),
    (re.compile(r'(?<!\*)\*([^*]+?)\*(?!\*)'), r'<em>\1</em>'),
    (re.compile(r'`([^`]+?)`'), r'<code>\1</code>'),
]


def markdown_to_html(text):
    out, in_list = [], False
    for raw in str(text or '').splitlines():
        line = html.escape(raw.rstrip())
        for pattern, repl in _MD_INLINE:
            line = pattern.sub(repl, line)
        stripped = line.strip()
        bullet = re.match(r'^[-*]\s+(.*)$', stripped)
        heading = re.match(r'^(#{1,4})\s+(.*)$', stripped)
        if bullet:
            if not in_list:
                out.append('<ul>')
                in_list = True
            out.append(f'<li>{bullet.group(1)}</li>')
            continue
        if in_list:
            out.append('</ul>')
            in_list = False
        if heading:
            level = min(4, len(heading.group(1)))
            out.append(f'<h{level}>{heading.group(2)}</h{level}>')
        elif stripped:
            out.append(f'<p>{stripped}</p>')
    if in_list:
        out.append('</ul>')
    return ''.join(out)


# --- the cards --------------------------------------------------------------

def _entities_card(config, states, kind='entities'):
    rows = []
    for item in (config.get('entities') or []):
        entity_id, extra = _entity_of(item)
        # `type: section` / `divider` rows carry no entity. A section is a
        # heading and worth keeping; a divider is a line and worth keeping.
        row_type = str(extra.get('type') or '').lower()
        if not entity_id:
            if row_type in ('section', 'divider'):
                rows.append({'kind': row_type, 'name': extra.get('label') or ''})
            continue
        rows.append(dict(_row(entity_id, states,
                              name=extra.get('name'), icon=extra.get('icon'),
                              secondary=extra.get('secondary_info')),
                         kind='entity'))
    return {'kind': kind, 'title': config.get('title'), 'rows': rows,
            'columns': _num(config.get('columns')) or None,
            'show_name': config.get('show_name', True),
            'show_state': config.get('show_state', True)}


def _tile_card(config, states):
    entity_id = str(config.get('entity') or '').strip()
    row = _row(entity_id, states, name=config.get('name'), icon=config.get('icon'))
    return {'kind': 'tile', **row,
            'vertical': bool(config.get('vertical')),
            'features': []}


def _gauge_card(config, states):
    entity_id = str(config.get('entity') or '').strip()
    row = _row(entity_id, states, name=config.get('name'))
    value = _num(row.get('state'))
    lo = _num(config.get('min'))
    hi = _num(config.get('max'))
    lo = 0.0 if lo is None else lo
    hi = 100.0 if hi is None else hi
    if hi <= lo:
        hi = lo + 1
    # Severity is HA's own shape: {green: 0, yellow: 25, red: 50} meaning "this
    # colour from this value up". Resolved HERE rather than in the browser
    # because it is a rule about the config, and the browser's job is drawing.
    severity = config.get('severity') if isinstance(config.get('severity'), dict) else {}
    colour = None
    if value is not None and severity:
        best = None
        for name, start in severity.items():
            start_n = _num(start)
            if start_n is None or value < start_n:
                continue
            if best is None or start_n >= best[1]:
                best = (name, start_n)
        colour = best[0] if best else None
    pct = None
    if value is not None:
        pct = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    return {'kind': 'gauge', 'name': row['name'], 'unit': config.get('unit')
            or row.get('unit'), 'value': value, 'min': lo, 'max': hi,
            'pct': pct, 'severity': colour, 'missing': row['missing'],
            'needle': bool(config.get('needle'))}


def _markdown_card(config, states):
    """The content, with Home Assistant rendering any template in it.

    Templates go to HA rather than being evaluated here, because they are
    Jinja with HA's own functions in scope (`states()`, `is_state()`,
    `area_name()`) and reimplementing that would be reimplementing Home
    Assistant. A render failure falls back to the raw text — a card showing its
    own source is ugly and truthful, which beats a blank card.
    """
    content = str(config.get('content') or '')
    rendered = content
    if '{{' in content or '{%' in content:
        try:
            from services import ha_api
            # `render_template` returns the rendered TEXT parsed as JSON — its
            # callers are contracted to end with `| to_json` for exactly that
            # reason. Markdown wants a string, so the content is captured into
            # a block and that block is what gets serialised; appending
            # `| to_json` to the content itself would only work for a config
            # that happened to be a single expression.
            out = ha_api.render_template('{% set _c %}' + content
                                         + '{% endset %}{{ _c | to_json }}')
            if isinstance(out, str):
                rendered = out
        except Exception as e:
            print(f"[ha_card_convert] markdown template failed: {e}")
    return {'kind': 'markdown', 'title': config.get('title'),
            'html': markdown_to_html(rendered)}


def _picture_entity_card(config, states):
    entity_id = str(config.get('entity') or '').strip()
    row = _row(entity_id, states, name=config.get('name'))
    st = (states or {}).get(entity_id) or {}
    attrs = st.get('attributes') or {}
    # An explicit `image:` wins; otherwise the entity's own picture, which is
    # what makes this card work for cameras and people without being told.
    picture = config.get('image') or attrs.get('entity_picture')
    return {'kind': 'picture', 'name': row['name'], 'state': row['state'],
            'unit': row['unit'], 'missing': row['missing'],
            'picture': picture,
            'camera': _domain(entity_id) == 'camera',
            'entity_id': entity_id,
            'show_name': config.get('show_name', True),
            'show_state': config.get('show_state', True)}


def _button_card(config, states):
    entity_id = str(config.get('entity') or '').strip()
    row = _row(entity_id, states, name=config.get('name'), icon=config.get('icon'))
    tap = config.get('tap_action') if isinstance(config.get('tap_action'), dict) else {}
    return {'kind': 'button', 'name': row['name'], 'icon': row['icon'],
            'state': row['state'], 'entity_id': entity_id,
            'missing': row['missing'] and bool(entity_id),
            'on': row['on'],
            # Only `toggle` is offered, and only on the same domains the entity
            # tile allows. `call-service` from a pasted config is a button on a
            # kitchen wall that can do anything the household's HA can do.
            'action': ('toggle' if row['toggleable']
                       and str(tap.get('action') or 'toggle') == 'toggle' else None),
            'show_name': config.get('show_name', True),
            'show_state': config.get('show_state', False)}


def _sensor_card(config, states):
    """The mini graph card: a reading, and where it has been.

    The only card here that needs HISTORY, which is why it arrived later than
    the rest — a drawing is a pure function of a config and a state, and this
    one is not. `ha_api.get_history` caches for five minutes so the board's
    twenty-second rebuild does not turn into a history query per sensor per
    rebuild forever.

    Downsampled HERE rather than in the browser. A day of a chatty sensor is
    thousands of samples, and shipping them to draw a line eighty pixels wide
    would make the graph the largest thing in the board payload by an order of
    magnitude.
    """
    from services import ha_api
    entity_id = str(config.get('entity') or '').strip()
    row = _row(entity_id, states, name=config.get('name'), icon=config.get('icon'))
    hours = int(_num(config.get('hours_to_show')) or 24)
    hours = max(1, min(168, hours))
    # HA's own `detail`: 1 is hourly, 2 is finer. The cap is what keeps a week
    # at detail 2 from becoming two thousand points nobody can see.
    detail = 2 if int(_num(config.get('detail')) or 1) >= 2 else 1
    buckets = min(96, hours * (12 if detail == 2 else 1)) or 1

    points, lo, hi = [], None, None
    if str(config.get('graph') or 'none').lower() == 'line' and entity_id:
        import datetime as _dt
        raw = []
        for stamp, value in ha_api.get_history(entity_id, hours) or []:
            num = _num(value)
            if num is None:
                continue                      # 'unavailable' is not a datum
            try:
                when = _dt.datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
            except ValueError:
                continue
            raw.append((when.timestamp(), num))
        if raw:
            first, last = raw[0][0], raw[-1][0]
            span = max(1.0, last - first)
            sums = [[0.0, 0] for _ in range(buckets)]
            for when, num in raw:
                i = min(buckets - 1, int((when - first) / span * buckets))
                sums[i][0] += num
                sums[i][1] += 1
            points = [round(s / n, 3) for s, n in sums if n]
            if points:
                lo, hi = min(points), max(points)
    return {'kind': 'sensor', 'name': row['name'], 'icon': row['icon'],
            'state': row['state'], 'precision': row.get('precision'),
            'unit': config.get('unit') or row.get('unit'),
            'missing': row['missing'], 'points': points,
            'min': lo, 'max': hi, 'hours': hours}


# What a climate entity is DOING, as against what it is set to. The two
# disagree constantly — a thermostat set to heat is idle most of the time —
# and the one somebody walking past wants is the action.
_HVAC_ACTION_LABEL = {
    'heating': 'Heating', 'cooling': 'Cooling', 'drying': 'Drying',
    'fan': 'Fan', 'idle': 'Idle', 'off': 'Off', 'preheating': 'Preheating',
}
_HVAC_ACTION_COLOUR = {
    'heating': 'warm', 'preheating': 'warm', 'cooling': 'cool', 'drying': 'cool',
}


def _thermostat_card(config, states):
    """A climate entity, as a dial.

    Read-only unless the tile's own interactive switch is on, and even then
    only the setpoint moves — the mode, the presets and the fan are a control
    panel, and a control panel on a kitchen wall at child height is a different
    conversation from a number two arrows can nudge.
    """
    entity_id = str(config.get('entity') or '').strip()
    st = (states or {}).get(entity_id) or {}
    attrs = st.get('attributes') or {}
    row = _row(entity_id, states, name=config.get('name'))
    current = _num(attrs.get('current_temperature'))
    target = _num(attrs.get('temperature'))
    lo = _num(attrs.get('target_temp_low'))
    hi = _num(attrs.get('target_temp_high'))
    floor = _num(attrs.get('min_temp'))
    ceiling = _num(attrs.get('max_temp'))
    floor = 45.0 if floor is None else floor
    ceiling = 95.0 if ceiling is None else ceiling
    if ceiling <= floor:
        ceiling = floor + 1
    action = str(attrs.get('hvac_action') or '').lower()
    # The dial's fill tracks the TARGET, because that is the number the arrows
    # move and the one the drawing has to make legible when it changes.
    pin = target if target is not None else current
    pct = None if pin is None else max(0.0, min(1.0, (pin - floor) / (ceiling - floor)))
    return {'kind': 'thermostat', 'entity_id': entity_id, 'name': row['name'],
            'missing': row['missing'], 'current': current, 'target': target,
            'target_low': lo, 'target_high': hi,
            'min': floor, 'max': ceiling, 'pct': pct,
            'mode': st.get('state'),
            'action': _HVAC_ACTION_LABEL.get(action, action.title() or None),
            'tone': _HVAC_ACTION_COLOUR.get(action),
            'step': _num(attrs.get('target_temp_step')) or 0.5,
            'unit': attrs.get('unit_of_measurement') or '°'}


# What an area card puts on screen, by device class. HA's own defaults, because
# a household that has arranged their areas in Home Assistant expects the same
# card to say the same things here.
_AREA_SENSORS = ('temperature', 'humidity')
_AREA_ALERTS = ('motion', 'moisture', 'door', 'window', 'smoke', 'gas')
_AREA_TOGGLES = ('light', 'switch', 'fan')


def area_entities(area_ref):
    """The entity ids in an area, by id or by name.

    Resolved through `ha_api.get_area_map`, which uses HA's own
    `area_entities()` template function — that is what picks up entities whose
    area comes from their DEVICE rather than from themselves, which is most of
    them, and is exactly the logic not worth reimplementing here.
    """
    from services import ha_api
    want = str(area_ref or '').strip().lower()
    if not want:
        return []
    for area in ha_api.get_area_map() or []:
        if str(area.get('id') or '').lower() == want \
                or str(area.get('name') or '').lower() == want:
            return [e for e in (area.get('entities') or []) if isinstance(e, str)]
    return []


def _area_card(config, states):
    ref = config.get('area') or config.get('area_id') or ''
    ids = area_entities(ref)
    sensor_classes = config.get('sensor_classes') or _AREA_SENSORS
    alert_classes = config.get('alert_classes') or _AREA_ALERTS

    readings, alerts, toggles = [], [], []
    for entity_id in ids:
        st = (states or {}).get(entity_id)
        if not st:
            continue
        attrs = st.get('attributes') or {}
        cls = str(attrs.get('device_class') or '').lower()
        domain = _domain(entity_id)
        if domain == 'sensor' and cls in sensor_classes:
            readings.append({'class': cls, 'state': st.get('state'),
                             'unit': attrs.get('unit_of_measurement'),
                             'name': attrs.get('friendly_name') or entity_id})
        elif domain == 'binary_sensor' and cls in alert_classes:
            if str(st.get('state') or '').lower() == 'on':
                alerts.append({'class': cls,
                               # The class's OWN icon — a motion badge that
                               # draws a generic warning triangle says
                               # "something is wrong" about a room somebody
                               # just walked through.
                               'icon': _icon_for(entity_id, attrs, st.get('state')),
                               'name': attrs.get('friendly_name') or entity_id})
        elif domain in _AREA_TOGGLES:
            toggles.append(_row(entity_id, states))

    # The room's own name and PHOTOGRAPH, from the area registry. HA's area
    # card leads with the picture when `display_type: picture`, and side by
    # side that is most of what makes it read as a place rather than as a row
    # of switches — a household that has bothered to upload a photo of the pool
    # house has already said which one they want.
    from services import ha_api
    name, picture, icon = config.get('name'), config.get('image'), None
    for area in ha_api.get_area_registry() or []:
        if str(area.get('area_id') or '').lower() == str(ref).lower() \
                or str(area.get('name') or '').lower() == str(ref).lower():
            name = name or area.get('name')
            picture = picture or area.get('picture')
            icon = area.get('icon')
            break
    if not name:
        for area in ha_api.get_area_map() or []:
            if str(area.get('id') or '').lower() == str(ref).lower():
                name = area.get('name')
                break
    on = [t for t in toggles if t['on']]
    return {'kind': 'area', 'name': name or str(ref) or 'Area',
            'picture': picture, 'icon': icon,
            # A picture is only the LEAD when the config asked for one. The
            # default area card is a text row, and turning every one of them
            # into a photograph would be redesigning boards nobody touched.
            'display': str(config.get('display_type') or 'compact').lower(),
            'readings': readings[:3], 'alerts': alerts[:4],
            'toggles': sorted(toggles, key=lambda t: (not t['on'], t['name']))[:6],
            'on_count': len(on),
            # An area nobody has put entities in is a REAL answer and a
            # different one from an area that does not exist.
            'empty': (not ids),
            'unknown': (not ids and not area_entities(ref))}


def convert(config, states, depth=0, hosts=None):
    """A card config -> a drawing instruction, or None.

    Recursive, because the stacks hold other cards. `depth` is a fuse: a config
    that nests itself would otherwise recurse until the stack gives out, and a
    hand-edited YAML file is exactly where that comes from.

    A real dashboard's stacks are MIXED — a custom power-flow card above a
    gauge, a column of graphs beside it — so this walks over two things it
    cannot draw itself, rather than dropping them:

      - a `custom:` card becomes a `host` node, which the browser fills by
        running the card's own JavaScript (services/ha_cards + ha_card_host.js).
        `hosts` collects them so the caller can resolve each one's file;
      - anything else becomes an `unsupported` node, which draws as a line
        naming the type.

    Both of those replaced a silent `None`, and the difference was not subtle:
    a stack of [custom card, gauge] rendered as a gauge, alone, with nothing
    anywhere saying the other card had been thrown away.
    """
    if not isinstance(config, dict) or depth > 4:
        return None
    kind = str(config.get('type') or '').strip().lower()

    if kind.startswith('custom:'):
        tag = kind[len('custom:'):].strip()
        if not tag:
            return {'kind': 'unsupported', 'type': 'custom:'}
        node = {'kind': 'host', 'tag': tag}
        if hosts is not None:
            node['host_id'] = f'h{len(hosts)}'
            hosts[node['host_id']] = {'tag': tag, 'config': config}
        return node

    if kind in STACKS:
        cards = [convert(c, states, depth + 1, hosts)
                 for c in (config.get('cards') or [])]
        cards = [c for c in cards if c]
        if not cards:
            return None
        return {'kind': 'stack', 'direction': STACKS[kind],
                'columns': int(_num(config.get('columns')) or 2),
                'square': bool(config.get('square', True)),
                'title': config.get('title'), 'cards': cards}

    if kind == 'entities':
        return _entities_card(config, states)
    if kind == 'glance':
        return _entities_card(config, states, kind='glance')
    if kind == 'tile':
        return _tile_card(config, states)
    if kind == 'gauge':
        return _gauge_card(config, states)
    if kind == 'markdown':
        return _markdown_card(config, states)
    if kind == 'picture-entity':
        return _picture_entity_card(config, states)
    if kind == 'button':
        return _button_card(config, states)
    if kind == 'sensor':
        return _sensor_card(config, states)
    if kind == 'thermostat':
        return _thermostat_card(config, states)
    if kind == 'area':
        return _area_card(config, states)
    # Named, and it keeps its place in the layout. This is the same rule the
    # top level follows — a card that vanishes silently is indistinguishable
    # from a card that failed — except that inside a stack it also matters that
    # the columns either side of it do not shuffle up to fill the hole.
    return {'kind': 'unsupported', 'type': kind or 'card',
            'name': config.get('name') or config.get('title') or ''}


def entity_ids(config, depth=0):
    """Every entity a built-in card needs, including through its stacks.

    Separate from `ha_cards.entity_ids`, which walks a config looking for
    anything entity-SHAPED. That is right for a custom card, whose config is
    somebody else's schema; here the schema is known, so the ids can be read
    from the fields that actually hold them — and a `name: sensor.foo` label
    does not become a state request.
    """
    out = []
    if not isinstance(config, dict) or depth > 4:
        return out
    kind = str(config.get('type') or '').strip().lower()
    if kind in STACKS:
        for card in (config.get('cards') or []):
            out.extend(entity_ids(card, depth + 1))
        return out
    if kind.startswith('custom:'):
        # Somebody else's schema again, so back to the shape-based walk. A
        # hosted card inside a native stack still needs its states shipped, and
        # nothing here knows which of its keys hold entity ids.
        from services import ha_cards
        return list(ha_cards.entity_ids(config))
    if kind == 'area':
        # An area card names no entities at all — it names an AREA, and the
        # entities come from Home Assistant's registry. Without this the card
        # would be handed an empty states map and draw an empty room.
        return area_entities(config.get('area') or config.get('area_id') or '')
    for key in ('entity', 'camera_image'):
        val = config.get(key)
        if isinstance(val, str) and '.' in val:
            out.append(val.strip())
    for item in (config.get('entities') or []):
        entity_id, _ = _entity_of(item)
        if entity_id:
            out.append(entity_id)
    return out
