"""House-only HA presentation: Show as (device with controls / separate entities) and Hide.

The user, 2026-11-13: "I want the entities to come through so I can place them individually.
Maybe there can be a toggle to have them as individual entities or as controls on the main
device." and "I also want to be able to hide certain things from the panel." Home Assistant
is never changed.
"""
import sys
import traceback

from test_twin_ha_routes import Ctx, LIVE, LINK, seed, ts, marker_for
from test_twin_device_controls import controller

OP = '/api/house/editor/op'
POOL = [('light.pool', 'Light'), ('switch.pump', 'Pump'), ('switch.waterfall', 'Waterfall'),
        ('switch.spa_jets', 'Spa jets'), ('water_heater.pool', 'Heater'), ('sensor.pool', 'Temperature')]


def _yard(model):
    model['site']['yard_rooms'] = [{'id': 'pool', 'name': 'Pool deck', 'ha_area': 'kitchen',
                                    'polygon': [[0, 0], [20, 0], [20, 20], [0, 20]]}]
    model['buildings'][0]['rooms'][0]['ha_area'] = None
    return model


def _op(c, op, headers=None):
    return c.client.post(OP, headers=headers or c.mum, json={'op': op})


def _ids(body):
    # Only the pool controller and its entity items; the fixture's area has other devices too.
    return sorted(d['device_id'] for d in body['devices']
                  if d['device_id'] == 'dev-k-light' or d['device_id'].startswith('entity:'))


def test_default_is_one_device_with_controls_unchanged():
    seed(); ts.update_model(_yard)
    with Ctx() as c:
        controller(c, POOL)
        body = c.client.get(LIVE, headers=c.mum).json()
        assert _ids(body) == ['dev-k-light']
        assert len(marker_for(body, 'dev-k-light')['accessories']) == 4
        link = next(d for d in c.client.get(LINK, headers=c.mum).json()['devices'] if d['device_id'] == 'dev-k-light')
        assert link['show_as'] == 'controls' and link['hidden'] is False
        assert [a['entity_id'] for a in link['controls']] == ['switch.pump', 'switch.waterfall', 'switch.spa_jets', 'water_heater.pool']


def test_separate_entities_are_placeable_items_and_switching_back_unplaces_them():
    seed(); ts.update_model(_yard)
    with Ctx() as c:
        controller(c, POOL)
        r = _op(c, {'op': 'set_ha_display', 'device': 'dev-k-light', 'show_as': 'entities'})
        assert r.status_code == 200, r.text
        assert ts.current_model()['ha_display']['devices']['dev-k-light']['show_as'] == 'entities'
        body = c.client.get(LIVE, headers=c.mum).json()
        items = ['entity:light.pool', 'entity:switch.pump', 'entity:switch.waterfall', 'entity:switch.spa_jets', 'entity:water_heater.pool']
        assert _ids(body) == sorted(items), _ids(body)
        rows = {d['device_id']: d for d in body['devices']}
        assert rows['entity:water_heater.pool']['kind'] == 'water_heater' and rows['entity:switch.pump']['name'] == 'Pump'
        assert all(rows[i]['accessories'] == [] and rows[i]['offered'] is True for i in items)
        link = {d['device_id']: d for d in c.client.get(LINK, headers=c.mum).json()['devices']}
        assert link['entity:switch.pump']['parent_name'] == 'Pool controller'
        # Each item is placed on its own, in the yard room.
        r = _op(c, {'op': 'place_device', 'device': 'entity:switch.pump', 'host': {'yard_room': 'pool', 'u': .2, 'v': .3}, 'offset': 1})
        assert r.status_code == 200, r.text
        m = marker_for(c.client.get(LIVE, headers=c.mum).json(), 'entity:switch.pump')
        assert m and m['placed'] and m['yard']
        # Back to one device: entity placements go, in one history step.
        rounds = len(ts.rounds())
        r = _op(c, {'op': 'set_ha_display', 'device': 'dev-k-light', 'show_as': 'controls'})
        assert r.status_code == 200 and 'Removed 1 entity placement' in r.json()['words'], r.text
        assert len(ts.rounds()) == rounds + 1
        assert not [d for d in ts.current_model()['site'].get('devices', []) if d['device'].startswith('entity:')]
        assert _ids(c.client.get(LIVE, headers=c.mum).json()) == ['dev-k-light']


