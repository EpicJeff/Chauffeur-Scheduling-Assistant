"""Household light appearance preferences. Independent of Home Assistant."""
import re

from services import storage

KEY = 'house_twin_light_looks'


def _colour(value):
    if not isinstance(value, list) or len(value) != 3 or any(
            type(channel) is not int or not 0 <= channel <= 255 for channel in value):
        raise ValueError('A colour must contain three integers from 0 to 255.')
    return list(value)


def validate(look):
    if look is None:
        return {}
    if not isinstance(look, dict) or set(look) - {'colour', 'effects'}:
        raise ValueError('A look may contain only colour and effects.')
    result = {}
    if 'colour' in look:
        result['colour'] = _colour(look['colour'])
    if 'effects' in look:
        effects = look['effects']
        if not isinstance(effects, dict) or len(effects) > 64:
            raise ValueError('Choose at most 64 effects per entity.')
        normalized = {}
        for name, palette in effects.items():
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise ValueError('An effect name must contain 1 to 80 characters.')
            name = name.strip().lower()
            if name in normalized:
                raise ValueError('Choose different effect names.')
            if not isinstance(palette, list) or not 1 <= len(palette) <= 4:
                raise ValueError('An effect needs one to four colours.')
            normalized[name] = [_colour(colour) for colour in palette]
        if normalized:
            result['effects'] = normalized
    return result


def read():
    return storage.get_app_state(KEY) or {}


def save(body):
    if not isinstance(body, dict) or set(body) != {'entity_id', 'look'}:
        raise ValueError('Supply entity_id and look.')
    entity = body['entity_id']
    if not isinstance(entity, str) or not re.fullmatch(r'[a-z_]+\.[a-z0-9_]+', entity):
        raise ValueError('Choose a valid entity id.')
    look = validate(body['look'])
    # Hold the storage lock across the read and write: two entity edits merge.
    with storage.db_lock:
        looks = dict(read())
        if look:
            looks[entity] = look
        else:
            looks.pop(entity, None)
        if len(looks) > 256:
            raise ValueError('Choose at most 256 entities.')
        storage.set_app_state(KEY, looks)
    return look
