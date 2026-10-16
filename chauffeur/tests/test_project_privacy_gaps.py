"""Project privacy at the remaining read/write doors; no browser required.

Run from chauffeur/: python tests/test_project_privacy_gaps.py [item number]
"""
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch

from harness import check
from fastapi.testclient import TestClient
from services import storage, projects, threads, subjects, missions, mind, watchers
from services import agent_tools_v2 as tools
from test_front_door_chat import _fresh
from test_subjects import MOM, DAD, AUNT, KID
import main

ROOT = Path(__file__).resolve().parents[1]


def project(audience='private', owner='mom'):
    return projects.create({'title': audience + ' project', 'goal': 'x', 'done_when': 'x',
                            'owner_member_id': owner, 'audience': audience}, dict(MOM))['project']


def thread(title, p=None, owner='mom'):
    return threads.create(title=title, owner_member_id=owner, created_by='mom',
                          project_id=p['id'] if p else None,
                          next_action='Call the vendor', next_action_at='2020-01-01')


def program(title, p=None, owner='mom'):
    pid = storage.add_program({'title': title, 'member_id': owner, 'state': 'active'})
    projects.adopt('program', pid, None, project_id=p['id'] if p else None)
    return pid


def mission(goal, p=None, status='waiting_user'):
    mid = storage.add_mission({'goal': goal, 'created_by': 'mom', 'status': status,
                              'summary': 'Confidential summary', 'error': 'Confidential error'})
    projects.adopt('mission', mid, None, project_id=p['id'] if p else None)
    storage.add_mission_step(mid, {'kind': 'ask', 'result_json': {'question': 'Confidential question?'}})
    return mid


def scenario_1_tools():
    _fresh()
    p = project()
    tid = thread('Secret tiler', p)
    pid = program('Secret piano', p)
    thread('Shared gutter')
    program('Shared guitar')
    errors = []
    def expect(ok, message):
        if not ok:
            errors.append(message)
    for fn in (tools.list_threads, tools.list_programs):
        result = fn(acting_member=dict(DAD))
        expect('Secret' not in json.dumps(result), f'{fn.__name__} leaked: {result}')
        expect('Shared' in json.dumps(result), f'{fn.__name__} lost wrapper')
    with patch.object(threads, 'draft_message', return_value={'status': 'ok', 'subject': 'Draft', 'body': 'Text'}) as draft:
        for title in ('Secret tiler', 'tiler', 'unknown'):
            before = storage.get_thread(tid)
            result = tools.add_thread_note(title, 'Unauthorized note', acting_member=dict(DAD))
            expect(result['status'] == 'error', f'add note matched hidden {title}')
            expect(storage.get_thread(tid) == before, 'hidden thread mutated')
            result = tools.draft_thread_message(title, acting_member=dict(DAD))
            expect(result['status'] == 'error', f'draft matched hidden {title}')
            if title == 'unknown':
                expect('Secret' not in json.dumps(result), 'not-found hint leaked hidden thread')
        expect(not draft.called, 'draft service called for hidden thread')
    for title in ('Secret piano', 'Secret pi', 'unknown'):
        result = tools.program_progress(title, acting_member=dict(DAD))
        expect(result['status'] == 'error', f'progress matched hidden {title}')
        if title == 'unknown':
            expect('Secret' not in json.dumps(result), 'not-found hint leaked hidden program')
    expect('Secret' in tools.list_threads(acting_member=dict(MOM))['message'], 'thread owner lost access')
    expect(tools.program_progress('Secret piano', acting_member=dict(MOM))['status'] == 'success', 'program owner lost access')
    # A separate record keeper still has access without gaining the project.
    storage.update_thread(tid, {'owner_member_id': 'aunt'})
    storage.update_program(pid, {'member_id': 'aunt'})
    expect(tools.add_thread_note('Secret tiler', 'Keeper note', acting_member=dict(AUNT))['status'] == 'success', 'thread keeper lost access')
    expect(tools.program_progress('Secret piano', acting_member=dict(AUNT))['status'] == 'success', 'program keeper lost access')
    check(not errors, '\n'.join(errors))


