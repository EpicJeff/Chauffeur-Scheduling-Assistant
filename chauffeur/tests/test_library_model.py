"""Program library, the model (spec 2026-10-19-program-library-design.md rev 3, section 1; plan Task 1 Step 1).

Pinned here, against the interfaces Tasks 2-3 implement:

  * a library row (`storage.add_library_program/get_library_program/update_library_program/
    delete_library_program`) holds the curriculum: phases with stable ids, an ordered ladder of
    lessons with stable ids, rotation sessions as a lesson's `variants`. The run (`programs` row)
    holds `library_id`, the effective `shape`, `progress` {lessons: {id: {done_sessions,
    completed_at}}, current, phases: {id: {weeks, milestone_hit_at}}} and no curriculum;
  * `programs.load(run)` hydrates title, source, phases (with `units` rebuilt from the lessons
    and the run's own weeks/milestone_hit_at), `unresolved: bool`;
  * `programs.lesson_for(run, date)` is the one projection {lesson_id, variant_label, title, steps,
    body|url, phase_id}: the bookmark's lesson, the date's variant (arithmetic over dates, never
    progress), and its steps follow a library edit;
  * progress rules: partial sessions, completion, the bookmark never leaving the current phase,
    the exhausted phase stays on its last lesson, Next/Back (`programs.step_bookmark`) keep counts,
    a removed current lesson moves within its phase, a lesson added into a judged phase is
    completed, "Reached it" (`programs.mark_milestone(run_id, phase_id)`) finishes only when every
    phase is judged, completion credits the named lesson, a moved lesson answers 409;
  * scripts are keyed (run id, lesson id, variant label) through the existing storage helpers
    (`upsert_program_lesson/get_program_lesson/delete_program_lesson`) with the slot dict
    {'lesson_id', 'variant_label'};
  * the effective shape lives on the run; an unresolved library is its own state.

Review Focus 1, 2, 3: scenario_edit_during_an_open_lesson, scenario_two_runs_same_program,
scenario_unresolved_run.

Run from chauffeur/:  python tests/test_library_model.py   (HA_BASE_URL unset)
"""
import datetime
import importlib
import json
import re
import time
import traceback
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)
from test_subjects import MOM, DAD, AUNT, KID
from services import storage, programs, projects, home_board
import main

SAM = {'id': 'sib', 'name': 'Sam', 'role': 'child', 'is_child': True}
MOVED = "That lesson moved; open it again."
UNRESOLVED = "Its library program is missing"
HEX = re.compile(r'[0-9a-f]{32}')
SLOTS = [{'day': 0, 'time_start': '17:00'}, {'day': 2, 'time_start': '17:00'}, {'day': 4, 'time_start': '17:00'}]

TODAY = datetime.date.today()
MON = TODAY + datetime.timedelta(days=(7 - TODAY.weekday()) or 7)     # the next Monday, never today
WED, FRI, MON2 = (MON + datetime.timedelta(days=n) for n in (2, 4, 7))
TABLES = ('programs_table', 'program_lessons_table', 'protected_commitments_table', 'projects_table',
          'members_table', 'threads_table', 'missions_table', 'mission_steps_table', 'app_state_table',
          'deletions_table')


def _svc():
    """services.library, imported per call: until Task 2 lands each scenario is red on its own."""
    return importlib.import_module('services.library')


def _fresh():
    for name in TABLES:
        getattr(storage, name).truncate()
    table = getattr(storage, 'library_programs_table', None)
    if table is not None:
        table.truncate()
    for m in (MOM, DAD, AUNT, dict(KID, birthdate='2017-03-01'), SAM):
        storage.add_member(dict(m))
    home_board.invalidate_cache()


def _curriculum(b_sessions=1):
    """Two phases; the first holds a two-session lesson, a lesson with a rotation, and a third."""
    ids = {k: uuid.uuid4().hex for k in ('P1', 'P2', 'A', 'B', 'D', 'C', 'E')}
    phases = [
        {'id': ids['P1'], 'name': 'Foundations', 'weeks': 4, 'what': 'Find your way round the keys',
         'milestone': 'Play a C major scale hands together', 'steps': ['Warm up your hands'],
         'progression': 'One new note a week', 'rotation': []},
        {'id': ids['P2'], 'name': 'First songs', 'weeks': 3, 'what': 'Play a tune',
         'milestone': 'Play Ode to Joy for someone', 'steps': [], 'progression': '', 'rotation': []}]
    lessons = [
        {'id': ids['A'], 'phase_id': ids['P1'], 'title': 'Posture and middle C', 'sessions': 2,
         'steps': ['Sit tall', 'Find middle C'], 'body': 'Middle C sits under the brand name.', 'variants': []},
        {'id': ids['B'], 'phase_id': ids['P1'], 'title': 'Five-finger scale', 'sessions': b_sessions, 'steps': ['Scale'],
         'variants': [{'label': 'Session A', 'steps': ['Scale up slowly']},
                      {'label': 'Session B', 'steps': ['Scale down slowly']}]},
        {'id': ids['D'], 'phase_id': ids['P1'], 'title': 'Hands together', 'sessions': 1,
         'steps': ['Both hands, slowly'], 'variants': []},
        {'id': ids['C'], 'phase_id': ids['P2'], 'title': 'Ode to Joy, right hand', 'sessions': 2,
         'steps': ['Right hand only'], 'variants': []},
        {'id': ids['E'], 'phase_id': ids['P2'], 'title': 'Ode to Joy, both hands', 'sessions': 1,
         'steps': ['Both hands'], 'variants': []}]
    return ids, phases, lessons


def _library(title='Learn piano', created_by='aunt', minutes=30, sessions_per_week=2, b_sessions=1):
    ids, phases, lessons = _curriculum(b_sessions)
    ids['L'] = storage.add_library_program({
        'title': title, 'created_by': created_by, 'archived': False,
        'made_for': {'age_band': 'explorer', 'minutes': minutes, 'sessions_per_week': sessions_per_week,
                     'assumes': 'complete beginner'},
        'source': {'origin': 'cited', 'plan_name': 'Faber Piano Adventures', 'url': 'https://example.test/faber',
                   'facts': [], 'reason': ''},
        'phases': phases, 'lessons': lessons})
    return ids


def _project(owner='kid', title=None, audience='household'):
    res = projects.create({'title': title or f'{owner} piano {uuid.uuid4().hex[:6]}', 'goal': 'g', 'done_when': 'd',
                           'owner_member_id': owner, 'audience': audience}, dict(MOM))
    check(res['status'] == 'success', f'project: {res}')
    return res['project']


def _done(ids, *keys, n=None):
    """Progress entries marking these lessons completed (each at its own requirement unless n)."""
    sessions = {'A': 2, 'B': 1, 'D': 1, 'C': 2, 'E': 1}
    return {ids[k]: {'done_sessions': n if n is not None else sessions[k], 'completed_at': time.time()} for k in keys}


