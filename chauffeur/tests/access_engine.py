"""Task 6 runtime probes. The engine's oracle is HOUSE plus its own pieces/origin.

It has no signed-in viewer; each probe asserts this oracle and returns skip
instead of applying the person's-own-surface table to an autonomous engine.
"""
import json
from unittest.mock import patch

from harness import check
import access_fixture
from test_access_core import TABLE, COLS, KIND, load
from services import access_readers, missions, planned, storage, threads


def words(value):
    return json.dumps(value, default=str)


def act(fx, action, engine='R9b', entry='_apply_planner_action'):
    mid = fx.ids[engine]
    storage.update_mission(mid, {'status': 'running', 'tier': 'flash'})
    m = storage.get_mission(mid)
    if entry in ('step', '_step_once'):
        with patch.object(missions, '_llm', return_value=action):
            getattr(missions, entry)(m)
    elif entry == '_run_planner_action':
        missions._run_planner_action(m, action, storage.get_settings(), action['action'])
    else:
        missions._apply_planner_action(m, action, storage.get_settings(), action['action'], None)
    return storage.get_mission_steps(mid)


def run(name, fx, rkey):
    kind, row = load(fx, rkey)
    # Generic reads never acquire Mom's authority, even in her private mission.
    for engine in ('R9a', 'R9b'):
        allowed = TABLE[rkey][COLS.index('house')] is not None or engine == 'R9a' and rkey in ('R1', 'R2', 'R3')
        m = storage.get_mission(fx.ids[engine])
        if name == '_match_thread':
            out = missions._match_thread(fx.title(rkey), mission=m)
        elif name == '_seed_thread_context':
            storage.mission_steps_table.truncate()
            missions._seed_thread_context(m['id'], row)
            out = storage.get_mission_steps(m['id'])
        else:
            action = {'action': 'tool', 'tool': {'mission': 'list_situations',
                      'thread': 'list_threads', 'program': 'list_programs'}[kind], 'args': {}}
            storage.mission_steps_table.truncate()
            out = act(fx, action, engine, entry=name)
            if name == '_user_prompt':
                out = missions._user_prompt(storage.get_mission(m['id']))
        text = words(out)
        seen = fx.title(rkey) in text or fx.secret(rkey) in text
        check(seen == allowed, f'{name} {engine} {rkey}: allowed={allowed}, output={text[:1800]}')


def register(probe):
    for rid, cls, kinds, _ in access_readers.READERS:
        if cls != '4.4-engine':
            continue
        name = rid[-1].rsplit('.', 1)[-1]
        def run_probe(fx, rkey, col, name=name):
            if col != 'house':
                return 'skip'
            if name in ('launch', 'ask_card', 'planner_action', 'approve_plan'):
                # These readers consume their own row/plan; exercised below
                # through complete launch/interview/approval/card workflows.
                lifecycle_contract(name)
            else:
                fresh = access_fixture.build()
                storage.update_thread(fresh.ids['R13'], {'title': 'Unrelated wrapper'})
                run(name, fresh, rkey)
            return 'skip'
        probe(rid)(run_probe)


def lifecycle_contract(name):
    fx = access_fixture.build()
    mid = fx.ids['R9a']
    storage.update_mission(mid, {'status': 'running'})
    if name == 'launch':
        from access_signed_in import request
        # Both launch doors ignore a different home, preserving origin context
        # for Mom without publishing it in a household mission Dad can read.
        for http in (False, True):
            args = {'goal': 'household work', 'origin_kind': 'thread', 'origin_ref': fx.ids['R1'],
                    'tier': 'flash', 'project_id': fx.projects['household']['id']}
            if http:
                response = request(fx, 'mom', 'POST', '/api/missions/launch', json=args)
                check(response.status_code == 200, response.text)
                out = response.json()
            else:
                out = missions.launch(**args, created_by='mom')
            check(out.get('mission_id'), f'launch executed: {out}')
            launched = storage.get_mission(out['mission_id'])
            check(launched['project_id'] == fx.projects['mom_private']['id'],
                  f'origin home wins over requested household project: {launched}')
            mom = request(fx, 'mom', 'GET', f'/api/missions/{launched["id"]}')
            check(mom.status_code == 200 and fx.secret('R1') in mom.text,
                  f'Mom retains the real seeded origin context: {mom.text}')
            dad = request(fx, 'dad', 'GET', f'/api/missions/{launched["id"]}')
            listing = request(fx, 'dad', 'GET', '/api/missions/admin')
            check(dad.status_code == 404 and listing.status_code == 200
                  and launched['id'] not in listing.text
                  and fx.secret('R1') not in dad.text + listing.text,
                  f'Dad cannot see the mission or origin words: {dad.text} {listing.text}')
        return
    with patch.object(missions, '_dm_person'):
        out = planned.planner_action(mid, {'action': 'interview', 'questions': [{'key': 'x', 'ask': 'Which day?'}]})
        check(out['status'] == 'success', f'real planner interview: {out}')
        storage.update_mission(mid, {'plan': {'state': 'proposed', 'rev': 1, 'questions': [], 'stages': [],
                                            'steps': [], 'approved_by': None}})
        storage.add_mission_step(mid, {'kind': 'ask', 'name': 'plan', 'result_json': {'question': 'Approve?'}})
        if name == 'approve_plan':
            out = planned.approve_plan(mid, 1, fx.viewers['mom'])
            check(out['status'] == 'success', f'approve own private project: {out}')
        else:
            card = missions.ask_card(storage.get_mission(mid))
            check(card and card['project']['title'] == 'Mom private', f'own project on ask card: {card}')


