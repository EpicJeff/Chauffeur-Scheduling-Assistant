"""Argyle's style reaches the prompt last, and each caller decides whose (Task 2 of
docs/superpowers/plans/2026-11-11-argyle-style.md).

The person's own style where the conversation is theirs alone (their chat, their
DM with Argyle, a recognised voice); the household's everywhere else (the wall
panel, the family channel, an unknown voice). The router never infers it from
acting_member: the family channel knows the sender, but everyone reads the reply.

Run from chauffeur/:  python tests/test_argyle_style_router.py
"""
import inspect
import re
import unittest
from unittest.mock import patch

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from fastapi.testclient import TestClient

import main
from services import agent_router, agent_tools_v2, argyle_style, storage

PIRATE = {'style': 'custom', 'custom': 'a cheerful pirate'}


def _member(mid, role, style=None):
    if not storage.get_member(mid):
        storage.add_member({'id': mid, 'name': mid.title(), 'role': role, 'status': 'active'})
    if style is not None:
        storage.update_member(mid, {'argyle_style': style})
    return storage.get_member(mid)


class StyleInThePrompt(unittest.TestCase):
    def setUp(self):
        self.kid = _member('kid', 'child', PIRATE)
        self.mum = _member('mum', 'parent', {'style': 'playful'})
        self.captured = {}
        tests = self

        def fake_llm(prompt, tools, system_prompt):
            tests.captured['system'] = system_prompt
            return {'message': 'ok', 'tool_calls': []}
        self.llm = patch.object(agent_router, 'call_gemma_with_fallback', side_effect=fake_llm)
        self.llm.start()

    def tearDown(self):
        self.llm.stop()

    def system(self, **kw):
        agent_router.process_agent_request('hello', **kw)
        return self.captured['system']

    def test_the_block_is_last(self):
        system = self.system(source='admin', acting_member=self.mum, style_member=self.mum)
        self.assertTrue(system.rstrip().endswith(argyle_style.prompt_block('playful', '').rstrip()),
                        'the style block must be the tail, after every rule')

    def test_a_default_family_gets_todays_prompt_plus_warm(self):
        with patch.object(storage, 'get_settings', return_value={**storage.get_settings(),
                                                                   'argyle_style': 'warm', 'argyle_style_custom': ''}):
            real = self.system(source='admin')
            with patch.object(argyle_style, 'prompt_block', return_value=''):
                bare = self.system(source='admin')
        clock = lambda text: re.sub(r'\d{1,2}:\d{2}', 'HH:MM', text)   # the two builds may straddle a minute
        self.assertEqual(clock(real), clock(bare + argyle_style.prompt_block('warm', '')))

    def test_acting_member_alone_never_picks_a_style(self):
        system = self.system(source='family', acting_member=self.kid)
        self.assertNotIn('a cheerful pirate', system, 'the family channel must not speak in a kid\'s style')

    def test_a_person_on_their_own_surface_gets_their_style(self):
        system = self.system(source='family', acting_member=self.kid, style_member=self.kid)
        self.assertIn('"a cheerful pirate"', system)


class CallersChoose(unittest.TestCase):
    """Each caller passes style_member; the router is stubbed to record it."""

    def setUp(self):
        self.kid = _member('kid', 'child', PIRATE)
        self.mum = _member('mum', 'parent')
        self.calls = []
        tests = self

        def record(*args, **kw):
            tests.calls.append(kw)
            return {'message': 'ok', 'status': 'success'}
        self.router = patch.object(agent_router, 'process_agent_request', side_effect=record)
        self.router.start()

    def tearDown(self):
        self.router.stop()

    def style_member_id(self):
        self.assertTrue(self.calls, 'the caller never reached the router')
        self.assertIn('style_member', self.calls[-1], 'the caller must say whose style applies')
        chosen = self.calls[-1]['style_member']
        return chosen.get('id') if chosen else None

    def mention(self, channel, sender):
        with patch.object(agent_tools_v2, '_post_chat_message', lambda *a, **kw: None), \
                patch.object(storage, 'get_channel_messages', lambda *a, **kw: []):
            main._run_argyle_mention(channel, sender, 'what is on today?')

    def test_the_argyle_dm_is_the_senders(self):
        self.mention({'id': 'c-dm', 'kind': 'dm', 'member_ids': ['kid', 'argyle']}, self.kid)
        self.assertEqual(self.style_member_id(), 'kid')

    def test_the_family_channel_is_the_households(self):
        self.mention({'id': 'c-fam', 'kind': 'group', 'member_ids': ['kid', 'mum', 'argyle']}, self.kid)
        self.assertIsNone(self.style_member_id())
        self.mention({'id': 'c-dm2', 'kind': 'dm', 'member_ids': ['kid', 'mum']}, self.kid)
        self.assertIsNone(self.style_member_id(), 'a DM between two people is not a conversation with Argyle')

    def chat(self, headers, body=None):
        with patch.object(storage, 'get_settings', side_effect=lambda: {
                **storage_settings, 'auth_enforce': True}), \
                patch('services.llm.auto_name_conversation', lambda *a, **kw: None):
            return TestClient(main.app).post('/api/chat', json={'message': 'hi', **(body or {})},
                                             headers=headers)

    def test_a_personal_chat_is_the_members(self):
        token = storage.create_member_token('kid', proof='password', minted_on='personal')
        r = self.chat({'X-Member-Token': token}, {'source': 'pwa'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.style_member_id(), 'kid')

    def test_the_wall_panel_is_the_households(self):
        _member('mum', 'parent')
        panel = storage.enrol_device_token('panel-style', 'Kitchen panel', by_member='mum')
        r = self.chat({'X-Device-Token': panel}, {'context': {'search': '?panel=true'}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(self.style_member_id())

    def test_voice_passes_the_recognised_actor(self):
        # The converse endpoint needs a live voice pipeline; its call is read here,
        # and test_voice_actor runs the actor path itself.
        src = inspect.getsource(main.converse_ha_assist)
        call = src[src.index("process_agent_request(req.text"):]
        call = call[:call.index(')\n')]
        self.assertIn('style_member=actor', call)


storage_settings = dict(storage.get_settings() or {})


if __name__ == '__main__':
    unittest.main()
