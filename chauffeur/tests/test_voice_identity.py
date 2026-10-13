"""Voice identity, projection, exact approval and endpoint regressions; no network."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_voice_test_')
from harness import check  # isolates storage before importing the application
from services import storage, voice_identity as voice, voice_tools, voice_approval as approval
from services import agent_router, agent_tools_v2, missions, situations


class VoiceIdentityTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.missions_table, storage.mission_steps_table,
                      storage.threads_table, storage.shopping_lists_table, storage.shopping_items_table,
                      storage.overrides_table, storage.drivers_table, storage.conversations_table,
                      storage.chat_channels_table, storage.chat_messages_table):
            table.truncate()
        with voice._lock:
            voice._sessions.clear()
            voice._requests.clear()
            voice._observed.clear()
        self.settings = {'service_token': 'service', 'missions_enabled': True,
                         'missions_submit_enabled': True, 'llm_gemini_paid_api_key': 'fake',
                         'contact_first_name': 'Jeff', 'contact_email': 'jeff@example.test'}
        storage.get_settings = lambda: self.settings
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent'})
        storage.add_member({'id': 'kid', 'name': 'Alex', 'role': 'child'})
        storage.set_member_pin('jeff', '1234')
        storage.set_member_pin('kid', '9876')
        voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen',
                                'device_id': 'device', 'enabled': True}], approvals_enabled=True)
        situations.REFRESH_DELAY_S = 0
        self.pool_patch = patch.object(situations, '_pool_call', return_value={})
        self.pool_patch.start()
        self.addCleanup(self.pool_patch.stop)

    def metadata(self, **changes):
        import uuid
        return {'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen', 'device_id': 'device',
                'observed_at': time.time(), 'request_id': uuid.uuid4().hex, **changes}

    def context(self, **changes):
        return voice.context(self.metadata(**changes), True)

    def verify(self, name='Jeff', pin='1234'):
        voice.intercept(f"It's {name}", self.context())
        result = voice.intercept(f'My PIN is {pin}', self.context())
        self.assertEqual(result['status'], 'authentication')
        return self.context()

    def request(self, token='service', member_token=None):
        from starlette.requests import Request
        headers = [(b'x-service-token', token.encode())] if token else []
        if member_token:
            headers.append((b'x-member-token', member_token.encode()))
        return Request({'type': 'http', 'headers': headers, 'query_string': b'', 'method': 'POST', 'path': '/'})

    def ask(self, kind='submit', **extra):
        mid = storage.add_mission({'goal': 'dishwasher', 'created_by': 'jeff', 'status': 'waiting_user'})
        values = {'site': 'merchant.test', 'url': 'https://merchant.test/review', 'button': 'Book appointment',
                  'state': {'text': 'Tuesday $114.95', 'fields': []},
                  'facts': {'slot': 'Tuesday, 8 AM to noon', 'fee': '$114.95'},
                  'fields': ['first_name', 'email'], 'missing': [], 'browse': {'goal': 'g', 'site': 'merchant.test'}}
        aid = storage.add_mission_step(mid, {'kind': 'ask', 'name': kind, 'result_json': {**values, **extra}})
        return mid, aid

    def test_number_grammar_and_leading_zero(self):
        for phrase, expected in [('1234', '1234'), ('one two three four', '1234'),
                                 ('twelve thirty-four', '1234'), ('one thousand two hundred thirty-four', '1234'),
                                 ('zero zero seven six', '0076'), ('00 76', '0076')]:
            self.assertEqual(voice.normalize_pin(phrase), expected)
        for phrase in ('maybe 1234', 'one hundred hundred', 'twelve and thirty-four', '1234 approve booking'):
            self.assertIsNone(voice.normalize_pin(phrase))

    def test_named_is_not_verified_and_exact_names_only(self):
        voice.intercept("It's Jeff", self.context())
        ctx = self.context()
        self.assertEqual(ctx.level, 'named')
        self.assertIsNone(ctx.verified_member())
        voice.intercept("It's Jef", self.context())
        self.assertEqual(self.context().level, 'unknown')

    def test_ambiguous_alias_accepts_full_name_on_next_turn(self):
        storage.update_member('jeff', {'name': 'Jeff Wilson', 'voice_aliases': ['Dad']})
        storage.add_member({'id': 'other', 'name': 'Other Parent', 'role': 'parent', 'voice_aliases': ['Dad']})
        result = voice.intercept("It's Dad", self.context())
        self.assertIn('full name', result['message'])
        self.assertTrue(voice.expects_reply(self.context()))
        voice.intercept('Jeff Wilson', self.context())
        self.assertEqual(self.context().member_id, 'jeff')
        self.assertIsNone(self.context().verified_member())

    def test_cancel_clears_pending_pin_challenge(self):
        voice.intercept("It's Jeff", self.context())
        voice.challenge(self.context())
        approval.intercept('cancel', self.context())
        self.assertFalse(voice.expects_reply(self.context()))
        self.assertIsNone(voice.intercept('1234', self.context()))

    def test_verification_expires_without_sliding(self):
        ctx = self.verify()
        self.assertEqual(ctx.verified_member()['id'], 'jeff')
        original = ctx.expires_at
        self.assertEqual(self.context().expires_at, original)
        with patch.object(voice.time, 'time', return_value=original + 1):
            self.assertIsNone(ctx.verified_member())
            self.assertEqual(self.context().level, 'unknown')

    def test_wrong_length_does_not_count_wrong_pin(self):
        voice.intercept("It's Jeff", self.context())
        for _ in range(3):
            result = voice.intercept('My PIN is 12', self.context())
            self.assertIn('one digit', result['message'])
        self.assertFalse(voice._locked(self.context(), 'jeff'))

    def test_three_wrong_pins_survive_session_restart(self):
        voice.intercept("It's Jeff", self.context())
        for _ in range(3):
            voice.intercept('My PIN is 4321', self.context())
        voice._sessions.clear()
        voice.intercept("It's Jeff", self.context())
        result = voice.intercept('My PIN is 1234', self.context())
        self.assertIn('locked', result['message'])
        self.assertIsNone(self.context().verified_member())
        voice.recover('ha', 'assist_satellite.kitchen', True, 'jeff')
        self.assertEqual(self.verify().level, 'verified')

    def test_member_lock_cannot_move_to_another_satellite(self):
        voice.intercept("It's Jeff", self.context())
        for _ in range(3):
            voice.intercept('My PIN is 4321', self.context())
        voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.other', 'enabled': True}])
        ctx = self.context(satellite_id='assist_satellite.other')
        voice.intercept("It's Jeff", ctx)
        result = voice.intercept('My PIN is 1234', self.context(satellite_id='assist_satellite.other'))
        self.assertIn('locked', result['message'])

    def test_pin_reset_role_change_and_disabled_member_revoke(self):
        ctx = self.verify()
        storage.set_member_pin('jeff', '5555')
        self.assertIsNone(ctx.verified_member())
        ctx = self.verify(pin='5555')
        storage.update_member('jeff', {'role': 'child'})
        self.assertIsNone(ctx.verified_member())
        storage.update_member('jeff', {'role': 'parent', 'status': 'disabled'})
        self.assertIsNone(self.context().member())

    def test_service_revocation_metadata_and_device_boundaries(self):
        ctx = self.verify()
        self.assertFalse(self.context(device_id='different').paired)
        self.assertFalse(voice.context(self.metadata(observed_at=time.time() - 90), True).paired)
        self.assertFalse(voice.context(self.metadata(), False).paired)
        self.assertFalse(voice.context(self.metadata(request_id='x' * 129), True).paired)
        self.settings['service_token'] = 'rotated'
        self.assertIsNone(ctx.verified_member())
        self.assertFalse(self.context().paired)

    def test_device_change_does_not_borrow_unbound_satellite_session(self):
        voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen', 'enabled': True}])
        previous = self.verify()
        next_device = self.context(device_id='replacement')
        self.assertEqual(next_device.level, 'unknown')
        self.assertIsNone(previous.verified_member())

    def test_pin_length_is_private_and_backfills_only_on_success(self):
        import main
        self.assertNotIn('pin_length', main._public_member(storage.get_member('jeff')))
        storage.update_member('jeff', {'pin_length': None})
        self.assertFalse(storage.verify_member_pin('jeff', '1111'))
        self.assertIsNone(storage.get_member('jeff')['pin_length'])
        self.assertTrue(storage.verify_member_pin('jeff', '1234'))
        self.assertEqual(storage.get_member('jeff')['pin_length'], 4)

    def test_endpoint_pin_never_reaches_model_history_title_or_sse(self):
        import main
        voice.intercept("It's Jeff", self.context())
        before = list(main.CHAT_EVENTS)
        for text in ('My PIN is one two three four', 'My PIN is malformed 1234', 'My PIN is 1234 and approve booking', 'Well, my PIN is 1234'):
            with patch.object(agent_router, 'process_agent_request') as model:
                result = main.converse_ha_assist(main.ConverseRequest(text=text, conversation_id='shared', voice=self.metadata()), self.request())
                model.assert_not_called()
            self.assertIn('response', result)
        self.assertFalse(storage.conversations_table.all())
        self.assertEqual(main.CHAT_EVENTS, before)

    def test_stale_pin_reply_and_revoked_token_never_become_chat(self):
        import main
        voice.intercept("It's Jeff", self.context())
        voice.challenge(self.context())
        for metadata, request in [(self.metadata(observed_at=time.time() - 90), self.request()),
                                  (self.metadata(), self.request(token='wrong'))]:
            with patch.object(agent_router, 'process_agent_request') as model:
                result = main.converse_ha_assist(main.ConverseRequest(text='1234', voice=metadata), request)
                model.assert_not_called()
            self.assertNotIn('1234', json.dumps(result))
        self.assertFalse(storage.conversations_table.all())

    def test_pending_pin_with_trailing_command_is_intercepted(self):
        import main
        voice.intercept("It's Jeff", self.context())
        voice.challenge(self.context())
        with patch.object(agent_router, 'process_agent_request') as model:
            main.converse_ha_assist(main.ConverseRequest(text='1234 and approve booking', voice=self.metadata()), self.request())
            model.assert_not_called()
        self.assertFalse(storage.conversations_table.all())

    def test_format_reprompt_keeps_bare_retry_out_of_chat_and_listens(self):
        import main
        voice.intercept("It's Jeff", self.context())
        with patch.object(agent_router, 'process_agent_request') as model:
            result = main.converse_ha_assist(main.ConverseRequest(text='My PIN is 12', voice=self.metadata()), self.request())
            self.assertTrue(result['continue_conversation'])
            result = main.converse_ha_assist(main.ConverseRequest(text='one two three four', voice=self.metadata()), self.request())
            self.assertIn('Verified', result['response']['speech']['plain']['speech'])
            model.assert_not_called()
        self.assertFalse(storage.conversations_table.all())

    def test_unknown_mission_request_does_not_borrow_parent_or_private_thread(self):
        storage.add_thread({'id': 'private', 'title': 'dishwasher secret', 'owner_member_id': 'jeff'})
        storage.add_mission({'goal': 'dishwasher secret', 'origin_kind': 'thread', 'origin_ref': 'private'})
        result = voice_tools.dispatch('start_mission_for', {'goal': 'get the dishwasher fixed'}, self.context())
        self.assertEqual(result['status'], 'success')
        row = storage.get_mission(result['mission_id'])
        self.assertIsNone(row['created_by'])
        self.assertEqual(row['requester_provenance']['actor_kind'], 'household_voice')
        self.assertNotEqual(row['origin_ref'], 'private')

    def test_wrong_pin_reverification_cannot_reuse_old_readback(self):
        self.verify()
        mid, _ = self.ask()
        approval.prepare(self.context(), mid, 'submit')
        voice.intercept('My PIN is 4321', self.context())
        voice.intercept('My PIN is 1234', self.context())
        self.assertEqual(approval.intercept('approve booking', self.context())['status'], 'refused')

    def test_recovery_does_not_clear_web_pin_lock(self):
        for _ in range(5):
            storage.rate_record('member:jeff', False)
        self.assertTrue(storage.rate_locked('member:jeff'))
        voice.recover('ha', 'assist_satellite.kitchen', True, 'jeff')
        self.assertTrue(storage.rate_locked('member:jeff'))

    def test_duplicate_pin_delivery_returns_original_reply(self):
        import main
        voice.intercept("It's Jeff", self.context())
        req = main.ConverseRequest(text='My PIN is 1234', voice=self.metadata())
        with patch.object(storage, 'verify_member_pin', wraps=storage.verify_member_pin) as verify:
            first = main.converse_ha_assist(req, self.request())
            second = main.converse_ha_assist(req, self.request())
            self.assertEqual(first, second)
            self.assertEqual(verify.call_count, 1)

    def test_concurrent_duplicate_request_runs_once(self):
        ctx = self.context()
        calls = []
        def work():
            calls.append(True)
            time.sleep(.02)
            return {'status': 'safe'}
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: voice.once(ctx, work), range(5)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(results, [{'status': 'safe'}] * 5)

    def test_history_is_partitioned_on_name_and_satellite(self):
        import main
        seen = []
        def model(text, **kwargs):
            seen.append(kwargs)
            return {'message': 'Shared answer.'}
        with patch.object(agent_router, 'process_agent_request', side_effect=model):
            for _ in range(2):
                main.converse_ha_assist(main.ConverseRequest(text='schedule', conversation_id='shared', voice=self.metadata()), self.request())
            voice.intercept("It's Jeff", self.context())
            main.converse_ha_assist(main.ConverseRequest(text='schedule', conversation_id='shared', voice=self.metadata()), self.request())
            main.converse_ha_assist(main.ConverseRequest(text='schedule', conversation_id='shared', voice=self.metadata(satellite_id='assist_satellite.other')), self.request())
        self.assertEqual(len(seen[1]['history']), 2)
        self.assertEqual(seen[2]['history'], [])
        self.assertEqual(seen[3]['history'], [])
        self.assertTrue(all(s['source'] == 'voice' for s in seen))

    def test_router_refuses_unoffered_privileged_tool(self):
        calls = []
        def llm(prompt, tools, system_prompt):
            calls.append((tools, system_prompt, prompt))
            return {'tool_calls': [{'name': 'read_mail', 'arguments': {'uid': 1}}]} if len(calls) == 1 else {'message': 'Use your phone.'}
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=llm), \
                patch.object(agent_tools_v2, 'read_mail') as read:
            agent_router.process_agent_request('read my mail', source='voice', voice_context=self.verify(),
                                                context={'private': 'SECRET'}, focus_key='private-focus')
            read.assert_not_called()
        self.assertNotIn('read_mail', {t['name'] for t in calls[0][0]})
        self.assertNotIn('SECRET', calls[0][1])

    def test_voice_cannot_delegate_to_a_privileged_ui_action(self):
        with patch.object(agent_router, 'call_gemma_with_fallback', return_value={'delegate_to_gemini': True}):
            result = agent_router.process_agent_request('plan a trip', source='voice', voice_context=self.context())
        self.assertEqual(result['status'], 'refused')
        self.assertNotIn('ui_action', result)

    def test_household_lists_retain_provenance_and_hide_private_lists(self):
        ctx = self.context()
        storage.add_shopping_list({'id': 'private', 'name': 'Surprise', 'audience': 'private', 'shared_with': ['jeff']})
        result = voice_tools.dispatch('add_shopping_items', {'items': 'milk'}, ctx)
        self.assertEqual(result['status'], 'success')
        item = storage.shopping_items_table.all()[0]
        self.assertEqual(item['added_by'], 'jeff')
        self.assertEqual(item['actor_provenance']['actor_kind'], 'household_voice')
        result = voice_tools.dispatch('get_shopping_list_items', {'list_name': 'Surprise'}, self.verify())
        self.assertNotIn('milk', result['message'])
        self.assertEqual(result['status'], 'error')
        voice_tools.dispatch('check_off_shopping_item', {'item_name': 'milk'}, self.context())
        self.assertEqual(storage.get_shopping_items(item['list_id'])[0]['checked_provenance']['actor_kind'], 'member')

    def test_schedule_projection_hides_private_event_and_assignment_is_household(self):
        import datetime
        today = datetime.date.today().isoformat()
        storage.add_driver({'id': 'driver', 'name': 'Jeff'})
        storage.set_cached_schedule({'events': [
            {'id': 'shared', 'title': 'Soccer', 'start': today + 'T10:00:00'},
            {'id': 'secret', 'title': 'Surprise party', 'start': today + 'T11:00:00', 'audience': 'private'}]})
        ctx = self.context()
        result = voice_tools.dispatch('get_calendar_events', {'start_date': today, 'end_date': today}, ctx)
        self.assertEqual([r['title'] for r in result['events']], ['Soccer'])
        result = voice_tools.dispatch('assign_driver_to_event_fuzzy', {'event_name': 'Soccer', 'driver_name': 'Jeff', 'target_date': today}, ctx)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(storage.get_all_overrides()[0]['actor_kind'], 'household_voice')
        result = voice_tools.dispatch('assign_driver_to_event_fuzzy', {'event_name': 'Surprise', 'driver_name': 'Jeff', 'target_date': today}, ctx)
        self.assertEqual(result['status'], 'error')

    def test_message_cannot_impersonate_spoken_name(self):
        voice.intercept("It's Jeff", self.context())
        with patch.object(agent_tools_v2, '_post_chat_message') as post:
            voice_tools.dispatch('send_family_message', {'message_text': 'Dinner is ready', 'from_member': 'Jeff'}, self.context())
        self.assertTrue(post.call_args.args[1].get('system'))
        self.assertIn('Household voice', post.call_args.args[2])

    def test_household_direct_message_uses_relay_not_claimed_sender(self):
        with patch.object(agent_tools_v2, '_post_chat_message') as post:
            result = voice_tools.dispatch('send_direct_message', {'recipient_name': 'Jeff',
                                          'message_text': 'Please bring milk', 'from_member': 'Alex'}, self.context())
        self.assertEqual(result['status'], 'success')
        self.assertTrue(post.call_args.args[1].get('system'))
        self.assertEqual(post.call_args.kwargs['context']['actor_kind'], 'household_voice')
        result = voice_tools.dispatch('send_direct_message', {'recipient_name': 'external cleaner', 'message_text': 'hello'}, self.context())
        self.assertEqual(result['status'], 'refused')

    def test_approval_requires_pin_then_later_exact_confirmation(self):
        mid, _ = self.ask()
        voice.intercept("It's Jeff", self.context())
        result = approval.prepare(self.context(), mid, 'submit')
        self.assertEqual(result['status'], 'authentication')
        voice.intercept('My PIN is 1234', self.context())
        ctx = self.context()
        result = approval.after_verification(ctx)
        self.assertIn('$114.95', result['message'])
        self.assertEqual(approval.intercept('approve booking', ctx)['status'], 'refused')
        approval.prepare(self.context(), mid, 'submit')
        with patch.object(missions, 'start_browse', return_value='browse') as start:
            result = approval.intercept('approve booking', self.context())
            self.assertEqual(start.call_count, 1)
            self.assertEqual(storage.get_mission(mid)['voice_approval']['member_id'], 'jeff')
            approval.intercept('approve booking', self.context())
            self.assertEqual(start.call_count, 1)

    def test_readback_approval_survives_missing_and_short_fingerprint(self):
        from services import voice_fingerprint as fp
        profile = {'member_id': 'jeff', 'key': ['ha', 'assist_satellite.kitchen'],
                   'calibrated': True, 'vector': [float(i == 0) for i in range(256)]}
        with patch.object(fp, 'profiles', return_value=[profile]):
            voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen',
                                    'device_id': 'device', 'enabled': True, 'recognition_enabled': True}],
                            approvals_enabled=True)
            self.verify()  # no observation: PIN still establishes the bounded room session
            for kind, evidence in (('submit', None), ('release', {'vector': profile['vector'], 'seconds': .5})):
                mid, _ = self.ask(kind)
                ctx = self.context()
                approval.prepare(ctx, mid, kind)
                after = fp.apply(self.context(), evidence)
                self.assertEqual(after.generation, ctx.generation)
                with patch.object(missions, 'start_browse', return_value='browse') as start:
                    result = approval.intercept('approve booking' if kind == 'submit' else 'approve release', after)
                    self.assertEqual(result['status'], 'success')
                    self.assertEqual(start.call_count, 1)

    def test_bridge_failure_is_visible_without_exposing_extra_metadata(self):
        self.context(fingerprint_bridge={'available': False, 'reason': 'Assist pipeline controller is unavailable.',
                                         'version': '2026.10.1', 'vector': [1], 'secret': 'hidden'})
        bridge = voice.admin_state()['satellites'][0]['fingerprint_bridge']
        self.assertFalse(bridge['available'])
        self.assertEqual(set(bridge), {'available', 'reason', 'version'})

    def test_approval_request_before_name_continues_after_pin(self):
        mid, _ = self.ask()
        ctx = self.context()
        self.assertEqual(approval.prepare(ctx, mid, 'submit')['status'], 'authentication')
        self.assertTrue(voice.expects_reply(ctx))
        named = voice.intercept("It's Jeff", self.context())
        self.assertIn('PIN', named['message'])
        voice.intercept('1234', self.context())
        result = approval.after_verification(self.context())
        self.assertIn('$114.95', result['message'])

    def test_source_calendar_privacy_survives_merge_model_and_cache(self):
        from services import calendar
        raw = {'id': 'event', 'summary': 'Private appointment',
               'start': {'dateTime': '2026-10-14T10:00:00-04:00'},
               'end': {'dateTime': '2026-10-14T11:00:00-04:00'}}
        def fetch(cal_id, *args):
            return cal_id, [{**raw, 'visibility': 'private' if cal_id == 'private' else 'public'}]
        with patch.object(calendar, '_fetch_single_calendar', side_effect=fetch):
            events = calendar.fetch_upcoming_events(['private', 'public'])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].visibility, 'private')
        storage.set_cached_schedule({'events': [e.model_dump(mode='json') for e in events]})
        result = voice_tools.dispatch('get_calendar_events', {'start_date': '2026-10-14', 'end_date': '2026-10-14'}, self.verify())
        self.assertEqual(result['events'], [])

    def test_verification_audit_is_sanitized(self):
        self.verify()
        record = voice.admin_state()['auth_history'][-1]
        self.assertEqual(record['outcome'], 'verified')
        self.assertEqual(record['member_id'], 'jeff')
        self.assertEqual(set(record), {'at', 'ha_instance_id', 'satellite_id', 'member_id', 'outcome', 'by_member'})

    def test_mutation_and_provenance_roll_back_together(self):
        with patch.object(voice_tools, 'record_action', side_effect=RuntimeError('simulated audit write loss')):
            with self.assertRaises(RuntimeError):
                voice_tools.dispatch('add_shopping_items', {'items': 'milk'}, self.context())
        self.assertFalse(storage.shopping_items_table.all())

    def test_changed_submit_record_and_stale_readback_refuse(self):
        ctx = self.verify()
        mid, aid = self.ask()
        approval.prepare(ctx, mid, 'submit')
        rj = storage.get_mission_steps(mid)[0]['result_json']
        rj['facts']['fee'] = '$124.95'
        storage.update_mission_step(aid, {'result_json': rj})
        with patch.object(missions, 'start_browse') as start:
            self.assertEqual(approval.intercept('approve booking', self.context())['status'], 'refused')
            start.assert_not_called()
        approval.prepare(self.context(), mid, 'submit')
        voice._sessions[('ha', 'assist_satellite.kitchen')]['readback']['expires_at'] = time.time() - 1
        self.assertEqual(approval.intercept('approve booking', self.context())['status'], 'refused')

    def test_privacy_change_after_readback_refuses_voice_approval(self):
        self.verify()
        mid, _ = self.ask()
        approval.prepare(self.context(), mid, 'submit')
        storage.update_mission(mid, {'sensitivity': 'sensitive'})
        with patch.object(missions, 'start_browse') as start:
            self.assertEqual(approval.intercept('approve booking', self.context())['status'], 'refused')
            start.assert_not_called()

    def test_changed_contact_card_refuses_and_approved_values_remain_bound(self):
        self.verify()
        mid, _ = self.ask('release')
        approval.prepare(self.context(), mid, 'release')
        self.settings['contact_email'] = 'changed@example.test'
        with patch.object(missions, 'start_browse') as start:
            self.assertEqual(approval.intercept('approve release', self.context())['status'], 'refused')
            start.assert_not_called()
        approval.prepare(self.context(), mid, 'release')
        with patch.object(missions, 'start_browse', return_value='browse'):
            approval.intercept('approve release', self.context())
        self.settings['contact_email'] = 'later@example.test'
        self.assertEqual(missions._released_for(storage.get_mission(mid), 'merchant.test')['email'], 'changed@example.test')

    def test_release_uses_validated_record_not_an_earlier_read(self):
        import copy
        self.verify()
        self.settings['contact_phone'] = '555-0100'
        mid, _ = self.ask('release')
        approval.prepare(self.context(), mid, 'release')
        original = storage.get_mission_steps
        calls = []
        def alternating_read(mission_id):
            rows = original(mission_id)
            calls.append(True)
            if len(calls) == 1:
                rows = copy.deepcopy(rows)
                rows[-1]['result_json']['site'] = 'other.test'
                rows[-1]['result_json']['fields'].append('phone')
                rows[-1]['result_json']['browse']['site'] = 'other.test'
            return rows
        with patch.object(storage, 'get_mission_steps', side_effect=alternating_read), \
                patch.object(missions, 'start_browse', return_value='browse') as start:
            result = approval.intercept('approve release', self.context())
        self.assertEqual(result['status'], 'success')
        self.assertEqual(start.call_args.args[2], 'merchant.test')
        self.assertEqual(set(start.call_args.kwargs['released']), {'first_name', 'email'})

    def test_child_missing_pin_and_approval_switch_refuse(self):
        mid, _ = self.ask()
        self.assertEqual(approval.prepare(self.verify('Alex', '9876'), mid, 'submit')['status'], 'refused')
        storage.clear_member_pin('jeff')
        self.assertNotEqual(self.verify().level, 'verified')
        config = voice.configuration()
        voice.configure(True, config['satellites'], approvals_enabled=False)
        self.assertEqual(approval.prepare(self.context(), mid, 'submit')['status'], 'refused')

    def test_phone_recovery_requires_personal_parent_even_in_audit_mode(self):
        import main
        from fastapi import HTTPException
        parent = storage.create_member_token('jeff')
        kid = storage.create_member_token('kid')
        house = storage.create_member_token('jeff', house_session=True)
        for token in (None, kid, house):
            with self.assertRaises(HTTPException):
                main.voice_identity_state(self.request(member_token=token))
        self.assertTrue(main.voice_identity_state(self.request(member_token=parent))['enabled'])

    def test_ha_registry_metadata_and_older_device_mapping(self):
        path = Path(__file__).resolve().parents[2] / 'homeassistant/custom_components/chauffeur_conversation/voice.py'
        package = ModuleType('voice_metadata_test')
        package.__path__ = [str(path.parent)]
        spec = importlib.util.spec_from_file_location('voice_metadata_test.voice', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        helpers = ModuleType('homeassistant.helpers')
        helpers.entity_registry = SimpleNamespace(async_get=lambda _: SimpleNamespace(async_get=lambda entity: SimpleNamespace(device_id='device') if entity == 'assist_satellite.kitchen' else None))
        helpers.device_registry = SimpleNamespace(async_get=lambda _: SimpleNamespace(async_get=lambda device: object() if device == 'device' else None))
        async def installation(_): return 'ha'
        helpers.instance_id = SimpleNamespace(async_get=installation)
        bridge = SimpleNamespace(status=lambda _: {'available': False, 'reason': 'Choose an STT delegate.'})
        with patch.dict(sys.modules, {'homeassistant': ModuleType('homeassistant'), 'homeassistant.helpers': helpers,
                                     'voice_metadata_test': package, 'voice_metadata_test.pipeline_bridge': bridge}):
            value = asyncio.run(module.metadata(None, SimpleNamespace(device_id='device'), {'device': 'assist_satellite.kitchen'}))
            self.assertEqual(value['satellite_id'], 'assist_satellite.kitchen')
            value = asyncio.run(module.metadata(None, SimpleNamespace(device_id='forged', satellite_id='assist_satellite.kitchen')))
            self.assertIsNone(value['satellite_id'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
