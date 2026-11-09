"""The rulebook core for Home Assistant control
(docs/superpowers/specs/2026-11-09-ha-control-permissions-design.md, Task 1).

One household switch, a grid of who may control which kind of thing, and a
per-kind "needs proof of who you are" checkbox. The defaults reproduce what
Chauffeur did before the grid existed, read from the retired
`panel_allow_unsafe_controls` switch. Pure logic: nothing here talks to Home
Assistant.

Run from chauffeur/:  python tests/test_control_rules.py
"""
import copy
import unittest

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import control_rules as cr
from services.control_rules import Who

SENSITIVE = ('garage', 'locks', 'alarm')
EVERYDAY = ('lights', 'switches', 'media', 'climate', 'blinds', 'other')


def member(role, proven=True):
    return Who(role=role, member_id=f'{role}-1', place=None, proven=proven)


PANEL = Who(role=None, member_id=None, place='panel', proven=False)
UNKNOWN_VOICE = Who(role=None, member_id=None, place='unknown_voice', proven=False)
UNKNOWN_VOICE_NO_ID = Who(role=None, member_id=None, place='unknown_voice', proven=False, voice_id=False)
ADMIN = Who(role=None, member_id=None, place=None, proven=True, admin=True)


class Kinds(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(cr.KINDS, ('lights', 'switches', 'media', 'climate', 'blinds',
                                    'garage', 'locks', 'alarm', 'other'))
        self.assertEqual(cr.ROLES, ('parent', 'adult', 'child', 'helper', 'guest'))
        self.assertEqual(cr.PLACES, ('panel', 'unknown_voice'))
        for domain in ('homeassistant', 'hassio', 'automation', 'notify', 'tts', 'recorder'):
            self.assertIn(domain, cr.NEVER_DOMAINS)

    def test_kinds(self):
        cases = [
            ('light.kitchen', {}, 'lights'),
            ('switch.kettle', {}, 'switches'),
            ('fan.office', {}, 'switches'),
            ('input_boolean.guest_mode', {}, 'switches'),
            ('media_player.office_tv', {}, 'media'),
            ('remote.office_tv', {}, 'media'),
            ('climate.hall', {}, 'climate'),
            ('water_heater.pool', {}, 'climate'),
            ('cover.garage_door', {'device_class': 'garage'}, 'garage'),
            ('cover.side_gate', {'device_class': 'gate'}, 'garage'),
            ('cover.patio_door', {'device_class': 'door'}, 'garage'),
            ('cover.office_shade', {'device_class': 'shade'}, 'blinds'),
            ('cover.mystery', {}, 'blinds'),
            ('lock.front_door', {}, 'locks'),
            ('alarm_control_panel.house', {}, 'alarm'),
            ('valve.sprinkler', {}, 'other'),
            ('vacuum.roomba', {}, 'other'),
            ('siren.porch', {}, 'other'),
            ('button.reboot_router', {}, 'other'),
        ]
        for eid, attrs, kind in cases:
            self.assertEqual(cr.kind_of(eid, attrs), kind, eid)
        # Attributes UNKNOWN (state could not be read) is not attributes empty:
        # an unread cover might be the garage, so it is judged as one.
        self.assertEqual(cr.kind_of('cover.garage_door', None), 'garage')

    def test_not_device_control(self):
        for eid in ('homeassistant.restart', 'notify.mobile', 'sensor.temperature',
                    'binary_sensor.door', 'automation.goodnight', 'person.mum', 'zone.home'):
            self.assertIsNone(cr.kind_of(eid, {}), eid)


class Defaults(unittest.TestCase):
    def test_defaults_switch_off(self):
        rules = cr.default_rules({})
        self.assertIs(rules['enabled'], True)
        self.assertEqual(rules['proof'], {k: k in SENSITIVE for k in cr.KINDS})
        for role in ('parent', 'adult'):
            self.assertEqual(rules['people'][role], {k: 'yes' for k in cr.KINDS}, role)
        for role in ('child', 'helper', 'guest'):
            self.assertEqual(rules['people'][role],
                             {k: 'no' if k in SENSITIVE else 'yes' for k in cr.KINDS}, role)
        self.assertEqual(rules['places']['unknown_voice'],
                         {k: 'ask' if k in SENSITIVE else 'yes' for k in cr.KINDS})
        # Blinds and Everything else stay Yes: Argyle at the panel could
        # already operate them, and taking that away was never approved.
        self.assertEqual(rules['places']['panel'], {
            'lights': 'yes', 'switches': 'yes', 'media': 'yes', 'climate': 'yes',
            'blinds': 'yes', 'garage': 'no', 'locks': 'no', 'alarm': 'no', 'other': 'yes'})

    def test_defaults_switch_on(self):
        rules = cr.default_rules({'panel_allow_unsafe_controls': True})
        self.assertEqual(rules['places']['panel'], {
            'lights': 'yes', 'switches': 'yes', 'media': 'yes', 'climate': 'yes',
            'blinds': 'yes', 'garage': 'ask', 'locks': 'ask', 'alarm': 'no', 'other': 'yes'})
        # The legacy switch only ever spoke for the wall; people are unchanged.
        self.assertEqual(rules['people'], cr.default_rules({})['people'])

    def test_defaults_are_fresh_copies(self):
        a = cr.default_rules({})
        a['people']['parent']['locks'] = 'no'
        self.assertEqual(cr.default_rules({})['people']['parent']['locks'], 'yes')

    def test_stored_rules_win(self):
        stored = cr.default_rules({})
        stored['people']['child']['lights'] = 'no'
        got = cr.rules({'ha_control': stored, 'panel_allow_unsafe_controls': True})
        self.assertEqual(got, stored)
        self.assertEqual(cr.rules({}), cr.default_rules({}))


class Validate(unittest.TestCase):
    def test_valid_round_trips(self):
        grid = cr.default_rules({'panel_allow_unsafe_controls': True})
        self.assertEqual(cr.validate_rules(copy.deepcopy(grid)), grid)

    def test_rejects(self):
        bad = []
        g = cr.default_rules({}); g['people']['child']['lights'] = 'ask'; bad.append(g)
        g = cr.default_rules({}); g['places']['panel']['lights'] = 'maybe'; bad.append(g)
        g = cr.default_rules({}); g['people']['parent']['teleport'] = 'yes'; bad.append(g)
        g = cr.default_rules({}); g['people']['wizard'] = {k: 'yes' for k in cr.KINDS}; bad.append(g)
        g = cr.default_rules({}); del g['places']['panel']['locks']; bad.append(g)
        g = cr.default_rules({}); g['proof']['locks'] = 'sure'; bad.append(g)
        g = cr.default_rules({}); g['enabled'] = 'yes'; bad.append(g)
        for grid in bad:
            with self.assertRaises(ValueError) as caught:
                cr.validate_rules(grid)
            self.assertTrue(str(caught.exception).strip(), 'a refusal must say why')


class Decide(unittest.TestCase):
    def setUp(self):
        self.off = cr.default_rules({})
        self.on = cr.default_rules({'panel_allow_unsafe_controls': True})

    def assertAllowed(self, decision):
        self.assertTrue(decision.allowed, decision)
        self.assertIsNone(decision.needs, decision)

    def assertRefused(self, decision, needs=None):
        self.assertFalse(decision.allowed, decision)
        self.assertEqual(decision.needs, needs, decision)
        self.assertTrue(decision.message.strip(), decision)

    def test_decide_matrix(self):
        self.assertAllowed(cr.decide(member('parent'), ['locks'], self.off))
        self.assertRefused(cr.decide(member('parent', proven=False), ['locks'], self.off), needs='pin')
        self.assertAllowed(cr.decide(member('parent', proven=False), ['lights'], self.off))
        self.assertRefused(cr.decide(member('child'), ['locks'], self.off))
        self.assertAllowed(cr.decide(member('child'), ['lights'], self.off))
        self.assertAllowed(cr.decide(PANEL, ['lights'], self.off))
        self.assertRefused(cr.decide(PANEL, ['locks'], self.on), needs='identify')
        self.assertRefused(cr.decide(PANEL, ['locks'], self.off))
        self.assertRefused(cr.decide(PANEL, ['alarm'], self.on))
        self.assertRefused(cr.decide(UNKNOWN_VOICE, ['locks'], self.off), needs='identify')
        self.assertAllowed(cr.decide(UNKNOWN_VOICE, ['lights'], self.off))
        self.assertAllowed(cr.decide(ADMIN, ['alarm'], self.off))

    def test_unknown_voice_without_voice_id(self):
        d = cr.decide(UNKNOWN_VOICE_NO_ID, ['locks'], self.off)
        self.assertRefused(d)
        self.assertIn('phone', d.message.lower())

    def test_disabled_refuses_everyone(self):
        rules = copy.deepcopy(self.off)
        rules['enabled'] = False
        for who in (ADMIN, member('parent'), PANEL):
            d = cr.decide(who, ['lights'], rules)
            self.assertRefused(d)
            self.assertIn('turned off', d.message)

    def test_decide_place_yes_on_proof_kind(self):
        rules = copy.deepcopy(self.off)
        rules['places']['panel']['locks'] = 'yes'
        self.assertRefused(cr.decide(PANEL, ['locks'], rules), needs='identify')
        rules['proof']['locks'] = False
        self.assertAllowed(cr.decide(PANEL, ['locks'], rules))

    def test_proof_on_everyday_kind(self):
        rules = copy.deepcopy(self.off)
        rules['proof']['media'] = True
        self.assertRefused(cr.decide(member('adult', proven=False), ['media'], rules), needs='pin')
        self.assertAllowed(cr.decide(member('adult'), ['media'], rules))
        self.assertRefused(cr.decide(PANEL, ['media'], rules), needs='identify')

    def test_decide_mixed(self):
        d = cr.decide(member('child'), ('lights', 'locks'), self.off)
        self.assertRefused(d)
        self.assertEqual(set(d.kinds), {'lights', 'locks'})
        # One flat refusal beats an askable kind; identify beats pin.
        self.assertRefused(cr.decide(PANEL, ('locks', 'alarm'), self.on))
        rules = copy.deepcopy(self.on)
        rules['proof']['lights'] = True
        self.assertRefused(cr.decide(PANEL, ('lights', 'locks'), rules), needs='identify')

    def test_no_kinds_is_allowed(self):
        self.assertAllowed(cr.decide(member('child'), (), self.off))


if __name__ == '__main__':
    unittest.main()