def scenario_1_channel_tools():
    _fresh()
    from services import agent_router
    from test_subject_hardening import _router_capture
    p = project()
    tid = thread('Secret tiler', p)
    program('Secret piano', p)
    group = storage.get_or_create_group(['mom', 'dad'], 'Parents')
    for name, args in [('list_threads', {}), ('list_programs', {}),
                       ('program_progress', {'program_title': 'unknown'}),
                       ('add_thread_note', {'thread_title': 'tiler', 'text': 'Channel note'}),
                       ('draft_thread_message', {'thread_title': 'unknown'})]:
        before = storage.get_thread(tid)
        seen, undo = _router_capture([{'message': '', 'tool_calls': [{'name': name, 'arguments': args}]},
                                      {'message': 'done', 'tool_calls': []}])
        try:
            result = agent_router.process_agent_request('check the work', source='family', acting_member=dict(MOM),
                                                        focus_key='channel:' + group['id'])
        finally:
            undo()
        check('Secret' not in json.dumps(seen[1:]) + json.dumps(result), f'{name} leaked to channel')
        check(storage.get_thread(tid) == before, f'{name} acted on a hidden channel record')


def scenario_2_mind_snapshot():
    _fresh()
    for audience in ('household', 'private', 'parents'):
        thread(audience + ' plumber', project(audience))
    thread('Plain wrapped gutter')
    text = mind.snapshot(datetime.datetime.now())
    check('household plumber' in text, 'household project thread disappeared from snapshot')
    check('private plumber' not in text and 'parents plumber' not in text, 'restricted project reached snapshot')
    check('Plain wrapped gutter' in text, 'wrapper thread disappeared from snapshot')
    check(not projects.can_see(project('household'), None), 'anonymous project access must remain denied')


def scenario_3_mission_reader():
    _fresh()
    storage.save_occasion({'id': 'parents-subject', 'title': 'Parents occasion', 'audience': 'parents'})
    for audience in ('household', 'parents', 'private'):
        p = project(audience)
        row = {'project_id': p['id'], 'created_by': 'mom',
               'subject_kind': 'occasion', 'subject_id': 'parents-subject'}
        check(missions.read_viewer(row) == {'id': None, 'role': 'parent'},
              f'{audience} project downgraded parents-bound mission: {missions.read_viewer(row)}')
    check(missions.read_viewer({'project_id': project('household')['id']}) == {'id': None, 'role': 'adult'},
          'household project alone reads as adult')
    for audience in ('parents', 'private'):
        check(missions.read_viewer({'project_id': project(audience)['id']}) == {'id': None, 'role': 'parent'},
              f'{audience} project uses the narrowest generic transcript audience')


def scenario_4_show_closed_binds_after_tick():
    source = (ROOT / 'templates/components/projects_page.html').read_text(encoding='utf-8')
    handler = re.search(r'x-model="showClosed" @change="([^"]+)"', source).group(1)
    island = source.split('<script>')[-1].split('</script>')[0]
    code = """const assert=require('assert');global.window={};global.location={search:''};
global.document={documentElement:{dataset:{}}};let saved;
global.localStorage={getItem:()=>null,setItem:(k,v)=>{saved=v}};
""" + island + """
const p=projectsPage();const queue=[];let rendered=false,bound=0;
p.elsewhere=[{id:'finished',group:'done'}];p.showClosed=false;
assert.equal(p.visibleElsewhere.length,0);
p.rootEl={isConnected:true,querySelectorAll:()=>rendered?[{id:'pieces'}]:[]};
p.$nextTick=fn=>queue.push(fn);p.sitCtx=()=>({});
window.Situations={bind:el=>{assert.equal(el.id,'pieces');bound++}};
p.showClosed=true;
new Function('with(this){' + """ + json.dumps(handler) + """ + '}').call(p);
assert.equal(saved,'1');assert.equal(bound,0);
rendered=p.visibleElsewhere.length>0;queue.forEach(fn=>fn());
assert.equal(bound,1,'newly rendered closed cards must have working inline buttons');
"""
    result = subprocess.run(['node', '-'], input=code, capture_output=True, text=True, encoding='utf-8')
    check(result.returncode == 0, result.stdout + result.stderr)