def _run(ids, member='kid', current='A', done=None, phases=None, state='proposed', shape=None, project=None):
    project = project or _project(member)
    data = {'member_id': member, 'library_id': ids['L'], 'state': state, 'created_by': 'mom',
            'starting_point': f'SECRET-START-{member}',
            'shape': programs.clamp_shape(shape or {'minutes': 20, 'sessions_per_week': 3}),
            'progress': {'lessons': done or {}, 'current': ids[current] if current else None,
                         'phases': phases or {}},
            'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None,
                         'rebaselined_at': None, 'rebaselines': 0}}
    rid = programs.create_row(data, project_id=project['id'])
    check(rid, 'the run was stored')
    return rid


def _approve(rid, slots=SLOTS):
    res = programs.approve(rid, 'mom', slots=slots)
    check(res['status'] == 'success', f'approved: {res}')


def _progress(rid):
    return storage.get_program(rid).get('progress') or {}


def _current(rid):
    return _progress(rid).get('current')


def _count(rid, lesson):
    return int(((_progress(rid).get('lessons') or {}).get(lesson) or {}).get('done_sessions') or 0)


def _completed(rid, lesson):
    return bool(((_progress(rid).get('lessons') or {}).get(lesson) or {}).get('completed_at'))


def _lid(value):
    """A lesson named by id, or by a lesson dict, or nothing."""
    if value is None or isinstance(value, str):
        return value
    return value.get('lesson_id') or value.get('id')


def _lesson_ids(lid):
    return [lesson['id'] for lesson in storage.get_library_program(lid)['lessons']]


def _windows(rid, start, end=None, viewer=MOM):
    return [w for w in programs.practice_windows(start, end or start, viewer=dict(viewer)) if w['program_id'] == rid]


def _live_commitments(rid):
    return [c for c in storage.get_protected_commitments(include_inactive=True)
            if c.get('active') and (c.get('source') or {}).get('id') == rid]


def _http(member_id, method, path, **kwargs):
    headers = {'X-Member-Token': storage.create_member_token(member_id)} if member_id else {}
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        return TestClient(main.app).request(method, path, headers=headers, **kwargs)


def _say(text):
    return [{'type': 'say', 'text': text}]


def _has_flag(data, key):
    if isinstance(data, dict):
        return data.get(key) is True or any(_has_flag(v, key) for v in data.values())
    if isinstance(data, list):
        return any(_has_flag(v, key) for v in data)
    return False


# --- the row, the run, the loader -------------------------------------------------------------

def scenario_load_hydrates_the_run():
    _fresh()
    ids = _library()
    rid = _run(ids, phases={ids['P1']: {'weeks': 6, 'milestone_hit_at': None}})
    raw = storage.get_program(rid)
    check(raw.get('library_id') == ids['L'], f'the run names its library row: {raw}')
    check(not raw.get('phases') and not (raw.get('source') or {}).get('plan_name'),
          f'the run stores no curriculum of its own: {raw}')
    loaded = programs.load(raw)
    check(loaded['unresolved'] is False, f'a bound run is resolved: {loaded}')
    check(loaded['id'] == rid and loaded['member_id'] == 'kid' and loaded['starting_point'] == 'SECRET-START-kid',
          'the run fields ride along')
    check(loaded['title'] == 'Learn piano' and loaded['source']['plan_name'] == 'Faber Piano Adventures',
          f"title and source from the library: {loaded.get('title')} {loaded.get('source')}")
    check([p['id'] for p in loaded['phases']] == [ids['P1'], ids['P2']]
          and [p['name'] for p in loaded['phases']] == ['Foundations', 'First songs'], f"phases: {loaded['phases']}")
    check(loaded['phases'][0]['weeks'] == 6 and loaded['phases'][1]['weeks'] == 3,
          f"the run's own pacing over the library default: {[p['weeks'] for p in loaded['phases']]}")
    units = loaded['phases'][0]['units']
    check([u['title'] for u in units] == ['Posture and middle C', 'Five-finger scale', 'Hands together']
          and [int(u['sessions']) for u in units] == [2, 1, 1], f'units rebuilt from the lessons: {units}')
    check([_lid(u) for u in units] == [ids['A'], ids['B'], ids['D']], f'each unit names its lesson: {units}')
    check([u['title'] for u in loaded['phases'][1]['units']] == ['Ode to Joy, right hand', 'Ode to Joy, both hands'],
          'the second phase has its own units')
    check(loaded['phases'][0]['milestone'] == 'Play a C major scale hands together'
          and not loaded['phases'][0].get('milestone_hit_at'), 'the milestone, not yet judged')
    check(loaded['shape']['minutes'] == 20 and loaded['shape']['sessions_per_week'] == 3,
          f"the run's effective shape, not the library's made_for (30/2): {loaded['shape']}")
    storage.update_program(rid, {'state': 'active'})
    check(programs.mark_milestone(rid, ids['P1'])['status'] == 'success', 'Reached it on Foundations')
    loaded = programs.load(storage.get_program(rid))
    check(loaded['phases'][0].get('milestone_hit_at') and not loaded['phases'][1].get('milestone_hit_at'),
          "the run's judgement is merged into its phase")
    check(storage.get_library_program(ids['L'])['phases'][0].get('milestone_hit_at') is None,
          'a judgement is the run\'s, never written onto the library row')


