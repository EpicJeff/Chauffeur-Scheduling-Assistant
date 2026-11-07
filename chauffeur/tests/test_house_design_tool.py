"""Argyle in the house editor (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md section 7.4; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 11 and its
review amendments): the house_design tool edits through the same operations
as the hand path, refuses anyone but a parent, and a real agent turn through
POST /api/house/editor/say changes the house, is metered per provider request
as 'conversation', and stops cleanly at a spend checkpoint.

The provider HTTP layer (llm_budget.urlopen) is stubbed with Gemini bodies
whose text is the router's JSON contract; everything else is real.

Run from chauffeur/:  python tests/test_house_design_tool.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_design_tool_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import llm, storage  # noqa: E402
from services import agent_tools_v2  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_store as ts  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_edit_house.plan.json')
PRICED = next(iter(tc.PRICES))
PARENT_M = {'id': 'p1', 'name': 'Pat', 'role': 'parent'}
CHILD_M = {'id': 'k1', 'name': 'Kit', 'role': 'child'}


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Model:
    """Stands in for llm_budget.urlopen; answers each request with the next reply."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, request, timeout=60):
        self.requests.append(request)
        text = json.dumps(self.replies.pop(0) if self.replies else {'message': 'Done.', 'tool_calls': []})
        body = {'candidates': [{'content': {'parts': [{'text': text}]}, 'finishReason': 'STOP'}],
                'usageMetadata': {'promptTokenCount': 900, 'candidatesTokenCount': 80}}
        return _Response(json.dumps(body).encode('utf-8'))


_real_settings = storage.get_settings


def _enforced():
    return patch.object(storage, 'get_settings', side_effect=lambda: {**_real_settings(), 'auth_enforce': True})


def _seed():
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None, 'llm_provider': 'gemini',
                            'llm_gemini_api_key': 'k', 'llm_gemini_paid_api_key': 'paid-k'})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    with open(FIXTURE, encoding='utf-8') as f:
        ts.push_round(json.load(f), 'build')


def _section(plan, sid):
    return next(s for s in plan['buildings'][0]['roof']['sections'] if s['id'] == sid)


TOKENS = {}


def _people():
    if not TOKENS:
        storage.add_member(dict(PARENT_M))
        storage.add_member(dict(CHILD_M))
        TOKENS['parent'] = {'X-Member-Token': storage.create_member_token('p1')}
        TOKENS['child'] = {'X-Member-Token': storage.create_member_token('k1')}
    return TOKENS


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app)


def scenario_tool_is_registered_and_never_runs_from_a_mission():
    from services import missions
    check('house_design' in agent_tools_v2.TOOL_SCHEMAS and 'house_design' in agent_tools_v2.TOOL_HANDLERS, 'registered')
    check('house_design' in agent_tools_v2.REGISTRY_EXCEPTIONS, 'mission exception declared')
    check('house_design' not in missions.proposable_tools(), 'never offered to a mission, like house and music')


def scenario_tool_edits_through_the_same_operations():
    _seed()
    _people()
    out = agent_tools_v2.execute_tool('house_design', {'action': 'edit', 'edit': {
        'op': 'set', 'piece': 'roof-1', 'field': 'pitch', 'value': 8}}, actor=storage.get_member('p1'))
    check(out.get('status') == 'ok', out)
    s = _section(ts.current(), 'roof-1')
    check(s['pitch'] == 8 and s['pitch_source'] == 'person', s)
    status = agent_tools_v2.execute_tool('house_design', {'action': 'status'}, actor=storage.get_member('p1'))
    check(status.get('status') == 'ok' and (status.get('summary') or status.get('message')), status)
    check(len(json.dumps(status)) < 2000, 'status is a summary, never the plan')
    bad = agent_tools_v2.execute_tool('house_design', {'action': 'edit', 'edit': {
        'op': 'set', 'piece': 'wall-1', 'field': 'from', 'value': [0, 0]}}, actor=storage.get_member('p1'))
    check(bad.get('status') in ('error', 'refused') and bad.get('message'), bad)


def scenario_tool_refuses_non_parents():
    _seed()
    _people()
    for actor in (storage.get_member('k1'), None):
        out = agent_tools_v2.execute_tool('house_design', {'action': 'status'}, actor=actor)
        check('Only a parent can change the house.' in (out.get('message') or ''), out)


