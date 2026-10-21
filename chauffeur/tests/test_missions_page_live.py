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
    chat_actions._execute = lambda a, p, approver=None: {'status': 'success', 'message': 'added'}


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
            # Adding a piece requires a person who can edit its project; the
            # old unbound launch form also accepted an unattributed admin.
            page.goto(served.url('api/account/setup'))
            page.evaluate("""token => {
                localStorage.setItem('chauffeur_admin_token', token);
                localStorage.setItem('chauffeur_admin_token_for', 'mom');
            }""", storage.create_member_token('mom'))
            _open_record(page, served, 'Find a plumber')
            # The record sheet isolates the requested mission.
            page.wait_for_selector('[data-record-sheet][data-kind=mission] .situation-card')
            now = page.locator('[data-record-sheet][data-kind=mission] [data-sit-group="now"] .situation-card')
            titles = now.locator('.sit-title').all_inner_texts()
            check('Find a plumber' in titles,
                  f"a waiting mission needs you: {titles}")
            plumber = page.locator('[data-record-sheet][data-kind=mission] .situation-card:has-text("Find a plumber")').first
            check(plumber.locator('.sit-next button').first.inner_text() == 'What budget?',
                  "the waiting mission leads with its question")
            plumber.locator('.sit-next button').first.click()
            page.wait_for_selector('[data-record-sheet][data-kind=mission] details[open] input[placeholder="Type your answer"]')
            page.fill('[data-record-sheet][data-kind=mission] details[open] input[placeholder="Type your answer"]', 'Under 500')
            page.locator('[data-record-sheet][data-kind=mission] details[open] button:has-text("Send"):visible').first.click()
            page.wait_for_timeout(800)
            steps = storage.get_mission_steps([m for m in storage.get_missions() if m['goal'] == 'Find a plumber'][0]['id'])
            check(any(s.get('name') == 'user_answer' for s in steps), "the answer went through the old box")
            # Approve the pending proposal from the card; the mission moves to history.
            _open_record(page, served, 'Compare pool covers')
            check(page.locator('[data-record-sheet][data-kind=mission] [data-sit-group="now"] .sit-title').inner_text() == 'Compare pool covers',
                  "a done mission with a pending proposal still needs you")
            pool = page.locator('[data-record-sheet][data-kind=mission] .situation-card:has-text("Compare pool covers")').first
            pool.locator('.sit-next button').first.click()        # 'Add: call Ace Pools' (do)
            page.wait_for_timeout(1000)
            check(page.locator('[data-record-sheet][data-kind=mission] [data-sit-group="done"] .situation-card:has-text("Compare pool covers")').count() == 1,
                  "once its decision is made the finished mission is history")
            # The act reported its outcome in the global notice; a person taps OK.
            if page.locator('#cc-alert-modal').is_visible():
                page.locator('#cc-alert-modal button:has-text("OK")').click()
            # Launch still works (flash: the pro tier needs the paid key).
            from services import missions, projects
            project_id = storage.get_mission(next(m['id'] for m in storage.get_missions()
                                                 if m['goal'] == 'Find a plumber')).get('project_id')
            if not project_id:
                mid = next(m['id'] for m in storage.get_missions() if m['goal'] == 'Find a plumber')
                project_id = projects.adopt('mission', mid, storage.get_member('mom'))
            page.goto(served.url('projects?id=' + project_id), wait_until='networkidle')
            actor_id = page.evaluate('() => window.chfPersonId()')
            check(actor_id == 'mom' and projects.can_act(storage.get_project(project_id), storage.get_member(actor_id)),
                  f"the signed-in parent can add to this project: {actor_id}")
            settings = storage.get_settings()
            counts = storage.get_app_state('mission_calls:' + datetime.date.today().isoformat()) or {}
            cap = int(settings.get('mission_cap_launch', missions.CAPS_DEFAULT['launch']))
            check(settings.get('missions_enabled') and int(counts.get('launch', 0)) < cap,
                  f"the fixture permits a launch: enabled={settings.get('missions_enabled')}, launches={counts.get('launch', 0)}, cap={cap}")
            page.locator('[data-project-add]').click()   # one-list + Add: Ask Argyle is the mission form
            page.locator('[data-prompt-choice]', has_text='Ask Argyle').first.click()
            form = page.locator('[data-piece-form="mission"]')
            form.locator('textarea[name="goal"]').fill('Book the dentist')
            form.locator('select[name="tier"]').select_option('flash')
            with page.expect_response(lambda r: r.request.method == 'POST' and
                                      r.url == served.url('api/missions/launch'), timeout=15000) as launched:
                form.locator('[data-piece-create]').click()
            response = launched.value
            body = response.text()
            check(response.status == 200, f"the launch POST succeeds: {response.status} {body}")
            result = response.json()
            check(result.get('status') == 'launched' and result.get('mission_id'),
                  f"the launch POST returns a mission: {response.status} {body}")
            check(any(m['goal'] == 'Book the dentist' for m in storage.get_missions()), "the launch form launched")
            mission = storage.get_mission(result['mission_id'])
            check(mission and mission['goal'] == 'Book the dentist' and mission['tier'] == 'flash'
                  and mission['created_by'] == actor_id and mission['project_id'] == project_id,
                  f"the response's mission belongs to the chosen project and parent: {mission}")
            _shot(page, 'missions-page')
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print("test_missions_page_live OK")
