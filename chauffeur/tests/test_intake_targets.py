"""The intake target list offers EVERY calendar a proposal can land on (2026-11-02).

Device question: "why are the personal calendars the only calendars available
to assign to via intake?" Not a rule, a leftover: the /intake select was built
in email intake v1 from passengers' and drivers' calendar_ids only. The family's
shared calendar (default_calendar_id, starred in Config > General) came later
and never joined the list, though ingest already defaults ownerless proposals
to it, so such a card showed the blank 'Onto whose calendar?' line while being
assigned. Calendars also moved onto the member record, so a person with a
calendar but no passenger or driver profile was missing too.

The list is now built on the server (email_ingest.calendar_targets, served by
GET /api/ingest/targets): the family calendar first, then every active
person's calendars, then any shared calendar nobody owns; names from calendar
metadata when Google answers, the id when it does not. Both selects on the
page (the proposal target and the sender default) read it.

Run from chauffeur/:  python tests/test_intake_targets.py
"""
import os
import unittest
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from fastapi.testclient import TestClient

import main
from services import calendar, email_ingest, storage

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')


class IntakeTargetTests(unittest.TestCase):
    def setUp(self):
        for t in (storage.members_table, storage.passengers_table, storage.drivers_table):
            t.truncate()
        self.settings = {'service_token': 'service',
                         'calendar_ids': ['family@group', 'kid@group', 'dad@group', 'school@group'],
                         'default_calendar_id': 'family@group'}
        self.orig = storage.get_settings
        storage.get_settings = lambda: self.settings
        storage.add_member({'id': 'dad', 'name': 'Jeff', 'role': 'parent', 'calendar_ids': ['dad@group']})
        storage.add_member({'id': 'kid', 'name': 'Addison', 'role': 'child', 'calendar_ids': ['kid@group']})
        storage.add_member({'id': 'gone', 'name': 'Old', 'role': 'adult', 'status': 'archived',
                            'calendar_ids': ['old@group']})
        self.meta = {'family@group': {'summary': 'Wilson Family'}, 'kid@group': {'summary': 'Addison'},
                     'dad@group': {'summary': 'Jeff'}, 'school@group': {'summary': 'School PTA'}}

    def tearDown(self):
        storage.get_settings = self.orig

    def test_family_first_then_people_then_shared_calendars_nobody_owns(self):
        with mock.patch.object(calendar, 'get_calendar_metadata', return_value=self.meta):
            out = email_ingest.calendar_targets()
        self.assertEqual([c['id'] for c in out], ['family@group', 'kid@group', 'dad@group', 'school@group'],
                         'family calendar first, people in name order (Addison, Jeff), then the shared '
                         "leftovers; the archived person's calendar is not offered")
        self.assertEqual([c['kind'] for c in out], ['family', 'person', 'person', 'shared'])
        self.assertEqual(out[0]['label'], '★ Family — Wilson Family')
        self.assertEqual(out[1]['label'], 'Addison — Addison')
        self.assertEqual(out[2]['label'], 'Jeff — Jeff')
        self.assertEqual(out[2]['member_id'], 'dad')
        self.assertEqual(out[3]['label'], 'School PTA')
        self.assertEqual(len({c['id'] for c in out}), len(out), 'no calendar is offered twice')

    def test_a_family_calendar_that_is_also_a_persons_is_offered_once_as_family(self):
        self.settings['default_calendar_id'] = 'dad@group'
        with mock.patch.object(calendar, 'get_calendar_metadata', return_value=self.meta):
            out = email_ingest.calendar_targets()
        self.assertEqual([c['id'] for c in out], ['dad@group', 'kid@group', 'family@group', 'school@group'])
        self.assertEqual(out[0]['kind'], 'family')

    def test_no_google_means_ids_not_an_empty_list(self):
        with mock.patch.object(calendar, 'get_calendar_metadata', side_effect=RuntimeError('no creds')):
            out = email_ingest.calendar_targets()
        self.assertEqual(out[0]['label'], '★ Family — family@group')
        self.assertEqual(out[1]['label'], 'Addison — kid@group')
        self.assertEqual(out[2]['label'], 'Jeff — dad@group')
        self.assertEqual(out[3]['label'], 'school@group')

    def test_the_endpoint_serves_it(self):
        client = TestClient(main.app)
        with mock.patch.object(calendar, 'get_calendar_metadata', return_value=self.meta):
            res = client.get('/api/ingest/targets', headers={'x-service-token': 'service'})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual([c['id'] for c in res.json()['calendars']],
                         ['family@group', 'kid@group', 'dad@group', 'school@group'])

    def test_the_page_reads_the_served_list_for_both_selects(self):
        page = open(os.path.join(TPL, 'intake.html'), encoding='utf-8').read()
        self.assertIn('api/ingest/targets', page)
        self.assertNotIn("(p.calendar_ids || []).forEach(c => opts.push", page,
                         'the page no longer builds the list from passenger calendars')
        self.assertNotIn("((d.calendar_ids || d.calendarIds) || []).forEach(c => opts.push", page)
        # The proposal target and the sender-default select both read calendarTargets.
        self.assertEqual(page.count('x-for="opt in calendarTargets"'), 1)
        self.assertIn('x-for="opt in targetsFor(p)"', page)
        self.assertIn('...this.calendarTargets', page)


if __name__ == '__main__':
    unittest.main()
