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


def _http(member_id, method, path, **kwargs):
    headers = {'X-Member-Token': storage.create_member_token(member_id)} if member_id else {}
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        return TestClient(main.app).request(method, path, headers=headers, **kwargs)


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


def _choice(mid):
    card = missions.ask_card(storage.get_mission(mid))
    check(card and (card.get('question') or '').startswith(MATCH_HEAD) and card['question'].endswith(MATCH_TAIL),
          f'the choice is a mission ask card in its own words: {card}')
    labels = [o.get('label') for o in card['options']]
    check(all(label in labels for label in ('Use', 'Make new', 'Not now')), f'three buttons: {labels}')
    return {o['payload']['option']: o for o in card['options'] if (o.get('payload') or {}).get('option')}


def _answer(mid, option, opts=None):
    opt = (opts or _choice(mid))[option]
    return situations.act('mission', mid, opt['verb'], option_id=opt['id'], payload=opt['payload'], actor=dict(MOM))


def _waiting_checks(mid):
    row = _row(mid, 'r1')
    check(row['state'] == 'waiting_choice' and (row.get('result') or {}).get('status') == 'waiting_choice'
          and (row.get('result') or {}).get('choice_id'), f'the row waits on a durable choice: {row}')
    check(_row(mid, 'r2')['state'] not in ('skipped', 'done', 'failed', 'running'), f"its dependent waits: {_row(mid, 'r2')}")
    check(_stage(mid)['state'] not in ('done', 'skipped', 'uncertain', 'partial'), f"the stage stays open: {_stage(mid)['state']}")
    check(not _runs(), 'no run until the person chooses')


def scenario_a_library_match_waits_for_a_choice():
    _fresh()
    lid = _library()
    mid, _ = _staged()
    _waiting_checks(mid)
    opts = _choice(mid)
    check(set(opts) == {'use', 'make_new', 'not_now'}, f'the options name their choice: {opts}')
    res = _answer(mid, 'use', opts)
    check(_ok(res), f'Use: {res}')
    runs = _runs()
    check(len(runs) == 1 and runs[0]['library_id'] == lid and runs[0]['member_id'] == 'kid'
          and runs[0]['starting_point'] == SECRET, f'one run of the library program for Kate: {runs}')
    row = _row(mid, 'r1')
    check(row['state'] == 'done' and (row.get('result') or {}).get('created') == [{'kind': 'program', 'id': runs[0]['id']}],
          f'the row is done and names the run: {row}')
    check(_row(mid, 'r2')['state'] == 'done', f"and the stage carried on: {_row(mid, 'r2')}")
    _answer(mid, 'use', opts)
    check(len(_runs()) == 1, 'a repeated answer creates nothing')


def scenario_make_new_curates_and_not_now_fails_the_row():
    _fresh()
    lid = _library()
    mid, _ = _staged()
    before = len(_library_rows())
    check(_ok(_answer(mid, 'make_new')), 'Make new')
    runs = _runs()
    check(len(_library_rows()) == before + 1 and len(runs) == 1 and runs[0]['library_id'] != lid,
          f'a new library program, and a run of it: {runs}')
    check(_row(mid, 'r1')['state'] == 'done' and _row(mid, 'r2')['state'] == 'done', 'the stage carried on')
    _fresh()
    _library()
    mid, _ = _staged()
    _answer(mid, 'not_now')
    row = _row(mid, 'r1')
    check(row['state'] == 'failed' and (row.get('result') or {}).get('message') == NOT_NOW, f'Not now fails the row: {row}')
    check(not _runs() and _row(mid, 'r2')['state'] == 'skipped', f"no run, and the dependent is skipped: {_row(mid, 'r2')}")
    check(_stage(mid)['state'] not in ('running', 'proposed'), f"the stage goes on without it: {_stage(mid)['state']}")


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


def scenario_waiting_choice_survives_restart():
    """Review Focus 5: a restart while the choice is open, then a pause and resume."""
    _fresh()
    lid = _library()
    mid, project = _staged()
    _waiting_checks(mid)
    planned._active_stages.clear()                # the process died; nothing is in flight
    planned.reconcile()
    _waiting_checks(mid)
    check(not [s for s in storage.get_mission_steps(mid) if s.get('name') == 'stage_check'],
          'a waiting choice is never mistaken for an uncertain write')
    check(_ok(projects.set_state(project['id'], 'paused', dict(MOM))), 'paused')
    check(_ok(projects.set_state(project['id'], 'active', dict(MOM))), 'resumed')
    _waiting_checks(mid)
    stage = _stage(mid)
    try:
        planned.resume_stage(mid, 's1', stage.get('snapshot'), dict(MOM))
    except Exception as exc:                      # a refusal is fine; a re-run is not
        print('resume_stage raised', type(exc).__name__, exc)
    _waiting_checks(mid)
    opts = _choice(mid)
    check(_ok(_answer(mid, 'use', opts)), 'Use after the restart')
    _answer(mid, 'use', opts)
    runs = _runs()
    check(len(runs) == 1 and runs[0]['library_id'] == lid, f'exactly one run: {runs}')


# --- voice ----------------------------------------------------------------------------------

def scenario_voice_persists_its_policy():
    from test_front_door_chat import _fresh as _fresh_front_door
    from services import agent_tools_v2 as tools
    storage.add_library_program               # the library's storage door: red here until Task 2
    _fresh_front_door()
    out = tools.start_project('I want Kate to learn piano', acting_member=dict(MOM), spoken=True)
    check(out['status'] == 'success' and out.get('mission_id'), f'started by voice: {out}')
    check(storage.get_mission(out['mission_id']).get('interaction') == 'voice',
          f"the planning mission remembers it was spoken: {storage.get_mission(out['mission_id'])}")
    out = tools.start_project('I want to learn the drums', acting_member=dict(MOM))
    check(storage.get_mission(out['mission_id']).get('interaction') != 'voice', 'a typed one does not')


def scenario_voice_uses_a_single_match_and_says_so_later():
    _fresh()
    lid = _library()
    mid, _ = _staged(interaction='voice')
    runs = _runs()
    check(len(runs) == 1 and runs[0]['library_id'] == lid and _row(mid, 'r1')['state'] == 'done',
          f'one match: used at once, no spoken dialog: {_row(mid, "r1")}')
    check(not any(MATCH_HEAD in (p['body'] or '') + json.dumps(p['card'] or {}) for p in POSTS),
          'no Use / Make new card under voice')
    _step(mid)
    check(any('from the library' in (p['body'] or '') and 'Kate' in (p['body'] or '') for p in POSTS),
          f"the mission's notice says so: {[p['body'] for p in POSTS]}")
    _fresh()
    first, second = _library(), _library()
    mid, _ = _staged(interaction='voice')
    runs = _runs()
    check(len(runs) == 1 and runs[0]['library_id'] not in (first, second) and len(_library_rows()) == 3,
          f'several matches: a new one is curated: {runs}')
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
