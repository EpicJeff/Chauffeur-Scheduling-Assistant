"""Program library, the flows (spec 2026-10-19-program-library-design.md rev 3, section 3; plan Task 1 Step 3).

Pinned here:

  * the picker: POST /api/programs {project_id, library_id} starts a `proposed` run whose shape
    defaults come from the row's made_for, spending no research;
  * make a new one: POST /api/programs {project_id, title, age_band, minutes, sessions_per_week,
    assumes, starting_point} curates a library row from the PUBLIC profile (`age_band` defaults
    from the birthdate, else `any`, never from a pinned stage) and starts a run that alone holds
    the starting point; the payload carries "Everyone in the household will see this program as:
    {title}";
  * Argyle: the planner's propose_program row, with a library match, returns
    {'status': 'waiting_choice', 'choice_id', 'options'}; the row is recorded `waiting_choice`, its
    dependents wait, the stage stays open, reconcile keeps it waiting, a pause/resume and a
    resume never re-run it; the choice is a mission ask card ("There's a {title} program in the
    library, made for {made_for}. Use it for {name}, or make a new one?") with Use / Make new /
    Not now, answered through the card's own situation option, whose payload carries `option` in
    ('use', 'make_new', 'not_now'); Use and Make new create exactly one run even when answered
    twice, then the stage continues; Not now fails the row with "No program for now";
  * voice: start_project(spoken=True) persists `interaction: 'voice'` on the planning mission; under
    it a single library match is used at once and the mission's notice says so later; several
    matches or none curate a new row;
  * the run's legacy /edit: a retitle is refused ("The name belongs to the library program; rename
    the project instead."), a shape edit writes the run, Look again makes a NEW library row and
    rebinds the run to it;
  * deleting a project or a run never touches the library row; a body-goal title is refused at
    the library's own door.

Review Focus 5: scenario_waiting_choice_survives_restart.

Run from chauffeur/:  python tests/test_library_flows.py   (HA_BASE_URL unset)
"""
import importlib
import json
import traceback
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)
from test_planned_missions import _fresh as _fresh_planned, _plan_of, _interviewed
from test_mission_subject import _plan, _step, _mission
from test_subjects import MOM, AUNT
from services import storage, missions, situations, projects, planned, programs_curate, web, threads
import main

VISIBLE = "Everyone in the household will see this program as: Learn piano"
RETITLE = "The name belongs to the library program; rename the project instead."
MATCH_HEAD = "There's a Learn piano program in the library, made for "
MATCH_TAIL = ". Use it for Kate, or make a new one?"
NOTICE = "I started Kate on Learn piano from the library"
SPOKEN = "I'm setting that up"
NOT_NOW = "No program for now"
SECRET = 'SECRET-START: shy about playing for anyone'
CURATED = {'phases': [{'name': 'Foundations', 'weeks': 4, 'what': 'The keys', 'milestone': 'Play a C major scale',
                       'units': [{'n': 1, 'title': 'Middle C', 'sessions': 2}, {'n': 2, 'title': 'Five fingers', 'sessions': 1}],
                       'rotation': [{'label': 'Session A', 'steps': ['Scales']}, {'label': 'Session B', 'steps': ['A tune']}]},
                      {'name': 'Songs', 'weeks': 3, 'what': 'A tune', 'milestone': 'Play Ode to Joy',
                       'steps': ['Play it through']}],
           'source': {'origin': 'cited', 'plan_name': 'Faber', 'url': 'https://example.test/faber', 'facts': [], 'reason': ''}}
STAGES = [{'id': 's1', 'kind': 'build', 'title': 'The program', 'why': 'a weekly plan', 'makes': ["Kate's piano program"]}]
ROWS = [{'id': 'r1', 'tool': 'propose_program', 'summary': "Propose Kate's piano program",
         'args': {'title': 'Learn piano', 'for_member_name': 'Kate', 'sessions_per_week': 3, 'minutes': 20,
                  'starting_point': SECRET}},
        {'id': 'r2', 'tool': 'create_thread', 'needs': ['r1'], 'summary': 'A thread for the books',
         'args': {'title': 'Piano books for Kate', 'kind': 'project'}}]
POSTS = []
REAL_POST = missions._post        # kept before any scenario stubs it: the voice notice path is real


def _svc():
    """services.library, imported per call: until Task 2 lands each scenario is red on its own."""
    return importlib.import_module('services.library')


