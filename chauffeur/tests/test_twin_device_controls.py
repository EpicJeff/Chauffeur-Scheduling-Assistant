"""Multi-entity controllers keep one marker and independent, typed controls."""
import sys
import traceback

from test_twin_ha_routes import Ctx, LIVE, LINK, _state, seed, ts, cr, marker_for
from services import twin_ha


def controller(c, members, name='Pool controller'):
    c.ha.devices[0]['name'] = name
    c.ha.entities.pop('light.kitchen_ceiling')
    c.ha.states.pop('light.kitchen_ceiling')
    for eid, label in members:
        c.ha.entities[eid] = 'dev-k-light'
        c.ha.states[eid] = _state(eid, friendly_name=f'{name} {label}')


def test_pool_yard_room_one_device_and_marker_with_all_controls():
    seed()
    def yard(model):
        model['site']['yard_rooms'] = [{'id': 'pool', 'name': 'Pool deck', 'ha_area': 'kitchen',
            'polygon': [[0, 0], [20, 0], [20, 20], [0, 20]]}]
        model['buildings'][0]['rooms'][0]['ha_area'] = None
        return model
    ts.update_model(yard)
    members = [('light.pool', 'Light'), ('switch.pump', 'Pump'), ('switch.waterfall', 'Waterfall'),
               ('switch.spa_jets', 'Spa jets'), ('water_heater.pool', 'Heater'), ('sensor.pool', 'Temperature')]
    with Ctx() as c:
        controller(c, members)
        device = next(d for d in c.client.get(LINK, headers=c.mum).json()['devices']
                      if d['device_id'] == 'dev-k-light')
        assert device['entity_id'] == 'light.pool' and device['kind'] == 'light'
        body = c.client.get(LIVE, headers=c.mum).json()
        rows = [d for d in body['devices'] if d['device_id'] == 'dev-k-light']
        assert len(rows) == 1
        marker = marker_for(body, 'dev-k-light')
        assert marker['yard'] and marker['room'] == 'pool' and marker['name'] == 'Pool controller'
        assert marker['accessories'] == rows[0]['accessories']
        accessories = {a['entity_id']: a for a in marker['accessories']}
        # The brief's enumerated fixture has FOUR secondaries, not five.
        assert set(accessories) == {eid for eid, _ in members[1:-1]}
        assert all(a['offered'] is True for a in accessories.values())
        assert accessories['water_heater.pool']['kind'] == 'water_heater'
        assert accessories['switch.spa_jets']['name'] == 'Spa jets'
        # A fifth secondary remains reachable through the disclosure in the UI.
        c.ha.entities['number.pool_speed'] = 'dev-k-light'
        c.ha.states['number.pool_speed'] = _state('number.pool_speed', '50')
        body = c.client.get(LIVE, headers=c.mum).json()
        assert len(marker_for(body, 'dev-k-light')['accessories']) == 5


def test_secondary_lock_obeys_its_own_grid_and_service_gate():
    seed()
    with Ctx() as c:
        # Locks outrank lights in the existing primary ordering. A second lock
        # on this controller is an accessory and must keep the lock rule too.
        controller(c, [('lock.main', 'Main lock'), ('lock.spa', 'Spa lock'), ('light.pool', 'Light')])
        grid = cr.default_rules({})
        grid['places']['panel'].update(locks='no', lights='yes', other='yes')
        c.extra['ha_control'] = grid
        device = next(d for d in c.client.get(LIVE, headers=c.panel).json()['devices']
                      if d['device_id'] == 'dev-k-light')
        assert device['entity_id'] == 'lock.main' and device['offered'] is False
        accessories = {a['entity_id']: a for a in device['accessories']}
        assert accessories['lock.spa']['kind'] == 'lock' and accessories['lock.spa']['offered'] is False
        assert accessories['light.pool']['offered'] is True
        response = c.client.post('/api/ha/card/service', headers=c.panel,
            json={'domain': 'lock', 'service': 'unlock', 'data': {'entity_id': 'lock.spa'}})
        assert response.status_code == 403 and not c.ha.calls_on('lock.spa')
        # 'Ask who' still offers the standard identification path.
        grid['places']['panel']['locks'] = 'ask'
        asked = next(d for d in c.client.get(LIVE, headers=c.panel).json()['devices']
                     if d['device_id'] == 'dev-k-light')
        assert next(a for a in asked['accessories'] if a['entity_id'] == 'lock.spa')['offered'] is True


def test_accessory_domains_names_and_primary_exclusion():
    domains = ['light', 'switch', 'input_boolean', 'fan', 'climate', 'water_heater', 'cover',
               'valve', 'number', 'input_number', 'select', 'input_select', 'button', 'siren', 'humidifier', 'lock']
    ids = [f'{domain}.pool' for domain in domains]
    device = {'entity_id': 'camera.pool', 'entities': ['camera.pool', *ids, 'sensor.temp', 'binary_sensor.flow'],
              'name': 'Pool', 'kind': 'camera'}
    states = {eid: _state(eid, friendly_name=f'POOL: {eid.partition(".")[0]}') for eid in ids}
    accessories = twin_ha.device_accessories(device, states)
    assert [a['entity_id'] for a in accessories] == ids
    assert [a['name'] for a in accessories] == domains
    expected = {'input_boolean': 'switch', 'cover': 'blinds', 'input_number': 'number',
                'input_select': 'select', 'button': 'other', 'siren': 'other'}
    assert [a['kind'] for a in accessories] == [expected.get(d, d) for d in domains]
    device['entity_id'] = 'light.pool'
    assert 'light.pool' not in {a['entity_id'] for a in twin_ha.device_accessories(device, states)}


def test_no_ha_has_no_accessories_or_errors():
    seed()
    with Ctx(available=False) as c:
        response = c.client.get(LIVE, headers=c.mum)
        assert response.status_code == 200
        assert response.json()['devices'] == response.json()['markers'] == []


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print('ok  ', test.__name__)
        except Exception:
            print('FAIL', test.__name__)
            traceback.print_exc(limit=5)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
