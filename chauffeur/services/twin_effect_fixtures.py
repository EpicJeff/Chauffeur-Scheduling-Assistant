"""Switch/sensor driven effects using the light fixture placement contract."""
from copy import deepcopy
import re
from uuid import UUID, uuid4

from services import twin_fixtures as fixtures

MAX_FIXTURES = 64
OPS = ('add_effect_fixture', 'update_effect_fixture', 'delete_effect_fixture')
TYPES = {
    'waterfall': {'label': 'Waterfall', 'shapes': ('line',), 'size': (.3, 1.5)},
    'fountain': {'label': 'Fountain', 'shapes': ('point',), 'size': (1, 6)},
    'bubbler': {'label': 'Bubbler', 'shapes': ('point',), 'size': (.3, 1.5)},
    'fire': {'label': 'Fire', 'shapes': ('point', 'line'), 'size': (.5, 2)},
}
_COMMON = {'id', 'type', 'shape', 'ref', 'building', 'level', 'strength',
           'entity', 'sensor', 'sensor_min', 'sensor_max', 'size_min', 'size_max', 'name'}
_PLACEMENT = {'ref', 'building', 'level', 'at', 'path', 'snap', 'detached', 'facing'}


def placement(fixture):
    """Adapt only the effect id to the shared light placement format."""
    value = {k: deepcopy(v) for k, v in fixture.items() if k in _PLACEMENT}
    value.update(id='fixture:' + fixture['id'][7:], shape=fixture['shape'])
    return value


def set_placement(fixture, value):
    """Copy canonical/resolved placement back, preserving effect properties."""
    for key in _PLACEMENT:
        fixture.pop(key, None)
        if key in value:
            fixture[key] = deepcopy(value[key])


def _entity(value, domains, label):
    if not isinstance(value, str) or not re.fullmatch(r'(' + '|'.join(domains) + r')\.[a-z0-9_]+', value):
        raise ValueError('Choose a ' + label + ' entity (' + ', '.join(domains) + ').')
    return value


def validate(fixture):
    """Return canonical effect data; placement validation stays with lights."""
    if not isinstance(fixture, dict) or not isinstance(fixture.get('type'), str) or fixture['type'] not in TYPES:
        raise ValueError('Choose waterfall, fountain, bubbler or fire.')
    f = deepcopy(fixture)
    f.pop('orphaned', None)
    f.pop('orphan_reason', None)
    kind, shape = f['type'], f.get('shape')
    if shape not in TYPES[kind]['shapes']:
        raise ValueError('Choose ' + ' or '.join(TYPES[kind]['shapes']) + ' for ' + kind + '.')
    allowed = _COMMON | ({'path', 'snap', 'detached', 'facing'} if shape == 'line' else {'at'})
    if kind == 'waterfall':
        allowed.add('drop_ft')
    if set(f) - allowed:
        raise ValueError('Choose supported effect fixture properties.')
    fid = f.get('id')
    try:
        if not isinstance(fid, str) or not fid.startswith('effect:') or str(UUID(fid[7:])) != fid[7:]:
            raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError('An effect fixture needs a canonical effect:<uuid> id.') from None
    set_placement(f, fixtures.validate(placement(f)))
    for key, domains, label in (('entity', ('switch', 'light', 'input_boolean', 'fan'), 'switch'),
                                ('sensor', ('sensor', 'number', 'input_number'), 'sensor')):
        if f.get(key) is None:
            f.pop(key, None)
        else:
            f[key] = _entity(f[key], domains, label)
    if 'sensor' in f:
        for key in ('sensor_min', 'sensor_max'):
            f[key] = fixtures._number(f.get(key), key.replace('_', ' '), -1e308, 1e308)
        if f['sensor_min'] == f['sensor_max']:
            raise ValueError('Sensor min and max must differ.')
    elif 'sensor_min' in f or 'sensor_max' in f:
        raise ValueError('Link a sensor before setting its min and max.')
    for key, default in zip(('size_min', 'size_max'), TYPES[kind]['size']):
        f[key] = fixtures._number(f.get(key, default), key.replace('_', ' '), 0, 30)
    f['strength'] = fixtures._number(f.get('strength', 1), 'effect strength', 0, 1)
    if 'name' in f:
        if not isinstance(f['name'], str) or not 1 <= len(f['name'].strip()) <= 80:
            raise ValueError('Choose an effect name from 1 to 80 characters.')
        f['name'] = f['name'].strip()
    if 'drop_ft' in f:
        f['drop_ft'] = fixtures._number(f['drop_ft'], 'waterfall drop in feet', .1, 40)
    return f


