"""Privacy follows the data, and Argyle can tell you the weather (2026-11-10).

Device run, the user: "I got a lot of 'That's private' responses even though it
knew who I was and I was just asking for the schedule which should not be
private by default." Cause: v2.499.776 made every read outside the old voice set
PRIVATE, so the drive digest, run sheet, chores, dinners and routines were all
held behind "Read it out, or send it to your chat?".

Ruling: shared household information is SPEAKABLE (schedule, drives, chores,
routines, meals, lists, errands, projects, points, weather). PRIVATE stays for
personal communications and sensitive stores (mail, family messages, threads,
requests, the Mind's insights and findings, wide searches, the raw admin state
dump, gift-bearing occasion reads), a person's whereabouts (house locate), and
calendar rows marked private or sensitive (the per-row checks).

Also the user: "It also told me it had no tool to tell me the weather for the
week which is silly." New agent tool get_weather(days=7): the daily forecast from
Home Assistant (settings.weather_entity, else the first weather.* entity, via
ha_api.get_weather_forecast), one line per day from today, days clamped 1..10.
Offered to every voice (it is in voice_tools.TOOLS) and speakable. No forecast
-> status 'error' with "I can't see a weather forecast right now." The hand path
is the existing weather board tile.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_voice_privacy_weather.py
"""
import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_voice_private_answers as base     # sets CHAUFFEUR_DATA_DIR first
from services import storage, voice_tools, ha_api, agent_tools_v2

SHARED = ('get_drive_digest', 'get_run_sheet', 'get_household_tasks', 'get_kid_tasks', 'get_routine_status',
          'get_week_dinners', 'get_tonights_plate', 'list_chores', 'get_household_status', 'get_errands',
          'get_eating_plan', 'list_projects', 'get_project', 'get_household_load',
          'get_point_balances', 'adjust_points', 'get_family_goals', 'get_travel_time',
          'get_calendar_events', 'get_shopping_list_items', 'research_question', 'get_weather')
PERSONAL = ('read_mail', 'search_mail', 'get_family_messages', 'list_threads', 'get_requests', 'answer_request',
            'list_insights', 'list_open_findings', 'find_in_chauffeur', 'get_current_state', 'start_ask',
            'draft_thread_message', 'suggest_gift_ideas', 'add_occasion_gift_list', 'get_occasion',
            'manage_car',   # manage_car locate says where a family car, so a person, is
            # Branch review 2026-11-10: these speak calendar or program titles with no
            # per-row check (a private appointment, a restricted program): held.
            'get_assist_coverage', 'negotiate_day', 'list_programs', 'program_progress')


def forecast(days=10, start=None):
    start = start or datetime.date.today()
    conds = ['sunny', 'rainy', 'cloudy', 'partlycloudy', 'snowy', 'sunny', 'windy', 'sunny', 'rainy', 'cloudy']
    return [{'datetime': (start + datetime.timedelta(days=i)).isoformat() + 'T12:00:00+00:00',
             'condition': conds[i % len(conds)], 'temperature': 70 + i, 'templow': 50 + i,
             'precipitation_probability': 60 if conds[i % len(conds)] == 'rainy' else 0} for i in range(days)]


class Classification(unittest.TestCase):
    def test_shared_household_reads_are_speakable(self):
        for name in SHARED:
            self.assertIn(name, voice_tools.SPEAKABLE, name)

    def test_personal_reads_stay_private(self):
        for name in PERSONAL:
            self.assertIn(name, voice_tools.PRIVATE, name)

    def test_schedule_turn_is_safe(self):
        from services import voice_private
        turn = voice_private.SatelliteTurn(storage.get_member('jeff') or {'id': 'jeff'})
        turn.before_tool('get_drive_digest', {'target_date': 'today'})
        turn.tool_result({'status': 'success', 'message': 'Jeff drives Ben to soccer at 4.'})
        self.assertTrue(turn.safe)