def scenario_5_household_watchers():
    _fresh()
    allowed_threads, allowed_missions = set(), set()
    for audience in ('household', 'private', 'parents', 'wrapper'):
        p = None if audience == 'wrapper' else project(audience)
        tid = thread(audience + ' tiler', p)
        mids = [mission(audience + ' booking ' + status, p, status)
                for status in ('waiting_user', 'done', 'blocked')]
        if audience in ('household', 'wrapper'):
            allowed_threads.add(tid)
            allowed_missions.update(mids)
    now = datetime.datetime.now()
    tf, mf = watchers._thread_stalls(now), watchers._mission_states(now)
    check({f.subject_id for f in tf} == allowed_threads, 'restricted thread words enter household findings/DMs')
    check({f.subject_id for f in mf} == allowed_missions, 'restricted mission words enter household findings/DMs')
    check(any(f.dm for f in tf) and any(f.dm for f in mf), 'household/wrapper DM policy stays working')


def scenario_6_program_http_permission():
    _fresh()
    pid = program('Secret piano', project(), owner='aunt')
    storage.upsert_program_lesson(pid, {'phase_name': '', 'unit_n': 0, 'session_label': ''},
                                  {'origin': 'generated', 'scenes': [{'type': 'say', 'text': 'Secret lesson'}]})
    tokens = {who: {'X-Member-Token': storage.create_member_token(who)} for who in ('mom', 'dad', 'aunt', 'kid')}
    errors = []
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        client = TestClient(main.app)
        before = storage.get_program(pid)
        lesson = client.get(f'/api/programs/{pid}/lesson', headers=tokens['dad'])
        if lesson.status_code != 200 or lesson.json() != {'lesson': None}:
            errors.append(f'lesson read must withhold the stored lesson: {lesson.text}')
        for method, suffix, body in [('get', 'footprint', None), ('put', 'lesson', {}),
                                     ('post', 'session', {'minutes': 10}), ('post', 'finish', {}),
                                     ('post', 'edit', {'title': 'Changed'}), ('post', 'drop', {})]:
            kw = {'headers': tokens['dad']}
            if body is not None:
                kw['json'] = body
            response = getattr(client, method)(f'/api/programs/{pid}/{suffix}', **kw)
            if response.status_code != 403:
                errors.append(f'{suffix}: expected 403, got {response.status_code} {response.text[:150]}')
        if storage.get_program(pid) != before:
            errors.append('denied requests mutated private program')
        # Keeper and parents of a child retain real HTTP writes.
        for owner, actor, p in [('aunt', 'aunt', project()), ('kid', 'kid', project('private', 'kid')),
                                ('kid', 'dad', project('private', 'kid'))]:
            own = program('Allowed practice', p, owner)
            response = client.post(f'/api/programs/{own}/session', json={'minutes': 12}, headers=tokens[actor])
            if response.status_code != 200 or not storage.get_program(own)['sessions']:
                errors.append(f'{actor} lost access to {owner}: {response.text}')
    check(not errors, '\n'.join(errors))


def scenario_7_program_speech():
    _fresh()
    for audience in ('private', 'parents', 'household', 'wrapper'):
        p = None if audience == 'wrapper' else project(audience)
        row = storage.get_program(program(audience + ' piano', p))
        check(subjects.spoken_safe('program', row) == (audience in ('household', 'wrapper')),
              f'{audience} program speech ignored project audience')
        check(subjects.visible('program', row, dict(MOM), spoken=True) == (audience in ('household', 'wrapper')),
              f'{audience} owner bypassed room speech rule')
    row['sensitivity'] = 'sensitive'
    check(not subjects.spoken_safe('program', row), 'existing sensitive speech rule survives')


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        if len(sys.argv) > 1 and not fn.__name__.startswith('scenario_' + sys.argv[1] + '_'):
            continue
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))
