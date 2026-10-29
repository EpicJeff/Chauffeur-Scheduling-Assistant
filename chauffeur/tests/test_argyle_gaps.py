"""Where Argyle fell short is recorded, not noticed (services/argyle_gaps.py).

Three signals: the router's own view of a turn (tool errors, unknown tools, no answer),
the model's report_gap call made BEFORE it says it cannot, and a parent's vocabulary
correction. Deduplicated, listed under Config › People, exportable as a note.

Run from chauffeur/:  python tests/test_argyle_gaps.py
"""
import types
import unittest
from unittest.mock import patch

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_router, agent_tools_v2, argyle_gaps, argyle_memory, ha_api, storage

PARENT = {'id': 'm_mom', 'name': 'Lorena', 'role': 'parent'}
KID = {'id': 'm_lily', 'name': 'Lily', 'role': 'child'}


def _route(text, rounds, **kw):
    """`rounds` is a list of model replies; the last one repeats if the loop asks for more."""
    orig = agent_router.call_gemma_with_fallback
    seen = {'prompts': [], 'systems': []}

    def fake(prompt, tools_, system):
        seen['prompts'].append(prompt)
        seen['systems'].append(system)
        seen.setdefault('declared', {t['name'] for t in tools_})
        i = min(len(seen['prompts']) - 1, len(rounds) - 1)
        return dict(rounds[i])
    agent_router.call_gemma_with_fallback = fake
    try:
        return agent_router.process_agent_request(text, **kw), seen
    finally:
        agent_router.call_gemma_with_fallback = orig