class ScheduleOnTheSatellite(unittest.TestCase):
    """The device run, end to end: Jeff is recognised and asks what is next."""
    def setUp(self):
        base.PrivateAnswerTests.setUp(self)

    say = base.PrivateAnswerTests.say
    dm = base.PrivateAnswerTests.dm

    def test_whats_next_is_answered_aloud(self):
        digest = 'Next up: Jeff drives Ben to soccer at 4:15.'
        self.reply = digest
        with patch.object(agent_tools_v2, 'get_drive_digest',
                          base.fake({'status': 'success', 'message': digest})):
            speech, _ = self.say("Can you tell me what's next on the schedule for today?", base.JEFF,
                                 call={'name': 'get_drive_digest', 'arguments': {'target_date': 'today'}})
        self.assertTrue(speech.endswith(digest), speech)    # after 'Hi Jeff.' on a first recognition
        self.assertNotEqual(speech, base.QUESTION)
        self.assertEqual(self.vp._held, {})

    def _digest_with(self, event_ids, events, errands=()):
        from services import access
        self.reply = 'Jeff drives to Dr. Patel at 3.'
        with patch.object(agent_tools_v2, 'get_drive_digest',
                          base.fake({'status': 'success', 'message': self.reply,
                                     'events': [{'id': i} for i in event_ids]})),                 patch.object(access, 'cached_schedule',
                             return_value={'events': events, 'scheduled_errands': list(errands)}):
            return self.say("What's next on the schedule for today?", base.JEFF,
                            call={'name': 'get_drive_digest', 'arguments': {'target_date': 'today'}})[0]

    def test_digest_with_a_private_appointment_asks(self):
        # Branch review C1: the digest named private calendar titles aloud.
        speech = self._digest_with(['e1'], [{'id': 'e1', 'title': 'Dr. Patel', 'visibility': 'private'}])
        self.assertEqual(speech, base.QUESTION)

    def test_digest_with_a_sensitive_event_asks(self):
        speech = self._digest_with(['e1'], [{'id': 'e1', 'title': 'Therapy', 'sensitivity': 'sensitive'}])
        self.assertEqual(speech, base.QUESTION)

    def test_digest_of_shared_events_and_errands_is_spoken(self):
        speech = self._digest_with(['e2', 'errand-1'], [{'id': 'e2', 'title': 'Soccer'}],
                                   errands=[{'id': 'errand-1', 'title': 'Pick up dry cleaning'}])
        self.assertNotEqual(speech, base.QUESTION)

    def test_mail_still_asks(self):
        speech, _ = base.PrivateAnswerTests.hold_mail(self)
        self.assertEqual(speech, base.QUESTION)


class Weather(unittest.TestCase):
    def setUp(self):
        self.settings = {}
        p = patch.object(storage, 'get_settings', side_effect=lambda: dict(self.settings))
        p.start(); self.addCleanup(p.stop)
        self.asked = []

        def get_weather_forecast(entity_id=None, kind='daily'):
            self.asked.append((entity_id, kind))
            return self.data
        self.data = forecast()
        p = patch.object(ha_api, 'get_weather_forecast', side_effect=get_weather_forecast)
        p.start(); self.addCleanup(p.stop)

    def test_week_forecast(self):
        res = agent_tools_v2.get_weather()
        self.assertEqual(res['status'], 'success')
        self.assertEqual(len(res['days']), 7)
        self.assertEqual(self.asked[-1][1], 'daily')
        today = datetime.date.today()
        self.assertEqual(res['days'][0]['date'], today.isoformat())
        for day in res['days']:
            self.assertIn('high', day)
            self.assertIn('low', day)
            self.assertIn('condition', day)
        self.assertIn('70', res['message'])
        self.assertIn((today + datetime.timedelta(days=2)).strftime('%A'), res['message'])

    def test_days_clamped(self):
        self.assertEqual(len(agent_tools_v2.get_weather(days=1)['days']), 1)
        self.assertEqual(len(agent_tools_v2.get_weather(days=40)['days']), 10)
        self.assertEqual(len(agent_tools_v2.get_weather(days=0)['days']), 1)

    def test_past_entries_skipped(self):
        self.data = forecast(start=datetime.date.today() - datetime.timedelta(days=2))
        res = agent_tools_v2.get_weather(days=3)
        self.assertEqual(res['days'][0]['date'], datetime.date.today().isoformat())

    def test_days_missing_means_a_week(self):
        self.assertEqual(len(agent_tools_v2.get_weather(days=None)['days']), 7)

    def test_weather_is_a_proposal_read(self):
        from services import agent_router
        self.assertIn('get_weather', agent_router.PROPOSE_ONLY_READS)

    def test_configured_entity_used(self):
        self.settings['weather_entity'] = 'weather.backyard'
        agent_tools_v2.get_weather()
        self.assertEqual(self.asked[-1][0], 'weather.backyard')

    def test_no_forecast(self):
        self.data = []
        res = agent_tools_v2.get_weather()
        self.assertEqual(res['status'], 'error')
        self.assertEqual(res['message'], "I can't see a weather forecast right now.")

    def test_offered_to_the_model_and_to_every_voice(self):
        names = {t['name'] for t in agent_tools_v2.get_available_tools()}
        self.assertIn('get_weather', names)
        self.assertIn('get_weather', voice_tools.TOOLS)

    def test_unknown_voice_can_ask(self):
        ctx = base.voice.context({'ha_instance_id': '', 'satellite_id': '', 'request_id': 'r'}, False)
        res = voice_tools.dispatch('get_weather', {'days': 3}, ctx)
        self.assertEqual(res['status'], 'success')
        self.assertEqual(len(res['days']), 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
