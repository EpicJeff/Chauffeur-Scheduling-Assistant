"""A fake Home Assistant for the house editor's live scenarios (piece 3 of
docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md, Tasks 4 and 5).

The live app runs in this process (tests/live_app.py serves uvicorn on a
thread), so patching services.ha_api's functions reaches every route the
editor calls. The shapes are the ones tests/test_twin_ha_routes.py fakes:
the area registry carries floor_id, the floor registry carries level, the
entity registry maps entity ids to device ids, the device registry carries
each device's area, and get_area_map lists each area's entities.

Unlike the routes test's fake, availability is read at call time, so one
served app can answer as a connected house in one scenario and as a house
with no Home Assistant in the next:

    import house_ha_fake
    fake = house_ha_fake.FakeHA(areas=..., floors=..., devices=...).install()
    fake.available = False      # the next request sees no Home Assistant
    fake.calls                  # every call_service: (domain, service, data)

Each device is {'id', 'name', 'area_id', 'entities': [(entity_id, state, attributes)]};
an entity's friendly_name is the device's name unless its attributes give one.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PATCHED = ('mode', 'is_available', 'get_states', 'get_state', 'call_service', 'get_area_map',
           'get_entity_registry', 'get_device_registry', 'get_area_registry', 'ws_command',
           'get_exposed', 'get_floor_registry')


class FakeHA:
    def __init__(self, areas, floors, devices, available=True):
        self.available = available
        self.areas = copy.deepcopy(areas)
        self.floors = copy.deepcopy(floors)
        self.devices = copy.deepcopy(devices)
        self.calls = []
        self.fail_calls = False
        self.states = {}
        for device in self.devices:
            for eid, state, attrs in device['entities']:
                self.states[eid] = {'entity_id': eid, 'state': state,
                                    'attributes': {'friendly_name': device['name'], **(attrs or {})}}
        self.orig = None

    # --- the registries ------------------------------------------------------
    def _entities(self):
        return [(eid, d['id']) for d in self.devices for eid, _s, _a in d['entities']]

    def _area_of(self, device_id):
        return next(d['area_id'] for d in self.devices if d['id'] == device_id)

    def area_map(self, ttl=60):
        if not self.available:
            return []
        return [{'id': a['area_id'], 'name': a['name'],
                 'entities': [eid for eid, did in self._entities() if self._area_of(did) == a['area_id']]}
                for a in self.areas]

    # --- install -------------------------------------------------------------
    def install(self):
        from services import ha_api
        fake = self
        self.orig = {n: getattr(ha_api, n, None) for n in PATCHED}
        ha_api.mode = lambda: 'direct' if fake.available else 'unconfigured'
        ha_api.is_available = lambda: fake.available
        ha_api.get_states = lambda ttl=5: copy.deepcopy(list(fake.states.values())) if fake.available else []
        ha_api.get_state = lambda eid, *a, **k: copy.deepcopy(fake.states.get(eid)) if fake.available else None
        ha_api.get_area_map = self.area_map
        ha_api.get_entity_registry = lambda ttl=300: (
            [{'entity_id': eid, 'device_id': did, 'area_id': None, 'name': None, 'platform': 'fake'}
             for eid, did in fake._entities()] if fake.available else [])
        ha_api.get_device_registry = lambda ttl=300: (
            [{'id': d['id'], 'name': d['name'], 'name_by_user': None, 'manufacturer': 'Acme', 'model': 'X',
              'area_id': d['area_id']} for d in fake.devices] if fake.available else [])
        ha_api.get_area_registry = lambda ttl=300: (
            [{'area_id': a['area_id'], 'name': a['name'], 'floor_id': a.get('floor_id'), 'picture': None,
              'icon': None} for a in fake.areas] if fake.available else [])
        ha_api.get_floor_registry = lambda ttl=300: copy.deepcopy(fake.floors) if fake.available else []
        ha_api.get_exposed = lambda ttl=60: {}

        def ws(command, timeout=8, **fields):
            if not fake.available:
                return None
            if command == 'config/area_registry/list':
                return [dict(a) for a in fake.areas]
            if command == 'config/floor_registry/list':
                return copy.deepcopy(fake.floors)
            return None
        ha_api.ws_command = ws

        def call(domain, service, data=None, **kw):
            if not fake.available or fake.fail_calls:
                raise RuntimeError('Home Assistant is not reachable.')
            fake.calls.append((domain, service, copy.deepcopy(data)))
            ids = (data or {}).get('entity_id')
            for eid in ([ids] if isinstance(ids, str) else ids or []):
                row = fake.states.get(eid)
                if row is None:
                    continue
                if service == 'turn_on':
                    row['state'] = 'on'
                elif service == 'turn_off':
                    row['state'] = 'off'
                elif service == 'toggle':
                    row['state'] = 'off' if row['state'] == 'on' else 'on'
            return []
        ha_api.call_service = call
        return self

    def uninstall(self):
        from services import ha_api
        for n, fn in (self.orig or {}).items():
            if fn is None:
                if hasattr(ha_api, n):
                    delattr(ha_api, n)
            else:
                setattr(ha_api, n, fn)

    def calls_on(self, eid):
        out = []
        for domain, service, data in self.calls:
            ids = (data or {}).get('entity_id')
            ids = [ids] if isinstance(ids, str) else list(ids or [])
            if eid in ids:
                out.append((domain, service, data))
        return out
