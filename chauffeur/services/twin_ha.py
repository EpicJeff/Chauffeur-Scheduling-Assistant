"""Home Assistant's areas and devices in the connected house model.

Placement helpers only describe choices; model operations own all writes.
"""
from collections import Counter
from copy import deepcopy
import math
import re
import logging
import threading
import time

from services import control_rules, ha_api, house, twin_model


# What a device IS, most telling first: a lock that also reports its battery
# is a lock, and a light that also reports its energy is a light.
_KINDS = ('lock', 'garage', 'camera', 'climate', 'light', 'fan', 'outlet', 'switch',
          'media', 'blinds', 'water_heater', 'valve', 'number', 'select', 'humidifier', 'sensor', 'other')
_PLURALS = {'light': 'lights', 'switch': 'switches', 'fan': 'fans',
            'camera': 'cameras', 'sensor': 'sensors', 'outlet': 'outlets'}


_CONTROL_DOMAINS = frozenset(('light', 'switch', 'input_boolean', 'fan', 'climate',
    'water_heater', 'cover', 'valve', 'number', 'input_number', 'select', 'input_select',
    'button', 'siren', 'humidifier', 'lock'))


def device_accessories(device, states):
    """Every controllable sibling of the primary; sensors remain device facts."""
    out = []
    for eid in device['entities']:
        domain = eid.partition('.')[0]
        if eid == device['entity_id'] or domain not in _CONTROL_DOMAINS:
            continue
        attrs = (states.get(eid) or {}).get('attributes') or {}
        name = attrs.get('friendly_name') or eid.partition('.')[2].replace('_', ' ')
        name = re.sub(r'^' + re.escape(device['name']) + r'(?:[\s:–—-]+|$)', '', name,
                      flags=re.IGNORECASE).strip()
        out.append({'entity_id': eid, 'name': name or domain.capitalize(),
                    'kind': _entity_kind({'entity_id': eid, 'domain': domain, '_state': states.get(eid)})})
    return out


def _entity_kind(entity, registry=None):
    domain = entity['domain']
    if domain == 'switch':
        # A smart plug is an outlet: its state says so, or the registry does.
        row = registry or {}
        attrs = (entity.get('_state') or {}).get('attributes') or {}
        if 'outlet' in (attrs.get('device_class'), row.get('device_class'), row.get('original_device_class')):
            return 'outlet'
    if domain == 'cover':
        attrs = (entity.get('_state') or {}).get('attributes')
        return 'garage' if control_rules.kind_of(entity['entity_id'], attrs) == 'garage' else 'blinds'
    return {'light': 'light', 'switch': 'switch', 'input_boolean': 'switch',
            'fan': 'fan', 'camera': 'camera', 'binary_sensor': 'sensor',
            'sensor': 'sensor', 'lock': 'lock', 'climate': 'climate',
            'media_player': 'media', 'water_heater': 'water_heater', 'valve': 'valve',
            'number': 'number', 'input_number': 'number', 'select': 'select',
            'input_select': 'select', 'humidifier': 'humidifier'}.get(domain, 'other')


def catalogue() -> dict:
    if ha_api.mode() == 'unconfigured':
        return {'available': False, 'areas': [], 'floors': [], 'devices': []}
    area_rows = ha_api.get_area_registry()
    if not area_rows:
        return {'available': False, 'areas': [], 'floors': [], 'devices': []}
    floors = ha_api.get_floor_registry()
    floor_by_id = {f['floor_id']: f for f in floors}
    areas = []
    for row in area_rows:
        floor = floor_by_id.get(row.get('floor_id'), {})
        areas.append({'area_id': row['area_id'], 'name': row['name'],
                      'floor_id': row.get('floor_id'), 'floor_name': floor.get('name'),
                      'floor_level': floor.get('level')})
    area_by_name = {a['name']: a['area_id'] for a in areas}
    registry = ha_api.get_entity_registry()
    order = {e['entity_id']: i for i, e in enumerate(registry)}
    rows = {e['entity_id']: e for e in registry}
    kind = lambda e: _entity_kind(e, rows.get(e['entity_id']))
    grouped = {}
    for entity in house._catalogue():
        device_id = entity.get('_device_id') or 'entity:' + entity['entity_id']
        grouped.setdefault(device_id, []).append(entity)
    devices = []
    for device_id, members in grouped.items():
        members.sort(key=lambda e: order.get(e['entity_id'], len(order)))
        primary = min(members, key=lambda e: _KINDS.index(kind(e)))
        devices.append({'device_id': device_id,
                        'name': primary.get('_device_name') or primary['name'],
                        'area_id': area_by_name.get(primary.get('area')),
                        'kind': kind(primary), 'entity_id': primary['entity_id'],
                        'entities': [e['entity_id'] for e in members]})
    return {'available': bool(areas), 'areas': areas, 'floors': floors, 'devices': devices}


