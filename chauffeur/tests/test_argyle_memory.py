"""Argyle's memory: what the family taught it, kept as rows, read on every surface.

2026-10-29: "remember X" wrote one text blob that only the solver's pattern prompt
ever read; Argyle's chat and voice never saw it, each save overwrote the last, and
no page listed it. Now `memory` is a tool on every surface (chat, PWA, voice), a
parent or adult's correction is remembered without being asked, the rows ride the
system prompt, vocabulary rows become names the house tool answers to, and
Config › People lists and forgets them.

Run from chauffeur/:  python tests/test_argyle_memory.py
"""
import types
import unittest
from unittest.mock import patch

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_tools_v2, argyle_memory, ha_api, house, storage

PARENT = {'id': 'm_mom', 'name': 'Lorena', 'role': 'parent'}
KID = {'id': 'm_lily', 'name': 'Lily', 'role': 'child'}


def _states():
    return [
        {'entity_id': 'binary_sensor.front_entry', 'state': 'off', 'last_changed': '2026-10-29T06:00:00+00:00',
         'attributes': {'friendly_name': 'Front door Entry Door', 'device_class': 'door'}},
        {'entity_id': 'binary_sensor.garage_entry', 'state': 'off', 'last_changed': '2026-10-29T06:00:00+00:00',
         'attributes': {'friendly_name': 'Garage Entry Door', 'device_class': 'door'}},
        {'entity_id': 'binary_sensor.ev9_front_left_door', 'state': 'off', 'last_changed': '2026-10-29T06:00:00+00:00',
         'attributes': {'friendly_name': 'Kia EV9 Front Left Door', 'device_class': 'door'}},
        {'entity_id': 'light.hall', 'state': 'off', 'last_changed': '2026-10-29T06:00:00+00:00',
         'attributes': {'friendly_name': 'Hall Light'}},
    ]


REGISTRY = [{'entity_id': s['entity_id'], 'name': None, 'original_name': s['attributes']['friendly_name'],
             'aliases': [], 'area_id': None, 'device_id': None, 'hidden_by': None, 'disabled_by': None,
             'platform': 'x'} for s in _states()]


def voice(level, member=None):
    ctx = types.SimpleNamespace(level=level, member=lambda: member,
                                verified_member=lambda: member if level == 'verified' else None)
    ctx.ha_instance_id, ctx.service_revision = '', ''
    ctx.provenance = lambda: {}
    return ctx