def scenario_lesson_for_resolves_the_bookmark_and_the_date():
    _fresh()
    ids = _library()
    rid = _run(ids, current='B')
    _approve(rid)
    run = storage.get_program(rid)
    labels = []
    for day in (MON, WED, FRI, MON2):
        one = programs.lesson_for(run, day)
        check(set(one) >= {'lesson_id', 'variant_label', 'title', 'steps', 'phase_id'}, f'the projection: {one}')
        check(one['lesson_id'] == ids['B'] and one['phase_id'] == ids['P1'] and one['title'] == 'Five-finger scale',
              f'the bookmark picks the lesson: {one}')
        want = {'Session A': ['Scale up slowly'], 'Session B': ['Scale down slowly']}.get(one['variant_label'])
        check(want is not None and one['steps'] == want, f"the date picks the variant and its steps: {one}")
        labels.append(one['variant_label'])
    check(labels[0] != labels[1] and labels[1] != labels[2] and labels[2] != labels[3],
          f'consecutive evenings take turns: {labels}')
    check(programs.lesson_for(run, WED) == programs.lesson_for(run, WED), 'the same date gives the same answer')
    before = programs.lesson_for(storage.get_program(rid), WED)['variant_label']
    storage.update_program(rid, {'state': 'active'})
    programs.log_session(rid, lesson_id=ids['A'])
    check(programs.lesson_for(storage.get_program(rid), WED)['variant_label'] == before,
          'logging never changes which variant a date gets')
    # The bookmarked lesson itself practised, short of completion: still date arithmetic only.
    multi = _library(b_sessions=3)
    busy = _run(multi, current='B')
    _approve(busy)
    days = (MON, WED, FRI, MON2)
    seen = {d: programs.lesson_for(storage.get_program(busy), d) for d in days}
    check(len({seen[d]['variant_label'] for d in days}) == 2, f'both variants are dealt: {seen}')
    windows_before = {w['date']: (w['variant_label'], w['steps']) for w in _windows(busy, MON, MON2)}
    for logged in (1, 2):
        if logged == 1:
            programs.log_session(busy, lesson_id=multi['B'])
        else:
            programs.log_session(busy)
        check(_count(busy, multi['B']) == logged and not _completed(busy, multi['B']) and _current(busy) == multi['B'],
              f'{logged} of three sessions on the bookmarked lesson: {_progress(busy)}')
        for d in days:
            now = programs.lesson_for(storage.get_program(busy), d)
            check((now['lesson_id'], now['variant_label'], now['steps'])
                  == (seen[d]['lesson_id'], seen[d]['variant_label'], seen[d]['steps']),
                  f'after log {logged}, the date keeps its variant: {d} {seen[d]} -> {now}')
        check({w['date']: (w['variant_label'], w['steps']) for w in _windows(busy, MON, MON2)} == windows_before,
              f'after log {logged}, every window keeps its variant and steps')
    check(_count(busy, multi['B']) == 2 and not _completed(busy, multi['B']) and _current(busy) == multi['B'],
          f'two of three sessions on the bookmarked lesson: {_progress(busy)}')
    for d in days:
        now = programs.lesson_for(storage.get_program(busy), d)
        check((now['lesson_id'], now['variant_label'], now['steps'])
              == (seen[d]['lesson_id'], seen[d]['variant_label'], seen[d]['steps']),
              f'practising the lesson never moves a date to another variant: {d} {seen[d]} -> {now}')
    check({w['date']: (w['variant_label'], w['steps']) for w in _windows(busy, MON, MON2)} == windows_before,
          'and every window keeps its variant and steps')
    windows = _windows(rid, MON, FRI)
    check(len(windows) == 3, f'three windows this week: {windows}')
    from services import program_lessons as pl
    for w in windows:
        one = programs.lesson_for(storage.get_program(rid), datetime.date.fromisoformat(w['date']))
        check(w.get('lesson_id') == one['lesson_id'] and w.get('variant_label') == one['variant_label']
              and w['steps'] == one['steps'], f'a window carries the projection: {w} vs {one}')
        slot = pl.slot_of(w)
        check(slot.get('lesson_id') == one['lesson_id'] and slot.get('variant_label') == one['variant_label'],
              f'the script slot of a window is (lesson id, variant label): {slot}')
    plain = programs.lesson_for(storage.get_program(_run(ids, current='A')), MON)
    check(plain['lesson_id'] == ids['A'] and plain['variant_label'] == '' and plain['steps'] == ['Sit tall', 'Find middle C']
          and plain.get('body') == 'Middle C sits under the brand name.', f'a lesson with no variants: {plain}')


def scenario_steps_follow_a_library_edit():
    _fresh()
    ids = _library()
    rid = _run(ids, current='A', done={ids['A']: {'done_sessions': 1, 'completed_at': None}})
    _approve(rid)
    before = _progress(rid)
    res = _svc().update_lesson(ids['L'], ids['A'], {'steps': ['Sit tall', 'Play middle C five times']}, dict(AUNT))
    check(res.get('status') in ('success', 'ok'), f'the creator edits a lesson: {res}')
    one = programs.lesson_for(storage.get_program(rid), MON)
    check(one['lesson_id'] == ids['A'] and one['steps'] == ['Sit tall', 'Play middle C five times'],
          f'the projection reads the edited steps: {one}')
    check(_windows(rid, MON)[0]['steps'] == ['Sit tall', 'Play middle C five times'], 'and so does the window')
    check(_progress(rid) == before, f'a content edit changes no progress: {before} -> {_progress(rid)}')


def scenario_ids_are_stable_through_edit_reorder_add_and_remove():
    _fresh()
    lib = _svc()
    ids = _library()
    rid = _run(ids, done={ids['A']: {'done_sessions': 1, 'completed_at': None}})
    row = storage.get_library_program(ids['L'])
    phase_ids = [p['id'] for p in row['phases']]
    check(_lesson_ids(ids['L']) == [ids[k] for k in 'ABDCE'], 'storage keeps the ids it was given')
    check(lib.update(ids['L'], {'title': 'Learn the piano'}, dict(AUNT)).get('status') in ('success', 'ok'), 'retitle')
    check(lib.update_lesson(ids['L'], ids['A'], {'title': 'Sitting and middle C', 'sessions': 3}, dict(AUNT))
          .get('status') in ('success', 'ok'), 'lesson edit')
    row = storage.get_library_program(ids['L'])
    check(row['title'] == 'Learn the piano' and row['lessons'][0]['title'] == 'Sitting and middle C', 'edits land')
    check(_lesson_ids(ids['L']) == [ids[k] for k in 'ABDCE'] and [p['id'] for p in row['phases']] == phase_ids,
          'content edits keep every id')
    order = [ids[k] for k in 'ADBCE']
    check(lib.order_lessons(ids['L'], order, dict(AUNT)).get('status') in ('success', 'ok'), 'reorder')
    row = storage.get_library_program(ids['L'])
    check(_lesson_ids(ids['L']) == order, f'the new order: {_lesson_ids(ids["L"])}')
    check({l['id']: l['phase_id'] for l in row['lessons']}[ids['D']] == ids['P1'], 'a lesson keeps its phase')
    check(_count(rid, ids['A']) == 1, 'progress is keyed by lesson id, so a reorder moves no count')
    lib.add_lesson(ids['L'], {'phase_id': ids['P2'], 'title': 'Ode to Joy, from memory', 'sessions': 1,
                              'steps': ['No looking']}, dict(AUNT))
    added = [i for i in _lesson_ids(ids['L']) if i not in order]
    check(len(added) == 1 and HEX.fullmatch(added[0]), f'one new lesson with a minted uuid4 hex id: {added}')
    new = next(l for l in storage.get_library_program(ids['L'])['lessons'] if l['id'] == added[0])
    check(new['phase_id'] == ids['P2'] and new['title'] == 'Ode to Joy, from memory', f'added into its phase: {new}')
    check(lib.remove_lesson(ids['L'], ids['D'], dict(AUNT)).get('status') in ('success', 'ok'), 'remove')
    check(_lesson_ids(ids['L']) == [ids[k] for k in 'ABCE'] + added, f'the rest untouched: {_lesson_ids(ids["L"])}')
    check([p['id'] for p in storage.get_library_program(ids['L'])['phases']] == phase_ids, 'phase ids never move')
    # A program made through the service mints its ids once.
    curated = {'phases': [{'name': 'Strum', 'weeks': 2, 'what': 'Down strums', 'milestone': 'Strum a song',
                           'units': [{'n': 1, 'title': 'Hold it', 'sessions': 1}, {'n': 2, 'title': 'Down strums', 'sessions': 2}],
                           'rotation': [{'label': 'Session A', 'steps': ['Chords']}, {'label': 'Session B', 'steps': ['Song']}]},
                          {'name': 'Songs', 'weeks': 2, 'what': 'A song', 'milestone': 'Play one', 'steps': ['Play along']}],
               'source': {'origin': 'generated', 'plan_name': '', 'url': '', 'facts': [], 'reason': 'test'}}
    with patch('services.programs_curate.curate', return_value=curated):
        res = lib.create({'title': 'Learn ukulele', 'age_band': 'any', 'minutes': 15, 'sessions_per_week': 2,
                          'assumes': 'complete beginner'}, dict(AUNT))
    check(res.get('status') in ('success', 'ok') and res.get('program'), f'created: {res}')
    made = storage.get_library_program(res['program']['id'])
    phases = {p['id'] for p in made['phases']}
    check(made['phases'] and all(HEX.fullmatch(p) for p in phases), f'phase ids minted: {made["phases"]}')
    check(made['lessons'] and all(HEX.fullmatch(l['id']) and l['phase_id'] in phases for l in made['lessons']),
          f'lesson ids minted, each in a phase: {made["lessons"]}')
    check(all(any(l['phase_id'] == p for l in made['lessons']) for p in phases), 'every phase has a lesson')


