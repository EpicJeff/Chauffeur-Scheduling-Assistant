"""Twin display preferences, isolated from schedule settings and model rounds."""
import re

from services import storage

KEY = 'house_twin_glance'
ICONS = frozenset('solar house battery battery-charging car ev-plug grid plug thermometer humidity water gas fan cooling bulb lock door window garage camera alarm wifi server trash washer dryer dishwasher oven tv speaker sprinkler pool leaf cloud gauge clock person pet bell power'.split())


def starting_icon(entity, row=None):
    """Only for existing entity lists, or the editor's initial suggestion."""
    classes = {'battery': 'battery', 'humidity': 'humidity', 'temperature': 'thermometer',
               'power': 'power', 'energy': 'power', 'gas': 'gas', 'water': 'water', 'moisture': 'water',
               'door': 'door', 'opening': 'door', 'window': 'window', 'garage_door': 'garage', 'lock': 'lock',
               'motion': 'person', 'occupancy': 'person', 'presence': 'person', 'smoke': 'alarm', 'safety': 'alarm'}
    kinds = {'weather': 'cloud', 'climate': 'thermometer', 'water_heater': 'thermometer', 'humidifier': 'humidity',
             'light': 'bulb', 'switch': 'plug', 'outlet': 'plug', 'fan': 'fan', 'lock': 'lock', 'cover': 'window',
             'camera': 'camera', 'alarm_control_panel': 'alarm', 'alarm': 'alarm', 'media_player': 'speaker',
             'person': 'person', 'device_tracker': 'person'}
    row = row or {}
    return classes.get((row.get('attributes') or {}).get('device_class')) or kinds.get(row.get('kind')) or kinds.get(entity.split('.')[0], 'gauge')


def migrate(entities, states=None):
    if entities is None:
        return None
    if states is None and any(isinstance(tile, str) for tile in entities):
        from services import ha_api
        try:
            states = {row['entity_id']: row for row in ha_api.get_states()}
        except Exception:
            states = {}
    return [{'entity': tile, 'icon': starting_icon(tile, (states or {}).get(tile)), 'label': ''}
            if isinstance(tile, str) else dict(tile) for tile in entities]


def validate(tiles):
    if tiles is None:
        return
    if not isinstance(tiles, list) or len(tiles) > 12:
        raise ValueError('Choose up to twelve tiles.')
    seen = set()
    for tile in tiles:
        if not isinstance(tile, dict) or set(tile) - {'entity', 'icon', 'label'}:
            raise ValueError('Each tile needs an entity and a known icon.')
        entity = tile.get('entity')
        if not isinstance(entity, str) or not re.fullmatch(r'[a-z_]+\.[a-z0-9_]+', entity) or entity in seen:
            raise ValueError('Choose different, valid entity ids.')
        if not isinstance(tile.get('icon'), str) or tile['icon'] not in ICONS:
            raise ValueError('Choose an icon from the icon grid.')
        if not isinstance(tile.get('label', ''), str) or len(tile.get('label', '')) > 32 or any(ord(c) < 32 for c in tile.get('label', '')):
            raise ValueError('A tile label must be at most 32 characters on one line.')
        seen.add(entity)


def read(panel=None):
    household = storage.get_app_state(KEY) or {}
    override = (panel or {}).get(KEY) or {}
    # Persist the conversion once, preserving idle preferences and explicit empties.
    for fields, panel_id in ((household, None), (override, (panel or {}).get('device_id'))):
        old = fields.get('entities')
        if old is not None and any(isinstance(tile, str) for tile in old):
            fields['entities'] = migrate(old)
            if panel_id:
                storage.set_device_twin_glance(panel_id, fields)
            else:
                storage.set_app_state(KEY, fields)
    chosen = household.get('entities') or []
    weather_entity = (storage.get_settings() or {}).get('weather_entity') or None
    if not weather_entity:
        from services import ha_api
        try:
            weather = ha_api.get_entities('weather')
            weather_entity = weather[0]['entity_id'] if weather else None
        except Exception:
            pass
    return {'household_entities': chosen,
            'panel_entities': override.get('entities'),
            'entities': override.get('entities') if override.get('entities') is not None else chosen,
            'weather_entity': weather_entity,
            'idle_enabled': override.get('idle_enabled', household.get('panel_idle_enabled', True)) if panel
            else household.get('idle_enabled', False),
            'panel_idle_enabled': household.get('panel_idle_enabled', True),
            'panel_id': panel.get('device_id') if panel else None}


def entities():
    """Server-owned stream scope, including selected sensors without a room."""
    lists = [storage.get_app_state(KEY) or {}]
    lists.extend(d.get(KEY) or {} for d in storage.get_trusted_devices())
    return {tile if isinstance(tile, str) else tile['entity']
            for fields in lists for tile in fields.get('entities') or []}


def save(entities, idle_enabled, panel_id=None, panel_idle_enabled=True):
    entities = migrate(entities)
    validate(entities)
    if not panel_id and entities is None:
        entities = []
    fields = {'entities': entities, 'idle_enabled': idle_enabled}
    if panel_id:
        return storage.set_device_twin_glance(panel_id, fields)
    fields['panel_idle_enabled'] = panel_idle_enabled
    storage.set_app_state(KEY, fields)
    return fields
