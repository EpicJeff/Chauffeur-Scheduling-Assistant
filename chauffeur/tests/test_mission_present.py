"""Drive the real mission entry point and registry with offline page data."""
import copy
import datetime
import traceback
from unittest.mock import patch
from harness import check
from services import storage, missions, boards, page_lookup, net_guard, browse, web, agent_tools_v2, planned
from test_subjects import _fresh as fresh_subjects, MOM, KID
from test_projects import _make
from test_page_lookup import HTML, Response, public

POSTS = []
def fresh(audience='household'):
    fresh_subjects()
    for table in (storage.projects_table, storage.boards_table, storage.lookups_table): table.truncate()
    storage.get_settings = lambda: {'mission_cap_pro_calls': 1000, 'mission_step_cap': 60}
    project = _make('mom', MOM, audience=audience)
    mid = storage.add_mission(dict(goal='Find concert looks', origin_kind='manual', created_by='mom', tier='flash', project_id=project['id']))
    POSTS.clear()
    return mid, project

def run(mid, *actions):
    script = iter(actions)
    missions._llm = lambda *a, **k: next(script)
    for _ in actions: missions.step(storage.get_mission(mid))
    return storage.get_mission(mid)

def present(mid, **extra):
    records = page_lookup.for_mission(mid)
    return dict(action='present', title='Concert outfit', layout='options', noun='looks', slots=[{'role':'Shoes'}],
                options=[dict(title='Look', items=[{'slot':0,'lookup':r['id'],'facts':[]}]) for r in records],
                commit='buy', summary='Found three looks.', next_action='Open the board', **extra)

def lookups(mid):
    run(mid, *[dict(action='look_up',url=f'https://store.test/{i}') for i in range(3)])

def scenario_plain_mission_end_to_end():
    mid, p = fresh()
    check('get_current_state' in agent_tools_v2.TOOL_HANDLERS, 'real registry')
    run(mid, {'action':'research','question':'Concert shoes'})
    lookups(mid)
    check(len(page_lookup.for_mission(mid)) == 3, 'lookups run')
    row = run(mid, present(mid))
    bb = boards.for_project(p['id'])
    check(row['status'] == 'done' and len(bb) == 1 and len(bb[0]['options']) == 3, (row, bb))
    cards = [v for v in POSTS if (v[2] or {}).get('kind') == 'board']
    check(len(cards) == 1 and cards[0][0]['dm_key'] == ':'.join(sorted((storage.ensure_argyle_member()['id'], 'mom'))), cards)
    steps = storage.get_mission_steps(mid)
    check(sum(s['kind']=='tool' and s['name']=='look_up' and set(s['args_json'])=={'url'} for s in steps)==3, steps)
    check(any(s['name']=='present' and s['result_json']['board_id']==bb[0]['id'] for s in steps), steps)
    check(bb[0]['options'][0]['items'][0]['price']['amount']==79, 'server fields')

def scenario_present_bad_url_drops_item():
    mid, p = fresh(); lookups(mid); a = present(mid)
    a['options'][0]['items'][0]['lookup'] = 'lk_fake'
    run(mid, a)
    check(len(boards.for_project(p['id'])[0]['options']) == 2, 'bad item gone')

def scenario_two_invalid_presents_fall_back_to_text():
    mid, p = fresh(); bad = dict(action='present',title='Nothing',summary='No valid options.',options=[])
    run(mid, bad)
    refusals = [s for s in storage.get_mission_steps(mid) if s['name']=='present_refused']
    check(refusals and 'stage_id' in refusals[0]['result_json'] and refusals[0]['result_json']['stage_id'] is None, 'plain refusal names the null stage')
    row = run(mid, bad)
    check(row['status']=='done' and row['summary']=='No valid options.' and not boards.for_project(p['id']), row)
    check(POSTS and 'No valid options.' in POSTS[-1][1] and not POSTS[-1][2], POSTS)

def scenario_parents_project_card_not_to_child():
    mid, p = fresh('parents'); lookups(mid); run(mid, present(mid))
    check(POSTS and not any('kid' in v[0].get('members',[]) for v in POSTS), POSTS)
    check(all('kid' not in v[0]['dm_key'].split(':') for v in POSTS), POSTS)

