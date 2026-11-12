"""Household energy display mapping. No solver settings or schedule writes."""
import re
from copy import deepcopy
from services import storage

KEY = 'house_twin_energy'


def read():
    return migrate(storage.get_app_state(KEY) or {})


def migrate(mapping):
    """Read old per-car chargers without writing during a GET."""
    mapping = deepcopy(mapping)
    if 'chargers' not in mapping and any(c.get('charge_power') or c.get('anchor') for c in mapping.get('cars', []) if isinstance(c, dict)):
        mapping['chargers'] = []
        for car in mapping.get('cars', []):
            if car.get('charge_power') or car.get('anchor'):
                mapping['chargers'].append(dict(id='charger-' + car['id'], name=car['name'][:92] + ' charger',
                    power=car.get('charge_power'), anchor=car.get('anchor'), car=car['id']))
                car.update(charge_power=None, anchor=None)
    return mapping


def save(mapping):
    mapping = validate(mapping)
    storage.set_app_state(KEY, mapping)


def validate(mapping):
    if not isinstance(mapping, dict):
        raise ValueError('Energy sources must be a mapping.')
    # Validate first, then migrate, so malformed legacy input is a 422 too.
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
                or value['type'] == 'object' and (kind not in ('grid', 'house', 'charger')
                    or not isinstance(value.get('building'), str) or not 1 <= len(value['building']) <= 64)):
            raise ValueError('Choose a placed device or an equipment object.')
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
                result['cars'][-1]['anchor'] = location(car['anchor'], 'charger')
            result['cars'][-1].update({key: entity(car.get(key)) for key in ('charge_power', 'battery_level', 'location')})
            for key in ('charging', 'fuel_level', 'range_entity'):
                if key in car:
                    result['cars'][-1][key] = entity(car[key])
            if 'parking' in car:
                parking = car['parking']
                if parking is not None and (not isinstance(parking, str) or not 1 <= len(parking) <= 200):
                    raise ValueError('Choose a parking spot.')
                result['cars'][-1]['parking'] = parking
    if 'chargers' in mapping:
        chargers = mapping['chargers']
        if not isinstance(chargers, list) or len(chargers) > 8:
            raise ValueError('Choose up to eight chargers.')
        result['chargers'] = []
        seen = set()
        for charger in chargers:
            if (not isinstance(charger, dict) or not isinstance(charger.get('id'), str) or not 1 <= len(charger['id']) <= 200
                    or charger['id'] in seen or not isinstance(charger.get('name'), str) or not 1 <= len(charger['name']) <= 100
                    or charger.get('car') is not None and (not isinstance(charger['car'], str) or not 1 <= len(charger['car']) <= 100)):
                raise ValueError('Each charger needs a unique id and a name, and an optional car id.')
            seen.add(charger['id'])
            row = {key: charger[key] for key in ('id', 'name')}
            for key in ('power', 'anchor', 'car'):
                if key in charger:
                    row[key] = entity(charger[key]) if key == 'power' else location(charger[key], 'charger') if key == 'anchor' else charger[key]
            result['chargers'].append(row)
    result = migrate(result)
    if len(result.get('chargers', [])) > 8:
        raise ValueError('Choose up to eight chargers.')
    return result


def household_cars():
    # Share cars.py's telemetry bindings and presence rule (no tracker = home).
    from services.cars import warn_thresholds
    battery_warning, fuel_warning = warn_thresholds(storage.get_settings())
    return [{'id': str(c.get('id') or c.get('doc_id') or getattr(c, 'doc_id', '')), 'name': c.get('name') or 'Car',
             'color': c.get('color_code') or '#64748b', 'battery_warn_pct': battery_warning, 'fuel_warn_pct': fuel_warning,
             'range_entity': c.get('ha_range_entity'),
             'twin_model': c.get('twin_model'),
             'battery_level': c.get('ha_battery_entity'),
             'fuel_level': c.get('ha_fuel_entity'),
             'location': c.get('ha_device_tracker')}
            for c in storage.get_all_cars() or [] if not c.get('is_disabled')]


def entities():
    mapping = read()
    ids = {mapping.get(k) for k in ('solar_power', 'battery_power', 'battery_level', 'grid_power', 'house_power')}
    for car in mapping.get('cars', household_cars()):
        ids.update(car.get(k) for k in ('charge_power', 'battery_level', 'fuel_level', 'location', 'charging', 'range_entity'))
    ids.update(c.get('power') for c in mapping.get('chargers', []))
    # Saved display rows still inherit the household's fuel and range bindings.
    ids.update(c.get(k) for c in household_cars() for k in ('fuel_level', 'range_entity'))
    return ids - {None, ''}