def _fresh():
    storage.add_library_program               # the library's storage door: red here until Task 2
    _fresh_planned(step_cap=200)
    table = getattr(storage, 'library_programs_table', None)
    if table is not None:
        table.truncate()
    for name in ('projects_table', 'program_lessons_table', 'deletions_table', 'protected_commitments_table'):
        getattr(storage, name).truncate()
    POSTS.clear()
    missions._post = lambda dm, argyle, body, card=None: POSTS.append({'body': body, 'card': card}) or {'id': f'm{len(POSTS)}'}
    web.research = lambda question, read_pages=None, api_key=None: {'status': 'success', 'answer': 'x', 'facts': [], 'sources': []}
    threads.draft_message = lambda thread_id, intent=None, **k: {'status': 'ok', 'subject': 's', 'body': 'b'}
    programs_curate.curate = lambda *a, **k: json.loads(json.dumps(CURATED))


def _library(title='Learn piano', created_by='aunt', minutes=20, sessions_per_week=3, age_band='explorer'):
    """A library row in the new shape, straight into storage (red until Task 2)."""
    phase, lessons = uuid.uuid4().hex, [uuid.uuid4().hex, uuid.uuid4().hex]
    return storage.add_library_program({
        'title': title, 'created_by': created_by, 'archived': False,
        'made_for': {'age_band': age_band, 'minutes': minutes, 'sessions_per_week': sessions_per_week, 'assumes': 'complete beginner'},
        'source': {'origin': 'cited', 'plan_name': 'Faber', 'url': 'https://example.test/faber', 'facts': [], 'reason': ''},
        'phases': [{'id': phase, 'name': 'Foundations', 'weeks': 4, 'what': 'The keys', 'milestone': 'Play a C major scale',
                    'steps': [], 'progression': '', 'rotation': []}],
        'lessons': [{'id': lessons[0], 'phase_id': phase, 'title': 'Middle C', 'sessions': 2, 'steps': ['Find it']},
                    {'id': lessons[1], 'phase_id': phase, 'title': 'Five fingers', 'sessions': 1, 'steps': ['Up and down']}]})


def _project(owner='kid', audience='parents', title=None):
    res = projects.create({'title': title or f'Piano {uuid.uuid4().hex[:6]}', 'goal': 'g', 'done_when': 'd',
                           'owner_member_id': owner, 'audience': audience}, dict(MOM))
    check(res['status'] == 'success', f'project: {res}')
    return res['project']


def _http(member_id, method, path, raise_errors=True, **kwargs):
    headers = {'X-Member-Token': storage.create_member_token(member_id)} if member_id else {}
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        return TestClient(main.app, raise_server_exceptions=raise_errors).request(method, path, headers=headers, **kwargs)


def _library_rows():
    """Every library row; archived ones are counted by the callers that care."""
    return [r for r in storage.get_library_programs() if not r.get('archived')]


def _runs(library_id=None):
    rows = [r for r in storage.get_programs(include_finished=True) if r.get('library_id')]
    return [r for r in rows if library_id is None or r['library_id'] == library_id]


def _ok(res):
    return (res or {}).get('status') in ('success', 'ok')


# --- the hand path --------------------------------------------------------------------------

def scenario_the_picker_starts_a_run_with_the_effective_shape():
    _fresh()
    lid = _library(minutes=25, sessions_per_week=2)
    project = _project('kid')
    before = len(_library_rows())
    with patch('services.programs_curate.curate', side_effect=AssertionError('the picker spends no research')):
        r = _http('mom', 'POST', '/api/programs', json={'project_id': project['id'], 'library_id': lid, 'for_member_id': 'kid'})
    check(r.status_code == 200 and r.json().get('status') == 'success', f'picked: {r.status_code} {r.text[:300]}')
    run = storage.get_program(r.json()['id'])
    check(run['library_id'] == lid and run['state'] == 'proposed' and run['member_id'] == 'kid'
          and run['project_id'] == project['id'], f'a proposed run in this project: {run}')
    check(run['shape']['minutes'] == 25 and run['shape']['sessions_per_week'] == 2, f'defaults from made_for: {run["shape"]}')
    check(len(_library_rows()) == before, 'picking makes no library row')