class ArgyleGapsTests(unittest.TestCase):
    def setUp(self):
        self.orig = {}

        def stub(mod, name, value):
            self.orig[(mod, name)] = getattr(mod, name)
            setattr(mod, name, value)
        self.stub = stub
        stub(ha_api, 'mode', lambda: 'supervisor')
        stub(ha_api, 'get_states', lambda ttl=5: [])
        stub(ha_api, 'get_entity_registry', lambda ttl=300: [])
        stub(ha_api, 'get_area_map', lambda ttl=60: [])
        stub(ha_api, 'get_device_registry', lambda ttl=300: [])
        stub(ha_api, 'get_exposed', lambda ttl=60: {})
        self.settings = {'calendar_ids': []}
        tests = self
        stub(storage, 'get_settings', lambda: dict(tests.settings))
        stub(storage, 'update_settings', lambda data: (tests.settings.clear(), tests.settings.update(data)))
        with storage.db_lock:
            storage.members_table.truncate()
            storage.argyle_gaps_table.truncate()
            storage.argyle_memories_table.truncate()
        storage.add_member(dict(PARENT))
        storage.add_member(dict(KID))

    def tearDown(self):
        for (mod, name), value in self.orig.items():
            setattr(mod, name, value)
        with storage.db_lock:
            storage.members_table.truncate()
            storage.argyle_gaps_table.truncate()
            storage.argyle_memories_table.truncate()

    # --- the store ----------------------------------------------------------------
    def test_the_same_gap_twice_is_one_row_counted_and_a_fixed_one_reopens(self):
        a = argyle_gaps.record('no_tool', asked='open the pod bay doors', source='chat', acting_member=PARENT,
                               tool='open_pod_bay_doors', message='Unknown tool: open_pod_bay_doors')
        b = argyle_gaps.record('no_tool', asked='pod bay doors please', source='voice', tool='open_pod_bay_doors',
                               message='Unknown tool: open_pod_bay_doors')
        self.assertEqual(a['id'], b['id'])
        rows = argyle_gaps.list_gaps()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['count'], rows[0]['asked'], rows[0]['source'], rows[0]['who_name']),
                         (2, 'pod bay doors please', 'voice', 'Lorena'))
        self.assertEqual(argyle_gaps.set_status(a['id'], 'fixed', version='2.499.721')['status'], 'success')
        self.assertEqual(argyle_gaps.list_gaps('open'), [])
        self.assertEqual(argyle_gaps.list_gaps('fixed')[0]['fixed_version'], '2.499.721')
        again = argyle_gaps.record('no_tool', asked='pod bay doors', tool='open_pod_bay_doors',
                                   message='Unknown tool: open_pod_bay_doors')
        self.assertEqual((again['status'], again['count'], again['reopened']), ('open', 3, True),
                         'a gap that comes back after a fix is open again, never silently counted under fixed')
        self.assertEqual(argyle_gaps.set_status(a['id'], 'nonsense')['status'], 'error')

    def test_service_trouble_and_refusals_are_never_gaps(self):
        for msg in ('Home Assistant is not connected.', 'The AI service is overloaded right now',
                    'That needs your phone.', 'Only a parent or adult can unlock that.', 'Which device do you mean?'):
            self.assertIsNone(argyle_gaps.record('tool_error', asked='x', tool='house', message=msg), msg)
        self.assertEqual(argyle_gaps.list_gaps('all'), [])

    # --- the router's own view of a turn -------------------------------------------
    def test_an_unknown_tool_and_a_failing_tool_are_recorded_from_the_turn(self):
        self.stub(ha_api, 'get_states', lambda ttl=5: (_ for _ in ()).throw(RuntimeError('boom')))
        res, seen = _route('open the pod bay doors and find the hall light', [
            {'tool_calls': [{'name': 'open_pod_bay_doors', 'arguments': {}},
                            {'name': 'house', 'arguments': {'action': 'find', 'query': 'hall light'}}], 'message': ''},
            {'tool_calls': [], 'message': 'I could not.'}], acting_member=PARENT)
        self.assertEqual(res['status'], 'success', res)
        rows = {r['kind']: r for r in argyle_gaps.list_gaps()}
        self.assertEqual(set(rows), {'no_tool', 'tool_error'}, rows)
        self.assertEqual(rows['no_tool']['tool'], 'open_pod_bay_doors')
        self.assertEqual(rows['no_tool']['asked'], 'open the pod bay doors and find the hall light')
        self.assertEqual((rows['no_tool']['who'], rows['no_tool']['source']), ('m_mom', 'admin'))
        self.assertEqual(rows['tool_error']['tool'], 'house')
        self.assertIn('could not answer', rows['tool_error']['message'])

    def test_a_turn_that_ends_with_no_answer_is_a_gap(self):
        res, _ = _route('what is the meaning of the garage', [{'tool_calls': [], 'message': ''}], acting_member=PARENT)
        self.assertEqual(res['status'], 'error')
        rows = argyle_gaps.list_gaps()
        self.assertEqual([r['kind'] for r in rows], ['no_answer'])
        self.assertEqual(rows[0]['asked'], 'what is the meaning of the garage')

    def test_a_turn_with_only_good_results_records_nothing(self):
        _route('find the hall light', [
            {'tool_calls': [{'name': 'house', 'arguments': {'action': 'find', 'query': 'hall light'}}], 'message': ''},
            {'tool_calls': [], 'message': 'No such light.'}], acting_member=PARENT)
        self.assertEqual(argyle_gaps.list_gaps('all'), [])
        # A tool called with arguments it cannot use IS a gap: the model misused it, or the
        # tool should have coped ('what is on the calendar' with no dates, live 2026-10-29).
        _route('what is on the calendar', [
            {'tool_calls': [{'name': 'get_calendar_events', 'arguments': {}}], 'message': ''},
            {'tool_calls': [], 'message': 'Nothing today.'}], acting_member=PARENT)
        self.assertEqual([r['tool'] for r in argyle_gaps.list_gaps()], ['get_calendar_events'])

    # --- the model's own note ----------------------------------------------------------
    def test_report_gap_carries_the_persons_words_and_the_last_answer_from_the_router(self):
        """The model says what was missing; the router says what was asked, where, by whom and
        what Argyle had just said. The model's own 'asked' is never trusted."""
        history = [{'role': 'user', 'content': 'are all the doors locked'},
                   {'role': 'assistant', 'content': 'Yes, all the doors are locked.'}]
        res, seen = _route("that's wrong, the kia was unlocked", [
            {'tool_calls': [{'name': 'report_gap', 'arguments': {
                'kind': 'wrong', 'what_was_asked': 'MODEL SAID THIS', 'asked': 'MODEL SAID THIS',
                'what_was_missing': 'answered yes without reading every lock'}}], 'message': ''},
            {'tool_calls': [], 'message': 'Noted.'}], acting_member=PARENT, history=history, source='pwa')
        rows = argyle_gaps.list_gaps()
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row['kind'], 'wrong')
        self.assertEqual(row['asked'], "that's wrong, the kia was unlocked")
        self.assertEqual(row['prior'], 'Yes, all the doors are locked.')
        self.assertEqual(row['message'], 'answered yes without reading every lock')
        self.assertEqual((row['source'], row['who_name']), ('pwa', 'Lorena'))
        self.assertIn("report_gap(kind='cannot')", seen['systems'][0],
                      'the prompt never tells the model to note a gap before saying it cannot')
        self.assertIn("report_gap(kind='wrong')", seen['systems'][0])

    def test_report_gap_is_declared_once_and_reaches_voice(self):
        tools = [t for t in agent_tools_v2.get_available_tools() if t['name'] == 'report_gap']
        self.assertEqual(len(tools), 1)
        self.assertIn('before', tools[0]['description'].lower())
        self.assertNotIn('asked', tools[0]['parameters']['properties'], 'the person\'s words are the router\'s to give')
        res = agent_tools_v2.execute_tool('report_gap', {'kind': 'cannot', 'what_was_asked': 'water the garden',
                                                         'what_was_missing': 'no irrigation tool'}, actor=KID)
        self.assertEqual(res['status'], 'success', res)
        self.assertIn('cannot do that yet', res['message'])
        self.assertEqual(argyle_gaps.list_gaps()[0]['who_name'], 'Lily', 'a kid hitting a wall is still a gap')
        from services import voice_tools
        self.assertIn('report_gap', voice_tools.TOOLS)
        ctx = types.SimpleNamespace(level='unknown', member=lambda: None, verified_member=lambda: None,
                                    ha_instance_id='', service_revision='', provenance=lambda: {})
        res = voice_tools.dispatch('report_gap', {'kind': 'cannot', 'what_was_missing': 'cannot start the car',
                                                  'asked': 'start my car'}, ctx)
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(argyle_gaps.list_gaps()[0]['source'], 'voice')

    # --- a correction the family made by hand ---------------------------------------------
    def test_a_vocabulary_memory_is_a_gap_the_family_closed(self):
        self.stub(ha_api, 'get_states', lambda ttl=5: [{'entity_id': 'lock.a', 'state': 'locked', 'attributes': {}}])
        res = argyle_memory.remember(kind='vocabulary', phrase='the beach doors', text='the beach apartment locks',
                                     entity_ids=['lock.a'], acting_member=PARENT, source='voice')
        self.assertEqual(res['status'], 'success', res)
        rows = argyle_gaps.list_gaps()
        self.assertEqual([r['kind'] for r in rows], ['taught'])
        self.assertIn('the beach doors', rows[0]['asked'])
        self.assertEqual(rows[0]['source'], 'voice')

    # --- the page and the note ----------------------------------------------------------------
    def test_the_people_page_lists_marks_fixed_and_exports_as_a_parent_only(self):
        argyle_gaps.record('cannot', asked='water the garden', source='chat', acting_member=PARENT,
                           message='no irrigation tool')
        gid = argyle_gaps.list_gaps()[0]['id']
        from fastapi.testclient import TestClient
        import main
        parent = {'X-Member-Token': storage.create_member_token('m_mom')}
        kid = {'X-Member-Token': storage.create_member_token('m_lily')}
        with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
            client = TestClient(main.app)
            r = client.get('/api/argyle/gaps', headers=parent)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual([g['asked'] for g in r.json()['gaps']], ['water the garden'])
            self.assertIn(r.status_code, (200,))
            self.assertIn(client.get('/api/argyle/gaps', headers=kid).status_code, (401, 403))
            r = client.get('/api/argyle/gaps.md', headers=parent)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertIn('water the garden', r.text)
            self.assertIn('no irrigation tool', r.text)
            self.assertIn(client.get('/api/argyle/gaps.md', headers=kid).status_code, (401, 403))
            r = client.post(f'/api/argyle/gaps/{gid}/status', json={'status': 'fixed', 'version': '2.499.721'}, headers=kid)
            self.assertIn(r.status_code, (401, 403))
            r = client.post(f'/api/argyle/gaps/{gid}/status', json={'status': 'fixed', 'version': '2.499.721'}, headers=parent)
            self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(argyle_gaps.list_gaps('fixed')[0]['fixed_version'], '2.499.721')
        src = open('templates/config.html', encoding='utf-8').read()
        self.assertIn('/api/argyle/gaps', src, 'no hand path on the People page')
        block = src[src.index('/api/argyle/gaps') - 3000:src.index('/api/argyle/gaps') + 4000]
        self.assertNotIn('confirm(', block.replace('promptConfirm(', ''), 'browser dialogs are banned')
        self.assertNotIn('prompt(', block.replace('promptInput(', '').replace('promptConfirm(', ''))


if __name__ == '__main__':
    unittest.main()