def test_hide_device_entity_item_and_accessory():
    seed(); ts.update_model(_yard)
    with Ctx() as c:
        controller(c, POOL)
        assert _op(c, {'op': 'set_ha_display', 'kind': 'entities', 'item': 'switch.waterfall', 'hidden': True}).status_code == 200
        body = c.client.get(LIVE, headers=c.mum).json()
        assert 'switch.waterfall' not in [a['entity_id'] for a in marker_for(body, 'dev-k-light')['accessories']]
        _op(c, {'op': 'set_ha_display', 'device': 'dev-k-light', 'show_as': 'entities'})
        body = c.client.get(LIVE, headers=c.mum).json()
        assert 'entity:switch.waterfall' not in _ids(body) and 'entity:switch.pump' in _ids(body)
        # The editor still lists the hidden item, marked hidden, so it can be shown again.
        link = {d['device_id']: d for d in c.client.get(LINK, headers=c.mum).json()['devices']}
        assert link['entity:switch.waterfall']['hidden'] is True
        assert _op(c, {'op': 'set_ha_display', 'kind': 'entities', 'item': 'entity:switch.waterfall', 'hidden': False}).status_code == 200
        assert 'entity:switch.waterfall' in _ids(c.client.get(LIVE, headers=c.mum).json())
        assert _op(c, {'op': 'set_ha_display', 'kind': 'devices', 'item': 'dev-k-light', 'hidden': True}).status_code == 200
        assert _ids(c.client.get(LIVE, headers=c.mum).json()) == []
        link = {d['device_id']: d for d in c.client.get(LINK, headers=c.mum).json()['devices']}
        # Still listed for the editor, marked as hidden with their device.
        assert link['entity:switch.pump']['device_hidden'] is True and link['entity:switch.pump']['hidden'] is False


def test_only_parents_change_display_and_nothing_changed_is_refused():
    seed(); ts.update_model(_yard)
    with Ctx() as c:
        controller(c, POOL)
        assert _op(c, {'op': 'set_ha_display', 'kind': 'devices', 'item': 'dev-k-light', 'hidden': True}, c.kid).status_code in (401, 403)
        r = _op(c, {'op': 'set_ha_display', 'device': 'dev-k-light', 'show_as': 'controls'})
        assert r.status_code == 400 and 'Nothing changed' in r.text
        r = _op(c, {'op': 'set_ha_display', 'device': 'dev-k-light', 'show_as': 'sideways'})
        assert r.status_code == 400
        body = c.client.get(LIVE, headers=c.mum).json()
        assert body['can_edit_house'] is True
        assert c.client.get(LIVE, headers=c.panel).json()['can_edit_house'] is False


def test_settings_survive_normalize_and_bad_settings_reset():
    from services import twin_model
    seed()
    model = ts.current_model()
    model['ha_display'] = {'devices': {'d1': {'show_as': 'entities'}}, 'hidden': {'devices': ['d2'], 'entities': ['switch.x']}}
    out, notes = twin_model.normalize(model)
    assert out['ha_display']['devices']['d1']['show_as'] == 'entities' and out['ha_display']['hidden']['entities'] == ['switch.x']
    model['ha_display'] = {'devices': {'d1': {'show_as': 'sideways'}}}
    out, notes = twin_model.normalize(model)
    assert out['ha_display'] == {'devices': {}, 'hidden': {'devices': [], 'entities': []}} and notes


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
            traceback.print_exc(limit=6)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
