"""One seed and the sign-in helpers for the slice 2 live tests (front door spec §2-§3).

Its own throwaway data directory, set before storage is imported, the way
tests/test_projects_live.py does it."""
import atexit
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = tempfile.mkdtemp(prefix='chauffeur_sheets_live_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))

from services import storage  # noqa: E402

TOKENS, IDS = {}, {}
SHOTS = os.environ.get('PROJECTS_SHOTS')
_PROGRAM = {'shape': {'sessions_per_week': 3, 'minutes': 20, 'preferred_days': []}, 'phases': [],
            'source': {'origin': 'none', 'reason': 'test'},
            'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    if TOKENS:
        return
    from services import projects, threads
    for m in ({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'email': 'mom@example.com', 'color_code': '#287a72'},
              {'id': 'dad', 'name': 'Dad', 'role': 'parent', 'color_code': '#7a2850'},
              {'id': 'aunt', 'name': 'Aunt Jo', 'role': 'adult', 'color_code': '#285a7a'},
              {'id': 'kid', 'name': 'Kate', 'role': 'child', 'stage_override': 'navigator', 'color_code': '#5a7a28'}):
        storage.add_member(m)
    for who in ('mom', 'dad', 'aunt', 'kid'):
        TOKENS[who] = storage.create_member_token(who)
    storage.add_project({'id': 'prj-bath', 'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'we use it every day',
                         'owner_member_id': 'mom', 'created_by': 'mom', 'audience': 'household', 'pieces': [], 'steps': []})
    IDS['bath'] = 'prj-bath'
    IDS['thread'] = threads.create(title='Tiler', owner_member_id='mom', goal='tile by May', kind='vendor',
                                   counterparty_name='Ace Tile', next_action='Call Ace back', created_by='mom',
                                   project_id='prj-bath')
    IDS['closed'] = threads.create(title='Old permit', owner_member_id='mom', goal='permit', created_by='mom',
                                   project_id='prj-bath')
    storage.update_thread(IDS['closed'], {'state': 'done'})
    # Keep the sheet answerable across scenarios: the live push loop must not
    # step this fixture into blocked after repeated missing-key errors.
    IDS['mission'] = storage.add_mission({'goal': 'Find three tilers', 'created_by': 'mom', 'tier': 'mission', 'status': 'waiting_user'})
    storage.add_mission_step(IDS['mission'], {'kind': 'ask', 'name': 'question',
                                            'result_json': {'question': 'Which day suits the tiler?'}})
    projects.adopt('mission', IDS['mission'], None, project_id='prj-bath')
    for pid, title, state in (('pr-prop', 'Tiling basics', 'proposed'), ('pr-live', 'Strength basics', 'active')):
        # A run reads its curriculum from the library since the program library split.
        from library_run_fixture import add_run
        add_run({'id': pid, 'member_id': 'mom', 'title': title, 'state': state, **_PROGRAM})
        projects.adopt('program', pid, None, project_id='prj-bath')
    storage.add_project({'id': 'prj-gift', 'title': 'Surprise party', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom',
                         'created_by': 'mom', 'audience': 'private', 'pieces': [], 'steps': []})
    IDS['keeper'] = storage.add_mission({'goal': 'Book the venue', 'created_by': 'aunt', 'tier': 'mission', 'status': 'waiting_user'})
    storage.add_mission_step(IDS['keeper'], {'kind': 'ask', 'name': 'question',
                                           'result_json': {'question': 'Which day suits the venue?'}})
    projects.adopt('mission', IDS['keeper'], None, project_id='prj-gift')
    storage.add_project({'id': 'prj-bike', 'title': 'Ride a bike', 'goal': 'ride to school', 'done_when': 'no hands',
                         'owner_member_id': 'kid', 'created_by': 'kid', 'audience': 'parents', 'pieces': [], 'steps': []})
    storage.set_app_state('projects_adopted_rev', 1)   # the startup migration must not re-wrap the fixture


def serve():
    from live_app import live_app
    served = live_app(seed)
    if served is not None:
        storage.update_settings({'auth_enforce': True, 'missions_enabled': True, 'programs_enabled': True})
    return served


def admin(page, served, who):
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                  {'chauffeur_admin_token': TOKENS[who], 'chauffeur_admin_token_for': who})


def pwa(page, served, who):
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                  {'chauffeur_member_id': who, 'chauffeur_member_token': TOKENS[who], 'chauffeur_member_token_for': who,
                   'chauffeur_theme': 'dark'})


def shot(page, name):
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, name + '.png'), full_page=True)