def normalize(model, notes):
    """Keep context orphans, drop malformed records, leave untouched houses alone."""
    if 'effect_fixtures' not in model:
        return
    raw, kept, ids = model['effect_fixtures'], [], set()
    if not isinstance(raw, list):
        notes.append('Dropped invalid effect_fixtures; expected a fixture list.')
        raw = []
    for value in raw:
        try:
            f = validate(value)
            if f['id'] in ids or len(kept) >= MAX_FIXTURES:
                raise ValueError('Duplicate effect fixture id or more than 64 fixtures.')
        except ValueError as exc:
            notes.append(f'Dropped an effect fixture: {exc}')
            continue
        p = placement(f)
        fixtures._resolve(model, p)
        set_placement(f, p)
        if reason := fixtures._context_error(model, p):
            f.update(orphaned=True, orphan_reason=reason)
        kept.append(f)
        ids.add(f['id'])
    model['effect_fixtures'] = kept


def apply_op(model, op):
    """Apply one editor operation; its store wrapper owns the undo round."""
    kind = op.get('op')
    if kind not in OPS:
        raise ValueError('Choose a supported effect fixture operation.')
    rows = model.setdefault('effect_fixtures', [])
    if kind == 'add_effect_fixture':
        if len(rows) >= MAX_FIXTURES:
            raise ValueError('A house can have at most 64 effect fixtures.')
        value = deepcopy(op.get('fixture'))
        if isinstance(value, dict):
            value.setdefault('id', 'effect:' + str(uuid4()))
        value = validate(value)
        if any(f['id'] == value['id'] for f in rows):
            raise ValueError('That effect fixture id already exists.')
    else:
        previous = next((f for f in rows if f['id'] == op.get('id')), None)
        if previous is None:
            raise ValueError('That effect fixture is missing.')
        if kind == 'delete_effect_fixture':
            rows.remove(previous)
            return 'Deleted the effect fixture.'
        change = op.get('change')
        if not isinstance(change, dict) or 'id' in change:
            raise ValueError('Choose effect fixture changes; the id stays fixed.')
        baseline = previous
        if 'shape' in change and change['shape'] != previous['shape']:
            baseline = {k: v for k, v in previous.items() if k not in {'at', 'path', 'snap', 'detached', 'facing'}}
        if 'type' in change and change['type'] != 'waterfall':
            baseline = {k: v for k, v in baseline.items() if k != 'drop_ft'}
        candidate = {**baseline, **change}
        for key in ('entity', 'sensor', 'drop_ft', 'name'):
            if key in change and change[key] is None:
                candidate.pop(key, None)
                if key == 'sensor':
                    candidate.pop('sensor_min', None)
                    candidate.pop('sensor_max', None)
        value = validate(candidate)
    p = placement(value)
    fixtures._in_lot(model, p)
    fixtures._resolve(model, p)
    fixtures._in_lot(model, p)
    set_placement(value, p)
    if kind == 'add_effect_fixture':
        rows.append(value)
    else:
        rows[rows.index(previous)] = value
    return 'Added the effect fixture.' if kind == 'add_effect_fixture' else 'Changed the effect fixture.'


def live_layout(model):
    """Same reference-space geometry as the light fixture live envelope."""
    return {'effect_fixtures': deepcopy(model.get('effect_fixtures', []))}
