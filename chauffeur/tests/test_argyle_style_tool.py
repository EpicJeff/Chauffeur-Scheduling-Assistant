"""Asking Argyle to change how it talks (Task 3 of docs/superpowers/plans/2026-11-11-argyle-style.md).

"Talk like a pirate" sets the speaker's OWN style; anyone may, kids included. The
household style is a parent's to change, and only when they say so. A voice Argyle
does not know, and the shared wall panel, change nothing. A style request is never
stored as a memory row.

Run from chauffeur/:  python tests/test_argyle_style_tool.py
"""
import inspect
import types
import unittest

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import access, agent_router, agent_tools_v2, argyle_memory, argyle_style, storage, voice_tools

PARENT = {'id': 'm_mom', 'name': 'Lorena', 'role': 'parent'}
ADULT = {'id': 'm_gran', 'name': 'Gran', 'role': 'adult'}
KID = {'id': 'm_lily', 'name': 'Lily', 'role': 'child'}


def voice(level, member=None, recognised=False):
    ctx = types.SimpleNamespace(level=level, member=lambda: member,
                                verified_member=lambda: member if level == 'verified' else None,
                                actor=lambda: member if recognised else None)
    ctx.ha_instance_id, ctx.service_revision = '', ''
    ctx.provenance = lambda: {}
    return ctx


class StyleTool(unittest.TestCase):
    def setUp(self):
        self.orig = {}

        def stub(mod, name, value):
            self.orig[(mod, name)] = getattr(mod, name)
            setattr(mod, name, value)
        self.settings = {}
        tests = self
        stub(storage, 'get_settings', lambda: dict(tests.settings))
        stub(storage, 'patch_settings', lambda data: tests.settings.update(data))
        stub(storage, 'update_settings', lambda data: (tests.settings.clear(), tests.settings.update(data)))
        self.recorded = []
        stub(voice_tools, 'record_action', lambda *a, **kw: tests.recorded.append(a))
        with storage.db_lock:
            storage.members_table.truncate()
            storage.argyle_memories_table.truncate()
        for m in (PARENT, ADULT, KID):
            storage.add_member(dict(m))

    def tearDown(self):
        for (mod, name), value in self.orig.items():
            setattr(mod, name, value)
        with storage.db_lock:
            storage.members_table.truncate()
            storage.argyle_memories_table.truncate()

    def mine(self, member):
        return argyle_style.get_member_style(member['id'])

    def test_anyone_sets_their_own_kids_included(self):
        res = agent_tools_v2.style(action='set', scope='me', style='custom', custom='a cheerful pirate',
                                   acting_member=KID)
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.mine(KID), {'style': 'custom', 'custom': 'a cheerful pirate'})
        self.assertEqual(self.mine(PARENT)['style'], 'household', 'only the speaker changes')
        res = agent_tools_v2.style(action='reset', scope='me', acting_member=KID)
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.mine(KID)['style'], 'household')

    def test_only_a_parent_sets_the_household(self):
        for who in (KID, ADULT):
            res = agent_tools_v2.style(action='set', scope='household', style='plain', acting_member=who)
            self.assertEqual(res['status'], 'error', (who, res))
            self.assertIn('parent', res['message'].lower())
        self.assertEqual(argyle_style.household(), ('warm', ''))
        res = agent_tools_v2.style(action='set', scope='household', style='plain', acting_member=PARENT)
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(argyle_style.household(), ('plain', ''))
        res = agent_tools_v2.style(action='reset', scope='household', acting_member=PARENT)
        self.assertEqual(argyle_style.household(), ('warm', ''))

    def test_nobody_and_the_shared_panel_change_nothing(self):
        for who in (None, access.HOUSE, access.HOUSE_PARENT):
            for scope in ('me', 'household'):
                res = agent_tools_v2.style(action='set', scope=scope, style='playful', acting_member=who)
                self.assertEqual(res['status'], 'error', (who, scope, res))
        self.assertEqual(argyle_style.household(), ('warm', ''))

    def test_unknown_style_is_an_error(self):
        res = agent_tools_v2.style(action='set', scope='me', style='loud', acting_member=KID)
        self.assertEqual(res['status'], 'error', res)

    def test_show_says_what_applies(self):
        agent_tools_v2.style(action='set', scope='me', style='playful', acting_member=KID)
        res = agent_tools_v2.style(action='show', acting_member=KID)
        self.assertEqual(res['status'], 'success', res)
        self.assertIn('Playful', res['message'])

    def test_by_voice(self):
        res = voice_tools.dispatch('style', {'action': 'set', 'scope': 'me', 'style': 'custom',
                                             'custom': 'a pirate'}, voice('unknown'))
        self.assertNotEqual(res.get('status'), 'success', res)
        self.assertEqual(self.mine(KID)['style'], 'household')
        res = voice_tools.dispatch('style', {'action': 'set', 'scope': 'me', 'style': 'custom',
                                             'custom': 'a pirate'}, voice('named', KID, recognised=True))
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.mine(KID)['custom'], 'a pirate')
        self.assertTrue(self.recorded, 'a spoken change is recorded like every other voice action')
        # A parent PIN-unlocked the satellite; a voice nobody recognised speaks next.
        for scope in ('me', 'household'):
            res = voice_tools.dispatch('style', {'action': 'set', 'scope': scope, 'style': 'playful'},
                                       voice('verified', PARENT, recognised=False))
            self.assertNotEqual(res.get('status'), 'success', (scope, res))
        self.assertEqual(self.mine(PARENT)['style'], 'household', 'an unrecognised voice spent the PIN')
        self.assertEqual(argyle_style.household(), ('warm', ''))

    def test_wiring(self):
        tools = [t for t in agent_tools_v2.get_available_tools() if t['name'] == 'style']
        self.assertEqual(len(tools), 1, 'declared once')
        props = tools[0]['parameters']['properties']
        self.assertEqual(set(props['action']['enum']), {'set', 'show', 'reset'})
        self.assertEqual(set(props['scope']['enum']), {'me', 'household'})
        self.assertEqual(set(props['style']['enum']), {'plain', 'warm', 'playful', 'custom'})
        self.assertIn('style', voice_tools.TOOLS)
        self.assertIn('style', voice_tools.SPEAKABLE)
        # The router hands the caller's identity to the tool, never the model's arguments.
        res = agent_tools_v2.execute_tool('style', {'action': 'set', 'scope': 'household', 'style': 'plain',
                                                    'acting_member': PARENT}, actor=KID)
        self.assertEqual(res['status'], 'error', res)
        src = inspect.getsource(agent_router)
        self.assertIn('"style"', src[src.index('elif func_name in ("list_situations"'):][:900],
                      'the chat router never routes the style tool with the caller as actor')

    def test_a_style_request_is_not_a_memory(self):
        memory_tool = next(t for t in agent_tools_v2.get_available_tools() if t['name'] == 'memory')
        self.assertIn('how Argyle talks goes to style', memory_tool['description'])
        self.assertIn('how Argyle talks goes to style', argyle_memory.prompt_block())


if __name__ == '__main__':
    unittest.main()
