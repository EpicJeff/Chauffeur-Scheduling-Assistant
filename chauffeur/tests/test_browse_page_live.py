"""/missions draws a browse step with its report and last screenshot, a release
ask with Share / Not these / Stop, and a hand-off with its link."""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='browse_page_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63f8ff1f0003030200f0b3c2d10000000049454e44ae426082')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    from services import missions
    storage.update_settings({'llm_gemini_api_key': '', 'missions_enabled': True, 'contact_first_name': 'Jeff', 'contact_email': 'ffejnosliw@gmail.com'})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    mid = storage.add_mission({'goal': 'get the dishwasher fixed', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    with open(os.path.join(missions.browse_dir(mid), 'turn_03.png'), 'wb') as f:
        f.write(PNG)
    storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'find slots', 'site': 'bodewell.com'},
                                   'result_json': {'outcome': 'needs_release', 'text': 'the form wants first_name, email', 'learned': {}, 'turns': 3,
                                                   'stopped_at': 'https://bodewell.com/guest-schedule-service', 'screenshots': ['turn_03.png'], 'filled': {}}})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'release', 'result_json': {'question': 'Share with bodewell.com: Jeff · ffejnosliw@gmail.com?', 'site': 'bodewell.com',
                                                                                     'fields': ['first_name', 'email'], 'values': {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com'},
                                                                                     'browse': {'goal': 'find slots', 'site': 'bodewell.com', 'start_url': 'https://bodewell.com/guest-schedule-service'}}})
    storage.update_mission(mid, {'status': 'waiting_user'})
    m2 = storage.add_mission({'goal': 'book the dishwasher repair', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    storage.add_mission_step(m2, {'kind': 'ask', 'name': 'submit', 'result_json': {
        'question': "Book at bodewell.com: Tue, Oct 20 8AM-12PM, $114.95 (button 'Book appointment')?", 'verb': 'book', 'site': 'bodewell.com',
        'url': 'https://www.bodewell.com/schedule', 'button': 'Book appointment', 'state': {'fields': {'notes': ''}, 'selected': ['Tue, Oct 20 8AM-12PM'], 'text': 't', 'text_sha': 'a' * 64, 'prices': ['$114.95']},
        'display': 'Trip charge $114.95', 'facts': {'slot': 'Tue, Oct 20 8AM-12PM', 'price': '$114.95'}, 'intent': '', 'filled': {'first_name': 'Jeff'}, 'changed': [],
        'browse': {'goal': 'book', 'site': 'bodewell.com', 'start_url': 'https://www.bodewell.com/schedule', 'released': {}}}})
    storage.update_mission(m2, {'status': 'waiting_user'})
    m3 = storage.add_mission({'goal': 'register for the permit', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    a3 = storage.add_mission_step(m3, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {'ask_id': 'a', 'browse_step_id': 'b', 'button': 'Send application', 'url': 'https://permits.example/a',
                                                                                             'state': {}, 'pressed_at': 1.0, 'outcome': 'unknown', 'text': ''}})
    storage.add_mission_step(m3, {'kind': 'ask', 'name': 'verify', 'result_json': {'question': "I pressed 'Send application' at https://permits.example/a and could not read whether it went through. Check your email or the site, then tell me below.",
                                                                                 'attempt_step_id': a3, 'button': 'Send application', 'url': 'https://permits.example/a', 'facts': {}, 'display': '', 'payment': False}})
    storage.update_mission(m3, {'status': 'waiting_user'})
    import time

    def fake(**kw):
        base = {'learned': {}, 'wanted_fields': [], 'turns': 2, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {'first_name': 'Jeff'}}
        ap = kw.get('approved')
        if ap:
            kw['on_attempt']({'ask_id': ap['ask_id'], 'button': ap['button'], 'url': kw['start_url'], 'state': ap['state'], 'pressed_at': time.time(), 'outcome': None, 'text': ''})
            return {**base, 'outcome': 'submitted', 'text': 'CONFIRMED: 12345', 'stopped_at': kw['start_url'], 'submit': None, 'changed': [], 'attempts_extra': [],
                    'attempt': {**ap, 'pressed_at': time.time(), 'outcome': 'confirmed', 'text': 'Confirmation number 12345'}}
        return {**base, 'outcome': 'captcha_failed', 'text': 'the check failed', 'stopped_at': 'https://bodewell.com/x'}
    missions._browse = fake
    missions._browse_async = False


def _open_record(page, served, title):
    row = next(r for r in storage.get_missions() if r['goal'] == title)
    page.goto(served.url('missions?id=' + row['id']), wait_until='networkidle')
    page.wait_for_selector('[data-record-sheet][data-open="true"][data-kind="mission"] details[open]', timeout=15000)


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            _open_record(page, served, 'get the dishwasher fixed')
            page.wait_for_selector('[data-record-sheet][data-kind=mission] .situation-card', timeout=15000)
            card = page.locator('[data-record-sheet][data-kind=mission] .situation-card:has-text("dishwasher fixed")').first
            check(card.locator('.sit-next button').first.inner_text().startswith('Share with bodewell.com'), "the card's next step is the release")
            rdet = card.locator('xpath=../following-sibling::details[1]').first
            check(rdet.get_attribute('open') is not None, "the record's details open with its sheet")
            page.wait_for_timeout(400)
            tl = rdet.inner_text()
            check('bodewell.com' in tl and 'needs_release' in tl and 'first_name' in tl, f"the browse step shows its outcome: {tl[:300]}")
            check(rdet.locator('img.browse-shot').count() == 1, "the last screenshot is drawn")
            shot_ok = rdet.locator('img.browse-shot').first.evaluate("i => i && i.complete && i.naturalWidth > 0")
            check(shot_ok, "the screenshot actually loads through the gated route")
            check('Jeff' in tl and 'ffejnosliw@gmail.com' in tl, "the release shows the exact values")
            check(rdet.locator('input[placeholder="Type your answer"]').count() == 0 or
                  not rdet.locator('input[placeholder="Type your answer"]').first.is_visible(),
                  "a release is answered by its buttons, not the free-text box")
            rdet.locator('button:has-text("Not these")').first.click()
            page.wait_for_timeout(1500)
            row = [x for x in storage.get_missions() if x['goal'] == 'get the dishwasher fixed'][0]
            steps = storage.get_mission_steps(row['id'])
            check(steps[-1]['kind'] == 'ask' and steps[-1]['name'] == 'handoff', f"Not these hands off: {steps[-1]}")
            page.wait_for_timeout(1200)
            if page.locator('#cc-alert-modal').is_visible():
                page.locator('#cc-alert-modal button:has-text("OK")').click()
            card = page.locator('[data-record-sheet][data-kind=mission] .situation-card:has-text("dishwasher fixed")').first
            rdet = card.locator('xpath=../following-sibling::details[1]').first
            if not rdet.get_attribute('open'):
                rdet.locator('summary').first.click()     # the lane re-rendered; open it again
                page.wait_for_timeout(400)
            tl = rdet.inner_text()
            check('finish it on your phone' in tl.lower() and rdet.locator('a[href^="https://bodewell.com"]').count() >= 1,
                  f"the hand-off shows its link: text={tl[:400]!r}")
            _open_record(page, served, 'book the dishwasher repair')
            book = page.locator('[data-record-sheet][data-kind=mission] .situation-card:has-text("book the dishwasher")').first
            check(book.locator('.sit-next button').first.inner_text().startswith('Book at'), "the submit card leads with the whole question")
            det = book.locator('xpath=../following-sibling::details[1]').first
            check(det.get_attribute('open') is not None, "the booking details open with its sheet")
            page.wait_for_timeout(500)
            tl = det.inner_text()
            check("Book at bodewell.com" in tl and 'Tue, Oct 20 8AM-12PM' in tl and 'first_name' in tl and det.locator('button:has-text("Book it")').count() == 1
                  and det.locator('button:has-text("I\'ll finish it myself")').count() == 1 and det.locator('button:has-text("Stop")').count() == 1, f"the submit ask block: {tl[:400]}")
            check(not det.locator('input[placeholder="Type your answer"]').first.is_visible(), "a submit is answered by its buttons")
            det.locator('button:has-text("Book it")').first.click(); page.wait_for_timeout(1500)
            m2 = [x for x in storage.get_missions() if x['goal'] == 'book the dishwasher repair'][0]
            steps = storage.get_mission_steps(m2['id'])
            check(any(s['name'] == 'submit_approved' for s in steps), f"Book it approved with the ask id: {[s['name'] for s in steps]}")
            if page.locator('#cc-alert-modal').is_visible():
                page.locator('#cc-alert-modal button:has-text("OK")').click()
            _open_record(page, served, 'register for the permit')
            perm = page.locator('[data-record-sheet][data-kind=mission] .situation-card:has-text("permit")').first
            check(perm.locator('.sit-next button').first.inner_text() == 'It went through', "the verify card leads with It went through")
            det = perm.locator('xpath=../following-sibling::details[1]').first
            check(det.get_attribute('open') is not None, "the verification details open with its sheet")
            page.wait_for_timeout(500)
            det.locator('input[placeholder="Confirmation number or what you saw"]').first.fill('confirmation 4242')
            det.locator('button:has-text("It went through")').first.click(); page.wait_for_timeout(1500)
            m3 = [x for x in storage.get_missions() if x['goal'] == 'register for the permit'][0]
            from services import missions as _m
            a = _m.attempts_for(m3['id'])[0]
            check(a['outcome'] == 'confirmed' and a['detail'] == 'confirmation 4242' and m3['status'] == 'running', f"It went through resolved the attempt with the detail: {a} {m3['status']}")
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_browse_page_live')
