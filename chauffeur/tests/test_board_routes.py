"""Real authenticated board routes, cleanup and registry readers, entirely offline."""
import io
import os
import traceback
import uuid
from unittest.mock import patch
from types import SimpleNamespace
from PIL import Image
from fastapi.testclient import TestClient
from harness import check
from services import storage, boards, boards_contract as C, page_lookup, net_guard, browse, projects, deletion, voice_tools, agent_tools_v2 as tools
from test_subjects import _fresh as fresh_subjects, MOM, KID
from test_projects import _make
from test_boards import seed
from test_page_lookup import Response, public
import main

CLIENT=TestClient(main.app)
HEADERS={}
def fresh(audience='household'):
    fresh_subjects(); storage.projects_table.truncate()
    storage.get_settings=lambda: {'auth_enforce':True,'calendar_ids':[]}
    a=seed(); p=_make('mom', MOM, audience=audience)
    mid=storage.add_mission(dict(goal='Concert outfit', created_by='mom', project_id=p['id']))
    storage.lookups_table.update({'mission_id':mid})
    fields,note=boards.build_from_present(a, storage.get_mission(mid)); check(not note,note)
    b=boards.create(fields)
    HEADERS.clear(); HEADERS.update({m:{'X-Member-Token':storage.create_member_token(m,proof='password',minted_on='personal')} for m in ('mom','kid')})
    return p,b

def url(p,b): return f"/api/projects/{p['id']}/boards/{b['id']}"
def get(path, who='mom'): return CLIENT.get(path,headers=HEADERS[who])

def scenario_get_board_view():
    p,b=fresh(); r=get(url(p,b))
    check(r.status_code==200 and set(r.json())==C.VIEW_KEYS, (r.status_code,r.text))

def scenario_board_in_other_project_404():
    p,b=fresh(); other=_make('mom',MOM)
    r=get(url(other,b)); check(r.status_code==404 and r.json()['detail']=='This board is no longer available.',r.text)

def scenario_parents_board_hidden_from_child():
    p,b=fresh('parents'); lid=next(iter(boards.lookup_ids(b)))
    for path in (url(p,b),url(p,b)+'/image/'+lid,f"/api/projects/{p['id']}"):
        check(get(path,'kid').status_code==404,path)
    check(projects.rows(p,KID)==[], 'no child row')

def scenario_image_cached_and_downscaled():
    p,b=fresh(); lid=b['options'][0]['items'][0]['lookup_id']; calls=[]
    buf=io.BytesIO(); Image.new('RGBA',(2000,1000),(20,60,100,0)).save(buf,format='PNG')
    old=page_lookup.requests.get
    page_lookup.requests.get=lambda u,**kw: calls.append(u) or Response(200,buf.getvalue(),{'Content-Type':'image/png'})
    try:
        for _ in range(2):
            r=get(url(p,b)+'/image/'+lid)
            check(r.status_code==200 and r.headers['cache-control']=='private, max-age=86400',r.text[:100])
            image=Image.open(io.BytesIO(r.content)); check(image.size==(800,400) and image.format=='JPEG',image.size)
            check(min(image.getpixel((400,200))) >= 250,'transparent pixels must composite onto white')
        check(len(calls)==1 and os.path.isfile(os.path.join(boards.image_dir(b['id']),lid+'.jpg')),calls)
    finally: page_lookup.requests.get=old

def scenario_image_only_from_lookup():
    p,b=fresh(); calls=[]; old=page_lookup.requests.get
    page_lookup.requests.get=lambda u,**kw: calls.append(u) or Response(500)
    try:
        check(get(url(p,b)+'/image/lk_9999999999').status_code==404,'foreign lookup')
        lid=b['options'][0]['items'][0]['lookup_id']
        get(url(p,b)+'/image/'+lid+'?url=http://127.0.0.1/')
        check(calls==['https://store.test/i.png'],calls)
    finally: page_lookup.requests.get=old

def scenario_image_private_address_404():
    p,b=fresh(); lid=b['options'][0]['items'][0]['lookup_id']; old=page_lookup.requests.get; calls=[]
    page_lookup.requests.get=lambda *a,**kw: calls.append(a) or Response(302,'',{'Location':'http://127.0.0.1/'})
    try:
        check(get(url(p,b)+'/image/'+lid).status_code==404,'redirect blocked')
        check(len(calls)==1,'no private request')
        storage.lookups_table.update({'image_url':'http://192.168.1.10/'})
        check(get(url(p,b)+'/image/'+lid).status_code==404 and len(calls)==1,'private refused before fetch')
    finally: page_lookup.requests.get=old

