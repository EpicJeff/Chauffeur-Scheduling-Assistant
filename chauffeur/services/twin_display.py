"""House-only HA presentation. Registry data and HA state are never changed."""
from copy import deepcopy
import re


def _id(value, entity=False):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= 255
            and (not entity or re.fullmatch(r'[a-z_]+\.[a-z0-9_]+', value) is not None))


def validate(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {'devices', 'hidden'}:
        raise ValueError('Invalid house display settings.')
    devices, hidden = value.get('devices', {}), value.get('hidden', {})
    if not isinstance(devices, dict) or not isinstance(hidden, dict) or set(hidden) - {'devices', 'entities'}:
        raise ValueError('Invalid house display settings.')
    for did, config in devices.items():
        if (not _id(did) or not isinstance(config, dict) or set(config) - {'show_as', 'entity_ids'}
                or config.get('show_as') not in ('controls', 'entities')):
            raise ValueError('Choose Device with controls or Separate entities.')
        ids = config.get('entity_ids', [])
        if not isinstance(ids, list) or any(not _id(eid, True) for eid in ids) or len(set(ids)) != len(ids):
            raise ValueError('Invalid house entity ids.')
    for kind in ('devices', 'entities'):
        ids = hidden.get(kind, [])
        if not isinstance(ids, list) or any(not _id(i, kind == 'entities') for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('Invalid hidden house items.')
    return {'devices': deepcopy(devices), 'hidden': {
        kind: list(hidden.get(kind, [])) for kind in ('devices', 'entities')}}


def show_as(model, device_id):
    return model.get('ha_display', {}).get('devices', {}).get(device_id, {}).get('show_as', 'controls')


def hidden(model, kind, item_id):
    return item_id in model.get('ha_display', {}).get('hidden', {}).get(kind, [])


def entity_items(device, states):
    from services import twin_ha
    # Include the primary (camera/media too), but never turn a sensor into an item.
    members = twin_ha.device_accessories({**device, 'entity_id': None}, states)
    primary = device['entity_id']
    if primary.partition('.')[0] not in twin_ha._CONTROL_DOMAINS and primary.partition('.')[0] not in ('sensor', 'binary_sensor'):
        members.insert(0, {'entity_id': primary, 'name': device['name'], 'kind': device['kind']})
    return [{**member, 'device_id': 'entity:' + member['entity_id'],
             'entities': [member['entity_id']], 'area_id': device.get('area_id'),
             'parent_device_id': device['device_id'], 'accessories': []} for member in members]


def catalogue(model, source, states=None, *, include_hidden=False):
    """Project once, before auto spots and every consumer's device counts."""
    states = states or {}
    devices = []
    for device in source.get('devices', []):
        if not include_hidden and hidden(model, 'devices', device['device_id']):
            continue
        items = entity_items(device, states) if show_as(model, device['device_id']) == 'entities' else [device]
        for item in items:
            if include_hidden or not hidden(model, 'entities', item['entity_id']):
                devices.append(item)
    return {**source, 'devices': devices}


def entity_ids(device):
    """The placeable entity item ids of one HA device (its entities, minus sensors)."""
    return ['entity:' + eid for eid in device.get('entities', [])
            if eid.partition('.')[0] not in ('sensor', 'binary_sensor')]


def apply_op(model, op, catalogue, unplace):
    """set_ha_display: {device, show_as} or {item, kind: devices|entities, hidden}.

    House-only: Home Assistant is never changed. Returns the summary words."""
    display = validate(model.get('ha_display'))
    if 'show_as' in op:
        device_id = op.get('device')
        if op['show_as'] not in ('controls', 'entities') or not _id(device_id):
            raise ValueError('Choose Device with controls or Separate entities.')
        device = next((d for d in catalogue.get('devices', []) if d['device_id'] == device_id), None)
        if catalogue.get('available') and device is None:
            raise ValueError('Choose a device.')
        before = display['devices'].get(device_id, {}).get('show_as', 'controls')
        if before == op['show_as']:
            raise ValueError('Nothing changed.')
        removed = 0
        if op['show_as'] == 'controls':
            display['devices'].pop(device_id, None)
            # The device's entity items go back under it: their own placements are removed;
            # the device's own placement stays.
            for item in entity_ids(device or {'entities': []}):
                removed += bool(unplace(model, item))
        else:
            display['devices'][device_id] = {'show_as': 'entities'}
        model['ha_display'] = validate(display)
        if op['show_as'] == 'entities':
            return 'Showing the device as separate entities.'
        return 'Showing the device with its controls.' + (
            f' Removed {removed} entity placement{"s" if removed != 1 else ""}.' if removed else '')
    kind, item, hidden = op.get('kind'), op.get('item'), op.get('hidden')
    if kind not in ('devices', 'entities') or not isinstance(hidden, bool):
        raise ValueError('Choose a device or entity to hide or show.')
    if kind == 'entities' and isinstance(item, str) and item.startswith('entity:'):
        item = item[len('entity:'):]
    if not _id(item, kind == 'entities'):
        raise ValueError('Choose a device or entity to hide or show.')
    ids = display['hidden'][kind]
    if hidden == (item in ids):
        raise ValueError('Nothing changed.')
    if hidden:
        ids.append(item)
    else:
        ids.remove(item)
    model['ha_display'] = validate(display)
    return 'Hidden in the house view.' if hidden else 'Shown in the house view again.'


def accessories(model, rows):
    """Drop hidden accessories from a device's controls."""
    return [row for row in rows if not hidden(model, 'entities', row['entity_id'])]
