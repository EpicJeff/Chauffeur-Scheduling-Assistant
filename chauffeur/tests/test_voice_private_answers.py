"""Private answers wait for the speaker (spec 2026-11-10, Task 3).

The user, 2026-11-10: "Can Argyle just ask whether to read it aloud or send it
to the chat?" On a recognised (actor) satellite turn whose answer is not safe
to speak, Argyle holds the answer and asks QUESTION. The same actor's next
turn decides: read it aloud, or post it to their Argyle DM. Anything else
(another voice, an unknown voice, a sign-off, a second unclear reply, the 60 s
timer) posts it to the DM: nothing private is read out on someone else's say
so, and nothing is lost.

What is safe to speak: every agent tool is classified SPEAKABLE or PRIVATE in
voice_tools (a write that confirms what the speaker asked is speakable; a read
is speakable only if it was already a voice tool); unknown names are private;
the phone's per-row checks (calendar events, shopping lists, driver events)
apply too. Unrecognised voices never meet the question.

Ruling (controller, 2026-11-10): the held answer lives in voice_private,
keyed by satellite, not on the identity session row: another voice's
fingerprint replaces the session row before the turn is handled, which would
silently drop the answer instead of sending it to the chat.

Every scenario runs the real endpoint and router; only the model is stubbed.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_voice_private_answers.py
"""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_private_answers_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp, voice_tools, agent_router

KITCHEN = 'assist_satellite.kitchen'
QUESTION = "That's private. Read it out, or send it to your chat?"
SECRET = 'The email from school says the password reset code is pineapple.'


def vector(index=0):
    return [float(i == index) for i in range(256)]


JEFF = vector(0)
MUM = vector(3)
TV = vector(1)


def fake(result):
    """A tool stand-in the router can call with any keyword arguments."""
    def tool(*args, **kwargs):
        tool.calls.append(kwargs)
        return dict(result)
    tool.calls = []
    return tool


class PrivateAnswerTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.conversations_table, storage.chat_messages_table):
            table.truncate()
        voice._sessions.clear(); voice._observed.clear(); voice._requests.clear()
        fp._observations.clear(); fp._enrollments.clear(); fp._last.clear()
        from services import voice_private
        self.vp = voice_private
        voice_private._held.clear()
        self.settings = {'service_token': 'service'}
        settings_patch = patch.object(storage, 'get_settings', side_effect=lambda: dict(self.settings))
        settings_patch.start(); self.addCleanup(settings_patch.stop)
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent'})
        storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent'})
        storage.ensure_argyle_member()
        fp._save([{'member_id': mid, 'key': ['ha', KITCHEN], 'vector': vec, 'revision': fp.REVISION,
                   'consent_actor': 'jeff', 'created_at': time.time(), 'checks': 2, 'calibrated': True}
                  for mid, vec in (('jeff', JEFF), ('mum', MUM))])
        voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': KITCHEN, 'device_id': 'device-' + KITCHEN,
                                'enabled': True, 'recognition_enabled': True}])
        from services import voice_conversation
        voice_conversation._turns.clear()
        for target, value in (('services.announce.answer_through_speaker', None),
                              ('services.llm.auto_name_conversation', None),
                              ('main.trigger_background_refresh', None)):
            p = patch(target, return_value=value) if value is None and target.endswith('speaker') \
                else patch(target, lambda *a, **kw: None)
            p.start(); self.addCleanup(p.stop)
        # Timers never fire on their own inside a test; expire() is called directly.
        timer = patch('threading.Timer')
        self.timer = timer.start(); self.addCleanup(timer.stop)
        self.call = None
        self.reply = 'Okay.'
        self.model_turns = 0

        def fake_llm(prompt, tools, system_prompt, *a, **kw):
            if 'Tool Result' in prompt or self.call is None:
                return {'message': self.reply, 'tool_calls': []}
            self.model_turns += 1
            return {'message': '', 'tool_calls': [self.call]}
        llm = patch.object(agent_router, 'call_gemma_with_fallback', side_effect=fake_llm)
        llm.start(); self.addCleanup(llm.stop)

    # --- fixtures ----------------------------------------------------------
    def say(self, text, voiceprint=None, seconds=6.0, call=None):
        import main
        from starlette.requests import Request
        self.call = call
        request_id = uuid.uuid4().hex
        metadata = {'ha_instance_id': 'ha', 'satellite_id': KITCHEN, 'device_id': 'device-' + KITCHEN,
                    'request_id': request_id, 'utterance_id': request_id, 'run_id': 'run-' + request_id,
                    'observed_at': time.time()}
        if voiceprint is not None:
            ctx = voice.context(dict(metadata), True)
            oid = 'obs-' + request_id
            fp._observations[oid] = {'key': ('ha', KITCHEN, 'device-' + KITCHEN, 'run-' + request_id, request_id),
                                     'revision': ctx.service_revision, 'vector': voiceprint, 'seconds': seconds,
                                     'expires': time.time() + 60}
            metadata['observation_id'] = oid
        request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                           'headers': [(b'x-service-token', b'service')]})
        result = main.converse_ha_assist(main.ConverseRequest(text=text, voice=metadata,
                                                              conversation_id='conv-1'), request)
        return result['response']['speech']['plain']['speech'], result['continue_conversation']

    def dm(self, member_id='jeff'):
        channel = storage.get_or_create_dm(member_id, 'argyle')
        return [m.get('body') or '' for m in storage.get_channel_messages(channel['id'], limit=20)]

    def hold_mail(self):
        """Jeff asks for his mail; the answer is private and gets held."""
        from services import agent_tools_v2
        self.reply = SECRET
        mail = patch.object(agent_tools_v2, 'read_mail', fake({'status': 'success', 'message': SECRET}))
        mail.start(); self.addCleanup(mail.stop)
        speech, keep = self.say('read me the latest email from school', JEFF,
                                call={'name': 'read_mail', 'arguments': {}})
        self.reply = 'Okay.'
        return speech, keep

    # --- classification ------------------------------------------------------
    def test_every_registry_tool_is_classified(self):
        from services import agent_tools_v2
        names = {t['name'] for t in agent_tools_v2.get_available_tools() + agent_tools_v2.get_admin_tools()}
        names |= {'house', 'music', 'memory', 'report_gap', 'prepare_voice_approval'}
        unclassified = sorted(n for n in names if n not in voice_tools.SPEAKABLE and n not in voice_tools.PRIVATE)
        both = sorted(voice_tools.SPEAKABLE & voice_tools.PRIVATE)
        self.assertEqual(unclassified, [], 'classify every tool as SPEAKABLE or PRIVATE')
        self.assertEqual(both, [])
        for name in ('read_mail', 'search_mail', 'get_family_messages', 'list_threads',
                     'find_in_chauffeur', 'get_requests', 'research_question', 'launch_mission'):
            self.assertIn(name, voice_tools.PRIVATE, name)
        for name in ('add_household_task', 'add_shopping_items', 'send_family_message', 'house', 'music'):
            self.assertIn(name, voice_tools.SPEAKABLE, name)

    def test_unknown_tool_is_private(self):
        turn = self.vp.SatelliteTurn(storage.get_member('jeff'))
        turn.before_tool('a_tool_added_next_year', {})
        turn.tool_result({'status': 'success'})
        self.assertFalse(turn.safe)

    def test_failed_tool_is_not_private(self):
        turn = self.vp.SatelliteTurn(storage.get_member('jeff'))
        turn.before_tool('add_household_task', {'title': 'Bins'})
        turn.tool_result({'status': 'error', 'message': 'No title.'})
        self.assertTrue(turn.safe, 'an error message is not private')

    # --- speakable answers -----------------------------------------------------
    def test_write_confirmation_spoken(self):
        from services import agent_tools_v2
        with patch.object(agent_tools_v2, 'add_household_task',
                          fake({'status': 'success', 'message': 'Added take out the bins.'})):
            self.reply = 'Added take out the bins.'
            speech, _ = self.say('add take out the bins to the house list', JEFF,
                                 call={'name': 'add_household_task', 'arguments': {'title': 'Take out the bins'}})
        self.assertNotEqual(speech, QUESTION)
        self.assertIn('bins', speech)
        self.assertEqual(self.vp._held, {})

    # --- private answers --------------------------------------------------------
    def test_private_read_asks(self):
        speech, keep = self.hold_mail()
        self.assertEqual(speech, QUESTION)
        self.assertTrue(keep, 'the mic stays open for the answer')
        self.assertNotIn('pineapple', speech)
        self.assertEqual(self.dm(), [])
        self.assertEqual(self.timer.call_args.args[0], 60)

    def test_same_actor_read_it(self):
        self.hold_mail()
        turns = self.model_turns
        speech, _ = self.say('read it', JEFF, seconds=0.4)
        self.assertEqual(speech, SECRET)
        self.assertEqual(self.model_turns, turns, 'the decision never reaches the model')
        self.assertEqual(self.vp._held, {})
        self.assertEqual(self.dm(), [])

    def test_same_actor_yes_out_loud(self):
        self.hold_mail()
        self.assertEqual(self.say('yes, out loud', JEFF, seconds=0.4)[0], SECRET)

    def test_same_actor_send_it(self):
        self.hold_mail()
        speech, _ = self.say('send it to my chat', JEFF, seconds=0.4)
        self.assertEqual(speech, 'Sent to your chat.')
        self.assertTrue(any('pineapple' in body for body in self.dm()), self.dm())
        self.assertEqual(self.vp._held, {})

    def test_same_actor_no_sends(self):
        self.hold_mail()
        self.assertEqual(self.say('no', JEFF, seconds=0.4)[0], 'Sent to your chat.')
        self.assertTrue(any('pineapple' in body for body in self.dm()))

    def test_unclear_reasks_once(self):
        self.hold_mail()
        speech, keep = self.say('hmm what was that', JEFF, seconds=0.4)
        self.assertEqual(speech, QUESTION)
        self.assertTrue(keep)
        self.assertEqual(self.dm(), [])

    def test_second_unclear_releases(self):
        self.hold_mail()
        self.say('hmm what was that', JEFF, seconds=0.4)
        turns = self.model_turns
        speech, _ = self.say('what time is practice on saturday', JEFF,
                             call={'name': 'get_calendar_events', 'arguments': {}})
        self.assertNotIn('pineapple', speech)
        self.assertTrue(any('pineapple' in body for body in self.dm()))
        self.assertEqual(self.model_turns, turns + 1, 'the turn goes on to the model')

    def test_other_voice_sends_to_chat(self):
        self.hold_mail()
        turns = self.model_turns
        speech, _ = self.say('read it', MUM)
        self.assertNotIn('pineapple', speech)
        self.assertTrue(any('pineapple' in body for body in self.dm('jeff')))
        self.assertFalse(any('pineapple' in body for body in self.dm('mum')))
        self.assertEqual(self.vp._held, {})
        self.say('what time is practice on saturday', MUM, call={'name': 'get_calendar_events', 'arguments': {}})
        self.assertEqual(self.model_turns, turns + 1, "Mum's own turn is answered normally")

    def test_unknown_voice_sends_to_chat(self):
        self.hold_mail()
        speech, _ = self.say('read it out loud now please everyone', TV)
        self.assertNotIn('pineapple', speech)
        self.assertTrue(any('pineapple' in body for body in self.dm()))

    def test_sign_off_sends_to_chat(self):
        self.hold_mail()
        speech, keep = self.say('thanks, that is all', JEFF)
        self.assertNotIn('pineapple', speech)
        self.assertFalse(keep)
        self.assertTrue(any('pineapple' in body for body in self.dm()))
        self.assertEqual(voice._sessions[('ha', KITCHEN)]['level'], 'unknown')

    def test_timer_sends_to_chat(self):
        self.hold_mail()
        self.vp.expire('ha', KITCHEN)
        self.assertTrue(any('pineapple' in body for body in self.dm()))
        self.assertEqual(self.vp._held, {})
        self.vp.expire('ha', KITCHEN)       # a second expiry posts nothing more
        self.assertEqual(sum('pineapple' in body for body in self.dm()), 1)

    def test_late_reply_after_timer_reaches_model(self):
        self.hold_mail()
        self.vp.expire('ha', KITCHEN)
        turns = self.model_turns
        self.say('read it', JEFF, seconds=0.4, call={'name': 'get_calendar_events', 'arguments': {}})
        self.assertEqual(self.model_turns, turns + 1)

    def test_calendar_private_event_asks(self):
        from services import agent_tools_v2, access
        events = [{'id': 'e1', 'title': 'Therapy', 'private': True}]
        with patch.object(agent_tools_v2, 'get_calendar_events',
                          fake({'status': 'success', 'events': [{'id': 'e1', 'title': 'Therapy'}],
                                'message': 'Therapy at 3.'})), \
                patch.object(access, 'cached_schedule', return_value={'events': events}):
            self.reply = 'You have therapy at 3.'
            speech, _ = self.say('what do I have tomorrow afternoon', JEFF,
                                 call={'name': 'get_calendar_events', 'arguments': {}})
        self.assertEqual(speech, QUESTION)

    def test_locate_is_private(self):
        """'Where is Ben' answers with a person's whereabouts: never spoken unasked
        in a shared room (Task 2 review carry-forward)."""
        turn = self.vp.SatelliteTurn(storage.get_member('jeff'))
        turn.before_tool('house', {'action': 'locate', 'query': 'Ben'})
        turn.tool_result({'status': 'success', 'message': 'Ben is at school.'})
        self.assertFalse(turn.safe)
        from services import agent_tools_v2
        with patch.object(agent_tools_v2, 'house', fake({'status': 'success', 'message': 'Ben is at school.'})):
            self.reply = 'Ben is at school.'
            speech, _ = self.say('where is Ben right now', JEFF,
                                 call={'name': 'house', 'arguments': {'action': 'locate', 'query': 'Ben'}})
        self.assertEqual(speech, QUESTION)

    def test_device_control_spoken(self):
        turn = self.vp.SatelliteTurn(storage.get_member('jeff'))
        turn.before_tool('house', {'action': 'act', 'entity_id': 'light.office', 'service': 'turn_off'})
        turn.tool_result({'status': 'success', 'message': 'Done.'})
        self.assertTrue(turn.safe)

    # --- review round 1 ---------------------------------------------------------
    # Ruling (controller, 2026-11-10, replaces "an error is never private"): calling
    # a PRIVATE tool makes the turn private whatever comes back (a bare state dict
    # with no status is a disclosure); a SPEAKABLE tool's errors stay speakable
    # ("Say your PIN first"); tools whose speakable text carries records are PRIVATE.
    def test_private_tool_without_status_is_private(self):
        turn = self.vp.SatelliteTurn(storage.get_member('jeff'))
        turn.before_tool('get_current_state', {})
        turn.tool_result({'schedule': [{'title': 'Therapy'}]})
        self.assertFalse(turn.safe)

    def test_private_tool_error_still_private(self):
        turn = self.vp.SatelliteTurn(storage.get_member('jeff'))
        turn.before_tool('read_mail', {})
        turn.tool_result({'status': 'error', 'message': 'Which one? "Re: Ben\'s report"'})
        self.assertFalse(turn.safe)

    def test_record_bearing_tools_are_private(self):
        for name in ('answer_request', 'adjust_points', 'start_ask', 'get_current_state', 'list_insights'):
            self.assertIn(name, voice_tools.PRIVATE, name)

    def test_house_without_arguments_does_not_raise(self):
        turn = self.vp.SatelliteTurn(storage.get_member('jeff'))
        turn.before_tool('house', None)
        turn.tool_result(None)

    def _ctx(self):
        return voice.context({'ha_instance_id': 'ha', 'satellite_id': KITCHEN, 'device_id': 'device-' + KITCHEN,
                              'request_id': uuid.uuid4().hex, 'observed_at': time.time()}, True)

    def test_read_it_still_posts_card(self):
        self.say('what is on the calendar tomorrow', JEFF)       # Jeff is recognised, the mic is open
        # A card's proposal must exist: storage refuses a chat child of a missing proposal.
        storage.add_action_proposal({'id': 'prop-9', 'action_type': 'request', 'summary': 'Draft',
                                     'created_by_member_id': 'jeff'})
        card = {'kind': 'family_action', 'id': 'card-9', 'proposal_id': 'prop-9', 'summary': 'Draft'}
        self.vp.hold(self._ctx(), storage.get_member('jeff'), SECRET, card)
        with patch.object(storage, 'update_action_proposal') as bind:
            speech, _ = self.say('read it', JEFF, seconds=0.4)
        self.assertTrue(speech.startswith(SECRET), speech)
        channel = storage.get_or_create_dm('jeff', storage.ensure_argyle_member()['id'])
        rows = storage.get_channel_messages(channel['id'], limit=10)
        self.assertTrue(any((m.get('card') or {}).get('id') == 'card-9' for m in rows), rows)
        bind.assert_called_once_with('prop-9', {'channel_id': channel['id']})

    def test_dont_read_it_sends(self):
        self.hold_mail()
        speech, _ = self.say("don't read it out loud", JEFF, seconds=0.4)
        self.assertEqual(speech, 'Sent to your chat.')
        self.assertTrue(any('pineapple' in body for body in self.dm()))

    def test_failed_post_never_breaks_the_next_turn(self):
        from services import agent_tools_v2
        self.hold_mail()
        with patch.object(agent_tools_v2, '_post_chat_message', side_effect=RuntimeError('db locked')):
            speech, _ = self.say('what time is practice on saturday', MUM,
                                 call={'name': 'get_calendar_events', 'arguments': {}})
        self.assertNotIn('pineapple', speech)
        self.assertNotIn('error', speech.lower())
        self.assertIn(('ha', KITCHEN), self.vp._held, 'kept for a later retry, never lost')

    def test_failed_post_still_ends_the_session_on_goodbye(self):
        from services import agent_tools_v2
        self.hold_mail()
        with patch.object(agent_tools_v2, '_post_chat_message', side_effect=RuntimeError('db locked')):
            speech, keep = self.say('thanks, that is all', JEFF)
        self.assertNotIn('pineapple', speech)
        self.assertFalse(keep)
        self.assertEqual(voice._sessions[('ha', KITCHEN)]['level'], 'unknown')

    def test_failed_post_never_breaks_configure(self):
        from services import agent_tools_v2
        self.hold_mail()
        with patch.object(agent_tools_v2, '_post_chat_message', side_effect=RuntimeError('db locked')):
            voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': KITCHEN,
                                    'device_id': 'device-' + KITCHEN, 'enabled': True,
                                    'recognition_enabled': True}])

    def test_new_answer_survives_a_failed_release_of_the_old_one(self):
        """Round 2: hold() must never drop the NEW answer because the OLD one could not
        be posted. The new one is held; the old one is delivered on a later release."""
        from services import agent_tools_v2
        self.hold_mail()                                   # the old answer: pineapple
        newer = 'The second email says the field trip form is due Friday.'
        with patch.object(agent_tools_v2, '_post_chat_message', side_effect=RuntimeError('db locked')):
            self.assertEqual(self.vp.hold(self._ctx(), storage.get_member('jeff'), newer, None), QUESTION)
        self.assertEqual(self.vp._held[('ha', KITCHEN)]['reply'], newer)
        speech, _ = self.say('send it to my chat', JEFF, seconds=0.4)
        self.assertEqual(speech, 'Sent to your chat.')
        bodies = self.dm()
        self.assertTrue(any('field trip' in b for b in bodies), bodies)
        self.assertTrue(any('pineapple' in b for b in bodies), 'the old answer is delivered too, never lost')
        self.assertEqual(sum('pineapple' in b for b in bodies), 1)

    def test_approval_readback_is_never_held(self):
        from services import voice_approval
        with patch.object(voice_approval, 'current_readback',
                          return_value='Say approve booking to book the dentist for Friday.'):
            speech, _ = self.hold_mail()
        self.assertEqual(speech, 'Say approve booking to book the dentist for Friday.')
        self.assertEqual(self.vp._held, {})
        # Branch review M1: the private answer is not lost either.
        self.assertTrue(any('pineapple' in body for body in self.dm()), self.dm())

    # --- branch review (Tasks 1-3) -------------------------------------------------
    def verify_jeff(self):
        storage.set_member_pin('jeff', '1234')
        self.say("It's Jeff", JEFF)
        self.say('my PIN is 1234', JEFF)
        self.assertEqual(voice._sessions[('ha', KITCHEN)]['level'], 'verified')

    def test_verified_session_other_voice_cannot_read_it(self):
        """C1: Jeff gave his PIN; his mail is held; a voice that is merely
        uncertain against Jeff (not a contradiction) says read it."""
        import math
        self.verify_jeff()
        self.assertEqual(self.hold_mail()[0], QUESTION)
        near = [0.0] * 256
        near[0], near[5] = 1.0, 1.5
        norm = math.sqrt(sum(x * x for x in near))
        near = [x / norm for x in near]
        self.assertTrue(fp.DIFFERENT < fp.score(near, JEFF) < fp.THRESHOLD)
        speech, _ = self.say('read it out loud please', near, seconds=2.0)
        self.assertNotIn('pineapple', speech)
        self.assertTrue(any('pineapple' in body for body in self.dm()))

    def test_verified_own_short_read_it_works(self):
        self.verify_jeff()
        self.hold_mail()
        self.assertEqual(self.say('read it', JEFF, seconds=0.4)[0], SECRET)

    def _actor_on_next_turn(self, text, voiceprint, seconds):
        seen = []
        real = agent_router.process_agent_request

        def spy(*a, **kw):
            seen.append(kw.get('voice_context'))
            return real(*a, **kw)
        with patch.object(agent_router, 'process_agent_request', side_effect=spy):
            self.say(text, voiceprint, seconds=seconds)
        return seen[-1].actor()

    def test_send_it_closes_the_conversation(self):
        """C2: "send it" closes the mic, so the next short turn is a new
        conversation and inherits nobody."""
        self.hold_mail()
        speech, keep = self.say('send it', JEFF, seconds=0.4)
        self.assertEqual(speech, 'Sent to your chat.')
        self.assertFalse(keep)
        self.assertIsNone(self._actor_on_next_turn('lights off', TV, 0.4))

    def test_read_it_closes_the_conversation(self):
        self.hold_mail()
        speech, keep = self.say('read it', JEFF, seconds=0.4)
        self.assertEqual(speech, SECRET)
        if not keep:
            self.assertIsNone(self._actor_on_next_turn('lights off', TV, 0.4))

    def test_identity_prompt_keeps_the_conversation(self):
        """Every satellite answer moves the conversation clock by the flag HA is
        actually sent, intercepts included."""
        from services import voice_conversation
        ctx = voice.context({'ha_instance_id': 'ha', 'satellite_id': KITCHEN, 'device_id': 'device-' + KITCHEN,
                             'request_id': 'r', 'observed_at': time.time()}, True)
        result = self.say("It's Jeff")           # a name prompt keeps the mic open for the PIN
        self.assertEqual(voice_conversation.in_conversation(ctx), bool(result[1]))

    def test_read_it_works_with_conversation_mode_off(self):
        """I2: the hold keeps the mic open even when conversation mode is off, so
        the answer to the question is inside the conversation."""
        self.settings['voice_conversation_mode'] = False
        speech, keep = self.hold_mail()
        self.assertEqual(speech, QUESTION)
        self.assertTrue(keep)
        self.assertEqual(self.say('read it', JEFF, seconds=0.4)[0], SECRET)

    def test_unknown_voice_never_held(self):
        from services import agent_tools_v2
        with patch.object(agent_tools_v2, 'find_in_chauffeur',
                          fake({'status': 'success', 'message': 'The dentist is on Friday.'})):
            self.reply = 'The dentist is on Friday.'
            speech, _ = self.say('when is the dentist again', TV,
                                 call={'name': 'find_in_chauffeur', 'arguments': {'query': 'dentist'}})
        self.assertNotEqual(speech, QUESTION)
        self.assertEqual(self.vp._held, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
