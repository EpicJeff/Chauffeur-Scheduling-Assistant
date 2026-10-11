"""The thread card's details show the mission's steps (the shared transcript,
proposals included), the release buttons work from the thread and the
transcript follows, a hand-off card carries its link, and a child owner's
House card shows Argyle's question but no buttons (the steps are the admin
page's)."""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='browse_thread_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    from services import threads, missions
    storage.update_settings({'llm_gemini_api_key': '', 'missions_enabled': True, 'contact_first_name': 'Jeff'})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True, 'color_code': '#f59e0b'})
    tid = threads.create('Dishwasher repair', owner_member_id='mom', goal='get it fixed', created_by='mom')
    mid = storage.add_mission({'goal': 'get the dishwasher fixed', 'origin_kind': 'thread', 'origin_ref': tid, 'created_by': 'mom', 'tier': 'mission'})
    storage.add_mission_step(mid, {'kind': 'tool', 'name': 'search_mail', 'args_json': {'query': 'cafe'}, 'result_json': {'message': 'Found: Your Cafe order'}})
    storage.add_mission_step(mid, {'kind': 'proposal', 'name': 'add_thread_note', 'args_json': {'text': 'call Ace'},
                                   'result_json': {'proposal_id': 'p-live-1', 'card': {'title': 'Add: call Ace Pools'}, 'why': 'they quoted'}})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'release', 'result_json': {'question': 'Share with bodewell.com: Jeff?', 'site': 'bodewell.com', 'fields': ['first_name'],
                                                                                     'values': {'first_name': 'Jeff'}, 'browse': {'goal': 'g', 'site': 'bodewell.com', 'start_url': 'https://bodewell.com/f'}}})
    storage.update_mission(mid, {'status': 'waiting_user'})
    gt = threads.create('Gutters', owner_member_id='mom', created_by='mom')
    gm = storage.add_mission({'goal': 'get the gutters cleaned', 'origin_kind': 'thread', 'origin_ref': gt, 'created_by': 'mom', 'tier': 'mission'})
    storage.add_mission_step(gm, {'kind': 'ask', 'name': 'handoff', 'result_json': {'question': 'I got as far as https://gutterco.example/book. Finish it on your phone and tell me what you found.',
                                                                                    'url': 'https://gutterco.example/book', 'filled': {}, 'reason': 'captcha'}})
    storage.update_mission(gm, {'status': 'waiting_user'})
    kt = threads.create("Kate's science fair", owner_member_id='kid', created_by='mom')
    km = storage.add_mission({'goal': 'science fair supplies', 'origin_kind': 'thread', 'origin_ref': kt, 'created_by': 'mom', 'tier': 'mission'})
    storage.add_mission_step(km, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Which day is it?'}})
    storage.update_mission(km, {'status': 'waiting_user'})
    missions._browse_async = False
    missions._browse = lambda **kw: {'outcome': 'done', 'text': 'ok', 'learned': {}, 'stopped_at': 'u', 'wanted_fields': [], 'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            page.wait_for_selector('#threads .situation-card', timeout=15000)
            card = page.locator('#threads .situation-card:has-text("Dishwasher repair")').first
            check(card.locator('.sit-next button').first.inner_text().startswith('Share with bodewell.com'), "the thread leads with the release")
            # The details that belong to this card: the next <details> sibling.
            det = card.locator('xpath=../following-sibling::details[1]').first
            det.locator('summary').first.click()
            page.wait_for_timeout(800)
            tl = det.inner_text()
            check('search_mail' in tl and 'Your Cafe order' in tl, f"the mission's steps are in the thread's details: {tl[:300]}")
            check('Share with bodewell.com' in tl, "the release ask is shown there too")
            check('Add: call Ace Pools' in tl and det.locator('button:has-text("Approve")').count() == 1, f"a proposal step draws with its Approve: {tl[:400]}")
            check('Jeff' in card.locator('.sit-next button').first.inner_text(), "the Share button shows the exact value")
            gutters = page.locator('#threads .situation-card:has-text("Gutters")').first
            check(gutters.locator('a[href="https://gutterco.example/book"]').count() == 1, f"the hand-off card carries its link: {gutters.inner_html()[:600]}")
            card.locator('.sit-next button').first.click()
            page.wait_for_timeout(1500)
            m = [x for x in storage.get_missions() if x['goal'] == 'get the dishwasher fixed'][0]
            check(m['status'] == 'running' and m.get('releases'), f"Share from the thread card released and resumed: {m['status']}")
            if page.locator('#cc-alert-modal').is_visible():
                page.locator('#cc-alert-modal button:has-text("OK")').click()
            page.wait_for_timeout(800)
            det = card.locator('xpath=../following-sibling::details[1]').first
            if not det.get_attribute('open'):
                det.locator('summary').first.click()
                page.wait_for_timeout(800)
            tl = det.inner_text()
            check('Not these' not in tl and 'running' in tl, f"the thread's transcript followed the release: {tl[:300]}")
            check(not b.errors, f"script errors: {b.errors}")

        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('app'), wait_until='networkidle')
            page.evaluate("localStorage.setItem('chauffeur_member_id', 'kid');")
            page.goto(served.url('app'), wait_until='networkidle')
            page.evaluate("async () => { await fetchHouseThreads(); }")
            page.wait_for_selector('#house-threads .situation-card', state='attached', timeout=15000)
            txt = page.locator('#house-threads').first.text_content()
            check('science fair' in txt and 'Which day is it?' in txt, f"the child sees the thread and Argyle's question: {txt[:200]}")
            check(page.locator('#house-threads button').count() == 0, "a child owner has no buttons")
            check(not b.errors, f"PWA script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_browse_thread_live')
