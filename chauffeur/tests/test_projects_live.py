"""Projects on the served app, in a real browser (Projects core spec §4), Task 11.

One shared component (`components/projects_page.html`) draws the admin Work
group's Projects tab, `/projects`, and the phone app's Projects tab. Markers the
test relies on (exact):
  * a project card `[data-project-id="<id>"]` (tap to open it);
  * in the open project (one-list spec §3): the goal and done-when text; each
    step a row `[data-row="step:<id>"]` whose checkbox `[data-row-box]` ticks a
    person's step and whose title `[data-row-title]` opens the step sheet
    `[data-step-sheet]`; what an Argyle step found on its row;
    `[data-step-skip="<id>"]` and `[data-step-stop="<id>"]` in a running
    (doing) Argyle step's sheet; `[data-step-hold="<id>"]` in a person's step
    sheet, which shows the suggested time and `[data-hold-confirm]` to keep it;
  * on the list page `[data-new-project]` opens the New project sheet: inputs
    named title, goal, done_when, the shared audience picker
    (`[data-create-audience] [data-audience-value]`), and `[data-create-project]`;
  * the phone app has no Projects tab: Projects is reached from More (one-list spec §5);
  * an old Programs link opens its piece sheet inside the owning project.
No browser dialogs anywhere (alert/confirm/prompt).

Run from chauffeur/:  python tests/test_projects_live.py
Screenshots go to the scratchpad when PROJECTS_SHOTS is set to a directory.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Its own throwaway data, never the checkout's data/ (the way test_pwa_adult_shell_live does it): the seed
# writes fixed ids, so a shared database collects duplicates run after run.
import atexit, shutil, tempfile  # noqa: E401
DATA = tempfile.mkdtemp(prefix='chauffeur_projects_live_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))

from services import storage


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


TOKENS = {}
IDS = {}
SHOTS = os.environ.get('PROJECTS_SHOTS')


def _seed():
    if TOKENS:          # one seed per process: every scenario serves the same throwaway data
        return
    for m in ({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'email': 'mom@example.com', 'driver_id': 'd1', 'color_code': '#287a72'},
              {'id': 'dad', 'name': 'Dad', 'role': 'parent', 'color_code': '#7a2850'},
              {'id': 'kid', 'name': 'Kate', 'role': 'child', 'stage_override': 'navigator', 'color_code': '#285a7a'},
              {'id': 'tot', 'name': 'Sam', 'role': 'child', 'stage_override': 'sprout', 'color_code': '#5a7a28'},
              {'id': 'exp', 'name': 'Ana', 'role': 'child', 'stage_override': 'explorer', 'color_code': '#7a5a28'}):
        storage.add_member(m)
    for who in ('mom', 'dad', 'kid', 'tot', 'exp'):
        TOKENS[who] = storage.create_member_token(who)
    from library_run_fixture import add_run   # a run reads its curriculum from the library
    add_run({'id': 'pr1', 'member_id': 'mom', 'title': 'Strength basics', 'state': 'active'})
    bath = storage.add_project({'id': 'prj-bath', 'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'we use it every day',
                                'owner_member_id': 'mom', 'created_by': 'mom', 'audience': 'household',
                                'pieces': [{'kind': 'program', 'id': 'pr1', 'added_by': 'mom', 'added_at': 0}],
                                'steps': [
                                    {'id': 'demo', 'order': 0, 'title': 'Demo the old tile', 'owner': 'mom', 'needs': [], 'due_date': None,
                                     'state': 'todo', 'done_by': None, 'done_at': None, 'hold': None},
                                    {'id': 'tile', 'order': 1, 'title': 'Find tile', 'owner': 'argyle', 'needs': [], 'due_date': None,
                                     'state': 'doing', 'done_by': None, 'done_at': None, 'goal': 'three tiles under $5',
                                     'mission_id': None, 'stage_id': None, 'found': {'tiles': ['Ivory matte']}, 'question': None},
                                    {'id': 'lay', 'order': 2, 'title': 'Tile the floor', 'owner': 'dad', 'needs': ['demo'],
                                     'due_date': None, 'state': 'todo', 'done_by': None, 'done_at': None, 'hold': None}]})
    bike = storage.add_project({'id': 'prj-bike', 'title': 'Learn to ride a bike', 'goal': 'ride to school', 'done_when': 'no hands on the bike',
                                'owner_member_id': 'kid', 'created_by': 'mom', 'audience': 'parents',
                                'steps': [{'id': 'prac', 'order': 0, 'title': 'Practise in the park', 'owner': 'kid', 'needs': [],
                                           'due_date': None, 'state': 'todo', 'done_by': None, 'done_at': None, 'hold': None}]})
    mine = storage.add_project({'id': 'prj-185', 'title': 'Get down to 185 lbs', 'goal': 'feel better on hikes',
                                'done_when': 'the scale says 185', 'owner_member_id': 'mom', 'created_by': 'mom',
                                'audience': 'private', 'body_goal': True})
    potty = storage.add_project({'id': 'prj-tot', 'title': 'Use the big-kid potty', 'goal': 'no more diapers', 'done_when': 'a dry week',
                                 'owner_member_id': 'tot', 'created_by': 'mom', 'audience': 'parents'})
    swim = storage.add_project({'id': 'prj-exp', 'title': 'Learn to swim', 'goal': 'swim a length', 'done_when': 'one length alone',
                                'owner_member_id': 'exp', 'created_by': 'mom', 'audience': 'parents'})
    storage.update_program('pr1', {'project_id': bath})
    IDS.update(bath=bath, bike=bike, mine=mine, tot=potty, exp=swim)


def _serve():
    from live_app import live_app
    served = live_app(_seed)
    if served is not None:
        storage.update_settings({'auth_enforce': True})
    return served


def _admin(page, served, who):
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                  {'chauffeur_admin_token': TOKENS[who], 'chauffeur_admin_token_for': who})


def _pwa(page, served, who):
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                  {'chauffeur_member_id': who, 'chauffeur_member_token': TOKENS[who], 'chauffeur_member_token_for': who,
                   'chauffeur_theme': 'dark'})


def _open_projects(page):
    """Projects lives in More on the phone (one-list spec §5); as project_sheets_fixture.open_projects."""
    page.locator('#tab-more').click()
    page.locator('#pwa-feature-list').get_by_text('Projects', exact=True).first.click()
    page.wait_for_selector('#projects-container [data-project-card], #projects-container [data-project-detail]', timeout=15000)


def _step(pid, sid):
    return next(s for s in storage.get_project(pid)['steps'] if s['id'] == sid)


def scenario_the_admin_tab():
    served = _serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            dialogs = []
            page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
            calls = []
            page.on('requestfinished', lambda r: calls.append(f"{r.method} {r.url.split('/', 3)[-1][:70]}") if '/api/projects' in r.url else None)
            page.on('requestfailed', lambda r: calls.append(f"FAILED {r.method} {r.url.split('/', 3)[-1][:70]} {r.failure}") if '/api/projects' in r.url else None)
            _admin(page, served, 'mom')
            page.goto(served.url('work?tab=projects'), wait_until='load')
            page.wait_for_selector(f'[data-project-id="{IDS["bath"]}"]', timeout=15000)
            text = page.locator('body').inner_text()
            check('Bathroom' in text and 'Learn to ride a bike' in text and 'Get down to 185 lbs' in text, "Mom's cards")
            page.locator(f'[data-project-id="{IDS["bath"]}"]').first.click()
            page.wait_for_selector('[data-row="step:demo"]', timeout=10000)
            body = page.locator('[data-project-detail]').inner_text()
            check('a new bathroom' in body and 'we use it every day' in body, "goal and done-when")
            check('Ivory matte' in page.locator('[data-row="step:tile"]').inner_text(), "what Argyle's step found, on its row")
            page.locator('[data-row="step:tile"] [data-row-title]').click()
            page.wait_for_selector('[data-step-sheet]', timeout=5000)
            check(page.locator('[data-step-skip="tile"]').count() == 1 and page.locator('[data-step-stop="tile"]').count() == 1,
                  "Skip and Stop in a running Argyle step's sheet")
            page.keyboard.press('Escape')
            page.wait_for_selector('[data-step-sheet]', state='detached', timeout=5000)
            page.locator('[data-row="step:demo"] [data-row-box]').click()
            for _ in range(40):
                if _step(IDS['bath'], 'demo')['state'] == 'done':
                    break
                page.wait_for_timeout(250)
            check(_step(IDS['bath'], 'demo')['state'] == 'done', f"the tick reached the server: {calls[-6:]}")
            page.locator('[data-row="step:lay"] [data-row-title]').click()
            page.wait_for_selector('[data-step-sheet]', timeout=5000)
            page.locator('[data-step-hold="lay"]').click()
            page.wait_for_selector('[data-hold-confirm]', timeout=10000)
            page.locator('[data-hold-confirm]').first.click()
            for _ in range(40):
                if _step(IDS['bath'], 'lay').get('hold'):
                    break
                page.wait_for_timeout(250)
            check(_step(IDS['bath'], 'lay').get('hold'), "the suggested time was kept")
            page.wait_for_function("() => (document.querySelector('[data-step-sheet]') || {innerText: ''}).innerText.includes('On the calendar')",
                                   timeout=10000)
            if SHOTS:
                Path(SHOTS).mkdir(parents=True, exist_ok=True)
                Path(SHOTS, 'projects-admin.png').write_bytes(page.screenshot(full_page=True))
            page.keyboard.press('Escape')
            page.locator('[data-project-back]').click()
            page.locator('[data-new-project]').first.click()
            page.fill('[name="title"]', 'Garage clear-out')
            page.fill('[name="goal"]', 'park the car inside')
            page.fill('[name="done_when"]', 'the car fits')
            page.locator('[data-create-audience] [data-audience-value="household"]').check()
            page.locator('[data-create-project]').first.click()
            for _ in range(40):
                if any(p['title'] == 'Garage clear-out' for p in storage.get_projects()):
                    break
                page.wait_for_timeout(250)
            check(any(p['title'] == 'Garage clear-out' and p['created_by'] == 'mom' and p['audience'] == 'household'
                      for p in storage.get_projects()), "a project created by hand, for the household as picked")
            check(not dialogs, f"no browser dialogs: {dialogs}")
            page.goto(served.url('programs?id=pr1'), wait_until='load')
            page.wait_for_selector('[data-record-sheet][data-open="true"]', timeout=15000)
            check('Bathroom' in page.locator('[data-project-detail]').inner_text(),
                  "the program opens in its owning project")
            check('Strength basics' in page.locator('[data-record-sheet]').inner_text(),
                  "the old program link opens that program's sheet")
    finally:
        served.stop()


def scenario_the_phone_tab_for_a_child_and_a_parent():
    served = _serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            dialogs = []
            page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
            _pwa(page, served, 'kid')
            page.goto(served.url('app'), wait_until='load')
            page.wait_for_selector('#tab-more', state='visible', timeout=15000)
            check(page.locator('#tab-projects').count() == 0, "no Projects tab")
            _open_projects(page)
            page.wait_for_selector(f'[data-project-id="{IDS["bike"]}"]', timeout=15000)
            text = page.locator('body').inner_text()
            check('Learn to ride a bike' in text and 'Bathroom' in text and '185' not in text,
                  "Kate sees her project and the household one, never Mom's private one")
            page.locator(f'[data-project-id="{IDS["bike"]}"]').first.click()
            page.wait_for_selector('[data-row="step:prac"] [data-row-box]', timeout=10000)
            page.locator('[data-row="step:prac"] [data-row-box]').click()
            for _ in range(40):
                if _step(IDS['bike'], 'prac')['state'] == 'done':
                    break
                page.wait_for_timeout(250)
            check(_step(IDS['bike'], 'prac')['state'] == 'done' and _step(IDS['bike'], 'prac')['done_by'] == 'kid',
                  "Kate ticks her own step")
            if SHOTS:
                Path(SHOTS, 'projects-pwa-kid.png').write_bytes(page.screenshot(full_page=True))
            _pwa(page, served, 'dad')
            page.goto(served.url('app'), wait_until='load')
            page.wait_for_selector('#tab-more', state='visible', timeout=15000)
            check(page.locator('#tab-projects').count() == 0, "no Projects tab")
            _open_projects(page)
            page.wait_for_selector(f'[data-project-id="{IDS["bike"]}"]', timeout=15000)
            text = page.locator('body').inner_text()
            check('Learn to ride a bike' in text and '185' not in text, "Dad sees Kate's project, not Mom's private one")
            check(not dialogs, f"no browser dialogs: {dialogs}")
    finally:
        served.stop()


def scenario_younger_children_reach_their_projects_without_a_tab():
    """A sprout's and an explorer's tab bars stay as approved; their projects live in My things and More."""
    served = _serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            _pwa(page, served, 'tot')
            page.goto(served.url('app'), wait_until='load')
            page.wait_for_selector('#pwa-tab-bar', timeout=15000)
            check(page.locator('#tab-projects').count() == 0, "a sprout has no Projects tab")
            page.locator('#pwa-tab-bar > button:visible', has_text='My things').first.click()
            page.wait_for_selector(f'[data-project-id="{IDS["tot"]}"]', timeout=15000)
            check('Use the big-kid potty' in page.locator('body').inner_text(), "Sam finds his project in My things")
            _pwa(page, served, 'exp')
            page.goto(served.url('app'), wait_until='load')
            page.wait_for_selector('#tab-more', timeout=15000)
            check(page.locator('#tab-projects').count() == 0, "an explorer has no Projects tab")
            page.locator('#tab-more').click()
            page.locator('text=Projects').first.click()
            page.wait_for_selector(f'[data-project-id="{IDS["exp"]}"]', timeout=15000)
            check('Learn to swim' in page.locator('body').inner_text(), "Ana finds hers through More")
    finally:
        served.stop()


SCENARIOS = [scenario_the_admin_tab, scenario_the_phone_tab_for_a_child_and_a_parent,
             scenario_younger_children_reach_their_projects_without_a_tab]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print("  ok  %s" % fn.__name__)
    print("\n%d/%d projects live scenarios passed" % (len(SCENARIOS), len(SCENARIOS)))