def scenario_a_real_turn_edits_the_house_and_is_metered():
    _seed()
    tokens = _people()
    model = Model([
        {'message': '', 'tool_calls': [{'name': 'house_design', 'arguments': {
            'action': 'edit', 'edit': {'op': 'set', 'piece': 'roof-1', 'field': 'pitch', 'value': 8}}}]},
        {'message': 'Set the roof pitch to 8:12.', 'tool_calls': []},
    ])
    c = _client()
    with _enforced(), patch.object(llm.llm_budget, 'urlopen', model):
        r = c.post('/api/house/editor/say', headers=tokens['parent'],
                   json={'message': 'the roof is 8/12', 'selection': None, 'history': []})
    check(r.status_code == 200, r.text)
    body = r.json()
    check(body['reply'] == 'Set the roof pitch to 8:12.' and body['changed'] is True and body['summary'], body)
    check(_section(ts.current(), 'roof-1')['pitch'] == 8, 'the house changed through the real router')
    conv = [e for e in tc.entries() if e['stage'] == 'conversation']
    check(len(conv) == len(model.requests) >= 2, (len(conv), len(model.requests)))
    check(abs(body['cost'] - sum(e['usd'] for e in conv)) < 1e-9, (body['cost'], conv))


def scenario_a_child_cannot_talk_the_house_into_changing():
    _seed()
    tokens = _people()
    c = _client()
    with _enforced():
        r = c.post('/api/house/editor/say', headers=tokens['child'], json={'message': 'hi'})
    check(r.status_code in (401, 403), r.status_code)


def scenario_say_stops_at_a_due_checkpoint_before_any_request():
    _seed()
    tokens = _people()
    per_million = tc.price(PRICED, 1_000_000, 0)[0]
    tc.record('step:walls', [{'model': PRICED, 'input_tokens': int(10.5 / per_million * 1_000_000),
                              'output_tokens': 0, 'images': 0, 'prompt_chars': 0, 'max_output_tokens': 0}])
    model = Model([{'message': 'hi', 'tool_calls': []}])
    c = _client()
    with _enforced(), patch.object(llm.llm_budget, 'urlopen', model):
        r = c.post('/api/house/editor/say', headers=tokens['parent'], json={'message': 'hi'})
    check(r.status_code == 409 and r.json()['detail']['checkpoint'] == 10.0, r.text)
    check(model.requests == [], 'no request made')


def scenario_a_checkpoint_inside_the_turn_stops_cleanly():
    # The first request crosses $10; the router's next request must stop with
    # the checkpoint, not be treated as a model failure.
    _seed()
    tokens = _people()
    per_dollar = tc.price(PRICED, 1_000_000, 0)[0]
    tc.record('step:walls', [{'model': PRICED, 'input_tokens': int(9.99 / per_dollar * 1_000_000),
                              'output_tokens': 0, 'images': 0, 'prompt_chars': 0, 'max_output_tokens': 0}])
    check(tc.blocking_checkpoint() is None, 'just under the checkpoint')
    failures = []
    from services import model_pools
    model = Model([
        {'message': '', 'tool_calls': [{'name': 'house_design', 'arguments': {'action': 'status'}}]},
        {'message': 'never reached', 'tool_calls': []},
    ])
    c = _client()
    with _enforced(), patch.object(llm.llm_budget, 'urlopen', model), \
            patch.object(model_pools, 'note_failure', lambda *a, **k: failures.append(a)), \
            patch.object(tc, 'price', lambda m, i, o: (0.05, True)):
        r = c.post('/api/house/editor/say', headers=tokens['parent'], json={'message': 'status?'})
    check(r.status_code == 409 and r.json()['detail']['checkpoint'] == 10.0, r.text)
    check(len(model.requests) == 1 and failures == [], (len(model.requests), failures))


def scenario_describe_is_short_even_for_a_whole_building():
    _seed()
    _people()
    parent = storage.get_member('p1')
    wall = agent_tools_v2.execute_tool('house_design', {'action': 'describe', 'piece': 'wall-1'}, actor=parent)
    check(wall.get('status') == 'ok' and "'" in json.dumps(wall), wall)          # feet-inches in plain words
    whole = agent_tools_v2.execute_tool('house_design', {'action': 'describe', 'piece': 'house'}, actor=parent)
    check(whole.get('status') == 'ok' and len(json.dumps(whole)) < 1500, len(json.dumps(whole)))
    check('wall-5' not in json.dumps(whole), 'a building is described by counts, not every piece')


