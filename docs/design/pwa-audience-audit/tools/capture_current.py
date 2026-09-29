"""Read-only PWA review against a temporary database and fictional fixtures."""
import os, sys, tempfile, json
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/'chauffeur'),str(ROOT/'chauffeur/tests')]
os.environ['CHAUFFEUR_DATA_DIR']=tempfile.mkdtemp(prefix='chauffeur_design_audit_')
from live_app import live_app
from services import storage, ha_api
from services.stages import CAPABILITIES
OUT=ROOT/'docs/design/pwa-audience-audit/current'
OUT.mkdir(parents=True,exist_ok=True)
day=datetime.now().strftime('%Y-%m-%d')
profiles=[('adult','Alex Morgan','parent'),('sprout','Jamie','child'),('explorer','Maya','child'),('navigator','Sam','child'),('copilot','Jordan','child')]
def seed():
    storage.add_driver({'id':'d1','name':'Alex Morgan','color_code':'#287a72'})
    for key,name,role in profiles:
        storage.add_member({'id':key,'name':name,'role':role,'driver_id':'d1' if key=='adult' else None,'color_code':'#7c3aed','stage_override':key if role=='child' else None})
ha_api.get_states=lambda *a,**kw:[]
ha_api.get_state=lambda *a,**kw:None
served=live_app(seed)
events=[{'id':'soccer','title':'Soccer practice','start':day+'T16:00:00','end':day+'T17:00:00','location':'Riverside fields','calendar_ids':['maya'],'event_type':'activity'}, {'id':'piano','title':'Piano lesson','start':day+'T17:30:00','end':day+'T18:00:00','location':'Music studio','calendar_ids':['sam'],'event_type':'activity'}]
schedule={'events':events,'assignments':{'soccer':'d1','piano':'d1'},'calendar_metadata':{'maya':{'summary':'Maya','backgroundColor':'#7c3aed'},'sam':{'summary':'Sam','backgroundColor':'#0891b2'}},'initial_edges':{},'route_edges':{},'final_edges':{}}
chores=[{'id':'c1','title':'Unload the dishwasher','description':'Put clean dishes away','points':10,'state':'claimed','claimed_by':'explorer','claimed_by_name':'Maya','eligible_member_ids':[]},{'id':'c2','title':'Take out recycling','description':'Blue bin by the door','points':15,'state':'done','claimed_by':'navigator','claimed_by_name':'Sam','eligible_member_ids':[]},{'id':'c3','title':'Water the plants','points':5,'state':'open','eligible_member_ids':[]}]
routine={'items':[{'id':'r'+str(i),'title':title,'checked':i==0,'time_of_day':t,'steps':[]} for i,(title,t) in enumerate([('Brush your teeth','07:00'),('Pack your backpack','07:15'),('Put your shoes on','07:25'),('Put away your bag','15:30'),('Read for 15 minutes','19:00')])],'streak':{'today_total':5,'today_done':1,'current':3}}
metrics={}
try:
  for key,name,role in profiles:
    token=storage.create_member_token(key)
    with served.browser(reduced_motion='reduce',has_touch=True) as page:
      page.set_viewport_size({'width':390,'height':844})
      page.set_default_timeout(15000)
      init={'chauffeur_member_id':key,'chauffeur_member_token':token,'chauffeur_member_token_for':key,'chauffeur_view':'drives' if key=='adult' else 'myday','chauffeur_theme':'light'}
      if key=='adult':init['chauffeur_driver_id']='d1'
      page.add_init_script('localStorage.clear(); Object.entries('+json.dumps(init)+').forEach(([k,v])=>localStorage.setItem(k,v));')
      page.route('**/api/schedule?*',lambda r:r.fulfill(json=schedule))
      page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=204,body=''))
      page.route('**/api/stream*',lambda r:r.fulfill(status=204,body=''))
      page.route('**/api/music/favorites*',lambda r:r.fulfill(json={'items':[]}))
      page.route('**/api/routines/day?*',lambda r:r.fulfill(json=routine))
      page.route('**/api/chores',lambda r:r.fulfill(json=chores))
      page.route('**/api/points',lambda r:r.fulfill(json=[{'member_id':'explorer','name':'Maya','balance':45}]))
      page.route('**/api/members/*/day?*',lambda r:r.fulfill(json={'rides':[dict(e,driver={'member_id':'adult','name':'Alex','color_code':'#287a72'},status='scheduled') for e in events],'due_soon':([] if key=='adult' else [{'id':'task1','title':'Bring your library book','due_date':day,'kind':'bring','emoji':'??','label':'Tomorrow'}]),'launch':{'leave_at':day+'T07:35:00','driver':{'name':'Alex'},'title':'School'},'status_days':[]}))
      page.goto(served.url('app'),wait_until='domcontentloaded')
      page.wait_for_timeout(2000)
      if page.locator('#pin-modal-skip').is_visible():page.locator('#pin-modal-skip').click()
      page.wait_for_selector('#screen-schedule:not(.hidden)')
      page.wait_for_timeout(1800)
      if key!='adult':page.wait_for_function('document.getElementById("myday-content").innerText.includes("Pack your backpack")')
      else:page.wait_for_function('document.getElementById("days-container").innerText.includes("Soccer practice")')
      page.screenshot(path=str(OUT/f'{key}-day.png'))
      metrics[key]=page.evaluate('''()=>({stage:membersData.find(m=>m.id===selectedMemberId)?.stage,capabilities:kidCaps(),tabs:[...document.querySelectorAll('button[id^="tab-"]')].filter(e=>e.checkVisibility()).map(e=>({text:e.innerText,w:e.getBoundingClientRect().width})),header:document.querySelector('header').getBoundingClientRect().toJSON(),overflow:document.documentElement.scrollWidth>innerWidth,smallText:[...document.querySelectorAll('#screen-schedule *')].filter(e=>e.checkVisibility()&&e.children.length===0&&e.textContent.trim()&&parseFloat(getComputedStyle(e).fontSize)<12).slice(0,12).map(e=>({text:e.textContent.trim().slice(0,65),size:getComputedStyle(e).fontSize})),unnamedButtons:[...document.querySelectorAll('button')].filter(e=>e.checkVisibility()&&!e.innerText.trim()&&!e.getAttribute('aria-label')&&!e.title).map(e=>e.id||e.outerHTML.slice(0,100))})''')
      if key=='adult':
        for view in ('family','chores','messages','map','music'):
          page.evaluate('(v)=>setView(v)',view);page.wait_for_timeout(900)
          page.screenshot(path=str(OUT/f'adult-{view}.png'))
      if key=='explorer':
        page.evaluate('setView("chores")');page.wait_for_timeout(700)
        page.screenshot(path=str(OUT/'explorer-chores.png'))
      print(key, metrics[key]['tabs'],flush=True)
  (OUT/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
finally:served.stop()