def scenario_make_a_new_one_publishes_the_profile_and_keeps_the_starting_point():
    _fresh()
    storage.update_member('kid', {'birthdate': '2017-03-01', 'stage_override': 'copilot'})
    project = _project('kid')
    calls = []

    def curate(*a, **k):
        calls.append(repr((a, k)))
        return json.loads(json.dumps(CURATED))
    body = {'project_id': project['id'], 'for_member_id': 'kid', 'title': 'Learn piano', 'minutes': 20,
            'sessions_per_week': 3, 'assumes': 'complete beginner', 'starting_point': SECRET}
    with patch('services.programs_curate.curate', side_effect=curate):
        r = _http('mom', 'POST', '/api/programs', json=body)
    check(r.status_code == 200 and r.json().get('status') == 'success', f'made: {r.status_code} {r.text[:300]}')
    check(VISIBLE in r.text, f'the payload says what the household will see: {r.text[:300]}')
    run = storage.get_program(r.json()['id'])
    row = storage.get_library_program(run['library_id'])
    check(run['starting_point'] == SECRET and SECRET not in json.dumps(row), 'the starting point stays on the run')
    check(calls and not any(SECRET in c for c in calls), f'curated from the public profile, never the starting point: {calls}')
    check(row['title'] == 'Learn piano' and row['created_by'] == 'mom', f'the library row: {row}')
    check(row['made_for'] == {'age_band': 'explorer', 'minutes': 20, 'sessions_per_week': 3, 'assumes': 'complete beginner'},
          f'age band from the birthdate, never the pinned stage: {row["made_for"]}')
    units = sum(len(p.get('units') or []) for p in CURATED['phases'])
    check(len(row['lessons']) == units + 1, f'one lesson per unit, and one for the phase with only steps: {row["lessons"]}')
    variants = [v['label'] for v in row['lessons'][0].get('variants') or []]
    check(variants == ['Session A', 'Session B'], f'a rotation becomes the lesson variants: {row["lessons"][0]}')
    storage.update_member('kid', {'birthdate': None})
    with patch('services.programs_curate.curate', side_effect=curate):
        r = _http('mom', 'POST', '/api/programs', json=dict(body, project_id=_project('kid')['id']))
    row = storage.get_library_program(storage.get_program(r.json()['id'])['library_id'])
    check(row['made_for']['age_band'] == 'any', f'no birthdate on file: any: {row["made_for"]}')
    with patch('services.programs_curate.curate', side_effect=curate):
        r = _http('mom', 'POST', '/api/programs', json=dict(body, project_id=_project('kid')['id'], age_band='navigator'))
    row = storage.get_library_program(storage.get_program(r.json()['id'])['library_id'])
    check(row['made_for']['age_band'] == 'navigator', 'an age band the person chose is kept')


def scenario_a_body_goal_title_is_refused_at_the_library_door():
    _fresh()
    refusal = programs_curate.screen_aim('lose 15 pounds')['message']
    before = len(_library_rows())
    res = _svc().create({'title': 'lose 15 pounds', 'age_band': 'any', 'minutes': 20, 'sessions_per_week': 3,
                         'assumes': ''}, dict(MOM))
    check(not _ok(res) and res.get('message') == refusal, f'the service refuses in the screen\'s words: {res}')
    r = _http('mom', 'POST', '/api/library', json={'title': 'lose 15 pounds', 'age_band': 'any', 'minutes': 20,
                                                    'sessions_per_week': 3, 'assumes': ''})
    check(r.status_code != 200 or not _ok(r.json()), f'and so does the route: {r.status_code} {r.text[:200]}')
    check(len(_library_rows()) == before, 'nothing was made')
    lid = _library()
    res = _svc().update(lid, {'title': 'Lose 15 pounds by summer'}, dict(AUNT))
    check(not _ok(res) and storage.get_library_program(lid)['title'] == 'Learn piano', f'nor renamed into one: {res}')


def scenario_the_legacy_edit_route():
    _fresh()
    lid = _library()
    project = _project('kid')
    r = _http('mom', 'POST', '/api/programs', json={'project_id': project['id'], 'library_id': lid, 'for_member_id': 'kid'})
    rid = r.json()['id']
    r = _http('mom', 'POST', f'/api/programs/{rid}/edit', json={'title': 'Piano for Kate'})
    check(RETITLE in r.text and storage.get_library_program(lid)['title'] == 'Learn piano',
          f'a retitle is refused, the name stays the library\'s: {r.text[:200]}')
    r = _http('mom', 'POST', f'/api/programs/{rid}/edit', json={'minutes': 25, 'sessions_per_week': 2})
    shape = storage.get_program(rid)['shape']
    check(r.status_code == 200 and shape['minutes'] == 25 and shape['sessions_per_week'] == 2, f'the shape is the run\'s: {shape}')
    made_for = storage.get_library_program(lid)['made_for']
    check(made_for['minutes'] == 20 and made_for['sessions_per_week'] == 3, f'the library defaults stay: {made_for}')
    first = storage.get_library_program(lid)['lessons'][0]['id']
    storage.upsert_program_lesson(rid, {'lesson_id': first, 'variant_label': ''}, {'scenes': [{'type': 'say', 'text': 'Old.'}]})
    before = len(_library_rows())
    r = _http('mom', 'POST', f'/api/programs/{rid}/edit', json={'recurate': True})
    run = storage.get_program(rid)
    check(r.status_code == 200 and len(_library_rows()) == before + 1 and run['library_id'] not in (lid, None),
          f'Look again makes a new library program and rebinds: {r.text[:200]}')
    check(storage.get_library_program(lid) is not None, 'the old program stays in the library')
    new = storage.get_library_program(run['library_id'])
    check((run.get('progress') or {}).get('current') == new['lessons'][0]['id'], 'progress starts over')
    check(storage.get_program_lesson(rid, {'lesson_id': first, 'variant_label': ''}) is None, 'and its scripts go')


