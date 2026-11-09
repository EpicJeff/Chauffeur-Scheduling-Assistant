"""What a control request touches (Task 2 of
docs/superpowers/plans/2026-11-09-ha-control-permissions.md).

A scene or script is judged by what it reaches, not by its own domain: a
"Goodnight" script that locks the doors follows the Locks rule. Scenes list
their entities in state; scripts are read through Home Assistant's
`search/related` (the panel behind a script's "Related" tab) unioned with
their own config. Anything that cannot be read makes the script count as
touching EVERY kind, so it passes only when every kind would.

Stubbed ha_api; the real control_scripts and control_rules.

Run from chauffeur/:  python tests/test_control_scripts.py
"""
import copy
import unittest

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import control_rules as cr
from services import control_scripts as cs
from services import ha_api
from services.control_rules import Who

CHILD = Who(role='child', member_id='kid-1', place=None, proven=True)
PARENT = Who(role='parent', member_id='mum-1', place=None, proven=True)


def state(eid, **attrs):
    return {'entity_id': eid, 'state': 'on', 'attributes': attrs}


STATES = [
    state('light.a'),
    state('light.hall'),
    state('lock.front'),
    state('lock.side'),
    state('cover.garage_door', device_class='garage'),
    state('cover.office_shade', device_class='shade'),
    state('scene.night', entity_id=['light.a', 'lock.front']),
    state('scene.movie', entity_id=['light.a']),
    state('script.goodnight', friendly_name='Goodnight'),
    state('script.lights_only', friendly_name='Lights only'),
    state('script.a', friendly_name='A'),
    state('script.b', friendly_name='B'),
    state('script.templated', friendly_name='Templated'),
    state('script.gate', friendly_name='Gate'),
    state('script.chatty', friendly_name='Chatty'),
    state('script.quiet', friendly_name='Quiet'),
    state('script.open_garage', friendly_name='Open garage'),
]
ENTITY_REGISTRY = [
    {'entity_id': 'cover.garage_door', 'device_id': 'dev-garage', 'area_id': None},
    {'entity_id': 'lock.side', 'device_id': None, 'area_id': 'garage_area'},
]
DEVICE_REGISTRY = [{'id': 'dev-garage', 'name': 'Garage opener', 'area_id': None}]
AREAS = [{'id': 'garage_area', 'name': 'Garage', 'entities': ['lock.side']},
         {'id': 'kitchen', 'name': 'Kitchen', 'entities': ['light.a', 'lock.front']}]