# --- progress rules -------------------------------------------------------------------------

def scenario_partial_sessions_then_completion_then_the_next_in_phase():
    _fresh()
    ids = _library()
    rid = _run(ids, current='A', state='active')
    programs.log_session(rid)
    check(_count(rid, ids['A']) == 1 and not _completed(rid, ids['A']) and _current(rid) == ids['A'],
          f'one of two sessions: {_progress(rid)}')
    programs.log_session(rid)
    check(_completed(rid, ids['A']) and _current(rid) == ids['B'], f'two of two completes it and moves on: {_progress(rid)}')
    check(_lid(programs.next_in_phase(storage.get_program(rid))) == ids['D'], 'the next lesson in the phase')
    programs.log_session(rid)
    programs.log_session(rid)
    check(_completed(rid, ids['D']) and _current(rid) == ids['D'],
          f'an exhausted phase stays on its last lesson, ready to judge: {_progress(rid)}')
    check(programs.next_in_phase(storage.get_program(rid)) is None, 'nothing left in the phase')
    programs.log_session(rid)
    check(_current(rid) == ids['D'] and _count(rid, ids['D']) == 2,
          f'further logs count against the last lesson, never the next phase: {_progress(rid)}')
    check(not _count(rid, ids['C']) and storage.get_program(rid)['state'] == 'active',
          'the next phase waits for the person to judge the milestone')


def scenario_completion_moves_past_a_lesson_already_completed():
    _fresh()
    ids = _library()
    done = {ids['A']: {'done_sessions': 1, 'completed_at': None}, **_done(ids, 'B')}
    rid = _run(ids, current='A', state='active', done=done)
    stamp = done[ids['B']]['completed_at']
    programs.log_session(rid)
    check(_completed(rid, ids['A']) and _current(rid) == ids['D'],
          f'the next UNCOMPLETED lesson, skipping one already done: {_progress(rid)}')
    b = (_progress(rid).get('lessons') or {}).get(ids['B']) or {}
    check(b.get('done_sessions') == 1 and b.get('completed_at') == stamp, f'the completed lesson keeps its counts: {b}')


def scenario_next_and_back_keep_every_count():
    _fresh()
    ids = _library()
    rid = _run(ids, current='A', state='active', done={ids['A']: {'done_sessions': 1, 'completed_at': None}})
    for direction, want in (('next', 'B'), ('next', 'D'), ('next', 'D'), ('back', 'B'), ('back', 'A'), ('back', 'A')):
        programs.step_bookmark(rid, direction)
        check(_current(rid) == ids[want], f'{direction} lands on {want}: {_progress(rid)}')
        check(_count(rid, ids['A']) == 1 and not _completed(rid, ids['A']), 'moving the bookmark completes nothing')
    r = _http('kid', 'POST', f'/api/programs/{rid}/unit', json={'direction': 'next'})
    check(r.status_code == 200 and _current(rid) == ids['B'], f'Next by hand: {r.status_code} {r.text[:200]}')
    r = _http('kid', 'POST', f'/api/programs/{rid}/unit', json={'direction': 'back'})
    check(r.status_code == 200 and _current(rid) == ids['A'], f'"Another session on this" stays: {r.text[:200]}')
    check(_count(rid, ids['A']) == 1, 'and still no count moved')


def scenario_a_removed_current_lesson_moves_within_its_phase():
    _fresh()
    lib = _svc()
    ids = _library()
    rid = _run(ids, current='B')
    lib.remove_lesson(ids['L'], ids['B'], dict(AUNT))
    check(_current(rid) == ids['D'], f'the next lesson of the same phase: {_progress(rid)}')
    ids = _library()
    rid = _run(ids, current='D')
    lib.remove_lesson(ids['L'], ids['D'], dict(AUNT))
    check(_current(rid) == ids['B'], f'the last one removed: the previous lesson of its phase: {_progress(rid)}')
    ids = _library()
    judged = {ids['P1']: {'milestone_hit_at': time.time()}}
    rid = _run(ids, current='C', state='active', phases=judged, done=_done(ids, 'A', 'B', 'D'))
    lib.remove_lesson(ids['L'], ids['C'], dict(AUNT))
    check(_current(rid) == ids['E'], f'never back into an earlier phase: {_progress(rid)}')


def scenario_a_lesson_added_into_a_judged_phase_is_completed():
    _fresh()
    ids = _library()
    rid = _run(ids, current='A', state='active')
    check(programs.mark_milestone(rid, ids['P1'])['status'] == 'success', 'Reached it')
    check(_current(rid) == ids['C'], f'the bookmark moves to the next unjudged phase: {_progress(rid)}')
    check(all(_completed(rid, ids[k]) for k in 'ABD'), f'every lesson of the judged phase is completed: {_progress(rid)}')
    _svc().add_lesson(ids['L'], {'phase_id': ids['P1'], 'title': 'Pedal basics', 'sessions': 1, 'steps': []}, dict(AUNT))
    new = [i for i in _lesson_ids(ids['L']) if i not in [ids[k] for k in 'ABDCE']][0]
    loaded = programs.load(storage.get_program(rid))
    check(((loaded['progress']['lessons'].get(new) or {}).get('completed_at')),
          f'a lesson added into a judged phase is completed by that judgement: {loaded["progress"]}')
    check(_current(rid) == ids['C'] and _lid(programs.next_in_phase(storage.get_program(rid))) != new,
          'and the bookmark does not go back for it')