def scenario_deleting_a_project_or_a_run_leaves_the_library_row():
    _fresh()
    from services import deletion
    lid = _library()
    project = _project('kid')
    r = _http('mom', 'POST', '/api/programs', json={'project_id': project['id'], 'library_id': lid, 'for_member_id': 'kid'})
    rid = r.json()['id']
    preview = deletion.preview('project', project['id'], dict(MOM))
    check(preview['status'] == 'ok', f'preview: {preview}')
    item = next((i for i in preview['items'] if i['kind'] == 'program'), None)
    check(item and 'Learn piano' in item['title'] and 'Kate' in item['title'],
          f"the confirm names the run by its program and person: {preview['items']}")
    check(deletion.start('project', project['id'], dict(MOM), preview['token'])['status'] == 'ok', 'started')
    for _ in range(5):
        deletion.maintain()
    check(storage.get_program(rid) is None and storage.get_project(project['id']) is None, 'the project and its run are gone')
    check(storage.get_library_program(lid) is not None, 'the library program stays')
    other = _project('kid')
    r = _http('mom', 'POST', '/api/programs', json={'project_id': other['id'], 'library_id': lid, 'for_member_id': 'kid'})
    rid = r.json()['id']
    preview = deletion.preview('program', rid, dict(MOM))
    check(deletion.start('program', rid, dict(MOM), preview['token'])['status'] == 'ok', 'a run deleted on its own')
    for _ in range(5):
        deletion.maintain()
    check(storage.get_program(rid) is None and storage.get_library_program(lid) is not None, 'and the program stays')


# --- Argyle: the waiting choice -------------------------------------------------------------

def _stage(mid, sid='s1'):
    return next(s for s in _plan_of(mid)['stages'] if s['id'] == sid)


def _row(mid, rid):
    return next(r for r in _stage(mid)['rows'] if r['id'] == rid)


def _staged(interaction=None):
    """A planning mission in Mom's project whose build stage proposes Kate's program, approved."""
    project = _project('mom', audience='private', title='Music at home')
    fields = {'project_id': project['id']}
    if interaction:
        fields['interaction'] = interaction
    mid = _interviewed(mid=_mission(created_by='mom', **fields), template=None)
    planned.answer_plan(mid, {'budget': 40}, dict(MOM))
    _plan({'action': 'plan', 'stages': STAGES})
    _step(mid)
    rev = _plan_of(mid)['rev']
    res = situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f'plan approved: {res}')
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': ROWS})
    _step(mid)
    st = _stage(mid)
    res = situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s1:{st['snapshot']}:approve", payload={},
                         actor=dict(MOM))
    check(res['status'] == 'success', f'stage approved: {res}')
    return mid, project


def _made_for_phrase(minutes=20):
    """The fixture profile (explorer, 20 minutes) said as the card says it: the explorer stage's
    ages from the household's cutoffs, then the session length."""
    from services import stages
    cut = stages.cutoffs()
    return f"ages {cut[0]}–{cut[1] - 1} with {minutes}-minute sessions"


def _match_card():
    return (f"There's a Learn piano program in the library, made for {_made_for_phrase()}. "
            f"Use it for Kate, or make a new one?")


def _choice(mid):
    card = missions.ask_card(storage.get_mission(mid))
    check(card and card.get('question') == _match_card(), f'the choice card, word for word: {card}')
    labels = [o.get('label') for o in card['options']]
    check(all(label in labels for label in ('Use', 'Make new', 'Not now')), f'three buttons: {labels}')
    return {o['payload']['option']: o for o in card['options'] if (o.get('payload') or {}).get('option')}


def _act(mid, opt, raise_errors=True):
    """A card button, through the HTTP route the phone and the admin page post to."""
    body = {'verb': opt['verb'], 'option_id': opt['id'], 'payload': opt['payload']}
    return _http('mom', 'POST', f'/api/situations/mission/{mid}/act', json=body, raise_errors=raise_errors)


def _answer(mid, option, opts=None):
    return _act(mid, (opts or _choice(mid))[option])


def _choice_id(mid):
    return (_row(mid, 'r1').get('result') or {}).get('choice_id')


def _bound(mid, choice_id, run_id):
    """Whether the persisted mission (row or steps) binds this choice to this run."""
    def walk(value):
        if isinstance(value, dict):
            if value.get('run_id') == run_id and choice_id in json.dumps(value):
                return True
            return any(walk(v) for v in value.values())
        if isinstance(value, list):
            return any(walk(v) for v in value)
        return False
    return walk(storage.get_mission(mid)) or walk(storage.get_mission_steps(mid))


