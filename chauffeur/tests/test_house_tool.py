"""The house tool (docs/superpowers/specs/2026-10-27-house-tool-design.md).

Argyle reads and controls Home Assistant devices through one tool, `house`.
Reads are open to anyone; writes respect HA's Assist exposure unless the
household lifts it; locks, alarms and garage doors need a parent or adult
(signed in, admin chat, or a VERIFIED voice). Every act reads the entity
back. Stubbed ha_api, the real services.house and the real tool entry point.

Run from chauffeur/:  python tests/test_house_tool.py
"""
import types
import unittest

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_tools_v2, ha_api, house, maps, storage

LAMP_TOKEN = 'eyJ-secret-should-never-leave'
EV9_PARTS = ('engine', 'defrost', 'trunk', 'hood', 'front_left_door', 'front_right_door', 'back_left_door',
             'back_right_door', 'sunroof', 'locked')
TV_APPS = ('Netflix', 'YouTube', 'Disney+', 'Prime Video', 'Hulu', 'Max', 'Plex', 'Spotify', 'Paramount+',
           'Peacock', 'Apple TV', 'YouTube TV', 'Sling TV')
# Live shape 2026-10-29: the Tesla Powerwall is ONE HA device ("My Home", Garage) with ~50 entities;
# only the entity names say Powerwall. (entity id, name, state, unit, device_class)
POWERWALL = (
    ('sensor.powerwall_version', 'Powerwall Version', 'unavailable', None, None),
    ('sensor.powerwall_percentage_charged', 'Powerwall Percentage charged', '40.129133242027', '%', 'battery'),
    ('sensor.powerwall_battery_power', 'Powerwall Battery power', '0.0', 'kW', 'power'),
    ('sensor.powerwall_solar_power', 'Powerwall Solar power', '10.119', 'kW', 'power'),
    ('sensor.powerwall_grid_power', 'Powerwall Grid power', '-8.495', 'kW', 'power'),
    ('sensor.powerwall_battery_charged', 'Powerwall Battery charged', '9.535', 'kWh', 'energy'),
    ('sensor.my_home_battery_exported', 'Powerwall Battery exported', '7.721', 'kWh', 'energy'),
    ('sensor.powerwall_island_status', 'Powerwall Island status', 'on_grid', None, 'enum'),
    ('number.powerwall_backup_reserve', 'Powerwall Backup reserve', '20', '%', 'battery'),
    ('binary_sensor.powerwall_grid_status', 'Powerwall Grid status', 'on', None, 'power'),
    ('switch.powerwall_storm_watch', 'Powerwall Storm watch', 'off', None, 'switch'),
    ('select.powerwall_operation_mode', 'Powerwall Operation mode', 'autonomous', None, None),
)
EV9_ADDRESS = '12 Maple Lane, Example Township, Cary, Wake County, North Carolina, 27500, United States'


def _states():
    return [
        {'entity_id': 'light.office_lamp', 'state': 'on', 'last_changed': '2026-10-27T10:00:00+00:00',
         'attributes': {'friendly_name': 'Office Lamp', 'brightness': 128, 'color_mode': 'brightness',
                        'access_token': LAMP_TOKEN, 'supported_color_modes': ['brightness']}},
        {'entity_id': 'media_player.office_tv_2', 'state': 'on', 'last_changed': '2026-10-27T09:00:00+00:00',
         'attributes': {'friendly_name': 'Office TV', 'access_token': 'tv-token', 'entity_picture': '/api/x',
                        'app_id': 'com.att.tv', 'app_name': 'com.att.tv', 'device_class': 'tv'}},
        {'entity_id': 'remote.office_tv', 'state': 'on', 'last_changed': '2026-10-27T09:00:00+00:00',
         'attributes': {'friendly_name': 'Office TV', 'current_activity': 'com.att.tv', 'activity_list': list(TV_APPS)}},
        {'entity_id': 'media_player.living_room_tv_2', 'state': 'off', 'last_changed': '2026-10-27T09:00:00+00:00',
         'attributes': {'friendly_name': 'Living Room TV', 'device_class': 'tv'}},
        {'entity_id': 'remote.living_room_tv', 'state': 'off', 'last_changed': '2026-10-27T09:00:00+00:00',
         'attributes': {'friendly_name': 'Living Room TV', 'current_activity': None, 'activity_list': ['Netflix', 'YouTube']}},
        {'entity_id': 'remote.living_room', 'state': 'on', 'last_changed': '2026-10-27T09:00:00+00:00',
         'attributes': {'friendly_name': 'Living Room Apple TV'}},
        {'entity_id': 'remote.sunroom_tv', 'state': 'unavailable', 'last_changed': '2026-10-27T09:00:00+00:00',
         'attributes': {'friendly_name': 'Sunroom TV'}},
        {'entity_id': 'media_player.office_cast', 'state': 'playing', 'last_changed': '2026-10-27T09:00:00+00:00',
         'attributes': {'friendly_name': 'Office Google TV Media Player', 'app_name': 'YouTube',
                        'media_title': 'Peppa Pig Tales', 'media_artist': 'Peppa Pig Stories',
                        'media_position': 209.7, 'media_duration': 1994.6, 'media_content_type': 'video'}},
        {'entity_id': 'light.front_porch_column_1', 'state': 'off', 'last_changed': '2026-10-27T08:00:00+00:00',
         'attributes': {'friendly_name': 'Front Porch Column 1'}},
        {'entity_id': 'light.hall', 'state': 'off', 'last_changed': '2026-10-27T08:00:00+00:00',
         'attributes': {'friendly_name': 'Hall Light'}},
        {'entity_id': 'lock.front_door', 'state': 'locked', 'last_changed': '2026-10-27T07:00:00+00:00',
         'attributes': {'friendly_name': 'Front Door'}},
        {'entity_id': 'cover.main_garage', 'state': 'closed', 'last_changed': '2026-10-27T06:00:00+00:00',
         'attributes': {'friendly_name': 'Main Garage', 'device_class': 'garage'}},
        {'entity_id': 'cover.office_blind', 'state': 'open', 'last_changed': '2026-10-27T06:00:00+00:00',
         'attributes': {'friendly_name': 'Office Blind', 'device_class': 'blind'}},
        {'entity_id': 'light.hidden_strip', 'state': 'on', 'last_changed': '2026-10-27T06:00:00+00:00',
         'attributes': {'friendly_name': 'Office Strip'}},
        *[{'entity_id': f'binary_sensor.ev9_{k}', 'state': 'off', 'last_changed': '2026-10-27T06:00:00+00:00',
           'attributes': {'friendly_name': f'Kia EV9 {k.replace("_", " ").title()}'}}
          for k in EV9_PARTS],
        {'entity_id': 'device_tracker.ev9_location', 'state': 'home', 'last_changed': '2026-10-27T14:13:16+00:00',
         'last_updated': '2026-10-27T14:13:16+00:00',
         'attributes': {'friendly_name': 'Kia EV9 Location', 'source_type': 'gps', 'latitude': 35.780736,
                        'longitude': -78.915669, 'gps_accuracy': 0, 'in_zones': ['zone.home', 'zone.bus_stop']}},
        {'entity_id': 'sensor.garage_kia_ev9_geocoded_location', 'last_changed': '2026-10-27T14:13:16+00:00',
         'state': EV9_ADDRESS, 'attributes': {'friendly_name': 'Kia EV9 Geocoded Location'}},
        {'entity_id': 'device_tracker.van', 'state': 'not_home', 'last_changed': '2026-10-27T15:00:00+00:00',
         'last_updated': '2026-10-27T15:00:00+00:00',
         'attributes': {'friendly_name': 'Van', 'latitude': 35.79, 'longitude': -78.78, 'gps_accuracy': 12}},
        {'entity_id': 'person.lorena_wilson', 'state': 'home', 'last_changed': '2026-10-27T13:00:00+00:00',
         'last_updated': '2026-10-27T13:00:00+00:00',
         'attributes': {'friendly_name': 'Lorena Wilson', 'source': 'device_tracker.lorena_phone',
                        'device_trackers': ['device_tracker.lorena_phone'], 'latitude': 35.70, 'longitude': -78.70,
                        'gps_accuracy': 20, 'user_id': 'u1'}},
        {'entity_id': 'device_tracker.lorena_phone', 'state': 'home', 'last_changed': '2026-10-27T13:00:00+00:00',
         'attributes': {'friendly_name': "Lorena's Phone", 'source_type': 'gps', 'latitude': 35.70, 'longitude': -78.70}},
        {'entity_id': 'person.jeff_wilson_2', 'state': 'not_home', 'last_changed': '2026-10-27T12:00:00+00:00',
         'last_updated': '2026-10-27T12:30:00+00:00',
         'attributes': {'friendly_name': 'Jeff Wilson', 'source': 'device_tracker.jeff_phone',
                        'device_trackers': ['device_tracker.jeffs_iphone_2', 'device_tracker.jeff_phone'],
                        'latitude': 35.81, 'longitude': -78.81, 'gps_accuracy': 5}},
        {'entity_id': 'device_tracker.jeff_phone', 'state': 'not_home', 'last_changed': '2026-10-27T12:00:00+00:00',
         'attributes': {'friendly_name': "Jeff's Phone", 'source_type': 'gps', 'latitude': 35.81, 'longitude': -78.81}},
        {'entity_id': 'device_tracker.jeffs_iphone_2', 'state': 'not_home', 'last_changed': '2026-10-27T11:00:00+00:00',
         'attributes': {'friendly_name': 'Jeff\u2019s iPhone (2)', 'source_type': 'gps', 'latitude': 35.80, 'longitude': -78.80}},
        {'entity_id': 'person.lily', 'state': 'unknown', 'last_changed': '2026-10-01T00:00:00+00:00',
         'attributes': {'friendly_name': 'Lily', 'device_trackers': []}},
        {'entity_id': 'device_tracker.lillian_bus', 'state': 'GREEN LEVEL HS', 'last_changed': '2026-10-27T07:30:00+00:00',
         'attributes': {'friendly_name': 'LILLIAN Bus', 'source_type': 'gps', 'latitude': 35.75, 'longitude': -78.95}},
        *[{'entity_id': eid, 'state': state, 'last_changed': '2026-10-29T06:00:00+00:00',
           'attributes': {'friendly_name': name, **({'unit_of_measurement': unit} if unit else {}),
                          **({'device_class': dc} if dc else {})}}
          for eid, name, state, unit, dc in POWERWALL],
        {'entity_id': 'automation.charge_powerwall_nightly', 'state': 'off', 'last_changed': '2026-10-29T06:00:00+00:00',
         'attributes': {'friendly_name': 'Powerwall - Charge Nightly'}},
    ]