def scenario_reached_it_finishes_only_when_every_phase_is_judged():
    _fresh()
    ids = _library()
    rid = _run(ids)
    _approve(rid)
    check(len(_live_commitments(rid)) == 3, 'three windows claimed')
    res = programs.mark_milestone(rid, ids['P1'])
    row = storage.get_program(rid)
    check(res['status'] == 'success' and row['state'] == 'active' and len(_live_commitments(rid)) == 3,
          f'a non-final phase never finishes the run: {res} {row["state"]}')
    check((row['progress']['phases'].get(ids['P1']) or {}).get('milestone_hit_at'), 'the judgement is on the run')
    ids2 = _library()
    rid2 = _run(ids2)
    _approve(rid2)
    res = programs.mark_milestone(rid2, ids2['P2'])
    check(res['status'] == 'success' and storage.get_program(rid2)['state'] == 'active'
          and len(_live_commitments(rid2)) == 3 and _current(rid2) == ids2['A'],
          f'judging the last phase first finishes nothing and moves no bookmark: {res} {_progress(rid2)}')
    res = programs.mark_milestone(rid2, ids2['P1'])
    row = storage.get_program(rid2)
    check(res['status'] == 'success' and row['state'] == 'done' and row.get('finished_at')
          and not _live_commitments(rid2), f'every phase judged: finished and released: {res} {row["state"]}')
    ids3 = _library()
    rid3 = _run(ids3)
    _approve(rid3)
    programs.mark_milestone(rid3, ids3['P1'])
    with patch.object(programs, 'release_commitments', side_effect=RuntimeError('calendar down')):
        res = programs.mark_milestone(rid3, ids3['P2'])
    row = storage.get_program(rid3)
    check(res['status'] == 'error' and res['message'] == programs.RELEASE_ERROR, f'a release failure surfaces: {res}')
    check(row['state'] == 'active' and not (row['progress']['phases'].get(ids3['P2']) or {}).get('milestone_hit_at')
          and len(_live_commitments(rid3)) == 3, f'and nothing of the finish landed (one transaction): {row}')
    # A release that fails part-way: the first window is deleted, the second refuses.
    ids4 = _library()
    rid4 = _run(ids4)
    _approve(rid4)
    programs.mark_milestone(rid4, ids4['P1'])
    before = json.loads(json.dumps(storage.get_program(rid4)))
    real_delete = storage.delete_protected_commitment
    deletes = []

    def second_fails(cid):
        deletes.append(cid)
        if len(deletes) == 2:
            raise RuntimeError('the second window would not go')
        return real_delete(cid)
    with patch.object(storage, 'delete_protected_commitment', side_effect=second_fails):
        res = programs.mark_milestone(rid4, ids4['P2'])
    row = storage.get_program(rid4)
    check(len(deletes) >= 2, f'the failure was injected after one window was released: {deletes}')
    check(res['status'] == 'error' and res['message'] == programs.RELEASE_ERROR, f'it surfaces: {res}')
    check(len(_live_commitments(rid4)) == 3, f'all three windows are back (rolled back): {_live_commitments(rid4)}')
    check(row['emissions'] == before['emissions'] and row['progress'] == before['progress']
          and row['state'] == 'active' and not row.get('finished_at'),
          f'emissions, progress, state and finish time exactly as before: {row}')


def scenario_completion_credits_the_named_lesson_and_a_moved_lesson_is_409():
    _fresh()
    ids = _library()
    rid = _run(ids, current='A', state='active')
    programs.log_session(rid, lesson_id=ids['B'])
    check(_completed(rid, ids['B']) and not _count(rid, ids['A']) and _current(rid) == ids['A'],
          f'the named lesson is credited, never the current one: {_progress(rid)}')
    r = _http('kid', 'POST', f'/api/programs/{rid}/session', json={'lesson_id': ids['D'], 'minutes': 20})
    check(r.status_code == 200 and _completed(rid, ids['D']), f'by hand, by name: {r.status_code} {r.text[:200]}')
    logged = len(storage.get_program(rid)['sessions'])
    r = _http('kid', 'POST', f'/api/programs/{rid}/session', json={'lesson_id': 'f' * 32})
    check(r.status_code == 409 and MOVED in r.text, f'a lesson not in the library: {r.status_code} {r.text[:200]}')
    _svc().remove_lesson(ids['L'], ids['E'], dict(AUNT))
    r = _http('kid', 'POST', f'/api/programs/{rid}/session', json={'lesson_id': ids['E']})
    check(r.status_code == 409 and MOVED in r.text, f'a removed lesson: {r.status_code} {r.text[:200]}')
    check(len(storage.get_program(rid)['sessions']) == logged, 'a refused completion logs nothing')
    r = _http('mom', 'PUT', f'/api/programs/{rid}/lesson',
              json={'lesson_id': ids['E'], 'variant_label': '', 'scenes': _say('Both hands now.')})
    check(r.status_code == 409 and MOVED in r.text, f'a script for a moved lesson: {r.status_code} {r.text[:200]}')


def scenario_scripts_are_keyed_by_run_lesson_and_variant():
    _fresh()
    ids = _library()
    kate, sam = _run(ids, member='kid'), _run(ids, member='sib')
    b_a = {'lesson_id': ids['B'], 'variant_label': 'Session A'}
    b_b = {'lesson_id': ids['B'], 'variant_label': 'Session B'}
    storage.upsert_program_lesson(kate, b_a, {'scenes': _say('Up words.'), 'origin': 'generated'})
    storage.upsert_program_lesson(kate, b_b, {'scenes': _say('Down words.'), 'origin': 'generated'})
    check('Up words.' in json.dumps(storage.get_program_lesson(kate, b_a))
          and 'Down words.' in json.dumps(storage.get_program_lesson(kate, b_b)), 'one script per variant')
    check(storage.get_program_lesson(sam, b_a) is None, 'two runs of one program never share a script')
    check(storage.get_program_lesson(kate, {'lesson_id': ids['A'], 'variant_label': ''}) is None, 'nor two lessons')
    r = _http('mom', 'PUT', f'/api/programs/{kate}/lesson',
              json={'lesson_id': ids['A'], 'variant_label': '', 'scenes': _say('Sit tall, Kate.')})
    check(r.status_code == 200, f'a hand edit by lesson id: {r.status_code} {r.text[:200]}')
    r = _http('mom', 'GET', f'/api/programs/{kate}/lesson', params={'lesson_id': ids['A'], 'variant_label': ''})
    check(r.status_code == 200 and 'Sit tall, Kate.' in r.text, f'read back by lesson id: {r.text[:200]}')
    r = _http('mom', 'GET', f'/api/programs/{sam}/lesson', params={'lesson_id': ids['A'], 'variant_label': ''})
    check(r.status_code == 200 and r.json().get('lesson') is None, f"Sam's run has no script of Kate's: {r.text[:200]}")
    r = _http('mom', 'DELETE', f'/api/programs/{kate}/lesson', params={'lesson_id': ids['A'], 'variant_label': ''})
    check(r.status_code == 200 and storage.get_program_lesson(kate, {'lesson_id': ids['A'], 'variant_label': ''}) is None,
          f'cleared by lesson id: {r.text[:200]}')
    check(storage.get_program_lesson(kate, b_a) and storage.get_program_lesson(kate, b_b), 'the other scripts stay')


