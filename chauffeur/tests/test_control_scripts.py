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
# check() applies each person's own scope too, so the people must exist.
from services import storage  # noqa: E402
for _mid, _role in (('kid-1', 'child'), ('mum-1', 'parent')):
    if not storage.get_member(_mid):
        storage.add_member({'id': _mid, 'name': _mid, 'role': _role, 'status': 'active'})


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
    state('script.mixed', friendly_name='Mixed'),
    state('script.labelled', friendly_name='Labelled'),
    state('script.legacy', friendly_name='Legacy'),
    state('script.no_config', friendly_name='No config'),
    state('script.kitchen_off', friendly_name='Kitchen off'),
    state('script.device_action', friendly_name='Device action'),
    state('script.ha_generic', friendly_name='HA generic'),
    state('script.trigger_auto', friendly_name='Trigger automation'),
    state('script.group_on', friendly_name='Group on'),
    state('script.svc_template', friendly_name='Service template'),
    state('script.scene_short', friendly_name='Scene shorthand'),
    state('script.csv', friendly_name='CSV'),
    state('script.fires_event', friendly_name='Fires event'),
    state('automation.unlock_front'),
    state('group.garage', entity_id=['cover.garage_door']),
    state('sensor.kitchen_temp'),
    state('lock.kitchen_door'),
    state('light.kitchen'),
]
ENTITY_REGISTRY = [
    {'entity_id': 'cover.garage_door', 'device_id': 'dev-garage', 'area_id': None},
    {'entity_id': 'sensor.garage_temp', 'device_id': 'dev-garage', 'area_id': None},
    {'entity_id': 'lock.side', 'device_id': None, 'area_id': 'garage_area'},
]
DEVICE_REGISTRY = [{'id': 'dev-garage', 'name': 'Garage opener', 'area_id': None}]
AREAS = [{'id': 'garage_area', 'name': 'Garage', 'entities': ['lock.side']},
         {'id': 'kitchen', 'name': 'Kitchen', 'entities': ['light.a', 'lock.front']},
         {'id': 'kitchen2', 'name': 'Kitchen two',
          'entities': ['light.kitchen', 'sensor.kitchen_temp', 'lock.kitchen_door']}]

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
    'script.mixed': {'entity': ['light.a']},
    'script.labelled': {},
    'script.legacy': {},
    'script.no_config': {},
    # HA's search resolves UPWARD: the room and device of a referenced light come back too.
    'script.kitchen_off': {'entity': ['light.kitchen'], 'area': ['kitchen2'], 'device': ['dev-garage']},
    'script.device_action': {'device': ['dev-garage']},
    'script.ha_generic': {'entity': ['light.a']},
    'script.trigger_auto': {'entity': ['automation.unlock_front']},
    'script.group_on': {'entity': ['group.garage']},
    'script.svc_template': {},
    'script.scene_short': {},
    'script.csv': {'entity': ['light.a']},
    'script.fires_event': {},
}
CONFIGS = {
    'goodnight': {'sequence': [
        {'service': 'light.turn_off', 'target': {'entity_id': 'light.a'}},
        {'service': 'cover.close_cover', 'target': {'device_id': 'dev-garage'}},
        {'service': 'lock.lock', 'target': {'area_id': 'garage_area'}}]},
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
    # A readable light step must not vouch for an unread scene step.
    'mixed': {'sequence': [
        {'service': 'light.turn_on', 'target': {'entity_id': 'light.a'}},
        {'service': 'scene.apply', 'data': {'entities': {'lock.front': 'unlocked'}}}]},
    'labelled': {'sequence': [
        {'service': 'light.turn_on', 'target': {'entity_id': 'light.a', 'label_id': 'doors'}}]},
    'legacy': {'sequence': [
        {'service': 'lock.unlock', 'data_template': {'entity_id': '{{ states("input_text.d") }}'}}]},
    'kitchen_off': {'sequence': [{'service': 'light.turn_off', 'target': {'entity_id': 'light.kitchen'}}]},
    'device_action': {'sequence': [
        {'type': 'open', 'device_id': 'dev-garage', 'entity_id': '4f1c2d3e5a6b7c8d9e0f', 'domain': 'cover'}]},
    'ha_generic': {'sequence': [{'service': 'homeassistant.turn_off', 'target': {'entity_id': 'light.a'}}]},
    'trigger_auto': {'sequence': [
        {'service': 'automation.trigger', 'target': {'entity_id': 'automation.unlock_front'}}]},
    'group_on': {'sequence': [
        {'service': 'homeassistant.turn_on', 'target': {'entity_id': 'group.garage'}}]},
    'svc_template': {'sequence': [{'service_template': '{{ "script.open_garage" }}'}]},
    'scene_short': {'sequence': [{'scene': 'scene.night'}]},
    # HA splits a comma-separated entity_id string (cv.comp_entity_ids).
    'csv': {'sequence': [{'action': 'light.turn_on', 'target': {'entity_id': 'light.a, LOCK.Front'}}]},
    'fires_event': {'sequence': [{'event': 'unlock_requested', 'event_data': {'door': 'front'}}]},
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
            if command == 'script/config':
                object_id = str(fields.get('entity_id', '')).partition('.')[2]
                config = CONFIGS.get(object_id)
                return {'config': copy.deepcopy(config)} if config is not None else None
            return None
        ha_api.ws_command = ws
        ha_api.get_script_config = lambda object_id: None
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
        self.assertEqual(set(by_id), {'script.templated', 'script.gate', 'script.chatty',
                                      'script.labelled', 'script.legacy', 'script.no_config',
                                      'script.trigger_auto', 'script.group_on', 'script.svc_template',
                                      'script.fires_event'})
        self.assertEqual(by_id['script.gate']['name'], 'Gate')
        for row in rows:
            self.assertTrue(row['reason'].strip())


class ReviewRound1(Base):
    """Findings from the Claude review of Task 2, each a way past the rules."""

    def test_config_read_through_websocket_wrapper(self):
        # Live HA answers script/config as {'config': ...}; REST answers nothing here.
        _, reasons = cs.touched('script.gate')
        self.assertTrue(any('rest_command' in r for r in reasons), reasons)
        self.assertEqual(set(cr.kinds_for(['script.chatty'])), set(cr.KINDS))

    def test_rest_fallback_still_works(self):
        ha_api.ws_command = lambda command, timeout=8, **fields: (
            copy.deepcopy(RELATED.get(fields.get('item_id'), {})) if command == 'search/related' else None)
        ha_api.get_script_config = lambda object_id: copy.deepcopy(CONFIGS.get(object_id))
        cs.clear_cache()
        _, reasons = cs.touched('script.gate')
        self.assertTrue(any('rest_command' in r for r in reasons), reasons)

    def test_config_unreadable_is_unreadable(self):
        # Neither websocket nor REST can read the steps: never "touches nothing".
        self.assertEqual(set(cr.kinds_for(['script.no_config'])), set(cr.KINDS))

    def test_each_action_judged_alone(self):
        kinds = set(cr.kinds_for(['script.mixed']))
        self.assertIn('locks', kinds)            # scene.apply entities are read, not skipped
        self.assertFalse(cr.check(CHILD, ['script.mixed'], {'ha_control': self.rules}).allowed)

    def test_label_and_floor_targets_unreadable(self):
        self.assertEqual(set(cr.kinds_for(['script.labelled'])), set(cr.KINDS))

    def test_data_template_unreadable(self):
        self.assertEqual(set(cr.kinds_for(['script.legacy'])), set(cr.KINDS))

    def test_upward_related_does_not_poison(self):
        # The kitchen light's room holds a sensor and a lock; turning the light off is lights only.
        self.assertEqual(set(cr.kinds_for(['script.kitchen_off'])), {'lights'})
        self.assertTrue(cr.check(CHILD, ['script.kitchen_off'], {'ha_control': self.rules}).allowed)
        self.assertTrue(cr.check(PARENT, ['script.kitchen_off'], {'ha_control': self.rules}).allowed)

    def test_device_action_uses_its_domain(self):
        self.assertEqual(set(cr.kinds_for(['script.device_action'])), {'garage'})

    def test_homeassistant_generic_service_reads_targets(self):
        self.assertEqual(set(cr.kinds_for(['script.ha_generic'])), {'lights'})

    def test_check_refuses_empty_and_coerces_string(self):
        settings = {'ha_control': self.rules}
        self.assertFalse(cr.check(PARENT, [], settings).allowed)
        self.assertFalse(cr.check(CHILD, 'lock.front', settings).allowed)
        self.assertTrue(cr.check(CHILD, 'light.a', settings).allowed)


class ReviewRound2(Base):
    """A step that names something Chauffeur cannot classify is never harmless."""

    def test_automation_trigger_unreadable(self):
        self.assertEqual(set(cr.kinds_for(['script.trigger_auto'])), set(cr.KINDS))
        self.assertFalse(cr.check(CHILD, ['script.trigger_auto'], {'ha_control': self.rules}).allowed)

    def test_named_group_unreadable(self):
        self.assertEqual(set(cr.kinds_for(['script.group_on'])), set(cr.KINDS))

    def test_service_template_unreadable(self):
        self.assertEqual(set(cr.kinds_for(['script.svc_template'])), set(cr.KINDS))

    def test_scene_shorthand_is_read(self):
        kinds = set(cr.kinds_for(['script.scene_short']))
        self.assertTrue({'lights', 'locks'} <= kinds, kinds)
        self.assertFalse(cr.check(CHILD, ['script.scene_short'], {'ha_control': self.rules}).allowed)


class ReviewRound3(Base):
    def test_comma_separated_ids_in_a_step(self):
        kinds = set(cr.kinds_for(['script.csv']))
        self.assertIn('locks', kinds)
        self.assertFalse(cr.check(CHILD, ['script.csv'], {'ha_control': self.rules}).allowed)

    def test_comma_separated_ids_direct(self):
        settings = {'ha_control': self.rules}
        self.assertFalse(cr.check(CHILD, ['light.a, lock.front'], settings).allowed)
        self.assertFalse(cr.check(CHILD, 'light.a,lock.front', settings).allowed)
        self.assertEqual(cr.targets({'entity_id': 'light.a, Lock.Front'}), {'light.a', 'lock.front'})

    def test_event_step_unreadable(self):
        self.assertEqual(set(cr.kinds_for(['script.fires_event'])), set(cr.KINDS))


class Targets(Base):
    def test_targets_filter_to_the_service_domain(self):
        self.assertEqual(cr.targets({'area_id': 'kitchen2'}, domain='light'), {'light.kitchen'})
        self.assertEqual(cr.targets({'device_id': 'dev-garage'}, domain='cover'), {'cover.garage_door'})
        settings = {'ha_control': self.rules}
        self.assertTrue(cr.check(CHILD, cr.targets({'area_id': 'kitchen2'}, domain='light'), settings).allowed)

    def test_unresolvable_targets_raise(self):
        for data in ({'floor_id': 'upstairs'}, {'label_id': 'doors'},
                     {'entity_id': 'light.a', 'label_id': 'doors'},
                     {'area_id': 'no_such_room'}, {'device_id': 'no_such_device'}):
            with self.assertRaises(ValueError, msg=data):
                cr.targets(data)

    def test_targets_area_and_list(self):
        self.assertEqual(cr.targets({'area_id': 'kitchen'}), {'light.a', 'lock.front'})
        # No domain given: every actuatable entity in the room, never a sensor.
        self.assertEqual(cr.targets({'area_id': 'kitchen2'}), {'light.kitchen', 'lock.kitchen_door'})
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