# What HA's search/related answers, keyed by the FULL script entity id.
RELATED = {
    'script.goodnight': {'entity': ['light.a'], 'device': ['dev-garage'], 'area': ['garage_area']},
    'script.lights_only': {'entity': ['light.hall']},
    'script.a': {'script': ['script.b'], 'entity': ['light.a']},
    'script.b': {'script': ['script.a'], 'entity': ['lock.front']},
    'script.templated': {},
    'script.gate': {},
    'script.chatty': {},
    'script.quiet': {},
    'script.open_garage': {'entity': ['cover.garage_door']},
}
CONFIGS = {
    'goodnight': {'sequence': [{'service': 'light.turn_off', 'target': {'entity_id': 'light.a'}}]},
    'lights_only': {'sequence': [
        {'delay': '00:00:05'},
        {'service': 'notify.mobile', 'data': {'message': 'night'}},
        {'service': 'light.turn_on', 'target': {'entity_id': 'light.hall'}}]},
    'a': {'sequence': [{'service': 'script.b'}]},
    'b': {'sequence': [{'service': 'script.a'}, {'service': 'lock.lock', 'target': {'entity_id': 'lock.front'}}]},
    'templated': {'sequence': [{'service': 'lock.unlock',
                                'target': {'entity_id': '{{ states("input_text.which_door") }}'}}]},
    'gate': {'sequence': [{'service': 'rest_command.open_gate'}]},
    'chatty': {'sequence': [{'service': 'conversation.process', 'data': {'text': 'open the garage'}}]},
    # HA's search can answer empty for a script it has not indexed; the config still names the lock.
    'quiet': {'sequence': [{'action': 'lock.unlock', 'target': {'entity_id': 'lock.side'}}]},
    'open_garage': {'sequence': [{'service': 'cover.open_cover', 'target': {'entity_id': 'cover.garage_door'}}]},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.orig = {name: getattr(ha_api, name) for name in (
            'mode', 'get_states', 'get_entity_registry', 'get_device_registry', 'get_area_map',
            'ws_command', 'get_script_config')
            if hasattr(ha_api, name)}
        self.ws_calls = []
        ha_api.mode = lambda: 'direct'
        ha_api.get_states = lambda ttl=5: copy.deepcopy(STATES)
        ha_api.get_entity_registry = lambda ttl=300: copy.deepcopy(ENTITY_REGISTRY)
        ha_api.get_device_registry = lambda ttl=300: copy.deepcopy(DEVICE_REGISTRY)
        ha_api.get_area_map = lambda ttl=60: copy.deepcopy(AREAS)

        def ws(command, timeout=8, **fields):
            self.ws_calls.append((command, fields))
            if command == 'search/related':
                return copy.deepcopy(RELATED.get(fields.get('item_id'), {}))
            return None
        ha_api.ws_command = ws
        ha_api.get_script_config = lambda object_id: copy.deepcopy(CONFIGS.get(object_id))
        cs.clear_cache()
        self.rules = cr.default_rules({})

    def tearDown(self):
        for name, fn in self.orig.items():
            setattr(ha_api, name, fn)
        cs.clear_cache()


class Scenes(Base):
    def test_scene_reads_entity_list(self):
        touched, reasons = cs.touched('scene.night')
        self.assertEqual(touched, {'light.a', 'lock.front'})
        self.assertEqual(reasons, [])
        kinds = set(cr.kinds_for(['scene.night']))
        self.assertTrue({'lights', 'locks'} <= kinds, kinds)
        self.assertEqual(set(cr.kinds_for(['scene.movie'])), {'lights'})


class Scripts(Base):
    def test_search_uses_full_entity_id(self):
        cs.touched('script.goodnight')
        related = [f for c, f in self.ws_calls if c == 'search/related']
        self.assertTrue(related, 'search/related was never asked')
        self.assertEqual(related[0].get('item_type'), 'script')
        self.assertEqual(related[0].get('item_id'), 'script.goodnight')

    def test_script_via_search_related(self):
        touched, reasons = cs.touched('script.goodnight')
        self.assertTrue({'light.a', 'cover.garage_door', 'lock.side'} <= touched, touched)
        self.assertEqual(reasons, [])
        self.assertTrue({'lights', 'garage', 'locks'} <= set(cr.kinds_for(['script.goodnight'])))

    def test_config_targets_are_unioned(self):
        touched, reasons = cs.touched('script.quiet')
        self.assertIn('lock.side', touched)
        self.assertIn('locks', cr.kinds_for(['script.quiet']))

    def test_script_calls_script_and_cycles_end(self):
        kinds = set(cr.kinds_for(['script.a']))
        self.assertIn('locks', kinds)
        self.assertIn('lights', kinds)

    def test_harmless_actions_ignored(self):
        touched, reasons = cs.touched('script.lights_only')
        self.assertEqual(reasons, [])
        self.assertEqual(set(cr.kinds_for(['script.lights_only'])), {'lights'})
        self.assertTrue(cr.check(CHILD, ['script.lights_only'], {'ha_control': self.rules}).allowed)


class Unreadable(Base):
    def assertEveryKind(self, eid):
        self.assertEqual(set(cr.kinds_for([eid])), set(cr.KINDS), eid)

    def test_template_target_unreadable(self):
        _, reasons = cs.touched('script.templated')
        self.assertTrue(any('template' in r.lower() for r in reasons), reasons)
        self.assertEveryKind('script.templated')

    def test_rest_command_unreadable(self):
        _, reasons = cs.touched('script.gate')
        self.assertTrue(any('rest_command' in r for r in reasons), reasons)
        self.assertEveryKind('script.gate')

    def test_conversation_process_unreadable(self):
        _, reasons = cs.touched('script.chatty')
        self.assertTrue(reasons)
        self.assertEveryKind('script.chatty')

    def test_unreadable_is_every_kind(self):
        rules = copy.deepcopy(self.rules)
        rules['people']['child']['alarm'] = 'yes'      # children may use the alarm, not the locks
        settings = {'ha_control': rules}
        self.assertFalse(cr.check(CHILD, ['script.gate'], settings).allowed)
        # A parent with every kind allowed and signed in passes it.
        self.assertTrue(cr.check(PARENT, ['script.gate'], settings).allowed)

    def test_no_ha(self):
        ha_api.mode = lambda: 'unconfigured'
        ha_api.ws_command = lambda command, timeout=8, **fields: None
        ha_api.get_states = lambda ttl=5: []
        ha_api.get_script_config = lambda object_id: None
        cs.clear_cache()
        touched, reasons = cs.touched('script.goodnight')
        self.assertEqual(touched, set())
        self.assertTrue(reasons)
        decision = cr.check(CHILD, ['script.goodnight'], {'ha_control': self.rules})
        self.assertFalse(decision.allowed)

    def test_check_never_raises(self):
        def boom(*a, **k):
            raise RuntimeError('HA fell over')
        ha_api.get_states = boom
        ha_api.ws_command = boom
        cs.clear_cache()
        decision = cr.check(CHILD, ['script.goodnight', 'lock.front'], {'ha_control': self.rules})
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.message.strip())

    def test_unreadable_scripts_list(self):
        rows = cs.unreadable_scripts()
        by_id = {r['entity_id']: r for r in rows}
        self.assertEqual(set(by_id), {'script.templated', 'script.gate', 'script.chatty'})
        self.assertEqual(by_id['script.gate']['name'], 'Gate')
        for row in rows:
            self.assertTrue(row['reason'].strip())


class Targets(Base):
    def test_targets_area_and_list(self):
        self.assertEqual(cr.targets({'area_id': 'kitchen'}), {'light.a', 'lock.front'})
        self.assertEqual(cr.targets({'entity_id': ['light.a', 'lock.front']}), {'light.a', 'lock.front'})
        self.assertEqual(cr.targets({'entity_id': 'light.a'}), {'light.a'})
        self.assertEqual(cr.targets({'device_id': 'dev-garage'}), {'cover.garage_door'})
        self.assertEqual(cr.targets({'target': {'area_id': ['garage_area']}}), {'lock.side'})
        settings = {'ha_control': self.rules}
        self.assertFalse(cr.check(CHILD, cr.targets({'area_id': 'kitchen'}), settings).allowed)
        self.assertTrue(cr.check(CHILD, cr.targets({'entity_id': 'light.a'}), settings).allowed)

    def test_entity_kinds_use_live_attributes(self):
        self.assertEqual(cr.kinds_for(['cover.office_shade']), ('blinds',))
        self.assertEqual(cr.kinds_for(['cover.garage_door']), ('garage',))
        # Not in state at all: unread, so a cover is judged as the garage.
        self.assertEqual(cr.kinds_for(['cover.unknown']), ('garage',))


if __name__ == '__main__':
    unittest.main()
