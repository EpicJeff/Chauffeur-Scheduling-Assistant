"""Final slice-2 review regressions: real HTTP readers and executed UI code.

Run from chauffeur/: python tests/test_project_final_fixes.py
"""
import json
from pathlib import Path
import re
import subprocess
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from harness import check
from fastapi.testclient import TestClient
from services import storage, projects, threads, subjects, situations
from test_front_door_chat import _fresh
from test_subjects import MOM, DAD, AUNT
import main

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text(encoding='utf-8')


def node(code):
    code = "global.location={search:''}; global.document={documentElement:{dataset:{}}};\n" + code
    result = subprocess.run(['node', '-'], input=code, text=True, encoding='utf-8', capture_output=True)
    check(result.returncode == 0, result.stdout + result.stderr)
    return result.stdout


def island(name):
    return source('templates/components/' + name + '.html').split('<script>')[-1].split('</script>')[0]


def private():
    return projects.create({'title': 'Private project', 'goal': 'x', 'done_when': 'x',
                            'owner_member_id': 'mom', 'audience': 'private'}, dict(MOM))['project']


def scenario_private_project_readers():
    _fresh()
    p = private()
    tid = threads.create(title='Secret tiler', owner_member_id='aunt', created_by='mom', project_id=p['id'])
    mid = storage.add_mission({'goal': 'Secret booking', 'created_by': 'aunt', 'status': 'waiting_user'})
    projects.adopt('mission', mid, None, project_id=p['id'])
    storage.add_program({'id': 'secret-program', 'title': 'Secret piano', 'member_id': 'aunt', 'state': 'active'})
    projects.adopt('program', 'secret-program', None, project_id=p['id'])
    tokens = {who: {'X-Member-Token': storage.create_member_token(who)} for who in ('mom', 'dad', 'aunt')}
    failures = []
    def expect(ok, message):
        if not ok:
            failures.append(message)
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        client = TestClient(main.app)
        for who in tokens:
            allowed = who != 'dad'
            for kind, rid in [('thread', tid), ('mission', mid), ('program', 'secret-program')]:
                got = client.get(f'/api/projects/for/{kind}/{rid}', headers=tokens[who]).json()
                expect(got['record_visible'] == allowed, f'{who} locate {kind}: {got}')
                if kind != 'program':
                    got = client.get(f'/api/situations/{kind}/{rid}', headers=tokens[who])
                    expect((got.status_code == 200 and bool(got.json())) == allowed, f'{who} situation {kind}')
            search = client.get('/api/subjects/search?q=Secret', headers=tokens[who]).json()['candidates']
            expect(bool(search) == allowed, f'{who} search: {search}')
            for path, key, rid in [('/api/threads', 'threads', tid), ('/api/programs', 'programs', 'secret-program'),
                                   ('/api/missions/admin', 'active', mid)]:
                rows = client.get(path, headers=tokens[who]).json()[key]
                expect(any(r['id'] == rid for r in rows) == allowed, f'{who} {path}')
        # A wrapper must still delegate to its record without recursing.
        wrapped = threads.create(title='Shared wrapper', owner_member_id='mom', created_by='mom')
        expect(projects.can_see(projects.project_for('thread', wrapped), dict(DAD)), 'wrapper visibility')
    check(not failures, '\n'.join(failures))


def scenario_finished_keeper_projection():
    _fresh()
    p = private()
    mid = storage.add_mission({'goal': 'Book venue', 'created_by': 'aunt', 'status': 'done',
                              'status_note': 'Hidden project note', 'plan': {'state': 'done', 'stages': []}})
    projects.adopt('mission', mid, None, project_id=p['id'])
    storage.add_mission_step(mid, {'kind': 'note', 'result_json': {'secret': 'Hidden transcript'}})
    rows = projects.elsewhere(dict(AUNT))
    check(len(rows) == 1 and rows[0]['id'] == mid and rows[0]['group'] == 'done', 'finished keeper stays discoverable')
    from services import planned
    row = storage.get_mission(mid)
    row['steps'] = storage.get_mission_steps(mid)
    check('Hidden' not in json.dumps(planned.keeper_view(row, dict(AUNT))), 'keeper transcript and cached note redacted')
    node("const assert = require('assert'); global.window={}; global.localStorage={getItem:()=>null};\n" + island('projects_page') + """
const p = projectsPage(); p.elsewhere = [{id:'old',group:'done'}, {id:'live',group:'moving'}];
assert.deepStrictEqual(p.visibleElsewhere.map(s=>s.id), ['live']);
p.showClosed=true; assert.deepStrictEqual(p.visibleElsewhere.map(s=>s.id), ['old','live']);
""")