def scenario_project_row_present():
    p,b=fresh(); r=get(f"/api/projects/{p['id']}"); check(r.status_code==200,r.text)
    row=next(v for v in r.json()['rows'] if v['kind']=='board')
    check(set(row)==C.ROW_KEYS and row['sheet']['id']==b['id'],row)

def scenario_project_delete_removes_board_and_cache():
    p,b=fresh(); folder=boards.image_dir(b['id']);os.makedirs(folder,exist_ok=True)
    open(os.path.join(folder,'cached.jpg'),'wb').close()
    deletion.delete('project',p['id'])
    deletion.maintain()
    check(not boards.get(b['id']) and not storage.lookups_table.all() and not os.path.exists(folder),'project cleanup')
    check(get(url(p,b)).status_code==404,'old card unavailable')

def scenario_board_view_tool_audience():
    p,b=fresh('parents')
    out=tools.execute_tool('board_view',{'board_id':b['id'],'acting_member':MOM},actor=KID)
    check(out.get('status')=='error' and 'Concert' not in str(out),out)
    out=tools.execute_tool('board_view',{'board_id':b['id']},actor=MOM)
    check(out.get('status')=='success' and not voice_tools.row_checks_after('board_view',out),out)
    p,b=fresh(); out=tools.execute_tool('board_view',{'board_id':b['id']},actor=MOM)
    check(out.get('status')=='success' and voice_tools.row_checks_after('board_view',out) and 'board_view' in voice_tools.SPEAKABLE,out)
    check('board_view' in voice_tools.TOOLS,'voice declaration')
    from services import missions
    check('board_view' not in missions.READ_TOOLS,'not a planner read')

def scenario_board_view_focus_and_voice_entry_points():
    from services import triage, app_voice, voice_private
    from services.voice_identity import VoiceContext
    p,b=fresh()
    tid=storage.add_thread(dict(title='Concert', kind='project', state='open', project_id=p['id'],
                               owner_member_id='mom', created_by='mom', next_action='Pick the shoes'))
    storage.boards_table.update({'thread_id':tid})
    focus='board-test-focus'; triage.set_focus(focus,'thread',tid,'Concert')
    out=tools.execute_tool('board_view',{},actor=MOM,focus_key=focus)
    check(out.get('board_id')==b['id'],out)
    ctx=VoiceContext('', '', 'request', 'generation')
    with patch.object(VoiceContext, 'actor', return_value=MOM):
        out=voice_tools.dispatch('board_view',{'board_id':b['id']},ctx)
    check(out.get('status')=='success',out)
    turn=app_voice.begin(MOM,HEADERS['mom']['X-Member-Token'],uuid.uuid4().hex)
    turn.before_tool('board_view',{});turn.tool_result(out)
    check(turn.audible(out),'household phone speech')
    satellite=voice_private.SatelliteTurn(MOM)
    satellite.before_tool('board_view',{});satellite.tool_result(out)
    check(satellite.safe,'household satellite speech')
    storage.projects_table.update({'audience':'parents'})
    private=tools.execute_tool('board_view',{'board_id':b['id']},actor=MOM)
    turn.tool_result(private);satellite.tool_result(private)
    check(not turn.audible(private) and not satellite.safe,'private speech withheld on both rails')

def scenario_mission_delete_preserves_board_lookups():
    p,b=fresh(); mid=b['rounds'][0]['mission_id']
    storage.lookups_table.insert(dict(id='lk_9999999999',mission_id=mid))
    deletion.delete('mission',mid);deletion.maintain()
    check(boards.get(b['id']) and len(storage.lookups_table.all())==3,'board provenance survives mission deletion; unused lookup removed')