def extra_contracts():
    fx = access_fixture.build()
    storage.update_thread(fx.ids['R13'], {'title': 'Unrelated wrapper'})
    def draft(tid, **kw):
        return {'draft': words(storage.get_thread(tid))}
    with patch.object(threads, 'draft_message', side_effect=draft) as effect:
        steps = act(fx, {'action': 'draft', 'intent': 'reply'}, 'R9a')
        check(fx.secret('R9origin') in words(steps), 'I6: origin thread drafts in its own mission')
        effect.reset_mock()
        storage.mission_steps_table.truncate()
        steps = act(fx, {'action': 'draft', 'thread_title': fx.title('R1'), 'intent': 'reply'})
        check(not effect.called and fx.title('R1') not in words(steps)
              and fx.secret('R1') not in words(steps), 'unrelated draft cannot read or store private thread words')
    for engine in ('R9a', 'R9b'):
        steps = act(fx, {'action': 'tool', 'tool': 'list_threads', 'args': {}}, engine)
        for target in ('R1', 'R9origin'):
            check((fx.secret(target) in words(steps)) == (engine == 'R9a'), f'{engine} own-project tool {target}')
    # The origin exception is independent of sharing a home project.
    storage.update_thread(fx.ids['R9origin'], {'project_id': fx.projects['kate_private']['id']})
    storage.mission_steps_table.truncate()
    with patch.object(threads, 'draft_message', side_effect=draft):
        steps = act(fx, {'action': 'draft', 'intent': 'reply'}, 'R9a')
    check(fx.secret('R9origin') in words(steps), 'I6: origin exception survives a different private home')
    # Picking a new piece as subject cannot turn a generic read into a creator read.
    fx = access_fixture.build()
    steps = act(fx, {'action': 'subject', 'kind': 'thread', 'id': fx.ids['R1']})
    check(not storage.get_mission(fx.ids['R9b']).get('subject_id')
          and fx.secret('R1') not in words(steps), 'subject branch cannot widen to creator private piece')
    # Tool context must be caller-owned and cleared after the call.
    from services import agent_tools_v2 as tools, access
    out = tools.execute_tool('list_threads', {'mission_id': fx.ids['R9a']}, actor=access.HOUSE)
    check(fx.secret('R1') not in words(out), 'model cannot forge mission context')
    from access_channels import capture_router
    prompt, _ = capture_router(access.HOUSE, 'conv:room', [{
        'name': 'find_in_chauffeur', 'arguments': {'query': fx.title('R1'),
                                                'mission_id': fx.ids['R9a']}}])
    check(fx.ids['R1'] not in prompt and fx.secret('R1') not in prompt,
          'real chat router cannot accept a model-authored mission_id')
    for engine in ('R9a', 'R9b'):
        storage.mission_steps_table.truncate()
        steps = act(fx, {'action': 'tool', 'tool': 'find_in_chauffeur',
                        'args': {'query': fx.title('R1'), 'kind': 'thread'}}, engine)
        result = steps[-1]['result_json']
        check((fx.ids['R1'] in [c['id'] for c in result.get('candidates', [])]) == (engine == 'R9a'),
              f'{engine} finder obeys mission context: {result}')
    for name in ('launch', 'planner_action', 'approve_plan', 'ask_card'):
        lifecycle_contract(name)
    # The real renderer gets explicit mission authority, never viewer=None.
    from services import situations
    fx = access_fixture.build()
    real_view = situations.view
    calls = []
    def render(*args, **kwargs):
        viewer = args[2] if len(args) > 2 else kwargs.get('viewer')
        check(viewer is not None, 'engine must give situations.view an explicit reader')
        calls.append(args)
        return real_view(*args, **kwargs)
    with patch.object(situations, 'view', side_effect=render):
        own = act(fx, {'action': 'tool', 'tool': 'list_situations', 'args': {}}, 'R9a')
        other = act(fx, {'action': 'tool', 'tool': 'list_situations', 'args': {}}, 'R9b')
    check(calls and fx.ids['R1'] in words(own) and fx.ids['R1'] not in words(other),
          'explicit renderer retains own-project access and refuses unrelated private pieces')


if __name__ == '__main__':
    extra_contracts()
    print('PASS access_engine contracts')