def scenario_generation_help_and_legacy_slots_keep_lesson_identity():
    """Generation, the player's help, the wall's scenes and the legacy slot tuple, by lesson id.

    Retargeted to the lesson depth contract (spec 2026-10-20 sections 6-7): a library run plays
    the library's ONE script per (library, lesson, variant), written from the public profile, so
    two runs of one library share it and no run's private starting point reaches any prompt. The
    legacy (phase_name, unit_n, session_label) tuple still translates to the lesson for one
    release and reads the same script. The GET-by-tuple, lesson-scenes, lesson-help and library
    DELETE assertions below read through the run resolver and the library script routes, which
    Task 4 builds: until it lands they are red on that, and only on that."""
    _fresh()
    storage.library_scripts_table.truncate()
    from services import model_pools, program_lessons as pl, library_scripts
    ids = _library()
    rid = _run(ids, current='B')
    _approve(rid, [{'day': 0, 'time_start': '17:00'}, {'day': 2, 'time_start': '17:00'}])
    other = _run(ids, member='sib', current='B', project=_project('sib'))
    _approve(other, [{'day': 0, 'time_start': '18:00'}, {'day': 2, 'time_start': '18:00'}])
    labels = {d: programs.lesson_for(storage.get_program(rid), d)['variant_label'] for d in (MON, WED)}
    check(labels[MON] != labels[WED], f'two evenings, two variants: {labels}')
    prompts = []

    marks = ('Scale up slowly', 'Scale down slowly', 'Up, both hands', 'Down, both hands')

    def fake_pool(pool, key, system, prompt, **kw):
        # The script says which private inputs and which steps its own prompt carried, so each
        # stored row can be traced back to the prompt that wrote it. Full length for the
        # 30-minute profile, so no shortfall retry spends a second call.
        prompts.append(prompt)
        who = '+'.join(sp for sp in ('SECRET-START-kid', 'SECRET-START-sib') if sp in prompt) or 'nobody'
        steps = '+'.join(mk for mk in marks if mk in prompt) or 'no steps'
        return {'scenes': [{'type': 'say', 'text': f'Generated script for {who} with {steps}.'}]
                + [{'type': 'do', 'text': 'Play the scale slowly', 'seconds': 600}] * 3, '_model': 'stub'}
    eve = datetime.datetime.combine(MON - datetime.timedelta(days=1), datetime.time(21, 0))
    with patch.object(model_pools, 'call_pool_json', side_effect=fake_pool):
        wrote = pl.generate_due(now=eve)
    check(wrote == 2 and len(prompts) == 2,
          f'one script per (library, lesson, variant), shared by both runs: {wrote} written, {len(prompts)} calls')
    check(storage.program_lessons_table.all() == [], 'nothing is written per run')
    check(not any('SECRET-START' in p for p in prompts), f"no run's private starting point reaches any prompt: {prompts}")
    check(any('Scale up slowly' in p for p in prompts) and any('Scale down slowly' in p for p in prompts),
          "the variants' steps reach the generation input")
    variant_steps = {'Session A': 'Scale up slowly', 'Session B': 'Scale down slowly'}
    for day in (MON, WED):
        slot = {'lesson_id': ids['B'], 'variant_label': labels[day]}
        stored = storage.get_library_script(ids['L'], slot) or {}
        want = f'Generated script for nobody with {variant_steps[labels[day]]}.'
        check(json.dumps(stored.get('scenes')).count(want) == 1,
              f"the script under (library, B, {labels[day]}) came from a prompt carrying that variant's steps "
              f"and nobody's starting point: {stored.get('scenes')}")
        for run in (rid, other):
            read = library_scripts.script_for_run(storage.get_program(run), ids['B'], labels[day]) or {}
            check(read.get('scenes') == stored.get('scenes'), f'both runs read the same script: {run} {slot} {read}')
    hand, regen = labels[MON], labels[WED]
    storage.edit_library_script(ids['L'], {'lesson_id': ids['B'], 'variant_label': hand},
                                {'origin': 'generated', 'source_url': '', 'scenes': _say('Thumb on C, then climb.'),
                                 'model': '', 'attempts': 0, 'note': '', 'minutes': 1})
    # Legacy (phase_name, unit_n, session_label), translated for one release: unit 2 of Foundations is B.
    r = _http('mom', 'GET', f'/api/programs/{rid}/lesson',
              params={'phase_name': 'Foundations', 'unit_n': 2, 'session_label': hand})
    check(r.status_code == 200 and 'Thumb on C, then climb.' in r.text, f'the legacy tuple finds the lesson: {r.text[:200]}')
    r = _http('mom', 'GET', f'/api/programs/{rid}/lesson-scenes', params={'lesson_id': ids['B'], 'variant_label': hand})
    check(r.status_code == 200 and 'Thumb on C, then climb.' in r.text, f"the wall's scenes by lesson id: {r.text[:200]}")
    import main as _main
    helped = []

    def fake_help(pool, key, system, prompt, **kw):
        helped.append(prompt)
        return {'answer': 'Try it slowly, one finger at a time.'}
    with patch.object(model_pools, 'call_pool_json', side_effect=fake_help), \
            patch.object(model_pools, 'credentials', return_value=('interactive', 'k')):
        _main._lesson_help_at.clear()
        r = _http('kid', 'POST', f'/api/programs/{rid}/lesson-help',
                  json={'lesson_id': ids['B'], 'variant_label': hand, 'scene_idx': 0})
        check(r.status_code == 200 and r.json().get('answer'), f'help answers: {r.status_code} {r.text[:200]}')
        check(helped and 'Thumb on C, then climb.' in helped[0] and 'Learn piano' in helped[0],
              f"help reads the beat of the named lesson and the library title: {helped}")
        check(not any('SECRET-START' in p for p in helped), f'and no starting point reaches the help prompt: {helped}')
        _main._lesson_help_at.clear()
        r = _http('kid', 'POST', f'/api/programs/{rid}/lesson-help', json={'lesson_id': 'f' * 32, 'variant_label': ''})
        check(r.status_code == 409 and MOVED in r.text, f'help for a moved lesson: {r.status_code} {r.text[:200]}')
    r = _http('kid', 'POST', '/api/lessons/wait',
              json={'room': 'living room', 'text': 'Time to switch hands.', 'minutes': 5, 'program_id': rid})
    queue = storage.get_app_state(pl.WAIT_STATE_KEY) or []
    check(r.status_code == 200 and any(e.get('program_id') == rid for e in queue), f'the wait queue carries the run id: {queue}')
    # A content edit keeps every script until Regenerate.
    _svc().update_lesson(ids['L'], ids['B'], {'variants': [{'label': 'Session A', 'steps': ['Up, both hands']},
                                                           {'label': 'Session B', 'steps': ['Down, both hands']}]}, dict(AUNT))
    for label, words in ((hand, 'Thumb on C, then climb.'), (regen, 'Generated script')):
        kept = storage.get_library_script(ids['L'], {'lesson_id': ids['B'], 'variant_label': label})
        check(words in json.dumps(kept), f'{label}: kept through the library edit: {kept}')
    r = _http('mom', 'DELETE', f"/api/library/{ids['L']}/lessons/{ids['B']}/script", params={'variant_label': regen})
    check(r.status_code == 200, f'Regenerate clears one slot: {r.status_code} {r.text[:200]}')
    prompts.clear()
    storage.set_app_state('program_lessons_swept', '')
    with patch.object(model_pools, 'call_pool_json', side_effect=fake_pool):
        pl.generate_due(now=eve)
    want = {'Session A': 'Up, both hands', 'Session B': 'Down, both hands'}[regen]
    check(len(prompts) == 1 and want in prompts[0], f'only the cleared slot is written again, from the edited steps: {prompts}')
    check('Thumb on C, then climb.' in json.dumps(storage.get_library_script(ids['L'], {'lesson_id': ids['B'], 'variant_label': hand})),
          'the hand edit is still there')