def resolve_area(value, areas):
    if not value:
        return None
    for area in areas:
        if value == area['area_id']:
            return area['area_id']
    for area in areas:
        if str(value).casefold() == (area.get('name') or '').casefold():
            return area['area_id']
    return None


_catalogue_failed_until = 0
_catalogue_lock = threading.Lock()


def safe_catalogue():
    """Share failed reads across editors and live views while HA recovers."""
    global _catalogue_failed_until
    unavailable = {'available': False, 'areas': [], 'floors': [], 'devices': []}
    configured = ha_api.mode() != 'unconfigured'
    with _catalogue_lock:
        if configured and time.monotonic() < _catalogue_failed_until:
            return unavailable
        try:
            result = catalogue()
        except Exception as error:
            logging.getLogger(__name__).warning('House HA catalogue unavailable: %s', error)
            result = unavailable
        if configured and not result['available']:
            _catalogue_failed_until = time.monotonic() + 30
        return result


def _rooms(model):
    for building in model.get('buildings', []):
        for room in building.get('rooms', []):
            yield building, room
    # Yard regions share room linking and auto-placement, without a building's
    # coordinate transform or floor. Keep the actual room objects for callers.
    yard = {'id': None, 'levels': []}
    for room in model.get('site', {}).get('yard_rooms', []):
        yield yard, room


def _name(value):
    return ''.join(c for c in (value or '').casefold() if c.isalnum())


def suggest(model, areas) -> dict:
    linked = {resolve_area(r.get('ha_area'), areas) for _, r in _rooms(model) if r.get('ha_area')}
    candidates = []
    for building, room in _rooms(model):
        name = _name(room.get('name'))
        if room.get('ha_area') or not name:
            continue
        index = next((i for i, level in enumerate(building.get('levels', []))
                      if level['id'] == room.get('level')), None)
        for area in areas:
            other = _name(area.get('name'))
            if area['area_id'] in linked or not other:
                continue
            if name == other or name in other or other in name:
                candidates.append((name != other, index != area.get('floor_level'),
                                   room['id'], area['area_id']))
    # Exact matches across all rooms precede substring matches; stable order breaks remaining ties.
    candidates.sort(key=lambda c: c[:2])
    out = {}
    for _, _, room_id, area_id in candidates:
        if room_id not in out and area_id not in linked:
            out[room_id] = area_id
            linked.add(area_id)
    return out


def rooms_for_area(model, area_id, areas=None) -> list:
    if not area_id:
        return []
    return sorted((r for _, r in _rooms(model)
                   if r.get('ha_area') == area_id or areas is not None
                   and resolve_area(r.get('ha_area'), areas) == area_id),
                  key=lambda r: twin_model._area(r.get('polygon', [])), reverse=True)


def placements(model) -> dict:
    out = {}
    for building in model.get('buildings', []):
        for anchor in building.get('anchors', []):
            if anchor.get('device'):
                out[anchor['device']] = {'kind': 'anchor', 'building': building['id'],
                                         'anchor': anchor['id'], 'offset': anchor.get('offset', 0)}
        for device in building.get('devices', []):
            if device.get('device'):
                out[device['device']] = {'kind': 'host', 'building': building['id'],
                                         'host': deepcopy(device.get('host', {})),
                                         'offset': device.get('offset', 0)}
    for device in model.get('site', {}).get('devices', []):
        if device.get('device') and device.get('host', {}).get('yard_room'):
            out[device['device']] = {'kind': 'host', 'building': None, 'yard': True,
                                    'host': deepcopy(device['host']),
                                    'offset': device.get('offset', 0)}
    return out


def yard_spot(model, placement):
    """A floor-like yard host in lot feet; z is height above local ground."""
    from services import twin_site_shapes
    host = placement.get('host', {})
    room = next((r for r in model.get('site', {}).get('yard_rooms', [])
                 if r['id'] == host.get('yard_room')), None)
    if room is None:
        return None
    try:
        at = twin_site_shapes.yard_device_point(model['site'], placement)
    except (ValueError, KeyError, TypeError):
        return None
    return {'building': None, 'level': None, 'room': room['id'], 'yard': True,
            'outdoor': True, 'at': at, 'z': placement.get('offset', 0),
            'location_valid': True}