class ArgyleMemoryTests(unittest.TestCase):
    def setUp(self):
        self.orig = {}

        def stub(mod, name, value):
            self.orig[(mod, name)] = getattr(mod, name)
            setattr(mod, name, value)
        self.states = _states()
        stub(ha_api, 'get_states', lambda ttl=5: self.states)
        stub(ha_api, 'get_entity_registry', lambda ttl=300: REGISTRY)
        stub(ha_api, 'get_area_map', lambda ttl=60: [])
        stub(ha_api, 'get_device_registry', lambda ttl=300: [])
        stub(ha_api, 'get_exposed', lambda ttl=60: {})
        stub(ha_api, 'mode', lambda: 'supervisor')
        # harness pins storage.get_settings to a constant; the memory blob needs a real store.
        self.settings = {'calendar_ids': []}
        tests = self
        stub(storage, 'get_settings', lambda: dict(tests.settings))
        stub(storage, 'update_settings', lambda data: (tests.settings.clear(), tests.settings.update(data)))
        with storage.db_lock:
            storage.members_table.truncate()
            storage.argyle_memories_table.truncate()
        storage.add_member(dict(PARENT))
        storage.add_member(dict(KID))

    def tearDown(self):
        for (mod, name), value in self.orig.items():
            setattr(mod, name, value)
        with storage.db_lock:
            storage.members_table.truncate()
            storage.argyle_memories_table.truncate()

    # --- who may teach ---------------------------------------------------------
    def test_a_parent_is_remembered_without_being_asked_and_a_kid_is_not(self):
        res = agent_tools_v2.memory(action='remember', text='Answer with every lock, never a summary',
                                    acting_member=PARENT, source='chat')
        self.assertEqual(res['status'], 'success', res)
        rows = argyle_memory.list_memories()
        self.assertEqual([r['text'] for r in rows], ['Answer with every lock, never a summary'])
        self.assertEqual((rows[0]['kind'], rows[0]['by'], rows[0]['by_name'], rows[0]['source']),
                         ('preference', 'm_mom', 'Lorena', 'chat'))
        res = agent_tools_v2.memory(action='remember', text='the doors means the pool house', acting_member=KID)
        self.assertEqual(res['status'], 'refused', res)
        self.assertIn('parent', res['message'].lower())
        self.assertEqual(len(argyle_memory.list_memories()), 1)
        res = agent_tools_v2.memory(action='remember', text='anything', acting_member=None)
        self.assertEqual(res['status'], 'refused')

    def test_remember_appends_and_never_overwrites(self):
        for text in ('first', 'second'):
            agent_tools_v2.memory(action='remember', text=text, acting_member=PARENT)
        self.assertEqual([r['text'] for r in argyle_memory.list_memories()], ['first', 'second'])
        res = agent_tools_v2.memory(action='remember', text='second', acting_member=PARENT)
        self.assertEqual(res['status'], 'success')
        self.assertEqual(len(argyle_memory.list_memories()), 2, 'saying it twice stores it once')

    # --- the rows reach the model and the house tool ---------------------------
    def test_the_prompt_block_carries_every_row_on_every_surface(self):
        agent_tools_v2.memory(action='remember', text='Answer with every lock', acting_member=PARENT)
        agent_tools_v2.memory(action='remember', kind='vocabulary', phrase='the entry doors',
                              text='the entry doors are the house doors, not the cars',
                              entity_ids=['binary_sensor.front_entry', 'binary_sensor.garage_entry'],
                              acting_member=PARENT)
        block = argyle_memory.prompt_block()
        self.assertIn('WHAT THE FAMILY TAUGHT ME', block)
        self.assertIn('Answer with every lock', block)
        self.assertIn("'the entry doors'", block)
        self.assertIn("memory(action='remember'", block)
        self.assertIn('binary_sensor.front_entry', block)
        import inspect
        from services import agent_router
        src = inspect.getsource(agent_router)
        self.assertIn('argyle_memory.prompt_block()', src, 'the router never loads what the family taught')
        self.assertIn("memory(action='remember'", src, 'the prompt never tells the model to remember a correction')

    def test_a_vocabulary_row_is_a_name_the_house_tool_answers_to(self):
        """'the entry doors' finds nothing by name today; once taught, it finds exactly those
        entities and never the Kia's doors, and the category tally steps aside for the name."""
        res = house.house(action='find', query='the house doors')
        self.assertNotEqual([c['entity_id'] for c in res['candidates'][:2]],
                            ['binary_sensor.front_entry', 'binary_sensor.garage_entry'])
        self.assertIn('categories', res, 'before teaching, "doors" is the category tally')
        agent_tools_v2.memory(action='remember', kind='vocabulary', phrase='the house doors',
                              text='the house doors are the entry doors, not the cars',
                              entity_ids=['binary_sensor.front_entry', 'binary_sensor.garage_entry'],
                              acting_member=PARENT)
        res = house.house(action='find', query='the house doors')
        self.assertEqual([c['entity_id'] for c in res['candidates'][:2]],
                         ['binary_sensor.front_entry', 'binary_sensor.garage_entry'], res['candidates'])
        self.assertIn('the house doors', res['candidates'][0]['aliases'])
        self.assertNotIn('categories', res, 'the words said are now a name; the tally steps aside')
        read = house.house(action='read', query='house doors')
        self.assertEqual(read['status'], 'ambiguous', read)
        self.assertEqual([c['entity_id'] for c in read['candidates'][:2]],
                         ['binary_sensor.front_entry', 'binary_sensor.garage_entry'])

    def test_a_vocabulary_row_needs_a_phrase_and_entities_that_exist(self):
        res = agent_tools_v2.memory(action='remember', kind='vocabulary', text='x', acting_member=PARENT)
        self.assertEqual(res['status'], 'error')
        res = agent_tools_v2.memory(action='remember', kind='vocabulary', phrase='the pool', text='x',
                                    entity_ids=['light.nope'], acting_member=PARENT)
        self.assertEqual(res['status'], 'error', res)
        self.assertIn('light.nope', res['message'])
        self.assertEqual(argyle_memory.list_memories(), [])

    # --- forgetting -------------------------------------------------------------
    def test_forget_by_id_or_by_words_and_list(self):
        agent_tools_v2.memory(action='remember', text='Short answers on voice', acting_member=PARENT)
        agent_tools_v2.memory(action='remember', text='Say the room with every light', acting_member=PARENT)
        res = agent_tools_v2.memory(action='list', acting_member=KID)
        self.assertEqual(res['status'], 'success')
        self.assertEqual(len(res['memories']), 2, 'anyone may ask what Argyle was taught')
        rid = res['memories'][0]['id']
        res = agent_tools_v2.memory(action='forget', memory_id=rid, acting_member=KID)
        self.assertEqual(res['status'], 'refused')
        res = agent_tools_v2.memory(action='forget', memory_id=rid, acting_member=PARENT)
        self.assertEqual(res['status'], 'success', res)
        res = agent_tools_v2.memory(action='forget', text='every light', acting_member=PARENT)
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(argyle_memory.list_memories(), [])
        res = agent_tools_v2.memory(action='forget', text='nothing like this', acting_member=PARENT)
        self.assertEqual(res['status'], 'error')

    # --- the old blob -------------------------------------------------------------
    def test_the_old_memory_blob_becomes_a_row_once(self):
        settings = storage.get_settings()
        settings['ai_memory'] = 'Always say which car.'
        storage.update_settings(settings)
        rows = argyle_memory.list_memories()
        self.assertEqual([r['text'] for r in rows], ['Always say which car.'])
        self.assertEqual(rows[0]['by_name'], 'earlier memory')
        self.assertEqual(len(argyle_memory.list_memories()), 1, 'migrated once, never twice')
        self.assertEqual(storage.get_settings().get('ai_memory'), 'Always say which car.',
                         'the blob stays for the solver prompt that still reads it')

    # --- wiring: declared once, every surface -------------------------------------
    def test_the_tool_is_declared_once_and_reaches_chat_pwa_and_voice(self):
        tools = [t for t in agent_tools_v2.get_available_tools() if t['name'] == 'memory']
        self.assertEqual(len(tools), 1)
        self.assertEqual(set(tools[0]['parameters']['properties']['action']['enum']), {'remember', 'forget', 'list'})
        self.assertIn('correct', tools[0]['description'].lower())
        res = agent_tools_v2.execute_tool('memory', {'action': 'remember', 'text': 'via execute_tool',
                                                     'acting_member': {'id': 'x', 'role': 'parent'}}, actor=PARENT)
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(argyle_memory.list_memories()[-1]['by'], 'm_mom', 'identity is the caller, never the arguments')
        res = agent_tools_v2.execute_tool('memory', {'action': 'remember', 'text': 'via a kid'}, actor=KID)
        self.assertEqual(res['status'], 'refused')
        from services import voice_tools
        self.assertIn('memory', voice_tools.TOOLS)
        res = voice_tools.dispatch('memory', {'action': 'remember', 'text': 'spoken by a verified parent'},
                                   voice('verified', PARENT))
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(argyle_memory.list_memories()[-1]['source'], 'voice')
        res = voice_tools.dispatch('memory', {'action': 'remember', 'text': 'spoken by nobody'}, voice('unknown'))
        self.assertEqual(res['status'], 'refused', res)
        self.assertEqual(len([r for r in argyle_memory.list_memories() if r['text'] == 'spoken by nobody']), 0)
        import inspect
        from services import agent_router
        src = inspect.getsource(agent_router)
        self.assertIn('"memory"', src[src.index('elif func_name in ("list_situations"'):][:900],
                      'the chat router never routes the memory tool')

    def test_the_people_page_lists_and_forgets_as_a_parent_and_never_as_a_kid(self):
        agent_tools_v2.memory(action='remember', text='Listed on the page', acting_member=PARENT)
        rid = argyle_memory.list_memories()[0]['id']
        from fastapi.testclient import TestClient
        import main
        parent = {'X-Member-Token': storage.create_member_token('m_mom')}
        kid = {'X-Member-Token': storage.create_member_token('m_lily')}
        with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
            client = TestClient(main.app)
            r = client.get('/api/argyle/memories', headers=parent)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual([m['text'] for m in r.json()['memories']], ['Listed on the page'])
            r = client.get('/api/argyle/memories', headers=kid)
            self.assertIn(r.status_code, (401, 403), r.text)
            r = client.post('/api/argyle/memories', json={'text': 'Typed on the page'}, headers=parent)
            self.assertEqual(r.status_code, 200, r.text)
            r = client.delete(f'/api/argyle/memories/{rid}', headers=kid)
            self.assertIn(r.status_code, (401, 403), r.text)
            r = client.delete(f'/api/argyle/memories/{rid}', headers=parent)
            self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([m['text'] for m in argyle_memory.list_memories()], ['Typed on the page'])
        src = open('templates/config.html', encoding='utf-8').read()
        self.assertIn("'api/argyle/memories'", src, 'no hand path on the People page')
        block = src[src.index('<details id="argyle-memory"'):src.index('<details id="people"')]
        self.assertNotIn("fetch('/api/", block, 'a root-relative URL leaves the add-on under HA ingress (device 2026-10-29)')
        self.assertIn("this.base() + 'api/argyle/memories'", block)
        self.assertNotIn('confirm(', block.replace('promptConfirm(', ''), 'browser dialogs are banned')


if __name__ == '__main__':
    unittest.main()