def scenario_the_effective_shape_lives_on_the_run():
    _fresh()
    ids = _library(minutes=30, sessions_per_week=2)
    project = _project('kid', audience='parents')
    with patch('services.programs_curate.curate', side_effect=AssertionError('the picker spends no research')):
        r = _http('mom', 'POST', '/api/programs',
                  json={'project_id': project['id'], 'library_id': ids['L'], 'for_member_id': 'kid'})
    check(r.status_code == 200 and r.json().get('status') == 'success', f'a run from the picker: {r.status_code} {r.text[:300]}')
    rid = r.json()['id']
    raw = storage.get_program(rid)
    check(raw['library_id'] == ids['L'] and raw['state'] == 'proposed' and raw['member_id'] == 'kid'
          and raw['project_id'] == project['id'], f'the run: {raw}')
    check(raw['shape']['minutes'] == 30 and raw['shape']['sessions_per_week'] == 2,
          f"defaults copied from made_for: {raw['shape']}")
    check((raw.get('progress') or {}).get('current') == ids['A'], 'the bookmark starts on the first lesson')
    r = _http('mom', 'POST', f'/api/programs/{rid}/edit', json={'minutes': 15})
    check(r.status_code == 200 and storage.get_program(rid)['shape']['minutes'] == 15, f'the run owns its minutes: {r.text[:200]}')
    _approve(rid)
    shape = storage.get_program(rid)['shape']
    check(shape['sessions_per_week'] == 3 and shape['minutes'] == 15 and len(shape.get('slots') or []) == 3,
          f'approval persists the agreed shape on the run: {shape}')
    made_for = storage.get_library_program(ids['L'])['made_for']
    check(made_for['minutes'] == 30 and made_for['sessions_per_week'] == 2, f'the library defaults are untouched: {made_for}')
    start = (TODAY - datetime.timedelta(days=28)).isoformat()
    storage.update_program(rid, {'shape': {**shape, 'preferred_days': [0, 2, 4]},
                                 'baseline': {**storage.get_program(rid)['baseline'], 'start_date': start}})
    short = programs.weekday_shortfall(storage.get_program(rid))
    check(short and short['per_week'] == 3, f"weekday_shortfall reads the run's shape: {short}")


def scenario_rebaseline_writes_the_runs_pacing_only():
    _fresh()
    ids = _library()
    rid = _run(ids, state='active', shape={'minutes': 20, 'sessions_per_week': 3, 'preferred_days': [0, 2, 4]})
    storage.update_program(rid, {'baseline': {'start_date': (TODAY - datetime.timedelta(days=28)).isoformat(),
                                              'target_date': None, 'rebaselined_at': None, 'rebaselines': 0}})
    out = programs.maybe_rebaseline(storage.get_program(rid))
    check(out, 'three empty weeks re-pace the plan')
    weeks = (_progress(rid).get('phases') or {}).get(ids['P1'], {}).get('weeks')
    check(weeks and weeks > 4, f"the run's pacing stretched: {_progress(rid)}")
    check([p['weeks'] for p in storage.get_library_program(ids['L'])['phases']] == [4, 3],
          'the library default pacing is untouched')


# --- the unresolved state, warm boards ------------------------------------------------------

def scenario_unresolved_run():
    """Review Focus 3: the library row is deleted (or the pointer dangles) under a live run."""
    _fresh()
    ids = _library()
    project = _project('kid')
    rid = _run(ids, project=project)
    _approve(rid)
    storage.delete_library_program(ids['L'])
    loaded = programs.load(storage.get_program(rid))
    check(loaded['unresolved'] is True and loaded['phases'] == [], f'unresolved, empty curriculum: {loaded}')
    check('Learn piano' not in json.dumps(loaded), 'nothing of the vanished curriculum is invented')
    windows = _windows(rid, MON)
    check(len(windows) == 1 and windows[0]['time_start'] == '17:00', f'its time stays reserved: {windows}')
    words = json.dumps(windows[0])
    check(not windows[0].get('steps') and not windows[0].get('lesson_id')
          and 'Learn piano' not in words and 'middle C' not in words, f'a neutral window, time only: {windows[0]}')
    check(len(_live_commitments(rid)) == 3, 'its commitments are kept for the solver')
    for path in ('/api/programs', f"/api/projects/{project['id']}", '/api/practice-windows',
                 f'/api/programs/{rid}/footprint', '/api/commitments'):
        r = _http('mom', 'GET', path)
        check(r.status_code == 200, f'{path} answers, never a 500: {r.status_code} {r.text[:200]}')
    r = _http('mom', 'GET', '/api/commitments')
    check('Learn piano' not in r.text and 'middle C' not in r.text, f'its commitments render neutral: {r.text[:400]}')
    r = _http('mom', 'GET', f"/api/projects/{project['id']}")
    check(UNRESOLVED in r.text or _has_flag(r.json(), 'unresolved'), f'the run card says so: {r.text[:400]}')
    from services import deletion
    preview = deletion.preview('program', rid, dict(MOM))
    check(preview['status'] == 'ok', f'an unresolved run is deletable: {preview}')
    check(deletion.start('program', rid, dict(MOM), preview['token'])['status'] == 'ok', 'delete started')
    for _ in range(5):
        deletion.maintain()
    check(storage.get_program(rid) is None and not _live_commitments(rid), 'deleted, its time released')
    ids2 = _library(title='Learn piano again')
    rid2 = _run(ids2, current='B', done=_done(ids2, 'A'))
    _approve(rid2)
    storage.update_program(rid2, {'library_id': 'no-such-library-row'})
    check(programs.load(storage.get_program(rid2))['unresolved'] is True, 'a dangling pointer is unresolved too')
    r = _http('mom', 'GET', f"/api/programs/{rid2}/footprint")
    check(r.status_code == 200, f'and answers: {r.status_code}')
    ids3 = _library(title='Piano for everyone')
    res = programs.rebind(rid2, ids3['L'], dict(MOM))
    check(res.get('status') in ('success', 'ok'), f'Pick a program rebinds it: {res}')
    loaded = programs.load(storage.get_program(rid2))
    check(loaded['unresolved'] is False and loaded['title'] == 'Piano for everyone'
          and storage.get_program(rid2)['library_id'] == ids3['L'], f'bound again: {loaded.get("title")}')
    check(_current(rid2) == ids3['A'] and not (_progress(rid2).get('lessons') or {}),
          f'progress starts over on the new program: {_progress(rid2)}')
    check(len(_live_commitments(rid2)) == 3, 'and its time was never released')


def _corrupt_raw(lid, fields):
    """Write a malformed value past the storage door's own checks, as a damaged file would."""
    table = getattr(storage, 'library_programs_table', None)
    if table is not None:
        table.update(fields, storage.Query().id == lid)
    else:
        storage.update_library_program(lid, fields)