def scenario_source_mission_audience_gates_every_surface():
    from services import missions, access, situations
    p,b=fresh(); mid=b['rounds'][0]['mission_id'];storage.boards_table.truncate()
    storage.update_mission(mid,{'subject_kind':'occasion','subject_id':'o1','subject_rev':1})
    action=dict(action='present',title='Surprise',layout='options',noun='looks',slots=[{'role':'Shoes'}],
                options=[dict(title='Look',items=[dict(slot=0,lookup=r['id'])]) for r in page_lookup.for_mission(mid)],summary='Found surprises.')
    with patch.object(missions,'_llm',return_value=action),patch.object(missions,'_post',return_value={'id':'notice'}), \
         patch.object(situations,'touched',return_value=None):
        missions.step(storage.get_mission(mid))
    b=boards.for_project(p['id'])[0];lid=b['options'][0]['items'][0]['lookup_id']
    buf=io.BytesIO();Image.new('RGB',(10,10),'white').save(buf,format='PNG')
    with patch.object(page_lookup.requests,'get',return_value=Response(200,buf.getvalue(),{'Content-Type':'image/png'})):
        check(get(url(p,b)).status_code==200,'parent sees board')
        check(any(r['kind']=='board' for r in get(f"/api/projects/{p['id']}").json()['rows']),'parent sees row')
        check(get(url(p,b)+'/image/'+lid).status_code==200,'parent sees image')
        check(get(url(p,b),'kid').status_code==404,'source-hidden child must not see board')
        check(get(url(p,b)+'/image/'+lid,'kid').status_code==404,'source-hidden child must not see cached image')
    check(not any(r['kind']=='board' for r in get(f"/api/projects/{p['id']}",'kid').json()['rows']),'no child row')
    check(tools.execute_tool('board_view',{'board_id':b['id']},actor=KID)['status']=='error','tool denies child')
    parent=tools.execute_tool('board_view',{'board_id':b['id']},actor=MOM)
    check(parent['status']=='success' and not voice_tools.row_checks_after('board_view',parent),'source private on shared speech')
    check(not boards.can_see(b,access.HOUSE),'HOUSE must see the source mission too')
    deletion.delete('mission',mid);deletion.maintain()
    check(get(url(p,b),'kid').status_code==200,'after source removal use project visibility')

def scenario_image_deadline_returns_404():
    p,b=fresh();lid=b['options'][0]['items'][0]['lookup_id'];clock=[0.0];closed=[]
    class Slow(Response):
        def iter_content(self,chunk_size=65536):
            for _ in range(3):clock[0]+=8;yield b'x'
        def close(self):closed.append(True)
    with patch.object(page_lookup,'time',SimpleNamespace(monotonic=lambda:clock[0])), \
         patch.object(page_lookup.requests,'get',return_value=Slow(headers={'Content-Type':'image/png'})):
        check(get(url(p,b)+'/image/'+lid).status_code==404,'image deadline')
    check(clock[0]==16 and closed and not os.path.exists(boards.image_dir(b['id'])),'no timed-out cache')

def scenario_image_transparency_modes_and_format_allowlist():
    for mode in ('RGBA','LA','P'):
        p,b=fresh();lid=b['options'][0]['items'][0]['lookup_id'];buf=io.BytesIO()
        source=Image.new(mode,(10,10), (20,60,100,0) if mode=='RGBA' else (20,0) if mode=='LA' else 0)
        if mode=='P':source.info['transparency']=0
        source.save(buf,format='PNG')
        original=Image.open; formats=[]
        def opening(*a,**kw):formats.append(kw.get('formats'));return original(*a,**kw)
        with patch.object(page_lookup.requests,'get',return_value=Response(200,buf.getvalue(),{'Content-Type':'image/png'})), \
             patch.object(Image,'open',side_effect=opening):
            r=get(url(p,b)+'/image/'+lid)
        check(r.status_code==200 and formats==[['JPEG','PNG','WEBP','GIF']],formats)
        check(min(original(io.BytesIO(r.content)).getpixel((5,5)))>=250,mode+' transparent pixel must be white')

if __name__=='__main__':
    old=net_guard._resolve, page_lookup.requests.get, browse.render_page, main.trigger_background_refresh
    net_guard._resolve=public
    page_lookup.requests.get=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('unexpected network'))
    browse.render_page=lambda *a,**kw: None
    main.trigger_background_refresh=lambda *a,**kw: None
    failed=0
    try:
        for name,fn in list(globals().items()):
            if name.startswith('scenario_'):
                try: fn();print('PASS',name)
                except Exception: failed+=1;print('FAIL',name);traceback.print_exc()
    finally:
        net_guard._resolve,page_lookup.requests.get,browse.render_page,main.trigger_background_refresh=old
        CLIENT.close()
    raise SystemExit(bool(failed))