def _waiting_checks(mid, choice_id=None):
    row = _row(mid, 'r1')
    check(row['state'] == 'waiting_choice' and (row.get('result') or {}).get('status') == 'waiting_choice'
          and (row.get('result') or {}).get('choice_id'), f'the row waits on a durable choice: {row}')
    if choice_id is not None:
        check(row['result']['choice_id'] == choice_id, f'the same choice, never a new one: {row}')
    check(_row(mid, 'r2')['state'] not in ('skipped', 'done', 'failed', 'running'), f"its dependent waits: {_row(mid, 'r2')}")
    check(_stage(mid)['state'] not in ('done', 'skipped', 'uncertain', 'partial'), f"the stage stays open: {_stage(mid)['state']}")
    check(not _runs(), 'no run until the person chooses')


def scenario_the_tool_returns_a_waiting_choice_on_a_match():
    _fresh()
    from services import agent_tools_v2 as tools
    _library()
    project = _project('mom', audience='private', title='Music at home')
    res = tools.propose_program(title='Learn piano', for_member_name='Kate', sessions_per_week=3, minutes=20,
                                starting_point=SECRET, acting_member=dict(MOM), project_id=project['id'])
    options = [o if isinstance(o, str) else (o.get('option') or o.get('id')) for o in res.get('options') or []]
    check(res.get('status') == 'waiting_choice' and res.get('choice_id') and options == ['use', 'make_new'],
          f"a match returns the choice, its id and its options: {res}")
    check(not _runs() and len(_library_rows()) == 1, 'and creates nothing yet')


def scenario_a_library_match_waits_for_a_choice():
    _fresh()
    lid = _library()
    mid, _ = _staged()
    _waiting_checks(mid)
    choice = _choice_id(mid)
    opts = _choice(mid)
    check(set(opts) == {'use', 'make_new', 'not_now'}, f'the options name their choice: {opts}')
    r = _answer(mid, 'use', opts)
    check(r.status_code == 200, f'Use, through the route: {r.status_code} {r.text[:200]}')
    runs = _runs()
    check(len(runs) == 1 and runs[0]['library_id'] == lid and runs[0]['member_id'] == 'kid'
          and runs[0]['starting_point'] == SECRET, f'one run of the library program for Kate: {runs}')
    row = _row(mid, 'r1')
    check(row['state'] == 'done' and (row.get('result') or {}).get('created') == [{'kind': 'program', 'id': runs[0]['id']}],
          f'the row is done and names the run: {row}')
    check(_bound(mid, choice, runs[0]['id']), 'the choice is durably bound to the run it made')
    check(_row(mid, 'r2')['state'] == 'done', f"and the stage carried on: {_row(mid, 'r2')}")
    _answer(mid, 'use', opts)
    check(len(_runs()) == 1 and _row(mid, 'r1') == row, 'a repeated answer creates nothing and changes nothing')


def scenario_make_new_curates_and_not_now_fails_the_row():
    _fresh()
    lid = _library()
    mid, _ = _staged()
    choice = _choice_id(mid)
    opts = _choice(mid)
    before = len(_library_rows())
    r = _answer(mid, 'make_new', opts)
    check(r.status_code == 200, f'Make new: {r.status_code} {r.text[:200]}')
    runs = _runs()
    check(len(_library_rows()) == before + 1 and len(runs) == 1 and runs[0]['library_id'] != lid,
          f'a new library program, and a run of it: {runs}')
    check(_bound(mid, choice, runs[0]['id']), 'the choice is bound to the run')
    check(_row(mid, 'r1')['state'] == 'done' and _row(mid, 'r2')['state'] == 'done', 'the stage carried on')
    _answer(mid, 'make_new', opts)
    check(len(_library_rows()) == before + 1 and len(_runs()) == 1, 'a repeated Make new makes nothing more')
    _fresh()
    _library()
    mid, _ = _staged()
    r = _answer(mid, 'not_now')
    check(r.status_code == 200, f'Not now: {r.status_code} {r.text[:200]}')
    row = _row(mid, 'r1')
    check(row['state'] == 'failed' and (row.get('result') or {}).get('message') == NOT_NOW, f'Not now fails the row: {row}')
    check(not _runs() and _row(mid, 'r2')['state'] == 'skipped', f"no run, and the dependent is skipped: {_row(mid, 'r2')}")
    check(_stage(mid)['state'] not in ('running', 'proposed'), f"the stage goes on without it: {_stage(mid)['state']}")