def scenario_a_corrupted_library_row_reads_unresolved():
    """Review Focus 3, the corrupted half: the row is there but its curriculum cannot be read."""
    _fresh()
    project = _project('kid')

    def orphan_lesson(ids):
        lessons = [dict(l, phase_id='no-such-phase') if l['id'] == ids['A'] else l
                   for l in storage.get_library_program(ids['L'])['lessons']]
        _corrupt_raw(ids['L'], {'lessons': lessons})
    for what, corrupt in (('a lesson in no phase', orphan_lesson),
                          ('lessons that are not a list', lambda ids: _corrupt_raw(ids['L'], {'lessons': 'not a list'}))):
        ids = _library()
        rid = _run(ids, project=project)
        _approve(rid)
        corrupt(ids)
        loaded = programs.load(storage.get_program(rid))
        check(loaded['unresolved'] is True and loaded['phases'] == [], f'{what}: unresolved, never half a curriculum: {loaded}')
        windows = _windows(rid, MON)
        check(len(windows) == 1 and not windows[0].get('steps') and not windows[0].get('lesson_id'),
              f'{what}: a neutral window that still holds the time: {windows}')
        for path in ('/api/programs', f"/api/projects/{project['id']}", '/api/practice-windows',
                     f'/api/programs/{rid}/footprint', '/api/commitments'):
            r = _http('mom', 'GET', path)
            check(r.status_code == 200, f'{what}: {path} answers, never a 500: {r.status_code} {r.text[:200]}')
        check(len(_live_commitments(rid)) == 3, f'{what}: its time stays reserved')


def scenario_a_library_change_invalidates_warm_boards():
    _fresh()
    ids = _library()
    _run(ids)
    spare = _library(title='Learn the recorder')      # no run: the service may delete it

    def digest():
        home_board._ACCESS_DIGEST.clear()
        return home_board._access_input_digest()
    before = digest()
    check(digest() == before, 'the digest is stable while nothing changes')
    # A WARM digest: memoised a moment ago, then the library changes under it.
    warm = home_board._access_input_digest()
    check(warm == before and home_board._ACCESS_DIGEST.get('digest') == warm, 'the digest is memoised')
    _svc().update(ids['L'], {'title': 'Learn the piano'}, dict(AUNT))
    edited = home_board._access_input_digest()
    check(edited != warm, 'an edit through the library service reaches a warm digest at once')
    res = _svc().delete(spare['L'], dict(AUNT))
    check(res.get('status') in ('success', 'ok'), f'the unused row is deleted: {res}')
    removed = home_board._access_input_digest()
    check(removed != edited, 'a removal through the library service reaches a warm digest at once')
    storage.delete_library_program(ids['L'])
    check(digest() != removed, 'a vanished library row changes it too')


# --- Review Focus 1 and 2 -------------------------------------------------------------------

def scenario_edit_during_an_open_lesson():
    """Review Focus 1: a library edit lands while Kate is mid-lesson on the wall."""
    _fresh()
    lib = _svc()
    ids = _library()
    rid = _run(ids, current='A', done={ids['A']: {'done_sessions': 1, 'completed_at': None}})
    _approve(rid)
    opened = _windows(rid, MON, viewer=KID)[0]
    check(opened.get('lesson_id') == ids['A'], f'the wall opened lesson A: {opened}')
    lib.order_lessons(ids['L'], [ids[k] for k in 'ADBCE'], dict(AUNT))
    lib.update_lesson(ids['L'], ids['A'], {'steps': ['Sit tall (edited)']}, dict(AUNT))
    lib.update_lesson(ids['L'], ids['D'], {'steps': ['Both hands (edited)']}, dict(AUNT))
    one = programs.lesson_for(storage.get_program(rid), MON)
    check(one['lesson_id'] == ids['A'] and one['steps'] == ['Sit tall (edited)'],
          f'the open lesson is still A, with its edited steps: {one}')
    programs.step_bookmark(rid, 'next')
    check(_current(rid) == ids['D'], 'meanwhile a parent tapped Next on the run')
    r = _http('kid', 'POST', f'/api/programs/{rid}/session',
              json={'lesson_id': opened['lesson_id'], 'variant_label': opened.get('variant_label') or '',
                    'slot_date': MON.isoformat(), 'minutes': 20})
    check(r.status_code == 200 and r.json().get('status') == 'success', f'the wall completes: {r.status_code} {r.text[:200]}')
    check(_completed(rid, ids['A']) and _count(rid, ids['A']) == 2 and not _count(rid, ids['D']),
          f'the lesson it opened was credited, not the current one: {_progress(rid)}')
    nxt = _windows(rid, WED)[0]
    check(nxt.get('lesson_id') == ids['D'] and nxt['steps'] == ['Both hands (edited)'],
          f'the next window picks up the edited steps: {nxt}')


def scenario_two_runs_same_program():
    """Review Focus 2: Kate and Sam on one program, different phases, the same evening."""
    _fresh()
    ids = _library()
    kate = _run(ids, member='kid', current='A', project=_project('kid', title="Kate's piano"))
    sam = _run(ids, member='sib', current='C', project=_project('sib', title="Sam's piano"),
               phases={ids['P1']: {'milestone_hit_at': time.time()}}, done=_done(ids, 'A', 'B', 'D'))
    _approve(kate, [{'day': 0, 'time_start': '17:00'}])
    _approve(sam, [{'day': 0, 'time_start': '18:00'}])
    wk, ws = _windows(kate, MON), _windows(sam, MON)
    check(len(wk) == 1 and len(ws) == 1, f'one window each: {wk} {ws}')
    check(wk[0]['lesson_id'] == ids['A'] and wk[0]['steps'] == ['Sit tall', 'Find middle C'] and wk[0]['member_id'] == 'kid',
          f"Kate's window is Kate's lesson: {wk[0]}")
    check(ws[0]['lesson_id'] == ids['C'] and ws[0]['steps'] == ['Right hand only'] and ws[0]['member_id'] == 'sib',
          f"Sam's window is Sam's lesson: {ws[0]}")
    storage.upsert_program_lesson(kate, {'lesson_id': ids['A'], 'variant_label': ''}, {'scenes': _say('Kate words.')})
    check(storage.get_program_lesson(sam, {'lesson_id': ids['A'], 'variant_label': ''}) is None
          and storage.get_program_lesson(sam, {'lesson_id': ids['C'], 'variant_label': ''}) is None,
          "Kate's script never reaches Sam's run")
    at_five = programs.due_practice_pushes(now=datetime.datetime.combine(MON, datetime.time(17, 5)))
    check([p['program_id'] for p in at_five] == [kate] and at_five[0]['steps'] == ['Sit tall', 'Find middle C'],
          f"Kate's push carries Kate's lesson: {at_five}")
    at_six = programs.due_practice_pushes(now=datetime.datetime.combine(MON, datetime.time(18, 5)))
    check([p['program_id'] for p in at_six] == [sam] and at_six[0]['steps'] == ['Right hand only'],
          f"Sam's push carries Sam's lesson: {at_six}")
    before = _progress(sam)
    programs.log_session(kate)
    check(_progress(sam) == before and _count(kate, ids['A']) == 1, "Kate's practice moves only Kate's run")
    _svc().update_lesson(ids['L'], ids['C'], {'steps': ['Right hand, slowly']}, dict(AUNT))
    check(_windows(sam, MON)[0]['steps'] == ['Right hand, slowly'] and _windows(kate, MON)[0]['steps'] == ['Sit tall', 'Find middle C'],
          'one library edit reaches the run on that lesson and only it')


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