def scenario_accept_and_reread_drive_the_build():
    import test_twin_build as engine_tests
    from services import twin_build as tb
    engine_tests._fresh()
    _people()
    _, _, photo = engine_tests._sources()
    reader = engine_tests.Reader()
    b = tb.start(engine_tests._inputs(photo), reader=reader, inline=True)
    parent = storage.get_member('p1')
    with patch.object(__import__('services.twin_reads', fromlist=['read']), 'read', reader):
        out = agent_tools_v2.execute_tool('house_design', {'action': 'accept'}, actor=parent)
        check(out.get('status') == 'ok', out)
        deadline = __import__('time').time() + 20
        while tb.status(b)['state'] == 'running' and __import__('time').time() < deadline:
            __import__('time').sleep(0.1)
        check(tb.status(b)['pause'] and tb.status(b)['pause']['step'] == 'registration:L2', tb.status(b)['pause'])
        before = len(reader.calls)
        out = agent_tools_v2.execute_tool('house_design', {'action': 'reread', 'step': 'rooms:L1'}, actor=parent)
        check(out.get('status') == 'ok', out)
        deadline = __import__('time').time() + 20
        while tb.status(b)['state'] == 'running' and __import__('time').time() < deadline:
            __import__('time').sleep(0.1)
        check([c['step'] for c in reader.calls[before:]].count('rooms:L1') == 1, reader.calls[before:])


def scenario_house_design_is_refused_off_the_editor():
    # The tool exists only inside the house editor: a PWA chat turn whose model
    # emits a house_design edit is refused and the house is unchanged.
    _seed()
    _people()
    from services import agent_router
    model = Model([
        {'message': '', 'tool_calls': [{'name': 'house_design', 'arguments': {
            'action': 'edit', 'edit': {'op': 'set', 'piece': 'roof-1', 'field': 'pitch', 'value': 12}}}]},
        {'message': 'ok', 'tool_calls': []},
    ])
    with patch.object(llm.llm_budget, 'urlopen', model):
        agent_router.process_agent_request('make the roof steeper', source='pwa',
                                           acting_member=storage.get_member('p1'))
    check(_section(ts.current(), 'roof-1')['pitch'] == 6, 'the house is unchanged off the editor')


def scenario_a_checkpoint_mid_turn_still_reports_what_changed():
    _seed()
    tokens = _people()
    per_million = tc.price(PRICED, 1_000_000, 0)[0]
    tc.record('step:walls', [{'model': PRICED, 'input_tokens': int(9.99 / per_million * 1_000_000),
                              'output_tokens': 0, 'images': 0, 'prompt_chars': 0, 'max_output_tokens': 0}])
    model = Model([
        {'message': '', 'tool_calls': [{'name': 'house_design', 'arguments': {
            'action': 'edit', 'edit': {'op': 'set', 'piece': 'roof-1', 'field': 'pitch', 'value': 8}}}]},
        {'message': 'never reached', 'tool_calls': []},
    ])
    c = _client()
    with _enforced(), patch.object(llm.llm_budget, 'urlopen', model), \
            patch.object(tc, 'price', lambda m, i, o: (0.05, True)):
        r = c.post('/api/house/editor/say', headers=tokens['parent'], json={'message': 'roof 8/12'})
    check(r.status_code == 409, r.text)
    detail = r.json()['detail']
    check(detail['checkpoint'] == 10.0 and detail.get('changed') is True and detail.get('summary'), detail)


def scenario_long_messages_are_capped():
    _seed()
    tokens = _people()
    model = Model([{'message': 'ok', 'tool_calls': []}])
    c = _client()
    with _enforced(), patch.object(llm.llm_budget, 'urlopen', model):
        r = c.post('/api/house/editor/say', headers=tokens['parent'],
                   json={'message': 'x' * 20000, 'history': [{'role': 'user', 'content': 'y' * 20000}] * 30})
    check(r.status_code in (200, 400), r.status_code)
    if r.status_code == 200:
        import re
        sent = model.requests[0].data.decode('utf-8')
        longest = lambda ch: max((len(m) for m in re.findall(ch + '+', sent)), default=0)
        check(longest('x') <= 4000 and longest('y') <= 4000, ('message and history capped', longest('x'), longest('y')))


if __name__ == '__main__':
    for fn in (scenario_tool_is_registered_and_never_runs_from_a_mission,
               scenario_tool_edits_through_the_same_operations,
               scenario_tool_refuses_non_parents,
               scenario_a_real_turn_edits_the_house_and_is_metered,
               scenario_a_child_cannot_talk_the_house_into_changing,
               scenario_say_stops_at_a_due_checkpoint_before_any_request,
               scenario_a_checkpoint_inside_the_turn_stops_cleanly,
               scenario_describe_is_short_even_for_a_whole_building,
               scenario_accept_and_reread_drive_the_build,
               scenario_house_design_is_refused_off_the_editor,
               scenario_a_checkpoint_mid_turn_still_reports_what_changed,
               scenario_long_messages_are_capped):
        fn()
        print('  ok ', fn.__name__)
