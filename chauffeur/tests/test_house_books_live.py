"""Live book pages: real shared controllers, paper registration, permissions, teardown."""
import json
from pathlib import Path
from test_house_hybrid_live import seed, live_app, ha_api

OUT = Path('../scratch/book-review')
WINDOWS = [dict(program_id='p' + str(i), member_id='k1', member_name='Maya',
                date='2026-09-24', time_start='16:30', title='Piano' if i == 0 else 'Reading ' + str(i),
                session_label='A gentle beginning', unit_title='Finding the notes',
                phase_name='Begin', unit_n=1, logged=False, steps=['Play three notes slowly.']) for i in range(3)]
CELEBRATIONS = dict(up_next=dict(member_name='Maya', title='Piano', milestone='A first melody'),
                    practiced=[dict(key='p1', member_name='Finn', title='Reading', sessions=3)],
                    celebrated=[dict(key='c1', member_name='Maya', milestone='Both hands together'),
                                dict(key='c2', member_name='Finn', milestone='A whole chapter')])
LESSON = {'scenes':[{'type':'say','text':'Make room for a little music.'},
                    {'type':'show','caption':'Listen to the beat.', 'primitive':{'kind':'timer', 'seconds':20}}]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed)
    assert served
    mode = {'tasks':'full', 'programs':'full'}
    task_rows = [dict(title='Replace the air filter' if i == 0 else 'Household task ' + str(i),
                      who='Maya' if i % 2 else None, due='2020-01-01', past_due=i == 0, unclaimed=i % 2 == 0) for i in range(6)]
    try:
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            page.set_default_timeout(20000)
            page.add_init_script('''window.bookPolls = new Set();
              const si=window.setInterval, ci=window.clearInterval;
              window.setInterval=function(fn, ms, ...rest){const id=si(fn,ms,...rest); if(ms===30000)bookPolls.add(id); return id;};
              window.clearInterval=function(id){bookPolls.delete(id);return ci(id);};''')
            page.route('**/api/v2/chat/stream*', lambda r:r.fulfill(status=204, body=''))
            page.route('**/api/music/favorites*', lambda r:r.fulfill(json={'items':[]}))
            page.route('**/api/home_board?widgets=tasks', lambda r:r.fulfill(
                body='invalid' if mode['tasks'] == 'error' else json.dumps({'tiles':[{'type':'tasks','data':
                    {'tasks':task_rows,'total':9} if mode['tasks'] == 'full' else {'empty':'Nothing owed right now.'}}]}), content_type='application/json'))
            page.route('**/api/programs/celebrations', lambda r:r.fulfill(
                body='invalid' if mode['programs'] == 'error' else json.dumps(CELEBRATIONS if mode['programs'] == 'full' else {}), content_type='application/json'))
            page.route('**/api/practice-windows?*', lambda r:r.fulfill(
                body='invalid' if mode['programs'] == 'error' else json.dumps({'windows':WINDOWS if mode['programs'] == 'full' else []}), content_type='application/json'))
            page.route('**/api/programs/*/lesson-scenes?*', lambda r:r.fulfill(json={'lesson':LESSON}))
            page.route('**/api/members', lambda r:r.fulfill(json=[dict(id='parent',name='Parent',role='parent',has_pin=True)]))
            writes=[]
            page.on('request', lambda r:writes.append(r.url) if '/api/' in r.url and r.method == 'POST' and any(s in r.url for s in ('/programs/', '/auth', '/tasks')) else None)
            page.goto(served.url('house?compare=living&light=day'), wait_until='domcontentloaded')
            page.wait_for_function('window.chfHouseComparison?.readyMs > 0')
            # Keep the real lesson controller; isolate its external audio adapter.
            page.evaluate("() => { window.chfLocalPlayer={start:async()=>{}}; MusicLogic.findLocalEntity=async()=>({entity:null}); }")

            def enter(key):
                page.locator(f'#hybrid-hotspots [data-card="{key}"], #hybrid-shortcuts [data-card="{key}"]').filter(visible=True).click()
                page.wait_for_selector(f'#hybrid-room-frame[data-view="{key}"][data-phase="detail"]')
                page.locator('#house-book').wait_for(state='visible')

            def leave():
                page.locator('#hybrid-view-back').click()
                page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')

            def registered():
                assert page.evaluate('''() => {
                  const a=document.querySelector('#hybrid-detail-picture').getBoundingClientRect(), b=document.querySelector('#house-book').getBoundingClientRect();
                  return ['x','y','width','height'].every(k=>Math.abs(a[k]-b[k])<1);
                }'''), 'ink must share the photo camera'
                page.screenshot(path=str(OUT/'latest.png'))
                assert page.locator('#hybrid-room-frame').evaluate("el=>getComputedStyle(el).overflow==='clip'")
                assert page.evaluate("() => {const r=document.getElementById('hybrid-detail-picture').getBoundingClientRect();return r.x<=1 && r.y<=1 && r.right>=innerWidth-1 && r.bottom>=innerHeight-1;}")
                if page.viewport_size['width'] < 700:
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

            enter('tasks')
            page.get_by_text('Replace the air filter', exact=True).wait_for()
            assert page.locator('.book-task').count() == 6
            assert page.locator('.is-overdue').inner_text().find('Overdue') >= 0
            assert 'next 6 of 9' in page.locator('.book-note').last.inner_text()
            registered()
            page.screenshot(path=str(OUT/'ledger-day-desktop.png'))
            page.locator('#house-compare-light').select_option('night')
            page.wait_for_selector('#hybrid-detail[data-light="night"]')
            registered()
            page.screenshot(path=str(OUT/'ledger-night-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(OUT/'ledger-phone-left.png'))
            page.get_by_role('button',name='Notes & manage →').tap()
            registered()
            assert page.get_by_role('button',name='Manage with parent PIN').is_visible()
            page.screenshot(path=str(OUT/'ledger-phone-right.png'))
            # Exercise the existing PIN gate, cancel before credentials or navigation.
            page.evaluate("() => { window.pinAsked=0; window.promptInput=async(title,message)=>{if(message.includes('PIN'))pinAsked++;return null;}; }")
            page.get_by_role('button',name='Manage with parent PIN').tap()
            page.wait_for_function('pinAsked===1')
            page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
            assert not writes
            mode['tasks']='error'
            enter('tasks')
            page.locator('#house-book').get_by_text('Could not load this list. Please try again.',exact=True).wait_for()
            mode['tasks']='empty'
            page.get_by_role('button',name='Try again',exact=True).click()
            page.get_by_text('Nothing owed right now.',exact=True).wait_for()
            leave()

            page.set_viewport_size({'width':1400,'height':1000})
            baseline=page.evaluate('bookPolls.size')
            enter('programs')
            page.locator('.book-practice').get_by_text('Piano',exact=True).wait_for()
            page.wait_for_function("Alpine.$data(document.querySelector('.book-spread')).pgToday[0]?.raw._lesson")
            assert page.locator('.book-practice').count() == 2
            assert page.get_by_text('Both hands together',exact=False).is_visible()
            registered()
            page.screenshot(path=str(OUT/'program-night-desktop.png'))
            page.locator('#house-compare-light').select_option('day')
            page.wait_for_selector('#hybrid-detail[data-light="day"]')
            page.get_by_role('button',name='Turn practice page').click()
            page.get_by_text('Reading 2',exact=True).wait_for()
            page.get_by_role('button',name='Turn practice page').click()
            page.get_by_role('button',name='Turn journal page').click()
            page.get_by_text('Finn practised Reading three times',exact=True).wait_for()
            page.get_by_role('button',name='Turn journal page').click()
            page.screenshot(path=str(OUT/'program-day-desktop.png'))
            start=page.get_by_role('button',name='Start session ↗').first
            start.click()
            lesson=page.locator('#house-book-lesson')
            lesson.wait_for(state='visible')
            page.get_by_text('Make room for a little music.',exact=True).wait_for()
            assert lesson.bounding_box()['width'] < 500
            page.screenshot(path=str(OUT/'lesson-desktop.png'))
            page.keyboard.press('Escape')
            lesson.wait_for(state='hidden')
            assert start.evaluate('(el)=>document.activeElement===el')
            assert page.locator('#hybrid-room-frame').get_attribute('data-view') == 'programs'
            page.set_viewport_size({'width':390,'height':844})
            start.tap()
            page.wait_for_selector('#hybrid-room-frame[data-book-page="right"]')
            registered()
            page.screenshot(path=str(OUT/'lesson-phone.png'))
            page.get_by_role('button',name='Continue',exact=True).tap()
            page.get_by_text('Listen to the beat.',exact=True).wait_for()
            leave()
            assert page.evaluate("!Alpine.$data(document.getElementById('house-book-lesson')).openFlag && !Alpine.$data(document.getElementById('house-book-lesson')).timer")
            page.wait_for_function(f'bookPolls.size === {baseline}')
            assert not writes
            mode['programs']='error'
            enter('programs')
            page.get_by_text("Today's practice could not refresh.",exact=False).wait_for()
            mode['programs']='empty'
            page.get_by_role('button',name='Try again',exact=True).filter(visible=True).click()
            page.get_by_text('No practice planned for today.',exact=True).wait_for()
            leave()
            mode['programs']='full'
            page.set_viewport_size({'width':844,'height':390})
            enter('programs')
            page.locator('.book-practice').get_by_text('Piano',exact=True).wait_for()
            registered()
            page.screenshot(path=str(OUT/'program-landscape-phone.png'))
            page.get_by_role('button',name='Turn practice page').tap()
            page.get_by_text('Reading 2',exact=True).wait_for()
            page.get_by_role('button',name='Start session ↗').tap()
            page.get_by_role('button',name='Close session',exact=True).tap()
            leave()
            assert not served.errors(), served.errors()
            print('PASS: book data, paper registration, day/night, touch, page turns, PIN cancellation, in-book sessions, Escape/focus, errors/empty and teardown',flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    main()