REGISTRY = [
    {'entity_id': 'light.office_lamp', 'name': None, 'original_name': 'Office Lamp', 'aliases': [],
     'area_id': 'office', 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'hue'},
    {'entity_id': 'media_player.office_tv_2', 'name': 'Office TV', 'original_name': None, 'aliases': [],
     'area_id': 'office', 'device_id': 'dev_office_tv', 'hidden_by': None, 'disabled_by': None, 'platform': 'androidtv_remote'},
    {'entity_id': 'remote.office_tv', 'name': None, 'original_name': 'Office TV', 'aliases': [],
     'area_id': None, 'device_id': 'dev_office_tv', 'hidden_by': None, 'disabled_by': None, 'platform': 'androidtv_remote'},
    {'entity_id': 'media_player.living_room_tv_2', 'name': None, 'original_name': 'Living Room TV', 'aliases': [],
     'area_id': None, 'device_id': 'dev_living_tv', 'hidden_by': None, 'disabled_by': None, 'platform': 'androidtv_remote'},
    {'entity_id': 'remote.living_room_tv', 'name': None, 'original_name': 'Living Room TV', 'aliases': [],
     'area_id': None, 'device_id': 'dev_living_tv', 'hidden_by': None, 'disabled_by': None, 'platform': 'androidtv_remote'},
    {'entity_id': 'remote.living_room', 'name': None, 'original_name': 'Living Room Apple TV', 'aliases': [],
     'area_id': 'living_room', 'device_id': 'dev_apple_tv', 'hidden_by': None, 'disabled_by': None, 'platform': 'apple_tv'},
    {'entity_id': 'remote.sunroom_tv', 'name': None, 'original_name': 'Sunroom TV', 'aliases': [],
     'area_id': 'sunroom', 'device_id': 'dev_sunroom_tv', 'hidden_by': None, 'disabled_by': None, 'platform': 'androidtv_remote'},
    # Device 2026-10-28: the Cast face of the Office TV sits in NO HA area; only its name says Office.
    {'entity_id': 'media_player.office_cast', 'name': None, 'original_name': 'Office Google TV Media Player', 'aliases': [],
     'area_id': None, 'device_id': 'dev_office_cast', 'hidden_by': None, 'disabled_by': None, 'platform': 'cast'},
    {'entity_id': 'light.front_porch_column_1', 'name': None, 'original_name': 'Front Porch Column 1',
     'aliases': ['front porch column one'], 'area_id': 'front_yard', 'device_id': None,
     'hidden_by': None, 'disabled_by': None, 'platform': 'hue'},
    {'entity_id': 'light.hall', 'name': None, 'original_name': 'Hall Light', 'aliases': [],
     'area_id': 'hall', 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'hue'},
    {'entity_id': 'lock.front_door', 'name': None, 'original_name': 'Front Door', 'aliases': [],
     'area_id': 'hall', 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'august'},
    {'entity_id': 'cover.main_garage', 'name': None, 'original_name': 'Main Garage', 'aliases': [],
     'area_id': 'garage', 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'myq'},
    {'entity_id': 'cover.office_blind', 'name': None, 'original_name': 'Office Blind', 'aliases': [],
     'area_id': 'office', 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'somfy'},
    {'entity_id': 'light.hidden_strip', 'name': None, 'original_name': 'Office Strip', 'aliases': [],
     'area_id': 'office', 'device_id': None, 'hidden_by': 'user', 'disabled_by': None, 'platform': 'wled'},
    *[{'entity_id': f'binary_sensor.ev9_{k}', 'name': None, 'original_name': k.replace('_', ' ').title(), 'aliases': [],
       'area_id': None, 'device_id': 'dev_ev9', 'hidden_by': None, 'disabled_by': None, 'platform': 'kia_uvo'}
      for k in EV9_PARTS],
    {'entity_id': 'device_tracker.ev9_location', 'name': None, 'original_name': 'Location', 'aliases': [],
     'area_id': None, 'device_id': 'dev_ev9', 'hidden_by': None, 'disabled_by': None, 'platform': 'kia_uvo'},
    {'entity_id': 'sensor.garage_kia_ev9_geocoded_location', 'name': None, 'original_name': 'Geocoded Location',
     'aliases': [], 'area_id': None, 'device_id': 'dev_ev9', 'hidden_by': None, 'disabled_by': None, 'platform': 'kia_uvo'},
    {'entity_id': 'device_tracker.van', 'name': None, 'original_name': 'Van', 'aliases': [],
     'area_id': None, 'device_id': 'dev_van', 'hidden_by': None, 'disabled_by': None, 'platform': 'mobile_app'},
    *[{'entity_id': eid, 'name': None, 'original_name': name, 'aliases': [], 'area_id': None, 'device_id': None,
       'hidden_by': None, 'disabled_by': None, 'platform': platform}
      for eid, name, platform in (('person.lorena_wilson', 'Lorena Wilson', 'person'),
                                  ('device_tracker.lorena_phone', "Lorena's Phone", 'mobile_app'),
                                  ('person.jeff_wilson_2', 'Jeff Wilson', 'person'),
                                  ('device_tracker.jeff_phone', "Jeff's Phone", 'mobile_app'),
                                  ('device_tracker.jeffs_iphone_2', 'Jeff\u2019s iPhone (2)', 'icloud'),
                                  ('person.lily', 'Lily', 'person'),
                                  ('device_tracker.lillian_bus', 'LILLIAN Bus', 'hctb'))],
    *[{'entity_id': eid, 'name': None, 'original_name': name.replace('Powerwall ', ''), 'aliases': [], 'area_id': None,
       'device_id': 'dev_powerwall', 'hidden_by': None, 'disabled_by': None, 'platform': 'powerwall'}
      for eid, name, _s, _u, _d in POWERWALL],
    {'entity_id': 'automation.charge_powerwall_nightly', 'name': None, 'original_name': 'Powerwall - Charge Nightly',
     'aliases': [], 'area_id': None, 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'automation'},
]

