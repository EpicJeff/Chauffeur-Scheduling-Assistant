"""A named voice speaker asking about their own day gets THEIR drives (2026-10-30).

Device report: "what time do I need to leave today" on a satellite that had
just greeted the user by name answered with another driver's departure. The
voice path offered get_calendar_events with dates only, so even with the lens
known the model had no way to ask for one person's drives, and the tool
returned the whole house. Three things close it:

  1. get_calendar_events takes member_name and keeps only that person's
     assigned drives (the solver assigns a driver's own appointments to them,
     so those ride along).
  2. The voice dispatcher passes member_name through.
  3. The router scopes a first-person question ("I", "my", "me") to the named
     or verified speaker when the model left member_name empty and no other
     family member is named in the words: a deterministic backstop that only
     ever narrows a read.

Real router loop with a faked model, real voice_identity, real voice_tools.
Run from chauffeur/:  python tests/test_voice_my_drives.py
"""
import datetime
import time
import unittest
import uuid
from unittest.mock import patch

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_router, situations, storage, voice_identity as voice, voice_tools
from services import agent_tools_v2 as tools

TODAY = datetime.date.today().isoformat()


def seed():
    storage.drivers_table.truncate()
    storage.add_driver({'id': 'jeff', 'name': 'Jeff', 'color_code': '#fff'})
    storage.add_driver({'id': 'sarah', 'name': 'Sarah', 'color_code': '#000'})
    storage.set_cached_schedule({'events': [
        {'id': 'ev_jeff', 'title': 'Soccer Practice', 'location': 'Soccer Field',
         'start': f'{TODAY}T09:00:00', 'end': f'{TODAY}T10:00:00'},
        {'id': 'ev_sarah', 'title': 'Karate', 'location': 'Dojo',
         'start': f'{TODAY}T10:00:00', 'end': f'{TODAY}T11:00:00'},
        {'id': 'ev_open', 'title': 'Piano', 'location': 'Studio',
         'start': f'{TODAY}T15:00:00', 'end': f'{TODAY}T16:00:00'},
    ], 'assignments': {'ev_jeff': 'jeff', 'ev_sarah': 'sarah'}, 'ghost_assignments': {}, 'scheduled_errands': [],
        'initial_edges': {'jeff': {'ev_jeff': {'travel_mins': 20, 'buffer_before_mins': 5, 'driver_home_location': 'Home'}}}})


class VoiceMyDrivesTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.conversations_table, storage.overrides_table):
            table.truncate()
        with voice._lock:
            voice._sessions.clear()
            voice._requests.clear()
            voice._observed.clear()
        self.settings = {'service_token': 'service', 'contact_first_name': 'Jeff'}
        self.orig_settings = storage.get_settings
        storage.get_settings = lambda: self.settings
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent', 'driver_id': 'jeff'})
        storage.add_member({'id': 'sarah', 'name': 'Sarah', 'role': 'parent', 'driver_id': 'sarah'})
        storage.set_member_pin('jeff', '1234')
        voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.office',
                                'device_id': 'office-dev', 'enabled': True}])
        seed()
        situations.REFRESH_DELAY_S = 0
        p = patch.object(situations, '_pool_call', return_value={})
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        storage.get_settings = self.orig_settings

    def metadata(self):
        return {'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.office', 'device_id': 'office-dev',
                'observed_at': time.time(), 'request_id': uuid.uuid4().hex}

    def context(self):
        return voice.context(self.metadata(), True)

    def named(self):
        """The speaker said who they are (or the fingerprint did): level 'named', no PIN."""
        voice.intercept("It's Jeff", self.context())
        ctx = self.context()
        self.assertEqual(ctx.level, 'named')
        self.assertEqual(ctx.member()['id'], 'jeff')
        return ctx

    # --- 1. the tool --------------------------------------------------------------
    def test_the_calendar_tool_keeps_one_persons_drives_when_asked(self):
        everyone = tools.get_calendar_events(TODAY, TODAY)['events']
        self.assertEqual([e['title'] for e in everyone], ['Soccer Practice', 'Karate', 'Piano'])
        mine = tools.get_calendar_events(TODAY, TODAY, member_name='Jeff')['events']
        self.assertEqual([e['title'] for e in mine], ['Soccer Practice'])
        self.assertEqual(mine[0]['assigned_driver'], 'Jeff')
        self.assertEqual(mine[0].get('leave_label'), '8:30 AM', 'the departure still rides on the row')
        # Someone who is not a driver has no drives; an unknown name is an error, not everyone's drives.
        storage.add_member({'id': 'kid', 'name': 'Alex', 'role': 'child'})
        self.assertEqual(tools.get_calendar_events(TODAY, TODAY, member_name='Alex')['events'], [])
        self.assertEqual(tools.get_calendar_events(TODAY, TODAY, member_name='Nobody')['status'], 'error')
        decl = next(t for t in tools.get_available_tools() if t['name'] == 'get_calendar_events')
        self.assertIn('member_name', decl['parameters']['properties'])

    # --- 2. the voice dispatcher ---------------------------------------------------
    def test_voice_dispatch_passes_the_name_through(self):
        result = voice_tools.dispatch('get_calendar_events', {'start_date': TODAY, 'end_date': TODAY, 'member_name': 'Jeff'},
                                      self.context())
        self.assertEqual([e['title'] for e in result['events']], ['Soccer Practice'])

    # --- 3. the backstop -------------------------------------------------------------
    def test_a_first_person_question_is_scoped_to_the_speaker_when_the_model_did_not(self):
        others = ['Sarah', 'Alex']
        scope = voice_tools.scope_to_speaker
        args = {'start_date': TODAY, 'end_date': TODAY}
        self.assertEqual(scope('get_calendar_events', args, 'what time do I need to leave today', 'Jeff', others),
                         {**args, 'member_name': 'Jeff'})
        self.assertEqual(scope('get_calendar_events', args, "when's my next drive", 'Jeff', others)['member_name'], 'Jeff')
        self.assertEqual(scope('get_drive_digest', {'target_date': 'today'}, 'read me my digest', 'Jeff', others)['member_name'], 'Jeff')
        # Another person named: the model's reading stands, nothing is added.
        self.assertEqual(scope('get_calendar_events', args, 'when does Sarah leave', 'Jeff', others), args)
        self.assertEqual(scope('get_calendar_events', args, "what time do I take Alex to karate", 'Jeff', others), args)
        # A household question stays a household question.
        self.assertEqual(scope('get_calendar_events', args, "what's on the calendar today", 'Jeff', others), args)
        # The model's own choice is kept; an unknown speaker scopes nothing; other tools are untouched.
        self.assertEqual(scope('get_calendar_events', {**args, 'member_name': 'Sarah'}, 'when do I leave', 'Jeff', others)
                         ['member_name'], 'Sarah')
        self.assertEqual(scope('get_calendar_events', args, 'when do I leave', None, others), args)
        self.assertEqual(scope('get_travel_time', {'origin': 'x'}, 'how long is my drive', 'Jeff', others), {'origin': 'x'})

    def test_the_router_answers_a_named_speaker_with_their_own_drive(self):
        """The whole voice path: a named (not PIN-verified) speaker asks in the first
        person, the model calls the calendar tool with dates only, and the tool result
        the model is handed holds only the speaker's drive."""
        ctx = self.named()
        seen = []

        def fake_model(prompt, tools_, system_prompt):
            if not seen:
                seen.append('first')
                return {'message': '', 'tool_calls': [{'name': 'get_calendar_events',
                                                        'arguments': {'start_date': TODAY, 'end_date': TODAY}}]}
            seen.append(prompt)
            return {'message': 'You leave at 8:30 for Soccer Practice.', 'tool_calls': []}
        with patch.object(agent_router, 'call_gemma_with_fallback', fake_model):
            res = agent_router.process_agent_request('what time do I need to leave today', source='voice', voice_context=ctx)
        self.assertEqual(res.get('message'), 'You leave at 8:30 for Soccer Practice.')
        second = seen[1]
        self.assertIn('Soccer Practice', second)
        self.assertNotIn('Karate', second, "another driver's drive must not be in what the model reads")
        self.assertNotIn('Piano', second)
        # The same question from an unknown voice is the household's question.
        with voice._lock:
            voice._sessions.clear()
        seen.clear()
        with patch.object(agent_router, 'call_gemma_with_fallback', fake_model):
            agent_router.process_agent_request('what time do I need to leave today', source='voice', voice_context=self.context())
        self.assertIn('Karate', seen[1])


if __name__ == '__main__':
    unittest.main()
