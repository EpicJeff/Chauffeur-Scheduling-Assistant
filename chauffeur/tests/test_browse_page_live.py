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
    missions._browse = lambda **kw: {'outcome': 'captcha_failed', 'text': 'the check failed', 'learned': {}, 'stopped_at': 'https://bodewell.com/x', 'wanted_fields': [],
                                     'turns': 2, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {'first_name': 'Jeff'}}
    missions._browse_async = False


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=missions'), wait_until='networkidle')
            page.wait_for_selector('#missions .situation-card', timeout=15000)
            card = page.locator('#missions .situation-card').first
            check(card.locator('.sit-next button').first.inner_text().startswith('Share with bodewell.com'), "the card's next step is the release")
            page.locator('#missions details summary').first.click()
            page.wait_for_timeout(400)
            tl = page.locator('#missions details[open]').first.inner_text()
            check('bodewell.com' in tl and 'needs_release' in tl and 'first_name' in tl, f"the browse step shows its outcome: {tl[:300]}")
            check(page.locator('#missions details[open] img.browse-shot').count() == 1, "the last screenshot is drawn")
            shot_ok = page.evaluate("() => { const i = document.querySelector('#missions details[open] img.browse-shot'); return i && i.complete && i.naturalWidth > 0; }")
            check(shot_ok, "the screenshot actually loads through the gated route")
            check('Jeff' in tl and 'ffejnosliw@gmail.com' in tl, "the release shows the exact values")
            check(page.locator('#missions details[open] input[placeholder="Type your answer"]').count() == 0 or
                  not page.locator('#missions details[open] input[placeholder="Type your answer"]').first.is_visible(),
                  "a release is answered by its buttons, not the free-text box")
            page.locator('#missions details[open] button:has-text("Not these")').first.click()
            page.wait_for_timeout(1500)
            row = storage.get_missions()[0]
            steps = storage.get_mission_steps(row['id'])
            check(steps[-1]['kind'] == 'ask' and steps[-1]['name'] == 'handoff', f"Not these hands off: {steps[-1]}")
            page.wait_for_timeout(1200)
            if page.locator('#cc-alert-modal').is_visible():
                page.locator('#cc-alert-modal button:has-text("OK")').click()
            if not page.locator('#missions details[open]').count():
                page.locator('#missions details summary').first.click()     # the lane re-rendered; open it again
                page.wait_for_timeout(400)
            tl = page.locator('#missions details[open]').first.inner_text()
            check('finish it on your phone' in tl.lower() and page.locator('#missions details[open] a[href^="https://bodewell.com"]').count() >= 1,
                  f"the hand-off shows its link: open={page.locator('#missions details[open]').count()} text={tl[:400]!r}")
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_browse_page_live')