DEVICES = [{'id': 'dev_ev9', 'name': 'Kia EV9', 'area_id': 'garage'}, {'id': 'dev_van', 'name': 'Van', 'area_id': None},
           {'id': 'dev_powerwall', 'name': 'My Home', 'area_id': 'garage'},
           {'id': 'dev_office_cast', 'name': 'GoogleTV1645', 'area_id': None},
           {'id': 'dev_office_tv', 'name': 'Office TV', 'area_id': 'office'},
           {'id': 'dev_living_tv', 'name': 'Living Room TV', 'area_id': 'living_room'},
           {'id': 'dev_apple_tv', 'name': 'Living Room Apple TV', 'area_id': 'living_room'}]

AREAS = [
    {'id': 'office', 'name': 'Office', 'entities': ['light.office_lamp', 'media_player.office_tv_2',
                                                    'remote.office_tv', 'cover.office_blind', 'light.hidden_strip']},
    {'id': 'living_room', 'name': 'Living Room', 'entities': ['media_player.living_room_tv_2', 'remote.living_room_tv',
                                                              'remote.living_room']},
    {'id': 'front_yard', 'name': 'Front Yard', 'entities': ['light.front_porch_column_1']},
    {'id': 'hall', 'name': 'Hall', 'entities': ['light.hall', 'lock.front_door']},
    {'id': 'garage', 'name': 'Garage', 'entities': ['cover.main_garage', 'device_tracker.ev9_location',
                                                    'sensor.garage_kia_ev9_geocoded_location',
                                                    *[f'binary_sensor.ev9_{k}' for k in EV9_PARTS],
                                                    *[row[0] for row in POWERWALL]]},
]

EXPOSED = {'light.office_lamp': True, 'media_player.office_tv_2': True, 'light.front_porch_column_1': True,
           'lock.front_door': True, 'cover.main_garage': True, 'cover.office_blind': True, 'light.hall': False}

SERVICES = {'light': {'turn_on', 'turn_off', 'toggle'}, 'lock': {'lock', 'unlock'},
            'cover': {'open_cover', 'close_cover'}, 'media_player': {'turn_off', 'turn_on'},
            'remote': {'turn_on', 'turn_off', 'send_command'}}


def voice(level, member=None):
    return types.SimpleNamespace(level=level, member=lambda: member,
                                 verified_member=lambda: member if level == 'verified' else None)


class HouseToolTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.tv_ignores_launches = False
        self.tv_opens_browser = False
        self.states = _states()
        self.settings = {}
        self.orig = {}

        def stub(mod, name, value):
            self.orig[(mod, name)] = getattr(mod, name)
            setattr(mod, name, value)
        tests = self

        def call_service(domain, service, data=None, return_response=False, timeout=None):
            tests.calls.append((domain, service, dict(data or {})))
            eid = (data or {}).get('entity_id')
            after = {('light', 'turn_on'): 'on', ('light', 'turn_off'): 'off', ('lock', 'unlock'): 'unlocked',
                     ('lock', 'lock'): 'locked', ('cover', 'open_cover'): 'open', ('media_player', 'turn_off'): 'off'}
            if (domain, service) == ('remote', 'turn_on') and not tests.tv_ignores_launches:
                # The TV never echoes a link: the twin reports the package id, the remote
                # reports the configured NAME when HA knows the id, else the package.
                twin = {'remote.office_tv': 'media_player.office_tv_2',
                        'remote.living_room_tv': 'media_player.living_room_tv_2'}.get(eid)
                sent = (data or {}).get('activity')
                hit = next(((n, p) for n, p, a, l in house.KNOWN_APPS if sent in (l, p)), None)
                package = 'com.tcl.browser' if tests.tv_opens_browser else (hit[1] if hit else sent)
                shown = hit[0] if hit and hit[0] in TV_APPS and not tests.tv_opens_browser else package
                for s in tests.states:
                    if s['entity_id'] == eid:
                        s['state'] = 'on'
                        if sent:
                            s['attributes']['current_activity'] = shown
                    if s['entity_id'] == twin:
                        s['state'] = 'on'
                        if sent:
                            s['attributes']['app_id'] = package
            for s in tests.states:
                if s['entity_id'] == eid and (domain, service) in after:
                    s['state'] = after[(domain, service)]
                    if (domain, service) == ('light', 'turn_on') and 'brightness_pct' in (data or {}):
                        s['attributes']['brightness'] = round(data['brightness_pct'] * 255 / 100)
            return []
        stub(ha_api, 'get_states', lambda ttl=5: tests.states)
        stub(ha_api, 'get_entity_registry', lambda ttl=300: REGISTRY)
        stub(ha_api, 'get_area_map', lambda ttl=60: AREAS)
        stub(ha_api, 'get_device_registry', lambda ttl=300: DEVICES)
        self.geocoded = []
        stub(maps, 'reverse_geocode', lambda lat, lon: (tests.geocoded.append((lat, lon)) or 'Target, 12 Elm St, Cary'))
        stub(ha_api, 'get_exposed', lambda ttl=60: dict(EXPOSED))
        stub(ha_api, 'call_service', call_service)
        stub(ha_api, 'has_service', lambda d, s: s in SERVICES.get(d, set()))
        stub(ha_api, 'get_history', lambda entity_id, hours=24: tests.history(entity_id, hours))
        stub(ha_api, 'mode', lambda: 'supervisor')
        stub(storage, 'get_settings', lambda: dict(tests.settings))
        stub(house, '_settle', lambda: None)  # no 0.6 s sleep in tests
        with storage.db_lock:
            storage.members_table.truncate()
        storage.add_member({'id': 'm_lorena', 'name': 'Lorena', 'role': 'parent', 'voice_aliases': ['Mom'],
                            'ha_person_entity': 'person.lorena_wilson'})
        storage.add_member({'id': 'm_lily', 'name': 'Lily', 'role': 'child', 'ha_person_entity': 'person.lily'})
        storage.add_member({'id': 'm_james', 'name': 'James', 'role': 'child'})
        from services import stages
        self.private_location = set()
        stub(stages, 'can', lambda member, capability: (capability != 'private_location'
                                                        or (member or {}).get('id') in tests.private_location))
        self.history_rows = []

    def history(self, entity_id, hours):
        return self.history_rows

    def tearDown(self):
        for (mod, name), value in self.orig.items():
            setattr(mod, name, value)
        with storage.db_lock:
            storage.members_table.truncate()

    def run_tool(self, **kw):
        return agent_tools_v2.house(**kw)

    # --- find ---------------------------------------------------------------
    def test_find_ranks_the_named_device_first_and_matches_aliases(self):
        res = self.run_tool(action='find', query='office lamp')
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['candidates'][0]['entity_id'], 'light.office_lamp')
        self.assertEqual(res['candidates'][0]['ha_area'], 'Office')
        self.assertNotIn('area', res['candidates'][0], 'the HA room must not be called a location-sounding "area"')
        ids = [c['entity_id'] for c in self.run_tool(action='find', query='front porch column one')['candidates']]
        self.assertEqual(ids[0], 'light.front_porch_column_1', 'the registry alias did not match')

    def test_find_skips_hidden_entities_and_filters_by_domain(self):
        ids = [c['entity_id'] for c in self.run_tool(action='find', query='office')['candidates']]
        self.assertNotIn('light.hidden_strip', ids)
        ids = [c['entity_id'] for c in self.run_tool(action='find', query='office', domain='light')['candidates']]
        self.assertEqual(ids, ['light.office_lamp'])

    def test_find_by_area_lists_the_rooms_devices(self):
        ids = {c['entity_id'] for c in self.run_tool(action='find', query='garage')['candidates']}
        self.assertIn('cover.main_garage', ids)

    # --- a device is many sensors (2026-10-29) --------------------------------
    def test_one_word_finds_every_sensor_on_the_device_with_units(self):
        """Live 2026-10-29: "what level is the Powerwall battery" found ONE entity, Powerwall Version
        (unavailable), and Argyle said unknown; the percentage sat on the same device unseen. A query
        that names a device answers with the whole device: every entity, unit and device_class."""
        res = self.run_tool(action='find', query='powerwall')
        self.assertEqual(res['status'], 'success', res)
        ids = [c['entity_id'] for c in res['candidates']]
        self.assertGreater(len(ids), 1, 'Powerwall Version alone was the live failure')
        self.assertTrue(all(c['device'] == 'My Home' for c in res['candidates'] if c['domain'] != 'automation'))
        dev = res['devices'][0]
        self.assertEqual(dev['device'], 'My Home')
        self.assertEqual(dev['ha_area'], 'Garage')
        rows = {r['entity_id']: r for r in dev['entities']}
        self.assertEqual(len(rows), len(POWERWALL), 'every entity on the device, not only the matching ones')
        pct = rows['sensor.powerwall_percentage_charged']
        self.assertEqual((pct['state'], pct['unit'], pct['device_class']), ('40.129133242027', '%', 'battery'))
        self.assertEqual(rows['sensor.powerwall_version']['state'], 'unavailable')
        self.assertNotIn('unit', rows['sensor.powerwall_version'])
        self.assertNotIn('automation.charge_powerwall_nightly', rows, 'off-device entities are not the device')
        self.assertEqual(self.calls, [])

    def test_a_devices_own_name_finds_its_sensors_too(self):
        for query, device, member in (('kia ev9', 'Kia EV9', 'binary_sensor.ev9_engine'),
                                      ('my home', 'My Home', 'sensor.powerwall_percentage_charged')):
            res = self.run_tool(action='find', query=query)
            self.assertEqual(res['devices'][0]['device'], device, res.get('devices'))
            self.assertIn(member, [r['entity_id'] for r in res['devices'][0]['entities']])

    def test_reading_a_device_by_name_answers_the_whole_device(self):
        res = self.run_tool(action='read', query='powerwall', acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['device']['device'], 'My Home')
        rows = {r['entity_id']: r for r in res['device']['entities']}
        self.assertEqual(rows['sensor.powerwall_percentage_charged']['unit'], '%')
        self.assertIn('automation.charge_powerwall_nightly', [c['entity_id'] for c in res['other']],
                      'matches off the device are still shown, apart')
        self.assertEqual(self.calls, [])

    def test_a_query_across_two_devices_stays_ambiguous_but_groups_them(self):
        res = self.run_tool(action='read', query='garage')
        self.assertEqual(res['status'], 'ambiguous', res)
        self.assertEqual({d['device'] for d in res['devices']}, {'Kia EV9', 'My Home'})
        self.assertEqual(self.calls, [])

    def test_a_loose_word_never_drags_in_every_device_with_such_a_sensor(self):
        """Live 2026-10-29: 'powerwall battery' grouped 27 devices (phones, a mower, a siren)
        because any name with 'battery' scored above the fuzzy floor."""
        self.states.append({'entity_id': 'sensor.ev9_battery', 'state': '81', 'last_changed': '2026-10-29T06:00:00+00:00',
                            'attributes': {'friendly_name': 'Kia EV9 Battery', 'unit_of_measurement': '%',
                                           'device_class': 'battery'}})
        REGISTRY.append({'entity_id': 'sensor.ev9_battery', 'name': None, 'original_name': 'Battery', 'aliases': [],
                         'area_id': None, 'device_id': 'dev_ev9', 'hidden_by': None, 'disabled_by': None, 'platform': 'kia_uvo'})
        try:
            res = self.run_tool(action='find', query='powerwall battery')
            self.assertEqual([d['device'] for d in res['devices']], ['My Home'])
            res = self.run_tool(action='find', query='ev9 battery')
            self.assertEqual([d['device'] for d in res['devices']], ['Kia EV9'])
        finally:
            REGISTRY.pop()

    def test_candidate_rows_carry_unit_and_device_class_only_when_the_entity_has_them(self):
        row = self.run_tool(action='find', query='backup reserve')['candidates'][0]
        self.assertEqual((row['entity_id'], row['unit'], row['device_class']),
                         ('number.powerwall_backup_reserve', '%', 'battery'))
        lamp = self.run_tool(action='find', query='office lamp')['candidates'][0]
        self.assertNotIn('unit', lamp)
        self.assertNotIn('device_class', lamp)

    def test_a_device_with_too_many_entities_is_capped_with_a_count(self):
        for i in range(70):
            self.states.append({'entity_id': f'sensor.rack_{i}', 'state': str(i), 'last_changed': '2026-10-29T06:00:00+00:00',
                                'attributes': {'friendly_name': f'Rack Sensor {i}', 'unit_of_measurement': 'W'}})
            REGISTRY.append({'entity_id': f'sensor.rack_{i}', 'name': None, 'original_name': f'Sensor {i}', 'aliases': [],
                             'area_id': None, 'device_id': 'dev_rack', 'hidden_by': None, 'disabled_by': None, 'platform': 'x'})
        DEVICES.append({'id': 'dev_rack', 'name': 'Rack', 'area_id': None})
        try:
            dev = self.run_tool(action='find', query='rack sensor')['devices'][0]
            self.assertEqual(len(dev['entities']), 60)
            self.assertEqual(dev['more'], 10)
        finally:
            del REGISTRY[-70:]
            DEVICES.pop()

    def test_the_tool_and_the_prompt_say_a_device_is_many_sensors(self):
        tool = next(t for t in agent_tools_v2.get_available_tools() if t['name'] == 'house')
        self.assertIn('devices', tool['description'])
        self.assertIn('device_class', tool['description'])
        import inspect
        from services import agent_router
        self.assertIn('device_class', inspect.getsource(agent_router),
                      'the system prompt never tells the model to pick the sensor that fits the question')

    # --- read ---------------------------------------------------------------
    def test_read_gives_brightness_as_percent_and_never_a_token(self):
        res = self.run_tool(action='read', entity_id='light.office_lamp')
        self.assertEqual(res['status'], 'success')
        ent = res['entity']
        self.assertEqual(ent['state'], 'on')
        self.assertEqual(ent['ha_area'], 'Office')
        self.assertNotIn('area', ent)
        self.assertEqual(ent['brightness_pct'], 50)
        self.assertNotIn('access_token', ent['attributes'])
        self.assertNotIn(LAMP_TOKEN, repr(res))
        self.assertTrue(ent['exposed'])
        tv = self.run_tool(action='read', entity_id='media_player.office_tv_2')['entity']
        self.assertNotIn('entity_picture', tv['attributes'])
        self.assertNotIn('tv-token', repr(tv))

    def test_read_of_an_unexposed_entity_is_still_a_read(self):
        res = self.run_tool(action='read', entity_id='light.hall', acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success')
        self.assertFalse(res['entity']['exposed'])

    def test_an_ambiguous_query_returns_candidates_and_touches_nothing(self):
        res = self.run_tool(action='act', query='office', service='turn_off',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'ambiguous')
        self.assertGreater(len(res['candidates']), 1)
        self.assertEqual(self.calls, [])

    # --- history ------------------------------------------------------------
    def test_history_is_thinned_and_counts_changes(self):
        self.history_rows = [(f'2026-10-27T00:{i % 60:02d}:00+00:00', 'on' if i % 2 else 'off') for i in range(500)]
        res = self.run_tool(action='history', entity_id='light.office_lamp', hours=24)
        self.assertEqual(res['status'], 'success')
        self.assertLessEqual(len(res['points']), 50)
        self.assertEqual(res['changes'], 499)
        self.assertEqual(res['points'][0]['state'], 'off')
        self.assertEqual(res['points'][-1]['state'], 'on')

    # --- act ----------------------------------------------------------------
    def test_a_kid_can_turn_off_an_exposed_lamp_and_hears_the_state_after(self):
        res = self.run_tool(action='act', entity_id='light.office_lamp', service='turn_off',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls, [('light', 'turn_off', {'entity_id': 'light.office_lamp'})])
        self.assertEqual(res['state_after'], 'off')

    def test_brightness_rides_the_call_as_given(self):
        res = self.run_tool(action='act', query='office lamp', service='light.turn_on', data={'brightness_pct': 20},
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[0], ('light', 'turn_on', {'entity_id': 'light.office_lamp', 'brightness_pct': 20}))
        self.assertEqual(res['brightness_pct'], 20)

    def test_entity_id_in_data_never_overrides_the_resolved_entity(self):
        self.run_tool(action='act', entity_id='light.office_lamp', service='turn_off',
                      data={'entity_id': 'lock.front_door'}, acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(self.calls, [('light', 'turn_off', {'entity_id': 'light.office_lamp'})])

    def test_an_unexposed_light_is_refused_until_the_household_allows_it(self):
        res = self.run_tool(action='act', entity_id='light.hall', service='turn_on',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'refused')
        self.assertIn('not exposed', res['message'])
        self.assertIn('Config', res['message'])
        self.assertEqual(self.calls, [])
        self.settings['house_control_unexposed'] = True
        res = self.run_tool(action='act', entity_id='light.hall', service='turn_on',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['state_after'], 'on')

    def test_a_lock_needs_a_verified_parent_voice(self):
        res = self.run_tool(action='act', entity_id='lock.front_door', service='unlock',
                            voice_context=voice('named', {'id': 'p1', 'role': 'parent'}), source='voice')
        self.assertEqual(res['status'], 'refused')
        self.assertIn('parent', res['message'])
        self.assertEqual(self.calls, [])
        res = self.run_tool(action='act', entity_id='lock.front_door', service='unlock',
                            voice_context=voice('verified', {'id': 'p1', 'role': 'parent'}), source='voice')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['state_after'], 'unlocked')

    def test_a_verified_kid_voice_still_cannot_unlock(self):
        res = self.run_tool(action='act', entity_id='lock.front_door', service='unlock',
                            voice_context=voice('verified', {'id': 'k1', 'role': 'kid'}), source='voice')
        self.assertEqual(res['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_a_garage_door_needs_a_parent_but_a_blind_does_not(self):
        res = self.run_tool(action='act', entity_id='cover.main_garage', service='open_cover',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'refused')
        self.assertEqual(self.calls, [])
        res = self.run_tool(action='act', entity_id='cover.office_blind', service='open_cover',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        res = self.run_tool(action='act', entity_id='cover.main_garage', service='open_cover',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['state_after'], 'open')

    def test_the_admin_chat_counts_as_a_trusted_hand(self):
        res = self.run_tool(action='act', entity_id='lock.front_door', service='lock', source='admin')
        self.assertEqual(res['status'], 'success', res)

    def test_nobody_in_particular_is_not_a_trusted_hand(self):
        res = self.run_tool(action='act', entity_id='lock.front_door', service='lock')
        self.assertEqual(res['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_the_wall_panel_may_switch_a_light_but_never_unlock_the_door(self):
        from services import access
        res = self.run_tool(action='act', entity_id='light.office_lamp', service='turn_off',
                            acting_member=access.HOUSE, source='panel')
        self.assertEqual(res['status'], 'success', res)
        res = self.run_tool(action='act', entity_id='lock.front_door', service='unlock',
                            acting_member=access.HOUSE, source='panel')
        self.assertEqual(res['status'], 'refused', 'the wall panel reads as an adult but is a room anyone can walk into')
        self.assertEqual(self.calls, [('light', 'turn_off', {'entity_id': 'light.office_lamp'})])
        res = self.run_tool(action='act', entity_id='cover.main_garage', service='open_cover',
                            acting_member=access.HOUSE_PARENT, source='panel')
        self.assertEqual(res['status'], 'refused')

    def test_an_unknown_voice_may_still_switch_a_light(self):
        res = self.run_tool(action='act', entity_id='light.office_lamp', service='turn_off',
                            voice_context=voice('unknown'), source='voice')
        self.assertEqual(res['status'], 'success', res)

    def test_a_service_the_entity_does_not_have_is_an_error_and_calls_nothing(self):
        res = self.run_tool(action='act', entity_id='light.office_lamp', service='unlock',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'error')
        self.assertEqual(self.calls, [])
        res = self.run_tool(action='act', entity_id='light.office_lamp', service='lock.turn_off',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'error', 'a service from another domain was accepted')
        self.assertEqual(self.calls, [])

    # --- locate -------------------------------------------------------------
    def test_locate_a_car_answers_its_zone_and_address_never_its_ha_room(self):
        """Device run 2026-10-27: "where is the Kia EV9" came back "in the Garage",
        the HA area of forty EV9 entities, while the tracker said home and the
        geocoded sensor named the street."""
        res = self.run_tool(action='locate', query='Kia EV9')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['entity_id'], 'device_tracker.ev9_location')
        self.assertEqual(res['zone'], 'home')
        self.assertEqual(res['address'], EV9_ADDRESS)
        self.assertEqual((res['latitude'], res['longitude']), (35.780736, -78.915669))
        self.assertEqual(res['last_updated'], '2026-10-27T14:13:16+00:00')
        self.assertNotIn('Garage', res['message'])
        self.assertIn('home', res['message'].lower())
        self.assertIn('Maple Lane', res['message'])
        self.assertEqual(self.geocoded, [], 'a geocoded sensor on the same device beats a lookup')

    def test_locate_away_without_a_geocoded_sensor_reverse_geocodes(self):
        res = self.run_tool(action='locate', query='van')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['zone'], 'not_home')
        self.assertEqual(res['address'], 'Target, 12 Elm St, Cary')
        self.assertEqual(self.geocoded, [(35.79, -78.78)])
        self.assertIn('Target', res['message'])

    def test_locate_never_answers_from_a_non_tracker(self):
        res = self.run_tool(action='locate', query='office lamp')
        self.assertEqual(res['status'], 'error')
        self.assertIn('location', res['message'].lower())
        self.assertEqual(self.geocoded, [])

    def test_locate_by_entity_id_works_too(self):
        res = self.run_tool(action='locate', entity_id='device_tracker.van')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['zone'], 'not_home')

    def test_the_tool_tells_the_model_the_room_is_not_a_location(self):
        tool = next(t for t in agent_tools_v2.get_available_tools() if t['name'] == 'house')
        self.assertIn('locate', tool['parameters']['properties']['action']['enum'])
        self.assertIn('ha_area', tool['description'])
        self.assertIn('locate', tool['description'])

    # --- locate people ------------------------------------------------------
    def test_a_first_name_finds_the_ha_person_and_answers_from_their_phone(self):
        """Device run 2026-10-27: "where is Lorena" said there was no location
        tracker, while person.lorena_wilson sat there with her phone attached."""
        res = self.run_tool(action='locate', query='Lorena', acting_member={'id': 'p9', 'role': 'parent'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['entity_id'], 'person.lorena_wilson')
        self.assertEqual(res['zone'], 'home')
        self.assertEqual(res['source'], "Lorena's Phone")
        self.assertIn('home', res['message'].lower())
        self.assertEqual(self.geocoded, [], 'nobody needs a street address for home')

    def test_a_spoken_alias_resolves_through_the_family_member(self):
        res = self.run_tool(action='locate', query='mom', acting_member={'id': 'k1', 'role': 'child'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['entity_id'], 'person.lorena_wilson')

    def test_a_person_beats_their_own_phones_and_away_gets_an_address(self):
        res = self.run_tool(action='locate', query='Jeff', acting_member={'id': 'p9', 'role': 'parent'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['entity_id'], 'person.jeff_wilson_2', 'the person entity, not one of the two phones')
        self.assertEqual(res['zone'], 'not_home')
        self.assertEqual(res['address'], 'Target, 12 Elm St, Cary')
        self.assertEqual(self.geocoded, [(35.81, -78.81)])
        self.assertIn('Jeff Wilson', res['message'])

    def test_naming_the_phone_itself_still_finds_the_phone(self):
        res = self.run_tool(action='locate', query="Jeff's phone", acting_member={'id': 'p9', 'role': 'parent'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['entity_id'], 'device_tracker.jeff_phone')

    def test_a_person_with_no_tracker_says_exactly_that_and_never_answers_with_the_bus(self):
        res = self.run_tool(action='locate', query='Lily', acting_member={'id': 'p9', 'role': 'parent'})
        self.assertEqual(res['status'], 'error')
        self.assertIn('person.lily', res['message'])
        self.assertIn('no device tracker', res['message'].lower())
        self.assertNotIn('bus', res['message'].lower())
        self.assertEqual(self.geocoded, [])

    def test_a_family_member_unknown_to_ha_is_told_apart_from_an_unknown_name(self):
        res = self.run_tool(action='locate', query='James', acting_member={'id': 'p9', 'role': 'parent'})
        self.assertEqual(res['status'], 'error')
        self.assertIn('James', res['message'])
        self.assertIn('person', res['message'].lower(), 'the fix is to link a person entity to James in Chauffeur or HA')
        self.assertNotIn('bus', res['message'].lower())

    def test_a_child_who_keeps_location_private_is_hidden_from_everyone_but_a_parent(self):
        self.states.append({'entity_id': 'device_tracker.lily_phone', 'state': 'not_home',
                            'last_changed': '2026-10-27T15:00:00+00:00',
                            'attributes': {'friendly_name': "Lily's Phone", 'source_type': 'gps',
                                           'latitude': 35.76, 'longitude': -78.96}})
        for st in self.states:
            if st['entity_id'] == 'person.lily':
                st['state'] = 'not_home'
                st['attributes'].update(device_trackers=['device_tracker.lily_phone'], source='device_tracker.lily_phone',
                                        latitude=35.76, longitude=-78.96)
        self.private_location.add('m_lily')
        from services import access
        for who, src in (({'id': 'k2', 'role': 'child'}, 'pwa'), (access.HOUSE, 'panel'), (None, 'voice')):
            res = self.run_tool(action='locate', query='Lily', acting_member=who, source=src,
                                voice_context=voice('unknown') if src == 'voice' else None)
            self.assertEqual(res['status'], 'refused', (who, src, res))
            self.assertIn('private', res['message'].lower())
            self.assertNotIn('35.76', repr(res))
        res = self.run_tool(action='locate', query='Lily', acting_member={'id': 'p9', 'role': 'parent'}, source='pwa')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['zone'], 'not_home')
        self.assertEqual(self.geocoded, [(35.76, -78.96)])
        # Her phone is her whereabouts too: asking for the device is asking for her.
        self.geocoded.clear()
        res = self.run_tool(action='locate', query="Lily's phone", acting_member={'id': 'k2', 'role': 'child'}, source='pwa')
        self.assertEqual(res['status'], 'refused', res)
        self.assertNotIn('35.76', repr(res))
        res = self.run_tool(action='locate', entity_id='device_tracker.lily_phone', acting_member=None, source='panel')
        self.assertEqual(res['status'], 'refused', res)
        res = self.run_tool(action='locate', query="Lily's phone", acting_member={'id': 'p9', 'role': 'parent'}, source='pwa')
        self.assertEqual(res['status'], 'success', res)

    # --- app ----------------------------------------------------------------
    def test_find_lists_the_apps_a_tv_can_open(self):
        rows = {c['entity_id']: c for c in self.run_tool(action='find', query='office tv')['candidates']}
        self.assertEqual(rows['remote.office_tv']['apps'], list(TV_APPS))
        self.assertNotIn('apps', rows['media_player.office_tv_2'])
        lamp = self.run_tool(action='find', query='office lamp')['candidates'][0]
        self.assertNotIn('apps', lamp)

    def test_a_spoken_app_name_becomes_the_package_id_on_the_remote(self):
        res = self.run_tool(action='app', query='office tv', app='netflix', acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        # DEVICE-FOUND 2026-10-28: a package id launches nothing on a Google TV; the link does.
        self.assertEqual(self.calls, [('remote', 'turn_on', {'entity_id': 'remote.office_tv',
                                                             'activity': 'https://www.netflix.com/browse'})])
        self.assertEqual(res['entity_id'], 'remote.office_tv')
        self.assertEqual(res['app'], 'Netflix')
        self.assertEqual(res['app_id'], 'com.netflix.ninja')
        self.assertEqual(res['sent'], 'https://www.netflix.com/browse')
        self.assertTrue(res['landed'])
        self.assertIn('Netflix', res['message'])
        self.assertIn('Office TV', res['message'])

    def test_the_ways_people_say_an_app_all_land_on_the_right_package(self):
        for spoken, package, link in (
                ('Disney Plus', 'com.disney.disneyplus', 'https://www.disneyplus.com'),
                ('prime', 'com.amazon.amazonvideo.livingroom', 'https://app.primevideo.com'),
                ('HBO Max', 'com.wbd.stream', 'https://play.max.com'),
                ('you tube', 'com.google.android.youtube.tv', 'https://www.youtube.com'),
                ('paramount', 'com.cbs.ott', 'https://www.paramountplus.com'),
                ('YouTube TV', 'com.google.android.youtube.tvunplugged', 'https://tv.youtube.com'),
                ('the Hulu app', 'com.hulu.livingroomplus', 'https://www.hulu.com'),
                ('plex', 'com.plexapp.android', 'https://app.plex.tv'),
                ('kodi', 'org.xbmc.kodi', 'org.xbmc.kodi')):          # no link known: the package goes
            self.calls.clear()
            res = self.run_tool(action='app', entity_id='remote.office_tv', app=spoken,
                                acting_member={'id': 'k1', 'role': 'kid'})
            self.assertEqual(res['status'], 'success', (spoken, res))
            self.assertEqual(self.calls[0][2]['activity'], link, spoken)
            self.assertEqual(res['app_id'], package, spoken)

    def test_a_package_id_or_a_link_is_sent_as_given(self):
        res = self.run_tool(action='app', entity_id='remote.office_tv', app='tv.twitch.android.app',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[0][2]['activity'], 'tv.twitch.android.app')
        res = self.run_tool(action='app', entity_id='remote.office_tv', app='https://www.netflix.com/title/80057281',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[1][2]['activity'], 'https://www.netflix.com/title/80057281')

    def test_a_launch_that_lands_in_the_browser_says_the_app_may_be_missing(self):
        """Live 2026-10-28: Hulu's link opened the TV's browser; HA said success all the same."""
        self.tv_opens_browser = True
        res = self.run_tool(action='app', entity_id='remote.office_tv', app='hulu',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.assertFalse(res['landed'])
        self.assertIn('browser', res['message'])
        self.assertIn('not be installed', res['message'])

    def test_an_app_only_ha_knows_is_sent_under_the_name_ha_lists(self):
        res = self.run_tool(action='app', entity_id='remote.office_tv', app='sling',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[0][2]['activity'], 'Sling TV')
        self.assertEqual(res['app'], 'Sling TV')

    def test_an_unknown_app_is_an_error_that_names_what_the_tv_has_and_touches_nothing(self):
        res = self.run_tool(action='app', entity_id='remote.office_tv', app='nintendo',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'error')
        self.assertIn('nintendo', res['message'])
        self.assertIn('Netflix', res['message'])
        self.assertEqual(self.calls, [])
        res = self.run_tool(action='app', entity_id='remote.office_tv', app='', acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'error')
        self.assertEqual(self.calls, [])

    def test_the_media_player_twin_or_the_room_finds_the_remote(self):
        res = self.run_tool(action='app', entity_id='media_player.office_tv_2', app='netflix',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['entity_id'], 'remote.office_tv')
        self.calls.clear()
        res = self.run_tool(action='app', query='office', app='youtube', acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[0][2]['entity_id'], 'remote.office_tv')

    def test_part_of_a_tvs_name_is_enough_when_it_fits_one_tv(self):
        """Live 2026-10-28: 'pool house' found no TV while the Pool House Lounge TV sat there."""
        res = self.run_tool(action='app', query='living', app='netflix', acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'refused', res)   # unexposed, but it was FOUND
        self.assertIn('Living Room TV', res['message'])
        self.assertEqual(self.calls, [])

    def test_a_tv_without_an_app_list_is_never_an_app_target(self):
        res = self.run_tool(action='app', query='living room apple tv', app='netflix',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'error', res)
        self.assertIn('Android TV', res['message'])
        self.assertEqual(self.calls, [])
        res = self.run_tool(action='app', query='office lamp', app='netflix', acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'error', res)
        self.assertEqual(self.calls, [])

    def test_a_tv_counts_as_exposed_when_either_twin_is(self):
        # remote.office_tv is not exposed; its media_player twin is. The TV is one thing.
        res = self.run_tool(action='app', entity_id='remote.office_tv', app='netflix',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.calls.clear()
        res = self.run_tool(action='app', query='living room tv', app='netflix',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'refused', res)
        self.assertIn('not exposed', res['message'])
        self.assertEqual(self.calls, [])
        self.settings['house_control_unexposed'] = True
        res = self.run_tool(action='app', query='living room tv', app='netflix',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[0][2]['entity_id'], 'remote.living_room_tv')

    def test_an_offline_android_tv_is_offline_not_a_non_tv(self):
        """Live 2026-10-28: the Sunroom TV was unavailable, carried no app list, and was called
        'not an Android TV' while it sat in the Android TV Remote integration."""
        res = self.run_tool(action='app', query='sunroom tv', app='netflix', acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'error', res)
        self.assertIn('offline', res['message'])
        self.assertNotIn('not an Android TV', res['message'])
        self.assertEqual(self.calls, [])

    def test_a_tv_already_on_the_app_never_counts_as_a_landing(self):
        """Live 2026-10-28: 'open DIRECTV' on a TV already on DIRECTV read as landed although
        the launch itself had changed nothing."""
        res = self.run_tool(action='app', entity_id='remote.office_tv', app='directv',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['app_id'], 'com.att.tv')
        self.assertFalse(res['landed'])
        self.assertTrue(res['already'])
        self.assertIn('already', res['message'])

    def test_reading_a_tv_stitches_its_faces_into_what_is_on(self):
        """Device 2026-10-28: the remote knows the app, the Cast entity in the same room knows the
        title; a read of either TV face answers with both."""
        for s in self.states:
            if s['entity_id'] == 'remote.office_tv':
                s['attributes']['current_activity'] = 'YouTube'
            if s['entity_id'] == 'media_player.office_tv_2':
                s['attributes'].update(app_id='com.google.android.youtube.tv', app_name='YouTube')
        for eid in ('remote.office_tv', 'media_player.office_tv_2'):
            res = self.run_tool(action='read', entity_id=eid)
            self.assertEqual(res['status'], 'success', res)
            tv = res['entity']['tv']
            self.assertEqual(tv['app'], 'YouTube')
            self.assertEqual(tv['title'], 'Peppa Pig Tales')
            self.assertEqual(tv['state'], 'playing')
            self.assertIn('YouTube', tv['message'])
            self.assertIn('Peppa Pig', tv['message'])
        lamp = self.run_tool(action='read', entity_id='light.office_lamp')['entity']
        self.assertNotIn('tv', lamp)

    def test_the_answer_is_honest_when_the_tv_does_not_report_the_app(self):
        self.tv_ignores_launches = True
        res = self.run_tool(action='app', entity_id='remote.office_tv', app='netflix',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.assertFalse(res['landed'])
        self.assertNotIn('is on Netflix', res['message'])
        self.assertIn('asked', res['message'].lower())

    def test_app_is_declared_and_reaches_the_tool_from_every_surface(self):
        tool = next(t for t in agent_tools_v2.get_available_tools() if t['name'] == 'house')
        self.assertIn('app', tool['parameters']['properties']['action']['enum'])
        self.assertIn('app', tool['parameters']['properties'])
        self.assertIn('Netflix', tool['description'])
        res = agent_tools_v2.execute_tool('house', {'action': 'app', 'query': 'office tv', 'app': 'netflix',
                                                    'acting_member': {'id': 'x', 'role': 'kid'}})
        self.assertEqual(res['status'], 'success', res)
        from services import voice_tools
        recorded = []
        self.orig[(voice_tools, 'record_action')] = voice_tools.record_action
        voice_tools.record_action = lambda ctx, name, principal=None, details=None, provenance=None: recorded.append(name)
        ctx = voice('unknown')
        ctx.ha_instance_id, ctx.service_revision = '', ''
        ctx.provenance = lambda: {}
        res = voice_tools.dispatch('house', {'action': 'app', 'query': 'office tv', 'app': 'disney plus'}, ctx)
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(recorded, ['house'])
        self.assertEqual(self.calls[-1][2]['activity'], 'https://www.disneyplus.com')
        self.assertEqual(res['app_id'], 'com.disney.disneyplus')
        import inspect
        from services import agent_router
        src = inspect.getsource(agent_router)
        branch = src[src.index("elif func_name == 'house':"):]
        self.assertIn("'app'", branch[:600], 'the chat router drops the app argument before it reaches the tool')
        self.assertIn("action='app'", src, 'the system prompt never tells the model how to open an app')

    # --- degradation --------------------------------------------------------
    def test_no_home_assistant_means_a_plain_error_for_every_action(self):
        setattr(ha_api, 'mode', lambda: 'unconfigured')
        for action in ('find', 'read', 'history', 'act', 'locate', 'app'):
            res = self.run_tool(action=action, query='office lamp', entity_id='light.office_lamp', service='turn_off',
                                app='netflix', acting_member={'id': 'p1', 'role': 'parent'})
            self.assertEqual(res['status'], 'error', action)
            self.assertIn('not connected', res['message'])
        self.assertEqual(self.calls, [])

    def test_an_unknown_action_is_an_error(self):
        self.assertEqual(self.run_tool(action='dance', query='x')['status'], 'error')

    # --- wiring -------------------------------------------------------------
    def test_the_tool_is_declared_once_and_runs_through_execute_tool(self):
        names = [t['name'] for t in agent_tools_v2.get_available_tools()]
        self.assertEqual(names.count('house'), 1)
        res = agent_tools_v2.execute_tool('house', {'action': 'read', 'entity_id': 'light.office_lamp',
                                                    'acting_member': {'id': 'x', 'role': 'parent'}})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['entity']['brightness_pct'], 50)

    def test_voice_dispatch_reaches_the_tool_and_records_the_act(self):
        from services import voice_tools
        self.assertIn('house', voice_tools.TOOLS)
        recorded = []
        self.orig[(voice_tools, 'record_action')] = voice_tools.record_action
        voice_tools.record_action = lambda ctx, name, principal=None, details=None, provenance=None: recorded.append(name)
        ctx = voice('unknown')
        ctx.ha_instance_id, ctx.service_revision = '', ''
        ctx.provenance = lambda: {}
        res = voice_tools.dispatch('house', {'action': 'act', 'entity_id': 'light.office_lamp', 'service': 'turn_off'}, ctx)
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(recorded, ['house'])
        res = voice_tools.dispatch('house', {'action': 'read', 'entity_id': 'light.office_lamp'}, ctx)
        self.assertEqual(res['status'], 'success', res)


if __name__ == '__main__':
    unittest.main()