def scenario_a_failed_answer_leaves_no_half_state():
    _fresh()
    from services import programs
    lid = _library()
    mid, _ = _staged()
    choice = _choice_id(mid)
    opts = _choice(mid)
    real = programs.create_row
    made = []

    def crash(*a, **k):
        made.append(real(*a, **k))
        raise RuntimeError('the power went out after the run was written')
    with patch.object(programs, 'create_row', side_effect=crash):
        r = _act(mid, opts['use'], raise_errors=False)
    check(made, 'the failure was injected after the run was created')
    check(r.status_code != 200 or not _ok(r.json()), f'the answer did not succeed: {r.status_code} {r.text[:200]}')
    check(all(storage.get_program(m) is None for m in made if m), f'the half-made run was rolled back: {made}')
    _waiting_checks(mid, choice)
    r = _answer(mid, 'use')
    runs = _runs()
    check(r.status_code == 200 and len(runs) == 1 and runs[0]['library_id'] == lid, f'answered again, one run: {runs}')


def scenario_no_match_curates_at_once():
    _fresh()
    archived = _library(title='Learn piano', created_by='aunt')
    storage.update_library_program(archived, {'archived': True})     # an archived row is never offered
    mid, _ = _staged()
    row = _row(mid, 'r1')
    check(row['state'] == 'done' and "I made a new library program: Learn piano." in (row.get('result') or {}).get('message', ''),
          f'no live match: curated at once: {row}')
    runs = _runs()
    check(len(runs) == 1 and len(_library_rows()) == 1 and runs[0]['library_id'] != archived, 'one new row, one run of it')


def _answer_in_a_fresh_process(mid, option):
    """Answer the card from a NEW interpreter over the same data directory: nothing in memory
    survives, only what was persisted."""
    import os
    import subprocess
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    code = f"""
import sys
sys.path.insert(0, {here!r})
import harness
from unittest.mock import patch
from fastapi.testclient import TestClient
from services import storage, missions
import main
card = missions.ask_card(storage.get_mission({mid!r}))
opt = next(o for o in card['options'] if (o.get('payload') or {{}}).get('option') == {option!r})
token = storage.create_member_token('mom')
with patch.object(storage, 'get_settings', return_value={{**storage.get_settings(), 'auth_enforce': True}}):
    r = TestClient(main.app).post('/api/situations/mission/{mid}/act', headers={{'X-Member-Token': token}},
                                  json={{'verb': opt['verb'], 'option_id': opt['id'], 'payload': opt['payload']}})
print('STATUS', r.status_code, r.text[:300])
"""
    env = {k: v for k, v in os.environ.items() if k != 'HA_BASE_URL'}
    out = subprocess.run([sys.executable, '-c', code], cwd=os.path.dirname(here), env=env,
                         capture_output=True, text=True, timeout=600)
    return out.stdout + out.stderr


def scenario_waiting_choice_survives_restart():
    """Review Focus 5: a restart while the choice is open, then a pause and resume."""
    _fresh()
    from services import agent_tools_v2 as tools
    lid = _library()
    mid, project = _staged()
    _waiting_checks(mid)
    choice = _choice_id(mid)
    reran = []

    def trap(*a, **k):
        reran.append((a, k))
        raise AssertionError('the waiting row was executed again')
    with patch.object(tools, 'propose_program', side_effect=trap), \
            patch.dict(tools.TOOL_HANDLERS, {'propose_program': trap}), \
            patch.object(programs_curate, 'curate', side_effect=trap):
        planned._active_stages.clear()            # the process died; nothing is in flight
        planned.reconcile()
        _waiting_checks(mid, choice)
        check(not [s for s in storage.get_mission_steps(mid) if s.get('name') == 'stage_check'],
              'a waiting choice is never mistaken for an uncertain write')
        check(_ok(projects.set_state(project['id'], 'paused', dict(MOM))), 'paused')
        check(_ok(projects.set_state(project['id'], 'active', dict(MOM))), 'resumed')
        _waiting_checks(mid, choice)
        res = planned.resume_stage(mid, 's1', _stage(mid).get('snapshot'), dict(MOM))
        check(isinstance(res, dict), f'resume answers (a refusal is fine): {res}')
        _waiting_checks(mid, choice)
    check(not reran, f'reconcile, pause/resume and resume never re-ran the row: {reran}')
    stale = _choice(mid)
    out = _answer_in_a_fresh_process(mid, 'use')
    check('STATUS 200' in out, f'a fresh process answers from what was persisted: {out[-600:]}')
    runs = _runs()
    check(len(runs) == 1 and runs[0]['library_id'] == lid and _bound(mid, choice, runs[0]['id']),
          f'exactly one run, bound to the choice: {runs}')
    _act(mid, stale['use'])
    check(len(_runs()) == 1, 'a repeated tap after the restart creates nothing')


# --- voice ----------------------------------------------------------------------------------

