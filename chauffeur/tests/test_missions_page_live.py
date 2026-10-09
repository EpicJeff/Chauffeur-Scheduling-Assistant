"""/missions on the situation card: a waiting mission leads with its question,
a finished mission with a pending proposal stays in Needs you, approving from
the transcript moves it to history, the launch form still launches."""
import datetime
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='missions_page_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

SHOTS = os.environ.get('CHF_SHOTS')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def seed():
    storage.update_settings({'llm_gemini_api_key': '', 'missions_enabled': True})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    waiting = storage.add_mission({'goal': 'Find a plumber', 'status': 'waiting_user', 'created_by': 'mom',
                                   'tier': 'flash', 'origin_kind': 'manual', 'step_count': 1})
    storage.add_mission_step(waiting, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'What budget?'}})
    done = storage.add_mission({'goal': 'Compare pool covers', 'status': 'done', 'created_by': 'mom', 'tier': 'flash',
                                'origin_kind': 'manual', 'step_count': 3, 'summary': 'Two options found',
                                'finished_at': datetime.datetime.now().timestamp()})
    storage.add_action_proposal({'id': 'p1', 'action_type': 'add_errand', 'summary': 'Add: call Ace Pools',
                                 'payload': {'title': 'Call Ace Pools'}, 'status': 'proposed', 'requires_admin': True})
    storage.add_mission_step(done, {'kind': 'proposal', 'name': 'add_errand', 'idx': 3,
                                    'result_json': {'proposal_id': 'p1', 'status': 'proposed',
                                                    'card': {'title': 'Add: call Ace Pools'}}})
    from services import chat_actions
    chat_actions._execute = lambda a, p: {'status': 'success', 'message': 'added'}


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=missions'), wait_until='networkidle')
            # /work hosts the Mind lane too (hidden tab, its own cards): every
            # locator below is scoped to the missions section.
            page.wait_for_selector('#missions .situation-card')
            now = page.locator('#missions [data-sit-group="now"] .situation-card')
            titles = now.locator('.sit-title').all_inner_texts()
            check('Find a plumber' in titles and 'Compare pool covers' in titles,
                  f"a waiting mission AND a done one with a pending proposal need you: {titles}")
            plumber = page.locator('#missions .situation-card:has-text("Find a plumber")').first
            check(plumber.locator('.sit-next button').first.inner_text() == 'What budget?',
                  "the waiting mission leads with its question")
            plumber.locator('.sit-next button').first.click()
            page.wait_for_selector('#missions details[open] input[placeholder="Type your answer"]')
            page.fill('#missions details[open] input[placeholder="Type your answer"]', 'Under 500')
            page.locator('#missions details[open] button:has-text("Send"):visible').first.click()
            page.wait_for_timeout(800)
            steps = storage.get_mission_steps([m for m in storage.get_missions() if m['goal'] == 'Find a plumber'][0]['id'])
            check(any(s.get('name') == 'user_answer' for s in steps), "the answer went through the old box")
            # Approve the pending proposal from the card; the mission moves to history.
            pool = page.locator('#missions .situation-card:has-text("Compare pool covers")').first
            pool.locator('.sit-next button').first.click()        # 'Add: call Ace Pools' (do)
            page.wait_for_timeout(1000)
            check(page.locator('#missions [data-sit-group="done"] .situation-card:has-text("Compare pool covers")').count() == 1,
                  "once its decision is made the finished mission is history")
            # The act reported its outcome in the global notice; a person taps OK.
            if page.locator('#cc-alert-modal').is_visible():
                page.locator('#cc-alert-modal button:has-text("OK")').click()
            # Launch still works (flash: the pro tier needs the paid key).
            page.fill('#missions textarea[placeholder*="What should Argyle work on"]', 'Book the dentist')
            page.locator('#missions select').first.select_option('flash')
            page.locator('#missions button:has-text("Launch")').click()
            page.wait_for_timeout(800)
            check(any(m['goal'] == 'Book the dentist' for m in storage.get_missions()), "the launch form launched")
            _shot(page, 'missions-page')
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print("test_missions_page_live OK")