def scenario_mission_sheet_beyond_history_cap():
    _fresh()
    mid = storage.add_mission({'goal': 'Old booking', 'created_by': 'mom', 'status': 'done', 'created_at': 1})
    attempt = storage.add_mission_step(mid, {'kind': 'attempt', 'result_json': {'outcome': 'unknown'}})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'verify',
                                   'result_json': {'question': 'Did it book?', 'attempt_step_id': attempt}})
    for n in range(61):
        storage.add_mission({'goal': f'Newer {n}', 'created_by': 'mom', 'status': 'done', 'created_at': 100+n})
    headers = {'X-Member-Token': storage.create_member_token('mom')}
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        client = TestClient(main.app)
        history = client.get('/api/missions/admin', headers=headers).json()['history']
        check(mid not in [m['id'] for m in history], 'fixture is outside the history cap')
        mission = client.get('/api/missions/' + mid, headers=headers).json()
        situation = client.get('/api/situations/mission/' + mid, headers=headers).json()
    check(any(o['verb'] == 'verify' for o in situation['options']), 'old mission still needs verification')
    fixtures = {f'api/missions/{mid}': mission, f'api/situations/mission/{mid}': situation}
    node("const assert=require('assert'); global.window={}; global.document={visibilityState:'visible'};\n" +
         'const fixtures=' + json.dumps(fixtures) + '; const mid=' + json.dumps(mid) + ';\n' +
         """let calls=[], poll; global.setInterval=fn=>{poll=fn};
global.fetch=async url=>{calls.push(url); return {ok:!!fixtures[url], json:async()=>fixtures[url]};};
""" + island('missions_page') + """
(async()=>{const m=missionsSettings(true); m.$refs={}; m.$nextTick=fn=>fn();
m.onSheet({kind:'mission',id:mid}); await new Promise(setImmediate);
assert(m.missionById(mid), 'direct requested mission must load');
assert(m.sitById(mid).options.some(o=>o.verb==='verify'));
m.startPolling(); poll(); await new Promise(setImmediate);
await m.cardCtx().onChange();
assert.equal(calls.filter(p=>p==='api/missions/'+mid).length,3);
assert.equal(calls.filter(p=>p==='api/situations/mission/'+mid).length,3);
assert(!calls.some(p=>p.includes('admin')||p.includes('?kinds')));
m.onSheet({kind:'mission',id:'missing'}); await new Promise(setImmediate);
assert.equal(m.groups.length,0); assert(m.adminChecked);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


def scenario_unowned_thread_form():
    form = source('templates/components/project_piece_forms.html')
    select = re.search(r'<select name="owner_member_id".*?</select>', form, re.S).group()
    check('<option value="">Who' in select, 'blank owner choice is selectable')
    _fresh()
    p = private()
    # Execute the actual submit handler, then submit its exact body over HTTP.
    body = json.loads(node("global.window={}; global.localStorage={getItem:()=>null};\n" + island('projects_page') + """
(async()=>{const p=projectsPage();p.myId='mom';p.pieceForm={...p.emptyPieceForm,kind:'thread',projectId:'PROJECT',title:'Unowned loop',owner_member_id:''};
p.mutate=async(path,body)=>{console.log(JSON.stringify(body));return false};await p.createPiece()})();
"""))
    body['project_id'] = p['id']
    headers = {'X-Member-Token': storage.create_member_token('mom')}
    response = TestClient(main.app).post('/api/threads', json=body, headers=headers)
    check(response.status_code == 200 and not storage.get_thread(response.json()['id'])['owner_member_id'], 'blank creates unowned thread')


def scenario_helper_program_form():
    form = source('templates/components/project_piece_forms.html')
    select = re.search(r'<select name="for_member_id".*?</select>', form, re.S).group()
    check('m in members' in select, 'program recipient uses original member set')
    _fresh()
    storage.add_member({'id': 'helper', 'name': 'Helper', 'role': 'helper'})
    p = private()
    from services import programs_curate
    with patch.object(programs_curate, 'curate', return_value={'phases': [], 'source': {}}):
        response = TestClient(main.app).post('/api/programs', json={'title': 'Learn piano', 'for_member_id': 'helper', 'project_id': p['id']},
                                            headers={'X-Member-Token': storage.create_member_token('mom')})
    check(response.status_code == 200 and storage.get_program(response.json()['id'])['member_id'] == 'helper', 'parent proposes for helper')


def scenario_redirect_shell_and_encoding():
    client = TestClient(main.app)
    for route in ['threads', 'missions', 'programs', 'work?tab=threads', 'work?tab=missions', 'rhythms?tab=programs']:
        for record in ['', '&id=T1%26settings%3Dopen%23hash%2Bplus']:
            path = '/' + route + ('&' if '?' in route else '?') + 'panel=true&kiosk=true&tabs=projects&theme=ha&embed=1' + record
            response = client.get(path, follow_redirects=False)
            query = parse_qs(urlsplit(response.headers['location']).query)
            for key, value in [('panel','true'), ('kiosk','true'), ('tabs','projects'), ('theme','ha'), ('embed','1')]:
                check(query.get(key) == [value], f'{path} preserves {key}: {query}')
            if record:
                check(query['piece'][0].split(':',1)[1] == 'T1&settings=open#hash+plus' and 'settings' not in query, 'id is encoded as one value')


def scenario_house_query_merge():
    go = re.search(r'  function go\(slug\).*?\n  }', source('static/house.js'), re.S).group()
    # The original one-line function ends before the next declaration.
    if go.splitlines()[0].endswith('}'):
        go = go.splitlines()[0]
    node("const assert=require('assert'); const BASE='/api/hassio_ingress/test/'; global.window={location:{href:'https://example.test'+BASE+'house?panel=true', search:'?panel=true&lane=old'}};\n" + go + """
go('projects?lane=programs');const u=new URL(window.location.href,'https://example.test');
assert.equal(u.pathname,BASE+'projects');assert.equal(u.searchParams.get('lane'),'programs');assert.equal(u.searchParams.get('panel'),'true');
""")


def scenario_legacy_rhythms_hashes():
    code = source('templates/rhythms.html').split('<script>')[-1].split('</script>')[0]
    for anchor in ['programs-settings', 'lessons', 'programs-pacing']:
        node("const assert=require('assert');let to;global.window={location:{hash:" + json.dumps('#'+anchor) + ",replace:p=>to=p}};\n" + code +
             '\nassert.equal(to,' + json.dumps('work?tab=projects#'+anchor) + ');')


def scenario_thread_loading_reset():
    node("const assert=require('assert');global.window={};\n" + island('threads_page') + """
const t=threadsPage(true);t.loadedOnce=true;t.load=()=>{};t.onSheet({kind:'thread',id:'next'});assert.equal(t.loadedOnce,false);
""")


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))