def scenario_present_refused_with_open_stages():
    mid, p = fresh(); lookups(mid)
    plan=dict(state='running',rev=1,stages=[dict(id='s',kind='build',state='proposed',title='Build')])
    storage.update_mission(mid, {'plan':plan})
    run(mid, present(mid))
    check(not boards.for_project(p['id']) and any('open stages' in str(s.get('result_json')) for s in storage.get_mission_steps(mid)), 'open stages refused')

def scenario_work_stage_ends_in_board():
    mid, p = fresh(); lookups(mid)
    stage=dict(id='s',kind='work',state='running',title='Find looks',goal='Find looks',step_budget=12,steps_used=0,
               subject=list(missions.subject_of(storage.get_mission(mid))))
    storage.update_mission(mid, {'plan':dict(state='approved',rev=1,stages=[stage])})
    run(mid, present(mid))
    m=storage.get_mission(mid); st=m['plan']['stages'][0]
    check(st['state']=='done' and st['found']['board_id'], st)
    check(any((c or {}).get('kind')=='board' for _,_,c in POSTS), POSTS)
    run(mid, {'action':'finish','summary':'All done.'})
    done=[c for _,_,c in POSTS if (c or {}).get('kind')=='mission_done']
    check(done and done[-1]['boards']==[dict(board_id=st['found']['board_id'], project_id=p['id'], title='Concert outfit')], done)

def scenario_prompt_has_rules():
    text=missions._system_prompt(datetime.datetime.now())
    check('end with present, not finish' in text and '"action":"look_up"' in text and '"action":"present"' in text, 'prompt')

def scenario_planned_final_present_posts_only_done_card():
    mid,p=fresh();lookups(mid)
    storage.update_mission(mid, {'plan':dict(state='approved',rev=1,stages=[dict(id='s',kind='work',state='done',title='Research')])})
    POSTS.clear();row=run(mid,present(mid));board=boards.for_project(p['id'])[0]
    cards=[c for _,_,c in POSTS if c]
    check(row['status']=='done' and len(cards)==1 and cards[0]['kind']=='mission_done',cards)
    check(cards[0]['boards']==[dict(board_id=board['id'],project_id=p['id'],title=board['title'])],cards)

def scenario_lookup_catalog_survives_transcript_window():
    mid,p=fresh()
    for i in range(30):
        lid='lk_'+f'{i:010x}'
        storage.lookups_table.insert(dict(id=lid,mission_id=mid,title='T'*100,store='Store',price=None if i==0 else 12,currency='USD',fetched_at=i))
        storage.add_mission_step(mid,dict(kind='tool',name='look_up',result_json={'lookup':lid}))
    for i in range(25):storage.add_mission_step(mid,dict(kind='note',name='other',result_json={'note':'later'}))
    text=missions._user_prompt(storage.get_mission(mid))
    check('LOOKUPS:' in text and 'lk_0000000000' in text and 'lk_000000001d' in text,text)
    catalog=text.split('LOOKUPS:')[1].split('Reply with')[0]
    check('T'*61 not in catalog and 'no price' in catalog and '12 USD' in catalog,catalog)
    check(catalog.index('lk_0000000000') < catalog.index('lk_000000001d'),'newest last')

def scenario_new_stage_gets_its_own_present_retry():
    mid,p=fresh();lookups(mid)
    stage=lambda sid,state:dict(id=sid,kind='work',state=state,title=sid,goal='Find looks',step_budget=12,steps_used=0,
                               subject=list(missions.subject_of(storage.get_mission(mid))))
    storage.update_mission(mid,{'plan':dict(state='approved',rev=1,stages=[stage('s1','running'),stage('s2','pending')])})
    bad=dict(action='present',title='Bad',summary='Fallback',options=[])
    run(mid,bad);run(mid,present(mid))
    missions.step(storage.get_mission(mid))  # prepare_next starts s2 without a planner call
    run(mid,bad)
    m=storage.get_mission(mid)
    check(m['plan']['stages'][1]['state']=='running' and not m['plan']['stages'][1].get('found'),m['plan'])
    check(storage.get_mission_steps(mid)[-1]['name']=='present_refused','first failure is only a refusal')
    refusals = [s['result_json'] for s in storage.get_mission_steps(mid) if s['name'] == 'present_refused']
    check([r.get('stage_id') for r in refusals] == ['s1', 's2'], refusals)
    successful = [s for s in storage.get_mission_steps(mid) if s['name'] == 'present']
    check(successful[-1]['result_json']['stage_id'] == 's1', successful)

