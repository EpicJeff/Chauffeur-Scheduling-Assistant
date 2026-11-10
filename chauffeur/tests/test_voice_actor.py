"""A recognised voice acts as that person (spec 2026-11-10, Task 2).

The user, 2026-11-10: "If you are recognized by voice, you should be able to
do whatever you can do in chat on your phone. That is the point of
recognition."

  - VoiceContext.actor(): the verified member, or the voice-recognised member
    on a turn recognised this turn (fingerprint match or an inheriting short
    reply inside one conversation) with Argyle chat scope; never a claimed
    name, never an uncertain long sample.
  - An actor's satellite turn is offered exactly the tools that person's
    phone chat gets (source='family'), plus the household voice mutations
    and the voice approval tool, so being recognised is never weaker than
    being a stranger.
  - Household mutations and messages run as the actor (no parent_of_record,
    no "Household voice:" prefix); everything else runs on the family rail.
  - A card goes to the actor's Argyle DM and the spoken reply says so.
  - Recognition is not proof: proven stays False, booking approvals still ask
    for a PIN.
  - An unrecognised voice is unchanged.

Every scenario runs the real endpoint and the real router; only the model
(call_gemma_with_fallback) is stubbed: it asks for one tool call, then stops.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_voice_actor.py
"""
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_voice_actor_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp, voice_tools, agent_router

KITCHEN = 'assist_satellite.kitchen'


def vector(index=0):
    return [float(i == index) for i in range(256)]


def uncertain():
    a = 0.55
    v = [0.0] * 256
    v[0], v[1] = a, math.sqrt(1 - a * a)
    return v


JEFF = vector(0)
BEN = vector(2)
TV = vector(1)


class VoiceActorTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.conversations_table):
            table.truncate()
        voice._sessions.clear(); voice._observed.clear(); voice._requests.clear()
        fp._observations.clear(); fp._enrollments.clear(); fp._last.clear()
        self.settings = {'service_token': 'service'}
        settings_patch = patch.object(storage, 'get_settings', side_effect=lambda: dict(self.settings))
        settings_patch.start(); self.addCleanup(settings_patch.stop)
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent'})
        storage.set_member_pin('jeff', '1234')
        storage.add_member({'id': 'ben', 'name': 'Ben', 'role': 'child'})
        storage.ensure_argyle_member()
        fp._save([{'member_id': mid, 'key': ['ha', KITCHEN], 'vector': vec, 'revision': fp.REVISION,
                   'consent_actor': 'jeff', 'created_at': time.time(), 'checks': 2, 'calibrated': True}
                  for mid, vec in (('jeff', JEFF), ('ben', BEN))])
        voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': KITCHEN, 'device_id': 'device-' + KITCHEN,
                                'enabled': True, 'recognition_enabled': True}])
        from services import voice_conversation
        voice_conversation._turns.clear()
        speaker = patch('services.announce.answer_through_speaker', return_value=None)
        speaker.start(); self.addCleanup(speaker.stop)
        naming = patch('services.llm.auto_name_conversation', lambda *a, **kw: None)
        naming.start(); self.addCleanup(naming.stop)
        refresh = patch('main.trigger_background_refresh', lambda *a, **kw: None)
        refresh.start(); self.addCleanup(refresh.stop)
        # The model: one tool call (self.call) on the first round, then done.
        self.call = None
        self.offered = []          # tool names offered on each first round
        self.reply = 'Okay.'

        def fake_llm(prompt, tools, system_prompt, *a, **kw):
            if 'Tool Result' in prompt or self.call is None:
                return {'message': self.reply, 'tool_calls': []}
            self.offered.append(sorted({t['name'] for t in tools}))
            return {'message': '', 'tool_calls': [self.call]}
        llm = patch.object(agent_router, 'call_gemma_with_fallback', side_effect=fake_llm)
        llm.start(); self.addCleanup(llm.stop)
        # What the router was handed, per turn.
        self.router_calls = []
        real = agent_router.process_agent_request

        def spy(*a, **kw):
            self.router_calls.append(kw)
            return real(*a, **kw)
        router = patch.object(agent_router, 'process_agent_request', side_effect=spy)
        router.start(); self.addCleanup(router.stop)

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
        return result['response']['speech']['plain']['speech']

    def ctx(self):
        return self.router_calls[-1]['voice_context']

    def family_tools(self, member_id):
        """What this person's phone chat offers the model: the reference set."""
        self.call = {'name': 'get_household_tasks', 'arguments': {}}
        self.offered.clear()
        agent_router.process_agent_request('what needs doing', source='family',
                                           acting_member=storage.get_member(member_id),
                                           focus_key='channel:test')
        self.call = None
        return set(self.offered[-1])

    # --- who acts ----------------------------------------------------------
    def test_actor_for_recognised(self):
        self.say('what is on the calendar tomorrow', JEFF)
        self.assertEqual(self.ctx().actor()['id'], 'jeff')

    def test_actor_for_inheriting_short_reply(self):
        self.say('what is on the calendar tomorrow', JEFF)
        self.say('yes', JEFF, seconds=0.4)
        self.assertEqual(self.ctx().actor()['id'], 'jeff')

    def test_actor_for_verified(self):
        self.say("It's Jeff")
        self.say('my PIN is 1234')
        self.say('what is on the calendar tomorrow')
        self.assertEqual(self.ctx().level, 'verified')
        self.assertEqual(self.ctx().actor()['id'], 'jeff')

    def test_actor_none_for_claimed_name(self):
        self.say("It's Jeff")
        self.say('what is on the calendar tomorrow')
        self.assertEqual(self.ctx().level, 'named')
        self.assertIsNone(self.ctx().actor())
        self.assertEqual(self.ctx().member()['id'], 'jeff', 'a claimed name is still the lens')

    def test_actor_none_for_uncertain_long_sample(self):
        self.say('what is on the calendar tomorrow', JEFF)
        self.say('somebody talking in the next room about dinner', uncertain())
        self.assertIsNone(self.ctx().actor())

    def test_actor_none_without_chat_agent_scope(self):
        from services import scope
        real = scope.can_see
        with patch.object(scope, 'can_see', side_effect=lambda m, facet, *a, **kw:
                          False if facet == 'chat.agent' and (m or {}).get('id') == 'jeff' else real(m, facet, *a, **kw)):
            self.say('what is on the calendar tomorrow', JEFF)
            self.assertIsNone(self.ctx().actor())

    def test_unknown_voice_has_no_actor(self):
        self.say('what is on the calendar tomorrow', TV)
        self.assertIsNone(self.ctx().actor())

    # --- what the actor is offered -------------------------------------------
    def test_recognised_adult_gets_family_tools(self):
        reference = self.family_tools('jeff')
        self.say('what needs doing around the house', JEFF, call={'name': 'get_household_tasks', 'arguments': {}})
        offered = set(self.offered[-1])
        self.assertEqual(offered, reference | set(voice_tools.MUTATIONS) | {'prepare_voice_approval'})
        for name in ('add_household_task', 'cancel_event'):
            self.assertIn(name, offered)
            self.assertNotIn(name, voice_tools.TOOLS)

    def test_child_actor_gets_child_rail(self):
        reference = self.family_tools('ben')
        self.say('what are my chores today please', BEN, call={'name': 'get_kid_tasks', 'arguments': {}})
        offered = set(self.offered[-1])
        self.assertEqual(offered, reference | set(voice_tools.MUTATIONS) | {'prepare_voice_approval'})
        self.assertNotIn('add_routing_rule', offered, 'no admin bridge tools for a child')

    def test_child_actor_never_parent_of_record(self):
        from services import situations
        with patch.object(situations, 'parent_of_record', side_effect=AssertionError('parent_of_record used')), \
                patch.object(voice_tools, '_mutate', return_value={'status': 'success', 'message': 'Added.'}) as mutate:
            self.say('add crayons to the shopping list please', BEN,
                     call={'name': 'add_shopping_items', 'arguments': {'items': ['crayons']}})
        self.assertEqual(mutate.call_args.args[2]['id'], 'ben')

    def test_unknown_voice_tools_unchanged(self):
        from services import agent_tools_v2
        from services.voice_approval import tool_schema
        self.say('what is on the calendar tomorrow', TV, call={'name': 'get_calendar_events', 'arguments': {}})
        registry = {t['name'] for t in agent_tools_v2.get_available_tools() + agent_tools_v2.get_admin_tools()}
        self.assertEqual(set(self.offered[-1]), (registry & voice_tools.TOOLS) | {tool_schema()['name']})

    # --- what the actor's actions are recorded as ------------------------------
    def test_actor_mutation_runs_as_actor(self):
        with patch.object(voice_tools, '_mutate', return_value={'status': 'success', 'message': 'Jeff is driving.'}) as mutate:
            self.say('Jeff drives Ben to practice today', JEFF,
                     call={'name': 'assign_driver_to_event_fuzzy',
                           'arguments': {'event_name': 'practice', 'driver_name': 'Jeff'}})
        name, args, principal, provenance = mutate.call_args.args
        self.assertEqual(name, 'assign_driver_to_event_fuzzy')
        self.assertEqual(principal['id'], 'jeff')
        self.assertEqual(provenance['actor_kind'], 'member')
        self.assertEqual(provenance['actor_member_id'], 'jeff')
        self.assertEqual(provenance['via'], 'voice')

    def test_unknown_mutation_still_parent_of_record(self):
        from services import situations
        with patch.object(situations, 'parent_of_record', return_value=storage.get_member('jeff')), \
                patch.object(voice_tools, '_mutate', return_value={'status': 'success', 'message': 'Added.'}) as mutate:
            self.say('add milk to the shopping list please', TV,
                     call={'name': 'add_shopping_items', 'arguments': {'items': ['milk']}})
        self.assertEqual(mutate.call_args.args[3]['actor_kind'], 'household_voice')

    def _family_messages(self):
        channel = storage.get_family_channel()
        return storage.get_channel_messages(channel['id'], limit=10) if channel else []

    def test_actor_message_from_member(self):
        self.say('tell the family dinner is at six tonight', JEFF,
                 call={'name': 'send_family_message', 'arguments': {'message_text': 'Dinner is at six.'}})
        last = self._family_messages()[-1]
        self.assertEqual(last['sender_member_id'], 'jeff')
        self.assertEqual(last['body'], 'Dinner is at six.')

    def test_unknown_message_still_household(self):
        self.say('tell the family dinner is at six tonight', TV,
                 call={'name': 'send_family_message', 'arguments': {'message_text': 'Dinner is at six.'}})
        last = self._family_messages()[-1]
        self.assertEqual(last['sender_member_id'], 'argyle')
        self.assertEqual(last['body'], 'Household voice: Dinner is at six.')

    def test_actor_family_tool_runs(self):
        from services import agent_tools_v2
        with patch.object(agent_tools_v2, 'add_household_task',
                          return_value={'status': 'success', 'message': 'Added.'}) as add:
            self.say('add take out the bins to the house list', JEFF,
                     call={'name': 'add_household_task', 'arguments': {'title': 'Take out the bins'}})
        self.assertEqual(add.call_args.kwargs['acting_member']['id'], 'jeff')

    def test_actor_teaches_memory(self):
        from services import agent_tools_v2
        with patch.object(agent_tools_v2, 'memory',
                          return_value={'status': 'success', 'message': 'Noted.'}) as memory:
            self.say('remember that Ben likes the window seat', JEFF,
                     call={'name': 'memory', 'arguments': {'action': 'remember',
                                                           'text': 'Ben likes the window seat'}})
        self.assertEqual(memory.call_args.kwargs['acting_member']['id'], 'jeff')

    def test_actor_card_goes_to_dm(self):
        from services import agent_tools_v2
        card = {'kind': 'family_action', 'id': 'card-1', 'summary': 'Ben to Sam\'s on Saturday'}
        with patch.object(agent_tools_v2, 'propose_family_action',
                          return_value={'status': 'success', 'message': 'I asked a parent.', 'card': card}):
            speech = self.say('can I go to Sams on saturday please', BEN,
                              call={'name': 'propose_family_action',
                                    'arguments': {'action_type': 'request', 'summary': "Ben to Sam's"}})
        self.assertTrue(speech.rstrip().endswith("I've put that in your Argyle chat."), speech)
        dm = storage.get_or_create_dm('ben', 'argyle')
        rows = storage.get_channel_messages(dm['id'], limit=5)
        self.assertTrue(any((m.get('card') or {}).get('id') == 'card-1' for m in rows), rows)

    def test_unknown_voice_card_not_posted(self):
        self.say('what is on the calendar tomorrow', TV, call={'name': 'get_calendar_events', 'arguments': {}})
        self.assertNotIn("Argyle chat", self.say('thanks', TV))

    # --- recognition is not proof ----------------------------------------------
    def test_recognised_not_proven(self):
        from services import agent_tools_v2
        with patch.object(agent_tools_v2, 'house',
                          return_value={'status': 'refused', 'needs': 'pin',
                                        'message': 'Say your PIN first, then ask again.'}) as house:
            self.say('unlock the front door please', JEFF,
                     call={'name': 'house', 'arguments': {'action': 'act', 'entity_id': 'lock.front',
                                                          'service': 'unlock'}})
        self.assertFalse(self.router_calls[-1].get('proven'))
        kwargs = house.call_args.kwargs
        self.assertIs(kwargs.get('voice_context'), self.ctx())
        self.assertFalse(kwargs.get('proven', False))

    def test_booking_approval_still_pin(self):
        from services import voice_approval
        with patch.object(voice_approval, '_enabled', return_value=True):
            speech = self.say('approve the booking for the dentist', JEFF,
                              call={'name': 'prepare_voice_approval',
                                    'arguments': {'mission_ref': 'dentist', 'kind': 'submit'}})
        self.assertIn('PIN', speech)

    # --- review round 1: the parent-visible history and the DM card ------------
    def history(self):
        return storage.get_app_state('voice_action_history') or []

    def test_actor_device_control_recorded(self):
        from services import agent_tools_v2
        with patch.object(agent_tools_v2, 'house',
                          return_value={'status': 'success', 'message': 'Done.', 'entity_id': 'light.office',
                                        'service': 'turn_off'}):
            self.say('turn off the office light please', JEFF,
                     call={'name': 'house', 'arguments': {'action': 'act', 'entity_id': 'light.office',
                                                          'service': 'turn_off'}})
        row = self.history()[-1]
        self.assertEqual(row['action'], 'house')
        self.assertEqual(row['principal_member_id'], 'jeff')
        self.assertEqual(row['via'], 'voice')
        self.assertEqual(row['details'].get('entity_id'), 'light.office')

    def test_actor_failed_control_not_recorded(self):
        from services import agent_tools_v2
        with patch.object(agent_tools_v2, 'house',
                          return_value={'status': 'refused', 'message': 'Say your PIN first.'}):
            self.say('unlock the front door please', JEFF,
                     call={'name': 'house', 'arguments': {'action': 'act', 'entity_id': 'lock.front',
                                                          'service': 'unlock'}})
        self.assertEqual(self.history(), [])

    def test_actor_music_and_memory_recorded(self):
        from services import agent_tools_v2
        with patch.object(agent_tools_v2, 'music',
                          return_value={'status': 'success', 'message': 'Playing.', 'entity_id': 'media_player.office',
                                        'item': {'name': 'Abbey Road'}}):
            self.say('play abbey road in the office please', JEFF,
                     call={'name': 'music', 'arguments': {'action': 'play', 'query': 'abbey road'}})
        with patch.object(agent_tools_v2, 'memory',
                          return_value={'status': 'success', 'message': 'Noted.',
                                        'memory': {'text': 'Ben likes the window seat'}}):
            self.say('remember that Ben likes the window seat', JEFF,
                     call={'name': 'memory', 'arguments': {'action': 'remember',
                                                           'text': 'Ben likes the window seat'}})
        actions = [(r['action'], r['principal_member_id']) for r in self.history()]
        self.assertEqual(actions, [('music', 'jeff'), ('memory', 'jeff')])

    def test_actor_card_bound_to_dm(self):
        from services import agent_tools_v2
        card = {'kind': 'family_action', 'id': 'card-2', 'proposal_id': 'prop-1', 'summary': "Ben to Sam's"}
        with patch.object(agent_tools_v2, 'propose_family_action',
                          return_value={'status': 'success', 'message': 'I asked a parent.', 'card': card}), \
                patch.object(storage, 'update_action_proposal') as bind:
            self.say('can I go to Sams on saturday please', BEN,
                     call={'name': 'propose_family_action',
                           'arguments': {'action_type': 'request', 'summary': "Ben to Sam's"}})
        dm = storage.get_or_create_dm('ben', storage.ensure_argyle_member()['id'])
        bind.assert_called_once_with('prop-1', {'channel_id': dm['id']})

    def test_card_post_failure_keeps_the_answer(self):
        from services import agent_tools_v2
        card = {'kind': 'family_action', 'id': 'card-3', 'summary': "Ben to Sam's"}
        with patch.object(agent_tools_v2, 'propose_family_action',
                          return_value={'status': 'success', 'message': 'I asked a parent.', 'card': card}), \
                patch.object(agent_tools_v2, '_post_chat_message', side_effect=RuntimeError('db locked')):
            speech = self.say('can I go to Sams on saturday please', BEN,
                              call={'name': 'propose_family_action',
                                    'arguments': {'action_type': 'request', 'summary': "Ben to Sam's"}})
        self.assertTrue(speech, 'a failed DM post never turns the answer into an error')
        self.assertNotIn("I've put that in your Argyle chat.", speech)

    def test_verified_without_chat_scope_is_not_actor(self):
        from services import scope
        real = scope.can_see
        self.say("It's Jeff")
        self.say('my PIN is 1234')
        with patch.object(scope, 'can_see', side_effect=lambda m, facet, *a, **kw:
                          False if facet == 'chat.agent' and (m or {}).get('id') == 'jeff' else real(m, facet, *a, **kw)):
            self.say('what is on the calendar tomorrow')
            self.assertIsNone(self.ctx().actor())
            self.assertEqual(self.ctx().verified_member()['id'], 'jeff', 'still verified for the stranger rail')


if __name__ == '__main__':
    unittest.main(verbosity=2)
