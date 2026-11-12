"""Household energy display mapping. No solver settings or schedule writes."""
import re
from services import storage

KEY = 'house_twin_energy'


def read():
    return storage.get_app_state(KEY) or {}


def save(mapping):
    mapping = validate(mapping)
    storage.set_app_state(KEY, mapping)


def validate(mapping):
    if not isinstance(mapping, dict):
        raise ValueError('Energy sources must be a mapping.')
    roles = ('solar_power', 'battery_power', 'battery_level', 'grid_power', 'house_power')
    def entity(value):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r'[a-z_]+\.[a-z0-9_]+', value)):
            raise ValueError('Choose a Home Assistant entity or Automatic.')
        return value
    def location(value, kind=None):
        if value is None:
            return None
        if (not isinstance(value, dict) or value.get('type') not in ('device', 'object')
                or not isinstance(value.get('id'), str) or not 1 <= len(value['id']) <= 200
                or value['type'] == 'object' and (kind not in ('grid', 'house')
                    or not isinstance(value.get('building'), str) or not 1 <= len(value['building']) <= 64)):
            raise ValueError('Choose a placed device or a meter or panel object.')
        return {key: value[key] for key in ('type', 'id', *(['building'] if value['type'] == 'object' else []))}
    result = {key: entity(mapping[key]) for key in roles if key in mapping}
    if 'home_includes_chargers' in mapping:
        if type(mapping['home_includes_chargers']) is not bool:
            raise ValueError('Choose whether home power includes the chargers.')
        result['home_includes_chargers'] = mapping['home_includes_chargers']
    if 'locations' in mapping:
        if not isinstance(mapping['locations'], dict) or any(k not in ('battery', 'grid', 'house') for k in mapping['locations']):
            raise ValueError('Choose an equipment role.')
        result['locations'] = {k: location(v, k) for k, v in mapping['locations'].items()}
    for key, values in (('battery_positive', ('charge', 'discharge')), ('grid_positive', ('import', 'export'))):
        if key in mapping:
            if mapping[key] not in values:
                raise ValueError('Choose the positive power direction.')
            result[key] = mapping[key]
    if 'panels' in mapping:
        panels = mapping['panels']
        if (not isinstance(panels, dict) or type(panels.get('visible', True)) is not bool
                or panels.get('plane') is not None and (not isinstance(panels['plane'], str) or len(panels['plane']) > 200)):
            raise ValueError('Choose panel visibility and a roof plane.')
        result['panels'] = {'visible': panels.get('visible', True), 'plane': panels.get('plane')}
    if 'cars' in mapping:
        cars = mapping['cars']
        if not isinstance(cars, list) or len(cars) > 12:
            raise ValueError('Choose up to twelve cars.')
        result['cars'] = []
        seen = set()
        for car in cars:
            if (not isinstance(car, dict) or not isinstance(car.get('id'), str) or not 1 <= len(car['id']) <= 100
                    or car['id'] in seen or not isinstance(car.get('name'), str) or not 1 <= len(car['name']) <= 100):
                raise ValueError('Each car needs a unique id and a name.')
            seen.add(car['id'])
            result['cars'].append({key: car[key] for key in ('id', 'name')})
            if 'anchor' in car:
                result['cars'][-1]['anchor'] = location(car['anchor'])
            result['cars'][-1].update({key: entity(car.get(key)) for key in ('charge_power', 'battery_level', 'location')})
    return result


def household_cars():
    # Share cars.py's telemetry bindings and presence rule (no tracker = home).
    return [{'id': str(c.get('id') or c.get('doc_id') or getattr(c, 'doc_id', '')), 'name': c.get('name') or 'Car',
             'battery_level': c.get('ha_battery_entity'),
             'location': c.get('ha_device_tracker')}
            for c in storage.get_all_cars() or [] if not c.get('is_disabled')]


def entities():
    mapping = read()
    ids = {mapping.get(k) for k in ('solar_power', 'battery_power', 'battery_level', 'grid_power', 'house_power')}
    for car in mapping.get('cars', household_cars()):
        ids.update(car.get(k) for k in ('charge_power', 'battery_level', 'location'))
    return ids - {None, ''}
