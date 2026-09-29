from pathlib import Path
from playwright.sync_api import sync_playwright
import json
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'previews';OUT.mkdir(exist_ok=True)
errors=[];report=[]
def capture(locator,target,**options):
 Path(target).write_bytes(locator.screenshot(**options))
with sync_playwright() as p:
 browser=p.chromium.launch()
 page=browser.new_page(viewport={'width':1600,'height':1250},device_scale_factor=1,reduced_motion='reduce')
 page.set_default_timeout(10000)
 page.on('pageerror',lambda e:errors.append(str(e)))
 url=(ROOT/'index.html').as_uri()
 for who in ['adult','sprout','explorer','navigator','copilot']:
  print('goto',who,flush=True)
  page.goto(url+'?audience='+who)
  screens=page.locator('#screen-links button').evaluate_all('(els)=>els.map(e=>e.dataset.screen)')
  for screen in screens:
   print('screen',who,screen,flush=True)
   page.locator(f'#screen-links button[data-screen={screen}]').click()
   capture(page.locator('#phone'),OUT/f'{who}-{screen}.png')
   report.append(page.locator('#phone').evaluate('''e=>({audience:e.dataset.audience,screen:document.querySelector('#screen-links .active').innerText,overflow:e.scrollWidth>e.clientWidth,contentOverflow:e.querySelector('.app-content').scrollWidth>e.querySelector('.app-content').clientWidth,buttons:[...e.querySelectorAll('button')].filter(b=>b.checkVisibility()).length,smallTargets:[...e.querySelectorAll('button')].filter(b=>b.checkVisibility()).filter(b=>b.getBoundingClientRect().height<44).map(b=>b.innerText)})'''))
  page.locator('#screen-links button').first.click()
  page.locator('#theme').click()
  capture(page.locator('#phone'),OUT/f'{who}-dark.png')
 page.goto(url+'?compare')
 capture(page,OUT/'five-audiences.png',full_page=True)
 page.goto(url)
 capture(page,OUT/'adult-review.png',full_page=True)
 for role in ('adult','keeping-up','helper'):
  page.locator('#role').select_option(role)
  capture(page.locator('#phone'),OUT/f'adult-role-{role}.png')
  if role in ('adult','helper'):assert page.locator('#app-content [data-action=approvals]').count()==0
  if role=='helper':assert page.locator('#app-nav button').count()==2
 page.locator('#role').select_option('parent')
 page.locator('[data-action=approvals]').click()
 page.locator('[data-action=approved]').click()
 assert 'Approved' in page.locator('#toast').inner_text()
 page.locator('#app-nav [data-screen=more]').click()
 page.locator('[data-search=features]').fill('music')
 assert page.locator('#app-content .list-row:visible').count()==1
 page.locator('#app-content .list-row:visible').click()
 assert page.get_by_role('dialog',name='Music').is_visible()
 page.keyboard.press('Escape')
 assert page.locator('#sheet').is_hidden()
 page.locator('.audiences [data-audience=explorer]').click()
 page.locator('[data-task=bag-away]').click()
 assert page.locator('[data-task=bag-away]').get_attribute('aria-pressed')=='true'
 page.locator('[data-task=bag-away]').click()
 assert page.locator('[data-task=bag-away]').get_attribute('aria-pressed')=='false'
 page.locator('#app-header [data-action=notifications]').click()
 assert page.locator('#sheet [data-action=approved]').count()==0
 page.keyboard.press('Escape')
 page.locator('#app-nav [data-screen=messages]').click()
 page.locator('[data-action=thread]').first.click()
 page.locator('[name=message]').fill('See you at 3:15.')
 page.locator('form.composer button').click()
 assert page.locator('#preview-messages').inner_text()=='See you at 3:15.'
 page.keyboard.press('Escape')
 for width in (360,390,768):
  page.set_viewport_size({'width':width,'height':1000})
  for who in ('adult','sprout','explorer','navigator','copilot'):
   page.goto(url+'?audience='+who)
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,who)
   assert page.locator('#app-content').evaluate('e=>e.scrollWidth<=e.clientWidth'),(width,who)
  capture(page,OUT/f'review-{width}.png',full_page=True)
 assert not errors,errors
 assert not any(r['overflow'] or r['contentOverflow'] for r in report),report
 assert not any(r['smallTargets'] for r in report),report
 (OUT/'verification.json').write_text(json.dumps({'errors':errors,'screens':report,'interactions':'approvals, search, task completion/undo, messages, Escape; 360/390/768 reflow'},indent=2))
 print('PASS',len(report),'screens; five dark previews; interactions; responsive layout')
 browser.close()