def scenario_successful_present_resets_only_its_stage_attempt():
    mid, p = fresh()
    stage = dict(id='s', kind='work', state='running', title='Research', goal='Research', step_budget=12, steps_used=0,
                 subject=list(missions.subject_of(storage.get_mission(mid))))
    storage.update_mission(mid, {'plan': dict(state='approved', rev=1, stages=[stage])})
    for name, sid in [('present_refused', 's'), ('present', 's'), ('present_refused', 'other')]:
        storage.add_mission_step(mid, {'kind': 'llm' if name == 'present' else 'note', 'name': name,
                                       'result_json': {'stage_id': sid}})
    bad = dict(action='present', title='Bad', summary='Text fallback', options=[])
    run(mid, bad)
    check(storage.get_mission(mid)['plan']['stages'][0]['state'] == 'running', 'earlier attempt and other stage do not count')
    run(mid, bad)
    check(storage.get_mission(mid)['plan']['stages'][0]['state'] == 'done', 'second failure in this attempt falls back')

def scenario_planned_without_present_matches_main_transcript():
    mid, p = fresh()
    stage = lambda sid: dict(id=sid, kind='work', state='pending', title=sid, goal='Research',
                            step_budget=12, steps_used=0, subject=list(missions.subject_of(storage.get_mission(mid))))
    storage.update_mission(mid, {'plan': dict(state='approved', rev=1, stages=[stage('s1'), stage('s2')])})
    for sid in ('s1', 's2'):
        missions.step(storage.get_mission(mid))  # prepare_next only, no planner action
        run(mid, {'action': 'research', 'question': 'Find background'},
                 {'action': 'stage_done', 'stage_id': sid, 'summary': 'Found background', 'found': {}})
    run(mid, {'action': 'finish', 'summary': 'Research complete.'})
    steps = [(s['kind'], s['name']) for s in storage.get_mission_steps(mid)]
    # Fixed baseline from main for this scripted run: no start/end marker rows.
    check(steps == [('tool', 'research'), ('tool', 'research'), ('llm', 'finish')], steps)
    check(storage.get_mission(mid)['status'] == 'done', 'script finishes the planned mission')

def scenario_stage_refusal_discards_board_and_sends_nothing():
    mid,p=fresh();lookups(mid)
    stage=dict(id='s',kind='work',state='running',title='Find',goal='Find',step_budget=12,steps_used=0,
               subject=list(missions.subject_of(storage.get_mission(mid))))
    storage.update_mission(mid,{'plan':dict(state='approved',rev=1,stages=[stage])})
    with patch.object(planned,'planner_action',return_value={'status':'refused','message':'Stage moved.'}):
        run(mid,present(mid))
    check(not boards.for_project(p['id']) and not POSTS,'a refused stage must leave no board or card')
    steps=storage.get_mission_steps(mid)
    check(steps[-1]['name']=='refused' and steps[-1]['result_json']=={'note':'Stage moved.'},steps)
    check(not any(s['name']=='present' for s in steps),'no successful present step for refused stage')

if __name__=='__main__':
    old=missions._llm, missions._post, web.research, page_lookup.requests.get, browse.render_page, net_guard._resolve
    missions._post=lambda dm,argyle,body,card=None: POSTS.append((dm,body,card)) or {'id':str(len(POSTS))}
    web.research=lambda *a,**k: {'status':'success','facts':[],'sources':[]}
    page_lookup.requests.get=lambda *a,**k: Response()
    browse.render_page=lambda *a,**k: (_ for _ in ()).throw(AssertionError('unexpected fallback'))
    net_guard._resolve=public
    failed=0
    try:
        for name,fn in list(globals().items()):
            if name.startswith('scenario_'):
                try: fn(); print('PASS',name)
                except Exception: failed+=1; print('FAIL',name); traceback.print_exc()
    finally:
        missions._llm, missions._post, web.research, page_lookup.requests.get, browse.render_page, net_guard._resolve=old
    raise SystemExit(bool(failed))