def _voice_fresh():
    from test_front_door_chat import _fresh as _fresh_front_door
    storage.add_library_program               # the library's storage door: red here until Task 2
    _fresh_front_door()
    table = getattr(storage, 'library_programs_table', None)
    if table is not None:
        table.truncate()
    for name in ('program_lessons_table', 'deletions_table', 'protected_commitments_table', 'agent_action_proposals_table'):
        getattr(storage, name).truncate()
    missions._post = REAL_POST                # the real notice path: stored DMs with their refs
    web.research = lambda question, read_pages=None, api_key=None: {'status': 'success', 'answer': 'x', 'facts': [], 'sources': []}
    threads.draft_message = lambda thread_id, intent=None, **k: {'status': 'ok', 'subject': 's', 'body': 'b'}
    programs_curate.curate = lambda *a, **k: json.loads(json.dumps(CURATED))


def _dm(member_id='mom'):
    argyle = storage.ensure_argyle_member()
    return storage.get_channel_messages(storage.get_or_create_dm(argyle['id'], member_id)['id'])


def _notices():
    return [m for m in _dm() if NOTICE in (m.get('body') or '')]


def scenario_voice_persists_its_policy():
    from services import agent_tools_v2 as tools
    _voice_fresh()
    out = tools.start_project('I want Kate to learn piano', acting_member=dict(MOM), spoken=True)
    check(out['status'] == 'success' and out.get('mission_id'), f'started by voice: {out}')
    check(storage.get_mission(out['mission_id']).get('interaction') == 'voice',
          f"the planning mission remembers it was spoken: {storage.get_mission(out['mission_id'])}")
    out = tools.start_project('I want to learn the drums', acting_member=dict(MOM))
    check(storage.get_mission(out['mission_id']).get('interaction') != 'voice', 'a typed one does not')


def _raw_notices():
    """Every stored notice, before any read filter: what delivery would have to re-check."""
    return [m for m in storage.chat_messages_table.all() if NOTICE in (m.get('body') or '')]


def _held(held):
    """Hold every queued push fan-out: _post_chat_message stores the message, then hands it to
    main._fanout_message_notifications on a thread; here the hand-off is recorded, not run."""
    return patch.object(main, '_fanout_message_notifications', side_effect=lambda channel, message: held.append((channel, message)))


def _settle():
    """Join the fan-out threads the held hand-offs ran on."""
    import threading
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(5)


def _held_notices(held):
    return [(channel, message) for channel, message in held if NOTICE in (message.get('body') or '')]


def _release(queued):
    """Deliver the held notices through the REAL fan-out, recording every push and HA notify."""
    from services import ha_api
    sent = []
    real = main._fanout_message_notifications
    with patch.object(main, 'send_push_to_member', side_effect=lambda member_id, title, body, path, *a, **k:
                      sent.append({'to': member_id, 'body': body})), \
            patch.object(ha_api, 'call_service', side_effect=lambda *a, **k: sent.append({'ha': a})), \
            patch('services.family_digest.in_member_quiet_hours', return_value=False):
        for channel, message in queued:
            real(channel, message)
    return sent


def _voice_until_the_stage_ran():
    """Kate's piano by voice, driven to the moment the program stage has run (one match: used)."""
    from services import agent_tools_v2 as tools
    _voice_fresh()
    lid = _library()
    out = tools.start_project('I want Kate to learn piano', acting_member=dict(MOM), spoken=True)
    check(out['status'] == 'success' and SPOKEN in (out.get('message') or ''), f'the spoken reply: {out}')
    check(not _notices() and not _raw_notices(), 'nothing is announced at the time of the spoken reply')
    mid = out['mission_id']
    _plan({'action': 'interview', 'questions': [{'key': 'budget', 'ask': 'What is the budget?', 'kind': 'number'}]})
    _step(mid)
    planned.answer_plan(mid, {'budget': 40}, dict(MOM))
    _plan({'action': 'plan', 'stages': STAGES})
    _step(mid)
    rev = _plan_of(mid)['rev']
    res = situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f'plan approved: {res}')
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': ROWS})
    _step(mid)
    check(not _notices(), 'still nothing before the program stage runs')
    st = _stage(mid)
    res = situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s1:{st['snapshot']}:approve", payload={},
                         actor=dict(MOM))
    check(res['status'] == 'success', f'stage approved: {res}')
    runs = _runs()
    check(len(runs) == 1 and runs[0]['library_id'] == lid and _row(mid, 'r1')['state'] == 'done',
          f'one match: used at once, no spoken dialog: {_row(mid, "r1")}')
    check(not any(MATCH_HEAD in json.dumps(m.get('card') or {}) + (m.get('body') or '') for m in _dm()),
          'no Use / Make new card under voice')
    return mid, runs[0]['id']