def _inside(point, polygon):
    x, y = point
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def _grid(polygon, count):
    if len(polygon) < 3 or twin_model._area(polygon) <= 0:
        return []
    centre = twin_model._centroid(polygon)
    x0, y0, x1, y1 = twin_model._bounds(polygon)
    points = [centre] if _inside(centre, polygon) else []
    step = 2.0
    while len(points) < count:
        candidates = []
        for ix in range(math.floor((x0 - centre[0]) / step), math.ceil((x1 - centre[0]) / step) + 1):
            for iy in range(math.floor((y0 - centre[1]) / step), math.ceil((y1 - centre[1]) / step) + 1):
                point = [centre[0] + ix * step, centre[1] + iy * step]
                if _inside(point, polygon) and point not in points:
                    candidates.append(point)
        candidates.sort(key=lambda p: (p[0] - centre[0]) ** 2 + (p[1] - centre[1]) ** 2)
        points.extend(candidates[:count - len(points)])
        # A small room may need a denser grid to give every device its own spot.
        step /= 2
    return points[:count]


def auto_spots(model, catalogue) -> dict:
    placed = placements(model)
    grouped = {}
    for device in catalogue.get('devices', []):
        if device['device_id'] not in placed and device.get('area_id'):
            grouped.setdefault(device['area_id'], []).append(device)
    out = {}
    for area_id, devices in grouped.items():
        rooms = rooms_for_area(model, area_id, catalogue.get('areas'))
        if not rooms:
            continue
        room = rooms[0]
        building = next(b for b, r in _rooms(model) if r is room)
        level = next((l for l in building.get('levels', []) if l['id'] == room.get('level')), {})
        for device, point in zip(devices, _grid(room.get('polygon', []), len(devices))):
            if building['id'] is None:
                out[device['device_id']] = {'building': None, 'level': None,
                                            'room': room['id'], 'yard': True,
                                            'outdoor': True, 'at': point, 'z': 0}
                continue
            height = level.get('ceiling', 9) if device['kind'] in ('light', 'fan') else 4 + room.get('floor_offset_ft', 0)
            out[device['device_id']] = {'building': building['id'], 'level': room.get('level'),
                                        'room': room['id'], 'at': point,
                                        'z': level.get('elevation', 0) + height}
    return out


def _room_walls(building, room):
    joints = room.get('joints', [])
    edges = {frozenset((a, b)) for a, b in zip(joints, joints[1:] + joints[:1])}
    return [w for w in building.get('walls', []) if frozenset(w.get('joints', [])) in edges]


def count_notes(model, room_id, catalogue) -> list:
    for building, room in _rooms(model):
        if room['id'] != room_id or not room.get('ha_area'):
            continue
        walls = {w['id'] for w in _room_walls(building, room)}
        anchors = Counter()
        for anchor in building.get('anchors', []):
            host = anchor.get('host', {})
            if host.get('floor') == room_id or host.get('ceiling') == room_id or host.get('wall') in walls:
                anchors[anchor.get('kind')] += 1
        devices = Counter(d['kind'] for d in catalogue.get('devices', [])
                          if d.get('area_id') == room['ha_area'])
        return [f'The plan shows {n} {plural}; Home Assistant has {devices[kind]} in this area.'
                for kind, plural in _PLURALS.items()
                if (n := anchors[kind]) and devices[kind] and n != devices[kind]]
    return []


def obvious(model, room_id, catalogue) -> list:
    placed = placements(model)
    for building, room in _rooms(model):
        if room['id'] != room_id or not room.get('ha_area'):
            continue
        walls = _room_walls(building, room)
        openings = [o for w in walls for o in building.get('openings', [])
                    if o.get('wall') == w['id'] and o.get('state') != 'ghost']
        exterior = {w['id'] for w in walls if w.get('exterior')}
        doors = [o for o in openings if o.get('kind') == 'door' and o['wall'] in exterior]
        occupied = {p.get('host', {}).get('opening') for p in placed.values() if p['building'] == building['id']}
        occupied.update(a.get('host', {}).get('opening') for a in building.get('anchors', []) if a.get('device'))
        garages = [o for o in openings if o.get('kind') == 'garage' and o['id'] not in occupied]
        locks = doors if len(doors) == 1 and doors[0]['id'] not in occupied else []
        out = []
        for device in catalogue.get('devices', []):
            if device['device_id'] in placed or device.get('area_id') != room['ha_area']:
                continue
            targets = garages if device['kind'] == 'garage' else locks if device['kind'] == 'lock' else []
            if targets:
                opening = targets.pop(0)
                out.append({'device': device['device_id'], 'building': building['id'],
                            'host': {'opening': opening['id'], 'side': 'in'}})
        return out
    return []


def gone_rooms(model, areas) -> list:
    if not areas:
        return []
    return [room['id'] for _, room in _rooms(model)
            if room.get('ha_area') and resolve_area(room['ha_area'], areas) is None]