def scenario_voice_uses_a_single_match_and_says_so_later():
    held = []
    with _held(held):
        mid, run_id = _voice_until_the_stage_ran()
        _step(mid)
        _settle()
    notices = _notices()
    check(len(notices) == 1, f"the mission's notice arrives once, after the stage ran: {[m.get('body') for m in _dm()]}")
    check({'kind': 'program', 'id': run_id} in [{k: r.get(k) for k in ('kind', 'id')} for r in notices[0].get('refs') or []],
          f'the notice refers to the run: {notices[0]}')
    check(storage.message_visible(notices[0]), 'and passes the delivery re-check')
    check(len(_raw_notices()) == 1, 'stored once')
    queued = _held_notices(held)
    check(len(queued) == 1, f'and queued once for delivery: {len(queued)}')
    sent = _release(queued)
    check(len(sent) == 1 and sent[0].get('to') == 'mom' and NOTICE in sent[0].get('body', ''),
          f'released while the run exists, it is delivered (the control for the suppression below): {sent}')


def scenario_a_queued_voice_notice_is_not_delivered_once_its_run_is_gone():
    """The notice is stored and queued while its run exists; the run's deletion is admitted; delivery
    is released BEFORE cleanup, while the notice row is still stored and the run row still exists but
    reads gone. Only the delivery path's own gone-ref re-check can stop it there: the reload finds the
    row, and a visibility check that skips references would push. Released again after cleanup (the
    notice row removed with the run), it still says nothing."""
    from services import access, deletion
    held = []
    with _held(held):
        mid, run_id = _voice_until_the_stage_ran()
        _step(mid)
        _settle()
    queued = _held_notices(held)
    check(len(queued) == 1 and len(_raw_notices()) == 1 and storage.get_program(run_id),
          f'the notice was stored and queued while its run existed: {len(queued)} {_raw_notices()}')
    preview = deletion.preview('program', run_id, dict(MOM))
    check(preview['status'] == 'ok', f'preview: {preview}')
    check(deletion.start('program', run_id, dict(MOM), preview['token'])['status'] == 'ok', 'the run is deleted')
    # Admitted, not cleaned up: the queued copy is still stored and the run row is still there.
    notice_id = queued[0][1]['id']
    check(storage.get_chat_message(notice_id) is not None and len(_raw_notices()) == 1,
          f'before cleanup the queued notice is still stored: {_raw_notices()}')
    run = storage.get_program(run_id)
    check(run is not None and access.gone('program', run, rid=run_id),
          f'and its run still has a row but reads gone: {run}')
    sent = _release(queued)
    check(not sent, f'released before cleanup: no push and no HA notify about a run that is gone: {sent}')
    check(not _notices() and not storage.message_visible(storage.get_chat_message(notice_id)),
          f'and the stored notice is not visible: {_raw_notices()}')
    for _ in range(5):
        deletion.maintain()
    check(storage.get_program(run_id) is None, 'gone after cleanup')
    sent = _release(queued)
    check(not sent, f'released after cleanup: still no push and no HA notify: {sent}')
    check(not _notices() and all(not storage.message_visible(m) for m in _raw_notices()),
          f'and no stored notice is visible: {_raw_notices()}')


def scenario_a_voice_notice_is_suppressed_once_its_run_is_gone():
    """The notice is delivered later; by then the run it names may be gone, and then it says nothing."""
    from services import deletion
    mid, run_id = _voice_until_the_stage_ran()
    preview = deletion.preview('program', run_id, dict(MOM))
    check(preview['status'] == 'ok', f'preview: {preview}')
    check(deletion.start('program', run_id, dict(MOM), preview['token'])['status'] == 'ok', 'the run is deleted')
    for _ in range(5):
        deletion.maintain()
    check(storage.get_program(run_id) is None, 'gone before the notice is delivered')
    _step(mid)
    check(not _notices(), f"no notice reaches Mom's DM about a run that is gone: {[m.get('body') for m in _dm()]}")
    check(all(not storage.message_visible(m) for m in _raw_notices()),
          f'and any stored copy fails the delivery re-check: {_raw_notices()}')


def scenario_voice_curates_when_the_match_is_not_single():
    _fresh()
    first, second = _library(), _library()
    mid, _ = _staged(interaction='voice')
    runs = _runs()
    check(len(runs) == 1 and runs[0]['library_id'] not in (first, second) and len(_library_rows()) == 3,
          f'several matches: a new one is curated: {runs}')
    check(not any(MATCH_HEAD in (p['body'] or '') + json.dumps(p['card'] or {}) for p in POSTS),
          'no Use / Make new card under voice')
    _fresh()
    mid, _ = _staged(interaction='voice')
    check(len(_runs()) == 1 and len(_library_rows()) == 1, 'no match: curated')


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    print(f'\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed')
    raise SystemExit(bool(failed))
